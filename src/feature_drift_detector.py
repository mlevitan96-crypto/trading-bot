#!/usr/bin/env python3
"""
Feature Drift & Stationarity Monitor
=====================================

Implements CUSUM (Cumulative Sum) algorithm to detect shifts in signal performance.
Automatically quarantines failing signals by setting their multiplier to 0.1x until
distribution stabilizes for 48 hours.
"""

import json
import os
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple
from collections import deque
import numpy as np

SIGNAL_WEIGHTS_GATE_FILE = Path("feature_store/signal_weights_gate.json")
DRIFT_STATE_PATH = Path("feature_store/feature_drift_state.json")
DRIFT_LOG_PATH = Path("logs/feature_drift_log.jsonl")
SIGNAL_OUTCOMES_FILE = Path("logs/signal_outcomes.jsonl")

# Signal component names (22 signals as specified)
SIGNAL_COMPONENTS = [
    'liquidation', 'funding', 'oi_velocity', 'whale_flow', 'ofi_momentum',
    'fear_greed', 'hurst', 'lead_lag', 'volatility_skew', 'oi_divergence',
    'ensemble', 'mtf_alignment', 'regime', 'market_intel', 'volume',
    'momentum', 'session', 'unrealized_pnl', 'mtf_exit_signal', 'regime_shift',
    'hold_duration', 'trailing_stop'
]

QUARANTINE_MULTIPLIER = 0.1  # Quarantine signal weight multiplier
QUARANTINE_DURATION_HOURS = 48  # Hours before signal can be restored
DRIFT_Z_SCORE_THRESHOLD = 2.0  # Z-score threshold for drift detection
DRIFT_WIN_RATE_THRESHOLD = 0.35  # Win rate threshold (35%)


class CUSUMDetector:
    """
    CUSUM (Cumulative Sum) detector for mean shift detection.
    """
    
    def __init__(self, h: float = 5.0, k: float = 0.5):
        """
        Initialize CUSUM detector.
        
        Args:
            h: Decision threshold (higher = less sensitive)
            k: Reference value (typically 0.5 * standard deviation)
        """
        self.h = h
        self.k = k
        self.s_plus = 0.0  # Upper cumulative sum
        self.s_minus = 0.0  # Lower cumulative sum
        self.mean = 0.0
        self.std = 1.0
        self.sample_count = 0
    
    def update(self, value: float) -> Tuple[bool, str]:
        """
        Update detector with new value.
        
        Args:
            value: New observation
        
        Returns:
            (drift_detected, direction) where direction is 'up' or 'down'
        """
        self.sample_count += 1
        
        # Update running statistics (simple incremental update)
        if self.sample_count == 1:
            self.mean = value
            self.std = 1.0
        else:
            # Simple running mean and std (for efficiency)
            old_mean = self.mean
            self.mean = old_mean + (value - old_mean) / self.sample_count
            # Approximate std (not exact but good enough for CUSUM)
            if self.sample_count > 10:
                # Use recent samples for std estimate
                self.std = abs(value - self.mean) * 1.25  # Rough approximation
        
        # Standardize value
        if self.std > 0:
            z = (value - self.mean) / self.std
        else:
            z = 0.0
        
        # Update CUSUM statistics
        self.s_plus = max(0, self.s_plus + z - self.k)
        self.s_minus = max(0, self.s_minus - z - self.k)
        
        # Check for drift
        if self.s_plus > self.h:
            return True, 'up'
        elif self.s_minus > self.h:
            return True, 'down'
        
        return False, 'none'
    
    def reset(self):
        """Reset detector state."""
        self.s_plus = 0.0
        self.s_minus = 0.0


