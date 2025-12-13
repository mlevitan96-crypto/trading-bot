"""
Bot Enhancements Module
Adaptive protective mode tuning and utilities for the crypto trading bot.
"""

import json
from pathlib import Path
from src.volatility_monitor import set_protective_thresholds


PROTECTIVE_STATE_FILE = "logs/protective_state.json"

PROTECTIVE_STATE = {
    'trigger_count': 0,
    'last_drawdown': 0.0,
    'false_positive_count': 0,
    'missed_drawdown_count': 0
}


def load_protective_state():
    """Load protective mode state from disk."""
    global PROTECTIVE_STATE
    try:
        if Path(PROTECTIVE_STATE_FILE).exists():
            with open(PROTECTIVE_STATE_FILE, 'r') as f:
                PROTECTIVE_STATE = json.load(f)
    except Exception as e:
        print(f"⚠️  Could not load protective state: {e}")


def save_protective_state():
    """Save protective mode state to disk."""
    try:
        Path("logs").mkdir(exist_ok=True)
        with open(PROTECTIVE_STATE_FILE, 'w') as f:
            json.dump(PROTECTIVE_STATE, f, indent=2)
    except Exception as e:
        print(f"⚠️  Could not save protective state: {e}")


def update_protective_mode(drawdown, triggered):
    """
    Adaptive protective mode tuning based on performance.
    
    Args:
        drawdown: Current drawdown percentage (0.02 = 2%)
        triggered: Boolean indicating if protective mode was triggered
    
    Logic:
        - If protective mode triggers frequently but drawdown is minimal:
          → Relax thresholds (reduce false positives)
        - If drawdown occurs without protective mode triggering:
          → Tighten thresholds (increase sensitivity)
    """
    global PROTECTIVE_STATE
    
    load_protective_state()
    
    if triggered:
        PROTECTIVE_STATE['trigger_count'] += 1
        
        # Check if this was a false positive (triggered but minimal drawdown)
        if drawdown < 0.01:
            PROTECTIVE_STATE['false_positive_count'] += 1
    
    PROTECTIVE_STATE['last_drawdown'] = drawdown
    
    # Evaluate tuning every 5 cycles
    if PROTECTIVE_STATE['trigger_count'] % 5 == 0 or PROTECTIVE_STATE.get('missed_drawdown_count', 0) > 0:
        
        # Too many false positives: relax thresholds
        if PROTECTIVE_STATE['false_positive_count'] >= 3 and drawdown < 0.015:
            set_protective_thresholds(
                volume_spike=6.0,
                atr_jump=0.5,
                bb_expansion=0.35
            )
            print(f"🔧 Protective mode relaxed: {PROTECTIVE_STATE['false_positive_count']} benign triggers detected")
            PROTECTIVE_STATE['false_positive_count'] = 0
        
        # Missed drawdown: tighten thresholds
        elif drawdown > 0.025 and PROTECTIVE_STATE['trigger_count'] == 0:
            set_protective_thresholds(
                volume_spike=3.5,
                atr_jump=0.28,
                bb_expansion=0.22
            )
            print(f"🛡️  Protective mode tightened: {drawdown*100:.2f}% drawdown without trigger")
            PROTECTIVE_STATE['missed_drawdown_count'] = PROTECTIVE_STATE.get('missed_drawdown_count', 0) + 1
    
    save_protective_state()


def safe_get(data, key, default=None):
    """
    Safely get a value from a dictionary.
    
    Args:
        data: Dictionary to access
        key: Key to retrieve
        default: Default value if key not found
    
    Returns:
        Value from dictionary or default
    """
    try:
        return data.get(key, default) if isinstance(data, dict) else default
    except Exception:
        return default


def get_protective_state_stats():
    """
    Get current protective mode tuning statistics.
    
    Returns:
        dict: Protective mode state and statistics
    """
    load_protective_state()
    return PROTECTIVE_STATE.copy()
