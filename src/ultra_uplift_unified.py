# src/ultra_uplift_unified.py
#
# Ultra Uplift Unified – 24/7 crypto learning stack integration
# Purpose:
#   Fold true-sample statistical uplift, trade-to-strategy tagging, venue execution profiles,
#   adverse selection memory, confidence-weighted promotion cadence, intraday→nightly auto-handoff,
#   risk-parity clamps, and correlation guards into a single continuous orchestrator.
#
# What this adds (plug-and-play):
#   1) Trade-to-strategy tagging: fills/orders carry strategy_id + param_hash for true attribution
#   2) True-sample uplift tests: contender vs champion using only tagged trades (no asset proxies)
#   3) Venue profiles: learned slice/delay/router settings by latency/vol bands per venue+asset
#   4) Adverse selection memory: short-term quote-touch outcomes → router hardening on repeats
#   5) Confidence-weighted cadence: faster handoff when p-value small & effect size large
#   6) Auto-handoff: intraday winner → nightly canary after 2 consecutive validated cycles
#   7) Risk-parity clamps: vol-normalized scales blended with capacity KPIs
#   8) Correlation guards: promotion penalties when covariance rises without outsized uplift
#
# Integration points:
#   - Call run_ultra_uplift_cycle(...) every 5–10 minutes (24/7 crypto).
#   - Wire outputs:
#       configs/intraday_overrides.json (updated params/overlays/router/scale)
#       configs/strategy_registry.json (auto-handoff to canary via history entries)
#       logs/ultra_uplift_unified.jsonl (audit of uplift, execution, risk, and handoff)
#
# Assumptions:
#   - per_trade_logs_by_asset: each trade dict may include:
#       {"roi":float,"order":{...},"fills":[...],
#        "strategy_id":"...", "param_hash":"...", "quote_touch_ret":float,
#        "venue":"BINANCE", "timestamp":int}
#     If tags missing, module falls back gracefully (but encourages true tagging).
#
# Note:
#   - Replace stubs (correlation matrix, venue volatility band) with your live infra.
#   - This module is orchestration-safe: JSON input/output, pure Python.

import os, json, time, random, math
from statistics import mean

LOG_DIR = "logs"
CONFIG_DIR = "configs"
REGISTRY_PATH = os.path.join(CONFIG_DIR, "strategy_registry.json")
INTRA_OVERRIDES = os.path.join(CONFIG_DIR, "intraday_overrides.json")
ULTRA_LOG = os.path.join(LOG_DIR, "ultra_uplift_unified.jsonl")

ASSETS = [
    "BTCUSDT","ETHUSDT","SOLUSDT","AVAXUSDT","DOTUSDT","TRXUSDT",
    "XRPUSDT","ADAUSDT","DOGEUSDT","BNBUSDT"
]

def _now(): return int(time.time())
def _append_jsonl(path,obj): os.makedirs(os.path.dirname(path),exist_ok=True); open(path,"a").write(json.dumps(obj)+"\n")
def _read_json(path, default=None):
    if not os.path.exists(path): return default
    try:
        with open(path,"r") as f: return json.load(f)
    except: return default

# ======================================================================================
# Trade-to-strategy tagging helpers
# ======================================================================================

def param_hash(params):
    if not params: return "hash_empty"
    keys = sorted(params.keys())
    return "h_" + str(abs(hash(tuple((k, params[k]) for k in keys))))  # deterministic-ish hash

def filter_trades_by_strategy(trades, strategy_id=None, param_hash_val=None, window=120):
    if not trades: return []
    window_trades = trades[-window:]
    if not strategy_id and not param_hash_val:
        return window_trades
    filtered = []
    for t in window_trades:
        sid = t.get("strategy_id")
        ph = t.get("param_hash")
        if (strategy_id and sid == strategy_id) or (param_hash_val and ph == param_hash_val):
            filtered.append(t)
    return filtered or window_trades  # fallback to window if no tags match

# ======================================================================================
# Metrics and samples
# ======================================================================================

