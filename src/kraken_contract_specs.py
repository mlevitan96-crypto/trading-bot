"""
Kraken Futures Contract Specifications
Defines contract sizes, tick sizes, and minimum order sizes for each symbol.

Based on Kraken Futures API documentation:
- Contract size: Usually 1 USD per contract (perpetual futures)
- Tick size: Minimum price increment (varies by symbol)
- Min size: Minimum order size in contracts
"""

from typing import Dict, Optional, Tuple

# Kraken Futures Contract Specifications
# Note: These values may need verification against actual Kraken API responses
KRAKEN_CONTRACT_SPECS: Dict[str, Dict[str, float]] = {
    "PI_XBTUSD": {
        "contract_size": 1.0,      # 1 USD per contract (inverse perpetual)
        "tick_size": 0.5,          # 0.5 USD tick size (verified)
        "min_size": 1.0,           # Minimum 1 USD (1 contract)
        "max_size": 75000000.0,    # Maximum 75M USD position size
        "notional_precision": 2    # Decimal places for notional
    },
    "PI_ETHUSD": {
        "contract_size": 1.0,
        "tick_size": 0.05,         # 0.05 USD tick size (verified)
        "min_size": 1.0,           # Minimum 1 USD
        "max_size": 45000000.0,    # Maximum 45M USD position size
        "notional_precision": 2
    },
    "PI_XRPUSD": {
        "contract_size": 1.0,
        "tick_size": 0.0001,       # 0.0001 USD tick size
        "min_size": 1.0,
        "max_size": None,
        "notional_precision": 4
    },
    "PF_SOLUSD": {
        "contract_size": 1.0,
        "tick_size": 0.01,
        "min_size": 1.0,
        "max_size": None,
        "notional_precision": 2
    },
    "PF_AVAXUSD": {
        "contract_size": 1.0,
        "tick_size": 0.01,
        "min_size": 1.0,
        "max_size": None,
        "notional_precision": 2
    },
    "PF_DOTUSD": {
        "contract_size": 1.0,
        "tick_size": 0.001,
        "min_size": 1.0,
        "max_size": None,
        "notional_precision": 3
    },
    "PF_TRXUSD": {
        "contract_size": 1.0,
        "tick_size": 0.0001,
        "min_size": 1.0,
        "max_size": None,
        "notional_precision": 4
    },
    "PF_ADAUSD": {
        "contract_size": 1.0,
        "tick_size": 0.0001,
        "min_size": 1.0,
        "max_size": None,
        "notional_precision": 4
    },
    "PF_DOGEUSD": {
        "contract_size": 1.0,
        "tick_size": 0.0001,
        "min_size": 1.0,
        "max_size": None,
        "notional_precision": 4
    },
    "PF_BNBUSD": {
        "contract_size": 1.0,
        "tick_size": 0.01,
        "min_size": 1.0,
        "max_size": None,
        "notional_precision": 2
    },
    "PF_LINKUSD": {
        "contract_size": 1.0,
        "tick_size": 0.001,
        "min_size": 1.0,
        "max_size": None,
        "notional_precision": 3
    },
    "PF_ARBUSD": {
        "contract_size": 1.0,
        "tick_size": 0.001,
        "min_size": 1.0,
        "max_size": None,
        "notional_precision": 3
    },
    "PF_OPUSD": {
        "contract_size": 1.0,
        "tick_size": 0.001,
        "min_size": 1.0,
        "max_size": None,
        "notional_precision": 3
    },
    "PF_PEPEUSD": {
        "contract_size": 1.0,
        "tick_size": 0.0000001,    # Very small tick for meme coins
        "min_size": 1.0,
        "max_size": None,
        "notional_precision": 7
    },
}

# Default specs (fallback)
DEFAULT_SPECS = {
    "contract_size": 1.0,
    "tick_size": 0.01,
    "min_size": 1.0,
    "max_size": None,
    "notional_precision": 2
}


def get_kraken_contract_specs(kraken_symbol: str) -> Dict[str, float]:
    """
    Get contract specifications for a Kraken symbol.
    
    Args:
        kraken_symbol: Kraken symbol format (e.g., "PI_XBTUSD")
    
    Returns:
        Dict with contract_size, tick_size, min_size, etc.
    """
    return KRAKEN_CONTRACT_SPECS.get(kraken_symbol, DEFAULT_SPECS.copy())


def normalize_to_tick_size(price: float, tick_size: float) -> float:
    """
    Round price to valid tick size.
    
    Args:
        price: Raw price
        tick_size: Minimum tick size
    
    Returns:
        Price rounded to nearest tick
    """
    if tick_size <= 0:
        return price
    
    # Round to nearest tick
    return round(price / tick_size) * tick_size


def round_to_precision(value: float, precision: int) -> float:
    """
    Round value to specified decimal precision.
    
    Args:
        value: Value to round
        precision: Number of decimal places
    
    Returns:
        Rounded value
    """
    return round(value, precision)


def calculate_contracts_from_usd(usd_amount: float, price: float, contract_size: float = 1.0) -> float:
    """
    Calculate number of contracts from USD notional.
    
    For Kraken perpetual futures:
    - Contract size is usually 1 USD per contract
    - Contracts = USD / (Price * Contract Size)
    - For 1:1 contracts: Contracts = USD / Price
    
    Args:
        usd_amount: USD notional amount
        price: Current price
        contract_size: Contract size multiplier (default 1.0)
    
    Returns:
        Number of contracts
    """
    if price <= 0:
        return 0.0
    
    contracts = usd_amount / (price * contract_size)
    return max(contracts, 0.0)  # Ensure non-negative


def calculate_usd_from_contracts(contracts: float, price: float, contract_size: float = 1.0) -> float:
    """
    Calculate USD notional from number of contracts.
    
    Args:
        contracts: Number of contracts
        price: Current price
        contract_size: Contract size multiplier (default 1.0)
    
    Returns:
        USD notional amount
    """
    return contracts * price * contract_size
