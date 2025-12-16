#!/usr/bin/env python3
"""
Market Intelligence System - CoinGlass Hobbyist Edition
Uses only accessible endpoints on CoinGlass Hobbyist plan ($18/month):

AVAILABLE DATA:
1. /api/futures/taker-buy-sell-volume/exchange-list - Order flow (buy/sell pressure)
2. /api/futures/liquidation/coin-list - Liquidation data (cascade risk)
3. /api/index/fear-greed-history - Fear & Greed Index (macro sentiment)

SIGNAL LOGIC:
- Taker Buy/Sell: High buy ratio = bullish, high sell ratio = bearish
- Liquidations: Longs getting liquidated = bearish, shorts getting liquidated = bullish
- Fear & Greed: <25 = extreme fear (contrarian buy), >75 = greed (contrarian sell)

Reference: https://docs.coinglass.com/reference/endpoint-overview
"""

import os
import json
import time
import requests
from pathlib import Path
from datetime import datetime
from typing import Dict, Any, Optional, List

COINGLASS_URL = "https://open-api-v4.coinglass.com"
COINGLASS_API_KEY = os.environ.get('COINGLASS_API_KEY', '')

# Hobbyist plan: 30 requests/min = 1 request every 2 seconds
# Use 2.5s delay to stay safely under limit with margin
COINGLASS_RATE_LIMIT_DELAY = 2.5
_last_coinglass_call = 0.0

# Reduce symbols to top 8 to stay under rate limit (8 per-symbol calls + 2 bulk = 10 calls)
# Priority symbols by trading volume and liquidity
SYMBOLS = ['BTC', 'ETH', 'SOL', 'XRP', 'DOGE', 'BNB', 'AVAX', 'ADA']

FEATURE_DIR = Path("feature_store/intelligence")
LOG_FILE = Path("logs/market_intelligence.log")
FUNDING_CACHE = FEATURE_DIR / "funding_rates.json"
OI_CACHE = FEATURE_DIR / "open_interest.json"

FEATURE_DIR.mkdir(parents=True, exist_ok=True)
LOG_FILE.parent.mkdir(parents=True, exist_ok=True)


def log(msg: str):
    ts = datetime.utcnow().isoformat() + "Z"
    entry = f"[{ts}] {msg}"
    print(entry)
    try:
        with open(LOG_FILE, 'a') as f:
            f.write(entry + '\n')
    except (OSError, IOError):
        pass  # Gracefully ignore I/O errors


def _rate_limit():
    """Enforce CoinGlass Hobbyist rate limit (30 req/min = 2s between calls)."""
    # Use centralized rate limiter if available, otherwise fall back to simple delay
    try:
        from src.coinglass_rate_limiter import wait_for_rate_limit
        wait_for_rate_limit()
    except ImportError:
        # Fallback to simple delay if rate limiter not available
        global _last_coinglass_call
        elapsed = time.time() - _last_coinglass_call
        if elapsed < COINGLASS_RATE_LIMIT_DELAY:
            sleep_time = COINGLASS_RATE_LIMIT_DELAY - elapsed
            time.sleep(sleep_time)
        _last_coinglass_call = time.time()


def coinglass_get(endpoint: str, params: Optional[Dict] = None) -> Optional[Dict]:
    """Make rate-limited request to CoinGlass API (Hobbyist: 30 req/min)."""
    if not COINGLASS_API_KEY:
        log("   No CoinGlass API key configured")
        return None
    
    # Enforce rate limit before making request
    _rate_limit()
    
    url = f"{COINGLASS_URL}{endpoint}"
    headers = {'accept': 'application/json', 'CG-API-KEY': COINGLASS_API_KEY}
    
    try:
        resp = requests.get(url, headers=headers, params=params or {}, timeout=15)
        if resp.status_code == 200:
            data = resp.json()
            if data.get('code') == '0':
                return data
            log(f"   API error: {data.get('msg', 'unknown')}")
            return None
        elif resp.status_code == 429:
            log(f"   Rate limited - waiting 60s before retry")
            time.sleep(60)
            return None
        log(f"   HTTP {resp.status_code}")
        return None
    except Exception as e:
        log(f"   Request error: {e}")
        return None


