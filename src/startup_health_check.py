#!/usr/bin/env python3
"""
STARTUP HEALTH CHECK & AUTO-REMEDIATION
Prevents silent crashes by checking all critical systems before and during operation.

Key Features:
- Port conflict detection and auto-kill
- Process health monitoring
- Crash recovery with alerts
- Heartbeat monitoring
"""

import os
import socket
import signal
import subprocess
import json
import time
import threading
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional

HEALTH_LOG_PATH = "logs/health_check.jsonl"
CRITICAL_PORTS = [5000, 3000, 8080]
HEARTBEAT_FILE = "logs/.bot_heartbeat"
MAX_HEARTBEAT_AGE_SECONDS = 120
CRASH_COUNT_FILE = "logs/.crash_count"
MAX_CRASHES_BEFORE_ALERT = 3


def append_health_log(event: str, details: Dict = None):
    """Log health events."""
    os.makedirs(os.path.dirname(HEALTH_LOG_PATH), exist_ok=True)
    record = {
        "timestamp": datetime.utcnow().isoformat(),
        "event": event,
        "details": details or {}
    }
    try:
        with open(HEALTH_LOG_PATH, 'a') as f:
            f.write(json.dumps(record) + "\n")
    except:
        pass


def is_port_in_use(port: int) -> bool:
    """Check if a port is currently in use."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind(('0.0.0.0', port))
            return False
        except socket.error:
            return True


def get_process_using_port(port: int) -> Optional[int]:
    """Get the PID of process using a port."""
    try:
        result = subprocess.run(
            ['lsof', '-t', '-i', f':{port}'],
            capture_output=True,
            text=True,
            timeout=5
        )
        if result.stdout.strip():
            pids = result.stdout.strip().split('\n')
            return [int(pid) for pid in pids if pid.strip()]
    except:
        pass
    
    try:
        result = subprocess.run(
            ['fuser', f'{port}/tcp'],
            capture_output=True,
            text=True,
            timeout=5
        )
        if result.stdout.strip():
            pids = result.stdout.strip().split()
            return [int(pid) for pid in pids if pid.strip().isdigit()]
    except:
        pass
    
    return []


def kill_process_on_port(port: int, force: bool = False) -> Dict:
    """Kill any process using the specified port."""
    pids = get_process_using_port(port)
    
    if not pids:
        return {"status": "no_process", "port": port}
    
    killed = []
    failed = []
    
    for pid in pids:
        if pid == os.getpid():
            continue
            
        try:
            sig = signal.SIGKILL if force else signal.SIGTERM
            os.kill(pid, sig)
            killed.append(pid)
            append_health_log("process_killed", {"port": port, "pid": pid, "force": force})
        except ProcessLookupError:
            pass
        except PermissionError:
            failed.append(pid)
        except Exception as e:
            failed.append(pid)
    
    if killed:
        time.sleep(0.5)
    
    return {
        "status": "killed" if killed else "failed",
        "port": port,
        "killed_pids": killed,
        "failed_pids": failed
    }


def clear_port(port: int, max_attempts: int = 3) -> bool:
    """Ensure a port is free, killing processes if needed."""
    for attempt in range(max_attempts):
        if not is_port_in_use(port):
            return True
        
        force = attempt >= 1
        result = kill_process_on_port(port, force=force)
        
        if result["status"] == "killed":
            time.sleep(0.5)
            if not is_port_in_use(port):
                return True
        
        time.sleep(0.2)
    
    return not is_port_in_use(port)


def update_heartbeat():
    """Update the heartbeat file to indicate the bot is alive."""
    try:
        os.makedirs(os.path.dirname(HEARTBEAT_FILE), exist_ok=True)
        with open(HEARTBEAT_FILE, 'w') as f:
            f.write(datetime.utcnow().isoformat())
    except:
        pass


def check_heartbeat() -> Dict:
    """Check if the bot heartbeat is current."""
    try:
        if not os.path.exists(HEARTBEAT_FILE):
            return {"status": "missing", "age_seconds": None}
        
        with open(HEARTBEAT_FILE, 'r') as f:
            last_beat = datetime.fromisoformat(f.read().strip())
        
        age = (datetime.utcnow() - last_beat).total_seconds()
        
        if age > MAX_HEARTBEAT_AGE_SECONDS:
            return {"status": "stale", "age_seconds": age}
        
        return {"status": "healthy", "age_seconds": age}
    except:
        return {"status": "error", "age_seconds": None}


def increment_crash_count() -> int:
    """Increment and return the crash count."""
    try:
        count = 0
        today = datetime.utcnow().date().isoformat()
        if os.path.exists(CRASH_COUNT_FILE):
            with open(CRASH_COUNT_FILE, 'r') as f:
                data = json.load(f)
                stored_date = data.get('date', '')
                if stored_date == today:
                    count = data.get('count', 0)
        
        count += 1
        
        os.makedirs(os.path.dirname(CRASH_COUNT_FILE), exist_ok=True)
        with open(CRASH_COUNT_FILE, 'w') as f:
            json.dump({
                'date': datetime.utcnow().date().isoformat(),
                'count': count,
                'last_crash': datetime.utcnow().isoformat()
            }, f)
        
        return count
    except:
        return 1


def reset_crash_count():
    """Reset the crash count after successful startup."""
    try:
        if os.path.exists(CRASH_COUNT_FILE):
            os.remove(CRASH_COUNT_FILE)
    except:
        pass


def run_startup_health_check() -> Dict[str, Any]:
    """
    Run all startup health checks with auto-remediation.
    Returns status and any issues found.
    """
    print("=" * 60)
    print("STARTUP HEALTH CHECK")
    print("=" * 60)
    
    results = {
        "timestamp": datetime.utcnow().isoformat(),
        "checks": {},
        "remediations": [],
        "overall_status": "healthy"
    }
    
    print("\n[DATA INTEGRITY] Validating data sources...")
    try:
        from src.data_integrity_validator import DataIntegrityValidator
        data_validation = DataIntegrityValidator.run_startup_validation(fix_issues=True)
        results["checks"]["data_integrity"] = data_validation["status"]
        if data_validation["status"] == "FAIL":
            results["overall_status"] = "degraded"
            print(f"   Data integrity issues: {len(data_validation['issues_found'])}")
        elif data_validation["status"] == "FIXED":
            results["remediations"].extend([f"data_fix:{f}" for f in data_validation.get("fixes_applied", [])])
            print(f"   Data integrity: {len(data_validation.get('fixes_applied', []))} issues auto-fixed")
        else:
            print("   Data integrity: OK")
    except Exception as e:
        print(f"   Data integrity check failed: {e}")
        results["checks"]["data_integrity"] = "error"
    
    print("\n📡 Checking critical ports...")
    gunicorn_active = os.environ.get("USE_GUNICORN", "1") == "1"
    
    for port in CRITICAL_PORTS:
        if is_port_in_use(port):
            if port == 5000 and gunicorn_active:
                print(f"   ✅ Port {port} in use by Gunicorn (expected)")
                results["checks"][f"port_{port}"] = "ok"
            else:
                print(f"   ⚠️  Port {port} in use - clearing...")
                if clear_port(port):
                    print(f"   ✅ Port {port} cleared successfully")
                    results["remediations"].append(f"cleared_port_{port}")
                    results["checks"][f"port_{port}"] = "remediated"
                else:
                    print(f"   ❌ Failed to clear port {port}")
                    results["checks"][f"port_{port}"] = "failed"
                    results["overall_status"] = "degraded"
        else:
            print(f"   ✅ Port {port} available")
            results["checks"][f"port_{port}"] = "ok"
    
    print("\n💓 Checking heartbeat status...")
    heartbeat = check_heartbeat()
    if heartbeat["status"] == "stale":
        print(f"   ⚠️  Heartbeat stale ({heartbeat['age_seconds']:.0f}s old)")
        results["checks"]["heartbeat"] = "stale"
    elif heartbeat["status"] == "missing":
        print(f"   ℹ️  No previous heartbeat (fresh start)")
        results["checks"]["heartbeat"] = "fresh_start"
    else:
        print(f"   ✅ Heartbeat healthy ({heartbeat.get('age_seconds', 0):.0f}s old)")
        results["checks"]["heartbeat"] = "ok"
    
    print("\n📁 Checking critical files...")
    critical_files = [
        "logs/portfolio.json",
        "config/asset_universe.json",
        "feature_store/signal_weights.json"
    ]
    
    for filepath in critical_files:
        if os.path.exists(filepath):
            try:
                with open(filepath, 'r') as f:
                    content = f.read()
                    if filepath.endswith('.json'):
                        json.loads(content)
                print(f"   ✅ {filepath} valid")
                results["checks"][filepath] = "ok"
            except json.JSONDecodeError:
                print(f"   🚨 {filepath} CORRUPTED - attempting auto-repair...")
                results["checks"][filepath] = "corrupted"
                # CRITICAL: Attempt restore from backup for portfolio.json
                if "portfolio" in filepath:
                    try:
                        from src.data_registry import DataRegistry as DR
                        if DR.restore_from_backup(filepath):
                            print(f"   ✅ {filepath} restored from backup!")
                            results["checks"][filepath] = "restored"
                            results["remediations"].append(f"restored_{filepath}")
                        else:
                            print(f"   ❌ No backup available for {filepath}")
                            results["overall_status"] = "degraded"
                    except Exception as restore_err:
                        print(f"   ❌ Restore failed: {restore_err}")
                        results["overall_status"] = "degraded"
                else:
                    results["overall_status"] = "degraded"
            except Exception as e:
                print(f"   ⚠️  {filepath} error: {e}")
                results["checks"][filepath] = "error"
        else:
            print(f"   ℹ️  {filepath} not found (will be created)")
            results["checks"][filepath] = "missing"
    
    print("\n🔄 Checking Python processes...")
    try:
        result = subprocess.run(
            ['pgrep', '-f', 'python.*run.py'],
            capture_output=True,
            text=True,
            timeout=5
        )
        pids = [p for p in result.stdout.strip().split('\n') if p and int(p) != os.getpid()]
        if pids:
            print(f"   ⚠️  Found {len(pids)} orphan Python processes")
            for pid in pids:
                try:
                    os.kill(int(pid), signal.SIGTERM)
                    print(f"   ✅ Killed orphan process {pid}")
                    results["remediations"].append(f"killed_orphan_{pid}")
                except:
                    pass
        else:
            print("   ✅ No orphan processes")
        results["checks"]["orphan_processes"] = "ok"
    except Exception as e:
        print(f"   ⚠️  Process check error: {e}")
        results["checks"]["orphan_processes"] = "error"
    
    reset_crash_count()
    update_heartbeat()
    
    append_health_log("startup_health_check", results)
    
    print("\n" + "=" * 60)
    print(f"🏥 HEALTH CHECK COMPLETE: {results['overall_status'].upper()}")
    print("=" * 60)
    
    return results


class HealthWatchdog:
    """
    Background watchdog that monitors bot health and auto-remediates issues.
    """
    
    def __init__(self, interval_seconds: int = 30):
        self.interval = interval_seconds
        self.running = False
        self.thread = None
        self.consecutive_failures = 0
        self.max_failures = 5
    
    def start(self):
        """Start the watchdog in a background thread."""
        if self.running:
            return
        
        self.running = True
        self.thread = threading.Thread(target=self._watchdog_loop, daemon=True)
        self.thread.start()
        print(f"🐕 Health Watchdog started (checking every {self.interval}s)")
    
    def stop(self):
        """Stop the watchdog."""
        self.running = False
    
    def _watchdog_loop(self):
        """Main watchdog loop."""
        while self.running:
            try:
                self._check_health()
                self.consecutive_failures = 0
            except Exception as e:
                self.consecutive_failures += 1
                append_health_log("watchdog_error", {"error": str(e), "consecutive": self.consecutive_failures})
                
                if self.consecutive_failures >= self.max_failures:
                    append_health_log("watchdog_critical", {"message": "Too many consecutive failures"})
            
            time.sleep(self.interval)
    
    def _check_health(self):
        """Run health checks."""
        update_heartbeat()
        
        if is_port_in_use(5000):
            pass
        else:
            append_health_log("port_lost", {"port": 5000})
        
        heartbeat = check_heartbeat()
        if heartbeat["status"] == "stale" and heartbeat.get("age_seconds", 0) > 300:
            append_health_log("heartbeat_critical", heartbeat)


_watchdog_instance = None


def get_watchdog() -> HealthWatchdog:
    """Get the singleton watchdog instance."""
    global _watchdog_instance
    if _watchdog_instance is None:
        _watchdog_instance = HealthWatchdog()
    return _watchdog_instance


def start_health_watchdog(interval: int = 30):
    """Start the health watchdog."""
    watchdog = get_watchdog()
    watchdog.interval = interval
    watchdog.start()


if __name__ == "__main__":
    results = run_startup_health_check()
    print(f"\nResults: {json.dumps(results, indent=2)}")
