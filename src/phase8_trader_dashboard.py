"""
Phase 8: Trader Dashboard - P&L-first, simple, fast
Focus: Daily and selectable timeframe P&L, active trades, trade history
60-second auto-refresh, Phoenix timezone
"""

import json
import time
from dataclasses import dataclass, asdict
from typing import List, Dict
from datetime import datetime, timezone, timedelta
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    import zoneinfo
    TZ_PHX = zoneinfo.ZoneInfo("America/Phoenix")
except Exception:
    import pytz
    TZ_PHX = pytz.timezone("America/Phoenix")


@dataclass
class ActiveTrade:
    trade_id: str
    symbol: str
    side: str
    entry_price: float
    current_price: float
    size_units: float
    entry_ts: float
    pnl_usd_unrealized: float


@dataclass
class ClosedTrade:
    trade_id: str
    symbol: str
    side: str
    entry_price: float
    exit_price: float
    size_units: float
    entry_ts: float
    exit_ts: float
    pnl_usd_realized: float


def to_phx(ts_utc: float) -> str:
    """Convert UTC epoch seconds to Phoenix local time string."""
    dt = datetime.fromtimestamp(ts_utc, tz=timezone.utc)
    dt = dt.astimezone(TZ_PHX)
    return dt.strftime("%a, %b %d %H:%M:%S")


def get_active_trades() -> List[ActiveTrade]:
    """Get active trades from position manager (spot + futures)."""
    active = []
    
    # Get SPOT positions (all assumed LONG for spot)
    try:
        from position_manager import get_open_positions
        from blofin_client import get_current_price
        
        positions = get_open_positions()
        
        for pos in positions:
            symbol = pos.get("symbol", "")
            try:
                current_price = get_current_price(symbol)
                entry_price = pos.get("entry_price", 0)
                size_usd = pos.get("size", 0)
                
                quantity = size_usd / entry_price if entry_price > 0 else 0
                
                # Spot is always LONG
                pnl = (current_price - entry_price) * quantity
                
                active.append(ActiveTrade(
                    trade_id=str(pos.get("position_id", "")),
                    symbol=symbol,
                    side="LONG (spot)",
                    entry_price=entry_price,
                    current_price=current_price,
                    size_units=quantity,
                    entry_ts=pos.get("timestamp", time.time()),
                    pnl_usd_unrealized=pnl
                ))
            except:
                continue
    except Exception as e:
        print(f"Error getting spot positions: {e}")
    
    # Get FUTURES positions (can be LONG or SHORT)
    try:
        from futures_portfolio_tracker import get_open_futures_positions
        from blofin_executor import BlofinFuturesExecutor
        
        blofin = BlofinFuturesExecutor()
        futures_positions = get_open_futures_positions()
        
        for pos in futures_positions:
            symbol = pos.get("symbol", "")
            try:
                current_price = blofin.get_mark_price(symbol)
                entry_price = pos.get("entry_price", 0)
                direction = pos.get("direction", "LONG").upper()
                leverage = pos.get("leverage", 1)
                margin = pos.get("margin_collateral", pos.get("size", 0))
                
                # Calculate quantity from margin and entry price
                notional = margin * leverage
                quantity = notional / entry_price if entry_price > 0 else 0
                
                # Direction-aware P&L calculation
                if direction == "LONG":
                    price_pnl = (current_price - entry_price) * quantity
                else:  # SHORT
                    price_pnl = (entry_price - current_price) * quantity
                
                # Display side with leverage
                display_side = f"{direction}-{leverage}x"
                
                active.append(ActiveTrade(
                    trade_id=str(pos.get("position_id", pos.get("trade_id", ""))),
                    symbol=symbol,
                    side=display_side,
                    entry_price=entry_price,
                    current_price=current_price,
                    size_units=quantity,
                    entry_ts=pos.get("timestamp", time.time()),
                    pnl_usd_unrealized=price_pnl
                ))
            except Exception as e:
                print(f"Error processing futures position {symbol}: {e}")
                continue
    except Exception as e:
        print(f"Error getting futures positions: {e}")
    
    return active


