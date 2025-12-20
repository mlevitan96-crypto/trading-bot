#!/usr/bin/env python3
"""
COMPREHENSIVE SYSTEMS AUDIT
===========================
Checks for:
1. Bugs and file mismatches
2. Missing integrations (systems that should call each other but don't)
3. Missing logging/analysis
4. Hardcoded values that should be learned
5. Areas not pushing for profitability
"""

import os
import sys
import json
import ast
import re
from pathlib import Path
from collections import defaultdict
from datetime import datetime

sys.path.insert(0, os.path.dirname(__file__))

print("=" * 80)
print("COMPREHENSIVE SYSTEMS AUDIT")
print("=" * 80)
print(f"Time: {datetime.now().isoformat()}\n")

issues = {
    "file_mismatches": [],
    "missing_integrations": [],
    "missing_logging": [],
    "hardcoded_values": [],
    "profitability_gaps": [],
    "bugs": []
}

# ============================================================================
# 1. FILE PATH MISMATCHES
# ============================================================================

print("1. CHECKING FILE PATH MISMATCHES")
print("-" * 80)

# Check DataRegistry paths vs actual usage
try:
    from src.data_registry import DataRegistry as DR
    
    # Expected files
    expected_files = {
        "LEARNING_STATE_FILE": "feature_store/learning_state.json",
        "SIGNAL_WEIGHTS_FILE": "feature_store/signal_weights.json",
        "LEARNING_AUDIT_LOG": "logs/learning_audit.jsonl",
        "SIGNAL_OUTCOMES": "logs/signal_outcomes.jsonl",
        "ENRICHED_DECISIONS": "logs/enriched_decisions.jsonl",
        "POSITIONS_FUTURES": "logs/positions_futures.json",
        "SIGNALS_UNIVERSE": "logs/signals.jsonl"
    }
    
    for name, path in expected_files.items():
        file_path = Path(path)
        if not file_path.exists():
            issues["file_mismatches"].append({
                "type": "missing_file",
                "file": path,
                "expected_by": name,
                "severity": "HIGH" if "learning" in path.lower() or "signal" in path.lower() else "MEDIUM"
            })
            print(f"   [MISSING] {path} (expected by {name})")
        else:
            print(f"   [OK] {path}")
            
except Exception as e:
    issues["bugs"].append({
        "type": "import_error",
        "module": "data_registry",
        "error": str(e),
        "severity": "HIGH"
    })
    print(f"   [ERROR] Could not check DataRegistry: {e}")

# ============================================================================
# 2. MISSING INTEGRATIONS
# ============================================================================

print("\n2. CHECKING MISSING INTEGRATIONS")
print("-" * 80)

# Check if signal tracking is called where it should be
signal_tracking_locations = {
    "conviction_gate.py": "signal_tracker.log_signal",
    "unified_stack.py": "signal_universe_tracker.log_signal",
    "bot_cycle.py": "signal_tracker or signal_universe_tracker"
}

for file, expected_call in signal_tracking_locations.items():
    file_path = Path(f"src/{file}")
    if file_path.exists():
        content = file_path.read_text()
        if expected_call.split(".")[0] not in content:
            issues["missing_integrations"].append({
                "type": "missing_signal_tracking",
                "file": file,
                "expected": expected_call,
                "severity": "HIGH"
            })
            print(f"   [MISSING] {file} should call {expected_call}")
        else:
            print(f"   [OK] {file} has signal tracking")
    else:
        print(f"   [WARNING] {file} not found")

# Check if post-trade learning is called
post_trade_files = [
    "unified_stack.py",
    "bot_cycle.py",
    "futures_portfolio_tracker.py"
]

for file in post_trade_files:
    file_path = Path(f"src/{file}")
    if file_path.exists():
        content = file_path.read_text()
        has_unified_close = "unified_on_trade_close" in content
        has_learning_calls = any(x in content for x in [
            "continuous_learning",
            "signal_weight_learner",
            "profit_attribution",
            "phase101",
            "phase106",
            "phase107"
        ])
        
        if not has_unified_close and not has_learning_calls:
            issues["missing_integrations"].append({
                "type": "missing_post_trade_learning",
                "file": file,
                "expected": "unified_on_trade_close or learning updates",
                "severity": "HIGH"
            })
            print(f"   [MISSING] {file} should call post-trade learning")
        else:
            print(f"   [OK] {file} has post-trade learning")

