#!/usr/bin/env python3
"""
CLEAN P&L DASHBOARD V2 - Rebuilt from Scratch
==============================================
Modern, clean dashboard with 2 tabs:
1. Daily Summary - Real-time trading data, positions, charts
2. Executive Summary - Comprehensive analysis, weekly/monthly summaries

Uses standardized data sources:
- positions_futures.json (via DataRegistry) - canonical trade data
- Standardized field names throughout

Port: 8050 (must match existing)
"""

import io
import base64
import time
import os
import json
import math
import threading
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional
from pathlib import Path

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from flask import Flask
from dash import Dash, html, dcc, Input, Output, State, dash_table, callback_context
import dash_bootstrap_components as dbc
import hashlib

# Standardized imports
from src.data_registry import DataRegistry as DR
from src.position_manager import load_futures_positions
from src.infrastructure.path_registry import PathRegistry
from src.pnl_dashboard_loader import load_trades_df, clear_cache

# Configuration
DEFAULT_TIMEFRAME_HOURS = 72
APP_TITLE = "P&L Dashboard"
PORT = 8050

# Dashboard password (hashed for security)
DASHBOARD_PASSWORD = "Echelonlev2007!"
DASHBOARD_PASSWORD_HASH = hashlib.sha256(DASHBOARD_PASSWORD.encode()).hexdigest()

# Price cache for dashboard (prevents rate limiting)
_price_cache: Dict[str, Dict[str, Any]] = {}
_price_cache_lock = threading.Lock()
PRICE_CACHE_TTL = 60  # Cache prices for 60 seconds

# Request cache
_request_cache: Dict[str, Any] = {}
_request_cache_lock = threading.Lock()
_REQUEST_CACHE_MAX_AGE = 5  # 5 seconds


def safe_load_json(filepath: str, default=None) -> dict:
    """Safely load JSON file."""
    if default is None:
        default = {}
    if not os.path.exists(filepath):
        return default
    try:
        with open(filepath, 'r') as f:
            return json.load(f)
    except Exception as e:
        print(f"⚠️  Error loading {filepath}: {e}")
        return default


def get_wallet_balance() -> float:
    """Get current wallet balance from positions_futures.json."""
    try:
        starting_capital = 10000.0
        positions_data = DR.read_json(DR.POSITIONS_FUTURES)
        if not positions_data:
            return starting_capital
        closed_positions = positions_data.get("closed_positions", [])
        
        total_pnl = 0.0
        for pos in closed_positions:
            val = pos.get("pnl", pos.get("net_pnl", pos.get("realized_pnl", 0)))
            if val is None:
                continue
            try:
                val = float(val)
                if not math.isnan(val):
                    total_pnl += val
            except (TypeError, ValueError):
                continue
        
        return starting_capital + total_pnl
    except Exception as e:
        print(f"⚠️  Failed to calculate wallet balance: {e}")
        return 10000.0


def load_open_positions_df() -> pd.DataFrame:
    """Load open positions with real-time pricing."""
    try:
        from src.exchange_gateway import ExchangeGateway
        
        positions_data = load_futures_positions()
        if not positions_data:
            return pd.DataFrame(columns=["symbol", "strategy", "side", "entry_price", "current_price", "size", "margin_collateral", "leverage", "pnl_usd", "pnl_pct", "entry_time"])
        open_positions = positions_data.get("open_positions", [])
        
        rows = []
        gateway = None
        
        try:
            gateway = ExchangeGateway()
        except Exception as e:
            print(f"⚠️  ExchangeGateway init failed: {e}")
        
        for pos in open_positions:
            symbol = pos.get("symbol", "")
            entry_price = pos.get("entry_price", 0.0)
            size = pos.get("size", 0.0)  # Contract size
            leverage = pos.get("leverage", 1)
            direction = pos.get("direction", "LONG")
            margin = pos.get("margin_collateral", 0.0) or (size / leverage if leverage > 0 else size)
            strategy = pos.get("strategy", "Unknown")
            entry_time = pos.get("opened_at", "")
            
            # Get current price
            current_price = entry_price
            try:
                if gateway:
                    current_price = gateway.get_price(symbol, venue="futures")
            except:
                pass
            
            # Calculate P&L
            if direction == "LONG":
                price_roi = ((current_price - entry_price) / entry_price) if entry_price > 0 else 0.0
            else:
                price_roi = ((entry_price - current_price) / entry_price) if entry_price > 0 else 0.0
            
            leveraged_roi = price_roi * leverage
            pnl_usd = margin * leveraged_roi
            pnl_pct = leveraged_roi * 100
            
            rows.append({
                "symbol": symbol,
                "strategy": strategy,
                "side": direction,
                "entry_price": entry_price,
                "current_price": current_price,
                "size": size,
                "margin_collateral": margin,
                "leverage": leverage,
                "pnl_usd": pnl_usd,
                "pnl_pct": pnl_pct,
                "entry_time": entry_time,
            })
        
        df = pd.DataFrame(rows)
        if not df.empty:
            df = df.sort_values("pnl_usd", ascending=False)
        return df
    except Exception as e:
        print(f"⚠️  Failed to load open positions: {e}")
        import traceback
        traceback.print_exc()
        return pd.DataFrame(columns=["symbol", "strategy", "side", "entry_price", "current_price", "size", "margin_collateral", "leverage", "pnl_usd", "pnl_pct", "entry_time"])


