"""
Hold Time Enforcement Module - Prevents premature exits.

This module enforces minimum hold times to avoid:
1. Quick exits that lose money to fees
2. Panic exits during normal volatility
3. Exits before trades have time to develop

Learning shows:
- Quick trades (<5m) typically lose money due to fees
- Medium holds (15-60m) are most profitable
- Different coins have different optimal hold times

Override conditions allow early exit for:
- Stop-loss triggered
- Take-profit hit
- Liquidation risk
- Manual override flag
"""

import json
import os
import time
from datetime import datetime, timedelta
from typing import Dict, List, Tuple, Optional
from collections import defaultdict
from pathlib import Path

try:
    from src.data_registry import DataRegistry as DR
except ImportError:
    DR = None

try:
    from src.file_locks import atomic_json_save, locked_json_read
except ImportError:
    atomic_json_save = None
    locked_json_read = None

HOLD_TIME_POLICY_PATH = "feature_store/hold_time_policy.json"
HOLD_TIME_LOG_PATH = "logs/hold_time_enforcement.jsonl"
POSITIONS_PATH = "logs/positions_futures.json"

MAJOR_COINS = ["BTCUSDT", "ETHUSDT"]
OTHER_MAJORS = ["BNBUSDT", "SOLUSDT", "XRPUSDT", "ADAUSDT"]
ALTCOINS = ["DOTUSDT", "LINKUSDT", "AVAXUSDT", "MATICUSDT", "OPUSDT", 
            "ARBUSDT", "DOGEUSDT", "TRXUSDT", "PEPEUSDT"]

DEFAULT_HOLD_TIMES = {
    "BTCUSDT": 900,
    "ETHUSDT": 900,
    "BNBUSDT": 720,
    "SOLUSDT": 720,
    "XRPUSDT": 720,
    "ADAUSDT": 720,
    "DOTUSDT": 600,
    "LINKUSDT": 600,
    "AVAXUSDT": 600,
    "MATICUSDT": 600,
    "OPUSDT": 600,
    "ARBUSDT": 600,
    "DOGEUSDT": 600,
    "TRXUSDT": 600,
    "PEPEUSDT": 600,
}

DEFAULT_HOLD_BY_TIER = {
    "major": 900,
    "other_major": 720,
    "altcoin": 600,
    "unknown": 600,
}

OVERRIDE_REASONS = [
    "stop_loss",
    "stop_loss_triggered",
    "take_profit",
    "take_profit_hit",
    "liquidation_risk",
    "liquidation",
    "manual_override",
    "emergency",
    "kill_switch",
    "risk_limit",
    "max_position_cap",
    "capacity_critical",
    "ladder_exit",
    "protective_clearance",
    "turnover_required",
    "drawdown_override",
    "loss_override",
]

# Drawdown override thresholds (Resilience Patch: Hold Time Deadlock Breaker)
DRAWDOWN_OVERRIDE_THRESHOLD = 0.015  # 1.5% portfolio drawdown
LOSS_OVERRIDE_THRESHOLD = 0.02       # 2% unrealized loss on position


def _get_portfolio_drawdown() -> float:
    """
    Compute current portfolio drawdown from positions file.
    Returns drawdown as a percentage (0.0 to 1.0).
    """
    try:
        if not os.path.exists(POSITIONS_PATH):
            return 0.0
        
        with open(POSITIONS_PATH, 'r') as f:
            positions = json.load(f)
        
        total_pnl = 0.0
        total_margin = 0.0
        
        for pos in positions:
            if isinstance(pos, dict):
                pnl = float(pos.get("unrealized_pnl", 0) or 0)
                margin = float(pos.get("margin", 0) or pos.get("size", 0) or 0)
                total_pnl += pnl
                total_margin += margin
        
        if total_margin > 0 and total_pnl < 0:
            return abs(total_pnl) / total_margin
        return 0.0
    except Exception:
        return 0.0


