"""
Robust trade loader for P&L Dashboard
- Uses DataRegistry for canonical trade source (logs/portfolio.json)
- Normalizes timestamps (ISO strings, epoch seconds, epoch ms)
- Maps actual field names from the trading system
- Detects file format (JSON object with 'trades' array vs JSON lines)
- CACHED: DataFrame is cached and only rebuilt when source files change
"""

import os
import json
import time
import threading
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple
import pandas as pd
from src.io_safe import safe_open, AccessBlocked
from src.data_registry import DataRegistry as DR
from src.infrastructure.path_registry import resolve_path

# Resolve paths to absolute for slot-based deployments
LOG_FILES = [
    resolve_path(DR.PORTFOLIO_MASTER),
]

DATE_FMT = "%Y-%m-%d %H:%M:%S"

# DataFrame cache to prevent memory-intensive rebuilds on every request
_df_cache: Optional[pd.DataFrame] = None
_cache_timestamp: float = 0
_cache_file_mtime: float = 0
_cache_lock = threading.Lock()
CACHE_TTL_SECONDS = 30  # Cache for 30s to reduce database queries and improve performance

def clear_cache():
    """Clear the DataFrame cache to force fresh data on next load."""
    global _df_cache, _cache_timestamp, _cache_file_mtime
    with _cache_lock:
        _df_cache = None
        _cache_timestamp = 0
        _cache_file_mtime = 0

def _safe_load_json(path: str) -> List[Dict[str, Any]]:
    """
    Load trades from JSON file, handling multiple formats:
    1. Single JSON object with 'trades' array
    2. JSON lines format (one trade per line)
    3. Portfolio.json format
    4. Positions.json format (closed_positions)
    
    OPERATOR SAFETY: Checks for file locks before reading to avoid stale data.
    """
    # Resolve relative paths to absolute for slot-based deployments
    abs_path = resolve_path(path) if not os.path.isabs(path) else path
    if not os.path.exists(abs_path):
        return []
    
    # OPERATOR SAFETY: Check for write lock before reading
    lock_path = Path(f"{abs_path}.lock")
    if lock_path.exists():
        # File may be locked for writing - check if lock is stale
        try:
            lock_age = time.time() - lock_path.stat().st_mtime
            if lock_age > 30:  # Lock older than 30s is probably stale
                try:
                    from src.operator_safety import alert_operator, ALERT_MEDIUM
                    alert_operator(
                        ALERT_MEDIUM,
                        "DASHBOARD_LOAD",
                        f"Reading file with stale lock (age: {lock_age:.1f}s) - data may be inconsistent",
                        {"filepath": abs_path, "lock_age": lock_age}
                    )
                except:
                    pass
        except:
            pass  # Lock check is best-effort
    
    try:
        # Use file_locks for safe reading
        from src.file_locks import locked_json_read
        try:
            data = locked_json_read(abs_path, default={}, timeout=2.0)
            # Handle different data formats
            if isinstance(data, dict):
                if "trades" in data and isinstance(data["trades"], list):
                    return data["trades"]
                elif "closed_positions" in data and isinstance(data["closed_positions"], list):
                    return data["closed_positions"]
                return []
            elif isinstance(data, list):
                return data
            else:
                return []
        except:
            # Fallback to direct read if file_locks fails
            pass
        
        # Fallback: Direct read (for JSONL files or if file_locks unavailable)
        with open(abs_path, "r") as f:
            content = f.read().strip()
            if not content:
                return []
            
            data = json.loads(content)
            
            if isinstance(data, dict):
                if "trades" in data and isinstance(data["trades"], list):
                    return data["trades"]
                elif "closed_positions" in data and isinstance(data["closed_positions"], list):
                    return data["closed_positions"]
                return []
            elif isinstance(data, list):
                return data
            else:
                return []
    except json.JSONDecodeError:
        events = []
        with open(abs_path, "r") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    evt = json.loads(line)
                    events.append(evt)
                except Exception:
                    continue
        return events
    except Exception:
        return []

def _normalize_timestamp(ts_raw) -> int:
    """
    Convert various timestamp formats to epoch seconds:
    - ISO string (e.g., '2025-11-11T21:30:49.334855-07:00')
    - Epoch milliseconds (> 1e12)
    - Epoch seconds
    """
    if ts_raw is None:
        return int(time.time())
    
    if isinstance(ts_raw, str):
        try:
            dt = datetime.fromisoformat(ts_raw.replace("Z", "+00:00"))
            return int(dt.timestamp())
        except Exception:
            try:
                dt = datetime.strptime(ts_raw, DATE_FMT)
                return int(dt.timestamp())
            except Exception:
                return int(time.time())
    
    if isinstance(ts_raw, (int, float)):
        if ts_raw > 1e12:
            return int(ts_raw / 1000)
        return int(ts_raw)
    
    return int(time.time())

