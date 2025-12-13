# src/phase_161_170.py
#
# Phases 161–170: Symbol-Level Calibration, Tuning, Execution, Retirement, Dashboard, Orchestrator
# - 161: Composite→ROI Calibrator (per-symbol expectancy from actuals)
# - 162: Symbol Confidence Tuner (precision-driven thresholds)
# - 163: Symbol ROI Gate Tuner (fee ratio & drawdown aware)
# - 164: Symbol Trade Cap Manager (volatility & win-rate aware)
# - 165: Symbol Performance Tracker (win rate, fee ratio, drawdown, expectancy)
# - 166: Symbol Strategy Retirer (retire weak/expensive per-symbol strategies)
# - 167: Symbol Risk Budgeter v2 (performance & volatility informed)
# - 168: Symbol Execution Adapter (orders with tuned gates & sizing scaffolds)
# - 169: Symbol Operator Dashboard (visibility for symbol-level controls)
# - 170: Symbol Orchestrator v2 (nightly symbol-level run)
#
# Integrates with existing logs produced by Phases 111–160.

import os, json, time
from statistics import mean, stdev

# ---- Inputs ----
ATTR_LOG = "logs/attribution_events.jsonl"   # should contain per-trade composite_score & roi where available
TRADES_LOG = "logs/trades_futures.json"      # { "history": [ {symbol, roi, fees, ts, ...} ] }

# ---- Outputs ----
COMPOSITE_TO_ROI = "logs/composite_to_roi_map.json"
SYMBOL_CONF_THRESH = "logs/symbol_confidence_thresholds.json"
SYMBOL_ROI_GATES = "logs/symbol_roi_gates.json"
SYMBOL_TRADE_CAPS = "logs/symbol_trade_caps.json"
SYMBOL_PERF_METRICS = "logs/symbol_performance_metrics.json"
SYMBOL_RETIREMENTS = "logs/symbol_strategy_retirements.jsonl"
SYMBOL_RISK_BUDGET_V2 = "logs/symbol_risk_budget_v2.json"
SYMBOL_EXEC_ORDERS = "logs/symbol_execution_orders.json"
SYMBOL_OP_DASH = "logs/symbol_operator_dashboard.json"
SYMBOL_ORCH_V2 = "logs/symbol_orchestrator_v2.json"

# ---- Utils ----
def _read_json(path, default):
    return json.load(open(path)) if os.path.exists(path) else default
