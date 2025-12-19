#!/usr/bin/env python3
"""
SIZING MULTIPLIER LEARNERS
===========================
Learns optimal sizing multipliers for all gates that were converted from binary blocking.

Learners:
1. Intelligence Gate Sizing - Learn multipliers for intel conflicts
2. Streak Filter Sizing - Learn multipliers for win/loss streaks
3. Regime Filter Sizing - Learn multipliers for regime mismatches
4. Fee Gate Sizing - Learn multipliers for fee drag levels
5. ROI Threshold Sizing - Learn multipliers for ROI threshold violations

Each learner:
- Analyzes last 7 days of trade data from logs/positions_futures.json
- Correlates gate state with P&L outcomes
- Applies EWMA smoothing to prevent oscillation
- Saves learned parameters to feature_store/*.json
- Returns summary for nightly digest

Usage:
    from src.sizing_multiplier_learners import run_all_sizing_learners
    result = run_all_sizing_learners()
"""

import json
import os
import time
from datetime import datetime, timedelta
from typing import Dict, List, Tuple, Optional, Any
from collections import defaultdict
from statistics import mean, median

try:
    from src.data_registry import DataRegistry as DR
except ImportError:
    import sys
    sys.path.insert(0, '/home/runner/workspace')
    from src.data_registry import DataRegistry as DR

# Output paths for learned multipliers
INTELLIGENCE_SIZING_PATH = "feature_store/intelligence_gate_sizing.json"
STREAK_SIZING_PATH = "feature_store/streak_sizing_weights.json"
REGIME_SIZING_PATH = "feature_store/regime_sizing_weights.json"
FEE_GATE_SIZING_PATH = "feature_store/fee_gate_sizing_multipliers.json"
ROI_SIZING_PATH = "feature_store/roi_threshold_sizing.json"

EWMA_ALPHA = 0.3  # Exponential weighted moving average smoothing
DEFAULT_LOOKBACK_DAYS = 7
MIN_TRADES_FOR_LEARNING = 5  # Minimum trades per category to learn from

# Default multipliers (fallbacks if no data)
DEFAULT_INTEL_MULTIPLIERS = {
    "strong_conflict": 0.4,      # intel confidence >= 0.6
    "moderate_conflict": 0.6,    # intel confidence 0.4-0.6
    "weak_conflict": 0.8,        # intel confidence < 0.4
    "neutral": 0.85,             # intel direction NEUTRAL
    "aligned": 1.0,              # intel aligns with signal (base)
    "aligned_boost": 1.3,        # intel aligns with high confidence (max)
}

DEFAULT_STREAK_MULTIPLIERS = {
    "3_plus_wins": 1.5,          # 3+ consecutive wins
    "2_wins": 1.3,
    "1_win": 1.1,
    "neutral": 1.0,
    "1_loss": 0.85,
    "2_losses": 0.7,
    "3_plus_losses": 0.5,
}

DEFAULT_REGIME_MULTIPLIERS = {
    "mismatch": 0.6,             # Regime doesn't match strategy
    "match": 1.0,                # Regime matches strategy
}

DEFAULT_FEE_SIZING_MULTIPLIERS = {
    "negative_ev": 0.3,          # Expected move < breakeven
    "insufficient_buffer": 0.65, # Expected move < min_required (interpolated 0.5-0.8)
    "good_edge": 1.0,            # Expected move >= min_required
}

DEFAULT_ROI_SIZING_MULTIPLIERS = {
    "below_threshold": 0.6,      # ROI < threshold (interpolated 0.4-0.8)
    "at_threshold": 0.8,
    "above_threshold": 1.0,
}


def _now() -> str:
    """Return current UTC timestamp in ISO format."""
    return datetime.utcnow().isoformat() + "Z"


def _log(msg: str):
    """Log with timestamp prefix."""
    ts = datetime.utcnow().isoformat() + "Z"
    print(f"[{ts}] [SIZING-LEARNER] {msg}")


def _read_json(path: str, default=None) -> Dict:
    """Read JSON file safely."""
    try:
        if os.path.exists(path):
            with open(path, 'r') as f:
                return json.load(f)
    except Exception as e:
        _log(f"Error reading {path}: {e}")
    return default if default is not None else {}


def _write_json(path: str, data: Dict) -> bool:
    """Write JSON file atomically."""
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp_path = path + ".tmp"
        with open(tmp_path, 'w') as f:
            json.dump(data, f, indent=2, default=str)
        os.replace(tmp_path, path)
        return True
    except Exception as e:
        _log(f"Error writing {path}: {e}")
        return False


def _ewma_update(current: float, new: float, alpha: float = EWMA_ALPHA) -> float:
    """Exponential weighted moving average update."""
    return alpha * new + (1 - alpha) * current


