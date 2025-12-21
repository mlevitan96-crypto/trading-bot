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

# Check what load_closed_positions_df() returns (simplified - no pandas import)
print("\n2. CHECKING FEE EXTRACTION LOGIC")
print("-" * 80)
print("   Testing fee extraction on sample data...")

# Simulate the fee extraction logic
sample_pos = {
    "trading_fees": 0.2,
    "funding_fees": 0.0,
    "fees_usd": None,
    "fees": None
}

fees_usd = sample_pos.get("fees_usd", 0)
trading_fees = sample_pos.get("trading_fees", 0)
funding_fees = sample_pos.get("funding_fees", 0)
legacy_fees = sample_pos.get("fees", 0)

if fees_usd and fees_usd != 0:
    fees = float(fees_usd)
    source = "fees_usd"
elif (trading_fees and trading_fees != 0) or (funding_fees and funding_fees != 0):
    fees = float(trading_fees or 0) + float(funding_fees or 0)
    source = "trading_fees + funding_fees"
else:
    fees = float(legacy_fees or 0.0)
    source = "legacy fees"

print(f"   Sample calculation:")
print(f"      trading_fees: ${trading_fees}")
print(f"      funding_fees: ${funding_fees}")
print(f"      fees_usd: {fees_usd}")
print(f"      → Total fees: ${fees:.2f} (from {source})")
print(f"\n   ✅ Fee extraction logic should work correctly")
print(f"   ✅ Data has trading_fees, so fees should be calculated")

print("\n" + "=" * 80)
