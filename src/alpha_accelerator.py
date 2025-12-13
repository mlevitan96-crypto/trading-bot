# src/alpha_accelerator.py
#
# Alpha Accelerator Module – Aggressive meta-research, cross-asset learning, and fast promotions
# Purpose:
#   Double the pace of alpha discovery with:
#     - Multi-contender seeding per asset (diverse parameter grids)
#     - Expanded Bayesian bandit arms and parallel trials
#     - Cross-asset attribution transfer (signal uplift/downweight)
#     - Aggressive canary rotation (shorter windows, faster promotions)
#     - Anomaly-driven exploration (auto-spin new overlays on regime/exec issues)
#     - Global attribution boost (reinforce strong signals across the portfolio)
#     - Full audit trails and wiring hooks to nightly cycle
#
# Inputs:
#   - multi_asset_summary: from multi_asset_orchestration.multi_asset_cycle(...)
#   - governance_audit: from governance_upgrade.run_governance_upgrade(...)
#   - strategy_registry: configs/strategy_registry.json (alpha_lab)
#   - auto_correction_overrides: configs/strategy_overrides.json
#   - per_trade_logs_by_asset: {symbol: [trade dicts with signals/features/roi/order/fills]}
#
# Outputs:
#   - configs/strategy_registry.json (updated with seeded contenders and promotions)
#   - configs/accelerator_overrides.json (fast canary rotation overrides)
#   - logs/alpha_accelerator.jsonl (audit of seeding, bandit arms, promotions, transfers)
#
# Integration:
#   Run after alpha_lab_cycle and governance_upgrade; before portfolio_scaling.
#   Call alpha_accelerator_cycle(...) in the nightly orchestration.

import os, json, time, math, random, copy
from statistics import mean
from src.infrastructure.path_registry import PathRegistry

LOG_DIR = str(PathRegistry.LOGS_DIR)
CONFIG_DIR = str(PathRegistry.CONFIGS_DIR)

ACCEL_LOG = PathRegistry.get_path("logs", "alpha_accelerator.jsonl")
REGISTRY_PATH = PathRegistry.get_path("configs", "strategy_registry.json")
STRAT_OVERRIDES = PathRegistry.get_path("configs", "strategy_overrides.json")
ACCEL_OVERRIDES = PathRegistry.get_path("configs", "accelerator_overrides.json")

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

def _ensure_registry():
    reg = _read_json(REGISTRY_PATH, default={"ts": _now(), "assets": {a: {"champion": None, "contenders": [], "history": []} for a in ASSETS}})
    if reg is None:
        reg = {"ts": _now(), "assets": {a: {"champion": None, "contenders": [], "history": []} for a in ASSETS}}
    assets = reg.get("assets", {})
    for a in ASSETS:
        assets.setdefault(a, {"champion": None, "contenders": [], "history": []})
    reg["assets"] = assets
    return reg

def _rand_id(prefix="strat"): return f"{prefix}_{int(_now())}_{random.randint(1000,9999)}"

def _grid_trend():
    return {
        "lookback": [10, 20, 40, 80, 120],
        "threshold": [0.25, 0.35, 0.45, 0.55],
        "breakout_z": [1.0, 1.5, 2.0],
        "stop_atr": [2, 3, 4],
        "take_atr": [3, 4, 5]
    }

def _grid_chop():
    return {
        "lookback": [10, 15, 25, 35],
        "mean_rev_z": [0.8, 1.2, 1.6, 2.0],
        "entry_cooldown": [2, 3, 5],
        "stop_atr": [1.5, 2.0, 2.5],
        "take_atr": [2.5, 3.5, 4.5]
    }

def _grid_uncertain():
    return {
        "lookback": [20, 40, 80],
        "hybrid_blend": [0.3, 0.5, 0.7],
        "stop_atr": [2, 3],
        "take_atr": [3, 4]
    }

def _seed_signals(regime):
    if regime == "trend":
        return ["Momentum","OFI","Carry"]
    if regime == "chop":
        return ["MeanReversion","LiquidityImbalance","VWAPDist"]
    return ["Momentum","MeanReversion","OFI"]

