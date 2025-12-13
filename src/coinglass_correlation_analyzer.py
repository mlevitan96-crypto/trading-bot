"""
CoinGlass-to-Trade Correlation Analyzer

Analyzes correlations between:
1. CoinGlass market intelligence (Taker flow, Liquidations, Fear/Greed)
2. Internal technical signals (OFI, Ensemble, Regime)
3. Trade outcomes (P&L, Win/Loss)

Discovers which CoinGlass signals predict winning trades.
"""

import json
import os
import math
from datetime import datetime, timedelta
from typing import Dict, List, Tuple, Optional, Any
from collections import defaultdict
from pathlib import Path

ENRICHED_DECISIONS = "logs/enriched_decisions.jsonl"
INTELLIGENCE_CACHE = "feature_store/intelligence/latest_snapshot.json"
CORRELATION_OUTPUT = "feature_store/coinglass_correlations.json"

import sys
sys.path.insert(0, '/home/runner/workspace')

HAS_MARKET_INTEL = False
SYMBOLS = ['BTC', 'ETH', 'SOL', 'BNB', 'AVAX', 'DOT', 'XRP', 'ADA', 'DOGE', 'MATIC', 'TRX', 'LINK', 'ARB', 'OP', 'PEPE']

try:
    from src.market_intelligence import (
        get_taker_buy_sell, 
        get_liquidations, 
        get_fear_greed
    )
    HAS_MARKET_INTEL = True
    print("   [OK] Market intelligence module loaded")
except ImportError as e:
    print(f"   [WARN] Market intelligence import failed: {e}")


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
                    "symbol": dec.get("symbol", "").replace("USDT", ""),
                    "symbol_full": dec.get("symbol", ""),
                    "direction": signal_ctx.get("side", ""),
                    "ofi": abs(signal_ctx.get("ofi", 0)),
                    "ensemble": signal_ctx.get("ensemble", 0),
                    "roi_expected": signal_ctx.get("roi", 0),
                    "regime": signal_ctx.get("regime", "unknown"),
                    "pnl_usd": outcome.get("pnl_usd", 0),
                    "pnl_pct": outcome.get("pnl_pct", 0),
                    "leverage": outcome.get("leverage", 5),
                    "is_win": outcome.get("pnl_usd", 0) > 0
                })
            except:
                continue
    
    return sorted(decisions, key=lambda x: x.get("ts", 0))


def fetch_current_coinglass() -> Dict:
    """Fetch current CoinGlass market intelligence."""
    if not HAS_MARKET_INTEL:
        print("   [WARN] Market intelligence module not available")
        return {}
    
    print("   Fetching CoinGlass data...")
    
    try:
        taker = get_taker_buy_sell()
        liq = get_liquidations()
        fg = get_fear_greed()
        
        snapshot = {
            "ts": _now(),
            "taker_flow": taker,
            "liquidations": liq,
            "fear_greed": fg
        }
        
        os.makedirs(os.path.dirname(INTELLIGENCE_CACHE), exist_ok=True)
        with open(INTELLIGENCE_CACHE, 'w') as f:
            json.dump(snapshot, f, indent=2)
        
        print(f"   Fetched: {len(taker)} taker, {len(liq)} liq, F&G={fg}")
        return snapshot
    except Exception as e:
        print(f"   [ERROR] Failed to fetch CoinGlass: {e}")
        return {}


def load_cached_intelligence() -> Dict:
    """Load cached intelligence if available."""
    if os.path.exists(INTELLIGENCE_CACHE):
        try:
            with open(INTELLIGENCE_CACHE, 'r') as f:
                return json.load(f)
        except:
            pass
    return {}


def bucket_buy_sell_ratio(ratio: float) -> str:
    """Bucket buy/sell ratio."""
    if ratio > 1.1:
        return "strong_buy"
    elif ratio > 1.02:
        return "buy"
    elif ratio > 0.98:
        return "neutral"
    elif ratio > 0.9:
        return "sell"
    else:
        return "strong_sell"


def bucket_liq_ratio(ratio: float) -> str:
    """Bucket liquidation ratio (long_liq / total)."""
    if ratio > 0.7:
        return "heavy_long_liq"
    elif ratio > 0.55:
        return "more_long_liq"
    elif ratio > 0.45:
        return "balanced"
    elif ratio > 0.3:
        return "more_short_liq"
    else:
        return "heavy_short_liq"


