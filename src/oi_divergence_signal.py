#!/usr/bin/env python3
"""
OI DIVERGENCE SIGNAL - Trap Detection via Price/OI Divergence
==============================================================
Detects when price movement diverges from open interest changes,
indicating potential trap setups (long squeeze or short squeeze).

THEORY:
- Price Up + OI Flat/Down = Potential Long Trap (no new money entering)
  → Existing longs may be exiting, smart money shorting → SHORT signal
- Price Down + OI Flat/Down = Potential Short Trap (shorts covering)
  → Covering rally possible → LONG signal
- Price Up + OI Up = Healthy trend confirmation → No trap signal
- Price Down + OI Up = New shorts entering → Trend continuation

GAME THEORY:
This signal exploits the behavior of retail traders who chase price
without understanding position flow. When price moves but OI doesn't
follow, it suggests the move is driven by exits, not new conviction.

USAGE:
    from src.oi_divergence_signal import get_oi_divergence_signal
    signal = get_oi_divergence_signal('BTCUSDT')
"""

import time
import json
import requests
from pathlib import Path
from typing import Dict, Any, Optional, List
from datetime import datetime


COINGLASS_OI_FILE = Path("feature_store/intelligence/open_interest.json")
BLOFIN_API_URL = "https://openapi.blofin.com"
BINANCE_KLINES_URL = "https://api.binance.us/api/v3/klines"

OI_CACHE: Dict[str, Dict[str, Any]] = {}
CACHE_TTL = 120  # 2 minutes

PAPER_MODE = True
PRICE_CHANGE_THRESHOLD = 0.003 if PAPER_MODE else 0.005  # 0.3% vs 0.5%
OI_FLAT_THRESHOLD = 0.005 if PAPER_MODE else 0.01  # 0.5% vs 1%
DIVERGENCE_RATIO_THRESHOLD = 2.0 if PAPER_MODE else 3.0


def _load_coinglass_oi() -> Dict[str, Any]:
    """Load cached OI data from CoinGlass."""
    try:
        if COINGLASS_OI_FILE.exists():
            data = json.loads(COINGLASS_OI_FILE.read_text())
            return data
    except Exception as e:
        print(f"[OI-Div] Error loading CoinGlass OI: {e}")
    return {}


def _fetch_recent_price_change(symbol: str, lookback_candles: int = 4) -> Optional[float]:
    """Fetch recent price change % from Binance (last hour of 15m candles)."""
    try:
        clean_symbol = symbol.upper().replace('-', '')
        if not clean_symbol.endswith('USDT'):
            clean_symbol = f"{clean_symbol}USDT"
        
        params = {
            'symbol': clean_symbol,
            'interval': '15m',
            'limit': lookback_candles + 1
        }
        resp = requests.get(BINANCE_KLINES_URL, params=params, timeout=10)
        if resp.status_code == 200:
            candles = resp.json()
            if len(candles) >= 2:
                start_price = float(candles[0][1])  # Open of first candle
                end_price = float(candles[-1][4])   # Close of last candle
                return (end_price - start_price) / start_price
    except Exception as e:
        print(f"[OI-Div] Error fetching price for {symbol}: {e}")
    return None


def _get_oi_change(symbol: str) -> Optional[Dict[str, Any]]:
    """Get OI change data from cached CoinGlass data."""
    coinglass_data = _load_coinglass_oi()
    
    clean_symbol = symbol.upper().replace('-', '').replace('USDT', '')
    
    # Check new format: {"oi": {"BTC": {...}, "ETH": {...}}}
    if 'oi' in coinglass_data:
        oi_data = coinglass_data.get('oi', {})
        sym_data = oi_data.get(clean_symbol, {})
        if sym_data:
            return {
                'oi_current': sym_data.get('open_interest', 0),
                'oi_change_1h': sym_data.get('oi_change_1h', 0),
                'oi_change_4h': sym_data.get('oi_change_4h', 0),
                'oi_change_24h': sym_data.get('oi_change_24h', 0)
            }
    
    # Check legacy format: {"data": [...]}
    if 'data' in coinglass_data:
        for item in coinglass_data.get('data', []):
            if item.get('symbol', '').upper() == clean_symbol:
                return {
                    'oi_current': item.get('openInterest', 0),
                    'oi_change_1h': item.get('h1OiChangePercent', 0),
                    'oi_change_4h': item.get('h4OiChangePercent', 0),
                    'oi_change_24h': item.get('h24OiChangePercent', 0)
                }
    
    # Check another legacy format: {"symbols": {...}}
    if 'symbols' in coinglass_data:
        sym_data = coinglass_data['symbols'].get(clean_symbol, {})
        if sym_data:
            return {
                'oi_current': sym_data.get('oi', 0),
                'oi_change_1h': sym_data.get('oi_change_1h', 0),
                'oi_change_4h': sym_data.get('oi_change_4h', 0),
                'oi_change_24h': sym_data.get('oi_change_24h', 0)
            }
    
    return None


