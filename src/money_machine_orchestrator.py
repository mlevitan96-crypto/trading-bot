from src.blocked_signal_logger import log_blocked
# === Learning-to-Execution Orchestrator (src/money_machine_orchestrator.py) ===
# Purpose:
# - Promote profitable patterns into live execution with sizing and exits
# - Enforce mode-aware behavior (paper vs live)
# - Govern capital allocation, risk, and health checks
# - Rollback degradations, alert on drift, and keep a tight profit loop

import os, json, time, statistics

LIVE_CFG = "live_config.json"
POLICIES = "configs/signal_policies.json"
PATTERN_SUMMARY = "feature_store/pattern_summary.json"
AUDIT_LOG = "logs/full_pipeline_audit.jsonl"
ORCH_LOG = "logs/orchestrator_money_machine.jsonl"

def _now(): return int(time.time())
def _append_jsonl(path,row):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path,"a") as f: f.write(json.dumps(row)+"\n")
def _read_json(path):
    if not os.path.exists(path): return {}
    try: return json.load(open(path))
    except: return {}
def _write_json(path,obj):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path,"w") as f: json.dump(obj,f,indent=2)

# ---------- Profit evidence aggregation ----------

def _aggregate_evidence():
    ps=_read_json(PATTERN_SUMMARY)
    patterns=ps.get("patterns",[])
    strict=[p for p in patterns if p.get("status")=="strict" and p.get("expected",{}).get("wr",0)>=0.40 and p.get("expected",{}).get("pnl",0)>0]
    candidates=[p for p in patterns if p.get("status")=="candidate" and p.get("expected",{}).get("wr",0)>=0.30]
    return strict, candidates

# ---------- Promotion: patterns -> runtime overlays ----------

def promote_patterns_to_runtime(strict, candidates, cfg):
    rt = cfg.get("runtime", {}) or {}
    overlays = rt.get("conditional_overlays", []) or []

    def _key(p):
        s=p["slice"]
        return (s["symbol"], s["direction"], s["session_bin"], s["regime"], s["vol_bin"], s["liq_bin"], s["trend_bin"], s["combo"])

    # Upsert strict overlays (live)
    for p in strict:
        th=p["thresholds"]; s=p["slice"]; exp=p["expected"]
        overlays=[o for o in overlays if not (_key({"slice":o})==_key(p))]
        overlays.append({
            **s, "thresholds": th, "expected": exp, "status": "live"
        })

    # Record candidate overlays (exploration mode uses them at smaller size)
    rt["candidate_overlays"] = [
        {"slice": p["slice"], "thresholds": p["thresholds"], "expected": p["expected"], "status":"candidate"}
        for p in candidates
    ]

    rt["conditional_overlays"] = overlays
    cfg["runtime"] = rt
    return cfg

# ---------- Profit-first sizing & exposure ----------

def compute_sizing(runtime, symbol, volatility, confidence=1.0):
    base = float(runtime.get("size_throttle", 0.35))
    vol_norm = max(0.15, min(1.0, 0.5 / (volatility/20.0 + 1e-9)))  # normalize by vol bands
    evidence_boost = min(1.25, 1.0 + 0.15 * max(0.0, confidence - 0.40) * 100.0)  # boost if WR > 40%
    dd_guard = 0.85 if runtime.get("protective_mode", True) else 1.0
    return round(base * vol_norm * evidence_boost * dd_guard, 3)

# ---------- Exit policies ----------

def apply_exit_policy(ctx, runtime):
    ep = runtime.get("exit_policy", {
        "time_stop_bars": 20,
        "tp_bands": [0.002, 0.004],
        "trail_mult_vol": 0.8
    })
    ctx["exit_policy"] = ep
    return ctx

# ---------- Mode-aware governance patch ----------

def mode_aware_update(cfg):
    rt = cfg.get("runtime", {}) or {}
    mode = (rt.get("trading_mode") or "paper").lower()

    rt.setdefault("size_throttle", 0.35)
    rt.setdefault("protective_mode", True)
    rt.setdefault("kill_switch_enabled", True)
    rt.setdefault("explore_budget", 0.20)
    rt.setdefault("direction_bias", {"long":1.0,"short":1.0})
    rt.setdefault("cooldown_secs", {"alpha": 120, "ema": 300})
    rt.setdefault("session_overlays", {
        0: {"ofi": 0.56, "ensemble": 0.07, "roi": 0.003, "cooldown_alpha": 90},
        1: {"ofi": 0.54, "ensemble": 0.06, "roi": 0.003, "cooldown_alpha": 120},
        2: {"ofi": 0.52, "ensemble": 0.06, "roi": 0.003, "cooldown_alpha": 75},
        3: {"ofi": 0.55, "ensemble": 0.07, "roi": 0.003, "cooldown_alpha": 120}
    })
    rt.setdefault("deployment_gates", {"strict_wr": 0.40, "strict_pnl": 0.0, "explore_wr": 0.30, "explore_pnl": -10.0})
    rt.setdefault("explore_perturb", {"ofi": 0.01, "ensemble": 0.005, "roi": 0.0004})

    if mode == "paper":
        rt["protective_mode"] = False
        rt["kill_switch_enabled"] = False
        rt["size_throttle"] = min(0.30, rt["size_throttle"])
        rt["explore_budget"] = 0.35
        rt["deployment_gates"] = {"strict_wr": 0.35, "strict_pnl": -5.0, "explore_wr": 0.25, "explore_pnl": -25.0}
        rt["direction_bias"] = {"long":1.0,"short":0.6}
        rt["cooldown_secs"]["alpha"] = 60
        rt["cooldown_secs"]["ema"] = 180
        rt["exit_policy"] = {"time_stop_bars": 20, "tp_bands":[0.002,0.004], "trail_mult_vol":0.8}
    else:
        rt["protective_mode"] = True
        rt["kill_switch_enabled"] = True
        rt["size_throttle"] = max(0.35, rt["size_throttle"])
        rt["explore_budget"] = 0.10
        rt["deployment_gates"] = {"strict_wr": 0.40, "strict_pnl": 0.0, "explore_wr": 0.30, "explore_pnl": -10.0}
        rt["direction_bias"] = {"long":1.0,"short":0.9}
        rt["cooldown_secs"]["alpha"] = 120
        rt["cooldown_secs"]["ema"] = 300
        rt["exit_policy"] = {"time_stop_bars": 30, "tp_bands":[0.003,0.006], "trail_mult_vol":0.6}

    cfg["runtime"] = rt
    return cfg

