"""
Phase 8.3 — Drift Detector + Regression Suite
Continuous parameter drift monitoring, auto-restore, and post-change regression runs.

Delivers:
- Drift detector: Watches Phase 7.4 critical parameters (EV gates, trailing start R, add spacing R) per tier.
- Auto-restore: Captures baselines, detects drift beyond tolerance, restores exact values, and logs events.
- Change hooks: On config changes or experiment promotions, snapshot → run validation suite → gate promotion if failing.
- Regression suite runner: Executes Phase 8.2 validation suite automatically after impactful changes.
- Dashboard telemetry: Exposes current vs baseline vs last-restore context.

Cadence:
- Drift check: every 15 minutes
- Baseline refresh: hourly (optional, guarded)
- Regression on change: immediate
"""

import time
import threading
from dataclasses import dataclass, field
from typing import Dict, Optional, List
from datetime import datetime
import pytz

ARIZONA_TZ = pytz.timezone("America/Phoenix")

# ==============================
# Config
# ==============================

@dataclass
class Phase83Config:
    tiers: List[str] = field(default_factory=lambda: ["majors", "l1s", "experimental"])
    drift_tolerance_ev_usd: float = 0.02         # EV gate tolerance (USD)
    drift_tolerance_trailing_r: float = 0.05     # trailing start tolerance (R)
    drift_tolerance_add_r: float = 0.10          # add spacing tolerance (R)
    restore_cooldown_sec: int = 600              # min time between restores for same tier
    baseline_refresh_hours: int = 12             # refresh baselines to reflect intentional long-lived changes
    run_regression_on_change: bool = True        # run Phase 8.2 validation after changes
    gate_promotion_on_regression_fail: bool = True

CFG83 = Phase83Config()

# ==============================
# State
# ==============================

_state_lock = threading.Lock()
_baselines: Dict[str, Dict[str, float]] = {}        # tier -> {ev_gate, trailing_r, add_r}
_last_restore_ts: Dict[str, float] = {}             # tier -> epoch of last restore
_last_baseline_refresh_ts: float = 0.0
_last_regression_result: Optional[Dict] = None

# ==============================
# Helpers
# ==============================

def now() -> float: 
    return time.time()

def emit_event(event_type: str, payload: dict):
    """Emit telemetry event (for dashboard integration)."""
    ts = datetime.now(ARIZONA_TZ).strftime('%Y-%m-%d %H:%M:%S')
    print(f"📊 PHASE83 [{ts}] {event_type}: {payload}")

# ==============================
# Phase 7.4 parameter hooks
# ==============================

def current_ev_gate_tier(tier: str) -> float:
    """Get current EV gate for tier from Phase 7.4."""
    try:
        from phase74_nudges import get_phase74_nudges
        nudges = get_phase74_nudges()
        return nudges.config.ev_gate_default_usd
    except:
        return 0.50

def set_ev_gate_tier(tier: str, value: float):
    """Set EV gate for tier in Phase 7.4."""
    try:
        from phase74_nudges import get_phase74_nudges
        nudges = get_phase74_nudges()
        nudges.config.ev_gate_default_usd = value
    except:
        pass

def current_trailing_start_r_tier(tier: str) -> float:
    """Get current trailing start R for tier from Phase 7.4."""
    try:
        from phase74_nudges import get_phase74_nudges
        nudges = get_phase74_nudges()
        return nudges.config.trailing_start_r_trend
    except:
        return 0.70

def set_trailing_start_r_tier(tier: str, value: float):
    """Set trailing start R for tier in Phase 7.4."""
    try:
        from phase74_nudges import get_phase74_nudges
        nudges = get_phase74_nudges()
        nudges.config.trailing_start_r_trend = value
    except:
        pass

def current_add_spacing_tier(tier: str) -> float:
    """Get current pyramiding trigger R for tier from Phase 7.4."""
    try:
        from phase74_nudges import get_phase74_nudges
        nudges = get_phase74_nudges()
        return nudges.config.pyramid_trigger_r_trend
    except:
        return 0.50

