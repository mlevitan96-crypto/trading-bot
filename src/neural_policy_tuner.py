"""
Neural policy tuner - dynamically adjusts strategy weights based on performance.
Uses softmax-based approach to convert performance rewards into probability distributions.
Includes temperature scaling, decay, and minimum weights to prevent strategy paralysis.
"""
import json
from pathlib import Path
import numpy as np
import pytz
from datetime import datetime
from src.strategy_performance_memory import compute_strategy_reward, load_strategy_memory

REGIME_WEIGHTS_FILE = "logs/regime_weights.json"
LEARNING_CONFIG_FILE = "logs/learning_config.json"
ARIZONA_TZ = pytz.timezone('America/Phoenix')

def get_arizona_time():
    """Get current time in Arizona timezone."""
    return datetime.now(ARIZONA_TZ)

def initialize_regime_weights():
    """Initialize regime weights log file."""
    Path("logs").mkdir(exist_ok=True)
    if not Path(REGIME_WEIGHTS_FILE).exists():
        weights = {
            "regime_log": [],
            "created_at": get_arizona_time().isoformat()
        }
        with open(REGIME_WEIGHTS_FILE, 'w') as f:
            json.dump(weights, f, indent=2)

def _load_learning_config():
    """Load learning configuration with defaults."""
    try:
        with open(LEARNING_CONFIG_FILE, 'r') as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {"temperature": 1.0, "min_weight": 0.05, "decay": 0.98}


def evolve_strategy_weights(regime, active_strategies):
    """
    Compute performance-based weights for strategies using softmax with enhancements.
    Includes realized P&L-aware rewards, decay to avoid overfitting, temperature scaling,
    and minimum weights to prevent strategy paralysis.
    
    Args:
        regime: Current market regime
        active_strategies: List of active strategy names for this regime
    
    Returns:
        Dict mapping strategy names to weights (0-1, sum to 1)
    """
    if not active_strategies:
        return {}
    
    cfg = _load_learning_config()
    memory = load_strategy_memory()
    
    # Compute rewards for all active strategies with decay
    rewards = []
    for s in active_strategies:
        r = compute_strategy_reward(s, regime)  # realized ROI w/ missed penalty
        # Add mild decay to avoid overfitting to recent spikes
        r = r * cfg.get("decay", 0.98)
        rewards.append(max(r, 1e-4))  # Prevent negative rewards
    
    rewards = np.array(rewards)
    
    # SAFETY: Clamp rewards to prevent NaN from overflow
    rewards = np.clip(rewards, -10, 10)  # Prevent extreme values
    
    # Apply temperature scaling (higher temp = more exploration)
    temperature = max(0.3, cfg.get("temperature", 1.0))
    exp_rewards = np.exp(rewards / temperature)
    
    # SAFETY: Handle NaN/Inf
    if not np.all(np.isfinite(exp_rewards)):
        exp_rewards = np.ones_like(rewards)  # Fall back to equal weights
    
    weights = exp_rewards / np.sum(exp_rewards)
    
    # SAFETY: Final NaN check
    if not np.all(np.isfinite(weights)):
        weights = np.ones(len(active_strategies)) / len(active_strategies)
    
    # Clamp minimum weights to avoid paralysis (strategies never get zero weight)
    min_w = cfg.get("min_weight", 0.05)
    weights = np.maximum(weights, min_w)
    weights = weights / np.sum(weights)  # Re-normalize after clamping
    
    # Convert to dict
    tuned_weights = {s: round(float(w), 4) for s, w in zip(active_strategies, weights)}
    
    return tuned_weights

def log_regime_shift(regime, strategy_weights):
    """
    Log a regime shift and the corresponding strategy weights.
    
    Args:
        regime: New market regime
        strategy_weights: Dict of strategy weights
    """
    initialize_regime_weights()
    
    with open(REGIME_WEIGHTS_FILE, 'r') as f:
        data = json.load(f)
    
    entry = {
        "timestamp": get_arizona_time().isoformat(),
        "regime": regime,
        "weights": strategy_weights
    }
    
    data["regime_log"].append(entry)
    
    # Keep last 200 regime shifts
    if len(data["regime_log"]) > 200:
        data["regime_log"] = data["regime_log"][-200:]
    
    with open(REGIME_WEIGHTS_FILE, 'w') as f:
        json.dump(data, f, indent=2)
    
    print(f"\n🧠 Strategy Weights for {regime}:")
    for s, w in strategy_weights.items():
        print(f"   🔁 {s}: {w:.2%}")

def get_weighted_strategy_selection(regime, active_strategies):
    """
    Select a strategy based on learned weights (can be used for random selection).
    
    Args:
        regime: Current market regime
        active_strategies: List of active strategies
    
    Returns:
        Tuple (weights_dict, selected_strategy)
    """
    weights = evolve_strategy_weights(regime, active_strategies)
    
    # For now, return all strategies with their weights
    # Could be extended to do weighted random selection
    return weights, active_strategies

def get_regime_history():
    """
    Get recent regime shift history.
    
    Returns:
        List of recent regime shifts with weights
    """
    if not Path(REGIME_WEIGHTS_FILE).exists():
        return []
    
    with open(REGIME_WEIGHTS_FILE, 'r') as f:
        data = json.load(f)
    
    return data.get("regime_log", [])[-20:]  # Last 20 shifts
