# src/ecosystem_integrity_audit.py
#
# v6.3 Ecosystem Integrity Audit (full-stack integration, diagnostics, and auto-remediation)
# Purpose:
#   - Audit integration across data freshness, health checks, learning loops, trading gates, recovery, and fills
#   - Detect gaps: stale feeds, fee mismatches, missing schema fields, unwired modules, proposals without validation
#   - Publish incidents and remediation proposals; optionally apply safe fixes (toggle AUTO_FIX)
#   - Feed all findings back into learning and knowledge graph to compound reliability and profit
#
# CLI:
#   python3 src/ecosystem_integrity_audit.py

import os, json, time, statistics
from collections import defaultdict

AUTO_FIX = True  # set to False if you want suggestions only

LOGS_DIR = "logs"
EXEC_LOG = f"{LOGS_DIR}/executed_trades.jsonl"
SIG_LOG  = f"{LOGS_DIR}/strategy_signals.jsonl"
LEARN_LOG= f"{LOGS_DIR}/learning_updates.jsonl"
KG_LOG   = f"{LOGS_DIR}/knowledge_graph.jsonl"
LIVE_CFG = "live_config.json"

MODULES_EXPECTED = [
    "ofi_shadow_intelligence",
    "profit_target_sizing_intelligence",
    "symbol_allocation_intelligence",
    "kill_switch_recovery_orchestrator",
    "bot_cycle_kill_switch_integration",
    "data_sync_module"
]

def _now(): return int(time.time())

def _append_jsonl(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path,"a") as f: f.write(json.dumps(obj) + "\n")

def _read_json(path, default=None):
    if not os.path.exists(path): return default
    try:
        with open(path,"r") as f: return json.load(f)
    except: return default

def _write_json(path, obj):
    tmp = path + ".tmp"
    with open(tmp, "w") as f: json.dump(obj, f, indent=2)
    os.replace(tmp, path)

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

def _latest_ts(rows, keys=("ts","timestamp")) -> int:
    for r in reversed(rows):
        for k in keys:
            val = r.get(k)
            if val is not None:
                try: return int(val)
                except: continue
    return 0

def _safe_mean(x):
    try: return statistics.mean(x) if x else 0.0
    except: return 0.0

def _audit_data_freshness(exec_rows, sig_rows, live) -> dict:
    now=_now()
    exec_latest=_latest_ts(exec_rows)
    sig_latest=_latest_ts(sig_rows)
    exec_stale = (now - exec_latest) > 10*60  # >10 minutes stale is red
    sig_stale  = (now - sig_latest)  > 5*60   # >5 minutes stale is amber
    stale_metrics_flag = bool(live.get("runtime",{}).get("stale_metrics_flag"))
    return {
        "exec_latest_ts": exec_latest, "sig_latest_ts": sig_latest,
        "exec_stale": exec_stale, "sig_stale": sig_stale,
        "stale_metrics_flag": stale_metrics_flag
    }

def _audit_schema(exec_rows) -> dict:
    mandatory = {"symbol","ts","pnl_pct","net_pnl","strategy_id"}
    sample = exec_rows[-20:] if len(exec_rows)>=20 else exec_rows
    missing = []
    for r in sample:
        miss = [k for k in mandatory if k not in r]
        if miss: missing.extend(miss)
    return {"schema_ok": (len(missing)==0), "missing_fields": sorted(list(set(missing)))}

def _audit_fill_quality(exec_rows) -> dict:
    by_sym=defaultdict(lambda: {"fees_sum":0.0,"count":0,"slip_sum":0.0})
    for t in exec_rows[-1000:]:
        sym=t.get("symbol")
        if not sym: continue
        fee=float(t.get("fees",0.0))
        slip=float(t.get("slippage", t.get("est_slippage", 0.0)))
        by_sym[sym]["fees_sum"] += fee
        by_sym[sym]["slip_sum"]  += slip
        by_sym[sym]["count"]     += 1
    outliers=[]
    report={}
    for sym, v in by_sym.items():
        c = max(v["count"],1)
        fee_avg = v["fees_sum"]/c
        slip_avg= v["slip_sum"]/c
        report[sym]={"avg_fee": round(fee_avg,6), "avg_slippage": round(slip_avg,6), "samples": c}
        if fee_avg > 1.0 or slip_avg > 0.0010:
            outliers.append(sym)
    return {"per_symbol": report, "outliers": outliers}

def _audit_kill_switch(live) -> dict:
    rt=live.get("runtime",{}) or {}
    return {
        "phase82_on": bool(rt.get("kill_switch_phase82", False)),
        "protective_mode": bool(rt.get("protective_mode", False)),
        "restart_stage": rt.get("restart_stage","frozen"),
        "size_throttle": float(rt.get("size_throttle", 0.0)),
        "fee_diff": float(rt.get("fee_diff", 0.0))
    }

def _audit_learning_wiring(learn_rows) -> dict:
    has_validation = any(u.get("update_type") in ("validated_proposals","shadow_proposal") for u in learn_rows[-5000:])
    has_intents    = any(u.get("update_type")=="governance_intents" for u in learn_rows[-5000:])
    has_reverts    = any(u.get("update_type") in ("auto_reverts","allocation_reverts") for u in learn_rows[-5000:])
    modules_seen   = set([u.get("update_type") for u in learn_rows[-5000:] if u.get("update_type")])
    return {
        "validation_present": has_validation,
        "governance_intents_present": has_intents,
        "reverts_present": has_reverts,
        "learning_updates_seen": sorted(list(modules_seen))[:50]
    }

