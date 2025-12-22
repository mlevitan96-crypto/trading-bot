#!/usr/bin/env python3
"""
Check All Pending Signals Across All Directories
=================================================
Check all trading-bot directories to see where signals actually are.
"""

import os
import json
from pathlib import Path

print("=" * 80)
print("CHECKING ALL PENDING SIGNALS ACROSS ALL DIRECTORIES")
print("=" * 80)

# Find all trading-bot directories
bot_dirs = []
for item in Path("/root").iterdir():
    if item.is_dir() and "trading-bot" in item.name:
        bot_dirs.append(item)

bot_dirs.sort()

print(f"\nFound {len(bot_dirs)} trading-bot directories:\n")

total_signals = 0
for bot_dir in bot_dirs:
    pending_file = bot_dir / "feature_store" / "pending_signals.json"
    
    if pending_file.exists():
        try:
            with open(pending_file, 'r') as f:
                data = json.load(f)
                if isinstance(data, dict):
                    count = len(data)
                elif isinstance(data, list):
                    count = len(data)
                else:
                    count = 0
            
            import time
            mtime = pending_file.stat().st_mtime
            age_minutes = (time.time() - mtime) / 60
            
            print(f"📁 {bot_dir.name}:")
            print(f"   Pending signals: {count:,}")
            print(f"   File age: {age_minutes:.1f} minutes")
            print(f"   Path: {pending_file}")
            
            total_signals += count
        except Exception as e:
            print(f"📁 {bot_dir.name}:")
            print(f"   ⚠️  Error reading: {e}")
    else:
        print(f"📁 {bot_dir.name}:")
        print(f"   ⚠️  File not found: {pending_file}")

print(f"\n{'='*80}")
print(f"TOTAL PENDING SIGNALS ACROSS ALL DIRECTORIES: {total_signals:,}")
print(f"{'='*80}")

# Check which directory the bot is actually using
print(f"\n🔍 Checking which directory bot is using:")
try:
    import sys
    sys.path.insert(0, '/root/trading-bot-current/src')
    from src.infrastructure.path_registry import PathRegistry
    
    project_root = PathRegistry.get_root()
    print(f"   PathRegistry PROJECT_ROOT: {project_root}")
    
    # Check what signal tracker would use
    from src.signal_outcome_tracker import PENDING_SIGNALS_FILE
    print(f"   Signal tracker file: {PENDING_SIGNALS_FILE}")
    print(f"   Absolute path: {Path(PENDING_SIGNALS_FILE).absolute()}")
    
except Exception as e:
    print(f"   ⚠️  Error checking: {e}")

print(f"\n{'='*80}")
