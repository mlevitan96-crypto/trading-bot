# src/kill_switch_recovery_orchestrator.py
#
# v6.3 Kill-Switch Recovery Orchestrator
# Purpose:
#   - Diagnose why Phase82 kill-switch/protective mode engaged (last 30–60 min)
#   - Reconcile stale metrics, fee mismatches, and data/health drift
#   - Trigger fill-quality analysis and publish incidents to the knowledge graph
#   - Stage an autonomous restart (A→B→C→Full) with profit/risk gates
#   - Feed all findings back into learning so recovery improves over time
#
# Triggers:
#   - Manual: python3 src/kill_switch_recovery_orchestrator.py
#   - Automatic: call run_ks_recovery_cycle() when kill-switch=ON or protective_mode=True
#
# Inputs:
#   logs/executed_trades.jsonl, logs/strategy_signals.jsonl, logs/learning_updates.jsonl
#   live_config.json (runtime state: kill-switch flags, limits, size throttles, allowed symbols)
#
# Outputs:
#   logs/learning_updates.jsonl: ks_diagnostics, ks_reconciliation, ks_recovery_cycle
#   logs/knowledge_graph.jsonl: ks_diagnostics, ks_reconciliation, ks_restart_plan
#   live_config.json: runtime.kill_switch_phase82, runtime.restart_stage, runtime.size_throttle, runtime.allowed_symbols
#
# Staged restart policy:
#   Stage A: 25% size, winners only
#   Stage B: 50% size, winners + break-even
#   Stage C: 75% size, most symbols (except quarantined losers)
#   Full:   100% size, all approved symbols after 2 clean gate passes
#
import os, json, time, statistics
from collections import defaultdict
from typing import Dict, Any, List, Tuple

LOGS_DIR = "logs"
EXEC_LOG = f"{LOGS_DIR}/executed_trades.jsonl"
SIG_LOG  = f"{LOGS_DIR}/strategy_signals.jsonl"
LEARN_LOG= f"{LOGS_DIR}/learning_updates.jsonl"
KG_LOG   = f"{LOGS_DIR}/knowledge_graph.jsonl"
LIVE_CFG = "live_config.json"

# Gate thresholds
PROMOTE_EXPECTANCY = 0.55
PROMOTE_PNL        = 0.0
DRAW_DOWN_LIMIT    = 0.05
FEE_MISMATCH_LIMIT = 10.0

def _now() -> int: return int(time.time())

def _append_jsonl(path: str, obj: Dict[str, Any]):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "a") as f: f.write(json.dumps(obj) + "\n")

def _read_json(path: str, default=None):
    if not os.path.exists(path): return default
    try:
        with open(path, "r") as f: return json.load(f)
    except: return default

def _write_json(path: str, obj: Dict[str, Any]):
    tmp = path + ".tmp"
    with open(tmp, "w") as f: json.dump(obj, f, indent=2)
    os.replace(tmp, path)

def _read_jsonl(path: str, limit=200000) -> List[Dict[str, Any]]:
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

def _window(rows: List[Dict[str,Any]], secs: int) -> List[Dict[str,Any]]:
    cutoff=_now()-secs
    return [r for r in rows if int(r.get("ts",0) or 0) >= cutoff]

def _risk_snapshot(exec_rows: List[Dict[str,Any]]) -> Dict[str,Any]:
    dcut=_now()-24*60*60
    series=[float(t.get("pnl_pct",0.0)) for t in exec_rows if int(t.get("ts",0) or 0)>=dcut]
    cum=0.0; peak=0.0; max_dd=0.0
    for r in series:
        cum+=r; peak=max(peak, cum); max_dd=max(max_dd, peak-cum)
    cutoff=_now()-4*60*60
    counts=defaultdict(int)
    for t in exec_rows:
        ts=int(t.get("ts",0) or 0); sym=t.get("symbol")
        if sym and ts>=cutoff: counts[sym]+=1
    total=sum(counts.values()) or 1
    coin_exposure={sym: round(cnt/total,6) for sym,cnt in counts.items()}
    max_leverage=max([float(t.get("leverage",0.0)) for t in exec_rows] or [0.0])
    return {"coin_exposure":coin_exposure,"portfolio_exposure":round(sum(coin_exposure.values()),6),"max_leverage":round(max_leverage,3),"max_drawdown_24h":round(max_dd,6)}

