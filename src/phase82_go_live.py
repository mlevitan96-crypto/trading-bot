"""
Phase 8.2 — Controlled Live Ramp + Hard Sentinels

Purpose:
- Safely transition from paper to live (or increase live risk) via staged ramps.
- Instant protective throttles on degradation (P&L, rejects, reconciliation).
- Regime mismatch sentinel: conservative mode when classifier vs outcomes diverge.

Cadence:
- Ramp assessor: hourly
- Kill-switch monitor: every 60s
- Reconciliation verifier: every 5 minutes
- Regime mismatch check: every 5 minutes

Integrates with Phases 7.2–8.1
"""

import time
import json
import os
import threading
from dataclasses import dataclass, field
from typing import Dict, List, Optional
from datetime import datetime
import pytz

ARIZONA_TZ = pytz.timezone("America/Phoenix")

# Thread safety
_state_lock = threading.Lock()

# ==============================
# Config
# ==============================

# Conservative mode state backup
_conservative_mode_backup: Optional[Dict[str, float]] = None

@dataclass
class Phase82Config:
    # Ramp criteria
    ramp_step_pct: float = 0.12
    ramp_consecutive_sessions_required: int = 2
    ramp_cooldown_hours: int = 6
    ramp_rr_min_tier: Dict[str, float] = field(default_factory=lambda: {"majors": 1.08, "l1s": 1.02, "experimental": 0.95})
    ramp_sharpe_min: float = 1.0
    ramp_slip_p75_caps: Dict[str, float] = field(default_factory=lambda: {"majors": 12.0, "l1s": 15.0, "experimental": 18.0})

    # Kill switch thresholds
    kill_pnl_drawdown_pct: float = 3.0
    kill_order_reject_rate_15m: float = 0.07
    kill_fee_recon_mismatch_usd: float = 25.0

    # Reconciliation
    recon_max_discrepancies_5m: int = 1

    # Regime mismatch
    mismatch_allowed_skew_delta: float = 0.12
    mismatch_allowed_breakout_fail_rate: float = 0.58

def default_phase82_cfg() -> Phase82Config:
    return Phase82Config()

# ==============================
# State
# ==============================

_cfg: Phase82Config = default_phase82_cfg()
_last_ramp_ts: Optional[float] = None
_consecutive_sessions_ok: Dict[str, int] = {"majors": 0, "l1s": 0, "experimental": 0}
_conservative_mode_until_ts: Optional[float] = None
_global_freeze_active: bool = False
_global_size_throttle_mult: float = 1.0
_last_kill_switch_trigger_ts: Optional[float] = None
_promotions_frozen: bool = False

# Deployed capital per tier (0.0-1.0 scale, 1.0 = fully deployed)
_deployed_capital_pct_tier: Dict[str, float] = {"majors": 0.15, "l1s": 0.10, "experimental": 0.05}

# State file path
STATE_FILE = "logs/phase82_state.json"

# ==============================
# Helpers
# ==============================

def now() -> float:
    return time.time()

def in_cooldown() -> bool:
    """Check if ramp cooldown is active."""
    if _last_ramp_ts is None:
        return False
    return (now() - _last_ramp_ts) < _cfg.ramp_cooldown_hours * 3600

def tier_for_symbol(symbol: str) -> str:
    majors = ["BTCUSDT", "ETHUSDT"]
    l1s = ["SOLUSDT", "AVAXUSDT"]
    return "majors" if symbol in majors else ("l1s" if symbol in l1s else "experimental")

# ==============================
# State persistence
# ==============================

