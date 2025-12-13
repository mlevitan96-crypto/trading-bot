# src/operators_consolidation.py
#
# Operators’ Consolidation – Per-signal attribution logging, tag coverage alerts,
# canary pass/fail monitoring with retry logic, 24h regime-aware venue profiles,
# and a consolidated operator digest payload for nightly/intraday emails.
#
# What this adds:
#   1) Per-signal attribution logging: per asset+strategy node WR/PF/EV by signal
#   2) Tag coverage alerts: nightly digest includes % untagged trades and blocklist status
#   3) Canary monitoring: explicit pass/fail reasons (statistics vs capacity) and auto-retry plan
#   4) 24h regime-aware venue profiles: rolling hourly profiles with volatility-aware decay
#   5) Operators’ digest payload: promotions, rollbacks, tag health, venue changes, capacity status
#
# Integration:
#   - Intraday (every 5–10 min): call update_venue_profiles_24h(...) and update_signal_attribution(...)
#   - Nightly (post-promoter, pre-scaling): call canary_monitor_and_retry(...), tag_coverage_audit(...),
#     build_operator_digest(...), then send via your existing SMTP reporting module.
#
# Files:
#   - configs/strategy_registry.json        (champions/contenders/history)
#   - configs/intraday_overrides.json       (live intraday params/router/scale)
#   - configs/venue_profiles_24h.json       (rolling hourly per asset+venue profiles)
#   - logs/signal_attribution.jsonl         (per-signal WR/PF/EV snapshots)
#   - logs/operators_consolidation.jsonl    (digest + alerts + canary outcomes)

import os, json, time, random, math
from statistics import mean

LOG_DIR = "logs"
CONFIG_DIR = "configs"

REGISTRY_PATH = os.path.join(CONFIG_DIR, "strategy_registry.json")
INTRA_OVERRIDES_PATH = os.path.join(CONFIG_DIR, "intraday_overrides.json")
VENUE_24H_PATH = os.path.join(CONFIG_DIR, "venue_profiles_24h.json")

ATTR_LOG = os.path.join(LOG_DIR, "signal_attribution.jsonl")
OPS_LOG = os.path.join(LOG_DIR, "operators_consolidation.jsonl")

ASSETS = [
    "BTCUSDT","ETHUSDT","SOLUSDT","AVAXUSDT","DOTUSDT","TRXUSDT",
    "XRPUSDT","ADAUSDT","DOGEUSDT","BNBUSDT","MATICUSDT"
]

def _now(): return int(time.time())
def _ts(): return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
def _append_jsonl(path,obj): os.makedirs(os.path.dirname(path),exist_ok=True); open(path,"a").write(json.dumps(obj)+"\n")
def _read_json(path, default=None):
    if not os.path.exists(path): return default
    try:
        with open(path,"r") as f: return json.load(f)
    except:
        return default

# ======================================================================================
# Per-signal attribution logging
# ======================================================================================

def metrics_from_rois(rois):
    if not rois: return {"wr":0.0,"pf":0.0,"ev":0.0,"n":0}
    wr = sum(1 for r in rois if r>0)/len(rois)
    gains = sum(r for r in rois if r>0)
    losses = abs(sum(r for r in rois if r<0))
    pf = (gains/losses) if losses>0 else float('inf')
    ev = mean(rois)
    return {"wr":round(wr,4),"pf":round(pf,4),"ev":round(ev,6),"n":len(rois)}

def update_signal_attribution(per_trade_logs_by_asset, window=200):
    """
    Logs per-signal WR/PF/EV per asset using recent trades’ `signals` dict.
    Expected trade record keys: {"signals":{"Momentum":..., "OFI":..., "MeanReversion":...}, "roi":...}
    """
    snapshot = {"ts": _now(), "assets": {}}
    for a, trades in per_trade_logs_by_asset.items():
        recent = trades[-window:]
        # Collect ROIs per signal (weight threshold > 0 to count)
        signal_rois = {}
        for t in recent:
            roi = t.get("roi",0.0)
            sigs = t.get("signals",{})
            for name, weight in sigs.items():
                if weight is None: continue
                if weight > 0:  # simple gate
                    signal_rois.setdefault(name, []).append(roi)
        signal_stats = {name: metrics_from_rois(rois) for name, rois in signal_rois.items()}
        snapshot["assets"][a] = {"signals": signal_stats}
    _append_jsonl(ATTR_LOG, {"event":"signal_attribution_snapshot", **snapshot})
    return snapshot

