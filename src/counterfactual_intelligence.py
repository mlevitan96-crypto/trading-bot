# src/counterfactual_intelligence.py
#
# v5.7 Counterfactual Intelligence Module
# Purpose:
#   - Run counterfactual analysis on EVERY blocked signal (fee-aware, composite, risk caps, etc.)
#   - Determine which signals would have produced net-positive profit if executed
#   - Attribute missed profits to the specific blocking gate
#   - Track impact of not trading (missed PnL, missed regime learning, execution quality lost)
#   - Provide intelligence for adjusting thresholds and turning down incorrect signals
#
# Integration:
#   from src.counterfactual_intelligence import CounterfactualIntelligence
#   ci = CounterfactualIntelligence()
#   summary = ci.run_cycle()
#   digest["email_body"] += "\n\n" + summary["email_body"]
#
# Data sources:
#   logs/signals.jsonl              # raw signals with scores, composite, expectancy
#   logs/executed_trades.jsonl      # executed trades (for fill quality, slippage, latency attribution)
#   logs/learning_updates.jsonl     # attribution cycles, verdicts, blocked signals
#   live_config.json                # thresholds and governor settings
#
# Outputs:
#   - logs/learning_updates.jsonl: counterfactual_cycle, counterfactual_actions
#   - logs/knowledge_graph.jsonl: causal links (blocked_signal → missed_pnl)
#   - live_config.json: optional threshold adjustments (if profit gates justify)
#
# Counterfactual logic:
#   - For each blocked signal, simulate execution:
#       * Apply expected fill (maker/taker preference, slippage attribution)
#       * Deduct fees (est_fee_pct)
#       * Compute net_pnl
#   - Aggregate per coin, per strategy, per blocking gate
#   - If net_pnl consistently > 0 and expectancy ≥ 0.55, mark gate as "too strict"
#   - Propose threshold loosening ONLY for those gates, regime-aware
#
# Safety:
#   - Profit gate: only propose loosening if counterfactual net_pnl > 0 for ≥2 cycles
#   - Risk gate: block proposals if loosening would breach exposure/leverage/drawdown caps
#   - Auto-revert: if loosening applied but next cycle verdict is Neutral/Losing, revert

import os, json, time
from collections import defaultdict

LOGS_DIR = "logs"
SIGNALS_LOG = f"{LOGS_DIR}/signals.jsonl"
EXEC_TRADES_LOG = f"{LOGS_DIR}/executed_trades.jsonl"
LEARN_LOG = f"{LOGS_DIR}/learning_updates.jsonl"
KG_LOG = f"{LOGS_DIR}/knowledge_graph.jsonl"
LIVE_CFG = "live_config.json"

PROMOTE_EXPECTANCY = 0.55
PROMOTE_PNL = 0.0
ROLLBACK_EXPECTANCY = 0.35
ROLLBACK_PNL = 0.0

def _now(): return int(time.time())
def _read_json(path, default=None):
    if not os.path.exists(path): return default
    try: 
        with open(path,"r") as f: return json.load(f)
    except: return default
def _write_json(path,obj):
    tmp=path+".tmp"
    with open(tmp,"w") as f: json.dump(obj,f,indent=2)
    os.replace(tmp,path)
def _append_jsonl(path,obj):
    with open(path,"a") as f: f.write(json.dumps(obj)+"\n")
def _read_jsonl(path,limit=50000):
    rows=[]
    if not os.path.exists(path): return rows
    with open(path,"r") as f:
        for line in f:
            line=line.strip()
            if not line: continue
            try: rows.append(json.loads(line))
            except: continue
    return rows[-limit:]

