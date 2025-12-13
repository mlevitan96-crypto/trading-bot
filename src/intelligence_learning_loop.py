#!/usr/bin/env python3
"""
Intelligence Learning Loop - Closed Feedback System

This module creates a complete feedback loop:
1. ANALYZE: Correlate all intelligence sources with outcomes
2. LEARN: Generate composite rules from patterns
3. APPLY: Feed learned rules into execution decisions
4. VERIFY: Track if learned rules improve outcomes

The learned rules are saved to feature_store/learned_rules.json and
automatically loaded by the execution pipeline.

Usage:
    python src/intelligence_learning_loop.py --learn   # Run learning cycle
    python src/intelligence_learning_loop.py --verify  # Verify improvements
"""

import json
import os
from datetime import datetime, timedelta
from collections import defaultdict
from pathlib import Path
import statistics

from src.data_registry import DataRegistry as DR

LOGS_DIR = "logs"
FEATURE_DIR = "feature_store"
LEARNED_RULES_PATH = DR.LEARNED_RULES
LEARNING_HISTORY_PATH = f"{FEATURE_DIR}/learning_history.jsonl"


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


def save_json(path, data):
    """Save JSON file."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w') as f:
        json.dump(data, f, indent=2)


def append_jsonl(path, record):
    """Append to JSONL file."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'a') as f:
        f.write(json.dumps(record) + "\n")


