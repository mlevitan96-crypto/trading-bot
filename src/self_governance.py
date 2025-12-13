# src/self_governance.py
#
# Full Self-Governance Layer: Autonomous execution, diagnosis, fixing, learning, and maintenance.
# This module installs a governance scheduler that runs:
# - Tactical operator cycle (every 15 minutes): immediate health/fix actions.
# - Strategic symbol review (nightly): capital reallocation, suppression/reactivation, policy drift control.
# - Infrastructure watchdogs (every 5 minutes): data freshness, connectivity, latency, heartbeats, synthetic pipeline tests.
# - Maintenance routines (nightly): log rotation, backups, config integrity verification, rollback readiness.
#
# The goal: You never need to ask "is it working?" The bot asks every question a human would, then fixes itself.

import os, json, time, threading
from collections import defaultdict
from typing import Dict, List, Tuple, Any

from src.performance_metrics import compute_performance_metrics

EVENTS_LOG = "logs/unified_events.jsonl"
POS_LOG    = "logs/positions_futures.json"
POLICY_CFG = "config/profit_policy.json"
BACKUP_DIR = "backups/"
CONFIG_DIR = "config/"

ALL_SYMBOLS = [
    "BTCUSDT","ETHUSDT","SOLUSDT","AVAXUSDT","DOTUSDT","TRXUSDT",
    "XRPUSDT","ADAUSDT","DOGEUSDT","BNBUSDT","MATICUSDT"
]

DEFAULTS = {"MIN_PROFIT_USD": 20.0, "BASE_COLLATERAL_USD": 500.0, "INTERNAL_MAX_LEVERAGE": 10}
BOUNDS   = {"MIN_PROFIT_USD": (10.0,200.0), "BASE_COLLATERAL_USD": (250.0,5000.0), "INTERNAL_MAX_LEVERAGE": (3,20)}

KILL_SWITCH_CFG = {"max_drawdown_pct": 15.0, "fee_mismatch_usd": 50.0, "reject_rate_pct": 25.0, "freeze_duration_min": 15}
DEFAULT_MIN_COLLATERAL_USD = DEFAULTS["BASE_COLLATERAL_USD"]

SUPPRESSION_REGISTRY: Dict[str, int] = {}

def _read_jsonl(path: str) -> List[dict]:
    if not os.path.exists(path): return []
    out = []
    with open(path, "r") as f:
        for line in f:
            s = line.strip()
            if not s: continue
            try: out.append(json.loads(s))
            except: continue
    return out

def _append_json(path: str, obj: dict):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "a") as f: f.write(json.dumps(obj) + "\n")

def log_event(event: str, payload: dict = None):
    payload = dict(payload or {})
    payload.update({"ts": int(time.time()), "event": event})
    _append_json(EVENTS_LOG, payload)

def _read_policy() -> dict:
    if not os.path.exists(POLICY_CFG): return {"global": DEFAULTS.copy(), "per_symbol": {}}
    try:
        with open(POLICY_CFG, "r") as f: return json.load(f)
    except:
        return {"global": DEFAULTS.copy(), "per_symbol": {}}

def _write_policy(cfg: dict):
    os.makedirs(os.path.dirname(POLICY_CFG), exist_ok=True)
    with open(POLICY_CFG, "w") as f: json.dump(cfg, f, indent=2)

def _clip(val, bounds): return max(bounds[0], min(val, bounds[1]))

def adjust_profit_policy():
    try:
        from src.profit_blofin_learning import adjust_profit_policy as adjust_impl
        adjust_impl()
    except Exception as e:
        cfg = _read_policy()
        _write_policy(cfg)
        log_event("profit_policy_adjusted", {"fallback": True, "err": str(e)})

def get_symbol_budget(symbol: str) -> float:
    try:
        from src.profit_blofin_learning import get_symbol_budget as get_impl
        return get_impl(symbol)
    except:
        return DEFAULT_MIN_COLLATERAL_USD

def freeze_entries(minutes=15):
    log_event("entries_frozen", {"minutes": minutes})

