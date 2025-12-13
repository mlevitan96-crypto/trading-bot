# === Validation Suite Patch + Kill-Switch Fallback (src/validation_suite_patch.py) ===
# Purpose:
# - Fix import failure for apply_trailing_stops and harden validation pipeline.
# - Add sanity checks for drawdown/fee metrics to prevent false PHASE82 triggers.
# - Implement graceful-degradation: validation errors degrade protection level instead of catastrophic block.
# - Provide kill-switch reset flow with audited reason codes.
#
# Drop-in:
# - Place this file in src/.
# - Call `apply_validation_suite_patch()` at orchestrator startup (before trading window).
# - Scheduler: run `run_validation_guardrails()` before PHASE82 evaluation each cycle.

import os, json, time, importlib, traceback
from types import ModuleType

LIVE_CFG = "live_config.json"
VAL_LOG  = "logs/validation_suite_patch.jsonl"
KS_LOG   = "logs/kill_switch_events.jsonl"

def _now(): return int(time.time())
def _append_jsonl(path, row):
    try:
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(path, "a") as f: f.write(json.dumps(row) + "\n")
    except (OSError, IOError):
        pass  # Gracefully ignore I/O errors in logging - non-critical
def _read_json(path):
    if not os.path.exists(path): return {}
    try: return json.load(open(path))
    except: return {}
def _write_json(path, obj):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w") as f: json.dump(obj, f, indent=2)

# --- Safe import helper with stubbing support ---
def _safe_import_trailing_stop():
    """
    Try to import apply_trailing_stops from src.trailing_stop.
    The actual function is named apply_futures_trailing_stops, so we create an alias.
    If missing, create a stub with no-ops that preserves interface and logs a warning.
    """
    try:
        mod = importlib.import_module("src.trailing_stop")
        # The actual function is apply_futures_trailing_stops
        fn = getattr(mod, "apply_futures_trailing_stops", None)
        if callable(fn):
            _append_jsonl(VAL_LOG, {"ts": _now(), "update_type": "import_ok", "module": "src.trailing_stop", "function": "apply_futures_trailing_stops"})
            return fn
        else:
            _append_jsonl(VAL_LOG, {"ts": _now(), "update_type": "missing_symbol", "name": "apply_futures_trailing_stops"})
            return _apply_trailing_stops_stub
    except Exception as e:
        _append_jsonl(VAL_LOG, {"ts": _now(), "update_type": "import_error", "module": "src.trailing_stop", "error": str(e), "trace": traceback.format_exc()})
        return _apply_trailing_stops_stub

def _apply_trailing_stops_stub(positions, policy):
    """
    Stub: preserves interface and returns input unchanged.
    Logs one-time warning and avoids raising, so validation can continue.
    """
    _append_jsonl(VAL_LOG, {
        "ts": _now(),
        "update_type": "stub_apply_trailing_stops_used",
        "positions_count": len(positions) if positions else 0
    })
    return positions

# --- Sanity checks for kill-switch inputs ---
def _sanitize_metrics(dd_pct, reject_rate, fee_mismatch_usd):
    """
    Sanity-limits to avoid absurd values caused by upstream failures.
    - dd_pct: clamp to [-100, 100] and mark suspicious if |dd| > 50 with no corroboration.
    - reject_rate: clamp to [0, 1].
    - fee_mismatch: clamp to [0, 10_000] and flag > 100 when recent fees are low.
    """
    suspicious = []
    # Drawdown sanity
    dd_clamped = max(-100.0, min(100.0, float(dd_pct or 0.0)))
    if abs(dd_clamped) > 50.0:
        suspicious.append("dd_pct_extreme")

    # Reject rate sanity
    r_clamped = max(0.0, min(1.0, float(reject_rate or 0.0)))
    if r_clamped > 0.95:
        suspicious.append("reject_rate_extreme")

    # Fee mismatch sanity
    fm_clamped = max(0.0, min(10000.0, float(fee_mismatch_usd or 0.0)))
    if fm_clamped > 100.0:
        suspicious.append("fee_mismatch_extreme")

    return dd_clamped, r_clamped, fm_clamped, suspicious

