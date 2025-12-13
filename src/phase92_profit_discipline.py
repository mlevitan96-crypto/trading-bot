"""
Phase 9.2 — Profit Discipline Pack
Overlay module enforcing profitability discipline on top of Phase 9.1 Adaptive Governance.
Implements JSON-style recommendations directly into autonomy controller logic:
- Win rate optimization (entry filters, regime gating)
- Position sizing discipline (reduce during streaks, cap exposure)
- Trade frequency control (limit trades per window, throttle signals)
- Exit optimization (tighter trailing stops, time-based exits, profit locks)
- Governance controls (freeze ramps until win rate recovers, audit signals)
"""

import time
import threading
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta
from pathlib import Path
import json
from typing import Dict, List, Optional

LOGS_DIR = Path("logs")
STATE_FILE = LOGS_DIR / "phase92_state.json"
EVENT_LOG = LOGS_DIR / "phase92_events.jsonl"

@dataclass
class Phase92Config:
    min_win_rate_pct: float = 40.0
    target_win_rate_pct: float = 60.0
    max_trades_per_4h: int = 10
    max_symbol_exposure_pct: float = 0.10
    losing_streak_threshold: int = 5
    reduce_size_pct_on_streak: float = 0.30
    min_roi_projection_pct: float = 0.25
    tighten_trailing_stop_atr: float = 1.5
    time_exit_hours: float = 6.0
    profit_lock_trigger_pct: float = 0.5
    profit_lock_reduce_pct: float = 0.25
    mtf_confidence_min: float = 0.50
    volume_boost_min: float = 1.25
    sentiment_fusion_throttle_min: int = 60
    # OVERNIGHT FIX: Tiered time-based exits to prevent positions stuck overnight
    tier1_exit_hours: float = 2.0   # Exit after 2h if losing > 0.5%
    tier2_exit_hours: float = 4.0   # Exit after 4h if gain < 0.2%
    tier3_exit_hours: float = 8.0   # Exit after 8h if gain < 0.5%
    max_hold_hours: float = 12.0    # Force exit after 12h regardless of P&L

CFG92 = Phase92Config()

_state = {
    "ramps_frozen": False,
    "last_governance_check_ts": 0,
    "signal_audit_count": 0,
    "entry_rejections": {},
    "size_adjustments": {},
    "frequency_blocks": 0,
    "exit_triggers": {},
    "started_at": None
}

def _load_state():
    global _state
    if STATE_FILE.exists():
        try:
            with open(STATE_FILE, 'r') as f:
                _state.update(json.load(f))
        except:
            pass

def _save_state():
    with open(STATE_FILE, 'w') as f:
        json.dump(_state, f, indent=2)

def _emit_event(event_type: str, data: Dict):
    """Log JSONL event"""
    LOGS_DIR.mkdir(exist_ok=True)
    event = {
        "ts": int(time.time()),
        "event": event_type,
        "data": data
    }
    with open(EVENT_LOG, 'a') as f:
        f.write(json.dumps(event) + '\n')

def _emit_dashboard_event(event_type: str, data: Dict):
    """Emit to main dashboard event log"""
    try:
        from src.phase87_89_expansion import phase87_on_any_critical_event
        phase87_on_any_critical_event(event_type, data)
    except:
        pass

# ======================================================================================
# Helpers to read existing data
# ======================================================================================

def _load_positions() -> Dict:
    """Load positions.json"""
    try:
        with open(LOGS_DIR / "positions.json", 'r') as f:
            return json.load(f)
    except:
        return {"open_positions": [], "closed_positions": []}

def _load_portfolio() -> Dict:
    """Load portfolio.json"""
    try:
        with open(LOGS_DIR / "portfolio.json", 'r') as f:
            return json.load(f)
    except:
        return {"current_value": 10000, "trades": []}

def _get_recent_trades(hours: int = 4) -> List[Dict]:
    """Get trades from last N hours"""
    portfolio = _load_portfolio()
    cutoff = datetime.now() - timedelta(hours=hours)
    recent = []
    for trade in portfolio.get("trades", []):
        try:
            ts = datetime.fromisoformat(trade.get("timestamp", "").replace('Z', '+00:00'))
            if ts.replace(tzinfo=None) >= cutoff:
                recent.append(trade)
        except:
            continue
    return recent

def _calc_strategy_win_rate(strategy: str, lookback: int = 50) -> float:
    """Calculate win rate for strategy from recent closed positions"""
    positions = _load_positions()
    closed = positions.get("closed_positions", [])[-lookback:]
    strategy_trades = [p for p in closed if p.get("strategy") == strategy]
    if not strategy_trades:
        return 50.0  # default
    wins = sum(1 for p in strategy_trades if p.get("final_roi", 0) > 0)
    return (wins / len(strategy_trades)) * 100

