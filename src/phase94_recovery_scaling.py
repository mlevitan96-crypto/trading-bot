"""
Phase 9.4 — Recovery & Scaling Pack
Purpose: Automatically scale exposure caps and ramp sizes once profitability metrics recover.
Integrates with Phase 9.2 (discipline) and Phase 9.3 (venue governance).
"""

from dataclasses import dataclass, field, asdict
from typing import Dict, List
import json
import time
from datetime import datetime
from pathlib import Path

@dataclass
class Phase94Config:
    win_rate_partial: float = 0.40
    win_rate_full: float = 0.60
    sharpe_partial: float = 0.80
    sharpe_full: float = 1.00
    pnl_threshold_usd: float = 250.0
    sustained_passes_required: int = 3
    exposure_increment_partial: float = 0.05
    exposure_increment_full: float = 0.10
    ramp_multiplier_partial: float = 0.5
    ramp_multiplier_full: float = 1.0
    cadence_sec: int = 600

CFG94 = Phase94Config()

_state = {
    "sustained_passes": 0,
    "last_tick_ts": 0,
    "ramps_frozen": False,  # Start unfrozen, will freeze on first fail check
    "current_ramp_multiplier": 1.0,  # Start at 1.0x (neutral), will adjust based on recovery
    "last_valid_multiplier": 1.0,  # Preserved multiplier before freeze (restored on unfreeze)
    "scaling_level": "none",
    "exposure_adjustments": [],
    "last_valid_metrics": {}  # Cache last valid metrics to avoid thrashing on transient failures
}

STATE_FILE = Path("logs/phase94_state.json")
EVENT_LOG = Path("logs/phase94_events.jsonl")

# ======================================================================================
# State persistence
# ======================================================================================

def _load_state():
    global _state
    if STATE_FILE.exists():
        try:
            with open(STATE_FILE, 'r') as f:
                _state.update(json.load(f))
        except:
            pass

def _save_state():
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(STATE_FILE, 'w') as f:
        json.dump(_state, f, indent=2)

def _emit_event(event: str, payload: Dict):
    """Emit event to JSONL log"""
    EVENT_LOG.parent.mkdir(parents=True, exist_ok=True)
    with open(EVENT_LOG, 'a') as f:
        f.write(json.dumps({
            "ts": time.time(),
            "dt": datetime.now().isoformat(),
            "event": event,
            "payload": payload
        }) + '\n')

def _emit_dashboard_event(event: str, payload: Dict):
    """Emit event for dashboard consumption"""
    _emit_event(event, payload)

# ======================================================================================
# Integration hooks
# ======================================================================================

def calc_global_win_rate() -> float:
    """Calculate global win rate across all venues with fallback to cached value"""
    try:
        from src.phase92_profit_discipline import _load_trades
        trades = _load_trades()
        if not trades:
            # No trades yet - use cached value or default
            return _state["last_valid_metrics"].get("win_rate", 0.0)
        wins = sum(1 for t in trades if t.get("gross_profit", 0) > 0)
        wr = wins / len(trades)
        _state["last_valid_metrics"]["win_rate"] = wr  # Cache valid metric
        return wr
    except:
        # Exception - use cached value or fallback
        return _state["last_valid_metrics"].get("win_rate", 0.0)

def rolling_sharpe_24h() -> float:
    """Calculate 24h Sharpe ratio across all venues with fallback to cached value"""
    try:
        from src.phase93_venue_governance import _load_positions
        from src.phase92_profit_discipline import _load_trades
        
        trades = _load_trades()
        if not trades:
            # No trades yet - use cached value or default
            return _state["last_valid_metrics"].get("sharpe", 0.0)
        
        # Calculate returns from last 24h closed positions
        cutoff = time.time() - 86400
        returns = []
        for t in trades:
            if t.get("ts", 0) >= cutoff:
                gross = t.get("gross_profit", 0)
                fees = t.get("fees", 0)
                size = t.get("size", 1)
                if size > 0:
                    returns.append((gross - fees) / size)
        
        if len(returns) < 5:
            # Not enough data - use cached value or default
            return _state["last_valid_metrics"].get("sharpe", 0.0)
        
        import numpy as np
        sharpe = float(np.mean(returns) / (np.std(returns) + 1e-9))
        _state["last_valid_metrics"]["sharpe"] = sharpe  # Cache valid metric
        return sharpe
    except:
        # Exception - use cached value or fallback
        return _state["last_valid_metrics"].get("sharpe", 0.0)

