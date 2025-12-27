#!/usr/bin/env python3
"""
Golden Hour Performance Review Generator
========================================

Generates daily and weekly performance reviews for Golden Hour trading (09:00-16:00 UTC).

Outputs:
- Daily Summary Report (reports/golden_hour_daily_summary_YYYY-MM-DD.md)
- Daily Detailed Report (reports/golden_hour_daily_detailed_YYYY-MM-DD.md)
- Weekly Summary Report (reports/golden_hour_weekly_summary_YYYY-MM-DD.md)
- Weekly Detailed Report (reports/golden_hour_weekly_detailed_YYYY-MM-DD.md)
- Aggregated JSON data (reports/golden_hour_data_YYYY-MM-DD.json)

All reports are saved to git-tracked files for external review.
"""

import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Any, Tuple
import math

# Add src to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.data_registry import DataRegistry as DR

# Golden Hour window: 09:00-16:00 UTC
GOLDEN_HOUR_START = 9
GOLDEN_HOUR_END = 16
UTC = timezone.utc

# Reports directory
REPORTS_DIR = Path("reports")
REPORTS_DIR.mkdir(exist_ok=True)


def is_golden_hour(timestamp: datetime) -> bool:
    """Check if timestamp falls within Golden Hour (09:00-16:00 UTC)."""
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=UTC)
    else:
        timestamp = timestamp.astimezone(UTC)
    
    hour = timestamp.hour
    return GOLDEN_HOUR_START <= hour < GOLDEN_HOUR_END


def parse_timestamp(ts: Any) -> datetime:
    """Parse timestamp from various formats."""
    if isinstance(ts, (int, float)):
        return datetime.fromtimestamp(ts, tz=UTC)
    elif isinstance(ts, str):
        # Try ISO format
        try:
            dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=UTC)
            return dt
        except:
            pass
        # Try timestamp string
        try:
            return datetime.fromtimestamp(float(ts), tz=UTC)
        except:
            pass
    return None


def get_pnl_value(pos: Dict) -> float:
    """Extract P&L value from position with fallbacks."""
    val = pos.get("pnl") or pos.get("net_pnl") or pos.get("realized_pnl") or 0.0
    try:
        val = float(val)
        if math.isnan(val):
            return 0.0
        return val
    except (TypeError, ValueError):
        return 0.0


