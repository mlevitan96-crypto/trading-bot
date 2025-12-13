#!/usr/bin/env python3
"""
Intelligence Backtesting & Learning Module

Analyzes historical trades against signals and market intelligence to:
1. Compare OFI signals vs actual outcomes
2. Analyze market intelligence accuracy vs price movements  
3. Find optimal thresholds for each symbol/direction
4. Identify patterns that would have improved performance
5. Generate actionable recommendations

Usage:
    python src/intelligence_backtest.py --full     # Full analysis
    python src/intelligence_backtest.py --quick    # Quick summary
"""

import json
import os
from datetime import datetime, timedelta
from collections import defaultdict
from pathlib import Path
import statistics

ENRICHED_LOG = "logs/enriched_decisions.jsonl"
ALPHA_TRADES_LOG = "logs/alpha_trades.jsonl"
INTEL_SUMMARY = "feature_store/intelligence/summary.json"
INTEL_HISTORY = "feature_store/intelligence/history.jsonl"
PORTFOLIO_LOG = "logs/portfolio.json"
BLOCKED_SIGNALS_LOG = "logs/blocked_signals.jsonl"


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


def load_json(path, default=None):
    """Load JSON file."""
    if not os.path.exists(path):
        return default or {}
    try:
        with open(path, 'r') as f:
            return json.load(f)
    except:
        return default or {}


