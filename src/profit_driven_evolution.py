# src/profit_driven_evolution.py
#
# v7.2 Profit-Driven Evolution: Attribution-Weighted Calibration & Tuning
# Purpose:
# - Fuse profit attribution directly into auto-calibration and strategy auto-tuning.
# - Gates and parameters are adjusted based on their measured dollar contribution (sum_net, avg_net),
#   not just profit trend — pushing aggressively yet safely toward more profit.
#
# What it does:
# 1) Computes profit attribution per gate (from counterfactuals) and ingests latest digest context.
# 2) Applies attribution-weighted adjustments to:
#      - Runtime governance: size_throttle, protective_mode, exposure_buffer_mult, fee_tolerance_usd
#      - Strategy thresholds: Alpha OFI/Ensemble/MTF curve; EMA ROI/cooldown/confirm_mode
# 3) Writes changes to live_config.json and configs/signal_policies.json
# 4) Emits rich telemetry for full visibility and auditable evolution.
#
# Integration:
# - Run after build_unified_digest() in the nightly scheduler.

import os, json, time, statistics
from collections import defaultdict
from src.full_integration_blofin_micro_live_and_paper import _bus

LEARN_LOG   = "logs/learning_updates.jsonl"
DIGEST_JSON = "logs/nightly_digest.json"
LIVE_CFG    = "live_config.json"
POLICIES_CF = "configs/signal_policies.json"

def _now(): return int(time.time())

def _read_json(path):
    if not os.path.exists(path): return {}
    try: return json.load(open(path))
    except Exception: return {}

def _write_json(path, obj):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path,"w") as f: json.dump(obj, f, indent=2)

def _read_jsonl(path, limit=200000):
    rows=[]
    if not os.path.exists(path): return rows
    with open(path,"r") as f:
        for line in f:
            line=line.strip()
            if not line: continue
            try: rows.append(json.loads(line))
            except: continue
    return rows[-limit:]

# --- Attribution ingestion ---

def _gate_profit_attribution(rows, window=200000):
    packets={}
    for r in rows[-window:]:
        did=r.get("decision_id")
        if not did: continue
        p=packets.get(did,{})
        if r.get("update_type")=="gate_verdicts":
            p["reasons"]=(r.get("gates") or {}).get("reason_codes",[])
        if r.get("update_type")=="counterfactual":
            p["cf"]=r.get("counterfactual",{})
        packets[did]=p

    gate_profit=defaultdict(list)
    for did,p in packets.items():
        cf=p.get("cf",{}) or {}
        if cf.get("status")!="evaluated": continue
        net=cf.get("net_usd",0.0)
        for rc in (p.get("reasons") or ["unknown"]):
            gate_profit[rc].append(net)

    summary={rc:{
        "count":len(vals),
        "avg_net":statistics.mean(vals) if vals else 0.0,
        "sum_net":sum(vals)
    } for rc,vals in gate_profit.items()}
    return summary

def _profit_trend(rows, days_back=7):
    summaries=[r for r in rows if r.get("update_type")=="counterfactual_summary"][-days_back:]
    if not summaries: return {"trend":"flat","avg_delta":0.0,"nights":0}
    deltas=[s.get("delta_sum_net",0.0) for s in summaries]
    avg_delta=statistics.mean(deltas)
    trend="up" if avg_delta>0 else ("down" if avg_delta<0 else "flat")
    return {"trend":trend,"avg_delta":avg_delta,"nights":len(summaries)}

# --- Helper math ---

def _bounded(v, lo, hi): return max(lo, min(hi, v))

def _influence(sum_net, count, alpha=1.0):
    if count<=0: return 0.0
    s = sum_net
    n = count
    magnitude = abs(s) / (10.0 + abs(s))
    strength  = min(1.0, (n**0.5)/10.0)
    return _bounded((1 if s>0 else -1) * magnitude * strength * alpha, -1.0, 1.0)

# --- Governance (runtime) adjustments driven by attribution ---