def get_closed_trades_spot(tf: str) -> List[ClosedTrade]:
    """Get spot-only closed trades for timeframe."""
    try:
        from portfolio_tracker import get_recent_trades
        
        # Map timeframe to number of trades
        limit_map = {"1D": 100, "7D": 500, "30D": 1000, "YTD": 5000, "ALL": 10000}
        limit = limit_map.get(tf, 100)
        
        trades = get_recent_trades(limit=limit)
        return _parse_spot_trades(trades, tf)
    except Exception as e:
        print(f"Error getting spot trades: {e}")
        return []


def get_closed_trades_futures(tf: str) -> List[ClosedTrade]:
    """Get futures-only closed trades for timeframe."""
    try:
        from futures_portfolio_tracker import get_recent_futures_trades
        
        # Map timeframe to number of trades
        limit_map = {"1D": 100, "7D": 500, "30D": 1000, "YTD": 5000, "ALL": 10000}
        limit = limit_map.get(tf, 100)
        
        trades = get_recent_futures_trades(limit=limit)
        return _parse_futures_trades(trades, tf)
    except Exception as e:
        print(f"Error getting futures trades: {e}")
        return []


def get_closed_trades(tf: str) -> List[ClosedTrade]:
    """Get ALL closed trades (spot + futures) for timeframe."""
    try:
        spot = get_closed_trades_spot(tf)
        futures = get_closed_trades_futures(tf)
        
        # Combine and sort by exit time
        all_trades = spot + futures
        all_trades.sort(key=lambda t: t.exit_ts)
        
        return all_trades
    except Exception as e:
        print(f"Error getting all trades: {e}")
        return []


def _parse_spot_trades(trades: List[Dict], tf: str) -> List[ClosedTrade]:
    """Parse spot trades from portfolio_tracker format."""
    if not trades:
        return []
    
    # Filter by timeframe
    now = time.time()
    cutoff_map = {
        "1D": now - 86400,
        "7D": now - 604800,
        "30D": now - 2592000,
        "YTD": datetime.now().replace(month=1, day=1, hour=0, minute=0, second=0).timestamp(),
        "ALL": 0
    }
    cutoff = cutoff_map.get(tf, now - 86400)
    
    closed = []
    for t in trades:
        try:
            timestamp = t.get("timestamp", 0)
            if isinstance(timestamp, str):
                timestamp = datetime.fromisoformat(timestamp.replace("Z", "+00:00")).timestamp()
            
            if timestamp < cutoff:
                continue
            
            # Extract P&L - trades have either 'profit' or 'net_profit' field
            pnl = t.get("profit", t.get("net_profit", 0))
            
            # Determine trade type for display
            side = t.get("side", "buy")
            action = t.get("action", "")
            display_side = action if action else side
            
            # Get prices (prefer new fields, fallback to legacy)
            entry_price = t.get("entry_price", 0)
            exit_price = t.get("exit_price", t.get("price", 0))
            
            # Get quantity (prefer new 'quantity' field, fallback to 'amount')
            quantity = t.get("quantity", t.get("partial_size", t.get("amount", 0)))
            
            closed.append(ClosedTrade(
                trade_id=str(t.get("trade_id", f"{t.get('symbol', 'UNK')}_{timestamp}")),
                symbol=t.get("symbol", ""),
                side=display_side,
                entry_price=entry_price,
                exit_price=exit_price,
                size_units=quantity,
                entry_ts=timestamp - 3600,  # Approximate
                exit_ts=timestamp,
                pnl_usd_realized=pnl
            ))
        except Exception as e:
            print(f"Error processing trade: {e}, trade: {t}")
            continue
            
    return closed


