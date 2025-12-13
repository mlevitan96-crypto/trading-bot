"""
Counter-Signal Orchestrator

PHILOSOPHY: If we can predict ANYTHING about our signals (even that they're wrong),
we should EXPLOIT that for profit. This is the "opportunistic" architecture.

When Alpha signals are predictably losing, we don't just AVOID trades - we INVERT them
to profit from the predictability.

Key Components:
1. Loss Pattern Detector - detects when Alpha is consistently wrong
2. Inversion Controller - manages state transitions between Alpha and Beta modes  
3. Entry Wrapper - applies inversion to signals before execution
4. Meta-Learning - tracks inversion performance and auto-adjusts
"""

import json
import os
from datetime import datetime, timedelta
from typing import Dict, Tuple, Optional, Any
from collections import deque

try:
    from src.data_registry import DataRegistry as DR
except ImportError:
    DR = None

ORCHESTRATOR_STATE_FILE = "state/counter_signal_state.json"
INVERSION_LOG = "logs/inversion_events.jsonl"
LEARNING_FILE = "feature_store/inversion_learning.json"

INVERSION_CONFIG = {
    "min_signals_for_detection": 10,
    "loss_rate_threshold": 0.70,
    "consecutive_losses_trigger": 5,
    "inversion_cooldown_minutes": 30,
    "min_inversion_duration_minutes": 15,
    "max_inversion_duration_hours": 4,
    "auto_revert_on_wins": 3,
    "confidence_threshold": 0.65
}


def _now() -> datetime:
    return datetime.utcnow()


def _default_state() -> Dict:
    """Return default orchestrator state."""
    return {
        "mode": "alpha",
        "inversion_active": False,
        "inversion_started": None,
        "inversion_reason": None,
        "recent_signals": [],
        "inversion_history": [],
        "alpha_consecutive_losses": 0,
        "beta_wins_since_inversion": 0,
        "last_decision_time": None,
        "stats": {
            "total_inversions": 0,
            "successful_inversions": 0,
            "inversion_pnl": 0
        }
    }


def _load_state() -> Dict:
    """Load orchestrator state with atomic read."""
    if os.path.exists(ORCHESTRATOR_STATE_FILE):
        try:
            with open(ORCHESTRATOR_STATE_FILE, 'r') as f:
                data = json.load(f)
                defaults = _default_state()
                for key, val in defaults.items():
                    if key not in data:
                        data[key] = val
                return data
        except:
            pass
    
    return _default_state()


def _save_state(state: Dict):
    """Save orchestrator state with atomic write."""
    os.makedirs(os.path.dirname(ORCHESTRATOR_STATE_FILE), exist_ok=True)
    state["last_updated"] = _now().isoformat()
    
    tmp_file = ORCHESTRATOR_STATE_FILE + ".tmp"
    try:
        with open(tmp_file, 'w') as f:
            json.dump(state, f, indent=2, default=str)
        os.replace(tmp_file, ORCHESTRATOR_STATE_FILE)
    except Exception as e:
        if os.path.exists(tmp_file):
            os.remove(tmp_file)
        raise e


def _log_event(event_type: str, details: Dict):
    """Log inversion events."""
    os.makedirs(os.path.dirname(INVERSION_LOG), exist_ok=True)
    event = {
        "ts": _now().isoformat(),
        "event": event_type,
        **details
    }
    with open(INVERSION_LOG, 'a') as f:
        f.write(json.dumps(event) + "\n")
    print(f"[COUNTER-SIGNAL] {event_type}: {details}")


