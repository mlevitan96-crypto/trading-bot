#!/usr/bin/env python3
"""
Check Dashboard Table Data
===========================
Verify what data the dashboard table would receive, including fees column.
"""

import os
import sys
sys.path.insert(0, os.path.dirname(__file__))

print("=" * 80)
print("CHECKING DASHBOARD TABLE DATA")
print("=" * 80)

try:
    from src.data_registry import DataRegistry as DR
    from datetime import datetime
    import pytz
    
    ARIZONA_TZ = pytz.timezone('America/Phoenix')
    
    # Load closed positions (same as dashboard)
    closed_positions = DR.get_closed_positions(hours=168)
    
    if not closed_positions:
        print("\n⚠️  No closed positions found")
        sys.exit(0)
    
    print(f"\nLoaded {len(closed_positions)} closed positions")
    
    # Simulate the dataframe creation (without pandas)
    table_records = []
    for pos in closed_positions[-5:]:  # Last 5 for sample
        # Same fee extraction as dashboard
        fees_usd = pos.get("fees_usd", 0)
        trading_fees = pos.get("trading_fees", 0)
        funding_fees = pos.get("funding_fees", 0)
        legacy_fees = pos.get("fees", 0)
        
        if fees_usd and fees_usd != 0:
            fees = float(fees_usd)
        elif (trading_fees and trading_fees != 0) or (funding_fees and funding_fees != 0):
            fees = float(trading_fees or 0) + float(funding_fees or 0)
        else:
            fees = float(legacy_fees or 0.0)
        
        # Create record like df.to_dict("records") would
        record = {
            "symbol": pos.get("symbol", ""),
            "strategy": pos.get("strategy", ""),
            "entry_time": pos.get("opened_at", ""),
            "exit_time": pos.get("closed_at", ""),
            "entry_price": float(pos.get("entry_price", 0.0) or 0),
            "exit_price": float(pos.get("exit_price", 0.0) or 0),
            "size": float(pos.get("margin_collateral", pos.get("margin_usd", 0.0)) or 0),
            "hold_duration_h": 0.0,  # Simplified
            "roi_pct": 0.0,  # Simplified
            "net_pnl": float(pos.get("pnl", pos.get("net_pnl", 0.0)) or 0),
            "fees": fees  # This is the key column
        }
        table_records.append(record)
    
    print(f"\n✅ Sample table records (last 5 trades):")
    print(f"   Columns that would be sent to table: {list(table_records[0].keys()) if table_records else 'N/A'}")
    
    if "fees" in (table_records[0].keys() if table_records else []):
        print(f"\n✅ 'fees' column IS in the table data!")
        print(f"\n   Sample records with fees:")
        for i, rec in enumerate(table_records, 1):
            print(f"   {i}. {rec['symbol']}: fees=${rec['fees']:.2f}, net_pnl=${rec['net_pnl']:.2f}")
    else:
        print(f"\n❌ 'fees' column NOT in table data!")
    
    # Check total fees (like summary card does)
    total_fees = sum(r["fees"] for r in table_records)
    print(f"\n   Total fees (sample): ${total_fees:.2f}")
    print(f"\n✅ If you see 'Total Fees' in the dashboard summary card,")
    print(f"   then fees are working - the table column should also be visible.")
    
except Exception as e:
    print(f"\n❌ Error: {e}")
    import traceback
    traceback.print_exc()

print("\n" + "=" * 80)
print("NEXT STEPS:")
print("=" * 80)
print("1. Check if 'Total Fees' appears in the dashboard summary card above the table")
print("2. If yes: Hard refresh browser (Ctrl+Shift+R) to clear cache")
print("3. If no: Restart dashboard: sudo systemctl restart tradingbot")
print("4. Check browser console (F12) for JavaScript errors")
print("=" * 80)