def _load_recent_trades(lookback_days: int = DEFAULT_LOOKBACK_DAYS) -> List[Dict]:
    """Load recent closed trades from positions_futures.json."""
    try:
        positions_data = DR.read_json(DR.POSITIONS_FUTURES)
        closed = positions_data.get("closed_positions", [])
        
        cutoff = datetime.utcnow() - timedelta(days=lookback_days)
        
        recent = []
        for trade in closed:
            closed_at = trade.get("closed_at", "")
            if closed_at:
                try:
                    # Parse timestamp
                    if closed_at.endswith("Z"):
                        closed_at = closed_at[:-1]
                    trade_time = datetime.fromisoformat(closed_at)
                    if trade_time >= cutoff:
                        recent.append(trade)
                except:
                    pass
        
        return recent
    except Exception as e:
        _log(f"Error loading trades: {e}")
        return []


def _calculate_pnl_roi(pnl: float, margin: float) -> float:
    """Calculate ROI from P&L and margin."""
    if margin and margin > 0:
        return (pnl / margin) * 100
    return 0.0


def _extract_intel_state(trade: Dict) -> Optional[str]:
    """
    Extract intelligence gate state from trade metadata.
    
    Returns:
        "aligned", "strong_conflict", "moderate_conflict", "weak_conflict", "neutral", or None
    """
    # Check multiple possible locations for gate attribution
    gate_attr = trade.get("gate_attribution", {})
    signal_ctx = trade.get("signal_context", {})
    metadata = trade.get("metadata", {})
    
    # Check intel_reason directly in trade dict (from position_manager)
    intel_reason = (trade.get("intel_reason") or 
                   gate_attr.get("intel_reason") or 
                   signal_ctx.get("intel_reason") or
                   metadata.get("intel_reason"))
    
    if intel_reason:
        intel_reason_str = str(intel_reason).lower()
        if "confirmed" in intel_reason_str or "align" in intel_reason_str:
            return "aligned"
        elif "strong" in intel_reason_str:
            return "strong_conflict"
        elif "moderate" in intel_reason_str:
            return "moderate_conflict"
        elif "weak" in intel_reason_str:
            return "weak_conflict"
        elif "neutral" in intel_reason_str:
            return "neutral"
    
    # Infer from intel confidence if available
    intel_conf = trade.get("intel_confidence") or gate_attr.get("intel_confidence")
    intel_dir = trade.get("intel_direction")
    signal_dir = trade.get("direction", "")
    
    if intel_conf is not None and intel_dir:
        # Try to infer conflict state from direction mismatch
        if str(intel_dir).upper() != str(signal_dir).upper():
            if intel_conf >= 0.6:
                return "strong_conflict"
            elif intel_conf >= 0.4:
                return "moderate_conflict"
            else:
                return "weak_conflict"
        else:
            return "aligned"
    
    return None


def _extract_streak_state(trade: Dict) -> Optional[str]:
    """
    Extract streak filter state from trade metadata.
    
    Returns:
        "3_plus_wins", "2_wins", "1_win", "neutral", "1_loss", "2_losses", "3_plus_losses", or None
    """
    gate_attr = trade.get("gate_attribution", {})
    signal_ctx = trade.get("signal_context", {})
    
    # Check streak_reason directly in trade dict (from position_manager)
    streak_reason = (trade.get("streak_reason") or 
                    gate_attr.get("streak_reason") or 
                    signal_ctx.get("streak_reason", ""))
    
    if streak_reason:
        streak_str = str(streak_reason).lower()
        if "boost" in streak_str or "wins" in streak_str:
            if "3" in streak_str or "plus" in streak_str or "_3_" in streak_str:
                return "3_plus_wins"
            elif "_2_" in streak_str or "2_wins" in streak_str:
                return "2_wins"
            elif "_1_" in streak_str or "1_win" in streak_str:
                return "1_win"
        elif "losses" in streak_str or "reduce" in streak_str:
            if "3" in streak_str or "plus" in streak_str or "_3_" in streak_str:
                return "3_plus_losses"
            elif "_2_" in streak_str or "2_losses" in streak_str:
                return "2_losses"
            elif "_1_" in streak_str or "1_loss" in streak_str:
                return "1_loss"
        elif "neutral" in streak_str:
            return "neutral"
    
    # Try to infer from streak multipliers
    streak_mult = gate_attr.get("streak_mult") or signal_ctx.get("streak_mult")
    if streak_mult:
        if streak_mult >= 1.3:
            return "3_plus_wins"  # High boost likely means 3+ wins
        elif streak_mult >= 1.1:
            return "1_win"
        elif streak_mult <= 0.6:
            return "3_plus_losses"  # Significant reduction likely means 3+ losses
        elif streak_mult <= 0.75:
            return "2_losses"
        elif streak_mult <= 0.9:
            return "1_loss"
    
    return None