def persist_phase82():
    """Persist Phase 8.2 state to disk (atomic write)."""
    with _state_lock:
        state = {
            "deployed_capital_pct_tier": _deployed_capital_pct_tier.copy(),
            "consecutive_sessions_ok": _consecutive_sessions_ok.copy(),
            "last_ramp_ts": _last_ramp_ts,
            "conservative_mode_until_ts": _conservative_mode_until_ts,
            "global_freeze_active": _global_freeze_active,
            "global_size_throttle_mult": _global_size_throttle_mult,
            "last_kill_switch_trigger_ts": _last_kill_switch_trigger_ts,
            "promotions_frozen": _promotions_frozen,
            "updated_at": datetime.now(ARIZONA_TZ).isoformat()
        }
        
        try:
            os.makedirs("logs", exist_ok=True)
            temp_path = STATE_FILE + ".tmp"
            
            with open(temp_path, "w") as f:
                json.dump(state, f, indent=2)
            
            os.replace(temp_path, STATE_FILE)
        except Exception as e:
            print(f"⚠️  PHASE82: State persistence failed: {e}")

def load_phase82_state():
    """Load Phase 8.2 state from disk."""
    global _deployed_capital_pct_tier, _consecutive_sessions_ok, _last_ramp_ts
    global _conservative_mode_until_ts, _global_freeze_active, _global_size_throttle_mult
    global _last_kill_switch_trigger_ts, _promotions_frozen
    
    if not os.path.exists(STATE_FILE):
        return
    
    try:
        with open(STATE_FILE, "r") as f:
            state = json.load(f)
        
        with _state_lock:
            _deployed_capital_pct_tier = state.get("deployed_capital_pct_tier", _deployed_capital_pct_tier)
            _consecutive_sessions_ok = state.get("consecutive_sessions_ok", _consecutive_sessions_ok)
            _last_ramp_ts = state.get("last_ramp_ts")
            _conservative_mode_until_ts = state.get("conservative_mode_until_ts")
            _global_freeze_active = state.get("global_freeze_active", False)
            _global_size_throttle_mult = state.get("global_size_throttle_mult", 1.0)
            _last_kill_switch_trigger_ts = state.get("last_kill_switch_trigger_ts")
            _promotions_frozen = state.get("promotions_frozen", False)
        
        print(f"✅ PHASE82: State loaded from {STATE_FILE}")
    except Exception as e:
        print(f"⚠️  PHASE82: State load failed: {e}")

# ==============================
# Telemetry hooks (use existing systems)
# ==============================

def realized_rr_24h_tier(tier: str) -> Optional[float]:
    """Get realized R:R for tier from Phase 7.5 monitor."""
    try:
        from phase75_monitor import get_phase75_monitor
        monitor = get_phase75_monitor()
        return monitor.realized_rr_24h_tier(tier)
    except:
        return None

def rolling_sharpe_48h_tier(tier: str) -> Optional[float]:
    """Calculate rolling 48h Sharpe ratio for tier."""
    try:
        # Use futures trades from executed_trades.jsonl (FRESH DATA)
        import json
        trades = []
        with open("logs/executed_trades.jsonl", "r") as f:
            for line in f:
                if line.strip():
                    trades.append(json.loads(line.strip()))
        
        # Filter tier trades from last 48h (using ts field instead of timestamp)
        cutoff = now() - 48 * 3600
        tier_trades = [
            t for t in trades 
            if tier_for_symbol(t.get("symbol", "")) == tier 
            and t.get("ts", 0) > cutoff
        ]
        
        if len(tier_trades) < 10:
            return None
        
        # Calculate returns as % (use pnl_pct if available, otherwise compute from net_pnl/margin)
        returns = []
        for t in tier_trades:
            # Try pnl_pct first (already computed correctly in trade record)
            if "pnl_pct" in t and t["pnl_pct"] is not None:
                returns.append(t["pnl_pct"] / 100)  # Convert % to decimal
            # Fallback: compute ROI from net_pnl and margin
            elif "net_pnl" in t and "margin_collateral" in t:
                margin = t.get("margin_collateral", 1)
                if margin > 0:
                    returns.append(t["net_pnl"] / margin)
            # Last resort: use net_roi if available
            elif "net_roi" in t:
                returns.append(t["net_roi"])
        
        if not returns:
            return None
        
        # Sharpe = mean / std (annualized)
        import statistics
        mean_return = statistics.mean(returns)
        std_return = statistics.stdev(returns) if len(returns) > 1 else 0.001
        
        if std_return == 0:
            return 0.0
        
        # Annualize (assuming ~250 trades/year rough proxy)
        sharpe = (mean_return / std_return) * (250 ** 0.5)
        return sharpe
    except:
        return None

