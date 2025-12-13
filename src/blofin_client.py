import os
import time
import requests
import pandas as pd

from src.memory_efficient_cache import get_ohlcv_cache


class BlofinClient:
    """
    Market data client using Binance.US API for real-time OHLCV data.
    Now with built-in caching to prevent memory-intensive repeated DataFrame creation.
    """
    
    def __init__(self):
        self.api_key = os.getenv("BLOFIN_API_KEY", "")
        self.api_secret = os.getenv("BLOFIN_API_SECRET", "")
        self.passphrase = os.getenv("BLOFIN_PASSPHRASE", "")
        self.mode = os.getenv("TRADING_MODE", "paper")
        self.binance_url = "https://api.binance.us/api/v3/klines"
        self._cache = get_ohlcv_cache()
    
    def fetch_ohlcv(self, symbol="BTCUSDT", timeframe="1m", limit=100, use_cache=True):
        """
        Fetch real OHLCV data from Binance.US API with retry logic and caching.
        Falls back to simulated data if all retries fail.
        
        Args:
            symbol: Trading pair (e.g., "BTCUSDT")
            timeframe: Candle interval (1m, 5m, 15m, 1h, 4h, 1d)
            limit: Number of candles to fetch
            use_cache: Use cached data if available (default True, reduces memory churn)
        """
        if use_cache:
            cached = self._cache.get(symbol, timeframe, limit)
            if cached is not None:
                return cached
        
        params = {
            "symbol": symbol,
            "interval": timeframe,
            "limit": limit
        }
        
        for attempt in range(3):
            try:
                response = requests.get(self.binance_url, params=params, timeout=10)
                response.raise_for_status()
                data = response.json()
                
                if not data:
                    raise Exception("No data returned from Binance.US API")
                
                df = pd.DataFrame(data, columns=[
                    "timestamp", "open", "high", "low", "close", "volume",
                    "close_time", "quote_asset_volume", "num_trades",
                    "taker_buy_base", "taker_buy_quote", "ignore"
                ])
                
                df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms")
                df["open"] = df["open"].astype(float)
                df["high"] = df["high"].astype(float)
                df["low"] = df["low"].astype(float)
                df["close"] = df["close"].astype(float)
                df["volume"] = df["volume"].astype(float)
                
                result = df[["timestamp", "open", "high", "low", "close", "volume"]]
                
                if use_cache:
                    self._cache.set(symbol, timeframe, limit, result)
                
                return result
                
            except Exception as e:
                if attempt < 2:
                    wait_time = 1.5 * (attempt + 1)
                    print(f"⚠️ API attempt {attempt + 1} failed for {symbol}: {e}")
                    print(f"   Retrying in {wait_time}s...")
                    time.sleep(wait_time)
                else:
                    print(f"⚠️ All API retries failed for {symbol}: {e}")
                    print("⚠️ Using simulated data as fallback")
                    return self._generate_simulated_data()
    
    def _generate_simulated_data(self):
        """
        Generate simulated OHLCV data as fallback.
        """
        import numpy as np
        
        size = 100
        base_price = 50000
        
        trend = np.linspace(0, 500, size)
        noise = np.random.randn(size) * 100
        prices = base_price + trend + noise
        
        data = {
            "timestamp": pd.date_range(end=pd.Timestamp.now(), periods=size, freq="1min"),
            "open": prices + np.random.randn(size) * 20,
            "high": prices + np.abs(np.random.randn(size) * 30) + 50,
            "low": prices - np.abs(np.random.randn(size) * 30) - 50,
            "close": prices + np.random.randn(size) * 15,
            "volume": np.random.randint(2000, 4000, size)
        }
        
        return pd.DataFrame(data)


def get_current_price(symbol):
    """
    Get current price for a symbol from Binance.US.
    
    Args:
        symbol: Trading pair (e.g., 'BTCUSDT')
    
    Returns:
        Current price as float
    """
    try:
        url = "https://api.binance.us/api/v3/ticker/price"
        params = {"symbol": symbol}
        response = requests.get(url, params=params, timeout=5)
        response.raise_for_status()
        data = response.json()
        return float(data["price"])
    except Exception as e:
        print(f"❌ Error fetching current price for {symbol}: {e}")
        raise
