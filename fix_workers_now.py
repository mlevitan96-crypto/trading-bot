#!/usr/bin/env python3
"""
Fix Workers Now - Immediate Fix
=================================
This script will:
1. Stop the restart loop
2. Verify workers can start
3. Check for errors preventing worker startup
4. Provide clear next steps
"""

import sys
import os
import subprocess
import time
from pathlib import Path

print("="*80)
print("IMMEDIATE WORKER FIX")
print("="*80)
print()

# 1. Check if bot service is running
print("1. Checking bot service status...")
try:
    result = subprocess.run(
        ["systemctl", "is-active", "tradingbot"],
        capture_output=True,
        text=True,
        timeout=5
    )
    
    if result.returncode == 0:
        print("   ✅ Bot service is running")
        print("   ⚠️  Stopping bot to break any restart loops...")
        subprocess.run(["sudo", "systemctl", "stop", "tradingbot"], timeout=10)
        time.sleep(2)
    else:
        print("   ℹ️  Bot service is not running")
except Exception as e:
    print(f"   ⚠️  Error: {e}")

# 2. Check for worker processes
print("\n2. Checking for existing worker processes...")
try:
    workers = ["predictive_engine", "ensemble_predictor", "signal_resolver", "feature_builder"]
    for worker in workers:
        result = subprocess.run(
            ["pgrep", "-f", worker],
            capture_output=True,
            text=True,
            timeout=5
        )
        if result.returncode == 0:
            pids = result.stdout.strip().split('\n')
            print(f"   ⚠️  {worker} process(es) found: {', '.join(pids)}")
            print(f"      Killing to ensure clean restart...")
            for pid in pids:
                try:
                    subprocess.run(["kill", "-9", pid], timeout=5)
                except:
                    pass
        else:
            print(f"   ✅ No {worker} processes running (clean state)")
except Exception as e:
    print(f"   ⚠️  Error checking processes: {e}")

# 3. Pull latest code
print("\n3. Pulling latest code...")
try:
    result = subprocess.run(
        ["git", "pull", "origin", "main"],
        cwd="/root/trading-bot-current",
        capture_output=True,
        text=True,
        timeout=30
    )
    if result.returncode == 0:
        print("   ✅ Code updated")
    else:
        print(f"   ⚠️  Git pull had issues: {result.stderr[:200]}")
except Exception as e:
    print(f"   ⚠️  Error: {e}")

# 4. Start bot service
print("\n4. Starting bot service...")
try:
    result = subprocess.run(
        ["sudo", "systemctl", "start", "tradingbot"],
        capture_output=True,
        text=True,
        timeout=10
    )
    if result.returncode == 0:
        print("   ✅ Bot service started")
    else:
        print(f"   ❌ Failed to start: {result.stderr[:200]}")
except Exception as e:
    print(f"   ❌ Error starting bot: {e}")

# 5. Wait and check
print("\n5. Waiting 30 seconds for workers to start...")
time.sleep(30)

# 6. Check workers
print("\n6. Checking worker status...")
try:
    workers = {
        "predictive_engine": "predictive_engine",
        "ensemble_predictor": "ensemble_predictor",
        "signal_resolver": "signal_resolver",
        "feature_builder": "feature_builder"
    }
    
    running = []
    not_running = []
    
    for name, pattern in workers.items():
        result = subprocess.run(
            ["pgrep", "-f", pattern],
            capture_output=True,
            text=True,
            timeout=5
        )
        
        if result.returncode == 0 and result.stdout.strip():
            pids = result.stdout.strip().split('\n')
            running.append(f"{name} (PIDs: {', '.join(pids)})")
        else:
            not_running.append(name)
    
    if running:
        print("   ✅ Running workers:")
        for worker in running:
            print(f"      - {worker}")
    
    if not_running:
        print("   ❌ Workers NOT running:")
        for worker in not_running:
            print(f"      - {worker}")
    
    print("\n" + "="*80)
    if not_running:
        print("⚠️  SOME WORKERS ARE NOT RUNNING")
        print()
        print("Next steps:")
        print("1. Check logs for worker startup errors:")
        print("   journalctl -u tradingbot --since '5 minutes ago' | grep -i 'worker\\|ensemble\\|predictive\\|ERROR\\|Exception'")
        print()
        print("2. Check if _start_all_worker_processes() was called:")
        print("   journalctl -u tradingbot --since '5 minutes ago' | grep -i 'Starting Worker Processes'")
        print()
        print("3. Run diagnostic script:")
        print("   python3 check_worker_startup_logs.py")
    else:
        print("✅ ALL WORKERS ARE RUNNING!")
        print()
        print("Verify output files are updating:")
        print("   python3 verify_workers_running.py")
    print("="*80)

except Exception as e:
    print(f"   ⚠️  Error checking workers: {e}")
    import traceback
    traceback.print_exc()
