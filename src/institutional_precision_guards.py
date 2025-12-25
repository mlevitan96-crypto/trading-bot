"""
Institutional Precision Guards (BIG ALPHA PHASE 3)
==================================================

Upgrades TRUE TREND logic with Magnet Targets and Taker Aggression.
Integrates institutional order flow data to refine entry/exit precision.

Data Sources:
1. Taker Aggression: 5-minute taker buy/sell ratio tracking
2. Magnet Targets: Option Max Pain price levels
3. Orderbook Walls: Large bid/ask clusters within 5% range

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
INSTITUTIONAL_GUARDS_CACHE = FEATURE_DIR / "institutional_precision_guards.json"

FEATURE_DIR.mkdir(parents=True, exist_ok=True)

# Cache TTL
CACHE_TTL_SECONDS = 300  # 5 minutes
TAKER_AGGRESSION_CACHE_TTL = 60  # 1 minute (more dynamic)

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
        print(f"⚠️ [INST-PRECISION] API error for {endpoint}: {e}", flush=True)
        return None


def _load_cache() -> Dict:
    """Load cached institutional precision guard data from disk."""
    if INSTITUTIONAL_GUARDS_CACHE.exists():
        try:
            return json.loads(INSTITUTIONAL_GUARDS_CACHE.read_text())
        except Exception:
            pass
    return {}


def _save_cache(data: Dict):
    """Save institutional precision guard data to disk atomically."""
    try:
        tmp_file = INSTITUTIONAL_GUARDS_CACHE.with_suffix('.tmp')
        tmp_file.write_text(json.dumps(data, indent=2, default=str))
        tmp_file.replace(INSTITUTIONAL_GUARDS_CACHE)
    except Exception as e:
        print(f"⚠️ [INST-PRECISION] Error saving cache: {e}", flush=True)


def get_taker_aggression_5m(symbol: str) -> Dict[str, Any]:
    """
    Get 5-minute taker buy/sell ratio for taker aggression tracking.
    
    Uses: /api/futures/taker-buy-sell-volume/exchange-list
    
    For LONG entries, we require ratio > 1.10 (10% more buying than selling).
    
    Args:
        symbol: Trading symbol (e.g., "BTCUSDT")
    
    Returns:
        Dict with taker aggression metrics
    """
    cache_key = f"taker_aggression_{symbol}"
    now = time.time()
    
    # Check in-memory cache
    if cache_key in _cache and cache_key in _cache_timestamp:
        if now - _cache_timestamp[cache_key] < TAKER_AGGRESSION_CACHE_TTL:
            return _cache[cache_key]
    
    # Check disk cache
    disk_cache = _load_cache()
    if cache_key in disk_cache:
        cached_data = disk_cache[cache_key]
        cache_age = now - cached_data.get("ts", 0)
        if cache_age < TAKER_AGGRESSION_CACHE_TTL:
            _cache[cache_key] = cached_data
            _cache_timestamp[cache_key] = now
            return cached_data
    
    # Clean symbol
    clean_symbol = symbol.upper().replace('-', '').replace('USDT', '')
    
    # Try to use existing market_intelligence function first (reuse existing data)
    try:
        from src.market_intelligence import get_taker_buy_sell
        taker_data = get_taker_buy_sell()
        if clean_symbol in taker_data:
            symbol_data = taker_data[clean_symbol]
            buy_vol = symbol_data.get('buy_vol_usd', 0)
            sell_vol = symbol_data.get('sell_vol_usd', 0)
            
            # Calculate 5m ratio (buy_vol / sell_vol)
            ratio_5m = (buy_vol / sell_vol) if sell_vol > 0 else 1.0
            
            result = {
                "symbol": symbol,
                "ts": now,
                "buy_vol_usd": buy_vol,
                "sell_vol_usd": sell_vol,
                "ratio_5m": ratio_5m,
                "is_aggressive_buying": ratio_5m > 1.10,  # Required for LONG entries
                "error": None
            }
            
            # Update caches
            _cache[cache_key] = result
            _cache_timestamp[cache_key] = now
            disk_cache[cache_key] = result
            _save_cache(disk_cache)
            
            return result
    except Exception as e:
        print(f"⚠️ [INST-PRECISION] Error getting taker data for {symbol}: {e}", flush=True)
    
    # Fallback: fetch directly from API
    data = _coinglass_get("/api/futures/taker-buy-sell-volume/exchange-list", {
        "symbol": clean_symbol,
        "range": "5m"  # 5-minute window
    })
    
    result = {
        "symbol": symbol,
        "ts": now,
        "buy_vol_usd": 0.0,
        "sell_vol_usd": 0.0,
        "ratio_5m": 1.0,
        "is_aggressive_buying": False,
        "error": "No data available"
    }
    
    if data and 'data' in data:
        try:
            data_obj = data.get('data', {})
            buy_vol = float(data_obj.get('buy_vol_usd', 0))
            sell_vol = float(data_obj.get('sell_vol_usd', 0))
            ratio_5m = (buy_vol / sell_vol) if sell_vol > 0 else 1.0
            
            result.update({
                "buy_vol_usd": buy_vol,
                "sell_vol_usd": sell_vol,
                "ratio_5m": ratio_5m,
                "is_aggressive_buying": ratio_5m > 1.10,
                "error": None
            })
        except Exception as e:
            result["error"] = str(e)
    
    # Update caches
    _cache[cache_key] = result
    _cache_timestamp[cache_key] = now
    disk_cache[cache_key] = result
    _save_cache(disk_cache)
    
    return result


def get_option_max_pain(symbol: str) -> Dict[str, Any]:
    """
    Get Option Max Pain price level (magnet target).
    
    Endpoint: /api/option/max-pain
    
    Max Pain is the strike price at which option holders would experience maximum loss.
    Price tends to "magnetize" toward this level, especially near expiration.
    
    Args:
        symbol: Trading symbol (e.g., "BTCUSDT")
    
    Returns:
        Dict with max pain price and metadata
    """
    cache_key = f"max_pain_{symbol}"
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
    
    # Clean symbol
    clean_symbol = symbol.upper().replace('-', '').replace('USDT', '')
    
    # Fetch from API
    data = _coinglass_get("/api/option/max-pain", {
        "symbol": clean_symbol
    })
    
    result = {
        "symbol": symbol,
        "ts": now,
        "max_pain_price": 0.0,
        "error": None
    }
    
    if not data or 'data' not in data:
        result["error"] = "No data from API"
        return result
    
    try:
        max_pain_data = data.get('data', {})
        
        # Parse max pain price (structure depends on API response)
        if isinstance(max_pain_data, dict):
            max_pain_price = float(max_pain_data.get('maxPain', max_pain_data.get('max_pain', max_pain_data.get('price', 0))))
        elif isinstance(max_pain_data, (int, float)):
            max_pain_price = float(max_pain_data)
        else:
            result["error"] = "Unexpected data format"
            return result
        
        result["max_pain_price"] = max_pain_price
        result["error"] = None
        
    except Exception as e:
        result["error"] = str(e)
        print(f"⚠️ [INST-PRECISION] Error parsing max pain for {symbol}: {e}", flush=True)
    
    # Update caches
    _cache[cache_key] = result
    _cache_timestamp[cache_key] = now
    disk_cache[cache_key] = result
    _save_cache(disk_cache)
    
    return result


def get_orderbook_walls(symbol: str, current_price: float) -> Dict[str, Any]:
    """
    Get top 3 largest Ask and Bid walls within 5% range of current price.
    
    Endpoint: /api/futures/orderbook/aggregated-orderbook-bid-ask-range
    
    Ask Walls = Large sell orders (resistance)
    Bid Walls = Large buy orders (support)
    
    Args:
        symbol: Trading symbol
        current_price: Current market price
    
    Returns:
        Dict with top 3 Ask and Bid walls
    """
    cache_key = f"orderbook_walls_{symbol}"
    now = time.time()
    
    # Check in-memory cache (shorter TTL for orderbook - more dynamic)
    if cache_key in _cache and cache_key in _cache_timestamp:
        cache_age = now - _cache_timestamp[cache_key]
        if cache_age < 60:  # 1 minute cache
            cached = _cache[cache_key]
            # Check if cached price is still relevant (within 1% of current)
            cached_price = cached.get("current_price", 0)
            if cached_price > 0 and abs(cached_price - current_price) / cached_price < 0.01:
                return cached
    
    # Clean symbol
    clean_symbol = symbol.upper().replace('-', '').replace('USDT', '')
    
    # Calculate 5% range
    price_range_pct = 0.05  # 5%
    price_lower = current_price * (1 - price_range_pct)
    price_upper = current_price * (1 + price_range_pct)
    
    # Fetch from API
    data = _coinglass_get("/api/futures/orderbook/aggregated-orderbook-bid-ask-range", {
        "symbol": clean_symbol,
        "priceLower": price_lower,
        "priceUpper": price_upper
    })
    
    result = {
        "symbol": symbol,
        "current_price": current_price,
        "ts": now,
        "ask_walls": [],  # Top 3 largest Ask walls (resistance)
        "bid_walls": [],  # Top 3 largest Bid walls (support)
        "institutional_ask_walls": [],  # Ask walls > $25M
        "error": None
    }
    
    if not data or 'data' not in data:
        result["error"] = "No data from API"
        return result
    
    try:
        orderbook_data = data.get('data', {})
        
        # Parse orderbook data (structure depends on API response)
        asks = []
        bids = []
        
        if isinstance(orderbook_data, dict):
            asks = orderbook_data.get('asks', orderbook_data.get('ask', []))
            bids = orderbook_data.get('bids', orderbook_data.get('bid', []))
        elif isinstance(orderbook_data, list):
            # If it's a list, assume it contains both asks and bids
            asks = [item for item in orderbook_data if item.get('side') == 'ask' or item.get('type') == 'ask']
            bids = [item for item in orderbook_data if item.get('side') == 'bid' or item.get('type') == 'bid']
        
        # Process Ask walls (resistance - large sell orders)
        ask_walls = []
        for ask in asks:
            price = float(ask.get('price', ask.get('priceLevel', 0)))
            size = float(ask.get('size', ask.get('quantity', ask.get('amount', 0))))
            size_usd = price * size  # Approximate USD value
            
            if price > 0 and size_usd > 0:
                ask_walls.append({
                    "price": price,
                    "size": size,
                    "size_usd": size_usd,
                    "distance_pct": ((price - current_price) / current_price * 100) if current_price > 0 else 0
                })
        
        # Sort by size_usd (largest first) and take top 3
        ask_walls.sort(key=lambda x: x['size_usd'], reverse=True)
        result["ask_walls"] = ask_walls[:3]
        
        # Institutional Ask Walls (> $25M)
        result["institutional_ask_walls"] = [w for w in ask_walls if w['size_usd'] > 25000000]
        
        # Process Bid walls (support - large buy orders)
        bid_walls = []
        for bid in bids:
            price = float(bid.get('price', bid.get('priceLevel', 0)))
            size = float(bid.get('size', bid.get('quantity', bid.get('amount', 0))))
            size_usd = price * size
            
            if price > 0 and size_usd > 0:
                bid_walls.append({
                    "price": price,
                    "size": size,
                    "size_usd": size_usd,
                    "distance_pct": ((price - current_price) / current_price * 100) if current_price > 0 else 0
                })
        
        # Sort by size_usd (largest first) and take top 3
        bid_walls.sort(key=lambda x: x['size_usd'], reverse=True)
        result["bid_walls"] = bid_walls[:3]
        
    except Exception as e:
        result["error"] = str(e)
        print(f"⚠️ [INST-PRECISION] Error parsing orderbook walls for {symbol}: {e}", flush=True)
    
    # Update caches
    _cache[cache_key] = result
    _cache_timestamp[cache_key] = now
    disk_cache[cache_key] = result
    _save_cache(disk_cache)
    
    return result


def check_taker_aggression_for_long(symbol: str) -> Tuple[bool, float]:
    """
    Check if taker aggression is sufficient for LONG entry.
    
    Requires 5m ratio > 1.10 (10% more buying than selling).
    
    Returns:
        Tuple of (is_sufficient: bool, ratio: float)
    """
    aggression_data = get_taker_aggression_5m(symbol)
    
    if aggression_data.get("error"):
        # Fail open if we can't get data
        return True, 1.0
    
    ratio = aggression_data.get("ratio_5m", 1.0)
    return aggression_data.get("is_aggressive_buying", False), ratio


def get_max_pain_price(symbol: str) -> float:
    """
    Get Option Max Pain price for a symbol.
    
    Returns:
        Max Pain price, or 0.0 if unavailable
    """
    max_pain_data = get_option_max_pain(symbol)
    
    if max_pain_data.get("error"):
        return 0.0
    
    return max_pain_data.get("max_pain_price", 0.0)


def check_price_distance_from_max_pain(current_price: float, max_pain_price: float) -> Tuple[float, bool]:
    """
    Check distance from current price to Max Pain.
    
    Returns:
        Tuple of (distance_pct: float, is_far: bool)
        is_far = True if > 2% away (triggers extended hold)
    """
    if max_pain_price <= 0 or current_price <= 0:
        return 0.0, False
    
    distance_pct = abs(current_price - max_pain_price) / max_pain_price * 100
    is_far = distance_pct > 2.0
    
    return distance_pct, is_far


def get_institutional_ask_wall_below_target(symbol: str, target_price: float, current_price: float) -> Optional[Dict[str, Any]]:
    """
    Find largest institutional Ask Wall (> $25M) below target price.
    
    Used to adjust take profit targets (move TP to 0.1% below wall).
    
    Args:
        symbol: Trading symbol
        target_price: Target price (e.g., Tier 4 +2.0%)
        current_price: Current market price
    
    Returns:
        Dict with wall info if found, None otherwise
    """
    walls_data = get_orderbook_walls(symbol, current_price)
    
    if walls_data.get("error"):
        return None
    
    institutional_walls = walls_data.get("institutional_ask_walls", [])
    
    # Find walls below target price
    walls_below = [w for w in institutional_walls if w['price'] < target_price]
    
    if not walls_below:
        return None
    
    # Return largest wall below target
    largest_wall = max(walls_below, key=lambda x: x['size_usd'])
    return largest_wall


def get_all_institutional_data(symbol: str, current_price: float) -> Dict[str, Any]:
    """
    Get all institutional precision guard data for a symbol.
    
    Returns combined data for dashboard display and analysis.
    """
    return {
        "symbol": symbol,
        "current_price": current_price,
        "taker_aggression": get_taker_aggression_5m(symbol),
        "max_pain": get_option_max_pain(symbol),
        "orderbook_walls": get_orderbook_walls(symbol, current_price),
        "ts": time.time()
    }

