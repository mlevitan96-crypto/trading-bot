"""
SIGNAL OUTCOME TRACKER - Track Signal Predictions vs Actual Price Outcomes
============================================================================
Logs every signal with price predictions and tracks actual outcomes at
1m, 5m, 15m, 30m, 1h to learn which signals predict profitable moves.

CORE FUNCTIONALITY:
1. Log signals with: timestamp, symbol, signal_name, direction, confidence, price
2. Store pending signals in memory with expected resolution times
3. Resolve signals by fetching actual prices at forward intervals
4. Calculate: did direction match price move? How much did price move?
5. Write completed outcomes to logs/signal_outcomes.jsonl
6. Aggregate stats to feature_store/signal_stats.json
7. Feed outcomes to RegimeDirectionRouter for dynamic direction adaptation

SIGNAL NAMES:
- funding: Funding rate extremes
- whale_flow: Whale exchange flows
- oi_velocity: Open interest velocity
- liquidation: Liquidation cascade detection
- ofi_momentum: Order flow momentum
- fear_greed: Fear & Greed contrarian

USAGE:
    from src.signal_outcome_tracker import signal_tracker
    
    signal_tracker.log_signal('BTCUSDT', 'funding', 'LONG', 0.85, 97500.00, signal_data)
"""

import os
import json
import time
import threading
import requests
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, Any, Optional, List, Tuple
from collections import defaultdict
from dataclasses import dataclass, field, asdict
import uuid


OUTCOMES_LOG = Path("logs/signal_outcomes.jsonl")
PENDING_SIGNALS_FILE = Path("feature_store/pending_signals.json")
SIGNAL_STATS_FILE = Path("feature_store/signal_stats.json")

OUTCOMES_LOG.parent.mkdir(parents=True, exist_ok=True)
PENDING_SIGNALS_FILE.parent.mkdir(parents=True, exist_ok=True)

HORIZONS = ['1m', '5m', '15m', '30m', '1h']
HORIZON_SECONDS = {
    '1m': 60,
    '5m': 300,
    '15m': 900,
    '30m': 1800,
    '1h': 3600
}

VALID_SIGNAL_NAMES = {'funding', 'whale_flow', 'oi_velocity', 'liquidation', 'ofi_momentum', 'fear_greed', 'hurst', 'lead_lag', 'volatility_skew', 'oi_divergence', 'ensemble'}
VALID_DIRECTIONS = {'LONG', 'SHORT', 'NEUTRAL'}

BINANCE_PRICE_URL = "https://api.binance.us/api/v3/ticker/price"


@dataclass
class PendingSignal:
    """A signal awaiting price resolution at various horizons."""
    id: str
    ts: str
    ts_epoch: float
    symbol: str
    signal_name: str
    direction: str
    confidence: float
    price_at_signal: float
    signal_data: Dict[str, Any] = field(default_factory=dict)
    prices: Dict[str, Optional[float]] = field(default_factory=dict)
    resolved_horizons: List[str] = field(default_factory=list)
    
    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'PendingSignal':
        return cls(
            id=data.get('id', str(uuid.uuid4())),
            ts=data.get('ts', ''),
            ts_epoch=data.get('ts_epoch', time.time()),
            symbol=data.get('symbol', ''),
            signal_name=data.get('signal_name', ''),
            direction=data.get('direction', 'NEUTRAL'),
            confidence=data.get('confidence', 0.0),
            price_at_signal=data.get('price_at_signal', 0.0),
            signal_data=data.get('signal_data', {}),
            prices=data.get('prices', {}),
            resolved_horizons=data.get('resolved_horizons', [])
        )
    
    def is_fully_resolved(self) -> bool:
        """Check if all horizons have been resolved."""
        return all(h in self.resolved_horizons for h in HORIZONS)
    
    def get_next_resolution_time(self) -> Optional[float]:
        """Get the next horizon that needs resolution."""
        for horizon in HORIZONS:
            if horizon not in self.resolved_horizons:
                target_time = self.ts_epoch + HORIZON_SECONDS[horizon]
                return target_time
        return None


