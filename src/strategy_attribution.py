import json
from datetime import datetime
from src.regime_predictor import predict_next_regime
from src.volatility_monitor import detect_volatility_spike


def log_strategy_performance(df, strategy_tag, roi):
    """
    Log strategy performance with regime and volatility context.
    """
    entry = {
        "timestamp": datetime.utcnow().isoformat(),
        "strategy": strategy_tag,
        "roi": roi,
        "regime": predict_next_regime(),
        **detect_volatility_spike(df)
    }
    
    log_file = "logs/strategy_attribution_log.json"
    try:
        with open(log_file, "r") as f:
            logs = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        logs = []
    
    logs.append(entry)
    
    with open(log_file, "w") as f:
        json.dump(logs[-1000:], f, indent=2)
