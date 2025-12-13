#!/usr/bin/env python3
"""
Signal Universe Tracker - Complete Learning From EVERY Signal

This module captures EVERY signal generated, whether executed or blocked,
and tracks what WOULD have happened for complete learning.

Key Components:
1. Universal Signal Logger - captures all signals with full context
2. Counterfactual Price Tracker - follows prices post-signal
3. Missed Opportunity Analyzer - identifies blocked winners
4. Learning Integration - feeds back into decision rules

The goal: Learn from 100% of signals, not just the ones we trade.
"""

import json
import os
import time
import threading
from datetime import datetime, timedelta
from collections import defaultdict
from typing import Dict, List, Optional, Any
import statistics

from src.data_registry import DataRegistry as DR

LOGS_DIR = "logs"
SIGNAL_UNIVERSE_PATH = DR.SIGNALS_UNIVERSE
COUNTERFACTUAL_PATH = DR.COUNTERFACTUAL_OUTCOMES
MISSED_OPPORTUNITIES_PATH = DR.MISSED_OPPORTUNITIES
LEARNING_FEEDBACK_PATH = DR.COUNTERFACTUAL_LEARNINGS

_pending_counterfactuals = {}
_counterfactual_lock = threading.Lock()
_tracker_thread = None
_tracker_running = False


def _ensure_dirs():
    """Ensure log directories exist."""
    os.makedirs(LOGS_DIR, exist_ok=True)
    os.makedirs("feature_store", exist_ok=True)


def _append_jsonl(path: str, record: dict):
    """Append a record to JSONL file."""
    _ensure_dirs()
    try:
        with open(path, 'a') as f:
            f.write(json.dumps(record) + "\n")
    except Exception as e:
        print(f"⚠️ [SIGNAL-TRACKER] Failed to write to {path}: {e}")


def _load_jsonl(path: str, limit: int = None) -> List[dict]:
    """Load records from JSONL file."""
    records = []
    if not os.path.exists(path):
        return records
    try:
        with open(path, 'r') as f:
            for i, line in enumerate(f):
                if limit and i >= limit:
                    break
                try:
                    records.append(json.loads(line.strip()))
                except:
                    continue
    except:
        pass
    return records


def _get_coinglass_data(symbol: str) -> Dict[str, Any]:
    """Fetch CoinGlass market intelligence for a symbol."""
    result = {}
    
    intel_path = f"feature_store/intelligence/{symbol}_intel.json"
    
    try:
        if os.path.exists(intel_path):
            with open(intel_path, 'r') as f:
                cg_data = json.load(f)
            
            taker = cg_data.get("taker", {})
            liq = cg_data.get("liquidation", {})
            signal = cg_data.get("signal", {})
            
            buy_ratio = taker.get("buy_ratio", 0.5)
            sell_ratio = taker.get("sell_ratio", 0.5)
            taker_ratio = buy_ratio / sell_ratio if sell_ratio > 0 else 1.0
            
            liq_long = liq.get("liq_long_24h", 0)
            liq_short = liq.get("liq_short_24h", 0)
            liq_total = liq_long + liq_short
            liq_bias = (liq_short - liq_long) / liq_total if liq_total > 0 else 0
            
            result = {
                "fear_greed": cg_data.get("fear_greed"),
                "taker_ratio": round(taker_ratio, 4),
                "liquidation_bias": round(liq_bias, 4),
                "signal_direction": signal.get("direction"),
                "signal_confidence": signal.get("confidence"),
                "liq_long_24h": liq_long,
                "liq_short_24h": liq_short,
                "buy_ratio": buy_ratio,
                "sell_ratio": sell_ratio,
            }
    except Exception as e:
        pass
    
    if not result:
        try:
            cg_data = DR.get_coinglass_features(symbol)
            if cg_data:
                result = {
                    "fear_greed": cg_data.get("fear_greed"),
                    "taker_ratio": cg_data.get("taker_ratio"),
                    "liquidation_bias": cg_data.get("liquidation_bias"),
                }
        except Exception:
            pass
    
    return result


