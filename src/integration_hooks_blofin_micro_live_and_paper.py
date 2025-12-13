# src/integration_hooks_bloatfin_micro_live_and_paper.py
#
# v6.5.2 Integration Hooks: bot_cycle + signal_generator + paper/live safety harness
# Purpose:
#   - Drop-in integration for V6.5.1 patch: execution, sizing, exposure, grace windows
#   - Wire signal inversion overlay (SHORT→LONG) with regime/latency guards and propagation
#   - Provide a clean paper/live toggle with guardrails (limits, throttles, logging)
#   - Ensure paper mode stays safe and fully instrumented; live mode uses micro-size with fee-aware gating
#
# Usage:
#   - In bot_cycle.py: import and call run_entry_flow(...) for entries; honour grace_map on closes
#   - In futures_signal_generator.py: call adjust_and_propagate_signal(...)
#   - Configure paper/live in live_config.json (runtime.paper_mode: true/false), or via CLI below
#
# Files
import os, json, time, argparse
from typing import Dict, Any, Tuple

LIVE_CFG  = "live_config.json"
LEARN_LOG = "logs/learning_updates.jsonl"
KG_LOG    = "logs/knowledge_graph.jsonl"

# Utilities
def _now(): return int(time.time())
def _append_jsonl(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path,"a") as f: f.write(json.dumps(obj) + "\n")
def _read_json(path, default=None):
    if not os.path.exists(path): return default
    try:
        with open(path,"r") as f: return json.load(f)
    except: return default
def _write_json(path, obj):
    tmp=path+".tmp"
    with open(tmp,"w") as f: json.dump(obj,f,indent=2)
    os.replace(tmp, path)

# Import patch functions (assumes v6_5_integration_patch.py exists)
try:
    from v6_5_integration_patch import (
        size_after_adjustment,
        pre_entry_check,
        post_open_guard,
        adjust_signal_direction,
        propagate_signal_adjustment,
        run_fee_venue_audit,
        run_recovery_cycle,
        nightly_learning_digest,
        start_scheduler
    )
except ImportError:
    # Minimal fallback stubs (no-op) to avoid breaking; recommend ensuring v6_5_integration_patch.py is present
    def size_after_adjustment(symbol, strategy_id, base_notional, runtime): return base_notional
    def pre_entry_check(symbol, strategy_id, final_notional, pv, limits, regime, verdict, edge_hint): return True, {"symbol":symbol, "strategy_id":strategy_id, "grace_until": _now()+3, "exposure": 0.0, "cap": 0.25}
    def post_open_guard(ctx, direction, order_id): pass
    def adjust_signal_direction(signal): return signal
    def propagate_signal_adjustment(signal): pass
    def run_fee_venue_audit(): return {}
    def run_recovery_cycle(): return {}
    def nightly_learning_digest(): return {}
    def start_scheduler(interval_secs=600): pass

# Paper/live safety harness
DEFAULT_LIMITS = {"max_exposure": 0.20, "max_leverage": 3.0, "max_drawdown_24h": 0.05}
PAPER_LIMITS   = {"max_exposure": 0.10, "max_leverage": 1.0, "max_drawdown_24h": 0.03}
MICRO_LIVE_NOTIONAL_USD = 100.0  # per trade initial notional
PAPER_NOTIONAL_USD      = 50.0   # smaller to limit churn and test fees/slippage logic
ALLOWED_SYMBOLS_PAPER   = ["ETHUSDT", "SOLUSDT"]
ALLOWED_SYMBOLS_LIVE    = ["ETHUSDT", "SOLUSDT"]  # expand after digests confirm profitability

def _bus(update_type, payload):
    _append_jsonl(LEARN_LOG, {"ts": _now(), "update_type": update_type, **payload})
def _kg(subj, pred, obj):
    _append_jsonl(KG_LOG, {"ts": _now(), "subject": subj, "predicate": pred, "object": obj})

def _runtime() -> Dict[str,Any]:
    live=_read_json(LIVE_CFG, default={}) or {}
    return (live.get("runtime",{}) or {})

def _set_runtime(upd: Dict[str,Any]):
    live=_read_json(LIVE_CFG, default={}) or {}
    rt = live.get("runtime",{}) or {}
    rt.update(upd)
    live["runtime"]=rt
    _write_json(LIVE_CFG, live)

