#!/usr/bin/env python3
"""
Analyze Golden Hour Trades
==========================
Analyzes all trades that occurred during golden hour (09:00-16:00 UTC)
and generates a comprehensive report.
"""

import json
import sys
from pathlib import Path
from datetime import datetime, timezone, timedelta
from collections import defaultdict

def is_golden_hour(dt: datetime) -> bool:
    """Check if datetime is within golden hour window (09:00-16:00 UTC)"""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    hour = dt.hour
    return 9 <= hour < 16


def parse_timestamp(ts):
    """Parse various timestamp formats"""
    if ts is None:
        return None
    
    try:
        if isinstance(ts, str):
            # Try ISO format
            if 'T' in ts or ' ' in ts:
                dt = datetime.fromisoformat(ts.replace('Z', '+00:00'))
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                return dt
            # Try numeric string
            return datetime.fromtimestamp(float(ts), tz=timezone.utc)
        elif isinstance(ts, (int, float)):
            return datetime.fromtimestamp(float(ts), tz=timezone.utc)
    except:
        pass
    
    return None


def analyze_golden_hour_trades():
    """Analyze all trades during golden hour"""
    try:
        from src.data_registry import DataRegistry
        
        registry = DataRegistry()
        positions_file = Path(registry.POSITIONS_FUTURES)
        
        if not positions_file.exists():
            print(f"❌ Positions file not found: {positions_file}")
            return None
        
        with open(positions_file, 'r') as f:
            data = json.load(f)
        
        closed_positions = data.get("closed_positions", [])
        open_positions = data.get("open_positions", [])
        
        # Analyze closed trades
        golden_hour_closed = []
        non_golden_closed = []
        
        for pos in closed_positions:
            opened_at = parse_timestamp(pos.get("opened_at") or pos.get("open_ts"))
            if not opened_at:
                continue
            
            if is_golden_hour(opened_at):
                golden_hour_closed.append(pos)
            else:
                non_golden_closed.append(pos)
        
        # Analyze open trades
        golden_hour_open = []
        non_golden_open = []
        
        for pos in open_positions:
            opened_at = parse_timestamp(pos.get("opened_at") or pos.get("open_ts"))
            if not opened_at:
                continue
            
            if is_golden_hour(opened_at):
                golden_hour_open.append(pos)
            else:
                non_golden_open.append(pos)
        
        # Calculate statistics
        def calc_stats(positions):
            if not positions:
                return {
                    "count": 0,
                    "total_pnl": 0.0,
                    "wins": 0,
                    "losses": 0,
                    "win_rate": 0.0,
                    "avg_pnl": 0.0,
                    "with_snapshots": 0,
                    "snapshot_rate": 0.0,
                }
            
            total_pnl = 0.0
            wins = 0
            losses = 0
            with_snapshots = 0
            
            for pos in positions:
                pnl = float(pos.get("pnl", 0) or 0)
                total_pnl += pnl
                if pnl > 0:
                    wins += 1
                elif pnl < 0:
                    losses += 1
                
                if pos.get("volatility_snapshot"):
                    with_snapshots += 1
            
            count = len(positions)
            win_rate = (wins / count * 100) if count > 0 else 0.0
            snapshot_rate = (with_snapshots / count * 100) if count > 0 else 0.0
            
            return {
                "count": count,
                "total_pnl": total_pnl,
                "wins": wins,
                "losses": losses,
                "win_rate": win_rate,
                "avg_pnl": total_pnl / count if count > 0 else 0.0,
                "with_snapshots": with_snapshots,
                "snapshot_rate": snapshot_rate,
            }
        
        golden_closed_stats = calc_stats(golden_hour_closed)
        non_golden_closed_stats = calc_stats(non_golden_closed)
        golden_open_stats = calc_stats(golden_hour_open)
        
        # Group by symbol
        symbol_stats = defaultdict(lambda: {"count": 0, "pnl": 0.0, "wins": 0, "losses": 0})
        
        for pos in golden_hour_closed:
            symbol = pos.get("symbol", "unknown")
            pnl = float(pos.get("pnl", 0) or 0)
            symbol_stats[symbol]["count"] += 1
            symbol_stats[symbol]["pnl"] += pnl
            if pnl > 0:
                symbol_stats[symbol]["wins"] += 1
            elif pnl < 0:
                symbol_stats[symbol]["losses"] += 1
        
        # Group by strategy
        strategy_stats = defaultdict(lambda: {"count": 0, "pnl": 0.0, "wins": 0, "losses": 0})
        
        for pos in golden_hour_closed:
            strategy = pos.get("strategy", "unknown")
            pnl = float(pos.get("pnl", 0) or 0)
            strategy_stats[strategy]["count"] += 1
            strategy_stats[strategy]["pnl"] += pnl
            if pnl > 0:
                strategy_stats[strategy]["wins"] += 1
            elif pnl < 0:
                strategy_stats[strategy]["losses"] += 1
        
        # Sample trades with snapshots
        sample_trades = []
        for pos in golden_hour_closed[-20:]:  # Last 20 golden hour trades
            if pos.get("volatility_snapshot"):
                snapshot = pos["volatility_snapshot"]
                sample_trades.append({
                    "symbol": pos.get("symbol", "unknown"),
                    "strategy": pos.get("strategy", "unknown"),
                    "opened_at": pos.get("opened_at") or pos.get("open_ts"),
                    "pnl": pos.get("pnl", 0),
                    "atr_14": snapshot.get("atr_14", 0),
                    "regime": snapshot.get("regime_at_entry", "unknown"),
                    "volume_24h": snapshot.get("volume_24h", 0),
                })
        
        return {
            "golden_hour_closed": golden_closed_stats,
            "non_golden_closed": non_golden_closed_stats,
            "golden_hour_open": golden_open_stats,
            "symbol_stats": dict(symbol_stats),
            "strategy_stats": dict(strategy_stats),
            "sample_trades": sample_trades,
            "total_golden_hour_trades": len(golden_hour_closed) + len(golden_hour_open),
        }
        
    except Exception as e:
        print(f"❌ Error analyzing trades: {e}")
        import traceback
        traceback.print_exc()
        return None


