# Operator Safety Audit - Complete Risk Assessment

## Executive Summary

This document identifies all potential failure modes that could cause:
- Silent trading failures
- Mismatched state/positions/configs/dependencies/dashboard data
- Systemd pointing to wrong slot
- Bot running stale code
- Bot losing track of open positions
- Bot failing mid-trade
- Bot restarting with stale state
- Bot writing logs dashboard doesn't read

## Risk Categories

### 🔴 CRITICAL - Immediate Risk to Trading Operations

### 🟡 HIGH - Significant Risk to Data Integrity

### 🟢 MEDIUM - Moderate Risk, Should Be Fixed

### ⚪ LOW - Minor Risk, Nice to Have

---

## 🔴 CRITICAL RISKS

### RISK-001: Position Save Failure Silent Fallback
**Risk**: If `atomic_json_save()` fails, code falls back to non-atomic write without alerting operator.
**Location**: `src/position_manager.py:218-224`
```python
if not atomic_json_save(POSITIONS_FUTURES_FILE, positions):
    print(f"⚠️ [POSITION-MANAGER] Failed to save positions atomically, using fallback")
    with open(POSITIONS_FUTURES_FILE, 'w') as f:
        json.dump(positions, f, indent=2)
```
**Impact**: 
- Position data could be lost if crash occurs during fallback write
- No operator alert - failure is silent
- Dashboard may show stale data

**Fix**: Add alerting, retry logic, and validation

---

### RISK-002: Mid-Trade Crash Loses Position State
**Risk**: If bot crashes between opening position and saving to file, position is lost.
**Location**: `src/position_manager.py:229-393` (open_futures_position)
**Impact**:
- Position opened but not saved
- Bot restarts, doesn't know position exists
- Position becomes "orphaned" - no tracking

**Fix**: Add transaction-like state with recovery on restart

---

### RISK-003: File Lock Timeout Returns Default Silently
**Risk**: If file lock times out, `locked_json_read()` returns default empty dict without alerting.
**Location**: `src/file_locks.py:122-164`
```python
if not _acquire_lock(lock_file, exclusive=False, timeout=timeout):
    print(f"⚠️ [FILE-LOCK] Read lock timeout on {filepath}, returning default")
    return default.copy()
```
**Impact**:
- Bot thinks no positions exist when file is actually locked
- Could cause duplicate position opens
- No operator alert

**Fix**: Add alerting and retry with backoff

---

### RISK-004: Systemd Service Points to Wrong Slot
**Risk**: If symlink `trading-bot-current` points to wrong slot, bot runs stale code.
**Location**: Systemd service file (not in repo, but referenced)
**Impact**:
- Bot runs old code with known bugs
- New fixes not active
- Configuration mismatches

**Fix**: Add startup validation to detect slot mismatch

---

### RISK-005: Dashboard Reads Stale Data During File Write
**Risk**: Dashboard reads positions file while bot is writing, gets partial/corrupted data.
**Location**: `src/pnl_dashboard_loader.py` reads without checking for write locks
**Impact**:
- Dashboard shows corrupted data
- User sees incorrect positions/P&L
- No indication data is stale

**Fix**: Add file lock checking in dashboard loader

---

### RISK-006: Restart Loses In-Memory Position State
**Risk**: `BotCycle.open_positions` dict is lost on restart, positions exist in file but not tracked.
**Location**: `src/full_bot_cycle.py:287` (in-memory dict)
**Impact**:
- Positions exist in file but not actively tracked
- Exit logic doesn't run
- Positions become "zombie" - open but not managed

**Fix**: Rebuild in-memory state from file on startup

---

## 🟡 HIGH RISKS

### RISK-007: Partial Close Fails Mid-Operation
**Risk**: If partial close fails after updating position but before saving, state is inconsistent.
**Location**: `src/position_manager.py:684-697`
**Impact**:
- Position size updated in memory but not saved
- On restart, position reverts to old size
- P&L calculations incorrect

**Fix**: Use atomic transaction pattern

---

