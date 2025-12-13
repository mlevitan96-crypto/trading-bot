#!/usr/bin/env python3
"""
Condition Analysis - Understanding WHEN LONG vs SHORT works

Instead of blocking directions, this analyzes what market conditions
correlate with successful trades in each direction.

Key questions:
1. What OFI ranges lead to profitable LONGs vs SHORTs?
2. What volatility levels favor each direction?
3. How does market intelligence alignment affect outcomes?
4. What time patterns exist?

Usage:
    python src/condition_analysis.py
"""

import json
import os
from datetime import datetime
from collections import defaultdict
from pathlib import Path

ENRICHED_LOG = "logs/enriched_decisions.jsonl"
ALPHA_TRADES_LOG = "logs/alpha_trades.jsonl"


def load_jsonl(path, limit=None):
    """Load JSONL file with optional limit."""
    records = []
    if not os.path.exists(path):
        return records
    try:
        with open(path, 'r') as f:
            for i, line in enumerate(f):
                if limit and i >= limit:
                    break
                try:
                    records.append(json.loads(line.strip()))
                except:
                    continue
    except:
        pass
    return records


def analyze_ofi_vs_direction():
    """Analyze what OFI ranges work for each direction."""
    print("\n" + "="*70)
    print("📊 OFI RANGES VS DIRECTION SUCCESS")
    print("="*70)
    print("\nQuestion: What OFI values lead to profitable trades?")
    
    enriched = load_jsonl(ENRICHED_LOG)
    
    ofi_ranges = [
        (0.0, 0.3, "Weak (0-0.3)"),
        (0.3, 0.5, "Moderate (0.3-0.5)"),
        (0.5, 0.7, "Strong (0.5-0.7)"),
        (0.7, 0.9, "Very Strong (0.7-0.9)"),
        (0.9, 2.0, "Extreme (0.9+)")
    ]
    
    results = defaultdict(lambda: {"long_wins": 0, "long_losses": 0, "short_wins": 0, "short_losses": 0})
    
    for record in enriched:
        ctx = record.get("signal_ctx", {})
        outcome = record.get("outcome", {})
        
        ofi = abs(ctx.get("ofi", 0))
        side = ctx.get("side", "").upper()
        pnl = outcome.get("pnl_usd", 0)
        
        for low, high, label in ofi_ranges:
            if low <= ofi < high:
                if side == "LONG":
                    if pnl > 0:
                        results[label]["long_wins"] += 1
                    else:
                        results[label]["long_losses"] += 1
                elif side == "SHORT":
                    if pnl > 0:
                        results[label]["short_wins"] += 1
                    else:
                        results[label]["short_losses"] += 1
                break
    
    print(f"\n{'OFI Range':<20} {'LONG WR%':>10} {'LONG N':>8} {'SHORT WR%':>11} {'SHORT N':>9}")
    print("-"*60)
    
    insights = []
    
    for low, high, label in ofi_ranges:
        stats = results[label]
        long_total = stats["long_wins"] + stats["long_losses"]
        short_total = stats["short_wins"] + stats["short_losses"]
        
        long_wr = (stats["long_wins"] / long_total * 100) if long_total > 0 else 0
        short_wr = (stats["short_wins"] / short_total * 100) if short_total > 0 else 0
        
        l_icon = "🟢" if long_wr >= 40 else "🔴"
        s_icon = "🟢" if short_wr >= 40 else "🔴"
        
        print(f"{label:<20} {l_icon}{long_wr:>8.1f}% {long_total:>8} {s_icon}{short_wr:>9.1f}% {short_total:>9}")
        
        if long_wr >= 40 and long_total >= 5:
            insights.append(f"✅ LONG works well in {label} OFI range ({long_wr:.1f}% WR)")
        if short_wr >= 40 and short_total >= 5:
            insights.append(f"✅ SHORT works well in {label} OFI range ({short_wr:.1f}% WR)")
    
    return insights


