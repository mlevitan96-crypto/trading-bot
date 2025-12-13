# src/trade_liveness_monitor.py
#
# v5.6 Trade Liveness + Rapid Diagnostics
# 30-minute cadence to prevent long idle periods by:
# - Verifying thresholds are loaded, correctly mapped to regime, and within observed composite score bands
# - Scanning signals across 11 coins to ensure at least one passable candidate
# - Attributing blockers (composite, watchdog, kill-switch, protective) and applying targeted fixes
# - Escalating actions at 30/60/120 minutes (warn → degraded mode → operator alert)
#
# Integration:
#   from src.trade_liveness_monitor import TradeLivenessMonitor
#   monitor = TradeLivenessMonitor()
#   monitor.run_cycle()   # call every 30 minutes via scheduler/cron
#   Or inside nightly_orchestration: run at start and end of the cycle

import os, json, time, math
from typing import Dict, Any, List, Optional

LOGS_DIR = "logs"
os.makedirs(LOGS_DIR, exist_ok=True)

EXECUTED_TRADES_LOG   = f"{LOGS_DIR}/executed_trades.jsonl"
DECISION_TRACE_LOG    = f"{LOGS_DIR}/decision_trace.jsonl"
COMPOSITE_LOG         = f"{LOGS_DIR}/composite_scores.jsonl"
LEARNING_UPDATES_LOG  = f"{LOGS_DIR}/learning_updates.jsonl"
OPERATOR_DIGEST_LOG   = f"{LOGS_DIR}/operator_digest.jsonl"
ALERTS_LOG            = f"{LOGS_DIR}/operator_alerts.jsonl"

LIVE_CFG_PATH         = "live_config.json"

# Optional: tie-ins to governance patch if present
try:
    from src.governance_patch import PatchOrchestrator
except:
    PatchOrchestrator = None

# ------------------- basic IO -------------------
def _read_jsonl(path, limit=5000):
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
    with open(path, "a") as f: f.write(json.dumps(obj) + "\n")

def _read_json(path, default=None):
    if not os.path.exists(path): return default
    try:
        with open(path,"r") as f: return json.load(f)
    except:
        return default

def _write_json(path, obj):
    tmp = path + ".tmp"
    with open(tmp, "w") as f: json.dump(obj, f, indent=2)
    os.replace(tmp, path)

def _now(): return int(time.time())

def _mins_since(ts):
    if not ts: return 10**6
    try: return int((_now() - int(ts)) / 60)
    except: return 10**6

# ------------------- helper analytics -------------------
def _last_trade_ts() -> Optional[int]:
    rows = _read_jsonl(EXECUTED_TRADES_LOG, 5000)
    if not rows: return None
    return rows[-1].get("ts") or rows[-1].get("timestamp")

def _composite_window(minutes=180) -> List[float]:
    rows = _read_jsonl(COMPOSITE_LOG, 5000) or _read_jsonl(DECISION_TRACE_LOG, 5000)
    cutoff = _now() - minutes*60
    vals=[]
    for r in rows:
        ts = r.get("ts") or r.get("timestamp")
        if ts and ts >= cutoff:
            comp = r.get("metrics",{}).get("composite_score")
            if comp is None: comp = r.get("composite_score")
            try: vals.append(float(comp))
            except: pass
    return vals

def _regime_recent() -> str:
    rows = _read_jsonl(DECISION_TRACE_LOG, 1000)
    for r in reversed(rows):
        regime = r.get("regime") or r.get("context",{}).get("regime")
        if regime: return str(regime)
    return "unknown"

def _blocker_attribution(minutes=180) -> Dict[str,int]:
    rows = _read_jsonl(DECISION_TRACE_LOG, 5000)
    cutoff = _now() - minutes*60
    counts={"composite":0,"watchdog":0,"kill_switch":0,"protective":0,"other":0}
    for r in rows:
        ts = r.get("ts") or r.get("timestamp")
        if not ts or ts < cutoff: continue
        reason = (r.get("veto_reason") or r.get("blocker") or "").lower()
        if "composite" in reason: counts["composite"]+=1
        elif "watchdog" in reason: counts["watchdog"]+=1
        elif "kill" in reason: counts["kill_switch"]+=1
        elif "protective" in reason or "stable" in reason: counts["protective"]+=1
        else: counts["other"]+=1
    return counts

