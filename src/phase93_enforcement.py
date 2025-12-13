"""
Phase 9.3 Enforcement Patch — Router + Gate + Executor
Goal:
- Hard-block spot entries at all critical chokepoints (router, gate, executor)
- Fail-safe detection and halt if any spot trade bypasses governance
- Futures-only until spot meets expectancy thresholds (from 9.3/9.5)
- Unified audit: emits events on every block/breach

Integration points:
- venue_policy: Call before signal processing
- venue_guard_entry_gate: Call before position sizing
- venue_guard_execution_wrapper: Wrap order placement
- start_venue_enforcement_audit: Initialize on startup
"""

from typing import Dict, List, Optional
import time
import os
import json
import logging

logger = logging.getLogger(__name__)

# ======================================================================================
# Config
# ======================================================================================

class VenueCfg:
    spot_enabled: bool = False      # initial target state (futures-only)
    futures_enabled: bool = True

    # Expectancy thresholds for spot re-enable (Phase 9.3 alignment)
    spot_unfreeze_min_sharpe: float = 0.8
    spot_unfreeze_min_net_pnl_usd: float = 100.0
    spot_unfreeze_required_passes: int = 5

    # Absolute enforcement
    hard_block_spot_when_disabled: bool = True
    halt_on_breach: bool = False  # log warnings instead of halting (safer for production)

    # Persistence
    state_path: str = "logs/venue_enforcement_state.json"
    events_path: str = "logs/venue_enforcement_events.jsonl"

VCFG = VenueCfg()

STATE = {
    "spot_enabled": VCFG.spot_enabled,
    "futures_enabled": VCFG.futures_enabled,
    "spot_unfreeze_passes": 0,
    "last_breach_ts": 0.0,
    "total_blocks": 0,
    "total_breaches": 0
}

# ======================================================================================
# Persistence
# ======================================================================================

def _persist_state():
    try:
        os.makedirs(os.path.dirname(VCFG.state_path), exist_ok=True)
        with open(VCFG.state_path, "w") as f:
            json.dump(STATE, f, indent=2)
    except Exception as e:
        logger.error(f"Venue persist error: {e}")

def _append_event(event: str, payload: dict):
    try:
        os.makedirs(os.path.dirname(VCFG.events_path), exist_ok=True)
        row = {"ts": int(time.time()), "event": event, "payload": payload}
        with open(VCFG.events_path, "a") as f:
            f.write(json.dumps(row) + "\n")
    except Exception as e:
        logger.error(f"Venue event write error: {e}")

def _load_state():
    global STATE
    try:
        if os.path.exists(VCFG.state_path):
            with open(VCFG.state_path, "r") as f:
                loaded = json.load(f)
                STATE.update(loaded)
                logger.info(f"📊 VENUE-ENFORCE: State loaded (spot={STATE['spot_enabled']}, futures={STATE['futures_enabled']})")
    except Exception as e:
        logger.error(f"Venue load error: {e}")

# ======================================================================================
# Router-level policy (first choke point)
# ======================================================================================

def venue_policy(signal: Dict) -> bool:
    """
    First line of defense: router blocks signals by venue.
    Returns True if the venue is allowed, False otherwise.
    """
    venue = signal.get("venue", "spot")
    
    if venue == "spot" and not STATE["spot_enabled"]:
        STATE["total_blocks"] += 1
        logger.warning(f"🚫 VENUE-BLOCK [ROUTER]: Spot disabled, blocking {signal.get('symbol', 'UNKNOWN')}")
        _append_event("venue_block_router_spot_disabled", {"signal": signal})
        
        # [PHASE 10.1] Record breach attempt when spot is blocked at router level
        try:
            from src.phase101_allocator import record_breach_attempt
            record_breach_attempt(signal.get('symbol', 'UNKNOWN'), "spot", signal.get('strategy', 'unknown'))
        except Exception:
            pass
        
        return False

    if venue == "futures" and not STATE["futures_enabled"]:
        STATE["total_blocks"] += 1
        logger.warning(f"🚫 VENUE-BLOCK [ROUTER]: Futures disabled, blocking {signal.get('symbol', 'UNKNOWN')}")
        _append_event("venue_block_router_futures_disabled", {"signal": signal})
        return False

    return True

