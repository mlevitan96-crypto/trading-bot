"""
Signal quality tracking and analysis.
"""
import json
from pathlib import Path
from datetime import datetime
import pytz

SIGNAL_LOG_FILE = "logs/signal_quality.json"
ARIZONA_TZ = pytz.timezone('America/Phoenix')

def get_arizona_time():
    """Get current time in Arizona timezone."""
    return datetime.now(ARIZONA_TZ)

def initialize_signal_log():
    """Initialize signal quality log file."""
    Path("logs").mkdir(exist_ok=True)
    if not Path(SIGNAL_LOG_FILE).exists():
        log = {
            "signals": [],
            "created_at": get_arizona_time().isoformat()
        }
        with open(SIGNAL_LOG_FILE, 'w') as f:
            json.dump(log, f, indent=2)

def log_signal_quality(symbol, strategy, roi, volume, momentum, ema_gap):
    """
    Log signal quality metrics for analysis.
    
    Args:
        symbol: Trading pair
        strategy: Strategy name
        roi: Predicted ROI
        volume: Volume ratio (current / moving average)
        momentum: Price momentum
        ema_gap: Gap between fast and slow EMA
    """
    initialize_signal_log()
    
    try:
        with open(SIGNAL_LOG_FILE, 'r') as f:
            log = json.load(f)
        if not isinstance(log, dict) or "signals" not in log or not isinstance(log["signals"], list):
            raise ValueError("Invalid log format")
    except (json.JSONDecodeError, ValueError):
        log = {
            "signals": [],
            "created_at": get_arizona_time().isoformat()
        }
    
    signal = {
        "timestamp": get_arizona_time().isoformat(),
        "symbol": symbol,
        "strategy": strategy,
        "roi": round(roi, 6),
        "volume_ratio": round(volume, 4),
        "momentum": round(momentum, 6),
        "ema_gap": round(ema_gap, 6)
    }
    
    log["signals"].append(signal)
    
    # Keep last 500 signals
    if len(log["signals"]) > 500:
        log["signals"] = log["signals"][-500:]
    
    with open(SIGNAL_LOG_FILE, 'w') as f:
        json.dump(log, f, indent=2)

def get_signal_quality_stats(strategy=None, limit=100):
    """
    Get signal quality statistics.
    
    Args:
        strategy: Filter by strategy name (optional)
        limit: Number of recent signals to analyze
    
    Returns:
        Dict with statistics
    """
    if not Path(SIGNAL_LOG_FILE).exists():
        return {"error": "No signal data available"}
    
    with open(SIGNAL_LOG_FILE, 'r') as f:
        log = json.load(f)
    
    signals = log.get("signals", [])
    if strategy:
        signals = [s for s in signals if s["strategy"] == strategy]
    
    signals = signals[-limit:]
    
    if not signals:
        return {"error": "No signals found"}
    
    avg_roi = sum(s["roi"] for s in signals) / len(signals)
    avg_volume = sum(s["volume_ratio"] for s in signals) / len(signals)
    avg_momentum = sum(s["momentum"] for s in signals) / len(signals)
    
    return {
        "count": len(signals),
        "avg_roi": round(avg_roi, 6),
        "avg_volume_ratio": round(avg_volume, 4),
        "avg_momentum": round(avg_momentum, 6),
        "strategy": strategy or "all"
    }
