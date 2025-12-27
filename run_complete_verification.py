#!/usr/bin/env python3
"""
Complete Systems Verification Script
====================================
Runs all verification checks for autonomous brain integration and system readiness.
Can be run on droplet to verify everything is working.
"""

import sys
import subprocess
import importlib.util
from pathlib import Path

def run_verification(script_path: str, description: str) -> tuple:
    """Run a verification script and return (success, output)."""
    print(f"\n{'='*70}")
    print(f"RUNNING: {description}")
    print(f"{'='*70}")
    
    if not Path(script_path).exists():
        return (False, f"Script not found: {script_path}")
    
    try:
        result = subprocess.run(
            [sys.executable, script_path],
            capture_output=True,
            text=True,
            timeout=60
        )
        
        if result.returncode == 0:
            print(result.stdout)
            return (True, result.stdout)
        else:
            print(result.stderr)
            return (False, result.stderr)
    except subprocess.TimeoutExpired:
        return (False, "Script timed out after 60 seconds")
    except Exception as e:
        return (False, f"Error running script: {e}")

def check_code_verification():
    """Run code pattern verification."""
    return run_verification(
        "verify_integration_code.py",
        "Integration Code Pattern Verification"
    )

def check_imports():
    """Check if all required modules can be imported."""
    print(f"\n{'='*70}")
    print("CHECKING: Python Module Imports")
    print(f"{'='*70}")
    
    required_modules = [
        "src.regime_classifier",
        "src.shadow_execution_engine",
        "src.policy_tuner",
        "src.feature_drift_detector",
        "src.adaptive_signal_optimizer"
    ]
    
    optional_modules = [
        "numpy",
        "hmmlearn",
        "optuna",
        "schedule"
    ]
    
    all_good = True
    
    for module in required_modules:
        try:
            importlib.import_module(module)
            print(f"  OK: {module}")
        except ImportError as e:
            print(f"  FAIL: {module} - {e}")
            all_good = False
        except Exception as e:
            print(f"  ERROR: {module} - {e}")
            all_good = False
    
    print("\n  Optional dependencies:")
    for module in optional_modules:
        try:
            importlib.import_module(module)
            print(f"    OK: {module}")
        except ImportError:
            print(f"    MISSING: {module} (may need: pip install {module})")
    
    return all_good

def check_file_structure():
    """Check that all required files exist."""
    print(f"\n{'='*70}")
    print("CHECKING: File Structure")
    print(f"{'='*70}")
    
    required_files = [
        "src/regime_classifier.py",
        "src/shadow_execution_engine.py",
        "src/policy_tuner.py",
        "src/feature_drift_detector.py",
        "src/adaptive_signal_optimizer.py",
        "src/run.py",
        "src/bot_cycle.py",
        "src/unified_stack.py",
        "src/conviction_gate.py",
        "verify_integration_code.py"
    ]
    
    all_exist = True
    for filepath in required_files:
        path = Path(filepath)
        if path.exists():
            print(f"  OK: {filepath}")
        else:
            print(f"  MISSING: {filepath}")
            all_exist = False
    
    return all_exist

def check_service_status():
    """Check if trading bot service is running (if on droplet)."""
    print(f"\n{'='*70}")
    print("CHECKING: Service Status")
    print(f"{'='*70}")
    
    try:
        result = subprocess.run(
            ["systemctl", "status", "tradingbot", "--no-pager"],
            capture_output=True,
            text=True,
            timeout=5
        )
        
        if result.returncode == 0:
            print(result.stdout)
            if "active (running)" in result.stdout:
                print("\n  OK: Service is running")
                return True
            else:
                print("\n  WARNING: Service exists but not running")
                return False
        else:
            # Try alternative service name
            result2 = subprocess.run(
                ["systemctl", "status", "trading-bot", "--no-pager"],
                capture_output=True,
                text=True,
                timeout=5
            )
            if result2.returncode == 0:
                print(result2.stdout)
                if "active (running)" in result2.stdout:
                    print("\n  OK: Service is running (trading-bot)")
                    return True
            print("\n  INFO: Service check not available (may not be on droplet)")
            return None
    except FileNotFoundError:
        print("  INFO: systemctl not available (not on droplet)")
        return None
    except Exception as e:
        print(f"  INFO: Could not check service: {e}")
        return None

def main():
    """Run all verification checks."""
    print("="*70)
    print("COMPLETE SYSTEMS VERIFICATION")
    print("="*70)
    print("This script verifies:")
    print("  1. Code pattern integration")
    print("  2. Python module imports")
    print("  3. File structure")
    print("  4. Service status (if on droplet)")
    print()
    
    results = []
    
    # 1. Code verification
    success, output = check_code_verification()
    results.append(("Code Pattern Verification", success))
    
    # 2. File structure
    file_check = check_file_structure()
    results.append(("File Structure", file_check))
    
    # 3. Module imports
    import_check = check_imports()
    results.append(("Module Imports", import_check))
    
    # 4. Service status (optional - only on droplet)
    service_check = check_service_status()
    if service_check is not None:
        results.append(("Service Status", service_check))
    
    # Summary
    print("\n" + "="*70)
    print("VERIFICATION SUMMARY")
    print("="*70)
    
    passed = sum(1 for _, success in results if success)
    total = len(results)
    
    for name, success in results:
        status = "PASS" if success else "FAIL"
        print(f"{status}: {name}")
    
    print()
    print(f"Total: {total} checks")
    print(f"Passed: {passed}")
    print(f"Failed: {total - passed}")
    print("="*70)
    
    if passed == total:
        print("\nSUCCESS: All verifications passed!")
        return 0
    else:
        print("\nWARNING: Some verifications failed - review above")
        return 1

if __name__ == "__main__":
    sys.exit(main())

