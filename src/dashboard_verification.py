import os
import json
import time
import requests
from datetime import datetime
from typing import Dict, List, Optional, Tuple

class BackendStateCollector:
    """Reads backend position files and validates integrity"""
    
    def __init__(self):
        self.futures_log = "logs/positions_futures.json"
        self.spot_log = "logs/positions.json"
        self.backup_dir = "logs/backups"
    
    def collect(self) -> Dict:
        """Collect backend state with validation"""
        result = {
            "success": True,
            "positions": [],
            "count": 0,
            "total_margin": 0.0,
            "file_age_seconds": None,
            "errors": [],
            "source": None
        }
        
        # Try futures positions first (primary source)
        if os.path.exists(self.futures_log):
            try:
                with open(self.futures_log, 'r') as f:
                    data = json.load(f)
                
                positions = data.get("open_positions", [])
                result["positions"] = positions
                result["count"] = len(positions)
                result["total_margin"] = sum(p.get("margin_collateral", 0) for p in positions)
                result["source"] = "futures"
                
                # Check file freshness
                mtime = os.path.getmtime(self.futures_log)
                result["file_age_seconds"] = time.time() - mtime
                
            except json.JSONDecodeError as e:
                result["success"] = False
                result["errors"].append(f"FILE_CORRUPTION: {self.futures_log} - {str(e)}")
                self._attempt_restore_backup()
            except Exception as e:
                result["success"] = False
                result["errors"].append(f"READ_ERROR: {str(e)}")
        
        # Fallback to spot positions
        elif os.path.exists(self.spot_log):
            try:
                with open(self.spot_log, 'r') as f:
                    data = json.load(f)
                
                positions = data.get("open_positions", [])
                result["positions"] = positions
                result["count"] = len(positions)
                result["source"] = "spot"
            except Exception as e:
                result["success"] = False
                result["errors"].append(f"SPOT_READ_ERROR: {str(e)}")
        
        return result
    
    def _attempt_restore_backup(self):
        """Auto-restore from most recent backup"""
        if not os.path.exists(self.backup_dir):
            return
        
        try:
            backups = [f for f in os.listdir(self.backup_dir) if f.startswith("positions_futures_")]
            if not backups:
                return
            
            # Get most recent backup
            backups.sort(reverse=True)
            latest = os.path.join(self.backup_dir, backups[0])
            
            # Restore
            import shutil
            shutil.copy(latest, self.futures_log)
            print(f"🔧 AUTO-RESTORE: Restored {self.futures_log} from {latest}")
        except Exception as e:
            print(f"⚠️ Failed to restore backup: {e}")


class UIStateCollector:
    """Fetches rendered dashboard state via HTTP"""
    
    def __init__(self, dashboard_url: str = "http://localhost:5000"):
        self.dashboard_url = dashboard_url
        self.api_endpoint = f"{dashboard_url}/api/open_positions_snapshot"
    
    def collect(self) -> Dict:
        """Collect UI state from dashboard API"""
        result = {
            "success": True,
            "positions_displayed": 0,
            "symbols": [],
            "errors": []
        }
        
        try:
            response = requests.get(self.api_endpoint, timeout=5)
            if response.status_code == 200:
                data = response.json()
                result["positions_displayed"] = data.get("count", 0)
                result["symbols"] = data.get("symbols", [])
            else:
                result["success"] = False
                result["errors"].append(f"HTTP_{response.status_code}: {self.api_endpoint}")
        except requests.exceptions.ConnectionError:
            result["success"] = False
            result["errors"].append("DASHBOARD_OFFLINE: Cannot connect to dashboard")
        except Exception as e:
            result["success"] = False
            result["errors"].append(f"UI_FETCH_ERROR: {str(e)}")
        
        return result


