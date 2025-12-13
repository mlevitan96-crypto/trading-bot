# src/phase_181_190.py
#
# Phases 181–190: Profit Loop, Champion–Challenger, Execution Alpha, Dashboard
# - 181: PnL Ledger v2
# - 182: Profit Loop Controller
# - 183: Champion–Challenger Router
# - 184: Experiment Harness
# - 185: Smart Order Router v3 (limit-first, dynamic offsets)
# - 186: Maker Rebate Arb
# - 187: Slippage Guard v2 (L2-aware scaffold)
# - 188: Latency-Aware Executor (TTL/offset adaptation)
# - 189: Profit Protection Rules (drawdown halts, auto-tune risk)
# - 190: Operator Profit Dashboard
#
# Integration hooks:
# - Feed from existing execution bridge (alpha_to_execution_adapter.py).
# - Use execution_gates() for final gate approval.
# - Nightly orchestrator: run profit loop checks, champion promotion, and dashboard generation.

import os, json, time, math
from statistics import mean, stdev

# ---- Paths ----
TRADES_LOG = "logs/trades_futures.json"                 # { "history": [ {symbol, roi, fees, slippage_bp, ts, venue, order_type, size, pnl_net} ] }
EXECUTION_RESULTS = "logs/executed_orders.jsonl"        # bridge decisions
PNL_LEDGER = "logs/pnl_ledger_v2.json"                  # aggregated pnl
PROFIT_LOOP = "logs/profit_loop_controller.json"        # targets & actions
CHAMPION_CHALLENGER = "logs/champion_challenger_router.json"
EXPERIMENTS = "logs/experiment_harness.json"
SMART_ROUTER_CFG = "logs/smart_order_router_v3.json"
MAKER_REBATE_MAP = "logs/maker_rebates.json"            # { venue: {symbol: maker_rebate_bp} }
SLIPPAGE_GUARD = "logs/slippage_guard_v2.json"
LATENCY_PROFILE = "logs/venue_latency_profile.json"     # { venue: {avg_ms, spread_bp_avg} }
PROFIT_PROTECTION = "logs/profit_protection_rules.json"
PROFIT_DASH = "logs/operator_profit_dashboard.json"

# Existing gates
from src.execution_gates import execution_gates, mark_trade

def _now(): return int(time.time())
def _read_json(path, default=None): return json.load(open(path)) if os.path.exists(path) else (default if default is not None else {})
def _write_json(path, obj): os.makedirs(os.path.dirname(path), exist_ok=True); json.dump(obj, open(path, "w"), indent=2)
def _append_jsonl(path, obj): os.makedirs(os.path.dirname(path), exist_ok=True); open(path, "a").write(json.dumps(obj) + "\n")
def _read_jsonl(path): return [json.loads(l) for l in open(path)] if os.path.exists(path) else []

# ======================================================================
# 181 – PnL Ledger v2
# Aggregates realized PnL, fees, slippage per symbol and globally.
# ======================================================================
def pnl_ledger_v2():
    trades = _read_json(TRADES_LOG, {"history": []}).get("history", [])
    by_sym = {}
    for t in trades[-10000:]:
        sym = t.get("symbol"); roi = t.get("roi", 0.0); fees = t.get("fees", 0.0)
        slip = t.get("slippage_bp", 0.0); pnl_net = t.get("pnl_net", roi - fees)
        if sym is None: continue
        rec = by_sym.setdefault(sym, {"n": 0, "pnl_net": 0.0, "fees": 0.0, "slippage_bp": []})
        rec["n"] += 1; rec["pnl_net"] += pnl_net; rec["fees"] += fees; rec["slippage_bp"].append(slip)
    ledger = {"ts": _now(), "symbols": {}, "global": {"pnl_net": 0.0, "fees": 0.0}}
    for sym, r in by_sym.items():
        avg_slip = mean(r["slippage_bp"]) if r["slippage_bp"] else 0.0
        ledger["symbols"][sym] = {"n": r["n"], "pnl_net": round(r["pnl_net"], 6), "fees": round(r["fees"], 6), "avg_slippage_bp": round(avg_slip, 3)}
        ledger["global"]["pnl_net"] += r["pnl_net"]; ledger["global"]["fees"] += r["fees"]
    ledger["global"]["pnl_net"] = round(ledger["global"]["pnl_net"], 6); ledger["global"]["fees"] = round(ledger["global"]["fees"], 6)
    _write_json(PNL_LEDGER, ledger)
    return ledger

