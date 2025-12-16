#!/usr/bin/env python3
"""
Fix health checks to be more lenient for newly started bots
"""
import os
import time
from pathlib import Path

# Update signal_integrity.py to check if bot just started
def update_signal_integrity():
    """Make signal integrity checks more lenient"""
    file_path = Path("src/signal_integrity.py")
    content = file_path.read_text()
    
    # Check if already updated
    if "bot_startup_time" in content:
        print("✅ signal_integrity.py already updated")
        return
    
    # Find the get_status function and update it
    old_check = """            # Check file age (should be updated within last 10 minutes)
            file_age = time.time() - signal_file.stat().st_mtime
            if file_age > 600:  # 10 minutes
                all_recent = False"""
    
    new_check = """            # Check file age (should be updated within last 10 minutes)
            # But be lenient if bot just started (within last hour)
            file_age = time.time() - signal_file.stat().st_mtime
            bot_startup_time = os.path.getenv("BOT_STARTUP_TIME", "0")
            bot_age = time.time() - float(bot_startup_time) if bot_startup_time != "0" else 3600
            
            # If bot started less than 1 hour ago, allow files up to 30 minutes old
            max_age = 600 if bot_age > 3600 else 1800  # 10 min normally, 30 min if just started
            if file_age > max_age:
                all_recent = False"""
    
    if old_check in content:
        content = content.replace(old_check, new_check)
        file_path.write_text(content)
        print("✅ Updated signal_integrity.py")
    else:
        print("⚠️  Could not find exact pattern to replace in signal_integrity.py")

if __name__ == "__main__":
    update_signal_integrity()

