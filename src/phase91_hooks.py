"""
Phase 9.1 Hooks — Data Access Layer
Provides data access and control interfaces for Phase 9.1 Adaptive Governance.
"""

import time
import json
from typing import Dict, List, Optional

def emit_dashboard_event(event_type: str, payload: dict):
    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    print(f"📊 PHASE91 [{ts}] {event_type}: {payload}")
    try:
        with open("logs/dashboard_events.jsonl", "a") as f:
            f.write(json.dumps({"ts": time.time(), "event": event_type, "payload": payload}) + "\n")
    except:
        pass

# ==============================
# Volatility & Drift Hooks
# ==============================

def realized_volatility_index_1h() -> Optional[float]:
    """Get 1-hour realized volatility index (0..1 scale)."""
    try:
        from src.phase81_edge_compounding import get_regime_v2
        regime = get_regime_v2()
        vol = regime.get("volatility_index", 0.5)
        return min(1.0, max(0.0, vol))
    except:
        return 0.5

def set_drift_tolerances(tolerances: Dict[str, float]):
    """Set Phase 8.3 drift tolerances dynamically."""
    try:
        from src.phase83_drift_detector import CFG83
        CFG83.drift_tolerance_ev_usd = tolerances.get("ev_usd", 0.02)
        CFG83.drift_tolerance_trailing_r = tolerances.get("trailing_r", 0.05)
        CFG83.drift_tolerance_add_r = tolerances.get("add_r", 0.10)
    except Exception as e:
        print(f"⚠️  Phase 9.1: Failed to set drift tolerances: {e}")

# ==============================
# Phase 8.7 Audit Integration
# ==============================

def phase87_audit_event(event_type: str, payload: dict):
    """Log critical event to Phase 8.7 audit chain."""
    try:
        from src.phase87_89_expansion import phase87_append_audit
        phase87_append_audit(event_type, payload)
    except:
        pass

# ==============================
# Capital Management Hooks
# ==============================

def increase_deployed_capital_pct_tiers(tiers: List[str], step_pct: float):
    """Increase deployed capital for specified tiers."""
    try:
        from src.phase82_go_live import increase_deployed_capital_pct_tiers as ramp_fn
        ramp_fn(tiers, step_pct)
    except Exception as e:
        print(f"⚠️  Phase 9.1: Failed to increase capital: {e}")

def freeze_ramps_global():
    """Freeze capital ramps globally (critical watchdog action)."""
    try:
        from src.phase82_go_live import freeze_new_entries_global
        freeze_new_entries_global()
    except Exception as e:
        print(f"⚠️  Phase 9.1: Failed to freeze ramps: {e}")

def get_baseline_ramp_cooldown() -> int:
    """Get immutable baseline ramp cooldown from Phase 9 (in minutes)."""
    try:
        from src.phase9_autonomy import CFG9
        # Store baseline on first access if not present
        if not hasattr(CFG9, 'ramp_cooldown_baseline_min'):
            CFG9.ramp_cooldown_baseline_min = CFG9.ramp_cooldown_min
        return CFG9.ramp_cooldown_baseline_min
    except:
        return 180  # default

def set_phase9_ramp_cooldown(cooldown_min: int):
    """Set Phase 9 ramp cooldown dynamically (adjustments from baseline)."""
    try:
        from src.phase9_autonomy import CFG9
        # Preserve baseline on first write
        if not hasattr(CFG9, 'ramp_cooldown_baseline_min'):
            CFG9.ramp_cooldown_baseline_min = CFG9.ramp_cooldown_min
        CFG9.ramp_cooldown_min = cooldown_min
    except Exception as e:
        print(f"⚠️  Phase 9.1: Failed to set ramp cooldown: {e}")

def health_weighted_ramp_for_phase9(tier: str, base_step: float) -> float:
    """
    Calculate health-weighted ramp step for Phase 9 to use.
    Returns the adjusted step size based on composite health and Phase 9.4 multiplier.
    """
    try:
        from src.phase91_adaptive_governance import health_weighted_ramp_size
        health = composite_health()
        step = health_weighted_ramp_size(base_step, health)
        
        # Phase 9.4: Apply recovery-based ramp multiplier
        try:
            from src.phase94_recovery_scaling import get_phase94_ramp_multiplier
            multiplier = get_phase94_ramp_multiplier()
            step *= multiplier
        except:
            pass  # Phase 9.4 not available or multiplier not set
        
        return step
    except Exception as e:
        print(f"⚠️  Phase 9.1: Failed to calculate health-weighted ramp: {e}")
        return base_step  # fallback to base step