def _calc_global_win_rate(lookback: int = 50) -> float:
    """Calculate overall win rate from recent closed positions"""
    positions = _load_positions()
    closed = positions.get("closed_positions", [])[-lookback:]
    if not closed:
        return 50.0
    wins = sum(1 for p in closed if p.get("final_roi", 0) > 0)
    return (wins / len(closed)) * 100

def _count_recent_losses(strategy: str, lookback: int = 10) -> int:
    """Count consecutive recent losses for strategy"""
    positions = _load_positions()
    closed = positions.get("closed_positions", [])
    strategy_trades = [p for p in closed if p.get("strategy") == strategy][-lookback:]
    
    streak = 0
    for trade in reversed(strategy_trades):
        if trade.get("final_roi", 0) < 0:
            streak += 1
        else:
            break
    return streak

def _get_current_regime() -> str:
    """Get current regime from phase7.1 or default"""
    try:
        from src.phase71_predictive_stability import get_current_regime
        regime = get_current_regime()
        return regime.get("name", "stable")
    except:
        return "stable"

def _portfolio_value() -> float:
    """Get current portfolio value"""
    portfolio = _load_portfolio()
    return portfolio.get("current_value", 10000)

# ======================================================================================
# Win rate optimization
# ======================================================================================

def phase92_entry_filter(signal: Dict) -> bool:
    """
    Enforce stricter entry criteria:
    - Multi-timeframe confirmation threshold ≥0.50
    - Volume boost multiplier ≥1.25
    - ROI projection ≥0.25%
    - Disable Sentiment-Fusion in choppy regimes
    
    Returns True if signal passes all filters
    """
    reasons = []
    
    # MTF confidence check
    mtf_conf = signal.get("mtf_confidence", 1.0)
    if mtf_conf < CFG92.mtf_confidence_min:
        reasons.append(f"mtf_confidence_{mtf_conf:.2f}_below_{CFG92.mtf_confidence_min}")
    
    # Volume boost check
    vol_boost = signal.get("volume_boost", 1.0)
    if vol_boost < CFG92.volume_boost_min:
        reasons.append(f"volume_boost_{vol_boost:.2f}_below_{CFG92.volume_boost_min}")
    
    # ROI projection check
    roi_proj = signal.get("roi_projection_pct", 0) * 100  # convert to pct
    if roi_proj < CFG92.min_roi_projection_pct:
        reasons.append(f"roi_projection_{roi_proj:.2f}_below_{CFG92.min_roi_projection_pct}")
    
    # Regime filter for Sentiment-Fusion
    regime = _get_current_regime()
    if regime == "choppy" and signal.get("strategy") == "Sentiment-Fusion":
        reasons.append("sentiment_fusion_disabled_in_choppy_regime")
    
    # Track rejections
    if reasons:
        key = signal.get("strategy", "unknown")
        _state["entry_rejections"][key] = _state["entry_rejections"].get(key, 0) + 1
        _emit_event("entry_rejected", {
            "strategy": signal.get("strategy"),
            "symbol": signal.get("symbol"),
            "reasons": reasons
        })
        return False
    
    return True

# ======================================================================================
# Position sizing discipline
# ======================================================================================

def phase92_position_size(base_size: float, strategy: str, symbol: str) -> float:
    """
    Adjust position size based on streaks and win rate.
    - Reduce size by 30% during losing streaks ≥5
    - Cap max single-symbol exposure at 10% of portfolio
    - Reduce by 50% if strategy win rate <40%
    """
    size = base_size
    adjustments = []
    
    # Check losing streak
    streak_losses = _count_recent_losses(strategy)
    if streak_losses >= CFG92.losing_streak_threshold:
        size *= (1.0 - CFG92.reduce_size_pct_on_streak)
        adjustments.append(f"losing_streak_{streak_losses}_reduce_{CFG92.reduce_size_pct_on_streak*100}pct")
    
    # Check strategy win rate
    win_rate = _calc_strategy_win_rate(strategy)
    if win_rate < CFG92.min_win_rate_pct:
        size *= 0.85  # Reduced penalty (was 0.5 = 50% cut, now 0.85 = 15% cut)
        adjustments.append(f"low_winrate_{win_rate:.1f}_reduce_15pct")
    
    # Cap exposure
    portfolio_val = _portfolio_value()
    max_size = portfolio_val * CFG92.max_symbol_exposure_pct
    if size > max_size:
        size = max_size
        adjustments.append(f"capped_to_{CFG92.max_symbol_exposure_pct*100}pct_portfolio")
    
    if adjustments:
        _emit_event("size_adjusted", {
            "strategy": strategy,
            "symbol": symbol,
            "base_size": base_size,
            "final_size": size,
            "adjustments": adjustments
        })
    
    return size

# ======================================================================================
# Trade frequency control
# ======================================================================================