def log_signal(
    symbol: str,
    side: str,
    disposition: str,
    intelligence: Dict[str, Any],
    block_reason: str = None,
    block_gate: str = None,
    entry_price: float = None,
    signal_context: Dict[str, Any] = None
):
    """
    Log every signal to the universe tracker.
    
    Args:
        symbol: Trading symbol (e.g., BTCUSDT)
        side: LONG or SHORT
        disposition: EXECUTED, BLOCKED, SKIPPED, or PARTIAL
        intelligence: Full intelligence context (OFI, ensemble, MTF, regime, etc.)
        block_reason: Why signal was blocked (if blocked)
        block_gate: Which gate blocked it (if blocked)
        entry_price: Price at signal time
        signal_context: Additional context (strategy, venue, etc.)
    """
    ts = int(time.time())
    
    cg_data = _get_coinglass_data(symbol)
    
    market_intel = intelligence.get("market_intel", {})
    market_intel.update(cg_data)
    
    record = {
        "ts": ts,
        "ts_iso": datetime.utcnow().isoformat(),
        "symbol": symbol,
        "side": side,
        "disposition": disposition,
        "entry_price": entry_price,
        "intelligence": {
            "ofi": intelligence.get("ofi"),
            "ofi_raw": intelligence.get("ofi_raw"),
            "ensemble": intelligence.get("ensemble"),
            "mtf_confidence": intelligence.get("mtf_confidence"),
            "regime": intelligence.get("regime"),
            "volatility": intelligence.get("volatility"),
            "market_intel": market_intel,
            "fear_greed": cg_data.get("fear_greed") or intelligence.get("fear_greed"),
            "taker_ratio": cg_data.get("taker_ratio") or intelligence.get("taker_ratio"),
            "liquidation_bias": cg_data.get("liquidation_bias") or intelligence.get("liquidation_bias"),
        },
        "block_reason": block_reason,
        "block_gate": block_gate,
        "context": signal_context or {},
        "counterfactual_pending": disposition != "EXECUTED"
    }
    
    _append_jsonl(SIGNAL_UNIVERSE_PATH, record)
    
    if disposition != "EXECUTED" and entry_price:
        _schedule_counterfactual(ts, symbol, side, entry_price, record)
    
    return record


def _schedule_counterfactual(signal_ts: int, symbol: str, side: str, entry_price: float, signal_record: dict):
    """Schedule price checks for counterfactual analysis."""
    global _pending_counterfactuals
    
    with _counterfactual_lock:
        key = f"{signal_ts}_{symbol}_{side}"
        _pending_counterfactuals[key] = {
            "signal_ts": signal_ts,
            "symbol": symbol,
            "side": side,
            "entry_price": entry_price,
            "signal_record": signal_record,
            "checks": {
                "5m": {"due_ts": signal_ts + 300, "done": False, "price": None},
                "15m": {"due_ts": signal_ts + 900, "done": False, "price": None},
                "60m": {"due_ts": signal_ts + 3600, "done": False, "price": None},
            }
        }


def _get_current_price(symbol: str) -> Optional[float]:
    """Get current price for a symbol."""
    try:
        from src.data_fetcher import get_current_price
        return get_current_price(symbol)
    except:
        pass
    
    try:
        from src.blofin_client import BlofinClient
        client = BlofinClient()
        sym = symbol.replace("USDT", "-USDT")
        ticker = client.get_ticker(sym)
        if ticker and "last" in ticker:
            return float(ticker["last"])
    except:
        pass
    
    try:
        import requests
        url = f"https://api.binance.us/api/v3/ticker/price?symbol={symbol}"
        resp = requests.get(url, timeout=5)
        if resp.status_code == 200:
            return float(resp.json().get("price", 0))
    except:
        pass
    
    return None