def seed_contenders(registry, multi_asset_summary, per_asset_seed_count=6):
    seeded = []
    for ap in multi_asset_summary.get("assets", []):
        asset, regime = ap["asset"], ap.get("regime","uncertain")
        grid = _grid_trend() if regime=="trend" else (_grid_chop() if regime=="chop" else _grid_uncertain())
        signals = _seed_signals(regime)
        registry["assets"].setdefault(asset, {"champion": None, "contenders": [], "history": []})
        for _ in range(per_asset_seed_count):
            strat_id = _rand_id(asset)
            params = {
                "lookback": random.choice(grid.get("lookback",[20,50])),
                "threshold": random.choice(grid.get("threshold",[0.3,0.5])) if "threshold" in grid else None,
                "breakout_z": random.choice(grid.get("breakout_z",[1.5])) if "breakout_z" in grid else None,
                "mean_rev_z": random.choice(grid.get("mean_rev_z",[1.2])) if "mean_rev_z" in grid else None,
                "entry_cooldown": random.choice(grid.get("entry_cooldown",[3])) if "entry_cooldown" in grid else None,
                "stop_atr": random.choice(grid.get("stop_atr",[2,3,4])),
                "take_atr": random.choice(grid.get("take_atr",[3,4,5])),
                "hybrid_blend": random.choice(grid.get("hybrid_blend",[0.5])) if "hybrid_blend" in grid else None
            }
            params = {k:v for k,v in params.items() if v is not None}
            node = {
                "id": strat_id,
                "params": params,
                "signals": signals,
                "regime_bias": regime,
                "stats": {"expectancy": 0.0, "win_rate": 0.0, "profit_factor": 0.0, "n": 0}
            }
            registry["assets"][asset]["contenders"].append(node)
            seeded.append({"asset":asset,"id":strat_id,"regime":regime,"params":params,"signals":signals})
    _append_jsonl(ACCEL_LOG, {"ts": _now(), "event":"seed_contenders", "count": len(seeded)})
    return registry, seeded

def build_arms_from_grid(grid, max_arms=15):
    keys = list(grid.keys())
    arms = []
    for _ in range(max_arms):
        params = {}
        for k in keys:
            params[k] = random.choice(grid[k])
        arms.append(params)
    seen, unique = set(), []
    for p in arms:
        ser = json.dumps(p, sort_keys=True)
        if ser not in seen:
            seen.add(ser)
            unique.append(p)
    return unique

def thompson_select_arm(posterior):
    best_arm, best_val = None, -1
    for arm_id, (a,b) in posterior.items():
        sample = random.betavariate(a, b)
        if sample > best_val:
            best_val, best_arm = sample, arm_id
    return best_arm

def update_posterior(posterior, arm_id, win):
    a,b = posterior.get(arm_id,(1,1))
    posterior[arm_id] = (a + (1 if win else 0), b + (0 if win else 1))
    return posterior

def run_parallel_bandits(registry, per_trade_logs_by_asset, per_asset_max_arms=12):
    plans = {}
    for asset in ASSETS:
        conts = registry["assets"][asset]["contenders"]
        if not conts: continue
        regime = conts[0]["regime_bias"]
        base_grid = _grid_trend() if regime=="trend" else (_grid_chop() if regime=="chop" else _grid_uncertain())
        arms = build_arms_from_grid(base_grid, max_arms=per_asset_max_arms)
        posterior = {json.dumps(a, sort_keys=True):(1,1) for a in arms}
        trades = per_trade_logs_by_asset.get(asset, [])[-min(150, len(per_trade_logs_by_asset.get(asset, []))):]
        for t in trades:
            arm_id = random.choice(list(posterior.keys()))
            update_posterior(posterior, arm_id, win=(t.get("roi",0.0) > 0))
        chosen_arm_id = thompson_select_arm(posterior)
        if chosen_arm_id is None:
            continue
        chosen_params = json.loads(chosen_arm_id)
        plans[asset] = {"chosen_arm_id": chosen_arm_id, "params": chosen_params, "posterior_size": len(posterior)}
    _append_jsonl(ACCEL_LOG, {"ts": _now(), "event":"parallel_bandits", "assets": list(plans.keys())})
    return plans

def aggregate_attribution(per_trade_logs_by_asset):
    signal_wr = {}
    for asset, trades in per_trade_logs_by_asset.items():
        hits, cnt = {}, {}
        for t in trades:
            r = t.get("roi",0.0)
            for s, w in t.get("signals", {}).items():
                cnt[s] = cnt.get(s,0)+1
                if r>0: hits[s] = hits.get(s,0)+1
        wr = {s: (hits.get(s,0)/cnt[s]) for s in cnt} if cnt else {}
        signal_wr[asset] = wr
    return signal_wr

