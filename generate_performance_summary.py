#!/usr/bin/env python3
"""
Generate Performance Summary Report for External Review
========================================================
Creates a comprehensive, shareable summary of today's trading performance
and enhanced logging verification.
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
    print("Note: This script must be run on the server where dependencies are installed")
    sys.exit(1)


def parse_timestamp(ts_str: str) -> float:
    """Parse timestamp string to Unix timestamp."""
    if isinstance(ts_str, (int, float)):
        return float(ts_str)
    
    try:
        ts_clean = ts_str.replace('Z', '+00:00')
        if '.' in ts_clean and '+' in ts_clean:
            parts = ts_clean.split('+')
            if len(parts) == 2:
                main_part = parts[0].split('.')[0]
                tz_part = parts[1]
                ts_clean = f"{main_part}+{tz_part}"
        
        dt = datetime.fromisoformat(ts_clean)
        return dt.timestamp()
    except Exception as e:
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


def generate_summary_report():
    """Generate comprehensive summary report."""
    print("Generating performance summary report...")
    
    # Get positions data
    try:
        positions_data = load_futures_positions()
    except Exception as e:
        print(f"ERROR: Failed to load positions: {e}")
        return None
    
    if not positions_data:
        print("ERROR: No positions data found")
        return None
    
    closed_positions = positions_data.get("closed_positions", [])
    open_positions = positions_data.get("open_positions", [])
    
    # Filter to today's closed positions
    today_closed = []
    for pos in closed_positions:
        closed_at = pos.get("closed_at") or pos.get("timestamp")
        if closed_at and is_today(closed_at):
            today_closed.append(pos)
    
    # Filter to today's open positions
    today_opened = []
    for pos in open_positions:
        opened_at = pos.get("opened_at") or pos.get("timestamp")
        if opened_at and is_today(opened_at):
            today_opened.append(pos)
    
    # Analyze closed trades
    total_pnl = 0.0
    winning_trades = 0
    losing_trades = 0
    has_snapshot_count = 0
    missing_snapshot_count = 0
    regime_distribution = defaultdict(int)
    atr_values = []
    volume_values = []
    
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
    
    # Analyze open positions
    open_positions_snapshots = 0
    for pos in today_opened:
        snapshot_info = analyze_volatility_snapshot(pos)
        if snapshot_info["has_snapshot"]:
            open_positions_snapshots += 1
    
    # Generate report
    report_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    report_time = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    
    report = {
        "report_metadata": {
            "generated_at": report_time,
            "report_date": report_date,
            "timezone": "UTC"
        },
        "summary": {
            "total_closed_trades": len(today_closed),
            "total_open_positions": len(today_opened),
            "winning_trades": winning_trades,
            "losing_trades": losing_trades,
            "win_rate_pct": (winning_trades / len(today_closed) * 100) if len(today_closed) > 0 else 0.0,
            "net_pnl_usd": round(total_pnl, 2),
            "average_pnl_per_trade": round(total_pnl / len(today_closed), 2) if len(today_closed) > 0 else 0.0
        },
        "enhanced_logging_status": {
            "closed_trades_with_snapshot": has_snapshot_count,
            "closed_trades_missing_snapshot": missing_snapshot_count,
            "open_positions_with_snapshot": open_positions_snapshots,
            "open_positions_missing_snapshot": len(today_opened) - open_positions_snapshots,
            "logging_working": has_snapshot_count > 0 or open_positions_snapshots > 0,
            "coverage_pct": (has_snapshot_count / len(today_closed) * 100) if len(today_closed) > 0 else 0.0
        },
        "regime_distribution": dict(regime_distribution),
        "volatility_metrics": {
            "average_atr": round(sum(atr_values) / len(atr_values), 2) if atr_values else None,
            "min_atr": round(min(atr_values), 2) if atr_values else None,
            "max_atr": round(max(atr_values), 2) if atr_values else None,
            "average_volume_24h": round(sum(volume_values) / len(volume_values), 2) if volume_values else None,
            "min_volume_24h": round(min(volume_values), 2) if volume_values else None,
            "max_volume_24h": round(max(volume_values), 2) if volume_values else None
        },
        "trades_detail": []
    }
    
    # Add trade details (limit to reasonable number)
    for trade in trades_detail[:50]:  # Limit to 50 for readability
        trade_summary = {
            "symbol": trade["symbol"],
            "direction": trade["direction"],
            "entry_price": trade["entry_price"],
            "exit_price": trade["exit_price"],
            "pnl_usd": round(float(trade["pnl"]), 2),
            "strategy": trade["strategy"],
            "has_enhanced_logging": trade["snapshot_info"]["has_snapshot"],
            "regime_at_entry": trade["snapshot_info"]["regime_at_entry"] if trade["snapshot_info"]["has_snapshot"] else None,
            "atr_14": round(trade["snapshot_info"]["atr_14"], 2) if trade["snapshot_info"]["has_snapshot"] and trade["snapshot_info"]["atr_14"] else None
        }
        report["trades_detail"].append(trade_summary)
    
    # Generate markdown report
    markdown_report = f"""# Trading Bot Performance Summary Report
**Generated:** {report_time}  
**Date Analyzed:** {report_date}

---

## Executive Summary

### Performance Metrics
- **Total Closed Trades:** {len(today_closed)}
- **Winning Trades:** {winning_trades}
- **Losing Trades:** {losing_trades}
- **Win Rate:** {report['summary']['win_rate_pct']:.1f}%
- **Net P&L:** ${report['summary']['net_pnl_usd']:.2f}
- **Average P&L per Trade:** ${report['summary']['average_pnl_per_trade']:.2f}

