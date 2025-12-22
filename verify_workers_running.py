#!/usr/bin/env python3
"""
Verify Workers Are Running
==========================
Check if workers are actually running and producing output after restart.
"""

import sys
import os
import time
import subprocess
from pathlib import Path
from datetime import datetime

sys.path.insert(0, os.path.dirname(__file__))

def check_worker_process(worker_name):
    """Check if a worker process is running."""
    # Workers run as separate multiprocessing.Process instances
    # They all show up as python3 processes running run.py
    # The best way to verify they're running is to check if output files are updating
    # But we can also check for multiple python processes running run.py
    
    try:
        # Check for python processes running run.py
        # If we see multiple processes (main + workers), workers are likely running
        result = subprocess.run(
            ["ps", "aux"],
            capture_output=True,
            text=True,
            timeout=5
        )
        run_py_processes = [line for line in result.stdout.split('\n') 
                           if 'python' in line.lower() and 'run.py' in line]
        
        # If we have multiple processes (main + at least 1 worker), workers are running
        # The exact count varies, but if files are updating, workers are definitely running
        if len(run_py_processes) > 1:
            return True  # Multiple processes = workers are running
    except:
        pass
    
    # Fallback: If we can't detect processes but files are updating, assume workers are running
    # This is handled by the file check in the main function
    return False

def check_file_updating(file_path, max_age_minutes=5):
    """Check if a file exists and is being updated."""
    path = Path(file_path)
    if not path.exists():
        return False, "File does not exist"
    
    mtime = path.stat().st_mtime
    age_minutes = (time.time() - mtime) / 60
    
    if age_minutes > max_age_minutes:
        return False, f"File is stale ({age_minutes:.1f} min old)"
    else:
        return True, f"File is updating ({age_minutes:.1f} min old)"

def main():
    print("="*80)
    print("WORKER STATUS VERIFICATION")
    print("="*80)
    print(f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print()
    
    workers = {
        "predictive_engine": {
            "process_name": "predictive_engine",
            "output_file": "logs/predictive_signals.jsonl",
            "max_age": 5
        },
        "ensemble_predictor": {
            "process_name": "ensemble_predictor",
            "output_file": "logs/ensemble_predictions.jsonl",
            "max_age": 5
        },
        "signal_resolver": {
            "process_name": "signal_resolver",
            "output_file": "feature_store/pending_signals.json",
            "max_age": 5
        },
        "feature_builder": {
            "process_name": "feature_builder",
            "output_file": "feature_store/features_*.json",
            "max_age": 60
        }
    }
    
    # Use PathRegistry for proper path resolution
    try:
        from src.infrastructure.path_registry import PathRegistry
        path_registry = PathRegistry()
    except:
        path_registry = None
    
    all_ok = True
    
    for worker_name, worker_info in workers.items():
        print(f"Checking {worker_name}...")
        
        # Check process (workers run as separate python processes)
        is_running = check_worker_process(worker_info["process_name"])
        if is_running:
            print(f"   ✅ Process: Running (detected via multiple run.py processes)")
        else:
            # Don't fail if process not detected - file check is more reliable
            print(f"   ⚠️  Process: Not detected (but may be running as separate process)")
        
        # Check output file
        output_file = worker_info["output_file"]
        if path_registry:
            try:
                if "logs/" in output_file:
                    file_path = path_registry.get_path("logs", output_file.replace("logs/", ""))
                elif "feature_store/" in output_file:
                    file_path = path_registry.get_path("feature_store", output_file.replace("feature_store/", ""))
                else:
                    file_path = output_file
            except:
                file_path = output_file
        else:
            file_path = output_file
        
        # For wildcard patterns, just check directory
        if "*" in file_path:
            dir_path = Path(file_path).parent
            if dir_path.exists():
                files = list(dir_path.glob(Path(file_path).name))
                if files:
                    # Check most recent file
                    latest_file = max(files, key=lambda p: p.stat().st_mtime)
                    is_updating, status = check_file_updating(str(latest_file), worker_info["max_age"])
                    print(f"   {'✅' if is_updating else '⚠️ '} Output: {status} ({latest_file.name})")
                    if not is_updating:
                        all_ok = False
                else:
                    print(f"   ⚠️  Output: No files matching pattern")
                    all_ok = False
            else:
                print(f"   ❌ Output: Directory does not exist")
                all_ok = False
        else:
            is_updating, status = check_file_updating(file_path, worker_info["max_age"])
            print(f"   {'✅' if is_updating else '⚠️ '} Output: {status}")
            if not is_updating:
                all_ok = False
        
        print()
    
    print("="*80)
    if all_ok:
        print("✅ ALL WORKERS ARE RUNNING AND PRODUCING OUTPUT")
        print()
        print("   Workers are running as separate processes (multiprocessing).")
        print("   File updates confirm workers are actively generating data.")
    else:
        print("⚠️  SOME WORKERS HAVE ISSUES")
        print()
        print("   Check output file status above.")
        print("   If files are updating, workers ARE running (process detection may be limited).")
        print()
        print("   For detailed process info, run:")
        print("   python3 check_actual_workers.py")
    print("="*80)
    
    return 0 if all_ok else 1

if __name__ == "__main__":
    sys.exit(main())
