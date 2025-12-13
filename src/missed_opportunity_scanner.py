#!/usr/bin/env python3
"""
MISSED OPPORTUNITY SCANNER - OFFENSIVE LEARNING
================================================
This module proactively scans historical price data to find profitable moves
we NEVER signaled. It answers: "What money did we leave on the table?"

Instead of just learning from executed/blocked trades, this hunts for:
1. Significant price moves (>1% in short timeframes)
2. Intelligence patterns that preceded those moves
3. Rules we should add to capture these opportunities in the future

Usage:
    python src/missed_opportunity_scanner.py --hours 24
    python src/missed_opportunity_scanner.py --aggressive
"""

import json
import os
import sys
import time
from datetime import datetime, timedelta
from collections import defaultdict
from typing import Dict, List, Optional, Tuple, Any
import statistics

from src.data_registry import DataRegistry as DR

# Dynamic symbol loading from canonical config
ASSET_UNIVERSE = DR.get_enabled_symbols()

MISSED_OPPS_PATH = DR.MISSED_OPPORTUNITIES
OFFENSIVE_RULES_PATH = "feature_store/offensive_rules.json"


def load_jsonl(path: str, max_age_hours: int = None) -> List[Dict]:
    """Load JSONL records, optionally filtering by age."""
    if not os.path.exists(path):
        return []
    
    records = []
    cutoff = None
    if max_age_hours:
        cutoff = (datetime.utcnow() - timedelta(hours=max_age_hours)).timestamp()
    
    try:
        with open(path, 'r') as f:
            for line in f:
                try:
                    rec = json.loads(line.strip())
                    if cutoff:
                        ts = rec.get('ts') or rec.get('timestamp', 0)
                        if isinstance(ts, str):
                            try:
                                ts = datetime.fromisoformat(ts.replace('Z', '+00:00')).timestamp()
                            except:
                                ts = 0
                        if ts >= cutoff:
                            records.append(rec)
                    else:
                        records.append(rec)
                except:
                    continue
    except:
        pass
    return records


def save_json(path: str, data: Dict):
    """Save JSON file atomically."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + '.tmp'
    with open(tmp, 'w') as f:
        json.dump(data, f, indent=2, default=str)
    os.rename(tmp, path)


def append_jsonl(path: str, record: Dict):
    """Append to JSONL file."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'a') as f:
        f.write(json.dumps(record, default=str) + '\n')


