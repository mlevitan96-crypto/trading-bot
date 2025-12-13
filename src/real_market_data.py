"""
Phase 2 Real-Time Market Data Aggregator

Fetches market data asynchronously to feed the Alpha Engine with:
- Order Flow Imbalance (OFI) signals
- Spread metrics
- Basis spread (Spot vs Futures premium)

This replaces slow synchronous calls with async data fetching.
"""

import asyncio
import aiohttp
import time
import json
import os
from typing import Dict, Optional, List
from collections import deque

MARKET_DATA_CACHE_PATH = "feature_store/real_market_data.json"
OFI_HISTORY_PATH = "logs/ofi_signals.jsonl"

class MarketDataAggregator:
    """
    Fetches real-time data asynchronously to feed the Alpha Engine.
    Calculates OFI and tracks cross-venue basis.
    """
    
    def __init__(self, cache_ttl_sec: float = 2.0):
        self.cache_ttl_sec = cache_ttl_sec
        self.latest_data: Dict[str, Dict] = {}
        self.ofi_history: Dict[str, deque] = {}
        self.last_books: Dict[str, Dict] = {}
        
        # Fee structure (BloFin)
        self.fees = {
            "blofin_taker": 0.0006,  # 0.06%
            "blofin_maker": 0.0002,  # 0.02%
            "binance_taker": 0.0010  # 0.10%
        }
        
        self._load_cache()
    
    def _load_cache(self):
        """Load cached data if fresh enough."""
        if os.path.exists(MARKET_DATA_CACHE_PATH):
            try:
                with open(MARKET_DATA_CACHE_PATH, 'r') as f:
                    cached = json.load(f)
                    # Only use if less than 5 seconds old
                    if time.time() - cached.get('ts', 0) < 5:
                        self.latest_data = cached.get('data', {})
            except:
                pass
    
    def _save_cache(self):
        """Persist cache for quick recovery."""
        os.makedirs(os.path.dirname(MARKET_DATA_CACHE_PATH), exist_ok=True)
        with open(MARKET_DATA_CACHE_PATH, 'w') as f:
            json.dump({'ts': time.time(), 'data': self.latest_data}, f)
    
    def _log_ofi(self, symbol: str, ofi: float, details: Dict):
        """Log OFI signal for analysis."""
        os.makedirs(os.path.dirname(OFI_HISTORY_PATH), exist_ok=True)
        entry = {
            'ts': time.time(),
            'symbol': symbol,
            'ofi': round(ofi, 4),
            **details
        }
        with open(OFI_HISTORY_PATH, 'a') as f:
            f.write(json.dumps(entry) + '\n')

    def calculate_ofi(self, symbol: str, current_book: Dict) -> float:
        """
        Calculate Order Flow Imbalance from orderbook changes.
        
        OFI measures buying vs selling pressure based on:
        - Price improvements (aggressive orders)
        - Size changes at best bid/ask
        
        Returns: Normalized OFI (-1 to +1), positive = buy pressure
        """
        prev = self.last_books.get(symbol)
        
        if not prev:
            self.last_books[symbol] = current_book
            return 0.0
        
        # Current metrics
        b_t = current_book.get('bid', 0)
        b_qty_t = current_book.get('bid_qty', 0)
        a_t = current_book.get('ask', 0)
        a_qty_t = current_book.get('ask_qty', 0)
        
        # Previous metrics
        b_t_1 = prev.get('bid', 0)
        b_qty_t_1 = prev.get('bid_qty', 0)
        a_t_1 = prev.get('ask', 0)
        a_qty_t_1 = prev.get('ask_qty', 0)
        
        # Bid side contribution (buy pressure)
        if b_t > b_t_1:
            e_bid = b_qty_t  # Price improved: aggressive buying
        elif b_t < b_t_1:
            e_bid = -b_qty_t_1  # Price dropped: bid pulled
        else:
            e_bid = b_qty_t - b_qty_t_1  # Size change
        
        # Ask side contribution (sell pressure)
        if a_t > a_t_1:
            e_ask = -a_qty_t_1  # Ask retreated: less sell pressure
        elif a_t < a_t_1:
            e_ask = a_qty_t  # Aggressive selling
        else:
            e_ask = a_qty_t - a_qty_t_1  # Size change
        
        # Raw OFI
        ofi_raw = e_bid - e_ask
        
        # Normalize by average size to get -1 to +1 range
        avg_size = (b_qty_t + a_qty_t + b_qty_t_1 + a_qty_t_1) / 4
        if avg_size > 0:
            ofi_normalized = max(-1.0, min(1.0, ofi_raw / avg_size))
        else:
            ofi_normalized = 0.0
        
        # Update state
        self.last_books[symbol] = current_book
        
        # Track history for smoothing
        if symbol not in self.ofi_history:
            self.ofi_history[symbol] = deque(maxlen=10)
        self.ofi_history[symbol].append(ofi_normalized)
        
        return ofi_normalized

    def get_smoothed_ofi(self, symbol: str) -> float:
        """Get exponentially weighted OFI from recent history."""
        if symbol not in self.ofi_history or not self.ofi_history[symbol]:
            return 0.0
        
        history = list(self.ofi_history[symbol])
        if not history:
            return 0.0
        
        # EMA with alpha=0.3
        alpha = 0.3
        ema = history[0]
        for val in history[1:]:
            ema = alpha * val + (1 - alpha) * ema
        
        return ema

    def check_basis_arbitrage(self, spot_price: float, perp_price: float) -> Dict:
        """
        Check if basis spread is sufficient to cover fees.
        
        Returns dict with:
        - is_profitable: bool
        - net_margin: expected profit margin
        - direction: 'long_spot_short_perp' or 'short_spot_long_perp'
        """
        if spot_price <= 0 or perp_price <= 0:
            return {'is_profitable': False, 'net_margin': 0, 'direction': None}
        
        spread = perp_price - spot_price
        spread_pct = spread / spot_price
        
        # Total entry cost (taker on both sides)
        entry_cost = self.fees["binance_taker"] + self.fees["blofin_taker"]
        
        # Net margin after fees
        net_margin = abs(spread_pct) - entry_cost
        
        is_profitable = net_margin > 0
        
        if spread > 0:
            direction = "long_spot_short_perp"  # Perp premium: contango
        else:
            direction = "short_spot_long_perp"  # Perp discount: backwardation
        
        return {
            'is_profitable': is_profitable,
            'net_margin': round(net_margin * 100, 4),  # In percentage
            'direction': direction if is_profitable else None,
            'basis_bps': round(spread_pct * 10000, 2),
            'fee_cost_bps': round(entry_cost * 10000, 2)
        }

    async def fetch_binance_ticker(self, session: aiohttp.ClientSession, symbol: str) -> Optional[Dict]:
        """Fetch Level 1 ticker from Binance."""
        url = f"https://api.binance.com/api/v3/ticker/bookTicker?symbol={symbol}"
        try:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=2)) as response:
                if response.status == 200:
                    data = await response.json()
                    return {
                        "venue": "binance_spot",
                        "symbol": symbol,
                        "bid": float(data['bidPrice']),
                        "ask": float(data['askPrice']),
                        "bid_qty": float(data['bidQty']),
                        "ask_qty": float(data['askQty']),
                        "ts": time.time()
                    }
        except Exception as e:
            pass
        return None

    async def get_snapshot(self, symbol: str) -> Dict:
        """
        Get complete market snapshot for a symbol.
        
        Returns:
        - OFI signal
        - Spread metrics
        - Basis (if spot data available)
        - Data freshness
        """
        # Check cache freshness
        cached = self.latest_data.get(symbol, {})
        if cached and (time.time() - cached.get('ts', 0)) < self.cache_ttl_sec:
            return cached
        
        result = {
            'ts': time.time(),
            'symbol': symbol,
            'ofi_signal': 0.0,
            'ofi_smoothed': self.get_smoothed_ofi(symbol),
            'spread_bp': 0.0,
            'basis_bps': 0.0,
            'data_quality': 'stale'
        }
        
        try:
            async with aiohttp.ClientSession() as session:
                # Fetch Binance spot data
                spot_data = await self.fetch_binance_ticker(session, symbol)
                
                if spot_data:
                    # Calculate OFI
                    ofi = self.calculate_ofi(symbol, spot_data)
                    
                    # Calculate spread
                    mid = (spot_data['bid'] + spot_data['ask']) / 2
                    spread_bp = ((spot_data['ask'] - spot_data['bid']) / mid) * 10000
                    
                    result.update({
                        'ofi_signal': round(ofi, 4),
                        'ofi_smoothed': round(self.get_smoothed_ofi(symbol), 4),
                        'spread_bp': round(spread_bp, 2),
                        'spot_mid': mid,
                        'data_quality': 'realtime'
                    })
                    
                    self._log_ofi(symbol, ofi, {'spread_bp': spread_bp})
        except Exception as e:
            result['error'] = str(e)
        
        # Update cache
        self.latest_data[symbol] = result
        self._save_cache()
        
        return result

    def get_cached_snapshot(self, symbol: str) -> Dict:
        """Get cached snapshot without async (for sync code paths)."""
        cached = self.latest_data.get(symbol, {})
        if not cached:
            return {
                'ts': 0,
                'symbol': symbol,
                'ofi_signal': 0.0,
                'ofi_smoothed': 0.0,
                'spread_bp': 5.0,  # Default assumption
                'data_quality': 'none'
            }
        return cached

    def is_data_fresh(self, symbol: str, max_age_sec: float = 2.0) -> bool:
        """Check if cached data is fresh enough."""
        cached = self.latest_data.get(symbol, {})
        return (time.time() - cached.get('ts', 0)) < max_age_sec


