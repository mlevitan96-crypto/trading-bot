"""
HURST EXPONENT SIGNAL - Market Regime Detection
================================================
The Hurst Exponent reveals whether the market is:
- Trending (H > 0.5): Momentum signals are more reliable
- Mean-reverting (H < 0.5): Contrarian signals are more reliable
- Random walk (H ≈ 0.5): Low predictability, reduce position size

CALCULATION: R/S (Rescaled Range) Analysis
- Uses historical price returns
- Calculates log(R/S) vs log(n) relationship
- Slope of regression = Hurst Exponent

SIGNAL OUTPUT:
- direction: LONG if trending up, SHORT if trending down
- confidence: abs(H - 0.5) * 2 (how far from random)
- regime: 'trending', 'mean_reverting', or 'random'
"""

import numpy as np
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, Optional, Tuple
import json

HURST_CACHE_FILE = Path("feature_store/hurst_cache.json")
HURST_CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)

_hurst_cache: Dict[str, Dict] = {}
_cache_ttl = 300


def _load_cache():
    """Load Hurst cache from disk."""
    global _hurst_cache
    try:
        if HURST_CACHE_FILE.exists():
            _hurst_cache = json.loads(HURST_CACHE_FILE.read_text())
    except:
        _hurst_cache = {}


def _save_cache():
    """Save Hurst cache to disk."""
    try:
        HURST_CACHE_FILE.write_text(json.dumps(_hurst_cache, indent=2))
    except:
        pass


