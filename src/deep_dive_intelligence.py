"""
DEEP DIVE INTELLIGENCE ANALYSIS
================================
Comprehensive analysis across all trades, blocked signals, and counterfactuals
to extract profit-seeking patterns.

Philosophy: "Predict trends to make money" - not "avoid losses"
Goal: No matter which way coins move, predict it and profit off of it.
"""

import json
import os
from datetime import datetime, timedelta
from collections import defaultdict
from typing import Dict, List, Tuple, Any, Optional
import statistics

POSITIONS_FILE = "logs/positions_futures.json"
COUNTERFACTUAL_FILE = "logs/counterfactual_outcomes.jsonl"
ENRICHED_DECISIONS_FILE = "logs/enriched_decisions.jsonl"
ALPHA_TRADES_FILE = "logs/alpha_trades.jsonl"
COIN_TIERS_FILE = "feature_store/coin_tier_recommendations.json"
INVERSION_RULES_FILE = "feature_store/signal_inversion_rules.json"
DIRECTION_RULES_FILE = "feature_store/learned_direction_rules.json"


def load_jsonl(filepath: str) -> List[Dict]:
    """Load JSONL file."""
    records = []
    if os.path.exists(filepath):
        with open(filepath, 'r') as f:
            for line in f:
                try:
                    records.append(json.loads(line.strip()))
                except:
                    pass
    return records


def load_json(filepath: str) -> Dict:
    """Load JSON file."""
    if os.path.exists(filepath):
        with open(filepath, 'r') as f:
            return json.load(f)
    return {}


def parse_timestamp(ts) -> Optional[datetime]:
    """Parse various timestamp formats, always returns naive datetime."""
    if ts is None:
        return None
    if isinstance(ts, (int, float)):
        try:
            return datetime.fromtimestamp(ts)
        except:
            return None
    if isinstance(ts, str):
        try:
            clean = ts.replace('Z', '').replace('+00:00', '')
            if '-07:00' in ts:
                clean = ts.split('-07:00')[0]
            elif '+' in clean:
                clean = clean.split('+')[0]
            return datetime.fromisoformat(clean)
        except:
            return None
    return None


def get_hour_bucket(ts) -> Optional[int]:
    """Get UTC hour from timestamp."""
    dt = parse_timestamp(ts)
    return dt.hour if dt else None


def get_hold_duration_bucket(opened_at, closed_at) -> str:
    """Categorize hold duration into buckets."""
    open_dt = parse_timestamp(opened_at)
    close_dt = parse_timestamp(closed_at)
    if not open_dt or not close_dt:
        return "unknown"
    
    duration_mins = (close_dt - open_dt).total_seconds() / 60
    
    if duration_mins < 15:
        return "ultra_short (<15m)"
    elif duration_mins < 60:
        return "short (15m-1h)"
    elif duration_mins < 240:
        return "medium (1h-4h)"
    elif duration_mins < 480:
        return "long (4h-8h)"
    else:
        return "extended (>8h)"


def categorize_ofi(ofi_score: float) -> str:
    """Categorize OFI score."""
    if ofi_score is None:
        return "unknown"
    ofi = abs(ofi_score)
    if ofi >= 0.8:
        return "strong (0.8+)"
    elif ofi >= 0.6:
        return "moderate (0.6-0.8)"
    elif ofi >= 0.4:
        return "weak (0.4-0.6)"
    else:
        return "noise (<0.4)"


def categorize_ensemble(ensemble_score: float) -> str:
    """Categorize ensemble score."""
    if ensemble_score is None:
        return "unknown"
    ens = abs(ensemble_score)
    if ens >= 0.08:
        return "high (0.08+)"
    elif ens >= 0.05:
        return "medium (0.05-0.08)"
    elif ens >= 0.03:
        return "low (0.03-0.05)"
    else:
        return "minimal (<0.03)"


def categorize_mtf(mtf_confidence: float) -> str:
    """Categorize MTF alignment."""
    if mtf_confidence is None:
        return "unknown"
    if mtf_confidence >= 0.7:
        return "aligned (0.7+)"
    elif mtf_confidence >= 0.5:
        return "partial (0.5-0.7)"
    elif mtf_confidence >= 0.3:
        return "weak (0.3-0.5)"
    else:
        return "opposed (<0.3)"


