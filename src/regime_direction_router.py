#!/usr/bin/env python3
"""
REGIME-AWARE DIRECTION ROUTER - Dynamic Signal Direction Adaptation
====================================================================
Automatically adapts signal direction routing based on rolling window
performance analysis. Replaces static direction rules with dynamic,
data-driven direction decisions.

ARCHITECTURE:
1. Rolling Window EV Tracker - Tracks EV by signal × direction over 
   configurable window size (default: 300 samples)
2. Direction Decision Engine - Compares LONG vs SHORT EV with safety margins
3. Hysteresis System - Prevents flip-flopping with persistence requirements
4. Safety Rails - Min samples, cooldowns, max flips, manual overrides

INTEGRATION:
- conviction_gate.py calls get_allowed_directions() instead of static rules
- enhanced_signal_learner.py feeds data via update_signal_outcome()
- Logs all decisions to logs/direction_router.jsonl for analysis

RESEARCH BASIS:
- Hidden Markov Models for regime detection (QuantStart, State Street)
- Rolling window with EWMA for non-stationary markets (Macrosynergy)
- Hysteresis to prevent noise-driven flips (industry standard)
- Safety rails from quant best practices

Author: Trading Bot
Created: 2025-12-05
"""

import json
import os
from datetime import datetime, timedelta
from pathlib import Path
from collections import defaultdict
from typing import Dict, List, Optional, Any, Tuple, Set
from threading import Lock
import math


ROUTER_STATE_FILE = Path("feature_store/direction_router_state.json")
DIRECTION_RULES_FILE = Path("feature_store/direction_rules.json")
ROUTER_LOG_FILE = Path("logs/direction_router.jsonl")
SIGNAL_OUTCOMES_FILE = Path("logs/signal_outcomes.jsonl")

ROUTER_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
ROUTER_LOG_FILE.parent.mkdir(parents=True, exist_ok=True)


