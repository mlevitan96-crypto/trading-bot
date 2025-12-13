import json
from datetime import datetime
import pytz
from src.regime_predictor import predict_next_regime
from src.volatility_monitor import detect_volatility_spike

ARIZONA_TZ = pytz.timezone('America/Phoenix')


def get_arizona_time():
    """Get current time in Arizona timezone."""
    return datetime.now(ARIZONA_TZ)


def log_reentry_event(df, assets):
    """
    Log re-entry events with regime and volatility data.
    """
    entry = {
        "timestamp": get_arizona_time().isoformat(),
        "regime": predict_next_regime(),
        **detect_volatility_spike(df),
        "assets_reentered": assets,
        "action": "reentry"
    }
    
    log_file = "logs/reentry_log.json"
    try:
        with open(log_file, "r") as f:
            logs = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        logs = []
    
    logs.append(entry)
    
    with open(log_file, "w") as f:
        json.dump(logs[-500:], f, indent=2)