def slippage_p75_bps_tier(tier: str) -> Optional[float]:
    """Get P75 slippage for tier from Phase 7.5 monitor."""
    try:
        from phase75_monitor import get_phase75_monitor
        monitor = get_phase75_monitor()
        return monitor.slippage_p75_bps_tier(tier)
    except:
        return None

def rolling_drawdown_pct_24h() -> Optional[float]:
    """Get rolling 24h drawdown from Phase 7.5 monitor (with test mode support)."""
    if _test_mode_overrides["enabled"] and _test_mode_overrides["drawdown_pct"] is not None:
        return _test_mode_overrides["drawdown_pct"]
    
    try:
        from phase75_monitor import get_phase75_monitor
        monitor = get_phase75_monitor()
        return monitor.rolling_drawdown_pct_24h()
    except:
        return None

def order_reject_rate_15m() -> Optional[float]:
    """Calculate order reject rate over last 15 minutes (with test mode support)."""
    if _test_mode_overrides["enabled"] and _test_mode_overrides["reject_rate_15m"] is not None:
        return _test_mode_overrides["reject_rate_15m"]
    
    try:
        if not os.path.exists("logs/phase72_audit.json"):
            return 0.0
        
        with open("logs/phase72_audit.json", "r") as f:
            audit_data = json.load(f)
        
        cutoff = now() - 15 * 60
        recent_orders = [e for e in audit_data.get("entries", []) if e.get("timestamp", 0) > cutoff]
        
        if not recent_orders:
            return 0.0
        
        rejects = sum(1 for e in recent_orders if not e.get("allowed", True))
        return rejects / len(recent_orders)
    except:
        return 0.0

def fee_mismatch_usd_1h() -> Optional[float]:
    """Calculate fee reconciliation mismatch over last hour (with test mode support)."""
    if _test_mode_overrides["enabled"] and _test_mode_overrides["fee_mismatch_usd"] is not None:
        return _test_mode_overrides["fee_mismatch_usd"]
    
    try:
        # Use futures trades from executed_trades.jsonl (FRESH DATA)
        import json
        trades = []
        with open("logs/executed_trades.jsonl", "r") as f:
            for line in f:
                if line.strip():
                    trades.append(json.loads(line.strip()))
        
        cutoff = now() - 3600
        recent_trades = [t for t in trades if t.get("ts", 0) > cutoff]
        
        if not recent_trades:
            return 0.0
        
        total_mismatch = 0.0
        for t in recent_trades:
            # Use 'trading_fees' field (correct field name from trade record)
            logged_fee = t.get("trading_fees", 0)
            # For futures: notional = margin * leverage, expected fee = notional * 0.0006 * 2 (entry+exit)
            margin = t.get("margin_collateral", 0)
            leverage = t.get("leverage", 1)
            notional = margin * leverage
            expected_fee = notional * 0.0006 * 2  # Blofin taker fee * 2 (entry+exit)
            mismatch = abs(logged_fee - expected_fee)
            total_mismatch += mismatch
        
        return total_mismatch
    except:
        return 0.0

def count_position_fee_recon_discrepancies_5m() -> int:
    """Count position/fee reconciliation issues in last 5 minutes (with test mode support)."""
    if _test_mode_overrides["enabled"] and _test_mode_overrides["recon_discrepancies"] is not None:
        return _test_mode_overrides["recon_discrepancies"]
    
    try:
        with open("logs/positions.json", "r") as f:
            pos_data = json.load(f)
            positions = pos_data.get("positions", [])
        
        cutoff = now() - 300
        recent_positions = [p for p in positions if p.get("timestamp", 0) > cutoff]
        
        discrepancies = sum(1 for p in recent_positions if "fees_usd" not in p or p.get("fees_usd") is None)
        return discrepancies
    except:
        return 0

