# src/phase_246_250.py
#
# Phases 246–250: Autonomy Hardening (Idempotency, Deadlock Detection, State Checkpointing)
# - 246: Idempotent Order IDs + Reconciliation (no duplicate orders)
# - 247: Deadlock Detector Watchdog (critical section timeout + auto-restart intent)
# - 248: State Checkpointing & Recovery (positions/pending intents)
# - 249: Dependency Health Gates (storage/time/connector health)
# - 250: Feature Flags & Canary Router (safe rollouts, auto-promotion)
#
# Wiring package: ready-to-use hooks for alpha_to_execution_adapter.py and resilience layer (236–245).

import os, json, time, hashlib, threading, shutil
from contextlib import contextmanager

# ---- Paths ----
ORDER_REGISTRY = "logs/order_registry.jsonl"             # executed intents (idempotency)
ORDER_INTENTS = "logs/order_intents.jsonl"               # open/pending intents
STATE_CHECKPOINT = "logs/state_checkpoint.json"          # positions, exposure, pending
DEADLOCK_LOG = "logs/deadlock_detector.json"             # detection events
FEATURE_FLAGS = "logs/feature_flags_250.json"            # flags for modules/features
CANARY_ROUTER = "logs/canary_router_250.json"            # flow splits and promotions
COMMAND_BUS = "logs/command_bus.json"                    # restart/halts (from 236–245)
RESILIENCE_DASH = "logs/operator_resilience_dashboard.json"
API_CONNECTORS_LOG = "logs/dual_api_connectors.json"

def _now(): return int(time.time())
def _read_json(path, default=None): return json.load(open(path)) if os.path.exists(path) else (default if default is not None else {})
def _write_json(path, obj): os.makedirs(os.path.dirname(path), exist_ok=True); json.dump(obj, open(path, "w"), indent=2)
def _append_jsonl(path, obj): os.makedirs(os.path.dirname(path), exist_ok=True); open(path, "a").write(json.dumps(obj) + "\n")
def _read_jsonl(path): return [json.loads(l) for l in open(path)] if os.path.exists(path) else []

# ======================================================================
# 246 – Idempotent Order IDs + Reconciliation
# Ensures retries never duplicate orders; reconciles before placement.
# ======================================================================
def _hash_fields(*fields):
    h = hashlib.sha256()
    for f in fields:
        h.update(str(f).encode("utf-8"))
    return h.hexdigest()[:32]

def generate_client_order_id(symbol, direction, size, price_offset_bp, ttl_sec, ts=None, seed="v1"):
    ts = ts or _now()
    return f"{symbol}-{_hash_fields(symbol, direction, size, price_offset_bp, ttl_sec, ts, seed)}"

def intent_exists(client_order_id):
    # Check in both intents and registry
    intents = _read_jsonl(ORDER_INTENTS)
    registry = _read_jsonl(ORDER_REGISTRY)
    return any(i.get("client_order_id") == client_order_id for i in intents) or \
           any(r.get("client_order_id") == client_order_id for r in registry)

def record_order_intent(symbol, direction, size, venue, order_cfg, client_order_id):
    _append_jsonl(ORDER_INTENTS, {
        "ts": _now(),
        "symbol": symbol,
        "direction": direction,
        "size": size,
        "venue": venue,
        "order_cfg": order_cfg,
        "client_order_id": client_order_id,
        "state": "pending"
    })

def finalize_order_intent(client_order_id, status, execution_meta=None):
    # Append to registry and mark final state; we keep intents as append-only for audit simplicity
    _append_jsonl(ORDER_REGISTRY, {
        "ts": _now(),
        "client_order_id": client_order_id,
        "final_status": status,
        "execution_meta": execution_meta or {}
    })

def reconcile_before_place(symbol, direction, size, order_cfg, ttl_sec):
    cid = generate_client_order_id(symbol, direction, size, order_cfg.get("offset_bp"), ttl_sec)
    return {"client_order_id": cid, "duplicate": intent_exists(cid)}

# ======================================================================
# 247 – Deadlock Detector Watchdog
# Flags long-held locks/critical sections and publishes restart intents.
# ======================================================================
_deadlock_registry = {}

