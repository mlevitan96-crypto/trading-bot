# src/desk_grade_analysis_harness.py
#
# Desk-grade analysis harness for trading performance review
# Purpose:
#   - Analyze execution and signal data to identify patterns
#   - Generate actionable recommendations
#   - Produce professional-grade digest for review
#
import json
from typing import List, Dict, Any
from collections import defaultdict
from statistics import mean, stdev

def analyze(exec_rows: List[Dict[str,Any]], sig_rows: List[Dict[str,Any]]) -> Dict[str,Any]:
    """
    Comprehensive analysis of trading execution and signals.
    Returns summary dict with metrics and recommendations.
    """
    summary = {
        "execution_analysis": _analyze_execution(exec_rows),
        "signal_analysis": _analyze_signals(sig_rows),
        "recommendations": []
    }
    
    # Generate recommendations based on analysis
    summary["recommendations"] = _generate_recommendations(summary)
    
    return summary

def _analyze_execution(exec_rows: List[Dict[str,Any]]) -> Dict[str,Any]:
    """Analyze execution quality, fees, slippage, timing."""
    if not exec_rows:
        return {"total_trades": 0, "message": "No execution data available"}
    
    by_symbol = defaultdict(lambda: {"trades": 0, "fees": [], "slippage": [], "pnl": [], "durations": []})
    instant_closes = 0
    
    for trade in exec_rows:
        symbol = trade.get("symbol")
        if not symbol:
            continue
            
        by_symbol[symbol]["trades"] += 1
        by_symbol[symbol]["fees"].append(float(trade.get("fees", 0)))
        by_symbol[symbol]["slippage"].append(float(trade.get("slippage", trade.get("est_slippage", 0))))
        by_symbol[symbol]["pnl"].append(float(trade.get("gross_profit", 0)) - float(trade.get("fees", 0)))
        
        # Check for instant closes (<1 second)
        entry_ts = trade.get("entry_ts", 0)
        exit_ts = trade.get("exit_ts", 0)
        if exit_ts and entry_ts:
            duration = exit_ts - entry_ts
            by_symbol[symbol]["durations"].append(duration)
            if duration < 1:
                instant_closes += 1
    
    # Aggregate metrics
    symbol_stats = {}
    for symbol, data in by_symbol.items():
        symbol_stats[symbol] = {
            "trades": data["trades"],
            "avg_fee": round(mean(data["fees"]) if data["fees"] else 0, 4),
            "avg_slippage": round(mean(data["slippage"]) if data["slippage"] else 0, 6),
            "net_pnl": round(sum(data["pnl"]), 2),
            "win_rate": round(sum(1 for p in data["pnl"] if p > 0) / len(data["pnl"]) * 100, 2) if data["pnl"] else 0,
            "avg_duration_sec": round(mean(data["durations"]), 1) if data["durations"] else 0
        }
    
    return {
        "total_trades": len(exec_rows),
        "instant_closes": instant_closes,
        "instant_close_rate": round(instant_closes / len(exec_rows) * 100, 2) if exec_rows else 0,
        "by_symbol": symbol_stats
    }

def _analyze_signals(sig_rows: List[Dict[str,Any]]) -> Dict[str,Any]:
    """Analyze signal quality, direction distribution, strength."""
    if not sig_rows:
        return {"total_signals": 0, "message": "No signal data available"}
    
    by_side = defaultdict(int)
    by_strategy = defaultdict(int)
    strengths = []
    inversions = 0
    
    for sig in sig_rows:
        side = sig.get("side", "").upper()
        strategy = sig.get("strategy_id", "unknown")
        strength = sig.get("strength", 0)
        overlays = sig.get("overlays", [])
        
        by_side[side] += 1
        by_strategy[strategy] += 1
        strengths.append(float(strength))
        
        if "short_inversion_overlay" in overlays:
            inversions += 1
    
    return {
        "total_signals": len(sig_rows),
        "by_side": dict(by_side),
        "by_strategy": dict(by_strategy),
        "avg_strength": round(mean(strengths), 4) if strengths else 0,
        "inversions": inversions,
        "inversion_rate": round(inversions / len(sig_rows) * 100, 2) if sig_rows else 0
    }

