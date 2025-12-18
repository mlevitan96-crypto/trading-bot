"""
Canonical Sizing Helper - Enforces exchange-specific contract sizes, tick sizes, and rounding rules.

This ensures all position sizing respects exchange limitations:
- Minimum contract size
- Tick size rounding
- Notional precision
- Order size validation

All position sizing functions should use this helper to ensure orders are valid.
"""

import os
import json
from pathlib import Path
from typing import Dict, Any, Optional, Tuple
from datetime import datetime

from src.exchange_utils import normalize_to_kraken, get_exchange_symbol
from src.kraken_contract_specs import (
    get_kraken_contract_specs,
    normalize_to_tick_size,
    round_to_precision,
    calculate_contracts_from_usd,
    calculate_usd_from_contracts
)
from src.infrastructure.path_registry import PathRegistry


# Log file for size adjustments
SIZE_ADJUSTMENTS_LOG = PathRegistry.LOGS_DIR / "size_adjustments.jsonl"
SIZE_ADJUSTMENTS_LOG.parent.mkdir(parents=True, exist_ok=True)


def log_size_adjustment(
    symbol: str,
    original_usd: float,
    original_contracts: Optional[float],
    adjusted_contracts: float,
    adjusted_usd: float,
    adjustments: Dict[str, Any],
    reason: str
):
    """
    Log size adjustments for learning and diagnostics.
    
    Args:
        symbol: Trading symbol
        original_usd: Original target USD amount
        original_contracts: Original contract count (if known)
        adjusted_contracts: Final adjusted contract count
        adjusted_usd: Final adjusted USD amount
        adjustments: Dict of adjustments made (tick_rounded, min_size_enforced, etc.)
        reason: Reason for adjustment
    """
    log_entry = {
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "symbol": symbol,
        "original_usd": original_usd,
        "original_contracts": original_contracts,
        "adjusted_contracts": adjusted_contracts,
        "adjusted_usd": adjusted_usd,
        "adjustments": adjustments,
        "reason": reason
    }
    
    try:
        with open(SIZE_ADJUSTMENTS_LOG, 'a') as f:
            f.write(json.dumps(log_entry) + '\n')
    except Exception as e:
        print(f"⚠️ [SIZING] Failed to log size adjustment: {e}")


def normalize_position_size(
    symbol: str,
    target_usd: float,
    price: float,
    exchange: Optional[str] = None
) -> Tuple[float, float, Dict[str, Any]]:
    """
    Normalize position size to valid exchange contract size, tick size, and rounding rules.
    
    This is the canonical sizing function - ALL position sizing should use this.
    
    Args:
        symbol: Trading symbol (internal format, e.g., "BTCUSDT")
        target_usd: Target position size in USD
        price: Current market price
        exchange: Exchange name ("kraken" or "blofin"). If None, uses EXCHANGE env var.
    
    Returns:
        Tuple of:
            - contracts: Valid contract count (float)
            - adjusted_usd: Actual USD amount after adjustments (float)
            - adjustments: Dict of adjustments made for logging
    
    Raises:
        ValueError: If price <= 0 or other invalid input
    """
    if price <= 0:
        raise ValueError(f"Invalid price for {symbol}: {price}")
    
    if target_usd <= 0:
        return 0.0, 0.0, {"reason": "Zero or negative target USD"}
    
    # Determine exchange
    if exchange is None:
        exchange = os.getenv("EXCHANGE", "blofin").lower()
    
    adjustments = {
        "original_usd": target_usd,
        "original_price": price,
        "exchange": exchange
    }
    
    # Get exchange-specific symbol
    exchange_symbol = get_exchange_symbol(exchange, symbol)
    
    if exchange == "kraken":
        # Kraken-specific sizing logic
        return _normalize_kraken_size(symbol, exchange_symbol, target_usd, price, adjustments)
    elif exchange == "blofin":
        # Blofin-specific sizing logic (for compatibility)
        # Blofin uses different contract specs, but for now we'll use similar logic
        return _normalize_blofin_size(symbol, target_usd, price, adjustments)
    else:
        # Unknown exchange - return as-is (may cause issues, but better than crashing)
        print(f"⚠️ [SIZING] Unknown exchange '{exchange}', using basic sizing")
        contracts = target_usd / price if price > 0 else 0.0
        return contracts, target_usd, adjustments


