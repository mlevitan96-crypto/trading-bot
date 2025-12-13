# src/critical_bug_patch.py
#
# Consolidated Critical Bug Patch + Integration Hooks
# - Full margin recompute from persisted positions
# - Proper kill switch freeze logic for stale metrics
# - Diagnostic audit wired with real portfolio inputs
# - Integration functions for bot_cycle.py

import os, json, time

# Use absolute paths relative to project root (same as metrics_refresh.py)
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOG_DIR = os.path.join(PROJECT_ROOT, "logs")
POSITIONS_FILE = os.path.join(LOG_DIR,"futures_positions.json")
METRIC_LOG = os.path.join(LOG_DIR,"metrics.jsonl")
AUDIT_LOG = os.path.join(LOG_DIR,"diagnostic_audit.jsonl")

def _now(): return int(time.time())
def _append_jsonl(path,obj): os.makedirs(os.path.dirname(path),exist_ok=True); open(path,"a").write(json.dumps(obj)+"\n")
def _read_jsonl(path): return [json.loads(l) for l in open(path)] if os.path.exists(path) else []

# ======================================================================
# 1. Full Margin Recompute
# ======================================================================
def recompute_margin(balance, reserved):
    """
    Load persisted positions and recompute used + available margin atomically.
    """
    try:
        with open(POSITIONS_FILE, 'r') as f:
            data = json.load(f)
            positions = data.get("open_positions", [])
    except (FileNotFoundError, json.JSONDecodeError):
        positions = []
    
    used_margin = sum(p.get("margin",0.0) for p in positions)
    available = balance - reserved - used_margin
    if available > balance:
        available = balance - reserved
    return {"used_margin":round(used_margin,2),"available_margin":max(0,round(available,2))}

# ======================================================================
# 2. Kill Switch Freeze Logic
# ======================================================================
def kill_switch(metrics, max_age_hours=24):
    """
    Freeze trading if any metric is older than max_age_hours.
    """
    if not metrics:
        return {"freeze":False,"reason":"no_metrics"}
    
    for m in metrics:
        age_hours = (time.time()-m.get("ts",time.time()))/3600
        if age_hours > max_age_hours:
            return {"freeze":True,"reason":"stale_metric","age_hours":round(age_hours,2)}
    return {"freeze":False,"reason":"fresh"}

# ======================================================================
# 3. Diagnostic Audit with Real Inputs
# ======================================================================
def run_diagnostic_audit(balance, reserved):
    """
    Nightly audit using real positions + metrics.
    """
    margin = recompute_margin(balance,reserved)
    metrics = _read_jsonl(METRIC_LOG)
    kill = kill_switch(metrics)

    audit = {
        "ts":_now(),
        "margin":margin,
        "kill_switch":kill,
        "positions_count":len(_read_jsonl(POSITIONS_FILE)) if os.path.exists(POSITIONS_FILE) else 0,
        "metrics_checked":len(metrics)
    }
    _append_jsonl(AUDIT_LOG,audit)
    return audit

# ======================================================================
# 4. Integration Hooks for bot_cycle.py
# ======================================================================
def risk_check(balance, reserved):
    """
    Hook for bot_cycle risk management.
    Recompute margin and enforce kill switch before trading.
    """
    margin = recompute_margin(balance,reserved)
    metrics = _read_jsonl(METRIC_LOG)
    kill = kill_switch(metrics)

    if kill["freeze"]:
        print(f"🚨 [KILL-SWITCH] Trading frozen due to {kill['reason']} (age={kill.get('age_hours','N/A')}h)")
        return {"go":False,"margin":margin,"kill":kill}
    else:
        print(f"✅ [RISK-CHECK] Margin OK: ${margin['available_margin']:.2f} available, Metrics fresh")
        return {"go":True,"margin":margin,"kill":kill}

def nightly_audit(balance, reserved):
    """
    Hook for bot_cycle nightly scheduler (e.g., midnight).
    """
    audit = run_diagnostic_audit(balance,reserved)
    print(f"🔍 [NIGHTLY-AUDIT] Margin: ${audit['margin']['available_margin']:.2f} available, ${audit['margin']['used_margin']:.2f} used | Kill switch: {audit['kill_switch']['reason']}")
    return audit

# CLI quick run
if __name__=="__main__":
    balance,reserved = 10000.0, 1000.0
    rc = risk_check(balance,reserved)
    audit = nightly_audit(balance,reserved)
    print(f"\nRisk check result: {json.dumps(rc,indent=2)}")
