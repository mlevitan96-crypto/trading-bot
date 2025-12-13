"""
Phase 9 — Autonomy Controller
Full self-governance: capital ramps, continuous learning, safety orchestration, feature flags, and mission-critical watchdogs.

Scope (designed to minimize future patching by bundling capabilities):
- Autonomy governor: portfolio/tier capital scaling with multi-signal health gating
- Continuous learning loop: attribution → parameter calibration → baseline refresh
- Global safety orchestration: unified health score, fail-safe throttles, incident lifecycle
- Feature flag framework: staged activation, audit logging, regression gates
- Watchdog & heartbeats: subsystem liveness, timeout handling, auto-recovery routines
- Status & telemetry: compact API payloads for cockpit-grade visibility

Cadence:
- Autonomy governor: every 10 minutes
- Learning loop: hourly
- Watchdog: every minute
- Feature flag reconciler: on-demand + every 30 minutes
"""

import time
import threading
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from src.phase9_hooks import *

_PHASE9_INITIALIZED = False
_phase9_lock = threading.Lock()

@dataclass
class Phase9Config:
    ramp_step_pct_tier: Dict[str, float] = field(default_factory=lambda: {
        "majors": 0.12, "l1s": 0.10, "experimental": 0.08
    })
    ramp_max_daily_pct: float = 0.25
    ramp_cooldown_min: int = 180
    shrink_step_pct_tier: Dict[str, float] = field(default_factory=lambda: {
        "majors": 0.15, "l1s": 0.18, "experimental": 0.22
    })
    shrink_reasons: List[str] = field(default_factory=lambda: [
        "validation_fail", "risk_off", "drawdown_breach", "latency_spike", "reject_spike"
    ])

    w_validation: float = 0.30
    w_regime_stability: float = 0.20
    w_drift_clean: float = 0.20
    w_execution_quality: float = 0.20
    w_risk_load: float = 0.10

    health_ramp_min: float = 0.75
    health_hold_min: float = 0.55
    health_shrink_below: float = 0.40

    attrib_window_hours: int = 24
    baseline_refresh_hours: int = 24
    calibration_max_ev_delta_usd: float = 0.05
    calibration_max_trailing_delta_r: float = 0.10
    calibration_max_add_delta_r: float = 0.20
    calibration_confidence_min: float = 0.60

    staged_rollout_pct: Dict[str, float] = field(default_factory=lambda: {
        "phase88_peer_consensus": 0.0,
        "phase89_external_nudges": 0.0,
        "hedge_dispatcher": 1.0,
        "capital_preservation_mode": 1.0
    })
    staged_increment_pct: float = 0.10
    staged_max_pct: float = 1.0

    heartbeat_timeout_sec: Dict[str, int] = field(default_factory=lambda: {
        "validation_suite": 60 * 60,
        "drift_detector": 30 * 60,
        "risk_layer": 10 * 60,
        "profit_optimizer": 45 * 60,
        "predictive_intel": 10 * 60,
        "transparency_audit": 5 * 60
    })
    auto_recovery_cooldown_min: int = 15

    autonomy_tick_sec: int = 600
    learning_tick_sec: int = 3600
    watchdog_tick_sec: int = 60
    flags_tick_sec: int = 1800

CFG9 = Phase9Config()

_last_ramp_ts: Dict[str, float] = {"majors": 0.0, "l1s": 0.0, "experimental": 0.0}
_daily_ramp_accum_pct: float = 0.0
_daily_ramp_epoch: int = 0
_last_learning_ts: float = 0.0
_last_baseline_refresh_ts: float = 0.0
_last_auto_recovery_ts: float = 0.0
_feature_flags_runtime: Dict[str, float] = {}

_heartbeats: Dict[str, float] = {
    "validation_suite": 0.0,
    "drift_detector": 0.0,
    "risk_layer": 0.0,
    "profit_optimizer": 0.0,
    "predictive_intel": 0.0,
    "transparency_audit": 0.0
}

def now() -> float:
    return time.time()

def minutes_since(ts: float) -> float:
    return (now() - ts) / 60.0

