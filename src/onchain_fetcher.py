"""
ON-CHAIN FETCHER - Whale Alerts & Exchange Flows
=================================================
Fetches on-chain data from free sources:
1. Whale Alert API (free tier - 10 calls/min)
2. CryptoQuant (limited free access)
3. Glassnode (very limited free)

Key Signals:
- Large exchange inflows = potential selling (bearish)
- Large exchange outflows = accumulation (bullish)
- Whale movements = follow the smart money

Data Flow:
- Polls every 10 minutes
- Caches to feature_store/onchain/
- realtime_features.py reads cached data at entry time

Reference: Following pattern from market_intelligence.py
"""

import os
import json
import time
import requests
from pathlib import Path
from datetime import datetime, timedelta
from typing import Dict, Any, Optional, List

from src.data_registry import DataRegistry as DR

ONCHAIN_DIR = Path(DR.ONCHAIN_DIR)
WHALE_CACHE = Path(DR.ONCHAIN_WHALE_CACHE)
FLOWS_CACHE = Path(DR.ONCHAIN_FLOWS_CACHE)
LOG_FILE = Path("logs/onchain_fetcher.log")

ONCHAIN_DIR.mkdir(parents=True, exist_ok=True)
LOG_FILE.parent.mkdir(parents=True, exist_ok=True)

WHALE_ALERT_API_KEY = os.environ.get('WHALE_ALERT_API_KEY', '')

SYMBOLS = ['BTC', 'ETH', 'SOL', 'BNB', 'XRP', 'ADA', 'DOGE', 'DOT', 'AVAX', 'MATIC', 'TRX', 'LINK', 'ARB', 'OP', 'PEPE']

EXCHANGE_ADDRESSES = {
    'binance': ['bc1qm34lsc65zpw79lxes69zkqmk6ee3ewf0j77s3h'],
    'coinbase': ['bc1qxy2kgdygjrsqtzq2n0yrf2493p83kkfjhx0wlh'],
    'kraken': ['bc1qr4dl5wa7kl8yu792dceg9z5knl2gkn220lk7a9']
}


def log(msg: str):
    ts = datetime.utcnow().isoformat() + "Z"
    entry = f"[{ts}] {msg}"
    print(entry)
    try:
        with open(LOG_FILE, 'a') as f:
            f.write(entry + '\n')
    except:
        pass


def get_whale_transactions(min_usd: int = 1000000) -> List[Dict]:
    """
    Get recent whale transactions from Whale Alert API.
    
    Free tier: 10 requests/minute, last 1 hour of data
    
    Args:
        min_usd: Minimum transaction value in USD
    
    Returns:
        List of whale transactions
    """
    if not WHALE_ALERT_API_KEY:
        return _get_simulated_whale_data()
    
    try:
        now = int(time.time())
        start = now - 3600
        
        url = f"https://api.whale-alert.io/v1/transactions"
        params = {
            'api_key': WHALE_ALERT_API_KEY,
            'min_value': min_usd,
            'start': start,
            'cursor': ''
        }
        
        resp = requests.get(url, params=params, timeout=15)
        if resp.status_code == 200:
            data = resp.json()
            transactions = data.get('transactions', [])
            
            parsed = []
            for tx in transactions:
                symbol = tx.get('symbol', '').upper()
                if symbol not in SYMBOLS:
                    continue
                
                from_owner = tx.get('from', {}).get('owner_type', 'unknown')
                to_owner = tx.get('to', {}).get('owner_type', 'unknown')
                
                flow_type = 'neutral'
                if to_owner == 'exchange' and from_owner != 'exchange':
                    flow_type = 'exchange_inflow'
                elif from_owner == 'exchange' and to_owner != 'exchange':
                    flow_type = 'exchange_outflow'
                elif from_owner == 'exchange' and to_owner == 'exchange':
                    flow_type = 'exchange_transfer'
                
                parsed.append({
                    'symbol': symbol,
                    'amount_usd': tx.get('amount_usd', 0),
                    'flow_type': flow_type,
                    'from_type': from_owner,
                    'to_type': to_owner,
                    'timestamp': tx.get('timestamp', now)
                })
            
            return parsed
    except Exception as e:
        log(f"Whale Alert API error: {e}")
    
    return _get_simulated_whale_data()


_last_coinglass_call = 0.0
COINGLASS_RATE_LIMIT_DELAY = 2.5  # Hobbyist plan: 30 req/min

def _coinglass_rate_limit():
    """Enforce CoinGlass Hobbyist rate limit."""
    global _last_coinglass_call
    elapsed = time.time() - _last_coinglass_call
    if elapsed < COINGLASS_RATE_LIMIT_DELAY:
        time.sleep(COINGLASS_RATE_LIMIT_DELAY - elapsed)
    _last_coinglass_call = time.time()


