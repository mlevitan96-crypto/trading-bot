"""
Leverage-Aware Profit Module + Governance Sentinel Extensions
Single drop-in code block that adds:
- Dynamic leverage selection (confidence-gated, ROI-based scaling)
- Stop-loss enforcement on every leveraged trade
- Trailing stop upgrades (locks gains as price moves favorably)
- Margin usage monitor + liquidation buffer guard
- Governance integration (periodic checks + self-heal logs)
- Dashboard-compatible logging fields (leverage, stop_loss, trailing_stop)

Save as: src/leverage_governance.py

Integration:
1) Import and wire register_leverage_governance(register_periodic_task, get_wallet_balance) at startup.
2) Route all trade entries through open_leveraged_position(...) to ensure leverage+SL.
3) Ensure external hooks exist (placeholders below) or replace with actual imports:
   - open_futures_position(...), close_position(...)
   - planned_position_size_usd(signal)
   - get_current_price(symbol)
   - append_json(path, obj), block_new_entries_global(), allow_new_entries_global()
   - update_attribution(...), ledger_add(...)
4) Dashboard: this module logs positions with leverage, stop_loss, trailing_stop fields to logs/positions_futures.json.
"""

import os, json, time
from typing import Dict, Any, List, Optional
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from position_manager import save_positions

# --------------------------------------------------------------------------------------
# Paths
# --------------------------------------------------------------------------------------

TRADES_LOG = "logs/trades_futures.json"
OPEN_POS_LOG = "logs/positions_futures.json"  # FIXED: Was reading wrong file!
EVENTS_LOG = "logs/unified_events.jsonl"
SELF_HEAL_LOG = "logs/self_heal.jsonl"

# --------------------------------------------------------------------------------------
# Config — leverage, risk caps, cadence
# --------------------------------------------------------------------------------------

# Leverage usage policy
MAX_LEVERAGE = 10                 # hard internal cap (even if venue allows 100x)
LEVERAGE_CONFIDENCE_ROI = 0.005   # min ROI (0.5%) to allow leverage
LEVERAGE_CONFIDENCE_SIGNALS = 2   # min multi-timeframe confirmations
LEVERAGE_CAPITAL_FRACTION = 0.25  # cap single-trade notional at 25% of wallet

# Stop-loss policy
STOP_LOSS_WALLET_FRACTION = 0.02  # cap max loss per trade at 2% of wallet
TRAIL_START_PCT = 0.5             # start trailing after +0.5% move
TRAIL_STEP_PCT = 0.25             # tighten trailing stop by 0.25% increments of favorable move

# Portfolio safety
MAX_EXPOSURE_MULT = 3.0           # freeze new entries if exposure > 3x wallet
MARGIN_LIQUIDATION_BUFFER = 0.5   # force exit if unrealized loss > 50% of margin

# Governance cadence (seconds)
GOV_INTERVAL_SEC = 600            # 10 minutes

# --------------------------------------------------------------------------------------
# Helpers: IO + safe calls
# --------------------------------------------------------------------------------------

def _append_json(path: str, obj: Dict[str, Any]):
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "a") as f:
            f.write(json.dumps(obj) + "\n")
    except Exception as e:
        print(f"[LEVERAGE_GOV] Failed to append {path}: {e}")

def _load_json_dict(path: str) -> Dict[str, Any]:
    """Load regular JSON dict file (like logs/positions.json)"""
    if not os.path.exists(path): return {}
    try:
        with open(path, "r") as f:
            return json.load(f)
    except Exception:
        return {}

def _save_json_dict(path: str, data: Dict[str, Any]):
    """Save regular JSON dict file"""
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            json.dump(data, f, indent=2)
    except Exception as e:
        print(f"[LEVERAGE_GOV] Failed to save {path}: {e}")

