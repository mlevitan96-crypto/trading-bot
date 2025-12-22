#!/usr/bin/env python3
"""
Close All Open Positions Script
================================
Closes all currently open futures positions to start fresh with enhanced logging.
Uses force_close=True to bypass hold time restrictions.
"""

import os
import sys
from pathlib import Path

# Add project root to path
script_dir = Path(__file__).parent.absolute()
project_root = script_dir.parent
sys.path.insert(0, str(project_root))

try:
    from src.position_manager import load_futures_positions, close_futures_position
    from src.exchange_gateway import ExchangeGateway
except ImportError as e:
    print(f"[ERROR] Failed to import required modules: {e}")
    print("Make sure you're running from the project root directory")
    sys.exit(1)


def get_current_price(symbol):
    """Get current market price for a symbol."""
    try:
        gateway = ExchangeGateway()
        from src.venue_config import get_venue
        venue = get_venue(symbol) if hasattr(__import__('src.venue_config', fromlist=['get_venue']), 'get_venue') else "futures"
        price = gateway.get_price(symbol, venue=venue)
        return price
    except Exception as e:
        print(f"[WARN] Could not get price for {symbol}: {e}")
        # Try alternative method
        try:
            df = gateway.fetch_ohlcv(symbol, timeframe="1m", limit=5, venue=venue)
            if df is not None and len(df) > 0:
                return float(df['close'].iloc[-1])
        except:
            pass
    return None


def close_all_positions():
    """Close all open futures positions."""
    print("=" * 70)
    print("Close All Open Positions")
    print("=" * 70)
    
    # Load positions
    positions_data = load_futures_positions()
    open_positions = positions_data.get("open_positions", [])
    
    if not open_positions:
        print("\n[OK] No open positions to close.")
        return True
    
    print(f"\n[INFO] Found {len(open_positions)} open position(s)")
    
    closed_count = 0
    failed_count = 0
    
    for i, pos in enumerate(open_positions, 1):
        symbol = pos.get("symbol", "UNKNOWN")
        strategy = pos.get("strategy", "UNKNOWN")
        direction = pos.get("direction", "UNKNOWN")
        entry_price = pos.get("entry_price", 0)
        
        print(f"\n[{i}/{len(open_positions)}] Closing: {symbol} {direction} @ ${entry_price:.2f} ({strategy})")
        
        # Get current price
        current_price = get_current_price(symbol)
        if current_price is None:
            print(f"  [FAIL] Could not get current price for {symbol}")
            failed_count += 1
            continue
        
        print(f"  [INFO] Current price: ${current_price:.2f}")
        
        # Close position with force_close=True to bypass hold time
        try:
            success = close_futures_position(
                symbol=symbol,
                strategy=strategy,
                direction=direction,
                exit_price=current_price,
                reason="manual_close_all_for_fresh_start",
                funding_fees=0.0,
                force_close=True  # Bypass hold time restrictions
            )
            
            if success:
                print(f"  [OK] Successfully closed {symbol}")
                closed_count += 1
            else:
                print(f"  [FAIL] Failed to close {symbol} (position may not exist)")
                failed_count += 1
                
        except Exception as e:
            print(f"  [ERROR] Exception closing {symbol}: {e}")
            failed_count += 1
    
    # Summary
    print("\n" + "=" * 70)
    print("Summary:")
    print(f"  Total positions: {len(open_positions)}")
    print(f"  Successfully closed: {closed_count}")
    print(f"  Failed: {failed_count}")
    print("=" * 70)
    
    if failed_count == 0:
        print("\n[SUCCESS] All positions closed successfully!")
        return True
    else:
        print(f"\n[WARN] {failed_count} position(s) failed to close")
        return False


if __name__ == "__main__":
    try:
        success = close_all_positions()
        sys.exit(0 if success else 1)
    except KeyboardInterrupt:
        print("\n[INFO] Interrupted by user")
        sys.exit(1)
    except Exception as e:
        print(f"\n[ERROR] Unexpected error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
