"""
Futures Signal Generation: EMA crossover signals for leveraged trading.
Integrates with protective mode gating and pre-trade validation.
"""
import time
import json
import pandas as pd
from pathlib import Path
from typing import Dict, Any, Optional, Tuple
from datetime import datetime


LOGS = Path("logs")
CONFIGS = Path("configs")


def load_json(path: Path, fallback=None):
    """Load JSON file with fallback."""
    try:
        with open(path, "r") as f:
            return json.load(f)
    except:
        return fallback if fallback is not None else {}


def save_json(path: Path, data: Dict[str, Any]):
    """Save data to JSON file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        json.dump(data, f, indent=2)


def ema(prices: pd.Series, span: int) -> pd.Series:
    """Calculate exponential moving average."""
    return prices.ewm(span=span, adjust=False).mean()


def ema_crossover(prices: pd.Series, short_span: int = 12, long_span: int = 26) -> Tuple[str, str]:
    """
    Calculate EMA crossover signals.
    
    Returns:
        Tuple of (latest_state, prev_state) where state is "LONG" or "SHORT"
    """
    if len(prices) < long_span + 2:
        return "HOLD", "HOLD"
    
    short_ema = ema(prices, short_span)
    long_ema = ema(prices, long_span)
    
    latest_state = "LONG" if short_ema.iloc[-1] > long_ema.iloc[-1] else "SHORT"
    prev_state = "LONG" if short_ema.iloc[-2] > long_ema.iloc[-2] else "SHORT"
    
    return latest_state, prev_state


def generate_futures_signal(symbol: str, prices: pd.Series, strategy: str = "EMA", 
                            regime: str = "trending") -> Dict[str, Any]:
    """
    Generate trading signal based on EMA crossover.
    
    Args:
        symbol: Trading symbol
        prices: Price series
        strategy: Strategy name
        regime: Market regime
    
    Returns:
        Signal dict with action, symbol, strategy, regime, state
    """
    latest, prev = ema_crossover(prices)
    
    signal = None
    if latest == "LONG" and prev == "SHORT":
        signal = {
            "action": "OPEN_LONG",
            "symbol": symbol,
            "strategy": strategy,
            "regime": regime,
            "state": latest,
            "crossover": "bullish"
        }
    
    elif latest == "SHORT" and prev == "LONG":
        signal = {
            "action": "OPEN_SHORT",
            "symbol": symbol,
            "strategy": strategy,
            "regime": regime,
            "state": latest,
            "crossover": "bearish"
        }
    
    else:
        signal = {
            "action": "HOLD",
            "symbol": symbol,
            "strategy": strategy,
            "regime": regime,
            "state": latest,
            "crossover": None
        }
    
    # V6.6 Signal Inversion: Conditionally flips SHORT→LONG in range/chop markets
    try:
        from src.full_integration_blofin_micro_live_and_paper import adjust_and_propagate_signal
        # Build raw signal dict for V6.6 overlay
        raw_signal = {
            "ts": int(time.time()),
            "price_ts": int(time.time()),
            "symbol": symbol,
            "side": "LONG" if signal["action"] == "OPEN_LONG" else "SHORT" if signal["action"] == "OPEN_SHORT" else "HOLD",
            "strength": 0.5,  # Default strength
            "regime": regime,
            "verdict_status": "Neutral"  # Will be set by caller if available
        }
        adjusted = adjust_and_propagate_signal(raw_signal)
        # Apply adjustments back to signal
        if adjusted.get("side") != raw_signal["side"]:
            signal["action"] = "OPEN_LONG" if adjusted["side"] == "LONG" else "OPEN_SHORT"
            signal["state"] = adjusted["side"]
            signal["v66_inverted"] = True
    except Exception as e:
        pass
    
    return signal


def load_leverage_cap(symbol: str, strategy: str, regime: str) -> int:
    """
    Load leverage cap from configuration.
    
    Args:
        symbol: Trading symbol
        strategy: Strategy name
        regime: Market regime
    
    Returns:
        Leverage cap (1-10x)
    """
    budgets = load_json(CONFIGS / "leverage_budgets.json", {"proposals": []})
    
    for proposal in budgets.get("proposals", []):
        if (proposal.get("symbol") == symbol and 
            proposal.get("strategy") == strategy and 
            proposal.get("regime") == regime):
            return int(round(float(proposal.get("proposed_leverage", 2))))
    
    defaults = load_json(CONFIGS / "leverage_defaults.json", {"max_leverage": 2})
    return int(defaults.get("max_leverage", 2))


def compute_futures_qty(symbol: str, mark_price: float, leverage: int, 
                       margin_budget_usdt: float) -> float:
    """
    Compute position quantity for futures trade.
    
    Formula: qty = (margin_budget * leverage) / mark_price
    
    Args:
        symbol: Trading symbol
        mark_price: Current mark price
        leverage: Leverage multiplier
        margin_budget_usdt: Margin budget in USDT
    
    Returns:
        Position quantity
    """
    if mark_price <= 0 or leverage <= 0 or margin_budget_usdt <= 0:
        return 0.0
    
    return round((margin_budget_usdt * leverage) / mark_price, 6)


def should_allow_futures_entry(protective_mode: str, symbol: str, 
                               last_trade_ts: Dict[str, float], 
                               cooldown_seconds: int = 60) -> Tuple[bool, str]:
    """
    Pre-trade validation for futures entries.
    
    Args:
        protective_mode: Current protective mode (OFF/ALERT/BLOCK/REDUCE)
        symbol: Trading symbol
        last_trade_ts: Dict of symbol -> last trade timestamp
        cooldown_seconds: Minimum seconds between trades
    
    Returns:
        Tuple of (allowed, reason)
    """
    if protective_mode in ("BLOCK", "REDUCE"):
        return False, f"protective_mode:{protective_mode}"
    
    last_ts = last_trade_ts.get(symbol, 0)
    if time.time() - last_ts < cooldown_seconds:
        seconds_left = round(cooldown_seconds - (time.time() - last_ts), 1)
        return False, f"cooldown:{seconds_left}s_remaining"
    
    return True, "ok"


def log_futures_signal_evaluation(symbol: str, signal: Dict[str, Any], 
                                  allowed: bool, reason: str, 
                                  leverage: int = None, qty: float = None):
    """
    Log signal evaluation for dashboard display.
    
    Args:
        symbol: Trading symbol
        signal: Signal dict
        allowed: Whether entry was allowed
        reason: Reason for decision
        leverage: Leverage used (if applicable)
        qty: Quantity (if applicable)
    """
    log_file = LOGS / "futures_signal_evaluations.json"
    
    try:
        history = load_json(log_file, {"evaluations": []})
        
        entry = {
            "timestamp": datetime.utcnow().isoformat(),
            "symbol": symbol,
            "action": signal.get("action"),
            "state": signal.get("state"),
            "crossover": signal.get("crossover"),
            "allowed": allowed,
            "reason": reason,
            "leverage": leverage,
            "qty": qty
        }
        
        evaluations = history.get("evaluations", [])
        evaluations.append(entry)
        
        evaluations = evaluations[-50:]
        
        save_json(log_file, {"evaluations": evaluations, "last_updated": entry["timestamp"]})
        
    except Exception as e:
        print(f"⚠️ Failed to log signal evaluation: {e}")
