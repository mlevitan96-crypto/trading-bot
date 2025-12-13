"""
Kelly Criterion position sizing for optimal capital allocation.
Uses historical win rate and payoff ratio to calculate mathematically optimal position sizes.

Phase 1 Optimizations:
- Volatility-weighted Kelly (reduces size during high volatility)
- Sharpe/Sortino throttle (reduces size during poor risk-adjusted performance)
"""
import numpy as np
from src.strategy_performance_memory import load_strategy_memory
from src.optimization_enhancements import optimize_spot_size, optimize_futures_size

# Feature flags for Phase 1 optimizations
ENABLE_VOL_WEIGHTING = True
ENABLE_SHARPE_THROTTLE = True


def calculate_kelly_fraction(win_rate, payoff_ratio):
    """
    Calculate Kelly Criterion fraction for optimal position sizing.
    
    Kelly formula: f* = (bp - q) / b
    where:
    - b = payoff ratio (avg win / avg loss)
    - p = win rate (probability of winning)
    - q = 1 - p (probability of losing)
    
    Args:
        win_rate: Probability of winning (0.0 to 1.0)
        payoff_ratio: Average win / average loss
    
    Returns:
        Kelly fraction (capped at 0.25 for safety)
    """
    if payoff_ratio <= 0 or win_rate <= 0:
        return 0.05  # Default conservative sizing
    
    # Clamp win_rate to 0.99 max to avoid division issues with perfect performance
    # A true 100% win rate would make q=0, breaking Kelly math
    p = min(win_rate, 0.99)
    b = payoff_ratio
    q = 1 - p
    
    kelly_fraction = (b * p - q) / b
    
    # Safety caps:
    # - No negative sizing (no edge)
    # - Max 25% per position (risk management)
    # - Use half-Kelly for conservative approach
    half_kelly = kelly_fraction * 0.5
    
    return max(0.01, min(half_kelly, 0.25))


def get_win_rate_and_payoff(strategy, regime):
    """
    Calculate win rate and payoff ratio from strategy performance history.
    
    Args:
        strategy: Strategy name
        regime: Market regime
    
    Returns:
        Tuple (win_rate, payoff_ratio)
    """
    memory = load_strategy_memory()
    key = f"{strategy}_{regime}"
    
    if key not in memory["performance"]:
        # No history: use default conservative values
        return 0.50, 1.5  # 50% win rate, 1.5:1 payoff
    
    perf = memory["performance"][key]
    roi_history = perf.get("roi_history", [])
    
    if len(roi_history) < 10:
        # Insufficient data: use defaults
        return 0.50, 1.5
    
    # Calculate win rate
    wins = [r for r in roi_history if r > 0]
    losses = [r for r in roi_history if r < 0]
    
    win_rate = len(wins) / len(roi_history) if roi_history else 0.50
    
    # Calculate payoff ratio
    if wins and losses:
        avg_win = np.mean(wins)
        avg_loss = abs(np.mean(losses))
        payoff_ratio = float(avg_win / avg_loss) if avg_loss > 0 else 1.5
    else:
        payoff_ratio = 1.5  # Default
    
    return win_rate, payoff_ratio


