"""
Phase 3 Correlation & Exposure Controls

Theme-based exposure caps and cross-symbol correlation blocking.
Prevents over-concentration in correlated assets.
"""

from typing import Dict, List, Optional
import numpy as np
from dataclasses import dataclass


@dataclass
class ExposureState:
    """Current exposure by theme."""
    theme_exposure_bps: Dict[str, float]
    total_exposure_bps: float
    positions_by_theme: Dict[str, List[str]]


def theme_for_symbol(symbol: str) -> str:
    """
    Map symbol to thematic bucket.
    
    Args:
        symbol: Trading symbol (e.g., "BTCUSDT", "ETHUSDT")
        
    Returns:
        Theme name: "majors", "L1s", or "alts"
    """
    symbol_clean = symbol.replace("USDT", "").replace("-", "")
    
    majors = {"BTC", "ETH"}
    l1s = {"SOL", "AVAX", "DOT"}
    
    if symbol_clean in majors:
        return "majors"
    elif symbol_clean in l1s:
        return "L1s"
    else:
        return "alts"


def compute_theme_exposure(positions: List[Dict], portfolio_value: float) -> Dict[str, float]:
    """
    Compute current exposure by theme in basis points.
    
    Args:
        positions: List of open positions with 'symbol' and 'size_usd' fields
        portfolio_value: Total portfolio value in USD
        
    Returns:
        Dict mapping theme -> exposure in bps
    """
    theme_totals = {"majors": 0.0, "L1s": 0.0, "alts": 0.0}
    
    for pos in positions:
        theme = theme_for_symbol(pos.get("symbol", ""))
        theme_totals[theme] += pos.get("size_usd", 0.0)
    
    if portfolio_value > 0:
        return {
            theme: (total / portfolio_value) * 10000
            for theme, total in theme_totals.items()
        }
    
    return theme_totals


def correlation_block_check(symbol: str, positions: List[Dict], 
                            corr_matrix: np.ndarray, symbol_list: List[str],
                            threshold: float = 0.8) -> bool:
    """
    Check if adding symbol would exceed correlation threshold.
    
    Args:
        symbol: Symbol to potentially add
        positions: Current open positions
        corr_matrix: Correlation matrix (N x N)
        symbol_list: List of symbols matching corr_matrix order
        threshold: Maximum allowed average correlation
        
    Returns:
        True if should block due to correlation
    """
    if not positions or corr_matrix is None or len(symbol_list) == 0:
        return False
    
    try:
        if symbol not in symbol_list:
            return False
        
        symbol_idx = symbol_list.index(symbol)
        
        open_symbols = [p.get("symbol", "") for p in positions]
        open_indices = [symbol_list.index(s) for s in open_symbols if s in symbol_list]
        
        if not open_indices:
            return False
        
        correlations = [corr_matrix[symbol_idx, idx] for idx in open_indices]
        avg_corr = np.mean(correlations) if correlations else 0.0
        
        return bool(avg_corr >= threshold)
        
    except (ValueError, IndexError):
        return False


def exposure_cap_check(symbol: str, position_size_usd: float, positions: List[Dict],
                      portfolio_value: float, theme_caps: Dict[str, float]) -> bool:
    """
    Check if adding position would exceed theme exposure cap.
    
    Args:
        symbol: Symbol to potentially add
        position_size_usd: Proposed position size in USD
        positions: Current open positions
        portfolio_value: Total portfolio value
        theme_caps: Max exposure per theme in bps
        
    Returns:
        True if should block due to exposure cap
    """
    theme = theme_for_symbol(symbol)
    theme_cap = theme_caps.get(theme, 0)
    
    if theme_cap == 0:
        return False
    
    current_exposure = compute_theme_exposure(positions, portfolio_value)
    current_theme_bps = current_exposure.get(theme, 0.0)
    
    new_position_bps = (position_size_usd / portfolio_value) * 10000 if portfolio_value > 0 else 0
    projected_theme_bps = current_theme_bps + new_position_bps
    
    return projected_theme_bps >= theme_cap


def get_exposure_state(positions: List[Dict], portfolio_value: float) -> ExposureState:
    """Get current exposure state."""
    theme_exposure = compute_theme_exposure(positions, portfolio_value)
    
    positions_by_theme = {"majors": [], "L1s": [], "alts": []}
    for pos in positions:
        theme = theme_for_symbol(pos.get("symbol", ""))
        positions_by_theme[theme].append(pos.get("symbol", ""))
    
    total_exposure_bps = sum(theme_exposure.values())
    
    return ExposureState(
        theme_exposure_bps=theme_exposure,
        total_exposure_bps=total_exposure_bps,
        positions_by_theme=positions_by_theme
    )
