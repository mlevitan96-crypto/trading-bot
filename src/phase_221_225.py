# src/phase_221_225.py
#
# Phases 221–225: Precision Monitor, Rebate-Aware Venue Selector v2, Anomaly Sandbox
# - 221: Real-Time Precision Monitor (per-symbol precision/recall with decay)
# - 222: Confidence Nudge Engine (auto-adjust thresholds intra-day)
# - 223: Rebate-Aware Venue Selector v2 (latency + fill probability weighting)
# - 224: Anomaly Sandbox (isolates symbols that trigger halts/anomalies)
# - 225: Nightly Orchestrator (summaries + safe parameter updates)
#
# Wiring package: includes integration hooks to alpha_to_execution_adapter.py
# to drive immediate confidence nudges and venue selection improvements.

import os, json, time, math
from statistics import mean

# ---- Paths ----
EXECUTION_RESULTS = "logs/executed_orders.jsonl"         # bridge decisions and outcomes (append)
SYMBOL_CONF_THRESH = "logs/symbol_confidence_thresholds.json"  # existing thresholds
PRECISION_MONITOR = "logs/precision_monitor_221.json"    # live precision/recall metrics
CONF_NUDGE = "logs/confidence_nudge_222.json"            # nudges applied (audit)
VENUE_LATENCY = "logs/venue_latency_profile.json"        # { venue: {avg_ms, spread_bp_avg} }
MAKER_REBATE_MAP = "logs/maker_rebates.json"             # { venue: {symbol: rebate_bp} }
VENUE_SELECTOR_V2 = "logs/venue_selector_v2_223.json"    # selection rationale
ANOMALY_EVENTS = "logs/anomaly_events.jsonl"             # e.g., Phase 114 / 212 triggers
ANOMALY_SANDBOX = "logs/anomaly_sandbox_224.json"        # isolation state and shadow policy
ORCH_221_225 = "logs/orchestrator_221_225.json"          # nightly summary

def _now(): return int(time.time())
def _read_json(path, default=None): return json.load(open(path)) if os.path.exists(path) else (default if default is not None else {})
def _write_json(path, obj): os.makedirs(os.path.dirname(path), exist_ok=True); json.dump(obj, open(path, "w"), indent=2)
def _append_jsonl(path, obj): os.makedirs(os.path.dirname(path), exist_ok=True); open(path, "a").write(json.dumps(obj) + "\n")
def _read_jsonl(path): return [json.loads(l) for l in open(path)] if os.path.exists(path) else []

# ======================================================================
# 221 – Real-Time Precision Monitor (decay-weighted)
# Tracks per-symbol precision/recall with exponential decay over recent window.
# ======================================================================
def precision_monitor(decay=0.92, window=3000):
    results = _read_jsonl(EXECUTION_RESULTS)
    by_sym = {}
    for r in results[-window:]:
        sym = r.get("symbol")
        gd = r.get("gate_decision", {})
        approved = bool(gd.get("approved"))
        realized = gd.get("realized_roi", None)
        fees = gd.get("fees", 0.0)
        # Treat a positive realized net as a "hit" if approved
        hit = approved and realized is not None and (realized - fees) > 0
        # For recall proxy, count opportunities: approved decisions vs total considered
        if sym is None: continue
        rec = by_sym.setdefault(sym, {"precision": 0.5, "recall_proxy": 0.5, "n": 0})
        rec["precision"] = decay * rec["precision"] + (0.1 if hit else -0.1 if approved else 0.0)
        # recall_proxy increases when approved and hit; decreases when rejected but later outcome is unknown
        rec["recall_proxy"] = decay * rec["recall_proxy"] + (0.05 if approved else -0.02)
        rec["n"] += 1
    metrics = {sym: {"precision": round(max(0.0, min(1.0, v["precision"])), 4),
                     "recall_proxy": round(max(0.0, min(1.0, v["recall_proxy"])), 4),
                     "samples": v["n"]} for sym, v in by_sym.items()}
    _write_json(PRECISION_MONITOR, {"ts": _now(), "metrics": metrics})
    return metrics

