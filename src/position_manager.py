"""
Position management for futures trading only.
All spot trading functionality has been removed - futures-only architecture.
"""
import json
from pathlib import Path
from datetime import datetime
import pytz
from src.io_safe import safe_open, AccessBlocked
from src.infrastructure.path_registry import PathRegistry

# Use PathRegistry for unified path resolution (handles slot-based deployments)
POSITIONS_FUTURES_FILE = str(PathRegistry.POS_LOG)
ARIZONA_TZ = pytz.timezone('America/Phoenix')

# --- AUTO-INJECT: enforce minimum hold time before allowing exit ---
MIN_HOLD_SECONDS = 600
import time as __pm_time

def _can_exit(position):
    """Check if position can be exited based on minimum hold time."""
    opened = position.get("opened_at") or position.get("open_ts") or None
    if opened is None:
        return True
    try:
        opened_ts = int(opened)
    except:
        try:
            opened_ts = int(float(opened))
        except:
            opened_ts = None
    if opened_ts is None:
        return True
    if (__pm_time.time() - opened_ts) < MIN_HOLD_SECONDS:
        return False
    return True
# --- END AUTO-INJECT ---

# Elite System integration (lazy import to avoid circular deps)
_elite_attribution = None
_elite_futures_attribution = None
_elite_exec_health = None

def _get_elite_modules():
    """Lazy load elite modules to avoid circular imports."""
    global _elite_attribution, _elite_futures_attribution, _elite_exec_health
    if _elite_attribution is None:
        from src.elite_system import Attribution, FuturesAttribution, ExecutionHealth
        _elite_attribution = Attribution()
        _elite_futures_attribution = FuturesAttribution()
        _elite_exec_health = ExecutionHealth(warn=0.004, crit=0.010)
    return _elite_attribution, _elite_futures_attribution, _elite_exec_health

def get_arizona_time():
    """Get current time in Arizona timezone."""
    return datetime.now(ARIZONA_TZ)

def validate_entry_price(symbol, entry_price, tolerance_pct=0.20):
    """
    Validate entry price against live market price to prevent data corruption.
    
    Args:
        symbol: Trading pair
        entry_price: Proposed entry price
        tolerance_pct: Maximum allowed deviation (default 20%)
    
    Returns:
        Tuple (valid, live_price, deviation_pct)
    """
    try:
        from src.exchange_gateway import ExchangeGateway
        from src.venue_config import get_venue
        
        gateway = ExchangeGateway()
        venue = get_venue(symbol)
        live_price = gateway.get_price(symbol, venue=venue)
        
        if live_price <= 0 or entry_price <= 0:
            return False, live_price, 0.0
        
        deviation_pct = abs(entry_price - live_price) / live_price
        valid = deviation_pct <= tolerance_pct
        
        if not valid:
            print(f"🚨 PRICE VALIDATION FAILED: {symbol}")
            print(f"   Entry Price: ${entry_price:.4f}")
            print(f"   Live {venue} Price: ${live_price:.4f}")
            print(f"   Deviation: {deviation_pct*100:.2f}% (max: {tolerance_pct*100:.0f}%)")
        
        return valid, live_price, deviation_pct
        
    except Exception as e:
        print(f"⚠️ Price validation error for {symbol}: {e}")
        return True, entry_price, 0.0  # Allow on validation failure to prevent false blocks


# ============================================================================
# SPOT TRADING STUB FUNCTIONS
# These return empty data - ALL spot trading has been disabled
# ============================================================================

def get_open_positions():
    """DEPRECATED: Spot trading disabled - returns empty list."""
    return []

def close_position(symbol, strategy, exit_price, reason="manual"):
    """DEPRECATED: Spot trading disabled - no-op."""
    return False

def open_position(symbol, entry_price, size, strategy):
    """DEPRECATED: Spot trading disabled - no-op."""
    return False

def scale_into_position(symbol, current_price, strategy, portfolio_value):
    """DEPRECATED: Spot trading disabled - no-op."""
    return False, 0, 0

def update_peak_price(symbol, strategy, current_price):
    """DEPRECATED: Spot trading disabled - no-op."""
    return False

def load_positions():
    """DEPRECATED: Spot trading disabled - returns empty structure."""
    return {"open_positions": [], "closed_positions": []}

def save_positions(positions):
    """DEPRECATED: Spot trading disabled - no-op."""
    pass


# ============================================================================
# FUTURES-ONLY POSITION MANAGEMENT
# All real trading happens through futures functions below
# ============================================================================

def initialize_futures_positions():
    """Initialize futures positions tracking file. Also repairs empty/malformed files."""
    # Ensure the logs directory exists (using resolved path)
    file_path = Path(POSITIONS_FUTURES_FILE)
    file_path.parent.mkdir(parents=True, exist_ok=True)
    
    # Force flush to ensure logs appear in systemd/journalctl
    import sys
    print(f"🔍 [POSITION-MANAGER] Initializing positions file: {POSITIONS_FUTURES_FILE}", flush=True)
    print(f"🔍 [POSITION-MANAGER] Absolute path: {file_path.resolve()}", flush=True)
    
    # If file doesn't exist, create it
    if not file_path.exists():
        print(f"📝 [POSITION-MANAGER] Creating new positions_futures.json file", flush=True)
        positions = {
            "open_positions": [],
            "closed_positions": [],
            "created_at": get_arizona_time().isoformat()
        }
        with open(POSITIONS_FUTURES_FILE, 'w') as f:
            json.dump(positions, f, indent=2)
        print(f"✅ [POSITION-MANAGER] Created positions_futures.json with proper structure", flush=True)
        return
    
    # If file exists but is empty or malformed, repair it
    try:
        with open(POSITIONS_FUTURES_FILE, 'r') as f:
            content = f.read().strip()
            if not content or content == '{}':
                # File is empty or just empty object - repair it
                print(f"🔧 [POSITION-MANAGER] Repairing empty positions_futures.json file", flush=True)
                positions = {
                    "open_positions": [],
                    "closed_positions": [],
                    "created_at": get_arizona_time().isoformat(),
                    "repaired_at": get_arizona_time().isoformat()
                }
                with open(POSITIONS_FUTURES_FILE, 'w') as f:
                    json.dump(positions, f, indent=2)
                print(f"✅ [POSITION-MANAGER] Repaired empty positions_futures.json file", flush=True)
                return
            
            # Try to parse and validate structure
            data = json.loads(content)
            if not isinstance(data, dict):
                raise ValueError("Not a dict")
            
            # Ensure required keys exist
            if "open_positions" not in data or "closed_positions" not in data:
                print(f"🔧 [POSITION-MANAGER] Repairing malformed positions_futures.json (missing keys)", flush=True)
                positions = {
                    "open_positions": data.get("open_positions", []),
                    "closed_positions": data.get("closed_positions", []),
                    "created_at": data.get("created_at", get_arizona_time().isoformat()),
                    "repaired_at": get_arizona_time().isoformat()
                }
                with open(POSITIONS_FUTURES_FILE, 'w') as f:
                    json.dump(positions, f, indent=2)
                print(f"✅ [POSITION-MANAGER] Repaired malformed positions_futures.json file", flush=True)
            else:
                print(f"✅ [POSITION-MANAGER] positions_futures.json is valid (open: {len(data.get('open_positions', []))}, closed: {len(data.get('closed_positions', []))})", flush=True)
    except (json.JSONDecodeError, ValueError) as e:
        # File is corrupted - repair it
        print(f"🔧 [POSITION-MANAGER] Repairing corrupted positions_futures.json: {e}", flush=True)
        positions = {
            "open_positions": [],
            "closed_positions": [],
            "created_at": get_arizona_time().isoformat(),
            "repaired_at": get_arizona_time().isoformat()
        }
        with open(POSITIONS_FUTURES_FILE, 'w') as f:
            json.dump(positions, f, indent=2)
        print(f"✅ [POSITION-MANAGER] Repaired corrupted positions_futures.json file", flush=True)


