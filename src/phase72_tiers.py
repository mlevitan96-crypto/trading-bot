"""
Phase 7.2 - Symbol Tier Classification
Categorizes symbols into majors, L1s, and experimental tiers.
"""

TIERS = {
    "majors": {"symbols": {"BTCUSDT", "ETHUSDT"}},
    "l1s": {"symbols": {"SOLUSDT", "AVAXUSDT"}},
    "experimental": {"symbols": {"DOTUSDT", "TRXUSDT", "XRPUSDT", "ADAUSDT", "DOGEUSDT", "BNBUSDT", "MATICUSDT"}},
}


def tier_for_symbol(symbol: str) -> str:
    """
    Get tier for symbol.
    
    Args:
        symbol: Symbol name (e.g., "BTCUSDT")
        
    Returns:
        Tier name: "majors", "l1s", or "experimental"
    """
    for tier_name, tier_data in TIERS.items():
        if symbol in tier_data["symbols"]:
            return tier_name
    return "experimental"  # Default to experimental for unknown symbols


def get_symbols_in_tier(tier: str) -> set:
    """Get all symbols in a tier."""
    return TIERS.get(tier, {}).get("symbols", set())


def get_all_tiers() -> dict:
    """Get all tier definitions."""
    return TIERS.copy()
