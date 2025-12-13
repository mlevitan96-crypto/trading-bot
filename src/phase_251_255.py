# src/phase_251_255.py
#
# Phases 251–255: Burn-In Profit Validator
# - 251: Fee Ratio Monitor
# - 252: Win Rate Monitor
# - 253: Net PnL Monitor
# - 254: Correlation Monitor
# - 255: Canary Promotion Engine
#
# Purpose: enforce profit validation thresholds and auto-promotion/demotion rules
# during burn-in mode. Fully autonomous, no manual dashboard checks required.

import os, json, time, random

# ---- Paths ----
FEE_RATIO_LOG = "logs/fee_ratio_monitor.json"
WIN_RATE_LOG = "logs/win_rate_monitor.json"
PNL_LOG = "logs/net_pnl_monitor.json"
CORR_LOG = "logs/correlation_monitor.json"
CANARY_LOG = "logs/canary_promotion_engine.json"
COMMAND_BUS = "logs/command_bus.json"
LEVERAGE_POLICY = "logs/leverage_policy.json"
ROI_GATES = "logs/roi_gates.json"
SYMBOL_UNIVERSE = "logs/symbol_universe.json"

def _now(): return int(time.time())
def _read_json(path, default=None): return json.load(open(path)) if os.path.exists(path) else (default if default is not None else {})
def _write_json(path, obj): os.makedirs(os.path.dirname(path), exist_ok=True); json.dump(obj, open(path, "w"), indent=2)

# ======================================================================
# 251 – Fee Ratio Monitor
# ======================================================================
def fee_ratio_monitor(fee_ratio_series):
    avg_fee = sum(fee_ratio_series)/len(fee_ratio_series) if fee_ratio_series else 1.0
    actions = []
    if avg_fee > 0.5:  # >50%
        # tighten ROI gates
        gates = _read_json(ROI_GATES, {"roi_gate": 0.005})
        gates["roi_gate"] = round(gates["roi_gate"] + 0.01, 4)
        _write_json(ROI_GATES, gates)
        actions.append("tighten_roi_gate")
        actions.append("enforce_maker_first")
    result = {"ts": _now(), "avg_fee_ratio": avg_fee, "actions": actions}
    _write_json(FEE_RATIO_LOG, result)
    return result

# ======================================================================
# 252 – Win Rate Monitor
# ======================================================================
def win_rate_monitor(win_rate_series, symbol_expectancies):
    avg_win = sum(win_rate_series)/len(win_rate_series) if win_rate_series else 0.0
    actions = []
    if avg_win < 0.2:  # <20%
        # prune bottom 20% symbols
        sorted_syms = sorted(symbol_expectancies.items(), key=lambda x: x[1])
        prune_count = max(1, int(len(sorted_syms)*0.2))
        pruned = [s for s,_ in sorted_syms[:prune_count]]
        universe = _read_json(SYMBOL_UNIVERSE, {"symbols": []})
        universe["symbols"] = [s for s in universe.get("symbols", []) if s not in pruned]
        _write_json(SYMBOL_UNIVERSE, universe)
        actions.append({"pruned_symbols": pruned})
        actions.append("throttle_weak_symbols")
    result = {"ts": _now(), "avg_win_rate": avg_win, "actions": actions}
    _write_json(WIN_RATE_LOG, result)
    return result

# ======================================================================
# 253 – Net PnL Monitor
# ======================================================================
def net_pnl_monitor(pnl_series):
    negative_streak = 0
    for v in pnl_series[-3:]:
        if v < 0: negative_streak += 1
    actions = []
    if negative_streak >= 3:
        lev = _read_json(LEVERAGE_POLICY, {})
        for sym in lev:
            lev[sym]["leverage"] = min(1.2, lev[sym].get("leverage", 1.0))
        _write_json(LEVERAGE_POLICY, lev)
        actions.append("cap_leverage_1.2x")
        actions.append("pause_challengers")
    result = {"ts": _now(), "negative_streak": negative_streak, "actions": actions}
    _write_json(PNL_LOG, result)
    return result

