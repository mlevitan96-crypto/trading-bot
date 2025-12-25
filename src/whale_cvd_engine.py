"""
Whale CVD Engine - Institutional Flow Tracking
==============================================

Implements Cumulative Volume Delta (CVD) tracking with whale/retail bucketing
using CoinGlass taker buy/sell volume data.

Since the CoinGlass API doesn't provide granular trade-by-trade size data,
we use volume intensity patterns as a proxy for whale activity:
- High volume spikes (>3x average) = Whale activity indicator
- Cumulative Volume Delta (CVD) = Σ(buy_vol - sell_vol) over rolling window
- Whale intensity metric based on volume patterns

API Endpoint: /api/futures/taker-buy-sell-volume/exchange-list
"""

import os
import json
import time
from pathlib import Path
from datetime import datetime, timedelta
from typing import Dict, Any, Optional, List, Tuple
from collections import deque

from src.infrastructure.path_registry import PathRegistry

# Whale/Retail thresholds (USD)
WHALE_THRESHOLD = 50000.0  # >$50k = Whale
RETAIL_THRESHOLD = 5000.0  # <$5k = Retail

# Feature store paths
FEATURE_DIR = Path(PathRegistry.get_path("feature_store", "intelligence"))
WHALE_FLOW_FILE = FEATURE_DIR / "whale_flow.json"

FEATURE_DIR.mkdir(parents=True, exist_ok=True)

# In-memory cache for CVD history (rolling window)
_cvd_history: Dict[str, deque] = {}  # symbol -> deque of (timestamp, buy_vol, sell_vol)
_cvd_cache: Dict[str, Dict] = {}  # symbol -> latest CVD data


def _load_whale_flow_cache() -> Dict[str, Dict]:
    """Load cached whale flow data from disk."""
    if WHALE_FLOW_FILE.exists():
        try:
            return json.loads(WHALE_FLOW_FILE.read_text())
        except Exception as e:
            print(f"⚠️ [WHALE-CVD] Error loading cache: {e}", flush=True)
    return {}


def _save_whale_flow_cache(data: Dict[str, Dict]):
    """Save whale flow data to disk atomically."""
    try:
        # Use tmp file + rename for atomic write
        tmp_file = WHALE_FLOW_FILE.with_suffix('.tmp')
        tmp_file.write_text(json.dumps(data, indent=2, default=str))
        tmp_file.replace(WHALE_FLOW_FILE)
    except Exception as e:
        print(f"⚠️ [WHALE-CVD] Error saving cache: {e}", flush=True)


def calculate_cvd_from_volume(buy_vol: float, sell_vol: float, symbol: str) -> Dict[str, Any]:
    """
    Calculate Cumulative Volume Delta from buy/sell volume data.
    
    Since we don't have trade-by-trade data, we use:
    - Volume intensity as proxy for whale activity
    - Cumulative delta = buy_vol - sell_vol
    - Rolling average to detect trends
    
    Args:
        buy_vol: Total buy volume (USD)
        sell_vol: Total sell volume (USD)
        symbol: Trading symbol
    
    Returns:
        Dict with CVD metrics and whale intensity
    """
    global _cvd_history
    
    # Initialize history for symbol if needed
    if symbol not in _cvd_history:
        _cvd_history[symbol] = deque(maxlen=24)  # 24-hour rolling window
    
    now = time.time()
    delta = buy_vol - sell_vol
    
    # Add to history
    _cvd_history[symbol].append((now, buy_vol, sell_vol))
    
    # Calculate cumulative delta over rolling window
    cvd_total = sum(d[2] - d[1] for d in _cvd_history[symbol])  # buy - sell
    cvd_avg = cvd_total / len(_cvd_history[symbol]) if _cvd_history[symbol] else 0
    
    # Calculate volume intensity (proxy for whale activity)
    # High volume = whale activity indicator
    total_vol = buy_vol + sell_vol
    avg_vol = sum(d[1] + d[2] for d in _cvd_history[symbol]) / len(_cvd_history[symbol]) if _cvd_history[symbol] else total_vol
    volume_intensity = total_vol / avg_vol if avg_vol > 0 else 1.0
    
    # Whale intensity: based on volume spike (>3x = high whale activity)
    whale_intensity = min(100.0, (volume_intensity / 3.0) * 100.0) if volume_intensity > 1.0 else 0.0
    
    # Determine whale/retail classification
    # High volume + large delta = whale activity
    if total_vol > WHALE_THRESHOLD and abs(delta) > WHALE_THRESHOLD:
        flow_type = "whale"
    elif total_vol < RETAIL_THRESHOLD:
        flow_type = "retail"
    else:
        flow_type = "mixed"
    
    # CVD direction
    if cvd_total > 0:
        cvd_direction = "LONG"  # More buying pressure
    elif cvd_total < 0:
        cvd_direction = "SHORT"  # More selling pressure
    else:
        cvd_direction = "NEUTRAL"
    
    result = {
        "symbol": symbol,
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "ts": now,
        "buy_vol_usd": buy_vol,
        "sell_vol_usd": sell_vol,
        "net_vol_usd": delta,
        "total_vol_usd": total_vol,
        "cvd_total": cvd_total,
        "cvd_avg": cvd_avg,
        "cvd_direction": cvd_direction,
        "volume_intensity": round(volume_intensity, 3),
        "whale_intensity": round(whale_intensity, 2),
        "flow_type": flow_type,
        "history_size": len(_cvd_history[symbol])
    }
    
    # Update cache
    _cvd_cache[symbol] = result
    
    return result


