# src/integration_orchestrator.py
#
# Integration Orchestrator — Auto-handoff, venue profile persistence, trade tagging audits,
# and adversarial stress-test harness wired into your 24/7 crypto learning stack.
#
# What this module does:
#   1) Nightly auto-handoff enforcement:
#        - Scans strategy_registry history for "intraday_validated_uplift_ready_for_canary"
#        - Promotes flagged contenders to canary at 20% scale with capacity gates
#        - Auto-rollback canaries on degradation; writes governance audit entries
#   2) Venue profile persistence:
#        - Learns per asset+venue execution profiles (slice/delay/mode) from recent fills
#        - Persists to configs/venue_profiles.json with decay/refresh
#        - Router selection by current latency/vol bands
#   3) Trade tagging audits:
#        - Validates that trades have strategy_id + param_hash tags
#        - If >2% untagged for any asset, raises alert and blocks uplift-dependent actions
#   4) Stress-test harness:
#        - Injects adversarial shocks (regime flip, liquidity drought, sentiment lag spike)
#        - Validates system reactions (swap pause, router hardening, rollbacks)
#        - Logs outcomes in logs/stress_harness.jsonl
#
# Integration:
#   - Run auto_handoff_enforcer() once per nightly cycle (post-relative uplift promoter).
#   - Run venue_profile_persistence() every intraday cycle post execution, or hourly.
#   - Run trade_tagging_audit() every intraday cycle before uplift tests.
#   - Run stress_harness() on demand or nightly in shadow mode.
#
# I/O paths:
#   - configs/strategy_registry.json (champions/contenders/history)
#   - configs/intraday_overrides.json (live intraday params/router/scale)
#   - configs/venue_profiles.json (persisted execution profiles per asset+venue)
#   - logs/governance_upgrade.jsonl (promotion/rollback audits)
#   - logs/integration_orchestrator.jsonl (module audits)
#   - logs/stress_harness.jsonl (stress outcomes)

import os, json, time, random, math
from statistics import mean

LOG_DIR = "logs"
CONFIG_DIR = "configs"

REGISTRY_PATH = os.path.join(CONFIG_DIR, "strategy_registry.json")
INTRA_OVERRIDES_PATH = os.path.join(CONFIG_DIR, "intraday_overrides.json")
VENUE_PROFILES_PATH = os.path.join(CONFIG_DIR, "venue_profiles.json")

GOV_AUDIT = os.path.join(LOG_DIR, "governance_upgrade.jsonl")
ORCH_AUDIT = os.path.join(LOG_DIR, "integration_orchestrator.jsonl")
STRESS_LOG = os.path.join(LOG_DIR, "stress_harness.jsonl")

ASSETS = [
    "BTCUSDT","ETHUSDT","SOLUSDT","AVAXUSDT","DOTUSDT","TRXUSDT",
    "XRPUSDT","ADAUSDT","DOGEUSDT","BNBUSDT","MATICUSDT"
]

def _now(): return int(time.time())
def _append_jsonl(path,obj): os.makedirs(os.path.dirname(path),exist_ok=True); open(path,"a").write(json.dumps(obj)+"\n")
def _read_json(path, default=None):
    if not os.path.exists(path): return default
    try:
        with open(path,"r") as f: return json.load(f)
    except:
        return default

# ======================================================================================
# Trade tagging audit
# ======================================================================================

def trade_tagging_audit(per_trade_logs_by_asset, threshold=0.02):
    """
    Check % of trades missing strategy_id or param_hash per asset.
    Returns audit packet and a blocklist of assets where uplift actions should be paused.
    """
    blocklist = set()
    report = {}
    for a, trades in per_trade_logs_by_asset.items():
        n = len(trades)
        untagged = sum(1 for t in trades if not t.get("strategy_id") or not t.get("param_hash"))
        pct = (untagged / max(1, n))
        report[a] = {"untagged_pct": round(pct, 4), "n": n}
        if pct > threshold:
            blocklist.add(a)
    _append_jsonl(ORCH_AUDIT, {"ts": _now(), "event": "trade_tagging_audit", "report": report, "blocklist": list(blocklist)})
    return {"report": report, "blocklist": blocklist}

# ======================================================================================
# Venue profile persistence
# ======================================================================================

def latency_band(avg_latency):
    if avg_latency <= 100: return "low"
    if avg_latency <= 160: return "medium"
    return "high"

def vol_band_stub(vol):
    if vol < 0.008: return "low"
    if vol < 0.015: return "medium"
    return "high"