def get_taker_buy_sell() -> Dict[str, Dict]:
    """
    Get taker buy/sell volume ratio per symbol.
    High buy ratio = bullish order flow
    High sell ratio = bearish order flow
    
    Response format:
    {
      "symbol": "BTC",
      "buy_ratio": 48.0,
      "sell_ratio": 52.0,
      "buy_vol_usd": 33137263281.17,
      "sell_vol_usd": 35895803441.49
    }
    """
    results = {}
    
    for symbol in SYMBOLS:
        data = coinglass_get("/api/futures/taker-buy-sell-volume/exchange-list",
                            {"symbol": symbol, "range": "24h"})
        if data and 'data' in data:
            d = data.get('data', {})
            if isinstance(d, dict) and 'buy_ratio' in d:
                buy_ratio = float(d.get('buy_ratio', 50)) / 100
                sell_ratio = float(d.get('sell_ratio', 50)) / 100
                buy_vol = float(d.get('buy_vol_usd', 0) or 0)
                sell_vol = float(d.get('sell_vol_usd', 0) or 0)
                
                results[symbol] = {
                    'buy_vol_usd': buy_vol,
                    'sell_vol_usd': sell_vol,
                    'buy_ratio': buy_ratio,
                    'sell_ratio': sell_ratio,
                    'buy_sell_ratio': buy_vol / sell_vol if sell_vol > 0 else 1.0
                }
        # Rate limiting now handled globally in coinglass_get()
    
    return results


def get_liquidations() -> Dict[str, Dict]:
    """
    Get 24h liquidation data per coin.
    More long liquidations = bearish (longs getting stopped out)
    More short liquidations = bullish (shorts getting squeezed)
    """
    data = coinglass_get("/api/futures/liquidation/coin-list")
    if not data or 'data' not in data:
        return {}
    
    results = {}
    for item in data.get('data', []):
        symbol = item.get('symbol', '')
        if symbol in SYMBOLS:
            long_liq = float(item.get('long_liquidation_usd_24h', 0) or 0)
            short_liq = float(item.get('short_liquidation_usd_24h', 0) or 0)
            total = long_liq + short_liq
            
            results[symbol] = {
                'liq_long_24h': long_liq,
                'liq_short_24h': short_liq,
                'liq_total_24h': total,
                'liq_ratio': long_liq / total if total > 0 else 0.5,
                'liq_1h_long': float(item.get('long_liquidation_usd_1h', 0) or 0),
                'liq_1h_short': float(item.get('short_liquidation_usd_1h', 0) or 0),
                'liq_4h_long': float(item.get('long_liquidation_usd_4h', 0) or 0),
                'liq_4h_short': float(item.get('short_liquidation_usd_4h', 0) or 0),
            }
    
    return results


def get_fear_greed() -> int:
    """
    Get current Fear & Greed Index (0-100).
    <25 = Extreme Fear (contrarian buy signal)
    25-45 = Fear
    45-55 = Neutral
    55-75 = Greed
    >75 = Extreme Greed (contrarian sell signal)
    """
    data = coinglass_get("/api/index/fear-greed-history", {"limit": 1})
    if data and 'data' in data:
        data_obj = data.get('data', {})
        if isinstance(data_obj, dict):
            data_list = data_obj.get('data_list', [])
            if data_list and len(data_list) > 0:
                return int(data_list[0])
        elif isinstance(data_obj, list) and len(data_obj) > 0:
            return int(data_obj[0])
    return 50


