"""
Phase 7.4 Profit Engine Configuration
Expectancy-driven sizing, pyramiding, and precision exits
"""

from dataclasses import dataclass


@dataclass
class Phase74Config:
    min_expected_value_usd: float = 0.50
    min_ensemble_score: float = 0.52
    ev_window_trades: int = 50
    
    size_ramp_up_pct: float = 0.20
    size_ramp_down_pct: float = 0.25
    max_size_multiplier: float = 2.0
    min_size_multiplier: float = 0.5
    slippage_p75_cap_bps: float = 12.0
    
    pyramid_max_adds: int = 2
    pyramid_trigger_r_multiple: float = 0.6
    pyramid_add_size_fraction: float = 0.33
    pyramid_trailing_tighten_bps: float = 10
    
    trailing_start_r: float = 0.8
    trailing_step_bps: float = 8
    trailing_max_bps: float = 35
    tp_unlock_r: float = 1.2
    tp_widen_factor: float = 1.015
    vol_stop_k: float = 1.8
    time_decay_minutes: int = 45
    time_progress_r_threshold: float = 0.25
    
    prefer_maker_when_queue_advantage: bool = True
    maker_queue_min: float = 0.7
    maker_imbalance_min: float = 0.6
    
    blofin_fee_maker: float = 0.0002
    blofin_fee_taker: float = 0.0006


def default_phase74_cfg() -> Phase74Config:
    return Phase74Config()
