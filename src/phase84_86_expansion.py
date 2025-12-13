"""
Phases 8.4–8.6 Expansion Pack — Profit Optimizer, Predictive Intelligence, Institutional Risk Layer
Unified implementation: dynamic capital reallocation, regime forecasting + early-warning sentinel,
portfolio hedging and correlation guards.

Phase 8.4: Profit Optimizer - Attribution-driven reweighting with confidence scoring
Phase 8.5: Predictive Intelligence - Regime forecasting with early-warning sentinel
Phase 8.6: Institutional Risk Layer - Correlation guards, hedge dispatcher, preservation mode
"""

import time
import threading
import json
import os
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple
from datetime import datetime
import pytz

ARIZONA_TZ = pytz.timezone("America/Phoenix")

# ======================================================================================
# Shared utilities
# ======================================================================================

_state_lock = threading.Lock()

def now() -> float:
    return time.time()

def emit_event(event_type: str, payload: dict):
    """Emit telemetry event for dashboard integration."""
    ts = datetime.now(ARIZONA_TZ).strftime('%Y-%m-%d %H:%M:%S')
    print(f"📊 PHASE84-86 [{ts}] {event_type}: {payload}")

# ======================================================================================
# Phase 8.4 — Profit Optimizer
# ======================================================================================

@dataclass
class Phase84Config:
    attribution_window_hours: int = 24
    top_n: int = 5
    bottom_n: int = 5
    weight_nudge_pct_up: float = 0.10
    weight_nudge_pct_down: float = 0.10
    require_validation_passes: int = 2
    regime_stability_min_minutes: int = 60
    pyramiding_uplift_rr_min: float = 0.12
    max_pyramiding_depth_majors: int = 3
    max_pyramiding_depth_l1s: int = 2
    max_pyramiding_depth_experimental: int = 1
    corr_cap_pair: float = 0.55
    theme_cap_pct: float = 0.40
    optimizer_tick_sec: int = 1800

CFG84 = Phase84Config()

_validation_suite_history: List[Dict] = []
_last_regime_change_ts: Optional[float] = None
_symbol_weights: Dict[str, float] = {}
_pyramiding_depth_caps: Dict[str, int] = {}

def phase84_health_score() -> float:
    """Composite confidence score from validation history and regime stability."""
    passes = 0
    for r in reversed(_validation_suite_history[-5:]):
        if r.get("all_passed"):
            passes += 1
        else:
            break
    val_score = min(1.0, passes / max(1, CFG84.require_validation_passes))
    
    last_change = _last_regime_change_ts or (now() - CFG84.regime_stability_min_minutes * 60)
    stable_min = (now() - last_change) >= CFG84.regime_stability_min_minutes * 60
    regime_score = 1.0 if stable_min else 0.5
    
    return 0.5 * val_score + 0.5 * regime_score

def phase84_pick_symbols_for_nudges(attrib: Dict[str, float]) -> Tuple[List[str], List[str]]:
    """Select top and bottom performers for reweighting."""
    top = [s for s, _ in sorted(attrib.items(), key=lambda kv: kv[1], reverse=True)[:CFG84.top_n]]
    bottom = [s for s, _ in sorted(attrib.items(), key=lambda kv: kv[1])[:CFG84.bottom_n]]
    return top, bottom

def phase84_correlation_guard(symbols: List[str]) -> List[str]:
    """Filter out symbols that violate pairwise correlation caps."""
    from phase84_86_hooks import get_large_positions_symbols, get_rolling_corr_24h
    
    filtered = []
    large_syms = get_large_positions_symbols()
    
    for s in symbols:
        ok = True
        for ls in large_syms:
            c = get_rolling_corr_24h(s, ls)
            if c is not None and c > CFG84.corr_cap_pair:
                ok = False
                emit_event("phase84_corr_skip", {"symbol": s, "corr_with": ls, "corr": round(c, 2)})
                break
        if ok:
            filtered.append(s)
    
    return filtered

