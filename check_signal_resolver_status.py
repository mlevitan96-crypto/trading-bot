#!/usr/bin/env python3
"""
Check Signal Resolver Status
============================
Check if the signal resolver is actively running and processing signals.
"""

import os
import sys
import subprocess
from pathlib import Path
from datetime import datetime

sys.path.insert(0, os.path.dirname(__file__))

print("=" * 80)
print("SIGNAL RESOLVER STATUS CHECK")
print("=" * 80)
print(f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
print()

# Check if bot service is running
print("1. BOT SERVICE STATUS:")
print("-" * 80)
try:
    result = subprocess.run(['systemctl', 'is-active', 'tradingbot'], 
                          capture_output=True, text=True, timeout=5)
    if result.returncode == 0:
        print(f"   ✅ Trading bot service is: {result.stdout.strip()}")
    else:
        print(f"   ❌ Trading bot service is: {result.stdout.strip()}")
except Exception as e:
    print(f"   ⚠️  Could not check service status: {e}")

# Check recent bot logs for signal resolver activity
print("\n2. RECENT SIGNAL RESOLVER LOGS:")
print("-" * 80)
try:
    result = subprocess.run(['journalctl', '-u', 'tradingbot', '--since', '10 minutes ago', 
                           '--no-pager', '-n', '50'], 
                          capture_output=True, text=True, timeout=10)
    if result.returncode == 0:
        lines = result.stdout.split('\n')
        resolver_lines = [l for l in lines if 'SIGNAL-RESOLVER' in l or 'SignalTracker' in l]
        if resolver_lines:
            print(f"   Found {len(resolver_lines)} resolver log entries:")
            for line in resolver_lines[-10:]:  # Last 10 entries
                # Extract timestamp and message
                parts = line.split(']', 1)
                if len(parts) > 1:
                    print(f"   {parts[1].strip()}")
                else:
                    print(f"   {line[:100]}")
        else:
            print(f"   ⚠️  No signal resolver activity in last 10 minutes")
            print(f"   Showing last 5 bot log lines:")
            for line in lines[-5:]:
                print(f"   {line[:100]}")
    else:
        print(f"   ⚠️  Could not read logs: {result.stderr}")
except Exception as e:
    print(f"   ⚠️  Could not check logs: {e}")

# Check pending signals file modification time
print("\n3. PENDING SIGNALS FILE STATUS:")
print("-" * 80)
pending_file = Path("feature_store/pending_signals.json")
if pending_file.exists():
    import time
    mtime = pending_file.stat().st_mtime
    age_seconds = time.time() - mtime
    age_minutes = int(age_seconds / 60)
    print(f"   File: {pending_file}")
    print(f"   Last modified: {age_minutes} minutes ago")
    if age_minutes < 5:
        print(f"   ✅ File is being updated (actively processing)")
    elif age_minutes < 15:
        print(f"   ⚠️  File hasn't been updated recently (may be processing slowly)")
    else:
        print(f"   ❌ File hasn't been updated in {age_minutes} minutes (may be stuck)")
else:
    print(f"   ❌ File not found: {pending_file}")

# Check resolved outcomes file modification time
print("\n4. RESOLVED OUTCOMES FILE STATUS:")
print("-" * 80)
outcomes_file = Path("logs/signal_outcomes.jsonl")
if outcomes_file.exists():
    import time
    mtime = outcomes_file.stat().st_mtime
    age_seconds = time.time() - mtime
    age_minutes = int(age_seconds / 60)
    print(f"   File: {outcomes_file}")
    print(f"   Last modified: {age_minutes} minutes ago")
    if age_minutes < 2:
        print(f"   ✅ File is being updated (actively resolving)")
    elif age_minutes < 5:
        print(f"   ⚠️  File updated recently (may be processing slowly)")
    else:
        print(f"   ❌ File hasn't been updated in {age_minutes} minutes (resolution may be stuck)")
else:
    print(f"   ❌ File not found: {outcomes_file}")

# Check CPU usage
print("\n5. CPU USAGE:")
print("-" * 80)
try:
    result = subprocess.run(['top', '-b', '-n', '1'], 
                          capture_output=True, text=True, timeout=5)
    if result.returncode == 0:
        lines = result.stdout.split('\n')
        # Find python process
        python_lines = [l for l in lines if 'python' in l.lower() and 'run.py' in l]
        if python_lines:
            print(f"   Found {len(python_lines)} Python process(es):")
            for line in python_lines[:3]:  # First 3
                parts = line.split()
                if len(parts) > 8:
                    cpu = parts[8]
                    cmd = ' '.join(parts[11:])
                    print(f"   CPU: {cpu}% - {cmd[:60]}")
        else:
            print(f"   ⚠️  No Python processes found running run.py")
    else:
        print(f"   ⚠️  Could not check CPU usage")
except Exception as e:
    print(f"   ⚠️  Could not check CPU: {e}")

print("\n" + "=" * 80)
print("RECOMMENDATIONS:")
print("=" * 80)
print("If resolution appears stuck:")
print("  1. Check bot logs: journalctl -u tradingbot --since '10 minutes ago' | grep SIGNAL-RESOLVER")
print("  2. Restart bot: sudo systemctl restart tradingbot")
print("  3. Monitor: python3 check_resolution_progress.py")
print("=" * 80)
