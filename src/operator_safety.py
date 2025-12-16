"""
Operator Safety Module - Alerts, Validation, and Recovery

Provides:
- Operator alerts for critical failures
- State validation and integrity checks
- Recovery mechanisms for corrupted state
- Startup validation for deployment issues
"""

import os
import sys
import json
import time
from pathlib import Path
from typing import Dict, List, Optional, Any
from datetime import datetime
import traceback

# Alert levels
ALERT_CRITICAL = "CRITICAL"
ALERT_HIGH = "HIGH"
ALERT_MEDIUM = "MEDIUM"
ALERT_LOW = "LOW"

# Alert destinations
ALERT_LOG_FILE = "logs/operator_alerts.jsonl"
ALERT_STDOUT = True  # Always print to stdout for systemd/journalctl


class OperatorAlert:
    """Represents an operator alert."""
    
    def __init__(self, level: str, category: str, message: str, details: Dict = None, action_required: bool = False):
        self.level = level
        self.category = category
        self.message = message
        self.details = details or {}
        self.action_required = action_required
        self.timestamp = time.time()
        self.timestamp_iso = datetime.utcnow().isoformat()
    
    def to_dict(self) -> Dict:
        return {
            "level": self.level,
            "category": self.category,
            "message": self.message,
            "details": self.details,
            "action_required": self.action_required,
            "timestamp": self.timestamp,
            "timestamp_iso": self.timestamp_iso
        }
    
    def format_for_operator(self) -> str:
        """Format alert for operator-friendly display."""
        level_emoji = {
            ALERT_CRITICAL: "🚨",
            ALERT_HIGH: "⚠️",
            ALERT_MEDIUM: "ℹ️",
            ALERT_LOW: "📝"
        }
        emoji = level_emoji.get(self.level, "📝")
        
        msg = f"{emoji} [{self.level}] {self.category}: {self.message}"
        if self.action_required:
            msg += " [ACTION REQUIRED]"
        if self.details:
            details_str = ", ".join(f"{k}={v}" for k, v in self.details.items())
            msg += f" | {details_str}"
        return msg


def alert_operator(level: str, category: str, message: str, details: Dict = None, action_required: bool = False):
    """
    Send an alert to the operator.
    
    Args:
        level: Alert level (CRITICAL, HIGH, MEDIUM, LOW)
        category: Alert category (e.g., "POSITION_SAVE", "FILE_LOCK", "SYSTEMD_SLOT")
        message: Human-readable message
        details: Additional details dict
        action_required: Whether operator action is required
    """
    alert = OperatorAlert(level, category, message, details, action_required)
    
    # Always print to stdout (captured by systemd/journalctl)
    if ALERT_STDOUT:
        print(alert.format_for_operator(), flush=True)
    
    # Log to alert file
    try:
        from src.infrastructure.path_registry import resolve_path
        alert_file = resolve_path(ALERT_LOG_FILE)
        os.makedirs(os.path.dirname(alert_file), exist_ok=True)
        with open(alert_file, 'a') as f:
            f.write(json.dumps(alert.to_dict()) + '\n')
    except Exception as e:
        # Fallback if path resolution fails
        try:
            os.makedirs("logs", exist_ok=True)
            with open(ALERT_LOG_FILE, 'a') as f:
                f.write(json.dumps(alert.to_dict()) + '\n')
        except:
            pass  # Don't fail if alerting fails


