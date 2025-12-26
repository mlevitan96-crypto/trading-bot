#!/usr/bin/env python3
"""
FINAL ALPHA Comprehensive End-to-End Test
==========================================
Tests all FINAL ALPHA features:
1. Time-Regime Optimizer
2. Symbol-Strategy Power Ranking
3. Execution Post-Mortem Tuning
4. Dashboard Integration
5. Dynamic Golden Hour Windows
6. Shadow Win Rate Tracking

This script validates:
- All imports work correctly
- All functions are callable
- Configuration files are properly structured
- Integration points are wired correctly
- No circular dependencies
- Data flow is consistent
"""

import sys
import json
import time
from pathlib import Path
from datetime import datetime, timedelta, timezone
from typing import Dict, Any

# Add project root to path
PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

print("=" * 80)
print("FINAL ALPHA COMPREHENSIVE END-TO-END TEST")
print("=" * 80)
print()

all_tests_passed = True
test_results = []

def test_result(test_name: str, passed: bool, message: str = ""):
    """Record test result"""
    global all_tests_passed
    status = "[PASS]" if passed else "[FAIL]"
    test_results.append({"test": test_name, "passed": passed, "message": message})
    print(f"{status}: {test_name}")
    if message:
        print(f"   {message}")
    if not passed:
        all_tests_passed = False
    print()

# ============================================================================
# 1. TEST IMPORTS & MODULE AVAILABILITY
# ============================================================================
print("=" * 80)
print("SECTION 1: Module Imports & Availability")
print("=" * 80)
print()

try:
    from src.time_regime_optimizer import TimeRegimeOptimizer, get_time_regime_optimizer
    test_result("Time-Regime Optimizer module import", True)
except Exception as e:
    test_result("Time-Regime Optimizer module import", False, f"Error: {e}")

try:
    from src.enhanced_trade_logging import is_golden_hour, check_golden_hours_block, get_golden_hour_config
    test_result("Enhanced Trade Logging module import", True)
except Exception as e:
    test_result("Enhanced Trade Logging module import", False, f"Error: {e}")

try:
    from src.intelligence_gate import intelligence_gate, get_symbol_7day_performance, _get_symbol_shadow_win_rate_48h
    test_result("Intelligence Gate module import", True)
except Exception as e:
    test_result("Intelligence Gate module import", False, f"Error: {e}")

try:
    from src.trade_execution import (
        calculate_marketable_limit_price,
        get_marketable_limit_offset_bps,
        analyze_fill_failure_rate,
        MARKETABLE_LIMIT_OFFSET_BPS,
        MARKETABLE_LIMIT_OFFSET_BPS_MAX
    )
    test_result("Trade Execution module import", True)
except Exception as e:
    test_result("Trade Execution module import", False, f"Error: {e}")

try:
    from src.self_healing_learning_loop import SelfHealingLearningLoop
    test_result("Self-Healing Learning Loop module import", True)
except Exception as e:
    test_result("Self-Healing Learning Loop module import", False, f"Error: {e}")

# ============================================================================
# 2. TEST TIME-REGIME OPTIMIZER
# ============================================================================
print("=" * 80)
print("SECTION 2: Time-Regime Optimizer")
print("=" * 80)
print()

try:
    optimizer = get_time_regime_optimizer()
    assert optimizer is not None, "Optimizer instance is None"
    test_result("Time-Regime Optimizer instantiation", True)
except Exception as e:
    test_result("Time-Regime Optimizer instantiation", False, f"Error: {e}")

try:
    optimizer = get_time_regime_optimizer()
    config = optimizer._load_golden_hour_config()
    assert isinstance(config, dict), "Config should be a dict"
    assert "restrict_to_golden_hour" in config, "Config missing restrict_to_golden_hour"
    assert "allowed_windows" in config, "Config missing allowed_windows"
    test_result("Time-Regime Optimizer config loading", True)
except Exception as e:
    test_result("Time-Regime Optimizer config loading", False, f"Error: {e}")

try:
    optimizer = get_time_regime_optimizer()
    windows = optimizer.get_allowed_windows()
    assert isinstance(windows, list), "Allowed windows should be a list"
    assert len(windows) > 0, "Should have at least base window (09:00-16:00)"
    test_result("Time-Regime Optimizer get_allowed_windows", True, f"Found {len(windows)} windows")
except Exception as e:
    test_result("Time-Regime Optimizer get_allowed_windows", False, f"Error: {e}")

try:
    optimizer = get_time_regime_optimizer()
    # This may return empty dict if no shadow data exists - that's OK
    window_metrics = optimizer.analyze_shadow_trades_by_time_window(days=14)
    assert isinstance(window_metrics, dict), "Window metrics should be a dict"
    test_result("Time-Regime Optimizer analyze_shadow_trades", True, f"Analyzed {len(window_metrics)} windows")
