# src/full_autonomy_pipeline.py
#
# Phase 13.0 – Complete Autonomous Trading & Learning System
# Purpose: Integrate ALL modules so the bot can learn, trade, promote, prune, auto-tune, monitor execution,
# detect regimes, stress-test strategies, reallocate capital, and self-heal without manual intervention.
#
# This pipeline runs nightly (learning mode or live mode depending on config).
# It orchestrates:
#   - Accounting sanity guard
#   - Intelligence learning mode (Phase 11.5)
#   - Promotion & pruning (Phase 12.0)
#   - Auto-tuning thresholds (Phase 12.5)
#   - Execution quality monitor
#   - Dynamic regime detection
#   - Synthetic stress testing
#   - Capital allocation engine
#   - Recovery & fail-safe logic
#
# NOTE: This is a skeleton integration. Each module should be imported from its respective file.
#       The orchestration ensures everything runs in sequence automatically.

import time
import json
import os
import sys

# Add src to path for imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# ---- Import core modules ----
try:
    import accounting_sanity_guard as accounting
    import promotion_pruning_autonomy as promotion
    import promotion_pruning_autotune as autotune
except ImportError as e:
    print(f"Warning: Core module import failed: {e}")
    accounting = promotion = autotune = None

# Placeholder imports for additional modules (to be implemented separately)
# These should each expose a `run()` function
intelligence = None
execution_monitor = None
regime_detection = None
stress_test = None
capital_alloc = None
recovery = None

EVENT_LOG = "logs/full_autonomy_events.jsonl"

def log_event(event, payload=None):
    os.makedirs(os.path.dirname(EVENT_LOG), exist_ok=True)
    payload = dict(payload or {})
    payload.update({"event": event, "ts": int(time.time())})
    with open(EVENT_LOG, "a") as f:
        f.write(json.dumps(payload) + "\n")

