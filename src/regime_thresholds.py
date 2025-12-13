"""
Regime-aware threshold management with adaptive tuning.
"""

# Default thresholds by market regime
REGIME_THRESHOLDS = {
    "Stable": {
        "ROI": 0.002,
        "Momentum": -0.001,
        "VolumeRatio": 0.9
    },
    "Trending": {
        "ROI": 0.003,
        "Momentum": 0.0,
        "VolumeRatio": 1.0
    },
    "Volatile": {
        "ROI": 0.004,
        "Momentum": 0.01,
        "VolumeRatio": 1.1
    },
    "Ranging": {
        "ROI": 0.0025,
        "Momentum": 0.0,
        "VolumeRatio": 0.95
    }
}

# Adaptive thresholds (can be tuned based on performance)
adaptive_thresholds = REGIME_THRESHOLDS["Stable"].copy()

def get_thresholds_for_regime(regime):
    """
    Get trading thresholds for a specific market regime.
    
    Args:
        regime: Market regime name
    
    Returns:
        Dict with ROI, Momentum, and VolumeRatio thresholds
    """
    return REGIME_THRESHOLDS.get(regime, REGIME_THRESHOLDS["Stable"])

def update_adaptive_thresholds(new_thresholds):
    """
    Update adaptive thresholds based on performance analysis.
    
    Args:
        new_thresholds: Dict with updated threshold values
    """
    global adaptive_thresholds
    adaptive_thresholds.update(new_thresholds)
    print(f"🔧 Updated adaptive thresholds: {adaptive_thresholds}")

def get_adaptive_thresholds():
    """Get current adaptive thresholds."""
    return adaptive_thresholds.copy()
