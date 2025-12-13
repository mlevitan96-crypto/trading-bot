"""
MOMENTUM-BASED PROFIT PREDICTOR
===============================
Analyzes what happens BEFORE profitable trades to PREDICT winning opportunities.

This goes beyond the basic profit seeker by:
1. Analyzing trade DURATION patterns (quick vs slow wins)
2. Looking at STRATEGY performance
3. Examining CLOSE REASON patterns
4. Finding TIMING patterns (when do wins happen?)
5. Building FORWARD-LOOKING prediction rules

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


class MomentumPredictor:
    """
    Predict profitable opportunities based on multiple dimensions:
    - Time patterns
    - Strategy performance
    - Duration analysis
    - Close reason patterns
    - Symbol momentum
    """
    
    def __init__(self):
        self.trades = []
        self.predictions = {}
        self.best_conditions = {}
        
    def load_trades(self) -> List[Dict]:
        """Load all trades with rich context."""
        trades = []
        
        positions_file = os.path.join(DATA_DIR, "positions_futures.json")
        if os.path.exists(positions_file):
            try:
                with open(positions_file, 'r') as f:
                    data = json.load(f)
                closed = data.get("closed_positions", [])
                for pos in closed:
                    if pos.get("pnl") is not None:
                        trades.append(pos)
            except:
                pass
        
        self.trades = trades
        return trades
    
    def analyze_all_dimensions(self) -> Dict[str, Any]:
        """
        COMPREHENSIVE DIMENSION ANALYSIS
        Slice data every possible way to find profitable patterns.
        """
        if not self.trades:
            self.load_trades()
        
        alpha_trades = [t for t in self.trades if t.get("bot_type", "alpha") == "alpha"]
        
        results = {
            "total_trades": len(alpha_trades),
            "by_strategy": self._analyze_by_strategy(alpha_trades),
            "by_close_reason": self._analyze_by_close_reason(alpha_trades),
            "by_duration": self._analyze_by_duration(alpha_trades),
            "by_hour": self._analyze_by_hour(alpha_trades),
            "by_day_of_week": self._analyze_by_dow(alpha_trades),
            "by_symbol_direction": self._analyze_by_symbol_direction(alpha_trades),
            "by_leverage": self._analyze_by_leverage(alpha_trades),
            "by_size_bucket": self._analyze_by_size(alpha_trades),
            "by_roi_range": self._analyze_by_roi(alpha_trades),
            "winning_streaks": self._analyze_streaks(alpha_trades),
            "top_performers": self._find_top_performers(alpha_trades)
        }
        
        rules = self._generate_trading_rules(results)
        results["actionable_rules"] = rules
        
        return results
    
    def _analyze_by_strategy(self, trades: List[Dict]) -> Dict:
        """Which strategies actually make money?"""
        by_strat = defaultdict(lambda: {"trades": 0, "wins": 0, "pnl": 0, "durations": []})
        
        for t in trades:
            strat = t.get("strategy", "unknown")
            pnl = float(t.get("pnl", 0))
            by_strat[strat]["trades"] += 1
            by_strat[strat]["pnl"] += pnl
            if pnl > 0:
                by_strat[strat]["wins"] += 1
            
            dur = self._calc_duration(t)
            if dur:
                by_strat[strat]["durations"].append(dur)
        
        result = {}
        for strat, data in by_strat.items():
            if data["trades"] >= 3:
                avg_dur = sum(data["durations"]) / len(data["durations"]) if data["durations"] else 0
                result[strat] = {
                    "trades": data["trades"],
                    "win_rate": round((data["wins"] / data["trades"]) * 100, 1),
                    "total_pnl": round(data["pnl"], 2),
                    "avg_pnl": round(data["pnl"] / data["trades"], 3),
                    "avg_duration_min": round(avg_dur, 1),
                    "profitable": data["pnl"] > 0
                }
        
        return dict(sorted(result.items(), key=lambda x: x[1]["total_pnl"], reverse=True))
    
    def _analyze_by_close_reason(self, trades: List[Dict]) -> Dict:
        """What close reasons correlate with profits?"""
        by_reason = defaultdict(lambda: {"trades": 0, "wins": 0, "pnl": 0})
        
        for t in trades:
            reason = t.get("close_reason", "unknown")
            pnl = float(t.get("pnl", 0))
            by_reason[reason]["trades"] += 1
            by_reason[reason]["pnl"] += pnl
            if pnl > 0:
                by_reason[reason]["wins"] += 1
        
        result = {}
        for reason, data in by_reason.items():
            if data["trades"] >= 3:
                result[reason] = {
                    "trades": data["trades"],
                    "win_rate": round((data["wins"] / data["trades"]) * 100, 1),
                    "total_pnl": round(data["pnl"], 2),
                    "avg_pnl": round(data["pnl"] / data["trades"], 3),
                    "profitable": data["pnl"] > 0
                }
        
        return dict(sorted(result.items(), key=lambda x: x[1]["total_pnl"], reverse=True))
    
    def _analyze_by_duration(self, trades: List[Dict]) -> Dict:
        """Do quick trades or slow trades perform better?"""
        buckets = {
            "0-2min": (0, 2),
            "2-5min": (2, 5),
            "5-15min": (5, 15),
            "15-30min": (15, 30),
            "30-60min": (30, 60),
            "1-4hr": (60, 240),
            "4hr+": (240, 999999)
        }
        
        by_dur = defaultdict(lambda: {"trades": 0, "wins": 0, "pnl": 0})
        
        for t in trades:
            dur = self._calc_duration(t)
            if dur is None:
                continue
            
            for bucket, (low, high) in buckets.items():
                if low <= dur < high:
                    pnl = float(t.get("pnl", 0))
                    by_dur[bucket]["trades"] += 1
                    by_dur[bucket]["pnl"] += pnl
                    if pnl > 0:
                        by_dur[bucket]["wins"] += 1
                    break
        
        result = {}
        for bucket, data in by_dur.items():
            if data["trades"] >= 3:
                result[bucket] = {
                    "trades": data["trades"],
                    "win_rate": round((data["wins"] / data["trades"]) * 100, 1),
                    "total_pnl": round(data["pnl"], 2),
                    "avg_pnl": round(data["pnl"] / data["trades"], 3),
                    "profitable": data["pnl"] > 0
                }
        
        bucket_order = list(buckets.keys())
        return {k: result[k] for k in bucket_order if k in result}
    
    def _analyze_by_hour(self, trades: List[Dict]) -> Dict:
        """Which hours are most profitable?"""
        by_hour = defaultdict(lambda: {"trades": 0, "wins": 0, "pnl": 0})
        
        for t in trades:
            hour = self._get_hour(t)
            if hour is None:
                continue
            
            pnl = float(t.get("pnl", 0))
            by_hour[hour]["trades"] += 1
            by_hour[hour]["pnl"] += pnl
            if pnl > 0:
                by_hour[hour]["wins"] += 1
        
        result = {}
        for hour in range(24):
            data = by_hour[hour]
            if data["trades"] >= 3:
                result[f"{hour:02d}:00"] = {
                    "trades": data["trades"],
                    "win_rate": round((data["wins"] / data["trades"]) * 100, 1),
                    "total_pnl": round(data["pnl"], 2),
                    "avg_pnl": round(data["pnl"] / data["trades"], 3),
                    "profitable": data["pnl"] > 0
                }
        
        return result
    
    def _analyze_by_dow(self, trades: List[Dict]) -> Dict:
        """Which days of week are best?"""
        days = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
        by_dow = defaultdict(lambda: {"trades": 0, "wins": 0, "pnl": 0})
        
        for t in trades:
            dow = self._get_dow(t)
            if dow is None:
                continue
            
            pnl = float(t.get("pnl", 0))
            by_dow[dow]["trades"] += 1
            by_dow[dow]["pnl"] += pnl
            if pnl > 0:
                by_dow[dow]["wins"] += 1
        
        result = {}
        for i, day in enumerate(days):
            data = by_dow[i]
            if data["trades"] >= 3:
                result[day] = {
                    "trades": data["trades"],
                    "win_rate": round((data["wins"] / data["trades"]) * 100, 1),
                    "total_pnl": round(data["pnl"], 2),
                    "avg_pnl": round(data["pnl"] / data["trades"], 3),
                    "profitable": data["pnl"] > 0
                }
        
        return result
    
    def _analyze_by_symbol_direction(self, trades: List[Dict]) -> Dict:
        """Which symbol+direction combos work?"""
        by_sd = defaultdict(lambda: {"trades": 0, "wins": 0, "pnl": 0, "recent_pnl": 0, "recent_count": 0})
        
        sorted_trades = sorted(trades, key=lambda x: x.get("closed_at", ""))
        recent_cutoff = len(sorted_trades) - min(500, len(sorted_trades) // 4)
        
        for i, t in enumerate(sorted_trades):
            symbol = t.get("symbol", "UNKNOWN")
            direction = (t.get("direction") or t.get("side") or "unknown").upper()
            key = f"{symbol}|{direction}"
            
            pnl = float(t.get("pnl", 0))
            by_sd[key]["trades"] += 1
            by_sd[key]["pnl"] += pnl
            if pnl > 0:
                by_sd[key]["wins"] += 1
            
            if i >= recent_cutoff:
                by_sd[key]["recent_pnl"] += pnl
                by_sd[key]["recent_count"] += 1
        
        result = {}
        for key, data in by_sd.items():
            if data["trades"] >= 5:
                recent_avg = (data["recent_pnl"] / data["recent_count"]) if data["recent_count"] > 0 else 0
                overall_avg = data["pnl"] / data["trades"]
                
                trend = "improving" if recent_avg > overall_avg else "declining"
                
                result[key] = {
                    "trades": data["trades"],
                    "win_rate": round((data["wins"] / data["trades"]) * 100, 1),
                    "total_pnl": round(data["pnl"], 2),
                    "avg_pnl": round(overall_avg, 3),
                    "recent_avg_pnl": round(recent_avg, 3),
                    "trend": trend,
                    "profitable": data["pnl"] > 0
                }
        
        return dict(sorted(result.items(), key=lambda x: x[1]["total_pnl"], reverse=True))
    
    def _analyze_by_leverage(self, trades: List[Dict]) -> Dict:
        """Does leverage level affect profitability?"""
        by_lev = defaultdict(lambda: {"trades": 0, "wins": 0, "pnl": 0})
        
        for t in trades:
            lev = t.get("leverage", 1)
            pnl = float(t.get("pnl", 0))
            by_lev[lev]["trades"] += 1
            by_lev[lev]["pnl"] += pnl
            if pnl > 0:
                by_lev[lev]["wins"] += 1
        
        result = {}
        for lev, data in sorted(by_lev.items()):
            if data["trades"] >= 3:
                result[f"{lev}x"] = {
                    "trades": data["trades"],
                    "win_rate": round((data["wins"] / data["trades"]) * 100, 1),
                    "total_pnl": round(data["pnl"], 2),
                    "avg_pnl": round(data["pnl"] / data["trades"], 3),
                    "profitable": data["pnl"] > 0
                }
        
        return result
    
    def _analyze_by_size(self, trades: List[Dict]) -> Dict:
        """Do smaller or larger position sizes perform better?"""
        buckets = {
            "micro (<$100)": (0, 100),
            "small ($100-$300)": (100, 300),
            "medium ($300-$500)": (300, 500),
            "large ($500-$1000)": (500, 1000),
            "xlarge ($1000+)": (1000, 999999)
        }
        
        by_size = defaultdict(lambda: {"trades": 0, "wins": 0, "pnl": 0})
        
        for t in trades:
            margin = float(t.get("margin_collateral", 0))
            if margin <= 0:
                continue
            
            for bucket, (low, high) in buckets.items():
                if low <= margin < high:
                    pnl = float(t.get("pnl", 0))
                    by_size[bucket]["trades"] += 1
                    by_size[bucket]["pnl"] += pnl
                    if pnl > 0:
                        by_size[bucket]["wins"] += 1
                    break
        
        result = {}
        for bucket, data in by_size.items():
            if data["trades"] >= 3:
                result[bucket] = {
                    "trades": data["trades"],
                    "win_rate": round((data["wins"] / data["trades"]) * 100, 1),
                    "total_pnl": round(data["pnl"], 2),
                    "avg_pnl": round(data["pnl"] / data["trades"], 3),
                    "profitable": data["pnl"] > 0
                }
        
        return result
    
    def _analyze_by_roi(self, trades: List[Dict]) -> Dict:
        """Analyze trades by their ROI to find sweet spots."""
        winners = [t for t in trades if float(t.get("pnl", 0)) > 0]
        losers = [t for t in trades if float(t.get("pnl", 0)) < 0]
        
        def calc_roi_stats(trade_list):
            rois = []
            for t in trade_list:
                roi = float(t.get("final_roi") or t.get("net_roi") or 0)
                rois.append(roi * 100)
            
            if not rois:
                return None
            
            return {
                "count": len(rois),
                "avg_roi_pct": round(sum(rois) / len(rois), 2),
                "min_roi_pct": round(min(rois), 2),
                "max_roi_pct": round(max(rois), 2),
                "median_roi_pct": round(sorted(rois)[len(rois)//2], 2)
            }
        
        return {
            "winners": calc_roi_stats(winners),
            "losers": calc_roi_stats(losers),
            "total_win_rate": round(len(winners) / len(trades) * 100, 1) if trades else 0
        }
    
    def _analyze_streaks(self, trades: List[Dict]) -> Dict:
        """Analyze winning and losing streaks."""
        sorted_trades = sorted(trades, key=lambda x: x.get("closed_at", ""))
        
        current_streak = 0
        max_win_streak = 0
        max_lose_streak = 0
        last_was_win = None
        
        for t in sorted_trades:
            is_win = float(t.get("pnl", 0)) > 0
            
            if last_was_win is None:
                current_streak = 1
            elif is_win == last_was_win:
                current_streak += 1
            else:
                current_streak = 1
            
            if is_win:
                max_win_streak = max(max_win_streak, current_streak)
            else:
                max_lose_streak = max(max_lose_streak, current_streak)
            
            last_was_win = is_win
        
        return {
            "max_win_streak": max_win_streak,
            "max_lose_streak": max_lose_streak,
            "current_streak": current_streak,
            "current_is_winning": last_was_win
        }
    
    def _find_top_performers(self, trades: List[Dict]) -> Dict:
        """Find the absolute best performing trades to learn from."""
        sorted_by_pnl = sorted(trades, key=lambda x: float(x.get("pnl", 0)), reverse=True)
        
        top_winners = []
        for t in sorted_by_pnl[:20]:
            if float(t.get("pnl", 0)) > 0:
                top_winners.append({
                    "symbol": t.get("symbol"),
                    "direction": t.get("direction") or t.get("side"),
                    "strategy": t.get("strategy"),
                    "pnl": round(float(t.get("pnl", 0)), 2),
                    "roi_pct": round(float(t.get("final_roi") or 0) * 100, 2),
                    "duration_min": round(self._calc_duration(t) or 0, 1),
                    "close_reason": t.get("close_reason")
                })
        
        top_losers = []
        for t in sorted_by_pnl[-20:]:
            if float(t.get("pnl", 0)) < 0:
                top_losers.append({
                    "symbol": t.get("symbol"),
                    "direction": t.get("direction") or t.get("side"),
                    "strategy": t.get("strategy"),
                    "pnl": round(float(t.get("pnl", 0)), 2),
                    "roi_pct": round(float(t.get("final_roi") or 0) * 100, 2),
                    "duration_min": round(self._calc_duration(t) or 0, 1),
                    "close_reason": t.get("close_reason")
                })
        
        return {
            "top_winners": top_winners,
            "top_losers": list(reversed(top_losers))
        }
    
    def _generate_trading_rules(self, analysis: Dict) -> List[Dict]:
        """Generate actionable trading rules from the analysis."""
        rules = []
        
        profitable_sd = [(k, v) for k, v in analysis["by_symbol_direction"].items() 
                         if v.get("profitable") and v["trades"] >= 10]
        
        for key, stats in profitable_sd[:5]:
            parts = key.split("|")
            rules.append({
                "type": "SEEK",
                "condition": f"{parts[0]} {parts[1]}",
                "evidence": f"${stats['total_pnl']:.2f} profit, {stats['win_rate']}% WR, {stats['trades']} trades",
                "trend": stats.get("trend", "unknown"),
                "priority": "HIGH" if stats["total_pnl"] > 5 else "MEDIUM"
            })
        
        profitable_strat = [(k, v) for k, v in analysis["by_strategy"].items()
                           if v.get("profitable") and v["trades"] >= 10]
        
        for strat, stats in profitable_strat[:3]:
            rules.append({
                "type": "PREFER_STRATEGY",
                "condition": f"Strategy: {strat}",
                "evidence": f"${stats['total_pnl']:.2f} profit, {stats['win_rate']}% WR",
                "priority": "MEDIUM"
            })
        
        hours = analysis["by_hour"]
        profitable_hours = [h for h, v in hours.items() if v.get("profitable")]
        losing_hours = [h for h, v in hours.items() if not v.get("profitable") and v["total_pnl"] < -10]
        
        if profitable_hours:
            rules.append({
                "type": "PREFER_TIME",
                "condition": f"Trade during: {', '.join(profitable_hours[:5])}",
                "evidence": "Hours with positive P&L",
                "priority": "LOW"
            })
        
        if losing_hours:
            rules.append({
                "type": "AVOID_TIME",
                "condition": f"Avoid trading: {', '.join(losing_hours[:3])}",
                "evidence": "Hours with significant losses",
                "priority": "MEDIUM"
            })
        
        duration = analysis["by_duration"]
        profitable_dur = [(k, v) for k, v in duration.items() if v.get("profitable")]
        
        if profitable_dur:
            rules.append({
                "type": "HOLD_DURATION",
                "condition": f"Target hold time: {profitable_dur[0][0]}",
                "evidence": f"${profitable_dur[0][1]['total_pnl']:.2f} profit in this duration",
                "priority": "MEDIUM"
            })
        
        return rules
    
    def _calc_duration(self, trade: Dict) -> Optional[float]:
        """Calculate trade duration in minutes."""
        open_ts = trade.get("opened_at")
        close_ts = trade.get("closed_at")
        
        if not open_ts or not close_ts:
            return None
        
        try:
            if isinstance(open_ts, str):
                open_dt = datetime.fromisoformat(open_ts.replace('Z', '+00:00'))
            else:
                return None
            
            if isinstance(close_ts, str):
                close_dt = datetime.fromisoformat(close_ts.replace('Z', '+00:00'))
            else:
                return None
            
            delta = close_dt - open_dt
            return delta.total_seconds() / 60
        except:
            return None
    
    def _get_hour(self, trade: Dict) -> Optional[int]:
        """Get hour of day from trade open time."""
        open_ts = trade.get("opened_at")
        if not open_ts:
            return None
        
        try:
            if isinstance(open_ts, str):
                dt = datetime.fromisoformat(open_ts.replace('Z', '+00:00'))
                return dt.hour
        except:
            pass
        return None
    
    def _get_dow(self, trade: Dict) -> Optional[int]:
        """Get day of week from trade open time."""
        open_ts = trade.get("opened_at")
        if not open_ts:
            return None
        
        try:
            if isinstance(open_ts, str):
                dt = datetime.fromisoformat(open_ts.replace('Z', '+00:00'))
                return dt.weekday()
        except:
            pass
        return None
    
    def save_analysis(self, analysis: Dict):
        """Save analysis results."""
        os.makedirs(FEATURE_STORE, exist_ok=True)
        
        output_path = os.path.join(FEATURE_STORE, "momentum_analysis.json")
        with open(output_path, 'w') as f:
            json.dump(analysis, f, indent=2, default=str)
        
        rules_path = os.path.join(FEATURE_STORE, "trading_rules.json")
        with open(rules_path, 'w') as f:
            json.dump(analysis.get("actionable_rules", []), f, indent=2)
        
        return output_path


def run_analysis():
    """Run complete momentum analysis."""
    print("=" * 70)
    print("MOMENTUM-BASED PROFIT PREDICTOR")
    print("Finding patterns that PREDICT winning trades")
    print("=" * 70)
    
    predictor = MomentumPredictor()
    
    print("\n[1/2] Loading trade data...")
    trades = predictor.load_trades()
    alpha_count = len([t for t in trades if t.get("bot_type", "alpha") == "alpha"])
    print(f"     Loaded {len(trades)} trades ({alpha_count} Alpha)")
    
    print("\n[2/2] Analyzing all dimensions...")
    analysis = predictor.analyze_all_dimensions()
    
    output_path = predictor.save_analysis(analysis)
    print(f"\n     Analysis saved to: {output_path}")
    
    print("\n" + "=" * 70)
    print("PROFITABLE SYMBOL-DIRECTION COMBINATIONS:")
    print("=" * 70)
    
    sd = analysis["by_symbol_direction"]
    profitable = [(k, v) for k, v in sd.items() if v.get("profitable")]
    
    if profitable:
        for key, stats in profitable[:10]:
            trend_icon = "↑" if stats["trend"] == "improving" else "↓"
            print(f"  {key}: ${stats['total_pnl']:.2f} | {stats['win_rate']}% WR | {stats['trades']} trades | {trend_icon}")
    else:
        print("  No profitable combinations found with current data")
    
    print("\n" + "=" * 70)
    print("STRATEGY PERFORMANCE:")
    print("=" * 70)
    
    for strat, stats in list(analysis["by_strategy"].items())[:10]:
        marker = "***" if stats.get("profitable") else ""
        print(f"  {strat}: ${stats['total_pnl']:.2f} | {stats['win_rate']}% WR | {stats['trades']} trades {marker}")
    
    print("\n" + "=" * 70)
    print("BEST TRADING HOURS (UTC):")
    print("=" * 70)
    
    hours = analysis["by_hour"]
    profitable_hours = [(h, v) for h, v in hours.items() if v.get("profitable")]
    
    if profitable_hours:
        for hour, stats in profitable_hours:
            print(f"  {hour}: ${stats['total_pnl']:.2f} | {stats['win_rate']}% WR")
    else:
        print("  No consistently profitable hours found")
        worst = sorted(hours.items(), key=lambda x: x[1]["total_pnl"])[:3]
        print("  Worst hours to avoid:")
        for hour, stats in worst:
            print(f"    {hour}: ${stats['total_pnl']:.2f}")
    
    print("\n" + "=" * 70)
    print("DURATION ANALYSIS:")
    print("=" * 70)
    
    for dur, stats in analysis["by_duration"].items():
        marker = "***" if stats.get("profitable") else ""
        print(f"  {dur}: ${stats['total_pnl']:.2f} | {stats['win_rate']}% WR | {stats['trades']} trades {marker}")
    
    print("\n" + "=" * 70)
    print("ACTIONABLE RULES:")
    print("=" * 70)
    
    for rule in analysis["actionable_rules"]:
        print(f"\n  [{rule['type']}] {rule['condition']}")
        print(f"      Evidence: {rule['evidence']}")
        print(f"      Priority: {rule['priority']}")
    
    print("\n" + "=" * 70)
    print("TOP 5 WINNING TRADES TO LEARN FROM:")
    print("=" * 70)
    
    for i, trade in enumerate(analysis["top_performers"]["top_winners"][:5], 1):
        print(f"  #{i}: {trade['symbol']} {trade['direction']} | +${trade['pnl']:.2f} | {trade['strategy']} | {trade['duration_min']:.0f}min")
    
    return analysis


if __name__ == "__main__":
    run_analysis()
