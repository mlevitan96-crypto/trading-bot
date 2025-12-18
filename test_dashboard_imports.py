#!/usr/bin/env python3
"""Test dashboard imports to find missing dependencies"""

import sys
from pathlib import Path as PathTest

# Test if all critical imports work
try:
    print("Testing imports...")
    from pathlib import Path
    print("✅ Path imported")
    
    import src.pnl_dashboard as dashboard
    print("✅ Dashboard module imported")
    
    # Test Path is available
    test_path = Path("test")
    print(f"✅ Path object works: {test_path}")
    
    print("\n✅ All imports successful!")
except Exception as e:
    print(f"❌ Import error: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)
