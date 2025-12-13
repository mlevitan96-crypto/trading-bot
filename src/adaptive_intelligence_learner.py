#!/usr/bin/env python3
"""
ADAPTIVE INTELLIGENCE LEARNER
==============================
Comprehensive learning system that:
1. Tracks both inverted and original signal outcomes
2. Learns when to invert vs when to follow the trend
3. Provides multi-angle review capabilities
4. Self-adjusts rules based on live performance

The system doesn't blindly invert - it learns optimal conditions for each action.
"""

import json
import os
import tempfile
import shutil
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

try:
    from src.infrastructure.path_registry import PathRegistry
    LEARNING_LOG_PATH = PathRegistry.get_path("logs", "adaptive_learning.jsonl")
    REVIEW_ANALYSIS_PATH = PathRegistry.get_path("feature_store", "adaptive_review.json")
    PROMOTED_RULES_PATH = PathRegistry.get_path("feature_store", "promoted_intelligence_rules.json")
    ENRICHED_DECISIONS_PATH = PathRegistry.get_path("logs", "enriched_decisions.jsonl")
except ImportError:
    LEARNING_LOG_PATH = "logs/adaptive_learning.jsonl"
    REVIEW_ANALYSIS_PATH = "feature_store/adaptive_review.json"
    PROMOTED_RULES_PATH = "feature_store/promoted_intelligence_rules.json"
    ENRICHED_DECISIONS_PATH = "logs/enriched_decisions.jsonl"

try:
    from src.infrastructure.shutdown_manager import protected_write
except ImportError:
    from contextlib import contextmanager
    @contextmanager
    def protected_write():
        yield


MAX_LOG_ENTRIES = 50000

