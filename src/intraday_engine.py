# src/intraday_engine.py
#
# Intraday Engine – Continuous Learning & Execution Edge
# Purpose:
#   Run all-the-time learning and execution upgrades:
#     - Streaming bandits (online Thompson sampling, mid-session parameter swaps)
#     - Regime ensemble gating (volatility, Hurst proxy, micro-trend classifier)
#     - Adaptive overlays (auto-toggle trend/mean-reversion intraday)
#     - Execution Router 2.0 (latency-impact slicing, maker/taker switch, adverse selection guard)
#     - Capacity frontier micro-ramp (2–3% nudges with instant rollback on degradation)
#     - Uplift allocator (experiment slots based on profit alignment + capacity health)
#
# Integration:
#   - Run continuously (e.g., every 5–10 minutes) alongside your market data and trade logs.
#   - Hooks into existing configs and logs from nightly modules (overrides, registry, audits).
#   - Writes intraday decisions to configs/intraday_overrides.json and logs/intraday_engine.jsonl.
#
# Notes:
#   - This module is designed to be pure-Python orchestration; replace stubs with live data feeds
#     (market features, order book snapshots, venue latencies) as available in your system.

import os, json, time, math, random
from statistics import mean

LOG_DIR = "logs"
CONFIG_DIR = "configs"

INTRA_LOG = os.path.join(LOG_DIR, "intraday_engine.jsonl")
INTRA_OVERRIDES = os.path.join(CONFIG_DIR, "intraday_overrides.json")

REGISTRY_PATH = os.path.join(CONFIG_DIR, "strategy_registry.json")
STRAT_OVERRIDES = os.path.join(CONFIG_DIR, "strategy_overrides.json")
ACCEL_OVERRIDES = os.path.join(CONFIG_DIR, "accelerator_overrides.json")
PUSH_OVERRIDES = os.path.join(CONFIG_DIR, "profit_push_overrides.json")

ASSETS = [
    "BTCUSDT","ETHUSDT",
    "SOLUSDT","AVAXUSDT","DOTUSDT","TRXUSDT","XRPUSDT","ADAUSDT","DOGEUSDT","BNBUSDT","MATICUSDT"
]

def _now(): return int(time.time())
def _append_jsonl(path,obj): os.makedirs(os.path.dirname(path),exist_ok=True); open(path,"a").write(json.dumps(obj)+"\n")
def _read_json(path, default=None):
    if not os.path.exists(path): return default
    try:
        with open(path,"r") as f: return json.load(f)
    except: return default

# ======================================================================================
# Feature utilities (volatility, Hurst proxy, micro-trend)
# ======================================================================================

def rolling_vol(prices, window=50):
    if not prices or len(prices) < 2:
        return 0.0
    rets = []
    for i in range(1, min(len(prices), window)):
        rets.append((prices[-i] - prices[-i-1]) / max(1e-9, prices[-i-1]))
    return abs(mean(rets)) if rets else 0.0

def hurst_proxy(prices, window=100):
    """
    Simple Hurst exponent proxy via log variance ratio.
    >0.5 trending, ~0.5 random, <0.5 mean-reverting
    """
    if not prices or len(prices) < window:
        return 0.5
    segment = prices[-window:]
    diffs = [segment[i+1]-segment[i] for i in range(len(segment)-1)]
    var1 = mean([(x-mean(diffs))**2 for x in diffs]) if diffs else 0.0
    agg = [sum(diffs[:i]) for i in range(1, len(diffs))]
    var2 = mean([(x-mean(agg))**2 for x in agg]) if agg else 0.0
    ratio = var2 / max(1e-9, var1)
    # Map ratio to [0,1] and center ~0.5
    proxy = 0.5 + 0.1 * math.tanh(ratio - 1.0)
    return max(0.0, min(1.0, proxy))

def micro_trend_classifier(prices, window=30):
    """
    Micro-trend probability based on recent slope and persistence.
    """
    if not prices or len(prices) < window:
        return {"trend_p": 0.5, "mr_p": 0.5}
    segment = prices[-window:]
    diffs = [segment[i+1]-segment[i] for i in range(len(segment)-1)]
    slope = sum(diffs) / max(1, len(diffs))
    pos_runs = sum(1 for d in diffs if d > 0)
    neg_runs = sum(1 for d in diffs if d < 0)
    trend_p = 0.5 + 0.3 * math.tanh( (slope / max(1e-9, abs(mean(segment)))) + (pos_runs - neg_runs)/max(1, len(diffs)) )
    trend_p = max(0.0, min(1.0, trend_p))
    mr_p = 1.0 - trend_p
    return {"trend_p": trend_p, "mr_p": mr_p}

