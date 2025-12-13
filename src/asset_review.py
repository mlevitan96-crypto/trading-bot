# src/asset_review.py
#
# Automated Asset Review Module – Governance loop for underperformance
# - Detection: Flags assets breaching performance/capacity thresholds
# - Diagnostics: Signal attribution, regime alignment, execution anomalies
# - Recommendations: Parameter sweeps, signal reweighting, suspension gates
# - Audit: Full review packets logged for operator transparency
# - Integration Hook: Drop-in for nightly orchestration output
#
# Inputs expected from nightly orchestration:
#   multi_asset_summary["assets"] => list of asset packets:
#     {
#       "asset": "BTCUSDT",
#       "tier": "major"|"l1",
#       "regime": "trend"|"chop"|"uncertain",
#       "direction": float,
#       "vol": float,
#       "metrics": {"expectancy":..,"win_rate":..,"profit_factor":..,"drawdown":..,"n":int},
#       "capacity": {"avg_slippage":..,"avg_fill_quality":..,"max_drawdown":..,"n":int},
#       "scaling": {"current_mode":..,"next_mode":..,"action":..}
#     }
#
# Optional inputs:
#   signal_attribution_by_asset: {symbol: [{"signal":"Momentum","impact":0.002,"pnl":0.01,"wr":0.58}, ...]}
#     If missing, the module will infer placeholders and still generate useful recommendations.

import os, json, time
from statistics import mean

LOG_DIR = "logs"
ASSET_REVIEW_LOG = os.path.join(LOG_DIR, "asset_review.jsonl")

def _now(): return int(time.time())
def _append_jsonl(path,obj): os.makedirs(os.path.dirname(path),exist_ok=True); open(path,"a").write(json.dumps(obj)+"\n")

# ----------------------------------------------------------------------
# Thresholds – tier-aware gates
# ----------------------------------------------------------------------
def perf_breach(metrics, tier):
    """
    Returns True if asset performance is below governance thresholds.
    Majors face stricter gates.
    """
    wr_gate_major, wr_gate_l1 = 0.55, 0.50
    pf_gate_major, pf_gate_l1 = 1.3, 1.2
    dd_gate_major, dd_gate_l1 = -0.10, -0.12

    wr_gate = wr_gate_major if tier=="major" else wr_gate_l1
    pf_gate = pf_gate_major if tier=="major" else pf_gate_l1
    dd_gate = dd_gate_major if tier=="major" else dd_gate_l1

    return (
        metrics.get("expectancy",0.0) <= 0.0 or
        metrics.get("win_rate",0.0) < wr_gate or
        metrics.get("profit_factor",0.0) < pf_gate or
        metrics.get("drawdown",0.0) <= dd_gate
    )

def capacity_breach(capacity):
    return (
        capacity.get("avg_slippage",0.0) > 0.002 or
        capacity.get("avg_fill_quality",0.0) < 0.80 or
        capacity.get("max_drawdown",0.0) <= -0.05
    )

# ----------------------------------------------------------------------
# Diagnostics – signals, regime alignment, execution quality
# ----------------------------------------------------------------------
def diagnose_signals(attrib):
    """
    Summarize which signals are dragging.
    attrib: [{"signal":"Momentum","impact":0.002,"pnl":0.01,"wr":0.58}, ...]
    """
    if not attrib:
        return {
            "top_signals": [],
            "drag_signals": [],
            "notes": "No attribution provided; run signal diagnostics sweep."
        }
    # Rank by impact and PnL
    top = sorted(attrib, key=lambda x:(x.get("impact",0.0),x.get("pnl",0.0)), reverse=True)[:3]
    drag = sorted(attrib, key=lambda x:(x.get("impact",0.0),x.get("pnl",0.0)))[:3]
    return {
        "top_signals": [{"signal":a["signal"],"impact":a.get("impact",0.0),"wr":round(a.get("wr",0.0),4)} for a in top],
        "drag_signals": [{"signal":a["signal"],"impact":a.get("impact",0.0),"wr":round(a.get("wr",0.0),4)} for a in drag],
        "notes": "Signals ranked by impact and PnL."
    }

