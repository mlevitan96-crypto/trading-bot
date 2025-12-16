#!/usr/bin/env python3
"""
Signal State Machine
====================
Explicit state machine for signal lifecycle with validation and monitoring.

Prevents invalid state transitions and tracks signal lifecycle explicitly.
"""

import time
from typing import Dict, List, Optional, Any
from enum import Enum
from datetime import datetime

from src.signal_bus import SignalState, get_signal_bus


class SignalStateMachine:
    """
    Manages signal lifecycle state transitions with validation.
    
    Valid transitions:
    - GENERATED → EVALUATING → APPROVED → EXECUTING → EXECUTED
    - GENERATED → EVALUATING → BLOCKED
    - GENERATED → EXPIRED
    - EXECUTED → LEARNED
    """
    
    # Valid state transitions
    VALID_TRANSITIONS = {
        SignalState.GENERATED: [SignalState.EVALUATING, SignalState.EXPIRED],
        SignalState.EVALUATING: [SignalState.APPROVED, SignalState.BLOCKED, SignalState.EXPIRED],
        SignalState.APPROVED: [SignalState.EXECUTING, SignalState.EXPIRED],
        SignalState.EXECUTING: [SignalState.EXECUTED, SignalState.EXPIRED],
        SignalState.EXECUTED: [SignalState.LEARNED],
        SignalState.BLOCKED: [SignalState.LEARNED],  # Can learn from blocked signals
        SignalState.EXPIRED: [],  # Terminal state
        SignalState.LEARNED: []  # Terminal state
    }
    
    def __init__(self):
        self.signal_bus = get_signal_bus()
        self.transition_history = {}  # signal_id -> list of transitions
    
    def transition(
        self,
        signal_id: str,
        new_state: SignalState,
        metadata: Optional[Dict] = None,
        reason: Optional[str] = None
    ) -> bool:
        """
        Transition signal to new state with validation.
        
        Args:
            signal_id: Signal identifier
            new_state: New state to transition to
            metadata: Additional metadata
            reason: Reason for transition
        
        Returns:
            True if transition successful, False if invalid
        """
        # Get current state
        signal_data = self.signal_bus.get_signal(signal_id)
        if not signal_data:
            print(f"⚠️ [STATE-MACHINE] Signal {signal_id} not found")
            return False
        
        current_state_str = signal_data.get("state")
        try:
            current_state = SignalState(current_state_str)
        except ValueError:
            print(f"⚠️ [STATE-MACHINE] Invalid current state: {current_state_str}")
            return False
        
        # Validate transition
        if not self._is_valid_transition(current_state, new_state):
            print(f"⚠️ [STATE-MACHINE] Invalid transition: {current_state.value} → {new_state.value} for signal {signal_id}")
            return False
        
        # Perform transition
        success = self.signal_bus.update_state(
            signal_id,
            new_state,
            metadata=metadata,
            reason=reason
        )
        
        if success:
            # Record transition history
            if signal_id not in self.transition_history:
                self.transition_history[signal_id] = []
            
            self.transition_history[signal_id].append({
                "from_state": current_state.value,
                "to_state": new_state.value,
                "ts": time.time(),
                "timestamp": datetime.utcnow().isoformat() + 'Z',
                "reason": reason,
                "metadata": metadata
            })
        
        return success
    
    def _is_valid_transition(self, from_state: SignalState, to_state: SignalState) -> bool:
        """Check if transition is valid"""
        valid_next = self.VALID_TRANSITIONS.get(from_state, [])
        return to_state in valid_next
    
    def get_stuck_signals(self, max_age_seconds: int = 3600) -> List[Dict]:
        """
        Find signals stuck in same state for too long.
        
        Args:
            max_age_seconds: Maximum age before considered stuck (default 1 hour)
        
        Returns:
            List of stuck signal info
        """
        now = time.time()
        stuck = []
        
        # Get all signals
        all_signals = self.signal_bus.get_signals()
        
        for signal_data in all_signals:
            signal_id = signal_data.get("signal_id")
            state = signal_data.get("state")
            last_change = signal_data.get("last_state_change", signal_data.get("ts", 0))
            
            # Skip terminal states
            if state in ["expired", "learned"]:
                continue
            
            age = now - last_change
            if age > max_age_seconds:
                stuck.append({
                    "signal_id": signal_id,
                    "state": state,
                    "stuck_for_seconds": int(age),
                    "stuck_for_hours": age / 3600,
                    "symbol": signal_data.get("signal", {}).get("symbol", "UNKNOWN")
                })
        
        return stuck
    
    def auto_expire_old_signals(self, max_age_seconds: int = 7200) -> int:
        """
        Automatically expire signals that are too old.
        
        Args:
            max_age_seconds: Maximum age before auto-expire (default 2 hours)
        
        Returns:
            Number of signals expired
        """
        now = time.time()
        expired_count = 0
        
        # Get all non-terminal signals
        all_signals = self.signal_bus.get_signals()
        
        for signal_data in all_signals:
            signal_id = signal_data.get("signal_id")
            state = signal_data.get("state")
            
            # Skip already terminal states
            if state in ["expired", "learned", "executed"]:
                continue
            
            created_ts = signal_data.get("ts", 0)
            age = now - created_ts
            
            if age > max_age_seconds:
                # Auto-expire
                if self.transition(signal_id, SignalState.EXPIRED, reason="auto_expired_old"):
                    expired_count += 1
        
        return expired_count
    
    def get_transition_history(self, signal_id: str) -> List[Dict]:
        """Get transition history for a signal"""
        return self.transition_history.get(signal_id, [])


# Global singleton
_state_machine_instance = None


def get_state_machine() -> SignalStateMachine:
    """Get global SignalStateMachine instance"""
    global _state_machine_instance
    
    if _state_machine_instance is None:
        _state_machine_instance = SignalStateMachine()
    return _state_machine_instance