def _write_json(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    json.dump(obj, open(path, "w"), indent=2)
def _read_jsonl(path):
    return [json.loads(l) for l in open(path)] if os.path.exists(path) else []
def _append_jsonl(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    open(path, "a").write(json.dumps(obj) + "\n")
def _now(): return int(time.time())

# ======================================================================
# Phase 161 – Composite→ROI Calibrator (no proxy; uses actual outcomes)
# Builds per-symbol mapping of composite_score bins to expected ROI.
# ======================================================================
def calibrate_composite_to_roi():
    attr = _read_jsonl(ATTR_LOG)
    by_sym = {}
    for a in attr[-5000:]:
        sym = a.get("symbol")
        comp = a.get("composite_score")
        roi = a.get("roi")
        if sym is None or comp is None or roi is None:
            continue
        by_sym.setdefault(sym, []).append((comp, roi))
    out = {}
    for sym, pairs in by_sym.items():
        # Bin composite into deciles and compute mean ROI per bin
        if not pairs: continue
        comps = [c for c, _ in pairs]
        lo, hi = min(comps), max(comps)
        span = max(1e-6, hi - lo)
        bins = [{} for _ in range(10)]
        for comp, roi in pairs:
            idx = min(9, max(0, int(((comp - lo) / span) * 10)))
            bins[idx].setdefault("rois", []).append(roi)
            bins[idx]["comp_center"] = lo + (idx + 0.5) * (span / 10.0)
        mapping = [{"comp": round(b.get("comp_center", 0.0), 6),
                    "expected_roi": round(mean(b["rois"]), 6)} for b in bins if "rois" in b and b["rois"]]
        # Simple linear fallback if sparse
        if not mapping:
            avg_roi = round(mean([r for _, r in pairs]), 6)
            mapping = [{"comp": 0.0, "expected_roi": avg_roi}]
        out[sym] = {"mapping": mapping, "updated_ts": _now()}
    _write_json(COMPOSITE_TO_ROI, out)
    return out

def _roi_from_composite(sym, comp, roi_map):
    m = roi_map.get(sym, {}).get("mapping", [])
    if not m:
        return 0.0
    # nearest neighbor on comp centers
    nearest = min(m, key=lambda x: abs(x["comp"] - comp))
    return nearest["expected_roi"]

# ======================================================================
# Phase 162 – Symbol-Level Confidence Tuner
# Sets confidence thresholds per symbol from empirical precision.
# ======================================================================
def tune_symbol_confidence():
    attr = _read_jsonl(ATTR_LOG)
    stats = {}
    for a in attr[-5000:]:
        sym = a.get("symbol"); pred = a.get("prediction"); roi = a.get("roi")
        if sym is None or pred is None or roi is None:
            continue
        stats.setdefault(sym, {"hits": 0, "total": 0})
        hit = (pred == "positive" and roi > 0) or (pred == "negative" and roi < 0)
        stats[sym]["hits"] += 1 if hit else 0
        stats[sym]["total"] += 1
    out = {}
    for sym, s in stats.items():
        prec = s["hits"] / s["total"] if s["total"] > 0 else 0.5
        # Threshold policy: higher threshold when precision is mediocre
        thr = 0.65 if prec >= 0.6 else 0.7 if prec >= 0.5 else 0.8
        out[sym] = {"precision": round(prec, 4), "confidence_threshold": thr, "updated_ts": _now()}
    _write_json(SYMBOL_CONF_THRESH, out)
    return out

# ======================================================================
# Phase 163 – Symbol-Level ROI Gate Tuner
# ROI gate per symbol from fee ratio and drawdown.
# ======================================================================
def tune_symbol_roi_gates():
    trades = _read_json(TRADES_LOG, {"history": []}).get("history", [])
    by_sym = {}
    for t in trades[-5000:]:
        sym = t.get("symbol"); roi = t.get("roi", 0.0); fees = t.get("fees", 0.0)
        if sym is None: continue
        by_sym.setdefault(sym, []).append((roi, fees))
    out = {}
    for sym, vals in by_sym.items():
        gross = sum(r for r, f in vals)
        fees_sum = sum(f for r, f in vals)
        fee_ratio = fees_sum / max(1e-6, abs(gross))
        drawdown = min((r - f) for r, f in vals) if vals else 0.0
        # Gate policy: stricter when fees high or recent drawdown deep
        gate = 0.006 if fee_ratio > 0.6 else 0.004 if drawdown < -0.02 else 0.003
        out[sym] = {"fee_ratio": round(fee_ratio, 3), "drawdown": round(drawdown, 5), "roi_gate": gate, "updated_ts": _now()}
    _write_json(SYMBOL_ROI_GATES, out)
    return out

# ======================================================================
# Phase 164 – Symbol-Level Trade Cap Manager
# Max trades/hour per symbol from volatility and win rate.
# ======================================================================
def manage_symbol_trade_caps():
    trades = _read_json(TRADES_LOG, {"history": []}).get("history", [])
    by_sym = {}
    for t in trades[-2000:]:
        sym = t.get("symbol"); roi = t.get("roi", 0.0)
        if sym is None: continue
        by_sym.setdefault(sym, []).append(roi)
    out = {}
    for sym, rois in by_sym.items():
        win_rate = sum(1 for r in rois if r > 0) / len(rois) if rois else 0.0
        vol = stdev(rois) if len(rois) > 1 else 0.005
        cap = 1 if win_rate < 0.4 or vol > 0.02 else 2 if win_rate < 0.55 or vol > 0.01 else 3
        out[sym] = {"win_rate": round(win_rate, 4), "volatility": round(vol, 5), "max_trades_hour": cap, "updated_ts": _now()}
    _write_json(SYMBOL_TRADE_CAPS, out)
    return out

# ======================================================================
# Phase 165 – Symbol-Level Performance Tracker
# Win rate, fee ratio, drawdown, expectancy per symbol.
# ======================================================================
def track_symbol_performance():
    trades = _read_json(TRADES_LOG, {"history": []}).get("history", [])
    by_sym = {}
    for t in trades[-5000:]:
        sym = t.get("symbol"); roi = t.get("roi", 0.0); fees = t.get("fees", 0.0)
        if sym is None: continue
        by_sym.setdefault(sym, []).append((roi, fees))
    out = {}
    for sym, vals in by_sym.items():
        total = len(vals)
        wins = sum(1 for r, f in vals if (r - f) > 0)
        win_rate = wins / total if total else 0.0
        gross = sum(r for r, f in vals)
        fees_sum = sum(f for r, f in vals)
        fee_ratio = fees_sum / max(1e-6, abs(gross))
        drawdown = min((r - f) for r, f in vals) if vals else 0.0
        expectancy = mean([(r - f) for r, f in vals]) if vals else 0.0
        out[sym] = {
            "win_rate": round(win_rate, 4),
            "fee_ratio": round(fee_ratio, 4),
            "drawdown": round(drawdown, 6),
            "expectancy": round(expectancy, 6),
            "samples": total,
            "updated_ts": _now()
        }
    _write_json(SYMBOL_PERF_METRICS, out)
    return out

# ======================================================================
# Phase 166 – Symbol-Level Strategy Retirer
# Retire per-symbol strategies when win rate/fee ratio violate limits.
# ======================================================================
def retire_symbol_strategies():
    perf = _read_json(SYMBOL_PERF_METRICS, {})
    events = []
    for sym, p in perf.items():
        if p.get("win_rate", 0.0) < 0.3 or p.get("fee_ratio", 0.0) > 1.0:
            ev = {"symbol": sym, "reason": "low_win_or_high_fee", "ts": _now()}
            _append_jsonl(SYMBOL_RETIREMENTS, ev)
            events.append(ev)
    return events

# ======================================================================
# Phase 167 – Symbol-Level Risk Budgeter v2
# Dynamic risk budget informed by expectancy and volatility.
# ======================================================================
def budget_symbol_risk_v2():
    perf = _read_json(SYMBOL_PERF_METRICS, {})
    out = {}
    for sym, p in perf.items():
        base = 0.01
        # If volatility not tracked, estimate from expectancy variance proxy
        vol_proxy = abs(p.get("drawdown", 0.005))
        budget = base + 0.5 * max(0.0, p.get("expectancy", 0.0)) - 0.4 * vol_proxy
        out[sym] = {"risk_budget": round(max(0.002, min(0.03, budget)), 4), "updated_ts": _now()}
    _write_json(SYMBOL_RISK_BUDGET_V2, out)
    return out

# ======================================================================
# Phase 168 – Symbol-Level Execution Adapter
# Produces per-symbol order directives using tuned gates & mapped ROI.
# ======================================================================
def adapt_symbol_execution():
    roi_map = _read_json(COMPOSITE_TO_ROI, {})
    gates = _read_json(SYMBOL_ROI_GATES, {})
    confs = _read_json(SYMBOL_CONF_THRESH, {})
    caps = _read_json(SYMBOL_TRADE_CAPS, {})
    perf = _read_json(SYMBOL_PERF_METRICS, {})

    # Placeholder: iterate symbols present across configs
    syms = set(list(gates.keys()) + list(confs.keys()) + list(caps.keys()))
    orders = []
    for sym in syms:
        roi_gate = gates.get(sym, {}).get("roi_gate", 0.006)
        conf_thr = confs.get(sym, {}).get("confidence_threshold", 0.7)
        cap = caps.get(sym, {}).get("max_trades_hour", 2)

        # Use calibrated expected ROI from composite bins; fall back to expectancy
        expected_roi = roi_map.get(sym, {}).get("mapping", [])
        exp = perf.get(sym, {}).get("expectancy", 0.0)
        mapped_roi = expected_roi[0]["expected_roi"] if expected_roi else exp

        approved = (mapped_roi >= roi_gate)
        orders.append({
            "ts": _now(),
            "symbol": sym,
            "expected_roi": round(mapped_roi, 6),
            "roi_gate": roi_gate,
            "confidence_threshold": conf_thr,
            "max_trades_hour": cap,
            "approved": approved
        })
    _write_json(SYMBOL_EXEC_ORDERS, orders)
    return orders

# ======================================================================
# Phase 169 – Symbol-Level Operator Dashboard
# Consolidates symbol-level gates, performance, risk, and orders.
# ======================================================================
def generate_symbol_dashboard():
    dash = {
        "ts": _now(),
        "roi_gates": _read_json(SYMBOL_ROI_GATES, {}),
        "confidence_thresholds": _read_json(SYMBOL_CONF_THRESH, {}),
        "trade_caps": _read_json(SYMBOL_TRADE_CAPS, {}),
        "performance": _read_json(SYMBOL_PERF_METRICS, {}),
        "risk_budget": _read_json(SYMBOL_RISK_BUDGET_V2, {}),
        "execution_orders": _read_json(SYMBOL_EXEC_ORDERS, {})
    }
    _write_json(SYMBOL_OP_DASH, dash)
    return dash

# ======================================================================
# Phase 170 – Symbol-Level Orchestrator v2
# Nightly runner for all symbol-level phases.
# ======================================================================
def run_symbol_orchestrator():
    roi_map = calibrate_composite_to_roi()
    confs = tune_symbol_confidence()
    gates = tune_symbol_roi_gates()
    caps = manage_symbol_trade_caps()
    perf = track_symbol_performance()
    retirements = retire_symbol_strategies()
    risk = budget_symbol_risk_v2()
    orders = adapt_symbol_execution()
    dash = generate_symbol_dashboard()
    summary = {
        "ts": _now(),
        "symbols_processed": len(perf),
        "retirements": len(retirements),
        "orders_generated": len(orders)
    }
    _write_json(SYMBOL_ORCH_V2, summary)
    return summary

# ---- Unified Runner ----
def run_phase_161_170():
    res = run_symbol_orchestrator()
    print("Phases 161–170 executed. Per-symbol calibration, tuning, performance tracking, risk budgeting, execution directives, and dashboard generated.")
    return res

if __name__ == "__main__":
    run_phase_161_170()