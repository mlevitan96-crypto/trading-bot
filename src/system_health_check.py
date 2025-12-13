# src/system_health_check.py
#
# v5.7 System Health Check Suite
# Scope: Trades, Dashboard, Learning, Integration, Redundancy
# Output: logs/health_check.jsonl + logs/learning_updates.jsonl + email-ready summary
#
# Integration:
#   from src.system_health_check import SystemHealthCheck
#   hc = SystemHealthCheck()
#   summary = hc.run_cycle()         # call on startup, every 30 min, and nightly
#   print(summary["email_body"])     # include in consolidated email
#
# Notes:
# - No network calls; relies on standard logs/config files
# - Safe to run alongside Meta-Learning Orchestrator; read-only except remediation suggestions
# - If some logs are missing, marks status as "unknown" and surfaces a remediation checklist

import os, json, time
from collections import defaultdict
from typing import Dict, Any, List, Optional

LOGS_DIR = "logs"
os.makedirs(LOGS_DIR, exist_ok=True)

# Core logs
EXEC_LOG              = f"{LOGS_DIR}/executed_trades.jsonl"
DECISION_TRACE_LOG    = f"{LOGS_DIR}/decision_trace.jsonl"
META_GOV_LOG          = f"{LOGS_DIR}/meta_governor.jsonl"
META_LEARN_LOG        = f"{LOGS_DIR}/meta_learning.jsonl"
LEARNING_UPDATES_LOG  = f"{LOGS_DIR}/learning_updates.jsonl"
RESEARCH_DESK_LOG     = f"{LOGS_DIR}/research_desk.jsonl"
KNOWLEDGE_GRAPH_LOG   = f"{LOGS_DIR}/knowledge_graph.jsonl"
COUNTERFACTUAL_LOG    = f"{LOGS_DIR}/counterfactual_engine.jsonl"
TWIN_SYNC_LOG         = f"{LOGS_DIR}/twin_sync.jsonl"
HEALTH_CHECK_LOG      = f"{LOGS_DIR}/health_check.jsonl"

# Dashboard status (expected heartbeat producer writes here)
DASHBOARD_STATUS_LOG  = f"{LOGS_DIR}/dashboard_status.jsonl"  # optional heartbeat log

# Config
LIVE_CFG_PATH         = "live_config.json"

COINS = ["BTCUSDT","ETHUSDT","SOLUSDT","ADAUSDT","XRPUSDT","DOGEUSDT","AVAXUSDT","LINKUSDT","MATICUSDT","DOTUSDT","LTCUSDT"]

# ---------------- IO helpers ----------------
def _read_jsonl(path, limit=10000):
    rows=[]
    if not os.path.exists(path): return rows
    with open(path,"r") as f:
        for line in f:
            line=line.strip()
            if not line: continue
            try: rows.append(json.loads(line))
            except: continue
    return rows[-limit:]

def _append_jsonl(path, obj):
    with open(path,"a") as f: f.write(json.dumps(obj) + "\n")

def _read_json(path, default=None):
    if not os.path.exists(path): return default
    try:
        with open(path,"r") as f: return json.load(f)
    except: return default

def _write_json(path, obj):
    tmp = path + ".tmp"
    with open(tmp,"w") as f: json.dump(obj, f, indent=2)
    os.replace(tmp, path)

def _now(): return int(time.time())

def _mins_since(ts: Optional[int]) -> int:
    if not ts: return 10**6
    try: return int((_now() - int(ts)) / 60)
    except: return 10**6

# ---------------- Health readers ----------------
def _last_trade_ts() -> Optional[int]:
    rows = _read_jsonl(EXEC_LOG, 5000)
    if not rows: return None
    return rows[-1].get("ts") or rows[-1].get("timestamp")

def _idle_minutes_per_coin(window_mins=180) -> Dict[str,int]:
    rows = _read_jsonl(EXEC_LOG, 5000)
    cutoff = _now() - window_mins*60
    last_ts = {c: None for c in COINS}
    for r in rows:
        ts = r.get("ts") or r.get("timestamp")
        sym = r.get("asset") or r.get("symbol")
        if sym in COINS:
            last_ts[sym] = ts
    return {c: _mins_since(ts if ts and ts >= cutoff else None) for c, ts in last_ts.items()}

def _severity_from_meta_gov() -> Dict[str,str]:
    rows = _read_jsonl(META_GOV_LOG, 2000)
    for r in reversed(rows):
        sev = r.get("health", {}).get("severity", {})
        if sev: return sev
    return {"system":"⚠️"}  # default warning