class RegimeDirectionRouter:
    """
    Dynamic direction router that adapts to market regimes.
    
    Tracks rolling window EV by signal × direction and automatically
    adjusts which directions each signal is allowed to contribute to.
    """
    
    WINDOW_SIZE = 300
    MIN_SAMPLES_PER_DIRECTION = 50
    EV_DELTA_THRESHOLD_BPS = 5.0
    PERSISTENCE_WINDOWS = 2
    MAX_FLIPS_PER_DAY = 2
    COOLDOWN_MINUTES = 30
    EWMA_ALPHA = 0.3
    
    ALL_SIGNALS = [
        'funding', 'liquidation', 'hurst', 'whale_flow', 'lead_lag',
        'oi_velocity', 'ofi_momentum', 'fear_greed', 'volatility_skew', 'oi_divergence'
    ]
    
    def __init__(self):
        self._lock = Lock()
        self.state = self._load_state()
        self._initialize_missing_signals()
        
    def _load_state(self) -> Dict:
        """Load or initialize router state."""
        try:
            if ROUTER_STATE_FILE.exists():
                data = json.loads(ROUTER_STATE_FILE.read_text())
                if self._validate_state(data):
                    return data
        except Exception as e:
            print(f"[DirectionRouter] Error loading state: {e}")
        
        return self._create_initial_state()
    
    def _validate_state(self, data: Dict) -> bool:
        """Validate state structure."""
        required = ['signal_directions', 'rolling_windows', 'flip_history', 
                    'pending_flips', 'manual_overrides', 'last_update']
        return all(k in data for k in required)
    
    def _create_initial_state(self) -> Dict:
        """Create fresh initial state."""
        initial_directions = {
            'funding': ['SHORT'],
            'liquidation': ['SHORT'],
            'hurst': ['SHORT'],
            'whale_flow': ['SHORT'],
            'lead_lag': ['LONG'],
            'oi_velocity': None,
            'ofi_momentum': None,
            'fear_greed': None,
            'volatility_skew': [],
            'oi_divergence': None,
        }
        
        return {
            'signal_directions': initial_directions,
            'rolling_windows': {sig: {'LONG': [], 'SHORT': []} for sig in self.ALL_SIGNALS},
            'ewma_ev': {sig: {'LONG': 0.0, 'SHORT': 0.0} for sig in self.ALL_SIGNALS},
            'flip_history': [],
            'pending_flips': {},
            'manual_overrides': {},
            'cooldown_until_global': None,
            'last_update': datetime.utcnow().isoformat(),
            'regime_summary': {},
            'version': '1.0.0'
        }
    
    def _initialize_missing_signals(self):
        """Ensure all signals have entries."""
        for sig in self.ALL_SIGNALS:
            if sig not in self.state['signal_directions']:
                self.state['signal_directions'][sig] = None
            if sig not in self.state['rolling_windows']:
                self.state['rolling_windows'][sig] = {'LONG': [], 'SHORT': []}
            if sig not in self.state['ewma_ev']:
                self.state['ewma_ev'][sig] = {'LONG': 0.0, 'SHORT': 0.0}
    
    def _save_state(self):
        """Save state to file."""
        try:
            self.state['last_update'] = datetime.utcnow().isoformat()
            tmp = ROUTER_STATE_FILE.with_suffix('.tmp')
            tmp.write_text(json.dumps(self.state, indent=2, default=str))
            tmp.rename(ROUTER_STATE_FILE)
            
            self._save_direction_rules()
        except Exception as e:
            print(f"[DirectionRouter] Error saving state: {e}")
    
    def _save_direction_rules(self):
        """Save direction rules to separate file for consumers."""
        try:
            rules = {
                'signal_directions': self.state.get('signal_directions', {}),
                'ewma_ev': self.state.get('ewma_ev', {}),
                'regime_summary': self.state.get('regime_summary', {}),
                'last_update': self.state.get('last_update'),
                'version': '1.0.0'
            }
            tmp = DIRECTION_RULES_FILE.with_suffix('.tmp')
            tmp.write_text(json.dumps(rules, indent=2, default=str))
            tmp.rename(DIRECTION_RULES_FILE)
        except Exception as e:
            print(f"[DirectionRouter] Error saving direction rules: {e}")
    
    def _log_event(self, event_type: str, data: Dict):
        """Log event to JSONL file."""
        try:
            entry = {
                'ts': datetime.utcnow().isoformat(),
                'event': event_type,
                **data
            }
            with open(ROUTER_LOG_FILE, 'a') as f:
                f.write(json.dumps(entry) + '\n')
        except Exception as e:
            print(f"[DirectionRouter] Error logging: {e}")
    
    def update_signal_outcome(self, signal_name: str, direction: str, ev_contribution: float):
        """
        Update rolling window with new signal outcome.
        Called by signal_outcome_tracker when outcomes are resolved.
        
        Args:
            signal_name: Name of the signal (e.g., 'funding', 'hurst')
            direction: 'LONG' or 'SHORT'
            ev_contribution: EV in decimal form (e.g., 0.001 = 10bps)
        """
        if signal_name not in self.ALL_SIGNALS:
            return
        if direction not in ('LONG', 'SHORT'):
            return
            
        with self._lock:
            ev_bps = ev_contribution * 10000
            
            window = self.state['rolling_windows'][signal_name][direction]
            window.append({
                'ev_bps': ev_bps,
                'ts': datetime.utcnow().isoformat()
            })
            
            if len(window) > self.WINDOW_SIZE:
                window.pop(0)
            
            old_ewma = self.state['ewma_ev'][signal_name][direction]
            new_ewma = self.EWMA_ALPHA * ev_bps + (1 - self.EWMA_ALPHA) * old_ewma
            self.state['ewma_ev'][signal_name][direction] = new_ewma
    
    def get_allowed_directions(self, signal_name: str) -> Optional[List[str]]:
        """
        Get allowed directions for a signal.
        This is the main integration point for conviction_gate.py.
        
        Returns:
            None = both directions allowed
            ['LONG'] = only LONG allowed
            ['SHORT'] = only SHORT allowed
            [] = signal disabled
        """
        if signal_name in self.state.get('manual_overrides', {}):
            override = self.state['manual_overrides'][signal_name]
            return override.get('directions')
        
        return self.state['signal_directions'].get(signal_name, None)
    
    def evaluate_direction_changes(self) -> List[Dict]:
        """
        Evaluate all signals for potential direction changes.
        Called periodically by the learning engine.
        
        Returns list of recommended changes with reasoning.
        """
        recommendations = []
        
        with self._lock:
            for signal_name in self.ALL_SIGNALS:
                if signal_name in self.state.get('manual_overrides', {}):
                    continue
                
                rec = self._evaluate_signal_direction(signal_name)
                if rec:
                    recommendations.append(rec)
            
            self._check_pending_flips()
            
        return recommendations
    
    def _evaluate_signal_direction(self, signal_name: str) -> Optional[Dict]:
        """Evaluate if a signal needs direction change."""
        windows = self.state['rolling_windows'][signal_name]
        ewma = self.state['ewma_ev'][signal_name]
        current_directions = self.state['signal_directions'].get(signal_name)
        
        long_samples = len(windows['LONG'])
        short_samples = len(windows['SHORT'])
        
        if long_samples < self.MIN_SAMPLES_PER_DIRECTION or short_samples < self.MIN_SAMPLES_PER_DIRECTION:
            return None
        
        long_ev = ewma['LONG']
        short_ev = ewma['SHORT']
        
        ev_delta = abs(long_ev - short_ev)
        
        if ev_delta < self.EV_DELTA_THRESHOLD_BPS:
            if current_directions is not None and len(current_directions) > 0:
                recommended = None
                reason = f"EV delta ({ev_delta:.1f}bps) below threshold - enabling BOTH directions"
            else:
                return None
        elif long_ev > short_ev:
            if long_ev > 0 and short_ev < 0:
                recommended = ['LONG']
                reason = f"LONG +{long_ev:.1f}bps vs SHORT {short_ev:.1f}bps - clear LONG edge"
            elif long_ev > 0 and short_ev > 0:
                recommended = None
                reason = f"Both positive (LONG +{long_ev:.1f}, SHORT +{short_ev:.1f}) - allow BOTH"
            else:
                recommended = ['LONG']
                reason = f"LONG {long_ev:.1f}bps less negative than SHORT {short_ev:.1f}bps"
        else:
            if short_ev > 0 and long_ev < 0:
                recommended = ['SHORT']
                reason = f"SHORT +{short_ev:.1f}bps vs LONG {long_ev:.1f}bps - clear SHORT edge"
            elif short_ev > 0 and long_ev > 0:
                recommended = None
                reason = f"Both positive (SHORT +{short_ev:.1f}, LONG +{long_ev:.1f}) - allow BOTH"
            else:
                recommended = ['SHORT']
                reason = f"SHORT {short_ev:.1f}bps less negative than LONG {long_ev:.1f}bps"
        
        if long_ev < -2 and short_ev < -2:
            recommended = []
            reason = f"Both directions negative (LONG {long_ev:.1f}, SHORT {short_ev:.1f}) - DISABLE"
        
        if self._directions_equal(recommended, current_directions):
            return None
        
        return {
            'signal': signal_name,
            'current': current_directions,
            'recommended': recommended,
            'reason': reason,
            'long_ev_bps': long_ev,
            'short_ev_bps': short_ev,
            'long_samples': long_samples,
            'short_samples': short_samples,
            'ev_delta': ev_delta
        }
    
    def _directions_equal(self, a: Optional[List[str]], b: Optional[List[str]]) -> bool:
        """Compare direction lists for equality."""
        if a is None and b is None:
            return True
        if a is None or b is None:
            return False
        return set(a) == set(b)
    
    def _check_pending_flips(self):
        """Check if pending flips have persisted long enough to apply."""
        now = datetime.utcnow()
        to_apply = []
        
        for signal_name, pending in list(self.state.get('pending_flips', {}).items()):
            persistence_count = pending.get('persistence_count', 0)
            cooldown_until = pending.get('cooldown_until')
            
            if cooldown_until:
                cooldown_dt = datetime.fromisoformat(cooldown_until)
                if now < cooldown_dt:
                    continue
            
            if persistence_count >= self.PERSISTENCE_WINDOWS:
                to_apply.append((signal_name, pending))
        
        for signal_name, pending in to_apply:
            self._apply_direction_change(signal_name, pending)
    
    def _apply_direction_change(self, signal_name: str, pending: Dict):
        """Apply a direction change after persistence requirements met."""
        if self._is_in_cooldown():
            self._log_event('flip_blocked_cooldown', {
                'signal': signal_name,
                'reason': 'global cooldown active',
                'cooldown_until': self.state.get('cooldown_until_global')
            })
            return
        
        if not self._can_flip_today():
            self._log_event('flip_blocked_daily_limit', {
                'signal': signal_name,
                'reason': 'global max_flips_per_day exceeded'
            })
            return
        
        old_directions = self.state['signal_directions'].get(signal_name)
        new_directions = pending['recommended']
        
        self.state['signal_directions'][signal_name] = new_directions
        
        self.state['flip_history'].append({
            'ts': datetime.utcnow().isoformat(),
            'signal': signal_name,
            'from': old_directions,
            'to': new_directions,
            'reason': pending['reason'],
            'long_ev': pending.get('long_ev_bps'),
            'short_ev': pending.get('short_ev_bps')
        })
        
        if len(self.state['flip_history']) > 1000:
            self.state['flip_history'] = self.state['flip_history'][-500:]
        
        if signal_name in self.state['pending_flips']:
            del self.state['pending_flips'][signal_name]
        
        cooldown_until = (datetime.utcnow() + timedelta(minutes=self.COOLDOWN_MINUTES)).isoformat()
        self.state['cooldown_until_global'] = cooldown_until
        
        for other_signal in self.state.get('pending_flips', {}):
            self.state['pending_flips'][other_signal]['cooldown_until'] = cooldown_until
        
        self._log_event('direction_change_applied', {
            'signal': signal_name,
            'from': old_directions,
            'to': new_directions,
            'reason': pending['reason'],
            'long_ev_bps': pending.get('long_ev_bps'),
            'short_ev_bps': pending.get('short_ev_bps'),
            'persistence_windows': pending.get('persistence_count', 0),
            'cooldown_until_global': cooldown_until
        })
        
        self._save_state()
        
        print(f"🔄 [DirectionRouter] {signal_name}: {old_directions} → {new_directions} ({pending['reason']})")
    
    def _is_in_cooldown(self) -> bool:
        """Check if we're in global cooldown period (no flips allowed)."""
        cooldown_until = self.state.get('cooldown_until_global')
        if not cooldown_until:
            return False
        
        try:
            cooldown_dt = datetime.fromisoformat(cooldown_until)
            return datetime.utcnow() < cooldown_dt
        except:
            return False
    
    def _can_flip_today(self) -> bool:
        """Check if we can flip any signal today (global daily limit)."""
        today = datetime.utcnow().date()
        flips_today = 0
        
        for flip in self.state.get('flip_history', []):
            try:
                flip_date = datetime.fromisoformat(flip['ts']).date()
                if flip_date == today:
                    flips_today += 1
            except:
                pass
        
        return flips_today < self.MAX_FLIPS_PER_DAY
    
    def get_daily_flip_count(self) -> int:
        """Get count of flips applied today (global)."""
        today = datetime.utcnow().date()
        flips_today = 0
        
        for flip in self.state.get('flip_history', []):
            try:
                flip_date = datetime.fromisoformat(flip['ts']).date()
                if flip_date == today:
                    flips_today += 1
            except:
                pass
        
        return flips_today
    
    def get_cooldown_status(self) -> Dict:
        """Get current cooldown status."""
        cooldown_until = self.state.get('cooldown_until_global')
        in_cooldown = self._is_in_cooldown()
        
        remaining_seconds = 0
        if in_cooldown and cooldown_until:
            try:
                cooldown_dt = datetime.fromisoformat(cooldown_until)
                remaining = cooldown_dt - datetime.utcnow()
                remaining_seconds = max(0, remaining.total_seconds())
            except:
                pass
        
        return {
            'in_cooldown': in_cooldown,
            'cooldown_until': cooldown_until,
            'remaining_seconds': remaining_seconds,
            'daily_flips': self.get_daily_flip_count(),
            'max_flips': self.MAX_FLIPS_PER_DAY
        }
    
    def queue_direction_change(self, signal_name: str, recommendation: Dict):
        """
        Queue a direction change for persistence checking.
        Called when evaluate_direction_changes finds a potential change.
        
        New pending flips inherit the global cooldown if one is active.
        """
        with self._lock:
            current_pending = self.state.get('pending_flips', {}).get(signal_name)
            
            cooldown_inherit = self.state.get('cooldown_until_global') if self._is_in_cooldown() else None
            
            if current_pending:
                if self._directions_equal(current_pending.get('recommended'), recommendation.get('recommended')):
                    current_pending['persistence_count'] = current_pending.get('persistence_count', 0) + 1
                    current_pending['last_seen'] = datetime.utcnow().isoformat()
                    current_pending['long_ev_bps'] = recommendation.get('long_ev_bps')
                    current_pending['short_ev_bps'] = recommendation.get('short_ev_bps')
                    if cooldown_inherit and not current_pending.get('cooldown_until'):
                        current_pending['cooldown_until'] = cooldown_inherit
                else:
                    self.state['pending_flips'][signal_name] = {
                        'recommended': recommendation['recommended'],
                        'reason': recommendation['reason'],
                        'persistence_count': 1,
                        'first_seen': datetime.utcnow().isoformat(),
                        'last_seen': datetime.utcnow().isoformat(),
                        'long_ev_bps': recommendation.get('long_ev_bps'),
                        'short_ev_bps': recommendation.get('short_ev_bps'),
                        'cooldown_until': cooldown_inherit
                    }
            else:
                self.state['pending_flips'][signal_name] = {
                    'recommended': recommendation['recommended'],
                    'reason': recommendation['reason'],
                    'persistence_count': 1,
                    'first_seen': datetime.utcnow().isoformat(),
                    'last_seen': datetime.utcnow().isoformat(),
                    'long_ev_bps': recommendation.get('long_ev_bps'),
                    'short_ev_bps': recommendation.get('short_ev_bps'),
                    'cooldown_until': cooldown_inherit
                }
            
            self._save_state()
    
    def set_manual_override(self, signal_name: str, directions: Optional[List[str]], reason: str = "Manual override"):
        """
        Set a manual override for a signal's direction.
        Overrides take precedence over dynamic routing.
        """
        with self._lock:
            if 'manual_overrides' not in self.state:
                self.state['manual_overrides'] = {}
            
            self.state['manual_overrides'][signal_name] = {
                'directions': directions,
                'reason': reason,
                'set_at': datetime.utcnow().isoformat()
            }
            
            self._log_event('manual_override_set', {
                'signal': signal_name,
                'directions': directions,
                'reason': reason
            })
            
            self._save_state()
    
    def clear_manual_override(self, signal_name: str):
        """Remove manual override for a signal."""
        with self._lock:
            if signal_name in self.state.get('manual_overrides', {}):
                del self.state['manual_overrides'][signal_name]
                self._log_event('manual_override_cleared', {'signal': signal_name})
                self._save_state()
    
    def get_regime_summary(self) -> Dict:
        """Get current regime summary for dashboard."""
        summary = {
            'current_directions': dict(self.state['signal_directions']),
            'ewma_ev': dict(self.state['ewma_ev']),
            'pending_flips': dict(self.state.get('pending_flips', {})),
            'manual_overrides': dict(self.state.get('manual_overrides', {})),
            'recent_flips': self.state.get('flip_history', [])[-10:],
            'sample_counts': {},
            'regime_bias': 'NEUTRAL',
            'last_update': self.state.get('last_update')
        }
        
        for sig in self.ALL_SIGNALS:
            windows = self.state['rolling_windows'].get(sig, {'LONG': [], 'SHORT': []})
            summary['sample_counts'][sig] = {
                'LONG': len(windows['LONG']),
                'SHORT': len(windows['SHORT'])
            }
        
        total_long_ev = sum(self.state['ewma_ev'].get(s, {}).get('LONG', 0) for s in self.ALL_SIGNALS)
        total_short_ev = sum(self.state['ewma_ev'].get(s, {}).get('SHORT', 0) for s in self.ALL_SIGNALS)
        
        if total_short_ev > total_long_ev + 20:
            summary['regime_bias'] = 'STRONG_SHORT'
        elif total_short_ev > total_long_ev + 5:
            summary['regime_bias'] = 'SHORT'
        elif total_long_ev > total_short_ev + 20:
            summary['regime_bias'] = 'STRONG_LONG'
        elif total_long_ev > total_short_ev + 5:
            summary['regime_bias'] = 'LONG'
        else:
            summary['regime_bias'] = 'NEUTRAL'
        
        summary['total_ev'] = {'LONG': total_long_ev, 'SHORT': total_short_ev}
        
        return summary
    
    def bootstrap_from_outcomes(self, max_records: int = 2000):
        """
        Bootstrap rolling windows from historical signal outcomes.
        Call this on startup to populate windows from existing data.
        
        Phase 4 Tri-Layer Architecture: Reads from SQLite with JSONL fallback.
        """
        from src.data_registry import DataRegistry as DR
        
        records = []
        
        try:
            signals = DR.get_signals_from_db(limit=max_records)
            if signals:
                print(f"[DirectionRouter] Bootstrapping from SQLite ({len(signals)} signals)...")
                records = signals
        except Exception as e:
            print(f"[DirectionRouter] SQLite read failed: {e}")
        
        if not records:
            if not SIGNAL_OUTCOMES_FILE.exists():
                print("[DirectionRouter] No signal outcomes to bootstrap from")
                return
            
            print(f"[DirectionRouter] Falling back to {SIGNAL_OUTCOMES_FILE}...")
            try:
                with open(SIGNAL_OUTCOMES_FILE, 'r') as f:
                    for line in f:
                        line = line.strip()
                        if line:
                            try:
                                records.append(json.loads(line))
                            except:
                                pass
            except Exception as e:
                print(f"[DirectionRouter] Error reading outcomes: {e}")
                return
        
        records = records[-max_records:]
        
        count = 0
        for record in records:
            signal_name = record.get('signal_name')
            direction = record.get('direction')
            ev = record.get('ev_contribution', 0)
            
            if signal_name and direction and ev is not None:
                self.update_signal_outcome(signal_name, direction, ev)
                count += 1
        
        self._save_state()
        print(f"[DirectionRouter] Bootstrapped {count} outcomes into rolling windows")
        
        self.evaluate_direction_changes()


