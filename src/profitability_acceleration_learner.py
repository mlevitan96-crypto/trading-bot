#!/usr/bin/env python3
"""
PROFITABILITY ACCELERATION LEARNER
===================================
Nightly learning module for the 5 profitability acceleration systems.

Learners:
1. Fee Gate Threshold - Optimize entry fee gate based on blocked vs executed trades
2. Hold Time Policy - Calibrate minimum hold times per symbol/direction
3. Edge Sizer Multipliers - Calibrate grade multipliers from grade-to-PnL outcomes
4. Correlation Thresholds - Update throttle thresholds from correlated losses

Each learner:
- Analyzes last 7 days of trade data from logs/positions_futures.json
- Applies EWMA smoothing to prevent oscillation
- Saves learned parameters to feature_store/*.json
- Returns summary for nightly digest

Usage:
    from src.profitability_acceleration_learner import run_all_profitability_learners
    result = run_all_profitability_learners()

Author: Trading Bot System
Date: December 2025
"""

import json
import os
import time
from datetime import datetime, timedelta
from typing import Dict, List, Tuple, Optional, Any
from collections import defaultdict

try:
    from src.data_registry import DataRegistry as DR
except ImportError:
    import sys
    sys.path.insert(0, '/home/runner/workspace')
    from src.data_registry import DataRegistry as DR

FEE_GATE_LEARNING_PATH = "feature_store/fee_gate_learning.json"
HOLD_TIME_POLICY_PATH = "feature_store/hold_time_policy.json"
EDGE_SIZER_CALIBRATION_PATH = "feature_store/edge_sizer_calibration.json"
CORRELATION_THROTTLE_POLICY_PATH = "feature_store/correlation_throttle_policy.json"

EWMA_ALPHA = 0.3
DEFAULT_LOOKBACK_DAYS = 7

DEFAULT_FEE_THRESHOLD = 0.17
MIN_FEE_THRESHOLD = 0.10
MAX_FEE_THRESHOLD = 0.30

MIN_HOLD_SECONDS = 60
MAX_HOLD_SECONDS = 7200

MIN_GRADE_MULTIPLIER = 0.3
MAX_GRADE_MULTIPLIER = 2.0

DEFAULT_GRADE_MULTIPLIERS = {
    "A": 1.5,
    "B": 1.2,
    "C": 1.0,
    "D": 0.7,
    "F": 0.5,
}

HOLD_TIME_BUCKETS = {
    "flash": (0, 60),
    "quick": (60, 300),
    "scalp": (300, 900),
    "short": (900, 3600),
    "medium": (3600, 14400),
    "long": (14400, float("inf")),
}

CORRELATION_CLUSTERS = {
    "BTC": ["BTCUSDT", "ETHUSDT", "SOLUSDT"],
    "ALT": ["AVAXUSDT", "DOTUSDT", "ARBUSDT", "OPUSDT"],
    "MEME": ["DOGEUSDT", "PEPEUSDT"],
    "STABLE": ["BNBUSDT", "XRPUSDT", "ADAUSDT", "TRXUSDT", "LINKUSDT", "MATICUSDT"],
}

SYMBOL_TO_CLUSTER = {}
for cluster_name, members in CORRELATION_CLUSTERS.items():
    for symbol in members:
        SYMBOL_TO_CLUSTER[symbol] = cluster_name


def _now() -> str:
    """Return current UTC timestamp in ISO format."""
    return datetime.utcnow().isoformat() + "Z"


def _log(msg: str):
    """Log with timestamp prefix."""
    ts = datetime.utcnow().isoformat() + "Z"
    print(f"[{ts}] [PA-LEARNER] {msg}")


def _read_json(path: str, default=None) -> Dict:
    """Read JSON file safely."""
    try:
        if os.path.exists(path):
            with open(path, 'r') as f:
                return json.load(f)
    except Exception as e:
        _log(f"Error reading {path}: {e}")
    return default if default is not None else {}


def _write_json(path: str, data: Dict) -> bool:
    """Write JSON file atomically."""
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp_path = path + ".tmp"
        with open(tmp_path, 'w') as f:
            json.dump(data, f, indent=2, default=str)
        os.replace(tmp_path, path)
        return True
    except Exception as e:
        _log(f"Error writing {path}: {e}")
        return False


