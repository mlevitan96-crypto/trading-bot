"""
Blofin Futures Trading Client with HMAC-SHA256 authentication.
Supports leverage trading, margin management, and position monitoring.
Now with built-in caching to prevent memory-intensive repeated DataFrame creation.
"""
import os
import time
import hmac
import hashlib
import json
import requests
from datetime import datetime
from typing import Dict, Any, Optional
import pandas as pd

from src.memory_efficient_cache import get_ohlcv_cache
from src.blofin_rate_limiter import get_blofin_rate_limiter

# Environment configuration
BLOFIN_BASE = os.getenv("BLOFIN_BASE_URL", "https://openapi.blofin.com")
BLOFIN_TESTNET = os.getenv("BLOFIN_TESTNET", "false").lower() == "true"
BLOFIN_API_KEY = os.getenv("BLOFIN_API_KEY", "")
BLOFIN_API_SECRET = os.getenv("BLOFIN_API_SECRET", "")
BLOFIN_PASSPHRASE = os.getenv("BLOFIN_PASSPHRASE", "")
TIMEOUT = 10

# Use testnet if configured
if BLOFIN_TESTNET:
    BLOFIN_BASE = os.getenv("BLOFIN_TESTNET_BASE_URL", BLOFIN_BASE)


def blofin_headers(method: str, path: str, body: str = "") -> Dict[str, str]:
    """
    Generate HMAC-SHA256 authentication headers for Blofin API.
    
    Per Blofin docs: prehash = path + method + timestamp + nonce + body
    Then convert hex signature to base64.
    
    Args:
        method: HTTP method (GET, POST, etc.)
        path: API endpoint path
        body: Request body as JSON string
    
    Returns:
        Dict of authentication headers
    """
    import base64
    import uuid
    
    ts = str(int(time.time() * 1000))
    nonce = str(uuid.uuid4())
    
    # Blofin signature format: path + method + timestamp + nonce + body
    prehash = path + method.upper() + ts + nonce + body
    
    # Generate HMAC-SHA256 hex signature and convert to base64
    hex_signature = hmac.new(
        BLOFIN_API_SECRET.encode(),
        prehash.encode(),
        hashlib.sha256
    ).hexdigest().encode()
    
    sign = base64.b64encode(hex_signature).decode()
    
    return {
        "Content-Type": "application/json",
        "ACCESS-KEY": BLOFIN_API_KEY,
        "ACCESS-SIGN": sign,
        "ACCESS-TIMESTAMP": ts,
        "ACCESS-NONCE": nonce,
        "ACCESS-PASSPHRASE": BLOFIN_PASSPHRASE,
    }


