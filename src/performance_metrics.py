"""
Centralized Performance Metrics Aggregator

Computes real-time performance metrics from trade history and event logs
for kill-switch evaluation with proper sample-count and age safeguards.
"""

import json
import os
import time
from typing import Dict, List


PORTFOLIO_LOG = "logs/portfolio.json"
TRADES_FUTURES_LOG = "logs/trades_futures.json"  # Primary trades file (not backup)
TRADES_FUTURES_BACKUP = "logs/trades_futures_backup.json"  # Fallback only
EVENTS_LOG = "logs/unified_events.jsonl"


def _read_json(path: str) -> dict:
    """Read single JSON file."""
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r") as f:
            return json.load(f)
    except Exception:
        return {}


def _read_jsonl(path: str) -> List[dict]:
    """Read JSONL file."""
    if not os.path.exists(path):
        return []
    try:
        with open(path, "r") as f:
            return [json.loads(line) for line in f if line.strip()]
    except Exception:
        return []


def _parse_timestamp(ts_str: str) -> float:
    """Parse ISO 8601 timestamp string to Unix timestamp."""
    if not ts_str:
        return 0.0
    try:
        from datetime import datetime
        dt = datetime.fromisoformat(ts_str.replace('Z', '+00:00'))
        return dt.timestamp()
    except Exception:
        return 0.0


def compute_performance_metrics() -> Dict[str, float]:
    """
    Aggregate performance metrics from trade history and events.
    
    Returns:
        dict with keys:
            - drawdown_pct: Maximum drawdown percentage from peak
            - reject_rate_pct: Percentage of rejected orders
            - fee_mismatch_usd: Total fee discrepancy
            - total_fills: Count of closed trades
            - age_hours: Hours since oldest data point
    """
    portfolio_data = _read_json(PORTFOLIO_LOG)
    # Try primary trades file first, fallback to backup
    trades_data = _read_json(TRADES_FUTURES_LOG)
    if not trades_data or not trades_data.get("trades"):
        trades_data = _read_json(TRADES_FUTURES_BACKUP)
    trades = trades_data.get("trades", []) if trades_data else []
    events = _read_jsonl(EVENTS_LOG)
    
    total_fills = len(trades)
    current_time = time.time()
    
    age_hours = 0.0
    if trades:
        timestamps = []
        for t in trades:
            if "timestamp" in t:
                ts = _parse_timestamp(t["timestamp"])
                if ts > 0:
                    timestamps.append(ts)
            elif "entry_ts" in t:
                timestamps.append(float(t["entry_ts"]))
            elif "exit_ts" in t:
                timestamps.append(float(t["exit_ts"]))
            elif "created_ts" in t:
                timestamps.append(float(t["created_ts"]))
        
        if timestamps:
            # Use NEWEST trade to determine data freshness (not oldest)
            newest_trade_ts = max(timestamps)
            age_hours = (current_time - newest_trade_ts) / 3600.0
    
    if total_fills == 0:
        return {
            "drawdown_pct": 0.0,
            "reject_rate_pct": 0.0,
            "fee_mismatch_usd": 0.0,
            "total_fills": 0,
            "age_hours": 0.0
        }
    
    closed_trades = [t for t in trades if t.get("status") in ["closed", "win", "loss"]]
    
    cumulative_pnl = []
    running_sum = 0.0
    for trade in sorted(closed_trades, key=lambda x: x.get("exit_ts", 0)):
        profit = float(trade.get("profit_usd", 0.0))
        running_sum += profit
        cumulative_pnl.append(running_sum)
    
    if cumulative_pnl:
        peak = cumulative_pnl[0]
        max_drawdown = 0.0
        for pnl in cumulative_pnl:
            if pnl > peak:
                peak = pnl
            drawdown = peak - pnl
            if drawdown > max_drawdown:
                max_drawdown = drawdown
        
        starting_capital = 10000.0
        drawdown_pct = (max_drawdown / starting_capital) * 100.0
    else:
        drawdown_pct = 0.0
    
    recent_events = [e for e in events if e.get("ts", 0) > (current_time - 3600*24)]
    
    reject_events = [e for e in recent_events if e.get("event") == "entry_block"]
    total_attempts = len([e for e in recent_events if e.get("event") in ["entry_block", "entry_opened"]])
    
    if total_attempts > 0:
        reject_rate_pct = (len(reject_events) / total_attempts) * 100.0
    else:
        reject_rate_pct = 0.0
    
    fee_mismatch_events = [e for e in recent_events if e.get("event") == "fee_mismatch_detected"]
    fee_mismatch_usd = sum(abs(float(e.get("mismatch_usd", 0.0))) for e in fee_mismatch_events)
    
    return {
        "drawdown_pct": round(drawdown_pct, 2),
        "reject_rate_pct": round(reject_rate_pct, 2),
        "fee_mismatch_usd": round(fee_mismatch_usd, 2),
        "total_fills": total_fills,
        "age_hours": round(age_hours, 2)
    }


if __name__ == "__main__":
    metrics = compute_performance_metrics()
    print("📊 Performance Metrics:")
    for key, value in metrics.items():
        print(f"   {key}: {value}")
