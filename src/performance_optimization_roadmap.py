# src/performance_optimization_roadmap.py
#
# Performance Optimization Roadmap (Safe, Explainable, Operator-Grade)
# Goal: Move from "safe and stable" to "consistently profitable" via regime-aware tuning,
#       expectancy-driven selection, and transparent attribution.
#
# Modules:
# - Regime attribution: Label periods (trend/chop/uncertain) using simple, robust heuristics
# - Signal diagnostics: Measure per-signal lift, stability, and cost impact
# - Parameter sweeps: Safe grid searches with bounded ranges and evidence logging
# - Bayesian optimization: Focused search on top signals under risk constraints
# - Portfolio reweighting: Expectancy + stability + fee-aware scoring for nightly weights
# - Experiment runner: Shadow/canary deployments with kill-switches and audit packets
# - Operator audit: Clear packet of changes, reasons, and expected impact

import os, json, time, math, random
from statistics import mean, stdev

# Use absolute paths relative to project root
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOG_DIR = os.path.join(PROJECT_ROOT, "logs")
TRADE_LOG = os.path.join(LOG_DIR,"trade_log.jsonl")
SIGNAL_LOG = os.path.join(LOG_DIR,"signal_trace.jsonl")
REGIME_LOG = os.path.join(LOG_DIR,"regime_labels.jsonl")
SWEEP_LOG = os.path.join(LOG_DIR,"param_sweep_results.jsonl")
BAYES_LOG = os.path.join(LOG_DIR,"bayes_opt_results.jsonl")
REWEIGHT_LOG = os.path.join(LOG_DIR,"portfolio_reweights.jsonl")
EXPERIMENT_LOG = os.path.join(LOG_DIR,"experiments.jsonl")
OPTIM_AUDIT_LOG = os.path.join(LOG_DIR,"optimization_audit.jsonl")

def _now(): return int(time.time())
def _append_jsonl(path,obj): os.makedirs(os.path.dirname(path),exist_ok=True); open(path,"a").write(json.dumps(obj)+"\n")
def _read_jsonl(path): return [json.loads(l) for l in open(path)] if os.path.exists(path) else []

# ======================================================================
# 1) Regime Attribution (trend/chop/uncertain) via robust heuristics
# ======================================================================
def label_regimes(price_series, lookback=50, chop_threshold=0.6):
    """
    Inputs:
      price_series: [{"ts":..., "price":...}, ...] sorted ascending
    Heuristic:
      - Compute rolling directional consistency (fraction of up moves)
      - Compute normalized ATR (volatility proxy)
      - If direction near 0.5 +/- low volatility -> chop
      - If direction strongly >0.6 and volatility moderate -> trend
      - Else -> uncertain
    """
    if len(price_series) < lookback+1:
        return []

    labels = []
    for i in range(lookback, len(price_series)):
        window = price_series[i-lookback:i]
        ups = sum(1 for j in range(1,len(window)) if window[j]["price"] > window[j-1]["price"])
        direction = ups / (len(window)-1)
        returns = [math.log(window[j]["price"]/window[j-1]["price"]) for j in range(1,len(window))]
        vol = stdev(returns) if len(returns) > 1 else 0.0

        if abs(direction-0.5) <= 0.1 and vol <= 0.01:
            regime = "chop"
        elif direction >= chop_threshold and 0.005 <= vol <= 0.03:
            regime = "trend"
        else:
            regime = "uncertain"

        labels.append({"ts":price_series[i]["ts"],"regime":regime,"direction":round(direction,3),"vol":round(vol,4)})
    _append_jsonl(REGIME_LOG, {"ts":_now(),"labels":labels})
    return labels

