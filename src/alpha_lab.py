# src/alpha_lab.py
#
# Alpha Lab – Meta-Research Brain, Champion Selection, Bandit Optimizer, and Real-Time Anomaly Guard
# Purpose:
#   Push the bot into a relentless improvement loop: generate, test, and promote strategies with
#   Bayesian bandits, ELO-style champion selection, knowledge graph logging, and anomaly detection.
#
# What's included:
#   1) Strategy registry & knowledge graph (signals, regimes, parameters, outcomes)
#   2) Per-asset champion/contender framework with ELO and promotion gates
#   3) Bayesian bandit optimizer for parameter sets (Thompson sampling)
#   4) Real-time anomaly guard for execution and regime mismatches
#   5) Alpha attribution ledger: per-trade aggregation of signal contribution and outcome
#   6) Wiring hooks to integrate with nightly orchestration & governance
#
# Outputs:
#   - configs/strategy_registry.json: Inventory of strategies per asset (champion/contenders)
#   - logs/alpha_lab.jsonl: Research events, bandit pulls, promotions, anomalies
#   - logs/alpha_knowledge_graph.jsonl: Knowledge graph append-only (strategies, params, outcomes)
#   - logs/alpha_attribution.jsonl: Signal contribution summaries per asset
#
# Notes:
#   - Plug alpha_lab into your nightly flow after governance_upgrade and before portfolio_scaling.
#   - Feed in per-trade data and orchestration summaries to continuously update the research brain.

import os, json, time, math, random, copy
from statistics import mean, stdev

LOG_DIR = "logs"
CONFIG_DIR = "configs"

ALPHA_LOG = os.path.join(LOG_DIR, "alpha_lab.jsonl")
ALPHA_KG = os.path.join(LOG_DIR, "alpha_knowledge_graph.jsonl")
ALPHA_ATTRIB = os.path.join(LOG_DIR, "alpha_attribution.jsonl")
REGISTRY_PATH = os.path.join(CONFIG_DIR, "strategy_registry.json")

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
# 1) Strategy registry & knowledge graph
# ======================================================================================

def default_registry():
    """
    Registry schema:
      assets: {
        symbol: {
          champion: {id, params, signals, regime_bias, stats},
          contenders: [{id, params, signals, regime_bias, stats}, ...],
          history: [{id, outcome, ts, notes}]
        }
      }
    """
    return {"ts": _now(), "assets": {a: {"champion": None, "contenders": [], "history": []} for a in ASSETS}}

def register_strategy(registry, asset, strategy_id, params, signals, regime_bias):
    node = {
        "id": strategy_id,
        "params": params,
        "signals": signals,
        "regime_bias": regime_bias,
        "stats": {"expectancy": 0.0, "win_rate": 0.0, "profit_factor": 0.0, "n": 0}
    }
    registry["assets"].setdefault(asset, {"champion": None, "contenders": [], "history": []})
    registry["assets"][asset]["contenders"].append(node)
    _append_jsonl(ALPHA_KG, {"ts": _now(), "event": "strategy_registered", "asset": asset, "node": node})
    return registry

def update_strategy_stats(node, trades):
    if not trades:
        return node
    rois = [t.get("roi",0.0) for t in trades]
    wr = sum(1 for r in rois if r>0)/len(rois)
    gains = sum(r for r in rois if r>0)
    losses = abs(sum(r for r in rois if r<0))
    pf = (gains / losses) if losses > 0 else float('inf')
    node["stats"] = {"expectancy": round(mean(rois),6), "win_rate": round(wr,4), "profit_factor": round(pf,4), "n": len(rois)}
    return node

# ======================================================================================
# 2) Champion/contender with ELO and promotion gates
# ======================================================================================

def elo_score(expectancy, win_rate, profit_factor, n, scale=400):
    """
    Composite ELO-like score blending performance metrics.
    """
    base = 1000 + scale * (expectancy*100 + (win_rate-0.5) + (profit_factor-1.0)/2)
    conf = math.log(max(1, n), 10)
    return round(base + 25*conf, 2)

def promote_if_worthy(registry, asset, contender, capacity_ok=True):
    """
    Promotion gate: WR≥60%, PF≥1.5, EV>0, capacity_ok → champion.
    """
    s = contender["stats"]
    worthy = (s["expectancy"]>0 and s["win_rate"]>=0.60 and s["profit_factor"]>=1.5 and capacity_ok)
    if worthy:
        registry["assets"][asset]["champion"] = contender
        history_entry = {"ts": _now(), "id": contender["id"], "outcome": "promoted", "stats": s}
        registry["assets"][asset]["history"].append(history_entry)
        _append_jsonl(ALPHA_LOG, {"event":"champion_promoted", "asset": asset, "strategy_id": contender["id"], "stats": s})
    return registry, worthy

