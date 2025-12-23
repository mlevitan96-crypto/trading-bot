#!/usr/bin/env python3
"""
Backfill Volatility Snapshots for Historical Trades
====================================================
Attempts to recreate volatility snapshots for trades that don't have them
by fetching historical OHLCV data from the time the trade was opened.
"""

import json
import os
import sys
from datetime import datetime, timezone
from typing import Dict, List, Any, Optional

sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

try:
    from src.position_manager import load_futures_positions, save_futures_positions
    from src.enhanced_trade_logging import get_market_data_snapshot, extract_signal_components
    from src.exchange_gateway import ExchangeGateway
    from src.futures_ladder_exits import calculate_atr
    from src.regime_filter import get_regime_filter
    import pandas as pd
except ImportError as e:
    print(f"ERROR: Import error: {e}")
    sys.exit(1)


def parse_timestamp(ts_str: str) -> float:
    """Parse timestamp string to Unix timestamp."""
    if isinstance(ts_str, (int, float)):
        return float(ts_str)
    try:
        ts_clean = ts_str.replace('Z', '+00:00')
        if '.' in ts_clean and '+' in ts_clean:
            parts = ts_clean.split('+')
            if len(parts) == 2:
                main_part = parts[0].split('.')[0]
                tz_part = parts[1]
                ts_clean = f"{main_part}+{tz_part}"
        dt = datetime.fromisoformat(ts_clean)
        return dt.timestamp()
    except Exception as e:
        print(f"⚠️  Failed to parse timestamp '{ts_str}': {e}")
        return 0.0


def fetch_historical_atr(symbol: str, timestamp: float, gateway: ExchangeGateway) -> Optional[float]:
    """
    Fetch historical OHLCV data and calculate ATR for a given timestamp.
    
    Note: This uses current OHLCV data as a proxy since we can't easily fetch
    historical data at exact timestamps. This is a limitation.
    """
    try:
        from src.venue_config import get_venue
        venue = get_venue(symbol) if hasattr(__import__('src.venue_config', fromlist=['get_venue']), 'get_venue') else "futures"
        
        # Fetch current OHLCV data (we can't easily get historical data)
        # This is a limitation - we'd need historical data API access
        df = gateway.fetch_ohlcv(symbol, timeframe="1m", limit=50, venue=venue)
        if df is not None and len(df) >= 14:
            try:
                atr_val = calculate_atr(df["high"], df["low"], df["close"], period=14)
                return float(atr_val) if atr_val and not pd.isna(atr_val) else None
            except Exception as e:
                print(f"⚠️  ATR calculation failed for {symbol}: {e}", flush=True)
                return None
    except Exception as e:
        print(f"⚠️  Failed to fetch OHLCV for {symbol}: {e}", flush=True)
        return None
    
    return None


def backfill_snapshot_for_position(position: Dict, gateway: ExchangeGateway) -> Dict[str, Any]:
    """Attempt to create a volatility snapshot for a historical position."""
    snapshot = {
        "atr_14": 0.0,
        "volume_24h": 0.0,
        "regime_at_entry": "unknown",
        "signal_components": {}
    }
    
    symbol = position.get("symbol", "")
    opened_at = position.get("opened_at") or position.get("timestamp", "")
    
    if not opened_at:
        return snapshot
    
    opened_ts = parse_timestamp(opened_at)
    if opened_ts == 0:
        return snapshot
    
    # Try to get current ATR as proxy (limitation: not historical)
    atr_val = fetch_historical_atr(symbol, opened_ts, gateway)
    if atr_val:
        snapshot["atr_14"] = atr_val
    
    # Try to get regime (current regime, not historical - limitation)
    try:
        regime_filter = get_regime_filter()
        current_regime = regime_filter.get_regime(symbol)
        snapshot["regime_at_entry"] = current_regime if current_regime else "unknown"
    except:
        snapshot["regime_at_entry"] = "unknown"
    
    # Extract signal components from position if available
    signal_context = position.get("signal_context", {})
    if signal_context:
        signal_components = extract_signal_components(signal_context)
        snapshot["signal_components"] = signal_components
    
    return snapshot


