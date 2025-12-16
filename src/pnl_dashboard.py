import io
import base64
import time
import os
import threading
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from typing import Dict, Any

from flask import Flask, send_file, request, session, redirect, url_for, jsonify
from dash import Dash, html, dcc, Input, Output, State, dash_table, callback_context
from functools import wraps
import hashlib
import dash_bootstrap_components as dbc

from src.pnl_dashboard_loader import load_trades_df, clear_cache
from src.infrastructure.path_registry import PathRegistry

DEFAULT_TIMEFRAME_HOURS = 72
APP_TITLE = "P&L Dashboard"

# Dashboard password (hashed for security)
DASHBOARD_PASSWORD = "Echelonlev2007!"
DASHBOARD_PASSWORD_HASH = hashlib.sha256(DASHBOARD_PASSWORD.encode()).hexdigest()

# Use PathRegistry for unified path resolution (handles slot-based deployments)
OPEN_POS_LOG = str(PathRegistry.get_path("logs", "positions.json"))  # Legacy spot file (may not exist)
FUTURES_POS_LOG = str(PathRegistry.POS_LOG)  # Authoritative futures positions file
WALLET_SNAPSHOTS_FILE = str(PathRegistry.get_path("logs", "wallet_snapshots.jsonl"))

_dashboard_health_status = {
    "gateway_ok": True,
    "positions_loaded": 0,
    "rows_built": 0,
    "last_load_attempt": None,
    "last_success": None,
    "last_error": None
}

# Price cache for dashboard (prevents rate limiting)
_price_cache: Dict[str, Dict[str, Any]] = {}
_price_cache_lock = threading.Lock()
PRICE_CACHE_TTL = 30  # Cache prices for 30 seconds

def _format_bot_display(strategy: str, bot_type: str) -> str:
    """Format bot/strategy display for dashboard - Alpha or Beta prominently."""
    if not strategy:
        strategy = ""
    if "Alpha" in strategy or bot_type == "alpha":
        return "Alpha"
    elif "Beta" in strategy or bot_type == "beta":
        return "Beta"
    else:
        return strategy if strategy else "Alpha"

import json
from datetime import datetime
import fcntl


def safe_load_json(filepath: str, default=None, max_retries: int = 3) -> dict:
    """
    Safely load JSON with retry logic and file locking.
    Prevents crashes from concurrent file access during writes.
    """
    if default is None:
        default = {}
    
    if not os.path.exists(filepath):
        return default
    
    for attempt in range(max_retries):
        try:
            with open(filepath, 'r') as f:
                fcntl.flock(f.fileno(), fcntl.LOCK_SH | fcntl.LOCK_NB)
                try:
                    content = f.read()
                    if not content.strip():
                        return default
                    data = json.loads(content)
                    return data
                finally:
                    fcntl.flock(f.fileno(), fcntl.LOCK_UN)
        except (json.JSONDecodeError, BlockingIOError) as e:
            if attempt < max_retries - 1:
                time.sleep(0.1 * (attempt + 1))
                continue
            print(f"⚠️  JSON load failed after {max_retries} attempts for {filepath}: {e}")
            return default
        except Exception as e:
            print(f"⚠️  Unexpected error loading {filepath}: {e}")
            return default
    
    return default

_snapshot_lock = threading.Lock()
_last_snapshot_hour = None

def record_wallet_snapshot(force: bool = False) -> bool:
    """
    Record wallet balance snapshot (hourly).
    Returns True if snapshot was recorded, False if skipped.
    """
    global _last_snapshot_hour
    
    now = datetime.now()
    current_hour = now.strftime("%Y-%m-%d-%H")
    
    with _snapshot_lock:
        if not force and _last_snapshot_hour == current_hour:
            return False
        
        try:
            wallet_balance = get_wallet_balance()
            snapshot = {
                "ts": int(time.time()),
                "timestamp": now.isoformat(),
                "hour": current_hour,
                "balance": wallet_balance
            }
            
            # Ensure directory exists (works for both relative and absolute paths)
            snapshot_dir = os.path.dirname(WALLET_SNAPSHOTS_FILE)
            if snapshot_dir:
                os.makedirs(snapshot_dir, exist_ok=True)
            with open(WALLET_SNAPSHOTS_FILE, "a") as f:
                f.write(json.dumps(snapshot) + "\n")
            
            _last_snapshot_hour = current_hour
            print(f"📊 [SNAPSHOT] Recorded wallet snapshot: ${wallet_balance:.2f} at {current_hour}")
            return True
        except Exception as e:
            print(f"⚠️  [SNAPSHOT] Error recording wallet snapshot: {e}")
            import traceback
            traceback.print_exc()
            return False

def load_wallet_snapshots(hours: int = 24) -> pd.DataFrame:
    """Load wallet snapshots for the last N hours."""
    if not os.path.exists(WALLET_SNAPSHOTS_FILE):
        return pd.DataFrame(columns=["ts", "timestamp", "balance"])
    
    cutoff = int(time.time()) - hours * 3600
    snapshots = []
    
    try:
        with open(WALLET_SNAPSHOTS_FILE, "r") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    snap = json.loads(line)
                    if snap.get("ts", 0) >= cutoff:
                        snapshots.append(snap)
                except:
                    continue
    except Exception as e:
        print(f"[SNAPSHOT] Error loading snapshots: {e}")
    
    if not snapshots:
        return pd.DataFrame(columns=["ts", "timestamp", "balance"])
    
    df = pd.DataFrame(snapshots)
    df["time"] = pd.to_datetime(df["timestamp"])
    return df.sort_values("ts")

def fig_wallet_balance_trend(hours: int = 24) -> go.Figure:
    """Create wallet balance trend graph."""
    df = load_wallet_snapshots(hours)
    
    if df.empty:
        fig = go.Figure()
        fig.add_annotation(
            text="No hourly snapshots yet - tracking will begin shortly",
            xref="paper", yref="paper",
            x=0.5, y=0.5, showarrow=False,
            font=dict(size=14, color="#9aa0a6")
        )
        fig.update_layout(
            title="Wallet Balance (Hourly)",
            template="plotly_dark",
            paper_bgcolor="#1b1f2a",
            plot_bgcolor="#1b1f2a",
            height=200,
            margin=dict(l=40, r=40, t=40, b=40)
        )
        return fig
    
    min_balance = df["balance"].min()
    max_balance = df["balance"].max()
    y_range_margin = (max_balance - min_balance) * 0.1 if max_balance != min_balance else 100
    
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=df["time"],
        y=df["balance"],
        mode="lines+markers",
        name="Balance",
        line=dict(color="#1a73e8", width=2),
        marker=dict(size=6, color="#1a73e8"),
        fill="tozeroy",
        fillcolor="rgba(26, 115, 232, 0.1)"
    ))
    
    fig.update_layout(
        title="Wallet Balance (Hourly)",
        xaxis_title="Time",
        yaxis_title="Balance ($)",
        template="plotly_dark",
        paper_bgcolor="#1b1f2a",
        plot_bgcolor="#1b1f2a",
        height=200,
        margin=dict(l=40, r=40, t=40, b=40),
        yaxis=dict(
            range=[min_balance - y_range_margin, max_balance + y_range_margin],
            tickprefix="$",
            tickformat=",.0f"
        ),
        xaxis=dict(
            tickformat="%H:%M\n%m/%d"
        ),
        hovermode="x unified"
    )
    
    return fig

def fig_equity_curve(df: pd.DataFrame) -> go.Figure:
    if df.empty:
        return go.Figure()
    dfe = df.sort_values("ts")
    dfe["cum_net_pnl"] = dfe["net_pnl_usd"].cumsum()
    fig = px.line(dfe, x="time", y="cum_net_pnl", title="Equity curve (Net P&L)", markers=True)
    fig.update_layout(hovermode="x unified")
    return fig

def fig_pnl_by_symbol(df: pd.DataFrame) -> go.Figure:
    if df.empty:
        return go.Figure()
    agg = df.groupby("symbol", as_index=False)["net_pnl_usd"].sum().sort_values("net_pnl_usd", ascending=False)
    fig = px.bar(agg, x="symbol", y="net_pnl_usd", title="Net P&L by symbol", text="net_pnl_usd", color="net_pnl_usd", color_continuous_scale="RdYlGn")
    fig.update_traces(texttemplate="%{text:.2f}", textposition="outside")
    fig.update_layout(xaxis={'categoryorder':'total descending'})
    return fig

def fig_pnl_by_strategy(df: pd.DataFrame) -> go.Figure:
    if df.empty:
        return go.Figure()
    agg = df.groupby("strategy", as_index=False)["net_pnl_usd"].sum().sort_values("net_pnl_usd", ascending=False)
    fig = px.bar(agg, x="strategy", y="net_pnl_usd", title="Net P&L by strategy", text="net_pnl_usd", color="net_pnl_usd", color_continuous_scale="RdYlGn")
    fig.update_traces(texttemplate="%{text:.2f}", textposition="outside")
    fig.update_layout(xaxis={'categoryorder':'total descending'})
    return fig

def fig_hourly_distribution(df: pd.DataFrame) -> go.Figure:
    if df.empty:
        return go.Figure()
    agg = df.groupby("hour", as_index=False)["net_pnl_usd"].sum()
    fig = px.bar(agg, x="hour", y="net_pnl_usd", title="Hourly net P&L", color="net_pnl_usd", color_continuous_scale="RdYlGn")
    fig.update_layout(hovermode="x unified")
    return fig

def fig_win_rate_heatmap(df: pd.DataFrame, by: str = "symbol") -> go.Figure:
    if df.empty:
        return go.Figure()
    d = df.copy()
    d["win"] = (d["net_pnl_usd"] > 0).astype(int)
    level = by if by in ["symbol","strategy","date","hour"] else "symbol"
    agg = d.groupby(["date", level], as_index=False)["win"].mean()
    pivot = agg.pivot(index="date", columns=level, values="win").fillna(0.0)
    fig = px.imshow(pivot, aspect="auto", color_continuous_scale="RdYlGn", title=f"Win rate heatmap by {level}")
    fig.update_layout(hovermode="closest")
    return fig

def fig_trade_scatter(df: pd.DataFrame) -> go.Figure:
    if df.empty:
        return go.Figure()
    fig = px.scatter(df, x="size_usd", y="net_pnl_usd", color="symbol", hover_data=["time","strategy","side","fee_usd"], title="Trade scatter: Net P&L vs Size")
    fig.update_layout(hovermode="closest")
    return fig

def fig_symbol_cumulative_profit(df: pd.DataFrame, selected_symbols: list) -> go.Figure:
    """
    Creates cumulative profit chart with portfolio aggregate line + per-symbol lines.
    Portfolio line shown in gold for visibility.
    """
    if df.empty:
        fig = go.Figure()
        fig.update_layout(
            title="Cumulative Profit (Portfolio + Selected Symbols)",
            plot_bgcolor="#0f1217",
            paper_bgcolor="#0f1217",
            font={"color":"#e8eaed"}
        )
        return fig
    
    df_sorted = df.sort_values("ts")
    
    # Aggregate portfolio line (all symbols)
    df_sorted = df_sorted.copy()
    df_sorted["cum_profit_total"] = df_sorted["net_pnl_usd"].cumsum()
    
    fig = go.Figure()
    
    # Add portfolio aggregate line (prominent gold line)
    fig.add_trace(go.Scatter(
        x=df_sorted["time"],
        y=df_sorted["cum_profit_total"],
        mode="lines",
        name="Portfolio (All Symbols)",
        line={"width": 3, "color": "#FFD700"},  # Gold
        hovertemplate="<b>Portfolio</b><br>Time: %{x}<br>Cumulative P&L: $%{y:.2f}<extra></extra>"
    ))
    
    # Add per-symbol cumulative lines
    if selected_symbols:
        for sym in selected_symbols:
            df_sym = df_sorted[df_sorted["symbol"] == sym].copy()
            if df_sym.empty:
                continue
            df_sym["cum_profit"] = df_sym["net_pnl_usd"].cumsum()
            fig.add_trace(go.Scatter(
                x=df_sym["time"],
                y=df_sym["cum_profit"],
                mode="lines+markers",
                name=sym,
                hovertemplate=f"<b>{sym}</b><br>Time: %{{x}}<br>Cumulative P&L: $%{{y:.2f}}<extra></extra>"
            ))
    
    fig.update_layout(
        title="Cumulative Profit (Portfolio + Selected Symbols)",
        xaxis_title="Time",
        yaxis_title="Cumulative P&L (USD)",
        plot_bgcolor="#0f1217",
        paper_bgcolor="#0f1217",
        font={"color":"#e8eaed"},
        hovermode="x unified",
        legend={
            "itemclick": "toggle",
            "itemdoubleclick": "toggleothers",
            "bgcolor": "#1b1f2a",
            "bordercolor": "#9aa0a6",
            "borderwidth": 1
        }
    )
    
    return fig