def _adjust_runtime_by_attribution(rt, gate_attr, trend):
    rt.setdefault("size_throttle", 0.25)
    rt.setdefault("protective_mode", True)
    rt.setdefault("exposure_buffer_mult", 1.10)
    rt.setdefault("fee_tolerance_usd", 0.00)

    fee_inf   = _influence((gate_attr.get("fee_gate_block") or {}).get("sum_net",0.0),
                           (gate_attr.get("fee_gate_block") or {}).get("count",0))
    exp_inf   = _influence((gate_attr.get("exposure_gate_block") or {}).get("sum_net",0.0),
                           (gate_attr.get("exposure_gate_block") or {}).get("count",0))
    prot_inf  = _influence((gate_attr.get("protective_mode_active") or {}).get("sum_net",0.0),
                           (gate_attr.get("protective_mode_active") or {}).get("count",0))
    throttle_inf = _influence((gate_attr.get("size_throttle_zero") or {}).get("sum_net",0.0),
                              (gate_attr.get("size_throttle_zero") or {}).get("count",0))

    step = 0.05
    dir  = 1 if trend["trend"]=="up" and trend["avg_delta"]>5.0 else (-1 if trend["trend"]=="down" and trend["avg_delta"]<-5.0 else 0)
    dir += 1 if throttle_inf>0 else (-1 if throttle_inf<0 else 0)
    rt["size_throttle"] = _bounded(rt["size_throttle"] + step*dir, 0.10, 0.60)

    if prot_inf < -0.10 and trend["trend"]=="up": rt["protective_mode"] = False
    if prot_inf >  0.10 and trend["trend"]=="down": rt["protective_mode"] = True

    tol_step = 0.02
    if fee_inf > 0.05:
        rt["fee_tolerance_usd"] = _bounded(rt["fee_tolerance_usd"] + tol_step, -0.50, 0.00)
    elif fee_inf < -0.05:
        rt["fee_tolerance_usd"] = _bounded(rt["fee_tolerance_usd"] - tol_step, -0.50, 0.00)

    buf_step = 0.01
    if exp_inf > 0.05:
        rt["exposure_buffer_mult"] = _bounded(rt["exposure_buffer_mult"] - buf_step, 1.05, 1.15)
    elif exp_inf < -0.05:
        rt["exposure_buffer_mult"] = _bounded(rt["exposure_buffer_mult"] + buf_step, 1.05, 1.15)

    return rt

# --- Strategy parameter adjustments driven by attribution ---

def _adjust_alpha_by_attribution(alpha, gate_attr, trend, alpha_outcomes):
    alpha.setdefault("enabled", True)
    alpha.setdefault("ofi_threshold", 0.50)
    alpha.setdefault("ensemble_threshold", 0.05)
    alpha.setdefault("mtf_curve", {"min":0.25,"max":0.50})

    exec_avg = alpha_outcomes.get("exec_avg",0.0)
    blocked_avg = alpha_outcomes.get("blocked_avg",0.0)
    too_strict = blocked_avg > exec_avg

    fee_inf = _influence((gate_attr.get("fee_gate_block") or {}).get("sum_net",0.0),
                         (gate_attr.get("fee_gate_block") or {}).get("count",0))
    exp_inf = _influence((gate_attr.get("exposure_gate_block") or {}).get("sum_net",0.0),
                         (gate_attr.get("exposure_gate_block") or {}).get("count",0))
    passed_inf = _influence((gate_attr.get("passed_all") or {}).get("sum_net",0.0),
                            (gate_attr.get("passed_all") or {}).get("count",0))

    ofi_step, ens_step = 0.02, 0.01
    if too_strict and passed_inf > 0.05:
        alpha["ofi_threshold"] = _bounded(alpha["ofi_threshold"] - ofi_step, 0.40, 0.80)
        alpha["ensemble_threshold"] = _bounded(alpha["ensemble_threshold"] - ens_step, 0.00, 0.20)
    elif (fee_inf > 0.05 or exp_inf > 0.05) and passed_inf < -0.05:
        alpha["ofi_threshold"] = _bounded(alpha["ofi_threshold"] + ofi_step, 0.40, 0.80)
        alpha["ensemble_threshold"] = _bounded(alpha["ensemble_threshold"] + ens_step, 0.00, 0.20)

    mtf = alpha["mtf_curve"]
    mtf_min_step, mtf_max_step = 0.01, 0.02
    if trend["trend"]=="up" and trend["avg_delta"]>5.0:
        mtf["min"] = _bounded(mtf["min"] - mtf_min_step, 0.20, 0.35)
        mtf["max"] = _bounded(mtf["max"] + mtf_max_step, 0.40, 0.60)
    elif trend["trend"]=="down" and trend["avg_delta"]<-5.0:
        mtf["min"] = _bounded(mtf["min"] + mtf_min_step, 0.20, 0.35)
        mtf["max"] = _bounded(mtf["max"] - mtf_max_step, 0.40, 0.60)

    alpha["mtf_curve"] = {"min":round(mtf["min"],3), "max":round(mtf["max"],3)}
    return alpha

