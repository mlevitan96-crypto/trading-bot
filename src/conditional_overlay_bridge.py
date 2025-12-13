# === Execution Bridge Conditional Overlay Hook ===
# File: src/conditional_overlay_bridge.py
# Purpose: Apply per-slice thresholds based on live market conditions
# Enhanced: Multi-dimensional intelligence grid with daily learning integration

import json
import os
from datetime import datetime

from src.data_registry import DataRegistry as DR

DAILY_RULES_PATH = "feature_store/daily_learning_rules.json"
OPTIMAL_THRESHOLDS_PATH = "feature_store/optimal_thresholds.json"

SESSIONS = {
    "asia_night": (0, 4),
    "asia_morning": (4, 8),
    "europe_morning": (8, 12),
    "us_morning": (12, 16),
    "us_afternoon": (16, 20),
    "evening": (20, 24)
}


def _bin(x, edges):
    """Bin continuous value into discrete buckets."""
    for i, e in enumerate(edges):
        if x <= e:
            return i
    return len(edges)


def _load_json(path):
    """Load JSON file safely."""
    if not os.path.exists(path):
        return {}
    try:
        with open(path, 'r') as f:
            return json.load(f)
    except:
        return {}


def _get_current_session() -> str:
    """Get current trading session based on UTC hour."""
    hour = datetime.utcnow().hour
    for name, (start, end) in SESSIONS.items():
        if start <= hour < end:
            return name
    return "unknown"


def _classify_ofi(ofi: float) -> str:
    """Classify OFI into bucket."""
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


def _classify_ensemble(ens: float) -> str:
    """Classify ensemble into bucket."""
    if ens < -0.06:
        return "strong_bear"
    elif ens < -0.03:
        return "bear"
    elif ens < 0.03:
        return "neutral"
    elif ens < 0.06:
        return "bull"
    else:
        return "strong_bull"


def _check_pattern_match(ctx: dict, pattern_key: str) -> bool:
    """Check if current context matches a learned pattern."""
    parts = pattern_key.split("|")
    
    symbol = ctx.get('symbol', '')
    direction = ctx.get('side', ctx.get('direction', '')).upper()
    ofi = abs(ctx.get('ofi', 0))
    ensemble = ctx.get('ensemble', 0)
    session = _get_current_session()
    
    ofi_bucket = _classify_ofi(ofi)
    ens_bucket = _classify_ensemble(ensemble)
    
    for part in parts:
        part = part.strip()
        if "=" not in part:
            continue
        
        key, val = part.split("=", 1)
        key = key.strip()
        val = val.strip()
        
        if key == "sym" and val != symbol:
            return False
        elif key == "dir" and val != direction:
            return False
        elif key == "ofi" and val != ofi_bucket:
            return False
        elif key == "ens" and val != ens_bucket:
            return False
        elif key == "session" and val != session:
            return False
    
    return True


def _log_offensive_application(symbol, direction, old_threshold, new_threshold, reason):
    """Log when offensive rules are applied for tracking impact."""
    log_path = "logs/offensive_applications.jsonl"
    os.makedirs(os.path.dirname(log_path), exist_ok=True)
    
    record = {
        "timestamp": datetime.utcnow().isoformat(),
        "symbol": symbol,
        "direction": direction,
        "old_threshold": old_threshold,
        "new_threshold": new_threshold,
        "reason": reason,
    }
    
    try:
        with open(log_path, 'a') as f:
            f.write(json.dumps(record) + '\n')
    except:
        pass


