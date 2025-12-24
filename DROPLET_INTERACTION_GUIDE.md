# Droplet Interaction Guide
## How to Interact with Your Automatically Connected Droplet

Based on your automated connection setup, here's how to interact with the droplet for deployment and management.

---

## 🚀 Quick Deployment (Forensic Logging Updates)

Since you're automatically connected, you can run these commands directly:

### Step 1: Navigate to Active Directory

```bash
cd /root/trading-bot-B
```

**Note:** Based on memory bank, the bot runs from `/root/trading-bot-B` (not `/root/trading-bot-current`)

### Step 2: Activate Virtual Environment

```bash
source venv/bin/activate
```

You should see `(venv)` in your prompt.

### Step 3: Pull Latest Code

```bash
git pull origin main
```

**Expected output:**
```
remote: Enumerating objects: X, done.
...
Updating [commit]..[commit]
Fast-forward
 src/enhanced_trade_logging.py        | XX ++++++++----
 src/position_manager.py              | XX ++++++++++++
 src/intelligence_gate.py             | XX ++++++++++++
 src/counterfactual_tracker.py        | XXX ++++++++++++++++++++
 analyze_golden_hour_trades.py        | XX ++++++++++++
```

### Step 4: Verify New Files

```bash
# Check new counterfactual tracker exists
ls -la src/counterfactual_tracker.py

# Quick import test
python3 -c "from src.counterfactual_tracker import log_blocked_signal; print('✅ OK')"
```

### Step 5: Restart Service

```bash
sudo systemctl restart tradingbot
```

### Step 6: Verify Service Status

```bash
sudo systemctl status tradingbot
```

**Expected:** `Active: active (running)`

### Step 7: Check Logs (Optional)

```bash
journalctl -u tradingbot --since "1 minute ago" | tail -20
```

Look for no errors, normal startup messages.

---

## 📊 Automated Workflow Commands

### Generate and Push Reports (Best Practice)

Instead of manual copy/paste, use the automated workflow:

```bash
cd /root/trading-bot-B
source venv/bin/activate
git pull origin main  # Always pull first
python3 generate_and_push_reports.py
```

**What this does:**
- Generates `performance_summary_report.json` and `.md`
- Generates `EXTERNAL_REVIEW_SUMMARY.md`
- Generates `GOLDEN_HOUR_ANALYSIS.md` (with new profit factor and hold time metrics)
- Commits and pushes to GitHub automatically

**Then:** AI can analyze the full JSON files from GitHub instead of console snippets.

### Run Analysis Scripts

```bash
cd /root/trading-bot-B
source venv/bin/activate

# Today's performance
python3 analyze_today_performance.py

# Golden hour analysis (with new metrics)
python3 analyze_golden_hour_trades.py

# Enhanced logging verification
python3 verify_enhanced_logging.py

# Trading readiness check
python3 verify_trading_readiness.py
```

---

## 🔍 Status and Monitoring Commands

### Check Service Status

```bash
sudo systemctl status tradingbot
```

### View Recent Logs

```bash
# Last 50 lines
journalctl -u tradingbot -n 50

# Follow logs in real-time
journalctl -u tradingbot -f

# Last 5 minutes
journalctl -u tradingbot --since "5 minutes ago"

# Check for errors
journalctl -u tradingbot --since "1 hour ago" | grep -E "ERROR|Traceback|Exception"
```

### Check Enhanced Logging

```bash
# Watch for enhanced logging messages
journalctl -u tradingbot -f | grep -E "ENHANCED-LOGGING|INTEL-CONFIRM|INTEL-REDUCE"
```

### Verify Deployment

```bash
cd /root/trading-bot-B
git log --oneline -1
# Should show latest commit with forensic logging changes
```

### Check Active Directory

```bash
python3 -c "from src.infrastructure.path_registry import PathRegistry; print(PathRegistry.get_root())"
# Should output: /root/trading-bot-B
```

---

## 📁 Key File Locations

