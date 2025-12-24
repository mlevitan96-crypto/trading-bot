#!/usr/bin/env python3
"""
Verify Enhanced Logging is Working
===================================
Comprehensive check to confirm enhanced trade logging is:
1. Code is integrated and in place
2. Being called when positions open
3. Capturing snapshots successfully
4. Logging to journalctl
"""

import json
import sys
from pathlib import Path
from datetime import datetime, timezone, timedelta
import subprocess

def check_code_integration():
    """Verify the code is integrated in position_manager.py"""
    print("=" * 80)
    print("1. CODE INTEGRATION CHECK")
    print("=" * 80)
    
    position_manager_path = Path("src/position_manager.py")
    if not position_manager_path.exists():
        print("❌ position_manager.py not found")
        return False
    
    content = position_manager_path.read_text()
    
    checks = {
        "imports create_volatility_snapshot": "create_volatility_snapshot" in content,
        "calls create_volatility_snapshot": "create_volatility_snapshot(symbol" in content,
        "stores volatility_snapshot": '"volatility_snapshot"' in content or "'volatility_snapshot'" in content,
        "logs success message": "[ENHANCED-LOGGING] Captured volatility snapshot" in content,
        "logs error message": "[ENHANCED-LOGGING] Failed to capture" in content,
    }
    
    all_pass = True
    for check, passed in checks.items():
        status = "✅" if passed else "❌"
        print(f"   {status} {check}")
        if not passed:
            all_pass = False
    
    enhanced_logging_path = Path("src/enhanced_trade_logging.py")
    if enhanced_logging_path.exists():
        print(f"   ✅ enhanced_trade_logging.py exists")
    else:
        print(f"   ❌ enhanced_trade_logging.py not found")
        all_pass = False
    
    return all_pass


def check_recent_logs():
    """Check journalctl for recent ENHANCED-LOGGING messages"""
    print("\n" + "=" * 80)
    print("2. RECENT LOGS CHECK (last 24 hours)")
    print("=" * 80)
    
    try:
        # Check for success messages
        result = subprocess.run(
            ['journalctl', '-u', 'tradingbot', '--since', '24 hours ago', '--grep', 'ENHANCED-LOGGING'],
            capture_output=True,
            text=True,
            timeout=10
        )
        
        lines = result.stdout.strip().split('\n')
        success_count = sum(1 for line in lines if 'Captured volatility snapshot' in line)
        error_count = sum(1 for line in lines if 'Failed to capture' in line)
        
        print(f"   📊 Success messages: {success_count}")
        print(f"   ⚠️  Error messages: {error_count}")
        
        if success_count > 0:
            print(f"\n   Recent success messages:")
            for line in lines[-5:]:
                if 'Captured volatility snapshot' in line:
                    # Extract timestamp and message
                    parts = line.split('python3[')
                    if len(parts) > 1:
                        msg = parts[-1].split(']: ')[-1] if ']: ' in parts[-1] else parts[-1]
                        print(f"      ✅ {msg}")
        
        if error_count > 0:
            print(f"\n   Recent error messages:")
            for line in lines[-5:]:
                if 'Failed to capture' in line:
                    parts = line.split('python3[')
                    if len(parts) > 1:
                        msg = parts[-1].split(']: ')[-1] if ']: ' in parts[-1] else parts[-1]
                        print(f"      ⚠️  {msg}")
        
        return success_count > 0
        
    except Exception as e:
        print(f"   ⚠️  Could not check journalctl: {e}")
        return False