def load_closed_positions_df() -> pd.DataFrame:
    """Load closed positions from positions_futures.json."""
    try:
        positions_data = DR.read_json(DR.POSITIONS_FUTURES)
        if not positions_data:
            return pd.DataFrame(columns=["symbol", "strategy", "entry_time", "exit_time", "entry_price", "exit_price", "size", "hold_duration_h", "roi_pct", "net_pnl", "fees"])
        closed_positions = positions_data.get("closed_positions", [])
        
        rows = []
        for pos in closed_positions:
            symbol = pos.get("symbol", "")
            strategy = pos.get("strategy", "Unknown")
            entry_price = pos.get("entry_price", 0.0)
            exit_price = pos.get("exit_price", 0.0)
            direction = pos.get("direction", "LONG")
            size = pos.get("size", 0.0)
            leverage = pos.get("leverage", 1)
            margin = pos.get("margin_collateral", 0.0) or (size / leverage if leverage > 0 else size)
            
            # Calculate P&L
            if direction == "LONG":
                price_roi = ((exit_price - entry_price) / entry_price) if entry_price > 0 else 0.0
            else:
                price_roi = ((entry_price - exit_price) / entry_price) if entry_price > 0 else 0.0
            
            leveraged_roi = price_roi * leverage
            net_pnl = pos.get("pnl", pos.get("net_pnl", margin * leveraged_roi))
            
            entry_time = pos.get("opened_at", "")
            exit_time = pos.get("closed_at", "")
            
            # Calculate hold duration
            hold_duration_h = 0.0
            try:
                if entry_time and exit_time:
                    entry_dt = datetime.fromisoformat(entry_time.replace("Z", "+00:00"))
                    exit_dt = datetime.fromisoformat(exit_time.replace("Z", "+00:00"))
                    hold_duration_h = (exit_dt - entry_dt).total_seconds() / 3600.0
            except:
                pass
            
            rows.append({
                "symbol": symbol,
                "strategy": strategy,
                "entry_time": entry_time,
                "exit_time": exit_time,
                "entry_price": entry_price,
                "exit_price": exit_price,
                "size": size,
                "margin_collateral": margin,
                "leverage": leverage,
                "hold_duration_h": hold_duration_h,
                "roi_pct": leveraged_roi * 100,
                "net_pnl": net_pnl,
                "fees": pos.get("funding_fees", 0.0),
            })
        
        df = pd.DataFrame(rows)
        if not df.empty:
            df = df.sort_values("exit_time", ascending=False)
        return df
    except Exception as e:
        print(f"⚠️  Failed to load closed positions: {e}")
        return pd.DataFrame(columns=["symbol", "strategy", "entry_time", "exit_time", "entry_price", "exit_price", "size", "hold_duration_h", "roi_pct", "net_pnl", "fees"])


def compute_summary(wallet_balance: float, lookback_days: int = 1) -> dict:
    """Compute summary statistics for a given lookback period."""
    try:
        positions_data = DR.read_json(DR.POSITIONS_FUTURES)
        if not positions_data:
            # Return empty summary if no data
            return {
                "wallet_balance": wallet_balance,
                "total_trades": 0,
                "wins": 0,
                "losses": 0,
                "win_rate": 0.0,
                "net_pnl": 0.0,
                "avg_win": 0.0,
                "avg_loss": 0.0,
                "drawdown_pct": 0.0,
            }
        closed_positions = positions_data.get("closed_positions", [])
        open_positions = positions_data.get("open_positions", [])
        
        # Filter to lookback period
        cutoff = datetime.utcnow() - timedelta(days=lookback_days)
        recent_closed = []
        
        for pos in closed_positions:
            closed_at = pos.get("closed_at", "")
            if closed_at:
                try:
                    if isinstance(closed_at, str):
                        closed_dt = datetime.fromisoformat(closed_at.replace("Z", "+00:00"))
                    else:
                        closed_dt = datetime.fromtimestamp(closed_at)
                    if closed_dt >= cutoff:
                        recent_closed.append(pos)
                except:
                    pass
        
        # Calculate stats
        wins = []
        losses = []
        total_pnl = 0.0
        
        for pos in recent_closed:
            net_pnl = pos.get("pnl", pos.get("net_pnl", 0.0))
            if net_pnl is None:
                continue
            try:
                net_pnl = float(net_pnl)
                if not math.isnan(net_pnl):
                    total_pnl += net_pnl
                    if net_pnl > 0:
                        wins.append(net_pnl)
                    else:
                        losses.append(net_pnl)
            except:
                pass
        
        # Calculate unrealized P&L from open positions
        unrealized_pnl = 0.0
        try:
            from src.exchange_gateway import ExchangeGateway
            gateway = ExchangeGateway()
            
            for pos in open_positions:
                symbol = pos.get("symbol", "")
                entry_price = pos.get("entry_price", 0.0)
                direction = pos.get("direction", "LONG")
                margin = pos.get("margin_collateral", 0.0)
                leverage = pos.get("leverage", 1)
                
                try:
                    current_price = gateway.get_price(symbol, venue="futures")
                    if direction == "LONG":
                        price_roi = ((current_price - entry_price) / entry_price) if entry_price > 0 else 0.0
                    else:
                        price_roi = ((entry_price - current_price) / entry_price) if entry_price > 0 else 0.0
                    unrealized_pnl += margin * price_roi * leverage
                except:
                    pass
        except:
            pass
        
        total_trades = len(recent_closed)
        wins_count = len(wins)
        losses_count = len(losses)
        win_rate = (wins_count / total_trades * 100.0) if total_trades > 0 else 0.0
        avg_win = sum(wins) / len(wins) if wins else 0.0
        avg_loss = sum(losses) / len(losses) if losses else 0.0
        
        # Calculate drawdown
        starting_capital = 10000.0
        total_value = wallet_balance + unrealized_pnl
        drawdown_pct = ((total_value - starting_capital) / starting_capital) * 100.0
        
        return {
            "wallet_balance": wallet_balance,
            "total_trades": total_trades,
            "wins": wins_count,
            "losses": losses_count,
            "win_rate": win_rate,
            "net_pnl": total_pnl + unrealized_pnl,
            "avg_win": avg_win,
            "avg_loss": avg_loss,
            "drawdown_pct": drawdown_pct,
        }
    except Exception as e:
        print(f"⚠️  Failed to compute summary: {e}")
        return {
            "wallet_balance": wallet_balance,
            "total_trades": 0,
            "wins": 0,
            "losses": 0,
            "win_rate": 0.0,
            "net_pnl": 0.0,
            "avg_win": 0.0,
            "avg_loss": 0.0,
            "drawdown_pct": 0.0,
        }