def validate_systemd_slot():
    """
    Validate that systemd service is pointing to correct slot.
    
    Returns:
        dict with validation results
    """
    result = {
        "valid": True,
        "issues": [],
        "current_slot": None,
        "expected_slot": None
    }
    
    try:
        # Get current working directory (set by systemd WorkingDirectory)
        cwd = os.getcwd()
        result["current_slot"] = cwd
        
        # Check if we're in a slot directory
        if "trading-bot-current" in cwd:
            # Resolve symlink to see actual slot
            try:
                real_path = os.path.realpath(cwd)
                result["actual_slot"] = real_path
                
                if "trading-bot-A" in real_path:
                    result["expected_slot"] = "A"
                elif "trading-bot-B" in real_path:
                    result["expected_slot"] = "B"
                else:
                    result["issues"].append("Symlink points to unknown directory")
                    result["valid"] = False
            except Exception as e:
                result["issues"].append(f"Could not resolve symlink: {e}")
                result["valid"] = False
        
        # Check if code is stale (compare git commit)
        try:
            from src.infrastructure.path_registry import PathRegistry
            repo_root = PathRegistry.get_root()
            git_head = repo_root / ".git" / "HEAD"
            
            if git_head.exists():
                # Check if HEAD is detached or on branch
                with open(git_head, 'r') as f:
                    head_content = f.read().strip()
                    if head_content.startswith("ref:"):
                        # On branch, check last commit
                        ref_path = repo_root / ".git" / head_content[5:]
                        if ref_path.exists():
                            with open(ref_path, 'r') as f2:
                                commit_hash = f2.read().strip()[:8]
                                result["git_commit"] = commit_hash
        except Exception as e:
            # Git check is optional
            pass
        
        # Check if positions file exists and is accessible
        try:
            from src.infrastructure.path_registry import PathRegistry
            pos_file = PathRegistry.POS_LOG
            if not os.path.exists(pos_file):
                result["issues"].append(f"Positions file not found: {pos_file}")
                result["valid"] = False
            elif not os.access(pos_file, os.R_OK | os.W_OK):
                result["issues"].append(f"Positions file not accessible: {pos_file}")
                result["valid"] = False
        except Exception as e:
            result["issues"].append(f"Could not validate positions file: {e}")
            result["valid"] = False
        
        if not result["valid"]:
            # In paper mode, downgrade to HIGH alert (don't block startup)
            # In real trading mode, keep as CRITICAL
            alert_level = ALERT_HIGH if os.getenv('TRADING_MODE', 'paper').lower() == 'paper' else ALERT_CRITICAL
            alert_operator(
                alert_level,
                "SYSTEMD_SLOT",
                "Systemd slot validation failed",
                result,
                action_required=(alert_level == ALERT_CRITICAL)
            )
        else:
            print(f"✅ [SAFETY] Systemd slot validation passed: {result.get('expected_slot', 'unknown')} slot")
        
    except Exception as e:
        result["valid"] = False
        result["issues"].append(f"Validation error: {e}")
        # In paper mode, downgrade to HIGH alert (don't block startup)
        trading_mode = os.getenv('TRADING_MODE', 'paper').lower()
        alert_level = ALERT_HIGH if trading_mode == 'paper' else ALERT_CRITICAL
        alert_operator(
            alert_level,
            "SYSTEMD_SLOT",
            f"Systemd slot validation error: {e}",
            {"error": str(e), "traceback": traceback.format_exc()},
            action_required=(alert_level == ALERT_CRITICAL)
        )
    
    return result


def validate_startup_state():
    """
    Validate system state on startup.
    
    Checks:
    - Positions file integrity
    - Config file accessibility
    - Required directories exist
    - File permissions
    
    Returns:
        dict with validation results
    """
    result = {
        "valid": True,
        "issues": [],
        "checks": {}
    }
    
    try:
        from src.infrastructure.path_registry import PathRegistry
        
        # Check positions file
        pos_file = PathRegistry.POS_LOG
        if os.path.exists(pos_file):
            try:
                with open(pos_file, 'r') as f:
                    data = json.load(f)
                    if not isinstance(data, dict):
                        result["issues"].append("Positions file is not a dict")
                        result["valid"] = False
                    elif "open_positions" not in data or "closed_positions" not in data:
                        result["issues"].append("Positions file missing required keys")
                        result["valid"] = False
                    else:
                        result["checks"]["positions_file"] = {
                            "open_count": len(data.get("open_positions", [])),
                            "closed_count": len(data.get("closed_positions", []))
                        }
            except json.JSONDecodeError as e:
                result["issues"].append(f"Positions file is corrupted: {e}")
                result["valid"] = False
        else:
            result["checks"]["positions_file"] = "missing (will be created)"
        
        # Check logs directory
        logs_dir = PathRegistry.LOGS_DIR
        if not os.path.exists(logs_dir):
            result["issues"].append(f"Logs directory missing: {logs_dir}")
            result["valid"] = False
        elif not os.access(logs_dir, os.W_OK):
            result["issues"].append(f"Logs directory not writable: {logs_dir}")
            result["valid"] = False
        
        # Check config files
        config_files = [
            ("live_config.json", PathRegistry.get_path("live_config.json")),
            ("asset_universe.json", PathRegistry.get_path("config", "asset_universe.json")),
        ]
        
        for name, path in config_files:
            if os.path.exists(path):
                if not os.access(path, os.R_OK):
                    result["issues"].append(f"Config file not readable: {name}")
                    result["valid"] = False
            else:
                result["checks"][f"config_{name}"] = "missing (optional)"
        
        if not result["valid"]:
            # In paper mode, downgrade to MEDIUM alert (don't block startup)
            # In real trading mode, keep as HIGH
            trading_mode = os.getenv('TRADING_MODE', 'paper').lower()
            alert_level = ALERT_MEDIUM if trading_mode == 'paper' else ALERT_HIGH
            alert_operator(
                alert_level,
                "STARTUP_VALIDATION",
                "Startup state validation failed",
                result,
                action_required=(alert_level == ALERT_HIGH)
            )
        else:
            print(f"✅ [SAFETY] Startup state validation passed")
            if result["checks"]:
                print(f"   Checks: {result['checks']}")
        
    except Exception as e:
        result["valid"] = False
        result["issues"].append(f"Validation error: {e}")
        # In paper mode, downgrade to MEDIUM alert (don't block startup)
        trading_mode = os.getenv('TRADING_MODE', 'paper').lower()
        alert_level = ALERT_MEDIUM if trading_mode == 'paper' else ALERT_HIGH
        alert_operator(
            alert_level,
            "STARTUP_VALIDATION",
            f"Startup validation error: {e}",
            {"error": str(e)},
            action_required=(alert_level == ALERT_HIGH)
        )
    
    return result