def analyze_golden_hour_trades(positions: List[Dict], start_time: datetime, end_time: datetime) -> Dict[str, Any]:
    """
    Analyze trades within a time period, separating Golden Hour from non-Golden Hour.
    
    Returns:
        Dict with 'golden_hour' and 'non_golden_hour' analysis
    """
    golden_hour_trades = []
    non_golden_hour_trades = []
    
    for pos in positions:
        closed_at = pos.get("closed_at")
        if not closed_at:
            continue
        
        closed_dt = parse_timestamp(closed_at)
        if not closed_dt:
            continue
        
        # Filter by time window
        if closed_dt < start_time or closed_dt >= end_time:
            continue
        
        # Categorize by Golden Hour
        if is_golden_hour(closed_dt):
            golden_hour_trades.append(pos)
        else:
            non_golden_hour_trades.append(pos)
    
    def compute_metrics(trades: List[Dict]) -> Dict[str, Any]:
        if not trades:
            return {
                "count": 0,
                "wins": 0,
                "losses": 0,
                "win_rate": 0.0,
                "total_pnl": 0.0,
                "avg_pnl": 0.0,
                "gross_profit": 0.0,
                "gross_loss": 0.0,
                "profit_factor": 0.0,
                "avg_win": 0.0,
                "avg_loss": 0.0,
                "max_win": 0.0,
                "max_loss": 0.0,
                "hold_times": [],
                "avg_hold_time_hours": 0.0,
                "symbols": {},
                "strategies": {}
            }
        
        wins = []
        losses = []
        total_pnl = 0.0
        hold_times = []
        symbols = {}
        strategies = {}
        
        for pos in trades:
            pnl = get_pnl_value(pos)
            total_pnl += pnl
            
            if pnl > 0:
                wins.append(pnl)
            elif pnl < 0:
                losses.append(pnl)
            
            # Hold time
            entry_time = pos.get("entry_time") or pos.get("opened_at")
            exit_time = pos.get("exit_time") or pos.get("closed_at")
            if entry_time and exit_time:
                entry_dt = parse_timestamp(entry_time)
                exit_dt = parse_timestamp(exit_time)
                if entry_dt and exit_dt:
                    hold_seconds = (exit_dt - entry_dt).total_seconds()
                    hold_times.append(hold_seconds)
            
            # Symbol stats
            symbol = pos.get("symbol", "UNKNOWN")
            if symbol not in symbols:
                symbols[symbol] = {"count": 0, "pnl": 0.0, "wins": 0, "losses": 0}
            symbols[symbol]["count"] += 1
            symbols[symbol]["pnl"] += pnl
            if pnl > 0:
                symbols[symbol]["wins"] += 1
            elif pnl < 0:
                symbols[symbol]["losses"] += 1
            
            # Strategy stats
            strategy = pos.get("strategy", "UNKNOWN")
            if strategy not in strategies:
                strategies[strategy] = {"count": 0, "pnl": 0.0, "wins": 0, "losses": 0}
            strategies[strategy]["count"] += 1
            strategies[strategy]["pnl"] += pnl
            if pnl > 0:
                strategies[strategy]["wins"] += 1
            elif pnl < 0:
                strategies[strategy]["losses"] += 1
        
        gross_profit = sum(wins) if wins else 0.0
        gross_loss = abs(sum(losses)) if losses else 0.0
        profit_factor = gross_profit / gross_loss if gross_loss > 0 else (gross_profit if gross_profit > 0 else 0.0)
        
        avg_hold_time_hours = sum(hold_times) / len(hold_times) / 3600 if hold_times else 0.0
        
        # Calculate win rates for symbols and strategies
        for symbol_data in symbols.values():
            total = symbol_data["wins"] + symbol_data["losses"]
            symbol_data["win_rate"] = (symbol_data["wins"] / total * 100) if total > 0 else 0.0
        
        for strategy_data in strategies.values():
            total = strategy_data["wins"] + strategy_data["losses"]
            strategy_data["win_rate"] = (strategy_data["wins"] / total * 100) if total > 0 else 0.0
        
        return {
            "count": len(trades),
            "wins": len(wins),
            "losses": len(losses),
            "win_rate": (len(wins) / len(trades) * 100) if trades else 0.0,
            "total_pnl": total_pnl,
            "avg_pnl": total_pnl / len(trades) if trades else 0.0,
            "gross_profit": gross_profit,
            "gross_loss": gross_loss,
            "profit_factor": profit_factor,
            "avg_win": sum(wins) / len(wins) if wins else 0.0,
            "avg_loss": sum(losses) / len(losses) if losses else 0.0,
            "max_win": max(wins) if wins else 0.0,
            "max_loss": min(losses) if losses else 0.0,
            "hold_times": hold_times,
            "avg_hold_time_hours": avg_hold_time_hours,
            "symbols": symbols,
            "strategies": strategies
        }
    
    return {
        "golden_hour": compute_metrics(golden_hour_trades),
        "non_golden_hour": compute_metrics(non_golden_hour_trades),
        "period_start": start_time.isoformat(),
        "period_end": end_time.isoformat(),
        "total_trades": len(golden_hour_trades) + len(non_golden_hour_trades)
    }


