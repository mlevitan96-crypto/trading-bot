"""
Cross-Coin Rotation Analyzer
============================
Analyzes historical data to identify optimal cross-coin rotation opportunities.
Answers: "When should we have moved capital from Coin A to Coin B?"

This module:
1. Scans price moves across ALL coins simultaneously
2. Identifies rotation opportunities (exit losing/stagnant, enter winning)
3. Calculates theoretical returns from optimal rotation
4. Generates rotation rules for the learning system
5. Integrates with missed opportunity tracker and counterfactual analysis

Key Concepts:
- Rotation Window: Time period to analyze for rotation decisions (default 15min)
- Opportunity Cost: Money lost by staying in wrong coin vs rotating
- Rotation Score: Composite score for when rotation would have been profitable
"""

import json
import time
import statistics
from datetime import datetime, timedelta
from pathlib import Path
from collections import defaultdict, deque
from typing import Dict, List, Optional, Tuple, Deque
from dataclasses import dataclass, asdict

from src.data_registry import DR

LOGS_DIR = Path("logs")
FEATURE_STORE = Path("feature_store")
LOGS_DIR.mkdir(exist_ok=True)
FEATURE_STORE.mkdir(exist_ok=True)

ROTATION_LOG = LOGS_DIR / "rotation_opportunities.jsonl"
ROTATION_ANALYSIS = FEATURE_STORE / "rotation_analysis.json"
ROTATION_RULES = FEATURE_STORE / "rotation_rules.json"

# Use DataRegistry for canonical symbol list
def get_asset_universe():
    """Get asset universe from DataRegistry (dynamic, all 15 coins)."""
    try:
        return DR.get_enabled_symbols()
    except Exception:
        # Fallback includes ALL 15 coins
        return [
            "BTCUSDT", "ETHUSDT", "SOLUSDT", "AVAXUSDT", "DOTUSDT",
            "TRXUSDT", "XRPUSDT", "ADAUSDT", "DOGEUSDT", "BNBUSDT",
            "MATICUSDT", "LINKUSDT", "ARBUSDT", "OPUSDT", "PEPEUSDT"
        ]

ASSET_UNIVERSE = get_asset_universe()


@dataclass(slots=True)
class RotationOpportunity:
    """Represents a missed rotation opportunity. Uses slots for memory efficiency."""
    timestamp: str
    ts: float
    from_symbol: str
    to_symbol: str
    from_direction: str
    to_direction: str
    from_move_pct: float
    to_move_pct: float
    opportunity_cost_pct: float
    rotation_window_min: int
    from_regime: str
    to_regime: str
    market_context: Dict
    

@dataclass(slots=True)
class CoinSnapshot:
    """Price snapshot for a single coin at a point in time. Uses slots for memory efficiency."""
    symbol: str
    timestamp: datetime
    price: float
    move_1m: float
    move_5m: float
    move_15m: float
    volume_ratio: float
    momentum: float
    volatility: float


MAX_OPPORTUNITIES = 500
MAX_COIN_MOVES = 200
MAX_ROTATION_PATTERNS = 200