def _process_counterfactuals():
    """Process pending counterfactual price checks."""
    global _pending_counterfactuals
    
    now = int(time.time())
    completed_keys = []
    
    with _counterfactual_lock:
        for key, cf in list(_pending_counterfactuals.items()):
            all_done = True
            
            for interval, check in cf["checks"].items():
                if check["done"]:
                    continue
                    
                if now >= check["due_ts"]:
                    price = _get_current_price(cf["symbol"])
                    if price:
                        check["price"] = price
                        check["done"] = True
                        
                        entry = cf["entry_price"]
                        side = cf["side"]
                        
                        if side == "LONG":
                            pnl_pct = (price - entry) / entry * 100
                        else:
                            pnl_pct = (entry - price) / entry * 100
                        
                        check["pnl_pct"] = pnl_pct
                        check["would_win"] = pnl_pct > 0.1
                else:
                    all_done = False
            
            if all_done:
                _save_counterfactual_result(cf)
                completed_keys.append(key)
        
        for key in completed_keys:
            del _pending_counterfactuals[key]


def _save_counterfactual_result(cf: dict):
    """Save completed counterfactual analysis."""
    entry = cf["entry_price"]
    side = cf["side"]
    
    results = {}
    best_pnl = -999
    best_interval = None
    
    for interval, check in cf["checks"].items():
        if check["price"]:
            pnl_pct = check.get("pnl_pct", 0)
            results[interval] = {
                "exit_price": check["price"],
                "pnl_pct": pnl_pct,
                "would_win": check.get("would_win", False)
            }
            if pnl_pct > best_pnl:
                best_pnl = pnl_pct
                best_interval = interval
    
    would_have_won = best_pnl > 0.1
    
    record = {
        "signal_ts": cf["signal_ts"],
        "analyzed_ts": int(time.time()),
        "symbol": cf["symbol"],
        "side": cf["side"],
        "entry_price": entry,
        "disposition": cf["signal_record"].get("disposition"),
        "block_reason": cf["signal_record"].get("block_reason"),
        "block_gate": cf["signal_record"].get("block_gate"),
        "intelligence": cf["signal_record"].get("intelligence", {}),
        "outcomes": results,
        "best_pnl_pct": best_pnl,
        "best_interval": best_interval,
        "would_have_won": would_have_won,
        "missed_opportunity": would_have_won and cf["signal_record"].get("disposition") == "BLOCKED"
    }
    
    _append_jsonl(COUNTERFACTUAL_PATH, record)
    
    if record["missed_opportunity"]:
        _append_jsonl(MISSED_OPPORTUNITIES_PATH, record)
        print(f"   📊 [MISSED-OPP] {cf['symbol']} {cf['side']}: Would have made {best_pnl:.2f}% at {best_interval}")


def _counterfactual_worker():
    """Background worker for counterfactual tracking."""
    global _tracker_running
    
    while _tracker_running:
        try:
            _process_counterfactuals()
        except Exception as e:
            print(f"⚠️ [COUNTERFACTUAL] Worker error: {e}")
        
        time.sleep(30)


def start_tracker():
    """Start the counterfactual tracking worker."""
    global _tracker_thread, _tracker_running
    
    if _tracker_running:
        return
    
    _tracker_running = True
    _tracker_thread = threading.Thread(target=_counterfactual_worker, daemon=True)
    _tracker_thread.start()
    print("✅ [SIGNAL-TRACKER] Counterfactual tracker started")


def stop_tracker():
    """Stop the counterfactual tracking worker."""
    global _tracker_running
    _tracker_running = False


