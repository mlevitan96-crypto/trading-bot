"""
Fee-Aware Entry Gate - Blocks trades where expected move < total fees

This module ensures we only enter trades with positive expected value after fees.
It calculates total round-trip costs (entry fees + exit fees + slippage) and
compares against the expected price movement.

Fee Structure (Blofin):
- Maker fee: 0.02% (2 bps)
- Taker fee: 0.05% (5 bps)
- Estimated slippage: 0.02% (2 bps) for market orders
- Total round-trip: ~0.14% (14 bps) for typical market order trade

Usage:
    from src.fee_aware_gate import FeeAwareGate
    
    gate = FeeAwareGate()
    result = gate.evaluate_entry(
        symbol="BTCUSDT",
        side="LONG",
        expected_move_pct=0.25,  # 0.25% expected move
        order_size_usd=100,
        is_market=True
    )
    
    if result["allow"]:
        # Proceed with trade
        pass
    else:
        # Trade blocked - expected move too small
        print(f"Blocked: {result['reason']}")
"""

import json
import os
import time
from datetime import datetime
from typing import Dict, Optional, Any
from pathlib import Path

from src.file_locks import atomic_json_write, atomic_json_save, locked_json_read
from src.data_registry import DataRegistry as DR


MAKER_FEE_BPS = 2
TAKER_FEE_BPS = 5
SLIPPAGE_BPS = 2

MAKER_FEE_PCT = MAKER_FEE_BPS / 10000
TAKER_FEE_PCT = TAKER_FEE_BPS / 10000
SLIPPAGE_PCT = SLIPPAGE_BPS / 10000

MIN_BUFFER_MULTIPLIER = 1.2


def _now() -> str:
    """Return current UTC timestamp in ISO format."""
    return datetime.utcnow().isoformat() + "Z"


def _log(msg: str):
    """Log with timestamp prefix."""
    ts = datetime.utcnow().isoformat() + "Z"
    print(f"[{ts}] [FEE-GATE] {msg}")


