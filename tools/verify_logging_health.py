#!/usr/bin/env python3
"""
Enhanced Logging Health Verification Script
===========================================
Verifies that enhanced logging is working correctly by checking for:
- ATR (atr_14) values > 0
- Volatility values > 0
- Liquidation score (signal_components.liquidation) > 0

Checks the last 10 trades in enriched_decisions.jsonl or CSV export.
"""

import os
import json
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

try:
    from src.infrastructure.path_registry import PathRegistry
except ImportError:
    # Fallback if PathRegistry not available
    PathRegistry = None


def get_enriched_decisions_path():
    """Get path to enriched_decisions.jsonl using PathRegistry or fallback."""
    if PathRegistry:
        return PathRegistry.get_path("logs", "enriched_decisions.jsonl")
    else:
        # Fallback to relative path
        return project_root / "logs" / "enriched_decisions.jsonl"


def get_csv_export_path():
    """Get path to CSV export as fallback."""
    if PathRegistry:
        return PathRegistry.get_path("feature_store", "signal_analysis_export.csv")
    else:
        return project_root / "feature_store" / "signal_analysis_export.csv"


def read_last_n_lines(file_path, n=10):
    """Read last N lines from a file."""
    if not os.path.exists(file_path):
        return []
    
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            lines = f.readlines()
            return lines[-n:] if len(lines) >= n else lines
    except Exception as e:
        print(f"[WARN] Error reading {file_path}: {e}")
        return []


def parse_jsonl_line(line):
    """Parse a single JSONL line."""
    try:
        line = line.strip()
        if not line:
            return None
        return json.loads(line)
    except json.JSONDecodeError as e:
        print(f"[WARN] JSON decode error: {e}")
        return None


def check_volatility_snapshot(record):
    """
    Check if volatility_snapshot has non-zero values.
    Returns dict with check results.
    """
    checks = {
        "atr": False,
        "volatility": False,
        "liquidation": False,
        "has_snapshot": False
    }
    
    # Check signal_ctx for volatility_snapshot
    signal_ctx = record.get("signal_ctx", {})
    volatility_snapshot = signal_ctx.get("volatility_snapshot", {})
    
    # Also check top-level volatility_snapshot
    if not volatility_snapshot:
        volatility_snapshot = record.get("volatility_snapshot", {})
    
    if not volatility_snapshot:
        return checks
    
    checks["has_snapshot"] = True
    
    # Check ATR (atr_14)
    atr_14 = volatility_snapshot.get("atr_14", 0)
    if atr_14 and float(atr_14) > 0:
        checks["atr"] = True
    
    # Check volatility (can be in snapshot or signal_ctx)
    volatility = volatility_snapshot.get("volatility", 0)
    if not volatility or float(volatility) == 0:
        volatility = signal_ctx.get("volatility", 0)
    if volatility and float(volatility) > 0:
        checks["volatility"] = True
    
    # Check liquidation score (in signal_components)
    signal_components = volatility_snapshot.get("signal_components", {})
    if not signal_components:
        # Also check signal_ctx.signal_components
        signal_components = signal_ctx.get("signal_components", {})
    
    if signal_components:
        liquidation = signal_components.get("liquidation", 0)
        if liquidation and float(liquidation) != 0:
            checks["liquidation"] = True
    
    return checks