def _profit_verdict() -> Dict[str,Any]:
    updates=_read_jsonl(LEARN_LOG, 50000)
    verdict={"status":"Neutral","expectancy":0.5,"avg_pnl_short":0.0}
    for u in reversed(updates):
        if u.get("update_type")=="reverse_triage_cycle":
            v=u.get("summary",{}).get("verdict",{})
            verdict["status"]=v.get("verdict","Neutral")
            verdict["expectancy"]=float(v.get("expectancy",0.5))
            verdict["avg_pnl_short"]=float(v.get("pnl_short",{}).get("avg_pnl_pct",0.0))
            break
    return verdict

def _profit_gate(verdict: Dict[str,Any]) -> bool:
    return verdict["status"]=="Winning" and verdict["expectancy"]>=PROMOTE_EXPECTANCY and verdict["avg_pnl_short"]>=PROMOTE_PNL

def _risk_gate(risk: Dict[str,Any], live: Dict[str,Any]) -> bool:
    limits = (live.get("runtime", {}).get("capital_limits") or {"max_exposure":0.75,"per_coin_cap":0.25,"max_leverage":5.0,"max_drawdown_24h":DRAW_DOWN_LIMIT})
    return not (risk["portfolio_exposure"]>limits["max_exposure"] or risk["max_leverage"]>limits["max_leverage"] or risk["max_drawdown_24h"]>limits["max_drawdown_24h"])

def _fill_quality(exec_rows: List[Dict[str,Any]]) -> Dict[str,Any]:
    by_sym={"report":{}, "outliers":[]}
    tally=defaultdict(lambda: {"fees_sum":0.0,"slip_sum":0.0,"count":0})
    for t in exec_rows[-1000:]:
        sym=t.get("symbol"); 
        if not sym: continue
        fee=float(t.get("fees",0.0)); slip=float(t.get("slippage", t.get("est_slippage", 0.0)))
        tally[sym]["fees_sum"]+=fee; tally[sym]["slip_sum"]+=slip; tally[sym]["count"]+=1
    for sym,v in tally.items():
        c=max(v["count"],1); fee_avg=v["fees_sum"]/c; slip_avg=v["slip_sum"]/c
        by_sym["report"][sym]={"avg_fee": round(fee_avg,6), "avg_slippage": round(slip_avg,6), "samples": c}
        if fee_avg>1.0 or slip_avg>0.0010: by_sym["outliers"].append(sym)
    return by_sym

