#!/usr/bin/env python3
"""
Code Audit: Check for issues introduced by recent fixes
"""

import os
import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent
SRC_DIR = PROJECT_ROOT / "src"

ISSUES = []

def check_file(filepath: Path):
    """Check a single file for common issues."""
    rel_path = filepath.relative_to(PROJECT_ROOT)
    try:
        content = filepath.read_text(encoding='utf-8')
    except Exception as e:
        ISSUES.append(f"❌ {rel_path}: Cannot read file - {e}")
        return
    
    lines = content.split('\n')
    
    # Check 1: Hardcoded positions_futures.json paths (should use PathRegistry)
    if 'positions_futures.json' in content:
        for i, line in enumerate(lines, 1):
            if 'positions_futures.json' in line and 'PathRegistry' not in line and 'resolve_path' not in line:
                if not line.strip().startswith('#'):  # Skip comments
                    ISSUES.append(f"⚠️  {rel_path}:{i} Hardcoded positions_futures.json path (should use PathRegistry)")
    
    # Check 2: Path object used with os.path functions
    if 'os.path.' in content and 'Path(' in content:
        for i, line in enumerate(lines, 1):
            if 'os.path.' in line and any('Path(' in prev_line for prev_line in lines[max(0, i-3):i]):
                ISSUES.append(f"⚠️  {rel_path}:{i} Possible Path object used with os.path function")
    
    # Check 3: Missing Path import when Path() is used
    if 'Path(' in content and 'from pathlib import Path' not in content and 'import pathlib' not in content:
        ISSUES.append(f"⚠️  {rel_path}: Uses Path() but may not import it")
    
    # Check 4: Time used but not imported in function scope
    if 'time.sleep' in content or 'time.time' in content:
        has_import = 'import time' in content or 'from time import' in content
        in_function = False
        for i, line in enumerate(lines, 1):
            if re.match(r'^\s*def\s+\w+', line):
                in_function = True
                func_time_usage = False
            elif re.match(r'^\s*(def|class)', line) and not line.strip().startswith('def'):
                in_function = False
            
            if in_function and ('time.sleep' in line or 'time.time' in line):
                func_time_usage = True
                # Check if time is imported in function
                if func_time_usage and not has_import:
                    # Look back for import in function
                    func_has_import = False
                    for j in range(max(0, i-20), i):
                        if 'import time' in lines[j] or 'from time import' in lines[j]:
                            func_has_import = True
                            break
                    if not func_has_import:
                        ISSUES.append(f"⚠️  {rel_path}:{i} time used in function but may not be imported")
                        break
    
    # Check 5: isinstance checks on Path without importing Path
    if 'isinstance' in content and 'Path' in content:
        if 'from pathlib import Path' not in content and 'import pathlib' not in content:
            for i, line in enumerate(lines, 1):
                if 'isinstance' in line and 'Path' in line:
                    ISSUES.append(f"⚠️  {rel_path}:{i} isinstance check on Path but Path may not be imported")

def main():
    """Run audit on all Python files."""
    print("🔍 CODE AUDIT: Checking for issues from recent fixes\n")
    print("=" * 70)
    
    # Files we modified recently (priority check)
    recent_files = [
        'src/run.py',
        'src/healing_operator.py',
        'src/pnl_dashboard.py',
        'src/exit_health_sentinel.py',
        'src/position_manager.py',
    ]
    
    # Check recent files first
    print("\n📋 Checking recently modified files...")
    for filepath_str in recent_files:
        filepath = PROJECT_ROOT / filepath_str
        if filepath.exists():
            check_file(filepath)
    
    # Check all other Python files
    print("\n📋 Checking all Python files...")
    for py_file in SRC_DIR.rglob("*.py"):
        if py_file.name.startswith('_') or 'test' in py_file.name.lower():
            continue
        if str(py_file.relative_to(PROJECT_ROOT)) not in recent_files:
            check_file(py_file)
    
    # Report results
    print("\n" + "=" * 70)
    print("📊 AUDIT RESULTS\n")
    
    if not ISSUES:
        print("✅ No issues found!")
    else:
        print(f"Found {len(ISSUES)} potential issues:\n")
        for issue in ISSUES:
            print(issue)
        
        # Group by severity
        critical = [i for i in ISSUES if '❌' in i]
        warnings = [i for i in ISSUES if '⚠️' in i]
        
        print(f"\n📈 Summary:")
        print(f"  Critical: {len(critical)}")
        print(f"  Warnings: {len(warnings)}")
        
        if critical:
            print("\n🔴 CRITICAL ISSUES (must fix):")
            for issue in critical:
                print(f"  {issue}")

if __name__ == "__main__":
    main()

