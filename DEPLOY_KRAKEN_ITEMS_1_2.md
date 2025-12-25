# Deployment Steps: Kraken Items #1 & #2

## ✅ What's Being Deployed

- **Item #1:** Symbol Universe Validation
  - `src/venue_symbol_validator.py`
  - `src/venue_validation_scheduler.py`
  - Integration in `src/run.py`
  - Dashboard updates in `src/pnl_dashboard.py`

- **Item #2:** Contract Size & Tick Size Helper
  - `src/kraken_contract_specs.py`
  - `src/canonical_sizing_helper.py`
  - Integration in `src/kraken_futures_client.py`

## 📋 Pre-Deployment Status

✅ **All code is committed and pushed to GitHub**

You can verify:
```bash
# On your local machine (Windows)
cd "c:\Users\markl\OneDrive\Documents\Cursor\Kraken\trading-bot"
git log --oneline -5
```

You should see:
```
88d3b34f Integrate canonical sizing helper into Kraken place_order...
4b90bcc3 Implement Item #2: Contract Size & Tick Size...
dd7db76d Add venue symbol validation status to executive summary...
48e0ebb3 Implement Item #1: Symbol Universe Validation...
```

---

## 🚀 Deployment Steps (On Droplet)

### Step 1: SSH to Droplet

```bash
ssh kraken
```

### Step 2: Run Deployment Script

**This is the recommended method:**

```bash
/root/trading-bot-tools/deploy.sh
```

**What this does:**
1. ✅ Determines which slot is active (A or B)
2. ✅ Pulls latest code from GitHub into inactive slot
3. ✅ Creates/updates virtual environment
4. ✅ Installs any new dependencies
5. ✅ Runs health checks (if configured)
6. ✅ Stops tradingbot service
7. ✅ Switches symlink to updated slot
8. ✅ Starts tradingbot service

**Expected output:**
```
🔍 Determining active slot...
📦 Active slot: A
📦 Deploying to slot B...

🔍 Pulling latest code...
✅ Code pulled successfully

🔍 Setting up virtual environment...
✅ Virtual environment ready

🔍 Installing dependencies...
✅ Dependencies installed

🔍 Switching to slot B...
✅ Symlink updated

🔍 Restarting service...
✅ Service restarted

✅ Deployment complete! Active slot: B
```

---

### Step 3: Verify Deployment

**Check new files exist:**
```bash
# Venue validator files
ls -la /root/trading-bot-current/src/venue_symbol_validator.py
ls -la /root/trading-bot-current/src/venue_validation_scheduler.py

# Contract specs
ls -la /root/trading-bot-current/src/kraken_contract_specs.py
ls -la /root/trading-bot-current/src/canonical_sizing_helper.py

# Check integration
grep -n "venue_symbol_validator" /root/trading-bot-current/src/run.py | head -3
grep -n "canonical_sizing_helper" /root/trading-bot-current/src/kraken_futures_client.py | head -3
```

**Expected:** All files should exist and show file info.

---

### Step 4: Check Bot Status

```bash
# Check service is running
sudo systemctl status tradingbot

# Check logs for startup messages
journalctl -u tradingbot -n 100 --no-pager | grep -i "validation\|sizing\|kraken" | tail -20
```

**Look for:**
- ✅ `[VALIDATION] Running startup venue symbol validation...`
- ✅ `ExchangeGateway initialized with exchange: KRAKEN` (if EXCHANGE=kraken)
- ✅ No errors related to missing modules

---

### Step 5: Test Symbol Validation (Optional)

If you're using Kraken (`EXCHANGE=kraken` in `.env`), validation should run on startup.

**Check validation status:**
```bash
# Check validation status file
cat /root/trading-bot-current/feature_store/venue_symbol_status.json

# Or test manually
cd /root/trading-bot-current
/root/trading-bot-current/venv/bin/python -c "
from src.venue_symbol_validator import validate_venue_symbols
results = validate_venue_symbols(update_config=False)
print(f\"Valid: {results['summary']['valid']}/{results['summary']['total']}\")
"
```

---

## 🔄 Rollback (If Needed)

If something goes wrong:

```bash
# Quick rollback to previous slot
CURRENT=$(readlink -f /root/trading-bot-current)

if [[ "$CURRENT" == "/root/trading-bot-A" ]]; then
    sudo systemctl stop tradingbot
    ln -sfn /root/trading-bot-B /root/trading-bot-current
    sudo systemctl start tradingbot
    echo "✅ Rolled back to slot B"
else
    sudo systemctl stop tradingbot
    ln -sfn /root/trading-bot-A /root/trading-bot-current
    sudo systemctl start tradingbot
    echo "✅ Rolled back to slot A"
fi
```

---

## 🐛 Troubleshooting

### Error: "deploy.sh: No such file or directory"

**Manual deployment:**
```bash
# 1. Determine active slot
ACTIVE=$(readlink -f /root/trading-bot-current)
if [[ "$ACTIVE" == "/root/trading-bot-A" ]]; then
    INACTIVE="/root/trading-bot-B"
else
    INACTIVE="/root/trading-bot-A"
fi

# 2. Pull code
cd "$INACTIVE"
git pull origin main

# 3. Install deps
"$INACTIVE/venv/bin/pip" install -r "$INACTIVE/requirements.txt"

# 4. Switch
sudo systemctl stop tradingbot
ln -sfn "$INACTIVE" /root/trading-bot-current
sudo systemctl start tradingbot
```

### Error: "ModuleNotFoundError" after deployment

```bash
# Reinstall dependencies in venv
cd /root/trading-bot-current
source venv/bin/activate
pip install -r requirements.txt
deactivate
sudo systemctl restart tradingbot
```

### Bot not starting

```bash
# Check detailed logs
journalctl -u tradingbot -n 200 --no-pager

# Check for Python errors
cd /root/trading-bot-current
/root/trading-bot-current/venv/bin/python -c "import src.venue_symbol_validator"
/root/trading-bot-current/venv/bin/python -c "import src.canonical_sizing_helper"
```

---

## 📊 What Happens After Deployment

### Immediate Effects:
- ✅ Symbol validation runs on startup (if using Kraken)
- ✅ All orders automatically normalized to contract sizes and tick sizes
- ✅ Size adjustments logged to `logs/size_adjustments.jsonl`
- ✅ Validation status visible in dashboard executive summary

### Daily Operations:
- ✅ Symbol validation runs daily at 4 AM UTC
- ✅ Failed symbols automatically suppressed
- ✅ Validation results saved to `feature_store/venue_symbol_status.json`

---

## 🎯 Next Steps

After successful deployment:
1. **Monitor logs** for validation results (if using Kraken)
2. **Check dashboard** for validation status in executive summary
3. **Continue with Item #3** (Venue-Aware Learning State) when ready

---

## 📝 Quick Command Summary

```bash
# On droplet - run these in order:

# 1. Deploy
/root/trading-bot-tools/deploy.sh

# 2. Verify files
ls -la /root/trading-bot-current/src/venue_symbol_validator.py

# 3. Check status
sudo systemctl status tradingbot

# 4. Check logs
journalctl -u tradingbot -n 50 | grep -i "validation"
```
