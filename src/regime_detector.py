import pandas as pd
import json
from src.blofin_client import BlofinClient

# Use DataRegistry for canonical symbol loading
try:
    from src.data_registry import DataRegistry as DR
    USE_DATA_REGISTRY = True
except ImportError:
    USE_DATA_REGISTRY = False


def load_canonical_assets():
    """Load canonical asset list from DataRegistry or config/asset_universe.json"""
    # Prefer DataRegistry for centralized management
    if USE_DATA_REGISTRY:
        try:
            return DR.get_enabled_symbols()
        except Exception as e:
            print(f"⚠️ DataRegistry failed, trying direct load: {e}")
    
    # Fallback to direct file read
    try:
        with open("config/asset_universe.json", 'r') as f:
            config = json.load(f)
        
        assets = [
            asset["symbol"] 
            for asset in config.get("asset_universe", [])
            if asset.get("enabled", True)
        ]
        return assets
    except Exception as e:
        print(f"⚠️ Failed to load canonical assets, using fallback: {e}")
        # Fallback includes ALL 15 coins
        return [
            "BTCUSDT", "ETHUSDT", "SOLUSDT", "AVAXUSDT", "DOTUSDT",
            "TRXUSDT", "XRPUSDT", "ADAUSDT", "DOGEUSDT", "BNBUSDT",
            "MATICUSDT", "LINKUSDT", "ARBUSDT", "OPUSDT", "PEPEUSDT"
        ]


ASSETS = load_canonical_assets()
REGIME_MAP = {
    "Trending": ["Trend-Conservative", "Breakout-Aggressive"],
    "Volatile": ["Breakout-Aggressive", "Sentiment-Fusion"],
    "Stable": ["Sentiment-Fusion", "Trend-Conservative", "Breakout-Aggressive"],
    "Ranging": ["Trend-Conservative", "Sentiment-Fusion"]
}


def predict_regime():
    """
    Detect market regime based on cross-asset volatility.
    Returns: Volatile, Trending, Stable, or Ranging
    """
    blofin = BlofinClient()
    volatilities = []
    
    for asset in ASSETS:
        try:
            df = blofin.fetch_ohlcv(asset, timeframe="1m", limit=50)
            pct_change = df["close"].pct_change().dropna()
            vol = pct_change.std()
            volatilities.append(vol)
        except Exception as e:
            print(f"⚠️ Failed to fetch {asset}: {e}")
            continue
    
    if not volatilities:
        return "Unknown"
    
    avg_vol = round(pd.Series(volatilities).mean(), 4)
    
    if avg_vol > 0.03:
        regime = "Volatile"
    elif avg_vol > 0.015:
        regime = "Trending"
    elif avg_vol < 0.008:
        regime = "Stable"
    else:
        regime = "Ranging"
    
    print(f"📊 Market Regime: {regime} (volatility: {avg_vol:.4f})")
    return regime


def get_active_strategies_for_regime(regime):
    """
    Return which strategies should be active for the current regime.
    """
    return REGIME_MAP.get(regime, ["Trend-Conservative"])
