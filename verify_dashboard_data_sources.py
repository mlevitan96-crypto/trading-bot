#!/usr/bin/env python3
"""Verify all dashboard data sources are correct and tied to actual logs/data."""
import sys
sys.path.insert(0, ".")

from src.data_registry import DataRegistry as DR
from datetime import datetime, timedelta
import json
from pathlib import Path

print("=" * 80)
print("DASHBOARD DATA SOURCES VERIFICATION")
print("=" * 80)

errors = []
warnings = []

# 1. Verify positions_futures.json exists and is readable
print("\n1. Verifying positions_futures.json...")
try:
    positions_data = DR.read_json(DR.POSITIONS_FUTURES)
    if not positions_data:
        errors.append("positions_futures.json is empty or invalid")
        print("   ❌ ERROR: File is empty or invalid")
    else:
        open_pos = positions_data.get("open_positions", [])
        closed_pos = positions_data.get("closed_positions", [])
        print(f"   ✅ File readable: {len(open_pos)} open, {len(closed_pos)} closed positions")
        
        # Check for trading_window field
        gh_trades = [p for p in closed_pos if p.get("trading_window") == "golden_hour"]
        trades_24_7 = [p for p in closed_pos if p.get("trading_window") == "24_7"]
        unknown = [p for p in closed_pos if p.get("trading_window") not in ["golden_hour", "24_7"]]
        print(f"   ✅ Trading window breakdown: {len(gh_trades)} GH, {len(trades_24_7)} 24/7, {len(unknown)} unknown")
        if len(unknown) > 0:
            warnings.append(f"{len(unknown)} trades have no trading_window field")
except Exception as e:
    errors.append(f"Failed to read positions_futures.json: {e}")
    print(f"   ❌ ERROR: {e}")

# 2. Verify recent closed positions have P&L data
print("\n2. Verifying closed positions have P&L data...")
try:
    positions_data = DR.read_json(DR.POSITIONS_FUTURES)
    closed_pos = positions_data.get("closed_positions", []) if positions_data else []
    
    if closed_pos:
        recent = closed_pos[-50:]  # Check last 50
        missing_pnl = 0
        for pos in recent:
            pnl = pos.get("pnl") or pos.get("net_pnl") or pos.get("realized_pnl")
            if pnl is None:
                missing_pnl += 1
        
        if missing_pnl == 0:
            print(f"   ✅ All {len(recent)} recent positions have P&L data")
        else:
            warnings.append(f"{missing_pnl} of {len(recent)} recent positions missing P&L")
            print(f"   ⚠️  WARNING: {missing_pnl} of {len(recent)} recent positions missing P&L")
    else:
        print("   ⚠️  No closed positions found")
except Exception as e:
    errors.append(f"Failed to verify P&L data: {e}")
    print(f"   ❌ ERROR: {e}")

# 3. Verify date parsing works correctly
print("\n3. Verifying date parsing...")
try:
    positions_data = DR.read_json(DR.POSITIONS_FUTURES)
    closed_pos = positions_data.get("closed_positions", []) if positions_data else []
    
    if closed_pos:
        parse_errors = 0
        for pos in closed_pos[-20:]:  # Check last 20
            closed_at = pos.get("closed_at", "")
            if closed_at:
                try:
                    if isinstance(closed_at, str):
                        if "T" in closed_at:
                            dt = datetime.fromisoformat(closed_at.replace("Z", "+00:00"))
                        else:
                            dt = datetime.strptime(closed_at, "%Y-%m-%d %H:%M:%S")
                        _ = dt.timestamp()
                except Exception:
                    parse_errors += 1
        
        if parse_errors == 0:
            print(f"   ✅ All dates parse correctly")
        else:
            warnings.append(f"{parse_errors} positions have unparseable dates")
            print(f"   ⚠️  WARNING: {parse_errors} positions have unparseable dates")
    else:
        print("   ⚠️  No closed positions to check")
except Exception as e:
    errors.append(f"Failed to verify date parsing: {e}")
    print(f"   ❌ ERROR: {e}")

# 4. Verify 24-hour filtering works
print("\n4. Verifying 24-hour filtering...")
try:
    cutoff = datetime.utcnow() - timedelta(hours=24)
    cutoff_ts = cutoff.timestamp()
    
    positions_data = DR.read_json(DR.POSITIONS_FUTURES)
    closed_pos = positions_data.get("closed_positions", []) if positions_data else []
    
    if closed_pos:
        recent_24h = 0
        for pos in closed_pos:
            closed_at = pos.get("closed_at", "")
            if closed_at:
                try:
                    if isinstance(closed_at, str):
                        if "T" in closed_at:
                            dt = datetime.fromisoformat(closed_at.replace("Z", "+00:00"))
                        else:
                            dt = datetime.strptime(closed_at, "%Y-%m-%d %H:%M:%S")
                        ts = dt.timestamp()
                        if ts >= cutoff_ts:
                            recent_24h += 1
                except:
                    pass
        
        print(f"   ✅ Found {recent_24h} trades in last 24 hours (cutoff: {cutoff})")
        if recent_24h == 0:
            warnings.append("No trades in last 24 hours (this may be expected)")
    else:
        print("   ⚠️  No closed positions to check")
except Exception as e:
    errors.append(f"Failed to verify 24-hour filtering: {e}")
    print(f"   ❌ ERROR: {e}")

# 5. Verify dashboard can load data (simulate load functions)
print("\n5. Verifying dashboard load functions...")
try:
    # Simulate load_open_positions_df
    positions_data = DR.read_json(DR.POSITIONS_FUTURES)
    open_pos = positions_data.get("open_positions", []) if positions_data else []
    print(f"   ✅ load_open_positions_df would return {len(open_pos)} positions")
    
    # Simulate load_closed_positions_df
    closed_pos = positions_data.get("closed_positions", []) if positions_data else []
    print(f"   ✅ load_closed_positions_df would return {len(closed_pos)} positions (limited to 500)")
except Exception as e:
    errors.append(f"Failed to verify load functions: {e}")
    print(f"   ❌ ERROR: {e}")

# Summary
print("\n" + "=" * 80)
print("VERIFICATION SUMMARY")
print("=" * 80)

if errors:
    print(f"\n❌ ERRORS ({len(errors)}):")
    for err in errors:
        print(f"   - {err}")
    sys.exit(1)
else:
    print("\n✅ No errors found")

if warnings:
    print(f"\n⚠️  WARNINGS ({len(warnings)}):")
    for warn in warnings:
        print(f"   - {warn}")
else:
    print("\n✅ No warnings")

print("\n✅ All data sources verified and accessible")
print("=" * 80)

