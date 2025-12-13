# src/phase_266_270.py
#
# Phases 266–270: Portfolio Evolution Layer
# - 266: Regime Detector (portfolio-level regime classification)
# - 267: Dynamic Rebalancer (regime-aware target weights)
# - 268: Cross-Asset Scaler (asset-class scaling with unified risk budgets)
# - 269: Adaptive Portfolio Leverage (bands driven by stability and drawdown)
# - 270: Evolution Orchestrator (meta-feedback, checkpoints, single summary)
#
# Purpose: evolve the live portfolio dynamically as regimes shift, scale across assets,
# adapt leverage safely, and close the loop with meta-feedback for continuous improvement.

import os, json, time
from statistics import mean

# ---- Paths ----
PORTFOLIO_STATE = "logs/portfolio_state.json"            # weights, sector_load (from 261–265)
CANARY_STATE = "logs/canary_state.json"                  # strategy modes
PERF_HISTORY = "logs/strategy_performance_history.json"  # per-strategy daily metrics
SYMBOL_UNIVERSE = "logs/symbol_universe.json"            # symbols + sectors + asset_class
LEVERAGE_POLICY = "logs/leverage_policy.json"            # global + per-asset + per-strategy leverage
STATE_CHECKPOINT = "logs/state_checkpoint.json"          # unified checkpoint
EVOLUTION_SUMMARY = "logs/portfolio_evolution_summary.json"  # daily evolution summary
RISK_BUDGETS = "logs/risk_budgets.json"                  # per asset class risk caps
META_FEEDBACK = "logs/meta_feedback.json"                # evolution notes & proposed experiments

def _now(): return int(time.time())
def _read_json(path, default=None): return json.load(open(path)) if os.path.exists(path) else (default if default is not None else {})
def _write_json(path, obj): os.makedirs(os.path.dirname(path), exist_ok=True); json.dump(obj, open(path, "w"), indent=2)

# ======================================================================
# 266 – Regime Detector (portfolio-level)
# ======================================================================
def regime_detector(window_days=7):
    """
    Classify current regime using portfolio aggregates:
    - Momentum: positive avg(live_roi) and rising precision + win_rate
    - Mean-reversion: mixed/negative live_roi but improving after drawdowns
    - Choppy: low precision (<0.6) and low win rate (<0.25)
    Returns {"regime": str, "signals": {...}}
    """
    hist = _read_json(PERF_HISTORY, {})
    # Aggregate over strategies in portfolio mode
    canary = _read_json(CANARY_STATE, {})
    active = [s for s, st in canary.items() if st.get("status") == "portfolio"]
    if not active:
        return {"regime": "idle", "signals": {"avg_live_roi": 0.0, "avg_precision": 0.0, "avg_win_rate": 0.0, "avg_drawdown": 0.0}}

    def last_n(arr, n): return arr[-n:] if len(arr) >= n else arr
    live_rois, precisions, win_rates, drawdowns = [], [], [], []

    for strat in active:
        series = hist.get(strat, [])
        window = last_n(series, window_days)
        if not window: continue
        live_rois.append(mean([d.get("live_roi", 0.0) for d in window]))
        precisions.append(mean([d.get("precision", 0.0) for d in window]))
        win_rates.append(mean([d.get("win_rate", 0.0) for d in window]))
        drawdowns.append(mean([d.get("drawdown", 0.0) for d in window]))

    avg_live_roi = mean(live_rois) if live_rois else 0.0
    avg_precision = mean(precisions) if precisions else 0.0
    avg_win_rate = mean(win_rates) if win_rates else 0.0
    avg_drawdown = mean(drawdowns) if drawdowns else 0.0

    # Simple rule-based regime classification
    regime = "choppy"
    if avg_live_roi > 0 and avg_precision >= 0.62 and avg_win_rate >= 0.25:
        regime = "momentum"
    elif avg_live_roi <= 0 and avg_drawdown > 0.015 and avg_precision >= 0.6:
        regime = "mean_reversion"
    elif avg_precision < 0.6 or avg_win_rate < 0.25:
        regime = "choppy"

    return {
        "regime": regime,
        "signals": {
            "avg_live_roi": round(avg_live_roi, 6),
            "avg_precision": round(avg_precision, 6),
            "avg_win_rate": round(avg_win_rate, 6),
            "avg_drawdown": round(avg_drawdown, 6)
        }
    }

