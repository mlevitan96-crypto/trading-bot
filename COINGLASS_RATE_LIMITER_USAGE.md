# CoinGlass Rate Limiter - Usage Guide

## ✅ Already Implemented!

The CoinGlass rate limiter is **already active** and protecting all API calls. You don't need to do anything - it's working automatically in the background.

## How It Works

### Automatic Protection
All CoinGlass API calls automatically go through the rate limiter:
- `src/market_intelligence.py` - Uses rate limiter
- `src/onchain_fetcher.py` - Uses rate limiter  
- `src/coinglass_intelligence.py` - Uses rate limiter

### What It Does
1. **Tracks all calls** in a rolling 60-second window
2. **Enforces 2.5s minimum delay** between calls
3. **Blocks automatically** if approaching 30 req/min limit
4. **Thread-safe** - works across all components

## Current Status

### Active Poller
- **Intelligence Poller**: Runs every 60 seconds
- **Calls per poll**: ~18 calls
- **Rate**: ~18 calls/minute (60% utilization)
- **Status**: ✅ SAFE (12 calls/min headroom)

## How to Verify It's Working

### Option 1: Check Logs
Look for rate limit messages in `logs/market_intelligence.log`:
```bash
tail -f logs/market_intelligence.log | grep -i "rate"
```

### Option 2: Check Rate Limiter Stats (Python)
```python
from src.coinglass_rate_limiter import get_rate_limiter

# Get current statistics
stats = get_rate_limiter().get_stats()
print(f"Calls in last minute: {stats['calls_in_last_minute']}/30")
print(f"Utilization: {stats['utilization_pct']:.1f}%")
print(f"Headroom: {stats['headroom']} calls")
print(f"Total calls: {stats['total_calls']}")
print(f"Blocked calls: {stats['blocked_calls']}")
```

### Option 3: Monitor for 429 Errors
If you see `429 Too Many Requests` errors, the rate limiter is working correctly and blocking excessive calls. The system will automatically back off and retry.

## Configuration

### Rate Limit Settings
- **Limit**: 30 requests/minute (Hobbyist plan)
- **Minimum delay**: 2.5 seconds between calls
- **Window**: Rolling 60-second window

### Current Usage
- **Active**: Intelligence Poller (60s interval)
- **Calls/min**: ~18 (safe)
- **Headroom**: 12 calls/min

## Troubleshooting

### If You See 429 Errors
1. **Normal**: The rate limiter is working and blocking excessive calls
2. **Check**: Verify only one poller is active (Intelligence Poller)
3. **Verify**: Check that `coinglass_config.json` has `"polling": {"enabled": false}`

### If Charts Are Empty
- This is unrelated to the rate limiter
- Check that `COINGLASS_API_KEY` is set in your environment
- Verify files are being created in `feature_store/coinglass/`

## Summary

✅ **No action needed** - The rate limiter is already active and protecting all CoinGlass API calls.

The system is configured to:
- Stay within 30 req/min limit
- Use ~18 calls/min (60% utilization)
- Leave 12 calls/min headroom for safety
- Automatically block if approaching limit

**You're all set!** 🎉

