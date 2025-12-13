# src/phase_284_286.py
#
# Phases 284–286: Self-Healing Layer
# - 284: Anomaly Detector
# - 285: Auto-Reconciler
# - 286: Strategy Governor
#
# Integrated into nightly orchestrator: run_self_healing_cycle() is called
# automatically at the end of each cycle.

import os, json, time

LOG_DIR = "logs"
TRADE_LOG = os.path.join(LOG_DIR, "logs/executed_trades.jsonl")
PORTFOLIO_STATE = os.path.join(LOG_DIR, "portfolio_state.json")
SELF_HEAL_LOG = os.path.join(LOG_DIR, "self_healing_trace.jsonl")

def _now(): return int(time.time())
def _read_json(path, default=None): return json.load(open(path)) if os.path.exists(path) else (default if default is not None else {})
def _write_json(path, obj): os.makedirs(os.path.dirname(path), exist_ok=True); json.dump(obj, open(path, "w"), indent=2)
def _append_jsonl(path, obj): os.makedirs(os.path.dirname(path), exist_ok=True); open(path, "a").write(json.dumps(obj) + "\n")
def _read_jsonl(path): return [json.loads(l) for l in open(path)] if os.path.exists(path) else []

# ======================================================================
# 284 – Anomaly Detector
# ======================================================================
def detect_anomalies(portfolio):
    anomalies = []
    
    # Check futures portfolio for margin anomalies
    available_margin = portfolio.get("available_margin", 0)
    total_margin = portfolio.get("total_margin_allocated", 6000)
    
    if available_margin < 0:
        anomalies.append("Negative margin detected")
    if available_margin > total_margin * 2:
        anomalies.append("Inflated margin detected")
    
    # Check win rate from executed trades
    trades = _read_jsonl(TRADE_LOG)
    if len(trades) > 10:
        wins = sum(1 for t in trades if float(t.get("pnl", 0)) > 0)
        losses = sum(1 for t in trades if float(t.get("pnl", 0)) < 0)
        win_rate = wins / max(1, wins + losses)
        if win_rate < 0.4:
            anomalies.append(f"Low win rate ({win_rate:.1%})")
    
    return anomalies

# ======================================================================
# 285 – Auto-Reconciler
# ======================================================================
def reconcile_portfolio():
    trades = _read_jsonl(TRADE_LOG)
    balance = 10000.0
    realized_pnl, total_trades, wins, losses = 0.0, 0, 0, 0

    for t in trades:
        pnl = float(t.get("pnl", 0.0))
        fees = float(t.get("fees", 0.0))
        net = pnl - fees
        realized_pnl += net
        balance += net
        total_trades += 1
        if pnl > 0: wins += 1
        elif pnl < 0: losses += 1

    portfolio = {
        "balance": round(balance, 2),
        "realized_pnl": round(realized_pnl, 2),
        "total_trades": total_trades,
        "wins": wins,
        "losses": losses,
        "win_rate": round((wins / max(1, wins + losses)), 4),
        "margin_available": round(balance * 0.9, 2),
        "metrics_age": 0
    }
    _write_json(PORTFOLIO_STATE, portfolio)
    return portfolio

# ======================================================================
# 286 – Strategy Governor
# ======================================================================
def strategy_governor(portfolio):
    actions = []
    if portfolio["win_rate"] < 0.4:
        actions.append("Demote weak strategies to paper mode")
    if portfolio["win_rate"] >= 0.55 and portfolio["realized_pnl"] > 0:
        actions.append("Promote strong strategies to higher confidence stage")
    return actions

# ======================================================================
# Orchestrator Hook
# ======================================================================
def run_self_healing_cycle():
    """Run self-healing cycle - detects anomalies and auto-fixes portfolio corruption"""
    try:
        # Load actual futures portfolio from bot
        from src.futures_portfolio_tracker import load_futures_portfolio
        portfolio = load_futures_portfolio()
        
        # Detect anomalies in current state
        anomalies = detect_anomalies(portfolio)
        
        # If anomalies detected, reconcile from trade log
        if anomalies:
            reconciled_state = reconcile_portfolio()
            actions = strategy_governor(reconciled_state)
        else:
            reconciled_state = portfolio
            actions = []

        log_entry = {
            "ts": _now(),
            "anomalies": anomalies,
            "actions": actions,
            "available_margin": portfolio.get("available_margin", 0),
            "realized_pnl": portfolio.get("realized_pnl", 0)
        }
        _append_jsonl(SELF_HEAL_LOG, log_entry)
        return log_entry
    except Exception as e:
        return {"error": str(e), "anomalies": [], "actions": []}

# Nightly orchestrator integration
def nightly_orchestrator_hook():
    summary = run_self_healing_cycle()
    print("Self-healing summary:", json.dumps(summary, indent=2))

if __name__ == "__main__":
    nightly_orchestrator_hook()