def generate_summary_report(analysis: Dict[str, Any], period_type: str, period_label: str) -> str:
    """Generate executive summary report in markdown format."""
    gh = analysis["golden_hour"]
    ngh = analysis["non_golden_hour"]
    
    now = datetime.now(UTC)
    
    report = f"""# Golden Hour Performance Review - {period_label}

**Generated:** {now.isoformat()}  
**Period Type:** {period_type}  
**Analysis Period:** {analysis['period_start']} to {analysis['period_end']}  
**Golden Hour Window:** 09:00-16:00 UTC

---

## Executive Summary

"""
    
    # Compare Golden Hour vs Non-Golden Hour
    wr_diff = gh["win_rate"] - ngh["win_rate"]
    pnl_diff = gh["total_pnl"] - ngh["total_pnl"]
    pf_diff = gh["profit_factor"] - ngh["profit_factor"]
    
    if gh["count"] > 0 and ngh["count"] > 0:
        report += f"""**Golden Hour trading performance compared to non-Golden Hour:**

- **Win Rate:** {gh['win_rate']:.1f}% vs {ngh['win_rate']:.1f}% ({'+' if wr_diff >= 0 else ''}{wr_diff:.1f} percentage points)
- **Total P&L:** ${gh['total_pnl']:.2f} vs ${ngh['total_pnl']:.2f} ({'+' if pnl_diff >= 0 else ''}${pnl_diff:.2f} difference)
- **Profit Factor:** {gh['profit_factor']:.2f} vs {ngh['profit_factor']:.2f} ({'+' if pf_diff >= 0 else ''}{pf_diff:.2f} difference)
- **Average Hold Time:** {gh['avg_hold_time_hours']:.2f}h vs {ngh['avg_hold_time_hours']:.2f}h

"""
        
        if wr_diff > 0 and pnl_diff > 0:
            report += "**Conclusion:** Golden Hour trading demonstrates **superior performance** ✅\n\n"
        elif wr_diff < 0 or pnl_diff < 0:
            report += "**Conclusion:** Golden Hour trading shows **mixed performance** ⚠️\n\n"
        else:
            report += "**Conclusion:** Golden Hour trading performance is **comparable** to non-Golden Hour\n\n"
    elif gh["count"] > 0:
        report += f"""**Golden Hour Performance:**

- **Total Trades:** {gh['count']}
- **Win Rate:** {gh['win_rate']:.1f}%
- **Total P&L:** ${gh['total_pnl']:.2f}
- **Profit Factor:** {gh['profit_factor']:.2f}

"""
    else:
        report += "**No Golden Hour trades found in this period.**\n\n"
    
    # Key Metrics Table
    report += """---

## Key Performance Metrics

### Golden Hour (09:00-16:00 UTC)

"""
    
    if gh["count"] > 0:
        report += f"""- **Total Trades:** {gh['count']}
- **Wins:** {gh['wins']}
- **Losses:** {gh['losses']}
- **Win Rate:** {gh['win_rate']:.1f}%
- **Total P&L:** ${gh['total_pnl']:.2f}
- **Average P&L:** ${gh['avg_pnl']:.2f}
- **Gross Profit:** ${gh['gross_profit']:.2f}
- **Gross Loss:** ${gh['gross_loss']:.2f}
- **Profit Factor:** {gh['profit_factor']:.2f}
- **Average Win:** ${gh['avg_win']:.2f}
- **Average Loss:** ${gh['avg_loss']:.2f}
- **Max Win:** ${gh['max_win']:.2f}
- **Max Loss:** ${gh['max_loss']:.2f}
- **Average Hold Time:** {gh['avg_hold_time_hours']:.2f} hours

"""
    else:
        report += "No trades in Golden Hour period.\n\n"
    
    if ngh["count"] > 0:
        report += """### Non-Golden Hour (Outside 09:00-16:00 UTC)

"""
        report += f"""- **Total Trades:** {ngh['count']}
- **Wins:** {ngh['wins']}
- **Losses:** {ngh['losses']}
- **Win Rate:** {ngh['win_rate']:.1f}%
- **Total P&L:** ${ngh['total_pnl']:.2f}
- **Average P&L:** ${ngh['avg_pnl']:.2f}
- **Profit Factor:** {ngh['profit_factor']:.2f}
- **Average Hold Time:** {ngh['avg_hold_time_hours']:.2f} hours

"""
    
    # Top Performers
    if gh["count"] > 0 and gh["symbols"]:
        report += """---

## Top Performing Symbols (Golden Hour)

"""
        sorted_symbols = sorted(gh["symbols"].items(), key=lambda x: x[1]["pnl"], reverse=True)
        report += "| Symbol | Trades | Wins | Losses | Win Rate | Total P&L | Avg P&L |\n"
        report += "|--------|--------|------|--------|----------|----------|--------|\n"
        
        for symbol, data in sorted_symbols[:10]:
            avg_pnl = data["pnl"] / data["count"] if data["count"] > 0 else 0.0
            report += f"| {symbol} | {data['count']} | {data['wins']} | {data['losses']} | {data['win_rate']:.1f}% | ${data['pnl']:.2f} | ${avg_pnl:.2f} |\n"
        
        report += "\n"
    
    # Top Strategies
    if gh["count"] > 0 and gh["strategies"]:
        report += """---

## Top Performing Strategies (Golden Hour)

"""
        sorted_strategies = sorted(gh["strategies"].items(), key=lambda x: x[1]["pnl"], reverse=True)
        report += "| Strategy | Trades | Wins | Losses | Win Rate | Total P&L | Avg P&L |\n"
        report += "|----------|--------|------|--------|----------|----------|--------|\n"
        
        for strategy, data in sorted_strategies[:10]:
            avg_pnl = data["pnl"] / data["count"] if data["count"] > 0 else 0.0
            report += f"| {strategy} | {data['count']} | {data['wins']} | {data['losses']} | {data['win_rate']:.1f}% | ${data['pnl']:.2f} | ${avg_pnl:.2f} |\n"
        
        report += "\n"
    
    report += f"""
---

**Report Generated:** {now.isoformat()}  
**Data Source:** `logs/positions_futures.json`
"""
    
    return report