class CrossCoinRotationAnalyzer:
    """
    Analyzes cross-coin rotation opportunities to find optimal capital rotation.
    
    This is OFFENSIVE learning - finding where we could have rotated capital
    to capture better moves across the coin universe.
    
    Memory-optimized: Uses bounded deques to prevent unbounded memory growth.
    """
    
    def __init__(self, lookback_hours: int = 24, rotation_window_min: int = 15):
        self.lookback_hours = lookback_hours
        self.rotation_window_min = rotation_window_min
        self.opportunities: Deque[RotationOpportunity] = deque(maxlen=MAX_OPPORTUNITIES)
        self._coin_moves: Dict[str, Deque[Dict]] = defaultdict(lambda: deque(maxlen=MAX_COIN_MOVES))
        self._rotation_patterns: Dict[str, Deque[Dict]] = defaultdict(lambda: deque(maxlen=MAX_ROTATION_PATTERNS))
        
        self.trades = self._load_trades()
        self.enriched = self._load_enriched_decisions()
        self.missed_opps = self._load_missed_opportunities()
        
        print(f"🔄 Rotation Analyzer initialized: {self.lookback_hours}h lookback, {self.rotation_window_min}min windows")
        print(f"   📊 Loaded {len(self.trades)} trades, {len(self.enriched)} decisions, {len(self.missed_opps)} missed opportunities")
    
    def _load_trades(self) -> List[Dict]:
        """Load recent trades."""
        try:
            trades = DR.read_jsonl(str(DR.TRADES_CANONICAL), last_n=500)
            cutoff = time.time() - (self.lookback_hours * 3600)
            return [t for t in trades if t.get('ts', 0) > cutoff]
        except Exception as e:
            print(f"   ⚠️ Could not load trades: {e}")
            return []
    
    def _load_enriched_decisions(self) -> List[Dict]:
        """Load enriched decision records."""
        try:
            decisions = DR.read_jsonl(str(DR.ENRICHED_DECISIONS), last_n=1000)
            cutoff = time.time() - (self.lookback_hours * 3600)
            return [d for d in decisions if d.get('ts', 0) > cutoff]
        except Exception as e:
            print(f"   ⚠️ Could not load enriched decisions: {e}")
            return []
    
    def _load_missed_opportunities(self) -> List[Dict]:
        """Load missed opportunity records."""
        try:
            if Path("logs/missed_opportunities.jsonl").exists():
                return DR.read_jsonl("logs/missed_opportunities.jsonl", last_n=500)
            elif Path("logs/missed_opportunities.json").exists():
                with open("logs/missed_opportunities.json", 'r') as f:
                    data = json.load(f)
                    return data.get("missed_trades", [])
            return []
        except Exception as e:
            print(f"   ⚠️ Could not load missed opportunities: {e}")
            return []
    
    def _get_exchange_gateway(self):
        """Get exchange gateway for price data."""
        try:
            from src.exchange_gateway import ExchangeGateway
            return ExchangeGateway()
        except Exception as e:
            print(f"   ⚠️ Could not initialize exchange gateway: {e}")
            return None
    
    def fetch_coin_snapshots(self) -> Dict[str, List[CoinSnapshot]]:
        """
        Fetch price snapshots for all coins over the lookback period.
        Returns dict of symbol -> list of snapshots.
        """
        gateway = self._get_exchange_gateway()
        if not gateway:
            return {}
        
        all_snapshots = {}
        
        for symbol in ASSET_UNIVERSE:
            try:
                df = gateway.fetch_ohlcv(symbol, timeframe="15m", limit=96, venue="futures")
                if df is None or len(df) < 10:
                    continue
                
                snapshots = []
                for i in range(5, len(df)):
                    row = df.iloc[i]
                    
                    move_1m = (row['close'] - df.iloc[i-1]['close']) / df.iloc[i-1]['close'] * 100
                    move_5m = (row['close'] - df.iloc[max(0, i-5)]['close']) / df.iloc[max(0, i-5)]['close'] * 100
                    move_15m = (row['close'] - df.iloc[max(0, i-1)]['close']) / df.iloc[max(0, i-1)]['close'] * 100
                    
                    avg_vol = df.iloc[max(0, i-10):i]['volume'].mean()
                    vol_ratio = row['volume'] / avg_vol if avg_vol > 0 else 1.0
                    
                    momentum = df.iloc[max(0, i-3):i+1]['close'].diff().mean()
                    
                    volatility = df.iloc[max(0, i-10):i+1]['close'].pct_change().std() * 100
                    
                    ts = row['timestamp']
                    if isinstance(ts, str):
                        ts = datetime.fromisoformat(ts.replace('Z', '+00:00'))
                    elif isinstance(ts, (int, float)):
                        ts = datetime.utcfromtimestamp(ts)
                    
                    snapshots.append(CoinSnapshot(
                        symbol=symbol,
                        timestamp=ts,
                        price=row['close'],
                        move_1m=round(move_1m, 4),
                        move_5m=round(move_5m, 4),
                        move_15m=round(move_15m, 4),
                        volume_ratio=round(vol_ratio, 2),
                        momentum=round(momentum, 6),
                        volatility=round(volatility, 4)
                    ))
                
                all_snapshots[symbol] = snapshots
                print(f"   ✅ {symbol}: {len(snapshots)} snapshots")
                
            except Exception as e:
                print(f"   ⚠️ {symbol}: Error fetching data - {e}")
        
        return all_snapshots
    
    def find_rotation_opportunities(self, snapshots: Dict[str, List[CoinSnapshot]]) -> List[RotationOpportunity]:
        """
        Find opportunities where rotating from one coin to another would have been profitable.
        
        Criteria for rotation opportunity:
        1. Coin A was held but moved against us (or stagnated)
        2. Coin B moved in our favor (significant move we could have captured)
        3. The opportunity cost exceeds a threshold (>0.5%)
        """
        if not snapshots:
            print("❌ No snapshots available for rotation analysis")
            return []
        
        opportunities = []
        
        symbols = list(snapshots.keys())
        if len(symbols) < 2:
            print("❌ Need at least 2 symbols for rotation analysis")
            return []
        
        min_len = min(len(snapshots[s]) for s in symbols)
        
        for i in range(min_len):
            coins_at_time = []
            for symbol in symbols:
                if i < len(snapshots[symbol]):
                    coins_at_time.append(snapshots[symbol][i])
            
            if len(coins_at_time) < 2:
                continue
            
            sorted_by_move = sorted(coins_at_time, key=lambda x: x.move_15m, reverse=True)
            
            best_long = sorted_by_move[0]
            worst_for_long = sorted_by_move[-1]
            
            sorted_by_short = sorted(coins_at_time, key=lambda x: x.move_15m)
            best_short = sorted_by_short[0]
            
            if best_long.move_15m > 0.5 and worst_for_long.move_15m < -0.1:
                opportunity_cost = best_long.move_15m - worst_for_long.move_15m
                
                if opportunity_cost >= 0.5:
                    opp = RotationOpportunity(
                        timestamp=best_long.timestamp.isoformat() if hasattr(best_long.timestamp, 'isoformat') else str(best_long.timestamp),
                        ts=time.time(),
                        from_symbol=worst_for_long.symbol,
                        to_symbol=best_long.symbol,
                        from_direction="LONG",
                        to_direction="LONG",
                        from_move_pct=round(worst_for_long.move_15m, 2),
                        to_move_pct=round(best_long.move_15m, 2),
                        opportunity_cost_pct=round(opportunity_cost, 2),
                        rotation_window_min=self.rotation_window_min,
                        from_regime=self._classify_move(worst_for_long),
                        to_regime=self._classify_move(best_long),
                        market_context={
                            "from_volatility": worst_for_long.volatility,
                            "to_volatility": best_long.volatility,
                            "from_volume_ratio": worst_for_long.volume_ratio,
                            "to_volume_ratio": best_long.volume_ratio,
                            "coins_analyzed": len(coins_at_time),
                            "best_move_available": best_long.move_15m,
                            "worst_move_available": worst_for_long.move_15m,
                        }
                    )
                    opportunities.append(opp)
            
            if best_short.move_15m < -0.5 and worst_for_long.move_15m > 0.1:
                opportunity_cost = abs(best_short.move_15m) - worst_for_long.move_15m
                
                if opportunity_cost >= 0.5:
                    opp = RotationOpportunity(
                        timestamp=best_short.timestamp.isoformat() if hasattr(best_short.timestamp, 'isoformat') else str(best_short.timestamp),
                        ts=time.time(),
                        from_symbol=worst_for_long.symbol,
                        to_symbol=best_short.symbol,
                        from_direction="LONG",
                        to_direction="SHORT",
                        from_move_pct=round(worst_for_long.move_15m, 2),
                        to_move_pct=round(best_short.move_15m, 2),
                        opportunity_cost_pct=round(opportunity_cost, 2),
                        rotation_window_min=self.rotation_window_min,
                        from_regime=self._classify_move(worst_for_long),
                        to_regime=self._classify_move(best_short),
                        market_context={
                            "from_volatility": worst_for_long.volatility,
                            "to_volatility": best_short.volatility,
                            "from_volume_ratio": worst_for_long.volume_ratio,
                            "to_volume_ratio": best_short.volume_ratio,
                            "coins_analyzed": len(coins_at_time),
                        }
                    )
                    opportunities.append(opp)
        
        self.opportunities = opportunities
        print(f"🔄 Found {len(opportunities)} rotation opportunities")
        return opportunities
    
    def _classify_move(self, snapshot: CoinSnapshot) -> str:
        """Classify the market move type."""
        if snapshot.move_15m > 1.0:
            return "STRONG_UP"
        elif snapshot.move_15m > 0.3:
            return "UP"
        elif snapshot.move_15m > -0.3:
            return "FLAT"
        elif snapshot.move_15m > -1.0:
            return "DOWN"
        else:
            return "STRONG_DOWN"
    
    def analyze_rotation_patterns(self) -> Dict:
        """
        Analyze patterns in rotation opportunities to generate rules.
        This helps learn WHEN to rotate and BETWEEN which coins.
        """
        if not self.opportunities:
            return {"error": "No opportunities to analyze"}
        
        print(f"\n🔬 Analyzing {len(self.opportunities)} rotation opportunities...")
        
        by_from_symbol = defaultdict(list)
        by_to_symbol = defaultdict(list)
        by_pair = defaultdict(list)
        by_direction_combo = defaultdict(list)
        
        total_opportunity_cost = 0
        
        for opp in self.opportunities:
            by_from_symbol[opp.from_symbol].append(opp)
            by_to_symbol[opp.to_symbol].append(opp)
            by_pair[f"{opp.from_symbol} → {opp.to_symbol}"].append(opp)
            by_direction_combo[f"{opp.from_direction} → {opp.to_direction}"].append(opp)
            total_opportunity_cost += opp.opportunity_cost_pct
        
        analysis = {
            "timestamp": datetime.utcnow().isoformat(),
            "total_opportunities": len(self.opportunities),
            "total_opportunity_cost_pct": round(total_opportunity_cost, 2),
            "avg_opportunity_cost_pct": round(total_opportunity_cost / len(self.opportunities), 2) if self.opportunities else 0,
            "frequently_rotated_from": {},
            "frequently_rotated_to": {},
            "best_rotation_pairs": {},
            "direction_patterns": {},
            "rotation_rules": [],
        }
        
        for symbol, opps in sorted(by_from_symbol.items(), key=lambda x: len(x[1]), reverse=True):
            costs = [o.opportunity_cost_pct for o in opps]
            analysis["frequently_rotated_from"][symbol] = {
                "count": len(opps),
                "avg_cost": round(statistics.mean(costs), 2) if costs else 0,
                "total_cost": round(sum(costs), 2),
                "interpretation": "Consider shorter holds or tighter stops"
            }
        
        for symbol, opps in sorted(by_to_symbol.items(), key=lambda x: len(x[1]), reverse=True):
            moves = [o.to_move_pct for o in opps]
            analysis["frequently_rotated_to"][symbol] = {
                "count": len(opps),
                "avg_move": round(statistics.mean(moves), 2) if moves else 0,
                "max_move": round(max(moves), 2) if moves else 0,
                "interpretation": "Good rotation target - consider priority scanning"
            }
        
        for pair, opps in sorted(by_pair.items(), key=lambda x: len(x[1]), reverse=True)[:10]:
            costs = [o.opportunity_cost_pct for o in opps]
            analysis["best_rotation_pairs"][pair] = {
                "count": len(opps),
                "avg_cost": round(statistics.mean(costs), 2) if costs else 0,
                "total_cost": round(sum(costs), 2),
            }
        
        for combo, opps in by_direction_combo.items():
            costs = [o.opportunity_cost_pct for o in opps]
            analysis["direction_patterns"][combo] = {
                "count": len(opps),
                "avg_cost": round(statistics.mean(costs), 2) if costs else 0,
            }
        
        for symbol, data in analysis["frequently_rotated_from"].items():
            if data["count"] >= 3 and data["avg_cost"] >= 0.5:
                analysis["rotation_rules"].append({
                    "type": "EXIT_FASTER",
                    "symbol": symbol,
                    "reason": f"Frequently rotated FROM with avg {data['avg_cost']}% opportunity cost",
                    "recommendation": "Reduce hold time or tighten stops",
                    "priority": "HIGH" if data["avg_cost"] >= 1.0 else "MEDIUM"
                })
        
        for symbol, data in analysis["frequently_rotated_to"].items():
            if data["count"] >= 3 and data["avg_move"] >= 0.8:
                analysis["rotation_rules"].append({
                    "type": "SCAN_PRIORITY",
                    "symbol": symbol,
                    "reason": f"Frequently rotated TO with avg {data['avg_move']}% moves",
                    "recommendation": "Prioritize in signal scanning",
                    "priority": "HIGH" if data["avg_move"] >= 1.5 else "MEDIUM"
                })
        
        return analysis
    
    def integrate_with_trades(self) -> Dict:
        """
        Cross-reference rotation opportunities with actual trades.
        Identify where we were in the wrong coin at the wrong time.
        """
        if not self.trades or not self.opportunities:
            return {"status": "insufficient_data"}
        
        print(f"\n🔗 Cross-referencing {len(self.opportunities)} opportunities with {len(self.trades)} trades...")
        
        missed_rotations = []
        
        for opp in self.opportunities:
            opp_time = opp.timestamp
            if isinstance(opp_time, str):
                try:
                    opp_time = datetime.fromisoformat(opp_time.replace('Z', '+00:00'))
                except:
                    continue
            
            for trade in self.trades:
                trade_symbol = trade.get('symbol', '')
                trade_time = trade.get('timestamp') or trade.get('ts', 0)
                
                if isinstance(trade_time, (int, float)):
                    trade_time = datetime.utcfromtimestamp(trade_time)
                elif isinstance(trade_time, str):
                    try:
                        trade_time = datetime.fromisoformat(trade_time.replace('Z', '+00:00'))
                    except:
                        continue
                
                if trade_symbol == opp.from_symbol:
                    time_diff = abs((opp_time - trade_time).total_seconds())
                    if time_diff < 3600:
                        trade_pnl = trade.get('net_pnl_usd') or trade.get('pnl_usd', 0)
                        
                        missed_rotations.append({
                            "timestamp": opp.timestamp,
                            "held_symbol": opp.from_symbol,
                            "missed_symbol": opp.to_symbol,
                            "held_pnl": trade_pnl,
                            "potential_gain_pct": opp.to_move_pct,
                            "opportunity_cost_pct": opp.opportunity_cost_pct,
                            "should_have_rotated": opp.opportunity_cost_pct > 0.5,
                        })
        
        return {
            "total_missed_rotations": len(missed_rotations),
            "missed_rotations": missed_rotations[:20],
            "total_opportunity_cost": sum(m["opportunity_cost_pct"] for m in missed_rotations),
        }
    
    def generate_rotation_rules(self, analysis: Dict) -> Dict:
        """
        Generate actionable rotation rules for the learning system.
        These rules can be used by the execution engine.
        """
        rules = {
            "version": 1,
            "generated_at": datetime.utcnow().isoformat(),
            "type": "rotation",
            "purpose": "Optimize cross-coin capital rotation",
            
            "exit_faster": {},
            
            "scan_priority": {},
            
            "rotation_pairs": {},
            
            "global_settings": {
                "enable_rotation_scanning": True,
                "min_rotation_opportunity_pct": 0.5,
                "max_hold_before_rotation_check_min": 15,
            }
        }
        
        for rule in analysis.get("rotation_rules", []):
            symbol = rule.get("symbol", "")
            rule_type = rule.get("type", "")
            
            if rule_type == "EXIT_FASTER" and symbol:
                rules["exit_faster"][symbol] = {
                    "reason": rule.get("reason"),
                    "action": "REDUCE_HOLD_TIME",
                    "hold_time_reduction_pct": 25 if rule.get("priority") == "HIGH" else 15,
                }
            
            elif rule_type == "SCAN_PRIORITY" and symbol:
                rules["scan_priority"][symbol] = {
                    "reason": rule.get("reason"),
                    "action": "BOOST_SIGNAL_WEIGHT",
                    "weight_boost": 1.2 if rule.get("priority") == "HIGH" else 1.1,
                }
        
        for pair, data in analysis.get("best_rotation_pairs", {}).items():
            if data.get("count", 0) >= 3:
                rules["rotation_pairs"][pair] = {
                    "frequency": data["count"],
                    "avg_opportunity_cost": data["avg_cost"],
                    "action": "MONITOR_ROTATION",
                }
        
        with open(ROTATION_RULES, 'w') as f:
            json.dump(rules, f, indent=2)
        print(f"💾 Saved rotation rules to {ROTATION_RULES}")
        
        return rules
    
    def save_opportunities(self):
        """Save rotation opportunities to log file."""
        for opp in self.opportunities:
            with open(ROTATION_LOG, 'a') as f:
                f.write(json.dumps(asdict(opp), default=str) + '\n')
        print(f"💾 Saved {len(self.opportunities)} rotation opportunities to {ROTATION_LOG}")
    
    def run_full_analysis(self) -> Dict:
        """
        Run complete rotation analysis pipeline.
        
        Returns comprehensive analysis including:
        - Rotation opportunities found
        - Patterns identified
        - Integration with actual trades
        - Generated rules
        """
        print("\n" + "="*60)
        print("🔄 CROSS-COIN ROTATION ANALYSIS")
        print("="*60)
        
        print("\n📡 Step 1: Fetching price snapshots for all coins...")
        snapshots = self.fetch_coin_snapshots()
        
        if not snapshots:
            return {"error": "Could not fetch price data"}
        
        print("\n🔍 Step 2: Finding rotation opportunities...")
        opportunities = self.find_rotation_opportunities(snapshots)
        
        print("\n🔬 Step 3: Analyzing rotation patterns...")
        analysis = self.analyze_rotation_patterns()
        
        print("\n🔗 Step 4: Cross-referencing with actual trades...")
        trade_integration = self.integrate_with_trades()
        
        print("\n📝 Step 5: Generating rotation rules...")
        rules = self.generate_rotation_rules(analysis)
        
        print("\n💾 Step 6: Saving results...")
        self.save_opportunities()
        
        full_analysis = {
            **analysis,
            "trade_integration": trade_integration,
            "rules_generated": len(rules.get("exit_faster", {})) + len(rules.get("scan_priority", {})),
        }
        
        with open(ROTATION_ANALYSIS, 'w') as f:
            json.dump(full_analysis, f, indent=2, default=str)
        print(f"💾 Saved full analysis to {ROTATION_ANALYSIS}")
        
        print("\n" + "="*60)
        print("🔄 ROTATION ANALYSIS SUMMARY")
        print("="*60)
        print(f"   📊 Total opportunities found: {full_analysis.get('total_opportunities', 0)}")
        print(f"   💰 Total opportunity cost: {full_analysis.get('total_opportunity_cost_pct', 0):.1f}%")
        print(f"   📈 Avg opportunity cost: {full_analysis.get('avg_opportunity_cost_pct', 0):.2f}%")
        print(f"   🔗 Missed rotations: {trade_integration.get('total_missed_rotations', 0)}")
        print(f"   📝 Rules generated: {full_analysis.get('rules_generated', 0)}")
        
        return full_analysis


