# src/auto_correction.py
#
# Auto-Correction Module – Close the loop on reviews with automated learning
# - Per-trade learning: harvest execution, slippage, attribution, and outcomes
# - Sentiment integration: ingest market sentiment and map to regime-aware adjustments
# - Experiment manager: parameter sweeps and signal reweighting for flagged assets
# - Overlay toggles: enable/disable regime-aware overlays (mean reversion vs trend)
# - Feedback loop: write back adjustments to strategy configs and log audits
#
# Inputs:
#   reviews: output from run_asset_reviews(...) -> {"reviews":[...]}
#   per_trade_logs_by_asset: {symbol: [{"ts":..,"roi":..,"expected":..,"actual":..,"order":{...},"fills":[...],
#                                       "signals": {"Momentum":0.3,"OFI":0.2,...},
#                                       "features": {"sentiment":0.12,"vol":0.015,"chop":0.4}, ...}]}
#   sentiment_feed: [{"ts":..,"asset":"BTCUSDT","score":0.35},{"ts":..,"asset":"ALL","score":-0.1}, ...]
#
# Outputs:
#   adjustments packet per asset with parameter sweep plan, signal reweights, overlay toggles, exec router changes
#   logs to: logs/auto_correction.jsonl

import os, json, time, math
from statistics import mean

LOG_DIR = "logs"
AUTO_CORRECTION_LOG = os.path.join(LOG_DIR, "auto_correction.jsonl")

def _now(): return int(time.time())
def _append_jsonl(path,obj): os.makedirs(os.path.dirname(path),exist_ok=True); open(path,"a").write(json.dumps(obj)+"\n")

# ----------------------------------------------------------------------
# Per-trade learning – aggregate micro-insights
# ----------------------------------------------------------------------
def measure_slippage(expected, actual):
    return (actual - expected) / expected

def fill_quality(order, fills):
    total_filled = sum(f.get("size",0.0) for f in fills)
    completeness = total_filled / max(order.get("size",1.0), 1e-9)
    latencies = [f.get("latency_ms",0) for f in fills]
    avg_latency = mean(latencies) if latencies else 0.0
    latency_penalty = avg_latency/1000.0
    return completeness - latency_penalty

def learn_from_trades(trades):
    if not trades: 
        return {"n":0,"avg_slippage":0.0,"avg_fill_quality":0.0,"avg_roi":0.0,"signal_wr":{},"feature_corr":{}}
    slips = []
    fqs = []
    rois = []
    signal_hits = {}
    signal_count = {}
    feature_sum = {}
    feature_pnl = {}
    for t in trades:
        if "expected" in t and "actual" in t:
            slips.append(measure_slippage(t["expected"], t["actual"]))
        if "order" in t:
            fqs.append(fill_quality(t["order"], t.get("fills",[])))
        r = t.get("roi", 0.0); rois.append(r)
        sigs = t.get("signals", {})
        for s, w in sigs.items():
            signal_count[s] = signal_count.get(s,0) + 1
            if r > 0: signal_hits[s] = signal_hits.get(s,0) + 1
        feats = t.get("features", {})
        for f, val in feats.items():
            feature_sum[f] = feature_sum.get(f,0.0) + val
            feature_pnl[f] = feature_pnl.get(f,0.0) + (val * r)

    signal_wr = {s: round(signal_hits.get(s,0)/signal_count[s],4) for s in signal_count}
    feature_corr = {f: round(feature_pnl.get(f,0.0)/(abs(feature_sum.get(f,1e-9)) + 1e-9),6) for f in feature_sum}
    return {
        "n": len(trades),
        "avg_slippage": round(mean(slips) if slips else 0.0,6),
        "avg_fill_quality": round(mean(fqs) if fqs else 0.0,4),
        "avg_roi": round(mean(rois) if rois else 0.0,6),
        "signal_wr": signal_wr,
        "feature_corr": feature_corr
    }

# ----------------------------------------------------------------------
# Sentiment integration – map sentiment to regime-aware adjustments
# ----------------------------------------------------------------------
def aggregate_sentiment(asset, sentiment_feed, horizon_sec=6*3600):
    cutoff = _now() - horizon_sec
    scores = []
    for s in sentiment_feed or []:
        if s.get("ts",0) >= cutoff and (s.get("asset")==asset or s.get("asset")=="ALL"):
            scores.append(s.get("score",0.0))
    return round(mean(scores) if scores else 0.0, 4)