# ------------------- corrective actions -------------------
def _bounded(x, lo, hi): return max(lo, min(hi, x))

def _load_thresholds() -> Dict[str,float]:
    cfg = _read_json(LIVE_CFG_PATH, default={})
    filt = (cfg or {}).get("filters", {})
    thr  = filt.get("composite_thresholds", {})
    # Ensure keys exist with sane defaults
    return {
        "trend": float(thr.get("trend", 0.07)),
        "chop":  float(thr.get("chop", 0.05)),
        "min":   float(thr.get("min", 0.05)),
        "max":   float(thr.get("max", 0.12))
    }

def _save_thresholds(new: Dict[str,float]):
    cfg = _read_json(LIVE_CFG_PATH, default={})
    cfg.setdefault("filters", {})["composite_thresholds"] = new
    cfg["last_composite_tune_ts"] = _now()
    _write_json(LIVE_CFG_PATH, cfg)
    _append_jsonl(LEARNING_UPDATES_LOG, {"ts": _now(), "update_type":"liveness_threshold_adjust", "new": new})

def _sanity_check_thresholds(regime: str, scores: List[float], thr: Dict[str,float]) -> Dict[str,Any]:
    # If scores exist, ensure threshold aligns to mean + sigma and within [min,max]
    result={"changed":False,"new":thr.copy()}
    if not scores: return result
    m = sum(scores)/len(scores)
    var = sum((v-m)**2 for v in scores)/max(1,len(scores))
    sigma = math.sqrt(var)
    proposed = _bounded(m + sigma, thr["min"], thr["max"])
    key = "trend" if "trend" in regime.lower() else ("chop" if "chop" in regime.lower() else "chop")
    if abs(proposed - thr[key]) >= 0.01:
        result["new"][key] = round(proposed, 4)
        result["changed"]=True
    return result

def _shorten_watchdog_freeze():
    cfg = _read_json(LIVE_CFG_PATH, default={})
    wd = cfg.get("watchdog", {"freeze_minutes": 15})
    wd["freeze_minutes"] = max(5, int(wd.get("freeze_minutes",15)) - 5)
    cfg["watchdog"] = wd
    _write_json(LIVE_CFG_PATH, cfg)
    _append_jsonl(LEARNING_UPDATES_LOG, {"ts": _now(), "update_type":"watchdog_freeze_shortened", "new_minutes": wd["freeze_minutes"]})

def _enable_degraded_mode():
    cfg = _read_json(LIVE_CFG_PATH, default={})
    run = cfg.get("runtime", {})
    run["degraded_mode"] = True
    run["size_scalar"] = _bounded(float(run.get("size_scalar",1.0))*0.7, 0.2, 1.0)
    cfg["runtime"] = run
    _write_json(LIVE_CFG_PATH, cfg)
    _append_jsonl(LEARNING_UPDATES_LOG, {"ts": _now(), "update_type":"degraded_mode_enable", "runtime": run})

def _operator_alert(message: str, context: Dict[str,Any]):
    _append_jsonl(ALERTS_LOG, {"ts": _now(), "level":"CRITICAL", "msg": message, "context": context})

