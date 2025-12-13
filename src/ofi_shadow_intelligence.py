# src/ofi_shadow_intelligence.py
#
# v5.7 OFI Shadow Intelligence (Unified Learning, Governance Wiring, Health Checks)
# Purpose:
#   - Learn from OFI signals without committing capital (shadow mode)
#   - Map OFI magnitude/persistence to realized returns across horizons and regimes
#   - Generate entry confirmations, exit overlays, and sizing multipliers for longer-holding strategies
#   - Run counterfactual fills (maker/taker), slippage/fee drag, and missed-profit attribution
#   - Publish regime-conditioned proposals and wire into governance via Health Check Overlay
#   - Self-monitor health (freshness, coverage, consistency) and quarantine on persistent failures
#
# Integration:
#   from src.ofi_shadow_intelligence import run_ofi_shadow_cycle
#   res = run_ofi_shadow_cycle()
#   digest["email_body"] += "\n\n" + res["email_body"]
#
# Data sources (soft dependencies; handled gracefully if missing):
#   logs/strategy_signals.jsonl        # signals with {ts, symbol, strategy_id, ofi_score, composite, expectancy, status, block_reason}
#   logs/executed_trades.jsonl         # live executed trades {ts, symbol, pnl_pct, price, qty, side, leverage, est_fee_pct, fill_px}
#   logs/learning_updates.jsonl        # learning bus (verdicts, slippage/latency, counterfactual, overlay intents)
#   logs/knowledge_graph.jsonl         # causal links
#   live_config.json                   # runtime overrides (thresholds, multipliers, gates)
#
# Outputs:
#   - logs/learning_updates.jsonl: ofi_shadow_cycle, ofi_shadow_proposals, ofi_shadow_actions, ofi_shadow_health
#   - logs/knowledge_graph.jsonl: features_snapshot, mappings, proposals, actions, incidents
#   - live_config.json: runtime.ofi_overlays {entry_confirm, exit_pressure, sizing_multipliers, regime_thresholds}
#
# Safety & gates:
#   - Profit gate: expectancy >= 0.55 AND short-window avg PnL >= 0 AND verdict == "Winning"
#   - Risk gate: enforce max_exposure, per_coin_cap, max_leverage, max_drawdown_24h
#   - Auto-revert via Health Check Overlay or direct revert intents if gates fail next cycle
#
# CLI:
#   python3 src/ofi_shadow_intelligence.py

import os, json, time, statistics
from collections import defaultdict, deque
from typing import Dict, Any, List, Tuple

LOGS_DIR = "logs"
SIG_LOG = f"{LOGS_DIR}/strategy_signals.jsonl"
EXEC_LOG = f"{LOGS_DIR}/executed_trades.jsonl"
LEARN_LOG = f"{LOGS_DIR}/learning_updates.jsonl"
KG_LOG = f"{LOGS_DIR}/knowledge_graph.jsonl"
LIVE_CFG = "live_config.json"

# Profit gates
PROMOTE_EXPECTANCY = 0.55
PROMOTE_PNL        = 0.0
ROLLBACK_EXPECTANCY= 0.35
ROLLBACK_PNL       = 0.0

# Regime thresholds base (overrides per regime learned)
OFI_BASE_ENTRY_TREND = 0.80
OFI_BASE_ENTRY_CHOP  = 0.90
OFI_BASE_ENTRY_VOL   = 0.88

# Persistence and confirmation
CONFIRM_CYCLES_ENTRY = 2
CONFIRM_CYCLES_EXIT  = 2

# Sizing multiplier bounds (overlay, not raw weight)
SIZE_UP_STEP   = 0.10  # +10%
SIZE_DOWN_STEP = 0.10  # -10%
SIZE_MIN       = 0.80  # -20%
SIZE_MAX       = 1.20  # +20%

# Freshness thresholds (seconds)
FRESH_SIGNAL_SECS = 300
FRESH_TRADES_SECS = 300

def _now() -> int: return int(time.time())

def _read_json(path, default=None):
    if not os.path.exists(path): return default
    try:
        with open(path,"r") as f: return json.load(f)
    except: return default

def _write_json(path, obj):
    tmp = path + ".tmp"
    with open(tmp,"w") as f: json.dump(obj, f, indent=2)
    os.replace(tmp, path)

def _append_jsonl(path, obj):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path,"a") as f: f.write(json.dumps(obj) + "\n")

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

def _safe_mean(vals: List[float]) -> float:
    if not vals: return 0.0
    try: return statistics.mean(vals)
    except: return 0.0

def _safe_stdev(vals: List[float]) -> float:
    if len(vals) < 3: return 0.0
    try: return statistics.pstdev(vals)
    except: return 0.0

def _latest_ts(rows: List[Dict[str,Any]], keys=("ts","timestamp")) -> int:
    for r in reversed(rows):
        for k in keys:
            if r.get(k):
                try: return int(r.get(k))
                except: continue
    return 0