def calculate_hurst_exponent(prices, min_window: int = 10, max_window: int = 100, strict_period: int = None) -> float:
    """
    Calculate Hurst Exponent using R/S (Rescaled Range) method.
    
    Args:
        prices: List or array of price values (at least 100 for reliable estimate)
        min_window: Minimum window size for R/S calculation
        max_window: Maximum window size
        strict_period: If provided, use exactly this many periods (for 100-period rolling window)
    
    Returns:
        Hurst exponent (0 to 1)
        - H > 0.5: Trending/persistent
        - H = 0.5: Random walk
        - H < 0.5: Mean-reverting
    """
    # [BIG ALPHA] Use strict 100-period window if specified
    if strict_period is not None:
        if len(prices) < strict_period:
            return 0.5  # Insufficient data
        prices = list(prices[-strict_period:])  # Use exactly last N periods
        min_window = max(10, strict_period // 10)  # Adjust min_window proportionally
        max_window = strict_period // 2  # Adjust max_window proportionally
    
    if len(prices) < min_window * 2:
        return 0.5
    
    prices_arr = np.array(prices, dtype=float)
    returns = np.diff(np.log(prices_arr + 1e-10))
    
    if len(returns) < min_window:
        return 0.5
    
    rs_values = []
    n_values = []
    
    max_window = min(max_window, len(returns) // 2)
    
    for n in range(min_window, max_window + 1, max(1, (max_window - min_window) // 10)):
        num_segments = len(returns) // n
        if num_segments < 1:
            continue
        
        rs_list = []
        for i in range(num_segments):
            segment = returns[i * n:(i + 1) * n]
            if len(segment) < 2:
                continue
            
            mean = float(np.mean(segment))
            deviations = segment - mean
            cumulative = np.cumsum(deviations)
            
            R = float(np.max(cumulative) - np.min(cumulative))
            S = float(np.std(segment, ddof=1))
            
            if S > 1e-10:
                rs_list.append(R / S)
        
        if rs_list:
            rs_values.append(float(np.mean(rs_list)))
            n_values.append(n)
    
    if len(rs_values) < 3:
        return 0.5
    
    log_n = np.log(np.array(n_values, dtype=float))
    log_rs = np.log(np.array(rs_values, dtype=float))
    
    try:
        coeffs = np.polyfit(log_n, log_rs, 1)
        slope = float(coeffs[0])
        hurst = max(0.0, min(1.0, slope))
    except:
        hurst = 0.5
    
    return hurst


def get_price_trend_direction(prices, lookback: int = 20) -> Tuple[str, float]:
    """
    Determine if price is trending up or down.
    
    Returns:
        (direction, strength) - direction is 'LONG' or 'SHORT', strength is 0-1
    """
    if len(prices) < lookback:
        return ('LONG', 0.5)
    
    recent = list(prices[-lookback:])
    
    if recent[0] <= 0:
        return ('LONG', 0.5)
    
    mid_point = len(recent) // 2
    first_half_avg = float(np.mean(recent[:mid_point]))
    second_half_avg = float(np.mean(recent[mid_point:]))
    
    if first_half_avg <= 0:
        return ('LONG', 0.5)
    
    if second_half_avg > first_half_avg:
        direction = 'LONG'
        if first_half_avg > 1e-10:
            strength = float(min(1.0, (second_half_avg / first_half_avg - 1) * 10 + 0.5))
        else:
            strength = 0.5
    else:
        direction = 'SHORT'
        if second_half_avg > 1e-10:
            strength = float(min(1.0, (first_half_avg / second_half_avg - 1) * 10 + 0.5))
        else:
            strength = 0.5
    
    return (direction, strength)


def get_hurst_signal(symbol: str, use_cache: bool = True) -> Dict[str, Any]:
    """
    Generate Hurst Exponent signal for a symbol.
    
    Args:
        symbol: Trading pair (e.g., 'BTCUSDT')
        use_cache: Whether to use cached values (5 min TTL)
    
    Returns:
        Signal dict with:
        - active: bool
        - direction: 'LONG' or 'SHORT'
        - confidence: 0-1
        - hurst_value: actual H value
        - regime: 'trending', 'mean_reverting', 'random'
        - interpretation: human readable
    """
    global _hurst_cache
    
    if not _hurst_cache:
        _load_cache()
    
    now = time.time()
    cache_key = symbol
    
    if use_cache and cache_key in _hurst_cache:
        cached = _hurst_cache[cache_key]
        if now - cached.get('ts', 0) < _cache_ttl:
            return cached.get('signal', _empty_signal())
    
    try:
        prices = _fetch_prices(symbol, limit=200)
        
        if not prices or len(prices) < 50:
            return _empty_signal()
        
        # [BIG ALPHA] Use strict 100-period rolling window for TRUE TREND detection
        hurst = calculate_hurst_exponent(prices, strict_period=100)
        
        trend_dir, trend_strength = get_price_trend_direction(prices)
        
        # [BIG ALPHA] TRUE TREND detection: H > 0.55 = TRUE TREND (Momentum)
        if hurst > 0.55:
            regime = 'trending'  # TRUE TREND - Momentum
            direction = trend_dir
            confidence = min(1.0, (hurst - 0.5) * 4) * trend_strength
            interpretation = f"TRUE TREND detected (H={hurst:.2f}), favor {direction} momentum - FORCE-HOLD"
            active = True
        elif hurst < 0.45:
            regime = 'mean_reverting'  # NOISE - Mean Reversion
            direction = 'SHORT' if trend_dir == 'LONG' else 'LONG'
            confidence = min(1.0, (0.5 - hurst) * 4) * trend_strength
            interpretation = f"NOISE detected (H={hurst:.2f}), mean-reverting - standard exits"
            active = True
        else:
            regime = 'random'  # Random walk
            direction = trend_dir
            confidence = 0.3
            interpretation = f"Random walk (H={hurst:.2f}), low confidence"
            active = False
        
        signal = {
            'active': active,
            'direction': direction,
            'confidence': round(confidence, 3),
            'hurst_value': round(hurst, 4),
            'regime': regime,
            'interpretation': interpretation,
            'trend_direction': trend_dir,
            'trend_strength': round(trend_strength, 3),
            'timestamp': datetime.now().isoformat()
        }
        
        _hurst_cache[cache_key] = {
            'ts': now,
            'signal': signal
        }
        _save_cache()
        
        return signal
        
    except Exception as e:
        print(f"[Hurst] Error calculating for {symbol}: {e}")
        return _empty_signal()


def _empty_signal() -> Dict[str, Any]:
    """Return an empty/neutral signal."""
    return {
        'active': False,
        'direction': 'LONG',
        'confidence': 0.0,
        'hurst_value': 0.5,
        'regime': 'unknown',
        'interpretation': 'Insufficient data',
        'trend_direction': 'LONG',
        'trend_strength': 0.5,
        'timestamp': datetime.now().isoformat()
    }


def _fetch_prices(symbol: str, limit: int = 200) -> list:
    """
    Fetch recent prices for Hurst calculation.
    Uses BlofinClient to get OHLCV data from Binance.
    """
    try:
        from src.blofin_client import BlofinClient
        
        client = BlofinClient()
        
        df = client.fetch_ohlcv(symbol=symbol, timeframe='15m', limit=limit)
        
        if df is not None and len(df) > 0:
            closes = df['close'].tolist()
            return closes
        
        from src.blofin_client import get_current_price
        current_price = get_current_price(symbol)
        if current_price > 0:
            return [current_price] * 50
        
        return []
        
    except Exception as e:
        print(f"[Hurst] Error fetching prices for {symbol}: {e}")
        return []


def get_all_hurst_signals(symbols: list) -> Dict[str, Dict]:
    """
    Get Hurst signals for multiple symbols at once.
    
    Args:
        symbols: List of trading pairs
    
    Returns:
        Dict mapping symbol to signal
    """
    results = {}
    for symbol in symbols:
        results[symbol] = get_hurst_signal(symbol)
    return results


if __name__ == "__main__":
    print("Testing Hurst Exponent Signal...")
    
    np.random.seed(42)
    
    trend_prices = [100.0 + i * 0.5 + float(np.random.randn()) * 0.5 for i in range(200)]
    trend_h = calculate_hurst_exponent(trend_prices)
    print(f"Trending data Hurst: {trend_h:.3f} (expected > 0.5)")
    
    mean_rev: list = [100.0]
    for i in range(199):
        mean_rev.append(100.0 + (mean_rev[-1] - 100.0) * 0.9 + float(np.random.randn()) * 2.0)
    mean_rev_h = calculate_hurst_exponent(mean_rev)
    print(f"Mean-reverting data Hurst: {mean_rev_h:.3f} (expected < 0.5)")
    
    random_walk: list = [100.0]
    for i in range(199):
        random_walk.append(random_walk[-1] + float(np.random.randn()))
    random_h = calculate_hurst_exponent(random_walk)
    print(f"Random walk Hurst: {random_h:.3f} (expected ≈ 0.5)")
    
    print("\nLive test with BTCUSDT:")
    signal = get_hurst_signal("BTCUSDT", use_cache=False)
    print(f"Signal: {json.dumps(signal, indent=2)}")
