#!/usr/bin/env python3
"""
Debug script to check what the dashboard sees for CoinGlass status.
"""

import sys
import os
import time
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

def debug_coinglass_status():
    """Debug what the dashboard status check sees."""
    print("🔍 DEBUGGING COINGLASS STATUS CHECK")
    print("=" * 60)
    
    try:
        from src.infrastructure.path_registry import PathRegistry
        
        coinglass_dir = PathRegistry.get_path("feature_store", "coinglass")
        intel_dir = PathRegistry.get_path("feature_store", "intelligence")
        
        print(f"PathRegistry coinglass_dir: {coinglass_dir} (type: {type(coinglass_dir)})")
        print(f"PathRegistry intel_dir: {intel_dir} (type: {type(intel_dir)})")
        
        # Convert to strings
        coinglass_dir = str(coinglass_dir) if isinstance(coinglass_dir, Path) else coinglass_dir
        intel_dir = str(intel_dir) if isinstance(intel_dir, Path) else intel_dir
        
        print(f"\nAfter conversion:")
        print(f"coinglass_dir: {coinglass_dir}")
        print(f"intel_dir: {intel_dir}")
        print(f"\nExists check:")
        print(f"coinglass_dir exists: {os.path.exists(coinglass_dir)}")
        print(f"intel_dir exists: {os.path.exists(intel_dir)}")
        
        # Check API key
        has_api_key = bool(os.getenv('COINGLASS_API_KEY', ''))
        print(f"\nAPI key in environment: {has_api_key}")
        
        # Check systemd
        try:
            import subprocess
            result = subprocess.run(
                ["systemctl", "show", "tradingbot"],
                capture_output=True,
                text=True,
                timeout=1
            )
            has_api_in_systemd = "COINGLASS_API_KEY" in result.stdout
            print(f"API key in systemd: {has_api_in_systemd}")
        except Exception as e:
            print(f"Error checking systemd: {e}")
            has_api_in_systemd = False
        
        has_api_key = has_api_key or has_api_in_systemd
        
        # Check for recent files
        recent_files = False
        recent_file_count = 0
        
        print(f"\nChecking coinglass_dir:")
        if os.path.exists(coinglass_dir):
            try:
                files = os.listdir(coinglass_dir)
                print(f"  Files found: {len(files)}")
                for file in files[:5]:
                    file_path = os.path.join(coinglass_dir, file)
                    if os.path.isfile(file_path):
                        file_age = time.time() - os.path.getmtime(file_path)
                        print(f"    {file}: {file_age/3600:.2f} hours old")
                        if file_age < 3600:
                            recent_files = True
                            recent_file_count += 1
            except Exception as e:
                print(f"  Error listing: {e}")
        else:
            print(f"  Directory does not exist")
        
        print(f"\nChecking intel_dir:")
        if os.path.exists(intel_dir):
            try:
                files = os.listdir(intel_dir)
                print(f"  Files found: {len(files)}")
                for file in files[:10]:
                    file_path = os.path.join(intel_dir, file)
                    if os.path.isfile(file_path):
                        file_age = time.time() - os.path.getmtime(file_path)
                        # Check if it's an intel file
                        is_intel = ("intel" in file.lower() and file.endswith(".json")) or (file == "summary.json")
                        age_hours = file_age / 3600
                        print(f"    {file}: {age_hours:.2f} hours old (intel={is_intel})")
                        if is_intel and file_age < 3600:
                            recent_files = True
                            recent_file_count += 1
            except Exception as e:
                print(f"  Error listing: {e}")
        else:
            print(f"  Directory does not exist")
        
        print(f"\n" + "=" * 60)
        print(f"RESULT:")
        print(f"  Recent files found: {recent_files}")
        print(f"  Recent file count: {recent_file_count}")
        print(f"  Has API key: {has_api_key}")
        
        # Determine status
        if recent_files and recent_file_count > 0:
            status = "green"
        elif not has_api_key:
            status = "yellow"
        else:
            status = "yellow"
        
        print(f"  Expected status: {status}")
        
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    debug_coinglass_status()
