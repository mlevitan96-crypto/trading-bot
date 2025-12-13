# === Scenario Replay Auto-Tuner (src/scenario_replay_auto_tuner.py) ===
# Purpose:
# - Automatically fine-tune thresholds and allocations using historical logs.
# - Run offline scenario batches (grid search), score by PnL + WR, and apply the winner.
# - Feed results directly into live_config.runtime for immediate use in the next cycle.
# - No human-facing output required; logs and runtime overlays only.

import os, json, time, statistics, random
from collections import defaultdict

# CRITICAL: Use enriched_decisions.jsonl for full signal context + outcomes
# This file is created by data_enrichment_layer.py and contains:
# - signal_ctx: {ofi, ensemble, roi, regime, side}
# - outcome: {pnl_usd, pnl_pct, fees, etc}
# This enables proper scenario replay with actual decision context
EXEC_LOG   = "logs/enriched_decisions.jsonl"    # enriched decisions (signals + outcomes)
BLOCK_LOG  = "logs/enriched_blocked_signals.jsonl"       # optional: blocked signals with ctx
LIVE_CFG   = "live_config.json"                 # runtime config to update
TUNE_LOG   = "logs/scenario_auto_tuner.jsonl"   # audit of each tuning run

# Strict winner gates
MIN_WR = 0.40
MIN_PNL = 0.0

def _now(): return int(time.time())
def _append_jsonl(path, row):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "a") as f: f.write(json.dumps(row) + "\n")
def _read_json(path):
    if not os.path.exists(path): return {}
    try: return json.load(open(path))
    except: return {}
def _write_json(path, obj):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w") as f: json.dump(obj, f, indent=2)
def _read_jsonl(path, limit=800000):
    rows=[]
    if not os.path.exists(path): return rows
    with open(path,"r") as f:
        for line in f:
            line=line.strip()
            if not line: continue
            try: rows.append(json.loads(line))
            except: continue
    return rows[-limit:]

def _wr(pnls):
    wins=sum(1 for x in pnls if x>0)
    total=len(pnls) or 1
    return wins/total

def _score(pnls, target_wr=0.40):
    wr=_wr(pnls)
    pnl=sum(pnls)
    # Profit-first: WR matters to ensure robustness, but PnL is the primary driver
    # Score blends both with mild penalty for unstable outcomes
    stdev = statistics.pstdev(pnls) if pnls else 0.0
    return {
        "wr": wr,
        "pnl": pnl,
        "stability_penalty": stdev,
        "score": pnl + (wr - target_wr) * 100.0 - stdev * 0.5
    }

def _extract_ctx(record):
    # Normalize context fields across strategies
    ctx = record.get("signal_ctx", {}) or {}
    return {
        "ofi": float(ctx.get("ofi", 0.0) or 0.0),
        "ensemble": float(ctx.get("ensemble", 0.0) or 0.0),
        "roi": float(ctx.get("roi", 0.0) or 0.0),
        "vol": float(ctx.get("volatility", 0.0) or 0.0),
    }

# --- Scenario generator: build parameter grid based on current runtime and mild exploration ---
def _build_grid(cfg):
    policies = _read_json("configs/signal_policies.json")
    alpha = policies.get("alpha_trading", {}) or {}
    ema = policies.get("ema_futures", {}) or {}

    # Current baselines
    base_alpha_ofi = float(alpha.get("ofi_threshold", 0.50))
    base_alpha_ens = float(alpha.get("ensemble_threshold", 0.05))
    base_ema_roi   = float(ema.get("min_roi_threshold", 0.003))

    # Grid around baselines with mild exploration
    alpha_ofi_grid = [round(base_alpha_ofi + d,3) for d in (-0.06,-0.04,-0.02,0.0,0.02,0.04,0.06)]
    alpha_ens_grid = [round(base_alpha_ens + d,3) for d in (-0.02,-0.01,0.0,0.01,0.02)]
    ema_roi_grid   = [round(base_ema_roi + d,6) for d in (-0.0015,-0.001, -0.0005, 0.0, 0.0005, 0.001, 0.0015)]

    # Allocation weights exploration (profit-first governor synergy)
    rt = cfg.get("runtime", {}) or {}
    alloc = rt.get("strategy_allocations", {}) or {}
    w_alpha = float(alloc.get("alpha_trading", {}).get("weight", 0.20))
    w_ema   = float(alloc.get("ema_futures", {}).get("weight", 0.20))
    w_grid  = [round(x,2) for x in (max(0.05,w_alpha-0.10), w_alpha, min(0.50,w_alpha+0.10))]
    e_grid  = [round(x,2) for x in (max(0.05,w_ema-0.10), w_ema, min(0.50,w_ema+0.10))]

    scenarios=[]
    for ofi in alpha_ofi_grid:
        for ens in alpha_ens_grid:
            for roi in ema_roi_grid:
                for wa in w_grid:
                    for we in e_grid:
                        scenarios.append({
                            "alpha_ofi": ofi,
                            "alpha_ens": ens,
                            "ema_roi": roi,
                            "w_alpha": wa,
                            "w_ema": we
                        })
    random.shuffle(scenarios)
    return scenarios[:250]  # cap batch size for speed; adjust as needed

