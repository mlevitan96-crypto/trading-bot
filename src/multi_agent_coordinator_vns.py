# src/multi_agent_coordinator_vns.py
#
# v7.2 Multi-Agent Coordinator (Volatility-Normalized)
# Purpose:
# - Extend the coordinator to operate in volatility-normalized space (risk units), not raw notional.
# - Allocate capital per strategy and per symbol using ATR-based risk units.
# - Arbitrate conflicts with risk-aware scoring and enforce per-symbol risk caps and cooldowns.
#
# Integration:
# - Run after run_multi_agent_coordinator() nightly before trading opens.

import os, json, time, statistics
from collections import defaultdict
from src.full_integration_blofin_micro_live_and_paper import _bus

LEARN_LOG   = "logs/learning_updates.jsonl"
DIGEST_JSON = "logs/nightly_digest.json"
LIVE_CFG    = "live_config.json"
POLICIES_CF = "configs/signal_policies.json"
PRICE_LOG   = "logs/price_feed.jsonl"
VOL_LOG     = "logs/volatility_cache.json"

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

# --- Helpers: multi-horizon and outcomes ---

def _latest_weighted_signal(rows):
    for r in reversed(rows):
        if r.get("update_type")=="multi_horizon_weighted_signal":
            return r
    return {"weighted_delta":0.0, "weights":{"5m":0.25,"60m":0.25,"1440m":0.25,"10080m":0.25}}

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

# --- Volatility (ATR) utilities ---

def _compute_atr(symbol, window=50):
    prices=[p for p in _read_jsonl(PRICE_LOG,500000) if p.get("symbol")==symbol]
    closes=[float(p.get("close",0.0) or 0.0) for p in prices[-window:]]
    highs=[float(p.get("high",0.0) or 0.0) for p in prices[-window:]]
    lows =[float(p.get("low",0.0) or 0.0)  for p in prices[-window:]]
    if not closes or not highs or not lows: return None
    trs=[max(h-l, abs(h-c), abs(l-c)) for h,l,c in zip(highs,lows,closes)]
    return statistics.mean(trs) if trs else None

def _ensure_vol_cache(symbols):
    cache=_read_json(VOL_LOG)
    changed=False
    for sym in symbols:
        if sym not in cache or (cache.get(sym) or {}).get("atr") is None:
            atr=_compute_atr(sym)
            if atr:
                cache.setdefault(sym,{})["atr"]=atr
                changed=True
    if changed: _write_json(VOL_LOG,cache)
    return cache

# --- Strategy weighting based on outcomes and weighted delta ---

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

# --- Volatility-normalized allocation and sizing ---

def _risk_cap_map(alpha_weight, ema_weight, rt, symbols, vol_cache):
    max_exposure=float(rt.get("max_exposure",0.60) or 0.60)
    buf=float(rt.get("exposure_buffer_mult",1.10) or 1.10)
    total_cap_usd=max_exposure*buf
    prices=_read_jsonl(PRICE_LOG, 200000)
    latest_px: dict = {s: 0.0 for s in symbols}
    for p in reversed(prices):
        s=p.get("symbol")
        if s in latest_px and latest_px[s] == 0.0:
            latest_px[s]=float(p.get("mid", p.get("close", 0.0)) or 0.0)
    total_cap_ru = {}
    for s in symbols:
        atr=(vol_cache.get(s) or {}).get("atr") or 0.0
        px = latest_px.get(s) or 0.0
        total_cap_ru[s] = (total_cap_usd / (atr*px)) if atr>0 and px>0 else 0.0
    inv_atr_sum = sum((1.0/((vol_cache.get(s) or {}).get("atr") or 1e9)) for s in symbols)
    per_symbol_share = {s: ((1.0/((vol_cache.get(s) or {}).get("atr") or 1e9))/inv_atr_sum) for s in symbols}
    alpha_ru_cap_total = sum(total_cap_ru.values()) * alpha_weight
    ema_ru_cap_total   = sum(total_cap_ru.values()) * ema_weight
    alpha_caps = {s: round(alpha_ru_cap_total * per_symbol_share[s], 4) for s in symbols}
    ema_caps   = {s: round(ema_ru_cap_total   * per_symbol_share[s], 4) for s in symbols}
    return {
        "alpha": {"risk_cap_per_symbol": alpha_caps, "weight": round(alpha_weight,4)},
        "ema":   {"risk_cap_per_symbol": ema_caps,   "weight": round(ema_weight,4)},
        "total_cap_usd": round(total_cap_usd,4)
    }

def _build_vns_hints(rt, coord, symbols, vol_cache):
    throttle=float(rt.get("size_throttle",0.25))
    base_hints=(coord.get("sizing_hints") or {})
    vns=(coord.get("sizing_hints_volatility") or {})
    hints={}
    for strat in ("alpha","ema"):
        strat_units=(vns.get(strat) or {}).get("risk_units",{})
        per_trade={}
        for s in symbols:
            ru = float(strat_units.get(s, 0.0) or 0.0)
            per_trade[s] = round(max(0.001, ru) * throttle, 4)
        hints[strat] = {"per_trade_risk_units": per_trade, "base_notional": (base_hints.get(strat) or {}).get("default_final_notional_usd",0.0)}
    return hints