# ======================================================================================
# Tag coverage audit
# ======================================================================================

def tag_coverage_audit(per_trade_logs_by_asset, threshold=0.02):
    """
    Validate attribution tags per asset: strategy_id and param_hash must exist.
    Returns report and blocklist for uplift-dependent actions.
    """
    report = {}
    blocklist = set()
    for a, trades in per_trade_logs_by_asset.items():
        n = len(trades)
        untagged = sum(1 for t in trades if not t.get("strategy_id") or not t.get("param_hash"))
        pct = untagged / max(1, n)
        report[a] = {"untagged_pct": round(pct,4), "n": n}
        if pct > threshold:
            blocklist.add(a)
    _append_jsonl(OPS_LOG, {"ts": _now(), "event": "tag_coverage_audit", "report": report, "blocklist": list(blocklist)})
    return {"report": report, "blocklist": blocklist}

# ======================================================================================
# 24h regime-aware venue profiles
# ======================================================================================

def latency_band(avg_latency):
    if avg_latency <= 100: return "low"
    if avg_latency <= 160: return "medium"
    return "high"

def learn_profile_from_window(window):
    latencies = [f.get("latency_ms",0) for t in window for f in t.get("fills",[])]
    avg_lat = mean(latencies) if latencies else 120
    band = latency_band(avg_lat)
    if band == "low":
        prof = {"slice_parts":[3,5], "delay_ms":[50,80], "mode":"maker", "post_only":True}
    elif band == "medium":
        prof = {"slice_parts":[5,7], "delay_ms":[80,120], "mode":"maker", "post_only":True}
    else:
        prof = {"slice_parts":[7,9], "delay_ms":[120,160], "mode":"taker", "post_only":False}
    return prof, avg_lat

def regime_decay_weight(vol_band):
    # In higher volatility, decay older hours faster (give more weight to recent)
    return {"low": 0.85, "medium": 0.70, "high": 0.55}.get(vol_band, 0.70)

def update_venue_profiles_24h(per_trade_logs_by_asset, vol_band_by_asset=None):
    """
    Maintain rolling hourly profiles per asset+venue with regime-aware decay.
    Structure:
      { "BTCUSDT::BINANCE": { "hours": [ {ts, profile, avg_latency}... <=24 ], "last_profile": {...}, "vol_band": "medium" } }
    """
    profiles = _read_json(VENUE_24H_PATH, default={})
    for a, trades in per_trade_logs_by_asset.items():
        if not trades: continue
        venue = trades[-1].get("venue", "BINANCE")
        key = f"{a}::{venue}"
        bucket = profiles.get(key, {"hours": [], "vol_band": "medium"})
        vol_band = (vol_band_by_asset or {}).get(a, "medium")
        decay = regime_decay_weight(vol_band)
        # Take last 120 trades as current hour observation
        window = trades[-120:]
        learned, avg_lat = learn_profile_from_window(window)
        ts = _now()
        bucket["hours"].append({"ts": ts, "profile": learned, "avg_latency": avg_lat})
        # Keep last 24 hours
        bucket["hours"] = bucket["hours"][-24:]
        # Blend weighted: newer hours get weight 1, older decay multiplicatively
        # Start from the newest hour
        agg = {"slice_parts": learned["slice_parts"][:], "delay_ms": learned["delay_ms"][:], "mode": learned["mode"], "post_only": learned["post_only"]}
        w = 1.0
        total_w = 1.0
        # Include previous hours with decayed weights
        for h in reversed(bucket["hours"][:-1]):
            w *= decay
            total_w += w
            p = h["profile"]
            agg["slice_parts"][0] = int(round( (agg["slice_parts"][0]*1 + p["slice_parts"][0]*w) / (1 + w) ))
            agg["slice_parts"][1] = int(round( (agg["slice_parts"][1]*1 + p["slice_parts"][1]*w) / (1 + w) ))
            agg["delay_ms"][0] = int(round( (agg["delay_ms"][0]*1 + p["delay_ms"][0]*w) / (1 + w) ))
            agg["delay_ms"][1] = int(round( (agg["delay_ms"][1]*1 + p["delay_ms"][1]*w) / (1 + w) ))
            # Router mode/post_only: prefer taker/post_only=False if any hour indicated hardening
            agg["mode"] = "taker" if (agg["mode"] == "taker" or p["mode"] == "taker") else "maker"
            agg["post_only"] = False if (agg["post_only"] == False or p["post_only"] == False) else True

        bucket["last_profile"] = agg
        bucket["vol_band"] = vol_band
        bucket["updated_ts"] = ts
        profiles[key] = bucket

    os.makedirs(CONFIG_DIR, exist_ok=True)
    with open(VENUE_24H_PATH, "w") as f:
        json.dump(profiles, f, indent=2)
    _append_jsonl(OPS_LOG, {"ts": _now(), "event":"venue_profiles_24h_update", "keys": list(profiles.keys())})
    return profiles

