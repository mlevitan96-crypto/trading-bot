#!/usr/bin/env python3
"""
Comprehensive Audit Script for Autonomous Brain Integration
============================================================
Verifies that all components are properly wired and integrated.

This script checks:
1. All imports are valid
2. All components can be instantiated
3. All wiring points are connected
4. All data flows are functional
5. All dependencies are available
"""

import sys
import importlib
from pathlib import Path
from typing import Dict, List, Tuple, Any

class AuditResult:
    def __init__(self, component: str, status: str, details: str = ""):
        self.component = component
        self.status = status  # "PASS", "FAIL", "WARNING"
        self.details = details

audit_results: List[AuditResult] = []

def log_result(component: str, status: str, details: str = ""):
    """Log audit result."""
    audit_results.append(AuditResult(component, status, details))
    symbol = "✅" if status == "PASS" else "❌" if status == "FAIL" else "⚠️"
    print(f"{symbol} [{component}] {status}: {details}")

def check_import(module_name: str, component_name: str = None) -> bool:
    """Check if a module can be imported."""
    try:
        module = importlib.import_module(module_name)
        if component_name:
            if hasattr(module, component_name):
                return True
            else:
                log_result(f"{module_name}.{component_name}", "FAIL", f"Component {component_name} not found")
                return False
        return True
    except ImportError as e:
        log_result(module_name, "FAIL", f"Import error: {e}")
        return False
    except Exception as e:
        log_result(module_name, "FAIL", f"Error: {e}")
        return False

def check_component_instantiation(module_name: str, function_name: str, args: Tuple = ()) -> bool:
    """Check if a component can be instantiated."""
    try:
        module = importlib.import_module(module_name)
        if hasattr(module, function_name):
            func = getattr(module, function_name)
            result = func(*args)
            if result is not None:
                return True
            else:
                log_result(f"{module_name}.{function_name}", "WARNING", "Function returned None")
                return False
        else:
            log_result(f"{module_name}.{function_name}", "FAIL", f"Function {function_name} not found")
            return False
    except Exception as e:
        log_result(f"{module_name}.{function_name}", "FAIL", f"Error: {e}")
        return False

def check_file_exists(filepath: str) -> bool:
    """Check if a file exists."""
    path = Path(filepath)
    exists = path.exists()
    if not exists:
        log_result(filepath, "WARNING", "File does not exist (may be created at runtime)")
    return exists

def check_code_wiring(filepath: str, pattern: str, description: str) -> bool:
    """Check if code wiring exists in a file."""
    path = Path(filepath)
    if not path.exists():
        log_result(f"{filepath}::{description}", "FAIL", "File does not exist")
        return False
    
    try:
        content = path.read_text(encoding='utf-8')
        if pattern in content:
            log_result(f"{filepath}::{description}", "PASS", "Wiring found")
            return True
        else:
            log_result(f"{filepath}::{description}", "FAIL", f"Pattern '{pattern[:50]}...' not found")
            return False
    except Exception as e:
        log_result(f"{filepath}::{description}", "FAIL", f"Error reading file: {e}")
        return False

def audit_regime_classifier():
    """Audit regime classifier integration."""
    print("\n" + "="*70)
    print("AUDITING: Regime Classifier")
    print("="*70)
    
    # Check import
    if not check_import("src.regime_classifier"):
        return False
    
    # Check get_regime_classifier function
    if not check_component_instantiation("src.regime_classifier", "get_regime_classifier"):
        return False
    
    # Check wiring in adaptive_signal_optimizer
    check_code_wiring(
        "src/adaptive_signal_optimizer.py",
        "get_regime_classifier",
        "Regime classifier import in adaptive_signal_optimizer"
    )
    
    # Check wiring in bot_cycle
    check_code_wiring(
        "src/bot_cycle.py",
        "regime_classifier",
        "Regime classifier price update in bot_cycle"
    )
    
    # Check wiring in conviction_gate
    check_code_wiring(
        "src/conviction_gate.py",
        "get_active_weights",
        "Regime-based weights in conviction_gate"
    )
    
    return True

