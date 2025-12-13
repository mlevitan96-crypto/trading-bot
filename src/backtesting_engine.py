#!/usr/bin/env python3
"""
BACKTESTING ENGINE
==================
Simulates trades with different parameters to find optimal settings.

Features:
1. Load historical trades from logs/positions_futures.json
2. Simulate trades with different parameters (hold times, thresholds)
3. Calculate forward-looking metrics (WR, EV, Sharpe)
4. Save results to feature_store/backtest_results.json

KEY FINDINGS TO OPTIMIZE:
- 30-60min holds = profitable (+$4.32, 56.6% WR)
- 0-2min holds = catastrophic (-$294.58)
- 147 trades exited too early vs 0 too late

Author: Trading Bot System
Date: December 2025
"""

import json
import os
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any, Tuple
from collections import defaultdict
import math

DATA_DIR = "logs"
FEATURE_STORE = "feature_store"
BACKTEST_RESULTS_PATH = os.path.join(FEATURE_STORE, "backtest_results.json")
POSITIONS_FILE = os.path.join(DATA_DIR, "positions_futures.json")


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


def _parse_datetime(dt_str: str) -> Optional[datetime]:
    if not dt_str:
        return None
    try:
        if 'T' in dt_str:
            if '+' in dt_str or '-' in dt_str[10:]:
                return datetime.fromisoformat(dt_str)
            return datetime.fromisoformat(dt_str.replace('Z', '+00:00'))
        return datetime.fromisoformat(dt_str)
    except:
        return None


def _calculate_duration_minutes(opened_at: str, closed_at: str) -> float:
    open_dt = _parse_datetime(opened_at)
    close_dt = _parse_datetime(closed_at)
    if not open_dt or not close_dt:
        return 0
    delta = close_dt - open_dt
    return delta.total_seconds() / 60