def day_bucket(ts: float) -> int:
    return int(ts // (24 * 3600))

def reset_daily_ramp_if_needed():
    global _daily_ramp_accum_pct, _daily_ramp_epoch
    db = day_bucket(now())
    if db != _daily_ramp_epoch:
        _daily_ramp_accum_pct = 0.0
        _daily_ramp_epoch = db

def bump_heartbeat(name: str):
    with _phase9_lock:
        _heartbeats[name] = now()

def heartbeat_ok(name: str) -> bool:
    timeout = CFG9.heartbeat_timeout_sec.get(name, 600)
    with _phase9_lock:
        return (now() - _heartbeats.get(name, 0.0)) <= timeout

def health_validation() -> float:
    passed = last_validation_suite_passed()
    recent = heartbeat_ok("validation_suite")
    return 1.0 if (passed and recent) else (0.5 if recent else 0.0)

def health_regime_stability() -> float:
    last_flip_ts = last_regime_change_ts() or (now() - 3600)
    stable = (now() - last_flip_ts) >= 60 * 60
    return 1.0 if stable else 0.4

def health_drift_clean() -> float:
    drift = phase83_status_fetch() or {}
    last_restore_ts_dict = drift.get("last_restore_ts", {})
    if isinstance(last_restore_ts_dict, dict) and last_restore_ts_dict:
        last_restore_ts = max(last_restore_ts_dict.values(), default=0.0)
    else:
        last_restore_ts = 0.0
    baselines_ok = bool(drift.get("baselines"))
    if not baselines_ok:
        return 0.0
    if (now() - last_restore_ts) > 3600:
        return 1.0
    return 0.6

def health_execution_quality() -> float:
    slip_p75 = slippage_p75_bps_portfolio() or 12.0
    rejects = order_reject_rate_15m() or 0.0
    slip_score = max(0.0, 1.0 - (slip_p75 - 10.0) / 10.0)
    reject_score = max(0.0, 1.0 - (rejects / 0.10))
    return 0.5 * slip_score + 0.5 * reject_score

def health_risk_load() -> float:
    dd = rolling_drawdown_pct_24h() or 0.0
    preserve_until = phase86_preserve_until_ts()
    preserve_active = bool(preserve_until and now() < preserve_until)
    drawdown_penalty = max(0.0, 1.0 - dd / 5.0)
    return (0.5 * drawdown_penalty) + (0.5 * (0.0 if preserve_active else 1.0))

def composite_health() -> float:
    h = (
        CFG9.w_validation * health_validation() +
        CFG9.w_regime_stability * health_regime_stability() +
        CFG9.w_drift_clean * health_drift_clean() +
        CFG9.w_execution_quality * health_execution_quality() +
        CFG9.w_risk_load * health_risk_load()
    )
    return max(0.0, min(1.0, h))

def can_ramp_tier(tier: str) -> bool:
    # Phase 9.4: Check if recovery module has frozen ramps
    try:
        from src.phase94_recovery_scaling import is_phase94_ramps_frozen
        if is_phase94_ramps_frozen():
            return False
    except:
        pass  # Phase 9.4 not available
    
    with _phase9_lock:
        if minutes_since(_last_ramp_ts.get(tier, 0.0)) < CFG9.ramp_cooldown_min:
            return False
    reset_daily_ramp_if_needed()
    with _phase9_lock:
        if _daily_ramp_accum_pct >= CFG9.ramp_max_daily_pct:
            return False
    if current_global_regime_name() == "risk_off":
        return False
    return last_validation_suite_passed()

def apply_ramp(tier: str):
    base_step = CFG9.ramp_step_pct_tier.get(tier, 0.10)
    
    # Phase 9.1: Apply health-weighted ramp sizing if available
    try:
        from src.phase91_hooks import health_weighted_ramp_for_phase9
        step = health_weighted_ramp_for_phase9(tier, base_step)
        if step <= 0.0:
            emit_dashboard_event("phase9_ramp_skipped_health", {
                "tier": tier,
                "base_step": base_step
            })
            return
    except:
        step = base_step  # fallback to base step if Phase 9.1 not available
    
    increase_deployed_capital_pct_tiers([tier], step)
    with _phase9_lock:
        _last_ramp_ts[tier] = now()
        global _daily_ramp_accum_pct
        _daily_ramp_accum_pct += step
    emit_dashboard_event("phase9_ramp_applied", {
        "tier": tier,
        "step_pct": round(step, 3),
        "base_step_pct": round(base_step, 3),
        "daily_accum_pct": round(_daily_ramp_accum_pct, 3)
    })

def apply_shrink(tier: str, reason: str):
    step = CFG9.shrink_step_pct_tier.get(tier, 0.15)
    throttle_tier_exposure(tier, drop_pct=step)
    emit_dashboard_event("phase9_shrink_applied", {
        "tier": tier,
        "step_pct": step,
        "reason": reason
    })

def phase9_shrink_reason() -> str:
    if not last_validation_suite_passed():
        return "validation_fail"
    if current_global_regime_name() == "risk_off":
        return "risk_off"
    if (rolling_drawdown_pct_24h() or 0.0) >= 3.0:
        return "drawdown_breach"
    if (latency_ms_1m() or 0.0) > 600:
        return "latency_spike"
    if (order_reject_rate_15m() or 0.0) > 0.07:
        return "reject_spike"
    return "unknown"

def phase9_autonomy_tick():
    try:
        h = composite_health()
        emit_dashboard_event("phase9_health", {"score": round(h, 2)})
        
        tiers = ["majors", "l1s", "experimental"]
        if h >= CFG9.health_ramp_min:
            for t in tiers:
                if can_ramp_tier(t):
                    apply_ramp(t)
        elif h < CFG9.health_shrink_below:
            reason = phase9_shrink_reason()
            for t in tiers:
                apply_shrink(t, reason)
        else:
            emit_dashboard_event("phase9_hold", {"score": round(h, 2)})
    except Exception as e:
        emit_dashboard_event("phase9_autonomy_error", {"error": str(e)})

def calibration_confidence() -> float:
    v = 1.0 if last_validation_suite_passed() else 0.5
    d = health_drift_clean()
    return max(0.0, min(1.0, 0.6 * v + 0.4 * d))

def phase9_calibrate_parameters():
    conf = calibration_confidence()
    if conf < CFG9.calibration_confidence_min:
        emit_dashboard_event("phase9_calibration_skipped", {"confidence": round(conf, 2)})
        return
    
    attrib = pnl_attribution_last_hours(CFG9.attrib_window_hours)
    if not attrib:
        emit_dashboard_event("phase9_calibration_no_attrib", {})
        return
    
    for t in ["majors", "l1s", "experimental"]:
        tier_syms = [s for s in attrib.keys() if tier_for_symbol(s) == t]
        tier_pnl = sum(attrib.get(s, 0.0) for s in tier_syms)
        
        ev_delta = max(-CFG9.calibration_max_ev_delta_usd, 
                      min(CFG9.calibration_max_ev_delta_usd, tier_pnl / 1000.0))
        tr_delta = max(-CFG9.calibration_max_trailing_delta_r, 
                      min(CFG9.calibration_max_trailing_delta_r, tier_pnl / 5000.0))
        add_delta = max(-CFG9.calibration_max_add_delta_r, 
                       min(CFG9.calibration_max_add_delta_r, tier_pnl / 3000.0))
        
        nudge_ev_gate_tier(t, ev_delta)
        nudge_trailing_start_r_tier(t, tr_delta)
        nudge_add_spacing_tier(t, add_delta)
        
        emit_dashboard_event("phase9_calibration_nudges", {
            "tier": t,
            "ev_usd": round(ev_delta, 3),
            "tr_r": round(tr_delta, 3),
            "add_r": round(add_delta, 3)
        })

def phase9_learning_tick():
    global _last_learning_ts, _last_baseline_refresh_ts
    try:
        phase9_calibrate_parameters()
        
        if (now() - _last_baseline_refresh_ts) >= CFG9.baseline_refresh_hours * 3600:
            refresh_phase83_baselines()
            with _phase9_lock:
                _last_baseline_refresh_ts = now()
            emit_dashboard_event("phase9_baselines_refreshed", {})
        
        with _phase9_lock:
            _last_learning_ts = now()
    except Exception as e:
        emit_dashboard_event("phase9_learning_error", {"error": str(e)})

def phase9_flag_set(name: str, pct: float, source: str = "operator"):
    with _phase9_lock:
        old = _feature_flags_runtime.get(name, 0.0)
        pct = max(0.0, min(CFG9.staged_max_pct, pct))
        _feature_flags_runtime[name] = pct
    
    emit_dashboard_event("phase9_flag_set", {
        "flag": name,
        "from": old,
        "to": pct,
        "source": source
    })
    phase87_on_any_critical_event("phase9_flag_set", {
        "flag": name,
        "from": old,
        "to": pct,
        "source": source
    })
    
    if pct > 0 and not last_validation_suite_passed():
        suite_result = run_full_validation_suite()
        if not suite_result:
            with _phase9_lock:
                _feature_flags_runtime[name] = 0.0
            emit_dashboard_event("phase9_flag_revert_validation_fail", {"flag": name})

def phase9_flags_tick():
    try:
        h = composite_health()
        for flag in ["phase88_peer_consensus", "phase89_external_nudges"]:
            with _phase9_lock:
                curr = _feature_flags_runtime.get(flag, 0.0)
            target = curr
            
            if h >= CFG9.health_ramp_min and curr < CFG9.staged_max_pct:
                target = min(CFG9.staged_max_pct, curr + CFG9.staged_increment_pct)
            elif h < CFG9.health_hold_min:
                target = max(0.0, curr - CFG9.staged_increment_pct)
            
            if target != curr:
                phase9_flag_set(flag, target, source="autonomy")
    except Exception as e:
        emit_dashboard_event("phase9_flags_error", {"error": str(e)})

def phase9_watchdog_tick():
    try:
        degraded = []
        for name in _heartbeats.keys():
            if not heartbeat_ok(name):
                degraded.append(name)
        
        if not degraded:
            emit_dashboard_event("phase9_watchdog_ok", {})
            return
        
        global _last_auto_recovery_ts
        if minutes_since(_last_auto_recovery_ts) < CFG9.auto_recovery_cooldown_min:
            emit_dashboard_event("phase9_watchdog_degraded_hold", {"subs": degraded})
            return
        
        for sub in degraded:
            try_restart_subsystem(sub)
        
        with _phase9_lock:
            _last_auto_recovery_ts = now()
        emit_dashboard_event("phase9_watchdog_recovered", {"subs": degraded})
    except Exception as e:
        emit_dashboard_event("phase9_watchdog_error", {"error": str(e)})

def get_phase9_status() -> Dict:
    with _phase9_lock:
        return {
            "health_score": round(composite_health(), 3),
            "feature_flags": dict(_feature_flags_runtime),
            "last_learning_ts": _last_learning_ts,
            "last_baseline_refresh_ts": _last_baseline_refresh_ts,
            "daily_ramp_accum_pct": round(_daily_ramp_accum_pct, 3),
            "last_ramp_ts": dict(_last_ramp_ts),
            "heartbeats": dict(_heartbeats)
        }

def initialize_phase9():
    global _PHASE9_INITIALIZED, _feature_flags_runtime
    
    if _PHASE9_INITIALIZED:
        return
    
    with _phase9_lock:
        _feature_flags_runtime = dict(CFG9.staged_rollout_pct)
        
        for name in _heartbeats.keys():
            _heartbeats[name] = now()
    
    emit_dashboard_event("phase9_started", {
        "cfg": {
            "ramp_step_pct_tier": CFG9.ramp_step_pct_tier,
            "ramp_max_daily_pct": CFG9.ramp_max_daily_pct,
            "ramp_cooldown_min": CFG9.ramp_cooldown_min,
            "health_thresholds": {
                "ramp_min": CFG9.health_ramp_min,
                "hold_min": CFG9.health_hold_min,
                "shrink_below": CFG9.health_shrink_below
            }
        }
    })
    
    _PHASE9_INITIALIZED = True
