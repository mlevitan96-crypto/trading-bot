# src/symbol_allocation_intelligence.py
#
# v6.1 Symbol Allocation Intelligence (Review Trades + Non-Trades, Dynamic Reallocation, Governance Wiring)
# Purpose:
#   - Learn from both action (executed trades) and inaction (blocked/shadow signals) to optimize symbol-level allocations
#   - Identify winners/losers per symbol and strategy; reallocate capital dynamically with profit/risk gates
#   - Propose enabling/disabling strategies per symbol, adjust weights/sizing, and log every decision transparently
#   - Auto-revert allocations if degradation occurs post-change
#
# Design principles:
#   - Profit-first: proposals only activate when profit/risk gates pass; automatic reverts if short-window results degrade
#   - Smart-YES posture: reduce over-filtering by preserving minimum-pass lanes while redirecting capital from chronic losers
#   - Evidence-driven: use realized PnL, win rate, fee drag, and missed-profit counterfactuals for reallocation
#
# Integration:
#   from src.symbol_allocation_intelligence import run_symbol_allocation_cycle
#   res = run_symbol_allocation_cycle()
#   digest["email_body"] += "\n\n" + res["email_body"]
#
# Inputs:
#   logs/executed_trades.jsonl     # {ts, symbol, strategy_id, pnl_pct, net_pnl, fees, leverage, side}
#   logs/strategy_signals.jsonl    # {ts, symbol, ofi_score, composite, sentiment_score, breakout_strength, status, block_reason}
#   logs/learning_updates.jsonl    # regime, verdict, prior proposals/intents
#   live_config.json               # runtime allocations and limits
#
# Outputs:
#   logs/learning_updates.jsonl: allocation_cycle, allocation_proposals, allocation_reverts, allocation_health
#   logs/knowledge_graph.jsonl: alloc_features, alloc_proposals, alloc_reverts
#   live_config.json runtime.alloc_overlays: {per_symbol: {...}, rules, min_pass_lanes}
#
# CLI:
#   python3 src/symbol_allocation_intelligence.py

import os, json, time, statistics
from collections import defaultdict, deque
from typing import Dict, Any, List, Tuple

LOGS_DIR = "logs"
EXEC_LOG = f"{LOGS_DIR}/executed_trades.jsonl"
SIG_LOG  = f"{LOGS_DIR}/strategy_signals.jsonl"
LEARN_LOG= f"{LOGS_DIR}/learning_updates.jsonl"
KG_LOG   = f"{LOGS_DIR}/knowledge_graph.jsonl"
LIVE_CFG = "live_config.json"

# Gates
PROMOTE_EXPECTANCY = 0.55
PROMOTE_PNL        = 0.0

# Allocation rules
MIN_TRADES_FOR_DECISION = 20
WIN_FLOOR_WINNER        = 0.52    # winners need at least 52% WR or strong net PnL
NET_PNL_FLOOR_WINNER    = 0.0     # positive net
WIN_CEILING_LOSER       = 0.35    # losers below 35% WR or strongly negative net
NET_PNL_CEILING_LOSER   = -10.0   # dollar threshold (adjust per account size)
BREAK_EVEN_BAND         = (-5.0, 5.0)

# Sizing bounds
SIZE_MIN = 0.80
SIZE_MAX = 1.20
SIZE_STEP_SMALL = 0.05
SIZE_STEP_STD   = 0.10

# Freshness thresholds (seconds)
FRESH_SIG_SECS  = 300
FRESH_EXEC_SECS = 300

def _now() -> int: return int(time.time())

def _read_json(path, default=None):
    if not os.path.exists(path): return default
    try:
        with open(path,"r") as f: return json.load(f)
    except: return default

def _write_json(path, obj):
    tmp = path + ".tmp"
    with open(tmp,"w") as f: json.dump(obj, f, indent=2)
    os.replace(tmp, path)

def _append_jsonl(path, obj):
    with open(path,"a") as f: f.write(json.dumps(obj) + "\n")