class BacktestingEngine:
    """
    Backtesting engine for simulating trades with different parameters.
    """
    
    def __init__(self):
        self.trades: List[Dict] = []
        self.results: Dict[str, Any] = {}
        
    def load_trades(self) -> List[Dict]:
        """Load all closed trades from positions_futures.json."""
        data = _read_json(POSITIONS_FILE, {})
        closed = data.get("closed_positions", [])
        
        enriched_trades = []
        for trade in closed:
            if trade.get("pnl") is None:
                continue
            
            duration_min = _calculate_duration_minutes(
                trade.get("opened_at", ""),
                trade.get("closed_at", "")
            )
            trade["duration_minutes"] = duration_min
            
            opened_at = _parse_datetime(trade.get("opened_at", ""))
            if opened_at:
                trade["hour_utc"] = opened_at.hour
                trade["day_of_week"] = opened_at.weekday()
            
            enriched_trades.append(trade)
        
        self.trades = enriched_trades
        return enriched_trades
    
    def analyze_by_hold_time(self) -> Dict[str, Any]:
        """
        Analyze performance by hold time buckets.
        KEY INSIGHT: 30-60min holds are profitable, 0-2min are catastrophic.
        """
        if not self.trades:
            self.load_trades()
        
        buckets = {
            "0-2min": {"min": 0, "max": 2},
            "2-5min": {"min": 2, "max": 5},
            "5-10min": {"min": 5, "max": 10},
            "10-30min": {"min": 10, "max": 30},
            "30-60min": {"min": 30, "max": 60},
            "60-120min": {"min": 60, "max": 120},
            "120min+": {"min": 120, "max": float('inf')}
        }
        
        results = {}
        for bucket_name, limits in buckets.items():
            bucket_trades = [
                t for t in self.trades
                if limits["min"] <= t.get("duration_minutes", 0) < limits["max"]
            ]
            
            if not bucket_trades:
                results[bucket_name] = {
                    "trades": 0, "pnl": 0, "win_rate": 0, "avg_pnl": 0,
                    "recommendation": "no_data"
                }
                continue
            
            total_pnl = sum(float(t.get("pnl", 0)) for t in bucket_trades)
            wins = sum(1 for t in bucket_trades if float(t.get("pnl", 0)) > 0)
            win_rate = (wins / len(bucket_trades)) * 100 if bucket_trades else 0
            avg_pnl = total_pnl / len(bucket_trades) if bucket_trades else 0
            
            if total_pnl > 0 and win_rate > 50:
                recommendation = "hold_until"
            elif total_pnl < -50:
                recommendation = "block_exit_before"
            else:
                recommendation = "neutral"
            
            results[bucket_name] = {
                "trades": len(bucket_trades),
                "pnl": round(total_pnl, 2),
                "win_rate": round(win_rate, 1),
                "avg_pnl": round(avg_pnl, 3),
                "recommendation": recommendation
            }
        
        return results
    
    def analyze_by_hour(self) -> Dict[str, Any]:
        """
        Analyze performance by hour of day.
        KEY INSIGHT: 08:00 UTC = +$41.72 profit at 61.5% WR.
        """
        if not self.trades:
            self.load_trades()
        
        by_hour = defaultdict(lambda: {"trades": 0, "wins": 0, "pnl": 0})
        
        for trade in self.trades:
            hour = trade.get("hour_utc")
            if hour is None:
                continue
            
            pnl = float(trade.get("pnl", 0))
            by_hour[hour]["trades"] += 1
            by_hour[hour]["pnl"] += pnl
            if pnl > 0:
                by_hour[hour]["wins"] += 1
        
        results = {}
        for hour, stats in sorted(by_hour.items()):
            win_rate = (stats["wins"] / stats["trades"]) * 100 if stats["trades"] else 0
            avg_pnl = stats["pnl"] / stats["trades"] if stats["trades"] else 0
            
            if stats["pnl"] > 20 and win_rate > 55:
                recommendation = "boost_sizing"
            elif stats["pnl"] < -20 and win_rate < 45:
                recommendation = "block_trading"
            else:
                recommendation = "normal"
            
            results[f"{hour:02d}:00"] = {
                "trades": stats["trades"],
                "wins": stats["wins"],
                "pnl": round(stats["pnl"], 2),
                "win_rate": round(win_rate, 1),
                "avg_pnl": round(avg_pnl, 3),
                "recommendation": recommendation
            }
        
        return results
    
    def analyze_by_symbol_direction(self) -> Dict[str, Any]:
        """
        Analyze performance by symbol and direction.
        KEY INSIGHT: DOTUSDT|SHORT|OFI=strong = 100% WR, $17.75 P&L.
        """
        if not self.trades:
            self.load_trades()
        
        by_sd = defaultdict(lambda: {
            "trades": 0, "wins": 0, "pnl": 0, "durations": [],
            "ofi_scores": [], "winners": [], "losers": []
        })
        
        for trade in self.trades:
            symbol = trade.get("symbol", "UNKNOWN")
            direction = (trade.get("direction") or trade.get("side") or "UNKNOWN").upper()
            key = f"{symbol}|{direction}"
            
            pnl = float(trade.get("pnl", 0))
            by_sd[key]["trades"] += 1
            by_sd[key]["pnl"] += pnl
            
            if pnl > 0:
                by_sd[key]["wins"] += 1
                by_sd[key]["winners"].append(pnl)
            else:
                by_sd[key]["losers"].append(pnl)
            
            duration = trade.get("duration_minutes", 0)
            if duration > 0:
                by_sd[key]["durations"].append(duration)
            
            ofi = trade.get("ofi_score")
            if ofi:
                by_sd[key]["ofi_scores"].append(abs(float(ofi)))
        
        results = {}
        for key, stats in by_sd.items():
            if stats["trades"] < 3:
                continue
            
            win_rate = (stats["wins"] / stats["trades"]) * 100 if stats["trades"] else 0
            avg_pnl = stats["pnl"] / stats["trades"] if stats["trades"] else 0
            avg_duration = sum(stats["durations"]) / len(stats["durations"]) if stats["durations"] else 0
            avg_ofi = sum(stats["ofi_scores"]) / len(stats["ofi_scores"]) if stats["ofi_scores"] else 0
            
            avg_winner = sum(stats["winners"]) / len(stats["winners"]) if stats["winners"] else 0
            avg_loser = sum(stats["losers"]) / len(stats["losers"]) if stats["losers"] else 0
            rr_ratio = abs(avg_winner / avg_loser) if avg_loser != 0 else 0
            
            ev = (win_rate/100 * avg_winner) + ((1 - win_rate/100) * avg_loser)
            
            if stats["pnl"] > 5 and win_rate > 50:
                recommendation = "trade_aggressive"
                size_multiplier = min(1.5, 1 + (win_rate - 50) / 100)
            elif stats["pnl"] > 0:
                recommendation = "trade_normal"
                size_multiplier = 1.0
            else:
                recommendation = "reduce_size"
                size_multiplier = max(0.5, 1 - abs(stats["pnl"]) / 50)
            
            results[key] = {
                "trades": stats["trades"],
                "wins": stats["wins"],
                "pnl": round(stats["pnl"], 2),
                "win_rate": round(win_rate, 1),
                "avg_pnl": round(avg_pnl, 3),
                "ev": round(ev, 3),
                "avg_duration_min": round(avg_duration, 1),
                "avg_ofi": round(avg_ofi, 3),
                "rr_ratio": round(rr_ratio, 2),
                "recommendation": recommendation,
                "size_multiplier": round(size_multiplier, 2)
            }
        
        return dict(sorted(results.items(), key=lambda x: x[1]["pnl"], reverse=True))
    
    def simulate_min_hold_time(self, min_hold_minutes: int = 30) -> Dict[str, Any]:
        """
        Simulate what would happen if we enforced a minimum hold time.
        KEY INSIGHT: 147 trades exited too early vs 0 too late.
        """
        if not self.trades:
            self.load_trades()
        
        early_exits = []
        normal_exits = []
        
        for trade in self.trades:
            duration = trade.get("duration_minutes", 0)
            pnl = float(trade.get("pnl", 0))
            
            if duration < min_hold_minutes:
                early_exits.append(trade)
            else:
                normal_exits.append(trade)
        
        early_pnl = sum(float(t.get("pnl", 0)) for t in early_exits)
        normal_pnl = sum(float(t.get("pnl", 0)) for t in normal_exits)
        
        early_wr = (sum(1 for t in early_exits if float(t.get("pnl", 0)) > 0) / len(early_exits) * 100) if early_exits else 0
        normal_wr = (sum(1 for t in normal_exits if float(t.get("pnl", 0)) > 0) / len(normal_exits) * 100) if normal_exits else 0
        
        return {
            "min_hold_minutes": min_hold_minutes,
            "early_exits": {
                "count": len(early_exits),
                "total_pnl": round(early_pnl, 2),
                "win_rate": round(early_wr, 1),
                "avg_pnl": round(early_pnl / len(early_exits), 3) if early_exits else 0
            },
            "normal_exits": {
                "count": len(normal_exits),
                "total_pnl": round(normal_pnl, 2),
                "win_rate": round(normal_wr, 1),
                "avg_pnl": round(normal_pnl / len(normal_exits), 3) if normal_exits else 0
            },
            "potential_improvement": round(abs(early_pnl) if early_pnl < 0 else 0, 2),
            "recommendation": "enforce_min_hold" if early_pnl < -50 else "optional"
        }
    
    def calculate_sharpe_ratio(self, pnl_list: List[float], risk_free_rate: float = 0) -> float:
        """Calculate Sharpe ratio for a list of P&L values."""
        if not pnl_list or len(pnl_list) < 2:
            return 0
        
        mean_return = sum(pnl_list) / len(pnl_list)
        variance = sum((x - mean_return) ** 2 for x in pnl_list) / len(pnl_list)
        std_dev = math.sqrt(variance) if variance > 0 else 0.001
        
        return (mean_return - risk_free_rate) / std_dev if std_dev > 0 else 0
    
    def run_full_backtest(self) -> Dict[str, Any]:
        """
        Run complete backtest analysis and save results.
        """
        if not self.trades:
            self.load_trades()
        
        pnl_list = [float(t.get("pnl", 0)) for t in self.trades]
        sharpe = self.calculate_sharpe_ratio(pnl_list)
        
        results = {
            "generated_at": datetime.utcnow().isoformat(),
            "total_trades": len(self.trades),
            "total_pnl": round(sum(pnl_list), 2),
            "sharpe_ratio": round(sharpe, 3),
            "by_hold_time": self.analyze_by_hold_time(),
            "by_hour": self.analyze_by_hour(),
            "by_symbol_direction": self.analyze_by_symbol_direction(),
            "min_hold_simulation": {
                "15min": self.simulate_min_hold_time(15),
                "30min": self.simulate_min_hold_time(30),
                "45min": self.simulate_min_hold_time(45),
                "60min": self.simulate_min_hold_time(60)
            },
            "optimal_settings": self._derive_optimal_settings()
        }
        
        self.results = results
        _write_json(BACKTEST_RESULTS_PATH, results)
        
        print(f"[BACKTEST] Analysis complete: {len(self.trades)} trades analyzed")
        print(f"[BACKTEST] Total P&L: ${results['total_pnl']:.2f}, Sharpe: {results['sharpe_ratio']:.3f}")
        print(f"[BACKTEST] Results saved to {BACKTEST_RESULTS_PATH}")
        
        return results
    
    def _derive_optimal_settings(self) -> Dict[str, Any]:
        """Derive optimal settings from backtest results."""
        hold_time_data = self.analyze_by_hold_time()
        hour_data = self.analyze_by_hour()
        
        profitable_buckets = [
            k for k, v in hold_time_data.items()
            if v.get("pnl", 0) > 0 and v.get("win_rate", 0) > 50
        ]
        optimal_min_hold = 30
        if "30-60min" in profitable_buckets:
            optimal_min_hold = 30
        elif "10-30min" in profitable_buckets:
            optimal_min_hold = 10
        
        best_hours = [
            int(h.split(":")[0]) for h, v in hour_data.items()
            if v.get("pnl", 0) > 10 and v.get("win_rate", 0) > 55
        ]
        worst_hours = [
            int(h.split(":")[0]) for h, v in hour_data.items()
            if v.get("pnl", 0) < -10 and v.get("win_rate", 0) < 45
        ]
        
        return {
            "min_hold_minutes": optimal_min_hold,
            "best_hours_utc": best_hours,
            "worst_hours_utc": worst_hours,
            "profitable_hold_buckets": profitable_buckets
        }