# Check if learning controller is scheduled
run_py = Path("src/run.py")
if run_py.exists():
    content = run_py.read_text()
    has_learning_schedule = "ContinuousLearningController" in content and "schedule" in content
    if not has_learning_schedule:
        issues["missing_integrations"].append({
            "type": "missing_learning_schedule",
            "file": "run.py",
            "expected": "ContinuousLearningController scheduled",
            "severity": "CRITICAL"
        })
        print(f"   [MISSING] run.py should schedule ContinuousLearningController")
    else:
        print(f"   [OK] run.py schedules learning controller")

# ============================================================================
# 3. MISSING LOGGING/ANALYSIS
# ============================================================================

print("\n3. CHECKING MISSING LOGGING/ANALYSIS")
print("-" * 80)

# Check if signal outcomes are being logged
signal_outcomes_file = Path("logs/signal_outcomes.jsonl")
if signal_outcomes_file.exists():
    with open(signal_outcomes_file, 'r') as f:
        line_count = sum(1 for line in f if line.strip())
    if line_count == 0:
        issues["missing_logging"].append({
            "type": "empty_signal_outcomes",
            "file": "logs/signal_outcomes.jsonl",
            "expected": "Signal outcomes being logged",
            "severity": "CRITICAL"
        })
        print(f"   [EMPTY] signal_outcomes.jsonl has 0 entries")
    else:
        print(f"   [OK] signal_outcomes.jsonl has {line_count} entries")
else:
    issues["missing_logging"].append({
        "type": "missing_signal_outcomes",
        "file": "logs/signal_outcomes.jsonl",
        "expected": "Signal outcomes file",
        "severity": "CRITICAL"
    })
    print(f"   [MISSING] signal_outcomes.jsonl does not exist")

# Check if enriched decisions are being created
enriched_file = Path("logs/enriched_decisions.jsonl")
if enriched_file.exists():
    with open(enriched_file, 'r') as f:
        line_count = sum(1 for line in f if line.strip())
    if line_count == 0:
        issues["missing_logging"].append({
            "type": "empty_enriched_decisions",
            "file": "logs/enriched_decisions.jsonl",
            "expected": "Enriched decisions being created",
            "severity": "HIGH"
        })
        print(f"   [EMPTY] enriched_decisions.jsonl has 0 entries")
    else:
        print(f"   [OK] enriched_decisions.jsonl has {line_count} entries")
else:
    issues["missing_logging"].append({
        "type": "missing_enriched_decisions",
        "file": "logs/enriched_decisions.jsonl",
        "expected": "Enriched decisions file",
        "severity": "HIGH"
    })
    print(f"   [MISSING] enriched_decisions.jsonl does not exist")

# Check if learning audit log exists
learning_audit = Path("logs/learning_audit.jsonl")
if learning_audit.exists():
    with open(learning_audit, 'r') as f:
        line_count = sum(1 for line in f if line.strip())
    if line_count == 0:
        issues["missing_logging"].append({
            "type": "empty_learning_audit",
            "file": "logs/learning_audit.jsonl",
            "expected": "Learning cycles being logged",
            "severity": "HIGH"
        })
        print(f"   [EMPTY] learning_audit.jsonl has 0 entries")
    else:
        print(f"   [OK] learning_audit.jsonl has {line_count} entries")
else:
    issues["missing_logging"].append({
        "type": "missing_learning_audit",
        "file": "logs/learning_audit.jsonl",
        "expected": "Learning audit log",
        "severity": "HIGH"
    })
    print(f"   [MISSING] learning_audit.jsonl does not exist")

# ============================================================================
# 4. HARDCODED VALUES THAT SHOULD BE LEARNED
# ============================================================================

print("\n4. CHECKING HARDCODED VALUES")
print("-" * 80)

