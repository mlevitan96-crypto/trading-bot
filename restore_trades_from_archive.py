#!/usr/bin/env python3
"""
Restore trades from archive created by reset_portfolio_kraken_fresh_start.py
This allows you to view or restore historical trade data after a reset.
"""

import sys
from pathlib import Path
import json
from datetime import datetime

_project_root = Path(__file__).parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from src.position_manager import load_futures_positions, save_futures_positions

def list_archives():
    """List all available archives."""
    backup_dir = Path("backups")
    if not backup_dir.exists():
        return []
    
    archives = []
    for archive_dir in sorted(backup_dir.iterdir(), key=lambda x: x.stat().st_mtime, reverse=True):
        if archive_dir.is_dir() and archive_dir.name.startswith("kraken_fresh_start_"):
            summary_file = archive_dir / "archive_summary.json"
            if summary_file.exists():
                try:
                    with open(summary_file, 'r') as f:
                        summary = json.load(f)
                    archives.append({
                        "dir": archive_dir,
                        "timestamp": summary.get("archive_timestamp", ""),
                        "closed_count": summary.get("previous_state", {}).get("closed_positions_count", 0),
                        "open_count": summary.get("previous_state", {}).get("open_positions_count", 0)
                    })
                except:
                    pass
    
    return archives

def restore_from_archive(archive_dir: Path, restore_closed=True, restore_open=False):
    """Restore trades from archive."""
    positions_file = archive_dir / "positions_futures.json"
    
    if not positions_file.exists():
        print(f"❌ Archive file not found: {positions_file}")
        return False
    
    print(f"📦 Loading archive from: {archive_dir.name}")
    with open(positions_file, 'r') as f:
        archived_positions = json.load(f)
    
    current_positions = load_futures_positions()
    
    archived_closed = archived_positions.get("closed_positions", [])
    archived_open = archived_positions.get("open_positions", [])
    
    print(f"   Archived closed positions: {len(archived_closed)}")
    print(f"   Archived open positions: {len(archived_open)}")
    print()
    
    if restore_closed:
        print("Restoring closed positions...")
        # Append archived closed positions to current (avoid duplicates by checking closed_at)
        existing_closed = {pos.get("closed_at", "") for pos in current_positions.get("closed_positions", [])}
        
        restored_count = 0
        for pos in archived_closed:
            if pos.get("closed_at", "") not in existing_closed:
                current_positions.setdefault("closed_positions", []).append(pos)
                restored_count += 1
        
        print(f"   ✅ Restored {restored_count} closed positions")
        print(f"   Total closed positions now: {len(current_positions.get('closed_positions', []))}")
    
    if restore_open:
        print("Restoring open positions...")
        # For open positions, only restore if they don't exist
        existing_open = {(pos.get("symbol", ""), pos.get("strategy", ""), pos.get("direction", "")) 
                         for pos in current_positions.get("open_positions", [])}
        
        restored_count = 0
        for pos in archived_open:
            key = (pos.get("symbol", ""), pos.get("strategy", ""), pos.get("direction", ""))
            if key not in existing_open:
                current_positions.setdefault("open_positions", []).append(pos)
                restored_count += 1
        
        print(f"   ✅ Restored {restored_count} open positions")
        print(f"   Total open positions now: {len(current_positions.get('open_positions', []))}")
    
    # Save restored positions
    save_futures_positions(current_positions)
    print()
    print("✅ Positions restored successfully!")
    
    return True

def main():
    print("=" * 70)
    print("RESTORE TRADES FROM ARCHIVE")
    print("=" * 70)
    print()
    
    archives = list_archives()
    
    if not archives:
        print("❌ No archives found in backups/ directory")
        print()
        print("Archives are created when you run reset_portfolio_kraken_fresh_start.py")
        print("Check if backups/ directory exists and contains kraken_fresh_start_* folders")
        return
    
    print(f"Found {len(archives)} archive(s):")
    print()
    
    for i, archive in enumerate(archives, 1):
        print(f"[{i}] {archive['dir'].name}")
        print(f"    Timestamp: {archive['timestamp']}")
        print(f"    Closed positions: {archive['closed_count']}")
        print(f"    Open positions: {archive['open_count']}")
        print()
    
    if len(archives) == 1:
        selected = archives[0]
        print(f"Using latest archive: {selected['dir'].name}")
    else:
        choice = input(f"Select archive to restore from (1-{len(archives)}): ").strip()
        try:
            idx = int(choice) - 1
            if idx < 0 or idx >= len(archives):
                print("Invalid selection.")
                return
            selected = archives[idx]
        except ValueError:
            print("Invalid selection.")
            return
    
    print()
    print("=" * 70)
    print("RESTORE OPTIONS")
    print("=" * 70)
    print()
    print("1. Restore closed positions only (recommended - adds historical trades back)")
    print("2. Restore both closed and open positions")
    print("3. View archive contents only (no restore)")
    print()
    
    choice = input("Choose option (1/2/3): ").strip()
    
    if choice == "1":
        restore_from_archive(selected["dir"], restore_closed=True, restore_open=False)
    elif choice == "2":
        restore_from_archive(selected["dir"], restore_closed=True, restore_open=True)
    elif choice == "3":
        print()
        print("Archive contents:")
        positions_file = selected["dir"] / "positions_futures.json"
        if positions_file.exists():
            with open(positions_file, 'r') as f:
                data = json.load(f)
            print(f"   Closed positions: {len(data.get('closed_positions', []))}")
            print(f"   Open positions: {len(data.get('open_positions', []))}")
            
            if data.get("closed_positions"):
                print()
                print("   Sample closed positions (first 5):")
                for i, pos in enumerate(data["closed_positions"][:5], 1):
                    symbol = pos.get("symbol", "?")
                    entry = pos.get("entry_price", 0)
                    exit = pos.get("exit_price", 0)
                    pnl = pos.get("pnl", 0)
                    closed_at = pos.get("closed_at", "")[:19] if pos.get("closed_at") else "?"
                    print(f"      [{i}] {symbol}: ${entry:,.2f} → ${exit:,.2f}, P&L: ${pnl:,.2f} ({closed_at})")
        else:
            print("   Archive file not found")
    else:
        print("Invalid choice.")

if __name__ == "__main__":
    main()