def _diagnose(live: Dict[str,Any], exec_rows: List[Dict[str,Any]], sig_rows: List[Dict[str,Any]]) -> Dict[str,Any]:
    last30=_window(exec_rows, 30*60); last60=_window(exec_rows, 60*60)
    recent_wr = (sum(1 for t in last30 if float(t.get("pnl_pct",0.0))>0) / (len(last30) or 1))
    recent_net= sum(float(t.get("net_pnl",0.0)) for t in last30)
    stale = bool(live.get("runtime",{}).get("stale_metrics_flag")) or ((_now()-_latest_ts(exec_rows))>6*60*60) or ((_now()-_latest_ts(sig_rows))>5*60)
    fee_diff=float(live.get("runtime",{}).get("fee_diff",0.0))
    risk=_risk_snapshot(exec_rows)
    fills=_fill_quality(exec_rows)
    causes=[]
    if stale: causes.append("stale_metrics")
    if fee_diff>=FEE_MISMATCH_LIMIT: causes.append("fee_mismatch")
    if risk["max_drawdown_24h"]>DRAW_DOWN_LIMIT: causes.append("high_drawdown")
    if recent_wr<0.40 or recent_net<-10.0: causes.append("recent_loss_cluster")
    if fills["outliers"]: causes.append("fill_quality_outliers")
    diag={"recent_wr_30m":round(recent_wr,3),"recent_net_30m":round(recent_net,2),
          "stale_metrics":stale,"fee_diff":fee_diff,"risk":risk,"fills":fills,"causes":causes,
          "exec_count_30m":len(last30),"exec_count_60m":len(last60)}
    _append_jsonl(LEARN_LOG, {"ts": _now(), "update_type": "ks_diagnostics", "diagnostics": diag})
    _append_jsonl(KG_LOG, {"ts": _now(), "subject": {"overlay":"kill_switch"}, "predicate": "diagnostics", "object": diag})
    return diag

def _reconcile(live: Dict[str,Any], diag: Dict[str,Any]) -> Dict[str,Any]:
    actions=[]
    rt=live.get("runtime",{}) or {}
    live["runtime"]=rt
    if rt.get("stale_metrics_flag"):
        rt["stale_metrics_flag"]=False
        actions.append({"action":"clear_stale_metrics_flag"})
    if float(rt.get("fee_diff",0.0))>=FEE_MISMATCH_LIMIT:
        prev=rt["fee_diff"]
        rt["fee_diff"]=0.0
        actions.append({"action":"reset_fee_diff","prev_diff":prev})
        _append_jsonl(LEARN_LOG, {"ts": _now(), "update_type": "ks_reconciliation", "details": {"reset_fee_diff": prev}})
        _append_jsonl(KG_LOG, {"ts": _now(), "subject": {"overlay":"kill_switch"}, "predicate": "fee_reconciled", "object": {"prev_diff": prev}})
    if diag.get("fills",{}).get("outliers"):
        _append_jsonl(LEARN_LOG, {"ts": _now(), "update_type": "ks_reconciliation", "details": {"fill_quality_outliers": diag["fills"]}})
        _append_jsonl(KG_LOG, {"ts": _now(), "subject": {"overlay":"kill_switch"}, "predicate": "fill_quality_incident", "object": diag["fills"]})
        actions.append({"action":"fill_quality_incident_logged","symbols":diag["fills"]["outliers"]})
    _write_json(LIVE_CFG, live)
    return {"actions": actions}

def _load_alloc_overlay() -> Dict[str,Any]:
    live=_read_json(LIVE_CFG, default={}) or {}
    return ((live.get("runtime",{}).get("alloc_overlays",{}) or {}).get("per_symbol") or {})

def _restart_plan(verdict: Dict[str,Any], risk: Dict[str,Any], alloc: Dict[str,Any], current_stage: str="frozen") -> Dict[str,Any]:
    # Decide next stage from gates and allocation overlay
    profit_ok=_profit_gate(verdict)
    live=_read_json(LIVE_CFG, default={}) or {}
    risk_ok=_risk_gate(risk, live)
    if not (profit_ok and risk_ok):
        return {"next_stage":"frozen","size_throttle":0.0,"enable_symbols":[], "notes":["gates_not_passed"]}
    winners=[s for s,dec in (alloc or {}).items() if "winner_symbol" in dec.get("notes",[])]
    break_even=[s for s,dec in (alloc or {}).items() if "break_even_symbol" in dec.get("notes",[])]
    losers=[s for s,dec in (alloc or {}).items() if "loser_symbol" in dec.get("notes",[])]
    # Stage logic
    if current_stage in ("frozen","stage_a"):
        return {"next_stage":"stage_a","size_throttle":0.25,"enable_symbols":winners, "notes":["stage_a_enable_winners","losers_quarantined", {"losers": losers}]}
    elif current_stage=="stage_b":
        return {"next_stage":"stage_b","size_throttle":0.50,"enable_symbols":winners+break_even, "notes":["stage_b_enable_break_even", {"losers": losers}]}
    elif current_stage=="stage_c":
        return {"next_stage":"stage_c","size_throttle":0.75,"enable_symbols":winners+break_even, "notes":["stage_c_broad_enable", {"losers": losers}]}
    else:
        return {"next_stage":"full","size_throttle":1.00,"enable_symbols":winners+break_even, "notes":["full_resume", {"losers": losers}]}

