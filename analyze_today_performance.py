#!/usr/bin/env python3
"""
Analyze Today's Trading Performance
====================================
Checks today's trades, verifies enhanced logging worked, and provides performance analysis.
"""

import json
import os
import sys
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Any
from collections import defaultdict

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

try:
    from src.data_registry import DataRegistry as DR
    from src.position_manager import load_futures_positions
except ImportError as e:
    print(f"ERROR: Import error: {e}")
    print("Note: This script may need to be run on the server where dependencies are installed")
    sys.exit(1)


def parse_timestamp(ts_str: str) -> float:
    """Parse timestamp string to Unix timestamp."""
    if isinstance(ts_str, (int, float)):
        return float(ts_str)
    
    try:
        # Handle ISO format with timezone
        ts_clean = ts_str.replace('Z', '+00:00')
        if '.' in ts_clean and '+' in ts_clean:
            # Handle microseconds
            parts = ts_clean.split('+')
            if len(parts) == 2:
                main_part = parts[0].split('.')[0]
                tz_part = parts[1]
                ts_clean = f"{main_part}+{tz_part}"
        
        dt = datetime.fromisoformat(ts_clean)
        return dt.timestamp()
    except Exception as e:
        print(f"⚠️  Failed to parse timestamp '{ts_str}': {e}")
        return 0.0


def is_today(ts_str: str) -> bool:
    """Check if timestamp is from today (UTC)."""
    ts = parse_timestamp(ts_str)
    if ts == 0:
        return False
    
    today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    today_end = today_start + timedelta(days=1)
    
    return today_start.timestamp() <= ts < today_end.timestamp()


def analyze_volatility_snapshot(position: Dict) -> Dict[str, Any]:
    """Analyze volatility snapshot data quality."""
    snapshot = position.get("volatility_snapshot", {})
    
    if not snapshot:
        return {
            "has_snapshot": False,
            "atr_14": None,
            "volume_24h": None,
            "regime_at_entry": None,
            "has_signal_components": False,
        }
    
    signal_components = snapshot.get("signal_components", {})
    
    return {
        "has_snapshot": True,
        "atr_14": snapshot.get("atr_14", 0.0),
        "volume_24h": snapshot.get("volume_24h", 0.0),
        "regime_at_entry": snapshot.get("regime_at_entry", "unknown"),
        "has_signal_components": bool(signal_components),
        "signal_components": {
            "liquidation": signal_components.get("liquidation", 0.0),
            "funding": signal_components.get("funding", 0.0),
            "whale": signal_components.get("whale", 0.0),
        }
    }