def analyze_missed_opportunities(days: int = 7) -> dict:
    """
    Analyze missed opportunities from blocked signals.
    
    Returns summary of what we're missing by blocking.
    """
    cutoff_ts = int(time.time()) - (days * 86400)
    
    records = _load_jsonl(COUNTERFACTUAL_PATH)
    recent = [r for r in records if r.get("signal_ts", 0) >= cutoff_ts]
    
    if not recent:
        return {"error": "No counterfactual data yet", "days_analyzed": days}
    
    blocked = [r for r in recent if r.get("disposition") == "BLOCKED"]
    executed = [r for r in recent if r.get("disposition") == "EXECUTED"]
    
    blocked_winners = [r for r in blocked if r.get("would_have_won")]
    blocked_losers = [r for r in blocked if not r.get("would_have_won")]
    
    analysis = {
        "days_analyzed": days,
        "total_signals": len(recent),
        "blocked_count": len(blocked),
        "executed_count": len(executed),
        "blocked_would_win": len(blocked_winners),
        "blocked_would_lose": len(blocked_losers),
        "block_accuracy": len(blocked_losers) / len(blocked) * 100 if blocked else 0,
        "missed_profit_pct": sum(r.get("best_pnl_pct", 0) for r in blocked_winners),
        "avoided_loss_pct": sum(abs(r.get("best_pnl_pct", 0)) for r in blocked_losers),
    }
    
    by_gate = defaultdict(lambda: {"blocked": 0, "would_win": 0, "would_lose": 0})
    for r in blocked:
        gate = r.get("block_gate", "unknown")
        by_gate[gate]["blocked"] += 1
        if r.get("would_have_won"):
            by_gate[gate]["would_win"] += 1
        else:
            by_gate[gate]["would_lose"] += 1
    
    analysis["by_gate"] = dict(by_gate)
    
    by_symbol = defaultdict(lambda: {"blocked": 0, "would_win": 0, "missed_pnl": 0})
    for r in blocked:
        sym = r.get("symbol", "unknown")
        by_symbol[sym]["blocked"] += 1
        if r.get("would_have_won"):
            by_symbol[sym]["would_win"] += 1
            by_symbol[sym]["missed_pnl"] += r.get("best_pnl_pct", 0)
    
    analysis["by_symbol"] = dict(by_symbol)
    
    return analysis


def generate_gate_feedback() -> dict:
    """
    Generate feedback for gates based on counterfactual analysis.
    
    Identifies gates that are:
    - Over-blocking (blocking too many winners)
    - Under-blocking (letting through too many losers)
    """
    analysis = analyze_missed_opportunities(days=7)
    
    feedback = {
        "generated_at": datetime.utcnow().isoformat(),
        "gates_to_loosen": [],
        "gates_to_tighten": [],
        "symbol_adjustments": [],
    }
    
    for gate, stats in analysis.get("by_gate", {}).items():
        if stats["blocked"] < 5:
            continue
            
        win_rate_blocked = stats["would_win"] / stats["blocked"] * 100 if stats["blocked"] else 0
        
        if win_rate_blocked > 40:
            feedback["gates_to_loosen"].append({
                "gate": gate,
                "blocked": stats["blocked"],
                "would_win_pct": win_rate_blocked,
                "recommendation": f"Loosen {gate} - blocking {win_rate_blocked:.0f}% winners"
            })
        elif win_rate_blocked < 15:
            feedback["gates_to_tighten"].append({
                "gate": gate,
                "blocked": stats["blocked"],
                "would_win_pct": win_rate_blocked,
                "recommendation": f"{gate} is effective - consider tightening other gates"
            })
    
    for symbol, stats in analysis.get("by_symbol", {}).items():
        if stats["blocked"] < 3:
            continue
            
        win_rate = stats["would_win"] / stats["blocked"] * 100 if stats["blocked"] else 0
        
        if win_rate > 50:
            feedback["symbol_adjustments"].append({
                "symbol": symbol,
                "blocked": stats["blocked"],
                "would_win_pct": win_rate,
                "missed_pnl_pct": stats["missed_pnl"],
                "recommendation": f"Consider loosening gates for {symbol}"
            })
    
    try:
        with open(LEARNING_FEEDBACK_PATH, 'w') as f:
            json.dump(feedback, f, indent=2)
    except Exception as e:
        print(f"⚠️ [SIGNAL-TRACKER] Failed to save feedback: {e}")
    
    return feedback


