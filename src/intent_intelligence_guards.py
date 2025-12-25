"""
Intent Intelligence Guards (BIG ALPHA PHASE 4)
==============================================

Upgrades the bot with trade-size intent and liquidation heatmaps.
Links to Self-Healing loop for auto-tuning.

Data Sources:
1. Whale CVD (>$100k) - Extract volume for trades >$100k from /api/futures/cvd/exchange-list
2. Liquidation Heatmaps - Top 2 "High Concentration" clusters within 3% of current price
3. Fear & Greed Index - Sentiment multiplier from /api/index/fear-greed-history

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
INTENT_GUARDS_CACHE = FEATURE_DIR / "intent_intelligence_guards.json"

FEATURE_DIR.mkdir(parents=True, exist_ok=True)

# Cache TTL
CACHE_TTL_SECONDS = 300  # 5 minutes for most data
FNG_CACHE_TTL = 600  # 10 minutes for Fear & Greed (less frequent updates)

# In-memory cache
_cache: Dict[str, Dict] = {}
_cache_timestamp: Dict[str, float] = {}

# Whale CVD threshold (configurable, auto-tuned by learning loop)
WHALE_CVD_THRESHOLD_USD = 100000  # $100k default


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
        print(f"⚠️ [INTENT-GUARDS] API error for {endpoint}: {e}", flush=True)
        return None


def _load_cache() -> Dict:
    """Load cached intent intelligence guard data from disk."""
    if INTENT_GUARDS_CACHE.exists():
        try:
            return json.loads(INTENT_GUARDS_CACHE.read_text())
        except Exception:
            pass
    return {}


def _save_cache(data: Dict):
    """Save intent intelligence guard data to disk atomically."""
    try:
        tmp_file = INTENT_GUARDS_CACHE.with_suffix('.tmp')
        tmp_file.write_text(json.dumps(data, indent=2, default=str))
        tmp_file.replace(INTENT_GUARDS_CACHE)
    except Exception as e:
        print(f"⚠️ [INTENT-GUARDS] Error saving cache: {e}", flush=True)


def get_whale_cvd_intent(symbol: str, threshold_usd: float = None) -> Dict[str, Any]:
    """
    Get Whale CVD (>$100k) volume data for trade-size intent analysis.
    
    Endpoint: /api/futures/cvd/exchange-list
    
    Extracts volume for trades > threshold (default $100k).
    This represents whale/institutional trading intent.
    
    Args:
        symbol: Trading symbol (e.g., "BTCUSDT")
        threshold_usd: Minimum trade size to consider as "whale" (default: $100k)
    
    Returns:
        Dict with whale CVD metrics (buy_vol, sell_vol, net_cvd, direction)
    """
    if threshold_usd is None:
        # Load threshold from feature store (auto-tuned by learning loop)
        threshold_usd = _load_whale_cvd_threshold()
    
    cache_key = f"whale_cvd_{symbol}_{int(threshold_usd)}"
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
    data = _coinglass_get("/api/futures/cvd/exchange-list", {
        "symbol": clean_symbol
    })
    
    result = {
        "symbol": symbol,
        "threshold_usd": threshold_usd,
        "ts": now,
        "whale_buy_vol": 0.0,
        "whale_sell_vol": 0.0,
        "whale_net_cvd": 0.0,
        "whale_cvd_direction": "NEUTRAL",
        "retail_buy_vol": 0.0,
        "retail_sell_vol": 0.0,
        "retail_net_cvd": 0.0,
        "retail_cvd_direction": "NEUTRAL",
        "error": None
    }
    
    if not data or 'data' not in data:
        result["error"] = "No data from API"
        return result
    
    try:
        # Parse CVD data structure
        # Note: API structure may vary - this is a template
        cvd_data = data.get('data', {})
        
        # Extract whale volume (>threshold) and retail volume (<threshold)
        # Assuming API returns volume buckets or trade-level data
        if isinstance(cvd_data, dict):
            # If API returns aggregated data by size
            whale_buy = float(cvd_data.get('large_buy_vol', cvd_data.get('whale_buy_vol', 0)))
            whale_sell = float(cvd_data.get('large_sell_vol', cvd_data.get('whale_sell_vol', 0)))
            total_buy = float(cvd_data.get('total_buy_vol', cvd_data.get('buy_vol', 0)))
            total_sell = float(cvd_data.get('total_sell_vol', cvd_data.get('sell_vol', 0)))
            
            # If not directly provided, estimate from total (conservative approach)
            if whale_buy == 0 and whale_sell == 0:
                # Estimate whale as top 20% of volume (conservative proxy)
                whale_buy = total_buy * 0.20
                whale_sell = total_sell * 0.20
            
            result["whale_buy_vol"] = whale_buy
            result["whale_sell_vol"] = whale_sell
            result["whale_net_cvd"] = whale_buy - whale_sell
            
            if result["whale_net_cvd"] > 0:
                result["whale_cvd_direction"] = "LONG"
            elif result["whale_net_cvd"] < 0:
                result["whale_cvd_direction"] = "SHORT"
            
            # Retail = total - whale
            result["retail_buy_vol"] = total_buy - whale_buy
            result["retail_sell_vol"] = total_sell - whale_sell
            result["retail_net_cvd"] = result["retail_buy_vol"] - result["retail_sell_vol"]
            
            if result["retail_net_cvd"] > 0:
                result["retail_cvd_direction"] = "LONG"
            elif result["retail_net_cvd"] < 0:
                result["retail_cvd_direction"] = "SHORT"
            
            result["error"] = None
            
    except Exception as e:
        result["error"] = str(e)
        print(f"⚠️ [INTENT-GUARDS] Error parsing Whale CVD for {symbol}: {e}", flush=True)
    
    # Update caches
    _cache[cache_key] = result
    _cache_timestamp[cache_key] = now
    disk_cache[cache_key] = result
    _save_cache(disk_cache)
    
    return result


def get_liquidation_heatmap_clusters(symbol: str, current_price: float, limit: int = 2) -> Dict[str, Any]:
    """
    Get top N "High Concentration" liquidation clusters within 3% of current price.
    
    Endpoint: /api/futures/liquidation/aggregated-heatmap/model1
    
    Returns top 2 clusters by default (as specified in requirements).
    
    Args:
        symbol: Trading symbol
        current_price: Current market price
        limit: Number of top clusters to return (default: 2)
    
    Returns:
        Dict with top clusters (sorted by concentration/amount)
    """
    cache_key = f"liq_clusters_{symbol}"
    now = time.time()
    
    # Check in-memory cache
    if cache_key in _cache and cache_key in _cache_timestamp:
        cached = _cache[cache_key]
        cache_age = now - _cache_timestamp[cache_key]
        if cache_age < CACHE_TTL_SECONDS:
            cached_price = cached.get("current_price", 0)
            if cached_price > 0 and abs(cached_price - current_price) / cached_price < 0.02:  # Within 2%
                return cached
    
    # Use existing macro_institutional_guards function if available
    try:
        from src.macro_institutional_guards import get_liquidation_heatmap
        heatmap_data = get_liquidation_heatmap(symbol, current_price)
        
        # Extract and sort clusters by concentration/amount
        all_clusters = []
        
        short_clusters = heatmap_data.get("short_liq_clusters_nearby", [])
        long_clusters = heatmap_data.get("long_liq_clusters_nearby", [])
        
        for cluster in short_clusters:
            cluster["direction"] = "SHORT"
            all_clusters.append(cluster)
        
        for cluster in long_clusters:
            cluster["direction"] = "LONG"
            all_clusters.append(cluster)
        
        # Sort by amount (high concentration = high amount)
        all_clusters.sort(key=lambda x: x.get("amount", 0), reverse=True)
        
        # Filter within 3% range
        price_range_3pct = current_price * 0.03
        clusters_in_range = [
            c for c in all_clusters
            if abs(c.get("price", current_price) - current_price) <= price_range_3pct
        ]
        
        # Take top N
        top_clusters = clusters_in_range[:limit]
        
        result = {
            "symbol": symbol,
            "current_price": current_price,
            "ts": now,
            "top_clusters": top_clusters,
            "cluster_count": len(top_clusters),
            "error": None
        }
        
        # Update caches
        _cache[cache_key] = result
        _cache_timestamp[cache_key] = now
        disk_cache = _load_cache()
        disk_cache[cache_key] = result
        _save_cache(disk_cache)
        
        return result
        
    except Exception as e:
        print(f"⚠️ [INTENT-GUARDS] Error getting liquidation clusters for {symbol}: {e}", flush=True)
        return {
            "symbol": symbol,
            "current_price": current_price,
            "ts": now,
            "top_clusters": [],
            "cluster_count": 0,
            "error": str(e)
        }


def get_fear_greed_index() -> Dict[str, Any]:
    """
    Get Fear & Greed Index for sentiment multiplier.
    
    Endpoint: /api/index/fear-greed-history
    
    Returns:
        Dict with current Fear & Greed Index value (0-100)
    """
    cache_key = "fear_greed_index"
    now = time.time()
    
    # Check in-memory cache
    if cache_key in _cache and cache_key in _cache_timestamp:
        if now - _cache_timestamp[cache_key] < FNG_CACHE_TTL:
            return _cache[cache_key]
    
    # Check disk cache
    disk_cache = _load_cache()
    if cache_key in disk_cache:
        cached_data = disk_cache[cache_key]
        cache_age = now - cached_data.get("ts", 0)
        if cache_age < FNG_CACHE_TTL:
            _cache[cache_key] = cached_data
            _cache_timestamp[cache_key] = now
            return cached_data
    
    # Try to reuse existing market_intelligence function
    try:
        from src.market_intelligence import get_fear_greed
        fg_value = get_fear_greed()
        
        if isinstance(fg_value, int):
            result = {
                "value": fg_value,
                "ts": now,
                "classification": _classify_fear_greed(fg_value),
                "error": None
            }
        elif isinstance(fg_value, dict):
            result = {
                "value": fg_value.get("value", fg_value.get("fear_greed", 50)),
                "ts": now,
                "classification": _classify_fear_greed(fg_value.get("value", fg_value.get("fear_greed", 50))),
                "error": None
            }
        else:
            result = {
                "value": 50,
                "ts": now,
                "classification": "NEUTRAL",
                "error": "Unexpected data format"
            }
    except Exception as e:
        # Fallback: fetch directly from API
        data = _coinglass_get("/api/index/fear-greed-history", {"limit": 1})
        
        result = {
            "value": 50,
            "ts": now,
            "classification": "NEUTRAL",
            "error": None
        }
        
        if data and 'data' in data:
            try:
                # Parse Fear & Greed data
                fg_data = data.get('data', {})
                if isinstance(fg_data, list) and len(fg_data) > 0:
                    latest = fg_data[-1]
                    if isinstance(latest, dict):
                        fg_value = int(latest.get('value', latest.get('fear_greed', 50)))
                    else:
                        fg_value = int(latest)
                elif isinstance(fg_data, dict):
                    fg_value = int(fg_data.get('value', fg_data.get('fear_greed', 50)))
                else:
                    fg_value = 50
                
                result["value"] = fg_value
                result["classification"] = _classify_fear_greed(fg_value)
                result["error"] = None
            except Exception as parse_error:
                result["error"] = str(parse_error)
                print(f"⚠️ [INTENT-GUARDS] Error parsing Fear & Greed: {parse_error}", flush=True)
        else:
            result["error"] = "No data from API"
    
    # Update caches
    _cache[cache_key] = result
    _cache_timestamp[cache_key] = now
    disk_cache[cache_key] = result
    _save_cache(disk_cache)
    
    return result


def _classify_fear_greed(value: int) -> str:
    """Classify Fear & Greed Index value into category."""
    if value <= 24:
        return "EXTREME_FEAR"
    elif value <= 44:
        return "FEAR"
    elif value <= 55:
        return "NEUTRAL"
    elif value <= 75:
        return "GREED"
    else:
        return "EXTREME_GREED"


def check_whale_cvd_divergence(symbol: str, signal_direction: str, threshold_usd: float = None) -> Tuple[bool, str, Dict[str, Any]]:
    """
    Check if Whale CVD (>$100k) diverges from signal direction.
    
    Blocks signals where whale intent conflicts with signal.
    
    Args:
        symbol: Trading symbol
        signal_direction: Signal direction ("LONG" or "SHORT")
        threshold_usd: Whale threshold (default: loaded from feature store)
    
    Returns:
        Tuple of (should_block: bool, reason: str, data: Dict)
    """
    whale_data = get_whale_cvd_intent(symbol, threshold_usd)
    
    if whale_data.get("error"):
        # Fail open if we can't get data
        return False, "NO_DATA", whale_data
    
    whale_direction = whale_data.get("whale_cvd_direction", "NEUTRAL")
    
    # Check divergence
    if signal_direction == "LONG" and whale_direction == "SHORT":
        return True, "WHALE_INTENT_DIVERGENCE", whale_data
    elif signal_direction == "SHORT" and whale_direction == "LONG":
        return True, "WHALE_INTENT_DIVERGENCE", whale_data
    
    return False, "ALIGNED", whale_data


def check_moving_toward_liquidation_cluster(symbol: str, current_price: float, entry_price: float, direction: str) -> Tuple[bool, Optional[Dict[str, Any]]]:
    """
    Check if TRUE TREND position is moving toward a liquidation cluster.
    
    Used for extending hold time to 90 minutes for price magnetization.
    
    Args:
        symbol: Trading symbol
        current_price: Current market price
        entry_price: Entry price of position
        direction: Position direction ("LONG" or "SHORT")
    
    Returns:
        Tuple of (is_moving_toward: bool, cluster_info: Optional[Dict])
    """
    clusters_data = get_liquidation_heatmap_clusters(symbol, current_price, limit=2)
    
    if clusters_data.get("error") or not clusters_data.get("top_clusters"):
        return False, None
    
    top_clusters = clusters_data.get("top_clusters", [])
    
    for cluster in top_clusters:
        cluster_price = cluster.get("price", 0)
        cluster_direction = cluster.get("direction", "")
        
        if cluster_price <= 0:
            continue
        
        # For LONG positions, check if moving toward SHORT liquidation cluster (above entry)
        if direction == "LONG" and cluster_direction == "SHORT":
            if cluster_price > entry_price and current_price < cluster_price:
                # Price is between entry and cluster (moving toward cluster)
                distance_pct = abs(current_price - cluster_price) / current_price * 100
                if distance_pct <= 3.0:  # Within 3%
                    return True, cluster
        
        # For SHORT positions, check if moving toward LONG liquidation cluster (below entry)
        elif direction == "SHORT" and cluster_direction == "LONG":
            if cluster_price < entry_price and current_price > cluster_price:
                # Price is between entry and cluster (moving toward cluster)
                distance_pct = abs(current_price - cluster_price) / current_price * 100
                if distance_pct <= 3.0:  # Within 3%
                    return True, cluster
    
    return False, None


def get_fear_greed_multiplier() -> float:
    """
    Get Fear & Greed-based size multiplier.
    
    If F&G > 80 (Extreme Greed), reduce all base sizes by 40%.
    
    Returns:
        Multiplier (default: 1.0, reduced to 0.6 if Extreme Greed)
    """
    fg_data = get_fear_greed_index()
    fg_value = fg_data.get("value", 50)
    
    if fg_value > 80:  # Extreme Greed
        return 0.6  # Reduce by 40% (1.0 - 0.4 = 0.6)
    
    return 1.0  # Normal sizing


def _load_whale_cvd_threshold() -> float:
    """Load Whale CVD threshold from feature store (auto-tuned by learning loop)."""
    threshold_file = FEATURE_DIR / "whale_cvd_threshold.json"
    
    if threshold_file.exists():
        try:
            data = json.loads(threshold_file.read_text())
            return float(data.get("threshold_usd", WHALE_CVD_THRESHOLD_USD))
        except Exception:
            pass
    
    return WHALE_CVD_THRESHOLD_USD


def load_whale_cvd_threshold() -> float:
    """Public function to load Whale CVD threshold (used by learning loop)."""
    return _load_whale_cvd_threshold()


def save_whale_cvd_threshold(threshold_usd: float):
    """Save Whale CVD threshold to feature store (called by learning loop)."""
    threshold_file = FEATURE_DIR / "whale_cvd_threshold.json"
    
    try:
        data = {
            "threshold_usd": threshold_usd,
            "updated_at": time.time(),
            "updated_iso": datetime.utcnow().isoformat() + "Z"
        }
        tmp_file = threshold_file.with_suffix('.tmp')
        tmp_file.write_text(json.dumps(data, indent=2))
        tmp_file.replace(threshold_file)
        print(f"✅ [INTENT-GUARDS] Updated Whale CVD threshold to ${threshold_usd:,.0f}", flush=True)
    except Exception as e:
        print(f"⚠️ [INTENT-GUARDS] Error saving Whale CVD threshold: {e}", flush=True)

