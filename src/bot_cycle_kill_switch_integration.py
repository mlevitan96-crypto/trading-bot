# src/bot_cycle_kill_switch_integration.py
#
# v6.2 Kill-Switch Recovery Integration (Autonomous wiring into bot cycle)
# Purpose:
#   - Detect Phase82 kill-switch and protective mode states during bot cycles
#   - Automatically run Kill-Switch Recovery Orchestrator on activation
#   - Retry every 10 minutes until trading safely resumes (staged restart)
#   - Guard bot execution with profit/risk gates and runtime throttles
#
# Usage:
#   - As a daemon alongside bot_cycle.py
#   - Or import and call run_bot_cycle_with_recovery() inside your main bot loop
#
# CLI:
#   python3 src/bot_cycle_kill_switch_integration.py

import os, json, time, threading, signal, sys
from typing import Dict, Any

LIVE_CFG = "live_config.json"
LEARN_LOG = "logs/learning_updates.jsonl"
KG_LOG = "logs/knowledge_graph.jsonl"

# ---- Utilities ----

def _now() -> int:
    return int(time.time())

def _read_json(path: str, default=None):
    if not os.path.exists(path): return default
    try:
        with open(path, "r") as f: return json.load(f)
    except: return default

def _write_json(path: str, obj: Dict[str, Any]):
    tmp = path + ".tmp"
    with open(tmp, "w") as f: json.dump(obj, f, indent=2)
    os.replace(tmp, path)

def _append_jsonl(path: str, obj: Dict[str, Any]):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "a") as f: f.write(json.dumps(obj) + "\n")

def _profit_gate(verdict: Dict[str, Any]) -> bool:
    return (verdict.get("status") == "Winning"
            and float(verdict.get("expectancy", 0.5)) >= 0.55
            and float(verdict.get("avg_pnl_short", 0.0)) >= 0.0)

def _risk_gate(risk: Dict[str, Any], limits: Dict[str, Any]) -> bool:
    return not (
        float(risk.get("portfolio_exposure", 0.0)) > float(limits.get("max_exposure", 0.75)) or
        float(risk.get("max_leverage", 0.0)) > float(limits.get("max_leverage", 5.0)) or
        float(risk.get("max_drawdown_24h", 0.0)) > float(limits.get("max_drawdown_24h", 0.05))
    )

# ---- Kill-Switch Recovery Orchestrator (import or inline fallback) ----

def _run_ks_recovery() -> Dict[str, Any]:
    """
    Inline fallback: calls the orchestrator if import fails.
    If you have src/kill_switch_recovery_orchestrator.py, it will be imported and used.
    """
    try:
        # Prefer the orchestrator module if present
        from kill_switch_recovery_orchestrator import run_ks_recovery_cycle  # type: ignore
        return run_ks_recovery_cycle()
    except Exception:
        # Minimal fallback: clear stale flags and stage A restart
        live = _read_json(LIVE_CFG, default={}) or {}
        rt = live.get("runtime", {}) or {}
        live["runtime"] = rt
        rt["stale_metrics_flag"] = False
        rt["fee_diff"] = 0.0
        rt["restart_stage"] = "stage_a"
        rt["size_throttle"] = 0.25
        rt["protective_mode"] = True
        rt["kill_switch_phase82"] = False  # allow entries under protection
        rt.setdefault("allowed_symbols", [])
        _write_json(LIVE_CFG, live)
        actions = {"fallback": True, "stage": rt["restart_stage"], "size_throttle": rt["size_throttle"]}
        _append_jsonl(LEARN_LOG, {"ts": _now(), "update_type": "ks_recovery_cycle", "actions": actions})
        return {"ts": _now(), "email_body": "Fallback recovery applied (Stage A, 25% throttle).", "actions": actions}

# ---- Bot execution wrapper with recovery ----

def _get_runtime() -> Dict[str, Any]:
    live = _read_json(LIVE_CFG, default={}) or {}
    return live.get("runtime", {}) or {}

def _set_runtime(updates: Dict[str, Any]):
    live = _read_json(LIVE_CFG, default={}) or {}
    rt = live.get("runtime", {}) or {}
    rt.update(updates)
    live["runtime"] = rt
    _write_json(LIVE_CFG, live)

def _log_digest(title: str, payload: Dict[str, Any]):
    _append_jsonl(LEARN_LOG, {"ts": _now(), "update_type": title, "summary": payload})
    _append_jsonl(KG_LOG, {"ts": _now(), "subject": {"overlay": "bot_cycle_integration"}, "predicate": title, "object": payload})

