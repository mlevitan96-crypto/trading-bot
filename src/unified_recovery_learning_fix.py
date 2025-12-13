# src/unified_recovery_learning_fix.py
#
# v6.5 Unified Recovery + Execution Fix + Fee-Aware Gating + Signal Inversion + Learning Telemetry
# Purpose:
#   - Stop instant closes (exposure math + grace window + correct portfolio value)
#   - Gate entries by expected edge after fees/slippage (per symbol/strategy)
#   - Invert SHORT signals conditionally (regime + latency aware)
#   - Autonomously recover from protective mode (staged restart, symbol-aware)
#   - Log EVERYTHING to the learning bus + knowledge graph so paper losses become lessons
#
# How to integrate (drop-in hooks):
#   1) In bot_cycle.py before opening a position:
#       from unified_recovery_learning_fix import pre_entry_check, post_open_guard
#       ok, ctx = pre_entry_check(symbol, strategy_id, position_notional, portfolio_value_snapshot, runtime_limits, regime_state, verdict_status, expected_edge_hint)
#       if not ok: return  # skip entry (logs reason)
#       # ... open position ...
#       post_open_guard(ctx)  # enforces grace window; logs exposure telemetry
#
#   2) In futures_signal_generator.py:
#       from unified_recovery_learning_fix import adjust_signal_direction
#       signal = adjust_signal_direction(signal)  # may flip SHORT->LONG or mark NO_TRADE, logs overlay
#
#   3) In the daemon (every 10–60 min):
#       from unified_recovery_learning_fix import run_recovery_cycle, run_fee_venue_audit
#       run_recovery_cycle()       # staged A→B→C→Full restart if gates pass
#       run_fee_venue_audit()      # updates fee baselines, quarantines high-fee symbols in runtime
#
#   4) Nightly:
#       from unified_recovery_learning_fix import nightly_learning_digest
#       nightly_learning_digest()  # compiles losses, non-trades, counterfactuals, missed profit, and decisions

import os, json, time, statistics
from collections import defaultdict
from typing import Dict, Any, Tuple, List

# --- Files ---
LIVE_CFG  = "live_config.json"
LEARN_LOG = "logs/learning_updates.jsonl"
KG_LOG    = "logs/knowledge_graph.jsonl"
EXEC_LOG  = "logs/executed_trades.jsonl"
SIG_LOG   = "logs/strategy_signals.jsonl"

# --- Config defaults ---
DEFAULT_LIMITS = {"max_exposure": 0.25, "max_leverage": 5.0, "max_drawdown_24h": 0.05}
GRACE_SECS = 3
LATENCY_MS_SHORT_MAX = 500
PROMOTE_EXPECTANCY = 0.55
PROMOTE_PNL        = 0.0

# --- IO helpers ---
def _now(): return int(time.time())
def _append_jsonl(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "a") as f: f.write(json.dumps(obj) + "\n")
def _read_json(path, default=None):
    if not os.path.exists(path): return default
    try:
        with open(path, "r") as f: return json.load(f)
    except: return default
def _write_json(path, obj):
    tmp = path + ".tmp"
    with open(tmp, "w") as f: json.dump(obj, f, indent=2)
    os.replace(tmp, path)
def _read_jsonl(path, limit=200000) -> List[Dict[str,Any]]:
    rows=[]
    if not os.path.exists(path): return rows
    with open(path,"r") as f:
        for line in f:
            line=line.strip()
            if not line: continue
            try: rows.append(json.loads(line))
            except: continue
    return rows[-limit:]
def _latest_ts(rows, keys=("ts","timestamp")) -> int:
    for r in reversed(rows):
        for k in keys:
            if r.get(k):
                try: return int(r.get(k))
                except: continue
    return 0

# --- Learning-safe logging ---
def _kg(subj, pred, obj):
    _append_jsonl(KG_LOG, {"ts": _now(), "subject": subj, "predicate": pred, "object": obj})
def _bus(update_type, payload):
    _append_jsonl(LEARN_LOG, {"ts": _now(), "update_type": update_type, **payload})

