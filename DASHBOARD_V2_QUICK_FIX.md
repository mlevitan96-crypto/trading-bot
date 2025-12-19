# Dashboard V2 Quick Fix Guide

## Issue: Dashboard Not Loading / No Data Showing

### Root Cause
The dashboard was trying to access data before checking if `DataRegistry.read_json()` returned `None`. This caused crashes when data files didn't exist or couldn't be loaded.

### Fix Applied
✅ **All data loading functions now handle `None` returns properly**
✅ **Removed initial data load at build time** - data loads on demand in callbacks
✅ **Added graceful fallbacks** - dashboard shows empty state instead of crashing

### Files Fixed
- `src/pnl_dashboard_v2.py` - All data loading functions now handle None

### Next Steps (On Droplet)

```bash
# 1. Pull latest fix
cd /root/trading-bot-current
git pull origin main

# 2. Check for actual startup errors
journalctl -u tradingbot --since "5 minutes ago" | grep -E "DASHBOARD-V2|ERROR|Traceback|Exception" | tail -50

# 3. Restart bot
sudo systemctl restart tradingbot

# 4. Wait 30 seconds, then check if dashboard is accessible
sleep 30
curl -I http://localhost:8050/

# 5. Check dashboard startup messages
journalctl -u tradingbot --since "2 minutes ago" | grep -i "DASHBOARD-V2" | tail -20
```

### If Still Not Working

Check full error logs:
```bash
journalctl -u tradingbot --since "5 minutes ago" > /tmp/dashboard_errors.log
cat /tmp/dashboard_errors.log | grep -A 20 -E "DASHBOARD-V2|Traceback|Error|Exception"
```

### Expected Behavior After Fix

1. ✅ Dashboard should start even if `positions_futures.json` doesn't exist
2. ✅ Dashboard should show empty tables/charts (not crash)
3. ✅ Once data exists, it should load correctly
4. ✅ No more `AttributeError: 'NoneType' object has no attribute 'get'` errors