# ======================================================================================
# Canary monitoring & retry logic
# ======================================================================================

def capacity_ok(asset_packet, slip_max=0.0020, fq_min=0.84):
    cap = asset_packet.get("capacity", {})
    slip = cap.get("avg_slippage", 0.0015)
    fq = cap.get("avg_fill_quality", 0.85)
    return (slip <= slip_max) and (fq >= fq_min)

def stats_pass(stats, wr_floor=0.60, pf_floor=1.50, ev_floor=0.0):
    return (stats.get("win_rate",0.0) >= wr_floor and
            stats.get("profit_factor",0.0) >= pf_floor and
            stats.get("expectancy",0.0) > ev_floor)

def canary_monitor_and_retry(multi_asset_summary, promoter_evals=None, retry_wait_cycles=2):
    """
    Nightly consolidation:
      - Inspect registry history for canary promotions; evaluate capacity + stats
      - If pass: mark 'canary_pass' and schedule production consideration
      - If fail: classify reason (capacity/statistics), schedule retry after N cycles, or rollback
    """
    registry = _read_json(REGISTRY_PATH, default={"ts": _now(), "assets": {a: {"champion": None, "contenders": [], "history": []} for a in ASSETS}})
    intra = _read_json(INTRA_OVERRIDES_PATH, default={"ts": _now(), "assets": {}})

    outcomes = []
    for ap in multi_asset_summary.get("assets", []):
        asset = ap["asset"]
        hist = registry["assets"][asset].get("history", [])
        # Find last canary promotion
        canaries = [h for h in hist if h.get("outcome") in ["promoted_to_canary_auto","promoted_to_canary_manual"]]
        if not canaries: continue
        last = canaries[-1]
        # Capacity gate
        cap_good = capacity_ok(ap)
        # Stats from promoter evaluations if provided; fallback to asset metrics
        eval_stats = None
        if promoter_evals:
            # promoter_evals structure: {asset: {"win_rate":..,"profit_factor":..,"expectancy":..}}
            eval_stats = promoter_evals.get(asset)
        stats_good = stats_pass(eval_stats or ap.get("metrics", {}), wr_floor=0.60, pf_floor=1.50, ev_floor=0.0)

        if cap_good and stats_good:
            registry["assets"][asset]["history"].append({
                "ts": _now(),
                "id": last.get("id"),
                "outcome": "canary_pass",
                "reason": "capacity_ok_and_stats_pass"
            })
            outcomes.append({"asset": asset, "result": "PASS"})
        else:
            reason = "capacity_fail" if not cap_good else "stats_fail"
            registry["assets"][asset]["history"].append({
                "ts": _now(),
                "id": last.get("id"),
                "outcome": "canary_fail",
                "reason": reason,
                "retry_after_cycles": retry_wait_cycles
            })
            # Rollback intraday scale and params to champion for safety
            champ = registry["assets"][asset].get("champion")
            pkt = intra.get("assets", {}).get(asset, {})
            if champ:
                intra.setdefault("assets", {}).setdefault(asset, {})
                intra["assets"][asset]["bandit_params"] = champ.get("params", pkt.get("bandit_params", {}))
            base_scale = pkt.get("position_scale", 1.0)
            intra["assets"][asset]["position_scale"] = round(max(0.5, min(1.0, base_scale)), 4)
            intra["assets"][asset].setdefault("apply_rules", {})["canary_enabled"] = False
            outcomes.append({"asset": asset, "result": "FAIL", "reason": reason})

    os.makedirs(CONFIG_DIR, exist_ok=True)
    with open(REGISTRY_PATH, "w") as f: json.dump(registry, f, indent=2)
    with open(INTRA_OVERRIDES_PATH, "w") as f: json.dump(intra, f, indent=2)
    _append_jsonl(OPS_LOG, {"ts": _now(), "event":"canary_monitor_and_retry", "outcomes": outcomes})
    return {"outcomes": outcomes, "registry_path": REGISTRY_PATH, "intra_overrides_path": INTRA_OVERRIDES_PATH}

