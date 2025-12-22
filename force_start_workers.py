#!/usr/bin/env python3
"""
Force Start Workers - Direct Fix
==================================
Directly start worker processes without going through the bot service.
This bypasses any issues in run_heavy_initialization.
"""

import sys
import os
import time
import multiprocessing
from pathlib import Path

sys.path.insert(0, os.path.dirname(__file__))

# Import worker functions
from src.run import (
    _worker_predictive_engine,
    _worker_ensemble_predictor,
    _worker_signal_resolver,
    _worker_feature_builder,
    _start_worker_process
)

def main():
    print("="*80)
    print("FORCE STARTING WORKERS")
    print("="*80)
    print()
    
    workers = [
        ("predictive_engine", _worker_predictive_engine),
        ("ensemble_predictor", _worker_ensemble_predictor),
        ("signal_resolver", _worker_signal_resolver),
        ("feature_builder", _worker_feature_builder),
    ]
    
    started = []
    failed = []
    
    for name, func in workers:
        print(f"Starting {name}...")
        try:
            process = _start_worker_process(name, func, restart_on_crash=True)
            if process:
                started.append(name)
                print(f"   ✅ {name} started (PID: {process.pid})")
            else:
                failed.append(name)
                print(f"   ❌ {name} failed to start")
        except Exception as e:
            failed.append(name)
            print(f"   ❌ {name} error: {e}")
            import traceback
            traceback.print_exc()
        print()
    
    print("="*80)
    print("SUMMARY")
    print("="*80)
    print(f"✅ Started: {len(started)} workers")
    if started:
        for name in started:
            print(f"   - {name}")
    print()
    
    if failed:
        print(f"❌ Failed: {len(failed)} workers")
        for name in failed:
            print(f"   - {name}")
    else:
        print("✅ All workers started successfully!")
    
    print()
    print("Workers are now running. Wait 30 seconds, then verify:")
    print("   python3 verify_workers_running.py")
    print("="*80)

if __name__ == "__main__":
    main()
