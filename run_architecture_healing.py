#!/usr/bin/env python3
"""
Run Architecture-Aware Healing
==============================
Immediate fix for current issues and comprehensive healing cycle.
"""

import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

from src.architecture_aware_healing import ArchitectureAwareHealing

if __name__ == "__main__":
    print("="*80)
    print("ARCHITECTURE-AWARE HEALING")
    print("="*80)
    print()
    
    healer = ArchitectureAwareHealing()
    results = healer.run_healing_cycle()
    
    # Exit code based on results
    if results["failed"]:
        print("\n❌ Some issues could not be healed automatically")
        print("   Manual intervention may be required")
        sys.exit(1)
    elif results["healed"]:
        print("\n✅ All issues were successfully healed")
        sys.exit(0)
    else:
        print("\n✅ No issues found - system is healthy")
        sys.exit(0)
