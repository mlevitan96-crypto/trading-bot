"""
Catastrophic Loss Guard - Emergency exit for extreme losses.

This module provides a last-line-of-defense protection against catastrophic losses.
If any position reaches a configurable loss threshold (default: -15%), it triggers
an immediate market close regardless of other exit conditions.

This is separate from normal stop-losses and trailing stops - it's an EMERGENCY brake
for when markets move violently against a position.

Typical 30-minute crypto swings:
- Normal: 1-3% price move
- Volatile: 5-10% price move  
- Extreme (flash crash, major news): 15-30%+ possible

With leverage, these multiply. A 5% price move at 5x leverage = 25% position loss.
"""

import json
import os
import time
from datetime import datetime
from typing import Dict, List, Any, Optional, Tuple

CATASTROPHIC_LOSS_THRESHOLD_PCT = -20.0  # Exit if loss exceeds 20%
EXTREME_LOSS_THRESHOLD_PCT = -30.0  # Log as extreme if exceeds 30%
POSITIONS_PATH = "logs/positions_futures.json"
GUARD_LOG_PATH = "logs/catastrophic_guard.jsonl"
GUARD_STATE_PATH = "feature_store/catastrophic_guard_state.json"


def _now() -> str:
    return datetime.utcnow().isoformat() + "Z"


def _read_json(path: str, default: Any = None) -> Any:
    try:
        if os.path.exists(path):
            with open(path, 'r') as f:
                return json.load(f)
    except Exception:
        pass
    return default if default is not None else {}


def _write_json(path: str, data: Any) -> bool:
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'w') as f:
            json.dump(data, f, indent=2)
        return True
    except Exception as e:
        print(f"[CATASTROPHIC-GUARD] Failed to write {path}: {e}")
        return False


def _append_log(entry: Dict) -> None:
    try:
        os.makedirs(os.path.dirname(GUARD_LOG_PATH), exist_ok=True)
        entry["timestamp"] = _now()
        with open(GUARD_LOG_PATH, 'a') as f:
            f.write(json.dumps(entry) + "\n")
    except Exception:
        pass


def calculate_position_pnl_pct(position: Dict, current_price: float) -> float:
    """
    Calculate position P&L as a percentage.
    
    Returns: P&L percentage (e.g., -15.5 for a 15.5% loss)
    """
    entry_price = float(position.get("entry_price", 0) or position.get("avg_price", 0) or 0)
    side = position.get("side", "").upper() or position.get("direction", "").upper()
    
    if entry_price <= 0 or current_price <= 0:
        return 0.0
    
    if side in ["LONG", "BUY"]:
        raw_pnl_pct = ((current_price - entry_price) / entry_price) * 100
    elif side in ["SHORT", "SELL"]:
        raw_pnl_pct = ((entry_price - current_price) / entry_price) * 100
    else:
        return 0.0
    
    leverage = float(position.get("leverage", 1) or 1)
    leveraged_pnl_pct = raw_pnl_pct * leverage
    
    return round(leveraged_pnl_pct, 2)


def check_catastrophic_loss(position: Dict, current_price: float, 
                            threshold_pct: float = None) -> Tuple[bool, float, str]:
    """
    Check if a position has hit catastrophic loss level.
    
    Args:
        position: Position dictionary with entry_price, side, leverage
        current_price: Current market price
        threshold_pct: Loss threshold (default: CATASTROPHIC_LOSS_THRESHOLD_PCT)
    
    Returns:
        (should_exit, pnl_pct, reason)
    """
    if threshold_pct is None:
        threshold_pct = CATASTROPHIC_LOSS_THRESHOLD_PCT
    
    pnl_pct = calculate_position_pnl_pct(position, current_price)
    
    if pnl_pct <= threshold_pct:
        symbol = position.get("symbol", "UNKNOWN")
        side = position.get("side", "") or position.get("direction", "")
        leverage = position.get("leverage", 1)
        
        severity = "EXTREME" if pnl_pct <= EXTREME_LOSS_THRESHOLD_PCT else "CATASTROPHIC"
        reason = f"{severity}_LOSS: {pnl_pct:.1f}% (threshold: {threshold_pct}%)"
        
        _append_log({
            "event": "catastrophic_trigger",
            "symbol": symbol,
            "side": side,
            "leverage": leverage,
            "pnl_pct": pnl_pct,
            "threshold": threshold_pct,
            "current_price": current_price,
            "entry_price": position.get("entry_price"),
            "severity": severity,
        })
        
        print(f"🚨 [{severity}] {symbol} {side}: {pnl_pct:.1f}% loss - EMERGENCY EXIT TRIGGERED")
        
        return True, pnl_pct, reason
    
    return False, pnl_pct, ""


def scan_all_positions_for_catastrophic_loss(
    current_prices: Dict[str, float],
    threshold_pct: float = None
) -> List[Dict]:
    """
    Scan all open positions for catastrophic losses.
    
    Args:
        current_prices: Dict mapping symbol -> current price
        threshold_pct: Loss threshold (default: CATASTROPHIC_LOSS_THRESHOLD_PCT)
    
    Returns:
        List of positions that should be emergency closed
    """
    if threshold_pct is None:
        threshold_pct = CATASTROPHIC_LOSS_THRESHOLD_PCT
    
    positions = _read_json(POSITIONS_PATH, {})
    open_positions = positions.get("open", [])
    
    emergency_exits = []
    
    for pos in open_positions:
        symbol = pos.get("symbol", "")
        current_price = current_prices.get(symbol, 0)
        
        if current_price <= 0:
            continue
        
        should_exit, pnl_pct, reason = check_catastrophic_loss(pos, current_price, threshold_pct)
        
        if should_exit:
            emergency_exits.append({
                "position": pos,
                "pnl_pct": pnl_pct,
                "reason": reason,
                "current_price": current_price,
            })
    
    return emergency_exits


