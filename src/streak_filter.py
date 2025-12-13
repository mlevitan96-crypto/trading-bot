#!/usr/bin/env python3
"""
Streak Filter Module - Momentum-Based Trade Gating

Based on backtest analysis showing:
- After WIN: 54.8% WR, +$1.02
- After LOSS: 11.5% WR, -$1,848

This module implements streak-aware trading to avoid cascading losses.

Key Features:
1. Track consecutive wins/losses
2. Gate trades based on streak state
3. Optional: Inverse mode for after-loss trades
4. Cooldown period after loss streaks
"""

import json
import time
from pathlib import Path
from datetime import datetime, timedelta
from typing import Dict, Tuple, Optional
from src.file_locks import locked_json_read, atomic_json_save

try:
    from src.health_to_learning_bridge import log_gate_decision, log_health_event
except ImportError:
    def log_gate_decision(*args, **kwargs): pass
    def log_health_event(*args, **kwargs): pass

STREAK_STATE_DIR = Path("state")
STREAK_LOG = Path("logs/streak_filter.log")

STREAK_STATE_DIR.mkdir(parents=True, exist_ok=True)
STREAK_LOG.parent.mkdir(parents=True, exist_ok=True)

AUTO_RESET_CONFIG = {
    "max_skips_before_reset": 100,
    "max_hours_blocked": 4,
    "reset_on_nightly": True,
}

def _get_streak_file(bot_type: str = "alpha") -> Path:
    """Get bot-specific streak state file."""
    return STREAK_STATE_DIR / f"streak_state_{bot_type}.json"

STREAK_STATE_FILE = _get_streak_file("alpha")

DEFAULT_STATE = {
    "last_trade_win": True,
    "consecutive_wins": 0,
    "consecutive_losses": 0,
    "total_wins": 0,
    "total_losses": 0,
    "last_update": None,
    "cooldown_until": None,
    "trades_skipped": 0,
    "trades_allowed": 0,
}


def _log(msg: str):
    """Thread-safe logging."""
    ts = datetime.utcnow().isoformat() + "Z"
    entry = f"[{ts}] {msg}"
    print(entry)
    try:
        with open(STREAK_LOG, 'a') as f:
            f.write(entry + '\n')
    except:
        pass


def load_streak_state(bot_type: str = "alpha") -> Dict:
    """Load current streak state from disk for specific bot type."""
    state_file = _get_streak_file(bot_type)
    try:
        if state_file.exists():
            state = locked_json_read(str(state_file))
            if state:
                return state
    except Exception as e:
        _log(f"Error loading streak state for {bot_type}: {e}")
    return DEFAULT_STATE.copy()


def save_streak_state(state: Dict, bot_type: str = "alpha"):
    """Save streak state to disk atomically for specific bot type."""
    state_file = _get_streak_file(bot_type)
    try:
        state["last_update"] = datetime.utcnow().isoformat() + "Z"
        atomic_json_save(str(state_file), state)
    except Exception as e:
        _log(f"Error saving streak state for {bot_type}: {e}")


def update_streak(won: bool, pnl: float = 0.0, symbol: str = "", bot_type: str = "alpha"):
    """
    Update streak state after a trade closes.
    Call this from position close logic.
    
    Args:
        won: True if trade was profitable
        pnl: Realized P&L
        symbol: Trading symbol
        bot_type: alpha or beta (uses separate state files)
    """
    state = load_streak_state(bot_type)
    
    if won:
        state["consecutive_wins"] += 1
        state["consecutive_losses"] = 0
        state["total_wins"] += 1
        state["last_trade_win"] = True
        state["cooldown_until"] = None
        _log(f"[{bot_type.upper()}] WIN streak: {state['consecutive_wins']} | {symbol} +${pnl:.2f}")
    else:
        state["consecutive_losses"] += 1
        state["consecutive_wins"] = 0
        state["total_losses"] += 1
        state["last_trade_win"] = False
        
        if state["consecutive_losses"] >= 3:
            cooldown_mins = min(30, state["consecutive_losses"] * 5)
            state["cooldown_until"] = (datetime.utcnow() + timedelta(minutes=cooldown_mins)).isoformat() + "Z"
            _log(f"[{bot_type.upper()}] LOSS streak: {state['consecutive_losses']} | {symbol} ${pnl:.2f} | COOLDOWN {cooldown_mins}min")
        else:
            _log(f"[{bot_type.upper()}] LOSS streak: {state['consecutive_losses']} | {symbol} ${pnl:.2f}")
    
    save_streak_state(state, bot_type)