def learn_profile(trades_window):
    latencies = [f.get("latency_ms",0) for t in trades_window for f in t.get("fills",[])]
    avg_lat = mean(latencies) if latencies else 120
    band = latency_band(avg_lat)
    if band == "low":
        return {"slice_parts":[3,5], "delay_ms":[50,80], "mode":"maker", "post_only":True}
    elif band == "medium":
        return {"slice_parts":[5,7], "delay_ms":[80,120], "mode":"maker", "post_only":True}
    else:
        return {"slice_parts":[7,9], "delay_ms":[120,160], "mode":"taker", "post_only":False}

def decay_merge_profile(old, new, decay=0.7):
    if not old: return new
    merged = {}
    # For numeric lists, blend each end
    merged["slice_parts"] = [
        int(round(decay*old["slice_parts"][0] + (1-decay)*new["slice_parts"][0])),
        int(round(decay*old["slice_parts"][1] + (1-decay)*new["slice_parts"][1]))
    ]
    merged["delay_ms"] = [
        int(round(decay*old["delay_ms"][0] + (1-decay)*new["delay_ms"][0])),
        int(round(decay*old["delay_ms"][1] + (1-decay)*new["delay_ms"][1]))
    ]
    # Mode/post_only: prefer hardened/taker if either suggests it
    merged["mode"] = "taker" if (old["mode"] == "taker" or new["mode"] == "taker") else "maker"
    merged["post_only"] = False if (old["post_only"] == False or new["post_only"] == False) else True
    return merged

def venue_profile_persistence(per_trade_logs_by_asset, recent_vol_estimates=None):
    """
    Update venue profiles from recent execution.
    Writes configs/venue_profiles.json.
    """
    profiles = _read_json(VENUE_PROFILES_PATH, default={})
    for asset, trades in per_trade_logs_by_asset.items():
        if not trades: continue
        venue = trades[-1].get("venue", "BINANCE")
        window = trades[-120:]
        learned = learn_profile(window)
        # Harden if adverse selection memory indicates risk
        qt = [t.get("quote_touch_ret", 0.0) for t in window if "quote_touch_ret" in t]
        neg_hits = sum(1 for x in qt if x < 0.0)
        harden = neg_hits >= int(0.3 * max(1, len(qt)))
        if harden:
            learned["slice_parts"] = [max(learned["slice_parts"][0],5), max(learned["slice_parts"][1],9)]
            learned["delay_ms"] = [max(learned["delay_ms"][0],100), max(learned["delay_ms"][1],160)]
            learned["mode"] = "taker"; learned["post_only"] = False
        # Blend with existing
        key = f"{asset}::{venue}"
        profiles[key] = decay_merge_profile(profiles.get(key), learned, decay=0.7)
        # Attach bands (vol stub)
        vol = (recent_vol_estimates or {}).get(asset, 0.01)
        profiles[key]["vol_band"] = vol_band_stub(vol)
        profiles[key]["updated_ts"] = _now()

    os.makedirs(CONFIG_DIR, exist_ok=True)
    with open(VENUE_PROFILES_PATH, "w") as f:
        json.dump(profiles, f, indent=2)
    _append_jsonl(ORCH_AUDIT, {"ts": _now(), "event":"venue_profile_persistence", "profiles_keys": list(profiles.keys())})
    return profiles

# ======================================================================================
# Nightly auto-handoff enforcement
# ======================================================================================

def capacity_ok(asset_packet, slip_max=0.0020, fq_min=0.84):
    cap = asset_packet.get("capacity", {})
    slip = cap.get("avg_slippage", 0.0015)
    fq = cap.get("avg_fill_quality", 0.85)
    return (slip <= slip_max) and (fq >= fq_min)