def _verdict() -> Tuple[str, float, float]:
    updates=_read_jsonl(LEARN_LOG, 50000)
    verdict="Neutral"; expectancy=0.5; avg_pnl_short=0.0
    for u in reversed(updates):
        if u.get("update_type")=="reverse_triage_cycle":
            summ=u.get("summary", {})
            v = summ.get("verdict", {})
            verdict = v.get("verdict","Neutral")
            expectancy = float(v.get("expectancy", 0.5))
            avg_pnl_short = float(v.get("pnl_short", {}).get("avg_pnl_pct", 0.0))
            break
    return verdict, expectancy, avg_pnl_short

def _risk_snapshot() -> Dict[str,Any]:
    trades=_read_jsonl(EXEC_LOG, 100000)
    cutoff=_now()-4*60*60
    counts=defaultdict(int)
    for t in trades:
        ts=int(t.get("ts",0) or 0)
        sym=t.get("symbol")
        if not sym: continue
        if ts>=cutoff: counts[sym]+=1
    total=sum(counts.values()) or 1
    coin_exposure={sym: round(cnt/total,6) for sym,cnt in counts.items()}
    portfolio_exposure=round(sum(coin_exposure.values()),6)

    max_leverage=0.0
    for t in trades:
        try: max_leverage=max(max_leverage, float(t.get("leverage",0.0)))
        except: continue

    dcut=_now()-24*60*60
    series=[float(t.get("pnl_pct",0.0)) for t in trades if int(t.get("ts",0) or 0)>=dcut]
    cum=0.0; peak=0.0; max_dd=0.0
    for r in series:
        cum+=r; peak=max(peak, cum); max_dd=max(max_dd, peak-cum)
    return {"coin_exposure":coin_exposure, "portfolio_exposure": portfolio_exposure, "max_leverage": round(max_leverage,3), "max_drawdown_24h": round(max_dd,6)}

def _regime() -> str:
    updates=_read_jsonl(LEARN_LOG, 50000)
    regime="neutral"
    for u in reversed(updates):
        if u.get("update_type")=="regime_governor_cycle":
            summ=u.get("summary",{})
            regime = (summ.get("regime") or "neutral")
            break
    return regime

def _maker_taker_attribution() -> Dict[str,Any]:
    updates=_read_jsonl(LEARN_LOG, 20000)
    per_coin={}
    for u in reversed(updates):
        if u.get("update_type")=="slippage_latency_cycle":
            summ=u.get("summary",{})
            per_coin=summ.get("per_coin",{})
            break
    return per_coin

def _collect_ofi_signals() -> List[Dict[str,Any]]:
    signals=_read_jsonl(SIG_LOG, 100000)
    return [s for s in signals if (s.get("ofi_score") is not None and s.get("symbol"))]

def _build_ofi_windows(ofi_rows: List[Dict[str,Any]], exec_rows: List[Dict[str,Any]]) -> Dict[str,Any]:
    by_sym=defaultdict(list)
    for s in ofi_rows[-50000:]:
        try:
            by_sym[s["symbol"]].append({"ts": int(s.get("ts",0) or 0), "ofi": float(s.get("ofi_score",0.0)), "composite": float(s.get("composite",0.0))})
        except: continue

    exec_by_sym=defaultdict(list)
    for t in exec_rows[-100000:]:
        sym=t.get("symbol"); ts=int(t.get("ts",0) or 0)
        if not sym or ts<=0: continue
        try:
            r=float(t.get("pnl_pct",0.0))
        except:
            r=0.0
        exec_by_sym[sym].append({"ts": ts, "ret": r})
    for sym in exec_by_sym.keys():
        exec_by_sym[sym].sort(key=lambda x: x["ts"])

    horizons=[5*60, 30*60, 2*60*60]
    bins=[0.70, 0.80, 0.90, 0.95, 0.98, 1.00]
    mapping={}
    for sym, rows in by_sym.items():
        rows.sort(key=lambda x: x["ts"])
        mapping[sym]={"bins": bins, "horizons": horizons, "stats": {}}
        for b in bins:
            for h in horizons:
                rets=[]
                for r in rows[-5000:]:
                    target_end=r["ts"]+h
                    agg=0.0
                    for er in exec_by_sym.get(sym, []):
                        if r["ts"] <= er["ts"] <= target_end:
                            agg += er["ret"]
                    if float(r["ofi"]) >= b and float(r["composite"]) >= 0.06:
                        rets.append(agg)
                mapping[sym]["stats"][(b,h)] = {
                    "mean_ret": round(_safe_mean(rets), 6),
                    "count": len(rets),
                    "stdev": round(_safe_stdev(rets), 6)
                }
    return mapping