# ======================================================================================
# Operator digest builder
# ======================================================================================

def build_operator_digest(multi_asset_summary,
                          tag_audit_report,
                          canary_outcomes,
                          venue_profiles_24h,
                          signal_attr_snapshot,
                          max_assets=11):
    """
    Compose a compact digest payload with the most relevant operator info.
    Intended for SMTP reporting (email content construction handled elsewhere).
    """
    digest = {
        "ts": _ts(),
        "portfolio_overview": {
            "avg_wr": round(mean([a["metrics"]["win_rate"] for a in multi_asset_summary["assets"]]),4),
            "avg_pf": round(mean([a["metrics"]["profit_factor"] for a in multi_asset_summary["assets"]]),4),
            "avg_ev": round(mean([a["metrics"]["expectancy"] for a in multi_asset_summary["assets"]]),6)
        },
        "tag_health": [],
        "canary_results": canary_outcomes["outcomes"],
        "venue_profile_changes": [],
        "signal_highlights": []
    }

    # Tag health (top offenders first)
    offenders = sorted(tag_audit_report["report"].items(), key=lambda kv: kv[1]["untagged_pct"], reverse=True)[:max_assets]
    for asset, info in offenders:
        digest["tag_health"].append({"asset": asset, "untagged_pct": info["untagged_pct"], "n": info["n"]})

    # Venue profile latest state (slice/delay/mode) per asset
    for key, bucket in venue_profiles_24h.items():
        digest["venue_profile_changes"].append({
            "asset_venue": key,
            "mode": bucket["last_profile"]["mode"],
            "slice_parts": bucket["last_profile"]["slice_parts"],
            "delay_ms": bucket["last_profile"]["delay_ms"],
            "vol_band": bucket["vol_band"]
        })

    # Signal highlights: pick top signal by EV per asset
    for asset, pkt in signal_attr_snapshot["assets"].items():
        sigs = pkt.get("signals", {})
        if not sigs: continue
        best = sorted(sigs.items(), key=lambda kv: kv[1]["ev"], reverse=True)[0]
        digest["signal_highlights"].append({"asset": asset, "signal": best[0], "ev": best[1]["ev"], "wr": best[1]["wr"], "pf": best[1]["pf"]})

    _append_jsonl(OPS_LOG, {"ts": _now(), "event":"operator_digest_built", "digest_summary": {
        "tag_offenders": [x["asset"] for x in digest["tag_health"][:3]],
        "canary_pass": sum(1 for x in digest["canary_results"] if x["result"]=="PASS"),
        "canary_fail": sum(1 for x in digest["canary_results"] if x["result"]=="FAIL"),
        "venue_entries": len(digest["venue_profile_changes"]),
        "signals_reported": len(digest["signal_highlights"])
    }})
    return digest

# ======================================================================================
# CLI quick run – simulate operators’ consolidation
# ======================================================================================

