#!/usr/bin/env python3
"""
Comprehensive System Verification Script
Verifies ALL learning systems and workflows are actually running.
"""
import sys
import os
sys.path.insert(0, '.')

print("=" * 80)
print("COMPREHENSIVE SYSTEM VERIFICATION")
print("=" * 80)
print()

issues = []
working = []

# 1. Check critical dependencies
print("1. CHECKING CRITICAL DEPENDENCIES")
print("-" * 80)
critical = ['schedule', 'pandas', 'numpy', 'dash', 'flask', 'ccxt']
for mod in critical:
    try:
        __import__(mod)
        print(f"  ✅ {mod}")
        working.append(f"Dependency: {mod}")
    except ImportError as e:
        print(f"  ❌ {mod}: {e}")
        issues.append(f"Missing dependency: {mod}")
print()

# 2. Test ContinuousLearningController
print("2. TESTING CONTINUOUS LEARNING CONTROLLER")
print("-" * 80)
try:
    from src.continuous_learning_controller import ContinuousLearningController
    import schedule
    controller = ContinuousLearningController()
    print("  ✅ Can import and instantiate")
    working.append("ContinuousLearningController")
except Exception as e:
    print(f"  ❌ ERROR: {e}")
    issues.append(f"ContinuousLearningController: {e}")
print()

# 3. Test nightly_learning_scheduler import
print("3. TESTING NIGHTLY LEARNING SCHEDULER")
print("-" * 80)
try:
    from src.run import nightly_learning_scheduler
    import schedule
    print("  ✅ Can import nightly_learning_scheduler")
    print("  ✅ schedule module available")
    working.append("nightly_learning_scheduler (import)")
except Exception as e:
    print(f"  ❌ ERROR: {e}")
    issues.append(f"nightly_learning_scheduler: {e}")
print()

# 4. Test meta_learning_scheduler import
print("4. TESTING META LEARNING SCHEDULER")
print("-" * 80)
try:
    from src.run import meta_learning_scheduler
    print("  ✅ Can import meta_learning_scheduler")
    working.append("meta_learning_scheduler (import)")
except Exception as e:
    print(f"  ❌ ERROR: {e}")
    issues.append(f"meta_learning_scheduler: {e}")
print()

# 5. Test MetaLearningOrchestrator
print("5. TESTING META LEARNING ORCHESTRATOR")
print("-" * 80)
try:
    from src.meta_learning_orchestrator import MetaLearningOrchestrator
    print("  ✅ Can import MetaLearningOrchestrator")
    working.append("MetaLearningOrchestrator (import)")
except Exception as e:
    print(f"  ❌ ERROR: {e}")
    issues.append(f"MetaLearningOrchestrator: {e}")
print()

# 6. Check learning data files
print("6. CHECKING LEARNING DATA FILES")
print("-" * 80)
from pathlib import Path
import json

files_to_check = [
    'feature_store/learning_state.json',
    'feature_store/signal_weights.json',
    'feature_store/daily_learning_rules.json',
    'feature_store/fee_gate_learning.json',
    'logs/learning_updates.jsonl',
    'logs/signal_outcomes.jsonl',
]

for filepath in files_to_check:
    p = Path(filepath)
    if p.exists():
        size = p.stat().st_size
        print(f"  ✅ {filepath} ({size} bytes)")
        working.append(f"Data file: {filepath}")
    else:
        print(f"  ⚠️  {filepath}: MISSING")
        if 'learning_state.json' in filepath:
            issues.append(f"Critical file missing: {filepath}")
print()

# 7. Summary
print("=" * 80)
print("SUMMARY")
print("=" * 80)
print(f"✅ Working systems: {len(working)}")
print(f"❌ Issues found: {len(issues)}")
print()

if issues:
    print("ISSUES:")
    for issue in issues:
        print(f"  - {issue}")
else:
    print("✅ No critical issues found - all systems should be operational")

print()
print("Note: This checks if modules CAN be imported and instantiated.")
print("To verify they're ACTUALLY RUNNING, check service logs:")
print("  journalctl -u tradingbot.service -f | grep -i learning")
print()

