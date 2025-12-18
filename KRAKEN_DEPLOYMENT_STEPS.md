# Kraken Integration: Deployment Steps (On Droplet)

## Current Situation
You're already SSH'd into the droplet. The new Kraken code needs to be deployed before you can add API keys.

---

## Step 1: Deploy New Kraken Code

**The code is already in git**, so deploy it:

```bash
# Use the deployment script (handles A/B slot switching)
/root/trading-bot-tools/deploy.sh
```

**What this does:**
- Pulls latest code from git (includes new Kraken files)
- Installs any new dependencies
- Switches to the updated slot
- Restarts the bot

**Expected output:**
```
Deploying to slot B...
Pulling latest code...
Installing dependencies...
Switching to slot B...
Restarting service...
✅ Deployment complete
```

---

## Step 2: Verify Kraken Files Are Deployed

```bash
# Check if Kraken client exists
ls -la /root/trading-bot-current/src/kraken_futures_client.py

# Check exchange gateway
grep -i "kraken" /root/trading-bot-current/src/exchange_gateway.py | head -5

# Verify files exist
ls -la /root/trading-bot-current/src/kraken_rate_limiter.py
ls -la /root/trading-bot-current/src/exchange_utils.py
```

**Expected:** All files should exist and show file info.

---

## Step 3: Add API Keys to .env

Now that the code is deployed, add your API keys:

```bash
cd /root/trading-bot-current

# Edit .env file
nano .env
```

**Add these lines** (at the end of the file):
```bash
# Exchange Selection
EXCHANGE=kraken

# Kraken Futures API
KRAKEN_FUTURES_API_KEY=F60MLXJWKHf3Ft3t9TBLSxszee1Ba35hXf9s8EyAhxZ1xcX24Z43fucT
KRAKEN_FUTURES_API_SECRET=tgCd/39CS9ckc6Z2x3toH8iMFdRNxKUSCY6u4auNVEJN5mj/WUU2mosYFHGvQVd7VKWsK0Y4NUN2tud15CaNJg==
KRAKEN_FUTURES_TESTNET=true
```

**Save:** `Ctrl+O`, `Enter`, `Ctrl+X`

---

## Step 4: Verify .env File

```bash
# Check keys were added (without showing full secret)
grep KRAKEN .env

# Should show:
# EXCHANGE=kraken
# KRAKEN_FUTURES_API_KEY=F60MLXJWKHf3Ft3t9TBLSxszee1Ba35hXf9s8EyAhxZ1xcX24Z43fucT
# KRAKEN_FUTURES_API_SECRET=tgCd/39CS9ckc6Z2x3toH8iMFdRNxKUSCY6u4auNVEJN5mj/WUU2mosYFHGvQVd7VKWsK0Y4NUN2tud15CaNJg==
# KRAKEN_FUTURES_TESTNET=true
```

---

## Step 5: Test Connection

**IMPORTANT:** Use the venv's Python, not system python3:

```bash
cd /root/trading-bot-current

# Method 1: Use venv Python directly (recommended)
/root/trading-bot-current/venv/bin/python src/kraken_futures_client.py

# Method 2: Activate venv first (alternative)
source venv/bin/activate
python src/kraken_futures_client.py
deactivate  # When done
```

**If you get "ModuleNotFoundError: No module named 'pandas'"**:
```bash
# Make sure dependencies are installed in venv
cd /root/trading-bot-current
source venv/bin/activate
pip install -r requirements.txt
deactivate

# Then test again
/root/trading-bot-current/venv/bin/python src/kraken_futures_client.py
```

**Expected output:**
```
════════════════════════════════════════════════════════════
🔍 Testing Kraken Futures API Connectivity
════════════════════════════════════════════════════════════
📍 Mode: paper
🌐 Base URL: https://demo-futures.kraken.com
════════════════════════════════════════════════════════════

1️⃣ Testing mark price (symbol normalization)...
   ✅ BTCUSDT mark price: $XX,XXX.XX

2️⃣ Testing authenticated endpoint (account balance)...
   ✅ Account balance retrieved: {...}
```

---

## Step 6: Restart Bot to Use Kraken

```bash
# Restart bot service
sudo systemctl restart tradingbot

# Check status
sudo systemctl status tradingbot

# Verify it's using Kraken
journalctl -u tradingbot -n 50 --no-pager | grep -i "exchange\|kraken"
```

**Look for:**
```
✅ ExchangeGateway initialized with exchange: KRAKEN
```

---

## Step 7: Verify Exchange Selection

```bash
# Test exchange gateway directly
cd /root/trading-bot-current
python3 << 'EOF'
import os
os.chdir('/root/trading-bot-current')
from src.exchange_gateway import ExchangeGateway
gw = ExchangeGateway()
print(f"✅ Exchange: {gw.exchange.upper()}")
print(f"✅ Futures client: {type(gw.fut).__name__}")
EOF
```

**Expected:**
```
✅ Exchange: KRAKEN
✅ Futures client: KrakenFuturesClient
```

---

## Troubleshooting

### Error: "python3: can't open file... kraken_futures_client.py"

**Problem:** Code hasn't been deployed yet.

**Solution:** Run deploy script first:
```bash
/root/trading-bot-tools/deploy.sh
```

### Error: "No such file or directory: deploy.sh"

**Manual deployment:**
```bash
# Find which slot is active
ls -la /root/trading-bot-current

# Determine inactive slot
ACTIVE=$(readlink -f /root/trading-bot-current)
if [[ "$ACTIVE" == "/root/trading-bot-A" ]]; then
    INACTIVE="/root/trading-bot-B"
else
    INACTIVE="/root/trading-bot-A"
fi

# Pull latest code
cd "$INACTIVE"
git pull origin main

# Switch slots
sudo systemctl stop tradingbot
ln -sfn "$INACTIVE" /root/trading-bot-current
sudo systemctl start tradingbot
```

### Error: "Authentication failed"

- Check no spaces around `=` signs in .env
- Verify API secret doesn't have leading spaces
- Check API keys are correct

### Bot still using Blofin

- Check `.env` has `EXCHANGE=kraken`
- Restart bot: `sudo systemctl restart tradingbot`
- Check logs: `journalctl -u tradingbot -n 50 | grep exchange`

---

## Quick Command Summary

**Run these commands in order:**

```bash
# 1. Deploy new code
/root/trading-bot-tools/deploy.sh

# 2. Add API keys to .env
cd /root/trading-bot-current
nano .env
# (Add the 4 lines shown above, save with Ctrl+O, Ctrl+X)

# 3. Test connection
python3 src/kraken_futures_client.py

# 4. Restart bot
sudo systemctl restart tradingbot

# 5. Verify
journalctl -u tradingbot -n 50 | grep -i "exchange\|kraken"
```

---

## What to Expect

After deployment and restart:
- ✅ Bot loads Kraken client instead of Blofin
- ✅ Logs show "ExchangeGateway initialized with exchange: KRAKEN"
- ✅ Market data comes from Kraken testnet
- ✅ Orders go to Kraken (testnet)
- ✅ Dashboard shows Kraken as active exchange
