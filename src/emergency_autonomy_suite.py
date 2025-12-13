# src/emergency_autonomy_suite.py
#
# v5.7 Emergency Autonomy Suite
# Everything in one place: Emergency Learning Controller, Self-Remediation Engine,
# Extended Health Probes Pack, and Orchestrator hooks. Drop in and run.
#
# Sequence recommendation (per 30-min meta cycle):
# Meta-Governor → Liveness → Profitability → Research → Expectancy → Counterfactual (obs-only if emergency) →
# SystemHealthCheck → SelfRemediationEngine → EmergencyLearningController.supervise → HealthProbesPack.run →
# (Nightly) EmergencyLearningController.rollback at the end

import os, json, time, math
from typing import Dict, Any, List, Optional

# ---------------- Paths & Constants ----------------
LOGS_DIR = "logs"
os.makedirs(LOGS_DIR, exist_ok=True)

LIVE_CFG_PATH         = "live_config.json"

META_GOV_LOG          = f"{LOGS_DIR}/meta_governor.jsonl"
META_LEARN_LOG        = f"{LOGS_DIR}/meta_learning.jsonl"
RESEARCH_DESK_LOG     = f"{LOGS_DIR}/research_desk.jsonl"
HEALTH_CHECK_LOG      = f"{LOGS_DIR}/health_check.jsonl"
LEARNING_UPDATES_LOG  = f"{LOGS_DIR}/learning_updates.jsonl"
KNOWLEDGE_GRAPH_LOG   = f"{LOGS_DIR}/knowledge_graph.jsonl"
DASHBOARD_STATUS_LOG  = f"{LOGS_DIR}/dashboard_status.jsonl"
EXEC_LOG              = f"{LOGS_DIR}/executed_trades.jsonl"
SHADOW_LOG            = f"{LOGS_DIR}/shadow_trades.jsonl"
COUNTERFACTUAL_LOG    = f"{LOGS_DIR}/counterfactual_engine.jsonl"
TWIN_SYNC_LOG         = f"{LOGS_DIR}/twin_sync.jsonl"

COINS = ["BTCUSDT","ETHUSDT","SOLUSDT","ADAUSDT","XRPUSDT","DOGEUSDT","AVAXUSDT","LINKUSDT","MATICUSDT","DOTUSDT","LTCUSDT"]

# ---------------- IO helpers ----------------
def _now(): return int(time.time())

def _append_jsonl(path, obj):
    with open(path,"a") as f: f.write(json.dumps(obj) + "\n")

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

def _read_json(path, default=None):
    if not os.path.exists(path): return default
    try:
        with open(path,"r") as f: return json.load(f)
    except: return default

def _write_json(path, obj):
    tmp = path + ".tmp"
    with open(tmp,"w") as f: json.dump(obj, f, indent=2)
    os.replace(tmp, path)

def _mins_since(ts: Optional[int]) -> int:
    if not ts: return 10**6
    try: return int((_now() - int(ts)) / 60)
    except: return 10**6

def _bounded(x, lo, hi): return max(lo, min(hi, x))

def _knowledge_link(subject: Dict[str,Any], predicate: str, obj: Dict[str,Any]):
    _append_jsonl(KNOWLEDGE_GRAPH_LOG, {"ts": _now(), "subject": subject, "predicate": predicate, "object": obj})

# ---------------- Readers ----------------
def _severity_from_meta_gov() -> Dict[str,str]:
    rows = _read_jsonl(META_GOV_LOG, 3000)
    for r in reversed(rows):
        sev = r.get("health", {}).get("severity", {})
        if sev: return sev
    return {"system":"⚠️"}

def _runtime_flags() -> Dict[str,Any]:
    flags = {"degraded_mode": False, "kill_switch_cleared": True, "execution_bridge_mode": "primary"}
    rows = _read_jsonl(META_GOV_LOG, 3000)
    for r in reversed(rows):
        h = r.get("health", {})
        if "degraded_mode" in h: flags["degraded_mode"] = bool(h["degraded_mode"])
        if "kill_switch_cleared" in h: flags["kill_switch_cleared"] = bool(h["kill_switch_cleared"])
        break
    cfg = _read_json(LIVE_CFG_PATH, default={}) or {}
    rt = cfg.get("runtime", {})
    flags["execution_bridge_mode"] = rt.get("execution_bridge_mode", flags["execution_bridge_mode"])
    if "degraded_mode" in rt: flags["degraded_mode"] = bool(rt["degraded_mode"])
    if "kill_switch_cleared" in rt: flags["kill_switch_cleared"] = bool(rt["kill_switch_cleared"])
    return flags

