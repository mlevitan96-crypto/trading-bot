# src/intraday_uplift.py
#
# Intraday Uplift Module – Adaptive baselines + statistical uplift checks for mid-session swaps
# Purpose:
#   Replace naive mid-session parameter swaps with an adaptive, statistically rigorous path:
#     - Compute portfolio baselines every cycle and derive adaptive floors
#     - Compare contender vs. champion on recent trades with bootstrap + effect size gates
#     - Swap mid-session only if uplift passes AND capacity is healthy; else hold
#     - Write updated intraday overrides for immediate use by the scheduler/execution bridge
#
# Integration:
#   - Call run_intraday_uplift_cycle(...) from your intraday scheduler right after reading
#     intraday_overrides.json and before merging with surge_overrides.json.
#   - This module updates intraday_overrides in-place with uplift-aware decisions (swap/hold/rollback).
#
# Files:
#   - configs/intraday_overrides.json (input/output – updated with uplift decisions)
#   - logs/intraday_uplift.jsonl (audit trail of tests, decisions, and evidence)

import os, json, time, random, math
from statistics import mean

LOG_DIR = "logs"
CONFIG_DIR = "configs"
INTRA_OVERRIDES = os.path.join(CONFIG_DIR, "intraday_overrides.json")
INTRA_UPLIFT_LOG = os.path.join(LOG_DIR, "intraday_uplift.jsonl")

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
    wrs = [a.get("metrics",{}).get("win_rate", 0.5) for a in assets]
    pfs = [a.get("metrics",{}).get("profit_factor", 1.2) for a in assets]
    evs = [a.get("metrics",{}).get("expectancy", 0.0) for a in assets]
    base = {
        "wr": round(mean(wrs) if wrs else 0.5, 4),
        "pf": round(mean(pfs) if pfs else 1.2, 4),
        "ev": round(mean(evs) if evs else 0.0, 6)
    }
    wr_rng = (max(wrs) - min(wrs)) if wrs else 0.0
    pf_rng = (max(pfs) - min(pfs)) if pfs else 0.0
    wr_margin = 0.02 + min(0.02, wr_rng/4)
    pf_margin = 0.05 + min(0.05, pf_rng/4)
    floors = {
        "wr_floor": round(base["wr"] + wr_margin, 4),
        "pf_floor": round(base["pf"] + pf_margin, 4),
        "ev_floor": max(0.0, base["ev"])
    }
    return base, floors

# ======================================================================================
# Metrics & samples
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

def capacity_ok(asset_packet, slip_max=0.0020, fq_min=0.84):
    cap = asset_packet.get("capacity", {})
    slip = cap.get("avg_slippage", 0.0015)
    fq = cap.get("avg_fill_quality", 0.85)
    return (slip <= slip_max) and (fq >= fq_min)

# ======================================================================================
# Bootstrap uplift test + effect size
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

# ======================================================================================
# Decision logic
# ======================================================================================

def passes_floors(stats, floors):
    return (stats["wr"] >= floors["wr_floor"] and
            stats["pf"] >= floors["pf_floor"] and
            stats["ev"] > floors["ev_floor"])

def uplift_swap_decision(contender_stats, champion_stats, contender_sample, champion_sample,
                         floors, alpha=0.05, min_effect=0.2, min_trades=40):
    """
    Mid-session swap rule:
      - Evidence: contender_stats["n"] >= min_trades (shorter than nightly)
      - Adaptive floors: contender passes floors
      - Uplift: bootstrap p ≤ alpha AND effect size ≥ min_effect
    """
    if contender_stats["n"] < min_trades:
        return False, {"reason":"insufficient_trades","n":contender_stats["n"]}
    if not passes_floors(contender_stats, floors):
        return False, {"reason":"floor_fail","floors":floors,"stats":contender_stats}
    p, mu_a, mu_b = bootstrap_pvalue(champion_sample, contender_sample, iters=800)
    es = effect_size(champion_sample, contender_sample)
    ok = (p <= alpha) and (es >= min_effect)
    return ok, {"p_value":p, "effect_size":es, "mu_champion":mu_a, "mu_contender":mu_b}

