"""
Optimization Enhancements - Phase 1 Quick Wins

Adds two high-impact optimizations:
1. Volatility-weighted Kelly sizing (automatically reduces size during high volatility)
2. Sharpe/Sortino throttle (reduces size during poor risk-adjusted performance)

Integration with existing bot:
- Works with logs/performance.json and logs/pnl_hourly.json
- Adapts to Stable/Volatile/Trending/Choppy regimes
- Compatible with both spot (USD) and futures (margin) sizing
"""

import json
import math
from pathlib import Path
from typing import Tuple, Optional, Dict, List

LOGS_DIR = Path("logs")
PERFORMANCE_FILE = LOGS_DIR / "performance.json"
PNL_HOURLY_FILE = LOGS_DIR / "pnl_hourly.json"

def kelly_fraction(p_win: float, rr: float) -> float:
    """
    Calculate optimal Kelly fraction.
    
    Kelly f* = p - (1-p)/RR
    
    Args:
        p_win: Win rate (0.0 to 1.0)
        rr: Risk-reward ratio (average win / average loss)
    
    Returns:
        Optimal fraction of bankroll to risk (bounded 0-1)
    """
    if rr <= 0 or p_win <= 0:
        return 0.0
    
    f = p_win - (1 - p_win) / rr
    return max(0.0, min(1.0, f))


def volatility_weighted_kelly(
    bankroll: float,
    p_win: float,
    rr: float,
    current_vol: float,
    kelly_scale: float = 0.25,
    vol_reference: float = 0.25,
    min_size: float = 100.0
) -> Tuple[float, Dict]:
    """
    Calculate position size using volatility-weighted Kelly Criterion.
    
    Key insight: Reduce size when volatility is high to avoid whipsaws.
    vol_weight = vol_reference / current_vol
    
    Args:
        bankroll: Available capital (USD for spot, margin for futures)
        p_win: Historical win rate (0.0 to 1.0)
        rr: Risk-reward ratio
        current_vol: Current realized volatility (e.g., 0.30 = 30%)
        kelly_scale: Kelly fraction multiplier (0.25 = quarter Kelly)
        vol_reference: Reference volatility level (0.25 = 25%)
        min_size: Minimum position size
    
    Returns:
        (position_size_usd, metadata_dict)
    """
    # Base Kelly calculation
    kf = kelly_fraction(p_win, rr)
    
    # Volatility adjustment: downsize when vol > reference
    if current_vol is None or current_vol <= 0:
        vol_weight = 1.0
    else:
        # If current vol is 2x reference, reduce size by 50%
        vol_weight = max(0.3, min(2.0, vol_reference / current_vol))
    
    # Effective fraction with volatility weighting
    f_effective = kf * kelly_scale * vol_weight
    f_effective = max(0.02, min(0.50, f_effective))  # Bound to 2%-50%
    
    # Calculate dollar size
    position_size = bankroll * f_effective
    position_size = max(min_size, position_size)
    
    metadata = {
        "kelly_fraction": round(kf, 4),
        "kelly_scale": kelly_scale,
        "vol_weight": round(vol_weight, 3),
        "f_effective": round(f_effective, 4),
        "bankroll": bankroll,
        "position_size": round(position_size, 2),
        "current_vol": round(current_vol, 4) if current_vol else None,
        "vol_reference": vol_reference
    }
    
    return position_size, metadata


def parse_recent_performance(max_snapshots: int = 168) -> List[Dict]:
    """
    Parse recent hourly P&L snapshots.
    
    Args:
        max_snapshots: Number of recent snapshots to load (default 168 = 7 days)
    
    Returns:
        List of performance snapshots
    """
    if not PNL_HOURLY_FILE.exists():
        return []
    
    try:
        with open(PNL_HOURLY_FILE) as f:
            data = json.load(f)
        
        # Get recent snapshots
        snapshots = data.get("snapshots", [])
        return snapshots[-max_snapshots:] if len(snapshots) > max_snapshots else snapshots
    except:
        return []


