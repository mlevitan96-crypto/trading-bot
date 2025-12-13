#!/usr/bin/env python3
"""
Full Intelligence Correlation Analysis

Correlates ALL intelligence sources together to understand:
1. What did the FULL picture look like when we won vs lost?
2. What combination of signals predict success?
3. What are we missing or ignoring?
4. How do all signals work together (not in isolation)?

Data Sources Combined:
- OFI (Order Flow Imbalance)
- Ensemble Score (composite of multiple indicators)
- MTF Confidence (Multi-Timeframe alignment)
- Market Intelligence (Taker flow, Liquidations, Fear/Greed)
- Regime (Market condition classification)
- Volatility
- Volume patterns
- Entry/Exit timing

Usage:
    python src/full_intelligence_correlation.py
"""

import json
import os
from datetime import datetime, timedelta
from collections import defaultdict
from pathlib import Path
import statistics

LOGS_DIR = "logs"
FEATURE_DIR = "feature_store"


def load_jsonl(path, limit=None):
    """Load JSONL file."""
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


class FullIntelligenceCorrelation:
    """Comprehensive correlation of all intelligence sources."""
    
    def __init__(self):
        print("\n" + "="*70)
        print("📊 LOADING ALL INTELLIGENCE SOURCES")
        print("="*70)
        
        self.enriched = load_jsonl(f"{LOGS_DIR}/enriched_decisions.jsonl")
        print(f"   ✅ Enriched decisions: {len(self.enriched)} records")
        
        self.alpha_trades = load_jsonl(f"{LOGS_DIR}/alpha_trades.jsonl")
        print(f"   ✅ Alpha trades: {len(self.alpha_trades)} records")
        
        self.alpha_signals = load_jsonl(f"{LOGS_DIR}/alpha_signals_274_275.jsonl")
        print(f"   ✅ Alpha signals: {len(self.alpha_signals)} records")
        
        self.blocked = load_jsonl(f"{LOGS_DIR}/blocked_signals.jsonl")
        print(f"   ✅ Blocked signals: {len(self.blocked)} records")
        
        self.intel_history = load_jsonl(f"{FEATURE_DIR}/intelligence/history.jsonl")
        print(f"   ✅ Market intelligence history: {len(self.intel_history)} records")
        
        self.audit = load_jsonl(f"{LOGS_DIR}/audit_chain.jsonl", limit=1000)
        print(f"   ✅ Audit chain: {len(self.audit)} records (last 1000)")
        
        self.portfolio = load_json(f"{LOGS_DIR}/portfolio.json", {"trades": []})
        print(f"   ✅ Portfolio trades: {len(self.portfolio.get('trades', []))} records")
    
    def build_unified_decision_log(self):
        """Build a unified view of every decision with ALL intelligence."""
        print("\n" + "="*70)
        print("🔗 BUILDING UNIFIED DECISION LOG")
        print("="*70)
        
        decisions = []
        
        for record in self.enriched:
            ctx = record.get("signal_ctx", {})
            outcome = record.get("outcome", {})
            
            decision = {
                "ts": record.get("ts", 0),
                "symbol": record.get("symbol", ""),
                "venue": record.get("venue", ""),
                "strategy": record.get("strategy", ""),
                "action": "EXECUTED",
                
                "ofi": ctx.get("ofi", 0),
                "ofi_abs": abs(ctx.get("ofi", 0)),
                "ensemble": ctx.get("ensemble", 0),
                "ensemble_abs": abs(ctx.get("ensemble", 0)),
                "side": ctx.get("side", ""),
                "regime": ctx.get("regime", ""),
                "roi_expected": ctx.get("roi", 0),
                
                "pnl_usd": outcome.get("pnl_usd", 0),
                "pnl_pct": outcome.get("pnl_pct", 0),
                "fees": outcome.get("fees", 0),
                "entry_price": outcome.get("entry_price", 0),
                "exit_price": outcome.get("exit_price", 0),
                "leverage": outcome.get("leverage", 1),
                
                "is_win": outcome.get("pnl_usd", 0) > 0,
                "is_loss": outcome.get("pnl_usd", 0) <= 0,
                
                "ofi_aligned": (ctx.get("ofi", 0) > 0 and ctx.get("side") == "LONG") or 
                               (ctx.get("ofi", 0) < 0 and ctx.get("side") == "SHORT")
            }
            decisions.append(decision)
        
        for record in self.blocked:
            decision = {
                "ts": record.get("ts", 0),
                "symbol": record.get("decision", {}).get("symbol", ""),
                "action": "BLOCKED",
                "block_reason": record.get("reason", ""),
                "is_win": None,
                "is_loss": None
            }
            decisions.append(decision)
        
        print(f"   Total unified decisions: {len(decisions)}")
        return decisions
    
    def analyze_signal_combinations(self, decisions):
        """Analyze which combinations of signals lead to wins."""
        print("\n" + "="*70)
        print("🎯 SIGNAL COMBINATION ANALYSIS")
        print("="*70)
        print("\nQuestion: What does the FULL picture look like for wins vs losses?")
        
        executed = [d for d in decisions if d.get("action") == "EXECUTED"]
        
        if not executed:
            print("   No executed trades to analyze")
            return {}
        
        wins = [d for d in executed if d.get("is_win")]
        losses = [d for d in executed if d.get("is_loss")]
        
        print(f"\n   Total Executed: {len(executed)} | Wins: {len(wins)} | Losses: {len(losses)}")
        print(f"   Win Rate: {len(wins)/len(executed)*100:.1f}%")
        
        def calc_averages(trades, label):
            if not trades:
                return {}
            
            ofi_vals = [abs(t.get("ofi", 0)) for t in trades if t.get("ofi") is not None]
            ensemble_vals = [abs(t.get("ensemble", 0)) for t in trades if t.get("ensemble") is not None]
            aligned_count = sum(1 for t in trades if t.get("ofi_aligned"))
            
            return {
                "count": len(trades),
                "avg_ofi": statistics.mean(ofi_vals) if ofi_vals else 0,
                "avg_ensemble": statistics.mean(ensemble_vals) if ensemble_vals else 0,
                "ofi_aligned_pct": (aligned_count / len(trades) * 100) if trades else 0
            }
        
        win_stats = calc_averages(wins, "WINS")
        loss_stats = calc_averages(losses, "LOSSES")
        
        print(f"\n{'Metric':<30} {'WINS':>15} {'LOSSES':>15} {'Difference':>15}")
        print("-"*75)
        
        metrics = [
            ("Avg OFI Strength", win_stats.get("avg_ofi", 0), loss_stats.get("avg_ofi", 0)),
            ("Avg Ensemble Score", win_stats.get("avg_ensemble", 0), loss_stats.get("avg_ensemble", 0)),
            ("OFI Aligned %", win_stats.get("ofi_aligned_pct", 0), loss_stats.get("ofi_aligned_pct", 0))
        ]
        
        insights = []
        
        for name, win_val, loss_val in metrics:
            diff = win_val - loss_val
            diff_str = f"+{diff:.3f}" if diff > 0 else f"{diff:.3f}"
            indicator = "🟢" if diff > 0 else "🔴"
            print(f"{name:<30} {win_val:>15.3f} {loss_val:>15.3f} {indicator}{diff_str:>13}")
            
            if abs(diff) > 0.05:
                if diff > 0:
                    insights.append(f"Winners have higher {name.lower()} ({win_val:.2f} vs {loss_val:.2f})")
                else:
                    insights.append(f"Losers have higher {name.lower()} ({loss_val:.2f} vs {win_val:.2f}) - investigate!")
        
        return {"win_stats": win_stats, "loss_stats": loss_stats, "insights": insights}
    
    def analyze_by_symbol_direction(self, decisions):
        """Detailed breakdown by symbol and direction."""
        print("\n" + "="*70)
        print("📈 SYMBOL × DIRECTION × SIGNAL STRENGTH MATRIX")
        print("="*70)
        
        executed = [d for d in decisions if d.get("action") == "EXECUTED"]
        
        matrix = defaultdict(lambda: {
            "trades": 0, "wins": 0, "losses": 0, "pnl": 0,
            "ofi_sum": 0, "ensemble_sum": 0, "aligned_count": 0
        })
        
        for d in executed:
            key = f"{d.get('symbol', 'UNK')}_{d.get('side', 'UNK')}"
            matrix[key]["trades"] += 1
            matrix[key]["pnl"] += d.get("pnl_usd", 0)
            matrix[key]["ofi_sum"] += abs(d.get("ofi", 0))
            matrix[key]["ensemble_sum"] += abs(d.get("ensemble", 0))
            if d.get("is_win"):
                matrix[key]["wins"] += 1
            else:
                matrix[key]["losses"] += 1
            if d.get("ofi_aligned"):
                matrix[key]["aligned_count"] += 1
        
        print(f"\n{'Symbol_Dir':<18} {'Trades':>7} {'WR%':>7} {'P&L':>10} {'AvgOFI':>8} {'Aligned%':>9}")
        print("-"*65)
        
        sorted_matrix = sorted(matrix.items(), key=lambda x: x[1]["pnl"], reverse=True)
        
        profitable_patterns = []
        unprofitable_patterns = []
        
        for key, stats in sorted_matrix:
            trades = stats["trades"]
            if trades < 3:
                continue
            
            wr = (stats["wins"] / trades) * 100
            pnl = stats["pnl"]
            avg_ofi = stats["ofi_sum"] / trades
            aligned_pct = (stats["aligned_count"] / trades) * 100
            
            icon = "🟢" if pnl > 0 else "🔴"
            print(f"{key:<18} {trades:>7} {wr:>6.1f}% {icon}{pnl:>8.2f} {avg_ofi:>8.3f} {aligned_pct:>8.1f}%")
            
            if pnl > 0 and wr >= 35:
                profitable_patterns.append({
                    "pattern": key,
                    "wr": wr,
                    "pnl": pnl,
                    "avg_ofi": avg_ofi,
                    "aligned_pct": aligned_pct
                })
            elif pnl < -20:
                unprofitable_patterns.append({
                    "pattern": key,
                    "wr": wr,
                    "pnl": pnl,
                    "avg_ofi": avg_ofi,
                    "aligned_pct": aligned_pct
                })
        
        return {"profitable": profitable_patterns, "unprofitable": unprofitable_patterns}
    
    def analyze_missed_opportunities(self, decisions):
        """Analyze what we missed or blocked incorrectly."""
        print("\n" + "="*70)
        print("🔮 MISSED OPPORTUNITIES & BLOCKED SIGNALS")
        print("="*70)
        
        blocked = [d for d in decisions if d.get("action") == "BLOCKED"]
        
        print(f"\n   Total blocked signals: {len(blocked)}")
        
        if blocked:
            reasons = defaultdict(int)
            for d in blocked:
                reasons[d.get("block_reason", "unknown")] += 1
            
            print("\n   Block reasons:")
            for reason, count in sorted(reasons.items(), key=lambda x: -x[1]):
                print(f"      {reason}: {count}")
        else:
            print("   (No blocked signals logged yet - counterfactual learning needs more data)")
        
        return {"blocked_count": len(blocked), "blocked": blocked[:10]}
    
    def analyze_regime_correlation(self, decisions):
        """How do signals perform in different regimes?"""
        print("\n" + "="*70)
        print("🌊 REGIME × SIGNAL CORRELATION")
        print("="*70)
        
        executed = [d for d in decisions if d.get("action") == "EXECUTED"]
        
        regime_stats = defaultdict(lambda: {
            "trades": 0, "wins": 0, "pnl": 0,
            "ofi_sum": 0, "ensemble_sum": 0
        })
        
        for d in executed:
            regime = d.get("regime", "Unknown")
            regime_stats[regime]["trades"] += 1
            regime_stats[regime]["pnl"] += d.get("pnl_usd", 0)
            regime_stats[regime]["ofi_sum"] += abs(d.get("ofi", 0))
            regime_stats[regime]["ensemble_sum"] += abs(d.get("ensemble", 0))
            if d.get("is_win"):
                regime_stats[regime]["wins"] += 1
        
        print(f"\n{'Regime':<15} {'Trades':>8} {'WR%':>8} {'P&L':>12} {'Avg OFI':>10} {'Avg Ens':>10}")
        print("-"*65)
        
        for regime, stats in sorted(regime_stats.items(), key=lambda x: -x[1]["pnl"]):
            trades = stats["trades"]
            if trades == 0:
                continue
            wr = (stats["wins"] / trades) * 100
            pnl = stats["pnl"]
            avg_ofi = stats["ofi_sum"] / trades
            avg_ens = stats["ensemble_sum"] / trades
            
            icon = "🟢" if pnl > 0 else "🔴"
            print(f"{regime:<15} {trades:>8} {wr:>7.1f}% {icon}{pnl:>10.2f} {avg_ofi:>10.3f} {avg_ens:>10.3f}")
        
        return dict(regime_stats)
    
    def generate_composite_recommendations(self, combination_stats, pattern_stats):
        """Generate recommendations based on ALL correlations."""
        print("\n" + "="*70)
        print("💡 COMPOSITE INTELLIGENCE RECOMMENDATIONS")
        print("="*70)
        
        recommendations = []
        
        insights = combination_stats.get("insights", [])
        for insight in insights:
            recommendations.append({"type": "signal_correlation", "insight": insight})
        
        profitable = pattern_stats.get("profitable", [])
        for pattern in profitable[:5]:
            recommendations.append({
                "type": "profitable_pattern",
                "pattern": pattern["pattern"],
                "action": f"Increase exposure when OFI ≥ {pattern['avg_ofi']:.2f} and aligned",
                "expected_wr": pattern["wr"]
            })
        
        unprofitable = pattern_stats.get("unprofitable", [])
        for pattern in unprofitable[:5]:
            recommendations.append({
                "type": "unprofitable_pattern", 
                "pattern": pattern["pattern"],
                "action": f"Reduce exposure or require higher OFI (currently {pattern['avg_ofi']:.2f})",
                "current_wr": pattern["wr"]
            })
        
        print("\n📋 Action Items:")
        for i, rec in enumerate(recommendations[:10], 1):
            if rec["type"] == "signal_correlation":
                print(f"   {i}. 📊 {rec['insight']}")
            elif rec["type"] == "profitable_pattern":
                print(f"   {i}. ✅ {rec['pattern']}: {rec['action']} (expect {rec['expected_wr']:.1f}% WR)")
            elif rec["type"] == "unprofitable_pattern":
                print(f"   {i}. ⚠️ {rec['pattern']}: {rec['action']} (current {rec['current_wr']:.1f}% WR)")
        
        return recommendations
    
    def run_full_analysis(self):
        """Run complete correlation analysis."""
        print("\n" + "="*70)
        print("🔬 FULL INTELLIGENCE CORRELATION ANALYSIS")
        print(f"   Timestamp: {datetime.now().isoformat()}")
        print("="*70)
        
        decisions = self.build_unified_decision_log()
        
        combination_stats = self.analyze_signal_combinations(decisions)
        
        pattern_stats = self.analyze_by_symbol_direction(decisions)
        
        self.analyze_regime_correlation(decisions)
        
        missed = self.analyze_missed_opportunities(decisions)
        
        recommendations = self.generate_composite_recommendations(combination_stats, pattern_stats)
        
        report = {
            "timestamp": datetime.now().isoformat(),
            "total_decisions": len(decisions),
            "executed": len([d for d in decisions if d.get("action") == "EXECUTED"]),
            "blocked": len([d for d in decisions if d.get("action") == "BLOCKED"]),
            "combination_stats": combination_stats,
            "pattern_stats": pattern_stats,
            "recommendations": recommendations
        }
        
        from src.data_registry import DataRegistry as DR
        os.makedirs(os.path.dirname(DR.CORRELATION_REPORT), exist_ok=True)
        with open(DR.CORRELATION_REPORT, "w") as f:
            json.dump(report, f, indent=2, default=str)
        
        print(f"\n✅ Full report saved to {DR.CORRELATION_REPORT}")
        
        return report


def main():
    analyzer = FullIntelligenceCorrelation()
    analyzer.run_full_analysis()


if __name__ == "__main__":
    main()