# ======================================================================================
# Regime ensemble gating & adaptive overlays
# ======================================================================================

def regime_ensemble(prices):
    vol = rolling_vol(prices, window=50)
    hur = hurst_proxy(prices, window=100)
    micro = micro_trend_classifier(prices, window=30)
    # Ensemble score
    trend_score = 0.4 * (hur) + 0.4 * (micro["trend_p"]) + 0.2 * (vol > 0.01)
    chop_score = 1.0 - trend_score
    regime = "trend" if trend_score > 0.55 else ("chop" if chop_score > 0.55 else "uncertain")
    return {"regime": regime, "trend_score": round(trend_score,3), "chop_score": round(chop_score,3), "vol": round(vol,6), "hurst": round(hur,3)}

def adaptive_overlay_toggle(asset, ensemble, current_overlays):
    overlays = current_overlays[:]
    want_trend = ensemble["regime"] == "trend"
    want_mr = ensemble["regime"] == "chop"
    has_trend = any(o.get("overlay")=="trend_follow" and o.get("enable") for o in overlays)
    has_mr = any(o.get("overlay")=="mean_reversion" and o.get("enable") for o in overlays)

    changed = []
    if want_trend and not has_trend:
        overlays.append({"overlay":"trend_follow","enable":True,"params":{"momentum_window":[20,50,100]}})
        changed.append("enable_trend")
    if want_mr and not has_mr:
        overlays.append({"overlay":"mean_reversion","enable":True,"params":{"zscore_entry":[1.0,1.5,2.0]}})
        changed.append("enable_mr")
    if ensemble["regime"] == "uncertain":
        # keep risk reducer on in uncertain
        if not any(o.get("overlay")=="risk_reducer" and o.get("enable") for o in overlays):
            overlays.append({"overlay":"risk_reducer","enable":True,"params":{"position_scale":0.8}})
            changed.append("enable_risk_reducer")
    return overlays, changed

# ======================================================================================
# Streaming bandits (online Thompson sampling)
# ======================================================================================

def build_bandit_arms_from_overrides(override):
    grid = override.get("parameter_sweep_grid", {"lookback":[20,50,100],"threshold":[0.3,0.5],"stop_atr":[2,3],"take_atr":[3,4]})
    arms = []
    for lb in grid.get("lookback",[20,50]):
        for th in grid.get("threshold",[0.3,0.5]):
            for st in grid.get("stop_atr",[2,3]):
                for tk in grid.get("take_atr",[3,4]):
                    arms.append({"lookback":lb,"threshold":th,"stop_atr":st,"take_atr":tk})
    # Deduplicate and cap
    uniq = []
    seen = set()
    for a in arms:
        ser = json.dumps(a, sort_keys=True)
        if ser not in seen:
            seen.add(ser); uniq.append(a)
    return uniq[:20]

def update_posteriors_from_trades(posterior, trades_batch):
    for t in trades_batch:
        win = t.get("roi",0.0) > 0
        # If arm mapping is unknown intraday, diffuse learning across arms
        for arm_id in posterior.keys():
            a,b = posterior[arm_id]
            posterior[arm_id] = (a + (1 if win else 0), b + (0 if win else 1))
    return posterior

def thompson_pick_arm(posterior):
    best, val = None, -1
    for arm_id, (a,b) in posterior.items():
        sample = random.betavariate(a, b)
        if sample > val:
            val = sample; best = arm_id
    return best

def streaming_bandits(asset, override, trades, batch_size=20, switch_threshold=0.70):
    arms = build_bandit_arms_from_overrides(override)
    posterior = {json.dumps(a, sort_keys=True):(1,1) for a in arms}
    recent = trades[-batch_size:] if trades else []
    posterior = update_posteriors_from_trades(posterior, recent)
    chosen_id = thompson_pick_arm(posterior)
    if chosen_id is None:
        chosen_id = list(posterior.keys())[0] if posterior else json.dumps({"lookback":50,"threshold":0.4,"stop_atr":2,"take_atr":3}, sort_keys=True)
    chosen_params = json.loads(chosen_id)
    # Confidence heuristic: max sample > threshold → allow mid-session swap
    # (proxy via Beta mean a/(a+b))
    a,b = posterior.get(chosen_id, (1,1))
    confidence = a / max(1, (a+b))
    mid_session_swap = confidence >= switch_threshold
    return {"asset": asset, "params": chosen_params, "confidence": round(confidence,3), "swap": mid_session_swap}