# ---- Full autonomy cycle ----
def run_full_autonomy_cycle():
    log_event("autonomy_cycle_start")
    
    print("=" * 80)
    print("🤖 PHASE 13.0 - FULL AUTONOMY PIPELINE")
    print("=" * 80)
    print()

    # 1. Accounting sanity guard
    print("📊 [1/9] Running accounting sanity guard...")
    if accounting and hasattr(accounting, 'run_reconciliation'):
        try:
            accounting.run_reconciliation()
            log_event("accounting_checked", {"status": "success"})
            print("    ✅ Accounting reconciliation complete")
        except Exception as e:
            log_event("accounting_checked", {"status": "error", "error": str(e)})
            print(f"    ❌ Accounting error: {e}")
    else:
        print("    ⚠️  Accounting module not available")
    print()

    # 2. Intelligence learning mode (simulation) - PLACEHOLDER
    print("🧠 [2/9] Running intelligence learning mode...")
    if intelligence and hasattr(intelligence, 'run_learning_cycle'):
        try:
            intelligence.run_learning_cycle()
            log_event("intelligence_learning_complete", {"status": "success"})
            print("    ✅ Intelligence learning complete")
        except Exception as e:
            log_event("intelligence_learning_complete", {"status": "error", "error": str(e)})
            print(f"    ❌ Learning error: {e}")
    else:
        print("    ⚠️  Intelligence module not implemented yet")
        log_event("intelligence_learning_complete", {"status": "skipped"})
    print()

    # 3. Promotion & pruning
    print("🔄 [3/9] Running promotion & pruning...")
    if promotion and hasattr(promotion, 'run_promotion_pruning_nightly'):
        try:
            promotion.run_promotion_pruning_nightly()
            log_event("promotion_pruning_complete", {"status": "success"})
            print("    ✅ Promotion & pruning complete")
        except Exception as e:
            log_event("promotion_pruning_complete", {"status": "error", "error": str(e)})
            print(f"    ❌ Promotion error: {e}")
    else:
        print("    ⚠️  Promotion module not available")
    print()

    # 4. Auto-tuning thresholds
    print("⚙️  [4/9] Running auto-tuning...")
    if autotune and hasattr(autotune, 'run_autonomy_cycle'):
        try:
            autotune.run_autonomy_cycle()
            log_event("auto_tuning_complete", {"status": "success"})
            print("    ✅ Auto-tuning complete")
        except Exception as e:
            log_event("auto_tuning_complete", {"status": "error", "error": str(e)})
            print(f"    ❌ Auto-tuning error: {e}")
    else:
        print("    ⚠️  Auto-tuning module not available")
    print()

    # 5. Execution quality monitor - PLACEHOLDER
    print("📈 [5/9] Running execution quality monitor...")
    if execution_monitor and hasattr(execution_monitor, 'run'):
        try:
            execution_monitor.run()
            log_event("execution_quality_checked", {"status": "success"})
            print("    ✅ Execution quality checked")
        except Exception as e:
            log_event("execution_quality_checked", {"status": "error", "error": str(e)})
            print(f"    ❌ Execution monitor error: {e}")
    else:
        print("    ⚠️  Execution monitor not implemented yet")
        log_event("execution_quality_checked", {"status": "skipped"})
    print()

    # 6. Dynamic regime detection - PLACEHOLDER
    print("🌊 [6/9] Running dynamic regime detection...")
    if regime_detection and hasattr(regime_detection, 'run'):
        try:
            regime_detection.run()
            log_event("regime_detection_complete", {"status": "success"})
            print("    ✅ Regime detection complete")
        except Exception as e:
            log_event("regime_detection_complete", {"status": "error", "error": str(e)})
            print(f"    ❌ Regime detection error: {e}")
    else:
        print("    ⚠️  Regime detection not implemented yet")
        log_event("regime_detection_complete", {"status": "skipped"})
    print()

    # 7. Synthetic stress testing - PLACEHOLDER
    print("🧪 [7/9] Running synthetic stress testing...")
    if stress_test and hasattr(stress_test, 'run'):
        try:
            stress_test.run()
            log_event("stress_testing_complete", {"status": "success"})
            print("    ✅ Stress testing complete")
        except Exception as e:
            log_event("stress_testing_complete", {"status": "error", "error": str(e)})
            print(f"    ❌ Stress testing error: {e}")
    else:
        print("    ⚠️  Stress testing not implemented yet")
        log_event("stress_testing_complete", {"status": "skipped"})
    print()

    # 8. Capital allocation engine - PLACEHOLDER
    print("💰 [8/9] Running capital allocation engine...")
    if capital_alloc and hasattr(capital_alloc, 'run'):
        try:
            capital_alloc.run()
            log_event("capital_allocation_complete", {"status": "success"})
            print("    ✅ Capital allocation complete")
        except Exception as e:
            log_event("capital_allocation_complete", {"status": "error", "error": str(e)})
            print(f"    ❌ Capital allocation error: {e}")
    else:
        print("    ⚠️  Capital allocation not implemented yet")
        log_event("capital_allocation_complete", {"status": "skipped"})
    print()

    # 9. Recovery & fail-safe logic - PLACEHOLDER
    print("🛡️  [9/9] Running recovery & fail-safe...")
    if recovery and hasattr(recovery, 'run'):
        try:
            recovery.run()
            log_event("recovery_fail_safe_complete", {"status": "success"})
            print("    ✅ Recovery & fail-safe complete")
        except Exception as e:
            log_event("recovery_fail_safe_complete", {"status": "error", "error": str(e)})
            print(f"    ❌ Recovery error: {e}")
    else:
        print("    ⚠️  Recovery module not implemented yet")
        log_event("recovery_fail_safe_complete", {"status": "skipped"})
    print()

    log_event("autonomy_cycle_complete", {"status": "success"})
    
    print("=" * 80)
    print("✅ PHASE 13.0 AUTONOMY CYCLE COMPLETE")
    print("=" * 80)

if __name__ == "__main__":
    run_full_autonomy_cycle()
    print("\nPhase 13.0 full autonomy pipeline executed.")
    print("Modules integrated: Accounting, Promotion, Auto-tuning")
    print("Modules pending: Intelligence, Execution, Regime, Stress, Capital, Recovery")