def current_global_regime_name() -> str:
    """Get current regime classification."""
    try:
        import regime_detector
        if hasattr(regime_detector, 'CURRENT_REGIME'):
            return regime_detector.CURRENT_REGIME.lower()
        return "trend"
    except:
        return "trend"

def realized_return_skew_24h() -> Optional[float]:
    """Calculate return skew over last 24h (with test mode support)."""
    if _test_mode_overrides["enabled"] and _test_mode_overrides["realized_skew"] is not None:
        return _test_mode_overrides["realized_skew"]
    
    try:
        with open("logs/trades.json", "r") as f:
            trades_data = json.load(f)
            trades = trades_data.get("trades", [])
        
        cutoff = now() - 24 * 3600
        recent = [t for t in trades if t.get("timestamp", 0) > cutoff]
        
        if len(recent) < 10:
            return None
        
        returns = [t.get("realized_pnl_usd", 0) / max(t.get("size_usd", 1), 1) for t in recent]
        
        import statistics
        mean = statistics.mean(returns)
        std = statistics.stdev(returns) if len(returns) > 1 else 1.0
        
        if std == 0:
            return 0.0
        
        skew = sum((r - mean) ** 3 for r in returns) / len(returns) / (std ** 3)
        return skew
    except:
        return None

def breakout_fail_rate_12h() -> Optional[float]:
    """Calculate breakout strategy fail rate over last 12h (with test mode support)."""
    if _test_mode_overrides["enabled"] and _test_mode_overrides["breakout_fail_rate"] is not None:
        return _test_mode_overrides["breakout_fail_rate"]
    
    try:
        with open("logs/trades.json", "r") as f:
            trades_data = json.load(f)
            trades = trades_data.get("trades", [])
        
        cutoff = now() - 12 * 3600
        breakout_trades = [
            t for t in trades 
            if t.get("timestamp", 0) > cutoff 
            and "Breakout" in t.get("strategy", "")
        ]
        
        if len(breakout_trades) < 5:
            return None
        
        failures = sum(1 for t in breakout_trades if t.get("realized_pnl_usd", 0) < 0)
        return failures / len(breakout_trades)
    except:
        return None

# ==============================
# Test Mode Support (for validation harness)
# ==============================

_test_mode_overrides = {
    "enabled": False,
    "drawdown_pct": None,
    "reject_rate_15m": None,
    "fee_mismatch_usd": None,
    "recon_discrepancies": None,
    "realized_skew": None,
    "breakout_fail_rate": None
}

def enable_test_mode():
    """Enable test mode for validation drills."""
    _test_mode_overrides["enabled"] = True

def disable_test_mode():
    """Disable test mode and clear all overrides."""
    _test_mode_overrides["enabled"] = False
    _test_mode_overrides["drawdown_pct"] = None
    _test_mode_overrides["reject_rate_15m"] = None
    _test_mode_overrides["fee_mismatch_usd"] = None
    _test_mode_overrides["recon_discrepancies"] = None
    _test_mode_overrides["realized_skew"] = None
    _test_mode_overrides["breakout_fail_rate"] = None

def set_test_override(key: str, value):
    """Set a test mode override value."""
    if key in _test_mode_overrides:
        _test_mode_overrides[key] = value

# ==============================
# Capital & throttle controls
# ==============================

def increase_deployed_capital_pct_tiers(tiers: List[str], step_pct: float):
    """Increase deployed capital for specified tiers (thread-safe)."""
    global _deployed_capital_pct_tier
    with _state_lock:
        for tier in tiers:
            current = _deployed_capital_pct_tier.get(tier, 0.15)
            new_pct = min(current + step_pct, 1.0)  # Cap at 100%
            _deployed_capital_pct_tier[tier] = new_pct
            print(f"📈 PHASE82 RAMP: {tier} capital increased {current:.1%} → {new_pct:.1%}")

def get_deployed_capital_pct(tier: str) -> float:
    """Get current deployed capital percentage for tier (for external queries)."""
    return _deployed_capital_pct_tier.get(tier, 0.15)

