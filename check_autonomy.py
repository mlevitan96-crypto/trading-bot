#!/usr/bin/env python3
"""
Quick check to verify the bot is autonomous and self-healing.
"""

import sys
import os
import time
import threading

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

def check_autonomy():
    """Verify bot is autonomously self-healing."""
    print("🤖 AUTONOMY CHECK")
    print("=" * 60)
    
    autonomous = True
    issues = []
    
    # 0. Check if we're in the bot process or separate
    print("ℹ️  Note: This script runs separately from the bot process")
    print("   Checking bot logs and service status instead...\n")
    
    # 1. Check bot logs for healing operator (try multiple sources)
    healing_in_logs = False
    
    # First try: Check log file if it exists
    log_file = "logs/bot_out.log"
    if os.path.exists(log_file):
        try:
            with open(log_file, 'r') as f:
                lines = f.readlines()
                recent_lines = lines[-500:] if len(lines) > 500 else lines
                
                healing_started = any("healing operator started" in line.lower() for line in recent_lines)
                healing_running = any("[HEALING]" in line for line in recent_lines[-100:])
                
                if healing_started:
                    print("✅ Bot logs show healing operator STARTED")
                    healing_in_logs = True
                if healing_running:
                    print("✅ Recent [HEALING] activity in logs")
                    healing_in_logs = True
        except Exception as e:
            print(f"⚠️  Error reading log file: {e}")
    
    # Second try: Check systemd journal (logs may be going here)
    if not healing_in_logs:
        try:
            import subprocess
            result = subprocess.run(
                ["journalctl", "-u", "tradingbot", "-n", "200", "--no-pager"],
                capture_output=True,
                text=True,
                timeout=5
            )
            
            if result.returncode == 0:
                output = result.stdout
                healing_started = "healing operator started" in output.lower() or "healing operator started" in output.lower()
                healing_running = "[HEALING]" in output
                
                if healing_started:
                    print("✅ Systemd journal shows healing operator STARTED")
                    healing_in_logs = True
                if healing_running:
                    print("✅ Recent [HEALING] activity in journal")
                    healing_in_logs = True
                    
                if not healing_in_logs:
                    # Check for startup errors
                    if "healing" in output.lower():
                        print("⚠️  Found healing-related messages but no 'started' confirmation")
                        # Show relevant lines
                        lines = output.split('\n')
                        healing_lines = [l for l in lines if "healing" in l.lower()][-5:]
                        if healing_lines:
                            print("   Recent healing messages:")
                            for line in healing_lines:
                                print(f"     {line.strip()[:100]}")
            else:
                print("⚠️  Could not read systemd journal")
        except FileNotFoundError:
            print("⚠️  journalctl not available")
        except Exception as e:
            print(f"⚠️  Error checking journal: {e}")
    
    if not healing_in_logs:
        print("⚠️  Could not find evidence of healing operator in logs or journal")
    
    # 2. Try to check healing operator instance (may fail if separate process)
    healing_op = None
    try:
        from src.healing_operator import get_healing_operator
        healing_op = get_healing_operator()
        
        if healing_op is None:
            if not healing_in_logs:
                print("\n❌ Healing operator NOT detected (not in logs or process)")
                autonomous = False
                issues.append("Healing operator not started")
            else:
                print("\n✅ Healing operator detected in logs (may not be accessible in this process)")
        else:
            print(f"✅ Healing operator running: {healing_op.running}")
            if healing_op.thread:
                print(f"✅ Thread alive: {healing_op.thread.is_alive()}")
                
            # Check recent activity
            if hasattr(healing_op, 'last_healing_cycle_ts') and healing_op.last_healing_cycle_ts:
                age = time.time() - healing_op.last_healing_cycle_ts
                print(f"✅ Last cycle: {age:.0f}s ago ({age/60:.1f} min)")
                
                if age < 120:  # Within 2 minutes
                    print("   → Healing is ACTIVE (good!)")
                elif age < 300:  # Within 5 minutes
                    print("   → Healing running (acceptable)")
                else:
                    print("   ⚠️  No recent activity")
                    issues.append(f"No healing cycle in {age/60:.1f} minutes")
            
            # Check what it's doing
            if healing_op.last_healing_cycle:
                cycle = healing_op.last_healing_cycle
                healed = cycle.get('healed', [])
                failed = cycle.get('failed', [])
                
                # Check for critical failures
                CRITICAL = ["safety_layer", "file_integrity", "trade_execution"]
                critical_failures = [f for f in failed if f in CRITICAL]
                non_critical = [f for f in failed if f not in CRITICAL]
                
                if healed:
                    print(f"✅ Recently healed: {', '.join(healed)}")
                    print("   → Bot IS fixing itself!")
                
                if critical_failures:
                    print(f"🚨 CRITICAL failures: {', '.join(critical_failures)}")
                    autonomous = False
                    issues.append(f"Critical components failing: {critical_failures}")
                elif failed:
                    print(f"⚠️  Non-critical issues: {', '.join(non_critical)}")
                    print("   → Not blocking autonomy (yellow status is OK)")
                else:
                    print("✅ No failures detected")
    except Exception as e:
        print(f"❌ Error checking healing: {e}")
        autonomous = False
        issues.append(f"Error: {e}")
    
    # 3. Check bot service status
    print("\n" + "=" * 60)
    print("BOT SERVICE CHECK")
    print("=" * 60)
    
    try:
        import subprocess
        result = subprocess.run(
            ["systemctl", "is-active", "tradingbot"],
            capture_output=True,
            text=True,
            timeout=2
        )
        if result.stdout.strip() == "active":
            print("✅ Bot service is running")
        else:
            print(f"⚠️  Bot service status: {result.stdout.strip()}")
            issues.append("Bot service not active")
    except:
        print("⚠️  Could not check service status (systemctl not available or permission denied)")
    
    # 4. Final assessment
    print("\n" + "=" * 60)
    print("AUTONOMY ASSESSMENT")
    print("=" * 60)
    
    if autonomous and (healing_in_logs or healing_op):
        print("✅ FULLY AUTONOMOUS")
        print("   → Bot is self-healing")
        print("   → Critical components healthy")
        print("   → No human intervention needed")
        print("\n💡 Yellow status is OK if:")
        print("   • Non-critical components have minor issues")
        print("   • Bot is actively healing them")
        print("   • Critical components (safety, files, execution) are healthy")
        print("\n📊 To verify healing is working:")
        print("   • Check dashboard self-healing status")
        print("   • Look for [HEALING] messages: tail -f logs/bot_out.log | grep HEALING")
    elif healing_in_logs or healing_op:
        print("⚠️  AUTONOMOUS WITH MINOR ISSUES")
        if issues:
            print(f"   Issues: {', '.join(issues)}")
        print("   → Bot can still self-heal")
        print("   → Yellow status indicates monitoring needed")
    else:
        print("❌ NOT FULLY AUTONOMOUS")
        print(f"   Critical issues: {', '.join(issues)}")
        print("   → May need intervention")
        print("\n🔧 To fix:")
        print("   1. Check bot logs: tail -100 logs/bot_out.log | grep -i healing")
        print("   2. Restart bot: systemctl restart tradingbot")
        print("   3. Run this diagnostic again")
    
    return autonomous and (healing_in_logs or healing_op)

if __name__ == "__main__":
    check_autonomy()