def _parse_timestamp(ts_str: str) -> Optional[datetime]:
    """Parse timestamp string to datetime."""
    if not ts_str:
        return None
    try:
        if ts_str.endswith("Z"):
            ts_str = ts_str[:-1]
        if "+" in ts_str:
            ts_str = ts_str.split("+")[0]
        elif ts_str.count("-") > 2:
            parts = ts_str.rsplit("-", 1)
            if ":" in parts[-1]:
                ts_str = parts[0]
        return datetime.fromisoformat(ts_str)
    except:
        return None


def _calc_hold_time_seconds(opened_at: str, closed_at: str) -> float:
    """Calculate hold time in seconds."""
    opened = _parse_timestamp(opened_at)
    closed = _parse_timestamp(closed_at)
    if opened and closed:
        return (closed - opened).total_seconds()
    return 0.0


def _ewma_update(current: float, new_value: float, alpha: float = EWMA_ALPHA) -> float:
    """Apply EWMA smoothing: new = alpha * new_value + (1-alpha) * current."""
    return alpha * new_value + (1 - alpha) * current


def _load_recent_trades(days: int = DEFAULT_LOOKBACK_DAYS) -> List[Dict]:
    """Load closed positions from the last N days."""
    positions_data = _read_json(DR.POSITIONS_FUTURES, {"closed_positions": []})
    closed_positions = positions_data.get("closed_positions", [])
    
    cutoff = datetime.utcnow() - timedelta(days=days)
    recent_trades = []
    
    for pos in closed_positions:
        closed_at = _parse_timestamp(pos.get("closed_at", ""))
        if closed_at and closed_at >= cutoff:
            recent_trades.append(pos)
    
    _log(f"Loaded {len(recent_trades)} trades from last {days} days (total closed: {len(closed_positions)})")
    return recent_trades