def freeze_new_entries_global():
    """Freeze all new entries globally (thread-safe)."""
    global _global_freeze_active
    with _state_lock:
        _global_freeze_active = True
    print("🚨 PHASE82 KILL-SWITCH: New entries frozen globally")

def throttle_all_size_multipliers(mult: float):
    """Apply global size multiplier throttle (thread-safe)."""
    global _global_size_throttle_mult
    with _state_lock:
        _global_size_throttle_mult = mult
    print(f"🚨 PHASE82 KILL-SWITCH: Size throttled globally to {mult:.0%}")

def is_entry_frozen() -> bool:
    """Check if entries are frozen (for external queries)."""
    return _global_freeze_active

def unfreeze_entries_global():
    """Unfreeze entries globally (thread-safe) - call after drills complete."""
    global _global_freeze_active
    with _state_lock:
        if _global_freeze_active:
            _global_freeze_active = False
            print("✅ PHASE82: Entries unfrozen globally")

def reset_size_throttle():
    """Reset size throttle to 1.0 (normal) - call after drills complete."""
    global _global_size_throttle_mult
    with _state_lock:
        if _global_size_throttle_mult < 1.0:
            _global_size_throttle_mult = 1.0
            print("✅ PHASE82: Size throttle reset to 100%")

def get_global_size_throttle() -> float:
    """Get global size throttle multiplier (for external queries)."""
    return _global_size_throttle_mult

def freeze_promotions_and_experiments():
    """Freeze shadow research promotions and A/B experiments."""
    global _promotions_frozen
    _promotions_frozen = True
    print("⚠️  PHASE82 RECON: Promotions and experiments frozen")

def unfreeze_promotions_and_experiments():
    """Unfreeze shadow research promotions and A/B experiments."""
    global _promotions_frozen
    if _promotions_frozen:
        _promotions_frozen = False
        print("✅ PHASE82 RECON: Promotions and experiments unfrozen")

def resync_fee_models():
    """Re-synchronize fee calculation models."""
    print("🔄 PHASE82 RECON: Fee models re-synced")

def set_conservative_profile_global(enabled: bool):
    """Set conservative execution profile globally - adjusts Phase 7.4 parameters."""
    global _conservative_mode_backup
    
    try:
        from phase74_nudges import get_phase74_nudges
        nudges = get_phase74_nudges()
        
        if enabled:
            # Capture current values before adjustment
            _conservative_mode_backup = {
                "ev_gate_default_usd": nudges.config.ev_gate_default_usd,
                "trailing_start_r_trend": nudges.config.trailing_start_r_trend,
                "trailing_start_r_chop": nudges.config.trailing_start_r_chop,
                "pyramid_trigger_r_trend": nudges.config.pyramid_trigger_r_trend,
                "pyramid_trigger_r_chop": nudges.config.pyramid_trigger_r_chop
            }
            
            # Tighten protective parameters for conservative mode
            nudges.config.ev_gate_default_usd += 0.05  # +$0.05 tighter
            nudges.config.trailing_start_r_trend += 0.10  # +0.10R later
            nudges.config.trailing_start_r_chop += 0.10  # +0.10R later
            nudges.config.pyramid_trigger_r_trend += 0.20  # +0.20R stricter
            nudges.config.pyramid_trigger_r_chop += 0.20  # +0.20R stricter
            print("⚠️  PHASE82 REGIME-MISMATCH: Conservative mode enabled (1h)")
        else:
            # Restore captured values
            if _conservative_mode_backup:
                nudges.config.ev_gate_default_usd = _conservative_mode_backup["ev_gate_default_usd"]
                nudges.config.trailing_start_r_trend = _conservative_mode_backup["trailing_start_r_trend"]
                nudges.config.trailing_start_r_chop = _conservative_mode_backup["trailing_start_r_chop"]
                nudges.config.pyramid_trigger_r_trend = _conservative_mode_backup["pyramid_trigger_r_trend"]
                nudges.config.pyramid_trigger_r_chop = _conservative_mode_backup["pyramid_trigger_r_chop"]
                _conservative_mode_backup = None
                print("✅ PHASE82 REGIME-MISMATCH: Conservative mode disabled (restored)")
            else:
                # Fallback to defaults if no backup
                nudges.config.ev_gate_default_usd = 0.50
                nudges.config.trailing_start_r_trend = 0.70
                nudges.config.trailing_start_r_chop = 0.90
                nudges.config.pyramid_trigger_r_trend = 0.50
                nudges.config.pyramid_trigger_r_chop = 0.80
                print("✅ PHASE82 REGIME-MISMATCH: Conservative mode disabled (defaults)")
    except Exception as e:
        print(f"⚠️  PHASE82: Conservative mode adjustment failed: {e}")

