#!/usr/bin/env python3
"""Quick verification script for Phase 5 & 6 deployment"""

import sys

print("=" * 70)
print("PHASE 5 & 6 DEPLOYMENT VERIFICATION")
print("=" * 70)

all_ok = True

# Test 1: Trade Execution module
try:
    from src.trade_execution import (
        calculate_marketable_limit_price,
        calculate_slippage_bps,
        get_recent_slippage_stats
    )
    price = calculate_marketable_limit_price(50000.0, "LONG", False)
    assert price > 50000.0
    print("✅ Phase 5: Trade Execution module - OK")
except Exception as e:
    print(f"❌ Phase 5: Trade Execution module - FAIL: {e}")
    all_ok = False

# Test 2: Exhaustion Exit
try:
    from src.futures_ladder_exits import check_exhaustion_exit
    result = check_exhaustion_exit("BTCUSDT", "LONG")
    assert isinstance(result, tuple) and len(result) == 2
    print("✅ Phase 5: Exhaustion Exit - OK")
except Exception as e:
    print(f"❌ Phase 5: Exhaustion Exit - FAIL: {e}")
    all_ok = False

# Test 3: Symbol Alpha Floor
try:
    from src.intelligence_gate import get_symbol_7day_performance
    perf = get_symbol_7day_performance("BTCUSDT")
    assert "win_rate" in perf and "profit_factor" in perf
    print("✅ Phase 6: Symbol Alpha Floor - OK")
except Exception as e:
    print(f"❌ Phase 6: Symbol Alpha Floor - FAIL: {e}")
    all_ok = False

# Test 4: FeeAwareGate Symbol-Specific Multiplier
try:
    from src.fee_aware_gate import FeeAwareGate
    gate = FeeAwareGate()
    mult = gate._get_symbol_buffer_multiplier("BTCUSDT")
    assert isinstance(mult, (int, float)) and mult >= 1.0
    print(f"✅ Phase 5: FeeAwareGate Symbol Multiplier - OK (default: {mult})")
except Exception as e:
    print(f"❌ Phase 5: FeeAwareGate Symbol Multiplier - FAIL: {e}")
    all_ok = False

# Test 5: Slippage Audit Analysis
try:
    from src.self_healing_learning_loop import SelfHealingLearningLoop
    loop = SelfHealingLearningLoop()
    assert hasattr(loop, "_analyze_slippage_and_update_fee_gates")
    # Don't actually run it (might take time), just verify method exists
    print("✅ Phase 5: Slippage Audit Analysis method - OK")
except Exception as e:
    print(f"❌ Phase 5: Slippage Audit Analysis - FAIL: {e}")
    all_ok = False

# Test 6: Dashboard components
try:
    from src.trade_execution import get_recent_slippage_stats
    stats = get_recent_slippage_stats(hours=24)
    assert isinstance(stats, dict)
    print("✅ Dashboard: Can access slippage stats - OK")
except Exception as e:
    print(f"❌ Dashboard: Slippage stats access - FAIL: {e}")
    all_ok = False

print("=" * 70)
if all_ok:
    print("✅ ALL VERIFICATIONS PASSED")
    sys.exit(0)
else:
    print("❌ SOME VERIFICATIONS FAILED")
    sys.exit(1)

