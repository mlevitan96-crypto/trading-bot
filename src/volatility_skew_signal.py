#!/usr/bin/env python3
"""
VOLATILITY SKEW SIGNAL - Loss Aversion / Complacency Detection
================================================================
Measures asymmetry in price returns distribution to detect behavioral triggers.

THEORY:
- Negative skew (left tail heavy) = Recent sharp drops, traders fear downside
  → Loss aversion high → Contrarian LONG signal
- Positive skew (right tail heavy) = Recent sharp rises, complacency
  → Bullish complacency → Contrarian SHORT signal
- Near zero = Balanced distribution, no strong signal

CALCULATION:
Uses Fisher-Pearson coefficient of skewness on log returns:
  skewness = E[(X - μ)³] / σ³

THRESHOLDS (Paper Mode - relaxed for data collection):
- Strong Negative Skew: < -0.5 → LONG signal (fear/loss aversion)
- Strong Positive Skew: > 0.5 → SHORT signal (complacency)
- Neutral: -0.5 to 0.5 → No signal

USAGE:
    from src.volatility_skew_signal import get_volatility_skew_signal
    signal = get_volatility_skew_signal('BTCUSDT')
"""

import numpy as np
import time
import requests
from typing import Dict, Any, Optional, List
from datetime import datetime
from scipy import stats


BINANCE_KLINES_URL = "https://api.binance.us/api/v3/klines"

SKEW_CACHE: Dict[str, Dict[str, Any]] = {}
CACHE_TTL = 300  # 5 minutes

LOOKBACK_PERIODS = 96  # 96 x 15min = 24 hours of data
CANDLE_INTERVAL = "15m"

PAPER_MODE = True
SKEW_THRESHOLD_STRONG = 0.5 if PAPER_MODE else 0.8
SKEW_THRESHOLD_EXTREME = 1.0 if PAPER_MODE else 1.5


def _fetch_candles(symbol: str, limit: int = 100) -> List[List]:
    """Fetch candles from Binance."""
    try:
        params = {
            'symbol': symbol,
            'interval': CANDLE_INTERVAL,
            'limit': limit
        }
        resp = requests.get(BINANCE_KLINES_URL, params=params, timeout=10)
        if resp.status_code == 200:
            return resp.json()
    except Exception as e:
        print(f"[VolSkew] Error fetching candles for {symbol}: {e}")
    return []


def _calculate_log_returns(candles: List[List]) -> np.ndarray:
    """Calculate log returns from candle close prices."""
    closes = np.array([float(c[4]) for c in candles])
    if len(closes) < 2:
        return np.array([])
    log_returns = np.diff(np.log(closes))
    return log_returns


def _calculate_skewness(returns: np.ndarray) -> float:
    """Calculate Fisher-Pearson skewness coefficient."""
    if len(returns) < 10:
        return 0.0
    return float(stats.skew(returns, bias=False))


def _calculate_quantile_position(skew: float, historical_skews: List[float]) -> float:
    """Calculate where current skew falls in historical distribution."""
    if len(historical_skews) < 10:
        return 0.5
    return float(stats.percentileofscore(historical_skews, skew) / 100.0)