def diagnose_regime(regime, metrics, vol):
    """
    Check for regime mismatch: e.g., low PF/WR in trend, or overtrading in chop.
    """
    notes = []
    if regime == "trend" and metrics.get("profit_factor",0.0) < 1.3:
        notes.append("Profit factor low in trend regime; momentum/OFI may be mis-specified.")
    if regime == "chop" and metrics.get("win_rate",0.0) < 0.55:
        notes.append("Low WR in chop; consider mean-reversion overlays and tighter filters.")
    if vol and vol > 0.03:
        notes.append("High volatility; widen stops or reduce size to control adverse excursions.")
    return {"regime":regime,"vol":round(vol,6),"notes":notes or ["Regime alignment acceptable."]}

def diagnose_execution(capacity):
    """
    Identify execution anomalies driven by slippage, fill quality, or capacity drawdown.
    """
    notes = []
    if capacity.get("avg_slippage",0.0) > 0.002:
        notes.append("Excess slippage; reduce venue pressure or route to deeper books.")
    if capacity.get("avg_fill_quality",1.0) < 0.85:
        notes.append("Fill quality degraded; optimize order slicing and timing.")
    if capacity.get("max_drawdown",0.0) <= -0.05:
        notes.append("Capacity drawdown breached; scale back notional and retest.")
    return {"execution_notes": notes or ["Execution quality acceptable."]}

# ----------------------------------------------------------------------
# Recommendations – parameter sweeps, reweighting, suspension, routing
# ----------------------------------------------------------------------
def recommend_actions(asset_packet, diag_signals, diag_regime, diag_exec):
    asset = asset_packet["asset"]
    tier = asset_packet["tier"]
    regime = asset_packet["regime"]
    m = asset_packet["metrics"]
    c = asset_packet["capacity"]

    recs = []

    # Parameter sweeps
    recs.append({"type":"sweep","label":"lookback_grid","details":{"ranges":{"lookback":[10,20,40,80],"threshold":[0.2,0.35,0.5]}}})
    recs.append({"type":"sweep","label":"risk_controls","details":{"ranges":{"stop_atr":[2,3,4],"take_atr":[3,4,5]}}})

    # Signal reweighting
    if diag_signals["drag_signals"]:
        weak = [d["signal"] for d in diag_signals["drag_signals"]]
        recs.append({"type":"signals","label":"reweight_drag","details":{"reduce":weak,"increase":["OFI","Momentum","Carry"]}})

    # Regime-aware overlays
    if regime == "chop":
        recs.append({"type":"overlay","label":"mean_reversion","details":{"enable":True,"zscore_entry":[1.0,1.5,2.0]}})
    elif regime == "trend":
        recs.append({"type":"overlay","label":"trend_follow","details":{"enable":True,"momentum_window":[20,50,100]}})

    # Execution routing improvements
    if c.get("avg_slippage",0.0) > 0.0015 or c.get("avg_fill_quality",1.0) < 0.85:
        recs.append({"type":"execution","label":"adaptive_router","details":{"slice":{"parts":[3,5,7]},"delay_ms":[50,100,150],"post_only":[False,True]}})

    # Suspension gate (tier-aware)
    if m.get("expectancy",0.0) <= 0.0 and m.get("win_rate",0.0) < (0.55 if tier=="major" else 0.50):
        recs.append({"type":"suspension","label":"shadow_only","details":{"min_days":3,"reason":"Negative expectancy & low WR"}})

    # Canary constraints
    recs.append({"type":"scaling","label":"canary_constraints","details":{"max_alloc":0.03 if tier=="major" else 0.02,"min_trades":50,"capacity_checks":True}})

    return recs