def _runtime_flags() -> Dict[str,Any]:
    flags = {"degraded_mode": False, "kill_switch_cleared": True, "execution_bridge_mode": "primary"}
    rows = _read_jsonl(META_GOV_LOG, 2000)
    # Try meta-governor health first
    for r in reversed(rows):
        h = r.get("health", {})
        if "degraded_mode" in h: flags["degraded_mode"] = bool(h["degraded_mode"])
        if "kill_switch_cleared" in h: flags["kill_switch_cleared"] = bool(h["kill_switch_cleared"])
        break
    # Also check live_config runtime
    cfg = _read_json(LIVE_CFG_PATH, default={}) or {}
    rt = cfg.get("runtime", {})
    if "execution_bridge_mode" in rt: flags["execution_bridge_mode"] = rt["execution_bridge_mode"]
    if "degraded_mode" in rt: flags["degraded_mode"] = bool(rt["degraded_mode"])
    return flags

def _pca_variance_recent(default=0.5) -> float:
    rows = _read_jsonl(RESEARCH_DESK_LOG, 2000)
    for r in reversed(rows):
        var = r.get("pca_variance")
        if var is not None:
            try: return float(var)
            except: break
    return default

def _expectancy_recent(default=0.0) -> float:
    rows = _read_jsonl(META_LEARN_LOG, 1000)
    for r in reversed(rows):
        ex = r.get("expectancy", {})
        val = ex.get("score") if isinstance(ex, dict) else None
        if val is not None:
            try: return float(val)
            except: break
    return default

def _dashboard_status() -> Dict[str,Any]:
    rows = _read_jsonl(DASHBOARD_STATUS_LOG, 500)
    if not rows:
        return {"status":"unknown", "last_heartbeat_ts": None, "mins_since": None}
    hb = rows[-1]
    ts = hb.get("ts") or hb.get("timestamp")
    return {"status": hb.get("status","unknown"), "last_heartbeat_ts": ts, "mins_since": _mins_since(ts)}

def _knowledge_graph_size() -> int:
    return len(_read_jsonl(KNOWLEDGE_GRAPH_LOG, 200000))

def _learning_update_rate(window_mins=180) -> Dict[str,int]:
    rows = _read_jsonl(LEARNING_UPDATES_LOG, 10000)
    cutoff = _now() - window_mins*60
    counts = defaultdict(int)
    for r in rows:
        ts = r.get("ts") or r.get("timestamp")
        if ts and ts >= cutoff:
            counts[r.get("update_type","unknown")] += 1
    return dict(counts)

def _twin_status() -> Dict[str,Any]:
    twin_rows = _read_jsonl(TWIN_SYNC_LOG, 1000)
    if not twin_rows:
        return {"validations": 0, "last_failover": None, "last_divergence": None}
    last = twin_rows[-1]
    return {
        "validations": len(twin_rows),
        "last_failover": last.get("failover_triggered", False),
        "last_divergence": (last.get("comparison", {}) or {}).get("divergent_fields", [])
    }

def _integration_status() -> Dict[str,Any]:
    # Check module imports and scheduler hints
    modules_ok = []
    modules_err = []
    for mod in ["src.meta_governor", "src.trade_liveness_monitor", "src.profitability_governor", "src.meta_research_desk", "src.meta_learning_orchestrator", "src.counterfactual_scaling_engine"]:
        try:
            __import__(mod)
            modules_ok.append(mod)
        except Exception as e:
            modules_err.append({"module": mod, "error": str(e)[:120]})
    cfg = _read_json(LIVE_CFG_PATH, default={}) or {}
    rt = cfg.get("runtime", {})
    sched = {
        "meta_cadence_seconds": int(rt.get("meta_cadence_seconds", 1800)),
        "execution_bridge_mode": rt.get("execution_bridge_mode", "primary")
    }
    return {"modules_ok": modules_ok, "modules_err": modules_err, "scheduler": sched}

# ---------------- Scoring + suggestions ----------------
def _health_score(severity: Dict[str,str], flags: Dict[str,Any], last_trade_idle: int, dashboard: Dict[str,Any], pca_var: float, expectancy: float) -> Dict[str,Any]:
    # Simple composite score [0,100]
    penalties = 0
    if "🔴" in severity.values(): penalties += 40
    if flags.get("degraded_mode"): penalties += 20
    if not flags.get("kill_switch_cleared", True): penalties += 30
    if last_trade_idle and last_trade_idle > 120: penalties += 15
    if dashboard.get("status") in ("unknown","down"): penalties += 10
    if pca_var >= 0.60: penalties += 15
    base = 85
    score = max(0, base - penalties + int(10 * expectancy))
    status = "✅" if score >= 75 else ("⚠️" if score >= 50 else "🔴")
    return {"score": score, "status": status}

