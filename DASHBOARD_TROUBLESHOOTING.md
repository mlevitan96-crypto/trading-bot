# Dashboard Troubleshooting Guide

## Current Issue: Dashboard Not Loading (404 Not Found)

### Quick Diagnostic Commands

1. **Check if dashboard process is running:**
   ```bash
   ps aux | grep -E "python.*run\.py|gunicorn|flask" | grep -v grep
   ```

2. **Check if port 8050 is listening:**
   ```bash
   netstat -tlnp | grep 8050
   # or
   ss -tlnp | grep 8050
   ```

3. **Check full startup logs:**
   ```bash
   journalctl -u tradingbot --since "5 minutes ago" | head -100
   ```

4. **Check for dashboard startup messages:**
   ```bash
   journalctl -u tradingbot --since "5 minutes ago" | grep -E "Starting P&L|Dashboard|8050|dash_app"
   ```

5. **Check for any Python errors:**
   ```bash
   journalctl -u tradingbot --since "5 minutes ago" | grep -E "Traceback|Error|Exception|Failed"
   ```

### Common Issues

#### Issue 1: Dashboard Not Starting
**Symptoms:** 404 Not Found, no dashboard logs

**Possible Causes:**
- Dashboard initialization is crashing silently
- Port 8050 is blocked or in use
- Import errors in dashboard module
- Exception during `build_app()` call

**Fix:**
- Check full error logs: `journalctl -u tradingbot -n 200`
- Verify port is available: `sudo lsof -i :8050`
- Check if dashboard module imports: `python3 -c "from src.pnl_dashboard import build_app"`

#### Issue 2: Rate Limiting (429 Errors)
**Symptoms:** Dashboard loads but PnL shows 0, lots of 429 errors in logs

**Fix:**
- Price caching is now implemented (30 second cache)
- OHLCV is used as primary source (less rate limiting)
- Should resolve automatically after cache populates

#### Issue 3: Empty DataFrames Causing Crashes
**Symptoms:** Dashboard crashes when loading

**Fix:**
- Error handling added for empty DataFrames
- Dropdowns now handle empty data safely
- App should start even with no data

### Manual Dashboard Start Test

To test if dashboard can start manually:

```bash
cd ~/trading-bot-current
source venv/bin/activate  # if using venv
python3 -c "
import sys
sys.path.insert(0, 'src')
try:
    from pnl_dashboard import start_pnl_dashboard
    from flask import Flask
    app = Flask(__name__)
    dash_app = start_pnl_dashboard(app)
    print('✅ Dashboard can be imported and initialized')
except Exception as e:
    print(f'❌ Dashboard error: {e}')
    import traceback
    traceback.print_exc()
"
```

### Expected Startup Messages

When dashboard starts successfully, you should see:
```
🌐 Starting P&L Dashboard on http://0.0.0.0:8050
   ✅ Port 8050 is available
   ✅ P&L Dashboard initialized successfully
```

If you see:
```
   ⚠️  P&L Dashboard startup error: ...
```
Then there's an error during initialization - check the traceback.

### Next Steps

1. Run the diagnostic commands above
2. Share the output of: `journalctl -u tradingbot --since "5 minutes ago" | head -100`
3. Check if port 8050 is listening: `netstat -tlnp | grep 8050`

