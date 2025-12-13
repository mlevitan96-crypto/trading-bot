"""
BTC/ETH Lead-Lag Signal Detection

Detects when BTC price movements lead ETH (or other altcoins) to generate
predictive signals. Research shows BTC often leads altcoin moves by 5-15 minutes.

Signal Logic:
- Calculate rolling correlation between BTC and target asset at different lags
- If BTC leads by 5-15 min with high correlation → signal target in BTC's direction
- Uses cross-correlation and optionally Dynamic Time Warping (DTW)
"""

import numpy as np
from typing import Dict, Any, Optional, Tuple, List
from datetime import datetime, timedelta
from pathlib import Path
import json
import time

CACHE_FILE = Path("feature_store/lead_lag_cache.json")
CACHE_TTL_SECONDS = 180  # 3-minute cache


def _load_cache() -> Dict[str, Any]:
    """Load cached lead-lag calculations."""
    try:
        if CACHE_FILE.exists():
            with open(CACHE_FILE, 'r') as f:
                return json.load(f)
    except Exception:
        pass
    return {}


def _save_cache(cache: Dict[str, Any]) -> None:
    """Save lead-lag cache."""
    try:
        CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(CACHE_FILE, 'w') as f:
            json.dump(cache, f, indent=2)
    except Exception:
        pass


def _is_cache_valid(cache_entry: Dict[str, Any]) -> bool:
    """Check if cache entry is still valid."""
    if not cache_entry:
        return False
    cached_at = cache_entry.get('cached_at', 0)
    return (time.time() - cached_at) < CACHE_TTL_SECONDS


def fetch_price_series(symbol: str, limit: int = 60) -> Optional[List[float]]:
    """
    Fetch recent 1-minute candle close prices for a symbol.
    Returns list of close prices (oldest to newest).
    """
    try:
        from src.blofin_client import BlofinClient
        client = BlofinClient()
        
        clean_symbol = symbol.upper().replace('USDT', '').replace('-', '')
        blofin_symbol = f"{clean_symbol}-USDT"
        
        candles = client.get_ohlcv(blofin_symbol, timeframe='1m', limit=limit)
        
        if candles and len(candles) >= 20:
            closes = [float(c[4]) for c in candles]  # Close price is index 4
            return closes
    except Exception as e:
        pass
    
    # Fallback to Binance.US
    try:
        import requests
        clean_symbol = symbol.upper().replace('-', '')
        if not clean_symbol.endswith('USDT'):
            clean_symbol = f"{clean_symbol}USDT"
        
        url = f"https://api.binance.us/api/v3/klines"
        params = {
            'symbol': clean_symbol,
            'interval': '1m',
            'limit': limit
        }
        
        resp = requests.get(url, params=params, timeout=10)
        if resp.status_code == 200:
            data = resp.json()
            if data and len(data) >= 20:
                closes = [float(candle[4]) for candle in data]
                return closes
    except Exception:
        pass
    
    return None


def calculate_returns(prices: List[float]) -> np.ndarray:
    """Calculate log returns from price series."""
    prices_arr = np.array(prices)
    returns = np.diff(np.log(prices_arr))
    return returns


def _safe_corrcoef(a: np.ndarray, b: np.ndarray) -> float:
    """Safe correlation that handles zero-variance series without warnings."""
    if len(a) < 2 or len(b) < 2:
        return 0.0
    std_a = np.std(a)
    std_b = np.std(b)
    if std_a == 0 or std_b == 0:
        return 0.0
    with np.errstate(invalid='ignore', divide='ignore'):
        result = np.corrcoef(a, b)[0, 1]
    return 0.0 if np.isnan(result) else float(result)


def cross_correlation_at_lag(series1: np.ndarray, series2: np.ndarray, lag: int) -> float:
    """
    Calculate correlation between series1 and series2 with series1 leading by 'lag' periods.
    
    Positive lag: series1 leads series2
    Negative lag: series2 leads series1
    """
    if lag == 0:
        return _safe_corrcoef(series1, series2)
    elif lag > 0:
        if lag >= len(series1):
            return 0.0
        return _safe_corrcoef(series1[:-lag], series2[lag:])
    else:
        lag = abs(lag)
        if lag >= len(series1):
            return 0.0
        return _safe_corrcoef(series1[lag:], series2[:-lag])