# Chart Functions (Clean, Modern)
def create_equity_curve_chart(df: pd.DataFrame) -> go.Figure:
    """Create equity curve chart."""
    if df.empty:
        fig = go.Figure()
        fig.update_layout(title="Equity Curve", plot_bgcolor="#0f1217", paper_bgcolor="#0f1217", font={"color": "#e8eaed"})
        return fig
    
    df_sorted = df.sort_values("exit_time")
    df_sorted = df_sorted.copy()
    df_sorted["cum_pnl"] = df_sorted["net_pnl"].cumsum()
    starting_capital = 10000.0
    df_sorted["equity"] = starting_capital + df_sorted["cum_pnl"]
    
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=df_sorted["exit_time"],
        y=df_sorted["equity"],
        mode="lines+markers",
        name="Equity",
        line=dict(color="#34a853", width=2),
    ))
    fig.update_layout(
        title="Equity Curve",
        xaxis_title="Time",
        yaxis_title="Portfolio Value ($)",
        plot_bgcolor="#0f1217",
        paper_bgcolor="#0f1217",
        font={"color": "#e8eaed"},
        hovermode="x unified",
    )
    return fig


def create_pnl_by_symbol_chart(df: pd.DataFrame) -> go.Figure:
    """Create P&L by symbol bar chart."""
    if df.empty:
        fig = go.Figure()
        fig.update_layout(title="P&L by Symbol", plot_bgcolor="#0f1217", paper_bgcolor="#0f1217", font={"color": "#e8eaed"})
        return fig
    
    agg = df.groupby("symbol", as_index=False)["net_pnl"].sum().sort_values("net_pnl", ascending=False)
    
    colors = ["#34a853" if x >= 0 else "#ea4335" for x in agg["net_pnl"]]
    
    fig = go.Figure()
    fig.add_trace(go.Bar(
        x=agg["symbol"],
        y=agg["net_pnl"],
        marker_color=colors,
        text=[f"${x:.2f}" for x in agg["net_pnl"]],
        textposition="outside",
    ))
    fig.update_layout(
        title="Net P&L by Symbol",
        xaxis_title="Symbol",
        yaxis_title="Net P&L ($)",
        plot_bgcolor="#0f1217",
        paper_bgcolor="#0f1217",
        font={"color": "#e8eaed"},
        showlegend=False,
    )
    return fig


def create_pnl_by_strategy_chart(df: pd.DataFrame) -> go.Figure:
    """Create P&L by strategy bar chart."""
    if df.empty:
        fig = go.Figure()
        fig.update_layout(title="P&L by Strategy", plot_bgcolor="#0f1217", paper_bgcolor="#0f1217", font={"color": "#e8eaed"})
        return fig
    
    agg = df.groupby("strategy", as_index=False)["net_pnl"].sum().sort_values("net_pnl", ascending=False)
    
    colors = ["#34a853" if x >= 0 else "#ea4335" for x in agg["net_pnl"]]
    
    fig = go.Figure()
    fig.add_trace(go.Bar(
        x=agg["strategy"],
        y=agg["net_pnl"],
        marker_color=colors,
        text=[f"${x:.2f}" for x in agg["net_pnl"]],
        textposition="outside",
    ))
    fig.update_layout(
        title="Net P&L by Strategy",
        xaxis_title="Strategy",
        yaxis_title="Net P&L ($)",
        plot_bgcolor="#0f1217",
        paper_bgcolor="#0f1217",
        font={"color": "#e8eaed"},
        showlegend=False,
    )
    return fig


def create_win_rate_heatmap(df: pd.DataFrame) -> go.Figure:
    """Create win rate heatmap by symbol and date."""
    if df.empty:
        fig = go.Figure()
        fig.update_layout(title="Win Rate Heatmap", plot_bgcolor="#0f1217", paper_bgcolor="#0f1217", font={"color": "#e8eaed"})
        return fig
    
    df_copy = df.copy()
    df_copy["win"] = (df_copy["net_pnl"] > 0).astype(int)
    
    # Extract date from exit_time
    try:
        df_copy["date"] = pd.to_datetime(df_copy["exit_time"]).dt.date
    except:
        return go.Figure()
    
    pivot = df_copy.groupby(["symbol", "date"])["win"].mean().unstack(fill_value=0.0)
    
    fig = go.Figure(data=go.Heatmap(
        z=pivot.values,
        x=pivot.columns.astype(str),
        y=pivot.index,
        colorscale="RdYlGn",
        zmid=0.5,
        text=[[f"{val*100:.1f}%" for val in row] for row in pivot.values],
        texttemplate="%{text}",
        textfont={"size": 10},
    ))
    fig.update_layout(
        title="Win Rate Heatmap (Symbol × Date)",
        xaxis_title="Date",
        yaxis_title="Symbol",
        plot_bgcolor="#0f1217",
        paper_bgcolor="#0f1217",
        font={"color": "#e8eaed"},
    )
    return fig