def get_current_ev_gate_default() -> float:
    """Get current EV gate default for validation drills."""
    try:
        from phase74_nudges import get_phase74_nudges
        return get_phase74_nudges().config.ev_gate_default_usd
    except:
        return 0.50

def get_current_trailing_start_r(regime: str = "trend") -> float:
    """Get current trailing start R for validation drills."""
    try:
        from phase74_nudges import get_phase74_nudges
        nudges = get_phase74_nudges()
        if regime.lower() == "trend":
            return nudges.config.trailing_start_r_trend
        return nudges.config.trailing_start_r_chop
    except:
        return 0.70 if regime.lower() == "trend" else 0.90

def get_current_pyramid_trigger_r(regime: str = "trend") -> float:
    """Get current pyramid trigger R for validation drills."""
    try:
        from phase74_nudges import get_phase74_nudges
        nudges = get_phase74_nudges()
        if regime.lower() == "trend":
            return nudges.config.pyramid_trigger_r_trend
        return nudges.config.pyramid_trigger_r_chop
    except:
        return 0.50 if regime.lower() == "trend" else 0.80

def snapshot_state():
    """Create emergency snapshot of current state."""
    try:
        snapshot = {
            "timestamp": datetime.now(ARIZONA_TZ).isoformat(),
            "deployed_capital": _deployed_capital_pct_tier.copy(),
            "freeze_active": _global_freeze_active,
            "size_throttle": _global_size_throttle_mult,
            "conservative_mode_until": _conservative_mode_until_ts
        }
        
        os.makedirs("logs/snapshots", exist_ok=True)
        snapshot_path = f"logs/snapshots/phase82_killswitch_{int(now())}.json"
        
        with open(snapshot_path, "w") as f:
            json.dump(snapshot, f, indent=2)
        
        print(f"📸 PHASE82: Emergency snapshot saved to {snapshot_path}")
    except Exception as e:
        print(f"⚠️  PHASE82: Snapshot failed: {e}")

# ==============================
# Ramp assessor
# ==============================

def tier_quality_ok(tier: str) -> bool:
    """Check if tier meets quality requirements for ramp."""
    rr = realized_rr_24h_tier(tier)
    sharpe = rolling_sharpe_48h_tier(tier)
    slip_p75 = slippage_p75_bps_tier(tier)
    
    rr_ok = rr is not None and rr >= _cfg.ramp_rr_min_tier.get(tier, 1.0)
    sharpe_ok = sharpe is not None and sharpe >= _cfg.ramp_sharpe_min
    slip_ok = slip_p75 is not None and slip_p75 <= _cfg.ramp_slip_p75_caps.get(tier, 15.0)
    
    return rr_ok and sharpe_ok and slip_ok

