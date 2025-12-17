#!/usr/bin/env python3
"""
Check healing operator status from within the running bot process.
This should be run via the bot's API or by checking the actual process.
"""
import sys
import os

# Add project to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Try to connect to the running bot's Flask API to check status
try:
    import requests
    import json
    
    # Try to get status from dashboard API
    try:
        # Check localhost dashboard
        response = requests.get('http://localhost:8050/health/system_status', timeout=5)
        if response.status_code == 200:
            status = response.json()
            healing_status = status.get('self_healing', 'unknown')
            print(f"Dashboard reports self_healing status: {healing_status}")
            
            if healing_status == 'green':
                print("✅ Self-healing is GREEN - everything working!")
            elif healing_status == 'yellow':
                print("⚠️  Self-healing is YELLOW")
                print("   Check if healing operator thread is running in bot process")
            else:
                print(f"❌ Self-healing is {healing_status.upper()}")
        else:
            print(f"❌ Dashboard API returned status {response.status_code}")
    except requests.exceptions.ConnectionError:
        print("⚠️  Cannot connect to dashboard (bot might not be running or on different port)")
    except Exception as e:
        print(f"⚠️  Error checking dashboard: {e}")
    
    # Also check threads in current process (won't work if run separately)
    print("\nChecking threads in current process:")
    import threading
    threads = threading.enumerate()
    healing_threads = [t for t in threads if 'healing' in t.name.lower() or 'Healing' in t.name]
    
    if healing_threads:
        print(f"✅ Found {len(healing_threads)} healing-related threads:")
        for t in healing_threads:
            print(f"   - {t.name}: alive={t.is_alive()}, daemon={t.daemon}")
    else:
        print("⚠️  No healing-related threads found in current process")
        print("   (This is normal if running diagnostic separately from bot)")
        
except ImportError:
    print("⚠️  requests library not available - cannot check dashboard API")
    print("   Install with: pip install requests")

except Exception as e:
    print(f"❌ Error: {e}")
    import traceback
    traceback.print_exc()
