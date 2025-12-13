"""
Phase 7.4 Performance Nudges & Safety Sentinels
Regime-aware optimizations for pyramiding, trailing, and EV gates
"""

import time
from dataclasses import dataclass
from typing import Dict, Optional


@dataclass
class Phase74NudgeConfig:
    ev_gate_default_usd: float = 0.50
    ev_gate_majors_temp_usd: float = 0.35
    ev_auto_revert_rr_threshold: float = 0.90
    ev_temp_duration_hours: int = 48
    
    pyramid_trigger_r_trend: float = 0.50
    pyramid_trigger_r_chop: float = 0.80
    pyramid_add_size_fraction: float = 0.33
    pyramid_max_adds: int = 2
    pyramid_trailing_tighten_bps: float = 10
    
    trailing_start_r_trend: float = 0.70
    trailing_start_r_chop: float = 0.90
    trailing_step_bps_min: int = 6
    trailing_step_bps_max: int = 10
    
    time_decay_minutes_experimental_stable: int = 35
    time_decay_minutes_default: int = 45
    
    maker_queue_min: float = 0.75
    maker_imbalance_min: float = 0.65
    
    fee_maker_rate: float = 0.0002
    fee_taker_rate: float = 0.0006


class Phase74Nudges:
    def __init__(self, config: Phase74NudgeConfig):
        self.config = config
        self._ev_gate_majors_usd = config.ev_gate_default_usd
        self._ev_gate_majors_started_ts: Optional[float] = None
    
    def is_major(self, symbol: str) -> bool:
        return symbol.upper().replace("USDT", "") in {"BTC", "ETH"}
    
    def is_experimental(self, symbol: str) -> bool:
        return symbol.upper().replace("USDT", "") in {
            "DOT", "TRX", "XRP", "ADA", "DOGE", "BNB", "MATIC"
        }
    
    def ev_gate_usd(self, symbol: str) -> float:
        if self.is_major(symbol):
            return self._ev_gate_majors_usd
        return self.config.ev_gate_default_usd
    
    def enable_ev_temp_for_majors(self):
        self._ev_gate_majors_usd = self.config.ev_gate_majors_temp_usd
        self._ev_gate_majors_started_ts = time.time()
        print(f"ℹ️  PHASE74 NUDGES: EV gate for majors temporarily lowered to ${self._ev_gate_majors_usd:.2f}")
    
    def maybe_revert_ev_temp_for_majors(self, realized_rr_24h_majors: Optional[float] = None):
        if self._ev_gate_majors_started_ts is None:
            return
        
        elapsed_h = (time.time() - self._ev_gate_majors_started_ts) / 3600.0
        should_revert = False
        revert_reason = ""
        
        if realized_rr_24h_majors is not None and realized_rr_24h_majors < self.config.ev_auto_revert_rr_threshold:
            should_revert = True
            revert_reason = f"R:R {realized_rr_24h_majors:.2f} < {self.config.ev_auto_revert_rr_threshold}"
        elif elapsed_h >= self.config.ev_temp_duration_hours:
            should_revert = True
            revert_reason = f"duration {elapsed_h:.1f}h exceeded"
        
        if should_revert:
            prev = self._ev_gate_majors_usd
            self._ev_gate_majors_usd = self.config.ev_gate_default_usd
            self._ev_gate_majors_started_ts = None
            print(f"ℹ️  PHASE74 NUDGES: EV gate for majors reverted from ${prev:.2f} to ${self._ev_gate_majors_usd:.2f} ({revert_reason})")
    
    def pyramid_trigger_r(self, regime_name: str) -> float:
        if regime_name.lower() == "trend":
            return self.config.pyramid_trigger_r_trend
        return self.config.pyramid_trigger_r_chop
    
    def trailing_start_r(self, regime_name: str) -> float:
        if regime_name.lower() == "trend":
            return self.config.trailing_start_r_trend
        return self.config.trailing_start_r_chop
    
    def time_decay_minutes_for(self, position: Dict, regime: str) -> int:
        symbol = position.get("symbol", "")
        if self.is_experimental(symbol) and regime.lower() == "stable":
            return self.config.time_decay_minutes_experimental_stable
        return self.config.time_decay_minutes_default
    
    def get_status(self) -> Dict:
        return {
            "ev_gate_majors_usd": self._ev_gate_majors_usd,
            "ev_temp_active": self._ev_gate_majors_started_ts is not None,
            "config": {
                "pyramid_trigger_r_trend": self.config.pyramid_trigger_r_trend,
                "pyramid_trigger_r_chop": self.config.pyramid_trigger_r_chop,
                "trailing_start_r_trend": self.config.trailing_start_r_trend,
                "trailing_start_r_chop": self.config.trailing_start_r_chop,
                "maker_queue_min": self.config.maker_queue_min,
                "maker_imbalance_min": self.config.maker_imbalance_min
            }
        }


def default_phase74_nudge_cfg() -> Phase74NudgeConfig:
    return Phase74NudgeConfig()


_phase74_nudges = None

def get_phase74_nudges() -> Phase74Nudges:
    global _phase74_nudges
    if _phase74_nudges is None:
        _phase74_nudges = Phase74Nudges(default_phase74_nudge_cfg())
    return _phase74_nudges
