# src/profit_push_engine.py
#
# Profit Push Engine — relentless autonomous improvement loop
# Goal:
#   - Drive continuous profitability gains with adaptive exploration intensity, auto-pruning,
#     uplift targeting, and rolling profit objectives at asset and portfolio levels.
#   - Tight safety gates remain (capacity + canary), but the engine ramps experiments when
#     upside is detected and prunes losers fast.
#
# What this module adds:
#   1) Exploration intensity controller (per-asset) driven by uplift potential and risk health
#   2) Uplift targeting — prioritize assets/arms predicted to increase expectancy fastest
#   3) Auto-pruning of underperforming contenders and failed arms with evidence thresholds
#   4) Rolling profit objectives (asset + portfolio) that shape nightly decisions
#   5) Adaptive thresholds — relax gates slightly when capacity is pristine; tighten when not
#   6) Profit alignment scoring — rank overrides and bandit arms by expected profit uplift
#   7) Autonomous schedule — runs post-accelerator, pre-scaling; writes overrides back to configs
#
# Inputs:
#   - multi_asset_summary: dict with assets, regimes, metrics, capacity
#   - strategy_registry: configs/strategy_registry.json (champions/contenders)
#   - accelerator_overrides: configs/accelerator_overrides.json (from alpha_accelerator)
#   - canary_overrides: configs/canary_overrides.json
#   - per_trade_logs_by_asset: {symbol: [trade dicts]}
#   - governance_audit: governance_upgrade audit packet (promotion/rollback, drift)
#
# Outputs:
#   - configs/profit_push_overrides.json (prioritized overrides with exploration intensity)
#   - logs/profit_push_engine.jsonl (audit of intensity decisions, pruning, objectives)
#
# Integration:
#   - Call run_profit_push(...) after alpha_accelerator_cycle and before portfolio scaling.
#   - It updates overrides with exploration intensity and pruning decisions.

import os, json, time, random, copy
from statistics import mean

LOG_DIR = "logs"
CONFIG_DIR = "configs"

PUSH_LOG = os.path.join(LOG_DIR, "profit_push_engine.jsonl")
PUSH_OVERRIDES = os.path.join(CONFIG_DIR, "profit_push_overrides.json")
REGISTRY_PATH = os.path.join(CONFIG_DIR, "strategy_registry.json")
ACCEL_OVERRIDES = os.path.join(CONFIG_DIR, "accelerator_overrides.json")
CANARY_OVERRIDES = os.path.join(CONFIG_DIR, "canary_overrides.json")

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

# --------------------------------------------------------------------------------------
# 1) Rolling profit objectives — asset & portfolio
# --------------------------------------------------------------------------------------
def rolling_objectives(multi_asset_summary, horizon_assets=None):
    """
    Define rolling objectives used to steer exploration and promotion:
      - Asset target: expectancy > 0, WR ≥ 0.60, PF ≥ 1.5 within horizon
      - Portfolio target: net expectancy > 0; drawdown ≤ 5%; capacity OK
    """
    objs = {"asset": {"ev_gt": 0.0, "wr_ge": 0.60, "pf_ge": 1.5},
            "portfolio": {"ev_gt": 0.0, "max_dd_le": 0.05, "capacity_ok": True}}
    # Compute current rough portfolio EV from assets
    assets = multi_asset_summary.get("assets", [])
    evs = [a["metrics"].get("expectancy",0.0) for a in assets]
    current_portfolio_ev = round(sum(evs)/max(1,len(evs)), 6) if evs else 0.0
    objs["current_portfolio_ev"] = current_portfolio_ev
    return objs

