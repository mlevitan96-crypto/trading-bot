# src/missed_opportunity_probe.py
#
# v7.2 Missed Opportunity Probe
# Purpose:
# - Capture signals that never reached the decision stage (early gate-filtered/throttled) and run counterfactuals.
# - Quantify "missed edge" across horizons (5m, 60m, 1d, 1w) and attribute profit impact by gate reason and strategy.
# - Feed findings into EVERY layer: digest, profit attribution, horizon-weighted evolution, auto-tuning, and coordinators.
#
# What it adds end-to-end:
# 1) Per-signal records: update_type="missed_opportunity_probe"
# 2) Nightly summary: update_type="missed_opportunity_summary" (+ horizon stats)
# 3) Weighted delta (missed-only and blended): update_type="missed_opportunity_weighted_signal"
# 4) Live config overlay: runtime.research_overlays → relax/tighten pressures per gate/strategy/horizon
# 5) Digest extension: "=== Missed Opportunity Overlay ===" and structured JSON block
#
# Integration (nightly sequence):
# - After multi-horizon attribution and before digest+evolution

import os, json, time, statistics
from collections import defaultdict
from src.full_integration_blofin_micro_live_and_paper import _bus

LEARN_LOG   = "logs/learning_updates.jsonl"
PRICE_LOG   = "logs/price_feed.jsonl"
DIGEST_JSON = "logs/nightly_digest.json"
DIGEST_TXT  = "logs/nightly_digest.txt"
LIVE_CFG    = "live_config.json"
VOL_LOG     = "logs/volatility_cache.json"

def _now(): return int(time.time())

def _read_json(path):
    if not os.path.exists(path): return {}
    try: return json.load(open(path))
    except: return {}

def _write_json(path, obj):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path,"w") as f: json.dump(obj, f, indent=2)

def _read_jsonl(path, limit=500000):
    rows=[]
    if not os.path.exists(path): return rows
    with open(path,"r") as f:
        for line in f:
            line=line.strip()
            if not line: continue
            try: rows.append(json.loads(line))
            except: continue
    return rows[-limit:]

def _append_jsonl(path, row):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "a") as f:
        f.write(json.dumps(row) + "\n")

# --- Horizon weights ---

def get_horizon_weights(mode="balanced"):
    if mode=="profit_max":
        return {"5m":0.15, "60m":0.25, "1440m":0.30, "10080m":0.30}
    if mode=="risk_aware":
        return {"5m":0.35, "60m":0.35, "1440m":0.20, "10080m":0.10}
    return {"5m":0.25, "60m":0.25, "1440m":0.25, "10080m":0.25}

# --- Price helpers ---

def _mid_at(symbol, ts_target, tolerance_s=30):
    prices = _read_jsonl(PRICE_LOG, 500000)
    near = [p for p in prices if p.get("symbol")==symbol and abs(int(p.get("ts",0))-int(ts_target))<=tolerance_s]
    return (float(near[0].get("mid", near[0].get("close", 0.0)) or 0.0) if near else None)

def _price_after(symbol, ts_start, horizon_s):
    prices = _read_jsonl(PRICE_LOG, 500000)
    target_ts = ts_start + horizon_s
    future = [p for p in prices if p.get("symbol")==symbol and int(p.get("ts",0))>=target_ts]
    return (float(future[0].get("mid", future[0].get("close", 0.0)) or 0.0) if future else None)

# --- Volatility cache (ATR) for VNS conversion ---

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

# --- Signal collection: early-stage, never reached decision attribution ---

def _collect_missed_signals(rows, window=200000):
    started_ids=set(r.get("signal_id") for r in rows if r.get("update_type")=="decision_started" and r.get("signal_id"))
    candidates=[r for r in rows[-window:] if r.get("update_type") in ("signal_detected","gate_precheck_blocked","throttle_dropped","exposure_blocked_pre")]
    missed=[]
    seen=set()
    for r in candidates:
        sid=r.get("signal_id")
        if not sid or sid in started_ids or sid in seen: continue
        seen.add(sid)
        missed.append({
            "signal_id": sid,
            "symbol": r.get("symbol"),
            "side": (r.get("side","LONG") or "LONG").upper(),
            "strategy": r.get("strategy_id","unknown"),
            "ts": int(r.get("ts", _now())),
            "reason_codes": r.get("reason_codes", r.get("gate_reason_codes", ["precheck"])) or ["precheck"],
            "ctx": r.get("signal_ctx",{})
        })
    return missed