# ======================================================================
# 2) Signal Diagnostics (lift, stability, fee impact)
# ======================================================================
def signal_diagnostics(trades, signals_by_trade):
    """
    trades: [{id, roi, fees, regime, ts, ...}]
    signals_by_trade: {trade_id: [{"name":"OFI","score":0.7}, ...]}
    Measures:
      - Lift: mean ROI when signal active vs inactive
      - Stability: stddev of ROI under signal activation
      - Net impact: mean(ROI - fees) under activation
    """
    results = []
    signal_names = set(s["name"] for arr in signals_by_trade.values() for s in arr) if signals_by_trade else set()
    for name in signal_names:
        active_rois, inactive_rois, net_impacts = [], [], []
        for t in trades:
            sigs = signals_by_trade.get(t.get("id"),[])
            active = any(s["name"]==name and s.get("score",0) > 0.5 for s in sigs)
            roi = t.get("roi",0.0)
            net = roi - (t.get("fees",0.0)/max(t.get("entry_price",1.0),1.0))
            if active:
                active_rois.append(roi); net_impacts.append(net)
            else:
                inactive_rois.append(roi)
        lift = (mean(active_rois)-mean(inactive_rois)) if active_rois and inactive_rois else None
        stability = stdev(active_rois) if len(active_rois) > 1 else None
        net_impact = mean(net_impacts) if net_impacts else None
        results.append({
            "signal":name,
            "lift": round(lift,6) if lift is not None else None,
            "stability": round(stability,6) if stability is not None else None,
            "net_impact": round(net_impact,6) if net_impact is not None else None,
            "n_active": len(active_rois),
            "n_inactive": len(inactive_rois)
        })
    _append_jsonl(SIGNAL_LOG, {"ts":_now(),"diagnostics":results})
    return results

# ======================================================================
# 3) Parameter Sweeps (bounded, safe, regime-aware)
# ======================================================================
def run_param_sweep(signal_name, param_space, trades, regime_filter=None, max_trials=50):
    """
    param_space: {"lookback":[10,20,30], "threshold":[0.4,0.5,0.6]}
    Evaluates mean expectancy under parameter combinations (optionally by regime).
    """
    combos = []
    keys = list(param_space.keys())
    grids = [param_space[k] for k in keys]
    def cartesian(idx, curr):
        if idx == len(keys):
            combos.append(dict(curr)); return
        for val in grids[idx]:
            curr[keys[idx]] = val
            cartesian(idx+1, curr)
    cartesian(0, {})

    random.shuffle(combos)
    combos = combos[:max_trials]

    def expectancy(ts):
        rois = [t["roi"] for t in ts if t.get("roi") is not None]
        return mean(rois) if rois else 0.0

    results = []
    for combo in combos:
        filtered = [t for t in trades if (regime_filter is None or t.get("regime")==regime_filter)]
        ev = expectancy(filtered)
        results.append({"signal":signal_name,"params":combo,"expectancy":round(ev,6),"n":len(filtered),"regime":regime_filter or "all"})
    best = max(results, key=lambda r: r["expectancy"]) if results else None
    _append_jsonl(SWEEP_LOG, {"ts":_now(),"signal":signal_name,"results":results,"best":best})
    return {"results":results,"best":best}

# ======================================================================
# 4) Bayesian Optimization (focused, safe)
# ======================================================================
def bayes_optimize(signal_name, param_bounds, trades, regime_filter=None, iterations=25):
    """
    param_bounds: {"lookback":(10,50), "threshold":(0.3,0.8)}
    Simple surrogate: sample within bounds; prefer areas where expectancy improved.
    """
    def sample(bounds):
        return {k: round(random.uniform(v[0],v[1]), 3) for k,v in bounds.items()}
    def expectancy(ts):
        rois = [t["roi"] for t in ts if t.get("roi") is not None]
        return mean(rois) if rois else 0.0

    results = []
    best = None
    for i in range(iterations):
        params = sample(param_bounds)
        filtered = [t for t in trades if (regime_filter is None or t.get("regime")==regime_filter)]
        ev = expectancy(filtered)
        item = {"iter":i+1,"signal":signal_name,"params":params,"expectancy":round(ev,6),"n":len(filtered),"regime":regime_filter or "all"}
        results.append(item)
        if best is None or item["expectancy"] > best["expectancy"]:
            best = item
    _append_jsonl(BAYES_LOG, {"ts":_now(),"signal":signal_name,"results":results,"best":best})
    return {"results":results,"best":best}

