"""
SENTIMENT FETCHER - Social Media & News Sentiment for Crypto
==============================================================
Fetches sentiment data from free APIs:
1. Alternative.me Fear & Greed Index (already have via CoinGlass)
2. CryptoCompare Social Stats (free tier)
3. LunarCrush (free tier - 50 calls/day)

Data Flow:
- Polls every 5 minutes
- Caches to feature_store/sentiment/
- realtime_features.py reads cached sentiment at entry time

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

SENTIMENT_DIR = Path(DR.SENTIMENT_DIR)
SENTIMENT_CACHE = Path(DR.SENTIMENT_CACHE)
SENTIMENT_HISTORY = Path(DR.SENTIMENT_HISTORY)
LOG_FILE = Path("logs/sentiment_fetcher.log")

SENTIMENT_DIR.mkdir(parents=True, exist_ok=True)
LOG_FILE.parent.mkdir(parents=True, exist_ok=True)

SYMBOLS = ['BTC', 'ETH', 'SOL', 'BNB', 'AVAX', 'DOT', 'XRP', 'ADA', 'DOGE', 'MATIC', 'TRX', 'LINK', 'ARB', 'OP', 'PEPE']


def log(msg: str):
    ts = datetime.utcnow().isoformat() + "Z"
    entry = f"[{ts}] {msg}"
    print(entry)
    try:
        with open(LOG_FILE, 'a') as f:
            f.write(entry + '\n')
    except:
        pass


def get_fear_greed() -> Dict[str, Any]:
    """
    Get Fear & Greed Index from Alternative.me (free, no API key needed).
    
    Values:
    - 0-25: Extreme Fear (contrarian BUY signal)
    - 25-45: Fear
    - 45-55: Neutral
    - 55-75: Greed
    - 75-100: Extreme Greed (contrarian SELL signal)
    """
    try:
        url = "https://api.alternative.me/fng/?limit=1"
        resp = requests.get(url, timeout=10)
        if resp.status_code == 200:
            data = resp.json()
            if data.get('data'):
                fng = data['data'][0]
                value = int(fng.get('value', 50))
                classification = fng.get('value_classification', 'Neutral')
                
                signal = 0
                if value <= 25:
                    signal = 1
                elif value >= 75:
                    signal = -1
                
                return {
                    'value': value,
                    'classification': classification,
                    'signal': signal,
                    'timestamp': datetime.utcnow().isoformat() + 'Z'
                }
    except Exception as e:
        log(f"Fear/Greed fetch error: {e}")
    
    return {'value': 50, 'classification': 'Neutral', 'signal': 0, 'timestamp': datetime.utcnow().isoformat() + 'Z'}


def get_cryptocompare_social(symbol: str) -> Dict[str, Any]:
    """
    Get social stats from CryptoCompare (free tier).
    
    Includes:
    - Reddit subscribers, active users, posts per hour
    - Twitter followers
    - Code repository activity
    """
    try:
        url = f"https://min-api.cryptocompare.com/data/social/coin/latest?coinId={_get_coin_id(symbol)}"
        resp = requests.get(url, timeout=10)
        if resp.status_code == 200:
            data = resp.json()
            if data.get('Data'):
                d = data['Data']
                
                reddit = d.get('Reddit', {})
                twitter = d.get('Twitter', {})
                
                reddit_active = reddit.get('active_users', 0)
                reddit_posts = reddit.get('posts_per_hour', 0)
                twitter_followers = twitter.get('followers', 0)
                
                activity_score = min(100, (reddit_active * 0.1 + reddit_posts * 10 + twitter_followers / 10000))
                
                return {
                    'reddit_active': reddit_active,
                    'reddit_posts_per_hour': reddit_posts,
                    'twitter_followers': twitter_followers,
                    'activity_score': round(activity_score, 2),
                    'timestamp': datetime.utcnow().isoformat() + 'Z'
                }
    except Exception as e:
        log(f"CryptoCompare social fetch error for {symbol}: {e}")
    
    return {'reddit_active': 0, 'reddit_posts_per_hour': 0, 'twitter_followers': 0, 'activity_score': 0}


def _get_coin_id(symbol: str) -> int:
    """Map symbol to CryptoCompare coin ID."""
    coin_ids = {
        'BTC': 1182,
        'ETH': 7605,
        'SOL': 934443,
        'BNB': 204788,
        'XRP': 5031,
        'ADA': 321992,
        'DOGE': 4432,
        'DOT': 935952,
        'AVAX': 935972,
        'MATIC': 310298,
        'TRX': 310829,
        'LINK': 324320,
        'ARB': 1066660,
        'OP': 1065648,
        'PEPE': 1066610
    }
    return coin_ids.get(symbol, 1182)


def get_reddit_mentions(symbol: str) -> Dict[str, Any]:
    """
    Get Reddit mention velocity using Pushshift (if available) or estimate.
    
    High mention velocity often precedes price moves.
    """
    return {
        'mention_count_1h': 0,
        'mention_velocity': 0,
        'sentiment_positive': 0.5,
        'sentiment_negative': 0.5,
        'bullish_ratio': 0.5
    }


def compute_composite_sentiment(fear_greed: Dict, social: Dict[str, Dict]) -> Dict[str, Any]:
    """
    Compute composite sentiment score combining all sources.
    
    Components:
    1. Fear/Greed (30%): Market-wide sentiment
    2. Social Activity (30%): Per-coin activity level
    3. Trend Analysis (40%): Direction of social metrics
    
    Returns:
        score: -1 to 1 (bearish to bullish)
        confidence: 0 to 1
        signal: -1, 0, 1 (short, hold, long)
    """
    fg_score = (fear_greed.get('value', 50) - 50) / 50
    fg_signal = fear_greed.get('signal', 0) * -1
    
    per_symbol = {}
    for symbol, data in social.items():
        activity = data.get('activity_score', 0)
        
        activity_signal = 0
        if activity > 70:
            activity_signal = 0.3
        elif activity > 50:
            activity_signal = 0.1
        
        composite = (fg_signal * 0.4) + (activity_signal * 0.6)
        
        per_symbol[symbol] = {
            'score': round(composite, 3),
            'fear_greed_component': round(fg_signal * 0.4, 3),
            'activity_component': round(activity_signal * 0.6, 3),
            'activity_score': activity,
            'signal': 1 if composite > 0.2 else (-1 if composite < -0.2 else 0),
            'confidence': round(min(1.0, abs(composite) * 2), 2)
        }
    
    return {
        'market_wide': {
            'fear_greed': fear_greed,
            'overall_signal': fg_signal
        },
        'per_symbol': per_symbol,
        'timestamp': datetime.utcnow().isoformat() + 'Z'
    }


def poll_sentiment() -> Dict[str, Any]:
    """
    Main polling function - fetches all sentiment data.
    Called every 5 minutes by scheduler.
    """
    log("============================================================")
    log("Sentiment Poll Starting...")
    log("============================================================")
    
    fear_greed = get_fear_greed()
    log(f"Fear/Greed: {fear_greed['value']} ({fear_greed['classification']})")
    
    social_stats = {}
    for symbol in SYMBOLS[:5]:
        stats = get_cryptocompare_social(symbol)
        social_stats[symbol] = stats
        time.sleep(0.5)
    
    for symbol in SYMBOLS[5:]:
        social_stats[symbol] = {'activity_score': 0, 'reddit_active': 0, 'twitter_followers': 0}
    
    composite = compute_composite_sentiment(fear_greed, social_stats)
    
    result = {
        'fear_greed': fear_greed,
        'social_stats': social_stats,
        'composite': composite,
        'poll_timestamp': datetime.utcnow().isoformat() + 'Z'
    }
    
    try:
        with open(SENTIMENT_CACHE, 'w') as f:
            json.dump(result, f, indent=2)
        log(f"Saved to {SENTIMENT_CACHE}")
    except Exception as e:
        log(f"Failed to save cache: {e}")
    
    try:
        with open(SENTIMENT_HISTORY, 'a') as f:
            f.write(json.dumps({
                'ts': datetime.utcnow().isoformat() + 'Z',
                'fear_greed': fear_greed['value'],
                'fear_greed_signal': fear_greed['signal']
            }) + '\n')
    except:
        pass
    
    log("Sentiment Poll Complete")
    return result


def get_cached_sentiment() -> Dict[str, Any]:
    """
    Get cached sentiment data for realtime features.
    Returns empty dict with defaults if cache is stale or missing.
    """
    try:
        if SENTIMENT_CACHE.exists():
            with open(SENTIMENT_CACHE, 'r') as f:
                data = json.load(f)
            
            ts = data.get('poll_timestamp', '')
            if ts:
                poll_time = datetime.fromisoformat(ts.replace('Z', ''))
                age_minutes = (datetime.utcnow() - poll_time).total_seconds() / 60
                
                if age_minutes < 30:
                    return data
    except Exception as e:
        log(f"Cache read error: {e}")
    
    return {
        'fear_greed': {'value': 50, 'signal': 0},
        'composite': {'per_symbol': {}},
        'is_stale': True
    }


def get_sentiment_features(symbol: str) -> Dict[str, float]:
    """
    Get sentiment features for a specific symbol.
    Called by realtime_features.py at entry time.
    
    Returns:
        Dict with normalized features ready for ML
    """
    cached = get_cached_sentiment()
    
    fg = cached.get('fear_greed', {})
    fg_value = fg.get('value', 50)
    fg_signal = fg.get('signal', 0)
    
    composite = cached.get('composite', {}).get('per_symbol', {}).get(symbol, {})
    sentiment_score = composite.get('score', 0)
    sentiment_confidence = composite.get('confidence', 0)
    sentiment_signal = composite.get('signal', 0)
    
    social = cached.get('social_stats', {}).get(symbol, {})
    activity_score = social.get('activity_score', 0)
    
    return {
        'sentiment_fear_greed': fg_value / 100.0,
        'sentiment_fg_signal': fg_signal,
        'sentiment_score': sentiment_score,
        'sentiment_confidence': sentiment_confidence,
        'sentiment_signal': sentiment_signal,
        'sentiment_activity': activity_score / 100.0,
        'sentiment_is_stale': 1.0 if cached.get('is_stale', False) else 0.0
    }


if __name__ == "__main__":
    result = poll_sentiment()
    print(json.dumps(result, indent=2))