# --- Notional derivation: use coordinator hints (USD) and VNS risk units if available ---

def _derive_notionals(symbol, strategy, ctx, cfg, vol_cache):
    rt = cfg.get("runtime",{}) or {}
    coord = rt.get("coordinator",{}) or {}
    vns = (coord.get("sizing_hints_volatility") or {})
    usd = (coord.get("sizing_hints") or {})

    ru = float((vns.get(strategy) or {}).get("per_trade_risk_units",{}).get(symbol, 0.0) or 0.0)
    usd_notional = float((usd.get(strategy) or {}).get("default_final_notional_usd", 50.0) or 50.0)

    px = _mid_at(symbol, int((ctx or {}).get("ts", _now())))
    atr = (vol_cache.get(symbol) or {}).get("atr")
    if ru>0.0 and atr and px and px>0:
        return usd_notional, ru*atr*px
    return usd_notional, usd_notional

# --- Per-signal horizon evaluation ---

def _evaluate_missed_horizons(sig, horizons_min=(5,60,1440,10080), fees_rate=0.0005, slip_rate=0.0003):
    symbol=sig["symbol"]; ts=sig["ts"]; side=sig["side"]; strat=sig["strategy"]
    cfg=_read_json(LIVE_CFG); vol_cache=_ensure_vol_cache([symbol])
    usd_hint, cf_notional=_derive_notionals(symbol, "alpha" if "alpha" in strat.lower() else ("ema" if "ema" in strat.lower() else "alpha"), sig, cfg, vol_cache)
    entry=_mid_at(symbol, ts)
    if not entry or cf_notional<=0: 
        return {"status":"skip","signal_id":sig["signal_id"]}

    result={"status":"ok","signal_id":sig["signal_id"],"symbol":symbol,"side":side,"strategy":strat,"final_n":round(cf_notional,2)}
    for h in horizons_min:
        exit_px=_price_after(symbol, ts, h*60)
        if not exit_px:
            result[f"{h}m"]={"status":"no_price"}; continue
        ret=(exit_px-entry)/entry if side=="LONG" else (entry-exit_px)/entry
        fees=cf_notional*fees_rate; slip=cf_notional*slip_rate
        net=cf_notional*ret - (fees+slip)
        result[f"{h}m"]={"ret": round(ret,6), "net_usd": round(net,4)}
    result["reasons"]=sig["reason_codes"]
    return result

# --- Aggregate summary + pressures ---

def _aggregate_missed(results, weights):
    horizons=sorted({k for r in results for k in r.keys() if k.endswith("m")}, key=lambda x:int(x[:-1]))
    by_gate=defaultdict(lambda: defaultdict(list))
    by_strategy=defaultdict(lambda: defaultdict(list))
    totals={h:[] for h in horizons}

    for r in results:
        strat=r.get("strategy","unknown")
        gates=r.get("reasons",["precheck"])
        for h in horizons:
            cell=r.get(h,{}); 
            if not cell or cell.get("status")=="no_price": continue
            net=float(cell.get("net_usd",0.0) or 0.0)
            totals[h].append(net)
            by_strategy[strat][h].append(net)
            for g in gates:
                by_gate[g][h].append(net)

    summary={"ts":_now(),"update_type":"missed_opportunity_summary","horizons":{},"by_gate":{},"by_strategy":{}}
    for h in horizons:
        vals=totals[h]
        summary["horizons"][h]={
            "count": len(vals),
            "sum_net": round(sum(vals),4),
            "avg_net": round(statistics.mean(vals),4) if vals else 0.0
        }
    for g, hv in by_gate.items():
        summary["by_gate"][g]={h: {
            "count": len(hv.get(h,[])),
            "sum_net": round(sum(hv.get(h,[])),4),
            "avg_net": round(statistics.mean(hv.get(h,[])),4) if hv.get(h,[]) else 0.0
        } for h in horizons}
    for s, hv in by_strategy.items():
        summary["by_strategy"][s]={h: {
            "count": len(hv.get(h,[])),
            "sum_net": round(sum(hv.get(h,[])),4),
            "avg_net": round(statistics.mean(hv.get(h,[])),4) if hv.get(h,[]) else 0.0
        } for h in horizons}

    wsum=0.0; wtotal=0.0
    for h, stats in summary["horizons"].items():
        w=weights.get(h,0.0); wsum+=w; wtotal+=w*float(stats.get("sum_net",0.0) or 0.0)
    missed_weighted_delta=(wtotal/wsum) if wsum>0 else 0.0

    blended_weighted_delta=missed_weighted_delta
    rows=_read_jsonl(LEARN_LOG,500000)
    base_weighted=[r for r in rows if r.get("update_type")=="multi_horizon_weighted_signal"]
    if base_weighted:
        blended_weighted_delta += float(base_weighted[-1].get("weighted_delta",0.0) or 0.0)

    return summary, missed_weighted_delta, blended_weighted_delta