def compute_signals(taker_data: Dict, liq_data: Dict, fear_greed: int) -> Dict[str, Dict]:
    """
    Compute trading signals from available data.
    
    Signal Components:
    1. Taker Flow (40%): Buy/sell ratio indicates order flow direction
    2. Liquidation (40%): Which side is getting liquidated
    3. Fear & Greed (20%): Contrarian macro sentiment
    """
    signals = {}
    
    for symbol in SYMBOLS:
        taker = taker_data.get(symbol, {})
        liq = liq_data.get(symbol, {})
        
        buy_sell_ratio = taker.get('buy_sell_ratio', 1.0)
        flow_signal = 0
        if buy_sell_ratio > 1.15:
            flow_signal = 1
        elif buy_sell_ratio < 0.87:
            flow_signal = -1
        
        liq_ratio = liq.get('liq_ratio', 0.5)
        liq_signal = 0
        if liq_ratio > 0.60:
            liq_signal = -1
        elif liq_ratio < 0.40:
            liq_signal = 1
        
        fg_signal = 0
        if fear_greed < 25:
            fg_signal = 1
        elif fear_greed > 75:
            fg_signal = -1
        
        composite = (
            flow_signal * 0.40 +
            liq_signal * 0.40 +
            fg_signal * 0.20
        )
        
        if composite >= 0.4:
            direction = "LONG"
            confidence = min(abs(composite), 1.0)
        elif composite <= -0.4:
            direction = "SHORT"
            confidence = min(abs(composite), 1.0)
        else:
            direction = "NEUTRAL"
            confidence = 0.0
        
        signals[symbol] = {
            'direction': direction,
            'confidence': round(confidence, 3),
            'composite': round(composite, 3),
            'components': {
                'flow': flow_signal,
                'liquidation': liq_signal,
                'fear_greed': fg_signal
            },
            'raw': {
                'buy_sell_ratio': round(buy_sell_ratio, 3),
                'liq_ratio': round(liq_ratio, 3),
                'fear_greed': fear_greed
            }
        }
    
    return signals


def poll_intelligence():
    """Poll all available CoinGlass data and compute signals."""
    log("=" * 60)
    log("Market Intelligence Poll (CoinGlass Hobbyist)")
    log("=" * 60)
    
    log("Fetching Taker Buy/Sell Volume...")
    taker = get_taker_buy_sell()
    log(f"   Got {len(taker)} symbols")
    
    log("Fetching Liquidation Data...")
    liq = get_liquidations()
    log(f"   Got {len(liq)} symbols")
    
    log("Fetching Fear & Greed Index...")
    fg = get_fear_greed()
    log(f"   Fear & Greed: {fg}")
    
    log("Computing signals...")
    signals = compute_signals(taker, liq, fg)
    
    for symbol in SYMBOLS:
        feature_file = FEATURE_DIR / f"{symbol}USDT_intel.json"
        output = {
            'symbol': symbol,
            'ts': datetime.utcnow().isoformat() + 'Z',
            'taker': taker.get(symbol, {}),
            'liquidation': liq.get(symbol, {}),
            'fear_greed': fg,
            'signal': signals.get(symbol, {})
        }
        with open(feature_file, 'w') as f:
            json.dump(output, f, indent=2)
    
    summary = {
        'ts': datetime.utcnow().isoformat() + 'Z',
        'fear_greed': fg,
        'signals': {f"{s}USDT": signals.get(s, {}) for s in SYMBOLS}
    }
    with open(FEATURE_DIR / "summary.json", 'w') as f:
        json.dump(summary, f, indent=2)
    
    log("=" * 60)
    log("Signal Summary:")
    for symbol in SYMBOLS:
        sig = signals.get(symbol, {})
        if sig.get('direction') != 'NEUTRAL':
            log(f"   {symbol}USDT: {sig['direction']} (conf={sig['confidence']:.2f}, raw B/S={sig['raw']['buy_sell_ratio']:.2f})")
    log("=" * 60)
    
    return signals


def load_latest_signals() -> Dict:
    """Load latest signals from file (for use by trading bot)."""
    summary_file = FEATURE_DIR / "summary.json"
    if summary_file.exists():
        with open(summary_file) as f:
            return json.load(f)
    return {}


def get_signal(symbol: str) -> Optional[Dict]:
    """Get signal for a specific symbol."""
    if not symbol.endswith('USDT'):
        symbol = f"{symbol}USDT"
    
    feature_file = FEATURE_DIR / f"{symbol}_intel.json"
    if feature_file.exists():
        try:
            with open(feature_file) as f:
                data = json.load(f)
                return data.get('signal', {})
        except:
            pass
    return None


def _get_binance_funding_rates() -> Dict[str, Dict]:
    """Get funding rates from Binance Futures public API (no auth required)."""
    results = {}
    try:
        resp = requests.get(
            "https://fapi.binance.com/fapi/v1/premiumIndex",
            timeout=10
        )
        if resp.status_code == 200:
            data = resp.json()
            for item in data:
                symbol_full = item.get('symbol', '')
                if symbol_full.endswith('USDT'):
                    symbol = symbol_full.replace('USDT', '')
                    if symbol in SYMBOLS:
                        rate = float(item.get('lastFundingRate', 0) or 0)
                        mark_price = float(item.get('markPrice', 0) or 0)
                        
                        results[symbol] = {
                            'funding_rate': rate,
                            'predicted_rate': 0,
                            'mark_price': mark_price,
                            'funding_signal': -1 if rate > 0.0005 else (1 if rate < -0.0005 else 0),
                            'source': 'binance'
                        }
            log(f"   Binance funding: Got {len(results)} symbols")
    except Exception as e:
        log(f"   Binance funding error: {e}")
    return results


