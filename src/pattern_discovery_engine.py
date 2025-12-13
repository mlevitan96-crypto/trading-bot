#!/usr/bin/env python3
"""
PATTERN DISCOVERY ENGINE - FIND WHAT WE SHOULD HAVE SEEN
=========================================================
This module discovers what intelligence patterns preceded profitable moves
that we missed. It teaches the system WHAT TO LOOK FOR in the future.

Key questions answered:
1. What did OFI look like before big moves?
2. What was the regime/volatility state?
3. What market intelligence signals were present?
4. What thresholds would have caught these moves?

Usage:
    python src/pattern_discovery_engine.py
"""

import json
import os
import time
from datetime import datetime, timedelta
from collections import defaultdict
from typing import Dict, List, Optional, Any, Tuple
import statistics

from src.data_registry import DataRegistry as DR

ASSET_UNIVERSE = [
    "BTCUSDT", "ETHUSDT", "SOLUSDT", "AVAXUSDT", "DOTUSDT",
    "TRXUSDT", "XRPUSDT", "ADAUSDT", "DOGEUSDT", "BNBUSDT", "MATICUSDT"
]


def load_jsonl(path: str) -> List[Dict]:
    """Load JSONL file."""
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


def load_json(path: str) -> Optional[Dict]:
    """Load JSON file."""
    if not os.path.exists(path):
        return None
    try:
        with open(path, 'r') as f:
            return json.load(f)
    except:
        return None


