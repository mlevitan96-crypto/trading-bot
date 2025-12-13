from src.blofin_client import BlofinClient
from src.protective_mode_controller import log_protective_event
from src.stablecoin_rotation import rotate_to_stablecoin
from src.rotation_tracker import log_rotation_event
from src.reentry_module import reenter_market
from src.reentry_logger import log_reentry_event
from src.strategy_runner import run_trend_conservative, run_breakout_aggressive, run_sentiment_fusion, ensemble_confidence_score
from src.strategy_attribution import log_strategy_performance
from src.broker import place_order
from src.portfolio_tracker import record_trade, record_hourly_pnl, initialize_portfolio, load_portfolio
from src.portfolio_bridge import get_active_portfolio, get_portfolio_value
from src.heartbeat_tracker import write_heartbeat
from src.regime_detector import predict_regime, get_active_strategies_for_regime, ASSETS
from src.trade_cooldown import should_execute_trade, record_trade_time
from src.position_manager import get_open_futures_positions, close_futures_position, update_futures_peak_trough
from src.trailing_stop import apply_futures_trailing_stops
from src.signal_quality_tracker import log_signal_quality
from src.missed_opportunity_tracker import log_missed_trade, detect_untracked_moves, score_signal
from src.regime_thresholds import get_thresholds_for_regime
from src.strategy_performance_memory import log_strategy_result
from src.neural_policy_tuner import evolve_strategy_weights, log_regime_shift
from src.slippage import calculate_volatility, apply_slippage
from src.multi_timeframe import confirm_signal_multi_timeframe
import time
from src.kelly_sizing import get_position_size, get_futures_position_size_kelly
from src.capital_allocator import allocate_capital
from src.performance_tracker import track_risk_adjusted_performance, max_drawdown
from src.correlation_control import build_price_series_map, compute_correlation_matrix, correlation_exposure_cap, get_prospective_correlation_cap
from src.risk_parity import apply_risk_parity_sizing
from src.regime_fade_allocator import allocate_with_fade
from src.atr_ladder_exits import apply_atr_ladder_exits
from src.pair_overrides_loader import load_pair_overrides, get_kelly_cap_for_symbol, get_trail_pct_for_symbol, is_strategy_preferred
from src.signal_activity_logger import log_signal_evaluation
from src.bot_enhancements import update_protective_mode
from src.phase72_execution_diagnostics import log_signal_evaluation as log_phase72_signal
from src.phase72_execution import apply_phase72_filters, check_min_hold_time
from src.elite_system import Attribution, SignalDecayTracker, ProtectiveAudit, ExecutionHealth, FuturesAttribution
from src.futures_bot_helpers import (
    FuturesProtectiveState, load_futures_policy, assess_margin_safety,
    auto_reduce_positions, should_allow_futures_entry, execute_kill_switch
)
from src.futures_signal_generator import (
    generate_futures_signal, load_leverage_cap, compute_futures_qty,
    log_futures_signal_evaluation
)
from src.exchange_gateway import ExchangeGateway
from src.phase93_enforcement import (
    venue_policy, venue_guard_entry_gate, venue_guard_execution,
    venue_evaluate_spot_unfreeze, venue_detect_breach
)
from src.unified_self_governance_bot import (
    open_profit_blofin_entry,
)
from src.profit_blofin_learning import (
    promote_shadow_symbols,
    schedule_profit_learning,
    is_profit_learning_enabled,
)
from src.execution_gates import (
    init_protective_gates,
    execution_gates,
    mark_trade,
    log_gate_rejection
)
from src.alpha_signals_integration import (
    generate_live_alpha_signals,
    log_alpha_trade
)
from src.phase_281_283 import run_metadata_reconciliation, quick_verify
from src.validators.config_validator import get_validator, get_runtime_monitor
from src.critical_bug_patch import risk_check, nightly_audit
from src.metrics_refresh import pre_trade_metrics_check, nightly_metrics_audit
from src.nightly_orchestration import nightly_cycle


blofin = BlofinClient()

# [PHASES 271-280] OFI & Micro-Arb Alpha Signals (All trading is paper - no real money)
ENABLE_OFI_SIGNALS = True  # Enable OFI & micro-arb signal generation

# Initialize Elite System modules
_attribution = Attribution()
_futures_attribution = FuturesAttribution()
_decay_tracker = SignalDecayTracker(window=10)
_protective_audit = ProtectiveAudit()
_exec_health = ExecutionHealth(warn=0.004, crit=0.010)

# Initialize Futures Protective State
_futures_state = FuturesProtectiveState()
_futures_policy = load_futures_policy()
_futures_last_trade_ts = {}

# Initialize Exchange Gateway for futures trading
_exchange_gateway = ExchangeGateway()


def infer_venue(symbol: str, strategy: str = "") -> str:
    """Infer venue from centralized configuration."""
    from src.venue_config import get_venue
    return get_venue(symbol)


def run_risk_engine():
    """
    Risk management engine for FUTURES positions to prevent portfolio blow-up.
    
    Enforces:
    - Max 10 open positions total
    - Max 25% exposure per asset (with V6.5 grace window protection)
    """
    positions = get_open_futures_positions()
    portfolio = get_active_portfolio()
    portfolio_value = portfolio["portfolio_value"]
    
    if len(positions) == 0:
        return
    
    # Max positions cap (10 total)
    if len(positions) > 10:
        # Sort by unrealized P&L (close worst performers)
        # For futures: compare current price to entry based on direction
        sorted_positions = sorted(
            positions,
            key=lambda p: (p.get("peak_price" if p.get("direction") == "LONG" else "trough_price", p["entry_price"]) - p["entry_price"]) / p["entry_price"]
        )
        
        num_to_close = len(positions) - 10
        for pos in sorted_positions[:num_to_close]:
            # Use peak/trough price for exit to be conservative
            exit_price = pos.get("peak_price" if pos.get("direction") == "LONG" else "trough_price", pos["entry_price"])
            close_futures_position(pos["symbol"], pos["strategy"], pos.get("direction", "LONG"), exit_price, reason="risk_cap_max_positions")
            print(f"⚠️ Risk cap: Closed futures {pos['direction']} {pos['symbol']} (max 10 positions exceeded)")
    
    # Per-asset exposure cap (25% max) - V6.5: Skip positions in grace window
    positions = get_open_futures_positions()  # Refresh after potential closures
    per_asset = {}
    for p in positions:
        symbol = p["symbol"]
        
        # [V6.5] Check grace window - skip if position just opened (pass full position dict)
        try:
            from src.unified_recovery_learning_fix import is_in_grace_window
            if is_in_grace_window(p):
                print(f"   🛡️ V6.5: {p.get('direction')} {symbol} ({p.get('strategy')}) in grace window, skipping risk cap")
                continue
        except Exception as grace_err:
            pass  # If grace check fails, proceed with normal risk cap
        
        # Calculate notional exposure properly
        notional = p.get("notional_size", 0)
        if notional == 0:
            notional = p.get("margin_collateral", 0) * p.get("leverage", 1)
        if notional == 0:
            notional = abs(p.get("size", 0) * p.get("entry_price", 0))
        
        per_asset[symbol] = per_asset.get(symbol, 0) + notional
    
    for symbol, total_size in per_asset.items():
        exposure_pct = total_size / portfolio_value if portfolio_value > 0 else 0
        if exposure_pct > 0.25:
            # Find positions for this asset and close smallest ones
            asset_positions = [p for p in positions if p["symbol"] == symbol]
            sorted_by_size = sorted(asset_positions, key=lambda p: p["size"])
            
            # Close positions until under 25%
            for pos in sorted_by_size:
                if total_size / portfolio_value <= 0.25:
                    break
                exit_price = pos.get("peak_price" if pos.get("direction") == "LONG" else "trough_price", pos["entry_price"])
                close_futures_position(pos["symbol"], pos["strategy"], pos.get("direction", "LONG"), exit_price, reason="risk_cap_asset_exposure")
                print(f"⚠️ Risk cap: Closed futures {pos['direction']} {pos['symbol']}-{pos['strategy']} (asset exposure > 25%)")
                total_size -= pos["size"]


def startup():
    """Initialize profit-based learning system and execution gates on bot startup."""
    import os
    from src.profit_blofin_learning import log_event
    
    # Initialize execution gates (Phases 113, 123, 129)
    init_protective_gates()
    
    try:
        promote_shadow_symbols()
        
        try:
            from src.phase10_profit_engine import register_periodic_task
            schedule_profit_learning(register_periodic_task)
            print("✅ [PROFIT-LEARN] Periodic policy tuning scheduled (every 15 minutes)")
        except Exception as e:
            print(f"⚠️ [PROFIT-LEARN] Periodic scheduling unavailable: {e}")
        
        flag_status = "ENABLED" if is_profit_learning_enabled() else "DISABLED"
        log_event("startup_complete", {"profit_learning_enabled": is_profit_learning_enabled()})
        print(f"✅ [PROFIT-LEARN] Startup complete: Shadow symbols promoted, profit learning {flag_status}")
        print(f"   💡 To toggle: export ENABLE_PROFIT_LEARNING=1 (or =0 to disable)")
    except Exception as e:
        print(f"⚠️ [PROFIT-LEARN] Startup error: {e}")
    
    # Start Health Pulse Orchestrator for autonomous trading stall detection + auto-fix
    try:
        from src.health_pulse_orchestrator import start_health_pulse_monitor
        start_health_pulse_monitor()
    except Exception as e:
        print(f"⚠️ [HEALTH-PULSE] Startup error: {e}")