def get_position_size_kelly(portfolio_value, strategy, regime, volatility=None):
    """
    Calculate optimal position size using Kelly Criterion with Phase 1 optimizations.
    
    Phase 1 Enhancements:
    - Volatility-weighted Kelly: Reduces size when volatility is high
    - Sharpe/Sortino throttle: Reduces size when risk-adjusted performance is poor
    - Trading Policy Enforcement: Enforces dynamic position size limits
    - WIN-RATE SCALING: Increases limits when performance is strong (2025-11-29)
    
    Args:
        portfolio_value: Current portfolio value
        strategy: Strategy name
        regime: Market regime
        volatility: Current market volatility (optional, auto-detected if None)
    
    Returns:
        Position size in USD
    """
    # Import trading policy for position sizing limits with win-rate scaling
    try:
        from config.trading_policy import TRADING_POLICY, get_scaled_position_limits
        
        if TRADING_POLICY.get("ENABLE_WIN_RATE_SCALING", False):
            from src.data_registry import DataRegistry as DR
            closed_positions = DR.get_closed_positions(hours=24)
            
            if closed_positions:
                wins = [p for p in closed_positions if float(p.get("net_pnl", 0) or 0) > 0]
                current_wr = len(wins) / len(closed_positions) if closed_positions else 0.4
                recent_pnl = sum(float(p.get("net_pnl", 0) or 0) for p in closed_positions)
                pnl_positive = recent_pnl > 0
            else:
                current_wr = 0.40
                pnl_positive = True
            
            scaled_limits = get_scaled_position_limits(current_wr, pnl_positive)
            min_size = scaled_limits["min_size"]
            max_size = scaled_limits["max_size"]
            tier = scaled_limits["tier"]
            
            print(f"   🎯 Win-Rate Scaling: WR={current_wr*100:.1f}% → Tier={tier} (${min_size}-${max_size})")
        else:
            min_size = TRADING_POLICY["MIN_POSITION_SIZE_USD"]
            max_size = TRADING_POLICY["MAX_POSITION_SIZE_USD"]
        
        conviction_multipliers = TRADING_POLICY.get("CONVICTION_MULTIPLIERS", {"high": 1.5, "very_high": 2.0})
        conviction_thresholds = TRADING_POLICY.get("CONVICTION_THRESHOLDS", {"high": 0.65, "very_high": 0.75})
    except ImportError:
        min_size = 300
        max_size = 1200
        conviction_multipliers = {"high": 1.5, "very_high": 2.0}
        conviction_thresholds = {"high": 0.65, "very_high": 0.75}
    
    win_rate, payoff_ratio = get_win_rate_and_payoff(strategy, regime)
    kelly_fraction = calculate_kelly_fraction(win_rate, payoff_ratio)
    
    base_position_size = portfolio_value * kelly_fraction
    
    # Phase 1 Optimizations (only if at least one flag is enabled)
    if ENABLE_VOL_WEIGHTING or ENABLE_SHARPE_THROTTLE:
        # Auto-detect volatility from regime if not provided
        if volatility is None:
            volatility = _estimate_volatility_from_regime(regime)
        
        # Import with feature flags
        from src.optimization_enhancements import apply_optimization_enhancements
        
        optimized_size, metadata = apply_optimization_enhancements(
            base_size=base_position_size,
            bankroll=portfolio_value,
            p_win=win_rate,
            rr=payoff_ratio,
            current_vol=volatility,
            use_vol_weighting=ENABLE_VOL_WEIGHTING,  # Pass flag through
            use_sharpe_throttle=ENABLE_SHARPE_THROTTLE,  # Pass flag through
            kelly_scale=0.25,
            min_size=100.0,
            enforce_min=True
        )
        
        # Show optimization impact
        throttle = metadata.get("throttle", {}).get("throttle", 1.0)
        vol_weight = metadata.get("kelly", {}).get("vol_weight", 1.0)
        
        print(f"   📊 Kelly Sizing: WR={win_rate*100:.1f}% | P/L={payoff_ratio:.2f} | Base Size={kelly_fraction*100:.1f}% (${base_position_size:.2f})")
        
        if ENABLE_VOL_WEIGHTING and volatility:
            print(f"      🔧 Vol Weight: {vol_weight:.2f}x (vol={volatility:.1%})")
        
        if ENABLE_SHARPE_THROTTLE and throttle != 1.0:
            sharpe = metadata.get("throttle", {}).get("sharpe", 0)
            print(f"      🔧 Sharpe Throttle: {throttle:.2f}x (Sharpe={sharpe:.2f})")
        
        if optimized_size != base_position_size and base_position_size > 0:
            print(f"      ✅ Optimized: ${optimized_size:.2f} ({(optimized_size/base_position_size - 1)*100:+.1f}%)")
        
        # Apply trading policy limits
        final_size = max(min_size, min(max_size, optimized_size))
        if final_size != optimized_size:
            print(f"      🔒 Policy Limit: ${optimized_size:.2f} → ${final_size:.2f} (enforcing \${min_size}-\${max_size} range)")
            
            # Emit structured event for autonomous detection
            from src.policy_cap_events import emit_kelly_policy_cap
            cap_reason = "min_cap" if final_size == min_size else "max_cap"
            emit_kelly_policy_cap(
                venue="spot",
                strategy=strategy,
                regime=regime,
                symbol="unknown",  # Caller can override
                requested_size=optimized_size,
                final_size=final_size,
                min_limit=min_size,
                max_limit=max_size,
                cap_reason=cap_reason
            )
        
        return final_size
    else:
        print(f"   📊 Kelly Sizing: WR={win_rate*100:.1f}% | P/L={payoff_ratio:.2f} | Size={kelly_fraction*100:.1f}% (${base_position_size:.2f})")
        
        # Apply trading policy limits
        final_size = max(min_size, min(max_size, base_position_size))
        if final_size != base_position_size:
            print(f"      🔒 Policy Limit: ${base_position_size:.2f} → ${final_size:.2f} (enforcing \${min_size}-\${max_size} range)")
            
            # Emit structured event for autonomous detection
            from src.policy_cap_events import emit_kelly_policy_cap
            cap_reason = "min_cap" if final_size == min_size else "max_cap"
            emit_kelly_policy_cap(
                venue="spot",
                strategy=strategy,
                regime=regime,
                symbol="unknown",  # Caller can override
                requested_size=base_position_size,
                final_size=final_size,
                min_limit=min_size,
                max_limit=max_size,
                cap_reason=cap_reason
            )
        
        return final_size


