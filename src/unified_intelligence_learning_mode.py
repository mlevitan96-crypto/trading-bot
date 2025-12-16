# src/unified_intelligence_learning_mode.py
#
# Unified Intelligence Upgrade (Learning Mode, no real money)
# Covers all 11 coins:
# BTCUSDT, ETHUSDT, SOLUSDT, AVAXUSDT, DOTUSDT, TRXUSDT, XRPUSDT, ADAUSDT, DOGEUSDT, BNBUSDT, MATICUSDT
#
# Features:
# - Missed opportunity audit: detect significant moves without signals across all coins
# - Adaptive position sizing: scale collateral by win rate, expected ROI, and fees
# - Holding time optimization: detect early exits and enforce minimum profit holds (analysis/logging)
# - Strategy attribution (learning-only): track net P&L and win rate per strategy
# - Profit targeting layer: per-symbol minimum expected dollar profit before entry
# - Learning ingestion: log all decisions (executed, blocked, unfired) to improve signal intelligence
#
# NOTE: Learning mode only — no real money moved, focus on intelligence and boundaries exploration.

import os
import json
import time
from collections import defaultdict
from typing import Dict, List, Optional

# ---------- Trading universe - Dynamic loading from canonical config ----------
try:
    from src.data_registry import DataRegistry as DR
    ALL_SYMBOLS = DR.get_enabled_symbols()
except ImportError:
    ALL_SYMBOLS = [
        "BTCUSDT","ETHUSDT","SOLUSDT","AVAXUSDT","DOTUSDT",
        "TRXUSDT","XRPUSDT","ADAUSDT","DOGEUSDT","BNBUSDT",
        "LINKUSDT","ARBUSDT","OPUSDT","PEPEUSDT"
    ]

# ---------- Configuration ----------
EVENTS_LOG = "logs/intelligence_events.jsonl"
SIGNALS_LOG = "logs/signals_snapshot.jsonl"        # snapshots of scanned signals (candidates)
POSITIONS_LOG = "logs/positions_learning.jsonl"    # executed positions (learning ledger)

MAX_COLLATERAL_USD = 5000
BASE_COLLATERAL_USD = 500
MIN_HOLD_ROI = 0.005  # 0.5% minimum ROI before exit unless stop hit
MIN_MOVE_PCT_FOR_MISSED = 0.01  # 1% price move threshold to consider "missed opportunity"

MIN_PROFIT_TARGETS_USD = {
    "BTCUSDT": 20, "ETHUSDT": 15, "SOLUSDT": 10, "AVAXUSDT": 10, "DOTUSDT": 10,
    "TRXUSDT": 5,  "XRPUSDT": 10, "ADAUSDT": 10, "DOGEUSDT": 5,  "BNBUSDT": 10,
    "DEFAULT": 10
}

VENUE_FEES = {"taker_pct": 0.0012, "maker_pct": 0.0008}
DEFAULT_SLIPPAGE_PCT = 0.0005
DEFAULT_SPREAD_PCT   = 0.0003

LEARNING_WINDOW = 50  # rolling window for realized outcomes

# ---------- IO helpers ----------
def _append_json(path: str, obj: dict):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "a") as f:
        f.write(json.dumps(obj) + "\n")

def _read_jsonl(path: str) -> List[dict]:
    if not os.path.exists(path): return []
    out = []
    with open(path, "r") as f:
        for line in f:
            s = line.strip()
            if not s: continue
            try: out.append(json.loads(s))
            except: continue
    return out

def log_event(event: str, payload: Optional[dict] = None):
    if payload is None:
        payload = {}
    payload = dict(payload)
    payload.update({"ts": int(time.time()), "event": event})
    _append_json(EVENTS_LOG, payload)

# ---------- Cost model ----------
def estimate_round_trip_costs(size_usd: float, taker: bool=True,
                              slippage_pct: float=DEFAULT_SLIPPAGE_PCT,
                              spread_pct: float=DEFAULT_SPREAD_PCT) -> Dict[str, float]:
    fee_pct = VENUE_FEES["taker_pct"] if taker else VENUE_FEES["maker_pct"]
    fees = size_usd * fee_pct * 2
    slip = size_usd * slippage_pct
    sprd = size_usd * spread_pct
    return {
        "fees_usd": fees,
        "slippage_usd": slip,
        "spread_usd": sprd,
        "total_cost_usd": fees + slip + sprd
    }

# ---------- Realized outcomes (learning-only) ----------
def realized_outcomes_summary(symbol: str) -> dict:
    rows = [p for p in _read_jsonl(POSITIONS_LOG) if p.get("symbol")==symbol and "profit_usd" in p]
    rows = rows[-LEARNING_WINDOW:]
    wins = sum(1 for r in rows if float(r.get("profit_usd", 0)) > 0)
    losses = len(rows) - wins
    cum_pnl = sum(float(r.get("profit_usd", 0)) for r in rows)
    wr = (wins/len(rows)) if rows else 0.0
    avg_roi = sum(float(r.get("roi", 0)) for r in rows)/max(1,len(rows)) if rows else 0.0
    return {"win_rate": wr, "cum_pnl": cum_pnl, "samples": len(rows), "avg_roi": avg_roi}

