# src/v6_5_integration_patch.py
#
# v6.5.1 Integration Patch: Execution grace-direction, exposure after final sizing, fee audit scheduler
# Purpose:
#   - Fix direction context in post_open_guard() so grace enforcement is reliable
#   - Compute exposure AFTER final sizing adjustments so decisions reflect true notional
#   - Wire a fee audit scheduler to run periodically and update quarantine lists automatically
#   - Ensure signal inversion decisions propagate across the pipeline
#
# Integration hooks:
#   1) bot_cycle.py
#      from v6_5_integration_patch import size_after_adjustment, pre_entry_check, post_open_guard
#      final_notional = size_after_adjustment(symbol, strategy_id, base_notional, runtime)
#      ok, ctx = pre_entry_check(symbol, strategy_id, final_notional, pv_snapshot, runtime_limits, regime_state, verdict_status, expected_edge_hint)
#      if not ok: return
#      order_id = open_position(...)  # your existing placement
#      post_open_guard(ctx, direction=entry_side, order_id=order_id)
#
#   2) futures_signal_generator.py
#      from v6_5_integration_patch import adjust_signal_direction, propagate_signal_adjustment
#      signal = adjust_signal_direction(signal)
#      propagate_signal_adjustment(signal)  # ensure downstream modules see the updated side/strength
#
#   3) Daemon / scheduler
#      from v6_5_integration_patch import run_fee_venue_audit, run_recovery_cycle, nightly_learning_digest, start_scheduler
#      start_scheduler(interval_secs=600)  # 10 min cadence for fee audits + recovery probing
#
import os, json, time, statistics
from collections import defaultdict
from typing import Dict, Any, Tuple, List

# --- Files ---
LIVE_CFG  = "live_config.json"
LEARN_LOG = "logs/learning_updates.jsonl"
KG_LOG    = "logs/knowledge_graph.jsonl"
EXEC_LOG  = "logs/executed_trades.jsonl"
SIG_LOG   = "logs/strategy_signals.jsonl"

# --- Defaults ---
DEFAULT_LIMITS = {"max_exposure": 0.25, "max_leverage": 5.0, "max_drawdown_24h": 0.05}
GRACE_SECS = 3
LATENCY_MS_SHORT_MAX = 500
PROMOTE_EXPECTANCY = 0.55
PROMOTE_PNL        = 0.0

# --- IO helpers ---
def _now(): return int(time.time())
def _append_jsonl(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "a") as f: f.write(json.dumps(obj) + "\n")
def _read_json(path, default=None):
    if not os.path.exists(path): return default
    try:
        with open(path, "r") as f: return json.load(f)
    except: return default
def _write_json(path, obj):
    tmp = path + ".tmp"
    with open(tmp, "w") as f: json.dump(obj, f, indent=2)
    os.replace(tmp, path)
def _read_jsonl(path, limit=200000) -> List[Dict[str,Any]]:
    rows=[]
    if not os.path.exists(path): return rows
    with open(path,"r") as f:
        for line in f:
            line=line.strip()
            if not line: continue
            try: rows.append(json.loads(line))
            except: continue
    return rows[-limit:]
def _latest_ts(rows, keys=("ts","timestamp")) -> int:
    for r in reversed(rows):
        for k in keys:
            if r.get(k):
                try: return int(r.get(k))
                except: continue
    return 0

# --- Learning-safe logging ---
def _kg(subj, pred, obj):
    _append_jsonl(KG_LOG, {"ts": _now(), "subject": subj, "predicate": pred, "object": obj})
def _bus(update_type, payload):
    _append_jsonl(LEARN_LOG, {"ts": _now(), "update_type": update_type, **payload})

