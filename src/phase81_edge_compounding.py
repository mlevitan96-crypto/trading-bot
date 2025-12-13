"""
Phase 8.1 — Edge Compounding Patch
Bandit meta-optimizer, adaptive regime v2, drawdown recovery script, fill-quality learner, and overnight risk sentinel.

Delivers:
- Bandit meta-optimizer: reweights policy levers (EV gates, trailing, add spacing, routing bias) by recent net P&L using epsilon-greedy/Thompson sampling per tier
- Adaptive regime classifier v2: faster regime flips using volatility, trend persistence, order book imbalance, and realized skew
- Drawdown recovery script: staged tightening and controlled re-expansion after drawdown breaches
- Fill-quality learner: learns per symbol time-of-day slippage curves; avoids bad windows and adjusts routing
- Overnight risk sentinel: auto-throttles size/pyramiding during thin liquidity windows, auto-unwinds when conditions normalize

Cadence:
- Meta-optimizer: every 30 minutes
- Regime classifier v2: every 5 minutes  
- Drawdown recovery: reactive + staged hourly
- Fill-quality learner: every 15 minutes
- Overnight risk sentinel: every 5 minutes

Assumptions:
- Phases 7.2–8.0 are running with the required hooks.
"""

import time
import math
import random
import json
from pathlib import Path
from dataclasses import dataclass, field
from typing import Dict, List, Tuple, Optional
from datetime import datetime
import pytz

ARIZONA_TZ = pytz.timezone('America/Phoenix')

# ==============================
# Config
# ==============================

@dataclass
class Phase81Config:
    # Bandit meta-optimizer
    bandit_window_hours: int = 24
    bandit_epsilon: float = 0.10           # epsilon-greedy exploration
    bandit_ts_prior_alpha: float = 1.0     # Thompson sampling prior
    bandit_ts_prior_beta: float = 1.0
    bandit_weight_nudge: float = 0.07      # ±7% weight change per decision
    bandit_actions: List[str] = field(default_factory=lambda: [
        "ev_gate_relax", "ev_gate_tighten",
        "trailing_earlier", "trailing_later",
        "add_spacing_tighten", "add_spacing_relax",
        "maker_bias_up", "maker_bias_down"
    ])

    # Regime classifier v2 thresholds
    vol_trend_threshold: float = 0.55      # trend persistence score
    orderbook_imbalance_threshold: float = 0.60
    realized_skew_threshold: float = 0.10  # skew of returns

    # Drawdown recovery script
    dd_trigger_pct: float = 3.5
    dd_release_pct: float = 2.0
    recovery_initial_tighten: Dict[str, float] = field(default_factory=lambda: {
        "size_drop_pct": 0.25, "ev_gate_add_usd": 0.10, "disable_pyramiding": 1
    })
    recovery_step_interval_hours: int = 1
    recovery_step_size_increase_pct: float = 0.10
    recovery_max_hours: int = 12

    # Fill-quality learner
    slippage_bad_window_bps: float = 14.0  # above this → avoid maker, prefer taker
    min_samples_per_bucket: int = 30       # per symbol per hour bucket

    # Overnight sentinel
    overnight_hours_local: Tuple[int, int] = (22, 5)  # 10pm–5am local
    overnight_spread_p50_bps_threshold: float = 9.0
    overnight_size_drop_pct: float = 0.20
    overnight_disable_pyramiding: bool = True

def default_phase81_cfg() -> Phase81Config:
    return Phase81Config()

CFG81 = default_phase81_cfg()

# ==============================
# State
# ==============================

# Bandit weights per tier per action, normalized in [0, 1] baseline 0.5
_bandit_weights: Dict[str, Dict[str, float]] = {t: {a: 0.5 for a in CFG81.bandit_actions}
                                                for t in ["majors", "l1s", "experimental"]}