def check_streak_gate(symbol: str = "", direction: str = "", bot_type: str = "alpha") -> Tuple[bool, str, float]:
    """
    Check if a new trade should be allowed based on streak state.
    
    DISABLED 2025-12-02: Streak filter was blocking ALL trades for 8+ hours.
    Now relies on position sizing, ML features, and other filters instead.
    
    Returns:
        Tuple of (allowed: bool, reason: str, sizing_multiplier: float)
    """
    state = load_streak_state(bot_type)
    cons_wins = state.get("consecutive_wins", 0)
    
    if cons_wins >= 3:
        mult = min(1.5, 1.0 + (cons_wins * 0.1))
        _log(f"[{bot_type.upper()}] STREAK-BOOST: {cons_wins} consecutive wins | {symbol} | mult={mult:.2f}")
        state["trades_allowed"] = state.get("trades_allowed", 0) + 1
        save_streak_state(state, bot_type)
        return True, f"hot_streak_{cons_wins}", mult
    
    state["trades_allowed"] = state.get("trades_allowed", 0) + 1
    save_streak_state(state, bot_type)
    _log(f"[{bot_type.upper()}] STREAK-PASS: Trading allowed | {symbol}")
    return True, "streak_disabled", 1.0


def get_streak_stats(bot_type: str = "alpha") -> Dict:
    """Get current streak statistics for dashboard."""
    state = load_streak_state(bot_type)
    
    total = state.get("total_wins", 0) + state.get("total_losses", 0)
    wr = state.get("total_wins", 0) / total * 100 if total > 0 else 0
    
    return {
        "bot_type": bot_type,
        "consecutive_wins": state.get("consecutive_wins", 0),
        "consecutive_losses": state.get("consecutive_losses", 0),
        "last_trade_win": state.get("last_trade_win", True),
        "total_win_rate": wr,
        "trades_skipped": state.get("trades_skipped", 0),
        "trades_allowed": state.get("trades_allowed", 0),
        "cooldown_active": bool(state.get("cooldown_until")),
    }


def reset_streak_state(bot_type: str = "alpha", reason: str = "manual"):
    """Reset streak state (for testing or manual intervention)."""
    save_streak_state(DEFAULT_STATE.copy(), bot_type)
    _log(f"[{bot_type.upper()}] STREAK-RESET: State cleared (reason: {reason})")
    log_health_event("streak_filter", "reset", {"bot_type": bot_type, "reason": reason})


def check_auto_reset_needed(bot_type: str = "alpha") -> Tuple[bool, str]:
    """
    Check if streak filter should auto-reset based on configured thresholds.
    
    Auto-reset triggers:
    1. Too many consecutive skips (default: 100)
    2. Blocked for too long (default: 4 hours)
    
    Returns:
        Tuple of (should_reset: bool, reason: str)
    """
    state = load_streak_state(bot_type)
    
    skips = state.get("trades_skipped", 0)
    if skips >= AUTO_RESET_CONFIG["max_skips_before_reset"]:
        return True, f"max_skips_exceeded_{skips}"
    
    last_update = state.get("last_update")
    if last_update and not state.get("last_trade_win", True):
        try:
            last_dt = datetime.fromisoformat(last_update.replace("Z", ""))
            hours_blocked = (datetime.utcnow() - last_dt).total_seconds() / 3600
            if hours_blocked >= AUTO_RESET_CONFIG["max_hours_blocked"]:
                return True, f"blocked_too_long_{hours_blocked:.1f}h"
        except:
            pass
    
    return False, "no_reset_needed"


def auto_reset_if_needed(bot_type: str = "alpha") -> bool:
    """
    Automatically reset streak state if thresholds are exceeded.
    Called during health checks and at trade gate evaluation.
    
    Returns:
        True if reset was performed
    """
    should_reset, reason = check_auto_reset_needed(bot_type)
    if should_reset:
        _log(f"[{bot_type.upper()}] AUTO-RESET TRIGGERED: {reason}")
        reset_streak_state(bot_type, reason=f"auto_{reason}")
        return True
    return False