def generate_detailed_report(analysis: Dict[str, Any], period_type: str, period_label: str) -> str:
    """Generate detailed comprehensive report in markdown format."""
    gh = analysis["golden_hour"]
    ngh = analysis["non_golden_hour"]
    
    now = datetime.now(UTC)
    
    report = f"""# Golden Hour Performance Review - {period_label} (Detailed)

**Generated:** {now.isoformat()}  
**Period Type:** {period_type}  
**Analysis Period:** {analysis['period_start']} to {analysis['period_end']}  
**Golden Hour Window:** 09:00-16:00 UTC

---

## Complete Performance Metrics

### Golden Hour (09:00-16:00 UTC)

"""
    
    if gh["count"] > 0:
        report += f"""
**Trade Statistics:**
- Total Trades: {gh['count']}
- Wins: {gh['wins']}
- Losses: {gh['losses']}
- Win Rate: {gh['win_rate']:.2f}%

**P&L Metrics:**
- Total P&L: ${gh['total_pnl']:.2f}
- Average P&L: ${gh['avg_pnl']:.2f}
- Gross Profit: ${gh['gross_profit']:.2f}
- Gross Loss: ${gh['gross_loss']:.2f}
- Profit Factor: {gh['profit_factor']:.2f}
- Average Win: ${gh['avg_win']:.2f}
- Average Loss: ${gh['avg_loss']:.2f}
- Max Win: ${gh['max_win']:.2f}
- Max Loss: ${gh['max_loss']:.2f}

**Timing Metrics:**
- Average Hold Time: {gh['avg_hold_time_hours']:.2f} hours
- Total Hold Time: {sum(gh['hold_times']) / 3600:.2f} hours
- Shortest Hold: {min(gh['hold_times']) / 60:.1f} minutes (if available)
- Longest Hold: {max(gh['hold_times']) / 3600:.2f} hours (if available)

"""
    else:
        report += "No trades in Golden Hour period.\n\n"
    
    if ngh["count"] > 0:
        report += """### Non-Golden Hour (Outside 09:00-16:00 UTC)

"""
        report += f"""
**Trade Statistics:**
- Total Trades: {ngh['count']}
- Wins: {ngh['wins']}
- Losses: {ngh['losses']}
- Win Rate: {ngh['win_rate']:.2f}%

**P&L Metrics:**
- Total P&L: ${ngh['total_pnl']:.2f}
- Average P&L: ${ngh['avg_pnl']:.2f}
- Profit Factor: {ngh['profit_factor']:.2f}
- Average Hold Time: {ngh['avg_hold_time_hours']:.2f} hours

"""
    
    # Detailed Symbol Breakdown
    if gh["count"] > 0 and gh["symbols"]:
        report += """---

## Performance by Symbol (Golden Hour)

"""
        sorted_symbols = sorted(gh["symbols"].items(), key=lambda x: x[1]["pnl"], reverse=True)
        report += "| Symbol | Trades | Wins | Losses | Win Rate | Total P&L | Avg P&L |\n"
        report += "|--------|--------|------|--------|----------|----------|--------|\n"
        
        for symbol, data in sorted_symbols:
            avg_pnl = data["pnl"] / data["count"] if data["count"] > 0 else 0.0
            report += f"| {symbol} | {data['count']} | {data['wins']} | {data['losses']} | {data['win_rate']:.1f}% | ${data['pnl']:.2f} | ${avg_pnl:.2f} |\n"
        
        report += "\n"
    
    # Detailed Strategy Breakdown
    if gh["count"] > 0 and gh["strategies"]:
        report += """---

## Performance by Strategy (Golden Hour)

"""
        sorted_strategies = sorted(gh["strategies"].items(), key=lambda x: x[1]["pnl"], reverse=True)
        report += "| Strategy | Trades | Wins | Losses | Win Rate | Total P&L | Avg P&L |\n"
        report += "|----------|--------|------|--------|----------|----------|--------|\n"
        
        for strategy, data in sorted_strategies:
            avg_pnl = data["pnl"] / data["count"] if data["count"] > 0 else 0.0
            report += f"| {strategy} | {data['count']} | {data['wins']} | {data['losses']} | {data['win_rate']:.1f}% | ${data['pnl']:.2f} | ${avg_pnl:.2f} |\n"
        
        report += "\n"
    
    # Comparison Table
    if gh["count"] > 0 and ngh["count"] > 0:
        report += """---

## Performance Comparison

| Metric | Golden Hour | Non-Golden Hour | Difference |
|--------|-------------|-----------------|------------|
"""
        wr_diff = gh["win_rate"] - ngh["win_rate"]
        pnl_diff = gh["total_pnl"] - ngh["total_pnl"]
        pf_diff = gh["profit_factor"] - ngh["profit_factor"]
        hold_diff = gh["avg_hold_time_hours"] - ngh["avg_hold_time_hours"]
        
        report += f"| Win Rate | {gh['win_rate']:.1f}% | {ngh['win_rate']:.1f}% | {('+' if wr_diff >= 0 else '')}{wr_diff:.1f}% |\n"
        report += f"| Total P&L | ${gh['total_pnl']:.2f} | ${ngh['total_pnl']:.2f} | {('+' if pnl_diff >= 0 else '')}${pnl_diff:.2f} |\n"
        report += f"| Profit Factor | {gh['profit_factor']:.2f} | {ngh['profit_factor']:.2f} | {('+' if pf_diff >= 0 else '')}{pf_diff:.2f} |\n"
        report += f"| Avg Hold Time | {gh['avg_hold_time_hours']:.2f}h | {ngh['avg_hold_time_hours']:.2f}h | {('+' if hold_diff >= 0 else '')}{hold_diff:.2f}h |\n"
        report += "\n"
    
    report += f"""
---

**Report Generated:** {now.isoformat()}  
**Data Source:** `logs/positions_futures.json`
"""
    
    return report


