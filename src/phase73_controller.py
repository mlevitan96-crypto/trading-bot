"""
Phase 7.3 Self-Tuning Execution Controller
Dynamic relaxation adjustment and min-hold autotune
"""

import time
import json
import os
from typing import Dict, Optional
from datetime import datetime, timedelta
from phase73_config import Phase73Config, default_phase73_cfg
from phase72_tiers import tier_for_symbol


class Phase73Controller:
    def __init__(self, config: Optional[Phase73Config] = None):
        self.config = config or default_phase73_cfg()
        self.relax_pct_stable: Dict[str, float] = self.config.base_relax_pct_stable.copy()
        self.min_hold_symbol: Dict[str, int] = {}
        self.last_controller_run = 0
        self.state_file = "logs/phase73_state.json"
        self._load_state()
    
    def _load_state(self):
        if os.path.exists(self.state_file):
            try:
                with open(self.state_file, 'r') as f:
                    state = json.load(f)
                    self.relax_pct_stable = state.get("relax_pct_stable", self.relax_pct_stable)
                    self.min_hold_symbol = state.get("min_hold_symbol", {})
                    self.last_controller_run = state.get("last_controller_run", 0)
            except Exception:
                pass
    
    def _save_state(self):
        try:
            os.makedirs("logs", exist_ok=True)
            state = {
                "relax_pct_stable": self.relax_pct_stable,
                "min_hold_symbol": self.min_hold_symbol,
                "last_controller_run": self.last_controller_run
            }
            temp_file = f"{self.state_file}.tmp"
            with open(temp_file, 'w') as f:
                json.dump(state, f, indent=2)
            os.replace(temp_file, self.state_file)
        except Exception:
            pass
    
    def current_relax_pct_stable(self, tier: str) -> float:
        return self.relax_pct_stable.get(tier, 0.0)
    
    def set_relax_pct_stable(self, tier: str, value: float):
        lo, hi = self.config.relax_bounds.get(tier, (0.0, 0.06))
        self.relax_pct_stable[tier] = max(lo, min(hi, value))
        self._save_state()
    
    def current_min_hold(self, symbol: str) -> int:
        return self.min_hold_symbol.get(symbol, self.config.min_hold_base_sec)
    
    def set_min_hold(self, symbol: str, value: int):
        lo, hi = self.config.min_hold_bounds_sec
        self.min_hold_symbol[symbol] = max(lo, min(hi, int(value)))
        self._save_state()
    
    def relaxed_threshold(self, symbol: str, regime_name: str, base_threshold: float) -> float:
        tier = tier_for_symbol(symbol)
        thr = base_threshold
        if regime_name.lower() == "stable":
            thr = thr * (1.0 - self.current_relax_pct_stable(tier))
        return thr
    
    def controller_adjust_relaxation(self, telemetry):
        for tier in ["majors", "l1s", "experimental"]:
            exec_rate = telemetry.get_execution_rate_24h_tier(tier)
            rr = telemetry.get_realized_rr_24h_tier(tier)
            curr = self.current_relax_pct_stable(tier)
            
            if exec_rate < self.config.target_exec_rate_min:
                new_val = curr + self.config.relax_step_per_hour
                self.set_relax_pct_stable(tier, new_val)
                print(f"ℹ️  PHASE73: {tier} relax UP: {curr:.3f} → {self.current_relax_pct_stable(tier):.3f} (exec_rate={exec_rate:.2%})")
            elif rr is not None and rr < self.config.target_rr_min:
                new_val = curr - self.config.relax_step_per_hour
                self.set_relax_pct_stable(tier, new_val)
                print(f"ℹ️  PHASE73: {tier} relax DOWN: {curr:.3f} → {self.current_relax_pct_stable(tier):.3f} (rr={rr:.2f})")
            else:
                print(f"ℹ️  PHASE73: {tier} relax HOLD: {curr:.3f} (exec_rate={exec_rate:.2%}, rr={rr if rr else 'N/A'})")
        
        self.last_controller_run = time.time()
        self._save_state()
    
    def autotune_min_hold(self, telemetry, symbols):
        for symbol in symbols:
            vol = telemetry.get_realized_vol_24h(symbol)
            liq = telemetry.get_liquidity_score_24h(symbol)
            curr = self.current_min_hold(symbol)
            target = self.config.min_hold_base_sec
            
            if vol is not None and liq is not None:
                if vol >= 0.6 or liq <= 0.4:
                    target = curr + self.config.min_hold_adjust_step_sec
                elif vol <= 0.3 and liq >= 0.7:
                    target = curr - self.config.min_hold_adjust_step_sec
                else:
                    target = curr
                
                if target != curr:
                    self.set_min_hold(symbol, target)
                    print(f"ℹ️  PHASE73: {symbol} min-hold: {curr}s → {self.current_min_hold(symbol)}s (vol={vol:.2f}, liq={liq:.2f})")
        
        self._save_state()
    
    def should_run_controller(self) -> bool:
        return (time.time() - self.last_controller_run) >= self.config.controller_interval_sec
    
    def get_status(self) -> Dict:
        return {
            "relax_pct_stable": self.relax_pct_stable,
            "min_hold_symbol": self.min_hold_symbol,
            "last_controller_run": self.last_controller_run,
            "next_run_in_sec": max(0, self.config.controller_interval_sec - (time.time() - self.last_controller_run))
        }


_phase73_instance = None

def get_phase73_controller() -> Phase73Controller:
    global _phase73_instance
    if _phase73_instance is None:
        _phase73_instance = Phase73Controller()
    return _phase73_instance
