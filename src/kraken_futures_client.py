"""
Kraken Futures Trading Client with HMAC-SHA512 authentication.
Supports leverage trading, margin management, and position monitoring.
Designed to match the interface of BlofinFuturesClient for seamless integration.
"""
import os
import sys
from pathlib import Path

# Fix Python path when running directly (for testing)
# Add project root to path so 'src' imports work
# Must happen before any 'src' imports
_script_dir = Path(__file__).parent
_project_root = _script_dir.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

import time
import hmac
import hashlib
import json
import base64
import requests
from datetime import datetime
from typing import Dict, Any, Optional
import pandas as pd

from src.memory_efficient_cache import get_ohlcv_cache
from src.kraken_rate_limiter import get_kraken_rate_limiter

# Environment configuration
KRAKEN_FUTURES_BASE = os.getenv("KRAKEN_FUTURES_BASE_URL", "https://futures.kraken.com")
KRAKEN_FUTURES_TESTNET = os.getenv("KRAKEN_FUTURES_TESTNET", "false").lower() == "true"
KRAKEN_FUTURES_API_KEY = os.getenv("KRAKEN_FUTURES_API_KEY", "")
KRAKEN_FUTURES_API_SECRET = os.getenv("KRAKEN_FUTURES_API_SECRET", "")
TIMEOUT = 10

# Use testnet if configured
if KRAKEN_FUTURES_TESTNET:
    KRAKEN_FUTURES_BASE = os.getenv("KRAKEN_FUTURES_TESTNET_BASE_URL", "https://demo-futures.kraken.com")


def kraken_headers(method: str, endpoint_path: str, post_data: str = "") -> Dict[str, str]:
    """
    Generate HMAC-SHA512 authentication headers for Kraken Futures API.
    
    Per Kraken docs:
    1. Concatenate: post_data + nonce + endpoint_path
    2. SHA-256 hash of concatenated string
    3. HMAC-SHA-512 of SHA-256 hash (using base64-decoded api_secret)
    4. Base64 encode to get Authent value
    
    Args:
        method: HTTP method (GET, POST, etc.) - note: Kraken uses post_data, not method in signature
        endpoint_path: API endpoint path (e.g., "/derivatives/api/v3/sendorder")
        post_data: Request body as URL-encoded string (or empty for GET)
    
    Returns:
        Dict of authentication headers
    """
    # Generate nonce (timestamp in milliseconds)
    nonce = str(int(time.time() * 1000))
    
    # Kraken signature format: post_data + nonce + endpoint_path
    message = post_data + nonce + endpoint_path
    
    # Step 1: SHA-256 hash of the message
    sha256_hash = hashlib.sha256(message.encode('utf-8')).digest()
    
    # Step 2: Decode API secret from base64 (Kraken secrets are base64-encoded)
    try:
        decoded_secret = base64.b64decode(KRAKEN_FUTURES_API_SECRET)
    except Exception as e:
        raise ValueError(f"Failed to decode Kraken API secret (must be base64): {e}")
    
    # Step 3: HMAC-SHA-512 of the SHA-256 hash
    hmac_sha512 = hmac.new(decoded_secret, sha256_hash, hashlib.sha512).digest()
    
    # Step 4: Base64 encode to get Authent value
    authent = base64.b64encode(hmac_sha512).decode()
    
    headers = {
        'APIKey': KRAKEN_FUTURES_API_KEY,
        'Authent': authent,
        'Nonce': nonce,
        'Content-Type': 'application/x-www-form-urlencoded' if post_data else 'application/json'
    }
    
    return headers


# Symbol mapping: Internal format (BTCUSDT) -> Kraken format (PI_XBTUSD)
SYMBOL_MAP = {
    "BTCUSDT": "PI_XBTUSD",
    "ETHUSDT": "PI_ETHUSD",
    "SOLUSDT": "PF_SOLUSD",  # Kraken may use PF_ prefix for some
    "AVAXUSDT": "PF_AVAXUSD",
    "DOTUSDT": "PF_DOTUSD",
    "TRXUSDT": "PF_TRXUSD",
    "XRPUSDT": "PI_XRPUSD",
    "ADAUSDT": "PF_ADAUSD",
    "DOGEUSDT": "PF_DOGEUSD",
    "BNBUSDT": "PF_BNBUSD",
    "LINKUSDT": "PF_LINKUSD",
    "ARBUSDT": "PF_ARBUSD",
    "OPUSDT": "PF_OPUSD",
    "PEPEUSDT": "PF_PEPEUSD",
}