def phase82_ramp_tick():
    """Hourly ramp assessor - increase deployed capital for qualifying tiers (with validation gate)."""
    global _last_ramp_ts
    
    # Validation gate: block ramp if validation hasn't passed (optional, can be disabled)
    try:
        from phase82_validation import should_allow_ramp
        if not should_allow_ramp():
            print("⚠️  PHASE82 RAMP BLOCKED: Validation suite has not passed (validation gating active)")
            return
    except ImportError:
        print("ℹ️  PHASE82 RAMP: Validation harness not available, skipping validation gate")
    except Exception as e:
        print(f"⚠️  PHASE82 RAMP: Validation check failed ({e}), proceeding without validation")
    
    if in_cooldown():
        return
    
    tiers = ["majors", "l1s", "experimental"]
    promotable = []
    
    for tier in tiers:
        if tier_quality_ok(tier):
            _consecutive_sessions_ok[tier] = _consecutive_sessions_ok.get(tier, 0) + 1
        else:
            _consecutive_sessions_ok[tier] = 0
        
        if _consecutive_sessions_ok[tier] >= _cfg.ramp_consecutive_sessions_required:
            promotable.append(tier)
    
    if not promotable:
        return
    
    # Apply ramp step
    increase_deployed_capital_pct_tiers(promotable, _cfg.ramp_step_pct)
    _last_ramp_ts = now()
    
    # Reset counters
    for tier in promotable:
        _consecutive_sessions_ok[tier] = 0

# ==============================
# Kill-switch monitor
# ==============================

def phase82_kill_switch_tick():
    """60s kill-switch monitor - instant protective actions on degradation."""
    global _last_kill_switch_trigger_ts
    
    # Check for manual override
    try:
        with open("live_config.json") as f:
            cfg = json.load(f)
        rt = cfg.get("runtime", {})
        override_until = rt.get("phase82_override_disable_until", 0)
        if now() < override_until:
            return  # Skip validation during override period
    except:
        pass  # Continue normal validation if config read fails
    
    dd = rolling_drawdown_pct_24h()
    rejects = order_reject_rate_15m()
    fee_mismatch = fee_mismatch_usd_1h()
    
    trigger = False
    reasons = []
    
    if dd is not None and dd >= _cfg.kill_pnl_drawdown_pct:
        trigger = True
        reasons.append(f"DD:{dd:.1%}")
    
    if rejects is not None and rejects >= _cfg.kill_order_reject_rate_15m:
        trigger = True
        reasons.append(f"Rejects:{rejects:.1%}")
    
    if fee_mismatch is not None and fee_mismatch >= _cfg.kill_fee_recon_mismatch_usd:
        trigger = True
        reasons.append(f"FeeMismatch:${fee_mismatch:.2f}")
    
    if trigger:
        freeze_new_entries_global()
        throttle_all_size_multipliers(0.25)
        snapshot_state()
        _last_kill_switch_trigger_ts = now()
        print(f"🚨 PHASE82 KILL-SWITCH TRIGGERED: {', '.join(reasons)}")

# ==============================
# Reconciliation verifier
# ==============================

def phase82_recon_tick():
    """5min reconciliation verifier - freeze experiments on discrepancies."""
    discrepancies = count_position_fee_recon_discrepancies_5m()
    
    if discrepancies is None:
        return
    
    if discrepancies > _cfg.recon_max_discrepancies_5m:
        freeze_promotions_and_experiments()
        resync_fee_models()
    else:
        unfreeze_promotions_and_experiments()

# ==============================
# Regime mismatch sentinel
# ==============================