def _get_position_unrealized_pnl_pct(position_id: str) -> float:
    """
    Get unrealized P&L percentage for a specific position.
    Returns negative value for losses (e.g., -0.03 = 3% loss).
    """
    try:
        if not os.path.exists(POSITIONS_PATH):
            return 0.0
        
        with open(POSITIONS_PATH, 'r') as f:
            positions = json.load(f)
        
        for pos in positions:
            if isinstance(pos, dict):
                pos_id = pos.get("id") or pos.get("position_id") or ""
                symbol = pos.get("symbol", "")
                
                if pos_id == position_id or symbol in position_id:
                    pnl = float(pos.get("unrealized_pnl", 0) or 0)
                    margin = float(pos.get("margin", 0) or pos.get("size", 0) or 0)
                    if margin > 0:
                        return pnl / margin  # negative if losing
        return 0.0
    except Exception:
        return 0.0


def _now() -> str:
    return datetime.utcnow().isoformat() + "Z"


def _now_ts() -> float:
    return time.time()


def _log(msg: str):
    ts = datetime.utcnow().isoformat() + "Z"
    print(f"[{ts}] [HOLD-TIME] {msg}")


def _read_json(path: str, default=None):
    """Read JSON file with optional locking."""
    if locked_json_read is not None:
        try:
            return locked_json_read(path, default or {})
        except Exception:
            pass
    
    try:
        if os.path.exists(path):
            with open(path, 'r') as f:
                return json.load(f)
    except Exception:
        pass
    return default if default is not None else {}


def _write_json(path: str, data: dict) -> bool:
    """Write JSON file with optional atomic locking."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    
    if atomic_json_save is not None:
        try:
            return atomic_json_save(path, data)
        except Exception:
            pass
    
    try:
        tmp_path = path + '.tmp'
        with open(tmp_path, 'w') as f:
            json.dump(data, f, indent=2)
        os.replace(tmp_path, path)
        return True
    except Exception as e:
        _log(f"Error writing {path}: {e}")
        return False


def _append_jsonl(path: str, record: dict):
    """Append record to JSONL file."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    record['ts'] = _now_ts()
    record['ts_iso'] = _now()
    try:
        with open(path, 'a') as f:
            f.write(json.dumps(record, default=str) + '\n')
    except Exception as e:
        _log(f"Error appending to {path}: {e}")


def _parse_timestamp(ts) -> Optional[float]:
    """Parse timestamp to epoch seconds."""
    if ts is None:
        return None
    if isinstance(ts, (int, float)):
        return float(ts)
    if isinstance(ts, str):
        try:
            ts_clean = ts.replace('Z', '+00:00')
            dt = datetime.fromisoformat(ts_clean)
            return dt.timestamp()
        except Exception:
            pass
        for fmt in [
            "%Y-%m-%dT%H:%M:%S.%f%z",
            "%Y-%m-%dT%H:%M:%S%z",
            "%Y-%m-%dT%H:%M:%S.%f",
            "%Y-%m-%dT%H:%M:%S",
        ]:
            try:
                dt = datetime.strptime(ts[:26], fmt[:len(ts)])
                return dt.timestamp()
            except Exception:
                continue
    return None


def _get_symbol_tier(symbol: str) -> str:
    """Classify symbol into tier for default hold times."""
    if symbol in MAJOR_COINS:
        return "major"
    elif symbol in OTHER_MAJORS:
        return "other_major"
    elif symbol in ALTCOINS:
        return "altcoin"
    else:
        return "unknown"


