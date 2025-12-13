import json
from pathlib import Path
from typing import Dict, Optional, Any
from datetime import datetime

FEATURE_DIR = Path("feature_store/coinglass")

def load_coinglass_features(symbol: str) -> Optional[Dict[str, Any]]:
    """
    Load latest CoinGlass features for a symbol from cached data.
    
    Returns dict with keys:
    - oi_current: Current open interest
    - funding_current: Current funding rate
    - liq_recent_sum: Recent liquidations sum
    - ts: Timestamp of features
    
    Returns None if no cached features found.
    """
    feature_file = FEATURE_DIR / f"{symbol}_features.json"
    
    if not feature_file.exists():
        return None
    
    try:
        with open(feature_file) as f:
            features = json.load(f)
        
        # Check feature age (warn if older than 1 hour)
        if 'ts' in features:
            feature_time = datetime.fromisoformat(features['ts'].replace('Z', '+00:00'))
            age_sec = (datetime.utcnow().replace(tzinfo=feature_time.tzinfo) - feature_time).total_seconds()
            if age_sec > 3600:
                print(f"⚠️  CoinGlass features for {symbol} are {age_sec/60:.0f} min old")
        
        return {
            'oi_current': features.get('oi_current'),
            'funding_current': features.get('funding_current'),
            'liq_recent_sum': features.get('liq_recent_sum', 0),
            'ts': features.get('ts'),
            'source': 'coinglass'
        }
    
    except Exception as e:
        print(f"❌ Error loading CoinGlass features for {symbol}: {e}")
        return None


def enrich_signal_with_coinglass(signal: Dict[str, Any]) -> Dict[str, Any]:
    """
    Enrich a trading signal with CoinGlass external intelligence.
    
    Adds CoinGlass features to signal dict under 'coinglass' key.
    """
    symbol = signal.get('symbol', '')
    
    if not symbol:
        return signal
    
    cg_features = load_coinglass_features(symbol)
    
    if cg_features:
        signal['coinglass'] = cg_features
    
    return signal


def get_all_cached_features() -> Dict[str, Dict[str, Any]]:
    """
    Load all cached CoinGlass features for all symbols.
    
    Returns dict mapping symbol -> features.
    """
    features = {}
    
    if not FEATURE_DIR.exists():
        return features
    
    for feature_file in FEATURE_DIR.glob("*_features.json"):
        symbol = feature_file.stem.replace('_features', '')
        
        try:
            with open(feature_file) as f:
                features[symbol] = json.load(f)
        except Exception as e:
            print(f"❌ Error loading {feature_file}: {e}")
    
    return features


if __name__ == "__main__":
    # Test loading features
    print("CoinGlass Feature Loader Test")
    print("=" * 50)
    
    all_features = get_all_cached_features()
    
    if not all_features:
        print("❌ No cached features found")
        print(f"   Expected location: {FEATURE_DIR}")
    else:
        print(f"✅ Loaded features for {len(all_features)} symbols:\n")
        
        for symbol, features in sorted(all_features.items()):
            oi = features.get('oi_current', 'N/A')
            funding = features.get('funding_current', 'N/A')
            liq = features.get('liq_recent_sum', 0)
            ts = features.get('ts', 'N/A')
            
            print(f"{symbol:12} | OI: {oi} | Funding: {funding} | Liq: ${liq:,.0f if isinstance(liq, (int, float)) else 'N/A'}")
            print(f"{'':12} | Updated: {ts}")
            print()
