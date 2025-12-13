#!/usr/bin/env python3
"""
HOLD TIME GOVERNOR
==================
Prevents premature exits and learns optimal hold times per symbol+direction.

Features:
1. Block exits before minimum hold time (30min default) unless stop-loss hit
2. Learn optimal hold times per symbol+direction from historical data
3. Integrate with exit flow to prevent premature exits
4. Log all blocked early exits

KEY DATA:
- 30-60min holds = profitable (+$4.32, 56.6% WR)
- 0-2min holds = catastrophic (-$294.58)
- 147 trades exited too early vs 0 too late

Author: Trading Bot System
Date: December 2025
"""

import json
import os
import time
from datetime import datetime
from typing import Dict, List, Optional, Any, Tuple
from collections import defaultdict

DATA_DIR = "logs"
FEATURE_STORE = "feature_store"
CONFIG_DIR = "config"

HOLD_TIME_RULES_PATH = os.path.join(FEATURE_STORE, "hold_time_rules.json")
BLOCKED_EXITS_LOG = os.path.join(DATA_DIR, "blocked_early_exits.jsonl")
POSITIONS_FILE = os.path.join(DATA_DIR, "positions_futures.json")

DEFAULT_MIN_HOLD_MINUTES = 30
STOP_LOSS_THRESHOLD = -0.005


def _read_json(path: str, default: Any = None) -> Any:
    if not os.path.exists(path):
        return default
    try:
        with open(path, 'r') as f:
            return json.load(f)
    except:
        return default


def _write_json(path: str, data: Any):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp_path = path + ".tmp"
    with open(tmp_path, 'w') as f:
        json.dump(data, f, indent=2, default=str)
    os.replace(tmp_path, path)


def _append_jsonl(path: str, record: Dict):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    record["ts"] = int(time.time())
    with open(path, 'a') as f:
        f.write(json.dumps(record, default=str) + "\n")


def _parse_datetime(dt_str: str) -> Optional[datetime]:
    if not dt_str:
        return None
    try:
        if 'T' in dt_str:
            if '+' in dt_str or '-' in dt_str[10:]:
                return datetime.fromisoformat(dt_str)
            return datetime.fromisoformat(dt_str.replace('Z', '+00:00'))
        return datetime.fromisoformat(dt_str)
    except:
        return None