def _parse_futures_trades(trades: List[Dict], tf: str) -> List[ClosedTrade]:
    """Parse futures trades from futures_portfolio_tracker format."""
    if not trades:
        return []
    
    # Filter by timeframe
    now = time.time()
    cutoff_map = {
        "1D": now - 86400,
        "7D": now - 604800,
        "30D": now - 2592000,
        "YTD": datetime.now().replace(month=1, day=1, hour=0, minute=0, second=0).timestamp(),
        "ALL": 0
    }
    cutoff = cutoff_map.get(tf, now - 86400)
    
    closed = []
    for t in trades:
        try:
            timestamp = t.get("timestamp", 0)
            if isinstance(timestamp, str):
                timestamp = datetime.fromisoformat(timestamp.replace("Z", "+00:00")).timestamp()
            
            if timestamp < cutoff:
                continue
            
            # Futures trades have different structure
            pnl = t.get("net_pnl", 0)
            direction = t.get("direction", "LONG")
            leverage = t.get("leverage", 1)
            
            # Get prices
            entry_price = t.get("entry_price", 0)
            exit_price = t.get("exit_price", 0)
            
            # Get size (margin * leverage)
            margin = t.get("margin_collateral", 0)
            notional = t.get("notional_size", margin)
            
            # Display side as "LONG-5x" or "SHORT-3x"
            display_side = f"{direction}-{leverage}x"
            
            closed.append(ClosedTrade(
                trade_id=str(t.get("trade_id", f"{t.get('symbol', 'UNK')}_{timestamp}")),
                symbol=t.get("symbol", ""),
                side=display_side,
                entry_price=entry_price,
                exit_price=exit_price,
                size_units=notional,
                entry_ts=timestamp - 3600,  # Approximate
                exit_ts=timestamp,
                pnl_usd_realized=pnl
            ))
        except Exception as e:
            print(f"Error processing futures trade: {e}, trade: {t}")
            continue
            
    return closed


def pnl_series_spot(tf: str) -> List[Dict]:
    """Get spot-only P&L time series."""
    try:
        from portfolio_tracker import get_recent_trades
        return _build_pnl_series(get_recent_trades(limit=10000), tf, pnl_field="profit")
    except Exception as e:
        print(f"Error getting spot P&L series: {e}")
        return []


def pnl_series_futures(tf: str) -> List[Dict]:
    """Get futures-only P&L time series."""
    try:
        from futures_portfolio_tracker import get_recent_futures_trades
        return _build_pnl_series(get_recent_futures_trades(limit=10000), tf, pnl_field="net_pnl")
    except Exception as e:
        print(f"Error getting futures P&L series: {e}")
        return []


def pnl_series(tf: str) -> List[Dict]:
    """Get combined spot + futures P&L time series."""
    try:
        spot = pnl_series_spot(tf)
        futures = pnl_series_futures(tf)
        
        # Combine and sort by timestamp
        all_points = spot + futures
        if not all_points:
            return []
        
        all_points.sort(key=lambda x: x["ts"])
        
        # Rebuild cumulative
        series = []
        cumulative = 0
        for point in all_points:
            cumulative += point.get("pnl_delta", 0)
            series.append({
                "ts": point["ts"],
                "pnl_usd": cumulative
            })
        
        return series
    except Exception as e:
        print(f"Error getting combined P&L series: {e}")
        return []


def _build_pnl_series(trades: List[Dict], tf: str, pnl_field: str = "profit") -> List[Dict]:
    """Helper to build P&L time series from trades."""
    if not trades:
        return []
    
    # Filter by timeframe
    now = time.time()
    cutoff_map = {
        "1D": now - 86400,
        "7D": now - 604800,
        "30D": now - 2592000,
        "YTD": datetime.now().replace(month=1, day=1, hour=0, minute=0, second=0).timestamp(),
        "ALL": 0
    }
    cutoff = cutoff_map.get(tf, now - 86400)
    
    # Build time series from trades
    trade_points = []
    for t in trades:
        # Get timestamp
        ts_str = t.get("timestamp", "")
        if isinstance(ts_str, str):
            try:
                ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00")).timestamp()
            except:
                continue
        else:
            ts = ts_str or time.time()
        
        if ts < cutoff:
            continue
        
        # Get P&L from this trade
        pnl = t.get(pnl_field, t.get("net_profit", t.get("profit", 0)))
        
        trade_points.append({
            "ts": ts,
            "pnl": pnl,
            "pnl_delta": pnl  # For combining series
        })
    
    # Sort by timestamp
    trade_points.sort(key=lambda x: x["ts"])
    
    # Build cumulative series
    series = []
    cumulative = 0
    for point in trade_points:
        cumulative += point["pnl"]
        series.append({
            "ts": point["ts"],
            "pnl_usd": cumulative,
            "pnl_delta": point["pnl"]  # For combining
        })
    
    return series