class IntelligenceBacktest:
    """Backtests trading signals against historical outcomes."""
    
    def __init__(self):
        self.enriched = load_jsonl(ENRICHED_LOG)
        self.alpha_trades = load_jsonl(ALPHA_TRADES_LOG)
        self.intel_history = load_jsonl(INTEL_HISTORY)
        self.blocked = load_jsonl(BLOCKED_SIGNALS_LOG)
        self.portfolio = load_json(PORTFOLIO_LOG, {"trades": []})
        
    def analyze_ofi_signals(self):
        """Analyze OFI signal accuracy vs outcomes."""
        print("\n" + "="*70)
        print("📊 OFI SIGNAL ANALYSIS")
        print("="*70)
        
        results = defaultdict(lambda: {"trades": 0, "wins": 0, "pnl": 0, "ofi_sum": 0})
        
        for record in self.enriched:
            ctx = record.get("signal_ctx", {})
            outcome = record.get("outcome", {})
            
            symbol = record.get("symbol", "UNKNOWN")
            ofi = ctx.get("ofi", 0)
            side = ctx.get("side", "")
            pnl = outcome.get("pnl_usd", 0)
            
            if not side or ofi == 0:
                continue
            
            key = f"{symbol}_{side}"
            results[key]["trades"] += 1
            results[key]["pnl"] += pnl
            results[key]["ofi_sum"] += abs(ofi)
            if pnl > 0:
                results[key]["wins"] += 1
        
        print(f"\nFound {len(self.enriched)} enriched decisions\n")
        print(f"{'Symbol/Side':<20} {'Trades':>8} {'WR%':>8} {'P&L':>12} {'Avg OFI':>10}")
        print("-"*60)
        
        sorted_results = sorted(results.items(), key=lambda x: x[1]["pnl"], reverse=True)
        
        for key, stats in sorted_results[:20]:
            trades = stats["trades"]
            if trades == 0:
                continue
            wr = (stats["wins"] / trades) * 100
            pnl = stats["pnl"]
            avg_ofi = stats["ofi_sum"] / trades
            
            pnl_color = "🟢" if pnl > 0 else "🔴"
            print(f"{key:<20} {trades:>8} {wr:>7.1f}% {pnl_color}{pnl:>10.2f} {avg_ofi:>10.3f}")
        
        return dict(results)
    
    def analyze_ofi_thresholds(self):
        """Find optimal OFI thresholds per symbol."""
        print("\n" + "="*70)
        print("🎯 OFI THRESHOLD OPTIMIZATION")
        print("="*70)
        
        thresholds = [0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9]
        symbol_data = defaultdict(list)
        
        for record in self.enriched:
            ctx = record.get("signal_ctx", {})
            outcome = record.get("outcome", {})
            
            symbol = record.get("symbol", "UNKNOWN")
            ofi = abs(ctx.get("ofi", 0))
            pnl = outcome.get("pnl_usd", 0)
            
            if ofi > 0:
                symbol_data[symbol].append({"ofi": ofi, "pnl": pnl})
        
        recommendations = {}
        
        print(f"\n{'Symbol':<12} {'Best Thresh':>12} {'WR%':>8} {'Avg P&L':>10} {'Trades':>8}")
        print("-"*55)
        
        for symbol, trades in symbol_data.items():
            if len(trades) < 5:
                continue
            
            best_thresh = 0.5
            best_score = -999
            best_stats = {}
            
            for thresh in thresholds:
                filtered = [t for t in trades if t["ofi"] >= thresh]
                if len(filtered) < 3:
                    continue
                
                wins = sum(1 for t in filtered if t["pnl"] > 0)
                wr = wins / len(filtered) if filtered else 0
                avg_pnl = sum(t["pnl"] for t in filtered) / len(filtered)
                
                score = wr * 0.6 + (avg_pnl / 10) * 0.4
                
                if score > best_score:
                    best_score = score
                    best_thresh = thresh
                    best_stats = {"wr": wr * 100, "avg_pnl": avg_pnl, "trades": len(filtered)}
            
            if best_stats:
                recommendations[symbol] = {
                    "optimal_ofi_threshold": best_thresh,
                    **best_stats
                }
                print(f"{symbol:<12} {best_thresh:>12.2f} {best_stats['wr']:>7.1f}% {best_stats['avg_pnl']:>9.2f} {best_stats['trades']:>8}")
        
        return recommendations
    
    def analyze_direction_bias(self):
        """Analyze LONG vs SHORT performance per symbol."""
        print("\n" + "="*70)
        print("📈 DIRECTION BIAS ANALYSIS")
        print("="*70)
        
        direction_stats = defaultdict(lambda: {"LONG": {"trades": 0, "wins": 0, "pnl": 0},
                                                "SHORT": {"trades": 0, "wins": 0, "pnl": 0}})
        
        for record in self.enriched:
            ctx = record.get("signal_ctx", {})
            outcome = record.get("outcome", {})
            
            symbol = record.get("symbol", "UNKNOWN")
            side = ctx.get("side", "")
            pnl = outcome.get("pnl_usd", 0)
            
            if side in ["LONG", "SHORT"]:
                direction_stats[symbol][side]["trades"] += 1
                direction_stats[symbol][side]["pnl"] += pnl
                if pnl > 0:
                    direction_stats[symbol][side]["wins"] += 1
        
        print(f"\n{'Symbol':<12} {'LONG WR%':>10} {'LONG P&L':>12} {'SHORT WR%':>11} {'SHORT P&L':>12} {'Bias':>8}")
        print("-"*75)
        
        biases = {}
        
        for symbol, stats in sorted(direction_stats.items()):
            long_trades = stats["LONG"]["trades"]
            short_trades = stats["SHORT"]["trades"]
            
            if long_trades == 0 and short_trades == 0:
                continue
            
            long_wr = (stats["LONG"]["wins"] / long_trades * 100) if long_trades > 0 else 0
            short_wr = (stats["SHORT"]["wins"] / short_trades * 100) if short_trades > 0 else 0
            long_pnl = stats["LONG"]["pnl"]
            short_pnl = stats["SHORT"]["pnl"]
            
            if long_pnl > short_pnl and long_wr > short_wr:
                bias = "LONG"
            elif short_pnl > long_pnl and short_wr > long_wr:
                bias = "SHORT"
            else:
                bias = "MIXED"
            
            biases[symbol] = {
                "recommended_bias": bias,
                "long_wr": long_wr,
                "short_wr": short_wr,
                "long_pnl": long_pnl,
                "short_pnl": short_pnl
            }
            
            l_icon = "🟢" if long_pnl > 0 else "🔴"
            s_icon = "🟢" if short_pnl > 0 else "🔴"
            
            print(f"{symbol:<12} {long_wr:>9.1f}% {l_icon}{long_pnl:>10.2f} {short_wr:>10.1f}% {s_icon}{short_pnl:>10.2f} {bias:>8}")
        
        return biases
    
    def analyze_counterfactuals(self):
        """Analyze blocked signals - what would have happened?"""
        print("\n" + "="*70)
        print("🔮 COUNTERFACTUAL ANALYSIS (Blocked Signals)")
        print("="*70)
        
        if not self.blocked:
            print("\nNo blocked signals found for analysis.")
            print("   (Blocked signals are now being logged to logs/blocked_signals.jsonl)")
            return {}
        
        print(f"\nFound {len(self.blocked)} blocked signals to analyze")
        
        return {"blocked_count": len(self.blocked), "signals": self.blocked[:10]}
    
    def analyze_regime_performance(self):
        """Analyze performance by market regime."""
        print("\n" + "="*70)
        print("🌊 REGIME-BASED PERFORMANCE")
        print("="*70)
        
        regime_stats = defaultdict(lambda: {"trades": 0, "wins": 0, "pnl": 0})
        
        for record in self.enriched:
            ctx = record.get("signal_ctx", {})
            outcome = record.get("outcome", {})
            
            regime = ctx.get("regime", "Unknown")
            pnl = outcome.get("pnl_usd", 0)
            
            regime_stats[regime]["trades"] += 1
            regime_stats[regime]["pnl"] += pnl
            if pnl > 0:
                regime_stats[regime]["wins"] += 1
        
        print(f"\n{'Regime':<15} {'Trades':>8} {'WR%':>8} {'Total P&L':>12} {'Avg P&L':>10}")
        print("-"*55)
        
        for regime, stats in sorted(regime_stats.items(), key=lambda x: x[1]["pnl"], reverse=True):
            trades = stats["trades"]
            if trades == 0:
                continue
            wr = (stats["wins"] / trades) * 100
            pnl = stats["pnl"]
            avg_pnl = pnl / trades
            
            icon = "🟢" if pnl > 0 else "🔴"
            print(f"{regime:<15} {trades:>8} {wr:>7.1f}% {icon}{pnl:>10.2f} {avg_pnl:>10.2f}")
        
        return dict(regime_stats)
    
    def generate_recommendations(self):
        """Generate actionable recommendations based on analysis."""
        print("\n" + "="*70)
        print("💡 ACTIONABLE RECOMMENDATIONS")
        print("="*70)
        
        recommendations = []
        
        direction_bias = self.analyze_direction_bias()
        
        for symbol, bias_data in direction_bias.items():
            bias = bias_data["recommended_bias"]
            long_pnl = bias_data["long_pnl"]
            short_pnl = bias_data["short_pnl"]
            
            if bias == "LONG" and short_pnl < -20:
                recommendations.append({
                    "symbol": symbol,
                    "action": "DISABLE_SHORT",
                    "reason": f"SHORT trades losing ${abs(short_pnl):.2f}, LONG profitable",
                    "priority": "HIGH"
                })
            elif bias == "SHORT" and long_pnl < -20:
                recommendations.append({
                    "symbol": symbol,
                    "action": "DISABLE_LONG", 
                    "reason": f"LONG trades losing ${abs(long_pnl):.2f}, SHORT profitable",
                    "priority": "HIGH"
                })
        
        thresholds = self.analyze_ofi_thresholds()
        for symbol, data in thresholds.items():
            current_thresh = 0.5
            optimal = data["optimal_ofi_threshold"]
            
            if optimal > current_thresh + 0.1 and data["wr"] > 40:
                recommendations.append({
                    "symbol": symbol,
                    "action": "RAISE_OFI_THRESHOLD",
                    "from": current_thresh,
                    "to": optimal,
                    "reason": f"Higher threshold yields {data['wr']:.1f}% WR",
                    "priority": "MEDIUM"
                })
        
        print(f"\nGenerated {len(recommendations)} recommendations:\n")
        
        for i, rec in enumerate(recommendations[:10], 1):
            priority_icon = "🔴" if rec["priority"] == "HIGH" else "🟡"
            print(f"{i}. {priority_icon} [{rec['priority']}] {rec['symbol']}: {rec['action']}")
            print(f"   Reason: {rec['reason']}")
            print()
        
        return recommendations
    
    def run_full_analysis(self):
        """Run complete backtesting analysis."""
        print("\n" + "="*70)
        print("🔬 INTELLIGENCE BACKTESTING & LEARNING ANALYSIS")
        print(f"   Timestamp: {datetime.now().isoformat()}")
        print("="*70)
        
        self.analyze_ofi_signals()
        
        self.analyze_regime_performance()
        
        self.analyze_counterfactuals()
        
        recs = self.generate_recommendations()
        
        report = {
            "timestamp": datetime.now().isoformat(),
            "enriched_decisions": len(self.enriched),
            "alpha_trades": len(self.alpha_trades),
            "blocked_signals": len(self.blocked),
            "recommendations_count": len(recs),
            "recommendations": recs[:20]
        }
        
        report_path = "reports/backtest_analysis.json"
        os.makedirs("reports", exist_ok=True)
        with open(report_path, 'w') as f:
            json.dump(report, f, indent=2)
        
        print(f"\n✅ Full report saved to {report_path}")
        
        return report


def main():
    import sys
    
    bt = IntelligenceBacktest()
    
    if "--quick" in sys.argv:
        bt.analyze_ofi_signals()
        bt.analyze_direction_bias()
    else:
        bt.run_full_analysis()


if __name__ == "__main__":
    main()
