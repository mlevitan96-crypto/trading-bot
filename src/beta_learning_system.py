#!/usr/bin/env python3
"""
BETA BOT LEARNING SYSTEM
========================
Implements learning mechanisms for the Beta bot (signal inversion strategy),
mirroring Alpha's learning capabilities:
- Blocked signal counterfactual analysis
- Missed opportunity scanning
- Pattern discovery and promotion
- Continuous signal quality improvement

This enables Beta to learn independently from its own trading outcomes while
sharing market data with Alpha.
"""

import json
import os
import time
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

import sys
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.bot_registry import BotRegistry


class BetaLearningSystem:
    """
    Complete learning system for Beta bot - blocked signal review,
    missed trades analysis, and continuous signal improvement.
    """
    
    def __init__(self):
        self.registry = BotRegistry("beta")
        self.config = self._load_config()
        
        self.logs_dir = "logs/beta"
        self.feature_store = "feature_store/beta"
        
        os.makedirs(self.logs_dir, exist_ok=True)
        os.makedirs(self.feature_store, exist_ok=True)
        
        self.blocked_signals_log = f"{self.logs_dir}/blocked_signals.jsonl"
        self.counterfactual_log = f"{self.logs_dir}/counterfactual_analysis.jsonl"
        self.missed_opp_log = f"{self.logs_dir}/missed_opportunities.jsonl"
        self.learning_updates_log = f"{self.logs_dir}/learning_updates.jsonl"
        self.pattern_discoveries = f"{self.feature_store}/pattern_discoveries.json"
        self.daily_learning_rules = f"{self.feature_store}/daily_learning_rules.json"
        self.offensive_rules = f"{self.feature_store}/offensive_rules.json"
    
    def _load_config(self) -> Dict:
        """Load Beta bot configuration."""
        return self.registry.read_json("configs/beta_config.json") or {
            "min_ofi_threshold": 0.5,
            "invert_tiers": ["F"],
            "block_tiers": []
        }
    
    def _log(self, msg: str, level: str = "INFO"):
        ts = datetime.utcnow().isoformat() + "Z"
        print(f"[{ts}] [BETA-LEARN] [{level}] {msg}")
    
    def _read_jsonl(self, path: str, limit: int = 10000) -> List[Dict]:
        if not os.path.exists(path):
            return []
        rows = []
        try:
            with open(path, 'r') as f:
                for line in f:
                    line = line.strip()
                    if line:
                        try:
                            rows.append(json.loads(line))
                        except:
                            continue
        except:
            pass
        return rows[-limit:]
    
    def _append_jsonl(self, path: str, record: Dict):
        record['ts'] = time.time()
        record['ts_iso'] = datetime.utcnow().isoformat() + "Z"
        record['bot_id'] = 'beta'
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(path, 'a') as f:
            f.write(json.dumps(record, default=str) + '\n')
    
    def _read_json(self, path: str, default=None) -> Any:
        if not os.path.exists(path):
            return default
        try:
            with open(path, 'r') as f:
                return json.load(f)
        except:
            return default
    
    def _write_json(self, path: str, data: Dict):
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, 'w') as f:
            json.dump(data, f, indent=2, default=str)
        os.replace(tmp, path)
    
    def log_blocked_signal(self, signal: Dict, block_reason: str, block_gate: str = "beta_filter"):
        """Log a blocked signal for counterfactual analysis."""
        record = {
            "symbol": signal.get('symbol'),
            "direction": signal.get('direction'),
            "ofi": signal.get('ofi'),
            "tier": signal.get('tier'),
            "ensemble": signal.get('ensemble'),
            "block_reason": block_reason,
            "block_gate": block_gate,
            "signal_context": signal
        }
        self._append_jsonl(self.blocked_signals_log, record)
        self._log(f"Blocked {signal.get('symbol')}: {block_reason}")
    
    def run_counterfactual_analysis(self, lookback_hours: int = 24) -> Dict:
        """
        Analyze blocked signals to determine if they would have been profitable.
        This is the core of "what if we hadn't blocked this signal" learning.
        """
        self._log(f"Running counterfactual analysis (lookback: {lookback_hours}h)")
        
        cutoff_ts = time.time() - (lookback_hours * 3600)
        
        blocked = [r for r in self._read_jsonl(self.blocked_signals_log, 5000)
                   if r.get('ts', 0) >= cutoff_ts]
        
        enriched = self._read_jsonl(self.registry.ENRICHED_DECISIONS, 50000)
        
        outcomes_by_key = {}
        for e in enriched:
            key = f"{e.get('symbol')}_{e.get('direction', e.get('side', ''))}"
            if key not in outcomes_by_key:
                outcomes_by_key[key] = []
            outcomes_by_key[key].append(e)
        
        missed_profits = 0.0
        missed_wins = 0
        missed_losses = 0
        gate_attribution = defaultdict(lambda: {"missed_pnl": 0, "count": 0})
        symbol_missed = defaultdict(lambda: {"pnl": 0, "count": 0})
        
        counterfactual_records = []
        
        for blocked_sig in blocked:
            symbol = blocked_sig.get('symbol')
            direction = blocked_sig.get('direction')
            block_gate = blocked_sig.get('block_gate', 'unknown')
            
            key = f"{symbol}_{direction}"
            similar_outcomes = outcomes_by_key.get(key, [])
            
            if not similar_outcomes:
                continue
            
            avg_pnl = sum(o.get('pnl', 0) for o in similar_outcomes[-20:]) / max(len(similar_outcomes[-20:]), 1)
            win_rate = sum(1 for o in similar_outcomes[-20:] if o.get('pnl', 0) > 0) / max(len(similar_outcomes[-20:]), 1)
            
            if blocked_sig.get('tier') in self.config.get('invert_tiers', ['F']):
                estimated_pnl = -avg_pnl
            else:
                estimated_pnl = avg_pnl
            
            missed_profits += estimated_pnl
            if estimated_pnl > 0:
                missed_wins += 1
            else:
                missed_losses += 1
            
            gate_attribution[block_gate]["missed_pnl"] += estimated_pnl
            gate_attribution[block_gate]["count"] += 1
            symbol_missed[symbol]["pnl"] += estimated_pnl
            symbol_missed[symbol]["count"] += 1
            
            counterfactual_records.append({
                "symbol": symbol,
                "direction": direction,
                "block_gate": block_gate,
                "estimated_pnl": estimated_pnl,
                "original_tier": blocked_sig.get('tier'),
                "ofi": blocked_sig.get('ofi'),
                "profitable": estimated_pnl > 0
            })
        
        loose_proposals = []
        for gate, stats in gate_attribution.items():
            if stats["missed_pnl"] > 0 and stats["count"] >= 3:
                loose_proposals.append({
                    "gate": gate,
                    "missed_pnl": stats["missed_pnl"],
                    "count": stats["count"],
                    "recommendation": f"Consider loosening {gate} - missed ${stats['missed_pnl']:.2f}"
                })
        
        summary = {
            "analysis_type": "beta_counterfactual",
            "lookback_hours": lookback_hours,
            "blocked_signals_analyzed": len(blocked),
            "total_missed_pnl": missed_profits,
            "missed_wins": missed_wins,
            "missed_losses": missed_losses,
            "gate_attribution": dict(gate_attribution),
            "symbol_attribution": dict(symbol_missed),
            "loosen_proposals": loose_proposals,
            "counterfactual_details": counterfactual_records[:50]
        }
        
        self._append_jsonl(self.counterfactual_log, summary)
        self._log(f"Counterfactual: {len(blocked)} blocked, missed ${missed_profits:.2f} ({missed_wins}W/{missed_losses}L)")
        
        return summary
    
    def scan_missed_opportunities(self, lookback_hours: int = 24, min_move_pct: float = 1.5) -> Dict:
        """
        Scan for profitable moves we didn't trade.
        Identifies patterns where we should have entered but didn't.
        """
        self._log(f"Scanning missed opportunities (lookback: {lookback_hours}h, min_move: {min_move_pct}%)")
        
        cutoff_ts = time.time() - (lookback_hours * 3600)
        
        beta_trades = self.registry.get_trades(hours=lookback_hours)
        traded_windows = set()
        for t in beta_trades:
            ts = t.get('timestamp', '')
            symbol = t.get('symbol', '')
            if ts and symbol:
                try:
                    if isinstance(ts, (int, float)):
                        trade_ts = ts
                    else:
                        trade_ts = datetime.fromisoformat(ts.replace('Z', '+00:00')).timestamp()
                    hour_bucket = int(trade_ts / 3600)
                    traded_windows.add(f"{symbol}_{hour_bucket}")
                except:
                    pass
        
        all_signals = self._read_jsonl(self.registry.SIGNALS_UNIVERSE, 50000)
        recent_signals = [s for s in all_signals if s.get('ts', 0) >= cutoff_ts]
        
        enriched = self._read_jsonl(self.registry.ENRICHED_DECISIONS, 50000)
        recent_outcomes = [e for e in enriched if e.get('ts', 0) >= cutoff_ts]
        
        missed_opportunities = []
        pattern_counts = defaultdict(lambda: {"profitable": 0, "total": 0, "total_pnl": 0})
        
        for outcome in recent_outcomes:
            symbol = outcome.get('symbol')
            direction = outcome.get('direction', outcome.get('side', ''))
            pnl = outcome.get('pnl', 0)
            
            if pnl < min_move_pct * 10:
                continue
            
            ts = outcome.get('ts', 0)
            hour_bucket = int(ts / 3600)
            window_key = f"{symbol}_{hour_bucket}"
            
            if window_key in traded_windows:
                continue
            
            ofi = outcome.get('ofi', 0.5)
            regime = outcome.get('regime', 'unknown')
            ensemble = abs(outcome.get('ensemble', 0))
            
            ofi_bucket = "high" if ofi >= 0.7 else "mid" if ofi >= 0.5 else "low"
            ens_bucket = "strong" if ensemble >= 0.2 else "weak"
            pattern_key = f"{symbol}_{direction}_{ofi_bucket}_{regime}"
            
            pattern_counts[pattern_key]["total"] += 1
            pattern_counts[pattern_key]["total_pnl"] += pnl
            if pnl > 0:
                pattern_counts[pattern_key]["profitable"] += 1
            
            missed_opportunities.append({
                "symbol": symbol,
                "direction": direction,
                "missed_pnl": pnl,
                "ofi": ofi,
                "ensemble": ensemble,
                "regime": regime,
                "pattern": pattern_key,
                "timestamp": outcome.get('ts_iso', '')
            })
        
        high_value_patterns = []
        for pattern, stats in pattern_counts.items():
            if stats["total"] >= 2 and stats["total_pnl"] > 0:
                win_rate = stats["profitable"] / stats["total"]
                if win_rate >= 0.5:
                    high_value_patterns.append({
                        "pattern": pattern,
                        "occurrences": stats["total"],
                        "profitable": stats["profitable"],
                        "win_rate": win_rate,
                        "total_missed_pnl": stats["total_pnl"],
                        "recommendation": f"Add pattern to Beta offensive rules"
                    })
        
        high_value_patterns.sort(key=lambda x: x["total_missed_pnl"], reverse=True)
        
        summary = {
            "scan_type": "beta_missed_opportunities",
            "lookback_hours": lookback_hours,
            "opportunities_found": len(missed_opportunities),
            "total_missed_pnl": sum(m.get('missed_pnl', 0) for m in missed_opportunities),
            "patterns_discovered": len(high_value_patterns),
            "high_value_patterns": high_value_patterns[:20],
            "sample_opportunities": missed_opportunities[:30]
        }
        
        self._append_jsonl(self.missed_opp_log, summary)
        self._log(f"Missed opportunities: {len(missed_opportunities)} found, ${summary['total_missed_pnl']:.2f} missed")
        
        return summary
    
    def discover_patterns(self) -> Dict:
        """
        Analyze Beta's trading history to discover profitable patterns.
        Updates daily learning rules based on what's working.
        """
        self._log("Discovering patterns from Beta trading history")
        
        trades = self.registry.get_trades(hours=168)
        
        if len(trades) < 5:
            self._log("Not enough trades for pattern discovery")
            return {"status": "insufficient_data", "trades": len(trades)}
        
        pattern_stats = defaultdict(lambda: {
            "trades": 0, "wins": 0, "pnl": 0, "inverted": 0
        })
        
        for trade in trades:
            symbol = trade.get('symbol', 'UNKNOWN')
            direction = trade.get('direction', 'LONG')
            tier = trade.get('tier', 'C')
            inverted = trade.get('inverted', False)
            pnl = trade.get('pnl', 0)
            ofi = trade.get('ofi', 0.5)
            
            ofi_bucket = "high" if ofi >= 0.7 else "mid" if ofi >= 0.5 else "low"
            
            patterns = [
                f"symbol:{symbol}",
                f"direction:{direction}",
                f"tier:{tier}",
                f"ofi:{ofi_bucket}",
                f"{symbol}_{direction}",
                f"tier:{tier}_ofi:{ofi_bucket}",
                f"inverted:{inverted}"
            ]
            
            for p in patterns:
                pattern_stats[p]["trades"] += 1
                pattern_stats[p]["pnl"] += pnl
                if pnl > 0:
                    pattern_stats[p]["wins"] += 1
                if inverted:
                    pattern_stats[p]["inverted"] += 1
        
        profitable_patterns = []
        losing_patterns = []
        
        for pattern, stats in pattern_stats.items():
            if stats["trades"] < 3:
                continue
            
            win_rate = stats["wins"] / stats["trades"]
            avg_pnl = stats["pnl"] / stats["trades"]
            
            pattern_info = {
                "pattern": pattern,
                "trades": stats["trades"],
                "wins": stats["wins"],
                "wr": win_rate * 100,
                "pnl": stats["pnl"],
                "avg_pnl": avg_pnl,
                "ev": avg_pnl
            }
            
            if stats["pnl"] > 0 and win_rate >= 0.4:
                profitable_patterns.append(pattern_info)
            elif stats["pnl"] < 0 and win_rate < 0.35:
                losing_patterns.append(pattern_info)
        
        profitable_patterns.sort(key=lambda x: x["pnl"], reverse=True)
        losing_patterns.sort(key=lambda x: x["pnl"])
        
        symbol_biases = {}
        for pattern in profitable_patterns:
            if pattern["pattern"].count("_") == 1:
                parts = pattern["pattern"].split("_")
                if len(parts) == 2 and "USDT" in parts[0]:
                    symbol_biases[parts[0]] = {
                        "preferred_direction": parts[1],
                        "advantage": pattern["pnl"],
                        "win_rate": pattern["wr"]
                    }
        
        tier_performance = {}
        for pattern in pattern_stats:
            if pattern.startswith("tier:") and "_" not in pattern:
                tier = pattern.replace("tier:", "")
                stats = pattern_stats[pattern]
                if stats["trades"] > 0:
                    tier_performance[tier] = {
                        "trades": stats["trades"],
                        "win_rate": stats["wins"] / stats["trades"] * 100,
                        "pnl": stats["pnl"],
                        "inverted_count": stats["inverted"]
                    }
        
        inversion_effectiveness = {}
        inv_stats = pattern_stats.get("inverted:True", {"trades": 0, "wins": 0, "pnl": 0})
        non_inv_stats = pattern_stats.get("inverted:False", {"trades": 0, "wins": 0, "pnl": 0})
        
        if inv_stats["trades"] > 0:
            inversion_effectiveness["inverted"] = {
                "trades": inv_stats["trades"],
                "win_rate": inv_stats["wins"] / inv_stats["trades"] * 100,
                "pnl": inv_stats["pnl"],
                "avg_pnl": inv_stats["pnl"] / inv_stats["trades"]
            }
        if non_inv_stats["trades"] > 0:
            inversion_effectiveness["normal"] = {
                "trades": non_inv_stats["trades"],
                "win_rate": non_inv_stats["wins"] / non_inv_stats["trades"] * 100,
                "pnl": non_inv_stats["pnl"],
                "avg_pnl": non_inv_stats["pnl"] / non_inv_stats["trades"]
            }
        
        discoveries = {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "total_trades_analyzed": len(trades),
            "profitable_patterns": profitable_patterns[:20],
            "losing_patterns": losing_patterns[:20],
            "symbol_biases": symbol_biases,
            "tier_performance": tier_performance,
            "inversion_effectiveness": inversion_effectiveness,
            "recommendations": self._generate_recommendations(profitable_patterns, losing_patterns, inversion_effectiveness)
        }
        
        self._write_json(self.pattern_discoveries, discoveries)
        
        rules = {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "bot_id": "beta",
            "symbol_biases": symbol_biases,
            "tier_adjustments": tier_performance,
            "profitable_patterns": [p["pattern"] for p in profitable_patterns[:10]],
            "blocked_patterns": [p["pattern"] for p in losing_patterns[:10]],
            "inversion_analysis": inversion_effectiveness
        }
        self._write_json(self.daily_learning_rules, rules)
        
        self._log(f"Patterns: {len(profitable_patterns)} profitable, {len(losing_patterns)} losing")
        
        return discoveries
    
    def _generate_recommendations(self, profitable: List[Dict], losing: List[Dict], 
                                   inversion: Dict) -> List[Dict]:
        """Generate actionable recommendations from pattern analysis."""
        recommendations = []
        
        for p in profitable[:5]:
            recommendations.append({
                "type": "promote_pattern",
                "pattern": p["pattern"],
                "reason": f"Win rate {p['wr']:.1f}%, total P&L ${p['pnl']:.2f}",
                "action": "Lower entry threshold for this pattern"
            })
        
        for p in losing[:3]:
            recommendations.append({
                "type": "block_pattern",
                "pattern": p["pattern"],
                "reason": f"Win rate {p['wr']:.1f}%, total P&L ${p['pnl']:.2f}",
                "action": "Block or reduce sizing for this pattern"
            })
        
        if inversion.get("inverted", {}).get("pnl", 0) > inversion.get("normal", {}).get("pnl", 0):
            inv_wr = inversion.get("inverted", {}).get("win_rate", 0)
            recommendations.append({
                "type": "inversion_insight",
                "pattern": "F-tier inversion",
                "reason": f"Inverted signals performing better ({inv_wr:.1f}% WR)",
                "action": "Consider expanding inversion to D-tier"
            })
        elif inversion.get("inverted", {}).get("pnl", 0) < -10:
            recommendations.append({
                "type": "inversion_concern",
                "pattern": "F-tier inversion",
                "reason": f"Inverted signals underperforming",
                "action": "Review inversion criteria, may need tighter OFI filter"
            })
        
        return recommendations
    
    def apply_offensive_rules(self) -> Dict:
        """
        Apply learned patterns to create offensive trading rules.
        These lower thresholds for high-probability setups.
        """
        discoveries = self._read_json(self.pattern_discoveries, default={})
        profitable = discoveries.get("profitable_patterns", [])
        
        offensive_rules = {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "bot_id": "beta",
            "lower_ofi_symbols": [],
            "aggressive_tiers": [],
            "pattern_overrides": {}
        }
        
        for p in profitable[:10]:
            pattern = p["pattern"]
            if p["wr"] >= 55 and p["trades"] >= 5:
                if "symbol:" in pattern:
                    symbol = pattern.replace("symbol:", "")
                    offensive_rules["lower_ofi_symbols"].append({
                        "symbol": symbol,
                        "ofi_override": 0.45,
                        "reason": f"High WR pattern: {p['wr']:.1f}%"
                    })
                elif "tier:" in pattern and "_" not in pattern:
                    tier = pattern.replace("tier:", "")
                    offensive_rules["aggressive_tiers"].append({
                        "tier": tier,
                        "size_multiplier": 1.3,
                        "reason": f"Strong tier performance: {p['wr']:.1f}% WR"
                    })
        
        symbol_biases = discoveries.get("symbol_biases", {})
        for symbol, bias in symbol_biases.items():
            if bias.get("advantage", 0) > 20:
                offensive_rules["pattern_overrides"][f"{symbol}_{bias['preferred_direction']}"] = {
                    "priority": "high",
                    "size_boost": 1.2,
                    "reason": f"Strong directional edge: ${bias['advantage']:.2f}"
                }
        
        self._write_json(self.offensive_rules, offensive_rules)
        self._log(f"Applied {len(offensive_rules['lower_ofi_symbols'])} offensive rules")
        
        return offensive_rules
    
    def run_full_learning_cycle(self) -> Dict:
        """
        Run a complete learning cycle for Beta bot.
        This should be called nightly or after significant trading activity.
        """
        self._log("Starting full Beta learning cycle")
        
        results = {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "bot_id": "beta",
            "cycle_type": "full_learning"
        }
        
        try:
            cf_result = self.run_counterfactual_analysis(lookback_hours=24)
            results["counterfactual"] = {
                "blocked_analyzed": cf_result.get("blocked_signals_analyzed", 0),
                "missed_pnl": cf_result.get("total_missed_pnl", 0),
                "loosen_proposals": len(cf_result.get("loosen_proposals", []))
            }
        except Exception as e:
            results["counterfactual"] = {"error": str(e)}
            self._log(f"Counterfactual error: {e}", "ERROR")
        
        try:
            missed_result = self.scan_missed_opportunities(lookback_hours=24)
            results["missed_opportunities"] = {
                "found": missed_result.get("opportunities_found", 0),
                "missed_pnl": missed_result.get("total_missed_pnl", 0),
                "patterns": len(missed_result.get("high_value_patterns", []))
            }
        except Exception as e:
            results["missed_opportunities"] = {"error": str(e)}
            self._log(f"Missed opportunity error: {e}", "ERROR")
        
        try:
            pattern_result = self.discover_patterns()
            results["pattern_discovery"] = {
                "trades_analyzed": pattern_result.get("total_trades_analyzed", 0),
                "profitable": len(pattern_result.get("profitable_patterns", [])),
                "losing": len(pattern_result.get("losing_patterns", [])),
                "recommendations": len(pattern_result.get("recommendations", []))
            }
        except Exception as e:
            results["pattern_discovery"] = {"error": str(e)}
            self._log(f"Pattern discovery error: {e}", "ERROR")
        
        try:
            offensive_result = self.apply_offensive_rules()
            results["offensive_rules"] = {
                "lower_ofi_count": len(offensive_result.get("lower_ofi_symbols", [])),
                "aggressive_tiers": len(offensive_result.get("aggressive_tiers", [])),
                "pattern_overrides": len(offensive_result.get("pattern_overrides", {}))
            }
        except Exception as e:
            results["offensive_rules"] = {"error": str(e)}
            self._log(f"Offensive rules error: {e}", "ERROR")
        
        self._append_jsonl(self.learning_updates_log, results)
        self._log("Beta learning cycle complete")
        
        return results
    
    def get_learning_summary(self) -> Dict:
        """Get a summary of Beta's learned intelligence for reporting."""
        patterns = self._read_json(self.pattern_discoveries, default={})
        rules = self._read_json(self.daily_learning_rules, default={})
        offensive = self._read_json(self.offensive_rules, default={})
        
        recent_updates = self._read_jsonl(self.learning_updates_log, 5)
        
        return {
            "last_update": patterns.get("timestamp"),
            "trades_analyzed": patterns.get("total_trades_analyzed", 0),
            "profitable_patterns": patterns.get("profitable_patterns", [])[:5],
            "losing_patterns": patterns.get("losing_patterns", [])[:5],
            "symbol_biases": rules.get("symbol_biases", {}),
            "tier_performance": patterns.get("tier_performance", {}),
            "inversion_analysis": patterns.get("inversion_effectiveness", {}),
            "recommendations": patterns.get("recommendations", []),
            "offensive_rules_active": len(offensive.get("lower_ofi_symbols", [])),
            "recent_cycles": len(recent_updates)
        }


def run_beta_learning():
    """CLI entry point for Beta learning system."""
    learner = BetaLearningSystem()
    result = learner.run_full_learning_cycle()
    print(json.dumps(result, indent=2, default=str))
    return result


if __name__ == "__main__":
    run_beta_learning()