def run_streak_health_check() -> Dict:
    """
    Run health check on streak filter for all bots.
    Called by learning health monitor.
    
    Returns:
        Health check result with auto-remediation status
    """
    results = {
        "healthy": True,
        "bots": {},
        "auto_resets": []
    }
    
    for bot_type in ["alpha", "beta"]:
        stats = get_streak_stats(bot_type)
        bot_healthy = True
        issues = []
        
        if stats["trades_skipped"] > 50:
            issues.append(f"High skip count: {stats['trades_skipped']}")
            bot_healthy = False
        
        if not stats["last_trade_win"] and stats["consecutive_losses"] == 0:
            state = load_streak_state(bot_type)
            last_update = state.get("last_update")
            if last_update:
                try:
                    last_dt = datetime.fromisoformat(last_update.replace("Z", ""))
                    hours_blocked = (datetime.utcnow() - last_dt).total_seconds() / 3600
                    if hours_blocked > 2:
                        issues.append(f"Blocked for {hours_blocked:.1f}h")
                        bot_healthy = False
                except:
                    pass
        
        if auto_reset_if_needed(bot_type):
            results["auto_resets"].append(bot_type)
            bot_healthy = True
            issues = ["Auto-reset applied"]
        
        results["bots"][bot_type] = {
            "healthy": bot_healthy,
            "stats": stats,
            "issues": issues
        }
        
        if not bot_healthy:
            results["healthy"] = False
    
    return results


def should_invert_after_loss(bot_type: str = "alpha") -> bool:
    """
    Check if we should consider inverting trade direction after loss.
    
    Based on analysis: 539 trades could benefit from inversion.
    This is experimental and should be validated.
    """
    state = load_streak_state(bot_type)
    
    if not state.get("last_trade_win", True):
        return True
    
    return False


_beta_last_entry = {}
BETA_COOLDOWN_FILE = Path("state/beta_cooldown.json")

def _load_beta_cooldowns() -> Dict:
    """Load Beta entry cooldowns from disk."""
    global _beta_last_entry
    try:
        if BETA_COOLDOWN_FILE.exists():
            data = locked_json_read(str(BETA_COOLDOWN_FILE))
            if data:
                _beta_last_entry = data
                return data
    except Exception as e:
        _log(f"Error loading beta cooldowns: {e}")
    return {}

def _save_beta_cooldowns():
    """Save Beta entry cooldowns to disk."""
    global _beta_last_entry
    try:
        atomic_json_save(str(BETA_COOLDOWN_FILE), _beta_last_entry)
    except Exception as e:
        _log(f"Error saving beta cooldowns: {e}")

_load_beta_cooldowns()

def check_beta_entry_allowed(symbol: str) -> Tuple[bool, str]:
    """
    Beta-specific preflight checks before opening a position.
    
    Returns:
        Tuple of (allowed: bool, reason: str)
    """
    global _beta_last_entry
    from src.position_manager import get_open_futures_positions
    
    all_positions = get_open_futures_positions()
    beta_positions = [p for p in all_positions if p.get("bot_type") == "beta"]
    
    _log(f"[BETA-PREFLIGHT] {symbol}: {len(beta_positions)} Beta positions open")
    
    if len(beta_positions) >= 10:
        _log(f"[BETA-PREFLIGHT] BLOCKED {symbol}: Position cap 10 reached ({len(beta_positions)} open)")
        return False, f"beta_position_cap_10"
    
    existing = [p for p in beta_positions if p.get("symbol") == symbol]
    if existing:
        _log(f"[BETA-PREFLIGHT] BLOCKED {symbol}: Already has open position")
        return False, "beta_already_has_position"
    
    last_ts = _beta_last_entry.get(symbol, 0)
    if time.time() - last_ts < 120:
        remaining = 120 - (time.time() - last_ts)
        _log(f"[BETA-PREFLIGHT] BLOCKED {symbol}: Cooldown active ({remaining:.0f}s remaining)")
        return False, f"beta_cooldown_{remaining:.0f}s"
    
    _log(f"[BETA-PREFLIGHT] ALLOWED {symbol}: All checks passed")
    return True, "beta_entry_allowed"


def record_beta_entry(symbol: str):
    """Record that Beta opened a position on this symbol."""
    global _beta_last_entry
    _beta_last_entry[symbol] = time.time()
    _save_beta_cooldowns()
    _log(f"[BETA-PREFLIGHT] Recorded entry for {symbol}, cooldown 120s")


if __name__ == "__main__":
    print("Streak Filter Status:")
    print("\n=== ALPHA Bot ===")
    print(json.dumps(get_streak_stats("alpha"), indent=2))
    print("\n=== BETA Bot ===")
    print(json.dumps(get_streak_stats("beta"), indent=2))