class FeeAwareGate:
    """
    Fee-Aware Entry Gate - Blocks trades where expected_move < total_fees.
    
    This gate ensures positive expected value after accounting for:
    - Entry fees (maker or taker)
    - Exit fees (maker or taker)
    - Slippage on market orders
    
    Strategy:
    - Calculate total round-trip cost percentage
    - Require expected_move > total_cost * MIN_BUFFER_MULTIPLIER
    - Track decisions and compute fee savings from blocked trades
    """
    
    def __init__(self):
        """Initialize the fee-aware gate."""
        self.state_path = DR.FEE_GATE_STATE
        self.log_path = DR.FEE_GATE_LOG
        self.state = self._load_state()
        _log(f"Initialized - Blocks: {self.state.get('blocked_count', 0)}, Allows: {self.state.get('allowed_count', 0)}")
    
    def _load_state(self) -> Dict:
        """Load state from file or return defaults."""
        default_state = {
            "blocked_count": 0,
            "allowed_count": 0,
            "total_blocked_size_usd": 0.0,
            "total_allowed_size_usd": 0.0,
            "estimated_fee_savings_usd": 0.0,
            "last_updated": _now(),
            "config": {
                "maker_fee_bps": MAKER_FEE_BPS,
                "taker_fee_bps": TAKER_FEE_BPS,
                "slippage_bps": SLIPPAGE_BPS,
                "min_buffer_multiplier": MIN_BUFFER_MULTIPLIER
            }
        }
        
        state = locked_json_read(self.state_path, default=default_state)
        return state
    
    def _save_state(self):
        """Save state atomically."""
        self.state["last_updated"] = _now()
        atomic_json_save(self.state_path, self.state)
    
    def calculate_total_cost(self, order_size_usd: float, is_market: bool = True) -> Dict[str, float]:
        """
        Calculate total round-trip cost for a trade.
        
        Args:
            order_size_usd: Size of the order in USD
            is_market: True for market order (taker), False for limit (maker)
        
        Returns:
            Dict with:
                - entry_fee_usd: Entry fee in USD
                - exit_fee_usd: Exit fee in USD
                - slippage_usd: Estimated slippage in USD
                - total_cost_usd: Total round-trip cost in USD
                - total_cost_pct: Total cost as percentage of order size
        """
        if is_market:
            entry_fee_pct = TAKER_FEE_PCT + SLIPPAGE_PCT
            exit_fee_pct = TAKER_FEE_PCT
        else:
            entry_fee_pct = MAKER_FEE_PCT
            exit_fee_pct = MAKER_FEE_PCT
        
        entry_fee_usd = order_size_usd * entry_fee_pct
        exit_fee_usd = order_size_usd * exit_fee_pct
        slippage_usd = order_size_usd * SLIPPAGE_PCT if is_market else 0.0
        
        total_cost_usd = entry_fee_usd + exit_fee_usd + slippage_usd
        total_cost_pct = ((entry_fee_pct + exit_fee_pct) * 100) + (SLIPPAGE_PCT * 100 if is_market else 0)
        
        return {
            "entry_fee_usd": round(entry_fee_usd, 4),
            "exit_fee_usd": round(exit_fee_usd, 4),
            "slippage_usd": round(slippage_usd, 4),
            "total_cost_usd": round(total_cost_usd, 4),
            "total_cost_pct": round(total_cost_pct, 4)
        }
    
    def estimate_breakeven_move(self, order_size_usd: float, is_market: bool = True) -> float:
        """
        Calculate minimum price move needed to break even.
        
        Args:
            order_size_usd: Size of the order in USD
            is_market: True for market order, False for limit
        
        Returns:
            Minimum move percentage needed to break even (e.g., 0.14 for 0.14%)
        """
        cost_info = self.calculate_total_cost(order_size_usd, is_market)
        return cost_info["total_cost_pct"]
    
    def evaluate_entry(
        self,
        symbol: str,
        side: str,
        expected_move_pct: float,
        order_size_usd: float,
        is_market: bool = True,
        signal_confidence: Optional[float] = None,
        atr_pct: Optional[float] = None
    ) -> Dict[str, Any]:
        """
        Evaluate whether to allow or block an entry.
        
        Args:
            symbol: Trading symbol (e.g., "BTCUSDT")
            side: Trade direction ("LONG" or "SHORT")
            expected_move_pct: Expected price move in % (e.g., 0.5 for 0.5%)
            order_size_usd: Order size in USD
            is_market: True for market order, False for limit
            signal_confidence: Optional signal confidence (0-1)
            atr_pct: Optional ATR as percentage for context
        
        Returns:
            Dict with:
                - allow: bool - True to allow trade, False to block
                - reason: str - Human-readable reason
                - fee_cost_usd: Total fees in USD
                - fee_cost_pct: Total fees as %
                - expected_move_pct: Expected move
                - breakeven_move_pct: Minimum move needed
                - net_expected_pct: Expected move minus fees
                - edge_ratio: expected_move / breakeven_move
        """
        cost_info = self.calculate_total_cost(order_size_usd, is_market)
        breakeven_pct = cost_info["total_cost_pct"]
        
        edge_ratio = expected_move_pct / breakeven_pct if breakeven_pct > 0 else 999
        
        min_required_pct = breakeven_pct * MIN_BUFFER_MULTIPLIER
        
        net_expected_pct = expected_move_pct - breakeven_pct
        net_expected_usd = (net_expected_pct / 100) * order_size_usd
        
        if expected_move_pct >= min_required_pct:
            allow = True
            if edge_ratio >= 3.0:
                reason = f"strong_edge_{edge_ratio:.1f}x"
            elif edge_ratio >= 2.0:
                reason = f"good_edge_{edge_ratio:.1f}x"
            else:
                reason = f"acceptable_edge_{edge_ratio:.1f}x"
        else:
            allow = False
            if expected_move_pct < breakeven_pct:
                reason = f"negative_ev_after_fees_edge_{edge_ratio:.2f}x"
            else:
                reason = f"insufficient_buffer_edge_{edge_ratio:.2f}x"
        
        result = {
            "allow": allow,
            "decision": "ALLOW" if allow else "BLOCK",
            "reason": reason,
            "symbol": symbol,
            "side": side,
            "order_size_usd": order_size_usd,
            "is_market": is_market,
            "expected_move_pct": round(expected_move_pct, 4),
            "breakeven_move_pct": round(breakeven_pct, 4),
            "min_required_pct": round(min_required_pct, 4),
            "net_expected_pct": round(net_expected_pct, 4),
            "net_expected_usd": round(net_expected_usd, 4),
            "edge_ratio": round(edge_ratio, 2),
            "fee_cost_usd": cost_info["total_cost_usd"],
            "fee_cost_pct": cost_info["total_cost_pct"],
            "ts": _now()
        }
        
        if signal_confidence is not None:
            result["signal_confidence"] = signal_confidence
        if atr_pct is not None:
            result["atr_pct"] = atr_pct
        
        self._update_stats(result)
        self.log_decision(symbol, side, result["decision"], reason, result)
        
        _log(f"{result['decision']} {symbol} {side}: expected={expected_move_pct:.3f}% vs breakeven={breakeven_pct:.3f}% (edge={edge_ratio:.2f}x)")
        
        return result
    
    def _update_stats(self, result: Dict):
        """Update internal statistics."""
        if result["allow"]:
            self.state["allowed_count"] = self.state.get("allowed_count", 0) + 1
            self.state["total_allowed_size_usd"] = self.state.get("total_allowed_size_usd", 0) + result["order_size_usd"]
        else:
            self.state["blocked_count"] = self.state.get("blocked_count", 0) + 1
            self.state["total_blocked_size_usd"] = self.state.get("total_blocked_size_usd", 0) + result["order_size_usd"]
            self.state["estimated_fee_savings_usd"] = (
                self.state.get("estimated_fee_savings_usd", 0) + result["fee_cost_usd"]
            )
        
        self._save_state()
    
    def log_decision(self, symbol: str, side: str, decision: str, reason: str, context: Dict):
        """
        Write decision to the log file using atomic writes.
        
        Args:
            symbol: Trading symbol
            side: Trade direction
            decision: "ALLOW" or "BLOCK"
            reason: Human-readable reason
            context: Full context dict
        """
        record = {
            "ts": _now(),
            "symbol": symbol,
            "side": side,
            "decision": decision,
            "reason": reason,
            "expected_move_pct": context.get("expected_move_pct"),
            "breakeven_move_pct": context.get("breakeven_move_pct"),
            "edge_ratio": context.get("edge_ratio"),
            "order_size_usd": context.get("order_size_usd"),
            "fee_cost_usd": context.get("fee_cost_usd"),
            "net_expected_usd": context.get("net_expected_usd")
        }
        
        os.makedirs(os.path.dirname(self.log_path), exist_ok=True)
        try:
            with open(self.log_path, 'a') as f:
                f.write(json.dumps(record, default=str) + '\n')
        except Exception as e:
            _log(f"Error writing log: {e}")
    
    def get_stats(self) -> Dict:
        """
        Get statistics on block/allow decisions and fee savings.
        
        Returns:
            Dict with counts, totals, and fee savings
        """
        blocked = self.state.get("blocked_count", 0)
        allowed = self.state.get("allowed_count", 0)
        total = blocked + allowed
        
        return {
            "blocked_count": blocked,
            "allowed_count": allowed,
            "total_decisions": total,
            "block_rate_pct": round((blocked / total * 100) if total > 0 else 0, 2),
            "total_blocked_size_usd": round(self.state.get("total_blocked_size_usd", 0), 2),
            "total_allowed_size_usd": round(self.state.get("total_allowed_size_usd", 0), 2),
            "estimated_fee_savings_usd": round(self.state.get("estimated_fee_savings_usd", 0), 2),
            "config": self.state.get("config", {}),
            "last_updated": self.state.get("last_updated", _now())
        }
    
    def reset_stats(self):
        """Reset all statistics (for testing/debugging)."""
        self.state = {
            "blocked_count": 0,
            "allowed_count": 0,
            "total_blocked_size_usd": 0.0,
            "total_allowed_size_usd": 0.0,
            "estimated_fee_savings_usd": 0.0,
            "last_updated": _now(),
            "config": {
                "maker_fee_bps": MAKER_FEE_BPS,
                "taker_fee_bps": TAKER_FEE_BPS,
                "slippage_bps": SLIPPAGE_BPS,
                "min_buffer_multiplier": MIN_BUFFER_MULTIPLIER
            }
        }
        self._save_state()
        _log("Stats reset")