def learn_fee_gate_threshold() -> Dict[str, Any]:
    """
    Analyze blocked vs executed trades to optimize fee gate threshold.
    
    Algorithm:
    - Load last 7 days of trades from logs/positions_futures.json
    - Compute average expected_move for winning vs losing trades
    - Adjust threshold: if winners had higher expected_move, tighten; if not, loosen
    - Apply EWMA smoothing (alpha=0.3) to prevent oscillation
    - Save to feature_store/fee_gate_learning.json
    """
    _log("Starting fee gate threshold learning...")
    
    result = {
        "status": "no_data",
        "trades_analyzed": 0,
        "winners": 0,
        "losers": 0,
        "avg_winner_size": 0.0,
        "avg_loser_size": 0.0,
        "old_threshold": DEFAULT_FEE_THRESHOLD,
        "new_threshold": DEFAULT_FEE_THRESHOLD,
        "adjustment": 0.0,
        "timestamp": _now(),
    }
    
    trades = _load_recent_trades()
    if not trades:
        _log("No recent trades for fee gate learning")
        return result
    
    current_state = _read_json(FEE_GATE_LEARNING_PATH, {
        "threshold": DEFAULT_FEE_THRESHOLD,
        "history": [],
    })
    current_threshold = current_state.get("threshold", DEFAULT_FEE_THRESHOLD)
    
    winners = []
    losers = []
    
    for trade in trades:
        pnl = trade.get("pnl") or trade.get("net_pnl", 0)
        margin = trade.get("margin_collateral", 0) or trade.get("size_usd", 0)
        
        if margin > 0:
            pnl_pct = (pnl / margin) * 100
            
            if pnl > 0:
                winners.append({
                    "pnl": pnl,
                    "pnl_pct": pnl_pct,
                    "margin": margin,
                    "symbol": trade.get("symbol"),
                })
            else:
                losers.append({
                    "pnl": pnl,
                    "pnl_pct": pnl_pct,
                    "margin": margin,
                    "symbol": trade.get("symbol"),
                })
    
    result["trades_analyzed"] = len(trades)
    result["winners"] = len(winners)
    result["losers"] = len(losers)
    
    if not winners and not losers:
        _log("No valid trades for analysis")
        return result
    
    avg_winner_pct = sum(w["pnl_pct"] for w in winners) / len(winners) if winners else 0
    avg_loser_pct = sum(l["pnl_pct"] for l in losers) / len(losers) if losers else 0
    
    result["avg_winner_size"] = round(avg_winner_pct, 4)
    result["avg_loser_size"] = round(avg_loser_pct, 4)
    result["old_threshold"] = current_threshold
    
    if len(winners) >= 3 and len(losers) >= 3:
        win_rate = len(winners) / (len(winners) + len(losers))
        
        if win_rate < 0.4 and avg_loser_pct < -0.5:
            adjustment = 0.02
            reason = "low_win_rate_tighten"
        elif win_rate > 0.6 and avg_winner_pct > 0.5:
            adjustment = -0.01
            reason = "high_win_rate_loosen"
        elif avg_winner_pct > abs(avg_loser_pct) * 1.5:
            adjustment = -0.005
            reason = "winners_exceed_losers"
        elif abs(avg_loser_pct) > avg_winner_pct * 1.5:
            adjustment = 0.01
            reason = "losers_dominate"
        else:
            adjustment = 0.0
            reason = "balanced"
        
        raw_new = current_threshold + adjustment
        smoothed_new = _ewma_update(current_threshold, raw_new)
        
        new_threshold = max(MIN_FEE_THRESHOLD, min(MAX_FEE_THRESHOLD, smoothed_new))
        
        result["new_threshold"] = round(new_threshold, 4)
        result["adjustment"] = round(new_threshold - current_threshold, 4)
        result["reason"] = reason
        result["win_rate"] = round(win_rate, 4)
        result["status"] = "updated"
        
        new_state = {
            "threshold": new_threshold,
            "min_buffer_multiplier": 1.2,
            "updated_at": _now(),
            "trades_analyzed": len(trades),
            "win_rate": win_rate,
            "avg_winner_pct": avg_winner_pct,
            "avg_loser_pct": avg_loser_pct,
            "reason": reason,
            "history": current_state.get("history", [])[-30:] + [{
                "ts": _now(),
                "old": current_threshold,
                "new": new_threshold,
                "reason": reason,
            }],
        }
        
        _write_json(FEE_GATE_LEARNING_PATH, new_state)
        _log(f"Fee gate threshold: {current_threshold:.4f} -> {new_threshold:.4f} ({reason})")
    else:
        result["status"] = "insufficient_data"
        _log(f"Insufficient trades for fee gate learning (winners: {len(winners)}, losers: {len(losers)})")
    
    return result


