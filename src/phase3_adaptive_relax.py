"""
Phase 3 Adaptive Filter Relaxation

Automatically relaxes filters when flow is choked (95%+ signals blocked for 6+ hours).
Prevents missing opportunities during periods of strict filtering.
"""

from dataclasses import dataclass
from typing import Optional, List, Tuple
from datetime import datetime, timedelta
import json
from pathlib import Path


@dataclass
class BlockStats:
    """Signal blocking statistics."""
    block_pct: float
    block_hours: float
    top_reasons: List[str]
    total_signals: int
    blocked_signals: int


def choose_relax_policy(stats: BlockStats, choke_threshold: float = 95.0, 
                        window_hours: int = 6) -> Optional[str]:
    """
    Select a relaxation policy when flow is choked.
    
    Args:
        stats: Current blocking statistics
        choke_threshold: Block percentage threshold to trigger relaxation
        window_hours: Minimum hours of choking required
        
    Returns:
        Relaxation policy name or None
    """
    if stats.block_pct < choke_threshold or stats.block_hours < window_hours:
        return None
    
    reasons = set(stats.top_reasons) if stats.top_reasons else set()
    
    if "mtf_strict_fail" in reasons or "mtf_confirmation_required" in reasons:
        return "require_1m_strong+15m_neutral"
    
    if "regime_mismatch" in reasons or "regime_allocation_exhausted" in reasons:
        return "require_regime_in_favor+1m_ok"
    
    return "allow_divergence_if_attribution_positive"


def should_relax_mtf(stats: BlockStats, choke_threshold: float = 95.0,
                     window_hours: int = 6) -> bool:
    """Check if MTF confirmation should be relaxed."""
    policy = choose_relax_policy(stats, choke_threshold, window_hours)
    return policy is not None


def get_relaxed_threshold(policy: Optional[str]) -> float:
    """
    Get relaxed ensemble threshold based on policy.
    
    Returns:
        Relaxed threshold (default 0.30 from 0.50)
    """
    if policy is None:
        return 0.50
    
    if policy == "require_1m_strong+15m_neutral":
        return 0.40
    
    if policy == "require_regime_in_favor+1m_ok":
        return 0.35
    
    return 0.30


@dataclass
class RelaxationState:
    """Track relaxation state over time."""
    is_relaxed: bool = False
    policy: Optional[str] = None
    activated_at: Optional[datetime] = None
    deactivated_at: Optional[datetime] = None
    total_relaxation_hours: float = 0.0


def update_relaxation_state(state: RelaxationState, stats: BlockStats,
                            choke_threshold: float = 95.0,
                            window_hours: int = 6) -> RelaxationState:
    """
    Update relaxation state based on current blocking stats.
    
    Args:
        state: Current relaxation state
        stats: Current blocking statistics
        choke_threshold: Block percentage threshold
        window_hours: Minimum choke duration
        
    Returns:
        Updated relaxation state
    """
    policy = choose_relax_policy(stats, choke_threshold, window_hours)
    
    if policy and not state.is_relaxed:
        state.is_relaxed = True
        state.policy = policy
        state.activated_at = datetime.now()
        
    elif not policy and state.is_relaxed:
        state.is_relaxed = False
        state.deactivated_at = datetime.now()
        
        if state.activated_at:
            duration = (state.deactivated_at - state.activated_at).total_seconds() / 3600
            state.total_relaxation_hours += duration
        
        state.policy = None
    
    return state


def save_relaxation_state(state: RelaxationState):
    """Save relaxation state to disk."""
    state_file = Path("logs/phase3_relaxation_state.json")
    state_file.parent.mkdir(exist_ok=True)
    
    data = {
        "is_relaxed": state.is_relaxed,
        "policy": state.policy,
        "activated_at": state.activated_at.isoformat() if state.activated_at else None,
        "deactivated_at": state.deactivated_at.isoformat() if state.deactivated_at else None,
        "total_relaxation_hours": state.total_relaxation_hours,
        "updated_at": datetime.now().isoformat()
    }
    
    with open(state_file, 'w') as f:
        json.dump(data, f, indent=2)


def load_relaxation_state() -> RelaxationState:
    """Load relaxation state from disk."""
    state_file = Path("logs/phase3_relaxation_state.json")
    
    if state_file.exists():
        try:
            with open(state_file) as f:
                data = json.load(f)
                
                return RelaxationState(
                    is_relaxed=data.get("is_relaxed", False),
                    policy=data.get("policy"),
                    activated_at=datetime.fromisoformat(data["activated_at"]) if data.get("activated_at") else None,
                    deactivated_at=datetime.fromisoformat(data["deactivated_at"]) if data.get("deactivated_at") else None,
                    total_relaxation_hours=data.get("total_relaxation_hours", 0.0)
                )
        except Exception:
            pass
    
    return RelaxationState()