def get_whale_cvd(symbol: str, use_cache: bool = True) -> Dict[str, Any]:
    """
    Get Whale CVD data for a symbol.
    
    Args:
        symbol: Trading symbol (e.g., "BTCUSDT")
        use_cache: Whether to use cached data (5 min TTL)
    
    Returns:
        Dict with CVD metrics and whale intensity
    """
    global _cvd_cache
    
    # Clean symbol
    clean_symbol = symbol.upper().replace('-', '').replace('USDT', '')
    
    # Check cache
    if use_cache and clean_symbol in _cvd_cache:
        cached = _cvd_cache[clean_symbol]
        cache_age = time.time() - cached.get("ts", 0)
        if cache_age < 300:  # 5 minute cache
            return cached
    
    # Try to load from CoinGlass data
    try:
        from src.market_intelligence import get_taker_buy_sell
        
        taker_data = get_taker_buy_sell()
        if clean_symbol in taker_data:
            symbol_data = taker_data[clean_symbol]
            buy_vol = symbol_data.get('buy_vol_usd', 0)
            sell_vol = symbol_data.get('sell_vol_usd', 0)
            
            cvd_data = calculate_cvd_from_volume(buy_vol, sell_vol, clean_symbol)
            
            # Save to persistent cache
            cache_data = _load_whale_flow_cache()
            cache_data[clean_symbol] = cvd_data
            _save_whale_flow_cache(cache_data)
            
            return cvd_data
    except Exception as e:
        print(f"⚠️ [WHALE-CVD] Error fetching data for {symbol}: {e}", flush=True)
    
    # Return empty/neutral data if fetch fails
    return {
        "symbol": clean_symbol,
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "ts": time.time(),
        "buy_vol_usd": 0.0,
        "sell_vol_usd": 0.0,
        "net_vol_usd": 0.0,
        "total_vol_usd": 0.0,
        "cvd_total": 0.0,
        "cvd_avg": 0.0,
        "cvd_direction": "NEUTRAL",
        "volume_intensity": 1.0,
        "whale_intensity": 0.0,
        "flow_type": "unknown",
        "history_size": 0
    }


def check_whale_cvd_alignment(symbol: str, signal_direction: str) -> Tuple[bool, str, Dict[str, Any]]:
    """
    Check if Whale CVD aligns with signal direction.
    
    Args:
        symbol: Trading symbol
        signal_direction: Signal direction ("LONG" or "SHORT")
    
    Returns:
        Tuple of (aligned: bool, reason: str, cvd_data: dict)
        - aligned: True if Whale CVD aligns with signal direction
        - reason: Explanation ("ALIGNED", "DIVERGING", "NEUTRAL", "INSUFFICIENT_DATA")
        - cvd_data: Complete CVD metrics
    """
    cvd_data = get_whale_cvd(symbol)
    cvd_direction = cvd_data.get("cvd_direction", "NEUTRAL")
    whale_intensity = cvd_data.get("whale_intensity", 0.0)
    
    # If whale intensity is low, don't block (insufficient data)
    if whale_intensity < 30.0:
        return True, "INSUFFICIENT_DATA", cvd_data
    
    # Check alignment
    if cvd_direction == signal_direction:
        return True, "ALIGNED", cvd_data
    elif cvd_direction == "NEUTRAL":
        return True, "NEUTRAL", cvd_data
    else:
        return False, "DIVERGING", cvd_data


def get_all_whale_cvd(symbols: List[str]) -> Dict[str, Dict]:
    """
    Get Whale CVD data for multiple symbols.
    
    Args:
        symbols: List of trading symbols
    
    Returns:
        Dict mapping symbol to CVD data
    """
    results = {}
    for symbol in symbols:
        results[symbol] = get_whale_cvd(symbol)
    return results

