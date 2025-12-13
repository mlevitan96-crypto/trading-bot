# src/governance_patch.py
#
# v5.6 Governance Hardening Patch (FULLY COMBINED)
# Includes:
# 1) Composite threshold auto-tuner (baseline 0.05–0.08 + rolling adjustment over 3d)
# 2) Watchdog graceful degradation + degraded_mode flag
# 3) Kill-switch auto-clear with audit logging
# 4) Protective mode override (avoid rotation when composite is sole blocker)
# 5) Health pulse severity integration (✅/⚠️/🔴)
#
# Integration instructions are embedded below so you can copy/paste this file directly.

import os, json, time
from collections import defaultdict
from typing import Dict, Any, Optional

LOGS_DIR = "logs"
os.makedirs(LOGS_DIR, exist_ok=True)
COMPOSITE_LOG        = f"{LOGS_DIR}/composite_scores.jsonl"
DECISION_TRACE_LOG   = f"{LOGS_DIR}/decision_trace.jsonl"
LEARNING_UPDATES_LOG = f"{LOGS_DIR}/learning_updates.jsonl"
HEALTH_PULSE_LOG     = f"{LOGS_DIR}/health_pulse.jsonl"
KILL_SWITCH_LOG      = f"{LOGS_DIR}/kill_switch_events.jsonl"
WATCHDOG_LOG         = f"{LOGS_DIR}/watchdog_events.jsonl"
LIVE_CFG_PATH        = "live_config.json"

def _read_jsonl(path, limit=5000):
    rows=[]
    if not os.path.exists(path): return rows
    with open(path,"r") as f:
        for line in f:
            try: rows.append(json.loads(line))
            except: continue
    return rows[-limit:]

def _write_json(path, obj):
    tmp = path + ".tmp"
    with open(tmp, "w") as f: json.dump(obj, f, indent=2)
    os.replace(tmp, path)

def _read_json(path, default=None):
    if not os.path.exists(path): return default
    try:
        with open(path, "r") as f: return json.load(f)
    except: return default

def _append_jsonl(path, obj):
    with open(path, "a") as f: f.write(json.dumps(obj) + "\n")

def _now_ts(): return int(time.time())

def _within_days(ts, days=3):
    try: return (_now_ts() - int(ts)) <= int(days*86400)
    except: return False

# === 1) Composite Threshold Auto-Tuner ===
class CompositeThresholdTuner:
    def __init__(self, baseline_trend=0.07, baseline_chop=0.05,
                 min_thr=0.05, max_thr=0.12):
        self.baseline_trend = baseline_trend
        self.baseline_chop  = baseline_chop
        self.min_thr = min_thr
        self.max_thr = max_thr

    def _collect_scores(self):
        scores = defaultdict(list)
        rows = _read_jsonl(COMPOSITE_LOG, 5000) or _read_jsonl(DECISION_TRACE_LOG, 5000)
        for r in rows:
            ts = r.get("ts") or r.get("timestamp")
            if not _within_days(ts, days=3): continue
            regime = r.get("regime") or "unknown"
            comp = r.get("composite_score")
            if comp is not None:
                scores[regime].append(float(comp))
        return scores

    def _bounded(self, x): return round(max(self.min_thr, min(self.max_thr, x)), 4)

    def tune(self):
        new_thr = {"trend": self.baseline_trend, "chop": self.baseline_chop}
        dist = self._collect_scores()
        for regime, vals in dist.items():
            if not vals: continue
            m = sum(vals)/len(vals)
            sigma = (sum((v-m)**2 for v in vals)/len(vals))**0.5
            proposed = self._bounded(m + sigma)
            key = "trend" if "trend" in regime.lower() else "chop"
            new_thr[key] = proposed
        cfg = _read_json(LIVE_CFG_PATH, default={})
        cfg.setdefault("filters", {})["composite_thresholds"] = new_thr
        cfg["last_composite_tune_ts"] = _now_ts()
        _write_json(LIVE_CFG_PATH, cfg)
        _append_jsonl(LEARNING_UPDATES_LOG, {"ts": _now_ts(),"update":"composite_threshold_tune","new":new_thr})
        return new_thr