# ======================================================================
# 182 – Profit Loop Controller
# Targets: fee ratio, win rate, net PnL. Emits actions: throttle/scale/pause.
# ======================================================================
def profit_loop_controller(targets=None):
    targets = targets or {"fee_ratio_max": 0.4, "win_rate_min": 0.25, "pnl_daily_min": 0.0}
    trades = _read_json(TRADES_LOG, {"history": []}).get("history", [])
    by_day = {}
    for t in trades[-2000:]:
        day = time.strftime("%Y-%m-%d", time.localtime(t.get("ts", _now())))
        by_day.setdefault(day, []).append(t)
    today = time.strftime("%Y-%m-%d", time.localtime(_now()))
    day_trades = by_day.get(today, [])
    wins = sum(1 for x in day_trades if (x.get("roi", 0.0) - x.get("fees", 0.0)) > 0)
    fee_ratio = (sum(x.get("fees", 0.0) for x in day_trades) / max(1e-6, abs(sum(x.get("roi", 0.0) for x in day_trades)))) if day_trades else 0.0
    win_rate = (wins / len(day_trades)) if day_trades else 0.0
    pnl_net = sum(x.get("roi", 0.0) - x.get("fees", 0.0) for x in day_trades)
    action = "scale" if (fee_ratio <= targets["fee_ratio_max"] and win_rate >= targets["win_rate_min"] and pnl_net >= targets["pnl_daily_min"]) else "throttle" if win_rate >= 0.15 else "pause"
    ctrl = {"ts": _now(), "today": today, "fee_ratio": round(fee_ratio, 4), "win_rate": round(win_rate, 4), "pnl_net": round(pnl_net, 6), "action": action, "targets": targets}
    _write_json(PROFIT_LOOP, ctrl)
    return ctrl

# ======================================================================
# 183 – Champion–Challenger Router
# Routes a portion of orders to challengers under strict risk for A/B testing.
# ======================================================================
def champion_challenger_router(symbol_stats, challenger_ratio=0.2):
    # symbol_stats: {symbol: {precision, expectancy, samples}}
    routing = {}
    for sym, s in symbol_stats.items():
        champion_flow = 1.0 - challenger_ratio if s.get("precision", 0.6) >= 0.6 else 1.0 - (challenger_ratio/2)
        routing[sym] = {"champion_flow": round(champion_flow, 3), "challenger_flow": round(1.0 - champion_flow, 3)}
    _write_json(CHAMPION_CHALLENGER, {"ts": _now(), "routing": routing})
    return routing

# ======================================================================
# 184 – Experiment Harness
# Tracks experiments and computes lift; flags promotion-ready challengers.
# ======================================================================
def experiment_harness():
    res = _read_jsonl(EXECUTION_RESULTS)
    by_sym = {}
    for r in res[-5000:]:
        sym = r.get("symbol"); decision = r.get("gate_decision", {})
        is_challenger = r.get("experiment", "champion") == "challenger"
        win = decision.get("approved") and (decision.get("realized_roi", 0.0) - decision.get("fees", 0.0) > 0)
        bucket = "challenger" if is_challenger else "champion"
        rec = by_sym.setdefault(sym, {"champion": {"wins": 0, "n": 0}, "challenger": {"wins": 0, "n": 0}})
        rec[bucket]["n"] += 1; rec[bucket]["wins"] += 1 if win else 0
    lift_flags = {}
    for sym, rec in by_sym.items():
        ch_prec = (rec["champion"]["wins"] / max(1, rec["champion"]["n"]))
        cl_prec = (rec["challenger"]["wins"] / max(1, rec["challenger"]["n"]))
        lift = cl_prec - ch_prec
        lift_flags[sym] = {"champion_prec": round(ch_prec, 4), "challenger_prec": round(cl_prec, 4), "lift": round(lift, 4), "promote": (cl_prec >= ch_prec + 0.05 and rec["challenger"]["n"] >= 30)}
    _write_json(EXPERIMENTS, {"ts": _now(), "experiments": lift_flags})
    return lift_flags

