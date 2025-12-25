# 🚀 Kraken Integration - Simple Deployment Guide

## ✅ What's Ready
All the Kraken integration code is complete and tested. Everything is ready to deploy.

---

## 📋 Your Steps (Copy & Paste These Commands)

**Just follow these steps one at a time on your droplet:**

### Step 1: Connect to Your Droplet
```bash
ssh kraken
```

### Step 2: Deploy the New Code
```bash
cd /root/trading-bot-current
git pull origin main
```

### Step 3: Add Your Kraken API Keys
```bash
nano .env
```

**Add these 4 lines at the end of the file:**
```
EXCHANGE=kraken
KRAKEN_FUTURES_API_KEY=F60MLXJWKHf3Ft3t9TBLSxszee1Ba35hXf9s8EyAhxZ1xcX24Z43fucT
KRAKEN_FUTURES_API_SECRET=tgCd/39CS9ckc6Z2x3toH8iMFdRNxKUSCY6u4auNVEJN5mj/WUU2mosYFHGvQVd7VKWsK0Y4NUN2tud15CaNJg==
KRAKEN_FUTURES_TESTNET=true
```

**Save:** Press `Ctrl+O`, then `Enter`, then `Ctrl+X`

### Step 4: Test the Connection
```bash
/root/trading-bot-current/venv/bin/python src/kraken_futures_client.py
```

**What to expect:**
- ✅ Should see "Testing Kraken Futures API Connectivity"
- ✅ Should see BTC price (even if testnet shows weird prices, that's OK)
- ✅ Should see OHLCV test passing
- ❌ If you see errors, let me know

### Step 5: Restart the Bot
```bash
sudo systemctl restart tradingbot
```

### Step 6: Verify It's Working
```bash
journalctl -u tradingbot -n 50 --no-pager | grep -i "exchange\|kraken"
```

**Look for:**
```
✅ ExchangeGateway initialized with exchange: KRAKEN
```

---

## ✅ Done!

Your bot is now using Kraken testnet instead of Blofin.

**To check it's working:**
- Check the dashboard - it should show Kraken as the exchange
- Check logs for any errors: `journalctl -u tradingbot -f`

---

## ❓ Troubleshooting

**Problem: "git pull" says "Already up to date"**
- That's fine, code might already be there

**Problem: "No such file: .env"**
- Create it: `touch .env`
- Then edit it: `nano .env`

**Problem: Test fails with "404" or "Authentication failed"**
- Double-check your API keys have no spaces
- Make sure you saved the .env file correctly

**Problem: Bot won't start**
- Check logs: `journalctl -u tradingbot -n 100`
- Share the error message

---

## 🔄 Switching Back to Blofin (if needed)

If something goes wrong and you need to switch back:

```bash
nano .env
# Change this line:
EXCHANGE=blofin
# Save and restart
sudo systemctl restart tradingbot
```

---

## 📝 What Changed

The bot now:
- ✅ Uses Kraken Futures API instead of Blofin
- ✅ Connects to Kraken testnet (paper trading)
- ✅ All trading operations go through Kraken
- ✅ Market data comes from Kraken

**Note:** This is TESTNET mode. No real money trades until you change `KRAKEN_FUTURES_TESTNET=false`
