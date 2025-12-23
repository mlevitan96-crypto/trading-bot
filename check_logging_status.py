#!/usr/bin/env python3
"""
Detailed Enhanced Logging Status Check
======================================
Checks why enhanced logging might not be working by analyzing:
- When trades were opened (vs when logging was enabled on Dec 22, 2025)
- Open positions to see if they have snapshots
- Sample trades to understand the data structure
"""

import json
import os
import sys
from datetime import datetime, timezone, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

try:
    from src.position_manager import load_futures_positions
except ImportError as e:
    print(f"ERROR: Import error: {e}")
    sys.exit(1)


def parse_timestamp(ts_str: str) -> float:
    """Parse timestamp string to Unix timestamp."""
    if isinstance(ts_str, (int, float)):
        return float(ts_str)
    try:
        ts_clean = ts_str.replace('Z', '+00:00')
        if '.' in ts_clean and '+' in ts_clean:
            parts = ts_clean.split('+')
            if len(parts) == 2:
                main_part = parts[0].split('.')[0]
                tz_part = parts[1]
                ts_clean = f"{main_part}+{tz_part}"
        dt = datetime.fromisoformat(ts_clean)
        return dt.timestamp()
    except:
        return 0.0


def format_date(ts_str: str) -> str:
    """Format timestamp to readable date."""
    ts = parse_timestamp(ts_str)
    if ts == 0:
        return "Invalid"
    dt = datetime.fromtimestamp(ts, tz=timezone.utc)
    return dt.strftime("%Y-%m-%d %H:%M:%S UTC")


