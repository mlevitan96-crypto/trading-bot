# CoinGlass API Setup Guide

## Overview

CoinGlass provides market intelligence data (funding rates, open interest, liquidations, fear & greed index) that enriches trading signals.

**Current Status:** You have CoinGlass Hobbyist plan (~$18/month) but API key is not configured.

---

## Step 1: Get Your CoinGlass API Key

1. Log into your CoinGlass account
2. Navigate to API settings/dashboard
3. Generate or copy your API key

**API Key Format:** Usually a long string like `xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx`

---

## Step 2: Set API Key on Droplet

### Option A: Set in Systemd Service (Recommended)

Edit the systemd service file:

```bash
sudo systemctl edit tradingbot --full
```

Add to the `[Service]` section:

```ini
[Service]
Environment="COINGLASS_API_KEY=your-api-key-here"
```

Then reload and restart:

```bash
sudo systemctl daemon-reload
sudo systemctl restart tradingbot
```

### Option B: Set in Environment File

Create/edit environment file:

```bash
sudo nano /etc/tradingbot/env
```

Add:
```
COINGLASS_API_KEY=your-api-key-here
```

Then update systemd service to source this file:

```bash
sudo systemctl edit tradingbot --full
```

Add:
```ini
[Service]
EnvironmentFile=/etc/tradingbot/env
```

Reload and restart:
```bash
sudo systemctl daemon-reload
sudo systemctl restart tradingbot
```

### Option C: Set in .env file (if bot loads it)

Edit `.env` file in bot directory:

```bash
cd /root/trading-bot-current
nano .env
```

Add:
```
COINGLASS_API_KEY=your-api-key-here
```

**Note:** Only works if bot loads `.env` file at startup.

---

## Step 3: Verify API Key is Set

After restarting the bot:

```bash
# Check if bot process has the environment variable
sudo systemctl show tradingbot | grep COINGLASS

# Or check from within bot process
journalctl -u tradingbot -n 50 | grep -i "coinglass\|intel"
```

---

## Step 4: Verify CoinGlass Feed is Working

```bash
cd /root/trading-bot-current
python3 check_coinglass_feed.py
```

You should see:
- ✅ API key found
- ✅ Recent files in `feature_store/intelligence/`
- ✅ CoinGlass feed status: GREEN

**Wait 1-2 minutes** after restart for the intelligence poller to fetch data.

---

## How CoinGlass Works in the Bot

### Data Fetched Every 60 Seconds:
- **Taker Buy/Sell Volume** - Order flow pressure
- **Liquidations** - Forced selling/buying (cascade risk)
- **Fear & Greed Index** - Macro sentiment

### Where Data is Stored:
- `feature_store/intelligence/` - Main location
  - `{SYMBOL}USDT_intel.json` - Per-symbol intelligence
  - `summary.json` - Overall market summary
  - `funding_rates.json` - Funding rate data
  - `open_interest.json` - OI data

### How It's Used:
- Enriches trading signals with market microstructure
- Used by `intelligence_gate.py` for signal confirmation
- Helps identify high-confidence setups

---

## Rate Limits (Hobbyist Plan)

- **30 requests per minute**
- Bot uses **2.5 second delay** between calls
- Fetches data for top 8 symbols (stays under limit)

**If you hit rate limits:**
- Status will show yellow
- Bot will continue working (CoinGlass is optional)
- Data will be stale until rate limit resets

---

## Troubleshooting

### API Key Not Found After Setting
1. **Verify service restart:** `systemctl restart tradingbot`
2. **Check environment:** `systemctl show tradingbot | grep COINGLASS`
3. **Check bot logs:** `journalctl -u tradingbot -n 100 | grep -i "intel\|coinglass"`

### CoinGlass Feed Still Yellow After Setup
1. **Wait 2-3 minutes** - First fetch takes time
2. **Check logs:** `journalctl -u tradingbot | grep -i "intelligence\|coinglass"`
3. **Check files:** `ls -lh /root/trading-bot-current/feature_store/intelligence/`
4. **Run diagnostic:** `python3 check_coinglass_feed.py`

### Rate Limit Errors
- **Hobbyist plan:** 30 req/min limit
- Bot automatically respects this with 2.5s delays
- If still hitting limits, reduce symbols in `market_intelligence.py` (SYMBOLS list)

### Feed Shows Yellow But Has API Key
- **Normal behavior** - Yellow means data exists but > 1 hour old
- Check if intelligence poller is running: `journalctl -u tradingbot | grep "intelligence poller"`
- Feed will turn green once fresh data is fetched

---

## Status Meanings

- **🟢 GREEN:** CoinGlass feed is active, data fetched within last hour
- **🟡 YELLOW:** 
  - Data exists but > 1 hour old (normal if not trading)
  - OR no API key configured (optional feature)
- **🔴 RED:** Data > 24 hours old (feed may be broken)

**Note:** Yellow is acceptable - CoinGlass is optional and doesn't block trading.

---

## Files Modified for CoinGlass

- `src/market_intelligence.py` - Fetches CoinGlass data
- `src/intelligence_gate.py` - Uses CoinGlass data for signal filtering
- `src/healing_operator.py` - Monitors and heals CoinGlass feed
- `src/pnl_dashboard.py` - Displays CoinGlass feed status

---

## Next Steps After Setup

1. **Set API key** using one of the methods above
2. **Restart bot:** `systemctl restart tradingbot`
3. **Wait 2-3 minutes** for first fetch
4. **Verify:** Run `check_coinglass_feed.py`
5. **Monitor dashboard** - CoinGlass feed should turn green

---

## Quick Setup Command (If Using Systemd Edit)

```bash
# Edit service to add API key
sudo systemctl edit tradingbot --full

# Add this line in [Service] section:
# Environment="COINGLASS_API_KEY=your-actual-key-here"

# Save and exit, then:
sudo systemctl daemon-reload
sudo systemctl restart tradingbot

# Verify it's set
sudo systemctl show tradingbot | grep COINGLASS

# Check if feed is working (wait 2 min first)
cd /root/trading-bot-current
python3 check_coinglass_feed.py
```