def apply_multi_dimensional_rules(symbol, direction, ctx):
    """
    Apply rules from multi-dimensional daily learning.
    
    Checks if current trade matches any profitable or high-potential patterns
    discovered by the daily intelligence learner.
    
    Returns:
        Updated ctx with pattern-based adjustments
    """
    daily_rules = _load_json(DAILY_RULES_PATH)
    
    if not daily_rules:
        return ctx
    
    ctx['symbol'] = symbol
    ctx['side'] = direction
    
    profitable = daily_rules.get('profitable_patterns', {})
    for pattern_key, pattern_config in profitable.items():
        if _check_pattern_match(ctx, pattern_key):
            ctx['matched_pattern'] = pattern_key
            ctx['pattern_type'] = 'profitable'
            ctx['size_multiplier'] = pattern_config.get('size_multiplier', 1.0)
            
            ofi_reduction = pattern_config.get('ofi_threshold_reduction', 0)
            if ofi_reduction > 0:
                current_ofi = ctx.get('ofi_threshold', 0.50)
                ctx['ofi_threshold'] = max(0.10, current_ofi - ofi_reduction)
            
            _log_offensive_application(
                symbol, direction, 
                ctx.get('ofi_threshold', 0.5), ctx.get('ofi_threshold', 0.5),
                f"PROFITABLE PATTERN: {pattern_key}"
            )
            return ctx
    
    high_potential = daily_rules.get('high_potential_patterns', {})
    for pattern_key, pattern_config in high_potential.items():
        if _check_pattern_match(ctx, pattern_key):
            ctx['matched_pattern'] = pattern_key
            ctx['pattern_type'] = 'high_potential'
            ctx['size_multiplier'] = pattern_config.get('size_multiplier', 0.75)
            
            ofi_reduction = pattern_config.get('ofi_threshold_reduction', 0)
            if ofi_reduction > 0:
                current_ofi = ctx.get('ofi_threshold', 0.50)
                ctx['ofi_threshold'] = max(0.15, current_ofi - ofi_reduction)
            
            _log_offensive_application(
                symbol, direction,
                ctx.get('ofi_threshold', 0.5), ctx.get('ofi_threshold', 0.5),
                f"HIGH POTENTIAL PATTERN: {pattern_key}"
            )
            return ctx
    
    return ctx


def apply_offensive_thresholds(symbol, direction, ctx):
    """
    Apply offensive thresholds using MONEY-HUNTING logic.
    
    PAPER MODE = AGGRESSIVE EXPLORATION
    We're here to LEARN what makes money, not protect fake capital.
    
    Logic (in order of priority):
    1. PROFITABLE (P&L > 0): Full offensive - this pattern makes money!
    2. POSITIVE EV: Math says it should make money - go for it
    3. GOOD R/R (>1.0): Winners > losers, just need better WR - explore
    4. HIGH POTENTIAL: Missed opportunities > current losses - worth exploring
    5. ANY IMPROVEMENT: Better than baseline - worth more data
    6. DEFAULT: Apply offensive anyway - we need data to learn!
    
    Args:
        symbol: Trading symbol
        direction: Trade direction (LONG/SHORT)
        ctx: Decision context with current thresholds
    
    Returns:
        Updated ctx with offensive thresholds applied
    """
    offensive_rules = _load_json(DR.OFFENSIVE_RULES)
    learned_rules = _load_json(DR.LEARNED_RULES)
    offensive_adjustments = _load_json("feature_store/offensive_adjustments.json")
    
    dir_upper = direction.upper()
    combo = f"{symbol}_{dir_upper}"
    
    per_symbol = learned_rules.get("per_symbol", {}).get(symbol, {})
    pattern_stats = per_symbol.get(dir_upper, per_symbol)
    
    historical_pnl = pattern_stats.get("pnl", pattern_stats.get("total_pnl", 0))
    historical_wr = pattern_stats.get("win_rate", 0)
    historical_trades = pattern_stats.get("trades", pattern_stats.get("count", 0))
    avg_winner = pattern_stats.get("avg_winner", 0)
    avg_loser = pattern_stats.get("avg_loser", 0)
    
    if avg_winner and avg_loser and avg_loser != 0:
        risk_reward = abs(avg_winner / avg_loser)
    else:
        risk_reward = 1.0
    
    current_ofi = ctx.get("ofi_threshold", 0.50)
    
    offensive_ofi = None
    offensive_potential = 0
    
    if combo in offensive_adjustments.get("per_symbol_direction", {}):
        combo_data = offensive_adjustments["per_symbol_direction"][combo]
        offensive_ofi = combo_data.get("min_ofi")
        offensive_potential = combo_data.get("potential", 0)
    elif dir_upper in offensive_adjustments.get("per_direction", {}):
        dir_data = offensive_adjustments["per_direction"][dir_upper]
        offensive_ofi = dir_data.get("min_ofi")
        offensive_potential = dir_data.get("potential", 0)
    elif "global" in offensive_adjustments:
        offensive_ofi = offensive_adjustments["global"].get("new_min_ofi")
        offensive_potential = offensive_adjustments["global"].get("potential_upside", 0)
    
    if offensive_ofi is None:
        offensive_ofi = 0.15
    
    expected_value = (historical_wr / 100) * avg_winner - ((100 - historical_wr) / 100) * abs(avg_loser) if avg_winner and avg_loser else 0
    
    reason = ""
    blend_factor = 1.0
    
    if historical_pnl > 0:
        reason = f"💰 PROFITABLE: P&L=${historical_pnl:.2f} - GO AGGRESSIVE"
        blend_factor = 1.0
    
    elif expected_value > 0:
        reason = f"📈 POSITIVE EV: ${expected_value:.2f}/trade - MATH SAYS YES"
        blend_factor = 1.0
    
    elif risk_reward >= 1.0 and historical_wr > 0:
        reason = f"⚖️ GOOD R/R: {risk_reward:.1f}x (winners > losers) - EXPLORE MORE"
        blend_factor = 0.9
    
    elif offensive_potential > 0:
        reason = f"🎯 HIGH POTENTIAL: ${offensive_potential:.0f} missed opportunities - WORTH EXPLORING"
        blend_factor = 0.8
    
    elif historical_wr > 0:
        baseline_wr = learned_rules.get("performance_baseline", {}).get("win_rate", 18.0)
        if historical_wr >= baseline_wr:
            improvement = ((historical_wr / max(0.01, baseline_wr)) - 1) * 100
            reason = f"📊 ABOVE BASELINE: WR {historical_wr:.1f}% vs {baseline_wr:.1f}% - GATHER DATA"
            blend_factor = 0.7
        else:
            reason = f"🔬 LEARNING MODE: WR {historical_wr:.1f}% - PAPER MODE = EXPLORE"
            blend_factor = 0.5
    
    else:
        reason = f"🚀 NO DATA YET: Paper mode = explore everything - GO!"
        blend_factor = 0.6
    
    blended_ofi = current_ofi * (1 - blend_factor) + offensive_ofi * blend_factor
    new_ofi = min(current_ofi, blended_ofi)
    
    ctx["ofi_threshold"] = round(new_ofi, 3)
    ctx["offensive_applied"] = True
    ctx["offensive_reason"] = reason
    ctx["offensive_blend"] = blend_factor
    ctx["offensive_potential"] = offensive_potential
    ctx["risk_reward"] = risk_reward
    ctx["expected_value"] = expected_value
    
    if new_ofi < current_ofi:
        _log_offensive_application(
            symbol, dir_upper, current_ofi, new_ofi,
            f"{reason} | Blend={blend_factor:.0%}"
        )
    
    return ctx