# ------------------- liveness monitor -------------------
class TradeLivenessMonitor:
    def __init__(self, coins: Optional[List[str]]=None, min_warn=30, min_escalate=60, min_critical=120):
        self.coins = coins or ["BTCUSDT","ETHUSDT","SOLUSDT","ADAUSDT","XRPUSDT","DOGEUSDT","AVAXUSDT","LINKUSDT","MATICUSDT","DOTUSDT","LTCUSDT"]
        self.min_warn = min_warn
        self.min_escalate = min_escalate
        self.min_critical = min_critical
        self.patch = PatchOrchestrator() if PatchOrchestrator else None

    def _scan_signals(self) -> Dict[str,Any]:
        # Heuristic: look in decision_trace/composite_logs for recent passable candidates by coin
        cutoff = _now() - 60*30
        rows = _read_jsonl(COMPOSITE_LOG, 3000) or _read_jsonl(DECISION_TRACE_LOG, 3000)
        per_coin={"passable":[], "scores":{}}
        for r in rows:
            ts = r.get("ts") or r.get("timestamp")
            if not ts or ts < cutoff: continue
            sym = r.get("asset") or r.get("symbol")
            comp = r.get("metrics",{}).get("composite_score")
            if comp is None: comp = r.get("composite_score")
            try:
                val = float(comp)
            except:
                continue
            if sym in self.coins:
                per_coin["scores"].setdefault(sym, []).append(val)
        # Determine passable by comparing to current thresholds
        thr = _load_thresholds()
        regime = _regime_recent()
        key = "trend" if "trend" in regime.lower() or "stable" in regime.lower() else "chop"
        cutoff_thr = float(thr.get(key, 0.08))
        for sym, vals in per_coin["scores"].items():
            if any(v >= cutoff_thr for v in vals):
                per_coin["passable"].append(sym)
        return {"regime": regime, "thresholds": thr, "passable": per_coin["passable"], "scores": per_coin["scores"]}

    def run_cycle(self) -> Dict[str,Any]:
        last_ts = _last_trade_ts()
        idle_mins = _mins_since(last_ts)
        regime = _regime_recent()
        scores = _composite_window(180)
        thr = _load_thresholds()
        blockers = _blocker_attribution(180)

        # Step 1: Always verify thresholds → regime mapping and score alignment
        sanity = _sanity_check_thresholds(regime, scores, thr)
        if sanity["changed"]:
            _save_thresholds(sanity["new"])
            thr = sanity["new"]

        # Step 2: Rapid signal scan (ensure at least one coin is passable within 30m window)
        sig = self._scan_signals()

        # Step 3: Escalation ladder
        actions=[]
        if idle_mins >= self.min_warn:
            # Warn and nudge thresholds slightly if no passable signals
            if not sig["passable"]:
                key = "trend" if "trend" in regime.lower() or "stable" in regime.lower() else "chop"
                thr[key] = _bounded(thr[key] - 0.01, thr["min"], thr["max"])
                _save_thresholds(thr)
                actions.append({"type":"threshold_nudge","key":key,"new":thr[key]})
            # Shorten watchdog freeze if it's a common blocker
            if blockers.get("watchdog",0) > 0:
                _shorten_watchdog_freeze()
                actions.append({"type":"shorten_watchdog"})

        if idle_mins >= self.min_escalate:
            # Enable degraded mode and further relax thresholds within bounds
            _enable_degraded_mode()
            key = "trend" if "trend" in regime.lower() or "stable" in regime.lower() else "chop"
            thr[key] = _bounded(thr[key] - 0.01, thr["min"], thr["max"])
            _save_thresholds(thr)
            actions.append({"type":"degraded_mode"})
            actions.append({"type":"threshold_relax","key":key,"new":thr[key]})

        if idle_mins >= self.min_critical:
            # Operator alert with full attribution and recent metrics
            context = {"idle_minutes": idle_mins, "regime": regime, "thresholds": thr, "blockers": blockers, "passable": sig["passable"]}
            _operator_alert("Critical: No trades opened for extended period", context)
            actions.append({"type":"operator_alert"})

        # Step 4: Prepare and return liveness summary
        summary = {
            "ts": _now(),
            "idle_minutes": idle_mins,
            "regime": regime,
            "thresholds": thr,
            "blockers": blockers,
            "passable": sig["passable"],
            "actions": actions
        }

        _append_jsonl(LEARNING_UPDATES_LOG, {"ts": _now(), "update_type":"liveness_cycle", "summary": summary})
        return summary

# ------------------- CLI -------------------
if __name__ == "__main__":
    monitor = TradeLivenessMonitor()
    res = monitor.run_cycle()
    print("Liveness cycle:", json.dumps(res, indent=2))
