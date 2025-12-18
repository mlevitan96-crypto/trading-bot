#!/usr/bin/env python3
"""
Reset portfolio to $10,000 starting capital with zero P&L.
Archives existing trade history but starts fresh for Kraken trading.
"""

import sys
from pathlib import Path
import json
import shutil
from datetime import datetime

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
    pass

from src.position_manager import load_futures_positions, save_futures_positions
from src.futures_portfolio_tracker import load_futures_portfolio, save_futures_portfolio

def main():
    print("=" * 70)
    print("RESET PORTFOLIO - FRESH START FOR KRAKEN")
    print("=" * 70)
    print()
    print("This will:")
    print("  ✅ Reset wallet balance to $10,000")
    print("  ✅ Set realized P&L to $0.00")
    print("  ✅ Reset unrealized P&L to $0.00")
    print("  ✅ Archive existing trade history (not deleted)")
    print("  ✅ Reset portfolio to clean state")
    print()
    
    # Load current state
    print("Loading current portfolio state...")
    portfolio = load_futures_portfolio()
    positions_data = load_futures_positions()
    
    current_balance = portfolio.get("total_margin_allocated", 0)
    current_realized = portfolio.get("realized_pnl", 0)
    current_unrealized = portfolio.get("unrealized_pnl", 0)
    closed_count = len(positions_data.get("closed_positions", []))
    open_count = len(positions_data.get("open_positions", []))
    
    print(f"   Current margin: ${current_balance:,.2f}")
    print(f"   Realized P&L: ${current_realized:,.2f}")
    print(f"   Unrealized P&L: ${current_unrealized:,.2f}")
    print(f"   Wallet balance: ${current_balance + current_realized + current_unrealized:,.2f}")
    print(f"   Closed positions: {closed_count}")
    print(f"   Open positions: {open_count}")
    print()
    
    if open_count > 0:
        print("⚠️  WARNING: You have open positions!")
        print(f"   Open positions: {open_count}")
        for pos in positions_data.get("open_positions", []):
            symbol = pos.get("symbol", "")
            strategy = pos.get("strategy", "")
            direction = pos.get("direction", "")
            print(f"      - {symbol} {direction} ({strategy})")
        print()
        response = input("Continue anyway? Open positions will be cleared. (yes/no): ")
        if response.lower() not in ["yes", "y"]:
            print("Cancelled.")
            return
    
    print("=" * 70)
    response = input("Reset portfolio to $10,000 with zero P&L? (yes/no): ")
    
    if response.lower() not in ["yes", "y"]:
        print("Cancelled.")
        return
    
    print()
    print("Creating backup archive...")
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    archive_dir = Path("backups") / f"kraken_fresh_start_{timestamp}"
    archive_dir.mkdir(parents=True, exist_ok=True)
    
    # Archive current state
    positions_file = Path("logs/positions_futures.json")
    portfolio_file = Path("logs/portfolio_futures.json")
    
    if positions_file.exists():
        shutil.copy2(positions_file, archive_dir / "positions_futures.json")
    if portfolio_file.exists():
        shutil.copy2(portfolio_file, archive_dir / "portfolio_futures.json")
    
    # Create archive summary
    archive_summary = {
        "archive_timestamp": datetime.now().isoformat(),
        "reason": "Fresh start for Kraken migration",
        "previous_state": {
            "margin_allocated": current_balance,
            "realized_pnl": current_realized,
            "unrealized_pnl": current_unrealized,
            "wallet_balance": current_balance + current_realized + current_unrealized,
            "closed_positions_count": closed_count,
            "open_positions_count": open_count
        },
        "reset_state": {
            "starting_capital": 10000.0,
            "realized_pnl": 0.0,
            "unrealized_pnl": 0.0,
            "wallet_balance": 10000.0
        }
    }
    
    with open(archive_dir / "archive_summary.json", 'w') as f:
        json.dump(archive_summary, f, indent=2)
    
    print(f"   ✅ Archive created: {archive_dir}")
    print(f"   ✅ Archived {closed_count} closed positions")
    print(f"   ✅ Archived {open_count} open positions")
    print()
    
    # Reset portfolio
    print("Resetting portfolio...")
    portfolio["total_margin_allocated"] = 10000.0
    portfolio["available_margin"] = 10000.0
    portfolio["used_margin"] = 0.0
    portfolio["realized_pnl"] = 0.0
    portfolio["unrealized_pnl"] = 0.0
    portfolio["total_trading_fees"] = 0.0
    portfolio["total_funding_fees"] = 0.0
    portfolio["starting_capital"] = 10000.0
    portfolio["reset_timestamp"] = datetime.now().isoformat()
    portfolio["reset_reason"] = "Fresh start for Kraken migration"
    
    save_futures_portfolio(portfolio)
    print(f"   ✅ Portfolio reset: ${10000.0:,.2f} starting capital")
    print()
    
    # Reset positions (clear open, archive closed)
    print("Resetting positions...")
    positions_data["open_positions"] = []
    positions_data["closed_positions"] = []
    positions_data["reset_timestamp"] = datetime.now().isoformat()
    positions_data["reset_reason"] = "Fresh start for Kraken migration"
    
    save_futures_positions(positions_data)
    print(f"   ✅ Cleared open positions: {open_count} → 0")
    print(f"   ✅ Cleared closed positions: {closed_count} → 0")
    print()
    
    # Verify reset
    print("Verifying reset...")
    portfolio = load_futures_portfolio()
    positions_data = load_futures_positions()
    
    new_balance = portfolio.get("total_margin_allocated", 0)
    new_realized = portfolio.get("realized_pnl", 0)
    new_unrealized = portfolio.get("unrealized_pnl", 0)
    new_closed = len(positions_data.get("closed_positions", []))
    new_open = len(positions_data.get("open_positions", []))
    
    print(f"   Margin allocated: ${new_balance:,.2f}")
    print(f"   Realized P&L: ${new_realized:,.2f}")
    print(f"   Unrealized P&L: ${new_unrealized:,.2f}")
    print(f"   Wallet balance: ${new_balance + new_realized + new_unrealized:,.2f}")
    print(f"   Closed positions: {new_closed}")
    print(f"   Open positions: {new_open}")
    print()
    
    if new_balance == 10000.0 and new_realized == 0.0 and new_unrealized == 0.0:
        print("=" * 70)
        print("✅ RESET COMPLETE")
        print("=" * 70)
        print()
        print("Portfolio successfully reset to fresh start:")
        print(f"   Starting capital: $10,000.00")
        print(f"   Realized P&L: $0.00")
        print(f"   Unrealized P&L: $0.00")
        print(f"   Wallet balance: $10,000.00")
        print()
        print(f"⚠️  All previous trade history archived to:")
        print(f"   {archive_dir}")
        print()
        print("Next steps:")
        print("  1. Restart bot: sudo systemctl restart tradingbot")
        print("  2. Verify dashboard shows $10,000 balance")
        print("  3. Begin fresh trading on Kraken")
    else:
        print("⚠️  WARNING: Reset verification failed!")
        print("   Please check the portfolio files manually.")

if __name__ == "__main__":
    main()