# Reverse mapping for conversion back
REVERSE_SYMBOL_MAP = {v: k for k, v in SYMBOL_MAP.items()}


def normalize_to_kraken(symbol: str) -> str:
    """
    Normalize symbol to Kraken Futures format.
    
    Converts:
    - BTCUSDT → PI_XBTUSD
    - ETHUSDT → PI_ETHUSD
    - BTC-USDT → PI_XBTUSD (handles dash format too)
    
    Args:
        symbol: Input symbol in any format
    
    Returns:
        Kraken futures format: "PI_XBTUSD"
    """
    # Remove dash if present (BTC-USDT -> BTCUSDT)
    if "-" in symbol:
        symbol = symbol.replace("-", "")
    
    # Check mapping
    if symbol in SYMBOL_MAP:
        return SYMBOL_MAP[symbol]
    
    # If not in map, try to construct (may not work for all symbols)
    # Default pattern: BTCUSDT -> PI_XBTUSD (BTC -> XBT per ISO 4217)
    if symbol.endswith("USDT"):
        base = symbol[:-4]  # Remove USDT
        # BTC -> XBT (ISO 4217 standard)
        if base == "BTC":
            return "PI_XBTUSD"
        # For others, try PF_ prefix (may need verification)
        return f"PF_{base}USD"
    
    # Return as-is if can't convert
    return symbol


def normalize_from_kraken(symbol: str) -> str:
    """
    Convert Kraken symbol back to internal format.
    
    Converts:
    - PI_XBTUSD → BTCUSDT
    - PI_ETHUSD → ETHUSDT
    
    Args:
        symbol: Kraken symbol format
    
    Returns:
        Internal format: "BTCUSDT"
    """
    if symbol in REVERSE_SYMBOL_MAP:
        return REVERSE_SYMBOL_MAP[symbol]
    
    # Try to reverse engineer if not in map
    if symbol.startswith("PI_") or symbol.startswith("PF_"):
        # PI_XBTUSD -> BTCUSDT
        if symbol.startswith("PI_"):
            base_part = symbol[3:-3]  # Remove PI_ prefix and USD suffix
        else:  # PF_
            base_part = symbol[3:-3]
        
        # XBT -> BTC
        if base_part == "XBT":
            return "BTCUSDT"
        
        # Others: assume base_part matches
        return f"{base_part}USDT"
    
    return symbol