def verify_from_jsonl(jsonl_path):
    """Verify logging health from enriched_decisions.jsonl."""
    print(f"\n[CHECK] Checking: {jsonl_path}")
    
    if not os.path.exists(jsonl_path):
        print(f"[FAIL] File not found: {jsonl_path}")
        return False
    
    lines = read_last_n_lines(jsonl_path, n=10)
    if not lines:
        print("[FAIL] No data found in file")
        return False
    
    print(f"[OK] Found {len(lines)} recent records")
    
    passed_checks = {
        "atr": 0,
        "volatility": 0,
        "liquidation": 0,
        "has_snapshot": 0
    }
    
    valid_records = 0
    
    for i, line in enumerate(lines, 1):
        record = parse_jsonl_line(line)
        if not record:
            continue
        
        valid_records += 1
        checks = check_volatility_snapshot(record)
        
        # Count passes
        if checks["has_snapshot"]:
            passed_checks["has_snapshot"] += 1
        if checks["atr"]:
            passed_checks["atr"] += 1
        if checks["volatility"]:
            passed_checks["volatility"] += 1
        if checks["liquidation"]:
            passed_checks["liquidation"] += 1
        
        # Show details for first few records
        if i <= 3:
            symbol = record.get("symbol", "UNKNOWN")
            print(f"\n  Record {i} ({symbol}):")
            print(f"    Has snapshot: {'YES' if checks['has_snapshot'] else 'NO'}")
            print(f"    ATR > 0: {'YES' if checks['atr'] else 'NO'}")
            print(f"    Volatility > 0: {'YES' if checks['volatility'] else 'NO'}")
            print(f"    Liquidation > 0: {'YES' if checks['liquidation'] else 'NO'}")
    
    print(f"\n[SUMMARY] Out of {valid_records} valid records:")
    print(f"    Records with snapshot: {passed_checks['has_snapshot']}/{valid_records}")
    print(f"    Records with ATR > 0: {passed_checks['atr']}/{valid_records}")
    print(f"    Records with Volatility > 0: {passed_checks['volatility']}/{valid_records}")
    print(f"    Records with Liquidation > 0: {passed_checks['liquidation']}/{valid_records}")
    
    # Determine PASS/FAIL
    # Need at least 1 record with all three checks passing
    if (passed_checks["atr"] > 0 and 
        passed_checks["volatility"] > 0 and 
        passed_checks["liquidation"] > 0):
        print("\n[PASS] Enhanced logging is working correctly!")
        return True
    else:
        print("\n[FAIL] Enhanced logging not fully active yet.")
        print("   This is expected if no trades have occurred since deployment.")
        print("   Wait for golden hour (09:00-16:00 UTC) and check again after trades.")
        return False


def verify_from_csv(csv_path):
    """Verify logging health from CSV export (fallback)."""
    print(f"\n[CHECK] Checking CSV: {csv_path}")
    
    if not os.path.exists(csv_path):
        print(f"[WARN] CSV file not found: {csv_path}")
        return None
    
    try:
        import csv
        with open(csv_path, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            rows = list(reader)
        
        if not rows:
            print("[FAIL] No data in CSV")
            return False
        
        # Check last 10 rows
        recent_rows = rows[-10:] if len(rows) >= 10 else rows
        print(f"[OK] Found {len(recent_rows)} recent records")
        
        passed_checks = {
            "atr": 0,
            "volatility": 0,
            "liquidation": 0
        }
        
        for i, row in enumerate(recent_rows, 1):
            # Check ATR
            atr = row.get("atr_14", "0") or row.get("atr", "0")
            if atr and float(atr) > 0:
                passed_checks["atr"] += 1
            
            # Check volatility
            vol = row.get("volatility", "0")
            if vol and float(vol) > 0:
                passed_checks["volatility"] += 1
            
            # Check liquidation
            liq = row.get("liquidation_total_1h", "0") or row.get("liquidation", "0")
            if liq and float(liq) != 0:
                passed_checks["liquidation"] += 1
        
        print(f"\n[SUMMARY]:")
        print(f"    Records with ATR > 0: {passed_checks['atr']}/{len(recent_rows)}")
        print(f"    Records with Volatility > 0: {passed_checks['volatility']}/{len(recent_rows)}")
        print(f"    Records with Liquidation > 0: {passed_checks['liquidation']}/{len(recent_rows)}")
        
        if (passed_checks["atr"] > 0 and 
            passed_checks["volatility"] > 0 and 
            passed_checks["liquidation"] > 0):
            print("\n[PASS] Enhanced logging is working correctly!")
            return True
        else:
            print("\n[FAIL] Enhanced logging not fully active yet.")
            return False
            
    except Exception as e:
        print(f"[WARN] Error reading CSV: {e}")
        return None


def main():
    """Main verification function."""
    print("=" * 70)
    print("Enhanced Logging Health Verification")
    print("=" * 70)
    
    # Try JSONL first (primary source)
    jsonl_path = get_enriched_decisions_path()
    result = verify_from_jsonl(jsonl_path)
    
    # If JSONL check failed or file doesn't exist, try CSV
    if result is False:
        csv_path = get_csv_export_path()
        csv_result = verify_from_csv(csv_path)
        if csv_result is not None:
            result = csv_result
    
    # Exit with appropriate code
    sys.exit(0 if result else 1)


if __name__ == "__main__":
    main()