def find_optimal_lag(
    leader_returns: np.ndarray,
    follower_returns: np.ndarray,
    max_lag: int = 15
) -> Tuple[int, float]:
    """
    Find the lag at which leader best predicts follower.
    
    Returns:
        (optimal_lag, correlation) where positive lag means leader leads follower
    """
    best_lag = 0
    best_corr = 0.0
    
    # Test lags from 0 to max_lag (leader leading)
    for lag in range(0, max_lag + 1):
        try:
            corr = cross_correlation_at_lag(leader_returns, follower_returns, lag)
            if not np.isnan(corr) and abs(corr) > abs(best_corr):
                best_corr = corr
                best_lag = lag
        except Exception:
            continue
    
    return (best_lag, best_corr)


def _is_paper_mode() -> bool:
    """Check if running in paper mode."""
    try:
        import os
        return os.environ.get('TRADING_MODE', 'paper').lower() == 'paper'
    except:
        return True


def get_recent_direction(returns: np.ndarray, lookback: int = 10) -> Tuple[str, float]:
    """
    Determine recent price direction from returns.
    
    Returns:
        (direction, strength) where direction is 'LONG', 'SHORT', or 'NEUTRAL'
    """
    if len(returns) < lookback:
        lookback = len(returns)
    
    if lookback == 0:
        return ('NEUTRAL', 0.0)
    
    recent = returns[-lookback:]
    cumulative_return = float(np.sum(recent))
    
    # Paper mode: lower threshold to collect more data (5 bps vs 10 bps)
    threshold = 0.0005 if _is_paper_mode() else 0.001
    
    if cumulative_return > threshold:
        # Scale strength: max at 0.3% move in paper, 0.5% in live
        scale = 0.003 if _is_paper_mode() else 0.005
        strength = min(1.0, abs(cumulative_return) / scale)
        return ('LONG', strength)
    elif cumulative_return < -threshold:
        scale = 0.003 if _is_paper_mode() else 0.005
        strength = min(1.0, abs(cumulative_return) / scale)
        return ('SHORT', strength)
    else:
        return ('NEUTRAL', 0.0)


