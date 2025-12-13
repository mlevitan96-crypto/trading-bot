import numpy as np
import json
import os


def load_strategy_returns():
    """Load historical strategy returns from strategy memory."""
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    filepath = os.path.join(base_dir, "logs", "strategy_memory.json")
    
    try:
        with open(filepath, "r") as f:
            data = json.load(f)
        
        strategy_returns = {}
        if "performance" in data:
            for key, perf in data["performance"].items():
                if "_" in key:
                    strategy, regime = key.rsplit("_", 1)
                else:
                    strategy = key
                
                if strategy not in strategy_returns:
                    strategy_returns[strategy] = []
                
                if "roi_history" in perf and perf["roi_history"]:
                    strategy_returns[strategy].extend(perf["roi_history"])
        
        return strategy_returns
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def apply_risk_parity_sizing(base_sizes, min_history=5):
    """
    Apply risk parity overlay to position sizes.
    
    Adjusts position sizes based on strategy volatility to equalize risk contribution.
    Uses historical returns from strategy memory to calculate volatility.
    
    Args:
        base_sizes: Dict of {strategy: size} from Kelly/budget caps
        min_history: Minimum number of trades required for adjustment
    
    Returns:
        Dict of {strategy: adjusted_size} with risk-parity adjustments
    """
    if not base_sizes:
        return {}
    
    strategy_returns = load_strategy_returns()
    
    if not strategy_returns:
        return base_sizes
    
    vols = {}
    for strategy, size in base_sizes.items():
        if strategy in strategy_returns and len(strategy_returns[strategy]) >= min_history:
            returns = strategy_returns[strategy]
            vols[strategy] = np.std(returns) if returns else 0.01
        else:
            vols[strategy] = 0.01
    
    if not vols or all(v == 0.01 for v in vols.values()):
        return base_sizes
    
    target_vol = np.mean(list(vols.values()))
    
    adjusted = {}
    for strategy, size in base_sizes.items():
        current_vol = vols.get(strategy, 0.01)
        
        if current_vol > 1e-6:
            vol_factor = target_vol / current_vol
            vol_factor = min(max(vol_factor, 0.5), 1.5)
        else:
            vol_factor = 1.0
        
        adjusted[strategy] = size * vol_factor
    
    return adjusted


def get_risk_parity_stats():
    """Get risk parity statistics for monitoring."""
    strategy_returns = load_strategy_returns()
    
    stats = {}
    for strategy, returns in strategy_returns.items():
        if returns and len(returns) >= 2:
            stats[strategy] = {
                "count": len(returns),
                "mean_roi": float(np.mean(returns)),
                "volatility": float(np.std(returns)),
                "sharpe": float(np.mean(returns) / np.std(returns)) if np.std(returns) > 0 else 0
            }
    
    return stats