class IntelligenceLearner:
    """Learns from correlations and generates actionable rules."""
    
    def __init__(self):
        self.enriched = load_jsonl(DR.ENRICHED_DECISIONS)
        self.alpha_trades = load_jsonl(DR.TRADES_CANONICAL)
        self.blocked = self._load_blocked_signals()
        self.current_rules = load_json(LEARNED_RULES_PATH, self._default_rules())
    
    def _load_blocked_signals(self):
        """Load blocked signals from the universal signals file."""
        all_signals = load_jsonl(DR.SIGNALS_UNIVERSE)
        return [s for s in all_signals if s.get("disposition", "").upper() == "BLOCKED"]
    
    def _default_rules(self):
        """Default rules before learning."""
        return {
            "version": 1,
            "generated_at": None,
            "global": {
                "min_ofi": 0.5,
                "min_ensemble": 0.05,
                "require_ofi_alignment": True,
                "min_confidence": 0.3
            },
            "per_symbol": {},
            "per_direction": {
                "LONG": {"min_ofi": 0.5},
                "SHORT": {"min_ofi": 0.5}
            },
            "composite_rules": [],
            "performance_baseline": {
                "win_rate": 0,
                "avg_pnl": 0,
                "trades_analyzed": 0
            }
        }
    
    def analyze_all_data(self):
        """Comprehensive analysis of all intelligence data."""
        print("\n" + "="*70)
        print("📊 COMPREHENSIVE DATA ANALYSIS")
        print("="*70)
        
        analysis = {
            "total_trades": 0,
            "wins": 0,
            "losses": 0,
            "total_pnl": 0,
            "winner_pnls": [],
            "loser_pnls": [],
            "by_symbol_direction": defaultdict(lambda: {"trades": 0, "wins": 0, "pnl": 0, "ofi_sum": 0, "ens_sum": 0, "aligned": 0, "winner_pnls": [], "loser_pnls": []}),
            "by_ofi_range": defaultdict(lambda: {"trades": 0, "wins": 0, "pnl": 0}),
            "by_ensemble_range": defaultdict(lambda: {"trades": 0, "wins": 0, "pnl": 0}),
            "by_alignment": {"aligned": {"trades": 0, "wins": 0, "pnl": 0}, "contrary": {"trades": 0, "wins": 0, "pnl": 0}},
            "by_regime": defaultdict(lambda: {"trades": 0, "wins": 0, "pnl": 0})
        }
        
        for record in self.enriched:
            ctx = record.get("signal_ctx", {})
            outcome = record.get("outcome", {})
            
            symbol = record.get("symbol", "")
            side = ctx.get("side", "")
            ofi = ctx.get("ofi", 0)
            ofi_abs = abs(ofi)
            ensemble = abs(ctx.get("ensemble", 0))
            regime = ctx.get("regime", "Unknown")
            pnl = outcome.get("pnl_usd", 0)
            is_win = pnl > 0
            
            is_aligned = (ofi > 0 and side == "LONG") or (ofi < 0 and side == "SHORT")
            
            analysis["total_trades"] += 1
            analysis["total_pnl"] += pnl
            if is_win:
                analysis["wins"] += 1
                analysis["winner_pnls"].append(pnl)
            else:
                analysis["losses"] += 1
                analysis["loser_pnls"].append(pnl)
            
            key = f"{symbol}_{side}"
            analysis["by_symbol_direction"][key]["trades"] += 1
            analysis["by_symbol_direction"][key]["pnl"] += pnl
            analysis["by_symbol_direction"][key]["ofi_sum"] += ofi_abs
            analysis["by_symbol_direction"][key]["ens_sum"] += ensemble
            if is_win:
                analysis["by_symbol_direction"][key]["wins"] += 1
                analysis["by_symbol_direction"][key]["winner_pnls"].append(pnl)
            else:
                analysis["by_symbol_direction"][key]["loser_pnls"].append(pnl)
            if is_aligned:
                analysis["by_symbol_direction"][key]["aligned"] += 1
            
            ofi_range = self._get_range(ofi_abs, [0, 0.3, 0.5, 0.7, 0.9, 2.0])
            analysis["by_ofi_range"][ofi_range]["trades"] += 1
            analysis["by_ofi_range"][ofi_range]["pnl"] += pnl
            if is_win:
                analysis["by_ofi_range"][ofi_range]["wins"] += 1
            
            ens_range = self._get_range(ensemble, [0, 0.03, 0.06, 0.10, 1.0])
            analysis["by_ensemble_range"][ens_range]["trades"] += 1
            analysis["by_ensemble_range"][ens_range]["pnl"] += pnl
            if is_win:
                analysis["by_ensemble_range"][ens_range]["wins"] += 1
            
            align_key = "aligned" if is_aligned else "contrary"
            analysis["by_alignment"][align_key]["trades"] += 1
            analysis["by_alignment"][align_key]["pnl"] += pnl
            if is_win:
                analysis["by_alignment"][align_key]["wins"] += 1
            
            analysis["by_regime"][regime]["trades"] += 1
            analysis["by_regime"][regime]["pnl"] += pnl
            if is_win:
                analysis["by_regime"][regime]["wins"] += 1
        
        print(f"\n   Analyzed {analysis['total_trades']} trades")
        print(f"   Win Rate: {analysis['wins']/max(1,analysis['total_trades'])*100:.1f}%")
        print(f"   Total P&L: ${analysis['total_pnl']:.2f}")
        
        return analysis
    
    def _get_range(self, value, thresholds):
        """Get range label for a value."""
        for i in range(len(thresholds) - 1):
            if thresholds[i] <= value < thresholds[i + 1]:
                return f"{thresholds[i]:.2f}-{thresholds[i+1]:.2f}"
        return f"{thresholds[-1]:.2f}+"
    
    def generate_learned_rules(self, analysis):
        """Generate rules from analysis."""
        print("\n" + "="*70)
        print("🧠 GENERATING LEARNED RULES")
        print("="*70)
        
        rules = self._default_rules()
        rules["generated_at"] = datetime.now().isoformat()
        rules["version"] = self.current_rules.get("version", 0) + 1
        
        aligned = analysis["by_alignment"]["aligned"]
        contrary = analysis["by_alignment"]["contrary"]
        
        if aligned["trades"] > 5 and contrary["trades"] > 0:
            aligned_wr = aligned["wins"] / aligned["trades"] if aligned["trades"] > 0 else 0
            contrary_wr = contrary["wins"] / contrary["trades"] if contrary["trades"] > 0 else 0
            
            if aligned_wr > contrary_wr:
                rules["global"]["require_ofi_alignment"] = True
                print(f"   ✅ OFI Alignment REQUIRED (aligned WR: {aligned_wr*100:.1f}% vs contrary: {contrary_wr*100:.1f}%)")
            else:
                rules["global"]["require_ofi_alignment"] = False
                print(f"   ⚠️ OFI Alignment NOT required (contrary performs equal or better)")
        
        best_ofi_range = None
        best_ofi_wr = 0
        for range_key, stats in analysis["by_ofi_range"].items():
            if stats["trades"] >= 10:
                wr = stats["wins"] / stats["trades"]
                if wr > best_ofi_wr:
                    best_ofi_wr = wr
                    best_ofi_range = range_key
        
        if best_ofi_range:
            min_ofi = float(best_ofi_range.split("-")[0])
            rules["global"]["min_ofi"] = max(0.3, min_ofi)
            print(f"   ✅ Optimal OFI range: {best_ofi_range} ({best_ofi_wr*100:.1f}% WR)")
        
        for key, stats in analysis["by_symbol_direction"].items():
            if stats["trades"] < 5:
                continue
            
            symbol, direction = key.rsplit("_", 1)
            wr = stats["wins"] / stats["trades"]
            avg_ofi = stats["ofi_sum"] / stats["trades"]
            aligned_pct = stats["aligned"] / stats["trades"]
            
            if symbol not in rules["per_symbol"]:
                rules["per_symbol"][symbol] = {}
            
            avg_winner = sum(stats["winner_pnls"]) / len(stats["winner_pnls"]) if stats["winner_pnls"] else 0
            avg_loser = sum(stats["loser_pnls"]) / len(stats["loser_pnls"]) if stats["loser_pnls"] else 0
            
            rules["per_symbol"][symbol][direction] = {
                "min_ofi": round(avg_ofi * 0.8, 2),
                "win_rate": round(wr * 100, 1),
                "expected_wr": round(wr * 100, 1),
                "require_alignment": aligned_pct > 0.7,
                "trades": stats["trades"],
                "count": stats["trades"],
                "pnl": round(stats["pnl"], 2),
                "total_pnl": round(stats["pnl"], 2),
                "avg_winner": round(avg_winner, 2),
                "avg_loser": round(avg_loser, 2)
            }
            
            status = "✅" if stats["pnl"] > 0 else "⚠️"
            print(f"   {status} {key}: OFI≥{avg_ofi*0.8:.2f}, WR={wr*100:.1f}%, P&L=${stats['pnl']:.2f}")
        
        composite_rules = []
        
        for key, stats in analysis["by_symbol_direction"].items():
            if stats["trades"] >= 10 and stats["pnl"] > 0:
                symbol, direction = key.rsplit("_", 1)
                wr = stats["wins"] / stats["trades"]
                avg_ofi = stats["ofi_sum"] / stats["trades"]
                aligned_pct = stats["aligned"] / stats["trades"]
                
                if wr >= 0.35:
                    composite_rules.append({
                        "id": f"profitable_{key}",
                        "conditions": {
                            "symbol": symbol,
                            "direction": direction,
                            "min_ofi": round(avg_ofi * 0.7, 2),
                            "require_alignment": aligned_pct > 0.6
                        },
                        "action": {
                            "sizing_multiplier": min(1.5, 1.0 + (wr - 0.35)),
                            "priority": "high"
                        },
                        "evidence": {
                            "trades": stats["trades"],
                            "win_rate": round(wr * 100, 1),
                            "total_pnl": round(stats["pnl"], 2)
                        }
                    })
        
        for key, stats in analysis["by_symbol_direction"].items():
            if stats["trades"] >= 10 and stats["pnl"] < -20:
                symbol, direction = key.rsplit("_", 1)
                wr = stats["wins"] / stats["trades"]
                avg_ofi = stats["ofi_sum"] / stats["trades"]
                
                composite_rules.append({
                    "id": f"risky_{key}",
                    "conditions": {
                        "symbol": symbol,
                        "direction": direction
                    },
                    "action": {
                        "sizing_multiplier": max(0.3, wr),
                        "min_ofi_override": round(avg_ofi * 1.5, 2),
                        "priority": "caution"
                    },
                    "evidence": {
                        "trades": stats["trades"],
                        "win_rate": round(wr * 100, 1),
                        "total_pnl": round(stats["pnl"], 2)
                    }
                })
        
        rules["composite_rules"] = composite_rules
        
        rules["performance_baseline"] = {
            "win_rate": round(analysis["wins"] / max(1, analysis["total_trades"]) * 100, 2),
            "avg_pnl": round(analysis["total_pnl"] / max(1, analysis["total_trades"]), 4),
            "trades_analyzed": analysis["total_trades"]
        }
        
        print(f"\n   Generated {len(composite_rules)} composite rules")
        
        return rules
    
    def save_rules(self, rules):
        """Save learned rules for execution pipeline."""
        save_json(LEARNED_RULES_PATH, rules)
        print(f"\n   ✅ Rules saved to {LEARNED_RULES_PATH}")
        
        append_jsonl(LEARNING_HISTORY_PATH, {
            "ts": datetime.now().isoformat(),
            "version": rules["version"],
            "baseline": rules["performance_baseline"],
            "rules_count": len(rules["composite_rules"]),
            "symbols_covered": len(rules["per_symbol"])
        })
    
    def run_learning_cycle(self):
        """Run complete learning cycle."""
        print("\n" + "="*70)
        print("🔄 INTELLIGENCE LEARNING CYCLE")
        print(f"   Timestamp: {datetime.now().isoformat()}")
        print("="*70)
        
        analysis = self.analyze_all_data()
        
        if analysis["total_trades"] < 20:
            print(f"\n   ⚠️ Insufficient data ({analysis['total_trades']} trades)")
            print("   Need at least 20 trades for reliable learning")
            return None
        
        rules = self.generate_learned_rules(analysis)
        
        self.save_rules(rules)
        
        print("\n" + "="*70)
        print("✅ LEARNING CYCLE COMPLETE")
        print("="*70)
        print(f"   Version: {rules['version']}")
        print(f"   Rules: {len(rules['composite_rules'])} composite")
        print(f"   Symbols: {len(rules['per_symbol'])} configured")
        print(f"   Baseline WR: {rules['performance_baseline']['win_rate']}%")
        
        return rules