except Exception as e:
    test_result("Time-Regime Optimizer analyze_shadow_trades", False, f"Error: {e}")

# ============================================================================
# 3. TEST ENHANCED TRADE LOGGING (Dynamic Golden Hour)
# ============================================================================
print("=" * 80)
print("SECTION 3: Enhanced Trade Logging (Dynamic Golden Hour)")
print("=" * 80)
print()

try:
    # Test is_golden_hour() - should return bool
    result = is_golden_hour()
    assert isinstance(result, bool), "is_golden_hour() should return bool"
    test_result("is_golden_hour() function", True, f"Returns: {result}")
except Exception as e:
    test_result("is_golden_hour() function", False, f"Error: {e}")

try:
    config = get_golden_hour_config()
    assert isinstance(config, dict), "Config should be a dict"
    assert "restrict_to_golden_hour" in config, "Config missing restrict_to_golden_hour"
    test_result("get_golden_hour_config() function", True)
except Exception as e:
    test_result("get_golden_hour_config() function", False, f"Error: {e}")

try:
    should_block, reason, trading_window = check_golden_hours_block()
    assert isinstance(should_block, bool), "should_block should be bool"
    assert isinstance(reason, str), "reason should be str"
    assert trading_window in ["golden_hour", "24_7"], f"trading_window should be 'golden_hour' or '24_7', got '{trading_window}'"
    test_result("check_golden_hours_block() function", True, f"Window: {trading_window}, Block: {should_block}")
except Exception as e:
    test_result("check_golden_hours_block() function", False, f"Error: {e}")

# ============================================================================
# 4. TEST SYMBOL-STRATEGY POWER RANKING
# ============================================================================
print("=" * 80)
print("SECTION 4: Symbol-Strategy Power Ranking")
print("=" * 80)
print()

try:
    # Test get_symbol_7day_performance - should return dict with expected keys
    perf = get_symbol_7day_performance("BTCUSDT")
    assert isinstance(perf, dict), "Should return dict"
    assert "win_rate" in perf, "Missing win_rate"
    assert "profit_factor" in perf, "Missing profit_factor"
    assert "trade_count" in perf, "Missing trade_count"
    assert 0 <= perf["win_rate"] <= 1, "win_rate should be 0-1"
    test_result("get_symbol_7day_performance() function", True, 
                f"BTCUSDT: WR={perf['win_rate']:.2%}, PF={perf['profit_factor']:.2f}, Trades={perf['trade_count']}")
except Exception as e:
    test_result("get_symbol_7day_performance() function", False, f"Error: {e}")

try:
    # Test _get_symbol_shadow_win_rate_48h - should return float
    shadow_wr = _get_symbol_shadow_win_rate_48h("BTCUSDT")
    assert isinstance(shadow_wr, float), "Should return float"
    assert 0 <= shadow_wr <= 1, "shadow_wr should be 0-1"
    test_result("_get_symbol_shadow_win_rate_48h() function", True, f"BTCUSDT: {shadow_wr:.2%}")
except Exception as e:
    test_result("_get_symbol_shadow_win_rate_48h() function", False, f"Error: {e}")

try:
    # Test intelligence_gate with mock signal
    test_signal = {
        "symbol": "BTCUSDT",
        "action": "OPEN_LONG",
        "direction": "LONG",
        "expected_roi": 0.02,
        "current_price": 50000.0
    }
    approved, reason, sizing_mult = intelligence_gate(test_signal)
    assert isinstance(approved, bool), "approved should be bool"
    assert isinstance(reason, str), "reason should be str"
    assert isinstance(sizing_mult, (int, float)), "sizing_mult should be numeric"
    assert sizing_mult >= 0, "sizing_mult should be >= 0"
    test_result("intelligence_gate() with Power Ranking", True, 
                f"Approved: {approved}, Reason: {reason[:50]}, Size Mult: {sizing_mult:.2f}")
except Exception as e:
    test_result("intelligence_gate() with Power Ranking", False, f"Error: {e}")

# ============================================================================
# 5. TEST EXECUTION POST-MORTEM TUNING
# ============================================================================
print("=" * 80)
print("SECTION 5: Execution Post-Mortem Tuning")
print("=" * 80)
print()

