"""
Phase 9.1 — Adaptive Governance
Enhancements layered on Phase 9 Autonomy Controller:
- Dynamic tolerances (volatility-aware drift thresholds)
- Health-weighted ramp sizing
- Adaptive cooldowns
- Severity-scored watchdog
- Confidence-weighted calibration
- Observability upgrades (health trends, adaptive audit logs)

Cadence:
- Tolerance updates: hourly (volatility-aware drift thresholds)
- Health trend tracking: 60 seconds (continuous health history)
- Watchdog severity scoring: 60 seconds (layered on Phase 9 watchdog)
- Parameter calibration: hourly (confidence-weighted nudges)
"""

import time
import threading
from dataclasses import dataclass, field
from typing import Dict, List, Optional
from datetime import datetime
import pytz

ARIZONA_TZ = pytz.timezone("America/Phoenix")

# ==============================
# Config
# ==============================

@dataclass
class Phase91Config:
    # Dynamic tolerance thresholds
    volatility_low_threshold: float = 0.3
    volatility_high_threshold: float = 0.7
    
    # Tolerance ranges (ev_usd, trailing_r, add_r)
    tolerances_low_vol: Dict[str, float] = field(default_factory=lambda: {
        "ev_usd": 0.01, "trailing_r": 0.03, "add_r": 0.08
    })
    tolerances_normal_vol: Dict[str, float] = field(default_factory=lambda: {
        "ev_usd": 0.02, "trailing_r": 0.05, "add_r": 0.10
    })
    tolerances_high_vol: Dict[str, float] = field(default_factory=lambda: {
        "ev_usd": 0.03, "trailing_r": 0.08, "add_r": 0.15
    })
    
    # Health-weighted ramp thresholds
    health_ramp_full_threshold: float = 0.90  # full step
    health_ramp_half_threshold: float = 0.75  # half step
    
    # Adaptive cooldown multipliers
    cooldown_short_multiplier: float = 0.66   # health >= 0.90
    cooldown_long_multiplier: float = 1.33    # health < 0.60
    
    # Watchdog severity timeouts
    watchdog_minor_multiplier: int = 2   # timeout * 2
    watchdog_major_multiplier: int = 4   # timeout * 4
    
    # Calibration confidence weights
    calibration_min_confidence: float = 0.60
    calibration_confidence_range: float = 0.40  # 0.60 to 1.00
    
    # Health trend history
    health_history_max_len: int = 1440  # 24h at 1-min resolution
    
    # Nudge bounds (max deltas for calibration)
    max_ev_delta_usd: float = 0.05
    max_trailing_delta_r: float = 0.10
    max_add_delta_r: float = 0.20

CFG91 = Phase91Config()

# ==============================
# State
# ==============================

_phase91_lock = threading.Lock()
_health_history: List[float] = []
_last_tolerance_update_ts: float = 0.0
_current_tolerances: Dict[str, float] = CFG91.tolerances_normal_vol.copy()

# ==============================
# Helpers
# ==============================

def now() -> float:
    return time.time()

def emit_event(event_type: str, payload: dict):
    """Emit telemetry event."""
    from src.phase91_hooks import emit_dashboard_event
    emit_dashboard_event(event_type, payload)

# ==============================
# Dynamic Tolerances
# ==============================

def dynamic_tolerances(volatility_index: float) -> Dict[str, float]:
    """
    Adjust drift tolerances based on volatility regime.
    volatility_index: 0..1 (0=low vol, 1=high vol)
    """
    if volatility_index > CFG91.volatility_high_threshold:
        return CFG91.tolerances_high_vol.copy()
    elif volatility_index < CFG91.volatility_low_threshold:
        return CFG91.tolerances_low_vol.copy()
    else:
        return CFG91.tolerances_normal_vol.copy()

