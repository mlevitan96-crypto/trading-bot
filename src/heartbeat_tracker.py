"""
Heartbeat Tracker: Write heartbeats for critical subsystems
Governance Sentinel monitors these to detect stale/failed components
"""

import json
import time
from pathlib import Path
from datetime import datetime
from typing import Dict, Any


HEARTBEATS_DIR = Path("state/heartbeats")
HEARTBEATS_DIR.mkdir(parents=True, exist_ok=True)


def write_heartbeat(component_name: str, metadata: Dict[str, Any] = None):
    """
    Write heartbeat for a component.
    
    Args:
        component_name: Name of the component (e.g., "bot_cycle", "position_manager")
        metadata: Optional metadata to include (e.g., {"positions": 3, "portfolio_value": 10500})
    """
    heartbeat_file = HEARTBEATS_DIR / f"{component_name}.json"
    
    heartbeat_data = {
        "component": component_name,
        "last_heartbeat_ts": int(time.time()),
        "last_heartbeat_dt": datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC"),
        "metadata": metadata or {}
    }
    
    # Atomic write
    tmp_file = heartbeat_file.with_suffix(".tmp")
    tmp_file.write_text(json.dumps(heartbeat_data, indent=2))
    tmp_file.replace(heartbeat_file)


def read_heartbeat(component_name: str) -> Dict[str, Any]:
    """Read last heartbeat for a component"""
    heartbeat_file = HEARTBEATS_DIR / f"{component_name}.json"
    
    if not heartbeat_file.exists():
        return {}
    
    try:
        return json.loads(heartbeat_file.read_text())
    except Exception:
        return {}


def is_component_alive(component_name: str, stale_seconds: int = 300) -> bool:
    """
    Check if component is alive (heartbeat recent).
    
    Args:
        component_name: Component to check
        stale_seconds: Max age before considering stale (default 5 minutes)
    
    Returns:
        True if component is alive, False if stale/missing
    """
    hb = read_heartbeat(component_name)
    
    if not hb:
        return False
    
    last_ts = hb.get("last_heartbeat_ts", 0)
    age = int(time.time()) - int(last_ts)
    
    return age < stale_seconds
