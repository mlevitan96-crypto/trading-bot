#!/usr/bin/env python3
"""
Signal Pipeline Monitor
========================
Monitors signal pipeline health and provides dashboard metrics.

Tracks:
- Signals by state
- Stuck signals
- Signal flow health
- Pipeline throughput
"""

import time
from typing import Dict, List, Any
from datetime import datetime, timedelta

from src.signal_bus import get_signal_bus, SignalState
from src.signal_state_machine import get_state_machine


class SignalPipelineMonitor:
    """Monitors signal pipeline health"""
    
    def __init__(self):
        self.signal_bus = get_signal_bus()
        self.state_machine = get_state_machine()
    
    def get_pipeline_health(self) -> Dict[str, Any]:
        """Get comprehensive pipeline health metrics"""
        health = self.signal_bus.get_pipeline_health()
        
        # Add stuck signals
        stuck = self.state_machine.get_stuck_signals(max_age_seconds=3600)
        health["stuck_signals"] = stuck
        health["stuck_count"] = len(stuck)
        
        # Add recent activity (last hour)
        cutoff_ts = time.time() - 3600
        recent_signals = self.signal_bus.get_signals(since_ts=cutoff_ts)
        health["recent_activity"] = {
            "total_last_hour": len(recent_signals),
            "by_state": {}
        }
        
        for signal in recent_signals:
            state = signal.get("state", "unknown")
            health["recent_activity"]["by_state"][state] = \
                health["recent_activity"]["by_state"].get(state, 0) + 1
        
        # Calculate throughput (signals per hour)
        health["throughput"] = {
            "signals_per_hour": len(recent_signals),
            "avg_per_minute": len(recent_signals) / 60 if recent_signals else 0
        }
        
        # Overall health status
        health["status"] = self._calculate_health_status(health)
        
        return health
    
    def _calculate_health_status(self, health: Dict) -> str:
        """Calculate overall health status"""
        stuck_count = health.get("stuck_count", 0)
        total_signals = health.get("total_signals", 0)
        recent_activity = health.get("recent_activity", {}).get("total_last_hour", 0)
        
        # Critical: Too many stuck signals
        if stuck_count > 10:
            return "CRITICAL"
        
        # Warning: Some stuck signals or no recent activity
        if stuck_count > 0 or recent_activity == 0:
            return "WARNING"
        
        # Healthy: Active and no stuck signals
        return "HEALTHY"
    
    def get_signals_by_state(self, state: SignalState) -> List[Dict]:
        """Get all signals in given state"""
        return self.signal_bus.get_signals(state=state)
    
    def get_stuck_signals(self, max_age_hours: float = 1.0) -> List[Dict]:
        """Get stuck signals"""
        return self.state_machine.get_stuck_signals(max_age_seconds=int(max_age_hours * 3600))
    
    def get_recent_activity(self, hours: int = 1) -> Dict[str, Any]:
        """Get recent signal activity"""
        cutoff_ts = time.time() - (hours * 3600)
        signals = self.signal_bus.get_signals(since_ts=cutoff_ts)
        
        by_state = {}
        by_source = {}
        
        for signal in signals:
            state = signal.get("state", "unknown")
            source = signal.get("source", "unknown")
            
            by_state[state] = by_state.get(state, 0) + 1
            by_source[source] = by_source.get(source, 0) + 1
        
        return {
            "total": len(signals),
            "by_state": by_state,
            "by_source": by_source,
            "period_hours": hours
        }


# Global singleton
_monitor_instance = None


def get_pipeline_monitor() -> SignalPipelineMonitor:
    """Get global SignalPipelineMonitor instance"""
    global _monitor_instance
    
    if _monitor_instance is None:
        _monitor_instance = SignalPipelineMonitor()
    return _monitor_instance