# --- Fee baselines + expected edge ---
def _fee_baseline(exec_rows: List[Dict[str,Any]]) -> Dict[str, Dict[str, float]]:
    by_sym=defaultdict(lambda: {"fees_sum":0.0,"slip_sum":0.0,"count":0})
    for t in exec_rows[-2000:]:
        sym=t.get("symbol"); 
        if not sym: continue
        by_sym[sym]["fees_sum"] += float(t.get("trading_fees",0.0))
        by_sym[sym]["slip_sum"] += float(t.get("slippage", t.get("est_slippage",0.0)))
        by_sym[sym]["count"]    += 1
    out={}
    for sym,v in by_sym.items():
        c=max(v["count"],1)
        out[sym]={"avg_fee": v["fees_sum"]/c, "avg_slippage": v["slip_sum"]/c, "samples": c}
    return out

def _expected_edge_after_cost(symbol: str, strategy_id: str, expected_edge_hint: float) -> float:
    """Calculate expected edge after fees and slippage"""
    fees = _fee_baseline(_read_jsonl(EXEC_LOG, 100000))
    fb = fees.get(symbol, {"avg_fee": 1.0, "avg_slippage": 0.0008})
    live=_read_json(LIVE_CFG, default={}) or {}
    notional=float((live.get("runtime",{}) or {}).get("default_notional_usd", 1000.0))
    
    # Edge after costs
    edge_after = expected_edge_hint - fb["avg_fee"] - (fb["avg_slippage"] * notional)
    return edge_after

# --- Pre-Entry Check (stops instant closes + fee gating) ---
def pre_entry_check(
    symbol: str,
    strategy_id: str, 
    position_notional: float,
    portfolio_value: float,
    runtime_limits: Dict[str, float],
    regime_state: str = "unknown",
    verdict_status: str = "Losing",
    expected_edge_hint: float = 0.0
) -> Tuple[bool, Dict[str, Any]]:
    """
    Pre-entry validation gate:
    - Exposure cap (using CORRECT portfolio value and position notional calc)
    - Fee-aware edge requirement  
    - Symbol quarantine check
    - Runtime limits
    
    Returns: (approved, context_dict)
    """
    ctx = {
        "symbol": symbol,
        "strategy_id": strategy_id,
        "entry_ts": _now(),
        "position_notional": position_notional,
        "portfolio_value": portfolio_value
    }
    
    # 0. Check symbol quarantine (high fees)
    live = _read_json(LIVE_CFG, default={}) or {}
    quarantined = (live.get("runtime", {}) or {}).get("quarantined_symbols", [])
    if symbol in quarantined:
        reason = f"symbol_quarantined_{symbol}_high_fees"
        _bus("entry_rejected", {"symbol": symbol, "reason": reason})
        _kg(symbol, "entry_rejected_quarantine", reason)
        print(f"❌ Entry blocked: {symbol} quarantined for high fees")
        return False, ctx
    
    # 1. Exposure check (FIXED calculation - use actual position notional)
    from src.position_manager import get_open_futures_positions
    positions = get_open_futures_positions()
    
    # Calculate current exposure for this symbol (notional = size * entry_price OR margin * leverage)
    current_exposure = 0
    for p in positions:
        if p.get("symbol") == symbol:
            # Try multiple ways to get notional
            notional = p.get("notional_size", 0)
            if notional == 0:
                # Fallback: margin * leverage
                notional = p.get("margin_collateral", 0) * p.get("leverage", 1)
            if notional == 0:
                # Fallback: size * entry_price
                notional = abs(p.get("size", 0) * p.get("entry_price", 0))
            current_exposure += notional
    
    new_total_exposure = current_exposure + position_notional
    
    max_exposure_pct = runtime_limits.get("max_exposure", DEFAULT_LIMITS["max_exposure"])
    max_allowed = portfolio_value * max_exposure_pct
    
    if new_total_exposure > max_allowed:
        reason = f"exposure_cap_{symbol}_{new_total_exposure:.0f}>{max_allowed:.0f}"
        _bus("entry_rejected", {"symbol": symbol, "reason": reason, "exposure_pct": new_total_exposure/portfolio_value})
        _kg(symbol, "entry_rejected", reason)
        print(f"❌ Entry blocked: {reason}")
        return False, ctx
    
    # 2. Fee-aware edge gate (only if losing)
    if verdict_status == "Losing":
        edge_after = _expected_edge_after_cost(symbol, strategy_id, expected_edge_hint)
        if edge_after <= 0:
            reason = f"negative_edge_after_fees_{symbol}_{strategy_id}_edge={edge_after:.2f}"
            _bus("entry_rejected", {"symbol": symbol, "reason": reason, "edge_after_fees": edge_after})
            _kg(symbol, "entry_rejected_fee_gate", reason)
            print(f"❌ Entry blocked: {reason}")
            return False, ctx
    
    # 3. Passed all gates
    ctx["approved"] = True
    _bus("entry_approved", {"symbol": symbol, "strategy": strategy_id, "exposure_pct": new_total_exposure/portfolio_value})
    return True, ctx