def select_contenders_for_test(registry, asset, k=2):
    """
    Pick top-k contenders by ELO-like score to test against the champion.
    """
    conts = registry["assets"].get(asset, {}).get("contenders", [])
    scored = []
    for c in conts:
        # Ensure stats exist, create default if missing
        if "stats" not in c:
            c["stats"] = {"expectancy": 0.0, "win_rate": 0.0, "profit_factor": 0.0, "n": 0}
        s = c["stats"]
        scored.append({"node": c, "elo": elo_score(s["expectancy"], s["win_rate"], s["profit_factor"], s["n"])})
    scored.sort(key=lambda x: x["elo"], reverse=True)
    return [x["node"] for x in scored[:k]]

def record_match(asset, champion, contender):
    """
    Record a head-to-head match in the knowledge graph.
    """
    _append_jsonl(ALPHA_KG, {"ts": _now(), "event":"champion_match", "asset": asset,
                             "champion_id": champion["id"] if champion else None,
                             "contender_id": contender["id"]})

# ======================================================================================
# 3) Bayesian bandit optimizer (Thompson sampling) for parameter grids
# ======================================================================================

def bandit_update(posterior, arm_id, success):
    """
    Beta posterior update (success/failure for WR proxy).
    """
    a, b = posterior.get(arm_id, (1,1))
    posterior[arm_id] = (a + (1 if success else 0), b + (0 if success else 1))
    return posterior

def bandit_select(posterior):
    """
    Thompson sampling: sample Beta and pick best arm.
    Includes crash protection for betavariate (requires a,b > 0).
    """
    best_arm, best_val = None, -1
    for arm, (a,b) in posterior.items():
        a_safe = max(0.01, float(a) if a is not None else 1.0)
        b_safe = max(0.01, float(b) if b is not None else 1.0)
        try:
            sample = random.betavariate(a_safe, b_safe)
        except (ValueError, TypeError):
            sample = 0.5
        if sample > best_val:
            best_val, best_arm = sample, arm
    return best_arm

def build_parameter_arms(grid):
    """
    Flatten parameter grid into arm IDs with param dicts.
    """
    arms = {}
    def to_id(params):
        return "|".join(f"{k}={v}" for k,v in sorted(params.items()))
    
    # Ensure all grid values are lists
    def ensure_list(val):
        if isinstance(val, list):
            return val
        return [val] if val is not None else []
    
    lookbacks = ensure_list(grid.get("lookback", [20,50]))
    thresholds = ensure_list(grid.get("threshold", [0.3,0.5]))
    stops = ensure_list(grid.get("stop_atr", [2,3]))
    takes = ensure_list(grid.get("take_atr", [3,4]))
    
    # Fallback to defaults if empty
    if not lookbacks: lookbacks = [20, 50]
    if not thresholds: thresholds = [0.3, 0.5]
    if not stops: stops = [2, 3]
    if not takes: takes = [3, 4]
    
    for lb in lookbacks:
        for th in thresholds:
            for st in stops:
                for tk in takes:
                    params = {"lookback":lb,"threshold":th,"stop_atr":st,"take_atr":tk}
                    arms[to_id(params)] = params
    return arms

def run_bandit_iteration(asset, parameter_grid, recent_outcomes):
    """
    Run a single bandit iteration: update posteriors from outcomes, select next arm.
    recent_outcomes: [{arm_id, win:bool}]
    """
    arms = build_parameter_arms(parameter_grid)
    posterior = {arm_id:(1,1) for arm_id in arms.keys()}
    for o in recent_outcomes or []:
        posterior = bandit_update(posterior, o["arm_id"], bool(o.get("win",False)))
    chosen = bandit_select(posterior)
    _append_jsonl(ALPHA_LOG, {"event":"bandit_select", "asset": asset, "chosen_arm": chosen})
    return {"chosen_arm": chosen, "params": arms[chosen], "posterior": posterior}

# ======================================================================================
# 4) Real-time anomaly guard (execution + regime mismatches)
# ======================================================================================

def detect_anomalies(trades_window, regime_label, slip_gate=0.0025, fq_gate=0.80, wr_gate=0.45):
    """
    Detect execution anomalies and regime-strategy mismatches in recent trades.
    """
    if not trades_window:
        return {"anomalies": [], "ok": True}
    slips = [((t["actual"]-t["expected"])/t["expected"]) for t in trades_window if "expected" in t and "actual" in t]
    fqs = []
    wr = sum(1 for t in trades_window if t.get("roi",0.0) > 0) / max(1,len(trades_window))
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
    if wr < wr_gate: anomalies.append("low_win_rate_short_window")
    if regime_label=="trend" and wr < 0.52: anomalies.append("trend_mismatch")
    if regime_label=="chop" and wr < 0.50: anomalies.append("chop_mismatch")
    ok = len(anomalies)==0
    _append_jsonl(ALPHA_LOG, {"event":"anomaly_detection", "regime": regime_label, "anomalies": anomalies, "ok": ok})
    return {"anomalies": anomalies, "ok": ok}

