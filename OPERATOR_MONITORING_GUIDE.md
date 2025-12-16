# Operator Monitoring Guide
## What to Watch to Confirm Everything is Working

**Date:** 2025-12-16  
**Primary Dashboard:** `http://YOUR_IP:8050` (Streamlit)

---

## ✅ Primary Monitoring: Dashboard (Port 8050)

### What to Check Daily

#### 1. **System Health Panel** (Main Tab)
**Location:** Dashboard → Trading Tab → System Health

**What to Watch:**
- ✅ **Signal Engine:** Should be GREEN (signals being generated)
- ✅ **Decision Engine:** Should be GREEN (decisions being made)
- ✅ **Trade Execution:** Should be GREEN (trades being executed)
- ✅ **Self-Healing:** Should be GREEN (auto-repair working)
- ✅ **Safety Layer:** Should be GREEN (safety checks passing)

**Action if RED:**
- Check logs: `journalctl -u tradingbot -n 100`
- Self-healing should fix automatically (wait 1-2 minutes)
- If still red after 5 minutes, investigate

#### 2. **Analytics Tab** (New Architecture)
**Location:** Dashboard → Analytics Tab

**What to Watch:**
- **Blocked Opportunity Cost:** Shows money left on table
- **Guard Effectiveness:** Which guards help/hurt
- **Strategy Leaderboard:** Best/worst strategies
- **Signal Decay Metrics:** How fast signals age

**What It Means:**
- High blocked opportunity cost = Guards too strict
- Negative guard effectiveness = Guard costing money
- Strategy leaderboard = Which strategies to favor

#### 3. **Performance Tab**
**Location:** Dashboard → Performance Tab

**What to Watch:**
- Win rate (should be >50%, ideally >55%)
- Average profit per trade (should be positive)
- Total P&L (should be trending up)
- Trade count (should be increasing)

---

## 📊 Executive Summary (Daily)

### Where to Find It

**Option 1: Dashboard API**
```bash
curl http://YOUR_IP:8050/audit/executive_summary
```

**Option 2: Dashboard UI**
- Should be in Executive Summary tab (if implemented)
- Or check logs for daily digest

### What It Contains

1. **What Worked Today**
   - Profitable trades
   - Successful strategies
   - Effective guards

2. **What Didn't Work**
   - Losing trades
   - Failed strategies
   - Ineffective guards

3. **Missed Opportunities**
   - Blocked trades that would have been profitable
   - Opportunity cost analysis

4. **Blocked Signals Analysis**
   - Signals that should have been traded
   - Guard effectiveness review

5. **Exit Gate Analysis**
   - Exit gates that misfired
   - Premature exits vs missed exits

6. **What the Engine Learned**
   - Weight adjustments
   - Gate changes
   - Strategy promotions/demotions

7. **What Will Change Tomorrow**
   - Upcoming adjustments
   - Learning system proposals

8. **Weekly Summary**
   - 7-day performance
   - Learning trends
   - Overall health

---

## 🔔 Additional Monitoring

### 1. **Log Files** (Optional - for deep dive)

**Key Files to Check:**
```bash
# Recent signals
tail -20 logs/predictive_signals.jsonl

# Recent trades
tail -20 logs/positions_futures.json

# Learning updates
tail -20 logs/learning_updates.jsonl

# Operator alerts (critical issues)
tail -20 logs/operator_alerts.jsonl
```

### 2. **Systemd Status** (Quick Health Check)

```bash
# Check if bot is running
systemctl status tradingbot

# Check recent logs
journalctl -u tradingbot -n 50 --no-pager
```

### 3. **Architecture Components** (New)

**Check SignalBus Activity:**
```bash
# Count signals tracked
wc -l logs/signal_bus.jsonl

# Recent signals
tail -5 logs/signal_bus.jsonl
```

**Check Shadow Engine:**
```bash
# Shadow trade outcomes
tail -10 logs/shadow_trade_outcomes.jsonl
```

**Check Decision Tracking:**
```bash
# Decision events
tail -10 logs/signal_decisions.jsonl
```

---

## ⚠️ Red Flags to Watch For

### Critical (Immediate Action Required)

1. **Bot Cycle Not Running**
   - Dashboard shows "Bot cycle not found"
   - No recent signals
   - **Action:** Check `systemctl status tradingbot`

