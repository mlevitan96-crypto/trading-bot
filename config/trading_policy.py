"""
Trading Policy Configuration
Defines position sizing limits and risk parameters for the trading bot.

WIN-RATE-BASED SCALING (2025-11-29):
- Base sizing: $200-$1000 (conservative mode, WR < 40%)
- Standard sizing: $300-$1200 (WR 40-50%)
- Aggressive sizing: $400-$1500 (WR > 50%)
- Hot streak sizing: $500-$2000 (WR > 55% AND positive P&L)

Leverage follows same tiers: 5x → 6x → 7x → 8x
"""

TRADING_POLICY = {
    "MIN_POSITION_SIZE_USD": 300,
    "MAX_POSITION_SIZE_USD": 1200,
    "BASE_POSITION_SIZE_USD": 600,
    "CONVICTION_MULTIPLIERS": {
        "high": 1.5,
        "very_high": 2.0,
        "hot_streak": 2.5
    },
    "CONVICTION_THRESHOLDS": {
        "high": 0.60,
        "very_high": 0.70,
        "hot_streak": 0.80
    },
    "MIN_HOLD_SECONDS": 420,
    "PAPER_MODE_POSITION_SCALE": 1.0,
    "LIVE_MODE_POSITION_SCALE": 0.5,
    
    "WIN_RATE_SCALING": {
        "conservative": {"min_wr": 0.0, "max_wr": 0.40, "min_size": 200, "max_size": 1000, "leverage": 5},
        "standard": {"min_wr": 0.40, "max_wr": 0.50, "min_size": 300, "max_size": 1200, "leverage": 6},
        "aggressive": {"min_wr": 0.50, "max_wr": 0.55, "min_size": 400, "max_size": 1500, "leverage": 7},
        "hot_streak": {"min_wr": 0.55, "max_wr": 1.0, "min_size": 500, "max_size": 2000, "leverage": 8}
    },
    
    "ENABLE_WIN_RATE_SCALING": True,
    "WIN_RATE_LOOKBACK_HOURS": 24
}


def get_win_rate_tier(win_rate: float) -> dict:
    """
    Get position sizing tier based on current win rate.
    
    Args:
        win_rate: Win rate as decimal (0.0 to 1.0)
    
    Returns:
        Tier configuration dict with min_size, max_size, leverage
    """
    tiers = TRADING_POLICY["WIN_RATE_SCALING"]
    
    for tier_name, tier_config in sorted(tiers.items(), key=lambda x: x[1]["min_wr"], reverse=True):
        if tier_config["min_wr"] <= win_rate < tier_config["max_wr"] or win_rate >= tier_config["max_wr"]:
            if win_rate >= tier_config["min_wr"]:
                return {
                    "tier": tier_name,
                    "min_size": tier_config["min_size"],
                    "max_size": tier_config["max_size"],
                    "leverage": tier_config["leverage"]
                }
    
    return {
        "tier": "conservative",
        "min_size": 200,
        "max_size": 1000,
        "leverage": 5
    }


def get_scaled_position_limits(win_rate: float, pnl_positive: bool = True) -> dict:
    """
    Get dynamically scaled position limits based on performance.
    
    Args:
        win_rate: Current win rate (0.0 to 1.0)
        pnl_positive: Whether recent P&L is positive
    
    Returns:
        Dict with min_size, max_size, base_size, leverage, tier
    """
    tier = get_win_rate_tier(win_rate)
    
    if not pnl_positive and tier["tier"] in ["aggressive", "hot_streak"]:
        tier = get_win_rate_tier(max(0.40, win_rate - 0.10))
        tier["tier"] += "_dampened"
    
    base_size = (tier["min_size"] + tier["max_size"]) / 2
    
    return {
        "tier": tier["tier"],
        "min_size": tier["min_size"],
        "max_size": tier["max_size"],
        "base_size": base_size,
        "leverage": tier["leverage"]
    }
