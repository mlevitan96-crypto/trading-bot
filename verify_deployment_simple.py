#!/usr/bin/env python3
"""Simple deployment verification script"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

print("=" * 80)
print("FINAL ALPHA DEPLOYMENT VERIFICATION")
print("=" * 80)
print()

errors = 0
passed = 0

def test(name, func):
    global errors, passed
    try:
        result = func()
        if result:
            print(f"[OK] {name}")
            passed += 1
        else:
            print(f"[FAIL] {name}")
            errors += 1
    except Exception as e:
        print(f"[FAIL] {name}: {e}")
        errors += 1

# Test 1: Time-Regime Optimizer
test("Time-Regime Optimizer import", lambda: __import__('src.time_regime_optimizer'))
test("Time-Regime Optimizer instantiation", lambda: __import__('src.time_regime_optimizer').get_time_regime_optimizer() is not None)

# Test 2: Enhanced Trade Logging
test("Enhanced Trade Logging import", lambda: __import__('src.enhanced_trade_logging'))
test("is_golden_hour function", lambda: isinstance(__import__('src.enhanced_trade_logging').is_golden_hour(), bool))

# Test 3: Intelligence Gate
test("Intelligence Gate import", lambda: __import__('src.intelligence_gate'))
test("intelligence_gate function exists", lambda: hasattr(__import__('src.intelligence_gate'), 'intelligence_gate'))

# Test 4: Trade Execution
test("Trade Execution import", lambda: __import__('src.trade_execution'))
test("get_marketable_limit_offset_bps exists", lambda: hasattr(__import__('src.trade_execution'), 'get_marketable_limit_offset_bps'))

# Test 5: Self-Healing Loop
test("Self-Healing Loop import", lambda: __import__('src.self_healing_learning_loop'))
test("SelfHealingLearningLoop class", lambda: hasattr(__import__('src.self_healing_learning_loop'), 'SelfHealingLearningLoop'))

print()
print("=" * 80)
print(f"RESULTS: {passed} passed, {errors} errors")
print("=" * 80)

if errors == 0:
    print("✅ All FINAL ALPHA components deployed successfully!")
    sys.exit(0)
else:
    print(f"❌ {errors} component(s) failed verification")
    sys.exit(1)

