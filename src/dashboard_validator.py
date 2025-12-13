# src/dashboard_validator.py
#
# v5.7 Dashboard Validator (Self-Auditing, Full-Area Validation, Auto-Remediation)
# Purpose:
#   - Continuously validate that dashboard data is correct and consistent across ALL areas:
#       Trades (live vs history), Orders, Positions, PnL history, Fees, Execution metrics (slippage/latency)
#   - Detect mismatches, log incidents, attempt auto re-sync, and quarantine cycles on repeated failures
#   - Provide a digest summary and knowledge-graph links for cross-layer learning
#
# Integration:
#   from src.dashboard_validator import DashboardValidator
#   dv = DashboardValidator()
#   summary = dv.run_cycle()
#   digest["email_body"] += "\n\n" + summary["email_body"]
#
# Assumptions (paths; handled gracefully if missing):
#   logs/live_trades.jsonl          # primary live trade feed shown in "Live Trades" panel
#   logs/executed_trades.jsonl      # canonical executed trades history used by attribution
#   logs/order_routing.jsonl        # order lifecycle (send/ack/fill), routes & venues
#   logs/positions_snapshot.json    # current positions view for dashboard
#   logs/pnl_history.jsonl          # aggregated pnl by cycle/interval for dashboard
#   logs/fee_events.jsonl           # fee charges attributable to trades
#   logs/learning_updates.jsonl     # global learning bus (for incidents, validator updates)
#   logs/knowledge_graph.jsonl      # causal links for audit and cross-module learning
#   live_config.json                # for validator state, retry counters, and quarantine flags
#
# Validator scope:
#   - Live vs History Trades:
#       * Every live trade must be present in executed_trades within N seconds (id-based)
#       * Per-symbol and per-strategy counts must match
#       * Field consistency for pnl_pct, est_fee_pct, side, qty, price
#   - Orders:
#       * Every filled order should have a corresponding trade record
#       * Latency/route fields present; missing critical fields flagged
#   - Positions:
#       * Sum of open positions from trades/orders matches dashboard positions snapshot
#       * No negative or NaN quantities; symbol set consistency
#   - PnL History:
#       * Aggregation of executed_trades over last interval matches pnl_history entries (within tolerance)
#       * No gaps in timestamps; monotonic index or rolling window coverage
#   - Fees:
#       * Sum of fee_events matches fee fields in executed_trades (within tolerance)
#   - Execution Metrics:
#       * Slippage and latency stats computable; missing metrics flagged (not blocking if optional)
#
# Auto-Remediation:
#   - Re-sync missing trades: copy live trade rows into executed_trades if safe, or queue reconciliation event
#   - Rebuild pnl_history buckets from executed_trades when gaps detected
#   - Recompute positions snapshot from trades when inconsistencies detected (optional safe write)
#   - Two-step retry: if same mismatch persists across 2 consecutive cycles → quarantine and escalate
#
# Quarantine Behavior:
#   - If retry_count ≥ 2 for any critical mismatch (trades/history or orders→trades linkage), set validator_quarantine flag
#   - Orchestrator should skip dependent modules until validator clears or re-sync succeeds
#
# CLI:
#   python3 src/dashboard_validator.py

import os, json, time, math
from collections import defaultdict

LOGS_DIR = "logs"
LIVE_TRADES_LOG = f"{LOGS_DIR}/live_trades.jsonl"
EXEC_TRADES_LOG = f"{LOGS_DIR}/executed_trades.jsonl"
ORDER_LOG = f"{LOGS_DIR}/order_routing.jsonl"
POSITIONS_SNAPSHOT = f"{LOGS_DIR}/positions_snapshot.json"
PNL_HISTORY_LOG = f"{LOGS_DIR}/pnl_history.jsonl"
FEE_EVENTS_LOG = f"{LOGS_DIR}/fee_events.jsonl"
LEARNING_UPDATES_LOG = f"{LOGS_DIR}/learning_updates.jsonl"
KG_LOG = f"{LOGS_DIR}/knowledge_graph.jsonl"
LIVE_CFG_PATH = "live_config.json"

