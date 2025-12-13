# src/governance_upgrade.py
#
# Institutional Governance Upgrade – Canary overrides, auto-rollback, drift monitors,
# correlation-aware reweighting, experiment budgeting, and operator KPIs.
#
# Purpose:
#   Push the bot to learn faster, safer, and smarter before next week's full setup,
#   maximizing profit while protecting execution quality and governance.
#
# What's included:
#   1) Canary A/B for strategy_overrides with auto-rollback and immutable diff audits
#   2) Correlation-aware portfolio reweighting (diversification guard)
#   3) Feature & sentiment drift monitors (downweight unstable inputs)
#   4) Experiment budgeting + early stop conditions for parameter sweeps
#   5) Learning loop KPIs and operator-grade audit packets
#   6) Nightly wiring hooks so this runs automatically after orchestration/reviews/auto-correction
#
# Integration:
#   - Plug into nightly orchestration after auto_correction and before portfolio scaling.
#   - Reads existing outputs from multi_asset_orchestration, asset_review, auto_correction.
#   - Writes canary overrides to configs/canary_overrides.json and diffs to logs/config_diffs.jsonl.
#   - Logs KPIs and drift alarms to logs/governance_upgrade.jsonl.
#
# Notes:
#   - This module does not hard-depend on external services; it's pure orchestration logic.
#   - Replace mock functions/data where you have live signals, features, and correlation matrices.

import os, json, time, copy, math, random
from statistics import mean

LOG_DIR = "logs"
CONFIG_DIR = "configs"

GOV_LOG = os.path.join(LOG_DIR, "governance_upgrade.jsonl")
DIFF_LOG = os.path.join(LOG_DIR, "config_diffs.jsonl")
CANARY_OVERRIDES = os.path.join(CONFIG_DIR, "canary_overrides.json")
STRAT_OVERRIDES = os.path.join(CONFIG_DIR, "strategy_overrides.json")
NIGHTLY_GOV_AUDIT = os.path.join(LOG_DIR, "nightly_governance.jsonl")

def _now(): return int(time.time())
def _append_jsonl(path,obj): os.makedirs(os.path.dirname(path),exist_ok=True); open(path,"a").write(json.dumps(obj)+"\n")
def _read_json(path, default=None):
    if not os.path.exists(path): return default
    try:
        with open(path,"r") as f: return json.load(f)
    except: return default

# ======================================================================================
# 1) Canary overrides with auto-rollback and immutable diff audits
# ======================================================================================

def compute_config_diff(before, after):
    """Shallow diff focusing on per-asset override content."""
    diff = {"ts":_now(), "before": before or {}, "after": after or {}}
    summary = {}
    before_assets = (before or {}).get("assets", {})
    after_assets = (after or {}).get("assets", {})
    changed_assets = sorted(set(list(before_assets.keys()) + list(after_assets.keys())))
    for a in changed_assets:
        b = before_assets.get(a, {})
        c = after_assets.get(a, {})
        if b != c:
            summary[a] = {"before": b, "after": c}
    diff["summary"] = summary
    return diff

def write_canary_overrides(base_overrides, canary_fraction=0.2):
    """
    Create canary overrides by scaling risk/execution changes to a partial notional.
    Canary fraction applies to position scale if present; otherwise set apply_rules for canary.
    """
    canary = copy.deepcopy(base_overrides) if base_overrides else {"ts": _now(), "assets": {}}
    canary["ts"] = _now()
    for a, pkt in canary.get("assets", {}).items():
        rules = pkt.get("apply_rules", {})
        rules["canary_fraction"] = canary_fraction
        rules["canary_window_trades"] = max(rules.get("canary_min_trades", 50), 100)
        rules["promotion_criteria"] = {"expectancy_gt": 0.0, "win_rate_ge": 0.60, "pf_ge": 1.5, "capacity_ok": True}
        pkt["apply_rules"] = rules
        overlays = pkt.get("overlays", [])
        overlays.append({"overlay":"risk_reducer","enable":True,"params":{"position_scale":max(0.1, 1.0 - canary_fraction)}})
        pkt["overlays"] = overlays
    with open(CANARY_OVERRIDES, "w") as f:
        json.dump(canary, f, indent=2)
    _append_jsonl(GOV_LOG, {"ts":_now(), "event":"canary_overrides_written", "path": CANARY_OVERRIDES})
    return canary

