"""
Daily Statistics Tracker - Resets at midnight Phoenix time
Tracks combined spot + futures metrics for the current day
"""

import json
import math
import os
from datetime import datetime, time as datetime_time
import pytz

ARIZONA_TZ = pytz.timezone('America/Phoenix')


def _sanitize_numeric(value, default=0.0, field_name="unknown"):
    """Sanitize numeric values to prevent NaN/Inf from corrupting data."""
    if value is None:
        return default
    try:
        float_val = float(value)
        if math.isnan(float_val) or math.isinf(float_val):
            print(f"   ⚠️ [DAILY-STATS-SANITIZE] {field_name} was {value}, reset to {default}")
            return default
        return float_val
    except (TypeError, ValueError):
        return default


DAILY_STATS_FILE = os.path.join(os.path.dirname(os.path.dirname(__file__)), "logs", "daily_stats.json")


def get_arizona_time():
    """Get current time in Arizona timezone."""
    return datetime.now(ARIZONA_TZ)


def get_current_date_arizona():
    """Get current date in Arizona timezone (YYYY-MM-DD)."""
    return get_arizona_time().strftime("%Y-%m-%d")


def load_daily_stats():
    """Load daily stats from file."""
    try:
        with open(DAILY_STATS_FILE, "r") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return create_new_daily_stats()


def create_new_daily_stats():
    """Create new daily stats structure for current day."""
    return {
        "date": get_current_date_arizona(),
        "created_at": get_arizona_time().isoformat(),
        "spot": {
            "trades": 0,
            "wins": 0,
            "losses": 0,
            "total_pnl": 0.0,
            "starting_value": 0.0
        },
        "futures": {
            "trades": 0,
            "wins": 0,
            "losses": 0,
            "total_pnl": 0.0,
            "starting_margin": 0.0
        },
        "combined": {
            "trades": 0,
            "wins": 0,
            "losses": 0,
            "total_pnl": 0.0,
            "percent_pnl": 0.0
        }
    }


def save_daily_stats(stats):
    """Save daily stats to file with NaN protection."""
    # CRITICAL: Sanitize all numeric fields before saving
    for section in ["spot", "futures", "combined"]:
        if section in stats:
            for key in ["total_pnl", "percent_pnl", "starting_value", "starting_margin"]:
                if key in stats[section]:
                    stats[section][key] = _sanitize_numeric(
                        stats[section].get(key), 0.0, f"{section}.{key}"
                    )
    
    os.makedirs(os.path.dirname(DAILY_STATS_FILE), exist_ok=True)
    with open(DAILY_STATS_FILE, "w") as f:
        json.dump(stats, f, indent=2)


def check_and_reset_if_new_day():
    """Check if it's a new day and reset stats if needed."""
    from src.portfolio_tracker import load_portfolio
    from src.futures_portfolio_tracker import load_futures_portfolio
    
    stats = load_daily_stats()
    current_date = get_current_date_arizona()
    
    if stats.get("date") != current_date:
        # It's a new day - reset stats and capture starting values
        stats = create_new_daily_stats()
        
        # Set starting values from current portfolio states
        try:
            spot_portfolio = load_portfolio()
            stats["spot"]["starting_value"] = spot_portfolio.get("current_value", 10000.0)
        except:
            stats["spot"]["starting_value"] = 10000.0
        
        try:
            futures_portfolio = load_futures_portfolio()
            stats["futures"]["starting_margin"] = futures_portfolio.get("total_margin_allocated", 3000.0)
        except:
            stats["futures"]["starting_margin"] = 3000.0
        
        save_daily_stats(stats)
    
    # Ensure starting values are set (for first run)
    if stats["spot"]["starting_value"] == 0.0:
        try:
            spot_portfolio = load_portfolio()
            stats["spot"]["starting_value"] = spot_portfolio.get("current_value", 10000.0)
            save_daily_stats(stats)
        except:
            pass
    
    if stats["futures"]["starting_margin"] == 0.0:
        try:
            futures_portfolio = load_futures_portfolio()
            stats["futures"]["starting_margin"] = futures_portfolio.get("total_margin_allocated", 3000.0)
            save_daily_stats(stats)
        except:
            pass
    
    return stats


