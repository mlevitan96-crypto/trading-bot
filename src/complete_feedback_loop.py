#!/usr/bin/env python3
"""
COMPLETE FEEDBACK LOOP - Comprehensive Decision Review System

This module ensures we learn from EVERY decision by:
1. Reviewing every exit: Did we exit too early? Too late?
2. Reviewing every entry: Was the opposite direction better?
3. Tracking price after exit: How much did we leave on the table?
4. Auto-updating timing rules based on learned optimal hold durations
5. Generating actionable recommendations for future trades

Key Philosophy: Every decision generates both actual and counterfactual outcomes.
We learn from what we did AND what we could have done.
"""

import json
import os
import time
from datetime import datetime, timedelta
from collections import defaultdict
from typing import Dict, List, Any, Optional, Tuple
from pathlib import Path

try:
    from src.data_registry import DataRegistry as DR
except ImportError:
    import sys
    sys.path.insert(0, '/home/runner/workspace')
    from src.data_registry import DataRegistry as DR

LOGS_DIR = Path("logs")
FEATURE_STORE = Path("feature_store")
CONFIGS_DIR = Path("configs")

TIMING_RULES_PATH = FEATURE_STORE / "timing_rules.json"
EXIT_COUNTERFACTUALS_PATH = LOGS_DIR / "exit_counterfactuals.jsonl"
DIRECTION_COUNTERFACTUALS_PATH = LOGS_DIR / "direction_counterfactuals.jsonl"
FEEDBACK_SUMMARY_PATH = FEATURE_STORE / "feedback_loop_summary.json"
POSITION_TIMING_PATH = LOGS_DIR / "position_timing.jsonl"
ENRICHED_DECISIONS_PATH = LOGS_DIR / "enriched_decisions.jsonl"

DURATION_BUCKETS = {
    "flash": (0, 60),
    "quick": (60, 300),
    "short": (300, 900),
    "medium": (900, 3600),
    "extended": (3600, 14400),
    "long": (14400, float('inf'))
}


def load_jsonl(path: str) -> List[Dict]:
    """Load JSONL file."""
    records = []
    if not os.path.exists(path):
        return records
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


def save_json(path: str, data: Dict):
    """Save JSON atomically."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = str(path) + ".tmp"
    with open(tmp, 'w') as f:
        json.dump(data, f, indent=2)
    os.replace(tmp, path)


def append_jsonl(path: str, record: Dict):
    """Append to JSONL file."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'a') as f:
        f.write(json.dumps(record, default=str) + "\n")


def get_price_at_time(symbol: str, target_ts: float) -> Optional[float]:
    """Get price at a specific timestamp (from candle data)."""
    try:
        from src.exchange_gateway import ExchangeGateway
        gw = ExchangeGateway()
        return gw.get_price(symbol, venue="futures")
    except:
        return None


def get_price_path_after_exit(symbol: str, exit_ts: float, 
                               durations_minutes: List[int] = [5, 15, 30, 60]) -> Dict[int, Optional[float]]:
    """Get price at various intervals after exit to evaluate if we exited too early."""
    prices = {}
    try:
        from src.exchange_gateway import ExchangeGateway
        gw = ExchangeGateway()
        df = gw.fetch_ohlcv(symbol, timeframe="1m", limit=120, venue="futures")
        if df is not None and len(df) > 0:
            current_price = float(df['close'].iloc[-1])
            for mins in durations_minutes:
                prices[mins] = current_price
    except:
        for mins in durations_minutes:
            prices[mins] = None
    return prices


def classify_duration(duration_sec: float) -> str:
    """Classify duration into bucket."""
    for bucket, (min_s, max_s) in DURATION_BUCKETS.items():
        if min_s <= duration_sec < max_s:
            return bucket
    return "long"