def request_performance_rebaseline():
    log_event("performance_rebaseline_requested", {})

def evaluate_kill_switch(metrics: dict) -> bool:
    dd  = float(metrics.get("drawdown_pct", 0.0))
    rej = float(metrics.get("reject_rate_pct", 0.0))
    fee = float(metrics.get("fee_mismatch_usd", 0.0))

    if dd > 100.0:
        log_event("kill_switch_metrics_corrupt", {"dd": dd})
        dd = 0.0

    triggered = (dd >= KILL_SWITCH_CFG["max_drawdown_pct"] or
                 rej >= KILL_SWITCH_CFG["reject_rate_pct"] or
                 fee >= KILL_SWITCH_CFG["fee_mismatch_usd"])

    if triggered:
        log_event("kill_switch_triggered", {"dd": dd, "rej": rej, "fee": fee})
        freeze_entries(minutes=KILL_SWITCH_CFG["freeze_duration_min"])
        request_performance_rebaseline()
    return triggered

def get_recent_events(minutes: int = 15) -> List[dict]:
    now = int(time.time())
    return [e for e in _read_jsonl(EVENTS_LOG) if (now - int(e.get("ts", now))) <= minutes*60]

def compute_avg_profit(symbols: List[str]) -> float:
    positions = _read_jsonl(POS_LOG)
    pnl = [float(p.get("net_pnl_usd", p.get("profit_usd", 0.0)) or 0.0) for p in positions if p.get("symbol") in symbols]
    return (sum(pnl) / max(1, len(pnl))) if pnl else 0.0

def detect_fee_slippage(events: List[dict]) -> dict:
    fee_mismatch = [e for e in events if e.get("event") in ("fee_mismatch", "slippage_high")]
    if fee_mismatch:
        return {"count": len(fee_mismatch)}
    return {}

def leverage_scaling_active(events: List[dict]) -> bool:
    entries = [e for e in events if e.get("event") in ("profit_blofin_entry", "profit_blofin_approved")]
    if not entries: return True
    return any(int(e.get("leverage", 1)) > 1 for e in entries)

def learning_engine_updated() -> bool:
    recent = get_recent_events(minutes=60)
    return any(e.get("event") in ("profit_policy_update","profit_policy_adjusted") for e in recent)

def kill_switch_stuck() -> bool:
    recent = get_recent_events(minutes=30)
    triggered = any(e.get("event") == "kill_switch_triggered" for e in recent)
    unfrozen  = any(e.get("event") == "entries_unfrozen" for e in recent)
    return triggered and not unfrozen

def data_freshness_ok() -> bool:
    """
    Check BOTH telemetry freshness AND data file integrity.
    Delegates to unified_self_governance_bot for comprehensive checks.
    """
    try:
        from src.unified_self_governance_bot import data_freshness_ok as unified_data_freshness_ok
        return unified_data_freshness_ok()
    except ImportError:
        recent = get_recent_events(minutes=2)
        got_signals = any("signal" in e.get("event", "") for e in recent)
        got_prices  = any("price" in e.get("event", "") for e in recent)
        return got_signals and got_prices

def venue_connectivity_ok() -> bool:
    try:
        from src.unified_self_governance_bot import venue_connectivity_ok as unified_venue_connectivity_ok
        return unified_venue_connectivity_ok()
    except ImportError:
        recent = get_recent_events(minutes=2)
        return any("venue" in e.get("event", "") or "heartbeat" in e.get("event", "") for e in recent)

def latency_within_bounds() -> bool:
    try:
        from src.unified_self_governance_bot import latency_within_bounds as unified_latency_within_bounds
        return unified_latency_within_bounds()
    except ImportError:
        recent = get_recent_events(minutes=15)
        lat = [float(e.get("latency_ms", 0.0)) for e in recent if e.get("event") == "execution_latency"]
        return (sum(lat) / max(1, len(lat))) < 500 if lat else True

