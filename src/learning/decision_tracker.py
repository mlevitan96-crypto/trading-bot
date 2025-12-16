#!/usr/bin/env python3
"""
Decision Tracker - Enhanced Learning Engine Component
=====================================================
Tracks all signal decisions (approved/blocked) with full context for learning.

Integrates with:
- SignalBus for event sourcing
- Shadow Execution Engine for what-if analysis
- Analytics for reporting
"""

import time
from typing import Dict, Optional, Any
from datetime import datetime

from src.signal_bus import get_signal_bus, SignalState
from src.events.schemas import (
    SignalDecisionEvent,
    MarketSnapshot,
    create_decision_event,
    BlockerComponent
)
from src.exchange_gateway import ExchangeGateway


class DecisionTracker:
    """
    Tracks all signal decisions with full context.
    
    Every time a guard/gate blocks or approves a signal, this tracker:
    1. Captures market snapshot
    2. Records decision with blocker component and reason
    3. Emits to SignalBus for event sourcing
    4. Enables what-if analysis later
    """
    
    def __init__(self):
        self.signal_bus = get_signal_bus()
        self.exchange_gateway = ExchangeGateway()
    
    def track_decision(
        self,
        signal_id: str,
        decision: str,  # "APPROVED" or "BLOCKED"
        blocker_component: Optional[str] = None,
        blocker_reason: Optional[str] = None,
        symbol: Optional[str] = None,
        signal_metadata: Optional[Dict] = None
    ) -> bool:
        """
        Track a signal decision.
        
        Args:
            signal_id: Signal identifier
            decision: "APPROVED" or "BLOCKED"
            blocker_component: Component that made decision (e.g., "VolatilityGuard")
            blocker_reason: Specific reason (e.g., "Current vol 0.05 > Max 0.04")
            symbol: Trading symbol (for market snapshot)
            signal_metadata: Original signal metadata
        
        Returns:
            True if tracked successfully
        """
        try:
            # Get market snapshot
            market_snapshot = None
            if symbol:
                try:
                    price = self.exchange_gateway.get_price(symbol, venue="futures")
                    if price and price > 0:
                        # Get spread (simplified - can be enhanced)
                        spread_bps = 0.5  # Default, can be fetched from exchange
                        market_snapshot = MarketSnapshot(
                            price=price,
                            spread=price * spread_bps / 10000,
                            spread_bps=spread_bps,
                            timestamp=datetime.utcnow().isoformat() + 'Z'
                        )
                except Exception as e:
                    # Market snapshot is optional, continue without it
                    pass
            
            # Create decision event
            decision_event = create_decision_event(
                signal_id=signal_id,
                decision=decision,
                blocker_component=blocker_component,
                blocker_reason=blocker_reason,
                market_snapshot=market_snapshot,
                signal_metadata=signal_metadata
            )
            
            # Emit to SignalBus
            # First, update signal state
            if decision == "BLOCKED":
                self.signal_bus.update_state(
                    signal_id,
                    SignalState.BLOCKED,
                    metadata={
                        "blocker_component": blocker_component,
                        "blocker_reason": blocker_reason
                    },
                    reason=blocker_reason
                )
            elif decision == "APPROVED":
                self.signal_bus.update_state(
                    signal_id,
                    SignalState.APPROVED,
                    metadata={"approved_by": blocker_component or "system"}
                )
            
            # Log decision event to bus event log
            # (SignalBus already logs state changes, but we also want decision events)
            try:
                from src.infrastructure.path_registry import PathRegistry
                import json
                decision_log_path = Path(PathRegistry.get_path("logs", "signal_decisions.jsonl"))
                decision_log_path.parent.mkdir(parents=True, exist_ok=True)
                
                with open(decision_log_path, 'a') as f:
                    f.write(json.dumps(decision_event.to_dict()) + '\n')
            except Exception as e:
                # Non-critical, continue
                pass
            
            return True
            
        except Exception as e:
            print(f"⚠️ [DECISION-TRACKER] Failed to track decision: {e}")
            return False
    
    def track_block(
        self,
        signal_id: str,
        blocker_component: str,
        blocker_reason: str,
        symbol: Optional[str] = None,
        signal_metadata: Optional[Dict] = None
    ) -> bool:
        """Convenience method to track a blocked signal"""
        return self.track_decision(
            signal_id=signal_id,
            decision="BLOCKED",
            blocker_component=blocker_component,
            blocker_reason=blocker_reason,
            symbol=symbol,
            signal_metadata=signal_metadata
        )
    
    def track_approval(
        self,
        signal_id: str,
        approved_by: Optional[str] = None,
        symbol: Optional[str] = None,
        signal_metadata: Optional[Dict] = None
    ) -> bool:
        """Convenience method to track an approved signal"""
        return self.track_decision(
            signal_id=signal_id,
            decision="APPROVED",
            blocker_component=approved_by,
            blocker_reason="All gates passed",
            symbol=symbol,
            signal_metadata=signal_metadata
        )


# Global singleton
_decision_tracker_instance = None


def get_decision_tracker() -> DecisionTracker:
    """Get global DecisionTracker instance"""
    global _decision_tracker_instance
    
    if _decision_tracker_instance is None:
        _decision_tracker_instance = DecisionTracker()
    return _decision_tracker_instance