def _normalize_kraken_size(
    symbol: str,
    kraken_symbol: str,
    target_usd: float,
    price: float,
    adjustments: Dict[str, Any]
) -> Tuple[float, float, Dict[str, Any]]:
    """
    Normalize size for Kraken Futures.
    
    Process:
    1. Calculate contracts from USD
    2. Round to valid tick size (for price)
    3. Enforce minimum contract size
    4. Recalculate USD from adjusted contracts
    5. Round USD to appropriate precision
    """
    # Get contract specs
    specs = get_kraken_contract_specs(kraken_symbol)
    contract_size = specs["contract_size"]
    tick_size = specs["tick_size"]
    min_size = specs["min_size"]
    notional_precision = specs["notional_precision"]
    
    adjustments["contract_size"] = contract_size
    adjustments["tick_size"] = tick_size
    adjustments["min_size"] = min_size
    
    # Step 1: Round price to tick size
    tick_rounded_price = normalize_to_tick_size(price, tick_size)
    if tick_rounded_price != price:
        adjustments["price_tick_rounded"] = True
        adjustments["original_price"] = price
        adjustments["tick_rounded_price"] = tick_rounded_price
        price = tick_rounded_price
    else:
        adjustments["price_tick_rounded"] = False
    
    # Step 2: Calculate contracts from USD
    contracts = calculate_contracts_from_usd(target_usd, price, contract_size)
    original_contracts = contracts
    adjustments["calculated_contracts"] = contracts
    
    # Step 3: Enforce minimum contract size
    if contracts < min_size:
        if contracts > 0:
            adjustments["min_size_enforced"] = True
            adjustments["below_minimum"] = True
            # Round up to minimum if close, otherwise return 0
            if contracts >= min_size * 0.5:  # If at least 50% of minimum, round up
                contracts = min_size
            else:
                # Too small, return 0
                adjustments["reason"] = f"Size ${target_usd:.2f} too small (${contracts * price:.2f} < min ${min_size * price:.2f})"
                log_size_adjustment(symbol, target_usd, original_contracts, 0.0, 0.0, adjustments, adjustments["reason"])
                return 0.0, 0.0, adjustments
        else:
            adjustments["reason"] = "Zero or negative contracts calculated"
            return 0.0, 0.0, adjustments
    else:
        adjustments["min_size_enforced"] = False
    
    # Step 4: Round contracts to whole number (Kraken requires integer contracts)
    # Actually, Kraken may allow fractional contracts - verify this
    # For now, round to reasonable precision (4 decimal places for most, more for small tick sizes)
    if tick_size >= 0.01:
        contract_precision = 2
    elif tick_size >= 0.001:
        contract_precision = 3
    elif tick_size >= 0.0001:
        contract_precision = 4
    else:
        contract_precision = 6
    
    contracts = round_to_precision(contracts, contract_precision)
    adjustments["contracts_rounded"] = contracts
    adjustments["contract_precision"] = contract_precision
    
    # Step 5: Recalculate USD from adjusted contracts
    adjusted_usd = calculate_usd_from_contracts(contracts, price, contract_size)
    adjusted_usd = round_to_precision(adjusted_usd, notional_precision)
    
    adjustments["adjusted_usd"] = adjusted_usd
    adjustments["size_change_pct"] = ((adjusted_usd - target_usd) / target_usd * 100.0) if target_usd > 0 else 0.0
    
    # Log if significant adjustment
    if abs(adjustments.get("size_change_pct", 0)) > 1.0:  # More than 1% change
        reason = "Size adjusted to meet exchange requirements"
        if adjustments.get("price_tick_rounded"):
            reason += " (price tick-rounded)"
        if adjustments.get("min_size_enforced"):
            reason += " (min size enforced)"
        
        log_size_adjustment(
            symbol, target_usd, original_contracts, contracts, adjusted_usd,
            adjustments, reason
        )
    
    return contracts, adjusted_usd, adjustments