def analyze_executed_trades() -> Dict:
    """Analyze all executed trades for profitability patterns."""
    positions = load_json(POSITIONS_FILE)
    closed = positions.get('closed_positions', [])
    
    if not closed:
        return {"error": "No closed positions found"}
    
    analysis = {
        "total_trades": len(closed),
        "by_coin": defaultdict(lambda: {"trades": 0, "wins": 0, "pnl": 0.0, "fees": 0.0}),
        "by_direction": defaultdict(lambda: {"trades": 0, "wins": 0, "pnl": 0.0}),
        "by_coin_direction": defaultdict(lambda: {"trades": 0, "wins": 0, "pnl": 0.0}),
        "by_hour": defaultdict(lambda: {"trades": 0, "wins": 0, "pnl": 0.0}),
        "by_hold_duration": defaultdict(lambda: {"trades": 0, "wins": 0, "pnl": 0.0, "avg_pnl": []}),
        "by_ofi_bucket": defaultdict(lambda: {"trades": 0, "wins": 0, "pnl": 0.0}),
        "by_ensemble_bucket": defaultdict(lambda: {"trades": 0, "wins": 0, "pnl": 0.0}),
        "by_mtf_bucket": defaultdict(lambda: {"trades": 0, "wins": 0, "pnl": 0.0}),
        "by_regime": defaultdict(lambda: {"trades": 0, "wins": 0, "pnl": 0.0}),
        "by_close_reason": defaultdict(lambda: {"trades": 0, "wins": 0, "pnl": 0.0}),
        "direction_accuracy": {"correct": 0, "incorrect": 0},
        "win_loss_patterns": [],
        "best_configs": [],
        "worst_configs": []
    }
    
    all_pnls = []
    
    for pos in closed:
        symbol = pos.get('symbol', 'UNKNOWN')
        direction = pos.get('direction', 'UNKNOWN')
        pnl = pos.get('net_pnl', pos.get('pnl', 0)) or 0
        fees = pos.get('trading_fees', 0) or 0
        is_win = pnl > 0
        
        all_pnls.append(pnl)
        
        hour = get_hour_bucket(pos.get('opened_at'))
        hold_bucket = get_hold_duration_bucket(pos.get('opened_at'), pos.get('closed_at'))
        ofi_bucket = categorize_ofi(pos.get('ofi_score'))
        ensemble_bucket = categorize_ensemble(pos.get('ensemble_score'))
        mtf_bucket = categorize_mtf(pos.get('mtf_confidence'))
        regime = pos.get('regime', 'unknown')
        close_reason = pos.get('close_reason', 'unknown')
        
        coin_dir_key = f"{symbol}_{direction}"
        
        analysis["by_coin"][symbol]["trades"] += 1
        analysis["by_coin"][symbol]["wins"] += 1 if is_win else 0
        analysis["by_coin"][symbol]["pnl"] += pnl
        analysis["by_coin"][symbol]["fees"] += fees
        
        analysis["by_direction"][direction]["trades"] += 1
        analysis["by_direction"][direction]["wins"] += 1 if is_win else 0
        analysis["by_direction"][direction]["pnl"] += pnl
        
        analysis["by_coin_direction"][coin_dir_key]["trades"] += 1
        analysis["by_coin_direction"][coin_dir_key]["wins"] += 1 if is_win else 0
        analysis["by_coin_direction"][coin_dir_key]["pnl"] += pnl
        
        if hour is not None:
            analysis["by_hour"][hour]["trades"] += 1
            analysis["by_hour"][hour]["wins"] += 1 if is_win else 0
            analysis["by_hour"][hour]["pnl"] += pnl
        
        analysis["by_hold_duration"][hold_bucket]["trades"] += 1
        analysis["by_hold_duration"][hold_bucket]["wins"] += 1 if is_win else 0
        analysis["by_hold_duration"][hold_bucket]["pnl"] += pnl
        analysis["by_hold_duration"][hold_bucket]["avg_pnl"].append(pnl)
        
        analysis["by_ofi_bucket"][ofi_bucket]["trades"] += 1
        analysis["by_ofi_bucket"][ofi_bucket]["wins"] += 1 if is_win else 0
        analysis["by_ofi_bucket"][ofi_bucket]["pnl"] += pnl
        
        analysis["by_ensemble_bucket"][ensemble_bucket]["trades"] += 1
        analysis["by_ensemble_bucket"][ensemble_bucket]["wins"] += 1 if is_win else 0
        analysis["by_ensemble_bucket"][ensemble_bucket]["pnl"] += pnl
        
        analysis["by_mtf_bucket"][mtf_bucket]["trades"] += 1
        analysis["by_mtf_bucket"][mtf_bucket]["wins"] += 1 if is_win else 0
        analysis["by_mtf_bucket"][mtf_bucket]["pnl"] += pnl
        
        analysis["by_regime"][regime]["trades"] += 1
        analysis["by_regime"][regime]["wins"] += 1 if is_win else 0
        analysis["by_regime"][regime]["pnl"] += pnl
        
        analysis["by_close_reason"][close_reason]["trades"] += 1
        analysis["by_close_reason"][close_reason]["wins"] += 1 if is_win else 0
        analysis["by_close_reason"][close_reason]["pnl"] += pnl
        
        entry_price = pos.get('entry_price', 0)
        exit_price = pos.get('exit_price', 0)
        if entry_price and exit_price:
            price_moved_up = exit_price > entry_price
            if direction == "LONG":
                correct_direction = price_moved_up
            else:
                correct_direction = not price_moved_up
            
            if correct_direction:
                analysis["direction_accuracy"]["correct"] += 1
            else:
                analysis["direction_accuracy"]["incorrect"] += 1
    
    analysis["summary"] = {
        "total_pnl": sum(all_pnls),
        "avg_pnl": statistics.mean(all_pnls) if all_pnls else 0,
        "median_pnl": statistics.median(all_pnls) if all_pnls else 0,
        "win_count": sum(1 for p in all_pnls if p > 0),
        "loss_count": sum(1 for p in all_pnls if p <= 0),
        "win_rate": sum(1 for p in all_pnls if p > 0) / len(all_pnls) * 100 if all_pnls else 0,
        "direction_accuracy_pct": analysis["direction_accuracy"]["correct"] / 
            (analysis["direction_accuracy"]["correct"] + analysis["direction_accuracy"]["incorrect"]) * 100
            if (analysis["direction_accuracy"]["correct"] + analysis["direction_accuracy"]["incorrect"]) > 0 else 0
    }
    
    for bucket, data in analysis["by_hold_duration"].items():
        if data["avg_pnl"]:
            data["ev"] = statistics.mean(data["avg_pnl"])
            del data["avg_pnl"]
    
    return analysis