# ======================================================================
# 222 – Confidence Nudge Engine
# Auto-nudges per-symbol confidence thresholds based on live precision drift.
# ======================================================================
def confidence_nudge_engine(max_step=0.03, precision_target=0.65, recall_target=0.55):
    metrics = _read_json(PRECISION_MONITOR, {"metrics": {}}).get("metrics", {})
    confs = _read_json(SYMBOL_CONF_THRESH, {})
    nudges = {}
    for sym, m in metrics.items():
        prec = m.get("precision", 0.5); recp = m.get("recall_proxy", 0.5); n = m.get("samples", 0)
        base_thr = confs.get(sym, {}).get("confidence_threshold", 0.75)
        # Policy: if precision < target, raise thr; if recall too low, lower thr slightly
        delta = 0.0
        if prec < precision_target: delta += min(max_step, (precision_target - prec) * 0.2)
        if recp < recall_target: delta -= min(max_step, (recall_target - recp) * 0.15)
        # Stabilize with samples: low samples => smaller moves
        scale = 0.5 if n < 50 else 1.0
        new_thr = round(max(0.6, min(0.9, base_thr + delta * scale)), 3)
        if abs(new_thr - base_thr) >= 0.005:
            confs.setdefault(sym, {})["confidence_threshold"] = new_thr
            nudges[sym] = {"old": base_thr, "new": new_thr, "precision": prec, "recall_proxy": recp, "samples": n}
    if nudges:
        _write_json(SYMBOL_CONF_THRESH, confs)
    _write_json(CONF_NUDGE, {"ts": _now(), "nudges": nudges})
    return nudges

# ======================================================================
# 223 – Rebate-Aware Venue Selector v2
# Chooses venue by combining maker rebate, latency, and fill probability estimate.
# ======================================================================
def venue_selector_v2(symbol, candidate_venues, spread_bp=6.0, taker_fee_bp=5.0, maker_fee_bp=2.0):
    rebates = _read_json(MAKER_REBATE_MAP, {})
    latency = _read_json(VENUE_LATENCY, {})
    scored = []
    for v in candidate_venues:
        rb_bp = rebates.get(v, {}).get(symbol, 0.0)
        net_maker_bp = maker_fee_bp - rb_bp
        lat_ms = latency.get(v, {}).get("avg_ms", 150)
        # crude fill probability: higher with lower latency and moderate spread
        fill_prob = max(0.2, min(0.95, (1.0 - (lat_ms/800.0)) * (1.0 if spread_bp <= 6 else 0.8)))
        # expected net cost favors maker if fill_prob high; otherwise taker
        maker_cost = net_maker_bp / max(0.5, fill_prob)
        taker_cost = taker_fee_bp
        prefer_maker = maker_cost <= taker_cost
        expected_cost = maker_cost if prefer_maker else taker_cost
        scored.append({"venue": v, "lat_ms": lat_ms, "rebate_bp": rb_bp, "fill_prob": round(fill_prob,3),
                       "prefer_maker": prefer_maker, "expected_cost_bp": round(expected_cost,3)})
    best = min(scored, key=lambda x: x["expected_cost_bp"]) if scored else {"venue": candidate_venues[0] if candidate_venues else "default", "prefer_maker": True, "expected_cost_bp": maker_fee_bp}
    choice = {"ts": _now(), "symbol": symbol, "best": best, "scores": scored}
    _write_json(VENUE_SELECTOR_V2, choice)
    return choice

