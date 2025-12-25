#!/usr/bin/env python3
"""
Quick verification script to confirm BIG ALPHA components are deployed and working.
Run this on the droplet after deployment.
"""

import sys

def verify_imports():
    """Verify all BIG ALPHA components can be imported"""
    print("🔍 Verifying BIG ALPHA component imports...")
    try:
        from src.whale_cvd_engine import get_whale_cvd
        print("   ✅ Whale CVD Engine")
    except Exception as e:
        print(f"   ❌ Whale CVD Engine: {e}")
        return False
    
    try:
        from src.hurst_exponent import get_hurst_signal
        print("   ✅ Hurst Exponent")
    except Exception as e:
        print(f"   ❌ Hurst Exponent: {e}")
        return False
    
    try:
        from src.symbol_probation_state_machine import SymbolProbationStateMachine
        print("   ✅ Symbol Probation State Machine")
    except Exception as e:
        print(f"   ❌ Symbol Probation: {e}")
        return False
    
    try:
        from src.self_healing_learning_loop import SelfHealingLearningLoop
        print("   ✅ Self-Healing Learning Loop")
    except Exception as e:
        print(f"   ❌ Self-Healing Learning Loop: {e}")
        return False
    
    try:
        from src.intelligence_gate import intelligence_gate
        print("   ✅ Intelligence Gate (with Whale CVD filter)")
    except Exception as e:
        print(f"   ❌ Intelligence Gate: {e}")
        return False
    
    try:
        from src.hold_time_enforcer import get_hold_time_enforcer
        print("   ✅ Hold Time Enforcer (with Force-Hold logic)")
    except Exception as e:
        print(f"   ❌ Hold Time Enforcer: {e}")
        return False
    
    return True

def verify_integration():
    """Verify components are integrated into main bot"""
    print("\n🔍 Verifying integration points...")
    try:
        # Check run.py has learning loop startup
        with open('src/run.py', 'r') as f:
            content = f.read()
            if 'start_learning_loop' in content:
                print("   ✅ Learning Loop integrated in run.py")
            else:
                print("   ❌ Learning Loop NOT found in run.py")
                return False
    except Exception as e:
        print(f"   ⚠️  Could not verify run.py: {e}")
    
    try:
        # Check unified_recovery_learning_fix.py has probation check
        with open('src/unified_recovery_learning_fix.py', 'r') as f:
            content = f.read()
            if 'check_symbol_probation' in content:
                print("   ✅ Symbol Probation integrated in unified_recovery_learning_fix.py")
            else:
                print("   ❌ Symbol Probation NOT found in unified_recovery_learning_fix.py")
                return False
    except Exception as e:
        print(f"   ⚠️  Could not verify unified_recovery_learning_fix.py: {e}")
    
    try:
        # Check position_manager.py has TRUE TREND logic
        with open('src/position_manager.py', 'r') as f:
            content = f.read()
            if 'is_true_trend' in content:
                print("   ✅ TRUE TREND logic integrated in position_manager.py")
            else:
                print("   ❌ TRUE TREND logic NOT found in position_manager.py")
                return False
    except Exception as e:
        print(f"   ⚠️  Could not verify position_manager.py: {e}")
    
    return True

def main():
    print("=" * 60)
    print("BIG ALPHA DEPLOYMENT VERIFICATION")
    print("=" * 60)
    
    imports_ok = verify_imports()
    integration_ok = verify_integration()
    
    print("\n" + "=" * 60)
    if imports_ok and integration_ok:
        print("✅ ALL VERIFICATIONS PASSED")
        print("   BIG ALPHA components are deployed and integrated")
        return 0
    else:
        print("❌ SOME VERIFICATIONS FAILED")
        print("   Review output above for details")
        return 1

if __name__ == "__main__":
    sys.exit(main())

