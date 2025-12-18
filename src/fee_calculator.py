"""
Trading fee calculator supporting multiple exchanges (Blofin, Kraken).
"""
import os


# Fee rates by exchange (as decimal, e.g., 0.0006 = 0.06%)
EXCHANGE_FEES = {
    "blofin": {
        "maker": 0.0002,  # 0.02%
        "taker": 0.0006,  # 0.06%
    },
    "kraken": {
        "maker": 0.0002,  # 0.02% (verify with Kraken docs)
        "taker": 0.0005,  # 0.05% (verify with Kraken docs - may be 0.05-0.075%)
    }
}

# Default to Blofin for backward compatibility
MAKER_FEE = 0.0002
TAKER_FEE = 0.0006


def get_exchange_fees(exchange: str = None) -> dict:
    """
    Get fee rates for specified exchange.
    
    Args:
        exchange: Exchange name ("kraken" or "blofin"). If None, uses EXCHANGE env var or defaults to "blofin"
    
    Returns:
        Dict with "maker" and "taker" fee rates
    """
    if exchange is None:
        exchange = os.getenv("EXCHANGE", "blofin").lower()
    
    return EXCHANGE_FEES.get(exchange, EXCHANGE_FEES["blofin"])


def calculate_trading_fee(position_size, order_type="taker", exchange: str = None):
    """
    Calculate trading fee for a given position size.
    
    Args:
        position_size: Dollar amount of the position
        order_type: "maker" or "taker" (default: "taker" for market orders)
        exchange: Exchange name ("kraken" or "blofin"). If None, uses EXCHANGE env var
    
    Returns:
        Fee amount in dollars
    """
    fees = get_exchange_fees(exchange)
    fee_rate = fees.get(order_type, fees["taker"])
    fee = position_size * fee_rate
    return round(fee, 4)


def get_net_profit_after_fees(position_size, roi, order_type="taker", exchange: str = None):
    """
    Calculate net profit after deducting trading fees.
    
    Trading fees apply on both entry and exit:
    - Entry fee: fee on position size
    - Exit fee: fee on (position size + profit)
    
    Args:
        position_size: Dollar amount allocated to position
        roi: Return on investment (e.g., 0.01 for 1%)
        order_type: "maker" or "taker"
        exchange: Exchange name ("kraken" or "blofin"). If None, uses EXCHANGE env var
    
    Returns:
        Tuple of (net_profit, total_fees)
    """
    gross_profit = position_size * roi
    
    exit_value = position_size + gross_profit
    
    entry_fee = calculate_trading_fee(position_size, order_type, exchange)
    exit_fee = calculate_trading_fee(exit_value, order_type, exchange)
    
    total_fees = entry_fee + exit_fee
    
    net_profit = gross_profit - total_fees
    
    return round(net_profit, 4), total_fees