def analyze_exit_timing() -> Dict[str, Any]:
    """
    Analyze all closed positions to determine if we exited too early or too late.
    
    For each trade:
    - What was the price path after we exited?
    - Did the price continue in our favor? (exited too early)
    - Did the price reverse against us right after? (perfect exit)
    - Did we give back profits by holding too long? (exited too late)
    """
    timing_data = load_jsonl(str(POSITION_TIMING_PATH))
    
    if not timing_data:
        return {"status": "no_data", "message": "No position timing data available"}
    
    exit_analysis = {
        "total_analyzed": 0,
        "exited_too_early": [],
        "exited_too_late": [],
        "good_exits": [],
        "by_duration_bucket": defaultdict(lambda: {"too_early": 0, "too_late": 0, "good": 0, "total_pnl": 0, "n": 0})
    }
    
    for trade in timing_data[-200:]:
        symbol = trade.get("symbol")
        side = trade.get("side", "LONG")
        exit_price = trade.get("exit_price", 0)
        entry_price = trade.get("entry_price", 0)
        pnl_usd = trade.get("pnl_usd", 0)
        hold_duration = trade.get("hold_duration_sec", 0)
        duration_bucket = trade.get("duration_bucket", classify_duration(hold_duration))
        exit_alignment = trade.get("exit_alignment", 0.5)
        entry_alignment = trade.get("entry_alignment", 0.5)
        
        if not exit_price or not entry_price:
            continue
        
        exit_analysis["total_analyzed"] += 1
        
        bucket_stats = exit_analysis["by_duration_bucket"][duration_bucket]
        bucket_stats["n"] += 1
        bucket_stats["total_pnl"] += pnl_usd
        
        alignment_dropped = exit_alignment < entry_alignment - 0.25
        if pnl_usd > 0 and alignment_dropped:
            bucket_stats["good"] += 1
            exit_analysis["good_exits"].append({
                "symbol": symbol, "side": side, "pnl": pnl_usd,
                "duration": duration_bucket, "reason": "profit_locked_on_alignment_drop"
            })
        elif pnl_usd < 0 and hold_duration < 300:
            bucket_stats["too_early"] += 1
            exit_analysis["exited_too_early"].append({
                "symbol": symbol, "side": side, "pnl": pnl_usd,
                "duration": duration_bucket, "reason": "quick_loss_might_have_recovered"
            })
        elif pnl_usd < 0 and hold_duration > 1800:
            bucket_stats["too_late"] += 1
            exit_analysis["exited_too_late"].append({
                "symbol": symbol, "side": side, "pnl": pnl_usd,
                "duration": duration_bucket, "reason": "held_through_reversal"
            })
        else:
            bucket_stats["good"] += 1
    
    exit_analysis["by_duration_bucket"] = dict(exit_analysis["by_duration_bucket"])
    
    return exit_analysis


