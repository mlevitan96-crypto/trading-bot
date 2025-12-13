# src/multi_horizon_attribution.py
#
# v7.2 Multi-Horizon Attribution
# Purpose:
# - Measure profit impact across multiple timeframes (5m, 60m, 1d, 1w) for BOTH taken and blocked decisions.
# - Log horizon-specific counterfactual summaries and append them to the nightly digest.
# - Provide horizon-weighted signals the evolution modules can consume for sharper, resilient tuning.
#
# Integration:
# - Call run_multi_horizon_attribution() after the standard 60m run_counterfactual_cycle()
#   and before build_unified_digest()/run_profit_driven_evolution().

import os, json, time, statistics

LEARN_LOG   = "logs/learning_updates.jsonl"
PRICE_LOG   = "logs/price_feed.jsonl"
DIGEST_JSON = "logs/nightly_digest.json"
DIGEST_TXT  = "logs/nightly_digest.txt"

# --- IO helpers ---

def _now(): return int(time.time())

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
    os.makedirs(os.path.dirname(path) or "logs", exist_ok=True)
    with open(path, "a") as f:
        f.write(json.dumps(row) + "\n")

# --- Price helpers ---

def _mid_at(symbol, ts_target, tolerance_s=30):
    prices = _read_jsonl(PRICE_LOG, 500000)
    near = [p for p in prices if p.get("symbol")==symbol and abs(int(p.get("ts",0))-int(ts_target))<=tolerance_s]
    return (near[0].get("mid") if near else None)

def _latest_price_after(symbol, ts_start, horizon_s):
    prices = _read_jsonl(PRICE_LOG, 500000)
    target_ts = ts_start + horizon_s
    future = [p for p in prices if p.get("symbol")==symbol and int(p.get("ts",0))>=target_ts]
    return (future[0].get("mid") if future else None)

# --- Decision packet assembly (minimal fields needed) ---

def _collect_decisions(rows, window=200000):
    packets=[r for r in rows[-window:] if r.get("update_type") in ("decision_started","sizing_lineage","decision_finalized")]
    by_id={}
    for r in packets:
        did=r.get("decision_id"); 
        if not did: continue
        rec=by_id.get(did, {})
        rec.update(r)
        by_id[did]=rec
    return [p for p in by_id.values() if p.get("outcome") and p.get("sizing")]

# --- Multi-horizon counterfactuals for a single decision ---

def _evaluate_decision_horizons(packet, horizons_min=(5,60,1440,10080)):
    symbol = packet.get("symbol")
    ts_decision = int(packet.get("ts", _now()))
    side = (packet.get("side","LONG") or "LONG").upper()

    final_n = float((packet.get("sizing") or {}).get("final_notional_usd",0.0) or 0.0)
    fees = float((packet.get("outcome") or {}).get("fees_usd_est",0.0) or 0.0)
    entry_px = (packet.get("outcome") or {}).get("entry_px") or _mid_at(symbol, ts_decision)

    if final_n <= 0.0 or not entry_px:
        return {"status":"skip", "decision_id":packet.get("decision_id")}

    result = {"status":"ok", "decision_id":packet.get("decision_id"), "symbol":symbol, "side":side, "final_n":final_n}
    for h in horizons_min:
        exit_px = _latest_price_after(symbol, ts_decision, h*60)
        if not exit_px:
            result[f"{h}m"] = {"status":"no_price"}
            continue
        ret = (exit_px - entry_px)/entry_px if side=="LONG" else (entry_px - exit_px)/entry_px
        pnl_usd = final_n * ret - fees
        result[f"{h}m"] = {"ret": round(ret,6), "net_usd": round(pnl_usd,4)}
    return result

# --- Aggregate multi-horizon attribution for the night ---

