import json
from datetime import datetime
import pytz

ARIZONA_TZ = pytz.timezone('America/Phoenix')


def get_arizona_time():
    """Get current time in Arizona timezone."""
    return datetime.now(ARIZONA_TZ)


def log_rotation_event(df):
    """
    Log rotation events to JSON file.
    """
    entry = {
        "timestamp": get_arizona_time().isoformat(),
        "event": "rotation"
    }
    
    log_file = "logs/rotation_log.json"
    try:
        with open(log_file, "r") as f:
            logs = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        logs = []
    
    logs.append(entry)
    
    with open(log_file, "w") as f:
        json.dump(logs[-500:], f, indent=2)