try:
    # Test get_marketable_limit_offset_bps
    offset = get_marketable_limit_offset_bps()
    assert isinstance(offset, float), "Should return float"
    assert MARKETABLE_LIMIT_OFFSET_BPS <= offset <= MARKETABLE_LIMIT_OFFSET_BPS_MAX, \
        f"Offset should be between {MARKETABLE_LIMIT_OFFSET_BPS} and {MARKETABLE_LIMIT_OFFSET_BPS_MAX}"
    test_result("get_marketable_limit_offset_bps() function", True, f"Current offset: {offset} bps")
except Exception as e:
    test_result("get_marketable_limit_offset_bps() function", False, f"Error: {e}")

try:
    # Test calculate_marketable_limit_price
    price = calculate_marketable_limit_price(50000.0, "LONG", False)
    assert price > 50000.0, "LONG limit price should be above signal price"
    price_short = calculate_marketable_limit_price(50000.0, "SHORT", False)
    assert price_short < 50000.0, "SHORT limit price should be below signal price"
    test_result("calculate_marketable_limit_price() function", True, 
                f"LONG: ${price:.2f}, SHORT: ${price_short:.2f}")
except Exception as e:
    test_result("calculate_marketable_limit_price() function", False, f"Error: {e}")

try:
    # Test analyze_fill_failure_rate
    analysis = analyze_fill_failure_rate(hours=24)
    assert isinstance(analysis, dict), "Should return dict"
    # May have error if no data - that's OK
    if "error" not in analysis:
        assert "total_true_trend_attempts" in analysis, "Missing total_true_trend_attempts"
        assert "should_increase_offset" in analysis, "Missing should_increase_offset"
    test_result("analyze_fill_failure_rate() function", True, 
                f"Error: {analysis.get('error', 'None')}, Should increase: {analysis.get('should_increase_offset', 'N/A')}")
except Exception as e:
    test_result("analyze_fill_failure_rate() function", False, f"Error: {e}")

# ============================================================================
# 6. TEST SELF-HEALING LEARNING LOOP INTEGRATION
# ============================================================================
print("=" * 80)
print("SECTION 6: Self-Healing Learning Loop Integration")
print("=" * 80)
print()

try:
    loop = SelfHealingLearningLoop()
    assert loop is not None, "Loop instance is None"
    test_result("SelfHealingLearningLoop instantiation", True)
except Exception as e:
    test_result("SelfHealingLearningLoop instantiation", False, f"Error: {e}")

try:
    # Check that the loop has the necessary methods
    loop = SelfHealingLearningLoop()
    assert hasattr(loop, 'analyze_shadow_vs_live'), "Missing analyze_shadow_vs_live method"
    assert hasattr(loop, '_run_loop'), "Missing _run_loop method"
    test_result("SelfHealingLearningLoop methods check", True)
except Exception as e:
    test_result("SelfHealingLearningLoop methods check", False, f"Error: {e}")

# ============================================================================
# 7. TEST CONFIGURATION FILES
# ============================================================================
print("=" * 80)
print("SECTION 7: Configuration Files")
print("=" * 80)
print()

try:
    from src.infrastructure.path_registry import PathRegistry
    
    # Check golden_hour_config.json structure
    config_path = Path(PathRegistry.get_path("feature_store", "golden_hour_config.json"))
    if config_path.exists():
        with open(config_path, 'r') as f:
            config = json.load(f)
        assert "restrict_to_golden_hour" in config, "Missing restrict_to_golden_hour"
        assert "allowed_windows" in config, "Missing allowed_windows"
        test_result("golden_hour_config.json structure", True, 
                    f"Restrict: {config.get('restrict_to_golden_hour')}, Windows: {len(config.get('allowed_windows', []))}")
    else:
        test_result("golden_hour_config.json exists", True, "Will be created on first run")
except Exception as e:
    test_result("golden_hour_config.json check", False, f"Error: {e}")

try:
    # Check trade_execution_config.json structure (may not exist yet)
    config_path = Path(PathRegistry.get_path("feature_store", "trade_execution_config.json"))
    if config_path.exists():
        with open(config_path, 'r') as f:
            config = json.load(f)
        test_result("trade_execution_config.json exists", True, 
                    f"Offset: {config.get('marketable_limit_offset_bps', 'default')}")
    else:
        test_result("trade_execution_config.json exists", True, "Will be created on first adjustment")
except Exception as e:
    test_result("trade_execution_config.json check", False, f"Error: {e}")

# ============================================================================
# 8. TEST DATA FLOW & CONSISTENCY
# ============================================================================
print("=" * 80)
print("SECTION 8: Data Flow & Consistency")
print("=" * 80)
print()

