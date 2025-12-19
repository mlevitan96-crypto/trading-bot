# Dashboard V2 - Clean Rebuild Deployment Guide

## What Was Built

**New Clean Dashboard** (`src/pnl_dashboard_v2.py`):
- ✅ **2 Tabs Only**: Daily Summary, Executive Summary
- ✅ **All Functionality Preserved**:
  - System Health Panel
  - Wallet Balance (with running graph)
  - Daily/Weekly/Monthly Summary Cards
  - Open Positions Table (with real-time pricing)
  - Closed Positions Table
  - All Charts: Equity Curve, P&L by Symbol, P&L by Strategy, Win Rate Heatmap
  - Wallet Balance Trend
- ✅ **Standardized Data Sources**: Uses `positions_futures.json` via DataRegistry
- ✅ **Port 8050**: Maintains compatibility
- ✅ **Clean Code**: No legacy baggage, easy to maintain

---

## Deployment Steps

### Step 1: Backup Current Dashboard (Optional)

```bash
# On your droplet:
cd /root/trading-bot-current
cp src/pnl_dashboard.py src/pnl_dashboard.py.backup
```

### Step 2: Pull Latest Changes

```bash
cd /root/trading-bot-current
git pull origin main
```

### Step 3: Verify New Dashboard File

```bash
# Check new dashboard exists
ls -la src/pnl_dashboard_v2.py

# Check run.py was updated to use V2
grep -n "pnl_dashboard_v2" src/run.py
```

### Step 4: Test Import (Optional)

```bash
# Test that dashboard imports correctly
python3 -c "from src.pnl_dashboard_v2 import start_pnl_dashboard; print('✅ Dashboard V2 imports successfully')"
```

### Step 5: Restart Bot

```bash
sudo systemctl restart tradingbot
```

### Step 6: Verify Dashboard Loads

```bash
# Check logs for dashboard startup
journalctl -u tradingbot --since "2 minutes ago" | grep -i "dashboard\|DASHBOARD-V2" | head -20

# Verify dashboard is accessible (should return HTTP 200 or login page)
curl -I http://localhost:8050/
```

---

## What Changed

### Old Dashboard (`src/pnl_dashboard.py`)
- ❌ Legacy code with multiple tabs (Daily, Weekly, Monthly, Executive)
- ❌ Complex callback structure
- ❌ Executive Summary not showing properly
- ❌ Mixed data sources and path handling

### New Dashboard (`src/pnl_dashboard_v2.py`)
- ✅ Clean 2-tab structure (Daily Summary, Executive Summary)
- ✅ Simplified callbacks
- ✅ Executive Summary works correctly (uses existing generator from old dashboard)
- ✅ Standardized data sources (positions_futures.json via DataRegistry)
- ✅ All charts and functionality preserved
- ✅ Weekly/Monthly summaries shown in Daily Summary tab

---

## Dashboard Features

### Daily Summary Tab
1. **System Health Panel** - Signal Engine, Decision Engine, Trade Execution, Self-Healing
2. **Summary Cards**:
   - Daily Summary (Last 24 Hours)
   - Weekly Summary (Last 7 Days)
   - Monthly Summary (Last 30 Days)
   Each showing: Wallet Balance, Total Trades, Net P&L, Win Rate, Wins/Losses, Avg Win/Loss
3. **Wallet Balance Trend** - Running graph from snapshots
4. **Charts**:
   - Equity Curve
   - P&L by Symbol
   - P&L by Strategy
   - Win Rate Heatmap
5. **Open Positions Table** - Real-time pricing, P&L, leverage
6. **Closed Positions Table** - Recent 100 trades with all details

### Executive Summary Tab
- What Worked Today
- What Didn't Work
- Missed Opportunities
- Blocked Signals
- Exit Gates Analysis
- Learning Today
- Changes Tomorrow
- Weekly Summary

---

## Troubleshooting

### Dashboard Not Loading

```bash
# Check if port 8050 is in use
sudo lsof -i :8050

# Check dashboard startup errors
journalctl -u tradingbot --since "5 minutes ago" | grep -i "error\|traceback\|dashboard" | tail -50
```

### Executive Summary Empty

The Executive Summary uses the existing generator from the old dashboard. If it's empty, check:
```bash
# Check if executive summary generator works
python3 -c "from src.pnl_dashboard import generate_executive_summary; print(generate_executive_summary())"
```

### Import Errors

If you see import errors, ensure all dependencies are installed:
```bash
pip install -r requirements.txt
```

---

## Rollback (If Needed)

If you need to rollback to the old dashboard:

```bash
# Edit run.py to use old dashboard
cd /root/trading-bot-current
# Change line: from src.pnl_dashboard_v2 import start_pnl_dashboard
# To: from src.pnl_dashboard import start_pnl_dashboard
sudo systemctl restart tradingbot
```

Or restore from backup:
```bash
cp src/pnl_dashboard.py.backup src/pnl_dashboard.py
# Edit run.py as above
sudo systemctl restart tradingbot
```

---

## Summary

✅ **New clean dashboard built from scratch**
✅ **All functionality preserved**
✅ **2 tabs: Daily Summary, Executive Summary**
✅ **Port 8050 maintained**
✅ **Ready to deploy**

The new dashboard is cleaner, easier to maintain, and has all the features you need!