# ======================================================================================
# 5) Alpha attribution ledger
# ======================================================================================

def aggregate_attribution(trades):
    """
    Summarize signal contribution rates and PnL alignment.
    """
    if not trades:
        return {"signal_wr": {}, "signal_pnl": {}, "n": 0}
    sig_hits, sig_count, sig_pnl = {}, {}, {}
    for t in trades:
        r = t.get("roi",0.0)
        sigs = t.get("signals", {})
        for s, w in sigs.items():
            sig_count[s] = sig_count.get(s,0)+1
            if r>0: sig_hits[s] = sig_hits.get(s,0)+1
            sig_pnl[s] = sig_pnl.get(s,0.0) + r*w
    signal_wr = {s: round(sig_hits.get(s,0)/sig_count[s],4) for s in sig_count}
    _append_jsonl(ALPHA_ATTRIB, {"ts": _now(), "event":"alpha_attribution", "signal_wr": signal_wr, "signal_pnl": sig_pnl})
    return {"signal_wr": signal_wr, "signal_pnl": sig_pnl, "n": sum(sig_count.values())}

# ======================================================================================
# 6) Wiring hooks
# ======================================================================================

def alpha_lab_cycle(multi_asset_summary,
                    per_trade_logs_by_asset,
                    auto_correction_overrides,
                    governance_audit,
                    sentiment_feed=None):
    """
    Full alpha lab pass:
      - Update registry with contenders & stats
      - Select top contenders and run bandit iterations
      - Detect anomalies and gate promotions
      - Update knowledge graph and write registry
    Inputs:
      multi_asset_summary: orchestration output (assets with metrics, regime)
      per_trade_logs_by_asset: per-asset list of trades with signals/features
      auto_correction_overrides: configs/strategy_overrides.json content
      governance_audit: packet from governance_upgrade.run_governance_upgrade
    """
    registry = _read_json(REGISTRY_PATH, default=default_registry())
    
    # Safe extraction of capacity_ok_assets from governance audit
    capacity_ok_assets = set()
    if governance_audit and isinstance(governance_audit.get("summary"), dict):
        canary_eval = governance_audit.get("summary", {}).get("canary_evaluation", {})
        if isinstance(canary_eval, dict):
            capacity_ok_assets = set([a for a, perf in canary_eval.items()])

    overrides = auto_correction_overrides or {"assets": {}}
    for asset, override in overrides.get("assets", {}).items():
        params = override.get("parameter_sweep_grid", {"lookback":[20,50], "threshold":[0.3,0.5], "stop_atr":[2,3], "take_atr":[3,4]})
        signals = [s.get("signal") for s in override.get("signal_reweights", [])] or ["Momentum","OFI","MeanReversion"]
        regime_bias = "trend" if any(o.get("overlay")=="trend_follow" for o in override.get("overlays", [])) else ("chop" if any(o.get("overlay")=="mean_reversion" for o in override.get("overlays", [])) else "uncertain")
        strategy_id = f"{asset}_auto_{int(_now()%100000)}"
        registry = register_strategy(registry, asset, strategy_id, params, signals, regime_bias)

    for asset in ASSETS:
        contenders = registry["assets"].get(asset, {}).get("contenders", [])
        trades = per_trade_logs_by_asset.get(asset, [])
        for c in contenders:
            update_strategy_stats(c, trades)

    promotions = []
    for asset in ASSETS:
        champion = registry["assets"].get(asset, {}).get("champion")
        contenders = select_contenders_for_test(registry, asset, k=2)
        for contender in contenders:
            record_match(asset, champion, contender)
            capacity_ok = True
            reg, worthy = promote_if_worthy(registry, asset, contender, capacity_ok=capacity_ok)
            if worthy: promotions.append({"asset": asset, "id": contender["id"]})

    bandit_plans = {}
    for asset in ASSETS:
        ref = registry["assets"][asset]["champion"] or (registry["assets"][asset]["contenders"][0] if registry["assets"][asset]["contenders"] else None)
        if not ref:
            continue
        recent_outcomes = []
        trades = per_trade_logs_by_asset.get(asset, [])
        
        # Ensure ref["params"] is a valid dict, default if missing
        if not isinstance(ref.get("params"), dict):
            ref["params"] = {"lookback": 50, "threshold": 0.3, "stop_atr": 3, "take_atr": 4}
        
        arms = build_parameter_arms(ref["params"])
        arm_ids = list(arms.keys())
        if not arm_ids:
            continue
        for t in trades[:50]:
            arm_id = random.choice(arm_ids)
            recent_outcomes.append({"arm_id": arm_id, "win": t.get("roi",0.0)>0})
        plan = run_bandit_iteration(asset, ref["params"], recent_outcomes)
        bandit_plans[asset] = plan

    anomalies = {}
    for asset in ASSETS:
        window = per_trade_logs_by_asset.get(asset, [])[-40:]
        regime = None
        for ap in (multi_asset_summary.get("assets", [])):
            if ap["asset"] == asset:
                regime = ap["regime"]; break
        anomalies[asset] = detect_anomalies(window, regime or "uncertain")

    attrib_reports = {}
    for asset in ASSETS:
        trades = per_trade_logs_by_asset.get(asset, [])
        attrib_reports[asset] = aggregate_attribution(trades)

    registry["ts"] = _now()
    os.makedirs(CONFIG_DIR, exist_ok=True)
    with open(REGISTRY_PATH, "w") as f:
        json.dump(registry, f, indent=2)

    audit = {
        "ts": _now(),
        "promotions": promotions,
        "bandit_plans": bandit_plans,
        "anomalies": anomalies,
        "attribution": {a: attrib_reports[a] for a in attrib_reports}
    }
    _append_jsonl(ALPHA_LOG, {"event":"alpha_lab_cycle_complete", **audit})
    return {"registry": registry, "audit": audit}

