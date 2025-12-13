"""
Exit Stall Monitor - Phase 75/80 integration for exit health metrics.
Tracks position lifecycle and alerts on stalled exits.
"""
import json
import time
from datetime import datetime, timedelta
import pytz

ARIZONA_TZ = pytz.timezone('America/Phoenix')
MONITOR_LOG = "logs/exit_stall_monitor.jsonl"

def log_monitor_event(event: str, payload: dict):
    """Log monitor events."""
    try:
        with open(MONITOR_LOG, "a") as f:
            entry = {
                "timestamp": datetime.now(ARIZONA_TZ).isoformat(),
                "event": event,
                **payload
            }
            f.write(json.dumps(entry) + "\n")
    except Exception as e:
        print(f"⚠️ Exit monitor log error: {e}")

def get_exit_stall_metrics() -> dict:
    """
    Calculate exit stall metrics for Phase 75/80 monitoring.
    
    Returns:
        dict with metrics:
        - stale_position_count: Number of positions without recent price updates
        - exit_stall_minutes: Minutes since last exit (if positions open)
        - avg_position_age_minutes: Average age of open positions
        - health_score: 0.0-1.0 score (1.0 = healthy, 0.0 = critical)
    """
    try:
        # Load positions
        with open("logs/positions.json", "r") as f:
            pos_data = json.load(f)
        
        open_positions = pos_data.get("open_positions", [])
        stale_count = 0
        total_age_minutes = 0
        
        now_time = datetime.now(ARIZONA_TZ)
        
        # Count stale positions and compute ages
        for pos in open_positions:
            # Check if price is stale
            updated_at = pos.get("updated_at")
            if updated_at:
                try:
                    updated_time = datetime.fromisoformat(updated_at)
                    age_minutes = (now_time - updated_time.astimezone(ARIZONA_TZ)).total_seconds() / 60
                    
                    if age_minutes > 10:  # Stale if no update in 10+ minutes
                        stale_count += 1
                except Exception:
                    stale_count += 1  # Count as stale if can't parse timestamp
            else:
                stale_count += 1  # No timestamp = stale
            
            # Compute position age
            opened_at = pos.get("opened_at")
            if opened_at:
                try:
                    opened_time = datetime.fromisoformat(opened_at)
                    position_age = (now_time - opened_time.astimezone(ARIZONA_TZ)).total_seconds() / 60
                    total_age_minutes += position_age
                except Exception:
                    pass
        
        # Find last exit time
        exit_stall_minutes = None
        try:
            with open("logs/trades.json", "r") as f:
                trades_data = json.load(f)
            
            trades = trades_data.get("trades", [])
            if trades:
                for trade in reversed(trades):
                    timestamp = trade.get("timestamp")
                    if timestamp:
                        try:
                            trade_time = datetime.fromisoformat(timestamp)
                            exit_stall_minutes = (now_time - trade_time.astimezone(ARIZONA_TZ)).total_seconds() / 60
                            break
                        except Exception:
                            pass
        except Exception:
            pass
        
        # Compute average position age
        avg_position_age = (total_age_minutes / len(open_positions)) if len(open_positions) > 0 else 0.0
        
        # Compute health score
        health_score = 1.0
        
        if len(open_positions) > 0:
            # Penalize for stale positions
            stale_ratio = stale_count / len(open_positions)
            health_score -= (stale_ratio * 0.5)  # Max -0.5 for all stale
            
            # Penalize for exit stalls
            if exit_stall_minutes and exit_stall_minutes > 120:  # 2+ hours
                stall_penalty = min(0.3, (exit_stall_minutes - 120) / 600)  # Max -0.3
                health_score -= stall_penalty
            
            # Penalize for old positions (positions open >6 hours without exit)
            if avg_position_age > 360:
                age_penalty = min(0.2, (avg_position_age - 360) / 1440)  # Max -0.2
                health_score -= age_penalty
        
        health_score = max(0.0, min(1.0, health_score))
        
        metrics = {
            "stale_position_count": stale_count,
            "total_positions": len(open_positions),
            "exit_stall_minutes": exit_stall_minutes,
            "avg_position_age_minutes": avg_position_age,
            "health_score": health_score,
            "timestamp": datetime.now(ARIZONA_TZ).isoformat()
        }
        
        # Log metrics
        log_monitor_event("exit_stall_metrics", metrics)
        
        return metrics
        
    except Exception as e:
        print(f"⚠️ Exit stall metrics error: {e}")
        return {
            "stale_position_count": 0,
            "total_positions": 0,
            "exit_stall_minutes": None,
            "avg_position_age_minutes": 0.0,
            "health_score": 1.0,
            "error": str(e),
            "timestamp": datetime.now(ARIZONA_TZ).isoformat()
        }

def check_exit_stall_thresholds(metrics: dict) -> dict:
    """
    Check if exit stall metrics breach alert thresholds.
    
    Returns:
        dict with {
            "alert": bool,
            "kill_switch": bool,
            "reasons": list of threshold breaches
        }
    """
    reasons = []
    
    # Threshold 1: >5 stale positions
    if metrics["stale_position_count"] >= 5:
        reasons.append(f"Stale positions: {metrics['stale_position_count']}")
    
    # Threshold 2: No exits in 2+ hours with open positions
    if metrics["exit_stall_minutes"] and metrics["exit_stall_minutes"] > 120 and metrics["total_positions"] > 0:
        reasons.append(f"Exit stall: {metrics['exit_stall_minutes']:.0f} minutes")
    
    # Threshold 3: Health score below 0.5
    if metrics["health_score"] < 0.5:
        reasons.append(f"Low health score: {metrics['health_score']:.2f}")
    
    # Threshold 4: Average position age >12 hours
    if metrics["avg_position_age_minutes"] > 720:
        reasons.append(f"Old positions: {metrics['avg_position_age_minutes']:.0f} min avg")
    
    # Determine actions
    alert = len(reasons) > 0
    kill_switch = metrics["health_score"] < 0.3 or metrics["stale_position_count"] >= 10
    
    result = {
        "alert": alert,
        "kill_switch": kill_switch,
        "reasons": reasons,
        "metrics": metrics
    }
    
    if alert:
        log_monitor_event("exit_stall_threshold_breach", result)
    
    return result