# --- Fee baselines + expected edge ---
def _fee_baseline(exec_rows: List[Dict[str,Any]]) -> Dict[str, Dict[str, float]]:
    by_sym=defaultdict(lambda: {"fees_sum":0.0,"slip_sum":0.0,"count":0})
    for t in exec_rows[-2000:]:
        sym=t.get("symbol"); 
        if not sym: continue
        by_sym[sym]["fees_sum"] += float(t.get("fees",0.0))
        by_sym[sym]["slip_sum"] += float(t.get("slippage", t.get("est_slippage",0.0)))
        by_sym[sym]["count"]    += 1
    out={}
    for sym,v in by_sym.items():
        c=max(v["count"],1)
        out[sym]={"avg_fee": v["fees_sum"]/c, "avg_slippage": v["slip_sum"]/c, "samples": c}
    return out

def _expected_edge_after_cost(symbol: str, strategy_id: str, expected_edge_hint: float) -> float:
    fees = _fee_baseline(_read_jsonl(EXEC_LOG, 100000))
    fb = fees.get(symbol, {"avg_fee": 1.0, "avg_slippage": 0.0008})
    live=_read_json(LIVE_CFG, default={}) or {}
    notional=float((live.get("runtime",{}) or {}).get("default_notional_usd", 1000.0))
    if abs(expected_edge_hint) < 0.05:  # treat as pct
        edge_dollars = expected_edge_hint * notional - fb["avg_fee"] - fb["avg_slippage"] * notional
    else:
        edge_dollars = expected_edge_hint - fb["avg_fee"] - fb["avg_slippage"] * notional
    return edge_dollars

# --- Sizing after adjustments (fix timing issue) ---
def size_after_adjustment(symbol: str, strategy_id: str, base_notional: float, runtime: Dict[str,Any]) -> float:
    """
    Apply sizing overlays and runtime throttles to derive FINAL notional before exposure check.
    - Accounts for stage throttles, per-symbol multipliers, fee quarantine downsizing, etc.
    """
    rt = runtime or {}
    throttle = float(rt.get("size_throttle", 1.0))
    per_symbol = ((rt.get("alloc_overlays",{}) or {}).get("per_symbol",{}) or {}).get(symbol, {})
    mult = float(per_symbol.get("size_multiplier", 1.0))
    # Quarantine downsizing (e.g., halve size)
    fee_quarantine = (rt.get("fee_quarantine",{}) or {})
    quarantine_mult = 0.5 if symbol in fee_quarantine else 1.0
    final = max(0.0, base_notional * throttle * mult * quarantine_mult)
    _bus("sizing_after_adjustment", {"symbol": symbol, "strategy_id": strategy_id, "base": base_notional, "final": final,
                                     "throttle": throttle, "mult": mult, "quarantine_mult": quarantine_mult})
    _kg({"overlay":"sizing","symbol":symbol}, "final_size", {"base": base_notional, "final": final, "factors": {"throttle": throttle, "mult": mult, "quarantine_mult": quarantine_mult}})
    return final

# --- Exposure math + guard (uses FINAL notional) ---
def _audit_exposure(symbol, position_notional, portfolio_value, limits) -> Tuple[float, float, Dict[str,Any]]:
    eps=1e-9
    pv=float(portfolio_value or 0.0)
    pos=float(position_notional or 0.0)
    cap=float(limits.get("max_exposure", DEFAULT_LIMITS["max_exposure"]))
    live=_read_json(LIVE_CFG, default={}) or {}
    fallback_pv=float((live.get("runtime",{}) or {}).get("fallback_portfolio_value", 0.0))
    pv_used = pv if pv>eps else fallback_pv if fallback_pv>eps else pv
    exposure = pos / max(pv_used, eps)
    diag={"symbol":symbol, "position_notional":pos, "portfolio_value":pv, "fallback_portfolio_value":fallback_pv, "exposure_pct": round(exposure,6), "cap": cap}
    _bus("risk_exposure_audit", {"audit": diag}); _kg({"overlay":"risk_engine"}, "exposure_audit", diag)
    return exposure, cap, diag

def _should_block_entry(exposure_pct, cap, runtime):
    enabled = bool((runtime.get("risk_caps", {}) or {}).get("exposure_cap_enabled", True))
    return enabled and exposure_pct > (cap * 1.10)  # 10% buffer

