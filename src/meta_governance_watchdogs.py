# src/meta_governance_watchdogs.py
#
# v7.2 Meta-Governance Watchdogs
# Purpose:
# - Auto-relax/tighten gates and strategy thresholds using sustained pressure signals
#   (missed opportunities, blended deltas, gate/strategy pressures) with hysteresis and cooldown.
# - Prevent overreaction: apply bounded, rate-limited, auditable adjustments only when evidence persists.
#
# Integration:
# - Run nightly after missed_opportunity_probe and horizon_weighted_evolution, before digest build

import os, json, time
from collections import deque
from src.full_integration_blofin_micro_live_and_paper import _bus

LEARN_LOG   = "logs/learning_updates.jsonl"
LIVE_CFG    = "live_config.json"
POLICIES_CF = "configs/signal_policies.json"
STATE_JSON  = "logs/watchdog_state.json"

def _now(): return int(time.time())

def _read_json(path):
    if not os.path.exists(path): return {}
    try: return json.load(open(path))
    except: return {}

def _write_json(path, obj):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path,"w") as f: json.dump(obj, f, indent=2)

def _read_jsonl(path, limit=300000):
    rows=[]
    if not os.path.exists(path): return rows
    with open(path,"r") as f:
        for line in f:
            line=line.strip()
            if not line: continue
            try: rows.append(json.loads(line))
            except: continue
    return rows[-limit:]

# --- Evidence ingestion ---

def _latest_overlays(cfg):
    rt = cfg.get("runtime") or {}
    overlays = rt.get("research_overlays") or {}
    missed = float(overlays.get("missed_weighted_delta", 0.0) or 0.0)
    blended = float(overlays.get("blended_weighted_delta", 0.0) or 0.0)
    gate_pressures = overlays.get("gate_pressures", {}) or {}
    strat_pressures= overlays.get("strategy_pressures", {}) or {}
    return missed, blended, gate_pressures, strat_pressures

def _append_state(metric, value, window=7):
    st=_read_json(STATE_JSON)
    buf=deque(st.get(metric, []), maxlen=window)
    buf.append({"ts":_now(),"v":value})
    st[metric]=list(buf)
    _write_json(STATE_JSON, st)
    return list(buf)

def _evidence_persistent(seq, threshold, min_nights, mode="pos"):
    vals=[float(x.get("v",0.0) or 0.0) for x in seq][-min_nights:]
    if len(vals)<min_nights: return False
    if mode=="pos": return all(v>=threshold for v in vals)
    if mode=="neg": return all(v<=-threshold for v in vals)
    return False

def _cooldown_ok(key, min_seconds):
    st=_read_json(STATE_JSON)
    last=(st.get("last_change") or {}).get(key)
    if not last: return True
    return (_now() - int(last)) >= min_seconds

def _mark_change(key):
    st=_read_json(STATE_JSON)
    ch=st.get("last_change",{}) or {}
    ch[key]=_now()
    st["last_change"]=ch
    _write_json(STATE_JSON, st)

# --- Bounded adjustments & guardrails ---

def _bound(v, lo, hi): return max(lo, min(hi, v))

