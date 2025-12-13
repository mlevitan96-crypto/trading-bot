# src/phase_261_265.py
#
# Phases 261–265: Portfolio Scaling Layer (Automated Canary→Portfolio Migration)
# - 261: Portfolio Lift Validator (7-day sustained lift check)
# - 262: Strategy Stability Monitor (precision/win-rate/drawdown thresholds)
# - 263: Auto-Migration Engine (promote canary strategies to portfolio mode)
# - 264: Portfolio Risk Allocator (rebalance capital weights, diversification caps)
# - 265: Portfolio Scaling Orchestrator (nightly automation + checkpoint)
#
# Autonomy-first: no dashboards required. Produces a single summary and updates state.
# Integration hooks included for orchestrators and execution bridge.

import os, json, time
from statistics import mean

# ---- Paths ----
PERF_HISTORY = "logs/strategy_performance_history.json"  # per-strategy rolling metrics (append daily)
CANARY_STATE = "logs/canary_state.json"                  # from phases 256–260 (strategy mode/capital)
PORTFOLIO_STATE = "logs/portfolio_state.json"            # portfolio-level allocations
SYMBOL_UNIVERSE = "logs/symbol_universe.json"            # {symbols: [...], sectors: {symbol: sector}}
LEVERAGE_POLICY = "logs/leverage_policy.json"            # leverage per symbol/strategy if used
STATE_CHECKPOINT = "logs/state_checkpoint.json"          # unified state checkpoint
PORTFOLIO_SUMMARY = "logs/portfolio_scaling_summary.json" # nightly portfolio scaling summary

def _now(): return int(time.time())
def _read_json(path, default=None): return json.load(open(path)) if os.path.exists(path) else (default if default is not None else {})
def _write_json(path, obj): os.makedirs(os.path.dirname(path), exist_ok=True); json.dump(obj, open(path, "w"), indent=2)

# ======================================================================
# 261 – Portfolio Lift Validator (7-day sustained lift)
# ======================================================================
def append_daily_performance(strategy_name, paper_roi, live_roi, precision, win_rate, drawdown, fee_ratio):
    hist = _read_json(PERF_HISTORY, {})
    arr = hist.get(strategy_name, [])
    arr.append({
        "ts": _now(),
        "paper_roi": float(paper_roi),
        "live_roi": float(live_roi),
        "precision": float(precision),
        "win_rate": float(win_rate),
        "drawdown": float(drawdown),
        "fee_ratio": float(fee_ratio)
    })
    # Keep last 30 entries max
    hist[strategy_name] = arr[-30:]
    _write_json(PERF_HISTORY, hist)
    return hist[strategy_name]

def portfolio_lift_validator(min_days=7, min_lift=0.05):
    """
    Checks sustained lift over the last `min_days`: avg(live - paper) >= min_lift.
    Returns {strategy: {"sustained_lift": bool, "avg_lift": x, "days": n}}
    """
    hist = _read_json(PERF_HISTORY, {})
    out = {}
    for strat, series in hist.items():
        window = series[-min_days:] if len(series) >= min_days else series
        days = len(window)
        avg_lift = mean([(d.get("live_roi", 0.0) - d.get("paper_roi", 0.0)) for d in window]) if window else 0.0
        out[strat] = {"sustained_lift": (days >= min_days and avg_lift >= min_lift), "avg_lift": round(avg_lift, 6), "days": days}
    return out

# ======================================================================
# 262 – Strategy Stability Monitor
# ======================================================================
def strategy_stability_monitor(min_precision=0.65, min_win_rate=0.25, max_drawdown=0.02, min_days=7):
    """
    Checks stability over the same 7-day window: precision, win rate, drawdown thresholds.
    Returns {strategy: {"stable": bool, "precision": avg, "win_rate": avg, "drawdown": avg, "days": n}}
    """
    hist = _read_json(PERF_HISTORY, {})
    out = {}
    for strat, series in hist.items():
        window = series[-min_days:] if len(series) >= min_days else series
        days = len(window)
        avg_prec = mean([d.get("precision", 0.0) for d in window]) if window else 0.0
        avg_wr = mean([d.get("win_rate", 0.0) for d in window]) if window else 0.0
        avg_dd = mean([d.get("drawdown", 0.0) for d in window]) if window else 0.0
        stable = (days >= min_days) and (avg_prec >= min_precision) and (avg_wr >= min_win_rate) and (avg_dd <= max_drawdown)
        out[strat] = {"stable": stable, "precision": round(avg_prec, 6), "win_rate": round(avg_wr, 6), "drawdown": round(avg_dd, 6), "days": days}
    return out

