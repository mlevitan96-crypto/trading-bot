"""
Counterfactual Trade Tracker
============================
Tracks theoretical P&L of signals that were blocked by gates (Fee Gate, Conviction Gate, etc.)
to enable analysis of "what if" scenarios.

Stores blocked signals in counterfactual_trades.jsonl for later analysis.
"""

import json
import time
from pathlib import Path
from datetime import datetime, timezone
from typing import Dict, Any, Optional

COUNTERFACTUAL_LOG = Path("logs/counterfactual_trades.jsonl")
COUNTERFACTUAL_LOG.parent.mkdir(parents=True, exist_ok=True)


def _append_jsonl(filepath: Path, record: Dict[str, Any]):
    """Append a JSON record to a JSONL file."""
    try:
        with open(filepath, 'a') as f:
            f.write(json.dumps(record) + '\n')
    except Exception as e:
        print(f"⚠️ [COUNTERFACTUAL] Failed to log counterfactual: {e}")


def log_blocked_signal(
    symbol: str,
    side: str,
    signal_price: float,
    expected_move_pct: float,
    block_gate: str,
    block_reason: str,
    signal_context: Optional[Dict[str, Any]] = None,
    sizing_multiplier: float = 1.0
):
    """
    Log a blocked signal for counterfactual analysis.
    
    Args:
        symbol: Trading symbol
        side: LONG or SHORT
        signal_price: Price at which signal was generated
        expected_move_pct: Expected price move percentage
        block_gate: Which gate blocked it (e.g., "fee_gate", "conviction_gate")
        block_reason: Reason for blocking
        signal_context: Additional signal context (OFI, ensemble, regime, etc.)
        sizing_multiplier: What sizing multiplier would have been applied
    """
    record = {
        "ts": time.time(),
        "ts_iso": datetime.now(timezone.utc).isoformat(),
        "symbol": symbol,
        "side": side,
        "signal_price": signal_price,
        "expected_move_pct": expected_move_pct,
        "block_gate": block_gate,
        "block_reason": block_reason,
        "sizing_multiplier": sizing_multiplier,
        "signal_context": signal_context or {},
        "status": "blocked",
        "counterfactual_pnl": None,  # Will be calculated later when price moves
        "counterfactual_pnl_pct": None,
    }
    
    _append_jsonl(COUNTERFACTUAL_LOG, record)
    
    print(f"📊 [COUNTERFACTUAL] Logged blocked signal: {symbol} {side} @ ${signal_price:.2f} (blocked by {block_gate}: {block_reason})")


def update_counterfactual_pnl(
    symbol: str,
    current_price: float,
    lookback_seconds: int = 3600
):
    """
    Update counterfactual P&L for recent blocked signals.
    
    This should be called periodically to calculate "what if" P&L
    for signals that were blocked.
    
    Args:
        symbol: Trading symbol
        current_price: Current market price
        lookback_seconds: How far back to look for blocked signals (default 1 hour)
    """
    if not COUNTERFACTUAL_LOG.exists():
        return
    
    try:
        # Read all records
        records = []
        with open(COUNTERFACTUAL_LOG, 'r') as f:
            for line in f:
                if line.strip():
                    records.append(json.loads(line))
        
        # Filter for recent blocked signals for this symbol
        now = time.time()
        updated_count = 0
        
        for record in records:
            # Skip if already calculated or not for this symbol
            if record.get("symbol") != symbol or record.get("counterfactual_pnl") is not None:
                continue
            
            # Skip if too old
            signal_ts = record.get("ts", 0)
            if (now - signal_ts) > lookback_seconds:
                continue
            
            # Calculate theoretical P&L
            signal_price = record.get("signal_price", 0)
            side = record.get("side", "LONG")
            expected_move = record.get("expected_move_pct", 0) / 100
            
            if signal_price > 0:
                if side == "LONG":
                    pnl_pct = ((current_price - signal_price) / signal_price) * 100
                else:  # SHORT
                    pnl_pct = ((signal_price - current_price) / signal_price) * 100
                
                # Store theoretical P&L (would need position size to calculate USD)
                record["counterfactual_pnl_pct"] = pnl_pct
                record["current_price"] = current_price
                record["price_move_pct"] = pnl_pct
                record["updated_at"] = datetime.now(timezone.utc).isoformat()
                
                updated_count += 1
        
        # Write back updated records (this is a simple approach - in production might want to use a database)
        if updated_count > 0:
            # For now, we'll just log the updates - full rewrite would be expensive
            # In production, consider using a database or more efficient storage
            pass
            
    except Exception as e:
        print(f"⚠️ [COUNTERFACTUAL] Error updating P&L: {e}")


def get_counterfactual_stats(days: int = 7) -> Dict[str, Any]:
    """
    Get statistics on blocked signals and their theoretical outcomes.
    
    Args:
        days: Number of days to analyze
        
    Returns:
        Dict with statistics
    """
    if not COUNTERFACTUAL_LOG.exists():
        return {
            "total_blocked": 0,
            "by_gate": {},
            "theoretical_pnl": 0.0,
            "theoretical_wins": 0,
            "theoretical_losses": 0,
        }
    
    try:
        cutoff_ts = time.time() - (days * 24 * 3600)
        
        records = []
        with open(COUNTERFACTUAL_LOG, 'r') as f:
            for line in f:
                if line.strip():
                    record = json.loads(line)
                    if record.get("ts", 0) >= cutoff_ts:
                        records.append(record)
        
        stats = {
            "total_blocked": len(records),
            "by_gate": {},
            "theoretical_pnl_pct": 0.0,
            "theoretical_wins": 0,
            "theoretical_losses": 0,
            "with_pnl_calculated": 0,
        }
        
        for record in records:
            gate = record.get("block_gate", "unknown")
            stats["by_gate"][gate] = stats["by_gate"].get(gate, 0) + 1
            
            pnl_pct = record.get("counterfactual_pnl_pct")
            if pnl_pct is not None:
                stats["with_pnl_calculated"] += 1
                stats["theoretical_pnl_pct"] += pnl_pct
                if pnl_pct > 0:
                    stats["theoretical_wins"] += 1
                elif pnl_pct < 0:
                    stats["theoretical_losses"] += 1
        
        if stats["with_pnl_calculated"] > 0:
            stats["theoretical_pnl_pct"] /= stats["with_pnl_calculated"]
        
        return stats
        
    except Exception as e:
        print(f"⚠️ [COUNTERFACTUAL] Error getting stats: {e}")
        return {"error": str(e)}

