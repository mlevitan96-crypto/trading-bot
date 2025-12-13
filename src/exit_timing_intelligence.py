#!/usr/bin/env python3
"""
EXIT TIMING INTELLIGENCE
========================
Learns optimal exit timing from historical data using MFE/MAE analysis.

Features:
1. Analyze historical data to learn optimal exit timing
2. Calculate max favorable excursion (MFE) per trade pattern
3. Recommend R/R targets based on pattern performance
4. Save learned rules to feature_store/exit_timing_rules.json

KEY INSIGHTS:
- MFE (Max Favorable Excursion) tells us the best price reached during trade
- MAE (Max Adverse Excursion) tells us the worst drawdown during trade
- Optimal exits happen at ~70% of MFE for most patterns

Author: Trading Bot System
Date: December 2025
"""

import json
import os
from datetime import datetime
from typing import Dict, List, Optional, Any, Tuple
from collections import defaultdict
import math

DATA_DIR = "logs"
FEATURE_STORE = "feature_store"
CONFIG_DIR = "config"

EXIT_TIMING_RULES_PATH = os.path.join(FEATURE_STORE, "exit_timing_rules.json")
POSITIONS_FILE = os.path.join(DATA_DIR, "positions_futures.json")
EXIT_RUNTIME_LOG = os.path.join(DATA_DIR, "exit_runtime_events.jsonl")


def _read_json(path: str, default: Any = None) -> Any:
    if not os.path.exists(path):
        return default
    try:
        with open(path, 'r') as f:
            return json.load(f)
    except:
        return default


def _write_json(path: str, data: Any):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp_path = path + ".tmp"
    with open(tmp_path, 'w') as f:
        json.dump(data, f, indent=2, default=str)
    os.replace(tmp_path, path)


def _read_jsonl(path: str) -> List[Dict]:
    if not os.path.exists(path):
        return []
    records = []
    try:
        with open(path, 'r') as f:
            for line in f:
                try:
                    records.append(json.loads(line.strip()))
                except:
                    continue
    except:
        pass
    return records


def _classify_ofi(ofi: float) -> str:
    """Classify OFI into bucket."""
    ofi = abs(ofi)
    if ofi < 0.25:
        return "weak"
    elif ofi < 0.50:
        return "moderate"
    elif ofi < 0.75:
        return "strong"
    elif ofi < 0.90:
        return "very_strong"
    else:
        return "extreme"