class HoldTimeEnforcer:
    """
    Enforces minimum hold times to prevent premature exits.
    
    Strategy:
    - BLOCK exits before minimum hold time
    - ALLOW override for stop-loss, take-profit, liquidation risk
    - LEARN optimal hold times from historical P&L data
    - TRACK enforcement decisions for analysis
    """
    
    def __init__(self):
        self.policy = {}
        self.active_positions = {}
        self.symbol_hold_times = {}
        self.direction_hold_times = {}
        self.enforcement_stats = defaultdict(int)
        self.load_policy()
    
    def load_policy(self):
        """Load hold time policy from file."""
        self.policy = _read_json(HOLD_TIME_POLICY_PATH, {
            "version": 1,
            "updated_at": _now(),
            "symbol_hold_times": DEFAULT_HOLD_TIMES.copy(),
            "direction_hold_times": {},
            "tier_defaults": DEFAULT_HOLD_BY_TIER.copy(),
            "override_reasons": OVERRIDE_REASONS.copy(),
            "stats": {
                "blocks": 0,
                "allows": 0,
                "overrides": 0,
            },
            "learned_adjustments": {},
        })
        
        self.symbol_hold_times = self.policy.get("symbol_hold_times", DEFAULT_HOLD_TIMES.copy())
        self.direction_hold_times = self.policy.get("direction_hold_times", {})
        self.active_positions = self.policy.get("active_positions", {})
        
        _log(f"Loaded policy with {len(self.symbol_hold_times)} symbol hold times")
    
    def save_policy(self):
        """Save current policy to file."""
        self.policy["updated_at"] = _now()
        self.policy["symbol_hold_times"] = self.symbol_hold_times
        self.policy["direction_hold_times"] = self.direction_hold_times
        self.policy["active_positions"] = self.active_positions
        self.policy["stats"] = dict(self.enforcement_stats)
        
        _write_json(HOLD_TIME_POLICY_PATH, self.policy)
    
    def record_entry(self, position_id: str, symbol: str, side: str, entry_ts, position_data: Dict = None) -> Dict:
        """
        Record when a position is opened for hold time tracking.
        
        Args:
            position_id: Unique identifier for the position
            symbol: Trading pair (e.g., BTCUSDT)
            side: LONG or SHORT
            entry_ts: Entry timestamp (epoch or ISO string)
            position_data: Optional position dict to check for TRUE TREND regime
        
        Returns:
            Dict with entry record details
        """
        entry_epoch = _parse_timestamp(entry_ts) or _now_ts()
        
        # [BIG ALPHA] Check if this is a TRUE TREND position (H > 0.55)
        is_true_trend = False
        if position_data:
            is_true_trend = position_data.get("is_true_trend", False)
            if not is_true_trend:
                # Check hurst_regime_at_entry directly
                hurst_regime = position_data.get("hurst_regime_at_entry", "unknown")
                hurst_value = position_data.get("hurst_value_at_entry", 0.5)
                is_true_trend = (hurst_regime == "trending" and hurst_value > 0.55)
        
        # [BIG ALPHA] Force 45-minute minimum hold for TRUE TREND positions
        if is_true_trend:
            min_hold = 45 * 60  # 45 minutes = 2700 seconds
            _log(f"🔒 [TRUE-TREND] Force-hold enabled for {symbol} {side}: 45min minimum (Hurst regime detected)")
        else:
            min_hold = self.get_minimum_hold(symbol, side)
        
        min_exit_ts = entry_epoch + min_hold
        
        record = {
            "position_id": position_id,
            "symbol": symbol,
            "side": side.upper(),
            "entry_ts": entry_epoch,
            "entry_iso": datetime.utcfromtimestamp(entry_epoch).isoformat() + "Z",
            "min_hold_seconds": min_hold,
            "min_exit_ts": min_exit_ts,
            "min_exit_iso": datetime.utcfromtimestamp(min_exit_ts).isoformat() + "Z",
            "recorded_at": _now(),
            "is_true_trend": is_true_trend,  # [BIG ALPHA] Track TRUE TREND status
        }
        
        self.active_positions[position_id] = record
        self.save_policy()
        
        hold_minutes = min_hold / 60
        _log(f"Recorded entry: {symbol} {side} (min hold: {hold_minutes:.1f}min until {record['min_exit_iso']})")
        
        return record
    
    def can_exit(
        self, 
        position_id: str, 
        current_ts=None, 
        exit_reason: Optional[str] = None,
        unrealized_pnl_pct: Optional[float] = None,
        drawdown_pct: Optional[float] = None
    ) -> Dict:
        """
        Check if a position can be exited based on hold time rules.
        
        Args:
            position_id: Unique identifier for the position
            current_ts: Current timestamp (default: now)
            exit_reason: Reason for exit (may trigger override)
            unrealized_pnl_pct: Unrealized P&L percentage (negative = loss)
            drawdown_pct: Portfolio drawdown percentage
        
        Returns:
            Dict with:
                - allow: bool - whether exit is allowed
                - block: bool - whether exit is blocked
                - min_hold_remaining: seconds until minimum hold is met
                - reason: explanation of decision
                - override_used: bool - whether override was triggered
        
        Note (Resilience Patch): If drawdown > 1.5% OR unrealized loss > 2%,
        the hold time constraint is bypassed to prevent deadlock situations
        where the bot can't free up position slots during market stress.
        """
        current_epoch = _parse_timestamp(current_ts) if current_ts else _now_ts()
        
        position = self.active_positions.get(position_id)
        
        if position is None:
            return {
                "allow": True,
                "block": False,
                "min_hold_remaining": 0,
                "reason": "position_not_tracked",
                "override_used": False,
            }
        
        entry_ts = position.get("entry_ts", 0)
        min_hold = position.get("min_hold_seconds", 300)
        min_exit_ts = position.get("min_exit_ts", entry_ts + min_hold)
        
        hold_elapsed = current_epoch - entry_ts
        hold_remaining = max(0, min_exit_ts - current_epoch)
        
        override_triggered = False
        override_source = None
        
        # =========================================================
        # RESILIENCE PATCH: Hold Time Deadlock Breaker
        # =========================================================
        # If portfolio is in distress, allow early exits to free slots
        # Auto-compute metrics if not provided by caller
        if drawdown_pct is None:
            drawdown_pct = _get_portfolio_drawdown()
        if unrealized_pnl_pct is None:
            unrealized_pnl_pct = _get_position_unrealized_pnl_pct(position_id)
        
        if drawdown_pct is not None and drawdown_pct > DRAWDOWN_OVERRIDE_THRESHOLD:
            override_triggered = True
            override_source = f"drawdown_override:{drawdown_pct:.2%}"
            _log(f"🔓 Drawdown override: {drawdown_pct:.2%} > {DRAWDOWN_OVERRIDE_THRESHOLD:.2%} threshold")
        
        if unrealized_pnl_pct is not None and unrealized_pnl_pct < -LOSS_OVERRIDE_THRESHOLD:
            override_triggered = True
            override_source = f"loss_override:{unrealized_pnl_pct:.2%}"
            _log(f"🔓 Loss override: {unrealized_pnl_pct:.2%} exceeds -{LOSS_OVERRIDE_THRESHOLD:.2%} threshold")
        
        # Check explicit exit reason
        if exit_reason and not override_triggered:
            exit_reason_lower = exit_reason.lower().replace("-", "_").replace(" ", "_")
            for override in OVERRIDE_REASONS:
                if override in exit_reason_lower:
                    override_triggered = True
                    override_source = exit_reason
                    break
        
        if override_triggered:
            self.enforcement_stats["overrides"] += 1
            decision = {
                "allow": True,
                "block": False,
                "min_hold_remaining": hold_remaining,
                "reason": f"override_allowed:{override_source or exit_reason}",
                "override_used": True,
                "hold_elapsed": hold_elapsed,
                "min_hold": min_hold,
            }
            _log(f"✅ Override exit: {position['symbol']} ({override_source or exit_reason}) after {hold_elapsed:.0f}s")
        
        elif hold_remaining <= 0:
            self.enforcement_stats["allows"] += 1
            decision = {
                "allow": True,
                "block": False,
                "min_hold_remaining": 0,
                "reason": "min_hold_met",
                "override_used": False,
                "hold_elapsed": hold_elapsed,
                "min_hold": min_hold,
            }
            _log(f"✅ Min hold met: {position['symbol']} after {hold_elapsed:.0f}s (required: {min_hold}s)")
        
        else:
            self.enforcement_stats["blocks"] += 1
            decision = {
                "allow": False,
                "block": True,
                "min_hold_remaining": hold_remaining,
                "reason": f"hold_time_not_met:need_{hold_remaining:.0f}s_more",
                "override_used": False,
                "hold_elapsed": hold_elapsed,
                "min_hold": min_hold,
            }
            _log(f"🚫 Hold blocked: {position['symbol']} needs {hold_remaining:.0f}s more (held: {hold_elapsed:.0f}s)")
        
        self.log_enforcement(position_id, decision, {
            "symbol": position.get("symbol"),
            "side": position.get("side"),
            "exit_reason": exit_reason,
            "unrealized_pnl_pct": unrealized_pnl_pct,
            "drawdown_pct": drawdown_pct,
        })
        
        return decision
    
    def get_minimum_hold(self, symbol: str, direction: Optional[str] = None) -> int:
        """
        Get minimum hold time in seconds for a symbol/direction.
        
        Args:
            symbol: Trading pair (e.g., BTCUSDT)
            direction: LONG or SHORT (optional, for direction-specific holds)
        
        Returns:
            Minimum hold time in seconds
        """
        dir_key = f"{symbol}_{direction.upper()}" if direction else None
        if dir_key and dir_key in self.direction_hold_times:
            return self.direction_hold_times[dir_key]
        
        if symbol in self.symbol_hold_times:
            return self.symbol_hold_times[symbol]
        
        tier = _get_symbol_tier(symbol)
        return self.policy.get("tier_defaults", DEFAULT_HOLD_BY_TIER).get(tier, 300)
    
    def update_policy_from_data(self) -> Dict:
        """
        Learn optimal hold times from historical trade data.
        
        Analyzes closed positions to find:
        - Hold durations that are profitable vs. unprofitable
        - Symbol-specific optimal hold times
        - Direction-specific adjustments
        
        Returns:
            Dict with learning results
        """
        positions_data = _read_json(POSITIONS_PATH, {"closed_positions": []})
        closed = positions_data.get("closed_positions", [])
        
        if not closed:
            _log("No closed positions to learn from")
            return {"status": "no_data", "trades_analyzed": 0}
        
        symbol_stats: Dict[str, Dict] = {}
        direction_stats: Dict[str, Dict] = {}
        
        def get_symbol_stats(sym: str) -> Dict:
            if sym not in symbol_stats:
                symbol_stats[sym] = {
                    "quick_trades": [],
                    "medium_trades": [],
                    "long_trades": [],
                    "total_pnl": 0.0,
                }
            return symbol_stats[sym]
        
        def get_direction_stats(key: str) -> Dict:
            if key not in direction_stats:
                direction_stats[key] = {
                    "quick_pnl": 0.0,
                    "medium_pnl": 0.0,
                    "long_pnl": 0.0,
                    "quick_count": 0,
                    "medium_count": 0,
                    "long_count": 0,
                }
            return direction_stats[key]
        
        for pos in closed:
            symbol = pos.get("symbol", "UNKNOWN")
            direction = pos.get("direction", "UNKNOWN")
            pnl = pos.get("net_pnl") or pos.get("pnl", 0)
            
            opened_at = _parse_timestamp(pos.get("opened_at"))
            closed_at = _parse_timestamp(pos.get("closed_at"))
            
            if not opened_at or not closed_at:
                continue
            
            hold_seconds = closed_at - opened_at
            
            if hold_seconds < 300:
                bucket = "quick"
            elif hold_seconds < 3600:
                bucket = "medium"
            else:
                bucket = "long"
            
            sym_stats = get_symbol_stats(symbol)
            sym_stats[f"{bucket}_trades"].append({
                "hold": hold_seconds,
                "pnl": pnl,
                "direction": direction,
            })
            sym_stats["total_pnl"] += pnl
            
            dir_key = f"{symbol}_{direction}"
            dir_stats = get_direction_stats(dir_key)
            dir_stats[f"{bucket}_pnl"] += pnl
            dir_stats[f"{bucket}_count"] += 1
        
        adjustments = {}
        
        for symbol, stats in symbol_stats.items():
            quick_trades = stats["quick_trades"]
            medium_trades = stats["medium_trades"]
            
            quick_pnl = sum(t["pnl"] for t in quick_trades)
            medium_pnl = sum(t["pnl"] for t in medium_trades)
            
            quick_count = len(quick_trades)
            medium_count = len(medium_trades)
            
            current_hold = self.get_minimum_hold(symbol)
            new_hold = current_hold
            
            if quick_count >= 3 and medium_count >= 3:
                quick_avg = quick_pnl / quick_count
                medium_avg = medium_pnl / medium_count
                
                if medium_avg > quick_avg * 1.5 and quick_avg < 0:
                    new_hold = min(900, current_hold + 120)
                    reason = "medium_beats_quick_significantly"
                elif quick_avg > medium_avg and quick_avg > 0:
                    new_hold = max(180, current_hold - 60)
                    reason = "quick_trades_profitable"
                else:
                    reason = "no_change_needed"
                
                if new_hold != current_hold:
                    adjustments[symbol] = {
                        "old_hold": current_hold,
                        "new_hold": new_hold,
                        "reason": reason,
                        "quick_avg_pnl": quick_avg,
                        "medium_avg_pnl": medium_avg,
                    }
                    self.symbol_hold_times[symbol] = new_hold
                    _log(f"Adjusted {symbol}: {current_hold}s -> {new_hold}s ({reason})")
        
        for dir_key, stats in direction_stats.items():
            if "_" not in dir_key:
                continue
            
            symbol, direction = dir_key.rsplit("_", 1)
            
            quick_avg = stats["quick_pnl"] / max(1, stats["quick_count"])
            medium_avg = stats["medium_pnl"] / max(1, stats["medium_count"])
            
            if stats["quick_count"] >= 5 and quick_avg < -1.0:
                base_hold = self.get_minimum_hold(symbol)
                dir_hold = int(base_hold * 1.2)
                self.direction_hold_times[dir_key] = dir_hold
                _log(f"Direction adjustment: {dir_key} -> {dir_hold}s (quick trades losing)")
        
        self.policy["learned_adjustments"] = adjustments
        self.policy["last_learning_at"] = _now()
        self.policy["trades_analyzed"] = len(closed)
        self.save_policy()
        
        result = {
            "status": "success",
            "trades_analyzed": len(closed),
            "symbols_analyzed": len(symbol_stats),
            "adjustments_made": len(adjustments),
            "adjustments": adjustments,
        }
        
        _log(f"Learning complete: analyzed {len(closed)} trades, made {len(adjustments)} adjustments")
        
        return result
    
    def log_enforcement(self, position_id: str, decision: Dict, context: Optional[Dict] = None):
        """
        Log enforcement decision to JSONL log.
        
        Args:
            position_id: Position identifier
            decision: The can_exit decision dict
            context: Additional context (symbol, side, etc.)
        """
        record = {
            "position_id": position_id,
            "decision": decision,
            "context": context or {},
            "stats_snapshot": dict(self.enforcement_stats),
        }
        
        _append_jsonl(HOLD_TIME_LOG_PATH, record)
    
    def clear_position(self, position_id: str):
        """Remove a position from active tracking after it's closed."""
        if position_id in self.active_positions:
            del self.active_positions[position_id]
            self.save_policy()
            _log(f"Cleared position: {position_id}")
    
    def check_exit_guard(self, symbol: str, side: str, entry_time, 
                          current_pnl: float = 0, reason: str = None) -> Dict:
        """
        Check if an exit should be blocked based on hold time rules.
        
        This is the primary interface for position_manager.py to check
        whether an exit is allowed based on minimum hold times.
        
        Args:
            symbol: Trading pair (e.g., BTCUSDT)
            side: LONG or SHORT
            entry_time: Entry timestamp (datetime or string)
            current_pnl: Current P&L of the position
            reason: Reason for the exit attempt
        
        Returns:
            Dict with:
                - blocked: bool - whether exit should be blocked
                - allow: bool - whether exit is allowed
                - message: str - explanation of decision
                - hold_elapsed: float - seconds held so far
                - min_hold: int - minimum required hold time
                - remaining: float - seconds remaining before exit allowed
        """
        import time
        from datetime import datetime
        
        # Parse entry time to epoch
        # ZOMBIE POSITION FIX: If entry_time is None/missing, assume position
        # has been held for a long time (1 hour ago) to allow immediate exit.
        # This prevents "immortal" zombie positions with corrupted timestamps.
        if entry_time is None:
            entry_epoch = time.time() - 3600  # 1 hour ago - allows immediate exit
            _log(f"⚠️ Null entry_time for {symbol} - treating as zombie position (1h+ held)")
        elif isinstance(entry_time, datetime):
            entry_epoch = entry_time.timestamp()
        elif isinstance(entry_time, str):
            entry_epoch = _parse_timestamp(entry_time) or (time.time() - 3600)
        elif isinstance(entry_time, (int, float)):
            entry_epoch = float(entry_time) if entry_time > 0 else (time.time() - 3600)
        else:
            entry_epoch = time.time() - 3600  # Unknown type - allow exit
        
        current_epoch = time.time()
        hold_elapsed = current_epoch - entry_epoch
        min_hold = self.get_minimum_hold(symbol, side)
        remaining = max(0, min_hold - hold_elapsed)
        
        # Check for override reasons (emergency exits)
        if reason:
            reason_lower = reason.lower().replace("-", "_").replace(" ", "_")
            for override in OVERRIDE_REASONS:
                if override in reason_lower:
                    self.enforcement_stats["overrides"] += 1
                    _log(f"✅ Override exit allowed: {symbol} {side} ({reason}) after {hold_elapsed:.0f}s")
                    return {
                        "blocked": False,
                        "allow": True,
                        "message": f"Override allowed: {reason}",
                        "hold_elapsed": hold_elapsed,
                        "min_hold": min_hold,
                        "remaining": 0,
                    }
        
        # Check if minimum hold time is met
        if remaining <= 0:
            self.enforcement_stats["allows"] += 1
            _log(f"✅ Hold time met: {symbol} {side} after {hold_elapsed:.0f}s (required: {min_hold}s)")
            return {
                "blocked": False,
                "allow": True,
                "message": f"Minimum hold time met ({hold_elapsed:.0f}s >= {min_hold}s)",
                "hold_elapsed": hold_elapsed,
                "min_hold": min_hold,
                "remaining": 0,
            }
        else:
            self.enforcement_stats["blocks"] += 1
            _log(f"🚫 Exit blocked: {symbol} {side} needs {remaining:.0f}s more (held: {hold_elapsed:.0f}s, need: {min_hold}s)")
            return {
                "blocked": True,
                "allow": False,
                "message": f"Need {remaining:.0f}s more (held {hold_elapsed:.0f}s of {min_hold}s required)",
                "hold_elapsed": hold_elapsed,
                "min_hold": min_hold,
                "remaining": remaining,
            }
    
    def get_status(self) -> Dict:
        """Get current enforcement status and statistics."""
        return {
            "active_positions": len(self.active_positions),
            "symbol_hold_times": len(self.symbol_hold_times),
            "direction_adjustments": len(self.direction_hold_times),
            "stats": dict(self.enforcement_stats),
            "last_updated": self.policy.get("updated_at"),
            "last_learning": self.policy.get("last_learning_at"),
            "trades_analyzed": self.policy.get("trades_analyzed", 0),
        }
    
    def get_active_holds(self) -> List[Dict]:
        """Get list of active positions with their hold status."""
        current_ts = _now_ts()
        holds = []
        
        for pos_id, pos in self.active_positions.items():
            entry_ts = pos.get("entry_ts", 0)
            min_exit_ts = pos.get("min_exit_ts", entry_ts + 300)
            hold_elapsed = current_ts - entry_ts
            hold_remaining = max(0, min_exit_ts - current_ts)
            
            holds.append({
                "position_id": pos_id,
                "symbol": pos.get("symbol"),
                "side": pos.get("side"),
                "hold_elapsed": hold_elapsed,
                "hold_remaining": hold_remaining,
                "can_exit_at": pos.get("min_exit_iso"),
                "status": "holdable" if hold_remaining <= 0 else "holding",
            })
        
        return holds