def add_rotation_to_enriched_decision(decision: Dict, rotation_context: Dict) -> Dict:
    """
    Add rotation context to an enriched decision record.
    This allows counterfactual analysis to include rotation opportunities.
    """
    decision['rotation_context'] = {
        'better_coins_available': rotation_context.get('better_coins', []),
        'best_alternative_symbol': rotation_context.get('best_alternative'),
        'best_alternative_move_pct': rotation_context.get('best_move_pct'),
        'rotation_opportunity_cost_pct': rotation_context.get('opportunity_cost_pct', 0),
        'should_have_rotated': rotation_context.get('opportunity_cost_pct', 0) > 0.5,
    }
    return decision


def get_rotation_recommendation(current_symbol: str, current_direction: str) -> Optional[Dict]:
    """
    Get rotation recommendation for current position.
    Called by execution engine to check if rotation is advisable.
    """
    try:
        if not ROTATION_RULES.exists():
            return None
        
        with open(ROTATION_RULES, 'r') as f:
            rules = json.load(f)
        
        exit_faster = rules.get("exit_faster", {}).get(current_symbol)
        if exit_faster:
            return {
                "action": "CONSIDER_EXIT",
                "reason": exit_faster.get("reason"),
                "hold_reduction_pct": exit_faster.get("hold_time_reduction_pct", 0),
            }
        
        for pair, data in rules.get("rotation_pairs", {}).items():
            if pair.startswith(f"{current_symbol} →"):
                target = pair.split(" → ")[1]
                return {
                    "action": "CONSIDER_ROTATION",
                    "target_symbol": target,
                    "frequency": data.get("frequency", 0),
                    "avg_opportunity_cost": data.get("avg_opportunity_cost", 0),
                }
        
        return None
        
    except Exception as e:
        return None


def run_rotation_analysis(lookback_hours: int = 24) -> Dict:
    """
    Convenience function to run full rotation analysis.
    """
    analyzer = CrossCoinRotationAnalyzer(lookback_hours=lookback_hours)
    return analyzer.run_full_analysis()


if __name__ == "__main__":
    import sys
    
    lookback = 24
    if len(sys.argv) > 1:
        try:
            lookback = int(sys.argv[1])
        except:
            pass
    
    result = run_rotation_analysis(lookback_hours=lookback)
    print(f"\n✅ Analysis complete: {result.get('total_opportunities', 0)} opportunities found")