def check_recent_positions():
    """Check recent positions for volatility snapshots"""
    print("\n" + "=" * 80)
    print("3. RECENT POSITIONS CHECK")
    print("=" * 80)
    
    try:
        from src.data_registry import DataRegistry
        
        registry = DataRegistry()
        positions_file = Path(registry.POSITIONS_FUTURES)
        
        if not positions_file.exists():
            print(f"   ❌ Positions file not found: {positions_file}")
            return False
        
        with open(positions_file, 'r') as f:
            data = json.load(f)
        
        open_positions = data.get("open_positions", [])
        closed_positions = data.get("closed_positions", [])
        
        # Check open positions
        print(f"\n   📊 Open Positions: {len(open_positions)}")
        open_with_snapshots = 0
        for pos in open_positions:
            if pos.get("volatility_snapshot"):
                open_with_snapshots += 1
                snapshot = pos["volatility_snapshot"]
                symbol = pos.get("symbol", "unknown")
                atr = snapshot.get("atr_14", 0)
                regime = snapshot.get("regime_at_entry", "unknown")
                print(f"      ✅ {symbol}: ATR={atr:.2f}, Regime={regime}")
        
        print(f"   ✅ Open positions with snapshots: {open_with_snapshots}/{len(open_positions)}")
        
        # Check recent closed positions (last 24 hours)
        now = datetime.now(timezone.utc)
        recent_closed = []
        recent_with_snapshots = 0
        
        for pos in closed_positions:
            opened_at = pos.get("opened_at") or pos.get("open_ts")
            if not opened_at:
                continue
            
            try:
                if isinstance(opened_at, str):
                    opened_dt = datetime.fromisoformat(opened_at.replace('Z', '+00:00'))
                else:
                    opened_dt = datetime.fromtimestamp(float(opened_at), tz=timezone.utc)
                
                hours_ago = (now - opened_dt).total_seconds() / 3600
                if hours_ago <= 24:
                    recent_closed.append(pos)
                    if pos.get("volatility_snapshot"):
                        recent_with_snapshots += 1
            except:
                continue
        
        print(f"\n   📊 Closed Positions (last 24h): {len(recent_closed)}")
        print(f"   ✅ With snapshots: {recent_with_snapshots}/{len(recent_closed)}")
        
        if len(recent_closed) > 0:
            rate = (recent_with_snapshots / len(recent_closed)) * 100
            print(f"   📈 Capture rate: {rate:.1f}%")
            
            if rate >= 80:
                print(f"   ✅ GOOD: Capture rate is acceptable")
            elif rate >= 50:
                print(f"   ⚠️  WARNING: Capture rate is low")
            else:
                print(f"   ❌ POOR: Capture rate is very low")
        
        return open_with_snapshots == len(open_positions) if len(open_positions) > 0 else True
        
    except Exception as e:
        print(f"   ❌ Error checking positions: {e}")
        import traceback
        traceback.print_exc()
        return False


def check_function_exists():
    """Verify the function can be imported and called"""
    print("\n" + "=" * 80)
    print("4. FUNCTION AVAILABILITY CHECK")
    print("=" * 80)
    
    try:
        from src.enhanced_trade_logging import create_volatility_snapshot, is_golden_hour, check_stable_regime_block
        
        print("   ✅ create_volatility_snapshot imported successfully")
        print("   ✅ is_golden_hour imported successfully")
        print("   ✅ check_stable_regime_block imported successfully")
        
        # Test that it can be called (won't actually fetch data, just verify import)
        print("   ✅ All functions are importable and available")
        
        return True
        
    except ImportError as e:
        print(f"   ❌ Import error: {e}")
        return False
    except Exception as e:
        print(f"   ❌ Error: {e}")
        return False


def main():
    """Run all verification checks"""
    print("\n" + "=" * 80)
    print("ENHANCED LOGGING VERIFICATION")
    print("=" * 80)
    print(f"Timestamp: {datetime.now(timezone.utc).isoformat()}")
    
    results = {
        "Code Integration": check_code_integration(),
        "Recent Logs": check_recent_logs(),
        "Recent Positions": check_recent_positions(),
        "Function Availability": check_function_exists(),
    }
    
    print("\n" + "=" * 80)
    print("SUMMARY")
    print("=" * 80)
    
    all_pass = True
    for check, passed in results.items():
        status = "✅ PASS" if passed else "❌ FAIL"
        print(f"   {status}: {check}")
        if not passed:
            all_pass = False
    
    print("\n" + "=" * 80)
    if all_pass:
        print("✅ ENHANCED LOGGING IS WORKING AND IN PLACE")
    else:
        print("⚠️  SOME ISSUES DETECTED - REVIEW ABOVE")
    print("=" * 80)
    
    return 0 if all_pass else 1


if __name__ == "__main__":
    sys.exit(main())