_enforcer_instance = None


def get_hold_time_enforcer() -> HoldTimeEnforcer:
    """Get singleton instance of HoldTimeEnforcer."""
    global _enforcer_instance
    if _enforcer_instance is None:
        _enforcer_instance = HoldTimeEnforcer()
    return _enforcer_instance


if __name__ == "__main__":
    enforcer = HoldTimeEnforcer()
    
    print("\n" + "="*60)
    print("HOLD TIME ENFORCER - Status")
    print("="*60)
    
    status = enforcer.get_status()
    print(f"\nActive positions: {status['active_positions']}")
    print(f"Symbol hold times configured: {status['symbol_hold_times']}")
    print(f"Enforcement stats: {status['stats']}")
    
    print("\n" + "="*60)
    print("Running policy learning from historical data...")
    print("="*60)
    
    result = enforcer.update_policy_from_data()
    print(f"\nLearning result: {result['status']}")
    print(f"Trades analyzed: {result['trades_analyzed']}")
    print(f"Adjustments made: {result['adjustments_made']}")
    
    if result.get('adjustments'):
        print("\nAdjustments:")
        for symbol, adj in result['adjustments'].items():
            print(f"  {symbol}: {adj['old_hold']}s -> {adj['new_hold']}s ({adj['reason']})")
    
    print("\n" + "="*60)
    print("Current Hold Time Settings")
    print("="*60)
    for symbol in sorted(enforcer.symbol_hold_times.keys()):
        hold = enforcer.symbol_hold_times[symbol]
        print(f"  {symbol}: {hold}s ({hold/60:.1f}m)")
