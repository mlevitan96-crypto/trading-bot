import json
from datetime import datetime
from src.capital_allocator import allocate_capital
from src.regime_predictor import predict_next_regime


def activate_strategies():
    """
    Activate strategies based on capital allocation.
    Returns dict of strategy -> active/inactive status.
    """
    allocation = allocate_capital()
    regime = predict_next_regime()
    
    activation = {
        tag: "active" if capital >= 500 else "inactive"
        for tag, capital in allocation.items()
    }
    
    entry = {
        "timestamp": datetime.utcnow().isoformat(),
        "regime": regime,
        "activation": activation
    }
    
    log_file = "logs/strategy_activation_log.json"
    try:
        with open(log_file, "r") as f:
            logs = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        logs = []
    
    logs.append(entry)
    
    with open(log_file, "w") as f:
        json.dump(logs[-500:], f, indent=2)
    
    return activation
