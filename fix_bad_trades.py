#!/usr/bin/env python3
"""
Emergency script to delete bad trades from Dec 18, 2025 1:00 AM - 6:00 AM
and verify dashboard data loading.
"""

import json
import os
from datetime import datetime
from pathlib import Path
from src.data_registry import DataRegistry as DR
from src.infrastructure.path_registry import resolve_path

def parse_datetime(date_str):
    """Parse datetime string to timestamp."""
    if isinstance(date_str, (int, float)):
        return float(date_str)
    if isinstance(date_str, str):
        # Try ISO format
        try:
            dt = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
            return dt.timestamp()
        except:
            pass
        # Try other formats
        try:
            dt = datetime.strptime(date_str, "%Y-%m-%d %H:%M:%S")
            return dt.timestamp()
        except:
            pass
    return None

def main():
    print("=" * 80)
    print("EMERGENCY FIX: Deleting bad trades from Dec 18, 2025 1:00-6:00 AM")
    print("=" * 80)
    
    # Load positions file
    positions_file = resolve_path(DR.POSITIONS_FUTURES)
    print(f"\nLoading positions from: {positions_file}")
    
    if not os.path.exists(positions_file):
        print(f"ERROR: File not found: {positions_file}")
        return
    
    # Backup first
    backup_file = positions_file + ".backup_before_deletion"
    print(f"Creating backup: {backup_file}")
    with open(positions_file, 'r') as f:
        data = json.load(f)
    with open(backup_file, 'w') as f:
        json.dump(data, f, indent=2)
    
    closed_positions = data.get("closed_positions", [])
    open_positions = data.get("open_positions", [])
    
    print(f"\nInitial state:")
    print(f"   Closed positions: {len(closed_positions)}")
    print(f"   Open positions: {len(open_positions)}")
    
    # Define bad time window: Dec 18, 2025 1:00 AM - 6:00 AM UTC
    bad_start = datetime(2025, 12, 18, 1, 0, 0).timestamp()  # 1:00 AM
    bad_end = datetime(2025, 12, 18, 6, 0, 0).timestamp()     # 6:00 AM
    
    print(f"\nFiltering out trades from {datetime.fromtimestamp(bad_start)} to {datetime.fromtimestamp(bad_end)}")
    
    # Filter closed positions
    good_closed = []
    bad_closed = []
    for pos in closed_positions:
        closed_at = pos.get("closed_at", "")
        if not closed_at:
            # Keep positions without closed_at (shouldn't happen, but be safe)
            good_closed.append(pos)
            continue
        
        closed_ts = parse_datetime(closed_at)
        if closed_ts is None:
            print(f"WARNING: Could not parse closed_at: {closed_at}")
            good_closed.append(pos)  # Keep if we can't parse
            continue
        
        # Check if in bad time window
        if bad_start <= closed_ts < bad_end:
            bad_closed.append(pos)
            pnl = pos.get("pnl", pos.get("net_pnl", 0))
            symbol = pos.get("symbol", "N/A")
            print(f"   DELETING: {closed_at} - {symbol} - P&L: ${pnl:.2f}")
        else:
            good_closed.append(pos)
    
    # Filter open positions (check entry_time)
    good_open = []
    bad_open = []
    for pos in open_positions:
        entry_time = pos.get("entry_time", pos.get("opened_at", ""))
        if not entry_time:
            good_open.append(pos)  # Keep if no entry time
            continue
        
        entry_ts = parse_datetime(entry_time)
        if entry_ts is None:
            good_open.append(pos)  # Keep if we can't parse
            continue
        
        # Check if in bad time window
        if bad_start <= entry_ts < bad_end:
            bad_open.append(pos)
            symbol = pos.get("symbol", "N/A")
            print(f"   DELETING open position: {entry_time} - {symbol}")
        else:
            good_open.append(pos)
    
    print(f"\nResults:")
    print(f"   Closed positions: {len(closed_positions)} -> {len(good_closed)} (deleted {len(bad_closed)})")
    print(f"   Open positions: {len(open_positions)} -> {len(good_open)} (deleted {len(bad_open)})")
    
    # Calculate total P&L of deleted trades
    deleted_pnl = sum(pos.get("pnl", pos.get("net_pnl", 0)) or 0 for pos in bad_closed)
    print(f"   Total P&L of deleted trades: ${deleted_pnl:.2f}")
    
    # Update data
    data["closed_positions"] = good_closed
    data["open_positions"] = good_open
    
    # Save
    print(f"\nSaving updated positions file...")
    with open(positions_file, 'w') as f:
        json.dump(data, f, indent=2)
    
    print(f"DONE! Deleted {len(bad_closed)} closed trades and {len(bad_open)} open positions")
    print(f"Backup saved to: {backup_file}")
    
    # Verify dashboard can load data
    print(f"\nVerifying dashboard can load data...")
    try:
        from src.pnl_dashboard_v2 import load_closed_positions_df, get_wallet_balance
        df = load_closed_positions_df()
        wallet = get_wallet_balance()
        print(f"SUCCESS: Dashboard can load {len(df)} closed positions")
        print(f"SUCCESS: Wallet balance: ${wallet:.2f}")
    except Exception as e:
        print(f"WARNING: Dashboard verification failed: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()