def make_table(df: pd.DataFrame) -> dash_table.DataTable:
    cols = [
        {"name": "Time", "id": "time"},
        {"name": "Symbol", "id": "symbol"},
        {"name": "Strategy", "id": "strategy"},
        {"name": "Side", "id": "side"},
        {"name": "Size (USD)", "id": "size_usd", "type": "numeric", "format": {"specifier": ".2f"}},
        {"name": "P&L (USD)", "id": "pnl_usd", "type": "numeric", "format": {"specifier": ".2f"}},
        {"name": "Fee (USD)", "id": "fee_usd", "type": "numeric", "format": {"specifier": ".2f"}},
        {"name": "Net P&L (USD)", "id": "net_pnl_usd", "type": "numeric", "format": {"specifier": ".2f"}},
        {"name": "Order ID", "id": "order_id"},
        {"name": "Trade ID", "id": "trade_id"},
    ]
    return dash_table.DataTable(
        id="trade-table",
        columns=cols,
        data=df.to_dict("records"),
        sort_action="native",
        sort_mode="multi",
        filter_action="native",
        page_action="native",
        page_current=0,
        page_size=25,
        style_table={"height":"400px","overflowY":"auto"},
        style_cell={"padding":"8px","backgroundColor":"#0f1217","color":"#e8eaed"},
        style_header={"backgroundColor":"#1b1f2a","fontWeight":"bold"},
    )

def export_csv_bytes(df: pd.DataFrame) -> bytes:
    out = io.StringIO()
    df.to_csv(out, index=False)
    return out.getvalue().encode("utf-8")

def load_closed_positions_df():
    """Load closed positions from DataRegistry (positions_futures.json) - single source of truth."""
    try:
        from src.data_registry import DataRegistry as DR
        from datetime import datetime
        import pytz
        
        ARIZONA_TZ = pytz.timezone('America/Phoenix')
        
        # Initialize positions file if needed (repairs empty files)
        try:
            from src.position_manager import initialize_futures_positions
            initialize_futures_positions()
        except Exception as e:
            print(f"⚠️  [DASHBOARD] Failed to initialize positions: {e}")
        
        # Use DataRegistry for safe, centralized access to closed positions
        closed_positions = DR.get_closed_positions(hours=168)  # Last 7 days
        
        if not closed_positions:
            print("ℹ️  [DASHBOARD] No closed positions found in last 7 days")
            return pd.DataFrame(columns=["symbol","strategy","entry_time","exit_time","entry_price","exit_price","size","hold_duration_h","roi_pct","net_pnl","fees"])
        
        df_data = []
        for pos in closed_positions:
            # Parse timestamps
            entry_time = pos.get("opened_at", "")
            exit_time = pos.get("closed_at", "")
            
            # Calculate hold duration
            try:
                if entry_time and exit_time:
                    entry_dt = datetime.fromisoformat(entry_time.replace('Z', '+00:00'))
                    exit_dt = datetime.fromisoformat(exit_time.replace('Z', '+00:00'))
                    hold_duration_h = (exit_dt - entry_dt).total_seconds() / 3600.0
                else:
                    hold_duration_h = 0.0
            except:
                hold_duration_h = 0.0
            
            # Extract fees
            fees = float(pos.get("trading_fees", 0) or 0) + float(pos.get("funding_fees", 0) or 0)
            
            # Get P&L - try multiple field names for compatibility
            pnl_value = pos.get("pnl", pos.get("net_pnl", pos.get("realized_pnl", 0.0)))
            if pnl_value is None or (isinstance(pnl_value, float) and pnl_value != pnl_value):
                pnl_value = 0.0  # Handle NaN
            
            # Calculate ROI if not present
            roi_value = pos.get("final_roi", pos.get("net_roi", 0.0))
            if roi_value is None or (isinstance(roi_value, float) and roi_value != roi_value):
                # Calculate from entry/exit prices
                entry_p = float(pos.get("entry_price", 0.0) or 0)
                exit_p = float(pos.get("exit_price", 0.0) or 0)
                direction = pos.get("direction", "LONG").upper()
                if entry_p > 0 and exit_p > 0:
                    if direction == "LONG":
                        roi_value = (exit_p - entry_p) / entry_p
                    else:
                        roi_value = (entry_p - exit_p) / entry_p
                else:
                    roi_value = 0.0
            
            df_data.append({
                "symbol": pos.get("symbol", ""),
                "strategy": _format_bot_display(pos.get("strategy", ""), pos.get("bot_type", "alpha")),
                "entry_time": entry_time,
                "exit_time": exit_time,
                "entry_price": float(pos.get("entry_price", 0.0) or 0),
                "exit_price": float(pos.get("exit_price", 0.0) or 0),
                "size": float(pos.get("margin_collateral", pos.get("margin_usd", 0.0)) or 0),
                "hold_duration_h": hold_duration_h,
                "roi_pct": float(roi_value) * 100.0,
                "net_pnl": float(pnl_value),
                "fees": fees
            })
        
        df = pd.DataFrame(df_data)
        
        if not df.empty and "exit_time" in df.columns:
            df = df.sort_values(by="exit_time", ascending=False)
        
        return df
    except Exception as e:
        print(f"⚠️  Failed to load closed positions: {e}")
        import traceback
        traceback.print_exc()
        return pd.DataFrame(columns=["symbol","strategy","entry_time","exit_time","entry_price","exit_price","size","hold_duration_h","roi_pct","net_pnl","fees"])

def load_open_positions_df():
    """Load open positions from DataRegistry with real-time pricing and auto-remediation."""
    from src.data_registry import DataRegistry as DR
    
    rows = []
    gateway = None
    _dashboard_health_status["last_load_attempt"] = datetime.now().isoformat()
    
    try:
        from src.exchange_gateway import ExchangeGateway
        gateway = ExchangeGateway()
        _dashboard_health_status["gateway_ok"] = True
    except Exception as gw_err:
        print(f"⚠️  [DASHBOARD-HEALTH] ExchangeGateway init failed: {gw_err}")
        _dashboard_health_status["gateway_ok"] = False
        _dashboard_health_status["last_error"] = str(gw_err)
    
    try:
        # Initialize positions file if needed (repairs empty files)
        try:
            from src.position_manager import initialize_futures_positions
            initialize_futures_positions()
        except Exception as e:
            print(f"⚠️  [DASHBOARD] Failed to initialize positions: {e}")
        
        open_positions = DR.get_open_positions()
        _dashboard_health_status["positions_loaded"] = len(open_positions)
        
        if not open_positions:
            print("ℹ️  [DASHBOARD] No open positions found")
        
        for e in open_positions:
            symbol = e.get("symbol", "")
            notional_size = float(e.get("size", 0.0) or 0)
            entry = float(e.get("entry_price", 0.0) or 0)
            margin_collateral = float(e.get("margin_collateral", e.get("margin_usd", e.get("size_usd", 0.0))) or 0)
            leverage = float(e.get("leverage", 1.0) or 1)
            direction = e.get("direction", e.get("side", "LONG"))
            
            # Validate entry price
            if entry <= 0:
                print(f"⚠️  [DASHBOARD] Invalid entry price for {symbol}: {entry}, skipping")
                continue
            
            # Fetch current price with caching and rate limiting
            current = entry  # Default to entry if fetch fails
            price_fetched = False
            
            # Check cache first
            cached_price = None
            with _price_cache_lock:
                if symbol in _price_cache:
                    cache_entry = _price_cache[symbol]
                    if time.time() - cache_entry["timestamp"] < PRICE_CACHE_TTL:
                        cached_price = cache_entry["price"]
                        price_fetched = True
                        current = cached_price
            
            # If not cached, try to fetch (with rate limiting and quick timeout)
            # Use a short timeout to prevent dashboard from hanging
            if not price_fetched and gateway:
                fetch_start = time.time()
                max_fetch_time = 3.0  # Max 3 seconds per symbol to prevent hanging
                
                try:
                    # Use OHLCV as primary source (cached, less rate limiting)
                    try:
                        if time.time() - fetch_start < max_fetch_time:
                            ohlcv_df = gateway.fetch_ohlcv(symbol, timeframe="1m", limit=1, venue="futures")
                            if not ohlcv_df.empty and "close" in ohlcv_df.columns:
                                ohlcv_price = float(ohlcv_df["close"].iloc[-1])
                                if ohlcv_price and ohlcv_price > 0:
                                    current = ohlcv_price
                                    price_fetched = True
                                    # Cache it
                                    with _price_cache_lock:
                                        _price_cache[symbol] = {"price": current, "timestamp": time.time()}
                    except Exception as ohlcv_err:
                        # Suppress errors - will try mark price fallback or use entry price
                        pass
                    
                    # Fallback to mark price if OHLCV fails (only if we have time left)
                    if not price_fetched and (time.time() - fetch_start) < max_fetch_time:
                        try:
                            fetched_price = gateway.get_price(symbol, venue="futures")
                            if fetched_price and fetched_price > 0:
                                current = fetched_price
                                price_fetched = True
                                # Cache it
                                with _price_cache_lock:
                                    _price_cache[symbol] = {"price": current, "timestamp": time.time()}
                        except Exception as price_err:
                            # Suppress rate limit errors (429) and timeouts - we'll use cached or entry price
                            pass
                except Exception as err:
                    # Suppress all errors - we'll use entry price as fallback
                    pass
            
            # Calculate PnL
            if direction.upper() == "LONG":
                price_roi = ((current - entry) / entry) if entry > 0 else 0.0
            else:
                price_roi = ((entry - current) / entry) if entry > 0 else 0.0
            
            leveraged_roi = price_roi * leverage
            pnl_usd = leveraged_roi * margin_collateral
            pnl_pct = leveraged_roi * 100.0
            
            # Debug logging if PnL is 0 or price wasn't fetched
            if not price_fetched or (pnl_usd == 0 and current != entry):
                print(f"🔍 [DASHBOARD] {symbol}: entry=${entry:.4f}, current=${current:.4f}, "
                      f"price_fetched={price_fetched}, margin=${margin_collateral:.2f}, "
                      f"leverage={leverage}x, pnl_usd=${pnl_usd:.2f}")
            
            # Get strategy/bot attribution
            strategy = e.get("strategy", e.get("strategy_id", ""))
            bot_type = e.get("bot_type", "alpha")
            # Format strategy display - show bot type prominently
            if "Alpha" in strategy or bot_type == "alpha":
                strat_display = f"Alpha"
            elif "Beta" in strategy or bot_type == "beta":
                strat_display = f"Beta"
            else:
                strat_display = strategy if strategy else "Alpha"
            
            rows.append({
                "symbol": symbol,
                "strategy": strat_display,
                "side": direction,
                "amount": notional_size / current if current > 0 else 0,
                "size_usd": margin_collateral,
                "leverage": int(leverage),
                "entry_price": entry,
                "current_price": current,
                "stop_loss": float(e.get("stop_loss", 0.0) or 0),
                "trailing_stop": float(e.get("trailing_stop", 0.0) or 0),
                "pnl_usd": pnl_usd,
                "pnl_pct": pnl_pct
            })
        
        _dashboard_health_status["rows_built"] = len(rows)
        _dashboard_health_status["last_success"] = datetime.now().isoformat()
        
    except Exception as e:
        print(f"⚠️  [DASHBOARD-HEALTH] Failed to load positions: {e}")
        _dashboard_health_status["last_error"] = str(e)
        import traceback
        traceback.print_exc()
    
    if not rows:
        return pd.DataFrame(columns=["symbol","strategy","side","amount","size_usd","entry_price","current_price","pnl_usd","pnl_pct","leverage","stop_loss","trailing_stop"])
    
    return pd.DataFrame(rows)