# Parameters
HISTORY_MAX_DELAY_SECS = 60      # trade must appear in history within 60 seconds of live
PNL_TOLERANCE = 1e-6             # tolerance for PnL aggregation comparisons
FEE_TOLERANCE = 1e-6             # tolerance for fee aggregation comparisons
RETRY_THRESHOLD = 2              # consecutive cycles before quarantine
PNL_BUCKET_SECS = 1800           # 30-minute pnl buckets for dashboard history

def _now(): return int(time.time())

def _read_json(path, default=None):
    if not os.path.exists(path): return default
    try:
        with open(path, "r") as f: return json.load(f)
    except: return default

def _write_json(path, obj):
    tmp = path + ".tmp"
    with open(tmp, "w") as f: json.dump(obj, f, indent=2)
    os.replace(tmp, path)

def _append_jsonl(path, obj):
    with open(path, "a") as f: f.write(json.dumps(obj) + "\n")

def _read_jsonl(path, limit=100000):
    rows=[]
    if not os.path.exists(path): return rows
    with open(path,"r") as f:
        for line in f:
            line=line.strip()
            if not line: continue
            try: rows.append(json.loads(line))
            except: continue
    return rows[-limit:]

def _kg(subject, predicate, obj):
    _append_jsonl(KG_LOG, {"ts": _now(), "subject": subject, "predicate": predicate, "object": obj})

def _get_rt():
    live = _read_json(LIVE_CFG_PATH, default={}) or {}
    rt = live.get("runtime", {})
    live["runtime"] = rt
    return live, rt

def _update_rt(live, rt):
    live["runtime"] = rt
    _write_json(LIVE_CFG_PATH, live)

