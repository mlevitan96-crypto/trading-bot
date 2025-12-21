#!/usr/bin/env python3
"""
Verify Dashboard Fees
=====================
Quick test to verify fees are in the dataframe that the dashboard uses.
"""

import os
import sys
sys.path.insert(0, os.path.dirname(__file__))

print("=" * 80)
print("VERIFY DASHBOARD FEES IN DATAFRAME")
print("=" * 80)

try:
    from src.pnl_dashboard import load_closed_positions_df
    import pandas as pd
    
    print("\nLoading closed positions dataframe...")
    df = load_closed_positions_df()
    
    print(f"\n✅ DataFrame loaded successfully")
    print(f"   Shape: {df.shape[0]} rows, {df.shape[1]} columns")
    print(f"   Columns: {list(df.columns)}")
    
    if "fees" in df.columns:
        print(f"\n✅ 'fees' column exists in dataframe")
        
        if not df.empty:
            # Check fee values
            non_zero_fees = df[df["fees"] > 0]
            print(f"   Trades with fees > 0: {len(non_zero_fees)}/{len(df)}")
            
            if len(non_zero_fees) > 0:
                print(f"\n   Fee statistics:")
                print(f"      Min: ${df['fees'].min():.2f}")
                print(f"      Max: ${df['fees'].max():.2f}")
                print(f"      Avg: ${df['fees'].mean():.2f}")
                print(f"      Total: ${df['fees'].sum():.2f}")
                
                print(f"\n   Sample fees (last 5 trades):")
                for idx, row in df.tail(5).iterrows():
                    symbol = row.get("symbol", "UNKNOWN")
                    fees = row.get("fees", 0)
                    trading_fees = row.get("trading_fees", 0)
                    funding_fees = row.get("funding_fees", 0)
                    print(f"      {symbol}: fees=${fees:.2f} (trading=${trading_fees:.2f}, funding=${funding_fees:.2f})")
                
                print(f"\n✅ Fees are in the dataframe and should display in dashboard!")
            else:
                print(f"\n⚠️  All fees are $0.00 - checking why...")
                print(f"   Sample row fee fields:")
                sample = df.iloc[0] if len(df) > 0 else None
                if sample is not None:
                    print(f"      trading_fees: {sample.get('trading_fees', 'N/A')}")
                    print(f"      funding_fees: {sample.get('funding_fees', 'N/A')}")
                    print(f"      fees: {sample.get('fees', 'N/A')}")
        else:
            print(f"\n⚠️  DataFrame is empty (no closed positions in last 7 days)")
    else:
        print(f"\n❌ 'fees' column NOT in dataframe!")
        print(f"   This means the fee extraction isn't working")
        print(f"   Available columns: {list(df.columns)}")
        
except Exception as e:
    print(f"\n❌ Error: {e}")
    import traceback
    traceback.print_exc()

print("\n" + "=" * 80)