# ======================================================================
# 267 – Dynamic Rebalancer (regime-aware targets)
# ======================================================================
def dynamic_rebalancer(regime, current_weights, bias_strength=0.15):
    """
    Adjusts portfolio weights based on regime:
    - momentum: bias toward momentum/trend-following strategies
    - mean_reversion: bias toward MR strategies and reduce high-vol momentum
    - choppy: flatten allocations, reduce concentration
    Returns updated weights dictionary.
    """
    if not current_weights:
        return {}

    # Strategy tags (simple heuristics by name; replace with metadata if available)
    tags = {}
    for s in current_weights.keys():
        name = s.lower()
        if "momentum" in name or "trend" in name:
            tags[s] = "momentum"
        elif "meanrev" in name or "mr" in name or "reversion" in name:
            tags[s] = "mean_reversion"
        else:
            tags[s] = "neutral"

    new_w = dict(current_weights)
    if regime == "momentum":
        for s, w in current_weights.items():
            if tags[s] == "momentum": new_w[s] = round(w * (1 + bias_strength), 6)
            elif tags[s] == "mean_reversion": new_w[s] = round(w * (1 - bias_strength/2), 6)
    elif regime == "mean_reversion":
        for s, w in current_weights.items():
            if tags[s] == "mean_reversion": new_w[s] = round(w * (1 + bias_strength), 6)
            elif tags[s] == "momentum": new_w[s] = round(w * (1 - bias_strength/2), 6)
    elif regime == "choppy":
        avg = round(mean(list(current_weights.values())), 6)
        for s in current_weights.keys():
            new_w[s] = avg

    # Normalize to preserve total weight
    total = sum(new_w.values())
    if total > 0:
        scale = sum(current_weights.values()) / total
        for s in new_w:
            new_w[s] = round(new_w[s] * scale, 6)
    return new_w

# ======================================================================
# 268 – Cross-Asset Scaler (risk budgets)
# ======================================================================
def cross_asset_scaler(weights, asset_budgets=None):
    """
    Enforces per-asset-class risk budgets:
    - asset_budgets: {"crypto": 0.35, "fx": 0.20, "equities": 0.25} (example caps)
    Strategy→asset_class is derived from SYMBOL_UNIVERSE.sectors/asset_class mapping heuristics.
    Returns scaled weights and asset_loads.
    """
    if not weights:
        return {"weights": {}, "asset_loads": {}}

    uni = _read_json(SYMBOL_UNIVERSE, {"asset_class": {}, "sectors": {}, "symbols": []})
    asset_map = uni.get("asset_class", {})  # {symbol_or_strategy: "crypto"/"fx"/"equities"/...}
    budgets = asset_budgets or _read_json(RISK_BUDGETS, {"crypto": 0.35, "fx": 0.20, "equities": 0.25})

    asset_loads = {}
    for strat, w in weights.items():
        ac = asset_map.get(strat, "unknown")
        asset_loads[ac] = asset_loads.get(ac, 0.0) + w

    scaled = dict(weights)
    for ac, load in asset_loads.items():
        cap = budgets.get(ac, 0.20)
        if load > cap and load > 0:
            scale = cap / load
            for strat, w in weights.items():
                if asset_map.get(strat, "unknown") == ac:
                    scaled[strat] = round(w * scale, 6)
            asset_loads[ac] = round(cap, 6)

    # Re-normalize to original total
    original_total = sum(weights.values())
    new_total = sum(scaled.values())
    if new_total > 0:
        norm = original_total / new_total
        for strat in scaled:
            scaled[strat] = round(scaled[strat] * norm, 6)

    return {"weights": scaled, "asset_loads": asset_loads, "budgets": budgets}

# ======================================================================
# 269 – Adaptive Portfolio Leverage (bands)
# ======================================================================
def adaptive_portfolio_leverage(signals, current_leverage=None, base_band=(1.0, 1.5, 2.0)):
    """
    Adjusts portfolio leverage bands based on stability signals:
    - Increase toward mid/high band when precision >=0.65, win_rate >=0.27, drawdown <=1.5%
    - Reduce to base when precision <0.6 or drawdown >2%
    Stores in LEVERAGE_POLICY["portfolio"].
    """
    lp = _read_json(LEVERAGE_POLICY, {})
    cur = current_leverage or lp.get("portfolio", 1.0)

    precision = signals.get("avg_precision", 0.0)
    win_rate = signals.get("avg_win_rate", 0.0)
    drawdown = signals.get("avg_drawdown", 0.0)

    target = base_band[0]  # default 1.0×
    if precision >= 0.65 and win_rate >= 0.27 and drawdown <= 0.015:
        target = base_band[1]  # 1.5×
        if precision >= 0.70 and win_rate >= 0.30 and drawdown <= 0.012:
            target = base_band[2]  # 2.0×
    if precision < 0.60 or drawdown > 0.02:
        target = base_band[0]  # back to 1.0×

    # Smooth adjustment (no jumps >0.25)
    delta = max(min(target - cur, 0.25), -0.25)
    new_lev = round(cur + delta, 3)

    lp["portfolio"] = new_lev
    _write_json(LEVERAGE_POLICY, lp)
    return {"current": cur, "target": target, "new": new_lev}

