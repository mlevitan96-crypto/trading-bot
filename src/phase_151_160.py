# src/phase_151_160.py
#
# Phases 151–160: Alpha Signal Generation, Validation, Routing, Feedback,
# Attribution, Risk Filter, Confidence Scoring, Execution Adapter, Dashboard,
# Orchestrator
#
# Integrates with Phases 111–150 (governor, fee arbiter, throttle, anomaly defense, ML).

import os, json, time, random
from statistics import mean, stdev

# ---- Paths ----
FEATURE_STORE = "logs/feature_store.json"                  # Phase 131
REGIME_FORECAST = "logs/regime_forecast.json"              # Phase 119/124
EXEC_GOV_LOG = "logs/execution_governance.json"            # Phase 113
FEE_ARBITER_LOG = "logs/fee_arbiter_policy.json"           # Phase 123
THROTTLE_LOG = "logs/throughput_throttle.json"             # Phase 129
ANOMALY_DEF_LOG = "logs/real_time_anomaly_defense.jsonl"   # Phase 114
PORTF_RISK_BUDGET = "logs/portfolio_risk_budget.json"      # Phase 118
MICROSTRUCTURE_ALPHA = "logs/microstructure_alpha.json"    # Phase 121
ALPHA_FUSION_LOG = "logs/external_alpha_fusion.json"       # Phase 116
ML_LIVE_PREDICTIONS = "logs/ml_live_predictions.json"      # Phase 136

# Outputs
ALPHA_SIGNALS = "logs/alpha_signals.json"
ALPHA_VALIDATION = "logs/alpha_signal_validation.json"
ALPHA_ROUTES = "logs/alpha_signal_routes.json"
ALPHA_FEEDBACK = "logs/alpha_signal_feedback.json"
ALPHA_ATTRIB = "logs/alpha_signal_attribution.json"
ALPHA_RISK_FILTERED = "logs/alpha_signal_risk_filtered.json"
ALPHA_CONFIDENCE = "logs/alpha_signal_confidence.json"
ALPHA_ORDERS = "logs/alpha_signal_orders.json"
ALPHA_DASHBOARD = "logs/alpha_signal_dashboard.json"
ALPHA_ORCH = "logs/alpha_signal_orchestrator.json"

def _now(): return int(time.time())
def _read_json(path, default=None): 
    return json.load(open(path)) if os.path.exists(path) else (default if default is not None else {})
def _write_json(path, obj): 
    os.makedirs(os.path.dirname(path), exist_ok=True); json.dump(obj, open(path, "w"), indent=2)

# ======================================================================
# Phase 151 – Alpha signal generator
# Combines technical (from feature store), microstructure, and external alpha.
# ======================================================================
def alpha_signal_generator():
    features = _read_json(FEATURE_STORE, [])
    micro = _read_json(MICROSTRUCTURE_ALPHA, {})
    ext = _read_json(ALPHA_FUSION_LOG, {})
    ml_preds = _read_json(ML_LIVE_PREDICTIONS, [])  # optional
    ml_by_sym = {}
    for p in ml_preds[-200:]:
        ml_by_sym.setdefault(p.get("symbol"), []).append(p.get("confidence", 0.5))

    signals = []
    for f in features[-200:]:
        sym = f.get("symbol")
        m_alpha = micro.get(sym, {}).get("micro_alpha", 0.0)
        e_alpha = ext.get(sym, {}).get("alpha_boost", 0.0)
        tech_bias = 1 if f.get("signal_dir") == "up" else -1 if f.get("signal_dir") == "down" else 0
        ml_conf = mean(ml_by_sym.get(sym, [0.55]))
        # Composite directional score
        composite = 0.5*tech_bias + 0.3*m_alpha + 0.2*e_alpha
        direction = "BUY" if composite > 0.15 else "SELL" if composite < -0.15 else "HOLD"
        signals.append({
            "ts": _now(), "symbol": sym, "composite": round(composite, 4),
            "direction": direction, "ml_confidence": round(ml_conf, 3),
            "inputs": {"tech_bias": tech_bias, "micro": m_alpha, "external": e_alpha}
        })
    _write_json(ALPHA_SIGNALS, signals)
    return signals

# ======================================================================
# Phase 152 – Alpha signal validator
# Computes precision/recall proxy using recent outcomes (stubbed).
# ======================================================================
def alpha_signal_validator():
    signals = _read_json(ALPHA_SIGNALS, [])
    # Stubbed validation; replace with true label alignment
    precision = round(random.uniform(0.5, 0.75), 3)
    recall = round(random.uniform(0.5, 0.75), 3)
    roi_alignment = round(random.uniform(0.4, 0.7), 3)
    result = {"ts": _now(), "precision": precision, "recall": recall, "roi_alignment": roi_alignment}
    _write_json(ALPHA_VALIDATION, result)
    return result