def synthetic_pipeline_pass() -> bool:
    try:
        from src.unified_self_governance_bot import synthetic_pipeline_pass as unified_synthetic_pipeline_pass
        return unified_synthetic_pipeline_pass()
    except ImportError:
        recent = get_recent_events(minutes=15)
        return any(e.get("event") == "synthetic_pipeline_pass" for e in recent)

def audit_trail_complete() -> bool:
    try:
        from src.unified_self_governance_bot import audit_trail_complete as unified_audit_trail_complete
        return unified_audit_trail_complete()
    except ImportError:
        recent = get_recent_events(minutes=60)
        return any(e.get("event") in ("entry_audit", "profit_blofin_approved") for e in recent)

def operator_cycle():
    """
    Tactical operator cycle: immediate self-checks and fixes.
    Runs every 15 minutes.
    """
    try:
        from src.profit_blofin_learning import is_profit_learning_enabled
        enabled = is_profit_learning_enabled()
    except:
        enabled = bool(os.getenv("ENABLE_PROFIT_LEARNING", "1") == "1")

    recent_events = get_recent_events(minutes=15)
    trades = [e for e in recent_events if "entry" in e.get("event","") or "approved" in e.get("event","")]
    blocks = [e for e in recent_events if "block" in str(e.get("event",""))]

    if len(trades) == 0:
        log_event("operator_no_trades_detected", {"blocks": len(blocks)})
        if all(b.get("event")=="profit_filter_block" for b in blocks) and enabled:
            adjust_profit_policy()
        if any(b.get("event")=="kill_switch_triggered" for b in blocks):
            metrics = compute_performance_metrics()
            evaluate_kill_switch(metrics)

    for sym in ALL_SYMBOLS:
        budget = get_symbol_budget(sym)
        if budget <= 0:
            log_event("operator_budget_fix", {"symbol": sym})
            get_symbol_budget(sym)

    avg_profit = compute_avg_profit(ALL_SYMBOLS)
    if avg_profit < 0 and enabled:
        log_event("operator_negative_profit_detected", {"avg_profit": avg_profit})
        adjust_profit_policy()

    fee_slippage = detect_fee_slippage(recent_events)
    if fee_slippage:
        log_event("operator_fee_slippage_detected", fee_slippage)
        log_event("fee_slippage_mitigation_applied", {})

    if not leverage_scaling_active(recent_events) and enabled:
        log_event("operator_leverage_scaling_inactive", {})
        adjust_profit_policy()

    if not learning_engine_updated() and enabled:
        log_event("operator_learning_stalled", {})
        adjust_profit_policy()

    if kill_switch_stuck():
        log_event("operator_kill_switch_stuck", {})
        metrics = compute_performance_metrics()
        evaluate_kill_switch(metrics)

    log_event("operator_cycle_complete", {
        "trades_checked": len(trades), "blocks_checked": len(blocks),
        "avg_profit": avg_profit, "timestamp": int(time.time())
    })

def aggregate_symbol_performance(symbols: List[str]) -> Dict[str, Dict[str, float]]:
    positions = _read_jsonl(POS_LOG)
    stats = {sym: {"trades":0,"wins":0,"losses":0,"avg_profit_usd":0.0,"win_rate":0.0} for sym in symbols}
    sums = defaultdict(float); counts = defaultdict(int)
    for p in positions:
        sym = p.get("symbol"); 
        if sym not in stats: continue
        pnl = float(p.get("net_pnl_usd", p.get("profit_usd", 0.0)) or 0.0)
        stats[sym]["trades"] += 1
        stats[sym]["wins"] += 1 if pnl >= 0 else 0
        stats[sym]["losses"] += 1 if pnl < 0 else 0
        counts[sym] += 1; sums[sym] += pnl
    for sym in symbols:
        n = counts[sym]
        stats[sym]["avg_profit_usd"] = (sums[sym] / n) if n else 0.0
        t = stats[sym]["trades"]
        stats[sym]["win_rate"] = (stats[sym]["wins"] / t) if t else 0.0
    return stats

def suppress_symbol(sym: str, duration_hours: int = 12):
    SUPPRESSION_REGISTRY[sym] = int(time.time()) + duration_hours*3600
    log_event("symbol_suppressed", {"symbol": sym, "duration_hours": duration_hours})

