"""
Memory-Efficient Cache and Data Structures

Addresses the memory leak patterns identified in the architectural review:
1. TTL-based OHLCV cache to prevent repeated DataFrame creation
2. Slotted dataclasses for market tick data (reduced memory footprint)
3. Bounded ring buffers using collections.deque

This module provides infrastructure for Phase 1 of the tri-layer migration.
"""

import time
import threading
from collections import deque
from dataclasses import dataclass, field
from typing import Dict, Optional, Any, List, Deque
import pandas as pd


@dataclass(slots=True)
class MarketTick:
    """
    Memory-efficient market tick using slots=True.
    Eliminates __dict__ overhead - significant savings with millions of ticks.
    """
    symbol: str
    timestamp: float
    price: float
    volume: float
    bid: float = 0.0
    ask: float = 0.0
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "symbol": self.symbol,
            "timestamp": self.timestamp,
            "price": self.price,
            "volume": self.volume,
            "bid": self.bid,
            "ask": self.ask
        }


@dataclass(slots=True)
class OHLCVBar:
    """Memory-efficient OHLCV bar using slots=True."""
    timestamp: float
    open: float
    high: float
    low: float
    close: float
    volume: float
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "open": self.open,
            "high": self.high,
            "low": self.low,
            "close": self.close,
            "volume": self.volume
        }


class BoundedBuffer:
    """
    Thread-safe bounded buffer using deque.
    Automatically evicts oldest items when capacity is exceeded.
    """
    
    def __init__(self, maxlen: int = 1000):
        self._buffer: Deque[Any] = deque(maxlen=maxlen)
        self._lock = threading.Lock()
    
    def append(self, item: Any) -> None:
        with self._lock:
            self._buffer.append(item)
    
    def extend(self, items: List[Any]) -> None:
        with self._lock:
            self._buffer.extend(items)
    
    def get_all(self) -> List[Any]:
        with self._lock:
            return list(self._buffer)
    
    def get_last_n(self, n: int) -> List[Any]:
        with self._lock:
            return list(self._buffer)[-n:] if n < len(self._buffer) else list(self._buffer)
    
    def clear(self) -> None:
        with self._lock:
            self._buffer.clear()
    
    def __len__(self) -> int:
        return len(self._buffer)


class OHLCVCache:
    """
    TTL-based OHLCV DataFrame cache.
    
    Prevents repeated DataFrame creation by caching OHLCV data with automatic expiry.
    Key insight: OHLCV data for the same symbol/timeframe doesn't change rapidly,
    so caching for 10-30 seconds dramatically reduces memory churn.
    """
    
    def __init__(self, default_ttl: int = 15, max_entries: int = 100):
        """
        Args:
            default_ttl: Cache TTL in seconds (default 15s)
            max_entries: Maximum cached entries before LRU eviction
        """
        self._cache: Dict[str, Dict[str, Any]] = {}
        self._lock = threading.Lock()
        self._default_ttl = default_ttl
        self._max_entries = max_entries
        self._access_times: Dict[str, float] = {}
    
    def _make_key(self, symbol: str, timeframe: str, limit: int) -> str:
        return f"{symbol}:{timeframe}:{limit}"
    
    def get(self, symbol: str, timeframe: str, limit: int, copy: bool = False) -> Optional[pd.DataFrame]:
        """Get cached DataFrame if exists and not expired.
        
        Args:
            symbol: Trading symbol
            timeframe: Candle timeframe
            limit: Number of candles
            copy: If True, return a copy (safe for modification). Default False for read-only use.
        """
        key = self._make_key(symbol, timeframe, limit)
        
        with self._lock:
            self._prune_expired()
            
            if key not in self._cache:
                return None
            
            entry = self._cache[key]
            if time.time() > entry["expires_at"]:
                del self._cache[key]
                if key in self._access_times:
                    del self._access_times[key]
                return None
            
            self._access_times[key] = time.time()
            return entry["data"].copy() if copy else entry["data"]
    
    def _prune_expired(self) -> None:
        """Proactively remove expired entries to prevent memory accumulation."""
        now = time.time()
        expired_keys = [k for k, v in self._cache.items() if now > v["expires_at"]]
        for key in expired_keys:
            del self._cache[key]
            if key in self._access_times:
                del self._access_times[key]
    
    def set(self, symbol: str, timeframe: str, limit: int, df: pd.DataFrame, ttl: Optional[int] = None) -> None:
        """Cache DataFrame with TTL."""
        key = self._make_key(symbol, timeframe, limit)
        ttl = ttl or self._default_ttl
        
        with self._lock:
            if len(self._cache) >= self._max_entries:
                self._evict_lru()
            
            self._cache[key] = {
                "data": df.copy(),
                "expires_at": time.time() + ttl,
                "created_at": time.time()
            }
            self._access_times[key] = time.time()
    
    def _evict_lru(self) -> None:
        """Evict least recently used entry."""
        if not self._access_times:
            return
        
        oldest_key = min(self._access_times, key=self._access_times.get)
        if oldest_key in self._cache:
            del self._cache[oldest_key]
        del self._access_times[oldest_key]
    
    def clear(self) -> None:
        """Clear all cached entries."""
        with self._lock:
            self._cache.clear()
            self._access_times.clear()
    
    def stats(self) -> Dict[str, Any]:
        """Get cache statistics."""
        with self._lock:
            now = time.time()
            valid_entries = sum(1 for e in self._cache.values() if now < e["expires_at"])
            return {
                "total_entries": len(self._cache),
                "valid_entries": valid_entries,
                "expired_entries": len(self._cache) - valid_entries,
                "max_entries": self._max_entries
            }


