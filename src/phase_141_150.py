# src/phase_141_150.py
#
# Phases 141–150: Autonomous Phase Management Layer
# - Phase 141: Promotion Engine
# - Phase 142: Dependency Resolver
# - Phase 143: Health Monitor
# - Phase 144: Retirement Engine
# - Phase 145: Version Tracker
# - Phase 146: Performance Evaluator
# - Phase 147: Auto-Integration Scheduler
# - Phase 148: Alert System
# - Phase 149: Operator Digest
# - Phase 150: Orchestrator v3 (nightly runner)
#
# Design goals:
# - Auto-promote new phases from staging to active execution
# - Resolve dependencies and ensure correct execution order
# - Monitor health, retire failing phases, track versions
# - Evaluate performance and schedule integration
# - Alert on failures, produce operator digest
# - Orchestrate nightly, fully hands-off (ideal for paper trading)
#
# Inputs (optional, if present):
# - logs/phase_registry.json           # list of known phases, metadata, status
# - logs/phase_execution_reports.jsonl # per-phase execution outcomes
# - logs/operator_feedback.jsonl       # optional operator feedback events
# - logs/feature_store.json            # for performance correlation (optional)
# - logs/ml_training_metrics.json      # ML performance context (optional)
#
# Outputs:
# - logs/phase_promotion_events.jsonl
# - logs/phase_dependency_map.json
# - logs/phase_health_status.json
# - logs/phase_retirement_events.jsonl
# - logs/phase_version_history.json
# - logs/phase_performance_scores.json
# - logs/phase_integration_schedule.json
# - logs/phase_alerts.jsonl
# - logs/phase_operator_digest.json
# - logs/phase_orchestrator_v3.json
#
# Conventions:
# - Phase registry item example:
#   {
#     "id": 121, "name": "Microstructure Signals", "group": "alpha",
#     "status": "staging",           # staging | active | retired
#     "version": "v1.0.0",
#     "depends_on": [116],           # prerequisite phase IDs
#     "readiness": 0.0,              # 0..1 readiness score (data, deps, tests)
#     "impact_hint": 0.7,            # expected impact (0..1)
#     "error_rate": 0.0,             # rolling error rate
#     "freshness_ts": 0              # last successful run ts (for outputs)
#   }

import os, json, time, math
from statistics import mean

# ---------- Paths ----------
REGISTRY = "logs/phase_registry.json"
EXEC_REPORTS = "logs/phase_execution_reports.jsonl"
OP_FEEDBACK = "logs/operator_feedback.jsonl"

PROMOTION_LOG = "logs/phase_promotion_events.jsonl"
DEPENDENCY_MAP = "logs/phase_dependency_map.json"
HEALTH_STATUS = "logs/phase_health_status.json"
RETIREMENT_LOG = "logs/phase_retirement_events.jsonl"
VERSION_HISTORY = "logs/phase_version_history.json"
PERF_SCORES = "logs/phase_performance_scores.json"
INTEGRATION_SCHEDULE = "logs/phase_integration_schedule.json"
PHASE_ALERTS = "logs/phase_alerts.jsonl"
OP_DIGEST = "logs/phase_operator_digest.json"
ORCH_V3 = "logs/phase_orchestrator_v3.json"

# ---------- Utils ----------
def _now() -> int:
    return int(time.time())

def _read_json(path, default=None):
    return json.load(open(path)) if os.path.exists(path) else (default if default is not None else {})

