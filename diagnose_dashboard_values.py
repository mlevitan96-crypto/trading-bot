#!/usr/bin/env python3
"""
Diagnose what values the dashboard is actually showing vs what's in the data.
"""

import sys
from pathlib import Path

_project_root = Path(__file__).parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

# Load .env
try:
    from dotenv import load_dotenv
    _env_path = _project_root / ".env"
    if _env_path.exists():
        load_dotenv(_env_path)
    else:
        for fallback in ["/root/trading-bot-current/.env", "/root/trading-bot/.env"]:
            if Path(fallback).exists():
                load_dotenv(fallback)
                break
except ImportError:
    pass  # Optional

import os

def main():
    print("=" * 70)
    print("DASHBOARD VALUES DIAGNOSTIC")
    print("=" * 70)
    print()
    
    # 1. Check what get_wallet_balance() returns
    print("1. Wallet Balance Calculation:")
    try:
        from src.pnl_dashboard import get_wallet_balance
        wallet_balance = get_wallet_balance()
        print(f"   get_wallet_balance() returns: ${wallet_balance:,.2f}")
    except Exception as e:
        print(f"   ❌ Error: {e}")
        import traceback
        traceback.print_exc()
    print()
    
    # 2. Check portfolio file
    print("2. Portfolio File (portfolio_futures.json):")
    try:
        from src.futures_portfolio_tracker import load_futures_portfolio
        portfolio = load_futures_portfolio()
        margin = portfolio.get("total_margin_allocated", 0)
        realized = portfolio.get("realized_pnl", 0)
        unrealized = portfolio.get("unrealized_pnl", 0)
        total_equity = margin + realized + unrealized
        
        print(f"   Total margin allocated: ${margin:,.2f}")
        print(f"   Realized P&L: ${realized:,.2f}")
        print(f"   Unrealized P&L: ${unrealized:,.2f}")
        print(f"   Total equity: ${total_equity:,.2f}")
        print(f"   Expected wallet balance: ${10000.0 + realized:,.2f}")
    except Exception as e:
        print(f"   ❌ Error: {e}")
    print()
    
    # 3. Check closed positions sum
    print("3. Closed Positions P&L Sum:")
    try:
        from src.data_registry import DataRegistry as DR
        closed = DR.get_closed_positions(hours=None)
        total_pnl = sum(float(p.get("pnl") or p.get("net_pnl") or p.get("realized_pnl") or 0) for p in closed)
        print(f"   Total closed positions: {len(closed)}")
        print(f"   Sum of all P&L: ${total_pnl:,.2f}")
        print(f"   Expected wallet balance: ${10000.0 + total_pnl:,.2f}")
    except Exception as e:
        print(f"   ❌ Error: {e}")
    print()
    
    # 4. Check compute_summary (what dashboard actually shows)
    print("4. Dashboard Summary Calculation:")
    try:
        from src.pnl_dashboard import compute_summary, load_closed_positions_df
        from src.pnl_dashboard_loader import load_trades_df
        
        # Load data (limited for performance)
        df = load_trades_df()
        wallet = get_wallet_balance()
        
        # Compute summary for different timeframes
        summary_24h = compute_summary(df, lookback_days=1, wallet_balance=wallet)
        print(f"   24-hour summary:")
        print(f"      Wallet balance: ${summary_24h.get('wallet_balance', 0):,.2f}")
        print(f"      Net P&L: ${summary_24h.get('net_pnl', 0):,.2f}")
        print(f"      Total trades: {summary_24h.get('total_trades', 0)}")
    except Exception as e:
        print(f"   ❌ Error: {e}")
        import traceback
        traceback.print_exc()
    print()
    
    # 5. Check if user wants to reset
    print("=" * 70)
    print("CURRENT VALUES")
    print("=" * 70)
    print(f"Starting capital: $10,000.00")
    print(f"Realized P&L (from all closed trades): ${realized:,.2f}")
    print(f"Current wallet balance: ${wallet_balance:,.2f}")
    print()
    print("QUESTION:")
    print("Do you want to:")
    print("  A) Keep current values (they are mathematically correct)")
    print("  B) Reset to $10,000 (start fresh, clearing all historical trades)")
    print()
    print("If you want to reset, I can create a script to:")
    print("  1. Backup current data")
    print("  2. Reset portfolio_futures.json to $10,000 starting capital")
    print("  3. Clear or archive old closed positions")
    print()

if __name__ == "__main__":
    main()
