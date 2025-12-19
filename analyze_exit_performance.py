#!/usr/bin/env python3
"""
Comprehensive Exit Performance Analysis
========================================
Analyzes recent exits to identify:
1. Trades that exited too early (could have made more profit)
2. Trades that exited too late (gave back profits)
3. Average MFE capture rates
4. Exit learning effectiveness
5. Recommended profit target adjustments
"""

import os
import sys
import json
from datetime import datetime, timedelta
from collections import defaultdict
from typing import Dict, List, Any
from pathlib import Path

# Add project root to path
PROJECT_ROOT = Path(__file__).parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.infrastructure.path_registry import PathRegistry
from src.data_registry import DataRegistry as DR

def load_closed_positions() -> List[Dict]:
    """Load all closed positions for analysis."""
    try:
        return DR.get_closed_positions(hours=None)
    except Exception as e:
        print(f"Error loading positions: {e}")
        return []

def analyze_exit_performance() -> Dict[str, Any]:
    """Comprehensive analysis of exit performance."""
    print("=" * 70)
    print("EXIT PERFORMANCE ANALYSIS")
    print("=" * 70)
    print()
    
    closed_positions = load_closed_positions()
    
    if not closed_positions:
        print("⚠️  No closed positions found for analysis")
        return {}
    
    print(f"📊 Analyzing {len(closed_positions)} closed positions...\n")
    
    # Load exit runtime events for detailed analysis
    exit_events = []
    exit_log_path = PathRegistry.get_path("logs", "exit_runtime_events.jsonl")
    if os.path.exists(exit_log_path):
        with open(exit_log_path, 'r') as f:
            for line in f:
                try:
                    event = json.loads(line.strip())
                    exit_events.append(event)
                except:
                    continue
    
    # Analysis buckets
    analysis = {
        "total_trades": len(closed_positions),
        "by_exit_reason": defaultdict(lambda: {"count": 0, "total_pnl": 0.0, "avg_pnl": 0.0, "profitable": 0, "losing": 0}),
        "profit_target_exits": [],
        "time_stop_exits": [],
        "trailing_stop_exits": [],
        "stop_loss_exits": [],
        "early_exits": [],  # Profitable but could have been better
        "late_exits": [],  # Gave back profits
        "optimal_exits": [],
        "mfe_analysis": {
            "high_mfe_low_capture": [],  # Positions that reached high profit but we didn't capture it
            "low_mfe_high_capture": []   # Positions we exited well
        },
        "recommendations": []
    }
    
    # Analyze each closed position
    for pos in closed_positions:
        symbol = pos.get("symbol", "UNKNOWN")
        entry_price = float(pos.get("entry_price", 0) or 0)
        exit_price = float(pos.get("exit_price", 0) or 0)
        direction = pos.get("direction", "LONG")
        pnl = float(pos.get("pnl", 0) or 0)
        net_pnl = float(pos.get("net_pnl", pnl) or 0)
        reason = pos.get("exit_reason", "unknown")
        closed_at = pos.get("closed_at")
        
        if not entry_price or not exit_price:
            continue
        
        # Calculate ROI
        if direction.upper() == "LONG":
            roi_pct = ((exit_price - entry_price) / entry_price) * 100
        else:
            roi_pct = ((entry_price - exit_price) / entry_price) * 100
        
        # Categorize exit reason
        exit_type = "unknown"
        if "profit_target" in reason.lower():
            exit_type = "profit_target"
            analysis["profit_target_exits"].append({
                "symbol": symbol,
                "pnl": net_pnl,
                "roi_pct": roi_pct,
                "reason": reason,
                "closed_at": closed_at
            })
        elif "time" in reason.lower() or "stagnant" in reason.lower():
            exit_type = "time_stop"
            analysis["time_stop_exits"].append({
                "symbol": symbol,
                "pnl": net_pnl,
                "roi_pct": roi_pct,
                "reason": reason,
                "closed_at": closed_at
            })
        elif "trailing" in reason.lower() or "trail" in reason.lower():
            exit_type = "trailing_stop"
            analysis["trailing_stop_exits"].append({
                "symbol": symbol,
                "pnl": net_pnl,
                "roi_pct": roi_pct,
                "reason": reason,
                "closed_at": closed_at
            })
        elif "stop" in reason.lower() or "loss" in reason.lower():
            exit_type = "stop_loss"
            analysis["stop_loss_exits"].append({
                "symbol": symbol,
                "pnl": net_pnl,
                "roi_pct": roi_pct,
                "reason": reason,
                "closed_at": closed_at
            })
        
        # Categorize by exit reason for statistics
        reason_bucket = analysis["by_exit_reason"][exit_type]
        reason_bucket["count"] += 1
        reason_bucket["total_pnl"] += net_pnl
        if net_pnl > 0:
            reason_bucket["profitable"] += 1
        else:
            reason_bucket["losing"] += 1
        
        # Identify early exits (profitable but could have made more)
        # Check if there's a peak_price that's significantly higher than exit
        peak_price = pos.get("peak_price")
        if peak_price and entry_price > 0:
            peak_roi = ((peak_price - entry_price) / entry_price * 100) if direction == "LONG" else ((entry_price - peak_price) / entry_price * 100)
            if peak_roi > roi_pct + 1.0 and net_pnl > 0:  # Peak was >1% better, and we were profitable
                missed_profit = (peak_roi - roi_pct) * (pos.get("size", 0) or 0) / 100  # Estimate missed profit
                analysis["early_exits"].append({
                    "symbol": symbol,
                    "entry": entry_price,
                    "exit": exit_price,
                    "peak": peak_price,
                    "roi_captured": roi_pct,
                    "roi_peak": peak_roi,
                    "missed_pct": peak_roi - roi_pct,
                    "missed_profit_usd": missed_profit,
                    "reason": reason,
                    "closed_at": closed_at
                })
        
        # Identify late exits (gave back profits)
        if net_pnl < 0 and peak_price and peak_price != entry_price:
            if direction == "LONG" and peak_price > exit_price:
                gave_back = ((peak_price - exit_price) / entry_price) * 100
                if gave_back > 0.5:  # Gave back >0.5%
                    analysis["late_exits"].append({
                        "symbol": symbol,
                        "entry": entry_price,
                        "exit": exit_price,
                        "peak": peak_price,
                        "final_roi": roi_pct,
                        "peak_roi": ((peak_price - entry_price) / entry_price * 100),
                        "gave_back_pct": gave_back,
                        "reason": reason,
                        "closed_at": closed_at
                    })
    
    # Calculate averages
    for exit_type, stats in analysis["by_exit_reason"].items():
        if stats["count"] > 0:
            stats["avg_pnl"] = stats["total_pnl"] / stats["count"]
            stats["win_rate"] = (stats["profitable"] / stats["count"]) * 100
    
    # Analyze exit events for MFE/MAE data
    if exit_events:
        profit_target_events = [e for e in exit_events if "profit_target" in str(e.get("exit_type", "")) or "profit_target" in str(e.get("reason", ""))]
        time_stop_events = [e for e in exit_events if e.get("exit_type") == "time_stop"]
        
        if profit_target_events:
            avg_profit_target_pnl = sum(e.get("pnl_usd", 0) or 0 for e in profit_target_events) / len(profit_target_events)
            profit_target_wr = (sum(1 for e in profit_target_events if e.get("was_profitable", False)) / len(profit_target_events)) * 100
            analysis["profit_target_stats"] = {
                "count": len(profit_target_events),
                "avg_pnl": avg_profit_target_pnl,
                "win_rate": profit_target_wr
            }
        
        if time_stop_events:
            avg_time_stop_pnl = sum(e.get("pnl_usd", 0) or 0 for e in time_stop_events) / len(time_stop_events)
            time_stop_wr = (sum(1 for e in time_stop_events if e.get("was_profitable", False)) / len(time_stop_events)) * 100
            analysis["time_stop_stats"] = {
                "count": len(time_stop_events),
                "avg_pnl": avg_time_stop_pnl,
                "win_rate": time_stop_wr
            }
    
    # Generate recommendations
    recommendations = []
    
    # Recommendation 1: If too many time_stops vs profit_targets
    profit_target_count = len(analysis["profit_target_exits"])
    time_stop_count = len(analysis["time_stop_exits"])
    total_exits = profit_target_count + time_stop_count + len(analysis["trailing_stop_exits"]) + len(analysis["stop_loss_exits"])
    
    if total_exits > 0:
        profit_target_rate = (profit_target_count / total_exits) * 100
        time_stop_rate = (time_stop_count / total_exits) * 100
        
        if time_stop_rate > 40:
            recommendations.append({
                "priority": "HIGH",
                "issue": f"Too many time_stop exits ({time_stop_rate:.1f}%) vs profit targets ({profit_target_rate:.1f}%)",
                "recommendation": "Lower profit targets (0.5% → 0.3%, 1.0% → 0.8%) to capture profits before time limits",
                "action": "Reduce profit target thresholds by 20-30% to exit earlier"
            })
        
        if profit_target_rate > 0:
            avg_profit_target_pnl = sum(t["pnl"] for t in analysis["profit_target_exits"]) / profit_target_count
            if avg_profit_target_pnl > 0 and avg_profit_target_pnl < 10:  # Profitable but small
                recommendations.append({
                    "priority": "MEDIUM",
                    "issue": f"Profit targets are working but average profit is small (${avg_profit_target_pnl:.2f})",
                    "recommendation": "Consider slightly higher targets (0.6% instead of 0.5%) to capture more per trade",
                    "action": "Gradually increase profit targets if win rate remains high"
                })
    
    # Recommendation 2: Early exits (missed profit)
    if len(analysis["early_exits"]) > 0:
        avg_missed = sum(e["missed_pct"] for e in analysis["early_exits"]) / len(analysis["early_exits"])
        if avg_missed > 1.0:  # Average >1% missed
            recommendations.append({
                "priority": "MEDIUM",
                "issue": f"Found {len(analysis['early_exits'])} trades that exited early, missing avg {avg_missed:.2f}% profit",
                "recommendation": "Consider adding trailing stops or hold extended logic for strong moves",
                "action": "Enable 'LET IT RUN' logic for positions with strong alignment + momentum"
            })
    
    # Recommendation 3: Late exits (gave back profits)
    if len(analysis["late_exits"]) > 0:
        avg_gave_back = sum(e["gave_back_pct"] for e in analysis["late_exits"]) / len(analysis["late_exits"])
        recommendations.append({
            "priority": "HIGH",
            "issue": f"Found {len(analysis['late_exits'])} trades that gave back avg {avg_gave_back:.2f}% profit",
            "recommendation": "Tighten trailing stops or lower profit targets to lock in gains sooner",
            "action": "Reduce profit targets by 0.1-0.2% to exit earlier and protect gains"
        })
    
    analysis["recommendations"] = recommendations
    
    return analysis

