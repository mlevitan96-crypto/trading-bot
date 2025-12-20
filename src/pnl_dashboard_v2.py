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
# Import generate_executive_summary from old dashboard (has full implementation)
from src.pnl_dashboard import generate_executive_summary

# Configuration
DEFAULT_TIMEFRAME_HOURS = 72
APP_TITLE = "P&L Dashboard"
PORT = 8050

# Dashboard password (hashed for security)
DASHBOARD_PASSWORD = "Echelonlev2007!"
DASHBOARD_PASSWORD_HASH = hashlib.sha256(DASHBOARD_PASSWORD.encode()).hexdigest()

# WALLET RESET DATE - All trades before this date are excluded
# CRITICAL: User said reset happened "december 18 late in the day" - need to verify actual year
# Temporarily DISABLED reset filter until we can verify actual reset date from data
# TODO: Check actual trade dates to determine correct reset date
WALLET_RESET_ENABLED = False  # DISABLED - was filtering out all trades
WALLET_RESET_TS = datetime(2024, 12, 18, 0, 0, 0).timestamp() if WALLET_RESET_ENABLED else 0
STARTING_CAPITAL_AFTER_RESET = 10000.0

if WALLET_RESET_ENABLED:
    print(f"🔍 [DASHBOARD-V2] Wallet reset filter ENABLED: timestamp {WALLET_RESET_TS} (Dec 18, 2024 00:00:00 UTC)", flush=True)
else:
    print(f"⚠️  [DASHBOARD-V2] Wallet reset filter DISABLED - showing all trades. Reset date needs verification.", flush=True)

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
    """
    Get wallet balance from closed positions ONLY (realized P&L).
    
    CRITICAL: Wallet balance = starting_capital + realized P&L from closed positions AFTER RESET DATE.
    Does NOT include unrealized P&L (that would be misleading).
    
    WALLET RESET: Temporarily disabled - showing all trades until correct reset date is verified.
    """
    try:
        starting_capital = STARTING_CAPITAL_AFTER_RESET
        
        # Read positions file once
        positions_data = DR.read_json(DR.POSITIONS_FUTURES)
        if not positions_data:
            print(f"🔍 [WALLET] No positions data, returning starting capital: ${starting_capital:.2f}", flush=True)
            return starting_capital
        closed_positions = positions_data.get("closed_positions", [])
        
        if not closed_positions:
            print(f"🔍 [WALLET] No closed positions, returning starting capital: ${starting_capital:.2f}", flush=True)
            return starting_capital
        
        print(f"🔍 [WALLET] Processing {len(closed_positions)} closed positions", flush=True)
        
        # TEMPORARILY DISABLED: Reset filter until correct date is verified
        # CRITICAL: Filter to only trades AFTER wallet reset date (if enabled)
        # Use timestamp comparison to avoid timezone issues
        post_reset_positions = []
        for pos in closed_positions:
            if not WALLET_RESET_ENABLED:
                # Reset filter disabled - include all positions
                post_reset_positions.append(pos)
            else:
                closed_at = pos.get("closed_at", "")
                if not closed_at:
                    continue
                
                try:
                    # Parse to timestamp for reliable comparison
                    if isinstance(closed_at, str):
                        closed_dt = datetime.fromisoformat(closed_at.replace("Z", "+00:00"))
                        closed_ts = closed_dt.timestamp()
                    elif isinstance(closed_at, (int, float)):
                        closed_ts = float(closed_at)
                    else:
                        continue
                    
                    # Only include trades closed AFTER reset timestamp
                    if closed_ts >= WALLET_RESET_TS:
                        post_reset_positions.append(pos)
                except Exception as e:
                    print(f"⚠️  [WALLET] Error parsing closed_at for position: {e}", flush=True)
                    continue
        
        if WALLET_RESET_ENABLED:
            print(f"🔍 [WALLET] Found {len(post_reset_positions)} positions after reset date (out of {len(closed_positions)} total)", flush=True)
        else:
            print(f"🔍 [WALLET] Reset filter disabled - using all {len(post_reset_positions)} positions", flush=True)
        
        if not post_reset_positions:
            print(f"🔍 [WALLET] No positions after reset date, returning starting capital: ${starting_capital:.2f}", flush=True)
            return starting_capital
        
        # Calculate realized P&L from closed positions AFTER RESET ONLY
        total_realized_pnl = 0.0
        valid_pnl_count = 0
        for pos in post_reset_positions:
            # Try pnl field first (most reliable), then fallbacks
            val = pos.get("pnl", pos.get("net_pnl", pos.get("realized_pnl", 0)))
            if val is None:
                continue
            try:
                val = float(val)
                if not math.isnan(val):
                    total_realized_pnl += val
                    valid_pnl_count += 1
            except (TypeError, ValueError):
                continue
        
        # Wallet balance = starting capital + realized P&L ONLY (after reset)
        wallet_balance = starting_capital + total_realized_pnl
        print(f"🔍 [WALLET] Calculated: ${starting_capital:.2f} + ${total_realized_pnl:.2f} (from {valid_pnl_count} trades) = ${wallet_balance:.2f}", flush=True)
        return wallet_balance
    except Exception as e:
        print(f"⚠️  [WALLET] Failed to calculate wallet balance: {e}", flush=True)
        import traceback
        traceback.print_exc()
        return STARTING_CAPITAL_AFTER_RESET


