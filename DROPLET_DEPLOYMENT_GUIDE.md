# Droplet Deployment Guide
## Complete Guide for Deploying Clean Architecture to DigitalOcean

**Date:** 2025-01-XX  
**Purpose:** Step-by-step guide for deploying the new clean architecture to your droplet

---

## 🎯 Overview

The new clean architecture **does NOT change the droplet structure**. It's all code changes that work with the existing deployment.

**What Changed:**
- New modules added (SignalBus, StateMachine, etc.)
- New dashboard features (Analytics tab)
- New background services (ShadowExecutionEngine)
- All backward compatible with existing structure

**What Stays the Same:**
- Same directory structure
- Same systemd services
- Same port configuration
- Same file locations

---

## 📋 Pre-Deployment Checklist

Before deploying, ensure:
- [ ] All code pushed to git
- [ ] You have SSH access to droplet
- [ ] You know the droplet IP address
- [ ] You have the dashboard password: `Echelonlev2007!`

---

## 🚀 Deployment Steps

### Step 1: SSH into Droplet

```bash
ssh kraken
```

### Step 2: Navigate to Trading Bot Directory

```bash
cd /root/trading-bot-current
# or
cd /root/trading-bot-A  # if using slot-based deployment
```

### Step 3: Pull Latest Code

```bash
git pull origin main
```

**Verify:**
```bash
ls -la src/signal_bus.py
ls -la src/signal_state_machine.py
ls -la src/signal_pipeline_monitor.py
ls -la src/shadow_execution_engine.py
ls -la src/learning/decision_tracker.py
ls -la src/analytics/report_generator.py
```

All these files should exist.

### Step 4: Install Any New Dependencies (if needed)

```bash
pip3 install -r requirements.txt
```

**Note:** The new architecture uses only standard library + existing dependencies. No new packages needed.

### Step 5: Restart Services

The new architecture components start automatically with the bot. Just restart:

```bash
# Restart trading bot
systemctl restart tradingbot

# Restart dashboard (if separate service)
systemctl restart trading-dashboard
# or
systemctl restart cockpit
```

### Step 6: Verify Services Started

```bash
# Check bot status
systemctl status tradingbot

# Check logs for new components
tail -f /root/trading-bot-current/logs/bot_out.log | grep -E "SHADOW|SIGNAL-BUS|STATE-MACHINE"
```

**Expected output:**
```
🔮 [SHADOW] Shadow execution engine started (background thread)
✅ [SIGNAL-BUS] Signal bus initialized
✅ [STATE-MACHINE] State machine initialized
```

### Step 7: Verify Dashboard

1. Open browser: `http://YOUR_DROPLET_IP:8501`
2. Login with password: `Echelonlev2007!`
3. Click "Analytics" tab
4. Verify you see:
   - Signal Pipeline Health
   - Blocked Opportunity Cost
   - Guard Effectiveness
   - Strategy Leaderboard

---

## 🔍 Verification Checklist

### Signal Bus Working
```bash
# Check if signal bus log is being written
tail -f /root/trading-bot-current/logs/signal_bus.jsonl

# Should see new entries as signals are generated
```

### Shadow Engine Working
```bash
# Check shadow outcomes log
tail -f /root/trading-bot-current/logs/shadow_trade_outcomes.jsonl

# Should see shadow trades being tracked
```

### Decision Tracker Working
```bash
# Check decision log
tail -f /root/trading-bot-current/logs/signal_decisions.jsonl

# Should see decisions being tracked
```

### State Machine Working
```bash
# Check bot logs for state transitions
tail -f /root/trading-bot-current/logs/bot_out.log | grep "STATE-MACHINE"

# Should see transition logs (if verbose logging enabled)
```

---

## 🏗️ Architecture Components

### New Files Added

**Core Architecture:**
- `src/signal_bus.py` - Unified signal bus
- `src/signal_state_machine.py` - State machine
- `src/signal_pipeline_monitor.py` - Pipeline monitoring

**Learning Engine:**
- `src/learning/decision_tracker.py` - Decision tracking
- `src/learning/enhanced_learning_engine.py` - Enhanced learning
- `src/shadow_execution_engine.py` - Shadow execution
- `src/analytics/report_generator.py` - Analytics reports

**Event Schemas:**
- `src/events/schemas.py` - Event schemas