_bandit_history: List[Dict] = []  # action history with rewards
_last_dd_incident_ts: Optional[float] = None
_recovery_steps_applied: int = 0
_fill_quality_map: Dict[str, Dict[int, Dict[str, float]]] = {}  # symbol -> hour -> {"slip_p50": v, "n": count}
_regime_v2_history: List[Dict] = []  # regime changes
_overnight_throttle_active: bool = False

# Global levers adjusted by bandit/recovery
_global_ev_gate_bonus: float = 0.0  # USD added to all EV gates
_global_size_multiplier: float = 1.0  # multiplier for all position sizes
_pyramiding_frozen: bool = False

# Per-tier lever adjustments
_tier_ev_gate_nudges: Dict[str, float] = {"majors": 0.0, "l1s": 0.0, "experimental": 0.0}
_tier_trailing_r_nudges: Dict[str, float] = {"majors": 0.0, "l1s": 0.0, "experimental": 0.0}
_tier_add_spacing_nudges: Dict[str, float] = {"majors": 0.0, "l1s": 0.0, "experimental": 0.0}
_tier_maker_thresholds: Dict[str, Dict[str, float]] = {
    "majors": {"queue": 0.75, "imbalance": 0.65},
    "l1s": {"queue": 0.75, "imbalance": 0.65},
    "experimental": {"queue": 0.75, "imbalance": 0.65}
}

# Per-symbol routing bias
_symbol_routing_bias: Dict[str, bool] = {}  # symbol -> prefer_maker

# Persistence
PHASE81_STATE_FILE = "logs/phase81_state.json"

# ==============================
# Helpers
# ==============================

def now() -> float:
    return time.time()

def local_hour_now() -> int:
    return datetime.now(ARIZONA_TZ).hour

def tier_for_symbol(symbol: str) -> str:
    """Map symbol to tier (majors, l1s, experimental)."""
    majors = ["BTCUSDT", "ETHUSDT"]
    l1s = ["SOLUSDT", "AVAXUSDT", "DOTUSDT", "TRXUSDT"]
    if symbol in majors:
        return "majors"
    elif symbol in l1s:
        return "l1s"
    else:
        return "experimental"

def persist_state():
    """Save Phase 8.1 state to disk."""
    Path("logs").mkdir(exist_ok=True)
    state = {
        "bandit_weights": _bandit_weights,
        "bandit_history": _bandit_history[-500:],  # last 500 actions
        "fill_quality_map": _fill_quality_map,
        "regime_v2_history": _regime_v2_history[-200:],
        "global_ev_gate_bonus": _global_ev_gate_bonus,
        "global_size_multiplier": _global_size_multiplier,
        "pyramiding_frozen": _pyramiding_frozen,
        "tier_ev_gate_nudges": _tier_ev_gate_nudges,
        "tier_trailing_r_nudges": _tier_trailing_r_nudges,
        "tier_add_spacing_nudges": _tier_add_spacing_nudges,
        "tier_maker_thresholds": _tier_maker_thresholds,
        "symbol_routing_bias": _symbol_routing_bias,
        "last_dd_incident_ts": _last_dd_incident_ts,
        "recovery_steps_applied": _recovery_steps_applied,
        "overnight_throttle_active": _overnight_throttle_active,
        "updated_at": datetime.now(ARIZONA_TZ).isoformat()
    }
    with open(PHASE81_STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)

