import pandas as pd


# Configurable protective mode thresholds (adaptive tuning)
# Relaxed to allow trading during normal crypto volatility
PROTECTIVE_THRESHOLDS = {
    "volume_spike": 15.0,  # Raised from 5.0 to 15.0 (1500% increase required)
    "atr_jump": 0.60,      # Raised from 0.40 to 0.60 (60% of price)
    "bb_expansion": 0.50   # Raised from 0.30 to 0.50 (50% std/price)
}


def set_protective_thresholds(volume_spike=None, atr_jump=None, bb_expansion=None):
    """
    Update protective mode thresholds for adaptive tuning.
    
    Args:
        volume_spike: Volume spike threshold (e.g., 5.0 = 500% increase)
        atr_jump: ATR jump threshold (e.g., 0.40 = 40% of price)
        bb_expansion: Bollinger Band expansion threshold (e.g., 0.30 = 30% std/price)
    """
    global PROTECTIVE_THRESHOLDS
    
    if volume_spike is not None:
        PROTECTIVE_THRESHOLDS["volume_spike"] = volume_spike
    if atr_jump is not None:
        PROTECTIVE_THRESHOLDS["atr_jump"] = atr_jump
    if bb_expansion is not None:
        PROTECTIVE_THRESHOLDS["bb_expansion"] = bb_expansion
    
    print(f"🔧 Protective thresholds updated: vol={PROTECTIVE_THRESHOLDS['volume_spike']}, atr={PROTECTIVE_THRESHOLDS['atr_jump']}, bb={PROTECTIVE_THRESHOLDS['bb_expansion']}")


def get_protective_thresholds():
    """Get current protective mode thresholds."""
    return PROTECTIVE_THRESHOLDS.copy()


def detect_volatility_spike(df):
    """
    Detect volatility spikes using relative/scale-aware indicators.
    Returns dict with vol_spike, atr_jump, bb_expansion, and recommended action.
    
    NOTE: NaN values are treated as False (no spike) to prevent false protective triggers.
    """
    import math
    
    if df.empty or len(df) < 2:
        return {
            "vol_spike": False,
            "atr_jump": False,
            "bb_expansion": False,
            "action": "normal"
        }
    
    # Volume spike check with NaN safety
    vol_change = df["volume"].pct_change().iloc[-1] if len(df) >= 2 else 0
    if math.isnan(vol_change) or math.isinf(vol_change):
        vol_change = 0  # Treat NaN/Inf as no spike
    vol_spike = bool(vol_change > PROTECTIVE_THRESHOLDS["volume_spike"])
    
    # ATR check with NaN safety
    atr = df["high"].iloc[-1] - df["low"].iloc[-1]
    avg_price = df["close"].mean()
    atr_pct = (atr / avg_price) if avg_price > 0 else 0
    if math.isnan(atr_pct) or math.isinf(atr_pct):
        atr_pct = 0
    atr_jump = bool(atr_pct > PROTECTIVE_THRESHOLDS["atr_jump"])
    
    # BB expansion check with NaN safety
    price_std = df["close"].std()
    avg_close = df["close"].mean()
    bb_expansion_pct = (price_std / avg_close) if avg_close > 0 else 0
    if math.isnan(bb_expansion_pct) or math.isinf(bb_expansion_pct):
        bb_expansion_pct = 0
    bb_expansion = bool(bb_expansion_pct > PROTECTIVE_THRESHOLDS["bb_expansion"])
    
    return {
        "vol_spike": vol_spike,
        "atr_jump": atr_jump,
        "bb_expansion": bb_expansion,
        "action": "protect" if (vol_spike or atr_jump or bb_expansion) else "normal"
    }
