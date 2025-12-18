# Step-by-Step: Adding Kraken API Keys

## Your API Keys
```
EXCHANGE=kraken
KRAKEN_FUTURES_API_KEY=F60MLXJWKHf3Ft3t9TBLSxszee1Ba35hXf9s8EyAhxZ1xcX24Z43fucT
KRAKEN_FUTURES_API_SECRET=tgCd/39CS9ckc6Z2x3toH8iMFdRNxKUSCY6u4auNVEJN5mj/WUU2mosYFHGvQVd7VKWsK0Y4NUN2tud15CaNJg==
KRAKEN_FUTURES_TESTNET=true
```

**Note:** Your API secret had a leading space - I've removed it above. Make sure there are NO spaces around the `=` sign.

---

## Step 1: Add to .env File on Local Machine (Windows)

### Method A: Manual Edit (Recommended)

1. **Open File Explorer** and navigate to:
   ```
   c:\Users\markl\OneDrive\Documents\Cursor\Kraken\trading-bot
   ```

2. **Open `.env` file** in Notepad, VS Code, or any text editor
   - If you don't see `.env`, enable "Show hidden files" in File Explorer
   - Or create a new file named `.env` (with the dot at the start)

3. **Add these lines** (append to existing content, or create new file):
   ```bash
   # Exchange Selection
   EXCHANGE=kraken
   
   # Kraken Futures API
   KRAKEN_FUTURES_API_KEY=F60MLXJWKHf3Ft3t9TBLSxszee1Ba35hXf9s8EyAhxZ1xcX24Z43fucT
   KRAKEN_FUTURES_API_SECRET=tgCd/39CS9ckc6Z2x3toH8iMFdRNxKUSCY6u4auNVEJN5mj/WUU2mosYFHGvQVd7VKWsK0Y4NUN2tud15CaNJg==
   KRAKEN_FUTURES_TESTNET=true
   ```

4. **Save the file** (Ctrl+S)

### Method B: Using PowerShell

```powershell
# Navigate to project directory
cd "c:\Users\markl\OneDrive\Documents\Cursor\Kraken\trading-bot"

# Check if .env exists, if not create it
if (-not (Test-Path .env)) {
    New-Item -ItemType File -Path .env
}

# Add Kraken configuration (append to file)
Add-Content -Path .env -Value ""
Add-Content -Path .env -Value "# Exchange Selection"
Add-Content -Path .env -Value "EXCHANGE=kraken"
Add-Content -Path .env -Value ""
Add-Content -Path .env -Value "# Kraken Futures API"
Add-Content -Path .env -Value "KRAKEN_FUTURES_API_KEY=F60MLXJWKHf3Ft3t9TBLSxszee1Ba35hXf9s8EyAhxZ1xcX24Z43fucT"
Add-Content -Path .env -Value "KRAKEN_FUTURES_API_SECRET=tgCd/39CS9ckc6Z2x3toH8iMFdRNxKUSCY6u4auNVEJN5mj/WUU2mosYFHGvQVd7VKWsK0Y4NUN2tud15CaNJg=="
Add-Content -Path .env -Value "KRAKEN_FUTURES_TESTNET=true"

# Verify it was added
Write-Host "`n✅ .env file updated. Contents:" -ForegroundColor Green
Get-Content .env | Select-String -Pattern "KRAKEN" -Context 0,0
```

---

## Step 2: Test Locally (Windows)

Open PowerShell and run:

```powershell
cd "c:\Users\markl\OneDrive\Documents\Cursor\Kraken\trading-bot"
python src/kraken_futures_client.py
```

**Expected Output:**
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

✅ Connectivity test complete!
```

**If you get errors:**
- Verify `.env` file exists and has the keys
- Check there are NO spaces around `=` signs
- Make sure API secret doesn't have leading/trailing spaces

---

## Step 3: Add to .env File on Droplet (Production)

### SSH into Your Droplet

```bash
ssh root@your-droplet-ip
# Replace with your actual droplet IP
```

### Navigate to Bot Directory

```bash
cd /root/trading-bot-current
# Or wherever your bot is deployed
```

### Edit .env File

**Option A: Using nano (easier)**
```bash
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

**Save and exit:**
- Press `Ctrl + O` (save)
- Press `Enter` (confirm)
- Press `Ctrl + X` (exit)

**Option B: Using echo (quick one-liner)**
```bash
cd /root/trading-bot-current

cat >> .env << 'EOF'

# Exchange Selection
EXCHANGE=kraken

# Kraken Futures API
KRAKEN_FUTURES_API_KEY=F60MLXJWKHf3Ft3t9TBLSxszee1Ba35hXf9s8EyAhxZ1xcX24Z43fucT
KRAKEN_FUTURES_API_SECRET=tgCd/39CS9ckc6Z2x3toH8iMFdRNxKUSCY6u4auNVEJN5mj/WUU2mosYFHGvQVd7VKWsK0Y4NUN2tud15CaNJg==
KRAKEN_FUTURES_TESTNET=true
EOF
```

---

## Step 4: Verify .env File on Droplet

```bash
# Check that keys were added (without showing full secret)
grep KRAKEN .env