def pre_entry_check(symbol: str, strategy_id: str, final_notional: float, portfolio_value_snapshot: float,
                    runtime_limits: Dict[str,Any], regime_state: str, verdict_status: str, expected_edge_hint: float) -> Tuple[bool, Dict[str,Any]]:
    # 1) Fee-aware gating
    edge_after_cost = _expected_edge_after_cost(symbol, strategy_id, expected_edge_hint)
    fee_gate_ok = edge_after_cost >= 0.0
    # 2) Exposure audit (on final_notional)
    exposure_pct, cap, diag = _audit_exposure(symbol, final_notional, portfolio_value_snapshot, runtime_limits or DEFAULT_LIMITS)
    live=_read_json(LIVE_CFG, default={}) or {}; rt=live.get("runtime",{}) or {}
    # 3) Entry decision
    block_exposure = _should_block_entry(exposure_pct, cap, rt)
    ok = fee_gate_ok and not block_exposure
    reason = {"fee_gate_ok": fee_gate_ok, "edge_after_cost_dollars": round(edge_after_cost, 4),
              "block_exposure": block_exposure, "exposure_pct": round(exposure_pct,6)}
    _bus("pre_entry_decision", {"symbol": symbol, "strategy_id": strategy_id, "ok": ok, "reason": reason})
    _kg({"overlay":"entry_gate","symbol":symbol}, "pre_entry", {"ok": ok, "reason": reason})
    ctx={"symbol":symbol,"strategy_id":strategy_id,"grace_until": _now()+int(rt.get("post_open_grace_secs", GRACE_SECS)),
         "exposure": exposure_pct, "cap": cap}
    return ok, ctx

def post_open_guard(ctx: Dict[str,Any], direction: str, order_id: str):
    """
    Direction-aware grace enforcement. Stores grace per open order so close logic can look it up.
    """
    now=_now()
    live=_read_json(LIVE_CFG, default={}) or {}; rt=live.get("runtime",{}) or {}; live["runtime"]=rt
    rt.setdefault("grace_map", {})
    rt["grace_map"][order_id] = {"symbol": ctx["symbol"], "strategy_id": ctx["strategy_id"], "direction": direction,
                                 "grace_until": ctx["grace_until"], "exposure_pct": ctx["exposure"], "cap": ctx["cap"]}
    _write_json(LIVE_CFG, live)
    guard={"order_id": order_id, "symbol": ctx["symbol"], "direction": direction, "exposure_pct": round(ctx["exposure"],6),
           "cap": ctx["cap"], "grace_remaining_secs": max(0, ctx["grace_until"]-now)}
    _bus("post_open_guard", {"guard": guard}); _kg({"overlay":"risk_engine"}, "post_open_guard", guard)

# --- Signal direction correction + propagation ---
def _regime_allows_inversion(regime_state: str, verdict_status: str) -> bool:
    r=(regime_state or "neutral").lower()
    return (str(verdict_status or "Neutral")!="Winning") and (r in ("range","ranging","chop","neutral"))
def _too_late_to_short(signal_ts, price_ts, max_latency_ms=LATENCY_MS_SHORT_MAX) -> bool:
    try:
        return (int(price_ts)-int(signal_ts))*1000 > max_latency_ms
    except: return True

def adjust_signal_direction(signal: Dict[str,Any]) -> Dict[str,Any]:
    side=str(signal.get("side","")).upper()
    if side!="SHORT": return signal
    regime=signal.get("regime","neutral"); verdict=signal.get("verdict_status","Neutral")
    sig_ts=int(signal.get("ts",0) or 0); price_ts=int(signal.get("price_ts", sig_ts) or sig_ts)
    if not _regime_allows_inversion(regime, verdict): return signal
    if _too_late_to_short(sig_ts, price_ts):
        signal["side"]="NO_TRADE"
        signal.setdefault("overlays", []).append("short_inversion_latency_block")
    else:
        strength=float(signal.get("strength",0.0))
        signal["side"]="LONG"
        signal["strength"]=round(min(1.0, max(0.0, strength*0.85)),6)
        signal.setdefault("overlays", []).append("short_inversion_overlay")
    _bus("signal_inversion_applied", {"signal": signal}); _kg({"overlay":"signals"}, "short_inversion", signal)
    return signal