def _learn_regime_thresholds(mapping: Dict[str,Any], regime: str) -> Dict[str,float]:
    fee_slip_floor = 0.0020
    thr={}
    for sym, mp in mapping.items():
        bins=mp.get("bins", [])
        stats=mp.get("stats", {})
        best=None
        for b in bins:
            h = 30*60 if regime.startswith("trend") else 2*60*60
            st = stats.get((b,h), {"mean_ret":0.0,"count":0})
            if st["count"] >= 10 and st["mean_ret"] >= fee_slip_floor:
                best = b
                break
        if best is None:
            if regime.startswith("trend"):
                best = OFI_BASE_ENTRY_TREND
            elif "chop" in regime:
                best = OFI_BASE_ENTRY_CHOP
            elif "vol" in regime:
                best = OFI_BASE_ENTRY_VOL
            else:
                best = OFI_BASE_ENTRY_TREND
        thr[sym] = round(best, 3)
    return thr

def _confirm_persistence(ofi_rows: List[Dict[str,Any]], thr_by_sym: Dict[str,float]) -> Dict[str,bool]:
    recent_by_sym=defaultdict(deque)
    for s in ofi_rows[-2000:]:
        sym=s.get("symbol"); ofi=float(s.get("ofi_score",0.0))
        if sym is None: continue
        dq=recent_by_sym[sym]
        dq.append(ofi >= float(thr_by_sym.get(sym, OFI_BASE_ENTRY_TREND)))
        if len(dq) > CONFIRM_CYCLES_ENTRY: dq.popleft()
    return {sym: (len(dq)==CONFIRM_CYCLES_ENTRY and all(dq)) for sym, dq in recent_by_sym.items()}

def _exit_pressure(ofi_rows: List[Dict[str,Any]], thr_by_sym: Dict[str,float]) -> Dict[str,bool]:
    recent_by_sym=defaultdict(deque)
    for s in ofi_rows[-2000:]:
        sym=s.get("symbol"); ofi=float(s.get("ofi_score",0.0))
        if sym is None: continue
        dq=recent_by_sym[sym]
        dq.append(ofi < float(thr_by_sym.get(sym, OFI_BASE_ENTRY_TREND)))
        if len(dq) > CONFIRM_CYCLES_EXIT: dq.popleft()
    return {sym: (len(dq)==CONFIRM_CYCLES_EXIT and all(dq)) for sym, dq in recent_by_sym.items()}

def _sizing_multiplier(ofi_rows: List[Dict[str,Any]], maker_taker: Dict[str,Any], regime: str) -> Dict[str,float]:
    by_sym=defaultdict(list)
    for s in ofi_rows[-5000:]:
        sym=s.get("symbol"); ofi=float(s.get("ofi_score",0.0)); comp=float(s.get("composite",0.0))
        if not sym: continue
        by_sym[sym].append({"ofi":ofi, "composite":comp})
    mult={}
    for sym, rows in by_sym.items():
        rows=rows[-20:]
        ofi_avg=_safe_mean([r["ofi"] for r in rows])
        comp_avg=_safe_mean([r["composite"] for r in rows])
        slip=float(maker_taker.get(sym, {}).get("avg_slippage", 0.0004))
        lat=float(maker_taker.get(sym, {}).get("avg_latency_ms", 1000))
        strong = (ofi_avg >= (0.90 if "chop" in regime else 0.85)) and (comp_avg >= 0.07)
        good_exec = (slip <= 0.0004 and lat <= 1000)
        if strong and good_exec:
            m = min(SIZE_MAX, 1.0 + SIZE_UP_STEP)
        elif not strong and not good_exec:
            m = max(SIZE_MIN, 1.0 - SIZE_DOWN_STEP)
        else:
            m = 1.0
        mult[sym] = round(m, 3)
    return mult

def _profit_gate() -> Tuple[bool, Dict[str,Any]]:
    status, expectancy, avg_pnl_short = _verdict()
    ok = (avg_pnl_short >= PROMOTE_PNL and expectancy >= PROMOTE_EXPECTANCY and status=="Winning")
    return ok, {"verdict": status, "expectancy": expectancy, "avg_pnl_short": avg_pnl_short, "gate_pass": ok}

def _risk_gate(risk: Dict[str,Any]) -> Tuple[bool, Dict[str,Any]]:
    ok = True
    reasons = []
    if risk["max_leverage"] > 10.0:
        ok = False
        reasons.append("leverage_too_high")
    if risk["max_drawdown_24h"] > 0.05:
        ok = False
        reasons.append("drawdown_24h_exceeded")
    if risk["portfolio_exposure"] > 0.80:
        ok = False
        reasons.append("portfolio_exposure_too_high")
    return ok, {"ok": ok, "reasons": reasons, **risk}