def execute_signal(signal: dict, wallet_balance: float, rolling_expectancy: float) -> dict:
    """
    Execute trading signal with profit-based learning (feature-flagged).
    
    Routes through profit learning module if ENABLE_PROFIT_LEARNING=1,
    otherwise falls back to legacy direct execution.
    """
    from src.position_manager import open_futures_position
    from src.futures_signal_generator import compute_futures_qty
    from src.profit_blofin_learning import log_event
    from src.exchange_gateway import ExchangeGateway
    
    if not venue_guard_entry_gate(signal):
        log_event("venue_guard_block", signal)
        return {"status": "blocked", "reason": "venue_guard"}
    
    if is_profit_learning_enabled():
        result = open_profit_blofin_entry(signal, wallet_balance, rolling_expectancy)
        
        if result["status"] == "blocked":
            return result
        
        # Handle cases where execution didn't proceed (failed/error/etc)
        if "params" not in result:
            return {"status": result.get("status", "failed"), "reason": result.get("reason", "unknown")}
        
        params = result["params"]
        
        # ═══════════════════════════════════════════════════════════════
        # PRE-EXECUTION VALIDATION (Self-Validation & Questioning Layer)
        # ═══════════════════════════════════════════════════════════════
        from src.self_validation import validate_pre_trade
        validation_passed, validation_results = validate_pre_trade(signal, params)
        
        if not validation_passed:
            # Block trade on validation failure
            critical_failures = [r for r in validation_results if not r.passed and r.severity == "CRITICAL"]
            failure_messages = [r.message for r in critical_failures]
            
            print(f"🛑 [VALIDATION-BLOCK] Trade blocked by self-validation:")
            for r in critical_failures:
                print(f"   ❌ {r.validator}: {r.message}")
                if r.details:
                    print(f"      Details: {r.details}")
            
            log_event("trade_blocked_validation", {
                "signal": signal,
                "params": params,
                "failures": [r.to_dict() for r in critical_failures]
            })
            
            return {
                "status": "blocked",
                "reason": "validation_failure",
                "validation_failures": failure_messages
            }
        
        # Validation passed - proceed with execution
        symbol = params["symbol"]
        direction = "LONG" if params["side"] in ("buy", "long") else "SHORT"
        
        gw = ExchangeGateway()
        mark_price = gw.get_price(symbol, venue="futures")
        qty = compute_futures_qty(symbol, mark_price, params["leverage"], params["margin_usd"])
        
        position = open_futures_position(
            symbol=symbol,
            direction=direction,
            entry_price=mark_price,
            size=qty,
            leverage=params["leverage"],
            strategy=params["strategy"],
            liquidation_price=None,
            margin_collateral=params["margin_usd"]
        )
        
        print(f"✅ [PROFIT-LEARN] Order placed: {symbol} {direction} @ {params['leverage']}x | Margin: ${params['margin_usd']:.2f} | Expected profit: ${params['expected_profit_usd']:.2f}")
        
        # ═══════════════════════════════════════════════════════════════
        # POST-EXECUTION VALIDATION (Self-Validation & Questioning Layer)
        # ═══════════════════════════════════════════════════════════════
        # Only validate if position is a dict (not False/None for duplicate positions)
        if not isinstance(position, dict):
            return {
                "status": "blocked",
                "reason": "position_already_exists" if position is False else "position_creation_failed",
                "position": position
            }
        
        from src.self_validation import validate_post_trade
        post_passed, post_results = validate_post_trade(params, position)
        
        if not post_passed:
            # Log critical post-execution failures and AUTO-REMEDIATE
            critical_failures = [r for r in post_results if not r.passed and r.severity == "CRITICAL"]
            print(f"⚠️ [POST-VALIDATION] Critical issues detected after execution:")
            for r in critical_failures:
                print(f"   ❌ {r.validator}: {r.message}")
                if r.details:
                    print(f"      Details: {r.details}")
            
            log_event("trade_post_validation_failed", {
                "params": params,
                "position": position,
                "failures": [r.to_dict() for r in critical_failures]
            })
            
            # AUTO-REMEDIATION: Close position if execution outcome severely mismatches request
            from src.position_manager import close_futures_position
            conversion_failed = any(
                r.validator == "ConversionIntentChecker" and not r.passed and r.severity == "CRITICAL"
                for r in critical_failures
            )
            
            if conversion_failed:
                print(f"🔧 [AUTO-REMEDIATE] Closing malformed position immediately")
                close_futures_position(
                    symbol=position["symbol"],
                    strategy=position["strategy"],
                    direction=position["direction"],
                    exit_price=position["entry_price"],  # Exit at entry price to minimize slippage
                    reason="auto_remediate_validation_failure"
                )
                
                log_event("auto_remediation_close_position", {
                    "position": position,
                    "reason": "critical_post_validation_failure"
                })
                
                return {
                    "status": "auto_remediated",
                    "action": "position_closed",
                    "reason": "critical_post_validation_failure",
                    "position": position,
                    "profit_params": params
                }
        
        return {"status": "executed", "position": position, "profit_params": params}
    else:
        symbol = signal.get("symbol", "")
        side = signal.get("side", "long").lower()
        entry_price = signal.get("entry_price", 0.0)
        leverage = signal.get("leverage", 1)
        size_usd = signal.get("size_usd", 500.0)
        
        direction = "LONG" if side in ("buy", "long") else "SHORT"
        
        gw = ExchangeGateway()
        mark_price = gw.get_price(symbol, venue="futures")
        qty = compute_futures_qty(symbol, mark_price, leverage, size_usd)
        
        position = open_futures_position(
            symbol=symbol,
            direction=direction,
            entry_price=mark_price,
            size=qty,
            leverage=leverage,
            strategy=signal.get("strategy", "EMA-Futures"),
            liquidation_price=None,
            margin_collateral=size_usd
        )
        
        return {"status": "executed", "position": position}


def run_execution():
    """Placeholder for execution engine"""
    pass


def run_forecast_logger():
    """Placeholder for forecast logging"""
    pass