def analyze_direction_counterfactuals() -> Dict[str, Any]:
    """
    For every trade, compute what the OPPOSITE direction would have earned.
    This helps identify systematic directional bias in our signals.
    """
    timing_data = load_jsonl(str(POSITION_TIMING_PATH))
    
    if not timing_data:
        return {"status": "no_data"}
    
    direction_analysis = {
        "total_analyzed": 0,
        "opposite_would_be_better": 0,
        "our_direction_better": 0,
        "by_symbol": defaultdict(lambda: {"same_better": 0, "opposite_better": 0, "same_pnl": 0, "opposite_pnl": 0}),
        "direction_bias_score": {}
    }
    
    for trade in timing_data[-200:]:
        symbol = trade.get("symbol")
        side = trade.get("side", "LONG")
        entry_price = trade.get("entry_price", 0)
        exit_price = trade.get("exit_price", 0)
        pnl_usd = trade.get("pnl_usd", 0)
        
        if not entry_price or not exit_price:
            continue
        
        direction_analysis["total_analyzed"] += 1
        
        price_move_pct = (exit_price - entry_price) / entry_price * 100
        
        if side.upper() == "LONG":
            our_pnl_pct = price_move_pct
            opposite_pnl_pct = -price_move_pct
        else:
            our_pnl_pct = -price_move_pct
            opposite_pnl_pct = price_move_pct
        
        sym_stats = direction_analysis["by_symbol"][symbol]
        sym_stats["same_pnl"] += our_pnl_pct
        sym_stats["opposite_pnl"] += opposite_pnl_pct
        
        if opposite_pnl_pct > our_pnl_pct:
            direction_analysis["opposite_would_be_better"] += 1
            sym_stats["opposite_better"] += 1
        else:
            direction_analysis["our_direction_better"] += 1
            sym_stats["same_better"] += 1
    
    for symbol, stats in direction_analysis["by_symbol"].items():
        total = stats["same_better"] + stats["opposite_better"]
        if total > 0:
            direction_analysis["direction_bias_score"][symbol] = {
                "our_direction_accuracy": round(stats["same_better"] / total * 100, 1),
                "opposite_would_be_better_pct": round(stats["opposite_better"] / total * 100, 1),
                "net_pnl_advantage": round(stats["same_pnl"] - stats["opposite_pnl"], 2)
            }
    
    direction_analysis["by_symbol"] = dict(direction_analysis["by_symbol"])
    
    return direction_analysis


def learn_optimal_hold_durations() -> Dict[str, Any]:
    """
    Analyze position timing data to learn optimal hold durations per pattern.
    Updates timing_rules.json with evidence-based recommendations.
    """
    timing_data = load_jsonl(str(POSITION_TIMING_PATH))
    
    if len(timing_data) < 10:
        return {"status": "insufficient_data", "count": len(timing_data)}
    
    pattern_outcomes = defaultdict(lambda: defaultdict(lambda: {"pnl": 0, "n": 0, "wins": 0}))
    
    for trade in timing_data:
        symbol = trade.get("symbol", "UNK")
        side = trade.get("side", "UNK")
        duration_bucket = trade.get("duration_bucket", "unknown")
        pnl = trade.get("pnl_usd", 0)
        
        signal_ctx = trade.get("signal_ctx", {})
        ofi = signal_ctx.get("ofi", 0.5)
        
        if ofi < 0.25:
            ofi_bucket = "weak"
        elif ofi < 0.5:
            ofi_bucket = "moderate"
        elif ofi < 0.75:
            ofi_bucket = "strong"
        elif ofi < 0.9:
            ofi_bucket = "very_strong"
        else:
            ofi_bucket = "extreme"
        
        pattern_key = f"{symbol}|{side}|{ofi_bucket}"
        
        pattern_outcomes[pattern_key][duration_bucket]["pnl"] += pnl
        pattern_outcomes[pattern_key][duration_bucket]["n"] += 1
        if pnl > 0:
            pattern_outcomes[pattern_key][duration_bucket]["wins"] += 1
    
    timing_rules = {}
    
    for pattern_key, durations in pattern_outcomes.items():
        best_bucket = None
        best_ev = float('-inf')
        
        for dur_bucket, stats in durations.items():
            if stats["n"] >= 3:
                ev = stats["pnl"] / stats["n"]
                if ev > best_ev:
                    best_ev = ev
                    best_bucket = dur_bucket
        
        if best_bucket and best_bucket != "unknown":
            bucket_range = DURATION_BUCKETS.get(best_bucket, (900, 3600))
            wr = durations[best_bucket]["wins"] / durations[best_bucket]["n"] * 100 if durations[best_bucket]["n"] > 0 else 0
            
            timing_rules[pattern_key] = {
                "optimal_duration": best_bucket,
                "min_hold_sec": bucket_range[0],
                "max_hold_sec": bucket_range[1],
                "expected_ev": round(best_ev, 4),
                "n": durations[best_bucket]["n"],
                "wr": round(wr, 1),
                "all_durations": {k: {"pnl": round(v["pnl"], 2), "n": v["n"]} for k, v in durations.items()}
            }
    
    timing_rules["default"] = {
        "optimal_duration": "medium",
        "min_hold_sec": 900,
        "max_hold_sec": 3600,
        "expected_ev": 0,
        "n": 0
    }
    
    timing_rules["_metadata"] = {
        "updated_at": datetime.now().isoformat(),
        "total_trades_analyzed": len(timing_data),
        "patterns_learned": len(timing_rules) - 2
    }
    
    save_json(str(TIMING_RULES_PATH), timing_rules)
    
    return {
        "status": "SUCCESS",
        "patterns_learned": len(timing_rules) - 2,
        "total_trades_analyzed": len(timing_data),
        "rules": timing_rules
    }


