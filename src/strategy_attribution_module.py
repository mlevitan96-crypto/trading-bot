# src/strategy_attribution_module.py
#
# v5.7 Strategy Attribution Module
# Purpose:
#   - Attribute realized PnL to strategies/signal families (full loop to learning engine)
#   - Compute short vs long uplift, expectancy alignment, and reliability signals
#   - Propose promotions/rollbacks/pauses and update strategy weights/status
#   - Write knowledge graph links and monitoring-friendly logs
#
# Integration:
#   from src.strategy_attribution_module import StrategyAttribution
#   sam = StrategyAttribution()
#   summary = sam.run_cycle()
#   digest["email_body"] += "\n\n" + summary["email_body"]
#
# Assumptions (optional fields are handled gracefully):
#   logs/executed_trades.jsonl rows may include:
#     { ts, symbol, pnl_pct, strategy_id, signal_family, expectancy_at_exec, route, venue }
#   logs/strategy_signals.jsonl (optional enrichment):
#     { ts, symbol, strategy_id, signal_family, composite_score, expectancy }
#   live_config.json:
#     {
#       "runtime": {
#         "strategy_weights": { "ema_long": 0.12, "ofi_scalp": 0.18, ... },
#         "strategy_status":  { "ema_long": "active", "ofi_scalp": "active", ... }
#       }
#     }
#
# Profit gates (consistent with system-wide governance):
#   - Promote when: short-window PnL ≥ 0 and expectancy ≥ 0.55 for 2 cycles
#   - Rollback when: short-window PnL ≤ 0 and expectancy ≤ 0.35 for 2 cycles
#   - Pause when: reliability degrades (e.g., missing telemetry, zero trades for N cycles)
#
# Monitoring:
#   - Writes summary and actions to logs/learning_updates.jsonl
#   - Writes causal links to logs/knowledge_graph.jsonl
#   - Digest section includes per-strategy metrics and actions

import os, json, time
from collections import defaultdict

LOGS_DIR  = "logs"
EXEC_LOG  = f"{LOGS_DIR}/executed_trades.jsonl"
SIG_LOG   = f"{LOGS_DIR}/strategy_signals.jsonl"
LEARN_LOG = f"{LOGS_DIR}/learning_updates.jsonl"
KG_LOG    = f"{LOGS_DIR}/knowledge_graph.jsonl"
LIVE_CFG  = "live_config.json"

SHORT_WINDOW_MINS = 240   # 4 hours
LONG_WINDOW_MINS  = 1440  # 24 hours

# Profit gates
PROMOTE_EXPECTANCY = 0.55
PROMOTE_PNL        = 0.0
ROLLBACK_EXPECTANCY= 0.35
ROLLBACK_PNL       = 0.0

# Weight bounds and steps
WEIGHT_MIN = 0.02   # 2%
WEIGHT_MAX = 0.40   # 40%
WEIGHT_STEP= 0.04   # +/− 4% per decision

# Reliability thresholds
NO_TRADE_CYCLES_TO_PAUSE = 3

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

def _read_jsonl(path, limit=20000):
    rows=[]
    if not os.path.exists(path): return rows
    with open(path,"r") as f:
        for line in f:
            line=line.strip()
            if not line: continue
            try: rows.append(json.loads(line))
            except: continue
    return rows[-limit:]

def _append_jsonl(path, obj):
    with open(path,"a") as f: f.write(json.dumps(obj) + "\n")

def _kg(subject, predicate, obj):
    _append_jsonl(KG_LOG, {"ts": _now(), "subject": subject, "predicate": predicate, "object": obj})

def _window_cutoff(mins): return _now() - mins*60