# --------------------------------------------------------------------------------------
# 2) Profit alignment score — rank arms and overrides by uplift potential
# --------------------------------------------------------------------------------------
def profit_alignment_score(asset_packet, per_trade_trades):
    """
    Predict uplift potential using simple proxies:
      - Higher recent WR and PF → higher score
      - Lower slippage and better fill quality → higher score
      - Regime match bonus
    """
    m, c = asset_packet["metrics"], asset_packet["capacity"]
    wr = m.get("win_rate", 0.5)
    pf = m.get("profit_factor", 1.0)
    ev = m.get("expectancy", 0.0)
    slip = c.get("avg_slippage", 0.001)
    fq = c.get("avg_fill_quality", 0.85)
    regime = asset_packet.get("regime","uncertain")
    regime_bonus = 0.05 if (regime=="trend" and wr>=0.60) or (regime=="chop" and wr>=0.55) else 0.0
    # Normalize slip (lower is better) and fq
    slip_term = max(0.0, 0.002 - slip) * 10
    fq_term = max(0.0, fq - 0.80) * 2
    # Recent trade trend
    last = per_trade_trades[-50:] if per_trade_trades else []
    last_wr = sum(1 for t in last if t.get("roi",0.0)>0)/max(1,len(last)) if last else wr
    trend_bonus = max(0.0, last_wr - wr) * 0.5
    score = ev*100 + (wr-0.5)*2 + (pf-1.0) + slip_term + fq_term + regime_bonus + trend_bonus
    return round(score, 4)

# --------------------------------------------------------------------------------------
# 3) Exploration intensity controller
# --------------------------------------------------------------------------------------
def exploration_intensity(asset_packet, profit_score, governance_health, max_level=3):
    """
    Levels:
      0 = conservative (few arms, no new contenders)
      1 = default (baseline accelerator settings)
      2 = boosted (extra contenders & arms)
      3 = max push (aggressive experiments & fast gates)
    Rules:
      - If capacity pristine and profit_score strong → increase level
      - If capacity degraded or drift alarms → decrease level
    """
    slip_ok = asset_packet["capacity"].get("avg_slippage",0.0) <= 0.0015
    fq_ok = asset_packet["capacity"].get("avg_fill_quality",1.0) >= 0.85
    drift_alarm = governance_health.get("drift_alarm", False)
    anomalies = governance_health.get("anomalies", [])

    level = 1
    if slip_ok and fq_ok and profit_score > 0.8:
        level = 2
    if slip_ok and fq_ok and profit_score > 1.2:
        level = 3
    if drift_alarm or ("slippage_exceeded" in anomalies) or ("fill_quality_degraded" in anomalies):
        level = max(0, level - 1)
    return min(max_level, level)