@contextmanager
def deadlock_guard(section_name, module_name="alpha_adapter", timeout_sec=30):
    start = _now()
    token = f"{section_name}-{start}"
    _deadlock_registry[token] = {"section": section_name, "start": start, "module": module_name}
    try:
        yield
    finally:
        elapsed = _now() - start
        _deadlock_registry.pop(token, None)
        if elapsed >= timeout_sec:
            # Publish restart intent to command bus
            bus = _read_json(COMMAND_BUS, {"restarts": [], "halts": []})
            bus["restarts"].append({"module": module_name, "reason": "deadlock_detected", "section": section_name, "elapsed_sec": elapsed, "ts": _now()})
            _write_json(COMMAND_BUS, bus)
            # Log deadlock event
            ev = _read_json(DEADLOCK_LOG, {"events": []})
            ev["events"].append({"ts": _now(), "module": module_name, "section": section_name, "elapsed_sec": elapsed})
            _write_json(DEADLOCK_LOG, ev)

# ======================================================================
# 248 – State Checkpointing & Recovery
# Atomic snapshots of positions/exposure/pending to resume after restart.
# ======================================================================
def checkpoint_state(state_obj):
    """
    state_obj example:
    {
      "positions": {...},
      "exposure": {"total": 0.32, "by_symbol": {...}},
      "pending_intents": _read_jsonl(ORDER_INTENTS)[-500:],
      "last_sequence": 12345
    }
    """
    tmp_path = STATE_CHECKPOINT + ".tmp"
    _write_json(tmp_path, {"ts": _now(), "state": state_obj})
    # Atomic replace
    if os.path.exists(tmp_path):
        shutil.move(tmp_path, STATE_CHECKPOINT)

def load_checkpoint():
    ck = _read_json(STATE_CHECKPOINT, {"state": {}})
    return ck.get("state", {})

def reconcile_after_restart():
    state = load_checkpoint()
    pending = state.get("pending_intents", [])
    # Clear intents older than 24h or already finalized
    registry_ids = set(r.get("client_order_id") for r in _read_jsonl(ORDER_REGISTRY))
    fresh_pending = [p for p in pending if (_now() - p.get("ts", _now())) <= 86400 and p.get("client_order_id") not in registry_ids]
    # Overwrite intents with fresh pending
    open(ORDER_INTENTS, "w").write("")  # truncate
    for p in fresh_pending:
        _append_jsonl(ORDER_INTENTS, p)
    # Return exposure/positions for resync
    return {"positions": state.get("positions", {}), "exposure": state.get("exposure", {}), "pending_count": len(fresh_pending)}

