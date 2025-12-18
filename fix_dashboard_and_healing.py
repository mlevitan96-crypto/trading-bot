#!/usr/bin/env python3
"""
Fix dashboard cache and diagnose self-healing yellow status.
"""

import sys
from pathlib import Path

_project_root = Path(__file__).parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

# Load .env
from dotenv import load_dotenv
_env_path = _project_root / ".env"
if _env_path.exists():
    load_dotenv(_env_path)
else:
    for fallback in ["/root/trading-bot-current/.env", "/root/trading-bot/.env"]:
        if Path(fallback).exists():
            load_dotenv(fallback)
            break

import os
from src.pnl_dashboard_loader import clear_cache
from src.healing_operator import HealingOperator

def main():
    print("=" * 70)
    print("DASHBOARD CACHE & SELF-HEALING DIAGNOSTIC")
    print("=" * 70)
    print()
    
    # 1. Clear dashboard cache
    print("1. Clearing dashboard cache...")
    try:
        clear_cache()
        print("   ✅ Dashboard cache cleared")
    except Exception as e:
        print(f"   ⚠️  Error clearing cache: {e}")
    print()
    
    # 2. Check wallet balance calculation
    print("2. Checking wallet balance calculation...")
    try:
        from src.pnl_dashboard import get_wallet_balance
        wallet = get_wallet_balance()
        print(f"   Wallet balance: ${wallet:,.2f}")
        
        from src.data_registry import DataRegistry as DR
        closed = DR.get_closed_positions(hours=None)
        total_pnl = sum(float(p.get("pnl") or p.get("net_pnl") or p.get("realized_pnl") or 0) for p in closed)
        print(f"   Starting capital: $10,000.00")
        print(f"   Total P&L from {len(closed)} closed positions: ${total_pnl:,.2f}")
        print(f"   Calculated balance: ${10000.0 + total_pnl:,.2f}")
        
        if abs(wallet - (10000.0 + total_pnl)) < 1.0:
            print("   ✅ Wallet balance calculation is correct")
        else:
            print(f"   ⚠️  Wallet balance mismatch: ${abs(wallet - (10000.0 + total_pnl)):,.2f}")
    except Exception as e:
        print(f"   ❌ Error checking wallet balance: {e}")
        import traceback
        traceback.print_exc()
    print()
    
    # 3. Check portfolio file
    print("3. Checking portfolio file...")
    try:
        from src.futures_portfolio_tracker import load_futures_portfolio
        portfolio = load_futures_portfolio()
        margin = portfolio.get("total_margin_allocated", 0)
        realized = portfolio.get("realized_pnl", 0)
        unrealized = portfolio.get("unrealized_pnl", 0)
        total_equity = margin + realized + unrealized
        
        print(f"   Total margin: ${margin:,.2f}")
        print(f"   Realized P&L: ${realized:,.2f}")
        print(f"   Unrealized P&L: ${unrealized:,.2f}")
        print(f"   Total equity: ${total_equity:,.2f}")
        
        if margin != 10000.0:
            print(f"   ⚠️  Margin is ${margin:,.2f}, should be $10,000.00")
        else:
            print("   ✅ Margin is correct")
    except Exception as e:
        print(f"   ❌ Error checking portfolio: {e}")
    print()
    
    # 4. Check self-healing status
    print("4. Checking self-healing status...")
    try:
        healing_op = HealingOperator()
        status = healing_op.get_status()
        
        print(f"   Self-healing status: {status.get('self_healing', 'unknown')}")
        print(f"   Last cycle: {status.get('last_cycle_ts', 'unknown')}")
        print(f"   Thread running: {status.get('thread_running', 'unknown')}")
        
        if status.get('self_healing') == 'yellow':
            print()
            print("   🟡 YELLOW STATUS - Analyzing reasons:")
            
            # Check last cycle results
            last_result = healing_op.last_healing_cycle_result
            if last_result:
                healed = last_result.get('healed', [])
                failed = last_result.get('failed', [])
                errors = last_result.get('errors', {})
                
                if healed:
                    print(f"   ✅ Healed components ({len(healed)}): {', '.join(healed[:5])}")
                
                if failed:
                    print(f"   ⚠️  Failed components ({len(failed)}): {', '.join(failed[:5])}")
                    print("   Details:")
                    for comp, error in list(errors.items())[:5]:
                        print(f"      • {comp}: {str(error)[:100]}")
                else:
                    print("   ✅ No failed components")
                
                # Check for critical components
                CRITICAL = ['safety_layer', 'file_integrity', 'trade_execution']
                critical_failed = [f for f in failed if any(c in f.lower() for c in CRITICAL)]
                if critical_failed:
                    print(f"   🔴 CRITICAL components failed: {', '.join(critical_failed)}")
                    print("      (This would cause RED status)")
                else:
                    print("   ✅ No critical component failures")
            else:
                print("   ⚠️  No recent healing cycle results")
                print("      This is normal if healing just started or no issues detected")
            
            print()
            print("   Yellow status is OK if:")
            print("   • Non-critical components have issues (they don't block trading)")
            print("   • Healing is actively working (you see 'Healed' items)")
            print("   • No critical component failures")
        elif status.get('self_healing') == 'green':
            print("   ✅ Self-healing is GREEN - all systems healthy")
        elif status.get('self_healing') == 'red':
            print("   🔴 Self-healing is RED - CRITICAL component failures")
            print("   Check logs immediately!")
        else:
            print(f"   ⚠️  Unknown status: {status.get('self_healing')}")
    except Exception as e:
        print(f"   ❌ Error checking self-healing: {e}")
        import traceback
        traceback.print_exc()
    print()
    
    # 5. Recommendations
    print("=" * 70)
    print("RECOMMENDATIONS")
    print("=" * 70)
    print()
    print("Dashboard:")
    print("  • Cache has been cleared - refresh your browser")
    print("  • Dashboard should now show updated wallet balance")
    print("  • If still incorrect, check portfolio_futures.json values")
    print()
    print("Self-Healing (Yellow):")
    print("  • Yellow is NORMAL if non-critical components have minor issues")
    print("  • The bot is still autonomous and trading")
    print("  • Only RED status requires immediate attention")
    print("  • Check logs: journalctl -u tradingbot -n 100 | grep -i healing")
    print()

if __name__ == "__main__":
    main()
