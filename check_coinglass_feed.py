#!/usr/bin/env python3
"""
Check CoinGlass feed status and verify it's being pulled correctly.
"""

import sys
import os
import json
import time
from pathlib import Path

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

def check_coinglass():
    """Check CoinGlass feed status."""
    print("🔍 COINGLASS FEED CHECK")
    print("=" * 60)
    
    try:
        from src.infrastructure.path_registry import PathRegistry
        
        coinglass_dir = PathRegistry.get_path("feature_store", "coinglass")
        print(f"CoinGlass directory: {coinglass_dir}")
        print(f"Exists: {os.path.exists(coinglass_dir)}")
        
        if os.path.exists(coinglass_dir):
            files = list(Path(coinglass_dir).glob("*"))
            print(f"\nFiles found: {len(files)}")
            
            recent_files = []
            stale_files = []
            current_time = time.time()
            
            for file_path in files:
                if file_path.is_file():
                    file_age = current_time - os.path.getmtime(str(file_path))
                    age_hours = file_age / 3600
                    
                    file_info = {
                        "name": file_path.name,
                        "age_hours": age_hours,
                        "size": file_path.stat().st_size
                    }
                    
                    if file_age < 3600:  # < 1 hour
                        recent_files.append(file_info)
                    else:
                        stale_files.append(file_info)
            
            print(f"\n✅ Recent files (< 1 hour): {len(recent_files)}")
            for f in recent_files[:5]:
                print(f"  • {f['name']}: {f['age_hours']*60:.1f} min ago")
            
            print(f"\n⚠️  Stale files (> 1 hour): {len(stale_files)}")
            for f in stale_files[:5]:
                print(f"  • {f['name']}: {f['age_hours']:.1f} hours ago")
            
            # Check for CoinGlass API key
            print("\n" + "=" * 60)
            print("API KEY CHECK")
            print("=" * 60)
            api_key = os.getenv('COINGLASS_API_KEY', '')
            if api_key:
                print(f"✅ COINGLASS_API_KEY is set in this process (length: {len(api_key)})")
            else:
                print("⚠️  COINGLASS_API_KEY not found in this process's environment")
                print("   (This script runs separately - checking if bot has it...)")
                # Check if systemd service has it
                try:
                    import subprocess
                    result = subprocess.run(
                        ["systemctl", "show", "tradingbot"],
                        capture_output=True,
                        text=True,
                        timeout=2
                    )
                    if "COINGLASS_API_KEY" in result.stdout:
                        print("   ✅ Bot service HAS the API key configured (good!)")
                        print("   ℹ️  This script can't see it because it runs separately")
                    else:
                        print("   ❌ Bot service does NOT have the API key")
                        print("   → Check /etc/systemd/system/tradingbot.service")
                except:
                    print("   ⚠️  Could not check systemd service")
            
            # Check if CoinGlass fetch is being called
            print("\n" + "=" * 60)
            print("FETCH ACTIVITY CHECK")
            print("=" * 60)
            
            # Check intelligence directory (alternative location)
            intel_dir = PathRegistry.get_path("feature_store", "intelligence")
            if os.path.exists(intel_dir):
                intel_path = Path(intel_dir)
                funding_file = intel_path / "funding_rates.json"
                oi_file = intel_path / "open_interest.json"
                
                if funding_file.exists():
                    funding_age = (current_time - os.path.getmtime(str(funding_file))) / 3600
                    print(f"Funding rates file: {funding_age:.1f} hours old")
                
                if oi_file.exists():
                    oi_age = (current_time - os.path.getmtime(str(oi_file))) / 3600
                    print(f"Open interest file: {oi_age:.1f} hours old")
                
                # Check for intel JSON files
                intel_files = list(intel_path.glob("*intel.json"))
                if intel_files:
                    print(f"\nIntel files found: {len(intel_files)}")
                    for intel_file in intel_files[:5]:
                        file_age = (current_time - os.path.getmtime(str(intel_file))) / 3600
                        print(f"  • {intel_file.name}: {file_age:.1f} hours old")
            
            # Status assessment
            print("\n" + "=" * 60)
            print("STATUS ASSESSMENT")
            print("=" * 60)
            
            if len(recent_files) > 0:
                print("✅ CoinGlass feed is ACTIVE (recent files found)")
                print("   Status should be GREEN")
            elif len(stale_files) > 0:
                print("⚠️  CoinGlass feed has STALE files (> 1 hour old)")
                print("   Status is YELLOW (data exists but not fresh)")
                print("   Possible reasons:")
                print("     • CoinGlass fetcher not running")
                print("     • Rate limit reached")
                print("     • API key issues")
            else:
                print("❌ No CoinGlass files found")
                print("   Status is RED")
                print("   CoinGlass feed may not be initialized")
                
        else:
            print("❌ CoinGlass directory doesn't exist")
            print("   Status would be RED")
            
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    check_coinglass()
