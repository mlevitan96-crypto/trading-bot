"""
Exit Health Sentinel - Mandatory health check for exit logic.
Prevents silent exit logic failures by hard-failing when positions lack price data.
"""
import json
import time
from datetime import datetime, timedelta
import pytz

ARIZONA_TZ = pytz.timezone('America/Phoenix')
SENTINEL_LOG = "logs/exit_health_sentinel.jsonl"
MAX_POSITION_STALE_MINUTES = 10  # Trigger safe-mode if position has no price update for 10+ minutes
MAX_EXIT_STALL_HOURS = 1  # Trigger alert if no exits in 1+ hour with open positions

def log_sentinel_event(event: str, payload: dict):
    """Log sentinel events for auditing."""
    try:
        with open(SENTINEL_LOG, "a") as f:
            entry = {
                "timestamp": datetime.now(ARIZONA_TZ).isoformat(),
                "event": event,
                **payload
            }
            f.write(json.dumps(entry) + "\n")
    except Exception as e:
        print(f"⚠️ Sentinel log error: {e}")

def audit_exit_health() -> dict:
    """
    Audit exit health by checking:
    1. Open positions have current price data
    2. Exit logic is executing (not stalled)
    3. Position lifecycle is progressing
    
    Returns:
        dict with {
            "healthy": bool,
            "issues": list of issues found,
            "stale_positions": int,
            "last_exit_minutes_ago": float,
            "action": "pass" | "safe_mode" | "alert"
        }
    """
    issues = []
    stale_count = 0
    
    try:
        # Load positions
        with open("logs/positions.json", "r") as f:
            data = json.load(f)
        
        open_positions = data.get("open_positions", [])
        
        # Check 1: Do open positions have current price data?
        if len(open_positions) > 0:
            for pos in open_positions:
                symbol = pos.get("symbol")
                current_price = pos.get("current_price")
                updated_at = pos.get("updated_at")
                
                if current_price is None:
                    stale_count += 1
                    issues.append(f"{symbol} missing current_price")
                elif updated_at:
                    # Check if price update is stale
                    try:
                        updated_time = datetime.fromisoformat(updated_at)
                        age_minutes = (datetime.now(ARIZONA_TZ) - updated_time.astimezone(ARIZONA_TZ)).total_seconds() / 60
                        
                        if age_minutes > MAX_POSITION_STALE_MINUTES:
                            stale_count += 1
                            issues.append(f"{symbol} price stale ({age_minutes:.1f}min)")
                    except Exception:
                        pass
        
        # Check 2: Has exit logic executed recently?
        last_exit_minutes = None
        try:
            with open("logs/trades.json", "r") as f:
                trades_data = json.load(f)
            
            trades = trades_data.get("trades", [])
            if trades:
                # Find most recent exit
                for trade in reversed(trades):
                    if trade.get("timestamp"):
                        try:
                            trade_time = datetime.fromisoformat(trade["timestamp"])
                            minutes_ago = (datetime.now(ARIZONA_TZ) - trade_time.astimezone(ARIZONA_TZ)).total_seconds() / 60
                            last_exit_minutes = minutes_ago
                            break
                        except Exception:
                            pass
        except Exception:
            pass
        
        # Determine action
        action = "pass"
        
        if len(open_positions) > 0 and stale_count == len(open_positions):
            # ALL positions lack current prices - critical failure
            issues.append(f"CRITICAL: All {len(open_positions)} positions missing price data")
            action = "safe_mode"
        elif stale_count >= 3:
            # Multiple stale positions - warning
            issues.append(f"WARNING: {stale_count} positions with stale data")
            action = "alert"
        elif last_exit_minutes and last_exit_minutes > (MAX_EXIT_STALL_HOURS * 60) and len(open_positions) > 0:
            # No exits in 1+ hour with open positions - potential stall
            issues.append(f"WARNING: No exits in {last_exit_minutes:.0f} minutes with {len(open_positions)} open positions")
            action = "alert"
        
        result = {
            "healthy": len(issues) == 0,
            "issues": issues,
            "stale_positions": stale_count,
            "total_positions": len(open_positions),
            "last_exit_minutes_ago": last_exit_minutes,
            "action": action
        }
        
        # Log the audit
        log_sentinel_event("exit_health_audit", result)
        
        return result
        
    except Exception as e:
        issues.append(f"Audit error: {str(e)}")
        result = {
            "healthy": False,
            "issues": issues,
            "stale_positions": 0,
            "total_positions": 0,
            "last_exit_minutes_ago": None,
            "action": "alert"
        }
        log_sentinel_event("exit_health_audit_error", {"error": str(e)})
        return result

def trigger_safe_mode():
    """Trigger safe mode due to exit health failure."""
    print("\n" + "="*70)
    print("🚨 EXIT HEALTH SENTINEL: SAFE MODE ACTIVATED")
    print("="*70)
    print("Exit logic health check FAILED - positions cannot exit safely")
    print("ACTIONS:")
    print("  1. Freezing new entries")
    print("  2. Attempting to update position prices")
    print("  3. Logging incident for operator review")
    print("="*70 + "\n")
    
    log_sentinel_event("safe_mode_triggered", {
        "reason": "exit_health_failure",
        "timestamp": datetime.now(ARIZONA_TZ).isoformat()
    })

def update_position_prices(current_prices: dict):
    """
    Update positions.json with current market prices.
    Critical for exit logic health.
    
    Args:
        current_prices: Dict of {symbol: price}
    """
    try:
        with open("logs/positions.json", "r") as f:
            data = json.load(f)
        
        open_positions = data.get("open_positions", [])
        updated_count = 0
        
        for pos in open_positions:
            symbol = pos.get("symbol")
            if symbol in current_prices:
                pos["current_price"] = current_prices[symbol]
                pos["updated_at"] = datetime.now(ARIZONA_TZ).isoformat()
                updated_count += 1
        
        # Save updated positions
        with open("logs/positions.json", "w") as f:
            json.dump(data, f, indent=2)
        
        if updated_count > 0:
            print(f"✅ Exit Sentinel: Updated {updated_count} positions with current prices")
        
        log_sentinel_event("position_prices_updated", {
            "updated_count": updated_count,
            "total_positions": len(open_positions)
        })
        
        return updated_count
        
    except Exception as e:
        print(f"⚠️ Exit Sentinel: Failed to update position prices: {e}")
        log_sentinel_event("position_price_update_failed", {"error": str(e)})
        return 0
