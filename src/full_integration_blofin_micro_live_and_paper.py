# src/full_integration_blofin_micro_live_and_paper.py
#
# v6.6 Full Integration: Execution hooks + Signal inversion + Scheduler + Blofin futures bridge
# Purpose:
#   - Provide a single drop-in module that wires all discussed fixes into your bot:
#     1) Entry orchestration (sizing → fee/exposure gate → order → grace map)
#     2) Signal inversion overlay (SHORT→LONG) with regime/latency guards and propagation
#     3) Fee audit + recovery scheduler (10-min cadence + nightly digest @ 07:00 UTC)
#     4) Paper/live mode safety harness with guardrails and toggles
#     5) Blofin Futures open_order_fn bridge (micro-live safe defaults)
#
# Files and runtime:
#   - live_config.json (runtime modes, limits, grace_map, quarantines)
#   - logs/learning_updates.jsonl (learning bus)
#   - logs/knowledge_graph.jsonl (knowledge graph)
#   - logs/executed_trades.jsonl, logs/strategy_signals.jsonl (telemetry feeds)
#
# How to use:
#   - In bot_cycle.py:
#       from full_integration_blofin_micro_live_and_paper import run_entry_flow, honor_grace_before_exposure_close, start_scheduler
#       ok, tel = run_entry_flow(..., open_order_fn=blofin_open_order_fn)
#       if honor_grace_before_exposure_close(order_id): continue  # skip close
#   - In futures_signal_generator.py:
#       from full_integration_blofin_micro_live_and_paper import adjust_and_propagate_signal
#       signal = adjust_and_propagate_signal(signal)
#   - Daemon:
#       start_scheduler(interval_secs=600)
#   - CLI:
#       python3 src/full_integration_blofin_micro_live_and_paper.py --set-paper --scheduler
#
import os, json, time, argparse
from typing import Dict, Any, Tuple, List
from collections import defaultdict
from datetime import datetime

# --------------------------------------------------------------------------------------
# Initialize Opportunity Scorer at module level for profit-seeking integration
# --------------------------------------------------------------------------------------
OPPORTUNITY_SCORER = None
try:
    from src.opportunity_scorer import OpportunityScorer, check_time_filter
    OPPORTUNITY_SCORER = OpportunityScorer()
    print("[PROFIT-SEEKER] Module loaded successfully - profit-seeking mode ACTIVE")
except Exception as e:
    print(f"[PROFIT-SEEKER] WARNING: Failed to load opportunity_scorer: {e}")

# --------------------------------------------------------------------------------------
# IO + Logging helpers
# --------------------------------------------------------------------------------------
LIVE_CFG  = "live_config.json"
LEARN_LOG = "logs/learning_updates.jsonl"
KG_LOG    = "logs/knowledge_graph.jsonl"
EXEC_LOG  = "logs/executed_trades.jsonl"
SIG_LOG   = "logs/strategy_signals.jsonl"

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
def _bus(update_type, payload):
    _append_jsonl(LEARN_LOG, {"ts": _now(), "update_type": update_type, **payload})
def _kg(subj, pred, obj):
    _append_jsonl(KG_LOG, {"ts": _now(), "subject": subj, "predicate": pred, "object": obj})

# --------------------------------------------------------------------------------------
# Hold Time Governor Integration (Phase 15.0 - Prevents premature exits)
# --------------------------------------------------------------------------------------
HOLD_TIME_GOVERNOR = None
try:
    from src.hold_time_governor import get_governor, should_block_exit
    HOLD_TIME_GOVERNOR = get_governor()
    print("[HOLD_GOVERNOR] Module loaded successfully - minimum hold enforcement ACTIVE")
except Exception as e:
    print(f"[HOLD_GOVERNOR] WARNING: Failed to load hold_time_governor: {e}")

# --------------------------------------------------------------------------------------
# Exit Timing Intelligence Integration (Phase 15.0 - Optimal exit targets)
# --------------------------------------------------------------------------------------
EXIT_TIMING_INTEL = None
try:
    from src.exit_timing_intelligence import get_intelligence, get_optimal_targets
    EXIT_TIMING_INTEL = get_intelligence()
    print("[EXIT_TIMING] Module loaded successfully - MFE-based targets ACTIVE")
except Exception as e:
    print(f"[EXIT_TIMING] WARNING: Failed to load exit_timing_intelligence: {e}")

# --------------------------------------------------------------------------------------
# Fee-Aware Gate Integration (Profitability Module - Blocks unprofitable trades)
# --------------------------------------------------------------------------------------
FEE_AWARE_GATE = None
try:
    from src.fee_aware_gate import get_fee_gate
    FEE_AWARE_GATE = get_fee_gate()
    print("[FEE_GATE] Module loaded successfully - fee-aware blocking ACTIVE")
except Exception as e:
    print(f"[FEE_GATE] WARNING: Failed to load fee_aware_gate: {e}")

# --------------------------------------------------------------------------------------
# Edge-Weighted Sizing Integration (Profitability Module - Quality-based sizing)
# --------------------------------------------------------------------------------------
EDGE_WEIGHTED_SIZER = None
try:
    from src.edge_weighted_sizer import get_edge_sizer
    EDGE_WEIGHTED_SIZER = get_edge_sizer()
    print("[EDGE_SIZER] Module loaded successfully - edge-weighted sizing ACTIVE")
except Exception as e:
    print(f"[EDGE_SIZER] WARNING: Failed to load edge_weighted_sizer: {e}")

# --------------------------------------------------------------------------------------
# Correlation Throttle Integration (Profitability Module - Reduces correlated exposure)
# --------------------------------------------------------------------------------------
CORRELATION_THROTTLE = None
try:
    from src.correlation_throttle import get_correlation_throttle
    CORRELATION_THROTTLE = get_correlation_throttle()
    print("[CORR_THROTTLE] Module loaded successfully - correlation throttle ACTIVE")
except Exception as e:
    print(f"[CORR_THROTTLE] WARNING: Failed to load correlation_throttle: {e}")

# --------------------------------------------------------------------------------------
# Strategic Advisor Integration (Profitability Module - Hourly analysis)
# --------------------------------------------------------------------------------------
STRATEGIC_ADVISOR = None
try:
    from src.strategic_advisor import StrategicAdvisor
    STRATEGIC_ADVISOR = StrategicAdvisor()
    print("[STRATEGIC_ADVISOR] Module loaded successfully - hourly analysis ACTIVE")
except Exception as e:
    print(f"[STRATEGIC_ADVISOR] WARNING: Failed to load strategic_advisor: {e}")

# --------------------------------------------------------------------------------------
# Per-Symbol Threshold Overrides (from offensive learning + daily intelligence)
# --------------------------------------------------------------------------------------
OFFENSIVE_THRESHOLDS_PATH = "configs/offensive_thresholds.json"
DAILY_LEARNING_RULES_PATH = "feature_store/daily_learning_rules.json"
_cached_offensive_thresholds = None
_offensive_thresholds_mtime = 0
_cached_daily_rules = None
_daily_rules_mtime = 0

def _classify_ofi_bucket(ofi: float) -> str:
    """Classify OFI into bucket for pattern matching."""
    ofi = abs(ofi)
    if ofi < 0.25:
        return "weak"
    elif ofi < 0.50:
        return "moderate"
    elif ofi < 0.75:
        return "strong"
    elif ofi < 0.90:
        return "very_strong"
    else:
        return "extreme"

def _check_pattern_match_simple(symbol: str, direction: str, pattern_key: str) -> bool:
    """Check if symbol+direction matches a learned pattern key."""
    parts = pattern_key.split("|")
    for part in parts:
        if "=" not in part:
            continue
        key, val = part.split("=", 1)
        key = key.strip()
        val = val.strip()
        if key == "sym" and val != symbol:
            return False
        elif key == "dir" and val != direction.upper():
            return False
    return True

def _reload_daily_rules():
    """Reload daily learning rules if changed."""
    global _cached_daily_rules, _daily_rules_mtime
    try:
        if os.path.exists(DAILY_LEARNING_RULES_PATH):
            mtime = os.path.getmtime(DAILY_LEARNING_RULES_PATH)
            if mtime > _daily_rules_mtime:
                _cached_daily_rules = _read_json(DAILY_LEARNING_RULES_PATH, {})
                _daily_rules_mtime = mtime
    except:
        pass


def should_avoid_pattern(symbol: str, direction: str, ofi: float = 0) -> Tuple[bool, str]:
    """
    Check if this symbol+direction+ofi combination matches a losing pattern.
    Returns (should_avoid, reason).
    """
    _reload_daily_rules()
    
    if not _cached_daily_rules:
        return False, ""
    
    ofi_bucket = _classify_ofi_bucket(ofi)
    losing = _cached_daily_rules.get("losing_patterns", {})
    
    for pattern_key, config in losing.items():
        if config.get("action") != "avoid":
            continue
        
        parts = pattern_key.split("|")
        match = True
        for part in parts:
            if "=" not in part:
                continue
            key, val = part.split("=", 1)
            key = key.strip()
            val = val.strip()
            
            if key == "sym" and val != symbol:
                match = False
                break
            elif key == "dir" and val != direction.upper():
                match = False
                break
            elif key == "ofi" and val != ofi_bucket:
                match = False
                break
        
        if match:
            return True, f"losing_pattern:{pattern_key}"
    
    return False, ""


def get_symbol_bias(symbol: str) -> Tuple[str, float]:
    """
    Get preferred direction bias for a symbol from learning.
    Returns (preferred_direction, advantage_amount).
    """
    _reload_daily_rules()
    
    if not _cached_daily_rules:
        return "", 0
    
    biases = _cached_daily_rules.get("symbol_biases", {})
    if symbol in biases:
        bias = biases[symbol]
        return bias.get("preferred_direction", ""), bias.get("advantage", 0)
    
    return "", 0


def get_winning_pattern_boost(symbol: str, direction: str, ofi: float = 0.5) -> Tuple[float, str, bool]:
    """
    WINNING PATTERN AUTO-BOOST (Phase 15.0)
    =======================================
    Auto-increase size for patterns with EV > $1 and WR > 50%.
    
    KEY PATTERNS:
    - DOTUSDT|SHORT|OFI=strong = 100% WR, $17.75 P&L → 1.5x sizing
    
    Returns:
        (size_multiplier, pattern_matched, is_top_pattern)
    
    Criteria for boost:
    - EV (expected value) > $1 per trade
    - Win Rate > 50%
    - At least 5 trades in pattern history
    """
    _reload_daily_rules()
    
    if not _cached_daily_rules:
        return 1.0, "", False
    
    ofi_bucket = _classify_ofi_bucket(ofi)
    direction = direction.upper()
    
    profitable = _cached_daily_rules.get("profitable_patterns", {})
    
    pattern_checks = [
        f"sym={symbol}|dir={direction}|ofi={ofi_bucket}",
        f"sym={symbol}|dir={direction}",
        f"sym={symbol}|ofi={ofi_bucket}",
    ]
    
    best_match = None
    best_ev = 0
    
    for pattern_key, config in profitable.items():
        if config.get("action") != "trade_aggressive":
            continue
        
        ev = config.get("ev", 0)
        wr = config.get("wr", 0)
        trades = config.get("trades", 0)
        pnl = config.get("pnl", 0)
        
        if ev < 1.0 or wr < 50 or trades < 5:
            continue
        
        for check in pattern_checks:
            if _check_pattern_match_simple(symbol, direction, pattern_key):
                if ev > best_ev:
                    best_ev = ev
                    best_match = {
                        "pattern": pattern_key,
                        "ev": ev,
                        "wr": wr,
                        "pnl": pnl,
                        "trades": trades,
                        "size_multiplier": config.get("size_multiplier", 1.0)
                    }
                break
    
    if best_match:
        mult = min(1.5, best_match["size_multiplier"])
        is_top = best_match["ev"] > 3.0 or best_match["wr"] >= 100
        
        _bus("winning_pattern_boost", {
            "ts": _now(),
            "symbol": symbol,
            "direction": direction,
            "ofi_bucket": ofi_bucket,
            "pattern": best_match["pattern"],
            "ev": best_match["ev"],
            "wr": best_match["wr"],
            "pnl": best_match["pnl"],
            "multiplier": mult,
            "is_top_pattern": is_top
        })
        
        return mult, best_match["pattern"], is_top
    
    return 1.0, "", False