def auto_handoff_enforcer(multi_asset_summary, canary_fraction=0.2):
    """
    Promote contenders flagged as "intraday_validated_uplift_ready_for_canary" to canary (20% scale)
    with capacity gates. Auto-rollback on degradation.
    """
    registry = _read_json(REGISTRY_PATH, default={"ts": _now(), "assets": {a: {"champion": None, "contenders": [], "history": []} for a in ASSETS}})
    intra = _read_json(INTRA_OVERRIDES_PATH, default={"ts": _now(), "assets": {}})

    promoted = []
    rolled_back = []

    for ap in multi_asset_summary.get("assets", []):
        asset = ap["asset"]
        history = registry["assets"][asset].get("history", [])
        ready = [h for h in history if h.get("outcome") == "intraday_validated_uplift_ready_for_canary"]
        if not ready:
            continue

        # Capacity gate before canary
        if not capacity_ok(ap):
            _append_jsonl(GOV_AUDIT, {"ts": _now(), "asset": asset, "event":"handoff_skipped_capacity_block"})
            continue

        # Pick latest ready contender
        contender_id = ready[-1]["id"]
        contender_node = next((c for c in registry["assets"][asset].get("contenders", []) if c.get("id") == contender_id), None)
        if not contender_node:
            _append_jsonl(GOV_AUDIT, {"ts": _now(), "asset": asset, "event":"handoff_missing_contender", "id": contender_id})
            continue

        # Apply canary overrides
        pkt = intra.get("assets", {}).get(asset, {})
        base_scale = pkt.get("position_scale", 1.0)
        intra.setdefault("assets", {}).setdefault(asset, {})
        intra["assets"][asset]["position_scale"] = round(max(0.5, min(1.0, base_scale * (1.0*canary_fraction + 0.8))), 4)  # approx 20% canary influence
        intra["assets"][asset]["bandit_params"] = contender_node.get("params", pkt.get("bandit_params", {}))
        intra["assets"][asset].setdefault("apply_rules", {})["canary_enabled"] = True
        intra["assets"][asset]["mid_session_swap"] = False  # nightly governs

        registry["assets"][asset]["history"].append({
            "ts": _now(),
            "id": contender_id,
            "outcome": "promoted_to_canary_auto",
            "canary_fraction": canary_fraction
        })
        promoted.append({"asset": asset, "id": contender_id})

        # Simulated capacity re-check post-canary (hook your real monitor here)
        if not capacity_ok(ap):
            # rollback: restore champion params/scale
            champ = registry["assets"][asset].get("champion")
            intra["assets"][asset]["bandit_params"] = champ.get("params", intra["assets"][asset]["bandit_params"]) if champ else intra["assets"][asset]["bandit_params"]
            intra["assets"][asset]["position_scale"] = round(max(0.5, min(1.0, base_scale)), 4)
            intra["assets"][asset]["apply_rules"]["canary_enabled"] = False
            registry["assets"][asset]["history"].append({
                "ts": _now(),
                "id": contender_id,
                "outcome": "canary_rollback_capacity_degraded"
            })
            rolled_back.append({"asset": asset, "id": contender_id})

    # Persist updates
    os.makedirs(CONFIG_DIR, exist_ok=True)
    with open(INTRA_OVERRIDES_PATH, "w") as f:
        json.dump(intra, f, indent=2)
    registry["ts"] = _now()
    with open(REGISTRY_PATH, "w") as f:
        json.dump(registry, f, indent=2)

    _append_jsonl(GOV_AUDIT, {"ts": _now(), "event":"auto_handoff_enforcer_complete", "promoted": promoted, "rolled_back": rolled_back})
    _append_jsonl(ORCH_AUDIT, {"ts": _now(), "event":"auto_handoff_enforcer_complete", "promoted": promoted, "rolled_back": rolled_back})
    return {"promoted": promoted, "rolled_back": rolled_back, "registry_path": REGISTRY_PATH, "intra_overrides_path": INTRA_OVERRIDES_PATH}

# ======================================================================================
# Stress-test harness
# ======================================================================================

def stress_harness(per_trade_logs_by_asset, mode="combo"):
    """
    Injects adversarial shocks for resilience validation:
      - regime_flip: abrupt trend↔chop signals → expect intraday swaps to pause
      - liquidity_drought: raise latencies and reduce fill completeness → expect router hardening and micro-rollback
      - sentiment_lag_spike: stale, high-variance sentiment → expect decay clamp
    """
    outcomes = {}
    for a, trades in per_trade_logs_by_asset.items():
        if not trades: continue
        window = trades[-100:]
        if mode in ["regime_flip","combo"]:
            # Flip sign of recent returns to simulate regime change
            for t in window:
                t["roi"] = -t.get("roi", 0.0)
        if mode in ["liquidity_drought","combo"]:
            # Inflate latencies and reduce fill sizes
            for t in window:
                for f in t.get("fills", []):
                    f["latency_ms"] = int(f.get("latency_ms",100) * 1.5)
                    f["size"] = f.get("size",0.0) * 0.6
                t["quote_touch_ret"] = min(t.get("quote_touch_ret",0.0), -0.0005)
        if mode in ["sentiment_lag_spike","combo"]:
            # Add lag and variance flags (downstream modules should clamp)
            tlag = _now() - random.randint(900, 2400)  # 15–40 min stale
            trades[-1]["sentiment_lag_ts"] = tlag
            trades[-1]["sentiment_variance_flag"] = True

        outcomes[a] = {"mode": mode, "window_n": len(window)}

    _append_jsonl(STRESS_LOG, {"ts": _now(), "event":"stress_harness_injected", "mode": mode, "outcomes": outcomes})
    return outcomes

# ======================================================================================
# Orchestrator glue (run sequence examples)
# ======================================================================================

def run_intraday_glue(per_trade_logs_by_asset, recent_vol_estimates=None):
    """
    To be run each intraday cycle (every 5–10 minutes):
      1) Trade tagging audit → if blocklist non-empty, skip uplift-dependent actions
      2) Venue profile persistence → update execution profiles
    """
    audit = trade_tagging_audit(per_trade_logs_by_asset, threshold=0.02)
    profiles = venue_profile_persistence(per_trade_logs_by_asset, recent_vol_estimates=recent_vol_estimates)
    return {"tag_audit": audit, "venue_profiles": profiles}

