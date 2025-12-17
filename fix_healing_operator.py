#!/usr/bin/env python3
"""
Fix healing operator - start it if not running, or check bot logs for errors.
"""

import sys
import os
import subprocess

def check_bot_logs():
    """Check bot logs for healing operator startup messages."""
    print("📋 Checking bot logs for healing operator status...")
    print("=" * 60)
    
    log_file = "/root/trading-bot-current/logs/bot_out.log"
    if not os.path.exists(log_file):
        print(f"❌ Log file not found: {log_file}")
        return False
    
    # Check for healing operator messages
    try:
        result = subprocess.run(
            ["grep", "-i", "healing", log_file],
            capture_output=True,
            text=True,
            timeout=5
        )
        
        lines = result.stdout.strip().split('\n')
        if lines and lines[0]:
            recent_lines = lines[-20:]  # Last 20 healing-related lines
            print("Recent healing operator messages:")
            for line in recent_lines:
                if "HEALING" in line.upper():
                    print(f"  {line.strip()}")
            
            # Check for errors
            error_lines = [l for l in lines if "error" in l.lower() or "failed" in l.lower() or "❌" in l]
            if error_lines:
                print("\n⚠️  Found errors/warnings:")
                for line in error_lines[-5:]:
                    print(f"  {line.strip()}")
        else:
            print("⚠️  No healing-related messages found in logs")
        
        # Check if it says it started
        started = any("started" in l.lower() for l in lines)
        if started:
            print("\n✅ Logs show healing operator was started")
            return True
        else:
            print("\n❌ Logs don't show healing operator started")
            return False
            
    except Exception as e:
        print(f"❌ Error checking logs: {e}")
        return False

def check_service_status():
    """Check if bot service is running."""
    print("\n📋 Checking bot service status...")
    print("=" * 60)
    
    try:
        result = subprocess.run(
            ["systemctl", "status", "tradingbot", "--no-pager"],
            capture_output=True,
            text=True,
            timeout=5
        )
        
        print(result.stdout)
        
        if "active (running)" in result.stdout.lower():
            print("\n✅ Bot service is running")
            return True
        else:
            print("\n⚠️  Bot service may not be running properly")
            return False
    except Exception as e:
        print(f"❌ Error checking service: {e}")
        return False

def check_via_api():
    """Check healing status via dashboard API."""
    print("\n📋 Checking via dashboard API...")
    print("=" * 60)
    
    try:
        import requests
        # Try to get status from dashboard
        # This won't work if dashboard isn't accessible, but worth trying
        print("(This requires dashboard to be running)")
        print("Check dashboard manually at: http://YOUR_IP:8501")
    except:
        pass

def main():
    print("🔧 HEALING OPERATOR DIAGNOSTIC & FIX")
    print("=" * 60)
    
    service_ok = check_service_status()
    logs_ok = check_bot_logs()
    
    print("\n" + "=" * 60)
    print("DIAGNOSIS")
    print("=" * 60)
    
    if not service_ok:
        print("❌ Bot service is not running")
        print("   → Start it with: systemctl start tradingbot")
        return
    
    if not logs_ok:
        print("⚠️  Healing operator may not have started properly")
        print("\nPossible fixes:")
        print("1. Restart the bot service:")
        print("   systemctl restart tradingbot")
        print("\n2. Check for startup errors in logs:")
        print("   tail -100 /root/trading-bot-current/logs/bot_out.log | grep -i healing")
        print("\n3. If errors persist, check the bot code for import errors")
    else:
        print("✅ Logs indicate healing operator started")
        print("\nThe diagnostic script may show 'not running' because:")
        print("  • It runs in a separate process")
        print("  • The bot's healing operator is in a different process")
        print("\nTo verify it's actually running:")
        print("  1. Check dashboard - self-healing status should be green/yellow")
        print("  2. Look for [HEALING] messages in logs:")
        print("     tail -f /root/trading-bot-current/logs/bot_out.log | grep HEALING")

if __name__ == "__main__":
    main()