def generate_report(analysis):
    """Generate markdown report"""
    if not analysis:
        return "❌ No analysis data available"
    
    report = []
    report.append("# Golden Hour Trading Analysis")
    report.append("")
    report.append(f"**Generated:** {datetime.now(timezone.utc).isoformat()}")
    report.append("")
    report.append("## Summary")
    report.append("")
    report.append(f"- **Total Golden Hour Trades:** {analysis['total_golden_hour_trades']}")
    report.append(f"- **Closed Trades:** {analysis['golden_hour_closed']['count']}")
    report.append(f"- **Open Trades:** {analysis['golden_hour_open']['count']}")
    report.append("")
    
    # Closed trades stats
    gh = analysis['golden_hour_closed']
    ngh = analysis['non_golden_closed']
    
    report.append("## Closed Trades Performance")
    report.append("")
    report.append("### Golden Hour (09:00-16:00 UTC)")
    report.append("")
    report.append(f"- **Total Trades:** {gh['count']}")
    report.append(f"- **Wins:** {gh['wins']}")
    report.append(f"- **Losses:** {gh['losses']}")
    report.append(f"- **Win Rate:** {gh['win_rate']:.1f}%")
    report.append(f"- **Total P&L:** ${gh['total_pnl']:.2f}")
    report.append(f"- **Average P&L:** ${gh['avg_pnl']:.2f}")
    report.append(f"- **Enhanced Logging Coverage:** {gh['with_snapshots']}/{gh['count']} ({gh['snapshot_rate']:.1f}%)")
    report.append("")
    
    report.append("### Non-Golden Hour (Outside 09:00-16:00 UTC)")
    report.append("")
    report.append(f"- **Total Trades:** {ngh['count']}")
    report.append(f"- **Wins:** {ngh['wins']}")
    report.append(f"- **Losses:** {ngh['losses']}")
    report.append(f"- **Win Rate:** {ngh['win_rate']:.1f}%")
    report.append(f"- **Total P&L:** ${ngh['total_pnl']:.2f}")
    report.append(f"- **Average P&L:** ${ngh['avg_pnl']:.2f}")
    report.append(f"- **Enhanced Logging Coverage:** {ngh['with_snapshots']}/{ngh['count']} ({ngh['snapshot_rate']:.1f}%)")
    report.append("")
    
    # Performance comparison
    report.append("### Performance Comparison")
    report.append("")
    if gh['count'] > 0 and ngh['count'] > 0:
        win_rate_diff = gh['win_rate'] - ngh['win_rate']
        pnl_diff = gh['total_pnl'] - ngh['total_pnl']
        report.append(f"- **Win Rate Difference:** {win_rate_diff:+.1f}% (Golden Hour vs Non-Golden)")
        report.append(f"- **P&L Difference:** ${pnl_diff:+.2f} (Golden Hour vs Non-Golden)")
        report.append("")
    
    # Symbol breakdown
    if analysis['symbol_stats']:
        report.append("## Performance by Symbol (Golden Hour)")
        report.append("")
        report.append("| Symbol | Trades | Wins | Losses | Win Rate | Total P&L | Avg P&L |")
        report.append("|--------|--------|------|--------|----------|-----------|---------|")
        
        for symbol, stats in sorted(analysis['symbol_stats'].items(), key=lambda x: x[1]['count'], reverse=True):
            count = stats['count']
            wins = stats['wins']
            losses = stats['losses']
            win_rate = (wins / count * 100) if count > 0 else 0.0
            total_pnl = stats['pnl']
            avg_pnl = total_pnl / count if count > 0 else 0.0
            report.append(f"| {symbol} | {count} | {wins} | {losses} | {win_rate:.1f}% | ${total_pnl:.2f} | ${avg_pnl:.2f} |")
        
        report.append("")
    
    # Strategy breakdown
    if analysis['strategy_stats']:
        report.append("## Performance by Strategy (Golden Hour)")
        report.append("")
        report.append("| Strategy | Trades | Wins | Losses | Win Rate | Total P&L | Avg P&L |")
        report.append("|----------|--------|------|--------|----------|-----------|---------|")
        
        for strategy, stats in sorted(analysis['strategy_stats'].items(), key=lambda x: x[1]['count'], reverse=True):
            count = stats['count']
            wins = stats['wins']
            losses = stats['losses']
            win_rate = (wins / count * 100) if count > 0 else 0.0
            total_pnl = stats['pnl']
            avg_pnl = total_pnl / count if count > 0 else 0.0
            report.append(f"| {strategy} | {count} | {wins} | {losses} | {win_rate:.1f}% | ${total_pnl:.2f} | ${avg_pnl:.2f} |")
        
        report.append("")
    
    # Sample trades
    if analysis['sample_trades']:
        report.append("## Sample Golden Hour Trades (Last 20 with Snapshots)")
        report.append("")
        report.append("| Symbol | Strategy | Opened At | P&L | ATR | Regime | Volume 24h |")
        report.append("|--------|----------|-----------|-----|-----|--------|-----------|")
        
        for trade in analysis['sample_trades'][-20:]:
            opened_at = trade['opened_at']
            if isinstance(opened_at, (int, float)):
                opened_at = datetime.fromtimestamp(float(opened_at), tz=timezone.utc).isoformat()
            elif isinstance(opened_at, str):
                opened_at = opened_at[:19] if len(opened_at) > 19 else opened_at
            
            report.append(f"| {trade['symbol']} | {trade['strategy']} | {opened_at} | ${trade['pnl']:.2f} | {trade['atr_14']:.2f} | {trade['regime']} | {trade['volume_24h']:.0f} |")
        
        report.append("")
    
    report.append("## Enhanced Logging Status")
    report.append("")
    report.append("✅ Enhanced logging is capturing volatility snapshots for golden hour trades.")
    report.append(f"   - **Coverage:** {gh['with_snapshots']}/{gh['count']} trades ({gh['snapshot_rate']:.1f}%)")
    report.append("")
    
    return "\n".join(report)


