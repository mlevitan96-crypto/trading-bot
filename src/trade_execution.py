"""
Trade Execution Module - Phase 5: Execution Intelligence
==========================================================
Implements Marketable Limit Orders to capture the spread while ensuring fill immediacy.

Marketable Limit Orders:
- Instead of Market orders, place Limit orders at Price ± 0.05%
- Ensures fill immediacy during "TRUE TREND" while capping flash slippage
- Records slippage in BPS (Signal Price vs. Fill Price) for NBBO Audit
"""

import json
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, Optional, Tuple
from src.infrastructure.path_registry import PathRegistry

EXECUTED_TRADES_LOG = Path(PathRegistry.get_path("logs", "executed_trades.jsonl"))
EXECUTED_TRADES_LOG.parent.mkdir(parents=True, exist_ok=True)

# Marketable Limit Order offset: 0.05% (5 basis points)
MARKETABLE_LIMIT_OFFSET_BPS = 5.0  # 0.05% = 5 bps


def calculate_marketable_limit_price(signal_price: float, side: str, is_true_trend: bool = False) -> float:
    """
    Calculate marketable limit price for immediate fill.
    
    Args:
        signal_price: Price at which signal was generated
        side: "LONG" (BUY) or "SHORT" (SELL)
        is_true_trend: If True, use tighter offset for faster fills
    
    Returns:
        Limit price that should fill immediately (within 0.05% of signal price)
    """
    offset_pct = MARKETABLE_LIMIT_OFFSET_BPS / 10000.0  # Convert bps to decimal
    
    if is_true_trend:
        # Tighter offset for TRUE TREND (faster fills)
        offset_pct = offset_pct * 0.8  # 0.04% instead of 0.05%
    
    if side.upper() in ["LONG", "BUY"]:
        # For LONG: Place limit order slightly above signal price (willing to pay more)
        return signal_price * (1 + offset_pct)
    else:
        # For SHORT: Place limit order slightly below signal price (willing to sell for less)
        return signal_price * (1 - offset_pct)


def place_marketable_limit_order(
    client,
    symbol: str,
    side: str,
    qty: float,
    signal_price: float,
    leverage: int = 1,
    is_true_trend: bool = False,
    reduce_only: bool = False
) -> Dict[str, Any]:
    """
    Place a marketable limit order (Limit order at Price ± 0.05%).
    
    Args:
        client: Exchange client (BlofinFuturesClient)
        symbol: Trading symbol
        side: "BUY" or "SELL" (or "LONG"/"SHORT")
        qty: Order quantity
        signal_price: Price at which signal was generated
        leverage: Leverage multiplier
        is_true_trend: If True, use tighter offset for faster fills
        reduce_only: If True, only reduce existing position
    
    Returns:
        Order response with execution details
    """
    # Normalize side
    order_side = "BUY" if side.upper() in ["LONG", "BUY"] else "SELL"
    
    # Calculate marketable limit price
    limit_price = calculate_marketable_limit_price(signal_price, order_side, is_true_trend)
    
    # Place limit order
    try:
        result = client.place_order(
            symbol=symbol,
            side=order_side,
            qty=qty,
            price=limit_price,
            leverage=leverage,
            order_type="LIMIT",
            reduce_only=reduce_only
        )
        
        # Extract fill price from result
        fill_price = None
        if result and isinstance(result, dict):
            # Try to get fill price from order response
            fill_price = result.get("data", {}).get("avgPx") or result.get("avgPx") or result.get("fill_price")
            if fill_price:
                fill_price = float(fill_price)
        
        # If no fill price in response, use limit price as estimate
        if fill_price is None:
            fill_price = limit_price
        
        # Calculate slippage in BPS
        slippage_bps = calculate_slippage_bps(signal_price, fill_price, order_side)
        
        # Log execution with slippage audit
        log_execution_with_slippage(
            symbol=symbol,
            side=order_side,
            signal_price=signal_price,
            limit_price=limit_price,
            fill_price=fill_price,
            qty=qty,
            slippage_bps=slippage_bps,
            is_true_trend=is_true_trend,
            order_id=result.get("data", {}).get("ordId") if result and isinstance(result, dict) else None
        )
        
        return {
            "status": "filled",
            "order_id": result.get("data", {}).get("ordId") if result and isinstance(result, dict) else None,
            "signal_price": signal_price,
            "limit_price": limit_price,
            "fill_price": fill_price,
            "slippage_bps": slippage_bps,
            "qty": qty,
            "is_true_trend": is_true_trend
        }
        
    except Exception as e:
        print(f"❌ [TRADE-EXECUTION] Failed to place marketable limit order for {symbol}: {e}")
        raise


