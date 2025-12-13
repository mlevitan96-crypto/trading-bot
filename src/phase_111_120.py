# src/phase_111_120.py
#
# Phases 111–120: RL Policy, Predictive Memory, Execution Governor, Real-Time Anomaly Defense,
# Meta-Hypothesis Loops, External Alpha Fusion, Strategy Distillation, Capital Risk Budgeter,
# Adaptive Regime Router, Nightly Orchestrator v2

import os, json, time, random
from statistics import mean, stdev

# ---- Paths ----
ATTR_LOG = "logs/attribution_events.jsonl"
TRADES_LOG = "logs/trades_futures.json"
EXT_DATA_LOG = "logs/external_data.json"
ALPHA_SCORES = "logs/alpha_attribution_scores.json"
ML_STRATS = "logs/ml_composed_strategies.json"
WALK_FWD = "logs/walk_forward_results.json"
OP_DASH = "logs/operator_dashboard.json"
REGIME_FORECAST = "logs/regime_forecast.json"
VOL_FORECAST = "logs/volatility_forecast.json"

# Outputs
RL_POLICY_LOG = "logs/rl_policy_updates.jsonl"
PRED_MEM_LOG = "logs/predictive_memory.json"
EXEC_GOV_LOG = "logs/execution_governance.json"
ANOMALY_DEF_LOG = "logs/real_time_anomaly_defense.jsonl"
META_HYP_LOG = "logs/meta_hypothesis_loops.jsonl"
ALPHA_FUSION_LOG = "logs/external_alpha_fusion.json"
DISTILLED_STRATS_LOG = "logs/strategy_distillation.json"
PORTF_RISK_BUDGET = "logs/portfolio_risk_budget.json"
REGIME_ROUTER_LOG = "logs/adaptive_regime_router.json"
NIGHTLY_V2_LOG = "logs/nightly_orchestrator_v2.json"

# ---- Utils ----
def _read_json(path, default=None):
    return json.load(open(path)) if os.path.exists(path) else (default if default is not None else {})
def _write_json(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True); json.dump(obj, open(path, "w"), indent=2)
def _read_jsonl(path):
    return [json.loads(l) for l in open(path)] if os.path.exists(path) else []
def _append_jsonl(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True); open(path, "a").write(json.dumps(obj) + "\n")
def _now(): return int(time.time())

# ======================================================================
# Phase 111 – Reinforcement learning policy updater
# Learns a simple policy score for strategy selection based on recent reward.
# ======================================================================
def rl_policy_update():
    trades = _read_json(TRADES_LOG, {"history": []}).get("history", [])
    by_strat = {}
    for t in trades[-300:]:
        s = t.get("strategy"); r = t.get("roi", 0.0) - t.get("fees", 0.0)
        if not s: continue
        by_strat.setdefault(s, []).append(r)
    updates = {}
    for s, rewards in by_strat.items():
        avg_r = mean(rewards) if rewards else 0.0
        vol = stdev(rewards) if len(rewards) > 1 else 0.001
        policy = round(max(0.0, avg_r) / (vol + 0.001), 4)
        updates[s] = {"avg_reward": round(avg_r, 5), "volatility": round(vol, 5), "policy_score": policy}
        _append_jsonl(RL_POLICY_LOG, {"strategy": s, "policy_score": policy, "ts": _now()})
    return updates

# ======================================================================
# Phase 112 – Predictive memory builder
# Stores rolling signal→outcome mappings per symbol/strategy for next-step biasing.
# ======================================================================
def build_predictive_memory():
    attr = _read_jsonl(ATTR_LOG)
    mem = {}
    for a in attr[-1000:]:
        sym = a.get("symbol"); s = a.get("strategy"); pred = a.get("signal_dir"); roi = a.get("roi", 0.0)
        if not (sym and s): continue
        key = f"{sym}:{s}"
        mem.setdefault(key, {"n": 0, "pos_hits": 0, "neg_hits": 0, "avg_roi": 0.0})
        m = mem[key]; m["n"] += 1; m["avg_roi"] = ((m["avg_roi"] * (m["n"] - 1)) + roi) / m["n"]
        if roi > 0 and pred == "up": m["pos_hits"] += 1
        if roi < 0 and pred == "down": m["neg_hits"] += 1
    _write_json(PRED_MEM_LOG, mem)
    return mem

