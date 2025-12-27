# Code Cleanup Analysis - Dead Code & Deprecated References

**Date:** 2025-12-27  
**Purpose:** Identify old code, unused labels, and deprecated references that should be removed

---

## Executive Summary

This analysis identifies code that is no longer needed and could cause confusion or breakage if referenced in the future.

---

## Identified Issues

### 1. **Old Dashboard Files**
- **`src/pnl_dashboard.py`** - Old dashboard (replaced by `pnl_dashboard_v2.py`)
  - Still imported in `pnl_dashboard_v2.py` for `generate_executive_summary`
  - Need to check if this function is the only dependency

### 2. **Streamlit Dashboard (`cockpit.py`)**
- **Status:** May be deprecated (user views Flask/Dash dashboard on port 8050)
- **Need to verify:** Is `cockpit.py` still used or can it be removed?

### 3. **Backup/Legacy Files**
- Files with `.backup`, `_old`, `_backup`, `_legacy` suffixes
- Need to identify and remove if truly unused

### 4. **Deprecated Imports**
- Old import paths that may reference removed modules
- Need to audit all imports

---

## Analysis Required

### Files to Check:
1. `src/pnl_dashboard.py` - Can functions be moved to v2?
2. `cockpit.py` - Still in use?
3. Backup files - Safe to remove?
4. Old import statements

### Actions Needed:
1. Verify what's actually used
2. Move needed functions to active files
3. Remove unused files
4. Update imports
5. Test system

---

## Next Steps

1. ✅ Analyze dependencies
2. ⏳ Identify safe removals
3. ⏳ Create cleanup plan
4. ⏳ Execute cleanup
5. ⏳ Test and verify

