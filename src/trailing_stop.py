"""
Trailing stop-loss implementation with dynamic ATR-based stops.
FUTURES-ONLY architecture - all spot trading functions removed.

OVERNIGHT FIX (Dec 2024):
Instead of completely disabling trailing stops after 30 minutes,
use TIERED trailing stops that get progressively wider:
- 0-30 min: Tight 1.5% trailing stop (catch quick reversals)
- 30-120 min: Medium 3.0% trailing stop (allow some noise)
- 120-240 min: Wide 5.0% trailing stop (let winners run)
- 240+ min: Very wide 8.0% trailing stop (overnight protection)

This ensures positions are NEVER stuck without any exit mechanism.
"""
import pandas as pd
import numpy as np
import time
from src.position_manager import get_open_futures_positions, close_futures_position

TRAIL_PCT = 0.015  # 1.5% trailing stop (fallback default)
# OVERNIGHT FIX: Tiered trailing stops instead of disabling
TRAIL_PCT_TIGHT = 0.015    # 0-30 min: 1.5%
TRAIL_PCT_MEDIUM = 0.030   # 30-120 min: 3.0%
TRAIL_PCT_WIDE = 0.050     # 120-240 min: 5.0%
TRAIL_PCT_VERY_WIDE = 0.08 # 240+ min: 8.0% (overnight protection)

def calculate_atr(df, period=14):
    """
    Calculate Average True Range (ATR) for volatility measurement.
    
    Args:
        df: DataFrame with OHLCV data
        period: ATR period (default 14)
    
    Returns:
        ATR value
    """
    if len(df) < period + 1:
        return 0.01  # Default fallback
    
    high_low = df['high'] - df['low']
    high_close = np.abs(df['high'] - df['close'].shift())
    low_close = np.abs(df['low'] - df['close'].shift())
    
    ranges = pd.concat([high_low, high_close, low_close], axis=1)
    true_range = ranges.max(axis=1)
    atr = true_range.rolling(period).mean()
    
    return float(atr.iloc[-1]) if not pd.isna(atr.iloc[-1]) else 0.01

def get_dynamic_trail_pct(df):
    """
    Calculate dynamic trailing stop percentage based on ATR.
    
    Args:
        df: DataFrame with OHLCV data
    
    Returns:
        Trailing stop percentage (between 1% and 3%)
    """
    atr = calculate_atr(df)
    last_close = float(df['close'].iloc[-1])
    
    # Trail percentage scaled by ATR relative to price
    # ATR/price gives volatility as percentage
    trail_pct = atr / last_close if last_close > 0 else TRAIL_PCT
    
    # Clamp between 1% (tight) and 3% (wide)
    trail_pct = min(0.03, max(0.01, trail_pct))
    
    return trail_pct

def get_tiered_trail_pct(hold_duration_minutes: float, base_trail_pct: float | None = None) -> float:
    """
    OVERNIGHT FIX: Get tiered trailing stop percentage based on hold duration.
    Uses progressively wider stops for longer-held positions.
    
    Args:
        hold_duration_minutes: How long position has been held
        base_trail_pct: Optional base from ATR calculation
    
    Returns:
        Trailing stop percentage
    """
    if hold_duration_minutes < 30:
        # Tight stop for first 30 minutes
        return base_trail_pct if base_trail_pct else TRAIL_PCT_TIGHT
    elif hold_duration_minutes < 120:
        # Medium stop for 30-120 minutes (2 hours)
        return max(TRAIL_PCT_MEDIUM, (base_trail_pct or 0) * 1.5)
    elif hold_duration_minutes < 240:
        # Wide stop for 120-240 minutes (4 hours)
        return max(TRAIL_PCT_WIDE, (base_trail_pct or 0) * 2.0)
    else:
        # Very wide stop for 4+ hours (overnight protection)
        return max(TRAIL_PCT_VERY_WIDE, (base_trail_pct or 0) * 2.5)


def apply_futures_trailing_stops(current_prices, market_data=None):
    """
    Check all open FUTURES positions for trailing stop triggers with dynamic ATR-based stops.
    
    OVERNIGHT FIX: Uses TIERED trailing stops instead of disabling after 30 minutes.
    Longer-held positions get progressively wider stops:
    - 0-30 min: Tight 1.5% (catch quick reversals)
    - 30-120 min: Medium 3.0% (allow some noise)
    - 120-240 min: Wide 5.0% (let winners run)
    - 240+ min: Very wide 8.0% (overnight protection)
    
    Args:
        current_prices: Dict of {symbol: current_price}
        market_data: Optional dict of {symbol: DataFrame} for ATR calculation
    
    Returns:
        List of positions that were closed
    """
    open_positions = get_open_futures_positions()
    closed = []
    now = time.time()
    
    for pos in open_positions:
        symbol = pos["symbol"]
        if symbol not in current_prices:
            continue
        
        current_price = current_prices[symbol]
        entry = pos["entry_price"]
        direction = pos.get("direction", "LONG")
        
        entry_ts = pos.get("entry_ts", pos.get("timestamp", now))
        if isinstance(entry_ts, str):
            try:
                from datetime import datetime
                entry_ts = datetime.fromisoformat(entry_ts.replace('Z', '+00:00')).timestamp()
            except:
                entry_ts = now
        
        hold_duration_minutes = (now - entry_ts) / 60
        
        if direction == "LONG":
            peak = pos.get("peak_price", entry)
            trigger_price = peak
        else:
            trough = pos.get("trough_price", entry)
            trigger_price = trough
        
        # OVERNIGHT FIX: Use tiered trailing stops instead of disabling
        base_trail_pct = None
        if market_data and symbol in market_data:
            base_trail_pct = get_dynamic_trail_pct(market_data[symbol])
        
        trail_pct = get_tiered_trail_pct(hold_duration_minutes, base_trail_pct)
        
        should_close = False
        if direction == "LONG" and current_price < trigger_price * (1 - trail_pct):
            should_close = True
        elif direction == "SHORT" and current_price > trigger_price * (1 + trail_pct):
            should_close = True
        
        if should_close:
            # Determine tier for logging
            if hold_duration_minutes < 30:
                tier = "tight"
            elif hold_duration_minutes < 120:
                tier = "medium"
            elif hold_duration_minutes < 240:
                tier = "wide"
            else:
                tier = "overnight"
            
            success = close_futures_position(
                symbol, 
                pos["strategy"], 
                direction,
                current_price, 
                reason=f"trailing_stop_{tier}"
            )
            if success:
                closed.append({
                    "symbol": symbol,
                    "strategy": pos["strategy"],
                    "direction": direction,
                    "entry": entry,
                    "exit": current_price,
                    "trigger_price": trigger_price,
                    "trail_pct": trail_pct,
                    "hold_minutes": hold_duration_minutes,
                    "tier": tier
                })
                print(f"🔻 Futures trailing stop ({tier}): {direction} {symbol} | Trigger: ${trigger_price:.2f} → Exit: ${current_price:.2f} | Trail: {trail_pct*100:.1f}% | Held: {hold_duration_minutes:.0f}m")
    
    return closed

# Alias for backward compatibility with validation suite
apply_trailing_stops = apply_futures_trailing_stops
