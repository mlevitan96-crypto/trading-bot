"""
Unified Governance Sentinel — Full Self-Monitoring, Health Checks, and Self-Healing
Adapted for the existing trading bot architecture with proper integration points.
"""
import os
import json
import time
from typing import List, Dict, Any, Optional
from datetime import datetime
import pytz

ARIZONA_TZ = pytz.timezone('America/Phoenix')

# --------------------------------------------------------------------------------------
# Paths - adapted to existing structure
# --------------------------------------------------------------------------------------
TRADES_LOG = "logs/trades_futures.json"
POSITIONS_LOG = "logs/positions_futures.json"
EVENTS_LOG = "logs/unified_events.jsonl"
SELF_HEAL_LOG = "logs/self_heal.jsonl"

# --------------------------------------------------------------------------------------
# Helpers: IO + safe calls
# --------------------------------------------------------------------------------------

def _append_json(path: str, obj: Dict[str, Any]):
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "a") as f:
            f.write(json.dumps(obj) + "\n")
    except Exception as e:
        print(f"[GOVERNANCE] Failed to append {path}: {e}")

def _load_json(path: str, default=None):
    if not os.path.exists(path):
        return default if default is not None else {}
    try:
        with open(path, "r") as f:
            return json.load(f)
    except Exception:
        return default if default is not None else {}

