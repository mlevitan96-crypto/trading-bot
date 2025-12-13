# src/relative_uplift_promoter.py
#
# Relative Uplift Promoter – Adaptive floors + statistical uplift promotion
# Purpose:
#   Promote strategies that beat current baselines with statistical confidence,
#   while enforcing adaptive safety floors derived from live portfolio health.
#
# What this adds:
#   - Adaptive floors: floors scale with portfolio baselines (WR/PF/EV)
#   - Relative uplift tests: bootstrap significance vs champion or baseline
#   - Effect size gates: require meaningful advantage, not just tiny gains
#   - Capacity-aware gating: no promotions if execution health is degraded
#   - Integration hooks: reads registry, writes promotion results and diffs
#
# Inputs:
#   - multi_asset_summary: {"assets":[{"asset":..,"metrics":{wr,pf,ev,...},"capacity":{...},...}]}
#   - strategy_registry: configs/strategy_registry.json (champion/contenders)
#   - per_trade_logs_by_asset: {symbol: [trade dicts with roi, signals, order/fills]}
#   - governance_audit: nightly governance packet (for capacity gates)
#
# Outputs:
#   - configs/strategy_registry.json (updated champions/history)
#   - logs/relative_uplift_promoter.jsonl (promotion audits and statistics)
#
# Promotion rule (best practice hybrid):
#   Promote contender C if:
#     1) C passes adaptive floors (WR_floor, PF_floor, EV_floor from portfolio baselines)
#     2) C shows statistically significant uplift over current champion or baseline
#        (bootstrap p-value ≤ alpha AND effect size ≥ min_effect)
#     3) Capacity gates OK (slippage/fill healthy for asset in last window)
#   Else: keep contender in pool and optionally downweight losing arms.
#
# Notes:
#   - Bootstrap approach is robust when distributions are non-normal (common in PnL).
#   - Effect size based on difference in means and pooled variability proxy.
#   - This module avoids hard-coded thresholds; floors adapt nightly.

import os, json, time, random, math
from statistics import mean

LOG_DIR = "logs"
CONFIG_DIR = "configs"
KG_LOG = os.path.join(LOG_DIR, "relative_uplift_promoter.jsonl")
REGISTRY_PATH = os.path.join(CONFIG_DIR, "strategy_registry.json")

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
    except: return default

# ======================================================================================
# Baselines and adaptive floors
# ======================================================================================

def compute_portfolio_baselines(multi_asset_summary):
    assets = multi_asset_summary.get("assets", [])
    wrs = [a["metrics"].get("win_rate", 0.5) for a in assets if "metrics" in a]
    pfs = [a["metrics"].get("profit_factor", 1.0) for a in assets if "metrics" in a]
    evs = [a["metrics"].get("expectancy", 0.0) for a in assets if "metrics" in a]
    base = {
        "wr": round(mean(wrs) if wrs else 0.5, 4),
        "pf": round(mean(pfs) if pfs else 1.0, 4),
        "ev": round(mean(evs) if evs else 0.0, 6)
    }
    return base

def adaptive_floors(portfolio_base, wr_margin=0.02, pf_margin=0.05, ev_floor=0.0):
    """
    Floors scale with portfolio baseline:
      - WR_floor = base_wr + wr_margin (e.g., +2%)
      - PF_floor = base_pf + pf_margin (e.g., +0.05)
      - EV_floor = max(ev_floor, 0.0) (must be > 0)
    """
    floors = {
        "wr_floor": round(portfolio_base["wr"] + wr_margin, 4),
        "pf_floor": round(portfolio_base["pf"] + pf_margin, 4),
        "ev_floor": max(ev_floor, 0.0)
    }
    return floors

# ======================================================================================
# Metrics per contender and champion from trades
# ======================================================================================

def metrics_from_trades(trades):
    if not trades:
        return {"wr": 0.0, "pf": 0.0, "ev": 0.0, "n": 0}
    rois = [t.get("roi", 0.0) for t in trades]
    wr = sum(1 for r in rois if r > 0) / max(1, len(rois))
    gains = sum(r for r in rois if r > 0)
    losses = abs(sum(r for r in rois if r < 0))
    pf = (gains / losses) if losses > 0 else float('inf')
    ev = mean(rois)
    return {"wr": round(wr,4), "pf": round(pf,4), "ev": round(ev,6), "n": len(rois)}

# ======================================================================================
# Bootstrap uplift test (non-parametric)
# ======================================================================================

def bootstrap_pvalue(sample_a, sample_b, iters=1000, seed=None):
    """
    Test if mean(sample_b) > mean(sample_a) with bootstrap.
    Returns p-value for uplift (one-sided).
    """
    if seed is not None: random.seed(seed)
    if not sample_a or not sample_b:
        return 1.0, 0.0, 0.0
    mu_a = mean(sample_a)
    mu_b = mean(sample_b)
    count_better = 0
    for _ in range(iters):
        a_hat = mean(random.choices(sample_a, k=len(sample_a)))
        b_hat = mean(random.choices(sample_b, k=len(sample_b)))
        if b_hat - a_hat > 0:
            count_better += 1
    p = 1.0 - (count_better / iters)
    return round(p, 6), mu_a, mu_b