def _extract_regime_state(trade: Dict) -> Optional[str]:
    """Extract regime filter state from trade metadata."""
    gate_attr = trade.get("gate_attribution", {})
    signal_ctx = trade.get("signal_context", {})
    
    # Check regime_reason directly in trade dict (from position_manager)
    regime_reason = (trade.get("regime_reason") or 
                    gate_attr.get("regime_reason") or 
                    signal_ctx.get("regime_reason", ""))
    
    if regime_reason:
        regime_str = str(regime_reason).lower()
        if "mismatch" in regime_str:
            return "mismatch"
        elif "match" in regime_str:
            return "match"
    
    # Try to infer from regime multiplier
    regime_mult = gate_attr.get("regime_mult") or signal_ctx.get("regime_mult")
    if regime_mult and regime_mult < 1.0:
        return "mismatch"  # Reduced sizing likely means mismatch
    
    return None


def _extract_fee_state(trade: Dict) -> Optional[str]:
    """Extract fee gate state from trade metadata."""
    gate_attr = trade.get("gate_attribution", {})
    signal_ctx = trade.get("signal_context", {})
    
    # Check fee_reason directly in trade dict
    fee_reason = (trade.get("fee_reason") or 
                 gate_attr.get("fee_reason") or 
                 signal_ctx.get("fee_gate_reason", ""))
    
    if fee_reason:
        fee_str = str(fee_reason).lower()
        if "negative_ev" in fee_str:
            return "negative_ev"
        elif "insufficient_buffer" in fee_str or "buffer" in fee_str:
            return "insufficient_buffer"
        elif "good_edge" in fee_str or "strong_edge" in fee_str or "acceptable_edge" in fee_str:
            return "good_edge"
    
    # Try to infer from fee multiplier
    fee_mult = gate_attr.get("fee_mult") or signal_ctx.get("fee_mult")
    if fee_mult:
        if fee_mult <= 0.4:
            return "negative_ev"
        elif fee_mult < 0.9:
            return "insufficient_buffer"
        else:
            return "good_edge"
    
    return None


def _extract_roi_state(trade: Dict) -> Optional[str]:
    """Extract ROI threshold state from trade metadata."""
    gate_attr = trade.get("gate_attribution", {})
    signal_ctx = trade.get("signal_context", {})
    
    # Check roi_reason directly in trade dict
    roi_reason = (trade.get("roi_reason") or 
                 gate_attr.get("roi_reason") or 
                 signal_ctx.get("roi_reason", ""))
    
    if roi_reason:
        roi_str = str(roi_reason).lower()
        if "below_threshold" in roi_str or "roi_adjusted" in roi_str or "reduced_to" in roi_str:
            return "below_threshold"
        elif "at_threshold" in roi_str:
            return "at_threshold"
        elif "above_threshold" in roi_str or "partial_confirmation" in roi_str:
            return "above_threshold"
    
    # Try to infer from ROI multiplier
    roi_mult = gate_attr.get("roi_mult") or signal_ctx.get("roi_mult")
    if roi_mult:
        if roi_mult < 0.7:
            return "below_threshold"
        elif roi_mult < 0.9:
            return "at_threshold"
        else:
            return "above_threshold"
    
    return None


