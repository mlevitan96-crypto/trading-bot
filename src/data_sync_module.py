# src/data_sync_module.py
#
# Data Integrity Sync Module
# Purpose: Ensure executed_trades.jsonl has correct fields for learning systems
# Syncs from trades_futures_backup.json (authoritative source) to executed_trades.jsonl
#
# Fields learning systems expect:
#   - pnl_pct: P&L as percentage (e.g., 1.25 for 1.25%)
#   - net_pnl: P&L in USD
#   - strategy_id: Strategy name
#   - symbol, timestamp, fees, etc.

import json
import os
from pathlib import Path

FUTURES_BACKUP = "logs/trades_futures_backup.json"
EXECUTED_TRADES = "logs/executed_trades.jsonl"
SYNC_LOG = "logs/data_sync.log"

def _append_jsonl(filepath, entry):
    """Append a single JSON entry to a .jsonl file."""
    with open(filepath, 'a') as f:
        f.write(json.dumps(entry) + '\n')

def _read_jsonl(filepath):
    """Read all entries from a .jsonl file."""
    entries = []
    if not os.path.exists(filepath):
        return entries
    
    with open(filepath, 'r') as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    entries.append(json.loads(line))
                except:
                    continue
    return entries

def map_trade_to_execution_format(trade):
    """
    Convert trade from trades_futures_backup.json format to executed_trades.jsonl format.
    
    Input format (from trades_futures_backup.json):
        {
            "timestamp": "2025-11-13T09:55:46...",
            "symbol": "ETHUSDT",
            "strategy": "EMA-Futures",
            "net_pnl": -1.037843,
            "net_roi": -0.3686443,
            "trading_fees": 0.0168,
            "entry_price": 3607.48,
            "exit_price": 3345.81,
            ... (other fields)
        }
    
    Output format (for executed_trades.jsonl):
        {
            "ts": 1700000000,
            "symbol": "ETHUSDT",
            "strategy_id": "EMA-Futures",
            "pnl_pct": -36.86,  # net_roi * 100
            "net_pnl": -1.037843,
            "pnl": -0.003686,  # net_roi in decimal
            "fees": 0.0168,
            "entry_price": 3607.48,
            "exit_price": 3345.81,
            "direction": "LONG",
            "venue": "futures",
            ... (preserve all other fields)
        }
    """
    from datetime import datetime
    import time
    
    # Parse timestamp to unix time
    ts_str = trade.get('timestamp', '')
    try:
        # Handle Arizona time format "2025-11-13T09:55:46.876886-07:00"
        dt = datetime.fromisoformat(ts_str)
        ts = int(dt.timestamp())
    except:
        ts = int(time.time())
    
    # Extract fields
    net_pnl = trade.get('net_pnl', 0)
    net_roi = trade.get('net_roi', 0)
    trading_fees = trade.get('trading_fees', 0)
    
    # Map to execution format
    execution_entry = {
        "ts": ts,
        "symbol": trade.get('symbol', 'UNKNOWN'),
        "strategy_id": trade.get('strategy', 'unknown'),
        "pnl_pct": round(net_roi * 100, 4),  # Convert decimal to percentage
        "net_pnl": round(net_pnl, 6),
        "pnl": round(net_roi, 6),  # Decimal format (for backward compatibility)
        "fees": round(trading_fees, 6),
        "trading_fees": round(trading_fees, 6),
        "entry_price": trade.get('entry_price', 0),
        "exit_price": trade.get('exit_price', 0),
        "direction": trade.get('direction', 'LONG'),
        "venue": "futures",
        "leverage": trade.get('leverage', 1),
        "margin_collateral": trade.get('margin_collateral', 0),
        "notional_size": trade.get('notional_size', 0),
        "gross_pnl": trade.get('gross_pnl', 0),
        "price_roi": trade.get('price_roi', 0),
        "leveraged_roi": trade.get('leveraged_roi', 0),
        "funding_fees": trade.get('funding_fees', 0),
        "quantity": trade.get('quantity', 0),
        "timestamp": ts_str,
        "entry_ts": ts,
        "exit_ts": ts
    }
    
    return execution_entry

