"""
CoinGlass External Intelligence Integration

Provides market microstructure intelligence from CoinGlass API:
- Funding rates (sentiment indicator)
- Open Interest (capital flows)
- Liquidations (forced selling/buying)
- Long/Short ratios (positioning)

Enriches trading signals with external market intelligence for enhanced decision-making.
"""
import os
import sys
import time
import json
import statistics
from pathlib import Path
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple, Any

try:
    import requests
except ImportError:
    print("ERROR: requests library not installed. Run: pip install requests")
    sys.exit(1)

from src.atomic_write import atomic_write
from src.io_safe import safe_open

# CoinGlass API configuration (v2 API)
BASE_URL = "https://open-api.coinglass.com/public/v2"
FEATURE_DIR = Path("feature_store/coinglass")
CACHE_DIR = FEATURE_DIR / "cache"
LOG_FILE = Path("logs/coinglass_intelligence.log")

# Endpoints (v2 API paths - require ex/pair parameters)
ENDPOINTS = {
    "funding": "/funding_ohlc_history",
    "open_interest": "/open_interest_ohlc_history",
    "liquidations": "/liquidation_history",
    "long_short": "/top_long_short_position_ratio_history",
    "supported_coins": "/supported_exchange_pairs"
}


class CoinGlassClient:
    """CoinGlass API client with rate-limit handling and caching."""
    
    def __init__(self, api_key: str):
        """Initialize client with API key from secrets."""
        if not api_key:
            raise ValueError("COINGLASS_API_KEY is required")
        
        self.api_key = api_key
        self.headers = {
            "accept": "application/json",
            "CG-API-KEY": api_key
        }
        
        # Ensure directories exist
        FEATURE_DIR.mkdir(parents=True, exist_ok=True)
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    
    def log(self, msg: str):
        """Thread-safe logging with timestamp."""
        ts = datetime.utcnow().isoformat() + "Z"
        line = f"[{ts}] {msg}"
        print(line)
        try:
            # Use atomic write for thread safety
            existing = ""
            if LOG_FILE.exists():
                with open(LOG_FILE, "r") as f:
                    existing = f.read()
            atomic_write(str(LOG_FILE), existing + line + "\n")
        except Exception as e:
            print(f"Log write error: {e}")
    
    def safe_get(self, endpoint: str, params: Optional[Dict] = None, 
                  max_retries: int = 5) -> Tuple[Any, Optional[str], Optional[str]]:
        """GET with exponential backoff and rate-limit handling.
        
        Returns:
            Tuple of (response_data, rate_limit, rate_used)
        """
        url = BASE_URL + endpoint
        
        for attempt in range(max_retries):
            try:
                response = requests.get(
                    url, 
                    headers=self.headers, 
                    params=params, 
                    timeout=30
                )
                
                # Extract rate-limit headers
                limit = response.headers.get("API-KEY-MAX-LIMIT") or \
                        response.headers.get("X-RateLimit-Limit")
                used = response.headers.get("API-KEY-USE-LIMIT") or \
                       response.headers.get("X-RateLimit-Remaining")
                
                if response.status_code == 200:
                    return response.json(), limit, used
                
                if response.status_code in (429, 503):
                    backoff = (2 ** attempt) + 1
                    self.log(f"Rate limited ({response.status_code}). "
                            f"Backoff {backoff}s. Limit={limit} Used={used}")
                    time.sleep(backoff)
                    continue
                
                # Other errors
                self.log(f"HTTP {response.status_code} error for {url} "
                        f"params={params} body={response.text[:200]}")
                time.sleep(1)
                
            except requests.exceptions.RequestException as e:
                self.log(f"Request error (attempt {attempt+1}/{max_retries}): {e}")
                time.sleep(2 ** attempt)
        
        raise RuntimeError(f"Failed to GET {url} after {max_retries} attempts")
    
    def cache_write(self, key: str, data: Any) -> Path:
        """Write data to cache using atomic writes."""
        path = CACHE_DIR / f"{key}.json"
        atomic_write(str(path), json.dumps(data, indent=2))
        return path
    
    def cache_read(self, key: str) -> Optional[Any]:
        """Read data from cache if exists."""
        path = CACHE_DIR / f"{key}.json"
        if path.exists():
            try:
                with safe_open(str(path), "r") as f:
                    return json.load(f)
            except Exception as e:
                self.log(f"Cache read error for {key}: {e}")
        return None
    
    def validate_api_key(self) -> bool:
        """Validate API key with test request."""
        try:
            data, limit, used = self.safe_get(ENDPOINTS["supported_coins"])
            coins_count = len(data.get("data", [])) if isinstance(data, dict) else "unknown"
            self.log(f"✅ API key validated. Supported coins: {coins_count}")
            self.log(f"Rate limits: max={limit} used={used}")
            return True
        except Exception as e:
            self.log(f"❌ API key validation failed: {e}")
            return False
    
    def backfill_symbol(self, symbol: str, endpoint_key: str, 
                        days: int = 365, exchange: str = "Binance") -> Optional[Path]:
        """Backfill historical data for symbol/endpoint.
        
        Args:
            symbol: Trading pair (e.g., BTCUSDT)
            endpoint_key: One of funding, open_interest, liquidations
            days: Number of days to backfill
            exchange: Exchange name (default: Binance)
        
        Returns:
            Path to backfill cache file
        """
        self.log(f"📊 Backfill start: {symbol} {endpoint_key} on {exchange} ({days} days)")
        
        # v2 API uses ex/pair parameters
        params = {
            "ex": exchange,
            "pair": symbol,
            "interval": "d1"  # Daily data
        }
        
        # Add time range for historical data
        if days < 365:
            end_time = int(datetime.utcnow().timestamp() * 1000)
            start_time = int((datetime.utcnow() - timedelta(days=days)).timestamp() * 1000)
            params["startTime"] = str(start_time)
            params["endTime"] = str(end_time)
        
        try:
            data, limit, used = self.safe_get(ENDPOINTS[endpoint_key], params)
            self.log(f"  Received data for {symbol} {endpoint_key} "
                    f"(limit={limit} used={used})")
            
            # Store the complete response
            result = {
                "symbol": symbol,
                "exchange": exchange,
                "endpoint": endpoint_key,
                "days": days,
                "data": data
            }
            
        except Exception as e:
            self.log(f"⚠️ Backfill error {symbol} {endpoint_key}: {e}")
            result = {
                "symbol": symbol,
                "exchange": exchange,
                "endpoint": endpoint_key,
                "days": days,
                "data": [],
                "error": str(e)
            }
        
        # Write backfill cache
        cache_key = f"{symbol}_{endpoint_key}_backfill"
        path = self.cache_write(cache_key, result)
        self.log(f"✅ Backfill complete: {symbol} {endpoint_key} -> {path}")
        return path
    
    def derive_features(self, symbol: str) -> Optional[Path]:
        """Derive trading features from cached data.
        
        Features:
        - oi_delta_pct: Open Interest change (%)
        - funding_zscore: Funding rate z-score
        - liq_recent_sum: Recent liquidation volume
        
        Args:
            symbol: Trading pair (e.g., BTCUSDT)
        
        Returns:
            Path to features file
        """
        # Load cached backfills
        oi = self.cache_read(f"{symbol}_open_interest_backfill") or {}
        fund = self.cache_read(f"{symbol}_funding_backfill") or {}
        liq = self.cache_read(f"{symbol}_liquidations_backfill") or {}
        
        # Extract data arrays from response (handle both dict and list formats)
        if isinstance(oi, dict):
            oi_data = oi.get('data', {}).get('data', []) if isinstance(oi.get('data'), dict) else oi.get('data', [])
        else:
            oi_data = oi if isinstance(oi, list) else []
            
        if isinstance(fund, dict):
            fund_data = fund.get('data', {}).get('data', []) if isinstance(fund.get('data'), dict) else fund.get('data', [])
        else:
            fund_data = fund if isinstance(fund, list) else []
            
        if isinstance(liq, dict):
            liq_data = liq.get('data', {}).get('data', []) if isinstance(liq.get('data'), dict) else liq.get('data', [])
        else:
            liq_data = liq if isinstance(liq, list) else []
        
        features: Dict[str, Any] = {
            "symbol": symbol,
            "ts": datetime.utcnow().isoformat() + "Z",
            "source": "coinglass"
        }
        
        try:
            # Delta OI: compare most recent vs prior period
            if len(oi_data) >= 2:
                # Reverse order (newest first)
                last = oi_data[-1] if len(oi_data) > 0 else {}
                prev = oi_data[-2] if len(oi_data) > 1 else {}
                last_val = float(last.get("v", last.get("value", 0)) or 0)
                prev_val = float(prev.get("v", prev.get("value", 0)) or 0)
                
                if prev_val > 0:
                    features["oi_delta_pct"] = (last_val - prev_val) / prev_val
                    features["oi_current"] = last_val
                    self.log(f"  {symbol} OI: ${last_val:,.0f} "
                            f"(Δ{features['oi_delta_pct']*100:.2f}%)")
            
            # Funding zscore: statistical deviation from mean
            fund_vals = []
            for rec in fund_data:
                v = rec.get("v") or rec.get("rate") or rec.get("fundingRate")
                if v is not None:
                    try:
                        fund_vals.append(float(v))
                    except:
                        pass
            
            if len(fund_vals) >= 5:
                mu = statistics.mean(fund_vals)
                sd = statistics.pstdev(fund_vals) or 1.0
                current = fund_vals[-1] if fund_vals else 0
                features["funding_zscore"] = (current - mu) / sd if sd > 0 else 0
                features["funding_current"] = current
                features["funding_mean"] = mu
                self.log(f"  {symbol} Funding: {current:.6f} "
                        f"(z={features['funding_zscore']:.2f})")
            
            # Liquidation spike: sum recent liquidations
            liq_sum = 0.0
            for rec in liq_data[-5:]:  # Last 5 periods
                amt = rec.get("v") or rec.get("amount") or rec.get("liquidationAmount") or 0
                try:
                    liq_sum += float(amt)
                except:
                    pass
            
            if liq_sum > 0:
                features["liq_recent_sum"] = liq_sum
                self.log(f"  {symbol} Liquidations: ${liq_sum:,.0f}")
        
        except Exception as e:
            self.log(f"⚠️ Feature derivation error for {symbol}: {e}")
        
        # Write features file
        filename = FEATURE_DIR / f"{symbol}_features.json"
        atomic_write(str(filename), json.dumps(features, indent=2))
        self.log(f"✅ Features written: {filename}")
        return filename
    
    def poll_once(self, symbols: List[str], exchange: str = "Binance"):
        """Poll latest data for all endpoints and symbols."""
        for symbol in symbols:
            for endpoint_key in ("funding", "open_interest", "long_short", "liquidations"):
                try:
                    # Get latest data with v2 API parameters
                    params = {
                        "ex": exchange,
                        "pair": symbol,
                        "interval": "h1"  # Hourly data for polling
                    }
                    data, limit, used = self.safe_get(ENDPOINTS[endpoint_key], params)
                    
                    # Cache latest snapshot
                    cache_key = f"{symbol}_{endpoint_key}_latest"
                    self.cache_write(cache_key, {
                        "ts": datetime.utcnow().isoformat() + "Z",
                        "data": data
                    })
                    
                    # Rate-limit friendly sleep
                    time.sleep(0.15)
                    
                except Exception as e:
                    self.log(f"⚠️ Poll error {symbol} {endpoint_key}: {e}")
        
        # Derive features after polling
        for symbol in symbols:
            try:
                self.derive_features(symbol)
            except Exception as e:
                self.log(f"⚠️ Feature derivation error for {symbol}: {e}")


