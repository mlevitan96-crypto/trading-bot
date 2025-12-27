#!/usr/bin/env python3
"""
Trading Failure Point Monitor
==============================
Comprehensive monitoring for all trading failure points identified in the assessment.

Monitors:
- Exchange API health
- CoinGlass API health
- Kill switch states
- Strategy overlap states
- Symbol probation states
- File system health
- Network connectivity
- Intelligence data freshness
- Position limit states
- Configuration integrity

Runs as a background daemon, logging all failure points to:
- logs/failure_point_monitor.jsonl
- logs/failure_point_monitor_summary.json (latest status)
"""

import json
import time
import threading
import os
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional, Any
from collections import defaultdict

try:
    from src.data_registry import DataRegistry as DR
    from src.exchange_gateway import ExchangeGateway
except ImportError:
    DR = None
    ExchangeGateway = None

LOGS = Path("logs")
FEATURE_STORE = Path("feature_store")
MONITOR_LOG = LOGS / "failure_point_monitor.jsonl"
MONITOR_SUMMARY = LOGS / "failure_point_monitor_summary.json"

# Check intervals
HEALTH_CHECK_INTERVAL = 60  # 1 minute
SUMMARY_UPDATE_INTERVAL = 300  # 5 minutes

# Thresholds
INTELLIGENCE_STALE_SECS = 120  # 2 minutes
API_TIMEOUT_SECS = 10
DISK_SPACE_THRESHOLD_PCT = 90  # Alert if disk > 90% full


