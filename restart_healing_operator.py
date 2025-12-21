#!/usr/bin/env python3
"""
Restart Healing Operator
========================
Manually start/restart the healing operator if it's not running.
"""

import sys
import os
import time
sys.path.insert(0, os.path.dirname(__file__))

print("=" * 80)
print("RESTART HEALING OPERATOR")
print("=" * 80)

try:
    from src.healing_operator import get_healing_operator, start_healing_operator
    
    # Check current status
    healing_op = get_healing_operator()
    
    if healing_op:
        print(f"\n✅ Healing operator instance found")
        print(f"   Running: {healing_op.running}")
        if healing_op.thread:
            print(f"   Thread alive: {healing_op.thread.is_alive()}")
            print(f"   Thread name: {healing_op.thread.name}")
        
        if healing_op.running and healing_op.thread and healing_op.thread.is_alive():
            print("\n✅ Healing operator is already running!")
            print("   No action needed.")
        else:
            print("\n⚠️  Healing operator exists but not running")
            print("   Attempting to start...")
            try:
                healing_op.start()
                time.sleep(0.5)
                if healing_op.running and healing_op.thread and healing_op.thread.is_alive():
                    print("   ✅ Successfully started!")
                else:
                    print("   ❌ Failed to start")
            except Exception as e:
                print(f"   ❌ Error starting: {e}")
                import traceback
                traceback.print_exc()
    else:
        print("\n❌ Healing operator instance is None")
        print("   Creating new instance and starting...")
        try:
            healing_op = start_healing_operator()
            time.sleep(0.5)
            
            # Verify
            healing_op_check = get_healing_operator()
            if healing_op_check and healing_op_check.running:
                if healing_op_check.thread and healing_op_check.thread.is_alive():
                    print("   ✅ Successfully created and started!")
                    print(f"   Thread: {healing_op_check.thread.name}")
                else:
                    print("   ⚠️  Started but thread not alive")
            else:
                print("   ❌ Failed to start")
        except Exception as e:
            print(f"   ❌ Error: {e}")
            import traceback
            traceback.print_exc()
    
    # Final status check
    print("\n" + "=" * 80)
    print("FINAL STATUS")
    print("=" * 80)
    
    final_op = get_healing_operator()
    if final_op:
        print(f"   Instance: ✅ Found")
        print(f"   Running: {'✅' if final_op.running else '❌'}")
        if final_op.thread:
            print(f"   Thread: {'✅ Alive' if final_op.thread.is_alive() else '❌ Dead'}")
        else:
            print(f"   Thread: ❌ None")
        
        if final_op.last_healing_cycle_ts:
            age = time.time() - final_op.last_healing_cycle_ts
            print(f"   Last cycle: {age:.1f}s ago ({age/60:.1f} min)")
        
        status = final_op.get_status()
        print(f"   Status: {status.get('self_healing', 'unknown')}")
    else:
        print("   ❌ Healing operator still not found")
        print("   → Check logs for startup errors")
        print("   → May need to restart the bot service")
    
    print("\n" + "=" * 80)
    
except Exception as e:
    print(f"\n❌ Error: {e}")
    import traceback
    traceback.print_exc()
