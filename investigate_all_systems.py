#!/usr/bin/env python3
"""
Comprehensive System Investigation Script
Checks ALL learning systems, monitors, and workflows to verify they're actually running.
"""
import os
import sys
import json
import subprocess
from pathlib import Path
from datetime import datetime, timezone

sys.path.insert(0, '.')

print("=" * 80)
print("COMPREHENSIVE SYSTEM INVESTIGATION")
print("=" * 80)
print(f"Time: {datetime.now(timezone.utc).isoformat()}")
print()

# 1. Check Python dependencies
print("1. CHECKING PYTHON DEPENDENCIES")
print("-" * 80)
critical_modules = ['schedule', 'pandas', 'numpy', 'dash', 'flask', 'ccxt']
missing = []
for module in critical_modules:
    try:
        __import__(module)
        print(f"  ✅ {module}: INSTALLED")
    except ImportError:
        print(f"  ❌ {module}: MISSING")
        missing.append(module)

if missing:
    print(f"\n  ⚠️  CRITICAL: Missing modules: {', '.join(missing)}")
print()

# 2. Check learning-related files
print("2. CHECKING LEARNING DATA FILES")
print("-" * 80)
learning_files = [
    ('feature_store/learning_state.json', 'Learning State'),
    ('feature_store/signal_weights.json', 'Signal Weights'),
    ('feature_store/daily_learning_rules.json', 'Daily Learning Rules'),
    ('feature_store/fee_gate_learning.json', 'Fee Gate Learning'),
    ('logs/learning_updates.jsonl', 'Learning Updates'),
    ('logs/learning_events.jsonl', 'Learning Events'),
    ('logs/learning_audit.jsonl', 'Learning Audit'),
    ('logs/signal_outcomes.jsonl', 'Signal Outcomes'),
]

for path, name in learning_files:
    p = Path(path)
    exists = p.exists()
    size = p.stat().st_size if exists else 0
    status = "EXISTS" if exists else "MISSING"
    if exists and size > 0:
        try:
            if path.endswith('.jsonl'):
                lines = p.read_text().strip().split('\n')
                line_count = len([l for l in lines if l.strip()])
                if line_count > 0:
                    last_line = lines[-1] if lines else None
                    if last_line:
                        try:
                            last_entry = json.loads(last_line)
                            ts = last_entry.get('ts', last_entry.get('timestamp', 'unknown'))
                            print(f"  ✅ {name}: {status} ({size} bytes, {line_count} entries, last: {ts})")
                        except:
                            print(f"  ⚠️  {name}: {status} ({size} bytes, {line_count} entries, last line parse error)")
                    else:
                        print(f"  ⚠️  {name}: {status} ({size} bytes, empty)")
                else:
                    print(f"  ⚠️  {name}: {status} ({size} bytes, no entries)")
            else:
                data = json.loads(p.read_text())
                keys = list(data.keys())[:5]
                print(f"  ✅ {name}: {status} ({size} bytes, keys: {keys})")
        except Exception as e:
            print(f"  ❌ {name}: {status} but ERROR reading: {e}")
    else:
        print(f"  ⚠️  {name}: {status} ({size} bytes)")
print()

# 3. Check if learning systems can be imported
print("3. CHECKING LEARNING SYSTEM IMPORTS")
print("-" * 80)
learning_modules = [
    'src.continuous_learning_controller',
    'src.meta_learning_orchestrator',
    'src.counterfactual_intelligence',
    'src.signal_universe_tracker',
    'src.learning_health_monitor',
    'src.nightly_orchestration',
]

for module_path in learning_modules:
    try:
        __import__(module_path)
        print(f"  ✅ {module_path}: IMPORTABLE")
    except Exception as e:
        print(f"  ❌ {module_path}: IMPORT ERROR - {e}")
print()

# 4. Check service status
print("4. CHECKING SERVICE STATUS")
print("-" * 80)
try:
    result = subprocess.run(['systemctl', 'is-active', 'tradingbot.service'], 
                          capture_output=True, text=True, timeout=5)
    status = result.stdout.strip()
    if status == 'active':
        print(f"  ✅ tradingbot.service: ACTIVE")
    else:
        print(f"  ❌ tradingbot.service: {status.upper()}")