def calculate_sharpe_sortino(snapshots: List[Dict], lookback_hours: int = 168) -> Tuple[float, float]:
    """
    Calculate rolling Sharpe and Sortino ratios from hourly snapshots.
    
    Args:
        snapshots: List of hourly P&L snapshots
        lookback_hours: Number of hours to look back (default 168 = 7 days)
    
    Returns:
        (sharpe_ratio, sortino_ratio)
    """
    if not snapshots or len(snapshots) < 10:
        return (0.0, 0.0)
    
    # Take last N hours
    window = snapshots[-lookback_hours:] if len(snapshots) > lookback_hours else snapshots
    
    # Extract P&L changes between snapshots
    returns = []
    for i in range(1, len(window)):
        prev_pnl = float(window[i-1].get("total_pnl", 0))
        curr_pnl = float(window[i].get("total_pnl", 0))
        returns.append(curr_pnl - prev_pnl)
    
    if not returns or len(returns) < 5:
        return (0.0, 0.0)
    
    # Calculate mean and standard deviation
    mean_return = sum(returns) / len(returns)
    variance = sum((r - mean_return) ** 2 for r in returns) / len(returns)
    std_dev = math.sqrt(variance)
    
    # Calculate downside deviation (only negative returns)
    downside_returns = [min(0.0, r - mean_return) for r in returns]
    downside_var = sum(d ** 2 for d in downside_returns) / len(downside_returns)
    downside_std = math.sqrt(downside_var)
    
    # Sharpe ratio
    sharpe = mean_return / std_dev if std_dev > 1e-9 else 0.0
    
    # Sortino ratio (uses downside deviation only)
    sortino = mean_return / downside_std if downside_std > 1e-9 else 0.0
    
    return (round(sharpe, 3), round(sortino, 3))


def risk_adjusted_throttle(sharpe: float, sortino: float) -> float:
    """
    Calculate position sizing throttle based on risk-adjusted performance.
    
    Throttle ranges:
    - Poor performance (Sharpe < 0.2): 0.70x (reduce size 30%)
    - Weak performance (Sharpe < 0.4): 0.85x (reduce size 15%)
    - Normal performance: 1.0x (no change)
    - Strong performance (Sharpe > 0.8): 1.10x (increase size 10%)
    
    Args:
        sharpe: Sharpe ratio
        sortino: Sortino ratio
    
    Returns:
        Throttle multiplier (0.5 to 1.2)
    """
    # Poor risk-adjusted returns → defensive sizing
    if sharpe < 0.2 or sortino < 0.2:
        return 0.70
    
    # Weak but positive → slight reduction
    if sharpe < 0.4 or sortino < 0.4:
        return 0.85
    
    # Strong risk-adjusted returns → modest increase
    if sharpe > 0.8 and sortino > 0.8:
        return 1.10
    
    # Normal range → no adjustment
    return 1.0


def get_sharpe_sortino_throttle(lookback_hours: int = 168) -> Tuple[float, Dict]:
    """
    Get current Sharpe/Sortino throttle based on recent performance.
    
    Args:
        lookback_hours: Hours to look back (default 168 = 7 days)
    
    Returns:
        (throttle, metadata_dict)
    """
    snapshots = parse_recent_performance(max_snapshots=lookback_hours)
    
    if not snapshots:
        # No data → neutral throttle
        return (1.0, {
            "sharpe": 0.0,
            "sortino": 0.0,
            "throttle": 1.0,
            "reason": "no_data"
        })
    
    sharpe, sortino = calculate_sharpe_sortino(snapshots, lookback_hours)
    throttle = risk_adjusted_throttle(sharpe, sortino)
    
    metadata = {
        "sharpe": sharpe,
        "sortino": sortino,
        "throttle": throttle,
        "snapshots_analyzed": len(snapshots),
        "lookback_hours": lookback_hours
    }
    
    return (throttle, metadata)


