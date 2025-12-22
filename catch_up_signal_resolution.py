#!/usr/bin/env python3
"""
Catch Up Signal Resolution
==========================
Automatically process ALL pending signals in a continuous loop.
Runs until all signals are resolved or you press Ctrl+C.
"""

import os
import sys
import time
import json
from pathlib import Path
from contextlib import redirect_stdout, redirect_stderr
import io

sys.path.insert(0, os.path.dirname(__file__))

print("=" * 80)
print("CATCH UP SIGNAL RESOLUTION")
print("=" * 80)
print("This script will AUTOMATICALLY process all pending signals")
print("It will run continuously until all signals are resolved")
print("Press Ctrl+C to stop at any time\n")

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
    
    # Process in batches - runs AUTOMATICALLY in a loop
    batch_size = 500
    total_resolved = 0
    cycles = 0
    max_cycles = 200  # Safety limit (200 cycles × 500 = 100k signals max)
    
    print(f"Processing {batch_size} signals per cycle...")
    print(f"Running AUTOMATICALLY - will continue until all {pending_count:,} signals are resolved\n")
    
    try:
        while pending_count > 0 and cycles < max_cycles:
            cycles += 1
            start_time = time.time()
            
            # Capture output to check if signals are being removed
            f = io.StringIO()
            with redirect_stdout(f), redirect_stderr(f):
                resolved = signal_tracker.resolve_pending_signals(
                    max_signals_per_cycle=batch_size, 
                    throttle_ms=0
                )
            
            # Check output for save messages
            output = f.getvalue()
            if "Saved pending_signals.json" in output:
                # Extract how many were removed
                import re
                match = re.search(r'removed (\d+) resolved signals', output)
                if match:
                    removed_count = int(match.group(1))
                    if removed_count > 0:
                        print(f"   ✅ Removed {removed_count} fully resolved signals from pending list")
            
            elapsed = time.time() - start_time
            total_resolved += resolved
            
            # Recheck pending count
            if pending_file.exists():
                with open(pending_file, 'r') as f:
                    pending_data = json.load(f)
                    if isinstance(pending_data, dict):
                        pending_count = len(pending_data)
                    else:
                        pending_count = len(pending_data) if isinstance(pending_data, list) else 0
            
            # Show progress every cycle
            progress_pct = ((total_resolved / (total_resolved + pending_count)) * 100) if (total_resolved + pending_count) > 0 else 0
            print(f"[Cycle {cycles}] Resolved: {resolved} | Total: {total_resolved} | Remaining: {pending_count:,} | Progress: {progress_pct:.1f}% | Time: {elapsed:.1f}s")
            
            if pending_count == 0:
                print("\n✅ All signals resolved!")
                break
            
            # Small delay to prevent CPU overload
            time.sleep(0.5)
        
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