def _read_jsonl(path, limit=200000):
    rows=[]
    if not os.path.exists(path): return rows
    with open(path,"r") as f:
        for line in f:
            line=line.strip()
            if not line: continue
            try: rows.append(json.loads(line))
            except: continue
    return rows[-limit:]

def _latest_ts(rows: List[Dict[str,Any]], keys=("ts","timestamp")) -> int:
    for r in reversed(rows):
        for k in keys:
            val = r.get(k)
            if val is not None:
                try: return int(val)
                except: continue
    return 0

def _safe_mean(vals: List[float]) -> float:
    if not vals: return 0.0
    try: return statistics.mean(vals)
    except: return 0.0

def _safe_sum(vals: List[float]) -> float:
    try: return float(sum(vals))
    except: return 0.0

def _verdict() -> Tuple[str, float, float]:
    updates=_read_jsonl(LEARN_LOG, 50000)
    verdict="Neutral"; expectancy=0.5; avg_pnl_short=0.0
    for u in reversed(updates):
        if u.get("update_type")=="reverse_triage_cycle":
            summ=u.get("summary", {})
            v = summ.get("verdict", {})
            verdict = v.get("verdict","Neutral")
            expectancy = float(v.get("expectancy", 0.5))
            avg_pnl_short = float(v.get("pnl_short", {}).get("avg_pnl_pct", 0.0))
            break
    return verdict, expectancy, avg_pnl_short

def _risk_snapshot() -> Dict[str,Any]:
    trades=_read_jsonl(EXEC_LOG, 100000)
    dcut=_now()-24*60*60
    series=[float(t.get("pnl_pct",0.0)) for t in trades if int(t.get("ts",0) or 0)>=dcut]
    cum=0.0; peak=0.0; max_dd=0.0
    for r in series:
        cum+=r; peak=max(peak, cum); max_dd=max(max_dd, peak-cum)

    # exposure proxy by trade count split
    cutoff=_now()-4*60*60
    counts=defaultdict(int)
    for t in trades:
        ts=int(t.get("ts",0) or 0)
        sym=t.get("symbol")
        if not sym: continue
        if ts>=cutoff: counts[sym]+=1
    total=sum(counts.values()) or 1
    coin_exposure={sym: round(cnt/total,6) for sym,cnt in counts.items()}
    portfolio_exposure=round(sum(coin_exposure.values()),6)

    max_leverage=0.0
    for t in trades:
        try: max_leverage=max(max_leverage, float(t.get("leverage",0.0)))
        except: continue

    return {"coin_exposure":coin_exposure, "portfolio_exposure": portfolio_exposure, "max_leverage": round(max_leverage,3), "max_drawdown_24h": round(max_dd,6)}

def _regime() -> str:
    updates=_read_jsonl(LEARN_LOG, 50000)
    regime="neutral"
    for u in reversed(updates):
        if u.get("update_type")=="regime_governor_cycle":
            summ=u.get("summary",{})
            regime = (summ.get("regime") or "neutral")
            break
    return regime

def _health(sig_rows, exec_rows) -> Dict[str,Any]:
    sig_fresh = (_now()-_latest_ts(sig_rows)) <= FRESH_SIG_SECS if sig_rows else False
    exec_fresh= (_now()-_latest_ts(exec_rows))<= FRESH_EXEC_SECS if exec_rows else False
    coverage  = len(exec_rows[-2000:]) >= 50
    status = "healthy" if (sig_fresh and exec_fresh and coverage) else ("issues" if (sig_fresh or exec_fresh) else "quarantined")
    return {"signals_fresh": sig_fresh, "exec_fresh": exec_fresh, "coverage_ok": coverage, "status": status}

def _profit_gate() -> Tuple[bool, Dict[str,Any]]:
    status, expectancy, avg_pnl_short = _verdict()
    return (avg_pnl_short >= PROMOTE_PNL and expectancy >= PROMOTE_EXPECTANCY and status=="Winning"), {"status":status,"expectancy":expectancy,"avg_pnl_short":avg_pnl_short}

