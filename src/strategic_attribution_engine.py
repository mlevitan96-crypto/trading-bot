# src/strategic_attribution_engine.py
#
# Phase 18.0 - Strategic Attribution Engine
# Purpose:
#   - Analyzes which strategies, symbols, and regimes drive P&L
#   - Tracks attribution metrics: win rate, avg ROI, Sharpe ratio per strategy
#   - Identifies underperformers for pruning decisions
#   - Logs strategic performance data for continuous improvement

import os, json, time
from collections import defaultdict

ATTRIBUTION_LOG = "logs/strategic_attribution.jsonl"
TRADES_LOG = "logs/unified_events.jsonl"

def _append_event(event: str, data: dict = None):
    os.makedirs(os.path.dirname(ATTRIBUTION_LOG), exist_ok=True)
    entry = {"event": event, "ts": int(time.time())}
    if data:
        entry.update(data)
    with open(ATTRIBUTION_LOG, "a") as f:
        f.write(json.dumps(entry) + "\n")

def _read_jsonl(path: str):
    if not os.path.exists(path):
        return []
    events = []
    with open(path, "r") as f:
        for line in f:
            try:
                events.append(json.loads(line.strip()))
            except:
                pass
    return events

def run_strategic_attribution():
    """
    Analyze strategic performance attribution:
    - Per-strategy P&L contribution
    - Per-symbol profitability
    - Regime-specific performance
    - Exit quality metrics
    """
    trades = _read_jsonl(TRADES_LOG)
    
    # Attribution buckets
    strategy_metrics = defaultdict(lambda: {"trades": 0, "wins": 0, "total_roi": 0.0})
    symbol_metrics = defaultdict(lambda: {"trades": 0, "wins": 0, "total_roi": 0.0})
    regime_metrics = defaultdict(lambda: {"trades": 0, "wins": 0, "total_roi": 0.0})
    
    for trade in trades:
        if trade.get("event_type") != "trade_close":
            continue
        
        strategy = trade.get("strategy", "unknown")
        symbol = trade.get("symbol", "unknown")
        regime = trade.get("regime", "unknown")
        roi = float(trade.get("net_roi", 0.0))
        
        # Strategy attribution
        strategy_metrics[strategy]["trades"] += 1
        strategy_metrics[strategy]["total_roi"] += roi
        if roi > 0:
            strategy_metrics[strategy]["wins"] += 1
        
        # Symbol attribution
        symbol_metrics[symbol]["trades"] += 1
        symbol_metrics[symbol]["total_roi"] += roi
        if roi > 0:
            symbol_metrics[symbol]["wins"] += 1
        
        # Regime attribution
        regime_metrics[regime]["trades"] += 1
        regime_metrics[regime]["total_roi"] += roi
        if roi > 0:
            regime_metrics[regime]["wins"] += 1
    
    # Calculate win rates and average ROI
    attribution_summary = {
        "strategies": {},
        "symbols": {},
        "regimes": {}
    }
    
    for strategy, metrics in strategy_metrics.items():
        wr = metrics["wins"] / metrics["trades"] if metrics["trades"] > 0 else 0.0
        avg_roi = metrics["total_roi"] / metrics["trades"] if metrics["trades"] > 0 else 0.0
        attribution_summary["strategies"][strategy] = {
            "trades": metrics["trades"],
            "win_rate": round(wr, 3),
            "avg_roi": round(avg_roi, 4),
            "total_roi": round(metrics["total_roi"], 4)
        }
    
    for symbol, metrics in symbol_metrics.items():
        wr = metrics["wins"] / metrics["trades"] if metrics["trades"] > 0 else 0.0
        avg_roi = metrics["total_roi"] / metrics["trades"] if metrics["trades"] > 0 else 0.0
        attribution_summary["symbols"][symbol] = {
            "trades": metrics["trades"],
            "win_rate": round(wr, 3),
            "avg_roi": round(avg_roi, 4),
            "total_roi": round(metrics["total_roi"], 4)
        }
    
    for regime, metrics in regime_metrics.items():
        wr = metrics["wins"] / metrics["trades"] if metrics["trades"] > 0 else 0.0
        avg_roi = metrics["total_roi"] / metrics["trades"] if metrics["trades"] > 0 else 0.0
        attribution_summary["regimes"][regime] = {
            "trades": metrics["trades"],
            "win_rate": round(wr, 3),
            "avg_roi": round(avg_roi, 4),
            "total_roi": round(metrics["total_roi"], 4)
        }
    
    _append_event("attribution_computed", attribution_summary)
    return attribution_summary

if __name__ == "__main__":
    result = run_strategic_attribution()
    print("Phase 18.0 Strategic Attribution Engine complete.")
    print(f"Analyzed {len(result['strategies'])} strategies, {len(result['symbols'])} symbols, {len(result['regimes'])} regimes")