def get_time_of_day_boost(current_hour: int = None) -> Tuple[float, str, bool]:
    """
    TIME-OF-DAY BOOST (Phase 15.0)
    ==============================
    Boost sizing during proven profitable hours.
    
    KEY DATA: 08:00 UTC = +$41.72 profit at 61.5% WR
    
    Returns:
        (size_multiplier, reason, should_trade)
    """
    if current_hour is None:
        current_hour = datetime.utcnow().hour
    
    try:
        from src.opportunity_scorer import get_time_of_day_weight
        return get_time_of_day_weight(current_hour)
    except Exception:
        pass
    
    # EXPLORATION MODE 2025-12-03: No hour blocking, just sizing adjustments
    # User directive: Maximize data collection, this is paper trading
    BEST_HOURS = [8, 9, 10, 14, 15]
    REDUCED_HOURS = [3, 4, 5, 22, 23]  # Renamed from WORST - reduce size but don't block
    
    if current_hour in BEST_HOURS:
        return 1.25, f"BEST_HOUR:{current_hour:02d}:00_UTC", True
    
    if current_hour in REDUCED_HOURS:
        # Changed: 0.5x sizing instead of blocking (still collect data)
        return 0.5, f"REDUCED_HOUR:{current_hour:02d}:00_UTC", True
    
    return 1.0, f"NORMAL_HOUR:{current_hour:02d}:00_UTC", True


def apply_profitability_acceleration(symbol: str, direction: str, 
                                      ofi: float, base_size: float,
                                      current_hour: int = None) -> Tuple[float, Dict[str, Any]]:
    """
    UNIFIED PROFITABILITY ACCELERATION (Phase 15.0)
    ===============================================
    Combines all boost factors:
    1. Winning Pattern Auto-Boost
    2. Time-of-Day Boost
    
    Returns:
        (adjusted_size, boost_details)
    """
    if current_hour is None:
        current_hour = datetime.utcnow().hour
    
    pattern_mult, pattern_matched, is_top = get_winning_pattern_boost(symbol, direction, ofi)
    
    tod_mult, tod_reason, can_trade = get_time_of_day_boost(current_hour)
    
    if not can_trade:
        return 0.0, {
            "blocked": True,
            "reason": tod_reason,
            "pattern_matched": pattern_matched,
            "is_top_pattern": is_top
        }
    
    total_mult = pattern_mult * tod_mult
    total_mult = min(2.0, max(0.5, total_mult))
    
    adjusted_size = base_size * total_mult
    
    details = {
        "blocked": False,
        "base_size": round(base_size, 2),
        "adjusted_size": round(adjusted_size, 2),
        "total_multiplier": round(total_mult, 2),
        "pattern_boost": {
            "multiplier": pattern_mult,
            "pattern": pattern_matched,
            "is_top_pattern": is_top
        },
        "time_boost": {
            "multiplier": tod_mult,
            "reason": tod_reason,
            "hour_utc": current_hour
        }
    }
    
    if total_mult > 1.0:
        _bus("profitability_acceleration_applied", {
            "ts": _now(),
            "symbol": symbol,
            "direction": direction,
            **details
        })
        print(f"   🚀 [PROFIT-ACCEL] {symbol} {direction}: {total_mult:.2f}x boost (pattern:{pattern_mult:.2f}x, time:{tod_mult:.2f}x)")
    
    return adjusted_size, details


def get_ofi_threshold(symbol: str, direction: str) -> float:
    """
    Get OFI threshold for symbol+direction, with learned overrides.
    Returns lower thresholds for profitable patterns discovered by:
    1. Coin profiles (feature_store/coin_profiles.json) - per-coin base threshold
    2. Daily intelligence learner (feature_store/daily_learning_rules.json)
    3. Offensive thresholds (configs/offensive_thresholds.json)
    
    2025-12-09: Lowered base from 0.50 to 0.35 to allow more strong OFI trades through.
    """
    global _cached_offensive_thresholds, _offensive_thresholds_mtime
    
    base_threshold = 0.35
    
    try:
        from src.coin_profile_engine import get_coin_profile
        profile = get_coin_profile(symbol)
        if profile and "recommendations" in profile:
            profile_threshold = profile["recommendations"].get("ofi_threshold")
            if profile_threshold is not None:
                base_threshold = float(profile_threshold)
    except Exception:
        pass
    
    _reload_daily_rules()
    
    if _cached_daily_rules:
        profitable = _cached_daily_rules.get("profitable_patterns", {})
        for pattern_key, config in profitable.items():
            if _check_pattern_match_simple(symbol, direction, pattern_key):
                reduction = config.get("ofi_threshold_reduction", 0.10)
                learned_threshold = max(0.15, base_threshold - reduction)
                _bus("daily_rule_applied", {
                    "ts": _now(), "symbol": symbol, "direction": direction,
                    "pattern": pattern_key, "threshold": learned_threshold,
                    "original": base_threshold
                })
                return learned_threshold
        
        high_potential = _cached_daily_rules.get("high_potential_patterns", {})
        for pattern_key, config in high_potential.items():
            if _check_pattern_match_simple(symbol, direction, pattern_key):
                reduction = config.get("ofi_threshold_reduction", 0.05)
                learned_threshold = max(0.20, base_threshold - reduction)
                _bus("daily_rule_applied", {
                    "ts": _now(), "symbol": symbol, "direction": direction,
                    "pattern": pattern_key, "threshold": learned_threshold,
                    "type": "high_potential"
                })
                return learned_threshold
    
    try:
        if os.path.exists(OFFENSIVE_THRESHOLDS_PATH):
            mtime = os.path.getmtime(OFFENSIVE_THRESHOLDS_PATH)
            if mtime > _offensive_thresholds_mtime:
                _cached_offensive_thresholds = _read_json(OFFENSIVE_THRESHOLDS_PATH, {})
                _offensive_thresholds_mtime = mtime
    except:
        pass
    
    if not _cached_offensive_thresholds:
        return base_threshold
    
    key = f"{symbol}_{direction.upper()}"
    if key in _cached_offensive_thresholds:
        return float(_cached_offensive_thresholds[key])
    
    if symbol in _cached_offensive_thresholds:
        return float(_cached_offensive_thresholds[symbol])
    
    return float(_cached_offensive_thresholds.get("default", base_threshold))

# --------------------------------------------------------------------------------------
# Signal Inversion Logic (from feedback loop learning)
# --------------------------------------------------------------------------------------
SIGNAL_INVERSIONS_PATH = "configs/signal_inversions.json"
_cached_signal_inversions = None
_signal_inversions_mtime = 0

def should_invert_signal(symbol: str) -> bool:
    """
    Check if signals for this symbol should be inverted based on learned feedback.
    Returns True if opposite direction was consistently better.
    """
    global _cached_signal_inversions, _signal_inversions_mtime
    
    try:
        if os.path.exists(SIGNAL_INVERSIONS_PATH):
            mtime = os.path.getmtime(SIGNAL_INVERSIONS_PATH)
            if mtime > _signal_inversions_mtime:
                _cached_signal_inversions = _read_json(SIGNAL_INVERSIONS_PATH, {})
                _signal_inversions_mtime = mtime
    except:
        pass
    
    if not _cached_signal_inversions:
        return False
    
    inversion_config = _cached_signal_inversions.get(symbol, {})
    return bool(inversion_config.get("invert", False))


def apply_signal_inversion(symbol: str, direction: str) -> str:
    """
    Apply signal inversion if learned feedback indicates opposite direction is better.
    Returns the (possibly inverted) direction.
    """
    if should_invert_signal(symbol):
        inverted = "SHORT" if direction.upper() == "LONG" else "LONG"
        _bus("signal_inverted", {"symbol": symbol, "original": direction, "inverted": inverted})
        print(f"   🔄 [INVERSION] {symbol}: {direction} → {inverted} (learned from feedback loop)")
        return inverted
    return direction

# --------------------------------------------------------------------------------------
# Modes, limits, defaults (paper/live harness)
# --------------------------------------------------------------------------------------
# Normal paper trading uses portfolio-based sizing (6-10% = $600-$1000 per trade with $10k portfolio)
# Fee-aware gates still active - blocks unprofitable entries regardless of notional size
DEFAULT_LIMITS = {"max_exposure": 0.60, "max_leverage": 3.0, "max_drawdown_24h": 0.05}
PAPER_LIMITS   = {"max_exposure": 0.60, "max_leverage": 3.0, "max_drawdown_24h": 0.05}
MICRO_LIVE_NOTIONAL_USD = 100.0   # micro-live per-trade notional (ultra-conservative real money)
PAPER_NOTIONAL_USD      = None    # None = use Phase 7.2 futures_margin_budget (6-10% of portfolio)
ALLOWED_SYMBOLS_PAPER   = None    # None = all symbols from asset_universe.json
ALLOWED_SYMBOLS_LIVE    = None    # None = all 15 coins from asset_universe.json (FIXED - was restricting to 2 coins)

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
    # None means "use normal portfolio-based sizing" - don't override with fixed notional
    if PAPER_NOTIONAL_USD is not None or MICRO_LIVE_NOTIONAL_USD is not None:
        rt.setdefault("default_notional_usd", PAPER_NOTIONAL_USD if paper_mode else MICRO_LIVE_NOTIONAL_USD)
    rt.setdefault("capital_limits", PAPER_LIMITS if paper_mode else DEFAULT_LIMITS)
    # None means "all symbols allowed" - don't restrict
    if ALLOWED_SYMBOLS_PAPER is not None or ALLOWED_SYMBOLS_LIVE is not None:
        rt.setdefault("allowed_symbols_mode", ALLOWED_SYMBOLS_PAPER if paper_mode else ALLOWED_SYMBOLS_LIVE)
    rt.setdefault("grace_map", {})
    caps = rt.get("risk_caps", {}) or {}
    caps.setdefault("exposure_cap_enabled", True)
    caps.setdefault("max_exposure", (PAPER_LIMITS if paper_mode else DEFAULT_LIMITS)["max_exposure"])
    rt["risk_caps"] = caps
    rt.setdefault("post_open_grace_secs", 3)
    _set_runtime(rt)
    _bus("modes_defaults_ensured", {"paper_mode": paper_mode, "runtime": rt})
    _kg({"overlay":"modes"}, "defaults", {"paper_mode": paper_mode, "runtime": rt})

def set_paper_mode(on: bool):
    rt=_runtime(); rt["paper_mode"]=bool(on); _set_runtime(rt); ensure_modes_defaults()
    _bus("paper_mode_set", {"paper_mode": on}); _kg({"overlay":"modes"}, "paper_mode", {"on": on})
def set_live_mode_micro(on: bool):
    rt=_runtime(); rt["paper_mode"]=not bool(on); _set_runtime(rt); ensure_modes_defaults()
    _bus("micro_live_mode_set", {"on": on}); _kg({"overlay":"modes"}, "micro_live_mode", {"on": on})