class MissedOpportunityScanner:
    """
    Scans historical data to find profitable moves we never signaled.
    This is OFFENSIVE learning - finding money we left on the table.
    """
    
    def __init__(self, lookback_hours: int = 24, min_move_pct: float = 1.0):
        self.lookback_hours = lookback_hours
        self.min_move_pct = min_move_pct
        
        self.signals = load_jsonl(DR.SIGNALS_UNIVERSE, max_age_hours=lookback_hours * 2)
        self.trades = load_jsonl(DR.TRADES_CANONICAL, max_age_hours=lookback_hours * 2)
        
        self.signal_timestamps = self._build_signal_index()
        self.trade_timestamps = self._build_trade_index()
        
        self.opportunities = []
        self.patterns_found = defaultdict(list)
        
        print(f"📡 Scanner initialized: {len(self.signals)} signals, {len(self.trades)} trades in last {lookback_hours}h")
    
    def _build_signal_index(self) -> Dict[str, List[Dict]]:
        """Build index of signals by symbol+direction."""
        idx = defaultdict(list)
        for sig in self.signals:
            key = f"{sig.get('symbol')}_{sig.get('direction', sig.get('side', ''))}"
            idx[key].append(sig)
        return idx
    
    def _build_trade_index(self) -> Dict[str, List[Dict]]:
        """Build index of trades by symbol+direction."""
        idx = defaultdict(list)
        for trade in self.trades:
            key = f"{trade.get('symbol')}_{trade.get('direction', trade.get('side', ''))}"
            idx[key].append(trade)
        return idx
    
    def _get_exchange_gateway(self):
        """Lazy load exchange gateway."""
        try:
            from src.exchange_gateway import ExchangeGateway
            return ExchangeGateway()
        except Exception as e:
            print(f"⚠️ Could not load ExchangeGateway: {e}")
            return None
    
    def scan_price_moves(self) -> List[Dict]:
        """
        Scan historical price data for significant moves.
        Returns list of opportunities (moves we could have traded).
        """
        gateway = self._get_exchange_gateway()
        if not gateway:
            print("❌ Cannot scan without exchange gateway")
            return []
        
        all_opportunities = []
        
        for symbol in ASSET_UNIVERSE:
            try:
                opps = self._scan_symbol(symbol, gateway)
                all_opportunities.extend(opps)
                print(f"  {symbol}: Found {len(opps)} opportunities")
            except Exception as e:
                print(f"  ⚠️ {symbol}: Error scanning - {e}")
        
        return all_opportunities
    
    def _scan_symbol(self, symbol: str, gateway) -> List[Dict]:
        """Scan a single symbol for missed opportunities."""
        opportunities = []
        
        try:
            df = gateway.fetch_ohlcv(symbol, timeframe="15m", limit=96, venue="futures")
            if df is None or len(df) < 10:
                return []
        except Exception as e:
            print(f"    ⚠️ Could not fetch data for {symbol}: {e}")
            return []
        
        for i in range(4, len(df)):
            candle_time = df.iloc[i]['timestamp']
            if isinstance(candle_time, str):
                candle_time = datetime.fromisoformat(candle_time.replace('Z', '+00:00'))
            
            window = df.iloc[i-4:i+1]
            
            low_price = window['low'].min()
            high_price = window['high'].max()
            
            long_move = (high_price - window.iloc[0]['open']) / window.iloc[0]['open'] * 100
            short_move = (window.iloc[0]['open'] - low_price) / window.iloc[0]['open'] * 100
            
            opp = None
            
            if long_move >= self.min_move_pct:
                we_signaled = self._did_we_signal(symbol, "LONG", candle_time)
                we_traded = self._did_we_trade(symbol, "LONG", candle_time)
                
                if not we_signaled and not we_traded:
                    opp = {
                        "symbol": symbol,
                        "direction": "LONG",
                        "move_pct": round(long_move, 2),
                        "entry_price": window.iloc[0]['open'],
                        "best_price": high_price,
                        "timestamp": candle_time.isoformat() if hasattr(candle_time, 'isoformat') else str(candle_time),
                        "ts": time.time(),
                        "opportunity_type": "MISSED_LONG",
                        "potential_profit": round(long_move * 20, 2),
                        "volume": window['volume'].sum(),
                    }
            
            if short_move >= self.min_move_pct:
                we_signaled = self._did_we_signal(symbol, "SHORT", candle_time)
                we_traded = self._did_we_trade(symbol, "SHORT", candle_time)
                
                if not we_signaled and not we_traded:
                    if opp is None or short_move > long_move:
                        opp = {
                            "symbol": symbol,
                            "direction": "SHORT",
                            "move_pct": round(short_move, 2),
                            "entry_price": window.iloc[0]['open'],
                            "best_price": low_price,
                            "timestamp": candle_time.isoformat() if hasattr(candle_time, 'isoformat') else str(candle_time),
                            "ts": time.time(),
                            "opportunity_type": "MISSED_SHORT",
                            "potential_profit": round(short_move * 20, 2),
                            "volume": window['volume'].sum(),
                        }
            
            if opp:
                opportunities.append(opp)
        
        return opportunities
    
    def _did_we_signal(self, symbol: str, direction: str, opp_time) -> bool:
        """Check if we generated a signal near this opportunity."""
        key = f"{symbol}_{direction}"
        signals = self.signal_timestamps.get(key, [])
        
        if isinstance(opp_time, str):
            try:
                opp_time = datetime.fromisoformat(opp_time.replace('Z', '+00:00'))
            except:
                return False
        
        for sig in signals:
            sig_ts = sig.get('ts') or sig.get('timestamp', 0)
            if isinstance(sig_ts, str):
                try:
                    sig_ts = datetime.fromisoformat(sig_ts.replace('Z', '+00:00'))
                except:
                    continue
            elif isinstance(sig_ts, (int, float)):
                sig_ts = datetime.utcfromtimestamp(sig_ts)
            
            time_diff = abs((opp_time - sig_ts).total_seconds())
            if time_diff < 3600:
                return True
        
        return False
    
    def _did_we_trade(self, symbol: str, direction: str, opp_time) -> bool:
        """Check if we executed a trade near this opportunity."""
        key = f"{symbol}_{direction}"
        trades = self.trade_timestamps.get(key, [])
        
        if isinstance(opp_time, str):
            try:
                opp_time = datetime.fromisoformat(opp_time.replace('Z', '+00:00'))
            except:
                return False
        
        for trade in trades:
            trade_ts = trade.get('ts') or trade.get('timestamp', 0)
            if isinstance(trade_ts, str):
                try:
                    trade_ts = datetime.fromisoformat(trade_ts.replace('Z', '+00:00'))
                except:
                    continue
            elif isinstance(trade_ts, (int, float)):
                trade_ts = datetime.utcfromtimestamp(trade_ts)
            
            time_diff = abs((opp_time - trade_ts).total_seconds())
            if time_diff < 3600:
                return True
        
        return False
    
    def analyze_patterns(self, opportunities: List[Dict]) -> Dict:
        """
        Analyze patterns in missed opportunities to generate rules.
        This is where we learn WHAT we should have looked for.
        """
        print(f"\n🔬 Analyzing {len(opportunities)} missed opportunities...")
        
        by_symbol = defaultdict(list)
        by_direction = defaultdict(list)
        by_symbol_direction = defaultdict(list)
        
        total_potential = 0
        
        for opp in opportunities:
            symbol = opp.get('symbol', 'UNKNOWN')
            direction = opp.get('direction', 'UNKNOWN')
            move_pct = opp.get('move_pct', 0)
            potential = opp.get('potential_profit', 0)
            
            by_symbol[symbol].append(opp)
            by_direction[direction].append(opp)
            by_symbol_direction[f"{symbol}_{direction}"].append(opp)
            total_potential += potential
            
            append_jsonl(MISSED_OPPS_PATH, opp)
        
        analysis = {
            "timestamp": datetime.utcnow().isoformat(),
            "total_opportunities": len(opportunities),
            "total_potential_profit": round(total_potential, 2),
            "by_symbol": {},
            "by_direction": {},
            "by_symbol_direction": {},
            "top_opportunities": [],
            "recommended_rules": [],
        }
        
        for symbol, opps in by_symbol.items():
            moves = [o['move_pct'] for o in opps]
            potentials = [o['potential_profit'] for o in opps]
            analysis["by_symbol"][symbol] = {
                "count": len(opps),
                "avg_move": round(statistics.mean(moves), 2) if moves else 0,
                "max_move": round(max(moves), 2) if moves else 0,
                "total_potential": round(sum(potentials), 2),
            }
        
        for direction, opps in by_direction.items():
            moves = [o['move_pct'] for o in opps]
            potentials = [o['potential_profit'] for o in opps]
            analysis["by_direction"][direction] = {
                "count": len(opps),
                "avg_move": round(statistics.mean(moves), 2) if moves else 0,
                "total_potential": round(sum(potentials), 2),
            }
        
        sorted_combos = sorted(
            by_symbol_direction.items(),
            key=lambda x: sum(o['potential_profit'] for o in x[1]),
            reverse=True
        )
        
        for combo, opps in sorted_combos[:10]:
            parts = combo.split('_')
            symbol = parts[0] if parts else 'UNKNOWN'
            direction = parts[1] if len(parts) > 1 else 'UNKNOWN'
            
            moves = [o['move_pct'] for o in opps]
            potentials = [o['potential_profit'] for o in opps]
            
            analysis["by_symbol_direction"][combo] = {
                "count": len(opps),
                "avg_move": round(statistics.mean(moves), 2) if moves else 0,
                "total_potential": round(sum(potentials), 2),
            }
            
            if len(opps) >= 2 and sum(potentials) >= 50:
                analysis["recommended_rules"].append({
                    "type": "offensive",
                    "pattern": combo,
                    "symbol": symbol,
                    "direction": direction,
                    "action": "ADD_SIGNAL_SENSITIVITY",
                    "evidence": f"{len(opps)} missed opportunities worth ${sum(potentials):.0f}",
                    "recommendation": f"Lower signal threshold for {symbol} {direction}",
                    "priority": "HIGH" if sum(potentials) >= 100 else "MEDIUM",
                })
        
        sorted_opps = sorted(opportunities, key=lambda x: x.get('move_pct', 0), reverse=True)
        analysis["top_opportunities"] = sorted_opps[:15]
        
        return analysis
    
    def generate_offensive_rules(self, analysis: Dict) -> Dict:
        """
        Generate rules to capture opportunities we've been missing.
        These are OFFENSIVE rules - designed to find more trades.
        """
        rules = {
            "version": 1,
            "generated_at": datetime.utcnow().isoformat(),
            "type": "offensive",
            "purpose": "Capture missed profitable opportunities",
            "by_symbol": {},
            "by_direction": {},
            "global": {
                "lower_entry_threshold": False,
                "increase_sensitivity": False,
            },
            "specific_actions": [],
        }
        
        for rec in analysis.get("recommended_rules", []):
            symbol = rec.get("symbol")
            direction = rec.get("direction")
            
            if symbol and symbol != "UNKNOWN":
                if symbol not in rules["by_symbol"]:
                    rules["by_symbol"][symbol] = {
                        "lower_ofi_threshold": 0.0,
                        "lower_ensemble_threshold": 0.0,
                        "boost_sizing": 1.0,
                        "opportunities_missed": 0,
                        "potential_missed": 0,
                    }
                
                symbol_data = analysis["by_symbol"].get(symbol, {})
                rules["by_symbol"][symbol]["lower_ofi_threshold"] = -0.05
                rules["by_symbol"][symbol]["opportunities_missed"] = symbol_data.get("count", 0)
                rules["by_symbol"][symbol]["potential_missed"] = symbol_data.get("total_potential", 0)
            
            if direction and direction != "UNKNOWN":
                if direction not in rules["by_direction"]:
                    rules["by_direction"][direction] = {
                        "boost_sensitivity": 1.0,
                        "opportunities_missed": 0,
                    }
                
                dir_data = analysis["by_direction"].get(direction, {})
                rules["by_direction"][direction]["opportunities_missed"] = dir_data.get("count", 0)
            
            rules["specific_actions"].append({
                "pattern": rec.get("pattern"),
                "action": "LOWER_THRESHOLD",
                "delta": -0.05,
                "evidence": rec.get("evidence"),
            })
        
        if analysis.get("total_potential_profit", 0) > 200:
            rules["global"]["increase_sensitivity"] = True
            rules["global"]["sensitivity_boost"] = 0.1
        
        save_json(OFFENSIVE_RULES_PATH, rules)
        print(f"💾 Saved offensive rules to {OFFENSIVE_RULES_PATH}")
        
        return rules
    
    def run_full_scan(self) -> Dict:
        """Run the complete missed opportunity scan and analysis."""
        print("=" * 70)
        print("🎯 MISSED OPPORTUNITY SCANNER - OFFENSIVE LEARNING")
        print("=" * 70)
        print(f"Lookback: {self.lookback_hours} hours")
        print(f"Minimum move: {self.min_move_pct}%")
        print()
        
        print("📊 Scanning price history for missed opportunities...")
        opportunities = self.scan_price_moves()
        
        if not opportunities:
            print("✅ No significant missed opportunities found")
            return {"status": "clean", "opportunities": 0}
        
        print(f"\n🔥 Found {len(opportunities)} missed opportunities!")
        
        analysis = self.analyze_patterns(opportunities)
        
        rules = self.generate_offensive_rules(analysis)
        
        self._print_summary(analysis, rules)
        
        return {
            "status": "found",
            "opportunities": len(opportunities),
            "total_potential": analysis.get("total_potential_profit", 0),
            "rules_generated": len(rules.get("specific_actions", [])),
            "analysis": analysis,
            "rules": rules,
        }
    
    def _print_summary(self, analysis: Dict, rules: Dict):
        """Print summary of findings."""
        print("\n" + "=" * 70)
        print("📋 MISSED OPPORTUNITY SUMMARY")
        print("=" * 70)
        
        print(f"\n💰 Total Potential Missed: ${analysis.get('total_potential_profit', 0):.2f}")
        print(f"📊 Total Opportunities: {analysis.get('total_opportunities', 0)}")
        
        print("\n📈 BY SYMBOL (opportunities missed):")
        by_symbol = analysis.get("by_symbol", {})
        sorted_symbols = sorted(by_symbol.items(), key=lambda x: x[1].get('total_potential', 0), reverse=True)
        for symbol, data in sorted_symbols[:8]:
            print(f"  {symbol}: {data['count']} opps, avg {data['avg_move']}% move, ${data['total_potential']:.0f} potential")
        
        print("\n📊 BY DIRECTION:")
        by_dir = analysis.get("by_direction", {})
        for direction, data in by_dir.items():
            print(f"  {direction}: {data['count']} opps, avg {data['avg_move']}% move, ${data['total_potential']:.0f} potential")
        
        print("\n🔧 RECOMMENDED RULES:")
        for rule in analysis.get("recommended_rules", [])[:8]:
            print(f"  • {rule['pattern']}: {rule['recommendation']} ({rule['priority']})")
            print(f"    Evidence: {rule['evidence']}")
        
        print("\n🔥 TOP MISSED OPPORTUNITIES:")
        for opp in analysis.get("top_opportunities", [])[:5]:
            print(f"  • {opp['symbol']} {opp['direction']}: {opp['move_pct']}% move (${opp['potential_profit']:.0f})")
            print(f"    Time: {opp['timestamp']}")