# Global instance
_aggregator: Optional[MarketDataAggregator] = None

def get_aggregator() -> MarketDataAggregator:
    """Get or create the global MarketDataAggregator instance."""
    global _aggregator
    if _aggregator is None:
        _aggregator = MarketDataAggregator()
    return _aggregator

def get_ofi(symbol: str) -> float:
    """Get smoothed OFI for symbol."""
    return get_aggregator().get_smoothed_ofi(symbol)

def get_spread_bp(symbol: str) -> float:
    """Get cached spread in basis points."""
    return get_aggregator().get_cached_snapshot(symbol).get('spread_bp', 5.0)

def is_data_fresh(symbol: str, max_age_sec: float = 2.0) -> bool:
    """Check if data is fresh."""
    return get_aggregator().is_data_fresh(symbol, max_age_sec)


if __name__ == "__main__":
    import asyncio
    
    async def test():
        agg = MarketDataAggregator()
        
        print("Fetching BTCUSDT snapshot...")
        snapshot = await agg.get_snapshot("BTCUSDT")
        print(json.dumps(snapshot, indent=2))
        
        print("\nFetching ETHUSDT snapshot...")
        snapshot = await agg.get_snapshot("ETHUSDT")
        print(json.dumps(snapshot, indent=2))
    
    asyncio.run(test())