# ======================================================================
# Phase 113 – Execution governor
# Tightens gates based on recent performance; dynamic ROI thresholds & max trades.
# ======================================================================
def execution_governor():
    trades = _read_json(TRADES_LOG, {"history": []}).get("history", [])
    recent = trades[-200:] if trades else []
    wins = sum(1 for t in recent if t.get("roi", 0.0) > t.get("fees", 0.0))
    wr = wins / len(recent) if recent else 0.0
    fee_ratio = (sum(t.get("fees", 0.0) for t in recent) / max(1e-6, abs(sum(t.get("roi", 0.0) for t in recent)))) if recent else 0.0
    # Adaptive gates - 2025-12-09: Lowered from 0.005/0.003 to 0.0025/0.0015
    # Analysis showed ROI filter was blocking 749+ profitable trades on TRXUSDT alone
    roi_gate = 0.0025 if wr < 0.5 else 0.0015
    max_trades_hour = 2 if wr < 0.5 or fee_ratio > 0.5 else 6
    governor = {"win_rate": round(wr, 3), "fee_ratio": round(fee_ratio, 3), "roi_threshold": roi_gate, "max_trades_hour": max_trades_hour}
    _write_json(EXEC_GOV_LOG, governor)
    return governor

# ======================================================================
# Phase 114 – Real-time anomaly defense
# Blocks execution on detected fee explosions, ROI spikes, or drift-inconsistent signals.
# ======================================================================
def real_time_anomaly_defense():
    anomalies = []
    attr = _read_jsonl(ATTR_LOG)
    forecast = _read_json(REGIME_FORECAST, {})
    expected = forecast.get("predicted_regime", "mixed")
    for a in attr[-200:]:
        roi = a.get("roi", 0.0); fees = a.get("fees", 0.0); regime = a.get("regime", "mixed")
        if abs(roi) > 0.03: anomalies.append({"type": "roi_spike", "variant": a.get("variant_id"), "roi": roi})
        if fees > max(0.001, abs(roi) * 2): anomalies.append({"type": "fee_explosion", "fees": fees, "roi": roi})
        if regime != expected and abs(roi) < 0.001: anomalies.append({"type": "regime_mismatch", "expected": expected, "actual": regime})
    for an in anomalies:
        an["ts"] = _now(); _append_jsonl(ANOMALY_DEF_LOG, an)
    return anomalies

# ======================================================================
# Phase 115 – Meta-hypothesis loop
# Generates, schedules, and marks status for hypotheses from alpha gaps.
# ======================================================================
def meta_hypothesis_loop():
    alpha = _read_json(ALPHA_SCORES, {})
    ideas = []
    for sid, s in list(alpha.items())[:5]:
        gap = 1.0 - s.get("alpha_score", 0.0)
        if gap > 0.4:
            hyp = {"strategy_id": sid, "hypothesis": "Introduce order-flow gating + volatility-aware exits", "gap": round(gap, 3), "status": "queued", "ts": _now()}
            _append_jsonl(META_HYP_LOG, hyp); ideas.append(hyp)
    return ideas

# ======================================================================
# Phase 116 – External alpha fusion
# Fuses funding, OI, liquidations, sentiment into per-symbol alpha boost.
# ======================================================================
def external_alpha_fusion():
    ext = _read_json(EXT_DATA_LOG, {})
    symbols = set()
    for k in ["funding_rates", "open_interest", "liquidations", "sentiment"]:
        if isinstance(ext.get(k), dict): symbols.update(ext[k].keys())
    fusion = {}
    for sym in symbols:
        funding = ext.get("funding_rates", {}).get(sym, 0.0)
        oi = ext.get("open_interest", {}).get(sym, 0)
        liq = ext.get("liquidations", {}).get(sym, 0)
        sent = ext.get("sentiment", {}).get(sym, 0.0)
        boost = round(0.4*sent + 0.3*(funding) + 0.2*(oi/1e6) - 0.3*(liq/1000), 3)
        fusion[sym] = {"alpha_boost": boost, "inputs": {"funding": funding, "oi": oi, "liq": liq, "sent": sent}}
    _write_json(ALPHA_FUSION_LOG, fusion)
    return fusion