def print_analysis_report(analysis: Dict[str, Any]):
    """Print formatted analysis report."""
    print("=" * 70)
    print("EXIT PERFORMANCE SUMMARY")
    print("=" * 70)
    print()
    
    print(f"📊 Total Trades Analyzed: {analysis['total_trades']}\n")
    
    # Exit reason breakdown
    print("EXIT TYPE BREAKDOWN:")
    print("-" * 70)
    for exit_type, stats in sorted(analysis["by_exit_reason"].items(), key=lambda x: x[1]["count"], reverse=True):
        wr = stats["win_rate"]
        wr_color = "✅" if wr > 50 else "⚠️" if wr > 30 else "❌"
        print(f"  {exit_type:20s}: {stats['count']:4d} exits | "
              f"Avg P&L: ${stats['avg_pnl']:8.2f} | "
              f"Win Rate: {wr_color} {wr:5.1f}% | "
              f"Total P&L: ${stats['total_pnl']:10.2f}")
    print()
    
    # Profit target vs time stop comparison
    if "profit_target_stats" in analysis:
        pt = analysis["profit_target_stats"]
        print("PROFIT TARGET EXITS:")
        print(f"  Count: {pt['count']}")
        print(f"  Average P&L: ${pt['avg_pnl']:.2f}")
        print(f"  Win Rate: {pt['win_rate']:.1f}%")
        print()
    
    if "time_stop_stats" in analysis:
        ts = analysis["time_stop_stats"]
        print("TIME STOP EXITS:")
        print(f"  Count: {ts['count']}")
        print(f"  Average P&L: ${ts['avg_pnl']:.2f}")
        print(f"  Win Rate: {ts['win_rate']:.1f}%")
        print()
    
    # Early exits (missed profit)
    if analysis["early_exits"]:
        print(f"⚠️  EARLY EXITS (Missed Profit Opportunities): {len(analysis['early_exits'])} trades")
        print("-" * 70)
        for i, exit in enumerate(analysis["early_exits"][:5], 1):  # Top 5
            print(f"  {i}. {exit['symbol']:10s}: Captured {exit['roi_captured']:5.2f}% | "
                  f"Peak was {exit['roi_peak']:5.2f}% | "
                  f"Missed {exit['missed_pct']:5.2f}% (~${exit['missed_profit_usd']:.2f})")
        print()
    
    # Late exits (gave back profit)
    if analysis["late_exits"]:
        print(f"❌ LATE EXITS (Gave Back Profit): {len(analysis['late_exits'])} trades")
        print("-" * 70)
        for i, exit in enumerate(analysis["late_exits"][:5], 1):  # Top 5
            print(f"  {i}. {exit['symbol']:10s}: Final ROI {exit['final_roi']:6.2f}% | "
                  f"Peak was {exit['peak_roi']:6.2f}% | "
                  f"Gave back {exit['gave_back_pct']:5.2f}%")
        print()
    
    # Recommendations
    if analysis["recommendations"]:
        print("RECOMMENDATIONS:")
        print("-" * 70)
        for i, rec in enumerate(analysis["recommendations"], 1):
            priority_icon = "🔴" if rec["priority"] == "HIGH" else "🟡" if rec["priority"] == "MEDIUM" else "🟢"
            print(f"\n{priority_icon} {rec['priority']} PRIORITY")
            print(f"   Issue: {rec['issue']}")
            print(f"   Recommendation: {rec['recommendation']}")
            print(f"   Action: {rec['action']}")
        print()
    
    print("=" * 70)

if __name__ == "__main__":
    try:
        analysis = analyze_exit_performance()
        print_analysis_report(analysis)
        
        # Save detailed report
        report_path = PathRegistry.get_path("reports", "exit_performance_analysis.json")
        os.makedirs(os.path.dirname(report_path), exist_ok=True)
        with open(report_path, 'w') as f:
            json.dump(analysis, f, indent=2, default=str)
        
        print(f"\n✅ Detailed report saved to: {report_path}")
        
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