def get_api_key() -> str:
    """Get API key from Replit secrets."""
    # Try Replit secrets first
    api_key = os.environ.get("COINGLASS_API_KEY")
    
    if not api_key:
        raise ValueError(
            "COINGLASS_API_KEY not found in secrets. "
            "Please add it via the Replit Secrets tab."
        )
    
    return api_key


def main():
    """Main orchestration for backfill + polling."""
    print("=" * 80)
    print("CoinGlass External Intelligence Integration")
    print("=" * 80)
    
    # Get API key
    try:
        api_key = get_api_key()
    except ValueError as e:
        print(f"❌ {e}")
        return 1
    
    # Initialize client
    client = CoinGlassClient(api_key)
    
    # Validate API key
    if not client.validate_api_key():
        print("❌ API key validation failed. Check your key and try again.")
        return 1
    
    # Configuration - use DataRegistry for canonical symbol list
    try:
        from src.data_registry import DataRegistry as DR
        default_symbols = ",".join(DR.get_enabled_symbols())
    except Exception:
        # Fallback includes ALL 15 coins
        default_symbols = "BTCUSDT,ETHUSDT,SOLUSDT,BNBUSDT,AVAXUSDT,DOTUSDT,XRPUSDT,ADAUSDT,DOGEUSDT,TRXUSDT,MATICUSDT,LINKUSDT,ARBUSDT,OPUSDT,PEPEUSDT"
    
    symbols = os.environ.get("COINGLASS_SYMBOLS", default_symbols).split(",")
    
    backfill_days = int(os.environ.get("COINGLASS_BACKFILL_DAYS", "365"))
    poll_interval = int(os.environ.get("COINGLASS_POLL_INTERVAL_SEC", "300"))
    
    client.log(f"Configuration: symbols={len(symbols)} backfill={backfill_days}d "
               f"poll={poll_interval}s")
    
    # Backfill historical data
    print(f"\n📊 Starting backfill for {len(symbols)} symbols ({backfill_days} days)...")
    for symbol in symbols:
        print(f"\nBackfilling {symbol}...")
        client.backfill_symbol(symbol, "open_interest", days=backfill_days)
        client.backfill_symbol(symbol, "funding", days=backfill_days)
        # Limit liquidations to 90 days (heavy data)
        client.backfill_symbol(symbol, "liquidations", days=min(90, backfill_days))
    
    # Derive initial features
    print(f"\n🧠 Deriving features for {len(symbols)} symbols...")
    for symbol in symbols:
        client.derive_features(symbol)
    
    # Start polling loop
    print(f"\n🔄 Starting polling loop (interval={poll_interval}s, CTRL-C to stop)...")
    try:
        while True:
            client.log(f"Polling {len(symbols)} symbols...")
            client.poll_once(symbols)
            client.log(f"Poll complete. Sleeping {poll_interval}s...")
            time.sleep(poll_interval)
    except KeyboardInterrupt:
        client.log("⏸️ Polling interrupted by user")
        print("\n⏸️ Polling stopped by user")
    except Exception as e:
        client.log(f"❌ Fatal error: {e}")
        print(f"\n❌ Fatal error: {e}")
        return 1
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