# ======================================================================================
# Execution Router 2.0
# ======================================================================================

def latency_impact_curve(fills):
    latencies = [f.get("latency_ms",0) for f in fills]
    avg_lat = mean(latencies) if latencies else 120
    # Simple curve: higher latency → increase slices and delay
    if avg_lat <= 100:
        return {"slice_parts":[3,5], "delay_ms":[50,80]}
    elif avg_lat <= 160:
        return {"slice_parts":[5,7], "delay_ms":[80,120]}
    else:
        return {"slice_parts":[7,9], "delay_ms":[120,160]}

def maker_taker_router(spread_bps, vol_state):
    """
    Maker when spreads stable & vol low; taker when vol spiking or spreads wide.
    """
    if spread_bps <= 2 and vol_state == "low":
        return {"mode":"maker","post_only":True}
    elif spread_bps <= 4 and vol_state == "medium":
        return {"mode":"maker","post_only":True}
    else:
        return {"mode":"taker","post_only":False}

def adverse_selection_guard(quote_touch_returns):
    """
    If average short-window return after quote touch is negative → hold/cancel.
    """
    avg_r = mean(quote_touch_returns) if quote_touch_returns else 0.0
    return {"hold_orders": avg_r < 0.0, "avg_short_return": round(avg_r,6)}

def execution_router_v2(asset, recent_trades, spread_bps=3, vol="medium"):
    fills = []
    for t in recent_trades:
        fills.extend(t.get("fills", []))
    curve = latency_impact_curve(fills)
    mode = maker_taker_router(spread_bps, vol)
    guard = adverse_selection_guard([random.uniform(-0.0005,0.0007) for _ in range(30)])
    plan = {
        "asset": asset,
        "slice_parts": curve["slice_parts"],
        "delay_ms": curve["delay_ms"],
        "mode": mode["mode"],
        "post_only": mode["post_only"],
        "hold_orders": guard["hold_orders"]
    }
    return plan

# ======================================================================================
# Capacity frontier micro-ramp (2–3% nudges with rollback)
# ======================================================================================

def capacity_kpis(trades):
    slips = [((t["actual"]-t["expected"])/t["expected"]) for t in trades if "expected" in t and "actual" in t]
    fqs = []
    for t in trades:
        order = t.get("order", {})
        fills = t.get("fills", [])
        completeness = (sum(f.get("size",0.0) for f in fills) / max(order.get("size",1.0),1e-9)) if order else 1.0
        latencies = [f.get("latency_ms",0) for f in fills]
        avg_lat = mean(latencies) if latencies else 0.0
        fqs.append(completeness - avg_lat/1000.0)
    return {
        "avg_slippage": round(mean(slips) if slips else 0.0,6),
        "avg_fill_quality": round(mean(fqs) if fqs else 0.0,4)
    }

def micro_ramp(asset, kpis, current_scale=1.0, step=0.03):
    """
    Nudge position scale by 2–3% when capacity is pristine; rollback if kpis degrade.
    """
    pristine = (kpis["avg_slippage"] <= 0.0015 and kpis["avg_fill_quality"] >= 0.85)
    new_scale = current_scale
    action = "HOLD"
    if pristine and current_scale <= 1.0:
        new_scale = round(min(1.0, current_scale + step), 4)
        action = "RAMP"
    elif (kpis["avg_slippage"] > 0.0025 or kpis["avg_fill_quality"] < 0.82) and current_scale > 0.5:
        new_scale = round(max(0.5, current_scale - step), 4)
        action = "ROLLBACK"
    return {"asset": asset, "new_scale": new_scale, "action": action, "kpis": kpis}

# ======================================================================================
# Uplift allocator (experiment slots)
# ======================================================================================

def profit_alignment_score(asset_packet, trades):
    m, c = asset_packet.get("metrics", {}), asset_packet.get("capacity", {})
    wr = m.get("win_rate", 0.5); pf = m.get("profit_factor", 1.2); ev = m.get("expectancy", 0.0)
    slip = c.get("avg_slippage", 0.0018); fq = c.get("avg_fill_quality", 0.84)
    last = trades[-50:] if trades else []
    last_wr = sum(1 for t in last if t.get("roi",0.0)>0)/max(1,len(last)) if last else wr
    slip_term = max(0.0, 0.002 - slip) * 10
    fq_term = max(0.0, fq - 0.80) * 2
    score = ev*100 + (wr-0.5)*2 + (pf-1.0) + slip_term + fq_term + max(0.0, last_wr - wr)
    return round(score, 4)