def _should_run_recovery(rt: Dict[str, Any]) -> bool:
    kill_on = bool(rt.get("kill_switch_phase82", False))
    protective = bool(rt.get("protective_mode", False))
    stale = bool(rt.get("stale_metrics_flag", False))
    fee_diff = float(rt.get("fee_diff", 0.0)) >= 10.0
    last_recovery = int(rt.get("last_recovery_ts", 0))
    # Run if kill-switch on, or protective with stale/fee issues, or 10-min retry window
    return kill_on or protective or stale or fee_diff or (_now() - last_recovery >= 10 * 60)

def _apply_throttle_to_bot(rt: Dict[str, Any]) -> Dict[str, Any]:
    """
    Update bot execution parameters from runtime throttles.
    Your bot_cycle should read these to limit entries/size/allowed symbols.
    """
    return {
        "entries_enabled": not bool(rt.get("kill_switch_phase82", False)),
        "protective_mode": bool(rt.get("protective_mode", False)),
        "size_throttle": float(rt.get("size_throttle", 1.0)),
        "allowed_symbols": rt.get("allowed_symbols", []),
        "restart_stage": rt.get("restart_stage", "frozen")
    }

def _mock_bot_execute(throttle: Dict[str, Any]) -> Dict[str, Any]:
    """
    Placeholder for your real bot execution step.
    Replace with import of your bot_cycle.run() and pass throttle controls.
    """
    return {
        "executed": throttle["entries_enabled"],
        "protective_mode": throttle["protective_mode"],
        "size_throttle": throttle["size_throttle"],
        "allowed_symbols": throttle["allowed_symbols"],
        "restart_stage": throttle["restart_stage"]
    }

def run_bot_cycle_with_recovery():
    rt = _get_runtime()
    if _should_run_recovery(rt):
        rec = _run_ks_recovery()
        rt["last_recovery_ts"] = _now()
        _set_runtime(rt)
        _log_digest("kill_switch_recovery_applied", {"recovery": rec, "runtime": rt})

    # Pull latest runtime after recovery to apply throttles
    rt = _get_runtime()
    limits = (rt.get("capital_limits") or {"max_exposure": 0.75, "max_leverage": 5.0, "max_drawdown_24h": 0.05})
    # Profit/risk gate snapshot (simple placeholders; your system should supply real-time values)
    verdict = {"status": rt.get("verdict_status", "Neutral"), "expectancy": float(rt.get("verdict_expectancy", 0.5)), "avg_pnl_short": float(rt.get("verdict_avg_pnl_short", 0.0))}
    risk = {"portfolio_exposure": float(rt.get("risk_portfolio_exposure", 0.0)), "max_leverage": float(rt.get("risk_max_leverage", 0.0)), "max_drawdown_24h": float(rt.get("risk_max_drawdown_24h", 0.0))}

    gates_ok = _profit_gate(verdict) and _risk_gate(risk, limits)
    throttle = _apply_throttle_to_bot(rt)

    # If gates fail, keep protective mode and disable entries
    if not gates_ok:
        throttle["entries_enabled"] = False
        throttle["protective_mode"] = True

    # Execute bot with current throttles
    exec_result = _mock_bot_execute(throttle)

    # Log cycle summary
    _log_digest("bot_cycle_with_recovery", {"gates_ok": gates_ok, "verdict": verdict, "risk": risk, "throttle": throttle, "exec_result": exec_result})

    return {"ts": _now(), "gates_ok": gates_ok, "throttle": throttle, "exec_result": exec_result}

# ---- Daemon mode ----

_running = True

def _handle_sigterm(signum, frame):
    global _running
    _running = False

signal.signal(signal.SIGINT, _handle_sigterm)
signal.signal(signal.SIGTERM, _handle_sigterm)

def main_loop(interval_secs: int = 60):
    """
    Runs the bot cycle with autonomous recovery every `interval_secs`.
    If kill-switch is active or protective mode set, recovery retries occur every 10 minutes minimum.
    """
    _append_jsonl(LEARN_LOG, {"ts": _now(), "update_type": "bot_cycle_integration_start", "info": {"interval_secs": interval_secs}})
    while _running:
        try:
            res = run_bot_cycle_with_recovery()
        except Exception as e:
            _append_jsonl(LEARN_LOG, {"ts": _now(), "update_type": "bot_cycle_integration_error", "error": str(e)})
        time.sleep(interval_secs)
    _append_jsonl(LEARN_LOG, {"ts": _now(), "update_type": "bot_cycle_integration_stop", "info": {}})

# CLI entry
if __name__ == "__main__":
    # If invoked directly, run daemon loop (60s cadence) for rolling recovery + bot execution
    # To run once per invocation (e.g., cron), replace with `run_bot_cycle_with_recovery()`
    if len(sys.argv) > 1 and sys.argv[1] == "once":
        res = run_bot_cycle_with_recovery()
        print(json.dumps(res, indent=2))
    else:
        main_loop(interval_secs=60)