def load_futures_positions():
    """Load current futures positions with file locking to prevent corruption."""
    from src.file_locks import locked_json_read
    initialize_futures_positions()
    return locked_json_read(POSITIONS_FUTURES_FILE, default={"open_positions": [], "closed_positions": []})


def save_futures_positions(positions):
    """Save futures positions atomically with file locking to prevent corruption."""
    from src.operator_safety import safe_save_with_retry, alert_operator, ALERT_CRITICAL
    
    # Validate positions before saving
    from src.operator_safety import validate_position_integrity
    validation = validate_position_integrity(positions)
    if not validation["valid"]:
        alert_operator(
            ALERT_HIGH,
            "POSITION_SAVE",
            "Attempting to save invalid position data",
            validation,
            action_required=True
        )
        # Continue anyway - better to save invalid data than lose all data
    
    # Use safe save with retry and alerting
    success = safe_save_with_retry(POSITIONS_FUTURES_FILE, positions, max_retries=3)
    
    if not success:
        # This is critical - positions not saved
        alert_operator(
            ALERT_CRITICAL,
            "POSITION_SAVE",
            "CRITICAL: Failed to save positions after all retries - DATA LOSS RISK",
            {"filepath": POSITIONS_FUTURES_FILE, "open_count": len(positions.get("open_positions", [])), "closed_count": len(positions.get("closed_positions", []))},
            action_required=True
        )
        raise RuntimeError(f"CRITICAL: Failed to save positions to {POSITIONS_FUTURES_FILE} after all retries")


MAX_OPEN_POSITIONS = 10

