#!/usr/bin/env python3
"""
Diagnose Learning System Status
Checks if learning systems are running and what they're doing
"""

import os
import sys
import json
from pathlib import Path
from datetime import datetime

sys.path.insert(0, os.path.dirname(__file__))

print("=" * 80)
print("LEARNING SYSTEM DIAGNOSTIC")
print("=" * 80)
print(f"Time: {datetime.now().isoformat()}\n")

# Check file locations
base_dir = Path(".")
logs_dir = base_dir / "logs"
feature_store_dir = base_dir / "feature_store"

print("1. CHECKING FILE LOCATIONS")
print("-" * 80)

files_to_check = {
    "Learning State": "feature_store/learning_state.json",
    "Learning Audit": "logs/learning_audit.jsonl",
    "Signal Outcomes": "logs/signal_outcomes.jsonl",
    "Signal Weights": "feature_store/signal_weights_gate.json",
    "Conviction Gate Log": "logs/conviction_gate.jsonl",
    "Enriched Decisions": "logs/enriched_decisions.jsonl",
    "Positions (Trades)": "logs/positions_futures.json",
    "Signals": "logs/signals.jsonl"
}

for name, path in files_to_check.items():
    file_path = Path(path)
    exists = file_path.exists()
    size = file_path.stat().st_size if exists else 0
    status = "EXISTS" if exists else "MISSING"
    print(f"   {name:25} {status:8} {path:40} ({size:,} bytes)")

print("\n2. CHECKING LEARNING SYSTEM STATUS")
print("-" * 80)

# Try to import and check learning controller
try:
    from src.continuous_learning_controller import ContinuousLearningController, get_learning_state
    
    print("   [OK] Continuous Learning Controller importable")
    
    # Try to get learning state
    try:
        state = get_learning_state()
        if state:
            print(f"   [OK] Learning state exists")
            print(f"      Samples: {state.get('samples', {})}")
            print(f"      Last update: {state.get('generated_at', 'unknown')}")
        else:
            print("   [WARNING] Learning state is empty")
    except Exception as e:
        print(f"   [ERROR] Could not get learning state: {e}")
    
    # Try to run a learning cycle (dry run)
    try:
        controller = ContinuousLearningController()
        print("   [OK] Learning controller instantiated")
        
        # Check what it would analyze
        capture = controller.capture
        executed = capture.load_executed_trades(hours=168)
        blocked = capture.load_blocked_signals(hours=168)
        missed = capture.load_missed_opportunities(hours=168)
        counts = capture.get_sample_counts()
        
        print(f"   [INFO] Would analyze:")
        print(f"      Executed trades: {counts.get('executed', 0)}")
        print(f"      Blocked signals: {counts.get('blocked', 0)}")
        print(f"      Missed opportunities: {counts.get('missed_found', 0)}")
        
    except Exception as e:
        print(f"   [ERROR] Could not instantiate controller: {e}")
        import traceback
        traceback.print_exc()
        
except Exception as e:
    print(f"   [ERROR] Could not import learning controller: {e}")
    import traceback
    traceback.print_exc()

print("\n3. CHECKING SIGNAL OUTCOME TRACKER")
print("-" * 80)

try:
    from src.signal_outcome_tracker import signal_tracker
    
    print("   [OK] Signal outcome tracker importable")
    
    # Check pending signals
    pending_file = Path("feature_store/pending_signals.json")
    if pending_file.exists():
        try:
            with open(pending_file, 'r') as f:
                pending_data = json.load(f)
                if isinstance(pending_data, dict):
                    pending_count = len(pending_data)
                else:
                    pending_count = len(pending_data) if isinstance(pending_data, list) else 0
                print(f"   [INFO] Pending signals: {pending_count}")
        except:
            print("   [WARNING] Could not read pending signals")
    
    # Try to resolve some signals
    try:
        resolved = signal_tracker.resolve_pending_signals()
        print(f"   [OK] Resolved {resolved} pending signals")
    except Exception as e:
        print(f"   [WARNING] Could not resolve signals: {e}")
        
except Exception as e:
    print(f"   [ERROR] Could not import signal tracker: {e}")

print("\n4. CHECKING SCHEDULER STATUS")
print("-" * 80)

# Check if scheduler is running
try:
    import psutil
    scheduler_running = False
    for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
        try:
            cmdline = ' '.join(proc.info['cmdline'] or [])
            if 'scheduler' in cmdline.lower() or 'run.py' in cmdline:
                scheduler_running = True
                print(f"   [OK] Scheduler process found: PID {proc.info['pid']}")
                break
        except:
            pass
    if not scheduler_running:
        print("   [WARNING] Scheduler process not found")
except:
    print("   [INFO] Could not check process status (psutil not available)")

print("\n5. CHECKING DATA ENRICHMENT")
print("-" * 80)

try:
    from src.data_enrichment_layer import enrich_recent_decisions
    
    print("   [OK] Data enrichment importable")
    
    # Try to run enrichment
    try:
        enriched = enrich_recent_decisions(lookback_hours=48)
        print(f"   [OK] Enrichment would create {len(enriched)} enriched decisions")
    except Exception as e:
        print(f"   [WARNING] Could not run enrichment: {e}")
        
except Exception as e:
    print(f"   [ERROR] Could not import data enrichment: {e}")

print("\n6. RECOMMENDATIONS")
print("-" * 80)

# Check if learning can actually run
trades_file = Path("logs/positions_futures.json")
signals_file = Path("logs/signals.jsonl")

if not trades_file.exists():
    print("   [CRITICAL] No trade data found - learning cannot analyze trades")
else:
    print("   [OK] Trade data exists")

if not signals_file.exists():
    print("   [CRITICAL] No signal data found - learning cannot analyze signals")
else:
    print("   [OK] Signal data exists")

outcomes_file = Path("logs/signal_outcomes.jsonl")
if not outcomes_file.exists() or outcomes_file.stat().st_size == 0:
    print("   [WARNING] No signal outcomes - signal weight learning cannot optimize")
    print("   [ACTION] Need to ensure signal_tracker.log_signal() is being called")
else:
    print("   [OK] Signal outcomes exist")

enriched_file = Path("logs/enriched_decisions.jsonl")
if not enriched_file.exists() or enriched_file.stat().st_size == 0:
    print("   [WARNING] No enriched decisions - learning cannot link signals to outcomes")
    print("   [ACTION] Need to run data enrichment: enrich_recent_decisions()")
else:
    print("   [OK] Enriched decisions exist")

print("\n" + "=" * 80)
print("DIAGNOSTIC COMPLETE")
print("=" * 80)
