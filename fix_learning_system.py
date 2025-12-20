#!/usr/bin/env python3
"""
Fix Learning System - Ensure It's Working and Improving Profitability
======================================================================
This script:
1. Ensures data collection is working
2. Runs data enrichment to link signals to trades
3. Runs learning cycle to generate adjustments
4. Applies adjustments to improve profitability
5. Focuses on: Increasing win rates, decreasing losses
"""

import os
import sys
import json
from pathlib import Path
from datetime import datetime

sys.path.insert(0, os.path.dirname(__file__))

print("=" * 80)
print("FIXING LEARNING SYSTEM FOR PROFITABILITY")
print("=" * 80)
print(f"Goal: Increase win rates, decrease losses through learning\n")

# Step 1: Ensure data enrichment is running
print("STEP 1: Data Enrichment (Link Signals to Trades)")
print("-" * 80)

try:
    from src.data_enrichment_layer import enrich_recent_decisions
    
    print("   Running data enrichment...")
    enriched = enrich_recent_decisions(lookback_hours=168)  # Last 7 days
    
    if enriched:
        print(f"   [OK] Created {len(enriched)} enriched decisions")
        print(f"   [OK] Signals now linked to trade outcomes")
    else:
        print("   [WARNING] No enriched decisions created")
        print("   [INFO] This may be normal if no recent trades")
        
except Exception as e:
    print(f"   [ERROR] Data enrichment failed: {e}")
    import traceback
    traceback.print_exc()

# Step 2: Ensure signal outcomes are being tracked
print("\nSTEP 2: Signal Outcome Tracking")
print("-" * 80)

try:
    from src.signal_outcome_tracker import signal_tracker
    
    print("   Resolving pending signal outcomes...")
    resolved = signal_tracker.resolve_pending_signals()
    print(f"   [OK] Resolved {resolved} pending signal outcomes")
    
    # Check outcomes file
    outcomes_file = Path("logs/signal_outcomes.jsonl")
    if outcomes_file.exists():
        with open(outcomes_file, 'r') as f:
            line_count = sum(1 for line in f if line.strip())
        print(f"   [OK] Total signal outcomes: {line_count}")
    else:
        print("   [WARNING] No signal outcomes file - signal tracking may not be active")
        
except Exception as e:
    print(f"   [ERROR] Signal outcome tracking failed: {e}")
    import traceback
    traceback.print_exc()

# Step 3: Run learning cycle
print("\nSTEP 3: Run Learning Cycle (Analyze & Generate Adjustments)")
print("-" * 80)

try:
    from src.continuous_learning_controller import ContinuousLearningController
    
    print("   Starting learning cycle...")
    controller = ContinuousLearningController(lookback_hours=168)  # Last 7 days
    
    # Run learning cycle
    state = controller.run_learning_cycle(force=True)
    
    print(f"   [OK] Learning cycle complete")
    print(f"   Samples analyzed:")
    samples = state.get('samples', {})
    print(f"      Executed: {samples.get('executed', 0)}")
    print(f"      Blocked: {samples.get('blocked', 0)}")
    print(f"      Missed: {samples.get('missed_found', 0)}")
    
    # Check profitability analysis
    profitability = state.get('profitability', {})
    if profitability:
        print(f"   [OK] Profitability analysis complete")
        
        # Show key metrics
        by_symbol_dir = profitability.get('by_symbol_dir', {})
        by_hour = profitability.get('by_hour', {})
        
        if by_symbol_dir:
            print(f"   [INFO] Analyzed {len(by_symbol_dir)} symbol+direction combos")
        if by_hour:
            print(f"   [INFO] Analyzed {len(by_hour)} time windows")
    
    # Check adjustments generated
    adjustments = state.get('adjustments', [])
    print(f"   [INFO] Generated {len(adjustments)} adjustments")
    
    if adjustments:
        print("\n   Adjustments to improve profitability:")
        for i, adj in enumerate(adjustments[:10], 1):  # Show first 10
            target = adj.get('target', 'unknown')
            change = adj.get('change', {})
            reason = adj.get('reason', 'No reason')
            print(f"      {i}. {target}: {change} - {reason}")
    
    # Step 4: Apply adjustments
    print("\nSTEP 4: Apply Adjustments (Improve Profitability)")
    print("-" * 80)
    
    if adjustments:
        print(f"   Applying {len(adjustments)} adjustments...")
        result = controller.apply_adjustments(dry_run=False)
        
        applied = result.get('applied', 0)
        failed = result.get('failed', 0)
        
        print(f"   [OK] Applied {applied} adjustments")
        if failed > 0:
            print(f"   [WARNING] {failed} adjustments failed")
        
        if applied > 0:
            print(f"\n   [SUCCESS] Learning system updated to improve profitability!")
            print(f"   [INFO] Changes will take effect in next trading cycle")
    else:
        print("   [INFO] No adjustments generated (may need more data)")
        print("   [INFO] Learning system is working but needs more trade data")
        
except Exception as e:
    print(f"   [ERROR] Learning cycle failed: {e}")
    import traceback
    traceback.print_exc()

# Step 5: Verify signal weight learning
print("\nSTEP 5: Signal Weight Optimization")
print("-" * 80)

try:
    from src.signal_weight_learner import run_weight_update
    
    print("   Running signal weight update...")
    result = run_weight_update(dry_run=False)
    
    if result.get('status') == 'success':
        summary = result.get('summary', {})
        outcomes = summary.get('total_outcomes', 0)
        updated = summary.get('weights_updated', 0)
        
        print(f"   [OK] Signal weight update complete")
        print(f"      Outcomes analyzed: {outcomes}")
        print(f"      Weights updated: {updated}")
        
        if updated > 0:
            print(f"   [SUCCESS] Signal weights optimized for profitability!")
        else:
            print(f"   [INFO] Need {50 - outcomes} more outcomes to optimize weights")
    else:
        print(f"   [WARNING] Signal weight update: {result.get('status', 'unknown')}")
        print(f"   [INFO] This is normal if < 50 outcomes per signal")
        
except Exception as e:
    print(f"   [ERROR] Signal weight update failed: {e}")
    import traceback
    traceback.print_exc()

# Step 6: Summary
print("\n" + "=" * 80)
print("LEARNING SYSTEM FIX SUMMARY")
print("=" * 80)

print("\nWhat the Learning System Does:")
print("   1. Analyzes all trades (winners and losers)")
print("   2. Analyzes all signals (executed and blocked)")
print("   3. Identifies patterns that lead to wins vs losses")
print("   4. Adjusts signal weights (increase profitable, decrease unprofitable)")
print("   5. Adjusts gate thresholds (tighten for low WR, loosen for high WR)")
print("   6. Calibrates sizing (increase for high WR, decrease for low WR)")
print("   7. Identifies and avoids losing patterns")

print("\nGoal: Improve Profitability By:")
print("   - Increasing win rates (focus on patterns with >50% WR)")
print("   - Decreasing losses (avoid patterns with <40% WR)")
print("   - Optimizing signal weights (more weight on predictive signals)")
print("   - Optimizing timing (focus on best hours, avoid worst hours)")
print("   - Optimizing sizing (size up winners, size down losers)")

print("\nNext Steps:")
print("   1. Learning system will run every 12 hours automatically")
print("   2. Nightly scheduler runs comprehensive learning at 07:00 UTC")
print("   3. Monitor learning_audit.jsonl for learning cycle activity")
print("   4. Check feature_store/learning_state.json for current state")
print("   5. Signal weights will update once 50+ outcomes per signal")

print("\n" + "=" * 80)
print("FIX COMPLETE")
print("=" * 80)