def metrics_from_trades(trades):
    if not trades:
        return {"wr": 0.0, "pf": 0.0, "ev": 0.0, "n": 0}, []
    rois = [t.get("roi", 0.0) for t in trades]
    wr = sum(1 for r in rois if r > 0) / max(1, len(rois))
    gains = sum(r for r in rois if r > 0)
    losses = abs(sum(r for r in rois if r < 0))
    pf = (gains / losses) if losses > 0 else float('inf')
    ev = mean(rois)
    return {"wr": round(wr,4), "pf": round(pf,4), "ev": round(ev,6), "n": len(rois)}, rois

def compute_portfolio_baselines(multi_asset_summary):
    assets = multi_asset_summary.get("assets", [])
    wrs = [a.get("metrics",{}).get("win_rate", 0.5) for a in assets]
    pfs = [a.get("metrics",{}).get("profit_factor", 1.2) for a in assets]
    evs = [a.get("metrics",{}).get("expectancy", 0.0) for a in assets]
    base = {"wr": round(mean(wrs) if wrs else 0.5,4),
            "pf": round(mean(pfs) if pfs else 1.2,4),
            "ev": round(mean(evs) if evs else 0.0,6)}
    wr_rng = (max(wrs) - min(wrs)) if wrs else 0.0
    pf_rng = (max(pfs) - min(pfs)) if pfs else 0.0
    wr_margin = 0.02 + min(0.02, wr_rng/4)   # up to +4% margin when dispersion high
    pf_margin = 0.05 + min(0.05, pf_rng/4)   # up to +0.10 margin
    floors = {"wr_floor": round(base["wr"] + wr_margin,4),
              "pf_floor": round(base["pf"] + pf_margin,4),
              "ev_floor": max(0.0, base["ev"])}
    return base, floors

def capacity_ok(asset_packet, slip_max=0.0020, fq_min=0.84):
    cap = asset_packet.get("capacity", {})
    slip = cap.get("avg_slippage", 0.0015)
    fq = cap.get("avg_fill_quality", 0.85)
    return (slip <= slip_max) and (fq >= fq_min)

# ======================================================================================
# Bootstrap uplift + effect size
# ======================================================================================

def bootstrap_pvalue(sample_a, sample_b, iters=800, seed=None):
    if seed is not None: random.seed(seed)
    if not sample_a or not sample_b: return 1.0, 0.0, 0.0
    mu_a = mean(sample_a); mu_b = mean(sample_b)
    count_better = 0
    for _ in range(iters):
        a_hat = mean(random.choices(sample_a, k=len(sample_a)))
        b_hat = mean(random.choices(sample_b, k=len(sample_b)))
        if b_hat - a_hat > 0: count_better += 1
    p = 1.0 - (count_better / iters)
    return round(p,6), mu_a, mu_b

def effect_size(sample_a, sample_b):
    if not sample_a or not sample_b: return 0.0
    mu_a = mean(sample_a); mu_b = mean(sample_b)
    ad_a = mean([abs(x - mu_a) for x in sample_a]) if sample_a else 0.0
    ad_b = mean([abs(x - mu_b) for x in sample_b]) if sample_b else 0.0
    pooled = max(1e-9, (ad_a + ad_b) / 2.0)
    return round((mu_b - mu_a) / pooled, 4)

def passes_floors(stats, floors):
    return (stats["wr"] >= floors["wr_floor"] and stats["pf"] >= floors["pf_floor"] and stats["ev"] > floors["ev_floor"])

# ======================================================================================
# Venue execution profiles + adverse selection memory
# ======================================================================================

def latency_band(avg_latency):
    if avg_latency <= 100: return "low"
    if avg_latency <= 160: return "medium"
    return "high"

def venue_vol_band(vol):  # stub: derive from realized vol or book imbalance
    if vol < 0.008: return "low"
    if vol < 0.015: return "medium"
    return "high"