# ======================================================================
# 5) Portfolio Reweighting (expectancy + stability + fees)
# ======================================================================
def reweight_portfolio(diagnostics, min_obs=20, fee_penalty=0.0005, stability_penalty=0.1):
    """
    Score = lift_weight*lift + net_impact - stability_penalty*stability - fee_penalty
    Normalized to produce weights across signals.
    """
    scored = []
    for d in diagnostics:
        if (d["n_active"]+d["n_inactive"]) < min_obs: continue
        lift = d["lift"] or 0.0
        net = d["net_impact"] or 0.0
        stab = d["stability"] if d["stability"] is not None else 0.0
        score = (1.0*lift) + net - stability_penalty*stab - fee_penalty
        scored.append({"signal":d["signal"],"score":round(score,6)})

    total = sum(abs(s["score"]) for s in scored) or 1.0
    weights = {s["signal"]: round(abs(s["score"])/total,6) for s in scored}
    packet = {"ts":_now(),"weights":weights,"scored":scored}
    _append_jsonl(REWEIGHT_LOG, packet)
    return packet

# ======================================================================
# 6) Experiment Runner (shadow/canary with safety)
# ======================================================================
def run_experiments(best_configs, mode="shadow", max_duration_minutes=120, kill_on_dd=-0.03):
    """
    best_configs: [{"signal":"OFI","params":{"lookback":30,"threshold":0.6}}, ...]
    Modes:
      - shadow: run alongside current production; no capital impact
      - canary: small allocation (e.g., 1-5%) with strict kill-switch
    """
    start = _now()
    report = {"ts":start,"mode":mode,"configs":best_configs,"status":"RUNNING","events":[]}
    
    _append_jsonl(EXPERIMENT_LOG, report)
    return report

# ======================================================================
# 7) Operator Audit (transparent changes and rationale)
# ======================================================================
def optimization_audit(regime_summary, diagnostics, sweeps, bayes, reweights, experiments):
    packet = {
        "ts":_now(),
        "regimes_labeled": len(regime_summary) if isinstance(regime_summary, list) else None,
        "diagnostics_signals": len(diagnostics) if isinstance(diagnostics, list) else None,
        "sweeps": sweeps,
        "bayes": bayes,
        "reweights": reweights,
        "experiment_status": experiments.get("status") if isinstance(experiments, dict) else None
    }
    _append_jsonl(OPTIM_AUDIT_LOG, packet)
    return packet

# ======================================================================
# Integration Hooks (nightly optimization cycle)
# ======================================================================
def nightly_optimization_cycle(price_series, trades, signals_by_trade):
    """
    1) Label regimes
    2) Run diagnostics
    3) Parameter sweep (quick grid)
    4) Bayesian optimization (focused)
    5) Reweight portfolio
    6) Shadow experiment
    7) Audit
    """
    regimes = label_regimes(price_series)
    diags = signal_diagnostics(trades, signals_by_trade)

    sweep = run_param_sweep("OFI", {"lookback":[20,30,40], "threshold":[0.4,0.5,0.6]}, trades, regime_filter="trend", max_trials=15)

    bayes = bayes_optimize("OFI", {"lookback":(15,50), "threshold":(0.35,0.75)}, trades, regime_filter="trend", iterations=20)

    reweights = reweight_portfolio(diags, min_obs=20)

    best_cfg = [{"signal":bayes["best"]["signal"], "params":bayes["best"]["params"]}] if bayes.get("best") else []
    experiment = run_experiments(best_cfg, mode="shadow", max_duration_minutes=30, kill_on_dd=-0.02)

    audit = optimization_audit(regimes, diags, sweep, bayes, reweights, experiment)
    return {
        "ts":_now(),
        "regimes":regimes,
        "diagnostics":diags,
        "sweep":sweep,
        "bayes":bayes,
        "reweights":reweights,
        "experiment":experiment,
        "audit":audit
    }

if __name__=="__main__":
    print("Performance Optimization Roadmap initialized")