# ======================================================================
# 185 – Smart Order Router v3
# Limit-first, dynamic offset, TTL, reprice logic, maker-preference when feasible.
# ======================================================================
def smart_order_router_v3(symbol, spread_bp, venue, fee_ratio, prefer_maker=True):
    # Base offset: tighter for low spread, wider for high fee_ratio
    base_offset_bp = 0.5 if spread_bp <= 6 else 1.0
    fee_penalty_bp = 0.5 if fee_ratio > 0.6 else 0.0
    offset_bp = min(3.0, base_offset_bp + fee_penalty_bp)
    ttl_sec = 10 if spread_bp <= 6 else 20
    post_only = prefer_maker and spread_bp >= 4
    cfg = {"order_type": "limit", "offset_bp": round(offset_bp, 2), "ttl_sec": ttl_sec, "post_only": post_only, "venue": venue}
    _write_json(SMART_ROUTER_CFG, cfg)
    return cfg

# ======================================================================
# 186 – Maker Rebate Arb
# Chooses venue/pair combos with best maker rebates; computes net fee expectation.
# ======================================================================
def maker_rebate_arb(symbol, candidate_venues, taker_fee_bp=5.0, maker_fee_bp=2.0):
    rebates = _read_json(MAKER_REBATE_MAP, {})
    scores = []
    for v in candidate_venues:
        rb_bp = rebates.get(v, {}).get(symbol, 0.0)
        net_maker_bp = maker_fee_bp - rb_bp
        net_taker_bp = taker_fee_bp
        # Prefer maker if net_maker <= net_taker
        prefer_maker = net_maker_bp <= net_taker_bp
        scores.append({"venue": v, "maker_net_bp": net_maker_bp, "taker_net_bp": net_taker_bp, "prefer_maker": prefer_maker})
    best = min(scores, key=lambda x: x["maker_net_bp"] if x["prefer_maker"] else x["taker_net_bp"]) if scores else {"venue": candidate_venues[0] if candidate_venues else "default", "prefer_maker": True}
    return {"chosen": best, "scores": scores}

# ======================================================================
# 187 – Slippage Guard v2
# Blocks trades when recent slippage exceeds threshold; scaffold for L2/L3 checks.
# ======================================================================
def slippage_guard_v2(symbol, recent_slippage_bp, threshold_bp=6.0):
    blocked = recent_slippage_bp > threshold_bp
    state = {"blocked": blocked, "threshold_bp": threshold_bp, "recent_slippage_bp": recent_slippage_bp}
    _write_json(SLIPPAGE_GUARD, {"ts": _now(), symbol: state})
    return state

# ======================================================================
# 188 – Latency-Aware Executor
# Adjusts TTL and offset based on venue latency and spread dynamics.
# ======================================================================
def latency_aware_executor(symbol, venue, spread_bp):
    prof = _read_json(LATENCY_PROFILE, {}).get(venue, {"avg_ms": 150, "spread_bp_avg": 6})
    avg_ms = prof.get("avg_ms", 150)
    # Longer latency -> longer TTL and slightly wider offsets
    ttl = 10 if avg_ms < 120 else 15 if avg_ms < 200 else 20
    offset_bp = 0.6 if spread_bp <= 6 else 1.2
    return {"ttl_sec": ttl, "offset_bp": offset_bp}

# ======================================================================
# 189 – Profit Protection Rules
# Drawdown halts, risk auto-tune, cap reductions for weak symbols.
# ======================================================================
def profit_protection_rules():
    trades = _read_json(TRADES_LOG, {"history": []}).get("history", [])
    by_sym = {}
    for t in trades[-2000:]:
        sym = t.get("symbol"); pnl = t.get("roi", 0.0) - t.get("fees", 0.0)
        by_sym.setdefault(sym, []).append(pnl)
    decisions = {}
    for sym, pnl_list in by_sym.items():
        if not pnl_list: continue
        win_rate = sum(1 for p in pnl_list if p > 0) / len(pnl_list)
        dd = min(pnl_list)
        action = "normal"
        if dd < -0.03 or win_rate < 0.3:
            action = "pause"
        elif dd < -0.015 or win_rate < 0.45:
            action = "throttle"
        decisions[sym] = {"win_rate": round(win_rate, 4), "drawdown": round(dd, 6), "action": action}
    _write_json(PROFIT_PROTECTION, {"ts": _now(), "symbols": decisions})
    return decisions

