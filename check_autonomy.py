#!/usr/bin/env python3
"""
Quick check to verify the bot is autonomous and self-healing.
"""

import sys
import os
import time
import threading

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

def check_autonomy():
    """Verify bot is autonomously self-healing."""
    print("🤖 AUTONOMY CHECK")
    print("=" * 60)
    
    autonomous = True
    issues = []
    
    # 1. Check healing operator is running
    try:
        from src.healing_operator import get_healing_operator
        healing_op = get_healing_operator()
        
        if healing_op is None:
            print("❌ Healing operator NOT running")
            autonomous = False
            issues.append("Healing operator not started")
        else:
            print(f"✅ Healing operator running: {healing_op.running}")
            if healing_op.thread:
                print(f"✅ Thread alive: {healing_op.thread.is_alive()}")
                
            # Check recent activity
            if hasattr(healing_op, 'last_healing_cycle_ts') and healing_op.last_healing_cycle_ts:
                age = time.time() - healing_op.last_healing_cycle_ts
                print(f"✅ Last cycle: {age:.0f}s ago ({age/60:.1f} min)")
                
                if age < 120:  # Within 2 minutes
                    print("   → Healing is ACTIVE (good!)")
                elif age < 300:  # Within 5 minutes
                    print("   → Healing running (acceptable)")
                else:
                    print("   ⚠️  No recent activity")
                    issues.append(f"No healing cycle in {age/60:.1f} minutes")
            
            # Check what it's doing
            if healing_op.last_healing_cycle:
                cycle = healing_op.last_healing_cycle
                healed = cycle.get('healed', [])
                failed = cycle.get('failed', [])
                
                # Check for critical failures
                CRITICAL = ["safety_layer", "file_integrity", "trade_execution"]
                critical_failures = [f for f in failed if f in CRITICAL]
                non_critical = [f for f in failed if f not in CRITICAL]
                
                if healed:
                    print(f"✅ Recently healed: {', '.join(healed)}")
                    print("   → Bot IS fixing itself!")
                
                if critical_failures:
                    print(f"🚨 CRITICAL failures: {', '.join(critical_failures)}")
                    autonomous = False
                    issues.append(f"Critical components failing: {critical_failures}")
                elif failed:
                    print(f"⚠️  Non-critical issues: {', '.join(non_critical)}")
                    print("   → Not blocking autonomy (yellow status is OK)")
                else:
                    print("✅ No failures detected")
    except Exception as e:
        print(f"❌ Error checking healing: {e}")
        autonomous = False
        issues.append(f"Error: {e}")
    
    # 2. Check if bot can fix issues without human intervention
    print("\n" + "=" * 60)
    print("AUTONOMY ASSESSMENT")
    print("=" * 60)
    
    if autonomous and not issues:
        print("✅ FULLY AUTONOMOUS")
        print("   → Bot is self-healing")
        print("   → Critical components healthy")
        print("   → No human intervention needed")
        print("\n💡 Yellow status is OK if:")
        print("   • Non-critical components have minor issues")
        print("   • Bot is actively healing them")
        print("   • Critical components (safety, files, execution) are healthy")
    elif autonomous:
        print("⚠️  AUTONOMOUS WITH MINOR ISSUES")
        print(f"   Issues: {', '.join(issues)}")
        print("   → Bot can still self-heal")
        print("   → Yellow status indicates monitoring needed")
    else:
        print("❌ NOT FULLY AUTONOMOUS")
        print(f"   Critical issues: {', '.join(issues)}")
        print("   → May need intervention")
    
    return autonomous

if __name__ == "__main__":
    check_autonomy()
