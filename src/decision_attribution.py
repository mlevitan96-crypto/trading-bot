import os, json, time, uuid, statistics

LEARN_LOG = "logs/learning_updates.jsonl"
SIG_LOG   = "logs/strategy_signals.jsonl"
PRICE_LOG = "logs/price_feed.jsonl"
EXEC_LOG  = "logs/executed_trades.jsonl"

def _append_jsonl(path, row):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "a") as f:
        f.write(json.dumps(row) + "\n")

def _now(): return int(time.time())

def begin_decision_packet(symbol: str,
                          strategy_id: str,
                          side: str,
                          signal_ctx: dict,
                          runtime_ctx: dict):
    """
    signal_ctx: {"ofi":float,"ensemble":float,"mtf_conf":float,"ema_confirm":str,"latency_ms":int,"regime":"trend|range|chop"}
    runtime_ctx: {"size_throttle":float,"protective_mode":bool,"kill_switch":bool,"quarantine":bool,"symbol_mult":float,"max_exposure":float}
    """
    decision_id = str(uuid.uuid4())
    packet = {
        "ts": _now(),
        "decision_id": decision_id,
        "type": "decision_packet",
        "symbol": symbol,
        "strategy_id": strategy_id,
        "side": side,
        "signal_ctx": signal_ctx,
        "runtime_ctx": runtime_ctx,
        "gates": {},
        "sizing": {},
        "outcome": None,
        "counterfactual": None
    }
    _append_jsonl(LEARN_LOG, {"update_type":"decision_started", **packet})
    return packet

def attach_gate_verdicts(packet: dict,
                         gate_ctx: dict):
    """
    gate_ctx: {
      "edge_after_cost": float,
      "fee_gate_ok": bool,
      "exposure_pct": float,
      "exposure_cap": float,
      "exposure_gate_ok": bool,
      "global": {"kill_switch":bool,"protective_mode":bool,"size_throttle":float,"reasons":[...]}
    }
    """
    packet["gates"] = gate_ctx
    reasons = []
    if not gate_ctx.get("fee_gate_ok", True): reasons.append("fee_gate_block")
    if not gate_ctx.get("exposure_gate_ok", True): reasons.append("exposure_gate_block")
    if gate_ctx.get("global", {}).get("kill_switch", False): reasons.append("kill_switch_phase82_block")
    if gate_ctx.get("global", {}).get("size_throttle", 0.0) <= 0.0: reasons.append("size_throttle_zero")
    if gate_ctx.get("global", {}).get("protective_mode", False): reasons.append("protective_mode_active")
    packet["gates"]["reason_codes"] = reasons if reasons else ["passed_all"]
    _append_jsonl(LEARN_LOG, {"update_type":"gate_verdicts", "decision_id":packet["decision_id"], "gates":packet["gates"]})
    return packet

def attach_sizing_lineage(packet: dict,
                          base_notional_usd: float,
                          mtf_mult: float,
                          protective_mult: float,
                          size_throttle: float,
                          symbol_mult: float,
                          quarantine_mult: float,
                          final_notional_usd: float):
    packet["sizing"] = {
        "base_notional_usd": round(base_notional_usd or 0.0, 2),
        "mtf_mult": round(mtf_mult or 1.0, 4),
        "protective_mult": round(protective_mult or 1.0, 4),
        "size_throttle": round(size_throttle or 0.0, 4),
        "symbol_mult": round(symbol_mult or 1.0, 4),
        "quarantine_mult": round(quarantine_mult or 1.0, 4),
        "final_notional_usd": round(final_notional_usd or 0.0, 2)
    }
    _append_jsonl(LEARN_LOG, {"update_type":"sizing_lineage", "decision_id":packet["decision_id"], "sizing":packet["sizing"]})
    return packet

def finalize_decision_packet(packet: dict,
                             outcome: str,
                             price_ctx: dict,
                             fees_usd_est: float,
                             expected_edge_hint: float):
    """
    outcome: "executed" or "blocked"
    price_ctx: {"entry_px":float} for executed or blocked-attempt snapshot
    expected_edge_hint: model expectation pre-cost
    """
    packet["outcome"] = {
        "status": outcome,
        "entry_px": price_ctx.get("entry_px"),
        "fees_usd_est": round(fees_usd_est or 0.0, 4),
        "expected_edge_hint": round(expected_edge_hint or 0.0, 6),
        "expected_net_usd": round((expected_edge_hint or 0.0) * (packet.get("sizing",{}).get("final_notional_usd",0.0)) - (fees_usd_est or 0.0), 4)
    }
    _append_jsonl(LEARN_LOG, {"update_type":"decision_finalized", "decision_id":packet["decision_id"], "outcome":packet["outcome"]})
    return packet

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

