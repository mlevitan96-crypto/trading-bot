#!/usr/bin/env python3
"""
Check Trading Status Script
============================
Checks if the bot is set up to trade during golden hours:
1. Verifies bot is running (systemd service)
2. Checks current time vs golden hours (09:00-16:00 UTC)
3. Verifies golden hour check is implemented
4. Shows next golden hour window
"""

import os
import sys
from pathlib import Path
from datetime import datetime, timezone

# Add project root to path
script_dir = Path(__file__).parent.absolute()
project_root = script_dir.parent
sys.path.insert(0, str(project_root))

try:
    from src.enhanced_trade_logging import is_golden_hour, check_golden_hours_block
except ImportError as e:
    print(f"[ERROR] Failed to import enhanced_trade_logging: {e}")
    sys.exit(1)


def check_systemd_service():
    """Check if tradingbot service is running."""
    import subprocess
    try:
        result = subprocess.run(
            ["systemctl", "is-active", "tradingbot"],
            capture_output=True,
            text=True,
            timeout=5
        )
        return result.stdout.strip() == "active"
    except:
        return None


def get_next_golden_hour():
    """Calculate next golden hour window."""
    now = datetime.now(timezone.utc)
    current_hour = now.hour
    
    if 9 <= current_hour < 16:
        # Currently in golden hours
        next_start = now.replace(hour=9, minute=0, second=0, microsecond=0)
        if current_hour >= 9:
            # Next window is tomorrow
            from datetime import timedelta
            next_start = next_start + timedelta(days=1)
        return next_start, "NOW"
    else:
        # Not in golden hours - find next window
        if current_hour < 9:
            # Today's window hasn't started
            next_start = now.replace(hour=9, minute=0, second=0, microsecond=0)
        else:
            # Today's window has passed, next is tomorrow
            from datetime import timedelta
            next_start = (now + timedelta(days=1)).replace(hour=9, minute=0, second=0, microsecond=0)
        return next_start, "UPCOMING"


def main():
    """Main status check."""
    print("=" * 70)
    print("Trading Status Check")
    print("=" * 70)
    
    # 1. Check systemd service
    print("\n[1] System Service Status:")
    service_status = check_systemd_service()
    if service_status is True:
        print("    [OK] tradingbot service is ACTIVE")
    elif service_status is False:
        print("    [WARN] tradingbot service is INACTIVE")
    else:
        print("    [INFO] Could not check service status (may not be systemd)")
    
    # 2. Check current time and golden hours
    print("\n[2] Golden Hour Status:")
    now = datetime.now(timezone.utc)
    current_hour = now.hour
    is_golden = is_golden_hour()
    
    print(f"    Current UTC time: {now.strftime('%Y-%m-%d %H:%M:%S UTC')}")
    print(f"    Current UTC hour: {current_hour}")
    print(f"    Golden hours: 09:00-16:00 UTC")
    print(f"    Status: {'[IN GOLDEN HOURS]' if is_golden else '[OUTSIDE GOLDEN HOURS]'}")
    
    # 3. Test golden hour check
    print("\n[3] Golden Hour Check Implementation:")
    try:
        should_block, reason = check_golden_hours_block()
        if should_block:
            print(f"    [BLOCKING] {reason}")
        else:
            print("    [ALLOWING] Trades are allowed (within golden hours)")
    except Exception as e:
        print(f"    [ERROR] Check failed: {e}")
    
    # 4. Next golden hour window
    print("\n[4] Next Golden Hour Window:")
    next_start, status = get_next_golden_hour()
    next_end = next_start.replace(hour=16, minute=0)
    time_until = next_start - now
    
    if status == "NOW":
        print(f"    [ACTIVE] Currently in golden hours")
        print(f"    Window ends: {next_end.strftime('%Y-%m-%d %H:%M:%S UTC')}")
        hours_remaining = (next_end - now).total_seconds() / 3600
        print(f"    Time remaining: {hours_remaining:.1f} hours")
    else:
        print(f"    [UPCOMING] Next window starts: {next_start.strftime('%Y-%m-%d %H:%M:%S UTC')}")
        print(f"    Window ends: {next_end.strftime('%Y-%m-%d %H:%M:%S UTC')}")
        hours_until = time_until.total_seconds() / 3600
        print(f"    Time until start: {hours_until:.1f} hours")
    
    # 5. Summary
    print("\n" + "=" * 70)
    print("Summary:")
    if is_golden:
        print("    [READY] Bot will trade during current golden hour window")
        print("    Bot cycle runs every 60 seconds and will attempt trades")
        print("    Trades subject to: golden hours (PASS), stable regime check, other gates")
    else:
        print("    [WAITING] Bot is outside golden hours - trades will be blocked")
        print(f"    Next trading window: {next_start.strftime('%Y-%m-%d %H:%M:%S UTC')}")
    print("=" * 70)


if __name__ == "__main__":
    main()
