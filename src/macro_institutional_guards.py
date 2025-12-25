"""
Macro-Institutional Guards (BIG ALPHA PHASE 2)
==============================================

Integrates Institutional Macro Context from CoinGlass V4 API to act as high-level filters
for the existing signal pipeline.

Data Sources:
1. Liquidation Heatmap Model 1 - Identify major liquidation clusters
2. OI Velocity - 5-minute Open Interest Delta calculation
3. Global Long/Short Account Ratio - Retail sentiment trap detection

All API calls respect the 2.5s rate limit and use existing caching layer.
"""

import os
import json
import time
from pathlib import Path
from datetime import datetime, timedelta
from typing import Dict, Any, Optional, List, Tuple

from src.infrastructure.path_registry import PathRegistry

# CoinGlass V4 API
COINGLASS_URL = "https://open-api-v4.coinglass.com"
COINGLASS_API_KEY = os.environ.get('COINGLASS_API_KEY', '')

# Feature store paths
FEATURE_DIR = Path(PathRegistry.get_path("feature_store", "intelligence"))
MACRO_GUARDS_CACHE = FEATURE_DIR / "macro_guards.json"

FEATURE_DIR.mkdir(parents=True, exist_ok=True)

# Cache TTL (5 minutes)
CACHE_TTL_SECONDS = 300

# In-memory cache
_cache: Dict[str, Dict] = {}
_cache_timestamp: Dict[str, float] = {}


def _rate_limit():
    """Enforce CoinGlass rate limit using centralized rate limiter."""
    try:
        from src.coinglass_rate_limiter import wait_for_rate_limit
        wait_for_rate_limit()
    except ImportError:
        # Fallback to simple delay if rate limiter not available
        global _last_call_time
        if '_last_call_time' not in globals():
            _last_call_time = 0.0
        elapsed = time.time() - _last_call_time
        if elapsed < 2.5:
            time.sleep(2.5 - elapsed)
        _last_call_time = time.time()


def _coinglass_get(endpoint: str, params: Optional[Dict] = None) -> Optional[Dict]:
    """Make rate-limited request to CoinGlass V4 API."""
    if not COINGLASS_API_KEY:
        return None
    
    _rate_limit()
    
    import requests
    url = f"{COINGLASS_URL}{endpoint}"
    headers = {'accept': 'application/json', 'CG-API-KEY': COINGLASS_API_KEY}
    
    try:
        resp = requests.get(url, headers=headers, params=params or {}, timeout=15)
        if resp.status_code == 200:
            data = resp.json()
            if data.get('code') == '0':
                return data
        return None
    except Exception as e:
        print(f"⚠️ [MACRO-GUARDS] API error for {endpoint}: {e}", flush=True)
        return None


def _load_cache() -> Dict:
    """Load cached macro guard data from disk."""
    if MACRO_GUARDS_CACHE.exists():
        try:
            return json.loads(MACRO_GUARDS_CACHE.read_text())
        except Exception:
            pass
    return {}


def _save_cache(data: Dict):
    """Save macro guard data to disk atomically."""
    try:
        tmp_file = MACRO_GUARDS_CACHE.with_suffix('.tmp')
        tmp_file.write_text(json.dumps(data, indent=2, default=str))
        tmp_file.replace(MACRO_GUARDS_CACHE)
    except Exception as e:
        print(f"⚠️ [MACRO-GUARDS] Error saving cache: {e}", flush=True)