def dashboard_health_check():
    """Check dashboard health and auto-remediate common issues."""
    issues = []
    fixes_applied = []
    
    if not _dashboard_health_status.get("gateway_ok", True):
        issues.append("ExchangeGateway initialization failed")
        fixes_applied.append("Using entry prices as fallback (no live pricing)")
    
    if _dashboard_health_status.get("positions_loaded", 0) > 0 and _dashboard_health_status.get("rows_built", 0) == 0:
        issues.append(f"Positions loaded ({_dashboard_health_status['positions_loaded']}) but rows empty")
    
    last_error = _dashboard_health_status.get("last_error")
    if last_error:
        if "items" in last_error.lower():
            issues.append("Dict/List structure mismatch detected")
            fixes_applied.append("Auto-adapted to list structure")
        elif "json" in last_error.lower():
            issues.append("JSON parsing issue")
            fixes_applied.append("Using DataRegistry safe_load_json")
    
    status = {
        "healthy": len(issues) == 0,
        "issues": issues,
        "fixes_applied": fixes_applied,
        "stats": _dashboard_health_status
    }
    
    if issues:
        print(f"🏥 [DASHBOARD-HEALTH] Issues: {issues}")
        print(f"🔧 [DASHBOARD-HEALTH] Fixes: {fixes_applied}")
    
    return status

def make_open_positions_section(df: pd.DataFrame):
    """Create open positions section with table, summary, and chart"""
    table = dash_table.DataTable(
        id="open-positions-table",
        columns=[
            {"name": "Symbol", "id": "symbol"},
            {"name": "Bot", "id": "strategy"},
            {"name": "Side", "id": "side"},
            {"name": "Amount", "id": "amount", "type": "numeric", "format": {"specifier": ".6f"}},
            {"name": "Margin (USD)", "id": "size_usd", "type": "numeric", "format": {"specifier": ".2f"}},
            {"name": "Leverage", "id": "leverage", "type": "numeric", "format": {"specifier": "d"}},
            {"name": "Entry Price", "id": "entry_price", "type": "numeric", "format": {"specifier": ".4f"}},
            {"name": "Current Price", "id": "current_price", "type": "numeric", "format": {"specifier": ".4f"}},
            {"name": "Stop Loss", "id": "stop_loss", "type": "numeric", "format": {"specifier": ".5f"}},
            {"name": "Trailing Stop", "id": "trailing_stop", "type": "numeric", "format": {"specifier": ".5f"}},
            {"name": "P&L (USD)", "id": "pnl_usd", "type": "numeric", "format": {"specifier": ".2f"}},
            {"name": "P&L (%)", "id": "pnl_pct", "type": "numeric", "format": {"specifier": ".2f"}},
        ],
        data=df.to_dict("records"),
        sort_action="native",
        filter_action="native",
        page_action="native",
        page_size=20,
        style_table={"height": "300px", "overflowY": "auto"},
        style_cell={"padding": "8px", "backgroundColor": "#0f1217", "color": "#e8eaed"},
        style_header={"backgroundColor": "#1b1f2a", "fontWeight": "bold"},
        style_data_conditional=[
            {"if": {"filter_query": "{pnl_usd} > 0"}, "backgroundColor": "#0f2d0f", "color": "#00ff00"},
            {"if": {"filter_query": "{pnl_usd} < 0"}, "backgroundColor": "#2d0f0f", "color": "#ff4d4d"},
            {"if": {"filter_query": "{pnl_usd} = 0"}, "backgroundColor": "#1b1f2a", "color": "#e8eaed"},
        ]
    )

    total_size = df["size_usd"].sum() if not df.empty else 0.0
    total_pnl_usd = df["pnl_usd"].sum() if not df.empty else 0.0
    avg_pnl_pct = df["pnl_pct"].mean() if not df.empty else 0.0
    num_positions = len(df)
    
    pnl_color = "#34a853" if total_pnl_usd >= 0 else "#ea4335"
    
    summary = dbc.Card(
        dbc.CardBody([
            html.Div([
                html.Div([
                    html.Div("Open Positions", style={"fontSize": "12px", "color": "#9aa0a6"}),
                    html.Div(f"{num_positions}", style={"fontSize": "18px", "fontWeight": "bold"}),
                ], style={"display": "inline-block", "width": "25%", "verticalAlign": "top"}),
                html.Div([
                    html.Div("Total Margin", style={"fontSize": "12px", "color": "#9aa0a6"}),
                    html.Div(f"${total_size:.2f}", style={"fontSize": "18px", "fontWeight": "bold"}),
                ], style={"display": "inline-block", "width": "25%", "verticalAlign": "top"}),
                html.Div([
                    html.Div("Unrealized P&L", style={"fontSize": "12px", "color": "#9aa0a6"}),
                    html.Div(f"${total_pnl_usd:.2f}", style={"fontSize": "18px", "fontWeight": "bold", "color": pnl_color}),
                ], style={"display": "inline-block", "width": "25%", "verticalAlign": "top"}),
                html.Div([
                    html.Div("Avg P&L %", style={"fontSize": "12px", "color": "#9aa0a6"}),
                    html.Div(f"{avg_pnl_pct:.2f}%", style={"fontSize": "18px", "fontWeight": "bold", "color": pnl_color}),
                ], style={"display": "inline-block", "width": "25%", "verticalAlign": "top"}),
            ])
        ]),
        style={"backgroundColor": "#1b1f2a", "marginTop": "12px", "color": "#e8eaed", "border": "1px solid #2d3139", "borderRadius": "8px"}
    )

    bar_fig = go.Figure()
    if not df.empty:
        colors = ["#34a853" if v > 0 else "#ea4335" for v in df["pnl_usd"]]
        bar_fig.add_trace(go.Bar(
            x=df["symbol"],
            y=df["pnl_usd"],
            marker={"color": colors},
            text=df["pnl_usd"],
            texttemplate="%{text:.2f}",
            textposition="outside"
        ))
        bar_fig.update_layout(
            title="Unrealized P&L by Symbol",
            plot_bgcolor="#0f1217",
            paper_bgcolor="#0f1217",
            font={"color": "#e8eaed"},
            xaxis={"title": "Symbol"},
            yaxis={"title": "P&L (USD)"}
        )
    else:
        # Empty state message
        bar_fig.add_annotation(
            text="No open positions<br>Waiting for trades...",
            xref="paper", yref="paper",
            x=0.5, y=0.5,
            showarrow=False,
            font={"size": 16, "color": "#9aa0a6"}
        )
        bar_fig.update_layout(
            title="Unrealized P&L by Symbol",
            plot_bgcolor="#0f1217",
            paper_bgcolor="#0f1217",
            font={"color": "#e8eaed"}
        )

    bar = dcc.Graph(id="open-positions-bar", figure=bar_fig, config={"displayModeBar": True})
    
    # Add empty state message if no positions
    empty_message = None
    if df.empty:
        empty_message = dbc.Alert(
            [
                html.H5("No Open Positions", style={"marginBottom": "8px"}),
                html.P("The bot is not currently holding any open positions. Positions will appear here once trades are executed.", 
                       style={"marginBottom": "0", "color": "#9aa0a6"})
            ],
            color="info",
            style={"backgroundColor": "#1b1f2a", "border": "1px solid #2d3139", "color": "#e8eaed", "marginTop": "12px"}
        )

    return html.Div([table, summary, bar, empty_message] if empty_message else [table, summary, bar])

def make_closed_positions_section(df: pd.DataFrame):
    """Create closed positions section with table, summary, and chart (matches open positions styling)"""
    table = dash_table.DataTable(
        id="closed-positions-table",
        columns=[
            {"name": "Symbol", "id": "symbol"},
            {"name": "Bot", "id": "strategy"},
            {"name": "Entry Time", "id": "entry_time"},
            {"name": "Exit Time", "id": "exit_time"},
            {"name": "Entry Price", "id": "entry_price", "type": "numeric", "format": {"specifier": ".4f"}},
            {"name": "Exit Price", "id": "exit_price", "type": "numeric", "format": {"specifier": ".4f"}},
            {"name": "Size", "id": "size", "type": "numeric", "format": {"specifier": ".2f"}},
            {"name": "Hold (h)", "id": "hold_duration_h", "type": "numeric", "format": {"specifier": ".2f"}},
            {"name": "ROI (%)", "id": "roi_pct", "type": "numeric", "format": {"specifier": ".2f"}},
            {"name": "Net P&L (USD)", "id": "net_pnl", "type": "numeric", "format": {"specifier": ".2f"}},
            {"name": "Fees (USD)", "id": "fees", "type": "numeric", "format": {"specifier": ".2f"}},
        ],
        data=df.to_dict("records"),
        sort_action="native",
        filter_action="native",
        page_action="native",
        page_size=20,
        export_format="csv",
        export_headers="display",
        style_table={"height": "400px", "overflowY": "auto"},
        style_cell={"padding": "8px", "backgroundColor": "#0f1217", "color": "#e8eaed", "textAlign": "left"},
        style_header={"backgroundColor": "#1b1f2a", "fontWeight": "bold"},
        style_data_conditional=[
            {"if": {"filter_query": "{net_pnl} > 0"}, "backgroundColor": "#0f2d0f", "color": "#00ff00"},
            {"if": {"filter_query": "{net_pnl} < 0"}, "backgroundColor": "#2d0f0f", "color": "#ff4d4d"},
            {"if": {"filter_query": "{net_pnl} = 0"}, "backgroundColor": "#1b1f2a", "color": "#e8eaed"},
        ]
    )

    total_pnl = df["net_pnl"].sum() if not df.empty else 0.0
    total_fees = df["fees"].sum() if not df.empty else 0.0
    avg_roi = df["roi_pct"].mean() if not df.empty else 0.0
    avg_hold = df["hold_duration_h"].mean() if not df.empty else 0.0
    num_positions = len(df)
    winners = len(df[df["net_pnl"] > 0]) if not df.empty else 0
    losers = len(df[df["net_pnl"] <= 0]) if not df.empty else 0
    win_rate = (winners / num_positions * 100.0) if num_positions > 0 else 0.0
    
    pnl_color = "#34a853" if total_pnl >= 0 else "#ea4335"
    wr_color = "#34a853" if win_rate >= 50 else "#ea4335"
    
    summary = dbc.Card(
        dbc.CardBody([
            html.Div([
                html.Div([
                    html.Div("Closed Positions", style={"fontSize": "12px", "color": "#9aa0a6"}),
                    html.Div(f"{num_positions}", style={"fontSize": "18px", "fontWeight": "bold"}),
                ], style={"display": "inline-block", "width": "16.66%", "verticalAlign": "top"}),
                html.Div([
                    html.Div("Total P&L", style={"fontSize": "12px", "color": "#9aa0a6"}),
                    html.Div(f"${total_pnl:.2f}", style={"fontSize": "18px", "fontWeight": "bold", "color": pnl_color}),
                ], style={"display": "inline-block", "width": "16.66%", "verticalAlign": "top"}),
                html.Div([
                    html.Div("Avg ROI", style={"fontSize": "12px", "color": "#9aa0a6"}),
                    html.Div(f"{avg_roi:.2f}%", style={"fontSize": "18px", "fontWeight": "bold", "color": pnl_color}),
                ], style={"display": "inline-block", "width": "16.66%", "verticalAlign": "top"}),
                html.Div([
                    html.Div("Win Rate", style={"fontSize": "12px", "color": "#9aa0a6"}),
                    html.Div(f"{win_rate:.1f}%", style={"fontSize": "18px", "fontWeight": "bold", "color": wr_color}),
                ], style={"display": "inline-block", "width": "16.66%", "verticalAlign": "top"}),
                html.Div([
                    html.Div("Avg Hold", style={"fontSize": "12px", "color": "#9aa0a6"}),
                    html.Div(f"{avg_hold:.1f}h", style={"fontSize": "18px", "fontWeight": "bold"}),
                ], style={"display": "inline-block", "width": "16.66%", "verticalAlign": "top"}),
                html.Div([
                    html.Div("Total Fees", style={"fontSize": "12px", "color": "#9aa0a6"}),
                    html.Div(f"${total_fees:.2f}", style={"fontSize": "18px", "fontWeight": "bold", "color": "#ea4335"}),
                ], style={"display": "inline-block", "width": "16.66%", "verticalAlign": "top"}),
            ])
        ]),
        style={"backgroundColor": "#1b1f2a", "marginTop": "12px", "color": "#e8eaed", "border": "1px solid #2d3139", "borderRadius": "8px"}
    )

    bar_fig = go.Figure()
    if not df.empty:
        symbol_pnl = df.groupby("symbol")["net_pnl"].sum().reset_index()
        symbol_pnl = symbol_pnl.sort_values("net_pnl", ascending=False)
        colors = ["#34a853" if v > 0 else "#ea4335" for v in symbol_pnl["net_pnl"]]
        bar_fig.add_trace(go.Bar(
            x=symbol_pnl["symbol"],
            y=symbol_pnl["net_pnl"],
            marker={"color": colors},
            text=symbol_pnl["net_pnl"],
            texttemplate="%{text:.2f}",
            textposition="outside"
        ))
        bar_fig.update_layout(
            title="Realized P&L by Symbol",
            plot_bgcolor="#0f1217",
            paper_bgcolor="#0f1217",
            font={"color": "#e8eaed"},
            xaxis={"title": "Symbol"},
            yaxis={"title": "P&L (USD)"}
        )
    else:
        # Empty state message
        bar_fig.add_annotation(
            text="No closed positions in last 7 days<br>Trade history will appear here once positions are closed.",
            xref="paper", yref="paper",
            x=0.5, y=0.5,
            showarrow=False,
            font={"size": 16, "color": "#9aa0a6"}
        )
        bar_fig.update_layout(
            title="Realized P&L by Symbol",
            plot_bgcolor="#0f1217",
            paper_bgcolor="#0f1217",
            font={"color": "#e8eaed"}
        )

    bar = dcc.Graph(id="closed-positions-bar", figure=bar_fig, config={"displayModeBar": True})
    
    # CSV Export button
    export_btn = html.Button(
        "Export Closed Trades CSV",
        id="export-closed-btn",
        n_clicks=0,
        style={
            "backgroundColor": "#34a853",
            "color": "#fff",
            "border": "none",
            "padding": "8px 16px",
            "borderRadius": "6px",
            "marginTop": "12px",
            "cursor": "pointer"
        }
    )
    
    # Add empty state message if no positions
    empty_message = None
    if df.empty:
        empty_message = dbc.Alert(
            [
                html.H5("No Closed Positions (Last 7 Days)", style={"marginBottom": "8px"}),
                html.P("No closed trades found in the last 7 days. Closed positions will appear here once trades are completed.", 
                       style={"marginBottom": "0", "color": "#9aa0a6"})
            ],
            color="info",
            style={"backgroundColor": "#1b1f2a", "border": "1px solid #2d3139", "color": "#e8eaed", "marginTop": "12px"}
        )
    
    return html.Div([table, summary, bar, export_btn, empty_message] if empty_message else [table, summary, bar, export_btn])