def _get_coinglass_exchange_flows() -> List[Dict]:
    """
    Get exchange flow data from CoinGlass Exchange Balance API.
    
    Endpoint: /api/exchange/balance/list
    - balance_change_1d: 24h balance change (positive = inflow, negative = outflow)
    - balance_change_percent_1d: Percentage change
    
    Large inflows (positive) = bearish (selling pressure incoming)
    Large outflows (negative) = bullish (accumulation)
    """
    api_key = os.environ.get('COINGLASS_API_KEY', '')
    if not api_key:
        log("   No COINGLASS_API_KEY - using neutral fallback for whale data")
        return _get_neutral_fallback_data()
    
    now = int(time.time())
    transactions = []
    
    for symbol in ['BTC', 'ETH', 'SOL']:
        try:
            _coinglass_rate_limit()  # Rate limit before each call
            resp = requests.get(
                "https://open-api-v4.coinglass.com/api/exchange/balance/list",
                params={"symbol": symbol},
                headers={
                    "accept": "application/json",
                    "CG-API-KEY": api_key
                },
                timeout=10
            )
            
            if resp.status_code == 200:
                data = resp.json()
                if data.get('code') == '0' and 'data' in data:
                    total_change = 0
                    for exchange in data['data']:
                        change = float(exchange.get('balance_change_1d', 0) or 0)
                        total_change += change
                    
                    if abs(total_change) > 0:
                        flow_type = 'exchange_inflow' if total_change > 0 else 'exchange_outflow'
                        price_estimate = 97000 if symbol == 'BTC' else (3600 if symbol == 'ETH' else 200)
                        amount_usd = abs(total_change) * price_estimate
                        
                        transactions.append({
                            'symbol': symbol,
                            'amount_usd': amount_usd,
                            'flow_type': flow_type,
                            'from_type': 'exchange' if total_change < 0 else 'unknown',
                            'to_type': 'exchange' if total_change > 0 else 'unknown',
                            'timestamp': now,
                            'balance_change': total_change,
                            'source': 'coinglass'
                        })
                        log(f"   CoinGlass {symbol} exchange flow: {total_change:+.2f} ({flow_type})")
        except Exception as e:
            log(f"   CoinGlass exchange balance error for {symbol}: {e}")
    
    if transactions:
        return transactions
    
    log("   CoinGlass exchange balance returned no data - using neutral fallback")
    return _get_neutral_fallback_data()


def _get_neutral_fallback_data() -> List[Dict]:
    """
    Return neutral fallback data when no API sources are available.
    This ensures the system doesn't crash but signals are marked as unavailable.
    """
    now = int(time.time())
    return [
        {
            'symbol': 'BTC',
            'amount_usd': 0,
            'flow_type': 'neutral',
            'from_type': 'unknown',
            'to_type': 'unknown',
            'timestamp': now,
            'is_fallback': True,
            'source': 'none'
        }
    ]


def _get_simulated_whale_data() -> List[Dict]:
    """
    Try CoinGlass exchange balance API first, then fall back to neutral data.
    """
    log("   No WHALE_ALERT_API_KEY - trying CoinGlass exchange balance API...")
    return _get_coinglass_exchange_flows()


def compute_exchange_flow_signal(transactions: List[Dict]) -> Dict[str, Dict]:
    """
    Compute exchange flow signals per symbol.
    
    Logic:
    - Net inflows > $10M in 1h = bearish (selling incoming)
    - Net outflows > $10M in 1h = bullish (accumulation)
    - Large whale moves = increased volatility expected
    
    Returns:
        Dict[symbol] -> {net_flow, signal, confidence}
    """
    flows_by_symbol = {}
    
    for tx in transactions:
        symbol = tx.get('symbol', 'BTC')
        if symbol not in flows_by_symbol:
            flows_by_symbol[symbol] = {'inflows': 0, 'outflows': 0, 'transfers': 0}
        
        amount = tx.get('amount_usd', 0)
        flow_type = tx.get('flow_type', 'neutral')
        
        if flow_type == 'exchange_inflow':
            flows_by_symbol[symbol]['inflows'] += amount
        elif flow_type == 'exchange_outflow':
            flows_by_symbol[symbol]['outflows'] += amount
        elif flow_type == 'exchange_transfer':
            flows_by_symbol[symbol]['transfers'] += amount
    
    signals = {}
    for symbol in SYMBOLS:
        flows = flows_by_symbol.get(symbol, {'inflows': 0, 'outflows': 0, 'transfers': 0})
        net_flow = flows['outflows'] - flows['inflows']
        
        signal = 0
        confidence = 0
        
        if abs(net_flow) > 10_000_000:
            signal = 1 if net_flow > 0 else -1
            confidence = min(1.0, abs(net_flow) / 50_000_000)
        elif abs(net_flow) > 1_000_000:
            signal = 1 if net_flow > 0 else -1
            confidence = 0.3
        
        signals[symbol] = {
            'net_flow_usd': net_flow,
            'inflows_usd': flows['inflows'],
            'outflows_usd': flows['outflows'],
            'signal': signal,
            'confidence': round(confidence, 2),
            'interpretation': 'bullish_accumulation' if signal > 0 else ('bearish_distribution' if signal < 0 else 'neutral')
        }
    
    return signals