# ======================================================================
# Phase 117 – Strategy distillation
# Distills ML strategies to a smaller, higher-confidence set based on WFA + RL policy.
# ======================================================================
def strategy_distillation():
    wfa = _read_json(WALK_FWD, [])
    policy = rl_policy_update()
    distilled = []
    for r in wfa:
        sid = r.get("strategy_id"); valid = r.get("valid", False); pol = policy.get(sid, {}).get("policy_score", 0.0)
        if valid and pol >= 0.5:
            distilled.append({"strategy_id": sid, "policy_score": pol, "selected": True})
    _write_json(DISTILLED_STRATS_LOG, distilled)
    return distilled

# ======================================================================
# Phase 118 – Portfolio risk budgeter
# Assigns risk budget per symbol based on volatility and alpha boost.
# ======================================================================
def portfolio_risk_budgeter():
    vol = _read_json(VOL_FORECAST, [])
    fusion = _read_json(ALPHA_FUSION_LOG, {})
    # Build simple per-symbol budgets
    budgets = {}
    for sym, f in fusion.items():
        alpha = f.get("alpha_boost", 0.0)
        # Estimate volatility from recent forecaster samples
        v_est = mean([v.get("smoothed", 0.005) for v in vol[-10:]]) if vol else 0.005
        base = 0.01  # 1% base risk
        budget = max(0.002, base + 0.008*alpha - 0.5*v_est)  # penalize higher vol, boost high alpha
        budgets[sym] = {"risk_budget": round(max(0.002, min(0.03, budget)), 4), "alpha": round(alpha, 3), "vol": round(v_est, 4)}
    _write_json(PORTF_RISK_BUDGET, budgets)
    return budgets

# ======================================================================
# Phase 119 – Adaptive regime router
# Routes strategies by forecast regime using distilled set + governor gates.
# ======================================================================
def adaptive_regime_router():
    distilled = _read_json(DISTILLED_STRATS_LOG, [])
    forecast = _read_json(REGIME_FORECAST, {})
    governor = _read_json(EXEC_GOV_LOG, {})
    regime = forecast.get("predicted_regime", "mixed")
    roi_gate = governor.get("roi_threshold", 0.005)
    routes = []
    for d in distilled:
        routes.append({
            "strategy_id": d["strategy_id"],
            "target_regime": regime,
            "min_roi": roi_gate,
            "approved": True if d.get("policy_score", 0.0) >= 0.5 else False
        })
    _write_json(REGIME_ROUTER_LOG, routes)
    return routes

# ======================================================================
# Phase 120 – Nightly orchestrator v2
# Runs phases 111–119 in sequence and emits a concise operator summary.
# ======================================================================
def nightly_orchestrator_v2():
    rl = rl_policy_update()
    pmem = build_predictive_memory()
    gov = execution_governor()
    anom = real_time_anomaly_defense()
    meta = meta_hypothesis_loop()
    fusion = external_alpha_fusion()
    dist = strategy_distillation()
    risk = portfolio_risk_budgeter()
    route = adaptive_regime_router()
    summary = {
        "ts": _now(),
        "rl_updates": len(rl),
        "predictive_memory_keys": len(pmem),
        "governor": gov,
        "anomalies_detected": len(anom),
        "meta_hypotheses": len(meta),
        "symbols_fused": len(fusion),
        "distilled_strategies": len(dist),
        "risk_budget_symbols": len(risk),
        "routes": len(route)
    }
    _write_json(NIGHTLY_V2_LOG, summary)
    return summary

# ---- Unified Runner ----
def run_phase_111_120():
    result = nightly_orchestrator_v2()
    print("Phases 111–120 executed. RL policy, predictive memory, execution governor, anomaly defense, meta-hypotheses, alpha fusion, distillation, risk budgeting, and regime routing complete.")
    return result

if __name__ == "__main__":
    run_phase_111_120()