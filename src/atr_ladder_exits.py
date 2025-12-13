import json
import os
import pandas as pd
import numpy as np
from datetime import datetime
from src.portfolio_tracker import get_arizona_time, load_portfolio, save_portfolio
from src.position_manager import get_open_positions, close_position, load_positions, save_positions
from src.fee_calculator import calculate_trading_fee


def calculate_atr(df, period=14):
    """Calculate Average True Range."""
    if len(df) < period:
        return 0.01
    
    high_low = df['high'] - df['low']
    high_close = abs(df['high'] - df['close'].shift())
    low_close = abs(df['low'] - df['close'].shift())
    
    true_range = high_low.combine(high_close, max).combine(low_close, max)
    atr = true_range.rolling(window=period).mean().iloc[-1]
    
    return float(atr) if not pd.isna(atr) else 0.01


def take_partial_exit(position, pct, exit_price, reason="atr_ladder"):
    """Take partial profit on a position."""
    if pct <= 0 or pct >= 1:
        return False
    
    partial_size = position["size"] * pct
    entry_price = position["entry_price"]
    
    price_change = exit_price - entry_price
    gross_profit = (price_change / entry_price) * partial_size
    
    fees = calculate_trading_fee(partial_size, order_type="taker")
    net_profit = gross_profit - fees
    
    portfolio = load_portfolio()
    portfolio["current_value"] += net_profit
    portfolio["total_profit"] += net_profit
    portfolio["total_profit_pct"] = ((portfolio["current_value"] - portfolio["starting_capital"]) / 
                                      portfolio["starting_capital"]) * 100
    
    trade_record = {
        "timestamp": get_arizona_time().isoformat(),
        "symbol": position["symbol"],
        "action": "partial_exit",
        "reason": reason,
        "exit_price": exit_price,
        "partial_pct": pct,
        "partial_size": partial_size,
        "entry_price": entry_price,
        "gross_profit": gross_profit,
        "fees": fees,
        "net_profit": net_profit,
        "roi_pct": (price_change / entry_price) * 100
    }
    
    portfolio["trades"].append(trade_record)
    save_portfolio(portfolio)
    
    position["size"] = position["size"] * (1 - pct)
    
    # Update position in storage
    positions_data = load_positions()
    for i, p in enumerate(positions_data["open_positions"]):
        if (p["symbol"] == position["symbol"] and 
            p.get("strategy") == position.get("strategy") and
            p["entry_price"] == position["entry_price"]):
            positions_data["open_positions"][i] = position
            save_positions(positions_data)
            break
    
    print(f"💰 {position['symbol']}: Partial exit {pct*100:.0f}% @ ${exit_price:.2f} (${net_profit:.2f} profit)")
    
    return True


def apply_atr_ladder_exits(position, df, symbol):
    """
    Apply ATR-based ladder exits with partial profit taking.
    
    Takes 25% profit at each ATR milestone (1x ATR, 2x ATR above entry)
    while trailing the remainder with dynamic stops.
    
    Args:
        position: Position dict with entry_price, size, etc.
        df: DataFrame with OHLCV data
        symbol: Trading pair symbol
    
    Returns:
        bool: True if position should be closed completely
    """
    atr = calculate_atr(df)
    entry_price = position["entry_price"]
    current_price = float(df['close'].iloc[-1])
    
    if "milestones_hit" not in position:
        position["milestones_hit"] = []
    
    milestones = [
        ("1x_atr", entry_price + atr),
        ("2x_atr", entry_price + 2 * atr)
    ]
    
    for milestone_name, milestone_price in milestones:
        if current_price >= milestone_price and milestone_name not in position["milestones_hit"]:
            if position["size"] > 0:
                take_partial_exit(position, pct=0.25, exit_price=current_price, 
                                 reason=f"atr_ladder_{milestone_name}")
                position["milestones_hit"].append(milestone_name)
                
                # Update position in storage
                positions_data = load_positions()
                for i, p in enumerate(positions_data["open_positions"]):
                    if (p["symbol"] == position["symbol"] and 
                        p.get("strategy") == position.get("strategy") and
                        p["entry_price"] == position["entry_price"]):
                        positions_data["open_positions"][i] = position
                        save_positions(positions_data)
                        break
    
    if position["size"] <= 0:
        close_position(symbol, position.get("strategy", "Unknown"), current_price, "atr_ladder_complete")
        return True
    
    return False


def get_ladder_stats():
    """Get statistics on ATR ladder exits."""
    portfolio = load_portfolio()
    
    ladder_trades = [t for t in portfolio.get("trades", []) 
                     if t.get("action") == "partial_exit" and "atr_ladder" in t.get("reason", "")]
    
    if not ladder_trades:
        return {
            "total_ladder_exits": 0,
            "total_profit": 0,
            "avg_profit_per_exit": 0
        }
    
    total_profit = sum(t.get("net_profit", 0) for t in ladder_trades)
    
    return {
        "total_ladder_exits": len(ladder_trades),
        "total_profit": total_profit,
        "avg_profit_per_exit": total_profit / len(ladder_trades) if ladder_trades else 0,
        "recent_exits": ladder_trades[-5:]
    }