def get_liquidation_heatmap(symbol: str, current_price: float) -> Dict[str, Any]:
    """
    Fetch Liquidation Heatmap Model 1 and identify major liquidation clusters within 1% of current price.
    
    Endpoint: /api/futures/liquidation/aggregated-heatmap/model1
    
    Args:
        symbol: Trading symbol (e.g., "BTCUSDT")
        current_price: Current market price
    
    Returns:
        Dict with liquidation clusters and proximity data
    """
    cache_key = f"liq_heatmap_{symbol}"
    now = time.time()
    
    # Check in-memory cache
    if cache_key in _cache and cache_key in _cache_timestamp:
        if now - _cache_timestamp[cache_key] < CACHE_TTL_SECONDS:
            return _cache[cache_key]
    
    # Check disk cache
    disk_cache = _load_cache()
    if cache_key in disk_cache:
        cached_data = disk_cache[cache_key]
        cache_age = now - cached_data.get("ts", 0)
        if cache_age < CACHE_TTL_SECONDS:
            _cache[cache_key] = cached_data
            _cache_timestamp[cache_key] = now
            return cached_data
    
    # Clean symbol (remove USDT, convert to format CoinGlass expects)
    clean_symbol = symbol.upper().replace('-', '').replace('USDT', '')
    
    # Fetch from API
    data = _coinglass_get("/api/futures/liquidation/aggregated-heatmap/model1", {
        "symbol": clean_symbol
    })
    
    result = {
        "symbol": symbol,
        "current_price": current_price,
        "ts": now,
        "clusters": [],
        "short_liq_clusters_nearby": [],
        "long_liq_clusters_nearby": [],
        "has_nearby_short_liq": False,
        "has_nearby_long_liq": False,
        "error": None
    }
    
    if not data or 'data' not in data:
        result["error"] = "No data from API"
        return result
    
    try:
        heatmap_data = data.get('data', {})
        
        # Parse clusters (structure depends on CoinGlass API response)
        # Assuming clusters are returned as list of {price, long_liq, short_liq, ...}
        clusters = []
        if isinstance(heatmap_data, list):
            clusters = heatmap_data
        elif isinstance(heatmap_data, dict):
            clusters = heatmap_data.get('clusters', []) or heatmap_data.get('data', [])
        
        # Identify clusters within 1% of current price
        price_tolerance = current_price * 0.01  # 1%
        nearby_short = []
        nearby_long = []
        
        for cluster in clusters:
            if not isinstance(cluster, dict):
                continue
            
            cluster_price = float(cluster.get('price', cluster.get('priceLevel', 0)))
            if cluster_price <= 0:
                continue
            
            # Calculate distance from current price
            price_diff_pct = abs(cluster_price - current_price) / current_price if current_price > 0 else 999
            
            if price_diff_pct <= 0.01:  # Within 1%
                short_liq = float(cluster.get('shortLiquidation', cluster.get('short_liq', 0)))
                long_liq = float(cluster.get('longLiquidation', cluster.get('long_liq', 0)))
                
                cluster_info = {
                    "price": cluster_price,
                    "distance_pct": price_diff_pct * 100,
                    "short_liq": short_liq,
                    "long_liq": long_liq
                }
                
                if short_liq > 0:
                    nearby_short.append(cluster_info)
                if long_liq > 0:
                    nearby_long.append(cluster_info)
        
        result["clusters"] = clusters[:10]  # Store first 10 for reference
        result["short_liq_clusters_nearby"] = nearby_short
        result["long_liq_clusters_nearby"] = nearby_long
        result["has_nearby_short_liq"] = len(nearby_short) > 0
        result["has_nearby_long_liq"] = len(nearby_long) > 0
        
    except Exception as e:
        result["error"] = str(e)
        print(f"⚠️ [MACRO-GUARDS] Error parsing liquidation heatmap for {symbol}: {e}", flush=True)
    
    # Update caches
    _cache[cache_key] = result
    _cache_timestamp[cache_key] = now
    disk_cache[cache_key] = result
    _save_cache(disk_cache)
    
    return result