def cross_asset_transfer(signal_wr_by_asset, uplift_thresh=0.65, down_thresh=0.45):
    signal_pool = {}
    counts = {}
    for asset, wrs in signal_wr_by_asset.items():
        for s, wr in wrs.items():
            signal_pool[s] = signal_pool.get(s,0.0) + wr
            counts[s] = counts.get(s,0) + 1
    avg_wr = {s: signal_pool[s]/counts[s] for s in signal_pool}
    strong = [s for s, wr in avg_wr.items() if wr >= uplift_thresh]
    weak = [s for s, wr in avg_wr.items() if wr <= down_thresh]
    transfer = {"strong": strong, "weak": weak, "avg_wr": avg_wr}
    _append_jsonl(ACCEL_LOG, {"ts": _now(), "event":"cross_asset_transfer", "strong": strong, "weak": weak})
    return transfer

def apply_transfer_to_contenders(registry, transfer):
    strong, weak = transfer["strong"], transfer["weak"]
    for asset in ASSETS:
        for c in registry["assets"][asset]["contenders"]:
            c.setdefault("signal_bias", {})
            for s in strong:
                c["signal_bias"][s] = c["signal_bias"].get(s, 0.0) + 0.15
            for s in weak:
                c["signal_bias"][s] = c["signal_bias"].get(s, 0.0) - 0.15
    _append_jsonl(ACCEL_LOG, {"ts": _now(), "event":"apply_transfer_bias"})
    return registry

def build_accelerator_overrides(strategy_overrides, canary_fraction=0.2, promote_min_trades=60):
    accel = copy.deepcopy(strategy_overrides or {"ts": _now(), "assets": {}})
    accel["ts"] = _now()
    for a, pkt in accel.get("assets", {}).items():
        rules = pkt.get("apply_rules", {})
        rules["canary_fraction"] = canary_fraction
        rules["canary_min_trades"] = max(rules.get("canary_min_trades", 50), promote_min_trades)
        rules["promotion_criteria"] = {"expectancy_gt": 0.0, "win_rate_ge": 0.58, "pf_ge": 1.45, "capacity_ok": True}
        pkt["apply_rules"] = rules
        overlays = pkt.get("overlays", [])
        overlays.append({"overlay":"risk_reducer","enable":True,"params":{"position_scale":max(0.1, 1.0 - canary_fraction)}})
        pkt["overlays"] = overlays
    os.makedirs(CONFIG_DIR, exist_ok=True)
    with open(ACCEL_OVERRIDES, "w") as f:
        json.dump(accel, f, indent=2)
    _append_jsonl(ACCEL_LOG, {"ts": _now(), "event":"accelerator_overrides_written", "path": ACCEL_OVERRIDES})
    return accel

def detect_anomalies(trades_window, regime, slip_gate=0.0025, fq_gate=0.80, wr_gate=0.45):
    slips = [((t["actual"]-t["expected"])/t["expected"]) for t in trades_window if "expected" in t and "actual" in t]
    wr = sum(1 for t in trades_window if t.get("roi",0.0) > 0)/max(1,len(trades_window))
    fqs = []
    for t in trades_window:
        order = t.get("order", {})
        fills = t.get("fills", [])
        completeness = (sum(f.get("size",0.0) for f in fills) / max(order.get("size",1.0), 1e-9)) if order else 1.0
        latencies = [f.get("latency_ms",0) for f in fills]
        avg_lat = mean(latencies) if latencies else 0.0
        fqs.append(completeness - avg_lat/1000.0)
    anomalies = []
    if slips and mean(slips) > slip_gate: anomalies.append("slippage_exceeded")
    if fqs and mean(fqs) < fq_gate: anomalies.append("fill_quality_degraded")
    if wr < wr_gate: anomalies.append("low_win_rate")
    if regime=="trend" and wr < 0.52: anomalies.append("trend_mismatch")
    if regime=="chop" and wr < 0.50: anomalies.append("chop_mismatch")
    return anomalies