def learn_venue_profile(asset, venue, trades_window):
    latencies = [f.get("latency_ms",0) for t in trades_window for f in t.get("fills",[])]
    avg_lat = mean(latencies) if latencies else 120
    # Simple learned profile by bands
    band = latency_band(avg_lat)
    # Choose slices/delays by band
    if band == "low":
        return {"slice_parts":[3,5], "delay_ms":[50,80], "mode":"maker", "post_only":True}
    elif band == "medium":
        return {"slice_parts":[5,7], "delay_ms":[80,120], "mode":"maker", "post_only":True}
    else:
        return {"slice_parts":[7,9], "delay_ms":[120,160], "mode":"taker", "post_only":False}

def adverse_selection_memory(trades_window, horizon=80):
    qt = [t.get("quote_touch_ret", 0.0) for t in trades_window if "quote_touch_ret" in t]
    avg_qt = mean(qt) if qt else 0.0
    hits = sum(1 for x in qt if x < 0.0)
    return {"avg_qt": round(avg_qt,6), "hits": hits, "harden": hits >= int(0.3 * max(1,len(qt)))}

# ======================================================================================
# Risk-parity clamps + correlation guards
# ======================================================================================

def realized_vol(trades, window=120):
    rets = [t.get("roi",0.0) for t in trades[-window:]]
    if not rets: return 0.0
    mu = mean(rets); var = mean([(r-mu)**2 for r in rets])
    return math.sqrt(var)

def risk_parity_scales(per_trade_logs_by_asset, base_scales, target=1.0):
    vols = {a: max(1e-4, realized_vol(per_trade_logs_by_asset.get(a, []), window=120)) for a in ASSETS}
    inv_vol = {a: 1.0/vols[a] for a in ASSETS}
    norm = sum(inv_vol.values()) or 1.0
    weights = {a: inv_vol[a]/norm for a in ASSETS}
    scales = {}
    for a in ASSETS:
        blended = 0.5*base_scales.get(a,1.0) + 0.5*(weights[a]*target)
        scales[a] = round(min(1.0, max(0.5, blended)),4)
    return scales, {"vols":vols, "weights":weights}

def correlation_matrix_stub(per_trade_logs_by_asset):
    # Compute simple pairwise correlation on short windows (stub: sign-correlation)
    assets = list(per_trade_logs_by_asset.keys())
    corr = {a:{} for a in assets}
    for i,a in enumerate(assets):
        rets_a = [t.get("roi",0.0) for t in per_trade_logs_by_asset.get(a, [])[-100:]]
        for j,b in enumerate(assets):
            if j < i: continue
            rets_b = [t.get("roi",0.0) for t in per_trade_logs_by_asset.get(b, [])[-100:]]
            if not rets_a or not rets_b:
                c = 0.0
            else:
                signs = [1 if x>0 else -1 if x<0 else 0 for x in rets_a[:min(len(rets_a),len(rets_b))]]
                signs_b = [1 if x>0 else -1 if x<0 else 0 for x in rets_b[:min(len(rets_a),len(rets_b))]]
                matches = sum(1 for k in range(len(signs)) if signs[k]==signs_b[k])
                c = matches/max(1,len(signs))
            corr[a][b] = c; corr[b][a] = c
    return corr

def correlation_penalty(asset, corr_matrix, threshold=0.6):
    # Penalize promotions if average correlation against current winners is high
    row = corr_matrix.get(asset, {})
    vals = [v for k,v in row.items() if k!=asset]
    avg_c = (sum(vals)/max(1,len(vals))) if vals else 0.0
    return avg_c >= threshold, round(avg_c,3)

# ======================================================================================
# Confidence-weighted cadence (auto-handoff)
# ======================================================================================

def cadence_from_evidence(p_value, effect_size):
    # Smaller p and larger ES → faster handoff (0,1,2 cycles required)
    if p_value <= 0.01 and effect_size >= 0.4: return 0  # instant canary
    if p_value <= 0.03 and effect_size >= 0.3: return 1  # after 1 more cycle
    if p_value <= 0.05 and effect_size >= 0.2: return 2  # after 2 cycles
    return None

