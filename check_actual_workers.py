#!/usr/bin/env python3
"""
Check Actual Running Workers
============================
Check what's actually running by looking at python processes and their command lines.
"""

import subprocess
import sys
import os
from pathlib import Path

def get_python_processes():
    """Get all python processes with their command lines."""
    try:
        result = subprocess.run(
            ["ps", "aux"],
            capture_output=True,
            text=True,
            timeout=5
        )
        processes = []
        for line in result.stdout.split('\n'):
            if 'python' in line.lower() and 'run.py' in line:
                processes.append(line)
        return processes
    except Exception as e:
        print(f"Error getting processes: {e}")
        return []

def check_worker_files():
    """Check if worker output files are updating."""
    from src.infrastructure.path_registry import PathRegistry
    import time
    
    path_registry = PathRegistry()
    
    checks = {
        "predictive_signals.jsonl": path_registry.get_path("logs", "predictive_signals.jsonl"),
        "ensemble_predictions.jsonl": path_registry.get_path("logs", "ensemble_predictions.jsonl"),
        "pending_signals.json": path_registry.get_path("feature_store", "pending_signals.json"),
    }
    
    print("="*80)
    print("WORKER FILE STATUS")
    print("="*80)
    
    for name, path in checks.items():
        p = Path(path)
        if p.exists():
            age = (time.time() - p.stat().st_mtime) / 60
            status = "🟢 ACTIVE" if age < 5 else "🟡 STALE" if age < 60 else "🔴 INACTIVE"
            print(f"{status} {name}: {age:.1f} min old")
        else:
            print(f"❌ {name}: File does not exist")
    
    print("="*80)

def main():
    print("="*80)
    print("ACTUAL WORKER STATUS CHECK")
    print("="*80)
    print()
    
    # Check python processes
    print("Python processes running run.py:")
    processes = get_python_processes()
    if processes:
        for proc in processes:
            print(f"   {proc.strip()}")
    else:
        print("   No python processes found running run.py")
    print()
    
    # Check worker files
    check_worker_files()
    print()
    
    # Check systemd service
    print("="*80)
    print("SYSTEMD SERVICE STATUS")
    print("="*80)
    try:
        result = subprocess.run(
            ["systemctl", "is-active", "tradingbot"],
            capture_output=True,
            text=True,
            timeout=5
        )
        if result.returncode == 0:
            print("✅ tradingbot service is ACTIVE")
        else:
            print("❌ tradingbot service is NOT ACTIVE")
    except Exception as e:
        print(f"Error checking service: {e}")
    
    print()
    print("="*80)
    print("RECOMMENDATION")
    print("="*80)
    print("If files are updating, workers ARE running (just not showing in pgrep).")
    print("The process names don't match what pgrep is looking for.")
    print("="*80)

if __name__ == "__main__":
    sys.path.insert(0, os.path.dirname(__file__))
    main()
