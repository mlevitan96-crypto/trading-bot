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
from src.time_regime_optimizer import get_time_regime_optimizer
test("Time-Regime Optimizer instantiation", lambda: get_time_regime_optimizer() is not None)

# Test 2: Enhanced Trade Logging
test("Enhanced Trade Logging import", lambda: __import__('src.enhanced_trade_logging'))
from src.enhanced_trade_logging import is_golden_hour
test("is_golden_hour function", lambda: isinstance(is_golden_hour(), bool))

# Test 3: Intelligence Gate
test("Intelligence Gate import", lambda: __import__('src.intelligence_gate'))
from src.intelligence_gate import intelligence_gate
test("intelligence_gate function exists", lambda: callable(intelligence_gate))

# Test 4: Trade Execution
test("Trade Execution import", lambda: __import__('src.trade_execution'))
from src.trade_execution import get_marketable_limit_offset_bps
test("get_marketable_limit_offset_bps exists", lambda: callable(get_marketable_limit_offset_bps))

# Test 5: Self-Healing Loop
test("Self-Healing Loop import", lambda: __import__('src.self_healing_learning_loop'))
from src.self_healing_learning_loop import SelfHealingLearningLoop
test("SelfHealingLearningLoop class", lambda: SelfHealingLearningLoop is not None)

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