def learn_intelligence_gate_sizing() -> Dict[str, Any]:
    """
    Learn optimal sizing multipliers for intelligence gate conflicts.
    
    Analyzes trades with intel alignment/conflict states and correlates with P&L.
    """
    _log("Starting intelligence gate sizing multiplier learning...")
    
    result = {
        "status": "no_data",
        "trades_analyzed": 0,
        "multipliers_updated": 0,
        "multipliers": {},
        "category_stats": {},
        "timestamp": _now(),
    }
    
    trades = _load_recent_trades()
    if not trades:
        _log("No recent trades for intel gate sizing learning")
        return result
    
    current_multipliers = _read_json(INTELLIGENCE_SIZING_PATH, {
        "multipliers": DEFAULT_INTEL_MULTIPLIERS.copy(),
    }).get("multipliers", DEFAULT_INTEL_MULTIPLIERS.copy())
    
    # Group trades by intel state
    state_trades: Dict[str, List[Dict]] = defaultdict(list)
    
    for trade in trades:
        intel_state = _extract_intel_state(trade)
        if intel_state:
            pnl = trade.get("pnl") or trade.get("net_pnl", 0)
            margin = trade.get("margin_collateral", 0) or trade.get("size_usd", 0)
            roi_pct = _calculate_pnl_roi(pnl, margin)
            
            state_trades[intel_state].append({
                "pnl": pnl,
                "margin": margin,
                "roi_pct": roi_pct,
                "symbol": trade.get("symbol", "UNKNOWN"),
            })
    
    result["trades_analyzed"] = len(trades)
    
    new_multipliers = dict(current_multipliers)
    category_stats = {}
    updates_made = 0
    
    for state, trades_in_state in state_trades.items():
        if len(trades_in_state) < MIN_TRADES_FOR_LEARNING:
            category_stats[state] = {
                "count": len(trades_in_state),
                "status": "insufficient_data",
            }
            continue
        
        # Calculate performance metrics
        total_pnl = sum(t["pnl"] for t in trades_in_state)
        avg_pnl = total_pnl / len(trades_in_state)
        avg_roi = sum(t["roi_pct"] for t in trades_in_state) / len(trades_in_state)
        win_rate = sum(1 for t in trades_in_state if t["pnl"] > 0) / len(trades_in_state)
        
        category_stats[state] = {
            "count": len(trades_in_state),
            "total_pnl": round(total_pnl, 4),
            "avg_pnl": round(avg_pnl, 4),
            "avg_roi": round(avg_roi, 4),
            "win_rate": round(win_rate, 4),
        }
        
        current_mult = current_multipliers.get(state, 1.0)
        
        # Calculate optimal multiplier based on performance
        # Positive EV and good win rate → increase multiplier
        # Negative EV and poor win rate → decrease multiplier
        # Target: multiplier should correlate with expected ROI
        
        if avg_roi > 0 and win_rate > 0.5:
            # Positive performance → can increase sizing
            # Increase multiplier by 5-15% based on ROI
            adjustment = min(0.15, max(0.05, avg_roi / 10))
            optimal_mult = current_mult * (1 + adjustment)
        elif avg_roi < 0 or win_rate < 0.4:
            # Negative performance → should decrease sizing
            # Decrease multiplier by 5-15% based on negative ROI
            adjustment = min(0.15, max(0.05, abs(avg_roi) / 10))
            optimal_mult = current_mult * (1 - adjustment)
        else:
            # Neutral performance → keep current
            optimal_mult = current_mult
        
        # Apply EWMA smoothing
        smoothed_mult = _ewma_update(current_mult, optimal_mult)
        
        # Constrain to reasonable bounds (0.3x to 1.5x)
        smoothed_mult = max(0.3, min(1.5, smoothed_mult))
        
        if abs(smoothed_mult - current_mult) > 0.02:  # Only update if change > 2%
            new_multipliers[state] = round(smoothed_mult, 3)
            updates_made += 1
            category_stats[state]["old_mult"] = current_mult
            category_stats[state]["new_mult"] = smoothed_mult
            category_stats[state]["adjustment_pct"] = round(((smoothed_mult - current_mult) / current_mult) * 100, 2)
    
    result["multipliers"] = new_multipliers
    result["category_stats"] = category_stats
    result["multipliers_updated"] = updates_made
    result["status"] = "updated" if updates_made > 0 else "no_changes"
    
    # Save learned multipliers
    _write_json(INTELLIGENCE_SIZING_PATH, {
        "version": 1,
        "updated_at": _now(),
        "multipliers": new_multipliers,
        "stats": category_stats,
        "trades_analyzed": result["trades_analyzed"],
    })
    
    if updates_made > 0:
        _log(f"Updated {updates_made} intel gate multipliers")
    
    return result


