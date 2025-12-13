"""
Signal Activity Logger - Tracks all signal evaluations (executed + blocked)
"""
import json
from pathlib import Path
from datetime import datetime
import pytz

SIGNAL_LOG_FILE = "logs/signal_activity.json"
ARIZONA_TZ = pytz.timezone('America/Phoenix')
MAX_SIGNALS = 100  # Keep last 100 signals


def get_arizona_time():
    """Get current time in Arizona timezone."""
    return datetime.now(ARIZONA_TZ)


def initialize_signal_log():
    """Initialize signal activity log file."""
    Path("logs").mkdir(exist_ok=True)
    if not Path(SIGNAL_LOG_FILE).exists():
        data = {
            "signals": [],
            "created_at": get_arizona_time().isoformat()
        }
        with open(SIGNAL_LOG_FILE, 'w') as f:
            json.dump(data, f, indent=2)


def log_signal_evaluation(symbol, strategy, status, roi, details=None):
    """
    Log a signal evaluation (executed or blocked).
    
    Args:
        symbol: Trading pair (e.g., 'BTCUSDT')
        strategy: Strategy name
        status: 'executed', 'blocked_roi', 'blocked_volume', 'blocked_mtf', 
                'blocked_ensemble', 'blocked_cooldown', 'blocked_correlation', 'no_signal'
        roi: Expected ROI (float)
        details: Dict with additional info (volume_boost, reason, ensemble_score, etc.)
    """
    from src.file_locks import locked_json_read, atomic_json_save
    
    initialize_signal_log()
    
    signal_entry = {
        "timestamp": get_arizona_time().isoformat(),
        "symbol": symbol,
        "strategy": strategy,
        "status": status,
        "roi": round(roi * 100, 2) if roi else 0,
        "details": details or {}
    }
    
    try:
        data = locked_json_read(SIGNAL_LOG_FILE, default={"signals": [], "last_updated": ""})
        
        if "signals" not in data:
            data = {"signals": [], "last_updated": ""}
        
        data["signals"].insert(0, signal_entry)
        data["signals"] = data["signals"][:MAX_SIGNALS]
        data["last_updated"] = get_arizona_time().isoformat()
        
        atomic_json_save(SIGNAL_LOG_FILE, data)
            
    except Exception as e:
        pass


def get_recent_signals(limit=20):
    """Get the most recent signal evaluations."""
    initialize_signal_log()
    
    try:
        with open(SIGNAL_LOG_FILE, 'r') as f:
            data = json.load(f)
        return data["signals"][:limit]
    except Exception as e:
        print(f"⚠️ Error reading signals: {e}")
        return []


def get_signal_summary():
    """Get summary statistics for recent signals."""
    signals = get_recent_signals(limit=50)
    
    if not signals:
        return {
            "total_signals": 0,
            "executed": 0,
            "blocked": 0,
            "execution_rate": 0,
            "top_blocking_reason": "N/A"
        }
    
    executed = sum(1 for s in signals if s["status"] == "executed")
    blocked = sum(1 for s in signals if s["status"].startswith("blocked"))
    
    # Count blocking reasons
    blocking_reasons = {}
    for s in signals:
        if s["status"].startswith("blocked"):
            reason = s["status"].replace("blocked_", "")
            blocking_reasons[reason] = blocking_reasons.get(reason, 0) + 1
    
    top_reason = max(blocking_reasons.items(), key=lambda x: x[1])[0] if blocking_reasons else "N/A"
    
    return {
        "total_signals": len(signals),
        "executed": executed,
        "blocked": blocked,
        "execution_rate": round((executed / len(signals)) * 100, 1) if signals else 0,
        "top_blocking_reason": top_reason,
        "blocking_breakdown": blocking_reasons
    }
