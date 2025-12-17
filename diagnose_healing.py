#!/usr/bin/env python3
"""
Diagnostic script to check why self-healing is staying yellow.
Run this on the droplet to diagnose the issue.
"""
import sys
import os
import time

# Add project to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

try:
    from src.healing_operator import get_healing_operator
    from src.operator_safety import get_status
    
    print("="*60)
    print("HEALING OPERATOR DIAGNOSTIC")
    print("="*60)
    print()
    
    # Check 1: Can we import?
    print("✅ Successfully imported healing_operator module")
    
    # Check 2: Is operator instance available?
    healing_op = get_healing_operator()
    
    if healing_op is None:
        print("❌ PROBLEM: get_healing_operator() returned None")
        print("   → Healing operator was never started")
        print("   → Check bot logs for startup errors")
        sys.exit(1)
    
    print(f"✅ Healing operator instance found: {healing_op}")
    
    # Check 3: Is it running?
    if not hasattr(healing_op, 'running'):
        print("⚠️  Operator instance missing 'running' attribute")
    elif not healing_op.running:
        print("❌ PROBLEM: Healing operator is not running!")
        print("   → Operator was created but never started")
        print("   → Check bot startup logs for 'Healing operator started'")
        sys.exit(1)
    else:
        print(f"✅ Healing operator is running: {healing_op.running}")
    
    # Check 4: Has a cycle run?
    if not hasattr(healing_op, 'last_healing_cycle'):
        print("⚠️  Operator instance missing 'last_healing_cycle' attribute")
    elif healing_op.last_healing_cycle is None:
        print("⚠️  No healing cycle has completed yet")
        
        # Check if timestamp exists
        if hasattr(healing_op, 'last_healing_cycle_ts'):
            if healing_op.last_healing_cycle_ts is None:
                print("   → last_healing_cycle_ts is None (never initialized)")
            else:
                age = time.time() - healing_op.last_healing_cycle_ts
                print(f"   → last_healing_cycle_ts exists but age is {age:.0f}s")
                if age > 120:
                    print("   ❌ PROBLEM: Last cycle was > 2 minutes ago - healing loop may be stuck")
        else:
            print("   ❌ PROBLEM: last_healing_cycle_ts attribute doesn't exist")
    else:
        print(f"✅ Last healing cycle completed: {healing_op.last_healing_cycle}")
        healed = healing_op.last_healing_cycle.get('healed', [])
        failed = healing_op.last_healing_cycle.get('failed', [])
        print(f"   → Healed: {len(healed)} items")
        print(f"   → Failed: {len(failed)} items")
        if failed:
            print(f"   → Failed items: {failed}")
    
    # Check 5: Check status
    print()
    print("Status check:")
    try:
        status_dict = healing_op.get_status()
        healing_status = status_dict.get('self_healing', 'unknown')
        print(f"   → Status: {healing_status}")
        if healing_status == 'yellow':
            print("   ⚠️  Status is yellow - this is why dashboard shows yellow")
        elif healing_status == 'green':
            print("   ✅ Status is green - should show green on dashboard")
        else:
            print(f"   ❌ Status is {healing_status}")
    except Exception as e:
        print(f"   ❌ Error getting status: {e}")
        import traceback
        traceback.print_exc()
    
    # Check 6: Operator safety status
    print()
    print("Operator safety status check:")
    try:
        safety_status = get_status()
        safety_healing = safety_status.get('self_healing', 'unknown')
        print(f"   → Safety layer reports: {safety_healing}")
    except Exception as e:
        print(f"   ❌ Error getting safety status: {e}")
        import traceback
        traceback.print_exc()
    
    # Check 7: Thread status
    print()
    print("Thread status:")
    if hasattr(healing_op, 'thread'):
        if healing_op.thread is None:
            print("   ❌ PROBLEM: Thread is None - operator never started thread!")
        elif not healing_op.thread.is_alive():
            print("   ❌ PROBLEM: Thread is not alive - healing loop crashed!")
        else:
            print(f"   ✅ Thread is alive: {healing_op.thread.name}")
    else:
        print("   ⚠️  No thread attribute found")
    
    print()
    print("="*60)
    print("RECOMMENDATIONS:")
    print("="*60)
    
    if healing_op is None or (hasattr(healing_op, 'running') and not healing_op.running):
        print("1. Check bot startup logs for healing operator startup errors")
        print("2. Restart the bot to ensure healing operator starts properly")
    elif hasattr(healing_op, 'thread') and healing_op.thread and not healing_op.thread.is_alive():
        print("1. Healing loop thread crashed - check logs for errors")
        print("2. Restart the bot to restart healing operator")
    elif healing_op.last_healing_cycle is None:
        print("1. Healing operator is running but no cycles completed")
        print("2. Check logs for errors in healing cycle execution")
        print("3. Wait 1-2 minutes and check again")
    else:
        print("1. Healing operator appears to be working")
        print("2. If dashboard still shows yellow, check dashboard code/logs")
    
    print()
    
except Exception as e:
    print(f"❌ Error running diagnostic: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)
