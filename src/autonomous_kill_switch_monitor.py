"""
Autonomous Kill Switch Monitor & Recovery

Monitors Phase 82 kill switch status and automatically recovers when conditions normalize.
Part of the self-healing governance layer.
"""

import os
import json
import time
from typing import Dict, Optional, Any

STATE_FILE = "logs/phase82_state.json"
RECOVERY_LOG = "logs/kill_switch_recovery.jsonl"

def _append_event(path: str, event: dict):
    """Append event to log file."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    event["ts"] = int(time.time())
    with open(path, "a") as f:
        f.write(json.dumps(event) + "\n")

def get_kill_switch_status() -> Dict[str, Any]:
    """Check if kill switch is active and why."""
    if not os.path.exists(STATE_FILE):
        return {
            "active": False,
            "reason": "no_state_file",
            "frozen": False
        }
    
    try:
        with open(STATE_FILE, "r") as f:
            state = json.load(f)
        
        frozen = state.get("global_freeze_active", False)
        last_trigger = state.get("last_kill_switch_trigger_ts", 0)
        
        return {
            "active": frozen,
            "frozen": frozen,
            "last_trigger_ts": last_trigger,
            "time_since_trigger": int(time.time()) - last_trigger if last_trigger else 0
        }
    except Exception as e:
        return {
            "active": False,
            "reason": "state_read_error",
            "error": str(e)
        }

def check_recovery_conditions() -> Dict[str, Any]:
    """Check if kill switch should be automatically reset."""
    try:
        from src.phase82_go_live import (
            rolling_drawdown_pct_24h,
            order_reject_rate_15m,
            fee_mismatch_usd_1h,
            Phase82Config
        )
        
        cfg = Phase82Config()
        
        dd = rolling_drawdown_pct_24h() or 0.0
        rejects = order_reject_rate_15m() or 0.0
        fee_mismatch = fee_mismatch_usd_1h() or 0.0
        
        dd_safe = dd < cfg.kill_pnl_drawdown_pct
        rejects_safe = rejects < cfg.kill_order_reject_rate_15m
        fees_safe = fee_mismatch < cfg.kill_fee_recon_mismatch_usd
        
        all_safe = dd_safe and rejects_safe and fees_safe
        
        return {
            "can_recover": all_safe,
            "drawdown_pct": dd,
            "drawdown_safe": dd_safe,
            "drawdown_threshold": cfg.kill_pnl_drawdown_pct,
            "rejects_pct": rejects * 100,
            "rejects_safe": rejects_safe,
            "rejects_threshold": cfg.kill_order_reject_rate_15m * 100,
            "fee_mismatch": fee_mismatch,
            "fees_safe": fees_safe,
            "fee_threshold": cfg.kill_fee_recon_mismatch_usd
        }
    except Exception as e:
        return {
            "can_recover": False,
            "error": str(e)
        }

def attempt_auto_recovery() -> Dict[str, Any]:
    """Attempt to automatically reset kill switch if conditions are safe."""
    status = get_kill_switch_status()
    
    if not status["active"]:
        return {
            "action": "none",
            "reason": "kill_switch_not_active"
        }
    
    time_since_trigger = status.get("time_since_trigger", 0)
    
    if time_since_trigger < 300:
        return {
            "action": "waiting",
            "reason": "cooling_down",
            "seconds_remaining": 300 - time_since_trigger
        }
    
    conditions = check_recovery_conditions()
    
    if not conditions["can_recover"]:
        _append_event(RECOVERY_LOG, {
            "event": "recovery_blocked",
            "conditions": conditions
        })
        return {
            "action": "blocked",
            "reason": "unsafe_conditions",
            "conditions": conditions
        }
    
    try:
        with open(STATE_FILE, "r") as f:
            state = json.load(f)
        
        state["global_freeze_active"] = False
        state["global_size_throttle_mult"] = 1.0
        state["promotions_frozen"] = False
        
        with open(STATE_FILE, "w") as f:
            json.dump(state, f, indent=2)
        
        _append_event(RECOVERY_LOG, {
            "event": "auto_recovery_success",
            "conditions": conditions
        })
        
        return {
            "action": "recovered",
            "success": True,
            "conditions": conditions
        }
    except Exception as e:
        _append_event(RECOVERY_LOG, {
            "event": "auto_recovery_failed",
            "error": str(e)
        })
        return {
            "action": "failed",
            "error": str(e)
        }

def get_kill_switch_alert() -> Optional[Dict[str, Any]]:
    """Generate alert if kill switch is stuck."""
    status = get_kill_switch_status()
    
    if not status["active"]:
        return None
    
    time_since_trigger = status.get("time_since_trigger", 0)
    
    if time_since_trigger < 300:
        return None
    
    conditions = check_recovery_conditions()
    
    if conditions["can_recover"]:
        return {
            "severity": "warning",
            "message": "Kill switch active but conditions safe - attempting auto-recovery",
            "time_frozen": time_since_trigger,
            "conditions": conditions
        }
    else:
        return {
            "severity": "critical",
            "message": "Kill switch active - conditions still unsafe",
            "time_frozen": time_since_trigger,
            "conditions": conditions,
            "unsafe_reasons": [
                k for k, v in conditions.items() 
                if k.endswith("_safe") and not v
            ]
        }

def monitor_and_recover():
    """Main monitoring function - call periodically."""
    status = get_kill_switch_status()
    
    if not status["active"]:
        return {
            "status": "operational",
            "kill_switch": "inactive"
        }
    
    alert = get_kill_switch_alert()
    recovery_result = attempt_auto_recovery()
    
    return {
        "status": "kill_switch_active",
        "alert": alert,
        "recovery": recovery_result
    }

if __name__ == "__main__":
    result = monitor_and_recover()
    print(json.dumps(result, indent=2))
