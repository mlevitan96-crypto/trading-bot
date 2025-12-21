#!/usr/bin/env python3
"""
Check Signal Resolution Progress
================================
Shows how many signals are left to resolve and estimated time remaining.
"""

import os
import sys
import json
from pathlib import Path

sys.path.insert(0, os.path.dirname(__file__))

print("=" * 80)
print("SIGNAL RESOLUTION PROGRESS")
print("=" * 80)

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
        
        print(f"\nPending Signals: {pending_count:,}")
        
        # Check signal outcomes (to see how many have been resolved)
        outcomes_file = Path("logs/signal_outcomes.jsonl")
        if outcomes_file.exists():
            with open(outcomes_file, 'r') as f:
                outcomes_count = sum(1 for line in f if line.strip())
            print(f"Resolved Outcomes: {outcomes_count:,}")
            
            # Estimate time
            # Each signal resolves at 5 horizons, so ~5 outcomes per signal
            # But outcomes file may have old entries too
            # Rough estimate: if we started with 30,427 pending
            # and outcomes increased significantly, we're making progress
            
            if pending_count > 0:
                # UPDATED: Batch processing mode (200 signals per cycle, 60s per cycle)
                # Each signal resolves at 5 horizons, but we process 200 signals per cycle
                signals_per_cycle = 200  # From resolve_pending_signals(max_signals_per_cycle=200)
                cycle_interval_seconds = 60  # Healing cycle runs every 60 seconds
                
                # Calculate cycles needed
                cycles_needed = (pending_count + signals_per_cycle - 1) // signals_per_cycle  # Ceiling division
                total_seconds = cycles_needed * cycle_interval_seconds
                minutes_remaining = total_seconds / 60
                hours_remaining = minutes_remaining / 60
                
                print(f"\nEstimated Time Remaining (Batch Processing Mode):")
                print(f"   Processing: {signals_per_cycle} signals per cycle")
                print(f"   Cycle interval: {cycle_interval_seconds} seconds")
                print(f"   Cycles needed: {cycles_needed:,}")
                
                if hours_remaining < 1:
                    print(f"   Time: ~{int(minutes_remaining)} minutes")
                else:
                    hours = int(hours_remaining)
                    mins = int(minutes_remaining % 60)
                    print(f"   Time: ~{hours} hours {mins} minutes")
                
                # Progress calculation (assuming we started with ~30,427 signals)
                initial_count = 30427  # Approximate starting point
                if initial_count > pending_count:
                    progress_pct = ((initial_count - pending_count) / initial_count) * 100
                    print(f"\nProgress: {progress_pct:.1f}% complete")
                else:
                    # More signals added since start
                    resolved_estimate = outcomes_count // 5  # Rough: 5 outcomes per signal
                    if resolved_estimate > 0:
                        progress_pct = (resolved_estimate / (resolved_estimate + pending_count)) * 100
                        print(f"\nProgress: ~{progress_pct:.1f}% complete (estimated)")
                    else:
                        print(f"\nProgress: Calculating...")
            else:
                print(f"\n[COMPLETE] All signals resolved!")
        else:
            print(f"Signal outcomes file not found")
    except Exception as e:
        print(f"Error checking progress: {e}")
else:
    print(f"Pending signals file not found")

print("\n" + "=" * 80)
