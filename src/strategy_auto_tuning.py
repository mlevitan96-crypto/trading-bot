# src/strategy_auto_tuning.py
#
# v7.2 Strategy Auto-Tuning: Alpha & EMA Parameters
# Purpose:
# - Automatically tune per-strategy parameters (OFI threshold, Ensemble threshold, EMA ROI, cooldown, MTF sizing curve)
#   based on nightly evidence: counterfactual summaries, realized WR/net, and gate attribution.
# - Push toward higher profit with guardrails to prevent thrashing or hidden risk.
#
# Integration:
# - Call run_strategy_auto_tuning() after run_counterfactual_cycle() in the nightly scheduler (07:00 UTC).
# - Ensures configs/signal_policies.json and live_config.json are updated with bounded adjustments and telemetry.

import os, json, time, statistics
from collections import defaultdict
from src.full_integration_blofin_micro_live_and_paper import _bus

LEARN_LOG   = "logs/learning_updates.jsonl"
EXEC_LOG    = "logs/executed_trades.jsonl"
POLICIES_CF = "configs/signal_policies.json"
LIVE_CFG    = "live_config.json"

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

# --- Evidence aggregation ---

def _latest_counterfactual_summaries(rows, days_back=7):
    return [r for r in rows if r.get("update_type")=="counterfactual_summary"][-days_back:]

def _extract_alpha_decisions(rows, window=50000):
    packets = [r for r in rows[-window:] if r.get("update_type") in ("decision_finalized","decision_started","sizing_lineage","gate_verdicts")]
    alpha, ema = [], []
    by_id = defaultdict(dict)
    for r in packets:
        did = r.get("decision_id"); 
        if not did: continue
        rec = by_id[did]
        rec.update(r)
        by_id[did] = rec
    for did, rec in by_id.items():
        strat = rec.get("strategy_id") or rec.get("strategy") or ""
        if "alpha" in strat.lower():
            alpha.append(rec)
        elif "ema" in strat.lower():
            ema.append(rec)
    return alpha, ema

def _wr_net_from_exec_log(symbol_filter=None, window=200000):
    rows=_read_jsonl(EXEC_LOG, window)
    pnl = []
    for r in rows:
        sym=r.get("symbol")
        if symbol_filter and sym not in symbol_filter: continue
        net = float(r.get("net_usd", r.get("pnl_usd", 0.0)) or 0.0)
        pnl.append(net)
    wr = (sum(1 for x in pnl if x>0) / (len(pnl) or 1)) if pnl else 0.0
    avg_net = statistics.mean(pnl) if pnl else 0.0
    return wr, avg_net, len(pnl)

# --- Guarded adjustments ---

def _bounded(v, lo, hi): return max(lo, min(hi, v))

def _step(current, direction, step, lo, hi):
    if direction>0: return _bounded(current + step, lo, hi)
    if direction<0: return _bounded(current - step, lo, hi)
    return current

def _profit_signal(trend_avg_delta, min_abs=5.0):
    if trend_avg_delta > min_abs: return 1
    if trend_avg_delta < -min_abs: return -1
    return 0

# --- Parameter tuning logic ---

def _tune_alpha_params(policies, summaries, alpha_decisions):
    alpha = policies.setdefault("alpha_trading", {})
    alpha.setdefault("enabled", True)
    alpha.setdefault("ofi_threshold", 0.50)
    alpha.setdefault("ensemble_threshold", 0.05)
    alpha.setdefault("mtf_curve", {"min":0.25, "max":0.50})

    ofi_before = alpha["ofi_threshold"]
    ens_before = alpha["ensemble_threshold"]
    mtf_before = dict(alpha["mtf_curve"])

    trend_delta = statistics.mean([s.get("delta_sum_net",0.0) for s in summaries]) if summaries else 0.0
    signal_dir = _profit_signal(trend_delta, min_abs=7.5)

    executed = [p.get("outcome",{}).get("expected_net_usd",0.0) for p in alpha_decisions if (p.get("outcome") or {}).get("status")=="executed"]
    blocked  = [(p.get("counterfactual") or {}).get("net_usd",0.0) for p in alpha_decisions if (p.get("counterfactual") or {}).get("was_blocked")]
    exec_avg  = statistics.mean(executed) if executed else 0.0
    block_avg = statistics.mean(blocked) if blocked else 0.0

    relax_pressure = 1 if block_avg > exec_avg else -1 if exec_avg <= 0.0 else 0
    ofi_dir = signal_dir + relax_pressure
    ens_dir = signal_dir + relax_pressure

    ofi_step = 0.02
    ens_step = 0.01
    min_lo, min_hi = 0.40, 0.80
    ens_lo, ens_hi = 0.00, 0.20

    new_ofi = _step(ofi_before, ofi_dir, ofi_step, min_lo, min_hi)
    new_ens = _step(ens_before, ens_dir, ens_step, ens_lo, ens_hi)

    mtf = alpha["mtf_curve"]
    min_step, max_step = 0.01, 0.02
    mtf_min_lo, mtf_min_hi = 0.20, 0.35
    mtf_max_lo, mtf_max_hi = 0.40, 0.60
    mtf_dir = signal_dir
    new_mtf_min = _step(mtf["min"], mtf_dir, min_step, mtf_min_lo, mtf_min_hi)
    new_mtf_max = _step(mtf["max"], mtf_dir, max_step, mtf_max_lo, mtf_max_hi)

    alpha.update({"ofi_threshold": round(new_ofi,3),
                  "ensemble_threshold": round(new_ens,3),
                  "mtf_curve": {"min": round(new_mtf_min,3), "max": round(new_mtf_max,3)}})
    return policies, {
        "ofi_threshold_before": round(ofi_before,3),
        "ensemble_threshold_before": round(ens_before,3),
        "mtf_curve_before": mtf_before,
        "ofi_threshold_after": round(new_ofi,3),
        "ensemble_threshold_after": round(new_ens,3),
        "mtf_curve_after": {"min": round(new_mtf_min,3), "max": round(new_mtf_max,3)},
        "trend_delta": round(trend_delta,3),
        "exec_avg": round(exec_avg,3),
        "blocked_avg": round(block_avg,3)
    }