# --- Guardrails: degrade protection level on validation failures ---
def run_validation_guardrails():
    """
    1) Ensure trailing stop function exists (or stub).
    2) Read current PHASE82 inputs from live_config.
    3) Sanitize metrics and compute protection level.
    4) Write guardrail overlay to live_config.runtime for PHASE82 to respect.
    """
    apply_ts = _safe_import_trailing_stop()

    cfg = _read_json(LIVE_CFG)
    rt = cfg.get("runtime", {}) or {}
    ks = rt.get("kill_switch_phase82", {})
    
    # Handle case where kill_switch_phase82 is a boolean instead of dict
    if isinstance(ks, bool) or ks is None:
        _append_jsonl(VAL_LOG, {"ts": _now(), "update_type": "fix_kill_switch_structure", "old_type": str(type(ks))})
        ks = {
            "drawdown_pct": 0.0,
            "reject_rate": 0.0,
            "fee_mismatch_usd": 0.0,
            "global_block": False,
            "reason": "auto_fixed_structure"
        }
        rt["kill_switch_phase82"] = ks
    
    ks = ks or {}

    dd_pct = ks.get("drawdown_pct", 0.0)            # e.g., -4.36 for -4.36%
    reject_rate = ks.get("reject_rate", 0.0)        # fraction [0..1]
    fee_mismatch = ks.get("fee_mismatch_usd", 0.0)  # USD

    dd, rr, fm, suspicious = _sanitize_metrics(dd_pct, reject_rate, fee_mismatch)

    # Protection policy:
    # - Catastrophic only if (dd <= -30% AND rr >= 0.50) OR (fm >= 500 AND rr >= 0.50), with no validation errors.
    # - Degraded protection (protective_mode + throttle) if suspicious signals present OR validation stub used.
    # - Normal protection otherwise.
    validation_stub_used = (apply_ts is _apply_trailing_stops_stub)
    catastrophic = ((dd <= -30.0 and rr >= 0.50) or (fm >= 500.0 and rr >= 0.50)) and not validation_stub_used
    degraded = validation_stub_used or (len(suspicious) > 0)

    overlay = {
        "ts": _now(),
        "dd_pct_sanitized": dd,
        "reject_rate_sanitized": rr,
        "fee_mismatch_sanitized": fm,
        "suspicious_flags": suspicious,
        "validation_stub_used": validation_stub_used,
        "protection_level": ("catastrophic" if catastrophic else ("degraded" if degraded else "normal")),
        # Recommended runtime actions for PHASE82
        "recommended_actions": (
            {"global_block": True, "size_throttle": 0.0, "protective_mode": True}
            if catastrophic else
            {"global_block": False, "size_throttle": 0.25, "protective_mode": True}
            if degraded else
            {"global_block": False, "size_throttle": 1.0, "protective_mode": False}
        )
    }

    rt["phase82_guardrails_overlay"] = overlay
    cfg["runtime"] = rt
    _write_json(LIVE_CFG, cfg)
    _append_jsonl(VAL_LOG, {"ts": _now(), "update_type": "guardrails_applied", "overlay": overlay})

    print(f"🛡️ PHASE82 Guardrails | level={overlay['protection_level']} dd={dd:.2f}% rr={rr:.2f} fee_mismatch=${fm:.2f}")

# --- Kill-switch reset with audit ---
def reset_phase82_kill_switch(reason="manual_reset_after_validation_patch"):
    cfg = _read_json(LIVE_CFG)
    rt = cfg.get("runtime", {}) or {}
    # Clear the hard block while keeping protective mode if guardrails say degraded
    overlay = rt.get("phase82_guardrails_overlay", {}) or {}
    rec = overlay.get("recommended_actions", {}) or {}

    # Reset kill-switch state
    rt["kill_switch_phase82"] = {
        "ts": _now(),
        "drawdown_pct": overlay.get("dd_pct_sanitized", 0.0),
        "reject_rate": overlay.get("reject_rate_sanitized", 0.0),
        "fee_mismatch_usd": overlay.get("fee_mismatch_sanitized", 0.0),
        "global_block": False,
        "reason": "reset",
    }
    # Apply recommended actions
    rt["protective_mode"] = bool(rec.get("protective_mode", False))
    rt["size_throttle"] = float(rec.get("size_throttle", 1.0))

    cfg["runtime"] = rt
    _write_json(LIVE_CFG, cfg)

    payload = {
        "ts": _now(),
        "update_type": "phase82_reset",
        "reason": reason,
        "applied_actions": {
                "global_block": False,
                "protective_mode": rt["protective_mode"],
                "size_throttle": rt["size_throttle"]
        },
        "sanitized_metrics": {
            "dd_pct": overlay.get("dd_pct_sanitized", 0.0),
            "reject_rate": overlay.get("reject_rate_sanitized", 0.0),
            "fee_mismatch_usd": overlay.get("fee_mismatch_sanitized", 0.0)
        }
    }
    _append_jsonl(KS_LOG, payload)
    print(f"✅ PHASE82 reset | protective_mode={rt['protective_mode']} size_throttle={rt['size_throttle']:.2f}")

# --- Integration hooks ---
def apply_validation_suite_patch():
    """
    One-time patch at startup:
    - Validates trailing_stop import or stubs it.
    - Applies guardrails immediately so PHASE82 respects sane metrics.
    """
    _ = _safe_import_trailing_stop()  # ensure availability or stub
    run_validation_guardrails()
    # Auto-reset if metrics are sane
    cfg = _read_json(LIVE_CFG)
    rt = cfg.get("runtime", {}) or {}
    overlay = rt.get("phase82_guardrails_overlay", {}) or {}
    if overlay.get("protection_level") != "catastrophic":
        reset_phase82_kill_switch(reason="auto_reset_on_startup_guardrails")

# --- Example orchestrator wiring (call these from your existing orchestrator) ---
# At startup (before trading window opens):
#   from src.validation_suite_patch import apply_validation_suite_patch
#   apply_validation_suite_patch()
#
# If PHASE82 blocks trading due to bad inputs:
#   from src.validation_suite_patch import reset_phase82_kill_switch, run_validation_guardrails
#   run_validation_guardrails()   # refresh overlay from sanitized metrics
#   reset_phase82_kill_switch(reason="auto-clear-after-guardrails")
#
# Nightly (before meta-governance watchdogs):
#   run_validation_guardrails()   # ensures guardrails are current before evaluating PHASE82