# ---------- 1) Missed Opportunity Audit ----------
def audit_missed_opportunities():
    signals = _read_jsonl(SIGNALS_LOG)
    for s in signals:
        sym = s.get("symbol")
        if sym not in ALL_SYMBOLS: continue
        move_pct = float(s.get("price_move_pct", 0.0))
        executed = bool(s.get("executed", False))
        considered = bool(s.get("considered", False))
        if move_pct >= MIN_MOVE_PCT_FOR_MISSED and not executed and not considered:
            log_event("missed_opportunity", {
                "symbol": sym, "price_move_pct": move_pct,
                "regime": s.get("regime"), "confidence": s.get("confidence", 0.0),
                "reason": "no_signal_generated"
            })

# ---------- 2) Adaptive Position Sizing ----------
def adaptive_position_size(symbol: str, win_rate: float, expected_roi: float, fee_pct: float) -> float:
    size = BASE_COLLATERAL_USD
    if win_rate > 0.6 and expected_roi >= 0.008:      size *= 4  # 0.8%+ ROI
    elif win_rate > 0.55 and expected_roi >= 0.006:   size *= 3  # 0.6%+ ROI
    elif win_rate > 0.5 and expected_roi >= 0.004:    size *= 2  # 0.4%+ ROI
    if fee_pct >= VENUE_FEES["taker_pct"]: size *= 0.75
    size = min(size, MAX_COLLATERAL_USD)
    log_event("adaptive_size_decision", {
        "symbol": symbol, "win_rate": win_rate, "expected_roi": expected_roi,
        "fee_pct": fee_pct, "decided_size_usd": round(size, 2)
    })
    return size

# ---------- 3) Holding Time Optimization ----------
def analyze_holding_times_and_log():
    positions = _read_jsonl(POSITIONS_LOG)
    for p in positions:
        if not p.get("closed"): continue
        roi = float(p.get("roi", 0.0))
        stop_hit = bool(p.get("stop_hit", False))
        if roi < MIN_HOLD_ROI and not stop_hit:
            log_event("early_exit_detected", {
                "symbol": p.get("symbol"), "roi": roi,
                "entry_ts": p.get("entry_ts"), "exit_ts": p.get("exit_ts"),
                "strategy": p.get("strategy"), "note": "exited before minimum profit hold without stop"
            })

# ---------- 4) Strategy Attribution (learning-only) ----------
def strategy_performance_summary() -> Dict[str, dict]:
    positions = _read_jsonl(POSITIONS_LOG)
    stats = defaultdict(lambda: {"trades":0,"wins":0,"pnl":0.0,"avg_roi":0.0})
    roi_sum = defaultdict(float)
    for p in positions:
        strat = p.get("strategy", "unknown")
        stats[strat]["trades"] += 1
        stats[strat]["wins"]   += 1 if float(p.get("profit_usd",0)) > 0 else 0
        stats[strat]["pnl"]    += float(p.get("profit_usd",0))
        roi_sum[strat]         += float(p.get("roi",0))
    for strat, s in stats.items():
        s["win_rate"] = (s["wins"]/s["trades"]) if s["trades"] else 0.0
        s["avg_roi"]  = (roi_sum[strat]/s["trades"]) if s["trades"] else 0.0
        log_event("strategy_attribution", {
            "strategy": strat, "trades": s["trades"],
            "win_rate": round(s["win_rate"],4),
            "net_pnl": round(s["pnl"],2),
            "avg_roi": round(s["avg_roi"],4)
        })
    return stats

# ---------- 5) Profit Targeting Layer ----------
def enforce_profit_target(signal: dict) -> bool:
    symbol = signal.get("symbol","DEFAULT")
    target = MIN_PROFIT_TARGETS_USD.get(symbol, MIN_PROFIT_TARGETS_USD["DEFAULT"])
    size_usd = float(signal.get("size_usd", 0.0))
    exp_profit_usd = float(signal.get("roi", 0.0)) * size_usd
    if exp_profit_usd < target:
        log_event("profit_target_block", {
            "symbol": symbol, "expected_profit_usd": round(exp_profit_usd,2), "target_usd": target
        })
        return False
    return True

# ---------- Intelligence verdict (learning mode) ----------
def intelligence_go_no_go(signal: dict, symbol_stats: dict) -> Dict[str, object]:
    symbol = signal.get("symbol","")
    size_usd = float(signal.get("size_usd", BASE_COLLATERAL_USD))
    exp_profit_usd = float(signal.get("roi", 0.0)) * size_usd
    costs = estimate_round_trip_costs(size_usd, taker=True)
    net_edge_usd = exp_profit_usd - costs["total_cost_usd"]

    suggested_size_usd = adaptive_position_size(symbol, float(symbol_stats.get("win_rate",0.0)),
                                                float(signal.get("roi",0.0)), VENUE_FEES["taker_pct"])
    signal["size_usd"] = suggested_size_usd

    target_ok = enforce_profit_target(signal)

    verdict = {
        "symbol": symbol, "strategy": signal.get("strategy"),
        "exp_profit_usd": round(exp_profit_usd, 4),
        "total_cost_usd": round(costs["total_cost_usd"], 4),
        "net_edge_usd": round(net_edge_usd, 4),
        "suggested_size_usd": round(suggested_size_usd, 2),
        "profit_target_ok": target_ok,
        "go": bool(net_edge_usd > 0 and target_ok)
    }

    if verdict["go"]:
        log_event("intelligence_go", verdict)
    else:
        reasons = []
        if net_edge_usd <= 0: reasons.append("net_edge_negative")
        if not target_ok: reasons.append("below_profit_target")
        verdict["reject_reasons"] = reasons
        log_event("intelligence_no_go", verdict)

    return verdict