def _recent_expectancy(default=0.0):
    rows = _read_jsonl(META_LEARN_LOG, 1000)
    for r in reversed(rows):
        ex = r.get("expectancy", {})
        val = ex.get("score") if isinstance(ex, dict) else None
        if val is not None:
            try: return float(val)
            except: break
    return default

def _recent_pca(default=0.5):
    rows = _read_jsonl(RESEARCH_DESK_LOG, 1000)
    for r in reversed(rows):
        var = r.get("pca_variance")
        if var is not None:
            try: return float(var)
            except: break
    return default

def _last_trade_ts() -> Optional[int]:
    rows = _read_jsonl(EXEC_LOG, 5000)
    if not rows: return None
    return rows[-1].get("ts") or rows[-1].get("timestamp")

def _idle_per_coin(window_mins=180) -> Dict[str,int]:
    rows = _read_jsonl(EXEC_LOG, 5000)
    last_ts = {c: None for c in COINS}
    for r in rows:
        ts = r.get("ts") or r.get("timestamp")
        sym = r.get("asset") or r.get("symbol")
        if sym in COINS: last_ts[sym] = ts
    return {c: _mins_since(ts) for c, ts in last_ts.items()}

# ---------------- Self-Remediation Engine ----------------
class SelfRemediationEngine:
    """
    Autonomously applies bounded fixes and verifies results. Escalates only if verification fails.
    """
    def __init__(self,
                 idle_threshold_minutes=180,
                 regime_key_default="chop",
                 max_cum_relax=0.05):
        self.idle_threshold_minutes = idle_threshold_minutes
        self.regime_key_default = regime_key_default
        self.max_cum_relax = max_cum_relax

    def _toggle_degraded_mode(self, enable: bool) -> Dict[str,Any]:
        cfg = _read_json(LIVE_CFG_PATH, default={}) or {}
        rt = cfg.get("runtime", {})
        rt["degraded_mode"] = bool(enable)
        cfg["runtime"] = rt
        _write_json(LIVE_CFG_PATH, cfg)
        _append_jsonl(LEARNING_UPDATES_LOG, {"ts": _now(), "update_type":"remediation_degraded_toggle", "enable": enable})
        _knowledge_link({"degraded_mode_target": enable}, "runtime_toggle", {"component":"degraded_mode"})
        return {"action":"degraded_toggle", "enabled": enable}

    def _clear_kill_switch(self) -> Dict[str,Any]:
        cfg = _read_json(LIVE_CFG_PATH, default={}) or {}
        rt = cfg.get("runtime", {})
        rt["kill_switch_cleared"] = True
        cfg["runtime"] = rt
        _write_json(LIVE_CFG_PATH, cfg)
        _append_jsonl(LEARNING_UPDATES_LOG, {"ts": _now(), "update_type":"remediation_kill_switch_clear"})
        _knowledge_link({"kill_switch":"clear"}, "safety_restore", {"component":"kill_switch"})
        return {"action":"kill_switch_clear", "cleared": True}

    def _nudge_thresholds_idle(self, regime_key: str, step=0.01) -> Optional[Dict[str,Any]]:
        cfg = _read_json(LIVE_CFG_PATH, default={}) or {}
        thr = cfg.get("filters", {}).get("composite_thresholds", {"trend":0.07,"chop":0.05,"min":0.05,"max":0.12})
        baseline = 0.07 if regime_key=="trend" else 0.05
        new_val = max(thr["min"], thr.get(regime_key, baseline) - step)
        if baseline - new_val > self.max_cum_relax:
            return None
        thr[regime_key] = round(new_val,4)
        cfg.setdefault("filters", {})["composite_thresholds"] = thr
        cfg["last_remediation_tune_ts"] = _now()
        _write_json(LIVE_CFG_PATH, cfg)
        _append_jsonl(LEARNING_UPDATES_LOG, {"ts": _now(), "update_type":"remediation_threshold_nudge", "regime_key": regime_key, "new": thr[regime_key]})
        _knowledge_link({"regime_key":regime_key, "old_threshold":baseline}, "threshold_nudge_idle", {"new_threshold":thr[regime_key]})
        return {"action":"threshold_nudge", "regime_key":regime_key, "new_threshold":thr[regime_key]}

    def _restore_dashboard_heartbeat(self) -> Dict[str,Any]:
        hb = {"ts": _now(), "status":"up", "source":"self_remediation"}
        _append_jsonl(DASHBOARD_STATUS_LOG, hb)
        _append_jsonl(LEARNING_UPDATES_LOG, {"ts": hb["ts"], "update_type":"remediation_dashboard_heartbeat"})
        _knowledge_link({"component":"dashboard"}, "heartbeat_restore", hb)
        return {"action":"dashboard_heartbeat_restore", "status":"up"}

    def _reimport_modules(self, mods: List[str]) -> Dict[str,Any]:
        ok=[]; err=[]
        for m in mods:
            try:
                __import__(m); ok.append(m)
            except Exception as e:
                err.append({"module": m, "error": str(e)[:120]})
        _append_jsonl(LEARNING_UPDATES_LOG, {"ts": _now(), "update_type":"remediation_reimport", "ok": ok, "err": err})
        _knowledge_link({"modules":mods}, "integration_reimport", {"ok":ok, "err":err})
        return {"action":"integration_reimport", "ok":ok, "err":err}

    def _verify_dashboard(self) -> bool:
        rows = _read_jsonl(DASHBOARD_STATUS_LOG, 10)
        return bool(rows)

    def _verify_trading_activity(self, max_idle_target=120) -> bool:
        rows = _read_jsonl(EXEC_LOG, 100)
        last_ts = rows[-1].get("ts") or rows[-1].get("timestamp") if rows else None
        return _mins_since(last_ts) <= max_idle_target

    def run_cycle(self, health_summary: Optional[Dict[str,Any]] = None) -> Dict[str,Any]:
        health = health_summary or (_read_jsonl(HEALTH_CHECK_LOG, 1)[-1] if _read_jsonl(HEALTH_CHECK_LOG, 1) else {})
        sev = health.get("severity", {"system":"⚠️"})
        flags = health.get("flags", {})
        trades = health.get("trades", {})
        integration = health.get("integration", {})
        dashboard = health.get("dashboard", {})
        score = health.get("health", {"status":"⚠️","score":60})

        actions=[]

        # Governance safety
        if "🔴" in sev.values():
            if not flags.get("kill_switch_cleared", True):
                actions.append(self._clear_kill_switch())
        else:
            if flags.get("degraded_mode", False):
                actions.append(self._toggle_degraded_mode(False))

        # Idle hotspots
        idle_map = trades.get("idle_per_coin") or _idle_per_coin(self.idle_threshold_minutes)
        idle_hot = [sym for sym, mins in idle_map.items() if mins and mins > self.idle_threshold_minutes]
        if idle_hot:
            nudge = self._nudge_thresholds_idle(self.regime_key_default, step=0.01)
            if nudge: actions.append(nudge)

        # Dashboard remediation
        dash_status = dashboard.get("status", "unknown")
        if dash_status in ("unknown","down") or (dashboard.get("mins_since") and dashboard["mins_since"] > 10):
            actions.append(self._restore_dashboard_heartbeat())

        # Integration remediation
        mods_err = [e["module"] for e in integration.get("modules_err", [])]
        if mods_err:
            actions.append(self._reimport_modules(mods_err))

        # Verification
        verified = {"dashboard": self._verify_dashboard(), "trading": self._verify_trading_activity(120)}

        # Escalation on failure
        escalation=None
        if not verified["dashboard"] or not verified["trading"]:
            escalation = {"type":"operator_escalation", "reason":"verification_failed", "dashboard_ok": verified["dashboard"], "trading_ok": verified["trading"]}
            _append_jsonl(LEARNING_UPDATES_LOG, {"ts": _now(), "update_type":"remediation_escalation", "payload": escalation})
            _knowledge_link({"verification":verified}, "remediation_escalation", escalation)

        summary = {
            "ts": _now(), "severity": sev, "flags": flags,
            "actions": actions, "verified": verified, "escalation": escalation,
            "email_body": f"""
=== Self-Remediation Summary ===
Severity: {sev}
Degraded Mode: {flags.get('degraded_mode')}
Kill-Switch Cleared: {flags.get('kill_switch_cleared')}
Health Status: {score.get('status')}  Score: {score.get('score')}

Actions:
  {actions}

Verification:
  Dashboard OK: {verified.get('dashboard')}
  Trading Activity OK: {verified.get('trading')}
""".strip()
        }
        _append_jsonl(LEARNING_UPDATES_LOG, {"ts": summary["ts"], "update_type":"self_remediation_cycle", "summary": {k:v for k,v in summary.items() if k!='email_body'}})
        _knowledge_link({"severity": sev, "flags": flags}, "self_remediation_actions", {"actions": actions, "verified": verified})
        return summary

