"""
Futures Ladder Exits: Tiered exit strategy with adaptive learning.
Executes positions in slices based on risk-reward targets, signal reversals, and trailing stops.
"""
import json
import time
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple

import pandas as pd


LOGS = Path("logs")
CONFIGS = Path("configs")
FEATURE_STORE = Path("feature_store")

_timing_rules_cache = None
_timing_rules_loaded_at = 0


def load_json(path: Path, fallback=None):
    """Load JSON file with fallback."""
    try:
        with open(path, "r") as f:
            return json.load(f)
    except:
        return fallback if fallback is not None else {}


def save_json(path: Path, data: Dict[str, Any]):
    """Save data to JSON file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        json.dump(data, f, indent=2)


def load_timing_rules(force_reload: bool = False) -> Dict[str, Any]:
    """
    Load learned timing rules from feature store.
    Caches for 60 seconds to reduce disk I/O.
    
    Returns:
        Dict with pattern-specific timing recommendations
    """
    global _timing_rules_cache, _timing_rules_loaded_at
    
    if not force_reload and _timing_rules_cache and (time.time() - _timing_rules_loaded_at < 60):
        return _timing_rules_cache
    
    rules = load_json(FEATURE_STORE / "timing_rules.json", {})
    _timing_rules_cache = rules
    _timing_rules_loaded_at = time.time()
    return rules


def get_learned_timing_rule(symbol: str, side: str, ofi: float = 0.5) -> Optional[Dict[str, Any]]:
    """
    Get learned optimal timing for a specific pattern.
    
    Args:
        symbol: Trading symbol
        side: LONG or SHORT
        ofi: OFI strength (0-1)
    
    Returns:
        Timing rule with optimal_duration, min_hold_sec, max_hold_sec, expected_ev
    """
    rules = load_timing_rules()
    if not rules:
        return None
    
    if ofi < 0.25:
        ofi_bucket = "weak"
    elif ofi < 0.5:
        ofi_bucket = "moderate"
    elif ofi < 0.75:
        ofi_bucket = "strong"
    elif ofi < 0.9:
        ofi_bucket = "very_strong"
    else:
        ofi_bucket = "extreme"
    
    pattern_key = f"{symbol}|{side.upper()}|{ofi_bucket}"
    
    if pattern_key in rules:
        return rules[pattern_key]
    
    fuzzy_key = f"{symbol}|{side.upper()}|strong"
    if fuzzy_key in rules:
        return rules[fuzzy_key]
    
    if "default" in rules:
        return rules["default"]
    
    return None


def should_suppress_early_exit(symbol: str, side: str, hold_duration_sec: float, 
                                ofi: float = 0.5) -> Tuple[bool, str]:
    """
    Check if we should suppress an early exit based on learned timing rules.
    
    Returns:
        (should_suppress, reason)
    """
    rule = get_learned_timing_rule(symbol, side, ofi)
    if not rule:
        return False, "no_rule"
    
    min_hold = rule.get("min_hold_sec", 60)
    expected_ev = rule.get("expected_ev", 0)
    optimal_duration = rule.get("optimal_duration", "unknown")
    
    if hold_duration_sec < min_hold and expected_ev > 0:
        return True, f"learned_rule:min_hold={min_hold}s,optimal={optimal_duration}"
    
    return False, "rule_allows_exit"


def load_exit_policy(symbol: str, strategy: str, regime: str) -> Dict[str, Any]:
    """
    Load ladder exit policy from config.
    
    Args:
        symbol: Trading symbol
        strategy: Strategy name
        regime: Market regime
    
    Returns:
        Policy dict with tiers_pct, trail_atr_mult, min_slice, cooldown_s
    """
    cfg = load_json(CONFIGS / "ladder_exit_policies.json", {
        "defaults": {
            "tiers_pct": [0.25, 0.25, 0.5],
            "trail_atr_mult": 2.0,
            "min_slice": 0.001,
            "cooldown_s": 30,
            "rr_targets": [1.0, 2.0]
        },
        "overrides": []
    })
    
    for override in cfg.get("overrides", []):
        symbol_match = override.get("symbol") == symbol
        strategy_match = (override.get("strategy") == strategy or 
                         override.get("strategy") == "all" or
                         (strategy.startswith("Alpha") and override.get("strategy") == "Alpha-OFI"))
        regime_match = override.get("regime") == regime or override.get("regime") == "all"
        
        if symbol_match and strategy_match and regime_match:
            base = cfg["defaults"].copy()
            base.update(override)
            return base
    
    for override in cfg.get("overrides", []):
        if override.get("symbol") == symbol and override.get("regime") == "all":
            base = cfg["defaults"].copy()
            base.update(override)
            return base
    
    return cfg["defaults"]


def calculate_atr(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> float:
    """Calculate Average True Range."""
    tr = pd.concat([
        (high - low),
        (high - close.shift(1)).abs(),
        (low - close.shift(1)).abs()
    ], axis=1).max(axis=1)
    
    atr_val = tr.rolling(period).mean().iloc[-1]
    return float(atr_val) if not pd.isna(atr_val) else 0.0


def calculate_trailing_stop(entry_price: float, current_price: float, atr_val: float, 
                            side: str, atr_mult: float) -> float:
    """
    Calculate trailing stop price.
    
    Args:
        entry_price: Entry price
        current_price: Current market price
        atr_val: ATR value
        side: "LONG" or "SHORT"
        atr_mult: ATR multiplier
    
    Returns:
        Trailing stop price
    """
    if side == "LONG":
        return max(entry_price * 0.4, current_price - atr_mult * atr_val)
    else:
        return min(entry_price * 1.6, current_price + atr_mult * atr_val)


@dataclass
class LadderSlice:
    """Represents one tier of a laddered exit."""
    pct: float
    reason: str
    qty: float = 0.0
    filled: bool = False
    fill_price: Optional[float] = None
    timestamp: Optional[str] = None


@dataclass
class LadderPlan:
    """Complete ladder exit plan for a position."""
    symbol: str
    side: str
    total_qty: float
    tiers: List[LadderSlice]
    entry_price: float
    strategy: str
    regime: str
    leverage: int


def build_ladder_plan(symbol: str, strategy: str, regime: str, side: str, 
                      total_qty: float, entry_price: float, leverage: int) -> LadderPlan:
    """
    Build ladder exit plan with tiered slices.
    
    Args:
        symbol: Trading symbol
        strategy: Strategy name
        regime: Market regime
        side: "LONG" or "SHORT"
        total_qty: Total position quantity
        entry_price: Entry price
        leverage: Leverage multiplier
    
    Returns:
        LadderPlan with initialized tiers
    """
    policy = load_exit_policy(symbol, strategy, regime)
    tiers_pct = policy.get("tiers_pct", [0.25, 0.25, 0.5])
    
    tier_sum = sum(tiers_pct)
    tiers_pct = [p / tier_sum for p in tiers_pct]
    
    tiers = []
    for pct in tiers_pct:
        qty = round(total_qty * pct, 6)
        tiers.append(LadderSlice(pct=pct, reason="pending", qty=qty))
    
    return LadderPlan(
        symbol=symbol,
        side=side,
        total_qty=total_qty,
        tiers=tiers,
        entry_price=entry_price,
        strategy=strategy,
        regime=regime,
        leverage=leverage
    )


def get_timing_intelligence(symbol: str, side: str, entry_price: float, 
                            current_price: float, position_id: str = None) -> Dict[str, Any]:
    """
    Get exit timing intelligence from position timing system.
    Returns recommendation on whether to hold longer or exit sooner.
    """
    try:
        from src.position_timing_intelligence import check_exit_timing, open_position_tracking
        
        if position_id:
            timing = check_exit_timing(position_id, current_price)
            return timing
        else:
            return {'action': 'HOLD', 'should_exit': False, 'confidence': 0.5}
    except Exception as e:
        return {'action': 'HOLD', 'should_exit': False, 'confidence': 0.5, 'error': str(e)}


def evaluate_exit_triggers(plan: LadderPlan, prices: pd.Series, high: pd.Series, low: pd.Series,
                           signal_reverse: bool = False, protective_mode: str = "OFF",
                           position_id: str = None) -> List[Tuple[int, str]]:
    """
    Evaluate which ladder tiers should be executed this cycle.
    
    Uses intelligence-driven timing:
    - HOLD_EXTENDED: Strong MTF alignment + momentum = suppress exit triggers
    - EXIT_NOW/TAKE_PROFIT: MTF degraded = accelerate exits
    
    Args:
        plan: Ladder exit plan
        prices: Price series
        high: High prices
        low: Low prices
        signal_reverse: Whether signal reversed (EMA crossover flip)
        protective_mode: Current protective mode
        position_id: Optional position tracking ID for timing intelligence
    
    Returns:
        List of (tier_index, reason) tuples
    """
    triggers = []
    current_price = float(prices.iloc[-1])
    policy = load_exit_policy(plan.symbol, plan.strategy, plan.regime)
    
    atr_val = calculate_atr(high, low, prices, period=14)
    rr_targets = policy.get("rr_targets", [2.0, 3.5])  # Raised from [1.0, 2.0] for longer holds
    
    # ============================================================
    # TIMING INTELLIGENCE: Check if we should hold longer or exit sooner
    # ============================================================
    timing = get_timing_intelligence(plan.symbol, plan.side, plan.entry_price, current_price, position_id)
    timing_action = timing.get('action', 'HOLD')
    timing_should_exit = timing.get('should_exit', False)
    timing_confidence = timing.get('confidence', 0.5)
    
    # If timing intelligence says HOLD_EXTENDED with high confidence, suppress most exits
    suppress_rr_exits = timing_action == 'HOLD_EXTENDED' and timing_confidence >= 0.7
    
    # If timing intelligence says EXIT_NOW or TAKE_PROFIT, accelerate exits
    accelerate_exit = timing_should_exit and timing_confidence >= 0.7
    
    if timing_action in ['EXIT_NOW', 'FORCE_EXIT', 'TAKE_PROFIT'] and timing_confidence >= 0.7:
        for i, tier in enumerate(plan.tiers):
            if not tier.filled:
                reason = f"timing_{timing_action.lower()}"
                triggers.append((i, reason))
                print(f"   ⏰ [TIMING] {plan.symbol}: {timing_action} ({timing_confidence:.0%}) - {', '.join(timing.get('reasons', []))}")
                break
    
    if protective_mode in ("BLOCK", "REDUCE"):
        for i, tier in enumerate(plan.tiers):
            if not tier.filled:
                triggers.append((i, "protective_reduce"))
                break
    
    # Check minimum hold time from policy before allowing any early exit
    min_hold_seconds = policy.get("min_hold_seconds", 600)  # Default 10 minutes (increased based on learning)
    hold_duration_sec_current = 0
    try:
        from src.position_timing_intelligence import _position_store
        if position_id and position_id in _position_store:
            entry_ts = _position_store[position_id].get("entry_timestamp")
            if entry_ts:
                from datetime import datetime
                hold_duration_sec_current = (datetime.now() - datetime.fromisoformat(entry_ts)).total_seconds()
    except:
        pass
    
    min_hold_reached = hold_duration_sec_current >= min_hold_seconds
    
    if signal_reverse:
        # Only allow signal_reverse exit if minimum hold time is reached
        if min_hold_reached:
            for i, tier in enumerate(plan.tiers):
                if not tier.filled:
                    triggers.append((i, "signal_reverse"))
                    break
        else:
            remaining_hold = min_hold_seconds - hold_duration_sec_current
            print(f"   ⏳ [MIN_HOLD] {plan.symbol}: Signal reversed but hold time {hold_duration_sec_current:.0f}s < {min_hold_seconds}s (wait {remaining_hold:.0f}s)")
    
    # ============================================================
    # LEARNED TIMING RULES: Apply hold duration intelligence from feedback loop
    # ============================================================
    hold_duration_sec = 0
    try:
        from src.position_timing_intelligence import _position_store
        if position_id and position_id in _position_store:
            entry_ts = _position_store[position_id].get("entry_timestamp")
            if entry_ts:
                from datetime import datetime
                hold_duration_sec = (datetime.now() - datetime.fromisoformat(entry_ts)).total_seconds()
    except:
        pass
    
    ofi = timing.get("ofi", 0.5)
    should_suppress_learned, suppress_reason = should_suppress_early_exit(
        plan.symbol, plan.side, hold_duration_sec, ofi
    )
    
    # R/R targets - but respect timing intelligence, learned rules, AND minimum hold time
    for target in rr_targets:
        target_pct = target / 100.0
        hit_target = False
        
        if plan.side == "LONG" and current_price >= plan.entry_price * (1 + target_pct):
            hit_target = True
        elif plan.side == "SHORT" and current_price <= plan.entry_price * (1 - target_pct):
            hit_target = True
        
        if hit_target:
            # CRITICAL: Enforce minimum hold time for ALL R/R exits
            if not min_hold_reached:
                remaining_hold = min_hold_seconds - hold_duration_sec_current
                print(f"   ⏳ [MIN_HOLD] {plan.symbol}: R/R target {target}% hit but hold time {hold_duration_sec_current:.0f}s < {min_hold_seconds}s (wait {remaining_hold:.0f}s)")
                continue
            
            # If timing says HOLD_EXTENDED, skip lower R/R targets
            if suppress_rr_exits and target < 3.0:
                print(f"   🔒 [TIMING] {plan.symbol}: Suppressing {target}% exit - MTF alignment strong, holding")
                continue
            
            # If learned rules say min hold not reached, suppress early exits
            if should_suppress_learned and target < 2.5:
                print(f"   📚 [LEARNED] {plan.symbol}: Suppressing {target}% exit - {suppress_reason}")
                continue
            
            for i, tier in enumerate(plan.tiers):
                if not tier.filled:
                    triggers.append((i, f"rr_hit_{target}%"))
                    break
    
    trail_mult = policy.get("trail_atr_mult", 2.0)
    
    # Widen trailing stop if timing says HOLD_EXTENDED
    if suppress_rr_exits:
        trail_mult = trail_mult * 1.5  # Wider stop to let profits run
    
    trailing_price = calculate_trailing_stop(plan.entry_price, current_price, atr_val, plan.side, trail_mult)
    
    if ((plan.side == "LONG" and current_price <= trailing_price) or 
        (plan.side == "SHORT" and current_price >= trailing_price)):
        for i in reversed(range(len(plan.tiers))):
            if not plan.tiers[i].filled:
                triggers.append((i, "trail_stop"))
                break
    
    seen = set()
    unique_triggers = []
    for idx, reason in triggers:
        if idx not in seen:
            unique_triggers.append((idx, reason))
            seen.add(idx)
    
    return unique_triggers


def execute_ladder_exits(plan: LadderPlan, triggers: List[Tuple[int, str]]) -> List[Dict[str, Any]]:
    """
    Execute ladder exit slices.
    
    Args:
        plan: Ladder exit plan
        triggers: List of (tier_index, reason) to execute
    
    Returns:
        List of execution results
    """
    from src.position_manager import close_futures_position
    
    policy = load_exit_policy(plan.symbol, plan.strategy, plan.regime)
    min_slice = policy.get("min_slice", 0.001)
    cooldown_s = policy.get("cooldown_s", 30)
    
    state = load_json(LOGS / "ladder_state.json", {"last_exec_ts": {}, "fills": []})
    last_ts = float(state["last_exec_ts"].get(plan.symbol, 0))
    now_ts = time.time()
    
    if now_ts - last_ts < cooldown_s:
        return [{"status": "cooldown", "seconds_left": round(cooldown_s - (now_ts - last_ts), 1)}]
    
    results = []
    
    for idx, reason in triggers:
        tier = plan.tiers[idx]
        
        if tier.filled or tier.qty < min_slice:
            continue
        
        try:
            from src.blofin_futures_client import BlofinFuturesClient
            client = BlofinFuturesClient()
            mark_price = client.get_mark_price(plan.symbol)
            
            success = close_futures_position(
                symbol=plan.symbol,
                strategy=plan.strategy,
                direction=plan.side,
                exit_price=mark_price,
                reason=f"ladder_{reason}",
                funding_fees=0,
                partial_qty=tier.qty
            )
            
            if success:
                tier.filled = True
                tier.fill_price = mark_price
                tier.timestamp = datetime.utcnow().isoformat()
                
                results.append({
                    "tier": idx,
                    "qty": tier.qty,
                    "reason": reason,
                    "price": mark_price,
                    "status": "executed"
                })
                
                log_ladder_exit_event(plan, idx, tier, reason)
        
        except Exception as e:
            results.append({
                "tier": idx,
                "qty": tier.qty,
                "reason": reason,
                "status": "failed",
                "error": str(e)
            })
    
    if results:
        state["last_exec_ts"][plan.symbol] = now_ts
        state["fills"].append({
            "symbol": plan.symbol,
            "timestamp": datetime.utcnow().isoformat(),
            "tiers": [(i, plan.tiers[i].qty) for i, _ in triggers]
        })
        save_json(LOGS / "ladder_state.json", state)
    
    return results


def log_ladder_exit_event(plan: LadderPlan, idx: int, tier: LadderSlice, reason: str):
    """Log ladder exit event for analytics."""
    log_file = LOGS / "ladder_exit_events.json"
    history = load_json(log_file, {"events": []})
    
    event = {
        "timestamp": datetime.utcnow().isoformat(),
        "symbol": plan.symbol,
        "side": plan.side,
        "strategy": plan.strategy,
        "regime": plan.regime,
        "leverage": plan.leverage,
        "tier_index": idx,
        "tier_pct": tier.pct,
        "qty": tier.qty,
        "reason": reason,
        "fill_price": tier.fill_price
    }
    
    history["events"].append(event)
    history["events"] = history["events"][-200:]
    
    save_json(log_file, history)