# --------------------------------------------------------------------------------------
# Open Positions Helper (for correlation throttle)
# --------------------------------------------------------------------------------------
def get_open_positions() -> List[Dict]:
    """Get current open positions for correlation throttle."""
    try:
        from src.data_registry import DataRegistry as DR
        data = _read_json(DR.POSITIONS_FUTURES, default={"open_positions": []})
        return data.get("open_positions", [])
    except Exception as e:
        return []

# --------------------------------------------------------------------------------------
# Sizing after overlays + fee baselines + expected edge
# --------------------------------------------------------------------------------------
def _fee_baseline(exec_rows: List[Dict[str,Any]]) -> Dict[str, Dict[str, float]]:
    by_sym=defaultdict(lambda: {"fees_sum":0.0,"slip_sum":0.0,"count":0})
    for t in exec_rows[-2000:]:
        sym=t.get("symbol"); 
        if not sym: continue
        by_sym[sym]["fees_sum"] += float(t.get("fees",0.0))
        by_sym[sym]["slip_sum"] += float(t.get("slippage", t.get("est_slippage",0.0)))
        by_sym[sym]["count"]    += 1
    out={}
    for sym,v in by_sym.items():
        c=max(v["count"],1)
        out[sym]={"avg_fee": v["fees_sum"]/c, "avg_slippage": v["slip_sum"]/c, "samples": c}
    return out

def _expected_edge_after_cost(symbol: str, expected_edge_hint: float) -> float:
    fees = _fee_baseline(_read_jsonl(EXEC_LOG, 100000))
    fb = fees.get(symbol, {"avg_fee": 1.0, "avg_slippage": 0.0008})
    # Get notional with None-safe handling (key may exist with None value)
    notional_raw = _runtime().get("default_notional_usd", 1000.0)
    notional = float(notional_raw) if notional_raw is not None else 1000.0
    # Handle None or invalid expected_edge_hint - default to 0.5% (0.005) edge
    if expected_edge_hint is None:
        expected_edge_hint = 0.005
    try:
        expected_edge_hint = float(expected_edge_hint)
    except (TypeError, ValueError):
        expected_edge_hint = 0.005
    if abs(expected_edge_hint) < 0.05:  # treat as pct
        edge_dollars = expected_edge_hint * notional - fb["avg_fee"] - fb["avg_slippage"] * notional
    else:
        edge_dollars = expected_edge_hint - fb["avg_fee"] - fb["avg_slippage"] * notional
    return edge_dollars

def size_after_adjustment(symbol: str, strategy_id: str, base_notional: float, runtime: Dict[str,Any]) -> float:
    rt = runtime or {}
    # Ensure base_notional is a valid float
    if base_notional is None:
        base_notional = 500.0  # Default fallback
    try:
        base_notional = float(base_notional)
    except (TypeError, ValueError):
        base_notional = 500.0
    
    throttle_raw = rt.get("size_throttle", 1.0)
    throttle = float(throttle_raw) if throttle_raw is not None else 1.0
    
    per_symbol = ((rt.get("alloc_overlays",{}) or {}).get("per_symbol",{}) or {}).get(symbol, {})
    mult_raw = per_symbol.get("size_multiplier", 1.0)
    mult = float(mult_raw) if mult_raw is not None else 1.0
    
    fee_quarantine = (rt.get("fee_quarantine",{}) or {})
    quarantine_mult = 0.5 if symbol in fee_quarantine else 1.0
    final = max(0.0, base_notional * throttle * mult * quarantine_mult)
    _bus("sizing_after_adjustment", {"symbol": symbol, "strategy_id": strategy_id, "base": base_notional, "final": final,
                                     "throttle": throttle, "mult": mult, "quarantine_mult": quarantine_mult})
    _kg({"overlay":"sizing","symbol":symbol}, "final_size", {"base": base_notional, "final": final, "factors": {"throttle": throttle, "mult": mult, "quarantine_mult": quarantine_mult}})
    return final

# --------------------------------------------------------------------------------------
# Exposure audit + gate + grace enforcement
# --------------------------------------------------------------------------------------
def _audit_exposure(symbol, position_notional, portfolio_value, limits) -> Tuple[float, float, Dict[str,Any]]:
    eps=1e-9
    pv=float(portfolio_value if portfolio_value is not None else 0.0)
    pos=float(position_notional if position_notional is not None else 0.0)
    # None-safe max_exposure lookup
    risk_caps = _runtime().get("risk_caps", {}) or {}
    cap_raw = limits.get("max_exposure", risk_caps.get("max_exposure", 0.25))
    cap = float(cap_raw) if cap_raw is not None else 0.25
    # None-safe fallback_portfolio_value
    fallback_raw = _runtime().get("fallback_portfolio_value", 0.0)
    fallback_pv = float(fallback_raw) if fallback_raw is not None else 0.0
    pv_used = pv if pv>eps else fallback_pv if fallback_pv>eps else pv
    exposure = pos / max(pv_used, eps)
    diag={"symbol":symbol, "position_notional":pos, "portfolio_value":pv, "fallback_portfolio_value":fallback_pv, "exposure_pct": round(exposure,6), "cap": cap}
    _bus("risk_exposure_audit", {"audit": diag}); _kg({"overlay":"risk_engine"}, "exposure_audit", diag)
    return exposure, cap, diag

def _should_block_entry(exposure_pct, cap, runtime):
    enabled = bool((runtime.get("risk_caps", {}) or {}).get("exposure_cap_enabled", True))
    return enabled and exposure_pct > (cap * 1.10)  # 10% buffer

def pre_entry_check(symbol: str, strategy_id: str, final_notional: float, portfolio_value_snapshot: float,
                    runtime_limits: Dict[str,Any], regime_state: str, verdict_status: str, expected_edge_hint: float) -> Tuple[bool, Dict[str,Any]]:
    # [GOLDEN HOUR CHECK] Block entries outside trading hours (configurable)
    trading_window_info = {"trading_window": "unknown"}
    try:
        from src.enhanced_trade_logging import check_golden_hours_block
        should_block, reason, trading_window = check_golden_hours_block()
        trading_window_info["trading_window"] = trading_window
        if should_block:
            print(f"❌ Entry blocked: {reason}")
            return False, {"symbol": symbol, "strategy_id": strategy_id, "reason": reason, **trading_window_info}
    except Exception as e:
        # Fail open if check fails, but try to still set trading_window
        try:
            from src.enhanced_trade_logging import is_golden_hour
            trading_window_info["trading_window"] = "golden_hour" if is_golden_hour() else "24_7"
        except:
            pass
        pass  # Fail open if check fails
    
    # [STABLE REGIME BLOCK] Hard block on Stable regime (35.2% win rate)
    try:
        from src.enhanced_trade_logging import check_stable_regime_block
        should_block, reason = check_stable_regime_block(symbol, strategy_id)
        if should_block:
            print(f"❌ Entry blocked: {reason}")
            return False, {"symbol": symbol, "strategy_id": strategy_id, "reason": reason}
    except Exception as e:
        pass  # Fail open if check fails
    
    edge_after_cost = _expected_edge_after_cost(symbol, expected_edge_hint)
    fee_gate_ok = edge_after_cost >= 0.0
    exposure_pct, cap, diag = _audit_exposure(symbol, final_notional, portfolio_value_snapshot, runtime_limits)
    rt=_runtime()
    block_exposure = _should_block_entry(exposure_pct, cap, rt)
    ok = fee_gate_ok and not block_exposure
    reason = {"fee_gate_ok": fee_gate_ok, "edge_after_cost_dollars": round(edge_after_cost, 4),
              "block_exposure": block_exposure, "exposure_pct": round(exposure_pct,6)}
    _bus("pre_entry_decision", {"symbol": symbol, "strategy_id": strategy_id, "ok": ok, "reason": reason})
    _kg({"overlay":"entry_gate","symbol":symbol}, "pre_entry", {"ok": ok, "reason": reason})
    ctx={"symbol":symbol,"strategy_id":strategy_id,"grace_until": _now()+int(rt.get("post_open_grace_secs", 3)),
         "exposure": exposure_pct, "cap": cap}
    return ok, ctx

def post_open_guard(ctx: Dict[str,Any], direction: str, order_id: str):
    now=_now()
    live=_read_json(LIVE_CFG, default={}) or {}; rt=live.get("runtime",{}) or {}; live["runtime"]=rt
    rt.setdefault("grace_map", {})
    rt["grace_map"][order_id] = {"symbol": ctx["symbol"], "strategy_id": ctx["strategy_id"], "direction": direction,
                                 "grace_until": ctx["grace_until"], "exposure_pct": ctx["exposure"], "cap": ctx["cap"]}
    _write_json(LIVE_CFG, live)
    guard={"order_id": order_id, "symbol": ctx["symbol"], "direction": direction, "exposure_pct": round(ctx["exposure"],6),
           "cap": ctx["cap"], "grace_remaining_secs": max(0, ctx["grace_until"]-now)}
    _bus("post_open_guard", {"guard": guard}); _kg({"overlay":"risk_engine"}, "post_open_guard", guard)

def honor_grace_before_exposure_close(order_id: str) -> bool:
    rt=_runtime()
    gm=(rt.get("grace_map",{}) or {}).get(order_id)
    if not gm: return False
    still_in_grace = _now() < int(gm.get("grace_until", 0))
    if still_in_grace: _bus("grace_honored", {"order_id": order_id, "grace_until": gm["grace_until"]})
    return still_in_grace

# --------------------------------------------------------------------------------------
# Signal inversion overlay + propagation
# --------------------------------------------------------------------------------------
LATENCY_MS_SHORT_MAX = 500
def _regime_allows_inversion(regime_state: str, verdict_status: str) -> bool:
    r=(regime_state or "neutral").lower()
    return (str(verdict_status or "Neutral")!="Winning") and (r in ("range","ranging","chop","neutral"))
def _too_late_to_short(signal_ts, price_ts, max_latency_ms=LATENCY_MS_SHORT_MAX) -> bool:
    try: return (int(price_ts)-int(signal_ts))*1000 > max_latency_ms
    except: return True

def adjust_and_propagate_signal(signal: Dict[str,Any]) -> Dict[str,Any]:
    symbol = signal.get("symbol", "")
    side=str(signal.get("side","")).upper()
    feedback_inverted = False
    
    # FEEDBACK LOOP INVERSION: Check if learning says to invert signals for this symbol
    # This takes precedence over regime-based inversion for learned symbols
    if should_invert_signal(symbol):
        original_side = side
        side = apply_signal_inversion(symbol, side)
        signal["side"] = side
        signal.setdefault("overlays", []).append(f"feedback_loop_inversion_{original_side}_to_{side}")
        feedback_inverted = True
        # Skip legacy overlay for feedback-inverted symbols - the learning takes precedence
    
    # Legacy short inversion logic for regime-based inversion
    # Only apply if not already handled by feedback loop
    if not feedback_inverted and side=="SHORT":
        regime=signal.get("regime","neutral"); verdict=signal.get("verdict_status","Neutral")
        sig_ts=int(signal.get("ts",0) or 0); price_ts=int(signal.get("price_ts", sig_ts) or sig_ts)
        if _regime_allows_inversion(regime, verdict):
            if _too_late_to_short(sig_ts, price_ts):
                signal["side"]="NO_TRADE"
                signal.setdefault("overlays", []).append("short_inversion_latency_block")
            else:
                strength=float(signal.get("strength",0.0))
                signal["side"]="LONG"; signal["strength"]=round(min(1.0, max(0.0, strength*0.85)),6)
                signal.setdefault("overlays", []).append("short_inversion_overlay")
            _bus("signal_inversion_applied", {"signal": signal}); _kg({"overlay":"signals"}, "short_inversion", signal)
    # Propagate so downstream reads updated side/strength
    live=_read_json(LIVE_CFG, default={}) or {}; rt=live.get("runtime",{}) or {}; live["runtime"]=rt
    rt.setdefault("last_signal_adjustments", [])
    rt["last_signal_adjustments"].append({"ts": _now(), "symbol": signal.get("symbol"), "side": signal.get("side"),
                                          "strength": signal.get("strength"), "overlays": signal.get("overlays", [])})
    rt["last_signal_adjustments"] = rt["last_signal_adjustments"][-200:]
    _write_json(LIVE_CFG, live)
    _bus("signal_adjustment_propagated", {"signal": signal}); _kg({"overlay":"signals"}, "adjustment_propagated", signal)
    return signal

