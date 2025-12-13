"""
Phase 3 Funding Cost Model

Evaluates expected funding costs for futures positions.
Blocks positions with high funding costs unless attribution is strong.
"""

from typing import Dict, Optional
import json
from pathlib import Path
from datetime import datetime, timedelta


def estimate_funding_rate(symbol: str, position_side: str) -> float:
    """
    Estimate expected funding rate in bps per day.
    
    Args:
        symbol: Trading symbol
        position_side: "LONG" or "SHORT"
        
    Returns:
        Expected funding rate in bps/day (positive = cost, negative = earn)
    """
    funding_history_file = Path("logs/funding_history.json")
    
    if funding_history_file.exists():
        try:
            with open(funding_history_file) as f:
                history = json.load(f)
                
                symbol_data = history.get(symbol, {})
                recent_rates = symbol_data.get("recent_rates_bps", [])
                
                if recent_rates:
                    avg_rate = sum(recent_rates) / len(recent_rates)
                    
                    if position_side == "LONG":
                        return avg_rate
                    else:
                        return -avg_rate
        except Exception:
            pass
    
    avg_funding_bps = {
        "BTCUSDT": 2.0,
        "BTC-USDT": 2.0,
        "ETHUSDT": 2.5,
        "ETH-USDT": 2.5,
        "SOLUSDT": 3.0,
        "SOL-USDT": 3.0
    }
    
    base_rate = avg_funding_bps.get(symbol, 2.0)
    
    if position_side == "LONG":
        return base_rate
    else:
        return -base_rate


def funding_cost_ok(symbol: str, position_side: str, attribution_strength: float,
                   cost_cap_bps: float = 12.0, min_attribution_for_override: float = 0.30) -> bool:
    """
    Check if funding cost is acceptable.
    
    Args:
        symbol: Trading symbol
        position_side: "LONG" or "SHORT"
        attribution_strength: Maximum attribution strength for this symbol (0-1)
        cost_cap_bps: Maximum allowed funding cost in bps/day
        min_attribution_for_override: Attribution strength needed to override cost cap
        
    Returns:
        True if funding cost is acceptable
    """
    expected_cost = estimate_funding_rate(symbol, position_side)
    
    if expected_cost <= cost_cap_bps:
        return True
    
    if attribution_strength >= min_attribution_for_override:
        return True
    
    return False


def log_funding_decision(symbol: str, position_side: str, expected_cost_bps: float,
                        attribution_strength: float, allowed: bool, reason: Optional[str] = None):
    """Log funding cost decision for telemetry."""
    log_file = Path("logs/phase3_funding_decisions.json")
    log_file.parent.mkdir(exist_ok=True)
    
    if log_file.exists():
        try:
            with open(log_file) as f:
                decisions = json.load(f)
        except Exception:
            decisions = []
    else:
        decisions = []
    
    decisions.append({
        "timestamp": datetime.now().isoformat(),
        "symbol": symbol,
        "side": position_side,
        "expected_cost_bps": expected_cost_bps,
        "attribution_strength": attribution_strength,
        "allowed": allowed,
        "reason": reason
    })
    
    decisions = decisions[-1000:]
    
    with open(log_file, 'w') as f:
        json.dump(decisions, f, indent=2)


def update_funding_history(symbol: str, funding_rate_bps: float):
    """Update funding rate history for symbol."""
    history_file = Path("logs/funding_history.json")
    history_file.parent.mkdir(exist_ok=True)
    
    if history_file.exists():
        try:
            with open(history_file) as f:
                history = json.load(f)
        except Exception:
            history = {}
    else:
        history = {}
    
    if symbol not in history:
        history[symbol] = {
            "recent_rates_bps": [],
            "avg_rate_bps": 0.0,
            "updated_at": None
        }
    
    history[symbol]["recent_rates_bps"].append(funding_rate_bps)
    history[symbol]["recent_rates_bps"] = history[symbol]["recent_rates_bps"][-168:]
    
    if history[symbol]["recent_rates_bps"]:
        history[symbol]["avg_rate_bps"] = sum(history[symbol]["recent_rates_bps"]) / len(history[symbol]["recent_rates_bps"])
    
    history[symbol]["updated_at"] = datetime.now().isoformat()
    
    with open(history_file, 'w') as f:
        json.dump(history, f, indent=2)
