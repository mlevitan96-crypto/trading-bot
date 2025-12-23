#!/usr/bin/env python3
"""
Analyze Exported Data Files
============================
Read and analyze exported data files from the repository.
This allows AI to analyze full datasets instead of partial console output.
"""

import json
import os
import sys
from pathlib import Path
from datetime import datetime


def analyze_performance_report():
    """Analyze the performance summary report JSON file."""
    report_file = "performance_summary_report.json"
    
    if not os.path.exists(report_file):
        print(f"❌ Report file not found: {report_file}")
        return None
    
    print(f"📊 Analyzing {report_file}...")
    print()
    
    with open(report_file, 'r') as f:
        report = json.load(f)
    
    # Display summary
    print("=" * 80)
    print("PERFORMANCE SUMMARY ANALYSIS")
    print("=" * 80)
    print()
    
    summary = report.get("summary", {})
    logging_status = report.get("enhanced_logging_status", {})
    
    print("📈 Performance Metrics:")
    print(f"  Total Closed Trades: {summary.get('total_closed_trades', 0)}")
    print(f"  Win Rate: {summary.get('win_rate_pct', 0):.1f}%")
    print(f"  Net P&L: ${summary.get('net_pnl_usd', 0):.2f}")
    print(f"  Average P&L per Trade: ${summary.get('average_pnl_per_trade', 0):.2f}")
    print()
    
    print("🔍 Enhanced Logging Status:")
    working = logging_status.get("logging_working", False)
    coverage = logging_status.get("coverage_pct", 0)
    status_icon = "✅" if working else "❌"
    print(f"  Status: {status_icon} {'WORKING' if working else 'NOT WORKING'}")
    print(f"  Coverage: {coverage:.1f}%")
    print(f"  Trades with Snapshots: {logging_status.get('closed_trades_with_snapshot', 0)}/{summary.get('total_closed_trades', 0)}")
    print()
    
    # Regime distribution
    regime_dist = report.get("regime_distribution", {})
    if regime_dist:
        print("📊 Regime Distribution:")
        for regime, count in sorted(regime_dist.items(), key=lambda x: x[1], reverse=True):
            print(f"  {regime}: {count} trades")
        print()
    
    # Volatility metrics
    vol_metrics = report.get("volatility_metrics", {})
    if vol_metrics.get("average_atr"):
        print("📈 Volatility Metrics:")
        print(f"  Average ATR: {vol_metrics.get('average_atr', 0):.2f}")
        print(f"  Average 24h Volume: ${vol_metrics.get('average_volume_24h', 0):,.2f}")
        print()
    
    # Trade details summary
    trades = report.get("trades_detail", [])
    if trades:
        print(f"📋 Trade Details: {len(trades)} trades in report")
        print()
        print("Sample trades (first 5):")
        for i, trade in enumerate(trades[:5], 1):
            pnl = trade.get("pnl_usd", 0)
            pnl_str = f"${pnl:.2f}" if pnl >= 0 else f"-${abs(pnl):.2f}"
            print(f"  {i}. {trade.get('symbol')} {trade.get('direction')}: {pnl_str} ({trade.get('strategy')})")
        print()
    
    return report


def analyze_external_review():
    """Analyze the external review summary."""
    review_file = "EXTERNAL_REVIEW_SUMMARY.md"
    
    if not os.path.exists(review_file):
        print(f"⚠️  Review file not found: {review_file}")
        return None
    
    print(f"📄 External Review Summary available: {review_file}")
    with open(review_file, 'r') as f:
        content = f.read()
    
    # Extract key findings
    if "Enhanced Logging Not Working" in content or "❌" in content:
        print("  ⚠️  Critical finding: Enhanced logging is not working")
    
    return content


def main():
    """Main analysis function."""
    print("=" * 80)
    print("EXPORTED DATA ANALYSIS")
    print("=" * 80)
    print()
    
    # Check what files are available
    available_files = []
    if os.path.exists("performance_summary_report.json"):
        available_files.append("performance_summary_report.json")
    if os.path.exists("performance_summary_report.md"):
        available_files.append("performance_summary_report.md")
    if os.path.exists("EXTERNAL_REVIEW_SUMMARY.md"):
        available_files.append("EXTERNAL_REVIEW_SUMMARY.md")
    
    if not available_files:
        print("❌ No report files found in current directory")
        print("   Expected files:")
        print("   - performance_summary_report.json")
        print("   - performance_summary_report.md")
        print("   - EXTERNAL_REVIEW_SUMMARY.md")
        return
    
    print(f"Found {len(available_files)} report file(s)")
    print()
    
    # Analyze performance report
    if "performance_summary_report.json" in available_files:
        report = analyze_performance_report()
    
    # Check external review
    if "EXTERNAL_REVIEW_SUMMARY.md" in available_files:
        analyze_external_review()
    
    print("=" * 80)
    print("ANALYSIS COMPLETE")
    print("=" * 80)
    print()
    print("💡 Tip: AI can now analyze the full JSON/MD files directly")
    print("   instead of requiring manual copy/paste from console")


if __name__ == "__main__":
    main()

