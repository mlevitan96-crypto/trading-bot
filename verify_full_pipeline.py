#!/usr/bin/env python3
"""
Verify Full Trading Pipeline
=============================
Comprehensive check of entire signal → trade → learning → feedback loop.
"""

import os
import sys
import json
import time
from pathlib import Path
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(__file__))

print("=" * 80)
print("FULL TRADING PIPELINE VERIFICATION")
print("=" * 80)
print(f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
print()

# ============================================================================
# 1. SIGNAL GENERATION (Upstream)
# ============================================================================
print("=" * 80)
print("1. SIGNAL GENERATION PIPELINE")
print("=" * 80)

pipeline_steps = {
    "predictive_signals.jsonl": {
        "description": "Predictive engine generates raw signals",
        "status": "❓",
        "age_minutes": 0,
        "lines": 0
    },
    "ensemble_predictions.jsonl": {
        "description": "Ensemble predictor creates predictions",
        "status": "❓",
        "age_minutes": 0,
        "lines": 0
    },
    "pending_signals.json": {
        "description": "Signal resolver logs to pending",
        "status": "❓",
        "age_minutes": 0
    },
    "signal_outcomes.jsonl": {
        "description": "Signal outcomes tracked",
        "status": "❓",
        "age_minutes": 0,
        "lines": 0
    }
}

for step_name, step_info in pipeline_steps.items():
    path = Path(f"logs/{step_name}") if step_name.endswith('.jsonl') else Path(f"feature_store/{step_name}")
    if step_name == "signal_outcomes.jsonl":
        path = Path(f"logs/{step_name}")
    
    if path.exists():
        stat = path.stat()
        age_minutes = (datetime.now().timestamp() - stat.st_mtime) / 60
        
        if step_name.endswith('.jsonl'):
            try:
                with open(path, 'r') as f:
                    lines = sum(1 for _ in f)
            except:
                lines = 0
            step_info["lines"] = lines
            step_info["age_minutes"] = age_minutes
            
            if age_minutes < 5:
                step_info["status"] = "✅ ACTIVE"
            elif age_minutes < 60:
                step_info["status"] = "🟡 STALE"
            else:
                step_info["status"] = "🔴 INACTIVE"
        else:
            step_info["age_minutes"] = age_minutes
            if age_minutes < 5:
                step_info["status"] = "✅ ACTIVE"
            else:
                step_info["status"] = "🟡 STALE"
    else:
        step_info["status"] = "❌ MISSING"

for step_name, step_info in pipeline_steps.items():
    print(f"   {step_info['status']} {step_name}")
    print(f"      {step_info['description']}")
    if step_info.get("lines", 0) > 0:
        print(f"      Lines: {step_info['lines']}, Age: {step_info['age_minutes']:.1f} min")
    elif step_info.get("age_minutes", 0) > 0:
        print(f"      Age: {step_info['age_minutes']:.1f} min")
    print()

# ============================================================================
# 2. TRADE EXECUTION
# ============================================================================
print("=" * 80)
print("2. TRADE EXECUTION")
print("=" * 80)

# Check positions file
positions_path = Path("logs/positions_futures.json")
if positions_path.exists():
    try:
        with open(positions_path, 'r') as f:
            positions = json.load(f)
        
        open_pos = len(positions.get("open_positions", []))
        closed_pos = len(positions.get("closed_positions", []))
        
        stat = positions_path.stat()
        age_minutes = (datetime.now().timestamp() - stat.st_mtime) / 60
        
        print(f"   ✅ Positions file exists")
        print(f"      Open positions: {open_pos}")
        print(f"      Closed positions: {closed_pos}")
        print(f"      Last updated: {age_minutes:.1f} min ago")
        
        if age_minutes < 5:
            print(f"      Status: 🟢 ACTIVE (trades executing)")
        elif age_minutes < 60:
            print(f"      Status: 🟡 STALE (no recent trades)")
        else:
            print(f"      Status: 🔴 INACTIVE (no trades in {age_minutes:.0f} min)")
    except Exception as e:
        print(f"   ⚠️  Error reading positions: {e}")
else:
    print(f"   ❌ Positions file not found")

print()

# ============================================================================
# 3. LEARNING LOOP
# ============================================================================
print("=" * 80)
print("3. LEARNING LOOP")
print("=" * 80)

# Check learning files
learning_files = {
    "signal_weights_gate.json": "Signal weight learning",
    "learned_rules.json": "Learned trading rules",
    "adaptive_weights.json": "Adaptive signal weights",
    "daily_learning_rules.json": "Daily learning rules"
}

learning_active = False
for file_name, description in learning_files.items():
    path = Path(f"feature_store/{file_name}")
    if path.exists():
        stat = path.stat()
        age_hours = (datetime.now().timestamp() - stat.st_mtime) / 3600
        
        try:
            with open(path, 'r') as f:
                data = json.load(f)
                size = len(str(data))
        except:
            size = 0
        
        if age_hours < 24:
            print(f"   ✅ {file_name}: Updated {age_hours:.1f}h ago ({description})")
            learning_active = True
        else:
            print(f"   🟡 {file_name}: Updated {age_hours:.1f}h ago (stale)")
    else:
        print(f"   ❌ {file_name}: Not found")

print()

# Check if continuous learning controller is running
try:
    from src.continuous_learning_controller import ContinuousLearningController
    clc = ContinuousLearningController()
    print(f"   ✅ Continuous Learning Controller: Available")
    
    # Check last learning cycle
    learning_state_path = Path("feature_store/continuous_learning_state.json")
    if learning_state_path.exists():
        try:
            with open(learning_state_path, 'r') as f:
                state = json.load(f)
            last_cycle = state.get("last_cycle_at", 0)
            if last_cycle:
                last_dt = datetime.fromtimestamp(last_cycle)
                age_hours = (datetime.now() - last_dt).total_seconds() / 3600
                print(f"      Last learning cycle: {age_hours:.1f} hours ago")
                if age_hours < 12:
                    print(f"      Status: 🟢 ACTIVE")
                else:
                    print(f"      Status: 🟡 STALE (should run every 12h)")
        except:
            pass
except Exception as e:
    print(f"   ⚠️  Continuous Learning Controller: {e}")

print()

# ============================================================================
# 4. LEARNING → TRADES FEEDBACK
# ============================================================================
print("=" * 80)
print("4. LEARNING → TRADES FEEDBACK LOOP")
print("=" * 80)

# Check if learned weights are being used
weights_path = Path("feature_store/signal_weights_gate.json")
if weights_path.exists():
    try:
        with open(weights_path, 'r') as f:
            weights = json.load(f)
        
        print(f"   ✅ Learned weights file exists")
        print(f"      Signals with weights: {len(weights)}")
        
        # Check if weights are recent
        stat = weights_path.stat()
        age_hours = (datetime.now().timestamp() - stat.st_mtime) / 3600
        if age_hours < 24:
            print(f"      Status: 🟢 ACTIVE (updated {age_hours:.1f}h ago)")
        else:
            print(f"      Status: 🟡 STALE (updated {age_hours:.1f}h ago)")
        
        # Show sample weights
        if weights:
            sample = list(weights.items())[:3]
            print(f"      Sample weights:")
            for signal, weight in sample:
                print(f"         {signal}: {weight}")
    except Exception as e:
        print(f"   ⚠️  Error reading weights: {e}")
else:
    print(f"   ❌ Learned weights file not found")

# Check if conviction gate uses learned weights
try:
    from src.conviction_gate import ConvictionGate
    gate = ConvictionGate()
    if hasattr(gate, 'signal_weights') and gate.signal_weights:
        print(f"   ✅ Conviction gate loaded {len(gate.signal_weights)} learned weights")
    else:
        print(f"   ⚠️  Conviction gate not using learned weights")
except Exception as e:
    print(f"   ⚠️  Error checking conviction gate: {e}")

print()

# ============================================================================
# 5. WORKER PROCESSES
# ============================================================================
print("=" * 80)
print("5. WORKER PROCESSES STATUS")
print("=" * 80)

# Check bot service
try:
    import subprocess
    result = subprocess.run(['systemctl', 'is-active', 'tradingbot'], 
                          capture_output=True, text=True, timeout=5)
    if result.returncode == 0:
        print(f"   ✅ Bot service: ACTIVE")
    else:
        print(f"   ❌ Bot service: INACTIVE")
except:
    pass

# Check for worker process logs
try:
    import subprocess
    result = subprocess.run(['journalctl', '-u', 'tradingbot', '--since', '30 minutes ago', 
                           '--grep', 'Starting Worker|worker.*start|ENSEMBLE|PREDICTIVE'], 
                          capture_output=True, text=True, timeout=10)
    
    if result.stdout:
        lines = [l for l in result.stdout.strip().split('\n') if l.strip()]
        print(f"   Found {len(lines)} worker-related log lines in last 30 min")
        
        # Look for startup messages
        startup_msgs = [l for l in lines if 'Starting' in l or 'started' in l.lower()]
        if startup_msgs:
            print(f"   ✅ Worker startup messages found:")
            for msg in startup_msgs[:5]:
                print(f"      {msg[:100]}")
        else:
            print(f"   ⚠️  No worker startup messages found")
    else:
        print(f"   ⚠️  No worker-related logs found")
except Exception as e:
    print(f"   ⚠️  Error checking logs: {e}")

print()

# ============================================================================
# 6. PIPELINE HEALTH SUMMARY
# ============================================================================
print("=" * 80)
print("6. PIPELINE HEALTH SUMMARY")
print("=" * 80)

issues = []
warnings = []

# Check each pipeline step
if pipeline_steps["ensemble_predictions.jsonl"]["status"] == "🔴 INACTIVE":
    issues.append("CRITICAL: Ensemble predictor not generating predictions")

if pipeline_steps["signal_outcomes.jsonl"]["status"] == "❌ MISSING":
    warnings.append("Signal outcomes file not found (may be normal if no signals resolved yet)")

if not learning_active:
    warnings.append("Learning files are stale (may need to trigger learning cycle)")

if issues:
    print(f"   🔴 CRITICAL ISSUES ({len(issues)}):")
    for issue in issues:
        print(f"      - {issue}")
    print()

if warnings:
    print(f"   🟡 WARNINGS ({len(warnings)}):")
    for warning in warnings:
        print(f"      - {warning}")
    print()

if not issues and not warnings:
    print(f"   ✅ Pipeline appears healthy")

print()

# ============================================================================
# 7. RECOMMENDATIONS
# ============================================================================
print("=" * 80)
print("7. RECOMMENDATIONS")
print("=" * 80)

recommendations = []

if pipeline_steps["ensemble_predictions.jsonl"]["status"] == "🔴 INACTIVE":
    recommendations.append("1. CRITICAL: Restart bot to restart ensemble predictor worker")
    recommendations.append("   sudo systemctl restart tradingbot")
    recommendations.append("   Wait 2 minutes, then verify: python3 check_signal_generation.py")

if not learning_active:
    recommendations.append("2. Trigger learning cycle:")
    recommendations.append("   python3 -c \"from src.continuous_learning_controller import ContinuousLearningController; clc = ContinuousLearningController(); clc.run_learning_cycle(force=True)\"")

if pipeline_steps["signal_outcomes.jsonl"]["status"] == "❌ MISSING":
    recommendations.append("3. Signal outcomes file missing - check if signal resolver is working")

if recommendations:
    for rec in recommendations:
        print(f"   {rec}")
else:
    print(f"   ✅ No immediate actions required")

print()
print("=" * 80)
print("PIPELINE VERIFICATION COMPLETE")
print("=" * 80)
