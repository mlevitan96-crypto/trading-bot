#!/usr/bin/env python3
"""
Check if position prices are being updated during bot cycles.
"""

import sys
import os
import json
import time
import subprocess
from pathlib import Path

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

def check_updates():
    """Check if positions are being updated."""
    print("🔍 CHECKING POSITION UPDATES")
    print("=" * 60)
    
    try:
        from src.infrastructure.path_registry import PathRegistry
        
        pos_file = PathRegistry.POS_LOG
        print(f"Positions file: {pos_file}")
        
        # Check current file time
        if os.path.exists(pos_file):
            file_mtime = os.path.getmtime(pos_file)
            file_age = time.time() - file_mtime
            print(f"File last modified: {time.ctime(file_mtime)}")
            print(f"Age: {file_age/60:.1f} minutes ({file_age/3600:.2f} hours)")
            
            # Read positions
            with open(pos_file, 'r') as f:
                data = json.load(f)
            
            open_positions = data.get("open_positions", [])
            print(f"\nOpen positions: {len(open_positions)}")
            
            # Check update times
            if open_positions:
                print("\nPosition update times:")
                for pos in open_positions[:5]:
                    symbol = pos.get("symbol", "unknown")
                    updated_at = pos.get("updated_at", "never")
                    current_price = pos.get("current_price")
                    print(f"  {symbol}: updated_at={updated_at}, price={current_price}")
            
            # Check bot logs for update_position_prices calls
            print("\n" + "=" * 60)
            print("CHECKING BOT LOGS")
            print("=" * 60)
            
            try:
                result = subprocess.run(
                    ["journalctl", "-u", "tradingbot", "-n", "500", "--no-pager"],
                    capture_output=True,
                    text=True,
                    timeout=5
                )
                
                if result.returncode == 0:
                    output = result.stdout
                    
                    # Check for update calls
                    if "update_position_prices" in output or "Exit Sentinel" in output:
                        print("✅ Found position update calls in logs")
                        lines = [l for l in output.split('\n') if "Exit Sentinel" in l or "update" in l.lower()]
                        for line in lines[-5:]:
                            print(f"  {line.strip()[:100]}")
                    else:
                        print("⚠️  No position update calls found in recent logs")
                    
                    # Check for errors
                    error_lines = [l for l in output.split('\n') if "error" in l.lower() or "failed" in l.lower() or "❌" in l][-5:]
                    if error_lines:
                        print("\n⚠️  Recent errors:")
                        for line in error_lines:
                            print(f"  {line.strip()[:100]}")
                            
            except Exception as e:
                print(f"⚠️  Error checking logs: {e}")
        
        # Check if bot cycle is running
        print("\n" + "=" * 60)
        print("CHECKING BOT CYCLE")
        print("=" * 60)
        
        try:
            result = subprocess.run(
                ["journalctl", "-u", "tradingbot", "-n", "100", "--no-pager", "|", "grep", "-i", "bot.*cycle"],
                shell=True,
                capture_output=True,
                text=True,
                timeout=5
            )
            # Try simpler approach
            result2 = subprocess.run(
                ["journalctl", "-u", "tradingbot", "-n", "100", "--no-pager"],
                capture_output=True,
                text=True,
                timeout=5
            )
            if "cycle" in result2.stdout.lower() or "bot cycle" in result2.stdout.lower():
                print("✅ Bot cycle appears to be running")
            else:
                print("⚠️  No recent bot cycle activity in logs")
        except:
            pass
        
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    check_updates()
