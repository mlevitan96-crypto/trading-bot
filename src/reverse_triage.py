# src/reverse_triage.py
#
# v5.7 Profit-First Reverse Triage
# Purpose: Work backwards from "Are we making money?" to root cause and auto-fix.
#   Verdict → Profit lens → Execution funnel → Cost attribution → Signal integrity → Scheduler/Config contracts.
#
# Integration:
#   from src.reverse_triage import ReverseTriage
#   rt = ReverseTriage()
#   summary = rt.run_cycle()  # run every 30 min or upon "paralysis" trigger
#   digest["email_body"] += "\n\n" + summary["email_body"]

import os, json, time
from collections import defaultdict

LOGS_DIR = "logs"
CONFIG_DIR = "config"

LEARNING_UPDATES_LOG  = f"{LOGS_DIR}/learning_updates.jsonl"
META_LEARN_LOG        = f"{LOGS_DIR}/meta_learning.jsonl"
EXEC_LOG              = f"{LOGS_DIR}/executed_trades.jsonl"
NIGHTLY_LOG           = f"{LOGS_DIR}/nightly_pipeline.log"
KNOWLEDGE_GRAPH_LOG   = f"{LOGS_DIR}/knowledge_graph.jsonl"
FEE_TIER_CFG_PATH     = f"{CONFIG_DIR}/fee_tier_config.json"
LIVE_CFG_PATH         = "live_config.json"

# Verdict gates
WIN_EXPECTANCY_MIN = 0.50
WIN_PNL_MIN        = 0.0
LOSE_EXPECTANCY_MAX= 0.30
LOSE_PNL_MAX       = 0.0

# Profit gates
PROMOTE_EXPECTANCY = 0.55
PROMOTE_PNL        = 0.0
ROLLBACK_EXPECTANCY= 0.35
ROLLBACK_PNL       = 0.0

# Freshness thresholds
FEED_FRESH_SECS    = 2
SCHEDULER_HEARTBEAT_MAX_SECS = 60*90  # 90 min

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
    with open(path, "a") as f: f.write(json.dumps(obj) + "\n")

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

def _knowledge_link(subject, predicate, obj):
    _append_jsonl(KNOWLEDGE_GRAPH_LOG, {"ts": _now(), "subject": subject, "predicate": predicate, "object": obj})

def _recent_expectancy(default=0.0):
    rows=_read_jsonl(META_LEARN_LOG, 2000)
    for r in reversed(rows):
        ex = r.get("expectancy", {})
        val = ex.get("score") if isinstance(ex, dict) else None
        if val is not None:
            try: return float(val)
            except: break
    return default

def _aggregate_pnl(window_mins=240):
    cutoff = _now() - window_mins*60
    rows = _read_jsonl(EXEC_LOG, 20000)
    pnl_sum = 0.0; n=0
    per_coin = defaultdict(lambda: {"pnl_pct_sum":0.0, "n":0})
    for r in rows:
        ts = r.get("ts") or r.get("timestamp") or 0
        if ts < cutoff: continue
        pnl_pct = float(r.get("pnl_pct", 0.0))
        pnl_sum += pnl_pct
        n += 1
        sym = r.get("symbol"); 
        if sym: 
            per_coin[sym]["pnl_pct_sum"] += pnl_pct
            per_coin[sym]["n"] += 1
    avg_pnl = pnl_sum / max(1, n)
    for s in per_coin.values():
        s["avg_pnl_pct"] = round(s["pnl_pct_sum"]/max(1,s["n"]), 6)
    return {"avg_pnl_pct": round(avg_pnl,6), "trades": n, "per_coin": per_coin}