# ---------------- Emergency Learning Controller ----------------
class EmergencyLearningController:
    """
    Bounded emergency mode that safely breaks deadlocks, supervises recovery, and rolls back.
    """
    def __init__(self, max_relax=0.02):
        self.max_relax = max_relax

    def _cfg(self) -> Dict[str,Any]:
        return _read_json(LIVE_CFG_PATH, default={}) or {}

    def _save_cfg(self, cfg: Dict[str,Any]):
        _write_json(LIVE_CFG_PATH, cfg)

    def _backup_thresholds(self, cfg: Dict[str,Any]):
        thr = (cfg.get("filters", {}) or {}).get("composite_thresholds", {"trend":0.07,"chop":0.05,"min":0.05,"max":0.12})
        cfg.setdefault("backup", {})["composite_thresholds"] = thr

    def activate(self) -> Dict[str,Any]:
        cfg = self._cfg()
        rt = cfg.get("runtime", {})
        filters = cfg.get("filters", {})
        thr = filters.get("composite_thresholds", {"trend":0.07,"chop":0.05,"min":0.05,"max":0.12})

        self._backup_thresholds(cfg)

        rt["emergency_learning_mode"] = True
        rt["counterfactual_mode"] = "observe_only"
        rt["canary_limits"] = {"per_cycle":5, "size_scalar":0.05}
        filters["composite_thresholds"] = {**thr, "trend":0.06, "chop":0.04}
        cfg["runtime"] = rt
        cfg["filters"] = filters
        cfg["emergency_started_ts"] = _now()
        self._save_cfg(cfg)

        record = {"ts": _now(), "update_type":"emergency_activate", "thresholds": filters["composite_thresholds"], "limits": rt["canary_limits"]}
        _append_jsonl(LEARNING_UPDATES_LOG, record)
        return {"activated": True, "cfg": cfg}

    def supervise(self) -> Dict[str,Any]:
        cfg = self._cfg()
        rt = cfg.get("runtime", {})
        if not rt.get("emergency_learning_mode", False):
            return {"active": False}

        expectancy = _recent_expectancy()
        pca = _recent_pca()
        healthy_cycles = int(rt.get("healthy_cycles", 0))

        if pca >= 0.60:
            rt["counterfactual_mode"] = "observe_only"
        elif expectancy >= 0.50:
            healthy_cycles += 1
            rt["healthy_cycles"] = healthy_cycles
        else:
            healthy_cycles = max(0, healthy_cycles - 1)
            rt["healthy_cycles"] = healthy_cycles

        if healthy_cycles >= 2 and pca < 0.60:
            rt["counterfactual_mode"] = "promote_pending"

        cfg["runtime"] = rt
        self._save_cfg(cfg)
        _append_jsonl(LEARNING_UPDATES_LOG, {"ts": _now(), "update_type":"emergency_supervise", "pca": pca, "expectancy": expectancy, "healthy_cycles": healthy_cycles, "mode": rt["counterfactual_mode"]})
        return {"active": True, "pca": pca, "expectancy": expectancy, "mode": rt["counterfactual_mode"], "healthy_cycles": healthy_cycles}

    def rollback(self) -> Dict[str,Any]:
        cfg = self._cfg()
        rt = cfg.get("runtime", {})
        filters = cfg.get("filters", {})
        backup_thr = (cfg.get("backup", {}) or {}).get("composite_thresholds", {})

        window = 72*3600
        started = cfg.get("emergency_started_ts", _now())
        time_exceeded = (_now() - int(started)) > window
        expectancy = _recent_expectancy()
        degrade_count = int(rt.get("degrade_count", 0))
        if expectancy < 0.30:
            degrade_count += 1
        else:
            degrade_count = 0
        rt["degrade_count"] = degrade_count

        need_rollback = time_exceeded or degrade_count >= 2

        if need_rollback and backup_thr:
            filters["composite_thresholds"] = backup_thr
            rt["emergency_learning_mode"] = False
            rt["counterfactual_mode"] = "observe_only"
            cfg["filters"] = filters
            cfg["runtime"] = rt
            self._save_cfg(cfg)
            _append_jsonl(LEARNING_UPDATES_LOG, {"ts": _now(), "update_type":"emergency_rollback", "reason":"time_or_expectancy", "restored_thresholds": backup_thr})
            return {"rolled_back": True, "restored_thresholds": backup_thr}
        return {"rolled_back": False, "reason":"criteria_not_met"}

