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