def phase84_theme_exposure_guard(symbols: List[str]) -> List[str]:
    """Limit exposure to correlated themes."""
    from phase84_86_hooks import get_portfolio_exposure_pct_tier, get_tier_for_symbol
    
    kept = []
    tier_exposure = {
        t: get_portfolio_exposure_pct_tier(t)
        for t in ["majors", "l1s", "experimental"]
    }
    
    for s in symbols:
        t = get_tier_for_symbol(s)
        if tier_exposure.get(t, 0.0) <= CFG84.theme_cap_pct:
            kept.append(s)
        else:
            emit_event("phase84_theme_skip", {"symbol": s, "tier": t, "exposure": tier_exposure.get(t)})
    
    return kept

def phase84_apply_nudges(top_syms: List[str], bottom_syms: List[str], health: float):
    """Apply allocation nudges proportionally to health score."""
    with _state_lock:
        up = CFG84.weight_nudge_pct_up * health
        down = CFG84.weight_nudge_pct_down * health
        
        for s in top_syms:
            current = _symbol_weights.get(s, 1.0)
            _symbol_weights[s] = current * (1.0 + up)
        
        for s in bottom_syms:
            current = _symbol_weights.get(s, 1.0)
            _symbol_weights[s] = current * (1.0 - down)

def phase84_adaptive_pyramiding():
    """Increase allowable pyramiding depth when adds demonstrate net R:R uplift."""
    from phase84_86_hooks import get_adds_rr_uplift_24h_tier
    
    with _state_lock:
        for tier, base_cap in {
            "majors": CFG84.max_pyramiding_depth_majors,
            "l1s": CFG84.max_pyramiding_depth_l1s,
            "experimental": CFG84.max_pyramiding_depth_experimental
        }.items():
            uplift = get_adds_rr_uplift_24h_tier(tier)
            if uplift is None or uplift < CFG84.pyramiding_uplift_rr_min:
                _pyramiding_depth_caps[tier] = max(1, base_cap - 1)
            else:
                _pyramiding_depth_caps[tier] = base_cap

def phase84_optimizer_tick():
    """Main optimizer tick: reweight symbols based on attribution."""
    from phase84_86_hooks import get_pnl_attribution_last_hours
    
    try:
        attrib = get_pnl_attribution_last_hours(CFG84.attribution_window_hours)
        if not attrib:
            emit_event("phase84_skip_no_attrib", {})
            return
        
        top, bottom = phase84_pick_symbols_for_nudges(attrib)
        top = phase84_correlation_guard(top)
        bottom = phase84_correlation_guard(bottom)
        top = phase84_theme_exposure_guard(top)
        bottom = phase84_theme_exposure_guard(bottom)
        
        health = phase84_health_score()
        phase84_apply_nudges(top, bottom, health)
        phase84_adaptive_pyramiding()
        
        emit_event("phase84_nudges_applied", {
            "top": top,
            "bottom": bottom,
            "health": round(health, 2),
            "weights_active": len(_symbol_weights)
        })
    except Exception as e:
        emit_event("phase84_error", {"error": str(e)})

def phase84_update_validation_history(result: Dict):
    """Update validation suite history (called from Phase 8.2)."""
    global _validation_suite_history
    _validation_suite_history.append(result)
    if len(_validation_suite_history) > 10:
        _validation_suite_history = _validation_suite_history[-10:]

def phase84_set_regime_change(ts: float):
    """Notify of regime change (called from regime detector)."""
    global _last_regime_change_ts
    _last_regime_change_ts = ts

def get_phase84_status() -> Dict:
    """Get Phase 8.4 status for dashboard."""
    with _state_lock:
        return {
            "validation_history_n": len(_validation_suite_history),
            "last_regime_change_ts": _last_regime_change_ts,
            "health_score": round(phase84_health_score(), 2),
            "symbol_weights": _symbol_weights.copy(),
            "pyramiding_depth_caps": _pyramiding_depth_caps.copy()
        }

# ======================================================================================
# Phase 8.5 — Predictive Intelligence
# ======================================================================================

@dataclass
class Phase85Config:
    forecast_horizon_min: int = 30
    early_warning_threshold: float = 0.65
    cooldown_minutes: int = 30
    scenario_vol_spike_pct: float = 30.0
    scenario_spread_widen_bps: float = 5.0
    cadence_sec: int = 300

CFG85 = Phase85Config()
_last_early_warning_ts: Optional[float] = None
_conservative_mode_active: bool = False

