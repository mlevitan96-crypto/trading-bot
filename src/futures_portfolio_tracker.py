"""
Futures portfolio tracker with separate persistence from spot trading.
Tracks margin collateral, leveraged positions, and funding fees.
"""
import json
import math
from datetime import datetime
from pathlib import Path
import pytz
from src.infrastructure.path_registry import PathRegistry

# Use DataRegistry for safe writes with backup
try:
    from src.data_registry import DataRegistry as DR
    USE_SAFE_WRITE = True
except ImportError:
    USE_SAFE_WRITE = False


def _sanitize_numeric(value, default=0.0, field_name="unknown"):
    """Sanitize numeric values to prevent NaN/Inf from corrupting data."""
    if value is None:
        return default
    try:
        float_val = float(value)
        if math.isnan(float_val) or math.isinf(float_val):
            print(f"   ⚠️ [FUTURES-SANITIZE] {field_name} was {value}, reset to {default}")
            return default
        return float_val
    except (TypeError, ValueError):
        return default

PORTFOLIO_FUTURES_FILE = str(PathRegistry.PORTFOLIO_LOG)
TRADES_FUTURES_FILE = PathRegistry.get_path("logs", "trades_futures.json")
STARTING_MARGIN = 0.0  # Futures starts with 0, funded from main portfolio
ARIZONA_TZ = pytz.timezone('America/Phoenix')

def get_arizona_time():
    """Get current time in Arizona timezone."""
    return datetime.now(ARIZONA_TZ)


def initialize_futures_portfolio():
    """Initialize futures portfolio tracking with safe writes - NO FALLBACK."""
    PathRegistry.LOGS_DIR.mkdir(exist_ok=True)
    PathRegistry.LOGS_BACKUPS_DIR.mkdir(exist_ok=True)
    
    if not Path(PORTFOLIO_FUTURES_FILE).exists():
        portfolio = {
            "total_margin_allocated": STARTING_MARGIN,
            "available_margin": STARTING_MARGIN,
            "used_margin": 0.0,
            "unrealized_pnl": 0.0,
            "realized_pnl": 0.0,
            "total_funding_fees": 0.0,
            "total_trading_fees": 0.0,
            "open_positions_count": 0,
            "total_notional_exposure": 0.0,
            "effective_leverage": 0.0,
            "snapshots": [],
            "created_at": get_arizona_time().isoformat()
        }
        # CRITICAL: Always use safe write - fail fast if unavailable
        if USE_SAFE_WRITE:
            DR.safe_write_json_with_backup(PORTFOLIO_FUTURES_FILE, portfolio)
        else:
            # Atomic write with fsync even in fallback
            tmp_path = PORTFOLIO_FUTURES_FILE + '.tmp'
            with open(tmp_path, 'w') as f:
                json.dump(portfolio, f, indent=2)
                f.flush()
                import os as _os
                _os.fsync(f.fileno())
            _os.rename(tmp_path, PORTFOLIO_FUTURES_FILE)
    
    if not Path(TRADES_FUTURES_FILE).exists():
        trades = {
            "trades": [],
            "total_trades_count": 0,
            "created_at": get_arizona_time().isoformat()
        }
        # CRITICAL: Always use safe write - fail fast if unavailable
        if USE_SAFE_WRITE:
            DR.safe_write_json_with_backup(TRADES_FUTURES_FILE, trades)
        else:
            # Atomic write with fsync even in fallback
            tmp_path = TRADES_FUTURES_FILE + '.tmp'
            with open(tmp_path, 'w') as f:
                json.dump(trades, f, indent=2)
                f.flush()
                import os as _os
                _os.fsync(f.fileno())
            _os.rename(tmp_path, TRADES_FUTURES_FILE)


def load_futures_portfolio():
    """Load current futures portfolio state with corruption safeguards."""
    initialize_futures_portfolio()
    with open(PORTFOLIO_FUTURES_FILE, 'r') as f:
        portfolio = json.load(f)
    
    # SAFEGUARD: Prevent negative/zero margin from blocking ALL trading
    # If margin is corrupted, reset to default starting capital
    DEFAULT_MARGIN = 6000.0
    
    margin = portfolio.get("total_margin_allocated", 0)
    available = portfolio.get("available_margin", 0)
    
    if margin <= 0 or available < -100:
        print(f"⚠️ [PORTFOLIO-SAFEGUARD] Corrupted margin detected: allocated=${margin}, available=${available}")
        print(f"⚠️ [PORTFOLIO-SAFEGUARD] Resetting to default ${DEFAULT_MARGIN} to prevent trading freeze")
        portfolio["total_margin_allocated"] = DEFAULT_MARGIN
        portfolio["available_margin"] = DEFAULT_MARGIN - portfolio.get("used_margin", 0)
        # Persist the fix
        save_futures_portfolio(portfolio)
    
    return portfolio