class AggressiveLearner:
    """
    Combines missed opportunity analysis with existing learning
    to create a complete offensive+defensive learning system.
    """
    
    def __init__(self):
        self.scanner = MissedOpportunityScanner(lookback_hours=48, min_move_pct=0.8)
        self.existing_rules = self._load_existing_rules()
    
    def _load_existing_rules(self) -> Dict:
        """Load existing learned rules."""
        if os.path.exists(DR.LEARNED_RULES):
            try:
                with open(DR.LEARNED_RULES, 'r') as f:
                    return json.load(f)
            except:
                pass
        return {}
    
    def run_aggressive_learning(self) -> Dict:
        """
        Run aggressive learning cycle:
        1. Scan for missed opportunities (offensive)
        2. Analyze blocked signals that would have won (defensive improvement)
        3. Merge into unified rules
        """
        print("=" * 70)
        print("🚀 AGGRESSIVE LEARNING CYCLE")
        print("=" * 70)
        print()
        
        print("PHASE 1: Scanning for missed opportunities...")
        print("-" * 50)
        scan_results = self.scanner.run_full_scan()
        
        print("\n" + "=" * 50)
        print("PHASE 2: Analyzing blocked signals...")
        print("-" * 50)
        blocked_analysis = self._analyze_blocked_winners()
        
        print("\n" + "=" * 50)
        print("PHASE 3: Merging into unified rules...")
        print("-" * 50)
        unified = self._merge_rules(scan_results, blocked_analysis)
        
        print("\n" + "=" * 70)
        print("✅ AGGRESSIVE LEARNING COMPLETE")
        print("=" * 70)
        print(f"Missed opportunities found: {scan_results.get('opportunities', 0)}")
        print(f"Potential profit missed: ${scan_results.get('total_potential', 0):.2f}")
        print(f"Blocked winners found: {blocked_analysis.get('blocked_winners', 0)}")
        print(f"New offensive rules: {unified.get('offensive_rules_added', 0)}")
        
        return unified
    
    def _analyze_blocked_winners(self) -> Dict:
        """Analyze blocked signals that would have been profitable."""
        counterfactual = load_jsonl(DR.COUNTERFACTUAL_OUTCOMES)
        
        winners = [cf for cf in counterfactual if cf.get('would_have_won', False)]
        
        print(f"  Found {len(winners)} blocked signals that would have won")
        
        by_gate = defaultdict(list)
        for w in winners:
            gate = w.get('blocked_by_gate', 'unknown')
            by_gate[gate].append(w)
        
        print("\n  BY BLOCKING GATE:")
        for gate, blocked in sorted(by_gate.items(), key=lambda x: -len(x[1]))[:5]:
            potential = sum(b.get('potential_pnl', 0) for b in blocked)
            print(f"    {gate}: {len(blocked)} winners blocked (${potential:.0f} potential)")
        
        return {
            "blocked_winners": len(winners),
            "by_gate": {k: len(v) for k, v in by_gate.items()},
            "gates_to_loosen": [g for g, v in by_gate.items() if len(v) >= 3],
        }
    
    def _merge_rules(self, scan_results: Dict, blocked_analysis: Dict) -> Dict:
        """Merge offensive and defensive learnings into unified rules."""
        offensive_rules = scan_results.get("rules", {})
        
        merged = {
            "version": self.existing_rules.get("version", 0) + 1,
            "generated_at": datetime.utcnow().isoformat(),
            "learning_type": "aggressive",
            "offensive": offensive_rules,
            "gates_to_loosen": blocked_analysis.get("gates_to_loosen", []),
            "defensive": self.existing_rules,
            "offensive_rules_added": len(offensive_rules.get("specific_actions", [])),
        }
        
        save_json("feature_store/aggressive_learning_results.json", merged)
        print(f"  💾 Saved merged rules to feature_store/aggressive_learning_results.json")
        
        return merged


