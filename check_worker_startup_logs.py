#!/usr/bin/env python3
"""
Check Worker Startup Logs
==========================
Check if workers are actually being started and why they might be failing.
"""

import sys
import os
import subprocess
from datetime import datetime

def check_startup_logs():
    """Check recent logs for worker startup messages."""
    print("="*80)
    print("WORKER STARTUP LOG ANALYSIS")
    print("="*80)
    print(f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print()
    
    # Check for worker startup messages
    print("1. Checking for worker startup messages...")
    try:
        result = subprocess.run(
            ["journalctl", "-u", "tradingbot", "--since", "30 minutes ago", "--no-pager"],
            capture_output=True,
            text=True,
            timeout=15
        )
        
        if result.returncode == 0:
            lines = result.stdout.split('\n')
            
            # Look for key messages
            startup_messages = {
                "Starting Worker Processes": [],
                "predictive_engine": [],
                "ensemble_predictor": [],
                "signal_resolver": [],
                "feature_builder": [],
                "Process started": [],
                "Failed to start": [],
                "Crash": [],
                "ERROR": []
            }
            
            for line in lines:
                for key in startup_messages.keys():
                    if key.lower() in line.lower():
                        startup_messages[key].append(line)
            
            # Show results
            for key, matches in startup_messages.items():
                if matches:
                    print(f"\n   {key}:")
                    for match in matches[-5:]:  # Last 5 matches
                        print(f"      {match[:150]}")
            
            # Check if _start_all_worker_processes was called
            called = any("Starting Worker Processes" in line for line in lines)
            if called:
                print("\n   ✅ _start_all_worker_processes() WAS CALLED")
            else:
                print("\n   ❌ _start_all_worker_processes() WAS NOT CALLED")
                print("      This means workers are never being started!")
            
            # Check for errors
            errors = [line for line in lines if "ERROR" in line or "Exception" in line or "Traceback" in line]
            if errors:
                print(f"\n   ⚠️  Found {len(errors)} error lines:")
                for error in errors[-10:]:  # Last 10 errors
                    print(f"      {error[:150]}")
        
    except Exception as e:
        print(f"   ⚠️  Error checking logs: {e}")
    
    print("\n" + "="*80)
    print("2. Checking if run_heavy_initialization is being called...")
    print("="*80)
    
    try:
        result = subprocess.run(
            ["journalctl", "-u", "tradingbot", "--since", "30 minutes ago", "--grep", "run_heavy_initialization|Heavy initialization", "--no-pager"],
            capture_output=True,
            text=True,
            timeout=10
        )
        
        if result.returncode == 0 and result.stdout.strip():
            print("   ✅ run_heavy_initialization messages found")
            lines = result.stdout.split('\n')
            for line in lines[-5:]:
                print(f"      {line[:150]}")
        else:
            print("   ⚠️  No run_heavy_initialization messages found")
            print("      This might mean it's not being called or not logging")
    
    except Exception as e:
        print(f"   ⚠️  Error: {e}")
    
    print("\n" + "="*80)
    print("3. RECOMMENDATIONS")
    print("="*80)
    print("   If _start_all_worker_processes() was NOT called:")
    print("      → Workers are never being started")
    print("      → Check if run_heavy_initialization() is completing")
    print("      → Check for errors preventing worker startup")
    print()
    print("   If workers are starting but crashing:")
    print("      → Check error messages above")
    print("      → Workers may be failing immediately after startup")
    print()
    print("   Next steps:")
    print("      1. Check full logs: journalctl -u tradingbot --since '30 minutes ago' | tail -100")
    print("      2. Look for worker startup messages")
    print("      3. Check for errors in worker processes")

if __name__ == "__main__":
    check_startup_logs()