def get_portfolio_value() -> Dict:
    """Get current portfolio value and available funds - calculated from actual trades."""
    try:
        from portfolio_tracker import get_recent_trades, STARTING_CAPITAL
        
        # Calculate total portfolio value from actual trade P&L
        trades = get_recent_trades(limit=10000)
        realized_pnl = sum(t.get("profit", t.get("net_profit", 0)) for t in trades)
        total_value = STARTING_CAPITAL + realized_pnl
        
        # Calculate positions value from open positions
        positions_value = 0
        try:
            from position_manager import get_open_positions
            from blofin_client import get_current_price
            positions = get_open_positions()
            for pos in positions:
                try:
                    symbol = pos.get("symbol", "")
                    size_usd = pos.get("size", 0)
                    entry_price = pos.get("entry_price", 0)
                    current_price = get_current_price(symbol)
                    
                    quantity = size_usd / entry_price if entry_price > 0 else 0
                    current_value = quantity * current_price
                    positions_value += current_value
                except:
                    continue
        except:
            pass
        
        # Calculate available cash
        cash = total_value - positions_value
        
        return {
            "total_value": total_value,
            "cash": cash,
            "positions_value": positions_value
        }
    except Exception as e:
        print(f"Error getting portfolio value: {e}")
        import traceback
        traceback.print_exc()
        return {"total_value": 10000, "cash": 10000, "positions_value": 0}


def api_trades_active():
    """Active trades endpoint."""
    trades = get_active_trades()
    rows = []
    for t in trades:
        rows.append({
            "trade_id": t.trade_id,
            "symbol": t.symbol,
            "side": t.side,
            "entry_price": round(t.entry_price, 6),
            "current_price": round(t.current_price, 6),
            "size_units": round(t.size_units, 6),
            "entry_time_phx": to_phx(t.entry_ts),
            "pnl_usd_unrealized": round(t.pnl_usd_unrealized, 2),
            "pnl_color": ("green" if t.pnl_usd_unrealized >= 0 else "red")
        })
    return {"active": rows, "updated_at_phx": to_phx(time.time())}


def api_trades_history(tf: str = "1D"):
    """Combined trade history endpoint (spot + futures)."""
    trades = get_closed_trades(tf)
    rows = []
    for t in trades:
        rows.append({
            "trade_id": t.trade_id,
            "symbol": t.symbol,
            "side": t.side,
            "entry_price": round(t.entry_price, 6),
            "exit_price": round(t.exit_price, 6),
            "size_units": round(t.size_units, 6),
            "entry_time_phx": to_phx(t.entry_ts),
            "exit_time_phx": to_phx(t.exit_ts),
            "pnl_usd_realized": round(t.pnl_usd_realized, 2),
            "pnl_color": ("green" if t.pnl_usd_realized >= 0 else "red")
        })
    return {"history": rows, "timeframe": tf, "updated_at_phx": to_phx(time.time())}


def api_trades_history_spot(tf: str = "1D"):
    """Spot-only trade history endpoint."""
    trades = get_closed_trades_spot(tf)
    rows = []
    for t in trades:
        rows.append({
            "trade_id": t.trade_id,
            "symbol": t.symbol,
            "side": t.side,
            "entry_price": round(t.entry_price, 6),
            "exit_price": round(t.exit_price, 6),
            "size_units": round(t.size_units, 6),
            "entry_time_phx": to_phx(t.entry_ts),
            "exit_time_phx": to_phx(t.exit_ts),
            "pnl_usd_realized": round(t.pnl_usd_realized, 2),
            "pnl_color": ("green" if t.pnl_usd_realized >= 0 else "red")
        })
    return {"history": rows, "timeframe": tf, "venue": "spot", "updated_at_phx": to_phx(time.time())}