def propagate_signal_adjustment(signal: Dict[str,Any]):
    """
    Broadcast the adjusted signal to learning bus + runtime so downstream (sizing, entry gate) uses updated side/strength.
    """
    live=_read_json(LIVE_CFG, default={}) or {}; rt=live.get("runtime",{}) or {}; live["runtime"]=rt
    rt.setdefault("last_signal_adjustments", [])
    rt["last_signal_adjustments"].append({"ts": _now(), "symbol": signal.get("symbol"), "side": signal.get("side"),
                                          "strength": signal.get("strength"), "overlays": signal.get("overlays", [])})
    # Keep only recent 200
    rt["last_signal_adjustments"] = rt["last_signal_adjustments"][-200:]
    _write_json(LIVE_CFG, live)
    _bus("signal_adjustment_propagated", {"signal": signal})
    _kg({"overlay":"signals"}, "adjustment_propagated", signal)

# --- Recovery cycle (staged restart) ---
def _profit_verdict() -> Dict[str,Any]:
    updates=_read_jsonl(LEARN_LOG, 50000)
    v={"status":"Neutral","expectancy":0.5,"avg_pnl_short":0.0}
    for u in reversed(updates):
        if u.get("update_type")=="reverse_triage_cycle":
            s=u.get("summary",{}).get("verdict",{})
            v["status"]=s.get("verdict","Neutral")
            v["expectancy"]=float(s.get("expectancy",0.5))
            v["avg_pnl_short"]=float(s.get("pnl_short",{}).get("avg_pnl_pct",0.0))
            break
    return v

def _risk_snapshot(exec_rows: List[Dict[str,Any]]) -> Dict[str,Any]:
    dcut=_now()-24*60*60
    series=[float(t.get("pnl_pct",0.0)) for t in exec_rows if int(t.get("ts",0) or 0)>=dcut]
    cum=0.0; peak=0.0; max_dd=0.0
    for r in series: cum+=r; peak=max(peak,cum); max_dd=max(max_dd, peak-cum)
    counts=defaultdict(int); cutoff=_now()-4*60*60
    for t in exec_rows:
        ts=int(t.get("ts",0) or 0); sym=t.get("symbol"); 
        if sym and ts>=cutoff: counts[sym]+=1
    total=sum(counts.values()) or 1
    coin_exposure={sym: round(cnt/total,6) for sym,cnt in counts.items()}
    max_lev=max([float(t.get("leverage",0.0)) for t in exec_rows] or [0.0])
    return {"coin_exposure":coin_exposure,"portfolio_exposure":round(sum(coin_exposure.values()),6),"max_leverage":round(max_lev,3),"max_drawdown_24h":round(max_dd,6)}

def _profit_gate(verdict: Dict[str,Any]) -> bool:
    return verdict["status"]=="Winning" and verdict["expectancy"]>=PROMOTE_EXPECTANCY and verdict["avg_pnl_short"]>=PROMOTE_PNL
def _risk_gate(risk: Dict[str,Any], limits: Dict[str,Any]) -> bool:
    return not (risk["portfolio_exposure"]>limits["max_exposure"] or risk["max_leverage"]>limits["max_leverage"] or risk["max_drawdown_24h"]>limits["max_drawdown_24h"])

def _load_alloc_overlay() -> Dict[str,Any]:
    live=_read_json(LIVE_CFG, default={}) or {}
    return ((live.get("runtime",{}).get("alloc_overlays",{}) or {}).get("per_symbol") or {})