def learn_streak_sizing() -> Dict[str, Any]:
    """Learn optimal sizing multipliers for streak filter."""
    _log("Starting streak filter sizing multiplier learning...")
    
    result = {
        "status": "no_data",
        "trades_analyzed": 0,
        "multipliers_updated": 0,
        "multipliers": {},
        "category_stats": {},
        "timestamp": _now(),
    }
    
    trades = _load_recent_trades()
    if not trades:
        _log("No recent trades for streak sizing learning")
        return result
    
    current_multipliers = _read_json(STREAK_SIZING_PATH, {
        "multipliers": DEFAULT_STREAK_MULTIPLIERS.copy(),
    }).get("multipliers", DEFAULT_STREAK_MULTIPLIERS.copy())
    
    # Group trades by streak state
    state_trades: Dict[str, List[Dict]] = defaultdict(list)
    
    for trade in trades:
        streak_state = _extract_streak_state(trade)
        if streak_state:
            pnl = trade.get("pnl") or trade.get("net_pnl", 0)
            margin = trade.get("margin_collateral", 0) or trade.get("size_usd", 0)
            roi_pct = _calculate_pnl_roi(pnl, margin)
            
            state_trades[streak_state].append({
                "pnl": pnl,
                "margin": margin,
                "roi_pct": roi_pct,
                "symbol": trade.get("symbol", "UNKNOWN"),
            })
    
    result["trades_analyzed"] = len(trades)
    
    new_multipliers = dict(current_multipliers)
    category_stats = {}
    updates_made = 0
    
    for state, trades_in_state in state_trades.items():
        if len(trades_in_state) < MIN_TRADES_FOR_LEARNING:
            category_stats[state] = {
                "count": len(trades_in_state),
                "status": "insufficient_data",
            }
            continue
        
        total_pnl = sum(t["pnl"] for t in trades_in_state)
        avg_pnl = total_pnl / len(trades_in_state)
        avg_roi = sum(t["roi_pct"] for t in trades_in_state) / len(trades_in_state)
        win_rate = sum(1 for t in trades_in_state if t["pnl"] > 0) / len(trades_in_state)
        
        category_stats[state] = {
            "count": len(trades_in_state),
            "total_pnl": round(total_pnl, 4),
            "avg_pnl": round(avg_pnl, 4),
            "avg_roi": round(avg_roi, 4),
            "win_rate": round(win_rate, 4),
        }
        
        current_mult = current_multipliers.get(state, 1.0)
        
        # Calculate optimal multiplier
        if avg_roi > 0 and win_rate > 0.5:
            adjustment = min(0.15, max(0.05, avg_roi / 10))
            optimal_mult = current_mult * (1 + adjustment)
        elif avg_roi < 0 or win_rate < 0.4:
            adjustment = min(0.15, max(0.05, abs(avg_roi) / 10))
            optimal_mult = current_mult * (1 - adjustment)
        else:
            optimal_mult = current_mult
        
        smoothed_mult = _ewma_update(current_mult, optimal_mult)
        smoothed_mult = max(0.3, min(1.8, smoothed_mult))  # Streak can boost up to 1.8x
        
        if abs(smoothed_mult - current_mult) > 0.02:
            new_multipliers[state] = round(smoothed_mult, 3)
            updates_made += 1
            category_stats[state]["old_mult"] = current_mult
            category_stats[state]["new_mult"] = smoothed_mult
            category_stats[state]["adjustment_pct"] = round(((smoothed_mult - current_mult) / current_mult) * 100, 2)
    
    result["multipliers"] = new_multipliers
    result["category_stats"] = category_stats
    result["multipliers_updated"] = updates_made
    result["status"] = "updated" if updates_made > 0 else "no_changes"
    
    _write_json(STREAK_SIZING_PATH, {
        "version": 1,
        "updated_at": _now(),
        "multipliers": new_multipliers,
        "stats": category_stats,
        "trades_analyzed": result["trades_analyzed"],
    })
    
    if updates_made > 0:
        _log(f"Updated {updates_made} streak multipliers")
    
    return result


