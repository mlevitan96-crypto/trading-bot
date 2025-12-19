#!/usr/bin/env python3
"""Test Dashboard V2 import and basic functionality"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

print("Testing Dashboard V2 import...")
print("="*60)

try:
    print("1. Importing start_pnl_dashboard...")
    from src.pnl_dashboard_v2 import start_pnl_dashboard
    print("   ✅ Import successful")
except ImportError as e:
    print(f"   ❌ ImportError: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)
except Exception as e:
    print(f"   ❌ Unexpected error: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

try:
    print("2. Testing build_app (without Flask server)...")
    from src.pnl_dashboard_v2 import build_app
    print("   ✅ build_app import successful")
    
    # Try to build app
    app = build_app(server=None)
    if app is None:
        print("   ❌ build_app returned None")
        sys.exit(1)
    print("   ✅ build_app returned Dash app instance")
except Exception as e:
    print(f"   ❌ Error building app: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

print("")
print("="*60)
print("✅ All tests passed!")