def get_learned_rules():
    """Get current learned rules (for execution pipeline)."""
    return load_json(LEARNED_RULES_PATH, IntelligenceLearner()._default_rules())


def _is_paper_mode():
    """Check if we're in paper trading mode."""
    try:
        config_path = "live_config.json"
        if os.path.exists(config_path):
            with open(config_path, 'r') as f:
                config = json.load(f)
                return config.get("mode", "paper") == "paper"
    except:
        pass
    return True  # Default to paper for safety


def apply_learned_rules(signal: dict) -> dict:
    """
    Apply learned rules to a trading signal.
    
    In PAPER MODE: Rules are logged but NOT enforced - we want maximum data gathering.
    In LIVE MODE: Rules are fully enforced to protect real capital.
    
    Returns:
        dict with keys:
        - allowed: bool (should trade proceed?)
        - sizing_multiplier: float (size adjustment)
        - reason: str (explanation)
        - rule_id: str (which rule applied)
        - paper_mode: bool (if True, rules are advisory only)
    """
    rules = get_learned_rules()
    is_paper = _is_paper_mode()
    
    symbol = signal.get("symbol", "")
    direction = signal.get("side", "").upper()
    ofi = abs(signal.get("ofi", 0))
    ofi_raw = signal.get("ofi", 0)
    ensemble = abs(signal.get("ensemble", 0))
    
    result = {
        "allowed": True,
        "sizing_multiplier": 1.0,
        "reason": "default",
        "rule_id": None,
        "warnings": [],
        "paper_mode": is_paper,
        "would_block": False,  # Track what WOULD happen in live mode
        "would_size_mult": 1.0
    }
    
    # Calculate what the rules WOULD do (for learning purposes)
    would_size_mult = 1.0
    would_block = False
    
    global_rules = rules.get("global", {})
    
    if ofi < global_rules.get("min_ofi", 0.5):
        result["warnings"].append(f"OFI {ofi:.2f} below global min {global_rules.get('min_ofi', 0.5)}")
    
    if ensemble < global_rules.get("min_ensemble", 0.05):
        result["warnings"].append(f"Ensemble {ensemble:.3f} below min {global_rules.get('min_ensemble', 0.05)}")
    
    is_aligned = (ofi_raw > 0 and direction == "LONG") or (ofi_raw < 0 and direction == "SHORT")
    
    if global_rules.get("require_ofi_alignment", True) and not is_aligned:
        would_size_mult *= 0.5
        result["warnings"].append("OFI not aligned with direction")
    
    symbol_rules = rules.get("per_symbol", {}).get(symbol, {}).get(direction, {})
    if symbol_rules:
        if ofi < symbol_rules.get("min_ofi", 0):
            would_size_mult *= 0.7
            result["warnings"].append(f"Below symbol-specific OFI threshold {symbol_rules.get('min_ofi', 0):.2f}")
        
        if symbol_rules.get("require_alignment", False) and not is_aligned:
            would_size_mult *= 0.5
            result["warnings"].append("Symbol requires alignment")
    
    for rule in rules.get("composite_rules", []):
        conditions = rule.get("conditions", {})
        
        if conditions.get("symbol") and conditions["symbol"] != symbol:
            continue
        if conditions.get("direction") and conditions["direction"] != direction:
            continue
        
        if conditions.get("min_ofi") and ofi < conditions["min_ofi"]:
            continue
        
        if conditions.get("require_alignment") and not is_aligned:
            continue
        
        action = rule.get("action", {})
        
        if action.get("sizing_multiplier"):
            would_size_mult *= action["sizing_multiplier"]
        
        if action.get("min_ofi_override") and ofi < action["min_ofi_override"]:
            would_size_mult *= 0.5
            result["warnings"].append(f"Rule {rule['id']}: OFI below override threshold")
        
        result["rule_id"] = rule.get("id")
        result["reason"] = f"composite_rule:{rule['id']}"
        break
    
    if would_size_mult < 0.3:
        would_block = True
    
    # Store what WOULD happen for learning
    result["would_block"] = would_block
    result["would_size_mult"] = would_size_mult
    
    # PAPER MODE: Don't restrict trading - gather data!
    if is_paper:
        result["allowed"] = True
        result["sizing_multiplier"] = 1.0  # Full size in paper mode
        if would_block or would_size_mult < 1.0:
            result["reason"] = f"paper_mode_override (would_block={would_block}, would_size={would_size_mult:.2f}x)"
    else:
        # LIVE MODE: Apply full restrictions
        result["sizing_multiplier"] = would_size_mult
        if would_block:
            result["allowed"] = False
            result["reason"] = "sizing_too_low"
    
    return result