def learn_hold_time_policy() -> Dict[str, Any]:
    """
    Calibrate minimum hold times per symbol/direction.
    
    Algorithm:
    - Bucket trades by hold duration: <5min, 5-15min, 15-60min, 1h+
    - Compute EV per bucket per symbol
    - Set min_hold_seconds to the lower bound of the most profitable bucket
    - Apply 90th percentile guardrail (don't set min above 90% of actual holds)
    - Save to feature_store/hold_time_policy.json
    """
    _log("Starting hold time policy learning...")
    
    result = {
        "status": "no_data",
        "trades_analyzed": 0,
        "symbols_learned": 0,
        "patterns_learned": 0,
        "adjustments": {},
        "timestamp": _now(),
    }
    
    trades = _load_recent_trades()
    if not trades:
        _log("No recent trades for hold time learning")
        return result
    
    current_policy = _read_json(HOLD_TIME_POLICY_PATH, {
        "symbol_hold_times": {},
        "direction_hold_times": {},
        "tier_defaults": {"major": 600, "other_major": 480, "altcoin": 300},
    })
    
    symbol_buckets: Dict[str, Dict[str, List[Dict]]] = defaultdict(lambda: defaultdict(list))
    direction_buckets: Dict[str, Dict[str, List[Dict]]] = defaultdict(lambda: defaultdict(list))
    all_hold_times: Dict[str, List[float]] = defaultdict(list)
    
    for trade in trades:
        symbol = trade.get("symbol", "UNKNOWN")
        direction = trade.get("direction", "UNKNOWN")
        pnl = trade.get("pnl") or trade.get("net_pnl", 0)
        
        opened_at = trade.get("opened_at", "")
        closed_at = trade.get("closed_at", "")
        hold_seconds = _calc_hold_time_seconds(opened_at, closed_at)
        
        if hold_seconds <= 0:
            continue
        
        all_hold_times[symbol].append(hold_seconds)
        
        for bucket_name, (min_sec, max_sec) in HOLD_TIME_BUCKETS.items():
            if min_sec <= hold_seconds < max_sec:
                trade_data = {"pnl": pnl, "hold_seconds": hold_seconds}
                symbol_buckets[symbol][bucket_name].append(trade_data)
                dir_key = f"{symbol}_{direction}"
                direction_buckets[dir_key][bucket_name].append(trade_data)
                break
    
    result["trades_analyzed"] = len(trades)
    
    new_symbol_hold_times = dict(current_policy.get("symbol_hold_times", {}))
    new_direction_hold_times = dict(current_policy.get("direction_hold_times", {}))
    adjustments = {}
    
    for symbol, buckets in symbol_buckets.items():
        if not buckets:
            continue
        
        bucket_evs = {}
        for bucket_name, bucket_trades in buckets.items():
            if len(bucket_trades) >= 3:
                avg_pnl = sum(t["pnl"] for t in bucket_trades) / len(bucket_trades)
                win_rate = sum(1 for t in bucket_trades if t["pnl"] > 0) / len(bucket_trades)
                bucket_evs[bucket_name] = {
                    "avg_pnl": avg_pnl,
                    "win_rate": win_rate,
                    "count": len(bucket_trades),
                }
        
        if not bucket_evs:
            continue
        
        # CRITICAL FIX: Only consider buckets with POSITIVE EV as candidates
        # If all buckets are negative, default to LONGER hold times (since data shows we exit too early)
        profitable_buckets = {b: ev for b, ev in bucket_evs.items() if ev["avg_pnl"] > 0}
        
        if profitable_buckets:
            # Pick the bucket with the highest positive EV
            best_bucket = max(profitable_buckets.keys(), key=lambda b: profitable_buckets[b]["avg_pnl"])
            best_min_hold = HOLD_TIME_BUCKETS[best_bucket][0]
        else:
            # All buckets are negative - we're exiting too early
            # Default to LONGER hold times by picking "medium" or "long" duration
            current_hold = new_symbol_hold_times.get(symbol, 300)
            # Increase hold time by 50% when all buckets are losing
            best_min_hold = int(current_hold * 1.5)
            best_bucket = "extended_default"  # Mark that we're extending, not learning from positive data
            _log(f"  {symbol}: All buckets negative EV, extending hold time by 50%")
        
        symbol_holds = all_hold_times.get(symbol, [])
        if symbol_holds and profitable_buckets:
            # Only cap to p90 if we found profitable buckets
            sorted_holds = sorted(symbol_holds)
            p90_idx = int(len(sorted_holds) * 0.9)
            p90_hold = sorted_holds[min(p90_idx, len(sorted_holds) - 1)]
            best_min_hold = min(best_min_hold, p90_hold)
        
        best_min_hold = max(MIN_HOLD_SECONDS, min(MAX_HOLD_SECONDS, best_min_hold))
        
        current_hold = new_symbol_hold_times.get(symbol, 300)
        smoothed_hold = _ewma_update(current_hold, best_min_hold)
        smoothed_hold = max(MIN_HOLD_SECONDS, min(MAX_HOLD_SECONDS, int(smoothed_hold)))
        
        if abs(smoothed_hold - current_hold) > 30:
            # Handle extended_default case (when all buckets have negative EV)
            if best_bucket == "extended_default":
                bucket_ev = 0.0  # No positive bucket found, mark as neutral
            else:
                bucket_ev = round(bucket_evs[best_bucket]["avg_pnl"], 4)
            
            adjustments[symbol] = {
                "old": current_hold,
                "new": smoothed_hold,
                "best_bucket": best_bucket,
                "bucket_ev": bucket_ev,
            }
            new_symbol_hold_times[symbol] = smoothed_hold
    
    result["symbols_learned"] = len(symbol_buckets)
    result["patterns_learned"] = len(adjustments)
    result["adjustments"] = adjustments
    result["status"] = "updated" if adjustments else "no_changes"
    
    new_policy = {
        "version": 2,
        "updated_at": _now(),
        "symbol_hold_times": new_symbol_hold_times,
        "direction_hold_times": new_direction_hold_times,
        "tier_defaults": current_policy.get("tier_defaults", {"major": 600, "other_major": 480, "altcoin": 300}),
        "trades_analyzed": len(trades),
        "symbols_analyzed": len(symbol_buckets),
        "learning_summary": {
            "adjustments_made": len(adjustments),
            "adjustments": adjustments,
        },
    }
    
    _write_json(HOLD_TIME_POLICY_PATH, new_policy)
    _log(f"Hold time policy: {len(adjustments)} symbol adjustments made")
    
    return result