def update_handoff_state(registry, asset, contender_id, cadence):
    # Track consecutive wins toward handoff
    hist = registry["assets"][asset].setdefault("handoff_state", {})
    state = hist.get(contender_id, {"wins":0,"cadence":cadence})
    # Increment win count; cap at cadence
    state["wins"] = min((state["wins"] + 1), cadence if cadence is not None else 0)
    state["cadence"] = cadence
    hist[contender_id] = state
    registry["assets"][asset]["handoff_state"] = hist
    return state

def ready_for_canary(state):
    return (state.get("cadence") is not None) and (state.get("wins",0) >= state["cadence"])

# ======================================================================================
# Orchestrator
# ======================================================================================

def run_ultra_uplift_cycle(multi_asset_summary,
                           per_trade_logs_by_asset,
                           intraday_overrides=None,
                           registry_path=REGISTRY_PATH,
                           alpha=0.05,
                           min_effect=0.2,
                           window_trades_intraday=80,
                           window_trades_uplift=120):
    """
    Steps (every 5–10 min, 24/7):
      1) Baselines + floors (variance-aware)
      2) True-sample uplift (contender vs champion via tags) per asset (capacity-gated)
      3) Venue profiles + adverse selection memory → router hardening
      4) Risk-parity scales + correlation guards
      5) Confidence-weighted cadence → auto-handoff to nightly canary when ready
      6) Write updated intraday_overrides and registry; log audit
    """
    intraday_overrides = intraday_overrides or _read_json(INTRA_OVERRIDES, default={"ts": _now(), "assets": {}})
    registry = _read_json(registry_path, default={"ts": _now(), "assets": {a: {"champion": None, "contenders": [], "history": []} for a in ASSETS}})

    base, floors = compute_portfolio_baselines(multi_asset_summary)
    corr_matrix = correlation_matrix_stub(per_trade_logs_by_asset)

    updated_overrides = {"ts": _now(), "assets": {}}
    audit_decisions = []

    # Risk parity scales baseline
    base_scales = {a: intraday_overrides.get("assets", {}).get(a, {}).get("position_scale", 1.0) for a in ASSETS}
    parity_scales, parity_info = risk_parity_scales(per_trade_logs_by_asset, base_scales, target=1.0)

    for ap in multi_asset_summary.get("assets", []):
        asset = ap["asset"]
        cap_ok = capacity_ok(ap, slip_max=0.0020, fq_min=0.84)
        pkt = intraday_overrides.get("assets", {}).get(asset, {})
        current_params = pkt.get("bandit_params", {})
        current_hash = param_hash(current_params)
        champ_node = registry["assets"][asset].get("champion")
        champ_hash = param_hash(champ_node.get("params")) if champ_node else None

        # Choose contender: from intraday overrides or top contender in registry
        contenders = registry["assets"][asset].get("contenders", [])
        contender_node = (contenders[0] if contenders else {"id": f"{asset}_intra_contender", "params": current_params})
        contender_hash = param_hash(contender_node.get("params"))

        # True-sample windows
        trades_asset = per_trade_logs_by_asset.get(asset, [])
        short_window = trades_asset[-window_trades_intraday:]
        champion_trades = filter_trades_by_strategy(trades_asset, strategy_id=champ_node.get("id") if champ_node else None,
                                                    param_hash_val=champ_hash, window=window_trades_uplift)
        contender_trades = filter_trades_by_strategy(trades_asset, strategy_id=contender_node.get("id"),
                                                     param_hash_val=contender_hash, window=window_trades_uplift)

        champ_stats, champ_sample = metrics_from_trades(champion_trades)
        cont_stats, cont_sample = metrics_from_trades(contender_trades)

        # Uplift decision
        swap_ok = False
        evidence = {"reason": "capacity_block"} if not cap_ok else None
        if cap_ok:
            p, mu_a, mu_b = bootstrap_pvalue(champ_sample, cont_sample, iters=800)
            es = effect_size(champ_sample, cont_sample)
            floors_ok = passes_floors(cont_stats, floors)
            swap_ok = (p <= alpha) and (es >= min_effect) and floors_ok
            evidence = {"p_value": p, "effect_size": es, "floors_ok": floors_ok, "mu_champion": mu_a, "mu_contender": mu_b}

        # Venue execution plan + adverse selection memory
        venue = short_window[-1].get("venue") if short_window else "BINANCE"
        profile = learn_venue_profile(asset, venue, short_window)
        asm = adverse_selection_memory(short_window, horizon=window_trades_intraday)
        if asm["harden"]:
            profile["slice_parts"] = [max(profile["slice_parts"][0], 5), max(profile["slice_parts"][-1], 9)]
            profile["delay_ms"] = [max(profile["delay_ms"][0], 100), max(profile["delay_ms"][-1], 160)]
            profile["mode"] = "taker"; profile["post_only"] = False

        # Risk parity scale + correlation guard
        new_scale = parity_scales.get(asset, pkt.get("position_scale", 1.0))
        penalty, avg_corr = correlation_penalty(asset, corr_matrix, threshold=0.6)
        if penalty and not swap_ok:
            # Clamp scale a bit when correlation is high and no validated uplift yet
            new_scale = round(max(0.5, new_scale - 0.03), 4)

        # Confidence-weighted cadence + auto-handoff
        cadence = cadence_from_evidence(evidence.get("p_value", 1.0) if evidence else 1.0,
                                        evidence.get("effect_size", 0.0) if evidence else 0.0)
        state = update_handoff_state(registry, asset, contender_node["id"], cadence) if swap_ok else {"wins":0,"cadence":cadence}
        handoff_ready = ready_for_canary(state)

        # Apply mid-session swap or rollback logic
        next_params = current_params
        mid_swap = False
        rollback = False
        if cap_ok and swap_ok:
            next_params = contender_node.get("params", current_params)
            mid_swap = True
        else:
            # If last cycle swapped but evidence fails now, rollback
            if pkt.get("mid_session_swap"):
                next_params = champ_node.get("params", current_params) if champ_node else current_params
                rollback = True

        # Auto-handoff: write registry history entry to flag for nightly canary
        if handoff_ready:
            registry["assets"][asset]["history"].append({
                "ts": _now(),
                "id": contender_node["id"],
                "outcome": "intraday_validated_uplift_ready_for_canary",
                "evidence": {"p_value": evidence.get("p_value"), "effect_size": evidence.get("effect_size")},
                "floors": floors,
                "stats": cont_stats
            })

        # Compose updated overrides
        updated_overrides["assets"][asset] = {
            **pkt,
            "bandit_params": next_params,
            "mid_session_swap": mid_swap,
            "bandit_confidence": pkt.get("bandit_confidence", 0.0),
            "execution_router": {"mode": profile["mode"], "post_only": profile["post_only"],
                                 "slice_parts": profile["slice_parts"], "delay_ms": profile["delay_ms"],
                                 "hold_orders": asm["harden"]},
            "position_scale": new_scale,
            "apply_rules": {
                **pkt.get("apply_rules", {}),
                "intraday_uplift_enabled": True,
                "capacity_checks": True
            }
        }

        audit_decisions.append({
            "asset": asset,
            "cap_ok": cap_ok,
            "swap_ok": swap_ok,
            "mid_swap": mid_swap,
            "rollback": rollback,
            "p_value": evidence.get("p_value") if evidence else None,
            "effect_size": evidence.get("effect_size") if evidence else None,
            "floors_ok": evidence.get("floors_ok") if evidence else None,
            "avg_corr": avg_corr,
            "cadence": cadence,
            "handoff_state": state,
            "handoff_ready": handoff_ready
        })

    # Persist outputs
    os.makedirs(CONFIG_DIR, exist_ok=True)
    with open(INTRA_OVERRIDES, "w") as f:
        json.dump(updated_overrides, f, indent=2)
    registry["ts"] = _now()
    with open(REGISTRY_PATH, "w") as f:
        json.dump(registry, f, indent=2)

    audit = {
        "ts": _now(),
        "portfolio_base": base,
        "floors": floors,
        "parity_info": parity_info,
        "decisions": audit_decisions,
        "intraday_overrides_path": INTRA_OVERRIDES,
        "registry_path": REGISTRY_PATH
    }
    _append_jsonl(ULTRA_LOG, {"event":"ultra_uplift_cycle_complete", **audit})
    return {"overrides": updated_overrides, "registry": registry, "audit": audit}