def _adjust_runtime(rt, reason_log, gate_pressures, missed, blended):
    rt.setdefault("size_throttle", 0.25)
    rt.setdefault("protective_mode", True)
    rt.setdefault("exposure_buffer_mult", 1.10)
    rt.setdefault("fee_tolerance_usd", 0.00)
    rt.setdefault("max_exposure", 0.60)

    min_nights=3
    cd_secs=6*60*60

    fee_p=float(gate_pressures.get("fee_gate",0.0) or 0.0)
    seq=_append_state("pressure_fee_gate", fee_p)
    if _cooldown_ok("fee_tolerance_usd", cd_secs):
        if _evidence_persistent(seq, 0.10, min_nights, "pos"):
            old=rt["fee_tolerance_usd"]
            rt["fee_tolerance_usd"]=_bound(old - 0.02, -0.50, 0.00)
            reason_log.append({"control":"fee_tolerance_usd","delta":-0.02,"why":"fee_gate positive pressure (missed profitable signals) — relax"})
            _mark_change("fee_tolerance_usd")
        elif _evidence_persistent(seq, 0.10, min_nights, "neg"):
            old=rt["fee_tolerance_usd"]
            rt["fee_tolerance_usd"]=_bound(old + 0.02, -0.50, 0.00)
            reason_log.append({"control":"fee_tolerance_usd","delta":+0.02,"why":"fee_gate negative pressure (saved losses) — tighten"})
            _mark_change("fee_tolerance_usd")

    exp_p=float(gate_pressures.get("exposure_cap",0.0) or 0.0)
    seq=_append_state("pressure_exposure_cap", exp_p)
    if _cooldown_ok("exposure_buffer_mult", cd_secs):
        if _evidence_persistent(seq, 0.06, min_nights, "pos"):
            old=rt["exposure_buffer_mult"]
            rt["exposure_buffer_mult"]=_bound(old + 0.01, 1.05, 1.20)
            reason_log.append({"control":"exposure_buffer_mult","delta":+0.01,"why":"exposure cap positive pressure — relax"})
            _mark_change("exposure_buffer_mult")
        elif _evidence_persistent(seq, 0.06, min_nights, "neg"):
            old=rt["exposure_buffer_mult"]
            rt["exposure_buffer_mult"]=_bound(old - 0.01, 1.05, 1.20)
            reason_log.append({"control":"exposure_buffer_mult","delta":-0.01,"why":"exposure cap negative pressure — tighten"})
            _mark_change("exposure_buffer_mult")

    seq=_append_state("blended_delta", blended)
    if _cooldown_ok("protective_mode", cd_secs):
        if _evidence_persistent(seq, 5.0, min_nights, "pos"):
            if rt["protective_mode"]:
                rt["protective_mode"]=False
                reason_log.append({"control":"protective_mode","delta":"OFF","why":"blended delta sustained positive — disengage protection"})
                _mark_change("protective_mode")
        elif _evidence_persistent(seq, 5.0, min_nights, "neg"):
            if not rt["protective_mode"]:
                rt["protective_mode"]=True
                reason_log.append({"control":"protective_mode","delta":"ON","why":"blended delta sustained negative — engage protection"})
                _mark_change("protective_mode")

    seq=_append_state("missed_delta", missed)
    if _cooldown_ok("size_throttle", cd_secs):
        if _evidence_persistent(seq, 3.0, min_nights, "pos"):
            old=rt["size_throttle"]
            rt["size_throttle"]=_bound(old + 0.02, 0.10, 0.60)
            reason_log.append({"control":"size_throttle","delta":+0.02,"why":"missed delta sustained positive — increase sizing to capture edge"})
            _mark_change("size_throttle")
        elif _evidence_persistent(seq, 3.0, min_nights, "neg"):
            old=rt["size_throttle"]
            rt["size_throttle"]=_bound(old - 0.02, 0.10, 0.60)
            reason_log.append({"control":"size_throttle","delta":-0.02,"why":"missed delta sustained negative — reduce sizing to cut losses"})
            _mark_change("size_throttle")

    return rt

def _adjust_alpha(alpha, reason_log, strat_pressures):
    alpha.setdefault("ofi_threshold", 0.50)
    alpha.setdefault("ensemble_threshold", 0.05)
    alpha.setdefault("mtf_curve", {"min":0.25,"max":0.50})

    min_nights=3
    cd_secs=6*60*60
    p=float(strat_pressures.get("alpha",0.0) or 0.0)
    seq=_append_state("pressure_alpha", p)

    if _cooldown_ok("alpha_thresholds", cd_secs):
        if _evidence_persistent(seq, 0.08, min_nights, "pos"):
            alpha["ofi_threshold"]=_bound(alpha["ofi_threshold"] - 0.02, 0.40, 0.80)
            alpha["ensemble_threshold"]=_bound(alpha["ensemble_threshold"] - 0.01, 0.00, 0.20)
            reason_log.append({"control":"alpha_thresholds","delta":{"ofi":-0.02,"ensemble":-0.01},"why":"alpha positive pressure — relax"})
            _mark_change("alpha_thresholds")
        elif _evidence_persistent(seq, 0.08, min_nights, "neg"):
            alpha["ofi_threshold"]=_bound(alpha["ofi_threshold"] + 0.02, 0.40, 0.80)
            alpha["ensemble_threshold"]=_bound(alpha["ensemble_threshold"] + 0.01, 0.00, 0.20)
            reason_log.append({"control":"alpha_thresholds","delta":{"ofi":+0.02,"ensemble":+0.01},"why":"alpha negative pressure — tighten"})
            _mark_change("alpha_thresholds")

    return alpha