### Data Files
- **Positions:** `/root/trading-bot-B/logs/positions_futures.json`
- **Counterfactual Logs:** `/root/trading-bot-B/logs/counterfactual_trades.jsonl` (created on first use)
- **Bot Logs:** `/root/trading-bot-B/logs/bot_out.log`
- **Intelligence Gate Logs:** `/root/trading-bot-B/logs/intelligence_gate.log`

### Configuration
- **Service Config:** `/etc/systemd/system/tradingbot.service`
- **Environment:** `/root/trading-bot-B/.env`
- **Live Config:** `/root/trading-bot-B/live_config.json`

---

## 🛠️ Common Operations

### Restart Bot

```bash
sudo systemctl restart tradingbot
```

### Stop Bot

```bash
sudo systemctl stop tradingbot
```

### Start Bot

```bash
sudo systemctl start tradingbot
```

### View Service Logs

```bash
journalctl -u tradingbot -f
```

### Check Which Slot is Active

```bash
ls -la /root/trading-bot-current
# Shows symlink target (A or B)
```

### Pull Latest Code (Both Slots)

```bash
# Active slot (B)
cd /root/trading-bot-B
git pull origin main

# Inactive slot (A) - optional, for rollback capability
cd /root/trading-bot-A
git pull origin main
```

---

## 🔄 Automated Report Workflow (Recommended)

**Best Practice Pattern:**

1. **Pull latest code:**
   ```bash
   cd /root/trading-bot-B
   git pull origin main
   ```

2. **Generate reports:**
   ```bash
   source venv/bin/activate
   python3 generate_and_push_reports.py
   ```

3. **AI analyzes:** Reads full JSON/MD files from GitHub repository

4. **Results:** Comprehensive analysis with complete datasets

**Benefits:**
- ✅ Full data analysis (not snippets)
- ✅ Structured formats (JSON for programmatic analysis)
- ✅ No manual copy/paste
- ✅ Better insights
- ✅ Version history in git

---

## ⚠️ Troubleshooting

### Service Won't Start

```bash
# Check status
sudo systemctl status tradingbot

# Check logs for errors
journalctl -u tradingbot -n 100 | grep -E "ERROR|Traceback"

# Check if Python can import modules
cd /root/trading-bot-B
source venv/bin/activate
python3 -c "from src.position_manager import load_futures_positions; print('✅ OK')"
```

### Import Errors

```bash
cd /root/trading-bot-B
source venv/bin/activate
python3 -c "from src.counterfactual_tracker import log_blocked_signal; print('✅ OK')"
```

### Enhanced Logging Not Working

```bash
# Check if snapshots are being created
python3 -c "
import json
from pathlib import Path
data = json.load(open('logs/positions_futures.json'))
open_pos = data.get('open_positions', [])
if open_pos and 'volatility_snapshot' in open_pos[0]:
    print('✅ Enhanced logging is active')
    print(f'   Snapshot keys: {list(open_pos[0][\"volatility_snapshot\"].keys())}')
else:
    print('ℹ️  Wait for next trade to see enhanced logging')
"
```

### Git Pull Fails

```bash
# Check git status
git status

# If there are local changes, stash them
git stash
git pull origin main
git stash pop
```

---

## 📋 Deployment Checklist

After deploying forensic logging updates:

- [x] Code pulled successfully
- [x] New files exist (`src/counterfactual_tracker.py`)
- [x] No import errors
- [x] Service restarted and running
- [x] No errors in logs
- [x] Enhanced logging will activate on next trade

---

## 🎯 Quick Reference

| Task | Command |
|------|---------|
| Deploy updates | `cd /root/trading-bot-B && git pull && sudo systemctl restart tradingbot` |
| Generate reports | `python3 generate_and_push_reports.py` |
| Check status | `sudo systemctl status tradingbot` |
| View logs | `journalctl -u tradingbot -f` |
| Check errors | `journalctl -u tradingbot --since "1 hour ago" \| grep ERROR` |
| Verify deployment | `git log --oneline -1` |

---

## 📞 Dashboard Access

- **URL:** `http://159.65.168.230:8050/`
- **Password:** `Echelonlev2007!`

---

**Note:** Since you have automatic connection, you can run all these commands directly in your terminal without SSH. The droplet is already accessible!