class DashboardValidator:
    def __init__(self):
        self.live, self.rt = _get_rt()
        # initialize validator state
        vstate = self.rt.get("dashboard_validator_state", {})
        vstate.setdefault("retry_counters", {})   # {mismatch_type: count}
        vstate.setdefault("last_incidents", {})   # {mismatch_type: ts}
        vstate.setdefault("quarantine", False)
        self.rt["dashboard_validator_state"] = vstate
        _update_rt(self.live, self.rt)

    def _validate_live_vs_history_trades(self):
        live_trades = _read_jsonl(LIVE_TRADES_LOG, 100000)
        exec_trades = _read_jsonl(EXEC_TRADES_LOG, 100000)

        # Index executed trades by id
        exec_by_id = {}
        for t in exec_trades:
            tid = t.get("trade_id") or t.get("id") or t.get("order_id")
            if tid: exec_by_id[tid] = t

        # Build symbol/strategy counts
        live_counts_sym = defaultdict(int)
        live_counts_strat = defaultdict(int)
        hist_counts_sym = defaultdict(int)
        hist_counts_strat = defaultdict(int)

        missing_ids=[]
        inconsistent_fields=[]

        now=_now()
        for lt in live_trades[-5000:]:  # recent window focus; still checks consistency broadly
            tid = lt.get("trade_id") or lt.get("id") or lt.get("order_id")
            ts = int(lt.get("ts", lt.get("timestamp", 0)) or 0)
            sym = lt.get("symbol")
            strat = lt.get("strategy_id") or lt.get("signal_family") or "unknown"

            if sym: live_counts_sym[sym]+=1
            if strat: live_counts_strat[strat]+=1

            if tid:
                ht = exec_by_id.get(tid)
                if not ht:
                    # allow delay window: if older than delay and still missing, flag
                    if ts>0 and (now - ts) > HISTORY_MAX_DELAY_SECS:
                        missing_ids.append(tid)
                    continue
                # field consistency
                def _num(x): 
                    try: return float(x)
                    except: return None
                fields = ["pnl_pct","est_fee_pct","side","qty","price","symbol"]
                for f in fields:
                    lv = lt.get(f)
                    hv = ht.get(f)
                    if f in ("pnl_pct","est_fee_pct","qty","price"):
                        lvn=_num(lv); hvn=_num(hv)
                        if lvn is None or hvn is None: 
                            continue
                        if abs(lvn - hvn) > 1e-9:
                            inconsistent_fields.append({"id":tid,"field":f,"live":lvn,"hist":hvn})
                    else:
                        if lv is not None and hv is not None and lv != hv:
                            inconsistent_fields.append({"id":tid,"field":f,"live":lv,"hist":hv})

        # Build history counts for comparison (similar recent window)
        for ht in exec_trades[-5000:]:
            sym = ht.get("symbol")
            strat = ht.get("strategy_id") or ht.get("signal_family") or "unknown"
            if sym: hist_counts_sym[sym]+=1
            if strat: hist_counts_strat[strat]+=1

        # Compare counts
        sym_mismatch=[]
        for s in set(list(live_counts_sym.keys()) + list(hist_counts_sym.keys())):
            if live_counts_sym[s] != hist_counts_sym[s]:
                sym_mismatch.append({"symbol":s, "live_count": live_counts_sym[s], "hist_count": hist_counts_sym[s]})
        strat_mismatch=[]
        for st in set(list(live_counts_strat.keys()) + list(hist_counts_strat.keys())):
            if live_counts_strat[st] != hist_counts_strat[st]:
                strat_mismatch.append({"strategy":st, "live_count": live_counts_strat[st], "hist_count": hist_counts_strat[st]})

        return {
            "missing_ids": missing_ids,
            "sym_count_mismatch": sym_mismatch,
            "strat_count_mismatch": strat_mismatch,
            "field_inconsistencies": inconsistent_fields,
            "live_count_recent": sum(live_counts_sym.values()),
            "hist_count_recent": sum(hist_counts_sym.values())
        }

    def _validate_orders_linkage(self):
        orders = _read_jsonl(ORDER_LOG, 100000)
        exec_trades = _read_jsonl(EXEC_TRADES_LOG, 100000)
        exec_ids = set()
        for t in exec_trades:
            tid = t.get("trade_id") or t.get("id") or t.get("order_id")
            if tid: exec_ids.add(tid)

        missing_fills=[]
        missing_latency_fields=[]
        for o in orders[-20000:]:
            oid = o.get("order_id")
            filled = o.get("fill_ts") or o.get("filled_qty")
            # Check filled orders have trade record
            if filled and oid and (oid not in exec_ids):
                missing_fills.append(oid)
            # Latency fields presence
            if oid:
                if o.get("send_ts") is None or o.get("ack_ts") is None or o.get("fill_ts") is None:
                    missing_latency_fields.append(oid)

        return {
            "missing_filled_order_trade": missing_fills,
            "missing_latency_fields": missing_latency_fields
        }

    def _validate_positions_snapshot(self):
        pos = _read_json(POSITIONS_SNAPSHOT, default={}) or {}
        exec_trades = _read_jsonl(EXEC_TRADES_LOG, 100000)
        # Recompute position quantities per symbol from trades (simple net position proxy)
        net_qty = defaultdict(float)
        for t in exec_trades[-50000:]:
            sym = t.get("symbol")
            side = (t.get("side") or "").lower()
            qty = t.get("qty")
            try: q = float(qty if qty is not None else 0.0)
            except: q = 0.0
            if not sym: continue
            if side == "buy" or side == "long":
                net_qty[sym] += q
            elif side == "sell" or side == "short":
                net_qty[sym] -= q

        pos_inconsistencies=[]
        pos_symbols = set((pos or {}).keys())
        for sym in set(list(pos_symbols) + list(net_qty.keys())):
            dash_q = 0.0
            try: dash_q = float(pos.get(sym, {}).get("qty", 0.0) if isinstance(pos.get(sym), dict) else pos.get(sym, 0.0))
            except: dash_q = 0.0
            recomputed = round(net_qty.get(sym, 0.0), 12)
            if abs(dash_q - recomputed) > 1e-9:
                pos_inconsistencies.append({"symbol":sym, "dashboard_qty": dash_q, "recomputed_qty": recomputed})

        invalid_entries=[]
        for sym, pdata in (pos or {}).items():
            q = pdata.get("qty") if isinstance(pdata, dict) else pdata
            try:
                qf = float(q)
                if math.isnan(qf) or qf < 0 and str(pdata).lower().startswith("long"):
                    invalid_entries.append({"symbol":sym, "qty":q})
            except:
                invalid_entries.append({"symbol":sym, "qty":q})

        return {
            "pos_inconsistencies": pos_inconsistencies,
            "invalid_entries": invalid_entries,
            "dashboard_symbols": list(pos_symbols)
        }

    def _validate_pnl_history(self):
        pnl_hist = _read_jsonl(PNL_HISTORY_LOG, 100000)
        exec_trades = _read_jsonl(EXEC_TRADES_LOG, 100000)

        # Aggregate trades into buckets by PNL_BUCKET_SECS
        buckets = defaultdict(lambda: {"pnl_sum":0.0, "n":0})
        for t in exec_trades[-100000:]:
            ts = int(t.get("ts", 0))
            if ts <= 0: continue
            bucket = ts - (ts % PNL_BUCKET_SECS)
            try:
                pnl = float(t.get("pnl_usd", t.get("pnl", 0.0)))
                buckets[bucket]["pnl_sum"] += pnl
                buckets[bucket]["n"] += 1
            except: continue

        # Compare with pnl_history entries
        hist_buckets = {}
        for ph in pnl_hist:
            ts = int(ph.get("ts", 0))
            if ts <= 0: continue
            bucket = ts - (ts % PNL_BUCKET_SECS)
            pnl_val = float(ph.get("pnl_usd", ph.get("pnl", 0.0)))
            hist_buckets[bucket] = pnl_val

        mismatches=[]
        for b, data in buckets.items():
            computed = data["pnl_sum"]
            recorded = hist_buckets.get(b, 0.0)
            if abs(computed - recorded) > PNL_TOLERANCE:
                mismatches.append({"bucket_ts": b, "computed": round(computed,6), "recorded": round(recorded,6)})

        gaps=[]
        sorted_hist = sorted(hist_buckets.keys())
        for i in range(1, len(sorted_hist)):
            if sorted_hist[i] - sorted_hist[i-1] > PNL_BUCKET_SECS*2:
                gaps.append({"from": sorted_hist[i-1], "to": sorted_hist[i]})

        return {
            "pnl_mismatches": mismatches,
            "gaps": gaps
        }

    def _validate_fees(self):
        fee_events = _read_jsonl(FEE_EVENTS_LOG, 100000)
        exec_trades = _read_jsonl(EXEC_TRADES_LOG, 100000)

        # Sum fees from fee_events
        fee_sum_events = 0.0
        for fe in fee_events:
            try: fee_sum_events += float(fe.get("fee_usd", fe.get("fee", 0.0)))
            except: continue

        # Sum fees from executed_trades
        fee_sum_trades = 0.0
        for t in exec_trades:
            try: fee_sum_trades += float(t.get("fee_usd", t.get("fee", 0.0)))
            except: continue

        mismatch = abs(fee_sum_events - fee_sum_trades) > FEE_TOLERANCE

        return {
            "fee_sum_events": round(fee_sum_events, 6),
            "fee_sum_trades": round(fee_sum_trades, 6),
            "mismatch": mismatch
        }

    def _validate_execution_metrics(self):
        exec_trades = _read_jsonl(EXEC_TRADES_LOG, 100000)
        missing_slippage = 0
        missing_latency = 0
        for t in exec_trades[-10000:]:
            if t.get("slippage_bps") is None:
                missing_slippage += 1
            if t.get("latency_ms") is None:
                missing_latency += 1

        return {
            "missing_slippage_count": missing_slippage,
            "missing_latency_count": missing_latency,
            "total_recent_trades": min(10000, len(exec_trades))
        }

    def _attempt_remediation(self, validation_results):
        remediations=[]
        vstate = self.rt["dashboard_validator_state"]
        retry_counters = vstate["retry_counters"]

        # 1) Missing live→history trades: copy to executed_trades if safe
        live_hist = validation_results["live_vs_history"]
        missing_ids = live_hist["missing_ids"]
        if missing_ids:
            mismatch_type = "live_history_missing_ids"
            retry_counters[mismatch_type] = retry_counters.get(mismatch_type, 0) + 1
            if retry_counters[mismatch_type] < RETRY_THRESHOLD:
                # Attempt to copy missing trades from live_trades to executed_trades
                live_trades = _read_jsonl(LIVE_TRADES_LOG, 100000)
                live_by_id = {}
                for lt in live_trades:
                    tid = lt.get("trade_id") or lt.get("id") or lt.get("order_id")
                    if tid: live_by_id[tid] = lt
                copied=0
                for mid in missing_ids[:100]:  # limit batch
                    lt = live_by_id.get(mid)
                    if lt:
                        _append_jsonl(EXEC_TRADES_LOG, lt)
                        copied += 1
                remediations.append({"type": mismatch_type, "action":"copy_missing_trades", "copied": copied})
            else:
                # Quarantine
                vstate["quarantine"] = True
                remediations.append({"type": mismatch_type, "action":"quarantine", "reason":"retry_threshold_exceeded"})
        else:
            # Clear retry counter if no missing ids
            retry_counters.pop("live_history_missing_ids", None)

        # 2) Orders linkage: missing filled orders→trades
        orders_linkage = validation_results["orders_linkage"]
        missing_fills = orders_linkage["missing_filled_order_trade"]
        if missing_fills:
            mismatch_type = "orders_missing_fills"
            retry_counters[mismatch_type] = retry_counters.get(mismatch_type, 0) + 1
            if retry_counters[mismatch_type] >= RETRY_THRESHOLD:
                vstate["quarantine"] = True
                remediations.append({"type": mismatch_type, "action":"quarantine", "reason":"retry_threshold_exceeded"})
            else:
                remediations.append({"type": mismatch_type, "action":"log_incident", "count": len(missing_fills)})
        else:
            retry_counters.pop("orders_missing_fills", None)

        # 3) Positions snapshot inconsistencies: recompute and optionally overwrite
        pos_check = validation_results["positions"]
        pos_inconsistencies = pos_check["pos_inconsistencies"]
        if pos_inconsistencies:
            mismatch_type = "positions_inconsistent"
            retry_counters[mismatch_type] = retry_counters.get(mismatch_type, 0) + 1
            if retry_counters[mismatch_type] < RETRY_THRESHOLD:
                # Rebuild positions snapshot from trades
                exec_trades = _read_jsonl(EXEC_TRADES_LOG, 100000)
                net_qty = defaultdict(float)
                for t in exec_trades[-50000:]:
                    sym = t.get("symbol")
                    side = (t.get("side") or "").lower()
                    qty = t.get("qty")
                    try: q = float(qty if qty is not None else 0.0)
                    except: q = 0.0
                    if not sym: continue
                    if side == "buy" or side == "long":
                        net_qty[sym] += q
                    elif side == "sell" or side == "short":
                        net_qty[sym] -= q
                new_pos = {sym: {"qty": round(q,12), "recomputed": True} for sym, q in net_qty.items()}
                _write_json(POSITIONS_SNAPSHOT, new_pos)
                remediations.append({"type": mismatch_type, "action":"rebuild_positions_snapshot", "symbols": len(new_pos)})
            else:
                vstate["quarantine"] = True
                remediations.append({"type": mismatch_type, "action":"quarantine", "reason":"retry_threshold_exceeded"})
        else:
            retry_counters.pop("positions_inconsistent", None)

        # 4) PnL history gaps/mismatches: rebuild buckets
        pnl_check = validation_results["pnl_history"]
        pnl_mismatches = pnl_check["pnl_mismatches"]
        gaps = pnl_check["gaps"]
        if pnl_mismatches or gaps:
            mismatch_type = "pnl_history_gaps_mismatches"
            retry_counters[mismatch_type] = retry_counters.get(mismatch_type, 0) + 1
            if retry_counters[mismatch_type] < RETRY_THRESHOLD:
                # Rebuild pnl_history from executed_trades
                exec_trades = _read_jsonl(EXEC_TRADES_LOG, 100000)
                buckets = defaultdict(lambda: {"pnl_sum":0.0, "n":0})
                for t in exec_trades[-100000:]:
                    ts = int(t.get("ts", 0))
                    if ts <= 0: continue
                    bucket = ts - (ts % PNL_BUCKET_SECS)
                    try:
                        pnl = float(t.get("pnl_usd", t.get("pnl", 0.0)))
                        buckets[bucket]["pnl_sum"] += pnl
                        buckets[bucket]["n"] += 1
                    except: continue
                # Overwrite pnl_history
                with open(PNL_HISTORY_LOG, "w") as f:
                    for bucket in sorted(buckets.keys()):
                        f.write(json.dumps({"ts": bucket, "pnl_usd": round(buckets[bucket]["pnl_sum"],6), "n": buckets[bucket]["n"]}) + "\n")
                remediations.append({"type": mismatch_type, "action":"rebuild_pnl_history", "buckets": len(buckets)})
            else:
                vstate["quarantine"] = True
                remediations.append({"type": mismatch_type, "action":"quarantine", "reason":"retry_threshold_exceeded"})
        else:
            retry_counters.pop("pnl_history_gaps_mismatches", None)

        # Update state
        vstate["retry_counters"] = retry_counters
        self.rt["dashboard_validator_state"] = vstate
        _update_rt(self.live, self.rt)

        return remediations

    def run_cycle(self):
        ts = _now()
        vstate = self.rt.get("dashboard_validator_state", {})
        quarantine = vstate.get("quarantine", False)

        # Run all validations
        live_hist = self._validate_live_vs_history_trades()
        orders_link = self._validate_orders_linkage()
        positions = self._validate_positions_snapshot()
        pnl_hist = self._validate_pnl_history()
        fees = self._validate_fees()
        exec_metrics = self._validate_execution_metrics()

        validation_results = {
            "live_vs_history": live_hist,
            "orders_linkage": orders_link,
            "positions": positions,
            "pnl_history": pnl_hist,
            "fees": fees,
            "execution_metrics": exec_metrics
        }

        # Attempt remediation
        remediations = self._attempt_remediation(validation_results)

        # Determine overall health
        critical_issues = (
            len(live_hist["missing_ids"]) > 50 or
            len(orders_link["missing_filled_order_trade"]) > 20 or
            len(positions["pos_inconsistencies"]) > 5 or
            len(pnl_hist["pnl_mismatches"]) > 10 or
            fees["mismatch"]
        )

        health = "🟢 HEALTHY" if not critical_issues else "🟡 DEGRADED" if not quarantine else "🔴 QUARANTINED"

        # Email body
        email_body = f"""
=== Dashboard Validator ===
Health: {health}
Quarantine: {"YES" if quarantine else "NO"}

Live vs History Trades:
  - Missing IDs: {len(live_hist["missing_ids"])}
  - Symbol Count Mismatches: {len(live_hist["sym_count_mismatch"])}
  - Strategy Count Mismatches: {len(live_hist["strat_count_mismatch"])}
  - Field Inconsistencies: {len(live_hist["field_inconsistencies"])}
  - Live Count (recent): {live_hist["live_count_recent"]}
  - History Count (recent): {live_hist["hist_count_recent"]}

Orders Linkage:
  - Missing Filled Order→Trade: {len(orders_link["missing_filled_order_trade"])}
  - Missing Latency Fields: {len(orders_link["missing_latency_fields"])}

Positions Snapshot:
  - Inconsistencies: {len(positions["pos_inconsistencies"])}
  - Invalid Entries: {len(positions["invalid_entries"])}
  - Dashboard Symbols: {len(positions["dashboard_symbols"])}

PnL History:
  - Mismatches: {len(pnl_hist["pnl_mismatches"])}
  - Gaps: {len(pnl_hist["gaps"])}

Fees:
  - Events Sum: ${fees["fee_sum_events"]}
  - Trades Sum: ${fees["fee_sum_trades"]}
  - Mismatch: {fees["mismatch"]}

Execution Metrics:
  - Missing Slippage: {exec_metrics["missing_slippage_count"]}/{exec_metrics["total_recent_trades"]}
  - Missing Latency: {exec_metrics["missing_latency_count"]}/{exec_metrics["total_recent_trades"]}

Remediations: {len(remediations)}
"""
        if remediations:
            email_body += "\nRemediation Actions:\n"
            for r in remediations:
                email_body += f"  - [{r['type']}] {r['action']}\n"

        # Publish to learning_updates and knowledge_graph
        summary = {
            "ts": ts,
            "health": health,
            "quarantine": quarantine,
            "validation_results": validation_results,
            "remediations": remediations,
            "critical_issues": critical_issues,
            "email_body": email_body
        }

        _append_jsonl(LEARNING_UPDATES_LOG, {
            "ts": ts,
            "update_type": "dashboard_validator_cycle",
            "summary": {k: v for k, v in summary.items() if k != "email_body"}
        })

        _kg({"validator": "dashboard"}, "validation_cycle", {
            "health": health,
            "quarantine": quarantine,
            "critical_issues": critical_issues,
            "remediation_count": len(remediations)
        })

        return summary

if __name__ == "__main__":
    dv = DashboardValidator()
    result = dv.run_cycle()
    print(result["email_body"])
    print(f"\nHealth: {result['health']}")
    print(f"Quarantine: {result['quarantine']}")
    print(f"Remediations: {len(result['remediations'])}")