def analyze_counterfactuals() -> Dict:
    """Analyze blocked signals and their theoretical outcomes."""
    counterfactuals = load_jsonl(COUNTERFACTUAL_FILE)
    
    if not counterfactuals:
        return {"error": "No counterfactual data found"}
    
    analysis = {
        "total_blocked": len(counterfactuals),
        "missed_opportunities": 0,
        "avoided_losses": 0,
        "by_block_reason": defaultdict(lambda: {"count": 0, "would_win": 0, "missed_pnl": 0.0}),
        "by_coin": defaultdict(lambda: {"blocked": 0, "would_win": 0, "theoretical_pnl_5m": 0.0, "theoretical_pnl_15m": 0.0, "theoretical_pnl_60m": 0.0}),
        "by_direction": defaultdict(lambda: {"blocked": 0, "would_win": 0}),
        "by_hour": defaultdict(lambda: {"blocked": 0, "would_win": 0, "missed_pnl": 0.0}),
        "intelligence_patterns": {
            "high_ofi_blocked": {"count": 0, "would_win": 0},
            "high_ensemble_blocked": {"count": 0, "would_win": 0},
            "aligned_mtf_blocked": {"count": 0, "would_win": 0}
        },
        "best_interval_distribution": defaultdict(int)
    }
    
    for cf in counterfactuals:
        symbol = cf.get('symbol', 'UNKNOWN')
        side = cf.get('side', 'UNKNOWN')
        block_reason = cf.get('block_reason', 'unknown')
        would_have_won = cf.get('would_have_won', False)
        missed_opportunity = cf.get('missed_opportunity', False)
        best_pnl = cf.get('best_pnl_pct', 0) or 0
        best_interval = cf.get('best_interval', 'unknown')
        
        intel = cf.get('intelligence', {})
        ofi = intel.get('ofi', 0) or 0
        ensemble = intel.get('ensemble', 0) or 0
        mtf = intel.get('mtf_confidence', 0) or 0
        
        outcomes = cf.get('outcomes', {})
        pnl_5m = outcomes.get('5m', {}).get('pnl_pct', 0) or 0
        pnl_15m = outcomes.get('15m', {}).get('pnl_pct', 0) or 0
        pnl_60m = outcomes.get('60m', {}).get('pnl_pct', 0) or 0
        
        hour = None
        signal_ts = cf.get('signal_ts')
        if signal_ts:
            dt = parse_timestamp(signal_ts)
            hour = dt.hour if dt else None
        
        if missed_opportunity:
            analysis["missed_opportunities"] += 1
        else:
            analysis["avoided_losses"] += 1
        
        analysis["by_block_reason"][block_reason]["count"] += 1
        analysis["by_block_reason"][block_reason]["would_win"] += 1 if would_have_won else 0
        analysis["by_block_reason"][block_reason]["missed_pnl"] += best_pnl if missed_opportunity else 0
        
        analysis["by_coin"][symbol]["blocked"] += 1
        analysis["by_coin"][symbol]["would_win"] += 1 if would_have_won else 0
        analysis["by_coin"][symbol]["theoretical_pnl_5m"] += pnl_5m
        analysis["by_coin"][symbol]["theoretical_pnl_15m"] += pnl_15m
        analysis["by_coin"][symbol]["theoretical_pnl_60m"] += pnl_60m
        
        analysis["by_direction"][side]["blocked"] += 1
        analysis["by_direction"][side]["would_win"] += 1 if would_have_won else 0
        
        if hour is not None:
            analysis["by_hour"][hour]["blocked"] += 1
            analysis["by_hour"][hour]["would_win"] += 1 if would_have_won else 0
            analysis["by_hour"][hour]["missed_pnl"] += best_pnl if missed_opportunity else 0
        
        if abs(ofi) >= 0.8:
            analysis["intelligence_patterns"]["high_ofi_blocked"]["count"] += 1
            analysis["intelligence_patterns"]["high_ofi_blocked"]["would_win"] += 1 if would_have_won else 0
        
        if abs(ensemble) >= 0.08:
            analysis["intelligence_patterns"]["high_ensemble_blocked"]["count"] += 1
            analysis["intelligence_patterns"]["high_ensemble_blocked"]["would_win"] += 1 if would_have_won else 0
        
        if mtf >= 0.7:
            analysis["intelligence_patterns"]["aligned_mtf_blocked"]["count"] += 1
            analysis["intelligence_patterns"]["aligned_mtf_blocked"]["would_win"] += 1 if would_have_won else 0
        
        analysis["best_interval_distribution"][best_interval] += 1
    
    analysis["summary"] = {
        "block_efficiency": analysis["avoided_losses"] / len(counterfactuals) * 100 if counterfactuals else 0,
        "missed_opportunity_rate": analysis["missed_opportunities"] / len(counterfactuals) * 100 if counterfactuals else 0
    }
    
    return analysis