def create_wallet_balance_trend() -> go.Figure:
    """Create wallet balance trend chart from snapshots."""
    try:
        wallet_snapshots_file = PathRegistry.get_path("logs", "wallet_snapshots.jsonl")
        if not os.path.exists(wallet_snapshots_file):
            fig = go.Figure()
            fig.update_layout(title="Wallet Balance Trend", plot_bgcolor="#0f1217", paper_bgcolor="#0f1217", font={"color": "#e8eaed"})
            return fig
        
        snapshots = []
        with open(wallet_snapshots_file, 'r') as f:
            for line in f:
                try:
                    snapshots.append(json.loads(line))
                except:
                    pass
        
        if not snapshots:
            fig = go.Figure()
            fig.update_layout(title="Wallet Balance Trend", plot_bgcolor="#0f1217", paper_bgcolor="#0f1217", font={"color": "#e8eaed"})
            return fig
        
        df = pd.DataFrame(snapshots)
        df = df.sort_values("timestamp")
        
        fig = go.Figure()
        fig.add_trace(go.Scatter(
            x=df["timestamp"],
            y=df["balance"],
            mode="lines+markers",
            name="Wallet Balance",
            line=dict(color="#1a73e8", width=2),
        ))
        fig.update_layout(
            title="Wallet Balance Trend",
            xaxis_title="Time",
            yaxis_title="Balance ($)",
            plot_bgcolor="#0f1217",
            paper_bgcolor="#0f1217",
            font={"color": "#e8eaed"},
            hovermode="x unified",
        )
        return fig
    except Exception as e:
        print(f"⚠️  Failed to create wallet balance trend: {e}")
        fig = go.Figure()
        fig.update_layout(title="Wallet Balance Trend", plot_bgcolor="#0f1217", paper_bgcolor="#0f1217", font={"color": "#e8eaed"})
        return fig


# Executive Summary Generator
def generate_executive_summary() -> Dict[str, str]:
    """
    Generate executive summary narratives.
    This is a simplified version - full implementation follows the pattern from old dashboard.
    """
    try:
        # Import the existing executive summary generator
        from src.pnl_dashboard import generate_executive_summary as _old_generate
        return _old_generate()
    except Exception as e:
        print(f"⚠️  Failed to generate executive summary: {e}")
        return {
            "what_worked_today": "Executive summary generation in progress...",
            "what_didnt_work": "",
            "missed_opportunities": "",
            "blocked_signals": "",
            "exit_gates": "",
            "learning_today": "",
            "changes_tomorrow": "",
            "weekly_summary": "",
        }


# System Health Check
def get_system_health() -> dict:
    """Get system health status."""
    try:
        from src.system_health_check import get_health_status
        return get_health_status()
    except:
        return {
            "signal_engine": "unknown",
            "decision_engine": "unknown",
            "trade_execution": "unknown",
            "self_healing": "unknown",
        }


