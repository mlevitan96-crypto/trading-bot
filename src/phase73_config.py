"""
Phase 7.3 Configuration
Self-tuning execution controls with dynamic relaxation and min-hold autotune
"""

from dataclasses import dataclass, field
from typing import Dict, Tuple


@dataclass
class Phase73Config:
    base_relax_pct_stable: Dict[str, float] = field(default_factory=lambda: {
        "majors": 0.03,
        "l1s": 0.05, 
        "experimental": 0.00
    })
    
    relax_bounds: Dict[str, Tuple[float, float]] = field(default_factory=lambda: {
        "majors": (0.01, 0.06),
        "l1s": (0.02, 0.08),
        "experimental": (0.00, 0.03)
    })
    
    relax_step_per_hour: float = 0.005
    
    target_exec_rate_min: float = 0.10
    target_rr_min: float = 0.90
    
    min_hold_bounds_sec: Tuple[int, int] = (120, 360)
    min_hold_base_sec: int = 180
    min_hold_adjust_step_sec: int = 30
    
    shorts_min_wr: float = 0.48
    shorts_min_pnl_usd: float = 0.0
    shorts_min_rr_skew: float = 1.05
    shorts_slippage_p75_cap_bps: float = 12.0
    shorts_window_trades: int = 30
    suppress_shorts_until_profitable: bool = True
    
    fee_summary_window_hours: int = 24
    controller_interval_sec: int = 3600


def default_phase73_cfg() -> Phase73Config:
    return Phase73Config()
