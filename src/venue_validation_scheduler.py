"""
Venue Symbol Validation Scheduler - Runs validation daily at 4 AM UTC.
"""

import os
import time
from datetime import datetime
from typing import Optional

from src.venue_symbol_validator import validate_venue_symbols


# Last validation timestamp (track to avoid running multiple times per day)
_last_validation_date = None


def daily_validation_check():
    """
    Check if it's time to run daily validation (4 AM UTC).
    Runs validation if:
    - Current hour is 4 AM UTC (or within 1 hour window)
    - Haven't run validation today
    """
    global _last_validation_date
    
    now_utc = datetime.utcnow()
    current_hour = now_utc.hour
    current_date = now_utc.date()
    
    # Check if we should run (4 AM UTC window: 3:00-4:59)
    should_run = (current_hour >= 3 and current_hour < 5)
    
    # Check if we've already run today
    if _last_validation_date == current_date:
        return  # Already ran today
    
    if should_run:
        exchange = os.getenv("EXCHANGE", "blofin").lower()
        if exchange == "kraken":
            print(f"\n🔍 [VALIDATION] Running daily venue symbol validation (4 AM UTC)...")
            try:
                results = validate_venue_symbols(update_config=False)
                suppressed = results.get("summary", {}).get("suppressed", 0)
                if suppressed > 0:
                    print(f"⚠️  [VALIDATION] {suppressed} symbols failed validation")
                else:
                    print("✅ [VALIDATION] All symbols validated successfully")
                _last_validation_date = current_date
            except Exception as e:
                print(f"⚠️  [VALIDATION] Daily validation error: {e}")
        else:
            # Not using Kraken, skip
            pass


def register_daily_validation(register_periodic_task):
    """
    Register daily validation task with periodic scheduler.
    
    Args:
        register_periodic_task: Function that accepts (task_fn, interval_sec)
    """
    # Check every 30 minutes to catch 4 AM UTC window
    register_periodic_task(daily_validation_check, interval_sec=30 * 60)
    print("✅ [VALIDATION] Daily validation scheduler registered (4 AM UTC)")


def exchange_health_check():
    """
    Periodic exchange health check (runs every 5 minutes).
    """
    try:
        from src.exchange_health_monitor import check_exchange_health
        state = check_exchange_health()
        
        if state.get("status") == "degraded":
            print(f"🚨 [EXCHANGE-HEALTH] Exchange is DEGRADED ({state.get('consecutive_failures')} consecutive failures)")
    except Exception as e:
        print(f"⚠️ [EXCHANGE-HEALTH] Health check error: {e}")


def register_exchange_health_monitor(register_periodic_task):
    """
    Register exchange health monitoring task.
    
    Args:
        register_periodic_task: Function that accepts (task_fn, interval_sec)
    """
    # Check every 5 minutes
    register_periodic_task(exchange_health_check, interval_sec=5 * 60)
    print("✅ [EXCHANGE-HEALTH] Exchange health monitor registered (5min interval)")
