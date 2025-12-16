#!/usr/bin/env python3
"""
Event Schemas for Trading Bot
=============================
Defines structured event schemas for all trading bot events.
Enables event sourcing, analytics, and what-if scenarios.
"""

from typing import Dict, List, Optional, Any, Literal
from datetime import datetime
from dataclasses import dataclass, asdict
from enum import Enum
import json


class DecisionType(Enum):
    """Decision types for signal processing"""
    APPROVED = "APPROVED"
    BLOCKED = "BLOCKED"
    EXPIRED = "EXPIRED"
    CANCELLED = "CANCELLED"


class BlockerComponent(Enum):
    """Components that can block signals"""
    VOLATILITY_GUARD = "VolatilityGuard"
    RISK_GUARD = "RiskGuard"
    CAPITAL_GUARD = "CapitalGuard"
    SENTIMENT_GUARD = "SentimentGuard"
    FEE_GATE = "FeeGate"
    CONVICTION_GATE = "ConvictionGate"
    EXECUTION_GATE = "ExecutionGate"
    CORRELATION_THROTTLE = "CorrelationThrottle"
    HOLD_GOVERNOR = "HoldGovernor"
    REGIME_FILTER = "RegimeFilter"
    INTELLIGENCE_GATE = "IntelligenceGate"
    MTF_GATE = "MTFGate"
    ROI_GATE = "ROIGate"
    HOURLY_CAP = "HourlyCap"
    ANOMALY_DEFENSE = "AnomalyDefense"
    UNKNOWN = "Unknown"


@dataclass
class MarketSnapshot:
    """Market state at a specific point in time"""
    price: float
    spread: float
    spread_bps: float
    volume_24h: Optional[float] = None
    volatility: Optional[float] = None
    regime: Optional[str] = None
    funding_rate: Optional[float] = None
    open_interest: Optional[float] = None
    timestamp: Optional[str] = None
    
    def to_dict(self) -> Dict:
        """Convert to dictionary"""
        return asdict(self)


@dataclass
class SignalDecisionEvent:
    """
    Decision event for a signal - tracks exactly why trades are blocked.
    
    This is the foundation for:
    - Blocked opportunity analysis
    - What-if scenarios
    - Guard effectiveness evaluation
    """
    signal_id: str
    decision: Literal["APPROVED", "BLOCKED", "EXPIRED", "CANCELLED"]
    blocker_component: Optional[str] = None  # e.g., "VolatilityGuard"
    blocker_reason: Optional[str] = None  # e.g., "Current vol 0.05 > Max 0.04"
    market_snapshot: Optional[Dict] = None  # MarketSnapshot as dict
    signal_metadata: Optional[Dict] = None  # Original signal metadata
    timestamp: Optional[str] = None
    ts: Optional[float] = None
    
    def __post_init__(self):
        """Set timestamp if not provided"""
        if not self.timestamp:
            self.timestamp = datetime.utcnow().isoformat() + 'Z'
        if not self.ts:
            self.ts = datetime.utcnow().timestamp()
    
    def to_dict(self) -> Dict:
        """Convert to dictionary for JSON serialization"""
        return {
            "event_type": "signal_decision",
            "signal_id": self.signal_id,
            "decision": self.decision,
            "blocker_component": self.blocker_component,
            "blocker_reason": self.blocker_reason,
            "market_snapshot": self.market_snapshot,
            "signal_metadata": self.signal_metadata,
            "timestamp": self.timestamp,
            "ts": self.ts
        }
    
    @classmethod
    def from_dict(cls, data: Dict) -> "SignalDecisionEvent":
        """Create from dictionary"""
        return cls(
            signal_id=data["signal_id"],
            decision=data["decision"],
            blocker_component=data.get("blocker_component"),
            blocker_reason=data.get("blocker_reason"),
            market_snapshot=data.get("market_snapshot"),
            signal_metadata=data.get("signal_metadata"),
            timestamp=data.get("timestamp"),
            ts=data.get("ts")
        )


@dataclass
class SignalEvent:
    """
    Enhanced signal event with granular attribution metadata.
    
    Enables:
    - Strategy-level analytics
    - Indicator correlation analysis
    - Regime-specific performance
    """
    signal_id: str
    symbol: str
    direction: str
    strategy_name: Optional[str] = None
    indicator_values: Optional[Dict[str, float]] = None
    regime_context: Optional[str] = None
    confidence: Optional[float] = None
    alignment_score: Optional[float] = None
    metadata: Optional[Dict] = None
    timestamp: Optional[str] = None
    ts: Optional[float] = None
    
    def __post_init__(self):
        """Set timestamp if not provided"""
        if not self.timestamp:
            self.timestamp = datetime.utcnow().isoformat() + 'Z'
        if not self.ts:
            self.ts = datetime.utcnow().timestamp()
        
        # Ensure metadata dict exists
        if self.metadata is None:
            self.metadata = {}
        
        # Store strategy/indicator/regime in metadata for easy access
        if self.strategy_name:
            self.metadata["strategy_name"] = self.strategy_name
        if self.indicator_values:
            self.metadata["indicator_values"] = self.indicator_values
        if self.regime_context:
            self.metadata["regime_context"] = self.regime_context
    
    def to_dict(self) -> Dict:
        """Convert to dictionary for JSON serialization"""
        return {
            "event_type": "signal",
            "signal_id": self.signal_id,
            "symbol": self.symbol,
            "direction": self.direction,
            "strategy_name": self.strategy_name,
            "indicator_values": self.indicator_values,
            "regime_context": self.regime_context,
            "confidence": self.confidence,
            "alignment_score": self.alignment_score,
            "metadata": self.metadata,
            "timestamp": self.timestamp,
            "ts": self.ts
        }
    
    @classmethod
    def from_dict(cls, data: Dict) -> "SignalEvent":
        """Create from dictionary"""
        return cls(
            signal_id=data["signal_id"],
            symbol=data["symbol"],
            direction=data["direction"],
            strategy_name=data.get("strategy_name"),
            indicator_values=data.get("indicator_values"),
            regime_context=data.get("regime_context"),
            confidence=data.get("confidence"),
            alignment_score=data.get("alignment_score"),
            metadata=data.get("metadata", {}),
            timestamp=data.get("timestamp"),
            ts=data.get("ts")
        )


