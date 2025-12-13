"""
Nightly Maintenance Integration
This module wires nightly_maintenance.py into your bot's governance scheduler so it runs
automatically at 2 AM Arizona time every day. It ensures the bot continuously learns and
optimizes without manual intervention.
"""

import time
import datetime
import subprocess
import json
import os

# --------------------------------------------------------------------------------------
# Helper: run nightly maintenance script
# --------------------------------------------------------------------------------------

def run_nightly_maintenance():
    """Execute the nightly maintenance script and log results."""
    now = int(time.time())
    try:
        print("\n" + "="*60)
        print("🌙 [NIGHTLY] Starting scheduled maintenance...")
        print(f"   Time: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')} Arizona")
        print("="*60)
        
        # Call the existing nightly maintenance script
        result = subprocess.run(
            ["python3", "nightly_maintenance.py"],
            capture_output=True, text=True, check=False
        )
        
        log_event = {
            "ts": now,
            "event": "nightly_maintenance_run",
            "returncode": result.returncode,
            "stdout": result.stdout.strip()[:500],  # Truncate for log size
            "stderr": result.stderr.strip()[:500]
        }
        
        # Append to unified events log
        events_log = "logs/unified_events.jsonl"
        os.makedirs(os.path.dirname(events_log), exist_ok=True)
        with open(events_log, "a") as f:
            f.write(json.dumps(log_event) + "\n")
        
        if result.returncode == 0:
            print(f"✅ [NIGHTLY] Maintenance completed successfully")
        else:
            print(f"⚠️  [NIGHTLY] Maintenance completed with warnings (code={result.returncode})")
            if result.stderr:
                print(f"   Error output: {result.stderr[:200]}")
        
        # Also log to dedicated maintenance log
        maintenance_log = "logs/nightly_maintenance_runs.jsonl"
        with open(maintenance_log, "a") as f:
            f.write(json.dumps({
                **log_event,
                "full_stdout": result.stdout,
                "full_stderr": result.stderr
            }) + "\n")
        
        print("="*60 + "\n")
        
        # Generate nightly learning report
        try:
            from src.nightly_report import generate_nightly_report
            generate_nightly_report()
        except Exception as report_err:
            print(f"⚠️  [NIGHTLY] Report generation failed: {report_err}")
        
        # Refresh coin preference tiers based on latest trade data
        try:
            from src.coin_preference_engine import refresh_coin_tiers
            refresh_coin_tiers()
            print("✅ [NIGHTLY] Coin preference tiers refreshed")
        except Exception as coin_err:
            print(f"⚠️  [NIGHTLY] Coin preference refresh failed: {coin_err}")
        
    except Exception as e:
        error_event = {
            "ts": now,
            "event": "nightly_maintenance_error",
            "err": str(e)
        }
        
        events_log = "logs/unified_events.jsonl"
        os.makedirs(os.path.dirname(events_log), exist_ok=True)
        with open(events_log, "a") as f:
            f.write(json.dumps(error_event) + "\n")
        
        print(f"❌ [NIGHTLY] Error running nightly maintenance: {e}")
        import traceback
        traceback.print_exc()

# --------------------------------------------------------------------------------------
# Scheduler: run at 2 AM Arizona time daily
# --------------------------------------------------------------------------------------

_last_run_date = None

def nightly_check():
    """
    Check if it's 2 AM Arizona time and run maintenance if so.
    Uses _last_run_date to ensure it only runs once per day.
    """
    global _last_run_date
    
    # Get current Arizona local time (MST, UTC-7)
    arizona_tz = datetime.timezone(datetime.timedelta(hours=-7))
    now = datetime.datetime.now(arizona_tz)
    
    current_date = now.date()
    
    # Run if it's 2 AM and we haven't run today yet
    if now.hour == 2 and now.minute < 10 and _last_run_date != current_date:
        _last_run_date = current_date
        run_nightly_maintenance()
        print(f"[NIGHTLY] Next run scheduled for 2 AM on {current_date + datetime.timedelta(days=1)}")

def register_nightly_governance(register_periodic_task):
    """
    Register the nightly maintenance task with the bot's periodic scheduler.
    Checks every 10 minutes if it's time to run (2 AM Arizona time).
    
    Args:
        register_periodic_task: Function that accepts (task_fn, interval_sec)
    """
    print("🌙 [NIGHTLY] Registering nightly maintenance scheduler...")
    
    # Check every 10 minutes (600 seconds)
    # This is frequent enough to catch the 2 AM window
    register_periodic_task(nightly_check, interval_sec=600)
    
    print("✅ [NIGHTLY] Scheduler registered")
    print("   ℹ️  Daily maintenance will run at 2 AM Arizona time")
    print("   ℹ️  Tasks: Auto-tune thresholds, recalculate risk budgets, persist attribution")
    print("   ℹ️  Weekly (Mon): Strategy pruning and rebalancing")
    print("   ℹ️  Monthly (1st): Shadow experiment promotion")