_ohlcv_cache = OHLCVCache(default_ttl=15, max_entries=100)


def get_cached_ohlcv(fetch_fn, symbol: str, timeframe: str, limit: int, ttl: Optional[int] = None) -> pd.DataFrame:
    """
    Get OHLCV data with caching layer.
    
    Args:
        fetch_fn: Function to fetch OHLCV data (e.g., blofin.fetch_ohlcv)
        symbol: Trading pair symbol
        timeframe: Candle timeframe
        limit: Number of candles
        ttl: Optional custom TTL in seconds
    
    Returns:
        DataFrame with OHLCV data
    """
    cached = _ohlcv_cache.get(symbol, timeframe, limit)
    if cached is not None:
        return cached
    
    df = fetch_fn(symbol=symbol, timeframe=timeframe, limit=limit)
    _ohlcv_cache.set(symbol, timeframe, limit, df, ttl)
    return df


def get_ohlcv_cache() -> OHLCVCache:
    """Get the global OHLCV cache instance."""
    return _ohlcv_cache


class TickBuffer:
    """
    Bounded tick buffer for real-time price tracking.
    
    Replaces the anti-pattern:
        df = pd.concat([df, new_tick_df])
        df = df.iloc[-1000:]
    
    With memory-efficient bounded deque storage.
    """
    
    def __init__(self, symbol: str, maxlen: int = 1000):
        self.symbol = symbol
        self._ticks: Deque[MarketTick] = deque(maxlen=maxlen)
        self._lock = threading.Lock()
    
    def add_tick(self, price: float, volume: float, timestamp: Optional[float] = None) -> None:
        """Add a new tick to the buffer."""
        tick = MarketTick(
            symbol=self.symbol,
            timestamp=timestamp or time.time(),
            price=price,
            volume=volume
        )
        with self._lock:
            self._ticks.append(tick)
    
    def get_prices(self, n: Optional[int] = None) -> List[float]:
        """Get last n prices (or all if n is None)."""
        with self._lock:
            ticks = list(self._ticks)
        
        if n is not None:
            ticks = ticks[-n:]
        return [t.price for t in ticks]
    
    def get_latest_price(self) -> Optional[float]:
        """Get the most recent price."""
        with self._lock:
            if self._ticks:
                return self._ticks[-1].price
            return None
    
    def to_dataframe(self) -> pd.DataFrame:
        """Convert buffer to DataFrame (creates new DF, use sparingly)."""
        with self._lock:
            ticks = list(self._ticks)
        
        if not ticks:
            return pd.DataFrame(columns=["timestamp", "price", "volume"])
        
        return pd.DataFrame([t.to_dict() for t in ticks])
    
    def __len__(self) -> int:
        return len(self._ticks)


_tick_buffers: Dict[str, TickBuffer] = {}
_tick_buffer_lock = threading.Lock()


def get_tick_buffer(symbol: str, maxlen: int = 1000) -> TickBuffer:
    """Get or create a tick buffer for a symbol."""
    with _tick_buffer_lock:
        if symbol not in _tick_buffers:
            _tick_buffers[symbol] = TickBuffer(symbol, maxlen)
        return _tick_buffers[symbol]