def _tune_ema_params(policies, summaries, ema_decisions):
    ema = policies.setdefault("ema_futures", {})
    ema.setdefault("min_roi_threshold", 0.003)
    ema.setdefault("cooldown_minutes", 5)
    ema.setdefault("confirm_mode", "partial_ok")

    roi_before = ema["min_roi_threshold"]
    cd_before = ema["cooldown_minutes"]
    mode_before = ema["confirm_mode"]

    trend_delta = statistics.mean([s.get("delta_sum_net",0.0) for s in summaries]) if summaries else 0.0
    signal_dir = _profit_signal(trend_delta, min_abs=7.5)

    exec_net = [p.get("outcome",{}).get("expected_net_usd",0.0) for p in ema_decisions if (p.get("outcome") or {}).get("status")=="executed"]
    blcf_net = [(p.get("counterfactual") or {}).get("net_usd",0.0) for p in ema_decisions if (p.get("counterfactual") or {}).get("was_blocked")]
    exec_avg = statistics.mean(exec_net) if exec_net else 0.0
    blocked_avg = statistics.mean(blcf_net) if blcf_net else 0.0

    roi_dir = -1 if signal_dir<0 or blocked_avg < 0.0 else (1 if signal_dir>0 and blocked_avg>exec_avg else 0)
    cd_dir  = -1 if signal_dir<0 else (0 if signal_dir==0 else 1)

    roi_step = 0.0005
    cd_step  = 1
    roi_lo, roi_hi = 0.001, 0.010
    cd_lo,  cd_hi  = 2, 15

    new_roi = _step(roi_before, roi_dir, roi_step, roi_lo, roi_hi)
    new_cd  = int(_step(cd_before, cd_dir, cd_step, cd_lo, cd_hi))

    new_mode = "strict" if signal_dir<0 else "partial_ok"

    ema.update({"min_roi_threshold": round(new_roi,4),
                "cooldown_minutes": new_cd,
                "confirm_mode": new_mode})
    return policies, {
        "min_roi_before": round(roi_before,4),
        "cooldown_before": cd_before,
        "mode_before": mode_before,
        "min_roi_after": round(new_roi,4),
        "cooldown_after": new_cd,
        "mode_after": new_mode,
        "trend_delta": round(trend_delta,3),
        "exec_avg": round(exec_avg,3),
        "blocked_avg": round(blocked_avg,3)
    }

# --- Main runner ---

def run_strategy_auto_tuning():
    learn_rows = _read_jsonl(LEARN_LOG, 200000)
    summaries = _latest_counterfactual_summaries(learn_rows, days_back=7)
    alpha_decisions, ema_decisions = _extract_alpha_decisions(learn_rows, window=100000)

    policies = _read_json(POLICIES_CF)
    live_cfg = _read_json(LIVE_CFG)

    policies_before_alpha = json.loads(json.dumps(policies))
    policies, alpha_report = _tune_alpha_params(policies, summaries, alpha_decisions)

    policies_before_ema = json.loads(json.dumps(policies))
    policies, ema_report = _tune_ema_params(policies, summaries, ema_decisions)

    _write_json(POLICIES_CF, policies)

    rt = live_cfg.get("runtime", {}) or {}
    rt["last_strategy_auto_tune_ts"] = _now()
    live_cfg["runtime"] = rt
    _write_json(LIVE_CFG, live_cfg)

    _bus("strategy_auto_tuning_applied", {
        "ts": _now(),
        "alpha_report": alpha_report,
        "ema_report": ema_report,
        "alpha_policy_before": policies_before_alpha.get("alpha_trading",{}),
        "ema_policy_before": policies_before_ema.get("ema_futures",{})
    })
    print("✅ Strategy Auto-Tuning applied | "
          f"Alpha: ofi {alpha_report['ofi_threshold_after']} ens {alpha_report['ensemble_threshold_after']} "
          f"mtf {alpha_report['mtf_curve_after']} | "
          f"EMA: roi {ema_report['min_roi_after']} cd {ema_report['cooldown_after']} mode {ema_report['mode_after']}")
    return alpha_report, ema_report
