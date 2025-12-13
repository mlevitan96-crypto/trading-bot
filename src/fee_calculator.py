"""
Trading fee calculator for Blofin exchange.
"""

MAKER_FEE = 0.0002
TAKER_FEE = 0.0006


def calculate_trading_fee(position_size, order_type="taker"):
    """
    Calculate trading fee for a given position size.
    
    Args:
        position_size: Dollar amount of the position
        order_type: "maker" or "taker" (default: "taker" for market orders)
    
    Returns:
        Fee amount in dollars
    """
    if order_type == "maker":
        fee = position_size * MAKER_FEE
    else:
        fee = position_size * TAKER_FEE
    
    return round(fee, 4)


def get_net_profit_after_fees(position_size, roi, order_type="taker"):
    """
    Calculate net profit after deducting trading fees.
    
    Trading fees apply on both entry and exit:
    - Entry fee: fee on position size
    - Exit fee: fee on (position size + profit)
    
    Args:
        position_size: Dollar amount allocated to position
        roi: Return on investment (e.g., 0.01 for 1%)
        order_type: "maker" or "taker"
    
    Returns:
        Net profit after all fees
    """
    gross_profit = position_size * roi
    
    exit_value = position_size + gross_profit
    
    entry_fee = calculate_trading_fee(position_size, order_type)
    exit_fee = calculate_trading_fee(exit_value, order_type)
    
    total_fees = entry_fee + exit_fee
    
    net_profit = gross_profit - total_fees
    
    return round(net_profit, 4), total_fees