def get_signal_universe_stats() -> dict:
    """Get statistics on signal universe."""
    records = _load_jsonl(SIGNAL_UNIVERSE_PATH)
    
    if not records:
        return {"total_signals": 0, "message": "No signals logged yet"}
    
    cutoff_24h = int(time.time()) - 86400
    recent = [r for r in records if r.get("ts", 0) >= cutoff_24h]
    
    by_disposition = defaultdict(int)
    by_symbol = defaultdict(int)
    by_gate = defaultdict(int)
    
    for r in recent:
        by_disposition[r.get("disposition", "unknown")] += 1
        by_symbol[r.get("symbol", "unknown")] += 1
        if r.get("block_gate"):
            by_gate[r.get("block_gate")] += 1
    
    return {
        "total_signals_24h": len(recent),
        "total_signals_all": len(records),
        "by_disposition": dict(by_disposition),
        "by_symbol": dict(by_symbol),
        "by_block_gate": dict(by_gate),
        "pending_counterfactuals": len(_pending_counterfactuals),
    }


def print_learning_report():
    """Print a comprehensive learning report."""
    print("\n" + "="*70)
    print("📊 SIGNAL UNIVERSE LEARNING REPORT")
    print("="*70)
    
    stats = get_signal_universe_stats()
    print(f"\n   Total Signals (24h): {stats.get('total_signals_24h', 0)}")
    print(f"   Total Signals (all): {stats.get('total_signals_all', 0)}")
    print(f"   Pending Counterfactuals: {stats.get('pending_counterfactuals', 0)}")
    
    print("\n   By Disposition:")
    for disp, count in stats.get("by_disposition", {}).items():
        print(f"      {disp}: {count}")
    
    print("\n   By Block Gate:")
    for gate, count in stats.get("by_block_gate", {}).items():
        print(f"      {gate}: {count}")
    
    analysis = analyze_missed_opportunities(days=7)
    
    if "error" not in analysis:
        print(f"\n   📈 Counterfactual Analysis ({analysis['days_analyzed']} days):")
        print(f"      Blocked signals: {analysis['blocked_count']}")
        print(f"      Would have won: {analysis['blocked_would_win']} ({analysis['block_accuracy']:.1f}% accuracy)")
        print(f"      Missed profit: {analysis['missed_profit_pct']:.1f}%")
        print(f"      Avoided loss: {analysis['avoided_loss_pct']:.1f}%")
        
        if analysis.get("by_gate"):
            print("\n   📊 Gate Effectiveness:")
            for gate, gstats in analysis["by_gate"].items():
                acc = gstats["would_lose"] / gstats["blocked"] * 100 if gstats["blocked"] else 0
                print(f"      {gate}: {gstats['blocked']} blocked, {acc:.0f}% accuracy")
    
    feedback = generate_gate_feedback()
    
    if feedback.get("gates_to_loosen"):
        print("\n   ⚠️ Gates Blocking Too Many Winners:")
        for g in feedback["gates_to_loosen"]:
            print(f"      {g['recommendation']}")
    
    if feedback.get("symbol_adjustments"):
        print("\n   🎯 Symbol-Specific Adjustments:")
        for s in feedback["symbol_adjustments"]:
            print(f"      {s['recommendation']}")
    
    print("\n" + "="*70)


TIME_FILTER_SCENARIOS_PATH = "logs/time_filter_scenarios.jsonl"

TIME_FILTER_SCENARIOS = {
    "current_0_4": {"name": "Current (0-4 UTC)", "avoid_hours": [0, 1, 2, 3]},
    "narrow_2_4": {"name": "Narrow (2-4 UTC)", "avoid_hours": [2, 3]},
    "narrow_0_2": {"name": "Early (0-2 UTC)", "avoid_hours": [0, 1]},
    "wide_0_6": {"name": "Wide (0-6 UTC)", "avoid_hours": [0, 1, 2, 3, 4, 5]},
    "no_filter": {"name": "No Filter", "avoid_hours": []},
    "asia_22_4": {"name": "Asia Session (22-4 UTC)", "avoid_hours": [22, 23, 0, 1, 2, 3]},
}