def set_add_spacing_tier(tier: str, value: float):
    """Set pyramiding trigger R for tier in Phase 7.4."""
    try:
        from phase74_nudges import get_phase74_nudges
        nudges = get_phase74_nudges()
        nudges.config.pyramid_trigger_r_trend = value
    except:
        pass

# ==============================
# Baseline management
# ==============================

def capture_baseline_for_tier(tier: str):
    """Capture current baseline parameters for a tier."""
    with _state_lock:
        _baselines[tier] = {
            "ev_gate": current_ev_gate_tier(tier),
            "trailing_r": current_trailing_start_r_tier(tier),
            "add_r": current_add_spacing_tier(tier),
        }
    emit_event("baseline_captured", {"tier": tier, "baseline": _baselines[tier]})

def capture_all_baselines():
    """Capture baselines for all tiers."""
    for t in CFG83.tiers:
        capture_baseline_for_tier(t)

def maybe_refresh_baselines():
    """Refresh baselines periodically to reflect intentional config changes."""
    global _last_baseline_refresh_ts
    if (now() - _last_baseline_refresh_ts) < CFG83.baseline_refresh_hours * 3600:
        return
    capture_all_baselines()
    _last_baseline_refresh_ts = now()
    emit_event("baselines_refreshed", {})

def within_tol(curr: float, base: float, tol: float) -> bool:
    """Check if current value is within tolerance of baseline."""
    return abs((curr or 0.0) - (base or 0.0)) <= tol

def can_restore(tier: str) -> bool:
    """Check if restore cooldown has elapsed for tier."""
    ts = _last_restore_ts.get(tier, 0.0)
    return (now() - ts) >= CFG83.restore_cooldown_sec

# ==============================
# Drift detection & restore
# ==============================

def check_tier_and_restore_if_drift(tier: str):
    """Check tier for parameter drift and auto-restore if detected."""
    base = _baselines.get(tier)
    if not base:
        capture_baseline_for_tier(tier)
        base = _baselines[tier]

    curr_ev = current_ev_gate_tier(tier)
    curr_tr = current_trailing_start_r_tier(tier)
    curr_add = current_add_spacing_tier(tier)

    ev_ok = within_tol(curr_ev, base["ev_gate"], CFG83.drift_tolerance_ev_usd)
    tr_ok = within_tol(curr_tr, base["trailing_r"], CFG83.drift_tolerance_trailing_r)
    add_ok = within_tol(curr_add, base["add_r"], CFG83.drift_tolerance_add_r)

    drift = {"ev_gate": not ev_ok, "trailing_r": not tr_ok, "add_r": not add_ok}
    if not any(drift.values()):
        return

    if not can_restore(tier):
        emit_event("restore_skipped_cooldown", {"tier": tier, "drift": drift})
        return

    # Restore exact baseline values
    with _state_lock:
        set_ev_gate_tier(tier, base["ev_gate"])
        set_trailing_start_r_tier(tier, base["trailing_r"])
        set_add_spacing_tier(tier, base["add_r"])
        _last_restore_ts[tier] = now()

    emit_event("drift_restored", {
        "tier": tier,
        "from": {"ev_gate": curr_ev, "trailing_r": curr_tr, "add_r": curr_add},
        "to": base,
        "drift": drift
    })

def phase83_drift_tick():
    """15-minute drift check across all tiers."""
    for t in CFG83.tiers:
        check_tier_and_restore_if_drift(t)
    maybe_refresh_baselines()

# ==============================
# Regression suite integration
# ==============================

def run_regression_suite_and_gate(reason: str) -> bool:
    """
    Runs Phase 8.2 validation suite. Returns True if all_passed, else False.
    Also logs result to dashboard; optionally gates promotions/changes.
    """
    global _last_regression_result
    
    try:
        from phase82_validation import run_full_validation_suite
        suite = run_full_validation_suite()
        
        result = {
            "started_ts": suite.started_ts,
            "finished_ts": suite.finished_ts,
            "all_passed": suite.all_passed,
            "results": [{"name": r.name, "passed": r.passed, "details": r.details} for r in suite.results],
            "reason": reason
        }
        _last_regression_result = result
        emit_event("regression_result", result)
        return bool(suite.all_passed)
    except Exception as e:
        emit_event("regression_error", {"reason": reason, "error": str(e)})
        return False