def learn_edge_sizer_multipliers() -> Dict[str, Any]:
    """
    Calibrate grade multipliers from grade-to-PnL outcomes.
    
    Algorithm:
    - Group trades by signal quality grade (A/B/C/D/F)
    - Compute EV and win rate per grade
    - Adjust multipliers: increase for grades with positive EV, decrease for negative
    - Constrain multipliers to [0.3, 2.0] range
    - Save to feature_store/edge_sizer_calibration.json
    """
    _log("Starting edge sizer multiplier learning...")
    
    result = {
        "status": "no_data",
        "trades_analyzed": 0,
        "grades_calibrated": 0,
        "multipliers": {},
        "grade_stats": {},
        "timestamp": _now(),
    }
    
    trades = _load_recent_trades()
    if not trades:
        _log("No recent trades for edge sizer learning")
        return result
    
    current_calibration = _read_json(EDGE_SIZER_CALIBRATION_PATH, {
        "multipliers": DEFAULT_GRADE_MULTIPLIERS.copy(),
    })
    current_multipliers = current_calibration.get("multipliers", DEFAULT_GRADE_MULTIPLIERS.copy())
    
    grade_trades: Dict[str, List[Dict]] = defaultdict(list)
    
    for trade in trades:
        grade = trade.get("grade", trade.get("signal_grade", "C"))
        if grade not in ["A", "B", "C", "D", "F"]:
            grade = "C"
        
        pnl = trade.get("pnl") or trade.get("net_pnl", 0)
        margin = trade.get("margin_collateral", 0) or trade.get("size_usd", 100)
        
        grade_trades[grade].append({
            "pnl": pnl,
            "margin": margin,
            "roi": (pnl / margin * 100) if margin > 0 else 0,
        })
    
    result["trades_analyzed"] = len(trades)
    
    new_multipliers = dict(current_multipliers)
    grade_stats = {}
    calibrations_made = 0
    
    for grade in ["A", "B", "C", "D", "F"]:
        gtrades = grade_trades.get(grade, [])
        
        if len(gtrades) < 5:
            grade_stats[grade] = {
                "count": len(gtrades),
                "status": "insufficient_data",
            }
            continue
        
        total_pnl = sum(t["pnl"] for t in gtrades)
        avg_pnl = total_pnl / len(gtrades)
        avg_roi = sum(t["roi"] for t in gtrades) / len(gtrades)
        win_rate = sum(1 for t in gtrades if t["pnl"] > 0) / len(gtrades)
        
        grade_stats[grade] = {
            "count": len(gtrades),
            "total_pnl": round(total_pnl, 4),
            "avg_pnl": round(avg_pnl, 4),
            "avg_roi": round(avg_roi, 4),
            "win_rate": round(win_rate, 4),
        }
        
        current_mult = current_multipliers.get(grade, 1.0)
        
        if avg_pnl > 0 and win_rate > 0.5:
            adjustment = min(0.1, avg_roi / 100)
        elif avg_pnl < 0 and win_rate < 0.4:
            adjustment = max(-0.1, avg_roi / 100)
        else:
            adjustment = 0.0
        
        raw_new = current_mult + adjustment
        smoothed_new = _ewma_update(current_mult, raw_new)
        
        new_mult = max(MIN_GRADE_MULTIPLIER, min(MAX_GRADE_MULTIPLIER, smoothed_new))
        
        if abs(new_mult - current_mult) > 0.02:
            new_multipliers[grade] = round(new_mult, 3)
            calibrations_made += 1
            grade_stats[grade]["old_mult"] = current_mult
            grade_stats[grade]["new_mult"] = new_mult
    
    result["grades_calibrated"] = calibrations_made
    result["multipliers"] = new_multipliers
    result["grade_stats"] = grade_stats
    result["status"] = "updated" if calibrations_made > 0 else "no_changes"
    
    new_calibration = {
        "version": 2,
        "updated_at": _now(),
        "multipliers": new_multipliers,
        "min_multiplier": MIN_GRADE_MULTIPLIER,
        "max_multiplier": MAX_GRADE_MULTIPLIER,
        "trades_analyzed": len(trades),
        "grade_stats": grade_stats,
        "calibrations_made": calibrations_made,
        "history": current_calibration.get("history", [])[-30:] + [{
            "ts": _now(),
            "multipliers": new_multipliers,
            "calibrations": calibrations_made,
        }],
    }
    
    _write_json(EDGE_SIZER_CALIBRATION_PATH, new_calibration)
    _log(f"Edge sizer: {calibrations_made} grade multipliers calibrated")
    
    return result