def get_position_size_with_conviction(portfolio_value: float, strategy: str, regime: str, 
                                        confidence: float = 0.5, volatility: float = None) -> float:
    """
    Get position size with conviction-based multipliers for high-probability trades.
    
    Args:
        portfolio_value: Current portfolio value
        strategy: Strategy name
        regime: Market regime
        confidence: Signal confidence (0.0 to 1.0) - higher = more conviction = larger size
        volatility: Optional volatility override
    
    Returns:
        Position size in USD (scaled by conviction)
    """
    # Get base Kelly size
    base_size = get_position_size_kelly(portfolio_value, strategy, regime, volatility)
    
    # Load conviction multipliers
    try:
        from config.trading_policy import TRADING_POLICY
        multipliers = TRADING_POLICY.get("CONVICTION_MULTIPLIERS", {"high": 1.5, "very_high": 2.0})
        thresholds = TRADING_POLICY.get("CONVICTION_THRESHOLDS", {"high": 0.65, "very_high": 0.75})
        max_size = TRADING_POLICY.get("MAX_POSITION_SIZE_USD", 1000)
    except ImportError:
        multipliers = {"high": 1.5, "very_high": 2.0}
        thresholds = {"high": 0.65, "very_high": 0.75}
        max_size = 1000
    
    # Apply conviction multiplier
    conviction_mult = 1.0
    if confidence >= thresholds.get("very_high", 0.75):
        conviction_mult = multipliers.get("very_high", 2.0)
        print(f"      🎯 Very High Conviction: {confidence:.0%} → {conviction_mult}x size boost")
    elif confidence >= thresholds.get("high", 0.65):
        conviction_mult = multipliers.get("high", 1.5)
        print(f"      🎯 High Conviction: {confidence:.0%} → {conviction_mult}x size boost")
    
    # Apply multiplier but respect max cap
    final_size = min(base_size * conviction_mult, max_size)
    
    if conviction_mult > 1.0:
        print(f"      💰 Conviction Size: ${base_size:.2f} × {conviction_mult}x = ${final_size:.2f}")
    
    return final_size


def _estimate_volatility_from_regime(regime):
    """
    Estimate volatility from regime name.
    
    Args:
        regime: Market regime name
    
    Returns:
        Estimated volatility (0.0 to 1.0)
    """
    regime_upper = regime.upper() if regime else "STABLE"
    
    # Map regime to typical volatility levels
    if "VOLATILE" in regime_upper or "CHOPPY" in regime_upper:
        return 0.35  # High volatility
    elif "TRENDING" in regime_upper:
        return 0.28  # Moderate-high volatility
    elif "STABLE" in regime_upper:
        return 0.18  # Low volatility
    else:
        return 0.25  # Default/neutral


def get_position_size(portfolio_value, strategy, regime, use_kelly=True):
    """
    Get position size with optional Kelly Criterion.
    
    Args:
        portfolio_value: Current portfolio value
        strategy: Strategy name
        regime: Market regime
        use_kelly: If True, use Kelly sizing; if False, use fixed 15%
    
    Returns:
        Position size in USD
    """
    if use_kelly:
        return get_position_size_kelly(portfolio_value, strategy, regime)
    else:
        # Fallback to fixed 15%
        return portfolio_value * 0.15