def analyze_ofi_direction_alignment():
    """Analyze when OFI direction matches trade direction."""
    print("\n" + "="*70)
    print("📊 OFI DIRECTION ALIGNMENT")
    print("="*70)
    print("\nQuestion: Do trades work better when OFI direction matches trade direction?")
    
    enriched = load_jsonl(ENRICHED_LOG)
    
    aligned = {"wins": 0, "losses": 0, "pnl": 0}
    misaligned = {"wins": 0, "losses": 0, "pnl": 0}
    
    for record in enriched:
        ctx = record.get("signal_ctx", {})
        outcome = record.get("outcome", {})
        
        ofi = ctx.get("ofi", 0)
        side = ctx.get("side", "").upper()
        pnl = outcome.get("pnl_usd", 0)
        
        ofi_direction = "LONG" if ofi > 0 else "SHORT"
        is_aligned = (ofi_direction == side)
        
        if is_aligned:
            aligned["pnl"] += pnl
            if pnl > 0:
                aligned["wins"] += 1
            else:
                aligned["losses"] += 1
        else:
            misaligned["pnl"] += pnl
            if pnl > 0:
                misaligned["wins"] += 1
            else:
                misaligned["losses"] += 1
    
    aligned_total = aligned["wins"] + aligned["losses"]
    misaligned_total = misaligned["wins"] + misaligned["losses"]
    
    aligned_wr = (aligned["wins"] / aligned_total * 100) if aligned_total > 0 else 0
    misaligned_wr = (misaligned["wins"] / misaligned_total * 100) if misaligned_total > 0 else 0
    
    print(f"\n{'Type':<25} {'Trades':>8} {'Win Rate':>10} {'Total P&L':>12}")
    print("-"*57)
    
    a_icon = "🟢" if aligned["pnl"] > 0 else "🔴"
    m_icon = "🟢" if misaligned["pnl"] > 0 else "🔴"
    
    print(f"{'OFI-Aligned (same dir)':<25} {aligned_total:>8} {aligned_wr:>9.1f}% {a_icon}{aligned['pnl']:>10.2f}")
    print(f"{'OFI-Contrary (opp dir)':<25} {misaligned_total:>8} {misaligned_wr:>9.1f}% {m_icon}{misaligned['pnl']:>10.2f}")
    
    insights = []
    if aligned_wr > misaligned_wr + 5:
        insights.append(f"✅ OFI-aligned trades perform better ({aligned_wr:.1f}% vs {misaligned_wr:.1f}%)")
    elif misaligned_wr > aligned_wr + 5:
        insights.append(f"⚠️ Contrary trades actually perform better ({misaligned_wr:.1f}% vs {aligned_wr:.1f}%) - contrarian edge?")
    
    return insights


def analyze_symbol_conditions():
    """Analyze what conditions work for each symbol."""
    print("\n" + "="*70)
    print("📊 SYMBOL-SPECIFIC CONDITION PATTERNS")
    print("="*70)
    print("\nQuestion: What OFI threshold optimizes each symbol/direction?")
    
    enriched = load_jsonl(ENRICHED_LOG)
    
    symbol_data = defaultdict(lambda: {"long": [], "short": []})
    
    for record in enriched:
        ctx = record.get("signal_ctx", {})
        outcome = record.get("outcome", {})
        symbol = record.get("symbol", "")
        
        ofi = abs(ctx.get("ofi", 0))
        side = ctx.get("side", "").upper()
        pnl = outcome.get("pnl_usd", 0)
        
        if side in ["LONG", "SHORT"]:
            symbol_data[symbol][side.lower()].append({"ofi": ofi, "pnl": pnl})
    
    recommendations = {}
    
    print(f"\n{'Symbol':<12} {'Dir':<7} {'Best OFI≥':>10} {'WR%':>8} {'Avg P&L':>10} {'Trades':>8}")
    print("-"*60)
    
    for symbol in sorted(symbol_data.keys()):
        for direction in ["long", "short"]:
            trades = symbol_data[symbol][direction]
            if len(trades) < 5:
                continue
            
            best_thresh = 0.3
            best_wr = 0
            best_pnl = -999
            best_n = 0
            
            for thresh in [0.3, 0.4, 0.5, 0.6, 0.7, 0.8]:
                filtered = [t for t in trades if t["ofi"] >= thresh]
                if len(filtered) < 3:
                    continue
                
                wins = sum(1 for t in filtered if t["pnl"] > 0)
                wr = wins / len(filtered)
                avg_pnl = sum(t["pnl"] for t in filtered) / len(filtered)
                
                if wr > best_wr or (wr == best_wr and avg_pnl > best_pnl):
                    best_wr = wr
                    best_pnl = avg_pnl
                    best_thresh = thresh
                    best_n = len(filtered)
            
            if best_n >= 3:
                icon = "🟢" if best_wr >= 0.4 else "🔴"
                print(f"{symbol:<12} {direction.upper():<7} {best_thresh:>10.2f} {icon}{best_wr*100:>6.1f}% {best_pnl:>10.2f} {best_n:>8}")
                
                if best_wr >= 0.35:
                    if symbol not in recommendations:
                        recommendations[symbol] = {}
                    recommendations[symbol][direction] = {
                        "min_ofi": best_thresh,
                        "expected_wr": round(best_wr * 100, 1),
                        "expected_avg_pnl": round(best_pnl, 2)
                    }
    
    return recommendations