def intensity_to_settings(level, base_arms=12, base_contenders=6):
    if level == 0:
        return {"arms": max(4, base_arms//2), "contenders": max(2, base_contenders//2), "fast_gate": False}
    if level == 1:
        return {"arms": base_arms, "contenders": base_contenders, "fast_gate": True}
    if level == 2:
        return {"arms": base_arms + 4, "contenders": base_contenders + 2, "fast_gate": True}
    if level == 3:
        return {"arms": base_arms + 8, "contenders": base_contenders + 4, "fast_gate": True}

# --------------------------------------------------------------------------------------
# 4) Auto-pruning of underperforming contenders and failed arms
# --------------------------------------------------------------------------------------
def prune_contenders(registry, asset, min_n=60, wr_floor=0.50, ev_floor=0.0):
    """
    Remove contenders with enough evidence that they are losing.
    """
    conts = registry["assets"][asset]["contenders"]
    keep = []
    pruned = []
    for c in conts:
        s = c.get("stats", {})
        if s.get("n",0) >= min_n and (s.get("win_rate",0.0) < wr_floor or s.get("expectancy",0.0) <= ev_floor):
            pruned.append(c["id"])
        else:
            keep.append(c)
    registry["assets"][asset]["contenders"] = keep
    return registry, pruned

# --------------------------------------------------------------------------------------
# 5) Adaptive thresholds — tighten/relax gates by capacity health
# --------------------------------------------------------------------------------------
def adaptive_gates(capacity_ok):
    """
    If capacity pristine, allow faster promotion (slightly relaxed gates).
    If capacity poor, tighten gates.
    """
    if capacity_ok:
        return {"win_rate_ge": 0.58, "pf_ge": 1.45, "ev_gt": 0.0, "min_trades": 60}
    else:
        return {"win_rate_ge": 0.62, "pf_ge": 1.55, "ev_gt": 0.001, "min_trades": 80}

# --------------------------------------------------------------------------------------
# 6) Override writer — apply intensity into overrides
# --------------------------------------------------------------------------------------
def write_profit_push_overrides(accel_overrides, intensity_map, gates_map):
    """
    Combine accelerator overrides with intensity levels and adaptive gates.
    """
    push = copy.deepcopy(accel_overrides or {"ts": _now(), "assets": {}})
    push["ts"] = _now()
    for a, pkt in push.get("assets", {}).items():
        rules = pkt.get("apply_rules", {})
        imap = intensity_map.get(a, {"arms": 12, "contenders": 6, "fast_gate": True})
        gates = gates_map.get(a, {"win_rate_ge": 0.58, "pf_ge": 1.45, "ev_gt": 0.0, "min_trades": 60})
        # Annotate exploration settings for downstream modules (bandits/accelerator)
        rules["exploration_arms"] = imap["arms"]
        rules["exploration_contenders"] = imap["contenders"]
        rules["fast_gate_enabled"] = imap["fast_gate"]
        # Adaptive gates for canary promotion
        rules["promotion_criteria"] = {"win_rate_ge": gates["win_rate_ge"], "pf_ge": gates["pf_ge"],
                                       "expectancy_gt": gates["ev_gt"], "capacity_ok": True}
        rules["canary_min_trades"] = gates["min_trades"]
        pkt["apply_rules"] = rules
        push["assets"][a] = pkt
    os.makedirs(CONFIG_DIR, exist_ok=True)
    with open(PUSH_OVERRIDES, "w") as f:
        json.dump(push, f, indent=2)
    _append_jsonl(PUSH_LOG, {"ts": _now(), "event":"profit_push_overrides_written", "path": PUSH_OVERRIDES})
    return push

# --------------------------------------------------------------------------------------
# 7) Core orchestrator — run profit push
# --------------------------------------------------------------------------------------
def run_profit_push(multi_asset_summary,
                    per_trade_logs_by_asset,
                    governance_audit,
                    accelerator_overrides=None,
                    registry=None,
                    anomalies_by_asset=None):
    """
    Steps:
      - Compute rolling objectives and per-asset profit alignment
      - Determine exploration intensity per asset based on profit score and governance health
      - Build adaptive gates per asset (capacity-aware)
      - Prune losing contenders (evidence-based)
      - Write profit_push_overrides with intensity + adaptive gates
      - Return audit packet
    """
    accelerator_overrides = accelerator_overrides or _read_json(ACCEL_OVERRIDES, default={"ts": _now(), "assets": {}})
    registry = registry or _read_json(REGISTRY_PATH, default={"ts": _now(), "assets": {a: {"champion": None, "contenders": [], "history": []} for a in ASSETS}})
    anomalies_by_asset = anomalies_by_asset or {}

    objs = rolling_objectives(multi_asset_summary)
    intensity_map = {}
    gates_map = {}
    pruned_map = {}

    # Capacity health context
    capacity_ok_assets = set(governance_audit.get("summary", {}).get("promoted_assets", []))
    for ap in multi_asset_summary.get("assets", []):
        asset = ap["asset"]
        trades = per_trade_logs_by_asset.get(asset, [])
        pscore = profit_alignment_score(ap, trades)
        governance_health = {
            "drift_alarm": False,  # could be read from governance audit
            "anomalies": anomalies_by_asset.get(asset, [])
        }
        level = exploration_intensity(ap, pscore, governance_health, max_level=3)
        intensity_map[asset] = intensity_to_settings(level, base_arms=12, base_contenders=6)

        gates = adaptive_gates(capacity_ok=(asset in capacity_ok_assets))
        gates_map[asset] = gates

        # Prune contenders (evidence-based)
        registry, pruned = prune_contenders(registry, asset, min_n=gates["min_trades"], wr_floor=gates["win_rate_ge"], ev_floor=gates["ev_gt"])
        pruned_map[asset] = pruned

    # Write overrides
    push_overrides = write_profit_push_overrides(accelerator_overrides, intensity_map, gates_map)

    audit = {
        "ts": _now(),
        "objectives": objs,
        "intensity_map": intensity_map,
        "adaptive_gates": gates_map,
        "pruned": pruned_map,
        "overrides_path": PUSH_OVERRIDES
    }
    _append_jsonl(PUSH_LOG, {"event":"profit_push_complete", **audit})
    return {"overrides": push_overrides, "audit": audit, "registry": registry}

# --------------------------------------------------------------------------------------
# CLI quick run — simulate profit push
# --------------------------------------------------------------------------------------
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

    # Mock governance audit
    governance_audit = {
        "summary": {
            "promoted_assets": ["BTCUSDT","ETHUSDT"],  # treat as capacity OK
            "rolled_back_assets": ["ADAUSDT"]
        }
    }

    # Mock accelerator overrides
    accelerator_overrides = _read_json(ACCEL_OVERRIDES, default={"ts": _now(), "assets": {}})
    if not accelerator_overrides.get("assets"):
        accelerator_overrides = {
            "ts": _now(),
            "assets": {
                "BTCUSDT": {"apply_rules": {"capacity_checks": True, "canary_fraction": 0.2, "canary_min_trades": 60}, "overlays": []},
                "ETHUSDT": {"apply_rules": {"capacity_checks": True, "canary_fraction": 0.2, "canary_min_trades": 60}, "overlays": []}
            }
        }

    # Mock registry with contenders
    registry = _read_json(REGISTRY_PATH, default={"ts": _now(), "assets": {a: {"champion": None, "contenders": [], "history": []} for a in ASSETS}})
    if registry is None:
        registry = {"ts": _now(), "assets": {a: {"champion": None, "contenders": [], "history": []} for a in ASSETS}}
    for a in ASSETS:
        registry["assets"].setdefault(a, {"champion": None, "contenders": [], "history": []})
        # Seed 3 contenders with random stats
        for i in range(3):
            registry["assets"][a]["contenders"].append({
                "id": f"{a}_c{i}",
                "params": {"lookback": random.choice([20,40,80]), "stop_atr": random.choice([2,3,4]), "take_atr": random.choice([3,4,5])},
                "signals": ["Momentum","OFI","MeanReversion"],
                "regime_bias": random.choice(["trend","chop","uncertain"]),
                "stats": {"expectancy": random.uniform(-0.001, 0.002), "win_rate": random.uniform(0.45,0.70), "profit_factor": random.uniform(1.0, 1.8), "n": random.randint(40,120)}
            })
    os.makedirs(CONFIG_DIR, exist_ok=True)
    with open(REGISTRY_PATH, "w") as f:
        json.dump(registry, f, indent=2)

    # Mock anomalies by asset
    anomalies_by_asset = {a: random.sample(["slippage_exceeded","fill_quality_degraded","trend_mismatch","chop_mismatch"], k=random.randint(0,2)) for a in ASSETS}

    out = run_profit_push(
        multi_asset_summary=multi_asset_summary,
        per_trade_logs_by_asset=per_trade_logs_by_asset,
        governance_audit=governance_audit,
        accelerator_overrides=accelerator_overrides,
        registry=registry,
        anomalies_by_asset=anomalies_by_asset
    )

    print(json.dumps({
        "overrides_written": out["audit"]["overrides_path"],
        "assets_with_intensity": len(out["audit"]["intensity_map"]),
        "example_intensity": list(out["audit"]["intensity_map"].items())[:3],
        "pruned_counts": {a: len(ps) for a, ps in out["audit"]["pruned"].items()}
    }, indent=2))