def _risk_gate(risk: Dict[str,Any], live: Dict[str,Any]) -> bool:
    limits = (live.get("runtime", {}).get("capital_limits") or {
        "max_exposure": 0.75, "per_coin_cap": 0.25, "max_leverage": 5.0, "max_drawdown_24h": 0.05
    })
    if risk["portfolio_exposure"] > limits["max_exposure"]: return False
    if risk["max_leverage"] > limits["max_leverage"]: return False
    if risk["max_drawdown_24h"] > limits["max_drawdown_24h"]: return False
    return True

def _symbol_stats(exec_rows: List[Dict[str,Any]]) -> Dict[str,Any]:
    by_sym=defaultdict(list)
    by_sym_strat=defaultdict(lambda: defaultdict(list))
    for t in exec_rows:
        sym=t.get("symbol"); strat=t.get("strategy_id")
        if not sym: continue
        by_sym[sym].append(t)
        if strat: by_sym_strat[sym][strat].append(t)
    stats={}
    for sym, rows in by_sym.items():
        net=_safe_sum([float(r.get("net_pnl",0.0)) for r in rows])
        wins=sum(1 for r in rows if float(r.get("pnl_pct",0.0))>0)
        wr= (wins / len(rows)) if rows else 0.0
        fees=_safe_sum([float(r.get("fees",0.0)) for r in rows])
        stats[sym]={"count": len(rows), "win_rate": round(wr,4), "net_pnl": round(net,2), "fees": round(fees,2)}
        # per-strategy slice
        per={}
        for strat, srows in by_sym_strat[sym].items():
            net_s=_safe_sum([float(r.get("net_pnl",0.0)) for r in srows])
            wr_s= (sum(1 for r in srows if float(r.get("pnl_pct",0.0))>0) / len(srows)) if srows else 0.0
            per[strat]={"count": len(srows), "win_rate": round(wr_s,4), "net_pnl": round(net_s,2)}
        stats[sym]["by_strategy"]=per
    return stats

def _missed_profit(sig_rows: List[Dict[str,Any]]) -> Dict[str,Any]:
    # Estimate missed net from blocked signals using composite*ofi proxy minus fee/slippage
    by_sym=defaultdict(lambda: {"blocked_count":0,"missed_net":0.0})
    for s in sig_rows:
        if str(s.get("status",""))=="blocked":
            sym=s.get("symbol")
            comp=float(s.get("composite",0.0)); ofi=float(s.get("ofi_score",0.0))
            fee=0.0007
            slip=0.0004
            net = (comp*ofi) - fee - slip
            by_sym[sym]["blocked_count"] += 1
            by_sym[sym]["missed_net"] += net
    # round
    for sym, v in by_sym.items():
        v["missed_net"]=round(v["missed_net"],4)
    return by_sym

def _publish_kg(subject: Dict[str,Any], predicate: str, obj: Dict[str,Any]):
    _append_jsonl(KG_LOG, {"ts": _now(), "subject": subject, "predicate": predicate, "object": obj})