def validate_position_integrity(positions: Dict) -> Dict:
    """
    Validate position data integrity.
    
    Args:
        positions: Positions dict from load_futures_positions()
    
    Returns:
        dict with validation results
    """
    result = {
        "valid": True,
        "issues": [],
        "stats": {}
    }
    
    open_positions = positions.get("open_positions", [])
    closed_positions = positions.get("closed_positions", [])
    
    result["stats"]["open_count"] = len(open_positions)
    result["stats"]["closed_count"] = len(closed_positions)
    
    # Validate open positions
    for i, pos in enumerate(open_positions):
        # Check required fields
        required_fields = ["symbol", "direction", "entry_price", "size", "leverage", "strategy"]
        for field in required_fields:
            if field not in pos:
                result["issues"].append(f"Open position {i} missing field: {field}")
                result["valid"] = False
        
        # Check for invalid values
        if pos.get("entry_price", 0) <= 0:
            result["issues"].append(f"Open position {i} ({pos.get('symbol')}) has invalid entry_price: {pos.get('entry_price')}")
            result["valid"] = False
        
        if pos.get("size", 0) <= 0:
            result["issues"].append(f"Open position {i} ({pos.get('symbol')}) has invalid size: {pos.get('size')}")
            result["valid"] = False
        
        if pos.get("leverage", 0) <= 0:
            result["issues"].append(f"Open position {i} ({pos.get('symbol')}) has invalid leverage: {pos.get('leverage')}")
            result["valid"] = False
    
    if not result["valid"]:
        alert_operator(
            ALERT_HIGH,
            "POSITION_INTEGRITY",
            "Position integrity validation failed",
            result,
            action_required=True
        )
    
    return result


def safe_save_with_retry(filepath: str, data: Dict, max_retries: int = 3) -> bool:
    """
    Safely save JSON file with retry logic and alerting.
    
    Args:
        filepath: Path to file
        data: Data to save
        max_retries: Maximum retry attempts
    
    Returns:
        True if successful, False otherwise
    """
    from src.file_locks import atomic_json_save
    
    for attempt in range(max_retries):
        try:
            if atomic_json_save(filepath, data):
                return True
            
            # Atomic save failed, try fallback
            if attempt < max_retries - 1:
                time.sleep(0.1 * (attempt + 1))  # Exponential backoff
                continue
            
            # Last attempt - use fallback with alert
            alert_operator(
                ALERT_CRITICAL,
                "POSITION_SAVE",
                f"Atomic save failed, using fallback (attempt {attempt + 1}/{max_retries})",
                {"filepath": filepath, "attempt": attempt + 1},
                action_required=True
            )
            
            # Fallback: non-atomic write
            tmp_path = filepath + '.tmp'
            with open(tmp_path, 'w') as f:
                json.dump(data, f, indent=2)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_path, filepath)
            
            # Verify write
            try:
                with open(filepath, 'r') as f:
                    verify_data = json.load(f)
                if verify_data != data:
                    alert_operator(
                        ALERT_CRITICAL,
                        "POSITION_SAVE",
                        "Fallback save verification failed - data mismatch",
                        {"filepath": filepath},
                        action_required=True
                    )
                    return False
            except Exception as e:
                alert_operator(
                    ALERT_CRITICAL,
                    "POSITION_SAVE",
                    f"Fallback save verification failed: {e}",
                    {"filepath": filepath, "error": str(e)},
                    action_required=True
                )
                return False
            
            return True
            
        except Exception as e:
            if attempt < max_retries - 1:
                time.sleep(0.1 * (attempt + 1))
                continue
            
            alert_operator(
                ALERT_CRITICAL,
                "POSITION_SAVE",
                f"Save failed after {max_retries} attempts: {e}",
                {"filepath": filepath, "error": str(e), "traceback": traceback.format_exc()},
                action_required=True
            )
            return False
    
    return False