class ExitTimingIntelligence:
    """
    Learns optimal exit timing from historical trade data.
    
    Uses MFE (Maximum Favorable Excursion) analysis to determine:
    - Optimal take-profit levels per pattern
    - How much of the potential profit we're capturing
    - Whether we're exiting too early or too late
    """
    
    def __init__(self):
        self.rules: Dict[str, Any] = {}
        self.trades: List[Dict] = []
        self._load_rules()
    
    def _load_rules(self):
        """Load existing rules from feature store."""
        self.rules = _read_json(EXIT_TIMING_RULES_PATH, {})
    
    def load_trades(self) -> List[Dict]:
        """Load trades from positions file and exit runtime log."""
        data = _read_json(POSITIONS_FILE, {})
        closed = data.get("closed_positions", [])
        
        exit_events = _read_jsonl(EXIT_RUNTIME_LOG)
        exit_by_symbol = defaultdict(list)
        for event in exit_events:
            sym = event.get("symbol")
            if sym:
                exit_by_symbol[sym].append(event)
        
        enriched = []
        for trade in closed:
            if trade.get("pnl") is None:
                continue
            
            symbol = trade.get("symbol", "UNKNOWN")
            direction = (trade.get("direction") or trade.get("side") or "UNKNOWN").upper()
            
            peak = trade.get("peak_price")
            trough = trade.get("trough_price")
            entry = trade.get("entry_price")
            exit_price = trade.get("exit_price")
            
            mfe = 0
            mae = 0
            mfe_pct = 0
            mae_pct = 0
            
            if entry and peak and trough and exit_price:
                entry = float(entry)
                exit_price = float(exit_price)
                
                if direction == "LONG":
                    if peak:
                        mfe = (float(peak) - entry) / entry
                    if trough:
                        mae = (entry - float(trough)) / entry
                elif direction == "SHORT":
                    if trough:
                        mfe = (entry - float(trough)) / entry
                    if peak:
                        mae = (float(peak) - entry) / entry
                
                mfe_pct = mfe * 100
                mae_pct = mae * 100
            
            for event in exit_by_symbol.get(symbol, []):
                if event.get("mfe") is not None:
                    mfe = max(mfe, float(event.get("mfe", 0)))
                if event.get("mae") is not None:
                    mae = max(mae, abs(float(event.get("mae", 0))))
            
            trade["mfe"] = mfe
            trade["mae"] = mae
            trade["mfe_pct"] = mfe_pct
            trade["mae_pct"] = mae_pct
            
            actual_roi = float(trade.get("net_roi") or trade.get("final_roi") or 0)
            if mfe > 0:
                trade["capture_ratio"] = actual_roi / mfe if mfe > 0 else 0
            else:
                trade["capture_ratio"] = 0
            
            enriched.append(trade)
        
        self.trades = enriched
        return enriched
    
    def analyze_mfe_by_pattern(self) -> Dict[str, Any]:
        """
        Analyze MFE patterns by symbol+direction+OFI.
        
        Returns optimal exit targets per pattern.
        """
        if not self.trades:
            self.load_trades()
        
        by_pattern = defaultdict(lambda: {
            "trades": 0, "mfes": [], "maes": [], "pnls": [],
            "capture_ratios": [], "durations": []
        })
        
        for trade in self.trades:
            symbol = trade.get("symbol", "UNKNOWN")
            direction = (trade.get("direction") or trade.get("side") or "UNKNOWN").upper()
            ofi = trade.get("ofi_score", 0.5)
            ofi_bucket = _classify_ofi(float(ofi) if ofi else 0.5)
            
            pattern_key = f"{symbol}|{direction}|ofi={ofi_bucket}"
            
            by_pattern[pattern_key]["trades"] += 1
            by_pattern[pattern_key]["mfes"].append(trade.get("mfe", 0))
            by_pattern[pattern_key]["maes"].append(trade.get("mae", 0))
            by_pattern[pattern_key]["pnls"].append(float(trade.get("pnl", 0)))
            by_pattern[pattern_key]["capture_ratios"].append(trade.get("capture_ratio", 0))
        
        results = {}
        for pattern, stats in by_pattern.items():
            if stats["trades"] < 3:
                continue
            
            avg_mfe = sum(stats["mfes"]) / len(stats["mfes"]) if stats["mfes"] else 0
            avg_mae = sum(stats["maes"]) / len(stats["maes"]) if stats["maes"] else 0
            avg_pnl = sum(stats["pnls"]) / len(stats["pnls"]) if stats["pnls"] else 0
            total_pnl = sum(stats["pnls"])
            
            avg_capture = sum(stats["capture_ratios"]) / len(stats["capture_ratios"]) if stats["capture_ratios"] else 0
            
            wins = sum(1 for p in stats["pnls"] if p > 0)
            win_rate = (wins / stats["trades"]) * 100 if stats["trades"] else 0
            
            if avg_mfe > 0 and avg_mae > 0:
                rr_ratio = avg_mfe / avg_mae
            else:
                rr_ratio = 0
            
            optimal_tp1 = avg_mfe * 0.5 if avg_mfe > 0 else 0.005
            optimal_tp2 = avg_mfe * 0.7 if avg_mfe > 0 else 0.010
            optimal_stop = min(avg_mae * 0.8, 0.02) if avg_mae > 0 else 0.005
            
            if total_pnl > 5 and win_rate > 50:
                recommendation = "trade_aggressive"
                size_boost = min(1.5, 1 + (win_rate - 50) / 100)
            elif total_pnl > 0:
                recommendation = "trade_normal"
                size_boost = 1.0
            else:
                recommendation = "reduce_exposure"
                size_boost = max(0.5, 1 - abs(total_pnl) / 50)
            
            results[pattern] = {
                "trades": stats["trades"],
                "wins": wins,
                "win_rate": round(win_rate, 1),
                "total_pnl": round(total_pnl, 2),
                "avg_pnl": round(avg_pnl, 3),
                "avg_mfe_pct": round(avg_mfe * 100, 3),
                "avg_mae_pct": round(avg_mae * 100, 3),
                "rr_ratio": round(rr_ratio, 2),
                "avg_capture_ratio": round(avg_capture, 3),
                "optimal_targets": {
                    "tp1_roi": round(optimal_tp1, 4),
                    "tp2_roi": round(optimal_tp2, 4),
                    "stop_loss_roi": round(-optimal_stop, 4)
                },
                "recommendation": recommendation,
                "size_boost": round(size_boost, 2)
            }
        
        return dict(sorted(results.items(), key=lambda x: x[1]["total_pnl"], reverse=True))
    
    def analyze_exit_timing_quality(self) -> Dict[str, Any]:
        """
        Analyze how well we're timing our exits.
        
        KEY INSIGHT: If capture_ratio < 0.5, we're exiting too early
        If capture_ratio > 1.0, we're letting winners run properly
        """
        if not self.trades:
            self.load_trades()
        
        winners = [t for t in self.trades if float(t.get("pnl", 0)) > 0]
        losers = [t for t in self.trades if float(t.get("pnl", 0)) < 0]
        
        winner_captures = [t.get("capture_ratio", 0) for t in winners]
        loser_mfes = [t.get("mfe", 0) for t in losers]
        
        early_exits = sum(1 for c in winner_captures if 0 < c < 0.5)
        optimal_exits = sum(1 for c in winner_captures if 0.5 <= c <= 0.8)
        late_exits = sum(1 for c in winner_captures if c > 0.8)
        
        missed_profit_losers = sum(1 for m in loser_mfes if m > 0.005)
        
        return {
            "total_trades": len(self.trades),
            "winners": len(winners),
            "losers": len(losers),
            "exit_timing": {
                "early_exits": early_exits,
                "optimal_exits": optimal_exits,
                "late_exits": late_exits,
                "early_exit_pct": round((early_exits / len(winners)) * 100, 1) if winners else 0
            },
            "missed_opportunities": {
                "losers_that_were_winning": missed_profit_losers,
                "pct_of_losers": round((missed_profit_losers / len(losers)) * 100, 1) if losers else 0
            },
            "avg_winner_capture": round(sum(winner_captures) / len(winner_captures), 3) if winner_captures else 0,
            "recommendations": self._generate_exit_recommendations(early_exits, optimal_exits, late_exits, missed_profit_losers)
        }
    
    def _generate_exit_recommendations(self, early: int, optimal: int, late: int, missed: int) -> List[str]:
        """Generate actionable recommendations based on exit analysis."""
        recommendations = []
        
        total = early + optimal + late
        if total == 0:
            return ["Insufficient data for recommendations"]
        
        early_pct = early / total
        late_pct = late / total
        
        if early_pct > 0.4:
            recommendations.append("Too many early exits - increase minimum hold time to 30-45 minutes")
            recommendations.append("Consider using trailing stops instead of fixed take-profit")
        
        if late_pct > 0.3:
            recommendations.append("Letting winners run too long - set tighter take-profit levels")
        
        if missed > 10:
            recommendations.append(f"{missed} losing trades were profitable at some point - improve trailing logic")
        
        if not recommendations:
            recommendations.append("Exit timing is optimal - maintain current strategy")
        
        return recommendations
    
    def generate_per_symbol_targets(self) -> Dict[str, Any]:
        """Generate optimized exit targets per symbol."""
        patterns = self.analyze_mfe_by_pattern()
        
        by_symbol = defaultdict(lambda: {"patterns": [], "trades": 0, "pnl": 0})
        
        for pattern, data in patterns.items():
            parts = pattern.split("|")
            symbol = parts[0] if parts else "UNKNOWN"
            
            by_symbol[symbol]["patterns"].append(pattern)
            by_symbol[symbol]["trades"] += data["trades"]
            by_symbol[symbol]["pnl"] += data["total_pnl"]
        
        targets = {}
        for symbol, stats in by_symbol.items():
            symbol_patterns = [patterns[p] for p in stats["patterns"]]
            
            if not symbol_patterns:
                continue
            
            avg_mfe = sum(p["avg_mfe_pct"] for p in symbol_patterns) / len(symbol_patterns)
            avg_mae = sum(p["avg_mae_pct"] for p in symbol_patterns) / len(symbol_patterns)
            
            targets[symbol] = {
                "total_trades": stats["trades"],
                "total_pnl": round(stats["pnl"], 2),
                "tp1_roi": round(avg_mfe / 100 * 0.5, 4),
                "tp2_roi": round(avg_mfe / 100 * 0.7, 4),
                "stop_loss_roi": round(-avg_mae / 100 * 0.8, 4),
                "min_hold_minutes": 30 if stats["pnl"] > 0 else 20
            }
        
        return targets
    
    def learn_and_save(self) -> Dict[str, Any]:
        """
        Learn optimal exit timing rules and save to feature store.
        """
        self.load_trades()
        
        patterns = self.analyze_mfe_by_pattern()
        timing_quality = self.analyze_exit_timing_quality()
        symbol_targets = self.generate_per_symbol_targets()
        
        top_patterns = []
        for pattern, data in list(patterns.items())[:10]:
            if data["total_pnl"] > 0 and data["win_rate"] > 50:
                top_patterns.append({
                    "pattern": pattern,
                    "pnl": data["total_pnl"],
                    "win_rate": data["win_rate"],
                    "optimal_tp1": data["optimal_targets"]["tp1_roi"],
                    "optimal_tp2": data["optimal_targets"]["tp2_roi"],
                    "size_boost": data["size_boost"]
                })
        
        self.rules = {
            "generated_at": datetime.utcnow().isoformat(),
            "analysis_summary": {
                "total_trades": len(self.trades),
                "patterns_analyzed": len(patterns),
                "symbols_analyzed": len(symbol_targets)
            },
            "timing_quality": timing_quality,
            "top_patterns": top_patterns,
            "per_pattern": patterns,
            "per_symbol_targets": symbol_targets,
            "global_defaults": {
                "tp1_roi": 0.005,
                "tp2_roi": 0.010,
                "stop_loss_roi": -0.005,
                "min_hold_minutes": 30,
                "capture_target": 0.6
            }
        }
        
        _write_json(EXIT_TIMING_RULES_PATH, self.rules)
        
        print(f"[EXIT_TIMING] Analyzed {len(self.trades)} trades across {len(patterns)} patterns")
        print(f"[EXIT_TIMING] Found {len(top_patterns)} profitable patterns")
        print(f"[EXIT_TIMING] Rules saved to {EXIT_TIMING_RULES_PATH}")
        
        return self.rules
    
    def get_optimal_targets(self, symbol: str, direction: str, ofi: float = 0.5) -> Dict[str, float]:
        """
        Get optimal exit targets for a specific trade.
        
        Usage:
            from src.exit_timing_intelligence import get_optimal_targets
            targets = get_optimal_targets("DOTUSDT", "SHORT", ofi=0.8)
            # Returns: {"tp1_roi": 0.006, "tp2_roi": 0.012, "stop_loss_roi": -0.004}
        """
        ofi_bucket = _classify_ofi(ofi)
        pattern_key = f"{symbol}|{direction.upper()}|ofi={ofi_bucket}"
        
        if pattern_key in self.rules.get("per_pattern", {}):
            pattern_data = self.rules["per_pattern"][pattern_key]
            return pattern_data.get("optimal_targets", self.rules.get("global_defaults", {}))
        
        if symbol in self.rules.get("per_symbol_targets", {}):
            symbol_data = self.rules["per_symbol_targets"][symbol]
            return {
                "tp1_roi": symbol_data.get("tp1_roi", 0.005),
                "tp2_roi": symbol_data.get("tp2_roi", 0.010),
                "stop_loss_roi": symbol_data.get("stop_loss_roi", -0.005)
            }
        
        return self.rules.get("global_defaults", {
            "tp1_roi": 0.005,
            "tp2_roi": 0.010,
            "stop_loss_roi": -0.005
        })


