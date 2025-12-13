"""
Phase 2 Configuration - Capital Protection → Edge Compounding

Feature-flagged upgrades with shadow mode, statistical promotion gates,
and comprehensive risk controls. All gates log WHY they pass/fail.
"""

from dataclasses import dataclass, field
from typing import Dict, Optional, Tuple


@dataclass
class Phase2Config:
    """Phase 2 feature flags and risk parameters."""
    
    # ============= MODE & GATING =============
    shadow_mode: bool = False
    min_snapshots_for_throttle: int = 10
    promotion_gate_required_hours: int = 24
    promotion_gate_min_trades: int = 50
    
    # ============= RISK LIMITS =============
    max_leverage_live: float = 2.0
    max_leverage_shadow: float = 5.0
    kelly_position_size_cap: float = 0.5
    per_trade_risk_bps_cap: float = 25
    daily_loss_kill_switch_bps: float = 150
    
    # ============= VOLATILITY REGIME =============
    vol_baseline_annual_pct: float = 25.0
    vol_revalidation_lookback_days: int = 30
    vol_smooth_alpha: float = 0.3
    
    # ============= FILTERS =============
    mtf_confirm_required: bool = True
    mtf_timeframes: Tuple[str, str] = ("1m", "15m")
    mtf_adaptive_relaxation: bool = True
    mtf_relax_block_threshold_pct: float = 95.0
    mtf_relax_min_hours: int = 6
    mtf_relax_policy: str = "require_1m_strong+15m_neutral"
    
    # ============= PROMOTION GATES =============
    min_wilson_winrate_vs_baseline_diff: float = 0.03
    bootstrap_pnl_ci_excludes_zero: bool = True
    min_sortino_threshold: float = 0.3
    min_sharpe_threshold: float = 0.2
    max_slippage_bps: float = 8.0
    
    # ============= BUDGET ALLOCATOR =============
    per_symbol_budget_bps: Dict[str, float] = field(default_factory=dict)
    symbol_block_min_trades: int = 50
    symbol_block_winrate_threshold: float = 0.35
    
    # ============= LOGGING & AUDIT =============
    log_block_reasons: bool = True
    log_promotion_fail_reasons: bool = True
    telemetry_emit_interval_sec: int = 60


def default_phase2_config() -> Phase2Config:
    """Create default Phase 2 configuration."""
    cfg = Phase2Config()
    cfg.per_symbol_budget_bps = {
        # Live Trading (6 symbols)
        "BTCUSDT": 120,   # 1.2% of portfolio max
        "ETHUSDT": 120,
        "SOLUSDT": 80,    # 0.8% of portfolio max
        "AVAXUSDT": 60,
        "DOTUSDT": 60,
        "TRXUSDT": 60,
        # Previously Shadow (5 symbols) - Now Live
        "XRPUSDT": 80,
        "ADAUSDT": 60,
        "DOGEUSDT": 60,
        "BNBUSDT": 80,
        "MATICUSDT": 60
    }
    return cfg


# Global config instance
_phase2_config: Optional[Phase2Config] = None


def get_phase2_config() -> Phase2Config:
    """Get or create Phase 2 config singleton."""
    global _phase2_config
    if _phase2_config is None:
        _phase2_config = default_phase2_config()
    return _phase2_config


def set_phase2_config(cfg: Phase2Config):
    """Set Phase 2 config (for testing)."""
    global _phase2_config
    _phase2_config = cfg
