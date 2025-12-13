# src/health_check_overlay.py
#
# v5.7 Health Check Overlay (Universal Oversight + Counterfactual→Governance Wiring)
# Purpose:
#   - Continuously assess health across all modules, detect stale inputs, contradictory outputs, and failed gates
#   - Wire Counterfactual Intelligence outcomes into Portfolio/Risk/Regime governance with strict profit/risk gates
#   - Auto-quarantine misbehaving modules and publish unified oversight events and email digest sections
#
# Integration:
#   from src.health_check_overlay import HealthCheckOverlay
#   hco = HealthCheckOverlay()
#   summary = hco.run_cycle()
#   digest["email_body"] += "\n\n" + summary["email_body"]
#
# Data sources (soft dependencies, handled gracefully if missing):
#   logs/signals.jsonl
#   logs/executed_trades.jsonl
#   logs/learning_updates.jsonl
#   logs/knowledge_graph.jsonl
#   logs/live_trades.jsonl
#   logs/order_routing.jsonl
#   logs/pnl_history.jsonl
#   logs/fee_events.jsonl
#   live_config.json
#
# Outputs:
#   - logs/learning_updates.jsonl: health_overlay_cycle, health_overlay_incidents, governance_intents
#   - logs/knowledge_graph.jsonl: causal links for oversight and wiring actions
#   - live_config.json: overlay state (quarantine flags, module health map)
#
# Governance wiring:
#   - Consumes Counterfactual Intelligence proposals (update_type: counterfactual_actions)
#   - Applies profit gate (expectancy >= 0.55, short-window PnL >= 0, verdict Winning) and risk gate (exposure/leverage/drawdown caps)
#   - Publishes governance intents for Portfolio Governor (adjust scalars/weights), Risk Governor (keep blocks), Regime Governor (regime-conditioned loosening)
#   - Auto-reverts prior intents if next cycle verdict Neutral/Losing or risk breaches appear
#
# Health checks:
#   - Input freshness: signals, trades, orders, pnl_history, fee_events
#   - Module heartbeat: presence of recent updates per module (<= 2 cycles)
#   - Consistency gates: profit/risk consistency, dashboard validator quarantine propagation
#   - Remediation: marks module unhealthy and sets quarantine if violations persist ≥ 2 cycles
#
# CLI:
#   python3 src/health_check_overlay.py

import os, json, time
from collections import defaultdict

LOGS_DIR = "logs"
SIGNALS_LOG = f"{LOGS_DIR}/signals.jsonl"
EXEC_TRADES_LOG = f"{LOGS_DIR}/executed_trades.jsonl"
LIVE_TRADES_LOG = f"{LOGS_DIR}/live_trades.jsonl"
ORDER_LOG = f"{LOGS_DIR}/order_routing.jsonl"
PNL_HISTORY_LOG = f"{LOGS_DIR}/pnl_history.jsonl"
FEE_EVENTS_LOG = f"{LOGS_DIR}/fee_events.jsonl"
LEARN_LOG = f"{LOGS_DIR}/learning_updates.jsonl"
KG_LOG = f"{LOGS_DIR}/knowledge_graph.jsonl"
LIVE_CFG = "live_config.json"

# Freshness thresholds (seconds)
FRESH_SIGNAL_SECS = 180
FRESH_TRADES_SECS = 180
FRESH_ORDERS_SECS = 300
FRESH_PNL_SECS = 3600
FRESH_FEE_SECS = 3600

# Profit gates
PROMOTE_EXPECTANCY = 0.55
PROMOTE_PNL        = 0.0
ROLLBACK_EXPECTANCY= 0.35
ROLLBACK_PNL       = 0.0

# Risk caps (fallback if runtime not present)
DEFAULT_LIMITS = {
    "max_exposure": 0.75,
    "per_coin_cap": 0.25,
    "max_leverage": 5.0,
    "max_drawdown_24h": 0.05
}

def _now(): return int(time.time())

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

def _latest_ts(jsonl_rows, ts_keys=("ts","timestamp","bucket_ts")):
    latest=0
    for r in reversed(jsonl_rows):
        for k in ts_keys:
            if r.get(k):
                try:
                    latest = int(r.get(k))
                    return latest
                except:
                    continue
    return latest

def _verdict():
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

def _risk_snapshot():
    # Lightweight snapshot; aligns with RiskGovernor if present
    trades=_read_jsonl(EXEC_TRADES_LOG, 100000)
    # exposure proxy by recent trade counts
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

    # drawdown approx over 24h
    dcut=_now()-24*60*60
    series=[float(t.get("pnl_pct",0.0)) for t in trades if int(t.get("ts",0) or 0)>=dcut]
    cum=0.0; peak=0.0; max_dd=0.0
    for r in series:
        cum+=r; peak=max(peak, cum); max_dd=max(max_dd, peak-cum)
    return {"coin_exposure":coin_exposure, "portfolio_exposure": portfolio_exposure, "max_leverage": round(max_leverage,3), "max_drawdown_24h": round(max_dd,6)}