_intelligence_instance = None

def get_intelligence() -> ExitTimingIntelligence:
    """Get singleton intelligence instance."""
    global _intelligence_instance
    if _intelligence_instance is None:
        _intelligence_instance = ExitTimingIntelligence()
    return _intelligence_instance


def learn_exit_timing() -> Dict[str, Any]:
    """Learn optimal exit timing from history."""
    intel = get_intelligence()
    return intel.learn_and_save()


def get_optimal_targets(symbol: str, direction: str, ofi: float = 0.5) -> Dict[str, float]:
    """Get optimal exit targets for a trade."""
    intel = get_intelligence()
    return intel.get_optimal_targets(symbol, direction, ofi)


def get_exit_timing_rules() -> Dict[str, Any]:
    """Get cached exit timing rules."""
    return _read_json(EXIT_TIMING_RULES_PATH, {})


if __name__ == "__main__":
    print("=" * 70)
    print("EXIT TIMING INTELLIGENCE")
    print("=" * 70)
    
    intel = ExitTimingIntelligence()
    rules = intel.learn_and_save()
    
    print("\n" + "=" * 70)
    print("TIMING QUALITY ANALYSIS")
    print("=" * 70)
    quality = rules.get("timing_quality", {})
    print(f"  Total trades: {quality.get('total_trades', 0)}")
    print(f"  Winners: {quality.get('winners', 0)}")
    print(f"  Losers: {quality.get('losers', 0)}")
    
    timing = quality.get("exit_timing", {})
    print(f"\n  Exit Timing:")
    print(f"    Early exits: {timing.get('early_exits', 0)}")
    print(f"    Optimal exits: {timing.get('optimal_exits', 0)}")
    print(f"    Late exits: {timing.get('late_exits', 0)}")
    
    print("\n  Recommendations:")
    for rec in quality.get("recommendations", []):
        print(f"    - {rec}")
    
    print("\n" + "=" * 70)
    print("TOP PROFITABLE PATTERNS")
    print("=" * 70)
    for pattern in rules.get("top_patterns", [])[:5]:
        print(f"  {pattern['pattern']}:")
        print(f"    P&L: ${pattern['pnl']:.2f}, WR: {pattern['win_rate']:.1f}%")
        print(f"    Optimal TP1: {pattern['optimal_tp1']*100:.2f}%, TP2: {pattern['optimal_tp2']*100:.2f}%")
        print(f"    Size boost: {pattern['size_boost']:.2f}x")