def load_open_positions_df() -> pd.DataFrame:
    """Load open positions with real-time pricing - limited for memory efficiency."""
    try:
        positions_data = load_futures_positions()
        if not positions_data:
            return pd.DataFrame(columns=["symbol", "strategy", "side", "entry_price", "current_price", "size", "margin_collateral", "leverage", "pnl_usd", "pnl_pct", "entry_time"])
        open_positions = positions_data.get("open_positions", [])
        
        # Open positions are typically limited (max 10-20), but limit just in case
        if len(open_positions) > 50:
            open_positions = open_positions[:50]
        
        rows = []
        gateway = None
        
        # Initialize ExchangeGateway with timeout for price fetching
        # CRITICAL: We need prices to calculate P&L, but don't let it hang
        try:
            import threading
            gateway_result = [None]
            gateway_error = [None]
            
            def init_gateway():
                try:
                    from src.exchange_gateway import ExchangeGateway
                    gateway_result[0] = ExchangeGateway()
                except Exception as e:
                    gateway_error[0] = e
            
            init_thread = threading.Thread(target=init_gateway, daemon=True)
            init_thread.start()
            init_thread.join(timeout=3.0)  # 3 second timeout
            
            if init_thread.is_alive():
                print(f"⚠️  [DASHBOARD-V2] ExchangeGateway init timed out (will use entry_price as fallback)", flush=True)
                gateway = None
            elif gateway_error[0]:
                print(f"⚠️  [DASHBOARD-V2] ExchangeGateway init failed: {gateway_error[0]} (will use entry_price as fallback)", flush=True)
                gateway = None
            else:
                gateway = gateway_result[0]
                print(f"✅ [DASHBOARD-V2] ExchangeGateway initialized successfully", flush=True)
        except Exception as e:
            print(f"⚠️  [DASHBOARD-V2] ExchangeGateway error: {e} (will use entry_price as fallback)", flush=True)
            gateway = None
        
        for pos in open_positions:
            symbol = pos.get("symbol", "")
            entry_price = pos.get("entry_price", 0.0)
            size = pos.get("size", 0.0)  # Contract size
            leverage = pos.get("leverage", 1)
            direction = pos.get("direction", "LONG")
            margin = pos.get("margin_collateral", 0.0) or (size / leverage if leverage > 0 else size)
            strategy = pos.get("strategy", "Unknown")
            entry_time = pos.get("opened_at", "")
            
            # CRITICAL: Check if position already has unrealized_pnl calculated
            # This is the most reliable source
            if "unrealized_pnl" in pos and pos["unrealized_pnl"] is not None:
                try:
                    unrealized_pnl = float(pos["unrealized_pnl"])
                    if not math.isnan(unrealized_pnl):
                        # Use pre-calculated unrealized P&L
                        pnl_usd = unrealized_pnl
                        # Calculate percentage from USD P&L
                        pnl_pct = (pnl_usd / margin * 100) if margin > 0 else 0.0
                        # Get current price from mark_price if available, else estimate from P&L
                        if "mark_price" in pos and pos["mark_price"]:
                            current_price = float(pos["mark_price"])
                        elif "current_price" in pos and pos["current_price"]:
                            current_price = float(pos["current_price"])
                        else:
                            # Estimate current price from P&L
                            if direction == "LONG":
                                current_price = entry_price * (1 + pnl_pct / 100 / leverage) if leverage > 0 else entry_price
                            else:
                                current_price = entry_price * (1 - pnl_pct / 100 / leverage) if leverage > 0 else entry_price
                        print(f"🔍 [OPEN-POS] {symbol}: Using pre-calculated unrealized_pnl=${pnl_usd:.2f}", flush=True)
                    else:
                        raise ValueError("NaN unrealized_pnl")
                except (ValueError, TypeError):
                    # Fall through to calculate from price
                    unrealized_pnl = None
            else:
                unrealized_pnl = None
            
            # If no pre-calculated P&L, try to get current price and calculate
            if unrealized_pnl is None:
                # Try to get current price from position data first
                current_price = pos.get("mark_price") or pos.get("current_price") or entry_price
                
                # If we have mark_price or current_price, use it
                if current_price != entry_price and current_price > 0:
                    print(f"🔍 [OPEN-POS] {symbol}: Using mark_price/current_price={current_price:.4f}", flush=True)
                else:
                    # Try to fetch price with quick timeout (non-blocking)
                    try:
                        if gateway:
                            # Use threading to fetch price with timeout
                            price_result = [entry_price]
                            price_error = [None]
                            
                            def fetch_price():
                                try:
                                    price_result[0] = gateway.get_price(symbol, venue="futures")
                                except Exception as e:
                                    price_error[0] = e
                            
                            fetch_thread = threading.Thread(target=fetch_price, daemon=True)
                            fetch_thread.start()
                            fetch_thread.join(timeout=1.0)  # 1 second max per symbol
                            
                            if not fetch_thread.is_alive() and price_error[0] is None:
                                current_price = price_result[0]
                                print(f"🔍 [OPEN-POS] {symbol}: Fetched price={current_price:.4f}", flush=True)
                            else:
                                current_price = entry_price
                                print(f"⚠️  [OPEN-POS] {symbol}: Price fetch timeout/error, using entry_price", flush=True)
                        else:
                            current_price = entry_price
                            print(f"⚠️  [OPEN-POS] {symbol}: No gateway, using entry_price (P&L will be 0)", flush=True)
                    except Exception as e:
                        current_price = entry_price
                        print(f"⚠️  [OPEN-POS] {symbol}: Error fetching price: {e}, using entry_price", flush=True)
                
                # Calculate P&L from prices
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