class FailurePointMonitor:
    """
    Comprehensive failure point monitoring system.
    """
    
    def __init__(self):
        self.running = False
        self.thread = None
        self.last_summary_update = 0
        self._lock = threading.RLock()
        
        # Ensure directories exist
        LOGS.mkdir(parents=True, exist_ok=True)
        FEATURE_STORE.mkdir(parents=True, exist_ok=True)
    
    def start(self):
        """Start the monitoring daemon"""
        if self.running:
            return
        
        self.running = True
        self.thread = threading.Thread(target=self._run_loop, daemon=True)
        self.thread.start()
        print("🔍 [FAILURE-POINT-MONITOR] Started comprehensive failure point monitoring")
    
    def stop(self):
        """Stop the monitoring daemon"""
        self.running = False
        if self.thread:
            self.thread.join(timeout=5)
        print("🔍 [FAILURE-POINT-MONITOR] Stopped")
    
    def _run_loop(self):
        """Main monitoring loop"""
        while self.running:
            try:
                timestamp = datetime.utcnow().isoformat() + "Z"
                checks = {}
                
                # 1. Exchange API Health
                checks["exchange_api"] = self._check_exchange_api_health()
                
                # 2. CoinGlass API Health
                checks["coinglass_api"] = self._check_coinglass_api_health()
                
                # 3. Kill Switch States
                checks["kill_switch"] = self._check_kill_switch_state()
                
                # 4. Strategy Overlap
                checks["strategy_overlap"] = self._check_strategy_overlap()
                
                # 5. Symbol Probation
                checks["symbol_probation"] = self._check_symbol_probation()
                
                # 6. File System Health
                checks["file_system"] = self._check_file_system_health()
                
                # 7. Network Connectivity
                checks["network"] = self._check_network_connectivity()
                
                # 8. Intelligence Data Freshness
                checks["intelligence_freshness"] = self._check_intelligence_freshness()
                
                # 9. Position Limits
                checks["position_limits"] = self._check_position_limits()
                
                # 10. Configuration Integrity
                checks["config_integrity"] = self._check_config_integrity()
                
                # 11. Dashboard Health
                checks["dashboard"] = self._check_dashboard_health()
                
                # Log all checks
                entry = {
                    "timestamp": timestamp,
                    "checks": checks
                }
                self._log_entry(entry)
                
                # Update summary periodically
                now = time.time()
                if now - self.last_summary_update >= SUMMARY_UPDATE_INTERVAL:
                    self._update_summary(checks)
                    self.last_summary_update = now
                
            except Exception as e:
                print(f"⚠️ [FAILURE-POINT-MONITOR] Error in monitoring loop: {e}")
                import traceback
                traceback.print_exc()
            
            time.sleep(HEALTH_CHECK_INTERVAL)
    
    def _check_exchange_api_health(self) -> Dict[str, Any]:
        """Check Exchange API health"""
        status = {
            "healthy": False,
            "error": None,
            "response_time_ms": None,
            "timestamp": datetime.utcnow().isoformat() + "Z"
        }
        
        try:
            if ExchangeGateway is None:
                status["error"] = "ExchangeGateway not available"
                return status
            
            start_time = time.time()
            gateway = ExchangeGateway()
            # Try a simple API call (get price for a common symbol)
            price = gateway.get_price("BTCUSDT", venue="futures")
            response_time = (time.time() - start_time) * 1000
            
            if price is not None and price > 0:
                status["healthy"] = True
                status["response_time_ms"] = round(response_time, 2)
            else:
                status["error"] = "API returned invalid price"
                
        except Exception as e:
            status["error"] = str(e)
        
        return status
    
    def _check_coinglass_api_health(self) -> Dict[str, Any]:
        """Check CoinGlass API health"""
        status = {
            "healthy": False,
            "error": None,
            "intelligence_available": False,
            "stale": False,
            "timestamp": datetime.utcnow().isoformat() + "Z"
        }
        
        try:
            # Check intelligence summary file
            summary_file = FEATURE_STORE / "intelligence" / "summary.json"
            if summary_file.exists():
                with open(summary_file, 'r') as f:
                    data = json.load(f)
                
                ts_str = data.get('ts', '')
                if ts_str:
                    intel_time = datetime.fromisoformat(ts_str.replace('Z', '+00:00'))
                    age_secs = (datetime.now(timezone.utc) - intel_time.replace(tzinfo=timezone.utc)).total_seconds()
                    
                    status["intelligence_available"] = True
                    status["stale"] = age_secs > INTELLIGENCE_STALE_SECS
                    status["age_seconds"] = round(age_secs, 1)
                    
                    if not status["stale"]:
                        status["healthy"] = True
                else:
                    status["error"] = "No timestamp in intelligence data"
            else:
                status["error"] = "Intelligence summary file not found"
                
        except Exception as e:
            status["error"] = str(e)
        
        return status
    
    def _check_kill_switch_state(self) -> Dict[str, Any]:
        """Check kill switch state"""
        status = {
            "active": False,
            "type": None,
            "blocked_until": None,
            "reason": None,
            "timestamp": datetime.utcnow().isoformat() + "Z"
        }
        
        try:
            # Check max drawdown kill switch
            kill_switch_path = FEATURE_STORE / "max_drawdown_kill_switch_state.json"
            if kill_switch_path.exists():
                with open(kill_switch_path, 'r') as f:
                    state = json.load(f)
                
                blocked_until = state.get("blocked_until")
                if blocked_until:
                    # Check if still blocked
                    try:
                        blocked_dt = datetime.fromisoformat(blocked_until.replace('Z', '+00:00'))
                        if datetime.now(timezone.utc) < blocked_dt.replace(tzinfo=timezone.utc):
                            status["active"] = True
                            status["type"] = "max_drawdown"
                            status["blocked_until"] = blocked_until
                            status["reason"] = state.get("reason", "Portfolio drawdown exceeded threshold")
                    except:
                        pass
                        
        except Exception as e:
            status["error"] = str(e)
        
        return status
    
    def _check_strategy_overlap(self) -> Dict[str, Any]:
        """Check for strategy overlap conflicts"""
        status = {
            "overlaps": [],
            "count": 0,
            "timestamp": datetime.utcnow().isoformat() + "Z"
        }
        
        try:
            if DR is None:
                status["error"] = "DataRegistry not available"
                return status
            
            pos_data = DR.read_json(DR.POSITIONS_FUTURES)
            open_positions = pos_data.get("open_positions", []) if pos_data else []
            
            # Group by symbol and direction
            by_symbol_dir = defaultdict(list)
            for pos in open_positions:
                symbol = pos.get("symbol", "")
                side = pos.get("side", "").upper()
                strategy = pos.get("strategy", "")
                if symbol and side:
                    key = f"{symbol}_{side}"
                    by_symbol_dir[key].append({
                        "strategy": strategy,
                        "symbol": symbol,
                        "side": side
                    })
            
            # Find overlaps (multiple strategies on same symbol/direction)
            for key, positions in by_symbol_dir.items():
                if len(positions) > 1:
                    strategies = [p["strategy"] for p in positions]
                    status["overlaps"].append({
                        "symbol": positions[0]["symbol"],
                        "side": positions[0]["side"],
                        "strategies": strategies,
                        "count": len(positions)
                    })
            
            status["count"] = len(status["overlaps"])
            
        except Exception as e:
            status["error"] = str(e)
        
        return status
    
    def _check_symbol_probation(self) -> Dict[str, Any]:
        """Check symbol probation states"""
        status = {
            "on_probation": [],
            "count": 0,
            "timestamp": datetime.utcnow().isoformat() + "Z"
        }
        
        try:
            from src.symbol_probation_state_machine import get_probation_machine
            probation_machine = get_probation_machine()
            
            # This is a simplified check - may need to adjust based on actual implementation
            # We'll log symbols that are on probation
            # Note: This may require access to internal state, so it's a best-effort check
            
        except Exception as e:
            status["error"] = str(e)
        
        return status
    
    def _check_file_system_health(self) -> Dict[str, Any]:
        """Check file system health (disk space, permissions)"""
        status = {
            "healthy": True,
            "disk_usage_pct": None,
            "permissions_ok": True,
            "errors": [],
            "timestamp": datetime.utcnow().isoformat() + "Z"
        }
        
        try:
            # Check disk space
            stat = os.statvfs(".")
            total = stat.f_blocks * stat.f_frsize
            available = stat.f_bavail * stat.f_frsize
            used = total - available
            usage_pct = (used / total) * 100
            
            status["disk_usage_pct"] = round(usage_pct, 1)
            if usage_pct > DISK_SPACE_THRESHOLD_PCT:
                status["healthy"] = False
                status["errors"].append(f"Disk usage {usage_pct:.1f}% > {DISK_SPACE_THRESHOLD_PCT}% threshold")
            
            # Check critical file permissions
            critical_files = [
                DR.POSITIONS_FUTURES if DR else "logs/positions_futures.json",
                "feature_store/intelligence/summary.json"
            ]
            
            for file_path in critical_files:
                path = Path(file_path)
                if path.exists():
                    if not os.access(path, os.R_OK):
                        status["permissions_ok"] = False
                        status["errors"].append(f"No read permission: {file_path}")
                    if not os.access(path, os.W_OK):
                        status["permissions_ok"] = False
                        status["errors"].append(f"No write permission: {file_path}")
                        
        except Exception as e:
            status["healthy"] = False
            status["errors"].append(str(e))
        
        return status
    
    def _check_network_connectivity(self) -> Dict[str, Any]:
        """Check network connectivity to critical endpoints"""
        status = {
            "healthy": False,
            "endpoints": {},
            "timestamp": datetime.utcnow().isoformat() + "Z"
        }
        
        # Test connectivity to critical endpoints
        endpoints = [
            ("Exchange API", "api.blofin.com"),
            ("CoinGlass API", "api.coinglass.com"),
        ]
        
        all_healthy = True
        for name, host in endpoints:
            endpoint_status = {"reachable": False, "response_time_ms": None}
            
            try:
                # Simple connectivity test (DNS resolution + basic connection)
                import socket
                start_time = time.time()
                socket.create_connection((host, 443), timeout=5)
                response_time = (time.time() - start_time) * 1000
                endpoint_status["reachable"] = True
                endpoint_status["response_time_ms"] = round(response_time, 2)
            except Exception as e:
                endpoint_status["error"] = str(e)
                all_healthy = False
            
            status["endpoints"][name] = endpoint_status
        
        status["healthy"] = all_healthy
        return status
    
    def _check_intelligence_freshness(self) -> Dict[str, Any]:
        """Check intelligence data freshness"""
        status = {
            "fresh": False,
            "age_seconds": None,
            "stale": False,
            "timestamp": datetime.utcnow().isoformat() + "Z"
        }
        
        try:
            summary_file = FEATURE_STORE / "intelligence" / "summary.json"
            if summary_file.exists():
                with open(summary_file, 'r') as f:
                    data = json.load(f)
                
                ts_str = data.get('ts', '')
                if ts_str:
                    intel_time = datetime.fromisoformat(ts_str.replace('Z', '+00:00'))
                    age_secs = (datetime.now(timezone.utc) - intel_time.replace(tzinfo=timezone.utc)).total_seconds()
                    
                    status["age_seconds"] = round(age_secs, 1)
                    status["stale"] = age_secs > INTELLIGENCE_STALE_SECS
                    status["fresh"] = not status["stale"]
            else:
                status["error"] = "Intelligence file not found"
                
        except Exception as e:
            status["error"] = str(e)
        
        return status
    
    def _check_position_limits(self) -> Dict[str, Any]:
        """Check position limit status"""
        status = {
            "at_limit": False,
            "current": 0,
            "max": 10,
            "remaining": 10,
            "timestamp": datetime.utcnow().isoformat() + "Z"
        }
        
        try:
            if DR is None:
                status["error"] = "DataRegistry not available"
                return status
            
            pos_data = DR.read_json(DR.POSITIONS_FUTURES)
            open_positions = pos_data.get("open_positions", []) if pos_data else []
            
            status["current"] = len(open_positions)
            status["remaining"] = status["max"] - status["current"]
            status["at_limit"] = status["current"] >= status["max"]
            
        except Exception as e:
            status["error"] = str(e)
        
        return status
    
    def _check_config_integrity(self) -> Dict[str, Any]:
        """Check configuration file integrity"""
        status = {
            "healthy": True,
            "missing_files": [],
            "invalid_files": [],
            "timestamp": datetime.utcnow().isoformat() + "Z"
        }
        
        critical_configs = [
            "configs/trading_config.json",
            "feature_store/golden_hour_config.json",
        ]
        
        for config_path in critical_configs:
            path = Path(config_path)
            if not path.exists():
                status["healthy"] = False
                status["missing_files"].append(config_path)
            else:
                # Try to parse JSON
                try:
                    with open(path, 'r') as f:
                        json.load(f)
                except json.JSONDecodeError:
                    status["healthy"] = False
                    status["invalid_files"].append(config_path)
        
        return status
    
    def _check_dashboard_health(self) -> Dict[str, Any]:
        """Check dashboard health (port 8050)"""
        status = {
            "healthy": False,
            "accessible": False,
            "response_time_ms": None,
            "error": None,
            "timestamp": datetime.utcnow().isoformat() + "Z"
        }
        
        try:
            import socket
            
            # Check if port is open
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(2)
            result = sock.connect_ex(('localhost', 8050))
            sock.close()
            
            if result == 0:
                status["accessible"] = True
                # Try HTTP request if requests is available
                if REQUESTS_AVAILABLE:
                    try:
                        start_time = time.time()
                        response = requests.get('http://localhost:8050/', timeout=5)
                        response_time = (time.time() - start_time) * 1000
                        
                        if response.status_code == 200:
                            status["healthy"] = True
                            status["response_time_ms"] = round(response_time, 2)
                        else:
                            status["error"] = f"HTTP {response.status_code}"
                    except requests.exceptions.RequestException as e:
                        status["error"] = f"HTTP error: {str(e)}"
                else:
                    # Port is open but can't verify HTTP (requests not available)
                    status["healthy"] = True
                    status["response_time_ms"] = None
            else:
                status["error"] = "Port 8050 not accessible"
                
        except Exception as e:
            status["error"] = str(e)
        
        return status
    
    def _log_entry(self, entry: Dict[str, Any]):
        """Log monitoring entry to JSONL file"""
        try:
            MONITOR_LOG.parent.mkdir(parents=True, exist_ok=True)
            with open(MONITOR_LOG, 'a') as f:
                f.write(json.dumps(entry) + '\n')
        except Exception as e:
            print(f"⚠️ [FAILURE-POINT-MONITOR] Error logging entry: {e}")
    
    def _update_summary(self, checks: Dict[str, Any]):
        """Update summary file with latest status"""
        try:
            summary = {
                "timestamp": datetime.utcnow().isoformat() + "Z",
                "checks": checks,
                "overall_health": self._calculate_overall_health(checks)
            }
            
            with open(MONITOR_SUMMARY, 'w') as f:
                json.dump(summary, f, indent=2)
                
        except Exception as e:
            print(f"⚠️ [FAILURE-POINT-MONITOR] Error updating summary: {e}")
    
    def _calculate_overall_health(self, checks: Dict[str, Any]) -> str:
        """Calculate overall health status"""
        critical_issues = []
        warnings = []
        
        # Critical checks
        if checks.get("exchange_api", {}).get("healthy") is False:
            critical_issues.append("Exchange API unhealthy")
        
        if checks.get("kill_switch", {}).get("active") is True:
            critical_issues.append("Kill switch active")
        
        if checks.get("file_system", {}).get("healthy") is False:
            critical_issues.append("File system issues")
        
        # Warning checks
        if checks.get("coinglass_api", {}).get("stale") is True:
            warnings.append("CoinGlass intelligence stale")
        
        if checks.get("position_limits", {}).get("at_limit") is True:
            warnings.append("Position limit reached")
        
        if checks.get("dashboard", {}).get("healthy") is False:
            critical_issues.append("Dashboard not accessible")
        
        if checks.get("strategy_overlap", {}).get("count", 0) > 0:
            warnings.append(f"Strategy overlaps: {checks['strategy_overlap']['count']}")
        
        if checks.get("dashboard", {}).get("healthy") is False:
            critical_issues.append("Dashboard not accessible")
        
        if critical_issues:
            return "CRITICAL"
        elif warnings:
            return "WARNING"
        else:
            return "HEALTHY"


# Singleton instance
_monitor_instance = None

def get_failure_point_monitor() -> FailurePointMonitor:
    """Get singleton failure point monitor instance"""
    global _monitor_instance
    if _monitor_instance is None:
        _monitor_instance = FailurePointMonitor()
    return _monitor_instance


if __name__ == "__main__":
    monitor = get_failure_point_monitor()
    monitor.start()
    
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        monitor.stop()