def learn_regime_sizing() -> Dict[str, Any]:
    """Learn optimal sizing multiplier for regime filter mismatches."""
    _log("Starting regime filter sizing multiplier learning...")
    
    result = {
        "status": "no_data",
        "trades_analyzed": 0,
        "multipliers_updated": 0,
        "multipliers": {},
        "category_stats": {},
        "timestamp": _now(),
    }
    
    trades = _load_recent_trades()
    if not trades:
        _log("No recent trades for regime sizing learning")
        return result
    
    current_multipliers = _read_json(REGIME_SIZING_PATH, {
        "multipliers": DEFAULT_REGIME_MULTIPLIERS.copy(),
    }).get("multipliers", DEFAULT_REGIME_MULTIPLIERS.copy())
    
    state_trades: Dict[str, List[Dict]] = defaultdict(list)
    
    for trade in trades:
        regime_state = _extract_regime_state(trade)
        if regime_state:
            pnl = trade.get("pnl") or trade.get("net_pnl", 0)
            margin = trade.get("margin_collateral", 0) or trade.get("size_usd", 0)
            roi_pct = _calculate_pnl_roi(pnl, margin)
            
            state_trades[regime_state].append({
                "pnl": pnl,
                "margin": margin,
                "roi_pct": roi_pct,
                "symbol": trade.get("symbol", "UNKNOWN"),
            })
    
    result["trades_analyzed"] = len(trades)
    
    new_multipliers = dict(current_multipliers)
    category_stats = {}
    updates_made = 0
    
    # Focus on mismatch multiplier (match should stay at 1.0)
    if "mismatch" in state_trades and len(state_trades["mismatch"]) >= MIN_TRADES_FOR_LEARNING:
        trades_mismatch = state_trades["mismatch"]
        
        total_pnl = sum(t["pnl"] for t in trades_mismatch)
        avg_pnl = total_pnl / len(trades_mismatch)
        avg_roi = sum(t["roi_pct"] for t in trades_mismatch) / len(trades_mismatch)
        win_rate = sum(1 for t in trades_mismatch if t["pnl"] > 0) / len(trades_mismatch)
        
        category_stats["mismatch"] = {
            "count": len(trades_mismatch),
            "total_pnl": round(total_pnl, 4),
            "avg_pnl": round(avg_pnl, 4),
            "avg_roi": round(avg_roi, 4),
            "win_rate": round(win_rate, 4),
        }
        
        current_mult = current_multipliers.get("mismatch", 0.6)
        
        # If mismatches are actually profitable, increase multiplier (less reduction)
        # If mismatches are losing money, decrease multiplier (more reduction)
        if avg_roi > 0 and win_rate > 0.45:
            # Mismatches aren't that bad → increase from 0.6x toward 0.8x
            adjustment = min(0.2, max(0.05, avg_roi / 15))
            optimal_mult = current_mult + adjustment
        elif avg_roi < -1.0 or win_rate < 0.35:
            # Mismatches are bad → decrease from 0.6x toward 0.3x
            adjustment = min(0.3, max(0.05, abs(avg_roi) / 15))
            optimal_mult = current_mult - adjustment
        else:
            optimal_mult = current_mult
        
        smoothed_mult = _ewma_update(current_mult, optimal_mult)
        smoothed_mult = max(0.3, min(0.9, smoothed_mult))  # Mismatch should reduce sizing
        
        if abs(smoothed_mult - current_mult) > 0.02:
            new_multipliers["mismatch"] = round(smoothed_mult, 3)
            updates_made += 1
            category_stats["mismatch"]["old_mult"] = current_mult
            category_stats["mismatch"]["new_mult"] = smoothed_mult
            category_stats["mismatch"]["adjustment_pct"] = round(((smoothed_mult - current_mult) / current_mult) * 100, 2)
    
    # Match should always be 1.0
    new_multipliers["match"] = 1.0
    
    result["multipliers"] = new_multipliers
    result["category_stats"] = category_stats
    result["multipliers_updated"] = updates_made
    result["status"] = "updated" if updates_made > 0 else "no_changes"
    
    _write_json(REGIME_SIZING_PATH, {
        "version": 1,
        "updated_at": _now(),
        "multipliers": new_multipliers,
        "stats": category_stats,
        "trades_analyzed": result["trades_analyzed"],
    })
    
    if updates_made > 0:
        _log(f"Updated regime mismatch multiplier: {new_multipliers.get('mismatch', 0.6)}")
    
    return result