# --------------------------------------------------------------------------------------
# Recovery cycle + fee audit + nightly digest + scheduler
# --------------------------------------------------------------------------------------
PROMOTE_EXPECTANCY = 0.55
PROMOTE_PNL        = 0.0

def _profit_verdict() -> Dict[str,Any]:
    updates=_read_jsonl(LEARN_LOG, 50000)
    v={"status":"Neutral","expectancy":0.5,"avg_pnl_short":0.0}
    for u in reversed(updates):
        if u.get("update_type")=="reverse_triage_cycle":
            s=u.get("summary",{}).get("verdict",{})
            v["status"]=s.get("verdict","Neutral")
            v["expectancy"]=float(s.get("expectancy",0.5))
            v["avg_pnl_short"]=float(s.get("pnl_short",{}).get("avg_pnl_pct",0.0))
            break
    return v

def _risk_snapshot(exec_rows: List[Dict[str,Any]]) -> Dict[str,Any]:
    dcut=_now()-24*60*60
    series=[float(t.get("pnl_pct",0.0)) for t in exec_rows if int(t.get("ts",0) or 0)>=dcut]
    cum=0.0; peak=0.0; max_dd=0.0
    for r in series: cum+=r; peak=max(peak,cum); max_dd=max(max_dd, peak-cum)
    counts=defaultdict(int); cutoff=_now()-4*60*60
    for t in exec_rows:
        ts=int(t.get("ts",0) or 0); sym=t.get("symbol"); 
        if sym and ts>=cutoff: counts[sym]+=1
    total=sum(counts.values()) or 1
    coin_exposure={sym: round(cnt/total,6) for sym,cnt in counts.items()}
    max_lev=max([float(t.get("leverage",0.0)) for t in exec_rows] or [0.0])
    return {"coin_exposure":coin_exposure,"portfolio_exposure":round(sum(coin_exposure.values()),6),"max_leverage":round(max_lev,3),"max_drawdown_24h":round(max_dd,6)}

def _profit_gate(verdict: Dict[str,Any]) -> bool:
    return verdict["status"]=="Winning" and verdict["expectancy"]>=PROMOTE_EXPECTANCY and verdict["avg_pnl_short"]>=PROMOTE_PNL
def _risk_gate(risk: Dict[str,Any], limits: Dict[str,Any]) -> bool:
    return not (risk["portfolio_exposure"]>limits["max_exposure"] or risk["max_leverage"]>limits["max_leverage"] or risk["max_drawdown_24h"]>limits["max_drawdown_24h"])

def _load_alloc_overlay() -> Dict[str,Any]:
    live=_read_json(LIVE_CFG, default={}) or {}
    return ((live.get("runtime",{}).get("alloc_overlays",{}) or {}).get("per_symbol") or {})

def run_recovery_cycle() -> Dict[str,Any]:
    live=_read_json(LIVE_CFG, default={}) or {}; rt=live.get("runtime",{}) or {}; live["runtime"]=rt
    
    # Check for manual override - skip if override is active
    override_until = rt.get("phase82_override_disable_until", 0)
    if _now() < override_until:
        # Override active - don't modify kill switch or protective settings
        return {"plan": {"next_stage": "override_active", "notes": ["phase82_override_active"]}, "verdict": {}, "risk": {}, "manual_override": False}
    
    exec_rows=_read_jsonl(EXEC_LOG, 100000)
    verdict=_profit_verdict(); risk=_risk_snapshot(exec_rows)
    limits=(rt.get("capital_limits") or DEFAULT_LIMITS)
    profit_ok=_profit_gate(verdict); risk_ok=_risk_gate(risk, limits)
    alloc=_load_alloc_overlay()
    winners=[s for s,dec in alloc.items() if "winner_symbol" in dec.get("notes",[])]
    break_even=[s for s,dec in alloc.items() if "break_even_symbol" in dec.get("notes",[])]
    stage=rt.get("restart_stage","frozen")
    
    manual_override = bool(rt.get("force_unfreeze", False))
    if manual_override:
        if not risk_ok:
            plan={"next_stage":"stage_a","size_throttle":0.25,"enable_symbols":[],"notes":["manual_override_with_risk_limits"]}
        else:
            plan={"next_stage":"stage_a","size_throttle":0.5,"enable_symbols":[],"notes":["manual_override_enabled"]}
    elif not (profit_ok and risk_ok):
        plan={"next_stage":"frozen","size_throttle":0.0,"enable_symbols":[],"notes":["gates_not_passed"]}
    elif stage in ("frozen","stage_a"):
        plan={"next_stage":"stage_a","size_throttle":0.25,"enable_symbols":winners,"notes":["stage_a_enable_winners"]}
    elif stage=="stage_b":
        plan={"next_stage":"stage_b","size_throttle":0.50,"enable_symbols":winners+break_even,"notes":["stage_b_enable_break_even"]}
    elif stage=="stage_c":
        plan={"next_stage":"stage_c","size_throttle":0.75,"enable_symbols":winners+break_even,"notes":["stage_c_broad_enable"]}
    else:
        plan={"next_stage":"full","size_throttle":1.00,"enable_symbols":winners+break_even,"notes":["full_resume"]}
    rt["restart_stage"]=plan["next_stage"]; rt["size_throttle"]=plan["size_throttle"]; rt["allowed_symbols"]=plan["enable_symbols"]; rt["protective_mode"]=(plan["next_stage"]!="full"); rt["kill_switch_phase82"]=(plan["next_stage"]=="frozen")
    _write_json(LIVE_CFG, live)
    _bus("recovery_cycle", {"plan": plan, "verdict": verdict, "risk": risk, "limits": limits, "manual_override": manual_override}); _kg({"overlay":"kill_switch"}, "restart_plan", plan)
    return {"plan": plan, "verdict": verdict, "risk": risk, "manual_override": manual_override}

def run_fee_venue_audit() -> Dict[str,Any]:
    fees=_fee_baseline(_read_jsonl(EXEC_LOG, 100000))
    high=[sym for sym, v in fees.items() if v["avg_fee"]>1.0]
    live=_read_json(LIVE_CFG, default={}) or {}; rt=live.get("runtime",{}) or {}; live["runtime"]=rt
    rt.setdefault("fee_quarantine", {})
    for sym in high:
        rt["fee_quarantine"][sym] = {"status":"quarantined","reason":"avg_fee_high","avg_fee": fees[sym]["avg_fee"], "ts": _now()}
    for sym in list(rt["fee_quarantine"].keys()):
        if sym not in high: rt["fee_quarantine"].pop(sym, None)
    _write_json(LIVE_CFG, live)
    _bus("fee_venue_audit", {"fees": fees, "quarantined": high}); _kg({"overlay":"fees"}, "quarantine_updates", {"symbols": high, "fees": fees})
    return {"fees": fees, "quarantined": high}

def nightly_learning_digest() -> Dict[str,Any]:
    exec_rows=_read_jsonl(EXEC_LOG, 100000); sig_rows=_read_jsonl(SIG_LOG, 100000)
    last_day=_now()-24*60*60
    trades=[t for t in exec_rows if int(t.get("ts",0) or 0)>=last_day]
    blocked=[s for s in sig_rows if str(s.get("status",""))=="blocked" and int(s.get("ts",0) or 0)>=last_day]
    wins=sum(1 for t in trades if float(t.get("pnl_pct",0.0))>0); wr= (wins/len(trades)) if trades else 0.0
    net=sum(float(t.get("net_pnl",0.0)) for t in trades)
    fees=_fee_baseline(exec_rows); notional=float((_runtime().get("default_notional_usd", 1000.0)))
    missed=0.0
    for s in blocked:
        fb=fees.get(s.get("symbol",""), {"avg_fee":1.0,"avg_slippage":0.0008})
        comp=float(s.get("composite",0.0)); ofi=float(s.get("ofi_score",0.0))
        missed += (comp*ofi*notional) - fb["avg_fee"] - fb["avg_slippage"]*notional
    digest={"trades_count": len(trades), "win_rate": round(wr,4), "net_pnl": round(net,2), "blocked_count": len(blocked), "missed_counterfactual_net": round(missed,2)}
    _bus("nightly_learning_digest", {"digest": digest}); _kg({"overlay":"learning_digest"}, "daily", digest)
    return digest

def start_scheduler(interval_secs: int = 600):
    _bus("scheduler_start", {"interval_secs": interval_secs}); _kg({"overlay":"scheduler"}, "start", {"interval_secs": interval_secs})
    last_digest_day = None
    last_advisor_hour = -1
    while True:
        try:
            run_fee_venue_audit()
            run_recovery_cycle()
            utc_h = int(time.gmtime().tm_hour)
            utc_min = int(time.gmtime().tm_min)
            utc_d = int(time.gmtime().tm_yday)
            if utc_h == 7 and last_digest_day != utc_d:
                nightly_learning_digest()
                last_digest_day = utc_d
            if utc_min == 0 and utc_h != last_advisor_hour:
                try:
                    if STRATEGIC_ADVISOR is not None:
                        STRATEGIC_ADVISOR.run_hourly_analysis()
                        _bus("strategic_advisor_hourly", {"hour": utc_h})
                    last_advisor_hour = utc_h
                except Exception as advisor_err:
                    _bus("strategic_advisor_error", {"error": str(advisor_err)})
        except Exception as e:
            _bus("scheduler_error", {"error": str(e)})
        time.sleep(interval_secs)