def _remediation_checklist(severity: Dict[str,str], flags: Dict[str,Any], idle_per_coin: Dict[str,int], dashboard: Dict[str,Any], integration: Dict[str,Any], pca_var: float) -> List[Dict[str,Any]]:
    items=[]
    if "🔴" in severity.values():
        items.append({"area":"Governance","action":"Investigate critical severity","hint":"Check meta_governor.jsonl last cycle for subsystem flags"})
    if flags.get("degraded_mode"):
        items.append({"area":"Runtime","action":"Clear degraded mode once safe","hint":"Confirm data feed, router, logs stable"})
    if not flags.get("kill_switch_cleared", True):
        items.append({"area":"Safety","action":"Clear kill-switch after validation","hint":"Run liveness diagnostics and small canary to confirm stability"})
    # Idle hotspots
    for sym, mins in idle_per_coin.items():
        if mins > 180:
            items.append({"area":"Resilience","action":f"Hotspot idle: {sym}","hint":"Verify signals/composite scores; consider threshold nudge if healthy"})
    # Dashboard
    if dashboard.get("status") in ("unknown","down") or (dashboard.get("mins_since") and dashboard["mins_since"] > 10):
        items.append({"area":"Dashboard","action":"Restore heartbeat","hint":"Ensure dashboard writes logs/dashboard_status.jsonl every minute"})
    # Integration modules
    if integration["modules_err"]:
        items.append({"area":"Integration","action":"Fix module import errors","hint": f"Errors: {[e['module'] for e in integration['modules_err']]}"})
    # PCA dominance
    if pca_var >= 0.60:
        items.append({"area":"Risk","action":"Brake sizing / suspend promotions","hint":"High factor dominance; wait for diversification"})
    return items

# ---------------- Email builder ----------------
def _email_body(summary: Dict[str,Any]) -> str:
    sev = summary["severity"]
    flags = summary["flags"]
    dash = summary["dashboard"]
    return f"""
=== System Health Check ===
Status: {summary['health']['status']}  Score: {summary['health']['score']}

Governance:
  Severity: {sev}
  Degraded Mode: {flags['degraded_mode']}
  Kill-Switch Cleared: {flags['kill_switch_cleared']}
  Execution Bridge: {flags['execution_bridge_mode']}

Trades:
  Last Trade Idle (mins): {summary['trades']['last_idle_minutes']}
  Idle per coin (mins): {summary['trades']['idle_per_coin']}

Dashboard:
  Status: {dash['status']}
  Last Heartbeat (mins since): {dash['mins_since']}

Learning:
  Expectancy (recent): {summary['learning']['expectancy']}
  PCA Variance: {summary['learning']['pca_variance']}
  Knowledge Graph entries: {summary['learning']['knowledge_graph_size']}
  Learning updates (180m): {summary['learning']['updates_rate_180m']}

Integration:
  Modules OK: {len(summary['integration']['modules_ok'])}
  Modules Err: {summary['integration']['modules_err']}
  Scheduler: {summary['integration']['scheduler']}

Redundancy:
  Twin validations: {summary['redundancy']['validations']}
  Last divergence fields: {summary['redundancy']['last_divergence']}
  Last failover: {summary['redundancy']['last_failover']}

Remediation Checklist:
  {summary['remediation']}
""".strip()

# ---------------- Main class ----------------
class SystemHealthCheck:
    """
    Full-system health check across Trades, Dashboard, Learning, Integration, and Redundancy.
    Produces a consolidated JSONL record and email-ready string.
    """
    def run_cycle(self) -> Dict[str,Any]:
        # Read states
        severity = _severity_from_meta_gov()
        flags    = _runtime_flags()
        last_ts  = _last_trade_ts()
        last_idle_minutes = _mins_since(last_ts)
        idle_per_coin = _idle_minutes_per_coin(180)
        dashboard = _dashboard_status()
        pca_var   = _pca_variance_recent()
        expectancy = _expectancy_recent()
        kg_size   = _knowledge_graph_size()
        updates_rate = _learning_update_rate(180)
        integration = _integration_status()
        redundancy = _twin_status()

        # Score + remediation
        health = _health_score(severity, flags, last_idle_minutes, dashboard, pca_var, expectancy)
        remediation = _remediation_checklist(severity, flags, idle_per_coin, dashboard, integration, pca_var)

        summary = {
            "ts": _now(),
            "severity": severity,
            "flags": flags,
            "trades": {"last_idle_minutes": last_idle_minutes, "idle_per_coin": idle_per_coin},
            "dashboard": dashboard,
            "learning": {
                "expectancy": expectancy,
                "pca_variance": round(pca_var,3),
                "knowledge_graph_size": kg_size,
                "updates_rate_180m": updates_rate
            },
            "integration": integration,
            "redundancy": redundancy,
            "health": health,
            "remediation": remediation
        }

        # Email string
        summary["email_body"] = _email_body(summary)

        # Persist
        _append_jsonl(HEALTH_CHECK_LOG, summary)
        _append_jsonl(LEARNING_UPDATES_LOG, {"ts": summary["ts"], "update_type":"system_health_check", "summary": {k:v for k,v in summary.items() if k!='email_body'}})

        return summary

# ---------------- CLI ----------------
if __name__ == "__main__":
    hc = SystemHealthCheck()
    res = hc.run_cycle()
    print(json.dumps(res, indent=2))
    print("\n--- Email Body ---\n")
    print(res["email_body"])