def _write_json(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    json.dump(obj, open(path, "w"), indent=2)

def _read_jsonl(path):
    if not os.path.exists(path): return []
    with open(path, "r") as f:
        return [json.loads(line) for line in f if line.strip()]

def _append_jsonl(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "a") as f:
        f.write(json.dumps(obj) + "\n")

def _registry_items():
    reg = _read_json(REGISTRY, {"phases": []})
    return reg.get("phases", [])

def _update_registry(items):
    _write_json(REGISTRY, {"phases": items})

# ---------- Phase 142: Dependency Resolver ----------
def phase_dependency_resolver():
    phases = _registry_items()
    dep_map = {}
    for p in phases:
        dep_map[str(p["id"])] = {
            "depends_on": p.get("depends_on", []),
            "status": p.get("status", "staging"),
            "name": p.get("name"),
            "version": p.get("version", "v1.0.0")
        }
    _write_json(DEPENDENCY_MAP, dep_map)
    return dep_map

def _deps_satisfied(phase_id, dep_map, active_ids):
    deps = dep_map.get(str(phase_id), {}).get("depends_on", [])
    return all(d in active_ids for d in deps)

# ---------- Phase 143: Health Monitor ----------
def phase_health_monitor():
    phases = _registry_items()
    reports = _read_jsonl(EXEC_REPORTS)
    # Compute rolling error rate and freshness per phase
    by_id_reports = {}
    for r in reports[-500:]:
        pid = r.get("phase_id")
        if pid is None: continue
        by_id_reports.setdefault(pid, []).append(r)

    status = {}
    ts_now = _now()
    for p in phases:
        pid = p["id"]
        rlist = by_id_reports.get(pid, [])
        errors = sum(1 for r in rlist if r.get("status") == "error")
        total = len(rlist)
        err_rate = (errors / total) if total > 0 else 0.0
        last_success = max([r.get("ts", 0) for r in rlist if r.get("status") == "success"] or [0])
        freshness_age = (ts_now - last_success) if last_success > 0 else None
        status[str(pid)] = {
            "error_rate": round(err_rate, 4),
            "last_success_ts": last_success,
            "freshness_age_sec": freshness_age
        }
    _write_json(HEALTH_STATUS, status)
    # Persist back to registry error_rate / freshness_ts
    for p in phases:
        pid = str(p["id"])
        health = status.get(pid, {})
        p["error_rate"] = health.get("error_rate", 0.0)
        p["freshness_ts"] = health.get("last_success_ts", p.get("freshness_ts", 0))
    _update_registry(phases)
    return status

# ---------- Phase 146: Performance Evaluator ----------
def phase_performance_evaluator():
    phases = _registry_items()
    reports = _read_jsonl(EXEC_REPORTS)
    by_id = {}
    for r in reports[-500:]:
        pid = r.get("phase_id")
        if pid is None: continue
        by_id.setdefault(pid, []).append(r)

    scores = {}
    for p in phases:
        pid = p["id"]
        prs = by_id.get(pid, [])
        success_ratio = (sum(1 for r in prs if r.get("status") == "success") / max(1, len(prs))) if prs else 0.0
        impact_hint = p.get("impact_hint", 0.5)
        error_rate = p.get("error_rate", 0.0)
        # Score formula: impact * success * (1 - error) with minimum floor
        score = max(0.0, impact_hint * success_ratio * (1.0 - error_rate))
        scores[str(pid)] = {
            "phase_id": pid,
            "name": p.get("name"),
            "score": round(score, 4),
            "success_ratio": round(success_ratio, 4),
            "error_rate": round(error_rate, 4)
        }
    _write_json(PERF_SCORES, scores)
    return scores

# ---------- Phase 141: Promotion Engine ----------
def phase_promotion_engine():
    phases = _registry_items()
    dep_map = phase_dependency_resolver()
    perf_scores = _read_json(PERF_SCORES, {})
    active_ids = {p["id"] for p in phases if p.get("status") == "active"}

    promotions = []
    for p in phases:
        pid = p["id"]
        if p.get("status") != "staging":
            continue
        readiness = p.get("readiness", 0.0)
        perf = perf_scores.get(str(pid), {}).get("score", 0.0)
        deps_ok = _deps_satisfied(pid, dep_map, active_ids)
        # Promotion rule: deps_ok, readiness >= 0.6, perf >= 0.3
        if deps_ok and readiness >= 0.6 and perf >= 0.3:
            p["status"] = "active"
            promotions.append({"phase_id": pid, "action": "promoted", "ts": _now(), "reason": "deps_ok+readiness+perf"})
            _append_jsonl(PROMOTION_LOG, promotions[-1])

    # Auto-schedule staged items not ready (for later auto-promotion)
    schedule = _read_json(INTEGRATION_SCHEDULE, {"queue": []})
    for p in phases:
        if p.get("status") == "staging":
            # If dependencies not OK or readiness < threshold, put in queue with recheck time
            schedule["queue"].append({
                "phase_id": p["id"],
                "next_check_ts": _now() + 6*3600,  # re-evaluate in 6h
                "deps": dep_map.get(str(p["id"]), {}).get("depends_on", []),
                "reason": "await_deps_or_readiness",
            })
    _write_json(INTEGRATION_SCHEDULE, schedule)
    _update_registry(phases)
    return promotions

# ---------- Phase 144: Retirement Engine ----------
def phase_retirement_engine():
    phases = _registry_items()
    retirements = []
    for p in phases:
        # Retirement rule: if active, but error_rate > 0.4 OR perf score < 0.1 and stale > 24h
        if p.get("status") == "active":
            err = p.get("error_rate", 0.0)
            perf = _read_json(PERF_SCORES, {}).get(str(p["id"]), {}).get("score", 0.0)
            freshness_age = _now() - p.get("freshness_ts", 0)
            stale = freshness_age > 24*3600 if p.get("freshness_ts", 0) > 0 else True
            if err > 0.4 or (perf < 0.1 and stale):
                p["status"] = "retired"
                event = {"phase_id": p["id"], "action": "retired", "ts": _now(), "reason": "error_or_stale_or_low_perf"}
                retirements.append(event)
                _append_jsonl(RETIREMENT_LOG, event)
    _update_registry(phases)
    return retirements

# ---------- Phase 145: Version Tracker ----------
def phase_version_tracker():
    phases = _registry_items()
    history = _read_json(VERSION_HISTORY, {})
    for p in phases:
        pid = str(p["id"])
        rec = history.get(pid, {"history": []})
        # Append current snapshot (id, version, status, ts)
        snapshot = {"version": p.get("version", "v1.0.0"), "status": p.get("status", "staging"), "ts": _now()}
        rec["history"].append(snapshot)
        history[pid] = rec
    _write_json(VERSION_HISTORY, history)
    return history

# ---------- Phase 147: Auto-Integration Scheduler ----------
def phase_auto_integration_scheduler():
    schedule = _read_json(INTEGRATION_SCHEDULE, {"queue": []})
    dep_map = _read_json(DEPENDENCY_MAP, {})
    phases = _registry_items()
    active_ids = {p["id"] for p in phases if p.get("status") == "active"}

    # Re-evaluate queued items whose time has come
    now_ts = _now()
    updated_queue = []
    triggered = []
    for item in schedule.get("queue", []):
        if item.get("next_check_ts", 0) <= now_ts:
            pid = item["phase_id"]
            deps_ok = _deps_satisfied(pid, dep_map, active_ids)
            # If deps are now satisfied, boost readiness and mark for promotion attempt
            if deps_ok:
                for p in phases:
                    if p["id"] == pid and p.get("status") == "staging":
                        p["readiness"] = max(0.6, p.get("readiness", 0.5))  # bump readiness
                        triggered.append({"phase_id": pid, "action": "recheck_ready", "ts": now_ts, "deps_ok": True})
            else:
                # keep in queue and schedule next check
                item["next_check_ts"] = now_ts + 6*3600
                updated_queue.append(item)
        else:
            updated_queue.append(item)

    schedule["queue"] = updated_queue
    _write_json(INTEGRATION_SCHEDULE, schedule)
    _update_registry(phases)
    return {"triggered": triggered, "queue_len": len(updated_queue)}

# ---------- Phase 148: Alert System ----------
def phase_alert_system():
    phases = _registry_items()
    alerts = []
    for p in phases:
        # Alert on conflicting states or chronic errors
        if p.get("status") == "active" and p.get("error_rate", 0) > 0.5:
            alert = {"type": "chronic_errors", "phase_id": p["id"], "ts": _now(), "error_rate": p["error_rate"]}
            alerts.append(alert); _append_jsonl(PHASE_ALERTS, alert)
        if p.get("status") == "staging" and (p.get("readiness", 0.0) < 0.3):
            alert = {"type": "low_readiness", "phase_id": p["id"], "ts": _now(), "readiness": p.get("readiness", 0.0)}
            alerts.append(alert); _append_jsonl(PHASE_ALERTS, alert)
    return alerts

# ---------- Phase 149: Operator Digest ----------
def phase_operator_digest():
    promotions = _read_jsonl(PROMOTION_LOG)
    retirements = _read_jsonl(RETIREMENT_LOG)
    alerts = _read_jsonl(PHASE_ALERTS)
    health = _read_json(HEALTH_STATUS, {})
    perf = _read_json(PERF_SCORES, {})
    reg = _registry_items()
    counts = {
        "active": sum(1 for p in reg if p.get("status") == "active"),
        "staging": sum(1 for p in reg if p.get("status") == "staging"),
        "retired": sum(1 for p in reg if p.get("status") == "retired"),
        "promotions_24h": len([e for e in promotions if _now() - e.get("ts", 0) < 24*3600]),
        "retirements_24h": len([e for e in retirements if _now() - e.get("ts", 0) < 24*3600]),
        "alerts_24h": len([e for e in alerts if _now() - e.get("ts", 0) < 24*3600]),
    }
    digest = {
        "ts": _now(),
        "counts": counts,
        "top_at_risk": sorted(
            [{"phase_id": int(pid), "error_rate": v.get("error_rate", 0.0)} for pid, v in health.items()],
            key=lambda x: x["error_rate"], reverse=True
        )[:5],
        "top_scores": sorted(
            [{"phase_id": int(pid), "score": v.get("score", 0.0)} for pid, v in perf.items()],
            key=lambda x: x["score"], reverse=True
        )[:5]
    }
    _write_json(OP_DIGEST, digest)
    return digest

# ---------- Phase 150: Orchestrator v3 ----------
def phase_orchestrator_v3():
    # Run the whole phase management loop (ideal nightly at 2 AM)
    dep_map = phase_dependency_resolver()
    health = phase_health_monitor()
    perf = phase_performance_evaluator()
    promotions = phase_promotion_engine()
    retirements = phase_retirement_engine()
    version_hist = phase_version_tracker()
    scheduler = phase_auto_integration_scheduler()
    alerts = phase_alert_system()
    digest = phase_operator_digest()

    summary = {
        "ts": _now(),
        "dep_map_count": len(dep_map),
        "health_items": len(health),
        "perf_items": len(perf),
        "promotions": len(promotions),
        "retirements": len(retirements),
        "scheduler_queue_len": scheduler.get("queue_len", 0),
        "alerts": len(alerts),
        "digest_counts": digest.get("counts", {}),
    }
    _write_json(ORCH_V3, summary)
    return summary

# ---- Unified Runner ----
def run_phase_141_150():
    result = phase_orchestrator_v3()
    print("Phases 141–150 executed. Promotion, dependencies, health, performance, retirement, scheduler, alerts, digest, and orchestration summary updated.")
    return result

if __name__ == "__main__":
    run_phase_141_150()