def main():
    import argparse
    
    parser = argparse.ArgumentParser(description="Missed Opportunity Scanner")
    parser.add_argument("--hours", type=int, default=24, help="Lookback hours")
    parser.add_argument("--min-move", type=float, default=1.0, help="Minimum move %")
    parser.add_argument("--aggressive", action="store_true", help="Run full aggressive learning")
    args = parser.parse_args()
    
    if args.aggressive:
        learner = AggressiveLearner()
        results = learner.run_aggressive_learning()
    else:
        scanner = MissedOpportunityScanner(
            lookback_hours=args.hours,
            min_move_pct=args.min_move
        )
        results = scanner.run_full_scan()
    
    print("\n📊 Results saved to:")
    print(f"  - {MISSED_OPPS_PATH}")
    print(f"  - {OFFENSIVE_RULES_PATH}")
    
    return results


def run_with_rotation_analysis(lookback_hours: int = 24) -> Dict:
    """
    Run missed opportunity scanner with integrated rotation analysis.
    This provides a complete picture of:
    1. Single-coin missed opportunities (what moves we didn't catch)
    2. Cross-coin rotation opportunities (where we should have moved capital)
    """
    print("=" * 70)
    print("🎯 COMPREHENSIVE OPPORTUNITY ANALYSIS")
    print("   (Single-Coin Missed + Cross-Coin Rotation)")
    print("=" * 70)
    
    print("\n📊 PHASE 1: Single-Coin Missed Opportunities")
    print("-" * 50)
    scanner = MissedOpportunityScanner(lookback_hours=lookback_hours, min_move_pct=0.8)
    missed_results = scanner.run_full_scan()
    
    print("\n🔄 PHASE 2: Cross-Coin Rotation Opportunities")
    print("-" * 50)
    try:
        from src.cross_coin_rotation_analyzer import CrossCoinRotationAnalyzer
        rotation_analyzer = CrossCoinRotationAnalyzer(lookback_hours=lookback_hours)
        rotation_results = rotation_analyzer.run_full_analysis()
    except Exception as e:
        print(f"⚠️ Rotation analysis error: {e}")
        rotation_results = {"error": str(e)}
    
    combined = {
        "timestamp": datetime.utcnow().isoformat(),
        "lookback_hours": lookback_hours,
        "missed_opportunities": {
            "count": missed_results.get("opportunities", 0),
            "total_potential": missed_results.get("total_potential", 0),
            "rules_generated": missed_results.get("rules_generated", 0),
        },
        "rotation_opportunities": {
            "count": rotation_results.get("total_opportunities", 0),
            "total_opportunity_cost": rotation_results.get("total_opportunity_cost_pct", 0),
            "rules_generated": rotation_results.get("rules_generated", 0),
        },
        "combined_potential_pct": (
            missed_results.get("total_potential", 0) / 100 +
            rotation_results.get("total_opportunity_cost_pct", 0)
        ),
    }
    
    save_json("feature_store/comprehensive_opportunity_analysis.json", combined)
    
    print("\n" + "=" * 70)
    print("📊 COMPREHENSIVE OPPORTUNITY SUMMARY")
    print("=" * 70)
    print(f"   Single-Coin Missed: {combined['missed_opportunities']['count']} opportunities")
    print(f"   Rotation Missed: {combined['rotation_opportunities']['count']} opportunities")
    print(f"   Combined Potential: {combined['combined_potential_pct']:.1f}% missed gains")
    
    return combined


def enrich_with_rotation_context(opportunity: Dict, all_coins_data: Dict) -> Dict:
    """
    Enrich a missed opportunity with rotation context.
    Adds information about what other coins were doing at that time.
    """
    opp_symbol = opportunity.get('symbol', '')
    opp_time = opportunity.get('timestamp', '')
    
    other_coins = {}
    for symbol, moves in all_coins_data.items():
        if symbol != opp_symbol:
            matching_moves = [m for m in moves if abs(m.get('ts', 0) - opportunity.get('ts', 0)) < 3600]
            if matching_moves:
                best_move = max(matching_moves, key=lambda x: abs(x.get('move_pct', 0)))
                other_coins[symbol] = {
                    "move_pct": best_move.get('move_pct', 0),
                    "direction": best_move.get('direction', 'UNKNOWN'),
                }
    
    opportunity['rotation_context'] = {
        'other_coins_at_time': other_coins,
        'best_alternative': max(other_coins.items(), key=lambda x: x[1]['move_pct'])[0] if other_coins else None,
        'best_alternative_move': max(other_coins.values(), key=lambda x: x['move_pct'])['move_pct'] if other_coins else 0,
    }
    
    return opportunity


if __name__ == "__main__":
    main()