def get_funding_rates() -> Dict[str, Dict]:
    """
    Get current funding rates for all symbols.
    Positive funding = longs pay shorts = bearish crowd positioning
    Negative funding = shorts pay longs = bullish crowd positioning
    
    Primary: Binance Futures (reliable, no auth)
    Fallback: CoinGlass API
    """
    results = _get_binance_funding_rates()
    
    if not results or all(r.get('funding_rate', 0) == 0 for r in results.values()):
        log("   Trying CoinGlass fallback for funding...")
        data = coinglass_get("/api/futures/funding-rate/exchange-list")
        if data and 'data' in data:
            for item in data.get('data', []):
                symbol = item.get('symbol', '')
                if symbol in SYMBOLS:
                    rate = 0.0
                    stablecoin_list = item.get('stablecoin_margin_list', [])
                    for exchange_data in stablecoin_list:
                        if exchange_data.get('exchange') == 'Binance':
                            rate = float(exchange_data.get('funding_rate', 0) or 0)
                            break
                    if rate == 0 and stablecoin_list:
                        rate = float(stablecoin_list[0].get('funding_rate', 0) or 0)
                    
                    results[symbol] = {
                        'funding_rate': rate,
                        'predicted_rate': 0,
                        'funding_signal': -1 if rate > 0.0005 else (1 if rate < -0.0005 else 0),
                        'source': 'coinglass'
                    }
    
    with open(FUNDING_CACHE, 'w') as f:
        json.dump({'ts': datetime.utcnow().isoformat() + 'Z', 'rates': results}, f, indent=2)
    
    return results


def _get_binance_open_interest() -> Dict[str, Dict]:
    """Get open interest from Binance Futures public API (no auth required)."""
    results = {}
    try:
        resp = requests.get(
            "https://fapi.binance.com/fapi/v1/openInterest",
            params={"symbol": "BTCUSDT"},
            timeout=10
        )
        if resp.status_code == 200:
            for symbol in SYMBOLS:
                try:
                    resp = requests.get(
                        "https://fapi.binance.com/fapi/v1/openInterest",
                        params={"symbol": f"{symbol}USDT"},
                        timeout=5
                    )
                    if resp.status_code == 200:
                        data = resp.json()
                        oi = float(data.get('openInterest', 0) or 0)
                        results[symbol] = {
                            'open_interest': oi,
                            'oi_change_24h': 0,
                            'oi_change_1h': 0,
                            'oi_signal': 0,
                            'source': 'binance'
                        }
                except:
                    pass
            log(f"   Binance OI: Got {len(results)} symbols")
    except Exception as e:
        log(f"   Binance OI error: {e}")
    return results


def get_open_interest_delta() -> Dict[str, Dict]:
    """
    Get open interest changes for all symbols.
    Rising OI + Rising Price = Strong trend (new money entering)
    Rising OI + Falling Price = Bearish accumulation
    Falling OI = Positions closing (trend exhaustion)
    
    Primary: CoinGlass API v4 /api/futures/openInterest/exchange-list
    Fallback: Binance Futures API
    """
    results = {}
    
    for symbol in SYMBOLS:
        data = coinglass_get("/api/futures/open-interest/exchange-list", {"symbol": symbol})
        if data and 'data' in data:
            for item in data.get('data', []):
                if item.get('exchange') == 'All':
                    oi = float(item.get('open_interest_usd', 0) or 0)
                    oi_24h = float(item.get('open_interest_change_percent_24h', 0) or 0)
                    oi_1h = float(item.get('open_interest_change_percent_1h', 0) or 0)
                    
                    oi_signal = 0
                    if oi_1h > 2:
                        oi_signal = 1
                    elif oi_1h < -2:
                        oi_signal = -1
                    
                    results[symbol] = {
                        'open_interest': oi,
                        'oi_change_24h': oi_24h,
                        'oi_change_1h': oi_1h,
                        'oi_signal': oi_signal,
                        'source': 'coinglass'
                    }
                    break
    
    if not results:
        log("   CoinGlass OI failed, trying Binance fallback...")
        results = _get_binance_open_interest()
    
    with open(OI_CACHE, 'w') as f:
        json.dump({'ts': datetime.utcnow().isoformat() + 'Z', 'oi': results}, f, indent=2)
    
    return results