_router_instance = None
_router_lock = Lock()
_bootstrap_deferred = True
_bootstrap_delay = 90


def get_direction_router(skip_bootstrap: bool = False) -> RegimeDirectionRouter:
    """Get singleton direction router instance.
    
    Args:
        skip_bootstrap: If True, skip bootstrap on first access (defer to background)
    """
    global _router_instance, _bootstrap_deferred
    
    with _router_lock:
        if _router_instance is None:
            _router_instance = RegimeDirectionRouter()
            if not skip_bootstrap and not _bootstrap_deferred:
                _router_instance.bootstrap_from_outcomes()
            elif _bootstrap_deferred:
                import threading
                def deferred_bootstrap():
                    import time
                    time.sleep(_bootstrap_delay)
                    print(f"[DirectionRouter] Running deferred bootstrap...")
                    _router_instance.bootstrap_from_outcomes()
                threading.Thread(target=deferred_bootstrap, daemon=True, name="DirectionRouterBootstrap").start()
                _bootstrap_deferred = False
        return _router_instance


def get_allowed_directions(signal_name: str) -> Optional[List[str]]:
    """
    Convenience function for conviction_gate integration.
    Returns allowed directions for a signal.
    """
    router = get_direction_router()
    return router.get_allowed_directions(signal_name)