def record_signal_outcome(symbol: str, direction: str, pnl: float, 
                          was_inverted: bool = False) -> Dict:
    """
    Record the outcome of a signal for pattern detection.
    Call this after every trade closes.
    """
    state = _load_state()
    
    outcome = {
        "ts": _now().isoformat(),
        "symbol": symbol,
        "direction": direction,
        "pnl": pnl,
        "win": pnl > 0,
        "was_inverted": was_inverted,
        "mode": state["mode"]
    }
    
    state["recent_signals"].append(outcome)
    state["recent_signals"] = state["recent_signals"][-50:]
    
    if not was_inverted:
        if pnl <= 0:
            state["alpha_consecutive_losses"] += 1
        else:
            state["alpha_consecutive_losses"] = 0
    else:
        if pnl > 0:
            state["beta_wins_since_inversion"] += 1
    
    _save_state(state)
    return outcome


def detect_loss_pattern() -> Tuple[bool, float, str]:
    """
    Detect if Alpha is in a predictable losing pattern.
    
    Returns:
        (should_invert, confidence, reason)
    """
    state = _load_state()
    signals = state.get("recent_signals", [])
    
    if len(signals) < INVERSION_CONFIG["min_signals_for_detection"]:
        return False, 0.0, "insufficient_data"
    
    recent = signals[-20:]
    alpha_signals = [s for s in recent if not s.get("was_inverted", False)]
    
    if len(alpha_signals) < 5:
        return False, 0.0, "insufficient_alpha_signals"
    
    losses = sum(1 for s in alpha_signals if not s["win"])
    loss_rate = losses / len(alpha_signals)
    
    consecutive = state.get("alpha_consecutive_losses", 0)
    
    confidence = 0.0
    reasons = []
    
    if loss_rate >= INVERSION_CONFIG["loss_rate_threshold"]:
        confidence += 0.4
        reasons.append(f"loss_rate_{loss_rate:.0%}")
    
    if consecutive >= INVERSION_CONFIG["consecutive_losses_trigger"]:
        confidence += 0.3
        reasons.append(f"consecutive_{consecutive}")
    
    long_signals = [s for s in alpha_signals if s["direction"] == "LONG"]
    short_signals = [s for s in alpha_signals if s["direction"] == "SHORT"]
    
    if len(long_signals) >= 5:
        long_loss_rate = sum(1 for s in long_signals if not s["win"]) / len(long_signals)
        if long_loss_rate >= 0.80:
            confidence += 0.2
            reasons.append(f"long_bias_failing_{long_loss_rate:.0%}")
    
    if len(short_signals) >= 5:
        short_loss_rate = sum(1 for s in short_signals if not s["win"]) / len(short_signals)
        if short_loss_rate >= 0.80:
            confidence += 0.2
            reasons.append(f"short_bias_failing_{short_loss_rate:.0%}")
    
    total_pnl = sum(s["pnl"] for s in alpha_signals)
    if total_pnl < -20:
        confidence += 0.1
        reasons.append(f"negative_pnl_{total_pnl:.2f}")
    
    should_invert = confidence >= INVERSION_CONFIG["confidence_threshold"]
    reason = "|".join(reasons) if reasons else "no_pattern"
    
    return should_invert, min(confidence, 1.0), reason


def should_revert_to_alpha() -> Tuple[bool, str]:
    """
    Check if we should revert from Beta back to Alpha mode.
    """
    state = _load_state()
    
    if not state.get("inversion_active"):
        return False, "not_inverted"
    
    inversion_start = state.get("inversion_started")
    if inversion_start:
        try:
            start_time = datetime.fromisoformat(inversion_start)
            duration_hours = (_now() - start_time).total_seconds() / 3600
            
            if duration_hours >= INVERSION_CONFIG["max_inversion_duration_hours"]:
                return True, "max_duration_reached"
        except:
            pass
    
    if state.get("beta_wins_since_inversion", 0) >= INVERSION_CONFIG["auto_revert_on_wins"]:
        return True, "beta_winning_revert"
    
    signals = state.get("recent_signals", [])
    inverted_signals = [s for s in signals[-10:] if s.get("was_inverted")]
    
    if len(inverted_signals) >= 5:
        beta_loss_rate = sum(1 for s in inverted_signals if not s["win"]) / len(inverted_signals)
        if beta_loss_rate >= 0.70:
            return True, "beta_also_failing"
    
    return False, "continue_inversion"