def analyze_ensemble_thresholds():
    """Analyze ensemble score vs outcomes."""
    print("\n" + "="*70)
    print("📊 ENSEMBLE SCORE THRESHOLDS")
    print("="*70)
    print("\nQuestion: What ensemble scores correlate with wins?")
    
    enriched = load_jsonl(ENRICHED_LOG)
    
    ranges = [
        (-0.1, 0.0, "Negative"),
        (0.0, 0.03, "Weak (0-0.03)"),
        (0.03, 0.06, "Moderate (0.03-0.06)"),
        (0.06, 0.10, "Strong (0.06-0.10)"),
        (0.10, 1.0, "Very Strong (0.10+)")
    ]
    
    results = defaultdict(lambda: {"wins": 0, "losses": 0, "pnl": 0})
    
    for record in enriched:
        ctx = record.get("signal_ctx", {})
        outcome = record.get("outcome", {})
        
        ensemble = abs(ctx.get("ensemble", 0))
        pnl = outcome.get("pnl_usd", 0)
        
        for low, high, label in ranges:
            if low <= ensemble < high:
                results[label]["pnl"] += pnl
                if pnl > 0:
                    results[label]["wins"] += 1
                else:
                    results[label]["losses"] += 1
                break
    
    print(f"\n{'Ensemble Range':<25} {'Trades':>8} {'Win Rate':>10} {'Total P&L':>12}")
    print("-"*57)
    
    for low, high, label in ranges:
        stats = results[label]
        total = stats["wins"] + stats["losses"]
        if total == 0:
            continue
        
        wr = (stats["wins"] / total * 100)
        icon = "🟢" if stats["pnl"] > 0 else "🔴"
        
        print(f"{label:<25} {total:>8} {wr:>9.1f}% {icon}{stats['pnl']:>10.2f}")


def generate_actionable_insights():
    """Generate actionable trading insights."""
    print("\n" + "="*70)
    print("💡 ACTIONABLE INSIGHTS")
    print("="*70)
    
    insights = []
    
    ofi_insights = analyze_ofi_vs_direction()
    insights.extend(ofi_insights)
    
    alignment_insights = analyze_ofi_direction_alignment()
    insights.extend(alignment_insights)
    
    symbol_recs = analyze_symbol_conditions()
    
    analyze_ensemble_thresholds()
    
    print("\n" + "="*70)
    print("🎯 RECOMMENDED CONFIGURATION CHANGES")
    print("="*70)
    
    if symbol_recs:
        print("\nPer-symbol OFI thresholds (apply to conditional overlay):")
        for symbol, dirs in symbol_recs.items():
            for direction, config in dirs.items():
                print(f"   {symbol} {direction.upper()}: OFI ≥ {config['min_ofi']:.2f} (expect {config['expected_wr']:.1f}% WR)")
    
    print("\n" + "-"*70)
    print("Key Takeaways:")
    for i, insight in enumerate(insights, 1):
        print(f"   {i}. {insight}")
    
    if not insights:
        print("   (Need more data to generate insights - continue trading)")
    
    report = {
        "timestamp": datetime.now().isoformat(),
        "symbol_recommendations": symbol_recs,
        "insights": insights
    }
    
    os.makedirs("reports", exist_ok=True)
    with open("reports/condition_analysis.json", "w") as f:
        json.dump(report, f, indent=2)
    
    print(f"\n✅ Report saved to reports/condition_analysis.json")
    
    return report


def main():
    print("\n" + "="*70)
    print("🔬 CONDITION ANALYSIS - Understanding WHEN directions work")
    print(f"   Timestamp: {datetime.now().isoformat()}")
    print("="*70)
    
    generate_actionable_insights()


if __name__ == "__main__":
    main()