def main():
    """Main execution"""
    print("=" * 80)
    print("GOLDEN HOUR TRADE ANALYSIS")
    print("=" * 80)
    print("Analyzing trades during golden hour (09:00-16:00 UTC)...")
    print("")
    
    analysis = analyze_golden_hour_trades()
    
    if not analysis:
        print("❌ Failed to analyze trades")
        return 1
    
    # Generate report
    report = generate_report(analysis)
    
    # Save report
    report_file = Path("GOLDEN_HOUR_ANALYSIS.md")
    report_file.write_text(report)
    
    # Save JSON data
    json_file = Path("GOLDEN_HOUR_ANALYSIS.json")
    json_file.write_text(json.dumps(analysis, indent=2, default=str))
    
    print("✅ Analysis complete!")
    print("")
    print(f"📄 Markdown report: {report_file}")
    print(f"📊 JSON data: {json_file}")
    print("")
    
    # Print summary
    gh = analysis['golden_hour_closed']
    print("=" * 80)
    print("QUICK SUMMARY")
    print("=" * 80)
    print(f"Golden Hour Closed Trades: {gh['count']}")
    print(f"  Win Rate: {gh['win_rate']:.1f}%")
    print(f"  Total P&L: ${gh['total_pnl']:.2f}")
    print(f"  Enhanced Logging: {gh['with_snapshots']}/{gh['count']} ({gh['snapshot_rate']:.1f}%)")
    print("=" * 80)
    
    return 0


if __name__ == "__main__":
    sys.exit(main())