### RISK-008: Config File Mismatch Between Slots
**Risk**: If config files differ between slots, bot behavior inconsistent.
**Location**: Various config files (`live_config.json`, `config/asset_universe.json`)
**Impact**:
- Trading rules differ between restarts
- Unpredictable behavior
- Risk limits inconsistent

**Fix**: Add config validation and sync checks

---

### RISK-009: SQLite Database Out of Sync with JSON
**Risk**: Dashboard reads from SQLite, bot writes to JSON - if sync fails, data mismatches.
**Location**: `src/pnl_dashboard_loader.py:280-291` (tries SQLite first, falls back to JSON)
**Impact**:
- Dashboard shows different data than bot sees
- Closed positions missing from dashboard
- P&L calculations differ

**Fix**: Add sync validation and repair mechanisms

---

### RISK-010: Dependency Version Mismatch
**Risk**: If venv has different package versions than expected, behavior unpredictable.
**Location**: No validation of package versions
**Impact**:
- Silent failures due to API changes
- Unexpected behavior
- Hard to debug

**Fix**: Add dependency version checking

---

### RISK-011: Exchange Gateway Failure Silent
**Risk**: If exchange gateway fails, bot continues without alerting operator.
**Location**: Various places where `ExchangeGateway()` is used
**Impact**:
- Trades fail silently
- Positions not updated with real prices
- Dashboard shows stale prices

**Fix**: Add gateway health monitoring and alerting

---

## 🟢 MEDIUM RISKS

### RISK-012: Empty Positions File Not Detected on Startup
**Risk**: If `positions_futures.json` is empty `{}`, bot may not detect it needs repair.
**Location**: `src/position_manager.py:140-208` (initialize_futures_positions)
**Impact**:
- Bot starts with empty positions
- Existing positions lost (if file was corrupted)
- Dashboard shows no positions

**Fix**: Add startup validation and backup restoration

---

### RISK-013: Log File Path Mismatch
**Risk**: Bot writes to one log file, dashboard reads from different one.
**Location**: Various log files (already partially fixed in path audit)
**Impact**:
- Dashboard doesn't show recent activity
- Operator can't see what bot is doing
- Debugging difficult

**Fix**: Ensure all log paths use PathRegistry

---

### RISK-014: Restart During Trade Execution
**Risk**: If bot restarts while executing trade, trade may be partially completed.
**Location**: `src/bot_cycle.py:323-554` (execute_signal)
**Impact**:
- Trade partially executed
- Position state inconsistent
- Funds locked in partial position

**Fix**: Add trade execution state tracking and recovery

---

### RISK-015: Heartbeat Failure Doesn't Alert
**Risk**: If heartbeat fails, supervisor thinks bot is dead but bot is actually running.
**Location**: `src/run.py:2296-2340` (process heartbeat)
**Impact**:
- Supervisor may restart bot unnecessarily
- Or supervisor may not detect bot is actually dead
- Unpredictable behavior

**Fix**: Add heartbeat validation and alerting

---

## ⚪ LOW RISKS

### RISK-016: Cache Staleness in Dashboard
**Risk**: Dashboard cache may show stale data if file changes but cache not invalidated.
**Location**: `src/pnl_dashboard_loader.py:26-40` (cache with 10s TTL)
**Impact**:
- Dashboard shows data up to 10s old
- Minor user experience issue

**Fix**: Reduce cache TTL or add manual refresh

---

### RISK-017: Backup File Rotation May Lose Data
**Risk**: If backup rotation deletes all backups, no recovery possible.
**Location**: `src/data_registry.py:900-923` (_rotate_backups)
**Impact**:
- If file corrupted and backups deleted, data lost
- No recovery possible

**Fix**: Ensure minimum backup retention

---

## Summary Statistics

- **CRITICAL Risks**: 6
- **HIGH Risks**: 5
- **MEDIUM Risks**: 4
- **LOW Risks**: 2
- **Total Risks**: 17

## Next Steps

1. Fix all CRITICAL risks immediately
2. Fix HIGH risks in next iteration
3. Address MEDIUM risks as time permits
4. Document LOW risks for future consideration






