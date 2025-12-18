"""
Exchange utility functions for symbol normalization and conversion.
Handles conversion between internal format (BTCUSDT) and exchange-specific formats.
"""

# Symbol mapping: Internal format (BTCUSDT) -> Kraken format (PI_XBTUSD)
KRAKEN_SYMBOL_MAP = {
    "BTCUSDT": "PI_XBTUSD",
    "ETHUSDT": "PI_ETHUSD",
    "SOLUSDT": "PF_SOLUSD",
    "AVAXUSDT": "PF_AVAXUSD",
    "DOTUSDT": "PF_DOTUSD",
    "TRXUSDT": "PF_TRXUSD",
    "XRPUSDT": "PI_XRPUSD",
    "ADAUSDT": "PF_ADAUSD",
    "DOGEUSDT": "PF_DOGEUSD",
    "BNBUSDT": "PF_BNBUSD",
    "LINKUSDT": "PF_LINKUSD",
    "ARBUSDT": "PF_ARBUSD",
    "OPUSDT": "PF_OPUSD",
    "PEPEUSDT": "PF_PEPEUSD",
}

# Reverse mapping for conversion back
KRAKEN_REVERSE_MAP = {v: k for k, v in KRAKEN_SYMBOL_MAP.items()}


def normalize_to_kraken(symbol: str) -> str:
    """
    Normalize symbol to Kraken Futures format.
    
    Converts:
    - BTCUSDT → PI_XBTUSD
    - ETHUSDT → PI_ETHUSD
    - BTC-USDT → PI_XBTUSD (handles dash format too)
    
    Args:
        symbol: Input symbol in any format
    
    Returns:
        Kraken futures format: "PI_XBTUSD"
    """
    # Remove dash if present (BTC-USDT -> BTCUSDT)
    if "-" in symbol:
        symbol = symbol.replace("-", "")
    
    # Check mapping
    if symbol in KRAKEN_SYMBOL_MAP:
        return KRAKEN_SYMBOL_MAP[symbol]
    
    # If not in map, try to construct (may not work for all symbols)
    if symbol.endswith("USDT"):
        base = symbol[:-4]  # Remove USDT
        # BTC -> XBT (ISO 4217 standard)
        if base == "BTC":
            return "PI_XBTUSD"
        # For others, try PF_ prefix (may need verification)
        return f"PF_{base}USD"
    
    # Return as-is if can't convert
    return symbol


def normalize_from_kraken(symbol: str) -> str:
    """
    Convert Kraken symbol back to internal format.
    
    Converts:
    - PI_XBTUSD → BTCUSDT
    - PI_ETHUSD → ETHUSDT
    
    Args:
        symbol: Kraken symbol format
    
    Returns:
        Internal format: "BTCUSDT"
    """
    if symbol in KRAKEN_REVERSE_MAP:
        return KRAKEN_REVERSE_MAP[symbol]
    
    # Try to reverse engineer if not in map
    if symbol.startswith("PI_") or symbol.startswith("PF_"):
        # PI_XBTUSD -> BTCUSDT
        if symbol.startswith("PI_"):
            base_part = symbol[3:-3]  # Remove PI_ prefix and USD suffix
        else:  # PF_
            base_part = symbol[3:-3]
        
        # XBT -> BTC
        if base_part == "XBT":
            return "BTCUSDT"
        
        # Others: assume base_part matches
        return f"{base_part}USDT"
    
    return symbol


def normalize_to_blofin(symbol: str) -> str:
    """
    Normalize symbol to Blofin Futures format (for reference/comparison).
    
    Converts:
    - BTCUSDT → BTC-USDT
    - BTC-USDT → BTC-USDT (already correct)
    
    Args:
        symbol: Input symbol in any format
    
    Returns:
        Blofin futures format: "BTC-USDT"
    """
    # Remove -SWAP suffix if present
    if symbol.endswith("-SWAP"):
        symbol = symbol[:-5]
    
    # Already in correct format (BTC-USDT)
    if "-" in symbol and symbol.count("-") == 1:
        return symbol
    
    # Format: BTCUSDT → BTC-USDT
    if "USDT" in symbol and "-" not in symbol:
        base = symbol.replace("USDT", "")
        return f"{base}-USDT"
    
    return symbol


def get_exchange_symbol(exchange: str, symbol: str) -> str:
    """
    Get exchange-specific symbol format.
    
    Args:
        exchange: Exchange name ("kraken" or "blofin")
        symbol: Internal symbol format (e.g., "BTCUSDT")
    
    Returns:
        Exchange-specific symbol format
    """
    if exchange.lower() == "kraken":
        return normalize_to_kraken(symbol)
    elif exchange.lower() == "blofin":
        return normalize_to_blofin(symbol)
    else:
        # Unknown exchange, return as-is
        return symbol