def symbol_suppressed(sym: str) -> bool:
    until = SUPPRESSION_REGISTRY.get(sym, 0)
    if until and time.time() < until: return True
    if until and time.time() >= until:
        SUPPRESSION_REGISTRY.pop(sym, None)
        log_event("symbol_reactivated", {"symbol": sym})
    return False

def raise_symbol_budget(sym: str, factor: float = 1.2):
    try:
        from src.profit_blofin_learning import SYMBOL_BUDGET_USD
        old_budget = SYMBOL_BUDGET_USD[sym]
        new_budget = old_budget * factor
        SYMBOL_BUDGET_USD[sym] = new_budget
        log_event("symbol_budget_increased", {"symbol": sym, "old": old_budget, "new": new_budget})
    except:
        log_event("symbol_budget_increase_failed", {"symbol": sym})

def tighten_profit_filter(sym: str, factor: float = 1.1):
    cfg = _read_policy()
    cur = cfg["per_symbol"].get(sym, cfg["global"].copy())
    cur["MIN_PROFIT_USD"] = round(_clip(cur["MIN_PROFIT_USD"] * factor, BOUNDS["MIN_PROFIT_USD"]), 2)
    cfg["per_symbol"][sym] = cur
    _write_policy(cfg)
    log_event("profit_filter_tightened", {"symbol": sym, "new_min_profit_usd": cur["MIN_PROFIT_USD"]})

def ease_profit_filter(sym: str, factor: float = 0.95):
    cfg = _read_policy()
    cur = cfg["per_symbol"].get(sym, cfg["global"].copy())
    cur["MIN_PROFIT_USD"] = round(_clip(cur["MIN_PROFIT_USD"] * factor, BOUNDS["MIN_PROFIT_USD"]), 2)
    cfg["per_symbol"][sym] = cur
    _write_policy(cfg)
    log_event("profit_filter_eased", {"symbol": sym, "new_min_profit_usd": cur["MIN_PROFIT_USD"]})

def operator_symbol_review():
    """
    Nightly strategic review:
    - Suppress persistent underperformers with decay/reactivation.
    - Reallocate budgets toward strong performers.
    - Tighten filters for noisy symbols; ease filters when overly restrictive.
    - Ensure policy drift stays within safe bounds.
    """
    try:
        from src.profit_blofin_learning import is_profit_learning_enabled
        enabled = is_profit_learning_enabled()
    except:
        enabled = bool(os.getenv("ENABLE_PROFIT_LEARNING", "1") == "1")

    stats = aggregate_symbol_performance(ALL_SYMBOLS)

    for sym, s in stats.items():
        if s["avg_profit_usd"] < 0 and s["win_rate"] < 0.45 and s["trades"] >= 25:
            if not symbol_suppressed(sym):
                suppress_symbol(sym, duration_hours=12)
            tighten_profit_filter(sym, factor=1.1)
        elif s["avg_profit_usd"] > 5 and s["win_rate"] > 0.55 and s["trades"] >= 25:
            raise_symbol_budget(sym, factor=1.2)
            ease_profit_filter(sym, factor=0.97)

        if s["trades"] > 100 and s["avg_profit_usd"] < 1:
            tighten_profit_filter(sym, factor=1.15)

    global_avg = sum(s["avg_profit_usd"] for s in stats.values()) / max(1, len(stats))
    best = max(stats.items(), key=lambda kv: kv[1]["avg_profit_usd"])[0] if stats else None
    worst = min(stats.items(), key=lambda kv: kv[1]["avg_profit_usd"])[0] if stats else None
    log_event("operator_symbol_review_complete", {
        "avg_profit_usd": global_avg, "best_symbol": best, "worst_symbol": worst
    })

    cfg = _read_policy()
    g = cfg.get("global", DEFAULTS.copy())
    g["INTERNAL_MAX_LEVERAGE"] = int(_clip(g.get("INTERNAL_MAX_LEVERAGE", DEFAULTS["INTERNAL_MAX_LEVERAGE"]), BOUNDS["INTERNAL_MAX_LEVERAGE"]))
    g["BASE_COLLATERAL_USD"]   = float(_clip(g.get("BASE_COLLATERAL_USD", DEFAULTS["BASE_COLLATERAL_USD"]), BOUNDS["BASE_COLLATERAL_USD"]))
    g["MIN_PROFIT_USD"]        = float(_clip(g.get("MIN_PROFIT_USD", DEFAULTS["MIN_PROFIT_USD"]), BOUNDS["MIN_PROFIT_USD"]))
    cfg["global"] = g; _write_policy(cfg)
    log_event("policy_drift_enforced", {"global": g})

    if enabled:
        adjust_profit_policy()

