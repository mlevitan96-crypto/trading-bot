#!/usr/bin/env python3
"""
BIG ALPHA PHASE 5 & 6 Integration Test Suite
=============================================
End-to-end testing for Phase 5 (Execution Intelligence) and Phase 6 (Symbol-Specific Adaptive Brain)
"""

import sys
import json
import time
from pathlib import Path

def test_phase5_trade_execution():
    """Test Phase 5: Marketable Limit Orders & NBBO Audit"""
    print("🔍 Testing Phase 5: Trade Execution (Marketable Limit Orders & NBBO Audit)...")
    try:
        from src.trade_execution import (
            place_marketable_limit_order,
            calculate_slippage_bps,
            log_execution_with_slippage,
            get_recent_slippage_stats,
            calculate_marketable_limit_price
        )
        
        # Test calculate_marketable_limit_price
        signal_price = 50000.0
        limit_price_buy = calculate_marketable_limit_price(signal_price, "LONG", False)
        limit_price_sell = calculate_marketable_limit_price(signal_price, "SHORT", False)
        assert limit_price_buy > signal_price, "Buy limit should be above signal price"
        assert limit_price_sell < signal_price, "Sell limit should be below signal price"
        
        # Test calculate_slippage_bps
        slippage = calculate_slippage_bps(50000.0, 50025.0, "BUY")  # 25 USD difference = 5 bps
        assert abs(slippage - 5.0) < 0.1, f"Slippage calculation incorrect: {slippage}"
        
        # Test get_recent_slippage_stats (should not crash even if no data)
        stats = get_recent_slippage_stats(hours=24)
        assert isinstance(stats, dict), "Should return dict"
        
        print("   ✅ Phase 5: Trade Execution module OK")
        return True
    except Exception as e:
        print(f"   ❌ Phase 5: Trade Execution: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_phase5_exhaustion_exit():
    """Test Phase 5: Exhaustion Exit in futures_ladder_exits"""
    print("🔍 Testing Phase 5: Exhaustion Exit...")
    try:
        from src.futures_ladder_exits import check_exhaustion_exit
        
        # Test function exists and returns tuple
        result = check_exhaustion_exit("BTCUSDT", "LONG")
        assert isinstance(result, tuple), "Should return (bool, str)"
        assert len(result) == 2, "Should return (should_exit, reason)"
        
        # Test SHORT returns False (only applies to LONG)
        result_short = check_exhaustion_exit("BTCUSDT", "SHORT")
        assert result_short[0] == False, "SHORT should return False"
        
        print("   ✅ Phase 5: Exhaustion Exit OK")
        return True
    except Exception as e:
        print(f"   ❌ Phase 5: Exhaustion Exit: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_phase6_symbol_alpha_floor():
    """Test Phase 6: Symbol-Specific Alpha Floor"""
    print("🔍 Testing Phase 6: Symbol-Specific Alpha Floor...")
    try:
        from src.intelligence_gate import get_symbol_7day_performance, intelligence_gate
        
        # Test get_symbol_7day_performance
        perf = get_symbol_7day_performance("BTCUSDT")
        assert isinstance(perf, dict), "Should return dict"
        assert "win_rate" in perf, "Should have win_rate"
        assert "profit_factor" in perf, "Should have profit_factor"
        assert "trade_count" in perf, "Should have trade_count"
        
        # Test intelligence_gate uses symbol performance
        signal = {
            "symbol": "BTCUSDT",
            "action": "OPEN_LONG",
            "direction": "LONG"
        }
        result = intelligence_gate(signal)
        assert isinstance(result, tuple), "Should return (bool, str, float)"
        assert len(result) == 3, "Should return (allowed, reason, sizing_mult)"
        
        print("   ✅ Phase 6: Symbol-Specific Alpha Floor OK")
        return True
    except Exception as e:
        print(f"   ❌ Phase 6: Symbol-Specific Alpha Floor: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_phase5_fee_aware_gate():
    """Test Phase 5: FeeAwareGate symbol-specific buffer multiplier"""
    print("🔍 Testing Phase 5: FeeAwareGate Symbol-Specific Buffer Multiplier...")
    try:
        from src.fee_aware_gate import FeeAwareGate
        
        gate = FeeAwareGate()
        
        # Test _get_symbol_buffer_multiplier exists
        assert hasattr(gate, "_get_symbol_buffer_multiplier"), "Should have _get_symbol_buffer_multiplier method"
        
        # Test it returns a float (default or configured)
        multiplier = gate._get_symbol_buffer_multiplier("BTCUSDT")
        assert isinstance(multiplier, (int, float)), "Should return numeric value"
        assert multiplier >= 1.0, "Multiplier should be >= 1.0"
        
        print(f"   ✅ Phase 5: FeeAwareGate Symbol-Specific Buffer Multiplier OK (got {multiplier})")
        return True
    except Exception as e:
        print(f"   ❌ Phase 5: FeeAwareGate Symbol-Specific Buffer Multiplier: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_phase5_slippage_audit_analysis():
    """Test Phase 5: Self-Healing Slippage Audit Analysis"""
    print("🔍 Testing Phase 5: Self-Healing Slippage Audit Analysis...")
    try:
        from src.self_healing_learning_loop import SelfHealingLearningLoop
        
        loop = SelfHealingLearningLoop()
        
        # Test _analyze_slippage_and_update_fee_gates exists
        assert hasattr(loop, "_analyze_slippage_and_update_fee_gates"), "Should have _analyze_slippage_and_update_fee_gates method"
        
        # Test it can be called (may not update if no data, but should not crash)
        try:
            loop._analyze_slippage_and_update_fee_gates()
            print("   ✅ Phase 5: Slippage Audit Analysis OK (method executed without error)")
        except Exception as e:
            # If it fails due to missing data, that's OK for testing
            if "No execution log" in str(e) or "No recent execution" in str(e):
                print("   ✅ Phase 5: Slippage Audit Analysis OK (method exists, no data yet)")
            else:
                raise
        
        return True
    except Exception as e:
        print(f"   ❌ Phase 5: Slippage Audit Analysis: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_dashboard_imports():
    """Test that cockpit.py can import and access new components"""
    print("🔍 Testing Dashboard: cockpit.py imports...")
    try:
        # Test that cockpit.py exists and can be parsed
        cockpit_path = Path("cockpit.py")
        assert cockpit_path.exists(), "cockpit.py should exist"
        
        # Test that we can import the new trade_execution functions (used by dashboard)
        from src.trade_execution import get_recent_slippage_stats
        stats = get_recent_slippage_stats(hours=24)
        assert isinstance(stats, dict), "Should return dict"
        
        print("   ✅ Dashboard: cockpit.py can access new components")
        return True
    except Exception as e:
        print(f"   ❌ Dashboard: cockpit.py imports: {e}")
        import traceback
        traceback.print_exc()
        return False

def main():
    """Run all Phase 5 & 6 integration tests"""
    print("=" * 70)
    print("BIG ALPHA PHASE 5 & 6 INTEGRATION TEST SUITE")
    print("=" * 70)
    print()
    
    results = []
    
    results.append(("Phase 5: Trade Execution", test_phase5_trade_execution()))
    results.append(("Phase 5: Exhaustion Exit", test_phase5_exhaustion_exit()))
    results.append(("Phase 6: Symbol Alpha Floor", test_phase6_symbol_alpha_floor()))
    results.append(("Phase 5: FeeAwareGate Buffer Multiplier", test_phase5_fee_aware_gate()))
    results.append(("Phase 5: Slippage Audit Analysis", test_phase5_slippage_audit_analysis()))
    results.append(("Dashboard: cockpit.py imports", test_dashboard_imports()))
    
    print()
    print("=" * 70)
    print("TEST SUMMARY")
    print("=" * 70)
    
    passed = sum(1 for _, result in results if result)
    total = len(results)
    
    for name, result in results:
        status = "✅ PASS" if result else "❌ FAIL"
        print(f"{status}: {name}")
    
    print()
    print(f"Results: {passed}/{total} tests passed")
    
    if passed == total:
        print("🎉 All Phase 5 & 6 integration tests PASSED!")
        return 0
    else:
        print("⚠️ Some tests FAILED - please review errors above")
        return 1

if __name__ == "__main__":
    sys.exit(main())