# ======================================================================
# 263 – Auto-Migration Engine (canary → portfolio)
# ======================================================================
def auto_migration_engine(lift_report, stability_report):
    """
    Promotes strategies to full portfolio mode if sustained_lift & stable both true.
    Updates CANARY_STATE status to 'portfolio' and sets live_capital=0 (managed by portfolio allocator).
    Returns list of migrated strategies.
    """
    canary = _read_json(CANARY_STATE, {})
    migrated = []
    for strat in set(list(lift_report.keys()) + list(stability_report.keys())):
        if lift_report.get(strat, {}).get("sustained_lift") and stability_report.get(strat, {}).get("stable"):
            # Promote
            state = canary.get(strat, {"live_capital": 0.0, "status": "unknown"})
            state["status"] = "portfolio"
            state["live_capital"] = 0.0  # portfolio allocator will assign weights
            canary[strat] = state
            migrated.append(strat)
    _write_json(CANARY_STATE, canary)
    return migrated

# ======================================================================
# 264 – Portfolio Risk Allocator
# ======================================================================
def _sector_map():
    uni = _read_json(SYMBOL_UNIVERSE, {"symbols": [], "sectors": {}})
    return uni.get("sectors", {})  # {symbol: sector}

def portfolio_risk_allocator(active_strategies, base_weights=None, sector_cap=0.50, global_exposure_cap=0.60):
    """
    Rebalances capital weights across active portfolio strategies.
    - active_strategies: list of strategy names in 'portfolio' mode
    - base_weights: optional dict of initial desired weights {strategy: weight}, default equal
    - sector_cap: cap cumulative weight per sector to enforce diversification
    - global_exposure_cap: cap sum of all weights to limit exposure
    Returns normalized weights and diversification info.
    """
    # Initial equal weights or provided
    if not active_strategies:
        return {"weights": {}, "total_weight": 0.0, "sector_load": {}}
    weights = {}
    if base_weights:
        for s in active_strategies:
            weights[s] = float(base_weights.get(s, 0.0))
    else:
        eq = round(1.0 / len(active_strategies), 6)
        for s in active_strategies: weights[s] = eq

    # Sector attribution: assume a mapping strategy->representative symbol sector if available
    sectors = _sector_map()
    sector_load = {}
    # Heuristic: if strategy name matches a symbol key, use that; else spread evenly
    for s in active_strategies:
        sym = s  # if strategy names are symbols; otherwise fallback
        sec = sectors.get(sym, "unknown")
        sector_load[sec] = sector_load.get(sec, 0.0) + weights.get(s, 0.0)

    # Enforce sector caps: downscale overweight sectors
    for sec, load in sector_load.items():
        if load > sector_cap:
            scale = sector_cap / load
            for s in active_strategies:
                sym = s
                if sectors.get(sym, "unknown") == sec:
                    weights[s] = round(weights[s] * scale, 6)

    # Normalize and enforce global exposure cap
    total = sum(weights.values())
    if total > 0:
        # scale to global_exposure_cap
        scale = min(global_exposure_cap / total, 1.0)
        for s in weights:
            weights[s] = round(weights[s] * scale, 6)
    total = round(sum(weights.values()), 6)

    # Persist portfolio state
    portfolio = _read_json(PORTFOLIO_STATE, {})
    portfolio["weights"] = weights
    portfolio["total_weight"] = total
    portfolio["sector_load"] = sector_load
    _write_json(PORTFOLIO_STATE, portfolio)

    return {"weights": weights, "total_weight": total, "sector_load": sector_load}

# ======================================================================
# 265 – Portfolio Scaling Orchestrator (nightly)
# ======================================================================
def portfolio_scaling_orchestrator():
    """
    Nightly run:
    - Validate sustained lift & stability (7-day window)
    - Auto-migrate canary strategies to portfolio mode
    - Build active portfolio list and allocate risk-aware weights
    - Checkpoint state and write summary
    """
    lift = portfolio_lift_validator(min_days=7, min_lift=0.05)
    stability = strategy_stability_monitor(min_precision=0.65, min_win_rate=0.25, max_drawdown=0.02, min_days=7)
    migrated = auto_migration_engine(lift, stability)

    # Active portfolio strategies: in CANARY_STATE with status 'portfolio'
    canary = _read_json(CANARY_STATE, {})
    active_portfolio = [s for s, st in canary.items() if st.get("status") == "portfolio"]

    alloc = portfolio_risk_allocator(active_portfolio, base_weights=None, sector_cap=0.50, global_exposure_cap=0.60)

    # Checkpoint
    ck = {
        "ts": _now(),
        "canary_state": canary,
        "portfolio_state": _read_json(PORTFOLIO_STATE, {}),
        "leverage_policy": _read_json(LEVERAGE_POLICY, {}),
        "symbol_universe": _read_json(SYMBOL_UNIVERSE, {})
    }
    _write_json(STATE_CHECKPOINT, ck)

    # Summary
    summary = {
        "ts": _now(),
        "migrated": migrated,
        "active_portfolio": active_portfolio,
        "weights": alloc.get("weights", {}),
        "total_weight": alloc.get("total_weight", 0.0),
        "sector_load": alloc.get("sector_load", {}),
        "lift": lift,
        "stability": stability
    }
    _write_json(PORTFOLIO_SUMMARY, summary)
    return summary