def run_learning_cycle():
    """
    Module-level wrapper for running the learning cycle.
    Returns a dict with version, rules_count, baseline_wr for nightly maintenance reporting.
    
    Also runs counterfactual analysis to identify over-blocking.
    """
    learner = IntelligenceLearner()
    learner.run_learning_cycle()
    
    rules = get_learned_rules()
    result = {
        "version": rules.get("version", 0),
        "rules_count": len(rules.get("composite_rules", [])),
        "baseline_wr": rules.get("performance_baseline", {}).get("win_rate", 0),
        "trades_analyzed": rules.get("performance_baseline", {}).get("trades_analyzed", 0)
    }
    
    try:
        from src.signal_universe_tracker import analyze_missed_opportunities, generate_gate_feedback
        
        print("\n" + "="*70)
        print("📊 COUNTERFACTUAL ANALYSIS - What did we miss?")
        print("="*70)
        
        analysis = analyze_missed_opportunities(days=7)
        if "error" not in analysis:
            print(f"   Blocked signals: {analysis.get('blocked_count', 0)}")
            print(f"   Would have won: {analysis.get('blocked_would_win', 0)}")
            print(f"   Block accuracy: {analysis.get('block_accuracy', 0):.1f}%")
            print(f"   Missed profit: {analysis.get('missed_profit_pct', 0):.1f}%")
            print(f"   Avoided loss: {analysis.get('avoided_loss_pct', 0):.1f}%")
            
            result["counterfactual"] = {
                "blocked": analysis.get("blocked_count", 0),
                "would_win": analysis.get("blocked_would_win", 0),
                "block_accuracy": analysis.get("block_accuracy", 0),
                "missed_profit_pct": analysis.get("missed_profit_pct", 0),
            }
            
            feedback = generate_gate_feedback()
            if feedback.get("gates_to_loosen"):
                print("\n   ⚠️ Gates blocking too many winners:")
                for g in feedback["gates_to_loosen"][:3]:
                    print(f"      → {g['gate']}: {g['would_win_pct']:.0f}% would win")
                result["gates_to_loosen"] = [g["gate"] for g in feedback["gates_to_loosen"]]
        else:
            print(f"   No counterfactual data yet - will accumulate over time")
            
    except ImportError:
        print("   Counterfactual tracker not available")
    except Exception as e:
        print(f"   Counterfactual analysis error: {e}")
    
    return result