class KrakenFuturesClient:
    """
    Kraken Futures API client for leverage trading.
    
    Features:
    - Market data (OHLCV, mark price, orderbook)
    - Order management (place, cancel, query)
    - Position tracking (long/short, leverage, margin)
    - Account balance and margin queries
    
    Interface matches BlofinFuturesClient for seamless integration.
    """
    
    def __init__(self, base_url: str = KRAKEN_FUTURES_BASE, session: Optional[requests.Session] = None):
        self.base = base_url.rstrip("/")
        self.sess = session or requests.Session()
        self.mode = "paper" if not KRAKEN_FUTURES_API_KEY else "live"
        self._cache = get_ohlcv_cache()
    
    @staticmethod
    def normalize_symbol(symbol: str) -> str:
        """Normalize symbol to Kraken format (alias for normalize_to_kraken)."""
        return normalize_to_kraken(symbol)
    
    def _req(self, method: str, path: str, payload: Optional[Dict[str, Any]] = None, post_data: Optional[str] = None) -> Dict[str, Any]:
        """
        Make authenticated request to Kraken Futures API.
        
        Args:
            method: HTTP method (GET, POST, etc.)
            path: API endpoint path (e.g., "/derivatives/api/v3/sendorder")
            payload: Request payload dict (will be converted to URL-encoded string)
            post_data: Pre-formatted URL-encoded string (if provided, payload is ignored)
        
        Returns:
            Response JSON data
        """
        url = self.base + path
        
        # Convert payload to URL-encoded string if needed
        if post_data is None:
            if payload:
                # Convert dict to URL-encoded string
                post_data = "&".join([f"{k}={v}" for k, v in payload.items()])
            else:
                post_data = ""
        
        # GET requests don't need post_data in signature for public endpoints
        # But authenticated GET requests still need it
        if method == "GET" and not KRAKEN_FUTURES_API_KEY:
            # Public endpoint - no auth needed
            headers = {}
            body = None
        else:
            # Authenticated request
            headers = kraken_headers(method, path, post_data)
            body = post_data.encode('utf-8') if post_data else None
        
        # Enforce rate limiting before making request
        get_kraken_rate_limiter().acquire()
        
        try:
            if method == "GET":
                # For GET, params go in URL, post_data for auth signature
                if post_data and not KRAKEN_FUTURES_API_KEY:
                    # Public GET with query params
                    url += "?" + post_data
                    resp = self.sess.request(method, url, headers=headers, timeout=TIMEOUT)
                else:
                    # Authenticated GET
                    resp = self.sess.request(method, url, headers=headers, data=body, timeout=TIMEOUT)
            else:
                # POST/PUT/DELETE - body in request
                resp = self.sess.request(method, url, headers=headers, data=body, timeout=TIMEOUT)
            
            resp.raise_for_status()
            return resp.json()
        except requests.exceptions.RequestException as e:
            print(f"❌ Kraken Futures API error: {e}")
            if hasattr(e, 'response') and e.response is not None:
                try:
                    error_detail = e.response.json()
                    print(f"   Error details: {error_detail}")
                except:
                    print(f"   Response text: {e.response.text[:200]}")
            raise
    
    def get_mark_price(self, symbol: str) -> float:
        """
        Get current mark price for futures symbol.
        
        Args:
            symbol: Futures symbol (e.g., "BTCUSDT" or "PI_XBTUSD")
        
        Returns:
            Current mark price
        
        Raises:
            Exception: If mark price cannot be retrieved
        """
        kraken_symbol = self.normalize_symbol(symbol)
        
        # Kraken tickers endpoint: /derivatives/api/v3/tickers?symbol=PI_XBTUSD
        data = self._req("GET", f"/derivatives/api/v3/tickers?symbol={kraken_symbol}")
        
        # Kraken response format: {"result": "success", "tickers": [{"tag": "perpetual", "pair": "PI_XBTUSD", ...}]}
        tickers = data.get("tickers", [])
        if not tickers:
            raise Exception(f"No ticker data returned for {kraken_symbol}")
        
        # Find matching ticker
        ticker = next((t for t in tickers if t.get("tag") == "perpetual" or t.get("pair") == kraken_symbol), tickers[0])
        
        # Mark price field (may be "markPrice" or "indexPrice" - check Kraken docs)
        mark_price = ticker.get("markPrice") or ticker.get("indexPrice") or ticker.get("last")
        if mark_price is None:
            raise Exception(f"Mark price field missing for {kraken_symbol} - ticker: {ticker}")
        
        return float(mark_price)
    
    def get_ticker(self, symbol: str) -> Dict[str, Any]:
        """
        Get ticker data for symbol.
        
        Args:
            symbol: Futures symbol (e.g., "BTCUSDT" or "PI_XBTUSD")
        
        Returns:
            Ticker data dict
        
        Raises:
            Exception: If ticker data cannot be retrieved
        """
        kraken_symbol = self.normalize_symbol(symbol)
        data = self._req("GET", f"/derivatives/api/v3/tickers?symbol={kraken_symbol}")
        
        tickers = data.get("tickers", [])
        if not tickers:
            raise Exception(f"No ticker data returned for {kraken_symbol}")
        
        # Return first ticker (or matching perpetual)
        ticker = next((t for t in tickers if t.get("tag") == "perpetual"), tickers[0])
        return ticker
    
    def fetch_ohlcv(self, symbol: str, timeframe: str = "1m", limit: int = 100, use_cache: bool = True) -> pd.DataFrame:
        """
        Fetch OHLCV candlestick data with caching.
        
        Args:
            symbol: Futures symbol (e.g., "BTCUSDT" or "PI_XBTUSD")
            timeframe: Candle interval (1m, 5m, 15m, 1h, 4h, 1d)
            limit: Number of candles
            use_cache: Use cached data if available
        
        Returns:
            DataFrame with columns: timestamp, open, high, low, close, volume
        
        Raises:
            Exception: If candle data cannot be retrieved
        """
        kraken_symbol = self.normalize_symbol(symbol)
        cache_symbol = f"kraken_fut:{kraken_symbol}"
        
        if use_cache:
            cached = self._cache.get(cache_symbol, timeframe, limit)
            if cached is not None:
                return cached
        
        # Kraken candles endpoint: /derivatives/api/v3/candles?symbol=PI_XBTUSD&interval=1m&limit=100
        # Map timeframe to Kraken format (may need adjustment)
        kraken_timeframe = timeframe  # Kraken uses same format: 1m, 5m, 15m, 1h, 4h, 1d
        
        data = self._req("GET", f"/derivatives/api/v3/candles?symbol={kraken_symbol}&interval={kraken_timeframe}&limit={limit}")
        
        # Kraken response format: {"result": "success", "candles": [[timestamp, open, high, low, close, volume], ...]}
        candles = data.get("candles", [])
        if not candles:
            raise Exception(f"No candle data returned for {kraken_symbol}")
        
        # Convert to DataFrame
        df = pd.DataFrame(candles, columns=["timestamp", "open", "high", "low", "close", "volume"])
        
        # Convert timestamp (Kraken uses milliseconds)
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
            symbol: Futures symbol (e.g., "BTCUSDT" or "PI_XBTUSD")
            depth: Number of price levels to fetch (default: 5)
        
        Returns:
            Dict with "bids" and "asks" arrays
            Each entry is [price, size]
        
        Raises:
            Exception: If orderbook data cannot be retrieved
        """
        kraken_symbol = self.normalize_symbol(symbol)
        
        # Kraken orderbook endpoint: /derivatives/api/v3/orderbook?symbol=PI_XBTUSD
        data = self._req("GET", f"/derivatives/api/v3/orderbook?symbol={kraken_symbol}")
        
        # Kraken response format: {"result": "success", "orderBook": {"bids": [[price, qty], ...], "asks": [[price, qty], ...]}}
        orderbook = data.get("orderBook", {})
        if not orderbook:
            raise Exception(f"No orderbook data returned for {kraken_symbol}")
        
        bids = [[float(b[0]), float(b[1])] for b in orderbook.get("bids", [])[:depth]]
        asks = [[float(a[0]), float(a[1])] for a in orderbook.get("asks", [])[:depth]]
        
        return {
            "bids": bids,
            "asks": asks,
            "timestamp": orderbook.get("serverTime") or int(time.time() * 1000)
        }
    
    def get_positions(self, symbol: Optional[str] = None) -> Dict[str, Any]:
        """
        Get current futures positions.
        
        Args:
            symbol: Optional symbol filter (e.g., "BTCUSDT" or "PI_XBTUSD")
        
        Returns:
            Dict with positions data
        """
        try:
            path = "/derivatives/api/v3/openpositions"
            post_data = ""
            if symbol:
                kraken_symbol = self.normalize_symbol(symbol)
                post_data = f"symbol={kraken_symbol}"
            return self._req("GET", path, post_data=post_data)
        except Exception as e:
            print(f"⚠️ Failed to get positions: {e}")
            return {"result": "error", "openPositions": []}
    
    def get_balance(self) -> Dict[str, Any]:
        """
        Get account balance and margin info.
        
        Returns:
            Account balance data
        """
        try:
            return self._req("GET", "/derivatives/api/v3/accounts")
        except Exception as e:
            print(f"⚠️ Failed to get balance: {e}")
            return {"result": "error", "accounts": []}
    
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
            symbol: Futures symbol (e.g., "BTCUSDT" or "PI_XBTUSD")
            side: "BUY" or "SELL"
            qty: Order quantity (size)
            price: Limit price (None for market orders)
            leverage: Leverage multiplier (1-10x) - note: Kraken may require separate leverage setting
            order_type: "MARKET" or "LIMIT"
            reduce_only: If True, only reduce existing position
            take_profit: Take profit price
            stop_loss: Stop loss price
        
        Returns:
            Order response data
        """
        kraken_symbol = self.normalize_symbol(symbol)
        
        # Kraken sendorder endpoint requires URL-encoded post_data
        # Format: orderType=limit&symbol=PI_XBTUSD&side=buy&size=1&limitPrice=50000
        payload_dict = {
            "symbol": kraken_symbol,
            "side": side.lower(),  # buy or sell
            "size": str(qty),
        }
        
        # Order type
        if order_type.upper() == "MARKET":
            payload_dict["orderType"] = "mkt"
        else:
            payload_dict["orderType"] = "lmt"
            if price is not None:
                payload_dict["limitPrice"] = str(price)
        
        # Reduce only
        if reduce_only:
            payload_dict["reduceOnly"] = "true"
        
        # Take profit and stop loss (Kraken may use different parameter names)
        if take_profit is not None:
            payload_dict["stopPrice"] = str(take_profit)  # May need adjustment per Kraken docs
        if stop_loss is not None:
            payload_dict["stopPrice"] = str(stop_loss)  # May need adjustment per Kraken docs
        
        # Note: Leverage may need to be set separately via set_leverage()
        
        try:
            return self._req("POST", "/derivatives/api/v3/sendorder", payload=payload_dict)
        except Exception as e:
            print(f"❌ Failed to place order: {e}")
            raise
    
    def cancel_order(self, order_id: str, symbol: str) -> Dict[str, Any]:
        """
        Cancel an order.
        
        Args:
            order_id: Order ID to cancel
            symbol: Symbol of the order (e.g., "BTCUSDT" or "PI_XBTUSD")
        
        Returns:
            Cancel response
        """
        kraken_symbol = self.normalize_symbol(symbol)
        
        payload_dict = {
            "orderId": order_id,
            "symbol": kraken_symbol
        }
        
        try:
            return self._req("POST", "/derivatives/api/v3/cancelorder", payload=payload_dict)
        except Exception as e:
            print(f"❌ Failed to cancel order: {e}")
            raise
    
    def set_leverage(self, symbol: str, leverage: int, margin_mode: str = "cross") -> Dict[str, Any]:
        """
        Set leverage for symbol.
        
        Args:
            symbol: Futures symbol (e.g., "BTCUSDT" or "PI_XBTUSD")
            leverage: Leverage multiplier (1-50 depending on symbol and account)
            margin_mode: "cross" or "isolated" (Kraken terminology may differ)
        
        Returns:
            Response data
        """
        kraken_symbol = self.normalize_symbol(symbol)
        
        # Kraken leverage setting endpoint (may need verification)
        payload_dict = {
            "symbol": kraken_symbol,
            "maxLeverage": str(leverage),
            # margin_mode handling may differ per Kraken API
        }
        
        try:
            # Note: Endpoint name may need adjustment per Kraken docs
            return self._req("POST", "/derivatives/api/v3/leveragepreferences", payload=payload_dict)
        except Exception as e:
            print(f"❌ Failed to set leverage: {e}")
            raise