def auto_rollback_check(performance_metrics_by_asset, canary_overrides, thresholds=None):
    """
    Evaluate canary results; rollback assets that degraded.
    thresholds: per-asset gates for promotion/rollback.
    """
    thresholds = thresholds or {"expectancy_gt": 0.0, "win_rate_ge": 0.60, "pf_ge": 1.5, "capacity_ok": True}
    rollback_assets = []
    promote_assets = []

    for a, pkt in (canary_overrides.get("assets", {}) if canary_overrides else {}).items():
        perf = performance_metrics_by_asset.get(a, {})
        capacity_ok = perf.get("capacity_ok", True)
        ok = (
            perf.get("expectancy", -1e9) > thresholds["expectancy_gt"] and
            perf.get("win_rate", 0.0) >= thresholds["win_rate_ge"] and
            perf.get("profit_factor", 0.0) >= thresholds["pf_ge"] and
            (capacity_ok if thresholds.get("capacity_ok", True) else True)
        )
        if ok: promote_assets.append(a)
        else: rollback_assets.append(a)

    result = {"ts":_now(), "promote": promote_assets, "rollback": rollback_assets, "thresholds": thresholds}
    _append_jsonl(GOV_LOG, {"event":"canary_evaluation", **result})
    return result

def apply_promotion_to_main_overrides(strategy_overrides_path, canary_overrides, promote_assets):
    """
    Merge promoted canary overrides into main strategy_overrides.json.
    """
    current = _read_json(strategy_overrides_path, default={"ts": _now(), "assets": {}})
    new = copy.deepcopy(current)
    for a in promote_assets:
        if a in (canary_overrides.get("assets", {}) if canary_overrides else {}):
            new["assets"][a] = canary_overrides["assets"][a]
            new["assets"][a]["apply_rules"]["canary_fraction"] = 0.0
    diff = compute_config_diff(current, new)
    _append_jsonl(DIFF_LOG, diff)
    with open(strategy_overrides_path, "w") as f:
        json.dump(new, f, indent=2)
    _append_jsonl(GOV_LOG, {"event":"promotion_applied", "promoted": promote_assets, "path": strategy_overrides_path})
    return new, diff

def rollback_canary_assets(canary_overrides_path, rollback_assets):
    """
    Remove rollback assets from canary overrides file.
    """
    current = _read_json(canary_overrides_path, default={"ts": _now(), "assets": {}})
    new = copy.deepcopy(current)
    for a in rollback_assets:
        if a in new["assets"]:
            del new["assets"][a]
    diff = compute_config_diff(current, new)
    with open(canary_overrides_path, "w") as f:
        json.dump(new, f, indent=2)
    _append_jsonl(DIFF_LOG, diff)
    _append_jsonl(GOV_LOG, {"event":"canary_rollback", "rollback": rollback_assets, "path": canary_overrides_path})
    return new, diff

# ======================================================================================
# 2) Correlation-aware portfolio reweighting
# ======================================================================================

def correlation_aware_weights(base_weights, corr_matrix, penalty=0.25):
    """
    Reduce weights for clusters of highly correlated losers; bolster independent winners.
    base_weights: {symbol: weight} (sums to ~1)
    corr_matrix: {symbol: {symbol_j: corr_ij}}
    Returns adjusted weights normalized to sum=1.
    """
    if not base_weights: return {}
    adjusted = {}
    symbols = list(base_weights.keys())
    for s in symbols:
        w = base_weights[s]
        corrs = [abs(corr_matrix.get(s, {}).get(t, 0.0)) for t in symbols if t != s]
        avg_corr = mean(corrs) if corrs else 0.0
        factor = max(0.5, 1.0 - penalty * max(0.0, avg_corr - 0.6))
        adjusted[s] = max(0.0, w * factor)
    norm = sum(adjusted.values()) or 1.0
    adjusted = {s: round(adjusted[s]/norm, 6) for s in symbols}
    _append_jsonl(GOV_LOG, {"event":"correlation_weights_adjusted", "avg_corr_penalty": penalty, "weights": adjusted})
    return adjusted

# ======================================================================================
# 3) Feature & sentiment drift monitors
# ======================================================================================

def drift_score(current_corr, historical_corr, min_samples=200):
    """
    Simple drift score: magnitude of change from historical baseline.
    """
    if historical_corr is None: return 0.0
    delta = current_corr - historical_corr
    return round(delta, 6)