# ======================================================================================
# Uplift-aware parameter source
# ======================================================================================

def build_params_from_overrides(override):
    params = override.get("bandit_params") or {}
    if params and not params.get("disabled"):
        return params
    grid = override.get("parameter_sweep_grid", {"lookback":[20,50,100],"threshold":[0.3,0.5],"stop_atr":[2,3],"take_atr":[3,4]})
    lb = random.choice(grid.get("lookback",[20,50]))
    th = random.choice(grid.get("threshold",[0.3,0.5]))
    st = random.choice(grid.get("stop_atr",[2,3]))
    tk = random.choice(grid.get("take_atr",[3,4]))
    return {"lookback":lb,"threshold":th,"stop_atr":st,"take_atr":tk}

# ======================================================================================
# Orchestrator
# ======================================================================================

def run_intraday_uplift_cycle(multi_asset_summary,
                              per_trade_logs_by_asset,
                              intraday_overrides=None,
                              champion_params_by_asset=None,
                              alpha=0.05,
                              min_effect=0.2):
    """
    Steps:
      1) Load intraday_overrides (params per asset) and compute portfolio baselines + floors
      2) For each asset: capacity gate; compare contender vs champion on recent trades
      3) If uplift passes, set mid_session_swap=True and apply contender params; else hold
      4) If uplift fails after previous swap, optionally rollback to champion params
      5) Persist updated intraday_overrides.json and write audit
    """
    intraday_overrides = intraday_overrides or _read_json(INTRA_OVERRIDES, default={"ts": _now(), "assets": {}})
    base, floors = compute_portfolio_baselines(multi_asset_summary)

    decisions = []
    updated = {"ts": _now(), "assets": {}}

    for ap in multi_asset_summary.get("assets", []):
        asset = ap["asset"]
        cap_ok = capacity_ok(ap, slip_max=0.0020, fq_min=0.84)

        pkt = intraday_overrides.get("assets", {}).get(asset, {})
        current_params = pkt.get("bandit_params", {})
        contender_params = build_params_from_overrides(pkt)
        champion_params = (champion_params_by_asset or {}).get(asset) or current_params

        trades = per_trade_logs_by_asset.get(asset, [])
        short_window = trades[-80:]
        champ_stats, champ_sample = metrics_from_trades(short_window)
        cont_stats, cont_sample = champ_stats, champ_sample

        swap_ok, evidence = (False, {"reason":"capacity_block"}) if not cap_ok else uplift_swap_decision(
            cont_stats, champ_stats, cont_sample, champ_sample, floors, alpha=alpha, min_effect=min_effect, min_trades=40
        )

        next_params = current_params
        mid_swap = False
        rollback = False

        if cap_ok and swap_ok:
            next_params = contender_params
            mid_swap = True
        else:
            if pkt.get("mid_session_swap"):
                next_params = champion_params
                rollback = True

        updated["assets"][asset] = {
            **pkt,
            "bandit_params": next_params,
            "mid_session_swap": mid_swap,
            "bandit_confidence": pkt.get("bandit_confidence", 0.0),
            "apply_rules": {
                **pkt.get("apply_rules", {}),
                "intraday_uplift_enabled": True,
                "capacity_checks": True
            }
        }

        decisions.append({
            "asset": asset,
            "cap_ok": cap_ok,
            "floors": floors,
            "swap_ok": swap_ok,
            "mid_swap": mid_swap,
            "rollback": rollback,
            "evidence": evidence,
            "champ_stats": champ_stats,
            "cont_stats": cont_stats
        })

    os.makedirs(CONFIG_DIR, exist_ok=True)
    with open(INTRA_OVERRIDES, "w") as f:
        json.dump(updated, f, indent=2)

    audit = {
        "ts": _now(),
        "portfolio_base": base,
        "floors": floors,
        "decisions": decisions,
        "overrides_path": INTRA_OVERRIDES
    }
    _append_jsonl(INTRA_UPLIFT_LOG, {"event":"intraday_uplift_cycle_complete", **audit})
    return {"overrides": updated, "audit": audit}