class SignalOutcomeTracker:
    """
    Tracks signal outcomes by logging signals and resolving them at
    multiple forward time horizons.
    """
    
    def __init__(self):
        self.pending_signals: Dict[str, PendingSignal] = {}
        self._lock = threading.Lock()
        self._load_pending_signals()
        self._price_cache: Dict[str, Tuple[float, float]] = {}
        self._cache_ttl = 5.0
    
    def _load_pending_signals(self):
        """Load pending signals from disk."""
        try:
            if PENDING_SIGNALS_FILE.exists():
                data = json.loads(PENDING_SIGNALS_FILE.read_text())
                for signal_id, signal_data in data.items():
                    # Ensure ts_epoch is a float (UTC epoch seconds)
                    if 'ts_epoch' in signal_data:
                        signal_data['ts_epoch'] = float(signal_data['ts_epoch'])
                    else:
                        # If missing, try to parse from ts string
                        if 'ts' in signal_data:
                            try:
                                from datetime import datetime
                                dt = datetime.fromisoformat(signal_data['ts'].replace('Z', '+00:00'))
                                signal_data['ts_epoch'] = dt.timestamp()
                            except:
                                signal_data['ts_epoch'] = time.time()
                        else:
                            signal_data['ts_epoch'] = time.time()
                    
                    self.pending_signals[signal_id] = PendingSignal.from_dict(signal_data)
                print(f"[SignalTracker] Loaded {len(self.pending_signals)} pending signals")
        except Exception as e:
            print(f"[SignalTracker] Error loading pending signals: {e}")
            import traceback
            traceback.print_exc()
            self.pending_signals = {}
    
    def _save_pending_signals(self):
        """Save pending signals to disk."""
        try:
            data = {sid: sig.to_dict() for sid, sig in self.pending_signals.items()}
            PENDING_SIGNALS_FILE.write_text(json.dumps(data, indent=2))
        except Exception as e:
            print(f"[SignalTracker] Error saving pending signals: {e}")
    
    def _get_current_price(self, symbol: str) -> Optional[float]:
        """
        Get current price for a symbol from Binance.US.
        Uses caching to avoid excessive API calls.
        """
        now = time.time()
        
        if symbol in self._price_cache:
            cached_price, cached_time = self._price_cache[symbol]
            if now - cached_time < self._cache_ttl:
                return cached_price
        
        clean_symbol = symbol.replace('-', '').upper()
        if not clean_symbol.endswith('USDT'):
            clean_symbol = clean_symbol + 'USDT'
        
        try:
            response = requests.get(
                BINANCE_PRICE_URL,
                params={"symbol": clean_symbol},
                timeout=5
            )
            response.raise_for_status()
            data = response.json()
            price = float(data["price"])
            self._price_cache[symbol] = (price, now)
            return price
        except Exception as e:
            print(f"[SignalTracker] Error fetching price for {symbol}: {e}")
            if symbol in self._price_cache:
                return self._price_cache[symbol][0]
            return None
    
    def log_signal(
        self,
        symbol: str,
        signal_name: str,
        direction: str,
        confidence: float,
        price: float,
        signal_data: Optional[Dict[str, Any]] = None
    ) -> str:
        """
        Log a new signal for outcome tracking.
        
        Args:
            symbol: Trading pair (e.g., 'BTCUSDT')
            signal_name: One of: funding, whale_flow, oi_velocity, liquidation, ofi_momentum, fear_greed
            direction: LONG, SHORT, or NEUTRAL
            confidence: Confidence score 0-1
            price: Price at signal time
            signal_data: Optional additional signal metadata
        
        Returns:
            Signal ID for tracking
        """
        if signal_name not in VALID_SIGNAL_NAMES:
            print(f"[SignalTracker] Warning: Unknown signal name '{signal_name}'")
        
        direction = direction.upper()
        if direction not in VALID_DIRECTIONS:
            print(f"[SignalTracker] Warning: Invalid direction '{direction}', defaulting to NEUTRAL")
            direction = 'NEUTRAL'
        
        if direction == 'NEUTRAL':
            return ''
        
        clean_symbol = symbol.replace('-', '').upper()
        if not clean_symbol.endswith('USDT'):
            clean_symbol = clean_symbol + 'USDT'
        
        signal_id = str(uuid.uuid4())[:8]
        # Use time.time() which returns UTC epoch seconds (timezone-independent)
        now = time.time()
        # Ensure now is a float
        now = float(now)
        ts = datetime.utcnow().isoformat() + 'Z'
        
        pending = PendingSignal(
            id=signal_id,
            ts=ts,
            ts_epoch=now,  # UTC epoch seconds (timezone-independent)
            symbol=clean_symbol,
            signal_name=signal_name,
            direction=direction,
            confidence=max(0.0, min(1.0, confidence)),
            price_at_signal=price,
            signal_data=signal_data or {},
            prices={},
            resolved_horizons=[]
        )
        
        with self._lock:
            self.pending_signals[signal_id] = pending
            self._save_pending_signals()
        
        print(f"[SignalTracker] Logged signal {signal_id}: {clean_symbol} {signal_name} {direction} conf={confidence:.2f} price={price:.2f}")
        return signal_id
    
    def resolve_pending_signals(self) -> int:
        """
        Check all pending signals and resolve those that have passed their horizon times.
        Should be called every minute (or more frequently).
        
        All time comparisons use UTC epoch seconds (time.time()) to avoid timezone issues.
        
        Returns:
            Number of signals fully resolved
        """
        # Use UTC epoch time (time.time() returns seconds since UTC epoch)
        now = time.time()
        resolved_count = 0
        signals_to_remove = []
        total_pending = len(self.pending_signals)
        horizons_resolved_this_cycle = 0
        
        if total_pending == 0:
            return 0
        
        with self._lock:
            for signal_id, signal in list(self.pending_signals.items()):
                try:
                    # Ensure ts_epoch is a float (UTC epoch seconds)
                    if not isinstance(signal.ts_epoch, (int, float)):
                        print(f"[SignalTracker] Warning: Invalid ts_epoch type for signal {signal_id}: {type(signal.ts_epoch)}, fixing...")
                        # Try to parse from ts string if available
                        if signal.ts:
                            try:
                                from datetime import datetime
                                dt = datetime.fromisoformat(signal.ts.replace('Z', '+00:00'))
                                signal.ts_epoch = dt.timestamp()
                            except:
                                # Fallback to current time if parsing fails
                                signal.ts_epoch = now
                        else:
                            signal.ts_epoch = now
                    
                    signal.ts_epoch = float(signal.ts_epoch)  # Ensure it's a float
                    
                    # Calculate signal age for debugging
                    signal_age_seconds = now - signal.ts_epoch
                    
                    for horizon in HORIZONS:
                        if horizon in signal.resolved_horizons:
                            continue
                        
                        # Calculate target time using UTC epoch (ts_epoch is already UTC epoch)
                        target_time = signal.ts_epoch + HORIZON_SECONDS[horizon]
                        time_until_target = target_time - now
                        
                        # Debug logging for 1h horizon (the problematic one)
                        if horizon == '1h':
                            print(f"[SignalTracker] Checking 1h horizon for {signal_id}: ts_epoch={signal.ts_epoch:.0f}, target_time={target_time:.0f}, now={now:.0f}, time_until={time_until_target:.0f}s, age={signal_age_seconds:.0f}s")
                        
                        if now >= target_time:
                            price = self._get_current_price(signal.symbol)
                            if price is not None:
                                signal.prices[horizon] = price
                                signal.resolved_horizons.append(horizon)
                                horizons_resolved_this_cycle += 1
                                print(f"[SignalTracker] Resolved {signal_id} {horizon}: {price:.2f} (signal: {signal.symbol} {signal.signal_name} {signal.direction}, age={signal_age_seconds:.0f}s)")
                            else:
                                print(f"[SignalTracker] Warning: Could not fetch price for {signal.symbol} at {horizon} horizon")
                        elif horizon == '1h':
                            # Log why 1h is not resolving
                            print(f"[SignalTracker] 1h horizon not ready for {signal_id}: need {time_until_target:.0f}s more (target={target_time:.0f}, now={now:.0f})")
                    
                    if signal.is_fully_resolved():
                        self._write_outcome(signal)
                        signals_to_remove.append(signal_id)
                        resolved_count += 1
                        print(f"[SignalTracker] Fully resolved signal {signal_id}: {signal.symbol} {signal.signal_name} {signal.direction} - wrote to signal_outcomes.jsonl")
                
                except Exception as e:
                    print(f"[SignalTracker] Error resolving signal {signal_id}: {e}")
                    import traceback
                    traceback.print_exc()
            
            for signal_id in signals_to_remove:
                del self.pending_signals[signal_id]
            
            if signals_to_remove:
                self._save_pending_signals()
                print(f"[SignalTracker] Saved pending_signals.json (removed {len(signals_to_remove)} resolved signals)")
            
            self._cleanup_stale_signals()
        
        if resolved_count > 0:
            print(f"[SignalTracker] Resolved {resolved_count} signal(s) this cycle, {horizons_resolved_this_cycle} horizon(s) resolved, {len(self.pending_signals)} still pending")
        elif horizons_resolved_this_cycle > 0:
            print(f"[SignalTracker] Resolved {horizons_resolved_this_cycle} horizon(s) this cycle, {len(self.pending_signals)} signals still pending")
        
        return resolved_count
    
    def _cleanup_stale_signals(self):
        """Remove signals older than 2 hours that haven't been resolved."""
        # Use UTC epoch time (time.time() returns seconds since UTC epoch)
        now = float(time.time())
        max_age = 7200
        
        stale_ids = [
            sid for sid, sig in self.pending_signals.items()
            if (now - sig.ts_epoch) > max_age
        ]
        
        for signal_id in stale_ids:
            signal = self.pending_signals[signal_id]
            if signal.prices:
                self._write_outcome(signal, partial=True)
            del self.pending_signals[signal_id]
            print(f"[SignalTracker] Cleaned up stale signal {signal_id}")
    
    def _calculate_returns_and_hits(
        self,
        signal: PendingSignal
    ) -> Tuple[Dict[str, float], Dict[str, bool]]:
        """
        Calculate returns and hit rates for a signal.
        
        Returns:
            (returns_dict, hits_dict)
        """
        returns = {}
        hits = {}
        
        base_price = signal.price_at_signal
        if base_price <= 0:
            return {}, {}
        
        for horizon in HORIZONS:
            forward_price = signal.prices.get(horizon)
            if forward_price is None:
                continue
            
            ret = (forward_price - base_price) / base_price
            returns[horizon] = round(ret, 6)
            
            if signal.direction == 'LONG':
                hits[horizon] = ret > 0
            elif signal.direction == 'SHORT':
                hits[horizon] = ret < 0
            else:
                hits[horizon] = False
        
        return returns, hits
    
    def _calculate_ev_contribution(
        self,
        returns: Dict[str, float],
        hits: Dict[str, bool],
        confidence: float
    ) -> float:
        """
        Calculate expected value contribution of this signal.
        Uses weighted average of returns across horizons.
        """
        if not returns:
            return 0.0
        
        horizon_weights = {'1m': 0.05, '5m': 0.15, '15m': 0.25, '30m': 0.25, '1h': 0.30}
        
        weighted_return = 0.0
        total_weight = 0.0
        
        for horizon, ret in returns.items():
            weight = horizon_weights.get(horizon, 0.1)
            if hits.get(horizon, False):
                weighted_return += abs(ret) * weight
            else:
                weighted_return -= abs(ret) * weight
            total_weight += weight
        
        if total_weight > 0:
            avg_return = weighted_return / total_weight
        else:
            avg_return = 0.0
        
        ev = avg_return * confidence
        return round(ev, 6)
    
    def _write_outcome(self, signal: PendingSignal, partial: bool = False):
        """Write a resolved signal outcome to the JSONL log and SQLite."""
        try:
            returns, hits = self._calculate_returns_and_hits(signal)
            ev_contribution = self._calculate_ev_contribution(returns, hits, signal.confidence)
            
            outcome = {
                'ts': signal.ts,
                'symbol': signal.symbol,
                'signal_name': signal.signal_name,
                'direction': signal.direction,
                'confidence': signal.confidence,
                'price_at_signal': signal.price_at_signal,
                'prices': signal.prices,
                'returns': returns,
                'hits': hits,
                'ev_contribution': ev_contribution,
                'partial': partial
            }
            
            with open(OUTCOMES_LOG, 'a') as f:
                f.write(json.dumps(outcome) + '\n')
            
            try:
                from src.infrastructure.migrate_jsonl import get_dual_writer
                dual_writer = get_dual_writer()
                signal_record = {
                    'signal_id': signal.id,
                    'symbol': signal.symbol,
                    'signal_name': signal.signal_name,
                    'direction': signal.direction,
                    'confidence': signal.confidence,
                    'ev_contribution': ev_contribution,
                    'price_at_signal': signal.price_at_signal
                }
                dual_writer.write_signal_sync(signal_record)
            except Exception as sqlite_err:
                print(f"[SignalTracker] SQLite dual-write failed (non-blocking): {sqlite_err}")
            
            print(f"[SignalTracker] Wrote outcome: {signal.symbol} {signal.signal_name} {signal.direction} ev={ev_contribution:.4f}")
            
            self._update_stats()
            
            self._update_direction_router(signal.signal_name, signal.direction, ev_contribution)
            
        except Exception as e:
            print(f"[SignalTracker] Error writing outcome: {e}")
    
    def _update_direction_router(self, signal_name: str, direction: str, ev_contribution: float):
        """Feed outcome to the regime-aware direction router for dynamic adaptation."""
        try:
            from src.regime_direction_router import update_signal_outcome
            update_signal_outcome(signal_name, direction, ev_contribution)
        except ImportError:
            pass
        except Exception as e:
            pass
    
    def get_signal_stats(self) -> Dict[str, Any]:
        """
        Calculate comprehensive statistics for each signal type.
        
        Returns:
            {
                'updated_at': '2025-12-04T18:00:00',
                'signals': {
                    'funding': {
                        'n': 150,
                        'win_rate_1m': 0.52,
                        'win_rate_5m': 0.58,
                        ...
                        'best_horizon': '1h',
                        'recommended_weight': 0.22
                    },
                    ...
                },
                'signal_rankings': ['funding', 'whale_flow', ...]
            }
        """
        outcomes = self._load_all_outcomes()
        
        if not outcomes:
            return {
                'updated_at': datetime.utcnow().isoformat(),
                'signals': {},
                'signal_rankings': []
            }
        
        signal_data = defaultdict(lambda: {
            'returns': defaultdict(list),
            'hits': defaultdict(list),
            'confidences': []
        })
        
        for outcome in outcomes:
            signal_name = outcome.get('signal_name', '')
            if not signal_name:
                continue
            
            data = signal_data[signal_name]
            data['confidences'].append(outcome.get('confidence', 0.5))
            
            returns = outcome.get('returns', {})
            hits = outcome.get('hits', {})
            
            for horizon in HORIZONS:
                if horizon in returns:
                    data['returns'][horizon].append(returns[horizon])
                if horizon in hits:
                    data['hits'][horizon].append(1 if hits[horizon] else 0)
        
        stats = {}
        ev_scores = {}
        
        for signal_name, data in signal_data.items():
            n = len(data['confidences'])
            if n == 0:
                continue
            
            signal_stats = {'n': n}
            best_ev = -float('inf')
            best_horizon = None
            
            for horizon in HORIZONS:
                returns_list = data['returns'].get(horizon, [])
                hits_list = data['hits'].get(horizon, [])
                
                if returns_list:
                    avg_return = sum(returns_list) / len(returns_list)
                    signal_stats[f'avg_return_{horizon}'] = round(avg_return, 6)
                else:
                    avg_return = 0.0
                    signal_stats[f'avg_return_{horizon}'] = 0.0
                
                if hits_list:
                    win_rate = sum(hits_list) / len(hits_list)
                    signal_stats[f'win_rate_{horizon}'] = round(win_rate, 4)
                else:
                    win_rate = 0.5
                    signal_stats[f'win_rate_{horizon}'] = 0.5
                
                ev = avg_return * win_rate
                signal_stats[f'ev_{horizon}'] = round(ev, 6)
                
                if ev > best_ev:
                    best_ev = ev
                    best_horizon = horizon
            
            signal_stats['best_horizon'] = best_horizon or '5m'
            
            avg_confidence = sum(data['confidences']) / len(data['confidences'])
            best_ev_value = signal_stats.get(f'ev_{best_horizon}', 0)
            recommended_weight = min(0.30, max(0.05, best_ev_value * 100 * avg_confidence))
            signal_stats['recommended_weight'] = round(recommended_weight, 3)
            
            stats[signal_name] = signal_stats
            ev_scores[signal_name] = best_ev_value
        
        signal_rankings = sorted(ev_scores.keys(), key=lambda x: ev_scores.get(x, 0), reverse=True)
        
        total_weight = sum(stats[s].get('recommended_weight', 0) for s in stats)
        if total_weight > 0:
            for signal_name in stats:
                stats[signal_name]['recommended_weight'] = round(
                    stats[signal_name]['recommended_weight'] / total_weight, 3
                )
        
        result = {
            'updated_at': datetime.utcnow().isoformat(),
            'signals': stats,
            'signal_rankings': signal_rankings,
            'total_outcomes': len(outcomes)
        }
        
        return result
    
    def _load_all_outcomes(self) -> List[Dict[str, Any]]:
        """Load all outcomes from the JSONL log."""
        outcomes = []
        try:
            if OUTCOMES_LOG.exists():
                with open(OUTCOMES_LOG, 'r') as f:
                    for line in f:
                        line = line.strip()
                        if line:
                            try:
                                outcomes.append(json.loads(line))
                            except json.JSONDecodeError:
                                continue
        except Exception as e:
            print(f"[SignalTracker] Error loading outcomes: {e}")
        return outcomes
    
    def _update_stats(self):
        """Update the signal stats file."""
        try:
            stats = self.get_signal_stats()
            SIGNAL_STATS_FILE.write_text(json.dumps(stats, indent=2))
        except Exception as e:
            print(f"[SignalTracker] Error updating stats: {e}")
    
    def get_pending_count(self) -> int:
        """Get the number of pending signals."""
        return len(self.pending_signals)
    
    def get_pending_summary(self) -> Dict[str, int]:
        """Get summary of pending signals by type."""
        summary = defaultdict(int)
        for signal in self.pending_signals.values():
            summary[signal.signal_name] += 1
        return dict(summary)
    
    def force_resolve_all(self) -> int:
        """
        Force resolve all pending signals immediately with current prices.
        Useful for debugging or when shutting down.
        
        Returns:
            Number of signals resolved
        """
        count = 0
        with self._lock:
            for signal_id, signal in list(self.pending_signals.items()):
                try:
                    price = self._get_current_price(signal.symbol)
                    if price is not None:
                        for horizon in HORIZONS:
                            if horizon not in signal.resolved_horizons:
                                signal.prices[horizon] = price
                                signal.resolved_horizons.append(horizon)
                    
                    self._write_outcome(signal, partial=True)
                    count += 1
                except Exception as e:
                    print(f"[SignalTracker] Error force resolving {signal_id}: {e}")
            
            self.pending_signals.clear()
            self._save_pending_signals()
        
        return count
    
    def get_recent_outcomes(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Get the most recent outcomes for display."""
        outcomes = self._load_all_outcomes()
        return outcomes[-limit:] if outcomes else []
    
    def get_signal_performance(self, signal_name: str) -> Dict[str, Any]:
        """Get detailed performance stats for a specific signal."""
        stats = self.get_signal_stats()
        return stats.get('signals', {}).get(signal_name, {})


signal_tracker = SignalOutcomeTracker()


def run_resolver_loop(interval_seconds: int = 60):
    """
    Run the resolver in a background loop.
    Call this to start automatic resolution.
    """
    import threading
    
    def _resolver_thread():
        while True:
            try:
                resolved = signal_tracker.resolve_pending_signals()
                if resolved > 0:
                    print(f"[SignalTracker] Resolved {resolved} signals")
            except Exception as e:
                print(f"[SignalTracker] Resolver error: {e}")
            time.sleep(interval_seconds)
    
    thread = threading.Thread(target=_resolver_thread, daemon=True)
    thread.start()
    print(f"[SignalTracker] Started resolver loop (interval={interval_seconds}s)")
    return thread


if __name__ == '__main__':
    print("Signal Outcome Tracker - Manual Test")
    print("=" * 50)
    
    test_signal_id = signal_tracker.log_signal(
        symbol='BTCUSDT',
        signal_name='funding',
        direction='LONG',
        confidence=0.85,
        price=97500.00,
        signal_data={'funding_rate': -0.001, 'reason': 'extreme_negative_funding'}
    )
    
    print(f"\nLogged test signal: {test_signal_id}")
    print(f"Pending signals: {signal_tracker.get_pending_count()}")
    print(f"Pending summary: {signal_tracker.get_pending_summary()}")
    
    print("\nCurrent stats:")
    stats = signal_tracker.get_signal_stats()
    print(json.dumps(stats, indent=2))