class Comparator:
    """Compares backend vs UI state and diagnoses issues"""
    
    def __init__(self, tolerance: float = 0.05):
        self.tolerance = tolerance  # 5% tolerance for count mismatches
    
    def compare(self, backend: Dict, ui: Dict) -> Dict:
        """Compare states and generate diagnostics"""
        diagnosis = {
            "healthy": True,
            "issues": [],
            "severity": "OK",
            "suggested_fixes": []
        }
        
        # Check if both sources are accessible
        if not backend["success"]:
            diagnosis["healthy"] = False
            diagnosis["severity"] = "CRITICAL"
            diagnosis["issues"].extend(backend["errors"])
            if "FILE_CORRUPTION" in str(backend["errors"]):
                diagnosis["suggested_fixes"].append("AUTO_RESTORE_BACKUP")
        
        if not ui["success"]:
            diagnosis["healthy"] = False
            diagnosis["severity"] = "WARNING"
            diagnosis["issues"].extend(ui["errors"])
            diagnosis["suggested_fixes"].append("RESTART_DASHBOARD")
        
        # Compare position counts
        backend_count = backend["count"]
        ui_count = ui["positions_displayed"]
        
        if backend["success"] and ui["success"]:
            if backend_count > 0 and ui_count == 0:
                diagnosis["healthy"] = False
                diagnosis["severity"] = "CRITICAL"
                diagnosis["issues"].append(
                    f"DISPLAY_MISMATCH: Backend has {backend_count} positions, UI shows 0"
                )
                diagnosis["suggested_fixes"].append("CHECK_DASHBOARD_FILE_PATH")
                diagnosis["suggested_fixes"].append("VERIFY_LOAD_FUNCTION")
            
            elif abs(backend_count - ui_count) > max(1, backend_count * self.tolerance):
                diagnosis["healthy"] = False
                diagnosis["severity"] = "WARNING"
                diagnosis["issues"].append(
                    f"COUNT_MISMATCH: Backend={backend_count}, UI={ui_count}"
                )
                diagnosis["suggested_fixes"].append("REFRESH_DASHBOARD_DATA")
        
        # Check file freshness
        if backend.get("file_age_seconds") and backend["file_age_seconds"] > 300:  # 5 minutes
            diagnosis["healthy"] = False
            diagnosis["severity"] = "WARNING"
            diagnosis["issues"].append(
                f"STALE_BACKEND: Position file not updated in {backend['file_age_seconds']:.0f}s"
            )
            diagnosis["suggested_fixes"].append("CHECK_POSITION_SAVE_FUNCTION")
        
        return diagnosis


class GovernanceBridge:
    """Reports verification results to Health Pulse Orchestrator"""
    
    def __init__(self):
        self.status_file = "logs/dashboard_verification_status.json"
        self.event_log = "logs/dashboard_verification_events.log"
    
    def report(self, diagnosis: Dict, backend: Dict, ui: Dict):
        """Report verification status and log events"""
        
        # Update status file
        status = {
            "timestamp": time.time(),
            "timestamp_formatted": datetime.now().isoformat(),
            "healthy": diagnosis["healthy"],
            "severity": diagnosis["severity"],
            "backend_positions": backend["count"],
            "ui_positions": ui["positions_displayed"],
            "issues": diagnosis["issues"],
            "suggested_fixes": diagnosis["suggested_fixes"]
        }
        
        try:
            with open(self.status_file, 'w') as f:
                json.dump(status, f, indent=2)
        except Exception as e:
            print(f"⚠️ Failed to write status file: {e}")
        
        # Log events
        if not diagnosis["healthy"]:
            event = {
                "timestamp": datetime.now().isoformat(),
                "severity": diagnosis["severity"],
                "issues": diagnosis["issues"],
                "fixes": diagnosis["suggested_fixes"]
            }
            try:
                with open(self.event_log, 'a') as f:
                    f.write(json.dumps(event) + "\n")
            except Exception as e:
                print(f"⚠️ Failed to write event log: {e}")
        
        return status
    
    def get_health_verdict(self) -> bool:
        """Check if dashboard verification is healthy"""
        if not os.path.exists(self.status_file):
            return False
        
        try:
            with open(self.status_file, 'r') as f:
                status = json.load(f)
            
            # Check if status is recent (< 2 minutes old)
            age = time.time() - status.get("timestamp", 0)
            if age > 120:
                return False
            
            return status.get("healthy", False)
        except:
            return False


class DashboardVerificationService:
    """Main orchestrator for dashboard verification"""
    
    def __init__(self, dashboard_url: str = "http://localhost:5000"):
        self.backend_collector = BackendStateCollector()
        self.ui_collector = UIStateCollector(dashboard_url)
        self.comparator = Comparator()
        self.governance = GovernanceBridge()
    
    def run_verification(self) -> Tuple[bool, Dict]:
        """Run full verification cycle"""
        
        # Collect backend state
        backend = self.backend_collector.collect()
        
        # Collect UI state
        ui = self.ui_collector.collect()
        
        # Compare and diagnose
        diagnosis = self.comparator.compare(backend, ui)
        
        # Report to governance
        status = self.governance.report(diagnosis, backend, ui)
        
        # Print summary
        if not diagnosis["healthy"]:
            print(f"\n⚠️ DASHBOARD VERIFICATION FAILED [{diagnosis['severity']}]")
            for issue in diagnosis["issues"]:
                print(f"  ❌ {issue}")
            for fix in diagnosis["suggested_fixes"]:
                print(f"  🔧 Suggested: {fix}")
        else:
            print(f"✅ Dashboard verification passed (Backend={backend['count']}, UI={ui['positions_displayed']})")
        
        return diagnosis["healthy"], status
    
    def is_healthy(self) -> bool:
        """Quick health check without full verification"""
        return self.governance.get_health_verdict()


# Global singleton
_verification_service = None

def get_verification_service() -> DashboardVerificationService:
    """Get or create verification service singleton"""
    global _verification_service
    if _verification_service is None:
        _verification_service = DashboardVerificationService()
    return _verification_service


def verify_dashboard() -> bool:
    """Convenience function for quick verification"""
    service = get_verification_service()
    healthy, _ = service.run_verification()
    return healthy