### Enhanced Logging Status
- **Logging Working:** {'✅ YES' if report['enhanced_logging_status']['logging_working'] else '❌ NO'}
- **Coverage:** {report['enhanced_logging_status']['coverage_pct']:.1f}% of closed trades have volatility snapshots
- **Closed Trades with Snapshot:** {has_snapshot_count}/{len(today_closed)}
- **Open Positions with Snapshot:** {open_positions_snapshots}/{len(today_opened)}

---

## Regime Distribution

"""
    
    if regime_distribution:
        for regime, count in sorted(regime_distribution.items(), key=lambda x: x[1], reverse=True):
            markdown_report += f"- **{regime}:** {count} trades\n"
    else:
        markdown_report += "No regime data available (no trades with snapshots)\n"
    
    markdown_report += "\n---\n\n## Volatility Metrics\n\n"
    
    if atr_values:
        markdown_report += f"- **Average ATR:** {report['volatility_metrics']['average_atr']:.2f}\n"
        markdown_report += f"- **Min ATR:** {report['volatility_metrics']['min_atr']:.2f}\n"
        markdown_report += f"- **Max ATR:** {report['volatility_metrics']['max_atr']:.2f}\n"
    else:
        markdown_report += "No ATR data available\n"
    
    if volume_values:
        markdown_report += f"- **Average 24h Volume:** ${report['volatility_metrics']['average_volume_24h']:,.2f}\n"
        markdown_report += f"- **Min 24h Volume:** ${report['volatility_metrics']['min_volume_24h']:,.2f}\n"
        markdown_report += f"- **Max 24h Volume:** ${report['volatility_metrics']['max_volume_24h']:,.2f}\n"
    
    markdown_report += "\n---\n\n## Trade Details\n\n"
    
    if trades_detail:
        markdown_report += "| Symbol | Direction | Entry | Exit | P&L | Strategy | Enhanced Logging | Regime |\n"
        markdown_report += "|--------|-----------|-------|------|-----|----------|------------------|--------|\n"
        
        for trade in trades_detail[:20]:  # Show first 20 in markdown table
            pnl_str = f"${float(trade['pnl']):.2f}"
            if float(trade['pnl']) > 0:
                pnl_str = f"+{pnl_str}"
            
            logging_status = "✅" if trade['snapshot_info']['has_snapshot'] else "❌"
            regime = trade['snapshot_info']['regime_at_entry'] if trade['snapshot_info']['has_snapshot'] else "N/A"
            
            markdown_report += f"| {trade['symbol']} | {trade['direction']} | ${trade['entry_price']:.2f} | ${trade['exit_price']:.2f} | {pnl_str} | {trade['strategy']} | {logging_status} | {regime} |\n"
        
        if len(trades_detail) > 20:
            markdown_report += f"\n*Note: Showing first 20 of {len(trades_detail)} trades. See JSON export for complete list.*\n"
    else:
        markdown_report += "No closed trades for today.\n"
    
    markdown_report += f"\n---\n\n## Conclusion\n\n"
    
    if report['enhanced_logging_status']['logging_working']:
        markdown_report += "✅ **Enhanced logging is working correctly.**\n\n"
        markdown_report += f"- {has_snapshot_count} out of {len(today_closed)} closed trades have volatility snapshots\n"
        if today_opened:
            markdown_report += f"- {open_positions_snapshots} out of {len(today_opened)} open positions have volatility snapshots\n"
    else:
        markdown_report += "⚠️ **Enhanced logging may not be working.**\n\n"
        markdown_report += "- No volatility snapshots found in today's trades\n"
        markdown_report += "- This could indicate:\n"
        markdown_report += "  1. No trades occurred today\n"
        markdown_report += "  2. Logging errors (silent failures)\n"
        markdown_report += "  3. Trades occurred before logging was enabled\n"
    
    return {
        "json": report,
        "markdown": markdown_report
    }


def main():
    """Main function to generate and save reports."""
    reports = generate_summary_report()
    
    if not reports:
        print("ERROR: Failed to generate report")
        sys.exit(1)
    
    # Save JSON report
    json_file = "performance_summary_report.json"
    with open(json_file, 'w') as f:
        json.dump(reports["json"], f, indent=2)
    
    print(f"✅ JSON report saved to: {json_file}")
    
    # Save Markdown report
    md_file = "performance_summary_report.md"
    with open(md_file, 'w') as f:
        f.write(reports["markdown"])
    
    print(f"✅ Markdown report saved to: {md_file}")
    
    # Print summary to console
    print("\n" + "=" * 80)
    print("QUICK SUMMARY")
    print("=" * 80)
    print(f"Total Closed Trades: {reports['json']['summary']['total_closed_trades']}")
    print(f"Win Rate: {reports['json']['summary']['win_rate_pct']:.1f}%")
    print(f"Net P&L: ${reports['json']['summary']['net_pnl_usd']:.2f}")
    print(f"Enhanced Logging Working: {'YES' if reports['json']['enhanced_logging_status']['logging_working'] else 'NO'}")
    print(f"Coverage: {reports['json']['enhanced_logging_status']['coverage_pct']:.1f}%")
    print("=" * 80)
    print(f"\nReports saved. Share {md_file} or {json_file} for external review.")


if __name__ == "__main__":
    main()

