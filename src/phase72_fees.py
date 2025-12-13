"""
Phase 7.2 - Blofin Fee Netting
Accurate P&L calculation including maker/taker fees.
"""
from typing import Literal

# Blofin fee rates (as of implementation)
BLOFIN_FEE_MAKER = 0.0002  # 0.02%
BLOFIN_FEE_TAKER = 0.0006  # 0.06%


def fee_for_fill(route: Literal["maker", "taker"], size: float, price: float) -> float:
    """
    Calculate fee for a trade fill.
    
    Args:
        route: "maker" or "taker"
        size: Position size in base currency
        price: Fill price
        
    Returns:
        Fee in USD
    """
    rate = BLOFIN_FEE_MAKER if route == "maker" else BLOFIN_FEE_TAKER
    return rate * size * price


def net_realized_pnl(
    entry_price: float,
    exit_price: float,
    size: float,
    side: Literal["LONG", "SHORT", "long", "short"],
    entry_route: Literal["maker", "taker"] = "maker",
    exit_route: Literal["maker", "taker"] = "taker"
) -> float:
    """
    Calculate net realized P&L after fees.
    
    Args:
        entry_price: Entry fill price
        exit_price: Exit fill price
        size: Position size
        side: "LONG" or "SHORT"
        entry_route: Entry liquidity route
        exit_route: Exit liquidity route
        
    Returns:
        Net P&L in USD (after fees)
    """
    side_normalized = side.upper()
    
    if side_normalized == "LONG":
        gross_pnl = (exit_price - entry_price) * size
    else:  # SHORT
        gross_pnl = (entry_price - exit_price) * size
    
    entry_fee = fee_for_fill(entry_route, size, entry_price)
    exit_fee = fee_for_fill(exit_route, size, exit_price)
    total_fees = entry_fee + exit_fee
    
    return gross_pnl - total_fees


def net_unrealized_pnl(
    entry_price: float,
    current_price: float,
    size: float,
    side: Literal["LONG", "SHORT", "long", "short"],
    entry_route: Literal["maker", "taker"] = "maker"
) -> float:
    """
    Calculate net unrealized P&L for open position.
    
    Conservative approach: subtract entry fee, estimate exit fee as taker.
    
    Args:
        entry_price: Entry fill price
        current_price: Current market price
        size: Position size
        side: "LONG" or "SHORT"
        entry_route: Entry liquidity route (default: maker)
        
    Returns:
        Net unrealized P&L in USD
    """
    side_normalized = side.upper()
    
    if side_normalized == "LONG":
        gross_pnl = (current_price - entry_price) * size
    else:  # SHORT
        gross_pnl = (entry_price - current_price) * size
    
    entry_fee = fee_for_fill(entry_route, size, entry_price)
    estimated_exit_fee = fee_for_fill("taker", size, current_price)  # Conservative: assume taker
    
    return gross_pnl - entry_fee - estimated_exit_fee


def calculate_fees(size: float, entry_price: float, exit_price: float,
                   entry_route: Literal["maker", "taker"] = "maker",
                   exit_route: Literal["maker", "taker"] = "taker") -> dict:
    """
    Calculate breakdown of fees.
    
    Returns:
        Dict with entry_fee, exit_fee, total_fees
    """
    entry_fee = fee_for_fill(entry_route, size, entry_price)
    exit_fee = fee_for_fill(exit_route, size, exit_price)
    
    return {
        "entry_fee_usd": entry_fee,
        "exit_fee_usd": exit_fee,
        "total_fees_usd": entry_fee + exit_fee,
        "entry_route": entry_route,
        "exit_route": exit_route
    }
