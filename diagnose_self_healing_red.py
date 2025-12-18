#!/usr/bin/env python3
"""
Diagnostic script to investigate why self-healing status is red.
"""

import sys
import os
import json
import time
import threading
from pathlib import Path

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

def check_healing_operator():
    """Check healing operator instance and status."""
    print("=" * 60)
    print("HEALING OPERATOR DIAGNOSTIC")
    print("=" * 60)
    
    try:
        from src.healing_operator import get_healing_operator
        healing_op = get_healing_operator()
        
        if healing_op is None:
            print("❌ Healing operator instance is None")
            print("\nChecking for thread...")
            for thread in threading.enumerate():
                if "Healing" in thread.name or "heal" in thread.name.lower():
                    print(f"  Found thread: {thread.name} (alive: {thread.is_alive()})")
            return
        
        print(f"✅ Healing operator instance found: {type(healing_op)}")
        print(f"   Running: {healing_op.running}")
        print(f"   Thread: {healing_op.thread}")
        if healing_op.thread:
            print(f"   Thread alive: {healing_op.thread.is_alive()}")
            print(f"   Thread name: {healing_op.thread.name}")
        
        print(f"\n   Last cycle timestamp: {healing_op.last_healing_cycle_ts}")
        if healing_op.last_healing_cycle_ts:
            age = time.time() - healing_op.last_healing_cycle_ts
            print(f"   Cycle age: {age:.1f} seconds ({age/60:.1f} minutes)")
        
        print(f"\n   Last cycle data: {healing_op.last_healing_cycle}")
        if healing_op.last_healing_cycle:
            cycle = healing_op.last_healing_cycle
            print(f"     Healed: {cycle.get('healed', [])}")
            print(f"     Failed: {cycle.get('failed', [])}")
            print(f"     Critical: {cycle.get('critical', [])}")
        
        # Get status
        status = healing_op.get_status()
        print(f"\n   Status from get_status(): {status}")
        
        if status.get("self_healing") == "red":
            print("\n🚨 STATUS IS RED - Investigating why...")
            if healing_op.last_healing_cycle:
                failed = healing_op.last_healing_cycle.get("failed", [])
                if failed:
                    print(f"   ❌ Failed items: {failed}")
                critical = healing_op.last_healing_cycle.get("critical", [])
                if critical:
                    print(f"   🚨 Critical items: {critical}")
        
    except Exception as e:
        print(f"❌ Error checking healing operator: {e}")
        import traceback
        traceback.print_exc()

def check_operator_safety_status():
    """Check operator_safety.get_status() output."""
    print("\n" + "=" * 60)
    print("OPERATOR SAFETY STATUS CHECK")
    print("=" * 60)
    
    try:
        from src.operator_safety import get_status
        status = get_status()
        print(f"Operator safety status: {json.dumps(status, indent=2)}")
        
        self_healing_status = status.get("self_healing", "unknown")
        print(f"\nSelf-healing status: {self_healing_status}")
        
        if self_healing_status == "red":
            print("🚨 Status is RED in operator_safety.get_status()")
    except Exception as e:
        print(f"❌ Error checking operator safety status: {e}")
        import traceback
        traceback.print_exc()

def check_recent_logs():
    """Check recent bot logs for healing activity."""
    print("\n" + "=" * 60)
    print("RECENT HEALING LOGS")
    print("=" * 60)
    
    try:
        from src.infrastructure.path_registry import resolve_path
        log_file = resolve_path("logs/bot_out.log")
    except:
        log_file = Path("logs/bot_out.log")
    
    if not log_file.exists():
        print(f"⚠️  Log file not found: {log_file}")
        return
    
    print(f"Checking: {log_file}")
    
    # Read last 200 lines
    with open(log_file, 'r') as f:
        lines = f.readlines()
    
    recent_lines = lines[-200:] if len(lines) > 200 else lines
    healing_lines = [line for line in recent_lines if "[HEALING]" in line or "healing" in line.lower()]
    
    if healing_lines:
        print(f"\nFound {len(healing_lines)} recent healing-related lines:")
        for line in healing_lines[-10:]:  # Last 10
            print(f"  {line.strip()}")
    else:
        print("⚠️  No recent [HEALING] messages found in last 200 lines")

def check_alert_log():
    """Check for recent critical alerts."""
    print("\n" + "=" * 60)
    print("ALERT LOG CHECK")
    print("=" * 60)
    
    try:
        from src.infrastructure.path_registry import resolve_path
        alert_file = resolve_path("logs/operator_alerts.jsonl")
    except:
        alert_file = Path("logs/operator_alerts.jsonl")
    
    if not alert_file.exists():
        print(f"⚠️  Alert file not found: {alert_file}")
        return
    
    print(f"Checking: {alert_file}")
    
    current_time = time.time()
    critical_alerts = []
    
    with open(alert_file, 'r') as f:
        for line in f:
            try:
                alert = json.loads(line)
                if alert.get("level") == "CRITICAL":
                    alert_age = current_time - alert.get("timestamp", 0)
                    if alert_age < 3600:  # Last hour
                        critical_alerts.append((alert_age, alert))
            except:
                continue
    
    if critical_alerts:
        print(f"\n🚨 Found {len(critical_alerts)} CRITICAL alerts in last hour:")
        for age, alert in critical_alerts[:5]:  # Show first 5
            print(f"  [{age/60:.1f} min ago] {alert.get('category')}: {alert.get('message')}")
    else:
        print("✅ No critical alerts in last hour")

if __name__ == "__main__":
    check_healing_operator()
    check_operator_safety_status()
    check_recent_logs()
    check_alert_log()
    
    print("\n" + "=" * 60)
    print("DIAGNOSTIC COMPLETE")
    print("=" * 60)