def save_futures_portfolio(portfolio):
    """Save futures portfolio state with atomic write, fsync, and backup."""
    # CRITICAL: Sanitize all numeric fields before saving
    numeric_fields = [
        "total_margin_allocated", "available_margin", "used_margin",
        "unrealized_pnl", "realized_pnl", "total_funding_fees",
        "total_trading_fees", "total_notional_exposure", "effective_leverage"
    ]
    for field in numeric_fields:
        if field in portfolio:
            portfolio[field] = _sanitize_numeric(portfolio.get(field), 0.0, field)
    
    if USE_SAFE_WRITE:
        DR.safe_write_json_with_backup(PORTFOLIO_FUTURES_FILE, portfolio)
    else:
        # Fallback to atomic temp file write with fsync for durability
        tmp_path = PORTFOLIO_FUTURES_FILE + '.tmp'
        with open(tmp_path, 'w') as f:
            json.dump(portfolio, f, indent=2)
            f.flush()
            import os as _os
            _os.fsync(f.fileno())
        _os.rename(tmp_path, PORTFOLIO_FUTURES_FILE)


def load_futures_trades():
    """Load futures trades history."""
    initialize_futures_portfolio()
    with open(TRADES_FUTURES_FILE, 'r') as f:
        return json.load(f)


def save_futures_trades(trades_data):
    """Save futures trades history with atomic write, fsync, and backup."""
    if USE_SAFE_WRITE:
        DR.safe_write_json_with_backup(TRADES_FUTURES_FILE, trades_data)
    else:
        # Fallback to atomic temp file write with fsync for durability
        tmp_path = TRADES_FUTURES_FILE + '.tmp'
        with open(tmp_path, 'w') as f:
            json.dump(trades_data, f, indent=2)
            f.flush()
            import os as _os
            _os.fsync(f.fileno())
        _os.rename(tmp_path, TRADES_FUTURES_FILE)


def allocate_margin_from_spot(amount):
    """
    Allocate margin capital from main portfolio to futures trading.
    
    Args:
        amount: USD amount to allocate as margin collateral
    
    Returns:
        bool: True if successful
    """
    portfolio = load_futures_portfolio()
    portfolio["total_margin_allocated"] += amount
    portfolio["available_margin"] += amount
    
    snapshot = {
        "timestamp": get_arizona_time().isoformat(),
        "action": "margin_allocation",
        "amount": amount,
        "total_margin": portfolio["total_margin_allocated"],
        "available_margin": portfolio["available_margin"]
    }
    portfolio["snapshots"].append(snapshot)
    
    save_futures_portfolio(portfolio)
    return True


