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
                # Rough estimate: ~10-20 signals per second based on logs
                signals_per_second = 15  # Conservative estimate
                seconds_remaining = pending_count / signals_per_second
                minutes_remaining = seconds_remaining / 60
                
                print(f"\nEstimated Time Remaining:")
                if minutes_remaining < 1:
                    print(f"   ~{int(seconds_remaining)} seconds")
                elif minutes_remaining < 60:
                    print(f"   ~{int(minutes_remaining)} minutes")
                else:
                    hours = int(minutes_remaining / 60)
                    mins = int(minutes_remaining % 60)
                    print(f"   ~{hours} hours {mins} minutes")
                
                print(f"\nProgress: {((30427 - pending_count) / 30427 * 100):.1f}% complete")
            else:
                print(f"\n[COMPLETE] All signals resolved!")
        else:
            print(f"Signal outcomes file not found")
    except Exception as e:
        print(f"Error checking progress: {e}")
else:
    print(f"Pending signals file not found")

print("\n" + "=" * 80)