def uplift_allocator(multi_asset_summary, per_trade_logs_by_asset, max_slots=10, per_asset_cap=3):
    assets = []
    for ap in multi_asset_summary.get("assets", []):
        score = profit_alignment_score(ap, per_trade_logs_by_asset.get(ap["asset"], []))
        assets.append({"asset": ap["asset"], "score": score})
    assets.sort(key=lambda x: x["score"], reverse=True)
    plan = {}
    total = 0
    for a in assets:
        if total >= max_slots: break
        slots = min(per_asset_cap, max_slots - total)
        plan[a["asset"]] = {"slots": slots, "score": a["score"]}
        total += slots
    return plan

# ======================================================================================
# Intraday orchestrator
# ======================================================================================

def intraday_cycle(multi_asset_summary,
                   per_trade_logs_by_asset,
                   recent_prices_by_asset,
                   base_overrides=None,
                   current_position_scale=None):
    """
    Continuous pass:
      - Regime ensemble → adapt overlays
      - Streaming bandits → pick params, swap when confident
      - Execution Router 2.0 → slicing, maker/taker, adverse selection guard
      - Capacity micro-ramp → nudge scale safely
      - Uplift allocator → slot experiments where upside is highest
      - Write intraday overrides for immediate application
    """
    base_overrides = base_overrides or (
        _read_json(PUSH_OVERRIDES) or _read_json(ACCEL_OVERRIDES) or _read_json(STRAT_OVERRIDES) or {"assets": {}}
    )
    current_position_scale = current_position_scale or {a:1.0 for a in ASSETS}

    intraday_overrides = {"ts": _now(), "assets": {}}
    ensemble_report = {}
    router_plans = {}
    bandit_swaps = {}
    ramp_actions = {}
    overlay_changes = {}

    # Uplift allocation
    allocation = uplift_allocator(multi_asset_summary, per_trade_logs_by_asset, max_slots=12, per_asset_cap=3)

    for ap in multi_asset_summary.get("assets", []):
        asset = ap["asset"]
        prices = recent_prices_by_asset.get(asset, [])
        trades = per_trade_logs_by_asset.get(asset, [])

        # 1) Regime ensemble & overlays
        ens = regime_ensemble(prices)
        ensemble_report[asset] = ens
        current_ov = base_overrides.get("assets", {}).get(asset, {}).get("overlays", [])
        new_ov, changed = adaptive_overlay_toggle(asset, ens, current_ov)
        overlay_changes[asset] = changed

        # 2) Streaming bandits
        override = base_overrides.get("assets", {}).get(asset, {})
        bandit_decision = streaming_bandits(asset, override, trades, batch_size=allocation.get(asset, {}).get("slots", 2)*10, switch_threshold=0.68)
        bandit_swaps[asset] = bandit_decision

        # 3) Execution router
        router_plan = execution_router_v2(asset, trades[-100:], spread_bps=random.randint(1,5), vol=("low" if ens["vol"]<0.008 else "medium" if ens["vol"]<0.015 else "high"))
        router_plans[asset] = router_plan

        # 4) Capacity micro-ramp
        kpis = capacity_kpis(trades[-120:])
        ramp = micro_ramp(asset, kpis, current_scale=current_position_scale.get(asset, 1.0), step=0.03)
        ramp_actions[asset] = ramp

        # Build intraday override entry
        intraday_overrides["assets"][asset] = {
            "overlays": new_ov,
            "bandit_params": bandit_decision["params"],
            "bandit_confidence": bandit_decision["confidence"],
            "mid_session_swap": bandit_decision["swap"],
            "execution_router": router_plan,
            "position_scale": ramp["new_scale"],
            "apply_rules": {
                "capacity_checks": True,
                "intraday_enabled": True,
                "experiment_slots": allocation.get(asset, {}).get("slots", 0)
            }
        }

    os.makedirs(CONFIG_DIR, exist_ok=True)
    with open(INTRA_OVERRIDES, "w") as f:
        json.dump(intraday_overrides, f, indent=2)

    audit = {
        "ts": _now(),
        "ensemble": ensemble_report,
        "overlay_changes": overlay_changes,
        "bandit_swaps": bandit_swaps,
        "router_plans": router_plans,
        "ramp_actions": ramp_actions,
        "uplift_allocation": allocation,
        "overrides_path": INTRA_OVERRIDES
    }
    _append_jsonl(INTRA_LOG, {"event":"intraday_cycle_complete", **audit})
    return {"overrides": intraday_overrides, "audit": audit}