def get_exchange_reserves_estimate(symbol: str) -> Dict[str, Any]:
    """
    Estimate exchange reserves direction.
    
    Note: Without paid API, we use flow data as proxy.
    Decreasing reserves = bullish (less available to sell)
    Increasing reserves = bearish (more available to sell)
    """
    return {
        'reserves_trend': 'unknown',
        'reserves_change_pct': 0,
        'signal': 0,
        'confidence': 0
    }


def poll_onchain() -> Dict[str, Any]:
    """
    Main polling function - fetches all on-chain data.
    Called every 10 minutes by scheduler.
    """
    log("============================================================")
    log("On-Chain Poll Starting...")
    log("============================================================")
    
    transactions = get_whale_transactions(min_usd=500000)
    log(f"Fetched {len(transactions)} whale transactions")
    
    flow_signals = compute_exchange_flow_signal(transactions)
    
    significant_flows = {k: v for k, v in flow_signals.items() if abs(v.get('signal', 0)) > 0}
    if significant_flows:
        log(f"Significant flows detected: {list(significant_flows.keys())}")
    
    result = {
        'whale_transactions': transactions[-50:],
        'flow_signals': flow_signals,
        'poll_timestamp': datetime.utcnow().isoformat() + 'Z',
        'has_api_key': bool(WHALE_ALERT_API_KEY)
    }
    
    try:
        with open(WHALE_CACHE, 'w') as f:
            json.dump({'transactions': transactions[-100:], 'timestamp': result['poll_timestamp']}, f, indent=2)
        
        with open(FLOWS_CACHE, 'w') as f:
            json.dump({'signals': flow_signals, 'timestamp': result['poll_timestamp']}, f, indent=2)
        
        log(f"Saved to {FLOWS_CACHE}")
    except Exception as e:
        log(f"Failed to save cache: {e}")
    
    log("On-Chain Poll Complete")
    return result


def get_cached_onchain() -> Dict[str, Any]:
    """
    Get cached on-chain data for realtime features.
    Returns empty dict with defaults if cache is stale or missing.
    """
    try:
        if FLOWS_CACHE.exists():
            with open(FLOWS_CACHE, 'r') as f:
                data = json.load(f)
            
            ts = data.get('timestamp', '')
            if ts:
                poll_time = datetime.fromisoformat(ts.replace('Z', ''))
                age_minutes = (datetime.utcnow() - poll_time).total_seconds() / 60
                
                if age_minutes < 60:
                    return data
    except Exception as e:
        log(f"Cache read error: {e}")
    
    return {
        'signals': {},
        'is_stale': True
    }


def get_onchain_features(symbol: str) -> Dict[str, float]:
    """
    Get on-chain features for a specific symbol.
    Called by realtime_features.py at entry time.
    
    Returns:
        Dict with normalized features ready for ML
    """
    cached = get_cached_onchain()
    
    base_symbol = symbol.replace('USDT', '')
    signal_data = cached.get('signals', {}).get(base_symbol, {})
    
    net_flow = signal_data.get('net_flow_usd', 0)
    flow_signal = signal_data.get('signal', 0)
    flow_confidence = signal_data.get('confidence', 0)
    
    normalized_flow = max(-1, min(1, net_flow / 50_000_000))
    
    return {
        'onchain_net_flow': normalized_flow,
        'onchain_flow_signal': flow_signal,
        'onchain_flow_confidence': flow_confidence,
        'onchain_inflows': signal_data.get('inflows_usd', 0) / 100_000_000,
        'onchain_outflows': signal_data.get('outflows_usd', 0) / 100_000_000,
        'onchain_is_stale': 1.0 if cached.get('is_stale', False) else 0.0
    }


if __name__ == "__main__":
    result = poll_onchain()
    print(json.dumps(result, indent=2))
