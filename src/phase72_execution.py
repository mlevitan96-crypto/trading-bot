"""
Phase 7.2 - Execution Relaxation & Strategy Discipline (Tier-Based)
Per-symbol SHORT suppression, minimum hold enforcement, fee-netted P&L
"""
import time
import json
import os
from typing import Dict, List, Optional, Tuple
from datetime import datetime
from src.phase72_config import get_phase72_config
from src.phase72_tiers import tier_for_symbol
from src.phase72_fees import net_realized_pnl, net_unrealized_pnl


def get_rolling_shorts_stats_symbol(symbol: str, window: int = 30) -> Tuple[float, float, int]:
    """
    Get rolling SHORT performance stats for a specific symbol.
    
    Args:
        symbol: Trading pair (e.g., "BTCUSDT")
        window: Rolling window size
        
    Returns:
        (win_rate, total_pnl, trade_count)
    """
    try:
        with open('logs/trades_futures.json', 'r') as f:
            data = json.load(f)
            trades = data.get('trades', [])
        
        # Filter to SHORT trades for this symbol
        short_trades = [
            t for t in trades
            if t.get('symbol') == symbol and t.get('direction') == 'SHORT'
        ]
        
        if not short_trades:
            return 0.0, 0.0, 0
        
        # Get last N trades
        recent = short_trades[-window:] if len(short_trades) >= window else short_trades
        
        wins = len([t for t in recent if t.get('net_pnl', 0) > 0])
        total_pnl = sum(t.get('net_pnl', 0) for t in recent)
        win_rate = wins / len(recent) if recent else 0.0
        
        return win_rate, total_pnl, len(recent)
        
    except FileNotFoundError:
        return 0.0, 0.0, 0
    except Exception as e:
        print(f"⚠️  Error getting SHORT stats for {symbol}: {e}")
        return 0.0, 0.0, 0


def short_allowed(symbol: str) -> Tuple[bool, str]:
    """
    Check if SHORT trades are allowed for this symbol.
    
    Per-symbol rolling attribution check.
    
    Args:
        symbol: Trading pair
        
    Returns:
        (allowed, reason)
    """
    config = get_phase72_config()
    
    if not config.suppress_shorts_until_profitable:
        return True, ""
    
    wr, pnl, n = get_rolling_shorts_stats_symbol(symbol, config.shorts_window_trades)
    
    if n < config.shorts_window_trades:
        return False, f"insufficient_data:n={n}<{config.shorts_window_trades}"
    
    if pnl < config.shorts_min_pnl_usd:
        return False, f"unprofitable:pnl=${pnl:.2f}<${config.shorts_min_pnl_usd:.2f}"
    
    if wr < config.shorts_min_wr:
        return False, f"low_wr:{wr*100:.1f}%<{config.shorts_min_wr*100:.0f}%"
    
    return True, "profitable"


def relaxed_threshold(symbol: str, regime_name: str) -> float:
    """
    Get relaxed ensemble threshold for symbol in current regime.
    
    Args:
        symbol: Trading pair
        regime_name: Current market regime ("Stable", "Trending", etc.)
        
    Returns:
        Adjusted ensemble threshold
    """
    config = get_phase72_config()
    tier = tier_for_symbol(symbol)
    return config.get_ensemble_threshold(tier, regime_name)


def pre_entry_gate(symbol: str, side: str, ensemble_score: float, regime_name: str) -> Tuple[bool, str, Dict]:
    """
    Phase 7.2 pre-entry gate with tier-based relaxation and SHORT suppression.
    
    Args:
        symbol: Trading pair
        side: "LONG" or "SHORT"
        ensemble_score: Signal ensemble confidence score
        regime_name: Current market regime
        
    Returns:
        (allowed, reason, audit_data)
    """
    config = get_phase72_config()
    
    if not config.enabled:
        return True, "", {}
    
    tier = tier_for_symbol(symbol)
    threshold = relaxed_threshold(symbol, regime_name)
    
    audit = {
        "symbol": symbol,
        "tier": tier,
        "regime": regime_name,
        "ensemble_score": ensemble_score,
        "threshold": threshold,
        "side": side
    }
    
    # Check ensemble score
    if ensemble_score < threshold:
        return False, f"low_ensemble:{ensemble_score:.3f}<{threshold:.3f}", audit
    
    # Check SHORT suppression
    if side.upper() == "SHORT":
        allowed, short_reason = short_allowed(symbol)
        if not allowed:
            audit["short_suppression"] = short_reason
            return False, f"short_suppressed:{short_reason}", audit
    
    return True, "passed", audit


