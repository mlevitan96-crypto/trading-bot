#!/usr/bin/env python3
"""
Check Log Status & System Activity
==================================
Comprehensive status check showing:
- Service status
- Recent log activity
- File update timestamps
- Active processes
- Key system components
"""

import os
import sys
import json
import time
import subprocess
from pathlib import Path
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(__file__))

print("=" * 80)
print("LOG STATUS & SYSTEM ACTIVITY CHECK")
print("=" * 80)
print(f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")

# ============================================================================
# 1. SERVICE STATUS
# ============================================================================

print("1. SERVICE STATUS")
print("-" * 80)

try:
    result = subprocess.run(
        ["systemctl", "is-active", "tradingbot"],
        capture_output=True,
        text=True,
        timeout=2
    )
    if result.stdout.strip() == "active":
        print("✅ Bot service: ACTIVE")
        
        # Get detailed status
        status_result = subprocess.run(
            ["systemctl", "status", "tradingbot", "--no-pager", "-l"],
            capture_output=True,
            text=True,
            timeout=3
        )
        status_lines = status_result.stdout.split('\n')
        for line in status_lines[:5]:
            if line.strip():
                print(f"   {line}")
    else:
        print(f"❌ Bot service: {result.stdout.strip()}")
except Exception as e:
    print(f"⚠️  Could not check service status: {e}")

# ============================================================================
# 2. RECENT LOG ACTIVITY
# ============================================================================

print("\n2. RECENT LOG ACTIVITY")
print("-" * 80)

# Check systemd journal
try:
    journal_result = subprocess.run(
        ["journalctl", "-u", "tradingbot", "--since", "5 minutes ago", "--no-pager", "-n", "10"],
        capture_output=True,
        text=True,
        timeout=5
    )
    if journal_result.stdout.strip():
        lines = journal_result.stdout.strip().split('\n')
        print(f"   Last {len(lines)} log entries (last 5 minutes):")
        for line in lines[-5:]:
            if line.strip():
                # Truncate long lines
                line_short = line[:120] + "..." if len(line) > 120 else line
                print(f"   {line_short}")
    else:
        print("   ⚠️  No recent log entries in systemd journal")
except Exception as e:
    print(f"   ⚠️  Could not read journal: {e}")

# Check bot_out.log if it exists
bot_log = Path("logs/bot_out.log")
if bot_log.exists():
    try:
        stat = bot_log.stat()
        age = time.time() - stat.st_mtime
        print(f"\n   bot_out.log: Last updated {age:.0f}s ago ({age/60:.1f} min)")
        
        # Read last few lines
        with open(bot_log, 'r', encoding='utf-8', errors='ignore') as f:
            lines = f.readlines()
            if lines:
                print(f"   Last 3 lines:")
                for line in lines[-3:]:
                    line_clean = line.strip()[:100]
                    if line_clean:
                        print(f"     {line_clean}")
    except Exception as e:
        print(f"   ⚠️  Error reading bot_out.log: {e}")
else:
    print(f"\n   ⚠️  bot_out.log not found (logs may be in systemd journal)")

# ============================================================================
# 3. KEY FILE STATUS
# ============================================================================

print("\n3. KEY FILE STATUS")
print("-" * 80)

key_files = {
    "positions_futures.json": "logs/positions_futures.json",
    "signals.jsonl": "logs/signals.jsonl",
    "signal_outcomes.jsonl": "logs/signal_outcomes.jsonl",
    "enriched_decisions.jsonl": "logs/enriched_decisions.jsonl",
    ".bot_heartbeat": "logs/.bot_heartbeat",
    "learning_audit.jsonl": "logs/learning_audit.jsonl"
}

for name, path_str in key_files.items():
    path = Path(path_str)
    if path.exists():
        try:
            stat = path.stat()
            age = time.time() - stat.st_mtime
            size = stat.st_size
            
            if age < 300:  # < 5 minutes
                status = "✅"
            elif age < 3600:  # < 1 hour
                status = "🟡"
            else:
                status = "🔴"
            
            print(f"   {status} {name}: {age/60:.1f} min ago, {size:,} bytes")
        except Exception as e:
            print(f"   ⚠️  {name}: Error checking ({e})")
    else:
        print(f"   ⚠️  {name}: Not found")

# ============================================================================
# 4. ACTIVE PROCESSES
# ============================================================================

print("\n4. ACTIVE PROCESSES")
print("-" * 80)

try:
    ps_result = subprocess.run(
        ["ps", "aux"],
        capture_output=True,
        text=True,
        timeout=3
    )
    bot_processes = [line for line in ps_result.stdout.split('\n') 
                     if 'run.py' in line or 'trading' in line.lower() or 'python' in line.lower()]
    
    if bot_processes:
        print(f"   Found {len(bot_processes)} related processes:")
        for proc in bot_processes[:5]:  # Show first 5
            # Extract key info
            parts = proc.split()
            if len(parts) > 10:
                pid = parts[1]
                cpu = parts[2]
                mem = parts[3]
                cmd = ' '.join(parts[10:])[:60]
                print(f"     PID {pid}: CPU {cpu}%, MEM {mem}% - {cmd}")
    else:
        print("   ⚠️  No bot processes found (may be running in systemd)")
except Exception as e:
    print(f"   ⚠️  Could not check processes: {e}")

# ============================================================================
# 5. RECENT ERRORS
# ============================================================================

print("\n5. RECENT ERRORS (Last 10 minutes)")
print("-" * 80)

try:
    error_result = subprocess.run(
        ["journalctl", "-u", "tradingbot", "--since", "10 minutes ago", "--no-pager"],
        capture_output=True,
        text=True,
        timeout=5
    )
    
    error_lines = [line for line in error_result.stdout.split('\n')
                   if any(keyword in line.lower() for keyword in ['error', 'exception', 'traceback', 'failed', 'critical'])]
    
    if error_lines:
        print(f"   Found {len(error_lines)} error-related lines:")
        for line in error_lines[-5:]:  # Last 5
            line_short = line[:100] + "..." if len(line) > 100 else line
            print(f"     {line_short}")
    else:
        print("   ✅ No errors found in last 10 minutes")
except Exception as e:
    print(f"   ⚠️  Could not check errors: {e}")

# ============================================================================
# 6. SYSTEM COMPONENTS STATUS
# ============================================================================

print("\n6. SYSTEM COMPONENTS STATUS")
print("-" * 80)

# Check healing operator
try:
    from src.healing_operator import get_healing_operator
    healing_op = get_healing_operator()
    if healing_op and healing_op.running:
        if healing_op.thread and healing_op.thread.is_alive():
            print("   ✅ Healing Operator: Running")
            if healing_op.last_healing_cycle_ts:
                age = time.time() - healing_op.last_healing_cycle_ts
                print(f"      Last cycle: {age:.0f}s ago ({age/60:.1f} min)")
        else:
            print("   ⚠️  Healing Operator: Instance exists but thread not alive")
    else:
        print("   ⚠️  Healing Operator: Not running")
except Exception as e:
    print(f"   ⚠️  Healing Operator: Could not check ({e})")

# Check signal tracker
try:
    from src.signal_outcome_tracker import signal_tracker
    pending = len(signal_tracker.pending_signals) if hasattr(signal_tracker, 'pending_signals') else 0
    print(f"   ✅ Signal Tracker: Active ({pending:,} pending signals)")
except Exception as e:
    print(f"   ⚠️  Signal Tracker: Could not check ({e})")

# ============================================================================
# SUMMARY
# ============================================================================

print("\n" + "=" * 80)
print("SUMMARY")
print("=" * 80)
print("\n💡 Quick Commands:")
print("   • Check healing: python3 check_healing_status.py")
print("   • Check learning: python3 monitor_learning_status.py")
print("   • Watch logs: journalctl -u tradingbot -f")
print("   • Check service: systemctl status tradingbot")
print("\n" + "=" * 80)