def generate_improvement_recommendations() -> List[Dict[str, Any]]:
    """
    Analyze all feedback data and generate actionable recommendations.
    """
    recommendations = []
    
    exit_analysis = analyze_exit_timing()
    if exit_analysis.get("total_analyzed", 0) > 0:
        too_early_count = len(exit_analysis.get("exited_too_early", []))
        too_late_count = len(exit_analysis.get("exited_too_late", []))
        
        if too_early_count > too_late_count * 2:
            recommendations.append({
                "type": "exit_timing",
                "priority": "high",
                "issue": f"Exiting too early ({too_early_count} vs {too_late_count} too late)",
                "action": "Increase R/R targets and hold times",
                "config_change": {"ladder_exit_policies.json": {"rr_targets": [2.5, 4.0]}}
            })
        elif too_late_count > too_early_count * 2:
            recommendations.append({
                "type": "exit_timing",
                "priority": "high",
                "issue": f"Holding too long ({too_late_count} vs {too_early_count} too early)",
                "action": "Tighten trailing stops and reduce hold times",
                "config_change": {"ladder_exit_policies.json": {"trail_atr_mult": 1.5}}
            })
        
        for bucket, stats in exit_analysis.get("by_duration_bucket", {}).items():
            if stats["n"] >= 5:
                ev = stats["total_pnl"] / stats["n"]
                if ev > 0.5:
                    recommendations.append({
                        "type": "duration_optimization",
                        "priority": "medium",
                        "issue": f"{bucket} duration is profitable (EV=${ev:.2f})",
                        "action": f"Prioritize {bucket} hold times for similar setups",
                        "duration_bucket": bucket,
                        "expected_ev": round(ev, 2)
                    })
                elif ev < -1.0:
                    recommendations.append({
                        "type": "duration_optimization",
                        "priority": "high",
                        "issue": f"{bucket} duration is losing (EV=${ev:.2f})",
                        "action": f"Avoid {bucket} hold times - exit earlier or later",
                        "duration_bucket": bucket,
                        "expected_ev": round(ev, 2)
                    })
    
    direction_analysis = analyze_direction_counterfactuals()
    if direction_analysis.get("total_analyzed", 0) > 0:
        opposite_better = direction_analysis.get("opposite_would_be_better", 0)
        our_better = direction_analysis.get("our_direction_better", 0)
        total = opposite_better + our_better
        
        if total > 0:
            opposite_pct = opposite_better / total * 100
            if opposite_pct > 60:
                recommendations.append({
                    "type": "direction_bias",
                    "priority": "critical",
                    "issue": f"Wrong direction {opposite_pct:.0f}% of the time",
                    "action": "Review signal generation logic - consider signal inversion",
                    "opposite_better_pct": round(opposite_pct, 1)
                })
        
        for symbol, bias in direction_analysis.get("direction_bias_score", {}).items():
            if bias.get("opposite_would_be_better_pct", 0) > 70:
                recommendations.append({
                    "type": "symbol_direction_bias",
                    "priority": "high",
                    "symbol": symbol,
                    "issue": f"{symbol}: Opposite direction better {bias['opposite_would_be_better_pct']:.0f}% of time",
                    "action": f"Consider signal inversion for {symbol}"
                })
    
    return recommendations


