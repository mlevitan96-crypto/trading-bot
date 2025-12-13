import time
import traceback
import os
import threading
from src.bot_cycle import run_bot_cycle
from src.full_integration_blofin_micro_live_and_paper import start_scheduler, set_paper_mode


def bootstrap_services():
    """
    Bootstrap V6.6/V7.1 governance services:
      - Fee audits + recovery every 10 minutes
      - Nightly digest + desk-grade analysis at 07:00 UTC
    """
    print("🔧 [V6.6/V7.1] Starting unified scheduler...")
    set_paper_mode(True)  # Default to paper mode for safety
    scheduler_thread = threading.Thread(target=lambda: start_scheduler(interval_secs=600), daemon=True)
    scheduler_thread.start()
    print("✅ [V6.6/V7.1] Scheduler active (10-min audits + nightly digest)")


def watchdog_loop():
    """
    Watchdog loop with automatic error recovery.
    Runs the bot cycle continuously with 60-second intervals.
    """
    print("🟢 Crypto Trading Bot Started")
    print(f"📍 Trading Mode: {os.getenv('TRADING_MODE', 'paper')}")
    print("⏱️  Cycle Interval: 60 seconds\n")
    
    # Bootstrap V6.6/V7.1 services before starting main loop
    bootstrap_services()
    
    while True:
        try:
            run_bot_cycle()
        except Exception as e:
            print("\n🔴 Bot cycle failed:")
            print(traceback.format_exc())
            print("\n🛠️  Restarting bot cycle in 10 seconds...")
            time.sleep(10)
        
        time.sleep(60)


if __name__ == "__main__":
    watchdog_loop()