def learn_correlation_thresholds() -> Dict[str, Any]:
    """
    Update correlation throttle thresholds from correlated losses.
    
    Algorithm:
    - Find trades that lost money while correlated positions also lost
    - If correlated losses exceed 20% of total losses, tighten high_corr_threshold
    - If throttling is blocking too many winners, loosen threshold
    - Save to feature_store/correlation_throttle_policy.json
    """
    _log("Starting correlation threshold learning...")
    
    result = {
        "status": "no_data",
        "trades_analyzed": 0,
        "correlated_loss_events": 0,
        "correlated_loss_pct": 0.0,
        "old_threshold": 0.7,
        "new_threshold": 0.7,
        "cluster_stats": {},
        "timestamp": _now(),
    }
    
    trades = _load_recent_trades()
    if not trades:
        _log("No recent trades for correlation learning")
        return result
    
    current_policy = _read_json(CORRELATION_THROTTLE_POLICY_PATH, {
        "high_corr_threshold": 0.7,
        "extreme_corr_threshold": 0.85,
        "max_cluster_exposure_pct": 0.30,
    })
    current_threshold = current_policy.get("high_corr_threshold", 0.7)
    
    trades_by_hour: Dict[str, List[Dict]] = defaultdict(list)
    
    for trade in trades:
        closed_at = trade.get("closed_at", "")
        closed_dt = _parse_timestamp(closed_at)
        if closed_dt:
            hour_key = closed_dt.strftime("%Y-%m-%d-%H")
            trades_by_hour[hour_key].append(trade)
    
    correlated_loss_events = 0
    total_loss_events = 0
    cluster_stats: Dict[str, Dict] = defaultdict(lambda: {"trades": 0, "pnl": 0.0, "losses": 0})
    
    for hour_key, hour_trades in trades_by_hour.items():
        cluster_losses: Dict[str, List[float]] = defaultdict(list)
        
        for trade in hour_trades:
            symbol = trade.get("symbol", "UNKNOWN")
            pnl = trade.get("pnl") or trade.get("net_pnl", 0)
            cluster = SYMBOL_TO_CLUSTER.get(symbol)
            
            if cluster:
                cluster_stats[cluster]["trades"] += 1
                cluster_stats[cluster]["pnl"] += pnl
                
                if pnl < 0:
                    cluster_losses[cluster].append(pnl)
                    total_loss_events += 1
                    cluster_stats[cluster]["losses"] += 1
        
        for cluster, losses in cluster_losses.items():
            if len(losses) >= 2:
                correlated_loss_events += len(losses)
    
    result["trades_analyzed"] = len(trades)
    result["correlated_loss_events"] = correlated_loss_events
    result["old_threshold"] = current_threshold
    
    if total_loss_events > 0:
        corr_loss_pct = (correlated_loss_events / total_loss_events) * 100
        result["correlated_loss_pct"] = round(corr_loss_pct, 2)
        
        if corr_loss_pct > 30:
            adjustment = 0.03
            reason = "high_correlated_losses_tighten"
        elif corr_loss_pct > 20:
            adjustment = 0.01
            reason = "moderate_correlated_losses_tighten"
        elif corr_loss_pct < 10:
            adjustment = -0.02
            reason = "low_correlated_losses_loosen"
        else:
            adjustment = 0.0
            reason = "balanced"
        
        raw_new = current_threshold - adjustment
        smoothed_new = _ewma_update(current_threshold, raw_new)
        
        new_threshold = max(0.5, min(0.9, smoothed_new))
        
        result["new_threshold"] = round(new_threshold, 3)
        result["adjustment"] = round(new_threshold - current_threshold, 4)
        result["reason"] = reason
        result["status"] = "updated"
        
        new_policy = {
            "version": 2,
            "updated_at": _now(),
            "high_corr_threshold": new_threshold,
            "extreme_corr_threshold": min(0.95, new_threshold + 0.15),
            "max_cluster_exposure_pct": current_policy.get("max_cluster_exposure_pct", 0.30),
            "max_positions_per_cluster": 3,
            "trades_analyzed": len(trades),
            "correlated_loss_pct": corr_loss_pct,
            "reason": reason,
            "cluster_stats": {k: dict(v) for k, v in cluster_stats.items()},
            "history": current_policy.get("history", [])[-30:] + [{
                "ts": _now(),
                "old": current_threshold,
                "new": new_threshold,
                "corr_loss_pct": corr_loss_pct,
            }],
        }
        
        _write_json(CORRELATION_THROTTLE_POLICY_PATH, new_policy)
        _log(f"Correlation threshold: {current_threshold:.3f} -> {new_threshold:.3f} ({reason})")
    else:
        result["status"] = "no_losses"
        _log("No loss events for correlation learning")
    
    result["cluster_stats"] = {k: dict(v) for k, v in cluster_stats.items()}
    
    return result