def _latest_price_after(symbol, ts_start, horizon_s):
    prices = _read_jsonl(PRICE_LOG, 500000)
    target_ts = ts_start + horizon_s
    future = [p for p in prices if p.get("symbol")==symbol and p.get("ts",0)>=target_ts]
    return (future[0].get("mid") if future else None)

def _mid_at(symbol, ts_target):
    prices = _read_jsonl(PRICE_LOG, 500000)
    near = [p for p in prices if p.get("symbol")==symbol and abs(p.get("ts",0)-ts_target)<=30]
    return (near[0].get("mid") if near else None)

def assess_counterfactual(packet: dict, horizon_minutes=60):
    """
    For blocked decisions: simulate PnL if the trade had been taken at snapshot mid,
    closed at horizon mid, with same final_notional_usd and fees estimate.
    For executed decisions: compute realized_net_usd if we have exit; else compute 60-min hypothetical.
    """
    sizing = packet.get("sizing",{})
    final_n = float(sizing.get("final_notional_usd",0.0) or 0.0)
    if final_n <= 0.0:
        packet["counterfactual"] = {"status":"skipped_no_size"}
        _append_jsonl(LEARN_LOG, {"update_type":"counterfactual", "decision_id":packet["decision_id"], "counterfactual":packet["counterfactual"]})
        return packet

    symbol = packet.get("symbol")
    ts_decision = int(packet.get("ts", _now()))
    entry_px = packet.get("outcome",{}).get("entry_px") or _mid_at(symbol, ts_decision)
    exit_px = _latest_price_after(symbol, ts_decision, horizon_minutes*60)
    side = packet.get("side","LONG").upper()
    fees = float(packet.get("outcome",{}).get("fees_usd_est",0.0) or 0.0)

    if not entry_px or not exit_px:
        packet["counterfactual"] = {"status":"insufficient_price_data"}
        _append_jsonl(LEARN_LOG, {"update_type":"counterfactual", "decision_id":packet["decision_id"], "counterfactual":packet["counterfactual"]})
        return packet

    ret = (exit_px - entry_px)/entry_px if side=="LONG" else (entry_px - exit_px)/entry_px
    pnl_usd = final_n * ret - fees

    packet["counterfactual"] = {
        "status":"evaluated",
        "horizon_min": horizon_minutes,
        "entry_px": entry_px,
        "exit_px": exit_px,
        "ret": round(ret,6),
        "final_notional_usd": round(final_n,2),
        "fees_usd_est": round(fees,4),
        "net_usd": round(pnl_usd,4),
        "was_blocked": packet.get("outcome",{}).get("status")=="blocked"
    }
    _append_jsonl(LEARN_LOG, {"update_type":"counterfactual", "decision_id":packet["decision_id"], "counterfactual":packet["counterfactual"]})
    return packet

def run_counterfactual_cycle(horizon_minutes=60):
    rows = _read_jsonl(LEARN_LOG, 500000)
    packets = {}
    for r in rows:
        did = r.get("decision_id")
        if not did: continue
        p = packets.get(did, {"decision_id":did})
        if r.get("update_type")=="decision_started":
            p.update(r)
        elif r.get("update_type")=="sizing_lineage":
            p["sizing"] = r.get("sizing",{})
        elif r.get("update_type")=="decision_finalized":
            p["outcome"] = r.get("outcome",{})
        packets[did]=p

    evaluated=[]
    for did, p in packets.items():
        if p.get("counterfactual"): continue
        p = assess_counterfactual(p, horizon_minutes=horizon_minutes)
        cf = p.get("counterfactual",{})
        if cf.get("status")=="evaluated":
            evaluated.append({"blocked": cf.get("was_blocked",False), "net_usd": cf.get("net_usd",0.0)})

    blocked_nets = [e["net_usd"] for e in evaluated if e["blocked"]]
    taken_nets   = [e["net_usd"] for e in evaluated if not e["blocked"]]
    summary = {
        "ts": _now(),
        "horizon_minutes": horizon_minutes,
        "blocked_count": len(blocked_nets),
        "blocked_avg_net": round(statistics.mean(blocked_nets),4) if blocked_nets else 0.0,
        "blocked_sum_net": round(sum(blocked_nets),4),
        "taken_count": len(taken_nets),
        "taken_avg_net": round(statistics.mean(taken_nets),4) if taken_nets else 0.0,
        "taken_sum_net": round(sum(taken_nets),4),
        "delta_sum_net": round(sum(taken_nets) - sum(blocked_nets),4)
    }
    _append_jsonl(LEARN_LOG, {"update_type":"counterfactual_summary", **summary})
    print(f"📊 [Counterfactual {horizon_minutes}m] blocked_sum=${summary['blocked_sum_net']:.2f} taken_sum=${summary['taken_sum_net']:.2f} Δ=${summary['delta_sum_net']:.2f}")
    return summary