def _aggregate_horizon_results(results, was_blocked_map):
    horizons = []
    for r in results:
        for k in list(r.keys()):
            if k.endswith("m"):
                horizons.append(k)
    horizons = sorted(set(horizons), key=lambda x: int(x[:-1]))

    summary = {"ts": _now(), "update_type": "counterfactual_summary_multi", "horizons": {}}
    for h in horizons:
        taken_nets, blocked_nets = [], []
        for r in results:
            cell = r.get(h, {})
            if not cell or cell.get("status")=="no_price": continue
            net = float(cell.get("net_usd",0.0) or 0.0)
            did = r.get("decision_id")
            if was_blocked_map.get(did, False):
                blocked_nets.append(net)
            else:
                taken_nets.append(net)
        summary["horizons"][h] = {
            "taken_count": len(taken_nets),
            "taken_sum_net": round(sum(taken_nets),4),
            "taken_avg_net": round(statistics.mean(taken_nets),4) if taken_nets else 0.0,
            "blocked_count": len(blocked_nets),
            "blocked_sum_net": round(sum(blocked_nets),4),
            "blocked_avg_net": round(statistics.mean(blocked_nets),4) if blocked_nets else 0.0,
            "delta_sum_net": round(sum(taken_nets) - sum(blocked_nets),4)
        }
    return summary

# --- Horizon weights (for downstream evolution) ---

def get_horizon_weights(mode="balanced"):
    if mode=="profit_max":
        return {"5m":0.15, "60m":0.25, "1440m":0.30, "10080m":0.30}
    if mode=="risk_aware":
        return {"5m":0.35, "60m":0.35, "1440m":0.20, "10080m":0.10}
    return {"5m":0.25, "60m":0.25, "1440m":0.25, "10080m":0.25}

def _weighted_delta(summary_multi, weights):
    total=0.0
    wsum=0.0
    for h, stats in (summary_multi.get("horizons") or {}).items():
        w = weights.get(h, 0.0)
        total += w * float(stats.get("delta_sum_net",0.0) or 0.0)
        wsum  += w
    return (total/wsum) if wsum>0 else 0.0

# --- Digest append ---

def _append_to_digest(summary_multi):
    os.makedirs("logs", exist_ok=True)
    base = {}
    if os.path.exists(DIGEST_JSON):
        try: base = json.load(open(DIGEST_JSON))
        except: base = {}
    base["counterfactual_summary_multi"] = summary_multi
    with open(DIGEST_JSON,"w") as f: json.dump(base, f, indent=2)

    lines=[]
    lines.append("\n=== Multi-Horizon Counterfactuals ===")
    for h, stats in (summary_multi.get("horizons") or {}).items():
        lines.append(f"{h}: Δ={stats['delta_sum_net']} taken_sum={stats['taken_sum_net']} blocked_sum={stats['blocked_sum_net']}")
    with open(DIGEST_TXT,"a") as f: f.write("\n".join(lines)+"\n")

# --- Main runner ---

def run_multi_horizon_attribution(horizons=(5,60,1440,10080), weighting_mode="profit_max"):
    learn_rows = _read_jsonl(LEARN_LOG, 500000)

    decisions = _collect_decisions(learn_rows, window=200000)
    was_blocked_map = {}
    for p in decisions:
        did = p.get("decision_id")
        status = (p.get("outcome") or {}).get("status")
        was_blocked_map[did] = (status=="blocked")

    results=[]
    for p in decisions:
        eval_res = _evaluate_decision_horizons(p, horizons_min=horizons)
        if eval_res.get("status")=="ok":
            results.append(eval_res)

    summary_multi = _aggregate_horizon_results(results, was_blocked_map)
    _append_jsonl(LEARN_LOG, summary_multi)
    _append_to_digest(summary_multi)

    weights = get_horizon_weights(weighting_mode)
    weighted_delta = _weighted_delta(summary_multi, weights)
    signal = {
        "ts": _now(),
        "update_type": "multi_horizon_weighted_signal",
        "weights": weights,
        "weighted_delta": round(weighted_delta,4)
    }
    _append_jsonl(LEARN_LOG, signal)

    horizon_deltas = " ".join([f"{h} Δ={summary_multi['horizons'][h]['delta_sum_net']}" for h in summary_multi.get('horizons',{})]) if summary_multi.get('horizons') else "(no horizons)"
    print(f"[Multi-Horizon] weighted Δ={signal['weighted_delta']} mode={weighting_mode} | {horizon_deltas}")
    return summary_multi, signal