def record_spot_trade(pnl, is_win):
    """Record a spot trade completion."""
    stats = check_and_reset_if_new_day()
    
    stats["spot"]["trades"] += 1
    if is_win:
        stats["spot"]["wins"] += 1
    else:
        stats["spot"]["losses"] += 1
    stats["spot"]["total_pnl"] += pnl
    
    # Update combined
    stats["combined"]["trades"] = stats["spot"]["trades"] + stats["futures"]["trades"]
    stats["combined"]["wins"] = stats["spot"]["wins"] + stats["futures"]["wins"]
    stats["combined"]["losses"] = stats["spot"]["losses"] + stats["futures"]["losses"]
    stats["combined"]["total_pnl"] = stats["spot"]["total_pnl"] + stats["futures"]["total_pnl"]
    
    # Calculate percent P&L
    total_starting = stats["spot"]["starting_value"] + stats["futures"]["starting_margin"]
    if total_starting > 0:
        stats["combined"]["percent_pnl"] = (stats["combined"]["total_pnl"] / total_starting) * 100
    
    save_daily_stats(stats)


def record_futures_trade(pnl, is_win):
    """Record a futures trade completion."""
    stats = check_and_reset_if_new_day()
    
    stats["futures"]["trades"] += 1
    if is_win:
        stats["futures"]["wins"] += 1
    else:
        stats["futures"]["losses"] += 1
    stats["futures"]["total_pnl"] += pnl
    
    # Update combined
    stats["combined"]["trades"] = stats["spot"]["trades"] + stats["futures"]["trades"]
    stats["combined"]["wins"] = stats["spot"]["wins"] + stats["futures"]["wins"]
    stats["combined"]["losses"] = stats["spot"]["losses"] + stats["futures"]["losses"]
    stats["combined"]["total_pnl"] = stats["spot"]["total_pnl"] + stats["futures"]["total_pnl"]
    
    # Calculate percent P&L
    total_starting = stats["spot"]["starting_value"] + stats["futures"]["starting_margin"]
    if total_starting > 0:
        stats["combined"]["percent_pnl"] = (stats["combined"]["total_pnl"] / total_starting) * 100
    
    save_daily_stats(stats)


def update_starting_values(spot_value=None, futures_margin=None):
    """Update starting values for the day (called at midnight reset or first trade)."""
    stats = check_and_reset_if_new_day()
    
    if spot_value is not None:
        stats["spot"]["starting_value"] = spot_value
    if futures_margin is not None:
        stats["futures"]["starting_margin"] = futures_margin
    
    save_daily_stats(stats)


def get_daily_stats():
    """Get current daily stats."""
    stats = check_and_reset_if_new_day()
    return stats


def get_daily_summary():
    """Get formatted daily summary for dashboard display."""
    stats = get_daily_stats()
    
    return {
        "date": stats["date"],
        "trades": stats["combined"]["trades"],
        "wins": stats["combined"]["wins"],
        "losses": stats["combined"]["losses"],
        "total_pnl": round(stats["combined"]["total_pnl"], 2),
        "percent_pnl": round(stats["combined"]["percent_pnl"], 2),
        "win_rate": round((stats["combined"]["wins"] / stats["combined"]["trades"] * 100), 1) if stats["combined"]["trades"] > 0 else 0,
        "spot": {
            "trades": stats["spot"]["trades"],
            "wins": stats["spot"]["wins"],
            "losses": stats["spot"]["losses"],
            "pnl": round(stats["spot"]["total_pnl"], 2)
        },
        "futures": {
            "trades": stats["futures"]["trades"],
            "wins": stats["futures"]["wins"],
            "losses": stats["futures"]["losses"],
            "pnl": round(stats["futures"]["total_pnl"], 2)
        }
    }