def run_multi_dimensional_analysis():
    """Run the comprehensive multi-dimensional analysis."""
    try:
        from src.daily_intelligence_learner import run_daily_analysis, analyze_learning_trends
        
        print("\n" + "="*70)
        print("🔬 MULTI-DIMENSIONAL INTELLIGENCE GRID ANALYSIS")
        print("="*70)
        
        results = run_daily_analysis(save_snapshot=True)
        
        profitable = results.get('profitable', [])
        high_potential = results.get('high_potential', [])
        
        print(f"\n📊 Analysis Complete:")
        print(f"   - Profitable patterns found: {len(profitable)}")
        print(f"   - High potential patterns: {len(high_potential)}")
        
        trends = analyze_learning_trends()
        if trends.get('status') != 'insufficient_history':
            print(f"   - Stable profitable patterns: {len(trends.get('stable_profitable_patterns', []))}")
            print(f"   - Profitability improving: {trends.get('profitable_improving', 'Unknown')}")
        
        return results
    except ImportError as e:
        print(f"   Multi-dimensional learner not available: {e}")
        return None
    except Exception as e:
        print(f"   Multi-dimensional analysis error: {e}")
        return None


def main():
    import sys
    
    if "--learn" in sys.argv:
        learner = IntelligenceLearner()
        learner.run_learning_cycle()
        run_multi_dimensional_analysis()
    elif "--multi-dim" in sys.argv:
        run_multi_dimensional_analysis()
    elif "--verify" in sys.argv:
        rules = get_learned_rules()
        print("\n" + "="*70)
        print("📋 CURRENT LEARNED RULES")
        print("="*70)
        print(f"\n   Version: {rules.get('version', 0)}")
        print(f"   Generated: {rules.get('generated_at', 'never')}")
        print(f"   Composite Rules: {len(rules.get('composite_rules', []))}")
        print(f"   Symbols Configured: {len(rules.get('per_symbol', {}))}")
        print(f"\n   Baseline Performance:")
        baseline = rules.get("performance_baseline", {})
        print(f"      Win Rate: {baseline.get('win_rate', 0)}%")
        print(f"      Avg P&L: ${baseline.get('avg_pnl', 0):.4f}")
        print(f"      Trades Analyzed: {baseline.get('trades_analyzed', 0)}")
    elif "--full" in sys.argv:
        learner = IntelligenceLearner()
        learner.run_learning_cycle()
        run_multi_dimensional_analysis()
        run_nightly_learning()
    else:
        learner = IntelligenceLearner()
        learner.run_learning_cycle()
        run_multi_dimensional_analysis()


if __name__ == "__main__":
    main()