def _allocation_rules(stats: Dict[str,Any], missed: Dict[str,Any], regime: str) -> Dict[str,Any]:
    # Decide enable/disable and sizing adjustments per symbol, focusing EMA-Futures, Breakout-Aggressive, Sentiment-Fusion
    alloc={}
    for sym, s in stats.items():
        count=s.get("count",0); wr=s.get("win_rate",0.0); net=s.get("net_pnl",0.0)
        by_strat=s.get("by_strategy",{})
        ema=by_strat.get("EMA-Futures", {"count":0,"win_rate":0.0,"net_pnl":0.0})
        # Default posture: enable EMA on winners, size down on break-even, disable EMA on chronic losers; give other strategies room
        decision={"enable": [], "disable": [], "size_multiplier": 1.0, "notes": []}
        if count >= MIN_TRADES_FOR_DECISION:
            # Winner condition
            if (wr >= WIN_FLOOR_WINNER and net >= NET_PNL_FLOOR_WINNER) or (ema["win_rate"] >= WIN_FLOOR_WINNER and ema["net_pnl"] >= NET_PNL_FLOOR_WINNER):
                decision["enable"] += ["EMA-Futures","Breakout-Aggressive","Sentiment-Fusion"]
                # modest size up if execution clean; regime-conditioned
                decision["size_multiplier"] = min(SIZE_MAX, 1.0 + (SIZE_STEP_SMALL if "chop" in regime else SIZE_STEP_STD))
                decision["notes"].append("winner_symbol")
            # Loser condition
            elif (wr <= WIN_CEILING_LOSER and net <= NET_PNL_CEILING_LOSER) or (ema["win_rate"] <= WIN_CEILING_LOSER and ema["net_pnl"] <= NET_PNL_CEILING_LOSER):
                decision["disable"] += ["EMA-Futures"]
                decision["enable"] += ["Breakout-Aggressive","Sentiment-Fusion"]  # let alternatives try
                decision["size_multiplier"] = max(SIZE_MIN, 1.0 - SIZE_STEP_STD)
                decision["notes"].append("loser_symbol")
            # Break-even band
            elif (BREAK_EVEN_BAND[0] <= net <= BREAK_EVEN_BAND[1]):
                decision["enable"] += ["EMA-Futures","Breakout-Aggressive","Sentiment-Fusion"]
                decision["size_multiplier"] = max(SIZE_MIN, 1.0 - SIZE_STEP_SMALL)
                decision["notes"].append("break_even_symbol")
            else:
                # Mixed results: default enable alternatives, keep EMA but no size-up
                decision["enable"] += ["EMA-Futures","Breakout-Aggressive","Sentiment-Fusion"]
                decision["size_multiplier"] = 1.0
                decision["notes"].append("mixed_symbol")
        else:
            # Not enough data: keep shadow learning for EMA, allow others cautiously
            decision["enable"] += ["Breakout-Aggressive","Sentiment-Fusion"]
            decision["notes"].append("insufficient_data")
        # Consider missed profit (blocked signals implying loosening)
        mp=missed.get(sym, {"blocked_count":0,"missed_net":0.0})
        if mp["blocked_count"] >= 10 and mp["missed_net"] > 0.02:
            decision["notes"].append("missed_profit_signal")
            # Indicate loosening filters (handled by other modules), keep allocation permissive
        alloc[sym]=decision
    return alloc

def _profit_guard_reverts(exec_rows: List[Dict[str,Any]], intents: List[Dict[str,Any]]) -> List[Dict[str,Any]]:
    # If post-change window shows degradation, revert proposed alloc intents
    recent=exec_rows[-10:]
    if not recent: return []
    wins=sum(1 for t in recent if float(t.get("pnl_pct",0.0))>0)
    net=sum(float(t.get("net_pnl",0.0)) for t in recent)
    reverts=[]
    if len(recent)>=10 and (wins/len(recent) < 0.40 or net < -10.0):
        for i in intents:
            reverts.append({"type":"revert_allocation_intent","symbol": i.get("symbol"),"reason":"profit_guard_degradation"})
    if reverts:
        _append_jsonl(LEARN_LOG, {"ts": _now(), "update_type":"allocation_reverts", "reverts": reverts})
        _publish_kg({"overlay":"allocation"}, "reverts", {"reverts": reverts})
    return reverts

