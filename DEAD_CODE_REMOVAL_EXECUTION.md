# Dead Code Removal - Execution Plan

**Date:** 2025-12-27  
**Status:** Ready to Execute

---

## Summary of Findings

### ✅ SAFE TO DELETE (No Dependencies):
1. **`src/bot_cycle.backup.py`** - Backup file, no imports found
2. **`src/alpha_to_execution_adapter_backup.py`** - Backup file, no imports found

### ⚠️ NEEDS CONSOLIDATION:
1. **`src/pnl_dashboard.py`** (177KB) - Only used for `generate_executive_summary()` function
   - Used by: `pnl_dashboard_v2.py` (lines 56, 1058)
   - Action: Extract function to v2, then delete old file

### ❓ VERIFY USAGE:
1. **`cockpit.py`** - Streamlit dashboard (port 8501)
   - Status: NOT started in `run.py` (only pnl_dashboard_v2.py on port 8050)
   - Action: Verify not needed, then delete if unused

---

## Execution Plan

### Step 1: Delete Backup Files (IMMEDIATE) ✅
```bash
rm src/bot_cycle.backup.py
rm src/alpha_to_execution_adapter_backup.py
```

### Step 2: Extract `generate_executive_summary()` Function
- The function is large (~2000+ lines)
- Extract to `src/pnl_dashboard_v2.py` or create `src/executive_summary_generator.py`
- Update imports in `pnl_dashboard_v2.py`
- Test dashboard
- Delete `pnl_dashboard.py`

### Step 3: Verify cockpit.py Usage
- Check systemd services
- Check if referenced anywhere
- Delete if unused

---

## Why This Matters

**Old code causes:**
- Confusion about which files to modify
- Accidental references to deprecated code
- Maintenance burden
- Potential breakage if old code is modified

**Benefits of cleanup:**
- Clear codebase structure
- No ambiguity about which files are active
- Easier maintenance
- Prevents accidental use of deprecated code