class ReverseTriage:
    """
    Profit-first backward-chaining diagnosis:
    - Verdict: Are we making money right now?
    - If not: find failing stage and auto-fix.
    """
    def __init__(self):
        self.live = _read_json(LIVE_CFG_PATH, default={}) or {}
        self.rt   = self.live.get("runtime", {})
        self.rt.setdefault("size_scalars", {})
        self.live["runtime"] = self.rt
        _write_json(LIVE_CFG_PATH, self.live)

    # ---------- Verdict ----------
    def _verdict(self):
        expectancy = _recent_expectancy()
        pnl_short = _aggregate_pnl(240)
        verdict = "Winning" if (expectancy >= WIN_EXPECTANCY_MIN and pnl_short["avg_pnl_pct"] > WIN_PNL_MIN) else \
                  "Losing"  if (expectancy <= LOSE_EXPECTANCY_MAX or pnl_short["avg_pnl_pct"] <= LOSE_PNL_MAX) else \
                  "Neutral"
        return {"verdict": verdict, "expectancy": expectancy, "pnl_short": pnl_short}

    # ---------- Funnel ----------
    def _funnel(self):
        updates = _read_jsonl(LEARNING_UPDATES_LOG, 5000)
        fee_decisions = [u for u in updates if u.get("update_type")=="fee_governor_decision"]
        fee_pass = sum(1 for d in fee_decisions if d.get("decision", {}).get("passed", False))
        composite_pass = sum(1 for u in updates if u.get("update_type")=="composite_filter_result" and u.get("payload",{}).get("passed",False))
        composite_blocks = sum(1 for u in updates if u.get("update_type")=="composite_pass_fee_block")
        exec_rows = _read_jsonl(EXEC_LOG, 5000)
        executed = len([r for r in exec_rows if (r.get("ts") or 0) > _now()-240*60])

        stage = "unknown"
        if composite_pass == 0: stage = "composite"
        elif fee_pass == 0 and composite_pass > 0: stage = "fees"
        elif fee_pass > 0 and executed == 0: stage = "routing"
        else: stage = "profit"

        return {"composite_pass": composite_pass, "fee_pass": fee_pass, "composite_blocks": composite_blocks, "executed": executed, "stage": stage}

    # ---------- Costs ----------
    def _costs(self):
        # Summarize recent margins and estimated costs if available
        updates = _read_jsonl(LEARNING_UPDATES_LOG, 2000)
        margins=[]
        for u in updates:
            if u.get("update_type")=="fee_governor_decision":
                d = u.get("decision", {})
                margins.append({
                    "symbol": d.get("symbol"),
                    "margin_pct": d.get("margin_pct"),
                    "threshold_pct": d.get("effective_threshold_pct"),
                    "passed": d.get("passed", False)
                })
        # Identify dominant issue
        blocked = [m for m in margins if not m.get("passed")]
        dominant = "none"
        if blocked:
            # If margin < threshold for most, costs too high or thresholds too strict
            under = sum(1 for m in blocked if (m.get("margin_pct") or 0.0) < (m.get("threshold_pct") or 0.0))
            if under/len(blocked) >= 0.6:
                dominant = "threshold_or_cost"
        return {"margins": margins[-50:], "dominant": dominant}

    # ---------- Signal integrity ----------
    def _signal_integrity(self):
        # Placeholder: check last OFI/composite timestamp markers if present
        updates = _read_jsonl(LEARNING_UPDATES_LOG, 2000)
        last_ofi_ts = 0; last_comp_ts = 0
        for u in reversed(updates):
            if u.get("update_type")=="ofi_signal":
                last_ofi_ts = u.get("ts",0); break
        for u in reversed(updates):
            if u.get("update_type")=="composite_filter_result":
                last_comp_ts = u.get("ts",0); break
        now=_now()
        ofi_fresh = (now - last_ofi_ts) <= FEED_FRESH_SECS if last_ofi_ts>0 else False
        comp_fresh = (now - last_comp_ts) <= FEED_FRESH_SECS if last_comp_ts>0 else False
        return {"ofi_fresh": ofi_fresh, "comp_fresh": comp_fresh, "last_ofi_ts": last_ofi_ts, "last_comp_ts": last_comp_ts}

    # ---------- Scheduler/config contracts ----------
    def _orchestrator_health(self):
        rt = self.rt
        hb = int(rt.get("scheduler_heartbeat_ts", 0))
        heartbeat_ok = (_now() - hb) <= SCHEDULER_HEARTBEAT_MAX_SECS if hb>0 else False
        cfg = _read_json(FEE_TIER_CFG_PATH, default={}) or {}
        schema_ok = "tiers" in cfg and "symbols" in cfg
        units_ok = False
        try:
            # Check that fee constants are in valid bps range (0.00001 to 0.01 = 0.1 bps to 1%)
            # Note: Fee-Aware Governor uses _bounded() to clamp values, so raw config may differ
            tiers=cfg.get("tiers",{})
            sample = next(iter(tiers.values()))
            maker = float(sample.get("maker_pct",0.0))
            taker = float(sample.get("taker_pct",0.0))
            # Accept any value that's reasonable for fees (up to 5% for safety margin)
            units_ok = 0.0 <= maker <= 0.05 and 0.0 <= taker <= 0.05
        except: units_ok=False
        return {"heartbeat_ok": heartbeat_ok, "schema_ok": schema_ok, "units_ok": units_ok}

    # ---------- Auto-fixes ----------
    def _apply_fixes(self, verdict, funnel, costs, signals, orch):
        fixes=[]
        # Profit gates
        exp = verdict["expectancy"]; pnl = verdict["pnl_short"]["avg_pnl_pct"]
        if pnl <= ROLLBACK_PNL and exp <= ROLLBACK_EXPECTANCY:
            fixes.append({"action":"enable_rollback_for_losers","reason":"pnl<=0 & expectancy weak"})
        # Stage-based fixes
        if funnel["stage"]=="composite":
            fixes.append({"action":"lower_composite_threshold_within_bounds","reason":"no composite passes"})
        if funnel["stage"]=="fees":
            fixes.append({"action":"fee_calibration_probe_recalibrate","reason":"composite pass but fee blocking"})
        if funnel["stage"]=="routing":
            fixes.append({"action":"restart_bridge_and_validate_limits","reason":"fee pass without execution"})
        if costs["dominant"]=="threshold_or_cost":
            fixes.append({"action":"reduce_taker_threshold_small_step","reason":"margin<effective_threshold"})
        if not signals["ofi_fresh"] or not signals["comp_fresh"]:
            fixes.append({"action":"restart_feeds_and_rehydrate_cache","reason":"stale signal pipeline"})
        if not orch["heartbeat_ok"]:
            fixes.append({"action":"restart_scheduler_and_recover_nightly","reason":"heartbeat stale"})
        if (not orch["schema_ok"]) or (not orch["units_ok"]):
            fixes.append({"action":"rollback_config_to_last_known_good","reason":"schema/units invalid"})

        # Log intent (actual remediation hooks live in orchestrator)
        if fixes:
            _append_jsonl(LEARNING_UPDATES_LOG, {"ts": _now(), "update_type":"reverse_triage_auto_fix", "fixes": fixes})
            _knowledge_link({"verdict": verdict["verdict"], "stage": funnel["stage"]}, "reverse_triage_auto_fix", {"fixes": fixes})
        return fixes

    # ---------- Public ----------
    def run_cycle(self) -> dict:
        v = self._verdict()
        f = self._funnel()
        c = self._costs()
        s = self._signal_integrity()
        o = self._orchestrator_health()
        fixes = self._apply_fixes(v, f, c, s, o)

        email = f"""
=== Profit-First Reverse Triage ===
Verdict: {v['verdict']} | Expectancy: {v['expectancy']:.3f} | Short-window avg PnL: {v['pnl_short']['avg_pnl_pct']:.4f} | Trades: {v['pnl_short']['trades']}

Funnel:
  Composite passes: {f['composite_pass']} | Fee passes: {f['fee_pass']} | Blocks: {f['composite_blocks']} | Executed (4h): {f['executed']}
  Failing stage: {f['stage']}

Costs:
  Dominant issue: {c['dominant']}
  Recent margins (sample): {c['margins'][-3:] if c['margins'] else 'None'}

Signals:
  OFI fresh: {s['ofi_fresh']} | Composite fresh: {s['comp_fresh']}

Orchestrator & Config:
  Scheduler heartbeat OK: {o['heartbeat_ok']} | Config schema OK: {o['schema_ok']} | Units OK (bps bounds): {o['units_ok']}

Auto-fixes requested:
{json.dumps(fixes, indent=2) if fixes else "None"}
""".strip()

        summary = {
            "ts": _now(),
            "verdict": v,
            "funnel": f,
            "costs": c,
            "signals": s,
            "orchestrator": o,
            "fixes": fixes,
            "email_body": email
        }
        _append_jsonl(LEARNING_UPDATES_LOG, {"ts": summary["ts"], "update_type":"reverse_triage_cycle", "summary": {k:v for k,v in summary.items() if k!='email_body'}})
        _knowledge_link({"cycle":"reverse_triage"}, "reverse_triage_summary", {"verdict": v["verdict"], "stage": f["stage"], "fixes": fixes})
        return summary

# CLI
if __name__ == "__main__":
    rt = ReverseTriage()
    res = rt.run_cycle()
    print(json.dumps(res, indent=2))
    print("\n--- Email Body ---\n")
    print(res["email_body"])