def check_logging_status():
    """Detailed check of enhanced logging status."""
    print("=" * 80)
    print("ENHANCED LOGGING STATUS CHECK")
    print("=" * 80)
    print()
    
    # Enhanced logging was deployed on December 22, 2025
    logging_deployment_date = datetime(2025, 12, 22, 0, 0, 0, tzinfo=timezone.utc)
    logging_deployment_ts = logging_deployment_date.timestamp()
    
    print(f"Enhanced Logging Deployment Date: {logging_deployment_date.strftime('%Y-%m-%d %H:%M:%S UTC')}")
    print(f"Deployment Timestamp: {logging_deployment_ts}")
    print()
    
    positions_data = load_futures_positions()
    closed_positions = positions_data.get("closed_positions", [])
    open_positions = positions_data.get("open_positions", [])
    
    # Filter today's closed trades
    today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    today_end = today_start + timedelta(days=1)
    
    today_closed = []
    for pos in closed_positions:
        closed_at = pos.get("closed_at") or pos.get("timestamp")
        if closed_at:
            ts = parse_timestamp(closed_at)
            if today_start.timestamp() <= ts < today_end.timestamp():
                today_closed.append(pos)
    
    print(f"Today's Closed Trades: {len(today_closed)}")
    print()
    
    # Check open positions opened today
    today_opened = []
    for pos in open_positions:
        opened_at = pos.get("opened_at") or pos.get("timestamp")
        if opened_at:
            ts = parse_timestamp(opened_at)
            if today_start.timestamp() <= ts < today_end.timestamp():
                today_opened.append(pos)
    
    print(f"Open Positions Opened Today: {len(today_opened)}")
    print()
    
    # Analyze closed trades
    trades_opened_after_deployment = 0
    trades_with_snapshots = 0
    trades_opened_before_deployment = 0
    
    sample_trade_details = []
    
    for i, pos in enumerate(today_closed[:10]):  # Check first 10
        opened_at = pos.get("opened_at") or pos.get("timestamp")
        closed_at = pos.get("closed_at") or pos.get("timestamp")
        opened_ts = parse_timestamp(opened_at)
        
        has_snapshot = bool(pos.get("volatility_snapshot", {}))
        
        if opened_ts >= logging_deployment_ts:
            trades_opened_after_deployment += 1
        else:
            trades_opened_before_deployment += 1
        
        if has_snapshot:
            trades_with_snapshots += 1
        
        snapshot = pos.get("volatility_snapshot", {})
        
        sample_trade_details.append({
            "symbol": pos.get("symbol", "UNKNOWN"),
            "opened_at": format_date(opened_at),
            "opened_ts": opened_ts,
            "closed_at": format_date(closed_at),
            "opened_after_deployment": opened_ts >= logging_deployment_ts,
            "has_snapshot": has_snapshot,
            "snapshot_keys": list(snapshot.keys()) if snapshot else [],
            "snapshot_atr": snapshot.get("atr_14") if snapshot else None,
        })
    
    # Check all closed trades
    total_opened_after = 0
    total_with_snapshots = 0
    
    for pos in today_closed:
        opened_at = pos.get("opened_at") or pos.get("timestamp")
        opened_ts = parse_timestamp(opened_at)
        if opened_ts >= logging_deployment_ts:
            total_opened_after += 1
            if bool(pos.get("volatility_snapshot", {})):
                total_with_snapshots += 1
    
    print("=" * 80)
    print("ANALYSIS OF TODAY'S CLOSED TRADES")
    print("=" * 80)
    print()
    print(f"Total closed trades today: {len(today_closed)}")
    print(f"Trades opened AFTER Dec 22, 2025 (should have snapshots): {total_opened_after}")
    print(f"Trades opened BEFORE Dec 22, 2025 (won't have snapshots): {len(today_closed) - total_opened_after}")
    print(f"Trades with snapshots (opened after deployment): {total_with_snapshots}")
    print()
    
    if total_opened_after > 0:
        snapshot_rate = (total_with_snapshots / total_opened_after) * 100
        print(f"Snapshot capture rate: {snapshot_rate:.1f}% ({total_with_snapshots}/{total_opened_after})")
        
        if snapshot_rate == 0:
            print()
            print("⚠️  ISSUE DETECTED: Enhanced logging is NOT working!")
            print("   All trades opened after deployment should have snapshots, but none do.")
            print("   This indicates the logging code is failing silently.")
        elif snapshot_rate < 100:
            print()
            print(f"⚠️  PARTIAL ISSUE: Only {snapshot_rate:.1f}% of trades have snapshots")
            print("   Some trades are missing snapshots - check for errors in logs")
        else:
            print()
            print("✅ Enhanced logging is working correctly!")
    else:
        print()
        print("ℹ️  No trades were opened after deployment date.")
        print("   All today's closed trades were opened before Dec 22, 2025")
        print("   Enhanced logging only captures data for NEW positions opened after deployment")
    
    print()
    print("=" * 80)
    print("SAMPLE TRADE DETAILS (First 10)")
    print("=" * 80)
    print()
    
    for i, trade in enumerate(sample_trade_details, 1):
        print(f"Trade {i}: {trade['symbol']}")
        print(f"  Opened: {trade['opened_at']}")
        print(f"  Closed: {trade['closed_at']}")
        print(f"  Opened after deployment: {trade['opened_after_deployment']}")
        print(f"  Has snapshot: {trade['has_snapshot']}")
        if trade['has_snapshot']:
            print(f"  Snapshot keys: {trade['snapshot_keys']}")
            if trade['snapshot_atr']:
                print(f"  ATR: {trade['snapshot_atr']:.2f}")
        print()
    
    # Check open positions
    print("=" * 80)
    print("OPEN POSITIONS ANALYSIS")
    print("=" * 80)
    print()
    
    open_with_snapshots = 0
    open_opened_after_deployment = 0
    
    for pos in open_positions:
        opened_at = pos.get("opened_at") or pos.get("timestamp")
        opened_ts = parse_timestamp(opened_at)
        if opened_ts >= logging_deployment_ts:
            open_opened_after_deployment += 1
            if bool(pos.get("volatility_snapshot", {})):
                open_with_snapshots += 1
    
    print(f"Total open positions: {len(open_positions)}")
    print(f"Opened after deployment: {open_opened_after_deployment}")
    print(f"With snapshots: {open_with_snapshots}")
    
    if open_opened_after_deployment > 0:
        open_rate = (open_with_snapshots / open_opened_after_deployment) * 100
        print(f"Snapshot rate for open positions: {open_rate:.1f}%")
        
        if open_rate == 0:
            print()
            print("⚠️  Open positions also missing snapshots - confirms logging issue")
    
    print()
    print("=" * 80)
    print("CONCLUSION")
    print("=" * 80)
    print()
    
    if total_opened_after == 0 and open_opened_after_deployment == 0:
        print("✅ Enhanced logging status: CANNOT VERIFY (no new trades yet)")
        print("   All trades analyzed were opened before deployment.")
        print("   Wait for new trades to be opened after Dec 22, 2025 to verify logging.")
    elif total_with_snapshots == 0 and open_with_snapshots == 0 and (total_opened_after > 0 or open_opened_after_deployment > 0):
        print("❌ Enhanced logging status: NOT WORKING")
        print("   Trades opened after deployment have no snapshots.")
        print("   The create_volatility_snapshot() function is likely failing silently.")
        print("   Check bot logs for errors during position opening.")
    elif total_with_snapshots > 0 or open_with_snapshots > 0:
        rate = ((total_with_snapshots + open_with_snapshots) / (total_opened_after + open_opened_after_deployment)) * 100 if (total_opened_after + open_opened_after_deployment) > 0 else 0
        print(f"⚠️  Enhanced logging status: PARTIALLY WORKING ({rate:.1f}%)")
        print("   Some trades have snapshots, but not all.")
        print("   Check for intermittent errors in the logging code.")
    
    print()


if __name__ == "__main__":
    check_logging_status()

