#!/usr/bin/env python3
"""
Code Pattern Verification for Autonomous Brain Integration
==========================================================
Verifies integration patterns exist in code without importing modules.
This can run on any machine to verify code structure.
"""

import re
from pathlib import Path

def check_pattern_in_file(filepath: str, patterns: list, description: str) -> tuple:
    """Check if patterns exist in file."""
    path = Path(filepath)
    if not path.exists():
        return (False, f"File does not exist: {filepath}")
    
    try:
        content = path.read_text(encoding='utf-8')
        found_patterns = []
        missing_patterns = []
        
        for pattern in patterns:
            if isinstance(pattern, tuple):
                # Pattern with description
                pat, desc = pattern
                if re.search(pat, content, re.MULTILINE):
                    found_patterns.append(desc)
                else:
                    missing_patterns.append(desc)
            else:
                # Simple pattern
                if pattern in content:
                    found_patterns.append(pattern)
                else:
                    missing_patterns.append(pattern)
        
        if missing_patterns:
            return (False, f"Missing patterns: {', '.join(missing_patterns)}")
        else:
            return (True, f"Found: {', '.join(found_patterns)}")
    except Exception as e:
        return (False, f"Error reading file: {e}")

def verify_all_integrations():
    """Verify all integration patterns."""
    results = []
    
    print("="*70)
    print("AUTONOMOUS BRAIN INTEGRATION VERIFICATION")
    print("="*70)
    print()
    
    # 1. Regime Classifier in adaptive_signal_optimizer
    print("[1] Checking Regime Classifier integration...")
    success, msg = check_pattern_in_file(
        "src/adaptive_signal_optimizer.py",
        ["get_regime_classifier", "update_regime"],
        "Regime classifier in adaptive_signal_optimizer"
    )
    results.append(("Regime Classifier → Adaptive Optimizer", success, msg))
    print(f"   {'PASS' if success else 'FAIL'}: {msg}\n")
    
    # 2. Regime Classifier in bot_cycle
    success, msg = check_pattern_in_file(
        "src/bot_cycle.py",
        ["regime_classifier", "update_price"],
        "Regime classifier price update in bot_cycle"
    )
    results.append(("Regime Classifier → bot_cycle", success, msg))
    print(f"   {'PASS' if success else 'FAIL'}: {msg}\n")
    
    # 3. Adaptive weights in conviction_gate
    success, msg = check_pattern_in_file(
        "src/conviction_gate.py",
        ["get_active_weights", "regime_weights"],
        "Adaptive weights in conviction_gate"
    )
    results.append(("Adaptive Optimizer → conviction_gate", success, msg))
    print(f"   {'PASS' if success else 'FAIL'}: {msg}\n")
    
    # 4. Feature Drift Detector in unified_stack
    success, msg = check_pattern_in_file(
        "src/unified_stack.py",
        ["log_feature_performance", "get_drift_monitor"],
        "Feature drift logging in unified_on_trade_close"
    )
    results.append(("Feature Drift → unified_stack", success, msg))
    print(f"   {'PASS' if success else 'FAIL'}: {msg}\n")
    
    # 5. Feature Drift quarantine check in conviction_gate
    success, msg = check_pattern_in_file(
        "src/conviction_gate.py",
        ["is_quarantined", "drift_monitor"],
        "Quarantine check in conviction_gate"
    )
    results.append(("Feature Drift → conviction_gate", success, msg))
    print(f"   {'PASS' if success else 'FAIL'}: {msg}\n")
    
    # 6. Shadow Engine in bot_cycle
    success, msg = check_pattern_in_file(
        "src/bot_cycle.py",
        ["shadow_engine.execute_signal", "get_shadow_engine"],
        "Shadow execution in bot_cycle"
    )
    results.append(("Shadow Engine → bot_cycle", success, msg))
    print(f"   {'PASS' if success else 'FAIL'}: {msg}\n")
    
    # 7. Shadow Engine close in unified_stack
    success, msg = check_pattern_in_file(
        "src/unified_stack.py",
        ["shadow_engine.close_position", "get_shadow_engine"],
        "Shadow position closing in unified_on_trade_close"
    )
    results.append(("Shadow Engine → unified_stack", success, msg))
    print(f"   {'PASS' if success else 'FAIL'}: {msg}\n")
    
    # 8. Shadow comparison in run.py
    success, msg = check_pattern_in_file(
        "src/run.py",
        ["compare_shadow_vs_live_performance", "shadow_comparison_scheduler"],
        "Shadow comparison scheduler in run.py"
    )
    results.append(("Shadow Engine → run.py scheduler", success, msg))
    print(f"   {'PASS' if success else 'FAIL'}: {msg}\n")
    
    # 9. Policy Tuner in run.py
    success, msg = check_pattern_in_file(
        "src/run.py",
        ["policy_optimizer_scheduler", "get_policy_tuner"],
        "Policy optimizer scheduler in run.py"
    )
    results.append(("Policy Tuner → run.py scheduler", success, msg))
    print(f"   {'PASS' if success else 'FAIL'}: {msg}\n")
    
    # 10. Policy Tuner reads both sources
    success, msg = check_pattern_in_file(
        "src/policy_tuner.py",
        ["executed_trades.jsonl", "shadow_results.jsonl"],
        "Policy tuner reads from both executed_trades.jsonl and shadow_results.jsonl"
    )
    results.append(("Policy Tuner data sources", success, msg))
    print(f"   {'PASS' if success else 'FAIL'}: {msg}\n")
    
    # 11. Self-healing trigger
    success, msg = check_pattern_in_file(
        "src/run.py",
        ["SELF-HEALING", "should_optimize_guards"],
        "Self-healing trigger in shadow_comparison_scheduler"
    )
    results.append(("Self-healing trigger", success, msg))
    print(f"   {'PASS' if success else 'FAIL'}: {msg}\n")
    
    # 12. Drift detection scheduler
    success, msg = check_pattern_in_file(
        "src/run.py",
        ["drift_detection_scheduler", "run_drift_detection"],
        "Drift detection scheduler in run.py"
    )
    results.append(("Drift Detection → run.py scheduler", success, msg))
    print(f"   {'PASS' if success else 'FAIL'}: {msg}\n")
    
    # Summary
    print("="*70)
    print("VERIFICATION SUMMARY")
    print("="*70)
    
    passed = sum(1 for _, success, _ in results if success)
    failed = len(results) - passed
    
    for name, success, msg in results:
        status = "PASS" if success else "FAIL"
        print(f"{status}: {name}")
        if not success:
            print(f"       {msg}")
    
    print()
    print(f"Total: {len(results)} checks")
    print(f"Passed: {passed}")
    print(f"Failed: {failed}")
    print("="*70)
    
    if failed == 0:
        print("SUCCESS: All integration patterns verified!")
        return True
    else:
        print("FAILURE: Some integration patterns missing!")
        return False

if __name__ == "__main__":
    import sys
    success = verify_all_integrations()
    sys.exit(0 if success else 1)