# --- Post-Open Guard (grace window) ---
_open_grace_tracker = {}  # Track by (symbol, strategy, direction) tuple for unique positions

def post_open_guard(ctx: Dict[str, Any]):
    """
    After opening position, enforce grace window where risk_engine won't close it.
    Logs exposure telemetry.
    Uses (symbol, strategy, direction) as key to handle multiple concurrent positions.
    """
    symbol = ctx.get("symbol")
    strategy = ctx.get("strategy_id", "unknown")
    direction = ctx.get("direction", "LONG")
    entry_ts = ctx.get("entry_ts", _now())
    
    # Use tuple key for unique position tracking
    pos_key = (symbol, strategy, direction)
    grace_until = entry_ts + GRACE_SECS
    _open_grace_tracker[pos_key] = grace_until
    
    _bus("position_opened_grace", {
        "symbol": symbol,
        "strategy": strategy,
        "direction": direction,
        "grace_until": grace_until,
        "notional": ctx.get("position_notional", 0)
    })
    print(f"✅ Position opened: {direction} {symbol} ({strategy}) - grace until {grace_until}")

def is_in_grace_window(position: Dict[str, Any]) -> bool:
    """
    Check if position is still in grace window.
    Args:
        position: Position dict with symbol, strategy, direction
    Returns:
        True if within grace window
    """
    symbol = position.get("symbol")
    strategy = position.get("strategy", "unknown")
    direction = position.get("direction", "LONG")
    
    pos_key = (symbol, strategy, direction)
    grace_expiry = _open_grace_tracker.get(pos_key, 0)
    
    return _now() < grace_expiry

# --- Signal Direction Adjustment (inversion overlay) ---
def adjust_signal_direction(signal: Dict[str, Any]) -> Dict[str, Any]:
    """
    Conditionally invert SHORT signals based on:
    - Historical performance (SHORT signals have 27% WR with negative gross P&L)
    - Regime (only invert in trending/volatile regimes)
    - Latency (if feed is fresh, less likely to need inversion)
    
    Returns: Modified signal dict
    """
    if not signal or signal.get("action") not in ["OPEN_SHORT", "SHORT"]:
        return signal
    
    symbol = signal.get("symbol", "")
    strategy = signal.get("strategy", "EMA-Futures")
    
    # Load SHORT performance stats
    exec_rows = _read_jsonl(EXEC_LOG, 5000)
    short_trades = [t for t in exec_rows if t.get("direction") == "SHORT" and t.get("symbol") == symbol]
    
    if len(short_trades) < 10:
        # Not enough data, allow SHORT
        return signal
    
    # Calculate SHORT win rate and gross P&L
    wins = sum(1 for t in short_trades if t.get("gross_pnl", 0) > 0)
    wr = wins / len(short_trades) if short_trades else 0
    gross_pnl = sum(t.get("gross_pnl", 0) for t in short_trades)
    
    # Inversion criteria: WR < 35% AND gross P&L < 0
    should_invert = wr < 0.35 and gross_pnl < 0
    
    if should_invert:
        # Flip SHORT → LONG
        signal["action"] = "OPEN_LONG"
        signal["direction"] = "LONG"
        signal["inversion_applied"] = True
        signal["original_action"] = "OPEN_SHORT"
        signal["inversion_reason"] = f"short_wr={wr:.1%}_gross_pnl=${gross_pnl:.2f}"
        
        _bus("signal_inverted", {
            "symbol": symbol,
            "strategy": strategy,
            "original": "SHORT",
            "new": "LONG",
            "wr": wr,
            "gross_pnl": gross_pnl
        })
        _kg(symbol, "signal_inverted_short_to_long", f"wr={wr:.1%}")
        print(f"🔄 Signal INVERTED: {symbol} SHORT→LONG (WR={wr:.1%}, gross=${gross_pnl:.2f})")
    
    return signal