# ---------- Execution bridge hook (per trade) ----------

def apply_overlays_for_trade(symbol, direction, session_bin, vol, liq, ctx, runtime):
    # Direction bias
    ctx["direction_bias"] = runtime.get("direction_bias", {"long":1.0,"short":1.0}).get(direction,1.0)

    # Session thresholds
    sess = runtime.get("session_overlays", {}).get(session_bin, {})
    for k,v in sess.items():
        if k == "cooldown_alpha":
            runtime["cooldown_secs"]["alpha"] = v
        else:
            ctx[f"{k}_threshold"] = max(ctx.get(f"{k}_threshold", v), v)

    # Conditional overlays live
    vb = 0 if vol<=10 else (1 if vol<=20 else (2 if vol<=35 else 3))
    lb = 0 if liq<=1e5 else (1 if liq<=5e5 else 2)
    overlays = runtime.get("conditional_overlays", []) or []
    for o in overlays:
        if (o.get("symbol")==symbol and o.get("direction")==direction and
            o.get("session_bin")==session_bin and o.get("vol_bin")==vb and
            o.get("liq_bin")==lb and o.get("status")=="live"):
            th = o.get("thresholds",{})
            ctx["ofi_threshold"]=th.get("ofi", ctx.get("ofi_threshold",0.50))
            ctx["ensemble_threshold"]=th.get("ensemble", ctx.get("ensemble_threshold",0.05))
            ctx["roi_threshold"]=th.get("roi", ctx.get("roi_threshold",0.003))
            ctx["expected"]=o.get("expected",{})

    # Candidate overlays (explore route at reduced size)
    ctx["explore_budget"] = runtime.get("explore_budget", 0.20)
    ctx["explore_perturb"] = runtime.get("explore_perturb", {"ofi":0.01,"ensemble":0.005,"roi":0.0004})

    # Exit policy
    ctx = apply_exit_policy(ctx, runtime)

    # Sizing
    confidence = float(ctx.get("expected",{}).get("wr",0.0) or 0.0)
    ctx["size_multiplier"] = compute_sizing(runtime, symbol, vol, confidence)
    return ctx

# ---------- Watchdogs & Rollback ----------

def rollback_on_degradation(min_wr=0.35, min_pnl=-5.0, lookback_hours=6):
    # This uses enriched decisions; assume a separate reader for pnl stream
    # Here we just mark protective_mode if degradation detected (wire to real pnl feed)
    cfg=_read_json(LIVE_CFG); rt=cfg.get("runtime",{}) or {}
    # Placeholder: external metrics ingestion recommended
    wr=rt.get("last_wr", 0.0); pnl=rt.get("last_pnl", 0.0)
    if wr<min_wr or pnl<=min_pnl:
        rt["conditional_overlays"] = []
        rt["protective_mode"]=True
        rt["size_throttle"]=max(0.25, float(rt.get("size_throttle",0.35)) - 0.05)
        cfg["runtime"]=rt; _write_json(LIVE_CFG, cfg)
        _append_jsonl(ORCH_LOG, {"ts": _now(), "type":"rollback_applied", "wr": wr, "pnl": pnl})

def alert_on_drift():
    # Red flag if self-heal fixed modules or quarantined files
    last=[json.loads(l) for r in open(AUDIT_LOG) if (l:=r.strip())] if os.path.exists(AUDIT_LOG) else []
    fixed=sum(1 for r in last if r.get("type")=="MODULE_PATHS_FIXED")
    quars=sum(1 for r in last if "QUARANTINED" in str(r.get("type","")))
    if fixed>0 or quars>0:
        _append_jsonl(ORCH_LOG, {"ts": _now(), "type":"drift_alert", "fixed_modules": fixed, "quarantined": quars})

# ---------- Nightly orchestration ----------

def nightly_orchestrate():
    cfg=_read_json(LIVE_CFG)
    cfg=mode_aware_update(cfg)

    strict, candidates = _aggregate_evidence()
    cfg=promote_patterns_to_runtime(strict, candidates, cfg)
    _write_json(LIVE_CFG, cfg)

    alert_on_drift()
    _append_jsonl(ORCH_LOG, {
        "ts": _now(),
        "type":"nightly_summary",
        "strict_promoted": len(strict),
        "candidates_logged": len(candidates),
        "runtime": {
            "protective_mode": cfg["runtime"].get("protective_mode"),
            "kill_switch_enabled": cfg["runtime"].get("kill_switch_enabled"),
            "size_throttle": cfg["runtime"].get("size_throttle"),
            "overlays": len(cfg["runtime"].get("conditional_overlays",[]))
        }
    })
    print(f"[ORCH] promoted_strict={len(strict)} candidates={len(candidates)} protective={cfg['runtime'].get('protective_mode')}")

# NOTE: blocked signal logging enabled via src/blocked_signal_logger.py
