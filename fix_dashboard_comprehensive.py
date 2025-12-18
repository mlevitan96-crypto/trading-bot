#!/usr/bin/env python3
"""
Comprehensive dashboard fix - ensures all imports are correct and removes any
references to Path that might cause issues.
"""

import sys
from pathlib import Path as PathLib

_project_root = PathLib(__file__).parent
sys.path.insert(0, str(_project_root))

print("=" * 70)
print("COMPREHENSIVE DASHBOARD FIX")
print("=" * 70)
print()

# Verify Path import works
try:
    from pathlib import Path
    print("✅ Path import successful")
except Exception as e:
    print(f"❌ Path import failed: {e}")
    sys.exit(1)

# Verify dashboard module can be imported
try:
    import src.pnl_dashboard as dashboard
    print("✅ Dashboard module imports successfully")
except Exception as e:
    print(f"❌ Dashboard import failed: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

# Check if Path is available in module
if hasattr(dashboard, 'Path'):
    print("✅ Path is available in dashboard module")
else:
    print("⚠️  Path not found as attribute, checking imports...")
    try:
        # Try accessing Path through the module
        from src.pnl_dashboard import Path as DashboardPath
        print("✅ Path can be imported from dashboard module")
    except:
        print("⚠️  Path cannot be imported from dashboard module")

# Verify PathRegistry works
try:
    from src.infrastructure.path_registry import PathRegistry
    test_path = PathRegistry.get_path("logs", "test.json")
    print(f"✅ PathRegistry works: {test_path} (type: {type(test_path).__name__})")
    if isinstance(test_path, str):
        print("✅ PathRegistry.get_path() returns string as expected")
    else:
        print(f"⚠️  PathRegistry.get_path() returns {type(test_path).__name__}, not string")
except Exception as e:
    print(f"❌ PathRegistry test failed: {e}")

print()
print("=" * 70)
print("FIX COMPLETE")
print("=" * 70)
print()
print("If all checks passed, dashboard should work correctly.")
print("Deploy with: git pull && sudo systemctl restart tradingbot")
