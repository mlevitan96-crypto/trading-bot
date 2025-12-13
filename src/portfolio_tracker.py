"""
Portfolio tracker with $10,000 starting capital and hourly P&L tracking.
"""
import json
import math
from datetime import datetime
from pathlib import Path
import pytz
from src.performance_tracker import track_performance
from src.fee_calculator import get_net_profit_after_fees

PORTFOLIO_FILE = "logs/portfolio.json"


def _sanitize_numeric(value, default=0.0, field_name="unknown"):
    """
    Sanitize numeric values to prevent NaN/Inf from corrupting data.
    
    CRITICAL: This prevents cascading data corruption throughout the system.
    NaN values in portfolio data propagate to position sizing, P&L calculations,
    and dashboard displays, causing system-wide failures.
    """
    if value is None:
        return default
    try:
        float_val = float(value)
        if math.isnan(float_val) or math.isinf(float_val):
            print(f"   ⚠️ [SANITIZE] {field_name} was {value}, reset to {default}")
            return default
        return float_val
    except (TypeError, ValueError):
        print(f"   ⚠️ [SANITIZE] {field_name} invalid ({value}), reset to {default}")
        return default


PNL_FILE = "logs/pnl_hourly.json"
STARTING_CAPITAL = 10000.0
ARIZONA_TZ = pytz.timezone('America/Phoenix')

def get_arizona_time():
    """Get current time in Arizona timezone."""
    return datetime.now(ARIZONA_TZ)

def initialize_portfolio():
    """Initialize portfolio with $10,000 starting capital."""
    Path("logs").mkdir(exist_ok=True)
    
    if not Path(PORTFOLIO_FILE).exists():
        portfolio = {
            "starting_capital": STARTING_CAPITAL,
            "current_value": STARTING_CAPITAL,
            "cash": STARTING_CAPITAL,
            "positions": {},
            "trades": [],
            "total_trades_count": 0,
            "snapshots": [],
            "created_at": get_arizona_time().isoformat()
        }
        with open(PORTFOLIO_FILE, 'w') as f:
            json.dump(portfolio, f, indent=2)
    
    if not Path(PNL_FILE).exists():
        pnl = {
            "hourly_records": [],
            "created_at": get_arizona_time().isoformat()
        }
        with open(PNL_FILE, 'w') as f:
            json.dump(pnl, f, indent=2)

def load_portfolio():
    """Load current portfolio state with NaN protection."""
    initialize_portfolio()
    with open(PORTFOLIO_FILE, 'r') as f:
        portfolio = json.load(f)
    
    # CRITICAL: Sanitize all numeric fields to prevent NaN cascading
    portfolio["current_value"] = _sanitize_numeric(
        portfolio.get("current_value"), STARTING_CAPITAL, "current_value"
    )
    portfolio["cash"] = _sanitize_numeric(
        portfolio.get("cash"), portfolio["current_value"], "cash"
    )
    portfolio["starting_capital"] = _sanitize_numeric(
        portfolio.get("starting_capital"), STARTING_CAPITAL, "starting_capital"
    )
    
    return portfolio

def save_portfolio(portfolio):
    """Save portfolio state with NaN protection."""
    # CRITICAL: Sanitize before saving to prevent corrupted data on disk
    portfolio["current_value"] = _sanitize_numeric(
        portfolio.get("current_value"), STARTING_CAPITAL, "current_value"
    )
    portfolio["cash"] = _sanitize_numeric(
        portfolio.get("cash"), portfolio["current_value"], "cash"
    )
    
    with open(PORTFOLIO_FILE, 'w') as f:
        json.dump(portfolio, f, indent=2)

