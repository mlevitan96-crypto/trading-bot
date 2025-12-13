import json
import pandas as pd
from src.volatility_monitor import detect_volatility_spike


def validate_signals(df):
    """
    Validate trading signals based on recent performance.
    Returns dict of strategy -> valid/suppressed status.
    Bootstrap mode: returns all valid when no history exists.
    """
    log_file = "logs/strategy_attribution_log.json"
    try:
        with open(log_file, "r") as f:
            logs = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        logs = []
    
    recent = logs[-100:]
    
    if not recent:
        return {
            "Trend-Conservative": "valid",
            "Breakout-Aggressive": "valid",
            "Sentiment-Fusion": "valid"
        }
    
    df_logs = pd.DataFrame(recent)
    grouped = df_logs.groupby("strategy")["roi"].mean()
    
    volatility = detect_volatility_spike(df)
    
    valid = {}
    all_strategies = ["Trend-Conservative", "Breakout-Aggressive", "Sentiment-Fusion"]
    
    for tag in all_strategies:
        if tag in grouped.index:
            avg_roi = grouped[tag]
            if avg_roi < 0.005:
                valid[tag] = "suppressed"
            elif volatility["action"] == "protect" and tag == "Sentiment-Fusion":
                valid[tag] = "suppressed"
            else:
                valid[tag] = "valid"
        else:
            valid[tag] = "valid"
    
    return valid
