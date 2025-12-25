# Droplet Deployment Steps - Forensic Logging Enhancements

## Overview
This deployment adds comprehensive forensic execution data tracking:
- Slippage and execution latency calculation
- MFE/MAE tracking in volatility snapshots
- Enhanced IntelligenceGate logging (OFI ratio, bid-ask spread)
- Counterfactual trade tracking system
- Enhanced Golden Hour analysis

**No new dependencies required** - all changes are code-only and backward compatible.

---

## Step-by-Step Deployment Instructions

### Step 1: SSH into Droplet

```bash
ssh kraken
```

### Step 2: Navigate to Active Bot Directory

Based on memory bank, the bot runs from `/root/trading-bot-B`:

```bash
cd /root/trading-bot-B
```

**Verify you're in the right place:**
```bash
pwd
# Should show: /root/trading-bot-B
```

### Step 3: Activate Virtual Environment

```bash
source venv/bin/activate
```

You should see `(venv)` in your prompt.

### Step 4: Pull Latest Code

```bash
git pull origin main
```

**Expected output:**
```
remote: Enumerating objects: X, done.
remote: Counting objects: 100% (X/X), done.
...
Updating [commit]..[commit]
Fast-forward
 src/enhanced_trade_logging.py        | XX ++++++++----
 src/position_manager.py              | XX ++++++++++++
 src/intelligence_gate.py             | XX ++++++++++++
 src/counterfactual_tracker.py        | XXX ++++++++++++++++++++
 analyze_golden_hour_trades.py        | XX ++++++++++++
```

### Step 5: Verify New Files Exist

```bash
# Check new counterfactual tracker exists
ls -la src/counterfactual_tracker.py

# Verify enhanced logging was updated
grep -n "slippage_bps\|execution_latency_ms\|mfe_pct\|mae_pct" src/position_manager.py

# Verify IntelligenceGate enhancements
grep -n "ofi_ratio\|bid_ask_spread_bps" src/intelligence_gate.py
```

**Expected:** All files should exist and show the new code.

### Step 6: Check for Import Errors (Quick Test)

```bash
python3 -c "from src.counterfactual_tracker import log_blocked_signal; print('✅ Counterfactual tracker imports OK')"
python3 -c "from src.enhanced_trade_logging import create_volatility_snapshot; print('✅ Enhanced logging imports OK')"
python3 -c "from src.intelligence_gate import intelligence_gate; print('✅ IntelligenceGate imports OK')"
```

**Expected:** All should print success messages without errors.

### Step 7: Restart Trading Bot Service

```bash
sudo systemctl restart tradingbot
```

**Wait 5 seconds, then check status:**
```bash
sudo systemctl status tradingbot
```

**Expected output:**
```
● tradingbot.service - Trading Bot
   Loaded: loaded (/etc/systemd/system/tradingbot.service; enabled)
   Active: active (running) since [timestamp]
```

### Step 8: Verify Service Started Successfully

```bash
# Check logs for startup
journalctl -u tradingbot --since "1 minute ago" | tail -20
```

**Look for:**
- No Python import errors
- Bot cycle starting normally
- No tracebacks or exceptions

### Step 9: Monitor Enhanced Logging (Optional - Wait for Next Trade)

After the next trade opens, check for enhanced logging:

```bash
# Watch for enhanced logging messages
journalctl -u tradingbot -f | grep -E "ENHANCED-LOGGING|INTEL-CONFIRM|INTEL-REDUCE"
```

**Expected when a trade opens:**
```
✅ [ENHANCED-LOGGING] Captured volatility snapshot for BTCUSDT: ATR=X.XX, Regime=XXX
✅ INTEL-CONFIRM BTCUSDT: Signal=LONG aligns with Intel=LONG (conf=X.XX, mult=X.XX, OFI=X.XX, Spread=X.Xbps)
```

### Step 10: Verify Counterfactual Log Directory

