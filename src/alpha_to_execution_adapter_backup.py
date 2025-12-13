# --- src/alpha_to_execution_adapter.py (Updated with Phases 171–180 wiring) ---

import os, json, time
from statistics import mean

# Paths
ALPHA_ROUTES = "logs/alpha_signal_routes.json"
COMPOSITE_TO_ROI = "logs/composite_to_roi_map.json"
SYMBOL_CONF_THRESH = "logs/symbol_confidence_thresholds.json"
SYMBOL_PERF = "logs/symbol_performance_metrics.json"
SYMBOL_RISK_BUDGET_V2 = "logs/symbol_risk_budget_v2.json"
SYMBOL_AUDIT = "logs/symbol_audit_trail.jsonl"
EXECUTION_RESULTS = "logs/executed_orders.jsonl"

# Import execution gates
from src.execution_gates import execution_gates, mark_trade

def _now(): return int(time.time())
def _read_json(path, default=None): return json.load(open(path)) if os.path.exists(path) else default
def _append_jsonl(path, obj): os.makedirs(os.path.dirname(path), exist_ok=True); open(path, "a").write(json.dumps(obj) + "\n")

# ---- Phase 172: Composite builder ----
def build_composite(symbol, tech_bias, micro=None, external=None):
    micro_alpha = micro.get(symbol, {}).get("micro_alpha", 0.0) if isinstance(micro, dict) else 0.0
    ext_alpha = external.get(symbol, {}).get("alpha_boost", 0.0) if isinstance(external, dict) else 0.0
    return round(0.5*tech_bias + 0.3*micro_alpha + 0.2*ext_alpha, 6)

# ---- Phase 173: MTF confirmer ----
def symbol_mtf_confirm(symbol):
    # Placeholder: replace with real timeframe checks
    return {"confirmed": True, "cooldown": False, "disagree_rate": 0.0}

# ---- Phase 176: ROI from calibration ----
def roi_from_composite(sym, comp, roi_map):
    m = roi_map.get(sym, {}).get("mapping", [])
    if not m: return 0.0
    nearest = min(m, key=lambda x: abs(x["comp"] - comp))
    return nearest["expected_roi"]

# ---- Phase 178: Sizing adapter v2 ----
def sizing_adapter_v2(symbol, confidence, recent_slippage_bp=5.0):
    risk = _read_json(SYMBOL_RISK_BUDGET_V2, {}).get(symbol, {}).get("risk_budget", 0.01)
    base_size = risk * (0.5 + 0.5 * confidence)
    slip_penalty = 0.8 if recent_slippage_bp > 6 else 1.0
    return round(max(0.0, min(0.05, base_size * slip_penalty)), 4)

# ---- Phase 179: Audit trail ----
def append_symbol_audit(symbol, snapshot):
    snap = {"ts": _now(), "symbol": symbol, **snapshot}
    _append_jsonl(SYMBOL_AUDIT, snap)

# ---- Updated Execution Bridge ----
def run_alpha_execution_bridge():
    orders = _read_json(ALPHA_ROUTES, [])
    roi_map = _read_json(COMPOSITE_TO_ROI, {})
    confs = _read_json(SYMBOL_CONF_THRESH, {})
    perf = _read_json(SYMBOL_PERF, {})

    executed, blocked = 0, 0
    for o in orders:
        sym = o.get("symbol")
        comp = o.get("composite", 0.0)
        direction = o.get("direction")
        confidence = o.get("confidence", 0.6)

        # Phase 173: MTF confirmation
        mtf = symbol_mtf_confirm(sym)
        if not mtf["confirmed"]:
            append_symbol_audit(sym, {"reason": "mtf_cooldown", "mtf": mtf})
            blocked += 1
            continue

        # Phase 176: Expected ROI
        pred_roi = roi_from_composite(sym, comp, roi_map)
        exp_recent = perf.get(sym, {}).get("expectancy", 0.0)
        expected_roi = pred_roi if pred_roi else exp_recent

        # Phase 177: Confidence threshold
        conf_thr = confs.get(sym, {}).get("confidence_threshold", 0.7)
        if confidence < conf_thr:
            append_symbol_audit(sym, {"reason": "low_conf", "confidence": confidence})
            blocked += 1
            continue

        # Phase 178: Sizing
        size = sizing_adapter_v2(sym, confidence)

        # Audit trail
        append_symbol_audit(sym, {
            "direction": direction,
            "composite": comp,
            "expected_roi": expected_roi,
            "confidence": confidence,
            "conf_thr": conf_thr,
            "size": size
        })

        # Pass into execution gates
        decision = execution_gates(
            symbol=sym,
            predicted_roi=expected_roi,
            mtf_confirmed=True,
            quality_score=confidence
        )
        result = {
            "ts": _now(),
            "symbol": sym,
            "direction": direction,
            "expected_roi": expected_roi,
            "confidence": confidence,
            "size": size,
            "gate_decision": decision
        }
        _append_jsonl(EXECUTION_RESULTS, result)

        if decision.get("approved"):
            # place_order(sym, order_type=decision["order_type"], size=size)
            mark_trade()
            executed += 1
        else:
            blocked += 1

    print(f"Execution bridge complete. Executed: {executed}, Blocked: {blocked}")
    return {"executed": executed, "blocked": blocked}

if __name__ == "__main__":
    run_alpha_execution_bridge()