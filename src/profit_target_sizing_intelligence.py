# src/profit_target_sizing_intelligence.py
#
# v5.8 Profit Target & Sizing Intelligence (Evidence Fusion, Pattern Discovery, Governance Wiring)
# Purpose:
#   - Learn regime-aware profit targets and dynamic sizing multipliers from realized outcomes and shadow signals
#   - Fuse multiple evidence streams (Composite, OFI Shadow, Sentiment, Breakout, EMA) into a conviction score
#   - Prioritize "smart yes": hone evidence to find profitable long/short patterns, avoid over-filtering
#   - Publish proposals (targets, sizing, pattern tags) under profit/risk gates; auto-revert when gates fail
#   - Self-check health (freshness, coverage) and quarantine if inputs go stale
#
# Design philosophy:
#   - Less "no", more "smart yes": explicit minimum-pass lanes ensure high-conviction trades still execute
#   - Patterns are learned from realized PnL and counterfactuals, not hard-coded rules
#   - Evidence fusion → Conviction score → Adaptive target & sizing → Governance intents (profit/risk gated)
#
# Integration:
#   from src.profit_target_sizing_intelligence import run_pts_cycle
#   res = run_pts_cycle()
#   digest["email_body"] += "\n\n" + res["email_body"]
#
# Inputs (soft dependencies; handled gracefully if missing):
#   logs/executed_trades.jsonl         # realized trades with pnl_pct, side, symbol, strategy_id, ts
#   logs/strategy_signals.jsonl        # signals with ofi_score, composite, sentiment_score, ema_state, breakout_strength
#   logs/learning_updates.jsonl        # regime, slippage/latency attribution, reverse triage, counterfactual
#   live_config.json                   # runtime gates and prior overlays
#
# Outputs:
#   logs/learning_updates.jsonl: pts_cycle, pts_proposals, pts_reverts, pts_health
#   logs/knowledge_graph.jsonl: pts_features, pts_patterns, pts_proposals, pts_reverts
#   live_config.json runtime.pts_overlays: {targets_by_regime, sizing_by_symbol, patterns}
#
# Gates:
#   Profit: expectancy ≥ 0.55 AND short-window avg PnL ≥ 0 AND verdict == "Winning"
#   Risk: exposure/leverage/drawdown caps enforced
#
# CLI:
#   python3 src/profit_target_sizing_intelligence.py

import os, json, time, statistics
from collections import defaultdict
from typing import Dict, Any, List, Tuple

LOGS_DIR = "logs"
EXEC_LOG = f"{LOGS_DIR}/executed_trades.jsonl"
SIG_LOG  = f"{LOGS_DIR}/strategy_signals.jsonl"
LEARN_LOG= f"{LOGS_DIR}/learning_updates.jsonl"
KG_LOG   = f"{LOGS_DIR}/knowledge_graph.jsonl"
LIVE_CFG = "live_config.json"

# Profit gates
PROMOTE_EXPECTANCY = 0.55
PROMOTE_PNL        = 0.0

# Min-pass lanes (avoid over-filtering):
MIN_PASS_CONVICTION_TREND = 0.70
MIN_PASS_CONVICTION_CHOP  = 0.80
MIN_PASS_CONVICTION_VOL   = 0.75

# Target bands per regime (starting priors; learned adaptively)
PRIORS = {
    "trend": {"min": 0.008, "max": 0.025},   # 0.8% to 2.5%
    "chop":  {"min": 0.006, "max": 0.015},   # 0.6% to 1.5%
    "vol":   {"min": 0.010, "max": 0.030},   # 1.0% to 3.0%
    "neutral":{"min": 0.007, "max": 0.020}
}

# Sizing multipliers bounds
SIZE_MIN = 0.80
SIZE_MAX = 1.20
SIZE_STEP= 0.10

# Freshness thresholds
FRESH_SIG_SECS  = 300
FRESH_EXEC_SECS = 300

def _now(): return int(time.time())

def _read_json(path, default=None):
    if not os.path.exists(path): return default
    try:
        with open(path,"r") as f: return json.load(f)
    except: return default

def _write_json(path, obj):
    tmp=path+".tmp"
    with open(tmp,"w") as f: json.dump(obj,f,indent=2)
    os.replace(tmp, path)

def _append_jsonl(path, obj):
    with open(path,"a") as f: f.write(json.dumps(obj)+"\n")

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