_gate_instance = None


def get_fee_gate() -> FeeAwareGate:
    """Get or create singleton FeeAwareGate instance."""
    global _gate_instance
    if _gate_instance is None:
        _gate_instance = FeeAwareGate()
    return _gate_instance


if __name__ == "__main__":
    gate = FeeAwareGate()
    
    print("\n=== Fee-Aware Gate Test ===\n")
    
    result1 = gate.evaluate_entry(
        symbol="BTCUSDT",
        side="LONG",
        expected_move_pct=0.10,
        order_size_usd=100,
        is_market=True
    )
    print(f"Test 1 (should block): {result1['decision']} - {result1['reason']}")
    
    result2 = gate.evaluate_entry(
        symbol="ETHUSDT",
        side="SHORT",
        expected_move_pct=0.50,
        order_size_usd=200,
        is_market=True
    )
    print(f"Test 2 (should allow): {result2['decision']} - {result2['reason']}")
    
    result3 = gate.evaluate_entry(
        symbol="SOLUSDT",
        side="LONG",
        expected_move_pct=0.08,
        order_size_usd=150,
        is_market=False
    )
    print(f"Test 3 (limit order): {result3['decision']} - {result3['reason']}")
    
    print("\n=== Stats ===")
    stats = gate.get_stats()
    print(json.dumps(stats, indent=2))
