# src/phase_298_300_meta_governance.py
#
# Phases 298–300: Meta-Governance & Scaling
# - 298: Portfolio Governor (dynamic capital allocation across symbols by expectancy & risk)
# - 299: Shadow Portfolio Experiments (parallel ghost portfolios with alternative parameters)
# - 300: Knowledge Graph Layer (structured memory of signals, regimes, outcomes for explainability)
#
# Purpose: Scale beyond single-trade intelligence into portfolio-level governance, experimentation, and knowledge graph learning.

import os, json, time, random
from collections import defaultdict

LOG_DIR = "logs"
META_LOG = os.path.join(LOG_DIR, "meta_governance_trace.jsonl")

def _now(): return int(time.time())
def _append_jsonl(path, obj): os.makedirs(os.path.dirname(path), exist_ok=True); open(path, "a").write(json.dumps(obj) + "\n")

# ======================================================================
# 298 – Portfolio Governor
# ======================================================================
def portfolio_governor(expectancy_by_symbol: dict, risk_scores: dict, total_capital: float = 100000.0) -> dict:
    """
    Allocate capital dynamically across symbols based on rolling expectancy and risk scores.
    - Higher EV and lower risk → more allocation
    - Normalize allocations to total_capital
    """
    weights = {}
    total_score = 0.0
    for sym, ev in expectancy_by_symbol.items():
        risk = risk_scores.get(sym, 1.0)
        score = max(0.0, ev) / max(0.1, risk)
        weights[sym] = score
        total_score += score
    allocations = {sym: round(total_capital * (w / total_score), 2) if total_score > 0 else 0.0 for sym, w in weights.items()}
    return {"allocations": allocations, "weights": weights}

# ======================================================================
# 299 – Shadow Portfolio Experiments
# ======================================================================
def shadow_portfolios(symbols: list) -> dict:
    """
    Run parallel ghost portfolios with alternative parameters.
    - Each symbol gets 1–2 shadow configs (different risk multipliers, thresholds).
    - Winners promoted if expectancy > live.
    """
    shadows = {}
    for sym in symbols:
        configs = []
        for _ in range(random.randint(1, 2)):
            configs.append({
                "risk_mult": random.choice([0.75, 1.0, 1.25]),
                "threshold": random.choice([0.20, 0.25, 0.30]),
                "exploration_bias": random.choice(["high", "low"])
            })
        shadows[sym] = configs
    return {"shadow_portfolios": shadows}

# ======================================================================
# 300 – Knowledge Graph Layer
# ======================================================================
def knowledge_graph_entry(symbol: str, regime: str, signals: dict, outcome: float) -> dict:
    """
    Build structured memory of signals, regimes, and outcomes.
    - Each entry links symbol, regime, signals, and realized outcome.
    - Stored as graph-like JSON for explainability.
    """
    entry = {
        "ts": _now(),
        "symbol": symbol,
        "regime": regime,
        "signals": signals,
        "outcome_ev": outcome
    }
    return entry

def update_knowledge_graph(entries: list, path: str = os.path.join(LOG_DIR, "knowledge_graph.jsonl")):
    for e in entries:
        _append_jsonl(path, e)

# ======================================================================
# Orchestrator Hook
# ======================================================================
def run_meta_governance(expectancy_by_symbol: dict, risk_scores: dict, symbols: list,
                        regime: str, signals: dict, outcome: float,
                        total_capital: float = 100000.0) -> dict:
    portfolio = portfolio_governor(expectancy_by_symbol, risk_scores, total_capital)
    shadows = shadow_portfolios(symbols)
    kg_entry = knowledge_graph_entry(symbols[0] if symbols else "BTCUSDT", regime, signals, outcome)
    update_knowledge_graph([kg_entry])

    summary = {
        "ts": _now(),
        "portfolio": portfolio,
        "shadows": shadows,
        "knowledge_graph_entry": kg_entry
    }
    _append_jsonl(META_LOG, summary)
    return summary

# CLI quick run
if __name__ == "__main__":
    example = run_meta_governance(
        expectancy_by_symbol={"BTCUSDT":0.12,"ETHUSDT":0.08,"SOLUSDT":-0.02},
        risk_scores={"BTCUSDT":0.9,"ETHUSDT":1.1,"SOLUSDT":1.3},
        symbols=["BTCUSDT","ETHUSDT","SOLUSDT"],
        regime="trend",
        signals={"ofi":0.5,"micro_arb":0.2,"sentiment":0.1,"regime_strength":0.7},
        outcome=0.15,
        total_capital=100000.0
    )
    print("Meta-governance summary:", json.dumps(example, indent=2))