def run_symbol_allocation_cycle() -> Dict[str,Any]:
    # Read inputs
    exec_rows=_read_jsonl(EXEC_LOG, 100000)
    sig_rows =_read_jsonl(SIG_LOG,  100000)
    live=_read_json(LIVE_CFG, default={}) or {}
    rt=live.get("runtime", {}) or {}
    live["runtime"]=rt

    # Health
    health=_health(sig_rows, exec_rows)
    _append_jsonl(LEARN_LOG, {"ts": _now(), "update_type":"allocation_health", "health": health})
    _publish_kg({"overlay":"allocation"}, "health", health)
    if health["status"]=="quarantined":
        email="=== Symbol Allocation Intelligence ===\nStatus: 🛑 Quarantined (stale/insufficient inputs)\nNo allocation changes proposed."
        summary={"ts":_now(),"health":health,"email_body":email}
        _append_jsonl(LEARN_LOG, {"ts": summary["ts"], "update_type":"allocation_cycle", "summary": {k:v for k,v in summary.items() if k!='email_body'}})
        return summary

    regime=_regime()
    risk=_risk_snapshot()
    profit_ok, verdict_meta=_profit_gate()
    risk_ok=_risk_gate(risk, live)

    # Compute stats and missed profit
    stats=_symbol_stats(exec_rows)
    missed=_missed_profit(sig_rows)

    # Allocation decisions
    alloc=_allocation_rules(stats, missed, regime)

    # Build proposals with gates
    proposals=[]
    for sym, decision in alloc.items():
        proposals.append({
            "type":"symbol_allocation",
            "symbol": sym,
            "enable": decision["enable"],
            "disable": decision["disable"],
            "size_multiplier": round(decision["size_multiplier"],3),
            "notes": decision["notes"],
            "regime": regime,
            "source": "allocation_intelligence"
        })
    # Gate promotion: publish proposals; governors apply only if gates pass
    if proposals:
        _append_jsonl(LEARN_LOG, {"ts": _now(), "update_type":"allocation_proposals", "proposals": proposals, "verdict": verdict_meta, "risk": risk})
        _publish_kg({"overlay":"allocation"}, "proposals", {"proposals": proposals})

    # Update runtime overlays (non-invasive; governors decide actual application)
    rt.setdefault("alloc_overlays", {})
    rt["alloc_overlays"]["per_symbol"]=alloc
    rt["alloc_overlays"]["rules"]={"min_trades": MIN_TRADES_FOR_DECISION, "win_floor_winner": WIN_FLOOR_WINNER, "win_ceiling_loser": WIN_CEILING_LOSER}
    rt["alloc_overlays"]["min_pass_lanes"]={"comment":"preserve smart-YES lanes; allocation shifts capital, not blanket blocks"}
    live["runtime"]=rt
    _write_json(LIVE_CFG, live)

    # Profit guard: auto-revert if recent window shows degradation (for already-applied intents in prior cycles)
    reverts=_profit_guard_reverts(exec_rows, proposals if (profit_ok and risk_ok) else [])

    # Email digest
    email=f"""
=== Symbol Allocation Intelligence ===
Regime: {regime}
Health: {health['status']} | Signals fresh: {health['signals_fresh']} | Trades fresh: {health['exec_fresh']}

Per-symbol performance:
{json.dumps(stats, indent=2)}

Missed profit (blocked signals):
{json.dumps(missed, indent=2) if missed else "None"}

Allocation proposals (enable/disable/size):
{json.dumps(proposals, indent=2) if proposals else "None"}

Gates:
Profit OK: {profit_ok} | Verdict: {json.dumps(verdict_meta, indent=2)}
Risk OK: {risk_ok} | Snapshot: {json.dumps(risk, indent=2)}

Auto-reverts (profit guard):
{json.dumps(reverts, indent=2) if reverts else "None"}
""".strip()

    summary={
        "ts": _now(),
        "regime": regime,
        "health": health,
        "stats": stats,
        "missed_profit": missed,
        "alloc": alloc,
        "proposals": proposals,
        "gates": {"profit_ok": profit_ok, "risk_ok": risk_ok, "verdict": verdict_meta, "risk": risk},
        "reverts": reverts,
        "email_body": email
    }
    _append_jsonl(LEARN_LOG, {"ts": summary["ts"], "update_type":"allocation_cycle", "summary": {k:v for k,v in summary.items() if k!='email_body'}})
    _publish_kg({"overlay":"allocation"}, "features_snapshot", {"regime": regime, "stats": stats, "missed_profit": missed})
    return summary

# CLI
if __name__=="__main__":
    res = run_symbol_allocation_cycle()
    print(json.dumps(res, indent=2))
    print("\n--- Email Body ---\n")
    print(res["email_body"])