def api_trades_history_futures(tf: str = "1D"):
    """Futures-only trade history endpoint."""
    trades = get_closed_trades_futures(tf)
    rows = []
    for t in trades:
        rows.append({
            "trade_id": t.trade_id,
            "symbol": t.symbol,
            "side": t.side,
            "entry_price": round(t.entry_price, 6),
            "exit_price": round(t.exit_price, 6),
            "size_units": round(t.size_units, 6),
            "entry_time_phx": to_phx(t.entry_ts),
            "exit_time_phx": to_phx(t.exit_ts),
            "pnl_usd_realized": round(t.pnl_usd_realized, 2),
            "pnl_color": ("green" if t.pnl_usd_realized >= 0 else "red")
        })
    return {"history": rows, "timeframe": tf, "venue": "futures", "updated_at_phx": to_phx(time.time())}


def api_pnl(tf: str = "1D"):
    """P&L summary and time series endpoint."""
    series = pnl_series(tf)
    portfolio = get_portfolio_value()
    
    if not series:
        return {
            "summary": {
                "timeframe": tf,
                "total_pnl_usd": 0.0,
                "win_rate_pct": 0.0,
                "avg_trade_pnl_usd": 0.0,
                "trades_count": 0,
                "time_series": []
            },
            "portfolio": portfolio,
            "updated_at_phx": to_phx(time.time())
        }

    total = series[-1]["pnl_usd"] if series else 0
    
    closed = get_closed_trades(tf)
    wins = sum(1 for t in closed if t.pnl_usd_realized > 0)
    count = len(closed)
    win_rate = (wins / count * 100.0) if count > 0 else 0.0
    avg_pnl = (sum(t.pnl_usd_realized for t in closed) / count) if count > 0 else 0.0

    return {
        "summary": {
            "timeframe": tf,
            "total_pnl_usd": round(total, 2),
            "win_rate_pct": round(win_rate, 2),
            "avg_trade_pnl_usd": round(avg_pnl, 2),
            "trades_count": count,
            "time_series": series
        },
        "portfolio": portfolio,
        "updated_at_phx": to_phx(time.time())
    }


def api_pnl_spot(tf: str = "1D"):
    """Spot-only P&L summary and time series endpoint."""
    series = pnl_series_spot(tf)
    
    total = series[-1]["pnl_usd"] if series else 0
    closed = get_closed_trades_spot(tf)
    wins = sum(1 for t in closed if t.pnl_usd_realized > 0)
    count = len(closed)
    win_rate = (wins / count * 100.0) if count > 0 else 0.0
    avg_pnl = (sum(t.pnl_usd_realized for t in closed) / count) if count > 0 else 0.0

    return {
        "summary": {
            "venue": "spot",
            "timeframe": tf,
            "total_pnl_usd": round(total, 2),
            "win_rate_pct": round(win_rate, 2),
            "avg_trade_pnl_usd": round(avg_pnl, 2),
            "trades_count": count,
            "time_series": series
        },
        "updated_at_phx": to_phx(time.time())
    }


def api_pnl_futures(tf: str = "1D"):
    """Futures-only P&L summary and time series endpoint."""
    series = pnl_series_futures(tf)
    
    total = series[-1]["pnl_usd"] if series else 0
    closed = get_closed_trades_futures(tf)
    wins = sum(1 for t in closed if t.pnl_usd_realized > 0)
    count = len(closed)
    win_rate = (wins / count * 100.0) if count > 0 else 0.0
    avg_pnl = (sum(t.pnl_usd_realized for t in closed) / count) if count > 0 else 0.0

    return {
        "summary": {
            "venue": "futures",
            "timeframe": tf,
            "total_pnl_usd": round(total, 2),
            "win_rate_pct": round(win_rate, 2),
            "avg_trade_pnl_usd": round(avg_pnl, 2),
            "trades_count": count,
            "time_series": series
        },
        "updated_at_phx": to_phx(time.time())
    }