def phase92_trade_frequency_guard(symbol: str, strategy: str) -> bool:
    """
    Limit max trades per 4h window to 10.
    Throttle Sentiment-Fusion signals to 1 per symbol per hour.
    
    Returns True if trade is allowed
    """
    recent_trades = _get_recent_trades(hours=4)
    
    # Check 4h limit
    if len(recent_trades) >= CFG92.max_trades_per_4h:
        _state["frequency_blocks"] += 1
        _emit_event("frequency_blocked", {
            "reason": "max_trades_4h",
            "count": len(recent_trades),
            "limit": CFG92.max_trades_per_4h
        })
        return False
    
    # Sentiment-Fusion throttle
    if strategy == "Sentiment-Fusion":
        sf_symbol_trades = [t for t in recent_trades 
                           if t.get("strategy") == "Sentiment-Fusion" 
                           and t.get("symbol") == symbol]
        if sf_symbol_trades:
            try:
                last_trade_ts = datetime.fromisoformat(sf_symbol_trades[-1]["timestamp"].replace('Z', '+00:00'))
                minutes_since = (datetime.now() - last_trade_ts.replace(tzinfo=None)).total_seconds() / 60
                if minutes_since < CFG92.sentiment_fusion_throttle_min:
                    _state["frequency_blocks"] += 1
                    _emit_event("frequency_blocked", {
                        "reason": "sentiment_fusion_throttle",
                        "symbol": symbol,
                        "minutes_since_last": minutes_since,
                        "throttle_min": CFG92.sentiment_fusion_throttle_min
                    })
                    return False
            except:
                pass
    
    return True

# ======================================================================================
# Exit optimization (advisory - actual exits handled by main bot)
# ======================================================================================

def phase92_get_exit_recommendations(positions: List[Dict]) -> List[Dict]:
    """
    Return exit recommendations for positions:
    - Tighten ATR trailing stops to 1.5x ATR
    - Time-based exit if stagnant >6h with <0.1% gain
    - Profit lock: flag positions for size reduction when gain ≥0.5%
    - Multi-timeframe timing intelligence exit signals
    """
    recommendations = []
    
    for pos in positions:
        symbol = pos.get("symbol")
        opened_at = pos.get("opened_at")
        direction = pos.get("direction", "LONG")
        
        # Calculate time held
        try:
            if opened_at is None:
                time_held_hours = 0
            else:
                opened_ts = datetime.fromisoformat(opened_at.replace('Z', '+00:00'))
                time_held_hours = (datetime.now() - opened_ts.replace(tzinfo=None)).total_seconds() / 3600
        except:
            time_held_hours = 0
        
        # Calculate unrealized gain - handle None values
        entry = pos.get("entry_price") or 0
        peak = pos.get("peak_price")
        if peak is None:
            peak = entry  # Fallback to entry if peak not set
        unrealized_pct = ((peak - entry) / entry * 100) if entry > 0 else 0
        
        # [TIMING-INTELLIGENCE] Check multi-timeframe exit timing
        timing_id = pos.get("timing_id")
        if timing_id:
            try:
                from src.position_timing_intelligence import check_exit_timing
                timing_check = check_exit_timing(timing_id)
                if timing_check.get("action") in ["EXIT", "FORCE_EXIT"]:
                    recommendations.append({
                        "symbol": symbol,
                        "action": "timing_exit",
                        "reason": f"mtf_timing_{timing_check.get('action')}",
                        "confidence": timing_check.get("confidence", 0.5),
                        "details": timing_check.get("reasons", [])
                    })
            except Exception:
                pass
        
        # OVERNIGHT FIX: Tiered time-based exits to prevent positions stuck overnight
        # Current price for accurate P&L calculation
        current_price = pos.get("current_price") or pos.get("mark_price") or peak
        if direction == "LONG":
            current_pnl_pct = ((current_price - entry) / entry * 100) if entry > 0 else 0
        else:
            current_pnl_pct = ((entry - current_price) / entry * 100) if entry > 0 else 0
        
        exit_triggered = False
        exit_reason = None
        
        # Tier 1: Exit after 2h if losing > 0.5%
        if time_held_hours >= CFG92.tier1_exit_hours and current_pnl_pct < -0.5:
            exit_triggered = True
            exit_reason = f"tier1_loss_{time_held_hours:.1f}h_at_{current_pnl_pct:.2f}pct"
        
        # Tier 2: Exit after 4h if gain < 0.2%
        elif time_held_hours >= CFG92.tier2_exit_hours and current_pnl_pct < 0.2:
            exit_triggered = True
            exit_reason = f"tier2_stagnant_{time_held_hours:.1f}h_at_{current_pnl_pct:.2f}pct"
        
        # Tier 3: Exit after 8h if gain < 0.5%
        elif time_held_hours >= CFG92.tier3_exit_hours and current_pnl_pct < 0.5:
            exit_triggered = True
            exit_reason = f"tier3_weak_{time_held_hours:.1f}h_at_{current_pnl_pct:.2f}pct"
        
        # Max hold time: Force exit after 12h regardless of P&L
        elif time_held_hours >= CFG92.max_hold_hours:
            exit_triggered = True
            exit_reason = f"max_hold_{time_held_hours:.1f}h_force_exit"
        
        # Legacy: Original 6h stagnant exit (kept for backward compatibility)
        elif time_held_hours >= CFG92.time_exit_hours and unrealized_pct < 0.1:
            exit_triggered = True
            exit_reason = f"stagnant_{time_held_hours:.1f}h_with_{unrealized_pct:.2f}pct_gain"
        
        if exit_triggered:
            recommendations.append({
                "symbol": symbol,
                "action": "time_exit",
                "reason": exit_reason
            })
        
        # Profit lock
        if unrealized_pct >= CFG92.profit_lock_trigger_pct:
            recommendations.append({
                "symbol": symbol,
                "action": "profit_lock",
                "reason": f"unrealized_gain_{unrealized_pct:.2f}pct",
                "reduce_pct": CFG92.profit_lock_reduce_pct
            })
        
        # Tighter trailing stops (advisory)
        recommendations.append({
            "symbol": symbol,
            "action": "tighten_stops",
            "recommended_atr_mult": CFG92.tighten_trailing_stop_atr
        })
    
    if recommendations:
        _state["exit_triggers"][int(time.time())] = len(recommendations)
        _emit_event("exit_recommendations", {"count": len(recommendations), "items": recommendations})
    
    return recommendations