_CACHED_ENGINE = None

def get_engine() -> BacktestingEngine:
    """Get singleton backtesting engine instance."""
    global _CACHED_ENGINE
    if _CACHED_ENGINE is None:
        _CACHED_ENGINE = BacktestingEngine()
    return _CACHED_ENGINE


def run_backtest() -> Dict[str, Any]:
    """Run full backtest and return results."""
    engine = get_engine()
    return engine.run_full_backtest()


def run_quick_backtest() -> Dict[str, Any]:
    """Run quick backtest with default parameters."""
    engine = get_engine()
    return engine.run_full_backtest()


def get_backtest_results() -> Dict[str, Any]:
    """Get cached backtest results."""
    return _read_json(BACKTEST_RESULTS_PATH, {})


if __name__ == "__main__":
    print("=" * 70)
    print("BACKTESTING ENGINE")
    print("=" * 70)
    
    results = run_backtest()
    
    print("\n" + "=" * 70)
    print("HOLD TIME ANALYSIS")
    print("=" * 70)
    for bucket, data in results.get("by_hold_time", {}).items():
        print(f"  {bucket}: {data['trades']} trades, ${data['pnl']:.2f} P&L, {data['win_rate']:.1f}% WR")
    
    print("\n" + "=" * 70)
    print("OPTIMAL SETTINGS")
    print("=" * 70)
    optimal = results.get("optimal_settings", {})
    print(f"  Minimum Hold: {optimal.get('min_hold_minutes')} minutes")
    print(f"  Best Hours UTC: {optimal.get('best_hours_utc')}")
    print(f"  Worst Hours UTC: {optimal.get('worst_hours_utc')}")