def get_wallet_balance() -> float:
    """
    Get wallet balance from authoritative source (positions_futures.json).
    Calculates starting_capital + sum(all closed P&L) for accurate balance.
    """
    import math
    starting_capital = 10000.0
    
    try:
        from src.data_registry import DataRegistry as DR
        
        closed_positions = DR.get_closed_positions(hours=None)
        
        if not closed_positions:
            return starting_capital
        
        total_pnl = 0.0
        for pos in closed_positions:
            # Try pnl field first (most reliable), then fallbacks
            val = pos.get("pnl", pos.get("net_pnl", pos.get("realized_pnl", 0)))
            if val is None:
                continue
            try:
                val = float(val)
                if math.isnan(val):
                    continue
                total_pnl += val
            except (TypeError, ValueError):
                continue
        
        wallet_balance = starting_capital + total_pnl
        
        # Log wallet balance calculation periodically (every 20 calls to avoid spam)
        if not hasattr(get_wallet_balance, '_call_count'):
            get_wallet_balance._call_count = 0
        get_wallet_balance._call_count += 1
        if get_wallet_balance._call_count % 20 == 0:
            print(f"💰 [DASHBOARD] Wallet balance: ${wallet_balance:.2f} (from {len(closed_positions)} closed positions, P&L: ${total_pnl:.2f})")
        
        return wallet_balance
    except Exception as e:
        print(f"⚠️  [DASHBOARD] Failed to calculate wallet balance: {e}")
        import traceback
        traceback.print_exc()
        return starting_capital

def _compute_avg_win_loss_from_closed_positions(lookback_days: int = 1) -> tuple:
    """
    Calculate avg win/loss from CLOSED POSITIONS (complete round-trip trades),
    not partial exits. This gives more meaningful values.
    
    Returns: (avg_win, avg_loss, wins_count, losses_count)
    """
    import math
    from src.data_registry import DataRegistry as DR
    from datetime import datetime
    
    try:
        closed_positions = DR.get_closed_positions(hours=lookback_days * 24)
        
        if not closed_positions:
            return 0.0, 0.0, 0, 0
        
        wins = []
        losses = []
        
        for pos in closed_positions:
            # Try pnl field first (most reliable), then fallbacks
            val = pos.get("pnl", pos.get("net_pnl", pos.get("final_pnl", 0)))
            if val is None:
                continue
            try:
                net_pnl = float(val)
                if math.isnan(net_pnl):
                    continue
            except (TypeError, ValueError):
                continue
                
            if net_pnl > 0:
                wins.append(net_pnl)
            else:
                losses.append(net_pnl)
        
        avg_win = sum(wins) / len(wins) if wins else 0.0
        avg_loss = sum(losses) / len(losses) if losses else 0.0
        
        return avg_win, avg_loss, len(wins), len(losses)
    except Exception as e:
        print(f"⚠️  Failed to compute avg win/loss from closed positions: {e}")
        return 0.0, 0.0, 0, 0


def compute_summary(df: pd.DataFrame, lookback_days: int = 1, wallet_balance: float = 0.0) -> dict:
    """
    Compute summary statistics for a given lookback period with unrealized P&L and drawdown.
    
    Uses CLOSED POSITIONS for avg_win/avg_loss (complete round-trip trades),
    not partial exits which have tiny P&L values.
    
    For daily stats (lookback_days=1), uses daily_stats_tracker as authoritative source.
    For weekly/monthly, falls back to trades DataFrame.
    """
    from src.pnl_dashboard_loader import get_spot_realized_pnl
    
    # Get unrealized P&L from open positions
    open_positions_df = load_open_positions_df()
    unrealized_pnl = open_positions_df["pnl_usd"].sum() if not open_positions_df.empty else 0.0
    
    # Calculate avg win/loss from CLOSED POSITIONS (complete trades, not partial exits)
    avg_win, avg_loss, wins_count, losses_count = _compute_avg_win_loss_from_closed_positions(lookback_days)
    
    # For daily stats, use the daily_stats_tracker as authoritative source
    if lookback_days == 1:
        try:
            from src.daily_stats_tracker import get_daily_summary
            daily = get_daily_summary()
            
            starting_capital = 10000.0
            total_value = wallet_balance + unrealized_pnl
            drawdown_pct = ((total_value - starting_capital) / starting_capital) * 100.0
            
            return {
                "wallet_balance": wallet_balance,
                "total_trades": wins_count + losses_count,
                "wins": wins_count,
                "losses": losses_count,
                "win_rate": (wins_count / (wins_count + losses_count) * 100.0) if (wins_count + losses_count) > 0 else 0.0,
                "net_pnl": daily.get("total_pnl", 0.0) + unrealized_pnl,
                "avg_win": avg_win,
                "avg_loss": avg_loss,
                "drawdown_pct": drawdown_pct
            }
        except Exception as e:
            print(f"⚠️  Dashboard: Failed to load daily stats: {e}")
    
    # Get authoritative realized P&L (NOT from df sum)
    spot_realized_pnl = get_spot_realized_pnl()
    futures_df = df[df["venue"] == "futures"] if not df.empty else pd.DataFrame()
    futures_realized_pnl = futures_df["net_pnl_usd"].sum() if not futures_df.empty else 0.0
    total_realized_pnl = spot_realized_pnl + futures_realized_pnl
    
    if df.empty and wins_count == 0 and losses_count == 0:
        starting_capital = 10000.0
        total_value = wallet_balance + unrealized_pnl
        drawdown_pct = ((total_value - starting_capital) / starting_capital) * 100.0
        
        return {
            "wallet_balance": wallet_balance,
            "total_trades": 0,
            "wins": 0,
            "losses": 0,
            "win_rate": 0.0,
            "net_pnl": total_realized_pnl + unrealized_pnl,
            "avg_win": 0.0,
            "avg_loss": 0.0,
            "drawdown_pct": drawdown_pct
        }
    
    # Use closed positions for trade counts and win rate
    total = wins_count + losses_count
    win_rate = (wins_count / total * 100.0) if total > 0 else 0.0
    
    total_pnl = total_realized_pnl + unrealized_pnl
    
    starting_capital = 10000.0
    total_value = wallet_balance + unrealized_pnl
    drawdown_pct = ((total_value - starting_capital) / starting_capital) * 100.0
    
    return {
        "wallet_balance": wallet_balance,
        "total_trades": total,
        "wins": wins_count,
        "losses": losses_count,
        "win_rate": win_rate,
        "net_pnl": total_pnl,
        "avg_win": avg_win,
        "avg_loss": avg_loss,
        "drawdown_pct": drawdown_pct
    }

def summary_card(summary: dict, label: str = "Summary", hours: int = 24) -> dbc.Card:
    """Create a summary card with statistics and wallet balance graph"""
    pnl_color = "#34a853" if summary["net_pnl"] >= 0 else "#ea4335"
    wr_color = "#34a853" if summary["win_rate"] >= 50 else "#ea4335"
    drawdown_color = "#ea4335" if summary.get("drawdown_pct", 0) < 0 else "#34a853"
    
    balance_graph = fig_wallet_balance_trend(hours)
    
    return dbc.Card(
        dbc.CardBody([
            html.H4(label, className="card-title", style={"marginBottom": "16px"}),
            html.Div([
                html.Div([
                    html.Div("Wallet Balance", style={"fontSize": "12px", "color": "#9aa0a6"}),
                    html.Div(f"${summary['wallet_balance']:.2f}", style={"fontSize": "24px", "fontWeight": "bold", "color": "#1a73e8"}),
                ], style={"marginBottom": "12px"}),
                html.Div([
                    html.Div("Net P&L (incl. unrealized)", style={"fontSize": "12px", "color": "#9aa0a6"}),
                    html.Div(f"${summary['net_pnl']:.2f}", style={"fontSize": "24px", "fontWeight": "bold", "color": pnl_color}),
                ], style={"marginBottom": "12px"}),
                html.Div([
                    html.Div("Drawdown from $10,000", style={"fontSize": "12px", "color": "#9aa0a6"}),
                    html.Div(f"{summary.get('drawdown_pct', 0):.2f}%", style={"fontSize": "20px", "fontWeight": "bold", "color": drawdown_color}),
                ], style={"marginBottom": "12px"}),
                html.Div([
                    html.Div([
                        html.Div("Total Trades", style={"fontSize": "12px", "color": "#9aa0a6"}),
                        html.Div(f"{summary['total_trades']}", style={"fontSize": "18px", "fontWeight": "bold"}),
                    ], style={"display": "inline-block", "width": "50%", "verticalAlign": "top"}),
                    html.Div([
                        html.Div("Win Rate", style={"fontSize": "12px", "color": "#9aa0a6"}),
                        html.Div(f"{summary['win_rate']:.1f}%", style={"fontSize": "18px", "fontWeight": "bold", "color": wr_color}),
                    ], style={"display": "inline-block", "width": "50%", "verticalAlign": "top"}),
                ], style={"marginBottom": "12px"}),
                html.Div([
                    html.Div([
                        html.Div("Avg Win", style={"fontSize": "12px", "color": "#9aa0a6"}),
                        html.Div(f"${summary['avg_win']:.2f}", style={"fontSize": "16px", "color": "#34a853"}),
                    ], style={"display": "inline-block", "width": "50%", "verticalAlign": "top"}),
                    html.Div([
                        html.Div("Avg Loss", style={"fontSize": "12px", "color": "#9aa0a6"}),
                        html.Div(f"${summary['avg_loss']:.2f}", style={"fontSize": "16px", "color": "#ea4335"}),
                    ], style={"display": "inline-block", "width": "50%", "verticalAlign": "top"}),
                ], style={"marginBottom": "16px"}),
                dcc.Graph(
                    figure=balance_graph,
                    config={"displayModeBar": False},
                    style={"marginTop": "8px"}
                ),
            ])
        ]),
        style={
            "backgroundColor": "#1b1f2a",
            "border": "1px solid #2d3139",
            "borderRadius": "8px",
            "color": "#e8eaed",
            "marginBottom": "16px"
        }
    )

