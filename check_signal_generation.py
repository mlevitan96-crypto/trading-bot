#!/usr/bin/env python3
"""
Check Signal Generation Status
==============================
Verifies that signals are being generated after trading resume.
"""

import os
import sys
from pathlib import Path
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(__file__))

print("=" * 80)
print("SIGNAL GENERATION STATUS CHECK")
print("=" * 80)
print(f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
print()

# Check trading freeze status
from src.full_bot_cycle import is_trading_frozen
frozen = is_trading_frozen()
print(f"📊 Trading Status: {'🚫 FROZEN' if frozen else '✅ ACTIVE'}")
print()

# Check signal files
signal_files = {
    "ensemble_predictions.jsonl": Path("logs/ensemble_predictions.jsonl"),
    "predictive_signals.jsonl": Path("logs/predictive_signals.jsonl"),
    "pending_signals.json": Path("feature_store/pending_signals.json"),
    "signals_universe.jsonl": Path("logs/signals_universe.jsonl")
}

print("=" * 80)
print("SIGNAL FILE STATUS")
print("=" * 80)

for name, path in signal_files.items():
    if path.exists():
        stat = path.stat()
        age_seconds = (datetime.now().timestamp() - stat.st_mtime)
        age_minutes = age_seconds / 60
        
        if name.endswith('.jsonl'):
            # Count lines
            try:
                with open(path, 'r') as f:
                    lines = sum(1 for _ in f)
            except:
                lines = 0
            print(f"✅ {name}:")
            print(f"   Age: {age_minutes:.1f} minutes ago")
            print(f"   Lines: {lines}")
            if age_minutes < 5:
                print(f"   Status: 🟢 ACTIVE (recently updated)")
            elif age_minutes < 30:
                print(f"   Status: 🟡 STALE (updated {age_minutes:.0f} min ago)")
            else:
                print(f"   Status: 🔴 INACTIVE (updated {age_minutes:.0f} min ago)")
        else:
            # JSON file
            print(f"✅ {name}:")
            print(f"   Age: {age_minutes:.1f} minutes ago")
            if age_minutes < 5:
                print(f"   Status: 🟢 ACTIVE")
            else:
                print(f"   Status: 🟡 STALE")
    else:
        print(f"❌ {name}: File does not exist")

print()
print("=" * 80)
print("RECENT SIGNAL ACTIVITY")
print("=" * 80)

# Check ensemble_predictions.jsonl for recent entries
ensemble_path = signal_files["ensemble_predictions.jsonl"]
if ensemble_path.exists():
    import json
    recent_signals = []
    cutoff_time = (datetime.now() - timedelta(minutes=10)).timestamp()
    
    try:
        with open(ensemble_path, 'r') as f:
            for line in f:
                try:
                    signal = json.loads(line.strip())
                    ts = signal.get('ts', signal.get('timestamp', 0))
                    if isinstance(ts, str):
                        # Try to parse ISO format
                        try:
                            dt = datetime.fromisoformat(ts.replace('Z', '+00:00'))
                            ts = dt.timestamp()
                        except:
                            ts = 0
                    
                    if ts > cutoff_time:
                        recent_signals.append(signal)
                except:
                    pass
        
        if recent_signals:
            print(f"✅ Found {len(recent_signals)} signals in last 10 minutes")
            print(f"   Latest signal: {recent_signals[-1].get('symbol', 'UNKNOWN')} {recent_signals[-1].get('side', 'UNKNOWN')}")
        else:
            print(f"⚠️  No signals in last 10 minutes")
    except Exception as e:
        print(f"❌ Error reading {ensemble_path}: {e}")

print()
print("=" * 80)
print("RECOMMENDATIONS")
print("=" * 80)

if frozen:
    print("🚫 Trading is FROZEN - signals will not be generated")
    print("   Run: python3 pause_trading_for_learning.py --resume")
elif not ensemble_path.exists() or (ensemble_path.exists() and (datetime.now().timestamp() - ensemble_path.stat().st_mtime) > 600):
    print("⚠️  Signal generation appears inactive")
    print("   Check: sudo systemctl status tradingbot")
    print("   Check logs: journalctl -u tradingbot --since '10 minutes ago'")
else:
    print("✅ Signal generation appears active")
    print("   Signals are being generated and logged")

print("=" * 80)