def get_futures_position_size_kelly(portfolio_value, strategy, regime, leverage, max_leverage=10, liquidation_buffer_pct=15.0, strategy_margin_budget=None, volatility=None):
    """
    Calculate optimal futures position size using leverage-aware Kelly Criterion with Phase 1 optimizations.
    
    Key Differences vs Spot Kelly:
    1. Apply Kelly fraction to margin capital allocation (not notional)
    2. Clamp by strategy margin budget from allocator (critical for risk composition)
    3. Derive max notional from: margin × min(leverage_cap, buffer-adjusted leverage)
    4. Use tighter Kelly cap for futures (0.15 vs 0.25 for spot)
    
    Phase 1 Enhancements:
    - Volatility-weighted Kelly: Reduces margin when volatility is high
    - Sharpe/Sortino throttle: Reduces margin when risk-adjusted performance is poor
    - Trading Policy Enforcement: Enforces $100-$500 margin collateral limits
    
    Args:
        portfolio_value: Current portfolio value
        strategy: Strategy name
        regime: Market regime
        leverage: Proposed leverage multiplier
        max_leverage: Maximum allowed leverage (global cap)
        liquidation_buffer_pct: Required buffer from liquidation (%)
        strategy_margin_budget: Max margin for this strategy from allocator (if None, computed internally)
        volatility: Current market volatility (optional, auto-detected if None)
    
    Returns:
        dict with {
            "margin_allocation": USD allocated as margin collateral (clamped by budget & policy),
            "max_notional": Maximum notional exposure allowed,
            "effective_leverage": Actual leverage after safety caps,
            "kelly_fraction": Raw Kelly fraction used,
            "requested_margin": Uncapped Kelly margin request,
            "budget_cap_hit": True if clamped by strategy budget
        }
    """
    import math
    
    # CRITICAL: Guard against NaN/invalid portfolio values
    # NaN portfolio values cause cascading corruption through position sizing
    if portfolio_value is None or (isinstance(portfolio_value, float) and (math.isnan(portfolio_value) or math.isinf(portfolio_value))):
        print(f"   ❌ [KELLY] BLOCKED: Invalid portfolio_value ({portfolio_value}) - refusing to size position")
        return {
            "margin_allocation": 0,
            "max_notional": 0,
            "effective_leverage": 0,
            "kelly_fraction": 0,
            "requested_margin": 0,
            "budget_cap_hit": False,
            "error": "invalid_portfolio_value"
        }
    
    if portfolio_value <= 0:
        print(f"   ❌ [KELLY] BLOCKED: portfolio_value is ${portfolio_value:.2f} - refusing to size position")
        return {
            "margin_allocation": 0,
            "max_notional": 0,
            "effective_leverage": 0,
            "kelly_fraction": 0,
            "requested_margin": 0,
            "budget_cap_hit": False,
            "error": "zero_portfolio_value"
        }
    # Import trading policy for position sizing limits with win-rate scaling
    try:
        from config.trading_policy import TRADING_POLICY, get_scaled_position_limits
        
        if TRADING_POLICY.get("ENABLE_WIN_RATE_SCALING", False):
            from src.data_registry import DataRegistry as DR
            closed_positions = DR.get_closed_positions(hours=24)
            
            if closed_positions:
                wins = [p for p in closed_positions if float(p.get("net_pnl", 0) or 0) > 0]
                current_wr = len(wins) / len(closed_positions) if closed_positions else 0.4
                recent_pnl = sum(float(p.get("net_pnl", 0) or 0) for p in closed_positions)
                pnl_positive = recent_pnl > 0
            else:
                current_wr = 0.40
                pnl_positive = True
            
            scaled_limits = get_scaled_position_limits(current_wr, pnl_positive)
            min_margin = scaled_limits["min_size"]
            max_margin = scaled_limits["max_size"]
            scaled_leverage = scaled_limits["leverage"]
            tier = scaled_limits["tier"]
            
            if scaled_leverage > leverage:
                leverage = scaled_leverage
            
            print(f"   🎯 Futures Win-Rate Scaling: WR={current_wr*100:.1f}% → Tier={tier} (${min_margin}-${max_margin}, {leverage}x)")
        else:
            min_margin = TRADING_POLICY["MIN_POSITION_SIZE_USD"]
            max_margin = TRADING_POLICY["MAX_POSITION_SIZE_USD"]
    except ImportError:
        min_margin = 300
        max_margin = 1200
    
    # Get historical performance for this strategy-regime
    win_rate, payoff_ratio = get_win_rate_and_payoff(strategy, regime)
    
    # Calculate Kelly fraction with tighter cap for futures (15% vs 25% spot)
    kelly_fraction = calculate_kelly_fraction(win_rate, payoff_ratio)
    kelly_fraction = min(kelly_fraction, 0.15)  # Stricter futures cap
    
    # Step 1: Kelly-derived margin request
    requested_margin = portfolio_value * kelly_fraction
    
    # Initialize optimization metadata
    vol_weight = 1.0
    throttle = 1.0
    metadata = {}
    
    # Phase 1 Optimizations: Apply to requested margin before budget cap
    if ENABLE_VOL_WEIGHTING or ENABLE_SHARPE_THROTTLE:
        # Auto-detect volatility from regime if not provided
        if volatility is None:
            volatility = _estimate_volatility_from_regime(regime)
        
        # Get available margin for optimization calculation
        if strategy_margin_budget is None:
            from src.capital_allocator import get_strategy_margin_budget
            strategy_margin_budget = get_strategy_margin_budget(strategy, regime)
        
        # Import with feature flags
        from src.optimization_enhancements import apply_optimization_enhancements
        
        optimized_margin, metadata = apply_optimization_enhancements(
            base_size=requested_margin,
            bankroll=strategy_margin_budget,
            p_win=win_rate,
            rr=payoff_ratio,
            current_vol=volatility,
            use_vol_weighting=ENABLE_VOL_WEIGHTING,  # Pass flag through
            use_sharpe_throttle=ENABLE_SHARPE_THROTTLE,  # Pass flag through
            kelly_scale=0.15,
            min_size=50.0,
            enforce_min=False  # CRITICAL: Don't force min for futures - respect allocator
        )
        
        requested_margin = optimized_margin
        
        # Show optimization impact
        throttle = metadata.get("throttle", {}).get("throttle", 1.0)
        vol_weight = metadata.get("kelly", {}).get("vol_weight", 1.0)
    else:
        # If not provided, get from allocator
        if strategy_margin_budget is None:
            from src.capital_allocator import get_strategy_margin_budget
            strategy_margin_budget = get_strategy_margin_budget(strategy, regime)
    
    # Step 2: Clamp by strategy margin budget from capital allocator
    margin_allocation = min(requested_margin, strategy_margin_budget)
    budget_cap_hit = (requested_margin > strategy_margin_budget)
    
    # Step 3: Apply trading policy limits ($100-$500 for margin)
    margin_before_policy = margin_allocation
    margin_allocation = max(min_margin, min(max_margin, margin_allocation))
    policy_cap_hit = (margin_before_policy != margin_allocation)
    
    # Step 4: Derive effective leverage with safety adjustments
    # Buffer adjustment: reduce leverage if liquidation buffer is tight
    buffer_factor = max(0.5, min(1.0, liquidation_buffer_pct / 15.0))
    adjusted_leverage = min(leverage, max_leverage) * buffer_factor
    
    # Step 5: Calculate max notional exposure
    max_notional = margin_allocation * adjusted_leverage
    
    print(f"   📊 Futures Kelly Sizing: WR={win_rate*100:.1f}% | P/L={payoff_ratio:.2f}")
    
    if ENABLE_VOL_WEIGHTING or ENABLE_SHARPE_THROTTLE:
        if ENABLE_VOL_WEIGHTING and volatility:
            print(f"      🔧 Vol Weight: {vol_weight:.2f}x (vol={volatility:.1%})")
        if ENABLE_SHARPE_THROTTLE and throttle != 1.0:
            sharpe = metadata.get("throttle", {}).get("sharpe", 0)
            print(f"      🔧 Sharpe Throttle: {throttle:.2f}x (Sharpe={sharpe:.2f})")
    
    print(f"      Requested: ${requested_margin:.2f} | Budget: ${strategy_margin_budget:.2f} {'⚠️ CAPPED' if budget_cap_hit else ''}")
    
    # Emit structured events for autonomous detection
    from src.policy_cap_events import emit_budget_cap, emit_kelly_policy_cap
    
    if budget_cap_hit:
        emit_budget_cap(
            venue="futures",
            strategy=strategy,
            regime=regime,
            symbol="unknown",  # Caller can override
            requested_margin=requested_margin,
            budget_limit=strategy_margin_budget,
            final_margin=margin_allocation
        )
    
    if policy_cap_hit:
        print(f"      🔒 Policy Limit: ${margin_before_policy:.2f} → ${margin_allocation:.2f} (enforcing \${min_margin}-\${max_margin} margin range)")
        cap_reason = "min_cap" if margin_allocation == min_margin else "max_cap"
        emit_kelly_policy_cap(
            venue="futures",
            strategy=strategy,
            regime=regime,
            symbol="unknown",  # Caller can override
            requested_size=margin_before_policy,
            final_size=margin_allocation,
            min_limit=min_margin,
            max_limit=max_margin,
            cap_reason=cap_reason
        )
    
    print(f"      Margin: {kelly_fraction*100:.1f}% (${margin_allocation:.2f}) | Leverage: {adjusted_leverage:.1f}x | Notional: ${max_notional:.2f}")
    
    # CRITICAL: Final NaN guard - prevent any NaN from escaping sizing function
    if not math.isfinite(margin_allocation) or not math.isfinite(max_notional):
        print(f"   🚨 [KELLY-NAN] BLOCKED: margin_allocation={margin_allocation}, max_notional={max_notional}")
        return {
            "margin_allocation": 0,
            "max_notional": 0,
            "effective_leverage": 0,
            "kelly_fraction": 0,
            "requested_margin": 0,
            "budget_cap_hit": False,
            "error": "nan_in_calculation"
        }
    
    return {
        "margin_allocation": margin_allocation,
        "max_notional": max_notional,
        "effective_leverage": adjusted_leverage,
        "kelly_fraction": kelly_fraction,
        "requested_margin": requested_margin,
        "budget_cap_hit": budget_cap_hit
    }