def effect_size(sample_a, sample_b):
    """
    Simple effect size proxy: mean difference scaled by pooled absolute deviation.
    """
    if not sample_a or not sample_b:
        return 0.0
    mu_a = mean(sample_a)
    mu_b = mean(sample_b)
    ad_a = mean([abs(x - mu_a) for x in sample_a]) if sample_a else 0.0
    ad_b = mean([abs(x - mu_b) for x in sample_b]) if sample_b else 0.0
    pooled = max(1e-9, (ad_a + ad_b) / 2.0)
    es = (mu_b - mu_a) / pooled
    return round(es, 4)

# ======================================================================================
# Capacity gates (execution health)
# ======================================================================================

def capacity_ok(asset_packet, slip_max=0.0020, fq_min=0.84):
    cap = asset_packet.get("capacity", {})
    slip = cap.get("avg_slippage", 0.0015)
    fq = cap.get("avg_fill_quality", 0.85)
    return (slip <= slip_max) and (fq >= fq_min)

# ======================================================================================
# Promotion logic
# ======================================================================================

def contender_metrics(per_trade_logs_by_asset, asset, contender_id, window=120):
    """
    Filter trades attributed to contender if available; otherwise use asset window.
    For simplicity, this demo uses asset-level trades as proxy.
    """
    trades = per_trade_logs_by_asset.get(asset, [])[-window:]
    return metrics_from_trades(trades), [t.get("roi",0.0) for t in trades]

def champion_metrics(per_trade_logs_by_asset, asset, window=120):
    trades = per_trade_logs_by_asset.get(asset, [])[-window:]
    return metrics_from_trades(trades), [t.get("roi",0.0) for t in trades]

def passes_floors(metrics, floors):
    return (metrics["wr"] >= floors["wr_floor"] and
            metrics["pf"] >= floors["pf_floor"] and
            metrics["ev"] > floors["ev_floor"])

def should_promote(contender_stats, champion_stats, contender_sample, champion_sample,
                   floors, alpha=0.05, min_effect=0.2, min_trades=60):
    """
    Hybrid rule:
      - Enough evidence: contender_stats["n"] >= min_trades
      - Adaptive floors: contender passes floors
      - Uplift test: bootstrap p-value ≤ alpha AND effect size ≥ min_effect
    """
    if contender_stats["n"] < min_trades:
        return False, {"reason": "insufficient_trades", "n": contender_stats["n"]}
    if not passes_floors(contender_stats, floors):
        return False, {"reason": "floor_fail", "floors": floors, "stats": contender_stats}
    p, mu_a, mu_b = bootstrap_pvalue(champion_sample, contender_sample, iters=1000)
    es = effect_size(champion_sample, contender_sample)
    uplift_ok = (p <= alpha) and (es >= min_effect)
    return uplift_ok, {"p_value": p, "effect_size": es, "mu_champion": mu_a, "mu_contender": mu_b}

def apply_promotion(registry, asset, contender_node, evidence):
    registry["assets"][asset]["champion"] = contender_node
    registry["assets"][asset]["history"].append({
        "ts": _now(),
        "id": contender_node["id"],
        "outcome": "promoted_relative_uplift",
        "evidence": evidence,
        "stats": contender_node.get("stats", {})
    })
    return registry

# ======================================================================================
# Main orchestrator
# ======================================================================================

