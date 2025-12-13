"""
Confidence-Tier Backtester

Simulates trading with confidence-based position sizing:
- High confidence patterns (A/B tier): 1.5x-2x position size
- Medium confidence (C tier): 1x baseline
- Low confidence (D/F tier): 0.5x-0.75x or block entirely

This validates whether the confidence scoring actually improves P&L.
"""

import json
import os
import math
from datetime import datetime, timedelta
from typing import Dict, List, Tuple, Optional
from collections import defaultdict

ENRICHED_DECISIONS = "logs/enriched_decisions.jsonl"
DEEP_ANALYSIS = "feature_store/deep_intelligence_analysis.json"
CORRELATION_ANALYSIS = "feature_store/coinglass_correlations.json"
BACKTEST_RESULTS = "logs/confidence_tier_backtest.json"


def _now() -> str:
    return datetime.utcnow().isoformat() + "Z"


def load_enriched_decisions() -> List[Dict]:
    """Load all enriched decisions with outcomes."""
    decisions = []
    if not os.path.exists(ENRICHED_DECISIONS):
        return []
    
    with open(ENRICHED_DECISIONS, 'r') as f:
        for line in f:
            try:
                dec = json.loads(line.strip())
                signal_ctx = dec.get("signal_ctx", {})
                outcome = dec.get("outcome", {})
                
                decisions.append({
                    "ts": dec.get("ts", 0),
                    "symbol": dec.get("symbol", ""),
                    "symbol_base": dec.get("symbol", "").replace("USDT", ""),
                    "direction": signal_ctx.get("side", ""),
                    "ofi": abs(signal_ctx.get("ofi", 0)),
                    "ensemble": signal_ctx.get("ensemble", 0),
                    "regime": signal_ctx.get("regime", "unknown"),
                    "pnl_usd": outcome.get("pnl_usd", 0),
                    "leverage": outcome.get("leverage", 5),
                    "is_win": outcome.get("pnl_usd", 0) > 0
                })
            except:
                continue
    
    return sorted(decisions, key=lambda x: x.get("ts", 0))


def bucket_ofi(ofi: float) -> str:
    if ofi > 0.8:
        return "extreme"
    elif ofi > 0.7:
        return "very_strong"
    elif ofi > 0.6:
        return "strong"
    elif ofi > 0.4:
        return "moderate"
    else:
        return "weak"


def load_deep_analysis() -> Dict:
    """Load deep intelligence analysis results."""
    if os.path.exists(DEEP_ANALYSIS):
        try:
            with open(DEEP_ANALYSIS, 'r') as f:
                return json.load(f)
        except:
            pass
    return {}


def load_correlation_analysis() -> Dict:
    """Load CoinGlass correlation analysis."""
    if os.path.exists(CORRELATION_ANALYSIS):
        try:
            with open(CORRELATION_ANALYSIS, 'r') as f:
                return json.load(f)
        except:
            pass
    return {}