class BlofinFuturesClient:
    """
    Blofin Futures API client for leverage trading.
    
    Features:
    - Market data (OHLCV, mark price, orderbook)
    - Order management (place, cancel, query)
    - Position tracking (long/short, leverage, margin)
    - Account balance and margin queries
    """
    
    def __init__(self, base_url: str = BLOFIN_BASE, session: Optional[requests.Session] = None):
        self.base = base_url.rstrip("/")
        self.sess = session or requests.Session()
        self.mode = "paper" if not BLOFIN_API_KEY else "live"
        self._cache = get_ohlcv_cache()
    
    @staticmethod
    def normalize_symbol(symbol: str) -> str:
        """
        Normalize symbol to Blofin perpetual futures format.
        
        Converts:
        - BTCUSDT → BTC-USDT
        - BTC-USDT → BTC-USDT (already correct)
        - ETHUSDT → ETH-USDT
        - etc.
        
        Args:
            symbol: Input symbol in any format
        
        Returns:
            Blofin perpetual format: "BTC-USDT"
        """
        # Remove -SWAP suffix if present (incorrect format)
        if symbol.endswith("-SWAP"):
            symbol = symbol[:-5]
        
        # Already in correct format (BTC-USDT)
        if "-" in symbol and symbol.count("-") == 1:
            return symbol
        
        # Format: BTCUSDT → BTC-USDT
        if "USDT" in symbol and "-" not in symbol:
            base = symbol.replace("USDT", "")
            return f"{base}-USDT"
        
        # Default: return as-is
        return symbol
    
    def _req(self, method: str, path: str, payload: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        Make authenticated request to Blofin API.
        
        Args:
            method: HTTP method
            path: API endpoint path
            payload: Request payload dict
        
        Returns:
            Response JSON data
        """
        url = self.base + path
        body = "" if not payload else json.dumps(payload)
        hdrs = blofin_headers(method, path, body)
        
        # Enforce rate limiting before making request
        get_blofin_rate_limiter().acquire()
        
        try:
            resp = self.sess.request(method, url, headers=hdrs, data=body, timeout=TIMEOUT)
            resp.raise_for_status()
            return resp.json()
        except requests.exceptions.RequestException as e:
            print(f"❌ Blofin API error: {e}")
            raise
    
    def get_mark_price(self, symbol: str) -> float:
        """
        Get current mark price for futures symbol.
        
        Args:
            symbol: Futures symbol (e.g., "BTCUSDT" or "BTC-USDT")
        
        Returns:
            Current mark price
        
        Raises:
            Exception: If mark price cannot be retrieved
        """
        normalized = self.normalize_symbol(symbol)
        data = self._req("GET", f"/api/v1/market/mark-price?instId={normalized}")
        
        results = data.get("data", [])
        if not results:
            raise Exception(f"No mark price data returned for {normalized}")
        
        # Blofin uses "markPrice" field (not "markPx")
        mark_price = results[0].get("markPrice")
        if mark_price is None:
            raise Exception(f"Mark price field missing for {normalized}")
        
        return float(mark_price)
    
    def get_ticker(self, symbol: str) -> Dict[str, Any]:
        """
        Get ticker data for symbol.
        
        Args:
            symbol: Futures symbol (e.g., "BTCUSDT" or "BTC-USDT")
        
        Returns:
            Ticker data dict
        
        Raises:
            Exception: If ticker data cannot be retrieved
        """
        normalized = self.normalize_symbol(symbol)
        data = self._req("GET", f"/api/v1/market/ticker?instId={normalized}")
        
        results = data.get("data", [])
        if not results:
            raise Exception(f"No ticker data returned for {normalized}")
        
        return results[0]
    
    def fetch_ohlcv(self, symbol: str, timeframe: str = "1m", limit: int = 100, use_cache: bool = True) -> pd.DataFrame:
        """
        Fetch OHLCV candlestick data with caching (compatible with spot client format).
        
        Args:
            symbol: Futures symbol (e.g., "BTCUSDT" or "BTC-USDT")
            timeframe: Candle interval (1m, 5m, 15m, 1H, 4H, 1D)
            limit: Number of candles
            use_cache: Use cached data if available (default True, reduces memory churn)
        
        Returns:
            DataFrame with columns: timestamp, open, high, low, close, volume
        
        Raises:
            Exception: If candle data cannot be retrieved
        """
        normalized = self.normalize_symbol(symbol)
        cache_symbol = f"fut:{normalized}"
        
        if use_cache:
            cached = self._cache.get(cache_symbol, timeframe, limit)
            if cached is not None:
                return cached
        
        data = self._req("GET", f"/api/v1/market/candles?instId={normalized}&bar={timeframe}&limit={limit}")
        
        candles = data.get("data", [])
        if not candles:
            raise Exception(f"No candle data returned for {normalized} (check symbol format and instType)")
        
        df = pd.DataFrame(candles, columns=[
            "timestamp", "open", "high", "low", "close", "volume",
            "volCcy", "volCcyQuote", "confirm"
        ])
        
        df["timestamp"] = pd.to_datetime(df["timestamp"].astype(int), unit="ms")
        df["open"] = df["open"].astype(float)
        df["high"] = df["high"].astype(float)
        df["low"] = df["low"].astype(float)
        df["close"] = df["close"].astype(float)
        df["volume"] = df["volume"].astype(float)
        
        result = df[["timestamp", "open", "high", "low", "close", "volume"]]
        
        if use_cache:
            self._cache.set(cache_symbol, timeframe, limit, result)
        
        return result
    
    def get_orderbook(self, symbol: str, depth: int = 5) -> Dict[str, Any]:
        """
        Fetch orderbook depth for a symbol.
        
        Args:
            symbol: Futures symbol (e.g., "BTCUSDT" or "BTC-USDT")
            depth: Number of price levels to fetch (default: 5)
        
        Returns:
            Dict with "bids" and "asks" arrays
            Each entry is [price, size]
        
        Raises:
            Exception: If orderbook data cannot be retrieved
        """
        normalized = self.normalize_symbol(symbol)
        
        # Blofin orderbook endpoint: /api/v1/market/books
        # Size parameter determines depth (1-400 levels)
        data = self._req("GET", f"/api/v1/market/books?instId={normalized}&sz={depth}")
        
        orderbook_data = data.get("data", [])
        if not orderbook_data:
            raise Exception(f"No orderbook data returned for {normalized}")
        
        book = orderbook_data[0]
        
        # Blofin returns bids and asks as arrays of [price, size, ...]
        bids = [[float(b[0]), float(b[1])] for b in book.get("bids", [])[:depth]]
        asks = [[float(a[0]), float(a[1])] for a in book.get("asks", [])[:depth]]
        
        return {
            "bids": bids,
            "asks": asks,
            "timestamp": book.get("ts")
        }
    
    
    def get_positions(self, symbol: Optional[str] = None) -> Dict[str, Any]:
        """
        Get current futures positions.
        
        Args:
            symbol: Optional symbol filter (e.g., "BTCUSDT" or "BTC-USDT")
        
        Returns:
            Dict with positions data
        """
        try:
            path = "/api/v1/account/positions"
            if symbol:
                normalized = self.normalize_symbol(symbol)
                path += f"?instId={normalized}"
            return self._req("GET", path)
        except Exception as e:
            print(f"⚠️ Failed to get positions: {e}")
            return {"data": []}
    
    def get_balance(self) -> Dict[str, Any]:
        """
        Get account balance and margin info.
        
        Returns:
            Account balance data
        """
        try:
            return self._req("GET", "/api/v1/account/balance")
        except Exception as e:
            print(f"⚠️ Failed to get balance: {e}")
            return {"data": []}
    
    def place_order(
        self,
        symbol: str,
        side: str,
        qty: float,
        price: Optional[float] = None,
        leverage: int = 1,
        order_type: str = "LIMIT",
        reduce_only: bool = False,
        take_profit: Optional[float] = None,
        stop_loss: Optional[float] = None
    ) -> Dict[str, Any]:
        """
        Place futures order.
        
        Args:
            symbol: Futures symbol (e.g., "BTCUSDT" or "BTC-USDT")
            side: "BUY" or "SELL"
            qty: Order quantity
            price: Limit price (None for market orders)
            leverage: Leverage multiplier (1-10x)
            order_type: "MARKET" or "LIMIT"
            reduce_only: If True, only reduce existing position
            take_profit: Take profit price
            stop_loss: Stop loss price
        
        Returns:
            Order response data
        """
        normalized = self.normalize_symbol(symbol)
        
        payload = {
            "instId": normalized,
            "tdMode": "cross",  # cross or isolated margin
            "side": side.lower(),
            "ordType": order_type.lower(),
            "sz": str(qty),
            "lever": str(leverage),
        }
        
        if price is not None:
            payload["px"] = str(price)
        
        if reduce_only:
            payload["reduceOnly"] = "true"
        
        if take_profit is not None:
            payload["tpTriggerPx"] = str(take_profit)
            payload["tpOrdPx"] = str(take_profit)
        
        if stop_loss is not None:
            payload["slTriggerPx"] = str(stop_loss)
            payload["slOrdPx"] = str(stop_loss)
        
        try:
            return self._req("POST", "/api/v1/trade/order", payload)
        except Exception as e:
            print(f"❌ Failed to place order: {e}")
            raise
    
    def cancel_order(self, order_id: str, symbol: str) -> Dict[str, Any]:
        """
        Cancel an order.
        
        Args:
            order_id: Order ID to cancel
            symbol: Symbol of the order (e.g., "BTCUSDT" or "BTC-USDT")
        
        Returns:
            Cancel response
        """
        normalized = self.normalize_symbol(symbol)
        
        payload = {
            "instId": normalized,
            "ordId": order_id
        }
        
        try:
            return self._req("POST", "/api/v1/trade/cancel-order", payload)
        except Exception as e:
            print(f"❌ Failed to cancel order: {e}")
            raise
    
    def set_leverage(self, symbol: str, leverage: int, margin_mode: str = "cross") -> Dict[str, Any]:
        """
        Set leverage for symbol.
        
        Args:
            symbol: Futures symbol (e.g., "BTCUSDT" or "BTC-USDT")
            leverage: Leverage multiplier (1-125 depending on symbol)
            margin_mode: "cross" or "isolated"
        
        Returns:
            Response data
        """
        normalized = self.normalize_symbol(symbol)
        
        payload = {
            "instId": normalized,
            "lever": str(leverage),
            "mgnMode": margin_mode
        }
        
        try:
            return self._req("POST", "/api/v1/account/set-leverage", payload)
        except Exception as e:
            print(f"❌ Failed to set leverage: {e}")
            raise


def test_connectivity():
    """Test Blofin API connectivity with configured credentials."""
    client = BlofinFuturesClient()
    
    print("═" * 60)
    print("🔍 Testing Blofin Futures API Connectivity")
    print("═" * 60)
    print(f"📍 Mode: {client.mode}")
    print(f"🌐 Base URL: {client.base}")
    print("═" * 60)
    
    # Test 1: Public endpoint (mark price) - Test normalization with BTCUSDT format
    print("\n1️⃣ Testing mark price (symbol normalization)...")
    try:
        mark = client.get_mark_price("BTCUSDT")
        print(f"   ✅ BTCUSDT mark price: ${mark:,.2f}")
    except Exception as e:
        print(f"   ❌ Failed: {e}")
    
    # Test 2: Account balance (requires auth)
    print("\n2️⃣ Testing authenticated endpoint (account balance)...")
    try:
        balance = client.get_balance()
        print(f"   ✅ Account balance retrieved: {balance}")
    except Exception as e:
        print(f"   ❌ Failed: {e}")
    
    # Test 3: Get positions
    print("\n3️⃣ Testing positions query...")
    try:
        positions = client.get_positions()
        print(f"   ✅ Positions retrieved: {len(positions.get('data', []))} open positions")
    except Exception as e:
        print(f"   ❌ Failed: {e}")
    
    # Test 4: Fetch OHLCV data - Test with multiple formats
    print("\n4️⃣ Testing market data (OHLCV)...")
    try:
        df = client.fetch_ohlcv("BTCUSDT", "1m", 10)
        print(f"   ✅ Fetched {len(df)} candles")
        print(f"   Latest close: ${df['close'].iloc[-1]:,.2f}")
    except Exception as e:
        print(f"   ❌ Failed: {e}")
    
    # Test 5: Test with ETH to verify different symbols work
    print("\n5️⃣ Testing with ETHUSDT...")
    try:
        df_eth = client.fetch_ohlcv("ETHUSDT", "1m", 5)
        print(f"   ✅ Fetched {len(df_eth)} ETHUSDT candles")
        print(f"   Latest close: ${df_eth['close'].iloc[-1]:,.2f}")
    except Exception as e:
        print(f"   ❌ Failed: {e}")
    
    print("\n" + "═" * 60)
    print("✅ Connectivity test complete!")
    print("═" * 60)


if __name__ == "__main__":
    test_connectivity()