def open_futures_position(symbol, direction, entry_price, size, leverage, strategy, liquidation_price=None, margin_collateral=None, order_id=None, signal_context=None):
    """
    Open a new futures position with leverage.
    
    Args:
        symbol: Trading pair (e.g., 'BTC-USDT')
        direction: 'LONG' or 'SHORT'
        entry_price: Entry price
        size: Position size in USD (notional value including leverage)
        leverage: Leverage multiplier (e.g., 2, 5, 10)
        strategy: Strategy name
        liquidation_price: Estimated liquidation price (optional)
        margin_collateral: Initial margin posted (optional, calculated if not provided)
        order_id: Order ID from exchange/run_entry_flow (optional, for V6.6/V7.1 grace window tracking)
        signal_context: Dict with signal data for learning (ofi, ensemble, mtf, regime, expected_roi)
    
    Returns:
        Position dict if position opened, False if position already exists or max reached
    """
    positions = load_futures_positions()
    
    open_positions = positions.get("open_positions", [])
    if len(open_positions) >= MAX_OPEN_POSITIONS:
        print(f"⛔ [MAX-POSITIONS] Blocked {symbol} {direction}: Already at {len(open_positions)}/{MAX_OPEN_POSITIONS} positions")
        return False
    
    # Check if position already exists
    for pos in open_positions:
        if pos["symbol"] == symbol and pos["strategy"] == strategy and pos["direction"] == direction:
            return False
    
    # CRITICAL: Reject obviously wrong placeholder prices to prevent P&L corruption
    # $100 is the known placeholder that has caused $50k+ in fake P&L
    if entry_price is None or entry_price <= 0:
        print(f"🚨 [INVALID-PRICE] Blocked {symbol}: entry_price is None or <= 0")
        return False
    if entry_price == 100 or entry_price == 100.0:
        print(f"🚨 [PLACEHOLDER-PRICE] Blocked {symbol}: entry_price=$100 is a placeholder, not real price")
        return False
    # Sanity check: BTC should be >1000, ETH >100, most coins >0.00001
    # We'll reject any major coin with suspiciously low price
    if symbol.startswith("BTC") and entry_price < 1000:
        print(f"🚨 [INVALID-PRICE] Blocked {symbol}: price ${entry_price} is impossibly low for BTC")
        return False
    if symbol.startswith("ETH") and entry_price < 50:
        print(f"🚨 [INVALID-PRICE] Blocked {symbol}: price ${entry_price} is impossibly low for ETH")
        return False
    
    # Calculate margin if not provided
    if margin_collateral is None:
        margin_collateral = size / leverage
    
    # CRITICAL: Reject NaN/infinite sizes that would corrupt position data
    import math
    if not math.isfinite(size) or not math.isfinite(margin_collateral):
        print(f"🚨 [NAN-BLOCKED] {symbol} {direction} size={size} margin={margin_collateral} - INVALID (NaN/Inf)")
        return False
    
    # Prevent ghost positions (size=0 or margin=0)
    if size <= 0.01 or margin_collateral <= 0.01:
        print(f"⚠️ [GHOST-POSITION-BLOCKED] {symbol} {direction} size=${size:.2f} margin=${margin_collateral:.2f} - REJECTED")
        return False
    
    # Capture execution timing for latency calculation
    execution_timestamp = time.time()
    execution_time_iso = get_arizona_time().isoformat()
    
    # Get signal price from signal_context if available (for slippage calculation)
    signal_price = None
    if signal_context:
        signal_price = signal_context.get("signal_price") or signal_context.get("expected_price")
    
    position = {
        "symbol": symbol,
        "direction": direction,
        "strategy": strategy,
        "entry_price": entry_price,
        "size": size,
        "leverage": leverage,
        "margin_collateral": margin_collateral,
        "liquidation_price": liquidation_price,
        "peak_price": entry_price if direction == "LONG" else None,
        "trough_price": entry_price if direction == "SHORT" else None,
        "scaled": 0,
        "opened_at": execution_time_iso,
        "execution_timestamp": execution_timestamp,  # For latency calculation
        "signal_price": signal_price,  # For slippage calculation
        "signal_timestamp": signal_context.get("signal_timestamp") if signal_context else None,  # When signal was generated
        "venue": "futures"
    }
    
    # [V6.6/V7.1] Include order_id if provided (for grace window tracking)
    if order_id:
        position["order_id"] = order_id
    
    # Include signal context for learning if provided
    if signal_context:
        position["ofi_score"] = signal_context.get("ofi", 0.0)
        position["ensemble_score"] = signal_context.get("ensemble", 0.0)
        position["mtf_confidence"] = signal_context.get("mtf", 0.0)
        position["regime"] = signal_context.get("regime", "unknown")
        position["expected_roi"] = signal_context.get("expected_roi", 0.0)
        position["volatility"] = signal_context.get("volatility", 0.0)
        
        # [BIG ALPHA PHASE 2] Store Hurst regime + OI Velocity for TRUE TREND detection
        try:
            # Get Hurst signal from signal_context if available (from predictive_flow_engine)
            signals = signal_context.get("signals", {})
            hurst_signal = signals.get("hurst", {})
            if not hurst_signal:
                # Try to get Hurst signal directly
                from src.hurst_exponent import get_hurst_signal
                clean_symbol = symbol.upper().replace('-', '').replace('USDT', '')
                if not clean_symbol.endswith('USDT'):
                    clean_symbol = f"{clean_symbol}USDT"
                hurst_signal = get_hurst_signal(clean_symbol)
            
            hurst_regime = hurst_signal.get("regime", "unknown")
            hurst_value = hurst_signal.get("hurst_value", 0.5)
            position["hurst_regime_at_entry"] = hurst_regime
            position["hurst_value_at_entry"] = hurst_value
            
            # [BIG ALPHA PHASE 2] TRUE TREND requires: H > 0.55 AND positive 5m OI Delta
            is_hurst_trend = (hurst_regime == "trending" and hurst_value > 0.55)
            oi_positive = False
            oi_delta_5m = 0.0
            
            try:
                from src.macro_institutional_guards import check_oi_velocity_positive
                oi_positive, oi_delta_5m = check_oi_velocity_positive(symbol)
                position["oi_delta_5m_at_entry"] = oi_delta_5m
            except Exception as e:
                print(f"⚠️ [BIG-ALPHA-P2] Failed to check OI velocity for {symbol}: {e}", flush=True)
                # Fail open - if we can't get OI data, still allow TRUE TREND if Hurst is good
                oi_positive = True
                position["oi_delta_5m_at_entry"] = 0.0
            
            # TRUE TREND = Hurst trending (H > 0.55) AND new money entering (positive OI delta)
            position["is_true_trend"] = is_hurst_trend and oi_positive
            
            # [BIG ALPHA PHASE 3] Store Option Max Pain at entry (Magnet Target)
            max_pain_at_entry = 0.0
            try:
                from src.institutional_precision_guards import get_max_pain_price
                max_pain_at_entry = get_max_pain_price(symbol)
                position["max_pain_at_entry"] = max_pain_at_entry
                if max_pain_at_entry > 0:
                    price_gap_pct = abs(entry_price - max_pain_at_entry) / max_pain_at_entry * 100 if max_pain_at_entry > 0 else 0
                    print(f"📌 [BIG-ALPHA-P3] Max Pain Magnet Target for {symbol}: ${max_pain_at_entry:.2f} (gap={price_gap_pct:.2f}%)", flush=True)
            except Exception as e:
                print(f"⚠️ [BIG-ALPHA-P3] Failed to get Max Pain for {symbol}: {e}", flush=True)
                position["max_pain_at_entry"] = 0.0
            
            if position["is_true_trend"]:
                print(f"✅ [BIG-ALPHA-P2] TRUE TREND detected for {symbol} (H={hurst_value:.3f}, OI_Δ={oi_delta_5m:.0f}) - Force-hold enabled (45min min, Tier 4 target)", flush=True)
            elif is_hurst_trend and not oi_positive:
                print(f"⚠️ [BIG-ALPHA-P2] Hurst trending (H={hurst_value:.3f}) but OI delta negative ({oi_delta_5m:.0f}) - NOT TRUE TREND", flush=True)
        except Exception as e:
            # Fail open - don't break position opening
            print(f"⚠️ [BIG-ALPHA] Failed to capture Hurst regime for {symbol}: {e}", flush=True)
            position["hurst_regime_at_entry"] = "unknown"
            position["hurst_value_at_entry"] = 0.5
            position["is_true_trend"] = False
            position["oi_delta_5m_at_entry"] = 0.0
            position["max_pain_at_entry"] = 0.0
        
        # [ENHANCED LOGGING] Capture volatility snapshot at entry
        try:
            from src.enhanced_trade_logging import create_volatility_snapshot
            # Get signals from signal_context if available
            signals = signal_context.get("signals") or signal_context.get("signal_components") or {}
            volatility_snapshot = create_volatility_snapshot(symbol, signals, signal_price=signal_price)
            position["volatility_snapshot"] = volatility_snapshot
            # Log successful capture (only if we got meaningful data)
            if volatility_snapshot.get("atr_14", 0) > 0 or volatility_snapshot.get("regime_at_entry") != "unknown":
                print(f"✅ [ENHANCED-LOGGING] Captured volatility snapshot for {symbol}: ATR={volatility_snapshot.get('atr_14', 0):.2f}, Regime={volatility_snapshot.get('regime_at_entry', 'unknown')}", flush=True)
        except Exception as e:
            # Log the error so we can diagnose issues
            print(f"⚠️  [ENHANCED-LOGGING] Failed to capture volatility snapshot for {symbol}: {e}", flush=True)
            import traceback
            traceback.print_exc()
            position["volatility_snapshot"] = {}
        # [DUAL-BOT] Track which bot opened this position (alpha or beta)
        position["bot_type"] = signal_context.get("bot_type", "alpha")
        # [COUNTER-SIGNAL] Track if this was an inverted signal (at open time)
        position["was_inverted"] = signal_context.get("was_inverted", False)
        # [CONVICTION GATE] Track conviction level and aligned signals for learning
        position["conviction"] = signal_context.get("conviction", "UNKNOWN")
        position["aligned_signals"] = signal_context.get("aligned_signals", 0)
        # [TRADING WINDOW] Track whether trade was during golden hour or 24/7
        position["trading_window"] = signal_context.get("trading_window", "unknown")
        position["signal_components"] = signal_context.get("signal_components", {})
        
        # [SIZING MULTIPLIER LEARNING] Store gate attribution for learning optimal multipliers
        gate_attr = signal_context.get("gate_attribution", {})
        if gate_attr:
            position["gate_attribution"] = {
                "intel_reason": gate_attr.get("intel_reason"),
                "streak_reason": gate_attr.get("streak_reason"),
                "regime_reason": gate_attr.get("regime_reason"),
                "fee_reason": gate_attr.get("fee_reason"),
                "roi_reason": gate_attr.get("roi_reason"),
                "intel_mult": gate_attr.get("intel_mult", 1.0),
                "streak_mult": gate_attr.get("streak_mult", 1.0),
                "regime_mult": gate_attr.get("regime_mult", 1.0),
                "fee_mult": gate_attr.get("fee_mult", 1.0),
                "roi_mult": gate_attr.get("roi_mult", 1.0),
            }
        # Also store directly in position if not in gate_attribution
        position["intel_reason"] = signal_context.get("intel_reason") or gate_attr.get("intel_reason")
        position["streak_reason"] = signal_context.get("streak_reason") or gate_attr.get("streak_reason")
        position["regime_reason"] = signal_context.get("regime_reason") or gate_attr.get("regime_reason")
        position["fee_reason"] = signal_context.get("fee_reason") or gate_attr.get("fee_reason")
        position["roi_reason"] = signal_context.get("roi_reason") or gate_attr.get("roi_reason")
        # [ML-PREDICTOR] Store synchronized market microstructure features at entry time
        # Store the complete ml_features dict for future training
        if signal_context.get("ml_features"):
            ml_feat = signal_context["ml_features"]
            position["ml_features"] = ml_feat
            # Flatten ALL features directly into position for easy dataset building
            position["ml_symbol"] = ml_feat.get("symbol", "")
            position["ml_proposed_direction"] = ml_feat.get("proposed_direction", "")
            position["ml_entry_ts"] = ml_feat.get("timestamp", "")
            position["ml_hour"] = ml_feat.get("hour", 0)
            position["ml_hour_sin"] = ml_feat.get("hour_sin", 0)
            position["ml_hour_cos"] = ml_feat.get("hour_cos", 0)
            position["ml_day_of_week"] = ml_feat.get("day_of_week", 0)
            position["ml_bid_ask_imbalance"] = ml_feat.get("bid_ask_imbalance", 0)
            position["ml_spread_bps"] = ml_feat.get("spread_bps", 0)
            position["ml_bid_depth_usd"] = ml_feat.get("bid_depth_usd", 0)
            position["ml_ask_depth_usd"] = ml_feat.get("ask_depth_usd", 0)
            position["ml_mid_price"] = ml_feat.get("mid_price", 0)
            position["ml_top_bid_size"] = ml_feat.get("top_bid_size", 0)
            position["ml_top_ask_size"] = ml_feat.get("top_ask_size", 0)
            position["ml_depth_ratio"] = ml_feat.get("depth_ratio", 1.0)
            position["ml_return_1m"] = ml_feat.get("return_1m", 0)
            position["ml_return_5m"] = ml_feat.get("return_5m", 0)
            position["ml_return_15m"] = ml_feat.get("return_15m", 0)
            position["ml_volatility_1h"] = ml_feat.get("volatility_1h", 0)
            position["ml_price_trend"] = ml_feat.get("price_trend", 0)
            position["ml_buy_sell_ratio"] = ml_feat.get("buy_sell_ratio", 1.0)
            position["ml_buy_ratio"] = ml_feat.get("buy_ratio", 0.5)
            position["ml_liq_ratio"] = ml_feat.get("liq_ratio", 0.5)
            position["ml_liq_long_1h"] = ml_feat.get("liq_long_1h", 0)
            position["ml_liq_short_1h"] = ml_feat.get("liq_short_1h", 0)
            position["ml_fear_greed"] = ml_feat.get("fear_greed", 0.5)
            position["ml_intel_direction"] = ml_feat.get("intel_direction", 0)
            position["ml_intel_confidence"] = ml_feat.get("intel_confidence", 0)
            position["ml_funding_rate"] = ml_feat.get("funding_rate", 0)
            position["ml_funding_zscore"] = ml_feat.get("funding_zscore", 0)
            position["ml_oi_delta_pct"] = ml_feat.get("oi_delta_pct", 0)
            position["ml_oi_current"] = ml_feat.get("oi_current", 0)
            position["ml_long_short_ratio"] = ml_feat.get("long_short_ratio", 1.0)
            position["ml_long_ratio"] = ml_feat.get("long_ratio", 0.5)
            position["ml_short_ratio"] = ml_feat.get("short_ratio", 0.5)
            position["ml_recent_wins"] = ml_feat.get("recent_wins", 0)
            position["ml_recent_losses"] = ml_feat.get("recent_losses", 0)
            position["ml_streak_direction"] = ml_feat.get("streak_direction", 0)
            position["ml_streak_length"] = ml_feat.get("streak_length", 0)
            position["ml_recent_pnl"] = ml_feat.get("recent_pnl", 0)
            position["ml_btc_return_15m"] = ml_feat.get("btc_return_15m", 0)
            position["ml_btc_trend"] = ml_feat.get("btc_trend", 0)
            position["ml_eth_return_15m"] = ml_feat.get("eth_return_15m", 0)
            position["ml_eth_trend"] = ml_feat.get("eth_trend", 0)
            position["ml_btc_eth_aligned"] = ml_feat.get("btc_eth_aligned", 0)
        else:
            # Fallback to legacy signal_context fields
            position["bid_ask_imbalance"] = signal_context.get("bid_ask_imbalance", 0)
            position["spread_bps"] = signal_context.get("spread_bps", 0)
            position["return_5m"] = signal_context.get("return_5m", 0)
            position["return_15m"] = signal_context.get("return_15m", 0)
            position["fear_greed"] = signal_context.get("fear_greed", 0.5)
            position["intel_direction"] = signal_context.get("intel_direction", 0)
            position["intel_confidence"] = signal_context.get("intel_confidence", 0)
            position["depth_ratio"] = signal_context.get("depth_ratio", 1.0)
    
    if "open_positions" not in positions:
        positions["open_positions"] = []
    positions["open_positions"].append(position)
    save_futures_positions(positions)
    
    # Update portfolio margin accounting
    from src.futures_portfolio_tracker import update_margin_usage
    notional_size = margin_collateral * leverage
    update_margin_usage(margin_change=margin_collateral, notional_change=notional_size)
    
    # [TIMING-INTELLIGENCE] Track position timing and MTF signals
    try:
        from src.position_timing_intelligence import open_position_tracking
        timing_record = open_position_tracking(
            symbol=symbol,
            side=direction,
            entry_price=entry_price,
            signal_ctx=signal_context
        )
        position["timing_id"] = timing_record.get("position_id")
        position["mtf_alignment"] = timing_record.get("mtf_alignment", {}).get("score", 0)
        save_futures_positions(positions)
    except Exception as e:
        print(f"⚠️ [TIMING] Tracking error (non-blocking): {e}")
    
    # [BIG ALPHA] Record entry in hold_time_enforcer with position data for TRUE TREND force-hold
    try:
        from src.hold_time_enforcer import get_hold_time_enforcer
        enforcer = get_hold_time_enforcer()
        # Create position_id from symbol+strategy+direction+timestamp
        position_id = f"{symbol}_{strategy}_{direction}_{int(execution_timestamp)}"
        enforcer.record_entry(position_id, symbol, direction, execution_timestamp, position_data=position)
    except Exception as e:
        print(f"⚠️ [HOLD-TIME] Failed to record entry (non-blocking): {e}", flush=True)
    
    print(f"📊 Opened futures {direction} position: {symbol} @ ${entry_price:.2f} | Size: ${size:.2f} | Leverage: {leverage}x | {strategy}")
    if liquidation_price:
        print(f"   ⚠️  Liquidation price: ${liquidation_price:.2f}")
    
    return position  # Return position dict for post-execution validation


