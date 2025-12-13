"""
Centralized Venue Configuration
Single source of truth for all venue (spot vs futures) assignments.

All trading symbols default to futures (Blofin) unless explicitly marked as spot.
"""

# Centralized venue mapping - single source of truth
VENUE_MAP = {
    # Futures trading (Blofin)
    "BTCUSDT": "futures",
    "ETHUSDT": "futures",
    "SOLUSDT": "futures",
    "AVAXUSDT": "futures",
    "DOTUSDT": "futures",
    "TRXUSDT": "futures",
    
    # Shadow research symbols (also futures)
    "XRPUSDT": "futures",
    "ADAUSDT": "futures",
    "DOGEUSDT": "futures",
    "BNBUSDT": "futures",
    "MATICUSDT": "futures",
    
    # Spot-only assets (stablecoins, if needed)
    # "USDCUSDT": "spot",
    # "BUSDUSDT": "spot",
}


def get_venue(symbol: str) -> str:
    """
    Get venue for a given symbol.
    
    Args:
        symbol: Trading pair (e.g., "BTCUSDT")
    
    Returns:
        "futures" or "spot"
    """
    # Default to futures if not in map
    return VENUE_MAP.get(symbol, "futures")


def is_futures(symbol: str) -> bool:
    """Check if symbol is futures trading."""
    return get_venue(symbol) == "futures"


def is_spot(symbol: str) -> bool:
    """Check if symbol is spot trading."""
    return get_venue(symbol) == "spot"


def print_venue_map():
    """Print current venue configuration for debugging."""
    print("\n" + "="*60)
    print("📍 CENTRALIZED VENUE CONFIGURATION")
    print("="*60)
    for symbol, venue in sorted(VENUE_MAP.items()):
        icon = "🚀" if venue == "futures" else "💵"
        print(f"{icon} {symbol:12s} → {venue}")
    print("="*60 + "\n")
