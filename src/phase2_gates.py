"""
Phase 2 Promotion Gates - Statistical validation before going live.

Implements Wilson confidence intervals, bootstrap PnL CI, Sharpe/Sortino
thresholds, and comprehensive gate failure logging.
"""

from dataclasses import dataclass
from typing import List, Optional, Tuple
import math
import random


@dataclass
class SignalDecision:
    """Decision on whether to allow a signal."""
    allowed: bool
    reason: Optional[str] = None
    relaxed_policy_used: bool = False
    audit_trail: Optional[dict] = None


@dataclass
class ThrottleState:
    """Risk-adjusted performance throttle state."""
    sharpe: Optional[float] = None
    sortino: Optional[float] = None
    snapshots_collected: int = 0
    active: bool = False


@dataclass
class PromotionMetrics:
    """Metrics required for shadow→live promotion."""
    hours_observed: int
    trades: int
    wilson_winrate_lb_vs_baseline: float
    pnl_bootstrap_ci_low: float
    pnl_bootstrap_ci_high: float
    sortino: float
    sharpe: float
    slippage_bps_avg: float


@dataclass
class PromotionDecision:
    """Decision on whether to promote shadow to live."""
    promote: bool
    fail_reasons: List[str]


def wilson_score_interval(successes: int, trials: int, confidence: float = 0.95) -> Tuple[float, float]:
    """
    Calculate Wilson score confidence interval for win rate.
    
    More accurate than normal approximation for small sample sizes.
    Returns (lower_bound, upper_bound).
    """
    if trials == 0:
        return (0.0, 0.0)
    
    p_hat = successes / trials
    z = 1.96 if confidence == 0.95 else 1.645  # z-score for confidence level
    
    denominator = 1 + (z**2 / trials)
    centre = (p_hat + (z**2 / (2 * trials))) / denominator
    margin = (z / denominator) * math.sqrt((p_hat * (1 - p_hat) / trials) + (z**2 / (4 * trials**2)))
    
    return (max(0.0, centre - margin), min(1.0, centre + margin))


def bootstrap_pnl_ci(pnl_values: List[float], n_bootstrap: int = 1000, confidence: float = 0.95) -> Tuple[float, float]:
    """
    Calculate bootstrap confidence interval for PnL.
    
    Resample PnL values with replacement and compute percentiles.
    Returns (lower_bound, upper_bound).
    """
    if not pnl_values:
        return (0.0, 0.0)
    
    bootstrap_means = []
    for _ in range(n_bootstrap):
        sample = random.choices(pnl_values, k=len(pnl_values))
        bootstrap_means.append(sum(sample) / len(sample))
    
    bootstrap_means.sort()
    alpha = 1 - confidence
    lower_idx = int(alpha / 2 * n_bootstrap)
    upper_idx = int((1 - alpha / 2) * n_bootstrap)
    
    return (bootstrap_means[lower_idx], bootstrap_means[upper_idx])


def evaluate_throttle(throttle: ThrottleState, cfg) -> bool:
    """
    Activate throttle once enough snapshots exist and metrics meet thresholds.
    
    Args:
        throttle: Current throttle state
        cfg: Phase2Config
        
    Returns:
        True if throttle is active and metrics are healthy
    """
    if throttle.snapshots_collected < cfg.min_snapshots_for_throttle:
        return False
    
    sharpe_ok = throttle.sharpe is not None and throttle.sharpe >= cfg.min_sharpe_threshold
    sortino_ok = throttle.sortino is not None and throttle.sortino >= cfg.min_sortino_threshold
    
    return sharpe_ok and sortino_ok


def promotion_gate(pm: PromotionMetrics, baseline_winrate: float, cfg) -> PromotionDecision:
    """
    Comprehensive promotion gate with statistical validation.
    
    Only promotes shadow→live when ALL gates pass:
    1. Minimum observation time
    2. Minimum trade count
    3. Wilson winrate confidence interval exceeds baseline
    4. Bootstrap PnL CI excludes zero (positive edge)
    5. Sortino ratio above threshold
    6. Sharpe ratio above threshold
    7. Slippage below threshold
    
    Args:
        pm: Promotion metrics from shadow trading
        baseline_winrate: Current live system win rate
        cfg: Phase2Config
        
    Returns:
        PromotionDecision with promote flag and failure reasons
    """
    reasons = []
    
    # Gate 1: Observation time
    if pm.hours_observed < cfg.promotion_gate_required_hours:
        reasons.append(f"insufficient_hours:{pm.hours_observed}<{cfg.promotion_gate_required_hours}")
    
    # Gate 2: Trade count
    if pm.trades < cfg.promotion_gate_min_trades:
        reasons.append(f"insufficient_trades:{pm.trades}<{cfg.promotion_gate_min_trades}")
    
    # Gate 3: Wilson confidence interval for win rate
    if pm.wilson_winrate_lb_vs_baseline < cfg.min_wilson_winrate_vs_baseline_diff:
        reasons.append(f"wilson_lb_fail:{pm.wilson_winrate_lb_vs_baseline:.3f}<{cfg.min_wilson_winrate_vs_baseline_diff}")
    
    # Gate 4: Bootstrap PnL CI must exclude zero
    if cfg.bootstrap_pnl_ci_excludes_zero:
        if not (pm.pnl_bootstrap_ci_low > 0 or pm.pnl_bootstrap_ci_high < 0):
            reasons.append(f"pnl_ci_includes_zero:[{pm.pnl_bootstrap_ci_low:.2f},{pm.pnl_bootstrap_ci_high:.2f}]")
    
    # Gate 5: Sortino threshold
    if pm.sortino < cfg.min_sortino_threshold:
        reasons.append(f"sortino_fail:{pm.sortino:.3f}<{cfg.min_sortino_threshold}")
    
    # Gate 6: Sharpe threshold
    if pm.sharpe < cfg.min_sharpe_threshold:
        reasons.append(f"sharpe_fail:{pm.sharpe:.3f}<{cfg.min_sharpe_threshold}")
    
    # Gate 7: Slippage threshold
    if pm.slippage_bps_avg > cfg.max_slippage_bps:
        reasons.append(f"slippage_fail:{pm.slippage_bps_avg:.1f}>{cfg.max_slippage_bps}")
    
    return PromotionDecision(
        promote=(len(reasons) == 0),
        fail_reasons=reasons
    )


def allowed_leverage(shadow_mode: bool, throttle_active: bool, cfg) -> float:
    """
    Determine allowed leverage based on mode and throttle status.
    
    Conservative policy: cap leverage until throttle proves edge.
    
    Args:
        shadow_mode: True if in shadow mode
        throttle_active: True if risk throttle is active and healthy
        cfg: Phase2Config
        
    Returns:
        Maximum allowed leverage
    """
    if shadow_mode:
        return cfg.max_leverage_shadow
    
    # Live mode: conservative until proven
    if throttle_active:
        return min(cfg.max_leverage_shadow, 5.0)
    else:
        return cfg.max_leverage_live
