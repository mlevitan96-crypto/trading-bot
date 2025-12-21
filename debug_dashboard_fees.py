#!/usr/bin/env python3
"""
Debug Dashboard Fees
====================
Check what fee data is actually in the closed positions and if it's being loaded correctly.
"""

import os
import sys
import json
from pathlib import Path

sys.path.insert(0, os.path.dirname(__file__))

print("=" * 80)
print("DEBUG DASHBOARD FEES")
print("=" * 80)

# Check what's in positions_futures.json
positions_file = Path("logs/positions_futures.json")
if positions_file.exists():
    print("\n1. CHECKING positions_futures.json")
    print("-" * 80)
    try:
        with open(positions_file, 'r') as f:
            data = json.load(f)
            closed = data.get("closed_positions", [])
            print(f"   Total closed positions: {len(closed)}")
            
            if closed:
                # Check last 5 trades for fee fields
                recent = closed[-5:]
                print(f"\n   Last 5 trades fee fields:")
                for i, pos in enumerate(recent, 1):
                    symbol = pos.get("symbol", "UNKNOWN")
                    trading_fees = pos.get("trading_fees", "MISSING")
                    funding_fees = pos.get("funding_fees", "MISSING")
                    fees_usd = pos.get("fees_usd", "MISSING")
                    legacy_fees = pos.get("fees", "MISSING")
                    
                    print(f"\n   {i}. {symbol}:")
                    print(f"      trading_fees: {trading_fees}")
                    print(f"      funding_fees: {funding_fees}")
                    print(f"      fees_usd: {fees_usd}")
                    print(f"      fees (legacy): {legacy_fees}")
                    
                    # Calculate what should be shown
                    if fees_usd != "MISSING" and fees_usd != 0:
                        total = fees_usd
                    elif (trading_fees != "MISSING" and trading_fees != 0) or (funding_fees != "MISSING" and funding_fees != 0):
                        total = (trading_fees if trading_fees != "MISSING" else 0) + (funding_fees if funding_fees != "MISSING" else 0)
                    else:
                        total = legacy_fees if legacy_fees != "MISSING" else 0
                    
                    print(f"      → Total fees (calculated): ${total}")
    except Exception as e:
        print(f"   ❌ Error reading file: {e}")
        import traceback
        traceback.print_exc()
else:
    print(f"\n   ⚠️  positions_futures.json not found")

# Check what load_closed_positions_df() returns
print("\n2. CHECKING load_closed_positions_df() OUTPUT")
print("-" * 80)
try:
    from src.pnl_dashboard import load_closed_positions_df
    df = load_closed_positions_df()
    
    print(f"   DataFrame shape: {df.shape}")
    print(f"   Columns: {list(df.columns)}")
    
    if not df.empty:
        print(f"\n   Last 5 rows fee data:")
        for idx, row in df.tail(5).iterrows():
            symbol = row.get("symbol", "UNKNOWN")
            fees = row.get("fees", 0)
            trading_fees = row.get("trading_fees", 0)
            funding_fees = row.get("funding_fees", 0)
            
            print(f"   {symbol}: fees=${fees:.2f}, trading=${trading_fees:.2f}, funding=${funding_fees:.2f}")
        
        # Check if fees column has any non-zero values
        import pandas as pd
        non_zero_fees = df[df["fees"] > 0] if "fees" in df.columns else pd.DataFrame()
        print(f"\n   Trades with fees > 0: {len(non_zero_fees)}/{len(df)}")
        if len(non_zero_fees) > 0:
            print(f"   Sample fees: min=${df['fees'].min():.2f}, max=${df['fees'].max():.2f}, avg=${df['fees'].mean():.2f}")
        else:
            print(f"   ⚠️  ALL fees are $0.00 - this is the problem!")
    else:
        print("   ⚠️  DataFrame is empty")
        
except Exception as e:
    print(f"   ❌ Error loading dataframe: {e}")
    import traceback
    traceback.print_exc()

print("\n" + "=" * 80)
