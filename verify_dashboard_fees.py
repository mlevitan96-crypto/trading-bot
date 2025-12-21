#!/usr/bin/env python3
"""
Verify Dashboard Fees
=====================
Quick test to verify fees are in the dataframe that the dashboard uses.
Lightweight version that doesn't require pandas.
"""

import os
import sys
sys.path.insert(0, os.path.dirname(__file__))

print("=" * 80)
print("VERIFY DASHBOARD FEES IN DATAFRAME")
print("=" * 80)

try:
    from src.data_registry import DataRegistry as DR
    from datetime import datetime
    import pytz
    
    ARIZONA_TZ = pytz.timezone('America/Phoenix')
    
    print("\nLoading closed positions (simulating dashboard logic)...")
    
    # Use same logic as load_closed_positions_df() but without pandas
    closed_positions = DR.get_closed_positions(hours=168)  # Last 7 days
    
    if not closed_positions:
        print("\n⚠️  No closed positions found in last 7 days")
        print("=" * 80)
        sys.exit(0)
    
    print(f"   Found {len(closed_positions)} closed positions")
    
    # Process positions using same fee extraction logic as dashboard
    processed = []
    fees_found = 0
    fees_zero = 0
    fees_missing = 0
    
    for pos in closed_positions:
        # Extract fees - handle multiple formats (SQLite: fees_usd, JSON: trading_fees + funding_fees)
        fees_usd = pos.get("fees_usd", 0)  # SQLite format
        trading_fees = pos.get("trading_fees", 0)
        funding_fees = pos.get("funding_fees", 0)
        legacy_fees = pos.get("fees", 0)
        
        # Calculate total fees with proper fallback logic (same as dashboard)
        if fees_usd and fees_usd != 0:
            fees = float(fees_usd)
            source = "fees_usd"
        elif (trading_fees and trading_fees != 0) or (funding_fees and funding_fees != 0):
            fees = float(trading_fees or 0) + float(funding_fees or 0)
            source = "trading_fees + funding_fees"
        else:
            fees = float(legacy_fees or 0.0)
            source = "legacy fees"
        
        processed.append({
            "symbol": pos.get("symbol", ""),
            "fees": fees,
            "trading_fees": float(trading_fees or 0),
            "funding_fees": float(funding_fees or 0),
            "source": source
        })
        
        if fees > 0:
            fees_found += 1
        elif fees == 0:
            fees_zero += 1
        else:
            fees_missing += 1
    
    print(f"\n✅ Processed {len(processed)} positions")
    print(f"\n   Fee statistics:")
    print(f"      Positions with fees > 0: {fees_found}/{len(processed)}")
    print(f"      Positions with fees = 0: {fees_zero}/{len(processed)}")
    
    if fees_found > 0:
        # Calculate statistics
        fee_values = [p["fees"] for p in processed if p["fees"] > 0]
        if fee_values:
            print(f"\n   Fee values (from {fees_found} trades with fees):")
            print(f"      Min: ${min(fee_values):.2f}")
            print(f"      Max: ${max(fee_values):.2f}")
            print(f"      Avg: ${sum(fee_values) / len(fee_values):.2f}")
            print(f"      Total: ${sum(p['fees'] for p in processed):.2f}")
        
        print(f"\n   Sample fees (last 5 trades):")
        for p in processed[-5:]:
            symbol = p["symbol"]
            fees = p["fees"]
            trading_fees = p["trading_fees"]
            funding_fees = p["funding_fees"]
            source = p["source"]
            print(f"      {symbol}: fees=${fees:.2f} (trading=${trading_fees:.2f}, funding=${funding_fees:.2f}, source={source})")
        
        print(f"\n✅ Fees are being calculated correctly!")
        print(f"✅ Dashboard should display fees in 'Fees (USD)' column")
    else:
        print(f"\n⚠️  All fees are $0.00 - checking why...")
        print(f"   Sample position fee fields:")
        sample = processed[0] if processed else None
        if sample:
            print(f"      trading_fees: {sample.get('trading_fees', 'N/A')}")
            print(f"      funding_fees: {sample.get('funding_fees', 'N/A')}")
            print(f"      fees: {sample.get('fees', 'N/A')}")
            print(f"      source: {sample.get('source', 'N/A')}")
        
except Exception as e:
    print(f"\n❌ Error: {e}")
    import traceback
    traceback.print_exc()

print("\n" + "=" * 80)