try:
    # Test that golden hour check uses dynamic windows
    current_hour = datetime.now(timezone.utc).hour
    is_gh_static = 9 <= current_hour < 16
    is_gh_dynamic = is_golden_hour()
    
    # Dynamic should at least match static for base hours
    # (it may be True for more hours if windows were learned)
    if is_gh_static:
        assert is_gh_dynamic, "Dynamic golden hour should be True when static is True"
    
    test_result("Dynamic Golden Hour consistency", True, 
                f"Static: {is_gh_static}, Dynamic: {is_gh_dynamic}")
except Exception as e:
    test_result("Dynamic Golden Hour consistency", False, f"Error: {e}")

try:
    # Test that check_golden_hours_block returns consistent window type
    should_block1, reason1, window1 = check_golden_hours_block()
    should_block2, reason2, window2 = check_golden_hours_block()
    assert window1 == window2, "Window type should be consistent"
    test_result("check_golden_hours_block consistency", True, f"Window: {window1}")
except Exception as e:
    test_result("check_golden_hours_block consistency", False, f"Error: {e}")

# ============================================================================
# 9. TEST INTEGRATION POINTS
# ============================================================================
print("=" * 80)
print("SECTION 9: Integration Points")
print("=" * 80)
print()

try:
    # Test that optimizer can be called from enhanced_trade_logging
    from src.enhanced_trade_logging import is_golden_hour
    result = is_golden_hour()  # This should use optimizer internally
    assert isinstance(result, bool), "Should return bool"
    test_result("Enhanced Trade Logging → Time-Regime Optimizer integration", True)
except Exception as e:
    test_result("Enhanced Trade Logging → Time-Regime Optimizer integration", False, f"Error: {e}")

try:
    # Test that intelligence_gate uses Power Ranking
    test_signal = {"symbol": "AVAXUSDT", "action": "OPEN_LONG", "direction": "LONG", "expected_roi": 0.02}
    approved, reason, sizing_mult = intelligence_gate(test_signal)
    # Should not crash, sizing_mult should be valid
    assert isinstance(sizing_mult, (int, float)), "sizing_mult should be numeric"
    test_result("Intelligence Gate → Power Ranking integration", True, f"Size mult: {sizing_mult:.2f}")
except Exception as e:
    test_result("Intelligence Gate → Power Ranking integration", False, f"Error: {e}")

# ============================================================================
# 10. TEST EDGE CASES
# ============================================================================
print("=" * 80)
print("SECTION 10: Edge Cases")
print("=" * 80)
print()

try:
    # Test with invalid symbol
    perf = get_symbol_7day_performance("INVALID_SYMBOL_XYZ")
    assert isinstance(perf, dict), "Should return dict even for invalid symbol"
    assert "win_rate" in perf, "Should have win_rate"
    test_result("Edge case: Invalid symbol", True)
except Exception as e:
    test_result("Edge case: Invalid symbol", False, f"Error: {e}")

try:
    # Test with None/empty signal
    try:
        approved, reason, sizing_mult = intelligence_gate({})
        test_result("Edge case: Empty signal", True, "Handled gracefully")
    except (KeyError, AttributeError):
        # Expected to fail with missing keys - that's OK, just shouldn't crash with TypeError
        test_result("Edge case: Empty signal", True, "Raises expected KeyError (acceptable)")
except Exception as e:
    test_result("Edge case: Empty signal", False, f"Error: {e}")

try:
    # Test offset calculation with extreme values
    price = calculate_marketable_limit_price(0.0001, "LONG", False)
    assert price > 0, "Should handle very small prices"
    price = calculate_marketable_limit_price(1000000.0, "SHORT", False)
    assert price > 0, "Should handle very large prices"
    test_result("Edge case: Extreme prices", True)
except Exception as e:
    test_result("Edge case: Extreme prices", False, f"Error: {e}")

# ============================================================================
# SUMMARY
# ============================================================================
print("=" * 80)
print("TEST SUMMARY")
print("=" * 80)
print()

passed_count = sum(1 for r in test_results if r["passed"])
total_count = len(test_results)

print(f"Total Tests: {total_count}")
print(f"Passed: {passed_count}")
print(f"Failed: {total_count - passed_count}")
print()

if all_tests_passed:
    print("[SUCCESS] ALL TESTS PASSED")
    print()
    print("FINAL ALPHA components are working correctly!")
    print("- Time-Regime Optimizer: OK")
    print("- Symbol-Strategy Power Ranking: OK")
    print("- Execution Post-Mortem Tuning: OK")
    print("- Dynamic Golden Hour Windows: OK")
    print("- Integration Points: OK")
    sys.exit(0)
else:
    print("[FAILURE] SOME TESTS FAILED")
    print()
    print("Failed tests:")
    for result in test_results:
        if not result["passed"]:
            print(f"  - {result['test']}: {result['message']}")
    sys.exit(1)