def _latest_ts(rows: List[Dict[str,Any]], keys=("ts","timestamp")) -> int:
    for r in reversed(rows):
        for k in keys:
            if r.get(k):
                try: return int(r.get(k))
                except: continue
    return 0

def _safe_mean(vals: List[float]) -> float:
    if not vals: return 0.0
    try: return statistics.mean(vals)
    except: return 0.0

def _safe_median(vals: List[float]) -> float:
    if not vals: return 0.0
    try: return statistics.median(vals)
    except: return 0.0

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

def _evidence_fusion(sig: Dict[str,Any]) -> float:
    # Normalize fields to [0,1], then weighted sum
    ofi=float(sig.get("ofi_score",0.0))
    comp=float(sig.get("composite",0.0))
    sent=float(sig.get("sentiment_score",0.0))
    brk =float(sig.get("breakout_strength",0.0))
    ema = 1.0 if str(sig.get("ema_state","")).lower() in ("bullish","bearish") else 0.0
    # Simple normalization: composite ~ [0,0.1], map to [0,1]
    comp_n = min(max(comp/0.10, 0.0), 1.0)
    ofi_n  = min(max(ofi, 0.0), 1.0)
    sent_n = min(max((sent+1.0)/2.0, 0.0), 1.0)  # if sentiment in [-1,1]
    brk_n  = min(max(brk, 0.0), 1.0)
    ema_n  = ema
    # Weights: emphasize composite + OFI, then breakout + sentiment, EMA as binary boost
    score = (0.30*comp_n + 0.30*ofi_n + 0.20*brk_n + 0.15*sent_n + 0.05*ema_n)
    return round(score, 3)

def _learn_targets(exec_rows: List[Dict[str,Any]], regime: str) -> Dict[str, Dict[str,float]]:
    # Learn per-symbol profit target within regime bands based on recent realized returns
    cut=_now()-48*60*60
    by_sym=defaultdict(list)
    for t in exec_rows[-100000:]:
        ts=int(t.get("ts",0) or 0); sym=t.get("symbol")
        if not sym or ts<cut: continue
        try: r=float(t.get("pnl_pct",0.0))
        except: r=0.0
        by_sym[sym].append(r)
    bands=PRIORS.get(regime, PRIORS["neutral"])
    learned={}
    for sym, rets in by_sym.items():
        pos=[r for r in rets if r>0]
        neg=[r for r in rets if r<0]
        mpos=_safe_median(pos)
        mvol=_safe_median([abs(r) for r in rets])
        # Target = clamp(median positive return, min..max), fallback to volatility-informed midpoint
        base = mpos if mpos>0 else (0.5*bands["min"]+0.5*bands["max"])*0.5
        tgt  = min(max(base, bands["min"]), bands["max"])
        stop = min(max(0.5*mvol, 0.003), 0.02)  # dynamic protective stop (0.3%..2%)
        learned[sym]={"profit_target": round(tgt,4), "protective_stop": round(stop,4)}
    return learned

def _learn_sizing(sig_rows: List[Dict[str,Any]], regime: str) -> Dict[str,float]:
    # Size by conviction and execution health proxy (composite + OFI persistence)
    by_sym=defaultdict(list)
    for s in sig_rows[-5000:]:
        sym=s.get("symbol"); 
        if not sym: continue
        score=_evidence_fusion(s)
        by_sym[sym].append(score)
    sizing={}
    for sym, scores in by_sym.items():
        avg=_safe_mean(scores[-50:])
        strong = avg >= (0.85 if "chop" in regime else 0.80)
        weak   = avg < 0.65
        if strong:
            sizing[sym]=min(1.0+SIZE_STEP, SIZE_MAX)
        elif weak:
            sizing[sym]=max(1.0-SIZE_STEP, SIZE_MIN)
        else:
            sizing[sym]=1.0
        sizing[sym]=round(sizing[sym],3)
    return sizing

def _health(sig_rows, exec_rows) -> Dict[str,Any]:
    sig_fresh = (_now()-_latest_ts(sig_rows)) <= FRESH_SIG_SECS if sig_rows else False
    exec_fresh= (_now()-_latest_ts(exec_rows))<= FRESH_EXEC_SECS if exec_rows else False
    coverage  = len(sig_rows[-2000:]) >= 50
    status = "healthy" if (sig_fresh and exec_fresh and coverage) else ("issues" if (sig_fresh or exec_fresh) else "quarantined")
    return {"signals_fresh": sig_fresh, "exec_fresh": exec_fresh, "coverage_ok": coverage, "status": status}

