#!/usr/bin/env python3
"""
Find and fix trades with incorrect exit prices (like $4.76 for BTC).
This fixes the artificial losses from bad exit price data.
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
    pass

import json
import shutil
from datetime import datetime
from src.data_registry import DataRegistry as DR
from src.position_manager import load_futures_positions, save_futures_positions
from src.futures_portfolio_tracker import load_futures_portfolio, save_futures_portfolio

def find_suspicious_trades(closed_positions):
    """Find trades with suspicious exit prices (like $4.76)."""
    suspicious = []
    
    # Common suspicious exit prices (testnet artifacts)
    SUSPICIOUS_PRICES = [4.76, 4.765, 4.77]  # These are clearly wrong
    
    for i, pos in enumerate(closed_positions):
        symbol = pos.get("symbol", "")
        entry_price = pos.get("entry_price", 0)
        exit_price = pos.get("exit_price", 0)
        pnl = pos.get("pnl") or pos.get("net_pnl") or pos.get("realized_pnl") or 0
        
        try:
            entry_price = float(entry_price)
            exit_price = float(exit_price)
            pnl = float(pnl)
        except:
            continue
        
        # Check for suspicious exit prices
        if exit_price in SUSPICIOUS_PRICES:
            suspicious.append({
                "index": i,
                "symbol": symbol,
                "strategy": pos.get("strategy", ""),
                "entry_price": entry_price,
                "exit_price": exit_price,
                "pnl": pnl,
                "closed_at": pos.get("closed_at", ""),
                "direction": pos.get("direction", ""),
                "margin": pos.get("margin_collateral", 0),
                "leverage": pos.get("leverage", 1)
            })
        # Also check for exit prices that are way too low compared to entry
        elif entry_price > 100 and exit_price < 100:
            # Entry > $100 but exit < $100 is suspicious for major coins
            if symbol in ["BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "AVAXUSDT"]:
                suspicious.append({
                    "index": i,
                    "symbol": symbol,
                    "strategy": pos.get("strategy", ""),
                    "entry_price": entry_price,
                    "exit_price": exit_price,
                    "pnl": pnl,
                    "closed_at": pos.get("closed_at", ""),
                    "direction": pos.get("direction", ""),
                    "margin": pos.get("margin_collateral", 0),
                    "leverage": pos.get("leverage", 1),
                    "reason": "Exit price suspiciously low compared to entry"
                })
    
    return suspicious

def main():
    print("=" * 70)
    print("FIX BAD EXIT PRICES")
    print("=" * 70)
    print()
    
    # Load positions
    print("Loading closed positions...")
    positions_data = load_futures_positions()
    closed_positions = positions_data.get("closed_positions", [])
    print(f"   Found {len(closed_positions)} closed positions")
    print()
    
    # Find suspicious trades
    print("Scanning for suspicious exit prices...")
    suspicious = find_suspicious_trades(closed_positions)
    
    if not suspicious:
        print("   ✅ No suspicious trades found!")
        return
    
    print(f"   ⚠️  Found {len(suspicious)} suspicious trades:")
    print()
    
    total_bad_pnl = 0.0
    for trade in suspicious:
        print(f"   [{trade['index']}] {trade['symbol']} ({trade['strategy']})")
        print(f"       Entry: ${trade['entry_price']:,.2f} → Exit: ${trade['exit_price']:,.2f}")
        print(f"       P&L: ${trade['pnl']:,.2f}")
        print(f"       Closed at: {trade['closed_at']}")
        if trade.get('reason'):
            print(f"       Reason: {trade['reason']}")
        print()
        total_bad_pnl += trade['pnl']
    
    print(f"   Total P&L from suspicious trades: ${total_bad_pnl:,.2f}")
    print()
    
    # Show impact
    print("Current Portfolio State:")
    portfolio = load_futures_portfolio()
    current_realized = portfolio.get("realized_pnl", 0)
    current_wallet = 10000.0 + current_realized
    
    print(f"   Realized P&L: ${current_realized:,.2f}")
    print(f"   Wallet balance: ${current_wallet:,.2f}")
    print()
    
    print("If we remove these suspicious trades:")
    new_realized = current_realized - total_bad_pnl
    new_wallet = 10000.0 + new_realized
    print(f"   New realized P&L: ${new_realized:,.2f}")
    print(f"   New wallet balance: ${new_wallet:,.2f}")
    print(f"   Improvement: ${abs(new_wallet - current_wallet):,.2f}")
    print()
    
    # Confirm removal
    print("=" * 70)
    response = input("Remove these suspicious trades? (yes/no): ")
    
    if response.lower() not in ["yes", "y"]:
        print("Cancelled.")
        return
    
    print()
    print("Creating backup...")
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_dir = Path("backups") / f"bad_exit_prices_{timestamp}"
    backup_dir.mkdir(parents=True, exist_ok=True)
    
    positions_file = Path("logs/positions_futures.json")
    portfolio_file = Path("logs/portfolio_futures.json")
    
    if positions_file.exists():
        shutil.copy2(positions_file, backup_dir / "positions_futures.json")
    if portfolio_file.exists():
        shutil.copy2(portfolio_file, backup_dir / "portfolio_futures.json")
    
    print(f"   ✅ Backup created: {backup_dir}")
    print()
    
    # Save suspicious trades to archive (don't lose data)
    archive_file = backup_dir / "suspicious_trades_archive.json"
    with open(archive_file, 'w') as f:
        json.dump(suspicious, f, indent=2)
    print(f"   ✅ Suspicious trades archived to: {archive_file}")
    print()
    
    # Remove suspicious trades (by index, in reverse order to maintain indices)
    print("Removing suspicious trades from closed positions...")
    removed_indices = sorted([t["index"] for t in suspicious], reverse=True)
    for idx in removed_indices:
        if idx < len(closed_positions):
            removed = closed_positions.pop(idx)
            print(f"   Removed: {removed.get('symbol')} (Entry: ${removed.get('entry_price', 0):,.2f} → Exit: ${removed.get('exit_price', 0):,.2f})")
    
    # Update positions file
    positions_data["closed_positions"] = closed_positions
    save_futures_positions(positions_data)
    print(f"   ✅ Updated positions file ({len(closed_positions)} closed positions remaining)")
    print()
    
    # Recalculate portfolio P&L
    print("Recalculating portfolio P&L...")
    total_pnl = sum(float(p.get("pnl") or p.get("net_pnl") or p.get("realized_pnl") or 0) for p in closed_positions)
    
    portfolio["realized_pnl"] = total_pnl
    save_futures_portfolio(portfolio)
    
    print(f"   ✅ Portfolio realized_pnl updated: ${total_pnl:,.2f}")
    print()
    
    print("=" * 70)
    print("FIX COMPLETE")
    print("=" * 70)
    print()
    print("Summary:")
    print(f"   Removed {len(suspicious)} suspicious trades")
    print(f"   Remaining closed positions: {len(closed_positions)}")
    print(f"   New realized P&L: ${total_pnl:,.2f}")
    print(f"   New wallet balance: ${10000.0 + total_pnl:,.2f}")
    print()
    print("Next steps:")
    print("  1. Restart bot: sudo systemctl restart tradingbot")
    print("  2. Refresh dashboard")
    print("  3. Verify wallet balance is correct")
    print()
    print(f"⚠️  Original data backed up to: {backup_dir}")
    print("   Suspicious trades archived (not deleted)")

if __name__ == "__main__":
    main()