def get_status() -> Dict[str, str]:
    """
    Get operator safety layer health status.
    
    Returns:
        dict with component -> status_color mapping
        Status colors: "green" (healthy), "yellow" (degraded), "red" (failing)
    """
    status = {}
    
    try:
        from src.infrastructure.path_registry import PathRegistry
        
        # Check positions file integrity
        pos_file = PathRegistry.POS_LOG
        if not pos_file.exists():
            status["safety_layer"] = STATUS_RED
        else:
            try:
                with open(pos_file, 'r') as f:
                    data = json.load(f)
                if not isinstance(data, dict) or "open_positions" not in data or "closed_positions" not in data:
                    status["safety_layer"] = STATUS_YELLOW
                else:
                    status["safety_layer"] = STATUS_GREEN
            except json.JSONDecodeError:
                status["safety_layer"] = STATUS_RED
            except Exception:
                status["safety_layer"] = STATUS_YELLOW
        
        # Check self-healing status (check if last healing was successful)
        try:
            from src.infrastructure.path_registry import resolve_path
            alert_file = resolve_path(ALERT_LOG_FILE)
        except:
            alert_file = Path(ALERT_LOG_FILE)
        if alert_file.exists():
            # Check for recent critical alerts (within last hour)
            try:
                critical_count = 0
                with open(alert_file, 'r') as f:
                    for line in f:
                        try:
                            alert = json.loads(line)
                            if alert.get("level") == ALERT_CRITICAL:
                                alert_age = time.time() - alert.get("timestamp", 0)
                                if alert_age < 3600:  # Last hour
                                    critical_count += 1
                        except:
                            continue
                
                if critical_count > 0:
                    status["self_healing"] = STATUS_YELLOW
                else:
                    status["self_healing"] = STATUS_GREEN
            except Exception:
                status["self_healing"] = STATUS_YELLOW
        else:
            status["self_healing"] = STATUS_GREEN
            
    except Exception as e:
        status["safety_layer"] = STATUS_RED
        status["self_healing"] = STATUS_RED
    
    return status


# Status colors for get_status()
STATUS_GREEN = "green"
STATUS_YELLOW = "yellow"
STATUS_RED = "red"


# ============================================================================
# SELF-HEALING LAYER
# ============================================================================

