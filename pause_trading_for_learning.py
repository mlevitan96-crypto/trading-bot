#!/usr/bin/env python3
"""
Pause Trading for Learning Session
===================================
Temporarily pauses trading to allow signal resolution to catch up,
then triggers a comprehensive learning cycle.

Usage:
    python3 pause_trading_for_learning.py --pause    # Pause trading
    python3 pause_trading_for_learning.py --resume   # Resume trading
    python3 pause_trading_for_learning.py --status   # Check status
"""

import os
import sys
import json
import time
import argparse
from pathlib import Path
from datetime import datetime

sys.path.insert(0, os.path.dirname(__file__))

FREEZE_FLAG = Path("logs/trading_frozen.flag")

def pause_trading(reason="learning_session"):
    """Pause trading by creating freeze flag."""
    os.makedirs("logs", exist_ok=True)
    
    freeze_data = {
        "frozen_at": int(time.time()),
        "reason": reason,
        "frozen_by": "pause_trading_for_learning.py",
        "note": "Trading paused to allow signal resolution and learning cycle"
    }
    
    with open(FREEZE_FLAG, 'w') as f:
        json.dump(freeze_data, f, indent=2)
    
    print("=" * 80)
    print("TRADING PAUSED")
    print("=" * 80)
    print(f"✅ Trading has been paused")
    print(f"   Reason: {reason}")
    print(f"   Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"\n📊 Next Steps:")
    print(f"   1. Signal resolution will continue (no new signals will be generated)")
    print(f"   2. Monitor progress: python3 check_resolution_progress.py")
    print(f"   3. Once caught up, run learning cycle")
    print(f"   4. Resume trading: python3 pause_trading_for_learning.py --resume")
    print("=" * 80)

def resume_trading():
    """Resume trading by removing freeze flag."""
    if FREEZE_FLAG.exists():
        freeze_data = {}
        try:
            with open(FREEZE_FLAG, 'r') as f:
                freeze_data = json.load(f)
        except:
            pass
        
        FREEZE_FLAG.unlink()
        
        print("=" * 80)
        print("TRADING RESUMED")
        print("=" * 80)
        print(f"✅ Trading has been resumed")
        print(f"   Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        if freeze_data:
            frozen_at = freeze_data.get("frozen_at", 0)
            if frozen_at:
                duration = int(time.time()) - frozen_at
                hours = duration // 3600
                mins = (duration % 3600) // 60
                print(f"   Was paused for: {hours}h {mins}m")
        print("=" * 80)
    else:
        print("⚠️  Trading is not currently paused")

def check_status():
    """Check current trading status."""
    print("=" * 80)
    print("TRADING STATUS")
    print("=" * 80)
    
    if FREEZE_FLAG.exists():
        try:
            with open(FREEZE_FLAG, 'r') as f:
                freeze_data = json.load(f)
            
            frozen_at = freeze_data.get("frozen_at", 0)
            reason = freeze_data.get("reason", "unknown")
            
            if frozen_at:
                duration = int(time.time()) - frozen_at
                hours = duration // 3600
                mins = (duration % 3600) // 60
                
                print(f"🚫 Trading is PAUSED")
                print(f"   Reason: {reason}")
                print(f"   Paused at: {datetime.fromtimestamp(frozen_at).strftime('%Y-%m-%d %H:%M:%S')}")
                print(f"   Duration: {hours}h {mins}m")
            else:
                print(f"🚫 Trading is PAUSED")
                print(f"   Reason: {reason}")
        except Exception as e:
            print(f"🚫 Trading is PAUSED (could not read details: {e})")
    else:
        print(f"✅ Trading is ACTIVE")
    
    # Check signal resolution progress
    print(f"\n📊 Signal Resolution Status:")
    try:
        from check_resolution_progress import *
        # This will run the progress check
    except:
        print("   Run: python3 check_resolution_progress.py")
    
    print("=" * 80)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Pause/resume trading for learning session")
    parser.add_argument("--pause", action="store_true", help="Pause trading")
    parser.add_argument("--resume", action="store_true", help="Resume trading")
    parser.add_argument("--status", action="store_true", help="Check trading status")
    
    args = parser.parse_args()
    
    if args.pause:
        pause_trading()
    elif args.resume:
        resume_trading()
    elif args.status:
        check_status()
    else:
        parser.print_help()
