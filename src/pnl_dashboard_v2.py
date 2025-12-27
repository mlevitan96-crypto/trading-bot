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

⚠️ AI ASSISTANTS: CRITICAL - Before modifying this file:
- READ MEMORY_BANK.md section "CRITICAL: Disconnect Between Code and Reality"
- This dashboard has had multiple critical failures (December 2024 incident)
- Follow REQUIRED PROCESS in MEMORY_BANK.md for ALL date/data changes
- Test with actual data before claiming fixes
- User has explicitly stated failures "can't keep happening"

Key issues that occurred:
- Wrong year assumption (2025 vs 2024) filtered out ALL data
- Date parsing failures with timezone-aware strings
- P&L field name mismatches causing zeros
- Not testing with real data before claiming fixes

See MEMORY_BANK.md for complete documentation.
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
# Import generate_executive_summary - try dedicated module, fallback to inline stub
try:
    from src.executive_summary_generator import generate_executive_summary
except ImportError:
    # Fallback stub if module doesn't exist
    def generate_executive_summary() -> Dict[str, str]:
        return {
            "what_worked_today": "Executive summary generator not available",
            "what_didnt_work": "",
            "missed_opportunities": "",
            "blocked_signals": "",
            "exit_gates": "",
            "learning_today": "",
            "changes_tomorrow": "",
            "weekly_summary": ""
        }

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
                    return pd.DataFrame(columns=["symbol", "strategy", "trading_window", "entry_time", "exit_time", "entry_price", "exit_price", "size", "margin_collateral", "leverage", "hold_duration_h", "roi_pct", "net_pnl", "fees"])
                closed_positions = positions_data.get("closed_positions", [])
            except Exception as e2:
                print(f"⚠️  [DASHBOARD-V2] Fallback also failed: {e2}", flush=True)
                return pd.DataFrame(columns=["symbol", "strategy", "trading_window", "entry_time", "exit_time", "entry_price", "exit_price", "size", "hold_duration_h", "roi_pct", "net_pnl", "fees"])
        
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
            print(f"🔍 [DASHBOARD-V2] Reset filter disabled - using all {len(post_reset_positions)} positions (from {len(closed_positions)} total)", flush=True)
        
        # Further limit to last N positions for memory efficiency
        if len(post_reset_positions) > limit:
            post_reset_positions = post_reset_positions[-limit:]
            print(f"🔍 [DASHBOARD-V2] Limited to most recent {limit} positions", flush=True)
        
        closed_positions = post_reset_positions
        
        # DEBUG: Log sample of positions to verify data
        if len(closed_positions) > 0:
            sample = closed_positions[-1]
            print(f"🔍 [DASHBOARD-V2] Sample position: symbol={sample.get('symbol', 'N/A')}, closed_at={sample.get('closed_at', 'N/A')}, pnl={sample.get('pnl', sample.get('net_pnl', 0))}", flush=True)
        else:
            print(f"⚠️  [DASHBOARD-V2] WARNING: No closed positions after filtering! Check data file.", flush=True)
        
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
            
            # Ensure proper types for DataFrame (Dash DataTable requires specific types)
            rows.append({
                "symbol": str(symbol) if symbol else "N/A",
                "strategy": str(strategy) if strategy else "Unknown",
                "trading_window": str(pos.get("trading_window", "unknown")),
                "entry_time": str(entry_time) if entry_time else "",
                "exit_time": str(exit_time) if exit_time else "",
                "entry_price": float(entry_price) if entry_price else 0.0,
                "exit_price": float(exit_price) if exit_price else 0.0,
                "size": float(size) if size else 0.0,
                "margin_collateral": float(margin) if margin else 0.0,
                "leverage": int(leverage) if leverage else 1,
                "hold_duration_h": float(hold_duration_h) if hold_duration_h else 0.0,
                "roi_pct": float(leveraged_roi * 100) if leveraged_roi else 0.0,
                "net_pnl": float(net_pnl) if net_pnl is not None else 0.0,
                "fees": float(pos.get("funding_fees", 0.0) or 0.0),
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
        return pd.DataFrame(columns=["symbol", "strategy", "trading_window", "entry_time", "exit_time", "entry_price", "exit_price", "size", "margin_collateral", "leverage", "hold_duration_h", "roi_pct", "net_pnl", "fees"])


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
        
        # Now filter to lookback period (use timezone-aware datetime)
        from datetime import timezone
        cutoff = datetime.now(timezone.utc) - timedelta(days=lookback_days)
        cutoff_ts = cutoff.timestamp()
        recent_closed = []
        
        # Sort by closed_at timestamp (most recent first) for proper lookback filtering
        # This ensures we process the most recent trades first
        try:
            def get_timestamp(pos):
                closed_at = pos.get("closed_at", "")
                if not closed_at:
                    return 0.0
                try:
                    if isinstance(closed_at, str):
                        if "T" in closed_at:
                            closed_dt = datetime.fromisoformat(closed_at.replace("Z", "+00:00"))
                        else:
                            try:
                                closed_dt = datetime.strptime(closed_at, "%Y-%m-%d %H:%M:%S")
                            except:
                                return 0.0
                        return closed_dt.timestamp()
                    elif isinstance(closed_at, (int, float)):
                        return float(closed_at)
                except:
                    return 0.0
                return 0.0
            
            # Sort by timestamp descending (newest first)
            post_reset_positions = sorted(post_reset_positions, key=get_timestamp, reverse=True)
        except Exception as e:
            print(f"⚠️  [SUMMARY] Error sorting positions: {e}", flush=True)
        
        # Limit processing to prevent memory issues (after sorting, so we get most recent)
        max_positions_to_process = 3000  # Increased to capture more trades
        positions_to_process = post_reset_positions[:max_positions_to_process] if len(post_reset_positions) > max_positions_to_process else post_reset_positions
        
        print(f"🔍 [SUMMARY] Processing {len(positions_to_process)} positions for {lookback_days}-day lookback (cutoff: {cutoff}, cutoff_ts: {cutoff_ts})", flush=True)
        
        date_parse_errors = 0
        date_parse_success = 0
        for pos in positions_to_process:
            closed_at = pos.get("closed_at", "")
            if not closed_at:
                # Skip positions without closed_at
                continue
            try:
                # Parse to timestamp for reliable comparison
                if isinstance(closed_at, str):
                    # Handle timezone-aware and naive strings
                    if "T" in closed_at:
                        # Handle ISO format with timezone (e.g., "2025-12-24T10:29:04.402151-07:00")
                        try:
                            # Try parsing with timezone first
                            closed_dt = datetime.fromisoformat(closed_at.replace("Z", "+00:00"))
                        except ValueError:
                            # If that fails, try without microseconds
                            try:
                                closed_dt = datetime.fromisoformat(closed_at.split('.')[0].replace("Z", "+00:00"))
                            except:
                                # Last resort: try parsing as naive and assume UTC
                                closed_dt = datetime.strptime(closed_at.split('T')[0] + " " + closed_at.split('T')[1].split('.')[0], "%Y-%m-%d %H:%M:%S")
                    else:
                        # Try other formats
                        try:
                            closed_dt = datetime.strptime(closed_at, "%Y-%m-%d %H:%M:%S")
                        except:
                            closed_dt = datetime.fromisoformat(closed_at)
                    closed_ts = closed_dt.timestamp()
                elif isinstance(closed_at, (int, float)):
                    closed_ts = float(closed_at)
                else:
                    date_parse_errors += 1
                    continue
                
                # Compare timestamps
                date_parse_success += 1
                if closed_ts >= cutoff_ts:
                    recent_closed.append(pos)
            except Exception as e:
                date_parse_errors += 1
                if date_parse_errors <= 5:  # Only log first few errors
                    print(f"⚠️  [SUMMARY] Date parse error for closed_at='{closed_at}': {e}", flush=True)
                continue
        
        if date_parse_errors > 0:
            print(f"⚠️  [SUMMARY] {date_parse_errors} positions had date parse errors", flush=True)
        
        print(f"🔍 [SUMMARY] Date parsing: {date_parse_success} successful, {date_parse_errors} errors", flush=True)
        print(f"🔍 [SUMMARY] After lookback filter ({lookback_days} days): {len(recent_closed)} positions (from {len(positions_to_process)} processed, cutoff: {cutoff})", flush=True)
        
        # Calculate stats
        wins = []
        losses = []
        total_pnl = 0.0
        pnl_values_found = 0
        pnl_values_missing = 0
        
        for pos in recent_closed:
            # Try multiple field names for P&L (check all possible fields)
            net_pnl = (pos.get("pnl") or 
                      pos.get("net_pnl") or 
                      pos.get("realized_pnl") or 
                      pos.get("profit_usd") or
                      pos.get("profit") or
                      pos.get("total_pnl") or
                      pos.get("unrealized_pnl"))  # Last resort, though should be 0 for closed
            
            if net_pnl is None:
                pnl_values_missing += 1
                # DEBUG: Log first few missing P&L values
                if pnl_values_missing <= 3:
                    symbol = pos.get("symbol", "N/A")
                    closed_at = pos.get("closed_at", "N/A")
                    print(f"⚠️  [SUMMARY] Position missing P&L: symbol={symbol}, closed_at={closed_at}, keys={list(pos.keys())[:10]}", flush=True)
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
            except (TypeError, ValueError) as e:
                pnl_values_missing += 1
                if pnl_values_missing <= 3:
                    print(f"⚠️  [SUMMARY] P&L conversion error: {e}, value={net_pnl}, type={type(net_pnl)}", flush=True)
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
        from datetime import timezone
        cutoff = datetime.now(timezone.utc) - timedelta(days=lookback_days)
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

        # Import from dedicated executive summary module
        try:
            from src.executive_summary_generator import generate_executive_summary
        except ImportError:
            # Fallback stub
            def generate_executive_summary() -> Dict[str, str]:
                return {"error": "Executive summary generator not available"}
except (ImportError, Exception) as e:
    # Fallback if import fails - use basic implementation
    print(f"⚠️  [DASHBOARD-V2] Could not import generate_executive_summary: {e}, using fallback", flush=True)
    def generate_executive_summary() -> Dict[str, str]:
        return _get_basic_executive_summary()

# [FINAL ALPHA PHASE 7] Portfolio Health Metrics
def get_portfolio_health_metrics() -> dict:
    """
    Calculate Phase 7 Portfolio Health Metrics:
    - Portfolio Max Drawdown (24h)
    - System-Wide Sharpe Ratio
    - Active Concentration Risk (strategy overlap count)
    """
    try:
        from src.position_manager import get_open_futures_positions
        from datetime import datetime, timedelta
        import numpy as np
        
        STARTING_CAPITAL = STARTING_CAPITAL_AFTER_RESET
        
        # Calculate 24-hour Portfolio Max Drawdown
        closed_positions = DR.get_closed_positions(hours=24)
        max_drawdown_pct = 0.0
        
        if closed_positions:
            from datetime import timezone
            cutoff_time = datetime.now(timezone.utc) - timedelta(hours=24)
            total_pnl = 0.0
            
            # Simple approach: Calculate portfolio value now vs 24h ago
            for pos in closed_positions:
                pnl = float(pos.get("pnl", pos.get("net_pnl", pos.get("realized_pnl", 0))) or 0)
                total_pnl += pnl
            
            # For simplicity, use total P&L change over 24h as proxy for drawdown
            # More accurate would be peak-to-trough calculation, but this is a reasonable approximation
            portfolio_value_now = STARTING_CAPITAL + total_pnl
            # Estimate 24h ago value (conservative: assume it was higher if now is lower)
            # This is a simplified calculation - for precise MDD, need hourly snapshots
            if portfolio_value_now < STARTING_CAPITAL:
                max_drawdown_pct = ((STARTING_CAPITAL - portfolio_value_now) / STARTING_CAPITAL) * 100.0
            else:
                max_drawdown_pct = 0.0
        
        # Calculate System-Wide Sharpe Ratio
        sharpe_ratio = 0.0
        try:
            recent_trades = DR.get_closed_positions(hours=168)  # Last 7 days
            if len(recent_trades) >= 10:
                returns = []
                for pos in recent_trades:
                    pnl = float(pos.get("pnl", pos.get("net_pnl", pos.get("realized_pnl", 0))) or 0)
                    # Normalize by starting capital to get returns
                    returns.append(pnl / STARTING_CAPITAL)
                
                if len(returns) > 1:
                    mean_return = np.mean(returns)
                    std_return = np.std(returns)
                    sharpe_ratio = mean_return / std_return if std_return > 1e-9 else 0.0
        except Exception as e:
            print(f"⚠️  [PORTFOLIO-HEALTH] Sharpe calculation error: {e}", flush=True)
        
        # Calculate Active Concentration Risk (strategy overlap count)
        open_positions = get_open_futures_positions()
        strategy_overlap_count = 0
        strategy_symbol_map = {}  # (symbol, direction) -> list of strategies
        
        for pos in open_positions:
            symbol = pos.get("symbol", "")
            strategy = pos.get("strategy", "")
            direction = pos.get("direction", "")
            
            if symbol and strategy:
                key = (symbol, direction)
                if key not in strategy_symbol_map:
                    strategy_symbol_map[key] = []
                strategy_symbol_map[key].append(strategy)
        
        # Count overlaps (multiple strategies on same symbol/direction)
        for key, strategies in strategy_symbol_map.items():
            if len(strategies) > 1:
                strategy_overlap_count += len(strategies) - 1  # Count extra strategies
        
        # Check Kill Switch Status
        kill_switch_active = False
        try:
            from src.self_healing_learning_loop import get_learning_loop
            learning_loop = get_learning_loop()
            kill_switch_active = learning_loop.is_kill_switch_active()
        except:
            pass
        
        return {
            "max_drawdown_24h_pct": round(max_drawdown_pct, 2),
            "sharpe_ratio": round(sharpe_ratio, 2),
            "concentration_risk_overlaps": strategy_overlap_count,
            "kill_switch_active": kill_switch_active,
            "kill_switch_threshold_pct": 5.0,
            "sharpe_target": 1.5
        }
    except Exception as e:
        print(f"⚠️  [PORTFOLIO-HEALTH] Error calculating metrics: {e}", flush=True)
        import traceback
        traceback.print_exc()
        return {
            "max_drawdown_24h_pct": 0.0,
            "sharpe_ratio": 0.0,
            "concentration_risk_overlaps": 0,
            "kill_switch_active": False,
            "kill_switch_threshold_pct": 5.0,
            "sharpe_target": 1.5
        }


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
        # Check Self-Healing - check for recent healing activity in logs
        # Healing operator runs every 60 seconds, so check for activity in last 5 minutes
        try:
            from src.infrastructure.path_registry import resolve_path
            # Check bot_out.log for recent healing messages
            bot_log = resolve_path("logs/bot_out.log")
            if os.path.exists(bot_log):
                # Check last 200 lines for recent healing activity
                with open(bot_log, 'r') as f:
                    lines = f.readlines()
                    recent_lines = lines[-200:] if len(lines) > 200 else lines
                    # Look for healing activity in last 5 minutes (300 seconds)
                    current_time = time.time()
                    for line in reversed(recent_lines):
                        if "[HEALING]" in line or "[SELF-HEALING]" in line or "[SELF-HEAL]" in line:
                            # Try to extract timestamp if present, or use file mtime
                            # For simplicity, if we see recent healing messages, consider it healthy
                            health["self_healing"] = "healthy"
                            break
                    else:
                        # No recent healing messages - check heartbeat file as fallback
                        heartbeat_file = Path(PathRegistry.get_path("state", "heartbeats", "bot_cycle.json"))
                        if heartbeat_file.exists():
                            age_seconds = time.time() - heartbeat_file.stat().st_mtime
                            if age_seconds < 300:  # 5 minutes
                                health["self_healing"] = "healthy"
                            elif age_seconds < 600:
                                health["self_healing"] = "warning"
                            else:
                                health["self_healing"] = "error"
                        else:
                            health["self_healing"] = "warning"
            else:
                # No log file - check heartbeat as fallback
                try:
                    heartbeat_file = Path(PathRegistry.get_path("state", "heartbeats", "bot_cycle.json"))
                    if heartbeat_file.exists():
                        age_seconds = time.time() - heartbeat_file.stat().st_mtime
                        if age_seconds < 300:
                            health["self_healing"] = "healthy"
                        else:
                            health["self_healing"] = "warning"
                    else:
                        health["self_healing"] = "warning"
                except Exception as e:
                    print(f"⚠️  [HEALTH] Error checking heartbeat (no log): {e}", flush=True)
                    health["self_healing"] = "warning"
        except Exception as e:
            print(f"⚠️  [HEALTH] Error checking self-healing: {e}", flush=True)
            # If we can't check, default to warning (not error) since healing might still be working
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
        
        # Tabs: Daily Summary, Executive Summary, and 24/7 Trading
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
            dcc.Tab(
                label="⏰ 24/7 Trading",
                value="24_7",
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
    ], style={"backgroundColor": "#0b0e13", "fontFamily": "Inter, Segoe UI, Arial", "padding": "20px", "minHeight": "100vh", "width": "100%", "maxWidth": "100%", "margin": "0", "boxSizing": "border-box"})
    
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
            elif tab == "24_7":
                print("🔍 [DASHBOARD-V2] Building 24/7 trading tab...", flush=True)
                content = build_24_7_trading_tab()
                if content is None:
                    raise ValueError("build_24_7_trading_tab() returned None")
                print(f"✅ [DASHBOARD-V2] 24/7 trading tab built successfully (type: {type(content)})", flush=True)
                return content
            else:
                print(f"⚠️  [DASHBOARD-V2] Unknown tab value: {tab}", flush=True)
                return html.Div([
                    html.H4(f"Unknown tab: {tab}", style={"color": "#ea4335"}),
                    html.P("Please select Daily Summary, Executive Summary, or 24/7 Trading.", style={"color": "#9aa0a6"}),
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
            
            print(f"🔍 [DASHBOARD-V2] Loaded {len(closed_positions)} total closed positions", flush=True)
            
            print("🔍 [DASHBOARD-V2] Computing summaries (optimized)...", flush=True)
            # Don't limit positions here - let compute_summary_optimized handle the lookback period filtering
            daily_summary = compute_summary_optimized(wallet_balance, closed_positions, lookback_days=1)
            print(f"🔍 [DASHBOARD-V2] Daily summary: {daily_summary.get('total_trades', 0)} trades, ${daily_summary.get('net_pnl', 0):.2f} P&L", flush=True)
            weekly_summary = compute_summary_optimized(wallet_balance, closed_positions, lookback_days=7)
            print(f"🔍 [DASHBOARD-V2] Weekly summary: {weekly_summary.get('total_trades', 0)} trades, ${weekly_summary.get('net_pnl', 0):.2f} P&L", flush=True)
            monthly_summary = compute_summary_optimized(wallet_balance, closed_positions, lookback_days=30)
            print(f"🔍 [DASHBOARD-V2] Monthly summary: {monthly_summary.get('total_trades', 0)} trades, ${monthly_summary.get('net_pnl', 0):.2f} P&L", flush=True)
            print("📊 [DASHBOARD-V2] All summaries computed", flush=True)
            
            # Compute Golden Hour summary from GOLDEN_HOUR_ANALYSIS.json (all-time comprehensive data)
            # This uses the comprehensive analysis data, not just last 24h filtering
            golden_hour_summary = {
                "wallet_balance": wallet_balance,  # Required by summary_card
                "total_trades": 0,
                "wins": 0,
                "losses": 0,
                "win_rate": 0.0,
                "net_pnl": 0.0,
                "avg_pnl": 0.0,
                "avg_win": 0.0,
                "avg_loss": 0.0,
                "gross_profit": 0.0,
                "gross_loss": 0.0,
                "profit_factor": 0.0
            }
            
            try:
                # Load Golden Hour analysis data (all-time comprehensive stats)
                analysis_file = Path("GOLDEN_HOUR_ANALYSIS.json")
                if not analysis_file.exists():
                    # Try alternative location
                    analysis_file = Path("GOLDEN_HOUR_ANALYSIS_DROPLET.json")
                
                if analysis_file.exists():
                    with open(analysis_file, 'r') as f:
                        analysis_data = json.load(f)
                    
                    gh_data = analysis_data.get("golden_hour_closed", {})
                    if gh_data:
                        total_pnl = float(gh_data.get("total_pnl", 0))
                        wins = int(gh_data.get("wins", 0))
                        losses = int(gh_data.get("losses", 0))
                        count = int(gh_data.get("count", 0))
                        win_rate = float(gh_data.get("win_rate", 0))
                        profit_factor = float(gh_data.get("profit_factor", 0))
                        avg_pnl = float(gh_data.get("avg_pnl", 0))
                        
                        # Calculate gross profit/loss from P&L distribution
                        # We need to estimate these if not directly available
                        # Use average win/loss estimates based on win rate and avg P&L
                        if count > 0:
                            estimated_total_wins_pnl = avg_pnl * count * (win_rate / 100) if win_rate > 0 else 0
                            estimated_total_losses_pnl = avg_pnl * count * ((100 - win_rate) / 100) if win_rate < 100 else 0
                            
                            # Try to get from symbol stats if available
                            symbol_stats = analysis_data.get("symbol_stats", {})
                            gross_profit = 0.0
                            gross_loss = 0.0
                            for symbol_data in symbol_stats.values():
                                gross_profit += float(symbol_data.get("gross_profit", 0))
                                gross_loss += float(symbol_data.get("gross_loss", 0))
                            
                            # If no symbol stats, estimate from profit factor and total P&L
                            if gross_profit == 0 and gross_loss == 0 and profit_factor > 0:
                                # profit_factor = gross_profit / gross_loss
                                # total_pnl = gross_profit - gross_loss
                                # Solving: gross_loss = total_pnl / (profit_factor - 1)
                                if profit_factor != 1:
                                    gross_loss = abs(total_pnl / (profit_factor - 1)) if profit_factor > 1 else abs(total_pnl / (1 - profit_factor))
                                    gross_profit = total_pnl + gross_loss
                            
                            avg_win = gross_profit / wins if wins > 0 else 0.0
                            avg_loss = -(gross_loss / losses) if losses > 0 else 0.0
                            
                            golden_hour_summary = {
                                "wallet_balance": wallet_balance,  # Required by summary_card
                                "total_trades": count,
                                "wins": wins,
                                "losses": losses,
                                "win_rate": win_rate,
                                "net_pnl": total_pnl,
                                "avg_pnl": avg_pnl,
                                "avg_win": avg_win,
                                "avg_loss": avg_loss,
                                "gross_profit": gross_profit,
                                "gross_loss": gross_loss,
                                "profit_factor": profit_factor
                            }
                            print(f"🕘 [DASHBOARD-V2] Loaded Golden Hour ALL-TIME summary from analysis file: {count} trades, ${total_pnl:.2f} P&L, {win_rate:.1f}% WR (comprehensive accumulated data)", flush=True)
                            
                            # Also calculate 24h rolling window for reference (will update when next Golden Hour trades occur)
                            cutoff_24h_rolling = datetime.now(timezone.utc) - timedelta(hours=24)
                            cutoff_24h_rolling_ts = cutoff_24h_rolling.timestamp()
                            gh_24h_count = 0
                            gh_24h_pnl = 0.0
                            for pos in closed_positions:
                                closed_at = pos.get("closed_at", "")
                                if closed_at:
                                    try:
                                        if isinstance(closed_at, str) and "T" in closed_at:
                                            dt = datetime.fromisoformat(closed_at.replace("Z", "+00:00"))
                                            ts = dt.timestamp()
                                            if ts >= cutoff_24h_rolling_ts:
                                                hour = dt.hour
                                                if 9 <= hour < 16:  # Golden Hour: 09:00-16:00 UTC
                                                    gh_24h_count += 1
                                                    pnl_val = pos.get("net_pnl", pos.get("pnl", 0))
                                                    pnl_val = float(pnl_val) if pnl_val is not None else 0.0
                                                    gh_24h_pnl += pnl_val
                                    except:
                                        pass
                            print(f"🕘 [DASHBOARD-V2] 24h rolling window: {gh_24h_count} trades, ${gh_24h_pnl:.2f} P&L (will update automatically when next Golden Hour trades occur)", flush=True)
                        else:
                            print(f"⚠️  [DASHBOARD-V2] Golden Hour analysis data has 0 trades", flush=True)
                    else:
                        print(f"⚠️  [DASHBOARD-V2] No golden_hour_closed data in analysis file", flush=True)
                else:
                    print(f"⚠️  [DASHBOARD-V2] Golden Hour analysis file not found, using fallback filtering", flush=True)
                    # Fallback to filtering from positions (last 24h only)
                    cutoff_24h = datetime.now(timezone.utc) - timedelta(hours=24)
                    cutoff_24h_ts = cutoff_24h.timestamp()
                    
                    golden_hour_positions = []
                    for pos in closed_positions:
                        closed_at = pos.get("closed_at", "")
                        if not closed_at:
                            continue
                        try:
                            if isinstance(closed_at, str):
                                if "T" in closed_at:
                                    dt = datetime.fromisoformat(closed_at.replace("Z", "+00:00"))
                                else:
                                    try:
                                        dt = datetime.strptime(closed_at, "%Y-%m-%d %H:%M:%S")
                                    except:
                                        dt = None
                            else:
                                dt = None
                            
                            if dt:
                                closed_ts = dt.timestamp()
                                if closed_ts >= cutoff_24h_ts:
                                    hour = dt.hour
                                    if 9 <= hour < 16:
                                        golden_hour_positions.append(pos)
                        except:
                            continue
                    
                    # Calculate from filtered positions
                    pnls = []
                    for pos in golden_hour_positions:
                        pnl = pos.get("net_pnl", pos.get("pnl", pos.get("realized_pnl", 0)))
                        try:
                            pnls.append(float(pnl) if pnl is not None else 0.0)
                        except:
                            pnls.append(0.0)
                    
                    if pnls:
                        wins = sum(1 for pnl in pnls if pnl > 0)
                        losses = len(pnls) - wins
                        total_pnl = sum(pnls)
                        gross_profit = sum(pnl for pnl in pnls if pnl > 0)
                        gross_loss = abs(sum(pnl for pnl in pnls if pnl < 0))
                        profit_factor = gross_profit / gross_loss if gross_loss > 0 else (gross_profit if gross_profit > 0 else 0.0)
                        win_rate = (wins / len(pnls) * 100) if pnls else 0.0
                        avg_pnl = total_pnl / len(pnls) if pnls else 0.0
                        avg_win = gross_profit / wins if wins > 0 else 0.0
                        avg_loss = -(gross_loss / losses) if losses > 0 else 0.0
                        
                        golden_hour_summary = {
                            "wallet_balance": wallet_balance,  # Required by summary_card
                            "total_trades": len(golden_hour_positions),
                            "wins": wins,
                            "losses": losses,
                            "win_rate": win_rate,
                            "net_pnl": total_pnl,
                            "avg_pnl": avg_pnl,
                            "avg_win": avg_win,
                            "avg_loss": avg_loss,
                            "gross_profit": gross_profit,
                            "gross_loss": gross_loss,
                            "profit_factor": profit_factor
                        }
            except Exception as e:
                print(f"⚠️  [DASHBOARD-V2] Error loading Golden Hour analysis: {e}", flush=True)
                import traceback
                traceback.print_exc()
        except Exception as e:
            print(f"⚠️  [DASHBOARD-V2] Error computing summaries: {e}", flush=True)
            import traceback
            traceback.print_exc()
            # Use default empty summaries
            golden_hour_summary = empty_summary
        
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
    
    # [FINAL ALPHA PHASE 7] Get Portfolio Health Metrics
    portfolio_health = get_portfolio_health_metrics()
    
    # [FINAL ALPHA PHASE 7] Portfolio Health Card
    def portfolio_health_card(health: dict) -> dbc.Card:
        max_dd = health.get("max_drawdown_24h_pct", 0.0)
        sharpe = health.get("sharpe_ratio", 0.0)
        overlaps = health.get("concentration_risk_overlaps", 0)
        kill_switch = health.get("kill_switch_active", False)
        
        dd_color = "#34a853" if max_dd < 5.0 else "#ea4335"
        sharpe_color = "#34a853" if sharpe >= 1.5 else "#ea4335"
        overlap_color = "#34a853" if overlaps == 0 else "#ea4335"
        
        return dbc.Card([
            dbc.CardHeader(html.H4("🏥 Portfolio Health (Phase 7)", style={"color": "#fff", "margin": 0})),
            dbc.CardBody([
                dbc.Row([
                    dbc.Col([
                        html.Div(f"{max_dd:.2f}%", style={"fontSize": "24px", "fontWeight": "bold", "color": dd_color}),
                        html.Div("Max Drawdown (24h)", style={"fontSize": "12px", "color": "#9aa0a6"}),
                        html.Div(f"Threshold: {health.get('kill_switch_threshold_pct', 5.0)}%", style={"fontSize": "10px", "color": "#9aa0a6"}),
                    ]),
                    dbc.Col([
                        html.Div(f"{sharpe:.2f}", style={"fontSize": "24px", "fontWeight": "bold", "color": sharpe_color}),
                        html.Div("Sharpe Ratio", style={"fontSize": "12px", "color": "#9aa0a6"}),
                        html.Div(f"Target: ≥ {health.get('sharpe_target', 1.5)}", style={"fontSize": "10px", "color": "#9aa0a6"}),
                    ]),
                    dbc.Col([
                        html.Div(f"{overlaps}", style={"fontSize": "24px", "fontWeight": "bold", "color": overlap_color}),
                        html.Div("Strategy Overlaps", style={"fontSize": "12px", "color": "#9aa0a6"}),
                        html.Div("Concentration Risk", style={"fontSize": "10px", "color": "#9aa0a6"}),
                    ]),
                    dbc.Col([
                        html.Div("🚨 ACTIVE" if kill_switch else "✅ INACTIVE", 
                               style={"fontSize": "20px", "fontWeight": "bold", 
                                     "color": "#ea4335" if kill_switch else "#34a853"}),
                        html.Div("Kill Switch", style={"fontSize": "12px", "color": "#9aa0a6"}),
                        html.Div("Entry Blocker", style={"fontSize": "10px", "color": "#9aa0a6"}),
                    ]),
                ]),
            ]),
        ], style={"backgroundColor": "#0f1217", "border": "1px solid #2d3139", "marginBottom": "20px"})
    
    def _build_autonomous_brain_cards() -> List[dbc.Card]:
        """Build cards for autonomous brain system metrics."""
        cards = []
        
        try:
            # Regime Health Card
            from src.regime_classifier import get_regime_classifier
            regime_classifier = get_regime_classifier()
            
            # Get regime for primary symbol (BTCUSDT or first available)
            primary_symbol = "BTCUSDT"
            regime_info = regime_classifier.get_regime(primary_symbol)
            hurst_value = regime_info.get('hurst_value', 0.5)
            composite_regime = regime_info.get('composite_regime', 'NEUTRAL')
            confidence = regime_info.get('confidence', 0.0)
            
            # Determine regime color
            if 'TREND' in composite_regime:
                regime_color = '#00ff88'  # Green
            elif 'RANGE' in composite_regime:
                regime_color = '#ffd700'  # Gold
            else:
                regime_color = '#888'  # Gray
            
            regime_card = dbc.Card([
                dbc.CardBody([
                    html.H5("🧭 Market Regime Health", className="card-title"),
                    html.Div([
                        html.Div([
                            html.Span("Hurst Exponent: ", style={"color": "#888"}),
                            html.Span(f"{hurst_value:.3f}", style={"color": "#00ff88", "font-weight": "bold"})
                        ], style={"margin-bottom": "10px"}),
                        html.Div([
                            html.Span("Regime: ", style={"color": "#888"}),
                            html.Span(composite_regime, style={"color": regime_color, "font-weight": "bold"})
                        ], style={"margin-bottom": "10px"}),
                        html.Div([
                            html.Span("Confidence: ", style={"color": "#888"}),
                            html.Span(f"{confidence*100:.1f}%", style={"color": "#888"})
                        ])
                    ])
                ])
            ], style={"margin-bottom": "20px"})
            cards.append(regime_card)
            
            # Shadow Portfolio Opportunity Cost Card
            from src.shadow_execution_engine import compare_shadow_vs_live_performance
            comparison = compare_shadow_vs_live_performance(days=7)
            
            opportunity_cost_pct = comparison.get('opportunity_cost_pct', 0.0)
            shadow_outperforming = comparison.get('shadow_outperforming', False)
            should_optimize = comparison.get('should_optimize_guards', False)
            
            cost_color = '#ff4444' if shadow_outperforming and should_optimize else '#00ff88' if not shadow_outperforming else '#ffd700'
            cost_icon = '🚨' if should_optimize else '✅' if not shadow_outperforming else '⚠️'
            
            shadow_card = dbc.Card([
                dbc.CardBody([
                    html.H5(f"{cost_icon} Shadow Portfolio Analysis", className="card-title"),
                    html.Div([
                        html.Div([
                            html.Span("Opportunity Cost: ", style={"color": "#888"}),
                            html.Span(f"{opportunity_cost_pct:+.1f}%", style={"color": cost_color, "font-weight": "bold"})
                        ], style={"margin-bottom": "10px"}),
                        html.Div([
                            html.Span("Shadow Trades: ", style={"color": "#888"}),
                            html.Span(f"{comparison.get('shadow', {}).get('trades', 0)}", style={"color": "#00ff88"})
                        ], style={"margin-bottom": "10px"}),
                        html.Div([
                            html.Span("Live Trades: ", style={"color": "#888"}),
                            html.Span(f"{comparison.get('live', {}).get('trades', 0)}", style={"color": "#00ff88"})
                        ]),
                        html.Div([
                            html.Span("Shadow P&L: ", style={"color": "#888"}),
                            html.Span(f"${comparison.get('shadow', {}).get('pnl_usd', 0):.2f}", 
                                     style={"color": "#00ff88" if comparison.get('shadow', {}).get('pnl_usd', 0) >= 0 else "#ff4444"})
                        ], style={"margin-top": "10px"}) if should_optimize else None
                    ])
                ])
            ], style={"margin-bottom": "20px"})
            cards.append(shadow_card)
            
            # Signal Drift Status Card
            from src.feature_drift_detector import get_drift_monitor
            drift_monitor = get_drift_monitor()
            quarantine_state = drift_monitor.quarantine_state
            quarantined_count = len(quarantine_state)
            
            drift_color = '#ff4444' if quarantined_count > 0 else '#00ff88'
            drift_icon = '⚠️' if quarantined_count > 0 else '✅'
            
            quarantined_list = list(quarantine_state.keys())[:5]  # Show first 5
            quarantined_text = ', '.join(quarantined_list) if quarantined_list else 'None'
            if len(quarantine_state) > 5:
                quarantined_text += f" (+{len(quarantine_state) - 5} more)"
            
            drift_card = dbc.Card([
                dbc.CardBody([
                    html.H5(f"{drift_icon} Signal Drift Status", className="card-title"),
                    html.Div([
                        html.Div([
                            html.Span("Quarantined Signals: ", style={"color": "#888"}),
                            html.Span(f"{quarantined_count}", style={"color": drift_color, "font-weight": "bold"})
                        ], style={"margin-bottom": "10px"}),
                        html.Div([
                            html.Span("Signals: ", style={"color": "#888", "font-size": "0.9em"}),
                            html.Span(quarantined_text, style={"color": drift_color, "font-size": "0.9em"})
                        ]) if quarantined_count > 0 else html.Div([
                            html.Span("All signals healthy", style={"color": "#00ff88", "font-size": "0.9em"})
                        ])
                    ])
                ])
            ], style={"margin-bottom": "20px"})
            cards.append(drift_card)
            
        except Exception as e:
            # Non-blocking - if autonomous brain components aren't available, skip
            print(f"⚠️ [DASHBOARD] Autonomous brain cards error: {e}")
            pass
        
        return cards
    
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
            # [FINAL ALPHA PHASE 7] Portfolio Health Card
            portfolio_health_card(portfolio_health),
            
            # Golden Hour Summary Card (All-Time Comprehensive Data from GOLDEN_HOUR_ANALYSIS.json)
            summary_card(golden_hour_summary, "🕘 Golden Hour Trading (09:00-16:00 UTC, All-Time Analysis)"),
            
            # Summary Cards (Daily, Weekly, Monthly)
            summary_card(daily_summary, "📅 Daily Summary (Last 24 Hours - All Trades)"),
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


def build_24_7_trading_tab() -> html.Div:
    """Build 24/7 Trading tab content with Golden Hour vs 24/7 comparison."""
    print("🔍 [DASHBOARD-V2] Building 24/7 trading tab...", flush=True)
    try:
        from src.data_registry import DataRegistry as DR
        from datetime import datetime, timedelta, timezone
        import plotly.graph_objects as go
        
        closed_positions = DR.get_closed_positions(hours=None)  # Get all closed positions
        
        if not closed_positions:
            return html.Div([
                dbc.Card([
                    dbc.CardHeader(html.H3("⏰ Golden Hour vs 24/7 Trading Comparison", style={"color": "#fff", "margin": 0})),
                    dbc.CardBody([
                        html.P("No closed trades found. Waiting for trading data...", style={"color": "#9aa0a6"}),
                    ]),
                ], style={"backgroundColor": "#0f1217", "border": "1px solid #2d3139"}),
            ])
        
        # Filter trades by timestamp (09:00-16:00 UTC = Golden Hour) for ALL trades
        # This ensures we capture all trades correctly, not just those with trading_window field set
        cutoff_24h = datetime.now(timezone.utc) - timedelta(hours=24)
        cutoff_24h_ts = cutoff_24h.timestamp()
        
        golden_hour_trades = []
        trades_24_7 = []
        unknown_trades = []
        
        for t in closed_positions:
            closed_at = t.get("closed_at", "")
            if not closed_at:
                unknown_trades.append(t)
                continue
            
            try:
                # Parse timestamp
                if isinstance(closed_at, str):
                    if "T" in closed_at:
                        dt = datetime.fromisoformat(closed_at.replace("Z", "+00:00"))
                    else:
                        try:
                            dt = datetime.strptime(closed_at, "%Y-%m-%d %H:%M:%S")
                        except:
                            dt = None
                else:
                    dt = None
                
                if dt:
                    # Check if in last 24 hours
                    closed_ts = dt.timestamp()
                    if closed_ts >= cutoff_24h_ts:
                        # Classify by hour (09:00-16:00 UTC = Golden Hour)
                        hour = dt.hour
                        if 9 <= hour < 16:
                            golden_hour_trades.append(t)
                        else:
                            trades_24_7.append(t)
                    else:
                        # Older than 24h - classify by trading_window if available, otherwise by timestamp
                        tw = t.get("trading_window")
                        if tw == "golden_hour":
                            golden_hour_trades.append(t)
                        elif tw == "24_7":
                            trades_24_7.append(t)
                        else:
                            # Fallback to timestamp classification for historical trades
                            if 9 <= hour < 16:
                                golden_hour_trades.append(t)
                            else:
                                trades_24_7.append(t)
                else:
                    # Can't parse timestamp - use trading_window if available
                    tw = t.get("trading_window")
                    if tw == "golden_hour":
                        golden_hour_trades.append(t)
                    elif tw == "24_7":
                        trades_24_7.append(t)
                    else:
                        unknown_trades.append(t)
            except Exception as e:
                # Error parsing - use trading_window if available
                tw = t.get("trading_window")
                if tw == "golden_hour":
                    golden_hour_trades.append(t)
                elif tw == "24_7":
                    trades_24_7.append(t)
                else:
                    unknown_trades.append(t)
        
        # Calculate metrics for each group
        def calculate_metrics(trades):
            if not trades:
                return {
                    "count": 0, "wins": 0, "losses": 0, "win_rate": 0.0,
                    "total_pnl": 0.0, "avg_pnl": 0.0, "profit_factor": 0.0,
                    "gross_profit": 0.0, "gross_loss": 0.0, "max_win": 0.0, "max_loss": 0.0
                }
            
            pnls = [float(t.get("net_pnl", t.get("pnl", t.get("realized_pnl", 0))) or 0) for t in trades]
            wins = sum(1 for pnl in pnls if pnl > 0)
            losses = len(trades) - wins
            total_pnl = sum(pnls)
            gross_profit = sum(pnl for pnl in pnls if pnl > 0)
            gross_loss = abs(sum(pnl for pnl in pnls if pnl < 0))
            profit_factor = gross_profit / gross_loss if gross_loss > 0 else (gross_profit if gross_profit > 0 else 0.0)
            max_win = max(pnls) if pnls else 0.0
            max_loss = min(pnls) if pnls else 0.0
            
            return {
                "count": len(trades),
                "wins": wins,
                "losses": losses,
                "win_rate": (wins / len(trades) * 100) if trades else 0.0,
                "total_pnl": total_pnl,
                "avg_pnl": total_pnl / len(trades) if trades else 0.0,
                "profit_factor": profit_factor,
                "gross_profit": gross_profit,
                "gross_loss": gross_loss,
                "max_win": max_win,
                "max_loss": max_loss
            }
        
        gh_metrics = calculate_metrics(golden_hour_trades)
        all_24_7_metrics = calculate_metrics(trades_24_7)
        
        # Helper function for summary cards (local to this function)
        def summary_card_24_7(summary: dict, label: str) -> dbc.Card:
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
        
        # Get wallet balance and filter to last 24 hours for summary cards
        wallet_balance_24_7 = 10000.0  # Default
        try:
            wallet_snapshots = DR.read_json(DR.WALLET_SNAPSHOTS)
            if wallet_snapshots and wallet_snapshots.get("snapshots"):
                latest_snapshot = wallet_snapshots["snapshots"][-1] if wallet_snapshots["snapshots"] else {}
                wallet_balance_24_7 = float(latest_snapshot.get("balance", 10000.0))
        except:
            pass
        
        # Filter to last 24 hours only for summary cards
        # IMPORTANT: Golden Hour = ONLY trades that closed during 09:00-16:00 UTC in last 24h
        # IMPORTANT: 24/7 = ALL trades in last 24h (including Golden Hour trades)
        gh_24h_trades = []
        all_trades_24h = []  # ALL trades in last 24h (for 24/7 section)
        
        for t in closed_positions:
            closed_at = t.get("closed_at", "")
            if not closed_at:
                continue
            try:
                if isinstance(closed_at, str):
                    if "T" in closed_at:
                        dt = datetime.fromisoformat(closed_at.replace("Z", "+00:00"))
                    else:
                        try:
                            dt = datetime.strptime(closed_at, "%Y-%m-%d %H:%M:%S")
                        except:
                            dt = None
                else:
                    dt = None
                
                if dt:
                    closed_ts = dt.timestamp()
                    if closed_ts >= cutoff_24h_ts:
                        # ALL trades in last 24h go to 24/7 section
                        all_trades_24h.append(t)
                        
                        # ONLY trades during Golden Hour (09:00-16:00 UTC) go to Golden Hour section
                        hour = dt.hour
                        if 9 <= hour < 16:  # Golden Hour: 09:00-16:00 UTC
                            gh_24h_trades.append(t)
            except Exception as e:
                # Skip trades with parsing errors
                pass
        
        # Calculate summaries for last 24h
        def calc_summary_24h(trades_list, wallet_bal):
            if not trades_list:
                return {
                    "wallet_balance": wallet_bal,
                    "total_trades": 0, "wins": 0, "losses": 0, "win_rate": 0.0,
                    "net_pnl": 0.0, "avg_win": 0.0, "avg_loss": 0.0
                }
            
            pnls = []
            for t in trades_list:
                pnl = t.get("net_pnl", t.get("pnl", t.get("realized_pnl", 0)))
                try:
                    pnls.append(float(pnl) if pnl is not None else 0.0)
                except:
                    pnls.append(0.0)
            
            wins = [p for p in pnls if p > 0]
            losses = [p for p in pnls if p < 0]
            total_pnl = sum(pnls)
            avg_win = sum(wins) / len(wins) if wins else 0.0
            avg_loss = sum(losses) / len(losses) if losses else 0.0
            win_rate = (len(wins) / len(pnls) * 100.0) if pnls else 0.0
            
            return {
                "wallet_balance": wallet_bal,
                "total_trades": len(trades_list),
                "wins": len(wins),
                "losses": len(losses),
                "win_rate": win_rate,
                "net_pnl": total_pnl,
                "avg_win": avg_win,
                "avg_loss": avg_loss
            }
        
        gh_summary_24h = calc_summary_24h(gh_24h_trades, wallet_balance_24_7)
        # 24/7 section shows ALL trades in last 24h (including Golden Hour trades)
        all_24_7_summary_24h = calc_summary_24h(all_trades_24h, wallet_balance_24_7)
        
        # Debug logging
        print(f"🔍 [DASHBOARD-V2] 24/7 tab filtering: Total last 24h={len(all_trades_24h)}, Golden Hour={len(gh_24h_trades)}, 24/7 only={len(all_trades_24h) - len(gh_24h_trades)}", flush=True)
        
        # Calculate differences
        pnl_diff_dollars = gh_metrics["total_pnl"] - all_24_7_metrics["total_pnl"]
        pnl_total_combined = abs(gh_metrics["total_pnl"]) + abs(all_24_7_metrics["total_pnl"])
        pnl_diff_percent = (pnl_diff_dollars / pnl_total_combined * 100) if pnl_total_combined > 0 else 0.0
        wr_diff = gh_metrics["win_rate"] - all_24_7_metrics["win_rate"]
        pf_diff = gh_metrics["profit_factor"] - all_24_7_metrics["profit_factor"]
        
        # Create comparison chart
        fig_bar = go.Figure()
        fig_bar.add_trace(go.Bar(
            name='Golden Hour',
            x=['Total P&L', 'Avg P&L', 'Win Rate', 'Profit Factor'],
            y=[gh_metrics['total_pnl'], gh_metrics['avg_pnl'], 
               gh_metrics['win_rate'], gh_metrics['profit_factor']],
            marker_color='#FFA500'
        ))
        fig_bar.add_trace(go.Bar(
            name='24/7 Trading',
            x=['Total P&L', 'Avg P&L', 'Win Rate', 'Profit Factor'],
            y=[all_24_7_metrics['total_pnl'], all_24_7_metrics['avg_pnl'],
               all_24_7_metrics['win_rate'], all_24_7_metrics['profit_factor']],
            marker_color='#00D4FF'
        ))
        fig_bar.update_layout(
            title='Performance Metrics Comparison',
            barmode='group',
            template='plotly_dark',
            height=400,
            plot_bgcolor="#0f1217",
            paper_bgcolor="#0f1217",
            font={"color": "#e8eaed"}
        )
        
        # Load open positions for tables
        open_positions = []
        try:
            positions_data = DR.read_json(DR.POSITIONS_FUTURES)
            open_positions = positions_data.get("open_positions", []) if positions_data else []
        except Exception as e:
            print(f"⚠️  [DASHBOARD-V2] Error loading open positions for 24/7 tab: {e}", flush=True)
        
        # Create DataFrames for open and closed positions tables
        try:
            open_df_24_7 = load_open_positions_df()
            print(f"🔍 [DASHBOARD-V2] 24/7 tab: Loaded {len(open_df_24_7)} open positions", flush=True)
        except Exception as e:
            print(f"⚠️  [DASHBOARD-V2] Error loading open positions DF: {e}", flush=True)
            import traceback
            traceback.print_exc()
            open_df_24_7 = pd.DataFrame()
        
        try:
            closed_df_24_7 = load_closed_positions_df(limit=500)
            print(f"🔍 [DASHBOARD-V2] 24/7 tab: Loaded {len(closed_df_24_7)} closed positions", flush=True)
            if not closed_df_24_7.empty:
                print(f"   Columns: {list(closed_df_24_7.columns)}", flush=True)
                print(f"   Sample row keys: {list(closed_df_24_7.iloc[0].to_dict().keys()) if len(closed_df_24_7) > 0 else 'empty'}", flush=True)
        except Exception as e:
            print(f"⚠️  [DASHBOARD-V2] Error loading closed positions DF: {e}", flush=True)
            import traceback
            traceback.print_exc()
            closed_df_24_7 = pd.DataFrame()
        
        # Filter closed positions by trading_window for display
        # Note: We show ALL positions in tables, but metrics are filtered by trading_window
        closed_df_filtered = closed_df_24_7.copy() if not closed_df_24_7.empty else pd.DataFrame()  # Show all closed positions in table
        
        return html.Div([
            dbc.Card([
                dbc.CardHeader(html.H3("⏰ Golden Hour vs 24/7 Trading Comparison", style={"color": "#fff", "margin": 0})),
                dbc.CardBody([
                    html.P(f"Total Trades: {len(closed_positions)} | Golden Hour: {len(golden_hour_trades)} | 24/7: {len(trades_24_7)} | Unknown: {len(unknown_trades)}", 
                           style={"color": "#9aa0a6", "marginBottom": "20px"}),
                    
                    dbc.Row([
                        dbc.Col([
                            html.H4("🕘 Golden Hour (09:00-16:00 UTC)", style={"color": "#FFA500", "marginTop": "10px"}),
                            html.Div([
                                html.P(f"Total Trades: {gh_metrics['count']}", style={"color": "#e8eaed"}),
                                html.P(f"Win Rate: {gh_metrics['win_rate']:.1f}%", style={"color": "#e8eaed"}),
                                html.P(f"Total P&L: ${gh_metrics['total_pnl']:,.2f}", 
                                      style={"color": "#34a853" if gh_metrics['total_pnl'] >= 0 else "#ea4335"}),
                                html.P(f"Avg P&L: ${gh_metrics['avg_pnl']:,.2f}", style={"color": "#e8eaed"}),
                                html.P(f"Profit Factor: {gh_metrics['profit_factor']:.2f}", style={"color": "#e8eaed"}),
                                html.P(f"Gross Profit: ${gh_metrics['gross_profit']:,.2f}", style={"color": "#34a853"}),
                                html.P(f"Gross Loss: ${gh_metrics['gross_loss']:,.2f}", style={"color": "#ea4335"}),
                            ]),
                        ], width=4),
                        dbc.Col([
                            html.H4("🌐 24/7 Trading", style={"color": "#00D4FF", "marginTop": "10px"}),
                            html.Div([
                                html.P(f"Total Trades: {all_24_7_metrics['count']}", style={"color": "#e8eaed"}),
                                html.P(f"Win Rate: {all_24_7_metrics['win_rate']:.1f}%", style={"color": "#e8eaed"}),
                                html.P(f"Total P&L: ${all_24_7_metrics['total_pnl']:,.2f}",
                                      style={"color": "#34a853" if all_24_7_metrics['total_pnl'] >= 0 else "#ea4335"}),
                                html.P(f"Avg P&L: ${all_24_7_metrics['avg_pnl']:,.2f}", style={"color": "#e8eaed"}),
                                html.P(f"Profit Factor: {all_24_7_metrics['profit_factor']:.2f}", style={"color": "#e8eaed"}),
                                html.P(f"Gross Profit: ${all_24_7_metrics['gross_profit']:,.2f}", style={"color": "#34a853"}),
                                html.P(f"Gross Loss: ${all_24_7_metrics['gross_loss']:,.2f}", style={"color": "#ea4335"}),
                            ]),
                        ], width=4),
                        dbc.Col([
                            html.H4("📈 Difference (GH - 24/7)", style={"color": "#9aa0a6", "marginTop": "10px"}),
                            html.Div([
                                html.P(f"Trade Count Δ: {gh_metrics['count'] - all_24_7_metrics['count']:+d}", style={"color": "#e8eaed"}),
                                html.P(f"Win Rate Δ: {wr_diff:+.1f}%", 
                                      style={"color": "#34a853" if wr_diff > 0 else "#ea4335"}),
                                html.P(f"P&L Δ (Dollars): ${pnl_diff_dollars:+,.2f}",
                                      style={"color": "#34a853" if pnl_diff_dollars > 0 else "#ea4335"}),
                                html.P(f"P&L Δ (Percent): {pnl_diff_percent:+.1f}%",
                                      style={"color": "#34a853" if pnl_diff_dollars > 0 else "#ea4335"}),
                                html.P(f"Profit Factor Δ: {pf_diff:+.2f}",
                                      style={"color": "#34a853" if pf_diff > 0 else "#ea4335"}),
                            ]),
                        ], width=4),
                    ]),
                    
                    html.Hr(style={"borderColor": "#2d3139", "margin": "30px 0"}),
                    
                    html.H4("📊 Performance Comparison Chart", style={"color": "#fff", "marginBottom": "20px"}),
                    dcc.Graph(figure=fig_bar, config={"displayModeBar": True}),
                    
                    html.Hr(style={"borderColor": "#2d3139", "margin": "30px 0"}),
                    
                    html.Hr(style={"borderColor": "#2d3139", "margin": "30px 0"}),
                    
                    # Summary Cards for Golden Hour and 24/7 Trading (Last 24 Hours)
                    html.H4("📈 Trading Summaries (Last 24 Hours)", style={"color": "#fff", "marginBottom": "20px", "marginTop": "30px"}),
                    dbc.Row([
                        dbc.Col([
                            summary_card_24_7(gh_summary_24h, "🕘 Golden Hour Trading (09:00-16:00 UTC, Last 24 Hours)")
                        ], width=6),
                        dbc.Col([
                            summary_card_24_7(all_24_7_summary_24h, "🌐 24/7 Trading (Last 24 Hours)")
                        ], width=6),
                    ]),
                    
                    html.Hr(style={"borderColor": "#2d3139", "margin": "30px 0"}),
                    
                    # Open Positions Table
                    html.H4("📈 Open Positions", style={"color": "#fff", "marginBottom": "20px", "marginTop": "30px"}),
                    html.P(f"Currently {len(open_df_24_7)} open position(s)", style={"color": "#9aa0a6", "marginBottom": "10px"}),
                    dash_table.DataTable(
                        id="open-positions-24-7-table",
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
                        data=open_df_24_7.to_dict("records") if not open_df_24_7.empty else [],
                        style_table={"backgroundColor": "#0f1217", "color": "#e8eaed"},
                        style_cell={"backgroundColor": "#0f1217", "color": "#e8eaed", "textAlign": "left", "padding": "10px"},
                        style_header={"backgroundColor": "#1b1f2a", "fontWeight": "bold"},
                        style_data_conditional=[
                            {
                                "if": {"filter_query": "{pnl_usd} >= 0"},
                                "backgroundColor": "#1a4d2e",
                            },
                            {
                                "if": {"filter_query": "{pnl_usd} < 0"},
                                "backgroundColor": "#4d1a1a",
                            },
                        ],
                    ),
                    
                    html.Hr(style={"borderColor": "#2d3139", "margin": "30px 0"}),
                    
                    # Closed Positions Table
                    html.H4("📉 Recent Closed Positions", style={"color": "#fff", "marginBottom": "20px", "marginTop": "30px"}),
                    html.P(f"Showing most recent {min(100, len(closed_df_filtered))} of {len(closed_positions)} closed positions", 
                           style={"color": "#9aa0a6", "marginBottom": "10px"}),
                    dash_table.DataTable(
                        id="closed-positions-24-7-table",
                        columns=[
                            {"name": "Symbol", "id": "symbol"},
                            {"name": "Strategy", "id": "strategy"},
                            {"name": "Trading Window", "id": "trading_window"},
                            {"name": "Entry Time", "id": "entry_time"},
                            {"name": "Exit Time", "id": "exit_time"},
                            {"name": "Entry Price", "id": "entry_price", "type": "numeric", "format": {"specifier": ".4f"}},
                            {"name": "Exit Price", "id": "exit_price", "type": "numeric", "format": {"specifier": ".4f"}},
                            {"name": "Hold (h)", "id": "hold_duration_h", "type": "numeric", "format": {"specifier": ".1f"}},
                            {"name": "ROI (%)", "id": "roi_pct", "type": "numeric", "format": {"specifier": ".2f"}},
                            {"name": "Net P&L", "id": "net_pnl", "type": "numeric", "format": {"specifier": ".2f"}},
                            {"name": "Fees", "id": "fees", "type": "numeric", "format": {"specifier": ".2f"}},
                        ],
                        data=closed_df_filtered.head(100).to_dict("records") if not closed_df_filtered.empty and len(closed_df_filtered) > 0 else [],
                        page_size=20,
                        style_table={"backgroundColor": "#0f1217", "color": "#e8eaed"},
                        style_cell={"backgroundColor": "#0f1217", "color": "#e8eaed", "textAlign": "left", "padding": "10px"},
                        style_header={"backgroundColor": "#1b1f2a", "fontWeight": "bold"},
                        style_data_conditional=[
                            {
                                "if": {"filter_query": "{net_pnl} >= 0"},
                                "backgroundColor": "#1a4d2e",
                            },
                            {
                                "if": {"filter_query": "{net_pnl} < 0"},
                                "backgroundColor": "#4d1a1a",
                            },
                        ],
                    ) if not closed_df_filtered.empty else html.P(
                        f"No closed positions data available. DataFrame empty: {closed_df_24_7.empty if 'closed_df_24_7' in locals() else 'not loaded'}. Check logs for errors.",
                        style={"color": "#ea4335", "marginTop": "20px"}
                    ),
                ]),
            ], style={"backgroundColor": "#0f1217", "border": "1px solid #2d3139", "marginBottom": "20px"}),
        ])
    except Exception as e:
        print(f"❌ [DASHBOARD-V2] Error building 24/7 trading tab: {e}", flush=True)
        import traceback
        traceback.print_exc()
        return html.Div([
            dbc.Card([
                dbc.CardHeader(html.H3("⏰ Golden Hour vs 24/7 Trading Comparison", style={"color": "#fff", "margin": 0})),
                dbc.CardBody([
                    html.P(f"Error loading 24/7 trading data: {str(e)}", style={"color": "#ea4335"}),
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