def update_signal_outcome(signal_name: str, direction: str, ev_contribution: float):
    """
    Convenience function for signal_outcome_tracker integration.
    Updates rolling window with new outcome.
    """
    router = get_direction_router()
    router.update_signal_outcome(signal_name, direction, ev_contribution)


def run_direction_evaluation() -> List[Dict]:
    """
    Run direction evaluation and queue changes.
    Called periodically by learning engine.
    """
    router = get_direction_router()
    recommendations = router.evaluate_direction_changes()
    
    for rec in recommendations:
        router.queue_direction_change(rec['signal'], rec)
    
    return recommendations


if __name__ == "__main__":
    print("=" * 70)
    print("REGIME-AWARE DIRECTION ROUTER - Manual Run")
    print("=" * 70)
    
    router = get_direction_router()
    router.bootstrap_from_outcomes(max_records=3000)
    
    recommendations = router.evaluate_direction_changes()
    
    print(f"\nFound {len(recommendations)} direction change recommendations:")
    for rec in recommendations:
        print(f"  {rec['signal']}: {rec['current']} → {rec['recommended']}")
        print(f"    LONG: {rec['long_ev_bps']:+.1f}bps ({rec['long_samples']} samples)")
        print(f"    SHORT: {rec['short_ev_bps']:+.1f}bps ({rec['short_samples']} samples)")
        print(f"    Reason: {rec['reason']}")
        print()
    
    summary = router.get_regime_summary()
    print(f"\nCurrent Regime Bias: {summary['regime_bias']}")
    print(f"Total EV: LONG={summary['total_ev']['LONG']:+.1f}bps, SHORT={summary['total_ev']['SHORT']:+.1f}bps")
    print(f"\nCurrent Direction Rules:")
    for sig, dirs in summary['current_directions'].items():
        print(f"  {sig}: {dirs}")