MIN_TRADES_FOR_EXIT_TIMING_CHANGE = 50
MIN_TRADES_FOR_DIRECTION_INVERSION = 20
MIN_OPPOSITE_BETTER_PCT_FOR_INVERSION = 70
MIN_HOURS_OF_DATA_REQUIRED = 48


def update_exit_weights_from_timing_analysis(exit_analysis: Dict) -> Dict[str, Any]:
    """
    Update exit signal weights based on timing analysis results.
    - If exiting too early frequently, boost hold_duration weight
    - If exiting too late frequently, boost trailing_stop and momentum_reversal
    """
    try:
        from src.weighted_signal_fusion import WeightedSignalFusion, EXIT_WEIGHTS_PATH
        from src.weighted_signal_fusion import normalize_weights, MIN_WEIGHT, MAX_WEIGHT, save_json
        
        fusion = WeightedSignalFusion()
        weights = fusion.exit_weights.copy()
        adjustments = []
        
        too_early = exit_analysis.get('too_early_count', 0)
        too_late = exit_analysis.get('too_late_count', 0)
        total = exit_analysis.get('total_analyzed', 0)
        
        if total < 20:
            return {"status": "skipped", "reason": f"need 20+ trades, have {total}"}
        
        early_pct = too_early / total if total > 0 else 0
        late_pct = too_late / total if total > 0 else 0
        
        if early_pct > 0.5:
            weights['hold_duration'] = min(weights.get('hold_duration', 0.15) * 1.15, MAX_WEIGHT)
            weights['unrealized_pnl'] = max(weights.get('unrealized_pnl', 0.25) * 0.90, MIN_WEIGHT)
            adjustments.append(f"hold_duration +15%, unrealized_pnl -10% (early exit rate: {early_pct*100:.0f}%)")
        
        if late_pct > 0.3:
            weights['trailing_stop'] = min(weights.get('trailing_stop', 0.10) * 1.20, MAX_WEIGHT)
            weights['momentum_reversal'] = min(weights.get('momentum_reversal', 0.10) * 1.15, MAX_WEIGHT)
            adjustments.append(f"trailing_stop +20%, momentum_reversal +15% (late exit rate: {late_pct*100:.0f}%)")
        
        duration_stats = exit_analysis.get('by_duration', {})
        best_duration = max(duration_stats.items(), key=lambda x: x[1].get('ev', float('-inf')), default=(None, {}))
        
        if best_duration[0] and best_duration[1].get('ev', 0) > 0.1:
            weights['hold_duration'] = min(weights.get('hold_duration', 0.15) * 1.05, MAX_WEIGHT)
            adjustments.append(f"hold_duration +5% (best duration: {best_duration[0]} EV=${best_duration[1].get('ev', 0):.2f})")
        
        if adjustments:
            weights = normalize_weights(weights)
            save_json(EXIT_WEIGHTS_PATH, {
                "weights": weights,
                "updated_at": datetime.utcnow().isoformat(),
                "adjustments": adjustments,
                "source": "complete_feedback_loop",
                "analysis": {
                    "too_early_pct": early_pct,
                    "too_late_pct": late_pct,
                    "total_trades": total
                }
            })
            return {"status": "updated", "adjustments": adjustments, "weights": weights}
        
        return {"status": "no_changes", "reason": "performance within bounds"}
    
    except Exception as e:
        return {"status": "error", "error": str(e)}

def get_data_time_span_hours() -> float:
    """
    Calculate the time span of our position timing data in hours.
    Returns 0 if no data or insufficient data.
    """
    timing_data = load_jsonl(str(POSITION_TIMING_PATH))
    if len(timing_data) < 2:
        return 0
    
    try:
        timestamps = []
        for trade in timing_data:
            ts = trade.get("entry_timestamp") or trade.get("exit_timestamp")
            if ts:
                timestamps.append(datetime.fromisoformat(ts.replace('Z', '+00:00')))
        
        if len(timestamps) < 2:
            return 0
        
        time_span = max(timestamps) - min(timestamps)
        return time_span.total_seconds() / 3600
    except:
        return 0