def apply_optimization_enhancements(
    base_size: float,
    bankroll: float,
    p_win: float,
    rr: float,
    current_vol: Optional[float],
    use_vol_weighting: bool = True,
    use_sharpe_throttle: bool = True,
    kelly_scale: float = 0.25,
    min_size: float = 100.0,
    enforce_min: bool = True
) -> Tuple[float, Dict]:
    """
    Apply both optimizations to position sizing.
    
    This is the main integration point that combines:
    1. Volatility-weighted Kelly sizing
    2. Sharpe/Sortino throttle
    
    Args:
        base_size: Initial position size (from existing logic)
        bankroll: Available capital
        p_win: Historical win rate
        rr: Risk-reward ratio
        current_vol: Current volatility (optional)
        use_vol_weighting: Enable volatility weighting
        use_sharpe_throttle: Enable Sharpe/Sortino throttle
        kelly_scale: Kelly fraction scale (0.25 = quarter Kelly)
        min_size: Minimum position size
        enforce_min: If True, enforce min_size; if False, allow smaller (for budget-capped scenarios)
    
    Returns:
        (optimized_size, combined_metadata)
    """
    metadata = {
        "base_size": base_size,
        "vol_weighted": use_vol_weighting,
        "sharpe_throttled": use_sharpe_throttle
    }
    
    final_size = base_size
    
    # Step 1: Volatility-weighted Kelly (if enabled)
    if use_vol_weighting and current_vol is not None:
        kelly_size, kelly_meta = volatility_weighted_kelly(
            bankroll=bankroll,
            p_win=p_win,
            rr=rr,
            current_vol=current_vol,
            kelly_scale=kelly_scale,
            min_size=min_size
        )
        
        # Take minimum of base size and vol-weighted Kelly
        final_size = min(final_size, kelly_size)
        metadata["kelly"] = kelly_meta
    
    # Step 2: Sharpe/Sortino throttle (if enabled)
    if use_sharpe_throttle:
        throttle, throttle_meta = get_sharpe_sortino_throttle()
        final_size = final_size * throttle
        metadata["throttle"] = throttle_meta
    
    # Ensure minimum size (only if enforce_min=True)
    if enforce_min:
        final_size = max(min_size, final_size)
    
    metadata["final_size"] = round(final_size, 2)
    
    return final_size, metadata


# Convenience functions for spot and futures

def optimize_spot_size(
    base_size: float,
    portfolio_value: float,
    win_rate: float,
    avg_rr: float,
    volatility: Optional[float] = None
) -> Tuple[float, Dict]:
    """
    Optimize spot position size.
    
    Args:
        base_size: Base position size from existing logic
        portfolio_value: Current portfolio value
        win_rate: Historical win rate (0.42 default)
        avg_rr: Average risk-reward ratio (1.0 default)
        volatility: Current market volatility (optional)
    
    Returns:
        (optimized_size, metadata)
    """
    return apply_optimization_enhancements(
        base_size=base_size,
        bankroll=portfolio_value,
        p_win=win_rate,
        rr=avg_rr,
        current_vol=volatility,
        kelly_scale=0.25,  # Quarter Kelly for spot
        min_size=100.0
    )


def optimize_futures_size(
    base_margin: float,
    available_margin: float,
    win_rate: float,
    avg_rr: float,
    volatility: Optional[float] = None
) -> Tuple[float, Dict]:
    """
    Optimize futures margin allocation.
    
    CRITICAL: Does NOT enforce min_size to respect allocator budgets.
    The allocator may want to allocate $0 or very small amounts based on risk controls.
    
    Args:
        base_margin: Base margin from existing logic
        available_margin: Available margin capital
        win_rate: Historical win rate
        avg_rr: Average risk-reward ratio
        volatility: Current market volatility (optional)
    
    Returns:
        (optimized_margin, metadata)
    """
    return apply_optimization_enhancements(
        base_size=base_margin,
        bankroll=available_margin,
        p_win=win_rate,
        rr=avg_rr,
        current_vol=volatility,
        kelly_scale=0.15,  # More conservative for leveraged futures
        min_size=50.0,
        enforce_min=False  # CRITICAL: Don't force min size for futures - respect allocator budgets
    )