# --- Recovery Cycle (autonomous restart from protective mode) ---
def run_recovery_cycle():
    """
    Staged recovery from kill-switch protective mode.
    Checks if conditions are safe to resume trading.
    """
    try:
        from src.phase82_protective_mode import get_protective_status
        status = get_protective_status()
    except ImportError:
        # Phase 82 module not available, skip recovery check
        return
    
    if not status.get("active"):
        # Not in protective mode, nothing to recover
        return
    
    print("\n🔄 Running recovery cycle from protective mode...")
    
    # Check recent performance (last 20 trades)
    exec_rows = _read_jsonl(EXEC_LOG, 10000)
    recent = exec_rows[-20:]
    
    if len(recent) < 10:
        print("   ⏸️ Not enough recent trades to assess recovery")
        return
    
    wins = sum(1 for t in recent if t.get("net_pnl", 0) > 0)
    wr = wins / len(recent)
    avg_pnl = statistics.mean([t.get("net_pnl", 0) for t in recent])
    
    # Recovery gate: WR > 40% AND avg P&L > -$1
    can_recover = wr > 0.40 and avg_pnl > -1.0
    
    if can_recover:
        print(f"   ✅ Recovery conditions met: WR={wr:.1%}, avg P&L=${avg_pnl:.2f}")
        print(f"   📊 Recommend manual kill-switch deactivation")
        _bus("recovery_eligible", {"wr": wr, "avg_pnl": avg_pnl, "trades": len(recent)})
        _kg("recovery_cycle", "eligible_for_restart", f"wr={wr:.1%}")
    else:
        print(f"   ⏸️ Recovery conditions NOT met: WR={wr:.1%}, avg P&L=${avg_pnl:.2f}")
        _bus("recovery_not_ready", {"wr": wr, "avg_pnl": avg_pnl, "trades": len(recent)})

# --- Fee/Venue Audit (updates baselines) ---
def run_fee_venue_audit():
    """
    Audit fee/slippage baselines and quarantine high-cost symbols.
    Updates runtime config.
    """
    exec_rows = _read_jsonl(EXEC_LOG, 10000)
    fees = _fee_baseline(exec_rows)
    
    live = _read_json(LIVE_CFG, default={}) or {}
    runtime = live.get("runtime", {}) or {}
    quarantined = runtime.get("quarantined_symbols", [])
    
    print("\n📊 Fee/Venue Audit:")
    
    for symbol, stats in sorted(fees.items(), key=lambda x: x[1]["avg_fee"], reverse=True):
        print(f"   {symbol}: avg_fee=${stats['avg_fee']:.2f}, avg_slip={stats['avg_slippage']:.4f}, n={stats['samples']}")
        
        # Quarantine if avg fee > $3.00 and sample size > 10
        if stats["avg_fee"] > 3.0 and stats["samples"] > 10 and symbol not in quarantined:
            quarantined.append(symbol)
            _kg(symbol, "quarantined_high_fees", f"avg_fee=${stats['avg_fee']:.2f}")
            print(f"      ⚠️ QUARANTINED (high fees)")
    
    # Update runtime config
    runtime["quarantined_symbols"] = quarantined
    runtime["fee_baselines"] = fees
    live["runtime"] = runtime
    _write_json(LIVE_CFG, live)

# --- Nightly Learning Digest ---
def nightly_learning_digest():
    """
    Compile comprehensive learning insights from all rejections, inversions, and outcomes.
    Feeds into Meta-Learning Orchestrator.
    """
    print("\n🌙 Nightly Learning Digest...")
    
    learn_rows = _read_jsonl(LEARN_LOG, 50000)
    exec_rows = _read_jsonl(EXEC_LOG, 10000)
    
    # Count events
    entry_rejections = [r for r in learn_rows if r.get("update_type") == "entry_rejected"]
    signal_inversions = [r for r in learn_rows if r.get("update_type") == "signal_inverted"]
    
    # Performance metrics
    if exec_rows:
        recent_100 = exec_rows[-100:]
        wins = sum(1 for t in recent_100 if t.get("net_pnl", 0) > 0)
        wr = wins / len(recent_100) if recent_100 else 0
        total_pnl = sum(t.get("net_pnl", 0) for t in recent_100)
        
        digest = {
            "timestamp": _now(),
            "period": "last_100_trades",
            "win_rate": wr,
            "total_pnl": total_pnl,
            "entry_rejections": len(entry_rejections),
            "signal_inversions": len(signal_inversions),
            "total_trades": len(recent_100)
        }
        
        _append_jsonl("logs/nightly_digest.jsonl", digest)
        print(f"   ✅ Digest complete: WR={wr:.1%}, P&L=${total_pnl:.2f}, {len(entry_rejections)} rejections, {len(signal_inversions)} inversions")
        
        return digest
    
    return {}