def _map_direction_to_side(direction: str) -> str:
    """Convert LONG/SHORT to buy/sell"""
    if direction.upper() == "LONG":
        return "buy"
    elif direction.upper() == "SHORT":
        return "sell"
    return direction.lower()

def _normalize_trades(events: List[Dict[str, Any]]) -> pd.DataFrame:
    """
    Normalize trades from various formats to standard schema.
    
    Expected fields in input (futures format):
    - gross_pnl: Raw P&L before fees
    - net_pnl: P&L after fees
    - notional_size: Size in USD
    - trading_fees: Trading commission
    - funding_fees: Funding costs
    - direction: LONG/SHORT
    - timestamp: ISO string
    - symbol, strategy, etc.
    
    OR closed position format:
    - symbol, strategy, entry_price, exit_price, size
    - closed_at, final_roi
    
    Output schema:
    - ts, time, symbol, strategy, venue, side
    - size_usd, pnl_usd, fee_usd, net_pnl_usd
    - hour, date
    """
    if not events:
        return pd.DataFrame(columns=[
            "ts", "time", "symbol", "strategy", "venue", "side",
            "size_usd", "pnl_usd", "fee_usd", "net_pnl_usd",
            "order_id", "trade_id", "hour", "date"
        ])
    
    rows = []
    for e in events:
        if "closed_at" in e:
            # Closed position format from positions_futures.json
            ts = _normalize_timestamp(e.get("closed_at"))
            size_usd = float(e.get("size", 0.0))
            
            # CRITICAL FIX: Use the actual 'pnl' field from closed_positions
            # DO NOT calculate from final_roi * size - that's incorrect
            pnl_value = e.get("pnl", 0.0)
            if pnl_value is None or (isinstance(pnl_value, float) and pnl_value != pnl_value):
                pnl_value = 0.0  # Handle NaN
            gross_pnl = float(pnl_value)
            
            # Estimate fees (already deducted in pnl field)
            trading_fees = size_usd * 0.0006
            total_fees = trading_fees
            
            direction = e.get("direction", "")
            side = _map_direction_to_side(direction) if direction else "sell"
            
            row = {
                "ts": ts,
                "time": datetime.utcfromtimestamp(ts).strftime(DATE_FMT),
                "symbol": e.get("symbol", ""),
                "strategy": e.get("strategy", ""),
                "venue": "futures",
                "side": side,
                "size_usd": size_usd,
                "pnl_usd": gross_pnl,
                "fee_usd": total_fees,
                "net_pnl_usd": gross_pnl,  # pnl is already net
                "order_id": "",
                "trade_id": "",
            }
            rows.append(row)
        else:
            ts = _normalize_timestamp(e.get("timestamp") or e.get("ts"))
            
            # Handle portfolio.json format (spot trades and partial exits)
            # FIELD ALIASES: See DataIntegrityValidator.FIELD_ALIASES for canonical mapping
            # portfolio.json uses: gross_profit, net_profit, position_size/partial_size
            # trades_futures.json uses: gross_pnl, net_pnl, notional_size
            if "gross_profit" in e and ("profit" in e or "net_profit" in e):
                # Portfolio.json format - handles both 'profit' and 'net_profit' field names
                gross_pnl = float(e.get("gross_profit", 0.0))
                total_fees = float(e.get("fees", 0.0))
                net_pnl = float(e.get("profit", e.get("net_profit", 0.0)))
                size_usd = float(e.get("position_size", e.get("partial_size", 0.0)))
                venue = "spot"
            else:
                # Futures format
                gross_pnl = float(e.get("gross_pnl", e.get("pnl_usd", 0.0)))
                trading_fees = float(e.get("trading_fees", 0.0))
                funding_fees = float(e.get("funding_fees", 0.0))
                total_fees = trading_fees + funding_fees
                net_pnl = gross_pnl - total_fees
                size_usd = float(e.get("notional_size", e.get("size_usd", e.get("size", 0.0))))
                venue = e.get("venue", "futures")
            
            direction = e.get("direction", e.get("side", ""))
            side = _map_direction_to_side(direction) if direction else ""
            
            row = {
                "ts": ts,
                "time": datetime.utcfromtimestamp(ts).strftime(DATE_FMT),
                "symbol": e.get("symbol", ""),
                "strategy": e.get("strategy", ""),
                "venue": venue,
                "side": side,
                "size_usd": size_usd,
                "pnl_usd": gross_pnl,
                "fee_usd": total_fees,
                "net_pnl_usd": net_pnl,
                "order_id": e.get("order_id", ""),
                "trade_id": e.get("trade_id", ""),
            }
            rows.append(row)
    
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    
    # Only recalculate net_pnl_usd if not already set (for futures trades)
    if "net_pnl_usd" not in df.columns or df["net_pnl_usd"].isna().any():
        df["net_pnl_usd"] = df["pnl_usd"] - df["fee_usd"].fillna(0.0)
    
    # Convert datetime columns (fix FutureWarning by using .dt.strftime instead of .astype(str))
    if not df.empty and "time" in df.columns:
        df["hour"] = pd.to_datetime(df["time"]).dt.floor("H").dt.strftime("%Y-%m-%d %H:00:00")
        df["date"] = pd.to_datetime(df["time"]).dt.date.astype(str)
    
    return df

