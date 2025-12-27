# Code Cleanup Execution Plan

**Date:** 2025-12-27  
**Status:** In Progress

---

## Findings

### Files That ARE Used (KEEP):
1. **`src/pnl_dashboard.py`** - Still used for:
   - `get_wallet_balance()` function (imported in `run.py`)
   - Fallback for `generate_executive_summary()` in `pnl_dashboard_v2.py`

2. **`src/dashboard_app.py`** - Used by:
   - `src/export_codebase.py` (listed in exports)

3. **Dashboard modules that ARE imported:**
   - `src/phase8_trader_dashboard.py` - Used by `dashboard_app.py`
   - `src/trading_performance_dashboard.py` - Used by `dashboard_app.py`
   - `src/cockpit_dashboard_generator.py` - Used by `full_bot_cycle.py`
   - `src/dashboard_validator.py` - Used by `meta_learning_orchestrator.py`
   - `src/dashboard_verification.py` - Used by `health_pulse_orchestrator.py`
   - `src/dashboard_health_monitor.py` - Used by `run_dashboard_health_check.py`
   - `src/dashboard_reconciliation.py` - Used by `run_dashboard_health_check.py`

### Files That May Be Unused (NEED VERIFICATION):
1. **`run_dashboard_health_check.py`** - Script, check if run anywhere
2. **`cockpit.py`** - Streamlit dashboard, not started in run.py

---

## Action Plan

### Step 1: Move Functions from `pnl_dashboard.py` to `pnl_dashboard_v2.py`
- Move `get_wallet_balance()` to `pnl_dashboard_v2.py`
- Update `run.py` import
- This will allow deletion of `pnl_dashboard.py`

### Step 2: Verify Unused Files
- Check if `run_dashboard_health_check.py` is run anywhere
- Check if `cockpit.py` is needed (user views v2 dashboard)

### Step 3: Remove Unused Files
- Delete files that are truly unused
- Update any broken references

---

## Safe to Remove Now:
- ✅ Already removed: `bot_cycle.backup.py`, `alpha_to_execution_adapter_backup.py`

