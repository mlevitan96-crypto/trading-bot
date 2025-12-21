#!/usr/bin/env python3
"""
Quick check of healing operator status
"""

import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

try:
    from src.healing_operator import get_healing_operator
    from src.operator_safety import get_status
    
    print("=" * 80)
    print("HEALING STATUS CHECK")
    print("=" * 80)
    
    # Check healing operator
    healing_op = get_healing_operator()
    if healing_op:
        print(f"\n✅ Healing Operator: Running={healing_op.running}")
        if healing_op.last_healing_cycle:
            cycle = healing_op.last_healing_cycle
            print(f"   Last Cycle:")
            print(f"     Healed: {cycle.get('healed', [])}")
            print(f"     Failed: {cycle.get('failed', [])}")
            print(f"     Critical: {cycle.get('critical', [])}")
        
        status = healing_op.get_status()
        print(f"\n   Status: {status.get('self_healing', 'unknown')}")
        if status.get('self_healing') == 'red':
            print(f"\n🚨 RED STATUS DETECTED")
            print(f"   Reason: {status.get('reason', 'Unknown')}")
    else:
        print("\n❌ Healing operator not found")
    
    # Check operator safety status
    safety_status = get_status()
    print(f"\n\nOperator Safety Status:")
    print(f"   Self-Healing: {safety_status.get('self_healing', 'unknown')}")
    
    if safety_status.get('self_healing') == 'red':
        print(f"\n🚨 RED STATUS - Critical issues detected")
        print(f"   Check recent logs for details")
    
    print("\n" + "=" * 80)
    
except Exception as e:
    print(f"❌ Error: {e}")
    import traceback
    traceback.print_exc()