def sentiment_adjustments(sent_score, regime):
    adj = {"momentum_boost":0.0,"mean_rev_boost":0.0,"risk_reduction":0.0}
    if sent_score > 0.15:
        adj["momentum_boost"] = 0.2 if regime=="trend" else 0.1
    elif sent_score < -0.15:
        adj["mean_rev_boost"] = 0.2 if regime!="trend" else 0.1
        adj["risk_reduction"] = 0.1
    else:
        adj["risk_reduction"] = 0.05 if regime=="uncertain" else 0.0
    return adj

# ----------------------------------------------------------------------
# Experiment manager – parameter sweeps & signal reweighting
# ----------------------------------------------------------------------
def plan_parameter_sweeps(asset_packet, trade_learning):
    regime = asset_packet["regime"]
    avg_roi = trade_learning["avg_roi"]
    base = {
        "lookback": [10, 20, 40, 80],
        "threshold": [0.2, 0.35, 0.5],
        "stop_atr": [2, 3, 4],
        "take_atr": [3, 4, 5]
    }
    if regime == "trend" and avg_roi <= 0:
        base["momentum_window"] = [20, 50, 100, 150]
        base["breakout_z"] = [1.0, 1.5, 2.0]
    if regime == "chop":
        base["mean_rev_z"] = [0.8, 1.2, 1.6, 2.0]
        base["entry_cooldown"] = [2, 3, 5]
    return {"type":"parameter_sweep","grid":base,"min_trades":max(50, trade_learning["n"])}

def plan_signal_reweighting(asset_packet, trade_learning, sentiment_adj):
    wr = trade_learning["signal_wr"]
    reduce = [s for s, v in wr.items() if v < 0.5]
    increase = []
    if asset_packet["regime"]=="trend" or sentiment_adj["momentum_boost"]>0:
        increase.append("Momentum")
        increase.append("OFI")
    if asset_packet["regime"]=="chop" or sentiment_adj["mean_rev_boost"]>0:
        increase.append("MeanReversion")
    reweights = []
    for s in set(reduce):
        reweights.append({"signal":s,"delta_weight":-0.15})
    for s in set(increase):
        reweights.append({"signal":s,"delta_weight":+0.15})
    return {"type":"signal_reweight","changes":reweights}

# ----------------------------------------------------------------------
# Overlay toggles – regime-aware
# ----------------------------------------------------------------------
def plan_overlays(asset_packet, sentiment_adj):
    regime = asset_packet["regime"]
    overlays = []
    if regime == "chop" or sentiment_adj["mean_rev_boost"]>0:
        overlays.append({"overlay":"mean_reversion","enable":True,"params":{"zscore_entry":[1.0,1.5,2.0]}})
    if regime == "trend" or sentiment_adj["momentum_boost"]>0:
        overlays.append({"overlay":"trend_follow","enable":True,"params":{"momentum_window":[20,50,100]}})
    if sentiment_adj["risk_reduction"]>0:
        overlays.append({"overlay":"risk_reducer","enable":True,"params":{"position_scale":1.0 - sentiment_adj["risk_reduction"]}})
    return {"type":"overlays","changes":overlays}

# ----------------------------------------------------------------------
# Execution router – adaptive if slippage/fill degrade
# ----------------------------------------------------------------------
def plan_execution_router(trade_learning):
    recs = []
    if trade_learning["avg_slippage"] > 0.0015 or trade_learning["avg_fill_quality"] < 0.85:
        recs.append({"router":"adaptive","params":{"slice_parts":[3,5,7],"delay_ms":[50,100,150],"post_only":[False,True]}})
    if trade_learning["avg_slippage"] > 0.0020:
        recs.append({"router":"venue_pressure_limit","params":{"max_notional_per_min":0.5}})
    return {"type":"execution_router","changes":recs}

# ----------------------------------------------------------------------
# Build adjustment packet per asset
# ----------------------------------------------------------------------
def build_adjustments(asset_packet, trades, sentiment_feed):
    tl = learn_from_trades(trades)
    sent = aggregate_sentiment(asset_packet["asset"], sentiment_feed)
    sent_adj = sentiment_adjustments(sent, asset_packet["regime"])

    sweeps = plan_parameter_sweeps(asset_packet, tl)
    reweights = plan_signal_reweighting(asset_packet, tl, sent_adj)
    overlays = plan_overlays(asset_packet, sent_adj)
    exec_plan = plan_execution_router(tl)

    adjustments = {
        "ts": _now(),
        "asset": asset_packet["asset"],
        "tier": asset_packet["tier"],
        "regime": asset_packet["regime"],
        "learning": tl,
        "sentiment": {"score": sent, "adjustments": sent_adj},
        "plans": {"sweeps":sweeps, "reweights":reweights, "overlays":overlays, "execution":exec_plan},
        "apply_rules": {
            "shadow_only_until": None if asset_packet["metrics"]["expectancy"]>0 else _now()+2*24*3600,
            "canary_min_trades": max(50, tl["n"]),
            "capacity_checks": True
        }
    }
    _append_jsonl(AUTO_CORRECTION_LOG, {"adjustments": adjustments})
    return adjustments

