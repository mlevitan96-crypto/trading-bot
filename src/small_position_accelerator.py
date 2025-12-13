"""
Small Position Accelerator

Automatically exits small positions (<$300) when profitable to free up position slots
for larger, more meaningful trades. Prevents tiny positions from blocking new opportunities.
"""
import time
from datetime import datetime


def check_and_exit_small_positions(positions, close_position_func, current_prices):
    """
    Check for small profitable positions and exit them quickly to free slots.
    
    Logic:
    - Position size < $300 AND
    - Position is profitable (any profit) AND
    - Position has been open for > 10 minutes
    
    → Exit immediately to free slot for larger trades
    
    Args:
        positions: List of open positions
        close_position_func: Function to call to close positions
        current_prices: Dict of symbol -> current price
    
    Returns:
        int: Number of positions closed
    """
    MIN_POSITION_SIZE = 300.0  # Below this, exit quickly when profitable
    MIN_HOLD_TIME_SECONDS = 600  # 10 minutes minimum hold
    
    closed_count = 0
    current_time = time.time()
    
    for pos in positions:
        symbol = pos.get("symbol")
        strategy = pos.get("strategy")
        position_size = pos.get("size", 0)
        entry_price = pos.get("entry_price", 0)
        entry_time = pos.get("entry_time")
        
        # Skip if position is already large enough
        if position_size >= MIN_POSITION_SIZE:
            continue
        
        # Get current price
        current_price = current_prices.get(symbol)
        if not current_price or current_price <= 0:
            continue
        
        # Calculate unrealized P&L (direction-aware for longs and shorts)
        direction = pos.get("direction", "LONG")  # Default to LONG for spot positions
        
        if direction == "SHORT":
            # Short positions profit when price decreases
            unrealized_pnl_pct = (entry_price - current_price) / entry_price if entry_price > 0 else 0
        else:
            # Long positions profit when price increases
            unrealized_pnl_pct = (current_price - entry_price) / entry_price if entry_price > 0 else 0
        
        unrealized_pnl_usd = position_size * unrealized_pnl_pct
        
        # Skip if not profitable
        if unrealized_pnl_usd <= 0:
            continue
        
        # Check hold time
        if entry_time:
            try:
                if isinstance(entry_time, str):
                    entry_dt = datetime.fromisoformat(entry_time.replace("Z", ""))
                    entry_timestamp = entry_dt.timestamp()
                else:
                    entry_timestamp = float(entry_time)
                
                hold_duration = current_time - entry_timestamp
                
                # Skip if hasn't been held long enough
                if hold_duration < MIN_HOLD_TIME_SECONDS:
                    continue
            except:
                # If we can't parse entry time, skip this check
                pass
        
        # Exit the small profitable position
        try:
            close_position_func(
                symbol=symbol,
                strategy=strategy,
                exit_price=current_price,
                reason=f"small_position_accelerator (size=${position_size:.2f}, profit=${unrealized_pnl_usd:.2f})"
            )
            print(f"🎯 Small position exit: {symbol} ${position_size:.2f} → Profit ${unrealized_pnl_usd:.2f} (freeing slot)")
            closed_count += 1
        except Exception as e:
            print(f"⚠️ Failed to close small position {symbol}: {e}")
    
    return closed_count


def get_small_position_stats(positions):
    """
    Get statistics about small positions for monitoring.
    
    Returns:
        dict: Statistics about small positions
    """
    MIN_POSITION_SIZE = 300.0
    
    small_positions = [p for p in positions if p.get("size", 0) < MIN_POSITION_SIZE]
    large_positions = [p for p in positions if p.get("size", 0) >= MIN_POSITION_SIZE]
    
    total_small_size = sum(p.get("size", 0) for p in small_positions)
    total_large_size = sum(p.get("size", 0) for p in large_positions)
    
    return {
        "total_positions": len(positions),
        "small_count": len(small_positions),
        "large_count": len(large_positions),
        "small_total_size_usd": round(total_small_size, 2),
        "large_total_size_usd": round(total_large_size, 2),
        "small_positions_blocking_slots": len(small_positions) > 0,
        "avg_small_position_size": round(total_small_size / len(small_positions), 2) if small_positions else 0,
        "avg_large_position_size": round(total_large_size / len(large_positions), 2) if large_positions else 0
    }