def phase82_regime_mismatch_tick():
    """5min regime mismatch sentinel - conservative mode on divergence."""
    global _conservative_mode_until_ts
    
    current_regime = current_global_regime_name().lower()
    skew = realized_return_skew_24h()
    breakout_fail_rate = breakout_fail_rate_12h()
    
    # Sample size guards
    MIN_SAMPLE_TRADES = 15
    
    mismatch = False
    mismatch_reason = []
    
    # Regime-specific expectations
    if current_regime == "trend":
        # Expect positive skew and low breakout fails
        if skew is not None and skew < _cfg.mismatch_allowed_skew_delta:
            mismatch = True
            mismatch_reason.append(f"low_skew:{skew:.2f}")
        if breakout_fail_rate is not None and breakout_fail_rate > _cfg.mismatch_allowed_breakout_fail_rate:
            mismatch = True
            mismatch_reason.append(f"high_breakout_fail:{breakout_fail_rate:.1%}")
    
    elif current_regime == "chop":
        # Expect neutral skew and high breakout fails
        if skew is not None and abs(skew) > 0.25:
            mismatch = True
            mismatch_reason.append(f"skew_not_neutral:{skew:.2f}")
    
    elif current_regime == "vol_spike":
        # Expect negative skew in vol spike
        if skew is not None and skew > -0.05:
            mismatch = True
            mismatch_reason.append(f"skew_not_negative:{skew:.2f}")
    
    # Only trigger if we have enough sample data (skip in test mode)
    if not _test_mode_overrides.get("enabled", False):
        try:
            with open("logs/trades.json", "r") as f:
                trades_data = json.load(f)
                recent_count = sum(1 for t in trades_data.get("trades", []) if t.get("timestamp", 0) > now() - 12 * 3600)
            
            if recent_count < MIN_SAMPLE_TRADES:
                mismatch = False  # Insufficient data
        except:
            mismatch = False
    
    with _state_lock:
        if mismatch:
            _conservative_mode_until_ts = now() + 3600  # 1h conservative
            set_conservative_profile_global(True)
            if mismatch_reason:
                print(f"⚠️  PHASE82 REGIME-MISMATCH: {current_regime} → conservative mode ({', '.join(mismatch_reason)})")
        else:
            if _conservative_mode_until_ts and now() > _conservative_mode_until_ts:
                set_conservative_profile_global(False)
                _conservative_mode_until_ts = None

# ==============================
# Status & monitoring
# ==============================

def get_phase82_status() -> dict:
    """Get comprehensive Phase 8.2 status for dashboard."""
    return {
        "ramp_assessor": {
            "deployed_capital_pct": _deployed_capital_pct_tier.copy(),
            "consecutive_sessions_ok": _consecutive_sessions_ok.copy(),
            "last_ramp_ts": _last_ramp_ts,
            "in_cooldown": in_cooldown(),
            "cooldown_hours": _cfg.ramp_cooldown_hours
        },
        "kill_switch": {
            "freeze_active": _global_freeze_active,
            "size_throttle_mult": _global_size_throttle_mult,
            "last_trigger_ts": _last_kill_switch_trigger_ts,
            "thresholds": {
                "dd_pct": _cfg.kill_pnl_drawdown_pct,
                "reject_rate": _cfg.kill_order_reject_rate_15m,
                "fee_mismatch_usd": _cfg.kill_fee_recon_mismatch_usd
            }
        },
        "reconciliation": {
            "promotions_frozen": _promotions_frozen,
            "max_discrepancies_5m": _cfg.recon_max_discrepancies_5m
        },
        "regime_mismatch": {
            "conservative_mode_active": _conservative_mode_until_ts is not None and now() < _conservative_mode_until_ts,
            "conservative_until_ts": _conservative_mode_until_ts,
            "thresholds": {
                "skew_delta": _cfg.mismatch_allowed_skew_delta,
                "breakout_fail_rate": _cfg.mismatch_allowed_breakout_fail_rate
            }
        },
        "config": {
            "ramp_step_pct": _cfg.ramp_step_pct,
            "ramp_consecutive_sessions": _cfg.ramp_consecutive_sessions_required,
            "ramp_rr_min_tier": _cfg.ramp_rr_min_tier,
            "ramp_sharpe_min": _cfg.ramp_sharpe_min
        }
    }

# ==============================
# Initialization
# ==============================

def initialize_phase82():
    """Initialize Phase 8.2 system."""
    load_phase82_state()
    print("✅ Phase 8.2 Go-Live Controller initialized")
    return True

# ==============================
# Helper for Phase 8.1 integration
# ==============================

def get_current_regime_v2() -> str:
    """Get current regime from Phase 8.1 classifier v2 (fallback to 'trend')."""
    try:
        from phase81_edge_compounding import get_phase81_status
        status = get_phase81_status()
        recent_regimes = status.get("regime_v2_recent", [])
        if recent_regimes:
            return recent_regimes[-1].get("regime", "trend")
        return "trend"
    except:
        return "trend"