# Build Dashboard App
def build_app(server: Flask = None) -> Dash:
    """Build and return the Dash app."""
    
    # Initialize Flask server if not provided
    if server is None:
        server = Flask(__name__)
        server.secret_key = os.environ.get('FLASK_SECRET_KEY', hashlib.sha256(DASHBOARD_PASSWORD.encode()).hexdigest())
    
    app = Dash(__name__, server=server, external_stylesheets=[dbc.themes.DARKLY])
    app.title = APP_TITLE
    
    # Set server secret key if not already set
    if not hasattr(server, 'secret_key') or not server.secret_key:
        server.secret_key = os.environ.get('FLASK_SECRET_KEY', hashlib.sha256(DASHBOARD_PASSWORD.encode()).hexdigest())
    
    # Don't load data at build time - let callbacks load it on demand
    # Initial data load removed - prevents errors if data files don't exist yet
    
    # System Health Component
    def system_health_panel() -> html.Div:
        health = get_system_health()
        
        def status_indicator(status: str) -> str:
            if status == "healthy":
                return "🟢"
            elif status == "warning":
                return "🟡"
            elif status == "error":
                return "🔴"
            else:
                return "⚪"
        
        return html.Div([
            html.H4("System Health", style={"color": "#fff", "marginBottom": "12px"}),
            dbc.Row([
                dbc.Col([
                    html.Div([
                        html.Span(status_indicator(health.get("signal_engine", "unknown")), style={"fontSize": "24px", "marginRight": "8px"}),
                        html.Span("Signal Engine", style={"color": "#e8eaed"}),
                    ]),
                ]),
                dbc.Col([
                    html.Div([
                        html.Span(status_indicator(health.get("decision_engine", "unknown")), style={"fontSize": "24px", "marginRight": "8px"}),
                        html.Span("Decision Engine", style={"color": "#e8eaed"}),
                    ]),
                ]),
                dbc.Col([
                    html.Div([
                        html.Span(status_indicator(health.get("trade_execution", "unknown")), style={"fontSize": "24px", "marginRight": "8px"}),
                        html.Span("Trade Execution", style={"color": "#e8eaed"}),
                    ]),
                ]),
                dbc.Col([
                    html.Div([
                        html.Span(status_indicator(health.get("self_healing", "unknown")), style={"fontSize": "24px", "marginRight": "8px"}),
                        html.Span("Self-Healing", style={"color": "#e8eaed"}),
                    ]),
                ]),
            ]),
        ], style={"backgroundColor": "#0f1217", "borderRadius": "8px", "padding": "16px", "marginBottom": "20px"})
    
    # Authentication (simplified)
    from flask import session, request, redirect, url_for, render_template_string
    
    # Get Flask server from Dash app (Dash creates its own server wrapper)
    # IMPORTANT: Use app.server, not the original server variable, as Dash wraps it
    flask_server = app.server
    
    login_template = """
    <!DOCTYPE html>
    <html>
    <head>
        <title>Dashboard Login</title>
        <style>
            body { background: #0b0e13; color: #fff; font-family: Arial; padding: 40px; text-align: center; }
            form { max-width: 400px; margin: 0 auto; padding: 20px; background: #0f1217; border-radius: 8px; }
            input { width: 100%; padding: 12px; margin: 10px 0; border: 1px solid #2d3139; background: #1b1f2a; color: #fff; border-radius: 4px; }
            button { width: 100%; padding: 12px; margin: 10px 0; background: #1a73e8; color: #fff; border: none; border-radius: 4px; cursor: pointer; }
            button:hover { background: #1557b0; }
            h2 { color: #fff; }
        </style>
    </head>
    <body>
        <h2>P&L Dashboard Login</h2>
        <form method="post">
            <input type="password" name="password" placeholder="Password" required>
            <button type="submit">Login</button>
        </form>
    </body>
    </html>
    """
    
    # Register routes only if they don't already exist (prevent duplicate route errors)
    try:
        existing_rules = [rule.rule for rule in flask_server.url_map.iter_rules()]
        has_login = '/login' in existing_rules
        has_logout = '/logout' in existing_rules
    except:
        has_login = False
        has_logout = False
    
    if not has_login:
        @flask_server.route('/login', methods=['GET', 'POST'])
        def login():
            if request.method == 'POST':
                password = request.form.get('password', '')
                if hashlib.sha256(password.encode()).hexdigest() == DASHBOARD_PASSWORD_HASH:
                    session['authenticated'] = True
                    return redirect('/')
                return render_template_string(login_template + '<p style="color: #ea4335;">Invalid password</p>')
            return render_template_string(login_template)
    
    if not has_logout:
        @flask_server.route('/logout')
        def logout():
            session.pop('authenticated', None)
            return redirect('/login')
    
    # Main Layout
    app.layout = html.Div([
        html.Div([
            html.H2(APP_TITLE, style={"color": "#fff", "margin": "8px 0", "display": "inline-block"}),
            html.A("Logout", href="/logout", style={
                "float": "right",
                "backgroundColor": "#ea4335",
                "color": "#fff",
                "padding": "8px 16px",
                "borderRadius": "4px",
                "textDecoration": "none",
                "marginTop": "8px",
            }),
        ], style={"marginBottom": "20px"}),
        
        # System Health
        html.Div(id="system-health-container"),
        dcc.Interval(id="system-health-interval", interval=5*60*1000, n_intervals=0),
        
        # Tabs: Daily Summary and Executive Summary
        dcc.Tabs(id="main-tabs", value="daily", children=[
            dcc.Tab(
                label="📅 Daily Summary",
                value="daily",
                style={"backgroundColor": "#1b1f2a", "color": "#9aa0a6"},
                selected_style={"backgroundColor": "#1a73e8", "color": "#fff"},
            ),
            dcc.Tab(
                label="📋 Executive Summary",
                value="executive",
                style={"backgroundColor": "#1b1f2a", "color": "#9aa0a6"},
                selected_style={"backgroundColor": "#1a73e8", "color": "#fff"},
            ),
        ]),
        
        html.Div(id="tab-content", style={"marginTop": "20px"}),
        
        # Refresh intervals
        dcc.Interval(id="refresh-interval", interval=5*60*1000, n_intervals=0),  # 5 minutes
    ], style={"backgroundColor": "#0b0e13", "fontFamily": "Inter, Segoe UI, Arial", "padding": "20px", "minHeight": "100vh"})
    
    # Callbacks
    @app.callback(
        Output("system-health-container", "children"),
        Input("system-health-interval", "n_intervals"),
    )
    def update_system_health(n):
        return system_health_panel()
    
    @app.callback(
        Output("tab-content", "children"),
        Input("main-tabs", "value"),
        Input("refresh-interval", "n_intervals"),
    )
    def update_tab_content(tab, n_intervals):
        """Update tab content based on selected tab and refresh interval."""
        try:
            if tab == "daily":
                return build_daily_summary_tab()
            elif tab == "executive":
                return build_executive_summary_tab()
            return html.Div("Unknown tab", style={"color": "#fff"})
        except Exception as e:
            print(f"⚠️  Error updating tab content: {e}")
            import traceback
            traceback.print_exc()
            return html.Div([
                html.H4("Error loading content", style={"color": "#ea4335"}),
                html.P(str(e), style={"color": "#9aa0a6"}),
            ])
    
    # Note: Tables are updated via the tab content refresh callback
    # which rebuilds the entire tab when refresh-interval fires
    
    print("✅ [DASHBOARD-V2] Dashboard app fully configured")
    return app


