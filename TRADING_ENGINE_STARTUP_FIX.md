# Trading Engine Startup Fix

## Problem
After safety audit changes, trading engine was not starting - only dashboard was running.

## Root Cause
Safety validation and health checks were potentially blocking or causing exceptions that prevented `bot_worker` thread from starting.

## Solution

### 1. Paper Mode Always Starts Trading Engine
- **Requirement**: Paper trading mode must ALWAYS start the trading engine, even if health checks are degraded.
- **Implementation**: 
  - Added `is_paper_mode` check in `run_heavy_initialization()`
  - Health check failures in paper mode are logged as warnings but don't block startup
  - Trading engine always starts in paper mode regardless of health check results

### 2. Real Trading Mode Gated by Health Checks
- **Requirement**: Real trading mode must ONLY start the engine if health checks pass.
- **Implementation**:
  - Health check score < 50 or status == 'critical' blocks startup in real trading mode
  - Health check errors block startup in real trading mode
  - Dashboard continues running even if trading engine is blocked

### 3. Safety Module Non-Blocking
- **Requirement**: Safety module should still run and log warnings, but must not block paper mode.
- **Implementation**:
  - All safety validation wrapped in try-except (already was)
  - Alert levels downgraded in paper mode:
    - SYSTEMD_SLOT: CRITICAL → HIGH in paper mode
    - STARTUP_VALIDATION: HIGH → MEDIUM in paper mode
  - Validation failures logged but never block startup

### 4. Updated run.py
- **Changes**:
  - `main()`: Added paper mode detection, safety validation non-blocking
  - `run_heavy_initialization()`: 
    - Added paper mode detection
    - Health checks non-blocking in paper mode
    - Trading engine starts based on mode and health check result
    - Clear logging of why trading engine starts or doesn't start

## Files Modified

### `src/run.py`
1. **main()** (lines ~1613-1628):
   - Added `trading_mode` and `is_paper_mode` detection
   - Safety validation wrapped with paper mode awareness
   - Clear messaging about continuing in paper mode

2. **run_heavy_initialization()** (lines ~1496-1560):
   - Added `trading_mode` and `is_paper_mode` detection
   - Health checks wrapped with paper mode logic
   - Trading engine startup gated by mode and health check:
     - Paper mode: Always starts
     - Real mode: Only starts if health check passes (score >= 50, status != 'critical')
   - Clear logging of startup decision

### `src/operator_safety.py`
1. **validate_systemd_slot()** (lines ~179-199):
   - Alert level downgraded in paper mode (CRITICAL → HIGH)
   - Exception handler also downgrades alerts in paper mode

2. **validate_startup_state()** (lines ~204-280):
   - Alert level downgraded in paper mode (HIGH → MEDIUM)
   - Exception handler also downgrades alerts in paper mode

## Behavior Summary

### Paper Trading Mode
- ✅ Safety validation runs (warnings only, never blocks)
- ✅ Health checks run (warnings only if degraded, never blocks)
- ✅ Trading engine ALWAYS starts
- ✅ Dashboard ALWAYS starts
- ✅ All alerts logged but don't block operations

### Real Trading Mode
- ✅ Safety validation runs (alerts at appropriate levels)
- ✅ Health checks run (must pass to start trading engine)
- ⚠️ Trading engine starts ONLY if health check passes (score >= 50, status != 'critical')
- ✅ Dashboard ALWAYS starts (even if trading engine blocked)
- ⚠️ Alerts may require operator action

## Testing

### Paper Mode Test
1. Set `TRADING_MODE=paper`
2. Start bot
3. Verify: Trading engine starts regardless of health check results
4. Verify: Dashboard starts
5. Verify: Warnings logged but don't block

### Real Mode Test
1. Set `TRADING_MODE=live` (or real)
2. Start bot with healthy system
3. Verify: Trading engine starts
4. Start bot with degraded health (score < 50)
5. Verify: Trading engine does NOT start
6. Verify: Dashboard still starts
7. Verify: Alerts logged

## Log Messages

### Paper Mode (Health Check Degraded)
```
⚠️  Health check degraded (score: 45, status: degraded)
ℹ️  PAPER MODE: Continuing despite degraded health - trading engine WILL start
🤖 Starting trading engine (mode: PAPER)...
   ✅ Trading engine started
```

### Real Mode (Health Check Failed)
```
❌ Health check failed (score: 45, status: critical)
⚠️  REAL TRADING MODE: Health check failed - trading engine will NOT start
⛔ Trading engine NOT started - health check failed in REAL TRADING MODE
   ℹ️  Dashboard will continue running, but no trades will execute
```

### Real Mode (Health Check Passed)
```
✅ Startup health check passed - trading engine will start
🤖 Starting trading engine (mode: LIVE)...
   ✅ Trading engine started
```

## Summary

- **Paper Mode**: Trading engine always starts, safety/health checks are advisory only
- **Real Mode**: Trading engine gated by health checks, dashboard always starts
- **Safety Module**: Always runs, alerts appropriately, never blocks paper mode
- **Dashboard**: Always starts regardless of mode or health checks