class HoldTimeGovernor:
    """
    Governs minimum hold times to prevent catastrophic early exits.
    
    KEY INSIGHT: Early exits (0-2min) = -$294.58 loss
    SOLUTION: Block exits before minimum hold time unless stop-loss hit
    """
    
    def __init__(self):
        self.rules: Dict[str, Any] = {}
        self.global_min_hold = DEFAULT_MIN_HOLD_MINUTES
        self._load_rules()
    
    def _load_rules(self):
        """Load hold time rules from feature store."""
        self.rules = _read_json(HOLD_TIME_RULES_PATH, {})
        self.global_min_hold = self.rules.get("global_min_hold_minutes", DEFAULT_MIN_HOLD_MINUTES)
    
    def get_min_hold_time(self, symbol: str, direction: str) -> int:
        """
        Get minimum hold time for symbol+direction.
        
        Returns minutes before which exits are blocked (unless stop-loss).
        """
        key = f"{symbol}|{direction.upper()}"
        
        per_symbol = self.rules.get("per_symbol_direction", {})
        if key in per_symbol:
            return per_symbol[key].get("min_hold_minutes", self.global_min_hold)
        
        if symbol in self.rules.get("per_symbol", {}):
            return self.rules["per_symbol"][symbol].get("min_hold_minutes", self.global_min_hold)
        
        return self.global_min_hold
    
    def should_block_exit(self, symbol: str, direction: str, 
                          minutes_open: float, current_roi: float,
                          close_reason: str = "") -> Tuple[bool, str]:
        """
        Check if exit should be blocked.
        
        Args:
            symbol: Trading symbol
            direction: LONG or SHORT
            minutes_open: How long position has been open
            current_roi: Current ROI as decimal (e.g., -0.01 = -1%)
            close_reason: Reason for close attempt
        
        Returns:
            (should_block, reason)
        """
        min_hold = self.get_min_hold_time(symbol, direction)
        
        if current_roi <= STOP_LOSS_THRESHOLD:
            return False, "stop_loss_override"
        
        if "stop" in close_reason.lower() or "liquidat" in close_reason.lower():
            return False, "stop_loss_reason"
        
        if minutes_open < min_hold:
            reason = f"min_hold_not_reached:{min_hold}min>current:{minutes_open:.1f}min"
            
            _append_jsonl(BLOCKED_EXITS_LOG, {
                "symbol": symbol,
                "direction": direction,
                "minutes_open": round(minutes_open, 1),
                "min_hold": min_hold,
                "current_roi": round(current_roi, 4),
                "close_reason": close_reason,
                "blocked": True,
                "blocked_reason": reason
            })
            
            print(f"   🛑 [HOLD_GOVERNOR] Blocked early exit: {symbol} {direction}")
            print(f"      Open: {minutes_open:.1f}min, Min: {min_hold}min, ROI: {current_roi*100:.2f}%")
            
            return True, reason
        
        return False, "exit_allowed"
    
    def get_recommended_hold_time(self, symbol: str, direction: str) -> Tuple[int, int]:
        """
        Get recommended hold time range (min, max) for optimal performance.
        
        Returns (min_minutes, max_minutes) for the sweet spot.
        """
        key = f"{symbol}|{direction.upper()}"
        
        per_symbol = self.rules.get("per_symbol_direction", {})
        if key in per_symbol:
            config = per_symbol[key]
            return (
                config.get("min_hold_minutes", 30),
                config.get("optimal_max_minutes", 60)
            )
        
        return (30, 60)
    
    def learn_from_history(self) -> Dict[str, Any]:
        """
        Learn optimal hold times from historical trade data.
        Updates rules in feature_store/hold_time_rules.json.
        """
        data = _read_json(POSITIONS_FILE, {})
        closed = data.get("closed_positions", [])
        
        by_symbol_direction = defaultdict(lambda: {
            "durations": [], "pnls": [], "short_exits": [], "long_exits": []
        })
        
        for trade in closed:
            if trade.get("pnl") is None:
                continue
            
            symbol = trade.get("symbol", "UNKNOWN")
            direction = (trade.get("direction") or trade.get("side") or "UNKNOWN").upper()
            key = f"{symbol}|{direction}"
            
            opened_at = _parse_datetime(trade.get("opened_at", ""))
            closed_at = _parse_datetime(trade.get("closed_at", ""))
            
            if opened_at and closed_at:
                duration = (closed_at - opened_at).total_seconds() / 60
                pnl = float(trade.get("pnl", 0))
                
                by_symbol_direction[key]["durations"].append(duration)
                by_symbol_direction[key]["pnls"].append(pnl)
                
                if duration < 30:
                    by_symbol_direction[key]["short_exits"].append({"duration": duration, "pnl": pnl})
                else:
                    by_symbol_direction[key]["long_exits"].append({"duration": duration, "pnl": pnl})
        
        per_symbol_direction = {}
        for key, stats in by_symbol_direction.items():
            if len(stats["durations"]) < 5:
                continue
            
            short_pnl = sum(e["pnl"] for e in stats["short_exits"])
            long_pnl = sum(e["pnl"] for e in stats["long_exits"])
            
            if short_pnl < 0 and abs(short_pnl) > 5:
                min_hold = 30
            else:
                min_hold = 15
            
            winners = [(d, p) for d, p in zip(stats["durations"], stats["pnls"]) if p > 0]
            if winners:
                optimal_duration = sum(d for d, _ in winners) / len(winners)
            else:
                optimal_duration = 45
            
            per_symbol_direction[key] = {
                "min_hold_minutes": min_hold,
                "optimal_max_minutes": int(min(120, optimal_duration * 1.5)),
                "short_exit_pnl": round(short_pnl, 2),
                "long_exit_pnl": round(long_pnl, 2),
                "total_trades": len(stats["durations"]),
                "recommendation": "block_early" if short_pnl < -10 else "normal"
            }
        
        self.rules = {
            "generated_at": datetime.utcnow().isoformat(),
            "global_min_hold_minutes": DEFAULT_MIN_HOLD_MINUTES,
            "per_symbol_direction": per_symbol_direction,
            "per_symbol": {}
        }
        
        _write_json(HOLD_TIME_RULES_PATH, self.rules)
        
        print(f"[HOLD_GOVERNOR] Learned hold times for {len(per_symbol_direction)} symbol+direction combos")
        
        return self.rules
    
    def get_blocked_exits_stats(self) -> Dict[str, Any]:
        """Get statistics on blocked exits."""
        if not os.path.exists(BLOCKED_EXITS_LOG):
            return {"blocked_count": 0, "potential_savings": 0}
        
        blocked = []
        try:
            with open(BLOCKED_EXITS_LOG, 'r') as f:
                for line in f:
                    try:
                        blocked.append(json.loads(line.strip()))
                    except:
                        continue
        except:
            pass
        
        return {
            "blocked_count": len(blocked),
            "by_symbol": defaultdict(int),
            "avg_roi_at_block": sum(b.get("current_roi", 0) for b in blocked) / len(blocked) if blocked else 0
        }