# ======================================================================
# 190 – Operator Profit Dashboard
# Summarizes targets, actions, PnL, experiments, execution quality.
# ======================================================================
def operator_profit_dashboard():
    pnl = _read_json(PNL_LEDGER, {})
    loop = _read_json(PROFIT_LOOP, {})
    exp = _read_json(EXPERIMENTS, {})
    router = _read_json(SMART_ROUTER_CFG, {})
    protect = _read_json(PROFIT_PROTECTION, {})
    dash = {
        "ts": _now(),
        "pnl_ledger": pnl,
        "profit_loop": loop,
        "experiments": exp,
        "smart_router": router,
        "protection": protect
    }
    _write_json(PROFIT_DASH, dash)
    return dash

# ======================================================================
# Integration Hook: Execution Bridge Augmentation
# Use these helpers before calling execution_gates() in alpha_to_execution_adapter.py
# ======================================================================
def pre_execution_controls(symbol, venue, spread_bp, recent_slippage_bp, fee_ratio, confidence):
    # Slippage block
    slip = slippage_guard_v2(symbol, recent_slippage_bp)
    if slip["blocked"]:
        return {"blocked": True, "reason": "slippage_high", "slippage": slip}
    # Maker venue preference
    venue_choice = maker_rebate_arb(symbol, [venue], taker_fee_bp=5.0, maker_fee_bp=2.0)
    # Smart routing and latency tuning
    router_cfg = smart_order_router_v3(symbol, spread_bp, venue_choice["chosen"]["venue"], fee_ratio, prefer_maker=venue_choice["chosen"]["prefer_maker"])
    latency_cfg = latency_aware_executor(symbol, venue_choice["chosen"]["venue"], spread_bp)
    # Size multiplier from profit loop action
    loop = _read_json(PROFIT_LOOP, {"action": "throttle"}).get("action", "throttle")
    size_mult = 1.0 if loop == "scale" else 0.8 if loop == "throttle" else 0.5
    return {
        "blocked": False,
        "venue": venue_choice["chosen"]["venue"],
        "order_type": "limit",
        "offset_bp": max(router_cfg["offset_bp"], latency_cfg["offset_bp"]),
        "ttl_sec": max(router_cfg["ttl_sec"], latency_cfg["ttl_sec"]),
        "post_only": router_cfg["post_only"],
        "size_mult": size_mult
    }

# ======================================================================
# Nightly Orchestrator: Profit Loop + Experiments + Dashboard
# ======================================================================
def run_phase_181_190_nightly():
    ledger = pnl_ledger_v2()
    loop = profit_loop_controller()
    protect = profit_protection_rules()
    exp = experiment_harness()
    dash = operator_profit_dashboard()
    summary = {"ts": _now(), "pnl_global": ledger.get("global", {}), "loop_action": loop.get("action"), "retentions": len(protect.get("symbols", {})), "experiments": len(exp)}
    _write_json("logs/orchestrator_181_190.json", summary)
    return summary

# ---- Example bridge usage ----
# In alpha_to_execution_adapter.py, before execution_gates():
# ctl = pre_execution_controls(sym, venue="default_venue", spread_bp=current_spread_bp, recent_slippage_bp=recent_slip_bp, fee_ratio=current_fee_ratio, confidence=confidence)
# if ctl["blocked"]:
#     append_symbol_audit(sym, {"reason": ctl["reason"], "slippage": ctl["slippage"]})
#     continue
# decision = execution_gates(symbol=sym, predicted_roi=expected_roi, mtf_confirmed=True, quality_score=confidence)
# if decision.get("approved"):
#     # place_order with limit and offset from ctl
#     place_order(sym, order_type="limit", size=size * ctl["size_mult"], offset_bp=ctl["offset_bp"], ttl_sec=ctl["ttl_sec"], post_only=ctl["post_only"])
#     mark_trade()

if __name__ == "__main__":
    # Run nightly orchestration when executed directly
    run_phase_181_190_nightly()