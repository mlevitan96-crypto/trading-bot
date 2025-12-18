#!/usr/bin/env python3
"""
Diagnose wallet balance and P&L calculation issues.

Checks:
1. Wallet balance calculation from closed positions
2. Portfolio realized P&L vs sum of closed positions
3. Fee calculation consistency
4. Potential double-counting issues
"""

import sys
from pathlib import Path

_project_root = Path(__file__).parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

import json
import os
from datetime import datetime
from typing import Dict, List, Any

def load_positions_file() -> Dict[str, Any]:
    """Load positions_futures.json"""
    pos_file = _project_root / "logs" / "positions_futures.json"
    if pos_file.exists():
        try:
            with open(pos_file, 'r') as f:
                return json.load(f)
        except Exception as e:
            print(f"❌ Error loading positions file: {e}")
            return {}
    return {}

def load_portfolio_file() -> Dict[str, Any]:
    """Load portfolio_futures.json"""
    portfolio_file = _project_root / "logs" / "portfolio_futures.json"
    if portfolio_file.exists():
        try:
            with open(portfolio_file, 'r') as f:
                return json.load(f)
        except Exception as e:
            print(f"❌ Error loading portfolio file: {e}")
            return {}
    return {}

def diagnose_wallet_balance():
    """Diagnose wallet balance calculation issues"""
    print("=" * 70)
    print("WALLET BALANCE & P&L DIAGNOSTIC")
    print("=" * 70)
    print()
    
    # 1. Check positions file
    positions_data = load_positions_file()
    closed_positions = positions_data.get("closed_positions", [])
    open_positions = positions_data.get("open_positions", [])
    
    print("Positions File:")
    print(f"   Open positions: {len(open_positions)}")
    print(f"   Closed positions: {len(closed_positions)}")
    print()
    
    # 2. Calculate wallet balance from closed positions (how dashboard does it)
    starting_capital = 10000.0
    total_pnl_from_closed = 0.0
    pnl_by_field = {"pnl": 0.0, "net_pnl": 0.0, "realized_pnl": 0.0}
    
    print("Calculating wallet balance from closed positions...")
    for i, pos in enumerate(closed_positions):
        pnl = pos.get("pnl") or pos.get("net_pnl") or pos.get("realized_pnl") or 0.0
        try:
            pnl = float(pnl)
            total_pnl_from_closed += pnl
            
            # Track which field was used
            if pos.get("pnl") is not None:
                pnl_by_field["pnl"] += pnl
            if pos.get("net_pnl") is not None:
                pnl_by_field["net_pnl"] += pnl
            if pos.get("realized_pnl") is not None:
                pnl_by_field["realized_pnl"] += pnl
                
        except (TypeError, ValueError):
            pass
    
    wallet_balance_from_closed = starting_capital + total_pnl_from_closed
    
    print(f"   Starting capital: ${starting_capital:,.2f}")
    print(f"   Total P&L from closed positions: ${total_pnl_from_closed:,.2f}")
    print(f"   Calculated wallet balance: ${wallet_balance_from_closed:,.2f}")
    print()
    
    # 3. Check portfolio file
    portfolio = load_portfolio_file()
    portfolio_realized_pnl = portfolio.get("realized_pnl", 0.0)
    portfolio_unrealized_pnl = portfolio.get("unrealized_pnl", 0.0)
    portfolio_available_margin = portfolio.get("available_margin", 0.0)
    portfolio_total_margin = portfolio.get("total_margin_allocated", 10000.0)
    
    print("Portfolio File (portfolio_futures.json):")
    print(f"   Total margin allocated: ${portfolio_total_margin:,.2f}")
    print(f"   Realized P&L: ${portfolio_realized_pnl:,.2f}")
    print(f"   Unrealized P&L: ${portfolio_unrealized_pnl:,.2f}")
    print(f"   Available margin: ${portfolio_available_margin:,.2f}")
    print(f"   Total equity (margin + realized + unrealized): ${portfolio_total_margin + portfolio_realized_pnl + portfolio_unrealized_pnl:,.2f}")
    print()
    
    # 4. Check for discrepancies
    discrepancy = abs(total_pnl_from_closed - portfolio_realized_pnl)
    print("DISCREPANCY CHECK:")
    print(f"   Closed positions P&L sum: ${total_pnl_from_closed:,.2f}")
    print(f"   Portfolio realized_pnl: ${portfolio_realized_pnl:,.2f}")
    print(f"   Difference: ${discrepancy:,.2f}")
    
    if discrepancy > 1.0:  # More than $1 difference
        print("   WARNING: Significant discrepancy detected!")
        print("      This indicates portfolio_futures.json and closed positions are out of sync")
    else:
        print("   OK: P&L values match (difference < $1)")
    print()
    
    # 5. Check recent trades (last 10)
    print("Recent Closed Positions (last 10):")
    recent_closed = closed_positions[-10:] if len(closed_positions) > 10 else closed_positions
    for i, pos in enumerate(recent_closed, 1):
        symbol = pos.get("symbol", "UNKNOWN")
        strategy = pos.get("strategy", "UNKNOWN")
        pnl = pos.get("pnl") or pos.get("net_pnl") or pos.get("realized_pnl", 0.0)
        entry_price = pos.get("entry_price", 0)
        exit_price = pos.get("exit_price", 0)
        margin = pos.get("margin_collateral", 0)
        leverage = pos.get("leverage", 1)
        
        print(f"   [{i}] {symbol} ({strategy})")
        print(f"       Entry: ${entry_price:.2f} → Exit: ${exit_price:.2f}")
        print(f"       Margin: ${margin:.2f}, Leverage: {leverage}x")
        print(f"       P&L: ${float(pnl):,.2f} (fields: pnl={pos.get('pnl')}, net_pnl={pos.get('net_pnl')}, realized_pnl={pos.get('realized_pnl')})")
        if pos.get("trading_fees"):
            print(f"       Fees: ${pos.get('trading_fees', 0):,.2f}")
        print()
    
    # 6. Check exchange configuration
    exchange = os.getenv("EXCHANGE", "blofin").lower()
    print("Current Configuration:")
    print(f"   EXCHANGE: {exchange.upper()}")
    
    if exchange == "kraken":
        from src.fee_calculator import get_exchange_fees
        fees = get_exchange_fees("kraken")
        print(f"   Kraken fees: Maker={fees['maker']*100:.4f}%, Taker={fees['taker']*100:.4f}%")
    else:
        from src.fee_calculator import get_exchange_fees
        fees = get_exchange_fees("blofin")
        print(f"   Blofin fees: Maker={fees['maker']*100:.4f}%, Taker={fees['taker']*100:.4f}%")
    print()
    
    # 7. Check for venue mixing (old Blofin trades vs new Kraken trades)
    if closed_positions:
        venue_info = {}
        for pos in closed_positions:
            venue = pos.get("venue", "unknown")
            if venue not in venue_info:
                venue_info[venue] = {"count": 0, "total_pnl": 0.0}
            venue_info[venue]["count"] += 1
            pnl = pos.get("pnl") or pos.get("net_pnl") or pos.get("realized_pnl") or 0.0
            try:
                venue_info[venue]["total_pnl"] += float(pnl)
            except:
                pass
        
        if len(venue_info) > 1:
            print("VENUE MIXING DETECTED:")
            for venue, info in venue_info.items():
                print(f"   {venue}: {info['count']} trades, Total P&L: ${info['total_pnl']:,.2f}")
            print("   This is normal if you recently switched exchanges")
        else:
            print(f"All closed positions from same venue: {list(venue_info.keys())[0]}")
    print()
    
    # 8. Summary and recommendations
    print("=" * 70)
    print("SUMMARY & RECOMMENDATIONS")
    print("=" * 70)
    print()
    
    expected_wallet = starting_capital + total_pnl_from_closed
    portfolio_equity = portfolio_total_margin + portfolio_realized_pnl + portfolio_unrealized_pnl
    
    print(f"Dashboard Wallet Balance: ${wallet_balance_from_closed:,.2f}")
    print(f"Portfolio Total Equity: ${portfolio_equity:,.2f}")
    print(f"Difference: ${abs(wallet_balance_from_closed - portfolio_equity):,.2f}")
    print()
    
    if abs(wallet_balance_from_closed - portfolio_equity) > 10.0:
        print("CRITICAL: Large discrepancy detected!")
        print()
        print("Possible causes:")
        print("1. Portfolio file has stale data from old exchange")
        print("2. Closed positions P&L calculated with wrong fee rates")
        print("3. Double-counting of trades")
        print()
        print("Recommended fixes:")
        print("1. Reset portfolio_futures.json realized_pnl to match closed positions sum")
        print("2. Verify all closed positions have correct P&L values")
        print("3. Check for duplicate trade recordings")
    else:
        print("Values are consistent (difference < $10)")

if __name__ == "__main__":
    diagnose_wallet_balance()
