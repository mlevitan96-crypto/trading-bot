# src/multi_agent_coordinator.py
#
# v7.2 Multi-Agent Coordinator
# Purpose:
# - Coordinate Alpha and EMA under horizon-aware governance for portfolio-level intelligence.
# - Dynamically allocate capital, arbitrate conflicting signals, and route sizing with guardrails.
# - Exploit horizon-weighted profitability while preventing thrash, overlap, and hidden risk.
#
# What it does:
# 1) Reads multi-horizon weighted signals + attribution to score Alpha/EMA per timeframe.
# 2) Computes dynamic capital weights per strategy (Alpha vs EMA) and per symbol class.
# 3) Arbitrates conflicts (same symbol/side) with regime-aware tie-breakers and cooldowns.
# 4) Emits sizing hints, allocation map, and route decisions for the orchestrator/execution bridge.
# 5) Logs full telemetry for auditability (who won, why, and expected profit contribution).
#
# Integration:
# - Run after horizon_weighted_evolution and before the day's trading window opens.

import os, json, time, statistics
from collections import defaultdict
from src.full_integration_blofin_micro_live_and_paper import _bus

LEARN_LOG   = "logs/learning_updates.jsonl"
DIGEST_JSON = "logs/nightly_digest.json"
LIVE_CFG    = "live_config.json"
POLICIES_CF = "configs/signal_policies.json"
EXEC_LOG    = "logs/executed_trades.jsonl"

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

# --- Profit signals & attribution ingestion ---

def _latest_multi_summary(rows):
    for r in reversed(rows):
        if r.get("update_type")=="counterfactual_summary_multi":
            return r
    return {}

def _weighted_delta(summary_multi, weights):
    total=0.0; wsum=0.0
    for h, stats in (summary_multi.get("horizons") or {}).items():
        w=weights.get(h,0.0)
        total += w*float(stats.get("delta_sum_net",0.0) or 0.0)
        wsum += w
    return (total/wsum) if wsum>0 else 0.0

def _latest_weighted_signal(rows):
    for r in reversed(rows):
        if r.get("update_type")=="multi_horizon_weighted_signal":
            return r
    return {"weighted_delta":0.0, "weights":{"5m":0.25,"60m":0.25,"1440m":0.25,"10080m":0.25}}

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
    for p in packets.values():
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

def _strategy_outcomes(rows, window=120000):
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
        wr = (sum(1 for x in exec_net if x>0) / (len(exec_net) or 1)) if exec_net else 0.0
        return {
            "exec_avg": statistics.mean(exec_net) if exec_net else 0.0,
            "blocked_avg": statistics.mean(blocked_net) if blocked_net else 0.0,
            "wr": wr,
            "n_exec": len(exec_net),
            "n_block": len(blocked_net)
        }
    return outcomes_for("alpha"), outcomes_for("ema")

# --- Allocation math ---

def _score_strategy(alpha_out, ema_out, weighted_delta, weights):
    long_bias = (weights.get("1440m",0)+weights.get("10080m",0)) - (weights.get("5m",0)+weights.get("60m",0))
    alpha_base = 0.5 - 0.1*long_bias
    ema_base   = 0.5 + 0.1*long_bias

    def nudger(out):
        pos = max(0.0, out.get("exec_avg",0.0))
        wr  = out.get("wr",0.0)
        neg_pressure = 1.0 if out.get("blocked_avg",0.0) > out.get("exec_avg",0.0) else 0.0
        return 0.15*wr + 0.10*(pos) - 0.10*neg_pressure

    alpha_nudge = nudger(alpha_out)
    ema_nudge   = nudger(ema_out)

    delta_nudge = 0.05 if weighted_delta>5.0 else (-0.05 if weighted_delta<-5.0 else 0.0)

    alpha_score = max(0.0, alpha_base + alpha_nudge + delta_nudge)
    ema_score   = max(0.0, ema_base   + ema_nudge   + delta_nudge)

    total = alpha_score + ema_score
    if total <= 0.0001:
        return 0.5, 0.5
    return alpha_score/total, ema_score/total

def _allocation_map(alpha_weight, ema_weight, max_exposure, exposure_buffer_mult):
    cap = max_exposure * exposure_buffer_mult
    return {
        "alpha": {"exposure_cap": round(cap*alpha_weight,4), "weight": round(alpha_weight,4)},
        "ema":   {"exposure_cap": round(cap*ema_weight,4),   "weight": round(ema_weight,4)},
        "total_cap": round(cap,4)
    }

# --- Conflict arbitration (same symbol/side) ---