def record_trade(symbol, side, amount, price, strategy_name, roi, position_pct=0.15, 
                 entry_price=None, exit_price=None, quantity=None):
    """
    Record a trade and update portfolio value based on realistic position-based P&L with trading fees.
    
    Trading fees:
    - Maker: 0.02% (limit orders)
    - Taker: 0.06% (market orders) - used for all simulated trades
    
    Args:
        symbol: Trading pair (e.g., 'BTCUSDT')
        side: 'buy' or 'sell'
        amount: Amount traded (for display purposes)
        price: Current price (for display purposes)
        strategy_name: Name of the strategy
        roi: Strategy ROI (e.g., 0.008 for 0.8%)
        position_pct: Percentage of portfolio to allocate to this trade (default 15%)
        entry_price: Entry price for the position (optional, for transparency)
        exit_price: Exit price for the position (optional, for transparency)
        quantity: Actual quantity in base asset units (optional, for transparency)
    """
    # Filter out test/validation trades from production portfolio metrics
    # Phase82 validation tests and other test strategies should not affect production P&L
    if strategy_name and ("PHASE82" in strategy_name.upper() or "TEST" in strategy_name.upper()):
        print(f"   🧪 [TEST-TRADE-EXCLUDED] Skipping portfolio update for test strategy: {strategy_name}")
        return 0  # Return 0 to indicate no portfolio impact
    
    portfolio = load_portfolio()
    current_time = get_arizona_time().isoformat()
    
    # CRITICAL: Sanitize all inputs to prevent NaN cascading
    safe_roi = _sanitize_numeric(roi, 0.0, "roi")
    safe_position_pct = _sanitize_numeric(position_pct, 0.15, "position_pct")
    safe_price = _sanitize_numeric(price, 0.0, "price")
    
    position_size = portfolio["current_value"] * safe_position_pct
    position_size = _sanitize_numeric(position_size, 200.0, "position_size")
    
    gross_profit = position_size * safe_roi
    gross_profit = _sanitize_numeric(gross_profit, 0.0, "gross_profit")
    
    net_profit, total_fees = get_net_profit_after_fees(position_size, safe_roi, order_type="taker")
    net_profit = _sanitize_numeric(net_profit, 0.0, "net_profit")
    total_fees = _sanitize_numeric(total_fees, 0.0, "total_fees")
    
    portfolio["current_value"] = _sanitize_numeric(
        portfolio["current_value"] + net_profit, STARTING_CAPITAL, "new_current_value"
    )
    
    # Set defaults based on trade side
    if side.lower() in ["buy", "long"]:
        # For entry trades: entry_price is the trade price, no exit yet
        final_entry_price = entry_price if entry_price is not None else price
        final_exit_price = exit_price if exit_price is not None else 0
    else:
        # For exit trades: entry_price should be provided, exit_price is the trade price
        final_entry_price = entry_price if entry_price is not None else 0
        final_exit_price = exit_price if exit_price is not None else price
    
    trade = {
        "timestamp": current_time,
        "symbol": symbol,
        "side": side,
        "entry_price": final_entry_price,
        "exit_price": final_exit_price,
        "quantity": quantity if quantity is not None else amount,
        "amount": amount,
        "price": price,
        "position_size": position_size,
        "position_pct": position_pct * 100,
        "strategy": strategy_name,
        "roi": roi,
        "gross_profit": gross_profit,
        "fees": total_fees,
        "profit": net_profit
    }
    
    # Increment total trade count before appending (continuously increasing, no cap)
    portfolio["total_trades_count"] = portfolio.get("total_trades_count", len(portfolio["trades"])) + 1
    
    # Update aggregate stats
    portfolio["total_trading_fees"] = portfolio.get("total_trading_fees", 0.0) + total_fees
    
    # Update realized P&L (only for sell/exit trades)
    if side.lower() in ["sell", "short", "close"]:
        portfolio["realized_pnl"] = portfolio.get("realized_pnl", 0.0) + net_profit
        portfolio["total_trades"] = portfolio.get("total_trades", 0) + 1
        
        # Track wins/losses
        if net_profit > 0:
            portfolio["winning_trades"] = portfolio.get("winning_trades", 0) + 1
        else:
            portfolio["losing_trades"] = portfolio.get("losing_trades", 0) + 1
    
    portfolio["trades"].append(trade)
    
    # Keep only recent trades in memory (last 2000) for performance
    if len(portfolio["trades"]) > 2000:
        portfolio["trades"] = portfolio["trades"][-2000:]
    
    total_return = ((portfolio["current_value"] - STARTING_CAPITAL) / STARTING_CAPITAL) * 100
    
    snapshot = {
        "timestamp": current_time,
        "portfolio_value": portfolio["current_value"],
        "cash": portfolio.get("cash", portfolio["current_value"]),
        "total_return_pct": total_return,
        "strategy": strategy_name,
        "roi": roi,
        "gross_profit": gross_profit,
        "fees": total_fees,
        "profit": net_profit,
        "position_size": position_size
    }
    
    # Ensure snapshots field exists (for compatibility with old portfolios)
    if "snapshots" not in portfolio:
        portfolio["snapshots"] = []
    
    portfolio["snapshots"].append(snapshot)
    
    if len(portfolio["snapshots"]) > 1000:
        portfolio["snapshots"] = portfolio["snapshots"][-1000:]
    
    save_portfolio(portfolio)
    
    track_performance(portfolio["current_value"])
    
    return portfolio["current_value"]

