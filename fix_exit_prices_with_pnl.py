#!/usr/bin/env python3
"""
Fix trades with bad exit prices by using the recorded P&L to estimate correct exit price.
If we can't fix them, we'll estimate based on reasonable exit price near entry.
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

def estimate_correct_exit_price(pos, recorded_pnl):
    """
    Estimate correct exit price based on recorded P&L.
    If P&L is positive and exit price is wrong, estimate a reasonable exit.
    """
    entry_price = float(pos.get("entry_price", 0))
    exit_price = float(pos.get("exit_price", 0))
    direction = pos.get("direction", "LONG").upper()
    margin = float(pos.get("margin_collateral", 0))
    leverage = float(pos.get("leverage", 1))
    recorded_pnl = float(recorded_pnl)
    
    if entry_price == 0 or margin == 0:
        return None
    
    # Calculate what ROI would give us the recorded P&L
    # net_pnl = margin * net_roi
    # net_roi = net_pnl / margin
    net_roi = recorded_pnl / margin if margin > 0 else 0
    
    # Reverse engineer price ROI from net ROI
    # net_roi = leveraged_price_roi - fees_roi - funding_roi
    # We'll approximate by assuming fees are small
    # leveraged_price_roi ≈ net_roi (rough approximation)
    # price_roi ≈ net_roi / leverage
    
    price_roi = net_roi / leverage if leverage > 0 else 0
    
    # Now reverse calculate exit price from price ROI
    if direction == "LONG":
        # price_roi = (exit - entry) / entry
        # exit = entry * (1 + price_roi)
        estimated_exit = entry_price * (1 + price_roi)
    else:  # SHORT
        # price_roi = (entry - exit) / entry
        # exit = entry * (1 - price_roi)
        estimated_exit = entry_price * (1 - price_roi)
    
    # Sanity check: exit price should be reasonable
    if estimated_exit < 0 or estimated_exit > entry_price * 10:
        # If calculation seems wrong, use entry price (breakeven assumption)
        estimated_exit = entry_price
    
    return estimated_exit

def main():
    print("=" * 70)
    print("FIX EXIT PRICES USING RECORDED P&L")
    print("=" * 70)
    print()
    
    # Load positions
    print("Loading closed positions...")
    positions_data = load_futures_positions()
    closed_positions = positions_data.get("closed_positions", [])
    print(f"   Found {len(closed_positions)} closed positions")
    print()
    
    # Find trades with suspicious exit prices
    SUSPICIOUS_PRICES = [4.76, 4.765, 4.77]
    suspicious = []
    
    for i, pos in enumerate(closed_positions):
        entry_price = float(pos.get("entry_price", 0))
        exit_price = float(pos.get("exit_price", 0))
        pnl = pos.get("pnl") or pos.get("net_pnl") or pos.get("realized_pnl") or 0
        
        try:
            entry_price = float(entry_price)
            exit_price = float(exit_price)
            pnl = float(pnl)
        except:
            continue
        
        if exit_price in SUSPICIOUS_PRICES or (entry_price > 100 and exit_price < 100):
            estimated_exit = estimate_correct_exit_price(pos, pnl)
            suspicious.append({
                "index": i,
                "position": pos,
                "estimated_exit": estimated_exit
            })
    
    if not suspicious:
        print("   ✅ No suspicious trades found!")
        return
    
    print(f"   ⚠️  Found {len(suspicious)} trades with bad exit prices:")
    print()
    
    for trade in suspicious:
        pos = trade["position"]
        symbol = pos.get("symbol", "")
        entry = float(pos.get("entry_price", 0))
        exit = float(pos.get("exit_price", 0))
        pnl = float(pos.get("pnl") or pos.get("net_pnl") or 0)
        est_exit = trade["estimated_exit"]
        direction = pos.get("direction", "LONG")
        
        print(f"   [{trade['index']}] {symbol} {direction}")
        print(f"       Entry: ${entry:,.2f}")
        print(f"       Current exit: ${exit:,.2f} (WRONG)")
        print(f"       Recorded P&L: ${pnl:,.2f}")
        print(f"       Estimated exit: ${est_exit:,.2f}")
        print()
    
    print("=" * 70)
    print("OPTIONS:")
    print("=" * 70)
    print()
    print("1. Fix exit prices to estimated values (keep trades, fix prices)")
    print("2. Remove these trades (lose the P&L contribution)")
    print("3. Set exit price = entry price (breakeven assumption)")
    print()
    
    choice = input("Choose option (1/2/3): ").strip()
    
    if choice == "1":
        action = "fix"
        new_exit_method = "estimated"
    elif choice == "2":
        action = "remove"
        new_exit_method = None
    elif choice == "3":
        action = "fix"
        new_exit_method = "entry"
    else:
        print("Invalid choice. Cancelled.")
        return
    
    print()
    print("Creating backup...")
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_dir = Path("backups") / f"fix_exit_prices_{timestamp}"
    backup_dir.mkdir(parents=True, exist_ok=True)
    
    positions_file = Path("logs/positions_futures.json")
    portfolio_file = Path("logs/portfolio_futures.json")
    
    if positions_file.exists():
        shutil.copy2(positions_file, backup_dir / "positions_futures.json")
    if portfolio_file.exists():
        shutil.copy2(portfolio_file, backup_dir / "portfolio_futures.json")
    
    print(f"   ✅ Backup created: {backup_dir}")
    print()
    
    if action == "fix":
        print("Fixing exit prices...")
        fixed_count = 0
        
        for trade in suspicious:
            idx = trade["index"]
            pos = closed_positions[idx]
            
            if new_exit_method == "estimated":
                new_exit = trade["estimated_exit"]
            else:  # entry
                new_exit = float(pos.get("entry_price", 0))
            
            old_exit = pos.get("exit_price")
            pos["exit_price"] = new_exit
            pos["exit_price_fixed"] = True
            pos["original_exit_price"] = old_exit
            pos["fix_timestamp"] = datetime.now().isoformat()
            
            # Recalculate P&L with correct exit price
            direction = pos.get("direction", "LONG").upper()
            entry_price = float(pos.get("entry_price", 0))
            margin = float(pos.get("margin_collateral", 0))
            leverage = float(pos.get("leverage", 1))
            
            if direction == "LONG":
                price_roi = (new_exit - entry_price) / entry_price
            else:
                price_roi = (entry_price - new_exit) / entry_price
            
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
            
            # Update P&L fields
            pos["pnl"] = net_pnl
            pos["net_pnl"] = net_pnl
            pos["price_roi"] = price_roi
            pos["leveraged_roi"] = leveraged_roi
            pos["final_roi"] = net_roi
            
            print(f"   Fixed [{idx}] {pos.get('symbol')}: ${old_exit:.2f} → ${new_exit:,.2f}, P&L: ${pos.get('pnl', 0):,.2f}")
            fixed_count += 1
        
        print(f"   ✅ Fixed {fixed_count} trades")
        print()
        
        # Save positions
        positions_data["closed_positions"] = closed_positions
        save_futures_positions(positions_data)
        
    elif action == "remove":
        print("Removing suspicious trades...")
        removed_indices = sorted([t["index"] for t in suspicious], reverse=True)
        for idx in removed_indices:
            if idx < len(closed_positions):
                removed = closed_positions.pop(idx)
                print(f"   Removed: {removed.get('symbol')}")
        
        positions_data["closed_positions"] = closed_positions
        save_futures_positions(positions_data)
        print(f"   ✅ Removed {len(removed_indices)} trades")
        print()
    
    # Recalculate portfolio P&L
    print("Recalculating portfolio P&L...")
    total_pnl = sum(float(p.get("pnl") or p.get("net_pnl") or p.get("realized_pnl") or 0) for p in closed_positions)
    
    portfolio = load_futures_portfolio()
    portfolio["realized_pnl"] = total_pnl
    save_futures_portfolio(portfolio)
    
    print(f"   ✅ Portfolio realized_pnl updated: ${total_pnl:,.2f}")
    print()
    
    print("=" * 70)
    print("FIX COMPLETE")
    print("=" * 70)
    print()
    print("Summary:")
    if action == "fix":
        print(f"   Fixed {len(suspicious)} trades with corrected exit prices")
    else:
        print(f"   Removed {len(suspicious)} trades")
    print(f"   Remaining closed positions: {len(closed_positions)}")
    print(f"   New realized P&L: ${total_pnl:,.2f}")
    print(f"   New wallet balance: ${10000.0 + total_pnl:,.2f}")
    print()
    print(f"⚠️  Original data backed up to: {backup_dir}")

if __name__ == "__main__":
    main()