def get_oi_velocity(symbol: str) -> Dict[str, Any]:
    """
    Fetch Aggregated OI OHLC and calculate 5-minute OI Delta.
    
    Endpoint: /api/futures/open-interest/aggregated-history
    
    OI Delta = Current OI - OI 5 minutes ago
    Positive delta = new money entering (bullish)
    Negative delta = money leaving (bearish)
    
    Args:
        symbol: Trading symbol (e.g., "BTCUSDT")
    
    Returns:
        Dict with OI velocity metrics
    """
    cache_key = f"oi_velocity_{symbol}"
    now = time.time()
    
    # Check in-memory cache
    if cache_key in _cache and cache_key in _cache_timestamp:
        if now - _cache_timestamp[cache_key] < 60:  # 1 minute cache for OI (more dynamic)
            return _cache[cache_key]
    
    # Check disk cache
    disk_cache = _load_cache()
    if cache_key in disk_cache:
        cached_data = disk_cache[cache_key]
        cache_age = now - cached_data.get("ts", 0)
        if cache_age < 60:  # 1 minute cache
            _cache[cache_key] = cached_data
            _cache_timestamp[cache_key] = now
            return cached_data
    
    # Clean symbol
    clean_symbol = symbol.upper().replace('-', '').replace('USDT', '')
    
    # Fetch from API (request last 10 minutes of data to calculate 5m delta)
    end_time = int(now * 1000)  # milliseconds
    start_time = int((now - 600) * 1000)  # 10 minutes ago
    
    data = _coinglass_get("/api/futures/open-interest/aggregated-history", {
        "symbol": clean_symbol,
        "interval": "5m",  # 5-minute intervals
        "startTime": start_time,
        "endTime": end_time
    })
    
    result = {
        "symbol": symbol,
        "ts": now,
        "oi_delta_5m": 0.0,
        "oi_delta_5m_pct": 0.0,
        "current_oi": 0.0,
        "oi_5m_ago": 0.0,
        "is_positive": False,
        "error": None
    }
    
    if not data or 'data' not in data:
        result["error"] = "No data from API"
        return result
    
    try:
        oi_data = data.get('data', {})
        
        # Parse OI history (structure depends on API response)
        oi_history = []
        if isinstance(oi_data, list):
            oi_history = oi_data
        elif isinstance(oi_data, dict):
            oi_history = oi_data.get('data', []) or oi_data.get('history', [])
        
        if len(oi_history) < 2:
            result["error"] = "Insufficient data points"
            return result
        
        # Sort by timestamp (most recent first or last)
        oi_history = sorted(oi_history, key=lambda x: float(x.get('time', x.get('timestamp', 0))))
        
        # Get current OI (most recent)
        current_oi = float(oi_history[-1].get('openInterest', oi_history[-1].get('oi', 0)))
        
        # Get OI 5 minutes ago (second-to-last, or calculate based on time)
        target_time = now - 300  # 5 minutes ago
        oi_5m_ago = current_oi
        
        for item in oi_history:
            item_time = float(item.get('time', item.get('timestamp', 0))) / 1000.0  # Convert ms to seconds
            if item_time <= target_time:
                oi_5m_ago = float(item.get('openInterest', item.get('oi', current_oi)))
                break
        
        # Calculate delta
        oi_delta = current_oi - oi_5m_ago
        oi_delta_pct = (oi_delta / oi_5m_ago * 100) if oi_5m_ago > 0 else 0.0
        
        result["current_oi"] = current_oi
        result["oi_5m_ago"] = oi_5m_ago
        result["oi_delta_5m"] = oi_delta
        result["oi_delta_5m_pct"] = oi_delta_pct
        result["is_positive"] = oi_delta > 0
        
    except Exception as e:
        result["error"] = str(e)
        print(f"⚠️ [MACRO-GUARDS] Error parsing OI velocity for {symbol}: {e}", flush=True)
    
    # Update caches
    _cache[cache_key] = result
    _cache_timestamp[cache_key] = now
    disk_cache[cache_key] = result
    _save_cache(disk_cache)
    
    return result


def get_retail_long_short_ratio(symbol: str) -> Dict[str, Any]:
    """
    Fetch Global Long/Short Account Ratio History.
    
    Endpoint: /api/futures/global-long-short-account-ratio/history
    
    High Long/Short ratio (>2.0) = retail is very long = potential trap (contrarian signal)
    
    Args:
        symbol: Trading symbol (e.g., "BTCUSDT")
    
    Returns:
        Dict with ratio metrics
    """
    cache_key = f"retail_ratio_{symbol}"
    now = time.time()
    
    # Check in-memory cache
    if cache_key in _cache and cache_key in _cache_timestamp:
        if now - _cache_timestamp[cache_key] < 60:  # 1 minute cache
            return _cache[cache_key]
    
    # Check disk cache
    disk_cache = _load_cache()
    if cache_key in disk_cache:
        cached_data = disk_cache[cache_key]
        cache_age = now - cached_data.get("ts", 0)
        if cache_age < 60:
            _cache[cache_key] = cached_data
            _cache_timestamp[cache_key] = now
            return cached_data
    
    # Clean symbol
    clean_symbol = symbol.upper().replace('-', '').replace('USDT', '')
    
    # Fetch from API (get most recent data point)
    data = _coinglass_get("/api/futures/global-long-short-account-ratio/history", {
        "symbol": clean_symbol,
        "limit": 1  # Just need latest
    })
    
    result = {
        "symbol": symbol,
        "ts": now,
        "long_short_ratio": 1.0,
        "is_long_trap": False,  # Ratio > 2.0 = retail very long = trap
        "error": None
    }
    
    if not data or 'data' not in data:
        result["error"] = "No data from API"
        return result
    
    try:
        ratio_data = data.get('data', {})
        
        # Parse ratio (structure depends on API response)
        if isinstance(ratio_data, list) and len(ratio_data) > 0:
            latest = ratio_data[-1]
            ratio = float(latest.get('longShortRatio', latest.get('ratio', 1.0)))
        elif isinstance(ratio_data, dict):
            ratio = float(ratio_data.get('longShortRatio', ratio_data.get('ratio', 1.0)))
        else:
            result["error"] = "Unexpected data format"
            return result
        
        result["long_short_ratio"] = ratio
        result["is_long_trap"] = ratio > 2.0
        
    except Exception as e:
        result["error"] = str(e)
        print(f"⚠️ [MACRO-GUARDS] Error parsing retail ratio for {symbol}: {e}", flush=True)
    
    # Update caches
    _cache[cache_key] = result
    _cache_timestamp[cache_key] = now
    disk_cache[cache_key] = result
    _save_cache(disk_cache)
    
    return result


