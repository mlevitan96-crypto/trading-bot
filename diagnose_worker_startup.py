#!/usr/bin/env python3
"""
Diagnose Worker Startup Issues
================================
Check why workers aren't starting and provide actionable fixes.
"""

import sys
import os
import subprocess
import json
from pathlib import Path
from datetime import datetime

def check_bot_service():
    """Check if bot service is running."""
    print("="*80)
    print("1. BOT SERVICE STATUS")
    print("="*80)
    
    try:
        result = subprocess.run(
            ["systemctl", "is-active", "tradingbot"],
            capture_output=True,
            text=True,
            timeout=5
        )
        
        if result.returncode == 0:
            print(f"   ✅ Bot service: ACTIVE")
            
            # Get service status
            status_result = subprocess.run(
                ["systemctl", "status", "tradingbot", "--no-pager"],
                capture_output=True,
                text=True,
                timeout=10
            )
            
            if status_result.returncode == 0:
                lines = status_result.stdout.split('\n')
                for line in lines[:10]:
                    if line.strip():
                        print(f"      {line}")
            
            return True
        else:
            print(f"   ❌ Bot service: INACTIVE")
            print(f"      Output: {result.stdout.strip()}")
            return False
    except Exception as e:
        print(f"   ⚠️  Error checking service: {e}")
        return False

def check_worker_processes():
    """Check for worker processes."""
    print("\n" + "="*80)
    print("2. WORKER PROCESSES")
    print("="*80)
    
    workers = {
        "predictive_engine": "predictive_engine",
        "ensemble_predictor": "ensemble_predictor",
        "signal_resolver": "signal_resolver",
        "feature_builder": "feature_builder"
    }
    
    found_workers = []
    missing_workers = []
    
    for name, pattern in workers.items():
        try:
            result = subprocess.run(
                ["pgrep", "-f", pattern],
                capture_output=True,
                text=True,
                timeout=5
            )
            
            if result.returncode == 0 and result.stdout.strip():
                pids = result.stdout.strip().split('\n')
                print(f"   ✅ {name}: Running (PIDs: {', '.join(pids)})")
                found_workers.append(name)
            else:
                print(f"   ❌ {name}: NOT RUNNING")
                missing_workers.append(name)
        except Exception as e:
            print(f"   ⚠️  {name}: Error checking - {e}")
            missing_workers.append(name)
    
    return found_workers, missing_workers

def check_recent_logs():
    """Check recent bot logs for errors."""
    print("\n" + "="*80)
    print("3. RECENT LOGS (Last 50 lines)")
    print("="*80)
    
    # Check journalctl for recent errors
    try:
        result = subprocess.run(
            ["journalctl", "-u", "tradingbot", "--since", "10 minutes ago", "-n", "50", "--no-pager"],
            capture_output=True,
            text=True,
            timeout=10
        )
        
        if result.returncode == 0:
            lines = result.stdout.split('\n')
            
            # Look for worker-related messages
            worker_lines = []
            error_lines = []
            
            for line in lines:
                if any(worker in line.lower() for worker in ["predictive", "ensemble", "signal_resolver", "feature_builder", "worker"]):
                    worker_lines.append(line)
                if any(keyword in line.lower() for keyword in ["error", "exception", "traceback", "failed", "crash"]):
                    error_lines.append(line)
            
            if worker_lines:
                print("   Worker-related messages:")
                for line in worker_lines[:20]:
                    print(f"      {line}")
            
            if error_lines:
                print("\n   ⚠️  Errors found:")
                for line in error_lines[:20]:
                    print(f"      {line}")
            
            if not worker_lines and not error_lines:
                print("   ℹ️  No worker-related messages in last 10 minutes")
                print("   Showing last 20 log lines:")
                for line in lines[-20:]:
                    if line.strip():
                        print(f"      {line}")
        else:
            print(f"   ⚠️  Could not read logs: {result.stderr}")
    except Exception as e:
        print(f"   ⚠️  Error reading logs: {e}")

def check_startup_sequence():
    """Check if workers are being started in run.py."""
    print("\n" + "="*80)
    print("4. STARTUP SEQUENCE CHECK")
    print("="*80)
    
    run_py = Path("src/run.py")
    if not run_py.exists():
        print(f"   ❌ src/run.py not found")
        return
    
    # Check for worker startup code
    with open(run_py, 'r') as f:
        content = f.read()
    
    checks = {
        "_start_all_worker_processes": "_start_all_worker_processes" in content,
        "_worker_predictive_engine": "_worker_predictive_engine" in content,
        "_worker_ensemble_predictor": "_worker_ensemble_predictor" in content,
        "_worker_signal_resolver": "_worker_signal_resolver" in content,
        "_worker_feature_builder": "_worker_feature_builder" in content,
        "_monitor_worker_processes": "_monitor_worker_processes" in content,
    }
    
    for check, found in checks.items():
        status = "✅" if found else "❌"
        print(f"   {status} {check}: {'Found' if found else 'Missing'}")
    
    # Check if _start_all_worker_processes is called
    if "_start_all_worker_processes()" in content:
        print(f"   ✅ _start_all_worker_processes() is called")
    else:
        print(f"   ⚠️  _start_all_worker_processes() may not be called")

def provide_recommendations(found_workers, missing_workers, bot_active):
    """Provide actionable recommendations."""
    print("\n" + "="*80)
    print("5. RECOMMENDATIONS")
    print("="*80)
    
    if not bot_active:
        print("   🔴 CRITICAL: Bot service is not running")
        print("      Action: sudo systemctl start tradingbot")
        print("      Then wait 30 seconds and check again")
        return
    
    if missing_workers:
        print(f"   ⚠️  {len(missing_workers)} workers are not running:")
        for worker in missing_workers:
            print(f"      - {worker}")
        
        print("\n   Actions:")
        print("   1. Check bot logs for worker startup errors:")
        print("      journalctl -u tradingbot --since '10 minutes ago' | grep -i 'worker\\|ensemble\\|predictive'")
        print()
        print("   2. Restart bot service to restart workers:")
        print("      sudo systemctl restart tradingbot")
        print("      sleep 30")
        print("      python3 verify_workers_running.py")
        print()
        print("   3. Check if workers are crashing immediately:")
        print("      journalctl -u tradingbot --since '5 minutes ago' | grep -i 'error\\|exception\\|traceback'")
        print()
        print("   4. Run architecture-aware healing:")
        print("      python3 run_architecture_healing.py")
    else:
        print("   ✅ All workers appear to be running")
        print("   Run: python3 verify_workers_running.py to verify output files")

def main():
    print("="*80)
    print("WORKER STARTUP DIAGNOSIS")
    print("="*80)
    print(f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print()
    
    # 1. Check bot service
    bot_active = check_bot_service()
    
    # 2. Check worker processes
    found_workers, missing_workers = check_worker_processes()
    
    # 3. Check recent logs
    check_recent_logs()
    
    # 4. Check startup sequence
    check_startup_sequence()
    
    # 5. Provide recommendations
    provide_recommendations(found_workers, missing_workers, bot_active)
    
    print("\n" + "="*80)
    print("DIAGNOSIS COMPLETE")
    print("="*80)

if __name__ == "__main__":
    main()