def backfill_historical_trades(overwrite=False):
    """
    Backfill all trades from trades_futures_backup.json into executed_trades.jsonl.
    
    Args:
        overwrite: If True, clear executed_trades.jsonl and rebuild from scratch
    
    Returns:
        dict with sync stats
    """
    from datetime import datetime
    
    print(f"\n{'='*70}")
    print("🔄 DATA SYNC: Backfilling Historical Trades")
    print("="*70)
    
    # Load source data
    if not os.path.exists(FUTURES_BACKUP):
        return {"error": "futures_backup.json not found", "synced": 0}
    
    with open(FUTURES_BACKUP, 'r') as f:
        futures_data = json.load(f)
    
    trades = futures_data.get('trades', [])
    print(f"Found {len(trades)} trades in futures_backup.json")
    
    # Get existing executed_trades entries (to avoid duplicates)
    existing_entries = [] if overwrite else _read_jsonl(EXECUTED_TRADES)
    existing_symbols_ts = {(e.get('symbol'), e.get('ts')) for e in existing_entries}
    
    print(f"Existing entries in executed_trades.jsonl: {len(existing_entries)}")
    
    if overwrite:
        # Clear the file
        Path(EXECUTED_TRADES).parent.mkdir(parents=True, exist_ok=True)
        with open(EXECUTED_TRADES, 'w') as f:
            pass
        print("⚠️  Cleared executed_trades.jsonl (overwrite=True)")
    
    # Sync trades
    synced = 0
    skipped = 0
    
    for trade in trades:
        entry = map_trade_to_execution_format(trade)
        key = (entry['symbol'], entry['ts'])
        
        if key in existing_symbols_ts and not overwrite:
            skipped += 1
            continue
        
        _append_jsonl(EXECUTED_TRADES, entry)
        synced += 1
    
    print(f"\n✅ Sync complete:")
    print(f"   Synced: {synced} new trades")
    print(f"   Skipped: {skipped} duplicates")
    print(f"   Total in executed_trades.jsonl: {len(_read_jsonl(EXECUTED_TRADES))}")
    
    # Log sync event
    sync_summary = {
        "timestamp": datetime.now().isoformat(),
        "source": FUTURES_BACKUP,
        "destination": EXECUTED_TRADES,
        "total_source_trades": len(trades),
        "synced": synced,
        "skipped": skipped,
        "overwrite": overwrite
    }
    
    _append_jsonl(SYNC_LOG, sync_summary)
    
    return sync_summary

def sync_single_trade(trade_data):
    """
    Sync a single trade to executed_trades.jsonl in real-time.
    Called by position_manager when closing a position.
    
    Args:
        trade_data: Trade dict from trades_futures_backup.json format
    
    Returns:
        Mapped execution entry
    """
    entry = map_trade_to_execution_format(trade_data)
    _append_jsonl(EXECUTED_TRADES, entry)
    return entry

def validate_data_integrity():
    """
    Validate that executed_trades.jsonl has all required fields for learning.
    
    Returns:
        dict with validation results
    """
    print(f"\n{'='*70}")
    print("✅ DATA INTEGRITY VALIDATION")
    print("="*70)
    
    entries = _read_jsonl(EXECUTED_TRADES)
    
    if not entries:
        return {"status": "FAIL", "reason": "No entries in executed_trades.jsonl"}
    
    required_fields = ['pnl_pct', 'net_pnl', 'strategy_id', 'symbol', 'ts', 'fees']
    missing_fields = set()
    
    for entry in entries:
        for field in required_fields:
            if field not in entry:
                missing_fields.add(field)
    
    if missing_fields:
        return {
            "status": "FAIL",
            "reason": f"Missing fields: {', '.join(missing_fields)}",
            "total_entries": len(entries)
        }
    
    # Calculate stats
    total_pnl = sum(e.get('net_pnl', 0) for e in entries)
    total_fees = sum(e.get('fees', 0) for e in entries)
    winners = sum(1 for e in entries if e.get('net_pnl', 0) > 0)
    win_rate = winners / len(entries) * 100 if entries else 0
    
    print(f"\n📊 Validation Results:")
    print(f"   Total entries: {len(entries)}")
    print(f"   All required fields present: ✅")
    print(f"   Win rate: {win_rate:.1f}%")
    print(f"   Total P&L: ${total_pnl:.2f}")
    print(f"   Total fees: ${total_fees:.2f}")
    
    return {
        "status": "PASS",
        "total_entries": len(entries),
        "win_rate": win_rate,
        "total_pnl": total_pnl,
        "total_fees": total_fees,
        "required_fields": required_fields,
        "sample_entry": entries[-1] if entries else None
    }

if __name__ == "__main__":
    from datetime import datetime
    import sys
    
    # Run backfill
    result = backfill_historical_trades(overwrite=False)
    print(f"\n{result}")
    
    # Validate
    validation = validate_data_integrity()
    print(f"\n{validation}")