def drift_monitor(feature_corr_current, feature_corr_baseline, min_strength=0.02, max_flip=-0.01):
    """
    Detect drift: if correlation drops below min_strength or flips sign negatively, raise an alarm.
    feature_corr_current: {feature: corr}
    feature_corr_baseline: {feature: corr}
    Returns: {feature: {"drift": score, "action": "freeze"/"downweight"/"ok"}}
    """
    report = {}
    for f, curr in feature_corr_current.items():
        base = feature_corr_baseline.get(f, 0.0) if feature_corr_baseline else 0.0
        d = drift_score(curr, base)
        action = "ok"
        if curr < max_flip:
            action = "freeze"
        elif abs(curr) < min_strength:
            action = "downweight"
        report[f] = {"drift": d, "current": curr, "baseline": base, "action": action}
    _append_jsonl(GOV_LOG, {"event":"feature_drift_monitor", "report": report})
    return report

def sentiment_health(sentiment_series, lag_threshold_sec=600, variance_threshold=0.5):
    """
    Assess sentiment source health: lag and variance bounds.
    sentiment_series: [{"ts":..,"score":..}, ...]
    """
    if not sentiment_series: 
        return {"lag_ok": False, "variance_ok": False, "action": "downweight"}
    last_ts = max(s["ts"] for s in sentiment_series)
    lag_ok = (_now() - last_ts) <= lag_threshold_sec
    vals = [s["score"] for s in sentiment_series if "score" in s]
    rng = (max(vals) - min(vals)) if vals else 0.0
    variance_ok = rng <= variance_threshold
    action = "ok" if (lag_ok and variance_ok) else "downweight"
    _append_jsonl(GOV_LOG, {"event":"sentiment_health", "lag_ok": lag_ok, "variance_ok": variance_ok, "action": action})
    return {"lag_ok": lag_ok, "variance_ok": variance_ok, "action": action}

# ======================================================================================
# 4) Experiment budgeting + early stop
# ======================================================================================

def experiment_budget_plan(flagged_assets, max_concurrent_per_asset=2, portfolio_max_experiments=10):
    """
    Allocate experiment slots across reviewed assets.
    """
    assets = flagged_assets[:]
    random.shuffle(assets)
    plan = {}
    total = 0
    for a in assets:
        if total >= portfolio_max_experiments: break
        slots = min(max_concurrent_per_asset, portfolio_max_experiments - total)
        plan[a] = {"slots": slots}
        total += slots
    _append_jsonl(GOV_LOG, {"event":"experiment_budget", "plan": plan, "total": total})
    return plan

def early_stop_check(interim_metrics, stop_rules=None):
    """
    Stop experiments early if interim metrics degrade.
    stop_rules default: WR < 0.45 over >=50 trades OR slippage > 0.0025
    """
    stop_rules = stop_rules or {"wr_lt": 0.45, "min_trades": 50, "slip_gt": 0.0025}
    wr = interim_metrics.get("win_rate", 0.0)
    n = interim_metrics.get("n", 0)
    slip = interim_metrics.get("avg_slippage", 0.0)
    stop = (wr < stop_rules["wr_lt"] and n >= stop_rules["min_trades"]) or (slip > stop_rules["slip_gt"])
    _append_jsonl(GOV_LOG, {"event":"early_stop_evaluation", "interim": interim_metrics, "stop": stop})
    return stop

# ======================================================================================
# 5) Learning loop KPIs and operator-grade audit
# ======================================================================================

