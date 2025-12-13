# src/phase_256_260.py
#
# Phases 256–260: Canary Live Capital Deployment
# - 256: Canary Flow Allocator (release 5–10% live capital to promoted strategies)
# - 257: Live Flow Monitor (track live vs paper performance)
# - 258: Auto-Scale Engine (increase flow if lift ≥5% and precision ≥0.65; fee ratio ≤0.40 optional)
# - 259: Canary Risk Guard (halt live flow if drawdown >2% or win rate <15%)
# - 260: Canary Evolution Orchestrator (daily summary, auto-promote/demote, checkpoint state)
#
# Wiring package: integration hooks for orchestrators and execution bridge.
# Autonomy-first design: no dashboards required; produces one summary file daily.

import os, json, time
from statistics import mean

# ---- Paths ----
CANARY_STATE = "logs/canary_state.json"                  # per-strategy live capital + status
CANARY_LOG = "logs/canary_performance_log.json"          # live vs paper metrics per strategy
CANARY_SUMMARY = "logs/canary_daily_summary.json"        # daily orchestrator summary
COMMAND_BUS = "logs/command_bus.json"                    # halts/restarts (reuse)
STATE_CHECKPOINT = "logs/state_checkpoint.json"          # checkpoint for continuity
SYMBOL_UNIVERSE = "logs/symbol_universe.json"            # current tradable symbols
LEVERAGE_POLICY = "logs/leverage_policy.json"            # leverage caps used for risk guard
ROI_GATES = "logs/roi_gates.json"                        # ROI thresholds for auto-tightening

def _now(): return int(time.time())
def _read_json(path, default=None): return json.load(open(path)) if os.path.exists(path) else (default if default is not None else {})
def _write_json(path, obj): os.makedirs(os.path.dirname(path), exist_ok=True); json.dump(obj, open(path, "w"), indent=2)

# ======================================================================
# 256 – Canary Flow Allocator
# ======================================================================
def canary_flow_allocator(promoted_strategies, total_capital=1.0, flow_pct=0.10):
    """
    Returns per-strategy live capital allocations for canary rollout.
    total_capital is normalized (1.0 == 100% budget); flow_pct in [0.05..0.10].
    """
    if not promoted_strategies:
        return {}
    per = round((total_capital * flow_pct) / max(1, len(promoted_strategies)), 6)
    return {s: {"live_capital": per, "status": "canary"} for s in promoted_strategies}

# ======================================================================
# 257 – Live Flow Monitor
# ======================================================================
def live_flow_monitor(perf_log):
    """
    perf_log example per strategy:
    {
      "paper_roi": 0.03,
      "live_roi": 0.05,
      "precision": 0.68,
      "win_rate": 0.26,
      "drawdown": 0.012,
      "fee_ratio": 0.38
    }
    """
    monitor = {}
    for strat, p in perf_log.items():
        lift = round(p.get("live_roi", 0.0) - p.get("paper_roi", 0.0), 6)
        monitor[strat] = {
            "paper_roi": p.get("paper_roi", 0.0),
            "live_roi": p.get("live_roi", 0.0),
            "lift": lift,
            "precision": p.get("precision", 0.0),
            "win_rate": p.get("win_rate", 0.0),
            "drawdown": p.get("drawdown", 0.0),
            "fee_ratio": p.get("fee_ratio", 1.0)
        }
    return monitor

# ======================================================================
# 258 – Auto-Scale Engine
# ======================================================================
def auto_scale_engine(monitor, current_allocations, max_flow_pct=0.40, scale_factor=1.5,
                      min_lift=0.05, min_precision=0.65, max_fee_ratio=0.40):
    """
    Scales live capital for strategies meeting promotion thresholds.
    Caps per-strategy flow at max_flow_pct of normalized capital.
    """
    updated = {}
    for strat, stats in monitor.items():
        current = current_allocations.get(strat, {}).get("live_capital", 0.0)
        ok_lift = stats["lift"] >= min_lift
        ok_prec = stats["precision"] >= min_precision
        ok_fee = stats["fee_ratio"] <= max_fee_ratio
        if ok_lift and ok_prec and ok_fee:
            new_cap = min(current * scale_factor if current > 0 else (max_flow_pct * 0.25), max_flow_pct)
            updated[strat] = {"live_capital": round(new_cap, 6), "status": "scaled_up"}
        else:
            updated[strat] = {"live_capital": current, "status": "unchanged"}
    return updated

# ======================================================================
# 259 – Canary Risk Guard
# ======================================================================
def canary_risk_guard(monitor, allocations, dd_halt=0.02, wr_halt=0.15):
    """
    Halts live flow for risky strategies; maintains allocations otherwise.
    dd_halt: daily drawdown threshold; wr_halt: win-rate halt minimum.
    """
    guarded = {}
    for strat, stats in monitor.items():
        risky = (stats["drawdown"] > dd_halt) or (stats["win_rate"] < wr_halt)
        if risky:
            guarded[strat] = {"live_capital": 0.0, "status": "halted"}
        else:
            guarded[strat] = allocations.get(strat, {"live_capital": 0.0, "status": "unknown"})
    return guarded