# ======================================================================
# 224 – Anomaly Sandbox
# Isolates symbols that trigger halts/anomalies; routes them to shadow experiments.
# ======================================================================
def anomaly_sandbox(isolation_threshold=2):
    events = _read_jsonl(ANOMALY_EVENTS)
    counts = {}
    for e in events[-1000:]:
        sym = e.get("symbol")
        kind = e.get("type")  # e.g., "anomaly_defense", "shock_halt"
        if not sym: continue
        key = (sym, kind)
        counts[key] = counts.get(key, 0) + 1
    isolate = {}
    for (sym, kind), c in counts.items():
        if c >= isolation_threshold:
            isolate[sym] = {"state": "isolated", "reason": kind, "since_ts": _now(), "policy": {"trade_flow": 0.0, "shadow_flow": 0.3}}
    _write_json(ANOMALY_SANDBOX, {"ts": _now(), "isolated": isolate})
    return isolate

# ======================================================================
# 225 – Nightly Orchestrator (221–224)
# Runs precision monitor, confidence nudges, venue selector sanity, anomaly isolation.
# ======================================================================
def run_phase_221_225_nightly():
    pm = precision_monitor()
    nudges = confidence_nudge_engine()
    iso = anomaly_sandbox()
    summary = {
        "ts": _now(),
        "symbols_monitored": len(pm),
        "nudges_applied": len(nudges),
        "isolated_symbols": len(iso)
    }
    _write_json(ORCH_221_225, summary)
    return summary

# ----------------------------------------------------------------------
# Integration Hooks (use inside alpha_to_execution_adapter.py)
# ----------------------------------------------------------------------
def apply_live_confidence_nudge(symbol, confidence, default_thr=0.75):
    """Fetch latest nudged threshold for symbol and return decision boolean."""
    thr = _read_json(SYMBOL_CONF_THRESH, {}).get(symbol, {}).get("confidence_threshold", default_thr)
    return confidence >= thr, thr

def select_venue_with_v2(symbol, candidate_venues, spread_bp, fee_ratio):
    """Use v2 selector, produce order config adjustments."""
    choice = venue_selector_v2(symbol, candidate_venues, spread_bp=spread_bp)
    venue = choice["best"]["venue"]
    prefer_maker = choice["best"]["prefer_maker"]
    # Derive router offsets: favor slightly tighter if high fill_prob and low latency
    fill_prob = choice["best"].get("fill_prob", 0.6)
    lat_ms = choice["best"].get("lat_ms", 150)
    base_offset_bp = 0.5 if spread_bp <= 6 else 1.0
    fill_bonus = -0.1 if fill_prob > 0.8 and lat_ms < 120 else 0.0
    fee_penalty = 0.3 if fee_ratio > 0.6 else 0.0
    offset_bp = max(0.3, min(3.0, base_offset_bp + fill_bonus + fee_penalty))
    ttl_sec = 8 if lat_ms < 120 else 12 if lat_ms < 200 else 18
    order_cfg = {"order_type": "limit", "offset_bp": round(offset_bp,2), "ttl_sec": ttl_sec, "post_only": prefer_maker, "venue": venue}
    return {"venue": venue, "order_cfg": order_cfg, "selector": choice}

# Example usage in alpha_to_execution_adapter.py decision loop:
# -----------------------------------------------------------
# from phase_221_225 import apply_live_confidence_nudge, select_venue_with_v2
#
# ok_conf, conf_thr = apply_live_confidence_nudge(sym, confidence, default_thr=0.75)
# if not ok_conf:
#     append_symbol_audit(sym, {"reason": "low_conf_nudged", "confidence": confidence, "threshold": conf_thr})
#     blocked += 1
#     continue
#
# v2 = select_venue_with_v2(sym, candidate_venues=["venue_a","venue_b","default_venue"], spread_bp=current_spread_bp, fee_ratio=current_fee_ratio)
# venue = v2["venue"]
# order_cfg = v2["order_cfg"]
# # proceed to execution_gates() and, if approved, place_order with order_cfg
#
# Nightly:
# run_phase_221_225_nightly()

if __name__ == "__main__":
    run_phase_221_225_nightly()