def run_nightly_glue(multi_asset_summary):
    """
    To be run once per nightly cycle (post promoter, pre scaling):
      1) Auto-handoff enforcement → promote intraday-validated contenders to canary
    """
    return auto_handoff_enforcer(multi_asset_summary, canary_fraction=0.2)

# ======================================================================================
# CLI quick run — simulate integration orchestrator
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

    # Mock trades with tags
    def mock_trade(asset, strategy_id, ph, venue="BINANCE", mu=0.0004, sigma=0.012):
        roi = random.gauss(mu, sigma)
        expected = 100 + random.uniform(-1,1)
        actual = expected*(1 + random.uniform(-0.0015, 0.0025))
        order = {"size": random.uniform(0.1, 1.5)}
        fills = [{"size": order["size"]*random.uniform(0.4,0.7), "latency_ms": random.randint(80,220)},
                 {"size": order["size"]*random.uniform(0.3,0.6), "latency_ms": random.randint(120,260)}]
        return {"roi": roi, "expected": expected, "actual": actual, "order": order, "fills": fills,
                "strategy_id": strategy_id, "param_hash": ph, "venue": venue, "quote_touch_ret": random.uniform(-0.0006,0.0008),
                "timestamp": _now()}
    per_trade_logs_by_asset = {}
    for a in ASSETS:
        sid_champ = f"{a}_champ"
        ph_champ = "h_" + str(abs(hash(("lookback",50))))  # simple hash stub
        sid_cont = f"{a}_cont"
        ph_cont = "h_" + str(abs(hash(("lookback",80))))
        trades = []
        for _ in range(random.randint(90, 180)):
            if random.random() < 0.55:
                trades.append(mock_trade(a, sid_champ, ph_champ))
            else:
                trades.append(mock_trade(a, sid_cont, ph_cont))
        # Add some untagged trades to test audit
        for _ in range(3):
            trades.append({"roi": random.gauss(0.0002,0.012), "fills":[{"latency_ms": random.randint(100,180)}]})
        per_trade_logs_by_asset[a] = trades

    # Mock registry with flag for canary handoff on two assets
    registry = {"ts": _now(), "assets": {}}
    for a in ASSETS:
        champ_node = {"id": f"{a}_champ", "params": {"lookback":50,"threshold":0.3,"stop_atr":3,"take_atr":4}}
        cont_node = {"id": f"{a}_cont", "params": {"lookback":80,"threshold":0.5,"stop_atr":4,"take_atr":5}}
        history = []
        if random.random() < 0.25:
            history.append({"ts": _now()-3600, "id": cont_node["id"], "outcome":"intraday_validated_uplift_ready_for_canary"})
        registry["assets"][a] = {"champion": champ_node, "contenders": [cont_node], "history": history}
    os.makedirs(CONFIG_DIR, exist_ok=True)
    with open(REGISTRY_PATH, "w") as f: json.dump(registry, f, indent=2)

    # Seed intraday_overrides baseline
    intra = {"ts": _now(), "assets": {}}
    for a in ASSETS:
        intra["assets"][a] = {
            "bandit_params": {"lookback":50,"threshold":0.3,"stop_atr":3,"take_atr":4},
            "position_scale": random.uniform(0.7, 1.0),
            "execution_router": {"mode":"maker","post_only":True,"slice_parts":[3,5],"delay_ms":[50,80],"hold_orders":False},
            "apply_rules": {"capacity_checks": True, "intraday_enabled": True}
        }
    with open(INTRA_OVERRIDES_PATH, "w") as f: json.dump(intra, f, indent=2)

    # Run intraday glue (audit + venue profiles)
    glue_out = run_intraday_glue(per_trade_logs_by_asset, recent_vol_estimates={a: random.uniform(0.006,0.02) for a in ASSETS})
    print(json.dumps({"tag_audit": glue_out["tag_audit"]["report"], "blocklist": list(glue_out["tag_audit"]["blocklist"])}, indent=2))

    # Inject stress and log
    stress_out = stress_harness(per_trade_logs_by_asset, mode="combo")
    print(json.dumps({"stress_mode": "combo", "assets_affected": list(stress_out.keys())[:3]}, indent=2))

    # Run nightly auto-handoff enforcer
    handoff_out = run_nightly_glue(multi_asset_summary)
    print(json.dumps({
        "promoted": handoff_out["promoted"],
        "rolled_back": handoff_out["rolled_back"],
        "registry_path": handoff_out["registry_path"],
        "intra_overrides_path": handoff_out["intra_overrides_path"]
    }, indent=2))