def build_daily_summary_tab() -> html.Div:
    """Build Daily Summary tab content."""
    try:
        wallet_balance = get_wallet_balance()
        daily_summary = compute_summary(wallet_balance, lookback_days=1)
        weekly_summary = compute_summary(wallet_balance, lookback_days=7)
        monthly_summary = compute_summary(wallet_balance, lookback_days=30)
        
        closed_df = load_closed_positions_df()
        open_df = load_open_positions_df()
    except Exception as e:
        print(f"⚠️  [DASHBOARD-V2] Error building daily summary tab: {e}", flush=True)
        import traceback
        traceback.print_exc()
        # Return empty but functional dashboard instead of error
        wallet_balance = 10000.0
        empty_summary = {
            "wallet_balance": wallet_balance,
            "total_trades": 0,
            "wins": 0,
            "losses": 0,
            "win_rate": 0.0,
            "net_pnl": 0.0,
            "avg_win": 0.0,
            "avg_loss": 0.0,
            "drawdown_pct": 0.0,
        }
        daily_summary = weekly_summary = monthly_summary = empty_summary
        closed_df = pd.DataFrame(columns=["symbol", "strategy", "entry_time", "exit_time", "entry_price", "exit_price", "size", "hold_duration_h", "roi_pct", "net_pnl", "fees"])
        open_df = pd.DataFrame(columns=["symbol", "strategy", "side", "entry_price", "current_price", "size", "margin_collateral", "leverage", "pnl_usd", "pnl_pct", "entry_time"])
    
    def summary_card(summary: dict, label: str) -> dbc.Card:
        pnl_color = "#34a853" if summary["net_pnl"] >= 0 else "#ea4335"
        wr_color = "#34a853" if summary["win_rate"] >= 50 else "#ea4335"
        
        return dbc.Card([
            dbc.CardHeader(html.H4(label, style={"color": "#fff", "margin": 0})),
            dbc.CardBody([
                dbc.Row([
                    dbc.Col([
                        html.Div(f"${summary['wallet_balance']:.2f}", style={"fontSize": "28px", "fontWeight": "bold", "color": "#1a73e8"}),
                        html.Div("Wallet Balance", style={"fontSize": "12px", "color": "#9aa0a6"}),
                    ]),
                    dbc.Col([
                        html.Div(f"{summary['total_trades']}", style={"fontSize": "28px", "fontWeight": "bold", "color": "#fff"}),
                        html.Div("Total Trades", style={"fontSize": "12px", "color": "#9aa0a6"}),
                    ]),
                    dbc.Col([
                        html.Div(f"${summary['net_pnl']:.2f}", style={"fontSize": "28px", "fontWeight": "bold", "color": pnl_color}),
                        html.Div("Net P&L", style={"fontSize": "12px", "color": "#9aa0a6"}),
                    ]),
                    dbc.Col([
                        html.Div(f"{summary['win_rate']:.1f}%", style={"fontSize": "28px", "fontWeight": "bold", "color": wr_color}),
                        html.Div("Win Rate", style={"fontSize": "12px", "color": "#9aa0a6"}),
                    ]),
                    dbc.Col([
                        html.Div(f"{summary['wins']}/{summary['losses']}", style={"fontSize": "28px", "fontWeight": "bold", "color": "#fff"}),
                        html.Div("Wins/Losses", style={"fontSize": "12px", "color": "#9aa0a6"}),
                    ]),
                    dbc.Col([
                        html.Div(f"${summary['avg_win']:.2f}", style={"fontSize": "20px", "fontWeight": "bold", "color": "#34a853"}),
                        html.Div(f"${summary['avg_loss']:.2f}", style={"fontSize": "20px", "fontWeight": "bold", "color": "#ea4335"}),
                        html.Div("Avg Win/Loss", style={"fontSize": "12px", "color": "#9aa0a6"}),
                    ]),
                ]),
            ]),
        ], style={"backgroundColor": "#0f1217", "border": "1px solid #2d3139", "marginBottom": "20px"})
    
        # Open Positions Table
    open_table = html.Div([
        html.H4(f"Open Positions ({len(open_df)} active)", style={"color": "#fff", "marginBottom": "12px"}),
        dash_table.DataTable(
            id="open-positions-table",
            columns=[
                {"name": "Symbol", "id": "symbol"},
                {"name": "Strategy", "id": "strategy"},
                {"name": "Side", "id": "side"},
                {"name": "Entry Price", "id": "entry_price", "type": "numeric", "format": {"specifier": ".4f"}},
                {"name": "Current Price", "id": "current_price", "type": "numeric", "format": {"specifier": ".4f"}},
                {"name": "Margin", "id": "margin_collateral", "type": "numeric", "format": {"specifier": ".2f"}},
                {"name": "Leverage", "id": "leverage"},
                {"name": "P&L ($)", "id": "pnl_usd", "type": "numeric", "format": {"specifier": ".2f"}},
                {"name": "P&L (%)", "id": "pnl_pct", "type": "numeric", "format": {"specifier": ".2f"}},
            ],
            data=open_df.to_dict("records") if not open_df.empty else [],
            style_table={"backgroundColor": "#0f1217", "color": "#e8eaed"},
            style_cell={"backgroundColor": "#0f1217", "color": "#e8eaed", "textAlign": "left", "padding": "10px"},
            style_header={"backgroundColor": "#1b1f2a", "fontWeight": "bold"},
            style_data_conditional=[
                {
                    "if": {"filter_query": "{pnl_usd} >= 0"},
                    "backgroundColor": "#1a4d2e",
                    "color": "#00ff88",
                },
                {
                    "if": {"filter_query": "{pnl_usd} < 0"},
                    "backgroundColor": "#4d1a1a",
                    "color": "#ff4444",
                },
            ],
        ),
    ], style={"backgroundColor": "#0f1217", "borderRadius": "8px", "padding": "16px", "marginBottom": "20px"})
    
        # Closed Positions Table
    closed_table = html.Div([
        html.H4(f"Closed Trades (Recent - Showing {min(100, len(closed_df))} of {len(closed_df)} total)", style={"color": "#fff", "marginBottom": "12px"}),
        dash_table.DataTable(
            id="closed-positions-table",
            columns=[
                {"name": "Symbol", "id": "symbol"},
                {"name": "Strategy", "id": "strategy"},
                {"name": "Entry Time", "id": "entry_time"},
                {"name": "Exit Time", "id": "exit_time"},
                {"name": "Entry Price", "id": "entry_price", "type": "numeric", "format": {"specifier": ".4f"}},
                {"name": "Exit Price", "id": "exit_price", "type": "numeric", "format": {"specifier": ".4f"}},
                {"name": "Hold (h)", "id": "hold_duration_h", "type": "numeric", "format": {"specifier": ".1f"}},
                {"name": "ROI (%)", "id": "roi_pct", "type": "numeric", "format": {"specifier": ".2f"}},
                {"name": "Net P&L", "id": "net_pnl", "type": "numeric", "format": {"specifier": ".2f"}},
                {"name": "Fees", "id": "fees", "type": "numeric", "format": {"specifier": ".2f"}},
            ],
            data=closed_df.head(100).to_dict("records") if not closed_df.empty else [],
            page_size=20,
            style_table={"backgroundColor": "#0f1217", "color": "#e8eaed"},
            style_cell={"backgroundColor": "#0f1217", "color": "#e8eaed", "textAlign": "left", "padding": "10px"},
            style_header={"backgroundColor": "#1b1f2a", "fontWeight": "bold"},
            style_data_conditional=[
                {
                    "if": {"filter_query": "{net_pnl} >= 0"},
                    "backgroundColor": "#1a4d2e",
                    "color": "#00ff88",
                },
                {
                    "if": {"filter_query": "{net_pnl} < 0"},
                    "backgroundColor": "#4d1a1a",
                    "color": "#ff4444",
                },
            ],
        ),
    ], style={"backgroundColor": "#0f1217", "borderRadius": "8px", "padding": "16px", "marginBottom": "20px"})
    
    return html.Div([
        # Summary Cards (Daily, Weekly, Monthly)
        summary_card(daily_summary, "📅 Daily Summary (Last 24 Hours)"),
        summary_card(weekly_summary, "📊 Weekly Summary (Last 7 Days)"),
        summary_card(monthly_summary, "📈 Monthly Summary (Last 30 Days)"),
        
        # Wallet Balance Trend
        html.Div([
            html.H4("Wallet Balance Trend", style={"color": "#fff", "marginBottom": "12px"}),
            dcc.Graph(figure=create_wallet_balance_trend(), config={"displayModeBar": True}),
        ], style={"backgroundColor": "#0f1217", "borderRadius": "8px", "padding": "16px", "marginBottom": "20px"}),
        
        # Charts Row 1
        dbc.Row([
            dbc.Col([
                html.Div([
                    html.H4("Equity Curve", style={"color": "#fff", "marginBottom": "12px"}),
                    dcc.Graph(figure=create_equity_curve_chart(closed_df), config={"displayModeBar": True}),
                ], style={"backgroundColor": "#0f1217", "borderRadius": "8px", "padding": "16px"}),
            ], width=6),
            dbc.Col([
                html.Div([
                    html.H4("P&L by Symbol", style={"color": "#fff", "marginBottom": "12px"}),
                    dcc.Graph(figure=create_pnl_by_symbol_chart(closed_df), config={"displayModeBar": True}),
                ], style={"backgroundColor": "#0f1217", "borderRadius": "8px", "padding": "16px"}),
            ], width=6),
        ], style={"marginBottom": "20px"}),
        
        # Charts Row 2
        dbc.Row([
            dbc.Col([
                html.Div([
                    html.H4("P&L by Strategy", style={"color": "#fff", "marginBottom": "12px"}),
                    dcc.Graph(figure=create_pnl_by_strategy_chart(closed_df), config={"displayModeBar": True}),
                ], style={"backgroundColor": "#0f1217", "borderRadius": "8px", "padding": "16px"}),
            ], width=6),
            dbc.Col([
                html.Div([
                    html.H4("Win Rate Heatmap", style={"color": "#fff", "marginBottom": "12px"}),
                    dcc.Graph(figure=create_win_rate_heatmap(closed_df), config={"displayModeBar": True}),
                ], style={"backgroundColor": "#0f1217", "borderRadius": "8px", "padding": "16px"}),
            ], width=6),
        ], style={"marginBottom": "20px"}),
        
        # Tables
        open_table,
        closed_table,
    ])