def get_open_futures_positions():
    """
    Get all open futures positions.
    Filters out ghost positions (size=0) and positions marked as closed.
    """
    positions = load_futures_positions()
    open_positions = positions.get("open_positions", [])
    
    # Filter out ghost positions and closed positions
    valid_positions = []
    for pos in open_positions:
        size = float(pos.get("size", 0))
        margin = float(pos.get("margin_collateral", 0))
        status = pos.get("status", "open").lower()
        
        # Skip if size is 0, margin is 0, or marked as closed
        if size <= 0.01 and margin <= 0.01:
            continue
        if status == "closed":
            continue
            
        valid_positions.append(pos)
    
    return valid_positions


def update_futures_peak_trough(symbol, strategy, direction, current_price):
    """
    Update peak (for LONG) or trough (for SHORT) price for trailing stop tracking.
    Only updates if current_price represents a new extreme.
    
    Args:
        symbol: Trading pair
        strategy: Strategy name
        direction: 'LONG' or 'SHORT'
        current_price: Current market price
    
    Returns:
        True if updated, False if no position found or no new extreme
    """
    positions = load_futures_positions()
    updated = False
    
    for pos in positions.get("open_positions", []):
        if pos["symbol"] == symbol and pos["strategy"] == strategy and pos["direction"] == direction:
            if direction == "LONG":
                # Update peak_price if current price is higher
                old_peak = pos.get("peak_price", pos["entry_price"])
                if current_price > old_peak:
                    pos["peak_price"] = current_price
                    updated = True
            elif direction == "SHORT":
                # Update trough_price if current price is lower
                old_trough = pos.get("trough_price", pos["entry_price"])
                if current_price < old_trough:
                    pos["trough_price"] = current_price
                    updated = True
            break
    
    if updated:
        save_futures_positions(positions)
    
    return updated


