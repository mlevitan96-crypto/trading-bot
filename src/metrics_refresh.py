# src/metrics_refresh.py
#
# Metrics Refresh Strategy
# - Refresh metrics from trade logs
# - Enforce freshness before trading
# - Audit metrics nightly

import os, json, time

# Use absolute paths relative to project root
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOG_DIR = os.path.join(PROJECT_ROOT, "logs")
TRADE_LOG = os.path.join(LOG_DIR,"trade_log.jsonl")
POSITIONS_LOG = os.path.join(LOG_DIR,"positions_futures.json")
METRIC_LOG = os.path.join(LOG_DIR,"metrics.jsonl")
AUDIT_LOG = os.path.join(LOG_DIR,"metrics_audit.jsonl")

def _now(): return int(time.time())
def _append_jsonl(path,obj): os.makedirs(os.path.dirname(path),exist_ok=True); open(path,"a").write(json.dumps(obj)+"\n")
def _read_jsonl(path): return [json.loads(l) for l in open(path)] if os.path.exists(path) else []

# ======================================================================
# 1. Refresh Metrics from Positions Futures (actual trade data)
# ======================================================================
def refresh_metrics():
    try:
        if os.path.exists(POSITIONS_LOG):
            with open(POSITIONS_LOG, 'r') as f:
                data = json.load(f)
            trades = data.get('closed_positions', [])[-500:]
        else:
            trades = _read_jsonl(TRADE_LOG)
        
        if not trades:
            metric = {"ts":_now(),"win_rate":0.5,"expectancy":0.0}
            os.makedirs(os.path.dirname(METRIC_LOG), exist_ok=True)
            with open(METRIC_LOG, "w") as f:
                f.write(json.dumps(metric) + "\n")
            return metric

        pnl_values = []
        for t in trades:
            pnl = t.get("pnl_usd") or t.get("roi") or t.get("pnl")
            if pnl is not None:
                pnl_values.append(float(pnl))
        
        if not pnl_values:
            win_rate = 0.5
            expectancy = 0.0
        else:
            win_rate = sum(1 for p in pnl_values if p > 0) / len(pnl_values)
            expectancy = sum(pnl_values) / len(pnl_values)

        metric = {"ts":_now(),"win_rate":round(win_rate,4),"expectancy":round(expectancy,4)}
        
        os.makedirs(os.path.dirname(METRIC_LOG), exist_ok=True)
        with open(METRIC_LOG, "w") as f:
            f.write(json.dumps(metric) + "\n")
        
        return metric
    except Exception as e:
        print(f"⚠️ [METRICS] Refresh error: {e} - using safe defaults")
        metric = {"ts":_now(),"win_rate":0.5,"expectancy":0.0}
        os.makedirs(os.path.dirname(METRIC_LOG), exist_ok=True)
        with open(METRIC_LOG, "w") as f:
            f.write(json.dumps(metric) + "\n")
        return metric

# ======================================================================
# 2. Enforce Freshness Before Trading
# ======================================================================
def enforce_fresh_metrics(max_age_hours=24):
    metrics = _read_jsonl(METRIC_LOG)
    if not metrics:
        print("[METRICS] None found → refreshing...")
        return refresh_metrics()

    latest = metrics[-1]
    age_hours = (time.time()-latest["ts"])/3600
    if age_hours > max_age_hours:
        print(f"[METRICS] Stale ({age_hours:.2f}h) → refreshing...")
        return refresh_metrics()
    return latest

# ======================================================================
# 3. Nightly Metrics Audit
# ======================================================================
def audit_metrics(max_age_hours=24):
    latest = enforce_fresh_metrics(max_age_hours)
    if not latest:
        audit = {"ts":_now(),"status":"emergency","reason":"no_metrics"}
    else:
        age_hours = (time.time()-latest["ts"])/3600
        status = "ok" if age_hours<=max_age_hours else "warning"
        audit = {"ts":_now(),"status":status,"age_hours":round(age_hours,2),"metrics":latest}
    _append_jsonl(AUDIT_LOG,audit)
    return audit

# ======================================================================
# Integration Hooks for bot_cycle.py
# ======================================================================
def pre_trade_metrics_check():
    """
    Hook for bot_cycle risk management.
    Ensures metrics are fresh before trading.
    """
    latest = enforce_fresh_metrics()
    if not latest:
        print("[KILL-SWITCH] No metrics available → trading frozen")
        return {"go":False,"reason":"no_metrics"}
    age_hours = (time.time()-latest["ts"])/3600
    if age_hours > 24:
        print(f"[KILL-SWITCH] Metrics stale ({age_hours:.2f}h) → trading frozen")
        return {"go":False,"reason":"stale_metrics"}
    return {"go":True,"metrics":latest}

def nightly_metrics_audit():
    """
    Hook for bot_cycle nightly scheduler (midnight).
    """
    audit = audit_metrics()
    print(f"[METRICS-AUDIT] {json.dumps(audit,indent=2)}")
    return audit

# CLI quick run
if __name__=="__main__":
    # Example usage
    m = pre_trade_metrics_check()
    a = nightly_metrics_audit()