# ======================================================================================
# CLI quick run – simulate the ultra uplift cycle (24/7 crypto)
# ======================================================================================

if __name__ == "__main__":
    # Mock multi_asset_summary (replace with live feed)
    def mock_asset(a):
        return {
            "asset": a,
            "regime": random.choice(["trend","chop","uncertain"]),
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

    # Mock trades with tags (replace with live)
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
        ph_champ = param_hash({"lookback":50,"threshold":0.3,"stop_atr":3,"take_atr":4})
        sid_cont = f"{a}_cont"
        ph_cont = param_hash({"lookback":random.choice([20,80]),"threshold":random.choice([0.3,0.5]),"stop_atr":random.choice([2,4]),"take_atr":random.choice([3,5])})
        trades = []
        for _ in range(random.randint(90, 180)):
            # Mix trades tagged to champ and contender
            if random.random() < 0.55:
                trades.append(mock_trade(a, sid_champ, ph_champ, mu=random.uniform(-0.0004,0.001), sigma=random.uniform(0.008,0.015)))
            else:
                trades.append(mock_trade(a, sid_cont, ph_cont, mu=random.uniform(-0.0005,0.0012), sigma=random.uniform(0.008,0.015)))
        per_trade_logs_by_asset[a] = trades

    # Mock registry with tagged champion/contender
    registry = {"ts": _now(), "assets": {}}
    for a in ASSETS:
        champ_node = {"id": f"{a}_champ", "params": {"lookback":50,"threshold":0.3,"stop_atr":3,"take_atr":4}, "stats": {"expectancy":0.001,"win_rate":0.58,"profit_factor":1.5,"n":120}}
        cont_node = {"id": f"{a}_cont", "params": {"lookback":random.choice([20,80]),"threshold":random.choice([0.3,0.5]),"stop_atr":random.choice([2,4]),"take_atr":random.choice([3,5])}, "stats": {"expectancy":0.0012,"win_rate":0.60,"profit_factor":1.55,"n":120}}
        registry["assets"][a] = {"champion": champ_node, "contenders": [cont_node], "history": []}
    os.makedirs(CONFIG_DIR, exist_ok=True)
    with open(REGISTRY_PATH, "w") as f: json.dump(registry, f, indent=2)

    # Mock intraday overrides baseline
    intraday_overrides = {"ts": _now(), "assets": {}}
    for a in ASSETS:
        intraday_overrides["assets"][a] = {
            "overlays": [{"overlay":"trend_follow","enable":True,"params":{"momentum_window":[20,50,100]}}],
            "bandit_params": {"lookback":50,"threshold":0.3,"stop_atr":3,"take_atr":4},
            "bandit_confidence": random.uniform(0.55, 0.80),
            "mid_session_swap": False,
            "execution_router": {"mode": random.choice(["maker","taker"]), "post_only": True, "slice_parts":[3,5], "delay_ms":[50,80], "hold_orders": False},
            "position_scale": random.uniform(0.7, 1.0),
            "apply_rules": {"capacity_checks": True, "intraday_enabled": True, "experiment_slots": random.randint(1,3)}
        }
    with open(INTRA_OVERRIDES, "w") as f: json.dump(intraday_overrides, f, indent=2)

    out = run_ultra_uplift_cycle(
        multi_asset_summary=multi_asset_summary,
        per_trade_logs_by_asset=per_trade_logs_by_asset,
        intraday_overrides=intraday_overrides,
        registry_path=REGISTRY_PATH,
        alpha=0.05,
        min_effect=0.2
    )

    print(json.dumps({
        "floors": out["audit"]["floors"],
        "portfolio_base": out["audit"]["portfolio_base"],
        "example_asset": ASSETS[0],
        "decision": [d for d in out["audit"]["decisions"] if d["asset"] == ASSETS[0]][0],
        "intraday_overrides_path": out["audit"]["intraday_overrides_path"],
        "registry_path": out["audit"]["registry_path"]
    }, indent=2))