def analyze_today_performance():
    """Analyze today's trading performance."""
    print("=" * 80)
    print("TODAY'S TRADING PERFORMANCE ANALYSIS")
    print("=" * 80)
    print()
    
    # Get positions data
    try:
        positions_data = load_futures_positions()
    except Exception as e:
        print(f"ERROR: Failed to load positions: {e}")
        print(f"      This script may need to be run on the server where the bot is running")
        return
    
    if not positions_data:
        print("ERROR: No positions data found")
        return
    
    # Get closed positions
    closed_positions = positions_data.get("closed_positions", [])
    open_positions = positions_data.get("open_positions", [])
    
    print(f"Total closed positions in file: {len(closed_positions)}")
    print(f"Total open positions: {len(open_positions)}")
    print()
    
    # Filter to today's closed positions
    today_closed = []
    for pos in closed_positions:
        closed_at = pos.get("closed_at") or pos.get("timestamp")
        if closed_at and is_today(closed_at):
            today_closed.append(pos)
    
    print(f"Today's closed positions: {len(today_closed)}")
    print()
    
    if not today_closed:
        print("WARNING: No closed positions found for today")
        print("         Checking open positions opened today...")
        print()
        
        # Check if any positions opened today
        today_opened = []
        for pos in open_positions:
            opened_at = pos.get("opened_at") or pos.get("timestamp")
            if opened_at and is_today(opened_at):
                today_opened.append(pos)
        
        if today_opened:
            print(f"Found {len(today_opened)} positions opened today (still open):")
            for pos in today_opened:
                symbol = pos.get("symbol", "UNKNOWN")
                direction = pos.get("direction", "UNKNOWN")
                entry_price = pos.get("entry_price", 0)
                strategy = pos.get("strategy", "UNKNOWN")
                snapshot_info = analyze_volatility_snapshot(pos)
                
                print(f"   - {symbol} {direction} @ ${entry_price:.2f} ({strategy})")
                if snapshot_info["has_snapshot"]:
                    print(f"     [OK] Enhanced logging: ATR={snapshot_info['atr_14']:.2f}, "
                          f"Regime={snapshot_info['regime_at_entry']}")
                else:
                    print(f"     [WARNING] No volatility snapshot (logging may not be working)")
        else:
            print("   No positions opened today found")
        
        return
    
    # Analyze today's closed positions
    print("=" * 80)
    print("TODAY'S CLOSED TRADES ANALYSIS")
    print("=" * 80)
    print()
    
    # Performance metrics
    total_pnl = 0.0
    winning_trades = 0
    losing_trades = 0
    total_trades = len(today_closed)
    
    # Enhanced logging metrics
    has_snapshot_count = 0
    missing_snapshot_count = 0
    regime_distribution = defaultdict(int)
    atr_values = []
    volume_values = []
    
    # Detailed trade analysis
    trades_detail = []
    
    for pos in today_closed:
        symbol = pos.get("symbol", "UNKNOWN")
        direction = pos.get("direction", "UNKNOWN")
        entry_price = pos.get("entry_price", 0)
        exit_price = pos.get("exit_price", 0)
        pnl = pos.get("pnl") or pos.get("net_pnl", 0.0)
        strategy = pos.get("strategy", "UNKNOWN")
        opened_at = pos.get("opened_at") or pos.get("timestamp", "")
        closed_at = pos.get("closed_at") or pos.get("timestamp", "")
        
        total_pnl += float(pnl)
        if float(pnl) > 0:
            winning_trades += 1
        else:
            losing_trades += 1
        
        # Analyze volatility snapshot
        snapshot_info = analyze_volatility_snapshot(pos)
        
        if snapshot_info["has_snapshot"]:
            has_snapshot_count += 1
            regime = snapshot_info["regime_at_entry"]
            regime_distribution[regime] += 1
            
            atr = snapshot_info["atr_14"]
            volume = snapshot_info["volume_24h"]
            
            if atr and atr > 0:
                atr_values.append(atr)
            if volume and volume > 0:
                volume_values.append(volume)
        else:
            missing_snapshot_count += 1
        
        trades_detail.append({
            "symbol": symbol,
            "direction": direction,
            "entry_price": entry_price,
            "exit_price": exit_price,
            "pnl": pnl,
            "strategy": strategy,
            "opened_at": opened_at,
            "closed_at": closed_at,
            "snapshot_info": snapshot_info,
        })
    
    # Print summary
    print("PERFORMANCE SUMMARY")
    print("-" * 80)
    print(f"Total Trades: {total_trades}")
    print(f"Winning Trades: {winning_trades} ({winning_trades/total_trades*100:.1f}% win rate)" if total_trades > 0 else "Winning Trades: 0")
    print(f"Losing Trades: {losing_trades} ({losing_trades/total_trades*100:.1f}% loss rate)" if total_trades > 0 else "Losing Trades: 0")
    print(f"Net P&L: ${total_pnl:.2f}")
    print(f"Average P&L per Trade: ${total_pnl/total_trades:.2f}" if total_trades > 0 else "Average P&L per Trade: $0.00")
    print()
    
    print("ENHANCED LOGGING VERIFICATION")
    print("-" * 80)
    print(f"Trades with volatility snapshot: {has_snapshot_count}/{total_trades} ({has_snapshot_count/total_trades*100:.1f}%)" if total_trades > 0 else "Trades with volatility snapshot: 0/0")
    print(f"Trades missing snapshot: {missing_snapshot_count}/{total_trades} ({missing_snapshot_count/total_trades*100:.1f}%)" if total_trades > 0 else "Trades missing snapshot: 0/0")
    
    if has_snapshot_count > 0:
        print()
        print("[OK] Enhanced logging is WORKING")
        print()
        print("Regime Distribution:")
        for regime, count in sorted(regime_distribution.items(), key=lambda x: x[1], reverse=True):
            print(f"  - {regime}: {count} trades")
        
        if atr_values:
            print()
            print(f"ATR Statistics:")
            print(f"  - Average ATR: {sum(atr_values)/len(atr_values):.2f}")
            print(f"  - Min ATR: {min(atr_values):.2f}")
            print(f"  - Max ATR: {max(atr_values):.2f}")
        
        if volume_values:
            print()
            print(f"24h Volume Statistics:")
            avg_vol = sum(volume_values)/len(volume_values)
            print(f"  - Average Volume: ${avg_vol:,.2f}")
            print(f"  - Min Volume: ${min(volume_values):,.2f}")
            print(f"  - Max Volume: ${max(volume_values):,.2f}")
    else:
        print()
        print("[WARNING] Enhanced logging may NOT be working - no volatility snapshots found")
        print("          This could mean:")
        print("          1. Trades were opened before enhanced logging was enabled")
        print("          2. There's an error in the logging code")
        print("          3. The create_volatility_snapshot function is failing silently")
    
    print()
    print("=" * 80)
    print("DETAILED TRADE BREAKDOWN")
    print("=" * 80)
    print()
    
    for i, trade in enumerate(trades_detail, 1):
        print(f"Trade {i}: {trade['symbol']} {trade['direction']}")
        print(f"  Entry: ${trade['entry_price']:.2f} | Exit: ${trade['exit_price']:.2f}")
        pnl_str = f"${trade['pnl']:.2f}"
        if trade['pnl'] > 0:
            pnl_str = f"+{pnl_str}"
        print(f"  P&L: {pnl_str} | Strategy: {trade['strategy']}")
        
        if trade['snapshot_info']['has_snapshot']:
            print(f"  [OK] Enhanced Logging:")
            print(f"     - Regime: {trade['snapshot_info']['regime_at_entry']}")
            print(f"     - ATR: {trade['snapshot_info']['atr_14']:.2f}")
            print(f"     - Volume 24h: ${trade['snapshot_info']['volume_24h']:,.2f}")
            if trade['snapshot_info']['has_signal_components']:
                comp = trade['snapshot_info']['signal_components']
                print(f"     - Signal Components:")
                print(f"       * Liquidation: {comp['liquidation']:.4f}")
                print(f"       * Funding: {comp['funding']:.6f}")
                print(f"       * Whale: ${comp['whale']:,.2f}")
        else:
            print(f"  [WARNING] No volatility snapshot")
        
        print()
    
    print("=" * 80)
    print("ANALYSIS COMPLETE")
    print("=" * 80)


if __name__ == "__main__":
    analyze_today_performance()