# --- Conflict arbitration in risk space ---

def _arbitrate_conflicts_vns(signals, alpha_weight, ema_weight, vns_hints):
    by_key=defaultdict(list)
    for s in signals:
        key=(s.get("symbol"), s.get("side","LONG").upper())
        by_key[key].append(s)
    allowed=[]
    cooled=[]
    for key, items in by_key.items():
        if len(items)==1:
            allowed.append(items[0]); continue
        def strat_weight(x): return alpha_weight if x.get("strategy")=="alpha" else ema_weight
        def per_trade_ru(x):
            strat=x.get("strategy"); sym=x.get("symbol")
            return float((vns_hints.get(strat) or {}).get("per_trade_risk_units",{}).get(sym,0.0) or 0.0)
        items.sort(key=lambda x: (
            - strat_weight(x),
            - float(x.get("score",0.0)),
            per_trade_ru(x),
            - int(x.get("ts",0))
        ))
        winner=items[0]; allowed.append(winner)
        for loser in items[1:]:
            cooled.append({"symbol": loser["symbol"], "side": loser["side"], "strategy": loser["strategy"], "cooldown_s": 240})
    return allowed, cooled

# --- Pending signals scoring ---

def _score_pending_signals(rows, window=50000):
    pending=[r for r in rows[-window:] if r.get("update_type")=="decision_started"]
    scored=[]
    for p in pending:
        strat=p.get("strategy_id","")
        sc=(p.get("signal_ctx") or {})
        score = 0.0
        score += float(sc.get("ensemble",0.0) or 0.0)
        score += float(sc.get("ofi",0.0) or 0.0)*0.5
        score += 0.06 if (sc.get("regime","").lower()=="trend") else (0.02 if sc.get("regime","").lower()=="range" else 0.0)
        score -= (float(sc.get("latency_ms",0) or 0)/1000.0)*0.01
        scored.append({
            "symbol": p.get("symbol"),
            "side": p.get("side","LONG"),
            "strategy": "alpha" if "alpha" in strat.lower() else ("ema" if "ema" in strat.lower() else strat),
            "score": round(score,4),
            "ts": p.get("ts", _now())
        })
    return scored

# --- Main runner ---

def run_multi_agent_coordinator_vns(symbols=("BTCUSDT","ETHUSDT","SOLUSDT","AVAXUSDT","DOTUSDT","TRXUSDT","XRPUSDT","ADAUSDT","DOGEUSDT","BNBUSDT","MATICUSDT")):
    rows=_read_jsonl(LEARN_LOG,300000)
    cfg=_read_json(LIVE_CFG)
    rt=cfg.get("runtime",{}) or {}
    coord=rt.get("coordinator",{}) or {}
    policies=_read_json(POLICIES_CF)

    vol_cache=_ensure_vol_cache(symbols)

    weighted_signal=_latest_weighted_signal(rows)
    weighted_delta=float(weighted_signal.get("weighted_delta",0.0) or 0.0)
    weights=weighted_signal.get("weights", {"5m":0.25,"60m":0.25,"1440m":0.25,"10080m":0.25})
    alpha_out, ema_out = _strategy_outcomes(rows)

    alpha_w, ema_w = _score_strategy(alpha_out, ema_out, weighted_delta, weights)
    risk_caps = _risk_cap_map(alpha_w, ema_w, rt, symbols, vol_cache)

    vns_hints = _build_vns_hints(rt, coord, symbols, vol_cache)

    scored=_score_pending_signals(rows)
    allowed, cooled = _arbitrate_conflicts_vns(scored, alpha_w, ema_w, vns_hints)

    coord_out = {
        "mode": "multi_agent_vns",
        "alpha_weight": round(alpha_w,4),
        "ema_weight": round(ema_w,4),
        "risk_caps": risk_caps,
        "sizing_hints_volatility": vns_hints,
        "cooldowns": cooled,
        "weighted_delta": round(weighted_delta,4),
        "weights": weights
    }
    rt["coordinator"]=coord_out
    cfg["runtime"]=rt
    _write_json(LIVE_CFG,cfg)

    report={
        "ts": _now(),
        "alpha_weight": round(alpha_w,4),
        "ema_weight": round(ema_w,4),
        "risk_caps": risk_caps,
        "vns_hints": vns_hints,
        "allowed": allowed,
        "cooled": cooled,
        "weighted_delta": round(weighted_delta,4),
        "alpha_outcomes": {k: round(v,4) if isinstance(v,(int,float)) else v for k,v in alpha_out.items()},
        "ema_outcomes": {k: round(v,4) if isinstance(v,(int,float)) else v for k,v in ema_out.items()}
    }
    _bus("multi_agent_coordinator_vns_applied", report)

    def _cap_str(d):
        return ", ".join([f"{s[:3]}:{v}" for s,v in list(d.items())[:4]]) + ("..." if len(d)>4 else "")
    print(f"✅ Multi-Agent Coordinator (VNS) applied | "
          f"α={coord_out['alpha_weight']} EMA={coord_out['ema_weight']} | "
          f"Alpha caps: {_cap_str(risk_caps['alpha']['risk_cap_per_symbol'])} | "
          f"allowed={len(allowed)} cooled={len(cooled)}")
    return report