def get_position_size_with_venue(portfolio_value, strategy, regime, venue="spot", leverage=1, use_kelly=True, strategy_margin_budget=None):
    """
    Get position size with venue-aware Kelly Criterion (spot vs futures).
    
    Integrates with capital allocator to ensure Kelly requests respect regime-specific budgets.
    
    Args:
        portfolio_value: Current portfolio value
        strategy: Strategy name
        regime: Market regime
        venue: "spot" or "futures"
        leverage: Leverage multiplier (only used for futures)
        use_kelly: If True, use Kelly sizing; if False, use fixed sizing
        strategy_margin_budget: Override margin budget (if None, uses allocator)
    
    Returns:
        For spot: position size in USD
        For futures: dict with margin_allocation, max_notional, effective_leverage, budget_cap_hit
    """
    if venue == "spot":
        return get_position_size(portfolio_value, strategy, regime, use_kelly)
    elif venue == "futures":
        if not use_kelly:
            # Fixed margin allocation for futures without Kelly
            # Still respect allocator budget
            if strategy_margin_budget is None:
                from src.capital_allocator import get_strategy_margin_budget
                strategy_margin_budget = get_strategy_margin_budget(strategy, regime)
            
            fixed_request = portfolio_value * 0.10
            margin_alloc = min(fixed_request, strategy_margin_budget)
            
            return {
                "margin_allocation": margin_alloc,
                "max_notional": margin_alloc * min(leverage, 5),  # Conservative 5x cap
                "effective_leverage": min(leverage, 5),
                "kelly_fraction": 0.10,
                "requested_margin": fixed_request,
                "budget_cap_hit": (fixed_request > strategy_margin_budget)
            }
        else:
            return get_futures_position_size_kelly(
                portfolio_value, 
                strategy, 
                regime, 
                leverage, 
                strategy_margin_budget=strategy_margin_budget
            )
    else:
        raise ValueError(f"Unknown venue: {venue}. Must be 'spot' or 'futures'")
