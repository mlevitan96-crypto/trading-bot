import json
import os
from datetime import datetime
import pytz
from src.volatility_monitor import detect_volatility_spike
from src.infrastructure.path_registry import PathRegistry

ARIZONA_TZ = pytz.timezone('America/Phoenix')


def get_arizona_time():
    """Get current time in Arizona timezone."""
    return datetime.now(ARIZONA_TZ)


def log_protective_event(df):
    """
    Log protective mode events to JSON file.
    Returns the volatility status.
    """
    status = detect_volatility_spike(df)
    entry = {
        "timestamp": get_arizona_time().isoformat(),
        **status
    }
    
    log_file = str(PathRegistry.PROTECTIVE_MODE_LOG)
    try:
        with open(log_file, "r") as f:
            logs = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        logs = []
    
    logs.append(entry)
    
    with open(log_file, "w") as f:
        json.dump(logs[-500:], f, indent=2)
    
    return status
