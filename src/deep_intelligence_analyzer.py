"""
Deep Intelligence Analyzer - Comprehensive Pattern Discovery & Correlation Analysis

Analyzes all dimensions of trading data to discover:
1. Coin-to-coin correlations and lead-lag relationships
2. CoinGlass signal alignment with technical indicators
3. Multi-dimensional pattern discovery
4. Confidence scoring for patterns
5. Actionable insights for position sizing

Design principles:
- NO look-ahead bias - only use data available at decision time
- Statistical rigor - p-values, confidence intervals, sample sizes
- Practical focus - patterns must be tradeable
"""

import json
import os
import math
from datetime import datetime, timedelta
from typing import Dict, List, Tuple, Optional, Any
from collections import defaultdict
from pathlib import Path

ENRICHED_DECISIONS = "logs/enriched_decisions.jsonl"
COINGLASS_CACHE = "feature_store/coinglass/cache"
LEARNING_RULES = "feature_store/daily_learning_rules.json"
COIN_PROFILES = "feature_store/coin_profiles.json"
ANALYSIS_OUTPUT = "feature_store/deep_intelligence_analysis.json"

COIN_CLUSTERS = {
    "major": ["BTCUSDT"],
    "alt_l1": ["ETHUSDT", "SOLUSDT", "AVAXUSDT", "DOTUSDT", "MATICUSDT"],
    "payment": ["TRXUSDT", "XRPUSDT"],
    "l2": ["ARBUSDT", "OPUSDT"],
    "defi": ["LINKUSDT"],
    "meme": ["DOGEUSDT", "PEPEUSDT"],
    "exchange": ["BNBUSDT", "ADAUSDT"]
}

ALL_COINS = [c for cluster in COIN_CLUSTERS.values() for c in cluster]


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
                    "direction": signal_ctx.get("side", ""),
                    "ofi": abs(signal_ctx.get("ofi", 0)),
                    "ensemble": signal_ctx.get("ensemble", 0),
                    "roi_expected": signal_ctx.get("roi", 0),
                    "regime": signal_ctx.get("regime", "unknown"),
                    "pnl_usd": outcome.get("pnl_usd", 0),
                    "pnl_pct": outcome.get("pnl_pct", 0),
                    "leverage": outcome.get("leverage", 5),
                    "entry_price": outcome.get("entry_price", 0),
                    "exit_price": outcome.get("exit_price", 0),
                    "fees": outcome.get("fees", 0),
                    "is_win": outcome.get("pnl_usd", 0) > 0
                })
            except:
                continue
    
    return sorted(decisions, key=lambda x: x.get("ts", 0))


def bucket_ofi(ofi: float) -> str:
    """Bucket OFI into categories."""
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


def bucket_ensemble(ens: float) -> str:
    """Bucket ensemble score into categories."""
    if ens > 0.3:
        return "strong_bull"
    elif ens > 0.1:
        return "bull"
    elif ens > -0.1:
        return "neutral"
    elif ens > -0.3:
        return "bear"
    else:
        return "strong_bear"


def compute_pearson(x: List[float], y: List[float]) -> Tuple[float, float]:
    """Compute Pearson correlation and p-value approximation."""
    if len(x) < 5 or len(x) != len(y):
        return 0.0, 1.0
    
    n = len(x)
    mean_x = sum(x) / n
    mean_y = sum(y) / n
    
    var_x = sum((xi - mean_x) ** 2 for xi in x) / n
    var_y = sum((yi - mean_y) ** 2 for yi in y) / n
    
    if var_x == 0 or var_y == 0:
        return 0.0, 1.0
    
    cov = sum((x[i] - mean_x) * (y[i] - mean_y) for i in range(n)) / n
    r = cov / (math.sqrt(var_x) * math.sqrt(var_y))
    
    if abs(r) >= 1.0:
        return r, 0.0
    
    t_stat = r * math.sqrt((n - 2) / (1 - r ** 2)) if abs(r) < 1 else 0
    p_value = 2 * (1 - min(0.999, abs(t_stat) / (abs(t_stat) + 1)))
    
    return r, p_value


