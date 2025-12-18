"""
Exchange Gateway: Unified interface for spot (Binance) and futures (Blofin/Kraken) trading.
Routes market data and trading operations to appropriate exchange client.
"""
import os
from typing import Dict, Any, Optional
import pandas as pd


class ExchangeGateway:
    """
    Gateway that routes operations to spot or futures exchanges.
    
    Features:
    - Unified interface for both spot and futures
    - Support for multiple exchanges (Blofin, Kraken)
    - Automatic routing based on venue parameter
    - Preserves compatibility with existing bot code
    """
    
    def __init__(self, exchange: str = None, spot_client=None, futures_client=None):
        """
        Initialize gateway with exchange clients.
        
        Args:
            exchange: Exchange name ("kraken" or "blofin"). If None, uses EXCHANGE env var or defaults to "blofin"
            spot_client: Spot trading client (defaults based on exchange)
            futures_client: Futures trading client (defaults based on exchange)
        
        Note: Both clients are instantiated with default parameters if not provided,
        enabling zero-config usage: gateway = ExchangeGateway()
        """
        # Determine exchange from parameter or environment
        if exchange is None:
            exchange = os.getenv("EXCHANGE", "blofin").lower()
        self.exchange = exchange.lower()
        
        # Initialize spot client (defaults to Binance.US for now)
        if spot_client is None:
            from src.blofin_client import BlofinClient
            spot_client = BlofinClient()
        
        # Initialize futures client based on exchange selection
        if futures_client is None:
            if self.exchange == "kraken":
                from src.kraken_futures_client import KrakenFuturesClient
                futures_client = KrakenFuturesClient()
            else:  # Default to Blofin
                from src.blofin_futures_client import BlofinFuturesClient
                futures_client = BlofinFuturesClient()
        
        self.spot = spot_client
        self.fut = futures_client
        self.default_venue = "spot"  # Default to spot for backward compatibility
        
        print(f"✅ ExchangeGateway initialized with exchange: {self.exchange.upper()}")
    
    def get_price(self, symbol: str, venue: str = "spot") -> float:
        """
        Get current price for symbol.
        
        Args:
            symbol: Trading symbol
            venue: "spot" or "futures"
        
        Returns:
            Current price
        """
        if venue == "futures":
            return self.fut.get_mark_price(symbol)
        else:
            # Spot client compatibility
            if hasattr(self.spot, 'get_current_price'):
                from trading_bot.blofin_client import get_current_price
                return get_current_price(symbol)
            return 0.0
    
    def fetch_ohlcv(
        self,
        symbol: str,
        timeframe: str = "1m",
        limit: int = 100,
        venue: str = "spot"
    ) -> pd.DataFrame:
        """
        Fetch OHLCV candlestick data.
        
        Args:
            symbol: Trading symbol
            timeframe: Candle interval
            limit: Number of candles
            venue: "spot" or "futures"
        
        Returns:
            DataFrame with OHLCV data
        """
        if venue == "futures":
            return self.fut.fetch_ohlcv(symbol, timeframe, limit)
        else:
            return self.spot.fetch_ohlcv(symbol, timeframe, limit)
    
    def get_orderbook(self, symbol: str, venue: str = "futures", depth: int = 5) -> Dict[str, Any]:
        """
        Get orderbook depth for OFI calculation.
        
        Args:
            symbol: Trading symbol
            venue: "spot" or "futures"
            depth: Number of orderbook levels to fetch
        
        Returns:
            Dict with "bids" and "asks" arrays
            Each entry is [price, size]
        """
        if venue == "futures":
            # Use futures client to get orderbook
            try:
                # Fetch orderbook from Blofin futures
                orderbook = self.fut.get_orderbook(symbol, depth=depth)
                return orderbook
            except Exception as e:
                # Fallback: Return mock orderbook with neutral bid/ask
                print(f"⚠️ Orderbook fetch failed for {symbol} on {venue}: {e}")
                return {
                    "bids": [[100, 100] for _ in range(depth)],
                    "asks": [[100, 100] for _ in range(depth)]
                }
        else:
            # Spot orderbook not implemented yet
            return {
                "bids": [[100, 100] for _ in range(depth)],
                "asks": [[100, 100] for _ in range(depth)]
            }
    
    def place_order(self, venue: str = "spot", **kwargs) -> Dict[str, Any]:
        """
        Place order on specified venue.
        
        Args:
            venue: "spot" or "futures"
            **kwargs: Order parameters
        
        Returns:
            Order response
        """
        if venue == "futures":
            return self.fut.place_order(**kwargs)
        else:
            # Spot orders would go through spot client (paper trading)
            return {"status": "spot-paper", "venue": "spot", "kwargs": kwargs}
    
    def cancel_order(self, venue: str, order_id: str, symbol: str = None) -> Dict[str, Any]:
        """
        Cancel order on specified venue.
        
        Args:
            venue: "spot" or "futures"
            order_id: Order ID to cancel
            symbol: Symbol (required for futures)
        
        Returns:
            Cancel response
        """
        if venue == "futures":
            if not symbol:
                raise ValueError("Symbol required for futures order cancellation")
            return self.fut.cancel_order(order_id, symbol)
        else:
            return {"status": "spot-cancel", "order_id": order_id}
    
    def get_positions(self, venue: str, symbol: Optional[str] = None) -> Dict[str, Any]:
        """
        Get open positions.
        
        Args:
            venue: "spot" or "futures"
            symbol: Optional symbol filter
        
        Returns:
            Positions data
        """
        if venue == "futures":
            return self.fut.get_positions(symbol)
        else:
            # Spot positions tracked in position_manager.py
            from src.position_manager import get_open_positions
            positions = get_open_positions()
            if symbol:
                positions = [p for p in positions if p.get("symbol") == symbol]
            return {"positions": positions}
    
    def get_balance(self, venue: str) -> Dict[str, Any]:
        """
        Get account balance.
        
        Args:
            venue: "spot" or "futures"
        
        Returns:
            Balance data
        """
        if venue == "futures":
            return self.fut.get_balance()
        else:
            # Spot balance from portfolio tracker
            from src.portfolio_tracker import load_portfolio
            portfolio = load_portfolio()
            return {
                "total": portfolio.get("current_value", 10000),
                "available": portfolio.get("current_value", 10000),
                "currency": "USD"
            }
    
    def set_venue_default(self, venue: str):
        """
        Set default venue for operations.
        
        Args:
            venue: "spot" or "futures"
        """
        if venue not in ["spot", "futures"]:
            raise ValueError(f"Invalid venue: {venue}")
        self.default_venue = venue
        print(f"✅ Default venue set to: {venue}")