# ======================================================================================
# CLI quick run – simulate intraday engine
# ======================================================================================

if __name__ == "__main__":
    # Mock multi_asset_summary
    def mock_asset(a):
        return {
            "asset": a,
            "regime": random.choice(["trend","chop","uncertain"]),
            "metrics": {
                "expectancy": random.uniform(-0.001, 0.004),
                "win_rate": random.uniform(0.45, 0.75),
                "profit_factor": random.uniform(1.0, 2.5),
                "drawdown": random.uniform(-0.08, -0.01),
                "n": random.randint(50, 140)
            },
            "capacity": {
                "avg_slippage": random.uniform(0.0004, 0.0022),
                "avg_fill_quality": random.uniform(0.80, 0.90),
                "max_drawdown": random.uniform(-0.06, -0.01),
                "n": random.randint(20, 40)
            }
        }
    multi_asset_summary = {"assets": [mock_asset(a) for a in ASSETS]}

    # Mock per-trade logs
    def mock_trade():
        roi = random.uniform(-0.02, 0.03)
        expected = 100 + random.uniform(-1,1)
        actual = expected*(1 + random.uniform(-0.0015, 0.0025))
        order = {"size": random.uniform(0.1, 1.5)}
        fills = [{"size": order["size"]*random.uniform(0.4,0.7), "latency_ms": random.randint(80,220)},
                 {"size": order["size"]*random.uniform(0.3,0.6), "latency_ms": random.randint(120,260)}]
        signals = {"Momentum": random.uniform(0.1,0.4), "OFI": random.uniform(0.05,0.3), "MeanReversion": random.uniform(0.05,0.25)}
        features = {"sentiment": random.uniform(-0.3,0.3), "vol": random.uniform(0.005,0.04), "chop": random.uniform(0.0,1.0)}
        return {"roi": roi, "expected": expected, "actual": actual, "order": order, "fills": fills, "signals": signals, "features": features}
    per_trade_logs_by_asset = {a: [mock_trade() for _ in range(random.randint(80, 160))] for a in ASSETS}

    # Mock prices
    def mock_prices(n=200):
        base = 100 + random.uniform(-2,2)
        series = [base]
        for _ in range(n-1):
            series.append(series[-1]*(1 + random.uniform(-0.003,0.003)))
        return series
    recent_prices_by_asset = {a: mock_prices(random.randint(120,220)) for a in ASSETS}

    # Mock base overrides
    base_overrides = _read_json(PUSH_OVERRIDES) or _read_json(ACCEL_OVERRIDES) or _read_json(STRAT_OVERRIDES) or {"assets": {}}
    if not base_overrides.get("assets"):
        base_overrides = {"assets": {
            "BTCUSDT": {"parameter_sweep_grid":{"lookback":[20,50,100],"threshold":[0.3,0.5],"stop_atr":[2,3],"take_atr":[3,4]},
                        "overlays":[{"overlay":"trend_follow","enable":True,"params":{"momentum_window":[20,50,100]}}]},
            "ETHUSDT": {"parameter_sweep_grid":{"lookback":[10,20,40,80],"threshold":[0.25,0.35,0.45],"stop_atr":[2,3,4],"take_atr":[3,4,5]},
                        "overlays":[{"overlay":"mean_reversion","enable":True,"params":{"zscore_entry":[1.0,1.5,2.0]}}]}
        }}

    # Mock current scale
    current_position_scale = {a: random.uniform(0.6, 1.0) for a in ASSETS}

    out = intraday_cycle(
        multi_asset_summary=multi_asset_summary,
        per_trade_logs_by_asset=per_trade_logs_by_asset,
        recent_prices_by_asset=recent_prices_by_asset,
        base_overrides=base_overrides,
        current_position_scale=current_position_scale
    )

    print(json.dumps({
        "overrides_path": INTRA_OVERRIDES,
        "example_asset": ASSETS[0],
        "ensemble": out["audit"]["ensemble"][ASSETS[0]],
        "bandit_swap": out["audit"]["bandit_swaps"][ASSETS[0]],
        "router_plan": out["audit"]["router_plans"][ASSETS[0]],
        "ramp_action": out["audit"]["ramp_actions"][ASSETS[0]],
        "slots_planned": out["audit"]["uplift_allocation"].get(ASSETS[0], {})
    }, indent=2))
