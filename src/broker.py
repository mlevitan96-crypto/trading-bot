import json
import os
from datetime import datetime
import pytz

ARIZONA_TZ = pytz.timezone('America/Phoenix')
MODE = os.getenv("TRADING_MODE", "paper")


def get_arizona_time():
    """Get current time in Arizona timezone."""
    return datetime.now(ARIZONA_TZ)


def place_order(asset, side, order_type, size):
    """
    Place an order through the broker.
    Uses unified venue enforcement to ensure ALL trades route to futures.
    Raises RuntimeError if venue is not futures.
    """
    from src.unified_venue_enforcement import route_order, get_venue
    
    venue = get_venue(asset)
    
    signal = {
        "symbol": asset,
        "side": side,
        "order_type": order_type,
        "size": size,
        "size_usd": size if isinstance(size, (int, float)) else 0,
        "venue": venue
    }
    
    try:
        enforced_signal = route_order(signal)
    except RuntimeError as e:
        print(f"❌ VENUE ENFORCEMENT FAILED: {e}")
        return None
    
    entry = {
        "timestamp": get_arizona_time().isoformat(),
        "symbol": asset,
        "asset": asset,
        "side": side,
        "type": order_type,
        "size": size,
        "mode": MODE,
        "venue": enforced_signal["venue"],
        "exchange": enforced_signal["exchange"]
    }
    
    log_file = "logs/broker_log.json"
    try:
        with open(log_file, "r") as f:
            logs = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        logs = []
    
    logs.append(entry)
    
    with open(log_file, "w") as f:
        json.dump(logs[-500:], f, indent=2)
    
    print(f"📝 Order: {side} {size} {asset} ({order_type}) [Mode: {MODE}, Venue: {enforced_signal['venue']}, Exchange: {enforced_signal['exchange']}]")
    
    return enforced_signal