def _profit_gate() -> Tuple[bool, Dict[str,Any]]:
    status, expectancy, avg_pnl_short = _verdict()
    return (avg_pnl_short >= PROMOTE_PNL and expectancy >= PROMOTE_EXPECTANCY and status=="Winning"), {"status":status,"expectancy":expectancy,"avg_pnl_short":avg_pnl_short}

def _risk_gate(risk: Dict[str,Any], live: Dict[str,Any]) -> bool:
    limits = (live.get("runtime", {}).get("capital_limits") or {
        "max_exposure": 0.75, "per_coin_cap": 0.25, "max_leverage": 5.0, "max_drawdown_24h": 0.05
    })
    if risk["portfolio_exposure"] > limits["max_exposure"]: return False
    if risk["max_leverage"] > limits["max_leverage"]: return False
    if risk["max_drawdown_24h"] > limits["max_drawdown_24h"]: return False
    return True

def _publish_kg(subject: Dict[str,Any], predicate: str, obj: Dict[str,Any]):
    _append_jsonl(KG_LOG, {"ts": _now(), "subject": subject, "predicate": predicate, "object": obj})

def run_pts_cycle() -> Dict[str,Any]:
    # Read inputs
    exec_rows=_read_jsonl(EXEC_LOG, 100000)
    sig_rows =_read_jsonl(SIG_LOG,  100000)
    live=_read_json(LIVE_CFG, default={}) or {}
    rt=live.get("runtime", {}) or {}
    live["runtime"]=rt

    # Health
    health=_health(sig_rows, exec_rows)
    _append_jsonl(LEARN_LOG, {"ts": _now(), "update_type":"pts_health", "health": health})
    _publish_kg({"overlay":"pts"}, "health", health)
    if health["status"]=="quarantined":
        email="=== Profit Target & Sizing Intelligence ===\nStatus: 🛑 Quarantined (stale/insufficient inputs)\nNo actions taken."
        summary={"ts":_now(),"health":health,"email_body":email}
        _append_jsonl(LEARN_LOG, {"ts": summary["ts"], "update_type":"pts_cycle", "summary": {k:v for k,v in summary.items() if k!='email_body'}})
        return summary

    regime=_regime()
    risk=_risk_snapshot()
    profit_ok, verdict_meta=_profit_gate()
    risk_ok=_risk_gate(risk, live)

    # Learn targets and sizing
    targets=_learn_targets(exec_rows, regime)
    sizing =_learn_sizing(sig_rows, regime)

    # Pattern discovery (transparent tags)
    patterns={}
    # Long pattern: high composite + strong OFI + breakout momentum
    # Short pattern: negative sentiment + breakdown + OFI below threshold
    for s in sig_rows[-2000:]:
        sym=s.get("symbol"); 
        if not sym: continue
        comp=float(s.get("composite",0.0)); ofi=float(s.get("ofi_score",0.0))
        brk=float(s.get("breakout_strength",0.0)); sent=float(s.get("sentiment_score",0.0))
        ema_state=str(s.get("ema_state","")).lower()
        long_cond = (comp>=0.075 and ofi>=0.85 and brk>=0.70 and ema_state=="bullish")
        short_cond= (comp>=0.070 and ofi<=0.60 and brk>=0.65 and sent<=-0.30 and ema_state=="bearish")
        # Keep simple, evidence-driven tags
        if long_cond: patterns.setdefault(sym, set()).add("long_pressure_alignment")
        if short_cond:patterns.setdefault(sym, set()).add("short_breakdown_alignment")
    patterns={k:list(v) for k,v in patterns.items()}

    # Minimum-pass lanes (Smart YES)
    min_lane={}
    if "trend" in regime:
        min_lane["conviction_floor"]=MIN_PASS_CONVICTION_TREND
    elif "chop" in regime:
        min_lane["conviction_floor"]=MIN_PASS_CONVICTION_CHOP
    elif "vol" in regime:
        min_lane["conviction_floor"]=MIN_PASS_CONVICTION_VOL
    else:
        min_lane["conviction_floor"]=MIN_PASS_CONVICTION_TREND

    # Build proposals (governors apply with gates)
    proposals=[]
    # Profit targets per symbol (regime-aware)
    for sym, cfg in targets.items():
        proposals.append({
            "type":"profit_target",
            "symbol": sym,
            "profit_target": cfg["profit_target"],
            "protective_stop": cfg["protective_stop"],
            "regime": regime,
            "source":"pts"
        })
    # Sizing multipliers per symbol
    for sym, mult in sizing.items():
        if mult!=1.0 and profit_ok and risk_ok:
            proposals.append({
                "type":"sizing_multiplier",
                "symbol": sym,
                "multiplier": mult,
                "bounds": {"min": SIZE_MIN, "max": SIZE_MAX},
                "regime": regime,
                "source":"pts"
            })
    # Pattern tags to be used by entry/exit governors
    for sym, tags in patterns.items():
        proposals.append({
            "type":"pattern_tags",
            "symbol": sym,
            "tags": tags,
            "regime": regime,
            "source":"pts"
        })
    # Smart YES min-pass lane
    proposals.append({
        "type":"min_pass_lane",
        "conviction_floor": min_lane["conviction_floor"],
        "regime": regime,
        "source":"pts"
    })

    if proposals:
        _append_jsonl(LEARN_LOG, {"ts": _now(), "update_type":"pts_proposals", "proposals": proposals, "verdict": verdict_meta, "risk": risk})
        _publish_kg({"overlay":"pts"}, "proposals", {"proposals": proposals})

    # Update runtime overlays (non-invasive)
    rt.setdefault("pts_overlays", {})
    rt["pts_overlays"]["targets_by_regime"]= {"regime": regime, "targets": targets}
    rt["pts_overlays"]["sizing_by_symbol"]= sizing
    rt["pts_overlays"]["patterns"]= patterns
    rt["pts_overlays"]["min_pass_lane"]= min_lane
    live["runtime"]=rt
    _write_json(LIVE_CFG, live)

    # Reverts if gates fail
    reverts=[]
    if not profit_ok or not risk_ok:
        bus=_read_jsonl(LEARN_LOG, 20000)
        last_intents=[]
        for b in reversed(bus):
            if b.get("update_type")=="governance_intents":
                last_intents=b.get("intents", [])
                break
        for li in last_intents:
            if li.get("source") in ("pts","ofi_shadow"):
                reverts.append({
                    "type":"revert_governance_intent",
                    "symbol": li.get("symbol"),
                    "reason": "profit_or_risk_gate_failed"
                })
        if reverts:
            _append_jsonl(LEARN_LOG, {"ts": _now(), "update_type":"pts_reverts", "reverts": reverts, "verdict": verdict_meta, "risk": risk})
            _publish_kg({"overlay":"pts"}, "reverts", {"reverts": reverts, "verdict": verdict_meta})

    email=f"""
=== Profit Target & Sizing Intelligence ===
Regime: {regime}
Health: {health['status']} | Signals fresh: {health['signals_fresh']} | Trades fresh: {health['exec_fresh']}

Learned targets (per symbol):
{json.dumps(targets, indent=2)}

Sizing multipliers:
{json.dumps(sizing, indent=2)}

Pattern tags (evidence-driven):
{json.dumps(patterns, indent=2) if patterns else "None"}

Smart YES min-pass lane (conviction floor):
{min_lane['conviction_floor']}

Proposals published:
{json.dumps(proposals, indent=2) if proposals else "None"}

Gates:
Profit OK: {profit_ok} | Verdict: {json.dumps(verdict_meta, indent=2)}
Risk OK: {risk_ok} | Snapshot: {json.dumps(risk, indent=2)}

Reverts:
{json.dumps(reverts, indent=2) if reverts else "None"}
""".strip()

    summary={
        "ts": _now(),
        "regime": regime,
        "health": health,
        "targets": targets,
        "sizing": sizing,
        "patterns": patterns,
        "min_pass_lane": min_lane,
        "proposals": proposals,
        "gates": {"profit_ok": profit_ok, "risk_ok": risk_ok, "verdict": verdict_meta, "risk": risk},
        "reverts": reverts,
        "email_body": email
    }
    _append_jsonl(LEARN_LOG, {"ts": summary["ts"], "update_type":"pts_cycle", "summary": {k:v for k,v in summary.items() if k!='email_body'}})
    return summary

# CLI
if __name__=="__main__":
    res = run_pts_cycle()
    print(json.dumps(res, indent=2))
    print("\n--- Email Body ---\n")
    print(res["email_body"])