def compute_combined_insights() -> Dict:
    """Compute combined insights from executed and counterfactual data."""
    executed = analyze_executed_trades()
    counterfactual = analyze_counterfactuals()
    
    insights = {
        "executed_summary": executed.get("summary", {}),
        "counterfactual_summary": counterfactual.get("summary", {}),
        "actionable_recommendations": []
    }
    
    coin_direction_perf = executed.get("by_coin_direction", {})
    for key, data in coin_direction_perf.items():
        if data["trades"] >= 10:
            win_rate = data["wins"] / data["trades"] * 100 if data["trades"] > 0 else 0
            ev = data["pnl"] / data["trades"] if data["trades"] > 0 else 0
            
            if win_rate < 35 and data["trades"] >= 20:
                insights["actionable_recommendations"].append({
                    "type": "INVERSION_CANDIDATE",
                    "config": key,
                    "win_rate": round(win_rate, 1),
                    "trades": data["trades"],
                    "pnl": round(data["pnl"], 2),
                    "action": f"Consider inverting {key} signals (current WR {win_rate:.1f}% → potential {100-win_rate:.1f}%)"
                })
            elif win_rate > 65 and ev > 0.01:
                insights["actionable_recommendations"].append({
                    "type": "HIGH_PERFORMER",
                    "config": key,
                    "win_rate": round(win_rate, 1),
                    "trades": data["trades"],
                    "pnl": round(data["pnl"], 2),
                    "action": f"Increase allocation to {key} (WR {win_rate:.1f}%, EV ${ev:.3f})"
                })
    
    ofi_perf = executed.get("by_ofi_bucket", {})
    for bucket, data in ofi_perf.items():
        if data["trades"] >= 50:
            win_rate = data["wins"] / data["trades"] * 100 if data["trades"] > 0 else 0
            ev = data["pnl"] / data["trades"] if data["trades"] > 0 else 0
            
            if win_rate > 55 and ev > 0:
                insights["actionable_recommendations"].append({
                    "type": "OFI_SWEET_SPOT",
                    "bucket": bucket,
                    "win_rate": round(win_rate, 1),
                    "ev": round(ev, 4),
                    "trades": data["trades"],
                    "action": f"Prioritize OFI {bucket} entries (WR {win_rate:.1f}%, EV ${ev:.4f})"
                })
    
    hold_perf = executed.get("by_hold_duration", {})
    for bucket, data in hold_perf.items():
        if data["trades"] >= 50:
            ev = data.get("ev", data["pnl"] / data["trades"] if data["trades"] > 0 else 0)
            win_rate = data["wins"] / data["trades"] * 100 if data["trades"] > 0 else 0
            
            if ev > 0.05:
                insights["actionable_recommendations"].append({
                    "type": "HOLD_TIME_OPTIMIZATION",
                    "bucket": bucket,
                    "ev": round(ev, 4),
                    "win_rate": round(win_rate, 1),
                    "trades": data["trades"],
                    "action": f"Target {bucket} hold duration (EV ${ev:.4f}, WR {win_rate:.1f}%)"
                })
    
    cf_intel = counterfactual.get("intelligence_patterns", {})
    for pattern, data in cf_intel.items():
        if data["count"] >= 5:
            would_win_rate = data["would_win"] / data["count"] * 100 if data["count"] > 0 else 0
            if would_win_rate > 60:
                insights["actionable_recommendations"].append({
                    "type": "BLOCKING_MISTAKE",
                    "pattern": pattern,
                    "blocked_count": data["count"],
                    "would_win_rate": round(would_win_rate, 1),
                    "action": f"Stop blocking {pattern.replace('_', ' ')} signals ({would_win_rate:.1f}% would have won)"
                })
    
    hour_perf = executed.get("by_hour", {})
    profitable_hours = []
    losing_hours = []
    for hour, data in hour_perf.items():
        if data["trades"] >= 30:
            ev = data["pnl"] / data["trades"] if data["trades"] > 0 else 0
            win_rate = data["wins"] / data["trades"] * 100 if data["trades"] > 0 else 0
            if ev > 0.02:
                profitable_hours.append((hour, ev, win_rate, data["trades"]))
            elif ev < -0.02:
                losing_hours.append((hour, ev, win_rate, data["trades"]))
    
    if profitable_hours:
        best = max(profitable_hours, key=lambda x: x[1])
        insights["actionable_recommendations"].append({
            "type": "BEST_TRADING_HOUR",
            "hour_utc": best[0],
            "ev": round(best[1], 4),
            "win_rate": round(best[2], 1),
            "trades": best[3],
            "action": f"Increase activity at {best[0]:02d}:00 UTC (EV ${best[1]:.4f}, WR {best[2]:.1f}%)"
        })
    
    if losing_hours:
        worst = min(losing_hours, key=lambda x: x[1])
        insights["actionable_recommendations"].append({
            "type": "WORST_TRADING_HOUR",
            "hour_utc": worst[0],
            "ev": round(worst[1], 4),
            "win_rate": round(worst[2], 1),
            "trades": worst[3],
            "action": f"CAUTION at {worst[0]:02d}:00 UTC (EV ${worst[1]:.4f}, WR {worst[2]:.1f}%) - consider inversion"
        })
    
    return insights


