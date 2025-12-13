"""
Phase 3 Configuration - Edge Compounding & Disciplined Scale

Feature flags and parameters for:
- Adaptive filter relaxation
- Per-ticker bandits & attribution
- Correlation & exposure controls
- Drawdown-aware throttle
- Funding cost model
- Missed opportunity replay
- Capital ramp
"""

from dataclasses import dataclass, field
from typing import Dict, List


@dataclass
class Phase3Config:
    """Phase 3: Edge Compounding configuration."""
    
    adaptive_relax_enable: bool = True
    choke_block_threshold_pct: float = 95.0
    relax_window_hours: int = 6
    relax_policies: List[str] = field(default_factory=lambda: [
        "require_1m_strong+15m_neutral",
        "require_regime_in_favor+1m_ok",
        "allow_divergence_if_attribution_positive"
    ])
    
    ramp_stages: List[Dict] = field(default_factory=lambda: [
        {"duration_hours": 12, "max_leverage": 1.0, "note": "Phase 3 stage 1"},
        {"duration_hours": 24, "max_leverage": 1.5, "note": "Stage 2 if metrics hold"},
        {"duration_hours": 24, "max_leverage": 2.0, "note": "Stage 3 disciplined cap"},
        {"duration_hours": 24, "max_leverage": 3.0, "note": "Optional scale if Sharpe/Sortino + attribution strong"},
    ])
    ramp_hold_sharpe: float = 0.25
    ramp_hold_sortino: float = 0.3
    ramp_max_drawdown_bps: float = 300.0
    
    bandit_enable: bool = True
    bandit_alpha: float = 0.3
    attribution_decay: float = 0.97
    min_attribution_strength: float = 0.15
    
    corr_lookback_hours: int = 72
    max_theme_exposure_bps: Dict[str, float] = field(default_factory=lambda: {
        "majors": 250,
        "L1s": 200,
        "alts": 150
    })
    cross_symbol_corr_block_threshold: float = 0.8
    
    dd_throttle_enable: bool = True
    dd_soft_block_bps: float = 150.0
    dd_size_reduction_pct: float = 0.4
    
    funding_cost_model_enable: bool = True
    funding_cost_bps_cap: float = 12.0
    
    mor_enable: bool = True
    mor_lookback_hours: int = 48
    mor_replay_limit_per_day: int = 20
    
    promotion_requires_positive_attribution: bool = True
    promotion_min_expectancy_usd: float = 0.0
    promotion_min_edge_consistency_pct: float = 60.0
    
    telemetry_interval_sec: int = 60


_phase3_config = None


def get_phase3_config() -> Phase3Config:
    """Get Phase 3 configuration singleton."""
    global _phase3_config
    if _phase3_config is None:
        _phase3_config = Phase3Config()
    return _phase3_config


def set_phase3_config(cfg: Phase3Config):
    """Override Phase 3 configuration."""
    global _phase3_config
    _phase3_config = cfg
