#!/usr/bin/env python3
"""
Deep Data Analysis - Comprehensive Trade Intelligence
Analyzes every dimension of trading data to find profitable patterns.
"""

import json
import os
from collections import defaultdict
from datetime import datetime
from typing import Dict, List, Any, Tuple
import statistics

class DeepDataAnalysis:
    def __init__(self):
        self.trades = []
        self.signals = []
        self.decisions = []
        self.results = {}
        
    def load_data(self):
        print("=" * 70)
        print("LOADING ALL DATA SOURCES")
        print("=" * 70)
        
        if os.path.exists("logs/portfolio.json"):
            with open("logs/portfolio.json", "r") as f:
                data = json.load(f)
                self.trades = data if isinstance(data, list) else data.get("trades", [])
            print(f"   Loaded {len(self.trades)} trades from portfolio.json")
        
        if os.path.exists("logs/enriched_decisions.jsonl"):
            with open("logs/enriched_decisions.jsonl", "r") as f:
                self.decisions = [json.loads(line) for line in f if line.strip()]
            print(f"   Loaded {len(self.decisions)} enriched decisions")
        
        if os.path.exists("feature_store/signals_universe.jsonl"):
            with open("feature_store/signals_universe.jsonl", "r") as f:
                self.signals = [json.loads(line) for line in f if line.strip()][-5000:]
            print(f"   Loaded {len(self.signals)} signals (last 5000)")
        
        if os.path.exists("logs/alpha/portfolio.json"):
            with open("logs/alpha/portfolio.json", "r") as f:
                alpha_data = json.load(f)
                alpha_trades = alpha_data if isinstance(alpha_data, list) else alpha_data.get("trades", [])
            print(f"   Alpha trades: {len(alpha_trades)}")
            for t in alpha_trades:
                t['bot'] = 'alpha'
            self.trades.extend(alpha_trades)
        
        if os.path.exists("logs/beta/portfolio.json"):
            with open("logs/beta/portfolio.json", "r") as f:
                beta_data = json.load(f)
                beta_trades = beta_data if isinstance(beta_data, list) else beta_data.get("trades", [])
            print(f"   Beta trades: {len(beta_trades)}")
            for t in beta_trades:
                t['bot'] = 'beta'
            self.trades.extend(beta_trades)
        
    def get_pnl(self, trade: Dict) -> float:
        for field in ['pnl', 'profit', 'realized_pnl', 'net_pnl', 'pl']:
            if field in trade:
                try:
                    return float(trade[field])
                except:
                    pass
        return 0.0
    
    def get_ofi(self, trade: Dict) -> float:
        for field in ['ofi', 'ofi_score', 'ofi_confidence']:
            if field in trade:
                try:
                    return abs(float(trade[field]))
                except:
                    pass
        return 0.0
    
    def bucket_ofi(self, ofi: float) -> str:
        if ofi < 0.3:
            return "weak (<0.3)"
        elif ofi < 0.5:
            return "moderate (0.3-0.5)"
        elif ofi < 0.7:
            return "strong (0.5-0.7)"
        elif ofi < 0.9:
            return "very_strong (0.7-0.9)"
        else:
            return "extreme (0.9+)"
    
    def analyze_single_dimension(self, trades: List[Dict], dimension: str, extractor) -> Dict:
        buckets = defaultdict(lambda: {"trades": [], "pnl": 0, "wins": 0, "losses": 0})
        
        for t in trades:
            pnl = self.get_pnl(t)
            if pnl == 0:
                continue
            
            bucket = extractor(t)
            if bucket is None:
                bucket = "unknown"
            
            buckets[bucket]["trades"].append(t)
            buckets[bucket]["pnl"] += pnl
            if pnl > 0:
                buckets[bucket]["wins"] += 1
            else:
                buckets[bucket]["losses"] += 1
        
        results = {}
        for bucket, data in sorted(buckets.items(), key=lambda x: x[1]["pnl"], reverse=True):
            total = data["wins"] + data["losses"]
            if total == 0:
                continue
            
            pnls = [self.get_pnl(t) for t in data["trades"]]
            
            results[bucket] = {
                "n": total,
                "pnl": round(data["pnl"], 2),
                "win_rate": round(data["wins"] / total * 100, 1),
                "avg_pnl": round(data["pnl"] / total, 2),
                "wins": data["wins"],
                "losses": data["losses"],
                "best_trade": round(max(pnls), 2) if pnls else 0,
                "worst_trade": round(min(pnls), 2) if pnls else 0,
                "std_dev": round(statistics.stdev(pnls), 2) if len(pnls) > 1 else 0
            }
        
        return results
    
    def analyze_by_ofi_bucket(self, trades: List[Dict]) -> Dict:
        return self.analyze_single_dimension(
            trades, "OFI Bucket",
            lambda t: self.bucket_ofi(self.get_ofi(t))
        )
    
    def analyze_by_symbol(self, trades: List[Dict]) -> Dict:
        return self.analyze_single_dimension(
            trades, "Symbol",
            lambda t: t.get("symbol", t.get("pair", "unknown"))
        )
    
    def analyze_by_direction(self, trades: List[Dict]) -> Dict:
        return self.analyze_single_dimension(
            trades, "Direction",
            lambda t: t.get("direction", t.get("side", "unknown")).upper()
        )
    
    def analyze_by_session(self, trades: List[Dict]) -> Dict:
        def get_session(t):
            ts = t.get("timestamp", t.get("entry_time", t.get("open_time", "")))
            if not ts:
                return "unknown"
            try:
                if isinstance(ts, (int, float)):
                    dt = datetime.fromtimestamp(ts / 1000 if ts > 1e12 else ts)
                else:
                    dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
                hour = dt.hour
                if 0 <= hour < 6:
                    return "asia_night (0-6 UTC)"
                elif 6 <= hour < 12:
                    return "europe_morning (6-12 UTC)"
                elif 12 <= hour < 18:
                    return "us_afternoon (12-18 UTC)"
                else:
                    return "evening (18-24 UTC)"
            except:
                return "unknown"
        
        return self.analyze_single_dimension(trades, "Session", get_session)
    
    def analyze_by_tier(self, trades: List[Dict]) -> Dict:
        return self.analyze_single_dimension(
            trades, "Tier",
            lambda t: t.get("tier", t.get("signal_tier", t.get("confidence_tier", "unknown")))
        )
    
    def analyze_by_ensemble(self, trades: List[Dict]) -> Dict:
        def get_ensemble_bucket(t):
            score = t.get("ensemble_score", t.get("ensemble", 0))
            try:
                score = float(score)
            except:
                return "unknown"
            if score < -0.3:
                return "strong_bear (<-0.3)"
            elif score < -0.1:
                return "bear (-0.3 to -0.1)"
            elif score < 0.1:
                return "neutral (-0.1 to 0.1)"
            elif score < 0.3:
                return "bull (0.1 to 0.3)"
            else:
                return "strong_bull (>0.3)"
        
        return self.analyze_single_dimension(trades, "Ensemble", get_ensemble_bucket)
    
    def analyze_multi_dimension(self, trades: List[Dict]) -> Dict:
        combos = defaultdict(lambda: {"trades": [], "pnl": 0, "wins": 0, "losses": 0})
        
        for t in trades:
            pnl = self.get_pnl(t)
            if pnl == 0:
                continue
            
            symbol = t.get("symbol", t.get("pair", "UNK"))
            direction = t.get("direction", t.get("side", "UNK")).upper()
            ofi_bucket = self.bucket_ofi(self.get_ofi(t)).split()[0]
            
            key = f"{symbol}|{direction}|{ofi_bucket}"
            combos[key]["trades"].append(t)
            combos[key]["pnl"] += pnl
            if pnl > 0:
                combos[key]["wins"] += 1
            else:
                combos[key]["losses"] += 1
        
        profitable = []
        losing = []
        
        for combo, data in combos.items():
            total = data["wins"] + data["losses"]
            if total < 3:
                continue
            
            pnls = [self.get_pnl(t) for t in data["trades"]]
            result = {
                "pattern": combo,
                "n": total,
                "pnl": round(data["pnl"], 2),
                "win_rate": round(data["wins"] / total * 100, 1),
                "avg_pnl": round(data["pnl"] / total, 2),
                "consistency": round(data["wins"] / total, 2)
            }
            
            if data["pnl"] > 0:
                profitable.append(result)
            else:
                losing.append(result)
        
        profitable.sort(key=lambda x: x["pnl"], reverse=True)
        losing.sort(key=lambda x: x["pnl"])
        
        return {"profitable": profitable[:20], "losing": losing[:20]}
    
    def find_outliers(self, trades: List[Dict]) -> Dict:
        pnls = [(t, self.get_pnl(t)) for t in trades if self.get_pnl(t) != 0]
        if not pnls:
            return {"big_winners": [], "big_losers": []}
        
        pnl_values = [p[1] for p in pnls]
        mean_pnl = statistics.mean(pnl_values)
        std_pnl = statistics.stdev(pnl_values) if len(pnl_values) > 1 else 0
        
        big_winners = []
        big_losers = []
        
        for t, pnl in pnls:
            if std_pnl > 0 and abs(pnl - mean_pnl) > 2 * std_pnl:
                entry = {
                    "symbol": t.get("symbol", t.get("pair", "UNK")),
                    "direction": t.get("direction", t.get("side", "UNK")),
                    "pnl": round(pnl, 2),
                    "ofi": round(self.get_ofi(t), 3),
                    "tier": t.get("tier", t.get("signal_tier", "UNK")),
                    "z_score": round((pnl - mean_pnl) / std_pnl, 2) if std_pnl > 0 else 0
                }
                
                if pnl > 0:
                    big_winners.append(entry)
                else:
                    big_losers.append(entry)
        
        big_winners.sort(key=lambda x: x["pnl"], reverse=True)
        big_losers.sort(key=lambda x: x["pnl"])
        
        return {
            "big_winners": big_winners[:10],
            "big_losers": big_losers[:10],
            "mean_pnl": round(mean_pnl, 2),
            "std_pnl": round(std_pnl, 2)
        }
    
    def analyze_inversion_opportunity(self, trades: List[Dict]) -> Dict:
        by_combo = defaultdict(lambda: {"total": 0, "winners": 0, "pnl": 0})
        
        for t in trades:
            pnl = self.get_pnl(t)
            if pnl == 0:
                continue
            
            symbol = t.get("symbol", t.get("pair", "UNK"))
            direction = t.get("direction", t.get("side", "UNK")).upper()
            key = f"{symbol}|{direction}"
            
            by_combo[key]["total"] += 1
            by_combo[key]["pnl"] += pnl
            if pnl > 0:
                by_combo[key]["winners"] += 1
        
        invert_candidates = []
        keep_candidates = []
        
        for combo, data in by_combo.items():
            if data["total"] < 5:
                continue
            
            win_rate = data["winners"] / data["total"]
            result = {
                "pattern": combo,
                "n": data["total"],
                "win_rate": round(win_rate * 100, 1),
                "pnl": round(data["pnl"], 2),
                "avg_pnl": round(data["pnl"] / data["total"], 2)
            }
            
            if win_rate < 0.35 and data["pnl"] < 0:
                result["inverted_wr"] = round((1 - win_rate) * 100, 1)
                result["recommendation"] = "INVERT"
                invert_candidates.append(result)
            elif win_rate > 0.55 and data["pnl"] > 0:
                result["recommendation"] = "KEEP"
                keep_candidates.append(result)
        
        invert_candidates.sort(key=lambda x: x["win_rate"])
        keep_candidates.sort(key=lambda x: x["pnl"], reverse=True)
        
        return {
            "invert_these": invert_candidates[:15],
            "keep_these": keep_candidates[:15]
        }
    
    def analyze_ofi_threshold_optimization(self, trades: List[Dict]) -> Dict:
        thresholds = [0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9]
        results = []
        
        for threshold in thresholds:
            above = [t for t in trades if self.get_ofi(t) >= threshold and self.get_pnl(t) != 0]
            below = [t for t in trades if self.get_ofi(t) < threshold and self.get_pnl(t) != 0]
            
            above_pnl = sum(self.get_pnl(t) for t in above)
            below_pnl = sum(self.get_pnl(t) for t in below)
            
            above_wr = sum(1 for t in above if self.get_pnl(t) > 0) / len(above) if above else 0
            below_wr = sum(1 for t in below if self.get_pnl(t) > 0) / len(below) if below else 0
            
            results.append({
                "threshold": threshold,
                "above_n": len(above),
                "above_pnl": round(above_pnl, 2),
                "above_wr": round(above_wr * 100, 1),
                "below_n": len(below),
                "below_pnl": round(below_pnl, 2),
                "below_wr": round(below_wr * 100, 1),
                "delta_pnl": round(above_pnl - below_pnl, 2)
            })
        
        best = max(results, key=lambda x: x["above_pnl"] - x["below_pnl"] if x["above_n"] > 10 else -9999)
        
        return {
            "threshold_analysis": results,
            "optimal_threshold": best["threshold"],
            "reasoning": f"At {best['threshold']}, trades above have {best['above_wr']}% WR vs {best['below_wr']}% below"
        }
    
    def generate_actionable_rules(self) -> List[Dict]:
        rules = []
        
        inversion = self.analyze_inversion_opportunity(self.trades)
        for item in inversion["invert_these"][:5]:
            symbol, direction = item["pattern"].split("|")
            rules.append({
                "type": "INVERT",
                "symbol": symbol,
                "direction": direction,
                "reason": f"Win rate {item['win_rate']}% suggests opposite direction would be {item['inverted_wr']}%",
                "expected_improvement": f"From {item['avg_pnl']:.2f} to ~{-item['avg_pnl']:.2f} per trade",
                "confidence": "HIGH" if item["n"] >= 20 else "MEDIUM"
            })
        
        multi = self.analyze_multi_dimension(self.trades)
        for pattern in multi["profitable"][:5]:
            parts = pattern["pattern"].split("|")
            if len(parts) >= 3:
                rules.append({
                    "type": "PREFER",
                    "pattern": pattern["pattern"],
                    "reason": f"Consistent profitability: {pattern['win_rate']}% WR, ${pattern['pnl']} total",
                    "action": "Increase position size for this pattern",
                    "confidence": "HIGH" if pattern["n"] >= 10 else "MEDIUM"
                })
        
        for pattern in multi["losing"][:5]:
            parts = pattern["pattern"].split("|")
            if len(parts) >= 3:
                rules.append({
                    "type": "AVOID",
                    "pattern": pattern["pattern"],
                    "reason": f"Consistent losses: {pattern['win_rate']}% WR, ${pattern['pnl']} total",
                    "action": "Skip or reduce size for this pattern",
                    "confidence": "HIGH" if pattern["n"] >= 10 else "MEDIUM"
                })
        
        return rules
    
    def run_full_analysis(self) -> Dict:
        self.load_data()
        
        if not self.trades:
            print("\n No trades found to analyze!")
            return {}
        
        closed_trades = [t for t in self.trades if t.get("status", "").lower() == "closed" or self.get_pnl(t) != 0]
        print(f"\n   Analyzing {len(closed_trades)} closed trades with P&L data")
        
        print("\n" + "=" * 70)
        print("1. SINGLE DIMENSION ANALYSIS")
        print("=" * 70)
        
        print("\n OFI BUCKET ANALYSIS:")
        print("-" * 60)
        ofi_analysis = self.analyze_by_ofi_bucket(closed_trades)
        for bucket, data in ofi_analysis.items():
            status = "" if data["pnl"] > 0 else ""
            print(f"   {status} {bucket:25} | n={data['n']:4} | WR={data['win_rate']:5.1f}% | P&L=${data['pnl']:8.2f} | Avg=${data['avg_pnl']:6.2f}")
        
        print("\n SYMBOL ANALYSIS:")
        print("-" * 60)
        symbol_analysis = self.analyze_by_symbol(closed_trades)
        for symbol, data in list(symbol_analysis.items())[:15]:
            status = "" if data["pnl"] > 0 else ""
            print(f"   {status} {symbol:12} | n={data['n']:4} | WR={data['win_rate']:5.1f}% | P&L=${data['pnl']:8.2f} | Best=${data['best_trade']:6.2f} | Worst=${data['worst_trade']:6.2f}")
        
        print("\n DIRECTION ANALYSIS:")
        print("-" * 60)
        direction_analysis = self.analyze_by_direction(closed_trades)
        for direction, data in direction_analysis.items():
            status = "" if data["pnl"] > 0 else ""
            print(f"   {status} {direction:8} | n={data['n']:4} | WR={data['win_rate']:5.1f}% | P&L=${data['pnl']:8.2f}")
        
        print("\n SESSION ANALYSIS:")
        print("-" * 60)
        session_analysis = self.analyze_by_session(closed_trades)
        for session, data in session_analysis.items():
            status = "" if data["pnl"] > 0 else ""
            print(f"   {status} {session:25} | n={data['n']:4} | WR={data['win_rate']:5.1f}% | P&L=${data['pnl']:8.2f}")
        
        print("\n TIER ANALYSIS:")
        print("-" * 60)
        tier_analysis = self.analyze_by_tier(closed_trades)
        for tier, data in tier_analysis.items():
            status = "" if data["pnl"] > 0 else ""
            print(f"   {status} Tier {tier:8} | n={data['n']:4} | WR={data['win_rate']:5.1f}% | P&L=${data['pnl']:8.2f}")
        
        print("\n" + "=" * 70)
        print("2. MULTI-DIMENSIONAL PATTERNS")
        print("=" * 70)
        
        multi = self.analyze_multi_dimension(closed_trades)
        
        print("\n PROFITABLE PATTERNS (Symbol|Direction|OFI):")
        print("-" * 60)
        for p in multi["profitable"][:10]:
            print(f"    {p['pattern']:35} | n={p['n']:3} | WR={p['win_rate']:5.1f}% | P&L=${p['pnl']:7.2f}")
        
        print("\n LOSING PATTERNS (Symbol|Direction|OFI):")
        print("-" * 60)
        for p in multi["losing"][:10]:
            print(f"    {p['pattern']:35} | n={p['n']:3} | WR={p['win_rate']:5.1f}% | P&L=${p['pnl']:7.2f}")
        
        print("\n" + "=" * 70)
        print("3. OUTLIER ANALYSIS")
        print("=" * 70)
        
        outliers = self.find_outliers(closed_trades)
        print(f"\n   Mean P&L: ${outliers['mean_pnl']:.2f} | Std Dev: ${outliers['std_pnl']:.2f}")
        
        print("\n BIG WINNERS (>2 std dev):")
        print("-" * 60)
        for o in outliers["big_winners"][:5]:
            print(f"    {o['symbol']:12} {o['direction']:6} | P&L=${o['pnl']:7.2f} | OFI={o['ofi']:.3f} | z={o['z_score']:.1f}")
        
        print("\n BIG LOSERS (>2 std dev):")
        print("-" * 60)
        for o in outliers["big_losers"][:5]:
            print(f"    {o['symbol']:12} {o['direction']:6} | P&L=${o['pnl']:7.2f} | OFI={o['ofi']:.3f} | z={o['z_score']:.1f}")
        
        print("\n" + "=" * 70)
        print("4. INVERSION OPPORTUNITY ANALYSIS")
        print("=" * 70)
        
        inversion = self.analyze_inversion_opportunity(closed_trades)
        
        print("\n CANDIDATES FOR SIGNAL INVERSION:")
        print("-" * 60)
        for item in inversion["invert_these"][:10]:
            print(f"    {item['pattern']:20} | WR={item['win_rate']:5.1f}% → INVERT to {item['inverted_wr']:.1f}% | n={item['n']}")
        
        print("\n PATTERNS TO KEEP (already working):")
        print("-" * 60)
        for item in inversion["keep_these"][:10]:
            print(f"    {item['pattern']:20} | WR={item['win_rate']:5.1f}% | P&L=${item['pnl']:7.2f}")
        
        print("\n" + "=" * 70)
        print("5. OFI THRESHOLD OPTIMIZATION")
        print("=" * 70)
        
        ofi_opt = self.analyze_ofi_threshold_optimization(closed_trades)
        print("\n   Threshold | Above(n) | Above P&L | Above WR | Below(n) | Below P&L | Below WR")
        print("   " + "-" * 75)
        for r in ofi_opt["threshold_analysis"]:
            marker = " <-- OPTIMAL" if r["threshold"] == ofi_opt["optimal_threshold"] else ""
            print(f"      {r['threshold']:.1f}    |   {r['above_n']:4}   | ${r['above_pnl']:8.2f} |  {r['above_wr']:5.1f}%  |   {r['below_n']:4}   | ${r['below_pnl']:8.2f} |  {r['below_wr']:5.1f}%{marker}")
        
        print(f"\n   RECOMMENDATION: Use OFI threshold of {ofi_opt['optimal_threshold']}")
        print(f"   {ofi_opt['reasoning']}")
        
        print("\n" + "=" * 70)
        print("6. ACTIONABLE RULES FOR BOTH STRATEGIES")
        print("=" * 70)
        
        rules = self.generate_actionable_rules()
        
        for i, rule in enumerate(rules, 1):
            print(f"\n   Rule #{i} [{rule['type']}] - {rule['confidence']} confidence")
            if 'symbol' in rule:
                print(f"   Symbol: {rule['symbol']} | Direction: {rule['direction']}")
            elif 'pattern' in rule:
                print(f"   Pattern: {rule['pattern']}")
            print(f"   Reason: {rule['reason']}")
            if 'action' in rule:
                print(f"   Action: {rule['action']}")
            if 'expected_improvement' in rule:
                print(f"   Expected: {rule['expected_improvement']}")
        
        full_results = {
            "timestamp": datetime.now().isoformat(),
            "total_trades_analyzed": len(closed_trades),
            "ofi_analysis": ofi_analysis,
            "symbol_analysis": symbol_analysis,
            "direction_analysis": direction_analysis,
            "session_analysis": session_analysis,
            "tier_analysis": tier_analysis,
            "multi_dimensional": multi,
            "outliers": outliers,
            "inversion_candidates": inversion,
            "ofi_optimization": ofi_opt,
            "actionable_rules": rules
        }
        
        with open("feature_store/deep_data_analysis.json", "w") as f:
            json.dump(full_results, f, indent=2, default=str)
        print(f"\n Full analysis saved to: feature_store/deep_data_analysis.json")
        
        return full_results


if __name__ == "__main__":
    analyzer = DeepDataAnalysis()
    analyzer.run_full_analysis()
