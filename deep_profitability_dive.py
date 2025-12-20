#!/usr/bin/env python3
"""
Deep Profitability Dive Analysis
=================================
Comprehensive analysis to identify root causes of unprofitability:
- Win rate analysis by multiple dimensions
- P&L distribution analysis
- Entry/exit timing issues
- Fee impact analysis
- Signal quality analysis
- Learning system effectiveness
- Actionable recommendations
"""

import json
import os
import sys
from datetime import datetime, timedelta
from collections import defaultdict
from typing import Dict, List, Any, Tuple
from pathlib import Path
import statistics

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

try:
    from src.data_registry import DataRegistry as DR
except (ImportError, SyntaxError) as e:
    print(f"Warning: Could not import DataRegistry ({e}), using fallback paths")
    DR = None

class DeepProfitabilityDive:
    """Comprehensive profitability root cause analysis"""
    
    def __init__(self):
        self.trades = []
        self.signals = []
        self.blocked_signals = []
        self.analysis_results = {
            "timestamp": datetime.now().isoformat(),
            "overall_metrics": {},
            "win_rate_analysis": {},
            "pnl_distribution": {},
            "entry_analysis": {},
            "exit_analysis": {},
            "fee_impact": {},
            "signal_quality": {},
            "learning_effectiveness": {},
            "losing_patterns": {},
            "recommendations": []
        }
    
    def load_all_data(self):
        """Load all trade and signal data"""
        print("=" * 80)
        print("LOADING DATA")
        print("=" * 80)
        
        # Load closed trades - try multiple sources
        # 1. Try SQLite database first (if DataRegistry works)
        if DR:
            try:
                closed_positions = DR.get_closed_trades_from_db()
                if closed_positions:
                    self.trades = closed_positions
                    print(f"[OK] Loaded {len(self.trades)} closed trades from SQLite database")
            except Exception as e:
                print(f"[WARNING] Could not load from SQLite: {e}")
        
        # 2. Try canonical positions file
        if not self.trades:
            canonical_path = "logs/positions_futures.json"
            if os.path.exists(canonical_path):
                try:
                    with open(canonical_path, 'r') as f:
                        data = json.load(f)
                        # Extract closed positions
                        if isinstance(data, dict):
                            closed_positions = data.get("closed_positions", [])
                            if closed_positions:
                                self.trades = closed_positions
                                print(f"[OK] Loaded {len(self.trades)} closed trades from {canonical_path}")
                        elif isinstance(data, list):
                            self.trades = data
                            print(f"[OK] Loaded {len(self.trades)} trades from {canonical_path}")
                except Exception as e:
                    print(f"[WARNING] Error loading {canonical_path}: {e}")
        
        # 3. Fallback: try common paths
            for path in [
                "state/trades_futures.json",
                "logs/executed_trades.jsonl",
                "logs/closed_trades.jsonl"
            ]:
                if os.path.exists(path):
                    if path.endswith('.json'):
                        with open(path, 'r') as f:
                            data = json.load(f)
                            if isinstance(data, dict) and 'trades' in data:
                                self.trades = data['trades']
                            elif isinstance(data, list):
                                self.trades = data
                    else:
                        with open(path, 'r') as f:
                            for line in f:
                                if line.strip():
                                    self.trades.append(json.loads(line))
                    print(f"✅ Loaded {len(self.trades)} trades from {path}")
                    break
        
        # Load signals
        signals_paths = [
            "logs/predictive_signals.jsonl",
            "logs/signal_outcomes.jsonl",
            "logs/signals_universe.jsonl"
        ]
        for path in signals_paths:
            if os.path.exists(path):
                with open(path, 'r') as f:
                    for line in f:
                        if line.strip():
                            self.signals.append(json.loads(line))
                print(f"[OK] Loaded {len(self.signals)} signals from {path}")
                break
        
        # Load blocked signals
        blocked_paths = [
            "logs/blocked_signals.jsonl",
            "logs/beta/blocked_signals.jsonl"
        ]
        for path in blocked_paths:
            if os.path.exists(path):
                with open(path, 'r') as f:
                    for line in f:
                        if line.strip():
                            self.blocked_signals.append(json.loads(line))
                print(f"[OK] Loaded {len(self.blocked_signals)} blocked signals from {path}")
                break
        
        print(f"\nTotal data loaded:")
        print(f"   - Trades: {len(self.trades)}")
        print(f"   - Signals: {len(self.signals)}")
        print(f"   - Blocked signals: {len(self.blocked_signals)}")
        
        # If no data found, provide helpful message
        if len(self.trades) == 0 and len(self.signals) == 0:
            print("\n[INFO] No data found locally. Data is likely on the server.")
            print("[INFO] This script should be run on the server where the bot is running.")
            print("[INFO] Server: 159.65.168.230 (dashboard at http://159.65.168.230:8050)")
            print("[INFO] Expected data locations on server:")
            print("   - logs/positions_futures.json (canonical trade data)")
            print("   - data/trading_system.db (SQLite database)")
            print("   - logs/signals.jsonl (all signals)")
            print("   - logs/enriched_decisions.jsonl (enriched decisions)")
            print("\n[INFO] To run on server:")
            print("   ssh to server, cd to trading-bot directory, run: python deep_profitability_dive.py")
    
    def analyze_overall_metrics(self):
        """Calculate overall profitability metrics"""
        print("\n" + "=" * 80)
        print("OVERALL METRICS")
        print("=" * 80)
        
        if not self.trades:
            print("[WARNING] No trades to analyze")
            return
        
        total_pnl = 0.0
        winners = []
        losers = []
        total_fees = 0.0
        
        for trade in self.trades:
            pnl = self._get_pnl(trade)
            fees = self._get_fees(trade)
            total_pnl += pnl
            total_fees += fees
            
            if pnl > 0:
                winners.append(pnl)
            elif pnl < 0:
                losers.append(abs(pnl))
        
        win_rate = (len(winners) / len(self.trades) * 100) if self.trades else 0
        avg_win = statistics.mean(winners) if winners else 0
        avg_loss = statistics.mean(losers) if losers else 0
        rr_ratio = avg_win / avg_loss if avg_loss > 0 else 0
        
        # Daily P&L analysis
        daily_pnl = defaultdict(float)
        for trade in self.trades:
            ts = self._get_timestamp(trade)
            if ts:
                date = datetime.fromtimestamp(ts).date()
                daily_pnl[str(date)] += self._get_pnl(trade)
        
        winning_days = sum(1 for pnl in daily_pnl.values() if pnl > 0)
        losing_days = sum(1 for pnl in daily_pnl.values() if pnl < 0)
        total_days = len(daily_pnl)
        
        self.analysis_results["overall_metrics"] = {
            "total_trades": len(self.trades),
            "total_pnl": round(total_pnl, 2),
            "total_fees": round(total_fees, 2),
            "net_pnl_after_fees": round(total_pnl - total_fees, 2),
            "win_rate": round(win_rate, 2),
            "wins": len(winners),
            "losses": len(losers),
            "avg_win": round(avg_win, 2),
            "avg_loss": round(avg_loss, 2),
            "risk_reward_ratio": round(rr_ratio, 2),
            "expectancy": round((win_rate/100 * avg_win) - ((100-win_rate)/100 * avg_loss), 2),
            "total_days": total_days,
            "winning_days": winning_days,
            "losing_days": losing_days,
            "daily_win_rate": round(winning_days / total_days * 100, 2) if total_days > 0 else 0,
            "avg_daily_pnl": round(sum(daily_pnl.values()) / total_days, 2) if total_days > 0 else 0
        }
        
        print(f"Overall Performance:")
        print(f"   Total Trades: {len(self.trades)}")
        print(f"   Total P&L: ${total_pnl:.2f}")
        print(f"   Total Fees: ${total_fees:.2f}")
        print(f"   Net P&L (after fees): ${total_pnl - total_fees:.2f}")
        print(f"   Win Rate: {win_rate:.2f}% ({len(winners)} wins, {len(losers)} losses)")
        print(f"   Avg Win: ${avg_win:.2f} | Avg Loss: ${avg_loss:.2f}")
        print(f"   Risk/Reward: {rr_ratio:.2f}")
        print(f"   Expectancy: ${self.analysis_results['overall_metrics']['expectancy']:.2f}")
        print(f"\nDaily Performance:")
        print(f"   Total Days: {total_days}")
        print(f"   Winning Days: {winning_days} ({winning_days/total_days*100:.1f}%)")
        print(f"   Losing Days: {losing_days} ({losing_days/total_days*100:.1f}%)")
        print(f"   Avg Daily P&L: ${self.analysis_results['overall_metrics']['avg_daily_pnl']:.2f}")
    
    def analyze_win_rate_by_dimension(self):
        """Analyze win rate by symbol, direction, strategy, etc."""
        print("\n" + "=" * 80)
        print("WIN RATE ANALYSIS BY DIMENSION")
        print("=" * 80)
        
        by_symbol = defaultdict(lambda: {"wins": 0, "losses": 0, "pnl": 0.0, "trades": []})
        by_direction = defaultdict(lambda: {"wins": 0, "losses": 0, "pnl": 0.0, "trades": []})
        by_strategy = defaultdict(lambda: {"wins": 0, "losses": 0, "pnl": 0.0, "trades": []})
        by_conviction = defaultdict(lambda: {"wins": 0, "losses": 0, "pnl": 0.0, "trades": []})
        by_ofi_bucket = defaultdict(lambda: {"wins": 0, "losses": 0, "pnl": 0.0, "trades": []})
        by_hour = defaultdict(lambda: {"wins": 0, "losses": 0, "pnl": 0.0, "trades": []})
        by_day_of_week = defaultdict(lambda: {"wins": 0, "losses": 0, "pnl": 0.0, "trades": []})
        
        for trade in self.trades:
            pnl = self._get_pnl(trade)
            is_win = pnl > 0
            
            symbol = trade.get("symbol", "UNKNOWN")
            direction = trade.get("direction", trade.get("side", "UNKNOWN"))
            strategy = trade.get("strategy", "unknown")
            conviction = trade.get("conviction", trade.get("signal_context", {}).get("conviction", "unknown"))
            
            # OFI bucket
            signal_ctx = trade.get("signal_context", {})
            ofi = abs(signal_ctx.get("ofi", signal_ctx.get("ofi_raw", 0)) or 0)
            if ofi >= 0.9:
                ofi_bucket = "extreme"
            elif ofi >= 0.7:
                ofi_bucket = "very_strong"
            elif ofi >= 0.5:
                ofi_bucket = "strong"
            elif ofi >= 0.3:
                ofi_bucket = "moderate"
            else:
                ofi_bucket = "weak"
            
            # Time analysis
            ts = self._get_timestamp(trade)
            if ts:
                dt = datetime.fromtimestamp(ts)
                hour = dt.hour
                dow = dt.strftime("%A")
            else:
                hour = "unknown"
                dow = "unknown"
            
            for bucket_dict, key in [
                (by_symbol, symbol),
                (by_direction, direction),
                (by_strategy, strategy),
                (by_conviction, conviction),
                (by_ofi_bucket, ofi_bucket),
                (by_hour, hour),
                (by_day_of_week, dow)
            ]:
                if is_win:
                    bucket_dict[key]["wins"] += 1
                else:
                    bucket_dict[key]["losses"] += 1
                bucket_dict[key]["pnl"] += pnl
                bucket_dict[key]["trades"].append(trade)
        
        def calc_metrics(d: Dict) -> Dict:
            result = {}
            for key, val in d.items():
                total = val["wins"] + val["losses"]
                if total > 0:
                    result[key] = {
                        "trades": total,
                        "wins": val["wins"],
                        "losses": val["losses"],
                        "win_rate": round(val["wins"] / total * 100, 2),
                        "total_pnl": round(val["pnl"], 2),
                        "avg_pnl": round(val["pnl"] / total, 2)
                    }
            return result
        
        self.analysis_results["win_rate_analysis"] = {
            "by_symbol": calc_metrics(by_symbol),
            "by_direction": calc_metrics(by_direction),
            "by_strategy": calc_metrics(by_strategy),
            "by_conviction": calc_metrics(by_conviction),
            "by_ofi_bucket": calc_metrics(by_ofi_bucket),
            "by_hour": calc_metrics(by_hour),
            "by_day_of_week": calc_metrics(by_day_of_week)
        }
        
        # Print top findings
        print("\nBY SYMBOL (sorted by P&L):")
        symbol_data = sorted(
            self.analysis_results["win_rate_analysis"]["by_symbol"].items(),
            key=lambda x: x[1]["total_pnl"],
            reverse=True
        )
        for symbol, data in symbol_data[:10]:
            print(f"   {symbol}: WR={data['win_rate']:.1f}%, P&L=${data['total_pnl']:.2f}, n={data['trades']}")
        
        print("\nBY DIRECTION:")
        for direction, data in self.analysis_results["win_rate_analysis"]["by_direction"].items():
            print(f"   {direction}: WR={data['win_rate']:.1f}%, P&L=${data['total_pnl']:.2f}, n={data['trades']}")
        
        print("\nBY STRATEGY:")
        strategy_data = sorted(
            self.analysis_results["win_rate_analysis"]["by_strategy"].items(),
            key=lambda x: x[1]["total_pnl"],
            reverse=True
        )
        for strategy, data in strategy_data:
            print(f"   {strategy}: WR={data['win_rate']:.1f}%, P&L=${data['total_pnl']:.2f}, n={data['trades']}")
        
        print("\nBY OFI BUCKET:")
        for bucket, data in self.analysis_results["win_rate_analysis"]["by_ofi_bucket"].items():
            print(f"   {bucket}: WR={data['win_rate']:.1f}%, P&L=${data['total_pnl']:.2f}, n={data['trades']}")
    
    def analyze_losing_patterns(self):
        """Identify specific losing patterns"""
        print("\n" + "=" * 80)
        print("LOSING PATTERNS IDENTIFICATION")
        print("=" * 80)
        
        losing_patterns = defaultdict(lambda: {"trades": [], "total_pnl": 0.0, "count": 0})
        
        for trade in self.trades:
            pnl = self._get_pnl(trade)
            if pnl < 0:  # Only analyze losing trades
                symbol = trade.get("symbol", "UNKNOWN")
                direction = trade.get("direction", trade.get("side", "UNKNOWN"))
                strategy = trade.get("strategy", "unknown")
                conviction = trade.get("conviction", "unknown")
                
                signal_ctx = trade.get("signal_context", {})
                ofi = abs(signal_ctx.get("ofi", 0) or 0)
                if ofi >= 0.5:
                    ofi_level = "strong"
                elif ofi >= 0.3:
                    ofi_level = "moderate"
                else:
                    ofi_level = "weak"
                
                # Create pattern keys
                pattern_key = f"{symbol}|{direction}|{ofi_level}"
                losing_patterns[pattern_key]["trades"].append(trade)
                losing_patterns[pattern_key]["total_pnl"] += pnl
                losing_patterns[pattern_key]["count"] += 1
        
        # Sort by total loss
        sorted_patterns = sorted(
            losing_patterns.items(),
            key=lambda x: x[1]["total_pnl"]
        )
        
        self.analysis_results["losing_patterns"] = {}
        print("\nTOP LOSING PATTERNS:")
        for pattern, data in sorted_patterns[:20]:
            avg_loss = data["total_pnl"] / data["count"]
            self.analysis_results["losing_patterns"][pattern] = {
                "count": data["count"],
                "total_pnl": round(data["total_pnl"], 2),
                "avg_pnl": round(avg_loss, 2)
            }
            print(f"   {pattern}: n={data['count']}, Total Loss=${data['total_pnl']:.2f}, Avg=${avg_loss:.2f}")
    
    def analyze_entry_timing(self):
        """Analyze entry timing issues"""
        print("\n" + "=" * 80)
        print("ENTRY TIMING ANALYSIS")
        print("=" * 80)
        
        # Analyze hold times
        hold_times = []
        hold_times_by_outcome = {"wins": [], "losses": []}
        
        for trade in self.trades:
            entry_ts = self._get_entry_timestamp(trade)
            exit_ts = self._get_exit_timestamp(trade)
            pnl = self._get_pnl(trade)
            
            if entry_ts and exit_ts:
                hold_seconds = exit_ts - entry_ts
                hold_minutes = hold_seconds / 60
                hold_times.append(hold_minutes)
                
                if pnl > 0:
                    hold_times_by_outcome["wins"].append(hold_minutes)
                else:
                    hold_times_by_outcome["losses"].append(hold_minutes)
        
        if hold_times:
            self.analysis_results["entry_analysis"] = {
                "avg_hold_time_minutes": round(statistics.mean(hold_times), 2),
                "median_hold_time_minutes": round(statistics.median(hold_times), 2),
                "avg_hold_winning": round(statistics.mean(hold_times_by_outcome["wins"]), 2) if hold_times_by_outcome["wins"] else 0,
                "avg_hold_losing": round(statistics.mean(hold_times_by_outcome["losses"]), 2) if hold_times_by_outcome["losses"] else 0
            }
            
            print(f"Hold Time Analysis:")
            print(f"   Avg Hold Time: {self.analysis_results['entry_analysis']['avg_hold_time_minutes']:.2f} minutes")
            print(f"   Median Hold Time: {self.analysis_results['entry_analysis']['median_hold_time_minutes']:.2f} minutes")
            print(f"   Avg Hold (Winners): {self.analysis_results['entry_analysis']['avg_hold_winning']:.2f} minutes")
            print(f"   Avg Hold (Losers): {self.analysis_results['entry_analysis']['avg_hold_losing']:.2f} minutes")
    
    def analyze_exit_timing(self):
        """Analyze exit timing and reasons"""
        print("\n" + "=" * 80)
        print("EXIT TIMING ANALYSIS")
        print("=" * 80)
        
        exit_reasons = defaultdict(lambda: {"wins": 0, "losses": 0, "pnl": 0.0, "count": 0})
        
        for trade in self.trades:
            exit_reason = trade.get("exit_reason", trade.get("exit_style", "unknown"))
            pnl = self._get_pnl(trade)
            
            exit_reasons[exit_reason]["count"] += 1
            exit_reasons[exit_reason]["pnl"] += pnl
            if pnl > 0:
                exit_reasons[exit_reason]["wins"] += 1
            else:
                exit_reasons[exit_reason]["losses"] += 1
        
        self.analysis_results["exit_analysis"] = {}
        print("\nEXIT REASONS:")
        for reason, data in sorted(exit_reasons.items(), key=lambda x: x[1]["pnl"]):
            wr = (data["wins"] / data["count"] * 100) if data["count"] > 0 else 0
            self.analysis_results["exit_analysis"][reason] = {
                "count": data["count"],
                "win_rate": round(wr, 2),
                "total_pnl": round(data["pnl"], 2)
            }
            print(f"   {reason}: n={data['count']}, WR={wr:.1f}%, P&L=${data['pnl']:.2f}")
    
    def analyze_fee_impact(self):
        """Analyze fee impact on profitability"""
        print("\n" + "=" * 80)
        print("FEE IMPACT ANALYSIS")
        print("=" * 80)
        
        total_gross_pnl = 0.0
        total_fees = 0.0
        trades_where_fees_exceed_profit = 0
        
        for trade in self.trades:
            pnl = self._get_pnl(trade)
            fees = self._get_fees(trade)
            gross_pnl = pnl + fees  # Gross before fees
            
            total_gross_pnl += gross_pnl
            total_fees += fees
            
            if pnl < 0 and fees > abs(pnl):
                trades_where_fees_exceed_profit += 1
        
        fee_pct_of_gross = (total_fees / total_gross_pnl * 100) if total_gross_pnl > 0 else 0
        
        self.analysis_results["fee_impact"] = {
            "total_gross_pnl": round(total_gross_pnl, 2),
            "total_fees": round(total_fees, 2),
            "net_pnl": round(total_gross_pnl - total_fees, 2),
            "fee_pct_of_gross": round(fee_pct_of_gross, 2),
            "trades_where_fees_exceed_profit": trades_where_fees_exceed_profit,
            "fee_erosion_pct": round((total_fees / abs(total_gross_pnl) * 100) if total_gross_pnl < 0 else 0, 2)
        }
        
        print(f"Fee Impact:")
        print(f"   Gross P&L (before fees): ${total_gross_pnl:.2f}")
        print(f"   Total Fees: ${total_fees:.2f}")
        print(f"   Net P&L (after fees): ${total_gross_pnl - total_fees:.2f}")
        print(f"   Fees as % of Gross: {fee_pct_of_gross:.2f}%")
        print(f"   Trades where fees > profit: {trades_where_fees_exceed_profit}")
    
    def generate_recommendations(self):
        """Generate actionable recommendations"""
        print("\n" + "=" * 80)
        print("ACTIONABLE RECOMMENDATIONS")
        print("=" * 80)
        
        recommendations = []
        
        # Overall metrics
        overall = self.analysis_results.get("overall_metrics", {})
        if overall.get("win_rate", 0) < 50:
            recommendations.append({
                "priority": "HIGH",
                "category": "Win Rate",
                "issue": f"Win rate is {overall.get('win_rate', 0):.1f}% (below 50%)",
                "recommendation": "Focus on improving signal quality and entry timing. Consider tightening entry filters to only trade highest-conviction signals.",
                "action": "Increase minimum conviction threshold, require more signal alignment"
            })
        
        if overall.get("total_pnl", 0) < 0:
            recommendations.append({
                "priority": "CRITICAL",
                "category": "Overall Profitability",
                "issue": f"Total P&L is negative: ${overall.get('total_pnl', 0):.2f}",
                "recommendation": "Immediate action required. Consider pausing trading until root causes identified.",
                "action": "Run pattern analysis to identify and block losing patterns"
            })
        
        # Direction analysis
        direction_data = self.analysis_results.get("win_rate_analysis", {}).get("by_direction", {})
        for direction, data in direction_data.items():
            if data.get("win_rate", 0) < 40 and data.get("total_pnl", 0) < 0:
                recommendations.append({
                    "priority": "HIGH",
                    "category": "Direction Filter",
                    "issue": f"{direction} trades: WR={data['win_rate']:.1f}%, P&L=${data['total_pnl']:.2f}",
                    "recommendation": f"Consider blocking or reducing {direction} trades until pattern improves",
                    "action": f"Add filter to block {direction} trades or reduce sizing"
                })
        
        # Symbol analysis
        symbol_data = self.analysis_results.get("win_rate_analysis", {}).get("by_symbol", {})
        worst_symbols = sorted(
            [(s, d) for s, d in symbol_data.items() if d.get("total_pnl", 0) < 0 and d.get("win_rate", 0) < 40],
            key=lambda x: x[1]["total_pnl"]
        )[:5]
        
        for symbol, data in worst_symbols:
            recommendations.append({
                "priority": "MEDIUM",
                "category": "Symbol Filter",
                "issue": f"{symbol}: WR={data['win_rate']:.1f}%, P&L=${data['total_pnl']:.2f}",
                "recommendation": f"Consider reducing allocation or blocking {symbol} until performance improves",
                "action": f"Reduce {symbol} allocation or add to block list"
            })
        
        # OFI analysis
        ofi_data = self.analysis_results.get("win_rate_analysis", {}).get("by_ofi_bucket", {})
        for bucket, data in ofi_data.items():
            if data.get("win_rate", 0) < 40 and data.get("total_pnl", 0) < 0:
                recommendations.append({
                    "priority": "HIGH",
                    "category": "OFI Filter",
                    "issue": f"OFI {bucket}: WR={data['win_rate']:.1f}%, P&L=${data['total_pnl']:.2f}",
                    "recommendation": f"Consider blocking or reducing trades with {bucket} OFI",
                    "action": f"Add filter to block {bucket} OFI trades"
                })
        
        # Fee impact
        fee_data = self.analysis_results.get("fee_impact", {})
        if fee_data.get("fee_pct_of_gross", 0) > 30:
            recommendations.append({
                "priority": "MEDIUM",
                "category": "Fee Management",
                "issue": f"Fees are {fee_data.get('fee_pct_of_gross', 0):.1f}% of gross P&L",
                "recommendation": "Fees are eroding significant profit. Consider: 1) Increase minimum expected edge, 2) Reduce trade frequency, 3) Use maker orders where possible",
                "action": "Increase fee gate threshold, reduce trade frequency"
            })
        
        # Losing patterns
        losing_patterns = self.analysis_results.get("losing_patterns", {})
        if losing_patterns:
            top_loser = max(losing_patterns.items(), key=lambda x: abs(x[1]["total_pnl"]))
            recommendations.append({
                "priority": "HIGH",
                "category": "Pattern Blocking",
                "issue": f"Top losing pattern: {top_loser[0]} (${top_loser[1]['total_pnl']:.2f} loss)",
                "recommendation": f"Immediately block pattern: {top_loser[0]}",
                "action": f"Add filter to block {top_loser[0]} pattern"
            })
        
        self.analysis_results["recommendations"] = recommendations
        
        print("\nPRIORITIZED RECOMMENDATIONS:")
        for i, rec in enumerate(sorted(recommendations, key=lambda x: {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2}.get(x["priority"], 3)), 1):
            print(f"\n{i}. [{rec['priority']}] {rec['category']}")
            print(f"   Issue: {rec['issue']}")
            print(f"   Recommendation: {rec['recommendation']}")
            print(f"   Action: {rec['action']}")
    
    def save_results(self):
        """Save analysis results to file"""
        output_path = f"reports/deep_profitability_dive_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        
        with open(output_path, 'w') as f:
            json.dump(self.analysis_results, f, indent=2, default=str)
        
        print(f"\n[SAVED] Analysis saved to: {output_path}")
        return output_path
    
    # Helper methods
    def _get_pnl(self, trade: Dict) -> float:
        """Extract P&L from trade"""
        for key in ["realized_pnl", "net_pnl", "pnl_usd", "pnl", "profit", "net_profit"]:
            if key in trade:
                val = trade[key]
                if isinstance(val, (int, float)):
                    return float(val)
        return 0.0
    
    def _get_fees(self, trade: Dict) -> float:
        """Extract fees from trade"""
        for key in ["fees", "trading_fees", "total_fees", "fee"]:
            if key in trade:
                val = trade[key]
                if isinstance(val, (int, float)):
                    return float(val)
        return 0.0
    
    def _get_timestamp(self, trade: Dict) -> float:
        """Extract timestamp from trade"""
        for key in ["timestamp", "ts", "closed_at", "exit_timestamp"]:
            if key in trade:
                val = trade[key]
                if isinstance(val, (int, float)):
                    return float(val)
                elif isinstance(val, str):
                    try:
                        return datetime.fromisoformat(val.replace('Z', '+00:00')).timestamp()
                    except:
                        pass
        return None
    
    def _get_entry_timestamp(self, trade: Dict) -> float:
        """Extract entry timestamp"""
        for key in ["entry_timestamp", "entry_ts", "opened_at"]:
            if key in trade:
                val = trade[key]
                if isinstance(val, (int, float)):
                    return float(val)
        return self._get_timestamp(trade)  # Fallback
    
    def _get_exit_timestamp(self, trade: Dict) -> float:
        """Extract exit timestamp"""
        return self._get_timestamp(trade)
    
    def run_full_analysis(self):
        """Run complete analysis"""
        print("\n" + "=" * 80)
        print("DEEP PROFITABILITY DIVE ANALYSIS")
        print("=" * 80)
        print(f"Started: {datetime.now().isoformat()}\n")
        
        self.load_all_data()
        self.analyze_overall_metrics()
        self.analyze_win_rate_by_dimension()
        self.analyze_losing_patterns()
        self.analyze_entry_timing()
        self.analyze_exit_timing()
        self.analyze_fee_impact()
        self.generate_recommendations()
        
        output_path = self.save_results()
        
        print("\n" + "=" * 80)
        print("ANALYSIS COMPLETE")
        print("=" * 80)
        print(f"Results saved to: {output_path}")
        
        return self.analysis_results


if __name__ == "__main__":
    analyzer = DeepProfitabilityDive()
    results = analyzer.run_full_analysis()