def net_pnl_24h() -> float:
    """Calculate net P&L over last 24h with fallback to cached value"""
    try:
        from src.phase93_venue_governance import net_pnl_24h_venue
        spot_pnl = net_pnl_24h_venue("spot") or 0.0
        futures_pnl = net_pnl_24h_venue("futures") or 0.0
        pnl = spot_pnl + futures_pnl
        _state["last_valid_metrics"]["pnl"] = pnl  # Cache valid metric
        return pnl
    except:
        # Exception - use cached value or fallback
        return _state["last_valid_metrics"].get("pnl", 0.0)

def adjust_exposure_caps(increment: float):
    """Adjust venue exposure caps in Phase 9.3 and persist them"""
    try:
        from src.phase93_venue_governance import CFG93, _save_state as save_phase93_state
        
        # Increase spot and futures caps by increment
        old_spot = CFG93.venue_exposure_cap_pct.get("spot", 0.20)
        old_futures = CFG93.venue_exposure_cap_pct.get("futures", 0.60)
        
        new_spot = min(old_spot + increment, 0.50)  # Cap at 50%
        new_futures = min(old_futures + increment, 0.80)  # Cap at 80%
        
        CFG93.venue_exposure_cap_pct["spot"] = new_spot
        CFG93.venue_exposure_cap_pct["futures"] = new_futures
        
        # Persist to Phase 9.3 state file
        save_phase93_state()
        
        _state["exposure_adjustments"].append({
            "ts": time.time(),
            "increment": increment,
            "spot_cap": new_spot,
            "futures_cap": new_futures
        })
        
        _emit_event("exposure_caps_adjusted", {
            "increment": increment,
            "spot_old": old_spot,
            "spot_new": new_spot,
            "futures_old": old_futures,
            "futures_new": new_futures
        })
    except Exception as e:
        _emit_event("exposure_adjustment_error", {"error": str(e)})

def set_ramp_multiplier(mult: float):
    """Set capital ramp multiplier for Phase 9"""
    _state["current_ramp_multiplier"] = mult
    _emit_event("ramp_multiplier_set", {"multiplier": mult})

def freeze_ramps_global():
    """Freeze all capital ramps and preserve current multiplier"""
    # Save current multiplier before freezing
    _state["last_valid_multiplier"] = _state.get("current_ramp_multiplier", 1.0)
    _state["ramps_frozen"] = True
    _emit_event("ramps_frozen", {
        "preserved_multiplier": _state["last_valid_multiplier"]
    })

def allow_ramps_global():
    """Allow capital ramps and restore preserved multiplier"""
    _state["ramps_frozen"] = False
    # Restore last valid multiplier (if not already set by scaling decision)
    if _state.get("current_ramp_multiplier", 0) == 0:
        _state["current_ramp_multiplier"] = _state.get("last_valid_multiplier", 1.0)
    _emit_event("ramps_allowed", {
        "restored_multiplier": _state["current_ramp_multiplier"]
    })

def get_phase94_ramp_multiplier() -> float:
    """
    Get current ramp multiplier for Phase 9 integration.
    Returns 0 when frozen (to prevent ramps), otherwise returns the active multiplier.
    """
    if _state.get("ramps_frozen", False):
        return 0.0  # Return 0 when frozen to prevent ramps
    return _state.get("current_ramp_multiplier", 1.0)

def is_phase94_ramps_frozen() -> bool:
    """Check if Phase 9.4 has frozen ramps"""
    return _state.get("ramps_frozen", True)

def phase87_on_any_critical_event(event: str, payload: Dict):
    """Emit to Phase 8.7 audit chain"""
    try:
        from src.phase87_transparency_audit import phase87_emit_event
        phase87_emit_event(f"phase94_{event}", payload)
    except:
        pass

# ======================================================================================
# Core recovery scaling logic
# ======================================================================================