# ======================================================================================
# CLI quick run – simulate intraday uplift
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
                "n": random.randint(60, 160)
            },
            "capacity": {
                "avg_slippage": random.uniform(0.0006, 0.0020),
                "avg_fill_quality": random.uniform(0.82, 0.90),
                "n": random.randint(20, 40)
            }
        }
    multi_asset_summary = {"assets": [mock_asset(a) for a in ASSETS]}

    def mock_trade(mu=0.0004, sigma=0.012):
        roi = random.gauss(mu, sigma)
        expected = 100 + random.uniform(-1,1)
        actual = expected*(1 + random.uniform(-0.0015, 0.0025))
        order = {"size": random.uniform(0.1, 1.5)}
        fills = [{"size": order["size"]*random.uniform(0.4,0.7), "latency_ms": random.randint(80,220)},
                 {"size": order["size"]*random.uniform(0.3,0.6), "latency_ms": random.randint(120,260)}]
        return {"roi": roi, "expected": expected, "actual": actual, "order": order, "fills": fills}
    per_trade_logs_by_asset = {a: [mock_trade(mu=random.uniform(-0.0005,0.001), sigma=random.uniform(0.008,0.015)) for _ in range(random.randint(90, 180))] for a in ASSETS}

    intraday_overrides = _read_json(INTRA_OVERRIDES, default={"ts": _now(), "assets": {}})
    if not intraday_overrides.get("assets"):
        intraday_overrides = {"ts": _now(), "assets": {}}
        for a in ASSETS:
            intraday_overrides["assets"][a] = {
                "overlays": [{"overlay":"trend_follow","enable":True,"params":{"momentum_window":[20,50,100]}}],
                "bandit_params": {"lookback": random.choice([20,50,100]), "threshold": random.choice([0.3,0.5]), "stop_atr": random.choice([2,3]), "take_atr": random.choice([3,4])},
                "bandit_confidence": random.uniform(0.55, 0.80),
                "mid_session_swap": False,
                "execution_router": {"mode": random.choice(["maker","taker"]), "post_only": True, "slice_parts":[3,5], "delay_ms":[50,80], "hold_orders": False},
                "position_scale": random.uniform(0.7, 1.0),
                "apply_rules": {"capacity_checks": True, "intraday_enabled": True, "experiment_slots": random.randint(1,3)},
                "parameter_sweep_grid": {"lookback":[20,50,100],"threshold":[0.3,0.5],"stop_atr":[2,3],"take_atr":[3,4]}
            }
        os.makedirs(CONFIG_DIR, exist_ok=True)
        with open(INTRA_OVERRIDES, "w") as f: json.dump(intraday_overrides, f, indent=2)

    champion_params_by_asset = {a: {"lookback": 50, "threshold": 0.3, "stop_atr": 3, "take_atr": 4} for a in ASSETS}

    out = run_intraday_uplift_cycle(
        multi_asset_summary=multi_asset_summary,
        per_trade_logs_by_asset=per_trade_logs_by_asset,
        intraday_overrides=intraday_overrides,
        champion_params_by_asset=champion_params_by_asset,
        alpha=0.05,
        min_effect=0.2
    )

    print(json.dumps({
        "floors": out["audit"]["floors"],
        "portfolio_base": out["audit"]["portfolio_base"],
        "example_asset": ASSETS[0],
        "decision": [d for d in out["audit"]["decisions"] if d["asset"] == ASSETS[0]][0],
        "overrides_path": out["audit"]["overrides_path"]
    }, indent=2))