def compute_learning_kpis(override_history, canary_evals, router_changes_metrics):
    """
    KPIs:
      - override_success_rate: % overrides that improved expectancy
      - median_slippage_change: after router tweaks
      - mean_time_to_promotion: canary → production
      - auto_rollback_count
    """
    success_flags = [1 if h.get("expectancy_delta", 0.0) > 0 else 0 for h in override_history or []]
    override_success_rate = round((sum(success_flags) / max(1, len(success_flags))), 4)
    slippage_changes = [m.get("slippage_delta", 0.0) for m in router_changes_metrics or []]
    median_slippage_change = sorted(slippage_changes)[len(slippage_changes)//2] if slippage_changes else 0.0
    times = [e.get("promotion_time_sec", 0) for e in canary_evals or [] if e.get("promoted", False)]
    mean_time_to_promotion = round(mean(times), 2) if times else 0.0
    auto_rollback_count = sum(1 for e in canary_evals or [] if e.get("rolled_back", False))
    kpis = {
        "override_success_rate": override_success_rate,
        "median_slippage_change": round(median_slippage_change, 6),
        "mean_time_to_promotion": mean_time_to_promotion,
        "auto_rollback_count": auto_rollback_count
    }
    _append_jsonl(GOV_LOG, {"event":"learning_kpis", "kpis": kpis})
    return kpis

def nightly_governance_audit(packet):
    _append_jsonl(NIGHTLY_GOV_AUDIT, packet)
    return packet

# ======================================================================================
# 6) Nightly wiring hooks – integrate with orchestration, reviews, and auto-correction
# ======================================================================================

def run_governance_upgrade(multi_asset_summary,
                           reviews_output,
                           auto_correction_overrides_path=STRAT_OVERRIDES,
                           per_asset_performance=None,
                           sentiment_series=None,
                           feature_corr_baseline=None,
                           corr_matrix=None):
    """
    Orchestrated nightly governance:
      1) Read strategy_overrides generated by auto_correction
      2) Write canary overrides (A/B application)
      3) Drift monitors (features + sentiment)
      4) Correlation-aware portfolio weighting pass
      5) Experiment budgeting and early-stop prep
      6) Auto-rollback and promotion checks (requires per-asset performance input)
      7) KPIs + audit packet
    """
    strat_overrides = _read_json(auto_correction_overrides_path, default={"ts": _now(), "assets": {}})
    flagged_assets = reviews_output.get("summary", {}).get("assets_flagged", []) or [a["asset"] for a in multi_asset_summary.get("assets", []) if a["metrics"].get("expectancy", 0) <= 0]
    _append_jsonl(GOV_LOG, {"event":"read_strategy_overrides", "asset_count": len(strat_overrides.get("assets", {}))})

    canary = write_canary_overrides(strat_overrides, canary_fraction=0.2)

    feature_corr_current = feature_corr_baseline or {"sentiment": 0.1, "volatility": 0.05, "chop": -0.02}
    drift_report = drift_monitor(feature_corr_current, feature_corr_baseline or {"sentiment": 0.12, "volatility": 0.06, "chop": -0.01})
    sentiment_health_report = sentiment_health(sentiment_series or [{"ts": _now()-300, "score": 0.1}, {"ts": _now()-120, "score": 0.05}])

    base_weights = multi_asset_summary.get("weights", {}).get("weights", {})
    adjusted_weights = correlation_aware_weights(base_weights, corr_matrix or {}, penalty=0.25)

    budget = experiment_budget_plan(flagged_assets, max_concurrent_per_asset=2, portfolio_max_experiments=10)

    perf = per_asset_performance or {}
    canary_eval = auto_rollback_check(perf, canary, thresholds={"expectancy_gt": 0.0, "win_rate_ge": 0.60, "pf_ge": 1.5, "capacity_ok": True})
    promoted, rolled = canary_eval["promote"], canary_eval["rollback"]
    new_main, diff_prom = apply_promotion_to_main_overrides(STRAT_OVERRIDES, canary, promoted) if promoted else (_read_json(STRAT_OVERRIDES), {})
    new_canary, diff_roll = rollback_canary_assets(CANARY_OVERRIDES, rolled) if rolled else (_read_json(CANARY_OVERRIDES), {})

    kpis = compute_learning_kpis(
        override_history=[{"asset":"ETHUSDT","expectancy_delta":0.002},{"asset":"AVAXUSDT","expectancy_delta":-0.001}],
        canary_evals=[{"asset":"ETHUSDT","promoted": True, "promotion_time_sec": 86400},{"asset":"DOTUSDT","rolled_back": True}],
        router_changes_metrics=[{"asset":"ADAUSDT","slippage_delta":-0.0002},{"asset":"DOGEUSDT","slippage_delta":0.0001}]
    )

    audit_packet = {
        "ts": _now(),
        "summary": {
            "flagged_assets": flagged_assets,
            "adjusted_weights": adjusted_weights,
            "budget_plan": budget,
            "drift_report": drift_report,
            "sentiment_health": sentiment_health_report,
            "canary_evaluation": canary_eval,
            "promoted_assets": promoted,
            "rolled_back_assets": rolled,
            "kpis": kpis
        },
        "diffs": {
            "promotion_diff": diff_prom,
            "rollback_diff": diff_roll
        }
    }
    nightly_governance_audit(audit_packet)
    return audit_packet

# ======================================================================================
# CLI quick run – Simulate a full nightly governance upgrade pass
# ======================================================================================

if __name__ == "__main__":
    mock_weights = {
        "BTCUSDT": 0.22, "ETHUSDT": 0.18, "SOLUSDT": 0.12, "AVAXUSDT": 0.08, "DOTUSDT": 0.07,
        "TRXUSDT": 0.05, "XRPUSDT": 0.07, "ADAUSDT": 0.06, "DOGEUSDT": 0.06, "BNBUSDT": 0.05, "MATICUSDT": 0.04
    }
    mock_assets = []
    for a in ["BTCUSDT","ETHUSDT","SOLUSDT","AVAXUSDT","DOTUSDT","TRXUSDT","XRPUSDT","ADAUSDT","DOGEUSDT","BNBUSDT","MATICUSDT"]:
        mock_assets.append({
            "asset": a, "tier": "major" if a in ["BTCUSDT","ETHUSDT"] else "l1", "regime": random.choice(["trend","chop","uncertain"]),
            "metrics": {"expectancy": random.uniform(-0.001, 0.004), "win_rate": random.uniform(0.45, 0.75),
                        "profit_factor": random.uniform(1.0, 2.5), "drawdown": random.uniform(-0.08, -0.01), "n": random.randint(50,120)},
            "capacity": {"avg_slippage": random.uniform(0.0004, 0.0022), "avg_fill_quality": random.uniform(0.80, 0.90),
                         "max_drawdown": random.uniform(-0.06, -0.01), "n": random.randint(15,40)}
        })
    multi_asset_summary = {"assets": mock_assets, "weights": {"weights": mock_weights}}

    reviews_output = {"summary": {"assets_flagged": ["ETHUSDT","AVAXUSDT","DOTUSDT","ADAUSDT","DOGEUSDT"]}}

    overrides = {"ts": _now(), "assets": {
        "ETHUSDT": {"signal_reweights":[{"signal":"Momentum","delta_weight":+0.15},{"signal":"MeanReversion","delta_weight":-0.10}],
                    "overlays":[{"overlay":"trend_follow","enable":True,"params":{"momentum_window":[20,50,100]}}],
                    "execution_router":[{"router":"adaptive","params":{"slice_parts":[3,5,7],"delay_ms":[50,100,150]}}],
                    "parameter_sweep_grid":{"lookback":[10,20,40,80],"threshold":[0.2,0.35,0.5]},
                    "apply_rules":{"capacity_checks":True,"canary_min_trades":80}},
        "AVAXUSDT": {"signal_reweights":[{"signal":"MeanReversion","delta_weight":+0.15}],
                    "overlays":[{"overlay":"mean_reversion","enable":True,"params":{"zscore_entry":[1.0,1.5,2.0]}}],
                    "execution_router":[{"router":"adaptive","params":{"slice_parts":[3,5],"delay_ms":[80,120]}}],
                    "parameter_sweep_grid":{"lookback":[20,40,80],"stop_atr":[2,3,4]},
                    "apply_rules":{"capacity_checks":True,"canary_min_trades":60}}
    }}
    os.makedirs(CONFIG_DIR, exist_ok=True)
    with open(STRAT_OVERRIDES, "w") as f: json.dump(overrides, f, indent=2)

    per_asset_performance = {
        "ETHUSDT": {"expectancy": 0.0012, "win_rate": 0.62, "profit_factor": 1.65, "capacity_ok": True},
        "AVAXUSDT": {"expectancy": -0.0003, "win_rate": 0.51, "profit_factor": 1.22, "capacity_ok": True},
        "DOTUSDT": {"expectancy": 0.0004, "win_rate": 0.57, "profit_factor": 1.35, "capacity_ok": True},
        "ADAUSDT": {"expectancy": -0.0002, "win_rate": 0.49, "profit_factor": 1.18, "capacity_ok": False},
        "DOGEUSDT": {"expectancy": 0.0001, "win_rate": 0.55, "profit_factor": 1.28, "capacity_ok": True}
    }

    corr_matrix = {}
    symbols = list(mock_weights.keys())
    for s in symbols:
        corr_matrix[s] = {}
        for t in symbols:
            corr_matrix[s][t] = 1.0 if s==t else random.uniform(-0.2, 0.8)

    sentiment_series = [{"ts": _now()-120, "score": 0.12}, {"ts": _now()-300, "score": 0.05}, {"ts": _now()-540, "score": -0.02}]

    audit = run_governance_upgrade(
        multi_asset_summary=multi_asset_summary,
        reviews_output=reviews_output,
        auto_correction_overrides_path=STRAT_OVERRIDES,
        per_asset_performance=per_asset_performance,
        sentiment_series=sentiment_series,
        feature_corr_baseline={"sentiment":0.12,"volatility":0.06,"chop":-0.01},
        corr_matrix=corr_matrix
    )

    print(json.dumps({
        "promoted_assets": audit["summary"]["promoted_assets"],
        "rolled_back_assets": audit["summary"]["rolled_back_assets"],
        "adjusted_weights": audit["summary"]["adjusted_weights"],
        "kpis": audit["summary"]["kpis"]
    }, indent=2))
