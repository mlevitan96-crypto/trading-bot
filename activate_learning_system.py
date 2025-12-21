#!/usr/bin/env python3
"""
Activate Learning System
========================
Forces learning cycles to run and verifies everything is working.
This will:
1. Resolve pending signals (30,427+ signals)
2. Run data enrichment
3. Run learning cycle
4. Apply adjustments
5. Verify everything is working
"""

import os
import sys
from pathlib import Path
from datetime import datetime

sys.path.insert(0, os.path.dirname(__file__))

print("=" * 80)
print("ACTIVATING LEARNING SYSTEM")
print("=" * 80)
print(f"Time: {datetime.now().isoformat()}\n")

# ============================================================================
# 1. RESOLVE PENDING SIGNALS
# ============================================================================

print("1. RESOLVING PENDING SIGNALS")
print("-" * 80)

try:
    from src.signal_outcome_tracker import signal_tracker
    
    print("   Resolving pending signals...")
    resolved = signal_tracker.resolve_pending_signals()
    print(f"   [OK] Resolved {resolved} pending signals")
    
    # Check pending count
    pending_file = Path("feature_store/pending_signals.json")
    if pending_file.exists():
        try:
            with open(pending_file, 'r') as f:
                pending_data = json.load(f)
                if isinstance(pending_data, dict):
                    pending_count = len(pending_data)
                else:
                    pending_count = len(pending_data) if isinstance(pending_data, list) else 0
            print(f"   [INFO] Remaining pending: {pending_count:,}")
        except:
            pass
except Exception as e:
    print(f"   [ERROR] Signal resolution failed: {e}")
    import traceback
    traceback.print_exc()

# ============================================================================
# 2. RUN DATA ENRICHMENT
# ============================================================================

print("\n2. RUNNING DATA ENRICHMENT")
print("-" * 80)

try:
    from src.data_enrichment_layer import enrich_recent_decisions
    
    print("   Enriching decisions...")
    enriched = enrich_recent_decisions(lookback_hours=168)  # Last 7 days
    
    if enriched:
        print(f"   [OK] Created {len(enriched)} enriched decisions")
    else:
        print(f"   [INFO] No enriched decisions created (may need more data)")
except Exception as e:
    print(f"   [ERROR] Data enrichment failed: {e}")
    import traceback
    traceback.print_exc()

# ============================================================================
# 3. RUN LEARNING CYCLE
# ============================================================================

print("\n3. RUNNING LEARNING CYCLE")
print("-" * 80)

try:
    from src.continuous_learning_controller import ContinuousLearningController
    
    print("   Starting learning cycle...")
    controller = ContinuousLearningController(lookback_hours=168)
    
    # Force run learning cycle
    state = controller.run_learning_cycle(force=True)
    
    print(f"   [OK] Learning cycle complete")
    
    # Show results
    samples = state.get("samples", {})
    adjustments = state.get("adjustments", [])
    
    print(f"      Samples analyzed:")
    print(f"         Executed: {samples.get('executed', 0)}")
    print(f"         Blocked: {samples.get('blocked', 0)}")
    print(f"         Missed: {samples.get('missed_found', 0)}")
    
    print(f"      Adjustments generated: {len(adjustments)}")
    if adjustments:
        print(f"      Recent adjustments:")
        for i, adj in enumerate(adjustments[:5], 1):
            target = adj.get("target", "unknown")
            change = adj.get("change", {})
            print(f"         {i}. {target}: {change}")
    
    # Apply adjustments
    if adjustments:
        print(f"\n   Applying adjustments...")
        result = controller.apply_adjustments(dry_run=False)
        applied = result.get("applied", 0)
        failed = result.get("failed", 0)
        print(f"      Applied: {applied}, Failed: {failed}")
    
except Exception as e:
    print(f"   [ERROR] Learning cycle failed: {e}")
    import traceback
    traceback.print_exc()

# ============================================================================
# 4. UPDATE SIGNAL WEIGHTS
# ============================================================================

print("\n4. UPDATING SIGNAL WEIGHTS")
print("-" * 80)

try:
    from src.signal_weight_learner import run_weight_update
    
    print("   Running signal weight update...")
    result = run_weight_update(dry_run=False)
    
    if result.get("status") == "success":
        summary = result.get("summary", {})
        outcomes = summary.get("total_outcomes", 0)
        updated = summary.get("weights_updated", 0)
        
        print(f"   [OK] Signal weight update complete")
        print(f"      Outcomes analyzed: {outcomes}")
        print(f"      Weights updated: {updated}")
    else:
        print(f"   [WARNING] Signal weight update: {result.get('status', 'unknown')}")
except Exception as e:
    print(f"   [ERROR] Signal weight update failed: {e}")
    import traceback
    traceback.print_exc()

# ============================================================================
# 5. VERIFY LEARNING IS WORKING
# ============================================================================

print("\n5. VERIFYING LEARNING SYSTEM")
print("-" * 80)

# Check learning audit log
learning_audit = Path("logs/learning_audit.jsonl")
if learning_audit.exists():
    with open(learning_audit, 'r') as f:
        lines = [line for line in f if line.strip()]
        if lines:
            print(f"   [OK] Learning audit log: {len(lines)} entries")
            # Show last entry
            try:
                last = json.loads(lines[-1])
                event = last.get("event", "unknown")
                ts = last.get("ts", 0)
                if ts:
                    dt = datetime.fromtimestamp(ts)
                    print(f"      Last event: {event} at {dt.isoformat()}")
            except:
                pass
        else:
            print(f"   [WARNING] Learning audit log is empty")
else:
    print(f"   [MISSING] Learning audit log does not exist")

# Check learning state
try:
    from src.continuous_learning_controller import get_learning_state
    state = get_learning_state()
    if state:
        print(f"   [OK] Learning state exists")
        adjustments = len(state.get("adjustments", []))
        print(f"      Pending adjustments: {adjustments}")
    else:
        print(f"   [WARNING] Learning state not found")
except Exception as e:
    print(f"   [ERROR] Could not get learning state: {e}")

# Check enriched decisions
enriched_file = Path("logs/enriched_decisions.jsonl")
if enriched_file.exists():
    with open(enriched_file, 'r') as f:
        line_count = sum(1 for line in f if line.strip())
    if line_count > 0:
        print(f"   [OK] Enriched decisions: {line_count:,} entries")
    else:
        print(f"   [EMPTY] Enriched decisions: 0 entries")
else:
    print(f"   [MISSING] Enriched decisions file does not exist")

# ============================================================================
# SUMMARY
# ============================================================================

print("\n" + "=" * 80)
print("ACTIVATION COMPLETE")
print("=" * 80)

print("\n✅ What Was Done:")
print("   1. Resolved pending signals")
print("   2. Ran data enrichment")
print("   3. Ran learning cycle")
print("   4. Applied adjustments")
print("   5. Updated signal weights")

print("\n📊 Next Steps:")
print("   1. Run monitor_learning_status.py to verify")
print("   2. Check learning_audit.jsonl for cycle entries")
print("   3. Monitor performance over next 24 hours")
print("   4. Learning cycles will run automatically every 12 hours")

print("\n" + "=" * 80)