def check_liquidation_wall_conflict(symbol: str, signal_direction: str, current_price: float) -> Tuple[bool, str, Dict]:
    """
    Check if signal conflicts with nearby liquidation walls.
    
    Blocks LONG signals if they occur within 0.5% of a significant Short Liquidation cluster.
    
    Args:
        symbol: Trading symbol
        signal_direction: "LONG" or "SHORT"
        current_price: Current market price
    
    Returns:
        Tuple of (should_block: bool, reason: str, data: dict)
    """
    if signal_direction.upper() != "LONG":
        # Only block LONG signals near short liquidation walls
        return False, "NOT_LONG_SIGNAL", {}
    
    heatmap = get_liquidation_heatmap(symbol, current_price)
    
    if heatmap.get("error"):
        # Fail open if we can't get data
        return False, "NO_DATA", heatmap
    
    # Check for short liquidation clusters within 0.5% (tighter than 1% used for detection)
    nearby_short = heatmap.get("short_liq_clusters_nearby", [])
    price_tolerance_pct = 0.005  # 0.5%
    
    for cluster in nearby_short:
        distance_pct = cluster.get("distance_pct", 999) / 100.0
        if distance_pct <= price_tolerance_pct:
            short_liq_amount = cluster.get("short_liq", 0)
            # Only block if there's significant liquidity
            if short_liq_amount > 0:
                return True, "LIQ_WALL_CONFLICT", {
                    "cluster_price": cluster.get("price"),
                    "distance_pct": distance_pct * 100,
                    "short_liq_amount": short_liq_amount,
                    "heatmap": heatmap
                }
    
    return False, "NO_CONFLICT", heatmap


def check_oi_velocity_positive(symbol: str) -> Tuple[bool, float]:
    """
    Check if OI velocity is positive (new money entering).
    
    Returns:
        Tuple of (is_positive: bool, oi_delta_5m: float)
    """
    oi_data = get_oi_velocity(symbol)
    
    if oi_data.get("error"):
        # Fail open if we can't get data
        return True, 0.0
    
    return oi_data.get("is_positive", False), oi_data.get("oi_delta_5m", 0.0)


def check_long_trap(symbol: str) -> Tuple[bool, float]:
    """
    Check if retail is in a long trap (Long/Short ratio > 2.0).
    
    Returns:
        Tuple of (is_trap: bool, ratio: float)
    """
    ratio_data = get_retail_long_short_ratio(symbol)
    
    if ratio_data.get("error"):
        # Fail open if we can't get data
        return False, 1.0
    
    return ratio_data.get("is_long_trap", False), ratio_data.get("long_short_ratio", 1.0)


def get_all_macro_data(symbol: str, current_price: float) -> Dict[str, Any]:
    """
    Get all macro institutional guard data for a symbol.
    
    Returns combined data for dashboard display and analysis.
    """
    return {
        "symbol": symbol,
        "current_price": current_price,
        "liquidation_heatmap": get_liquidation_heatmap(symbol, current_price),
        "oi_velocity": get_oi_velocity(symbol),
        "retail_ratio": get_retail_long_short_ratio(symbol),
        "ts": time.time()
    }