def phase94_recovery_scaling_tick():
    """Execute recovery scaling check"""
    _load_state()
    
    win_rate = calc_global_win_rate() or 0.0
    sharpe = rolling_sharpe_24h() or 0.0
    pnl = net_pnl_24h() or 0.0

    # Check thresholds
    if win_rate >= CFG94.win_rate_partial and sharpe >= CFG94.sharpe_partial and pnl >= CFG94.pnl_threshold_usd:
        _state["sustained_passes"] += 1
        _emit_dashboard_event("phase94_pass", {
            "passes": _state["sustained_passes"],
            "win_rate": round(win_rate, 3),
            "sharpe": round(sharpe, 2),
            "pnl": round(pnl, 2)
        })
    else:
        _state["sustained_passes"] = 0
        freeze_ramps_global()
        _state["scaling_level"] = "none"
        _emit_dashboard_event("phase94_fail", {
            "win_rate": round(win_rate, 3),
            "sharpe": round(sharpe, 2),
            "pnl": round(pnl, 2)
        })

    # Scaling decisions
    if _state["sustained_passes"] >= CFG94.sustained_passes_required:
        if win_rate >= CFG94.win_rate_full and sharpe >= CFG94.sharpe_full:
            adjust_exposure_caps(CFG94.exposure_increment_full)
            set_ramp_multiplier(CFG94.ramp_multiplier_full)
            allow_ramps_global()
            _state["scaling_level"] = "full"
            _emit_dashboard_event("phase94_full_scaling", {
                "win_rate": round(win_rate, 3),
                "sharpe": round(sharpe, 2),
                "pnl": round(pnl, 2)
            })
            phase87_on_any_critical_event("full_scaling", {
                "win_rate": round(win_rate, 3),
                "sharpe": round(sharpe, 2),
                "pnl": round(pnl, 2)
            })
        else:
            adjust_exposure_caps(CFG94.exposure_increment_partial)
            set_ramp_multiplier(CFG94.ramp_multiplier_partial)
            allow_ramps_global()
            _state["scaling_level"] = "partial"
            _emit_dashboard_event("phase94_partial_scaling", {
                "win_rate": round(win_rate, 3),
                "sharpe": round(sharpe, 2),
                "pnl": round(pnl, 2)
            })
            phase87_on_any_critical_event("partial_scaling", {
                "win_rate": round(win_rate, 3),
                "sharpe": round(sharpe, 2),
                "pnl": round(pnl, 2)
            })
    
    _state["last_tick_ts"] = time.time()
    _save_state()

# ======================================================================================
# Startup and status
# ======================================================================================

def _phase94_background_loop():
    """Background thread that executes recovery scaling checks"""
    import threading
    while True:
        try:
            time.sleep(CFG94.cadence_sec)
            phase94_recovery_scaling_tick()
        except Exception as e:
            _emit_event("phase94_tick_error", {"error": str(e)})

def start_phase94_recovery_scaling():
    """Initialize Phase 9.4 and start background monitoring"""
    import threading
    _load_state()
    
    # Log initial state
    _emit_dashboard_event("phase94_started", {
        "cfg": asdict(CFG94),
        "initial_state": {
            "ramps_frozen": _state.get("ramps_frozen", False),
            "ramp_multiplier": _state.get("current_ramp_multiplier", 1.0),
            "sustained_passes": _state.get("sustained_passes", 0)
        }
    })
    
    # Start background thread
    thread = threading.Thread(target=_phase94_background_loop, daemon=True)
    thread.start()
    
    print("✅ Phase 9.4 Recovery & Scaling Pack started"
          f" (ramps_frozen={_state.get('ramps_frozen', False)}, "
          f"multiplier={_state.get('current_ramp_multiplier', 1.0):.1f}x)")

def get_phase94_status() -> Dict:
    """Get current Phase 9.4 status for dashboard"""
    _load_state()
    
    win_rate = calc_global_win_rate() or 0.0
    sharpe = rolling_sharpe_24h() or 0.0
    pnl = net_pnl_24h() or 0.0
    
    # Get current venue caps
    try:
        from src.phase93_venue_governance import CFG93
        spot_cap = CFG93.venue_exposure_cap_pct.get("spot", 0.20)
        futures_cap = CFG93.venue_exposure_cap_pct.get("futures", 0.60)
    except:
        spot_cap = 0.20
        futures_cap = 0.60
    
    return {
        "sustained_passes": _state.get("sustained_passes", 0),
        "passes_required": CFG94.sustained_passes_required,
        "ramps_frozen": _state.get("ramps_frozen", True),
        "scaling_level": _state.get("scaling_level", "none"),
        "current_ramp_multiplier": _state.get("current_ramp_multiplier", 0.0),
        "metrics": {
            "win_rate": round(win_rate, 3),
            "sharpe": round(sharpe, 2),
            "pnl": round(pnl, 2)
        },
        "thresholds": {
            "partial": {
                "win_rate": CFG94.win_rate_partial,
                "sharpe": CFG94.sharpe_partial,
                "pnl": CFG94.pnl_threshold_usd
            },
            "full": {
                "win_rate": CFG94.win_rate_full,
                "sharpe": CFG94.sharpe_full,
                "pnl": CFG94.pnl_threshold_usd
            }
        },
        "exposure_caps": {
            "spot": spot_cap,
            "futures": futures_cap
        },
        "recent_adjustments": _state.get("exposure_adjustments", [])[-5:],
        "last_tick": _state.get("last_tick_ts", 0)
    }