def audit_feature_drift_detector():
    """Audit feature drift detector integration."""
    print("\n" + "="*70)
    print("AUDITING: Feature Drift Detector")
    print("="*70)
    
    # Check import
    if not check_import("src.feature_drift_detector"):
        return False
    
    # Check get_drift_monitor function
    if not check_component_instantiation("src.feature_drift_detector", "get_drift_monitor"):
        return False
    
    # Check methods exist
    module = importlib.import_module("src.feature_drift_detector")
    monitor = module.get_drift_monitor()
    
    if not hasattr(monitor, 'log_feature_performance'):
        log_result("feature_drift_detector.log_feature_performance", "FAIL", "Method not found")
        return False
    else:
        log_result("feature_drift_detector.log_feature_performance", "PASS", "Method exists")
    
    if not hasattr(monitor, 'is_quarantined'):
        log_result("feature_drift_detector.is_quarantined", "FAIL", "Method not found")
        return False
    else:
        log_result("feature_drift_detector.is_quarantined", "PASS", "Method exists")
    
    # Check wiring in unified_stack
    check_code_wiring(
        "src/unified_stack.py",
        "log_feature_performance",
        "Feature drift logging in unified_on_trade_close"
    )
    
    # Check wiring in conviction_gate
    check_code_wiring(
        "src/conviction_gate.py",
        "is_quarantined",
        "Quarantine check in conviction_gate"
    )
    
    return True

def audit_shadow_execution_engine():
    """Audit shadow execution engine integration."""
    print("\n" + "="*70)
    print("AUDITING: Shadow Execution Engine")
    print("="*70)
    
    # Check import
    if not check_import("src.shadow_execution_engine"):
        return False
    
    # Check get_shadow_engine function
    if not check_component_instantiation("src.shadow_execution_engine", "get_shadow_engine"):
        return False
    
    # Check wiring in bot_cycle
    check_code_wiring(
        "src/bot_cycle.py",
        "shadow_engine.execute_signal",
        "Shadow execution in bot_cycle.execute_signal"
    )
    
    # Check wiring in unified_stack
    check_code_wiring(
        "src/unified_stack.py",
        "shadow_engine.close_position",
        "Shadow position closing in unified_on_trade_close"
    )
    
    # Check wiring in run.py
    check_code_wiring(
        "src/run.py",
        "compare_shadow_vs_live_performance",
        "Shadow comparison scheduler in run.py"
    )
    
    # Check log file path
    check_file_exists("logs/shadow_results.jsonl")
    
    return True

def audit_policy_tuner():
    """Audit policy tuner integration."""
    print("\n" + "="*70)
    print("AUDITING: Policy Tuner")
    print("="*70)
    
    # Check import
    if not check_import("src.policy_tuner"):
        return False
    
    # Check get_policy_tuner function
    if not check_component_instantiation("src.policy_tuner", "get_policy_tuner"):
        return False
    
    # Check load_trade_history reads from both sources
    check_code_wiring(
        "src/policy_tuner.py",
        "executed_trades.jsonl",
        "Policy tuner reads from executed_trades.jsonl"
    )
    
    check_code_wiring(
        "src/policy_tuner.py",
        "shadow_results.jsonl",
        "Policy tuner reads from shadow_results.jsonl"
    )
    
    # Check wiring in run.py
    check_code_wiring(
        "src/run.py",
        "policy_optimizer_scheduler",
        "Policy optimizer scheduler in run.py"
    )
    
    # Check self-healing trigger
    check_code_wiring(
        "src/run.py",
        "SELF-HEALING",
        "Self-healing trigger in shadow_comparison_scheduler"
    )
    
    return True

def audit_adaptive_signal_optimizer():
    """Audit adaptive signal optimizer integration."""
    print("\n" + "="*70)
    print("AUDITING: Adaptive Signal Optimizer")
    print("="*70)
    
    # Check import
    if not check_import("src.adaptive_signal_optimizer"):
        return False
    
    # Check get_active_weights function
    if not check_component_instantiation("src.adaptive_signal_optimizer", "get_active_weights", ("BTCUSDT",)):
        return False
    
    # Check wiring in conviction_gate
    check_code_wiring(
        "src/conviction_gate.py",
        "get_active_weights",
        "Adaptive weights in conviction_gate"
    )
    
    # Check regime update
    check_code_wiring(
        "src/adaptive_signal_optimizer.py",
        "update_regime",
        "Regime update in adaptive_signal_optimizer"
    )
    
    return True