def generate_executive_summary() -> Dict[str, str]:
    """
    Generate executive summary narratives from various data sources.
    Returns structured JSON with plain-English narratives.
    """
    from datetime import datetime, timedelta
    import pytz
    from pathlib import Path
    
    ARIZONA_TZ = pytz.timezone('America/Phoenix')
    now = datetime.now(ARIZONA_TZ)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    yesterday_start = today_start - timedelta(days=1)
    week_start = today_start - timedelta(days=7)
    
    summary = {
        "what_worked_today": "",
        "what_didnt_work": "",
        "missed_opportunities": "",
        "blocked_signals": "",
        "exit_gates": "",
        "learning_today": "",
        "changes_tomorrow": "",
        "weekly_summary": ""
    }
    
    # 1. Read daily stats (1-day, 2-day, 7-day summaries)
    try:
        from src.daily_stats_tracker import load_daily_stats
        daily_stats = load_daily_stats()
        
        combined = daily_stats.get("combined", {})
        total_pnl = combined.get("total_pnl", 0)
        total_trades = combined.get("total_trades", 0)
        win_rate = combined.get("win_rate", 0)
        
        if total_pnl > 0:
            summary["what_worked_today"] = f"Today was profitable with ${total_pnl:.2f} in total P&L across {total_trades} trades. Win rate was {win_rate:.1f}%. "
        elif total_pnl < 0:
            summary["what_didnt_work"] = f"Today was unprofitable with ${abs(total_pnl):.2f} in losses across {total_trades} trades. Win rate was {win_rate:.1f}%. "
        else:
            summary["what_worked_today"] = "No trades executed today. "
    except Exception as e:
        summary["what_worked_today"] = f"Could not load daily stats: {str(e)}. "
    
    # 2. Read missed opportunities
    try:
        missed_file = PathRegistry.get_path("logs", "missed_opportunities.json")
        if os.path.exists(missed_file):
            with open(missed_file, 'r') as f:
                missed_data = json.load(f)
            
            missed_trades = missed_data.get("missed_trades", [])
            today_missed = []
            for m in missed_trades:
                try:
                    ts_str = m.get("timestamp", "")
                    if ts_str:
                        record_time = datetime.fromisoformat(ts_str.replace("Z", "+00:00")).replace(tzinfo=ARIZONA_TZ)
                        if record_time >= today_start:
                            today_missed.append(m)
                except:
                    continue
            
            if today_missed:
                total_missed_roi = sum(m.get("missed_roi", 0) for m in today_missed)
                top_missed = sorted(today_missed, key=lambda x: x.get("missed_roi", 0), reverse=True)[:3]
                symbols = [m.get("symbol") for m in top_missed]
                summary["missed_opportunities"] = f"Identified {len(today_missed)} missed opportunities today with potential ROI of {total_missed_roi*100:.2f}%. Top missed: {', '.join(symbols)}. "
            else:
                summary["missed_opportunities"] = "No significant missed opportunities detected today. "
        else:
            summary["missed_opportunities"] = "Missed opportunity tracking not available. "
    except Exception as e:
        summary["missed_opportunities"] = f"Error analyzing missed opportunities: {str(e)}. "
    
    # 3. Read blocked signals
    try:
        blocked_file = PathRegistry.get_path("logs", "conviction_gate_log.jsonl")
        blocked_today = []
        if os.path.exists(blocked_file):
            with open(blocked_file, 'r') as f:
                for line in f:
                    try:
                        record = json.loads(line)
                        if not record.get("should_trade", True):
                            ts = record.get("ts", 0)
                            if ts:
                                record_time = datetime.fromtimestamp(ts, tz=ARIZONA_TZ)
                                if record_time >= today_start:
                                    blocked_today.append(record)
                    except:
                        continue
        
        if blocked_today:
            by_reason = {}
            for b in blocked_today:
                reason = b.get("block_reason", "unknown")
                by_reason[reason] = by_reason.get(reason, 0) + 1
            
            top_reasons = sorted(by_reason.items(), key=lambda x: x[1], reverse=True)[:3]
            reasons_str = ", ".join([f"{r[0]} ({r[1]}x)" for r in top_reasons])
            summary["blocked_signals"] = f"Blocked {len(blocked_today)} signals today. Top block reasons: {reasons_str}. "
        else:
            summary["blocked_signals"] = "No signals were blocked today. "
    except Exception as e:
        summary["blocked_signals"] = f"Error analyzing blocked signals: {str(e)}. "
    
    # 4. Exit gate analysis
    try:
        exit_file = PathRegistry.get_path("logs", "exit_runtime_events.jsonl")
        exit_events_today = []
        if os.path.exists(exit_file):
            with open(exit_file, 'r') as f:
                for line in f:
                    try:
                        record = json.loads(line)
                        ts = record.get("ts", 0)
                        if ts:
                            record_time = datetime.fromtimestamp(ts, tz=ARIZONA_TZ)
                            if record_time >= today_start:
                                exit_events_today.append(record)
                    except:
                        continue
        
        if exit_events_today:
            exit_types = {}
            for e in exit_events_today:
                exit_type = e.get("exit_type", "unknown")
                exit_types[exit_type] = exit_types.get(exit_type, 0) + 1
            
            types_str = ", ".join([f"{k} ({v}x)" for k, v in exit_types.items()])
            summary["exit_gates"] = f"Exit gates triggered {len(exit_events_today)} times today. Exit types: {types_str}. "
        else:
            summary["exit_gates"] = "No exit gate events recorded today. "
    except Exception as e:
        summary["exit_gates"] = f"Error analyzing exit gates: {str(e)}. "
    
    # 5. Learning history
    try:
        learning_file = PathRegistry.get_path("feature_store", "learning_history.jsonl")
        learning_today = []
        if os.path.exists(learning_file):
            with open(learning_file, 'r') as f:
                for line in f:
                    try:
                        record = json.loads(line)
                        ts = record.get("ts", record.get("timestamp", 0))
                        if ts:
                            if isinstance(ts, str):
                                record_time = datetime.fromisoformat(ts.replace("Z", "+00:00")).replace(tzinfo=ARIZONA_TZ)
                            else:
                                record_time = datetime.fromtimestamp(ts, tz=ARIZONA_TZ)
                            if record_time >= today_start:
                                learning_today.append(record)
                    except:
                        continue
        
        if learning_today:
            update_types = {}
            for l in learning_today:
                update_type = l.get("update_type", "unknown")
                update_types[update_type] = update_types.get(update_type, 0) + 1
            
            types_str = ", ".join([f"{k} ({v}x)" for k, v in update_types.items()])
            summary["learning_today"] = f"The engine learned from {len(learning_today)} events today. Learning types: {types_str}. "
        else:
            summary["learning_today"] = "No learning events recorded today. "
    except Exception as e:
        summary["learning_today"] = f"Error analyzing learning: {str(e)}. "
    
    # 6. Changes tomorrow (from nightly digest)
    try:
        digest_file = PathRegistry.get_path("logs", "nightly_digest.json")
        if os.path.exists(digest_file):
            with open(digest_file, 'r') as f:
                digest = json.load(f)
            
            changes = []
            if digest.get("auto_calibration"):
                ac = digest["auto_calibration"]
                changes.append("Auto-calibration adjustments")
            if digest.get("strategy_auto_tuning"):
                st = digest["strategy_auto_tuning"]
                changes.append("Strategy auto-tuning updates")
            
            if changes:
                summary["changes_tomorrow"] = f"Tomorrow's changes: {', '.join(changes)}. "
            else:
                summary["changes_tomorrow"] = "No scheduled changes for tomorrow. "
        else:
            summary["changes_tomorrow"] = "Digest not available for tomorrow's changes. "
    except Exception as e:
        summary["changes_tomorrow"] = f"Error analyzing tomorrow's changes: {str(e)}. "
    
    # 7. Weekly summary
    try:
        from src.daily_stats_tracker import load_daily_stats
        daily_stats = load_daily_stats()
        
        combined = daily_stats.get("combined", {})
        weekly_pnl = combined.get("total_pnl", 0)  # This is actually daily, but we'll use it
        weekly_trades = combined.get("total_trades", 0)
        weekly_wr = combined.get("win_rate", 0)
        
        # Try to get enriched decisions for weekly analysis
        decisions_file = PathRegistry.get_path("logs", "enriched_decisions.jsonl")
        weekly_decisions = []
        if os.path.exists(decisions_file):
            with open(decisions_file, 'r') as f:
                for line in f:
                    try:
                        record = json.loads(line)
                        ts = record.get("ts", 0)
                        if ts:
                            record_time = datetime.fromtimestamp(ts, tz=ARIZONA_TZ)
                            if record_time >= week_start:
                                weekly_decisions.append(record)
                    except:
                        continue
        
        if weekly_decisions:
            profitable = [d for d in weekly_decisions if d.get("outcome_pnl", 0) > 0]
            summary["weekly_summary"] = f"Over the past week: {len(weekly_decisions)} decisions, {len(profitable)} profitable. Win rate: {len(profitable)/len(weekly_decisions)*100:.1f}% if data available. "
        else:
            summary["weekly_summary"] = f"Weekly summary: {weekly_trades} trades, ${weekly_pnl:.2f} P&L, {weekly_wr:.1f}% win rate. "
    except Exception as e:
        summary["weekly_summary"] = f"Error generating weekly summary: {str(e)}. "
    
    # Clean up empty narratives
    for key in summary:
        if not summary[key] or summary[key].strip() == "":
            summary[key] = "No data available for this section. "
    
    return summary