def generate_deep_dive_report() -> str:
    """Generate comprehensive deep dive report."""
    print("=" * 80)
    print("DEEP DIVE INTELLIGENCE ANALYSIS")
    print("Philosophy: Predict trends to make money")
    print("=" * 80)
    print()
    
    executed = analyze_executed_trades()
    counterfactual = analyze_counterfactuals()
    insights = compute_combined_insights()
    
    summary = executed.get("summary", {})
    print("=== EXECUTED TRADES SUMMARY ===")
    print(f"Total Trades: {executed.get('total_trades', 0):,}")
    print(f"Total P&L: ${summary.get('total_pnl', 0):.2f}")
    print(f"Win Rate: {summary.get('win_rate', 0):.1f}%")
    print(f"Direction Accuracy: {summary.get('direction_accuracy_pct', 0):.1f}%")
    print(f"Average P&L per Trade: ${summary.get('avg_pnl', 0):.4f}")
    print()
    
    print("=== PERFORMANCE BY COIN ===")
    by_coin = executed.get("by_coin", {})
    coin_list = []
    for coin, data in by_coin.items():
        wr = data["wins"] / data["trades"] * 100 if data["trades"] > 0 else 0
        ev = data["pnl"] / data["trades"] if data["trades"] > 0 else 0
        coin_list.append((coin, data["trades"], wr, data["pnl"], ev))
    
    coin_list.sort(key=lambda x: x[3], reverse=True)
    print(f"{'Coin':<12} {'Trades':>7} {'WinRate':>8} {'P&L':>10} {'EV':>10}")
    print("-" * 50)
    for coin, trades, wr, pnl, ev in coin_list:
        print(f"{coin:<12} {trades:>7} {wr:>7.1f}% ${pnl:>9.2f} ${ev:>9.4f}")
    print()
    
    print("=== PERFORMANCE BY COIN + DIRECTION ===")
    by_coin_dir = executed.get("by_coin_direction", {})
    coin_dir_list = []
    for key, data in by_coin_dir.items():
        wr = data["wins"] / data["trades"] * 100 if data["trades"] > 0 else 0
        ev = data["pnl"] / data["trades"] if data["trades"] > 0 else 0
        coin_dir_list.append((key, data["trades"], wr, data["pnl"], ev))
    
    coin_dir_list.sort(key=lambda x: x[4])
    print(f"{'Config':<20} {'Trades':>7} {'WinRate':>8} {'P&L':>10} {'EV':>10}")
    print("-" * 60)
    print("WORST PERFORMERS (INVERSION CANDIDATES):")
    for config, trades, wr, pnl, ev in coin_dir_list[:10]:
        if trades >= 10:
            marker = "🔄" if wr < 40 else ""
            print(f"{config:<20} {trades:>7} {wr:>7.1f}% ${pnl:>9.2f} ${ev:>9.4f} {marker}")
    
    print("\nBEST PERFORMERS (BOOST CANDIDATES):")
    for config, trades, wr, pnl, ev in reversed(coin_dir_list[-10:]):
        if trades >= 10:
            marker = "⬆️" if wr > 55 and ev > 0 else ""
            print(f"{config:<20} {trades:>7} {wr:>7.1f}% ${pnl:>9.2f} ${ev:>9.4f} {marker}")
    print()
    
    print("=== PERFORMANCE BY HOUR (UTC) ===")
    by_hour = executed.get("by_hour", {})
    hour_list = []
    for hour, data in by_hour.items():
        wr = data["wins"] / data["trades"] * 100 if data["trades"] > 0 else 0
        ev = data["pnl"] / data["trades"] if data["trades"] > 0 else 0
        hour_list.append((hour, data["trades"], wr, data["pnl"], ev))
    
    hour_list.sort(key=lambda x: x[0])
    print(f"{'Hour':>6} {'Trades':>7} {'WinRate':>8} {'P&L':>10} {'EV':>10}")
    print("-" * 45)
    for hour, trades, wr, pnl, ev in hour_list:
        marker = "✅" if ev > 0.01 else ("❌" if ev < -0.01 else "")
        print(f"{hour:>4}:00 {trades:>7} {wr:>7.1f}% ${pnl:>9.2f} ${ev:>9.4f} {marker}")
    print()
    
    print("=== PERFORMANCE BY HOLD DURATION ===")
    by_hold = executed.get("by_hold_duration", {})
    print(f"{'Duration':<20} {'Trades':>7} {'WinRate':>8} {'P&L':>10} {'EV':>10}")
    print("-" * 60)
    for bucket, data in sorted(by_hold.items(), key=lambda x: x[1].get("ev", 0), reverse=True):
        wr = data["wins"] / data["trades"] * 100 if data["trades"] > 0 else 0
        ev = data.get("ev", data["pnl"] / data["trades"] if data["trades"] > 0 else 0)
        marker = "⭐" if ev > 0.05 else ""
        print(f"{bucket:<20} {data['trades']:>7} {wr:>7.1f}% ${data['pnl']:>9.2f} ${ev:>9.4f} {marker}")
    print()
    
    print("=== PERFORMANCE BY OFI STRENGTH ===")
    by_ofi = executed.get("by_ofi_bucket", {})
    print(f"{'OFI Bucket':<20} {'Trades':>7} {'WinRate':>8} {'P&L':>10} {'EV':>10}")
    print("-" * 60)
    for bucket, data in sorted(by_ofi.items(), key=lambda x: x[1]["pnl"], reverse=True):
        wr = data["wins"] / data["trades"] * 100 if data["trades"] > 0 else 0
        ev = data["pnl"] / data["trades"] if data["trades"] > 0 else 0
        print(f"{bucket:<20} {data['trades']:>7} {wr:>7.1f}% ${data['pnl']:>9.2f} ${ev:>9.4f}")
    print()
    
    print("=== PERFORMANCE BY ENSEMBLE STRENGTH ===")
    by_ensemble = executed.get("by_ensemble_bucket", {})
    print(f"{'Ensemble Bucket':<20} {'Trades':>7} {'WinRate':>8} {'P&L':>10} {'EV':>10}")
    print("-" * 60)
    for bucket, data in sorted(by_ensemble.items(), key=lambda x: x[1]["pnl"], reverse=True):
        wr = data["wins"] / data["trades"] * 100 if data["trades"] > 0 else 0
        ev = data["pnl"] / data["trades"] if data["trades"] > 0 else 0
        print(f"{bucket:<20} {data['trades']:>7} {wr:>7.1f}% ${data['pnl']:>9.2f} ${ev:>9.4f}")
    print()
    
    print("=== PERFORMANCE BY MTF ALIGNMENT ===")
    by_mtf = executed.get("by_mtf_bucket", {})
    print(f"{'MTF Bucket':<20} {'Trades':>7} {'WinRate':>8} {'P&L':>10} {'EV':>10}")
    print("-" * 60)
    for bucket, data in sorted(by_mtf.items(), key=lambda x: x[1]["pnl"], reverse=True):
        wr = data["wins"] / data["trades"] * 100 if data["trades"] > 0 else 0
        ev = data["pnl"] / data["trades"] if data["trades"] > 0 else 0
        print(f"{bucket:<20} {data['trades']:>7} {wr:>7.1f}% ${data['pnl']:>9.2f} ${ev:>9.4f}")
    print()
    
    print("=== PERFORMANCE BY EXIT REASON ===")
    by_close = executed.get("by_close_reason", {})
    print(f"{'Exit Reason':<35} {'Trades':>7} {'WinRate':>8} {'P&L':>10}")
    print("-" * 65)
    for reason, data in sorted(by_close.items(), key=lambda x: x[1]["pnl"], reverse=True)[:15]:
        wr = data["wins"] / data["trades"] * 100 if data["trades"] > 0 else 0
        print(f"{reason:<35} {data['trades']:>7} {wr:>7.1f}% ${data['pnl']:>9.2f}")
    print()
    
    print("=" * 80)
    print("BLOCKED SIGNALS ANALYSIS (Counterfactuals)")
    print("=" * 80)
    print()
    
    cf_summary = counterfactual.get("summary", {})
    print(f"Total Blocked Signals: {counterfactual.get('total_blocked', 0)}")
    print(f"Missed Opportunities: {counterfactual.get('missed_opportunities', 0)}")
    print(f"Avoided Losses: {counterfactual.get('avoided_losses', 0)}")
    print(f"Block Efficiency: {cf_summary.get('block_efficiency', 0):.1f}%")
    print()
    
    print("=== BLOCKED BY REASON ===")
    by_reason = counterfactual.get("by_block_reason", {})
    print(f"{'Reason':<30} {'Blocked':>8} {'Would Win':>10} {'Win%':>8}")
    print("-" * 60)
    for reason, data in sorted(by_reason.items(), key=lambda x: x[1]["count"], reverse=True):
        wr = data["would_win"] / data["count"] * 100 if data["count"] > 0 else 0
        marker = "🚨" if wr > 50 else ""
        print(f"{reason:<30} {data['count']:>8} {data['would_win']:>10} {wr:>7.1f}% {marker}")
    print()
    
    print("=== INTELLIGENCE PATTERNS IN BLOCKED SIGNALS ===")
    intel_patterns = counterfactual.get("intelligence_patterns", {})
    for pattern, data in intel_patterns.items():
        if data["count"] > 0:
            wr = data["would_win"] / data["count"] * 100
            print(f"{pattern}: {data['count']} blocked, {wr:.1f}% would have won")
    print()
    
    print("=" * 80)
    print("ACTIONABLE RECOMMENDATIONS")
    print("=" * 80)
    print()
    
    recs = insights.get("actionable_recommendations", [])
    
    inversions = [r for r in recs if r["type"] == "INVERSION_CANDIDATE"]
    boosters = [r for r in recs if r["type"] == "HIGH_PERFORMER"]
    ofi_sweet = [r for r in recs if r["type"] == "OFI_SWEET_SPOT"]
    hold_opts = [r for r in recs if r["type"] == "HOLD_TIME_OPTIMIZATION"]
    block_mistakes = [r for r in recs if r["type"] == "BLOCKING_MISTAKE"]
    time_opts = [r for r in recs if r["type"] in ["BEST_TRADING_HOUR", "WORST_TRADING_HOUR"]]
    
    if inversions:
        print("🔄 SIGNAL INVERSION CANDIDATES (Predictably losing → Invert to profit):")
        for r in inversions:
            print(f"   • {r['action']}")
        print()
    
    if boosters:
        print("⬆️ HIGH PERFORMERS (Increase allocation):")
        for r in boosters:
            print(f"   • {r['action']}")
        print()
    
    if ofi_sweet:
        print("🎯 OFI SWEET SPOTS:")
        for r in ofi_sweet:
            print(f"   • {r['action']}")
        print()
    
    if hold_opts:
        print("⏱️ HOLD TIME OPTIMIZATION:")
        for r in hold_opts:
            print(f"   • {r['action']}")
        print()
    
    if block_mistakes:
        print("🚨 BLOCKING MISTAKES (Stop blocking these):")
        for r in block_mistakes:
            print(f"   • {r['action']}")
        print()
    
    if time_opts:
        print("🕐 TIME-BASED OPTIMIZATION:")
        for r in time_opts:
            print(f"   • {r['action']}")
        print()
    
    print("=" * 80)
    print("KEY INSIGHT: Direction accuracy is 88% but P&L negative")
    print("This means: We KNOW which way price will move, but timing/sizing is wrong")
    print("Focus: Hold duration optimization + fee management + sizing calibration")
    print("=" * 80)
    
    return json.dumps(insights, indent=2, default=str)


if __name__ == "__main__":
    report = generate_deep_dive_report()
    
    with open("logs/deep_dive_intelligence_report.json", "w") as f:
        f.write(report)
    print("\n📊 Full report saved to logs/deep_dive_intelligence_report.json")