def run_bot_cycle():
    """
    Main bot cycle with regime-aware multi-asset trading, position scaling, and trailing stops.
    Enforces unified venue routing (futures-only) with heartbeat monitoring and self-healing.
    """
    # [PHASES 281-283] Portfolio Metadata Reconciliation - run every hour
    import os
    from pathlib import Path
    reconcile_marker = Path("logs/.last_reconciliation")
    should_reconcile = False
    
    if not reconcile_marker.exists():
        should_reconcile = True
    else:
        last_reconcile = reconcile_marker.stat().st_mtime
        if time.time() - last_reconcile > 3600:  # 1 hour
            should_reconcile = True
    
    if should_reconcile:
        try:
            print("\n🔍 [Phases 281-283] Running portfolio metadata reconciliation...")
            verification = quick_verify()
            if verification["needs_reconciliation"]:
                print(f"   ⚠️ Discrepancy detected: ${verification['delta']:.2f} ({verification['discrepancy_pct']:.2f}%)")
                summary = run_metadata_reconciliation()
                if summary.get("had_corruption"):
                    print(f"   ✅ Metadata corrected! Discrepancies: {len(summary.get('discrepancies', {}))}")
                else:
                    print(f"   ✅ Portfolio verified - no corruption")
            else:
                print(f"   ✅ Portfolio metadata verified - no reconciliation needed")
            reconcile_marker.touch()
        except Exception as e:
            print(f"   ⚠️ Reconciliation error: {e}")
    
    # [UNIFIED VENUE ENFORCEMENT] Initialize futures-only enforcement stack
    from src.unified_venue_enforcement import start_unified_stack, run_periodic_checks
    try:
        start_unified_stack()
    except Exception as e:
        print(f"⚠️ Unified enforcement initialization error: {e}")
    
    try:
        from phase80_coordinator import get_phase80_coordinator
        p80 = get_phase80_coordinator()
        p80.emit_heartbeat("signals")
        p80.emit_heartbeat("execution")
        p80.emit_heartbeat("persistence")
    except Exception as e:
        if "phase80" in str(type(e).__name__).lower() or "phase80" in str(e).lower():
            print(f"⚠️ Phase 8.0 heartbeat emission skipped: {e}")
    
    initialize_portfolio()
    
    print("\n" + "="*60)
    print("🤖 Starting bot cycle...")
    print("="*60)
    
    from src.performance_metrics import compute_performance_metrics
    from src.unified_self_governance_bot import evaluate_kill_switch
    
    startup_metrics = compute_performance_metrics()
    print(f"\n📊 Startup Kill-Switch Check:")
    print(f"   Total fills: {startup_metrics['total_fills']}")
    print(f"   Data age: {startup_metrics['age_hours']:.1f}h")
    print(f"   Drawdown: {startup_metrics['drawdown_pct']:.1f}%")
    print(f"   Reject rate: {startup_metrics['reject_rate_pct']:.1f}%")
    
    evaluate_kill_switch(startup_metrics)
    
    # [METRICS REFRESH] Enforce fresh metrics before trading
    try:
        metrics_check = pre_trade_metrics_check()
        if not metrics_check["go"]:
            print(f"🚨 [METRICS-REFRESH] Trading frozen: {metrics_check['reason']}")
            return  # Skip this cycle
        print(f"✅ [METRICS-REFRESH] Fresh metrics OK (WR={metrics_check['metrics']['win_rate']:.1%}, EV={metrics_check['metrics']['expectancy']:.4f})")
    except Exception as e:
        import traceback
        print(f"⚠️ Metrics refresh error: {e}")
        traceback.print_exc()
    
    # [CRITICAL BUG PATCH] Pre-cycle risk check with margin recompute
    try:
        from src.futures_portfolio_tracker import load_futures_portfolio, save_futures_portfolio
        from src.portfolio_tracker import get_portfolio_stats
        
        # Get current portfolio state
        portfolio_stats = get_portfolio_stats()
        futures_portfolio = load_futures_portfolio()
        
        balance = futures_portfolio.get("total_margin_allocated", 10000.0)
        reserved = 0.0  # No reserved funds currently
        
        rc = risk_check(balance, reserved)
        
        # Persist recomputed margin back to futures portfolio
        futures_portfolio["available_margin"] = rc["margin"]["available_margin"]
        futures_portfolio["used_margin"] = rc["margin"]["used_margin"]
        save_futures_portfolio(futures_portfolio)
        
        if not rc["go"]:
            print("🚨 [RISK-CHECK] Trading cycle skipped - margin/metrics check failed")
            return  # Skip this cycle
    except Exception as e:
        import traceback
        print(f"⚠️ Risk check error: {e}")
        traceback.print_exc()
    
    # [CONFIGURATION VALIDATOR] Run startup checks on first cycle only
    validator = get_validator()
    runtime_monitor = get_runtime_monitor()
    
    validator_first_run = not hasattr(run_bot_cycle, '_validator_checked')
    if validator_first_run:
        passed, issues, warnings = validator.run_startup_checks()
        if not passed:
            print("\n" + "=" * 70)
            print("❌ CRITICAL VALIDATION FAILURE")
            print("=" * 70)
            print("The bot detected critical configuration issues that must be fixed:")
            for issue in issues:
                print(f"  {issue}")
            print("\nPlease fix these issues and restart the bot.")
            print("=" * 70)
            import sys
            sys.exit(1)
        
        canonical_assets = validator.load_canonical_assets()
        runtime_monitor.set_expected_symbols(canonical_assets)
        
        run_bot_cycle._validator_checked = True
        print(f"✅ Configuration validation passed - monitoring {len(canonical_assets)} symbols\n")
    
    regime = predict_regime()
    active_strategies = get_active_strategies_for_regime(regime)
    
    # Compute adaptive strategy weights based on performance
    strategy_weights = evolve_strategy_weights(regime, active_strategies)
    log_regime_shift(regime, strategy_weights)
    
    # Regime-aware capital allocation with smooth fading during transitions
    raw_allocation = allocate_capital()
    capital_allocation = allocate_with_fade(raw_allocation, fade_steps=5)
    
    print(f"\n📊 Active strategies for {regime}: {active_strategies}")
    
    df_btc = blofin.fetch_ohlcv("BTCUSDT", timeframe="1m", limit=100)
    
    status = log_protective_event(df_btc)
    
    # Adaptive protective mode tuning based on performance
    protective_triggered = (status["action"] == "protect")
    current_drawdown = max_drawdown  # Use global max_drawdown from performance_tracker
    update_protective_mode(current_drawdown, protective_triggered)
    
    if status["action"] == "protect":
        print("⚠️ Protective mode activated!")
        rotate_to_stablecoin(df_btc, place_order)
        log_rotation_event(df_btc)
        return
    
    reentry = reenter_market(df_btc, place_order)
    if reentry["reentry"]:
        log_reentry_event(df_btc, ASSETS)
    
    # ==========================================
    # [EXIT HEALTH SENTINEL] Collect current prices with robust error handling
    # ==========================================
    from src.exit_health_sentinel import audit_exit_health, trigger_safe_mode, update_position_prices
    
    current_prices = {}
    market_data = {}
    price_fetch_failures = []
    
    for symbol in ASSETS:
        try:
            df_quick = blofin.fetch_ohlcv(symbol, timeframe="1m", limit=50)
            if "close" in df_quick.columns:
                import pandas as pd
                # [FIX] Use live futures mark price for trailing stops instead of stale OHLCV
                try:
                    from src.venue_config import get_venue
                    venue = get_venue(symbol)
                    current_prices[symbol] = _exchange_gateway.get_price(symbol, venue=venue)
                except Exception as mark_err:
                    # Fallback to OHLCV only if mark price fetch fails
                    close_data = df_quick["close"]
                    if isinstance(close_data, pd.Series):
                        current_prices[symbol] = float(close_data.iloc[-1])
                    elif isinstance(close_data, list):
                        current_prices[symbol] = float(close_data[-1])
                    else:
                        current_prices[symbol] = float(close_data)
                    print(f"⚠️ Mark price failed for trailing stops on {symbol}, using OHLCV ({mark_err})")
                
                # Store full DataFrame for ATR calculation
                market_data[symbol] = df_quick
        except Exception as e:
            price_fetch_failures.append(symbol)
            print(f"⚠️ Could not fetch price for {symbol}: {e}")
    
    # [EXIT HEALTH SENTINEL] Update positions.json with current prices (critical for exit logic)
    if current_prices:
        update_position_prices(current_prices)
    
    # [EXIT HEALTH SENTINEL] Audit exit health BEFORE executing exit logic
    exit_health = audit_exit_health()
    if not exit_health["healthy"]:
        print(f"⚠️ EXIT HEALTH ISSUES: {exit_health['issues']}")
        if exit_health["action"] == "safe_mode":
            trigger_safe_mode()
            return  # Hard fail - cannot safely exit positions
    
    # [PHASE 92] Get exit recommendations (time-based exits, profit locks) - FUTURES ONLY
    try:
        from src.phase92_profit_discipline import phase92_get_exit_recommendations
        
        phase92_positions = get_open_futures_positions()
        exit_recs = phase92_get_exit_recommendations(phase92_positions)
        
        # Execute time-based exits for futures positions
        for rec in exit_recs:
            if rec.get("action") == "time_exit":
                symbol = rec["symbol"]
                strategy = None
                direction = None
                
                # Find futures position and close it
                for pos in phase92_positions:
                    if pos["symbol"] == symbol:
                        strategy = pos["strategy"]
                        direction = pos.get("direction", "LONG")
                        current_price = current_prices.get(symbol)
                        if current_price:
                            closed = close_futures_position(symbol, strategy, direction, current_price, reason=f"phase92_time_exit_{rec['reason']}")
                            if closed:
                                print(f"⏰ Phase 92 time exit (futures): {direction} {symbol} ({strategy}) after {rec['reason']}")
                        break
        
        # Note: Profit locks and tighter stops are advisory - trailing stop logic already handles them
    except Exception as phase92_err:
        print(f"⚠️ Phase 92 exit recommendations error: {phase92_err}")
    
    # Apply dynamic ATR-based trailing stops to all open FUTURES positions
    apply_futures_trailing_stops(current_prices, market_data=market_data)
    
    # [EXIT STALL MONITOR] Track exit metrics for Phase 75/80 monitoring
    try:
        from src.exit_stall_monitor import get_exit_stall_metrics, check_exit_stall_thresholds
        exit_metrics = get_exit_stall_metrics()
        exit_thresholds = check_exit_stall_thresholds(exit_metrics)
        
        if exit_thresholds["alert"]:
            print(f"⚠️ EXIT STALL ALERT: {exit_thresholds['reasons']}")
        
        if exit_thresholds["kill_switch"]:
            print(f"🚨 EXIT STALL KILL-SWITCH: Critical exit health failure")
            trigger_safe_mode()
            return
    except Exception as monitor_err:
        print(f"⚠️ Exit stall monitor error: {monitor_err}")
    
    # Apply ATR ladder exits for partial profit taking at milestones - FUTURES ONLY
    open_positions = get_open_futures_positions()
    for pos in open_positions:
        symbol = pos["symbol"]
        if symbol in market_data:
            df_pos = market_data[symbol]
            apply_atr_ladder_exits(pos, df_pos, symbol)
    
    # Build correlation matrix for exposure control (computed once per cycle)
    portfolio = get_active_portfolio()
    price_series_map = build_price_series_map(blofin, ASSETS, timeframe="1m", limit=120)
    corr_matrix = compute_correlation_matrix(price_series_map, window=100)
    
    print(f"\n🔗 Correlation matrix computed for {len(price_series_map)} assets")
    
    for symbol in ASSETS:
        try:
            df = blofin.fetch_ohlcv(symbol, timeframe="1m", limit=100)
            import pandas as pd
            
            # Ensure close is a Series for consistent access
            if "close" in df.columns:
                close_series = pd.Series(df["close"]) if not isinstance(df["close"], pd.Series) else df["close"]
                # [FIX] Use live futures mark price instead of stale OHLCV for entry pricing
                try:
                    from src.venue_config import get_venue
                    venue = get_venue(symbol)
                    current_price = _exchange_gateway.get_price(symbol, venue=venue)
                    print(f"✅ Live {venue} price for {symbol}: ${current_price:.4f}")
                except Exception as mark_err:
                    # Fallback to OHLCV only if mark price fetch fails
                    current_price = float(close_series.iloc[-1])
                    print(f"⚠️ Mark price failed for {symbol}, using OHLCV: ${current_price:.4f} ({mark_err})")
            else:
                print(f"⚠️ No close data for {symbol}, skipping")
                continue
            
            portfolio = get_active_portfolio()
            
            # Update peak/trough prices for ALL open futures positions for this symbol
            current_open_positions = get_open_futures_positions()
            for pos in current_open_positions:
                if pos["symbol"] == symbol:
                    update_futures_peak_trough(
                        symbol=pos["symbol"],
                        strategy=pos["strategy"],
                        direction=pos["direction"],
                        current_price=current_price
                    )
            
            # === [PHASES 274-275] OFI & MICRO-ARB ALPHA SIGNALS ===
            if ENABLE_OFI_SIGNALS:
                try:
                    # Pass None to force fresh gateway instance (avoid module caching)
                    alpha_signals = generate_live_alpha_signals(
                        symbol=symbol,
                        exchange_gateway=None,
                        regime=regime
                    )
                    
                    # Log alpha signal for monitoring
                    if alpha_signals['combined_signal'] != 'HOLD':
                        print(f"🎯 [ALPHA] {symbol}: OFI={alpha_signals['ofi_value']:.3f} | "
                              f"Signal={alpha_signals['combined_signal']} | "
                              f"Arb={alpha_signals['arb_opportunity']} | "
                              f"Enter={alpha_signals['should_enter']}")
                    
                    # [v5.7 OFI SHADOW MODE] Log signals for shadow intelligence learning
                    # OFI signals are NO LONGER executed directly - they provide overlays for other strategies
                    if alpha_signals['should_enter'] and alpha_signals['combined_signal'] != 'HOLD':
                        # Calculate expected ROI based on OFI signal strength
                        ofi_confidence = abs(alpha_signals['ofi_value'])
                        base_roi = 0.015  # 1.5% base expectation
                        max_roi = 0.05    # 5% cap
                        expected_roi = min(base_roi * (1 + ofi_confidence), max_roi)
                        expected_move_pct = expected_roi * 100
                        
                        # [PHASES 288-290] Composite Alpha Fusion: Multi-signal alignment check
                        from src.phase_288_290_composite_alpha import pre_execution_gate
                        from src.phase_287_fee_governor import _get_symbol_tier
                        
                        tier_config = _get_symbol_tier(symbol)
                        tier_fee_pct = tier_config.get("fee_pct", 0.06)
                        tier_slippage_pct = tier_config.get("slippage_pct", 0.04)
                        
                        composite_order = {
                            "symbol": symbol,
                            "side": alpha_signals['combined_signal'],
                            "regime": regime,
                            "stage": "shadow",  # SHADOW MODE - not live execution
                            "signals": {
                                "ofi": alpha_signals['ofi_value'],
                                "micro_arb": alpha_signals.get('arb_edge_bps', 0.0),
                                "sentiment": 0.0,
                                "regime_strength": 0.5
                            },
                            "expected_move_pct": expected_move_pct,
                            "fee_cost_pct": tier_fee_pct * 2,
                            "slippage_pct": tier_slippage_pct,
                            "size_multiplier": 1.0
                        }
                        
                        composite_decision = pre_execution_gate(composite_order)
                        
                        # Log signal for shadow intelligence learning
                        import os
                        shadow_signal = {
                            "ts": int(time.time()),
                            "symbol": symbol,
                            "strategy_id": "OFI-Micro-Arb-v1",
                            "ofi_score": alpha_signals['ofi_value'],
                            "composite": composite_decision['composite_score'],
                            "expected_roi": expected_roi,
                            "side": alpha_signals['combined_signal'],
                            "regime": regime,
                            "status": "shadow",  # Not executed, logged for learning
                            "block_reason": composite_decision.get('reason') if not composite_decision["allow_trade"] else None,
                            "fee_margin": expected_move_pct - (tier_fee_pct * 2 + tier_slippage_pct)
                        }
                        
                        # Append to strategy signals log for OFI shadow intelligence
                        signal_log_path = "logs/strategy_signals.jsonl"
                        os.makedirs(os.path.dirname(signal_log_path) or ".", exist_ok=True)
                        with open(signal_log_path, "a") as f:
                            import json
                            f.write(json.dumps(shadow_signal) + "\n")
                        
                        print(f"📊 [OFI-SHADOW] {symbol}: OFI={alpha_signals['ofi_value']:.3f} | Signal={alpha_signals['combined_signal']} | Composite={composite_decision['composite_score']:.4f} | Mode=LEARNING")
                        
                        # Note: OFI signals are now used as OVERLAYS for longer-term strategies
                        # See src/ofi_shadow_intelligence.py for learning cycle
                
                except Exception as alpha_err:
                    print(f"⚠️ [ALPHA] Signal generation failed for {symbol}: {alpha_err}")
            
            # Load pair overrides on first cycle
            load_pair_overrides()
            
            # Batch risk parity adjustment for all active strategies on this symbol
            provisional_kelly_sizes = {}
            for strat in active_strategies:
                if is_strategy_preferred(symbol, strat):
                    kelly = get_position_size(portfolio["current_value"], strat, regime, use_kelly=True)
                    kelly_cap_override = get_kelly_cap_for_symbol(symbol)
                    if kelly_cap_override:
                        kelly = min(kelly, portfolio["current_value"] * kelly_cap_override)
                    provisional_kelly_sizes[strat] = kelly
            
            # Apply risk parity across all strategies for this symbol
            parity_adjusted_sizes = apply_risk_parity_sizing(provisional_kelly_sizes)
            
            for strategy_name in active_strategies:
                # Check if strategy is preferred for this symbol
                if not is_strategy_preferred(symbol, strategy_name):
                    continue
                
                # [PHASE 9.3 ENFORCEMENT] Router-level venue policy
                signal_ctx = {
                    "symbol": symbol,
                    "strategy": strategy_name,
                    "venue": infer_venue(symbol, strategy_name)
                }
                if not venue_policy(signal_ctx):
                    log_signal_evaluation(symbol, strategy_name, "blocked_venue_policy", 0)
                    continue
                
                if strategy_name == "Trend-Conservative":
                    # Multi-timeframe confirmation (1m + 15m)
                    confirmed, roi, signal_data = confirm_signal_multi_timeframe(symbol, strategy_name, blofin)
                    
                    if confirmed == False or roi is None:
                        # Log no signal or timeframe mismatch
                        log_signal_evaluation(symbol, strategy_name, "blocked_multi_timeframe", roi or 0)
                        continue
                    
                    if (confirmed == True or confirmed == 'partial') and roi is not None:
                        # Ensemble confidence scoring
                        df_short = blofin.fetch_ohlcv(symbol, timeframe="1m", limit=120)
                        df_long = blofin.fetch_ohlcv(symbol, timeframe="15m", limit=120)
                        score, threshold, components = ensemble_confidence_score(
                            symbol, strategy_name, df_short, df_long, regime, roi
                        )
                        
                        # Elite System: Track signal decay
                        _decay_tracker.update(symbol, strategy_name, score)
                        
                        if confirmed == 'partial':
                            threshold = threshold * 0.50
                            print(f"   🟡 Partial MTF: Relaxed ensemble threshold to {threshold:.2f} for {symbol}")
                        
                        if score < threshold:
                            print(f"⏸️  {symbol} - {strategy_name}: ensemble score {score:.2f} < {threshold:.2f}")
                            # Log blocked by ensemble
                            log_signal_evaluation(symbol, strategy_name, "blocked_ensemble", roi)
                            # Elite System: Log protective audit
                            _protective_audit.log(symbol, strategy_name, regime, reason="ensemble_low", roi=roi)
                            # Log as missed opportunity if suppressed by ensemble
                            if roi > 0.003:
                                prev_close = float(close_series.iloc[-2]) if len(close_series) >= 2 else current_price
                                log_missed_trade(symbol, strategy_name, ["Ensemble"], prev_close, current_price, components, regime)
                            continue
                        
                        # Log signal quality
                        if signal_data:
                            log_signal_quality(symbol, strategy_name, roi, signal_data.get("volume_ratio", 1.0), 
                                             signal_data.get("momentum", 0), signal_data.get("ema_gap", 0))
                        
                        # PHASE 11.1: Lowered ROI threshold to 0.10% (from 0.18%) based on autonomous analysis
                        if confirmed == 'partial' and roi >= 0.0010:
                            print(f"   🟢 Accepting partial confirmation with ROI {roi*100:.2f}% >= 0.10% (fee-safe)")
                            should_trade, reason = True, "partial_confirmation"
                        elif confirmed == 'partial' and roi < 0.0010:
                            print(f"   ❌ Rejecting partial confirmation: ROI {roi*100:.2f}% < 0.10% (below fee threshold)")
                            should_trade, reason = False, "sub_fee_roi"
                        else:
                            should_trade, reason = should_execute_trade(symbol, roi)
                        
                        # [PHASE 9.3 ENFORCEMENT] Gate-level venue check before sizing
                        if not venue_guard_entry_gate(signal_ctx):
                            log_signal_evaluation(symbol, strategy_name, "blocked_venue_gate", roi)
                            continue
                        
                        if should_trade:
                            log_strategy_performance(df, "Trend-Conservative", roi)
                            amount = 0.01 if symbol != "BTCUSDT" else 0.001
                            
                            # Multi-layer position sizing: Use pre-calculated parity-adjusted size
                            kelly_size = parity_adjusted_sizes.get(strategy_name, 
                                get_position_size(portfolio["current_value"], strategy_name, regime, use_kelly=True))
                            
                            budget_cap = capital_allocation.get(strategy_name, kelly_size)
                            
                            # Get prospective correlation cap (checks BEFORE trade with fresh position data)
                            # SPOT DISABLED: fresh_positions = get_open_positions()  # Fresh data before EACH trade
                            fresh_positions = []  # Empty for futures-only mode
                            correlation_cap = get_prospective_correlation_cap(
                                symbol, kelly_size, fresh_positions, corr_matrix,
                                max_pair_corr=0.85, max_cluster_exposure_pct=0.40,
                                portfolio_value=portfolio["current_value"]
                            )
                            
                            position_size = min(kelly_size, budget_cap, correlation_cap)
                            
                            # [PHASE 10.2] Apply futures concentration strategy
                            try:
                                from src.phase102_futures_optimizer import phase102_allocate_for_signal
                                position_size = phase102_allocate_for_signal(signal_ctx, position_size)
                            except Exception:
                                pass
                            
                            # Log if correlation limits position
                            if correlation_cap < min(kelly_size, budget_cap):
                                print(f"🔗 {symbol}-{strategy_name}: Corr cap ${correlation_cap:.0f} limits position")
                            
                            # Apply slippage for realistic execution price
                            volatility = calculate_volatility(df)
                            exec_price = apply_slippage(current_price, volatility)
                            
                            # Skip if position size is zero or negative
                            if position_size <= 0:
                                print(f"⚠️  {symbol}-{strategy_name}: Skipping zero-size position (budget cap: ${budget_cap:.0f})")
                                continue
                            
                            # [PHASE 9.3 ENFORCEMENT] Execution-level venue check
                            if not venue_guard_execution(symbol, "buy", position_size, signal_ctx["venue"], strategy_name):
                                log_signal_evaluation(symbol, strategy_name, "blocked_venue_execution", roi)
                                continue
                            
                            # Only record trade if position actually opens
                            # SPOT DISABLED: if open_position(symbol, exec_price, position_size, "Trend-Conservative"):
                                # Log executed trade
                                log_signal_evaluation(symbol, strategy_name, "executed", roi)
                                record_trade(symbol, "buy", amount, exec_price, "Trend-Conservative", roi, position_pct=position_size/portfolio["current_value"])
                                record_trade_time(symbol)
                                # [PHASE 9.3] Detect breach if spot executed while disabled
                                venue_detect_breach(signal_ctx["venue"], symbol, "buy", position_size, "Trend-Conservative")
                                # [PHASE 10.1] Update attribution
                                try:
                                    from src.phase101_allocator import update_attribution
                                    update_attribution(symbol, "Trend-Conservative", 0.0, signal_ctx["venue"])
                                except Exception:
                                    pass
                                log_strategy_result("Trend-Conservative", regime, roi, missed=False)
                        else:
                            # Log blocked by ROI/cooldown
                            log_signal_evaluation(symbol, strategy_name, f"blocked_{reason}", roi)
                            # Log missed opportunity
                            if signal_data and roi < 0.0018:
                                prev_close = float(close_series.iloc[-2]) if len(close_series) >= 2 else current_price
                                log_missed_trade(
                                    symbol, "Trend-Conservative", ["ROI"], 
                                    prev_close, current_price, signal_data, regime
                                )
                                log_strategy_result("Trend-Conservative", regime, roi, missed=True)
                            
                            # Check if we can scale into existing position
                            # SPOT DISABLED: scaled, additional_size, scale_roi = scale_into_position(symbol, current_price, "Trend-Conservative", portfolio["current_value"])
                            scaled = False  # Disabled for futures-only mode
                            if scaled:
                                # Record the scaling trade
                                amount = 0.005 if symbol != "BTCUSDT" else 0.0005
                                record_trade(symbol, "buy", amount, current_price, "Trend-Conservative-Scale", scale_roi)
                            else:
                                print(f"⏸️  {symbol} - Trend-Conservative: {reason}")
                
                elif strategy_name == "Breakout-Aggressive":
                    # Multi-timeframe confirmation (1m + 15m)
                    confirmed, roi, signal_data = confirm_signal_multi_timeframe(symbol, strategy_name, blofin)
                    
                    if confirmed == False or roi is None:
                        # Log no signal or timeframe mismatch
                        log_signal_evaluation(symbol, strategy_name, "blocked_multi_timeframe", roi or 0)
                        continue
                    
                    if (confirmed == True or confirmed == 'partial') and roi is not None:
                        # Ensemble confidence scoring
                        df_short = blofin.fetch_ohlcv(symbol, timeframe="1m", limit=120)
                        df_long = blofin.fetch_ohlcv(symbol, timeframe="15m", limit=120)
                        score, threshold, components = ensemble_confidence_score(
                            symbol, strategy_name, df_short, df_long, regime, roi
                        )
                        
                        if confirmed == 'partial':
                            threshold = threshold * 0.50
                            print(f"   🟡 Partial MTF: Relaxed ensemble threshold to {threshold:.2f} for {symbol}")
                        
                        if score < threshold:
                            print(f"⏸️  {symbol} - {strategy_name}: ensemble score {score:.2f} < {threshold:.2f}")
                            # Log blocked by ensemble
                            log_signal_evaluation(symbol, strategy_name, "blocked_ensemble", roi)
                            continue
                        
                        # Log signal quality
                        if signal_data:
                            log_signal_quality(symbol, strategy_name, roi, signal_data.get("volume_ratio", 1.0), 
                                             signal_data.get("momentum", 0), signal_data.get("ema_gap", 0))
                        
                        # PHASE 11.1: Lowered ROI threshold to 0.10% (from 0.18%) based on autonomous analysis
                        if confirmed == 'partial' and roi >= 0.0010:
                            print(f"   🟢 Accepting partial confirmation with ROI {roi*100:.2f}% >= 0.10% (fee-safe)")
                            should_trade, reason = True, "partial_confirmation"
                        elif confirmed == 'partial' and roi < 0.0010:
                            print(f"   ❌ Rejecting partial confirmation: ROI {roi*100:.2f}% < 0.10% (below fee threshold)")
                            should_trade, reason = False, "sub_fee_roi"
                        else:
                            should_trade, reason = should_execute_trade(symbol, roi)
                        
                        # [PHASE 9.3 ENFORCEMENT] Gate-level venue check before sizing
                        if not venue_guard_entry_gate(signal_ctx):
                            log_signal_evaluation(symbol, strategy_name, "blocked_venue_gate", roi)
                            continue
                        
                        if should_trade:
                            log_strategy_performance(df, "Breakout-Aggressive", roi)
                            amount = 0.01 if symbol != "BTCUSDT" else 0.001
                            
                            # Multi-layer position sizing: Use pre-calculated parity-adjusted size
                            kelly_size = parity_adjusted_sizes.get(strategy_name, 
                                get_position_size(portfolio["current_value"], strategy_name, regime, use_kelly=True))
                            
                            budget_cap = capital_allocation.get(strategy_name, kelly_size)
                            
                            # Get prospective correlation cap (checks BEFORE trade with fresh position data)
                            # SPOT DISABLED: fresh_positions = get_open_positions()  # Fresh data before EACH trade
                            fresh_positions = []  # Empty for futures-only mode
                            correlation_cap = get_prospective_correlation_cap(
                                symbol, kelly_size, fresh_positions, corr_matrix,
                                max_pair_corr=0.85, max_cluster_exposure_pct=0.40,
                                portfolio_value=portfolio["current_value"]
                            )
                            
                            position_size = min(kelly_size, budget_cap, correlation_cap)
                            
                            # [PHASE 10.2] Apply futures concentration strategy
                            try:
                                from src.phase102_futures_optimizer import phase102_allocate_for_signal
                                position_size = phase102_allocate_for_signal(signal_ctx, position_size)
                            except Exception:
                                pass
                            
                            # Log if correlation limits position
                            if correlation_cap < min(kelly_size, budget_cap):
                                print(f"🔗 {symbol}-{strategy_name}: Corr cap ${correlation_cap:.0f} limits position")
                            
                            # Apply slippage for realistic execution price
                            volatility = calculate_volatility(df)
                            exec_price = apply_slippage(current_price, volatility)
                            
                            # Skip if position size is zero or negative
                            if position_size <= 0:
                                print(f"⚠️  {symbol}-{strategy_name}: Skipping zero-size position (budget cap: ${budget_cap:.0f})")
                                continue
                            
                            # [PHASE 9.3 ENFORCEMENT] Execution-level venue check
                            if not venue_guard_execution(symbol, "buy", position_size, signal_ctx["venue"], strategy_name):
                                log_signal_evaluation(symbol, strategy_name, "blocked_venue_execution", roi)
                                continue
                            
                            # Only record trade if position actually opens
                            # SPOT DISABLED: if open_position(symbol, exec_price, position_size, "Breakout-Aggressive"):
                                # Log executed trade
                                log_signal_evaluation(symbol, strategy_name, "executed", roi)
                                record_trade(symbol, "buy", amount, exec_price, "Breakout-Aggressive", roi, position_pct=position_size/portfolio["current_value"])
                                record_trade_time(symbol)
                                # [PHASE 9.3] Detect breach if spot executed while disabled
                                venue_detect_breach(signal_ctx["venue"], symbol, "buy", position_size, "Breakout-Aggressive")
                                # [PHASE 10.1] Update attribution
                                try:
                                    from src.phase101_allocator import update_attribution
                                    update_attribution(symbol, "Breakout-Aggressive", 0.0, signal_ctx["venue"])
                                except Exception:
                                    pass
                                log_strategy_result("Breakout-Aggressive", regime, roi, missed=False)
                        else:
                            # Log blocked by ROI/cooldown
                            log_signal_evaluation(symbol, strategy_name, f"blocked_{reason}", roi)
                            # SPOT DISABLED: scaled, additional_size, scale_roi = scale_into_position(symbol, current_price, "Breakout-Aggressive", portfolio["current_value"])
                            scaled = False  # Disabled for futures-only mode
                            if scaled:
                                amount = 0.005 if symbol != "BTCUSDT" else 0.0005
                                record_trade(symbol, "buy", amount, current_price, "Breakout-Aggressive-Scale", scale_roi)
                            else:
                                print(f"⏸️  {symbol} - Breakout-Aggressive: {reason}")
                
                elif strategy_name == "Sentiment-Fusion":
                    # Multi-timeframe confirmation (1m + 15m)
                    confirmed, roi, signal_data = confirm_signal_multi_timeframe(symbol, strategy_name, blofin)
                    
                    if confirmed == False or roi is None:
                        # Log no signal or timeframe mismatch
                        log_signal_evaluation(symbol, strategy_name, "blocked_multi_timeframe", roi or 0)
                        continue
                    
                    if (confirmed == True or confirmed == 'partial') and roi is not None:
                        # Ensemble confidence scoring
                        df_short = blofin.fetch_ohlcv(symbol, timeframe="1m", limit=120)
                        df_long = blofin.fetch_ohlcv(symbol, timeframe="15m", limit=120)
                        score, threshold, components = ensemble_confidence_score(
                            symbol, strategy_name, df_short, df_long, regime, roi
                        )
                        
                        # Elite System: Track signal decay
                        _decay_tracker.update(symbol, strategy_name, score)
                        
                        if confirmed == 'partial':
                            threshold = threshold * 0.50
                            print(f"   🟡 Partial MTF: Relaxed ensemble threshold to {threshold:.2f} for {symbol}")
                        
                        if score < threshold:
                            print(f"⏸️  {symbol} - {strategy_name}: ensemble score {score:.2f} < {threshold:.2f}")
                            # Log blocked by ensemble
                            log_signal_evaluation(symbol, strategy_name, "blocked_ensemble", roi)
                            # Elite System: Log protective audit
                            _protective_audit.log(symbol, strategy_name, regime, reason="ensemble_low", roi=roi)
                            # Log as missed opportunity if suppressed by ensemble
                            if roi > 0.003:
                                prev_close = float(close_series.iloc[-2]) if len(close_series) >= 2 else current_price
                                log_missed_trade(symbol, strategy_name, ["Ensemble"], prev_close, current_price, components, regime)
                            continue
                        
                        # Log signal quality
                        if signal_data:
                            log_signal_quality(symbol, strategy_name, roi, signal_data.get("volume_ratio", 1.0), 
                                             signal_data.get("momentum", 0), signal_data.get("ema_gap", 0))
                        
                        # PHASE 11.1: Lowered ROI threshold to 0.10% (from 0.18%) based on autonomous analysis
                        if confirmed == 'partial' and roi >= 0.0010:
                            print(f"   🟢 Accepting partial confirmation with ROI {roi*100:.2f}% >= 0.10% (fee-safe)")
                            should_trade, reason = True, "partial_confirmation"
                        elif confirmed == 'partial' and roi < 0.0010:
                            print(f"   ❌ Rejecting partial confirmation: ROI {roi*100:.2f}% < 0.10% (below fee threshold)")
                            should_trade, reason = False, "sub_fee_roi"
                        else:
                            should_trade, reason = should_execute_trade(symbol, roi)
                        
                        # [PHASE 9.3 ENFORCEMENT] Gate-level venue check before sizing
                        if not venue_guard_entry_gate(signal_ctx):
                            log_signal_evaluation(symbol, strategy_name, "blocked_venue_gate", roi)
                            continue
                        
                        if should_trade:
                            log_strategy_performance(df, "Sentiment-Fusion", roi)
                            amount = 0.01 if symbol != "BTCUSDT" else 0.001
                            
                            # Multi-layer position sizing: Use futures sizing for futures trades
                            # Get futures margin budget allocation for this strategy
                            from src.capital_allocator import allocate_futures_margin
                            futures_margin_allocation = allocate_futures_margin()
                            strategy_margin_budget = futures_margin_allocation.get(strategy_name, 0)
                            
                            # Call futures sizing function instead of spot sizing
                            sizing_result = get_futures_position_size_kelly(
                                portfolio_value=portfolio["current_value"],
                                strategy=strategy_name,
                                regime=regime,
                                leverage=load_leverage_cap(symbol, strategy_name, regime),
                                strategy_margin_budget=strategy_margin_budget
                            )
                            
                            # Extract margin allocation from sizing result
                            kelly_size = sizing_result["margin_allocation"]
                            budget_cap = strategy_margin_budget
                            
                            # Get prospective correlation cap (checks BEFORE trade with fresh position data)
                            # SPOT DISABLED: fresh_positions = get_open_positions()  # Fresh data before EACH trade
                            fresh_positions = []  # Empty for futures-only mode
                            correlation_cap = get_prospective_correlation_cap(
                                symbol, kelly_size, fresh_positions, corr_matrix,
                                max_pair_corr=0.85, max_cluster_exposure_pct=0.40,
                                portfolio_value=portfolio["current_value"]
                            )
                            
                            position_size = min(kelly_size, budget_cap, correlation_cap)
                            
                            # [PHASE 10.2] Apply futures concentration strategy
                            try:
                                from src.phase102_futures_optimizer import phase102_allocate_for_signal
                                position_size = phase102_allocate_for_signal(signal_ctx, position_size)
                            except Exception:
                                pass
                            
                            # Log if correlation limits position
                            if correlation_cap < min(kelly_size, budget_cap):
                                print(f"🔗 {symbol}-{strategy_name}: Corr cap ${correlation_cap:.0f} limits position")
                            
                            # Log if correlation cap limits position
                            if correlation_cap < kelly_size:
                                print(f"🔗 {symbol}: Correlation cap ${correlation_cap:.0f} < Kelly ${kelly_size:.0f}")
                            
                            # Apply slippage for realistic execution price
                            volatility = calculate_volatility(df)
                            exec_price = apply_slippage(current_price, volatility)
                            
                            # Skip if position size is zero or negative
                            if position_size <= 0:
                                print(f"⚠️  {symbol}-{strategy_name}: Skipping zero-size position (budget cap: ${budget_cap:.0f})")
                                continue
                            
                            # [PHASE 9.3 ENFORCEMENT] Execution-level venue check
                            if not venue_guard_execution(symbol, "buy", position_size, signal_ctx["venue"], strategy_name):
                                log_signal_evaluation(symbol, strategy_name, "blocked_venue_execution", roi)
                                continue
                            
                            # Only record trade if position actually opens
                            # SPOT DISABLED: if open_position(symbol, exec_price, position_size, "Sentiment-Fusion"):
                                # Log executed trade
                                log_signal_evaluation(symbol, strategy_name, "executed", roi)
                                record_trade(symbol, "buy", amount, exec_price, "Sentiment-Fusion", roi, position_pct=position_size/portfolio["current_value"])
                                record_trade_time(symbol)
                                # [PHASE 9.3] Detect breach if spot executed while disabled
                                venue_detect_breach(signal_ctx["venue"], symbol, "buy", position_size, "Sentiment-Fusion")
                                # [PHASE 10.1] Update attribution
                                try:
                                    from src.phase101_allocator import update_attribution
                                    update_attribution(symbol, "Sentiment-Fusion", 0.0, signal_ctx["venue"])
                                except Exception:
                                    pass
                                log_strategy_result("Sentiment-Fusion", regime, roi, missed=False)
                        else:
                            # Log blocked by ROI/cooldown
                            log_signal_evaluation(symbol, strategy_name, f"blocked_{reason}", roi)
                            # Log missed opportunity
                            if signal_data and roi < 0.0018:
                                prev_close = float(close_series.iloc[-2]) if len(close_series) >= 2 else current_price
                                log_missed_trade(
                                    symbol, "Sentiment-Fusion", ["ROI"], 
                                    prev_close, current_price, signal_data, regime
                                )
                                log_strategy_result("Sentiment-Fusion", regime, roi, missed=True)
                            
                            # SPOT DISABLED: scaled, additional_size, scale_into_position(symbol, current_price, "Sentiment-Fusion", portfolio["current_value"])
                            scaled = False  # Disabled for futures-only mode
                            if scaled:
                                amount = 0.005 if symbol != "BTCUSDT" else 0.0005
                                record_trade(symbol, "buy", amount, current_price, "Sentiment-Fusion-Scale", scale_roi)
                            else:
                                print(f"⏸️  {symbol} - Sentiment-Fusion: {reason}")
                        
                        # Detect untracked large moves
                        detect_untracked_moves(symbol, df, "Sentiment-Fusion", regime)
        
        except Exception as e:
            import traceback
            print(f"⚠️ Error trading {symbol}: {e}")
            traceback.print_exc()
            continue
    
    # ==========================================
    # FUTURES MARGIN SAFETY MONITORING
    # ==========================================
    try:
        margin_report, protective_mode = assess_margin_safety(_futures_state, _futures_policy)
        
        # Log margin status if any positions exist
        if margin_report.get("positions"):
            print(f"\n🛡️ Futures Margin Safety: {protective_mode}")
            
            # Display position statuses
            for pos in margin_report.get("positions", []):
                buffer = pos.get("buffer_pct", 0)
                status_icon = "✅" if pos.get("status") == "OK" else "⚠️" if pos.get("status") == "ALERT" else "🚨"
                print(f"   {status_icon} {pos['symbol']}: Buffer {buffer:.2f}% ({pos.get('status')})")
            
            # Auto-reduce positions if in REDUCE mode
            if protective_mode == "REDUCE":
                print(f"\n🚨 PROTECTIVE MODE: Auto-reducing positions with buffer < {_futures_policy['auto_reduce_pct']}%")
                auto_reduce_positions(_futures_state, margin_report, _futures_policy)
            
            # Warn if blocking new entries
            elif protective_mode == "BLOCK":
                print(f"\n⚠️ PROTECTIVE MODE: Blocking new futures entries (buffer < {_futures_policy['block_buffer_pct']}%)")
            
            elif protective_mode == "ALERT":
                print(f"\n⚠️ Margins in ALERT range (buffer < {_futures_policy['alert_buffer_pct']}%)")
    
    except Exception as e:
        print(f"⚠️ Futures margin monitoring error: {e}")
        import traceback
        traceback.print_exc()
    
    # ==========================================
    # FUTURES SIGNAL GENERATION & TRADING
    # ==========================================
    try:
        from src.position_manager import open_futures_position
        
        # Get all futures symbols from venue config
        from src.venue_config import VENUE_MAP
        all_futures_symbols = [sym for sym, venue in VENUE_MAP.items() if venue == "futures"]
        
        # Prioritize by recent volatility (higher volatility = more profit opportunity)
        symbol_volatility = {}
        for sym in all_futures_symbols:
            try:
                df = _exchange_gateway.fetch_ohlcv(sym, timeframe="1m", limit=50, venue="futures")
                if df is not None and len(df) >= 20:
                    returns = df["close"].pct_change().dropna()
                    volatility = returns.std() * 100  # Convert to percentage
                    symbol_volatility[sym] = volatility
            except:
                symbol_volatility[sym] = 0.0
        
        # Sort by volatility (descending), take all symbols
        futures_symbols = sorted(symbol_volatility.keys(), key=lambda s: symbol_volatility.get(s, 0), reverse=True)
        
        if futures_symbols:
            vol_sorted = [(s, symbol_volatility.get(s, 0)) for s in futures_symbols[:5]]
            print(f"📊 Top 5 futures symbols by volatility: {', '.join([f'{s} ({v:.2f}%)' for s, v in vol_sorted])}")
        
        # Phase 7.2: Start with 20% margin, ratchet to 30% when profitable
        from src.phase72_execution import get_futures_margin_budget
        futures_margin_budget = get_futures_margin_budget(portfolio["current_value"])
        
        for symbol in futures_symbols:
            try:
                df = _exchange_gateway.fetch_ohlcv(symbol, timeframe="1m", limit=100, venue="futures")
                
                if df is None or len(df) < 30:
                    continue
                
                prices = df["close"]
                signal = generate_futures_signal(symbol, prices, strategy="EMA-Futures", regime=regime)
                
                last_ts = _futures_last_trade_ts.get(symbol, 0)
                cooldown_seconds = _futures_policy.get("cooldown_seconds", 60)
                on_cooldown = (time.time() - last_ts) < cooldown_seconds
                
                # [PHASE 10.3] Pre-entry efficiency check
                phase10x_allowed = True
                try:
                    from src.phase10x_combined import phase10x_pre_entry
                    signal_ctx = {"symbol": symbol, "strategy": "EMA-Futures", "venue": "futures", "position_size_usd": futures_margin_budget}
                    phase10x_allowed = phase10x_pre_entry(signal_ctx)
                except Exception as e:
                    print(f"   ⚠️ PHASE 10.3: Pre-entry check failed: {e}")
                
                protective_ok, protective_reason = should_allow_futures_entry(_futures_state, symbol)
                
                if not phase10x_allowed:
                    allowed = False
                    reason = "phase10x_blocked(spread/slippage)"
                elif not protective_ok:
                    allowed = False
                    reason = protective_reason
                elif on_cooldown:
                    allowed = False
                    reason = f"cooldown:{round(cooldown_seconds - (time.time() - last_ts), 1)}s"
                else:
                    allowed = True
                    reason = "ok"
                
                if signal["action"] in ("OPEN_LONG", "OPEN_SHORT"):
                    if allowed:
                        direction = "LONG" if signal["action"] == "OPEN_LONG" else "SHORT"
                        
                        # Phase 7.2: Check SHORT suppression
                        from src.phase72_execution import should_suppress_short
                        suppress, suppress_reason = should_suppress_short(symbol, direction)
                        if suppress:
                            print(f"   🛑 SHORT suppressed: {suppress_reason}")
                            continue
                        
                        leverage = load_leverage_cap(symbol, "EMA-Futures", regime)
                        mark_price = _exchange_gateway.get_price(symbol, venue="futures")
                        qty = compute_futures_qty(symbol, mark_price, leverage, futures_margin_budget)
                        
                        # [PHASE 10.2] Apply futures concentration strategy
                        adjusted_margin = futures_margin_budget  # Default to original
                        try:
                            from src.phase102_futures_optimizer import phase102_allocate_for_signal
                            base_margin = futures_margin_budget
                            signal_ctx = {"symbol": symbol, "strategy": "EMA-Futures", "venue": "futures"}
                            adjusted_margin = phase102_allocate_for_signal(signal_ctx, base_margin)
                            if adjusted_margin != base_margin:
                                print(f"   🎯 PHASE 10.2: Margin adjusted {base_margin:.2f} → {adjusted_margin:.2f} (multiplier: {adjusted_margin/base_margin:.2f}x)")
                            qty = compute_futures_qty(symbol, mark_price, leverage, adjusted_margin)
                        except Exception as e:
                            print(f"   ⚠️ PHASE 10.2: Allocation failed: {e}")
                        
                        # [PHASE 10.3] Apply regime-based risk modulation and winner bias
                        try:
                            from src.phase10x_combined import phase10x_modulate_size, phase10x_get_stop_metadata
                            signal_ctx = {"symbol": symbol, "strategy": "EMA-Futures", "venue": "futures"}
                            modulated_margin, metadata = phase10x_modulate_size(signal_ctx, adjusted_margin)
                            if modulated_margin != adjusted_margin:
                                adjusted_margin = modulated_margin
                                qty = compute_futures_qty(symbol, mark_price, leverage, adjusted_margin)
                                print(f"   🎯 PHASE 10.3: Risk-modulated margin → {adjusted_margin:.2f} (regime={metadata['regime']}, bias={metadata['bias']:.2f}x)")
                        except Exception as e:
                            print(f"   ⚠️ PHASE 10.3: Size modulation failed: {e}")
                        
                        if qty > 0:
                            print(f"\n🔮 FUTURES SIGNAL: {signal['action']} {symbol} @ {leverage}x (qty: {qty})")
                            
                            # [V6.5] Pre-entry check with correct exposure calculation + fee gating
                            try:
                                from src.unified_recovery_learning_fix import pre_entry_check, post_open_guard
                                notional = adjusted_margin * leverage
                                runtime_limits = {"max_exposure": 0.25, "max_leverage": leverage}
                                
                                # Get verdict for fee-aware gating
                                try:
                                    from src.reverse_triage import ReverseTriage
                                    rt = ReverseTriage()
                                    verdict_data = rt._verdict()
                                    verdict_status = verdict_data.get("verdict", "Losing")
                                except:
                                    verdict_status = "Losing"  # Safe default
                                
                                # Add direction to context for grace window tracking
                                ctx_direction = {"direction": direction}
                                
                                approved, ctx = pre_entry_check(
                                    symbol=symbol,
                                    strategy_id="EMA-Futures",
                                    position_notional=notional,
                                    portfolio_value=portfolio["portfolio_value"],
                                    runtime_limits=runtime_limits,
                                    regime_state=regime,
                                    verdict_status=verdict_status,
                                    expected_edge_hint=0.005  # 0.5% expected edge hint
                                )
                                
                                # Merge direction into context
                                ctx.update(ctx_direction)
                                
                                if not approved:
                                    print(f"   ❌ V6.5: Entry blocked by pre-check")
                                    continue
                            except Exception as pre_check_err:
                                print(f"   ⚠️ V6.5 pre-check error: {pre_check_err}")
                                # Allow trade to proceed if pre-check fails (fail-open)
                            
                            position = open_futures_position(
                                symbol=symbol,
                                direction=direction,
                                entry_price=mark_price,
                                size=qty,
                                leverage=leverage,
                                strategy="EMA-Futures",
                                liquidation_price=None,
                                margin_collateral=adjusted_margin
                            )
                            
                            # [V6.5] Post-open grace window guard
                            try:
                                from src.unified_recovery_learning_fix import post_open_guard
                                if 'ctx' in locals():
                                    post_open_guard(ctx)
                            except Exception as post_guard_err:
                                print(f"   ⚠️ V6.5 post-guard error: {post_guard_err}")
                            
                            _futures_last_trade_ts[symbol] = time.time()
                            
                            log_futures_signal_evaluation(
                                symbol, signal, True, "executed", leverage, qty
                            )
                            
                            print(f"   ✅ Opened {direction} position: {qty} {symbol} @ {leverage}x")
                        else:
                            log_futures_signal_evaluation(symbol, signal, False, "zero_qty", leverage, 0)
                    else:
                        log_futures_signal_evaluation(symbol, signal, False, reason, None, None)
                        print(f"   🚫 {symbol} futures entry blocked: {reason}")
                else:
                    log_futures_signal_evaluation(symbol, signal, False, "no_signal", None, None)
            
            except Exception as e:
                print(f"⚠️ Futures signal error for {symbol}: {e}")
                continue
    
    except Exception as e:
        print(f"⚠️ Futures signal generation error: {e}")
        import traceback
        traceback.print_exc()
    
    # ==========================================
    # FUTURES LADDER EXITS
    # ==========================================
    try:
        # Note: get_open_futures_positions already imported at top of file (line 15)
        from src.futures_ladder_exits import build_ladder_plan, evaluate_exit_triggers, execute_ladder_exits
        
        futures_positions = get_open_futures_positions()
        
        for pos in futures_positions:
            try:
                symbol = pos["symbol"]
                df = _exchange_gateway.fetch_ohlcv(symbol, timeframe="1m", limit=50, venue="futures")
                
                if df is None or len(df) < 20:
                    continue
                
                signal = generate_futures_signal(symbol, df["close"], strategy=pos["strategy"], regime=regime)
                signal_reversed = (
                    (pos["direction"] == "LONG" and signal["state"] == "SHORT") or
                    (pos["direction"] == "SHORT" and signal["state"] == "LONG")
                )
                
                plan = build_ladder_plan(
                    symbol=symbol,
                    strategy=pos["strategy"],
                    regime=regime,
                    side=pos["direction"],
                    total_qty=pos["size"],
                    entry_price=pos["entry_price"],
                    leverage=pos["leverage"]
                )
                
                triggers = evaluate_exit_triggers(
                    plan=plan,
                    prices=df["close"],
                    high=df["high"],
                    low=df["low"],
                    signal_reverse=signal_reversed,
                    protective_mode=protective_mode
                )
                
                if triggers:
                    results = execute_ladder_exits(plan, triggers)
                    
                    for result in results:
                        if result.get("status") == "executed":
                            print(f"   🎯 Ladder exit: Tier {result['tier']} ({result['reason']}) - {result['qty']:.6f} @ ${result['price']:.2f}")
                        elif result.get("status") == "cooldown":
                            print(f"   ⏸️ Ladder exits on cooldown: {result['seconds_left']}s")
                            break
            
            except Exception as e:
                print(f"⚠️ Ladder exit error for {pos.get('symbol', 'unknown')}: {e}")
                continue
    
    except Exception as e:
        print(f"⚠️ Futures ladder exits error: {e}")
        import traceback
        traceback.print_exc()
    
    # ==========================================
    # SMALL POSITION ACCELERATOR - REMOVED (SPOT ONLY)
    # ==========================================
    # COMMENTED OUT: This was for spot trading only - futures positions don't need accelerator
    # from src.small_position_accelerator import check_and_exit_small_positions
    # from src.position_manager import close_position
    
    # ==========================================
    # SPOT RISK ENGINE
    # ==========================================
    run_risk_engine()
    run_execution()
    run_forecast_logger()
    
    record_hourly_pnl()
    
    # Track risk-adjusted performance metrics
    portfolio = load_portfolio()
    if portfolio.get("trades") and len(portfolio["trades"]) >= 2:
        track_risk_adjusted_performance(portfolio["trades"])
    
    try:
        from phase80_coordinator import get_phase80_coordinator
        p80 = get_phase80_coordinator()
        p80.emit_heartbeat("telemetry")
        p80.emit_heartbeat("fees")
    except Exception as e:
        if "phase80" in str(type(e).__name__).lower() or "phase80" in str(e).lower():
            print(f"⚠️ Phase 8.0 telemetry/fees heartbeat skipped: {e}")
    
    # Elite System: Persist diagnostic data at end of cycle
    try:
        _decay_tracker.persist()
        _protective_audit.persist()
        _exec_health.persist()
        _futures_attribution.persist()
    except Exception as e:
        print(f"⚠️ Elite System persistence error: {e}")
    
    # [UNIFIED VENUE ENFORCEMENT] Run periodic integrity and heartbeat checks
    try:
        from src.unified_venue_enforcement import run_periodic_checks
        run_periodic_checks()
    except Exception as e:
        print(f"⚠️ Unified venue periodic checks error: {e}")
    
    # [PHASE 9.3 ENFORCEMENT] Periodic venue evaluation (check if spot can be re-enabled)
    try:
        from datetime import datetime, timedelta
        import pytz
        portfolio = load_portfolio()
        
        # Calculate spot-only performance from recent trades
        spot_symbols = ["ETHUSDT", "SOLUSDT", "AVAXUSDT", "DOTUSDT", "TRXUSDT", "BTCUSDT"]
        arizona_tz = pytz.timezone('America/Phoenix')
        cutoff_time = datetime.now(arizona_tz) - timedelta(hours=24)
        
        spot_pnl_24h = 0.0
        spot_trades_24h = []
        
        for trade in portfolio.get("trades", []):
            try:
                trade_time_str = trade.get("timestamp", "2020-01-01T00:00:00")
                trade_time = datetime.fromisoformat(trade_time_str)
                # Make timezone-aware if naive
                if trade_time.tzinfo is None:
                    trade_time = arizona_tz.localize(trade_time)
                
                if trade_time > cutoff_time and trade.get("symbol") in spot_symbols:
                    spot_trades_24h.append(trade)
                    spot_pnl_24h += trade.get("pnl", 0.0)
            except (ValueError, AttributeError):
                continue
        
        # Calculate spot Sharpe (simplified: mean return / std dev of returns)
        spot_sharpe_24h = 0.0
        if len(spot_trades_24h) >= 5:
            returns = [t.get("roi", 0.0) for t in spot_trades_24h if t.get("roi") is not None]
            if returns and len(returns) >= 5:
                import numpy as np
                spot_sharpe_24h = np.mean(returns) / (np.std(returns) + 1e-9) if np.std(returns) > 0 else 0.0
        
        venue_evaluate_spot_unfreeze(spot_sharpe_24h, spot_pnl_24h)
    except Exception as e:
        print(f"⚠️ Venue evaluation error: {e}")
    
    # Write heartbeat for governance monitoring
    try:
        portfolio = get_active_portfolio()
        positions = get_open_futures_positions()
        write_heartbeat("bot_cycle", {
            "portfolio_value": portfolio.get("portfolio_value", 0.0),
            "open_positions": len(positions),
            "available_margin": portfolio.get("available_margin", 0.0)
        })
    except Exception as e:
        print(f"⚠️ Heartbeat write error: {e}")
    
    # [PHASES 284-286] Self-Healing Layer - detect anomalies and auto-reconcile
    try:
        from src.phase_284_286 import run_self_healing_cycle
        healing_summary = run_self_healing_cycle()
        if healing_summary.get("anomalies"):
            print(f"🏥 Self-healing detected {len(healing_summary['anomalies'])} anomalies: {', '.join(healing_summary['anomalies'])}")
            if healing_summary.get("actions"):
                print(f"   🔧 Actions taken: {', '.join(healing_summary['actions'])}")
    except Exception as e:
        print(f"⚠️ Self-healing error: {e}")
    
    # [PHASES 294-297] Advanced Autonomy Expansion - adaptive exploration & risk elasticity
    try:
        from src.phase_294_297_expansion_integrated import run_expansion_cycle
        
        # Calculate health score (simplified: based on win rate and profitability)
        total_pnl = portfolio.get("realized_pnl", 0)
        portfolio_value = portfolio.get("current_value", 10000)
        pnl_ratio = total_pnl / 10000.0  # Relative to starting capital
        current_health = min(1.0, max(0.0, 0.5 + pnl_ratio))  # 0.0-1.0 scale
        
        # Calculate rolling EV (simplified from recent trades)
        recent_trades = portfolio.get("trades", [])[-20:]
        rolling_ev = sum([t.get("pnl", 0) for t in recent_trades]) / max(1, len(recent_trades)) if recent_trades else 0.0
        
        # Determine stage based on portfolio performance
        stage = "high_confidence" if total_pnl > 500 else "unlocked" if total_pnl > 100 else "bootstrap"
        
        # Build expectancy by regime (placeholder - could be enhanced with actual tracking)
        expectancy_by_regime = {
            "trend": 0.05,
            "chop": -0.02,
            "breakout": 0.03,
            "mean_rev": 0.01,
            "uncertain": 0.0
        }
        
        # Run expansion cycle
        expansion_summary = run_expansion_cycle(
            stage=stage,
            regime=regime,
            confidence=0.5,  # Default confidence
            symbol="BTCUSDT",  # Primary symbol for exploration
            expectancy_by_regime=expectancy_by_regime,
            health=current_health,
            rolling_ev=rolling_ev
        )
        
        # Log key metrics
        print(f"🔬 [EXPANSION] Stage={stage} | Risk Multiplier={expansion_summary['risk_multiplier']}x | "
              f"Decay Quota={expansion_summary['decay_quota']} | Weakest Regime={expansion_summary['curriculum']['weakest']}")
    except Exception as e:
        import traceback
        print(f"⚠️ Expansion cycle error: {e}")
        traceback.print_exc()
    
    # [PHASES 298-300] Meta-Governance & Scaling - portfolio governance, shadow experiments, knowledge graph
    try:
        from src.phase_298_300_meta_governance import run_meta_governance
        import json
        
        # Load canonical assets from config
        canonical_assets_path = "config/asset_universe.json"
        with open(canonical_assets_path, "r") as f:
            canonical_assets_data = json.load(f)
        # Extract symbols from asset_universe list
        canonical_symbols = [a["symbol"] for a in canonical_assets_data["asset_universe"]]
        
        # Calculate expectancy by symbol (rolling EV from recent trades)
        expectancy_by_symbol = {}
        risk_scores = {}
        all_trades = portfolio.get("trades", [])
        
        for symbol in canonical_symbols:
            symbol_trades = [t for t in all_trades[-100:] if t.get("symbol") == symbol]
            if symbol_trades:
                avg_pnl = sum([t.get("pnl", 0) for t in symbol_trades]) / len(symbol_trades)
                win_rate = sum([1 for t in symbol_trades if t.get("pnl", 0) > 0]) / len(symbol_trades)
                expectancy_by_symbol[symbol] = avg_pnl * win_rate
                
                # Risk score: volatility of returns (higher std = higher risk)
                pnls = [t.get("pnl", 0) for t in symbol_trades]
                risk_scores[symbol] = max(0.1, sum([(p - avg_pnl)**2 for p in pnls]) / len(pnls)) if len(pnls) > 1 else 1.0
            else:
                expectancy_by_symbol[symbol] = 0.0
                risk_scores[symbol] = 1.0
        
        # Prepare signals snapshot (from latest OFI/composite data)
        # CRITICAL FIX: Lowered composite threshold from 0.30 to 0.15
        # OFI-based composite scores typically range 0.02-0.15, not 0.30+
        signals_snapshot = {
            "regime": regime,
            "regime_strength": 0.5,  # Placeholder
            "composite_threshold": 0.15
        }
        
        # Run meta-governance
        portfolio_value = portfolio.get("current_value", 10000)
        meta_summary = run_meta_governance(
            expectancy_by_symbol=expectancy_by_symbol,
            risk_scores=risk_scores,
            symbols=canonical_symbols,
            regime=regime,
            signals=signals_snapshot,
            outcome=rolling_ev,
            total_capital=portfolio_value
        )
        
        # Log top 3 allocated symbols
        allocations = meta_summary["portfolio"]["allocations"]
        top_3 = sorted(allocations.items(), key=lambda x: x[1], reverse=True)[:3]
        top_str = ", ".join([f"{sym}=${amt:.0f}" for sym, amt in top_3])
        print(f"📊 [META-GOV] Portfolio Allocations (Top 3): {top_str}")
        print(f"   🧪 Shadow experiments: {len(meta_summary['shadows']['shadow_portfolios'])} symbols")
        print(f"   🧠 Knowledge graph entry logged for {meta_summary['knowledge_graph_entry']['symbol']}")
    except Exception as e:
        import traceback
        print(f"⚠️ Meta-governance error: {e}")
        traceback.print_exc()
    
    # [PHASES 301-303] Meta-Research & Governance Overlays - hypothesis generation, signal attribution, knowledge graph healing
    try:
        from src.phase_301_303_meta_research import run_meta_research
        
        # Calculate signal-level expectancy (simplified from recent composite alpha decisions)
        signal_ev = {
            "ofi": 0.05,  # Placeholder - could track from composite alpha decisions
            "micro_arb": 0.02,
            "sentiment": 0.0,
            "regime": 0.03
        }
        
        # Get base allocations from meta-governance
        base_alloc = meta_summary["portfolio"]["allocations"] if "meta_summary" in locals() else {}
        
        # Only run if we have allocations
        if base_alloc and sum(base_alloc.values()) > 0:
            portfolio_value = portfolio.get("current_value", 10000)
            research_summary = run_meta_research(
                signal_ev=signal_ev,
                base_alloc=base_alloc,
                total_capital=portfolio_value
            )
            
            # Log key metrics
            boosted_top_3 = sorted(research_summary["boosted_alloc"].items(), key=lambda x: x[1], reverse=True)[:3]
            boosted_str = ", ".join([f"{sym}=${amt:.0f}" for sym, amt in boosted_top_3])
            print(f"🔬 [META-RESEARCH] EV-Boosted Allocations (Top 3): {boosted_str}")
            print(f"   💡 Hypotheses generated: {len(research_summary['hypotheses'])}")
            print(f"   🧪 Challenger experiments spawned: {len(research_summary['experiments'])}")
            if research_summary['hypotheses']:
                print(f"   📝 Latest hypothesis: {research_summary['hypotheses'][0]}")
            
            # [PHASES 304-306] Research Memory & Auto-Promotion - track hypotheses, promote winners, audit
            try:
                from src.phase_304_306_research_memory import run_research_memory_cycle
                
                memory_summary = run_research_memory_cycle(
                    hypotheses=research_summary['hypotheses'],
                    experiments=research_summary['experiments']
                )
                
                print(f"📚 [RESEARCH-MEMORY] Tracked: {len(memory_summary['tracked'])} hypotheses")
                print(f"   ⭐ Promoted: {len(memory_summary['promoted'])} to live configs")
                print(f"   🧹 Audit: {memory_summary['audit']['ledger_size_after']} active hypotheses, {memory_summary['audit']['contradictions_found']} contradictions")
                
                # [PHASES 307-309] Governance Council - research agenda, synergy detection, multi-agent voting
                try:
                    from src.phase_307_309_governance_council import run_governance_cycle
                    
                    # Build expectancy by regime (simplified)
                    expectancy_by_regime = {"trend": 0.05, "chop": -0.02, "uncertain": 0.01}
                    
                    # Build signal matrix for synergy detection
                    signal_matrix = {
                        "BTCUSDT": {"ofi": 0.05, "sentiment": 0.0},
                        "ETHUSDT": {"ofi": 0.02, "sentiment": 0.0}
                    }
                    
                    # Sample config for governance vote
                    sample_config = research_summary['experiments'][0]['config'] if research_summary['experiments'] else {
                        "risk_mult": 1.0, "threshold": 0.25, "exploration_bias": "focused"
                    }
                    
                    governance_summary = run_governance_cycle(
                        hypotheses=research_summary['hypotheses'],
                        expectancy_by_regime=expectancy_by_regime,
                        signal_matrix=signal_matrix,
                        configs=sample_config
                    )
                    
                    print(f"🏛️ [GOVERNANCE] Agenda prioritized: {len(governance_summary['agenda'])} items")
                    print(f"   🔗 Synergies detected: {len(governance_summary['synergies'])}")
                    print(f"   🗳️ Council vote: {governance_summary['council_decision']['allow_promotion']} (PASS={list(governance_summary['council_decision']['votes'].values()).count('PASS')}/3)")
                    if governance_summary['agenda']:
                        print(f"   📋 Top priority: {governance_summary['agenda'][0][:80]}...")
                    
                    # [PHASES 310-312] Strategic Meta-Governance - voting ledger, conflict resolution, roadmap
                    try:
                        from src.phase_310_312_strategic_governance import run_strategic_governance
                        
                        # Get council decision details
                        council_votes = governance_summary['council_decision']['votes']
                        council_hypothesis = governance_summary['council_decision']['hypothesis']
                        council_outcome = governance_summary['council_decision']['allow_promotion']
                        
                        # Build rationale
                        pass_agents = [k for k,v in council_votes.items() if v=="PASS"]
                        fail_agents = [k for k,v in council_votes.items() if v=="FAIL"]
                        rationale = f"Approved by: {', '.join(pass_agents)}. Rejected by: {', '.join(fail_agents)}." if fail_agents else f"Unanimous approval by all agents."
                        
                        # Portfolio goals
                        portfolio_goals = {
                            "trend": "Improve trend regime expectancy",
                            "chop": "Reduce chop regime losses",
                            "uncertain": "Stabilize uncertain regime performance"
                        }
                        
                        strategic_summary = run_strategic_governance(
                            hypothesis=council_hypothesis,
                            votes=council_votes,
                            rationale=rationale,
                            configs=sample_config,
                            hypotheses=research_summary['hypotheses'],
                            portfolio_goals=portfolio_goals
                        )
                        
                        print(f"📜 [STRATEGIC-GOV] Vote recorded: {strategic_summary['vote_entry']['outcome']}")
                        if strategic_summary['conflict_resolution']:
                            print(f"   ⚠️ Conflict detected - Arbitration experiment spawned")
                        else:
                            print(f"   ✅ Consensus achieved - No conflict")
                        print(f"   🗓️ 7-day roadmap generated with {len(strategic_summary['roadmap']['agenda'])} milestones")
                        
                        # [PHASES 313-315] Institutional Audit - attribution, budget, audit packet
                        try:
                            from src.phase_313_315_institutional_audit import run_institutional_audit
                            
                            # Portfolio outcomes (simplified expectancy by regime)
                            portfolio_outcomes = {
                                "trend": 0.05,
                                "chop": -0.02,
                                "uncertain": 0.01
                            }
                            
                            # Research priorities (based on weakest regimes)
                            priorities = {
                                "trend": 3,
                                "chop": 6,  # Highest priority for weakest regime
                                "uncertain": 2
                            }
                            
                            # Collect governance activity
                            votes = [strategic_summary['vote_entry']]
                            promotions = memory_summary['promoted'] if memory_summary else []
                            conflicts = [strategic_summary['conflict_resolution']] if strategic_summary['conflict_resolution'] else []
                            
                            audit_summary = run_institutional_audit(
                                roadmap=strategic_summary['roadmap'],
                                portfolio_outcomes=portfolio_outcomes,
                                hypotheses=research_summary['hypotheses'],
                                priorities=priorities,
                                votes=votes,
                                promotions=promotions,
                                conflicts=conflicts
                            )
                            
                            print(f"📊 [INSTITUTIONAL-AUDIT] Attribution: {len(audit_summary['attribution'])} milestones linked")
                            print(f"   💰 Budget allocated: {sum(audit_summary['budget_allocations'].values()):.0f} units across {len(audit_summary['budget_allocations'])} hypotheses")
                            print(f"   📋 Audit packet generated: {len(audit_summary['votes'])} votes, {len(audit_summary['promotions'])} promotions, {len(audit_summary['conflicts'])} conflicts")
                            
                            # [PHASES 316-318] Meta-Institutional Intelligence - external data fusion, compliance, scaling
                            try:
                                from src.phase_316_318_meta_institution import run_meta_institution
                                
                                # Simplified external data (macro + news sentiment)
                                macro_data = {"inflation": 0.03, "gdp_growth": 0.02}
                                news_sentiment = {
                                    "BTC": 0.6, "ETH": 0.4, "SOL": 0.5,
                                    "AVAX": 0.3, "DOT": 0.2
                                }
                                
                                # Governance inputs from portfolio outcomes
                                governance_inputs = portfolio_outcomes
                                
                                # Audit packets list
                                audit_packets = [audit_summary]
                                
                                # Venues for scaling
                                venues = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "AVAXUSDT", "DOTUSDT"]
                                
                                meta_summary = run_meta_institution(
                                    macro=macro_data,
                                    news_sentiment=news_sentiment,
                                    governance_inputs=governance_inputs,
                                    votes=votes,
                                    promotions=promotions,
                                    audit_packets=audit_packets,
                                    venues=venues,
                                    base_capital=portfolio_value
                                )
                                
                                print(f"🌐 [META-INSTITUTION] External data fusion: {len(meta_summary['fusion']['fusion_score'])} symbols scored")
                                print(f"   📜 Compliance: {meta_summary['compliance']['status']} ({meta_summary['compliance']['standard']} standard)")
                                print(f"   💹 Capital scaling: ${sum(meta_summary['scaling']['capital_allocations'].values()):.0f} allocated across {len(meta_summary['scaling']['capital_allocations'])} venues")
                            except Exception as e:
                                import traceback
                                print(f"⚠️ Meta-institution error: {e}")
                                traceback.print_exc()
                                
                        except Exception as e:
                            import traceback
                            print(f"⚠️ Institutional audit error: {e}")
                            traceback.print_exc()
                            
                    except Exception as e:
                        import traceback
                        print(f"⚠️ Strategic governance error: {e}")
                        traceback.print_exc()
                        
                except Exception as e:
                    import traceback
                    print(f"⚠️ Governance council error: {e}")
                    traceback.print_exc()
                    
            except Exception as e:
                import traceback
                print(f"⚠️ Research memory error: {e}")
                traceback.print_exc()
        else:
            print(f"🔬 [META-RESEARCH] Skipped - waiting for trade history to build allocations")
    except Exception as e:
        import traceback
        print(f"⚠️ Meta-research error: {e}")
        traceback.print_exc()
    
    # [CRITICAL BUG PATCH] Nightly diagnostic audit (runs once per day at midnight Arizona time)
    try:
        import datetime
        import pytz
        
        arizona_tz = pytz.timezone('America/Phoenix')
        now = datetime.datetime.now(arizona_tz)
        
        if now.hour == 0 and now.minute < 2:  # Run at midnight Arizona time
            from src.futures_portfolio_tracker import load_futures_portfolio
            
            # Run margin audit
            futures_portfolio = load_futures_portfolio()
            balance = futures_portfolio.get("total_margin_allocated", 10000.0)
            reserved = 0.0  # No reserved funds currently
            audit_result = nightly_audit(balance, reserved)
            
            # Run metrics audit
            nightly_metrics_audit()
            
            # [NIGHTLY ORCHESTRATION] Run multi-asset optimization
            try:
                print("\n🌙 [NIGHTLY-ORCHESTRATION] Starting nightly multi-asset optimization...")
                
                # Collect data for all 11 assets (ASSETS already imported at module level from regime_detector)
                import json
                import os
                
                # Helper to load trade history from logs (robust with fallbacks)
                def load_trade_history():
                    trades_by_asset = {a: [] for a in ASSETS}
                    log_path = 'logs/trade_log.jsonl'
                    
                    if not os.path.exists(log_path):
                        print(f"   ℹ️  trade_log.jsonl not found, using empty history")
                        return trades_by_asset
                    
                    try:
                        with open(log_path, 'r') as f:
                            for line in f:
                                if not line.strip():
                                    continue
                                try:
                                    trade = json.loads(line.strip())
                                    symbol = trade.get('symbol', '')
                                    if symbol in ASSETS:
                                        trades_by_asset[symbol].append({
                                            'ts': trade.get('timestamp', 0),
                                            'roi': trade.get('roi', 0.0)
                                        })
                                except json.JSONDecodeError:
                                    continue  # Skip malformed lines
                    except Exception as e:
                        print(f"   ⚠️  Error loading trade history: {e}")
                    
                    return trades_by_asset
                
                # Helper to build price series from market data (robust with fallbacks)
                def build_price_series(symbols, lookback=120):
                    price_series_by_asset = {}
                    for symbol in symbols:
                        try:
                            candles = exchange.fetch_ohlcv(symbol, '1m', limit=lookback)
                            if candles and len(candles) > 0:
                                price_series_by_asset[symbol] = [
                                    {'ts': int(c[0]/1000), 'price': c[4]} for c in candles
                                ]
                            else:
                                price_series_by_asset[symbol] = []
                        except Exception as e:
                            print(f"   ⚠️  Failed to fetch candles for {symbol}: {e}")
                            price_series_by_asset[symbol] = []
                    return price_series_by_asset
                
                # Collect data with validation
                trades_by_asset = load_trade_history()
                price_series_by_asset = build_price_series(ASSETS)
                capacity_trades_by_asset = trades_by_asset  # Use same trades for capacity analysis
                modes_by_asset = {a: "shadow" for a in ASSETS}  # Start all in shadow mode
                
                # Validate we have some data before proceeding
                total_trades = sum(len(t) for t in trades_by_asset.values())
                total_prices = sum(len(p) for p in price_series_by_asset.values())
                
                if total_trades == 0 and total_prices == 0:
                    print(f"   ⚠️  No data available for nightly orchestration, skipping")
                else:
                    print(f"   📊 Loaded {total_trades} trades and {total_prices} price points across {len(ASSETS)} assets")
                    
                    # Run nightly orchestration with error handling
                    packet = nightly_cycle(
                        price_series_by_asset,
                        trades_by_asset,
                        capacity_trades_by_asset,
                        modes_by_asset,
                        portfolio_alloc_tests=[0.05, 0.10, 0.20, 0.40]
                    )
                    
                    print(f"✅ [NIGHTLY-ORCHESTRATION] Completed successfully")
                    print(f"   Portfolio weights updated: {len(packet['multi_asset_summary']['weights']['weights'])} assets")
                    print(f"   Scaling decision: {packet['portfolio_scaling_decision']['action']}")
                
            except Exception as e:
                import traceback
                print(f"⚠️ [NIGHTLY-ORCHESTRATION] Error during optimization: {e}")
                print(f"   Nightly cycle will retry at next midnight window")
                traceback.print_exc()
                
    except Exception as e:
        import traceback
        print(f"⚠️ Nightly audit error: {e}")
        traceback.print_exc()
    
    print("\n✅ Bot cycle completed successfully")
    print("="*60)