except Exception as e:
    print(f"  ⚠️  Could not check service status: {e}")
print()

# 5. Check recent logs for learning activity
print("5. CHECKING RECENT LEARNING ACTIVITY IN LOGS")
print("-" * 80)
try:
    # Check for learning-related log entries in last 24 hours
    result = subprocess.run([
        'journalctl', '-u', 'tradingbot.service', 
        '--since', '24 hours ago',
        '--no-pager'
    ], capture_output=True, text=True, timeout=10)
    
    log_lines = result.stdout.split('\n')
    
    learning_keywords = [
        '[LEARNING]', '[COUNTERFACTUAL]', 'Continuous Learning',
        'learning cycle', 'learning_cycle', 'MetaLearning',
        'signal weights', 'signal_weights', 'blocked signals'
    ]
    
    learning_lines = []
    for line in log_lines:
        for keyword in learning_keywords:
            if keyword.lower() in line.lower():
                learning_lines.append(line.strip())
                break
    
    if learning_lines:
        print(f"  ✅ Found {len(learning_lines)} learning-related log entries in last 24h")
        print("  Recent entries:")
        for line in learning_lines[-5:]:
            print(f"    {line[:120]}...")
    else:
        print(f"  ❌ NO learning-related log entries found in last 24 hours")
        print(f"  ⚠️  This suggests learning systems may not be running")
        
except Exception as e:
    print(f"  ⚠️  Could not check logs: {e}")
print()

# 6. Check for startup errors
print("6. CHECKING FOR STARTUP ERRORS")
print("-" * 80)
try:
    result = subprocess.run([
        'journalctl', '-u', 'tradingbot.service',
        '--since', '7 days ago',
        '--no-pager'
    ], capture_output=True, text=True, timeout=10)
    
    log_lines = result.stdout.split('\n')
    
    error_keywords = [
        'startup error', 'Failed to start', 'CRITICAL',
        'ModuleNotFoundError', 'ImportError', 'schedule',
        'learning.*error', 'learning.*failed'
    ]
    
    error_lines = []
    for line in log_lines:
        for keyword in error_keywords:
            if keyword.lower() in line.lower():
                error_lines.append(line.strip())
                break
    
    if error_lines:
        print(f"  ⚠️  Found {len(error_lines)} potential error entries")
        print("  Recent errors:")
        for line in error_lines[-10:]:
            print(f"    {line[:120]}...")
    else:
        print(f"  ✅ No obvious startup errors found")
        
except Exception as e:
    print(f"  ⚠️  Could not check for errors: {e}")
print()

# 7. Check ContinuousLearningController specifically
print("7. TESTING CONTINUOUS LEARNING CONTROLLER")
print("-" * 80)
try:
    from src.continuous_learning_controller import ContinuousLearningController
    controller = ContinuousLearningController()
    print("  ✅ ContinuousLearningController: INSTANTIATED")
    
    # Try to get current state (don't run full cycle, just check if it loads)
    try:
        state_file = Path('feature_store/learning_state.json')
        if state_file.exists():
            state = json.loads(state_file.read_text())
            print(f"  ✅ Learning state file readable: {len(state)} keys")
        else:
            print(f"  ⚠️  Learning state file missing")
    except Exception as e:
        print(f"  ❌ Error reading learning state: {e}")
        
except Exception as e:
    print(f"  ❌ ContinuousLearningController ERROR: {e}")
    import traceback
    traceback.print_exc()
print()

# 8. Summary
print("=" * 80)
print("SUMMARY")
print("=" * 80)
if missing:
    print(f"❌ CRITICAL ISSUES FOUND:")
    print(f"   - Missing Python modules: {', '.join(missing)}")
    print(f"   - These MUST be installed for systems to work")
else:
    print("✅ All critical Python modules are installed")
print()

print("Next steps:")
print("  1. Install missing modules: pip3 install " + " ".join(missing))
print("  2. Restart tradingbot.service: systemctl restart tradingbot.service")
print("  3. Monitor logs: journalctl -u tradingbot.service -f")
print()