def build_executive_summary_tab() -> html.Div:
    """Build Executive Summary tab content."""
    try:
        summary = generate_executive_summary()
    except Exception as e:
        print(f"⚠️  Error generating executive summary: {e}")
        import traceback
        traceback.print_exc()
        summary = {
            "what_worked_today": f"Error generating summary: {str(e)}",
            "what_didnt_work": "",
            "missed_opportunities": "",
            "blocked_signals": "",
            "exit_gates": "",
            "learning_today": "",
            "changes_tomorrow": "",
            "weekly_summary": "",
        }
    
    return html.Div([
        dbc.Card([
            dbc.CardHeader(html.H3("📋 Executive Summary", style={"color": "#fff", "margin": 0})),
            dbc.CardBody([
                html.Div([
                    html.H4("✅ What Worked Today", style={"color": "#34a853", "marginTop": "20px"}),
                    html.P(summary.get("what_worked_today", "No data available."), style={"color": "#e8eaed", "whiteSpace": "pre-wrap"}),
                    
                    html.H4("❌ What Didn't Work", style={"color": "#ea4335", "marginTop": "20px"}),
                    html.P(summary.get("what_didnt_work", "No data available."), style={"color": "#e8eaed", "whiteSpace": "pre-wrap"}),
                    
                    html.H4("🎯 Missed Opportunities", style={"color": "#fbbc04", "marginTop": "20px"}),
                    html.P(summary.get("missed_opportunities", "No data available."), style={"color": "#e8eaed", "whiteSpace": "pre-wrap"}),
                    
                    html.H4("🚫 Blocked Signals", style={"color": "#9aa0a6", "marginTop": "20px"}),
                    html.P(summary.get("blocked_signals", "No data available."), style={"color": "#e8eaed", "whiteSpace": "pre-wrap"}),
                    
                    html.H4("🚪 Exit Gates Analysis", style={"color": "#1a73e8", "marginTop": "20px"}),
                    html.P(summary.get("exit_gates", "No data available."), style={"color": "#e8eaed", "whiteSpace": "pre-wrap"}),
                    
                    html.H4("🧠 Learning Today", style={"color": "#9c27b0", "marginTop": "20px"}),
                    html.P(summary.get("learning_today", "No data available."), style={"color": "#e8eaed", "whiteSpace": "pre-wrap"}),
                    
                    html.H4("📅 Changes Tomorrow", style={"color": "#00bcd4", "marginTop": "20px"}),
                    html.P(summary.get("changes_tomorrow", "No data available."), style={"color": "#e8eaed", "whiteSpace": "pre-wrap"}),
                    
                    html.H4("📊 Weekly Summary", style={"color": "#ff9800", "marginTop": "20px"}),
                    html.P(summary.get("weekly_summary", "No data available."), style={"color": "#e8eaed", "whiteSpace": "pre-wrap"}),
                ]),
            ]),
        ], style={"backgroundColor": "#0f1217", "border": "1px solid #2d3139"}),
    ])