def record_futures_trade(symbol, direction, entry_price, exit_price, margin_collateral, leverage, 
                         strategy_name, funding_fees=0.0, trading_fees_usd=None, order_type="taker", 
                         duration_seconds=None, was_inverted=False):
    """
    Record a closed futures trade with leverage-adjusted P&L.
    
    Args:
        symbol: Trading pair (e.g., 'BTC-USDT')
        direction: 'LONG' or 'SHORT'
        entry_price: Entry price
        exit_price: Exit price
        margin_collateral: Margin posted for this trade
        leverage: Leverage multiplier used
        strategy_name: Strategy name
        funding_fees: Accumulated funding fees (positive = paid, negative = received)
        trading_fees_usd: Explicit trading fees from Blofin API (if available)
        order_type: "maker" or "taker" (default: "taker" for market orders)
        duration_seconds: Trade duration in seconds (from opened_at to closed_at)
        was_inverted: True if this trade was opened via counter-signal inversion
    
    Returns:
        dict: Trade record with calculated P&L
    """
    portfolio = load_futures_portfolio()
    trades_data = load_futures_trades()
    current_time = get_arizona_time().isoformat()
    
    # Calculate price ROI based on direction
    if direction == "LONG":
        price_roi = (exit_price - entry_price) / entry_price
    else:  # SHORT
        price_roi = (entry_price - exit_price) / entry_price
    
    # Apply leverage to ROI
    leveraged_roi = price_roi * leverage
    
    # Calculate trading fees using actual Blofin rates or explicit fees from API
    # Two-path fee handling:
    # 1. Live trading: Use explicit fees from Blofin API response when available
    # 2. Paper trading: Estimate fees using fee_calculator based on order type
    #    - Market orders = taker fees (0.06%)
    #    - Limit orders = maker fees (0.02%)
    #    - Both entry and exit fees are assessed on notional value
    if trading_fees_usd is not None:
        # Path 1: Use explicit fees from Blofin API response
        pass
    else:
        # Path 2: Estimate fees using fee_calculator for paper trading
        from src.fee_calculator import calculate_trading_fee
        import os
        # Get current exchange for correct fee rates
        exchange = os.getenv("EXCHANGE", "blofin").lower()
        notional_size = margin_collateral * leverage
        # Entry fee + exit fee (both assessed on notional)
        trading_fees_usd = calculate_trading_fee(notional_size, order_type, exchange=exchange) * 2
    
    trading_fees_roi = trading_fees_usd / margin_collateral if margin_collateral > 0 else 0
    funding_fees_roi = funding_fees / margin_collateral if margin_collateral > 0 else 0
    
    # Net ROI on margin
    net_roi = leveraged_roi - trading_fees_roi - funding_fees_roi
    
    # Calculate dollar P&L
    gross_pnl = margin_collateral * leveraged_roi
    net_pnl = margin_collateral * net_roi
    
    # Ensure portfolio has all required fields (migration safety)
    if "total_funding_fees" not in portfolio:
        portfolio["total_funding_fees"] = 0.0
    if "total_trading_fees" not in portfolio:
        portfolio["total_trading_fees"] = 0.0
    
    # Update portfolio
    portfolio["realized_pnl"] += net_pnl
    portfolio["total_funding_fees"] += funding_fees
    portfolio["total_trading_fees"] += trading_fees_usd
    portfolio["available_margin"] += margin_collateral  # Return margin after close
    portfolio["used_margin"] = max(0, portfolio["used_margin"] - margin_collateral)
    
    # Calculate quantity (number of contracts/units)
    quantity = (margin_collateral * leverage) / entry_price if entry_price > 0 else 0
    
    # Record trade
    trade = {
        "timestamp": current_time,
        "symbol": symbol,
        "side": "buy" if direction == "LONG" else "sell",  # Dashboard compatibility
        "direction": direction,
        "entry_price": entry_price,
        "exit_price": exit_price,
        "quantity": quantity,
        "margin_collateral": margin_collateral,
        "leverage": leverage,
        "notional_size": margin_collateral * leverage,
        "strategy": strategy_name,
        "price_roi": price_roi,
        "leveraged_roi": leveraged_roi,
        "net_roi": net_roi,
        "gross_pnl": gross_pnl,
        "trading_fees": trading_fees_usd,
        "funding_fees": funding_fees,
        "net_pnl": net_pnl,
        "pnl": net_pnl,  # Dashboard compatibility (USD P&L)
        "pnl_pct": net_roi * 100,  # Dashboard compatibility (% P&L)
        "duration_seconds": duration_seconds if duration_seconds is not None else 0,  # V6.6/V7.1 FIX: Grace window validation
        "venue": "futures"  # Mark as futures trade
    }
    
    # Ensure trades_data has all required fields (migration safety)
    if "trades" not in trades_data:
        trades_data["trades"] = []
    
    # Increment total trade count before appending (continuously increasing, no cap)
    trades_data["total_trades_count"] = trades_data.get("total_trades_count", len(trades_data["trades"])) + 1
    
    trades_data["trades"].append(trade)
    
    # Keep only recent trades in memory (last 2000) for performance
    if len(trades_data["trades"]) > 2000:
        trades_data["trades"] = trades_data["trades"][-2000:]
    
    # Take snapshot
    snapshot = {
        "timestamp": current_time,
        "action": "trade_close",
        "symbol": symbol,
        "strategy": strategy_name,
        "net_pnl": net_pnl,
        "total_realized_pnl": portfolio["realized_pnl"],
        "available_margin": portfolio["available_margin"],
        "used_margin": portfolio["used_margin"]
    }
    
    # Ensure portfolio has snapshots field (migration safety)
    if "snapshots" not in portfolio:
        portfolio["snapshots"] = []
    
    portfolio["snapshots"].append(snapshot)
    
    if len(portfolio["snapshots"]) > 1000:
        portfolio["snapshots"] = portfolio["snapshots"][-1000:]
    
    save_futures_portfolio(portfolio)
    save_futures_trades(trades_data)
    
    # Sync to executed_trades.jsonl for learning systems (v5.8 data integrity fix)
    try:
        from src.data_sync_module import sync_single_trade
        sync_single_trade(trade)
    except Exception as e:
        print(f"⚠️ Data sync warning: {e}")  # Non-critical, log but don't break trade recording
    
    # Daily stats: Record futures trade completion
    try:
        from src.daily_stats_tracker import record_futures_trade as record_daily_futures_trade
        is_win = net_roi > 0
        record_daily_futures_trade(net_pnl, is_win)
    except Exception as e:
        pass  # Fail silently to avoid breaking trade recording
    
    # Counter-Signal Orchestrator: Record outcome for pattern learning
    # was_inverted is passed from trade open time (stored in position metadata)
    try:
        from src.counter_signal_orchestrator import record_signal_outcome
        record_signal_outcome(
            symbol=symbol,
            direction=direction,
            pnl=net_pnl,
            was_inverted=was_inverted
        )
    except Exception as e:
        pass  # Fail silently
    
    return trade