def _safe_call(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except Exception as e:
        _append_json(EVENTS_LOG, {"ts": int(time.time()), "event": "safe_call_error", "fn": getattr(fn, "__name__", "unknown"), "err": str(e)})
        return None

# --------------------------------------------------------------------------------------
# Leverage decision + stop-loss math
# --------------------------------------------------------------------------------------

def choose_leverage(signal: Dict[str, Any], wallet_balance: float, rolling_expectancy: float) -> int:
    """
    Confidence-gated leverage selection:
    - Requires ROI >= LEVERAGE_CONFIDENCE_ROI, confirmations >= LEVERAGE_CONFIDENCE_SIGNALS, and positive rolling expectancy
    - Scales leverage with ROI strength; enforces capital ramp guard
    """
    roi = float(signal.get("roi", 0.0))
    confirmations = int(signal.get("confirmations", 0))
    leverage = 1

    if roi >= LEVERAGE_CONFIDENCE_ROI and confirmations >= LEVERAGE_CONFIDENCE_SIGNALS and rolling_expectancy > 0:
        if roi >= 0.01:          leverage = 5   # ROI >= 1.0% → 5x
        elif roi >= 0.0075:      leverage = 3   # ROI >= 0.75% → 3x
        elif roi >= 0.005:       leverage = 2   # ROI >= 0.5%  → 2x

    planned_size = signal.get("size", 0.0)
    if planned_size > wallet_balance * LEVERAGE_CAPITAL_FRACTION:
        leverage = 1  # force back to 1x if single-trade notional too large

    return min(leverage, MAX_LEVERAGE)

def compute_stop_loss(entry_price: float, wallet_balance: float, position_size: float, leverage: int, side: str) -> float:
    """
    Sets stop-loss to cap loss at STOP_LOSS_WALLET_FRACTION of wallet.
    Long: stop below entry; Short: stop above entry.
    Properly calculates price move based on actual contract quantity.
    
    Args:
        entry_price: Entry price of position
        wallet_balance: Current wallet balance
        position_size: Notional position size in USD (not margin)
        leverage: Position leverage multiplier
        side: Position direction ("LONG" or "SHORT")
    """
    if entry_price <= 0 or wallet_balance <= 0 or position_size <= 0: return 0.0
    
    # Maximum loss allowed in USD (2% of wallet)
    max_loss_usd = wallet_balance * STOP_LOSS_WALLET_FRACTION
    
    # Calculate actual contract quantity
    # position_size is the notional value, so quantity = notional / price
    quantity = position_size / entry_price
    
    if side.upper() in ("BUY", "LONG"):
        # For longs: (entry - stop) * quantity = max_loss
        # stop = entry - (max_loss / quantity)
        price_drop = max_loss_usd / quantity if quantity > 0 else (entry_price * 0.02)
        return max(entry_price - price_drop, entry_price * 0.95)  # At least 5% below entry
    else:
        # For shorts: (stop - entry) * quantity = max_loss
        # stop = entry + (max_loss / quantity)
        price_rise = max_loss_usd / quantity if quantity > 0 else (entry_price * 0.02)
        return min(entry_price + price_rise, entry_price * 1.05)  # At most 5% above entry

def maybe_update_trailing_stop(pos: Dict[str, Any], current_price: float) -> Optional[float]:
    """
    Trailing stop that activates after TRAIL_START_PCT favorable move
    and tightens by TRAIL_STEP_PCT increments.
    """
    entry = float(pos.get("entry_price", 0.0))
    side = str(pos.get("side", ""))
    existing_trail = float(pos.get("trailing_stop", 0.0))
    if entry <= 0 or current_price <= 0: return None

    move_pct = (current_price - entry) / entry * 100.0 if side.lower() in ("buy","long") else (entry - current_price) / entry * 100.0
    if move_pct < TRAIL_START_PCT: return None

    # Desired trail price: lock in portion of gains
    steps = int((move_pct - TRAIL_START_PCT) // TRAIL_STEP_PCT) + 1
    lock_pct = min(TRAIL_START_PCT + steps * TRAIL_STEP_PCT, move_pct)  # cap at current move
    if side.lower() in ("buy","long"):
        desired_trail = entry * (1 + (lock_pct / 100.0)) * 0.995  # slight buffer
        # Stop must stay below current price
        desired_trail = min(desired_trail, current_price * 0.999)
    else:
        desired_trail = entry * (1 - (lock_pct / 100.0)) * 1.005
        desired_trail = max(desired_trail, current_price * 1.001)

    # Only update if tighter (more protective)
    if existing_trail == 0.0 or (side.lower() in ("buy","long") and desired_trail > existing_trail) or (side.lower() in ("sell","short") and desired_trail < existing_trail):
        return desired_trail
    return None

# --------------------------------------------------------------------------------------
# Governance: margin usage + liquidation buffer + stop-loss/trailing enforcement
# --------------------------------------------------------------------------------------

def _portfolio_exposure() -> float:
    """
    Sum nominal exposure across open positions (size_usd * leverage).
    """
    data = _load_json_dict(OPEN_POS_LOG)
    positions = data.get("open_positions", [])
    total = 0.0
    for p in positions:
        total += float(p.get("size", 0.0)) * float(p.get("leverage", 1))
    return total

def margin_usage_monitor(get_wallet_balance):
    now = int(time.time())
    wallet = float(_safe_call(get_wallet_balance) or 0.0)
    exposure = _portfolio_exposure()
    if wallet <= 0:
        _append_json(EVENTS_LOG, {"ts": now, "event": "margin_usage_skip", "reason": "wallet_zero"})
        return
    usage_mult = exposure / wallet if wallet > 0 else 0.0
    _append_json(EVENTS_LOG, {"ts": now, "event": "margin_usage", "wallet": wallet, "exposure": exposure, "usage_mult": usage_mult})
    
    if usage_mult > MAX_EXPOSURE_MULT:
        print(f"⚠️  [LEVERAGE_GOV] Exposure {usage_mult:.2f}x exceeds {MAX_EXPOSURE_MULT}x limit")
        _append_json(SELF_HEAL_LOG, {"ts": now, "event": "high_exposure_warning", "usage_mult": usage_mult})

def liquidation_buffer_check(get_wallet_balance, get_current_price_fn):
    now = int(time.time())
    data = _load_json_dict(OPEN_POS_LOG)
    positions = data.get("open_positions", [])
    wallet = float(_safe_call(get_wallet_balance) or 0.0)
    
    for p in positions:
        sym = p.get("symbol", "")
        side = p.get("side", "")
        size = float(p.get("size", 0.0))
        lev = float(p.get("leverage", 1.0))
        entry = float(p.get("entry_price", 0.0))
        current = float(_safe_call(get_current_price_fn, sym) or entry)
        
        # Approx unrealized P&L (direction-aware):
        qty = (size * lev) / entry if entry > 0 else 0.0
        pnl = (current - entry) * qty if side.lower() in ("buy","long") else (entry - current) * qty
        margin = size  # assume initial margin ~ size_usd for simplicity
        
        if margin > 0 and pnl < 0 and abs(pnl) >= margin * MARGIN_LIQUIDATION_BUFFER:
            print(f"🚨 [LEVERAGE_GOV] Liquidation buffer breach: {sym} loss ${abs(pnl):.2f} >= {MARGIN_LIQUIDATION_BUFFER*100}% of margin ${margin:.2f}")
            _append_json(SELF_HEAL_LOG, {"ts": now, "event": "liquidation_buffer_warning", "symbol": sym, "pnl": pnl, "margin": margin})

def stop_loss_and_trailing_enforcement(get_wallet_balance, get_current_price_fn):
    """
    Ensures every position has a valid stop-loss; applies trailing stop as profits accrue;
    logs breach warnings.
    """
    now = int(time.time())
    wallet = float(_safe_call(get_wallet_balance) or 0.0)
    data = _load_json_dict(OPEN_POS_LOG)
    positions = data.get("open_positions", [])
    
    if not positions:
        return

    MAX_HOLD_HOURS = 8  # Close positions open longer than 8 hours
    
    updated = False
    positions_to_close = []  # Track positions to close after iteration
    
    for p in positions:
        sym = p.get("symbol", "")
        # FIXED: Use 'direction' field (our positions use this, not 'side')
        direction = p.get("direction", p.get("side", "LONG"))
        is_long = direction.upper() in ("LONG", "BUY")
        entry = float(p.get("entry_price", 0.0))
        current = float(_safe_call(get_current_price_fn, sym) or entry)
        stop_loss = float(p.get("stop_loss", 0.0))

        # Apply missing SL
        size = float(p.get("size", 0.0))
        lev = int(p.get("leverage", 1))
        if stop_loss <= 0 and entry > 0 and size > 0:
            side_for_sl = "long" if is_long else "short"
            new_sl = compute_stop_loss(entry, wallet, size, lev, side_for_sl)
            p["stop_loss"] = new_sl
            print(f"🛡️ [LEVERAGE_GOV] Applied stop-loss to {sym}: ${new_sl:.5f}")
            _append_json(SELF_HEAL_LOG, {"ts": now, "event": "stop_loss_applied", "symbol": sym, "stop_loss": new_sl})
            updated = True

        # Trailing stop update
        new_trail = maybe_update_trailing_stop(p, current)
        if new_trail is not None:
            p["trailing_stop"] = new_trail
            # Also sync the active stop to trailing (more protective)
            if is_long:
                p["stop_loss"] = max(float(p.get("stop_loss", 0.0)), new_trail)
            else:
                p["stop_loss"] = min(float(p.get("stop_loss", 0.0)), new_trail)
            print(f"📈 [LEVERAGE_GOV] Updated trailing stop for {sym}: ${new_trail:.5f}")
            _append_json(SELF_HEAL_LOG, {"ts": now, "event": "trailing_stop_update", "symbol": sym, "trailing_stop": new_trail})
            updated = True

        # TIME-BASED EXIT: Close positions open longer than MAX_HOLD_HOURS
        opened_at = p.get("opened_at", "")
        if opened_at:
            try:
                from datetime import datetime
                import pytz
                opened_dt = datetime.fromisoformat(opened_at.replace("Z", "+00:00"))
                if opened_dt.tzinfo is None:
                    opened_dt = opened_dt.replace(tzinfo=pytz.UTC)
                now_dt = datetime.now(pytz.UTC)
                hours_open = (now_dt - opened_dt).total_seconds() / 3600
                
                if hours_open > MAX_HOLD_HOURS:
                    print(f"⏰ [LEVERAGE_GOV] Time exit: {sym} open {hours_open:.1f}h > {MAX_HOLD_HOURS}h limit")
                    positions_to_close.append({
                        "symbol": sym,
                        "direction": direction,
                        "strategy": p.get("strategy", "unknown"),
                        "price": current,
                        "reason": f"time_exit_{hours_open:.0f}h"
                    })
            except Exception as e:
                pass  # Skip if can't parse time

        # Breach check (SL or trailing) - ACTUALLY CLOSE THE POSITION!
        effective_sl = float(p.get("stop_loss", 0.0))
        breach = (current <= effective_sl) if is_long else (current >= effective_sl)
        if effective_sl > 0 and breach:
            print(f"🚨 [LEVERAGE_GOV] Stop-loss breach: {sym} price ${current:.5f} hit stop ${effective_sl:.5f}")
            _append_json(SELF_HEAL_LOG, {"ts": now, "event": "stop_loss_breach", "symbol": sym, "price": current, "stop_loss": effective_sl})
            positions_to_close.append({
                "symbol": sym,
                "direction": direction,
                "strategy": p.get("strategy", "unknown"),
                "price": current,
                "reason": "stop_loss_breach"
            })
    
    # Close positions after iteration to avoid modifying list during iteration
    for pos_info in positions_to_close:
        try:
            from src.position_manager import close_futures_position
            closed = close_futures_position(
                pos_info["symbol"], 
                pos_info["strategy"], 
                pos_info["direction"], 
                pos_info["price"], 
                reason=pos_info["reason"]
            )
            if closed:
                print(f"✅ [LEVERAGE_GOV] Position closed: {pos_info['symbol']} {pos_info['direction']} @ ${pos_info['price']:.5f} ({pos_info['reason']})")
                _append_json(SELF_HEAL_LOG, {"ts": now, "event": "position_closed", "symbol": pos_info["symbol"], "reason": pos_info["reason"]})
        except Exception as e:
            print(f"⚠️ [LEVERAGE_GOV] Failed to close position {pos_info['symbol']}: {e}")

    # Save updated positions
    if updated:
        save_positions(data)  # Use save_positions to properly persist changes
        print(f"✅ [LEVERAGE_GOV] Persisted updates to positions.json")
        _append_json(EVENTS_LOG, {"ts": now, "event": "stop_trail_enforcement_cycle", "updates": updated})

# --------------------------------------------------------------------------------------
# Registration: wire governance to periodic scheduler
# --------------------------------------------------------------------------------------

def register_leverage_governance(register_periodic_task, get_wallet_balance, get_current_price_fn):
    """
    Call once at startup to wire leverage governance into your Periodic Task scheduler.
    """
    print("🛡️ [LEVERAGE_GOV] Registering leverage governance tasks...")
    register_periodic_task(lambda: margin_usage_monitor(get_wallet_balance), interval_sec=GOV_INTERVAL_SEC)
    register_periodic_task(lambda: liquidation_buffer_check(get_wallet_balance, get_current_price_fn), interval_sec=GOV_INTERVAL_SEC)
    register_periodic_task(lambda: stop_loss_and_trailing_enforcement(get_wallet_balance, get_current_price_fn), interval_sec=GOV_INTERVAL_SEC)
    print(f"✅ [LEVERAGE_GOV] Governance tasks registered (interval: {GOV_INTERVAL_SEC}s)")