def save_json(path: str, data: Dict):
    """Save JSON atomically."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + '.tmp'
    with open(tmp, 'w') as f:
        json.dump(data, f, indent=2, default=str)
    os.rename(tmp, path)


class PatternDiscoveryEngine:
    """
    Discovers patterns that preceded profitable moves we missed.
    This is the intelligence layer that learns WHAT to look for.
    """
    
    def __init__(self):
        self.missed_opps = load_jsonl(DR.MISSED_OPPORTUNITIES)
        self.signals = load_jsonl(DR.SIGNALS_UNIVERSE)
        self.enriched = load_jsonl(DR.ENRICHED_DECISIONS)
        self.offensive_rules = load_json(DR.OFFENSIVE_RULES)
        
        self.current_weights = self._load_current_weights()
        self.current_thresholds = self._load_current_thresholds()
        
        print(f"🔬 Pattern Discovery Engine initialized")
        print(f"   Missed opportunities: {len(self.missed_opps)}")
        print(f"   Signals to analyze: {len(self.signals)}")
        print(f"   Enriched decisions: {len(self.enriched)}")
    
    def _load_current_weights(self) -> Dict:
        """Load current composite weights."""
        try:
            with open('configs/composite_weights.json', 'r') as f:
                return json.load(f)
        except:
            return {}
    
    def _load_current_thresholds(self) -> Dict:
        """Load current thresholds from learned rules."""
        rules = load_json(DR.LEARNED_RULES)
        if rules:
            return rules.get('global', {})
        return {}
    
    def _get_exchange_gateway(self):
        """Lazy load exchange gateway."""
        try:
            from src.exchange_gateway import ExchangeGateway
            return ExchangeGateway()
        except Exception as e:
            print(f"⚠️ Could not load ExchangeGateway: {e}")
            return None
    
    def _get_signal_generator(self):
        """Lazy load signal generator for intelligence computation."""
        try:
            from src.signal_generator import SignalGenerator
            return SignalGenerator()
        except Exception as e:
            print(f"⚠️ Could not load SignalGenerator: {e}")
            return None
    
    def discover_patterns(self) -> Dict:
        """
        Main discovery method: analyze missed opportunities and find patterns.
        Returns patterns that would have caught profitable moves.
        """
        print("\n" + "=" * 70)
        print("🔎 PATTERN DISCOVERY - WHAT SHOULD WE HAVE SEEN?")
        print("=" * 70)
        
        gateway = self._get_exchange_gateway()
        
        patterns = {
            "timestamp": datetime.utcnow().isoformat(),
            "missed_opportunities_analyzed": len(self.missed_opps),
            "by_symbol_direction": {},
            "optimal_thresholds": {},
            "intelligence_patterns": [],
            "recommended_changes": [],
        }
        
        by_combo = defaultdict(list)
        for opp in self.missed_opps:
            combo = f"{opp.get('symbol')}_{opp.get('direction')}"
            by_combo[combo].append(opp)
        
        print(f"\n📊 Analyzing {len(by_combo)} symbol/direction combinations...")
        
        for combo, opps in sorted(by_combo.items(), key=lambda x: -len(x[1])):
            if len(opps) < 2:
                continue
            
            parts = combo.split('_')
            symbol = parts[0]
            direction = parts[1] if len(parts) > 1 else 'UNKNOWN'
            
            pattern_info = self._analyze_combo_pattern(symbol, direction, opps, gateway)
            patterns["by_symbol_direction"][combo] = pattern_info
            
            if pattern_info.get("recommended_threshold"):
                patterns["recommended_changes"].append({
                    "symbol": symbol,
                    "direction": direction,
                    "current_threshold": pattern_info.get("current_threshold"),
                    "recommended_threshold": pattern_info["recommended_threshold"],
                    "potential_gain": pattern_info.get("total_potential", 0),
                    "opportunities_to_capture": len(opps),
                })
        
        optimal = self._compute_optimal_thresholds(patterns)
        patterns["optimal_thresholds"] = optimal
        
        intel_patterns = self._discover_intelligence_patterns()
        patterns["intelligence_patterns"] = intel_patterns
        
        save_json(DR.PATTERN_DISCOVERIES, patterns)
        print(f"\n💾 Saved pattern discoveries to {DR.PATTERN_DISCOVERIES}")
        
        self._print_discovery_summary(patterns)
        
        return patterns
    
    def _analyze_combo_pattern(self, symbol: str, direction: str, 
                               opps: List[Dict], gateway) -> Dict:
        """Analyze patterns for a specific symbol/direction combo."""
        moves = [o.get('move_pct', 0) for o in opps]
        potentials = [o.get('potential_profit', 0) for o in opps]
        volumes = [o.get('volume', 0) for o in opps]
        
        current_ofi = self.current_thresholds.get('min_ofi', 0.5)
        current_ensemble = self.current_thresholds.get('min_ensemble', 0.05)
        
        signal_context = self._get_signal_context_for_combo(symbol, direction)
        
        pattern = {
            "count": len(opps),
            "avg_move": round(statistics.mean(moves), 2) if moves else 0,
            "max_move": round(max(moves), 2) if moves else 0,
            "total_potential": round(sum(potentials), 2),
            "avg_volume": round(statistics.mean(volumes), 0) if volumes else 0,
            "current_threshold": current_ofi,
            "signal_context": signal_context,
        }
        
        if len(opps) >= 3 and sum(potentials) >= 50:
            if direction == "SHORT":
                pattern["recommended_threshold"] = max(0.1, current_ofi - 0.15)
            else:
                pattern["recommended_threshold"] = max(0.1, current_ofi - 0.10)
            
            pattern["threshold_change"] = pattern["recommended_threshold"] - current_ofi
        
        return pattern
    
    def _get_signal_context_for_combo(self, symbol: str, direction: str) -> Dict:
        """Get context about what signals we DID generate for this combo."""
        matching_signals = [
            s for s in self.signals 
            if s.get('symbol') == symbol and 
               s.get('direction', s.get('side', '')).upper() == direction.upper()
        ]
        
        executed = [s for s in matching_signals if s.get('disposition', '').upper() == 'EXECUTED']
        blocked = [s for s in matching_signals if s.get('disposition', '').upper() == 'BLOCKED']
        
        ofi_values = []
        ensemble_values = []
        for sig in matching_signals:
            ofi = sig.get('ofi', sig.get('ofi_score'))
            if ofi is not None:
                ofi_values.append(float(ofi))
            
            ens = sig.get('ensemble_score', sig.get('ensemble'))
            if ens is not None:
                ensemble_values.append(float(ens))
        
        return {
            "total_signals": len(matching_signals),
            "executed": len(executed),
            "blocked": len(blocked),
            "avg_ofi": round(statistics.mean(ofi_values), 3) if ofi_values else None,
            "avg_ensemble": round(statistics.mean(ensemble_values), 3) if ensemble_values else None,
            "ofi_range": [round(min(ofi_values), 3), round(max(ofi_values), 3)] if ofi_values else None,
        }
    
    def _compute_optimal_thresholds(self, patterns: Dict) -> Dict:
        """Compute optimal global thresholds based on discoveries."""
        all_recommendations = patterns.get("recommended_changes", [])
        
        if not all_recommendations:
            return {
                "min_ofi": self.current_thresholds.get('min_ofi', 0.5),
                "status": "no_changes_recommended",
            }
        
        recommended_thresholds = [r['recommended_threshold'] for r in all_recommendations if r.get('recommended_threshold')]
        total_potential = sum(r['potential_gain'] for r in all_recommendations)
        
        if not recommended_thresholds:
            return {
                "min_ofi": self.current_thresholds.get('min_ofi', 0.5),
                "status": "no_threshold_changes",
            }
        
        avg_recommended = statistics.mean(recommended_thresholds)
        
        optimal = {
            "min_ofi": round(avg_recommended, 2),
            "original_ofi": self.current_thresholds.get('min_ofi', 0.5),
            "change": round(avg_recommended - self.current_thresholds.get('min_ofi', 0.5), 2),
            "potential_to_capture": round(total_potential, 2),
            "opportunities_to_capture": sum(r['opportunities_to_capture'] for r in all_recommendations),
            "per_symbol": {},
        }
        
        for rec in all_recommendations:
            symbol = rec.get('symbol')
            if symbol:
                optimal["per_symbol"][symbol] = {
                    "threshold": rec['recommended_threshold'],
                    "potential": rec['potential_gain'],
                }
        
        return optimal
    
    def _discover_intelligence_patterns(self) -> List[Dict]:
        """
        Discover patterns in our intelligence signals that correlate with wins/losses.
        This helps understand WHAT intelligence values lead to profits.
        """
        patterns = []
        
        winners = [e for e in self.enriched if e.get('pnl', 0) > 0]
        losers = [e for e in self.enriched if e.get('pnl', 0) < 0]
        
        if not winners and not losers:
            print("  ⚠️ No enriched decisions to analyze for intelligence patterns")
            return patterns
        
        metrics = ['ofi', 'ofi_score', 'ensemble_score', 'confidence', 'mtf_alignment']
        
        for metric in metrics:
            winner_vals = [e.get(metric) for e in winners if e.get(metric) is not None]
            loser_vals = [e.get(metric) for e in losers if e.get(metric) is not None]
            
            if winner_vals and loser_vals:
                try:
                    winner_vals = [float(v) for v in winner_vals if isinstance(v, (int, float))]
                    loser_vals = [float(v) for v in loser_vals if isinstance(v, (int, float))]
                    
                    if winner_vals and loser_vals:
                        winner_avg = statistics.mean(winner_vals)
                        loser_avg = statistics.mean(loser_vals)
                        
                        patterns.append({
                            "metric": metric,
                            "winner_avg": round(winner_avg, 3),
                            "loser_avg": round(loser_avg, 3),
                            "difference": round(winner_avg - loser_avg, 3),
                            "insight": f"Winners have {'higher' if winner_avg > loser_avg else 'lower'} {metric}",
                            "threshold_suggestion": round((winner_avg + loser_avg) / 2, 3) if winner_avg > loser_avg else None,
                        })
                except:
                    continue
        
        return patterns
    
    def _print_discovery_summary(self, patterns: Dict):
        """Print summary of discoveries."""
        print("\n" + "=" * 70)
        print("📊 PATTERN DISCOVERY SUMMARY")
        print("=" * 70)
        
        print(f"\nMissed opportunities analyzed: {patterns.get('missed_opportunities_analyzed', 0)}")
        
        optimal = patterns.get('optimal_thresholds', {})
        if optimal.get('change'):
            print(f"\n🎯 OPTIMAL THRESHOLD CHANGES:")
            print(f"   Current OFI threshold: {optimal.get('original_ofi', 0.5)}")
            print(f"   Recommended OFI threshold: {optimal.get('min_ofi', 0.5)}")
            print(f"   Change: {optimal.get('change', 0):+.2f}")
            print(f"   Potential to capture: ${optimal.get('potential_to_capture', 0):.2f}")
            print(f"   Opportunities: {optimal.get('opportunities_to_capture', 0)}")
        
        print("\n📈 BY SYMBOL (recommended changes):")
        for rec in patterns.get('recommended_changes', [])[:10]:
            print(f"   {rec['symbol']} {rec['direction']}: {rec['current_threshold']:.2f} → {rec['recommended_threshold']:.2f}")
            print(f"      Potential gain: ${rec['potential_gain']:.0f}, Opportunities: {rec['opportunities_to_capture']}")
        
        print("\n🔬 INTELLIGENCE PATTERNS:")
        for pat in patterns.get('intelligence_patterns', [])[:5]:
            print(f"   {pat['metric']}: Winner avg={pat['winner_avg']:.3f}, Loser avg={pat['loser_avg']:.3f}")
            print(f"      {pat['insight']}")
            if pat.get('threshold_suggestion'):
                print(f"      Suggested threshold: {pat['threshold_suggestion']:.3f}")
    
    def generate_actionable_rules(self) -> Dict:
        """
        Generate actionable rules that can be applied to execution.
        These rules lower thresholds to capture more opportunities.
        """
        patterns = load_json(DR.PATTERN_DISCOVERIES)
        if not patterns:
            print("⚠️ No pattern discoveries found. Run discover_patterns() first.")
            return {}
        
        rules = {
            "version": 1,
            "generated_at": datetime.utcnow().isoformat(),
            "type": "offensive_adjustments",
            "global": {},
            "per_symbol": {},
            "per_direction": {},
            "per_symbol_direction": {},
        }
        
        optimal = patterns.get('optimal_thresholds', {})
        if optimal.get('min_ofi'):
            rules["global"]["min_ofi_adjustment"] = optimal.get('change', 0)
            rules["global"]["new_min_ofi"] = optimal.get('min_ofi')
            rules["global"]["potential_upside"] = optimal.get('potential_to_capture', 0)
        
        for rec in patterns.get('recommended_changes', []):
            symbol = rec.get('symbol')
            direction = rec.get('direction')
            combo = f"{symbol}_{direction}"
            
            if symbol not in rules["per_symbol"]:
                rules["per_symbol"][symbol] = {
                    "min_ofi": rec.get('recommended_threshold'),
                    "potential": rec.get('potential_gain', 0),
                }
            
            rules["per_symbol_direction"][combo] = {
                "min_ofi": rec.get('recommended_threshold'),
                "potential": rec.get('potential_gain', 0),
                "opportunities": rec.get('opportunities_to_capture', 0),
            }
        
        short_recs = [r for r in patterns.get('recommended_changes', []) if r.get('direction') == 'SHORT']
        long_recs = [r for r in patterns.get('recommended_changes', []) if r.get('direction') == 'LONG']
        
        if short_recs:
            avg_short = statistics.mean([r['recommended_threshold'] for r in short_recs])
            total_short_potential = sum(r['potential_gain'] for r in short_recs)
            rules["per_direction"]["SHORT"] = {
                "min_ofi": round(avg_short, 2),
                "potential": round(total_short_potential, 2),
            }
        
        if long_recs:
            avg_long = statistics.mean([r['recommended_threshold'] for r in long_recs])
            total_long_potential = sum(r['potential_gain'] for r in long_recs)
            rules["per_direction"]["LONG"] = {
                "min_ofi": round(avg_long, 2),
                "potential": round(total_long_potential, 2),
            }
        
        save_json("feature_store/offensive_adjustments.json", rules)
        print(f"💾 Saved actionable rules to feature_store/offensive_adjustments.json")
        
        return rules


def main():
    engine = PatternDiscoveryEngine()
    
    print("\n🔍 PHASE 1: Discovering patterns in missed opportunities...")
    patterns = engine.discover_patterns()
    
    print("\n⚙️ PHASE 2: Generating actionable rules...")
    rules = engine.generate_actionable_rules()
    
    print("\n" + "=" * 70)
    print("✅ PATTERN DISCOVERY COMPLETE")
    print("=" * 70)
    print(f"\nPatterns discovered: {len(patterns.get('by_symbol_direction', {}))}")
    print(f"Recommended threshold changes: {len(patterns.get('recommended_changes', []))}")
    print(f"Rules generated: {len(rules.get('per_symbol_direction', {}))}")
    
    return patterns, rules


if __name__ == "__main__":
    main()
