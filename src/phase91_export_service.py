"""
Phase 9.1 Export Service
Centralized data aggregation for Phase 9.1 export endpoints.
Composes telemetry from Phase 9.1, Phase 9, Phase 8.4, and Phase 8.7.
"""

import os
import json
import time
from typing import Dict, List, Optional

LOGS_DIR = "logs"
GOVERNANCE_LOG = os.path.join(LOGS_DIR, "phase91_governance.jsonl")
CALIBRATION_LOG = os.path.join(LOGS_DIR, "phase91_calibration.jsonl")
AUDIT_CHAIN_LOG = os.path.join(LOGS_DIR, "audit_chain.jsonl")

# ==============================
# Log Writers
# ==============================

def log_governance_event(event: dict):
    """Append governance event (ramp/shrink) to JSONL log."""
    try:
        os.makedirs(LOGS_DIR, exist_ok=True)
        with open(GOVERNANCE_LOG, "a") as f:
            f.write(json.dumps(event) + "\n")
    except Exception as e:
        print(f"⚠️  Phase 9.1 Export: Failed to log governance event: {e}")

def log_calibration_event(event: dict):
    """Append calibration event to JSONL log."""
    try:
        os.makedirs(LOGS_DIR, exist_ok=True)
        with open(CALIBRATION_LOG, "a") as f:
            f.write(json.dumps(event) + "\n")
    except Exception as e:
        print(f"⚠️  Phase 9.1 Export: Failed to log calibration event: {e}")

# ==============================
# Log Readers
# ==============================

def read_jsonl_log(filepath: str, since: Optional[int] = None) -> List[dict]:
    """Read JSONL log file with optional time filter."""
    if not os.path.exists(filepath):
        return []
    
    events = []
    try:
        with open(filepath, "r") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                event = json.loads(line)
                if since is None or event.get("ts", 0) >= since:
                    events.append(event)
    except Exception as e:
        print(f"⚠️  Phase 9.1 Export: Failed to read {filepath}: {e}")
    
    return events

def get_governance_events(since: Optional[int] = None) -> List[dict]:
    """Get governance events (ramps/shrinks) with optional time filter."""
    return read_jsonl_log(GOVERNANCE_LOG, since)

def get_calibration_events(since: Optional[int] = None) -> List[dict]:
    """Get calibration events with optional time filter."""
    return read_jsonl_log(CALIBRATION_LOG, since)

def get_audit_events(since: Optional[int] = None) -> List[dict]:
    """Get Phase 8.7 audit events with optional time filter."""
    return read_jsonl_log(AUDIT_CHAIN_LOG, since)

# ==============================
# Health Export
# ==============================

def export_health() -> dict:
    """
    Export current health data: composite score, trends, subsystem status.
    Returns:
        {
            "current": float,
            "avg_1h": float,
            "avg_6h": float,
            "avg_24h": float,
            "subsystems": {
                "validation_suite": "ok|warning|error",
                "drift_detector": "ok|warning|error",
                ...
            }
        }
    """
    try:
        from src.phase9_autonomy import composite_health
        from src.phase91_adaptive_governance import _health_history, _phase91_lock
        
        current_health = composite_health()
        
        # Calculate averages from health history
        with _phase91_lock:
            history = list(_health_history)
        
        if len(history) >= 60:
            avg_1h = sum(history[-60:]) / 60
        else:
            avg_1h = sum(history) / len(history) if history else current_health
        
        if len(history) >= 360:
            avg_6h = sum(history[-360:]) / 360
        else:
            avg_6h = sum(history) / len(history) if history else current_health
        
        avg_24h = sum(history) / len(history) if history else current_health
        
        # Get subsystem status from Phase 9 watchdog
        subsystems = get_subsystem_health()
        
        return {
            "current": round(current_health, 3),
            "avg_1h": round(avg_1h, 3),
            "avg_6h": round(avg_6h, 3),
            "avg_24h": round(avg_24h, 3),
            "subsystems": subsystems
        }
    except Exception as e:
        print(f"⚠️  Phase 9.1 Export: Health export failed: {e}")
        return {
            "current": 0.0,
            "avg_1h": 0.0,
            "avg_6h": 0.0,
            "avg_24h": 0.0,
            "subsystems": {}
        }

def get_subsystem_health() -> Dict[str, str]:
    """Get Phase 9 subsystem health status."""
    try:
        from src.phase9_autonomy import get_phase9_status
        status = get_phase9_status()
        
        # Map subsystem heartbeats to health status
        subsystems = {}
        for subsystem, data in status.get("subsystem_health", {}).items():
            missed = data.get("missed", 0)
            if missed == 0:
                subsystems[subsystem] = "ok"
            elif missed <= 2:
                subsystems[subsystem] = "warning"
            else:
                subsystems[subsystem] = "error"
        
        return subsystems
    except Exception as e:
        print(f"⚠️  Phase 9.1 Export: Subsystem health failed: {e}")
        return {}

# ==============================
# Tolerances Export
# ==============================

def export_tolerances() -> dict:
    """
    Export current drift tolerances and volatility index.
    Returns:
        {
            "ev_usd": float,
            "trailing_r": float,
            "add_r": float,
            "vol_index": float,
            "last_update_ts": int
        }
    """
    try:
        from src.phase91_adaptive_governance import _current_tolerances, _last_tolerance_update_ts, _phase91_lock
        from src.phase91_hooks import realized_volatility_index_1h
        
        with _phase91_lock:
            tolerances = _current_tolerances.copy()
            last_update = _last_tolerance_update_ts
        
        vol_index = realized_volatility_index_1h() or 0.5
        
        return {
            **tolerances,
            "vol_index": round(vol_index, 3),
            "last_update_ts": int(last_update)
        }
    except Exception as e:
        print(f"⚠️  Phase 9.1 Export: Tolerances export failed: {e}")
        return {
            "ev_usd": 0.02,
            "trailing_r": 0.05,
            "add_r": 0.10,
            "vol_index": 0.5,
            "last_update_ts": 0
        }

# ==============================
# Attribution Export
# ==============================

def export_attribution() -> dict:
    """
    Export per-symbol and per-tier attribution data.
    Returns:
        {
            "per_symbol": {"BTCUSDT": 120.5, ...},
            "per_tier": {"majors": 75.3, ...},
            "sharpe": float,
            "sortino": float
        }
    """
    try:
        from src.phase84_86_expansion import get_live_attribution
        
        attrib = get_live_attribution()
        
        return {
            "per_symbol": attrib.get("per_symbol", {}),
            "per_tier": attrib.get("per_tier", {}),
            "sharpe": attrib.get("sharpe", 0.0),
            "sortino": attrib.get("sortino", 0.0)
        }
    except Exception as e:
        print(f"⚠️  Phase 9.1 Export: Attribution export failed: {e}")
        return {
            "per_symbol": {},
            "per_tier": {},
            "sharpe": 0.0,
            "sortino": 0.0
        }

# ==============================
# Initialization
# ==============================

def initialize_phase91_exports():
    """Initialize export service (ensure log directories exist)."""
    os.makedirs(LOGS_DIR, exist_ok=True)
    print("✅ Phase 9.1 Export Service initialized")