def update_margin_usage(margin_change, notional_change=0):
    """
    Update margin usage when opening/closing positions.
    
    Args:
        margin_change: Change in used margin (positive = new position, negative = closed position)
        notional_change: Change in notional exposure (for leverage tracking)
    """
    portfolio = load_futures_portfolio()
    
    portfolio["used_margin"] += margin_change
    portfolio["available_margin"] -= margin_change
    portfolio["total_notional_exposure"] += notional_change
    
    # Calculate effective leverage across portfolio
    if portfolio["used_margin"] > 0:
        portfolio["effective_leverage"] = portfolio["total_notional_exposure"] / portfolio["used_margin"]
    else:
        portfolio["effective_leverage"] = 0.0
    
    save_futures_portfolio(portfolio)


def get_futures_stats():
    """
    Get current futures portfolio statistics.
    
    Returns:
        dict with key metrics
    """
    from src.critical_bug_fixes import calculate_available_margin
    from src.position_manager import get_open_futures_positions
    
    portfolio = load_futures_portfolio()
    trades_data = load_futures_trades()
    
    trades = trades_data.get("trades", [])
    winning_trades = [t for t in trades if t.get("net_pnl", 0) > 0]
    
    # CRITICAL FIX: Recalculate available margin from open positions to prevent inflation
    open_positions = get_open_futures_positions()
    total_margin = portfolio["total_margin_allocated"]
    reserved_margin = 0.0  # Could add reserved funds here
    corrected_available = calculate_available_margin(total_margin, reserved_margin, open_positions)
    
    # Update portfolio if discrepancy detected
    if abs(corrected_available - portfolio["available_margin"]) > 0.01:
        portfolio["available_margin"] = corrected_available
        portfolio["used_margin"] = sum(p.get('margin', 0.0) for p in open_positions)
        save_futures_portfolio(portfolio)
    
    return {
        "total_margin": portfolio["total_margin_allocated"],
        "available_margin": corrected_available,
        "used_margin": portfolio["used_margin"],
        "unrealized_pnl": portfolio["unrealized_pnl"],
        "realized_pnl": portfolio["realized_pnl"],
        "total_pnl": portfolio["unrealized_pnl"] + portfolio["realized_pnl"],
        "total_funding_fees": portfolio["total_funding_fees"],
        "total_trading_fees": portfolio["total_trading_fees"],
        "notional_exposure": portfolio["total_notional_exposure"],
        "effective_leverage": portfolio["effective_leverage"],
        "total_trades": len(trades),
        "winning_trades": len(winning_trades),
        "win_rate": (len(winning_trades) / len(trades) * 100) if trades else 0,
        "open_positions": portfolio["open_positions_count"]
    }


def get_recent_futures_trades(limit=100):
    """
    Get recent futures trades.
    
    Args:
        limit: Maximum number of trades to return
    
    Returns:
        list of recent trades
    """
    trades_data = load_futures_trades()
    trades = trades_data.get("trades", [])
    return trades[-limit:] if trades else []