def execute_catastrophic_exits(
    current_prices: Dict[str, float],
    close_position_fn,
    threshold_pct: float = None
) -> Dict[str, Any]:
    """
    Check all positions and execute emergency exits for catastrophic losses.
    
    Args:
        current_prices: Dict mapping symbol -> current price
        close_position_fn: Function to close a position (symbol, side, reason) -> bool
        threshold_pct: Loss threshold (default: CATASTROPHIC_LOSS_THRESHOLD_PCT)
    
    Returns:
        Summary of actions taken
    """
    if threshold_pct is None:
        threshold_pct = CATASTROPHIC_LOSS_THRESHOLD_PCT
    
    result = {
        "timestamp": _now(),
        "threshold_pct": threshold_pct,
        "positions_checked": 0,
        "emergency_exits": 0,
        "exits": [],
    }
    
    emergency_list = scan_all_positions_for_catastrophic_loss(current_prices, threshold_pct)
    
    positions = _read_json(POSITIONS_PATH, {})
    result["positions_checked"] = len(positions.get("open", []))
    
    for emergency in emergency_list:
        pos = emergency["position"]
        symbol = pos.get("symbol", "")
        side = pos.get("side", "") or pos.get("direction", "")
        
        try:
            success = close_position_fn(symbol, side, emergency["reason"])
            
            exit_record = {
                "symbol": symbol,
                "side": side,
                "pnl_pct": emergency["pnl_pct"],
                "reason": emergency["reason"],
                "success": success,
            }
            result["exits"].append(exit_record)
            
            if success:
                result["emergency_exits"] += 1
                print(f"🚨 [CATASTROPHIC-GUARD] Closed {symbol} {side} at {emergency['pnl_pct']:.1f}% loss")
            else:
                print(f"⚠️ [CATASTROPHIC-GUARD] Failed to close {symbol} {side}")
                
        except Exception as e:
            print(f"⚠️ [CATASTROPHIC-GUARD] Error closing {symbol}: {e}")
            result["exits"].append({
                "symbol": symbol,
                "side": side,
                "pnl_pct": emergency["pnl_pct"],
                "error": str(e),
                "success": False,
            })
    
    state = _read_json(GUARD_STATE_PATH, {})
    state["last_check"] = _now()
    state["total_checks"] = state.get("total_checks", 0) + 1
    state["total_emergency_exits"] = state.get("total_emergency_exits", 0) + result["emergency_exits"]
    _write_json(GUARD_STATE_PATH, state)
    
    if result["emergency_exits"] > 0:
        _append_log({
            "event": "emergency_exits_executed",
            "count": result["emergency_exits"],
            "exits": result["exits"],
        })
    
    return result


def get_guard_status() -> Dict[str, Any]:
    """Get the current guard status for monitoring."""
    state = _read_json(GUARD_STATE_PATH, {})
    
    return {
        "active": True,
        "threshold_pct": CATASTROPHIC_LOSS_THRESHOLD_PCT,
        "extreme_threshold_pct": EXTREME_LOSS_THRESHOLD_PCT,
        "last_check": state.get("last_check", "never"),
        "total_checks": state.get("total_checks", 0),
        "total_emergency_exits": state.get("total_emergency_exits", 0),
    }


def set_threshold(new_threshold_pct: float) -> None:
    """
    Update the catastrophic loss threshold.
    
    Args:
        new_threshold_pct: New threshold (e.g., -20.0 for 20% loss)
    """
    global CATASTROPHIC_LOSS_THRESHOLD_PCT
    
    if new_threshold_pct > 0:
        new_threshold_pct = -new_threshold_pct
    
    if new_threshold_pct > -5:
        print(f"⚠️ [CATASTROPHIC-GUARD] Threshold {new_threshold_pct}% is too tight, minimum is -5%")
        new_threshold_pct = -5.0
    
    old_threshold = CATASTROPHIC_LOSS_THRESHOLD_PCT
    CATASTROPHIC_LOSS_THRESHOLD_PCT = new_threshold_pct
    
    _append_log({
        "event": "threshold_changed",
        "old": old_threshold,
        "new": new_threshold_pct,
    })
    
    print(f"🛡️ [CATASTROPHIC-GUARD] Threshold updated: {old_threshold}% → {new_threshold_pct}%")


if __name__ == "__main__":
    print("=" * 60)
    print("🚨 CATASTROPHIC LOSS GUARD - Status Check")
    print("=" * 60)
    
    status = get_guard_status()
    print(f"   Active: {status['active']}")
    print(f"   Threshold: {status['threshold_pct']}%")
    print(f"   Extreme threshold: {status['extreme_threshold_pct']}%")
    print(f"   Last check: {status['last_check']}")
    print(f"   Total checks: {status['total_checks']}")
    print(f"   Total emergency exits: {status['total_emergency_exits']}")