# ----------------------------------------------------------------------
# Integration – run auto-correction for all reviewed assets
# ----------------------------------------------------------------------
def run_auto_corrections(multi_asset_summary, reviews, per_trade_logs_by_asset, sentiment_feed):
    """
    multi_asset_summary: output dict from multi_asset_cycle(...)
    reviews: output dict from run_asset_reviews(...), expects reviews["reviews"] list
    per_trade_logs_by_asset: {symbol: [trade dicts]}
    sentiment_feed: list of sentiment dicts
    """
    reviewed_assets = [r["asset"] for r in reviews.get("reviews", [])]
    packets = []
    for ap in multi_asset_summary.get("assets", []):
        if ap["asset"] not in reviewed_assets:
            continue
        trades = per_trade_logs_by_asset.get(ap["asset"], [])
        pkt = build_adjustments(ap, trades, sentiment_feed)
        packets.append(pkt)

    summary = {"ts": _now(), "assets_auto_corrected": [p["asset"] for p in packets], "count": len(packets)}
    _append_jsonl(AUTO_CORRECTION_LOG, {"operator_summary": summary})
    return {"adjustments": packets, "summary": summary}

# ----------------------------------------------------------------------
# Wiring hook – apply adjustments to strategy configs
# ----------------------------------------------------------------------
def apply_adjustments_to_configs(adjustments_packets, config_store_path="configs/strategy_overrides.json"):
    os.makedirs(os.path.dirname(config_store_path), exist_ok=True)
    overrides = {"ts": _now(), "assets": {}}
    for pkt in adjustments_packets:
        a = pkt["asset"]
        overrides["assets"][a] = {
            "signal_reweights": pkt["plans"]["reweights"]["changes"],
            "overlays": pkt["plans"]["overlays"]["changes"],
            "execution_router": pkt["plans"]["execution"]["changes"],
            "parameter_sweep_grid": pkt["plans"]["sweeps"]["grid"],
            "apply_rules": pkt["apply_rules"]
        }
    with open(config_store_path, "w") as f:
        json.dump(overrides, f, indent=2)
    _append_jsonl(AUTO_CORRECTION_LOG, {"config_overrides_written": config_store_path, "asset_count": len(overrides["assets"])})
    return overrides

# ----------------------------------------------------------------------
# CLI quick run – mock example
# ----------------------------------------------------------------------
if __name__ == "__main__":
    multi_asset_summary = {
        "assets":[
            {"asset":"ETHUSDT","tier":"major","regime":"trend","metrics":{"expectancy":-0.0004},"capacity":{"avg_slippage":0.0012}},
            {"asset":"BTCUSDT","tier":"major","regime":"chop","metrics":{"expectancy":0.005},"capacity":{"avg_slippage":0.0008}}
        ]
    }
    reviews = {"reviews":[{"asset":"ETHUSDT"},{"asset":"AVAXUSDT"}]}
    per_trade_logs_by_asset = {
        "ETHUSDT":[
            {"ts":_now()-1000,"roi":-0.01,"expected":100,"actual":100.15,"order":{"size":1.0},"fills":[{"size":0.6,"latency_ms":120},{"size":0.4,"latency_ms":200}],
             "signals":{"Momentum":0.3,"OFI":0.2,"MeanReversion":0.1},
             "features":{"sentiment":-0.2,"vol":0.018,"chop":0.3}},
            {"ts":_now()-800,"roi":0.012,"expected":99.8,"actual":99.81,"order":{"size":0.8},"fills":[{"size":0.5,"latency_ms":90},{"size":0.3,"latency_ms":140}],
             "signals":{"Momentum":0.25,"OFI":0.15,"MeanReversion":0.05},
             "features":{"sentiment":0.1,"vol":0.012,"chop":0.2}}
        ]
    }
    sentiment_feed = [
        {"ts":_now()-1200,"asset":"ALL","score":-0.05},
        {"ts":_now()-900,"asset":"ETHUSDT","score":-0.2},
        {"ts":_now()-400,"asset":"ALL","score":0.1}
    ]

    out = run_auto_corrections(multi_asset_summary, reviews, per_trade_logs_by_asset, sentiment_feed)
    overrides = apply_adjustments_to_configs(out["adjustments"])
    print(json.dumps({"summary":out["summary"],"overrides_written":bool(overrides["assets"])}, indent=2))
