"""
PROFIT-SEEKER INTELLIGENCE ENGINE
=================================
A fundamentally different approach: Instead of avoiding losses, PREDICT PROFITS.

This engine:
1. Analyzes what happens BEFORE profitable trades (not after)
2. Builds multi-horizon predictive features (1m, 5m, 10m, 15m lookback)
3. Finds patterns that PRECEDE winning moves
4. Scores opportunities by EXPECTED PROFIT, not loss avoidance
5. Continuously learns from new outcomes

Author: Trading Bot System
Date: November 2025
"""

import json
import os
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple, Any
from collections import defaultdict
import math

DATA_DIR = "logs"
FEATURE_STORE = "feature_store"
REPORTS_DIR = "reports"


class ProfitSeeker:
    """
    The Profit-Seeker Engine - Find patterns that PREDICT profits.
    
    Key insight: We have data on what happened. Now we need to find
    what PRECEDES profitable outcomes and use that to predict future wins.
    """
    
    def __init__(self):
        self.trades = []
        self.winning_patterns = {}
        self.edge_model = {}
        self.feature_importance = {}
        
    def load_all_trades(self) -> List[Dict]:
        """Load all closed trades with full context."""
        trades = []
        
        positions_file = os.path.join(DATA_DIR, "positions_futures.json")
        if os.path.exists(positions_file):
            try:
                with open(positions_file, 'r') as f:
                    data = json.load(f)
                closed = data.get("closed_positions", [])
                for pos in closed:
                    if pos.get("pnl") is not None or pos.get("realized_pnl") is not None:
                        trades.append(pos)
            except:
                pass
        
        self.trades = trades
        return trades
    
    def build_feature_matrix(self) -> Dict[str, Any]:
        """
        Build comprehensive feature matrix for each trade.
        
        For each trade, extract:
        - Pre-trade price momentum (1m, 5m, 10m, 15m lookback)
        - Entry context (OFI, ensemble, regime)
        - Symbol characteristics
        - Time-of-day patterns
        - Outcome (P&L, duration, direction accuracy)
        """
        if not self.trades:
            self.load_all_trades()
        
        feature_matrix = []
        
        for trade in self.trades:
            features = self._extract_trade_features(trade)
            if features:
                feature_matrix.append(features)
        
        return {
            "total_trades": len(self.trades),
            "features_extracted": len(feature_matrix),
            "feature_matrix": feature_matrix
        }
    
    def _extract_trade_features(self, trade: Dict) -> Optional[Dict]:
        """Extract predictive features from a single trade."""
        try:
            entry_price = float(trade.get("entry_price", 0))
            exit_price = float(trade.get("exit_price", 0))
            pnl = float(trade.get("pnl") or trade.get("realized_pnl") or 0)
            
            if entry_price <= 0:
                return None
            
            symbol = trade.get("symbol", "UNKNOWN")
            side = (trade.get("side") or trade.get("direction") or "unknown").upper()
            bot_type = trade.get("bot_type", "alpha")
            
            entry_ts = trade.get("entry_time") or trade.get("opened_at")
            exit_ts = trade.get("exit_time") or trade.get("closed_at")
            
            entry_dt = None
            if entry_ts:
                try:
                    if isinstance(entry_ts, str):
                        entry_dt = datetime.fromisoformat(entry_ts.replace('Z', '+00:00'))
                    else:
                        entry_dt = datetime.fromtimestamp(entry_ts / 1000 if entry_ts > 1e12 else entry_ts)
                except:
                    pass
            
            hour_of_day = entry_dt.hour if entry_dt else 12
            day_of_week = entry_dt.weekday() if entry_dt else 0
            
            signal_ctx = trade.get("signal_context", {})
            ofi = abs(float(signal_ctx.get("ofi_confidence", 0.5)))
            ensemble = float(signal_ctx.get("ensemble_score", 0))
            regime = signal_ctx.get("regime_state", "unknown")
            
            price_change_pct = ((exit_price - entry_price) / entry_price) * 100 if entry_price > 0 else 0
            is_winner = pnl > 0
            is_direction_correct = (side == "LONG" and exit_price > entry_price) or \
                                   (side == "SHORT" and exit_price < entry_price)
            
            ofi_bucket = self._bucket_ofi(ofi)
            ensemble_bucket = self._bucket_ensemble(ensemble)
            hour_bucket = self._bucket_hour(hour_of_day)
            
            return {
                "symbol": symbol,
                "side": side,
                "bot_type": bot_type,
                "entry_price": entry_price,
                "exit_price": exit_price,
                "pnl": pnl,
                "pnl_pct": price_change_pct,
                "is_winner": is_winner,
                "is_direction_correct": is_direction_correct,
                "ofi": ofi,
                "ofi_bucket": ofi_bucket,
                "ensemble": ensemble,
                "ensemble_bucket": ensemble_bucket,
                "regime": regime,
                "hour_of_day": hour_of_day,
                "hour_bucket": hour_bucket,
                "day_of_week": day_of_week,
                "pattern_key": f"{symbol}|{side}|{ofi_bucket}|{ensemble_bucket}|{hour_bucket}"
            }
        except Exception as e:
            return None
    
    def _bucket_ofi(self, ofi: float) -> str:
        if ofi < 0.2:
            return "very_weak"
        elif ofi < 0.4:
            return "weak"
        elif ofi < 0.6:
            return "moderate"
        elif ofi < 0.8:
            return "strong"
        else:
            return "extreme"
    
    def _bucket_ensemble(self, ensemble: float) -> str:
        if ensemble < -0.1:
            return "bearish"
        elif ensemble < 0.1:
            return "neutral"
        elif ensemble < 0.3:
            return "bullish"
        else:
            return "strong_bullish"
    
    def _bucket_hour(self, hour: int) -> str:
        if 0 <= hour < 6:
            return "asia_night"
        elif 6 <= hour < 12:
            return "asia_morning"
        elif 12 <= hour < 18:
            return "us_morning"
        else:
            return "us_evening"
    
    def discover_winning_patterns(self) -> Dict[str, Any]:
        """
        CORE PROFIT-SEEKING LOGIC:
        Find patterns that PREDICT profitable outcomes.
        
        Instead of "avoid X because it loses", find "seek Y because it WINS".
        """
        matrix = self.build_feature_matrix()
        features = matrix.get("feature_matrix", [])
        
        if not features:
            return {"error": "No features extracted"}
        
        alpha_only = [f for f in features if f.get("bot_type") == "alpha"]
        
        pattern_stats = defaultdict(lambda: {
            "trades": 0,
            "wins": 0,
            "total_pnl": 0.0,
            "win_pnls": [],
            "examples": []
        })
        
        for f in alpha_only:
            key = f["pattern_key"]
            stats = pattern_stats[key]
            stats["trades"] += 1
            stats["total_pnl"] += f["pnl"]
            
            if f["is_winner"]:
                stats["wins"] += 1
                stats["win_pnls"].append(f["pnl"])
            
            if len(stats["examples"]) < 3:
                stats["examples"].append({
                    "symbol": f["symbol"],
                    "side": f["side"],
                    "pnl": f["pnl"],
                    "ofi": f["ofi"],
                    "ensemble": f["ensemble"]
                })
        
        winning_patterns = {}
        for key, stats in pattern_stats.items():
            if stats["trades"] >= 3:
                win_rate = (stats["wins"] / stats["trades"]) * 100
                avg_pnl = stats["total_pnl"] / stats["trades"]
                avg_win = sum(stats["win_pnls"]) / len(stats["win_pnls"]) if stats["win_pnls"] else 0
                
                edge_score = (win_rate / 100) * avg_win - ((100 - win_rate) / 100) * abs(avg_pnl - avg_win)
                
                if win_rate >= 40 or stats["total_pnl"] > 0:
                    winning_patterns[key] = {
                        "trades": stats["trades"],
                        "wins": stats["wins"],
                        "win_rate": round(win_rate, 1),
                        "total_pnl": round(stats["total_pnl"], 2),
                        "avg_pnl": round(avg_pnl, 2),
                        "avg_win": round(avg_win, 2),
                        "edge_score": round(edge_score, 3),
                        "examples": stats["examples"]
                    }
        
        sorted_patterns = dict(sorted(
            winning_patterns.items(),
            key=lambda x: x[1]["edge_score"],
            reverse=True
        ))
        
        self.winning_patterns = sorted_patterns
        
        dimension_analysis = self._analyze_dimensions(alpha_only)
        
        return {
            "total_alpha_trades": len(alpha_only),
            "patterns_found": len(sorted_patterns),
            "top_patterns": dict(list(sorted_patterns.items())[:15]),
            "dimension_analysis": dimension_analysis
        }
    
    def _analyze_dimensions(self, features: List[Dict]) -> Dict[str, Any]:
        """
        Slice data across EVERY dimension to find predictive signals.
        """
        
        by_symbol = defaultdict(lambda: {"trades": 0, "wins": 0, "pnl": 0})
        by_side = defaultdict(lambda: {"trades": 0, "wins": 0, "pnl": 0})
        by_ofi = defaultdict(lambda: {"trades": 0, "wins": 0, "pnl": 0})
        by_ensemble = defaultdict(lambda: {"trades": 0, "wins": 0, "pnl": 0})
        by_hour = defaultdict(lambda: {"trades": 0, "wins": 0, "pnl": 0})
        by_regime = defaultdict(lambda: {"trades": 0, "wins": 0, "pnl": 0})
        by_dow = defaultdict(lambda: {"trades": 0, "wins": 0, "pnl": 0})
        
        by_symbol_side = defaultdict(lambda: {"trades": 0, "wins": 0, "pnl": 0})
        by_ofi_side = defaultdict(lambda: {"trades": 0, "wins": 0, "pnl": 0})
        by_symbol_hour = defaultdict(lambda: {"trades": 0, "wins": 0, "pnl": 0})
        
        for f in features:
            symbol = f["symbol"]
            side = f["side"]
            ofi_b = f["ofi_bucket"]
            ens_b = f["ensemble_bucket"]
            hour_b = f["hour_bucket"]
            regime = f["regime"]
            dow = f["day_of_week"]
            pnl = f["pnl"]
            win = 1 if f["is_winner"] else 0
            
            by_symbol[symbol]["trades"] += 1
            by_symbol[symbol]["wins"] += win
            by_symbol[symbol]["pnl"] += pnl
            
            by_side[side]["trades"] += 1
            by_side[side]["wins"] += win
            by_side[side]["pnl"] += pnl
            
            by_ofi[ofi_b]["trades"] += 1
            by_ofi[ofi_b]["wins"] += win
            by_ofi[ofi_b]["pnl"] += pnl
            
            by_ensemble[ens_b]["trades"] += 1
            by_ensemble[ens_b]["wins"] += win
            by_ensemble[ens_b]["pnl"] += pnl
            
            by_hour[hour_b]["trades"] += 1
            by_hour[hour_b]["wins"] += win
            by_hour[hour_b]["pnl"] += pnl
            
            by_regime[regime]["trades"] += 1
            by_regime[regime]["wins"] += win
            by_regime[regime]["pnl"] += pnl
            
            by_dow[dow]["trades"] += 1
            by_dow[dow]["wins"] += win
            by_dow[dow]["pnl"] += pnl
            
            sym_side_key = f"{symbol}|{side}"
            by_symbol_side[sym_side_key]["trades"] += 1
            by_symbol_side[sym_side_key]["wins"] += win
            by_symbol_side[sym_side_key]["pnl"] += pnl
            
            ofi_side_key = f"{ofi_b}|{side}"
            by_ofi_side[ofi_side_key]["trades"] += 1
            by_ofi_side[ofi_side_key]["wins"] += win
            by_ofi_side[ofi_side_key]["pnl"] += pnl
            
            sym_hour_key = f"{symbol}|{hour_b}"
            by_symbol_hour[sym_hour_key]["trades"] += 1
            by_symbol_hour[sym_hour_key]["wins"] += win
            by_symbol_hour[sym_hour_key]["pnl"] += pnl
        
        def calc_stats(data: Dict) -> Dict:
            result = {}
            for key, stats in data.items():
                if stats["trades"] >= 2:
                    wr = (stats["wins"] / stats["trades"]) * 100
                    avg = stats["pnl"] / stats["trades"]
                    result[key] = {
                        "trades": stats["trades"],
                        "win_rate": round(wr, 1),
                        "total_pnl": round(stats["pnl"], 2),
                        "avg_pnl": round(avg, 3),
                        "profitable": stats["pnl"] > 0
                    }
            return dict(sorted(result.items(), key=lambda x: x[1]["total_pnl"], reverse=True))
        
        return {
            "by_symbol": calc_stats(by_symbol),
            "by_side": calc_stats(by_side),
            "by_ofi_bucket": calc_stats(by_ofi),
            "by_ensemble_bucket": calc_stats(by_ensemble),
            "by_hour_bucket": calc_stats(by_hour),
            "by_regime": calc_stats(by_regime),
            "by_day_of_week": calc_stats(by_dow),
            "by_symbol_side": calc_stats(by_symbol_side),
            "by_ofi_side": calc_stats(by_ofi_side),
            "by_symbol_hour": calc_stats(by_symbol_hour)
        }
    
    def build_edge_model(self) -> Dict[str, Any]:
        """
        Build a simple but effective edge model based on discovered patterns.
        
        For each potential trade, calculate EXPECTED EDGE based on:
        1. Symbol-side historical performance
        2. OFI bucket historical performance
        3. Time-of-day performance
        4. Combined pattern performance
        """
        if not self.winning_patterns:
            self.discover_winning_patterns()
        
        matrix = self.build_feature_matrix()
        features = matrix.get("feature_matrix", [])
        alpha_only = [f for f in features if f.get("bot_type") == "alpha"]
        
        symbol_side_edge = {}
        for f in alpha_only:
            key = f"{f['symbol']}|{f['side']}"
            if key not in symbol_side_edge:
                symbol_side_edge[key] = {"pnls": [], "wins": 0, "total": 0}
            symbol_side_edge[key]["pnls"].append(f["pnl"])
            symbol_side_edge[key]["total"] += 1
            if f["is_winner"]:
                symbol_side_edge[key]["wins"] += 1
        
        for key, data in symbol_side_edge.items():
            if data["total"] >= 3:
                avg_pnl = sum(data["pnls"]) / len(data["pnls"])
                win_rate = data["wins"] / data["total"]
                symbol_side_edge[key] = {
                    "avg_pnl": avg_pnl,
                    "win_rate": win_rate,
                    "edge": avg_pnl * win_rate,
                    "sample_size": data["total"]
                }
            else:
                symbol_side_edge[key] = None
        
        symbol_side_edge = {k: v for k, v in symbol_side_edge.items() if v is not None}
        
        ofi_side_edge = {}
        for f in alpha_only:
            key = f"{f['ofi_bucket']}|{f['side']}"
            if key not in ofi_side_edge:
                ofi_side_edge[key] = {"pnls": [], "wins": 0, "total": 0}
            ofi_side_edge[key]["pnls"].append(f["pnl"])
            ofi_side_edge[key]["total"] += 1
            if f["is_winner"]:
                ofi_side_edge[key]["wins"] += 1
        
        for key, data in ofi_side_edge.items():
            if data["total"] >= 5:
                avg_pnl = sum(data["pnls"]) / len(data["pnls"])
                win_rate = data["wins"] / data["total"]
                ofi_side_edge[key] = {
                    "avg_pnl": avg_pnl,
                    "win_rate": win_rate,
                    "edge": avg_pnl * win_rate,
                    "sample_size": data["total"]
                }
            else:
                ofi_side_edge[key] = None
        
        ofi_side_edge = {k: v for k, v in ofi_side_edge.items() if v is not None}
        
        self.edge_model = {
            "symbol_side": symbol_side_edge,
            "ofi_side": ofi_side_edge,
            "winning_patterns": self.winning_patterns,
            "model_version": datetime.now().isoformat(),
            "total_training_samples": len(alpha_only)
        }
        
        return self.edge_model
    
    def score_opportunity(self, symbol: str, side: str, ofi: float, 
                         ensemble: float = 0, hour: int = 12) -> Dict[str, Any]:
        """
        REAL-TIME OPPORTUNITY SCORER
        
        Instead of "should we block this?", answer "what's the expected profit?"
        
        Returns:
            expected_edge: Predicted profit (positive = good opportunity)
            confidence: How confident we are in the prediction
            recommendation: "STRONG_BUY", "BUY", "NEUTRAL", "AVOID"
            reasoning: Why we scored it this way
        """
        if not self.edge_model:
            self.build_edge_model()
        
        ofi_bucket = self._bucket_ofi(ofi)
        ensemble_bucket = self._bucket_ensemble(ensemble)
        hour_bucket = self._bucket_hour(hour)
        
        edges = []
        reasoning = []
        
        sym_side_key = f"{symbol}|{side}"
        sym_side_data = self.edge_model.get("symbol_side", {}).get(sym_side_key)
        if sym_side_data:
            edges.append(sym_side_data["edge"])
            wr = sym_side_data["win_rate"] * 100
            reasoning.append(f"{symbol} {side}: {wr:.0f}% WR, ${sym_side_data['avg_pnl']:.2f} avg")
        
        ofi_side_key = f"{ofi_bucket}|{side}"
        ofi_side_data = self.edge_model.get("ofi_side", {}).get(ofi_side_key)
        if ofi_side_data:
            edges.append(ofi_side_data["edge"])
            wr = ofi_side_data["win_rate"] * 100
            reasoning.append(f"{ofi_bucket} OFI + {side}: {wr:.0f}% WR, ${ofi_side_data['avg_pnl']:.2f} avg")
        
        pattern_key = f"{symbol}|{side}|{ofi_bucket}|{ensemble_bucket}|{hour_bucket}"
        pattern_data = self.edge_model.get("winning_patterns", {}).get(pattern_key)
        if pattern_data:
            edges.append(pattern_data["edge_score"])
            reasoning.append(f"Exact pattern match: {pattern_data['win_rate']}% WR, ${pattern_data['avg_pnl']:.2f} avg")
        
        if edges:
            expected_edge = sum(edges) / len(edges)
            confidence = min(1.0, len(edges) / 3)
        else:
            expected_edge = 0
            confidence = 0.1
            reasoning.append("No historical data for this pattern - neutral score")
        
        if expected_edge > 0.5 and confidence >= 0.5:
            recommendation = "STRONG_BUY"
        elif expected_edge > 0.1:
            recommendation = "BUY"
        elif expected_edge > -0.1:
            recommendation = "NEUTRAL"
        else:
            recommendation = "AVOID"
        
        return {
            "expected_edge": round(expected_edge, 4),
            "confidence": round(confidence, 2),
            "recommendation": recommendation,
            "reasoning": reasoning,
            "pattern_key": pattern_key,
            "should_trade": expected_edge > 0 or recommendation in ["STRONG_BUY", "BUY"]
        }
    
    def generate_profit_rules(self) -> Dict[str, Any]:
        """
        Generate actionable rules for the trading bot.
        
        Output format compatible with existing system.
        """
        if not self.winning_patterns:
            self.discover_winning_patterns()
        
        rules = {
            "seek_patterns": [],
            "profitable_symbol_sides": [],
            "optimal_conditions": {},
            "model_metadata": {
                "generated_at": datetime.now().isoformat(),
                "total_patterns": len(self.winning_patterns)
            }
        }
        
        for pattern_key, stats in self.winning_patterns.items():
            if stats["edge_score"] > 0 and stats["trades"] >= 3:
                parts = pattern_key.split("|")
                if len(parts) >= 3:
                    rules["seek_patterns"].append({
                        "symbol": parts[0],
                        "side": parts[1],
                        "ofi_bucket": parts[2],
                        "ensemble_bucket": parts[3] if len(parts) > 3 else "any",
                        "hour_bucket": parts[4] if len(parts) > 4 else "any",
                        "win_rate": stats["win_rate"],
                        "avg_pnl": stats["avg_pnl"],
                        "edge_score": stats["edge_score"],
                        "sample_size": stats["trades"]
                    })
        
        matrix = self.build_feature_matrix()
        features = matrix.get("feature_matrix", [])
        alpha_only = [f for f in features if f.get("bot_type") == "alpha"]
        
        sym_side_stats = defaultdict(lambda: {"pnl": 0, "trades": 0, "wins": 0})
        for f in alpha_only:
            key = f"{f['symbol']}|{f['side']}"
            sym_side_stats[key]["pnl"] += f["pnl"]
            sym_side_stats[key]["trades"] += 1
            if f["is_winner"]:
                sym_side_stats[key]["wins"] += 1
        
        for key, stats in sym_side_stats.items():
            if stats["pnl"] > 0 and stats["trades"] >= 3:
                parts = key.split("|")
                rules["profitable_symbol_sides"].append({
                    "symbol": parts[0],
                    "side": parts[1],
                    "total_pnl": round(stats["pnl"], 2),
                    "trades": stats["trades"],
                    "win_rate": round((stats["wins"] / stats["trades"]) * 100, 1)
                })
        
        rules["profitable_symbol_sides"].sort(key=lambda x: x["total_pnl"], reverse=True)
        
        return rules
    
    def save_model(self):
        """Save the edge model and rules to feature store."""
        os.makedirs(FEATURE_STORE, exist_ok=True)
        os.makedirs(REPORTS_DIR, exist_ok=True)
        
        if not self.edge_model:
            self.build_edge_model()
        
        model_path = os.path.join(FEATURE_STORE, "profit_seeker_model.json")
        with open(model_path, 'w') as f:
            json.dump(self.edge_model, f, indent=2, default=str)
        
        rules = self.generate_profit_rules()
        rules_path = os.path.join(FEATURE_STORE, "profit_seeking_rules.json")
        with open(rules_path, 'w') as f:
            json.dump(rules, f, indent=2)
        
        report = self._generate_report()
        report_path = os.path.join(REPORTS_DIR, "PROFIT_SEEKER_ANALYSIS.md")
        with open(report_path, 'w') as f:
            f.write(report)
        
        return {
            "model_path": model_path,
            "rules_path": rules_path,
            "report_path": report_path
        }
    
    def _generate_report(self) -> str:
        """Generate human-readable profit-seeking analysis report."""
        discovery = self.discover_winning_patterns()
        rules = self.generate_profit_rules()
        
        report = f"""# PROFIT-SEEKER ANALYSIS REPORT
Generated: {datetime.now().isoformat()}

## EXECUTIVE SUMMARY
Total Alpha Trades Analyzed: {discovery['total_alpha_trades']}
Profitable Patterns Found: {discovery['patterns_found']}

## PHILOSOPHY SHIFT
Instead of "what to avoid", this report shows "what to SEEK".
These patterns have POSITIVE expected value based on historical data.

## TOP PROFITABLE PATTERNS (Seek These!)

"""
        
        for i, (pattern_key, stats) in enumerate(list(discovery['top_patterns'].items())[:10], 1):
            parts = pattern_key.split("|")
            report += f"""### Pattern #{i}: {pattern_key}
- Symbol: {parts[0]}
- Direction: {parts[1]}
- OFI Bucket: {parts[2]}
- Win Rate: {stats['win_rate']}%
- Average P&L: ${stats['avg_pnl']:.2f}
- Total P&L: ${stats['total_pnl']:.2f}
- Edge Score: {stats['edge_score']:.3f}
- Sample Size: {stats['trades']} trades

"""
        
        dim = discovery['dimension_analysis']
        
        report += """## DIMENSION ANALYSIS

### Best Performing Symbol-Side Combinations
"""
        sym_side = dim.get('by_symbol_side', {})
        profitable_ss = [(k, v) for k, v in sym_side.items() if v.get('profitable')]
        for key, stats in profitable_ss[:10]:
            report += f"- {key}: {stats['win_rate']}% WR, ${stats['total_pnl']:.2f} total, {stats['trades']} trades\n"
        
        report += """
### Best Performing OFI-Side Combinations
"""
        ofi_side = dim.get('by_ofi_side', {})
        profitable_os = [(k, v) for k, v in ofi_side.items() if v.get('profitable')]
        for key, stats in profitable_os[:10]:
            report += f"- {key}: {stats['win_rate']}% WR, ${stats['total_pnl']:.2f} total, {stats['trades']} trades\n"
        
        report += """
### Best Trading Hours
"""
        hours = dim.get('by_hour_bucket', {})
        for key, stats in hours.items():
            marker = "***" if stats.get('profitable') else ""
            report += f"- {key}: {stats['win_rate']}% WR, ${stats['total_pnl']:.2f} total {marker}\n"
        
        report += """
## ACTIONABLE RULES

### Profitable Symbol-Side Combinations (SEEK THESE):
"""
        for rule in rules.get('profitable_symbol_sides', [])[:10]:
            report += f"- {rule['symbol']} {rule['side']}: ${rule['total_pnl']:.2f} profit, {rule['win_rate']}% WR\n"
        
        report += """
## IMPLEMENTATION

The profit_seeker module provides:
1. `score_opportunity(symbol, side, ofi, ensemble, hour)` - Returns expected edge
2. Edge model automatically loaded and used for real-time scoring
3. Rules saved to feature_store/profit_seeking_rules.json

Use `from src.profit_seeker import ProfitSeeker` to integrate.
"""
        
        return report