# ======================================================================
# 270 – Evolution Orchestrator
# ======================================================================
def portfolio_evolution_orchestrator():
    """
    Nightly evolution:
    - Detect regime from portfolio signals
    - Rebalance weights per regime
    - Enforce cross-asset risk budgets
    - Adapt portfolio leverage bands
    - Write single summary and checkpoint state
    """
    # Load current portfolio weights
    pstate = _read_json(PORTFOLIO_STATE, {"weights": {}, "total_weight": 0.0})
    weights = pstate.get("weights", {})

    # Regime detection
    regime_info = regime_detector(window_days=7)
    regime = regime_info["regime"]
    signals = regime_info["signals"]

    # Dynamic rebalancing
    rebalanced = dynamic_rebalancer(regime, weights, bias_strength=0.15)

    # Cross-asset scaling (risk budgets)
    scaled = cross_asset_scaler(rebalanced)

    # Adaptive leverage
    lev = adaptive_portfolio_leverage(signals, current_leverage=_read_json(LEVERAGE_POLICY, {}).get("portfolio", 1.0))

    # Persist evolved portfolio state
    evolved_state = _read_json(PORTFOLIO_STATE, {})
    evolved_state["weights"] = scaled["weights"]
    evolved_state["total_weight"] = round(sum(scaled["weights"].values()), 6)
    evolved_state["asset_loads"] = scaled.get("asset_loads", {})
    _write_json(PORTFOLIO_STATE, evolved_state)

    # Meta-feedback: propose experiments
    feedback = _read_json(META_FEEDBACK, {"proposals": []})
    proposals = []
    if regime == "momentum":
        proposals.append({"type": "rebalance_bias", "toward": "momentum", "strength": 0.15})
        proposals.append({"type": "spread_widening", "condition": "vol_spike", "delta_bp": 0.2})
    elif regime == "mean_reversion":
        proposals.append({"type": "entry_offset", "toward": "mean_reversion", "delta_bp": 0.3})
        proposals.append({"type": "latency_bias", "prefer": "slower/liquidity-rich venues"})
    else:  # choppy
        proposals.append({"type": "flatten_allocations", "target": "equal", "notes": "reduce turnover"})
        proposals.append({"type": "risk_trim", "portfolio_leverage": "back_to_1.0x"})

    feedback["proposals"] = proposals
    _write_json(META_FEEDBACK, feedback)

    # Summary
    summary = {
        "ts": _now(),
        "regime": regime,
        "signals": signals,
        "weights_before": weights,
        "weights_after": scaled["weights"],
        "total_weight": evolved_state["total_weight"],
        "asset_loads": scaled.get("asset_loads", {}),
        "risk_budgets": scaled.get("budgets", {}),
        "portfolio_leverage": lev,
        "meta_feedback": proposals
    }
    _write_json(EVOLUTION_SUMMARY, summary)

    # Checkpoint
    ck = {
        "ts": _now(),
        "portfolio_state": evolved_state,
        "canary_state": _read_json(CANARY_STATE, {}),
        "leverage_policy": _read_json(LEVERAGE_POLICY, {}),
        "symbol_universe": _read_json(SYMBOL_UNIVERSE, {}),
        "perf_history": {k: v[-3:] for k, v in _read_json(PERF_HISTORY, {}).items()}  # lightweight snapshot
    }
    _write_json(STATE_CHECKPOINT, ck)

    return summary

# ----------------------------------------------------------------------
# Integration Hooks
# ----------------------------------------------------------------------
def get_portfolio_leverage():
    return float(_read_json(LEVERAGE_POLICY, {}).get("portfolio", 1.0))

def apply_portfolio_leverage_to_size(base_size):
    """
    Execution bridge helper: multiply size by current portfolio leverage.
    """
    return round(base_size * get_portfolio_leverage(), 6)

def regime_hint():
    """
    Returns current regime and signals; helps execution gates adjust thresholds.
    """
    info = regime_detector(window_days=7)
    return info

# Example wiring:
# from src.phase_266_270 import portfolio_evolution_orchestrator, apply_portfolio_leverage_to_size, regime_hint
# nightly_summary = portfolio_evolution_orchestrator()
# size = apply_portfolio_leverage_to_size(base_size)
# rh = regime_hint()
# print("Evolution summary:", nightly_summary)
# print("Leveraged size:", size, "Regime:", rh["regime"])

if __name__ == "__main__":
    # Demo with synthetic initial state
    _write_json(PORTFOLIO_STATE, {"weights": {"momentum_v2": 0.30, "venue_selector_v3": 0.20}, "total_weight": 0.50})
    # Synthetic universe mapping (strategy→asset class)
    _write_json(SYMBOL_UNIVERSE, {"asset_class": {"momentum_v2": "crypto", "venue_selector_v3": "crypto"}, "sectors": {}, "symbols": []})
    _write_json(RISK_BUDGETS, {"crypto": 0.35, "fx": 0.20, "equities": 0.25})

    # Seed performance history for regime detection (7 days)
    ph = _read_json(PERF_HISTORY, {})
    ph["momentum_v2"] = [{"live_roi": 0.06, "paper_roi": 0.02, "precision": 0.70, "win_rate": 0.28, "drawdown": 0.012} for _ in range(7)]
    ph["venue_selector_v3"] = [{"live_roi": 0.05, "paper_roi": 0.02, "precision": 0.66, "win_rate": 0.26, "drawdown": 0.011} for _ in range(7)]
    _write_json(PERF_HISTORY, ph)

    summary = portfolio_evolution_orchestrator()
    print("Portfolio evolution summary:", json.dumps(summary, indent=2))