def test_connectivity():
    """Test Kraken Futures API connectivity with configured credentials."""
    client = KrakenFuturesClient()
    
    print("═" * 60)
    print("🔍 Testing Kraken Futures API Connectivity")
    print("═" * 60)
    print(f"📍 Mode: {client.mode}")
    print(f"🌐 Base URL: {client.base}")
    print("═" * 60)
    
    # Test 1: Public endpoint (mark price) - Test symbol normalization
    print("\n1️⃣ Testing mark price (symbol normalization)...")
    try:
        mark = client.get_mark_price("BTCUSDT")
        print(f"   ✅ BTCUSDT mark price: ${mark:,.2f}")
    except Exception as e:
        print(f"   ❌ Failed: {e}")
    
    # Test 2: Account balance (requires auth)
    if KRAKEN_FUTURES_API_KEY:
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
            open_pos = positions.get("openPositions", [])
            print(f"   ✅ Positions retrieved: {len(open_pos)} open positions")
        except Exception as e:
            print(f"   ❌ Failed: {e}")
    
    # Test 4: Fetch OHLCV data
    print("\n4️⃣ Testing market data (OHLCV)...")
    try:
        df = client.fetch_ohlcv("BTCUSDT", "1m", 10)
        print(f"   ✅ Fetched {len(df)} candles")
        print(f"   Latest close: ${df['close'].iloc[-1]:,.2f}")
    except Exception as e:
        print(f"   ❌ Failed: {e}")
    
    # Test 5: Test with ETH
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
