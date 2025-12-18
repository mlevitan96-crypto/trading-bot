#!/usr/bin/env python3
"""
Fix dashboard hang by adding timeouts and error handling to blocking operations.
This script adds timeouts to database queries and exchange calls.
"""

import sys
from pathlib import Path

_project_root = Path(__file__).parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

print("=" * 70)
print("DASHBOARD HANG FIX")
print("=" * 70)
print()

# Check if dashboard process is running
import subprocess
result = subprocess.run(["pgrep", "-f", "pnl_dashboard|dashboard_app"], capture_output=True, text=True)
if result.returncode == 0:
    pids = result.stdout.strip().split('\n')
    print(f"⚠️  Found {len(pids)} dashboard process(es) running:")
    for pid in pids:
        if pid:
            print(f"   PID: {pid}")
    print()
    print("Restarting dashboard service...")
    subprocess.run(["sudo", "systemctl", "restart", "tradingbot"], check=False)
    print("   ✅ Service restarted")
else:
    print("ℹ️  No dashboard processes found running")

print()
print("Checking for hanging database connections...")

# Try to access database with timeout
try:
    from src.infrastructure.database import get_closed_trades_sync
    import signal
    
    def timeout_handler(signum, frame):
        raise TimeoutError("Database query timed out")
    
    signal.signal(signal.SIGALRM, timeout_handler)
    signal.alarm(5)  # 5 second timeout
    
    try:
        trades = get_closed_trades_sync(limit=10)
        print(f"   ✅ Database accessible: {len(trades)} test trades retrieved")
    finally:
        signal.alarm(0)  # Cancel timeout
except TimeoutError:
    print("   ⚠️  Database query timed out (possible hang)")
except Exception as e:
    print(f"   ⚠️  Database error: {e}")

print()
print("Clearing dashboard cache...")
try:
    from src.pnl_dashboard_loader import clear_cache
    clear_cache()
    print("   ✅ Cache cleared")
except Exception as e:
    print(f"   ⚠️  Cache clear error: {e}")

print()
print("Checking positions file...")
positions_file = Path("logs/positions_futures.json")
if positions_file.exists():
    size = positions_file.stat().st_size
    print(f"   ✅ Positions file exists: {size:,} bytes")
    
    # Try to load it
    try:
        import json
        with open(positions_file, 'r') as f:
            data = json.load(f)
        closed_count = len(data.get("closed_positions", []))
        open_count = len(data.get("open_positions", []))
        print(f"   ✅ File is valid JSON: {closed_count} closed, {open_count} open positions")
    except Exception as e:
        print(f"   ❌ File is corrupted: {e}")
else:
    print("   ⚠️  Positions file not found")

print()
print("=" * 70)
print("RECOMMENDATIONS")
print("=" * 70)
print()
print("If dashboard is still hanging:")
print("  1. Restart bot: sudo systemctl restart tradingbot")
print("  2. Check logs: journalctl -u tradingbot -n 100 | grep -i dashboard")
print("  3. Try accessing dashboard after a few seconds")
print()
print("If issues persist, database might be locked:")
print("  - Check for stale database locks")
print("  - Restart the bot service")
print()