def _adjust_ema_by_attribution(ema, gate_attr, trend, ema_outcomes):
    ema.setdefault("min_roi_threshold", 0.003)
    ema.setdefault("cooldown_minutes", 5)
    ema.setdefault("confirm_mode", "partial_ok")

    exec_avg = ema_outcomes.get("exec_avg",0.0)
    blocked_avg = ema_outcomes.get("blocked_avg",0.0)
    saving_blocks = blocked_avg < 0.0

    fee_inf = _influence((gate_attr.get("fee_gate_block") or {}).get("sum_net",0.0),
                         (gate_attr.get("fee_gate_block") or {}).get("count",0))
    passed_inf = _influence((gate_attr.get("passed_all") or {}).get("sum_net",0.0),
                            (gate_attr.get("passed_all") or {}).get("count",0))

    roi_step = 0.0005
    cd_step  = 1

    if saving_blocks or fee_inf > 0.05:
        ema["min_roi_threshold"] = _bounded(ema["min_roi_threshold"] + roi_step, 0.001, 0.010)
    elif passed_inf > 0.05 and trend["trend"]=="up":
        ema["min_roi_threshold"] = _bounded(ema["min_roi_threshold"] - roi_step, 0.001, 0.010)

    if trend["trend"]=="down":
        ema["cooldown_minutes"] = int(_bounded(ema["cooldown_minutes"] + cd_step, 2, 15))
        ema["confirm_mode"] = "strict"
    elif trend["trend"]=="up":
        ema["cooldown_minutes"] = int(_bounded(ema["cooldown_minutes"] - cd_step, 2, 15))
        ema["confirm_mode"] = "partial_ok"

    return ema

# --- Extract strategy outcomes from decision packets ---

def _strategy_outcomes(rows, window=100000):
    packets=[r for r in rows[-window:] if r.get("update_type") in ("decision_finalized","decision_started","counterfactual")]
    by_id=defaultdict(dict)
    for r in packets:
        did=r.get("decision_id"); 
        if not did: continue
        rec=by_id[did]; rec.update(r); by_id[did]=rec

    def outcomes_for(prefix):
        exec_net=[(p.get("outcome") or {}).get("expected_net_usd",0.0) for p in by_id.values()
                  if (p.get("strategy_id","")+p.get("strategy","")).lower().startswith(prefix)
                  and (p.get("outcome") or {}).get("status")=="executed"]
        blocked_net=[(p.get("counterfactual") or {}).get("net_usd",0.0) for p in by_id.values()
                  if (p.get("strategy_id","")+p.get("strategy","")).lower().startswith(prefix)
                  and (p.get("counterfactual") or {}).get("was_blocked")]
        return {
            "exec_avg": (statistics.mean(exec_net) if exec_net else 0.0),
            "blocked_avg": (statistics.mean(blocked_net) if blocked_net else 0.0)
        }

    return outcomes_for("alpha"), outcomes_for("ema")

# --- Main runner ---

def run_profit_driven_evolution():
    rows=_read_jsonl(LEARN_LOG,200000)
    gate_attr=_gate_profit_attribution(rows)
    trend=_profit_trend(rows)
    alpha_outcomes, ema_outcomes = _strategy_outcomes(rows)

    cfg=_read_json(LIVE_CFG)
    rt=cfg.get("runtime",{}) or {}
    policies=_read_json(POLICIES_CF)
    alpha=policies.setdefault("alpha_trading",{})
    ema=policies.setdefault("ema_futures",{})

    before_runtime = json.loads(json.dumps(rt))
    before_alpha   = json.loads(json.dumps(alpha))
    before_ema     = json.loads(json.dumps(ema))

    rt   = _adjust_runtime_by_attribution(rt, gate_attr, trend)
    alpha= _adjust_alpha_by_attribution(alpha, gate_attr, trend, alpha_outcomes)
    ema  = _adjust_ema_by_attribution(ema, gate_attr, trend, ema_outcomes)

    cfg["runtime"]=rt
    policies["alpha_trading"]=alpha
    policies["ema_futures"]=ema
    _write_json(LIVE_CFG, cfg)
    _write_json(POLICIES_CF, policies)

    report={
        "ts": _now(),
        "trend": trend,
        "gate_profit_attribution": gate_attr,
        "before": {
            "runtime": before_runtime,
            "alpha": before_alpha,
            "ema": before_ema
        },
        "after": {
            "runtime": rt,
            "alpha": alpha,
            "ema": ema
        },
        "alpha_outcomes": {k: round(v,4) for k,v in alpha_outcomes.items()},
        "ema_outcomes": {k: round(v,4) for k,v in ema_outcomes.items()}
    }
    _bus("profit_driven_evolution_applied", report)
    print("✅ Profit-Driven Evolution applied | "
          f"size_throttle {before_runtime.get('size_throttle')}→{rt.get('size_throttle')} "
          f"protective_mode {before_runtime.get('protective_mode')}→{rt.get('protective_mode')} | "
          f"Alpha OFI {before_alpha.get('ofi_threshold')}→{alpha.get('ofi_threshold')} "
          f"Ensemble {before_alpha.get('ensemble_threshold')}→{alpha.get('ensemble_threshold')} "
          f"MTF {before_alpha.get('mtf_curve')}→{alpha.get('mtf_curve')} | "
          f"EMA ROI {before_ema.get('min_roi_threshold')}→{ema.get('min_roi_threshold')} "
          f"CD {before_ema.get('cooldown_minutes')}→{ema.get('cooldown_minutes')} mode {before_ema.get('confirm_mode')}→{ema.get('confirm_mode')}")
    return report