def phase91_update_tolerances():
    """Hourly: Update Phase 8.3 drift tolerances based on realized volatility."""
    from src.phase91_hooks import (
        realized_volatility_index_1h,
        set_drift_tolerances,
        phase87_audit_event
    )
    
    global _last_tolerance_update_ts, _current_tolerances
    
    vol_index = realized_volatility_index_1h() or 0.5
    tol = dynamic_tolerances(vol_index)
    
    with _phase91_lock:
        _current_tolerances = tol.copy()
        _last_tolerance_update_ts = now()
    
    set_drift_tolerances(tol)
    emit_event("phase91_tolerances_updated", {
        "vol_index": round(vol_index, 2),
        "tolerances": {k: round(v, 3) for k, v in tol.items()}
    })
    phase87_audit_event("phase91_tolerances_updated", {
        "vol_index": vol_index,
        "tolerances": tol
    })

# ==============================
# Health-Weighted Ramp Sizing
# ==============================

def health_weighted_ramp_size(base_step: float, health: float) -> float:
    """Scale ramp step based on composite health score."""
    if health < CFG91.health_ramp_half_threshold:
        return 0.0  # below threshold, no ramp
    elif health < CFG91.health_ramp_full_threshold:
        return base_step * 0.5  # half step
    else:
        return base_step  # full step

def phase91_apply_ramp(tier: str, base_step: float, health: float):
    """Apply health-weighted capital ramp for a tier."""
    from src.phase91_hooks import (
        increase_deployed_capital_pct_tiers,
        phase87_audit_event
    )
    
    step = health_weighted_ramp_size(base_step, health)
    if step <= 0.0:
        emit_event("phase91_ramp_skipped_health", {
            "tier": tier,
            "health": round(health, 2)
        })
        return
    
    increase_deployed_capital_pct_tiers([tier], step)
    
    event_payload = {
        "ts": int(now()),
        "tier": tier,
        "action": "ramp",
        "step_pct": round(step, 3),
        "health": round(health, 2)
    }
    
    emit_event("phase91_ramp_applied", event_payload)
    phase87_audit_event("phase91_ramp_applied", {
        "tier": tier,
        "step_pct": step,
        "health": health
    })
    
    # Log to JSONL for export
    try:
        from src.phase91_export_service import log_governance_event
        log_governance_event(event_payload)
    except:
        pass

# ==============================
# Adaptive Cooldowns
# ==============================

def adaptive_cooldown(base_minutes: int, health: float) -> int:
    """Adjust cooldown based on health score."""
    if health >= 0.90:
        return int(base_minutes * CFG91.cooldown_short_multiplier)
    elif health < 0.60:
        return int(base_minutes * CFG91.cooldown_long_multiplier)
    return base_minutes

def phase91_update_cooldowns():
    """Hourly: Update Phase 9 ramp cooldowns based on current health."""
    from src.phase91_hooks import (
        composite_health,
        set_phase9_ramp_cooldown,
        get_baseline_ramp_cooldown,
        phase87_audit_event
    )
    
    health = composite_health()
    baseline_cooldown = get_baseline_ramp_cooldown()  # immutable baseline
    new_cooldown = adaptive_cooldown(baseline_cooldown, health)  # always derive from baseline
    
    set_phase9_ramp_cooldown(new_cooldown)  # always set, even if same (to ensure baseline restore)
    emit_event("phase91_cooldown_adjusted", {
        "health": round(health, 2),
        "baseline_cooldown_min": baseline_cooldown,
        "adjusted_cooldown_min": new_cooldown,
        "multiplier": round(new_cooldown / baseline_cooldown, 2) if baseline_cooldown > 0 else 1.0
    })
    phase87_audit_event("phase91_cooldown_adjusted", {
        "health": health,
        "baseline_cooldown_min": baseline_cooldown,
        "adjusted_cooldown_min": new_cooldown
    })

# ==============================
# Severity-Scored Watchdog
# ==============================

def watchdog_severity(subsystem: str, last_seen: float, timeout: int) -> str:
    """Calculate watchdog severity based on time delta."""
    delta = now() - last_seen
    if delta < timeout:
        return "ok"
    if delta < timeout * CFG91.watchdog_minor_multiplier:
        return "minor"
    if delta < timeout * CFG91.watchdog_major_multiplier:
        return "major"
    return "critical"

