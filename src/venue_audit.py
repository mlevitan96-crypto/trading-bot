#!/usr/bin/env python3
"""
Systematic Venue Mismatch Audit
Checks for spot/futures function calls being used in wrong contexts
"""

import re
import os
from pathlib import Path

AUDIT_RESULTS = []

def audit_file(filepath):
    """Audit a single Python file for venue mismatches."""
    with open(filepath, 'r') as f:
        lines = f.readlines()
    
    for line_num, line in enumerate(lines, 1):
        # Check for position sizing calls
        if 'get_position_size(' in line and 'get_position_size_kelly' not in line and 'get_futures_position_size_kelly' not in line:
            # Look for context clues in surrounding lines
            context_start = max(0, line_num - 10)
            context_end = min(len(lines), line_num + 5)
            context = ''.join(lines[context_start:context_end])
            
            # Check for futures indicators
            is_futures_context = any([
                'venue="futures"' in context,
                'venue = "futures"' in context,
                "venue='futures'" in context,
                'futures_margin' in context.lower(),
                'blofin' in context.lower(),
                'leverage' in context.lower(),
                'margin_collateral' in context.lower()
            ])
            
            if is_futures_context:
                AUDIT_RESULTS.append({
                    'file': filepath,
                    'line': line_num,
                    'issue': 'SPOT sizing function in FUTURES context',
                    'code': line.strip(),
                    'severity': 'HIGH'
                })
        
        # Check for futures sizing calls
        if 'get_futures_position_size_kelly(' in line:
            context_start = max(0, line_num - 10)
            context_end = min(len(lines), line_num + 5)
            context = ''.join(lines[context_start:context_end])
            
            # Check for spot indicators
            is_spot_context = any([
                'venue="spot"' in context,
                'venue = "spot"' in context,
                "venue='spot'" in context,
                'binance_us' in context.lower() and 'futures' not in context.lower()
            ])
            
            if is_spot_context:
                AUDIT_RESULTS.append({
                    'file': filepath,
                    'line': line_num,
                    'issue': 'FUTURES sizing function in SPOT context',
                    'code': line.strip(),
                    'severity': 'HIGH'
                })
        
        # Check for capital allocation calls
        if 'allocate_capital(' in line and 'allocate_futures_margin' not in line:
            context_start = max(0, line_num - 10)
            context_end = min(len(lines), line_num + 5)
            context = ''.join(lines[context_start:context_end])
            
            # Check if this is being used for futures budget
            is_futures_budget = any([
                'futures_margin' in context.lower(),
                'margin_budget' in context.lower(),
                'leverage' in context.lower()
            ])
            
            if is_futures_budget:
                AUDIT_RESULTS.append({
                    'file': filepath,
                    'line': line_num,
                    'issue': 'SPOT allocation in FUTURES budget context',
                    'code': line.strip(),
                    'severity': 'MEDIUM'
                })

# Scan all Python files in src/
src_dir = Path('src')
for py_file in src_dir.rglob('*.py'):
    audit_file(str(py_file))

# Print report
print("=" * 80)
print("VENUE MISMATCH AUDIT REPORT")
print("=" * 80)
print()

if not AUDIT_RESULTS:
    print("✅ No venue mismatches detected!")
else:
    print(f"⚠️  Found {len(AUDIT_RESULTS)} potential venue mismatches:\n")
    
    # Group by severity
    high_severity = [r for r in AUDIT_RESULTS if r['severity'] == 'HIGH']
    medium_severity = [r for r in AUDIT_RESULTS if r['severity'] == 'MEDIUM']
    
    if high_severity:
        print(f"🔴 HIGH SEVERITY ({len(high_severity)} issues):")
        print("-" * 80)
        for result in high_severity:
            rel_path = result['file'].replace('src/', '')
            print(f"\n  File: {rel_path}:{result['line']}")
            print(f"  Issue: {result['issue']}")
            print(f"  Code: {result['code']}")
    
    if medium_severity:
        print(f"\n🟡 MEDIUM SEVERITY ({len(medium_severity)} issues):")
        print("-" * 80)
        for result in medium_severity:
            rel_path = result['file'].replace('src/', '')
            print(f"\n  File: {rel_path}:{result['line']}")
            print(f"  Issue: {result['issue']}")
            print(f"  Code: {result['code']}")

print("\n" + "=" * 80)