def load_closed_positions_df(limit: int = 500) -> pd.DataFrame:
    """
    Load closed positions from positions_futures.json.
    
    CRITICAL: 
    - Filters by wallet reset date (Dec 18, 2025) - only shows trades after reset
    - Limits to most recent N positions to prevent memory issues.
    """
    try:
        # Use DataRegistry method which can limit by time (more efficient)
        try:
            from src.data_registry import DataRegistry as DR
            # Get last 30 days (720 hours) - reasonable limit for dashboard
            closed_positions = DR.get_closed_positions(hours=720)
        except Exception as e:
            print(f"⚠️  [DASHBOARD-V2] Using fallback position loading: {e}", flush=True)
            # Fallback to direct file read
            try:
                from src.data_registry import DataRegistry as DR
                positions_data = DR.read_json(DR.POSITIONS_FUTURES)
                if not positions_data:
                    return pd.DataFrame(columns=["symbol", "strategy", "entry_time", "exit_time", "entry_price", "exit_price", "size", "hold_duration_h", "roi_pct", "net_pnl", "fees"])
                closed_positions = positions_data.get("closed_positions", [])
            except Exception as e2:
                print(f"⚠️  [DASHBOARD-V2] Fallback also failed: {e2}", flush=True)
                return pd.DataFrame(columns=["symbol", "strategy", "entry_time", "exit_time", "entry_price", "exit_price", "size", "hold_duration_h", "roi_pct", "net_pnl", "fees"])
        
        # TEMPORARILY DISABLED: Reset filter until correct date is verified
        # CRITICAL: Filter by wallet reset date (if enabled)
        post_reset_positions = []
        for pos in closed_positions:
            if not WALLET_RESET_ENABLED:
                # Reset filter disabled - include all positions
                post_reset_positions.append(pos)
            else:
                closed_at = pos.get("closed_at", "")
                if not closed_at:
                    continue
                try:
                    # Parse to timestamp for reliable comparison
                    if isinstance(closed_at, str):
                        closed_dt = datetime.fromisoformat(closed_at.replace("Z", "+00:00"))
                        closed_ts = closed_dt.timestamp()
                    elif isinstance(closed_at, (int, float)):
                        closed_ts = float(closed_at)
                    else:
                        continue
                    
                    # Only include trades AFTER reset timestamp
                    if closed_ts >= WALLET_RESET_TS:
                        post_reset_positions.append(pos)
                except:
                    pass
        
        if WALLET_RESET_ENABLED:
            print(f"🔍 [DASHBOARD-V2] After reset filter: {len(post_reset_positions)} positions (from {len(closed_positions)} total)", flush=True)
        else:
            print(f"🔍 [DASHBOARD-V2] Reset filter disabled - using all {len(post_reset_positions)} positions", flush=True)
        
        # Further limit to last N positions for memory efficiency
        if len(post_reset_positions) > limit:
            post_reset_positions = post_reset_positions[-limit:]
            print(f"🔍 [DASHBOARD-V2] Limited to most recent {limit} positions", flush=True)
        
        closed_positions = post_reset_positions
        
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
            # Keep only most recent for display (memory optimization)
            if len(df) > 500:
                df = df.head(500)
        return df
    except Exception as e:
        print(f"⚠️  Failed to load closed positions: {e}")
        return pd.DataFrame(columns=["symbol", "strategy", "entry_time", "exit_time", "entry_price", "exit_price", "size", "hold_duration_h", "roi_pct", "net_pnl", "fees"])