# Subsystems that should NOT trigger kill-switch when critical
# These are background processes that may be stale without indicating trading problems
NON_FREEZE_SUBSYSTEMS = {
    "drift_detector",      # Background drift detection, not essential for trading
    "validation_suite",    # Validation runs periodically, staleness is normal
    "predictive_intel",    # Prediction engine, non-critical for immediate trading
    "transparency_audit",  # Audit logging, non-critical
    "profit_optimizer",    # Optimization runs periodically
    "risk_layer",          # Risk checks run on-demand, not continuously
    "correlation_control", # Correlation analysis runs periodically
    "funding_cost_model",  # Funding cost updates periodically
    "watchdog",            # Meta-watchdog, should not freeze itself
}

def phase91_watchdog_tick():
    """60s: Severity-scored watchdog monitoring (layered on Phase 9)."""
    from src.phase91_hooks import (
        get_heartbeats,
        get_heartbeat_timeout,
        try_restart_subsystem,
        freeze_ramps_global,
        run_full_validation_suite,
        phase87_audit_event
    )
    
    heartbeats = get_heartbeats()
    degraded = []
    
    for name, last_seen in heartbeats.items():
        timeout = get_heartbeat_timeout(name)
        sev = watchdog_severity(name, last_seen, timeout)
        if sev != "ok":
            degraded.append((name, sev))
    
    if not degraded:
        emit_event("phase91_watchdog_ok", {})
        return
    
    # Handle degraded subsystems by severity
    for sub, sev in degraded:
        if sev == "minor":
            emit_event("phase91_watchdog_minor", {"subsystem": sub})
        elif sev == "major":
            try_restart_subsystem(sub)
            emit_event("phase91_watchdog_major_recover", {"subsystem": sub})
            phase87_audit_event("phase91_watchdog_major_recover", {"subsystem": sub})
        elif sev == "critical":
            # Skip freeze for non-critical subsystems (background processes)
            if sub in NON_FREEZE_SUBSYSTEMS:
                emit_event("phase91_watchdog_critical_skip", {"subsystem": sub, "reason": "non_freeze_subsystem"})
                continue
            
            freeze_ramps_global()
            suite = run_full_validation_suite()
            if suite and getattr(suite, 'all_passed', False):
                emit_event("phase91_watchdog_critical_recovered", {"subsystem": sub})
            else:
                emit_event("phase91_watchdog_critical_block", {"subsystem": sub})
            phase87_audit_event("phase91_watchdog_critical", {"subsystem": sub, "validation_passed": suite.all_passed if suite else False})

# ==============================
# Confidence-Weighted Calibration
# ==============================

def confidence_weighted_nudge(confidence: float, max_delta: float) -> float:
    """Scale nudge magnitude based on calibration confidence."""
    if confidence < CFG91.calibration_min_confidence:
        return 0.0
    scale = (confidence - CFG91.calibration_min_confidence) / CFG91.calibration_confidence_range
    return max_delta * scale

