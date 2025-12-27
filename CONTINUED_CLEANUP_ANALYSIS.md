# Continued Code Cleanup Analysis

**Date:** 2025-12-27  
**Purpose:** Continue identifying and removing old/unused code

---

## Files to Check

### Dashboard Files (Need Usage Verification):
1. `src/dashboard_app.py` (349KB) - Large file, verify usage
2. `src/phase8_trader_dashboard.py` - Verify usage
3. `src/trading_performance_dashboard.py` - Verify usage
4. `src/cockpit_dashboard_generator.py` - Verify usage
5. `src/dashboard_health_monitor.py` - Verify usage
6. `src/dashboard_reconciliation.py` - Verify usage
7. `src/dashboard_validator.py` - Verify usage
8. `src/dashboard_verification.py` - Verify usage
9. `src/run_dashboard_health_check.py` - Verify usage
10. `cockpit.py` - Streamlit dashboard, verify if used

### Old Dashboard File:
- `src/pnl_dashboard.py` - Only used for `generate_executive_summary()`, can delete after extraction

---

## Analysis Strategy

1. Check imports for each dashboard file
2. Check if files are referenced in run.py
3. Check systemd services
4. Remove unused files
5. Update any broken imports

---

## Expected Actions

- Delete unused dashboard files
- Remove old pnl_dashboard.py if not needed
- Clean up unused imports
- Document what was removed

