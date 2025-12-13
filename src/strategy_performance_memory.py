"""
Strategy performance memory and learning system.
Tracks strategy results by regime and computes performance-based rewards.
"""
import json
from pathlib import Path
import numpy as np
import pytz
from datetime import datetime

STRATEGY_MEMORY_FILE = "logs/strategy_memory.json"
ARIZONA_TZ = pytz.timezone('America/Phoenix')

def get_arizona_time():
    """Get current time in Arizona timezone."""
    return datetime.now(ARIZONA_TZ)

def initialize_strategy_memory():
    """Initialize strategy memory log file."""
    Path("logs").mkdir(exist_ok=True)
    if not Path(STRATEGY_MEMORY_FILE).exists():
        memory = {
            "performance": {},
            "created_at": get_arizona_time().isoformat()
        }
        with open(STRATEGY_MEMORY_FILE, 'w') as f:
            json.dump(memory, f, indent=2)

def load_strategy_memory():
    """Load strategy performance memory."""
    initialize_strategy_memory()
    with open(STRATEGY_MEMORY_FILE, 'r') as f:
        return json.load(f)

def save_strategy_memory(memory):
    """Save strategy performance memory."""
    with open(STRATEGY_MEMORY_FILE, 'w') as f:
        json.dump(memory, f, indent=2)

def log_strategy_result(strategy, regime, roi, missed=False):
    """
    Log the result of a strategy execution or missed opportunity.
    
    Args:
        strategy: Strategy name
        regime: Market regime
        roi: Return on investment
        missed: Whether this was a missed opportunity (True) or executed trade (False)
    """
    memory = load_strategy_memory()
    key = f"{strategy}_{regime}"
    
    if key not in memory["performance"]:
        memory["performance"][key] = {
            "roi_history": [],
            "missed_count": 0,
            "executed_count": 0,
            "last_updated": get_arizona_time().isoformat()
        }
    
    perf = memory["performance"][key]
    perf["roi_history"].append(round(roi, 6))
    
    # Keep last 100 ROI entries
    if len(perf["roi_history"]) > 100:
        perf["roi_history"] = perf["roi_history"][-100:]
    
    if missed:
        perf["missed_count"] += 1
    else:
        perf["executed_count"] += 1
    
    perf["last_updated"] = get_arizona_time().isoformat()
    
    save_strategy_memory(memory)

def compute_strategy_reward(strategy, regime):
    """
    Compute performance-based reward for a strategy in a specific regime.
    
    Args:
        strategy: Strategy name
        regime: Market regime
    
    Returns:
        Float reward score (higher = better performance)
    """
    memory = load_strategy_memory()
    key = f"{strategy}_{regime}"
    
    if key not in memory["performance"]:
        return 0.01  # Default small reward for untested strategies
    
    perf = memory["performance"][key]
    
    if not perf["roi_history"]:
        return 0.01
    
    # Average ROI - filter out NaN values to prevent propagation
    roi_values = [r for r in perf["roi_history"] if r is not None and not np.isnan(r)]
    if not roi_values:
        return 0.01
    avg_roi = np.mean(roi_values)
    
    # Penalty for missed opportunities
    total_opportunities = perf["executed_count"] + perf["missed_count"]
    penalty = perf["missed_count"] / max(total_opportunities, 1) if total_opportunities > 0 else 0
    
    # Reward = average ROI reduced by missed opportunity penalty
    reward = avg_roi * (1 - penalty * 0.5)  # 50% penalty weight
    
    # Ensure minimum positive reward
    return max(round(reward, 6), 0.001)

def get_strategy_stats(strategy, regime):
    """
    Get detailed statistics for a strategy in a regime.
    
    Args:
        strategy: Strategy name
        regime: Market regime
    
    Returns:
        Dict with statistics
    """
    memory = load_strategy_memory()
    key = f"{strategy}_{regime}"
    
    if key not in memory["performance"]:
        return {
            "avg_roi": 0,
            "total_opportunities": 0,
            "executed": 0,
            "missed": 0,
            "reward": 0.01
        }
    
    perf = memory["performance"][key]
    
    return {
        "avg_roi": round(np.mean(perf["roi_history"]), 6) if perf["roi_history"] else 0,
        "total_opportunities": perf["executed_count"] + perf["missed_count"],
        "executed": perf["executed_count"],
        "missed": perf["missed_count"],
        "reward": compute_strategy_reward(strategy, regime)
    }