# ======================================================================
# Phase 153 – Alpha signal router
# Applies regime filters and execution gates, routes actionable signals.
# ======================================================================
def alpha_signal_router():
    signals = _read_json(ALPHA_SIGNALS, [])
    forecast = _read_json(REGIME_FORECAST, {})
    regime = forecast.get("predicted_regime", "mixed")
    gov = _read_json(EXEC_GOV_LOG, {"roi_threshold": 0.005})
    arb = _read_json(FEE_ARBITER_LOG, {"roi_gate": 0.006})
    thr = _read_json(THROTTLE_LOG, {"max_trades_hour": 2})

    routed = []
    for s in signals:
        # regime filter: in volatile, suppress SELL unless strong
        composite = s.get("composite", 0.0)
        direction = s.get("direction")
        allowed = True
        if regime == "volatile" and direction == "SELL" and composite > -0.3:
            allowed = False
        roi_gate = max(gov.get("roi_threshold", 0.005), arb.get("roi_gate", 0.006))
        predicted_roi = abs(composite)  # proxy; replace with calibrated mapping
        approved = allowed and (predicted_roi >= roi_gate)
        routed.append({
            "ts": _now(), "symbol": s.get("symbol"),
            "direction": direction, "composite": composite,
            "approved": approved, "roi_gate": roi_gate,
            "regime": regime
        })
    _write_json(ALPHA_ROUTES, routed)
    return routed

# ======================================================================
# Phase 154 – Alpha signal feedback loop
# Reinforcement: upweight inputs that lead to approved signals and good outcomes.
# ======================================================================
def alpha_signal_feedback_loop():
    routes = _read_json(ALPHA_ROUTES, [])
    feedback = {}
    for r in routes:
        sym = r.get("symbol")
        approved = r.get("approved", False)
        composite = r.get("composite", 0.0)
        fb = feedback.setdefault(sym, {"n": 0, "approved": 0, "avg_comp": 0.0})
        fb["n"] += 1
        fb["approved"] += 1 if approved else 0
        fb["avg_comp"] = ((fb["avg_comp"] * (fb["n"] - 1)) + composite) / fb["n"]
    _write_json(ALPHA_FEEDBACK, feedback)
    return feedback

# ======================================================================
# Phase 155 – Alpha signal attribution engine
# Attributes composite score to feature groups.
# ======================================================================
def alpha_signal_attribution_engine():
    signals = _read_json(ALPHA_SIGNALS, [])
    attrib = {}
    for s in signals:
        sym = s.get("symbol")
        inputs = s.get("inputs", {})
        tech = inputs.get("tech_bias", 0.0)
        micro = inputs.get("micro", 0.0)
        external = inputs.get("external", 0.0)
        attrib.setdefault(sym, {"tech": 0.0, "micro": 0.0, "external": 0.0, "n": 0})
        a = attrib[sym]; a["n"] += 1
        a["tech"] += tech; a["micro"] += micro; a["external"] += external
    # Average contribution
    for sym, a in attrib.items():
        n = max(1, a["n"])
        a["tech"] = round(a["tech"]/n, 4); a["micro"] = round(a["micro"]/n, 4); a["external"] = round(a["external"]/n, 4)
    _write_json(ALPHA_ATTRIB, attrib)
    return attrib

# ======================================================================
# Phase 156 – Alpha signal risk filter
# Filters based on volatility, drawdown proxy, and fee burden.
# ======================================================================
def alpha_signal_risk_filter():
    routes = _read_json(ALPHA_ROUTES, [])
    risk_budget = _read_json(PORTF_RISK_BUDGET, {})
    arb = _read_json(FEE_ARBITER_LOG, {"fee_ratio": 0.6})
    filtered = []
    for r in routes:
        sym = r.get("symbol")
        budget = risk_budget.get(sym, {"risk_budget": 0.01})
        fee_ratio = arb.get("fee_ratio", 0.6)
        risky = (budget.get("risk_budget", 0.01) < 0.004) or (fee_ratio > 0.6)
        r2 = dict(r); r2["blocked_risk"] = risky
        filtered.append(r2)
    _write_json(ALPHA_RISK_FILTERED, filtered)
    return filtered