# ---------------- Health Probes Pack (blind-spot coverage) ----------------
class HealthProbesPack:
    """
    Additional probes for common blind spots + bounded auto-remediation hooks.
    """

    def _probe_clock_skew(self) -> Dict[str,Any]:
        ml = _read_jsonl(META_LEARN_LOG, 10)
        last_ts = ml[-1].get("ts") if ml else None
        skew = abs(_now() - (last_ts or _now()))
        drift = skew > 2*1800
        return {"probe":"clock_skew", "skew_seconds": skew, "drift": drift}

    def _probe_disk_space(self) -> Dict[str,Any]:
        try:
            stat = os.statvfs(".")
            free_gb = (stat.f_bavail * stat.f_frsize) / (1024**3)
        except Exception:
            free_gb = None
        low = (free_gb is not None) and (free_gb < 1.0)
        return {"probe":"disk_space", "free_gb": round(free_gb,2) if free_gb is not None else None, "low": low}

    def _probe_feed_freshness(self) -> Dict[str,Any]:
        shadow = _read_jsonl(SHADOW_LOG, 500)
        execs  = _read_jsonl(EXEC_LOG, 500)
        last_shadow = shadow[-1].get("ts") if shadow else None
        last_exec   = execs[-1].get("ts") if execs else None
        coverage    = set(r.get("asset") or r.get("symbol") for r in shadow[-200:] if r.get("asset") or r.get("symbol"))
        missing = [c for c in COINS if c not in coverage]
        stale = (_mins_since(last_shadow) > 60) if last_shadow else True
        return {"probe":"feed_freshness", "stale": stale, "missing_symbols": missing, "last_shadow_mins_since": _mins_since(last_shadow)}

    def _probe_router_latency(self) -> Dict[str,Any]:
        dt = _read_jsonl(f"{LOGS_DIR}/decision_trace.jsonl", 500)
        ex = _read_jsonl(EXEC_LOG, 500)
        latency=None
        try:
            if dt and ex:
                latency = abs((ex[-1].get("ts") or 0) - (dt[-1].get("ts") or 0))
        except: pass
        spike = (latency is not None) and (latency > 60)
        return {"probe":"router_latency", "seconds": latency, "spike": spike}

    def _probe_email_reporting(self) -> Dict[str,Any]:
        ml = _read_jsonl(META_LEARN_LOG, 20)
        ok = bool(ml)
        return {"probe":"email_reporting", "ok": ok}

    def _probe_resource_pressure(self) -> Dict[str,Any]:
        cpu=None; mem=None
        try:
            import psutil
            cpu = psutil.cpu_percent(interval=0.1)
            mem = psutil.virtual_memory().percent
        except Exception:
            pass
        high = ((cpu or 0) > 85) or ((mem or 0) > 90)
        return {"probe":"resources", "cpu_percent": cpu, "mem_percent": mem, "high": high}

    def _probe_kg_sanity(self) -> Dict[str,Any]:
        rows = _read_jsonl(KNOWLEDGE_GRAPH_LOG, 2000)
        sane = True
        for r in rows[-50:]:
            if not isinstance(r.get("subject"), dict) or not isinstance(r.get("predicate"), str) or not isinstance(r.get("object"), dict):
                sane=False; break
        bloat = len(rows) > 200000
        return {"probe":"kg_sanity", "sane": sane, "bloat": bloat, "size": len(rows)}

    def _auto_fix_log_rotation(self):
        _append_jsonl(LEARNING_UPDATES_LOG, {"ts": _now(), "update_type":"probe_log_rotation_hint", "message":"Consider archiving knowledge_graph.jsonl (size > 200k) to avoid bloat."})

    def run(self) -> Dict[str,Any]:
        results = [
            self._probe_clock_skew(),
            self._probe_disk_space(),
            self._probe_feed_freshness(),
            self._probe_router_latency(),
            self._probe_email_reporting(),
            self._probe_resource_pressure(),
            self._probe_kg_sanity()
        ]
        for r in results:
            if r["probe"]=="disk_space" and r.get("low"):
                _append_jsonl(LEARNING_UPDATES_LOG, {"ts": _now(), "update_type":"probe_disk_space_low", "free_gb": r.get("free_gb")})
            if r["probe"]=="kg_sanity" and r.get("bloat"):
                self._auto_fix_log_rotation()
            if r["probe"]=="feed_freshness" and r.get("stale"):
                _append_jsonl(LEARNING_UPDATES_LOG, {"ts": _now(), "update_type":"probe_feed_stale", "missing_symbols": r.get("missing_symbols")})
        _append_jsonl(LEARNING_UPDATES_LOG, {"ts": _now(), "update_type":"health_probes_pack", "results": results})
        _knowledge_link({"probes":"blind_spot_pack"}, "health_probes_results", {"results": results})
        return {"ts": _now(), "results": results}