def run_relative_uplift_promoter(multi_asset_summary, per_trade_logs_by_asset, governance_audit=None, registry_path=REGISTRY_PATH):
    """
    Steps:
      1) Compute portfolio baselines and adaptive floors
      2) For each asset, evaluate contenders vs champion
      3) Check capacity gates; run bootstrap uplift + effect size
      4) Promote worthy contenders; log evidence
      5) Write back updated registry
    """
    portfolio_base = compute_portfolio_baselines(multi_asset_summary)
    floors = adaptive_floors(portfolio_base, wr_margin=0.02, pf_margin=0.05, ev_floor=0.0)
    registry = _read_json(registry_path, default={"ts": _now(), "assets": {a: {"champion": None, "contenders": [], "history": []} for a in ASSETS}})

    promotions = []
    evaluations = []

    for ap in multi_asset_summary.get("assets", []):
        asset = ap["asset"]
        if not capacity_ok(ap, slip_max=0.0020, fq_min=0.84):
            evaluations.append({"asset": asset, "status": "capacity_block", "floors": floors})
            continue

        champ = registry["assets"].get(asset, {}).get("champion")
        contenders = registry["assets"].get(asset, {}).get("contenders", [])
        def elo_proxy(node):
            s = node.get("stats", {"expectancy":0.0,"win_rate":0.0,"profit_factor":0.0,"n":0})
            return s["expectancy"]*100 + (s["win_rate"]-0.5)*50 + (s["profit_factor"]-1.0)*25 + math.log(max(1, s["n"]), 10)
        contenders_sorted = sorted(contenders, key=elo_proxy, reverse=True)[:3]

        champ_stats, champ_sample = champion_metrics(per_trade_logs_by_asset, asset, window=120)
        if champ is None or champ_stats["n"] == 0:
            champ_stats = {"wr": portfolio_base["wr"], "pf": portfolio_base["pf"], "ev": portfolio_base["ev"], "n": 0}
            champ_sample = [portfolio_base["ev"]] * 60

        for c in contenders_sorted:
            c_stats, c_sample = contender_metrics(per_trade_logs_by_asset, asset, c["id"], window=120)
            c["stats"] = c_stats
            ok, evidence = should_promote(c_stats, champ_stats, c_sample, champ_sample, floors, alpha=0.05, min_effect=0.2, min_trades=60)
            evaluations.append({"asset": asset, "contender": c["id"], "ok": ok, "evidence": evidence, "floors": floors, "c_stats": c_stats, "champ_stats": champ_stats})
            if ok:
                registry = apply_promotion(registry, asset, c, evidence)
                promotions.append({"asset": asset, "id": c["id"], "evidence": evidence, "stats": c_stats})
                registry["assets"][asset]["contenders"] = [c] + registry["assets"][asset]["contenders"][:2]
                break

    registry["ts"] = _now()
    os.makedirs(CONFIG_DIR, exist_ok=True)
    with open(registry_path, "w") as f:
        json.dump(registry, f, indent=2)

    audit = {
        "ts": _now(),
        "portfolio_base": portfolio_base,
        "floors": floors,
        "promotions": promotions,
        "evaluations": evaluations
    }
    _append_jsonl(KG_LOG, {"event":"relative_uplift_promoter_complete", **audit})
    return {"registry": registry, "audit": audit}

# ======================================================================================
# CLI quick run – simulate promoter on mock data
# ======================================================================================

if __name__ == "__main__":
    def mock_asset(a):
        return {
            "asset": a,
            "regime": random.choice(["trend","chop","uncertain"]),
            "metrics": {
                "expectancy": random.uniform(-0.0005, 0.0035),
                "win_rate": random.uniform(0.48, 0.62),
                "profit_factor": random.uniform(1.1, 1.8),
                "n": random.randint(50, 140)
            },
            "capacity": {
                "avg_slippage": random.uniform(0.0006, 0.0020),
                "avg_fill_quality": random.uniform(0.82, 0.90),
                "n": random.randint(20, 40)
            }
        }
    multi_asset_summary = {"assets": [mock_asset(a) for a in ASSETS]}

    def mock_trade(mu=0.0005, sigma=0.01):
        roi = random.gauss(mu, sigma)
        expected = 100 + random.uniform(-1,1)
        actual = expected*(1 + random.uniform(-0.0015, 0.0025))
        order = {"size": random.uniform(0.1, 1.5)}
        fills = [{"size": order["size"]*random.uniform(0.4,0.7), "latency_ms": random.randint(80,220)},
                 {"size": order["size"]*random.uniform(0.3,0.6), "latency_ms": random.randint(120,260)}]
        return {"roi": roi, "expected": expected, "actual": actual, "order": order, "fills": fills}
    per_trade_logs_by_asset = {a: [mock_trade(mu=random.uniform(-0.0005,0.001), sigma=random.uniform(0.008,0.015)) for _ in range(random.randint(90, 160))] for a in ASSETS}

    registry = {"ts": _now(), "assets": {}}
    for a in ASSETS:
        registry["assets"][a] = {"champion": None, "contenders": [], "history": []}
        for i in range(3):
            registry["assets"][a]["contenders"].append({
                "id": f"{a}_contender_{i}",
                "params": {"lookback": random.choice([20,40,80]), "stop_atr": random.choice([2,3,4]), "take_atr": random.choice([3,4,5])},
                "signals": ["Momentum","OFI","MeanReversion"],
                "regime_bias": random.choice(["trend","chop"]),
                "stats": {"expectancy": random.uniform(-0.0003, 0.002), "win_rate": random.uniform(0.50,0.66), "profit_factor": random.uniform(1.1, 1.9), "n": random.randint(40,140)}
            })
    os.makedirs(CONFIG_DIR, exist_ok=True)
    with open(REGISTRY_PATH, "w") as f: json.dump(registry, f, indent=2)

    out = run_relative_uplift_promoter(
        multi_asset_summary=multi_asset_summary,
        per_trade_logs_by_asset=per_trade_logs_by_asset,
        governance_audit=None,
        registry_path=REGISTRY_PATH
    )

    print(json.dumps({
        "floors": out["audit"]["floors"],
        "portfolio_base": out["audit"]["portfolio_base"],
        "promotions_count": len(out["audit"]["promotions"]),
        "example_eval": out["audit"]["evaluations"][:3]
    }, indent=2))