class StrategyAttribution:
    """
    Strategy-level profit attribution and governance.
    - Aggregates PnL per strategy for short/long windows
    - Computes uplift (short - long), tracks expectancy alignment
    - Applies profit gates to propose promotions/rollbacks/pauses
    - Updates strategy_weights and strategy_status in live_config.json
    """
    def __init__(self, short_window=SHORT_WINDOW_MINS, long_window=LONG_WINDOW_MINS):
        self.short = short_window
        self.long  = long_window
        self.live  = _read_json(LIVE_CFG, default={}) or {}
        self.rt    = self.live.get("runtime", {})
        self.rt.setdefault("strategy_weights", {})
        self.rt.setdefault("strategy_status", {})
        self.rt.setdefault("strategy_cycle_counters", {})
        self.live["runtime"] = self.rt
        _write_json(LIVE_CFG, self.live)

    def _aggregate_by_strategy(self):
        short_cut = _window_cutoff(self.short)
        long_cut  = _window_cutoff(self.long)
        trades    = _read_jsonl(EXEC_LOG, 50000)
        signals   = _read_jsonl(SIG_LOG, 50000)

        latest_expectancy = defaultdict(lambda: 0.0)
        for s in signals:
            sid = s.get("strategy_id") or s.get("signal_family")
            if not sid: continue
            exp = s.get("expectancy")
            if exp is not None:
                try:
                    latest_expectancy[sid] = float(exp)
                except: pass

        agg_short = defaultdict(lambda: {"pnl_sum":0.0, "n":0})
        agg_long  = defaultdict(lambda: {"pnl_sum":0.0, "n":0})
        exec_counts = defaultdict(int)

        for t in trades:
            ts = t.get("ts") or t.get("timestamp") or 0
            sid = t.get("strategy_id") or t.get("signal_family") or "unknown"
            pnl = float(t.get("pnl_pct", 0.0))
            if ts >= long_cut:
                agg_long[sid]["pnl_sum"]  += pnl
                agg_long[sid]["n"]        += 1
            if ts >= short_cut:
                agg_short[sid]["pnl_sum"] += pnl
                agg_short[sid]["n"]       += 1
                exec_counts[sid]          += 1

        strategies = {}
        all_ids = set(list(agg_long.keys()) + list(agg_short.keys()) + list(self.rt["strategy_weights"].keys()))
        for sid in all_ids:
            s_short = agg_short.get(sid, {"pnl_sum":0.0, "n":0})
            s_long  = agg_long.get(sid, {"pnl_sum":0.0, "n":0})

            avg_short = (s_short["pnl_sum"]/max(1,s_short["n"])) if s_short["n"]>0 else 0.0
            avg_long  = (s_long["pnl_sum"]/max(1,s_long["n"])) if s_long["n"]>0 else 0.0
            uplift    = avg_short - avg_long
            expectancy = latest_expectancy[sid]

            strategies[sid] = {
                "avg_pnl_short": round(avg_short, 6),
                "avg_pnl_long":  round(avg_long, 6),
                "uplift_pct":    round(uplift, 6),
                "trades_short":  int(s_short["n"]),
                "trades_long":   int(s_long["n"]),
                "expectancy":    round(float(expectancy or 0.0), 6),
                "weight":        float(self.rt["strategy_weights"].get(sid, 0.08)),
                "status":        self.rt["strategy_status"].get(sid, "active"),
                "executions":    int(exec_counts.get(sid, 0))
            }
        return strategies

    def _update_cycle_counters(self, sid, promote_cond, rollback_cond):
        counters = self.rt["strategy_cycle_counters"]
        rec = counters.get(sid, {"promote":0, "rollback":0, "no_trade":0})
        rec["promote"]  = (rec["promote"] + 1) if promote_cond else 0
        rec["rollback"] = (rec["rollback"] + 1) if rollback_cond else 0
        rec["no_trade"] = (rec["no_trade"] + 1) if not promote_cond and not rollback_cond else 0
        counters[sid] = rec
        self.rt["strategy_cycle_counters"] = counters

    def _govern(self, strategies):
        actions=[]
        for sid, info in strategies.items():
            promote_cond  = (info["avg_pnl_short"] >= PROMOTE_PNL and info["expectancy"] >= PROMOTE_EXPECTANCY)
            rollback_cond = (info["avg_pnl_short"] <= ROLLBACK_PNL and info["expectancy"] <= ROLLBACK_EXPECTANCY)
            self._update_cycle_counters(sid, promote_cond, rollback_cond)
            streaks = self.rt["strategy_cycle_counters"].get(sid, {"promote":0,"rollback":0,"no_trade":0})

            if promote_cond and streaks["promote"] >= 2:
                new_w = min(WEIGHT_MAX, info["weight"] + WEIGHT_STEP)
                actions.append({"strategy_id": sid, "action": "promote_strategy", "from": info["weight"], "to": new_w, "reason": "profit+expectancy"})
                strategies[sid]["weight"] = new_w

            elif rollback_cond and streaks["rollback"] >= 2:
                new_w = max(WEIGHT_MIN, info["weight"] - WEIGHT_STEP)
                actions.append({"strategy_id": sid, "action": "rollback_strategy", "from": info["weight"], "to": new_w, "reason": "loss+weak_expectancy"})
                strategies[sid]["weight"] = new_w

            if info["status"] == "active" and info["executions"] == 0 and streaks["no_trade"] >= NO_TRADE_CYCLES_TO_PAUSE:
                actions.append({"strategy_id": sid, "action": "pause_strategy", "reason": "no_execution", "streak": streaks["no_trade"]})
                strategies[sid]["status"] = "paused"

            if info["status"] == "paused" and info["executions"] > 0 and info["uplift_pct"] > 0:
                actions.append({"strategy_id": sid, "action": "resume_strategy", "reason": "execution_resumed+positive_uplift"})
                strategies[sid]["status"] = "active"

            _kg({"strategy_id": sid}, "strategy_uplift_snapshot", {
                "avg_short": info["avg_pnl_short"],
                "avg_long":  info["avg_pnl_long"],
                "uplift_pct":info["uplift_pct"],
                "expectancy":info["expectancy"],
                "executions":info["executions"]
            })

        weights = self.rt["strategy_weights"]
        status  = self.rt["strategy_status"]
        for sid, info in strategies.items():
            weights[sid] = float(info["weight"])
            status[sid]  = info["status"]
        self.rt["strategy_weights"] = weights
        self.rt["strategy_status"]  = status
        self.live["runtime"] = self.rt
        _write_json(LIVE_CFG, self.live)

        if actions:
            _append_jsonl(LEARN_LOG, {"ts": _now(), "update_type": "strategy_attribution_actions", "actions": actions})
        return actions

    def run_cycle(self):
        strategies = self._aggregate_by_strategy()
        actions    = self._govern(strategies)

        sorted_sids = sorted(strategies.keys(), key=lambda k: strategies[k]["uplift_pct"], reverse=True)
        top_uplift  = {sid: strategies[sid]["uplift_pct"] for sid in sorted_sids[:5]}
        bottom_uplift = {sid: strategies[sid]["uplift_pct"] for sid in sorted_sids[-5:]} if sorted_sids else {}

        email = f"""
=== Strategy Attribution ===
Window: short={self.short}m vs long={self.long}m

Top uplift strategies (short - long):
{json.dumps(top_uplift, indent=2) if top_uplift else "None"}

Bottom uplift strategies (short - long):
{json.dumps(bottom_uplift, indent=2) if bottom_uplift else "None"}

Per-strategy metrics (sample):
{json.dumps({sid: {k: strategies[sid][k] for k in ['avg_pnl_short','avg_pnl_long','uplift_pct','expectancy','weight','status','executions']} for sid in sorted_sids[:5]}, indent=2) if sorted_sids else "None"}

Actions:
{json.dumps(actions, indent=2) if actions else "None"}
""".strip()

        summary = {
            "ts": _now(),
            "strategies": strategies,
            "actions": actions,
            "email_body": email
        }
        _append_jsonl(LEARN_LOG, {"ts": summary["ts"], "update_type":"strategy_attribution_cycle", "summary": {k:v for k,v in summary.items() if k!='email_body'}})
        return summary

# CLI
if __name__=="__main__":
    sam = StrategyAttribution()
    res = sam.run_cycle()
    print(json.dumps(res, indent=2))
    print("\n--- Email Body ---\n")
    print(res["email_body"])
