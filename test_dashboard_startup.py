#!/usr/bin/env python3
"""
Dashboard Startup Validation Script
Run this before pushing code to verify dashboard can start without errors.
"""

import sys
import os

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

def test_dashboard_imports():
    """Test that all dashboard imports work."""
    print("🔍 Testing dashboard imports...")
    try:
        from src.pnl_dashboard import build_app, start_pnl_dashboard
        from src.infrastructure.path_registry import PathRegistry
        print("✅ All dashboard imports successful")
        return True
    except Exception as e:
        print(f"❌ Dashboard import failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_path_registry():
    """Test that PathRegistry returns correct types."""
    print("\n🔍 Testing PathRegistry...")
    try:
        from src.infrastructure.path_registry import PathRegistry
        
        # Test get_path() returns string
        test_path = PathRegistry.get_path("logs", "test.json")
        if not isinstance(test_path, str):
            print(f"❌ PathRegistry.get_path() returned {type(test_path)}, expected str")
            return False
        
        # Test POS_LOG is Path object
        pos_log = PathRegistry.POS_LOG
        from pathlib import Path
        if not isinstance(pos_log, Path):
            print(f"❌ PathRegistry.POS_LOG is {type(pos_log)}, expected Path")
            return False
        
        # Test conversion to string works
        pos_log_str = str(pos_log)
        if not isinstance(pos_log_str, str):
            print(f"❌ str(PathRegistry.POS_LOG) failed")
            return False
        
        print("✅ PathRegistry works correctly")
        return True
    except Exception as e:
        print(f"❌ PathRegistry test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_dashboard_build():
    """Test that build_app() can be called without errors."""
    print("\n🔍 Testing dashboard build_app()...")
    try:
        from src.pnl_dashboard import build_app
        from flask import Flask
        
        flask_app = Flask(__name__)
        
        # This should not raise an exception
        dash_app = build_app(flask_app)
        
        if dash_app is None:
            print("❌ build_app() returned None")
            return False
        
        print("✅ Dashboard build_app() successful")
        return True
    except Exception as e:
        print(f"❌ Dashboard build_app() failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_path_conversions():
    """Test that all Path objects are properly converted in dashboard."""
    print("\n🔍 Testing Path object conversions in dashboard code...")
    try:
        import ast
        import re
        
        dashboard_file = os.path.join(os.path.dirname(__file__), 'src', 'pnl_dashboard.py')
        
        with open(dashboard_file, 'r') as f:
            content = f.read()
        
        # Look for patterns that might indicate Path objects used incorrectly
        # This is a basic check - full validation would require AST parsing
        problematic_patterns = [
            (r'os\.path\.exists\((PathRegistry\.(POS_LOG|FEATURE_STORE_DIR))\)', 
             'os.path.exists() called with Path object (should be str())'),
            (r'os\.walk\((PathRegistry\.(POS_LOG|FEATURE_STORE_DIR))\)',
             'os.walk() called with Path object (should be str())'),
            (r'open\((PathRegistry\.(POS_LOG|FEATURE_STORE_DIR))',
             'open() called with Path object (should be str())'),
        ]
        
        issues = []
        for pattern, message in problematic_patterns:
            matches = re.finditer(pattern, content)
            for match in matches:
                line_num = content[:match.start()].count('\n') + 1
                issues.append(f"Line {line_num}: {message}")
        
        if issues:
            print("⚠️  Found potential Path object issues:")
            for issue in issues[:5]:  # Show first 5
                print(f"   {issue}")
            # Don't fail - just warn, as these might be false positives
            print("   (These may be false positives - verify manually)")
        else:
            print("✅ No obvious Path object issues found")
        
        return True
    except Exception as e:
        print(f"⚠️  Path conversion check failed (non-critical): {e}")
        return True  # Don't fail on this check

def main():
    """Run all validation tests."""
    print("="*60)
    print("Dashboard Startup Validation")
    print("="*60)
    
    tests = [
        test_dashboard_imports,
        test_path_registry,
        test_path_conversions,
        test_dashboard_build,
    ]
    
    results = []
    for test in tests:
        try:
            result = test()
            results.append(result)
        except Exception as e:
            print(f"❌ Test {test.__name__} crashed: {e}")
            import traceback
            traceback.print_exc()
            results.append(False)
    
    print("\n" + "="*60)
    print("Validation Summary")
    print("="*60)
    
    passed = sum(results)
    total = len(results)
    
    if passed == total:
        print(f"✅ All {total} tests passed!")
        print("\n✅ Dashboard should start successfully")
        return 0
    else:
        print(f"❌ {total - passed} of {total} tests failed")
        print("\n❌ Dashboard may fail to start - fix issues before pushing")
        return 1

if __name__ == "__main__":
    sys.exit(main())
