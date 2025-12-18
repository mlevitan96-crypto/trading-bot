#!/usr/bin/env python3
"""
Fix wallet balance and P&L issues:
1. Fix portfolio margin to $10,000
2. Sync portfolio realized_pnl with closed positions
3. Verify exchange configuration
"""

import sys
from pathlib import Path

_project_root = Path(__file__).parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

import os
import json
from src.data_registry import DataRegistry as DR
from src.futures_portfolio_tracker import load_futures_portfolio, save_futures_portfolio

def main():
    print("=" * 70)
    print("WALLET BALANCE & P&L FIX")
    print("=" * 70)
    print()
    
    # Check exchange config
    exchange = os.getenv("EXCHANGE", "blofin").lower()
    print(f"Current EXCHANGE env var: {exchange.upper()}")
    
    if exchange != "kraken":
        print()
        print("⚠️  WARNING: EXCHANGE is not set to 'kraken'")
        print("   The bot is using Blofin instead of Kraken!")
        print("   Fix: Set EXCHANGE=kraken in .env file")
        print()
    
    # Load closed positions
    closed = DR.get_closed_positions(hours=None)
    print(f"Found {len(closed)} closed positions")
    
    # Recalculate total P&L from closed positions
    total_pnl = 0.0
    for pos in closed:
        pnl = pos.get("pnl") or pos.get("net_pnl") or pos.get("realized_pnl") or 0.0
        try:
            total_pnl += float(pnl)
        except:
            pass
    
    print(f"Total P&L from closed positions: ${total_pnl:,.2f}")
    print()
    
    # Load portfolio
    portfolio = load_futures_portfolio()
    current_margin = portfolio.get("total_margin_allocated", 10000.0)
    current_realized = portfolio.get("realized_pnl", 0.0)
    
    print("Current Portfolio State:")
    print(f"   Total margin allocated: ${current_margin:,.2f}")
    print(f"   Realized P&L: ${current_realized:,.2f}")
    print()
    
    # Fixes
    fixes_applied = []
    
    # Fix 1: Reset margin to $10,000 if wrong
    if current_margin != 10000.0:
        print(f"FIX 1: Resetting margin from ${current_margin:,.2f} to $10,000.00")
        portfolio["total_margin_allocated"] = 10000.0
        fixes_applied.append("margin_reset")
    
    # Fix 2: Sync realized_pnl with closed positions
    if abs(current_realized - total_pnl) > 1.0:
        print(f"FIX 2: Syncing realized_pnl from ${current_realized:,.2f} to ${total_pnl:,.2f}")
        portfolio["realized_pnl"] = total_pnl
        fixes_applied.append("pnl_sync")
    else:
        print("   Realized P&L already matches closed positions (difference < $1)")
    
    # Fix 3: Recalculate available margin
    unrealized = portfolio.get("unrealized_pnl", 0.0)
    used = portfolio.get("used_margin", 0.0)
    total_equity = 10000.0 + portfolio.get("realized_pnl", 0.0) + unrealized
    available = total_equity - used
    
    portfolio["available_margin"] = max(0.0, available)
    
    print()
    print("Updated Portfolio State:")
    print(f"   Total margin allocated: ${portfolio['total_margin_allocated']:,.2f}")
    print(f"   Realized P&L: ${portfolio['realized_pnl']:,.2f}")
    print(f"   Unrealized P&L: ${unrealized:,.2f}")
    print(f"   Used margin: ${used:,.2f}")
    print(f"   Available margin: ${portfolio['available_margin']:,.2f}")
    print(f"   Total equity: ${portfolio['total_margin_allocated'] + portfolio['realized_pnl'] + unrealized:,.2f}")
    print()
    
    if fixes_applied:
        save_futures_portfolio(portfolio)
        print(f"✅ Applied fixes: {', '.join(fixes_applied)}")
        print()
        print("New wallet balance calculation:")
        print(f"   Starting capital: $10,000.00")
        print(f"   + Realized P&L: ${portfolio['realized_pnl']:,.2f}")
        print(f"   + Unrealized P&L: ${unrealized:,.2f}")
        print(f"   = Total Equity: ${portfolio['total_margin_allocated'] + portfolio['realized_pnl'] + unrealized:,.2f}")
    else:
        print("✅ No fixes needed - portfolio already correct")
    
    print()
    print("=" * 70)

if __name__ == "__main__":
    main()
