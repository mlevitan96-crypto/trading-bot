#!/usr/bin/env python3
"""
Diagnostic script to check why trade execution status is red.
"""

import sys
import os
import json
import time
from pathlib import Path

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

def check_trade_execution():
    """Check trade execution status and diagnose issues."""
    print("🔍 TRADE EXECUTION DIAGNOSTIC")
    print("=" * 60)
    
    try:
        from src.infrastructure.path_registry import PathRegistry
        
        pos_file = PathRegistry.POS_LOG
        print(f"Checking positions file: {pos_file}")
        print(f"Exists: {os.path.exists(pos_file)}")
        
        if os.path.exists(pos_file):
            file_age = time.time() - os.path.getmtime(pos_file)
            print(f"File age: {file_age:.0f} seconds ({file_age/60:.1f} minutes, {file_age/3600:.2f} hours)")
            
            if file_age < 600:
                print("✅ Status should be GREEN (< 10 minutes)")
            elif file_age < 3600:
                print("⚠️  Status should be YELLOW (< 1 hour)")
            else:
                print("❌ Status is RED (> 1 hour)")
                
            # Check file contents
            try:
                with open(pos_file, 'r') as f:
                    data = json.load(f)
                
                open_positions = data.get("open_positions", [])
                closed_positions = data.get("closed_positions", [])
                
                print(f"\nOpen positions: {len(open_positions)}")
                print(f"Closed positions: {len(closed_positions)}")
                
                if open_positions:
                    print("\nCurrent open positions:")
                    for pos in open_positions[:5]:  # Show first 5
                        symbol = pos.get("symbol", "unknown")
                        opened_at = pos.get("opened_at", "unknown")
                        print(f"  • {symbol} opened at {opened_at}")
                
                # Check last closed position
                if closed_positions:
                    last_closed = closed_positions[-1]
                    closed_at = last_closed.get("closed_at", "unknown")
                    symbol = last_closed.get("symbol", "unknown")
                    print(f"\nLast closed position: {symbol} at {closed_at}")
                    
                    # Parse timestamp if available
                    try:
                        from datetime import datetime
                        if "T" in closed_at:
                            dt = datetime.fromisoformat(closed_at.replace('Z', '+00:00'))
                            age = (time.time() - dt.timestamp()) / 3600
                            print(f"  Age: {age:.1f} hours ago")
                    except:
                        pass
            except Exception as e:
                print(f"❌ Error reading file: {e}")
        else:
            print("❌ File does not exist - status would be YELLOW")
            
        # Check if bot is actively running
        print("\n" + "=" * 60)
        print("BOT ACTIVITY CHECK")
        print("=" * 60)
        
        # Check heartbeat
        heartbeat_file = PathRegistry.get_path("logs", ".bot_heartbeat")
        if os.path.exists(heartbeat_file):
            heartbeat_age = time.time() - os.path.getmtime(heartbeat_file)
            print(f"✅ Bot heartbeat: {heartbeat_age:.0f}s ago ({heartbeat_age/60:.1f} min)")
            if heartbeat_age > 300:
                print("⚠️  Bot heartbeat is stale (> 5 minutes)")
        else:
            print("⚠️  Bot heartbeat file not found")
        
        # Check if bot process is running
        try:
            import subprocess
            result = subprocess.run(
                ["systemctl", "is-active", "tradingbot"],
                capture_output=True,
                text=True,
                timeout=2
            )
            if result.stdout.strip() == "active":
                print("✅ Bot service is running")
            else:
                print(f"⚠️  Bot service status: {result.stdout.strip()}")
        except:
            pass
        
        print("\n" + "=" * 60)
        print("DIAGNOSIS")
        print("=" * 60)
        
        if os.path.exists(pos_file):
            if file_age > 3600:
                print("⚠️  Position file hasn't been updated in > 1 hour")
                print("   Possible reasons:")
                print("   1. Bot hasn't made any trades recently (normal)")
                print("   2. Bot cycle isn't running/updating positions")
                print("   3. Position manager isn't saving updates")
                print("\n   If bot is running but file not updating, this is a problem.")
                print("   If bot hasn't traded, this is normal (but status logic could be improved).")
        else:
            print("⚠️  Position file doesn't exist")
            print("   This should be created on bot startup.")
        
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    check_trade_execution()
