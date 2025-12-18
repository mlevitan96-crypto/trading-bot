#!/usr/bin/env python3
"""
Restore the suspicious trades from backup and fix their exit prices
instead of removing them.
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

from src.data_registry import DataRegistry as DR
from src.position_manager import load_futures_positions, save_futures_positions
from src.futures_portfolio_tracker import load_futures_portfolio, save_futures_portfolio

def estimate_exit_from_pnl(pos):
    """Estimate correct exit price based on recorded P&L."""
    entry_price = float(pos.get("entry_price", 0))
    direction = pos.get("direction", "LONG").upper()
    margin = float(pos.get("margin_collateral", 0))
    leverage = float(pos.get("leverage", 1))
    recorded_pnl = float(pos.get("pnl") or pos.get("net_pnl") or 0)
    
    if entry_price == 0 or margin == 0:
        # Can't estimate - use entry price (breakeven)
        return entry_price
    
    # Reverse engineer: net_pnl = margin * (leveraged_price_roi - fees_roi - funding_roi)
    # Approximate: net_roi ≈ net_pnl / margin
    net_roi = recorded_pnl / margin
    
    # Approximate fees (small, ~0.1% for taker round trip)
    estimated_fees_roi = 0.001
    funding_roi = float(pos.get("funding_fees", 0)) / margin if margin > 0 else 0
    
    # leveraged_price_roi ≈ net_roi + fees + funding
    leveraged_roi = net_roi + estimated_fees_roi + funding_roi
    price_roi = leveraged_roi / leverage if leverage > 0 else 0
    
    # Calculate exit price
    if direction == "LONG":
        estimated_exit = entry_price * (1 + price_roi)
    else:  # SHORT
        estimated_exit = entry_price * (1 - price_roi)
    
    # Sanity check
    if estimated_exit < 0 or estimated_exit > entry_price * 5 or estimated_exit < entry_price * 0.2:
        # If estimate seems unreasonable, use entry (breakeven)
        return entry_price
    
    return estimated_exit

def main():
    print("=" * 70)
    print("RESTORE AND FIX BAD TRADES")
    print("=" * 70)
    print()
    
    # Find latest backup
    backup_dir = Path("backups")
    bad_exit_backups = sorted([d for d in backup_dir.iterdir() if d.is_dir() and d.name.startswith("bad_exit_prices_")], reverse=True)
    
    if not bad_exit_backups:
        print("❌ No backup found. Cannot restore.")
        return
    
    latest_backup = bad_exit_backups[0]
    archive_file = latest_backup / "suspicious_trades_archive.json"
    
    if not archive_file.exists():
        print(f"❌ Archive file not found: {archive_file}")
        return
    
    print(f"Found backup: {latest_backup.name}")
    print(f"Archive file: {archive_file}")
    print()
    
    # Load archived trades
    with open(archive_file, 'r') as f:
        suspicious_trades = json.load(f)
    
    print(f"Found {len(suspicious_trades)} trades to restore and fix:")
    print()
    
    # Load current positions
    positions_data = load_futures_positions()
    closed_positions = positions_data.get("closed_positions", [])
    
    # Estimate correct exit prices for each
    fixes = []
    for trade in suspicious_trades:
        pos_dict = trade  # The trade dict contains position data
        symbol = pos_dict.get("symbol", "")
        entry = pos_dict.get("entry_price", 0)
        bad_exit = pos_dict.get("exit_price", 0)
        pnl = pos_dict.get("pnl", 0)
        
        # Create position dict from trade data (restore original structure)
        pos = {
            "symbol": symbol,
            "strategy": pos_dict.get("strategy", ""),
            "direction": pos_dict.get("direction", "LONG"),
            "entry_price": entry,
            "exit_price": bad_exit,
            "margin_collateral": pos_dict.get("margin", 0),
            "leverage": pos_dict.get("leverage", 1),
            "pnl": pnl,
            "net_pnl": pnl,
            "closed_at": pos_dict.get("closed_at", ""),
            "opened_at": "",  # We don't have this in archive
            "funding_fees": 0
        }
        
        estimated_exit = estimate_exit_from_pnl(pos)
        
        fixes.append({
            "position": pos,
            "bad_exit": bad_exit,
            "estimated_exit": estimated_exit,
            "pnl": pnl
        })
        
        print(f"   {symbol}: Bad exit ${bad_exit:,.2f} → Estimated ${estimated_exit:,.2f}, P&L: ${pnl:,.2f}")
    
    print()
    print("=" * 70)
    response = input("Restore and fix these trades? (yes/no): ")
    
    if response.lower() not in ["yes", "y"]:
        print("Cancelled.")
        return
    
    print()
    print("Creating new backup before restoring...")
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    new_backup = Path("backups") / f"before_restore_{timestamp}"
    new_backup.mkdir(parents=True, exist_ok=True)
    
    positions_file = Path("logs/positions_futures.json")
    if positions_file.exists():
        shutil.copy2(positions_file, new_backup / "positions_futures.json")
    print(f"   ✅ Backed up current state to {new_backup}")
    print()
    
    # Restore and fix each trade
    print("Restoring and fixing trades...")
    for fix in fixes:
        pos = fix["position"]
        
        # Use estimated exit price
        pos["exit_price"] = fix["estimated_exit"]
        pos["exit_price_fixed"] = True
        pos["original_exit_price"] = fix["bad_exit"]
        pos["fix_timestamp"] = datetime.now().isoformat()
        pos["fix_method"] = "estimated_from_pnl"
        
        # Recalculate P&L with correct exit price
        direction = pos.get("direction", "LONG").upper()
        entry_price = float(pos.get("entry_price", 0))
        exit_price = float(pos["exit_price"])
        margin = float(pos.get("margin_collateral", 0))
        leverage = float(pos.get("leverage", 1))
        
        if direction == "LONG":
            price_roi = (exit_price - entry_price) / entry_price
        else:
            price_roi = (entry_price - exit_price) / entry_price
        
        leveraged_roi = price_roi * leverage
        
        # Recalculate fees
        from src.fee_calculator import calculate_trading_fee
        import os
        exchange = os.getenv("EXCHANGE", "blofin").lower()
        notional_size = margin * leverage
        trading_fees_usd = calculate_trading_fee(notional_size, "taker", exchange=exchange) * 2
        trading_fees_roi = trading_fees_usd / margin if margin > 0 else 0
        funding_fees = float(pos.get("funding_fees", 0))
        funding_fees_roi = funding_fees / margin if margin > 0 else 0
        
        net_roi = leveraged_roi - trading_fees_roi - funding_fees_roi
        net_pnl = margin * net_roi
        
        # Update P&L
        pos["pnl"] = net_pnl
        pos["net_pnl"] = net_pnl
        pos["price_roi"] = price_roi
        pos["leveraged_roi"] = leveraged_roi
        pos["final_roi"] = net_roi
        
        # Add to closed positions
        closed_positions.append(pos)
        print(f"   ✅ Restored {pos['symbol']}: Exit ${fix['bad_exit']:,.2f} → ${exit_price:,.2f}, P&L: ${net_pnl:,.2f}")
    
    # Save positions
    positions_data["closed_positions"] = closed_positions
    save_futures_positions(positions_data)
    print(f"   ✅ Updated positions file ({len(closed_positions)} closed positions)")
    print()
    
    # Recalculate portfolio
    print("Recalculating portfolio P&L...")
    total_pnl = sum(float(p.get("pnl") or p.get("net_pnl") or p.get("realized_pnl") or 0) for p in closed_positions)
    
    portfolio = load_futures_portfolio()
    portfolio["realized_pnl"] = total_pnl
    save_futures_portfolio(portfolio)
    
    print(f"   ✅ Portfolio realized_pnl: ${total_pnl:,.2f}")
    print(f"   ✅ Wallet balance: ${10000.0 + total_pnl:,.2f}")
    print()
    
    print("=" * 70)
    print("RESTORE COMPLETE")
    print("=" * 70)

if __name__ == "__main__":
    main()