# ---------- Learning-mode execution wrapper ----------
def learning_execute(signal: dict, symbol_stats: dict, simulate_execution_fn=None) -> dict:
    decision = intelligence_go_no_go(signal, symbol_stats)
    if not decision["go"]:
        return {"status": "blocked", "decision": decision}
    res = {}
    if simulate_execution_fn:
        res = simulate_execution_fn(signal)
    log_event("learning_execution", {"decision": decision, "simulation": res})
    return {"status":"simulated", "decision": decision, "simulation": res}

# ---------- Periodic runners (learning mode) ----------
def run_learning_cycle(signals: Optional[List[dict]] = None, symbol_stats_map: Optional[Dict[str, dict]] = None):
    audit_missed_opportunities()
    analyze_holding_times_and_log()
    strategy_performance_summary()

    signals = signals or _read_jsonl(SIGNALS_LOG)
    symbol_stats_map = symbol_stats_map or {}

    for s in signals:
        sym = s.get("symbol","")
        if sym not in ALL_SYMBOLS: continue
        stats = symbol_stats_map.get(sym) or realized_outcomes_summary(sym)
        s["considered"] = True
        _append_json(SIGNALS_LOG, s)
        learning_execute(s, stats)

# ---------- Example simulate function ----------
def simple_simulation(signal: dict) -> dict:
    import random
    roi_realized = max(0.0, float(signal.get("roi",0.0)) * 0.6 - random.uniform(0.0, 0.0003))
    profit_usd = roi_realized * float(signal.get("size_usd", BASE_COLLATERAL_USD))
    pos = {
        "symbol": signal.get("symbol"), "strategy": signal.get("strategy"),
        "roi": roi_realized, "profit_usd": round(profit_usd, 2),
        "closed": True, "entry_ts": int(time.time()) - 300, "exit_ts": int(time.time()),
        "stop_hit": False
    }
    _append_json(POSITIONS_LOG, pos)
    return pos

# ---------- Standalone run (manual test in learning mode) ----------
if __name__ == "__main__":
    run_learning_cycle()
    samples = [
        {"symbol":"BTCUSDT","roi":0.008,"confidence":0.65,"regime":"volatile","strategy":"breakout","size_usd":BASE_COLLATERAL_USD},
        {"symbol":"ETHUSDT","roi":0.006,"confidence":0.62,"regime":"stable","strategy":"mean_reversion","size_usd":BASE_COLLATERAL_USD},
        {"symbol":"TRXUSDT","roi":0.004,"confidence":0.58,"regime":"choppy","strategy":"sentiment_fusion","size_usd":BASE_COLLATERAL_USD},
        {"symbol":"SOLUSDT","roi":0.007,"confidence":0.66,"regime":"volatile","strategy":"breakout","size_usd":BASE_COLLATERAL_USD},
        {"symbol":"AVAXUSDT","roi":0.006,"confidence":0.61,"regime":"volatile","strategy":"breakout","size_usd":BASE_COLLATERAL_USD},
        {"symbol":"DOTUSDT","roi":0.005,"confidence":0.60,"regime":"stable","strategy":"trend_follow","size_usd":BASE_COLLATERAL_USD},
        {"symbol":"XRPUSDT","roi":0.006,"confidence":0.60,"regime":"stable","strategy":"mean_reversion","size_usd":BASE_COLLATERAL_USD},
        {"symbol":"ADAUSDT","roi":0.005,"confidence":0.57,"regime":"choppy","strategy":"sentiment_fusion","size_usd":BASE_COLLATERAL_USD},
        {"symbol":"DOGEUSDT","roi":0.004,"confidence":0.55,"regime":"choppy","strategy":"momentum_scalp","size_usd":BASE_COLLATERAL_USD},
        {"symbol":"BNBUSDT","roi":0.006,"confidence":0.63,"regime":"stable","strategy":"breakout","size_usd":BASE_COLLATERAL_USD},
        {"symbol":"MATICUSDT","roi":0.005,"confidence":0.58,"regime":"stable","strategy":"trend_follow","size_usd":BASE_COLLATERAL_USD},
    ]
    for sample in samples:
        stats = realized_outcomes_summary(sample["symbol"])
        learning_execute(sample, stats, simulate_execution_fn=simple_simulation)
    print("Unified intelligence upgrade (learning mode) executed for all 11 coins. Decisions logged.")