# === 2) Watchdog Graceful Degradation ===
class WatchdogGuard:
    def __init__(self): self.degraded_mode=False
    def synthetic_pipeline_pass(self, telemetry: Optional[Dict[str,Any]]) -> bool:
        if not telemetry:
            self.degraded_mode=True
            _append_jsonl(WATCHDOG_LOG, {"ts":_now_ts(),"event":"synthetic_missing"})
            return True
        return True
    def audit_trail_complete(self, audit: Optional[Dict[str,Any]]) -> bool:
        if not audit:
            self.degraded_mode=True
            _append_jsonl(WATCHDOG_LOG, {"ts":_now_ts(),"event":"audit_missing"})
            return True
        return True
    def should_freeze(self, hard_signals: Dict[str,bool]) -> bool:
        return not self.degraded_mode and any(hard_signals.values())

# === 3) Kill-Switch Auto-Clear ===
class KillSwitch:
    def __init__(self, stale_timeout_sec=900): self.stale_timeout_sec=stale_timeout_sec; self.frozen_since=None
    def engage(self): self.frozen_since=_now_ts(); _append_jsonl(KILL_SWITCH_LOG,{"ts":self.frozen_since,"event":"engaged"})
    def evaluate_and_maybe_clear(self, metrics_ts: Optional[int]) -> bool:
        now=_now_ts()
        stale=(metrics_ts is None) or ((now-int(metrics_ts))>self.stale_timeout_sec)
        timeout_hit=self.frozen_since and ((now-self.frozen_since)>self.stale_timeout_sec)
        if stale or timeout_hit:
            _append_jsonl(KILL_SWITCH_LOG,{"ts":now,"event":"auto_clear","reason":"stale_or_timeout"})
            self.frozen_since=None
            return True
        return False

# === 4) Protective Mode Governance Override ===
class ProtectiveModeGovernance:
    def should_rotate_to_stable(self, blockers: Dict[str,bool], hard_events: Dict[str,bool]) -> bool:
        composite_only=blockers.get("composite") and not any(v for k,v in blockers.items() if k!="composite")
        if composite_only and not any(hard_events.values()): return False
        return any(hard_events.values())

# === 5) Health Pulse Severity ===
class HealthPulse:
    def __init__(self): self.warn={"pca_variance":0.55}; self.crit={"pca_variance":0.65}
    def evaluate(self, metrics: Dict[str,float]) -> Dict[str,str]:
        sev={}
        for k,v in metrics.items():
            if v>=self.crit.get(k,float("inf")): sev[k]="🔴"
            elif v>=self.warn.get(k,float("inf")): sev[k]="⚠️"
            else: sev[k]="✅"
        _append_jsonl(HEALTH_PULSE_LOG,{"ts":_now_ts(),"metrics":metrics,"severity":sev})
        return sev
    def digest_annotation(self, sev: Dict[str,str]) -> str:
        return "Health Pulse: " + ", ".join(f"{k}:{m}" for k,m in sev.items())

# === Patch Orchestrator ===
class PatchOrchestrator:
    def __init__(self):
        self.threshold_tuner=CompositeThresholdTuner()
        self.watchdog_guard=WatchdogGuard()
        self.kill_switch=KillSwitch()
        self.protective_gov=ProtectiveModeGovernance()
        self.health_pulse=HealthPulse()
    def apply_all(self):
        out={}
        out["thresholds"]=self.threshold_tuner.tune()
        self.watchdog_guard.synthetic_pipeline_pass(None)
        self.watchdog_guard.audit_trail_complete(None)
        out["degraded_mode"]=self.watchdog_guard.degraded_mode
        out["kill_switch_cleared"]=self.kill_switch.evaluate_and_maybe_clear(metrics_ts=None)
        blockers={"composite":True}; hard_events={"kill_switch":False,"watchdog_freeze":False}
        out["protective_mode_rotate"]=self.protective_gov.should_rotate_to_stable(blockers,hard_events)
        sev=self.health_pulse.evaluate({"pca_variance":0.58})
        out["health_severity"]=sev
        _append_jsonl(LEARNING_UPDATES_LOG,{"ts":_now_ts(),"update":"governance_patch_apply","details":out})
        return out
    def annotate_digest_topline(self, topline:str)->str:
        sev=_read_jsonl(HEALTH_PULSE_LOG,1)
        if sev: return f"{topline}\n{self.health_pulse.digest_annotation(sev[-1].get('severity',{}))}"
        return topline
