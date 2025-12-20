#!/usr/bin/env python3
"""
Comprehensive Profitability Analysis
====================================
Uses the same data loading methods as existing analysis tools.
Run this on the server where the bot is running (data exists there).

Usage:
    python run_profitability_analysis.py
"""

import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

# Try to use existing comprehensive analysis tools
print("=" * 80)
print("COMPREHENSIVE PROFITABILITY ANALYSIS")
print("=" * 80)
print("\nAttempting to use existing analysis tools...\n")

# Method 1: Use comprehensive_trade_analysis.py
try:
    from src.comprehensive_trade_analysis import ComprehensiveTradeAnalysis
    print("[METHOD 1] Using ComprehensiveTradeAnalysis...")
    analyzer = ComprehensiveTradeAnalysis()
    data_status = analyzer.load_all_data()
    
    if data_status.get("positions_futures", {}).get("closed_positions", 0) > 0:
        print(f"\n[SUCCESS] Found {data_status['positions_futures']['closed_positions']} closed positions")
        print("Running full analysis...\n")
        results = analyzer.run_full_analysis()
        print("\n[COMPLETE] Analysis finished. Check output above for results.")
    else:
        print("[INFO] No closed positions found via ComprehensiveTradeAnalysis")
        print("[INFO] Trying alternative methods...\n")
except Exception as e:
    print(f"[ERROR] ComprehensiveTradeAnalysis failed: {e}")
    print("[INFO] Trying alternative methods...\n")

# Method 2: Use deep_profitability_analyzer.py
try:
    from src.deep_profitability_analyzer import DeepProfitabilityAnalyzer
    print("[METHOD 2] Using DeepProfitabilityAnalyzer...")
    analyzer = DeepProfitabilityAnalyzer()
    analyzer.load_all_data()
    
    if len(analyzer.closed_trades) > 0:
        print(f"\n[SUCCESS] Found {len(analyzer.closed_trades)} closed trades")
        print("Running full analysis...\n")
        results = analyzer.run_full_analysis()
        print("\n[COMPLETE] Analysis finished. Results saved to reports/deep_profitability_analysis.json")
    else:
        print("[INFO] No closed trades found via DeepProfitabilityAnalyzer")
        print("[INFO] Trying direct data access...\n")
except Exception as e:
    print(f"[ERROR] DeepProfitabilityAnalyzer failed: {e}")
    print("[INFO] Trying direct data access...\n")

# Method 3: Direct data access using DataRegistry
try:
    from src.data_registry import DataRegistry as DR
    print("[METHOD 3] Using DataRegistry for direct data access...")
    
    # Try database first
    try:
        closed_trades = DR.get_closed_trades_from_db(limit=10000)
        if closed_trades:
            print(f"[SUCCESS] Found {len(closed_trades)} closed trades from database")
            print("\n[ANALYSIS] Running profitability analysis...")
            
            # Quick analysis
            total_pnl = sum(t.get('profit_usd', t.get('pnl', 0)) or 0 for t in closed_trades)
            winners = [t for t in closed_trades if (t.get('profit_usd', t.get('pnl', 0)) or 0) > 0]
            win_rate = len(winners) / len(closed_trades) * 100 if closed_trades else 0
            
            print(f"\n{'='*80}")
            print("QUICK PROFITABILITY SUMMARY")
            print(f"{'='*80}")
            print(f"Total Trades: {len(closed_trades)}")
            print(f"Total P&L: ${total_pnl:.2f}")
            print(f"Win Rate: {win_rate:.2f}% ({len(winners)} wins, {len(closed_trades)-len(winners)} losses)")
            
            # By symbol
            from collections import defaultdict
            by_symbol = defaultdict(lambda: {"pnl": 0, "wins": 0, "losses": 0})
            for t in closed_trades:
                sym = t.get('symbol', 'UNKNOWN')
                pnl = t.get('profit_usd', t.get('pnl', 0)) or 0
                by_symbol[sym]["pnl"] += pnl
                if pnl > 0:
                    by_symbol[sym]["wins"] += 1
                else:
                    by_symbol[sym]["losses"] += 1
            
            print(f"\nBY SYMBOL:")
            for sym, data in sorted(by_symbol.items(), key=lambda x: x[1]["pnl"], reverse=True):
                total = data["wins"] + data["losses"]
                wr = (data["wins"] / total * 100) if total > 0 else 0
                print(f"   {sym}: P&L=${data['pnl']:.2f}, WR={wr:.1f}%, n={total}")
            
            # By direction
            by_direction = defaultdict(lambda: {"pnl": 0, "wins": 0, "losses": 0})
            for t in closed_trades:
                direction = t.get('direction', t.get('side', 'UNKNOWN'))
                pnl = t.get('profit_usd', t.get('pnl', 0)) or 0
                by_direction[direction]["pnl"] += pnl
                if pnl > 0:
                    by_direction[direction]["wins"] += 1
                else:
                    by_direction[direction]["losses"] += 1
            
            print(f"\nBY DIRECTION:")
            for direction, data in by_direction.items():
                total = data["wins"] + data["losses"]
                wr = (data["wins"] / total * 100) if total > 0 else 0
                print(f"   {direction}: P&L=${data['pnl']:.2f}, WR={wr:.1f}%, n={total}")
            
            print(f"\n{'='*80}")
            print("For detailed analysis, run: python deep_profitability_dive.py")
            print(f"{'='*80}\n")
        else:
            print("[INFO] Database returned no trades, trying JSON fallback...")
            closed_positions = DR.get_closed_positions(hours=None)
            if closed_positions:
                print(f"[SUCCESS] Found {len(closed_positions)} closed positions from JSON")
            else:
                print("[WARNING] No trades found in database or JSON")
    except Exception as e:
        print(f"[ERROR] Database access failed: {e}")
        # Try JSON fallback
        try:
            closed_positions = DR.get_closed_positions(hours=None)
            if closed_positions:
                print(f"[SUCCESS] Found {len(closed_positions)} closed positions from JSON fallback")
            else:
                print("[WARNING] No trades found")
        except Exception as e2:
            print(f"[ERROR] JSON fallback also failed: {e2}")
            
except Exception as e:
    print(f"[ERROR] DataRegistry access failed: {e}")
    print("\n[INFO] Data may not be accessible from this location.")
    print("[INFO] This script should be run on the server where the bot is running.")
    print("[INFO] Server: 159.65.168.230")
    print("[INFO] Expected data locations:")
    print("   - logs/positions_futures.json")
    print("   - data/trading_system.db")
    print("   - logs/signals.jsonl")

print("\n" + "=" * 80)
print("ANALYSIS COMPLETE")
print("=" * 80)