def close_futures_position(symbol, strategy, direction, exit_price, reason="manual", funding_fees=0.0, partial_qty=None, force_close=False):
    """
    Close a futures position (fully or partially) and record the exit trade for P&L tracking.
    
    Args:
        symbol: Trading pair
        strategy: Strategy name
        direction: 'LONG' or 'SHORT'
        exit_price: Exit price
        reason: Reason for closing (manual, trailing_stop, liquidation, etc.)
        funding_fees: Accumulated funding fees (positive = paid, negative = received)
        partial_qty: If provided, only close this quantity (for ladder exits)
        force_close: If True, bypass hold time enforcement (for emergency reasons)
    
    Returns:
        True if position closed, False if position not found or blocked by hold time
    """
    BYPASS_HOLD_TIME_REASONS = {
        "KILL_SWITCH_EMERGENCY", "kill_switch", "liquidation", "auto_reduce_liquidation_buffer",
        "trailing_stop", "stop_loss", "protective_reduce", "protective_mode_escalate"
    }
    
    should_enforce_hold_time = not force_close and reason not in BYPASS_HOLD_TIME_REASONS
    
    if should_enforce_hold_time:
        try:
            from src.hold_time_enforcer import get_hold_time_enforcer
            enforcer = get_hold_time_enforcer()
            from datetime import datetime
            
            positions_temp = load_futures_positions()
            pos_data = next((p for p in positions_temp.get("open_positions", []) 
                           if p["symbol"] == symbol and p["strategy"] == strategy and p["direction"] == direction), None)
            
            if pos_data:
                entry_time_str = pos_data.get("opened_at", "")
                if entry_time_str:
                    try:
                        entry_time = datetime.fromisoformat(entry_time_str.replace("Z", "+00:00"))
                        current_time = datetime.now(entry_time.tzinfo) if entry_time.tzinfo else datetime.now()
                        hold_seconds = (current_time - entry_time).total_seconds()
                        
                        guard_result = enforcer.check_exit_guard(
                            symbol=symbol, 
                            side=direction, 
                            entry_time=entry_time, 
                            current_pnl=0,
                            reason=reason
                        )
                        
                        if guard_result.get("blocked", False):
                            print(f"   ⏳ [HOLD-TIME] {symbol} {direction}: Exit blocked - {guard_result.get('message', 'Minimum hold time not reached')}")
                            return False
                    except Exception as parse_err:
                        pass
        except Exception as hold_err:
            pass
    
    # Filter out test/validation trades from production portfolio metrics
    # This prevents Phase82 validation tests from contaminating kill-switch drawdown calculations
    is_test_strategy = strategy and ("PHASE82" in strategy.upper() or "TEST" in strategy.upper())
    
    positions = load_futures_positions()
    
    for i, pos in enumerate(positions["open_positions"]):
        if pos["symbol"] == symbol and pos["strategy"] == strategy and pos["direction"] == direction:
            
            # BUG FIX: Check if partial close would leave undersized remnant
            # If so, upgrade to full close to ensure proper accounting
            # ADJUSTED: Lowered from $200 to $20 for paper mode with small positions
            MIN_POSITION_USD = 20
            if partial_qty is not None and partial_qty < pos["size"]:
                exit_pct = partial_qty / pos["size"]
                remaining_margin = pos["margin_collateral"] * (1 - exit_pct)
                
                if remaining_margin < MIN_POSITION_USD:
                    # Upgrade to full close to prevent undersized remnant
                    print(f"🔧 [AUTO-FIX] Remaining margin would be ${remaining_margin:.2f} < ${MIN_POSITION_USD}, upgrading to full close")
                    partial_qty = pos["size"]  # Make it a full close
                    closed_pos = pos
                else:
                    # Normal partial close
                    remaining_qty = pos["size"] - partial_qty
                    closed_pos = pos.copy()
                    closed_pos["size"] = partial_qty
                    closed_pos["margin_collateral"] = pos["margin_collateral"] * exit_pct
            else:
                # Full close
                closed_pos = pos
                partial_qty = pos["size"]
            
            closed_pos["exit_price"] = exit_price
            closed_pos["closed_at"] = get_arizona_time().isoformat()
            closed_pos["close_reason"] = reason
            closed_pos["funding_fees"] = funding_fees * (partial_qty / pos["size"]) if partial_qty else funding_fees
            
            # [FORENSIC EXECUTION DATA] Calculate slippage and execution latency
            try:
                signal_price = closed_pos.get("signal_price")
                fill_price = closed_pos.get("entry_price")  # Actual fill price
                
                if signal_price and fill_price and signal_price > 0:
                    # Calculate slippage in BPS (basis points)
                    slippage_bps = abs((fill_price - signal_price) / signal_price) * 10000
                    closed_pos["slippage_bps"] = slippage_bps
                    closed_pos["signal_price"] = signal_price
                else:
                    closed_pos["slippage_bps"] = None
                
                # Calculate execution latency (signal generation to order fill)
                signal_ts = closed_pos.get("signal_timestamp")
                execution_ts = closed_pos.get("execution_timestamp")
                
                if signal_ts and execution_ts:
                    latency_ms = (execution_ts - signal_ts) * 1000  # Convert to milliseconds
                    closed_pos["execution_latency_ms"] = latency_ms
                else:
                    closed_pos["execution_latency_ms"] = None
            except Exception as e:
                closed_pos["slippage_bps"] = None
                closed_pos["execution_latency_ms"] = None
            
            # [MFE/MAE] Calculate Max Favorable and Adverse Excursion from peak/trough
            try:
                entry_price_pos = closed_pos.get("entry_price", 0)
                peak_price = closed_pos.get("peak_price")
                trough_price = closed_pos.get("trough_price")
                direction = closed_pos.get("direction", "LONG")
                
                if entry_price_pos > 0:
                    if direction == "LONG":
                        # For LONG: MFE is peak above entry, MAE is trough below entry
                        if peak_price and peak_price > entry_price_pos:
                            mfe_pct = ((peak_price - entry_price_pos) / entry_price_pos) * 100
                            closed_pos.setdefault("volatility_snapshot", {})["mfe_pct"] = mfe_pct
                            closed_pos.setdefault("volatility_snapshot", {})["mfe_price"] = peak_price
                        if trough_price and trough_price < entry_price_pos:
                            mae_pct = ((entry_price_pos - trough_price) / entry_price_pos) * 100
                            closed_pos.setdefault("volatility_snapshot", {})["mae_pct"] = mae_pct
                            closed_pos.setdefault("volatility_snapshot", {})["mae_price"] = trough_price
                    else:  # SHORT
                        # For SHORT: MFE is trough below entry, MAE is peak above entry
                        if trough_price and trough_price < entry_price_pos:
                            mfe_pct = ((entry_price_pos - trough_price) / entry_price_pos) * 100
                            closed_pos.setdefault("volatility_snapshot", {})["mfe_pct"] = mfe_pct
                            closed_pos.setdefault("volatility_snapshot", {})["mfe_price"] = trough_price
                        if peak_price and peak_price > entry_price_pos:
                            mae_pct = ((peak_price - entry_price_pos) / entry_price_pos) * 100
                            closed_pos.setdefault("volatility_snapshot", {})["mae_pct"] = mae_pct
                            closed_pos.setdefault("volatility_snapshot", {})["mae_price"] = peak_price
            except Exception as e:
                pass  # Non-critical, continue
            
            if direction == "LONG":
                price_roi = (exit_price - closed_pos["entry_price"]) / closed_pos["entry_price"]
            else:
                price_roi = (closed_pos["entry_price"] - exit_price) / closed_pos["entry_price"]
            
            leveraged_roi = price_roi * closed_pos["leverage"]
            
            # Calculate fees using exchange-aware fee calculator (market orders = taker fees)
            from src.fee_calculator import calculate_trading_fee
            import os
            # Get current exchange for correct fee rates
            exchange = os.getenv("EXCHANGE", "blofin").lower()
            notional_size = closed_pos["margin_collateral"] * closed_pos["leverage"]
            trading_fees_usd = calculate_trading_fee(notional_size, "taker", exchange=exchange) * 2  # entry + exit
            trading_fees_roi = trading_fees_usd / closed_pos["margin_collateral"] if closed_pos["margin_collateral"] > 0 else 0
            funding_fees_roi = closed_pos["funding_fees"] / closed_pos["margin_collateral"] if closed_pos["margin_collateral"] > 0 else 0
            net_roi = leveraged_roi - trading_fees_roi - funding_fees_roi
            
            closed_pos["price_roi"] = price_roi
            closed_pos["leveraged_roi"] = leveraged_roi
            closed_pos["final_roi"] = net_roi
            
            # Calculate USD P&L values for dashboard display
            net_pnl_usd = closed_pos["margin_collateral"] * net_roi
            gross_pnl_usd = closed_pos["margin_collateral"] * leveraged_roi
            
            closed_pos["pnl"] = net_pnl_usd  # USD P&L (legacy field)
            closed_pos["pnl_pct"] = net_roi * 100  # Percentage P&L (legacy field)
            
            # Dashboard-compatible fields
            closed_pos["net_pnl"] = net_pnl_usd
            closed_pos["gross_pnl"] = gross_pnl_usd
            closed_pos["net_roi"] = net_roi
            closed_pos["trading_fees"] = trading_fees_usd
            
            # Calculate trade duration and net P&L for velocity tracking
            from datetime import datetime
            try:
                entry_time = datetime.fromisoformat(closed_pos.get("opened_at", ""))
                exit_time = datetime.fromisoformat(closed_pos.get("closed_at", ""))
                trade_duration_seconds = (exit_time - entry_time).total_seconds()
            except:
                trade_duration_seconds = 3600  # Default 1 hour if parse fails
            
            # Emit USD P&L velocity event for autonomous tracking
            from src.policy_cap_events import emit_profit_per_trade_metric
            emit_profit_per_trade_metric(
                symbol=symbol,
                strategy=strategy,
                venue="futures",
                position_size_usd=closed_pos["margin_collateral"],
                profit_usd=net_pnl_usd,
                roi_pct=net_roi * 100,
                trade_duration_seconds=trade_duration_seconds
            )
            
            if "closed_positions" not in positions:
                positions["closed_positions"] = []
            positions["closed_positions"].append(closed_pos)
            
            try:
                from src.infrastructure.migrate_jsonl import get_dual_writer, parse_timestamp
                dual_writer = get_dual_writer()
                
                # Parse entry timestamp from position's opened_at field
                # Try multiple formats: ISO string, numeric timestamp
                opened_at = closed_pos.get('opened_at')
                entry_ts = parse_timestamp(opened_at)
                if entry_ts is None and opened_at:
                    # Fallback: try parsing ISO without timezone
                    try:
                        from datetime import datetime
                        dt = datetime.fromisoformat(str(opened_at).replace('Z', ''))
                        entry_ts = int(dt.timestamp())
                    except:
                        entry_ts = None
                
                # Exit timestamp is NOW since the trade is closing
                exit_ts = int(__pm_time.time())
                
                trade_record = {
                    'trade_id': closed_pos.get('order_id') or f"trade_{exit_ts}_{symbol}",
                    'symbol': symbol,
                    'side': direction.lower(),
                    'direction': direction,
                    'entry_price': closed_pos.get('entry_price'),
                    'exit_price': exit_price,
                    'quantity': closed_pos.get('size'),
                    'margin_usd': closed_pos.get('margin_collateral'),
                    'leverage': closed_pos.get('leverage', 1),
                    'profit_usd': closed_pos.get('net_pnl', net_pnl_usd),
                    'fees_usd': trading_fees_usd + closed_pos.get('funding_fees', 0),
                    'strategy': strategy,
                    'regime': closed_pos.get('regime'),
                    'entry_ts': entry_ts,
                    'exit_ts': exit_ts,
                    'closed': True,
                    'paper_trade': True
                }
                dual_writer.write_trade_sync(trade_record)
            except Exception as sqlite_err:
                print(f"⚠️ [DUAL-WRITE] SQLite trade write failed (non-blocking): {sqlite_err}")
            
            # Update or remove the open position
            if partial_qty < pos["size"]:
                # Partial close - update remaining position
                exit_pct = partial_qty / pos["size"]
                remaining_qty = pos["size"] - partial_qty
                remaining_margin = pos["margin_collateral"] * (1 - exit_pct)
                positions["open_positions"][i]["size"] = remaining_qty
                positions["open_positions"][i]["margin_collateral"] = remaining_margin
                print(f"📉 Partial close futures {direction}: {symbol} | Closed: {partial_qty:.6f} | Remaining: {remaining_qty:.6f} | Remaining margin: ${remaining_margin:.2f}")
            else:
                # Full close - remove position entirely
                del positions["open_positions"][i]
                print(f"📉 Closed futures {direction} position: {symbol} @ ${exit_price:.2f} | Leverage: {closed_pos['leverage']}x")
            
            save_futures_positions(positions)
            
            # [TIMING-INTELLIGENCE] Record position timing outcome for learning
            try:
                timing_id = pos.get("timing_id")
                if timing_id:
                    from src.position_timing_intelligence import close_position_tracking
                    close_position_tracking(
                        position_id=timing_id,
                        exit_price=exit_price,
                        pnl_usd=net_pnl_usd,
                        pnl_pct=net_roi * 100
                    )
            except Exception as e:
                pass  # Non-blocking
            
            # Record the futures trade for P&L tracking and dashboard display
            # Skip recording for test strategies to prevent contaminating production metrics
            if not is_test_strategy:
                from src.futures_portfolio_tracker import record_futures_trade
                # [ENHANCED LOGGING] Extract volatility snapshot from position
                volatility_snapshot = closed_pos.get("volatility_snapshot", {})
                trade_record = record_futures_trade(
                    symbol=symbol,
                    direction=direction,
                    entry_price=closed_pos["entry_price"],
                    exit_price=exit_price,
                    margin_collateral=closed_pos["margin_collateral"],
                    leverage=closed_pos["leverage"],
                    strategy_name=strategy,
                    funding_fees=closed_pos["funding_fees"],
                    trading_fees_usd=trading_fees_usd,
                    order_type="taker",  # Market orders = taker fees
                    duration_seconds=trade_duration_seconds,  # V6.6/V7.1 FIX: Grace window validation
                    was_inverted=closed_pos.get("was_inverted", False),  # Counter-signal flag from open time
                    volatility_snapshot=volatility_snapshot
                )
            else:
                print(f"   🧪 [TEST-TRADE-EXCLUDED] Skipping futures portfolio update for test strategy: {strategy}")
            
            from src.portfolio_tracker import load_portfolio
            from src.regime_detector import predict_regime
            
            portfolio = load_portfolio()
            position_pct = closed_pos["margin_collateral"] / portfolio["current_value"] if portfolio["current_value"] > 0 else 0.15
            
            try:
                _, futures_attribution, _ = _get_elite_modules()
                regime = predict_regime()
                if futures_attribution:
                    futures_attribution.log(
                        symbol=symbol,
                        strategy=strategy,
                        regime=regime,
                        roi=net_roi,
                        leverage=closed_pos['leverage'],
                        trading_fees=trading_fees_roi,
                        funding_fees=funding_fees_roi,
                        margin=closed_pos['margin_collateral']
                    )
            except Exception as e:
                pass
            
            print(f"   ROI: {price_roi*100:.2f}% → Leveraged: {leveraged_roi*100:.2f}% → Net: {net_roi*100:.2f}% | Reason: {reason}")
            if closed_pos["funding_fees"] != 0:
                print(f"   Funding fees: ${closed_pos['funding_fees']:.2f}")
            
            # [STREAK FILTER] Update streak state for momentum-based trade gating
            try:
                from src.streak_filter import update_streak
                bot_type = closed_pos.get("bot_type", "alpha")
                won = net_pnl_usd > 0
                update_streak(won=won, pnl=net_pnl_usd, symbol=symbol, bot_type=bot_type)
            except Exception as e:
                pass  # Non-blocking
            
            # [CONTINUOUS LEARNING] Log outcome for the learning feedback loop
            try:
                from src.continuous_learning_controller import log_conviction_outcome
                conviction = closed_pos.get("conviction", "UNKNOWN")
                aligned_signals = closed_pos.get("aligned_signals", 0)
                signal_components = closed_pos.get("signal_components", {})
                
                log_conviction_outcome(
                    symbol=symbol,
                    direction=direction,
                    conviction=conviction,
                    aligned_signals=aligned_signals,
                    executed=True,
                    outcome_pnl=net_pnl_usd,
                    signal_components=signal_components
                )
            except Exception as e:
                pass  # Non-blocking
            
            # [EXIT GATE LOGGING] Log to exit_runtime_events.jsonl for dashboard monitoring
            try:
                from src.exit_learning_and_enforcement import EXIT_RUNTIME_LOG, _append_jsonl
                
                # Determine exit type based on reason and profitability
                exit_type = "closed"
                if "tp1" in reason.lower() or "profit_target" in reason.lower():
                    exit_type = "tp1"
                elif "tp2" in reason.lower():
                    exit_type = "tp2"
                elif "trailing" in reason.lower() or "trail" in reason.lower():
                    exit_type = "trailing"
                elif "stop" in reason.lower() or "loss" in reason.lower():
                    exit_type = "stop"
                elif "time" in reason.lower():
                    exit_type = "time_stop"
                
                # Calculate minutes open
                minutes_open = trade_duration_seconds / 60 if trade_duration_seconds else 0
                
                # Calculate MFE (Max Favorable Excursion) from peak_price
                entry_price_pos = closed_pos.get("entry_price", 0) or entry_price
                peak_price = closed_pos.get("peak_price", exit_price)
                trough_price = closed_pos.get("trough_price", exit_price)
                
                # Calculate peak ROI (MFE)
                if direction == "LONG":
                    peak_roi = ((peak_price - entry_price_pos) / entry_price_pos) if entry_price_pos > 0 else 0.0
                    mfe_roi = peak_roi  # For LONG, peak is MFE
                else:  # SHORT
                    trough_roi = ((entry_price_pos - trough_price) / entry_price_pos) if entry_price_pos > 0 else 0.0
                    mfe_roi = trough_roi  # For SHORT, trough is MFE
                
                # Calculate capture rate (% of MFE we captured)
                exit_roi_raw = net_roi / 100.0  # Convert percentage to decimal
                capture_rate = (exit_roi_raw / mfe_roi * 100.0) if mfe_roi > 0 else 0.0
                
                exit_event = {
                    "symbol": symbol,
                    "exit_type": exit_type,
                    "roi": net_roi,  # Net ROI after fees (percentage)
                    "realized_roi": net_roi,  # For compatibility
                    "pnl_usd": net_pnl_usd,
                    "minutes_open": round(minutes_open, 1),
                    "reason": reason,
                    "was_profitable": net_roi > 0,
                    "strategy": strategy,
                    "direction": direction,
                    "entry_price": entry_price_pos,
                    "exit_price": exit_price,
                    "peak_price": peak_price if direction == "LONG" else None,
                    "trough_price": trough_price if direction == "SHORT" else None,
                    "mfe_roi": mfe_roi * 100.0,  # MFE as percentage (for learning analysis)
                    "capture_rate_pct": capture_rate,  # % of MFE captured (100% = perfect, <70% = early exit)
                    "leverage": closed_pos.get("leverage", 1),
                    "ts": int(__pm_time.time())  # Use existing time import
                }
                
                _append_jsonl(EXIT_RUNTIME_LOG, exit_event)
            except Exception as e:
                print(f"⚠️ [EXIT-LOG] Failed to log exit event: {e}")
                pass  # Non-blocking
            
            return True
    
    return False