# ======================================================================
# 260 – Canary Evolution Orchestrator
# ======================================================================
def canary_evolution_orchestrator(promoted_candidates=None, perf_log=None,
                                  total_capital=1.0, canary_pct=0.10, max_flow_pct=0.40):
    """
    Nightly orchestrator:
    - Determines promoted strategies (from performance log or provided list)
    - Allocates canary live capital
    - Monitors live vs paper
    - Auto-scales winners; halts risky streams
    - Writes state and a single daily summary
    """
    perf_log = perf_log or _read_json(CANARY_LOG, {})
    # Promotion criteria: lift ≥5%, precision ≥0.65, fee_ratio ≤0.40
    auto_promoted = [s for s, d in perf_log.items()
                     if (d.get("live_roi", 0.0) - d.get("paper_roi", 0.0)) >= 0.05
                     and d.get("precision", 0.0) >= 0.65
                     and d.get("fee_ratio", 1.0) <= 0.40]
    promoted = list(set((promoted_candidates or []) + auto_promoted))

    allocations = canary_flow_allocator(promoted, total_capital=total_capital, flow_pct=canary_pct)
    monitor = live_flow_monitor(perf_log)
    scaled = auto_scale_engine(monitor, allocations, max_flow_pct=max_flow_pct)
    guarded = canary_risk_guard(monitor, scaled)

    # Persist state
    _write_json(CANARY_STATE, guarded)

    # Summary
    summary = {
        "ts": _now(),
        "promoted": promoted,
        "strategies_total": len(perf_log),
        "active_canaries": len([s for s in guarded if guarded[s]["live_capital"] > 0]),
        "halted": len([s for s in guarded if guarded[s]["status"] == "halted"]),
        "avg_live_roi": round(mean([v.get("live_roi", 0.0) for v in perf_log.values()]) if perf_log else 0.0, 6),
        "avg_paper_roi": round(mean([v.get("paper_roi", 0.0) for v in perf_log.values()]) if perf_log else 0.0, 6),
        "avg_precision": round(mean([v.get("precision", 0.0) for v in perf_log.values()]) if perf_log else 0.0, 6),
        "avg_win_rate": round(mean([v.get("win_rate", 0.0) for v in perf_log.values()]) if perf_log else 0.0, 6),
        "avg_drawdown": round(mean([v.get("drawdown", 0.0) for v in perf_log.values()]) if perf_log else 0.0, 6),
        "avg_fee_ratio": round(mean([v.get("fee_ratio", 1.0) for v in perf_log.values()]) if perf_log else 1.0, 6)
    }
    _write_json(CANARY_SUMMARY, summary)
    return summary

# ----------------------------------------------------------------------
# Integration Hooks for execution bridge and orchestrators
# ----------------------------------------------------------------------
def get_live_capital_for_strategy(strategy_name):
    """
    Execution bridge: fetch live capital allocation for a given strategy.
    Returns normalized capital fraction [0..1].
    """
    state = _read_json(CANARY_STATE, {})
    return state.get(strategy_name, {}).get("live_capital", 0.0)

def pre_trade_canary_gate(strategy_name):
    """
    Blocks live placement if the strategy is halted; returns mode hints.
    """
    state = _read_json(CANARY_STATE, {})
    strat = state.get(strategy_name, {"live_capital": 0.0, "status": "unknown"})
    if strat.get("status") == "halted":
        return {"block_live": True, "reason": "canary_halted"}
    live_cap = strat.get("live_capital", 0.0)
    mode = "live" if live_cap > 0 else "paper"
    return {"block_live": False, "mode": mode, "live_capital": live_cap}

def update_canary_perf(strategy_name, paper_roi, live_roi, precision, win_rate, drawdown, fee_ratio):
    """
    Append/update performance metrics for a strategy; used by the bridge after daily aggregation.
    """
    log = _read_json(CANARY_LOG, {})
    log[strategy_name] = {
        "paper_roi": float(paper_roi),
        "live_roi": float(live_roi),
        "precision": float(precision),
        "win_rate": float(win_rate),
        "drawdown": float(drawdown),
        "fee_ratio": float(fee_ratio)
    }
    _write_json(CANARY_LOG, log)
    return log[strategy_name]

def checkpoint_canary_state():
    """
    Persist a minimal checkpoint combining canary state and ROI gates for continuity.
    """
    ck = {
        "ts": _now(),
        "canary_state": _read_json(CANARY_STATE, {}),
        "roi_gates": _read_json(ROI_GATES, {}),
        "leverage_policy": _read_json(LEVERAGE_POLICY, {}),
        "symbol_universe": _read_json(SYMBOL_UNIVERSE, {})
    }
    _write_json(STATE_CHECKPOINT, ck)
    return ck

if __name__ == "__main__":
    # Demo run with synthetic performance data
    demo_perf = {
        "momentum_v2": {"paper_roi": 0.02, "live_roi": 0.08, "precision": 0.71, "win_rate": 0.29, "drawdown": 0.011, "fee_ratio": 0.36},
        "meanrev_v3": {"paper_roi": 0.03, "live_roi": 0.02, "precision": 0.62, "win_rate": 0.22, "drawdown": 0.018, "fee_ratio": 0.41},
        "venue_selector_v3": {"paper_roi": 0.01, "live_roi": 0.07, "precision": 0.68, "win_rate": 0.28, "drawdown": 0.009, "fee_ratio": 0.35}
    }
    _write_json(CANARY_LOG, demo_perf)
    summary = canary_evolution_orchestrator()
    print("Canary evolution summary:", summary)