def phase85_forecast_inputs() -> Dict[str, float]:
    """Gather inputs for regime risk forecasting."""
    from phase84_86_hooks import (
        get_vol_trend_persistence, get_orderbook_imbalance_score,
        get_realized_return_skew_24h, get_portfolio_spread_p50_bps
    )
    
    return {
        "vol_persist": get_vol_trend_persistence() or 0.0,
        "imbalance": get_orderbook_imbalance_score() or 0.0,
        "skew": get_realized_return_skew_24h() or 0.0,
        "spread_p50_bps": get_portfolio_spread_p50_bps() or 10.0
    }

def phase85_forecast_regime_risk(features: Dict[str, float]) -> float:
    """Forecast regime risk score (0..1) based on features."""
    risk = 0.0
    risk += 0.4 * (1.0 if features["skew"] < 0 else 0.2)
    risk += 0.3 * (1.0 - features["imbalance"])
    risk += 0.3 * min(1.0, (features["spread_p50_bps"] / 12.0))
    return max(0.0, min(1.0, risk))

def phase85_early_warning_tick():
    """Early warning system: preemptive conservative mode."""
    global _last_early_warning_ts, _conservative_mode_active
    
    try:
        f = phase85_forecast_inputs()
        risk = phase85_forecast_regime_risk(f)
        
        if risk >= CFG85.early_warning_threshold:
            if (not _last_early_warning_ts) or ((now() - _last_early_warning_ts) > CFG85.cooldown_minutes * 60):
                _conservative_mode_active = True
                emit_event("phase85_early_warning_enter", {
                    "risk": round(risk, 2),
                    "features": {k: round(v, 3) for k, v in f.items()}
                })
                _last_early_warning_ts = now()
        else:
            if _conservative_mode_active:
                _conservative_mode_active = False
                emit_event("phase85_early_warning_clear", {
                    "risk": round(risk, 2)
                })
    except Exception as e:
        emit_event("phase85_error", {"error": str(e)})

def phase85_scenario_stress_estimates():
    """Scenario analysis for stress testing (report-only)."""
    from phase84_86_hooks import get_slippage_p75_bps_portfolio, get_realized_rr_24h_portfolio
    
    try:
        base_slip = get_slippage_p75_bps_portfolio() or 12.0
        base_rr = get_realized_rr_24h_portfolio() or 1.0
        
        est_slip = base_slip + CFG85.scenario_spread_widen_bps
        est_rr = base_rr - 0.1
        
        emit_event("phase85_scenario_stress", {
            "est_slip_p75_bps": round(est_slip, 2),
            "est_rr": round(est_rr, 2)
        })
    except Exception as e:
        emit_event("phase85_scenario_error", {"error": str(e)})

def get_phase85_status() -> Dict:
    """Get Phase 8.5 status for dashboard."""
    return {
        "last_early_warning_ts": _last_early_warning_ts,
        "conservative_mode_active": _conservative_mode_active,
        "forecast_horizon_min": CFG85.forecast_horizon_min
    }

# ======================================================================================
# Phase 8.6 — Institutional Risk Layer
# ======================================================================================

@dataclass
class Phase86Config:
    pair_corr_cap: float = 0.60
    theme_exposure_cap_pct: float = 0.35
    hedge_trigger_drawdown_pct: float = 3.0
    hedge_trigger_corr_cluster_score: float = 0.65
    preserve_mode_dd_pct: float = 5.0
    preserve_mode_min_minutes: int = 60
    exposure_soft_cap_pct: Dict[str, float] = field(default_factory=lambda: {
        "majors": 0.40, "l1s": 0.28, "experimental": 0.18
    })
    exposure_hard_cap_pct: Dict[str, float] = field(default_factory=lambda: {
        "majors": 0.48, "l1s": 0.32, "experimental": 0.22
    })
    cadence_sec: int = 300

CFG86 = Phase86Config()
_preserve_mode_until_ts: Optional[float] = None
_frozen_symbols: List[str] = []

def phase86_cluster_corr_risk_score() -> float:
    """Estimate cluster risk by averaging pairwise correlations."""
    from phase84_86_hooks import get_large_positions_symbols, get_rolling_corr_24h
    
    syms = get_large_positions_symbols()[:6]
    if len(syms) < 2:
        return 0.0
    
    pairs = []
    for i in range(len(syms)):
        for j in range(i + 1, len(syms)):
            c = get_rolling_corr_24h(syms[i], syms[j])
            if c is not None:
                pairs.append(c)
    
    if not pairs:
        return 0.0
    
    avg_corr = sum(pairs) / len(pairs)
    return max(0.0, min(1.0, avg_corr))