def log_time_filtered_signal(
    symbol: str,
    side: str,
    current_hour: int,
    entry_price: float,
    intelligence: Dict[str, Any],
    signal_context: Dict[str, Any] = None
):
    """
    Log a signal blocked by time filter with scenario analysis.
    Records which alternative time filter configs would have allowed this trade.
    
    This extends the existing signal universe tracker, NOT creating a new silo.
    """
    ts = int(time.time())
    
    scenarios_allowed = {}
    for scenario_id, scenario in TIME_FILTER_SCENARIOS.items():
        would_allow = current_hour not in scenario["avoid_hours"]
        scenarios_allowed[scenario_id] = {
            "name": scenario["name"],
            "would_allow": would_allow,
            "avoid_hours": scenario["avoid_hours"]
        }
    
    record = {
        "ts": ts,
        "ts_iso": datetime.utcnow().isoformat(),
        "symbol": symbol,
        "side": side,
        "current_hour": current_hour,
        "entry_price": entry_price,
        "intelligence": intelligence,
        "context": signal_context or {},
        "scenarios": scenarios_allowed,
        "counterfactual_pending": True
    }
    
    _append_jsonl(TIME_FILTER_SCENARIOS_PATH, record)
    
    log_signal(
        symbol=symbol,
        side=side,
        disposition="BLOCKED",
        intelligence=intelligence,
        block_reason="time_filter_block",
        block_gate=f"hour_{current_hour}_utc",
        entry_price=entry_price,
        signal_context={
            **(signal_context or {}),
            "time_filter_scenarios": scenarios_allowed
        }
    )
    
    allowed_scenarios = [s["name"] for s_id, s in scenarios_allowed.items() if s["would_allow"]]
    if allowed_scenarios:
        print(f"   📊 [TIME-SCENARIOS] Would pass: {', '.join(allowed_scenarios)}")
    
    return record


def analyze_time_filter_scenarios(days: int = 7) -> Dict[str, Any]:
    """
    Analyze counterfactual outcomes by time filter scenario.
    Shows what would have happened with different filter configurations.
    
    Returns detailed analysis per scenario with theoretical P&L.
    """
    cutoff_ts = int(time.time()) - (days * 86400)
    
    time_records = _load_jsonl(TIME_FILTER_SCENARIOS_PATH)
    counterfactual_records = _load_jsonl(COUNTERFACTUAL_PATH)
    
    recent_time = [r for r in time_records if r.get("ts", 0) >= cutoff_ts]
    
    cf_lookup = {}
    for cf in counterfactual_records:
        key = f"{cf.get('symbol')}_{cf.get('signal_ts')}"
        cf_lookup[key] = cf
    
    scenario_stats = {
        scenario_id: {
            "name": scenario["name"],
            "would_allow": 0,
            "would_block": 0,
            "winners_allowed": 0,
            "losers_allowed": 0,
            "theoretical_pnl_pct": 0.0,
            "by_hour": defaultdict(lambda: {"count": 0, "winners": 0, "pnl": 0.0}),
        }
        for scenario_id, scenario in TIME_FILTER_SCENARIOS.items()
    }
    
    for record in recent_time:
        symbol = record.get("symbol")
        ts = record.get("ts")
        hour = record.get("current_hour", 0)
        
        cf_key = f"{symbol}_{ts}"
        cf_result = cf_lookup.get(cf_key, {})
        would_have_won = cf_result.get("would_have_won", False)
        best_pnl = cf_result.get("best_pnl_pct", 0)
        
        for scenario_id, scenario_data in record.get("scenarios", {}).items():
            if scenario_id not in scenario_stats:
                continue
                
            stats = scenario_stats[scenario_id]
            
            if scenario_data.get("would_allow"):
                stats["would_allow"] += 1
                if would_have_won:
                    stats["winners_allowed"] += 1
                else:
                    stats["losers_allowed"] += 1
                stats["theoretical_pnl_pct"] += best_pnl
                
                stats["by_hour"][hour]["count"] += 1
                if would_have_won:
                    stats["by_hour"][hour]["winners"] += 1
                stats["by_hour"][hour]["pnl"] += best_pnl
            else:
                stats["would_block"] += 1
    
    for scenario_id, stats in scenario_stats.items():
        stats["by_hour"] = dict(stats["by_hour"])
        if stats["would_allow"] > 0:
            stats["theoretical_win_rate"] = stats["winners_allowed"] / stats["would_allow"] * 100
        else:
            stats["theoretical_win_rate"] = 0
    
    best_scenario = max(
        scenario_stats.keys(),
        key=lambda s: scenario_stats[s]["theoretical_pnl_pct"]
    )
    
    return {
        "days_analyzed": days,
        "total_time_filtered_signals": len(recent_time),
        "scenarios": scenario_stats,
        "best_scenario": {
            "id": best_scenario,
            "name": scenario_stats[best_scenario]["name"],
            "theoretical_pnl_pct": scenario_stats[best_scenario]["theoretical_pnl_pct"],
            "theoretical_win_rate": scenario_stats[best_scenario]["theoretical_win_rate"]
        },
        "recommendation": _generate_time_filter_recommendation(scenario_stats)
    }