# Patterns to find hardcoded thresholds
hardcoded_patterns = [
    (r'win_rate\s*[<>=]+\s*0\.(4[0-9]|5[0-9]|6[0-9])', "Win rate threshold"),
    (r'0\.(4[0-9]|5[0-9]|6[0-9])\s*#.*win', "Win rate comment"),
    (r'threshold\s*=\s*0\.(4[0-9]|5[0-9]|6[0-9])', "Threshold value"),
    (r'MIN.*WR|MAX.*WR', "Win rate constant"),
    (r'0\.(15|20|25|30|35|40|45|50|55|60)', "Common threshold"),
]

files_to_check = [
    "src/conviction_gate.py",
    "src/fee_aware_gate.py",
    "src/intelligence_gate.py",
    "src/phase10_profit_engine.py",
    "src/strategy_runner.py",
    "src/phase92_profit_discipline.py"
]

for file_path_str in files_to_check:
    file_path = Path(file_path_str)
    if file_path.exists():
        content = file_path.read_text()
        for pattern, description in hardcoded_patterns:
            matches = re.finditer(pattern, content, re.IGNORECASE)
            for match in matches:
                line_num = content[:match.start()].count('\n') + 1
                line = content.split('\n')[line_num - 1].strip()
                
                # Check if it's in a learning function (should be OK)
                is_in_learning = any(x in content[max(0, match.start()-500):match.start()] 
                                    for x in ["def learn", "def update", "def adjust"])
                
                if not is_in_learning:
                    issues["hardcoded_values"].append({
                        "type": "hardcoded_threshold",
                        "file": file_path_str,
                        "line": line_num,
                        "value": match.group(),
                        "description": description,
                        "severity": "MEDIUM"
                    })
                    print(f"   [HARDCODED] {file_path_str}:{line_num} - {description}: {match.group()[:50]}")

# Check for hardcoded signal weights
signal_weight_files = [
    "src/predictive_flow_engine.py",
    "src/conviction_gate.py"
]

for file_path_str in signal_weight_files:
    file_path = Path(file_path_str)
    if file_path.exists():
        content = file_path.read_text()
        # Look for weight dictionaries
        weight_pattern = r'["\'](liquidation|funding|whale|ofi|fear|regime|volatility|oi)["\']\s*:\s*0\.\d+'
        matches = re.finditer(weight_pattern, content, re.IGNORECASE)
        for match in matches:
            line_num = content[:match.start()].count('\n') + 1
            # Check if it's loading from file (should be OK)
            is_loading = any(x in content[max(0, match.start()-200):match.start()] 
                            for x in ["load", "read", "get", "from", "import"])
            
            if not is_loading:
                issues["hardcoded_values"].append({
                    "type": "hardcoded_signal_weight",
                    "file": file_path_str,
                    "line": line_num,
                    "value": match.group(),
                    "description": "Signal weight should be learned",
                    "severity": "HIGH"
                })
                print(f"   [HARDCODED] {file_path_str}:{line_num} - Signal weight: {match.group()}")

# ============================================================================
# 5. PROFITABILITY GAPS
# ============================================================================

print("\n5. CHECKING PROFITABILITY GAPS")
print("-" * 80)

# Check if profitability is being used in sizing
sizing_files = [
    "src/unified_stack.py",
    "src/conviction_gate.py",
    "src/edge_weighted_sizer.py"
]

for file_path_str in sizing_files:
    file_path = Path(file_path_str)
    if file_path.exists():
        content = file_path.read_text()
        has_profitability = any(x in content.lower() for x in [
            "win_rate", "profit", "pnl", "expectancy", "profitability"
        ])
        has_historical = any(x in content.lower() for x in [
            "historical", "learned", "performance"
        ])
        
        if not has_profitability and not has_historical:
            issues["profitability_gaps"].append({
                "type": "sizing_not_profitability_aware",
                "file": file_path_str,
                "expected": "Sizing should use win rate/profitability",
                "severity": "HIGH"
            })
            print(f"   [GAP] {file_path_str} sizing not using profitability")
        else:
            print(f"   [OK] {file_path_str} uses profitability in sizing")

# Check if exit decisions use profitability
exit_files = [
    "src/position_timing_intelligence.py",
    "src/futures_ladder_exits.py",
    "src/phase92_profit_discipline.py"
]