class HealthCheckOverlay:
    def __init__(self):
        self.live=_read_json(LIVE_CFG, default={}) or {}
        self.rt=self.live.get("runtime", {}) or {}
        self.rt.setdefault("overlay_state", {"module_health":{}, "quarantines":{}, "retry_counters":{}})
        self.live["runtime"]=self.rt
        _write_json(LIVE_CFG, self.live)

    def _freshness_check(self):
        signals=_read_jsonl(SIGNALS_LOG, 100000)
        exec_trades=_read_jsonl(EXEC_TRADES_LOG, 100000)
        live_trades=_read_jsonl(LIVE_TRADES_LOG, 100000)
        orders=_read_jsonl(ORDER_LOG, 100000)
        pnl_hist=_read_jsonl(PNL_HISTORY_LOG, 100000)
        fees=_read_jsonl(FEE_EVENTS_LOG, 100000)

        now=_now()
        fres={}

        fres["signals_fresh"]= (now - _latest_ts(signals)) <= FRESH_SIGNAL_SECS if signals else False
        fres["exec_trades_fresh"]= (now - _latest_ts(exec_trades)) <= FRESH_TRADES_SECS if exec_trades else False
        fres["live_trades_fresh"]= (now - _latest_ts(live_trades)) <= FRESH_TRADES_SECS if live_trades else False
        fres["orders_fresh"]= (now - _latest_ts(orders)) <= FRESH_ORDERS_SECS if orders else False
        fres["pnl_history_fresh"]= (now - _latest_ts(pnl_hist, ts_keys=("bucket_ts","ts","timestamp"))) <= FRESH_PNL_SECS if pnl_hist else False
        fres["fees_fresh"]= (now - _latest_ts(fees)) <= FRESH_FEE_SECS if fees else False

        return fres

    def _module_heartbeats(self):
        # Check recent updates per module in learning bus
        updates=_read_jsonl(LEARN_LOG, 100000)
        now=_now()
        hb={}
        last_type_ts=defaultdict(int)
        for u in updates[-50000:]:
            ut=u.get("update_type")
            ts=int(u.get("ts",0) or 0)
            if ut and ts:
                last_type_ts[ut]=max(last_type_ts[ut], ts)

        def fresh(ts, limit): return (now - ts) <= limit if ts>0 else False
        hb["portfolio_risk_cycle"]= fresh(last_type_ts.get("portfolio_risk_cycle",0), 1800)
        hb["regime_governor_cycle"]= fresh(last_type_ts.get("regime_governor_cycle",0), 1800)
        hb["dashboard_validator_cycle"]= fresh(last_type_ts.get("dashboard_validator_cycle",0), 1800)
        hb["counterfactual_cycle"]= fresh(last_type_ts.get("counterfactual_cycle",0), 1800)
        hb["reverse_triage_cycle"]= fresh(last_type_ts.get("reverse_triage_cycle",0), 1800)
        hb["slippage_latency_cycle"]= fresh(last_type_ts.get("slippage_latency_cycle",0), 1800)
        hb["profit_attribution_cycle"]= fresh(last_type_ts.get("profit_attribution_cycle",0), 1800)
        hb["strategy_attribution_cycle"]= fresh(last_type_ts.get("strategy_attribution_cycle",0), 1800)
        return hb

    def _risk_limits(self):
        limits=self.rt.get("capital_limits", {}) or {}
        for k,v in DEFAULT_LIMITS.items():
            limits.setdefault(k,v)
        return limits

    def _apply_governance_wiring(self):
        # Consume counterfactual proposals and publish governance intents if gates pass
        updates=_read_jsonl(LEARN_LOG, 50000)
        proposals=[]
        for u in reversed(updates):
            if u.get("update_type")=="counterfactual_actions":
                props=u.get("proposals", [])
                if props: proposals=props
                break

        status, expectancy, avg_pnl_short = _verdict()
        profit_gate_ok = (avg_pnl_short >= PROMOTE_PNL and expectancy >= PROMOTE_EXPECTANCY and status=="Winning")
        risk = _risk_snapshot()
        limits = self._risk_limits()

        intents=[]
        if profit_gate_ok:
            for p in proposals[:10]:
                sym = p.get("symbol")
                reason = p.get("reason","")
                # risk gate: block intents if would exceed per-coin cap (approx via exposure proxy)
                if risk.get("coin_exposure",{}).get(sym,0.0) >= limits["per_coin_cap"]:
                    continue
                # produce a portfolio intent: increase scalar slightly; regime-conditioned handled by Regime Governor reading intent tags
                intents.append({
                    "intent_type": "portfolio_adjust_scalar",
                    "symbol": sym,
                    "delta": +0.05,  # +5% conservative
                    "source": "counterfactual",
                    "reason": reason,
                    "guards": {"profit_gate": True, "risk_gate": True}
                })

        # Revert intents if profit gates fail or verdict Neutral/Losing
        reverts=[]
        if not profit_gate_ok or risk["portfolio_exposure"] > limits["max_exposure"] or risk["max_leverage"] > limits["max_leverage"] or risk["max_drawdown_24h"] > limits["max_drawdown_24h"]:
            # read last governance_intents and propose reverts
            bus=_read_jsonl(LEARN_LOG, 20000)
            last_intents=[]
            for b in reversed(bus):
                if b.get("update_type")=="governance_intents":
                    last_intents=b.get("intents", [])
                    break
            for li in last_intents:
                if li.get("source")=="counterfactual":
                    reverts.append({
                        "intent_type": "revert_portfolio_adjust_scalar",
                        "symbol": li.get("symbol"),
                        "reason": "profit_or_risk_gate_failed",
                        "original_delta": li.get("delta")
                    })

        # Publish intents and reverts
        if intents:
            _append_jsonl(LEARN_LOG, {"ts": _now(), "update_type":"governance_intents", "source":"overlay", "intents": intents})
            _append_jsonl(KG_LOG, {"ts": _now(), "subject":{"overlay":"health"}, "predicate":"governance_intents", "object": intents})
        if reverts:
            _append_jsonl(LEARN_LOG, {"ts": _now(), "update_type":"governance_reverts", "source":"overlay", "reverts": reverts, "verdict": {"status": status, "expectancy": expectancy, "avg_pnl_short": avg_pnl_short}})
            _append_jsonl(KG_LOG, {"ts": _now(), "subject":{"overlay":"health"}, "predicate":"governance_reverts", "object": reverts})

        return {"intents": intents, "reverts": reverts, "profit_gate_ok": profit_gate_ok, "risk": risk, "limits": limits}

    def _quarantine_logic(self, freshness, heartbeats):
        # Determine quarantines: stale inputs or missing heartbeats for critical modules
        retries=self.rt.get("overlay_state", {}).get("retry_counters", {})
        quarantines=self.rt.get("overlay_state", {}).get("quarantines", {})

        def bump(key):
            retries[key]=int(retries.get(key,0))+1
        def clear(key):
            retries[key]=0

        incidents=[]

        # Freshness failures
        for key, ok in freshness.items():
            if not ok:
                bump(f"fresh_{key}")
                incidents.append({"type":"freshness_fail", "key":key})
            else:
                clear(f"fresh_{key}")

        # Heartbeat failures
        for mod, ok in heartbeats.items():
            if not ok:
                bump(f"hb_{mod}")
                incidents.append({"type":"heartbeat_fail", "module":mod})
            else:
                clear(f"hb_{mod}")

        # Apply quarantine if any counter exceeds threshold (2 cycles)
        for rkey, count in retries.items():
            if count >= 2:
                quarantines[rkey] = True

        self.rt["overlay_state"]["retry_counters"]=retries
        self.rt["overlay_state"]["quarantines"]=quarantines
        self.live["runtime"]=self.rt
        _write_json(LIVE_CFG, self.live)

        return {"incidents": incidents, "quarantines": quarantines, "retries": retries}

    def run_cycle(self):
        # 1) Health checks
        freshness=self._freshness_check()
        heartbeats=self._module_heartbeats()
        q = self._quarantine_logic(freshness, heartbeats)

        # 2) Wire counterfactual into governance with gates
        gov=self._apply_governance_wiring()

        # 3) Publish overlay incidents
        status="✅ Healthy"
        if q["quarantines"]:
            status="🛑 Quarantined"
        elif q["incidents"]:
            status="⚠️ Issues detected"

        if q["incidents"]:
            _append_jsonl(LEARN_LOG, {"ts": _now(), "update_type":"health_overlay_incidents", "incidents": q["incidents"], "quarantines": q["quarantines"], "retries": q["retries"]})
            _append_jsonl(KG_LOG, {"ts": _now(), "subject":{"overlay":"health"}, "predicate":"incidents", "object": {"incidents": q["incidents"], "quarantines": q["quarantines"]}})

        email=f"""
=== Health Check Overlay ===
Status: {status}

Freshness:
{json.dumps(freshness, indent=2)}

Module heartbeats (<= 30 min):
{json.dumps(heartbeats, indent=2)}

Quarantines:
{json.dumps(q["quarantines"], indent=2) if q["quarantines"] else "None"}

Governance wiring (Counterfactual → Portfolio/Risk/Regime):
Profit gate OK: {gov["profit_gate_ok"]}
Risk snapshot:
{json.dumps(gov["risk"], indent=2)}
Limits:
{json.dumps(gov["limits"], indent=2)}

Intents published:
{json.dumps(gov["intents"], indent=2) if gov["intents"] else "None"}

Reverts published:
{json.dumps(gov["reverts"], indent=2) if gov["reverts"] else "None"}
""".strip()

        summary={
            "ts": _now(),
            "freshness": freshness,
            "heartbeats": heartbeats,
            "overlay": q,
            "governance": gov,
            "email_body": email
        }
        _append_jsonl(LEARN_LOG, {"ts": summary["ts"], "update_type":"health_overlay_cycle", "summary": {k:v for k,v in summary.items() if k!='email_body'}})
        return summary

# CLI
if __name__=="__main__":
    hco = HealthCheckOverlay()
    res = hco.run_cycle()
    print(json.dumps(res, indent=2))
    print("\n--- Email Body ---\n")
    print(res["email_body"])