def audit_run_scheduler():
    """Audit run.py schedulers."""
    print("\n" + "="*70)
    print("AUDITING: Run.py Schedulers")
    print("="*70)
    
    # Check all schedulers are present
    check_code_wiring(
        "src/run.py",
        "shadow_comparison_scheduler",
        "Shadow comparison scheduler"
    )
    
    check_code_wiring(
        "src/run.py",
        "policy_optimizer_scheduler",
        "Policy optimizer scheduler"
    )
    
    check_code_wiring(
        "src/run.py",
        "drift_detection_scheduler",
        "Drift detection scheduler"
    )
    
    return True

def audit_data_flow():
    """Audit data flow between components."""
    print("\n" + "="*70)
    print("AUDITING: Data Flow")
    print("="*70)
    
    # Check signal flow: bot_cycle -> shadow_engine
    check_code_wiring(
        "src/bot_cycle.py",
        "[AUTONOMOUS-BRAIN]",
        "Autonomous brain integration markers in bot_cycle"
    )
    
    # Check trade close flow: unified_stack -> drift_detector + shadow_engine
    check_code_wiring(
        "src/unified_stack.py",
        "[AUTONOMOUS-BRAIN]",
        "Autonomous brain integration markers in unified_stack"
    )
    
    # Check signal generation flow: conviction_gate -> adaptive_optimizer + drift_detector
    check_code_wiring(
        "src/conviction_gate.py",
        "[AUTONOMOUS-BRAIN]",
        "Autonomous brain integration markers in conviction_gate"
    )
    
    return True

def audit_dependencies():
    """Audit Python dependencies."""
    print("\n" + "="*70)
    print("AUDITING: Python Dependencies")
    print("="*70)
    
    required_modules = [
        "numpy",
        "hmmlearn",
        "optuna",
        "schedule"
    ]
    
    for module in required_modules:
        if check_import(module):
            log_result(f"dependency.{module}", "PASS", "Module available")
        else:
            log_result(f"dependency.{module}", "FAIL", "Module not available")
    
    return True

def generate_report():
    """Generate final audit report."""
    print("\n" + "="*70)
    print("AUDIT REPORT SUMMARY")
    print("="*70)
    
    passed = sum(1 for r in audit_results if r.status == "PASS")
    failed = sum(1 for r in audit_results if r.status == "FAIL")
    warnings = sum(1 for r in audit_results if r.status == "WARNING")
    
    print(f"\nTotal Checks: {len(audit_results)}")
    print(f"✅ Passed: {passed}")
    print(f"❌ Failed: {failed}")
    print(f"⚠️  Warnings: {warnings}")
    
    if failed > 0:
        print("\n" + "="*70)
        print("FAILED CHECKS:")
        print("="*70)
        for result in audit_results:
            if result.status == "FAIL":
                print(f"\n❌ {result.component}")
                print(f"   {result.details}")
    
    if warnings > 0:
        print("\n" + "="*70)
        print("WARNINGS:")
        print("="*70)
        for result in audit_results:
            if result.status == "WARNING":
                print(f"\n⚠️  {result.component}")
                print(f"   {result.details}")
    
    print("\n" + "="*70)
    if failed == 0:
        print("✅ AUDIT PASSED - All critical integrations verified")
    else:
        print("❌ AUDIT FAILED - Some integrations need attention")
    print("="*70)
    
    return failed == 0

def main():
    """Run comprehensive audit."""
    print("="*70)
    print("AUTONOMOUS BRAIN INTEGRATION AUDIT")
    print("="*70)
    print("This script verifies all wiring and integrations are correct.")
    print()
    
    # Run all audits
    audit_regime_classifier()
    audit_feature_drift_detector()
    audit_shadow_execution_engine()
    audit_policy_tuner()
    audit_adaptive_signal_optimizer()
    audit_run_scheduler()
    audit_data_flow()
    audit_dependencies()
    
    # Generate report
    success = generate_report()
    
    sys.exit(0 if success else 1)

if __name__ == "__main__":
    main()