class SignalDriftMonitor:
    """
    Monitors signal components for drift and manages quarantine.
    """
    
    def __init__(self):
        self.detectors: Dict[str, CUSUMDetector] = {}
        self.performance_history: Dict[str, deque] = {}
        self.quarantine_state: Dict[str, Dict] = {}  # signal_name -> {quarantined_at, reason}
        self._load_state()
    
    def _load_state(self):
        """Load drift detector state."""
        if DRIFT_STATE_PATH.exists():
            try:
                with open(DRIFT_STATE_PATH, 'r') as f:
                    state = json.load(f)
                    self.quarantine_state = state.get('quarantine_state', {})
            except Exception as e:
                print(f"⚠️ [DRIFT] Error loading state: {e}")
    
    def _save_state(self):
        """Save drift detector state."""
        DRIFT_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        
        state = {
            'quarantine_state': self.quarantine_state,
            'timestamp': time.time()
        }
        
        with open(DRIFT_STATE_PATH, 'w') as f:
            json.dump(state, f, indent=2)
    
    def _log_drift_event(self, signal_name: str, event_type: str, data: Dict):
        """Log drift detection event."""
        DRIFT_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        
        entry = {
            'timestamp': time.time(),
            'timestamp_iso': datetime.now(timezone.utc).isoformat(),
            'signal_name': signal_name,
            'event_type': event_type,
            **data
        }
        
        with open(DRIFT_LOG_PATH, 'a') as f:
            f.write(json.dumps(entry) + '\n')
    
    def _load_signal_outcomes(self, hours: int = 168) -> List[Dict]:
        """Load recent signal outcomes from log."""
        cutoff_time = time.time() - (hours * 3600)
        outcomes = []
        
        if not SIGNAL_OUTCOMES_FILE.exists():
            return outcomes
        
        try:
            with open(SIGNAL_OUTCOMES_FILE, 'r') as f:
                for line in f:
                    try:
                        entry = json.loads(line.strip())
                        ts = entry.get('ts', entry.get('timestamp', 0))
                        if isinstance(ts, str):
                            # Try to parse ISO format
                            try:
                                dt = datetime.fromisoformat(ts.replace('Z', '+00:00'))
                                ts = dt.timestamp()
                            except:
                                continue
                        
                        if ts >= cutoff_time:
                            outcomes.append(entry)
                    except:
                        continue
        except Exception as e:
            print(f"⚠️ [DRIFT] Error loading signal outcomes: {e}")
        
        return outcomes
    
    def _calculate_signal_performance(self, signal_name: str, outcomes: List[Dict]) -> Dict[str, Any]:
        """
        Calculate performance metrics for a signal.
        
        Args:
            signal_name: Name of signal component
            outcomes: List of signal outcome records
        
        Returns:
            Performance metrics dict
        """
        # Filter outcomes for this signal
        signal_outcomes = [
            o for o in outcomes
            if o.get('signal_name') == signal_name
        ]
        
        if len(signal_outcomes) < 10:
            return {
                'sample_count': len(signal_outcomes),
                'win_rate': 0.0,
                'avg_return': 0.0,
                'z_score': 0.0,
                'sufficient_data': False
            }
        
        # Calculate returns (assuming outcome has return_pct or similar)
        returns = []
        wins = 0
        
        for outcome in signal_outcomes:
            # Try different field names for return
            ret = outcome.get('return_pct', outcome.get('pnl_pct', outcome.get('outcome_pct', 0.0)))
            returns.append(ret)
            if ret > 0:
                wins += 1
        
        if not returns:
            return {
                'sample_count': 0,
                'win_rate': 0.0,
                'avg_return': 0.0,
                'z_score': 0.0,
                'sufficient_data': False
            }
        
        returns_arr = np.array(returns)
        win_rate = wins / len(returns)
        avg_return = np.mean(returns_arr)
        std_return = np.std(returns_arr) if len(returns_arr) > 1 else 1.0
        
        # Z-score (how many standard deviations from zero)
        z_score = abs(avg_return / std_return) if std_return > 0 else 0.0
        
        return {
            'sample_count': len(returns),
            'win_rate': round(win_rate, 3),
            'avg_return': round(avg_return, 4),
            'z_score': round(z_score, 3),
            'sufficient_data': True
        }
    
    def detect_drift(self, hours: int = 168) -> Dict[str, Any]:
        """
        Detect drift in signal components.
        
        Args:
            hours: Hours of history to analyze
        
        Returns:
            Drift detection results
        """
        outcomes = self._load_signal_outcomes(hours)
        
        drift_results = {}
        quarantined_signals = []
        restored_signals = []
        
        for signal_name in SIGNAL_COMPONENTS:
            # Calculate performance
            perf = self._calculate_signal_performance(signal_name, outcomes)
            
            if not perf.get('sufficient_data'):
                continue
            
            win_rate = perf['win_rate']
            z_score = perf['z_score']
            
            # Check for drift failure condition
            is_drift_failure = (z_score > DRIFT_Z_SCORE_THRESHOLD and 
                               win_rate < DRIFT_WIN_RATE_THRESHOLD)
            
            # Initialize detector if needed
            if signal_name not in self.detectors:
                self.detectors[signal_name] = CUSUMDetector()
                if signal_name not in self.performance_history:
                    self.performance_history[signal_name] = deque(maxlen=1000)
            
            # Update performance history
            self.performance_history[signal_name].append(perf['avg_return'])
            
            # Update CUSUM detector with average return
            detector = self.detectors[signal_name]
            drift_detected, direction = detector.update(perf['avg_return'])
            
            # Check if signal should be quarantined
            currently_quarantined = signal_name in self.quarantine_state
            
            if is_drift_failure or drift_detected:
                if not currently_quarantined:
                    # Quarantine signal
                    self.quarantine_state[signal_name] = {
                        'quarantined_at': time.time(),
                        'reason': 'drift_failure' if is_drift_failure else f'cusum_{direction}',
                        'z_score': z_score,
                        'win_rate': win_rate
                    }
                    quarantined_signals.append(signal_name)
                    
                    self._log_drift_event(signal_name, 'QUARANTINED', {
                        'z_score': z_score,
                        'win_rate': win_rate,
                        'reason': self.quarantine_state[signal_name]['reason']
                    })
            else:
                # Check if quarantined signal should be restored
                if currently_quarantined:
                    quarantine_time = self.quarantine_state[signal_name].get('quarantined_at', 0)
                    hours_quarantined = (time.time() - quarantine_time) / 3600
                    
                    if hours_quarantined >= QUARANTINE_DURATION_HOURS:
                        # Restore signal
                        del self.quarantine_state[signal_name]
                        restored_signals.append(signal_name)
                        
                        self._log_drift_event(signal_name, 'RESTORED', {
                            'hours_quarantined': round(hours_quarantined, 2),
                            'current_z_score': z_score,
                            'current_win_rate': win_rate
                        })
            
            drift_results[signal_name] = {
                'performance': perf,
                'drift_detected': drift_detected,
                'drift_direction': direction,
                'is_drift_failure': is_drift_failure,
                'quarantined': signal_name in self.quarantine_state
            }
        
        # Save state
        self._save_state()
        
        return {
            'drift_results': drift_results,
            'quarantined_signals': quarantined_signals,
            'restored_signals': restored_signals,
            'total_quarantined': len(self.quarantine_state)
        }
    
    def apply_quarantine_multipliers(self) -> Dict[str, float]:
        """
        Apply quarantine multipliers to signal weights.
        
        Returns:
            Dict mapping signal names to multipliers (0.1 for quarantined, 1.0 for normal)
        """
        multipliers = {}
        
        for signal_name in SIGNAL_COMPONENTS:
            if signal_name in self.quarantine_state:
                multipliers[signal_name] = QUARANTINE_MULTIPLIER
            else:
                multipliers[signal_name] = 1.0
        
        return multipliers
    
    def update_signal_weights(self):
        """
        Update signal weights file with quarantine multipliers.
        """
        multipliers = self.apply_quarantine_multipliers()
        
        # Load current weights
        if SIGNAL_WEIGHTS_GATE_FILE.exists():
            try:
                with open(SIGNAL_WEIGHTS_GATE_FILE, 'r') as f:
                    weights_data = json.load(f)
            except:
                weights_data = {'weights': {}}
        else:
            weights_data = {'weights': {}}
        
        original_weights = weights_data.get('weights', {})
        updated_weights = {}
        
        # Apply multipliers
        for signal_name, multiplier in multipliers.items():
            original_weight = original_weights.get(signal_name, 0.1)
            updated_weight = original_weight * multiplier
            updated_weights[signal_name] = round(updated_weight, 6)
        
        # Update weights file
        weights_data['weights'] = updated_weights
        weights_data['drift_quarantine_applied'] = True
        weights_data['drift_quarantine_timestamp'] = time.time()
        weights_data['quarantined_signals'] = list(self.quarantine_state.keys())
        
        SIGNAL_WEIGHTS_GATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(SIGNAL_WEIGHTS_GATE_FILE, 'w') as f:
            json.dump(weights_data, f, indent=2)
        
        return {
            'updated': len(multipliers),
            'quarantined': len(self.quarantine_state),
            'multipliers_applied': multipliers
        }


# Global instance
_drift_monitor: Optional[SignalDriftMonitor] = None


def get_drift_monitor() -> SignalDriftMonitor:
    """Get or create global drift monitor instance."""
    global _drift_monitor
    if _drift_monitor is None:
        _drift_monitor = SignalDriftMonitor()
    return _drift_monitor


def run_drift_detection() -> Dict[str, Any]:
    """
    Run drift detection and update signal weights.
    
    Returns:
        Drift detection and update results
    """
    monitor = get_drift_monitor()
    
    # Detect drift
    detection_results = monitor.detect_drift(hours=168)  # 7 days
    
    # Update signal weights
    update_results = monitor.update_signal_weights()
    
    return {
        'detection': detection_results,
        'update': update_results
    }

