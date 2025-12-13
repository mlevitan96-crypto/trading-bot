import json
import os


_OVERRIDES_CACHE = None


def load_pair_overrides():
    """Load pair-specific override configurations."""
    global _OVERRIDES_CACHE
    
    if _OVERRIDES_CACHE is not None:
        return _OVERRIDES_CACHE
    
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    filepath = os.path.join(base_dir, "configs", "pair_overrides.json")
    
    try:
        with open(filepath, "r") as f:
            data = json.load(f)
        
        _OVERRIDES_CACHE = data.get("overrides", {})
        print(f"✅ Loaded overrides for {len(_OVERRIDES_CACHE)} trading pairs")
        return _OVERRIDES_CACHE
    except (FileNotFoundError, json.JSONDecodeError) as e:
        print(f"⚠️  Could not load pair overrides: {e}")
        return {}


def get_pair_override(symbol, key, default=None):
    """
    Get a specific override value for a symbol.
    
    Args:
        symbol: Trading pair symbol (e.g., 'BTCUSDT')
        key: Override key (e.g., 'kelly_cap', 'trail_pct', 'roi_threshold')
        default: Default value if override not found
    
    Returns:
        Override value or default
    """
    overrides = load_pair_overrides()
    
    if symbol in overrides and key in overrides[symbol]:
        return overrides[symbol][key]
    
    return default


def get_kelly_cap_for_symbol(symbol):
    """Get Kelly cap override for symbol (or None for default)."""
    return get_pair_override(symbol, "kelly_cap", default=None)


def get_trail_pct_for_symbol(symbol):
    """Get trailing stop % override for symbol (or None for default)."""
    return get_pair_override(symbol, "trail_pct", default=None)


def get_roi_threshold_for_symbol(symbol):
    """Get ROI threshold override for symbol (or None for default)."""
    return get_pair_override(symbol, "roi_threshold", default=None)


def get_preferred_strategies(symbol):
    """Get preferred strategies for symbol (or None for default)."""
    return get_pair_override(symbol, "preferred_strategies", default=None)


def is_strategy_preferred(symbol, strategy):
    """Check if a strategy is preferred for a given symbol."""
    preferred = get_preferred_strategies(symbol)
    
    if preferred is None:
        return True
    
    return strategy in preferred


def reload_overrides():
    """Force reload of pair overrides from disk."""
    global _OVERRIDES_CACHE
    _OVERRIDES_CACHE = None
    return load_pair_overrides()