def anomaly_exploration(registry, multi_asset_summary, per_trade_logs_by_asset):
    spins = []
    for ap in multi_asset_summary.get("assets", []):
        asset, regime = ap["asset"], ap.get("regime","uncertain")
        window = per_trade_logs_by_asset.get(asset, [])[-50:]
        anomalies = detect_anomalies(window, regime)
        if not anomalies: continue
        if "trend_mismatch" in anomalies or regime=="chop":
            node = {
                "id": _rand_id(asset),
                "params": {"lookback": random.choice([10,15,25,35]), "mean_rev_z": random.choice([1.2,1.6,2.0]), "stop_atr": random.choice([1.5,2.0,2.5]), "take_atr": random.choice([2.5,3.5,4.5])},
                "signals": ["MeanReversion","LiquidityImbalance","VWAPDist"],
                "regime_bias": "chop",
                "stats": {"expectancy": 0.0, "win_rate": 0.0, "profit_factor": 0.0, "n": 0}
            }
            registry["assets"][asset]["contenders"].append(node)
            spins.append({"asset":asset,"overlay":"mean_reversion"})
        if "chop_mismatch" in anomalies or regime=="trend":
            node = {
                "id": _rand_id(asset),
                "params": {"lookback": random.choice([20,40,80,120]), "threshold": random.choice([0.25,0.35,0.45]), "breakout_z": random.choice([1.0,1.5,2.0]), "stop_atr": random.choice([2,3,4]), "take_atr": random.choice([3,4,5])},
                "signals": ["Momentum","OFI","Carry"],
                "regime_bias": "trend",
                "stats": {"expectancy": 0.0, "win_rate": 0.0, "profit_factor": 0.0, "n": 0}
            }
            registry["assets"][asset]["contenders"].append(node)
            spins.append({"asset":asset,"overlay":"trend_follow"})
    _append_jsonl(ACCEL_LOG, {"ts": _now(), "event":"anomaly_exploration_spins", "count": len(spins)})
    return registry, spins

def global_attribution_boost(registry, transfer, boost=0.10, cut=0.10):
    strong, weak = transfer["strong"], transfer["weak"]
    changes = []
    for asset in ASSETS:
        for c in registry["assets"][asset]["contenders"]:
            c.setdefault("signal_bias", {})
            for s in strong:
                c["signal_bias"][s] = c["signal_bias"].get(s, 0.0) + boost
                changes.append({"asset":asset,"signal":s,"delta":boost})
            for s in weak:
                c["signal_bias"][s] = c["signal_bias"].get(s, 0.0) - cut
                changes.append({"asset":asset,"signal":s,"delta":-cut})
    _append_jsonl(ACCEL_LOG, {"ts": _now(), "event":"global_attribution_boost", "changes": len(changes)})
    return registry, changes

def fast_promotion_gate(stats, capacity_ok=True):
    return (stats.get("expectancy",0.0) > 0.0 and stats.get("win_rate",0.0) >= 0.58 and stats.get("profit_factor",0.0) >= 1.45 and capacity_ok)

def update_contender_stats_from_trades(contender, trades):
    rois = [t.get("roi",0.0) for t in trades]
    if not rois:
        return contender
    wr = sum(1 for r in rois if r>0)/len(rois)
    gains = sum(r for r in rois if r>0)
    losses = abs(sum(r for r in rois if r<0))
    pf = (gains / losses) if losses > 0 else float('inf')
    contender["stats"] = {"expectancy": round(mean(rois),6), "win_rate": round(wr,4), "profit_factor": round(pf,4), "n": len(rois)}
    return contender

def evaluate_and_promote_fast(registry, per_trade_logs_by_asset, capacity_ok_assets=None):
    promoted = []
    for asset in ASSETS:
        conts = registry["assets"][asset]["contenders"]
        if not conts: continue
        trades = per_trade_logs_by_asset.get(asset, [])
        for c in conts:
            update_contender_stats_from_trades(c, trades[-max(60, min(200, len(trades))):])
            if fast_promotion_gate(c["stats"], capacity_ok=True if (capacity_ok_assets is None or asset in capacity_ok_assets) else False):
                registry["assets"][asset]["champion"] = c
                registry["assets"][asset]["history"].append({"ts": _now(), "id": c["id"], "outcome": "promoted_fast", "stats": c["stats"]})
                promoted.append({"asset":asset,"id":c["id"],"stats":c["stats"]})
                registry["assets"][asset]["contenders"] = [c] + registry["assets"][asset]["contenders"][:2]
    _append_jsonl(ACCEL_LOG, {"ts": _now(), "event":"evaluate_and_promote_fast", "promoted": promoted})
    return registry, promoted