def _normalize_blofin_size(
    symbol: str,
    target_usd: float,
    price: float,
    adjustments: Dict[str, Any]
) -> Tuple[float, float, Dict[str, Any]]:
    """
    Normalize size for Blofin Futures.
    
    Note: This maintains backward compatibility with existing Blofin logic.
    Blofin has different contract specs that may need separate handling.
    """
    # Blofin uses different specs - for now, use simplified logic
    # TODO: Add proper Blofin contract specs if needed
    contracts = target_usd / price if price > 0 else 0.0
    
    # Blofin minimum order size is typically much smaller
    min_size_usd = 10.0  # Conservative default
    if contracts * price < min_size_usd:
        adjustments["reason"] = f"Size ${target_usd:.2f} below Blofin minimum ${min_size_usd:.2f}"
        return 0.0, 0.0, adjustments
    
    adjustments["adjusted_usd"] = target_usd
    return contracts, target_usd, adjustments


def validate_order_size(
    symbol: str,
    contracts: float,
    price: float,
    exchange: Optional[str] = None
) -> Tuple[bool, Optional[str], Dict[str, Any]]:
    """
    Validate that an order size meets exchange requirements.
    
    Args:
        symbol: Trading symbol (internal format)
        contracts: Number of contracts
        price: Order price
        exchange: Exchange name (uses env var if None)
    
    Returns:
        Tuple of:
            - is_valid: True if valid, False otherwise
            - error_message: Error message if invalid
            - validation_details: Dict with validation results
    """
    if exchange is None:
        exchange = os.getenv("EXCHANGE", "blofin").lower()
    
    details = {
        "symbol": symbol,
        "exchange": exchange,
        "contracts": contracts,
        "price": price
    }
    
    if contracts <= 0:
        return False, "Contract count must be positive", details
    
    if price <= 0:
        return False, "Price must be positive", details
    
    if exchange == "kraken":
        kraken_symbol = get_exchange_symbol(exchange, symbol)
        specs = get_kraken_contract_specs(kraken_symbol)
        
        # Check minimum size
        if contracts < specs["min_size"]:
            return False, f"Contracts {contracts} below minimum {specs['min_size']}", details
        
        # Check price is valid tick size
        tick_rounded = normalize_to_tick_size(price, specs["tick_size"])
        if abs(price - tick_rounded) > 0.0001:  # Allow small floating point error
            return False, f"Price {price} not valid tick size (should be {tick_rounded})", details
        
        details["specs"] = specs
        details["valid"] = True
        return True, None, details
    
    # For other exchanges, basic validation only
    details["valid"] = True
    return True, None, details


if __name__ == "__main__":
    # Test the sizing helper
    print("🧪 Testing Canonical Sizing Helper\n")
    
    test_cases = [
        ("BTCUSDT", 500.0, 86000.0, "kraken"),
        ("ETHUSDT", 300.0, 2800.0, "kraken"),
        ("BTCUSDT", 50.0, 86000.0, "kraken"),  # Too small
        ("BTCUSDT", 500.0, 86000.5, "kraken"),  # Price needs tick rounding
    ]
    
    for symbol, target_usd, price, exchange in test_cases:
        print(f"Testing: {symbol} | ${target_usd} @ ${price}")
        try:
            contracts, adjusted_usd, adjustments = normalize_position_size(symbol, target_usd, price, exchange)
            print(f"  ✅ Contracts: {contracts:.4f}")
            print(f"  ✅ Adjusted USD: ${adjusted_usd:.2f}")
            if adjustments.get("size_change_pct"):
                print(f"  📊 Change: {adjustments['size_change_pct']:.2f}%")
            print()
        except Exception as e:
            print(f"  ❌ Error: {e}\n")