def learn_fee_gate_sizing() -> Dict[str, Any]:
    """Learn optimal sizing multipliers for fee gate fee drag levels."""
    _log("Starting fee gate sizing multiplier learning...")
    
    result = {
        "status": "no_data",
        "trades_analyzed": 0,
        "multipliers_updated": 0,
        "multipliers": {},
        "category_stats": {},
        "timestamp": _now(),
    }
    
    trades = _load_recent_trades()
    if not trades:
        _log("No recent trades for fee gate sizing learning")
        return result
    
    current_multipliers = _read_json(FEE_GATE_SIZING_PATH, {
        "multipliers": DEFAULT_FEE_SIZING_MULTIPLIERS.copy(),
    }).get("multipliers", DEFAULT_FEE_SIZING_MULTIPLIERS.copy())
    
    state_trades: Dict[str, List[Dict]] = defaultdict(list)
    
    for trade in trades:
        fee_state = _extract_fee_state(trade)
        if fee_state:
            pnl = trade.get("pnl") or trade.get("net_pnl", 0)
            margin = trade.get("margin_collateral", 0) or trade.get("size_usd", 0)
            roi_pct = _calculate_pnl_roi(pnl, margin)
            
            state_trades[fee_state].append({
                "pnl": pnl,
                "margin": margin,
                "roi_pct": roi_pct,
                "symbol": trade.get("symbol", "UNKNOWN"),
            })
    
    result["trades_analyzed"] = len(trades)
    
    new_multipliers = dict(current_multipliers)
    category_stats = {}
    updates_made = 0
    
    for state, trades_in_state in state_trades.items():
        if len(trades_in_state) < MIN_TRADES_FOR_LEARNING:
            category_stats[state] = {
                "count": len(trades_in_state),
                "status": "insufficient_data",
            }
            continue
        
        total_pnl = sum(t["pnl"] for t in trades_in_state)
        avg_pnl = total_pnl / len(trades_in_state)
        avg_roi = sum(t["roi_pct"] for t in trades_in_state) / len(trades_in_state)
        win_rate = sum(1 for t in trades_in_state if t["pnl"] > 0) / len(trades_in_state)
        
        category_stats[state] = {
            "count": len(trades_in_state),
            "total_pnl": round(total_pnl, 4),
            "avg_pnl": round(avg_pnl, 4),
            "avg_roi": round(avg_roi, 4),
            "win_rate": round(win_rate, 4),
        }
        
        current_mult = current_multipliers.get(state, 1.0)
        
        # Calculate optimal multiplier
        if avg_roi > 0 and win_rate > 0.5:
            adjustment = min(0.15, max(0.05, avg_roi / 10))
            optimal_mult = current_mult * (1 + adjustment)
        elif avg_roi < 0 or win_rate < 0.4:
            adjustment = min(0.15, max(0.05, abs(avg_roi) / 10))
            optimal_mult = current_mult * (1 - adjustment)
        else:
            optimal_mult = current_mult
        
        smoothed_mult = _ewma_update(current_mult, optimal_mult)
        
        # Constrain based on state
        if state == "negative_ev":
            smoothed_mult = max(0.2, min(0.5, smoothed_mult))
        elif state == "insufficient_buffer":
            smoothed_mult = max(0.4, min(0.9, smoothed_mult))
        else:  # good_edge
            smoothed_mult = max(0.9, min(1.1, smoothed_mult))
        
        if abs(smoothed_mult - current_mult) > 0.02:
            new_multipliers[state] = round(smoothed_mult, 3)
            updates_made += 1
            category_stats[state]["old_mult"] = current_mult
            category_stats[state]["new_mult"] = smoothed_mult
            category_stats[state]["adjustment_pct"] = round(((smoothed_mult - current_mult) / current_mult) * 100, 2)
    
    result["multipliers"] = new_multipliers
    result["category_stats"] = category_stats
    result["multipliers_updated"] = updates_made
    result["status"] = "updated" if updates_made > 0 else "no_changes"
    
    _write_json(FEE_GATE_SIZING_PATH, {
        "version": 1,
        "updated_at": _now(),
        "multipliers": new_multipliers,
        "stats": category_stats,
        "trades_analyzed": result["trades_analyzed"],
    })
    
    if updates_made > 0:
        _log(f"Updated {updates_made} fee gate multipliers")
    
    return result


def learn_roi_threshold_sizing() -> Dict[str, Any]:
    """Learn optimal sizing multipliers for ROI threshold violations."""
    _log("Starting ROI threshold sizing multiplier learning...")
    
    result = {
        "status": "no_data",
        "trades_analyzed": 0,
        "multipliers_updated": 0,
        "multipliers": {},
        "category_stats": {},
        "timestamp": _now(),
    }
    
    trades = _load_recent_trades()
    if not trades:
        _log("No recent trades for ROI threshold sizing learning")
        return result
    
    current_multipliers = _read_json(ROI_SIZING_PATH, {
        "multipliers": DEFAULT_ROI_SIZING_MULTIPLIERS.copy(),
    }).get("multipliers", DEFAULT_ROI_SIZING_MULTIPLIERS.copy())
    
    state_trades: Dict[str, List[Dict]] = defaultdict(list)
    
    for trade in trades:
        roi_state = _extract_roi_state(trade)
        if roi_state:
            pnl = trade.get("pnl") or trade.get("net_pnl", 0)
            margin = trade.get("margin_collateral", 0) or trade.get("size_usd", 0)
            roi_pct = _calculate_pnl_roi(pnl, margin)
            
            state_trades[roi_state].append({
                "pnl": pnl,
                "margin": margin,
                "roi_pct": roi_pct,
                "symbol": trade.get("symbol", "UNKNOWN"),
            })
    
    result["trades_analyzed"] = len(trades)
    
    new_multipliers = dict(current_multipliers)
    category_stats = {}
    updates_made = 0
    
    for state, trades_in_state in state_trades.items():
        if len(trades_in_state) < MIN_TRADES_FOR_LEARNING:
            category_stats[state] = {
                "count": len(trades_in_state),
                "status": "insufficient_data",
            }
            continue
        
        total_pnl = sum(t["pnl"] for t in trades_in_state)
        avg_pnl = total_pnl / len(trades_in_state)
        avg_roi = sum(t["roi_pct"] for t in trades_in_state) / len(trades_in_state)
        win_rate = sum(1 for t in trades_in_state if t["pnl"] > 0) / len(trades_in_state)
        
        category_stats[state] = {
            "count": len(trades_in_state),
            "total_pnl": round(total_pnl, 4),
            "avg_pnl": round(avg_pnl, 4),
            "avg_roi": round(avg_roi, 4),
            "win_rate": round(win_rate, 4),
        }
        
        current_mult = current_multipliers.get(state, 1.0)
        
        # Calculate optimal multiplier
        if avg_roi > 0 and win_rate > 0.5:
            adjustment = min(0.15, max(0.05, avg_roi / 10))
            optimal_mult = current_mult * (1 + adjustment)
        elif avg_roi < 0 or win_rate < 0.4:
            adjustment = min(0.15, max(0.05, abs(avg_roi) / 10))
            optimal_mult = current_mult * (1 - adjustment)
        else:
            optimal_mult = current_mult
        
        smoothed_mult = _ewma_update(current_mult, optimal_mult)
        
        # Constrain based on state
        if state == "below_threshold":
            smoothed_mult = max(0.3, min(0.9, smoothed_mult))
        elif state == "at_threshold":
            smoothed_mult = max(0.6, min(1.0, smoothed_mult))
        else:  # above_threshold
            smoothed_mult = max(0.9, min(1.1, smoothed_mult))
        
        if abs(smoothed_mult - current_mult) > 0.02:
            new_multipliers[state] = round(smoothed_mult, 3)
            updates_made += 1
            category_stats[state]["old_mult"] = current_mult
            category_stats[state]["new_mult"] = smoothed_mult
            category_stats[state]["adjustment_pct"] = round(((smoothed_mult - current_mult) / current_mult) * 100, 2)
    
    result["multipliers"] = new_multipliers
    result["category_stats"] = category_stats
    result["multipliers_updated"] = updates_made
    result["status"] = "updated" if updates_made > 0 else "no_changes"
    
    _write_json(ROI_SIZING_PATH, {
        "version": 1,
        "updated_at": _now(),
        "multipliers": new_multipliers,
        "stats": category_stats,
        "trades_analyzed": result["trades_analyzed"],
    })
    
    if updates_made > 0:
        _log(f"Updated {updates_made} ROI threshold multipliers")
    
    return result