def ensure_modes_defaults():
    rt=_runtime()
    paper_mode = bool(rt.get("paper_mode", True))
    # Notional defaults
    rt.setdefault("default_notional_usd", PAPER_NOTIONAL_USD if paper_mode else MICRO_LIVE_NOTIONAL_USD)
    # Limits
    rt.setdefault("capital_limits", PAPER_LIMITS if paper_mode else DEFAULT_LIMITS)
    # Allowed symbols
    rt.setdefault("allowed_symbols_mode", ALLOWED_SYMBOLS_PAPER if paper_mode else ALLOWED_SYMBOLS_LIVE)
    # Grace map container
    rt.setdefault("grace_map", {})
    # Exposure caps enabled
    caps = rt.get("risk_caps", {}) or {}
    caps.setdefault("exposure_cap_enabled", True)
    caps.setdefault("max_exposure", (PAPER_LIMITS if paper_mode else DEFAULT_LIMITS)["max_exposure"])
    rt["risk_caps"] = caps
    _set_runtime(rt)
    _bus("modes_defaults_ensured", {"paper_mode": paper_mode, "runtime": rt})
    _kg({"overlay":"modes"}, "defaults", {"paper_mode": paper_mode, "runtime": rt})

# Integration hook: Signal generator
def adjust_and_propagate_signal(signal: Dict[str,Any]) -> Dict[str,Any]:
    """
    Call inside futures_signal_generator.py after raw signal creation.
    """
    adjusted = adjust_signal_direction(signal)
    propagate_signal_adjustment(adjusted)
    return adjusted

# Integration hook: Bot cycle entry flow
def run_entry_flow(symbol: str,
                   strategy_id: str,
                   base_notional_usd: float,
                   portfolio_value_snapshot_usd: float,
                   regime_state: str,
                   verdict_status: str,
                   expected_edge_hint: float,
                   side: str,
                   open_order_fn,
                   bot_type: str = "alpha") -> Tuple[bool, Dict[str,Any]]:
    """
    Orchestrates sizing→exposure→entry→grace window wiring.
    - open_order_fn: callable that places the order, returns order_id (str)
    Returns: (executed_ok, telemetry)
    """
    ensure_modes_defaults()
    rt=_runtime()
    
    # ═══════════════════════════════════════════════════════════════
    # STREAK FILTER GATE (Skip trades after losses)
    # ═══════════════════════════════════════════════════════════════
    try:
        from src.streak_filter import check_streak_gate
        streak_allowed, streak_reason, streak_mult = check_streak_gate(symbol, side, bot_type)
        if not streak_allowed:
            reason = {"skip": "streak_filter", "streak_reason": streak_reason, "symbol": symbol}
            _bus("entry_skipped", {"symbol": symbol, "reason": reason})
            _kg({"overlay":"entry_gate","symbol":symbol}, "streak_block", reason)
            return False, {"reason": reason, "blocked_by": "streak_filter"}
    except Exception as e:
        streak_mult = 1.0  # Non-blocking fallback
    
    # ═══════════════════════════════════════════════════════════════
    # INTELLIGENCE GATE (CoinGlass market alignment)
    # ═══════════════════════════════════════════════════════════════
    try:
        from src.intelligence_gate import intelligence_gate
        signal = {"symbol": symbol, "action": side.upper()}
        intel_allowed, intel_reason, intel_mult = intelligence_gate(signal)
        if not intel_allowed:
            reason = {"skip": "intel_gate", "intel_reason": intel_reason, "symbol": symbol}
            _bus("entry_skipped", {"symbol": symbol, "reason": reason})
            _kg({"overlay":"entry_gate","symbol":symbol}, "intel_block", reason)
            return False, {"reason": reason, "blocked_by": "intelligence_gate"}
    except Exception as e:
        intel_mult = 1.0  # Non-blocking fallback
    
    # Apply sizing multipliers from gates
    combined_mult = streak_mult * intel_mult
    adjusted_notional = base_notional_usd * combined_mult
    
    # Guard: respect allowed symbols for mode
    allowed = rt.get("allowed_symbols_mode", [])
    if allowed and symbol not in allowed:
        reason={"skip":"symbol_not_allowed_in_mode","symbol":symbol,"allowed":allowed}
        _bus("entry_skipped", {"symbol": symbol, "reason": reason})
        _kg({"overlay":"entry_gate","symbol":symbol}, "skip", reason)
        return False, {"reason": reason}

    # Final sizing after overlays and throttles (using gate-adjusted notional)
    final_notional = size_after_adjustment(symbol, strategy_id, adjusted_notional, rt)

    # Pre-entry fee/exposure gate using FINAL notional
    ok, ctx = pre_entry_check(symbol, strategy_id, final_notional, portfolio_value_snapshot_usd,
                              (rt.get("capital_limits") or DEFAULT_LIMITS), regime_state, verdict_status, expected_edge_hint)
    if not ok:
        _bus("entry_blocked", {"symbol": symbol, "strategy_id": strategy_id, "final_notional": final_notional})
        return False, {"blocked": True, "final_notional": final_notional}

    # Place order via provided function (integration point to your bridge/exchange client)
    try:
        order_id = open_order_fn(symbol=symbol, side=side, strategy_id=strategy_id, notional_usd=final_notional)
        # Direction-aware grace map
        post_open_guard(ctx, direction=side, order_id=order_id)
        _bus("entry_placed", {"symbol": symbol, "strategy_id": strategy_id, "order_id": order_id, "final_notional": final_notional})
        _kg({"overlay":"execution","symbol":symbol}, "order_opened", {"order_id": order_id, "side": side, "notional_usd": final_notional})
        return True, {"order_id": order_id, "final_notional": final_notional}
    except Exception as e:
        _bus("entry_error", {"symbol": symbol, "strategy_id": strategy_id, "error": str(e)})
        return False, {"error": str(e)}