def apply_conditional_overlays(symbol, direction, vol, liq, ctx, runtime):
    """
    Apply conditional threshold overlays based on current market conditions.
    
    Args:
        symbol: Trading symbol (e.g., 'BTCUSDT')
        direction: Trade direction ('long' or 'short')
        vol: Current volatility
        liq: Current liquidity
        ctx: Decision context dict with thresholds
        runtime: Runtime config with conditional_overlays
    
    Returns:
        Updated ctx with per-slice thresholds applied
    """
    overlays = runtime.get("conditional_overlays", []) or []
    
    vol_bin = _bin(vol, [10, 20, 35, 60])
    liq_bin = _bin(liq, [1e5, 5e5, 1e6])
    
    for overlay in overlays:
        if (overlay.get("symbol") == symbol and 
            overlay.get("direction") == direction and 
            overlay.get("vol_bin") == vol_bin and 
            overlay.get("liq_bin") == liq_bin):
            
            thresholds = overlay.get("thresholds", {}) or {}
            
            ctx["ofi_threshold"] = thresholds.get("ofi", ctx.get("ofi_threshold", 0.50))
            ctx["ensemble_threshold"] = thresholds.get("ensemble", ctx.get("ensemble_threshold", 0.05))
            ctx["roi_threshold"] = thresholds.get("roi", ctx.get("roi_threshold", 0.003))
            
            break
    
    ctx = apply_offensive_thresholds(symbol, direction, ctx)
    
    return ctx


def get_offensive_status() -> dict:
    """Get current status of offensive rule application."""
    offensive_adjustments = _load_json("feature_store/offensive_adjustments.json")
    learned_rules = _load_json(DR.LEARNED_RULES)
    
    applications = []
    log_path = "logs/offensive_applications.jsonl"
    if os.path.exists(log_path):
        try:
            with open(log_path, 'r') as f:
                lines = f.readlines()[-20:]
                for line in lines:
                    try:
                        applications.append(json.loads(line.strip()))
                    except:
                        continue
        except:
            pass
    
    return {
        "offensive_rules_loaded": bool(offensive_adjustments),
        "global_adjustment": offensive_adjustments.get("global", {}),
        "per_direction": offensive_adjustments.get("per_direction", {}),
        "symbols_with_adjustments": list(offensive_adjustments.get("per_symbol_direction", {}).keys()),
        "recent_applications": applications[-10:],
    }
