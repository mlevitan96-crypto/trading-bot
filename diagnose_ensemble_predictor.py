#!/usr/bin/env python3
"""
Diagnose Ensemble Predictor Worker
===================================
Deep dive into why ensemble predictor isn't generating predictions.
"""

import os
import sys
import json
import subprocess
from pathlib import Path
from datetime import datetime

sys.path.insert(0, os.path.dirname(__file__))

print("=" * 80)
print("ENSEMBLE PREDICTOR DIAGNOSIS")
print("=" * 80)
print(f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
print()

# ============================================================================
# 1. CHECK IF WORKER IS STARTED
# ============================================================================
print("=" * 80)
print("1. CHECKING WORKER PROCESS STATUS")
print("=" * 80)

# Check if worker processes are running
try:
    result = subprocess.run(['ps', 'aux'], capture_output=True, text=True, timeout=5)
    processes = result.stdout
    
    ensemble_found = 'ensemble' in processes.lower() or 'ENSEMBLE' in processes
    predictive_found = 'predictive' in processes.lower() or 'PREDICTIVE' in processes
    
    print(f"   Ensemble predictor process: {'✅ FOUND' if ensemble_found else '❌ NOT FOUND'}")
    print(f"   Predictive engine process: {'✅ FOUND' if predictive_found else '❌ NOT FOUND'}")
    
    if ensemble_found:
        # Extract relevant lines
        for line in processes.split('\n'):
            if 'ensemble' in line.lower() or 'ENSEMBLE' in line:
                print(f"      {line[:120]}")
except Exception as e:
    print(f"   ⚠️  Error checking processes: {e}")

print()

# ============================================================================
# 2. CHECK STARTUP LOGS
# ============================================================================
print("=" * 80)
print("2. CHECKING STARTUP LOGS")
print("=" * 80)

try:
    result = subprocess.run(['journalctl', '-u', 'tradingbot', '--since', '1 hour ago', 
                           '--grep', 'Starting Worker|ensemble|ENSEMBLE'], 
                          capture_output=True, text=True, timeout=10)
    
    if result.stdout:
        lines = result.stdout.strip().split('\n')
        print(f"   Found {len(lines)} relevant log lines")
        
        # Look for worker startup
        startup_found = False
        for line in lines:
            if 'Starting Worker' in line or 'Starting ensemble' in line or 'ENSEMBLE-PREDICTOR' in line:
                print(f"   ✅ {line[:120]}")
                startup_found = True
        
        if not startup_found:
            print(f"   ⚠️  No worker startup messages found")
            print(f"   This suggests workers may not be starting")
    else:
        print(f"   ⚠️  No relevant logs found")
        print(f"   Checking all recent logs...")
        
        result2 = subprocess.run(['journalctl', '-u', 'tradingbot', '-n', '50'], 
                               capture_output=True, text=True, timeout=10)
        if result2.stdout:
            print(f"   Last 50 log lines:")
            for line in result2.stdout.strip().split('\n')[-10:]:
                print(f"      {line[:120]}")
except Exception as e:
    print(f"   ⚠️  Error checking logs: {e}")

print()

# ============================================================================
# 3. CHECK FOR ERRORS
# ============================================================================
print("=" * 80)
print("3. CHECKING FOR ERRORS")
print("=" * 80)

try:
    result = subprocess.run(['journalctl', '-u', 'tradingbot', '--since', '1 hour ago', 
                           '--grep', 'error|Error|ERROR|exception|Exception|EXCEPTION|failed|Failed|FAILED'], 
                          capture_output=True, text=True, timeout=10)
    
    if result.stdout:
        lines = result.stdout.strip().split('\n')
        print(f"   Found {len(lines)} error/warning lines")
        
        # Filter for ensemble-related errors
        ensemble_errors = [l for l in lines if 'ensemble' in l.lower() or 'ENSEMBLE' in l]
        if ensemble_errors:
            print(f"   ⚠️  Ensemble-related errors:")
            for line in ensemble_errors[:5]:
                print(f"      {line[:120]}")
        else:
            print(f"   ✅ No ensemble-specific errors found")
    else:
        print(f"   ✅ No errors found in last hour")
except Exception as e:
    print(f"   ⚠️  Error checking for errors: {e}")

print()

# ============================================================================
# 4. CHECK FILE DEPENDENCIES
# ============================================================================
print("=" * 80)
print("4. CHECKING FILE DEPENDENCIES")
print("=" * 80)

# Ensemble predictor depends on predictive_signals.jsonl
predictive_signals = Path("logs/predictive_signals.jsonl")
ensemble_predictions = Path("logs/ensemble_predictions.jsonl")

if predictive_signals.exists():
    stat = predictive_signals.stat()
    age_minutes = (datetime.now().timestamp() - stat.st_mtime) / 60
    print(f"   ✅ predictive_signals.jsonl exists (age: {age_minutes:.1f} min)")
    
    # Count lines
    try:
        with open(predictive_signals, 'r') as f:
            lines = sum(1 for _ in f)
        print(f"      Lines: {lines}")
    except:
        print(f"      ⚠️  Could not read file")
else:
    print(f"   ❌ predictive_signals.jsonl does NOT exist")
    print(f"      This would prevent ensemble predictor from working")

if ensemble_predictions.exists():
    stat = ensemble_predictions.stat()
    age_hours = (datetime.now().timestamp() - stat.st_mtime) / 3600
    print(f"   ✅ ensemble_predictions.jsonl exists (age: {age_hours:.1f} hours)")
    
    # Count lines
    try:
        with open(ensemble_predictions, 'r') as f:
            lines = sum(1 for _ in f)
        print(f"      Lines: {lines}")
    except:
        print(f"      ⚠️  Could not read file")
else:
    print(f"   ❌ ensemble_predictions.jsonl does NOT exist")

print()

# ============================================================================
# 5. CHECK IF WORKER IS CALLED
# ============================================================================
print("=" * 80)
print("5. CHECKING IF WORKER STARTUP IS CALLED")
print("=" * 80)

run_py = Path("src/run.py")
if run_py.exists():
    try:
        with open(run_py, 'r') as f:
            content = f.read()
        
        # Check if _start_all_worker_processes is called
        if '_start_all_worker_processes()' in content:
            print(f"   ✅ _start_all_worker_processes() is defined and called")
            
            # Check where it's called
            lines = content.split('\n')
            for i, line in enumerate(lines):
                if '_start_all_worker_processes()' in line and 'def ' not in line:
                    # Show context
                    start = max(0, i-2)
                    end = min(len(lines), i+3)
                    print(f"      Called at line {i+1}:")
                    for j in range(start, end):
                        marker = ">>>" if j == i else "   "
                        print(f"      {marker} {j+1}: {lines[j][:80]}")
                    break
        else:
            print(f"   ❌ _start_all_worker_processes() not found in code")
    except Exception as e:
        print(f"   ⚠️  Error reading run.py: {e}")

print()

# ============================================================================
# 6. RECOMMENDATIONS
# ============================================================================
print("=" * 80)
print("6. RECOMMENDATIONS")
print("=" * 80)

recommendations = []

if not ensemble_found:
    recommendations.append("1. Ensemble predictor worker process is NOT running")
    recommendations.append("   → Check if _start_all_worker_processes() is being called")
    recommendations.append("   → Check startup logs for worker initialization")

if not predictive_signals.exists() or (predictive_signals.exists() and (datetime.now().timestamp() - predictive_signals.stat().st_mtime) > 300):
    recommendations.append("2. Predictive signals file is stale or missing")
    recommendations.append("   → Check if predictive engine worker is running")

if ensemble_predictions.exists() and (datetime.now().timestamp() - ensemble_predictions.stat().st_mtime) > 3600:
    recommendations.append("3. Ensemble predictions file is stale (>1 hour old)")
    recommendations.append("   → Restart bot: sudo systemctl restart tradingbot")
    recommendations.append("   → Wait 2 minutes, then check: python3 check_signal_generation.py")

if recommendations:
    for rec in recommendations:
        print(f"   {rec}")
else:
    print(f"   ✅ No issues detected")

print()
print("=" * 80)
print("DIAGNOSIS COMPLETE")
print("=" * 80)
