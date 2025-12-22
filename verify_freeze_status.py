#!/usr/bin/env python3
"""
Verify Freeze Status
====================
Check if trading freeze is working and if signal logging is being blocked.
"""

import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(__file__))

print("=" * 80)
print("FREEZE STATUS VERIFICATION")
print("=" * 80)

# Check freeze flag
freeze_flag = Path("logs/trading_frozen.flag")
if freeze_flag.exists():
    print(f"✅ Freeze flag exists: {freeze_flag}")
    try:
        import json
        with open(freeze_flag, 'r') as f:
            freeze_data = json.load(f)
        print(f"   Reason: {freeze_data.get('reason', 'unknown')}")
    except:
        print(f"   (Could not read freeze data)")
else:
    print(f"❌ Freeze flag NOT found: {freeze_flag}")
    print(f"   Trading is NOT paused!")

# Test freeze check function
print(f"\nTesting freeze check function:")
try:
    from src.full_bot_cycle import is_trading_frozen
    frozen = is_trading_frozen()
    print(f"   is_trading_frozen() = {frozen}")
    if frozen:
        print(f"   ✅ Freeze check is working")
    else:
        print(f"   ❌ Freeze check returns False (trading not frozen)")
except Exception as e:
    print(f"   ❌ Error importing is_trading_frozen: {e}")

# Test signal tracker freeze check
print(f"\nTesting signal tracker freeze check:")
try:
    from src.signal_outcome_tracker import signal_tracker
    from src.full_bot_cycle import is_trading_frozen
    
    # Try to log a test signal
    test_result = signal_tracker.log_signal(
        symbol="TESTUSDT",
        signal_name="test",
        direction="LONG",
        confidence=0.5,
        price=100.0,
        signal_data={"test": True}
    )
    
    if test_result == "":
        print(f"   ✅ Signal logging is BLOCKED (returned empty string)")
        print(f"   ✅ Freeze check in log_signal() is working")
    else:
        print(f"   ❌ Signal logging is NOT blocked (returned: {test_result})")
        print(f"   ❌ Freeze check in log_signal() may not be working")
        
except Exception as e:
    print(f"   ⚠️  Error testing signal tracker: {e}")
    import traceback
    traceback.print_exc()

print("\n" + "=" * 80)