# --- Replay using simple decision rules on historical records ---
def _replay(execs, scenario):
    pnls=[]
    for r in execs:
        strat=(r.get("strategy_id") or r.get("strategy") or "").lower()
        pnl=float(r.get("outcome",{}).get("pnl_usd", r.get("net_pnl",0.0)) or 0.0)
        ctx=_extract_ctx(r)

        take=False
        # Alpha rule: take only if ctx exceeds thresholds
        if "alpha" in strat:
            if abs(ctx["ofi"]) >= scenario["alpha_ofi"] and abs(ctx["ensemble"]) >= scenario["alpha_ens"]:
                take=True
        # EMA rule: take only if roi exceeds threshold
        if "ema" in strat:
            if abs(ctx["roi"]) >= scenario["ema_roi"]:
                take=True

        # Weighting influence: dampen or amplify pnl contribution to reflect allocation
        if "alpha" in strat:
            weight = scenario["w_alpha"]
        elif "ema" in strat:
            weight = scenario["w_ema"]
        else:
            weight = 0.15  # default mild weight for other strategies

        if take:
            pnls.append(pnl * max(0.05, min(1.5, weight)))
        else:
            # If scenario would have skipped this, count zero (no trade)
            pnls.append(0.0)
    return _score(pnls)

# --- Apply winner directly into runtime + policy files ---
def _apply_winner(cfg, winner):
    # Update policy thresholds
    policies = _read_json("configs/signal_policies.json")
    alpha = policies.get("alpha_trading", {}) or {}
    ema = policies.get("ema_futures", {}) or {}

    alpha["ofi_threshold"] = winner["alpha_ofi"]
    alpha["ensemble_threshold"] = winner["alpha_ens"]
    ema["min_roi_threshold"] = winner["ema_roi"]

    policies["alpha_trading"] = alpha
    policies["ema_futures"] = ema
    _write_json("configs/signal_policies.json", policies)

    # Update allocations in runtime
    rt = cfg.get("runtime", {}) or {}
    alloc = rt.get("strategy_allocations", {}) or {}
    a = alloc.get("alpha_trading", {}) or {}
    e = alloc.get("ema_futures", {}) or {}

    a["mode"]="live"; a["weight"]=winner["w_alpha"]
    e["mode"]="paper" if winner["w_ema"]<0.10 else "live"
    e["weight"]=winner["w_ema"]

    alloc["alpha_trading"]=a
    alloc["ema_futures"]=e
    rt["strategy_allocations"]=alloc

    # Bias global throttle based on winner score
    rt["size_throttle"]=min(1.00, max(0.25, float(rt.get("size_throttle",0.35)) + (winner["score"]>0)*0.05))
    rt["protective_mode"]=False if winner["wr"]>=0.40 and winner["pnl"]>0 else True

    cfg["runtime"]=rt
    _write_json(LIVE_CFG, cfg)

def run_scenario_auto_tuner(window_days=14, target_wr=0.40):
    # Load history
    cutoff=_now()-window_days*86400
    execs=_read_jsonl(EXEC_LOG, 800000)
    execs=[r for r in execs if int(r.get("ts", _now()))>=cutoff]

    if not execs:
        _append_jsonl(TUNE_LOG, {"ts": _now(), "update_type":"no_data", "window_days":window_days})
        return

    cfg=_read_json(LIVE_CFG)
    scenarios=_build_grid(cfg)

    best=None
    for s in scenarios:
        res=_replay(execs, s)
        payload={"ts":_now(),"scenario":s,"res":res}
        _append_jsonl(TUNE_LOG, payload)
        if (best is None) or (res["score"]>best["res"]["score"]):
            best={"scenario":s,"res":res}

    # === Strict winner gate ===
    if best:
        res = best["res"]
        if res["wr"] >= MIN_WR and res["pnl"] > MIN_PNL:
            _apply_winner(cfg, {**best["scenario"], **res})
            _append_jsonl(TUNE_LOG, {
                "ts": _now(),
                "update_type": "winner_applied",
                "winner": best
            })
            print(f"♻️ Auto-Tuner applied | WR={res['wr']*100:.1f}% PnL={res['pnl']:.2f}")
        else:
            _append_jsonl(TUNE_LOG, {
                "ts": _now(),
                "update_type": "winner_rejected",
                "reason": "fails WR/PnL gate",
                "candidate": best
            })
            print(f"⛔ Auto-Tuner rejected | WR={res['wr']*100:.1f}% PnL={res['pnl']:.2f}")

# --- Scheduler integration ---
# Run daily BEFORE learning digest and adaptive overlays:
#   from src.scenario_replay_auto_tuner import run_scenario_auto_tuner
#   run_scenario_auto_tuner(window_days=14, target_wr=0.40)
# Then:
#   run_baseline_calibration(...)
#   run_adaptive_learning_rate(...)
#   run_profit_first_governor(...)
#   run_gate_complexity_monitor(...)