def _audit_modules_presence() -> dict:
    missing=[]
    for m in MODULES_EXPECTED:
        src_path = f"src/{m}.py"
        if not os.path.exists(src_path): missing.append(m)
    return {"modules_expected": MODULES_EXPECTED, "modules_missing": missing}

def _publish_incident(kind: str, details: dict):
    _append_jsonl(LEARN_LOG, {"ts": _now(), "update_type": "ecosystem_incident", "kind": kind, "details": details})
    _append_jsonl(KG_LOG, {"ts": _now(), "subject": {"overlay": "ecosystem_audit"}, "predicate": kind, "object": details})

def _apply_auto_fix(live, dfresh, schema, ks, fillq) -> list:
    actions=[]
    rt=live.get("runtime",{}) or {}
    live["runtime"]=rt

    if rt.get("stale_metrics_flag") and (not dfresh["exec_stale"] and not dfresh["sig_stale"]):
        rt["stale_metrics_flag"]=False
        actions.append({"action":"clear_stale_metrics_flag"})

    if float(rt.get("fee_diff",0.0)) >= 10.0:
        rt["fee_diff"]=0.0
        actions.append({"action":"reset_fee_diff"})

    if ks["phase82_on"] and (not dfresh["exec_stale"] and not dfresh["sig_stale"]):
        rt["restart_stage"]="stage_a"
        rt["size_throttle"]=0.25
        rt["protective_mode"]=True
        rt["kill_switch_phase82"]=False
        actions.append({"action":"stage_a_restart"})

    if not schema["schema_ok"]:
        _publish_incident("schema_mismatch", {"missing_fields": schema["missing_fields"]})
        actions.append({"action":"schema_incident_logged"})

    if fillq["outliers"]:
        _publish_incident("fill_quality_outliers", {"symbols": fillq["outliers"], "per_symbol": fillq["per_symbol"]})
        actions.append({"action":"fill_quality_incident_logged"})

    if actions:
        _write_json(LIVE_CFG, live)
    return actions

def run_audit_cycle():
    live=_read_json(LIVE_CFG, default={}) or {}
    exec_rows=_read_jsonl(EXEC_LOG, 100000)
    sig_rows =_read_jsonl(SIG_LOG,  100000)
    learn_rows=_read_jsonl(LEARN_LOG, 100000)

    dfresh=_audit_data_freshness(exec_rows, sig_rows, live)
    schema=_audit_schema(exec_rows)
    fillq =_audit_fill_quality(exec_rows)
    ks    =_audit_kill_switch(live)
    lwire =_audit_learning_wiring(learn_rows)
    mods  =_audit_modules_presence()

    actions=[]
    if AUTO_FIX:
        actions=_apply_auto_fix(live, dfresh, schema, ks, fillq)

    summary={
        "ts": _now(),
        "data_freshness": dfresh,
        "schema": schema,
        "fill_quality": fillq,
        "kill_switch": ks,
        "learning_wiring": lwire,
        "modules": mods,
        "auto_fix_actions": actions
    }

    email=f"""
=== Ecosystem Integrity Audit (v6.3) ===

🔍 DATA FRESHNESS:
  Last exec trade: {dfresh["exec_latest_ts"]} (stale: {dfresh["exec_stale"]})
  Last signal:     {dfresh["sig_latest_ts"]} (stale: {dfresh["sig_stale"]})
  Stale flag set:  {dfresh["stale_metrics_flag"]}

📊 SCHEMA INTEGRITY:
  Schema OK: {schema["schema_ok"]}
  Missing fields: {schema["missing_fields"] if schema["missing_fields"] else "None"}

💰 FILL QUALITY (recent 1000 trades):
  Outliers (high fees/slippage): {fillq["outliers"] if fillq["outliers"] else "None"}
  Per-symbol details: {json.dumps(fillq["per_symbol"], indent=2)}

🚨 KILL-SWITCH STATUS:
  Phase82 active:   {ks["phase82_on"]}
  Protective mode:  {ks["protective_mode"]}
  Restart stage:    {ks["restart_stage"]}
  Size throttle:    {ks["size_throttle"]}
  Fee diff:         ${ks["fee_diff"]:.2f}

🔗 LEARNING SYSTEM WIRING:
  Validation present:       {lwire["validation_present"]}
  Governance intents:       {lwire["governance_intents_present"]}
  Auto-reverts present:     {lwire["reverts_present"]}
  Update types seen (recent 5k): {len(lwire["learning_updates_seen"])}

🧩 MODULE PRESENCE:
  Expected modules: {len(mods["modules_expected"])}
  Missing modules:  {mods["modules_missing"] if mods["modules_missing"] else "None ✅"}

🔧 AUTO-FIX ACTIONS APPLIED:
{json.dumps(actions, indent=2) if actions else "  None (all checks passed or AUTO_FIX=False)"}
""".strip()

    summary["email_body"] = email
    _append_jsonl(LEARN_LOG, {"ts": _now(), "update_type": "ecosystem_audit_cycle", "summary": {k:v for k,v in summary.items() if k!="email_body"}})
    _append_jsonl(KG_LOG, {"ts": _now(), "subject": {"overlay": "ecosystem_audit"}, "predicate": "audit_summary", "object": summary})

    return summary

# CLI entry
if __name__=="__main__":
    res = run_audit_cycle()
    print(json.dumps(res, indent=2))
    print("\n--- Email Body ---\n")
    print(res["email_body"])