def run_all_sizing_learners() -> Dict[str, Any]:
    """
    Run all sizing multiplier learners and return summary.
    
    Returns:
        Dict with results from all learners
    """
    _log("=" * 60)
    _log("SIZING MULTIPLIER LEARNING - Starting")
    _log("=" * 60)
    
    start_time = time.time()
    
    results = {
        "intelligence_gate": {},
        "streak_filter": {},
        "regime_filter": {},
        "fee_gate": {},
        "roi_threshold": {},
        "summary": {},
        "timestamp": _now(),
    }
    
    try:
        results["intelligence_gate"] = learn_intelligence_gate_sizing()
    except Exception as e:
        _log(f"Intelligence gate learning error: {e}")
        import traceback
        traceback.print_exc()
        results["intelligence_gate"] = {"status": "error", "error": str(e)}
    
    try:
        results["streak_filter"] = learn_streak_sizing()
    except Exception as e:
        _log(f"Streak filter learning error: {e}")
        import traceback
        traceback.print_exc()
        results["streak_filter"] = {"status": "error", "error": str(e)}
    
    try:
        results["regime_filter"] = learn_regime_sizing()
    except Exception as e:
        _log(f"Regime filter learning error: {e}")
        import traceback
        traceback.print_exc()
        results["regime_filter"] = {"status": "error", "error": str(e)}
    
    try:
        results["fee_gate"] = learn_fee_gate_sizing()
    except Exception as e:
        _log(f"Fee gate learning error: {e}")
        import traceback
        traceback.print_exc()
        results["fee_gate"] = {"status": "error", "error": str(e)}
    
    try:
        results["roi_threshold"] = learn_roi_threshold_sizing()
    except Exception as e:
        _log(f"ROI threshold learning error: {e}")
        import traceback
        traceback.print_exc()
        results["roi_threshold"] = {"status": "error", "error": str(e)}
    
    elapsed = time.time() - start_time
    
    successful = sum(1 for k in ["intelligence_gate", "streak_filter", "regime_filter", "fee_gate", "roi_threshold"]
                     if results[k].get("status") in ["updated", "no_changes"])
    
    total_updates = sum(results[k].get("multipliers_updated", 0) for k in results if isinstance(results[k], dict))
    
    results["summary"] = {
        "successful_learners": successful,
        "total_learners": 5,
        "total_multipliers_updated": total_updates,
        "elapsed_seconds": round(elapsed, 2),
        "status": "success" if successful == 5 else "partial" if successful > 0 else "failed",
    }
    
    _log("=" * 60)
    _log(f"SIZING MULTIPLIER LEARNING - Complete ({successful}/5 successful, {total_updates} multipliers updated)")
    _log("=" * 60)
    
    return results