def _arbitrate_conflicts(signals, alpha_weight, ema_weight):
    by_key=defaultdict(list)
    for s in signals:
        key=(s.get("symbol"), s.get("side","LONG").upper())
        by_key[key].append(s)

    allowed=[]
    cooled=[]
    for key, items in by_key.items():
        if len(items)==1:
            allowed.append(items[0])
            continue
        items.sort(key=lambda x: (
            - (alpha_weight if x.get("strategy")=="alpha" else ema_weight),
            - float(x.get("score",0.0)),
            - int(x.get("ts",0))
        ))
        winner=items[0]; allowed.append(winner)
        for loser in items[1:]:
            cooled.append({"symbol": loser["symbol"], "side": loser["side"], "strategy": loser["strategy"], "cooldown_s": 180})
    return allowed, cooled

# --- Sizing hints & route decisions ---

def _build_sizing_hints(allocation_map, rt):
    hints={}
    for strat, info in allocation_map.items():
        if strat == "total_cap": continue
        cap=info.get("exposure_cap",0.0); throttle=float(rt.get("size_throttle",0.25))
        per_trade = max(10.0, cap * 0.01)
        hints[strat] = {"default_final_notional_usd": round(per_trade * throttle, 2)}
    return hints

# --- Main coordinator runner ---

def run_multi_agent_coordinator():
    rows=_read_jsonl(LEARN_LOG,300000)
    digest=_read_json(DIGEST_JSON)
    cfg=_read_json(LIVE_CFG)
    rt=cfg.get("runtime",{}) or {}
    policies=_read_json(POLICIES_CF)

    multi_summary=_latest_multi_summary(rows)
    weighted_signal=_latest_weighted_signal(rows)
    weighted_delta=float(weighted_signal.get("weighted_delta",0.0) or 0.0)
    weights=weighted_signal.get("weights", {"5m":0.25,"60m":0.25,"1440m":0.25,"10080m":0.25})

    gate_attr=_gate_profit_attribution(rows)
    alpha_out, ema_out = _strategy_outcomes(rows)

    max_exposure=float(rt.get("max_exposure",0.60) or 0.60)
    exposure_buffer_mult=float(rt.get("exposure_buffer_mult",1.10) or 1.10)

    alpha_w, ema_w = _score_strategy(alpha_out, ema_out, weighted_delta, weights)
    alloc_map=_allocation_map(alpha_w, ema_w, max_exposure, exposure_buffer_mult)

    hints=_build_sizing_hints(alloc_map, rt)

    pending=[r for r in rows[-50000:] if r.get("update_type")=="decision_started"]
    scored=[]
    for p in pending:
        strat=p.get("strategy_id","")
        sc=p.get("signal_ctx",{}) or {}
        score = 0.0
        score += float(sc.get("ensemble",0.0) or 0.0)
        score += float(sc.get("ofi",0.0) or 0.0)*0.5
        score += 0.05 if (sc.get("regime","").lower()=="trend") else 0.0
        score -= (float(sc.get("latency_ms",0) or 0)/1000.0)*0.01
        scored.append({"symbol": p.get("symbol"), "side": p.get("side","LONG"), "strategy": "alpha" if "alpha" in strat.lower() else ("ema" if "ema" in strat.lower() else strat),
                       "score": round(score,4), "ts": p.get("ts", _now())})

    allowed, cooled = _arbitrate_conflicts(scored, alpha_w, ema_w)

    report={
        "ts": _now(),
        "weighted_delta": round(weighted_delta,4),
        "weights": weights,
        "multi_horizon_summary": multi_summary.get("horizons",{}),
        "gate_attr": {k: {"count": v.get("count",0), "sum_net": round(v.get("sum_net",0.0),4), "avg_net": round(v.get("avg_net",0.0),4)}
                      for k,v in gate_attr.items()},
        "alpha_outcomes": {k: round(v,4) if isinstance(v,(int,float)) else v for k,v in alpha_out.items()},
        "ema_outcomes": {k: round(v,4) if isinstance(v,(int,float)) else v for k,v in ema_out.items()},
        "allocation_map": alloc_map,
        "sizing_hints": hints,
        "arbitration_allowed": allowed,
        "arbitration_cooled": cooled
    }

    rt["coordinator"] = {
        "mode": "multi_agent",
        "alpha_weight": round(alpha_w,4),
        "ema_weight": round(ema_w,4),
        "allocation_map": alloc_map,
        "sizing_hints": hints,
        "cooldowns": cooled
    }
    cfg["runtime"]=rt
    _write_json(LIVE_CFG, cfg)

    _bus("multi_agent_coordinator_applied", report)
    alpha_hint = hints.get('alpha', {}).get('default_final_notional_usd', 0)
    ema_hint = hints.get('ema', {}).get('default_final_notional_usd', 0)
    print(f"✅ Multi-Agent Coordinator applied | "
          f"α={round(alpha_w,4)} EMA={round(ema_w,4)} total_cap={alloc_map['total_cap']} | "
          f"hints α=${alpha_hint} EMA=${ema_hint} | "
          f"allowed={len(allowed)} cooled={len(cooled)}")
    return report