def _generate_recommendations(summary: Dict[str,Any]) -> List[str]:
    """Generate actionable recommendations based on analysis."""
    recs = []
    
    exec_analysis = summary.get("execution_analysis", {})
    sig_analysis = summary.get("signal_analysis", {})
    
    # Check for instant close problem
    instant_close_rate = exec_analysis.get("instant_close_rate", 0)
    if instant_close_rate > 50:
        recs.append(f"⚠️ CRITICAL: {instant_close_rate}% instant closes detected - grace window protection needed")
    elif instant_close_rate > 10:
        recs.append(f"⚠️ WARNING: {instant_close_rate}% instant closes - review risk engine timing")
    
    # Check for signal inversion effectiveness
    inversion_rate = sig_analysis.get("inversion_rate", 0)
    if inversion_rate > 30:
        recs.append(f"✅ Signal inversion active ({inversion_rate}% of signals) - monitor profitability impact")
    
    # Check for high-fee symbols
    by_symbol = exec_analysis.get("by_symbol", {})
    high_fee_symbols = [sym for sym, stats in by_symbol.items() if stats.get("avg_fee", 0) > 1.0]
    if high_fee_symbols:
        recs.append(f"💰 High-fee symbols detected: {', '.join(high_fee_symbols)} - consider quarantine or downsize")
    
    # Check for low win rate symbols
    low_wr_symbols = [sym for sym, stats in by_symbol.items() if stats.get("win_rate", 0) < 35 and stats.get("trades", 0) > 10]
    if low_wr_symbols:
        recs.append(f"📉 Low win rate symbols (<35%): {', '.join(low_wr_symbols)} - review strategy fit")
    
    # Check for profitable symbols
    profitable_symbols = [sym for sym, stats in by_symbol.items() if stats.get("net_pnl", 0) > 0 and stats.get("trades", 0) > 10]
    if profitable_symbols:
        recs.append(f"✅ Profitable symbols: {', '.join(profitable_symbols)} - consider increasing allocation")
    
    if not recs:
        recs.append("✅ No critical issues detected - system operating nominally")
    
    return recs

def build_digest(summary: Dict[str,Any]) -> str:
    """Build human-readable digest from analysis summary."""
    lines = []
    lines.append("=" * 80)
    lines.append("TRADING ANALYSIS DIGEST")
    lines.append("=" * 80)
    lines.append("")
    
    # Execution Analysis
    exec_analysis = summary.get("execution_analysis", {})
    lines.append("📊 EXECUTION ANALYSIS")
    lines.append("-" * 80)
    lines.append(f"Total Trades: {exec_analysis.get('total_trades', 0)}")
    lines.append(f"Instant Closes: {exec_analysis.get('instant_closes', 0)} ({exec_analysis.get('instant_close_rate', 0)}%)")
    lines.append("")
    
    by_symbol = exec_analysis.get("by_symbol", {})
    if by_symbol:
        lines.append("By Symbol:")
        for symbol, stats in sorted(by_symbol.items(), key=lambda x: x[1].get("net_pnl", 0), reverse=True):
            lines.append(f"  {symbol:12} | Trades: {stats['trades']:4} | Win Rate: {stats['win_rate']:5.1f}% | "
                        f"Net P&L: ${stats['net_pnl']:8.2f} | Avg Fee: ${stats['avg_fee']:5.2f} | "
                        f"Avg Duration: {stats['avg_duration_sec']:6.1f}s")
    lines.append("")
    
    # Signal Analysis
    sig_analysis = summary.get("signal_analysis", {})
    lines.append("🎯 SIGNAL ANALYSIS")
    lines.append("-" * 80)
    lines.append(f"Total Signals: {sig_analysis.get('total_signals', 0)}")
    lines.append(f"Signal Inversions: {sig_analysis.get('inversions', 0)} ({sig_analysis.get('inversion_rate', 0)}%)")
    lines.append(f"Average Strength: {sig_analysis.get('avg_strength', 0):.4f}")
    lines.append("")
    
    by_side = sig_analysis.get("by_side", {})
    if by_side:
        lines.append("By Direction:")
        for side, count in sorted(by_side.items(), key=lambda x: x[1], reverse=True):
            lines.append(f"  {side:10} | {count:4} signals")
    lines.append("")
    
    # Recommendations
    recs = summary.get("recommendations", [])
    lines.append("💡 RECOMMENDATIONS")
    lines.append("-" * 80)
    for rec in recs:
        lines.append(f"  {rec}")
    lines.append("")
    lines.append("=" * 80)
    
    return "\n".join(lines)
