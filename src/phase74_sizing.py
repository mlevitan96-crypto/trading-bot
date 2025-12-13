"""
Phase 7.4 Dynamic Sizing Ramp
Scale size based on expectancy and execution quality
"""

import json
import os
from phase74_config import Phase74Config
from phase74_expectancy import get_phase74_expectancy


class Phase74Sizing:
    def __init__(self):
        self.state_file = "logs/phase74_sizing.json"
        self.size_multipliers = {}
        self._load_state()
    
    def _load_state(self):
        if os.path.exists(self.state_file):
            try:
                with open(self.state_file, 'r') as f:
                    data = json.load(f)
                    self.size_multipliers = data.get("size_multipliers", {})
            except Exception:
                pass
    
    def _save_state(self):
        try:
            os.makedirs("logs", exist_ok=True)
            data = {"size_multipliers": self.size_multipliers}
            temp_file = f"{self.state_file}.tmp"
            with open(temp_file, 'w') as f:
                json.dump(data, f, indent=2)
            os.replace(temp_file, self.state_file)
        except Exception:
            pass
    
    def current_size_multiplier(self, symbol: str) -> float:
        return self.size_multipliers.get(symbol, 1.0)
    
    def set_size_multiplier(self, symbol: str, mult: float):
        self.size_multipliers[symbol] = mult
        self._save_state()
    
    def sizing_multiplier(self, symbol: str, config: Phase74Config) -> float:
        expectancy = get_phase74_expectancy()
        
        ev = expectancy.expected_value_usd(symbol, config)
        slip_p75 = expectancy.slippage_p75_bps(symbol, config.ev_window_trades)
        
        mult = self.current_size_multiplier(symbol)
        
        if ev >= config.min_expected_value_usd and slip_p75 <= config.slippage_p75_cap_bps:
            new_mult = min(config.max_size_multiplier, mult * (1.0 + config.size_ramp_up_pct))
            if new_mult != mult:
                print(f"ℹ️  PHASE74: {symbol} sizing UP: {mult:.2f}x → {new_mult:.2f}x (EV=${ev:.2f}, slip={slip_p75:.1f}bps)")
                self.set_size_multiplier(symbol, new_mult)
            return new_mult
        else:
            new_mult = max(config.min_size_multiplier, mult * (1.0 - config.size_ramp_down_pct))
            if new_mult != mult:
                print(f"ℹ️  PHASE74: {symbol} sizing DOWN: {mult:.2f}x → {new_mult:.2f}x (EV=${ev:.2f}, slip={slip_p75:.1f}bps)")
                self.set_size_multiplier(symbol, new_mult)
            return new_mult


_phase74_sizing = None

def get_phase74_sizing() -> Phase74Sizing:
    global _phase74_sizing
    if _phase74_sizing is None:
        _phase74_sizing = Phase74Sizing()
    return _phase74_sizing