def auto_apply_recommendations(recommendations: List[Dict], 
                                 exit_analysis: Dict = None,
                                 direction_analysis: Dict = None) -> Dict[str, Any]:
    """
    Automatically apply high-priority recommendations to config files.
    Only applies changes when we have sufficient confidence:
    - Enough trades (statistical significance)
    - Enough time span (avoid noise from short windows)
    
    Returns summary of what was changed.
    """
    applied = []
    
    data_hours = get_data_time_span_hours()
    if data_hours < MIN_HOURS_OF_DATA_REQUIRED:
        print(f"   ⏭️ AUTO-APPLY DISABLED: Need {MIN_HOURS_OF_DATA_REQUIRED}h+ of data, have {data_hours:.1f}h")
        return {"applied": [], "count": 0, "reason": f"insufficient_time_span:{data_hours:.1f}h"}
    
    for rec in recommendations:
        priority = rec.get('priority', 'medium')
        rec_type = rec.get('type', '')
        
        if priority != 'high' and priority != 'critical':
            continue
        
        if rec_type == 'exit_timing' and rec.get('config_change'):
            total_analyzed = exit_analysis.get('total_analyzed', 0) if exit_analysis else 0
            if total_analyzed < MIN_TRADES_FOR_EXIT_TIMING_CHANGE:
                applied.append({
                    "type": rec_type,
                    "status": "skipped",
                    "reason": f"Need {MIN_TRADES_FOR_EXIT_TIMING_CHANGE}+ trades, have {total_analyzed}"
                })
                print(f"   ⏭️ SKIPPED: Exit timing change - need {MIN_TRADES_FOR_EXIT_TIMING_CHANGE}+ trades (have {total_analyzed})")
                continue
            
            try:
                config_changes = rec.get('config_change', {})
                for config_file, updates in config_changes.items():
                    config_path = CONFIGS_DIR / config_file
                    if config_path.exists():
                        with open(config_path, 'r') as f:
                            config = json.load(f)
                        
                        if 'defaults' in config:
                            config['defaults'].update(updates)
                        else:
                            config.update(updates)
                        
                        save_json(str(config_path), config)
                        applied.append({
                            "type": rec_type,
                            "file": config_file,
                            "changes": updates,
                            "status": "applied",
                            "sample_size": total_analyzed
                        })
                        print(f"   ✅ AUTO-APPLIED: Updated {config_file} with {updates} (n={total_analyzed})")
            except Exception as e:
                applied.append({"type": rec_type, "status": "failed", "error": str(e)})
        
        if rec_type == 'symbol_direction_bias':
            symbol = rec.get('symbol')
            if not symbol:
                continue
            
            sym_stats = direction_analysis.get('by_symbol', {}).get(symbol, {}) if direction_analysis else {}
            n_trades = sym_stats.get('same_better', 0) + sym_stats.get('opposite_better', 0)
            
            if n_trades < MIN_TRADES_FOR_DIRECTION_INVERSION:
                applied.append({
                    "type": "signal_inversion",
                    "symbol": symbol,
                    "status": "skipped",
                    "reason": f"Need {MIN_TRADES_FOR_DIRECTION_INVERSION}+ trades, have {n_trades}"
                })
                print(f"   ⏭️ SKIPPED: Signal inversion for {symbol} - need {MIN_TRADES_FOR_DIRECTION_INVERSION}+ trades (have {n_trades})")
                continue
            
            try:
                inversion_path = CONFIGS_DIR / "signal_inversions.json"
                inversions = {}
                if inversion_path.exists():
                    with open(inversion_path, 'r') as f:
                        inversions = json.load(f)
                
                inversions[symbol] = {
                    "invert": True,
                    "reason": rec.get('issue', 'Direction accuracy < 50%'),
                    "applied_at": datetime.now().isoformat(),
                    "sample_size": n_trades
                }
                
                save_json(str(inversion_path), inversions)
                applied.append({
                    "type": "signal_inversion",
                    "symbol": symbol,
                    "status": "applied",
                    "sample_size": n_trades
                })
                print(f"   ✅ AUTO-APPLIED: Signal inversion for {symbol} (n={n_trades})")
            except Exception as e:
                applied.append({"type": "signal_inversion", "symbol": symbol, "status": "failed", "error": str(e)})
    
    return {"applied": applied, "count": sum(1 for a in applied if a.get('status') == 'applied')}