def calculate_lead_lag_signal(
    target_symbol: str,
    leader_symbol: str = "BTCUSDT",
    use_cache: bool = True
) -> Dict[str, Any]:
    """
    Calculate lead-lag signal for target_symbol based on leader_symbol.
    
    If BTC has moved recently and the correlation shows BTC leads the target,
    signal the target to follow BTC's direction.
    
    Args:
        target_symbol: The symbol to generate signal for (e.g., 'ETHUSDT')
        leader_symbol: The leading indicator (default: 'BTCUSDT')
        use_cache: Whether to use cached results
    
    Returns:
        Signal dict with direction, confidence, lag info, and reasons
    """
    cache_key = f"{leader_symbol}_{target_symbol}"
    
    # Check cache
    if use_cache:
        cache = _load_cache()
        if cache_key in cache and _is_cache_valid(cache.get(cache_key, {})):
            cached = cache[cache_key]
            return {
                'signal': cached.get('signal', 'NEUTRAL'),
                'confidence': cached.get('confidence', 0),
                'optimal_lag': cached.get('optimal_lag', 0),
                'correlation': cached.get('correlation', 0),
                'leader_direction': cached.get('leader_direction', 'NEUTRAL'),
                'leader_strength': cached.get('leader_strength', 0),
                'reasons': cached.get('reasons', ['cached_result']),
                'cached': True
            }
    
    # Default neutral result
    neutral_result = {
        'signal': 'NEUTRAL',
        'confidence': 0,
        'optimal_lag': 0,
        'correlation': 0,
        'leader_direction': 'NEUTRAL',
        'leader_strength': 0,
        'reasons': ['insufficient_data'],
        'cached': False
    }
    
    # Skip if target is the leader
    clean_target = target_symbol.upper().replace('-', '').replace('USDT', '')
    clean_leader = leader_symbol.upper().replace('-', '').replace('USDT', '')
    if clean_target == clean_leader:
        neutral_result['reasons'] = ['target_is_leader']
        return neutral_result
    
    # Fetch price series for both
    leader_prices = fetch_price_series(leader_symbol, limit=60)
    target_prices = fetch_price_series(target_symbol, limit=60)
    
    if not leader_prices or not target_prices:
        neutral_result['reasons'] = ['price_fetch_failed']
        return neutral_result
    
    if len(leader_prices) < 20 or len(target_prices) < 20:
        neutral_result['reasons'] = ['insufficient_candles']
        return neutral_result
    
    # Calculate returns
    leader_returns = calculate_returns(leader_prices)
    target_returns = calculate_returns(target_prices)
    
    # Ensure same length
    min_len = min(len(leader_returns), len(target_returns))
    leader_returns = leader_returns[-min_len:]
    target_returns = target_returns[-min_len:]
    
    # Find optimal lag
    optimal_lag, correlation = find_optimal_lag(leader_returns, target_returns, max_lag=15)
    
    # Get leader's recent direction
    leader_dir, leader_strength = get_recent_direction(leader_returns, lookback=5)
    
    # Generate signal
    signal = 'NEUTRAL'
    confidence = 0.0
    reasons = []
    
    # Signal conditions (relaxed in paper mode for data collection):
    # 1. Leader has moved significantly
    # 2. Optimal lag shows leader leads (lag >= 2 minutes)
    # 3. Correlation strength (positive = follow, negative = inverse)
    
    paper_mode = _is_paper_mode()
    min_strength = 0.15 if paper_mode else 0.3
    min_lag = 2 if paper_mode else 3
    min_corr = 0.3 if paper_mode else 0.5
    
    abs_corr = abs(correlation)
    is_inverse = correlation < 0
    
    if leader_dir != 'NEUTRAL' and leader_strength >= min_strength:
        if optimal_lag >= min_lag and abs_corr >= min_corr:
            if is_inverse:
                # Inverse correlation: signal opposite to leader
                signal = 'SHORT' if leader_dir == 'LONG' else 'LONG'
                confidence = min(1.0, abs_corr * leader_strength * 1.2)
                reasons = [
                    f"btc_leads_by_{optimal_lag}m",
                    f"inverse_corr_{correlation:.2f}",
                    f"btc_{leader_dir.lower()}_target_inverse"
                ]
            else:
                # Positive correlation: signal same as leader
                signal = leader_dir
                confidence = min(1.0, abs_corr * leader_strength * 1.5)
                reasons = [
                    f"btc_leads_by_{optimal_lag}m",
                    f"corr_{correlation:.2f}",
                    f"btc_{leader_dir.lower()}_{leader_strength:.2f}"
                ]
        elif optimal_lag >= 1 and abs_corr >= 0.5:
            # Weaker signal with shorter lag but higher correlation
            if is_inverse:
                signal = 'SHORT' if leader_dir == 'LONG' else 'LONG'
            else:
                signal = leader_dir
            confidence = min(0.6, abs_corr * leader_strength)
            reasons = [
                f"btc_slight_lead_{optimal_lag}m",
                f"{'inverse_' if is_inverse else ''}corr_{correlation:.2f}"
            ]
        else:
            reasons = [
                f"lag_{optimal_lag}m_below_{min_lag}" if optimal_lag < min_lag else f"weak_corr_{correlation:.2f}"
            ]
    else:
        if leader_dir == 'NEUTRAL':
            reasons = ['btc_no_significant_move']
        else:
            reasons = [f'btc_strength_{leader_strength:.2f}_below_{min_strength}']
    
    result = {
        'signal': signal,
        'confidence': float(confidence),
        'optimal_lag': int(optimal_lag),
        'correlation': float(correlation),
        'leader_direction': leader_dir,
        'leader_strength': float(leader_strength),
        'reasons': reasons,
        'cached': False
    }
    
    # Save to cache
    cache = _load_cache()
    cache[cache_key] = {
        **result,
        'cached_at': time.time()
    }
    _save_cache(cache)
    
    return result