# Or view the entire .env file
cat .env
```

**Expected output:**
```
EXCHANGE=kraken
KRAKEN_FUTURES_API_KEY=F60MLXJWKHf3Ft3t9TBLSxszee1Ba35hXf9s8EyAhxZ1xcX24Z43fucT
KRAKEN_FUTURES_API_SECRET=tgCd/39CS9ckc6Z2x3toH8iMFdRNxKUSCY6u4auNVEJN5mj/WUU2mosYFHGvQVd7VKWsK0Y4NUN2tud15CaNJg==
KRAKEN_FUTURES_TESTNET=true
```

---

## Step 5: Test Connection on Droplet

```bash
cd /root/trading-bot-current
python3 src/kraken_futures_client.py
```

**Expected output** (same as local test):
```
════════════════════════════════════════════════════════════
🔍 Testing Kraken Futures API Connectivity
════════════════════════════════════════════════════════════
📍 Mode: paper
🌐 Base URL: https://demo-futures.kraken.com
...
✅ Connectivity test complete!
```

---

## Step 6: Restart Bot Service

```bash
# Restart the bot to load new configuration
sudo systemctl restart tradingbot

# Check status
sudo systemctl status tradingbot

# View recent logs to verify Kraken is being used
journalctl -u tradingbot -n 50 --no-pager | grep -i "kraken\|exchange\|gateway"
```

**Look for:**
```
✅ ExchangeGateway initialized with exchange: KRAKEN
```

---

## Step 7: Verify Exchange Selection

```bash
# Check logs for exchange initialization
journalctl -u tradingbot -n 100 --no-pager | grep -i "exchange.*kraken\|ExchangeGateway"

# Or test manually
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

**Expected output:**
```
✅ Exchange: KRAKEN
✅ Futures client: KrakenFuturesClient
```

---

## Troubleshooting

### Error: "Authentication failed" or "Invalid API key"

**Check 1: Verify no extra spaces**
```bash
# On droplet, check for spaces around =
grep KRAKEN_FUTURES_API_SECRET .env | cat -A
# Should show: KRAKEN_FUTURES_API_SECRET=tgCd... (no spaces)
```

**Check 2: Verify API secret format**
- Should be base64-encoded (ends with `==`)
- No leading/trailing spaces
- No quotes around the value

**Fix:**
```bash
# Edit .env and ensure format is:
KRAKEN_FUTURES_API_SECRET=tgCd/39CS9ckc6Z2x3toH8iMFdRNxKUSCY6u4auNVEJN5mj/WUU2mosYFHGvQVd7VKWsK0Y4NUN2tud15CaNJg==
# NOT:
# KRAKEN_FUTURES_API_SECRET = tgCd...
# KRAKEN_FUTURES_API_SECRET="tgCd..."
# KRAKEN_FUTURES_API_SECRET= tgCd...  (space after =)
```

### Error: "Environment variable not found"

**Verify .env is being loaded:**
```bash
# Test if Python can read the variables
python3 << 'EOF'
import os
from pathlib import Path
from dotenv import load_dotenv

env_path = Path("/root/trading-bot-current/.env")
if env_path.exists():
    load_dotenv(env_path)
    key = os.getenv('KRAKEN_FUTURES_API_KEY')
    if key:
        print(f"✅ API Key found: {key[:20]}...")
    else:
        print("❌ API Key not found")
else:
    print(f"❌ .env file not found at {env_path}")
EOF
```

### Error: "IP not whitelisted"

If you enabled IP whitelisting in Kraken:
1. Get your server IP:
   ```bash
   curl ifconfig.me
   ```
2. Add that IP to Kraken API settings
3. Or temporarily disable IP whitelisting for testing

### Error: "Permission denied" or "Insufficient permissions"

**Verify API key permissions in Kraken:**
1. Log into https://futures.kraken.com
2. Go to Settings → API Keys
3. Check your API key has:
   - ✅ Query Funds
   - ✅ Query Open Orders & Trades
   - ✅ Create & Modify Orders
   - ✅ Access Futures Data

---

## Quick Command Reference

### Local (Windows PowerShell)
```powershell
# Test connection
cd "c:\Users\markl\OneDrive\Documents\Cursor\Kraken\trading-bot"
python src/kraken_futures_client.py

# View .env (be careful - shows secrets!)
Get-Content .env | Select-String -Pattern "KRAKEN"
```

### Droplet (Linux)
```bash
# Edit .env
cd /root/trading-bot-current
nano .env

# Test connection
python3 src/kraken_futures_client.py

# Restart bot
sudo systemctl restart tradingbot

# Check logs
journalctl -u tradingbot -f
```

---

## Security Checklist

- [x] API keys stored in `.env` file (not in code)
- [x] `.env` is in `.gitignore` (won't be committed)
- [x] Testnet mode enabled (`KRAKEN_FUTURES_TESTNET=true`)
- [ ] IP whitelisting configured (recommended for production)
- [ ] Keys only have trading permissions (no withdrawals)
- [ ] Production keys separate from testnet keys

---

## Next Steps After Configuration

1. **Test connectivity** on both local and droplet
2. **Verify bot uses Kraken** (check logs)
3. **Paper trade on testnet** for 1-2 weeks
4. **Monitor for errors** (authentication, rate limits)
5. **Switch to production** when ready:
   - Change `KRAKEN_FUTURES_TESTNET=false`
   - Use production API keys
   - Enable IP whitelisting

---

## Important Notes

### API Secret Format
Your API secret should be EXACTLY:
```
tgCd/39CS9ckc6Z2x3toH8iMFdRNxKUSCY6u4auNVEJN5mj/WUU2mosYFHGvQVd7VKWsK0Y4NUN2tud15CaNJg==
```
- No leading space (you had one initially - I removed it)
- No quotes around it
- No spaces around the `=` sign

### File Format
`.env` file format:
```bash
KEY=value
KEY2=value2
```
- No spaces around `=`
- No quotes needed (unless value has spaces)
- One key-value pair per line

### Bot Loads .env Automatically
The bot automatically loads `.env` from:
- Project root (where `run.py` is)
- Or `/root/trading-bot-current/.env` (fallback)

You don't need to manually load it - just ensure the file exists and has the keys.