def enforce_min_hold_on_exit(position: Dict) -> Tuple[bool, str]:
    """
    Check if position has been held long enough to exit.
    
    Args:
        position: Position dict with entry_time
        
    Returns:
        (can_exit, reason)
    """
    config = get_phase72_config()
    
    entry_ts = position.get('entry_time')
    if not entry_ts:
        return True, "no_entry_time"
    
    try:
        if isinstance(entry_ts, str):
            entry_time = datetime.fromisoformat(entry_ts.replace('Z', '+00:00'))
            entry_epoch = entry_time.timestamp()
        else:
            entry_epoch = entry_ts
        
        held = time.time() - entry_epoch
        
        if held < config.min_hold_seconds:
            # Allow protective exits (margin safety, stop loss)
            if config.min_hold_allow_protective_exit:
                return True, f"protective_exit_allowed:held_{held:.0f}s"
            return False, f"min_hold_not_met:{held:.0f}s<{config.min_hold_seconds}s"
        
        return True, f"held_{held:.0f}s"
        
    except Exception as e:
        print(f"⚠️  Min hold check error: {e}")
        return True, f"error:{str(e)}"


def get_futures_margin_budget(portfolio_value: float) -> float:
    """
    Calculate futures margin budget with ratcheting.
    
    Starts at 6%, ratchets to 10% when futures are profitable.
    
    Args:
        portfolio_value: Total portfolio value
        
    Returns:
        Futures margin budget in USD
    """
    config = get_phase72_config()
    
    base_margin = portfolio_value * config.futures_margin_pct
    
    if not config.futures_margin_ratchet_enabled:
        return base_margin
    
    # Check if futures are profitable
    try:
        # Use canonical positions file (not trades_futures.json which may have stale data)
        from src.data_registry import DataRegistry as DR
        with open(DR.POSITIONS_FUTURES, 'r') as f:
            data = json.load(f)
            closed = data.get('closed_positions', [])
        
        if not closed:
            return base_margin
        
        # Calculate total futures P&L from closed positions
        total_pnl = sum(p.get('pnl', p.get('net_pnl', 0)) or 0 for p in closed if isinstance(p.get('pnl', p.get('net_pnl', 0)), (int, float)))
        
        if total_pnl > 0:
            # Ratchet to max
            ratcheted_margin = portfolio_value * config.futures_margin_max_pct
            print(f"   🎯 Futures profitable (+${total_pnl:.2f}), ratcheting margin: ${base_margin:.2f} → ${ratcheted_margin:.2f}")
            return ratcheted_margin
        
        return base_margin
        
    except FileNotFoundError:
        return base_margin
    except Exception as e:
        print(f"⚠️  Margin ratchet error: {e}")
        return base_margin


def apply_phase72_filters(
    symbol: str,
    side: str,
    ensemble_score: float,
    regime: str,
    portfolio_value: float,
    strategy_budget: float,
    available_budget: float,
    position_size_requested: float,
    correlation_cap: float,
    correlation_exposure: float,
    open_positions_count: int,
    total_exposure: float
) -> Tuple[bool, str, Dict]:
    """
    Apply all Phase 7.2 filters to a signal.
    
    Returns:
        (execute, rejection_reason, audit_data)
    """
    allowed, reason, audit = pre_entry_gate(symbol, side, ensemble_score, regime)
    
    if not allowed:
        from src.phase72_execution_diagnostics import log_signal_evaluation
        log_signal_evaluation(
            symbol=symbol,
            strategy="Phase72",
            regime=regime,
            side=side,
            ensemble_score=ensemble_score,
            ensemble_threshold=relaxed_threshold(symbol, regime),
            portfolio_value=portfolio_value,
            strategy_budget=strategy_budget,
            available_budget=available_budget,
            position_size_requested=position_size_requested,
            correlation_cap=correlation_cap,
            correlation_exposure=correlation_exposure,
            open_positions_count=open_positions_count,
            total_exposure=total_exposure,
            executed=False,
            rejection_reasons=[reason]
        )
        return False, reason, audit
    
    return True, "", audit


# Backward compatibility exports
def should_suppress_short(symbol: str, direction: str) -> Tuple[bool, str]:
    """Legacy interface for SHORT suppression."""
    if direction.upper() != "SHORT":
        return False, ""
    
    allowed, reason = short_allowed(symbol)
    return not allowed, reason


def check_min_hold_time(position: Dict, allow_protective_exit: bool = True) -> Tuple[bool, str]:
    """Legacy interface for minimum hold check."""
    return enforce_min_hold_on_exit(position)


def get_adjusted_ensemble_threshold(regime: str, symbol: str = "BTCUSDT") -> float:
    """Legacy interface for threshold calculation."""
    return relaxed_threshold(symbol, regime)