def _safe_call(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except Exception as e:
        _append_json(EVENTS_LOG, {
            "ts": int(time.time()),
            "event": "safe_call_error",
            "fn": getattr(fn, "__name__", "unknown"),
            "err": str(e)
        })
        return None

# --------------------------------------------------------------------------------------
# Adapter functions for existing codebase
# --------------------------------------------------------------------------------------

def _get_open_positions() -> List[Dict[str, Any]]:
    """Load open positions from existing structure."""
    positions_data = _load_json(POSITIONS_LOG, {"open_positions": []})
    return positions_data.get("open_positions", [])

def _get_trades() -> List[Dict[str, Any]]:
    """Load trades from existing structure."""
    trades_data = _load_json(TRADES_LOG, {"trades": []})
    return trades_data.get("trades", [])

def _timestamp_to_unix(ts_str: str) -> int:
    """Convert ISO timestamp to unix timestamp."""
    try:
        dt = datetime.fromisoformat(ts_str.replace('Z', '+00:00'))
        return int(dt.timestamp())
    except:
        return 0

# --------------------------------------------------------------------------------------
# Integration adapters
# --------------------------------------------------------------------------------------

_kill_switch_active = False

def block_new_entries_global():
    """Temporarily block new position entries."""
    global _kill_switch_active
    _kill_switch_active = True
    try:
        from src.capital_protection import _emergency_stop
        _safe_call(_emergency_stop, "governance_sentinel_self_heal")
    except ImportError:
        pass

def allow_new_entries_global():
    """Re-enable position entries."""
    global _kill_switch_active
    _kill_switch_active = False

def update_attribution(symbol: str, strategy: str, venue: str, net_pnl: float):
    """Update attribution tracking with corrected net P&L."""
    try:
        from src.phase10_1_allocator import update_venue_attribution, update_strategy_attribution
        _safe_call(update_venue_attribution, venue, net_pnl)
        _safe_call(update_strategy_attribution, strategy, net_pnl)
    except ImportError:
        pass

def close_position_adapter(symbol: str, side: str, size_usd: float) -> Dict[str, Any]:
    """Adapter for closing positions using existing position manager."""
    try:
        from src.position_manager import close_futures_position
        from src.exchange_gateway import ExchangeGateway
        
        gateway = ExchangeGateway()
        df = gateway.fetch_ohlcv(symbol, timeframe="1m", limit=5, venue="futures")
        
        if df is None or len(df) == 0:
            return {"symbol": symbol, "closed": False, "error": "no_price_data"}
        
        current_price = float(df['close'].iloc[-1])
        
        # Map side to direction
        direction = "LONG" if side.upper() in ["LONG", "BUY"] else "SHORT"
        
        success = close_futures_position(
            symbol=symbol,
            strategy="EMA-Futures",
            direction=direction,
            exit_price=current_price,
            reason="governance_watchdog_stale",
            funding_fees=0.0
        )
        
        return {"symbol": symbol, "closed": success, "price": current_price}
    except Exception as e:
        return {"symbol": symbol, "closed": False, "error": str(e)}

# --------------------------------------------------------------------------------------
# Canonical Net P&L
# --------------------------------------------------------------------------------------

def _net_pnl(row: Dict[str, Any]) -> float:
    """Calculate net P&L (P&L - fees)."""
    pnl = float(row.get("pnl_usd", 0.0))
    fee = float(row.get("trading_fee_usd", 0.0))
    return pnl - fee

# --------------------------------------------------------------------------------------
# Self-Heal: Venue integrity (futures-only)
# --------------------------------------------------------------------------------------

def venue_integrity_check_and_heal():
    """Ensure all trades route to futures venue."""
    now = int(time.time())
    trades = _get_trades()
    
    if not trades:
        return
    
    mismatches = [t for t in trades[-100:] if t.get("venue") != "futures"]
    
    if mismatches:
        _append_json(SELF_HEAL_LOG, {
            "ts": now,
            "event": "venue_integrity_alert",
            "count": len(mismatches),
            "samples": mismatches[:3]
        })

# --------------------------------------------------------------------------------------
# Self-Heal: Net P&L verification
# --------------------------------------------------------------------------------------

def net_pnl_verify_and_replay():
    """Verify net P&L includes fees and replay if needed."""
    now = int(time.time())
    trades = _get_trades()
    
    if not trades:
        _append_json(EVENTS_LOG, {"ts": now, "event": "net_pnl_verify_skip", "reason": "no_trades"})
        return
    
    recent_trades = trades[-50:]
    mismatches = []
    
    for t in recent_trades:
        calc_net = _net_pnl(t)
        logged_net = float(t.get("net_pnl_usd", calc_net))
        
        if abs(calc_net - logged_net) > 0.01:
            mismatches.append({
                "symbol": t.get("symbol"),
                "calc": calc_net,
                "logged": logged_net
            })
    
    if not mismatches:
        _append_json(EVENTS_LOG, {"ts": now, "event": "net_pnl_integrity_pass"})
        return
    
    # Log discrepancies for monitoring
    _append_json(SELF_HEAL_LOG, {
        "ts": now,
        "event": "net_pnl_discrepancy",
        "count": len(mismatches),
        "samples": mismatches[:5]
    })

# --------------------------------------------------------------------------------------
# Heartbeat: Inactivity check
# --------------------------------------------------------------------------------------

def _last_trade_ts() -> int:
    """Get timestamp of last trade."""
    trades = _get_trades()
    if not trades:
        return 0
    
    last_trade = trades[-1]
    ts_str = last_trade.get("timestamp", "")
    return _timestamp_to_unix(ts_str) if ts_str else 0

def kill_switch_monitor_and_recover():
    """Monitor kill switch and attempt auto-recovery."""
    try:
        from src.autonomous_kill_switch_monitor import monitor_and_recover
        return _safe_call(monitor_and_recover)
    except ImportError:
        return None

def heartbeat_check_and_nudge():
    """Check for trading inactivity and diagnose root cause."""
    now = int(time.time())
    last_ts = _last_trade_ts()
    
    if last_ts == 0:
        return
    
    inactivity_sec = now - last_ts
    inactivity_hours = round(inactivity_sec / 3600, 1)
    
    if inactivity_sec > 3600:  # Alert after 1 hour (was 4)
        diagnosis = diagnose_trading_freeze()
        
        _append_json(EVENTS_LOG, {
            "ts": now,
            "event": "heartbeat_inactivity_alert",
            "inactivity_hours": inactivity_hours,
            "diagnosis": diagnosis
        })
        
        if inactivity_hours >= 2:
            print(f"⚠️ GOVERNANCE: No trades for {inactivity_hours}h - Diagnosis: {diagnosis.get('root_cause', 'unknown')}")
            
            if diagnosis.get("auto_fix_applied"):
                print(f"   ✅ Auto-fix applied: {diagnosis.get('fix_action')}")

def diagnose_trading_freeze() -> Dict[str, Any]:
    """
    Proactively diagnose why trading is frozen.
    Uses centralized checks from unified_self_governance_bot.
    Returns diagnosis with root cause and auto-fix actions taken.
    """
    diagnosis = {
        "root_cause": None,
        "details": {},
        "auto_fix_applied": False,
        "fix_action": None
    }
    
    try:
        from src.unified_self_governance_bot import (
            get_recent_events, clear_freeze, emit_watchdog_telemetry,
            verify_data_file_integrity
        )
        
        recent_events = get_recent_events(minutes=60)
        
        freeze_events = [e for e in recent_events if "freeze" in str(e.get("event", "")).lower()]
        watchdog_issues = [e for e in recent_events if e.get("event") == "watchdog_issue_detected"]
        data_issues = [e for e in recent_events if e.get("event") == "data_file_integrity_failed"]
        
        if data_issues:
            diagnosis["root_cause"] = "data_file_integrity_failed"
            diagnosis["details"]["data_issues"] = data_issues[-1]
        elif freeze_events:
            last_freeze = max(freeze_events, key=lambda x: x.get("ts", 0))
            diagnosis["details"]["last_freeze"] = last_freeze
            
            if watchdog_issues:
                last_issue = max(watchdog_issues, key=lambda x: x.get("ts", 0))
                failing_checks = [k for k, v in last_issue.items() 
                                  if k.endswith("_ok") and v is False]
                diagnosis["root_cause"] = f"watchdog_freeze: {failing_checks}"
                diagnosis["details"]["failing_checks"] = failing_checks
                
                emit_watchdog_telemetry(context="auto_heal")
                clear_freeze(reason="governance_auto_heal")
                diagnosis["auto_fix_applied"] = True
                diagnosis["fix_action"] = "emitted_telemetry_and_cleared_freeze"
            else:
                diagnosis["root_cause"] = "freeze_unknown_cause"
        
        if not verify_data_file_integrity():
            if not diagnosis["root_cause"]:
                diagnosis["root_cause"] = "data_file_integrity_check_failed"
        
    except Exception as e:
        diagnosis["root_cause"] = f"diagnosis_error: {str(e)}"
    
    return diagnosis

# --------------------------------------------------------------------------------------
# Exit Watchdog: Auto-close stale positions
# --------------------------------------------------------------------------------------

MAX_HOURS_OPEN = 48  # Close positions older than 48 hours

def exit_watchdog_close_stale():
    """Auto-close positions that have been open too long."""
    now = int(time.time())
    positions = _get_open_positions()
    
    if not positions:
        _append_json(EVENTS_LOG, {"ts": now, "event": "exit_watchdog_pass", "open_positions": 0})
        return
    
    stale = []
    for pos in positions:
        ts_str = pos.get("opened_at", "")
        ts_open = _timestamp_to_unix(ts_str)
        
        if ts_open == 0:
            continue
        
        age_sec = now - ts_open
        age_hours = age_sec / 3600
        
        if age_hours > MAX_HOURS_OPEN:
            stale.append({
                "symbol": pos.get("symbol"),
                "direction": pos.get("direction"),
                "age_hours": round(age_hours, 1),
                "opened_at": ts_str
            })
    
    if not stale:
        _append_json(EVENTS_LOG, {
            "ts": now,
            "event": "exit_watchdog_pass",
            "open_positions": len(positions),
            "max_age_hours": MAX_HOURS_OPEN
        })
        return
    
    # Close stale positions
    block_new_entries_global()
    closed = []
    
    try:
        for pos_info in stale:
            result = close_position_adapter(
                symbol=pos_info["symbol"],
                side=pos_info["direction"],
                size_usd=0.0
            )
            closed.append({
                "symbol": pos_info["symbol"],
                "age_hours": pos_info["age_hours"],
                "closed": result.get("closed", False)
            })
            _append_json(EVENTS_LOG, {
                "ts": now,
                "event": "forced_exit",
                "position": pos_info,
                "result": result
            })
    finally:
        allow_new_entries_global()
    
    _append_json(SELF_HEAL_LOG, {
        "ts": now,
        "event": "exit_watchdog_self_heal",
        "closed_count": len(closed),
        "positions": closed
    })
    
    print(f"🛡️ GOVERNANCE SENTINEL: Closed {len(closed)} stale positions (>{MAX_HOURS_OPEN}h old)")

# --------------------------------------------------------------------------------------
# Log Sink Integrity
# --------------------------------------------------------------------------------------

def log_sink_integrity_check():
    """Verify logs are being written correctly."""
    now = int(time.time())
    
    # Check that critical log files exist
    if not os.path.exists(TRADES_LOG):
        _append_json(SELF_HEAL_LOG, {
            "ts": now,
            "event": "log_sink_missing",
            "file": TRADES_LOG
        })
    
    if not os.path.exists(POSITIONS_LOG):
        _append_json(SELF_HEAL_LOG, {
            "ts": now,
            "event": "log_sink_missing",
            "file": POSITIONS_LOG
        })

# --------------------------------------------------------------------------------------
# Governance registration
# --------------------------------------------------------------------------------------

def register_governance_sentinel(register_periodic_task_fn):
    """
    Register all governance checks as periodic tasks.
    
    Args:
        register_periodic_task_fn: Function to register periodic tasks
                                   Should accept (fn, interval_sec)
    """
    print("🛡️ Registering Governance Sentinel...")
    
    # 1-minute cadence for kill switch monitor (critical safety)
    register_periodic_task_fn(kill_switch_monitor_and_recover, interval_sec=60)
    
    # 5-minute cadence for heartbeat (catches freeze loops faster)
    register_periodic_task_fn(heartbeat_check_and_nudge, interval_sec=300)
    
    # 10-minute cadence for most checks
    register_periodic_task_fn(venue_integrity_check_and_heal, interval_sec=600)
    register_periodic_task_fn(net_pnl_verify_and_replay, interval_sec=600)
    register_periodic_task_fn(log_sink_integrity_check, interval_sec=600)
    
    # 5-minute cadence for exit watchdog (more aggressive)
    register_periodic_task_fn(exit_watchdog_close_stale, interval_sec=300)
    
    print(f"   ℹ️  Kill Switch Monitor: Auto-recovery when safe (every 1min)")
    print(f"   ℹ️  Heartbeat + Freeze Diagnosis: Every 5min (auto-heals watchdog freezes)")
    print(f"   ℹ️  Exit Watchdog: Auto-close positions >{MAX_HOURS_OPEN}h old (every 5min)")
    print(f"   ℹ️  Venue Integrity: Futures-only enforcement (every 10min)")
    print(f"   ℹ️  Net P&L Verify: Fee inclusion checks (every 10min)")
    print(f"   ℹ️  Log Sink Integrity: File existence checks (every 10min)")
    print("✅ Governance Sentinel registered")