def _generate_time_filter_recommendation(scenario_stats: Dict) -> str:
    """Generate a recommendation based on scenario analysis."""
    current = scenario_stats.get("current_0_4", {})
    no_filter = scenario_stats.get("no_filter", {})
    narrow = scenario_stats.get("narrow_2_4", {})
    
    current_pnl = current.get("theoretical_pnl_pct", 0)
    no_filter_pnl = no_filter.get("theoretical_pnl_pct", 0)
    narrow_pnl = narrow.get("theoretical_pnl_pct", 0)
    
    if no_filter_pnl > current_pnl and no_filter.get("theoretical_win_rate", 0) > 45:
        return f"Consider removing time filter: +{no_filter_pnl - current_pnl:.1f}% potential gain"
    elif narrow_pnl > current_pnl:
        return f"Consider narrowing to 2-4 UTC: +{narrow_pnl - current_pnl:.1f}% potential gain"
    else:
        return "Current 0-4 UTC filter appears optimal based on counterfactual data"


def get_time_filter_dashboard_data() -> Dict[str, Any]:
    """Get time filter scenario data formatted for dashboard display."""
    analysis = analyze_time_filter_scenarios(days=7)
    
    scenarios = analysis.get("scenarios", {})
    
    dashboard_data = {
        "current_filter": "0-4 UTC (High Loss Hours)",
        "signals_blocked_7d": analysis.get("total_time_filtered_signals", 0),
        "scenarios": [],
        "best_scenario": analysis.get("best_scenario", {}),
        "recommendation": analysis.get("recommendation", "Insufficient data"),
    }
    
    for scenario_id, stats in scenarios.items():
        dashboard_data["scenarios"].append({
            "id": scenario_id,
            "name": stats["name"],
            "would_allow": stats["would_allow"],
            "would_block": stats["would_block"],
            "theoretical_win_rate": f"{stats['theoretical_win_rate']:.1f}%",
            "theoretical_pnl": f"{stats['theoretical_pnl_pct']:+.2f}%",
            "is_current": scenario_id == "current_0_4"
        })
    
    return dashboard_data


if __name__ == "__main__":
    import sys
    
    if "--report" in sys.argv:
        print_learning_report()
    elif "--analyze" in sys.argv:
        analysis = analyze_missed_opportunities(days=7)
        print(json.dumps(analysis, indent=2))
    elif "--feedback" in sys.argv:
        feedback = generate_gate_feedback()
        print(json.dumps(feedback, indent=2))
    elif "--time-scenarios" in sys.argv:
        analysis = analyze_time_filter_scenarios(days=7)
        print(json.dumps(analysis, indent=2, default=str))
    else:
        print("Usage:")
        print("  python src/signal_universe_tracker.py --report         # Full learning report")
        print("  python src/signal_universe_tracker.py --analyze        # Missed opportunity analysis")
        print("  python src/signal_universe_tracker.py --feedback       # Gate feedback")
        print("  python src/signal_universe_tracker.py --time-scenarios # Time filter scenarios")
