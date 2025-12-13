# src/horizon_weighted_evolution.py
#
# v7.2 Horizon-Weighted Evolution
# Purpose:
# - Fuse multi-horizon attribution (5m, 60m, 1d, 1w) into profit-driven evolution.
# - Adjust runtime governance and strategy parameters using weighted delta based on chosen mode:
#     profit_max (favor long-term compounding), balanced, risk_aware (favor short-term safety).
# - Provides horizon-aware telemetry so you know which timeframe drove each adjustment.
#
# Integration:
# - Run after run_multi_horizon_attribution() and before build_unified_digest().
# - Call run_horizon_weighted_evolution(mode="profit_max") nightly.

import os, json, time
from src.full_integration_blofin_micro_live_and_paper import _bus

LEARN_LOG   = "logs/learning_updates.jsonl"
LIVE_CFG    = "live_config.json"
POLICIES_CF = "configs/signal_policies.json"

def _now(): return int(time.time())

def _read_json(path):
    if not os.path.exists(path): return {}
    try: return json.load(open(path))
    except: return {}

def _write_json(path, obj):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path,"w") as f: json.dump(obj,f,indent=2)

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

def _latest_multi_summary(rows):
    for r in reversed(rows):
        if r.get("update_type")=="counterfactual_summary_multi":
            return r
    return {}

def get_horizon_weights(mode="balanced"):
    if mode=="profit_max":
        return {"5m":0.15,"60m":0.25,"1440m":0.30,"10080m":0.30}
    if mode=="risk_aware":
        return {"5m":0.35,"60m":0.35,"1440m":0.20,"10080m":0.10}
    return {"5m":0.25,"60m":0.25,"1440m":0.25,"10080m":0.25}

def _weighted_delta(summary_multi, weights):
    total=0.0; wsum=0.0
    for h, stats in (summary_multi.get("horizons") or {}).items():
        w=weights.get(h,0.0)
        total += w*float(stats.get("delta_sum_net",0.0) or 0.0)
        wsum += w
    return (total/wsum) if wsum>0 else 0.0

def run_horizon_weighted_evolution(mode="profit_max"):
    rows=_read_jsonl(LEARN_LOG,200000)
    summary_multi=_latest_multi_summary(rows)
    weights=get_horizon_weights(mode)
    weighted_delta=_weighted_delta(summary_multi, weights)

    cfg=_read_json(LIVE_CFG)
    rt=cfg.get("runtime",{}) or {}
    policies=_read_json(POLICIES_CF)
    alpha=policies.setdefault("alpha_trading",{})
    ema=policies.setdefault("ema_futures",{})

    before_runtime=json.loads(json.dumps(rt))
    before_alpha=json.loads(json.dumps(alpha))
    before_ema=json.loads(json.dumps(ema))

    step=0.05
    if weighted_delta>5.0:
        rt["size_throttle"]=min(rt.get("size_throttle",0.25)+step,0.60)
        rt["protective_mode"]=False
    elif weighted_delta<-5.0:
        rt["size_throttle"]=max(rt.get("size_throttle",0.25)-step,0.10)
        rt["protective_mode"]=True

    ofi_step, ens_step=0.02,0.01
    mtf=alpha.get("mtf_curve",{"min":0.25,"max":0.50})
    if weighted_delta>5.0:
        alpha["ofi_threshold"]=max(0.40,min(0.80,alpha.get("ofi_threshold",0.50)-ofi_step))
        alpha["ensemble_threshold"]=max(0.00,min(0.20,alpha.get("ensemble_threshold",0.05)-ens_step))
        mtf["min"]=max(0.20,min(0.35,mtf.get("min",0.25)-0.01))
        mtf["max"]=max(0.40,min(0.60,mtf.get("max",0.50)+0.02))
    elif weighted_delta<-5.0:
        alpha["ofi_threshold"]=max(0.40,min(0.80,alpha.get("ofi_threshold",0.50)+ofi_step))
        alpha["ensemble_threshold"]=max(0.00,min(0.20,alpha.get("ensemble_threshold",0.05)+ens_step))
        mtf["min"]=max(0.20,min(0.35,mtf.get("min",0.25)+0.01))
        mtf["max"]=max(0.40,min(0.60,mtf.get("max",0.50)-0.02))
    alpha["mtf_curve"]=mtf

    roi_step=0.0005; cd_step=1
    if weighted_delta>5.0:
        ema["min_roi_threshold"]=max(0.001,min(0.010,ema.get("min_roi_threshold",0.003)-roi_step))
        ema["cooldown_minutes"]=max(2,min(15,ema.get("cooldown_minutes",5)-cd_step))
        ema["confirm_mode"]="partial_ok"
    elif weighted_delta<-5.0:
        ema["min_roi_threshold"]=max(0.001,min(0.010,ema.get("min_roi_threshold",0.003)+roi_step))
        ema["cooldown_minutes"]=max(2,min(15,ema.get("cooldown_minutes",5)+cd_step))
        ema["confirm_mode"]="strict"

    cfg["runtime"]=rt
    policies["alpha_trading"]=alpha
    policies["ema_futures"]=ema
    _write_json(LIVE_CFG,cfg)
    _write_json(POLICIES_CF,policies)

    report={
        "ts":_now(),
        "mode":mode,
        "weights":weights,
        "weighted_delta":round(weighted_delta,4),
        "before":{"runtime":before_runtime,"alpha":before_alpha,"ema":before_ema},
        "after":{"runtime":rt,"alpha":alpha,"ema":ema}
    }
    _bus("horizon_weighted_evolution_applied",report)
    print(f"✅ Horizon-Weighted Evolution applied | mode={mode} weighted Δ={weighted_delta} | "
          f"size_throttle {before_runtime.get('size_throttle')}→{rt.get('size_throttle')} "
          f"protective_mode {before_runtime.get('protective_mode')}→{rt.get('protective_mode')} | "
          f"Alpha OFI {before_alpha.get('ofi_threshold')}→{alpha.get('ofi_threshold')} "
          f"Ensemble {before_alpha.get('ensemble_threshold')}→{alpha.get('ensemble_threshold')} "
          f"MTF {before_alpha.get('mtf_curve')}→{alpha.get('mtf_curve')} | "
          f"EMA ROI {before_ema.get('min_roi_threshold')}→{ema.get('min_roi_threshold')} "
          f"CD {before_ema.get('cooldown_minutes')}→{ema.get('cooldown_minutes')} "
          f"mode {before_ema.get('confirm_mode')}→{ema.get('confirm_mode')}")
    return report