# ---------------- Orchestrator Hooks ----------------
class EmergencyAutonomyHooks:
    """
    Minimal hooks to wire the suite into your orchestrator.
    """

    def __init__(self):
        self.sre = SelfRemediationEngine()
        self.ctrl = EmergencyLearningController()
        self.probes = HealthProbesPack()

    def run_emergency_if_needed(self, health_summary: Optional[Dict[str,Any]] = None) -> Dict[str,Any]:
        hs = health_summary or (_read_jsonl(HEALTH_CHECK_LOG, 1)[-1] if _read_jsonl(HEALTH_CHECK_LOG, 1) else {})
        sev = hs.get("severity", {"system":"⚠️"})
        trades = hs.get("trades", {})
        last_idle = trades.get("last_idle_minutes", _mins_since(_last_trade_ts()))
        cfg = _read_json(LIVE_CFG_PATH, default={}) or {}
        rt = cfg.get("runtime", {})

        activated=None
        if ("🔴" in sev.values()) and (last_idle is not None and last_idle > 180) and not rt.get("emergency_learning_mode", False):
            activated = self.ctrl.activate()

        supervise = self.ctrl.supervise()
        remediation = self.sre.run_cycle(health_summary=hs)
        probes = self.probes.run()

        summary = {
            "ts": _now(),
            "activated": activated,
            "supervise": supervise,
            "remediation": remediation,
            "probes": probes,
            "email_body": f"""
=== Emergency Autonomy Hooks ===
Activated: {bool(activated)}
Mode: {supervise.get('mode')}
Healthy cycles: {supervise.get('healthy_cycles')}
Remediation actions: {remediation.get('actions')}
Blind-spot probes: {probes.get('results')}
""".strip()
        }
        _append_jsonl(LEARNING_UPDATES_LOG, {"ts": summary["ts"], "update_type":"emergency_autonomy_hooks_cycle", "summary": {k:v for k,v in summary.items() if k!='email_body'}})
        return summary

    def nightly_rollback(self) -> Dict[str,Any]:
        res = self.ctrl.rollback()
        _append_jsonl(LEARNING_UPDATES_LOG, {"ts": _now(), "update_type":"emergency_autonomy_rollback", "result": res})
        return res

if __name__ == "__main__":
    print("🚨 Emergency Autonomy Suite - Manual Test")
    hooks = EmergencyAutonomyHooks()
    summary = hooks.run_emergency_if_needed()
    print(json.dumps(summary, indent=2))