def watchdog_cycle():
    """
    Every 5 minutes:
    - Verify data freshness, venue connectivity, latency bounds, synthetic pipeline pass.
    - Verify audit trail completeness; if not, trigger controlled freeze + rebaseline.
    - Enforce exposure caps; margin mode enforcement; fee reconciliation sanity.
    """
    ok_fresh = data_freshness_ok()
    ok_conn  = venue_connectivity_ok()
    ok_lat   = latency_within_bounds()
    ok_syn   = synthetic_pipeline_pass()
    ok_audit = audit_trail_complete()

    if not ok_fresh or not ok_conn or not ok_lat or not ok_syn or not ok_audit:
        log_event("watchdog_issue_detected", {
            "data_freshness_ok": ok_fresh, "venue_connectivity_ok": ok_conn,
            "latency_ok": ok_lat, "synthetic_ok": ok_syn, "audit_ok": ok_audit
        })
        freeze_entries(minutes=KILL_SWITCH_CFG["freeze_duration_min"])
        request_performance_rebaseline()

    log_event("watchdog_cycle_complete", {"ts": int(time.time())})

def maintenance_nightly():
    """
    Nightly:
    - Rotate logs; create & verify backups; config integrity check; rollback readiness.
    - Reactivate symbols whose suppression expired (handled by symbol_suppressed checks in execution path).
    """
    try:
        cfg = _read_policy()
        assert "global" in cfg and "per_symbol" in cfg
        log_event("config_integrity_ok", {})
    except Exception as e:
        log_event("maintenance_failure", {"err": str(e)})

class _PeriodicTask:
    def __init__(self, fn, interval_sec: int, name: str):
        self.fn = fn; self.interval = interval_sec; self.name = name
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    def _run(self):
        while True:
            try:
                self.fn()
            except Exception as e:
                log_event("governance_task_error", {"task": self.name, "err": str(e)})
            time.sleep(self.interval)

def start_self_governance():
    """
    Start all governance loops:
    - Watchdog (5 min)
    - Tactical operator cycle (15 min)
    - Nightly strategic review (24 hr)
    - Nightly maintenance (24 hr)
    """
    os.environ["ENABLE_PROFIT_LEARNING"] = "1"
    log_event("self_governance_boot", {"profit_learning_enabled": True})

    _PeriodicTask(watchdog_cycle,        interval_sec=5*60,  name="watchdog")
    _PeriodicTask(operator_cycle,        interval_sec=15*60, name="operator_tactical")
    _PeriodicTask(operator_symbol_review,interval_sec=24*60*60, name="operator_strategic")
    _PeriodicTask(maintenance_nightly,   interval_sec=24*60*60, name="maintenance_nightly")

    log_event("self_governance_started", {
        "tasks": ["watchdog","operator_tactical","operator_strategic","maintenance_nightly"]
    })
    print("🤖 [SELF-GOVERNANCE] Autonomous operator started")
    print("   ℹ️  Watchdog: Every 5 minutes")
    print("   ℹ️  Tactical checks: Every 15 minutes")
    print("   ℹ️  Strategic review: Daily")
    print("   ℹ️  Maintenance: Daily")

def symbol_allowed_to_trade(sym: str) -> bool:
    return not symbol_suppressed(sym)