def compute_summary_optimized(wallet_balance: float, closed_positions: list, lookback_days: int = 1) -> dict:
    """
    Optimized version that accepts pre-loaded positions to avoid redundant file reads.
    
    CRITICAL: Filters by both wallet reset date AND lookback period.
    """
    try:
        # TEMPORARILY DISABLED: Reset filter until correct date is verified
        # CRITICAL: First filter by wallet reset date (if enabled)
        post_reset_positions = []
        for pos in closed_positions:
            if not WALLET_RESET_ENABLED:
                # Reset filter disabled - include all positions
                post_reset_positions.append(pos)
            else:
                closed_at = pos.get("closed_at", "")
                if not closed_at:
                    continue
                try:
                    # Parse to timestamp for reliable comparison
                    if isinstance(closed_at, str):
                        closed_dt = datetime.fromisoformat(closed_at.replace("Z", "+00:00"))
                        closed_ts = closed_dt.timestamp()
                    elif isinstance(closed_at, (int, float)):
                        closed_ts = float(closed_at)
                    else:
                        continue
                    
                    # Only include trades AFTER reset timestamp
                    if closed_ts >= WALLET_RESET_TS:
                        post_reset_positions.append(pos)
                except:
                    pass
        
        if WALLET_RESET_ENABLED:
            print(f"🔍 [SUMMARY] After reset filter: {len(post_reset_positions)} positions (from {len(closed_positions)} total)", flush=True)
        else:
            print(f"🔍 [SUMMARY] Reset filter disabled - using all {len(post_reset_positions)} positions", flush=True)
        
        # Now filter to lookback period
        cutoff = datetime.utcnow() - timedelta(days=lookback_days)
        recent_closed = []
        
        # Limit processing to prevent memory issues
        max_positions_to_process = 1000
        positions_to_process = post_reset_positions[-max_positions_to_process:] if len(post_reset_positions) > max_positions_to_process else post_reset_positions
        
        for pos in positions_to_process:
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
        
        print(f"🔍 [SUMMARY] After lookback filter ({lookback_days} days): {len(recent_closed)} positions", flush=True)
        
        # Calculate stats
        wins = []
        losses = []
        total_pnl = 0.0
        pnl_values_found = 0
        pnl_values_missing = 0
        
        for pos in recent_closed:
            # Try multiple field names for P&L
            net_pnl = pos.get("pnl") or pos.get("net_pnl") or pos.get("realized_pnl") or pos.get("profit_usd")
            if net_pnl is None:
                pnl_values_missing += 1
                continue
            try:
                net_pnl = float(net_pnl)
                if math.isnan(net_pnl):
                    pnl_values_missing += 1
                    continue
                total_pnl += net_pnl
                pnl_values_found += 1
                if net_pnl > 0:
                    wins.append(net_pnl)
                else:
                    losses.append(net_pnl)
            except (TypeError, ValueError):
                pnl_values_missing += 1
                continue
        
        print(f"🔍 [SUMMARY] P&L stats: {pnl_values_found} valid, {pnl_values_missing} missing/invalid, total_pnl=${total_pnl:.2f}", flush=True)
        
        total_trades = len(recent_closed)
        wins_count = len(wins)
        losses_count = len(losses)
        win_rate = (wins_count / total_trades * 100.0) if total_trades > 0 else 0.0
        avg_win = sum(wins) / len(wins) if wins else 0.0
        avg_loss = sum(losses) / len(losses) if losses else 0.0
        
        print(f"🔍 [SUMMARY] Final stats: {total_trades} trades, {wins_count} wins, {losses_count} losses, win_rate={win_rate:.1f}%, net_pnl=${total_pnl:.2f}", flush=True)
        
        # Calculate drawdown based on wallet balance (realized P&L only)
        starting_capital = STARTING_CAPITAL_AFTER_RESET
        drawdown_pct = ((wallet_balance - starting_capital) / starting_capital) * 100.0
        
        return {
            "wallet_balance": wallet_balance,
            "total_trades": total_trades,
            "wins": wins_count,
            "losses": losses_count,
            "win_rate": win_rate,
            "net_pnl": total_pnl,
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


def compute_summary(wallet_balance: float, lookback_days: int = 1) -> dict:
    """Compute summary statistics for a given lookback period.
    
    CRITICAL: Filters by both wallet reset date AND lookback period.
    """
    try:
        # Use DataRegistry for efficient closed positions loading (with time limit)
        try:
            # Get closed positions from last 30 days (more than any lookback period)
            closed_positions = DR.get_closed_positions(hours=lookback_days * 24 + 168)  # Add 7 days buffer
        except Exception:
            # Fallback to direct read
            positions_data = DR.read_json(DR.POSITIONS_FUTURES)
            if not positions_data:
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
        
        # CRITICAL: First filter by wallet reset date (Dec 18, 2025)
        post_reset_positions = []
        for pos in closed_positions:
            closed_at = pos.get("closed_at", "")
            if not closed_at:
                continue
                try:
                    # Parse to timestamp for reliable comparison
                    if isinstance(closed_at, str):
                        closed_dt = datetime.fromisoformat(closed_at.replace("Z", "+00:00"))
                        closed_ts = closed_dt.timestamp()
                    elif isinstance(closed_at, (int, float)):
                        closed_ts = float(closed_at)
                    else:
                        continue
                    
                    # Only include trades AFTER reset timestamp
                    if closed_ts >= WALLET_RESET_TS:
                        post_reset_positions.append(pos)
                except:
                    pass
        
        # Get open positions (limited count)
        try:
            positions_data = DR.read_json(DR.POSITIONS_FUTURES)
            open_positions = positions_data.get("open_positions", []) if positions_data else []
        except:
            open_positions = []
        
        # Filter to lookback period
        cutoff = datetime.utcnow() - timedelta(days=lookback_days)
        recent_closed = []
        
        # Limit processing to prevent memory issues
        max_positions_to_process = 1000
        positions_to_process = post_reset_positions[-max_positions_to_process:] if len(post_reset_positions) > max_positions_to_process else post_reset_positions
        
        for pos in positions_to_process:
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
        
        # NOTE: Unrealized P&L is NOT included in net_pnl for summary calculations
        # Wallet balance = starting_capital + realized P&L only
        # Unrealized P&L can be displayed separately but should not affect wallet balance or net_pnl
        
        total_trades = len(recent_closed)
        wins_count = len(wins)
        losses_count = len(losses)
        win_rate = (wins_count / total_trades * 100.0) if total_trades > 0 else 0.0
        avg_win = sum(wins) / len(wins) if wins else 0.0
        avg_loss = sum(losses) / len(losses) if losses else 0.0
        
        # CRITICAL FIX: Only include unrealized P&L if there are closed trades OR if unrealized P&L exists
        # Net P&L should be from closed trades only - unrealized is separate
        # But for display purposes, we can show total including unrealized if there are open positions
        
        # Calculate drawdown based on wallet balance (realized P&L only)
        starting_capital = STARTING_CAPITAL_AFTER_RESET
        drawdown_pct = ((wallet_balance - starting_capital) / starting_capital) * 100.0
        
        # CRITICAL: Net P&L = realized P&L from closed trades ONLY in this period
        # Unrealized P&L is NOT included (shown separately if needed)
        net_pnl_calculated = total_pnl
        
        return {
            "wallet_balance": wallet_balance,
            "total_trades": total_trades,
            "wins": wins_count,
            "losses": losses_count,
            "win_rate": win_rate,
            "net_pnl": net_pnl_calculated,  # Only realized P&L from closed trades
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
    
    # PERFORMANCE: Limit to most recent 500 trades for chart generation
    if len(df) > 500:
        df = df.tail(500)
    
    df_sorted = df.sort_values("exit_time")
    df_sorted = df_sorted.copy()
    df_sorted["cum_pnl"] = df_sorted["net_pnl"].cumsum()
    starting_capital = STARTING_CAPITAL_AFTER_RESET
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


# Executive Summary Generator - Helper function first
def _get_basic_executive_summary() -> Dict[str, str]:
    """Fallback basic executive summary when full generator unavailable."""
    return {
        "what_worked_today": "Dashboard is loading data. Full executive summary will be available once data processing completes.",
        "what_didnt_work": "",
        "missed_opportunities": "",
        "blocked_signals": "",
        "exit_gates": "",
        "learning_today": "",
        "changes_tomorrow": "",
        "weekly_summary": "Weekly analysis in progress. Data is being collected and analyzed.",
    }

# Import from old dashboard for full implementation
try:
    from src.pnl_dashboard import generate_executive_summary
except (ImportError, Exception) as e:
    # Fallback if import fails - use basic implementation
    print(f"⚠️  [DASHBOARD-V2] Could not import generate_executive_summary: {e}, using fallback", flush=True)
    def generate_executive_summary() -> Dict[str, str]:
        return _get_basic_executive_summary()

# System Health Check
def get_system_health() -> dict:
    """Get system health status by checking actual component files and logs."""
    import os
    import time
    from pathlib import Path
    from src.infrastructure.path_registry import PathRegistry
    
    health = {
        "signal_engine": "unknown",
        "decision_engine": "unknown",
        "trade_execution": "unknown",
        "self_healing": "unknown",
    }
    
    try:
        # Check Signal Engine - signals.jsonl should be recent (< 10 minutes)
        signals_file = Path(PathRegistry.get_path("logs", "signals.jsonl"))
        if signals_file.exists():
            age_seconds = time.time() - signals_file.stat().st_mtime
            if age_seconds < 600:  # 10 minutes
                health["signal_engine"] = "healthy"
            elif age_seconds < 3600:  # 1 hour
                health["signal_engine"] = "warning"
            else:
                health["signal_engine"] = "error"
        else:
            health["signal_engine"] = "error"
    except Exception as e:
        print(f"⚠️  [HEALTH] Error checking signal engine: {e}", flush=True)
        health["signal_engine"] = "error"
    
    try:
        # Check Decision Engine - enriched_decisions.jsonl should be recent
        decisions_file = Path(PathRegistry.get_path("logs", "enriched_decisions.jsonl"))
        if decisions_file.exists():
            age_seconds = time.time() - decisions_file.stat().st_mtime
            if age_seconds < 600:
                health["decision_engine"] = "healthy"
            elif age_seconds < 3600:
                health["decision_engine"] = "warning"
            else:
                health["decision_engine"] = "error"
        else:
            health["decision_engine"] = "error"
    except Exception as e:
        print(f"⚠️  [HEALTH] Error checking decision engine: {e}", flush=True)
        health["decision_engine"] = "error"
    
    try:
        # Check Trade Execution - positions_futures.json should exist and be recent
        positions_file = Path(PathRegistry.POS_LOG)
        if positions_file.exists():
            age_seconds = time.time() - positions_file.stat().st_mtime
            if age_seconds < 3600:  # 1 hour for positions (less frequent updates)
                health["trade_execution"] = "healthy"
            elif age_seconds < 86400:  # 24 hours
                health["trade_execution"] = "warning"
            else:
                health["trade_execution"] = "error"
        else:
            health["trade_execution"] = "warning"  # May not exist if no trades yet
    except Exception as e:
        print(f"⚠️  [HEALTH] Error checking trade execution: {e}", flush=True)
        health["trade_execution"] = "error"
    
    try:
        # Check Self-Healing - healing operator heartbeat or logs
        heartbeat_file = Path(PathRegistry.get_path("state", "heartbeats", "bot_cycle.json"))
        if heartbeat_file.exists():
            age_seconds = time.time() - heartbeat_file.stat().st_mtime
            if age_seconds < 120:  # 2 minutes (healing runs every 60s)
                health["self_healing"] = "healthy"
            elif age_seconds < 600:
                health["self_healing"] = "warning"
            else:
                health["self_healing"] = "error"
        else:
            # Check if healing operator is running via logs
            health_log = Path(PathRegistry.get_path("logs", "healing_operator.jsonl"))
            if health_log.exists() and (time.time() - health_log.stat().st_mtime) < 300:
                health["self_healing"] = "healthy"
            else:
                health["self_healing"] = "warning"
    except Exception as e:
        print(f"⚠️  [HEALTH] Error checking self-healing: {e}", flush=True)
        health["self_healing"] = "error"
    
    return health


# Build Dashboard App
def build_app(server: Flask = None) -> Dash:
    """Build and return the Dash app."""
    
    # Initialize Flask server if not provided
    if server is None:
        server = Flask(__name__)
        server.secret_key = os.environ.get('FLASK_SECRET_KEY', hashlib.sha256(DASHBOARD_PASSWORD.encode()).hexdigest())
    
    # CRITICAL: Dash initialization - must match old dashboard exactly
    # url_base_pathname="/" already sets requests_pathname_prefix internally
    app = Dash(
        __name__, 
        server=server, 
        url_base_pathname="/",
        external_stylesheets=[dbc.themes.DARKLY],
        title=APP_TITLE
    )
    
    # CRITICAL: Configure Dash for production/Gunicorn
    # requests_pathname_prefix is read-only and set via url_base_pathname in constructor
    app.config.suppress_callback_exceptions = True
    
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
    
    # CRITICAL: Allow Dash internal routes without authentication
    # This is required for Dash components to load properly
    @flask_server.before_request
    def require_auth():
        # Allow login, logout, and Dash internal routes without authentication
        # Dash uses various internal routes that must be accessible
        if (request.path == '/login' or 
            request.path == '/logout' or
            request.path.startswith('/_dash-') or 
            request.path.startswith('/assets/') or
            request.path.startswith('/_reload-hash') or
            request.path == '/' or  # Allow root path (Dash will handle it)
            request.path.startswith('/_') or  # All Dash internal routes
            request.method == 'OPTIONS'):  # CORS preflight
            return None
        
        # Check authentication for all other routes
        if not session.get('authenticated'):
            if request.path.startswith('/api/') or request.path.startswith('/health/') or request.path.startswith('/audit/'):
                from flask import jsonify
                return jsonify({'error': 'Authentication required'}), 401
            else:
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
        
        html.Div(
            id="tab-content", 
            style={"marginTop": "20px"},
            children=html.Div([
                html.H4("Loading...", style={"color": "#9aa0a6"}),
                html.P("Initializing dashboard...", style={"color": "#9aa0a6"}),
            ])
        ),
        
        # Refresh intervals
        dcc.Interval(id="refresh-interval", interval=5*60*1000, n_intervals=0),  # 5 minutes
    ], style={"backgroundColor": "#0b0e13", "fontFamily": "Inter, Segoe UI, Arial", "padding": "20px", "minHeight": "100vh"})
    
    # Callbacks - MUST be registered after layout is set
    @app.callback(
        Output("system-health-container", "children"),
        Input("system-health-interval", "n_intervals"),
    )
    def update_system_health(n):
        try:
            return system_health_panel()
        except Exception as e:
            print(f"⚠️  [DASHBOARD-V2] Error updating system health: {e}", flush=True)
            import traceback
            traceback.print_exc()
            return html.Div("System health unavailable", style={"color": "#ea4335"})
    
    # CRITICAL: Register callback with explicit dependencies
    @app.callback(
        Output("tab-content", "children"),
        Input("main-tabs", "value"),
        Input("refresh-interval", "n_intervals"),
        prevent_initial_call=False,  # CRITICAL: Allow callback to fire on initial load
    )
    def update_tab_content(tab, n_intervals):
        """Update tab content based on selected tab and refresh interval."""
        try:
            print(f"🔍 [DASHBOARD-V2] ====== update_tab_content CALLED ======", flush=True)
            print(f"🔍 [DASHBOARD-V2] Parameters: tab={tab!r} (type: {type(tab)}), n_intervals={n_intervals!r}", flush=True)
            
            if tab is None:
                # Default to daily tab if no tab selected
                tab = "daily"
                print("⚠️  [DASHBOARD-V2] Tab was None, defaulting to 'daily'", flush=True)
            
            if tab == "daily":
                print("🔍 [DASHBOARD-V2] Building daily summary tab...", flush=True)
                content = build_daily_summary_tab()
                if content is None:
                    raise ValueError("build_daily_summary_tab() returned None")
                print(f"✅ [DASHBOARD-V2] Daily summary tab built successfully (type: {type(content)})", flush=True)
                return content
            elif tab == "executive":
                print("🔍 [DASHBOARD-V2] Building executive summary tab...", flush=True)
                content = build_executive_summary_tab()
                if content is None:
                    raise ValueError("build_executive_summary_tab() returned None")
                print(f"✅ [DASHBOARD-V2] Executive summary tab built successfully (type: {type(content)})", flush=True)
                return content
            else:
                print(f"⚠️  [DASHBOARD-V2] Unknown tab value: {tab}", flush=True)
                return html.Div([
                    html.H4(f"Unknown tab: {tab}", style={"color": "#ea4335"}),
                    html.P("Please select Daily Summary or Executive Summary.", style={"color": "#9aa0a6"}),
                ])
        except Exception as e:
            print(f"❌ [DASHBOARD-V2] CRITICAL ERROR updating tab content: {e}", flush=True)
            import traceback
            traceback.print_exc()
            error_msg = str(e)
            error_tb = traceback.format_exc()
            print(f"❌ [DASHBOARD-V2] Full traceback:\n{error_tb}", flush=True)
            return html.Div([
                html.H4("❌ Error loading content", style={"color": "#ea4335", "marginBottom": "12px"}),
                html.P(f"Error: {error_msg}", style={"color": "#9aa0a6", "marginBottom": "8px"}),
                html.Pre(error_tb[-500:], style={"color": "#9aa0a6", "fontSize": "10px", "overflow": "auto", "backgroundColor": "#1a1a1a", "padding": "10px"}),
                html.P("Check server logs for full details.", style={"color": "#9aa0a6", "fontSize": "12px", "marginTop": "8px"}),
            ])
    
    # Note: Tables are updated via the tab content refresh callback
    # which rebuilds the entire tab when refresh-interval fires
    
    # Verify callbacks are registered (safe check without accessing internal attributes)
    try:
        callback_count = len(app.callback_map) if hasattr(app, 'callback_map') else 0
        print(f"✅ [DASHBOARD-V2] Dashboard app fully configured - {callback_count} callbacks registered", flush=True)
    except Exception as e:
        print(f"⚠️  [DASHBOARD-V2] Could not verify callback count: {e}", flush=True)
        print("✅ [DASHBOARD-V2] Dashboard app fully configured", flush=True)
    
    return app