# ----------------------------------------------------------------------
# Integration Hooks (execution bridge & orchestrators)
# ----------------------------------------------------------------------
def get_strategy_mode(strategy_name):
    """
    Returns "portfolio", "canary", or "paper" based on CANARY_STATE.
    """
    st = _read_json(CANARY_STATE, {}).get(strategy_name, {"status": "paper"})
    return st.get("status", "paper")

def get_portfolio_weight(strategy_name):
    """
    Returns normalized portfolio weight [0..1] for a strategy in portfolio mode.
    """
    ps = _read_json(PORTFOLIO_STATE, {}).get("weights", {})
    return float(ps.get(strategy_name, 0.0))

def pre_trade_portfolio_gate(strategy_name):
    """
    Determines route mode and weight for execution:
    - portfolio: use portfolio weight to scale live size (subject to other gates)
    - canary: use CANARY_STATE live_capital
    - paper: route to paper
    """
    mode = get_strategy_mode(strategy_name)
    if mode == "portfolio":
        weight = get_portfolio_weight(strategy_name)
        return {"mode": "portfolio", "weight": weight}
    elif mode == "canary":
        cs = _read_json(CANARY_STATE, {}).get(strategy_name, {"live_capital": 0.0})
        return {"mode": "canary", "weight": float(cs.get("live_capital", 0.0))}
    else:
        return {"mode": "paper", "weight": 0.0}

def update_daily_performance(strategy_name, paper_roi, live_roi, precision, win_rate, drawdown, fee_ratio):
    """
    Public wrapper to append daily metrics (used by nightly aggregation job).
    """
    return append_daily_performance(strategy_name, paper_roi, live_roi, precision, win_rate, drawdown, fee_ratio)

# Example wiring in nightly orchestrator:
# --------------------------------------
# from src.phase_261_265 import portfolio_scaling_orchestrator, update_daily_performance
# # After aggregating daily metrics:
# update_daily_performance("momentum_v2", paper_roi=0.02, live_roi=0.06, precision=0.67, win_rate=0.27, drawdown=0.012, fee_ratio=0.37)
# update_daily_performance("venue_selector_v3", paper_roi=0.01, live_roi=0.05, precision=0.69, win_rate=0.28, drawdown=0.011, fee_ratio=0.36)
# # Then run scaling:
# summary = portfolio_scaling_orchestrator()
# print("Portfolio scaling summary:", summary)
#
# Execution bridge:
# from src.phase_261_265 import pre_trade_portfolio_gate
# gate = pre_trade_portfolio_gate(strategy_name)
# if gate["mode"] == "portfolio":
#     final_size *= gate["weight"]  # scale by portfolio allocation
# elif gate["mode"] == "canary":
#     final_size *= gate["weight"]  # scale by canary live_capital
# else:
#     route_paper_trade(...)

if __name__ == "__main__":
    # Demo with synthetic data
    # Seed CANARY_STATE with a canary strategy
    _write_json(CANARY_STATE, {
        "momentum_v2": {"live_capital": 0.10, "status": "canary"},
        "venue_selector_v3": {"live_capital": 0.10, "status": "canary"},
        "meanrev_v3": {"live_capital": 0.0, "status": "paper"}
    })
    # Append 7 days of performance for two strategies
    for _ in range(7):
        update_daily_performance("momentum_v2", paper_roi=0.02, live_roi=0.08, precision=0.70, win_rate=0.28, drawdown=0.012, fee_ratio=0.36)
        update_daily_performance("venue_selector_v3", paper_roi=0.01, live_roi=0.06, precision=0.68, win_rate=0.26, drawdown=0.010, fee_ratio=0.35)
        update_daily_performance("meanrev_v3", paper_roi=0.03, live_roi=0.02, precision=0.62, win_rate=0.22, drawdown=0.018, fee_ratio=0.41)
    # Run orchestrator
    summary = portfolio_scaling_orchestrator()
    print("Portfolio scaling summary:", json.dumps(summary, indent=2))