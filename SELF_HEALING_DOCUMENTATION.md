# Self-Healing Layer Documentation

## Overview

The self-healing layer in `src/operator_safety.py` automatically repairs recoverable issues during startup and runtime, while flagging dangerous issues that require operator intervention.

## What is Auto-Healed

### Cold-Start Issues (Always Auto-Healed)

1. **Missing Directories**
   - Creates: `logs/`, `config/`, `configs/`, `data/`, `feature_store/`, `state/`, `state/heartbeats/`, `logs/backups/`
   - Action: Creates directory structure with proper permissions

2. **Missing Files**
   - Initializes: `logs/positions_futures.json`, `logs/portfolio_futures.json`
   - Action: Creates files with valid empty structures

3. **Empty Files**
   - Repairs: Files that exist but are empty (`{}` or `0 bytes`)
   - Action: Replaces with valid structure, preserving any existing data if possible

4. **Malformed JSON Structure**
   - Repairs: Files with missing required keys (e.g., `open_positions`, `closed_positions`)
   - Action: Adds missing keys with empty arrays, preserves existing data

### Recoverable Runtime Issues (Auto-Healed)

1. **Stale File Locks**
   - Detects: Lock files older than 5 minutes
   - Action: Removes stale lock files to unblock operations
   - Risk: Low - locks are advisory, stale locks indicate dead processes

2. **Stale Heartbeats**
   - Detects: Heartbeat files older than 10 minutes
   - Action: Resets heartbeat timestamps to current time
   - Risk: Low - indicates process restart or temporary stall

3. **Corrupted JSON Files**
   - Detects: JSON parse errors in critical files
   - Action: Attempts to extract valid data, falls back to empty structure
   - Risk: Medium - may lose some data, but prevents system failure

4. **Orphan Processes** (Paper Mode Only)
   - Detects: Stale Python processes running trading bot code
   - Action: Terminates orphan processes (paper mode only)
   - Risk: Medium - in real mode, only logs (too risky to auto-kill)

## What is NOT Auto-Healed (CRITICAL Alerts Only)

These issues are detected and logged as CRITICAL alerts, but require operator intervention:

1. **State Mismatches**
   - Example: Positions count doesn't match portfolio state
   - Reason: Could indicate data corruption or incomplete transactions
   - Action: Operator must investigate and reconcile manually

2. **Partial Fills**
   - Example: Trade marked as "filled" but position size doesn't match order
   - Reason: Could indicate exchange API inconsistency or network issues
   - Action: Operator must verify with exchange and reconcile

3. **Conflicting Positions**
   - Example: Duplicate positions (same symbol + direction)
   - Reason: Could indicate double-entry bug or race condition
   - Action: Operator must investigate and remove duplicates manually

4. **Data Integrity Violations**
   - Example: Positions with invalid entry_price (≤0) or size (≤0)
   - Reason: Indicates corruption or bug in position tracking
   - Action: Operator must investigate and fix manually

## Self-Healing Process

### Startup Flow

1. **Validation Phase**
   - `validate_systemd_slot()`: Checks deployment slot integrity
   - `validate_startup_state()`: Checks file structure and permissions

2. **Self-Healing Phase**
   - `self_heal()`: Attempts to repair all recoverable issues
   - Returns status object with healing results

3. **Trading Engine Startup Decision**
   - **Paper Mode**: ALWAYS starts, even if healing found issues
   - **Real Mode**: Only starts if:
     - Health checks passed (score ≥ 50, status ≠ "critical")
     - Self-healing succeeded (no critical issues found)

### Healing Results

The `self_heal()` function returns:

```python
{
    "success": bool,           # True if no critical issues
    "healed": List[str],        # Issues successfully healed
    "failed": List[str],        # Issues that couldn't be healed
    "critical": List[str],      # Dangerous issues (not auto-healed)
    "stats": {
        "files_created": int,
        "files_repaired": int,
        "directories_created": int,
        "heartbeats_reset": int,
        "locks_cleared": int,
        "orphans_killed": int
    }
}
```

## Integration Points

### `src/run.py`

- Calls `self_heal()` after validation, before starting trading engine
- Uses healing results to gate trading engine startup in real mode
- Always starts engine in paper mode regardless of healing status

### `src/operator_safety.py`

- `self_heal()`: Main healing function
- `alert_operator()`: Sends CRITICAL alerts for dangerous issues
- `validate_startup_state()`: Detects issues that need healing

## Safety Guarantees

1. **No Data Loss**: Healing preserves existing data when possible
2. **Conservative Approach**: Dangerous issues are never auto-healed
3. **Paper Mode Safety**: Paper mode always starts (safe to test)
4. **Real Mode Protection**: Real mode only starts if all checks pass
5. **Audit Trail**: All healing actions are logged

## Operator Actions

When CRITICAL alerts are raised:

1. **Review Alerts**: Check `logs/operator_alerts.jsonl`
2. **Investigate**: Use diagnostic tools to understand the issue
3. **Fix Manually**: Resolve dangerous issues (state mismatches, conflicts)
4. **Restart**: Restart the bot after fixing issues

## Examples

### Example 1: Cold Start (Empty Positions File)

```
🔧 [SELF-HEAL] Starting self-healing process...
   ✅ Created directory: logs
   ✅ Initialized positions file: logs/positions_futures.json
✅ [SELF-HEAL] Healed 2 issues
```

### Example 2: Corrupted JSON

```
🔧 [SELF-HEAL] Starting self-healing process...
   ✅ Repaired corrupted positions file: logs/positions_futures.json
✅ [SELF-HEAL] Healed 1 issues
```

### Example 3: Critical Issue Detected

```
🔧 [SELF-HEAL] Starting self-healing process...
   ✅ Initialized positions file: logs/positions_futures.json
🚨 [SELF-HEAL] Found 1 dangerous issues (NOT auto-healed)
🚨 [CRITICAL] POSITION_CONFLICT: Duplicate positions detected in open_positions
```

## Future Enhancements

Potential future improvements:

1. **Periodic Healing**: Run healing checks periodically, not just at startup
2. **Healing Metrics**: Track healing success rate over time
3. **Predictive Healing**: Detect issues before they become critical
4. **Backup Before Healing**: Create backups before repairing files
5. **Healing Rollback**: Ability to rollback healing actions if they cause issues