# Integration hook: Close logic must honor grace_map (call inside your close/monitor loop)
def honor_grace_before_exposure_close(order_id: str) -> bool:
    """
    Returns True if grace window still active (i.e., DO NOT close yet).
    """
    rt=_runtime()
    gm=(rt.get("grace_map",{}) or {}).get(order_id)
    if not gm:
        return False
    still_in_grace = _now() < int(gm.get("grace_until", 0))
    if still_in_grace:
        _bus("grace_honored", {"order_id": order_id, "grace_until": gm["grace_until"]})
    return still_in_grace

# Mode management helpers
def set_paper_mode(on: bool):
    rt=_runtime()
    rt["paper_mode"]=bool(on)
    _set_runtime(rt)
    ensure_modes_defaults()
    _bus("paper_mode_set", {"paper_mode": on})
    _kg({"overlay":"modes"}, "paper_mode", {"on": on})

def set_live_mode_micro(on: bool):
    rt=_runtime()
    rt["paper_mode"]=not bool(on)
    _set_runtime(rt)
    ensure_modes_defaults()
    _bus("micro_live_mode_set", {"on": on})
    _kg({"overlay":"modes"}, "micro_live_mode", {"on": on})

# Example bridge for open_order_fn (replace with your actual exchange bridge)
def demo_open_order_fn(symbol: str, side: str, strategy_id: str, notional_usd: float) -> str:
    # This is a stub. In production, call your Blofin futures client with correct margin/leverage.
    order_id = f"{symbol}-{side}-{int(notional_usd)}-{_now()}"
    return order_id

# CLI: quick setup and smoke tests
if __name__=="__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--set-paper", action="store_true", help="Enable paper mode")
    parser.add_argument("--set-live", action="store_true", help="Enable micro-live mode")
    parser.add_argument("--scheduler", action="store_true", help="Start 10-min scheduler (fee audits + recovery + nightly digest)")
    parser.add_argument("--entry-demo", action="store_true", help="Run a demo entry flow on ETHUSDT")
    parser.add_argument("--signal-demo", action="store_true", help="Run a demo signal adjustment and propagation")
    args = parser.parse_args()

    if args.set_paper:
        set_paper_mode(True)
        print("Paper mode enabled.")
    if args.set_live:
        set_live_mode_micro(True)
        print("Micro-live mode enabled.")

    if args.scheduler:
        # Run fee audit + recovery every 10 minutes; nightly digest at 07:00 UTC
        start_scheduler(interval_secs=600)

    if args.signal_demo:
        raw_signal = {"ts": _now(), "price_ts": _now(), "symbol":"ETHUSDT", "side":"SHORT",
                      "strength":0.6, "regime":"range", "verdict_status":"Neutral"}
        adjusted = adjust_and_propagate_signal(raw_signal)
        print(json.dumps({"adjusted_signal": adjusted}, indent=2))

    if args.entry_demo:
        # Ensure mode defaults
        ensure_modes_defaults()
        rt=_runtime()
        pv_snapshot = 4000.0
        ok, telemetry = run_entry_flow(symbol="ETHUSDT",
                                       strategy_id="ema_futures",
                                       base_notional_usd=float(rt.get("default_notional_usd", 50.0)),
                                       portfolio_value_snapshot_usd=pv_snapshot,
                                       regime_state="range",
                                       verdict_status="Neutral",
                                       expected_edge_hint=0.008,  # 0.8% expected move, used for fee-aware gating
                                       side="LONG",
                                       open_order_fn=demo_open_order_fn)
        print(json.dumps({"ok": ok, "telemetry": telemetry}, indent=2))