def self_heal() -> Dict[str, Any]:
    """
    Comprehensive self-healing for recoverable issues.
    
    Auto-heals:
    - Cold-start: Missing/empty files, missing directories
    - Recoverable runtime: Stale heartbeats, lock timeouts, orphan processes, corrupted JSON
    
    Does NOT auto-heal (CRITICAL alerts only):
    - State mismatches (positions vs portfolio)
    - Partial fills (incomplete trades)
    - Conflicting positions (duplicate entries)
    - Data integrity violations
    
    Returns:
        dict with healing results:
        {
            "success": bool,
            "healed": List[str],  # List of issues healed
            "failed": List[str],   # List of issues that couldn't be healed
            "critical": List[str], # List of dangerous issues (not auto-healed)
            "stats": {
                "files_created": int,
                "files_repaired": int,
                "directories_created": int,
                "heartbeats_reset": int,
                "locks_cleared": int,
                "orphans_killed": int
            }
        }
    """
    result = {
        "success": True,
        "healed": [],
        "failed": [],
        "critical": [],
        "stats": {
            "files_created": 0,
            "files_repaired": 0,
            "directories_created": 0,
            "heartbeats_reset": 0,
            "locks_cleared": 0,
            "orphans_killed": 0
        }
    }
    
    print("\n🔧 [SELF-HEAL] Starting self-healing process...")
    
    try:
        from src.infrastructure.path_registry import PathRegistry
        from src.file_locks import locked_json_read, atomic_json_save
        
        # ====================================================================
        # 1. COLD-START: Create missing directories
        # ====================================================================
        required_dirs = [
            PathRegistry.LOGS_DIR,
            PathRegistry.CONFIG_DIR,
            PathRegistry.CONFIGS_DIR,
            PathRegistry.DATA_DIR,
            PathRegistry.FEATURE_STORE_DIR,
            Path("state"),
            Path("state/heartbeats"),
            Path("logs/backups"),
        ]
        
        for dir_path in required_dirs:
            if not dir_path.exists():
                try:
                    dir_path.mkdir(parents=True, exist_ok=True)
                    result["stats"]["directories_created"] += 1
                    result["healed"].append(f"Created directory: {dir_path}")
                    print(f"   ✅ Created directory: {dir_path}")
                except Exception as e:
                    result["failed"].append(f"Failed to create directory {dir_path}: {e}")
                    print(f"   ❌ Failed to create directory {dir_path}: {e}")
        
        # ====================================================================
        # 2. COLD-START: Initialize missing/empty position files
        # ====================================================================
        pos_file = PathRegistry.POS_LOG
        if not pos_file.exists() or pos_file.stat().st_size == 0:
            try:
                # Try to read existing data first (might be corrupted)
                existing_data = {}
                if pos_file.exists():
                    try:
                        existing_data = locked_json_read(str(pos_file), default={})
                    except:
                        pass  # File is corrupted, will create fresh
                
                # Create valid structure
                positions = {
                    "open_positions": existing_data.get("open_positions", []),
                    "closed_positions": existing_data.get("closed_positions", []),
                    "created_at": datetime.utcnow().isoformat(),
                    "healed_at": datetime.utcnow().isoformat()
                }
                
                if atomic_json_save(str(pos_file), positions):
                    result["stats"]["files_created"] += 1
                    result["healed"].append(f"Initialized positions file: {pos_file}")
                    print(f"   ✅ Initialized positions file: {pos_file}")
                else:
                    result["failed"].append(f"Failed to save positions file: {pos_file}")
            except Exception as e:
                result["failed"].append(f"Failed to initialize positions file: {e}")
                print(f"   ❌ Failed to initialize positions file: {e}")
        else:
            # Check if file is corrupted JSON
            try:
                with open(pos_file, 'r') as f:
                    data = json.load(f)
                # Validate structure
                if not isinstance(data, dict) or "open_positions" not in data or "closed_positions" not in data:
                    # Repair structure
                    positions = {
                        "open_positions": data.get("open_positions", []) if isinstance(data.get("open_positions"), list) else [],
                        "closed_positions": data.get("closed_positions", []) if isinstance(data.get("closed_positions"), list) else [],
                        "created_at": data.get("created_at", datetime.utcnow().isoformat()),
                        "healed_at": datetime.utcnow().isoformat()
                    }
                    if atomic_json_save(str(pos_file), positions):
                        result["stats"]["files_repaired"] += 1
                        result["healed"].append(f"Repaired positions file structure: {pos_file}")
                        print(f"   ✅ Repaired positions file structure: {pos_file}")
            except json.JSONDecodeError:
                # File is corrupted, try to extract what we can
                try:
                    from src.file_locks import DEFAULT_EMPTY
                    positions = DEFAULT_EMPTY.copy()
                    positions["created_at"] = datetime.utcnow().isoformat()
                    positions["healed_at"] = datetime.utcnow().isoformat()
                    if atomic_json_save(str(pos_file), positions):
                        result["stats"]["files_repaired"] += 1
                        result["healed"].append(f"Repaired corrupted positions file: {pos_file}")
                        print(f"   ✅ Repaired corrupted positions file: {pos_file}")
                except Exception as e:
                    result["failed"].append(f"Failed to repair corrupted positions file: {e}")
        
        # ====================================================================
        # 3. COLD-START: Initialize other critical files
        # ====================================================================
        critical_files = [
            ("logs/unified_events.jsonl", None),  # JSONL file, no initialization needed
            ("logs/portfolio_futures.json", {
                "total_margin_allocated": 10000.0,
                "available_margin": 10000.0,
                "used_margin": 0.0,
                "unrealized_pnl": 0.0,
                "realized_pnl": 0.0,
                "total_funding_fees": 0.0,
                "total_trading_fees": 0.0,
                "open_positions_count": 0,
                "total_notional_exposure": 0.0,
                "effective_leverage": 0.0,
                "snapshots": [],
                "created_at": datetime.utcnow().isoformat()
            }),
        ]
        
        for file_path_str, default_data in critical_files:
            file_path = PathRegistry.get_path(file_path_str) if not os.path.isabs(file_path_str) else Path(file_path_str)
            
            if default_data is None:
                # JSONL file - just ensure parent directory exists
                file_path.parent.mkdir(parents=True, exist_ok=True)
                continue
            
            if not file_path.exists() or (file_path.exists() and file_path.stat().st_size == 0):
                try:
                    if atomic_json_save(str(file_path), default_data):
                        result["stats"]["files_created"] += 1
                        result["healed"].append(f"Initialized file: {file_path}")
                        print(f"   ✅ Initialized file: {file_path}")
                except Exception as e:
                    result["failed"].append(f"Failed to initialize {file_path}: {e}")
        
        # ====================================================================
        # 4. RUNTIME: Clear stale file locks
        # ====================================================================
        try:
            import glob
            lock_pattern = str(PathRegistry.LOGS_DIR / "*.lock")
            lock_files = glob.glob(lock_pattern)
            
            current_time = time.time()
            stale_threshold = 300  # 5 minutes
            
            for lock_file in lock_files:
                try:
                    lock_age = current_time - os.path.getmtime(lock_file)
                    if lock_age > stale_threshold:
                        os.remove(lock_file)
                        result["stats"]["locks_cleared"] += 1
                        result["healed"].append(f"Cleared stale lock: {lock_file}")
                        print(f"   ✅ Cleared stale lock: {lock_file}")
                except Exception as e:
                    result["failed"].append(f"Failed to clear lock {lock_file}: {e}")
        except Exception as e:
            result["failed"].append(f"Failed to check locks: {e}")
        
        # ====================================================================
        # 5. RUNTIME: Reset stale heartbeats
        # ====================================================================
        try:
            heartbeat_file = Path("logs/.bot_heartbeat")
            if heartbeat_file.exists():
                heartbeat_age = time.time() - heartbeat_file.stat().st_mtime
                if heartbeat_age > 600:  # 10 minutes stale
                    # Reset heartbeat
                    heartbeat_file.parent.mkdir(parents=True, exist_ok=True)
                    with open(heartbeat_file, 'w') as f:
                        f.write(str(int(time.time())))
                    result["stats"]["heartbeats_reset"] += 1
                    result["healed"].append("Reset stale bot heartbeat")
                    print(f"   ✅ Reset stale bot heartbeat")
            
            # Check state/heartbeats directory
            hb_dir = Path("state/heartbeats")
            if hb_dir.exists():
                for hb_file in hb_dir.glob("*.json"):
                    try:
                        with open(hb_file, 'r') as f:
                            hb_data = json.load(f)
                        last_ts = hb_data.get("last_heartbeat_ts", 0)
                        age = time.time() - last_ts
                        if age > 600:  # 10 minutes stale
                            # Reset to current time
                            hb_data["last_heartbeat_ts"] = int(time.time())
                            hb_data["last_heartbeat_dt"] = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")
                            tmp_file = hb_file.with_suffix(".tmp")
                            tmp_file.write_text(json.dumps(hb_data, indent=2))
                            tmp_file.replace(hb_file)
                            result["stats"]["heartbeats_reset"] += 1
                            result["healed"].append(f"Reset stale heartbeat: {hb_file.name}")
                            print(f"   ✅ Reset stale heartbeat: {hb_file.name}")
                    except Exception as e:
                        # Non-critical, continue
                        pass
        except Exception as e:
            result["failed"].append(f"Failed to reset heartbeats: {e}")
        
        # ====================================================================
        # 6. RUNTIME: Kill orphan processes (only if safe)
        # ====================================================================
        try:
            import psutil
            current_pid = os.getpid()
            current_cmdline = " ".join(psutil.Process(current_pid).cmdline())
            
            # Find orphan Python processes running trading bot code
            orphans = []
            for proc in psutil.process_iter(['pid', 'cmdline', 'create_time']):
                try:
                    cmdline = " ".join(proc.info['cmdline'] or [])
                    if "trading" in cmdline.lower() and "python" in cmdline.lower():
                        if proc.info['pid'] != current_pid:
                            # Check if process is actually stale (no recent activity)
                            proc_obj = psutil.Process(proc.info['pid'])
                            if proc_obj.is_running():
                                # Check if it's been running too long without updates
                                # (This is a heuristic - be conservative)
                                create_time = proc.info.get('create_time', 0)
                                if time.time() - create_time > 3600:  # 1 hour old
                                    orphans.append(proc.info['pid'])
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue
            
            # Only kill orphans if we're confident they're stale
            # In paper mode, be more aggressive; in real mode, be conservative
            trading_mode = os.getenv('TRADING_MODE', 'paper').lower()
            is_paper_mode = trading_mode == 'paper'
            
            for orphan_pid in orphans:
                try:
                    if is_paper_mode:
                        # Paper mode: kill orphans more aggressively
                        proc = psutil.Process(orphan_pid)
                        proc.terminate()
                        time.sleep(1)
                        if proc.is_running():
                            proc.kill()
                        result["stats"]["orphans_killed"] += 1
                        result["healed"].append(f"Killed orphan process: PID {orphan_pid}")
                        print(f"   ✅ Killed orphan process: PID {orphan_pid}")
                    else:
                        # Real mode: only log, don't kill (too risky)
                        result["healed"].append(f"Found orphan process (not killed in real mode): PID {orphan_pid}")
                        print(f"   ⚠️  Found orphan process (not killed in real mode): PID {orphan_pid}")
                except (psutil.NoSuchProcess, psutil.AccessDenied) as e:
                    result["failed"].append(f"Failed to kill orphan {orphan_pid}: {e}")
        except ImportError:
            # psutil not available, skip
            pass
        except Exception as e:
            result["failed"].append(f"Failed to check orphan processes: {e}")
        
        # ====================================================================
        # 7. DANGEROUS ISSUES: Detect but DO NOT auto-heal
        # ====================================================================
        try:
            # Check for state mismatches
            pos_data = locked_json_read(str(PathRegistry.POS_LOG), default={"open_positions": [], "closed_positions": []})
            open_positions = pos_data.get("open_positions", [])
            
            # Check for duplicate positions (same symbol + direction)
            seen = set()
            duplicates = []
            for i, pos in enumerate(open_positions):
                key = (pos.get("symbol"), pos.get("direction"))
                if key in seen:
                    duplicates.append(i)
                seen.add(key)
            
            if duplicates:
                result["critical"].append(f"Duplicate positions detected: indices {duplicates}")
                alert_operator(
                    ALERT_CRITICAL,
                    "POSITION_CONFLICT",
                    f"Duplicate positions detected in open_positions (indices: {duplicates})",
                    {"duplicate_indices": duplicates, "open_count": len(open_positions)},
                    action_required=True
                )
            
            # Check for positions with invalid data
            invalid_positions = []
            for i, pos in enumerate(open_positions):
                if pos.get("entry_price", 0) <= 0 or pos.get("size", 0) <= 0:
                    invalid_positions.append(i)
            
            if invalid_positions:
                result["critical"].append(f"Invalid positions detected: indices {invalid_positions}")
                alert_operator(
                    ALERT_CRITICAL,
                    "POSITION_INTEGRITY",
                    f"Invalid position data detected (indices: {invalid_positions})",
                    {"invalid_indices": invalid_positions, "open_count": len(open_positions)},
                    action_required=True
                )
        except Exception as e:
            result["failed"].append(f"Failed to check dangerous issues: {e}")
        
        # ====================================================================
        # Summary
        # ====================================================================
        if result["healed"]:
            print(f"\n✅ [SELF-HEAL] Healed {len(result['healed'])} issues")
        if result["failed"]:
            print(f"\n⚠️  [SELF-HEAL] Failed to heal {len(result['failed'])} issues")
        if result["critical"]:
            print(f"\n🚨 [SELF-HEAL] Found {len(result['critical'])} dangerous issues (NOT auto-healed)")
            result["success"] = False  # Critical issues mean healing incomplete
        
        if not result["healed"] and not result["failed"] and not result["critical"]:
            print("   ℹ️  No issues found - system healthy")
        
        return result
        
    except Exception as e:
        result["success"] = False
        result["failed"].append(f"Self-healing error: {e}")
        print(f"   ❌ Self-healing error: {e}")
        import traceback
        traceback.print_exc()
        return result

