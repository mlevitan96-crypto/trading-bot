import json
import os
from datetime import datetime, timedelta
import pytz


COOLDOWN_FILE = "logs/trade_cooldown.json"
COOLDOWN_MINUTES = 5
MIN_ROI_THRESHOLD = 0.0005  # Lowered for paper mode learning


def get_arizona_now():
    """Get current time in Arizona timezone"""
    arizona_tz = pytz.timezone("America/Phoenix")
    return datetime.now(arizona_tz)


def load_cooldowns():
    """Load cooldown data from file"""
    if not os.path.exists(COOLDOWN_FILE):
        return {}
    
    try:
        with open(COOLDOWN_FILE, "r") as f:
            data = json.load(f)
            for symbol in data:
                data[symbol] = datetime.fromisoformat(data[symbol])
            return data
    except:
        return {}


def save_cooldowns(cooldowns):
    """Save cooldown data to file"""
    os.makedirs("logs", exist_ok=True)
    data = {symbol: dt.isoformat() for symbol, dt in cooldowns.items()}
    with open(COOLDOWN_FILE, "w") as f:
        json.dump(data, f, indent=2)


def can_trade(symbol):
    """
    Check if enough time has passed since last trade.
    Returns (can_trade, reason)
    """
    cooldowns = load_cooldowns()
    
    if symbol not in cooldowns:
        return True, "No previous trade"
    
    last_trade_time = cooldowns[symbol]
    now = get_arizona_now()
    time_diff = now - last_trade_time
    
    if time_diff < timedelta(minutes=COOLDOWN_MINUTES):
        remaining = COOLDOWN_MINUTES - (time_diff.total_seconds() / 60)
        return False, f"Cooldown: {remaining:.1f}min remaining"
    
    return True, f"Cooldown expired ({time_diff.total_seconds() / 60:.1f}min ago)"


def check_roi_threshold(roi):
    """
    Check if ROI meets minimum threshold to justify trading fees.
    Returns (passes, reason)
    """
    if roi < MIN_ROI_THRESHOLD:
        return False, f"ROI {roi:.4f} < minimum {MIN_ROI_THRESHOLD}"
    return True, f"ROI {roi:.4f} passes threshold"


def record_trade_time(symbol):
    """Record the current time as last trade time for symbol"""
    cooldowns = load_cooldowns()
    cooldowns[symbol] = get_arizona_now()
    save_cooldowns(cooldowns)


def should_execute_trade(symbol, roi):
    """
    Combined check for both cooldown and ROI threshold.
    Returns (should_trade, reason)
    """
    can_trade_now, cooldown_reason = can_trade(symbol)
    if not can_trade_now:
        return False, cooldown_reason
    
    roi_passes, roi_reason = check_roi_threshold(roi)
    if not roi_passes:
        return False, roi_reason
    
    return True, "Trade approved"