def phase86_apply_correlation_guards():
    """Freeze new entries for pairs exceeding correlation cap."""
    from phase84_86_hooks import (
        get_candidate_entry_symbols, get_large_positions_symbols, get_rolling_corr_24h
    )
    
    global _frozen_symbols
    
    try:
        syms = get_candidate_entry_symbols()
        large_syms = get_large_positions_symbols()
        
        for s in syms:
            for ls in large_syms:
                c = get_rolling_corr_24h(s, ls)
                if c is not None and c > CFG86.pair_corr_cap:
                    if s not in _frozen_symbols:
                        _frozen_symbols.append(s)
                        emit_event("phase86_corr_guard_freeze", {
                            "symbol": s,
                            "pair_with": ls,
                            "corr": round(c, 2)
                        })
    except Exception as e:
        emit_event("phase86_corr_guard_error", {"error": str(e)})

def phase86_theme_caps():
    """Throttle tier exposure when exceeding hard caps."""
    from phase84_86_hooks import get_portfolio_exposure_pct_tier
    
    try:
        for t, hard_cap in CFG86.exposure_hard_cap_pct.items():
            exp = get_portfolio_exposure_pct_tier(t)
            if exp is None:
                continue
            
            if exp > hard_cap:
                target = CFG86.exposure_soft_cap_pct.get(t, hard_cap)
                emit_event("phase86_theme_throttle", {
                    "tier": t,
                    "from_pct": round(exp * 100, 1),
                    "to_pct": round(target * 100, 1)
                })
    except Exception as e:
        emit_event("phase86_theme_error", {"error": str(e)})

def phase86_hedge_dispatcher():
    """Deploy portfolio hedge on drawdown or cluster risk triggers."""
    from phase84_86_hooks import get_rolling_drawdown_pct_24h
    
    try:
        dd = get_rolling_drawdown_pct_24h()
        cluster = phase86_cluster_corr_risk_score()
        
        if (dd is not None and dd >= CFG86.hedge_trigger_drawdown_pct) or \
           (cluster >= CFG86.hedge_trigger_corr_cluster_score):
            emit_event("phase86_hedge_trigger", {
                "drawdown_pct": round(dd, 2) if dd else None,
                "cluster_risk": round(cluster, 2),
                "action": "hedge_recommended"
            })
    except Exception as e:
        emit_event("phase86_hedge_error", {"error": str(e)})

def phase86_capital_preservation_mode_tick():
    """Enter capital preservation mode on extreme drawdown."""
    global _preserve_mode_until_ts
    from phase84_86_hooks import get_rolling_drawdown_pct_24h
    
    try:
        dd = get_rolling_drawdown_pct_24h()
        
        if dd is not None and dd >= CFG86.preserve_mode_dd_pct:
            if not _preserve_mode_until_ts:
                _preserve_mode_until_ts = now() + CFG86.preserve_mode_min_minutes * 60
                emit_event("phase86_preserve_enter", {"drawdown_pct": round(dd, 2)})
        else:
            if _preserve_mode_until_ts and now() > _preserve_mode_until_ts:
                _preserve_mode_until_ts = None
                emit_event("phase86_preserve_exit", {})
    except Exception as e:
        emit_event("phase86_preserve_error", {"error": str(e)})

def get_phase86_status() -> Dict:
    """Get Phase 8.6 status for dashboard."""
    return {
        "preserve_until_ts": _preserve_mode_until_ts,
        "frozen_symbols": _frozen_symbols.copy(),
        "cluster_risk_score": round(phase86_cluster_corr_risk_score(), 2),
        "preserve_mode_active": _preserve_mode_until_ts is not None and now() < _preserve_mode_until_ts
    }

# ======================================================================================
# Initialization
# ======================================================================================

def initialize_phase84_86():
    """Initialize all three expansion phases."""
    emit_event("started", {
        "phase84": "Profit Optimizer",
        "phase85": "Predictive Intelligence",
        "phase86": "Institutional Risk Layer"
    })
    
    print("✅ Phase 8.4-8.6 Expansion Pack initialized")
    return True
