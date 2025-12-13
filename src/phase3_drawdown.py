"""
Phase 3 Drawdown-Aware Throttle

Reduces position sizes during drawdown periods.
Complements Phase 2 Sharpe/Sortino throttle with drawdown-based adjustment.
"""

from typing import Tuple
from dataclasses import dataclass
import json
from pathlib import Path
from datetime import datetime


@dataclass
class DrawdownState:
    """Track rolling drawdown state."""
    peak_value: float = 10000.0
    current_value: float = 10000.0
    current_drawdown_bps: float = 0.0
    max_drawdown_bps: float = 0.0
    soft_block_active: bool = False


def compute_drawdown(peak_value: float, current_value: float) -> float:
    """
    Compute drawdown in basis points.
    
    Args:
        peak_value: Peak portfolio value
        current_value: Current portfolio value
        
    Returns:
        Drawdown in basis points (negative value)
    """
    if peak_value <= 0:
        return 0.0
    
    drawdown_pct = (current_value - peak_value) / peak_value
    return drawdown_pct * 10000


def update_drawdown_state(state: DrawdownState, current_value: float) -> DrawdownState:
    """
    Update drawdown state with current portfolio value.
    
    Args:
        state: Current drawdown state
        current_value: Current portfolio value
        
    Returns:
        Updated drawdown state
    """
    if current_value > state.peak_value:
        state.peak_value = current_value
    
    state.current_value = current_value
    state.current_drawdown_bps = compute_drawdown(state.peak_value, current_value)
    
    if state.current_drawdown_bps < state.max_drawdown_bps:
        state.max_drawdown_bps = state.current_drawdown_bps
    
    return state


def dd_adjust_size(base_size: float, rolling_drawdown_bps: float,
                  soft_block_threshold: float = 150.0,
                  size_reduction_pct: float = 0.4) -> Tuple[float, bool]:
    """
    Adjust position size based on drawdown.
    
    Args:
        base_size: Base position size (units or USD)
        rolling_drawdown_bps: Current rolling drawdown in bps (negative)
        soft_block_threshold: Drawdown threshold to trigger reduction (positive bps)
        size_reduction_pct: Percentage to reduce size (0-1)
        
    Returns:
        (adjusted_size, soft_block_active)
    """
    if rolling_drawdown_bps <= -soft_block_threshold:
        adjusted_size = base_size * (1.0 - size_reduction_pct)
        return adjusted_size, True
    
    return base_size, False


def should_pause_ramp(drawdown_bps: float, max_drawdown_threshold: float = 300.0) -> bool:
    """
    Check if capital ramp should pause due to drawdown.
    
    Args:
        drawdown_bps: Current drawdown in bps (negative)
        max_drawdown_threshold: Maximum allowed drawdown (positive bps)
        
    Returns:
        True if ramp should pause
    """
    return drawdown_bps <= -max_drawdown_threshold


def save_drawdown_state(state: DrawdownState):
    """Save drawdown state to disk."""
    state_file = Path("logs/phase3_drawdown_state.json")
    state_file.parent.mkdir(exist_ok=True)
    
    data = {
        "peak_value": state.peak_value,
        "current_value": state.current_value,
        "current_drawdown_bps": state.current_drawdown_bps,
        "max_drawdown_bps": state.max_drawdown_bps,
        "soft_block_active": state.soft_block_active,
        "updated_at": datetime.now().isoformat()
    }
    
    with open(state_file, 'w') as f:
        json.dump(data, f, indent=2)


def load_drawdown_state() -> DrawdownState:
    """Load drawdown state from disk."""
    state_file = Path("logs/phase3_drawdown_state.json")
    
    if state_file.exists():
        try:
            with open(state_file) as f:
                data = json.load(f)
                
                return DrawdownState(
                    peak_value=data.get("peak_value", 10000.0),
                    current_value=data.get("current_value", 10000.0),
                    current_drawdown_bps=data.get("current_drawdown_bps", 0.0),
                    max_drawdown_bps=data.get("max_drawdown_bps", 0.0),
                    soft_block_active=data.get("soft_block_active", False)
                )
        except Exception:
            pass
    
    return DrawdownState()