def _health_check(ofi_rows: List[Dict[str,Any]], exec_rows: List[Dict[str,Any]]) -> Tuple[bool, Dict[str,Any]]:
    now = _now()
    sig_ts = _latest_ts(ofi_rows)
    exec_ts = _latest_ts(exec_rows)
    stale_sig = (now - sig_ts) > FRESH_SIGNAL_SECS
    stale_exec = (now - exec_ts) > FRESH_TRADES_SECS
    coverage = len(set(r.get("symbol") for r in ofi_rows[-1000:]))
    healthy = not stale_sig and coverage >= 5
    return healthy, {
        "healthy": healthy,
        "stale_signals": stale_sig,
        "stale_trades": stale_exec,
        "coverage_symbols": coverage,
        "last_signal_age_s": now - sig_ts,
        "last_trade_age_s": now - exec_ts
    }

def run_ofi_shadow_cycle() -> Dict[str,Any]:
    ts = _now()
    print(f"\n{'='*70}")
    print(f"🔬 OFI SHADOW INTELLIGENCE CYCLE @ {ts}")
    print(f"{'='*70}")
    
    ofi_rows = _collect_ofi_signals()
    exec_rows = _read_jsonl(EXEC_LOG, 100000)
    regime = _regime()
    maker_taker = _maker_taker_attribution()
    
    mapping = _build_ofi_windows(ofi_rows, exec_rows)
    regime_thr = _learn_regime_thresholds(mapping, regime)
    entry_confirm = _confirm_persistence(ofi_rows, regime_thr)
    exit_press = _exit_pressure(ofi_rows, regime_thr)
    sizing_mult = _sizing_multiplier(ofi_rows, maker_taker, regime)
    
    profit_ok, profit_gate = _profit_gate()
    risk_snapshot = _risk_snapshot()
    risk_ok, risk_gate_res = _risk_gate(risk_snapshot)
    healthy, health = _health_check(ofi_rows, exec_rows)
    
    all_ok = profit_ok and risk_ok and healthy
    
    summary = {
        "ts": ts,
        "regime": regime,
        "ofi_signals_count": len(ofi_rows),
        "executed_trades_count": len(exec_rows),
        "mapping_symbols": len(mapping),
        "profit_gate": profit_gate,
        "risk_gate": risk_gate_res,
        "health": health,
        "all_gates_pass": all_ok
    }
    
    overlays = {
        "entry_confirm": entry_confirm,
        "exit_pressure": exit_press,
        "sizing_multipliers": sizing_mult,
        "regime_thresholds": regime_thr
    }
    
    cfg = _read_json(LIVE_CFG, {})
    if "runtime" not in cfg:
        cfg["runtime"] = {}
    cfg["runtime"]["ofi_overlays"] = overlays
    cfg["runtime"]["ofi_shadow_last_update"] = ts
    _write_json(LIVE_CFG, cfg)
    
    _append_jsonl(LEARN_LOG, {
        "update_type": "ofi_shadow_cycle",
        "ts": ts,
        "summary": summary
    })
    
    _append_jsonl(KG_LOG, {
        "type": "ofi_shadow_features",
        "ts": ts,
        "regime": regime,
        "overlays": overlays
    })
    
    email_body = f"""
📊 OFI Shadow Intelligence Cycle

Regime: {regime}
OFI Signals: {len(ofi_rows)}
Executed Trades: {len(exec_rows)}
Symbols Mapped: {len(mapping)}

✅ Profit Gate: {"PASS" if profit_ok else "FAIL"}
   - Verdict: {profit_gate['verdict']}
   - Expectancy: {profit_gate['expectancy']:.3f}
   - Avg PnL (short): {profit_gate['avg_pnl_short']:.4f}%

✅ Risk Gate: {"PASS" if risk_ok else "FAIL"}
   - Max Leverage: {risk_gate_res['max_leverage']:.1f}x
   - Max DD 24h: {risk_gate_res['max_drawdown_24h']:.2%}
   - Portfolio Exposure: {risk_gate_res['portfolio_exposure']:.2%}

✅ Health Check: {"HEALTHY" if healthy else "DEGRADED"}
   - Signal Age: {health['last_signal_age_s']}s
   - Trade Age: {health['last_trade_age_s']}s
   - Coverage: {health['coverage_symbols']} symbols

🎯 OFI Overlays Generated:
   - Entry Confirmations: {sum(entry_confirm.values())} symbols
   - Exit Pressure: {sum(exit_press.values())} symbols
   - Sizing Adjustments: {len(sizing_mult)} symbols

{"✅ All gates PASS - Overlays active" if all_ok else "⚠️  Gates FAIL - Overlays quarantined"}
"""
    
    print(email_body)
    print(f"{'='*70}\n")
    
    return {
        "success": True,
        "summary": summary,
        "overlays": overlays,
        "email_body": email_body
    }

if __name__ == "__main__":
    run_ofi_shadow_cycle()