class ConfidenceTierBacktester:
    """
    Backtests different position sizing strategies based on confidence tiers.
    
    Scenarios:
    1. Baseline: All trades at 1x size
    2. Tier-Based: Size based on confidence (A=1.5x, B=1.25x, C=1x, D=0.75x, F=0.5x)
    3. Block Low Confidence: Block D/F tier trades entirely
    4. Boost Only: Only boost A/B tier, keep others at 1x
    5. Inverse Low Confidence: Invert direction for F-tier signals
    """
    
    def __init__(self):
        self.decisions = []
        self.deep_analysis = {}
        self.correlation_analysis = {}
        self.results = {
            "run_ts": _now(),
            "scenarios": {},
            "tier_performance": {},
            "symbol_breakdown": {},
            "recommendations": []
        }
        
        self.direction_biases = {}
        self.symbol_blocks = set()
        self.pattern_tiers = {}
    
    def _load_insights(self):
        """Load insights from previous analyses."""
        corr = self.correlation_analysis.get("recommendations", [])
        for rec in corr:
            if rec["type"] == "direction_bias":
                sym = rec.get("symbol", "")
                self.direction_biases[sym] = rec.get("recommended_direction")
            elif rec["type"] == "avoid_symbol":
                sym = rec.get("symbol", "")
                self.symbol_blocks.add(sym)
        
        deep = self.deep_analysis.get("confidence_tiers", {})
        all_patterns = deep.get("all_patterns", [])
        for p in all_patterns:
            key = p.get("pattern", "")
            self.pattern_tiers[key] = p.get("tier", "F")
    
    def _get_trade_tier(self, decision: Dict) -> str:
        """
        Determine confidence tier for a trade based on multiple factors.
        
        Uses a scoring system that considers:
        - OFI strength (stronger = better)
        - Historical symbol performance
        - Direction alignment with learned biases
        - Ensemble signal strength
        """
        sym = decision["symbol"]
        sym_base = decision["symbol_base"]
        direction = decision["direction"]
        ofi = decision["ofi"]
        ensemble = abs(decision.get("ensemble", 0))
        ofi_bucket = bucket_ofi(ofi)
        
        score = 50
        
        if ofi >= 0.8:
            score += 15
        elif ofi >= 0.7:
            score += 10
        elif ofi >= 0.6:
            score += 5
        elif ofi < 0.4:
            score -= 10
        
        if ensemble >= 0.3:
            score += 10
        elif ensemble >= 0.2:
            score += 5
        elif ensemble < 0.1:
            score -= 5
        
        if sym_base in self.direction_biases:
            if self.direction_biases[sym_base] == direction:
                score += 15
            else:
                score -= 15
        
        if sym_base in self.symbol_blocks:
            score -= 20
        
        known_good = {"SOL": "LONG", "DOT": "SHORT", "BNB": "SHORT", "ETH": "SHORT"}
        if sym_base in known_good:
            if known_good[sym_base] == direction:
                score += 10
            else:
                score -= 10
        
        pattern_key = f"{sym}|{direction}"
        if pattern_key in self.pattern_tiers:
            tier = self.pattern_tiers[pattern_key]
            tier_boost = {"A": 20, "B": 10, "C": 0, "D": -10, "F": -20}
            score += tier_boost.get(tier, 0)
        
        if score >= 75:
            return "A"
        elif score >= 60:
            return "B"
        elif score >= 45:
            return "C"
        elif score >= 30:
            return "D"
        else:
            return "F"
    
    def run_backtest(self) -> Dict:
        """Run all backtest scenarios."""
        print("\n" + "="*80)
        print("🔬 CONFIDENCE-TIER BACKTESTER")
        print("="*80)
        print(f"Run time: {_now()}")
        
        self.decisions = load_enriched_decisions()
        self.deep_analysis = load_deep_analysis()
        self.correlation_analysis = load_correlation_analysis()
        self._load_insights()
        
        print(f"Loaded {len(self.decisions)} decisions")
        print(f"Direction biases: {len(self.direction_biases)}")
        print(f"Symbol blocks: {len(self.symbol_blocks)}")
        print(f"Pattern tiers: {len(self.pattern_tiers)}")
        
        self._run_scenario_baseline()
        self._run_scenario_tier_sizing()
        self._run_scenario_block_low()
        self._run_scenario_boost_only()
        self._run_scenario_inverse_losers()
        self._run_scenario_direction_bias()
        
        self._analyze_tier_performance()
        self._generate_recommendations()
        
        self._save_results()
        self._print_results()
        
        return self.results
    
    def _run_scenario_baseline(self):
        """Scenario 1: All trades at 1x size."""
        print("\n📊 Running Baseline scenario...")
        
        pnl = sum(d["pnl_usd"] for d in self.decisions)
        wins = sum(1 for d in self.decisions if d["is_win"])
        wr = wins / len(self.decisions) * 100 if self.decisions else 0
        
        self.results["scenarios"]["baseline"] = {
            "name": "Baseline (1x all trades)",
            "trades": len(self.decisions),
            "wins": wins,
            "wr": round(wr, 1),
            "pnl": round(pnl, 2),
            "avg_pnl": round(pnl / len(self.decisions), 2) if self.decisions else 0
        }
    
    def _run_scenario_tier_sizing(self):
        """Scenario 2: Size based on confidence tier."""
        print("📊 Running Tier-Based Sizing scenario...")
        
        tier_multipliers = {
            "A": 1.5,
            "B": 1.25,
            "C": 1.0,
            "D": 0.75,
            "F": 0.5
        }
        
        pnl = 0.0
        wins = 0
        tier_counts = defaultdict(int)
        
        for d in self.decisions:
            tier = self._get_trade_tier(d)
            tier_counts[tier] += 1
            mult = tier_multipliers.get(tier, 1.0)
            adjusted_pnl = d["pnl_usd"] * mult
            pnl += adjusted_pnl
            if adjusted_pnl > 0:
                wins += 1
        
        wr = wins / len(self.decisions) * 100 if self.decisions else 0
        
        self.results["scenarios"]["tier_sizing"] = {
            "name": "Tier-Based Sizing (A=1.5x, F=0.5x)",
            "trades": len(self.decisions),
            "wins": wins,
            "wr": round(wr, 1),
            "pnl": round(pnl, 2),
            "tier_distribution": dict(tier_counts)
        }
    
    def _run_scenario_block_low(self):
        """Scenario 3: Block D/F tier trades."""
        print("📊 Running Block Low Confidence scenario...")
        
        filtered = [d for d in self.decisions if self._get_trade_tier(d) in ["A", "B", "C"]]
        
        pnl = sum(d["pnl_usd"] for d in filtered)
        wins = sum(1 for d in filtered if d["is_win"])
        wr = wins / len(filtered) * 100 if filtered else 0
        
        blocked = len(self.decisions) - len(filtered)
        blocked_pnl = sum(d["pnl_usd"] for d in self.decisions if self._get_trade_tier(d) in ["D", "F"])
        
        self.results["scenarios"]["block_low"] = {
            "name": "Block D/F Tier Trades",
            "trades": len(filtered),
            "blocked": blocked,
            "wins": wins,
            "wr": round(wr, 1),
            "pnl": round(pnl, 2),
            "avoided_pnl": round(blocked_pnl, 2)
        }
    
    def _run_scenario_boost_only(self):
        """Scenario 4: Only boost A/B tier, keep others at 1x."""
        print("📊 Running Boost Only scenario...")
        
        pnl = 0.0
        wins = 0
        boosted_count = 0
        
        for d in self.decisions:
            tier = self._get_trade_tier(d)
            if tier == "A":
                mult = 1.5
                boosted_count += 1
            elif tier == "B":
                mult = 1.25
                boosted_count += 1
            else:
                mult = 1.0
            
            adjusted_pnl = d["pnl_usd"] * mult
            pnl += adjusted_pnl
            if adjusted_pnl > 0:
                wins += 1
        
        wr = wins / len(self.decisions) * 100 if self.decisions else 0
        
        self.results["scenarios"]["boost_only"] = {
            "name": "Boost A/B Only (Others 1x)",
            "trades": len(self.decisions),
            "boosted": boosted_count,
            "wins": wins,
            "wr": round(wr, 1),
            "pnl": round(pnl, 2)
        }
    
    def _run_scenario_inverse_losers(self):
        """Scenario 5: Invert direction for F-tier signals."""
        print("📊 Running Inverse Losers scenario...")
        
        pnl = 0.0
        wins = 0
        inverted = 0
        
        for d in self.decisions:
            tier = self._get_trade_tier(d)
            if tier == "F":
                adjusted_pnl = -d["pnl_usd"]
                inverted += 1
            else:
                adjusted_pnl = d["pnl_usd"]
            
            pnl += adjusted_pnl
            if adjusted_pnl > 0:
                wins += 1
        
        wr = wins / len(self.decisions) * 100 if self.decisions else 0
        
        self.results["scenarios"]["inverse_losers"] = {
            "name": "Invert F-Tier Signals",
            "trades": len(self.decisions),
            "inverted": inverted,
            "wins": wins,
            "wr": round(wr, 1),
            "pnl": round(pnl, 2)
        }
    
    def _run_scenario_direction_bias(self):
        """Scenario 6: Only trade preferred directions."""
        print("📊 Running Direction Bias scenario...")
        
        filtered = []
        for d in self.decisions:
            sym_base = d["symbol_base"]
            if sym_base in self.direction_biases:
                if d["direction"] == self.direction_biases[sym_base]:
                    filtered.append(d)
            else:
                filtered.append(d)
        
        pnl = sum(d["pnl_usd"] for d in filtered)
        wins = sum(1 for d in filtered if d["is_win"])
        wr = wins / len(filtered) * 100 if filtered else 0
        
        blocked = len(self.decisions) - len(filtered)
        blocked_pnl = sum(d["pnl_usd"] for d in self.decisions if d not in filtered)
        
        self.results["scenarios"]["direction_bias"] = {
            "name": "Respect Direction Biases",
            "trades": len(filtered),
            "blocked": blocked,
            "wins": wins,
            "wr": round(wr, 1),
            "pnl": round(pnl, 2),
            "avoided_pnl": round(blocked_pnl, 2),
            "biases_applied": dict(self.direction_biases)
        }
    
    def _analyze_tier_performance(self):
        """Analyze performance by tier."""
        print("\n📈 Analyzing tier performance...")
        
        tier_stats = defaultdict(lambda: {"trades": 0, "wins": 0, "pnl": 0.0})
        
        for d in self.decisions:
            tier = self._get_trade_tier(d)
            tier_stats[tier]["trades"] += 1
            tier_stats[tier]["pnl"] += d["pnl_usd"]
            if d["is_win"]:
                tier_stats[tier]["wins"] += 1
        
        for tier, stats in tier_stats.items():
            if stats["trades"] > 0:
                stats["wr"] = round(stats["wins"] / stats["trades"] * 100, 1)
                stats["avg_pnl"] = round(stats["pnl"] / stats["trades"], 2)
                stats["pnl"] = round(stats["pnl"], 2)
        
        self.results["tier_performance"] = dict(tier_stats)
    
    def _generate_recommendations(self):
        """Generate recommendations based on backtest results."""
        print("\n💡 Generating recommendations...")
        
        scenarios = self.results["scenarios"]
        baseline = scenarios.get("baseline", {})
        baseline_pnl = baseline.get("pnl", 0)
        
        recommendations = []
        
        for name, data in sorted(scenarios.items(), key=lambda x: x[1].get("pnl", -9999), reverse=True):
            if name == "baseline":
                continue
            
            delta = data.get("pnl", 0) - baseline_pnl
            if delta > 0:
                recommendations.append({
                    "scenario": name,
                    "improvement": round(delta, 2),
                    "improvement_pct": round(delta / abs(baseline_pnl) * 100, 1) if baseline_pnl != 0 else 0,
                    "new_pnl": data.get("pnl", 0),
                    "trades": data.get("trades", 0),
                    "recommendation": f"ADOPT: {data['name']} improves P&L by ${delta:.2f}"
                })
        
        tier_perf = self.results.get("tier_performance", {})
        for tier, stats in tier_perf.items():
            if stats.get("wr", 0) >= 30 and stats.get("pnl", 0) > 0:
                recommendations.append({
                    "type": "tier_boost",
                    "tier": tier,
                    "reason": f"Tier {tier} has {stats['wr']}% WR and positive P&L - increase size"
                })
            elif stats.get("pnl", 0) < -50:
                recommendations.append({
                    "type": "tier_block",
                    "tier": tier,
                    "reason": f"Tier {tier} lost ${abs(stats['pnl']):.2f} - consider blocking"
                })
        
        self.results["recommendations"] = recommendations
    
    def _print_results(self):
        """Print backtest results."""
        print("\n" + "="*80)
        print("📋 BACKTEST RESULTS")
        print("="*80)
        
        print("\n🔹 SCENARIO COMPARISON:")
        scenarios = self.results["scenarios"]
        for name, data in sorted(scenarios.items(), key=lambda x: x[1].get("pnl", -9999), reverse=True):
            trades = data.get("trades", 0)
            wr = data.get("wr", 0)
            pnl = data.get("pnl", 0)
            baseline_pnl = scenarios.get("baseline", {}).get("pnl", 0)
            delta = pnl - baseline_pnl if name != "baseline" else 0
            
            status = "📈" if delta > 0 else "📉" if delta < 0 else "➖"
            print(f"   {status} {data.get('name', name):35} | {trades:4} trades | {wr:5.1f}% WR | ${pnl:8.2f} | Δ ${delta:+8.2f}")
        
        print("\n🔹 TIER PERFORMANCE:")
        tier_perf = self.results.get("tier_performance", {})
        for tier in ["A", "B", "C", "D", "F"]:
            if tier in tier_perf:
                stats = tier_perf[tier]
                status = "✅" if stats.get("pnl", 0) > 0 else "❌"
                print(f"   {status} Tier {tier}: {stats.get('trades', 0):4} trades | "
                      f"{stats.get('wr', 0):5.1f}% WR | ${stats.get('pnl', 0):8.2f} | "
                      f"Avg ${stats.get('avg_pnl', 0):+.2f}")
        
        print("\n🔹 TOP RECOMMENDATIONS:")
        for rec in self.results.get("recommendations", [])[:10]:
            if "recommendation" in rec:
                print(f"   {rec['recommendation']}")
            elif "reason" in rec:
                print(f"   [{rec.get('type', 'info')}] {rec['reason']}")
        
        print("="*80 + "\n")
    
    def _save_results(self):
        """Save backtest results."""
        os.makedirs(os.path.dirname(BACKTEST_RESULTS), exist_ok=True)
        with open(BACKTEST_RESULTS, 'w') as f:
            json.dump(self.results, f, indent=2, default=str)
        print(f"\n💾 Results saved to: {BACKTEST_RESULTS}")


def run_backtest() -> Dict:
    """Run confidence-tier backtest."""
    backtester = ConfidenceTierBacktester()
    return backtester.run_backtest()


if __name__ == "__main__":
    run_backtest()
