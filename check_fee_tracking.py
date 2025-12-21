#!/usr/bin/env python3
"""
Check Fee Tracking in Trades
=============================
Verifies that trading fees and funding fees are being recorded in trades.
"""

import os
import sys
import json
from pathlib import Path
from datetime import datetime

sys.path.insert(0, os.path.dirname(__file__))

print("=" * 80)
print("FEE TRACKING VERIFICATION")
print("=" * 80)
print(f"Time: {datetime.now().isoformat()}\n")

# Load trades
trades_file = Path("logs/positions_futures.json")
if not trades_file.exists():
    print("[ERROR] Trades file does not exist")
    sys.exit(1)

with open(trades_file, 'r') as f:
    data = json.load(f)
    closed = data.get("closed_positions", [])

if not closed:
    print("[ERROR] No closed trades found")
    sys.exit(1)

print(f"Total closed trades: {len(closed)}\n")

# Check recent trades
recent = closed[-50:]  # Last 50 trades

print("CHECKING FEE FIELDS IN RECENT 50 TRADES")
print("-" * 80)

# Check for fee fields
has_trading_fees = 0
has_funding_fees = 0
has_both_fees = 0
missing_both = 0

trading_fees_values = []
funding_fees_values = []

for trade in recent:
    trading_fee = trade.get("trading_fees")
    funding_fee = trade.get("funding_fees")
    
    if trading_fee is not None and trading_fee != 0:
        has_trading_fees += 1
        trading_fees_values.append(float(trading_fee))
    
    if funding_fee is not None and funding_fee != 0:
        has_funding_fees += 1
        funding_fees_values.append(float(funding_fee))
    
    if (trading_fee is not None and trading_fee != 0) and (funding_fee is not None):
        has_both_fees += 1
    elif trading_fee is None and funding_fee is None:
        missing_both += 1

print(f"Trades with trading_fees field: {has_trading_fees}/{len(recent)}")
print(f"Trades with funding_fees field: {has_funding_fees}/{len(recent)}")
print(f"Trades with both fees: {has_both_fees}/{len(recent)}")
print(f"Trades missing both: {missing_both}/{len(recent)}")

if trading_fees_values:
    print(f"\nTrading fees (non-zero):")
    print(f"   Count: {len(trading_fees_values)}")
    print(f"   Min: ${min(trading_fees_values):.4f}")
    print(f"   Max: ${max(trading_fees_values):.4f}")
    print(f"   Avg: ${sum(trading_fees_values)/len(trading_fees_values):.4f}")
    print(f"   Total: ${sum(trading_fees_values):.2f}")
else:
    print(f"\n[WARNING] No trading fees found in recent trades")

if funding_fees_values:
    print(f"\nFunding fees (non-zero):")
    print(f"   Count: {len(funding_fees_values)}")
    print(f"   Min: ${min(funding_fees_values):.4f}")
    print(f"   Max: ${max(funding_fees_values):.4f}")
    print(f"   Avg: ${sum(funding_fees_values)/len(funding_fees_values):.4f}")
    print(f"   Total: ${sum(funding_fees_values):.2f}")
else:
    print(f"\n[INFO] No funding fees found (may be normal if positions closed quickly)")

# Check portfolio totals
portfolio = data.get("portfolio", {})
if portfolio:
    total_trading_fees = portfolio.get("total_trading_fees", 0)
    total_funding_fees = portfolio.get("total_funding_fees", 0)
    
    print(f"\nPortfolio Fee Totals:")
    print(f"   Total Trading Fees: ${total_trading_fees:.2f}")
    print(f"   Total Funding Fees: ${total_funding_fees:.2f}")
    print(f"   Combined: ${total_trading_fees + total_funding_fees:.2f}")

# Show sample trades
print(f"\nSAMPLE RECENT TRADES (Last 5):")
print("-" * 80)

for i, trade in enumerate(recent[-5:], 1):
    symbol = trade.get("symbol", "UNKNOWN")
    trading_fee = trade.get("trading_fees", "MISSING")
    funding_fee = trade.get("funding_fees", "MISSING")
    net_pnl = trade.get("net_pnl", trade.get("pnl", 0))
    gross_pnl = trade.get("gross_pnl", 0)
    
    print(f"\n{i}. {symbol}:")
    print(f"   Trading Fees: {trading_fee}")
    print(f"   Funding Fees: {funding_fee}")
    print(f"   Gross P&L: ${gross_pnl:.2f}")
    print(f"   Net P&L: ${net_pnl:.2f}")
    
    # Check if fees are in net_pnl calculation
    if gross_pnl and net_pnl:
        implied_fees = gross_pnl - net_pnl
        print(f"   Implied Fees (gross - net): ${implied_fees:.2f}")
        if trading_fee != "MISSING" and isinstance(trading_fee, (int, float)):
            expected_total = trading_fee + (funding_fee if isinstance(funding_fee, (int, float)) else 0)
            if abs(implied_fees - expected_total) > 0.01:
                print(f"   [WARNING] Fee mismatch! Expected ${expected_total:.2f}, got ${implied_fees:.2f}")

# Summary
print("\n" + "=" * 80)
print("SUMMARY")
print("=" * 80)

if has_trading_fees == len(recent):
    print("✅ Trading fees are being tracked in all recent trades")
elif has_trading_fees > 0:
    print(f"⚠️  Trading fees tracked in {has_trading_fees}/{len(recent)} trades ({has_trading_fees/len(recent)*100:.1f}%)")
else:
    print("❌ Trading fees NOT being tracked in recent trades")

if missing_both > 0:
    print(f"❌ {missing_both} trades are missing both fee fields")
    print("   [ACTION] Check if fee calculation is working in trade recording")

print("\n" + "=" * 80)