def run_recovery_cycle() -> Dict[str,Any]:
    live=_read_json(LIVE_CFG, default={}) or {}; rt=live.get("runtime",{}) or {}; live["runtime"]=rt
    
    # Check for manual override - skip if override is active
    override_until = rt.get("phase82_override_disable_until", 0)
    if _now() < override_until:
        # Override active - don't modify kill switch or protective settings
        return {"plan": {"next_stage": "override_active", "notes": ["phase82_override_active"]}, "verdict": {}, "risk": {}}
    
    exec_rows=_read_jsonl(EXEC_LOG, 100000)
    verdict=_profit_verdict(); risk=_risk_snapshot(exec_rows)
    limits=(rt.get("capital_limits") or DEFAULT_LIMITS)
    profit_ok=_profit_gate(verdict); risk_ok=_risk_gate(risk, limits)
    alloc=_load_alloc_overlay()
    winners=[s for s,dec in alloc.items() if "winner_symbol" in dec.get("notes",[])]
    break_even=[s for s,dec in alloc.items() if "break_even_symbol" in dec.get("notes",[])]
    stage=rt.get("restart_stage","frozen")
    if not (profit_ok and risk_ok):
        plan={"next_stage":"frozen","size_throttle":0.0,"enable_symbols":[],"notes":["gates_not_passed"]}
    elif stage in ("frozen","stage_a"):
        plan={"next_stage":"stage_a","size_throttle":0.25,"enable_symbols":winners,"notes":["stage_a_enable_winners"]}
    elif stage=="stage_b":
        plan={"next_stage":"stage_b","size_throttle":0.50,"enable_symbols":winners+break_even,"notes":["stage_b_enable_break_even"]}
    elif stage=="stage_c":
        plan={"next_stage":"stage_c","size_throttle":0.75,"enable_symbols":winners+break_even,"notes":["stage_c_broad_enable"]}
    else:
        plan={"next_stage":"full","size_throttle":1.00,"enable_symbols":winners+break_even,"notes":["full_resume"]}
    rt["restart_stage"]=plan["next_stage"]; rt["size_throttle"]=plan["size_throttle"]; rt["allowed_symbols"]=plan["enable_symbols"]; rt["protective_mode"]=(plan["next_stage"]!="full"); rt["kill_switch_phase82"]=(plan["next_stage"]=="frozen")
    _write_json(LIVE_CFG, live)
    _bus("recovery_cycle", {"plan": plan, "verdict": verdict, "risk": risk, "limits": limits}); _kg({"overlay":"kill_switch"}, "restart_plan", plan)
    return {"plan": plan, "verdict": verdict, "risk": risk}

# --- Fee/venue audit + quarantine + scheduler ---
def run_fee_venue_audit() -> Dict[str,Any]:
    fees=_fee_baseline(_read_jsonl(EXEC_LOG, 100000))
    high=[sym for sym, v in fees.items() if v["avg_fee"]>1.0]
    live=_read_json(LIVE_CFG, default={}) or {}; rt=live.get("runtime",{}) or {}; live["runtime"]=rt
    rt.setdefault("fee_quarantine", {})
    for sym in high:
        rt["fee_quarantine"][sym] = {"status":"quarantined","reason":"avg_fee_high","avg_fee": fees[sym]["avg_fee"], "ts": _now()}
    # Remove from quarantine if fees improved
    for sym in list(rt["fee_quarantine"].keys()):
        if sym not in high:
            rt["fee_quarantine"].pop(sym, None)
    _write_json(LIVE_CFG, live)
    _bus("fee_venue_audit", {"fees": fees, "quarantined": high}); _kg({"overlay":"fees"}, "quarantine_updates", {"symbols": high, "fees": fees})
    return {"fees": fees, "quarantined": high}