def get_enhanced_signal(symbol: str) -> Optional[Dict]:
    """
    Get enhanced signal combining all intelligence sources.
    Includes: taker flow, liquidations, fear & greed, funding rate, OI delta
    """
    base_signal = get_signal(symbol)
    if not base_signal:
        return None
    
    try:
        with open(FUNDING_CACHE) as f:
            funding_data = json.load(f).get('rates', {})
    except:
        funding_data = {}
    
    try:
        with open(OI_CACHE) as f:
            oi_data = json.load(f).get('oi', {})
    except:
        oi_data = {}
    
    sym = symbol.replace('USDT', '')
    funding = funding_data.get(sym, {})
    oi = oi_data.get(sym, {})
    
    funding_signal = funding.get('funding_signal', 0)
    oi_signal = oi.get('oi_signal', 0)
    
    base_composite = base_signal.get('composite', 0)
    enhanced_composite = (
        base_composite * 0.6 +
        funding_signal * 0.2 +
        oi_signal * 0.2
    )
    
    if enhanced_composite >= 0.3:
        direction = "LONG"
    elif enhanced_composite <= -0.3:
        direction = "SHORT"
    else:
        direction = "NEUTRAL"
    
    return {
        'direction': direction,
        'confidence': min(abs(enhanced_composite), 1.0),
        'enhanced_composite': round(enhanced_composite, 3),
        'base_composite': base_composite,
        'funding_signal': funding_signal,
        'oi_signal': oi_signal,
        'funding_rate': funding.get('funding_rate', 0),
        'oi_change_1h': oi.get('oi_change_1h', 0),
    }


def poll_enhanced_intelligence():
    """Poll all CoinGlass data including funding and OI, and persist enhanced summary."""
    log("=" * 60)
    log("Enhanced Intelligence Poll (Funding + OI)")
    log("=" * 60)
    
    log("Fetching Funding Rates...")
    try:
        funding = get_funding_rates()
        log(f"   Got {len(funding)} funding rates")
    except Exception as e:
        log(f"   Funding rate error: {e}")
        funding = {}
    
    log("Fetching Open Interest...")
    try:
        oi = get_open_interest_delta()
        log(f"   Got {len(oi)} OI readings")
    except Exception as e:
        log(f"   OI error: {e}")
        oi = {}
    
    poll_intelligence()
    
    try:
        summary_file = FEATURE_DIR / "summary.json"
        with open(summary_file) as f:
            summary = json.load(f)
        
        for symbol_key in summary.get('signals', {}):
            sym = symbol_key.replace('USDT', '')
            enhanced = get_enhanced_signal(symbol_key)
            if enhanced:
                summary['signals'][symbol_key]['enhanced'] = enhanced
                summary['signals'][symbol_key]['funding'] = funding.get(sym, {})
                summary['signals'][symbol_key]['oi'] = oi.get(sym, {})
        
        summary['funding_rates'] = funding
        summary['open_interest'] = oi
        summary['enhanced_ts'] = datetime.utcnow().isoformat() + 'Z'
        
        with open(summary_file, 'w') as f:
            json.dump(summary, f, indent=2)
        
        log("✅ Enhanced data persisted to summary.json")
    except Exception as e:
        log(f"⚠️ Error persisting enhanced data: {e}")
    
    return funding, oi


def main():
    """Run continuous intelligence polling."""
    log("Starting Market Intelligence System")
    log(f"Symbols: {SYMBOLS}")
    log(f"API Key: {'configured' if COINGLASS_API_KEY else 'NOT CONFIGURED'}")
    
    if not COINGLASS_API_KEY:
        log("ERROR: COINGLASS_API_KEY not set")
        return
    
    while True:
        try:
            poll_intelligence()
        except Exception as e:
            log(f"Poll error: {e}")
            import traceback
            traceback.print_exc()
        
        log("Sleeping 60 seconds...")
        time.sleep(60)


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "--once":
        poll_intelligence()
    else:
        main()