def get_volatility_skew_signal(symbol: str) -> Dict[str, Any]:
    """
    Calculate volatility skew signal for a symbol.
    
    Returns:
        {
            'signal': 'LONG' | 'SHORT' | 'NEUTRAL',
            'confidence': float (0-1),
            'skew_value': float,
            'skew_interpretation': str,
            'quantile': float (0-1, where current skew falls historically),
            'reasons': List[str]
        }
    """
    cache_key = symbol.upper()
    now = time.time()
    
    if cache_key in SKEW_CACHE:
        cached = SKEW_CACHE[cache_key]
        if now - cached.get('ts', 0) < CACHE_TTL:
            return cached.get('result', _neutral_result())
    
    clean_symbol = symbol.upper().replace('-', '')
    if not clean_symbol.endswith('USDT'):
        clean_symbol = f"{clean_symbol}USDT"
    
    candles = _fetch_candles(clean_symbol, limit=LOOKBACK_PERIODS)
    if len(candles) < 20:
        result = _neutral_result("insufficient_candle_data")
        SKEW_CACHE[cache_key] = {'ts': now, 'result': result}
        return result
    
    log_returns = _calculate_log_returns(candles)
    if len(log_returns) < 10:
        result = _neutral_result("insufficient_return_data")
        SKEW_CACHE[cache_key] = {'ts': now, 'result': result}
        return result
    
    skew_value = _calculate_skewness(log_returns)
    
    rolling_skews = []
    window = 20
    for i in range(window, len(log_returns)):
        window_returns = log_returns[i-window:i]
        rolling_skews.append(_calculate_skewness(window_returns))
    
    quantile = _calculate_quantile_position(skew_value, rolling_skews) if rolling_skews else 0.5
    
    signal = 'NEUTRAL'
    confidence = 0.0
    interpretation = 'balanced'
    reasons = []
    
    if skew_value < -SKEW_THRESHOLD_EXTREME:
        signal = 'LONG'
        confidence = min(0.9, 0.5 + abs(skew_value) * 0.3)
        interpretation = 'extreme_negative_fear'
        reasons = [
            'vol_skew_extreme_negative',
            'loss_aversion_trigger',
            f'skew_{skew_value:.2f}_below_{-SKEW_THRESHOLD_EXTREME}'
        ]
    elif skew_value < -SKEW_THRESHOLD_STRONG:
        signal = 'LONG'
        confidence = min(0.7, 0.3 + abs(skew_value) * 0.3)
        interpretation = 'negative_fear'
        reasons = [
            'vol_skew_negative',
            'fear_elevated',
            f'skew_{skew_value:.2f}'
        ]
    elif skew_value > SKEW_THRESHOLD_EXTREME:
        signal = 'SHORT'
        confidence = min(0.9, 0.5 + abs(skew_value) * 0.3)
        interpretation = 'extreme_positive_complacency'
        reasons = [
            'vol_skew_extreme_positive',
            'complacency_trigger',
            f'skew_{skew_value:.2f}_above_{SKEW_THRESHOLD_EXTREME}'
        ]
    elif skew_value > SKEW_THRESHOLD_STRONG:
        signal = 'SHORT'
        confidence = min(0.7, 0.3 + abs(skew_value) * 0.3)
        interpretation = 'positive_complacency'
        reasons = [
            'vol_skew_positive',
            'complacency_elevated',
            f'skew_{skew_value:.2f}'
        ]
    else:
        interpretation = 'balanced'
        reasons = ['vol_skew_neutral', f'skew_{skew_value:.2f}']
    
    if quantile < 0.1:
        confidence = min(1.0, confidence * 1.2)
        reasons.append('skew_historically_extreme_low')
    elif quantile > 0.9:
        confidence = min(1.0, confidence * 1.2)
        reasons.append('skew_historically_extreme_high')
    
    result = {
        'signal': signal,
        'confidence': round(confidence, 3),
        'skew_value': round(skew_value, 4),
        'skew_interpretation': interpretation,
        'quantile': round(quantile, 3),
        'lookback_periods': len(log_returns),
        'reasons': reasons
    }
    
    SKEW_CACHE[cache_key] = {'ts': now, 'result': result}
    return result


def _neutral_result(reason: str = "no_data") -> Dict[str, Any]:
    """Return a neutral signal result."""
    return {
        'signal': 'NEUTRAL',
        'confidence': 0.0,
        'skew_value': 0.0,
        'skew_interpretation': 'unknown',
        'quantile': 0.5,
        'lookback_periods': 0,
        'reasons': [reason]
    }


if __name__ == "__main__":
    print("=" * 60)
    print("VOLATILITY SKEW SIGNAL - Test")
    print("=" * 60)
    
    test_symbols = ['BTCUSDT', 'ETHUSDT', 'SOLUSDT']
    
    for symbol in test_symbols:
        result = get_volatility_skew_signal(symbol)
        print(f"\n{symbol}:")
        print(f"  Signal: {result['signal']}")
        print(f"  Confidence: {result['confidence']}")
        print(f"  Skew Value: {result['skew_value']}")
        print(f"  Interpretation: {result['skew_interpretation']}")
        print(f"  Quantile: {result['quantile']}")
        print(f"  Reasons: {result['reasons']}")