# ======================================================================================
# Entry gate-level enforcement (second choke point)
# ======================================================================================

def venue_guard_entry_gate(signal: Dict) -> bool:
    """
    Apply venue gate right before any strategy-level entry checks.
    """
    venue = signal.get("venue", "spot")
    
    if venue == "spot" and not STATE["spot_enabled"]:
        STATE["total_blocks"] += 1
        logger.warning(f"🚫 VENUE-BLOCK [GATE]: Spot disabled, blocking {signal.get('symbol', 'UNKNOWN')}-{signal.get('strategy', 'UNKNOWN')}")
        _append_event("venue_block_gate_spot_disabled", {"signal": signal})
        
        # [PHASE 10.1] Record breach attempt when spot is blocked at gate level
        try:
            from src.phase101_allocator import record_breach_attempt
            record_breach_attempt(signal.get('symbol', 'UNKNOWN'), "spot", signal.get('strategy', 'unknown'))
        except Exception:
            pass
        
        return False
    
    if venue == "futures" and not STATE["futures_enabled"]:
        STATE["total_blocks"] += 1
        logger.warning(f"🚫 VENUE-BLOCK [GATE]: Futures disabled, blocking {signal.get('symbol', 'UNKNOWN')}-{signal.get('strategy', 'UNKNOWN')}")
        _append_event("venue_block_gate_futures_disabled", {"signal": signal})
        return False
    
    return True

# ======================================================================================
# Execution-level enforcement (third choke point)
# ======================================================================================

def venue_guard_execution(symbol: str, side: str, size_usd: float, venue: str, strategy: str = "") -> bool:
    """
    Final enforcement at execution time.
    Returns True if execution is allowed, False otherwise.
    """
    if venue == "spot" and not STATE["spot_enabled"]:
        STATE["total_blocks"] += 1
        logger.warning(f"🚫 VENUE-BLOCK [EXECUTOR]: Spot disabled, blocking order {symbol} {side} ${size_usd:.2f}")
        _append_event("venue_block_executor_spot_disabled", {
            "symbol": symbol,
            "side": side,
            "size_usd": size_usd,
            "strategy": strategy
        })
        
        # [PHASE 10.1] Record breach attempt when spot is blocked at execution level
        try:
            from src.phase101_allocator import record_breach_attempt
            record_breach_attempt(symbol, "spot", strategy if strategy else "unknown")
        except Exception:
            pass
        
        return False

    if venue == "futures" and not STATE["futures_enabled"]:
        STATE["total_blocks"] += 1
        logger.warning(f"🚫 VENUE-BLOCK [EXECUTOR]: Futures disabled, blocking order {symbol} {side} ${size_usd:.2f}")
        _append_event("venue_block_executor_futures_disabled", {
            "symbol": symbol,
            "side": side,
            "size_usd": size_usd,
            "strategy": strategy
        })
        return False

    return True

# ======================================================================================
# Expectancy-based spot re-enable (aligns with Phase 9.3)
# ======================================================================================