def run_full_analysis():
    """Run complete profit-seeking analysis and save results."""
    print("=" * 60)
    print("PROFIT-SEEKER INTELLIGENCE ENGINE")
    print("Finding patterns that PREDICT profits")
    print("=" * 60)
    
    seeker = ProfitSeeker()
    
    print("\n[1/4] Loading trade history...")
    trades = seeker.load_all_trades()
    print(f"     Loaded {len(trades)} closed trades")
    
    print("\n[2/4] Building feature matrix...")
    matrix = seeker.build_feature_matrix()
    print(f"     Extracted features from {matrix['features_extracted']} trades")
    
    print("\n[3/4] Discovering winning patterns...")
    discovery = seeker.discover_winning_patterns()
    print(f"     Found {discovery['patterns_found']} patterns with positive edge")
    
    print("\n[4/4] Building edge model and saving...")
    seeker.build_edge_model()
    paths = seeker.save_model()
    print(f"     Model saved to: {paths['model_path']}")
    print(f"     Rules saved to: {paths['rules_path']}")
    print(f"     Report saved to: {paths['report_path']}")
    
    print("\n" + "=" * 60)
    print("TOP 5 PROFITABLE PATTERNS (SEEK THESE!):")
    print("=" * 60)
    
    for i, (key, stats) in enumerate(list(discovery['top_patterns'].items())[:5], 1):
        print(f"\n#{i} {key}")
        print(f"    Win Rate: {stats['win_rate']}% | Avg P&L: ${stats['avg_pnl']:.2f}")
        print(f"    Edge Score: {stats['edge_score']:.3f} | Trades: {stats['trades']}")
    
    dim = discovery['dimension_analysis']
    print("\n" + "=" * 60)
    print("PROFITABLE DIMENSIONS:")
    print("=" * 60)
    
    print("\nBy Symbol-Side:")
    sym_side = dim.get('by_symbol_side', {})
    profitable_ss = [(k, v) for k, v in sym_side.items() if v.get('profitable')][:5]
    for key, stats in profitable_ss:
        print(f"  {key}: ${stats['total_pnl']:.2f} ({stats['win_rate']}% WR)")
    
    print("\nBy OFI-Side:")
    ofi_side = dim.get('by_ofi_side', {})
    profitable_os = [(k, v) for k, v in ofi_side.items() if v.get('profitable')][:5]
    for key, stats in profitable_os:
        print(f"  {key}: ${stats['total_pnl']:.2f} ({stats['win_rate']}% WR)")
    
    return seeker


if __name__ == "__main__":
    run_full_analysis()