def run_complete_feedback_loop(auto_apply: bool = True) -> Dict[str, Any]:
    """
    Run the complete feedback loop analysis and update all configs.
    
    Args:
        auto_apply: If True, automatically apply high-priority recommendations
    """
    print("=" * 70)
    print("🔄 COMPLETE FEEDBACK LOOP ANALYSIS")
    print("=" * 70)
    print(f"Run time: {datetime.now().isoformat()}")
    
    print("\n📊 EXIT TIMING ANALYSIS:")
    print("-" * 50)
    exit_analysis = analyze_exit_timing()
    print(f"   Total trades analyzed: {exit_analysis.get('total_analyzed', 0)}")
    print(f"   Exited too early: {len(exit_analysis.get('exited_too_early', []))}")
    print(f"   Exited too late: {len(exit_analysis.get('exited_too_late', []))}")
    print(f"   Good exits: {len(exit_analysis.get('good_exits', []))}")
    
    if exit_analysis.get('by_duration_bucket'):
        print("\n   Performance by duration:")
        for bucket, stats in exit_analysis['by_duration_bucket'].items():
            if stats['n'] > 0:
                ev = stats['total_pnl'] / stats['n']
                print(f"      {bucket:10}: n={stats['n']:3} EV=${ev:6.2f} early={stats['too_early']:2} late={stats['too_late']:2} good={stats['good']:2}")
    
    print("\n🔄 DIRECTION COUNTERFACTUAL ANALYSIS:")
    print("-" * 50)
    direction_analysis = analyze_direction_counterfactuals()
    total_dir = direction_analysis.get('total_analyzed', 0)
    opposite_better = direction_analysis.get('opposite_would_be_better', 0)
    our_better = direction_analysis.get('our_direction_better', 0)
    print(f"   Total analyzed: {total_dir}")
    print(f"   Our direction was better: {our_better} ({our_better/total_dir*100:.1f}%)" if total_dir else "   No data")
    print(f"   Opposite would be better: {opposite_better} ({opposite_better/total_dir*100:.1f}%)" if total_dir else "")
    
    if direction_analysis.get('direction_bias_score'):
        print("\n   Direction accuracy by symbol:")
        for symbol, bias in sorted(direction_analysis['direction_bias_score'].items(), 
                                   key=lambda x: x[1].get('our_direction_accuracy', 0), reverse=True):
            print(f"      {symbol}: {bias['our_direction_accuracy']:.0f}% correct | net advantage: {bias['net_pnl_advantage']:+.2f}%")
    
    print("\n⏱️ LEARNING OPTIMAL HOLD DURATIONS:")
    print("-" * 50)
    timing_result = learn_optimal_hold_durations()
    print(f"   Status: {timing_result.get('status', 'unknown')}")
    print(f"   Patterns learned: {timing_result.get('patterns_learned', 0)}")
    print(f"   Total trades analyzed: {timing_result.get('total_trades_analyzed', 0)}")
    
    if timing_result.get('rules'):
        profitable_rules = [
            (k, v) for k, v in timing_result['rules'].items() 
            if k not in ['default', '_metadata'] and v.get('expected_ev', 0) > 0
        ]
        if profitable_rules:
            print("\n   Profitable timing patterns:")
            for pattern, rule in sorted(profitable_rules, key=lambda x: x[1].get('expected_ev', 0), reverse=True)[:5]:
                print(f"      {pattern}: optimal={rule['optimal_duration']} EV=${rule['expected_ev']:.2f} WR={rule.get('wr', 0):.0f}% n={rule['n']}")
    
    print("\n💡 IMPROVEMENT RECOMMENDATIONS:")
    print("-" * 50)
    recommendations = generate_improvement_recommendations()
    
    if not recommendations:
        print("   No specific recommendations at this time")
    else:
        for i, rec in enumerate(recommendations[:10], 1):
            priority = rec.get('priority', 'medium').upper()
            print(f"   {i}. [{priority}] {rec.get('issue', 'Unknown issue')}")
            print(f"      Action: {rec.get('action', 'N/A')}")
    
    applied_changes = {}
    if auto_apply and recommendations:
        print("\n🔧 AUTO-APPLYING HIGH-PRIORITY RECOMMENDATIONS:")
        print("-" * 50)
        applied_changes = auto_apply_recommendations(
            recommendations, 
            exit_analysis=exit_analysis, 
            direction_analysis=direction_analysis
        )
        if applied_changes.get('count', 0) > 0:
            print(f"\n   Applied {applied_changes['count']} changes automatically")
        else:
            print("   No changes auto-applied (insufficient confidence or already configured)")
    
    print("\n⚖️ UPDATING EXIT SIGNAL WEIGHTS:")
    print("-" * 50)
    exit_weight_update = update_exit_weights_from_timing_analysis({
        'too_early_count': len(exit_analysis.get('exited_too_early', [])),
        'too_late_count': len(exit_analysis.get('exited_too_late', [])),
        'total_analyzed': exit_analysis.get('total_analyzed', 0),
        'by_duration': exit_analysis.get('by_duration_bucket', {})
    })
    
    if exit_weight_update.get('status') == 'updated':
        for adj in exit_weight_update.get('adjustments', []):
            print(f"   ✅ {adj}")
        print("   💾 Exit weights updated and saved")
    elif exit_weight_update.get('status') == 'skipped':
        print(f"   ⏭️ Skipped: {exit_weight_update.get('reason')}")
    else:
        print(f"   ℹ️ {exit_weight_update.get('reason', exit_weight_update.get('status', 'No changes needed'))}")
    
    total_analyzed = exit_analysis.get('total_analyzed', 0)
    too_early = len(exit_analysis.get('exited_too_early', []))
    too_late = len(exit_analysis.get('exited_too_late', []))
    early_exit_rate = (too_early / total_analyzed * 100) if total_analyzed > 0 else 0
    direction_accuracy = round(our_better / total_dir * 100, 1) if total_dir else 0
    
    summary = {
        "timestamp": datetime.now().isoformat(),
        "direction_accuracy": direction_accuracy,
        "early_exit_rate": early_exit_rate,
        "timing_patterns_learned": timing_result.get('patterns_learned', 0),
        "exit_analysis": {
            "total_analyzed": total_analyzed,
            "too_early": too_early,
            "too_late": too_late,
            "good": len(exit_analysis.get('good_exits', []))
        },
        "direction_analysis": {
            "total_analyzed": total_dir,
            "our_better": our_better,
            "opposite_better": opposite_better,
            "accuracy_pct": direction_accuracy
        },
        "timing_rules_learned": timing_result.get('patterns_learned', 0),
        "recommendations_count": len(recommendations),
        "recommendations": recommendations[:10],
        "auto_applied": applied_changes
    }
    
    save_json(str(FEEDBACK_SUMMARY_PATH), summary)
    print(f"\n💾 Saved feedback summary to: {FEEDBACK_SUMMARY_PATH}")
    
    return summary


if __name__ == "__main__":
    run_complete_feedback_loop()