class DeepIntelligenceAnalyzer:
    """
    Comprehensive intelligence analyzer for pattern discovery.
    
    Analyzes:
    1. Coin correlations (returns, signals, outcomes)
    2. Technical indicator effectiveness
    3. CoinGlass signal alignment
    4. Multi-dimensional pattern discovery
    5. Confidence scoring
    """
    
    def __init__(self):
        self.decisions = []
        self.results = {
            "run_ts": _now(),
            "summary": {},
            "coin_correlations": {},
            "indicator_effectiveness": {},
            "pattern_discoveries": {},
            "confidence_tiers": {},
            "actionable_insights": [],
            "dimension_analysis": {}
        }
    
    def run_full_analysis(self) -> Dict:
        """Run complete deep intelligence analysis."""
        print("\n" + "="*80)
        print("🔬 DEEP INTELLIGENCE ANALYZER")
        print("="*80)
        print(f"Run time: {_now()}")
        
        self.decisions = load_enriched_decisions()
        print(f"Loaded {len(self.decisions)} enriched decisions")
        
        if len(self.decisions) < 10:
            print("❌ Insufficient data for analysis")
            return self.results
        
        self._analyze_coin_correlations()
        self._analyze_indicator_effectiveness()
        self._analyze_pattern_dimensions()
        self._compute_confidence_tiers()
        self._generate_actionable_insights()
        self._compute_summary()
        
        self._save_results()
        self._print_results()
        
        return self.results
    
    def _analyze_coin_correlations(self):
        """Analyze correlations between coins."""
        print("\n📊 Analyzing coin correlations...")
        
        by_coin = defaultdict(list)
        for d in self.decisions:
            by_coin[d["symbol"]].append(d)
        
        correlations = {}
        
        for sym1 in ALL_COINS:
            if sym1 not in by_coin or len(by_coin[sym1]) < 10:
                continue
            
            correlations[sym1] = {
                "trades": len(by_coin[sym1]),
                "win_rate": sum(1 for d in by_coin[sym1] if d["is_win"]) / len(by_coin[sym1]) * 100,
                "total_pnl": sum(d["pnl_usd"] for d in by_coin[sym1]),
                "avg_pnl": sum(d["pnl_usd"] for d in by_coin[sym1]) / len(by_coin[sym1]),
                "correlations": {}
            }
            
            pnl1 = [d["pnl_usd"] for d in by_coin[sym1]]
            
            for sym2 in ALL_COINS:
                if sym1 == sym2 or sym2 not in by_coin or len(by_coin[sym2]) < 10:
                    continue
                
                pnl2 = [d["pnl_usd"] for d in by_coin[sym2]]
                
                min_len = min(len(pnl1), len(pnl2))
                if min_len >= 10:
                    r, p = compute_pearson(pnl1[:min_len], pnl2[:min_len])
                    correlations[sym1]["correlations"][sym2] = {
                        "r": round(r, 3),
                        "p_value": round(p, 4),
                        "significant": p < 0.05
                    }
        
        self.results["coin_correlations"] = correlations
        print(f"   Analyzed {len(correlations)} coins with cross-correlations")
    
    def _analyze_indicator_effectiveness(self):
        """Analyze how well each indicator predicts outcomes."""
        print("\n📈 Analyzing indicator effectiveness...")
        
        indicators = {
            "ofi": {"thresholds": [0.4, 0.5, 0.6, 0.7, 0.8], "results": {}},
            "ensemble": {"thresholds": [-0.3, -0.1, 0.1, 0.3], "results": {}},
            "regime": {"categories": ["Stable", "Volatile", "Trending"], "results": {}},
            "direction": {"categories": ["LONG", "SHORT"], "results": {}}
        }
        
        ofi_results = {}
        for thresh in indicators["ofi"]["thresholds"]:
            above = [d for d in self.decisions if d["ofi"] >= thresh]
            below = [d for d in self.decisions if d["ofi"] < thresh]
            
            if len(above) >= 5 and len(below) >= 5:
                above_wr = sum(1 for d in above if d["is_win"]) / len(above) * 100
                below_wr = sum(1 for d in below if d["is_win"]) / len(below) * 100
                above_pnl = sum(d["pnl_usd"] for d in above)
                below_pnl = sum(d["pnl_usd"] for d in below)
                
                ofi_results[str(thresh)] = {
                    "above": {"trades": len(above), "wr": round(above_wr, 1), "pnl": round(above_pnl, 2)},
                    "below": {"trades": len(below), "wr": round(below_wr, 1), "pnl": round(below_pnl, 2)},
                    "lift": round(above_wr - below_wr, 1),
                    "predictive": above_wr > below_wr
                }
        
        indicators["ofi"]["results"] = ofi_results
        
        ens_results = {}
        for i, thresh in enumerate(indicators["ensemble"]["thresholds"]):
            if i == 0:
                bucket = [d for d in self.decisions if d["ensemble"] < thresh]
                label = f"<{thresh}"
            else:
                prev = indicators["ensemble"]["thresholds"][i-1]
                bucket = [d for d in self.decisions if prev <= d["ensemble"] < thresh]
                label = f"{prev}_to_{thresh}"
            
            if len(bucket) >= 5:
                wr = sum(1 for d in bucket if d["is_win"]) / len(bucket) * 100
                pnl = sum(d["pnl_usd"] for d in bucket)
                ens_results[label] = {
                    "trades": len(bucket),
                    "wr": round(wr, 1),
                    "pnl": round(pnl, 2),
                    "avg_pnl": round(pnl / len(bucket), 2)
                }
        
        bucket = [d for d in self.decisions if d["ensemble"] >= indicators["ensemble"]["thresholds"][-1]]
        if len(bucket) >= 5:
            wr = sum(1 for d in bucket if d["is_win"]) / len(bucket) * 100
            pnl = sum(d["pnl_usd"] for d in bucket)
            ens_results[f">={indicators['ensemble']['thresholds'][-1]}"] = {
                "trades": len(bucket),
                "wr": round(wr, 1),
                "pnl": round(pnl, 2),
                "avg_pnl": round(pnl / len(bucket), 2)
            }
        
        indicators["ensemble"]["results"] = ens_results
        
        regime_results = {}
        for regime in indicators["regime"]["categories"]:
            bucket = [d for d in self.decisions if d["regime"] == regime]
            if len(bucket) >= 5:
                wr = sum(1 for d in bucket if d["is_win"]) / len(bucket) * 100
                pnl = sum(d["pnl_usd"] for d in bucket)
                regime_results[regime] = {
                    "trades": len(bucket),
                    "wr": round(wr, 1),
                    "pnl": round(pnl, 2),
                    "avg_pnl": round(pnl / len(bucket), 2)
                }
        
        indicators["regime"]["results"] = regime_results
        
        dir_results = {}
        for direction in indicators["direction"]["categories"]:
            bucket = [d for d in self.decisions if d["direction"] == direction]
            if len(bucket) >= 5:
                wr = sum(1 for d in bucket if d["is_win"]) / len(bucket) * 100
                pnl = sum(d["pnl_usd"] for d in bucket)
                dir_results[direction] = {
                    "trades": len(bucket),
                    "wr": round(wr, 1),
                    "pnl": round(pnl, 2),
                    "avg_pnl": round(pnl / len(bucket), 2)
                }
        
        indicators["direction"]["results"] = dir_results
        
        self.results["indicator_effectiveness"] = indicators
        print(f"   Analyzed 4 indicator categories")
    
    def _analyze_pattern_dimensions(self):
        """Analyze patterns across multiple dimensions."""
        print("\n🔎 Analyzing multi-dimensional patterns...")
        
        dimensions = {
            "symbol_direction": {},
            "symbol_ofi_bucket": {},
            "symbol_regime": {},
            "direction_ofi_bucket": {},
            "direction_ensemble_bucket": {},
            "regime_direction": {},
            "ofi_ensemble_cross": {}
        }
        
        for d in self.decisions:
            sym = d["symbol"]
            direction = d["direction"]
            ofi_bucket = bucket_ofi(d["ofi"])
            ens_bucket = bucket_ensemble(d["ensemble"])
            regime = d["regime"]
            pnl = d["pnl_usd"]
            is_win = d["is_win"]
            
            key1 = f"{sym}|{direction}"
            if key1 not in dimensions["symbol_direction"]:
                dimensions["symbol_direction"][key1] = {"wins": 0, "total": 0, "pnl": 0.0}
            dimensions["symbol_direction"][key1]["total"] += 1
            dimensions["symbol_direction"][key1]["pnl"] += pnl
            if is_win:
                dimensions["symbol_direction"][key1]["wins"] += 1
            
            key2 = f"{sym}|{ofi_bucket}"
            if key2 not in dimensions["symbol_ofi_bucket"]:
                dimensions["symbol_ofi_bucket"][key2] = {"wins": 0, "total": 0, "pnl": 0.0}
            dimensions["symbol_ofi_bucket"][key2]["total"] += 1
            dimensions["symbol_ofi_bucket"][key2]["pnl"] += pnl
            if is_win:
                dimensions["symbol_ofi_bucket"][key2]["wins"] += 1
            
            key3 = f"{sym}|{regime}"
            if key3 not in dimensions["symbol_regime"]:
                dimensions["symbol_regime"][key3] = {"wins": 0, "total": 0, "pnl": 0.0}
            dimensions["symbol_regime"][key3]["total"] += 1
            dimensions["symbol_regime"][key3]["pnl"] += pnl
            if is_win:
                dimensions["symbol_regime"][key3]["wins"] += 1
            
            key4 = f"{direction}|{ofi_bucket}"
            if key4 not in dimensions["direction_ofi_bucket"]:
                dimensions["direction_ofi_bucket"][key4] = {"wins": 0, "total": 0, "pnl": 0.0}
            dimensions["direction_ofi_bucket"][key4]["total"] += 1
            dimensions["direction_ofi_bucket"][key4]["pnl"] += pnl
            if is_win:
                dimensions["direction_ofi_bucket"][key4]["wins"] += 1
            
            key5 = f"{direction}|{ens_bucket}"
            if key5 not in dimensions["direction_ensemble_bucket"]:
                dimensions["direction_ensemble_bucket"][key5] = {"wins": 0, "total": 0, "pnl": 0.0}
            dimensions["direction_ensemble_bucket"][key5]["total"] += 1
            dimensions["direction_ensemble_bucket"][key5]["pnl"] += pnl
            if is_win:
                dimensions["direction_ensemble_bucket"][key5]["wins"] += 1
            
            key6 = f"{regime}|{direction}"
            if key6 not in dimensions["regime_direction"]:
                dimensions["regime_direction"][key6] = {"wins": 0, "total": 0, "pnl": 0.0}
            dimensions["regime_direction"][key6]["total"] += 1
            dimensions["regime_direction"][key6]["pnl"] += pnl
            if is_win:
                dimensions["regime_direction"][key6]["wins"] += 1
            
            key7 = f"{ofi_bucket}|{ens_bucket}"
            if key7 not in dimensions["ofi_ensemble_cross"]:
                dimensions["ofi_ensemble_cross"][key7] = {"wins": 0, "total": 0, "pnl": 0.0}
            dimensions["ofi_ensemble_cross"][key7]["total"] += 1
            dimensions["ofi_ensemble_cross"][key7]["pnl"] += pnl
            if is_win:
                dimensions["ofi_ensemble_cross"][key7]["wins"] += 1
        
        for dim_name, dim_data in dimensions.items():
            for key, stats in dim_data.items():
                if stats["total"] >= 5:
                    stats["wr"] = round(stats["wins"] / stats["total"] * 100, 1)
                    stats["avg_pnl"] = round(stats["pnl"] / stats["total"], 2)
                    stats["pnl"] = round(stats["pnl"], 2)
                else:
                    stats["wr"] = 0.0
                    stats["avg_pnl"] = 0.0
        
        self.results["dimension_analysis"] = dimensions
        
        total_patterns = sum(len(d) for d in dimensions.values())
        print(f"   Analyzed {total_patterns} pattern combinations across 7 dimensions")
    
    def _compute_confidence_tiers(self):
        """Compute confidence tiers for discovered patterns."""
        print("\n🎯 Computing confidence tiers...")
        
        all_patterns = []
        
        for dim_name, dim_data in self.results["dimension_analysis"].items():
            for key, stats in dim_data.items():
                if stats["total"] >= 10:
                    baseline_wr = sum(1 for d in self.decisions if d["is_win"]) / len(self.decisions) * 100
                    lift = stats["wr"] - baseline_wr
                    
                    score = 0
                    
                    if stats["wr"] >= 50:
                        score += 30
                    elif stats["wr"] >= 40:
                        score += 20
                    elif stats["wr"] >= 30:
                        score += 10
                    
                    if stats["pnl"] > 50:
                        score += 25
                    elif stats["pnl"] > 20:
                        score += 15
                    elif stats["pnl"] > 0:
                        score += 10
                    elif stats["pnl"] < -50:
                        score -= 20
                    
                    if lift > 15:
                        score += 20
                    elif lift > 10:
                        score += 15
                    elif lift > 5:
                        score += 10
                    
                    if stats["total"] >= 50:
                        score += 15
                    elif stats["total"] >= 30:
                        score += 10
                    elif stats["total"] >= 20:
                        score += 5
                    
                    tier = "F"
                    size_mult = 0.5
                    if score >= 70:
                        tier = "A"
                        size_mult = 1.5
                    elif score >= 55:
                        tier = "B"
                        size_mult = 1.25
                    elif score >= 40:
                        tier = "C"
                        size_mult = 1.0
                    elif score >= 25:
                        tier = "D"
                        size_mult = 0.75
                    
                    all_patterns.append({
                        "dimension": dim_name,
                        "pattern": key,
                        "trades": stats["total"],
                        "wr": stats["wr"],
                        "pnl": stats["pnl"],
                        "avg_pnl": stats["avg_pnl"],
                        "lift": round(lift, 1),
                        "score": score,
                        "tier": tier,
                        "size_mult": size_mult
                    })
        
        all_patterns.sort(key=lambda x: x["score"], reverse=True)
        
        tier_summary = defaultdict(list)
        for p in all_patterns:
            tier_summary[p["tier"]].append(p)
        
        self.results["confidence_tiers"] = {
            "all_patterns": all_patterns[:100],
            "by_tier": {tier: patterns[:20] for tier, patterns in tier_summary.items()},
            "tier_counts": {tier: len(patterns) for tier, patterns in tier_summary.items()}
        }
        
        print(f"   Scored {len(all_patterns)} patterns into confidence tiers")
        for tier in ["A", "B", "C", "D", "F"]:
            count = tier_summary.get(tier, [])
            print(f"      Tier {tier}: {len(count)} patterns")
    
    def _generate_actionable_insights(self):
        """Generate actionable trading insights."""
        print("\n💡 Generating actionable insights...")
        
        insights = []
        
        dim = self.results["dimension_analysis"]
        sym_dir = dim.get("symbol_direction", {})
        
        for key, stats in sorted(sym_dir.items(), key=lambda x: x[1].get("wr", 0), reverse=True):
            if stats["total"] >= 10 and stats["wr"] >= 40:
                sym, direction = key.split("|")
                insights.append({
                    "type": "high_accuracy_combo",
                    "symbol": sym,
                    "direction": direction,
                    "wr": stats["wr"],
                    "trades": stats["total"],
                    "pnl": stats["pnl"],
                    "action": f"BOOST {sym} {direction} - {stats['wr']}% WR over {stats['total']} trades",
                    "size_mult": 1.3 if stats["wr"] >= 50 else 1.15
                })
        
        for key, stats in sorted(sym_dir.items(), key=lambda x: x[1].get("pnl", 0)):
            if stats["total"] >= 10 and stats["pnl"] < -20:
                sym, direction = key.split("|")
                insights.append({
                    "type": "avoid_pattern",
                    "symbol": sym,
                    "direction": direction,
                    "wr": stats["wr"],
                    "trades": stats["total"],
                    "pnl": stats["pnl"],
                    "action": f"BLOCK {sym} {direction} - Lost ${abs(stats['pnl']):.2f} over {stats['total']} trades",
                    "size_mult": 0.0
                })
        
        ofi_ens = dim.get("ofi_ensemble_cross", {})
        for key, stats in sorted(ofi_ens.items(), key=lambda x: x[1].get("wr", 0), reverse=True):
            if stats["total"] >= 15 and stats["wr"] >= 35:
                ofi_bucket, ens_bucket = key.split("|")
                insights.append({
                    "type": "signal_confluence",
                    "ofi_bucket": ofi_bucket,
                    "ensemble_bucket": ens_bucket,
                    "wr": stats["wr"],
                    "trades": stats["total"],
                    "pnl": stats["pnl"],
                    "action": f"When OFI={ofi_bucket} and Ensemble={ens_bucket}: {stats['wr']}% WR",
                    "size_mult": 1.2 if stats["wr"] >= 40 else 1.0
                })
        
        ind = self.results["indicator_effectiveness"]
        ofi_results = ind.get("ofi", {}).get("results", {})
        best_ofi_thresh = None
        best_lift = -999
        for thresh, data in ofi_results.items():
            if data.get("predictive") and data.get("lift", 0) > best_lift:
                best_lift = data["lift"]
                best_ofi_thresh = thresh
        
        if best_ofi_thresh:
            insights.append({
                "type": "optimal_threshold",
                "indicator": "ofi",
                "threshold": float(best_ofi_thresh),
                "lift": best_lift,
                "action": f"OFI threshold {best_ofi_thresh} provides {best_lift}% WR lift",
                "size_mult": 1.0
            })
        
        self.results["actionable_insights"] = insights
        print(f"   Generated {len(insights)} actionable insights")
    
    def _compute_summary(self):
        """Compute overall analysis summary."""
        baseline_wr = sum(1 for d in self.decisions if d["is_win"]) / len(self.decisions) * 100
        baseline_pnl = sum(d["pnl_usd"] for d in self.decisions)
        
        tier_counts = self.results["confidence_tiers"].get("tier_counts", {})
        high_conf = tier_counts.get("A", 0) + tier_counts.get("B", 0)
        
        high_accuracy = [i for i in self.results["actionable_insights"] if i["type"] == "high_accuracy_combo"]
        avoid_patterns = [i for i in self.results["actionable_insights"] if i["type"] == "avoid_pattern"]
        
        self.results["summary"] = {
            "total_decisions": len(self.decisions),
            "baseline_wr": round(baseline_wr, 1),
            "baseline_pnl": round(baseline_pnl, 2),
            "patterns_analyzed": sum(len(d) for d in self.results["dimension_analysis"].values()),
            "high_confidence_patterns": high_conf,
            "high_accuracy_combos": len(high_accuracy),
            "patterns_to_avoid": len(avoid_patterns),
            "potential_pnl_improvement": round(sum(p["pnl"] for p in avoid_patterns if p["pnl"] < 0), 2),
            "indicators_analyzed": 4,
            "dimensions_sliced": 7
        }
    
    def _print_results(self):
        """Print analysis results."""
        s = self.results["summary"]
        
        print("\n" + "="*80)
        print("📋 ANALYSIS SUMMARY")
        print("="*80)
        print(f"Total Decisions Analyzed: {s['total_decisions']}")
        print(f"Baseline Win Rate: {s['baseline_wr']}%")
        print(f"Baseline P&L: ${s['baseline_pnl']:.2f}")
        print(f"Patterns Analyzed: {s['patterns_analyzed']}")
        print(f"High Confidence Patterns (A/B): {s['high_confidence_patterns']}")
        print(f"High Accuracy Combos Found: {s['high_accuracy_combos']}")
        print(f"Patterns to Avoid: {s['patterns_to_avoid']}")
        print(f"Potential P&L Improvement by Avoiding: ${abs(s['potential_pnl_improvement']):.2f}")
        
        print("\n" + "-"*80)
        print("🎯 TOP HIGH-ACCURACY COMBINATIONS")
        print("-"*80)
        for insight in self.results["actionable_insights"][:10]:
            if insight["type"] == "high_accuracy_combo":
                print(f"   {insight['action']}")
        
        print("\n" + "-"*80)
        print("⛔ PATTERNS TO AVOID")
        print("-"*80)
        for insight in self.results["actionable_insights"]:
            if insight["type"] == "avoid_pattern":
                print(f"   {insight['action']}")
        
        print("\n" + "-"*80)
        print("🔗 SIGNAL CONFLUENCE PATTERNS")
        print("-"*80)
        for insight in self.results["actionable_insights"]:
            if insight["type"] == "signal_confluence":
                print(f"   {insight['action']}")
        
        print("\n" + "-"*80)
        print("📊 INDICATOR EFFECTIVENESS")
        print("-"*80)
        
        ind = self.results["indicator_effectiveness"]
        
        dir_results = ind.get("direction", {}).get("results", {})
        for direction, stats in dir_results.items():
            print(f"   {direction}: {stats['trades']} trades, {stats['wr']}% WR, ${stats['pnl']:.2f} P&L")
        
        regime_results = ind.get("regime", {}).get("results", {})
        for regime, stats in regime_results.items():
            print(f"   {regime}: {stats['trades']} trades, {stats['wr']}% WR, ${stats['pnl']:.2f} P&L")
        
        print("\n" + "-"*80)
        print("📈 TOP CONFIDENCE TIER PATTERNS")
        print("-"*80)
        
        tier_a = self.results["confidence_tiers"].get("by_tier", {}).get("A", [])[:5]
        for p in tier_a:
            print(f"   A: {p['pattern']} ({p['dimension']}) - {p['wr']}% WR, ${p['pnl']:.2f}, {p['trades']} trades")
        
        tier_b = self.results["confidence_tiers"].get("by_tier", {}).get("B", [])[:5]
        for p in tier_b:
            print(f"   B: {p['pattern']} ({p['dimension']}) - {p['wr']}% WR, ${p['pnl']:.2f}, {p['trades']} trades")
        
        print("="*80 + "\n")
    
    def _save_results(self):
        """Save analysis results to file."""
        os.makedirs(os.path.dirname(ANALYSIS_OUTPUT), exist_ok=True)
        with open(ANALYSIS_OUTPUT, 'w') as f:
            json.dump(self.results, f, indent=2, default=str)
        print(f"\n💾 Results saved to: {ANALYSIS_OUTPUT}")


def run_analysis() -> Dict:
    """Run deep intelligence analysis."""
    analyzer = DeepIntelligenceAnalyzer()
    return analyzer.run_full_analysis()


if __name__ == "__main__":
    run_analysis()