def get_lead_lag_signal(symbol: str, use_cache: bool = True) -> Dict[str, Any]:
    """
    Get lead-lag signal for a symbol (convenience wrapper).
    
    For ETH and altcoins, checks if BTC is leading.
    For BTC, returns neutral (BTC is the leader, doesn't follow).
    
    Returns signal dict compatible with predictive flow engine.
    """
    clean_symbol = symbol.upper().replace('-', '')
    if not clean_symbol.endswith('USDT'):
        clean_symbol = f"{clean_symbol}USDT"
    
    # BTC is the leader, doesn't follow anyone
    if 'BTC' in clean_symbol:
        return {
            'signal': 'NEUTRAL',
            'confidence': 0,
            'optimal_lag': 0,
            'correlation': 0,
            'leader_direction': 'NEUTRAL',
            'leader_strength': 0,
            'reasons': ['btc_is_leader'],
            'cached': False
        }
    
    # Check BTC lead-lag for this symbol
    result = calculate_lead_lag_signal(
        target_symbol=clean_symbol,
        leader_symbol="BTCUSDT",
        use_cache=use_cache
    )
    
    return result


def get_multi_leader_signal(symbol: str, use_cache: bool = True) -> Dict[str, Any]:
    """
    Check multiple leaders (BTC and ETH) for lead-lag signals.
    
    Combines signals from both BTC and ETH as potential leaders.
    """
    clean_symbol = symbol.upper().replace('-', '')
    if not clean_symbol.endswith('USDT'):
        clean_symbol = f"{clean_symbol}USDT"
    
    # Skip for BTC and ETH (they are leaders)
    if 'BTC' in clean_symbol:
        return {
            'signal': 'NEUTRAL',
            'confidence': 0,
            'reasons': ['btc_is_leader'],
            'cached': False
        }
    
    # Check BTC first
    btc_signal = calculate_lead_lag_signal(clean_symbol, "BTCUSDT", use_cache)
    
    # For ETH, only check BTC
    if 'ETH' in clean_symbol:
        return btc_signal
    
    # For altcoins, also check ETH as secondary leader
    eth_signal = calculate_lead_lag_signal(clean_symbol, "ETHUSDT", use_cache)
    
    # Combine signals - prefer stronger signal
    if btc_signal['confidence'] >= eth_signal['confidence']:
        result = btc_signal.copy()
        if eth_signal['signal'] == btc_signal['signal'] and eth_signal['signal'] != 'NEUTRAL':
            # Both agree - boost confidence
            result['confidence'] = min(1.0, btc_signal['confidence'] * 1.2)
            result['reasons'].append('eth_confirms')
    else:
        result = eth_signal.copy()
        result['reasons'] = [r.replace('btc', 'eth') for r in result['reasons']]
    
    return result


if __name__ == "__main__":
    print("Testing Lead-Lag Signal Detection...")
    print("=" * 60)
    
    # Test for various symbols
    test_symbols = ["ETHUSDT", "SOLUSDT", "BTCUSDT", "AVAXUSDT"]
    
    for symbol in test_symbols:
        print(f"\n{symbol}:")
        result = get_lead_lag_signal(symbol, use_cache=False)
        print(f"  Signal: {result['signal']}")
        print(f"  Confidence: {result['confidence']:.3f}")
        print(f"  Optimal Lag: {result['optimal_lag']} minutes")
        print(f"  Correlation: {result['correlation']:.3f}")
        print(f"  BTC Direction: {result['leader_direction']} ({result['leader_strength']:.2f})")
        print(f"  Reasons: {result['reasons']}")
    
    print("\n" + "=" * 60)
    print("Lead-Lag Signal test complete!")