if __name__ == "__main__":
    # Mock multi_asset_summary
    def mock_asset(a):
        return {
            "asset": a,
            "metrics": {
                "expectancy": random.uniform(-0.0005, 0.0035),
                "win_rate": random.uniform(0.48, 0.62),
                "profit_factor": random.uniform(1.1, 1.8),
                "n": random.randint(60, 160)
            },
            "capacity": {
                "avg_slippage": random.uniform(0.0006, 0.0020),
                "avg_fill_quality": random.uniform(0.82, 0.90),
                "n": random.randint(20, 40)
            }
        }
    multi_asset_summary = {"assets": [mock_asset(a) for a in ASSETS]}

    # Mock trades with signals + tags
    def mock_trade(asset, strategy_id, ph, venue="BINANCE"):
        roi = random.gauss(random.uniform(-0.0003,0.0012), random.uniform(0.008,0.015))
        order = {"size": random.uniform(0.1, 1.5)}
        fills = [{"size": order["size"]*random.uniform(0.4,0.7), "latency_ms": random.randint(80,220)},
                 {"size": order["size"]*random.uniform(0.3,0.6), "latency_ms": random.randint(120,260)}]
        signals = {"Momentum": random.uniform(0.1,0.4), "OFI": random.uniform(0.05,0.3), "MeanReversion": random.uniform(0.05,0.25)}
        return {"roi": roi, "order": order, "fills": fills, "signals": signals,
                "strategy_id": strategy_id, "param_hash": ph, "venue": venue, "timestamp": _now()}
    per_trade_logs_by_asset = {}
    for a in ASSETS:
        sid_champ = f"{a}_champ"
        ph_champ = "h_" + str(abs(hash(("lookback",50))))
        sid_cont = f"{a}_cont"
        ph_cont = "h_" + str(abs(hash(("lookback",80))))
        trades = []
        for _ in range(random.randint(120, 240)):
            if random.random() < 0.55:
                trades.append(mock_trade(a, sid_champ, ph_champ))
            else:
                trades.append(mock_trade(a, sid_cont, ph_cont))
        # Add a few untagged to test audit
        for _ in range(random.randint(0,6)):
            t = mock_trade(a, sid_champ, ph_champ)
            t.pop("strategy_id", None); t.pop("param_hash", None)
            trades.append(t)
        per_trade_logs_by_asset[a] = trades

    # Mock promoter evals (optional)
    promoter_evals = {a: {"win_rate": random.uniform(0.55,0.66), "profit_factor": random.uniform(1.4,1.8), "expectancy": random.uniform(0.0003,0.0025)} for a in ASSETS}

    # Seed registry with a canary promotion on a random subset
    registry = {"ts": _now(), "assets": {}}
    for a in ASSETS:
        champ_node = {"id": f"{a}_champ", "params": {"lookback":50,"threshold":0.3,"stop_atr":3,"take_atr":4}}
        cont_node = {"id": f"{a}_cont", "params": {"lookback":80,"threshold":0.5,"stop_atr":4,"take_atr":5}}
        history = []
        if random.random() < 0.3:
            history.append({"ts": _now()-3600, "id": cont_node["id"], "outcome":"promoted_to_canary_auto", "canary_fraction":0.2})
        registry["assets"][a] = {"champion": champ_node, "contenders": [cont_node], "history": history}
    os.makedirs(CONFIG_DIR, exist_ok=True)
    with open(REGISTRY_PATH, "w") as f: json.dump(registry, f, indent=2)

    # Seed intraday overrides
    intra = {"ts": _now(), "assets": {}}
    for a in ASSETS:
        intra["assets"][a] = {
            "bandit_params": {"lookback":50,"threshold":0.3,"stop_atr":3,"take_atr":4},
            "position_scale": random.uniform(0.7, 1.0),
            "execution_router": {"mode":"maker","post_only":True,"slice_parts":[3,5],"delay_ms":[50,80],"hold_orders":False},
            "apply_rules": {"capacity_checks": True, "intraday_enabled": True}
        }
    with open(INTRA_OVERRIDES_PATH, "w") as f: json.dump(intra, f, indent=2)

    # Intraday pass: update venue profiles + signal attribution + tag audit
    venue_profiles_24h = update_venue_profiles_24h(per_trade_logs_by_asset, vol_band_by_asset={a: random.choice(["low","medium","high"]) for a in ASSETS})
    signal_attr = update_signal_attribution(per_trade_logs_by_asset, window=200)
    tag_audit = tag_coverage_audit(per_trade_logs_by_asset, threshold=0.02)

    # Nightly pass: canary monitor + retry
    canary_outcomes = canary_monitor_and_retry(multi_asset_summary, promoter_evals=promoter_evals, retry_wait_cycles=2)

    # Build operator digest payload
    digest = build_operator_digest(multi_asset_summary, tag_audit, canary_outcomes, venue_profiles_24h, signal_attr)

    # Print a compact summary (email construction/sending handled by your SMTP module)
    print(json.dumps({
        "ts": digest["ts"],
        "portfolio": digest["portfolio_overview"],
        "tag_offenders_top3": digest["tag_health"][:3],
        "canary_pass_count": sum(1 for x in digest["canary_results"] if x["result"]=="PASS"),
        "canary_fail_count": sum(1 for x in digest["canary_results"] if x["result"]=="FAIL"),
        "venue_entries": len(digest["venue_profile_changes"]),
        "signals_reported": len(digest["signal_highlights"])
    }, indent=2))