def alpha_accelerator_cycle(multi_asset_summary,
                            governance_audit,
                            per_trade_logs_by_asset,
                            auto_correction_overrides=None):
    """
    Runs the full alpha accelerator pass:
      - Seed multiple contenders per asset
      - Run expanded bandit arms and record chosen params
      - Transfer attribution across assets (global strong/weak signals)
      - Spin overlays on anomalies
      - Apply global attribution boosts
      - Write aggressive canary overrides (short window)
      - Attempt fast promotions with capacity gates
      - Save registry and accelerator overrides; write audit
    """
    registry = _ensure_registry()
    strat_overrides = auto_correction_overrides or _read_json(STRAT_OVERRIDES, default={"ts": _now(), "assets": {}})

    registry, seeded = seed_contenders(registry, multi_asset_summary, per_asset_seed_count=6)
    bandit_plans = run_parallel_bandits(registry, per_trade_logs_by_asset, per_asset_max_arms=12)
    signal_wr_by_asset = aggregate_attribution(per_trade_logs_by_asset)
    transfer = cross_asset_transfer(signal_wr_by_asset, uplift_thresh=0.65, down_thresh=0.45)
    registry = apply_transfer_to_contenders(registry, transfer)
    registry, spins = anomaly_exploration(registry, multi_asset_summary, per_trade_logs_by_asset)
    registry, boost_changes = global_attribution_boost(registry, transfer, boost=0.10, cut=0.10)
    accel_overrides = build_accelerator_overrides(strat_overrides, canary_fraction=0.2, promote_min_trades=60)
    capacity_ok_assets = set(governance_audit.get("summary", {}).get("promoted_assets", []))
    registry, promoted = evaluate_and_promote_fast(registry, per_trade_logs_by_asset, capacity_ok_assets=capacity_ok_assets)

    os.makedirs(CONFIG_DIR, exist_ok=True)
    registry["ts"] = _now()
    with open(REGISTRY_PATH, "w") as f:
        json.dump(registry, f, indent=2)
    with open(ACCEL_OVERRIDES, "w") as f:
        json.dump(accel_overrides, f, indent=2)

    audit = {
        "ts": _now(),
        "seeded_count": len(seeded),
        "bandit_assets": list(bandit_plans.keys()),
        "spins_count": len(spins),
        "boost_changes": len(boost_changes),
        "promoted_fast": promoted
    }
    _append_jsonl(ACCEL_LOG, {"event":"alpha_accelerator_cycle_complete", **audit})
    return {"registry": registry, "accelerator_overrides": accel_overrides, "audit": audit}

if __name__ == "__main__":
    multi_asset_summary = {
        "assets": [{"asset": a, "regime": random.choice(["trend","chop","uncertain"])} for a in ASSETS]
    }

    def mock_trade():
        roi = random.uniform(-0.02, 0.03)
        expected = 100 + random.uniform(-1,1)
        actual = expected*(1 + random.uniform(-0.0015, 0.0030))
        order = {"size": random.uniform(0.1, 1.5)}
        fills = [{"size": order["size"]*random.uniform(0.4,0.7), "latency_ms": random.randint(80,220)},
                 {"size": order["size"]*random.uniform(0.3,0.6), "latency_ms": random.randint(120,260)}]
        signals = {"Momentum": random.uniform(0.1,0.4), "OFI": random.uniform(0.05,0.3), "MeanReversion": random.uniform(0.05,0.25)}
        features = {"sentiment": random.uniform(-0.3,0.3), "vol": random.uniform(0.005,0.04), "chop": random.uniform(0.0,1.0)}
        return {"roi": roi, "expected": expected, "actual": actual, "order": order, "fills": fills, "signals": signals, "features": features}

    per_trade_logs_by_asset = {a: [mock_trade() for _ in range(random.randint(80,160))] for a in ASSETS}

    governance_audit = {
        "summary": {
            "promoted_assets": ["BTCUSDT"],
            "rolled_back_assets": ["SOLUSDT","ADAUSDT"]
        }
    }

    auto_correction_overrides = {
        "ts": _now(),
        "assets": {
            "ETHUSDT": {
                "signal_reweights":[{"signal":"Momentum","delta_weight":+0.15},{"signal":"MeanReversion","delta_weight":-0.10}],
                "overlays":[{"overlay":"trend_follow","enable":True,"params":{"momentum_window":[20,50,100]}}],
                "parameter_sweep_grid":{"lookback":[20,50,100],"threshold":[0.3,0.5],"stop_atr":[2,3],"take_atr":[3,4]},
                "apply_rules":{"capacity_checks":True,"canary_min_trades":80}
            }
        }
    }

    out = alpha_accelerator_cycle(
        multi_asset_summary=multi_asset_summary,
        governance_audit=governance_audit,
        per_trade_logs_by_asset=per_trade_logs_by_asset,
        auto_correction_overrides=auto_correction_overrides
    )

    print(json.dumps({
        "seeded_contenders_total": sum(len(out["registry"]["assets"][a]["contenders"]) for a in ASSETS),
        "bandit_assets": out["audit"]["bandit_assets"],
        "promoted_fast": out["audit"]["promoted_fast"]
    }, indent=2))
