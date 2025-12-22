#!/usr/bin/env python3
"""
Catch Up Signal Resolution
==========================
Manually process pending signals to catch up while worker process is fixed.
"""

import os
import sys
import time
from pathlib import Path

sys.path.insert(0, os.path.dirname(__file__))

print("=" * 80)
print("CATCH UP SIGNAL RESOLUTION")
print("=" * 80)

from src.signal_outcome_tracker import signal_tracker

# Check current status
pending_file = Path("feature_store/pending_signals.json")
if pending_file.exists():
    import json
    with open(pending_file, 'r') as f:
        pending_data = json.load(f)
        if isinstance(pending_data, dict):
            pending_count = len(pending_data)
        else:
            pending_count = len(pending_data) if isinstance(pending_data, list) else 0
    
    print(f"\nCurrent pending signals: {pending_count:,}")
    
    if pending_count == 0:
        print("✅ No pending signals - all caught up!")
        sys.exit(0)
    
    # Process in batches
    batch_size = 500
    total_resolved = 0
    cycles = 0
    max_cycles = 100  # Safety limit
    
    print(f"\nProcessing {batch_size} signals per cycle...")
    print(f"Press Ctrl+C to stop\n")
    
    try:
        while pending_count > 0 and cycles < max_cycles:
            cycles += 1
            print(f"\n[Cycle {cycles}] Processing batch of {batch_size} signals...")
            
            resolved = signal_tracker.resolve_pending_signals(
                max_signals_per_cycle=batch_size, 
                throttle_ms=0
            )
            
            total_resolved += resolved
            
            # Recheck pending count
            if pending_file.exists():
                with open(pending_file, 'r') as f:
                    pending_data = json.load(f)
                    if isinstance(pending_data, dict):
                        pending_count = len(pending_data)
                    else:
                        pending_count = len(pending_data) if isinstance(pending_data, list) else 0
            
            print(f"   Resolved: {resolved} signals this cycle")
            print(f"   Total resolved: {total_resolved}")
            print(f"   Remaining: {pending_count:,}")
            
            if pending_count == 0:
                print("\n✅ All signals resolved!")
                break
            
            # Small delay to prevent CPU overload
            time.sleep(1)
        
        print("\n" + "=" * 80)
        print(f"SUMMARY:")
        print(f"   Cycles run: {cycles}")
        print(f"   Total signals resolved: {total_resolved}")
        print(f"   Remaining: {pending_count:,}")
        print("=" * 80)
        
    except KeyboardInterrupt:
        print(f"\n\n⏸️  Stopped by user")
        print(f"   Resolved {total_resolved} signals in {cycles} cycles")
        print(f"   Remaining: {pending_count:,}")
else:
    print("❌ Pending signals file not found")
