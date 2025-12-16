#!/usr/bin/env python3
"""
Diagnose Signal Engine Status - Detailed diagnostics for why signal engine is red
"""

import os
import sys
import time
from pathlib import Path

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

def diagnose_signal_engine():
    """Detailed diagnosis of signal engine status."""
    print("=" * 70)
    print("SIGNAL ENGINE DIAGNOSTICS")
    print("=" * 70)
    
    from src.infrastructure.path_registry import PathRegistry
    from src.signal_integrity import get_status
    
    # Get status
    status = get_status()
    signal_status = status.get('signal_engine', 'unknown')
    print(f"\nCurrent Status: {signal_status.upper()}")
    
    # Check each file individually
    signal_files = {
        "signals.jsonl": PathRegistry.get_path("logs", "signals.jsonl"),
        "ensemble_predictions.jsonl": PathRegistry.get_path("logs", "ensemble_predictions.jsonl"),
    }
    
    print("\n" + "-" * 70)
    print("FILE STATUS")
    print("-" * 70)
    
    all_exist = True
    all_recent = True
    
    for name, file_path in signal_files.items():
        path_obj = Path(file_path)
        exists = path_obj.exists()
        
        print(f"\n  {name}:")
        print(f"    Path: {file_path}")
        print(f"    Exists: {exists}")
        
        if not exists:
            all_exist = False
            print(f"    [MISSING] File does not exist")
            print(f"    Action: Run 'python3 force_heal_files.py' to create it")
        else:
            # Check age
            file_age = time.time() - path_obj.stat().st_mtime
            age_minutes = file_age / 60
            age_seconds = file_age
            
            print(f"    Age: {age_minutes:.1f} minutes ({age_seconds:.0f} seconds)")
            
            if file_age > 600:  # >10 minutes
                all_recent = False
                print(f"    [STALE] File is older than 10 minutes")
                print(f"    Action: Healing operator should update this (runs every 60 seconds)")
            else:
                print(f"    [RECENT] File is fresh (<10 minutes old)")
            
            # Check file size
            size = path_obj.stat().st_size
            print(f"    Size: {size} bytes")
            
            if size > 0:
                # Try to read last line
                try:
                    with open(file_path, 'r') as f:
                        lines = f.readlines()
                        if lines:
                            last_line = lines[-1].strip()
                            print(f"    Last entry: {last_line[:100]}..." if len(last_line) > 100 else f"    Last entry: {last_line}")
                except Exception as e:
                    print(f"    [ERROR] Could not read file: {e}")
    
    # Summary
    print("\n" + "=" * 70)
    print("DIAGNOSIS")
    print("=" * 70)
    
    if not all_exist:
        print("\n[ISSUE] One or more files are missing")
        print("  Solution: Run 'python3 force_heal_files.py'")
    elif not all_recent:
        print("\n[ISSUE] One or more files are stale (>10 minutes old)")
        print("  Solution: Check if healing operator is running")
        print("  - Healing operator should update stale files every 60 seconds")
        print("  - If not running, restart the bot to start healing operator")
    else:
        print("\n[OK] All files exist and are recent")
        print("  If status is still red, there may be a bug in signal_integrity.py")
    
    # Check healing operator
    print("\n" + "-" * 70)
    print("HEALING OPERATOR CHECK")
    print("-" * 70)
    
    try:
        from src.healing_operator import HealingOperator
        print("  [OK] Healing operator module can be imported")
        print("  Note: Check bot logs to verify healing operator thread is running")
    except Exception as e:
        print(f"  [WARNING] Could not import healing operator: {e}")
    
    return 0


if __name__ == "__main__":
    sys.exit(diagnose_signal_engine())