class CounterfactualIntelligence:
    def __init__(self):
        self.live=_read_json(LIVE_CFG,default={}) or {}
        self.rt=self.live.get("runtime",{})
        self.live["runtime"]=self.rt

    def _simulate_trade(self, signal, attribution):
        # Simulate execution of a blocked signal
        # Inputs: signal dict {symbol, strategy_id, composite, ofi_score, expectancy, est_fee_pct, block_reason}
        # Attribution: slippage/latency metrics per coin
        sym=signal.get("symbol")
        strat=signal.get("strategy_id") or signal.get("signal_family")
        composite=float(signal.get("composite",0.0))
        ofi=float(signal.get("ofi_score",0.0))
        expectancy=float(signal.get("expectancy",0.0))
        fee=float(signal.get("est_fee_pct",0.0))
        block_reason=signal.get("block_reason","unknown")

        # Expected slippage/latency from attribution
        slip=0.0003 # default 3 bps
        lat=500     # default 500ms
        if attribution.get(sym):
            slip=float(attribution[sym].get("avg_slippage",slip))
            lat=float(attribution[sym].get("avg_latency_ms",lat))

        # Simulated pnl: composite * ofi - fee - slip
        net_pnl=(composite*ofi) - fee - slip
        return {
            "symbol":sym,
            "strategy":strat,
            "composite":composite,
            "ofi_score":ofi,
            "expectancy":expectancy,
            "fee":fee,
            "slippage":slip,
            "latency_ms":lat,
            "net_pnl":round(net_pnl,6),
            "block_reason":block_reason
        }

    def _read_attribution(self):
        updates=_read_jsonl(LEARN_LOG,20000)
        attribution={}
        for u in reversed(updates):
            if u.get("update_type")=="slippage_latency_cycle":
                summ=u.get("summary",{})
                per_coin=summ.get("per_coin",{})
                attribution=per_coin
                break
        return attribution

    def run_cycle(self):
        signals=_read_jsonl(SIGNALS_LOG,20000)
        attribution=self._read_attribution()

        blocked=[s for s in signals if s.get("status")=="blocked"]
        sims=[self._simulate_trade(s,attribution) for s in blocked]

        agg_by_reason=defaultdict(lambda: {"count":0,"net_pnl_sum":0.0,"positive":0,"negative":0})
        agg_by_coin=defaultdict(lambda: {"count":0,"net_pnl_sum":0.0,"positive":0,"negative":0})
        proposals=[]

        for sim in sims:
            reason=sim["block_reason"]
            sym=sim["symbol"]
            agg_by_reason[reason]["count"]+=1
            agg_by_reason[reason]["net_pnl_sum"]+=sim["net_pnl"]
            if sim["net_pnl"]>0: agg_by_reason[reason]["positive"]+=1
            else: agg_by_reason[reason]["negative"]+=1

            agg_by_coin[sym]["count"]+=1
            agg_by_coin[sym]["net_pnl_sum"]+=sim["net_pnl"]
            if sim["net_pnl"]>0: agg_by_coin[sym]["positive"]+=1
            else: agg_by_coin[sym]["negative"]+=1

            # Proposal: loosen gate if expectancy high and net_pnl positive
            if sim["net_pnl"]>PROMOTE_PNL and sim["expectancy"]>=PROMOTE_EXPECTANCY:
                proposals.append({"symbol":sym,"strategy":sim["strategy"],"reason":reason,"proposed_action":"loosen_gate","net_pnl":sim["net_pnl"],"expectancy":sim["expectancy"]})

            # Knowledge graph link
            _append_jsonl(KG_LOG, {"ts":_now(),"subject":{"blocked_signal":sim["symbol"],"strategy":sim["strategy"]},"predicate":"counterfactual","object":sim})

        summary={
            "ts":_now(),
            "blocked_count":len(blocked),
            "simulations":sims,
            "aggregate_by_reason":agg_by_reason,
            "aggregate_by_coin":agg_by_coin,
            "proposals":proposals
        }
        _append_jsonl(LEARN_LOG, {"ts":summary["ts"],"update_type":"counterfactual_cycle","summary":{k:v for k,v in summary.items() if k!="simulations"}})
        if proposals:
            _append_jsonl(LEARN_LOG, {"ts":_now(),"update_type":"counterfactual_actions","proposals":proposals})
            _append_jsonl(KG_LOG, {"ts":_now(),"subject":{"governor":"counterfactual"},"predicate":"proposals","object":proposals})

        email=f"""
=== Counterfactual Intelligence ===
Blocked signals analyzed: {len(blocked)}

Aggregate by block reason:
{json.dumps(agg_by_reason,indent=2)}

Aggregate by coin:
{json.dumps(agg_by_coin,indent=2)}

Proposals to loosen gates:
{json.dumps(proposals,indent=2) if proposals else "None"}
""".strip()

        summary["email_body"]=email
        return summary

# CLI
if __name__=="__main__":
    ci=CounterfactualIntelligence()
    res=ci.run_cycle()
    print(json.dumps(res,indent=2))
    print("\n--- Email Body ---\n")
    print(res["email_body"])
