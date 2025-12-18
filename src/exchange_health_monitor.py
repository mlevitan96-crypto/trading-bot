"""
Exchange Health Monitor - Monitors exchange API liveness and connectivity.

Tracks consecutive API failures:
- If > 3 failures → mark exchange as DEGRADED
- Block new entries when degraded
- Continue managing exits
- Auto-recover when API responsive again

Specific handling for Kraken:
- Balance endpoint limitations (testnet doesn't support it)
- Explicit logging of testnet limitations
"""

import os
import time
from pathlib import Path
from typing import Dict, Any, Optional, Tuple
from datetime import datetime, timedelta
from collections import deque

from src.infrastructure.path_registry import PathRegistry


# Health thresholds
MAX_CONSECUTIVE_FAILURES = 3  # Mark degraded after 3 consecutive failures
HEALTH_CHECK_INTERVAL = 300  # Check every 5 minutes

# State file
EXCHANGE_HEALTH_STATE = PathRegistry.FEATURE_STORE_DIR / "exchange_health_state.json"


class ExchangeHealthMonitor:
    """
    Monitors exchange API health and connectivity.
    """
    
    def __init__(self):
        self.state_file = EXCHANGE_HEALTH_STATE
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        self.exchange = os.getenv("EXCHANGE", "blofin").lower()
        
    def load_state(self) -> Dict[str, Any]:
        """Load exchange health state."""
        if self.state_file.exists():
            try:
                with open(self.state_file, 'r') as f:
                    import json
                    return json.load(f)
            except Exception as e:
                print(f"⚠️ [EXCHANGE-HEALTH] Failed to load state: {e}")
                return {}
        return {
            "exchange": self.exchange,
            "status": "healthy",
            "consecutive_failures": 0,
            "failure_history": [],
            "last_success": None,
            "last_failure": None,
            "degraded_since": None
        }
    
    def save_state(self, state: Dict[str, Any]):
        """Save exchange health state."""
        state["last_updated"] = datetime.utcnow().isoformat() + "Z"
        try:
            with open(self.state_file, 'w') as f:
                import json
                json.dump(state, f, indent=2)
        except Exception as e:
            print(f"⚠️ [EXCHANGE-HEALTH] Failed to save state: {e}")
    
    def check_exchange_health(self) -> Tuple[bool, Optional[str], Dict[str, Any]]:
        """
        Check exchange API health.
        
        Returns:
            (is_healthy, error_message, details_dict)
        """
        details = {
            "exchange": self.exchange,
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "checks": {}
        }
        
        try:
            from src.exchange_gateway import ExchangeGateway
            gateway = ExchangeGateway()
            
            # Test 1: Mark price (basic connectivity)
            try:
                # Try to get BTC price as a connectivity test
                test_symbol = "BTCUSDT"
                price = gateway.get_price(test_symbol, venue="futures")
                
                if price and price > 0:
                    details["checks"]["mark_price"] = {"status": "ok", "price": price}
                else:
                    return False, "Invalid price returned", details
                    
            except Exception as e:
                error_msg = str(e)
                # Kraken testnet balance endpoint limitation - don't treat as failure
                if "authenticationError" in error_msg and "balance" in error_msg.lower():
                    if self.exchange == "kraken" and os.getenv("KRAKEN_FUTURES_TESTNET", "false").lower() == "true":
                        details["checks"]["mark_price"] = {
                            "status": "ok",
                            "note": "Balance endpoint unsupported on testnet (expected)",
                            "error": error_msg
                        }
                        return True, None, details  # Not a real failure
                
                return False, f"Mark price check failed: {error_msg}", details
            
            # Test 2: Orderbook (data availability)
            try:
                orderbook = gateway.get_orderbook(test_symbol, venue="futures", depth=5)
                if orderbook and orderbook.get("bids") and orderbook.get("asks"):
                    details["checks"]["orderbook"] = {"status": "ok"}
                else:
                    return False, "Empty orderbook returned", details
            except Exception as e:
                return False, f"Orderbook check failed: {str(e)}", details
            
            # Test 3: OHLCV (historical data)
            try:
                df = gateway.fetch_ohlcv(test_symbol, timeframe="1m", limit=5, venue="futures")
                if df is not None and not df.empty:
                    details["checks"]["ohlcv"] = {"status": "ok", "rows": len(df)}
                else:
                    return False, "Empty OHLCV returned", details
            except Exception as e:
                # OHLCV failures are less critical than orderbook/mark price
                details["checks"]["ohlcv"] = {"status": "warning", "error": str(e)}
                # Don't fail health check on OHLCV errors
            
            # All critical checks passed
            return True, None, details
            
        except Exception as e:
            return False, f"Health check exception: {str(e)}", details
    
    def update_health(self) -> Dict[str, Any]:
        """
        Run health check and update state.
        
        Returns:
            Updated health state
        """
        state = self.load_state()
        is_healthy, error_msg, details = self.check_exchange_health()
        
        now = datetime.utcnow()
        
        if is_healthy:
            # Reset failure count on success
            state["consecutive_failures"] = 0
            state["last_success"] = now.isoformat() + "Z"
            state["status"] = "healthy"
            
            # Clear degraded status if was degraded
            if state.get("status") == "degraded":
                degraded_since = state.get("degraded_since")
                if degraded_since:
                    try:
                        degraded_time = datetime.fromisoformat(degraded_since.replace("Z", "+00:00"))
                        recovery_time = (now - degraded_time.replace(tzinfo=None)).total_seconds() / 60
                        print(f"✅ [EXCHANGE-HEALTH] Exchange recovered after {recovery_time:.1f} minutes")
                    except:
                        pass
                
                state["status"] = "healthy"
                state["degraded_since"] = None
        else:
            # Increment failure count
            state["consecutive_failures"] = state.get("consecutive_failures", 0) + 1
            state["last_failure"] = now.isoformat() + "Z"
            
            # Record failure
            failure_record = {
                "timestamp": now.isoformat() + "Z",
                "error": error_msg,
                "consecutive_count": state["consecutive_failures"]
            }
            state.setdefault("failure_history", []).append(failure_record)
            
            # Keep only last 50 failures
            if len(state["failure_history"]) > 50:
                state["failure_history"] = state["failure_history"][-50:]
            
            # Mark as degraded if threshold exceeded
            if state["consecutive_failures"] >= MAX_CONSECUTIVE_FAILURES:
                if state.get("status") != "degraded":
                    state["status"] = "degraded"
                    state["degraded_since"] = now.isoformat() + "Z"
                    print(f"🚨 [EXCHANGE-HEALTH] Exchange marked as DEGRADED after {state['consecutive_failures']} consecutive failures")
                    print(f"   🔒 Blocking new entries. Managing exits only.")
                    print(f"   Error: {error_msg}")
        
        state["details"] = details
        self.save_state(state)
        
        return state
    
    def is_exchange_healthy(self) -> bool:
        """Check if exchange is currently healthy."""
        state = self.load_state()
        return state.get("status", "healthy") == "healthy"
    
    def get_health_status(self) -> Dict[str, Any]:
        """Get current health status."""
        state = self.load_state()
        return {
            "exchange": state.get("exchange", self.exchange),
            "status": state.get("status", "healthy"),
            "consecutive_failures": state.get("consecutive_failures", 0),
            "last_success": state.get("last_success"),
            "last_failure": state.get("last_failure"),
            "degraded_since": state.get("degraded_since")
        }


def check_exchange_health() -> Dict[str, Any]:
    """
    Main entry point for exchange health check.
    
    Call periodically to monitor exchange connectivity.
    """
    monitor = ExchangeHealthMonitor()
    return monitor.update_health()


def is_exchange_healthy() -> bool:
    """Check if exchange is healthy (for blocking entries)."""
    monitor = ExchangeHealthMonitor()
    return monitor.is_exchange_healthy()


def get_exchange_health_status() -> Dict[str, Any]:
    """Get exchange health status."""
    monitor = ExchangeHealthMonitor()
    return monitor.get_health_status()


if __name__ == "__main__":
    # Test exchange health
    print("🧪 Testing Exchange Health Monitor\n")
    
    status = check_exchange_health()
    print(f"Status: {status['status']}")
    print(f"Consecutive failures: {status['consecutive_failures']}")
    print(f"Healthy: {is_exchange_healthy()}")