```bash
# Check that counterfactual log directory exists
ls -la logs/counterfactual_trades.jsonl 2>/dev/null || echo "File will be created when first blocked signal is logged"
```

**Expected:** Either file exists or message that it will be created (this is normal - file is created on first use).

---

## Verification Checklist

After deployment, verify:

- [x] Code pulled successfully
- [x] New files exist (`src/counterfactual_tracker.py`)
- [x] No import errors
- [x] Service restarted and running
- [x] No errors in logs
- [x] Enhanced logging will activate on next trade

---

## Testing the New Features

### Test 1: Enhanced Logging (Automatic)
- **When:** Next trade opens
- **What to check:** `journalctl -u tradingbot | grep "ENHANCED-LOGGING"`
- **Expected:** Snapshot captured with ATR, regime, bid-ask spread

### Test 2: Slippage & Latency (Automatic)
- **When:** Next trade closes
- **What to check:** Check closed position in `logs/positions_futures.json`
- **Expected:** `slippage_bps` and `execution_latency_ms` fields present

### Test 3: MFE/MAE (Automatic)
- **When:** Next trade closes
- **What to check:** Check `volatility_snapshot` in closed position
- **Expected:** `mfe_pct`, `mae_pct`, `mfe_price`, `mae_price` fields present

### Test 4: IntelligenceGate Logging (Automatic)
- **When:** Next signal evaluated
- **What to check:** `journalctl -u tradingbot | grep "INTEL"`
- **Expected:** OFI ratio and bid-ask spread in log messages

### Test 5: Counterfactual Tracking (Manual Integration)
- **When:** After integrating into gates (if desired)
- **What to check:** `logs/counterfactual_trades.jsonl`
- **Expected:** Blocked signals logged with theoretical P&L

---

## Rollback (If Needed)

If something goes wrong:

```bash
# Stop service
sudo systemctl stop tradingbot

# Revert to previous commit
cd /root/trading-bot-B
git reset --hard HEAD~1

# Restart service
sudo systemctl start tradingbot
```

---

## Troubleshooting

### Import Error: No module named 'counterfactual_tracker'
**Solution:** Make sure you're in `/root/trading-bot-B` and virtual environment is activated.

### Service won't start
**Check logs:**
```bash
journalctl -u tradingbot -n 50
```

**Common issues:**
- Python syntax error → Check git pull completed successfully
- Missing dependency → Run `pip install -r requirements.txt` (shouldn't be needed)
- Path issues → Verify you're in `/root/trading-bot-B`

### Enhanced logging not appearing
**Wait for next trade** - logging only activates when positions open.

**Check if it's working:**
```bash
# Check if volatility snapshots are being created
python3 -c "
import json
from pathlib import Path
data = json.load(open('logs/positions_futures.json'))
open_pos = data.get('open_positions', [])
if open_pos:
    pos = open_pos[0]
    if 'volatility_snapshot' in pos:
        print('✅ Enhanced logging is working')
        print(f'   Snapshot keys: {list(pos[\"volatility_snapshot\"].keys())}')
    else:
        print('⚠️  No snapshot found in open positions')
else:
    print('ℹ️  No open positions - wait for next trade')
"
```

---

## Summary

✅ **Deployment is complete when:**
1. Code pulled successfully
2. Service restarted without errors
3. No import errors in logs
4. Enhanced logging will activate automatically on next trade

**No manual configuration needed** - all features activate automatically!

---

## Next Steps (Optional)

1. **Integrate counterfactual tracking** into Fee Gate/Conviction Gate if you want to track blocked signals
2. **Run golden hour analysis** after some trades accumulate:
   ```bash
   cd /root/trading-bot-B
   source venv/bin/activate
   python3 analyze_golden_hour_trades.py
   ```
3. **Monitor enhanced logging** in real-time to verify it's working

---

**Questions?** Check logs: `journalctl -u tradingbot -f`