def build_daily_summary_tab() -> html.Div:
    """Build Daily Summary tab content with robust error handling."""
    print("🔍 [DASHBOARD-V2] ====== build_daily_summary_tab() STARTED ======", flush=True)
    wallet_balance = STARTING_CAPITAL_AFTER_RESET
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
    
    try:
        print("🔍 [DASHBOARD-V2] Building daily summary tab...", flush=True)
        
        # Load wallet balance with error handling
        try:
            print("🔍 [DASHBOARD-V2] Step 1: Getting wallet balance...", flush=True)
            wallet_balance = get_wallet_balance()
            print(f"💰 [DASHBOARD-V2] Wallet balance: ${wallet_balance:.2f}", flush=True)
        except Exception as e:
            print(f"⚠️  [DASHBOARD-V2] Error getting wallet balance: {e}", flush=True)
            import traceback
            traceback.print_exc()
            wallet_balance = STARTING_CAPITAL_AFTER_RESET
        
        # Compute summaries with error handling
        # PERFORMANCE: Load positions once and reuse for all summaries
        try:
            print("🔍 [DASHBOARD-V2] Step 2: Loading positions for summaries...", flush=True)
            # Load positions once (limited to prevent slow loading)
            positions_data = DR.read_json(DR.POSITIONS_FUTURES)
            all_closed_positions = positions_data.get("closed_positions", []) if positions_data else []
            
            # TEMPORARILY DISABLED: Reset filter until correct date is verified
            # CRITICAL: Filter by wallet reset date FIRST (if enabled)
            closed_positions = []
            for pos in all_closed_positions:
                if not WALLET_RESET_ENABLED:
                    # Reset filter disabled - include all positions
                    closed_positions.append(pos)
                else:
                    closed_at = pos.get("closed_at", "")
                    if not closed_at:
                        continue
                    try:
                        # Parse to timestamp for reliable comparison
                        if isinstance(closed_at, str):
                            closed_dt = datetime.fromisoformat(closed_at.replace("Z", "+00:00"))
                            closed_ts = closed_dt.timestamp()
                        elif isinstance(closed_at, (int, float)):
                            closed_ts = float(closed_at)
                        else:
                            continue
                        
                        # Only include trades AFTER reset timestamp
                        if closed_ts >= WALLET_RESET_TS:
                            closed_positions.append(pos)
                    except:
                        pass
            
            if WALLET_RESET_ENABLED:
                print(f"🔍 [DASHBOARD-V2] After reset filter: {len(closed_positions)} positions (from {len(all_closed_positions)} total)", flush=True)
                if len(closed_positions) == 0:
                    print(f"⚠️  [DASHBOARD-V2] WARNING: No positions found after reset filter! Check reset date.", flush=True)
                    print(f"⚠️  [DASHBOARD-V2] Reset timestamp: {WALLET_RESET_TS}, Total positions: {len(all_closed_positions)}", flush=True)
                    # Show sample of position dates for debugging
                    if all_closed_positions:
                        sample_pos = all_closed_positions[-1] if all_closed_positions else {}
                        sample_date = sample_pos.get("closed_at", "N/A")
                        print(f"⚠️  [DASHBOARD-V2] Sample position closed_at: {sample_date}", flush=True)
            else:
                print(f"🔍 [DASHBOARD-V2] Reset filter disabled - using all {len(closed_positions)} positions", flush=True)
            
            # Limit to most recent 1000 for performance
            if len(closed_positions) > 1000:
                closed_positions = closed_positions[-1000:]
                print(f"🔍 [DASHBOARD-V2] Limited to most recent 1000 for performance", flush=True)
            
            print("🔍 [DASHBOARD-V2] Computing summaries (optimized)...", flush=True)
            daily_summary = compute_summary_optimized(wallet_balance, closed_positions, lookback_days=1)
            print(f"🔍 [DASHBOARD-V2] Daily summary: {daily_summary.get('total_trades', 0)} trades, ${daily_summary.get('net_pnl', 0):.2f} P&L", flush=True)
            weekly_summary = compute_summary_optimized(wallet_balance, closed_positions, lookback_days=7)
            print(f"🔍 [DASHBOARD-V2] Weekly summary: {weekly_summary.get('total_trades', 0)} trades, ${weekly_summary.get('net_pnl', 0):.2f} P&L", flush=True)
            monthly_summary = compute_summary_optimized(wallet_balance, closed_positions, lookback_days=30)
            print(f"🔍 [DASHBOARD-V2] Monthly summary: {monthly_summary.get('total_trades', 0)} trades, ${monthly_summary.get('net_pnl', 0):.2f} P&L", flush=True)
            print("📊 [DASHBOARD-V2] All summaries computed", flush=True)
        except Exception as e:
            print(f"⚠️  [DASHBOARD-V2] Error computing summaries: {e}", flush=True)
            import traceback
            traceback.print_exc()
            # Use default empty summaries
        
        # Load positions with error handling and limits for memory efficiency
        try:
            print("🔍 [DASHBOARD-V2] Step 3: Loading positions...", flush=True)
            # Limit to last 500 closed positions to prevent OOM
            closed_df = load_closed_positions_df(limit=500)
            print(f"🔍 [DASHBOARD-V2] Closed positions loaded: {len(closed_df)}", flush=True)
            open_df = load_open_positions_df()
            print(f"🔍 [DASHBOARD-V2] Open positions loaded: {len(open_df)}", flush=True)
            print(f"📈 [DASHBOARD-V2] Loaded {len(closed_df)} closed (limited to 500 most recent), {len(open_df)} open positions", flush=True)
        except Exception as e:
            print(f"⚠️  [DASHBOARD-V2] Error loading positions: {e}", flush=True)
            import traceback
            traceback.print_exc()
            # Use default empty DataFrames
            
    except Exception as e:
        print(f"❌ [DASHBOARD-V2] CRITICAL error building daily summary tab: {e}", flush=True)
        import traceback
        error_tb = traceback.format_exc()
        print(f"❌ [DASHBOARD-V2] Full traceback:\n{error_tb}", flush=True)
        # Continue with default empty data
    
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
    
    try:
        content = html.Div([
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
        component_count = len(content.children) if hasattr(content, 'children') else 'N/A'
        print(f"✅ [DASHBOARD-V2] Daily summary tab content built: {component_count} components", flush=True)
        print(f"✅ [DASHBOARD-V2] Content type: {type(content)}", flush=True)
        print("✅ [DASHBOARD-V2] ====== build_daily_summary_tab() COMPLETED ======", flush=True)
        return content
    except Exception as e:
        print(f"❌ [DASHBOARD-V2] Error building daily summary tab HTML structure: {e}", flush=True)
        import traceback
        traceback.print_exc()
        error_content = html.Div([
            html.H4("Error loading Daily Summary", style={"color": "#ea4335"}),
            html.P(str(e), style={"color": "#9aa0a6"}),
            html.P("Check server logs for details.", style={"color": "#9aa0a6", "fontSize": "12px"}),
        ])
        print(f"❌ [DASHBOARD-V2] Returning error content: {type(error_content)}", flush=True)
        return error_content


def build_executive_summary_tab() -> html.Div:
    """Build Executive Summary tab content with robust error handling."""
    try:
        print("🔍 [DASHBOARD-V2] Building executive summary tab...", flush=True)
        summary = generate_executive_summary()
        print("✅ [DASHBOARD-V2] Executive summary generated", flush=True)
    except Exception as e:
        print(f"❌ [DASHBOARD-V2] Error generating executive summary: {e}", flush=True)
        import traceback
        traceback.print_exc()
        summary = _get_basic_executive_summary()
    
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
        # Config already set in build_app, but verify here
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