def nightly_learning_digest() -> Dict[str,Any]:
    exec_rows=_read_jsonl(EXEC_LOG, 100000); sig_rows=_read_jsonl(SIG_LOG, 100000)
    last_day=_now()-24*60*60
    trades=[t for t in exec_rows if int(t.get("ts",0) or 0)>=last_day]
    blocked=[s for s in sig_rows if str(s.get("status",""))=="blocked" and int(s.get("ts",0) or 0)>=last_day]
    wins=sum(1 for t in trades if float(t.get("pnl_pct",0.0))>0); wr= (wins/len(trades)) if trades else 0.0
    net=sum(float(t.get("net_pnl",0.0)) for t in trades)
    fees=_fee_baseline(exec_rows); live=_read_json(LIVE_CFG, default={}) or {}; notional=float((live.get("runtime",{}) or {}).get("default_notional_usd", 1000.0))
    missed=0.0
    for s in blocked:
        fb=fees.get(s.get("symbol",""), {"avg_fee":1.0,"avg_slippage":0.0008})
        missed += (float(s.get("composite",0.0))*float(s.get("ofi_score",0.0))*notional) - fb["avg_fee"] - fb["avg_slippage"]*notional
    digest={"trades_count": len(trades), "win_rate": round(wr,4), "net_pnl": round(net,2), "blocked_count": len(blocked), "missed_counterfactual_net": round(missed,2)}
    _bus("nightly_learning_digest", {"digest": digest}); _kg({"overlay":"learning_digest"}, "daily", digest)
    return digest

def start_scheduler(interval_secs: int = 600):
    """
    Simple scheduler:
      - Every interval: run fee audit and recovery cycle
      - At ~07:00 UTC: publish nightly learning digest
    """
    _bus("scheduler_start", {"interval_secs": interval_secs}); _kg({"overlay":"scheduler"}, "start", {"interval_secs": interval_secs})
    last_digest_day = None
    while True:
        try:
            run_fee_venue_audit()
            run_recovery_cycle()
            # Nightly digest near 07:00 UTC
            utc_h = int(time.gmtime().tm_hour)
            utc_d = int(time.gmtime().tm_yday)
            if utc_h == 7 and last_digest_day != utc_d:
                # Run Scenario Auto-Tuner FIRST (optimizes thresholds via historical replay)
                try:
                    from scenario_replay_auto_tuner import run_scenario_auto_tuner
                    run_scenario_auto_tuner(window_days=14, target_wr=0.40)
                except Exception as e:
                    _bus("scenario_tuner_error", {"error": str(e)})
                
                # Then run nightly digest
                nightly_learning_digest()
                
                # Finally run Profit-First Governor (adjusts allocations based on realized P&L)
                try:
                    from profit_first_governor import run_profit_first_governor
                    run_profit_first_governor(window_hours=24, target_wr=0.40, demote_wr=0.25, demote_pnl=-5.0)
                except Exception as e:
                    _bus("profit_governor_error", {"error": str(e)})
                last_digest_day = utc_d
        except Exception as e:
            _bus("scheduler_error", {"error": str(e)})
        time.sleep(interval_secs)

# --- CLI for quick testing ---
if __name__=="__main__":
    import argparse
    p=argparse.ArgumentParser()
    p.add_argument("--demo", action="store_true", help="Demonstrate sizing/exposure/check/guard path")
    p.add_argument("--fee-audit", action="store_true", help="Run fee audit once")
    p.add_argument("--recovery", action="store_true", help="Run recovery once")
    p.add_argument("--digest", action="store_true", help="Run nightly digest once")
    p.add_argument("--scheduler", action="store_true", help="Start 10-min scheduler")
    args=p.parse_args()

    if args.demo:
        live=_read_json(LIVE_CFG, default={}) or {}; rt=live.get("runtime",{}) or {}
        base=1000.0; symbol="ETHUSDT"; strat="ema_futures"; pv=4000.0
        final=size_after_adjustment(symbol, strat, base, rt)
        ok, ctx = pre_entry_check(symbol, strat, final, pv, (rt.get("capital_limits") or DEFAULT_LIMITS), "range", "Neutral", 0.008)
        print(json.dumps({"final_notional": final, "ok": ok, "ctx": ctx}, indent=2))
        if ok: post_open_guard(ctx, direction="LONG", order_id=f"demo-{_now()}")
    if args.fee_audit:
        print(json.dumps(run_fee_venue_audit(), indent=2))
    if args.recovery:
        print(json.dumps(run_recovery_cycle(), indent=2))
    if args.digest:
        print(json.dumps(nightly_learning_digest(), indent=2))
    if args.scheduler:
        start_scheduler(interval_secs=600)