def record_hourly_pnl():
    """Record hourly P&L snapshot."""
    portfolio = load_portfolio()
    
    with open(PNL_FILE, 'r') as f:
        pnl_data = json.load(f)
    
    current_time = get_arizona_time()
    current_hour = current_time.replace(minute=0, second=0, microsecond=0).isoformat()
    
    if pnl_data["hourly_records"] and pnl_data["hourly_records"][-1]["hour"] == current_hour:
        return
    
    current_value = portfolio["current_value"]
    profit = current_value - STARTING_CAPITAL
    profit_pct = (profit / STARTING_CAPITAL) * 100
    
    if pnl_data["hourly_records"]:
        last_value = pnl_data["hourly_records"][-1]["portfolio_value"]
        hourly_change = current_value - last_value
        hourly_change_pct = (hourly_change / last_value) * 100 if last_value > 0 else 0
    else:
        hourly_change = profit
        hourly_change_pct = profit_pct
    
    record = {
        "hour": current_hour,
        "timestamp": current_time.isoformat(),
        "portfolio_value": current_value,
        "total_profit": profit,
        "total_profit_pct": profit_pct,
        "hourly_change": hourly_change,
        "hourly_change_pct": hourly_change_pct,
        "num_trades": len(portfolio["trades"])
    }
    
    pnl_data["hourly_records"].append(record)
    
    if len(pnl_data["hourly_records"]) > 168:
        pnl_data["hourly_records"] = pnl_data["hourly_records"][-168:]
    
    with open(PNL_FILE, 'w') as f:
        json.dump(pnl_data, f, indent=2)

def get_portfolio_stats():
    """Get current portfolio statistics."""
    portfolio = load_portfolio()
    
    current_value = portfolio["current_value"]
    profit = current_value - STARTING_CAPITAL
    profit_pct = (profit / STARTING_CAPITAL) * 100
    
    return {
        "starting_capital": STARTING_CAPITAL,
        "current_value": current_value,
        "total_profit": profit,
        "total_profit_pct": profit_pct,
        "num_trades": len(portfolio["trades"]),
        "num_snapshots": len(portfolio["snapshots"])
    }

def get_hourly_pnl():
    """Get hourly P&L records."""
    if not Path(PNL_FILE).exists():
        initialize_portfolio()
        return []
    
    with open(PNL_FILE, 'r') as f:
        pnl_data = json.load(f)
    
    return pnl_data.get("hourly_records", [])

def get_recent_trades(limit=20):
    """Get recent trades."""
    portfolio = load_portfolio()
    trades = portfolio.get("trades", [])
    return trades[-limit:] if trades else []

def get_portfolio_history(limit=100):
    """Get portfolio value history."""
    portfolio = load_portfolio()
    snapshots = portfolio.get("snapshots", [])
    return snapshots[-limit:] if snapshots else []