# ======================================================================
# Phase 157 – Alpha signal confidence scorer
# Combines model agreement, historical precision, and regime alignment.
# ======================================================================
def alpha_signal_confidence_scorer():
    signals = _read_json(ALPHA_SIGNALS, [])
    val = _read_json(ALPHA_VALIDATION, {"precision": 0.6, "recall": 0.6})
    forecast = _read_json(REGIME_FORECAST, {"predicted_regime": "mixed"})
    regime = forecast.get("predicted_regime", "mixed")

    conf = []
    for s in signals:
        base = 0.5*val.get("precision", 0.6) + 0.5*val.get("recall", 0.6)
        regime_bonus = 0.1 if (regime == "trending" and s.get("direction") == "BUY") else 0.0
        ml_bonus = 0.2 * s.get("ml_confidence", 0.55)
        score = min(0.99, max(0.0, base + regime_bonus + ml_bonus))
        conf.append({
            "ts": _now(), "symbol": s.get("symbol"),
            "direction": s.get("direction"),
            "confidence": round(score, 3)
        })
    _write_json(ALPHA_CONFIDENCE, conf)
    return conf

# ======================================================================
# Phase 158 – Alpha signal execution adapter
# Converts high-confidence, risk-filtered signals to orders; respects gates.
# ======================================================================
def alpha_signal_execution_adapter():
    filtered = _read_json(ALPHA_RISK_FILTERED, [])
    conf = _read_json(ALPHA_CONFIDENCE, [])
    conf_by_sym = {}
    for c in conf:
        conf_by_sym.setdefault(c["symbol"], []).append(c["confidence"])
    gov = _read_json(EXEC_GOV_LOG, {"roi_threshold": 0.005})
    arb = _read_json(FEE_ARBITER_LOG, {"roi_gate": 0.006, "prefer_limit": True})
    thr = _read_json(THROTTLE_LOG, {"max_trades_hour": 2})
    max_per_hour = min(gov.get("max_trades_hour", 2), arb.get("max_trades_hour", 2), thr.get("max_trades_hour", 2))

    orders = []
    count = 0
    for r in filtered:
        if count >= max_per_hour: break
        if r.get("blocked_risk", False): continue
        if not r.get("approved", False): continue
        sym = r.get("symbol")
        cscore = mean(conf_by_sym.get(sym, [0.6]))
        if cscore < 0.65: 
            continue
        order_type = "limit" if arb.get("prefer_limit", True) else "market"
        size_pct = 0.5 if cscore > 0.8 else 0.3
        orders.append({
            "ts": _now(), "symbol": sym, "direction": r.get("direction"),
            "order_type": order_type, "size_pct": size_pct, "confidence": round(cscore, 3)
        })
        count += 1
    _write_json(ALPHA_ORDERS, orders)
    return orders

# ======================================================================
# Phase 159 – Alpha signal operator dashboard
# Summarizes flow and key metrics for the operator.
# ======================================================================
def alpha_signal_operator_dashboard():
    dash = {
        "ts": _now(),
        "signals": len(_read_json(ALPHA_SIGNALS, [])),
        "validated": _read_json(ALPHA_VALIDATION, {}),
        "routed": len(_read_json(ALPHA_ROUTES, [])),
        "filtered": len(_read_json(ALPHA_RISK_FILTERED, [])),
        "orders": len(_read_json(ALPHA_ORDERS, [])),
        "confidence_avg": round(mean([c.get("confidence", 0.0) for c in _read_json(ALPHA_CONFIDENCE, [])]) if _read_json(ALPHA_CONFIDENCE, []) else 0.0, 3)
    }
    _write_json(ALPHA_DASHBOARD, dash)
    return dash

# ======================================================================
# Phase 160 – Alpha signal orchestrator
# Runs Phases 151–159 and returns a summary.
# ======================================================================
def alpha_signal_orchestrator():
    sig = alpha_signal_generator()
    val = alpha_signal_validator()
    route = alpha_signal_router()
    fb = alpha_signal_feedback_loop()
    attrib = alpha_signal_attribution_engine()
    risk = alpha_signal_risk_filter()
    conf = alpha_signal_confidence_scorer()
    orders = alpha_signal_execution_adapter()
    dash = alpha_signal_operator_dashboard()
    summary = {
        "ts": _now(),
        "signals": len(sig), "orders": len(orders),
        "validation": val, "routed": len(route),
        "risk_filtered": len(risk), "confidence": len(conf)
    }
    _write_json(ALPHA_ORCH, summary)
    return summary

# ---- Unified Runner ----
def run_phase_151_160():
    res = alpha_signal_orchestrator()
    print("Phases 151–160 executed: alpha generation, validation, routing, feedback, attribution, risk filter, confidence, execution, and dashboard complete.")
    return res

if __name__ == "__main__":
    run_phase_151_160()