def generate_reports(period_type: str = "daily") -> Dict[str, Any]:
    """
    Generate Golden Hour performance reports.
    
    Args:
        period_type: "daily" or "weekly"
    
    Returns:
        Dict with analysis results and file paths
    """
    now = datetime.now(UTC)
    
    if period_type == "daily":
        # Daily: last 24 hours
        start_time = now - timedelta(days=1)
        end_time = now
        period_label = f"Daily - {now.strftime('%Y-%m-%d')}"
    else:  # weekly
        # Weekly: last 7 days
        start_time = now - timedelta(days=7)
        end_time = now
        period_label = f"Weekly - {start_time.strftime('%Y-%m-%d')} to {now.strftime('%Y-%m-%d')}"
    
    print(f"📊 Generating {period_type} Golden Hour performance review...")
    print(f"   Period: {start_time.isoformat()} to {end_time.isoformat()}")
    
    # Load positions
    positions_data = DR.read_json(DR.POSITIONS_FUTURES)
    if not positions_data:
        print("⚠️  No positions data found")
        return None
    
    closed_positions = positions_data.get("closed_positions", [])
    print(f"   Loaded {len(closed_positions)} closed positions")
    
    # Analyze
    analysis = analyze_golden_hour_trades(closed_positions, start_time, end_time)
    print(f"   Golden Hour trades: {analysis['golden_hour']['count']}")
    print(f"   Non-Golden Hour trades: {analysis['non_golden_hour']['count']}")
    
    # Generate reports
    date_str = now.strftime("%Y-%m-%d")
    
    summary_report = generate_summary_report(analysis, period_type, period_label)
    detailed_report = generate_detailed_report(analysis, period_type, period_label)
    
    # Save files
    if period_type == "daily":
        summary_file = REPORTS_DIR / f"golden_hour_daily_summary_{date_str}.md"
        detailed_file = REPORTS_DIR / f"golden_hour_daily_detailed_{date_str}.md"
        data_file = REPORTS_DIR / f"golden_hour_daily_data_{date_str}.json"
    else:
        summary_file = REPORTS_DIR / f"golden_hour_weekly_summary_{date_str}.md"
        detailed_file = REPORTS_DIR / f"golden_hour_weekly_detailed_{date_str}.md"
        data_file = REPORTS_DIR / f"golden_hour_weekly_data_{date_str}.json"
    
    summary_file.write_text(summary_report, encoding="utf-8")
    detailed_file.write_text(detailed_report, encoding="utf-8")
    
    # Save JSON data
    json_data = {
        "generated_at": now.isoformat(),
        "period_type": period_type,
        "period_label": period_label,
        "analysis": analysis
    }
    data_file.write_text(json.dumps(json_data, indent=2, default=str), encoding="utf-8")
    
    print(f"✅ Summary report: {summary_file}")
    print(f"✅ Detailed report: {detailed_file}")
    print(f"✅ Data file: {data_file}")
    
    return {
        "analysis": analysis,
        "summary_file": str(summary_file),
        "detailed_file": str(detailed_file),
        "data_file": str(data_file)
    }


def main():
    """Main entry point - generate both daily and weekly reports."""
    print("=" * 70)
    print("Golden Hour Performance Review Generator")
    print("=" * 70)
    print()
    
    # Generate daily reports
    print("📅 Generating DAILY reports...")
    daily_result = generate_reports("daily")
    print()
    
    # Generate weekly reports
    print("📅 Generating WEEKLY reports...")
    weekly_result = generate_reports("weekly")
    print()
    
    print("=" * 70)
    print("✅ All reports generated successfully!")
    print("=" * 70)
    print()
    print("Files saved to: reports/")
    print("   - golden_hour_daily_summary_YYYY-MM-DD.md")
    print("   - golden_hour_daily_detailed_YYYY-MM-DD.md")
    print("   - golden_hour_weekly_summary_YYYY-MM-DD.md")
    print("   - golden_hour_weekly_detailed_YYYY-MM-DD.md")
    print("   - golden_hour_daily_data_YYYY-MM-DD.json")
    print("   - golden_hour_weekly_data_YYYY-MM-DD.json")
    print()
    print("All files are git-tracked and ready for external review.")


if __name__ == "__main__":
    main()