class AdaptiveIntelligenceLearner:
    """
    Tracks all signals with both inverted and original outcomes,
    learns optimal conditions for inversion vs following.
    """
    
    def __init__(self):
        self.learning_log = []
        self.load_learning_log()
    
    def load_learning_log(self):
        """Load existing learning log with memory-safe limits."""
        if os.path.exists(LEARNING_LOG_PATH):
            try:
                entries = []
                with open(LEARNING_LOG_PATH, "r") as f:
                    for line in f:
                        if line.strip():
                            entries.append(json.loads(line))
                            if len(entries) >= MAX_LOG_ENTRIES:
                                break
                self.learning_log = entries[-MAX_LOG_ENTRIES:]
            except Exception as e:
                print(f"[ADAPTIVE] Failed to load learning log: {e}")
                self.learning_log = []
    
    def log_decision(
        self,
        symbol: str,
        original_direction: str,
        executed_direction: str,
        inverted: bool,
        inversion_reason: Optional[str],
        signal_context: Dict,
        outcome: Optional[Dict] = None
    ):
        """
        Log a trading decision with full context for learning.
        
        Args:
            symbol: Trading symbol
            original_direction: Original signal direction
            executed_direction: Actually executed direction
            inverted: Whether we inverted the signal
            inversion_reason: Why we inverted (or didn't)
            signal_context: Full signal context (OFI, ensemble, regime, etc.)
            outcome: Trade outcome if known (pnl, exit_price, etc.)
        """
        entry = {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "symbol": symbol,
            "original_direction": original_direction,
            "executed_direction": executed_direction,
            "inverted": inverted,
            "inversion_reason": inversion_reason,
            "signal_context": signal_context,
            "outcome": outcome,
            "counterfactual": {
                "if_inverted_pnl": None,
                "if_followed_pnl": None
            }
        }
        
        self._append_log(entry)
        return entry
    
    def update_outcome(
        self,
        symbol: str,
        timestamp: str,
        outcome: Dict,
        counterfactual_pnl: Optional[float] = None
    ):
        """Update a decision with actual outcome and counterfactual."""
        for i, entry in enumerate(reversed(self.learning_log)):
            if entry["symbol"] == symbol and entry["timestamp"] == timestamp:
                entry["outcome"] = outcome
                
                if counterfactual_pnl is not None:
                    if entry["inverted"]:
                        entry["counterfactual"]["if_followed_pnl"] = counterfactual_pnl
                        entry["counterfactual"]["if_inverted_pnl"] = outcome.get("pnl", 0)
                    else:
                        entry["counterfactual"]["if_inverted_pnl"] = counterfactual_pnl
                        entry["counterfactual"]["if_followed_pnl"] = outcome.get("pnl", 0)
                
                self._rewrite_log()
                return True
        return False
    
    def _append_log(self, entry: Dict):
        """Append entry to learning log with memory-safe enforcement."""
        self.learning_log.append(entry)
        try:
            with open(LEARNING_LOG_PATH, "a") as f:
                f.write(json.dumps(entry) + "\n")
        except Exception as e:
            print(f"[ADAPTIVE] Failed to append log: {e}")
        
        if len(self.learning_log) > MAX_LOG_ENTRIES:
            trim_count = len(self.learning_log) - MAX_LOG_ENTRIES
            self.learning_log = self.learning_log[trim_count:]
            self._rewrite_log()
    
    def _rewrite_log(self):
        """
        Rewrite entire learning log (for updates).
        Uses atomic write pattern to prevent corruption on shutdown:
        1. Write to temp file
        2. Sync to disk
        3. Atomic rename
        """
        try:
            with protected_write():
                dir_name = os.path.dirname(LEARNING_LOG_PATH)
                os.makedirs(dir_name, exist_ok=True)
                
                fd, temp_path = tempfile.mkstemp(
                    suffix='.tmp',
                    prefix='adaptive_learning_',
                    dir=dir_name
                )
                try:
                    with os.fdopen(fd, 'w') as f:
                        for entry in self.learning_log:
                            f.write(json.dumps(entry) + "\n")
                        f.flush()
                        os.fsync(f.fileno())
                    
                    shutil.move(temp_path, LEARNING_LOG_PATH)
                except Exception:
                    if os.path.exists(temp_path):
                        os.unlink(temp_path)
                    raise
        except Exception as e:
            print(f"[ADAPTIVE] Failed to rewrite log: {e}")
    
    def analyze_multi_angle(self, min_samples: int = 30) -> Dict:
        """
        Comprehensive multi-angle analysis of all decisions.
        
        Returns analysis from multiple perspectives:
        - By symbol
        - By direction
        - By inversion decision
        - By OFI bucket
        - By ensemble bucket
        - By regime
        - By time of day
        - By trend conditions
        """
        entries_with_outcome = [e for e in self.learning_log if e.get("outcome")]
        
        if not entries_with_outcome:
            entries_with_outcome = self._load_enriched_decisions()
        
        analysis = {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "total_decisions": len(entries_with_outcome),
            "by_symbol": self._analyze_dimension(entries_with_outcome, "symbol", min_samples),
            "by_direction": self._analyze_dimension(entries_with_outcome, "direction", min_samples),
            "by_inversion": self._analyze_inversion(entries_with_outcome, min_samples),
            "by_ofi_bucket": self._analyze_dimension(entries_with_outcome, "ofi_bucket", min_samples),
            "by_ensemble_bucket": self._analyze_dimension(entries_with_outcome, "ensemble_bucket", min_samples),
            "by_regime": self._analyze_dimension(entries_with_outcome, "regime", min_samples),
            "by_session": self._analyze_dimension(entries_with_outcome, "session", min_samples),
            "by_symbol_direction": self._analyze_cross_dimension(entries_with_outcome, ["symbol", "direction"], min_samples),
            "by_symbol_ofi": self._analyze_cross_dimension(entries_with_outcome, ["symbol", "ofi_bucket"], min_samples),
            "trend_following_analysis": self._analyze_trend_conditions(entries_with_outcome),
            "inversion_recommendations": self._generate_recommendations(entries_with_outcome),
            "adaptation_rules": self._generate_adaptation_rules(entries_with_outcome, min_samples)
        }
        
        self._save_analysis(analysis)
        return analysis
    
    def _load_enriched_decisions(self) -> List[Dict]:
        """Load enriched decisions and normalize to analysis format."""
        if not os.path.exists(ENRICHED_DECISIONS_PATH):
            return []
        
        decisions = []
        try:
            with open(ENRICHED_DECISIONS_PATH, "r") as f:
                for line in f:
                    if line.strip():
                        d = json.loads(line)
                        decisions.append(self._normalize_decision(d))
        except Exception as e:
            print(f"[ADAPTIVE] Failed to load enriched decisions: {e}")
        
        return decisions
    
    def _normalize_decision(self, d: Dict) -> Dict:
        """Normalize enriched decision to analysis format."""
        ctx = d.get("signal_ctx", {})
        outcome = d.get("outcome", {})
        
        direction = ctx.get("side", "UNKNOWN").upper()
        if direction == "BUY":
            direction = "LONG"
        elif direction == "SELL":
            direction = "SHORT"
        
        ofi = abs(ctx.get("ofi", 0.5))
        if ofi < 0.3:
            ofi_bucket = "weak"
        elif ofi < 0.5:
            ofi_bucket = "moderate"
        elif ofi < 0.7:
            ofi_bucket = "strong"
        else:
            ofi_bucket = "very_strong"
        
        ensemble = ctx.get("ensemble", 0)
        if ensemble < -0.05:
            ensemble_bucket = "bearish"
        elif ensemble > 0.05:
            ensemble_bucket = "bullish"
        else:
            ensemble_bucket = "neutral"
        
        ts = d.get("ts", 0)
        if ts:
            try:
                dt = datetime.fromtimestamp(ts)
                hour = dt.hour
                if 0 <= hour < 8:
                    session = "asia"
                elif 8 <= hour < 14:
                    session = "europe"
                elif 14 <= hour < 21:
                    session = "us"
                else:
                    session = "evening"
            except:
                session = "unknown"
        else:
            session = "unknown"
        
        return {
            "symbol": d.get("symbol", "UNKNOWN"),
            "direction": direction,
            "inverted": False,
            "ofi_bucket": ofi_bucket,
            "ensemble_bucket": ensemble_bucket,
            "regime": ctx.get("regime", "unknown"),
            "session": session,
            "outcome": {
                "pnl": outcome.get("pnl_usd", 0),
                "pnl_pct": outcome.get("pnl_pct", 0)
            }
        }
    
    def _analyze_dimension(self, entries: List[Dict], dimension: str, min_samples: int) -> Dict:
        """Analyze performance by a single dimension."""
        buckets = defaultdict(lambda: {"wins": 0, "losses": 0, "pnl": 0, "count": 0})
        
        for e in entries:
            if dimension == "direction":
                key = e.get("direction", e.get("original_direction", "UNKNOWN"))
            else:
                key = e.get(dimension, e.get("signal_context", {}).get(dimension, "unknown"))
            
            pnl = e.get("outcome", {}).get("pnl", 0)
            buckets[key]["count"] += 1
            buckets[key]["pnl"] += pnl
            if pnl > 0:
                buckets[key]["wins"] += 1
            elif pnl < 0:
                buckets[key]["losses"] += 1
        
        result = {}
        for key, data in buckets.items():
            if data["count"] >= min_samples:
                total = data["wins"] + data["losses"]
                result[key] = {
                    "count": data["count"],
                    "win_rate": data["wins"] / total * 100 if total > 0 else 0,
                    "total_pnl": round(data["pnl"], 2),
                    "avg_pnl": round(data["pnl"] / data["count"], 2) if data["count"] > 0 else 0,
                    "inverted_wr_potential": 100 - (data["wins"] / total * 100) if total > 0 else 0
                }
        
        return dict(sorted(result.items(), key=lambda x: x[1]["total_pnl"], reverse=True))
    
    def _analyze_cross_dimension(self, entries: List[Dict], dimensions: List[str], min_samples: int) -> Dict:
        """Analyze performance across multiple dimensions."""
        buckets = defaultdict(lambda: {"wins": 0, "losses": 0, "pnl": 0, "count": 0})
        
        for e in entries:
            keys = []
            for dim in dimensions:
                if dim == "direction":
                    keys.append(e.get("direction", e.get("original_direction", "UNKNOWN")))
                else:
                    keys.append(str(e.get(dim, e.get("signal_context", {}).get(dim, "unknown"))))
            
            key = "|".join(keys)
            pnl = e.get("outcome", {}).get("pnl", 0)
            buckets[key]["count"] += 1
            buckets[key]["pnl"] += pnl
            if pnl > 0:
                buckets[key]["wins"] += 1
            elif pnl < 0:
                buckets[key]["losses"] += 1
        
        result = {}
        for key, data in buckets.items():
            if data["count"] >= min_samples:
                total = data["wins"] + data["losses"]
                wr = data["wins"] / total * 100 if total > 0 else 0
                result[key] = {
                    "count": data["count"],
                    "win_rate": round(wr, 1),
                    "total_pnl": round(data["pnl"], 2),
                    "avg_pnl": round(data["pnl"] / data["count"], 2) if data["count"] > 0 else 0,
                    "inversion_potential": round(100 - wr, 1),
                    "should_invert": wr < 40
                }
        
        return dict(sorted(result.items(), key=lambda x: x[1]["total_pnl"], reverse=True))
    
    def _analyze_inversion(self, entries: List[Dict], min_samples: int) -> Dict:
        """Analyze effectiveness of inversion decisions."""
        inverted = {"wins": 0, "losses": 0, "pnl": 0, "count": 0}
        followed = {"wins": 0, "losses": 0, "pnl": 0, "count": 0}
        
        for e in entries:
            pnl = e.get("outcome", {}).get("pnl", 0)
            bucket = inverted if e.get("inverted") else followed
            bucket["count"] += 1
            bucket["pnl"] += pnl
            if pnl > 0:
                bucket["wins"] += 1
            elif pnl < 0:
                bucket["losses"] += 1
        
        result = {}
        for name, data in [("inverted", inverted), ("followed_original", followed)]:
            if data["count"] >= min_samples:
                total = data["wins"] + data["losses"]
                result[name] = {
                    "count": data["count"],
                    "win_rate": data["wins"] / total * 100 if total > 0 else 0,
                    "total_pnl": round(data["pnl"], 2),
                    "avg_pnl": round(data["pnl"] / data["count"], 2) if data["count"] > 0 else 0
                }
        
        return result
    
    def _analyze_trend_conditions(self, entries: List[Dict]) -> Dict:
        """Analyze when to follow trend vs invert based on market conditions."""
        conditions = defaultdict(lambda: {"follow_wins": 0, "invert_wins": 0, "count": 0})
        
        for e in entries:
            ensemble = e.get("signal_context", {}).get("ensemble", e.get("ensemble_bucket", "neutral"))
            if isinstance(ensemble, (int, float)):
                if ensemble > 0.1:
                    trend = "strong_trend"
                elif ensemble > 0.05:
                    trend = "mild_trend"
                elif ensemble < -0.05:
                    trend = "counter_trend"
                else:
                    trend = "no_trend"
            else:
                trend = ensemble
            
            pnl = e.get("outcome", {}).get("pnl", 0)
            direction = e.get("direction", e.get("original_direction", ""))
            
            conditions[trend]["count"] += 1
            
            if pnl > 0:
                if e.get("inverted"):
                    conditions[trend]["invert_wins"] += 1
                else:
                    conditions[trend]["follow_wins"] += 1
        
        result = {}
        for condition, data in conditions.items():
            if data["count"] >= 5:
                total_wins = data["follow_wins"] + data["invert_wins"]
                result[condition] = {
                    "count": data["count"],
                    "follow_wr": data["follow_wins"] / data["count"] * 100 if data["count"] > 0 else 0,
                    "invert_wr": data["invert_wins"] / data["count"] * 100 if data["count"] > 0 else 0,
                    "recommendation": "follow" if data["follow_wins"] > data["invert_wins"] else "invert"
                }
        
        return result
    
    def _generate_recommendations(self, entries: List[Dict]) -> List[Dict]:
        """Generate actionable recommendations based on analysis."""
        recommendations = []
        
        symbol_stats = defaultdict(lambda: {"buy_wins": 0, "buy_losses": 0, "sell_wins": 0, "sell_losses": 0})
        
        for e in entries:
            symbol = e.get("symbol", "UNKNOWN")
            direction = e.get("direction", e.get("original_direction", "")).upper()
            pnl = e.get("outcome", {}).get("pnl", 0)
            
            if direction in ("LONG", "BUY"):
                if pnl > 0:
                    symbol_stats[symbol]["buy_wins"] += 1
                else:
                    symbol_stats[symbol]["buy_losses"] += 1
            elif direction in ("SHORT", "SELL"):
                if pnl > 0:
                    symbol_stats[symbol]["sell_wins"] += 1
                else:
                    symbol_stats[symbol]["sell_losses"] += 1
        
        MIN_SAMPLES_FOR_INVERSION = 30  # Statistical minimum to avoid overfitting noise
        INVERSION_THRESHOLD_WR = 35.0    # Only invert when WR is clearly bad
        
        for symbol, stats in symbol_stats.items():
            buy_total = stats["buy_wins"] + stats["buy_losses"]
            sell_total = stats["sell_wins"] + stats["sell_losses"]
            
            if buy_total >= MIN_SAMPLES_FOR_INVERSION:
                buy_wr = stats["buy_wins"] / buy_total * 100
                if buy_wr < INVERSION_THRESHOLD_WR:
                    recommendations.append({
                        "type": "invert_direction",
                        "symbol": symbol,
                        "direction": "BUY",
                        "current_wr": round(buy_wr, 1),
                        "inverted_wr": round(100 - buy_wr, 1),
                        "sample_size": buy_total,
                        "action": f"INVERT {symbol} BUY signals (WR: {buy_wr:.0f}% -> {100-buy_wr:.0f}%)"
                    })
                elif buy_wr > 60:
                    recommendations.append({
                        "type": "follow_direction",
                        "symbol": symbol,
                        "direction": "BUY",
                        "current_wr": round(buy_wr, 1),
                        "sample_size": buy_total,
                        "action": f"FOLLOW {symbol} BUY signals (WR: {buy_wr:.0f}%)"
                    })
            
            if sell_total >= MIN_SAMPLES_FOR_INVERSION:
                sell_wr = stats["sell_wins"] / sell_total * 100
                if sell_wr < INVERSION_THRESHOLD_WR:
                    recommendations.append({
                        "type": "invert_direction",
                        "symbol": symbol,
                        "direction": "SELL",
                        "current_wr": round(sell_wr, 1),
                        "inverted_wr": round(100 - sell_wr, 1),
                        "sample_size": sell_total,
                        "action": f"INVERT {symbol} SELL signals (WR: {sell_wr:.0f}% -> {100-sell_wr:.0f}%)"
                    })
                elif sell_wr > 60:
                    recommendations.append({
                        "type": "follow_direction",
                        "symbol": symbol,
                        "direction": "SELL",
                        "current_wr": round(sell_wr, 1),
                        "sample_size": sell_total,
                        "action": f"FOLLOW {symbol} SELL signals (WR: {sell_wr:.0f}%)"
                    })
        
        return sorted(recommendations, key=lambda x: x.get("sample_size", 0), reverse=True)
    
    def _generate_adaptation_rules(self, entries: List[Dict], min_samples: int) -> Dict:
        """Generate adaptive rules that know when to invert vs follow."""
        rules = {
            "default_action": "INVERT",
            "symbol_overrides": {},
            "condition_overrides": []
        }
        
        symbol_direction_stats = defaultdict(lambda: {"wins": 0, "losses": 0, "pnl": 0})
        
        for e in entries:
            symbol = e.get("symbol", "UNKNOWN")
            direction = e.get("direction", e.get("original_direction", "")).upper()
            if direction == "BUY":
                direction = "LONG"
            elif direction == "SELL":
                direction = "SHORT"
            
            pnl = e.get("outcome", {}).get("pnl", 0)
            key = f"{symbol}|{direction}"
            
            symbol_direction_stats[key]["pnl"] += pnl
            if pnl > 0:
                symbol_direction_stats[key]["wins"] += 1
            else:
                symbol_direction_stats[key]["losses"] += 1
        
        for key, stats in symbol_direction_stats.items():
            total = stats["wins"] + stats["losses"]
            if total >= min_samples:
                symbol, direction = key.split("|")
                wr = stats["wins"] / total * 100
                
                if symbol not in rules["symbol_overrides"]:
                    rules["symbol_overrides"][symbol] = {}
                
                if wr > 55:
                    rules["symbol_overrides"][symbol][direction] = {
                        "action": "FOLLOW",
                        "win_rate": round(wr, 1),
                        "sample_size": total,
                        "reason": f"Good WR ({wr:.0f}%) - follow signal"
                    }
                elif wr < 35:
                    rules["symbol_overrides"][symbol][direction] = {
                        "action": "INVERT",
                        "win_rate": round(wr, 1),
                        "inverted_wr": round(100 - wr, 1),
                        "sample_size": total,
                        "reason": f"Low WR ({wr:.0f}%) - invert for {100-wr:.0f}%"
                    }
                else:
                    rules["symbol_overrides"][symbol][direction] = {
                        "action": "NEUTRAL",
                        "win_rate": round(wr, 1),
                        "sample_size": total,
                        "reason": f"Moderate WR ({wr:.0f}%) - use other factors"
                    }
        
        return rules
    
    def _save_analysis(self, analysis: Dict):
        """Save analysis to file."""
        try:
            with open(REVIEW_ANALYSIS_PATH, "w") as f:
                json.dump(analysis, f, indent=2)
            print(f"[ADAPTIVE] Analysis saved to {REVIEW_ANALYSIS_PATH}")
        except Exception as e:
            print(f"[ADAPTIVE] Failed to save analysis: {e}")
    
    def update_promoted_rules(self, adaptation_rules: Dict):
        """Update promoted intelligence rules based on adaptive learning."""
        try:
            if os.path.exists(PROMOTED_RULES_PATH):
                with open(PROMOTED_RULES_PATH, "r") as f:
                    rules = json.load(f)
            else:
                rules = {}
            
            rules["adaptation_layer"] = {
                "updated_at": datetime.utcnow().isoformat() + "Z",
                "symbol_overrides": adaptation_rules.get("symbol_overrides", {}),
                "condition_overrides": adaptation_rules.get("condition_overrides", [])
            }
            
            with open(PROMOTED_RULES_PATH, "w") as f:
                json.dump(rules, f, indent=2)
            
            print("[ADAPTIVE] Updated promoted rules with adaptation layer")
        except Exception as e:
            print(f"[ADAPTIVE] Failed to update promoted rules: {e}")
    
    def print_review_summary(self, analysis: Dict):
        """Print a human-readable review summary."""
        print("=" * 70)
        print("ADAPTIVE INTELLIGENCE REVIEW SUMMARY")
        print("=" * 70)
        
        print(f"\nTotal Decisions Analyzed: {analysis.get('total_decisions', 0)}")
        
        print("\n📊 BY SYMBOL:")
        for symbol, data in list(analysis.get("by_symbol", {}).items())[:10]:
            status = "✅" if data["total_pnl"] > 0 else "❌"
            inv_note = f" (Invert potential: {data['inverted_wr_potential']:.0f}%)" if data["win_rate"] < 40 else ""
            print(f"   {status} {symbol:12} | WR={data['win_rate']:.1f}% | P&L=${data['total_pnl']:8.2f} | n={data['count']}{inv_note}")
        
        print("\n📈 BY DIRECTION:")
        for direction, data in analysis.get("by_direction", {}).items():
            status = "✅" if data["total_pnl"] > 0 else "❌"
            print(f"   {status} {direction:12} | WR={data['win_rate']:.1f}% | P&L=${data['total_pnl']:8.2f}")
        
        print("\n🔄 INVERSION ANALYSIS:")
        for inv_type, data in analysis.get("by_inversion", {}).items():
            status = "✅" if data["total_pnl"] > 0 else "❌"
            print(f"   {status} {inv_type:20} | WR={data['win_rate']:.1f}% | P&L=${data['total_pnl']:8.2f}")
        
        print("\n📊 BY OFI BUCKET:")
        for bucket, data in analysis.get("by_ofi_bucket", {}).items():
            status = "✅" if data["total_pnl"] > 0 else "❌"
            print(f"   {status} {bucket:15} | WR={data['win_rate']:.1f}% | P&L=${data['total_pnl']:8.2f}")
        
        print("\n🎯 TOP RECOMMENDATIONS:")
        for rec in analysis.get("inversion_recommendations", [])[:10]:
            print(f"   → {rec['action']}")
        
        print("\n🔧 ADAPTATION RULES:")
        adapt_rules = analysis.get("adaptation_rules", {})
        print(f"   Default action: {adapt_rules.get('default_action', 'INVERT')}")
        for symbol, directions in list(adapt_rules.get("symbol_overrides", {}).items())[:5]:
            for direction, rule in directions.items():
                print(f"   {symbol} {direction}: {rule['action']} ({rule['reason']})")


def run_adaptive_analysis():
    """Run comprehensive adaptive analysis and print results."""
    learner = AdaptiveIntelligenceLearner()
    analysis = learner.analyze_multi_angle(min_samples=30)  # Statistical minimum
    learner.print_review_summary(analysis)
    
    if analysis.get("adaptation_rules"):
        learner.update_promoted_rules(analysis["adaptation_rules"])
    
    return analysis


if __name__ == "__main__":
    run_adaptive_analysis()