for file_path_str in exit_files:
    file_path = Path(file_path_str)
    if file_path.exists():
        content = file_path.read_text()
        has_profitability = any(x in content.lower() for x in [
            "win_rate", "profit", "pnl", "expectancy", "profitability", "optimal_hold"
        ])
        
        if not has_profitability:
            issues["profitability_gaps"].append({
                "type": "exit_not_profitability_aware",
                "file": file_path_str,
                "expected": "Exit decisions should use profitability",
                "severity": "HIGH"
            })
            print(f"   [GAP] {file_path_str} exits not using profitability")
        else:
            print(f"   [OK] {file_path_str} uses profitability in exits")

# Check if learning systems are profitability-focused
learning_files = [
    "src/continuous_learning_controller.py",
    "src/signal_weight_learner.py",
    "src/profit_target_sizing_intelligence.py"
]

for file_path_str in learning_files:
    file_path = Path(file_path_str)
    if file_path.exists():
        content = file_path.read_text()
        has_profitability = any(x in content.lower() for x in [
            "profit", "pnl", "win_rate", "expectancy", "profitability"
        ])
        
        if not has_profitability:
            issues["profitability_gaps"].append({
                "type": "learning_not_profitability_focused",
                "file": file_path_str,
                "expected": "Learning should optimize for profitability",
                "severity": "CRITICAL"
            })
            print(f"   [GAP] {file_path_str} learning not profitability-focused")
        else:
            print(f"   [OK] {file_path_str} learning is profitability-focused")

# ============================================================================
# 6. BUGS AND ERRORS
# ============================================================================

print("\n6. CHECKING FOR BUGS")
print("-" * 80)

# Check for common bugs
bug_checks = [
    {
        "file": "src/continuous_learning_controller.py",
        "pattern": r'LEARNING_STATE_FILE\s*=\s*Path\(["\']([^"\']+)["\']\)',
        "description": "Learning state file path should use DataRegistry"
    },
    {
        "file": "src/conviction_gate.py",
        "pattern": r'signal_tracker\.log_signal',
        "description": "Signal tracking should be called",
        "should_exist": True
    }
]

for check in bug_checks:
    file_path = Path(check["file"])
    if file_path.exists():
        content = file_path.read_text()
        has_pattern = bool(re.search(check["pattern"], content))
        should_exist = check.get("should_exist", False)
        
        if should_exist and not has_pattern:
            issues["bugs"].append({
                "type": "missing_required_call",
                "file": check["file"],
                "description": check["description"],
                "severity": "HIGH"
            })
            print(f"   [BUG] {check['file']} - {check['description']}")
        elif not should_exist and has_pattern:
            print(f"   [OK] {check['file']} - {check['description']}")

# ============================================================================
# SUMMARY
# ============================================================================

print("\n" + "=" * 80)
print("AUDIT SUMMARY")
print("=" * 80)

total_issues = sum(len(v) for v in issues.values())
print(f"\nTotal Issues Found: {total_issues}")

for category, items in issues.items():
    if items:
        print(f"\n{category.upper().replace('_', ' ')}: {len(items)}")
        for item in items[:5]:  # Show first 5
            severity = item.get("severity", "UNKNOWN")
            print(f"  [{severity}] {item.get('type', 'unknown')} - {item.get('file', 'unknown')}")
        if len(items) > 5:
            print(f"  ... and {len(items) - 5} more")

# Save report
report_path = Path("reports/systems_audit_report.json")
report_path.parent.mkdir(parents=True, exist_ok=True)

report = {
    "timestamp": datetime.now().isoformat(),
    "total_issues": total_issues,
    "issues": issues,
    "summary": {
        category: len(items) for category, items in issues.items()
    }
}

with open(report_path, 'w') as f:
    json.dump(report, f, indent=2)

print(f"\n[OK] Full report saved to: {report_path}")

# Critical issues
critical = [item for items in issues.values() for item in items if item.get("severity") == "CRITICAL"]
if critical:
    print(f"\n[CRITICAL] {len(critical)} critical issues found - these must be fixed!")
    for item in critical:
        print(f"  - {item.get('type')} in {item.get('file', 'unknown')}")

print("\n" + "=" * 80)
print("AUDIT COMPLETE")
print("=" * 80)