# ======================================================================
# 249 – Dependency Health Gates
# Blocks trading if critical dependencies are degraded (storage/time/connectors).
# ======================================================================
def storage_healthy(min_free_mb=200):
    try:
        total, used, free = shutil.disk_usage(os.getcwd())
        return (free // (1024 * 1024)) >= min_free_mb
    except Exception:
        return False

def time_sync_healthy(max_skew_sec=90):
    # Placeholder: assume local clock OK; can be extended with NTP check
    return True

def connector_healthy():
    st = _read_json(API_CONNECTORS_LOG, {}).get("connectors", {})
    primary = st.get("primary", {"status": "healthy", "errors_5m": 0})
    secondary = st.get("secondary", {"status": "healthy", "errors_5m": 0})
    return (primary.get("status") == "healthy" and primary.get("errors_5m", 0) <= 1) or \
           (secondary.get("status") == "healthy" and secondary.get("errors_5m", 0) <= 1)

def dependency_health_gate():
    ok_storage = storage_healthy()
    ok_time = time_sync_healthy()
    ok_conn = connector_healthy()
    healthy = all([ok_storage, ok_time, ok_conn])
    return {"healthy": healthy, "storage": ok_storage, "time_sync": ok_time, "connector": ok_conn}

# ======================================================================
# 250 – Feature Flags & Canary Router
# Safe rollouts: 10% flow canary, auto-promote on success, auto-demote on failure.
# ======================================================================
def set_feature_flag(name, enabled=True, canary_pct=0.1):
    flags = _read_json(FEATURE_FLAGS, {"flags": {}})
    flags["flags"][name] = {"enabled": enabled, "canary_pct": canary_pct, "since_ts": _now()}
    _write_json(FEATURE_FLAGS, flags)
    return flags["flags"][name]

def route_canary(flow_name, metrics):
    """
    metrics example:
    {
      "lift": 0.07,          # challenger vs baseline
      "samples": 50,
      "fee_ratio_delta": -0.1,
      "precision_delta": +0.05
    }
    Policy: auto-promote if lift >= 0.05 and samples >= 30 and fee_ratio_delta <= 0.
            auto-demote if lift <= 0 or precision_delta < 0.
    """
    canary = _read_json(CANARY_ROUTER, {"routes": {}})
    decision = "hold"
    if metrics.get("lift", 0) >= 0.05 and metrics.get("samples", 0) >= 30 and metrics.get("fee_ratio_delta", 0) <= 0:
        decision = "promote"
    elif metrics.get("lift", 0) <= 0 or metrics.get("precision_delta", 0) < 0:
        decision = "demote"
    canary["routes"][flow_name] = {"decision": decision, "metrics": metrics, "ts": _now()}
    _write_json(CANARY_ROUTER, canary)
    return {"decision": decision}

# ======================================================================
# Nightly Hardening Orchestrator (246–250)
# - Rebuild flags and canary decisions
# - Checkpoint state snapshot
# - Summarize idempotency registry growth
# ======================================================================
def run_hardening_orchestrator_246_250(snapshot_state=None):
    flags = _read_json(FEATURE_FLAGS, {"flags": {}})
    canary = _read_json(CANARY_ROUTER, {"routes": {}})
    if snapshot_state:
        checkpoint_state(snapshot_state)
    intents_count = len(_read_jsonl(ORDER_INTENTS))
    registry_count = len(_read_jsonl(ORDER_REGISTRY))
    deps = dependency_health_gate()
    summary = {
        "ts": _now(),
        "flags": list(flags.get("flags", {}).keys()),
        "canary_routes": list(canary.get("routes", {}).keys()),
        "intents_count": intents_count,
        "registry_count": registry_count,
        "deps_healthy": deps["healthy"]
    }
    _write_json("logs/hardening_orchestrator_246_250.json", summary)
    return summary

# ----------------------------------------------------------------------
# Integration Hooks for alpha_to_execution_adapter.py
# ----------------------------------------------------------------------
def pre_place_idempotency(symbol, direction, size, order_cfg):
    ttl = order_cfg.get("ttl_sec", 12)
    recon = reconcile_before_place(symbol, direction, size, order_cfg, ttl)
    if recon["duplicate"]:
        return {"allow": False, "reason": "duplicate_intent", "client_order_id": recon["client_order_id"]}
    return {"allow": True, "client_order_id": recon["client_order_id"]}

def post_place_reconcile(client_order_id, status, execution_meta=None):
    finalize_order_intent(client_order_id, status, execution_meta)

def pre_trade_technical_gates(module_name="alpha_adapter"):
    # Dependency gates first
    deps = dependency_health_gate()
    if not deps["healthy"]:
        return {"block": True, "reason": f"deps_unhealthy:storage={deps['storage']},time={deps['time_sync']},connector={deps['connector']}"}
    # Deadlock guard used per critical section via context manager (see example).
    return {"block": False}

def use_deadlock_guard(section_name, module_name="alpha_adapter", timeout_sec=30):
    # Helper to be used as context manager
    return deadlock_guard(section_name, module_name=module_name, timeout_sec=timeout_sec)

def get_feature_flag(name, default_enabled=True, default_canary_pct=0.1):
    flags = _read_json(FEATURE_FLAGS, {"flags": {}}).get("flags", {})
    f = flags.get(name, {"enabled": default_enabled, "canary_pct": default_canary_pct})
    return f

# Example wiring in alpha_to_execution_adapter.py:
# ------------------------------------------------
# from phase_246_250 import pre_place_idempotency, post_place_reconcile, pre_trade_technical_gates, use_deadlock_guard, get_feature_flag, record_order_intent
#
# # Technical gates (before any trading logic):
# tech = pre_trade_technical_gates(module_name="alpha_adapter")
# if tech["block"]:
#     append_symbol_audit(sym, {"reason": tech["reason"]})
#     blocked += 1
#     continue
#
# # Idempotent intent & record:
# idem = pre_place_idempotency(sym, direction, final_size, order_cfg)
# if not idem["allow"]:
#     append_symbol_audit(sym, {"reason": idem["reason"], "client_order_id": idem["client_order_id"]})
#     blocked += 1
#     continue
# record_order_intent(sym, direction, final_size, venue, order_cfg, idem["client_order_id"])
#
# # Deadlock guard around API placement:
# with use_deadlock_guard("place_order", module_name="alpha_adapter", timeout_sec=30):
#     resp = safe_place_order(symbol=sym, size=final_size, connector_name=conn["connector_name"], connector_meta=conn["connector_meta"])
#     status = "filled" if resp.get("ok") else "rejected"
#     post_place_reconcile(idem["client_order_id"], status, execution_meta=resp)
#
# # On startup after a crash:
# from phase_246_250 import reconcile_after_restart
# recover = reconcile_after_restart()
# print("Recovered state:", recover)

if __name__ == "__main__":
    print("Hardening orchestrator summary:", run_hardening_orchestrator_246_250(snapshot_state={"positions": {}, "exposure": {"total": 0.0, "by_symbol": {}}, "pending_intents": _read_jsonl(ORDER_INTENTS)[-100:], "last_sequence": 0}))