def update_futures_margin_safety(symbol, strategy, direction, mark_price, liquidation_price):
    """
    Update margin safety metrics for a futures position.
    
    Args:
        symbol: Trading pair
        strategy: Strategy name
        direction: 'LONG' or 'SHORT'
        mark_price: Current mark price
        liquidation_price: Updated liquidation price
    
    Returns:
        dict with buffer_pct and status, or None if position not found
    """
    positions = load_futures_positions()
    
    for pos in positions.get("open_positions", []):
        if pos["symbol"] == symbol and pos["strategy"] == strategy and pos["direction"] == direction:
            pos["liquidation_price"] = liquidation_price
            
            # Calculate buffer percentage
            if direction == "LONG":
                buffer_pct = ((mark_price - liquidation_price) / mark_price) * 100
            else:  # SHORT
                buffer_pct = ((liquidation_price - mark_price) / mark_price) * 100
            
            # Update peak/trough for trailing stops
            if direction == "LONG" and mark_price > pos.get("peak_price", pos["entry_price"]):
                pos["peak_price"] = mark_price
            elif direction == "SHORT" and mark_price < pos.get("trough_price", pos["entry_price"]):
                pos["trough_price"] = mark_price
            
            save_futures_positions(positions)
            
            # Determine status (clamp negative buffers to 0 for clarity)
            buffer_pct = max(0.0, buffer_pct)
            
            if buffer_pct < 8.0:
                status = "REDUCE_EXPOSURE"
            elif buffer_pct < 12.0:
                status = "ALERT"
            else:
                status = "OK"
            
            return {
                "buffer_pct": buffer_pct,
                "status": status,
                "liquidation_price": liquidation_price,
                "mark_price": mark_price
            }
    
    return None