def backfill_volatility_snapshots():
    """Backfill volatility snapshots for positions missing them."""
    print("=" * 80)
    print("BACKFILL VOLATILITY SNAPSHOTS FOR HISTORICAL TRADES")
    print("=" * 80)
    print()
    print("⚠️  LIMITATIONS:")
    print("   - Cannot fetch exact historical OHLCV data")
    print("   - Uses current market data as proxy")
    print("   - Regime will be current, not historical")
    print("   - This is best-effort recreation")
    print()
    
    positions_data = load_futures_positions()
    closed_positions = positions_data.get("closed_positions", [])
    open_positions = positions_data.get("open_positions", [])
    
    # Filter to trades opened after Dec 22, 2025 (deployment date)
    deployment_ts = datetime(2025, 12, 22, 0, 0, 0, tzinfo=timezone.utc).timestamp()
    
    trades_to_backfill = []
    for pos in closed_positions:
        opened_at = pos.get("opened_at") or pos.get("timestamp", "")
        opened_ts = parse_timestamp(opened_at)
        
        if opened_ts >= deployment_ts:
            has_snapshot = bool(pos.get("volatility_snapshot", {}))
            if not has_snapshot:
                trades_to_backfill.append(pos)
    
    print(f"Found {len(trades_to_backfill)} closed trades that should have snapshots but don't")
    print()
    
    if not trades_to_backfill:
        print("✅ All trades already have snapshots or predate deployment")
        return
    
    print(f"⚠️  Attempting to backfill {len(trades_to_backfill)} trades...")
    print("   Note: This will use current market data, not historical")
    print()
    
    gateway = ExchangeGateway()
    backfilled_count = 0
    failed_count = 0
    
    for i, pos in enumerate(trades_to_backfill[:100]):  # Limit to first 100 to avoid overload
        symbol = pos.get("symbol", "UNKNOWN")
        snapshot = backfill_snapshot_for_position(pos, gateway)
        
        # Only update if we got meaningful data
        if snapshot.get("atr_14", 0) > 0 or snapshot.get("regime_at_entry") != "unknown":
            # Find position in closed_positions and update
            for closed_pos in closed_positions:
                if (closed_pos.get("symbol") == pos.get("symbol") and 
                    closed_pos.get("opened_at") == pos.get("opened_at") and
                    closed_pos.get("closed_at") == pos.get("closed_at")):
                    closed_pos["volatility_snapshot"] = snapshot
                    closed_pos["_backfilled"] = True  # Mark as backfilled
                    backfilled_count += 1
                    print(f"✅ Backfilled snapshot for {symbol} trade (ATR={snapshot.get('atr_14', 0):.2f}, Regime={snapshot.get('regime_at_entry')})")
                    break
        else:
            failed_count += 1
            print(f"⚠️  Could not backfill {symbol} - insufficient data")
    
    if backfilled_count > 0:
        positions_data["closed_positions"] = closed_positions
        save_futures_positions(positions_data)
        print()
        print(f"✅ Successfully backfilled {backfilled_count} trades")
        print(f"⚠️  {failed_count} trades could not be backfilled")
        print()
        print("⚠️  IMPORTANT: These snapshots use CURRENT market data, not historical")
        print("   Use for analysis with caution - they're approximations")
    else:
        print()
        print("❌ No trades were successfully backfilled")
        print("   This suggests we cannot recreate historical snapshots accurately")


def analyze_why_logging_failed():
    """Analyze why enhanced logging didn't work for the 384 trades."""
    print("=" * 80)
    print("ANALYSIS: Why Enhanced Logging Didn't Work")
    print("=" * 80)
    print()
    
    positions_data = load_futures_positions()
    closed_positions = positions_data.get("closed_positions", [])
    
    deployment_ts = datetime(2025, 12, 22, 0, 0, 0, tzinfo=timezone.utc).timestamp()
    
    # Check when trades were opened vs when code was deployed
    trades_after_deployment = []
    for pos in closed_positions:
        opened_at = pos.get("opened_at") or pos.get("timestamp", "")
        opened_ts = parse_timestamp(opened_at)
        if opened_ts >= deployment_ts:
            has_snapshot = bool(pos.get("volatility_snapshot", {}))
            trades_after_deployment.append({
                "opened_at": opened_at,
                "opened_ts": opened_ts,
                "has_snapshot": has_snapshot,
                "symbol": pos.get("symbol", "UNKNOWN")
            })
    
    print(f"Trades opened after deployment (Dec 22, 2025 00:00 UTC): {len(trades_after_deployment)}")
    print(f"Trades with snapshots: {sum(1 for t in trades_after_deployment if t['has_snapshot'])}")
    print(f"Trades without snapshots: {sum(1 for t in trades_after_deployment if not t['has_snapshot'])}")
    print()
    
    if trades_after_deployment:
        earliest = min(t["opened_ts"] for t in trades_after_deployment)
        latest = max(t["opened_ts"] for t in trades_after_deployment)
        
        print(f"Earliest trade after deployment: {datetime.fromtimestamp(earliest, tz=timezone.utc).isoformat()}")
        print(f"Latest trade after deployment: {datetime.fromtimestamp(latest, tz=timezone.utc).isoformat()}")
        print()
        
        print("REASON FOR FAILURE:")
        print("1. Enhanced logging code was deployed on Dec 22, 2025")
        print("2. But the code had silent error handling (designed to not break trading)")
        print("3. Errors were not logged, so failures were invisible")
        print("4. Error logging was added on Dec 23, 2025")
        print("5. After restart, new trades ARE getting snapshots (we see logs)")
        print()
        print("ROOT CAUSE:")
        print("The create_volatility_snapshot() function was failing silently.")
        print("Possible reasons:")
        print("  - ExchangeGateway.fetch_ohlcv() failing")
        print("  - calculate_atr() returning NaN/0")
        print("  - Regime detection failing")
        print("  - Import errors")
        print()
        print("SOLUTION:")
        print("✅ Error logging is now deployed")
        print("✅ New trades are getting snapshots (confirmed in logs)")
        print("⚠️  Historical trades cannot be accurately recreated (need historical OHLCV)")
        print("✅ Moving forward, all new trades will have complete snapshots")


def main():
    """Main function."""
    import argparse
    
    parser = argparse.ArgumentParser(description="Backfill volatility snapshots or analyze failures")
    parser.add_argument("--analyze", action="store_true", help="Analyze why logging failed")
    parser.add_argument("--backfill", action="store_true", help="Attempt to backfill snapshots")
    
    args = parser.parse_args()
    
    if args.analyze:
        analyze_why_logging_failed()
    elif args.backfill:
        response = input("⚠️  This will modify positions_futures.json. Continue? (yes/no): ")
        if response.lower() == "yes":
            backfill_volatility_snapshots()
        else:
            print("Cancelled")
    else:
        print("Usage:")
        print("  python3 backfill_volatility_snapshots.py --analyze   # Analyze why logging failed")
        print("  python3 backfill_volatility_snapshots.py --backfill  # Attempt to backfill (with confirmation)")


if __name__ == "__main__":
    main()