**Dashboard:**
- `cockpit.py` - Updated with Analytics tab

### Services Started Automatically

All new components start automatically in `src/run.py`:

1. **ShadowExecutionEngine** - Starts in `bot_worker()` function
2. **SignalBus** - Singleton, initialized on first use
3. **StateMachine** - Singleton, initialized on first use
4. **DecisionTracker** - Singleton, initialized on first use

**No new systemd services needed!**

---

## 📊 Dashboard Access

### Main Dashboard (Streamlit)
- **URL:** `http://YOUR_DROPLET_IP:8501`
- **Password:** `Echelonlev2007!`
- **Tabs:**
  - Trading: Active trades, history
  - Analytics: Pipeline health, blocked opportunities, guard effectiveness
  - Performance: Performance metrics

### PnL Dashboard (Flask/Dash)
- **URL:** `http://YOUR_DROPLET_IP:8050`
- **Password:** `Echelonlev2007!`
- **Features:** System health, P&L tracking, executive summary

---

## 🔧 Troubleshooting

### Issue: Shadow Engine Not Starting

**Check:**
```bash
grep "SHADOW" /root/trading-bot-current/logs/bot_out.log
```

**Fix:**
- Check if SignalBus is working
- Verify ExchangeGateway is accessible
- Check for import errors

### Issue: Analytics Tab Shows No Data

**Check:**
```bash
# Verify shadow outcomes exist
ls -la /root/trading-bot-current/logs/shadow_trade_outcomes.jsonl

# Check if signal bus has data
wc -l /root/trading-bot-current/logs/signal_bus.jsonl
```

**Fix:**
- Wait a few hours for data to accumulate
- Verify bot is generating signals
- Check dashboard can read files (permissions)

### Issue: State Transitions Not Working

**Check:**
```bash
# Check for state machine errors
grep "STATE-MACHINE" /root/trading-bot-current/logs/bot_out.log
```

**Fix:**
- Verify SignalBus is initialized
- Check signal_id is being passed correctly
- Verify state transitions are valid

---

## 📈 Monitoring

### Key Metrics to Watch

1. **Signal Pipeline Health**
   - Total signals
   - Stuck signals (should be 0)
   - Throughput (signals/hour)

2. **Shadow Execution**
   - Shadow trades tracked
   - Win rate of blocked signals
   - Opportunity cost

3. **Guard Effectiveness**
   - Which guards save money
   - Which guards cost money
   - Net impact per guard

### Log Files to Monitor

```bash
# Signal bus events
tail -f logs/signal_bus.jsonl

# Shadow trade outcomes
tail -f logs/shadow_trade_outcomes.jsonl

# Signal decisions
tail -f logs/signal_decisions.jsonl

# Bot output
tail -f logs/bot_out.log
```

---

## 🔄 Rollback Plan

If something goes wrong:

```bash
# Stop services
systemctl stop trading-bot

# Revert to previous commit
cd /root/trading-bot-current
git log --oneline -10  # Find previous commit
git checkout PREVIOUS_COMMIT_HASH

# Restart services
systemctl start trading-bot
```

**Or use slot-based deployment:**
- Switch symlink from `trading-bot-A` to `trading-bot-B`
- Keep old version in other slot

---

## ✅ Post-Deployment Verification

After deployment, verify:

1. **Bot is running:**
   ```bash
   systemctl status trading-bot
   ```

2. **Signals are being generated:**
   ```bash
   tail -f logs/signal_bus.jsonl | head -20
   ```

3. **Shadow engine is tracking:**
   ```bash
   ls -lh logs/shadow_trade_outcomes.jsonl
   ```

4. **Dashboard is accessible:**
   - Open browser, login, check Analytics tab

5. **No errors in logs:**
   ```bash
   grep -i error logs/bot_out.log | tail -20
   ```

---

## 🎯 Summary

**What to do on droplet:**
1. `git pull` - Get latest code
2. `systemctl restart trading-bot` - Restart bot
3. Verify logs show new components starting
4. Check dashboard Analytics tab

**No structural changes needed!** Everything works with existing deployment.

---

## 📞 Support

If you encounter issues:
1. Check logs: `tail -f logs/bot_out.log`
2. Verify files exist: `ls -la src/signal_bus.py`
3. Check services: `systemctl status trading-bot`
4. Review this guide for troubleshooting steps