def bucket_fear_greed(fg: int) -> str:
    """Bucket Fear & Greed index."""
    if fg < 25:
        return "extreme_fear"
    elif fg < 45:
        return "fear"
    elif fg < 55:
        return "neutral"
    elif fg < 75:
        return "greed"
    else:
        return "extreme_greed"


class CoinGlassCorrelationAnalyzer:
    """
    Analyzes correlations between CoinGlass data and trade outcomes.
    
    Key questions:
    1. Does high taker buy ratio predict LONG wins?
    2. Do liquidations predict direction?
    3. Does Fear/Greed affect accuracy?
    4. Which CoinGlass + OFI combos work best?
    """
    
    def __init__(self, fetch_fresh: bool = True):
        self.decisions = []
        self.coinglass = {}
        self.results = {
            "run_ts": _now(),
            "data_summary": {},
            "correlations": {},
            "pattern_discoveries": {},
            "recommendations": [],
            "confidence_adjustments": {}
        }
        self.fetch_fresh = fetch_fresh
    
    def run_analysis(self) -> Dict:
        """Run full correlation analysis."""
        print("\n" + "="*80)
        print("🔗 COINGLASS CORRELATION ANALYZER")
        print("="*80)
        print(f"Run time: {_now()}")
        
        self.decisions = load_enriched_decisions()
        print(f"Loaded {len(self.decisions)} enriched decisions")
        
        if self.fetch_fresh:
            self.coinglass = fetch_current_coinglass()
        else:
            self.coinglass = load_cached_intelligence()
        
        if not self.coinglass:
            print("   No CoinGlass data available - using cached patterns")
        
        self._analyze_by_symbol()
        self._analyze_direction_alignment()
        self._analyze_ofi_coinglass_cross()
        self._generate_recommendations()
        self._compute_confidence_adjustments()
        
        self._save_results()
        self._print_results()
        
        return self.results
    
    def _analyze_by_symbol(self):
        """Analyze performance by symbol."""
        print("\n📊 Analyzing by symbol...")
        
        by_symbol = defaultdict(lambda: {"wins": 0, "total": 0, "pnl": 0.0, "directions": {"LONG": {"wins": 0, "total": 0, "pnl": 0}, "SHORT": {"wins": 0, "total": 0, "pnl": 0}}})
        
        for d in self.decisions:
            sym = d["symbol"]
            by_symbol[sym]["total"] += 1
            by_symbol[sym]["pnl"] += d["pnl_usd"]
            if d["is_win"]:
                by_symbol[sym]["wins"] += 1
            
            direction = d["direction"]
            if direction in ["LONG", "SHORT"]:
                by_symbol[sym]["directions"][direction]["total"] += 1
                by_symbol[sym]["directions"][direction]["pnl"] += d["pnl_usd"]
                if d["is_win"]:
                    by_symbol[sym]["directions"][direction]["wins"] += 1
        
        symbol_stats = {}
        for sym, stats in by_symbol.items():
            if stats["total"] >= 5:
                wr = stats["wins"] / stats["total"] * 100
                
                dir_stats = {}
                for dir_name, dir_data in stats["directions"].items():
                    if dir_data["total"] >= 3:
                        dir_wr = dir_data["wins"] / dir_data["total"] * 100 if dir_data["total"] > 0 else 0
                        dir_stats[dir_name] = {
                            "trades": dir_data["total"],
                            "wr": round(dir_wr, 1),
                            "pnl": round(dir_data["pnl"], 2),
                            "better_than_avg": dir_wr > wr
                        }
                
                preferred_dir = None
                if dir_stats:
                    best = max(dir_stats.items(), key=lambda x: x[1]["wr"])
                    if best[1]["wr"] > wr + 5:
                        preferred_dir = best[0]
                
                symbol_stats[sym] = {
                    "trades": stats["total"],
                    "wr": round(wr, 1),
                    "pnl": round(stats["pnl"], 2),
                    "avg_pnl": round(stats["pnl"] / stats["total"], 2),
                    "by_direction": dir_stats,
                    "preferred_direction": preferred_dir
                }
        
        self.results["data_summary"]["by_symbol"] = symbol_stats
        print(f"   Analyzed {len(symbol_stats)} symbols")
    
    def _analyze_direction_alignment(self):
        """Analyze if CoinGlass signals align with trade direction success."""
        print("\n🎯 Analyzing direction alignment with CoinGlass...")
        
        taker = self.coinglass.get("taker_flow", {})
        liq = self.coinglass.get("liquidations", {})
        fg = self.coinglass.get("fear_greed", 50)
        
        fg_bucket = bucket_fear_greed(fg)
        
        alignments = {}
        
        for sym in SYMBOLS:
            sym_decisions = [d for d in self.decisions if d["symbol"] == sym]
            if len(sym_decisions) < 10:
                continue
            
            taker_data = taker.get(sym, {})
            liq_data = liq.get(sym, {})
            
            buy_ratio = taker_data.get("buy_sell_ratio", 1.0)
            liq_ratio = liq_data.get("liq_ratio", 0.5)
            
            buy_bucket = bucket_buy_sell_ratio(buy_ratio)
            liq_bucket = bucket_liq_ratio(liq_ratio)
            
            taker_signal = "LONG" if buy_ratio > 1.02 else "SHORT" if buy_ratio < 0.98 else "NEUTRAL"
            liq_signal = "SHORT" if liq_ratio > 0.55 else "LONG" if liq_ratio < 0.45 else "NEUTRAL"
            
            aligned_trades = []
            misaligned_trades = []
            
            for d in sym_decisions:
                direction = d["direction"]
                
                taker_aligned = (direction == taker_signal) or (taker_signal == "NEUTRAL")
                liq_aligned = (direction == liq_signal) or (liq_signal == "NEUTRAL")
                
                if taker_aligned and liq_aligned:
                    aligned_trades.append(d)
                elif not taker_aligned and not liq_aligned:
                    misaligned_trades.append(d)
            
            if len(aligned_trades) >= 3:
                aligned_wr = sum(1 for d in aligned_trades if d["is_win"]) / len(aligned_trades) * 100
                aligned_pnl = sum(d["pnl_usd"] for d in aligned_trades)
            else:
                aligned_wr = 0
                aligned_pnl = 0
            
            if len(misaligned_trades) >= 3:
                misaligned_wr = sum(1 for d in misaligned_trades if d["is_win"]) / len(misaligned_trades) * 100
                misaligned_pnl = sum(d["pnl_usd"] for d in misaligned_trades)
            else:
                misaligned_wr = 0
                misaligned_pnl = 0
            
            alignments[sym] = {
                "current_taker_signal": taker_signal,
                "current_liq_signal": liq_signal,
                "buy_sell_ratio": round(buy_ratio, 3),
                "liq_ratio": round(liq_ratio, 3),
                "aligned_trades": len(aligned_trades),
                "aligned_wr": round(aligned_wr, 1),
                "aligned_pnl": round(aligned_pnl, 2),
                "misaligned_trades": len(misaligned_trades),
                "misaligned_wr": round(misaligned_wr, 1),
                "misaligned_pnl": round(misaligned_pnl, 2),
                "alignment_helps": aligned_wr > misaligned_wr + 5
            }
        
        self.results["correlations"]["direction_alignment"] = alignments
        self.results["correlations"]["fear_greed"] = {
            "current": fg,
            "bucket": fg_bucket
        }
        
        helpful = sum(1 for a in alignments.values() if a.get("alignment_helps"))
        print(f"   CoinGlass alignment helps for {helpful}/{len(alignments)} symbols")
    
    def _analyze_ofi_coinglass_cross(self):
        """Analyze OFI x CoinGlass signal interactions."""
        print("\n🔬 Analyzing OFI x CoinGlass interactions...")
        
        cross_patterns = {}
        
        taker = self.coinglass.get("taker_flow", {})
        
        ofi_buckets = ["weak", "moderate", "strong", "very_strong", "extreme"]
        direction_buckets = ["LONG", "SHORT"]
        
        for ofi_bucket in ofi_buckets:
            for direction in direction_buckets:
                pattern_key = f"{ofi_bucket}_{direction}"
                
                matching = []
                for d in self.decisions:
                    d_ofi_bucket = "weak" if d["ofi"] < 0.4 else "moderate" if d["ofi"] < 0.6 else "strong" if d["ofi"] < 0.7 else "very_strong" if d["ofi"] < 0.8 else "extreme"
                    if d_ofi_bucket == ofi_bucket and d["direction"] == direction:
                        matching.append(d)
                
                if len(matching) >= 10:
                    wr = sum(1 for d in matching if d["is_win"]) / len(matching) * 100
                    pnl = sum(d["pnl_usd"] for d in matching)
                    
                    by_symbol = defaultdict(list)
                    for d in matching:
                        by_symbol[d["symbol"]].append(d)
                    
                    symbol_breakdown = {}
                    for sym, sym_trades in by_symbol.items():
                        if len(sym_trades) >= 3:
                            sym_wr = sum(1 for d in sym_trades if d["is_win"]) / len(sym_trades) * 100
                            sym_pnl = sum(d["pnl_usd"] for d in sym_trades)
                            symbol_breakdown[sym] = {
                                "trades": len(sym_trades),
                                "wr": round(sym_wr, 1),
                                "pnl": round(sym_pnl, 2)
                            }
                    
                    cross_patterns[pattern_key] = {
                        "ofi_bucket": ofi_bucket,
                        "direction": direction,
                        "trades": len(matching),
                        "wr": round(wr, 1),
                        "pnl": round(pnl, 2),
                        "avg_pnl": round(pnl / len(matching), 2),
                        "by_symbol": symbol_breakdown
                    }
        
        self.results["correlations"]["ofi_direction_cross"] = cross_patterns
        
        profitable = sum(1 for p in cross_patterns.values() if p["pnl"] > 0)
        print(f"   {profitable}/{len(cross_patterns)} OFI x Direction patterns are profitable")
    
    def _generate_recommendations(self):
        """Generate actionable recommendations."""
        print("\n💡 Generating recommendations...")
        
        recommendations = []
        
        symbol_stats = self.results["data_summary"].get("by_symbol", {})
        for sym, stats in symbol_stats.items():
            if stats.get("preferred_direction"):
                recommendations.append({
                    "type": "direction_bias",
                    "symbol": sym,
                    "recommended_direction": stats["preferred_direction"],
                    "reason": f"{sym} performs better on {stats['preferred_direction']} ({stats['by_direction'][stats['preferred_direction']]['wr']}% WR)",
                    "confidence": "high" if stats["by_direction"][stats["preferred_direction"]]["trades"] >= 20 else "medium"
                })
            
            if stats["pnl"] < -30 and stats["trades"] >= 15:
                recommendations.append({
                    "type": "avoid_symbol",
                    "symbol": sym,
                    "reason": f"{sym} has consistent losses (${stats['pnl']:.2f} over {stats['trades']} trades)",
                    "confidence": "high"
                })
        
        alignments = self.results["correlations"].get("direction_alignment", {})
        for sym, data in alignments.items():
            if data.get("alignment_helps") and data["aligned_trades"] >= 5:
                recommendations.append({
                    "type": "use_coinglass_filter",
                    "symbol": sym,
                    "reason": f"CoinGlass alignment improves WR by {data['aligned_wr'] - data['misaligned_wr']:.1f}%",
                    "current_signals": {
                        "taker": data["current_taker_signal"],
                        "liquidation": data["current_liq_signal"]
                    },
                    "confidence": "medium"
                })
        
        cross = self.results["correlations"].get("ofi_direction_cross", {})
        for pattern_key, data in sorted(cross.items(), key=lambda x: x[1]["pnl"], reverse=True)[:5]:
            if data["pnl"] > 10 and data["wr"] >= 25:
                recommendations.append({
                    "type": "boost_pattern",
                    "pattern": pattern_key,
                    "ofi_bucket": data["ofi_bucket"],
                    "direction": data["direction"],
                    "reason": f"{pattern_key}: {data['wr']}% WR, ${data['pnl']:.2f} P&L over {data['trades']} trades",
                    "size_mult": 1.2 if data["wr"] >= 30 else 1.1,
                    "confidence": "high" if data["trades"] >= 30 else "medium"
                })
        
        for pattern_key, data in sorted(cross.items(), key=lambda x: x[1]["pnl"])[:5]:
            if data["pnl"] < -20 and data["trades"] >= 15:
                recommendations.append({
                    "type": "block_pattern",
                    "pattern": pattern_key,
                    "ofi_bucket": data["ofi_bucket"],
                    "direction": data["direction"],
                    "reason": f"{pattern_key}: Lost ${abs(data['pnl']):.2f} over {data['trades']} trades",
                    "size_mult": 0.0,
                    "confidence": "high"
                })
        
        self.results["recommendations"] = recommendations
        print(f"   Generated {len(recommendations)} recommendations")
    
    def _compute_confidence_adjustments(self):
        """Compute confidence adjustments for trading."""
        print("\n🎚️ Computing confidence adjustments...")
        
        adjustments = {}
        
        for rec in self.results["recommendations"]:
            if rec["type"] == "direction_bias":
                sym = rec["symbol"]
                if sym not in adjustments:
                    adjustments[sym] = {"direction_bias": None, "size_mult": 1.0, "block": False}
                adjustments[sym]["direction_bias"] = rec["recommended_direction"]
            
            elif rec["type"] == "avoid_symbol":
                sym = rec["symbol"]
                if sym not in adjustments:
                    adjustments[sym] = {"direction_bias": None, "size_mult": 1.0, "block": False}
                adjustments[sym]["block"] = True
                adjustments[sym]["size_mult"] = 0.0
            
            elif rec["type"] == "boost_pattern":
                pattern = rec["pattern"]
                if pattern not in adjustments:
                    adjustments[pattern] = {"type": "pattern", "size_mult": rec.get("size_mult", 1.0)}
            
            elif rec["type"] == "block_pattern":
                pattern = rec["pattern"]
                if pattern not in adjustments:
                    adjustments[pattern] = {"type": "pattern", "size_mult": 0.0, "block": True}
        
        self.results["confidence_adjustments"] = adjustments
        
        blocks = sum(1 for a in adjustments.values() if a.get("block"))
        boosts = sum(1 for a in adjustments.values() if a.get("size_mult", 1.0) > 1.0)
        print(f"   {boosts} boosts, {blocks} blocks configured")
    
    def _print_results(self):
        """Print analysis results."""
        print("\n" + "="*80)
        print("📋 COINGLASS CORRELATION SUMMARY")
        print("="*80)
        
        print("\n🔹 SYMBOL PERFORMANCE:")
        symbol_stats = self.results["data_summary"].get("by_symbol", {})
        for sym, stats in sorted(symbol_stats.items(), key=lambda x: x[1]["pnl"], reverse=True):
            pref = f" → Prefer {stats['preferred_direction']}" if stats.get("preferred_direction") else ""
            print(f"   {sym:6} | {stats['trades']:3} trades | {stats['wr']:5.1f}% WR | ${stats['pnl']:8.2f} P&L{pref}")
        
        print("\n🔹 DIRECTION ALIGNMENT (CoinGlass signals):")
        alignments = self.results["correlations"].get("direction_alignment", {})
        for sym, data in sorted(alignments.items(), key=lambda x: x[1].get("aligned_wr", 0) - x[1].get("misaligned_wr", 0), reverse=True):
            if data.get("alignment_helps"):
                print(f"   {sym:6} | Aligned: {data['aligned_wr']:.1f}% WR | Misaligned: {data['misaligned_wr']:.1f}% WR | "
                      f"Taker={data['current_taker_signal']} Liq={data['current_liq_signal']}")
        
        print("\n🔹 TOP OFI x DIRECTION PATTERNS:")
        cross = self.results["correlations"].get("ofi_direction_cross", {})
        for key, data in sorted(cross.items(), key=lambda x: x[1]["pnl"], reverse=True)[:10]:
            status = "✅" if data["pnl"] > 0 else "❌"
            print(f"   {status} {key:25} | {data['trades']:3} trades | {data['wr']:5.1f}% WR | ${data['pnl']:8.2f}")
        
        print("\n🔹 TOP RECOMMENDATIONS:")
        for rec in self.results["recommendations"][:15]:
            conf = f"[{rec['confidence']}]"
            print(f"   {rec['type']:20} | {conf:8} | {rec['reason']}")
        
        print("="*80 + "\n")
    
    def _save_results(self):
        """Save analysis results."""
        os.makedirs(os.path.dirname(CORRELATION_OUTPUT), exist_ok=True)
        with open(CORRELATION_OUTPUT, 'w') as f:
            json.dump(self.results, f, indent=2, default=str)
        print(f"\n💾 Results saved to: {CORRELATION_OUTPUT}")


def run_analysis(fetch_fresh: bool = True) -> Dict:
    """Run CoinGlass correlation analysis."""
    analyzer = CoinGlassCorrelationAnalyzer(fetch_fresh=fetch_fresh)
    return analyzer.run_analysis()


if __name__ == "__main__":
    import sys
    fetch = "--cached" not in sys.argv
    run_analysis(fetch_fresh=fetch)
