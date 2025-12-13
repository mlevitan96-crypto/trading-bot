"""
Portfolio Bridge: Unified facade for portfolio access
Futures portfolio is the single source of truth; provides backward-compatible interface.
"""

from typing import Dict, Any
from src.futures_portfolio_tracker import load_futures_portfolio


def get_active_portfolio() -> Dict[str, Any]:
    """
    Get active portfolio with normalized structure.
    
    Returns futures portfolio with backward-compatible aliases:
    - portfolio_value: Total EQUITY (margin + realized P&L + unrealized P&L)
    - current_value: Alias for portfolio_value (backward compat)
    - available_margin: Available trading capital
    - All raw futures fields preserved
    
    Returns:
        Dict with unified portfolio structure
    """
    futures_portfolio = load_futures_portfolio()
    
    # Compute TRUE EQUITY from futures data (not static margin!)
    # Equity = Starting Capital + Realized P&L + Unrealized P&L
    base_margin = futures_portfolio.get("total_margin_allocated", 10000.0)
    realized_pnl = futures_portfolio.get("realized_pnl", 0.0)
    unrealized_pnl = futures_portfolio.get("unrealized_pnl", 0.0)
    
    # This is the DYNAMIC equity that changes as P&L accrues
    portfolio_value = base_margin + realized_pnl + unrealized_pnl
    
    # Start with raw futures fields, THEN override with computed equity
    # This ensures our dynamic calculation wins over any stale values
    unified = {
        **futures_portfolio,  # Start with all raw fields
        
        # Override with computed dynamic values (these MUST win)
        "portfolio_value": portfolio_value,
        "current_value": portfolio_value,
        "total_margin_allocated": base_margin,
        "realized_pnl": realized_pnl,
        "unrealized_pnl": unrealized_pnl,
        "available_margin": futures_portfolio.get("available_margin", portfolio_value),
        "used_margin": futures_portfolio.get("used_margin", 0.0)
    }
    
    return unified


def get_portfolio_value() -> float:
    """
    Get current portfolio value (total EQUITY).
    
    Calculates: Starting Capital + Realized P&L + Unrealized P&L
    
    Returns:
        Total portfolio equity in USD (dynamic, updates with P&L)
    """
    portfolio = get_active_portfolio()
    return portfolio["portfolio_value"]


def get_available_capital() -> float:
    """
    Get available capital for trading (excluding used margin).
    
    Returns:
        Available margin in USD
    """
    portfolio = get_active_portfolio()
    return portfolio.get("available_margin", 10000.0)