def get_signal_decision(symbol: str, original_direction: str, 
                        signal_strength: float = 1.0) -> Dict:
    """
    Main entry point: Get the final signal decision.
    
    This is the "opportunistic" wrapper that:
    1. Checks if we should invert based on pattern detection
    2. Returns the optimal direction (original or inverted)
    3. Tracks the decision for learning
    
    Args:
        symbol: Trading pair
        original_direction: The direction Alpha would trade (LONG/SHORT)
        signal_strength: Confidence in the original signal (0-1)
    
    Returns:
        Dict with:
        - direction: Final direction to trade (may be inverted)
        - inverted: Whether the signal was inverted
        - mode: Current mode (alpha/beta)
        - confidence: Confidence in the decision
        - reason: Why this decision was made
    """
    state = _load_state()
    
    if not state.get("inversion_active"):
        should_invert, confidence, reason = detect_loss_pattern()
        
        if should_invert:
            _activate_inversion(state, confidence, reason)
    else:
        should_revert, revert_reason = should_revert_to_alpha()
        
        if should_revert:
            _deactivate_inversion(state, revert_reason)
    
    state = _load_state()
    
    if state.get("inversion_active"):
        inverted_direction = "SHORT" if original_direction == "LONG" else "LONG"
        
        decision = {
            "symbol": symbol,
            "original_direction": original_direction,
            "direction": inverted_direction,
            "inverted": True,
            "mode": "beta",
            "confidence": state.get("inversion_confidence", 0.7),
            "reason": f"inversion_active|{state.get('inversion_reason', 'unknown')}",
            "signal_strength": signal_strength
        }
    else:
        decision = {
            "symbol": symbol,
            "original_direction": original_direction,
            "direction": original_direction,
            "inverted": False,
            "mode": "alpha",
            "confidence": signal_strength,
            "reason": "alpha_mode",
            "signal_strength": signal_strength
        }
    
    decision["timestamp"] = _now().isoformat()
    
    return decision


def _activate_inversion(state: Dict, confidence: float, reason: str):
    """Activate inversion mode (switch from Alpha to Beta)."""
    state["inversion_active"] = True
    state["mode"] = "beta"
    state["inversion_started"] = _now().isoformat()
    state["inversion_reason"] = reason
    state["inversion_confidence"] = confidence
    state["beta_wins_since_inversion"] = 0
    state["stats"]["total_inversions"] += 1
    
    state["inversion_history"].append({
        "started": state["inversion_started"],
        "reason": reason,
        "confidence": confidence
    })
    state["inversion_history"] = state["inversion_history"][-20:]
    
    _save_state(state)
    _log_event("INVERSION_ACTIVATED", {
        "reason": reason,
        "confidence": confidence,
        "alpha_consecutive_losses": state.get("alpha_consecutive_losses", 0)
    })


def _deactivate_inversion(state: Dict, reason: str):
    """Deactivate inversion mode (switch from Beta back to Alpha)."""
    inversion_start = state.get("inversion_started")
    duration_minutes = 0
    
    if inversion_start:
        try:
            start_time = datetime.fromisoformat(inversion_start)
            duration_minutes = (_now() - start_time).total_seconds() / 60
        except:
            pass
    
    if state["inversion_history"]:
        state["inversion_history"][-1]["ended"] = _now().isoformat()
        state["inversion_history"][-1]["duration_minutes"] = duration_minutes
        state["inversion_history"][-1]["revert_reason"] = reason
        state["inversion_history"][-1]["beta_wins"] = state.get("beta_wins_since_inversion", 0)
    
    state["inversion_active"] = False
    state["mode"] = "alpha"
    state["inversion_started"] = None
    state["inversion_reason"] = None
    state["alpha_consecutive_losses"] = 0
    
    _save_state(state)
    _log_event("INVERSION_DEACTIVATED", {
        "reason": reason,
        "duration_minutes": duration_minutes,
        "beta_wins": state.get("beta_wins_since_inversion", 0)
    })