def run_all_profitability_learners() -> Dict[str, Any]:
    """
    Run all profitability acceleration learners and return summary.
    
    Returns:
        Dict with results from all learners:
        - fee_gate: Fee gate threshold learning result
        - hold_time: Hold time policy learning result
        - edge_sizer: Edge sizer multiplier learning result
        - correlation: Correlation threshold learning result
        - summary: Overall summary
    """
    _log("=" * 60)
    _log("PROFITABILITY ACCELERATION LEARNING - Starting")
    _log("=" * 60)
    
    start_time = time.time()
    
    results = {
        "fee_gate": {},
        "hold_time": {},
        "edge_sizer": {},
        "correlation": {},
        "summary": {},
        "timestamp": _now(),
    }
    
    try:
        results["fee_gate"] = learn_fee_gate_threshold()
    except Exception as e:
        _log(f"Fee gate learning error: {e}")
        results["fee_gate"] = {"status": "error", "error": str(e)}
    
    try:
        results["hold_time"] = learn_hold_time_policy()
    except Exception as e:
        _log(f"Hold time learning error: {e}")
        results["hold_time"] = {"status": "error", "error": str(e)}
    
    try:
        results["edge_sizer"] = learn_edge_sizer_multipliers()
    except Exception as e:
        _log(f"Edge sizer learning error: {e}")
        results["edge_sizer"] = {"status": "error", "error": str(e)}
    
    try:
        results["correlation"] = learn_correlation_thresholds()
    except Exception as e:
        _log(f"Correlation learning error: {e}")
        results["correlation"] = {"status": "error", "error": str(e)}
    
    elapsed = time.time() - start_time
    
    successful = sum(1 for k in ["fee_gate", "hold_time", "edge_sizer", "correlation"]
                     if results[k].get("status") in ["updated", "no_changes", "no_losses"])
    
    results["summary"] = {
        "learners_run": 4,
        "successful": successful,
        "elapsed_seconds": round(elapsed, 2),
        "overall_status": "success" if successful == 4 else "partial" if successful > 0 else "failed",
    }
    
    _log("=" * 60)
    _log(f"PROFITABILITY ACCELERATION LEARNING - Complete ({elapsed:.2f}s)")
    _log(f"Results: {successful}/4 learners successful")
    _log("=" * 60)
    
    return results


if __name__ == "__main__":
    results = run_all_profitability_learners()
    print("\n" + "=" * 60)
    print("LEARNING RESULTS")
    print("=" * 60)
    print(json.dumps(results, indent=2, default=str))