_governor_instance = None

def get_governor() -> HoldTimeGovernor:
    """Get singleton governor instance."""
    global _governor_instance
    if _governor_instance is None:
        _governor_instance = HoldTimeGovernor()
    return _governor_instance


def should_block_exit(symbol: str, direction: str, minutes_open: float,
                      current_roi: float, close_reason: str = "") -> Tuple[bool, str]:
    """
    Convenience function to check if exit should be blocked.
    
    Usage in exit flow:
        from src.hold_time_governor import should_block_exit
        
        blocked, reason = should_block_exit(symbol, direction, minutes_open, roi, close_reason)
        if blocked:
            print(f"Exit blocked: {reason}")
            continue  # Skip this exit
    """
    governor = get_governor()
    return governor.should_block_exit(symbol, direction, minutes_open, current_roi, close_reason)


def learn_hold_times() -> Dict[str, Any]:
    """Learn optimal hold times from history."""
    governor = get_governor()
    return governor.learn_from_history()


def get_min_hold_time(symbol: str, direction: str) -> int:
    """Get minimum hold time for symbol+direction."""
    governor = get_governor()
    return governor.get_min_hold_time(symbol, direction)


if __name__ == "__main__":
    print("=" * 70)
    print("HOLD TIME GOVERNOR")
    print("=" * 70)
    
    governor = HoldTimeGovernor()
    rules = governor.learn_from_history()
    
    print("\n" + "=" * 70)
    print("LEARNED HOLD TIME RULES")
    print("=" * 70)
    
    for key, config in rules.get("per_symbol_direction", {}).items():
        print(f"  {key}:")
        print(f"    Min hold: {config['min_hold_minutes']}min")
        print(f"    Short exit P&L: ${config['short_exit_pnl']:.2f}")
        print(f"    Long exit P&L: ${config['long_exit_pnl']:.2f}")
        print(f"    Recommendation: {config['recommendation']}")
    
    print("\n" + "=" * 70)
    print("TESTING SHOULD_BLOCK_EXIT")
    print("=" * 70)
    
    test_cases = [
        ("BTCUSDT", "SHORT", 5, -0.001, "profit_target"),
        ("BTCUSDT", "SHORT", 35, -0.001, "profit_target"),
        ("DOTUSDT", "SHORT", 10, -0.006, "stop_loss"),
        ("ETHUSDT", "LONG", 2, 0.005, "take_profit"),
    ]
    
    for symbol, direction, minutes, roi, reason in test_cases:
        blocked, block_reason = governor.should_block_exit(symbol, direction, minutes, roi, reason)
        status = "BLOCKED" if blocked else "ALLOWED"
        print(f"  {symbol} {direction} ({minutes}min, {roi*100:.2f}%): {status} - {block_reason}")
