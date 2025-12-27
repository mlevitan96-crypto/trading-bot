#!/usr/bin/env python3
"""
Shadow Portfolio Engine (The Counterfactual Alpha)
==================================================

Automatically "executes" all signals in a virtual environment, including
those blocked by gates or thresholds. Records outcomes for counterfactual
analysis and guard optimization.
"""

import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Any
from collections import defaultdict

SHADOW_RESULTS_PATH = Path("logs/shadow_results.jsonl")
SHADOW_STATE_PATH = Path("feature_store/shadow_portfolio_state.json")


class ShadowPosition:
    """Represents a shadow (virtual) position."""
    
    def __init__(self, signal: Dict[str, Any], entry_price: float, timestamp: float):
        self.signal_id = signal.get('signal_id', f"shadow_{int(timestamp * 1000)}")
        self.symbol = signal.get('symbol', 'UNKNOWN')
        self.direction = signal.get('direction', 'LONG')
        self.size_usd = signal.get('size', signal.get('size_usd', 100.0))
        self.entry_price = entry_price
        self.entry_timestamp = timestamp
        self.exit_price = None
        self.exit_timestamp = None
        self.pnl_usd = 0.0
        self.pnl_pct = 0.0
        self.status = 'OPEN'  # OPEN, CLOSED
        self.blocked_reason = signal.get('blocked_reason')
        self.signal_metadata = signal.copy()
    
    def close(self, exit_price: float, exit_timestamp: float):
        """Close the shadow position."""
        if self.direction == 'LONG':
            self.pnl_pct = ((exit_price - self.entry_price) / self.entry_price) * 100
        else:  # SHORT
            self.pnl_pct = ((self.entry_price - exit_price) / self.entry_price) * 100
        
        self.pnl_usd = (self.pnl_pct / 100) * self.size_usd
        self.exit_price = exit_price
        self.exit_timestamp = exit_timestamp
        self.status = 'CLOSED'
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for logging."""
        return {
            'signal_id': self.signal_id,
            'symbol': self.symbol,
            'direction': self.direction,
            'size_usd': self.size_usd,
            'entry_price': self.entry_price,
            'entry_timestamp': self.entry_timestamp,
            'exit_price': self.exit_price,
            'exit_timestamp': self.exit_timestamp,
            'pnl_usd': self.pnl_usd,
            'pnl_pct': self.pnl_pct,
            'status': self.status,
            'blocked_reason': self.blocked_reason,
            'signal_metadata': self.signal_metadata
        }


class ShadowExecutionEngine:
    """
    Executes signals in shadow (virtual) portfolio and tracks outcomes.
    """
    
    def __init__(self):
        self.open_positions: Dict[str, ShadowPosition] = {}
        self.closed_positions: List[ShadowPosition] = []
        self._load_state()
    
    def _load_state(self):
        """Load shadow portfolio state."""
        if SHADOW_STATE_PATH.exists():
            try:
                with open(SHADOW_STATE_PATH, 'r') as f:
                    state = json.load(f)
                    # Restore open positions (simplified - in production, might want to load full state)
                    self.open_positions = {}
            except Exception as e:
                print(f"⚠️ [SHADOW] Error loading state: {e}")
    
    def _save_state(self):
        """Save shadow portfolio state."""
        SHADOW_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        
        state = {
            'open_count': len(self.open_positions),
            'closed_count': len(self.closed_positions),
            'timestamp': time.time()
        }
        
        with open(SHADOW_STATE_PATH, 'w') as f:
            json.dump(state, f, indent=2)
    
    def execute_signal(self, signal: Dict[str, Any], entry_price: float, blocked_reason: Optional[str] = None) -> str:
        """
        Execute a signal in the shadow portfolio.
        
        Args:
            signal: Signal dictionary
            entry_price: Entry price for the position
            blocked_reason: Reason why signal was blocked (if any)
        
        Returns:
            Position ID
        """
        timestamp = time.time()
        
        # Add blocked reason to signal metadata
        if blocked_reason:
            signal['blocked_reason'] = blocked_reason
        
        position = ShadowPosition(signal, entry_price, timestamp)
        self.open_positions[position.signal_id] = position
        
        # Log shadow execution
        self._log_shadow_result({
            'event': 'SHADOW_ENTRY',
            'signal_id': position.signal_id,
            'symbol': position.symbol,
            'direction': position.direction,
            'entry_price': entry_price,
            'size_usd': position.size_usd,
            'blocked_reason': blocked_reason,
            'timestamp': timestamp,
            'signal_metadata': signal
        })
        
        self._save_state()
        
        return position.signal_id
    
    def close_position(self, signal_id: str, exit_price: float) -> Optional[ShadowPosition]:
        """
        Close a shadow position.
        
        Args:
            signal_id: Position ID
            exit_price: Exit price
        
        Returns:
            Closed position or None if not found
        """
        if signal_id not in self.open_positions:
            return None
        
        position = self.open_positions[signal_id]
        timestamp = time.time()
        
        position.close(exit_price, timestamp)
        
        # Move to closed positions
        self.closed_positions.append(position)
        del self.open_positions[signal_id]
        
        # Log shadow exit
        self._log_shadow_result({
            'event': 'SHADOW_EXIT',
            'signal_id': position.signal_id,
            'symbol': position.symbol,
            'direction': position.direction,
            'entry_price': position.entry_price,
            'exit_price': exit_price,
            'pnl_usd': position.pnl_usd,
            'pnl_pct': position.pnl_pct,
            'hold_duration_seconds': timestamp - position.entry_timestamp,
            'timestamp': timestamp
        })
        
        # Keep only last 10,000 closed positions in memory
        if len(self.closed_positions) > 10000:
            self.closed_positions = self.closed_positions[-10000:]
        
        self._save_state()
        
        return position
    
    def _log_shadow_result(self, result: Dict[str, Any]):
        """Log shadow result to JSONL file."""
        SHADOW_RESULTS_PATH.parent.mkdir(parents=True, exist_ok=True)
        
        result['timestamp_iso'] = datetime.now(timezone.utc).isoformat()
        
        with open(SHADOW_RESULTS_PATH, 'a') as f:
            f.write(json.dumps(result) + '\n')
    
    def get_performance_summary(self, days: int = 7) -> Dict[str, Any]:
        """
        Get performance summary for shadow portfolio.
        
        Args:
            days: Number of days to analyze
        
        Returns:
            Performance summary dictionary
        """
        cutoff_time = time.time() - (days * 24 * 3600)
        
        # Filter closed positions in time window
        recent_closed = [
            p for p in self.closed_positions
            if p.exit_timestamp and p.exit_timestamp >= cutoff_time
        ]
        
        if not recent_closed:
            return {
                'total_trades': 0,
                'total_pnl_usd': 0.0,
                'total_pnl_pct': 0.0,
                'wins': 0,
                'losses': 0,
                'win_rate': 0.0,
                'avg_pnl_pct': 0.0,
                'days': days
            }
        
        total_pnl_usd = sum(p.pnl_usd for p in recent_closed)
        total_pnl_pct = sum(p.pnl_pct for p in recent_closed)
        wins = len([p for p in recent_closed if p.pnl_usd > 0])
        losses = len([p for p in recent_closed if p.pnl_usd < 0])
        
        return {
            'total_trades': len(recent_closed),
            'total_pnl_usd': round(total_pnl_usd, 2),
            'total_pnl_pct': round(total_pnl_pct, 2),
            'wins': wins,
            'losses': losses,
            'win_rate': round(wins / len(recent_closed), 3) if recent_closed else 0.0,
            'avg_pnl_pct': round(total_pnl_pct / len(recent_closed), 3) if recent_closed else 0.0,
            'days': days
        }
    
    def get_blocked_opportunity_cost(self, days: int = 7) -> Dict[str, Any]:
        """
        Analyze opportunity cost of blocked signals.
        
        Args:
            days: Number of days to analyze
        
        Returns:
            Opportunity cost analysis
        """
        cutoff_time = time.time() - (days * 24 * 3600)
        
        recent_closed = [
            p for p in self.closed_positions
            if p.exit_timestamp and p.exit_timestamp >= cutoff_time and p.blocked_reason
        ]
        
        if not recent_closed:
            return {
                'blocked_trades': 0,
                'missed_pnl_usd': 0.0,
                'blocked_reasons': {},
                'days': days
            }
        
        missed_pnl = sum(p.pnl_usd for p in recent_closed)
        
        # Group by blocked reason
        reason_groups = defaultdict(list)
        for p in recent_closed:
            reason_groups[p.blocked_reason].append(p)
        
        reason_analysis = {}
        for reason, positions in reason_groups.items():
            reason_pnl = sum(p.pnl_usd for p in positions)
            reason_analysis[reason] = {
                'count': len(positions),
                'total_pnl_usd': round(reason_pnl, 2),
                'avg_pnl_usd': round(reason_pnl / len(positions), 2) if positions else 0.0
            }
        
        return {
            'blocked_trades': len(recent_closed),
            'missed_pnl_usd': round(missed_pnl, 2),
            'blocked_reasons': reason_analysis,
            'days': days
        }


# Global instance
_shadow_engine: Optional[ShadowExecutionEngine] = None


def get_shadow_engine() -> ShadowExecutionEngine:
    """Get or create global shadow execution engine."""
    global _shadow_engine
    if _shadow_engine is None:
        _shadow_engine = ShadowExecutionEngine()
    return _shadow_engine


def compare_shadow_vs_live_performance(days: int = 7) -> Dict[str, Any]:
    """
    Compare shadow portfolio performance vs live portfolio.
    
    Args:
        days: Number of days to compare
    
    Returns:
        Comparison results with opportunity cost analysis
    """
    shadow_engine = get_shadow_engine()
    shadow_summary = shadow_engine.get_performance_summary(days)
    
    # Get live portfolio performance
    try:
        from src.position_manager import load_closed_positions
        closed_positions = load_closed_positions()
        
        cutoff_time = time.time() - (days * 24 * 3600)
        recent_live = [
            p for p in closed_positions
            if p.get('closed_ts') and p['closed_ts'] >= cutoff_time
        ]
        
        live_pnl_usd = sum(p.get('pnl', 0.0) for p in recent_live)
        live_trades = len(recent_live)
    except Exception as e:
        print(f"⚠️ [SHADOW] Error loading live positions: {e}")
        live_pnl_usd = 0.0
        live_trades = 0
    
    shadow_pnl_usd = shadow_summary.get('total_pnl_usd', 0.0)
    shadow_trades = shadow_summary.get('total_trades', 0)
    
    # Calculate opportunity cost
    opportunity_cost_pct = 0.0
    if live_pnl_usd != 0:
        opportunity_cost_pct = ((shadow_pnl_usd - live_pnl_usd) / abs(live_pnl_usd)) * 100
    
    comparison = {
        'days': days,
        'live': {
            'trades': live_trades,
            'pnl_usd': round(live_pnl_usd, 2)
        },
        'shadow': {
            'trades': shadow_trades,
            'pnl_usd': round(shadow_pnl_usd, 2),
            'win_rate': shadow_summary.get('win_rate', 0.0)
        },
        'opportunity_cost_usd': round(shadow_pnl_usd - live_pnl_usd, 2),
        'opportunity_cost_pct': round(opportunity_cost_pct, 2),
        'shadow_outperforming': shadow_pnl_usd > live_pnl_usd,
        'should_optimize_guards': opportunity_cost_pct > 15.0  # >15% outperformance triggers optimization
    }
    
    return comparison
