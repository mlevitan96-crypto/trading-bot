import json
import pandas as pd


def tune_signal_threshold():
    """
    Dynamically tune signal thresholds based on recent performance.
    Returns optimized threshold value.
    """
    log_file = "logs/strategy_attribution_log.json"
    try:
        with open(log_file, "r") as f:
            logs = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        logs = []
    
    if not logs:
        return 0.01
    
    df = pd.DataFrame(logs[-100:])
    avg_roi = df["roi"].mean()
    spike_rate = df["vol_spike"].sum() / len(df)
    
    if spike_rate > 0.3:
        return 0.015 if avg_roi < 0.01 else 0.01
    else:
        return 0.01 if avg_roi < 0.01 else 0.005