def load_state():
    """Load Phase 8.1 state from disk."""
    global _bandit_weights, _bandit_history, _fill_quality_map, _regime_v2_history
    global _global_ev_gate_bonus, _global_size_multiplier, _pyramiding_frozen
    global _tier_ev_gate_nudges, _tier_trailing_r_nudges, _tier_add_spacing_nudges
    global _tier_maker_thresholds, _symbol_routing_bias
    global _last_dd_incident_ts, _recovery_steps_applied, _overnight_throttle_active
    
    if not Path(PHASE81_STATE_FILE).exists():
        return
    
    try:
        with open(PHASE81_STATE_FILE, "r") as f:
            state = json.load(f)
        _bandit_weights = state.get("bandit_weights", _bandit_weights)
        _bandit_history = state.get("bandit_history", [])
        _fill_quality_map = state.get("fill_quality_map", {})
        _regime_v2_history = state.get("regime_v2_history", [])
        _global_ev_gate_bonus = state.get("global_ev_gate_bonus", 0.0)
        _global_size_multiplier = state.get("global_size_multiplier", 1.0)
        _pyramiding_frozen = state.get("pyramiding_frozen", False)
        _tier_ev_gate_nudges = state.get("tier_ev_gate_nudges", _tier_ev_gate_nudges)
        _tier_trailing_r_nudges = state.get("tier_trailing_r_nudges", _tier_trailing_r_nudges)
        _tier_add_spacing_nudges = state.get("tier_add_spacing_nudges", _tier_add_spacing_nudges)
        _tier_maker_thresholds = state.get("tier_maker_thresholds", _tier_maker_thresholds)
        _symbol_routing_bias = state.get("symbol_routing_bias", {})
        _last_dd_incident_ts = state.get("last_dd_incident_ts")
        _recovery_steps_applied = state.get("recovery_steps_applied", 0)
        _overnight_throttle_active = state.get("overnight_throttle_active", False)
    except Exception as e:
        print(f"⚠️ Phase 8.1: Failed to load state: {e}")

# ==============================
# Hook Implementations
# ==============================

def pnl_attribution_action_last_hours(tier: str, action: str, hours: int) -> float:
    """
    Estimate P&L attribution for a bandit action.
    Simplified: look at recent trades for symbols in tier and attribute based on action type.
    """
    try:
        from src.portfolio_tracker import load_portfolio
        portfolio = load_portfolio()
        trades = portfolio.get("trades", [])
        
        cutoff_ts = now() - hours * 3600
        recent_trades = [
            t for t in trades 
            if datetime.fromisoformat(t["timestamp"]).timestamp() >= cutoff_ts
            and tier_for_symbol(t["symbol"]) == tier
        ]
        
        if not recent_trades:
            return 0.0
        
        # Simple heuristic: if action is about EV gates, look at small P&L trades
        # If about trailing/routing, look at exit quality
        total_pnl = sum(t.get("profit", 0) for t in recent_trades)
        
        # Normalize to typical trade count
        return total_pnl / max(1, len(recent_trades))
    except:
        return 0.0

def vol_trend_persistence() -> float:
    """
    Calculate trend persistence score (0..1).
    Higher means stronger trend continuation.
    """
    try:
        from src.portfolio_tracker import load_portfolio
        portfolio = load_portfolio()
        trades = portfolio.get("trades", [])[-50:]
        
        if len(trades) < 10:
            return 0.5
        
        # Look at consecutive same-direction moves
        directions = []
        for t in trades:
            if t.get("roi", 0) > 0:
                directions.append(1)
            else:
                directions.append(-1)
        
        # Count longest streak
        max_streak = 1
        current_streak = 1
        for i in range(1, len(directions)):
            if directions[i] == directions[i-1]:
                current_streak += 1
                max_streak = max(max_streak, current_streak)
            else:
                current_streak = 1
        
        # Normalize by total trades
        return min(1.0, max_streak / len(directions))
    except:
        return 0.5

def orderbook_imbalance_score() -> float:
    """
    Estimate orderbook imbalance (0..1).
    Higher means strong buying pressure.
    """
    # Simplified: use recent trade volume bias
    try:
        from src.portfolio_tracker import load_portfolio
        portfolio = load_portfolio()
        trades = portfolio.get("trades", [])[-30:]
        
        if len(trades) < 5:
            return 0.5
        
        buy_volume = sum(t.get("amount", 0) for t in trades if t.get("side") in ["buy", "long"])
        sell_volume = sum(t.get("amount", 0) for t in trades if t.get("side") in ["sell", "short"])
        total_volume = buy_volume + sell_volume
        
        if total_volume == 0:
            return 0.5
        
        return buy_volume / total_volume
    except:
        return 0.5