def calculate_slippage_bps(signal_price: float, fill_price: float, side: str) -> float:
    """
    Calculate slippage in basis points (BPS).
    
    Args:
        signal_price: Price at which signal was generated
        fill_price: Actual fill price
        side: "BUY" or "SELL"
    
    Returns:
        Slippage in basis points (positive = worse, negative = better)
    """
    if signal_price <= 0 or fill_price <= 0:
        return 0.0
    
    if side.upper() in ["BUY", "LONG"]:
        # For BUY: Positive slippage = paid more than signal price (bad)
        slippage_pct = (fill_price - signal_price) / signal_price
    else:
        # For SELL: Positive slippage = received less than signal price (bad)
        slippage_pct = (signal_price - fill_price) / signal_price
    
    # Convert to basis points (1% = 100 bps)
    slippage_bps = slippage_pct * 10000.0
    return slippage_bps


def log_execution_with_slippage(
    symbol: str,
    side: str,
    signal_price: float,
    limit_price: float,
    fill_price: float,
    qty: float,
    slippage_bps: float,
    is_true_trend: bool = False,
    order_id: Optional[str] = None
):
    """
    Log execution to executed_trades.jsonl with NBBO Audit (slippage in BPS).
    
    Args:
        symbol: Trading symbol
        side: "BUY" or "SELL"
        signal_price: Price at which signal was generated
        limit_price: Limit order price placed
        fill_price: Actual fill price
        qty: Order quantity
        slippage_bps: Slippage in basis points
        is_true_trend: Whether this was a TRUE TREND trade
        order_id: Order ID from exchange
    """
    entry = {
        "ts": time.time(),
        "ts_iso": datetime.utcnow().isoformat() + "Z",
        "symbol": symbol,
        "side": side,
        "signal_price": signal_price,
        "limit_price": limit_price,
        "fill_price": fill_price,
        "slippage_bps": slippage_bps,
        "qty": qty,
        "is_true_trend": is_true_trend,
        "order_id": order_id,
        "order_type": "MARKETABLE_LIMIT",
        "execution_quality": "EXCELLENT" if abs(slippage_bps) < 3.0 else "GOOD" if abs(slippage_bps) < 5.0 else "FAIR" if abs(slippage_bps) < 10.0 else "POOR"
    }
    
    try:
        with open(EXECUTED_TRADES_LOG, "a") as f:
            f.write(json.dumps(entry) + "\n")
    except Exception as e:
        print(f"⚠️ [TRADE-EXECUTION] Failed to log execution: {e}")


def get_recent_slippage_stats(symbol: Optional[str] = None, hours: int = 24) -> Dict[str, Any]:
    """
    Get recent slippage statistics for NBBO Audit.
    
    Args:
        symbol: Optional symbol filter
        hours: Lookback window in hours
    
    Returns:
        Dict with slippage statistics
    """
    try:
        cutoff_ts = time.time() - (hours * 3600)
        recent_executions = []
        
        if not EXECUTED_TRADES_LOG.exists():
            return {"error": "No execution log found"}
        
        with open(EXECUTED_TRADES_LOG, "r") as f:
            for line in f:
                try:
                    entry = json.loads(line.strip())
                    if entry.get("ts", 0) >= cutoff_ts:
                        if symbol is None or entry.get("symbol") == symbol:
                            recent_executions.append(entry)
                except:
                    continue
        
        if not recent_executions:
            return {"error": "No recent executions found"}
        
        slippages = [e.get("slippage_bps", 0.0) for e in recent_executions if e.get("slippage_bps") is not None]
        
        if not slippages:
            return {"error": "No slippage data found"}
        
        avg_slippage = sum(slippages) / len(slippages)
        max_slippage = max(slippages)
        min_slippage = min(slippages)
        
        # Count executions exceeding 5bps threshold
        exceeding_5bps = sum(1 for s in slippages if abs(s) > 5.0)
        
        return {
            "symbol": symbol or "ALL",
            "total_executions": len(recent_executions),
            "avg_slippage_bps": avg_slippage,
            "max_slippage_bps": max_slippage,
            "min_slippage_bps": min_slippage,
            "exceeding_5bps_count": exceeding_5bps,
            "exceeding_5bps_pct": (exceeding_5bps / len(slippages) * 100) if slippages else 0.0,
            "hours": hours
        }
        
    except Exception as e:
        return {"error": str(e)}