# ==============================
# Watchdog Hooks
# ==============================

def get_heartbeats() -> Dict[str, float]:
    """Get all subsystem heartbeats."""
    try:
        from src.phase9_autonomy import _heartbeats
        return _heartbeats.copy()
    except:
        return {}

def get_heartbeat_timeout(subsystem: str) -> int:
    """Get timeout threshold for subsystem (default 600s)."""
    try:
        from src.phase9_autonomy import CFG9
        return CFG9.heartbeat_timeout_sec.get(subsystem, 600)
    except:
        return 600

def try_restart_subsystem(subsystem: str):
    """Attempt to restart a degraded subsystem."""
    try:
        from src.watchdog import attempt_restart
        attempt_restart(subsystem)
    except Exception as e:
        print(f"⚠️  Phase 9.1: Failed to restart {subsystem}: {e}")

def run_full_validation_suite():
    """Run Phase 8.2 validation suite."""
    try:
        from src.phase82_validation import run_full_validation_suite as run_suite
        return run_suite()
    except Exception as e:
        print(f"⚠️  Phase 9.1: Failed to run validation suite: {e}")
        return None

# ==============================
# Health & Calibration Hooks
# ==============================

def composite_health() -> float:
    """Get composite health score from Phase 9."""
    try:
        from src.phase9_autonomy import composite_health as get_health
        return get_health()
    except:
        return 0.5

def calibration_confidence() -> float:
    """Get calibration confidence from Phase 9."""
    try:
        from src.phase9_autonomy import calibration_confidence as get_conf
        return get_conf()
    except:
        return 0.3

def pnl_attribution_last_hours(hours: int) -> Optional[Dict[str, float]]:
    """Get P&L attribution by symbol over last N hours."""
    try:
        from src.phase84_86_hooks import get_pnl_attribution_last_hours
        return get_pnl_attribution_last_hours(hours)
    except:
        return {}

def tier_for_symbol(symbol: str) -> str:
    """Get tier classification for symbol."""
    try:
        from src.utils import get_tier_for_symbol
        return get_tier_for_symbol(symbol)
    except:
        majors = ["ETHUSDT", "BTCUSDT"]
        l1s = ["SOLUSDT", "AVAXUSDT", "DOTUSDT"]
        if symbol in majors:
            return "majors"
        elif symbol in l1s:
            return "l1s"
        return "experimental"

# ==============================
# Parameter Nudge Hooks
# ==============================

def nudge_ev_gate_tier(tier: str, delta_usd: float):
    """Nudge EV gate for tier (positive = raise, negative = lower)."""
    try:
        from src.phase83_drift_detector import current_ev_gate_tier, set_ev_gate_tier
        curr = current_ev_gate_tier(tier)
        new_val = max(0.1, min(1.0, curr + delta_usd))
        set_ev_gate_tier(tier, new_val)
    except Exception as e:
        print(f"⚠️  Phase 9.1: Failed to nudge EV gate for {tier}: {e}")

def nudge_trailing_start_r_tier(tier: str, delta_r: float):
    """Nudge trailing start R for tier."""
    try:
        from src.phase83_drift_detector import current_trailing_start_r_tier, set_trailing_start_r_tier
        curr = current_trailing_start_r_tier(tier)
        new_val = max(0.3, min(2.0, curr + delta_r))
        set_trailing_start_r_tier(tier, new_val)
    except Exception as e:
        print(f"⚠️  Phase 9.1: Failed to nudge trailing R for {tier}: {e}")

def nudge_add_spacing_tier(tier: str, delta_r: float):
    """Nudge pyramiding spacing R for tier."""
    try:
        from src.phase83_drift_detector import current_add_spacing_tier, set_add_spacing_tier
        curr = current_add_spacing_tier(tier)
        new_val = max(0.2, min(2.0, curr + delta_r))
        set_add_spacing_tier(tier, new_val)
    except Exception as e:
        print(f"⚠️  Phase 9.1: Failed to nudge add spacing for {tier}: {e}")
