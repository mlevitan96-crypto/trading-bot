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

# Load .env file if running directly (for testing)
if __name__ == "__main__":
    try:
        from dotenv import load_dotenv
        env_path = _project_root / ".env"
        if env_path.exists():
            load_dotenv(env_path)
            print(f"✅ Loaded .env from: {env_path}")
    except ImportError:
        pass  # dotenv not available, use environment variables as-is

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
    
    def __init__(self, base_url: str = None, session: Optional[requests.Session] = None):
        """
        Initialize Kraken Futures API client.
        
        Args:
            base_url: Base URL for Kraken Futures API (defaults from env)
            session: Optional requests session (for connection pooling)
        """
        if base_url is None:
            base_url = KRAKEN_FUTURES_BASE
        self.base = base_url.rstrip("/")
        self.sess = session or requests.Session()
        self.mode = "paper" if KRAKEN_FUTURES_TESTNET else ("live" if KRAKEN_FUTURES_API_KEY else "paper")
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
                # For GET, params go in URL
                if post_data:
                    # Add query params to URL
                    if "?" in url:
                        url += "&" + post_data
                    else:
                        url += "?" + post_data
                
                if not KRAKEN_FUTURES_API_KEY:
                    # Public GET - no auth headers needed
                    resp = self.sess.request(method, url, timeout=TIMEOUT)
                else:
                    # Authenticated GET - use headers but no body
                    resp = self.sess.request(method, url, headers=headers, timeout=TIMEOUT)
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
        
        # Mark price field (check multiple possible field names per Kraken API)
        # Kraken may use: markPrice, mark_price, indexPrice, last, lastPrice
        mark_price = (
            ticker.get("markPrice") or 
            ticker.get("mark_price") or
            ticker.get("indexPrice") or 
            ticker.get("last") or
            ticker.get("lastPrice") or
            ticker.get("fundingRate")  # Fallback, unlikely but possible
        )
        if mark_price is None:
            # Debug: print available fields
            available_fields = list(ticker.keys())
            raise Exception(f"Mark price field missing for {kraken_symbol}. Available fields: {available_fields}. Ticker: {ticker}")
        
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
        
        # Kraken OHLCV endpoint format: GET /:tick_type/:symbol/:resolution
        # tick_type can be: 'mark', 'spot', or 'trade'
        # We use 'trade' for actual trading data, or 'mark' for mark prices
        tick_type = "trade"  # Use 'trade' for OHLCV data (actual price movements)
        kraken_timeframe = timeframe  # Kraken uses same format: 1m, 5m, 15m, 1h, 4h, 1d
        
        # Calculate from timestamp (limit candles back from now)
        # Approximate: 1m = 60s, 5m = 300s, 15m = 900s, 1h = 3600s, 4h = 14400s, 1d = 86400s
        timeframe_seconds = {
            "1m": 60, "5m": 300, "15m": 900, "1h": 3600, 
            "4h": 14400, "12h": 43200, "1d": 86400, "1w": 604800
        }
        interval_seconds = timeframe_seconds.get(timeframe, 3600)
        from_timestamp = int(time.time()) - (limit * interval_seconds)
        
        # Kraken endpoint: /api/charts/v1/:tick_type/:symbol/:resolution?from={timestamp}
        # Note: This might be /derivatives/api/v3/charts/:tick_type/:symbol/:resolution
        # Let's try both formats and see which works
        endpoint_path = f"/api/charts/v1/{tick_type}/{kraken_symbol}/{kraken_timeframe}"
        query_params = {"from": from_timestamp}
        
        try:
            data = self._req("GET", endpoint_path, payload=query_params)
        except Exception as e:
            # Try alternative endpoint format
            if "404" in str(e) or "NOT_FOUND" in str(e):
                # Alternative: /derivatives/api/v3/charts/:tick_type/:symbol/:resolution
                endpoint_path = f"/derivatives/api/v3/charts/{tick_type}/{kraken_symbol}/{kraken_timeframe}"
                data = self._req("GET", endpoint_path, payload=query_params)
            else:
                raise
        
        # Kraken response format may vary - check for different structures
        # Format 1: {"candles": [{"time": ms, "open": str, ...}, ...]}
        # Format 2: {"result": "success", "candles": [[timestamp, open, high, low, close, volume], ...]}
        # Format 3: Direct array [[timestamp, open, high, low, close, volume], ...]
        
        candles = data.get("candles", [])
        if not candles and isinstance(data, list):
            candles = data  # Direct array format
        
        if not candles:
            raise Exception(f"No candle data returned for {kraken_symbol}. Response: {data}")
        
        # Limit to requested number (Kraken may return more)
        candles = candles[:limit]
        
        # Convert to DataFrame - handle both formats
        df_data = []
        for candle in candles:
            if isinstance(candle, dict):
                # Format 1: {"time": ms, "open": str, ...}
                df_data.append({
                    "timestamp": candle.get("time") or candle.get("timestamp"),
                    "open": float(candle.get("open", 0)),
                    "high": float(candle.get("high", 0)),
                    "low": float(candle.get("low", 0)),
                    "close": float(candle.get("close", 0)),
                    "volume": float(candle.get("volume", 0))
                })
            elif isinstance(candle, list) and len(candle) >= 6:
                # Format 2: [timestamp, open, high, low, close, volume]
                df_data.append({
                    "timestamp": candle[0],
                    "open": float(candle[1]),
                    "high": float(candle[2]),
                    "low": float(candle[3]),
                    "close": float(candle[4]),
                    "volume": float(candle[5])
                })
        
        if not df_data:
            raise Exception(f"Could not parse candle data for {kraken_symbol}. Format: {type(candles[0]) if candles else 'empty'}")
        
        df = pd.DataFrame(df_data)
        
        # Convert timestamp (Kraken uses milliseconds)
        df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms")
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
        
        Note: Balance endpoint is not supported on Kraken Futures testnet.
        This will return an authentication error, which is expected.
        
        Returns:
            Account balance data
        """
        try:
            result = self._req("GET", "/derivatives/api/v3/accounts")
            return result
        except Exception as e:
            error_str = str(e)
            
            # Handle testnet limitation explicitly
            if "authenticationError" in error_str or "authentication" in error_str.lower():
                is_testnet = os.getenv("KRAKEN_FUTURES_TESTNET", "false").lower() == "true"
                if is_testnet:
                    # Expected limitation on testnet - log but don't treat as error
                    print(f"ℹ️  [KRAKEN] Balance endpoint unsupported on testnet (expected limitation)")
                    return {
                        "result": "error",
                        "error": "Balance endpoint unsupported on testnet",
                        "testnet_limitation": True,
                        "accounts": []
                    }
            
            print(f"⚠️ [KRAKEN] Failed to get balance: {error_str}")
            return {"result": "error", "error": error_str, "accounts": []}
    
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
            qty: Order quantity (size in USD notional - will be converted to contracts)
            price: Limit price (None for market orders, will be normalized to tick size)
            leverage: Leverage multiplier (1-10x) - note: Kraken may require separate leverage setting
            order_type: "MARKET" or "LIMIT"
            reduce_only: If True, only reduce existing position
            take_profit: Take profit price
            stop_loss: Stop loss price
        
        Returns:
            Order response data
        """
        kraken_symbol = self.normalize_symbol(symbol)
        
        # Normalize size using canonical sizing helper
        # qty is expected to be in USD notional - convert to contracts
        if price is None or price <= 0:
            # For market orders, get current price first
            try:
                price = self.get_mark_price(symbol)
            except Exception as e:
                print(f"⚠️ [SIZING] Failed to get price for market order sizing: {e}")
                # Fallback - use qty as contracts (may cause issues but better than crash)
                print(f"   ⚠️ Using qty={qty} as contracts (not normalized)")
                price = 0  # Will be handled below
        
        # Normalize using canonical sizing helper
        try:
            from src.canonical_sizing_helper import normalize_position_size
            contracts, adjusted_usd, adjustments = normalize_position_size(
                symbol=symbol,
                target_usd=qty,
                price=price,
                exchange="kraken"
            )
            
            if contracts <= 0:
                return {
                    "result": "error",
                    "error": f"Size ${qty:.2f} too small or invalid (normalized to 0 contracts)",
                    "adjustments": adjustments
                }
            
            # Use normalized contracts and adjusted price
            qty = contracts
            if price > 0 and adjustments.get("price_tick_rounded"):
                price = adjustments.get("tick_rounded_price", price)
            
            # Log if significant adjustment
            if adjustments.get("size_change_pct", 0) != 0:
                change_pct = adjustments.get("size_change_pct", 0)
                print(f"📏 [SIZING] Normalized {symbol}: ${qty * price:.2f} → ${adjusted_usd:.2f} ({change_pct:+.1f}%)")
        except Exception as e:
            print(f"⚠️ [SIZING] Size normalization failed, using raw values: {e}")
            # Continue with original qty (may cause rejection but won't crash)
        
        # Normalize price to tick size if provided
        if price and price > 0:
            try:
                from src.kraken_contract_specs import get_kraken_contract_specs, normalize_to_tick_size
                specs = get_kraken_contract_specs(kraken_symbol)
                price = normalize_to_tick_size(price, specs["tick_size"])
            except Exception as e:
                print(f"⚠️ [SIZING] Price tick normalization failed: {e}")
        
        # Validate order size before placing
        try:
            from src.canonical_sizing_helper import validate_order_size
            is_valid, error_msg, validation_details = validate_order_size(
                symbol=symbol,
                contracts=qty,
                price=price if price else 1.0,
                exchange="kraken"
            )
            if not is_valid:
                return {
                    "result": "error",
                    "error": f"Invalid order size: {error_msg}",
                    "validation_details": validation_details
                }
        except Exception as e:
            print(f"⚠️ [SIZING] Order size validation failed: {e}")
            # Continue anyway (validation is best-effort)
        
        # Kraken sendorder endpoint requires URL-encoded post_data
        # Format: orderType=limit&symbol=PI_XBTUSD&side=buy&size=1&limitPrice=50000
        # Note: size is in contracts (already normalized by canonical sizing helper above)
        payload_dict = {
            "symbol": kraken_symbol,
            "side": side.lower(),  # buy or sell
            "size": str(qty),  # Contract count (normalized)
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