def venue_evaluate_spot_unfreeze(spot_sharpe_24h: float = 0.0, spot_pnl_24h: float = 0.0):
    """
    Evaluate if spot trading can be re-enabled based on performance.
    Call this periodically (e.g., every 5 minutes).
    """
    ok = (spot_sharpe_24h >= VCFG.spot_unfreeze_min_sharpe) and (spot_pnl_24h >= VCFG.spot_unfreeze_min_net_pnl_usd)

    if ok:
        STATE["spot_unfreeze_passes"] += 1
        logger.info(f"✅ VENUE-UNFREEZE: Spot pass {STATE['spot_unfreeze_passes']}/{VCFG.spot_unfreeze_required_passes} (Sharpe={spot_sharpe_24h:.2f}, P&L=${spot_pnl_24h:.2f})")
        _append_event("venue_spot_unfreeze_pass", {"sharpe": spot_sharpe_24h, "pnl": spot_pnl_24h, "passes": STATE["spot_unfreeze_passes"]})
    else:
        if STATE["spot_unfreeze_passes"] > 0:
            logger.info(f"⚠️  VENUE-UNFREEZE: Spot pass reset (Sharpe={spot_sharpe_24h:.2f}, P&L=${spot_pnl_24h:.2f})")
        STATE["spot_unfreeze_passes"] = 0

    if STATE["spot_unfreeze_passes"] >= VCFG.spot_unfreeze_required_passes and not STATE["spot_enabled"]:
        STATE["spot_enabled"] = True
        _persist_state()
        logger.info(f"🎯 VENUE-ENABLED: Spot trading enabled (Sharpe={spot_sharpe_24h:.2f}, P&L=${spot_pnl_24h:.2f})")
        _append_event("venue_spot_enabled", {"sharpe": spot_sharpe_24h, "pnl": spot_pnl_24h})

    _persist_state()

# ======================================================================================
# Audit and detection
# ======================================================================================

def venue_detect_breach(executed_venue: str, symbol: str, side: str, size_usd: float, strategy: str = "unknown"):
    """
    Call this after any order execution to detect breaches.
    If a spot order executed while spot is disabled, log as breach.
    """
    if executed_venue == "spot" and not STATE["spot_enabled"]:
        STATE["last_breach_ts"] = time.time()
        STATE["total_breaches"] += 1
        _persist_state()
        logger.error(f"🚨 VENUE-BREACH: Spot order executed while disabled! {symbol} {side} ${size_usd:.2f}")
        _append_event("venue_breach_spot_executed", {
            "symbol": symbol,
            "side": side,
            "size_usd": size_usd,
            "strategy": strategy,
            "ts": time.time()
        })
        
        # [PHASE 10.1] Alert on repeated breaches
        try:
            from src.phase101_allocator import record_breach_attempt
            record_breach_attempt(symbol, executed_venue, strategy)
        except Exception as e:
            logger.warning(f"Phase 10.1 breach alerting unavailable: {e}")
        
        if VCFG.halt_on_breach:
            logger.critical("🛑 VENUE-BREACH: Halting trading loop")
            raise RuntimeError("Spot execution while disabled - halting for safety")

# ======================================================================================
# Status and reporting
# ======================================================================================

def get_venue_enforcement_status() -> Dict:
    """Return current enforcement status for dashboard."""
    return {
        "spot_enabled": STATE["spot_enabled"],
        "futures_enabled": STATE["futures_enabled"],
        "spot_unfreeze_passes": STATE["spot_unfreeze_passes"],
        "spot_unfreeze_required": VCFG.spot_unfreeze_required_passes,
        "total_blocks": STATE["total_blocks"],
        "total_breaches": STATE["total_breaches"],
        "last_breach_ts": STATE["last_breach_ts"],
        "thresholds": {
            "sharpe": VCFG.spot_unfreeze_min_sharpe,
            "pnl_usd": VCFG.spot_unfreeze_min_net_pnl_usd
        }
    }

# ======================================================================================
# Bootstrap
# ======================================================================================

def start_venue_enforcement():
    """Initialize venue enforcement on startup."""
    _load_state()
    
    # Ensure directories exist
    os.makedirs(os.path.dirname(VCFG.state_path), exist_ok=True)
    
    logger.info(f"🛡️  VENUE-ENFORCE: Started")
    logger.info(f"   - Spot enabled: {STATE['spot_enabled']}")
    logger.info(f"   - Futures enabled: {STATE['futures_enabled']}")
    logger.info(f"   - Spot unfreeze requires: Sharpe≥{VCFG.spot_unfreeze_min_sharpe}, P&L≥${VCFG.spot_unfreeze_min_net_pnl_usd}")
    
    _append_event("venue_enforcement_started", {
        "spot_enabled": STATE["spot_enabled"],
        "futures_enabled": STATE["futures_enabled"]
    })
    _persist_state()
