#!/usr/bin/env python3
"""
Unified Signal Bus - Event-Driven Signal Architecture

Single source of truth for all signals in the trading bot.
Provides event sourcing, state tracking, and queryable signal pipeline.

This is the foundation for the clean architecture migration.
"""

import json
import os
import time
import threading
import uuid
from pathlib import Path
from typing import Dict, List, Optional, Any
from enum import Enum
from datetime import datetime

from src.infrastructure.path_registry import PathRegistry


class SignalState(Enum):
    """Explicit signal lifecycle states"""
    GENERATED = "generated"      # Signal created
    EVALUATING = "evaluating"    # Being evaluated by gates
    APPROVED = "approved"         # Passed all gates, ready to execute
    EXECUTING = "executing"       # Order being placed
    EXECUTED = "executed"         # Order filled
    BLOCKED = "blocked"           # Blocked by gate
    EXPIRED = "expired"           # Timed out
    LEARNED = "learned"           # Outcome analyzed, learning applied


class SignalBus:
    """
    Unified signal bus - single source of truth for all signals.
    
    Features:
    - Event sourcing: All events stored in event log
    - State tracking: Explicit signal lifecycle
    - Queryable: Find signals by state, symbol, time, etc.
    - Guaranteed delivery: All signals captured
    - Thread-safe: Safe for concurrent access
    """
    
    def __init__(self):
        self.event_log_path = Path(PathRegistry.get_path("logs", "signal_bus.jsonl"))
        self.state_index = {}  # signal_id -> current state info
        self._lock = threading.RLock()
        self._ensure_log_exists()
    
    def _ensure_log_exists(self):
        """Ensure event log file and directory exist"""
        self.event_log_path.parent.mkdir(parents=True, exist_ok=True)
        if not self.event_log_path.exists():
            self.event_log_path.touch()
    
    def emit_signal(self, signal: Dict[str, Any], source: str = "unknown") -> str:
        """
        Emit a signal event to the bus.
        
        Args:
            signal: Signal dictionary with at minimum: symbol, direction, ts
            source: Source of signal (e.g., "alpha_signals", "predictive_flow")
        
        Returns:
            signal_id: Unique identifier for this signal
        """
        # Generate unique signal ID
        signal_id = f"{signal.get('symbol', 'UNKNOWN')}_{int(time.time()*1000)}_{uuid.uuid4().hex[:8]}"
        
        # Ensure signal has required fields
        if 'ts' not in signal:
            signal['ts'] = time.time()
        if 'timestamp' not in signal:
            signal['timestamp'] = datetime.utcnow().isoformat() + 'Z'
        
        event = {
            "event_type": "signal_generated",
            "event_id": str(uuid.uuid4()),
            "signal_id": signal_id,
            "ts": time.time(),
            "timestamp": datetime.utcnow().isoformat() + 'Z',
            "source": source,
            "signal": signal,
            "state": SignalState.GENERATED.value
        }
        
        with self._lock:
            # Write to event log (append-only)
            try:
                with open(self.event_log_path, 'a') as f:
                    f.write(json.dumps(event) + '\n')
            except Exception as e:
                print(f"⚠️ [SIGNAL-BUS] Failed to write event: {e}")
                return None
            
            # Update in-memory state index
            self.state_index[signal_id] = {
                "state": SignalState.GENERATED.value,
                "signal": signal,
                "source": source,
                "ts": time.time(),
                "created_at": event["timestamp"]
            }
        
        return signal_id
    
    def update_state(self, signal_id: str, new_state: SignalState, 
                    metadata: Optional[Dict] = None, reason: Optional[str] = None) -> bool:
        """
        Update signal lifecycle state.
        
        Args:
            signal_id: Signal identifier
            new_state: New state to transition to
            metadata: Additional metadata about the state change
            reason: Reason for state change (e.g., "blocked_by_fee_gate")
        
        Returns:
            True if state updated, False if signal not found
        """
        with self._lock:
            if signal_id not in self.state_index:
                return False
            
            old_state = self.state_index[signal_id]["state"]
            
            event = {
                "event_type": "state_change",
                "event_id": str(uuid.uuid4()),
                "signal_id": signal_id,
                "old_state": old_state,
                "new_state": new_state.value,
                "ts": time.time(),
                "timestamp": datetime.utcnow().isoformat() + 'Z',
                "reason": reason,
                "metadata": metadata or {}
            }
            
            try:
                with open(self.event_log_path, 'a') as f:
                    f.write(json.dumps(event) + '\n')
            except Exception as e:
                print(f"⚠️ [SIGNAL-BUS] Failed to write state change: {e}")
                return False
            
            # Update state index
            self.state_index[signal_id]["state"] = new_state.value
            self.state_index[signal_id]["last_state_change"] = time.time()
            if metadata:
                self.state_index[signal_id].update(metadata)
            if reason:
                self.state_index[signal_id]["last_reason"] = reason
        
        return True
    
    def get_signal(self, signal_id: str) -> Optional[Dict]:
        """Get signal by ID with current state"""
        with self._lock:
            return self.state_index.get(signal_id)
    
    def get_signals(self, 
                   state: Optional[SignalState] = None,
                   symbol: Optional[str] = None,
                   source: Optional[str] = None,
                   since_ts: Optional[float] = None,
                   limit: Optional[int] = None) -> List[Dict]:
        """
        Query signals by various filters.
        
        Args:
            state: Filter by signal state
            symbol: Filter by symbol
            source: Filter by signal source
            since_ts: Only signals after this timestamp
            limit: Maximum number of results
        
        Returns:
            List of signal dictionaries with state info
        """
        with self._lock:
            results = []
            
            for signal_id, signal_data in self.state_index.items():
                # Apply filters
                if state and signal_data["state"] != state.value:
                    continue
                if symbol and signal_data["signal"].get("symbol") != symbol:
                    continue
                if source and signal_data.get("source") != source:
                    continue
                if since_ts and signal_data["ts"] < since_ts:
                    continue
                
                # Add signal_id to result
                result = signal_data.copy()
                result["signal_id"] = signal_id
                results.append(result)
            
            # Sort by timestamp (newest first)
            results.sort(key=lambda x: x["ts"], reverse=True)
            
            # Apply limit
            if limit:
                results = results[:limit]
            
            return results
    
    def get_signals_by_state(self, state: SignalState) -> List[str]:
        """Get all signal IDs in given state"""
        with self._lock:
            return [
                signal_id for signal_id, data in self.state_index.items()
                if data["state"] == state.value
            ]
    
    def get_pipeline_health(self) -> Dict[str, Any]:
        """Get health metrics for signal pipeline"""
        with self._lock:
            state_counts = {}
            for state in SignalState:
                state_counts[state.value] = len([
                    s for s in self.state_index.values()
                    if s["state"] == state.value
                ])
            
            # Count signals by source
            source_counts = {}
            for data in self.state_index.values():
                source = data.get("source", "unknown")
                source_counts[source] = source_counts.get(source, 0) + 1
            
            # Find stuck signals (in same state > 1 hour)
            now = time.time()
            stuck_signals = []
            for signal_id, data in self.state_index.items():
                last_change = data.get("last_state_change", data["ts"])
                if now - last_change > 3600:  # 1 hour
                    stuck_signals.append({
                        "signal_id": signal_id,
                        "state": data["state"],
                        "stuck_for_seconds": int(now - last_change)
                    })
            
            return {
                "total_signals": len(self.state_index),
                "state_counts": state_counts,
                "source_counts": source_counts,
                "stuck_signals": stuck_signals,
                "stuck_count": len(stuck_signals)
            }
    
    def replay_events(self, since_ts: Optional[float] = None) -> List[Dict]:
        """
        Replay events from event log.
        Useful for debugging and audit trail.
        
        Args:
            since_ts: Only replay events after this timestamp
        
        Returns:
            List of events
        """
        events = []
        
        if not self.event_log_path.exists():
            return events
        
        try:
            with open(self.event_log_path, 'r') as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        event = json.loads(line)
                        if since_ts and event.get("ts", 0) < since_ts:
                            continue
                        events.append(event)
                    except json.JSONDecodeError:
                        continue
        except Exception as e:
            print(f"⚠️ [SIGNAL-BUS] Failed to replay events: {e}")
        
        return events


# Global singleton instance
_signal_bus_instance = None
_signal_bus_lock = threading.Lock()


def get_signal_bus() -> SignalBus:
    """Get global SignalBus instance (singleton)"""
    global _signal_bus_instance
    
    with _signal_bus_lock:
        if _signal_bus_instance is None:
            _signal_bus_instance = SignalBus()
        return _signal_bus_instance