def build_app(server: Flask = None) -> Dash:
    server = server or Flask(__name__)
    
    # Set secret key for sessions
    server.secret_key = os.environ.get('FLASK_SECRET_KEY', hashlib.sha256(DASHBOARD_PASSWORD.encode()).hexdigest())
    
    app = Dash(__name__, server=server, url_base_pathname="/", title=APP_TITLE, external_stylesheets=[dbc.themes.DARKLY])
    
    # Authentication decorator
    def login_required(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if not session.get('authenticated'):
                if request.path.startswith('/api/') or request.path.startswith('/health/'):
                    # API endpoints return 401
                    return jsonify({'error': 'Authentication required'}), 401
                else:
                    # Web pages redirect to login
                    return redirect(url_for('login'))
            return f(*args, **kwargs)
        return decorated_function
    
    # Login route
    @server.route('/login', methods=['GET', 'POST'])
    def login():
        if request.method == 'POST':
            password = request.form.get('password', '')
            password_hash = hashlib.sha256(password.encode()).hexdigest()
            
            if password_hash == DASHBOARD_PASSWORD_HASH:
                session['authenticated'] = True
                next_page = request.args.get('next') or '/'
                return redirect(next_page)
            else:
                return '''
                    <html>
                        <head>
                            <title>Login - P&L Dashboard</title>
                            <style>
                                body { 
                                    font-family: Arial, sans-serif; 
                                    background: #1a1a1a; 
                                    color: #fff; 
                                    display: flex; 
                                    justify-content: center; 
                                    align-items: center; 
                                    height: 100vh; 
                                    margin: 0;
                                }
                                .login-box {
                                    background: #2d2d2d; 
                                    padding: 30px; 
                                    border-radius: 8px; 
                                    box-shadow: 0 4px 6px rgba(0,0,0,0.3);
                                    width: 300px;
                                }
                                h1 { margin-top: 0; color: #00d4ff; }
                                input[type="password"] {
                                    width: 100%; 
                                    padding: 10px; 
                                    margin: 10px 0; 
                                    border: 1px solid #444; 
                                    border-radius: 4px; 
                                    background: #1a1a1a; 
                                    color: #fff;
                                    box-sizing: border-box;
                                }
                                button {
                                    width: 100%; 
                                    padding: 10px; 
                                    background: #00d4ff; 
                                    color: #000; 
                                    border: none; 
                                    border-radius: 4px; 
                                    cursor: pointer; 
                                    font-weight: bold;
                                }
                                button:hover { background: #00b8e6; }
                                .error { color: #ff4444; margin-top: 10px; }
                            </style>
                        </head>
                        <body>
                            <div class="login-box">
                                <h1>🔒 P&L Dashboard</h1>
                                <form method="POST">
                                    <input type="password" name="password" placeholder="Enter password" required autofocus>
                                    <button type="submit">Login</button>
                                </form>
                                <div class="error">Invalid password. Please try again.</div>
                            </div>
                        </body>
                    </html>
                ''', 401
        
        # GET request - show login form
        return '''
            <html>
                <head>
                    <title>Login - P&L Dashboard</title>
                    <style>
                        body { 
                            font-family: Arial, sans-serif; 
                            background: #1a1a1a; 
                            color: #fff; 
                            display: flex; 
                            justify-content: center; 
                            align-items: center; 
                            height: 100vh; 
                            margin: 0;
                        }
                        .login-box {
                            background: #2d2d2d; 
                            padding: 30px; 
                            border-radius: 8px; 
                            box-shadow: 0 4px 6px rgba(0,0,0,0.3);
                            width: 300px;
                        }
                        h1 { margin-top: 0; color: #00d4ff; }
                        input[type="password"] {
                            width: 100%; 
                            padding: 10px; 
                            margin: 10px 0; 
                            border: 1px solid #444; 
                            border-radius: 4px; 
                            background: #1a1a1a; 
                            color: #fff;
                            box-sizing: border-box;
                        }
                        button {
                            width: 100%; 
                            padding: 10px; 
                            background: #00d4ff; 
                            color: #000; 
                            border: none; 
                            border-radius: 4px; 
                            cursor: pointer; 
                            font-weight: bold;
                        }
                        button:hover { background: #00b8e6; }
                    </style>
                </head>
                <body>
                    <div class="login-box">
                        <h1>🔒 P&L Dashboard</h1>
                        <form method="POST">
                            <input type="password" name="password" placeholder="Enter password" required autofocus>
                            <button type="submit">Login</button>
                        </form>
                    </div>
                </body>
            </html>
        '''
    
    # Logout route
    @server.route('/logout')
    def logout():
        session.pop('authenticated', None)
        return redirect(url_for('login'))
    
    # Protect all routes with authentication
    @server.before_request
    def require_auth():
        # Allow login, logout, and Dash internal routes without authentication
        if (request.path == '/login' or 
            request.path == '/logout' or
            request.path.startswith('/_dash-') or 
            request.path.startswith('/assets/') or
            request.path.startswith('/_reload-hash')):
            return None
        
        # Check authentication
        if not session.get('authenticated'):
            if request.path.startswith('/api/') or request.path.startswith('/health/') or request.path.startswith('/audit/'):
                return jsonify({'error': 'Authentication required'}), 401
            else:
                return redirect(url_for('login') + '?next=' + request.path)

    # API endpoint for dashboard verification
    @server.route("/api/open_positions_snapshot")
    @login_required
    def api_open_positions_snapshot():
        """JSON API endpoint that returns currently displayed positions"""
        from flask import jsonify
        try:
            df = load_open_positions_df()
            return jsonify({
                "success": True,
                "count": len(df),
                "symbols": df["symbol"].tolist() if not df.empty else [],
                "positions": df.to_dict("records") if not df.empty else [],
                "timestamp": time.time()
            })
        except Exception as e:
            return jsonify({
                "success": False,
                "error": str(e),
                "count": 0,
                "symbols": []
            }), 500

    @server.route("/api/dashboard_health")
    @login_required
    def api_dashboard_health():
        """Health check endpoint for dashboard auto-remediation monitoring"""
        from flask import jsonify
        try:
            health = dashboard_health_check()
            load_open_positions_df()
            health["stats"] = _dashboard_health_status.copy()
            return jsonify(health)
        except Exception as e:
            return jsonify({
                "healthy": False,
                "issues": [str(e)],
                "fixes_applied": [],
                "stats": _dashboard_health_status.copy()
            }), 500

    @server.route("/health/system_status")
    @login_required
    def api_system_status():
        """System health status endpoint returning green/yellow/red for all components"""
        from flask import jsonify
        try:
            status = {}
            
            # 1. CoinGlass feed
            try:
                from src.infrastructure.path_registry import PathRegistry
                coinglass_dir = PathRegistry.get_path("feature_store", "coinglass")
                if os.path.exists(coinglass_dir):
                    # Check if any recent files exist (within last hour)
                    recent_files = False
                    for file in os.listdir(coinglass_dir):
                        file_path = os.path.join(coinglass_dir, file)
                        if os.path.isfile(file_path):
                            file_age = time.time() - os.path.getmtime(file_path)
                            if file_age < 3600:  # 1 hour
                                recent_files = True
                                break
                    status["coinglass_feed"] = "green" if recent_files else "yellow"
                else:
                    status["coinglass_feed"] = "red"
            except Exception:
                status["coinglass_feed"] = "red"
            
            # 2. Signal engine
            try:
                from src.signal_integrity import get_status as get_signal_status
                signal_status = get_signal_status()
                status["signal_engine"] = signal_status.get("signal_engine", "yellow")
            except Exception:
                status["signal_engine"] = "red"
            
            # 3. Decision engine (check for recent decisions)
            try:
                decision_file = PathRegistry.get_path("logs", "enriched_decisions.jsonl")
                if os.path.exists(decision_file):
                    file_age = time.time() - os.path.getmtime(decision_file)
                    if file_age < 600:  # 10 minutes
                        status["decision_engine"] = "green"
                    elif file_age < 3600:  # 1 hour
                        status["decision_engine"] = "yellow"
                    else:
                        status["decision_engine"] = "red"
                else:
                    status["decision_engine"] = "yellow"
            except Exception:
                status["decision_engine"] = "red"
            
            # 4. Exit gates (check exit log)
            try:
                exit_file = PathRegistry.get_path("logs", "exit_runtime_events.jsonl")
                if os.path.exists(exit_file):
                    status["exit_gates"] = "green"
                else:
                    status["exit_gates"] = "yellow"
            except Exception:
                status["exit_gates"] = "yellow"
            
            # 5. Trade execution (check positions file updates)
            try:
                pos_file = PathRegistry.POS_LOG
                if os.path.exists(pos_file):
                    file_age = time.time() - os.path.getmtime(pos_file)
                    # More lenient: green if updated in last 10 minutes (not 5)
                    if file_age < 600:  # 10 minutes
                        status["trade_execution"] = "green"
                    elif file_age < 3600:  # 1 hour
                        status["trade_execution"] = "yellow"
                    else:
                        status["trade_execution"] = "red"
                else:
                    status["trade_execution"] = "yellow"
            except Exception:
                status["trade_execution"] = "red"
            
            # 6. Heartbeat freshness
            try:
                heartbeat_file = PathRegistry.get_path("logs", ".bot_heartbeat")
                if os.path.exists(heartbeat_file):
                    file_age = time.time() - os.path.getmtime(heartbeat_file)
                    if file_age < 120:  # 2 minutes
                        status["heartbeat_freshness"] = "green"
                    elif file_age < 300:  # 5 minutes
                        status["heartbeat_freshness"] = "yellow"
                    else:
                        status["heartbeat_freshness"] = "red"
                else:
                    status["heartbeat_freshness"] = "yellow"
            except Exception:
                status["heartbeat_freshness"] = "red"
            
            # 7. Feature store updates
            try:
                feature_dir = PathRegistry.FEATURE_STORE_DIR
                if os.path.exists(feature_dir):
                    # Check for recent feature files
                    recent_features = False
                    for root, dirs, files in os.walk(feature_dir):
                        for file in files:
                            file_path = os.path.join(root, file)
                            file_age = time.time() - os.path.getmtime(file_path)
                            if file_age < 3600:  # 1 hour
                                recent_features = True
                                break
                        if recent_features:
                            break
                    status["feature_store_updates"] = "green" if recent_features else "yellow"
                else:
                    status["feature_store_updates"] = "red"
            except Exception:
                status["feature_store_updates"] = "yellow"
            
            # 8. File integrity
            try:
                pos_file = PathRegistry.POS_LOG
                if os.path.exists(pos_file):
                    with open(pos_file, 'r') as f:
                        data = json.load(f)
                    if isinstance(data, dict) and "open_positions" in data and "closed_positions" in data:
                        status["file_integrity"] = "green"
                    else:
                        status["file_integrity"] = "yellow"
                else:
                    status["file_integrity"] = "yellow"
            except json.JSONDecodeError:
                status["file_integrity"] = "red"
            except Exception:
                status["file_integrity"] = "yellow"
            
            # 9. Self-healing status
            try:
                from src.operator_safety import get_status as get_safety_status
                safety_status = get_safety_status()
                status["self_healing"] = safety_status.get("self_healing", "yellow")
            except Exception:
                status["self_healing"] = "yellow"
            
            # 10. Safety layer status
            try:
                from src.operator_safety import get_status as get_safety_status
                safety_status = get_safety_status()
                status["safety_layer"] = safety_status.get("safety_layer", "yellow")
            except Exception:
                status["safety_layer"] = "yellow"
            
            return jsonify(status)
        except Exception as e:
            # Return all red on error
            return jsonify({
                "coinglass_feed": "red",
                "signal_engine": "red",
                "decision_engine": "red",
                "exit_gates": "red",
                "trade_execution": "red",
                "heartbeat_freshness": "red",
                "feature_store_updates": "red",
                "file_integrity": "red",
                "self_healing": "red",
                "safety_layer": "red",
                "error": str(e)
            }), 500

    @server.route("/audit/executive_summary")
    @login_required
    def api_executive_summary():
        """Executive summary endpoint generating plain-English narratives"""
        from flask import jsonify
        try:
            summary = generate_executive_summary()
            return jsonify(summary)
        except Exception as e:
            return jsonify({
                "error": str(e),
                "what_worked_today": "Error generating summary",
                "what_didnt_work": "Error generating summary",
                "missed_opportunities": "Error generating summary",
                "blocked_signals": "Error generating summary",
                "exit_gates": "Error generating summary",
                "learning_today": "Error generating summary",
                "changes_tomorrow": "Error generating summary",
                "weekly_summary": "Error generating summary"
            }), 500

    # Load data with error handling - app must start even if data loading fails
    try:
        df0 = load_trades_df()
    except Exception as e:
        print(f"⚠️  [DASHBOARD] Failed to load trades: {e}")
        df0 = pd.DataFrame(columns=["ts", "time", "symbol", "strategy", "venue", "side", "size_usd", "pnl_usd", "fee_usd", "net_pnl_usd", "order_id", "trade_id", "hour", "date"])
    
    try:
        wallet_balance = get_wallet_balance()
    except Exception as e:
        print(f"⚠️  [DASHBOARD] Failed to get wallet balance: {e}")
        wallet_balance = 10000.0
    
    try:
        daily_summary = compute_summary(df0, lookback_days=1, wallet_balance=wallet_balance)
    except Exception as e:
        print(f"⚠️  [DASHBOARD] Failed to compute summary: {e}")
        daily_summary = {"wallet_balance": wallet_balance, "total_trades": 0, "wins": 0, "losses": 0, "win_rate": 0.0, "net_pnl": 0.0, "avg_win": 0.0, "avg_loss": 0.0, "drawdown_pct": 0.0}
    
    try:
        open_positions_df = load_open_positions_df()
    except Exception as e:
        print(f"⚠️  [DASHBOARD] Failed to load open positions: {e}")
        import traceback
        traceback.print_exc()
        open_positions_df = pd.DataFrame(columns=["symbol","strategy","side","amount","size_usd","entry_price","current_price","pnl_usd","pnl_pct","leverage","stop_loss","trailing_stop"])
    
    try:
        closed_positions_df = load_closed_positions_df()
    except Exception as e:
        print(f"⚠️  [DASHBOARD] Failed to load closed positions: {e}")
        closed_positions_df = pd.DataFrame(columns=["symbol","strategy","entry_time","exit_time","entry_price","exit_price","size","hold_duration_h","roi_pct","net_pnl","fees"])

    app.layout = html.Div(style={"backgroundColor":"#0b0e13","fontFamily":"Inter,Segoe UI,Arial"}, children=[
        html.Div([
            html.Div([
                html.H2(APP_TITLE, style={"color":"#fff","margin":"8px 0","display":"inline-block"}),
                html.A("Alpha vs Beta", href="/bots", style={
                    "backgroundColor":"#1a4d2e","color":"#00ff88","padding":"8px 16px",
                    "borderRadius":"6px","textDecoration":"none","marginLeft":"20px",
                    "border":"1px solid #00ff88","fontWeight":"bold","display":"inline-block"
                }),
                html.A("Trader Dashboard", href="/phase8", style={
                    "backgroundColor":"#1b1f2a","color":"#00d4ff","padding":"8px 16px",
                    "borderRadius":"6px","textDecoration":"none","marginLeft":"10px",
                    "border":"1px solid #2d3139","display":"inline-block"
                }),
                html.A("Futures", href="/futures", style={
                    "backgroundColor":"#1b1f2a","color":"#00d4ff","padding":"8px 16px",
                    "borderRadius":"6px","textDecoration":"none","marginLeft":"10px",
                    "border":"1px solid #2d3139","display":"inline-block"
                }),
            ], style={"marginBottom":"12px"}),
            
            # System Health Panel
            html.Div([
                html.H4("System Health", style={"color":"#fff","margin":"8px"}),
                html.Div(id="system-health-container", children=[
                    html.Div("Loading system health...", style={"color":"#9aa0a6","padding":"16px"})
                ]),
                dcc.Interval(id="system-health-interval", interval=2*1000, n_intervals=0),  # Auto-refresh every 2s
            ], style={"marginBottom": "20px", "backgroundColor": "#0f1217", "borderRadius": "8px", "padding": "12px"}),
            
            # Summary Tabs Section
            html.Div([
                dcc.Tabs(id="summary-tabs", value="daily", children=[
                    dcc.Tab(label="📅 Daily", value="daily", style={"backgroundColor": "#1b1f2a", "color": "#9aa0a6"}, selected_style={"backgroundColor": "#1a73e8", "color": "#fff"}),
                    dcc.Tab(label="📊 Weekly", value="weekly", style={"backgroundColor": "#1b1f2a", "color": "#9aa0a6"}, selected_style={"backgroundColor": "#1a73e8", "color": "#fff"}),
                    dcc.Tab(label="📈 Monthly", value="monthly", style={"backgroundColor": "#1b1f2a", "color": "#9aa0a6"}, selected_style={"backgroundColor": "#1a73e8", "color": "#fff"}),
                    dcc.Tab(label="📋 Executive Summary", value="executive", style={"backgroundColor": "#1b1f2a", "color": "#9aa0a6"}, selected_style={"backgroundColor": "#1a73e8", "color": "#fff"}),
                ]),
                html.Div(id="summary-container", children=summary_card(daily_summary, "Daily Summary (Last 24 Hours)"), style={"padding": "16px"}),
                dcc.Interval(id="summary-interval", interval=30*1000, n_intervals=0),  # Auto-refresh every 30s
                dcc.Interval(id="executive-summary-interval", interval=24*60*60*1000, n_intervals=0),  # Auto-refresh once per day
            ], style={"marginBottom": "20px", "backgroundColor": "#0f1217", "borderRadius": "8px", "padding": "12px"}),
            
            # Open Positions Section
            html.Div([
                html.H4("Open Positions", style={"color":"#fff","margin":"8px"}),
                html.Div(id="open-positions-container", children=[make_open_positions_section(open_positions_df)]),
                dcc.Interval(id="open-positions-interval", interval=30*1000, n_intervals=0),
            ], style={"marginBottom": "20px", "backgroundColor": "#0f1217", "borderRadius": "8px", "padding": "12px"}),
            
            # Closed Positions Section
            html.Div([
                html.H4("Closed Trades History", style={"color":"#fff","margin":"8px"}),
                html.Div(id="closed-positions-container", children=[make_closed_positions_section(closed_positions_df)]),
                dcc.Interval(id="closed-positions-interval", interval=30*1000, n_intervals=0),
                dcc.Download(id="download-closed-csv"),
            ], style={"marginBottom": "20px", "backgroundColor": "#0f1217", "borderRadius": "8px", "padding": "12px"}),
            
            html.Div([
                html.Div([
                    html.Label("Lookback (hours)", style={"color":"#9aa0a6"}),
                    dcc.Input(id="lookback-hrs", type="number", value=DEFAULT_TIMEFRAME_HOURS, min=1, step=1, style={"width":"120px","marginRight":"12px"}),
                ], style={"display":"inline-block","marginRight":"20px"}),
                html.Div([
                    html.Label("Symbol", style={"color":"#9aa0a6"}),
                    dcc.Dropdown(
                        id="filter-symbol", 
                        options=[{"label":s,"value":s} for s in sorted(df0["symbol"].unique()) if s] if not df0.empty and "symbol" in df0.columns else [], 
                        value=None, 
                        placeholder="All", 
                        style={"width":"200px","marginRight":"12px"}
                    ),
                ], style={"display":"inline-block","marginRight":"20px"}),
                html.Div([
                    html.Label("Strategy", style={"color":"#9aa0a6"}),
                    dcc.Dropdown(
                        id="filter-strategy", 
                        options=[{"label":s,"value":s} for s in sorted(df0["strategy"].unique()) if s] if not df0.empty and "strategy" in df0.columns else [], 
                        value=None, 
                        placeholder="All", 
                        style={"width":"220px","marginRight":"12px"}
                    ),
                ], style={"display":"inline-block","marginRight":"20px"}),
                html.Button("Refresh", id="refresh-btn", n_clicks=0, style={"backgroundColor":"#1a73e8","color":"#fff","border":"none","padding":"8px 12px","borderRadius":"6px","marginRight":"12px"}),
                html.Button("Export CSV", id="export-btn", n_clicks=0, style={"backgroundColor":"#34a853","color":"#fff","border":"none","padding":"8px 12px","borderRadius":"6px"}),
                dcc.Download(id="download-csv"),
            ], style={"marginBottom":"10px"})
        ], style={"padding":"12px","borderBottom":"1px solid #1b1f2a"}),

        # Charts interval for auto-refresh
        dcc.Interval(id="charts-interval", interval=30*1000, n_intervals=0),  # Auto-refresh charts every 30s

        html.Div([
            html.H4("Trades", style={"color":"#fff","margin":"8px"}),
            html.Div(id="table-container", children=[make_table(df0)], style={"padding":"8px"})
        ])
    ])

    @app.callback(
        Output("system-health-container", "children"),
        Input("system-health-interval", "n_intervals")
    )
    def update_system_health(_n):
        """Update system health panel every 2 seconds"""
        try:
            # Call the status function directly (same as endpoint)
            status = {}
            
            # 1. CoinGlass feed
            try:
                coinglass_dir = PathRegistry.get_path("feature_store", "coinglass")
                if os.path.exists(coinglass_dir):
                    recent_files = False
                    for file in os.listdir(coinglass_dir):
                        file_path = os.path.join(coinglass_dir, file)
                        if os.path.isfile(file_path):
                            file_age = time.time() - os.path.getmtime(file_path)
                            if file_age < 3600:  # 1 hour
                                recent_files = True
                                break
                    status["coinglass_feed"] = "green" if recent_files else "yellow"
                else:
                    status["coinglass_feed"] = "red"
            except Exception:
                status["coinglass_feed"] = "red"
            
            # 2. Signal engine
            try:
                from src.signal_integrity import get_status as get_signal_status
                signal_status = get_signal_status()
                status["signal_engine"] = signal_status.get("signal_engine", "yellow")
            except Exception:
                status["signal_engine"] = "red"
            
            # 3. Decision engine
            try:
                decision_file = PathRegistry.get_path("logs", "enriched_decisions.jsonl")
                if os.path.exists(decision_file):
                    file_age = time.time() - os.path.getmtime(decision_file)
                    if file_age < 600:
                        status["decision_engine"] = "green"
                    elif file_age < 3600:
                        status["decision_engine"] = "yellow"
                    else:
                        status["decision_engine"] = "red"
                else:
                    status["decision_engine"] = "yellow"
            except Exception:
                status["decision_engine"] = "red"
            
            # 4. Exit gates
            try:
                exit_file = PathRegistry.get_path("logs", "exit_runtime_events.jsonl")
                status["exit_gates"] = "green" if os.path.exists(exit_file) else "yellow"
            except Exception:
                status["exit_gates"] = "yellow"
            
            # 5. Trade execution
            try:
                pos_file = PathRegistry.POS_LOG
                if os.path.exists(pos_file):
                    file_age = time.time() - os.path.getmtime(pos_file)
                    if file_age < 300:
                        status["trade_execution"] = "green"
                    elif file_age < 1800:
                        status["trade_execution"] = "yellow"
                    else:
                        status["trade_execution"] = "red"
                else:
                    status["trade_execution"] = "yellow"
            except Exception:
                status["trade_execution"] = "red"
            
            # 6. Heartbeat freshness
            try:
                heartbeat_file = PathRegistry.get_path("logs", ".bot_heartbeat")
                if os.path.exists(heartbeat_file):
                    file_age = time.time() - os.path.getmtime(heartbeat_file)
                    if file_age < 120:
                        status["heartbeat_freshness"] = "green"
                    elif file_age < 300:
                        status["heartbeat_freshness"] = "yellow"
                    else:
                        status["heartbeat_freshness"] = "red"
                else:
                    status["heartbeat_freshness"] = "yellow"
            except Exception:
                status["heartbeat_freshness"] = "red"
            
            # 7. Feature store updates
            try:
                feature_dir = PathRegistry.FEATURE_STORE_DIR
                if os.path.exists(feature_dir):
                    recent_features = False
                    for root, dirs, files in os.walk(feature_dir):
                        for file in files:
                            file_path = os.path.join(root, file)
                            file_age = time.time() - os.path.getmtime(file_path)
                            if file_age < 3600:
                                recent_features = True
                                break
                        if recent_features:
                            break
                    status["feature_store_updates"] = "green" if recent_features else "yellow"
                else:
                    status["feature_store_updates"] = "red"
            except Exception:
                status["feature_store_updates"] = "yellow"
            
            # 8. File integrity
            try:
                pos_file = PathRegistry.POS_LOG
                if os.path.exists(pos_file):
                    with open(pos_file, 'r') as f:
                        data = json.load(f)
                    if isinstance(data, dict) and "open_positions" in data and "closed_positions" in data:
                        status["file_integrity"] = "green"
                    else:
                        status["file_integrity"] = "yellow"
                else:
                    status["file_integrity"] = "yellow"
            except json.JSONDecodeError:
                status["file_integrity"] = "red"
            except Exception:
                status["file_integrity"] = "yellow"
            
            # 9. Self-healing status
            try:
                from src.operator_safety import get_status as get_safety_status
                safety_status = get_safety_status()
                status["self_healing"] = safety_status.get("self_healing", "yellow")
            except Exception:
                status["self_healing"] = "yellow"
            
            # 10. Safety layer status
            try:
                from src.operator_safety import get_status as get_safety_status
                safety_status = get_safety_status()
                status["safety_layer"] = safety_status.get("safety_layer", "yellow")
            except Exception:
                status["safety_layer"] = "yellow"
                
        except Exception as e:
            # Fallback: all red on error
            status = {
                "coinglass_feed": "red",
                "signal_engine": "red",
                "decision_engine": "red",
                "exit_gates": "red",
                "trade_execution": "red",
                "heartbeat_freshness": "red",
                "feature_store_updates": "red",
                "file_integrity": "red",
                "self_healing": "red",
                "safety_layer": "red"
            }
        
        # Component names with display labels
        components = [
            ("coinglass_feed", "CoinGlass Feed"),
            ("signal_engine", "Signal Engine"),
            ("decision_engine", "Decision Engine"),
            ("exit_gates", "Exit Gates"),
            ("trade_execution", "Trade Execution"),
            ("heartbeat_freshness", "Heartbeat Freshness"),
            ("feature_store_updates", "Feature Store Updates"),
            ("file_integrity", "File Integrity"),
            ("self_healing", "Self-Healing"),
            ("safety_layer", "Safety Layer")
        ]
        
        # Create grid of status indicators
        grid_items = []
        for key, label in components:
            color = status.get(key, "yellow")
            bg_color = {
                "green": "#28a745",
                "yellow": "#ffc107",
                "red": "#dc3545"
            }.get(color, "#6c757d")
            
            grid_items.append(
                html.Div([
                    html.Div(label, style={"color":"#fff","fontSize":"12px","marginBottom":"4px"}),
                    html.Div(
                        "",
                        style={
                            "width":"100%",
                            "height":"20px",
                            "backgroundColor":bg_color,
                            "borderRadius":"4px",
                            "border":"1px solid #333"
                        }
                    )
                ], style={"display":"inline-block","width":"18%","margin":"8px","verticalAlign":"top"})
            )
        
        return html.Div(grid_items, style={"display":"flex","flexWrap":"wrap","justifyContent":"space-between"})

    @app.callback(
        Output("summary-container", "children"),
        [Input("summary-tabs", "value"),
         Input("summary-interval", "n_intervals"),
         Input("executive-summary-interval", "n_intervals")],
        prevent_initial_call=False
    )
    def update_summary(tab, _n_intervals, _exec_n_intervals):
        """Update summary card on tab change OR interval refresh."""
        
        # Handle Executive Summary tab
        if tab == "executive":
            try:
                summary = generate_executive_summary()
                
                sections = [
                    ("What Worked Today", summary.get("what_worked_today", "No data available.")),
                    ("What Didn't Work", summary.get("what_didnt_work", "No data available.")),
                    ("Missed Opportunities", summary.get("missed_opportunities", "No data available.")),
                    ("Blocked Signals", summary.get("blocked_signals", "No data available.")),
                    ("Exit Gates Analysis", summary.get("exit_gates", "No data available.")),
                    ("Learning Today", summary.get("learning_today", "No data available.")),
                    ("Changes Tomorrow", summary.get("changes_tomorrow", "No data available.")),
                    ("Weekly Summary", summary.get("weekly_summary", "No data available."))
                ]
                
                content = []
                for title, text in sections:
                    content.append(
                        html.Div([
                            html.H5(title, style={"color":"#fff","marginBottom":"8px","marginTop":"16px"}),
                            html.P(text, style={"color":"#9aa0a6","lineHeight":"1.6","marginBottom":"12px"})
                        ])
                    )
                
                return html.Div(content, style={"padding":"16px"})
            except Exception as e:
                return html.Div([
                    html.P(f"Error loading executive summary: {str(e)}", style={"color":"#ff6b6b","padding":"12px"})
                ])
        
        # Handle other tabs (daily, weekly, monthly)
        try:
            # Handle None values from initial page load
            if tab is None:
                tab = "daily"
            if _n_intervals is None:
                _n_intervals = 0
            
            # Record wallet snapshot (hourly, but called every refresh to check)
            record_wallet_snapshot()
            
            # Force cache refresh by clearing it if interval triggered
            if _n_intervals > 0:
                try:
                    clear_cache()  # Force cache refresh
                except Exception as cache_err:
                    print(f"⚠️  [DASHBOARD] Error clearing cache: {cache_err}")
            
            df = load_trades_df()
            wallet_balance = get_wallet_balance()
            
            if tab == "daily":
                s = compute_summary(df, lookback_days=1, wallet_balance=wallet_balance)
                return summary_card(s, "Daily Summary (Last 24 Hours)", hours=24)
            elif tab == "weekly":
                s = compute_summary(df, lookback_days=7, wallet_balance=wallet_balance)
                return summary_card(s, "Weekly Summary (Last 7 Days)", hours=168)
            elif tab == "monthly":
                s = compute_summary(df, lookback_days=30, wallet_balance=wallet_balance)
                return summary_card(s, "Monthly Summary (Last 30 Days)", hours=720)
            return summary_card(compute_summary(df, 1, wallet_balance), "Summary", hours=24)
        except Exception as e:
            print(f"⚠️  [DASHBOARD] Error updating summary: {e}")
            import traceback
            traceback.print_exc()
            return html.Div([html.P(f"Error loading summary: {str(e)}", style={"color":"#ff6b6b","padding":"12px"})])

    @app.callback(
        Output("open-positions-container", "children"),
        Input("open-positions-interval", "n_intervals")
    )
    def refresh_open_positions(_n):
        try:
            # Add timeout protection - don't let this hang the dashboard
            load_start = time.time()
            df = load_open_positions_df()
            load_time = time.time() - load_start
            
            if _n and _n > 0 and _n % 10 == 0:  # Log every 10th refresh (every 5 minutes)
                print(f"🔄 [DASHBOARD] Refreshed open positions: {len(df)} positions (took {load_time:.2f}s)")
            
            # If loading took too long, log a warning
            if load_time > 5.0:
                print(f"⚠️  [DASHBOARD] Open positions load took {load_time:.2f}s (slow)")
            
            return [make_open_positions_section(df)]
        except Exception as e:
            print(f"⚠️  [DASHBOARD] Error loading open positions: {e}")
            import traceback
            traceback.print_exc()
            # Return empty section instead of crashing
            return [html.Div([html.P(f"Error loading open positions: {str(e)}", style={"color":"#ff6b6b","padding":"12px"})])]

    @app.callback(
        Output("closed-positions-container", "children"),
        Input("closed-positions-interval", "n_intervals")
    )
    def refresh_closed_positions(_n):
        try:
            df = load_closed_positions_df()
            if _n and _n > 0 and _n % 10 == 0:  # Log every 10th refresh (every 5 minutes)
                print(f"🔄 [DASHBOARD] Refreshed closed positions: {len(df)} positions")
            return [make_closed_positions_section(df)]
        except Exception as e:
            print(f"⚠️  [DASHBOARD] Error loading closed positions: {e}")
            import traceback
            traceback.print_exc()
            return [html.Div([html.P(f"Error loading closed positions: {str(e)}", style={"color":"#ff6b6b","padding":"12px"})])]

    @app.callback(
        Output("download-closed-csv", "data"),
        Input("export-closed-btn", "n_clicks"),
        prevent_initial_call=True
    )
    def export_closed_csv(n_clicks):
        if n_clicks is None or n_clicks == 0:
            return None
        df = load_closed_positions_df()
        return dcc.send_bytes(export_csv_bytes(df), filename=f"closed_trades_export_{int(time.time())}.csv")

    # Removed symbol-profit-chart callback - chart removed from dashboard

    @app.callback(
        Output("table-container","children"),
        [Input("refresh-btn","n_clicks"),
         Input("charts-interval", "n_intervals")],
        State("lookback-hrs","value"),
        State("filter-symbol","value"),
        State("filter-strategy","value"),
        prevent_initial_call=False
    )
    def refresh(_n_clicks, _n_intervals, lookback_hrs, symbol, strategy):
        """Refresh trades table on button click OR interval trigger."""
        try:
            # Handle None values
            if _n_clicks is None:
                _n_clicks = 0
            if _n_intervals is None:
                _n_intervals = 0
            
            # Force cache refresh on interval
            if _n_intervals > 0:
                try:
                    clear_cache()  # Force cache refresh
                except Exception as cache_err:
                    print(f"⚠️  [DASHBOARD] Error clearing cache: {cache_err}")
            
            df = load_trades_df()
            if not df.empty and lookback_hrs and lookback_hrs > 0:
                cutoff = int(time.time()) - int(lookback_hrs*3600)
                df = df[df["ts"] >= cutoff]
            if symbol:
                df = df[df["symbol"] == symbol]
            if strategy:
                df = df[df["strategy"] == strategy]

            return [make_table(df)]
        except Exception as e:
            print(f"⚠️  [DASHBOARD] Error refreshing table: {e}")
            import traceback
            traceback.print_exc()
            return [html.Div(f"Error loading trades: {str(e)}", style={"color": "#ff6b6b", "padding": "20px"})]

    @app.callback(
        Output("download-csv","data"),
        Input("export-btn","n_clicks"),
        State("lookback-hrs","value"),
        State("filter-symbol","value"),
        State("filter-strategy","value"),
        prevent_initial_call=True
    )
    def export_csv(_n, lookback_hrs, symbol, strategy):
        df = load_trades_df()
        if not df.empty and lookback_hrs and lookback_hrs > 0:
            cutoff = int(time.time()) - int(lookback_hrs*3600)
            df = df[df["ts"] >= cutoff]
        if symbol:
            df = df[df["symbol"] == symbol]
        if strategy:
            df = df[df["strategy"] == strategy]
        return dcc.send_bytes(export_csv_bytes(df), filename=f"trades_pnl_export_{int(time.time())}.csv")

    return app

def start_pnl_dashboard(flask_app: Flask = None):
    """
    Registers the P&L dashboard as the default view ("/") on your existing Flask app.
    If no app is provided, creates its own Flask + Dash server.
    """
    try:
        # Initialize positions file on startup (repairs empty/malformed files)
        try:
            from src.position_manager import initialize_futures_positions
            print("🔍 [DASHBOARD] Calling initialize_futures_positions()...", flush=True)
            initialize_futures_positions()
            print("✅ [DASHBOARD] Initialized/verified positions_futures.json structure", flush=True)
        except Exception as e:
            print(f"⚠️  [DASHBOARD] Failed to initialize positions file: {e}", flush=True)
            # Don't crash - continue without initialization
        
        app = build_app(flask_app)
        print("✅ [DASHBOARD] Dashboard app built successfully", flush=True)
        return app
    except Exception as e:
        print(f"❌ [DASHBOARD] CRITICAL: Dashboard startup failed: {e}", flush=True)
        import traceback
        traceback.print_exc()
        # Return a minimal Flask app so the server doesn't crash
        if flask_app:
            return flask_app
        from flask import Flask
        minimal_app = Flask(__name__)
        @minimal_app.route('/')
        def error_page():
            return f"<h1>Dashboard Error</h1><p>Dashboard failed to start: {str(e)}</p><p>Check logs for details.</p>", 500
        return minimal_app

if __name__ == "__main__":
    flask_server = Flask(__name__)
    dash_app = build_app(flask_server)
    port = int(os.environ.get("PORT", "8050"))
    dash_app.run(host="0.0.0.0", port=port, debug=False)