def get_orchestrator_status() -> Dict:
    """Get current orchestrator status for dashboard/monitoring."""
    state = _load_state()
    signals = state.get("recent_signals", [])
    
    alpha_signals = [s for s in signals[-20:] if not s.get("was_inverted")]
    
    if alpha_signals:
        alpha_win_rate = sum(1 for s in alpha_signals if s["win"]) / len(alpha_signals)
        alpha_pnl = sum(s["pnl"] for s in alpha_signals)
    else:
        alpha_win_rate = 0
        alpha_pnl = 0
    
    should_invert, confidence, pattern_reason = detect_loss_pattern()
    
    return {
        "mode": state.get("mode", "alpha"),
        "inversion_active": state.get("inversion_active", False),
        "inversion_started": state.get("inversion_started"),
        "inversion_reason": state.get("inversion_reason"),
        "alpha_consecutive_losses": state.get("alpha_consecutive_losses", 0),
        "beta_wins_since_inversion": state.get("beta_wins_since_inversion", 0),
        "recent_alpha_win_rate": round(alpha_win_rate, 3),
        "recent_alpha_pnl": round(alpha_pnl, 2),
        "pattern_detected": should_invert,
        "pattern_confidence": round(confidence, 3),
        "pattern_reason": pattern_reason,
        "total_inversions": state.get("stats", {}).get("total_inversions", 0),
        "last_updated": state.get("last_updated")
    }


def force_inversion(reason: str = "manual_override") -> Dict:
    """Manually force inversion mode (for testing or operator override)."""
    state = _load_state()
    _activate_inversion(state, confidence=1.0, reason=reason)
    return get_orchestrator_status()


def force_alpha(reason: str = "manual_override") -> Dict:
    """Manually force Alpha mode (for testing or operator override)."""
    state = _load_state()
    _deactivate_inversion(state, reason=reason)
    return get_orchestrator_status()


def is_inversion_active() -> bool:
    """Quick check if inversion mode is currently active."""
    state = _load_state()
    return state.get("inversion_active", False)


def run_inversion_analysis() -> Dict:
    """
    Analyze historical inversions and their effectiveness.
    For nightly learning.
    """
    state = _load_state()
    history = state.get("inversion_history", [])
    
    if not history:
        return {"status": "no_history", "inversions": 0}
    
    completed = [h for h in history if h.get("ended")]
    
    if not completed:
        return {"status": "no_completed_inversions", "inversions": len(history)}
    
    total_duration = sum(h.get("duration_minutes", 0) for h in completed)
    total_beta_wins = sum(h.get("beta_wins", 0) for h in completed)
    
    successful = [h for h in completed if h.get("beta_wins", 0) >= 1]
    
    analysis = {
        "status": "analyzed",
        "total_inversions": len(completed),
        "successful_inversions": len(successful),
        "success_rate": len(successful) / len(completed) if completed else 0,
        "total_duration_minutes": total_duration,
        "avg_duration_minutes": total_duration / len(completed) if completed else 0,
        "total_beta_wins": total_beta_wins,
        "avg_beta_wins_per_inversion": total_beta_wins / len(completed) if completed else 0
    }
    
    os.makedirs(os.path.dirname(LEARNING_FILE), exist_ok=True)
    learning_data = {
        "analysis_time": _now().isoformat(),
        "analysis": analysis,
        "history": completed[-10:]
    }
    with open(LEARNING_FILE, 'w') as f:
        json.dump(learning_data, f, indent=2)
    
    return analysis


if __name__ == "__main__":
    print("=== Counter-Signal Orchestrator Status ===")
    status = get_orchestrator_status()
    for k, v in status.items():
        print(f"  {k}: {v}")
    
    print("\n=== Pattern Detection ===")
    should_invert, confidence, reason = detect_loss_pattern()
    print(f"  Should invert: {should_invert}")
    print(f"  Confidence: {confidence:.2f}")
    print(f"  Reason: {reason}")