# ----------------------------------------------------------------------
# Review packet builder
# ----------------------------------------------------------------------
def build_review_packet(asset_packet, signal_attrib=None):
    m, c = asset_packet["metrics"], asset_packet["capacity"]
    tier = asset_packet["tier"]

    perf_fail = perf_breach(m, tier)
    cap_fail = capacity_breach(c)

    if not (perf_fail or cap_fail):
        return None  # no review needed

    diag_sigs = diagnose_signals(signal_attrib or [])
    diag_reg = diagnose_regime(asset_packet["regime"], m, asset_packet.get("vol",0.0))
    diag_exe = diagnose_execution(c)
    recs = recommend_actions(asset_packet, diag_sigs, diag_reg, diag_exe)

    packet = {
        "ts": _now(),
        "asset": asset_packet["asset"],
        "tier": tier,
        "regime": asset_packet["regime"],
        "metrics": m,
        "capacity": c,
        "breaches": {"performance": perf_fail, "capacity": cap_fail},
        "diagnostics": {"signals": diag_sigs, "regime": diag_reg, "execution": diag_exe},
        "recommendations": recs,
        "scaling_state": asset_packet.get("scaling",{})
    }
    _append_jsonl(ASSET_REVIEW_LOG, packet)
    return packet

# ----------------------------------------------------------------------
# Integration hook – run reviews for all assets
# ----------------------------------------------------------------------
def run_asset_reviews(multi_asset_summary, signal_attribution_by_asset=None):
    """
    multi_asset_summary: output from multi_asset_cycle(...)
    signal_attribution_by_asset: optional dict per asset
    """
    assets = multi_asset_summary.get("assets", [])
    reviews = []
    for ap in assets:
        attrib = None
        if signal_attribution_by_asset:
            attrib = signal_attribution_by_asset.get(ap["asset"])
        pkt = build_review_packet(ap, attrib)
        if pkt:
            reviews.append(pkt)
    # Aggregate operator summary
    summary = {
        "ts": _now(),
        "total_assets": len(assets),
        "reviews_generated": len(reviews),
        "assets_flagged": [r["asset"] for r in reviews]
    }
    _append_jsonl(ASSET_REVIEW_LOG, {"operator_summary": summary})
    return {"reviews": reviews, "summary": summary}

# ----------------------------------------------------------------------
# CLI quick run – example integration
# ----------------------------------------------------------------------
if __name__ == "__main__":
    # Minimal mock of multi_asset_summary["assets"]
    mock_assets = [
        {
            "asset":"ETHUSDT","tier":"major","regime":"trend","direction":0.61,"vol":0.012,
            "metrics":{"expectancy":-0.0004,"win_rate":0.433,"profit_factor":1.05,"drawdown":-0.085,"n":75},
            "capacity":{"avg_slippage":0.0012,"avg_fill_quality":0.83,"max_drawdown":-0.03,"n":25},
            "scaling":{"current_mode":"shadow","next_mode":"shadow","action":"HOLD"}
        },
        {
            "asset":"BTCUSDT","tier":"major","regime":"chop","direction":0.51,"vol":0.009,
            "metrics":{"expectancy":0.0087,"win_rate":0.733,"profit_factor":2.54,"drawdown":-0.022,"n":92},
            "capacity":{"avg_slippage":0.0006,"avg_fill_quality":0.87,"max_drawdown":-0.02,"n":28},
            "scaling":{"current_mode":"shadow","next_mode":"canary","action":"PROMOTE"}
        }
    ]
    # Optional signal attribution for ETH
    signal_attrib = {
        "ETHUSDT":[
            {"signal":"Momentum","impact":-0.0012,"pnl":-0.006,"wr":0.42},
            {"signal":"OFI","impact":0.0003,"pnl":0.002,"wr":0.55},
            {"signal":"Sentiment","impact":-0.0005,"pnl":-0.002,"wr":0.48}
        ]
    }
    # Run reviews
    multi_asset_summary = {"assets": mock_assets}
    output = run_asset_reviews(multi_asset_summary, signal_attribution_by_asset=signal_attrib)
    print(json.dumps(output, indent=2))