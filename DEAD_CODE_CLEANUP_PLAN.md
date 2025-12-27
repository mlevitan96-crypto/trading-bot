# Dead Code Cleanup Plan

**Date:** 2025-12-27  
**Purpose:** Remove old code, unused files, and deprecated references to prevent confusion and breakage

---

## Files Identified for Removal/Consolidation

### 1. **Backup Files** - Safe to Remove ✅
- `src/bot_cycle.backup.py` - Backup file, not imported anywhere
- `src/alpha_to_execution_adapter_backup.py` - Backup file, not imported anywhere

**Action:** DELETE these files (verified no imports)

### 2. **Old Dashboard File** - Needs Consolidation ⚠️
- `src/pnl_dashboard.py` - Old dashboard (177KB, 3500+ lines)
  - **Still Used:** Only for `generate_executive_summary()` function
  - **Used By:** `pnl_dashboard_v2.py` (line 56, 1058)
  - **Action:** 
    1. Extract `generate_executive_summary()` function to v2
    2. Remove import from v2
    3. DELETE `pnl_dashboard.py` after verification

### 3. **Streamlit Dashboard** - Verify Status ⚠️
- `cockpit.py` - Streamlit dashboard (port 8501)
  - **Current:** User uses Flask/Dash dashboard on port 8050
  - **Status:** Need to verify if still needed
  - **Action:** Check if referenced in run.py or systemd

### 4. **Other Dashboard Files** - Verify Usage ⚠️
Multiple dashboard-related files found:
- `src/dashboard_app.py` (349KB) - May be old
- `src/cockpit_dashboard_generator.py`
- `src/dashboard_health_monitor.py`
- `src/dashboard_reconciliation.py`
- `src/dashboard_validator.py`
- `src/dashboard_verification.py`
- `src/phase8_trader_dashboard.py`
- `src/trading_performance_dashboard.py`
- `src/run_dashboard_health_check.py`

**Action:** Verify which are actually used vs deprecated

---

## Consolidation Plan

### Phase 1: Safe Removals (No Dependencies)
1. ✅ Delete `src/bot_cycle.backup.py`
2. ✅ Delete `src/alpha_to_execution_adapter_backup.py`

### Phase 2: Function Extraction
1. Extract `generate_executive_summary()` from `pnl_dashboard.py` to `pnl_dashboard_v2.py`
2. Update imports in `pnl_dashboard_v2.py`
3. Test dashboard works
4. Delete `pnl_dashboard.py`

### Phase 3: Dashboard File Audit
1. Check which dashboard files are actually imported/used
2. Remove unused dashboard files
3. Consolidate functionality if needed

### Phase 4: Verification
1. Test all imports work
2. Test dashboard functions
3. Verify no broken references

---

## Risk Assessment

### LOW RISK:
- Backup files (`.backup.py`) - No imports found
- Old dashboard file (after function extraction)

### MEDIUM RISK:
- `cockpit.py` - Need to verify if used
- Other dashboard files - Need usage audit

### HIGH RISK:
- None identified (all have clear paths forward)

---

## Next Steps

1. ✅ Identify files (done)
2. ⏳ Extract `generate_executive_summary()` function
3. ⏳ Remove backup files
4. ⏳ Audit other dashboard files
5. ⏳ Execute cleanup
6. ⏳ Test and verify