@dataclass
class ShadowTradeOutcomeEvent:
    """
    Outcome of a shadow (simulated) trade.
    
    Used for:
    - What-if analysis
    - Comparing filtered vs unfiltered performance
    - Guard effectiveness evaluation
    """
    signal_id: str
    shadow_trade_id: str
    symbol: str
    direction: str
    entry_price: float
    exit_price: Optional[float] = None
    exit_timestamp: Optional[str] = None
    pnl: Optional[float] = None
    pnl_pct: Optional[float] = None
    hold_time_seconds: Optional[float] = None
    was_profitable: Optional[bool] = None
    original_decision: Optional[str] = None  # "BLOCKED" or "APPROVED"
    blocker_component: Optional[str] = None
    timestamp: Optional[str] = None
    ts: Optional[float] = None
    
    def __post_init__(self):
        """Set timestamp if not provided"""
        if not self.timestamp:
            self.timestamp = datetime.utcnow().isoformat() + 'Z'
        if not self.ts:
            self.ts = datetime.utcnow().timestamp()
    
    def to_dict(self) -> Dict:
        """Convert to dictionary for JSON serialization"""
        return {
            "event_type": "shadow_trade_outcome",
            "signal_id": self.signal_id,
            "shadow_trade_id": self.shadow_trade_id,
            "symbol": self.symbol,
            "direction": self.direction,
            "entry_price": self.entry_price,
            "exit_price": self.exit_price,
            "exit_timestamp": self.exit_timestamp,
            "pnl": self.pnl,
            "pnl_pct": self.pnl_pct,
            "hold_time_seconds": self.hold_time_seconds,
            "was_profitable": self.was_profitable,
            "original_decision": self.original_decision,
            "blocker_component": self.blocker_component,
            "timestamp": self.timestamp,
            "ts": self.ts
        }
    
    @classmethod
    def from_dict(cls, data: Dict) -> "ShadowTradeOutcomeEvent":
        """Create from dictionary"""
        return cls(
            signal_id=data["signal_id"],
            shadow_trade_id=data["shadow_trade_id"],
            symbol=data["symbol"],
            direction=data["direction"],
            entry_price=data["entry_price"],
            exit_price=data.get("exit_price"),
            exit_timestamp=data.get("exit_timestamp"),
            pnl=data.get("pnl"),
            pnl_pct=data.get("pnl_pct"),
            hold_time_seconds=data.get("hold_time_seconds"),
            was_profitable=data.get("was_profitable"),
            original_decision=data.get("original_decision"),
            blocker_component=data.get("blocker_component"),
            timestamp=data.get("timestamp"),
            ts=data.get("ts")
        )


def create_decision_event(
    signal_id: str,
    decision: str,
    blocker_component: Optional[str] = None,
    blocker_reason: Optional[str] = None,
    market_snapshot: Optional[MarketSnapshot] = None,
    signal_metadata: Optional[Dict] = None
) -> SignalDecisionEvent:
    """Helper to create a SignalDecisionEvent"""
    return SignalDecisionEvent(
        signal_id=signal_id,
        decision=decision,
        blocker_component=blocker_component,
        blocker_reason=blocker_reason,
        market_snapshot=market_snapshot.to_dict() if market_snapshot else None,
        signal_metadata=signal_metadata
    )


def create_signal_event(
    signal_id: str,
    symbol: str,
    direction: str,
    strategy_name: Optional[str] = None,
    indicator_values: Optional[Dict[str, float]] = None,
    regime_context: Optional[str] = None,
    confidence: Optional[float] = None,
    alignment_score: Optional[float] = None,
    metadata: Optional[Dict] = None
) -> SignalEvent:
    """Helper to create a SignalEvent with granular attribution"""
    return SignalEvent(
        signal_id=signal_id,
        symbol=symbol,
        direction=direction,
        strategy_name=strategy_name,
        indicator_values=indicator_values,
        regime_context=regime_context,
        confidence=confidence,
        alignment_score=alignment_score,
        metadata=metadata
    )

