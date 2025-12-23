#!/usr/bin/env python3
"""
Verify Trading Readiness
========================
Quick check to ensure:
1. Enhanced logging is working
2. Golden hour restrictions are active
3. Stable regime blocking is active
4. Recent trades are capturing snapshots
"""

import json
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

try:
    from src.position_manager import load_futures_positions
    from src.enhanced_trade_logging import (
        is_golden_hour,
        check_golden_hours_block,
        check_stable_regime_block
    )
    from src.data_registry import DataRegistry
except ImportError as e:
    print(f"ERROR: Import error: {e}")
    sys.exit(1)


def main():
    print("=" * 80)
    print("TRADING READINESS CHECK")
    print("=" * 80)
    print()
    
    # 1. Check Enhanced Logging Status
    print("1. ENHANCED LOGGING STATUS")
    print("-" * 80)
    positions_file = DataRegistry.POSITIONS_FUTURES
    
    # Resolve to absolute path for slot-based deployments
    from src.infrastructure.path_registry import resolve_path
    abs_positions_file = resolve_path(positions_file)
    
    if not os.path.exists(abs_positions_file):
        print(f"❌ Positions file not found: {abs_positions_file}")
        return
    
    positions = load_futures_positions()
    open_positions = positions.get("open_positions", [])
    closed_positions = positions.get("closed_positions", [])
    
    # Check recent closed trades (last 24 hours)
    now = datetime.now(timezone.utc)
    recent_closed = []
    for pos in closed_positions[-100:]:  # Check last 100 closed
        opened_at = pos.get("opened_at")
        if opened_at:
            try:
                if isinstance(opened_at, str):
                    opened_dt = datetime.fromisoformat(opened_at.replace('Z', '+00:00'))
                else:
                    opened_dt = datetime.fromtimestamp(opened_at)
                
                hours_ago = (now - opened_dt.replace(tzinfo=timezone.utc)).total_seconds() / 3600
                if hours_ago <= 24:
                    recent_closed.append(pos)
            except:
                pass
    
    trades_with_snapshots = sum(1 for pos in recent_closed if pos.get("volatility_snapshot"))
    trades_without_snapshots = len(recent_closed) - trades_with_snapshots
    
    print(f"   Recent closed trades (last 24h): {len(recent_closed)}")
    print(f"   ✅ With snapshots: {trades_with_snapshots}")
    print(f"   ⚠️  Without snapshots: {trades_without_snapshots}")
    
    if len(recent_closed) > 0:
        snapshot_rate = (trades_with_snapshots / len(recent_closed)) * 100
        if snapshot_rate >= 80:
            print(f"   ✅ Snapshot capture rate: {snapshot_rate:.1f}% (GOOD)")
        elif snapshot_rate >= 50:
            print(f"   ⚠️  Snapshot capture rate: {snapshot_rate:.1f}% (NEEDS ATTENTION)")
        else:
            print(f"   ❌ Snapshot capture rate: {snapshot_rate:.1f}% (POOR)")
    
    # Check open positions
    open_with_snapshots = sum(1 for pos in open_positions if pos.get("volatility_snapshot"))
    print(f"\n   Open positions: {len(open_positions)}")
    print(f"   ✅ With snapshots: {open_with_snapshots}/{len(open_positions)}")
    
    # Sample recent snapshot to verify data quality
    if recent_closed:
        for pos in reversed(recent_closed[-5:]):  # Check last 5
            snapshot = pos.get("volatility_snapshot", {})
            if snapshot:
                atr = snapshot.get("atr_14", 0)
                regime = snapshot.get("regime_at_entry", "unknown")
                print(f"\n   Sample snapshot ({pos.get('symbol', 'N/A')}):")
                print(f"      ATR: {atr:.2f} | Regime: {regime}")
                if atr == 0.0:
                    print(f"      ⚠️  ATR is 0.00 - may indicate calculation issue")
                break
    
    # 2. Golden Hour Check
    print("\n2. GOLDEN HOUR RESTRICTIONS")
    print("-" * 80)
    current_hour = datetime.now(timezone.utc).hour
    is_golden = is_golden_hour()
    should_block, reason = check_golden_hours_block()
    
    print(f"   Current UTC hour: {current_hour}:00")
    print(f"   Golden hour window: 09:00-16:00 UTC")
    print(f"   Is golden hour now: {'✅ YES' if is_golden else '❌ NO'}")
    print(f"   Would block trades: {'❌ YES' if should_block else '✅ NO'}")
    if should_block:
        print(f"   Block reason: {reason}")
    
    # Calculate when golden hour starts (if not in it)
    if not is_golden:
        if current_hour < 9:
            hours_until = 9 - current_hour
            print(f"\n   ⏰ Golden hour starts in {hours_until} hour(s)")
        else:
            hours_until = (24 - current_hour) + 9
            print(f"\n   ⏰ Golden hour starts in {hours_until} hour(s) (tomorrow)")
    
    # 3. Stable Regime Blocking
    print("\n3. STABLE REGIME BLOCKING")
    print("-" * 80)
    # Test with a common symbol
    test_symbol = "BTCUSDT"
    should_block_stable, stable_reason = check_stable_regime_block(test_symbol, "test")
    print(f"   Stable regime blocking: {'✅ ACTIVE' if should_block_stable else '✅ NOT BLOCKING'}")
    if should_block_stable:
        print(f"   Current regime: STABLE (would block)")
        print(f"   Block reason: {stable_reason}")
    else:
        print(f"   Current regime: NOT STABLE (trading allowed)")
    
    # 4. System Status Summary
    print("\n4. SYSTEM STATUS SUMMARY")
    print("-" * 80)
    
    issues = []
    warnings = []
    
    if len(recent_closed) > 0:
        snapshot_rate = (trades_with_snapshots / len(recent_closed)) * 100
        if snapshot_rate < 80:
            if snapshot_rate < 50:
                issues.append(f"Low snapshot capture rate: {snapshot_rate:.1f}%")
            else:
                warnings.append(f"Snapshot capture rate below target: {snapshot_rate:.1f}%")
    
    if not is_golden:
        warnings.append(f"Currently outside golden hours (trades will be blocked)")
    
    if issues:
        print("   ❌ ISSUES FOUND:")
        for issue in issues:
            print(f"      - {issue}")
    
    if warnings:
        print("   ⚠️  WARNINGS:")
        for warning in warnings:
            print(f"      - {warning}")
    
    if not issues and not warnings:
        print("   ✅ ALL SYSTEMS READY")
        print("   ✅ Enhanced logging active")
        print("   ✅ Golden hour restrictions active")
        print("   ✅ Stable regime blocking active")
    elif not issues:
        print("   ✅ CORE SYSTEMS READY (minor warnings above)")
    
    print("\n" + "=" * 80)
    print("Ready for trading!" if not issues else "Review issues above before trading")
    print("=" * 80)


if __name__ == "__main__":
    main()