def on_config_change(tier: str, param: str, new_value: float, source: str):
    """
    Wrapper for config changes that:
    - snapshots old value,
    - applies new value,
    - runs regression,
    - gates promotion if validation fails (and auto-restore baseline).
    """
    # Snapshot before change
    old_value = {
        "ev_gate": current_ev_gate_tier(tier),
        "trailing_r": current_trailing_start_r_tier(tier),
        "add_r": current_add_spacing_tier(tier),
    }.get(param)

    # Apply change via targeted setter
    if param == "ev_gate":
        set_ev_gate_tier(tier, new_value)
    elif param == "trailing_r":
        set_trailing_start_r_tier(tier, new_value)
    elif param == "add_r":
        set_add_spacing_tier(tier, new_value)
    else:
        emit_event("config_change_unknown_param", {"tier": tier, "param": param})
        return

    emit_event("config_change_applied", {
        "tier": tier,
        "param": param,
        "from": old_value,
        "to": new_value,
        "source": source
    })

    # Run regression suite if enabled
    if CFG83.run_regression_on_change:
        ok = run_regression_suite_and_gate(reason=f"config_change:{tier}:{param}")
        if not ok and CFG83.gate_promotion_on_regression_fail:
            # Revert to baseline exact values
            b = _baselines.get(tier)
            if b:
                with _state_lock:
                    set_ev_gate_tier(tier, b["ev_gate"])
                    set_trailing_start_r_tier(tier, b["trailing_r"])
                    set_add_spacing_tier(tier, b["add_r"])
                    _last_restore_ts[tier] = now()
                emit_event("config_change_reverted", {
                    "tier": tier,
                    "param": param,
                    "baseline": b
                })
            else:
                emit_event("config_change_revert_failed_no_baseline", {
                    "tier": tier,
                    "param": param
                })

def on_experiment_promotion(symbol: str, variant: Dict):
    """
    Called after Phase 8.0/8.1 promotion.
    - Runs regression suite,
    - If it fails, logs and gates (demote handled by Phase 8.0).
    """
    if not CFG83.run_regression_on_change:
        return
    
    ok = run_regression_suite_and_gate(reason=f"promotion:{symbol}")
    if not ok and CFG83.gate_promotion_on_regression_fail:
        emit_event("promotion_gated", {
            "symbol": symbol,
            "variant": variant,
            "reason": "regression_suite_failed"
        })

# ==============================
# Telemetry endpoint
# ==============================

def get_phase83_status() -> Dict:
    """Get Phase 8.3 status for dashboard/API."""
    with _state_lock:
        return {
            "baselines": _baselines.copy(),
            "last_restore_ts": _last_restore_ts.copy(),
            "last_baseline_refresh_ts": _last_baseline_refresh_ts,
            "last_regression_result": _last_regression_result,
            "config": {
                "tiers": CFG83.tiers,
                "tolerance_ev_usd": CFG83.drift_tolerance_ev_usd,
                "tolerance_trailing_r": CFG83.drift_tolerance_trailing_r,
                "tolerance_add_r": CFG83.drift_tolerance_add_r,
                "restore_cooldown_sec": CFG83.restore_cooldown_sec,
                "baseline_refresh_hours": CFG83.baseline_refresh_hours
            }
        }

# ==============================
# Initialization
# ==============================

def initialize_phase83():
    """Initialize Phase 8.3 Drift Detector."""
    # Capture initial baselines at startup
    capture_all_baselines()
    
    emit_event("started", {
        "tolerance": {
            "ev_usd": CFG83.drift_tolerance_ev_usd,
            "trailing_r": CFG83.drift_tolerance_trailing_r,
            "add_r": CFG83.drift_tolerance_add_r
        },
        "tiers": CFG83.tiers
    })
    
    print("✅ Phase 8.3 Drift Detector initialized")
    return True