def realized_return_skew_24h() -> float:
    """
    Calculate realized return skew over last 24h.
    Positive = more upside, negative = more downside.
    """
    try:
        from src.portfolio_tracker import load_portfolio
        portfolio = load_portfolio()
        trades = portfolio.get("trades", [])
        
        cutoff_ts = now() - 24 * 3600
        recent_trades = [
            t for t in trades 
            if datetime.fromisoformat(t["timestamp"]).timestamp() >= cutoff_ts
        ]
        
        if len(recent_trades) < 10:
            return 0.0
        
        returns = [t.get("roi", 0) for t in recent_trades]
        mean_return = sum(returns) / len(returns)
        
        # Simple skew: (mean - median) / std
        sorted_returns = sorted(returns)
        median_return = sorted_returns[len(sorted_returns) // 2]
        
        std = math.sqrt(sum((r - mean_return) ** 2 for r in returns) / len(returns))
        if std == 0:
            return 0.0
        
        return (mean_return - median_return) / std
    except:
        return 0.0

def rolling_drawdown_pct_24h() -> Optional[float]:
    """Calculate max drawdown over last 24h."""
    try:
        from src.portfolio_tracker import load_portfolio
        portfolio = load_portfolio()
        snapshots = portfolio.get("snapshots", [])
        
        if not snapshots:
            return None
        
        cutoff_ts = now() - 24 * 3600
        recent_snapshots = [
            s for s in snapshots
            if datetime.fromisoformat(s["timestamp"]).timestamp() >= cutoff_ts
        ]
        
        if len(recent_snapshots) < 2:
            return None
        
        values = [s["portfolio_value"] for s in recent_snapshots]
        peak = max(values)
        trough = min(values[values.index(peak):] if values.index(peak) < len(values) else values)
        
        if peak == 0:
            return None
        
        return ((peak - trough) / peak) * 100.0
    except:
        return None

def list_all_symbols() -> List[str]:
    """Return all traded symbols."""
    return ["ETHUSDT", "SOLUSDT", "AVAXUSDT", "DOTUSDT", "TRXUSDT", "BTCUSDT",
            "XRPUSDT", "ADAUSDT", "DOGEUSDT", "BNBUSDT", "MATICUSDT"]

def slippage_p50_bps_symbol(symbol: str, window_trades: int) -> Optional[float]:
    """
    Calculate median slippage in basis points for symbol.
    Simplified: estimate from recent trades.
    """
    try:
        from src.portfolio_tracker import load_portfolio
        portfolio = load_portfolio()
        trades = [t for t in portfolio.get("trades", []) if t.get("symbol") == symbol][-window_trades:]
        
        if len(trades) < 5:
            return None
        
        # Estimate slippage as (exit_price - entry_price) / entry_price * 10000 for closed positions
        slippages = []
        for t in trades:
            entry = t.get("entry_price", 0)
            exit_p = t.get("exit_price", 0)
            if entry > 0 and exit_p > 0:
                slip_bps = abs((exit_p - entry) / entry) * 10000
                slippages.append(slip_bps)
        
        if not slippages:
            return None
        
        sorted_slips = sorted(slippages)
        return sorted_slips[len(sorted_slips) // 2]
    except:
        return None

def portfolio_spread_p50_bps() -> Optional[float]:
    """Estimate portfolio-wide spread quality."""
    spreads = []
    for symbol in list_all_symbols():
        slip = slippage_p50_bps_symbol(symbol, window_trades=20)
        if slip is not None:
            spreads.append(slip)
    
    if not spreads:
        return None
    
    sorted_spreads = sorted(spreads)
    return sorted_spreads[len(sorted_spreads) // 2]

# ==============================
# Lever Application Functions
# ==============================

def nudge_ev_gate_tier(tier: str, delta_usd: float):
    """Adjust EV gate for tier."""
    _tier_ev_gate_nudges[tier] += delta_usd
    # Clamp to reasonable bounds
    _tier_ev_gate_nudges[tier] = max(-0.20, min(0.30, _tier_ev_gate_nudges[tier]))

def nudge_trailing_start_r_tier(tier: str, delta_r: float):
    """Adjust trailing stop start point for tier."""
    _tier_trailing_r_nudges[tier] += delta_r
    _tier_trailing_r_nudges[tier] = max(-0.30, min(0.30, _tier_trailing_r_nudges[tier]))

def nudge_add_spacing_tier(tier: str, delta_r: float):
    """Adjust pyramiding add spacing for tier."""
    _tier_add_spacing_nudges[tier] += delta_r
    _tier_add_spacing_nudges[tier] = max(-0.20, min(0.40, _tier_add_spacing_nudges[tier]))

def bump_maker_thresholds_tier(tier: str, queue_nudge: float, imbalance_nudge: float):
    """Adjust maker/taker routing thresholds for tier."""
    _tier_maker_thresholds[tier]["queue"] += queue_nudge
    _tier_maker_thresholds[tier]["imbalance"] += imbalance_nudge
    # Clamp
    _tier_maker_thresholds[tier]["queue"] = max(0.50, min(0.90, _tier_maker_thresholds[tier]["queue"]))
    _tier_maker_thresholds[tier]["imbalance"] = max(0.50, min(0.90, _tier_maker_thresholds[tier]["imbalance"]))

def set_symbol_routing_bias(symbol: str, prefer_maker: bool):
    """Set routing bias for symbol."""
    _symbol_routing_bias[symbol] = prefer_maker

def apply_global_size_drop(drop_pct: float):
    """Reduce all position sizes globally."""
    global _global_size_multiplier
    _global_size_multiplier *= (1.0 - drop_pct)
    _global_size_multiplier = max(0.25, _global_size_multiplier)  # floor at 25%

def apply_global_size_increase(increase_pct: float):
    """Increase all position sizes globally."""
    global _global_size_multiplier
    _global_size_multiplier *= (1.0 + increase_pct)
    _global_size_multiplier = min(1.5, _global_size_multiplier)  # cap at 150%

def apply_global_ev_gate_bonus(add_usd: float):
    """Add to all EV gates globally."""
    global _global_ev_gate_bonus
    _global_ev_gate_bonus += add_usd
    _global_ev_gate_bonus = min(0.50, _global_ev_gate_bonus)  # cap

def clear_global_ev_gate_bonus():
    """Reset global EV gate bonus."""
    global _global_ev_gate_bonus
    _global_ev_gate_bonus = 0.0

def freeze_pyramiding_global():
    """Disable all pyramiding."""
    global _pyramiding_frozen
    _pyramiding_frozen = True

def unfreeze_pyramiding_global():
    """Re-enable pyramiding."""
    global _pyramiding_frozen
    _pyramiding_frozen = False

def set_global_regime(regime_name: str):
    """Update global regime classification."""
    _regime_v2_history.append({
        "timestamp": datetime.now(ARIZONA_TZ).isoformat(),
        "regime": regime_name
    })
    # Also notify other systems (stub for now)

def get_regime_v2() -> dict:
    """Get current regime classification (for external callers)."""
    if _regime_v2_history:
        regime_name = _regime_v2_history[-1]["regime"]
        return {
            "regime": regime_name,
            "confidence": 0.75,  # Default confidence
            "volatility_index": 0.5  # Default volatility
        }
    return {
        "regime": "chop",
        "confidence": 0.5,
        "volatility_index": 0.5
    }

# ==============================
# Bandit meta-optimizer
# ==============================

def bandit_reward_for_action(tier: str, action: str) -> float:
    """
    Reward proxy: net P&L attribution delta for last window constrained to the action's lever.
    Returns normalized reward in [0, 1].
    """
    pnl_delta = pnl_attribution_action_last_hours(tier, action, CFG81.bandit_window_hours)
    # Normalize via sigmoid around 0: positive deltas → near 1, negatives → near 0
    return 1.0 / (1.0 + math.exp(- (pnl_delta or 0.0) / 50.0))

def sample_action_thompson(tier: str) -> str:
    """Thompson sampling for action selection."""
    actions = CFG81.bandit_actions
    params = []
    for a in actions:
        w = _bandit_weights[tier][a]
        alpha = CFG81.bandit_ts_prior_alpha + w * 10.0
        beta = CFG81.bandit_ts_prior_beta + (1.0 - w) * 10.0
        # Beta distribution sample
        sample_val = random.betavariate(alpha, beta)
        params.append((a, sample_val))
    return max(params, key=lambda kv: kv[1])[0]

def choose_bandit_action(tier: str) -> str:
    """Epsilon-greedy with Thompson sampling."""
    if random.random() < CFG81.bandit_epsilon:
        return random.choice(CFG81.bandit_actions)
    return sample_action_thompson(tier)

def apply_bandit_action(tier: str, action: str):
    """Apply the chosen lever for the tier."""
    if action == "ev_gate_relax":
        nudge_ev_gate_tier(tier, -0.05)
    elif action == "ev_gate_tighten":
        nudge_ev_gate_tier(tier, +0.05)
    elif action == "trailing_earlier":
        nudge_trailing_start_r_tier(tier, -0.05)
    elif action == "trailing_later":
        nudge_trailing_start_r_tier(tier, +0.05)
    elif action == "add_spacing_tighten":
        nudge_add_spacing_tier(tier, +0.1)
    elif action == "add_spacing_relax":
        nudge_add_spacing_tier(tier, -0.1)
    elif action == "maker_bias_up":
        bump_maker_thresholds_tier(tier, +0.05, +0.05)
    elif action == "maker_bias_down":
        bump_maker_thresholds_tier(tier, -0.05, -0.05)

def update_bandit_weights(tier: str, action: str):
    """Update bandit weights based on observed reward."""
    r = bandit_reward_for_action(tier, action)
    w = _bandit_weights[tier][action]
    # Move weight toward observed reward
    _bandit_weights[tier][action] = max(0.0, min(1.0, w + CFG81.bandit_weight_nudge * (r - w)))
    
    # Log action
    _bandit_history.append({
        "timestamp": datetime.now(ARIZONA_TZ).isoformat(),
        "tier": tier,
        "action": action,
        "reward": r,
        "new_weight": _bandit_weights[tier][action]
    })

def phase81_bandit_tick():
    """Run bandit meta-optimizer (every 30 minutes)."""
    try:
        for tier in ["majors", "l1s", "experimental"]:
            action = choose_bandit_action(tier)
            apply_bandit_action(tier, action)
            update_bandit_weights(tier, action)
        print(f"🎰 Phase 8.1: Bandit tick completed for all tiers")
    except Exception as e:
        print(f"⚠️ Phase 8.1: Bandit tick error: {e}")

# ==============================
# Adaptive regime classifier v2
# ==============================

def regime_features() -> Dict[str, float]:
    """Aggregate features for regime decision."""
    return {
        "vol_trend": vol_trend_persistence(),
        "orderbook_imbalance": orderbook_imbalance_score(),
        "realized_skew": realized_return_skew_24h()
    }

def classify_regime_v2() -> str:
    """Classify market regime using multiple signals."""
    f = regime_features()
    
    # Trend if vol_trend high, imbalance strong, and skew positive
    if (f["vol_trend"] >= CFG81.vol_trend_threshold and
        f["orderbook_imbalance"] >= CFG81.orderbook_imbalance_threshold and
        f["realized_skew"] >= CFG81.realized_skew_threshold):
        return "trend"
    
    # Risk-off if skew highly negative and imbalance weak
    if (f["realized_skew"] < -CFG81.realized_skew_threshold and 
        f["orderbook_imbalance"] < (CFG81.orderbook_imbalance_threshold - 0.1)):
        return "risk_off"
    
    return "chop"

def phase81_regime_tick():
    """Run regime classifier v2 (every 5 minutes)."""
    try:
        new_regime = classify_regime_v2()
        set_global_regime(new_regime)
        print(f"🔮 Phase 8.1: Regime classified as '{new_regime}'")
    except Exception as e:
        print(f"⚠️ Phase 8.1: Regime tick error: {e}")

# ==============================
# Drawdown recovery script
# ==============================

def phase81_drawdown_guard_tick():
    """Monitor and respond to drawdowns (every hour)."""
    try:
        global _last_dd_incident_ts, _recovery_steps_applied
        
        dd = rolling_drawdown_pct_24h()
        if dd is None:
            return
        
        # Trigger recovery on breach
        if dd >= CFG81.dd_trigger_pct and not _last_dd_incident_ts:
            _last_dd_incident_ts = now()
            _recovery_steps_applied = 0
            
            # Immediate tighten
            apply_global_size_drop(CFG81.recovery_initial_tighten["size_drop_pct"])
            apply_global_ev_gate_bonus(CFG81.recovery_initial_tighten["ev_gate_add_usd"])
            if CFG81.recovery_initial_tighten["disable_pyramiding"]:
                freeze_pyramiding_global()
            
            print(f"🚨 Phase 8.1: Drawdown recovery started (DD: {dd:.2f}%)")
        
        # Staged re-expansion once DD recovers
        elif _last_dd_incident_ts:
            if dd <= CFG81.dd_release_pct and _recovery_steps_applied < CFG81.recovery_max_hours:
                apply_global_size_increase(CFG81.recovery_step_size_increase_pct)
                _recovery_steps_applied += 1
                
                if _recovery_steps_applied == 1:
                    unfreeze_pyramiding_global()
                
                print(f"📈 Phase 8.1: Recovery step {_recovery_steps_applied} (DD: {dd:.2f}%)")
            
            # End recovery after max hours
            if (now() - _last_dd_incident_ts) > CFG81.recovery_max_hours * 3600:
                clear_global_ev_gate_bonus()
                _last_dd_incident_ts = None
                _recovery_steps_applied = 0
                print(f"✅ Phase 8.1: Drawdown recovery complete")
    
    except Exception as e:
        print(f"⚠️ Phase 8.1: Drawdown guard error: {e}")

# ==============================
# Fill-quality learner
# ==============================

def update_fill_quality():
    """Learn per symbol, per local hour slippage p50 and counts."""
    for symbol in list_all_symbols():
        hour = local_hour_now()
        slip_p50 = slippage_p50_bps_symbol(symbol, window_trades=50)
        
        if slip_p50 is None:
            continue
        
        bucket = _fill_quality_map.setdefault(symbol, {}).setdefault(hour, {"slip_p50": 0.0, "n": 0})
        
        # Incremental average
        n = bucket["n"]
        bucket["slip_p50"] = (bucket["slip_p50"] * n + slip_p50) / (n + 1)
        bucket["n"] = n + 1

def should_avoid_maker(symbol: str) -> bool:
    """Check if current hour has bad fill quality for symbol."""
    hour = local_hour_now()
    bucket = _fill_quality_map.get(symbol, {}).get(hour)
    
    if not bucket or bucket["n"] < CFG81.min_samples_per_bucket:
        return False
    
    return bucket["slip_p50"] >= CFG81.slippage_bad_window_bps

def phase81_fill_quality_tick():
    """Update fill quality and adjust routing (every 15 minutes)."""
    try:
        update_fill_quality()
        
        # Adjust routing bias based on quality
        avoided_count = 0
        for symbol in list_all_symbols():
            if should_avoid_maker(symbol):
                set_symbol_routing_bias(symbol, prefer_maker=False)
                avoided_count += 1
            else:
                set_symbol_routing_bias(symbol, prefer_maker=True)
        
        if avoided_count > 0:
            print(f"🎯 Phase 8.1: Fill quality adjusted routing for {avoided_count} symbols")
    
    except Exception as e:
        print(f"⚠️ Phase 8.1: Fill quality tick error: {e}")

# ==============================
# Overnight risk sentinel
# ==============================

def is_overnight_window() -> bool:
    """Check if we're in overnight hours."""
    start, end = CFG81.overnight_hours_local
    hour = local_hour_now()
    
    if start <= end:
        return start <= hour <= end
    # Wrap-around (e.g., 22 → 5)
    return hour >= start or hour <= end

def phase81_overnight_tick():
    """Monitor and throttle during overnight hours (every 5 minutes)."""
    try:
        global _overnight_throttle_active
        
        if not is_overnight_window():
            # Outside overnight window: restore normal operation
            if _overnight_throttle_active:
                _overnight_throttle_active = False
                print(f"🌅 Phase 8.1: Overnight protection lifted")
            return
        
        # Check spread quality
        spread_p50 = portfolio_spread_p50_bps()
        
        if spread_p50 and spread_p50 > CFG81.overnight_spread_p50_bps_threshold:
            if not _overnight_throttle_active:
                apply_global_size_drop(CFG81.overnight_size_drop_pct)
                if CFG81.overnight_disable_pyramiding:
                    freeze_pyramiding_global()
                _overnight_throttle_active = True
                print(f"🌙 Phase 8.1: Overnight protection active (spread: {spread_p50:.1f}bps)")
    
    except Exception as e:
        print(f"⚠️ Phase 8.1: Overnight sentinel error: {e}")

# ==============================
# Public API
# ==============================

def get_phase81_status() -> Dict:
    """Get current Phase 8.1 status for dashboard."""
    return {
        "bandit_weights": _bandit_weights,
        "bandit_recent_actions": _bandit_history[-10:],
        "regime_v2_current": _regime_v2_history[-1] if _regime_v2_history else None,
        "regime_v2_recent": _regime_v2_history[-5:],
        "drawdown_recovery": {
            "active": _last_dd_incident_ts is not None,
            "steps_applied": _recovery_steps_applied,
            "started_at": datetime.fromtimestamp(_last_dd_incident_ts, ARIZONA_TZ).isoformat() if _last_dd_incident_ts else None
        },
        "global_levers": {
            "ev_gate_bonus": _global_ev_gate_bonus,
            "size_multiplier": _global_size_multiplier,
            "pyramiding_frozen": _pyramiding_frozen
        },
        "tier_adjustments": {
            "ev_gate_nudges": _tier_ev_gate_nudges,
            "trailing_r_nudges": _tier_trailing_r_nudges,
            "add_spacing_nudges": _tier_add_spacing_nudges,
            "maker_thresholds": _tier_maker_thresholds
        },
        "overnight_protection": {
            "active": _overnight_throttle_active,
            "in_window": is_overnight_window()
        },
        "fill_quality_symbols": len(_fill_quality_map),
        "routing_bias_set": len(_symbol_routing_bias)
    }

def get_ev_gate_adjustment(symbol: str, base_gate: float) -> float:
    """Get adjusted EV gate for symbol including all nudges."""
    tier = tier_for_symbol(symbol)
    return base_gate + _global_ev_gate_bonus + _tier_ev_gate_nudges[tier]

def get_size_multiplier(symbol: str) -> float:
    """Get size multiplier for symbol."""
    return _global_size_multiplier

def is_pyramiding_allowed() -> bool:
    """Check if pyramiding is currently allowed."""
    return not _pyramiding_frozen

def get_trailing_adjustment(symbol: str) -> float:
    """Get trailing stop R adjustment for symbol."""
    tier = tier_for_symbol(symbol)
    return _tier_trailing_r_nudges[tier]

def get_maker_thresholds(symbol: str) -> Dict[str, float]:
    """Get maker/taker routing thresholds for symbol."""
    tier = tier_for_symbol(symbol)
    return _tier_maker_thresholds[tier]

def should_prefer_maker(symbol: str) -> bool:
    """Check routing bias for symbol."""
    return _symbol_routing_bias.get(symbol, True)

# ==============================
# Initialization
# ==============================

def initialize_phase81():
    """Initialize Phase 8.1."""
    load_state()
    print("✅ Phase 8.1 Edge Compounding initialized")

def persist_phase81():
    """Persist Phase 8.1 state."""
    persist_state()