def _adjust_ema(ema, reason_log, strat_pressures):
    ema.setdefault("min_roi_threshold", 0.003)
    ema.setdefault("cooldown_minutes", 5)
    ema.setdefault("confirm_mode", "partial_ok")

    min_nights=3
    cd_secs=6*60*60
    p=float(strat_pressures.get("ema",0.0) or 0.0)
    seq=_append_state("pressure_ema", p)

    if _cooldown_ok("ema_thresholds", cd_secs):
        if _evidence_persistent(seq, 0.08, min_nights, "pos"):
            ema["min_roi_threshold"]=_bound(ema["min_roi_threshold"] - 0.0005, 0.001, 0.010)
            ema["cooldown_minutes"]=int(_bound(ema["cooldown_minutes"] - 1, 2, 15))
            ema["confirm_mode"]="partial_ok"
            reason_log.append({"control":"ema_thresholds","delta":{"roi":-0.0005,"cd":-1,"mode":"partial_ok"},"why":"ema positive pressure — relax"})
            _mark_change("ema_thresholds")
        elif _evidence_persistent(seq, 0.08, min_nights, "neg"):
            ema["min_roi_threshold"]=_bound(ema["min_roi_threshold"] + 0.0005, 0.001, 0.010)
            ema["cooldown_minutes"]=int(_bound(ema["cooldown_minutes"] + 1, 2, 15))
            ema["confirm_mode"]="strict"
            reason_log.append({"control":"ema_thresholds","delta":{"roi":+0.0005,"cd":+1,"mode":"strict"},"why":"ema negative pressure — tighten"})
            _mark_change("ema_thresholds")

    return ema

# --- Main runner ---

def run_meta_governance_watchdogs():
    cfg=_read_json(LIVE_CFG)
    policies=_read_json(POLICIES_CF)

    missed, blended, gate_pressures, strat_pressures = _latest_overlays(cfg)

    rt = (cfg.get("runtime") or {})
    alpha = (policies.get("alpha_trading") or {})
    ema = (policies.get("ema_futures") or {})
    before_runtime = json.loads(json.dumps(rt))
    before_alpha = json.loads(json.dumps(alpha))
    before_ema = json.loads(json.dumps(ema))

    reason_log=[]

    rt = _adjust_runtime(rt, reason_log, gate_pressures, missed, blended)
    alpha = _adjust_alpha(alpha, reason_log, strat_pressures)
    ema = _adjust_ema(ema, reason_log, strat_pressures)

    cfg["runtime"]=rt
    policies["alpha_trading"]=alpha
    policies["ema_futures"]=ema
    _write_json(LIVE_CFG, cfg)
    _write_json(POLICIES_CF, policies)

    report={
        "ts": _now(),
        "evidence": {
            "missed_weighted_delta": missed,
            "blended_weighted_delta": blended,
            "gate_pressures": gate_pressures,
            "strategy_pressures": strat_pressures
        },
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
        "reasons": reason_log
    }
    _bus("meta_governance_watchdogs_applied", report)

    changes_str = " ".join([f"{r['control']}:{r['delta']}" for r in reason_log]) if reason_log else "none"
    print(f"✅ Meta-Governance Watchdogs applied | changes={len(reason_log)} | {changes_str}")
    return report