def phase91_calibrate_parameters():
    """Hourly: Confidence-weighted parameter calibration across tiers."""
    from src.phase91_hooks import (
        calibration_confidence,
        pnl_attribution_last_hours,
        tier_for_symbol,
        nudge_ev_gate_tier,
        nudge_trailing_start_r_tier,
        nudge_add_spacing_tier,
        phase87_audit_event
    )
    
    conf = calibration_confidence()
    attrib = pnl_attribution_last_hours(24) or {}
    
    if not attrib:
        emit_event("phase91_calibration_skipped_no_data", {"confidence": round(conf, 2)})
        return
    
    for tier in ["majors", "l1s", "experimental"]:
        tier_syms = [s for s in attrib.keys() if tier_for_symbol(s) == tier]
        tier_pnl = sum(attrib.get(s, 0.0) for s in tier_syms)
        
        # Calculate confidence-weighted nudges
        ev_delta = confidence_weighted_nudge(conf, CFG91.max_ev_delta_usd)
        tr_delta = confidence_weighted_nudge(conf, CFG91.max_trailing_delta_r)
        add_delta = confidence_weighted_nudge(conf, CFG91.max_add_delta_r)
        
        # Apply nudges (positive P&L → relax, negative → tighten)
        if tier_pnl > 0:
            nudge_ev_gate_tier(tier, -ev_delta)  # lower EV gate
            nudge_trailing_start_r_tier(tier, tr_delta)  # widen trailing
            nudge_add_spacing_tier(tier, add_delta)  # widen pyramiding
        elif tier_pnl < 0:
            nudge_ev_gate_tier(tier, ev_delta)  # raise EV gate
            nudge_trailing_start_r_tier(tier, -tr_delta)  # tighten trailing
            nudge_add_spacing_tier(tier, -add_delta)  # tighten pyramiding
        
        event_payload = {
            "ts": int(now()),
            "tier": tier,
            "confidence": round(conf, 2),
            "tier_pnl": round(tier_pnl, 2),
            "ev_delta": round(ev_delta, 3),
            "tr_delta": round(tr_delta, 3),
            "add_delta": round(add_delta, 3)
        }
        
        emit_event("phase91_calibration_nudges", event_payload)
        phase87_audit_event("phase91_calibration_nudges", {
            "tier": tier,
            "confidence": conf,
            "tier_pnl": tier_pnl,
            "nudges": {"ev_usd": ev_delta, "tr_r": tr_delta, "add_r": add_delta}
        })
        
        # Log to JSONL for export
        try:
            from src.phase91_export_service import log_calibration_event
            log_calibration_event(event_payload)
        except:
            pass

# ==============================
# Health Trend Telemetry
# ==============================

def phase91_health_trend_tick():
    """60s: Track composite health over time for trend analysis."""
    from src.phase91_hooks import composite_health
    
    global _health_history
    
    h = composite_health()
    
    with _phase91_lock:
        _health_history.append(h)
        if len(_health_history) > CFG91.health_history_max_len:
            _health_history.pop(0)
    
    # Calculate rolling averages
    if len(_health_history) >= 60:
        avg_1h = sum(_health_history[-60:]) / 60
    else:
        avg_1h = sum(_health_history) / len(_health_history)
    
    if len(_health_history) >= 360:
        avg_6h = sum(_health_history[-360:]) / 360
    else:
        avg_6h = sum(_health_history) / len(_health_history)
    
    avg_24h = sum(_health_history) / len(_health_history)
    
    emit_event("phase91_health_trend", {
        "current": round(h, 2),
        "avg_1h": round(avg_1h, 2),
        "avg_6h": round(avg_6h, 2),
        "avg_24h": round(avg_24h, 2)
    })

# ==============================
# Status Provider
# ==============================

def get_phase91_status() -> dict:
    """Get current Phase 9.1 status for dashboard."""
    with _phase91_lock:
        return {
            "tolerances_updated_ts": _last_tolerance_update_ts,
            "current_tolerances": _current_tolerances.copy(),
            "health_history_len": len(_health_history),
            "avg_health_1h": round(sum(_health_history[-60:]) / 60, 2) if len(_health_history) >= 60 else None,
            "avg_health_24h": round(sum(_health_history) / len(_health_history), 2) if _health_history else None,
            "config": {
                "volatility_thresholds": {
                    "low": CFG91.volatility_low_threshold,
                    "high": CFG91.volatility_high_threshold
                },
                "health_ramp_thresholds": {
                    "half": CFG91.health_ramp_half_threshold,
                    "full": CFG91.health_ramp_full_threshold
                },
                "calibration_min_confidence": CFG91.calibration_min_confidence
            }
        }

# ==============================
# Initialization
# ==============================

def start_phase91_adaptive_governance():
    """Initialize Phase 9.1 Adaptive Governance and register with coordinator."""
    emit_event("phase91_started", {
        "tolerances": _current_tolerances,
        "health_history_max_len": CFG91.health_history_max_len
    })
    print("✅ Phase 9.1 Adaptive Governance started")