# ======================================================================================
# Governance controls
# ======================================================================================

def phase92_governance_guard():
    """
    Freeze capital ramps while win rate <40%.
    Audit all entry signals.
    """
    global_win_rate = _calc_global_win_rate()
    
    # Check if ramps should be frozen
    should_freeze = global_win_rate < CFG92.min_win_rate_pct
    
    if should_freeze and not _state["ramps_frozen"]:
        _state["ramps_frozen"] = True
        _emit_event("ramps_frozen", {"global_win_rate": global_win_rate})
        _emit_dashboard_event("phase92_ramps_frozen", {"global_win_rate": global_win_rate})
        print(f"🚨 PHASE92: Ramps frozen - win rate {global_win_rate:.1f}% below minimum {CFG92.min_win_rate_pct}%")
    elif not should_freeze and _state["ramps_frozen"]:
        _state["ramps_frozen"] = False
        _emit_event("ramps_unfrozen", {"global_win_rate": global_win_rate})
        _emit_dashboard_event("phase92_ramps_unfrozen", {"global_win_rate": global_win_rate})
        print(f"✅ PHASE92: Ramps unfrozen - win rate recovered to {global_win_rate:.1f}%")
    
    _state["last_governance_check_ts"] = int(time.time())
    _save_state()

def are_ramps_frozen() -> bool:
    """Check if Phase 9.2 has frozen capital ramps"""
    return _state.get("ramps_frozen", False)

# ======================================================================================
# Periodic governance loop
# ======================================================================================

def _governance_loop():
    """Run governance checks every 10 minutes"""
    while True:
        try:
            time.sleep(600)  # 10 minutes
            phase92_governance_guard()
        except Exception as e:
            print(f"⚠️ Phase 9.2 governance loop error: {e}")

# ======================================================================================
# Bootstrap
# ======================================================================================

def start_phase92_profit_discipline_pack():
    """Initialize Phase 9.2 Profit Discipline Pack"""
    _load_state()
    _state["started_at"] = datetime.now().isoformat()
    
    # Start governance thread
    gov_thread = threading.Thread(target=_governance_loop, daemon=True, name="Phase92-Governance")
    gov_thread.start()
    
    # Initial governance check
    phase92_governance_guard()
    
    _emit_event("phase92_started", {"config": asdict(CFG92)})
    _emit_dashboard_event("phase92_started", {"config": asdict(CFG92)})
    print("📊 PHASE92 [{}] phase92_started: {}".format(
        datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        {"min_win_rate": CFG92.min_win_rate_pct, "max_trades_4h": CFG92.max_trades_per_4h}
    ))

def get_phase92_status() -> Dict:
    """Get current Phase 9.2 status for dashboard"""
    return {
        "ramps_frozen": _state.get("ramps_frozen", False),
        "global_win_rate": _calc_global_win_rate(),
        "entry_rejections": dict(_state.get("entry_rejections", {})),
        "frequency_blocks": _state.get("frequency_blocks", 0),
        "last_governance_check": _state.get("last_governance_check_ts", 0),
        "config": asdict(CFG92),
        "started_at": _state.get("started_at")
    }
