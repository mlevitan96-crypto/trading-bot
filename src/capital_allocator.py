"""
Regime-aware capital allocation for optimal strategy budgeting.
Allocates different capital percentages to strategies based on current market regime.
Enforces minimum budgets from profit learning module without exceeding portfolio value.
"""
from src.regime_detector import predict_regime
from src.portfolio_tracker import load_portfolio
from src.profit_blofin_learning import DEFAULT_MIN_COLLATERAL_USD


def allocate_capital():
    """
    Allocate capital across ALL strategies based on current market regime.
    Enforces minimum budget per strategy while respecting portfolio value cap.
    
    Returns:
        dict: Strategy name -> allocated capital (USD) for ALL strategies
    """
    portfolio = load_portfolio()
    regime = predict_regime()
    value = portfolio["current_value"]
    min_budget = DEFAULT_MIN_COLLATERAL_USD
    
    # Calculate raw allocations based on regime
    if regime == "Trending":
        raw_allocation = {
            "Trend-Conservative": value * 0.25,
            "Breakout-Aggressive": value * 0.25,
            "Sentiment-Fusion": value * 0.10
        }
    elif regime == "Volatile":
        raw_allocation = {
            "Breakout-Aggressive": value * 0.30,
            "Sentiment-Fusion": value * 0.20,
            "Trend-Conservative": value * 0.10
        }
    elif regime == "Stable":
        raw_allocation = {
            "Sentiment-Fusion": value * 0.30,
            "Trend-Conservative": value * 0.10,
            "Breakout-Aggressive": 0.0  # Lower priority in stable markets
        }
    elif regime == "Ranging":
        raw_allocation = {
            "Trend-Conservative": value * 0.20,
            "Sentiment-Fusion": value * 0.20,
            "Breakout-Aggressive": 0.0  # Lower priority in ranging markets
        }
    else:
        raw_allocation = {
            "Trend-Conservative": value * 0.15,
            "Breakout-Aggressive": value * 0.15,
            "Sentiment-Fusion": value * 0.15
        }
    
    # Apply minimum budgets
    allocation = {}
    for strategy in ["Trend-Conservative", "Breakout-Aggressive", "Sentiment-Fusion"]:
        allocation[strategy] = max(raw_allocation.get(strategy, 0.0), min_budget)
    
    # Check if total allocation exceeds portfolio value
    total_allocated = sum(allocation.values())
    
    if total_allocated > value:
        # Portfolio too small to give all strategies their minimum
        # Priority order by regime, then scale down proportionally
        strategy_priority = {
            "Stable": ["Sentiment-Fusion", "Trend-Conservative", "Breakout-Aggressive"],
            "Volatile": ["Breakout-Aggressive", "Sentiment-Fusion", "Trend-Conservative"],
            "Trending": ["Trend-Conservative", "Breakout-Aggressive", "Sentiment-Fusion"],
            "Ranging": ["Trend-Conservative", "Sentiment-Fusion", "Breakout-Aggressive"]
        }
        
        priorities = strategy_priority.get(regime, ["Trend-Conservative", "Breakout-Aggressive", "Sentiment-Fusion"])
        
        if value >= min_budget:
            # Give minimums to highest priority strategies first
            allocation = {k: 0.0 for k in allocation}
            remaining = value
            for strategy in priorities:
                if remaining >= min_budget:
                    allocation[strategy] = min_budget
                    remaining -= min_budget
                elif remaining > 0:
                    allocation[strategy] = remaining
                    remaining = 0
        else:
            # Portfolio too small for even one minimum - distribute proportionally
            scale = value / total_allocated
            for strategy in allocation:
                allocation[strategy] *= scale
    
    print(f"💰 Regime-aware allocation for {regime}:")
    for strategy, amount in allocation.items():
        pct = (amount / value * 100) if value > 0 else 0
        print(f"   {strategy}: ${amount:.2f} ({pct:.0f}%)")
    
    return allocation


def get_strategy_budget(strategy_name, regime=None):
    """
    Get the allocated budget for a specific strategy.
    
    Args:
        strategy_name: Name of the strategy
        regime: Optional regime override (uses current if None)
    
    Returns:
        float: Allocated capital for this strategy in USD
    """
    allocation = allocate_capital()
    return allocation.get(strategy_name, 0.0)


def allocate_futures_margin(max_total_margin_pct=0.60):
    """
    Allocate margin collateral budget for futures trading across ALL strategies.
    
    Futures allocation is separate from spot and uses margin collateral semantics:
    - Margin allocation = capital set aside for margin collateral
    - Notional exposure = margin × leverage (calculated separately)
    
    Args:
        max_total_margin_pct: Maximum percentage of portfolio to allocate as margin (default 60%, raised from 30% to enable larger positions)
    
    Returns:
        dict: Strategy name -> allocated margin collateral (USD) for ALL strategies
    """
    portfolio = load_portfolio()
    regime = predict_regime()
    value = portfolio["current_value"]
    total_margin_budget = value * max_total_margin_pct
    
    # Initialize all strategies with zero margin allocation
    margin_allocation = {
        "Trend-Conservative": 0.0,
        "Breakout-Aggressive": 0.0,
        "Sentiment-Fusion": 0.0
    }
    
    # Regime-specific margin allocation (more conservative than spot)
    if regime == "Trending":
        margin_allocation.update({
            "Trend-Conservative": total_margin_budget * 0.40,
            "Breakout-Aggressive": total_margin_budget * 0.35,
            "Sentiment-Fusion": total_margin_budget * 0.25
        })
    elif regime == "Volatile":
        # More conservative in volatile regimes
        margin_allocation.update({
            "Breakout-Aggressive": total_margin_budget * 0.30,
            "Sentiment-Fusion": total_margin_budget * 0.30,
            "Trend-Conservative": total_margin_budget * 0.40
        })
    elif regime == "Stable":
        # Can be more aggressive in stable regimes
        margin_allocation.update({
            "Sentiment-Fusion": total_margin_budget * 0.45,
            "Trend-Conservative": total_margin_budget * 0.35,
            "Breakout-Aggressive": total_margin_budget * 0.20
        })
    elif regime == "Ranging":
        margin_allocation.update({
            "Trend-Conservative": total_margin_budget * 0.35,
            "Sentiment-Fusion": total_margin_budget * 0.40,
            "Breakout-Aggressive": total_margin_budget * 0.25
        })
    else:
        # Default conservative fallback
        even_split = total_margin_budget / 3
        margin_allocation.update({
            "Trend-Conservative": even_split,
            "Breakout-Aggressive": even_split,
            "Sentiment-Fusion": even_split
        })
    
    print(f"💰 Futures margin allocation for {regime} (Total: ${total_margin_budget:.2f}):")
    for strategy, margin in margin_allocation.items():
        pct = (margin / total_margin_budget * 100) if total_margin_budget > 0 else 0
        print(f"   {strategy}: ${margin:.2f} ({pct:.0f}% of margin budget)")
    
    return margin_allocation


def get_strategy_margin_budget(strategy_name, regime=None):
    """
    Get the allocated margin collateral budget for a specific strategy (futures).
    
    Args:
        strategy_name: Name of the strategy
        regime: Optional regime override (uses current if None)
    
    Returns:
        float: Allocated margin collateral for this strategy in USD
    """
    margin_allocation = allocate_futures_margin()
    return margin_allocation.get(strategy_name, 0.0)