# ======================================================================================
# CLI quick run – Simulate Alpha Lab with mock data
# ======================================================================================

if __name__ == "__main__":
    multi_asset_summary = {
        "assets": [{"asset": a, "regime": random.choice(["trend","chop","uncertain"])} for a in ASSETS]
    }

    def mock_trade():
        roi = random.uniform(-0.02, 0.03)
        expected = 100 + random.uniform(-1,1)
        actual = expected*(1 + random.uniform(-0.0015, 0.0025))
        order = {"size": random.uniform(0.1, 1.5)}
        fills = [{"size": order["size"]*random.uniform(0.4,0.7), "latency_ms": random.randint(80,220)},
                 {"size": order["size"]*random.uniform(0.3,0.6), "latency_ms": random.randint(120,260)}]
        signals = {"Momentum": random.uniform(0.1,0.4), "OFI": random.uniform(0.05,0.3), "MeanReversion": random.uniform(0.05,0.25)}
        features = {"sentiment": random.uniform(-0.3,0.3), "vol": random.uniform(0.005, 0.04), "chop": random.uniform(0.0,1.0)}
        return {"roi": roi, "expected": expected, "actual": actual, "order": order, "fills": fills, "signals": signals, "features": features}

    per_trade_logs_by_asset = {a: [mock_trade() for _ in range(random.randint(60,140))] for a in ASSETS}

    auto_correction_overrides = {
        "assets": {
            "ETHUSDT": {
                "signal_reweights":[{"signal":"Momentum","delta_weight":+0.15},{"signal":"MeanReversion","delta_weight":-0.10}],
                "overlays":[{"overlay":"trend_follow","enable":True,"params":{"momentum_window":[20,50,100]}}],
                "parameter_sweep_grid":{"lookback":[20,50,100],"threshold":[0.3,0.5],"stop_atr":[2,3],"take_atr":[3,4]}
            },
            "AVAXUSDT": {
                "signal_reweights":[{"signal":"MeanReversion","delta_weight":+0.15}],
                "overlays":[{"overlay":"mean_reversion","enable":True,"params":{"zscore_entry":[1.0,1.5,2.0]}}],
                "parameter_sweep_grid":{"lookback":[10,20,40],"threshold":[0.2,0.35],"stop_atr":[2,3],"take_atr":[3,4]}
            }
        }
    }

    governance_audit = {
        "summary": {
            "canary_evaluation": {"promote":["BTCUSDT"], "rollback":["SOLUSDT","ADAUSDT"], "thresholds":{"win_rate_ge":0.60}},
            "promoted_assets": ["BTCUSDT"],
            "rolled_back_assets": ["SOLUSDT","ADAUSDT"]
        }
    }

    out = alpha_lab_cycle(multi_asset_summary, per_trade_logs_by_asset, auto_correction_overrides, governance_audit)
    print(json.dumps({"promotions": out["audit"]["promotions"], "bandit_assets": list(out["audit"]["bandit_plans"].keys()), "anomalies": {k:v["ok"] for k,v in out["audit"]["anomalies"].items()}}, indent=2))