def get_oi_divergence_signal(symbol: str) -> Dict[str, Any]:
    """
    Detect price/OI divergence for trap detection.
    
    Returns:
        {
            'signal': 'LONG' | 'SHORT' | 'NEUTRAL',
            'confidence': float (0-1),
            'trap_type': 'long_trap' | 'short_trap' | 'none',
            'price_change': float,
            'oi_change': float,
            'divergence_ratio': float,
            'reasons': List[str]
        }
    """
    cache_key = symbol.upper()
    now = time.time()
    
    if cache_key in OI_CACHE:
        cached = OI_CACHE[cache_key]
        if now - cached.get('ts', 0) < CACHE_TTL:
            return cached.get('result', _neutral_result())
    
    price_change = _fetch_recent_price_change(symbol)
    if price_change is None:
        result = _neutral_result("price_fetch_failed")
        OI_CACHE[cache_key] = {'ts': now, 'result': result}
        return result
    
    oi_data = _get_oi_change(symbol)
    if oi_data is None:
        result = _neutral_result("oi_data_unavailable")
        OI_CACHE[cache_key] = {'ts': now, 'result': result}
        return result
    
    oi_change = oi_data.get('oi_change_1h', 0) / 100.0  # Convert to decimal
    
    signal = 'NEUTRAL'
    confidence = 0.0
    trap_type = 'none'
    reasons = []
    
    abs_price_change = abs(price_change)
    abs_oi_change = abs(oi_change)
    
    divergence_ratio = 0.0
    if abs_oi_change > 0.0001:
        divergence_ratio = abs_price_change / abs_oi_change
    elif abs_price_change > PRICE_CHANGE_THRESHOLD:
        divergence_ratio = 10.0  # High divergence when OI is flat
    
    price_moving = abs_price_change > PRICE_CHANGE_THRESHOLD
    oi_flat = abs_oi_change < OI_FLAT_THRESHOLD
    oi_opposite = (price_change > 0 and oi_change < -OI_FLAT_THRESHOLD) or \
                  (price_change < 0 and oi_change > OI_FLAT_THRESHOLD)
    
    if price_change > PRICE_CHANGE_THRESHOLD and (oi_flat or oi_change < 0):
        trap_type = 'long_trap'
        signal = 'SHORT'
        
        if oi_change < -OI_FLAT_THRESHOLD:
            confidence = min(0.85, 0.5 + abs(oi_change) * 5)
            reasons = [
                'price_up_oi_down_divergence',
                'long_trap_confirmed',
                f'price_+{price_change*100:.2f}%_oi_{oi_change*100:.2f}%'
            ]
        else:
            confidence = min(0.65, 0.3 + abs_price_change * 20)
            reasons = [
                'price_up_oi_flat',
                'potential_long_trap',
                f'price_+{price_change*100:.2f}%_oi_flat'
            ]
    
    elif price_change < -PRICE_CHANGE_THRESHOLD and (oi_flat or oi_change < 0):
        trap_type = 'short_trap'
        signal = 'LONG'
        
        if oi_change < -OI_FLAT_THRESHOLD:
            confidence = min(0.85, 0.5 + abs(oi_change) * 5)
            reasons = [
                'price_down_oi_down_shorts_covering',
                'short_trap_confirmed',
                f'price_{price_change*100:.2f}%_oi_{oi_change*100:.2f}%'
            ]
        else:
            confidence = min(0.65, 0.3 + abs_price_change * 20)
            reasons = [
                'price_down_oi_flat',
                'potential_short_squeeze',
                f'price_{price_change*100:.2f}%_oi_flat'
            ]
    
    else:
        if price_change > 0 and oi_change > OI_FLAT_THRESHOLD:
            reasons = ['healthy_uptrend_new_longs_entering']
        elif price_change < 0 and oi_change > OI_FLAT_THRESHOLD:
            reasons = ['downtrend_new_shorts_entering']
        else:
            reasons = ['no_clear_divergence']
    
    if divergence_ratio > DIVERGENCE_RATIO_THRESHOLD * 2:
        confidence = min(1.0, confidence * 1.3)
        reasons.append(f'extreme_divergence_ratio_{divergence_ratio:.1f}x')
    
    result = {
        'signal': signal,
        'confidence': round(confidence, 3),
        'trap_type': trap_type,
        'price_change': round(price_change, 5),
        'oi_change': round(oi_change, 5),
        'divergence_ratio': round(divergence_ratio, 2),
        'oi_data': oi_data,
        'reasons': reasons
    }
    
    OI_CACHE[cache_key] = {'ts': now, 'result': result}
    return result


def _neutral_result(reason: str = "no_data") -> Dict[str, Any]:
    """Return a neutral signal result."""
    return {
        'signal': 'NEUTRAL',
        'confidence': 0.0,
        'trap_type': 'none',
        'price_change': 0.0,
        'oi_change': 0.0,
        'divergence_ratio': 0.0,
        'oi_data': {},
        'reasons': [reason]
    }


if __name__ == "__main__":
    print("=" * 60)
    print("OI DIVERGENCE SIGNAL - Test")
    print("=" * 60)
    
    test_symbols = ['BTCUSDT', 'ETHUSDT', 'SOLUSDT']
    
    for symbol in test_symbols:
        result = get_oi_divergence_signal(symbol)
        print(f"\n{symbol}:")
        print(f"  Signal: {result['signal']}")
        print(f"  Confidence: {result['confidence']}")
        print(f"  Trap Type: {result['trap_type']}")
        print(f"  Price Change: {result['price_change']*100:.3f}%")
        print(f"  OI Change: {result['oi_change']*100:.3f}%")
        print(f"  Divergence Ratio: {result['divergence_ratio']}")
        print(f"  Reasons: {result['reasons']}")