def start_pnl_dashboard(flask_app: Flask = None) -> Dash:
    """
    Start the P&L dashboard - entry point for run.py.
    Returns Dash app instance.
    
    CRITICAL: For Gunicorn with multiple workers, we need to ensure Dash
    dependencies are properly registered in each worker process.
    """
    try:
        print("🔍 [DASHBOARD-V2] Starting dashboard initialization...", flush=True)
        
        # CRITICAL: Register Dash dependencies before building app
        # This is required for Gunicorn workers to load Dash components correctly
        try:
            import dash
            import dash_bootstrap_components as dbc
            # Force Dash to register its component suites
            # This ensures Gunicorn workers can load Dash dependencies
            print("🔍 [DASHBOARD-V2] Registering Dash dependencies...", flush=True)
            # Dash registers dependencies on first import, so importing here ensures they're available
            _ = dash.__version__
            _ = dbc.__version__
            print("✅ [DASHBOARD-V2] Dash dependencies registered", flush=True)
        except Exception as e:
            print(f"⚠️  [DASHBOARD-V2] Warning: Dash dependency registration issue: {e}", flush=True)
            # Continue anyway - might still work
        
        # Initialize positions file on startup
        try:
            from src.position_manager import initialize_futures_positions
            print("🔍 [DASHBOARD-V2] Initializing positions file...", flush=True)
            initialize_futures_positions()
            print("✅ [DASHBOARD-V2] Initialized/verified positions_futures.json structure", flush=True)
        except Exception as e:
            print(f"⚠️  [DASHBOARD-V2] Failed to initialize positions file: {e}", flush=True)
            # Don't crash - continue without initialization
        
        print("🔍 [DASHBOARD-V2] Building dashboard app...", flush=True)
        app = build_app(server=flask_app)
        
        if app is None:
            raise RuntimeError("build_app() returned None - dashboard build failed")
        
        # CRITICAL: Ensure Dash app is fully configured for Gunicorn
        # Set app.config to ensure proper worker initialization
        if hasattr(app, 'config'):
            app.config.suppress_callback_exceptions = True
        
        print("✅ [DASHBOARD-V2] Dashboard app built successfully", flush=True)
        return app
    except Exception as e:
        print(f"❌ [DASHBOARD-V2] CRITICAL: Dashboard startup failed: {type(e).__name__}: {e}", flush=True)
        import traceback
        traceback.print_exc()
        raise


if __name__ == "__main__":
    from flask import Flask
    flask_app = Flask(__name__)
    app = build_app(server=flask_app)
    app.run_server(debug=False, host="0.0.0.0", port=PORT)