def _get_source_mtime() -> float:
    """Get the latest modification time of all source files."""
    latest = 0
    for path in LOG_FILES:
        try:
            # Ensure path is absolute (already resolved in LOG_FILES, but double-check)
            abs_path = resolve_path(path) if not os.path.isabs(path) else path
            mtime = os.path.getmtime(abs_path)
            if mtime > latest:
                latest = mtime
        except OSError:
            pass
    return latest


def load_trades_df() -> pd.DataFrame:
    """
    Load and normalize trades from SQLite (primary) with JSONL fallback.
    
    Phase 4 Tri-Layer Architecture: Reads from SQLite for analytics.
    Falls back to JSONL files if SQLite is unavailable.
    
    CACHING: DataFrame is cached and only rebuilt when cache TTL has elapsed.
    """
    global _df_cache, _cache_timestamp, _cache_file_mtime
    
    current_time = time.time()
    current_mtime = _get_source_mtime()
    
    with _cache_lock:
        cache_age = current_time - _cache_timestamp
        file_changed = current_mtime > _cache_file_mtime
        
        if _df_cache is not None and cache_age < CACHE_TTL_SECONDS and not file_changed:
            return _df_cache.copy()
        
        all_trades = []
        
        try:
            # Limit to last 1000 trades for performance (dashboard doesn't need all history on load)
            # Use threading-based timeout (more reliable than signal.SIGALRM)
            import threading
            
            closed_trades_result = [None]
            closed_trades_error = [None]
            
            def fetch_trades():
                try:
                    closed_trades_result[0] = DR.get_closed_trades_from_db(limit=1000, symbol=None)
                except Exception as e:
                    closed_trades_error[0] = e
            
            fetch_thread = threading.Thread(target=fetch_trades, daemon=True)
            fetch_thread.start()
            fetch_thread.join(timeout=5.0)  # 5 second timeout
            
            if fetch_thread.is_alive():
                print(f"⚠️  [LOADER] Database query timed out (>5s), falling back to JSONL")
                closed_trades = []
            elif closed_trades_error[0]:
                raise closed_trades_error[0]
            else:
                closed_trades = closed_trades_result[0] or []
                if closed_trades:
                    print(f"📊 [LOADER] Loaded {len(closed_trades)} trades from SQLite (limited to 1000 for performance)")
                    all_trades.extend(closed_trades)
        except TimeoutError:
            print(f"⚠️  [LOADER] Database query timed out, falling back to JSONL")
            closed_trades = []
        except Exception as e:
            print(f"⚠️  [LOADER] SQLite read failed, falling back to JSONL: {e}")
            for log_path in LOG_FILES:
                events = _safe_load_json(log_path)
                if events:
                    print(f"📊 [LOADER] Loaded {len(events)} trades from {log_path}")
                    all_trades.extend(events)
        
        print(f"📊 [LOADER] Total trades loaded: {len(all_trades)}")
        
        df = _normalize_trades(all_trades)
        
        _df_cache = df
        _cache_timestamp = current_time
        _cache_file_mtime = current_mtime
        
        return df.copy()

def get_spot_realized_pnl() -> float:
    """
    Get spot realized P&L from portfolio.json's realized_pnl field.
    This is the AUTHORITATIVE source for closed-position P&L.
    Uses DataRegistry for canonical path (automatically resolves to absolute).
    
    Returns:
        Realized P&L from closed spot positions
    """
    # DR.read_json() automatically resolves paths via resolve_path()
    portfolio = DR.read_json(DR.PORTFOLIO_MASTER)
    if not portfolio:
        return 0.0
    
    return portfolio.get("realized_pnl", 0.0)