def _apply_plan(live: Dict[str,Any], plan: Dict[str,Any]) -> Dict[str,Any]:
    rt=live.get("runtime",{}) or {}
    live["runtime"]=rt
    
    # Check for manual override - skip if override is active
    override_until = rt.get("phase82_override_disable_until", 0)
    if _now() < override_until:
        # Override active - don't modify kill switch or protective settings
        return rt
    
    rt["restart_stage"]=plan["next_stage"]
    rt["size_throttle"]=plan["size_throttle"]
    rt["allowed_symbols"]=plan["enable_symbols"]
    rt["protective_mode"]= (plan["next_stage"]!="full")
    # Kill-switch OFF when leaving frozen; entries allowed only via allowed_symbols
    rt["kill_switch_phase82"]= (plan["next_stage"]=="frozen")
    _write_json(LIVE_CFG, live)
    return rt

def run_ks_recovery_cycle() -> Dict[str,Any]:
    live=_read_json(LIVE_CFG, default={}) or {}
    exec_rows=_read_jsonl(EXEC_LOG, 100000)
    sig_rows =_read_jsonl(SIG_LOG,  100000)

    # 1) Diagnose
    diag=_diagnose(live, exec_rows, sig_rows)

    # 2) Reconcile (clear stale, fee mismatches, log fill incidents)
    recon=_reconcile(live, diag)

    # 3) Gates snapshot
    verdict=_profit_verdict()
    risk=_risk_snapshot(exec_rows)

    # 4) Allocation overlay (winners/break-even/losers)
    alloc=_load_alloc_overlay()

    # 5) Restart plan (A/B/C/Full)
    current_stage=(live.get("runtime",{}) or {}).get("restart_stage","frozen")
    plan=_restart_plan(verdict, risk, alloc, current_stage)

    # 6) Apply plan to runtime
    rt=_apply_plan(live, plan)

    # 7) Publish cycle
    actions={"diagnostics":diag,"reconciliation":recon,"verdict":verdict,"risk":risk,"plan":plan,"runtime":rt}
    _append_jsonl(LEARN_LOG, {"ts": _now(), "update_type": "ks_recovery_cycle", "actions": actions})
    _append_jsonl(KG_LOG, {"ts": _now(), "subject": {"overlay":"kill_switch"}, "predicate": "restart_plan", "object": plan})

    # 8) Email digest body
    email=f"""
=== Kill-Switch Recovery Orchestrator ===
Restart stage: {current_stage} → {plan['next_stage']} | Size throttle: {int(plan['size_throttle']*100)}% | Protective: {rt['protective_mode']}

Diagnostics:
{json.dumps(diag, indent=2)}

Reconciliation:
{json.dumps(recon, indent=2)}

Profit/Risk gates:
Verdict: {json.dumps(verdict, indent=2)}
Risk:    {json.dumps(risk, indent=2)}

Allocation overlay winners enabled:
{json.dumps(plan['enable_symbols'], indent=2)}

Notes:
{json.dumps(plan['notes'], indent=2)}
""".strip()

    return {"ts": _now(), "actions": actions, "email_body": email}

# CLI
if __name__=="__main__":
    res=run_ks_recovery_cycle()
    print(json.dumps(res, indent=2))
    print("\n--- Email Body ---\n")
    print(res["email_body"])
