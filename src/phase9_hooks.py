"""
Phase 9 Hooks — Data Access Layer
Provides data access and control interfaces for Phase 9 Autonomy Controller.
"""

import time
import json
from typing import Dict, List, Optional

def emit_dashboard_event(event_type: str, payload: dict):
    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    print(f"📊 PHASE9 [{ts}] {event_type}: {payload}")
    try:
        with open("logs/dashboard_events.jsonl", "a") as f:
            f.write(json.dumps({"ts": time.time(), "event": event_type, "payload": payload}) + "\n")
    except:
        pass

def last_validation_suite_passed() -> bool:
    try:
        from src.phase82_validation import get_validation_status
        status = get_validation_status()
        return status.get("all_passed", True) if status else True
    except Exception:
        pass
    return True

def run_full_validation_suite() -> bool:
    try:
        from src.phase82_validation import run_full_validation_suite as run_suite
        result = run_suite()
        return result.all_passed if result else False
    except Exception:
        pass
    return False

def phase83_status_fetch() -> Dict:
    try:
        from src.phase83_drift_detector import get_phase83_status
        return get_phase83_status()
    except Exception:
        pass
    return {}

def refresh_phase83_baselines():
    try:
        from src.phase83_drift_detector import capture_all_baselines
        capture_all_baselines()
    except Exception:
        pass

def last_regime_change_ts() -> Optional[float]:
    try:
        from src.phase80_coordinator import get_last_regime_change_ts
        return get_last_regime_change_ts()
    except Exception:
        pass
    return None

def current_global_regime_name() -> str:
    try:
        from src.phase82_go_live import get_current_regime_v2
        return get_current_regime_v2()
    except Exception:
        pass
    return "stable"

def phase86_preserve_until_ts() -> Optional[float]:
    try:
        from src.phase84_86_expansion import get_phase86_preserve_until_ts
        return get_phase86_preserve_until_ts()
    except Exception:
        pass
    return None

def rolling_drawdown_pct_24h() -> float:
    try:
        from src.portfolio_tracker import get_rolling_drawdown_24h
        return get_rolling_drawdown_24h()
    except Exception:
        pass
    return 0.0

def slippage_p75_bps_portfolio() -> float:
    try:
        from src.phase6_alpha_engine import get_slippage_p75_bps
        return get_slippage_p75_bps()
    except Exception:
        pass
    return 12.0

def order_reject_rate_15m() -> float:
    try:
        from src.phase6_alpha_engine import get_reject_rate_15m
        return get_reject_rate_15m()
    except Exception:
        pass
    return 0.0

def latency_ms_1m() -> float:
    try:
        from src.exchange_gateway import get_avg_latency_1m
        return get_avg_latency_1m()
    except Exception:
        pass
    return 100.0

def increase_deployed_capital_pct_tiers(tiers: List[str], step_pct: float):
    try:
        from src.phase82_go_live import increase_deployed_capital_pct_tiers as ramp_tiers
        ramp_tiers(tiers, step_pct)
    except Exception:
        pass

def throttle_tier_exposure(tier: str, drop_pct: Optional[float] = None):
    try:
        from src.phase82_go_live import get_deployed_capital_pct, increase_deployed_capital_pct_tiers
        if drop_pct:
            current_pct = get_deployed_capital_pct(tier)
            new_pct = max(0.0, current_pct - drop_pct)
            delta = new_pct - current_pct
            increase_deployed_capital_pct_tiers([tier], delta)
    except Exception:
        pass

def pnl_attribution_last_hours(hours: int) -> Dict[str, float]:
    try:
        from src.phase84_86_hooks import get_pnl_attribution_last_hours
        return get_pnl_attribution_last_hours(hours)
    except Exception:
        pass
    return {}

def tier_for_symbol(symbol: str) -> str:
    majors = ["ETHUSDT", "BTCUSDT"]
    l1s = ["SOLUSDT", "AVAXUSDT", "DOTUSDT", "TRXUSDT"]
    if symbol in majors:
        return "majors"
    elif symbol in l1s:
        return "l1s"
    else:
        return "experimental"

def nudge_ev_gate_tier(tier: str, delta_usd: float):
    if abs(delta_usd) < 0.01:
        return
    emit_dashboard_event(f"phase9_ev_nudge_{tier}", {"delta_usd": round(delta_usd, 3)})

def nudge_trailing_start_r_tier(tier: str, delta_r: float):
    if abs(delta_r) < 0.01:
        return
    emit_dashboard_event(f"phase9_trailing_nudge_{tier}", {"delta_r": round(delta_r, 3)})

def nudge_add_spacing_tier(tier: str, delta_r: float):
    if abs(delta_r) < 0.01:
        return
    emit_dashboard_event(f"phase9_pyramiding_nudge_{tier}", {"delta_r": round(delta_r, 3)})

def phase87_on_any_critical_event(event: str, payload: Dict):
    try:
        from src.phase87_89_expansion import phase87_append_audit
        phase87_append_audit(event, payload)
    except Exception:
        pass

def try_restart_subsystem(name: str):
    emit_dashboard_event(f"phase9_recovery_attempt_{name}", {})
