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
# [FINAL ALPHA] This is dynamically adjusted based on fill failure rate
MARKETABLE_LIMIT_OFFSET_BPS = 5.0  # 0.05% = 5 bps (default)
MARKETABLE_LIMIT_OFFSET_BPS_MAX = 12.0  # 0.12% = 12 bps (max, used if fills failing > 20%)

def get_marketable_limit_offset_bps() -> float:
    """
    [FINAL ALPHA] Get current marketable limit offset, which may be dynamically adjusted
    based on fill failure rate analysis.
    """
    try:
        from pathlib import Path
        from src.infrastructure.path_registry import PathRegistry
        config_path = Path(PathRegistry.get_path("feature_store", "trade_execution_config.json"))
        
        if config_path.exists():
            import json
            with open(config_path, 'r') as f:
                config = json.load(f)
                return config.get("marketable_limit_offset_bps", MARKETABLE_LIMIT_OFFSET_BPS)
    except:
        pass
    
    return MARKETABLE_LIMIT_OFFSET_BPS


def calculate_marketable_limit_price(signal_price: float, side: str, is_true_trend: bool = False) -> float:
    """
    Calculate marketable limit price for immediate fill.
    
    [FINAL ALPHA] Uses dynamically adjusted offset based on fill failure rate.
    
    Args:
        signal_price: Price at which signal was generated
        side: "LONG" (BUY) or "SHORT" (SELL)
        is_true_trend: If True, use tighter offset for faster fills
    
    Returns:
        Limit price that should fill immediately (within 0.05-0.12% of signal price)
    """
    # [FINAL ALPHA] Get dynamically adjusted offset
    offset_bps = get_marketable_limit_offset_bps()
    offset_pct = offset_bps / 10000.0  # Convert bps to decimal
    
    if is_true_trend:
        # Tighter offset for TRUE TREND (faster fills) - but respect minimum
        offset_pct = max(offset_pct * 0.8, MARKETABLE_LIMIT_OFFSET_BPS / 10000.0 * 0.8)  # At least 0.04%
    
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


def analyze_fill_failure_rate(hours: int = 24) -> Dict[str, Any]:
    """
    [FINAL ALPHA] Analyze fill failure rate for marketable limit orders.
    
    If fills are failing (not executing) > 20% of the time during "TRUE TREND",
    the offset should be increased from 0.05% to 0.12%.
    
    Returns:
        Dict with fill failure rate and recommendation
    """
    try:
        cutoff_ts = time.time() - (hours * 3600)
        
        if not EXECUTED_TRADES_LOG.exists():
            return {"error": "No execution log found"}
        
        true_trend_executions = []
        total_true_trend_attempts = 0
        
        # We need to track both successful fills and failed attempts
        # For now, we'll infer failures from orders that were placed but didn't fill
        # This is a simplified version - in a real system, we'd track order status
        
        with open(EXECUTED_TRADES_LOG, "r") as f:
            for line in f:
                try:
                    entry = json.loads(line.strip())
                    if entry.get("ts", 0) >= cutoff_ts:
                        if entry.get("is_true_trend", False):
                            true_trend_executions.append(entry)
                            total_true_trend_attempts += 1
                except:
                    continue
        
        # Calculate fill failure rate (simplified - assumes all logged entries are successful fills)
        # In a real system, we'd compare placed orders vs filled orders
        successful_fills = len(true_trend_executions)
        
        # For now, we'll use a heuristic: if slippage is very high, it suggests fills might be failing
        # A more accurate implementation would track order status separately
        high_slippage_count = sum(1 for e in true_trend_executions if abs(e.get("slippage_bps", 0)) > 10.0)
        estimated_failure_rate = (high_slippage_count / total_true_trend_attempts * 100) if total_true_trend_attempts > 0 else 0.0
        
        return {
            "total_true_trend_attempts": total_true_trend_attempts,
            "successful_fills": successful_fills,
            "estimated_failure_rate_pct": estimated_failure_rate,
            "should_increase_offset": estimated_failure_rate > 20.0,
            "current_offset_bps": get_marketable_limit_offset_bps(),
            "recommended_offset_bps": MARKETABLE_LIMIT_OFFSET_BPS_MAX if estimated_failure_rate > 20.0 else MARKETABLE_LIMIT_OFFSET_BPS
        }
    except Exception as e:
        return {"error": str(e)}