# ======================================================================
# 254 – Correlation Monitor
# ======================================================================
def correlation_monitor(corr_series):
    avg_corr = sum(corr_series)/len(corr_series) if corr_series else 0.0
    actions = []
    if avg_corr > 0.75:
        actions.append("bias_underrepresented_sectors")
    result = {"ts": _now(), "avg_corr": avg_corr, "actions": actions}
    _write_json(CORR_LOG, result)
    return result

# ======================================================================
# 255 – Canary Promotion Engine
# ======================================================================
def canary_promotion_engine(canary_metrics):
    """
    canary_metrics example:
    {
      "flow_name": "venue_selector_v3",
      "lift": 0.07,
      "samples": 50,
      "fee_ratio_delta": -0.05,
      "precision_delta": +0.05
    }
    """
    decision = "hold"
    if canary_metrics["lift"] >= 0.05 and canary_metrics["samples"] >= 30 and canary_metrics["fee_ratio_delta"] <= 0 and canary_metrics["precision_delta"] >= 0:
        decision = "promote"
    elif canary_metrics["lift"] <= 0 or canary_metrics["precision_delta"] < 0:
        decision = "demote"
    result = {"ts": _now(), "flow_name": canary_metrics["flow_name"], "decision": decision, "metrics": canary_metrics}
    log = _read_json(CANARY_LOG, {"routes": []})
    log["routes"].append(result)
    _write_json(CANARY_LOG, log)
    return result

# ======================================================================
# Burn-In Profit Validator Orchestrator
# ======================================================================
def run_burnin_validator(fee_ratio_series, win_rate_series, pnl_series, corr_series, symbol_expectancies, canary_metrics_list):
    fr = fee_ratio_monitor(fee_ratio_series)
    wr = win_rate_monitor(win_rate_series, symbol_expectancies)
    pn = net_pnl_monitor(pnl_series)
    co = correlation_monitor(corr_series)
    ca = [canary_promotion_engine(m) for m in canary_metrics_list]
    summary = {
        "ts": _now(),
        "fee_ratio": fr,
        "win_rate": wr,
        "net_pnl": pn,
        "correlation": co,
        "canary": ca
    }
    _write_json("logs/burnin_validator_summary.json", summary)
    return summary

# ----------------------------------------------------------------------
# Integration Hooks for execution bridge
# ----------------------------------------------------------------------
def pre_trade_profit_gates(fee_ratio_series, win_rate_series, pnl_series, corr_series, symbol_expectancies, canary_metrics_list):
    return run_burnin_validator(fee_ratio_series, win_rate_series, pnl_series, corr_series, symbol_expectancies, canary_metrics_list)

# Example usage in nightly orchestrator:
# from phase_251_255 import run_burnin_validator
# summary = run_burnin_validator(fee_ratio_series=[0.42,0.38,0.36],
#                                win_rate_series=[0.22,0.28,0.31],
#                                pnl_series=[0.01,-0.02,0.03],
#                                corr_series=[0.65,0.72,0.68],
#                                symbol_expectancies={"BTCUSDT":0.02,"ETHUSDT":-0.01,"SOLUSDT":0.03},
#                                canary_metrics_list=[{"flow_name":"venue_selector_v3","lift":0.07,"samples":50,"fee_ratio_delta":-0.05,"precision_delta":0.05}])
# print("Burn-in summary:", summary)

if __name__ == "__main__":
    # Demo run with synthetic data
    demo_summary = run_burnin_validator(
        fee_ratio_series=[0.42,0.38,0.36],
        win_rate_series=[0.22,0.28,0.31],
        pnl_series=[0.01,-0.02,0.03],
        corr_series=[0.65,0.72,0.68],
        symbol_expectancies={"BTCUSDT":0.02,"ETHUSDT":-0.01,"SOLUSDT":0.03},
        canary_metrics_list=[{"flow_name":"venue_selector_v3","lift":0.07,"samples":50,"fee_ratio_delta":-0.05,"precision_delta":0.05}]
    )
    print("Burn-in validator summary:", demo_summary)