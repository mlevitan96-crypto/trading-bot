#!/usr/bin/env python3
"""
Deep Signal Generation Analysis
================================
Comprehensive check of all signal generation components to ensure everything is working.
"""

import os
import sys
import json
import time
from pathlib import Path
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(__file__))

print("=" * 80)
print("DEEP SIGNAL GENERATION ANALYSIS")
print("=" * 80)
print(f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
print()

# ============================================================================
# 1. CHECK TRADING FREEZE STATUS
# ============================================================================
print("=" * 80)
print("1. TRADING FREEZE STATUS")
print("=" * 80)

try:
    from src.full_bot_cycle import is_trading_frozen
    frozen = is_trading_frozen()
    print(f"   Trading Frozen: {'🚫 YES' if frozen else '✅ NO'}")
    
    if frozen:
        freeze_flag = Path("logs/trading_frozen.flag")
        if freeze_flag.exists():
            try:
                with open(freeze_flag, 'r') as f:
                    freeze_data = json.load(f)
                print(f"   Reason: {freeze_data.get('reason', 'unknown')}")
                frozen_at = freeze_data.get('frozen_at', 0)
                if frozen_at:
                    frozen_dt = datetime.fromtimestamp(frozen_at)
                    duration = datetime.now() - frozen_dt
                    print(f"   Frozen at: {frozen_dt.strftime('%Y-%m-%d %H:%M:%S')}")
                    print(f"   Duration: {duration}")
                print(f"\n   ⚠️  ACTION REQUIRED: Trading is frozen - signals will be blocked!")
                print(f"   Run: python3 pause_trading_for_learning.py --resume")
            except Exception as e:
                print(f"   Error reading freeze flag: {e}")
except Exception as e:
    print(f"   ⚠️  Error checking freeze status: {e}")

print()

# ============================================================================
# 2. CHECK SIGNAL POLICIES
# ============================================================================
print("=" * 80)
print("2. SIGNAL POLICIES")
print("=" * 80)

signal_policy_path = Path("configs/signal_policies.json")
if signal_policy_path.exists():
    try:
        with open(signal_policy_path, 'r') as f:
            policy = json.load(f)
        
        alpha_trading = policy.get("alpha_trading", {})
        enabled = alpha_trading.get("enabled", False)
        enabled_symbols = alpha_trading.get("enabled_symbols", [])
        
        print(f"   Alpha Trading Enabled: {'✅ YES' if enabled else '❌ NO'}")
        print(f"   Enabled Symbols: {len(enabled_symbols)}")
        print(f"   Symbols: {', '.join(enabled_symbols[:5])}{'...' if len(enabled_symbols) > 5 else ''}")
        
        if not enabled:
            print(f"\n   ⚠️  ACTION REQUIRED: Alpha trading is disabled!")
    except Exception as e:
        print(f"   ❌ Error reading signal policies: {e}")
else:
    print(f"   ⚠️  Signal policies file not found: {signal_policy_path}")

print()

# ============================================================================
# 3. CHECK WORKER PROCESSES
# ============================================================================
print("=" * 80)
print("3. WORKER PROCESS STATUS")
print("=" * 80)

# Check if bot service is running
try:
    import subprocess
    result = subprocess.run(['systemctl', 'is-active', 'tradingbot'], 
                          capture_output=True, text=True, timeout=5)
    if result.returncode == 0:
        print(f"   Bot Service: ✅ ACTIVE ({result.stdout.strip()})")
    else:
        print(f"   Bot Service: ❌ INACTIVE")
        print(f"   Run: sudo systemctl restart tradingbot")
except Exception as e:
    print(f"   ⚠️  Could not check service status: {e}")

# Check for worker process logs
print(f"\n   Checking recent worker activity in logs...")
try:
    import subprocess
    result = subprocess.run(['journalctl', '-u', 'tradingbot', '--since', '10 minutes ago', 
                           '--grep', 'ENSEMBLE-PREDICTOR|SIGNAL-RESOLVER'], 
                          capture_output=True, text=True, timeout=10)
    if result.stdout:
        lines = result.stdout.strip().split('\n')
        print(f"   Found {len(lines)} relevant log lines in last 10 minutes")
        if lines:
            print(f"   Last activity:")
            for line in lines[-3:]:
                print(f"      {line[:100]}")
    else:
        print(f"   ⚠️  No worker activity found in last 10 minutes")
except Exception as e:
    print(f"   ⚠️  Could not check logs: {e}")

print()

# ============================================================================
# 4. CHECK SIGNAL FILES
# ============================================================================
print("=" * 80)
print("4. SIGNAL FILE STATUS")
print("=" * 80)

signal_files = {
    "predictive_signals.jsonl": Path("logs/predictive_signals.jsonl"),
    "ensemble_predictions.jsonl": Path("logs/ensemble_predictions.jsonl"),
    "pending_signals.json": Path("feature_store/pending_signals.json"),
    "signals_universe.jsonl": Path("logs/signals_universe.jsonl")
}

for name, path in signal_files.items():
    if path.exists():
        stat = path.stat()
        age_seconds = (datetime.now().timestamp() - stat.st_mtime)
        age_minutes = age_seconds / 60
        age_hours = age_seconds / 3600
        
        if name.endswith('.jsonl'):
            try:
                with open(path, 'r') as f:
                    lines = sum(1 for _ in f)
            except:
                lines = 0
            
            print(f"   ✅ {name}:")
            print(f"      Age: {age_hours:.1f} hours ({age_minutes:.0f} min)")
            print(f"      Lines: {lines}")
            
            if age_minutes < 5:
                print(f"      Status: 🟢 ACTIVE")
            elif age_minutes < 60:
                print(f"      Status: 🟡 STALE")
            else:
                print(f"      Status: 🔴 INACTIVE")
                if name == "ensemble_predictions.jsonl":
                    print(f"      ⚠️  CRITICAL: Ensemble predictions not updating!")
        else:
            print(f"   ✅ {name}:")
            print(f"      Age: {age_minutes:.1f} minutes")
    else:
        print(f"   ❌ {name}: File does not exist")

print()

# ============================================================================
# 5. CHECK CODE BLOCKS
# ============================================================================
print("=" * 80)
print("5. CODE BLOCKS THAT PREVENT SIGNAL GENERATION")
print("=" * 80)

blocks_found = []

# Check run.py for freeze checks
run_py = Path("src/run.py")
if run_py.exists():
    try:
        with open(run_py, 'r') as f:
            content = f.read()
            if 'is_trading_frozen' in content:
                # Count occurrences
                count = content.count('is_trading_frozen')
                print(f"   Found {count} freeze checks in src/run.py")
                if count > 0:
                    blocks_found.append("src/run.py has freeze checks")
    except:
        pass

# Check signal_outcome_tracker.py
tracker_py = Path("src/signal_outcome_tracker.py")
if tracker_py.exists():
    try:
        with open(tracker_py, 'r') as f:
            content = f.read()
            if 'is_trading_frozen' in content:
                print(f"   Found freeze check in src/signal_outcome_tracker.py")
                blocks_found.append("signal_outcome_tracker.py blocks when frozen")
    except:
        pass

if blocks_found:
    print(f"\n   ⚠️  Found {len(blocks_found)} potential blocks:")
    for block in blocks_found:
        print(f"      - {block}")
else:
    print(f"   ✅ No obvious code blocks found")

print()

# ============================================================================
# 6. RECOMMENDATIONS
# ============================================================================
print("=" * 80)
print("6. RECOMMENDATIONS")
print("=" * 80)

recommendations = []

if frozen:
    recommendations.append("1. Resume trading: python3 pause_trading_for_learning.py --resume")

if not signal_policy_path.exists() or not alpha_trading.get("enabled", False):
    recommendations.append("2. Enable alpha trading in configs/signal_policies.json")

ensemble_path = signal_files["ensemble_predictions.jsonl"]
if ensemble_path.exists():
    age_hours = (datetime.now().timestamp() - ensemble_path.stat().st_mtime) / 3600
    if age_hours > 1:
        recommendations.append("3. Restart bot to restart ensemble predictor worker: sudo systemctl restart tradingbot")
        recommendations.append("4. Check logs for ensemble predictor errors: journalctl -u tradingbot --since '1 hour ago' | grep -i ensemble")

if recommendations:
    for rec in recommendations:
        print(f"   {rec}")
else:
    print(f"   ✅ No immediate actions required")

print()
print("=" * 80)
print("ANALYSIS COMPLETE")
print("=" * 80)