2. **All Health Checks Red**
   - Everything showing red for >10 minutes
   - **Action:** Check logs, restart if needed

3. **No Signals Generated**
   - `predictive_signals.jsonl` not updated in >30 minutes
   - **Action:** Check market data connections

4. **Continuous Errors**
   - Same error repeating in logs
   - **Action:** Check error message, may need code fix

### Warning (Monitor Closely)

1. **Win Rate <40%**
   - System may need adjustment
   - **Action:** Review strategy performance

2. **Negative Average Profit**
   - Losing money on average
   - **Action:** Review guard effectiveness, may need tightening

3. **High Blocked Opportunity Cost**
   - Guards too strict
   - **Action:** Review Analytics tab, consider guard adjustments

4. **Learning Systems Not Updating**
   - No learning updates in >24 hours
   - **Action:** Check learning controller logs

---

## 📅 Daily Checklist

### Morning (5 minutes)
- [ ] Check dashboard health panel (all green?)
- [ ] Review overnight trades (count, win rate)
- [ ] Check for critical alerts
- [ ] Review executive summary (if available)

### Evening (5 minutes)
- [ ] Review daily performance (P&L, win rate)
- [ ] Check Analytics tab (blocked opportunities, guard effectiveness)
- [ ] Review learning updates (what changed?)
- [ ] Check for any red flags

### Weekly (15 minutes)
- [ ] Review weekly summary
- [ ] Analyze strategy leaderboard
- [ ] Review guard effectiveness trends
- [ ] Check learning system convergence

---

## 🎯 Key Metrics to Track

### Performance Metrics
- **Win Rate:** Target >50% (ideally >55%)
- **Average Profit:** Target >$0 per trade
- **Total P&L:** Should trend upward
- **Trade Count:** Should be consistent (not zero)

### Learning Metrics
- **Signal Weight Updates:** Should see adjustments
- **Guard Effectiveness:** Should see positive values
- **Strategy Promotions:** Winners should be promoted
- **Symbol Suppressions:** Losers should be suppressed

### Health Metrics
- **All Health Checks:** Should be GREEN
- **Bot Cycle:** Should complete every ~2 minutes
- **Self-Healing:** Should show green (auto-repair working)
- **No Critical Errors:** Should be minimal

---

## 📧 Alerts & Notifications

### Operator Alerts
**Location:** `logs/operator_alerts.jsonl`

**What Triggers Alerts:**
- Critical system failures
- Data integrity violations
- Trading engine failures
- Safety layer breaches

**How to Check:**
```bash
tail -20 logs/operator_alerts.jsonl
```

### Email Reports (If Configured)
**Location:** Check your email (if `REPORT_TO_EMAIL` is set)

**What's Included:**
- Daily digest
- Performance summary
- Learning updates
- Critical alerts

---

## 🚀 Quick Status Check (30 seconds)

**Run this daily:**
```bash
cd ~/trading-bot-current
./verify_bot_working.sh
```

**Or manually:**
```bash
# Check bot status
systemctl status tradingbot | head -10

# Check recent activity
journalctl -u tradingbot --since "1 hour ago" | grep -E "completed|signal|trade" | tail -10
```

---

## 📋 Summary

### Primary Monitoring
✅ **Dashboard (Port 8050)** - Your main source of truth
- System Health Panel
- Analytics Tab
- Performance Tab

### Daily Checks
✅ **Executive Summary** - What worked/didn't work
✅ **Health Panel** - All green?
✅ **Performance Metrics** - Win rate, P&L

### Weekly Reviews
✅ **Analytics Tab** - Guard effectiveness, strategy leaderboard
✅ **Learning Updates** - What changed?
✅ **Weekly Summary** - Overall trends

### Red Flags
⚠️ **Bot not running** - Check systemd
⚠️ **All health red** - Check logs
⚠️ **No signals** - Check market data
⚠️ **Win rate <40%** - Review strategies

---

## 🎯 Bottom Line

**You're doing it right!**

- ✅ Dashboard (Port 8050) is your main source of truth
- ✅ Executive summaries will come daily
- ✅ Health panel shows system status
- ✅ Analytics tab shows learning insights

**Just watch the dashboard daily - that's all you need!**

The bot will:
- Trade automatically
- Learn continuously
- Heal itself
- Alert you if critical issues occur

**You're set! Just monitor the dashboard and wait for the executive summaries.** 🎉