# --------------------------------------------------------------------------------------
# Entry orchestration + hooks for bot_cycle
# --------------------------------------------------------------------------------------
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
    Orchestrates sizing→fee/exposure gate→order→grace window wiring.
    - open_order_fn: callable(symbol, side, strategy_id, notional_usd) -> order_id
    """
    ensure_modes_defaults()
    rt=_runtime()
    
    # Explicitly capture bot_type from parameter (avoid scope issues)
    current_bot_type = bot_type
    signal_inverted = False
    original_side = side
    
    # ═══════════════════════════════════════════════════════════════
    # COUNTER-SIGNAL ORCHESTRATOR (Opportunistic Signal Inversion)
    # If Alpha is predictably losing, INVERT signals to profit from predictability
    # KEY: When inversion is active, we BYPASS streak filter (that's the point!)
    # ═══════════════════════════════════════════════════════════════
    try:
        from src.counter_signal_orchestrator import get_signal_decision
        decision = get_signal_decision(symbol, side)
        if decision.get("inverted"):
            side = decision["direction"]
            signal_inverted = True
            current_bot_type = "beta"
            _bus("signal_inverted", {"symbol": symbol, "original": original_side, "inverted_to": side, 
                                     "reason": decision.get("reason"), "confidence": decision.get("confidence")})
            _kg({"overlay":"counter_signal", "symbol": symbol}, "inversion_applied", 
                {"from": original_side, "to": side, "confidence": decision.get("confidence")})
    except Exception as e:
        pass
    
    # ═══════════════════════════════════════════════════════════════
    # STREAK FILTER (Adjust size after losses - NEVER BLOCK)
    # User directive: "Make money, don't play defense"
    # ═══════════════════════════════════════════════════════════════
    streak_mult = 1.0
    if not signal_inverted:
        try:
            from src.streak_filter import check_streak_gate
            streak_allowed, streak_reason, streak_mult = check_streak_gate(symbol, side, current_bot_type)
            if not streak_allowed:
                # EXPLORATION MODE: Convert block to size reduction (0.5x)
                print(f"   ⚠️ [STREAK] {symbol}: Streak filter would block → reducing to 0.5x instead")
                streak_mult = 0.5
                _bus("streak_reduced", {"symbol": symbol, "reason": streak_reason, "mult": streak_mult})
        except Exception as e:
            streak_mult = 1.0
    else:
        _bus("streak_filter_bypassed", {"symbol": symbol, "reason": "inversion_active", "original_side": original_side})
        streak_mult = 1.0
    
    # ═══════════════════════════════════════════════════════════════
    # TREND INCEPTION DETECTOR (Leading indicators for trend starts)
    # Boosts entries when inception signals align, suppresses when opposing
    # ═══════════════════════════════════════════════════════════════
    inception_mult = 1.0
    try:
        from src.trend_inception_detector import should_boost_entry
        should_boost, inception_mult, inception_reason = should_boost_entry(symbol, side)
        if inception_mult != 1.0:
            _bus("trend_inception_check", {"symbol": symbol, "side": side, "boost": should_boost, 
                                           "multiplier": inception_mult, "reason": inception_reason})
            if inception_mult < 1.0:
                print(f"   ⚠️ [INCEPTION] {symbol}: Trend inception opposes {side} → size reduced")
    except Exception as e:
        inception_mult = 1.0
    
    # ═══════════════════════════════════════════════════════════════
    # INTELLIGENCE GATE (CoinGlass market alignment - SIZING ONLY)
    # User directive: "Make money, don't play defense"
    # ═══════════════════════════════════════════════════════════════
    intel_mult = 1.0
    try:
        from src.intelligence_gate import intelligence_gate
        signal = {"symbol": symbol, "action": side.upper()}
        intel_allowed, intel_reason, intel_mult = intelligence_gate(signal)
        if not intel_allowed:
            # EXPLORATION MODE: Convert block to size reduction (0.5x)
            print(f"   ⚠️ [INTEL] {symbol}: Intelligence gate would block → reducing to 0.5x instead")
            intel_mult = 0.5
            _bus("intel_reduced", {"symbol": symbol, "reason": intel_reason, "mult": intel_mult})
    except Exception as e:
        intel_mult = 1.0
    
    # Apply sizing multipliers from gates (including trend inception)
    combined_mult = streak_mult * intel_mult * inception_mult
    adjusted_notional = base_notional_usd * combined_mult
    
    # ═══════════════════════════════════════════════════════════════
    # FEE-AWARE GATE (Sizing adjustment, NEVER BLOCKS)
    # User directive: "Make money, don't play defense"
    # ═══════════════════════════════════════════════════════════════
    fee_mult = 1.0
    if FEE_AWARE_GATE is not None:
        try:
            edge_pct = (expected_edge_hint * 100) if expected_edge_hint is not None else 0.5
            fee_result = FEE_AWARE_GATE.evaluate_entry(symbol, side, edge_pct, adjusted_notional, is_market=True)
            if not fee_result.get("allow", True):
                # EXPLORATION MODE: Convert block to size increase to overcome fees
                print(f"   ⚠️ [FEE] {symbol}: Fee gate would block → boosting size to $200 minimum")
                adjusted_notional = max(adjusted_notional, 200.0)
                _bus("fee_reduced", {"symbol": symbol, "reason": fee_result.get("reason", ""), "action": "size_boost"})
        except Exception as fee_err:
            _bus("fee_gate_error", {"symbol": symbol, "error": str(fee_err)})
    
    allowed = rt.get("allowed_symbols_mode", [])
    if allowed and symbol not in allowed:
        reason={"skip":"symbol_not_allowed_in_mode","symbol":symbol,"allowed":allowed}
        _bus("entry_skipped", {"symbol": symbol, "reason": reason}); _kg({"overlay":"entry_gate","symbol":symbol}, "skip", reason)
        return False, {"reason": reason}
    final_notional = size_after_adjustment(symbol, strategy_id, adjusted_notional, rt)
    ok, ctx = pre_entry_check(symbol, strategy_id, final_notional, portfolio_value_snapshot_usd,
                              (rt.get("capital_limits") or DEFAULT_LIMITS), regime_state, verdict_status, expected_edge_hint)
    if not ok:
        # EXPLORATION MODE: Reduce size instead of blocking
        print(f"   ⚠️ [PRE-CHECK] {symbol}: Pre-entry check would block → reducing to $200 minimum")
        final_notional = 200.0
        _bus("pre_entry_reduced", {"symbol": symbol, "strategy_id": strategy_id, "reduced_to": final_notional})
    
    # ═══════════════════════════════════════════════════════════════
    # CORRELATION THROTTLE (Reduce size for correlated positions)
    # ═══════════════════════════════════════════════════════════════
    if CORRELATION_THROTTLE is not None:
        try:
            open_positions = get_open_positions()
            throttle_result = CORRELATION_THROTTLE.check_throttle(
                symbol, side, final_notional, open_positions, portfolio_value_snapshot_usd
            )
            if throttle_result.get("throttled", False):
                old_notional = final_notional
                final_notional = throttle_result.get("throttled_size", final_notional)
                _bus("correlation_throttle_applied", {
                    "symbol": symbol, "original": old_notional, "throttled": final_notional,
                    "reason": throttle_result.get("reason", "")
                })
                print(f"   ⚠️ [CORR-THROTTLE] {symbol}: ${old_notional:.2f} → ${final_notional:.2f}")
        except Exception as throttle_err:
            _bus("correlation_throttle_error", {"symbol": symbol, "error": str(throttle_err)})
    
    try:
        order_id = open_order_fn(symbol=symbol, side=side, strategy_id=strategy_id, notional_usd=final_notional)
        post_open_guard(ctx, direction=side, order_id=order_id)
        _bus("entry_placed", {"symbol": symbol, "strategy_id": strategy_id, "order_id": order_id, "final_notional": final_notional})
        _kg({"overlay":"execution","symbol":symbol}, "order_opened", {"order_id": order_id, "side": side, "notional_usd": final_notional})
        return True, {"order_id": order_id, "final_notional": final_notional}
    except Exception as e:
        _bus("entry_error", {"symbol": symbol, "strategy_id": strategy_id, "error": str(e)})
        return False, {"error": str(e)}

# --------------------------------------------------------------------------------------
# Blofin Futures bridge (micro-live safe defaults)
# --------------------------------------------------------------------------------------
# NOTE: Replace stubs with your actual Blofin client. This bridge enforces micro-live safety:
#  - Converts notional USD to quantity using last price
#  - Applies leverage caps from runtime
#  - Uses isolated margin by default (safer), and reduces size for quarantined symbols
def _get_last_price(symbol: str) -> float:
    # TODO: integrate Blofin price endpoint; for now read from a cache or default
    cache=_read_json("price_cache.json", default={}) or {}
    return float(cache.get(symbol, 2000.0))  # default price if not available

def _usd_to_qty(symbol: str, notional_usd: float) -> float:
    px=_get_last_price(symbol)
    qty = notional_usd / max(px, 1e-9)
    return round(qty, 6)

def blofin_open_order_fn(symbol: str, side: str, strategy_id: str, notional_usd: float) -> str:
    # Respect fee quarantine downsizing (already applied by sizing_after_adjustment)
    rt=_runtime()
    lev = float((rt.get("capital_limits") or DEFAULT_LIMITS).get("max_leverage", 3.0))
    qty = _usd_to_qty(symbol, notional_usd)
    params = {
        "symbol": symbol,
        "side": side.upper(),         # "LONG"/"SHORT" mapped to "BUY"/"SELL" in the real client
        "strategy_id": strategy_id,
        "quantity": qty,
        "mode": "isolated",           # safer default
        "leverage": lev,
        "reduce_only": False,         # set True for closes
        "time_in_force": "GTC"
    }
    # TODO: call your real Blofin client here, e.g., client.place_order(**params)
    order_id = f"blofin-{symbol}-{side}-{int(notional_usd)}-{_now()}"
    _bus("blofin_order_opened", {"params": params, "order_id": order_id})
    _kg({"overlay":"blofin_bridge"}, "order_open", {"params": params, "order_id": order_id})
    return order_id

# --------------------------------------------------------------------------------------
# UNIFIED GATE ENFORCEMENT (v7.2) - All paths pass same protections
# --------------------------------------------------------------------------------------
def _get_runtime_flags(live_cfg: dict = None) -> Dict[str,Any]:
    """Read global protection flags from live_config (None-safe).
    
    Respects operator_override from dedicated file (logs/operator_override.json).
    This file is not touched by governance systems, ensuring override persists.
    """
    import time
    import os
    
    if live_cfg is None:
        live_cfg = _read_json(LIVE_CFG, default={}) or {}
    rt = (live_cfg.get("runtime", {}) or {})
    
    # Check for operator override from DEDICATED FILE first (survives governance rewrites)
    override_file = "logs/operator_override.json"
    if os.path.exists(override_file):
        try:
            with open(override_file) as f:
                override = json.load(f)
            if override.get("enabled", False):
                expires_at = override.get("expires_at", 0)
                if expires_at > time.time():
                    # Override is active - return permissive flags
                    return {
                        "kill_switch": False,
                        "protective_mode": False,
                        "size_throttle": 1.0,
                        "restart_stage": "running",
                        "max_exposure": 0.60,
                        "operator_override_active": True,
                    }
        except:
            pass  # File corrupt or missing, continue with normal checks
    
    # Handle kill_switch_phase82 as either bool or dict with global_block field
    ks = rt.get("kill_switch_phase82", False)
    if isinstance(ks, dict):
        kill_switch_active = bool(ks.get("global_block", False))
    else:
        kill_switch_active = bool(ks)
    
    return {
        "kill_switch": kill_switch_active,
        "protective_mode": bool(rt.get("protective_mode", False)),
        "size_throttle": float(rt.get("size_throttle") if rt.get("size_throttle") is not None else 1.0),
        "restart_stage": (rt.get("restart_stage") or ""),
        "max_exposure": float(rt.get("max_exposure") if rt.get("max_exposure") is not None else 0.60),
        "operator_override_active": False,
    }

def _get_symbol_controls(live_cfg: dict, symbol: str) -> Dict[str,Any]:
    """Read symbol-level controls (allocation mult, quarantine status)."""
    if live_cfg is None:
        live_cfg = _read_json(LIVE_CFG, default={}) or {}
    rt = (live_cfg.get("runtime", {}) or {})
    alloc = ((rt.get("alloc_overlays", {}) or {}).get("per_symbol", {}) or {}).get(symbol, {})
    fee_quarantine = (rt.get("fee_quarantine", {}) or {})
    return {
        "symbol_mult": float(alloc.get("size_multiplier", 1.0) if alloc.get("size_multiplier") is not None else 1.0),
        "quarantine_mult": 0.5 if symbol in fee_quarantine else 1.0,
    }

def enforce_global_protections(symbol: str, live_cfg: dict, context: dict) -> Dict[str,Any]:
    """
    Unified global protection check. Returns hard_block=True if trading must stop,
    plus protective_downsize multiplier and reason codes for attribution.
    
    Respects operator_override from dedicated file (logs/operator_override.json).
    """
    import time
    import os
    
    if live_cfg is None:
        live_cfg = _read_json(LIVE_CFG, default={}) or {}
    
    # Check for operator override from DEDICATED FILE (survives governance rewrites)
    override_file = "logs/operator_override.json"
    if os.path.exists(override_file):
        try:
            with open(override_file) as f:
                override = json.load(f)
            if override.get("enabled", False):
                expires_at = override.get("expires_at", 0)
                if expires_at > time.time():
                    # Override is active - bypass all protections
                    return {
                        "hard_block": False,
                        "protective_downsize": 1.0,
                        "reasons": ["operator_override_active"],
                        "flags": {
                            "kill_switch": False,
                            "protective_mode": False,
                            "size_throttle": 1.0,
                            "restart_stage": "running",
                            "max_exposure": 0.60,
                        },
                    }
        except:
            pass  # File corrupt or missing, continue with normal checks
    
    flags = _get_runtime_flags(live_cfg)
    reasons = []
    hard_block = False

    if flags["kill_switch"]:
        hard_block = True
        reasons.append("kill_switch_phase82_block")

    protective_downsize = 1.0
    if flags["protective_mode"]:
        protective_downsize = 0.5
        reasons.append("protective_mode_active")
        regime = (context.get("regime_state") or "").lower()
        if regime in ("chop", "range"):
            reasons.append("protective_mode_regime_penalty")

    throttle = flags["size_throttle"]
    if throttle <= 0.0:
        reasons.append("size_throttle_zero")

    return {
        "hard_block": hard_block,
        "protective_downsize": protective_downsize,
        "reasons": reasons,
        "flags": flags,
    }

def unified_pre_entry_gate(symbol: str,
                           expected_edge_hint: float,
                           final_notional_usd: float,
                           portfolio_value_snapshot_usd: float,
                           flags: dict) -> Tuple[bool, Dict[str,Any]]:
    """
    Unified pre-entry gate (fee + exposure) with full attribution.
    Returns (ok, attribution_dict).
    """
    edge_after_cost = _expected_edge_after_cost(symbol, expected_edge_hint)
    fee_gate_ok = edge_after_cost >= 0.0

    max_exp = flags.get("max_exposure", 0.60)
    exposure_pct, cap, diag = _audit_exposure(
        symbol, final_notional_usd, portfolio_value_snapshot_usd,
        {"max_exposure": max_exp}
    )
    exposure_gate_ok = exposure_pct <= (max_exp * 1.10)

    reason_codes = []
    if not fee_gate_ok:
        reason_codes.append("fee_gate_block")
    if not exposure_gate_ok:
        reason_codes.append("exposure_gate_block")

    ok = fee_gate_ok and exposure_gate_ok

    attribution = {
        "ts": _now(),
        "update_type": "gate_attribution",
        "symbol": symbol,
        "edge_after_cost": round(edge_after_cost, 6),
        "fee_gate_ok": fee_gate_ok,
        "exposure_pct": round(exposure_pct, 6),
        "cap": cap,
        "exposure_gate_ok": exposure_gate_ok,
        "final_notional_usd": round(final_notional_usd, 2),
        "reason_codes": reason_codes if reason_codes else ["passed_all"],
    }
    _bus("gate_attribution", attribution)
    _kg({"overlay":"gate_engine","symbol":symbol}, "decision", attribution)

    return ok, attribution

def compose_final_size(symbol: str,
                       base_notional_usd: float,
                       live_cfg: dict,
                       context: dict) -> float:
    """
    Unified sizing composer - routes ALL sizing through size_after_adjustment.
    This ensures throttle, quarantine, and protective mode are ALWAYS applied.
    """
    flags = _get_runtime_flags(live_cfg)
    sym_ctrl = _get_symbol_controls(live_cfg, symbol)

    protective_mult = 0.5 if flags["protective_mode"] else 1.0
    mtf_mult = float(context.get("mtf_size_mult") if context.get("mtf_size_mult") is not None else 1.0)
    desired_notional = base_notional_usd * mtf_mult * protective_mult

    throttle = flags["size_throttle"]
    final = max(0.0, desired_notional * throttle * sym_ctrl["symbol_mult"] * sym_ctrl["quarantine_mult"])

    _bus("sizing_attribution", {
        "ts": _now(),
        "symbol": symbol,
        "base_notional_usd": round(base_notional_usd, 2),
        "desired_notional_usd": round(desired_notional, 2),
        "final_notional_usd": round(final, 2),
        "mtf_mult": mtf_mult,
        "protective_mult": protective_mult,
        "size_throttle": throttle,
        "symbol_mult": sym_ctrl["symbol_mult"],
        "quarantine_mult": sym_ctrl["quarantine_mult"],
    })

    return final

def alpha_entry_wrapper(symbol: str,
                        ofi_confidence: float,
                        ensemble_score: float,
                        mtf_confidence: float,
                        expected_edge_hint: float,
                        base_notional_usd: float,
                        portfolio_value_snapshot_usd: float,
                        side: str,
                        open_order_fn) -> Tuple[bool, Dict[str,Any]]:
    """
    Alpha entry wrapper - enforces ALL unified gates before allowing entry.
    This replaces the previous Alpha bypass that skipped throttle/protective checks.
    """
    live_cfg = _read_json(LIVE_CFG, default={}) or {}
    rt = (live_cfg.get("runtime", {}) or {})
    regime_state = rt.get("regime_state", "unknown")
    
    def _log_alpha_signal(disposition: str, block_reason: str = None):
        try:
            from src.signal_universe_tracker import log_signal
            from src.exchange_gateway import ExchangeGateway
            gw = ExchangeGateway()
            entry_price = gw.get_price(symbol, venue="futures")
            log_signal(
                symbol=symbol,
                side=side.upper(),
                disposition=disposition,
                intelligence={
                    "ofi": ofi_confidence,
                    "ensemble": ensemble_score,
                    "mtf_confidence": mtf_confidence,
                    "regime": regime_state,
                    "expected_roi": expected_edge_hint,
                    "volatility": 0.0,
                    "entry_price": entry_price
                },
                block_reason=block_reason
            )
        except Exception as e:
            pass
    
    # BETA BOT PROCESSING - Independent parallel strategy
    # Beta receives same signals but processes with F-tier inversion logic
    try:
        from src.beta_trading_engine import get_beta_engine
        beta_engine = get_beta_engine()
        if beta_engine and beta_engine.enabled:
            beta_signal = {
                "symbol": symbol,
                "direction": side.upper(),
                "ofi": ofi_confidence,
                "ensemble": ensemble_score,
                "mtf_confidence": mtf_confidence,
                "regime": regime_state,
                "base_notional_usd": base_notional_usd,
                "entry_price": entry_price if 'entry_price' in dir() else 0
            }
            beta_result = beta_engine.process_signal(beta_signal)
            if beta_result:
                print(f"   🤖 [BETA] {symbol}: {beta_result.get('action', 'N/A')} | Tier={beta_result.get('tier', 'N/A')} | Inverted={beta_result.get('inverted', False)}")
    except Exception as e:
        print(f"   ⚠️ [BETA] Error processing {symbol}: {str(e)[:50]}")
    
    # Calculate inception multiplier for this trade (boost/suppress based on leading indicators)
    inception_mult = 1.0
    try:
        from src.trend_inception_detector import TrendInceptionDetector
        tid = TrendInceptionDetector()
        inception_score = tid.get_inception_score(symbol)
        if inception_score:
            # Align with trade direction
            signal_dir = "LONG" if side.upper() in ["BUY", "LONG"] else "SHORT"
            inception_dir = inception_score.get("composite_direction", "NEUTRAL")
            if inception_dir == signal_dir:
                inception_mult = 1.3  # Boost aligned entries
            elif inception_dir != "NEUTRAL" and inception_dir != signal_dir:
                inception_mult = 0.7  # Suppress opposing entries
    except Exception as e:
        pass  # Default to 1.0
    
    # Check for losing patterns (size adjustment, NEVER BLOCK)
    # User directive: "Make money, don't play defense"
    pattern_size_mult = 1.0
    avoid, avoid_reason = should_avoid_pattern(symbol, side, ofi_confidence)
    if avoid:
        # EXPLORATION MODE: Reduce size instead of blocking
        pattern_size_mult = 0.5
        _bus("alpha_losing_pattern_reduced", {
            "ts": _now(), "symbol": symbol, "side": side,
            "ofi": ofi_confidence, "reason": avoid_reason, "mult": pattern_size_mult
        })
        print(f"   ⚠️ [LEARNING] {symbol} {side}: Losing pattern detected → reducing to 0.5x (was block)")
    
    # COIN SELECTION ENGINE - Score this opportunity (sizing only, NEVER BLOCK)
    # User directive: "Make money, don't play defense"
    coin_size_mult = 1.0
    coin_grade = "C"
    try:
        from src.coin_selection_engine import score_opportunity
        ofi_bucket = "extreme" if ofi_confidence > 0.8 else "very_strong" if ofi_confidence > 0.7 else "strong" if ofi_confidence > 0.6 else "moderate" if ofi_confidence > 0.4 else "weak"
        ens_bucket = "strong_bull" if ensemble_score > 0.3 else "bull" if ensemble_score > 0.1 else "neutral" if ensemble_score > -0.1 else "bear" if ensemble_score > -0.3 else "strong_bear"
        
        selection = score_opportunity(symbol, side.upper(), ofi_bucket, ens_bucket, "us_morning")
        
        if not selection.get("should_trade", True):
            # EXPLORATION MODE: Reduce size instead of blocking
            coin_size_mult = 0.5
            print(f"   ⚠️ [COIN-SELECT] {symbol} {side} Grade={selection['grade']} → reducing to 0.5x (was skip)")
            _bus("coin_selection_reduced", {"symbol": symbol, "side": side, "selection": selection, "mult": coin_size_mult})
        else:
            coin_size_mult = selection.get("size_multiplier", 1.0)
            coin_grade = selection.get("grade", "C")
            if coin_size_mult != 1.0:
                print(f"   🎯 [COIN-SELECT] {symbol} {side} Grade={coin_grade} SizeMult={coin_size_mult:.2f}")
    except Exception as e:
        coin_size_mult = 1.0
        coin_grade = "C"
    
    # ═══════════════════════════════════════════════════════════════
    # EDGE-WEIGHTED SIZING (Scale size based on signal quality)
    # ═══════════════════════════════════════════════════════════════
    edge_size_mult = 1.0
    if EDGE_WEIGHTED_SIZER is not None:
        try:
            signal_meta = {
                "grade": coin_grade,
                "ofi_score": ofi_confidence,
                "ensemble_score": ensemble_score,
                "mtf_confidence": mtf_confidence,
                "symbol": symbol,
                "side": side.upper()
            }
            adjusted_size, edge_mult, edge_reason = EDGE_WEIGHTED_SIZER.compute_size(base_notional_usd, signal_meta)
            if edge_mult != 1.0:
                edge_size_mult = edge_mult
                print(f"   📏 [EDGE-SIZER] {symbol} {side} Grade={coin_grade}: {edge_mult:.2f}x sizing ({edge_reason})")
                _bus("edge_sizing_applied", {
                    "symbol": symbol, "grade": coin_grade, "multiplier": edge_mult,
                    "reason": edge_reason, "original": base_notional_usd, "adjusted": adjusted_size
                })
        except Exception as edge_err:
            _bus("edge_sizing_error", {"symbol": symbol, "error": str(edge_err)})
    
    coin_size_mult = coin_size_mult * edge_size_mult
    
    # Check symbol bias - warn if going against preferred direction
    preferred_dir, advantage = get_symbol_bias(symbol)
    if preferred_dir and preferred_dir != side.upper() and advantage > 10:
        _bus("alpha_bias_warning", {
            "ts": _now(), "symbol": symbol, "side": side,
            "preferred": preferred_dir, "advantage": advantage
        })
        print(f"   ⚠️ [BIAS] {symbol} {side} vs preferred {preferred_dir} (${advantage:.0f} advantage)")
    
    # === PROFIT-SEEKING OPPORTUNITY SCORING ===
    # Instead of defensive filters, use expected profit scoring
    if OPPORTUNITY_SCORER is not None:
        try:
            current_hour = datetime.now().hour
            
            opp_result = OPPORTUNITY_SCORER.score_opportunity(symbol, side.upper(), ofi_confidence, ensemble_score, current_hour)
            expected_edge = opp_result.get("expected_edge", 0)
            win_prob = opp_result.get("win_probability", 0) * 100
            recommendation = opp_result.get("recommendation", "NEUTRAL")
            is_winning_pattern = opp_result.get("is_winning_pattern", False)
            
            if is_winning_pattern:
                print(f"   🏆 [PROFIT-SEEKER] {symbol} {side}: ***TOP WINNING PATTERN*** Edge=${expected_edge:.4f}, WR={win_prob:.0f}%")
                for reason in opp_result.get("reasoning", []):
                    print(f"      → {reason}")
            else:
                print(f"   📊 [PROFIT-SEEKER] {symbol} {side}: Edge=${expected_edge:.4f}, WR={win_prob:.0f}%, Rec={recommendation}")
            
            if not opp_result.get("should_trade", False) and not is_winning_pattern:
                # CHANGED 2025-12-02: Warn-only mode for 24h to restore trade flow
                # Previously: Blocked trades entirely. Now: Log warning, allow trade with reduced size
                _log_alpha_signal("warned", f"Profit-seeker WARN (not block): Edge=${expected_edge:.4f}, Rec={recommendation}")
                print(f"   ⚠️ [PROFIT-SEEKER] WARNING {symbol} {side}: Negative edge (${expected_edge:.4f}) - allowing with reduced size")
                # Reduce size by 50% instead of blocking completely
                coin_size_mult = coin_size_mult * 0.5
            
            if expected_edge > 0.1:
                edge_size_mult = min(1.5, 1.0 + expected_edge)
                coin_size_mult = coin_size_mult * edge_size_mult
                print(f"   💰 [EDGE-BOOST] Increased size by {edge_size_mult:.2f}x due to positive edge")
        except Exception as e:
            print(f"   ⚠️ [PROFIT-SEEKER] Error scoring opportunity: {e}")
            import traceback
            traceback.print_exc()
    else:
        print(f"   ⚠️ [PROFIT-SEEKER] Module not loaded, using legacy logic")
    
    ofi_threshold = get_ofi_threshold(symbol, side)
    
    if ofi_confidence < ofi_threshold or ensemble_score < 0.05:
        _bus("alpha_prequal_block", {
            "ts": _now(), "symbol": symbol,
            "ofi_confidence": ofi_confidence,
            "ensemble_score": ensemble_score,
            "ofi_threshold": ofi_threshold,
            "reason": "alpha_thresholds_not_met"
        })
        _log_alpha_signal("blocked", f"Alpha thresholds not met: OFI={ofi_confidence:.2f}<{ofi_threshold:.2f} or ENS={ensemble_score:.2f}<0.05")
        return False, {"reason": "alpha_thresholds_not_met", "ofi_threshold": ofi_threshold}
    
    # 2025-12-09: OFI-BASED SIZING MULTIPLIER
    # Analysis showed ALL trades were "medium" OFI with 22% WR and -$0.36 EV
    # Strong/very_strong OFI signals should get larger sizes, medium should get reduced
    ofi_size_mult = 1.0
    if ofi_confidence >= 0.80:
        ofi_size_mult = 1.5  # Very strong OFI - max boost
        print(f"   🔥 [OFI-STRONG] {symbol} {side}: OFI={ofi_confidence:.2f} → 1.5x sizing boost")
    elif ofi_confidence >= 0.60:
        ofi_size_mult = 1.2  # Strong OFI - moderate boost
        print(f"   ✅ [OFI-GOOD] {symbol} {side}: OFI={ofi_confidence:.2f} → 1.2x sizing boost")
    elif ofi_confidence >= 0.40:
        ofi_size_mult = 0.7  # Medium OFI - REDUCE size (these were losing)
        print(f"   ⚠️ [OFI-MEDIUM] {symbol} {side}: OFI={ofi_confidence:.2f} → 0.7x reduced sizing")
    # Below 0.40 is already blocked by threshold

    gp = enforce_global_protections(symbol, live_cfg, {"regime_state": regime_state})
    if gp["hard_block"]:
        _bus("entry_blocked_global", {"ts": _now(), "symbol": symbol, "reasons": gp["reasons"]})
        _log_alpha_signal("blocked", f"Global protection: {', '.join(gp['reasons'])}")
        return False, {"reason": "global_protection_block", "reasons": gp["reasons"]}

    mtf_size_mult = 0.5 * (0.5 + float(mtf_confidence if mtf_confidence is not None else 0.0) * 0.5)
    final_notional = compose_final_size(
        symbol=symbol,
        base_notional_usd=base_notional_usd,
        live_cfg=live_cfg,
        context={"mtf_size_mult": mtf_size_mult, "regime_state": regime_state}
    )
    
    # Apply coin selection sizing multiplier (from learning-based grading)
    final_notional = final_notional * coin_size_mult
    
    # Apply pattern-based sizing multiplier (losing pattern detection)
    final_notional = final_notional * pattern_size_mult
    
    # Apply inception multiplier from trend inception detector (boost/suppress based on leading indicators)
    final_notional = final_notional * inception_mult
    if inception_mult != 1.0:
        print(f"   📡 [INCEPTION] {symbol} {side}: Size adjusted by {inception_mult:.2f}x (trend inception {'aligned' if inception_mult > 1.0 else 'opposing'})")
    
    # Apply OFI-based sizing multiplier (2025-12-09 improvement)
    final_notional = final_notional * ofi_size_mult
    
    # === PROFIT-SEEKING INTELLIGENCE (Phase 15.0 + ML) ===
    # Apply ML-driven sizing: boost winning patterns, reduce (never block) weak ones
    current_hour = datetime.utcnow().hour
    
    try:
        from src.profit_seeking_sizer import get_profit_seeking_size
        profit_size, profit_attr = get_profit_seeking_size(
            symbol=symbol,
            direction=side.upper(),
            base_size=final_notional,
            ofi=ofi_confidence,
            ensemble_score=ensemble_score
        )
        
        if profit_attr.get("combined_multiplier", 1.0) != 1.0:
            mult = profit_attr["combined_multiplier"]
            print(f"   💰 [PROFIT-SEEK] {symbol} {side}: {mult:.2f}x ({profit_attr.get('pattern_reason', 'n/a')})")
            final_notional = profit_size
    except Exception as e:
        print(f"   ⚠️ [PROFIT-SEEK] Error (non-blocking): {e}")
    
    accelerated_size, accel_details = apply_profitability_acceleration(
        symbol=symbol,
        direction=side.upper(),
        ofi=ofi_confidence,
        base_size=final_notional,
        current_hour=current_hour
    )
    
    # EXPLORATION MODE: Never block on time-of-day, just adjust size
    # User directive: "Make money, don't play defense"
    if accel_details.get("blocked"):
        # Convert block to 0.5x sizing instead
        print(f"   ⏰ [TOD-REDUCED] {symbol}: Time slot reduced sizing (was blocked) → continuing at 0.5x")
        final_notional = final_notional * 0.5
    elif accel_details.get("total_multiplier", 1.0) != 1.0:
        final_notional = accelerated_size
        
        pattern_info = accel_details.get("pattern_boost", {})
        if pattern_info.get("is_top_pattern"):
            print(f"   🏆 [TOP-PATTERN] {symbol} {side}: {pattern_info.get('pattern', 'unknown')} → 1.5x sizing!")

    # EXPLORATION MODE: Never block on zero size, enforce $200 floor instead
    if final_notional <= 0.0:
        print(f"   ⚠️ [SIZE-RESCUE] {symbol}: Size was $0 → setting to $200 minimum floor")
        final_notional = 200.0

    # ═══════════════════════════════════════════════════════════════
    # CRITICAL: ENFORCE $200 MINIMUM POSITION SIZE (Final Gate)
    # User policy: Quality over quantity, $200-$2000 per position
    # This is the LAST sizing adjustment before order placement
    # ═══════════════════════════════════════════════════════════════
    MIN_POSITION_SIZE_USD = 200.0
    if final_notional < MIN_POSITION_SIZE_USD:
        print(f"   📏 [SIZE-FLOOR] {symbol}: ${final_notional:.0f} < ${MIN_POSITION_SIZE_USD:.0f} minimum → BOOSTED to ${MIN_POSITION_SIZE_USD:.0f}")
        final_notional = MIN_POSITION_SIZE_USD

    ok, attribution = unified_pre_entry_gate(
        symbol=symbol,
        expected_edge_hint=expected_edge_hint,
        final_notional_usd=final_notional,
        portfolio_value_snapshot_usd=float(portfolio_value_snapshot_usd if portfolio_value_snapshot_usd is not None else 0.0),
        flags=_get_runtime_flags(live_cfg)
    )
    if not ok:
        _log_alpha_signal("blocked", f"Pre-entry gate: {attribution.get('reason', 'unknown')}")
        return False, {"reason": "pre_entry_gate_block", "attribution": attribution}

    try:
        order_id = open_order_fn(symbol=symbol, side=side, strategy_id="Alpha-OFI", notional_usd=final_notional)
        _log_alpha_signal("executed")
        rt = _runtime()
        grace_until = _now() + int(rt.get("post_open_grace_secs", 3) if rt.get("post_open_grace_secs") is not None else 3)
        ctx = {"symbol": symbol, "strategy_id": "Alpha-OFI", "grace_until": grace_until, "exposure": attribution["exposure_pct"], "cap": attribution["cap"]}
        post_open_guard(ctx, direction=side.lower(), order_id=order_id)
        
        # CRITICAL: Persist trade to position_manager (positions_futures.json)
        # This was missing - caused trades to log but not persist to portfolio!
        try:
            from src.position_manager import open_futures_position
            from src.exchange_gateway import ExchangeGateway
            from src.leverage_governance import choose_leverage
            
            gw = ExchangeGateway()
            entry_price = gw.get_price(symbol, venue="futures")
            direction = "LONG" if side.upper() == "BUY" else "SHORT"
            
            # DYNAMIC LEVERAGE based on signal confidence and ROI
            # Uses leverage_governance.py choose_leverage() instead of hardcoded 5x
            wallet_balance = float(portfolio_value_snapshot_usd) if portfolio_value_snapshot_usd else 10000.0
            signal_for_leverage = {
                "roi": expected_edge_hint if expected_edge_hint else 0.0,
                "confirmations": 2 if (ofi_confidence > 0.6 and abs(ensemble_score) > 0.2) else 1,
                "size": final_notional
            }
            # Get rolling expectancy from recent trades (positive = profitable)
            try:
                from src.data_registry import DataRegistry
                DR = DataRegistry()
                recent = DR.get_trades()[-50:] if DR.get_trades() else []
                wins = sum(1 for t in recent if t.get("realized_pnl", 0) > 0)
                rolling_exp = wins / len(recent) if recent else 0.5
            except:
                rolling_exp = 0.5
            
            leverage = choose_leverage(signal_for_leverage, wallet_balance, rolling_exp)
            print(f"   📊 [LEVERAGE] {symbol}: ROI={expected_edge_hint:.3f}, Conf={signal_for_leverage['confirmations']}, Exp={rolling_exp:.2f} → {leverage}x")
            
            margin_collateral = final_notional / leverage
            
            # Build signal context for learning (including gate attribution for sizing multiplier learning)
            # Note: In run_entry_flow_unified, default to "alpha" since this is the Alpha-OFI strategy
            bot_type_for_context = "alpha"
            
            # Get gate attribution from attribution dict (contains gate decisions)
            gate_attribution_alpha = attribution.get("gate_attribution", {}) if isinstance(attribution, dict) else {}
            
            # Get trading_window from pre_entry_check ctx (if available)
            trading_window = ctx.get("trading_window") if "trading_window" in ctx else "unknown"
            if trading_window == "unknown":
                # Fallback: determine from current time
                try:
                    from src.enhanced_trade_logging import is_golden_hour
                    trading_window = "golden_hour" if is_golden_hour() else "24_7"
                except:
                    trading_window = "unknown"
            
            signal_context = {
                "ofi": ofi_confidence,
                "ensemble": ensemble_score,
                "mtf": mtf_confidence,
                "regime": regime_state,
                "expected_roi": expected_edge_hint,
                "volatility": 0.0,
                "bot_type": bot_type_for_context,
                "was_inverted": False,
                "trading_window": trading_window,  # [TRADING WINDOW] Track golden_hour vs 24_7
                # [SIZING MULTIPLIER LEARNING] Store gate attribution for learning
                "gate_attribution": gate_attribution_alpha,
            }
            
            # [ML-PREDICTOR] Capture synchronized market microstructure features at entry time
            try:
                from src.realtime_features import RealtimeFeatureCapture
                from src.blofin_futures_client import BlofinFuturesClient
                
                blofin_client = BlofinFuturesClient()
                feature_capture = RealtimeFeatureCapture(blofin_client)
                entry_features = feature_capture.capture_all_features(symbol, direction)
                
                # ADD STRATEGY SIGNALS to ML features so model learns full context
                entry_features["ofi_score"] = ofi_confidence
                entry_features["ensemble_score"] = ensemble_score
                entry_features["mtf_confidence"] = mtf_confidence
                entry_features["regime"] = regime_state
                entry_features["expected_roi"] = expected_edge_hint
                entry_features["ofi_bucket"] = "extreme" if ofi_confidence > 0.8 else "very_strong" if ofi_confidence > 0.7 else "strong" if ofi_confidence > 0.6 else "moderate" if ofi_confidence > 0.4 else "weak"
                entry_features["ensemble_bucket"] = "strong_bull" if ensemble_score > 0.3 else "bull" if ensemble_score > 0.1 else "neutral" if ensemble_score > -0.1 else "bear" if ensemble_score > -0.3 else "strong_bear"
                entry_features["final_size_usd"] = final_notional
                entry_features["leverage"] = leverage
                
                # Re-log with full strategy context
                import json
                try:
                    with open("logs/entry_features.jsonl", 'a') as f:
                        f.write(json.dumps(entry_features) + '\n')
                except Exception:
                    pass
                
                # Store ALL captured features in signal_context for learning
                signal_context["ml_features"] = entry_features
                signal_context["bid_ask_imbalance"] = entry_features.get("bid_ask_imbalance", 0)
                signal_context["spread_bps"] = entry_features.get("spread_bps", 0)
                signal_context["return_5m"] = entry_features.get("return_5m", 0)
                signal_context["return_15m"] = entry_features.get("return_15m", 0)
                signal_context["return_1m"] = entry_features.get("return_1m", 0)
                signal_context["volatility_1h"] = entry_features.get("volatility_1h", 0)
                signal_context["price_trend"] = entry_features.get("price_trend", 0)
                signal_context["fear_greed"] = entry_features.get("fear_greed", 0.5)
                signal_context["intel_direction"] = entry_features.get("intel_direction", 0)
                signal_context["intel_confidence"] = entry_features.get("intel_confidence", 0)
                signal_context["depth_ratio"] = entry_features.get("depth_ratio", 1.0)
                signal_context["buy_sell_ratio"] = entry_features.get("buy_sell_ratio", 1.0)
                signal_context["buy_ratio"] = entry_features.get("buy_ratio", 0.5)
                signal_context["liq_ratio"] = entry_features.get("liq_ratio", 0.5)
                signal_context["liq_long_1h"] = entry_features.get("liq_long_1h", 0)
                signal_context["liq_short_1h"] = entry_features.get("liq_short_1h", 0)
                
                print(f"   🧠 [ML-FEATURES] Captured: imbalance={entry_features.get('bid_ask_imbalance', 0):.3f}, spread={entry_features.get('spread_bps', 0):.1f}bps, 5m_ret={entry_features.get('return_5m', 0):.2f}%")
            except Exception as feat_err:
                print(f"   ⚠️ [ML-FEATURES] Capture error (non-blocking): {feat_err}")
            
            pos_result = open_futures_position(
                symbol=symbol,
                direction=direction,
                entry_price=entry_price,
                size=final_notional,
                leverage=leverage,
                strategy="Alpha-OFI",
                liquidation_price=None,
                margin_collateral=margin_collateral,
                order_id=order_id,
                signal_context=signal_context
            )
            if pos_result:
                print(f"   ✅ [ALPHA] Position persisted: {symbol} {direction} | Size: ${final_notional:.2f}")
            else:
                print(f"   ⚠️ [ALPHA] Position duplicate: {symbol} {direction} Alpha-OFI")
        except Exception as persist_err:
            print(f"   ❌ [ALPHA] Persist error: {symbol} - {persist_err}")
            _bus("alpha_persist_error", {"ts": _now(), "symbol": symbol, "error": str(persist_err)})
        
        _bus("alpha_order_placed", {
            "ts": _now(), "symbol": symbol,
            "order_id": order_id,
            "final_notional_usd": round(final_notional, 2),
            "attribution": attribution
        })
        return True, {"order_id": order_id, "final_notional": final_notional, "attribution": attribution}
    except Exception as e:
        _bus("alpha_order_error", {"ts": _now(), "symbol": symbol, "error": str(e)})
        return False, {"error": str(e)}

def run_entry_flow_unified(symbol: str,
                           strategy_id: str,
                           base_notional_usd: float,
                           portfolio_value_snapshot_usd: float,
                           regime_state: str,
                           verdict_status: str,
                           expected_edge_hint: float,
                           side: str,
                           open_order_fn) -> Tuple[bool, Dict[str,Any]]:
    """
    Unified entry flow for ALL paths (EMA-Futures, etc.) - enforces same gates as Alpha.
    """
    live_cfg = _read_json(LIVE_CFG, default={}) or {}

    gp = enforce_global_protections(symbol, live_cfg, {"regime_state": regime_state})
    if gp["hard_block"]:
        _bus("entry_blocked_global", {"ts": _now(), "symbol": symbol, "strategy_id": strategy_id, "reasons": gp["reasons"]})
        return False, {"reason": "global_protection_block", "reasons": gp["reasons"]}

    final_notional = compose_final_size(
        symbol=symbol,
        base_notional_usd=base_notional_usd,
        live_cfg=live_cfg,
        context={"mtf_size_mult": 1.0, "regime_state": regime_state}
    )
    if final_notional <= 0.0:
        _bus("entry_blocked_zero_size", {"ts": _now(), "symbol": symbol, "strategy_id": strategy_id, "reasons": gp["reasons"]})
        return False, {"reason": "size_throttle_zero", "reasons": gp["reasons"]}

    ok, attribution = unified_pre_entry_gate(
        symbol=symbol,
        expected_edge_hint=expected_edge_hint,
        final_notional_usd=final_notional,
        portfolio_value_snapshot_usd=float(portfolio_value_snapshot_usd if portfolio_value_snapshot_usd is not None else 0.0),
        flags=_get_runtime_flags(live_cfg)
    )
    if not ok:
        return False, {"reason": "pre_entry_gate_block", "attribution": attribution}

    try:
        order_id = open_order_fn(symbol=symbol, side=side, strategy_id=strategy_id, notional_usd=final_notional)
        rt = _runtime()
        grace_until = _now() + int(rt.get("post_open_grace_secs", 3) if rt.get("post_open_grace_secs") is not None else 3)
        ctx = {"symbol": symbol, "strategy_id": strategy_id, "grace_until": grace_until, "exposure": attribution["exposure_pct"], "cap": attribution["cap"]}
        post_open_guard(ctx, direction=side.lower(), order_id=order_id)
        _bus("entry_order_placed", {
            "ts": _now(), "symbol": symbol, "strategy_id": strategy_id,
            "side": side, "order_id": order_id,
            "final_notional_usd": round(final_notional, 2),
            "attribution": attribution
        })
        return True, {"order_id": order_id, "final_notional": final_notional, "attribution": attribution}
    except Exception as e:
        _bus("entry_order_error", {"ts": _now(), "symbol": symbol, "strategy_id": strategy_id, "error": str(e)})
        return False, {"error": str(e)}

def remediate_live_config(live_cfg_path: str = "live_config.json") -> Tuple[bool, str]:
    """
    Config sanity remediation - fixes None values and frozen states on startup.
    """
    try:
        cfg = _read_json(live_cfg_path, default={}) or {}
    except Exception:
        return False, "live_config_load_error"

    rt = cfg.get("runtime", {}) or {}
    changed = False

    if rt.get("default_notional_usd") is None:
        rt["default_notional_usd"] = 300.0
        changed = True
    if (rt.get("restart_stage") or "") == "frozen":
        rt["restart_stage"] = "stage_a"
        changed = True
    if rt.get("size_throttle") is None:
        rt["size_throttle"] = 0.5
        changed = True

    cfg["runtime"] = rt
    if changed:
        _write_json(live_cfg_path, cfg)
        _bus("live_config_remediated", {"ts": _now(), "changes": {"default_notional_usd": rt.get("default_notional_usd"), "restart_stage": rt.get("restart_stage"), "size_throttle": rt.get("size_throttle")}})
    return True, "ok" if changed else "no_changes_needed"

# --------------------------------------------------------------------------------------
# CLI: modes, scheduler, demos
# --------------------------------------------------------------------------------------
if __name__=="__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--set-paper", action="store_true", help="Enable paper mode")
    parser.add_argument("--set-live", action="store_true", help="Enable micro-live mode")
    parser.add_argument("--scheduler", action="store_true", help="Start 10-min scheduler (fee audits + recovery + nightly digest)")
    parser.add_argument("--signal-demo", action="store_true", help="Run a demo signal adjustment")
    parser.add_argument("--entry-demo", action="store_true", help="Run a demo entry flow on ETHUSDT via Blofin bridge")
    args = parser.parse_args()

    if args.set_paper:
        set_paper_mode(True); print("Paper mode enabled.")
    if args.set_live:
        set_live_mode_micro(True); print("Micro-live mode enabled.")

    if args.scheduler:
        start_scheduler(interval_secs=600)

    if args.signal_demo:
        raw_signal = {"ts": _now(), "price_ts": _now(), "symbol":"ETHUSDT", "side":"SHORT",
                      "strength":0.6, "regime":"range", "verdict_status":"Neutral"}
        adjusted = adjust_and_propagate_signal(raw_signal)
        print(json.dumps({"adjusted_signal": adjusted}, indent=2))

    if args.entry_demo:
        ensure_modes_defaults()
        rt=_runtime()
        pv_snapshot = 4000.0
        ok, telemetry = run_entry_flow(
            symbol="ETHUSDT",
            strategy_id="ema_futures",
            base_notional_usd=float(rt.get("default_notional_usd", 50.0)),
            portfolio_value_snapshot_usd=pv_snapshot,
            regime_state="range",
            verdict_status="Neutral",
            expected_edge_hint=0.008,  # 0.8% expected move
            side="LONG",
            open_order_fn=blofin_open_order_fn
        )
        print(json.dumps({"ok": ok, "telemetry": telemetry}, indent=2))