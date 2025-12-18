#!/usr/bin/env python3
"""
Reset portfolio to fresh start - useful when switching exchanges or starting over.
This will:
1. Backup current data
2. Reset portfolio to $10,000 starting capital
3. Archive old closed positions (optional)
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

def main():
    print("=" * 70)
    print("PORTFOLIO RESET - FRESH START")
    print("=" * 70)
    print()
    print("⚠️  WARNING: This will reset your portfolio to $10,000 starting capital")
    print("   All historical P&L will be archived (not deleted)")
    print()
    
    # Confirm
    response = input("Type 'RESET' to confirm: ")
    if response != "RESET":
        print("Cancelled.")
        return
    
    print()
    print("Creating backups...")
    
    # Backup files
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_dir = Path("backups") / f"reset_{timestamp}"
    backup_dir.mkdir(parents=True, exist_ok=True)
    
    portfolio_file = Path("logs/portfolio_futures.json")
    positions_file = Path("logs/positions_futures.json")
    
    if portfolio_file.exists():
        shutil.copy2(portfolio_file, backup_dir / "portfolio_futures.json")
        print(f"   ✅ Backed up: {portfolio_file}")
    
    if positions_file.exists():
        shutil.copy2(positions_file, backup_dir / "positions_futures.json")
        print(f"   ✅ Backed up: {positions_file}")
    
    print()
    print("Resetting portfolio...")
    
    # Reset portfolio file
    try:
        from src.futures_portfolio_tracker import load_futures_portfolio, save_futures_portfolio
        
        portfolio = load_futures_portfolio()
        
        # Archive old values
        old_realized = portfolio.get("realized_pnl", 0)
        old_closed_count = len(portfolio.get("closed_positions", []))
        
        # Reset to starting capital
        portfolio["total_margin_allocated"] = 10000.0
        portfolio["available_margin"] = 10000.0
        portfolio["used_margin"] = 0.0
        portfolio["realized_pnl"] = 0.0
        portfolio["unrealized_pnl"] = 0.0
        portfolio["total_funding_fees"] = portfolio.get("total_funding_fees", 0.0)
        portfolio["total_trading_fees"] = portfolio.get("total_trading_fees", 0.0)
        
        # Add metadata about reset
        if "reset_history" not in portfolio:
            portfolio["reset_history"] = []
        portfolio["reset_history"].append({
            "timestamp": datetime.now().isoformat(),
            "old_realized_pnl": old_realized,
            "old_closed_positions_count": old_closed_count,
            "reason": "Fresh start - exchange switch or manual reset"
        })
        
        save_futures_portfolio(portfolio)
        print(f"   ✅ Portfolio reset to $10,000 starting capital")
        print(f"      Previous realized P&L: ${old_realized:,.2f} (archived)")
    except Exception as e:
        print(f"   ❌ Error resetting portfolio: {e}")
        import traceback
        traceback.print_exc()
        return
    
    print()
    print("Archiving old closed positions...")
    
    # Archive closed positions (don't delete, just move to archive)
    try:
        from src.position_manager import load_futures_positions, save_futures_positions
        from src.data_registry import DataRegistry as DR
        
        positions_data = load_futures_positions()
        closed_positions = positions_data.get("closed_positions", [])
        
        if closed_positions:
            # Save archive
            archive_file = backup_dir / "closed_positions_archive.json"
            with open(archive_file, 'w') as f:
                json.dump(closed_positions, f, indent=2)
            print(f"   ✅ Archived {len(closed_positions)} closed positions to {archive_file}")
            
            # Clear closed positions
            positions_data["closed_positions"] = []
            save_futures_positions(positions_data)
            print(f"   ✅ Cleared closed positions (kept in archive)")
        else:
            print("   ℹ️  No closed positions to archive")
    except Exception as e:
        print(f"   ❌ Error archiving positions: {e}")
        import traceback
        traceback.print_exc()
    
    print()
    print("=" * 70)
    print("RESET COMPLETE")
    print("=" * 70)
    print()
    print("New Portfolio State:")
    print(f"   Starting capital: $10,000.00")
    print(f"   Realized P&L: $0.00")
    print(f"   Unrealized P&L: $0.00")
    print(f"   Total equity: $10,000.00")
    print()
    print(f"Backups saved to: {backup_dir}")
    print()
    print("Next steps:")
    print("  1. Restart bot: sudo systemctl restart tradingbot")
    print("  2. Refresh dashboard")
    print("  3. Verify wallet balance shows $10,000.00")
    print()

if __name__ == "__main__":
    main()