# --- Digest append ---

def _append_to_digest(summary):
    os.makedirs("logs", exist_ok=True)
    base = _read_json(DIGEST_JSON)
    base["missed_opportunity_summary"]=summary
    with open(DIGEST_JSON,"w") as f: json.dump(base, f, indent=2)

    lines=["=== Missed Opportunity Overlay ==="]
    for h, stats in (summary.get("horizons") or {}).items():
        lines.append(f"{h}: count={stats['count']} sum_net={stats['sum_net']} avg={stats['avg_net']}")
    with open(DIGEST_TXT,"a") as f: f.write("\n".join(lines)+"\n")

# --- Live config overlay: relax/tighten pressures by gate and strategy ---

def _apply_research_overlays(summary, missed_weighted_delta, blended_weighted_delta):
    cfg=_read_json(LIVE_CFG); rt=cfg.get("runtime",{}) or {}
    overlays=rt.get("research_overlays",{}) or {}

    def pressure(x):
        if x==0: return 0.0
        mag=abs(x)/(10.0+abs(x))
        return (1 if x>0 else -1)*round(mag,3)

    gate_pressures={}
    for gate, hv in (summary.get("by_gate") or {}).items():
        total=sum((cell.get("sum_net",0.0) or 0.0) for cell in hv.values())
        gate_pressures[gate]=pressure(total)

    strat_pressures={}
    for strat, hv in (summary.get("by_strategy") or {}).items():
        total=sum((cell.get("sum_net",0.0) or 0.0) for cell in hv.values())
        strat_pressures[strat]=pressure(total)

    overlays.update({
        "missed_weighted_delta": round(missed_weighted_delta,4),
        "blended_weighted_delta": round(blended_weighted_delta,4),
        "gate_pressures": gate_pressures,
        "strategy_pressures": strat_pressures,
    })
    rt["research_overlays"]=overlays
    cfg["runtime"]=rt
    _write_json(LIVE_CFG, cfg)
    return overlays

# --- Main runner ---

def run_missed_opportunity_probe(horizons=(5,60,1440,10080), weighting_mode="profit_max"):
    rows=_read_jsonl(LEARN_LOG, 500000)
    weights=get_horizon_weights(weighting_mode)

    missed=_collect_missed_signals(rows)
    if not missed:
        print("ℹ️  Missed Opportunity Probe: No missed signals found")
        return {"status":"no_data"}

    results=[]
    for sig in missed[:500]:
        res=_evaluate_missed_horizons(sig, horizons)
        if res.get("status")=="ok":
            results.append(res)
            _append_jsonl(LEARN_LOG, {"update_type":"missed_opportunity_probe", **res})

    if not results:
        print("ℹ️  Missed Opportunity Probe: No evaluable results")
        return {"status":"no_results"}

    summary, missed_delta, blended_delta = _aggregate_missed(results, weights)
    _append_jsonl(LEARN_LOG, summary)
    _append_jsonl(LEARN_LOG, {"update_type":"missed_opportunity_weighted_signal", "ts":_now(),
                              "missed_weighted_delta": round(missed_delta,4),
                              "blended_weighted_delta": round(blended_delta,4),
                              "weights": weights})

    _append_to_digest(summary)
    overlays=_apply_research_overlays(summary, missed_delta, blended_delta)

    _bus("missed_opportunity_probe_completed", {
        "ts": _now(),
        "missed_count": len(missed),
        "evaluated_count": len(results),
        "missed_weighted_delta": round(missed_delta,4),
        "blended_weighted_delta": round(blended_delta,4),
        "gate_pressures": overlays.get("gate_pressures",{}),
        "strategy_pressures": overlays.get("strategy_pressures",{})
    })

    print(f"✅ Missed Opportunity Probe completed | "
          f"missed={len(missed)} eval={len(results)} | "
          f"missed_Δ={round(missed_delta,2)} blended_Δ={round(blended_delta,2)} | "
          f"gates={len(overlays.get('gate_pressures',{}))} strats={len(overlays.get('strategy_pressures',{}))}")
    return {"status":"ok", "summary": summary, "overlays": overlays}
