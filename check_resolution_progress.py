#!/usr/bin/env python3
"""
Check Signal Resolution Progress
================================
Shows how many signals are left to resolve and estimated time remaining.
Run this script repeatedly to see progress updates.
"""

import os
import sys
import json
import time
from pathlib import Path
from datetime import datetime

sys.path.insert(0, os.path.dirname(__file__))

print("=" * 80)
print("SIGNAL RESOLUTION PROGRESS")
print("=" * 80)
print(f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
print()

# Check pending signals
pending_file = Path("feature_store/pending_signals.json")
if pending_file.exists():
    try:
        # Get file modification time to detect if it's being updated
        pending_mtime = pending_file.stat().st_mtime
        pending_age_seconds = time.time() - pending_mtime
        
        with open(pending_file, 'r') as f:
            pending_data = json.load(f)
            if isinstance(pending_data, dict):
                pending_count = len(pending_data)
            else:
                pending_count = len(pending_data) if isinstance(pending_data, list) else 0
        
        print(f"Pending Signals: {pending_count:,}")
        if pending_age_seconds < 120:  # Updated in last 2 minutes
            print(f"   ✅ File updated {int(pending_age_seconds)} seconds ago (actively processing)")
        else:
            print(f"   ⚠️  File last updated {int(pending_age_seconds/60)} minutes ago")
        
        # Check signal outcomes (to see how many have been resolved)
        outcomes_file = Path("logs/signal_outcomes.jsonl")
        if outcomes_file.exists():
            outcomes_mtime = outcomes_file.stat().st_mtime
            outcomes_age_seconds = time.time() - outcomes_mtime
            
            with open(outcomes_file, 'r') as f:
                outcomes_count = sum(1 for line in f if line.strip())
            print(f"Resolved Outcomes: {outcomes_count:,}")
            if outcomes_age_seconds < 120:
                print(f"   ✅ File updated {int(outcomes_age_seconds)} seconds ago (actively processing)")
            else:
                print(f"   ⚠️  File last updated {int(outcomes_age_seconds/60)} minutes ago")
            
            if pending_count > 0:
                # UPDATED: Batch processing mode (200 signals per cycle, 60s per cycle)
                signals_per_cycle = 200  # From resolve_pending_signals(max_signals_per_cycle=200)
                cycle_interval_seconds = 60  # Healing cycle runs every 60 seconds
                
                # Calculate cycles needed
                cycles_needed = (pending_count + signals_per_cycle - 1) // signals_per_cycle  # Ceiling division
                total_seconds = cycles_needed * cycle_interval_seconds
                minutes_remaining = total_seconds / 60
                hours_remaining = minutes_remaining / 60
                
                print(f"\nProcessing Rate:")
                print(f"   Signals per cycle: {signals_per_cycle}")
                print(f"   Cycle interval: {cycle_interval_seconds} seconds")
                print(f"   Signals per minute: {signals_per_cycle * (60 / cycle_interval_seconds)}")
                
                print(f"\nEstimated Time Remaining:")
                print(f"   Cycles needed: {cycles_needed:,}")
                if hours_remaining < 1:
                    print(f"   Time: ~{int(minutes_remaining)} minutes")
                else:
                    hours = int(hours_remaining)
                    mins = int(minutes_remaining % 60)
                    print(f"   Time: ~{hours} hours {mins} minutes")
                
                # Better progress calculation using outcomes
                # Each signal has 5 horizons, so outcomes_count / 5 ≈ signals resolved
                signals_resolved_estimate = outcomes_count // 5
                total_signals_estimate = signals_resolved_estimate + pending_count
                
                if total_signals_estimate > 0:
                    progress_pct = (signals_resolved_estimate / total_signals_estimate) * 100
                    print(f"\nProgress Estimate:")
                    print(f"   Signals resolved: ~{signals_resolved_estimate:,}")
                    print(f"   Signals remaining: {pending_count:,}")
                    print(f"   Progress: {progress_pct:.1f}% complete")
                else:
                    print(f"\nProgress: Calculating...")
                
                # Show rate of progress if we can detect it
                print(f"\n💡 Tip: Run this script again in 1-2 minutes to see progress rate")
            else:
                print(f"\n✅ [COMPLETE] All signals resolved!")
        else:
            print(f"⚠️  Signal outcomes file not found")
    except Exception as e:
        print(f"❌ Error checking progress: {e}")
        import traceback
        traceback.print_exc()
else:
    print(f"⚠️  Pending signals file not found at: {pending_file}")

print("\n" + "=" * 80)
