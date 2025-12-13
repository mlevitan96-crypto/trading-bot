"""
Position Timing Intelligence - Multi-Timeframe Analysis & Optimal Hold Duration Learning

This module provides:
1. Multi-timeframe signal analysis (1m, 5m, 15m, 1h) for entry timing
2. Position duration tracking and optimal hold time learning
3. Exit timing recommendations based on learned patterns
4. Integration with the existing learning loop for continuous improvement
"""

import json
import time
import threading
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
from pathlib import Path

try:
    from src.data_registry import (
        FEATURE_STORE_DIR, LOGS_DIR, 
        safe_read_json, safe_write_json, safe_append_jsonl
    )
except ImportError:
    FEATURE_STORE_DIR = Path("feature_store")
    LOGS_DIR = Path("logs")
    
    def safe_read_json(path, default=None):
        try:
            with open(path, 'r') as f:
                return json.load(f)
        except:
            return default if default is not None else {}
    
    def safe_write_json(path, data):
        with open(path, 'w') as f:
            json.dump(data, f, indent=2, default=str)
    
    def safe_append_jsonl(path, record):
        with open(path, 'a') as f:
            f.write(json.dumps(record, default=str) + '\n')

TIMING_RULES_PATH = FEATURE_STORE_DIR / "timing_rules.json"
POSITION_TRACKING_PATH = LOGS_DIR / "position_timing.jsonl"
MTF_SIGNALS_PATH = LOGS_DIR / "mtf_signals.jsonl"

DURATION_BUCKETS = {
    'flash': (0, 60),           # <1 minute
    'quick': (60, 300),         # 1-5 minutes
    'short': (300, 900),        # 5-15 minutes
    'medium': (900, 3600),      # 15-60 minutes
    'extended': (3600, 14400),  # 1-4 hours
    'long': (14400, float('inf'))  # >4 hours
}

TIMEFRAMES = ['1m', '5m', '15m', '1h']

_active_positions: Dict[str, dict] = {}
_timing_rules: Dict[str, dict] = {}
_lock = threading.Lock()


def get_duration_bucket(duration_seconds: float) -> str:
    """Classify duration into a bucket."""
    for bucket, (min_s, max_s) in DURATION_BUCKETS.items():
        if min_s <= duration_seconds < max_s:
            return bucket
    return 'long'


def fetch_mtf_trend(symbol: str) -> Dict[str, dict]:
    """
    Fetch multi-timeframe trend signals for a symbol.
    Returns trend direction and strength for each timeframe.
    """
    try:
        from src.exchange_data import get_candles_binance
    except ImportError:
        return _mock_mtf_trend(symbol)
    
    mtf_signals = {}
    
    for tf in TIMEFRAMES:
        try:
            candles = get_candles_binance(symbol, interval=tf, limit=50)
            if candles and len(candles) >= 20:
                closes = [c['close'] for c in candles]
                
                ema_fast = _ema(closes, 8)
                ema_slow = _ema(closes, 21)
                
                current_close = closes[-1]
                trend = 'BULLISH' if ema_fast > ema_slow else 'BEARISH'
                
                trend_strength = abs(ema_fast - ema_slow) / ema_slow * 100
                
                momentum = (closes[-1] - closes[-5]) / closes[-5] * 100 if len(closes) >= 5 else 0
                
                mtf_signals[tf] = {
                    'trend': trend,
                    'strength': round(trend_strength, 3),
                    'momentum': round(momentum, 3),
                    'ema_fast': round(ema_fast, 6),
                    'ema_slow': round(ema_slow, 6),
                    'price': current_close
                }
        except Exception as e:
            mtf_signals[tf] = {'trend': 'UNKNOWN', 'strength': 0, 'error': str(e)}
    
    return mtf_signals


def _mock_mtf_trend(symbol: str) -> Dict[str, dict]:
    """Fallback mock data for testing."""
    import random
    return {tf: {
        'trend': random.choice(['BULLISH', 'BEARISH']),
        'strength': round(random.uniform(0.1, 2.0), 3),
        'momentum': round(random.uniform(-1, 1), 3)
    } for tf in TIMEFRAMES}


def _ema(data: List[float], period: int) -> float:
    """Calculate Exponential Moving Average."""
    if len(data) < period:
        return sum(data) / len(data) if data else 0
    
    multiplier = 2 / (period + 1)
    ema = sum(data[:period]) / period
    
    for price in data[period:]:
        ema = (price - ema) * multiplier + ema
    
    return ema


def calculate_mtf_alignment(mtf_signals: Dict[str, dict], trade_side: str) -> dict:
    """
    Calculate how well multi-timeframe signals align with the trade direction.
    Returns alignment score and details.
    """
    aligned_count = 0
    total_strength = 0
    details = {}
    
    expected_trend = 'BULLISH' if trade_side.upper() == 'LONG' else 'BEARISH'
    
    for tf, signal in mtf_signals.items():
        trend = signal.get('trend', 'UNKNOWN')
        strength = signal.get('strength', 0)
        
        is_aligned = trend == expected_trend
        if is_aligned:
            aligned_count += 1
            total_strength += strength
        
        details[tf] = {
            'aligned': is_aligned,
            'trend': trend,
            'strength': strength
        }
    
    alignment_score = aligned_count / len(TIMEFRAMES) if TIMEFRAMES else 0
    avg_strength = total_strength / aligned_count if aligned_count > 0 else 0
    
    return {
        'score': round(alignment_score, 2),
        'aligned_count': aligned_count,
        'total_timeframes': len(TIMEFRAMES),
        'avg_aligned_strength': round(avg_strength, 3),
        'details': details,
        'recommendation': _get_timing_recommendation(alignment_score, avg_strength)
    }


def _get_timing_recommendation(alignment_score: float, avg_strength: float) -> str:
    """Get timing recommendation based on MTF alignment."""
    if alignment_score >= 0.75 and avg_strength >= 0.5:
        return 'HOLD_EXTENDED'  # Strong alignment, can hold longer
    elif alignment_score >= 0.5:
        return 'HOLD_STANDARD'  # Moderate alignment, standard hold
    elif alignment_score >= 0.25:
        return 'QUICK_EXIT'  # Weak alignment, exit quickly
    else:
        return 'IMMEDIATE_EXIT'  # No alignment, exit immediately


def open_position_tracking(symbol: str, side: str, entry_price: float, 
                          signal_ctx: dict = None) -> dict:
    """
    Start tracking a new position with MTF signals.
    Call this when opening a position.
    """
    with _lock:
        position_id = f"{symbol}_{side}_{int(time.time())}"
        
        mtf_signals = fetch_mtf_trend(symbol)
        mtf_alignment = calculate_mtf_alignment(mtf_signals, side)
        
        position = {
            'position_id': position_id,
            'symbol': symbol,
            'side': side,
            'entry_price': entry_price,
            'entry_time': datetime.utcnow().isoformat(),
            'entry_ts': time.time(),
            'mtf_at_entry': mtf_signals,
            'mtf_alignment': mtf_alignment,
            'signal_ctx': signal_ctx or {},
            'status': 'OPEN'
        }
        
        _active_positions[position_id] = position
        
        safe_append_jsonl(MTF_SIGNALS_PATH, {
            'ts': time.time(),
            'event': 'position_open',
            'position_id': position_id,
            'symbol': symbol,
            'side': side,
            'mtf_signals': mtf_signals,
            'mtf_alignment': mtf_alignment
        })
        
        return position


def check_exit_timing(position_id: str, current_price: float = None) -> dict:
    """
    Check if it's time to exit based on learned timing rules and MTF signals.
    Returns exit recommendation with reasoning.
    
    Intelligence-Driven Decisions:
    - HOLD_LONGER: Strong MTF alignment + momentum continuing + below optimal time
    - EXIT_NOW: MTF alignment degraded OR exceeded optimal time OR momentum reversed
    - TAKE_PROFIT: Good profit + alignment weakening (lock in gains)
    """
    with _lock:
        position = _active_positions.get(position_id)
        if not position:
            return {'action': 'NOT_FOUND', 'reason': 'Position not tracked'}
        
        symbol = position['symbol']
        side = position['side']
        entry_ts = position['entry_ts']
        
        current_ts = time.time()
        hold_duration = current_ts - entry_ts
        duration_bucket = get_duration_bucket(hold_duration)
        
        current_mtf = fetch_mtf_trend(symbol)
        current_alignment = calculate_mtf_alignment(current_mtf, side)
        
        entry_alignment = position.get('mtf_alignment', {}).get('score', 0.5)
        current_alignment_score = current_alignment.get('score', 0.5)
        
        optimal = get_optimal_timing(symbol, side, position.get('signal_ctx', {}))
        optimal_bucket = optimal.get('optimal_duration', 'medium')
        optimal_range = DURATION_BUCKETS.get(optimal_bucket, (900, 3600))
        
        action = 'HOLD'
        reasons = []
        confidence = 0.5
        hold_multiplier = 1.0  # Adjusts how long to hold
        
        # Calculate momentum direction
        entry_mtf = position.get('mtf_at_entry', {})
        momentum_continuing = _check_momentum_continuation(entry_mtf, current_mtf, side)
        
        # Calculate alignment change
        alignment_delta = current_alignment_score - entry_alignment
        alignment_degraded = alignment_delta < -0.25
        alignment_improved = alignment_delta > 0.1
        
        # ============================================================
        # INTELLIGENCE-DRIVEN HOLD LONGER LOGIC
        # ============================================================
        
        # Strong alignment + momentum continuing = HOLD LONGER
        if current_alignment_score >= 0.75 and momentum_continuing:
            reasons.append(f"Strong MTF alignment ({current_alignment_score:.0%}) + momentum continuing")
            action = 'HOLD_EXTENDED'
            hold_multiplier = 1.5  # Allow 50% longer than optimal
            confidence = 0.8
        
        # Alignment improved since entry = HOLD LONGER
        elif alignment_improved and momentum_continuing:
            reasons.append(f"MTF alignment improved: {entry_alignment:.0%} → {current_alignment_score:.0%}")
            action = 'HOLD_EXTENDED'
            hold_multiplier = 1.3
            confidence = 0.7
        
        # Good alignment but not strong = standard hold
        elif current_alignment_score >= 0.5:
            reasons.append(f"Moderate MTF alignment ({current_alignment_score:.0%})")
            action = 'HOLD'
            confidence = 0.6
        
        # ============================================================
        # INTELLIGENCE-DRIVEN EXIT SOONER LOGIC (v2 - LONGER HOLDS)
        # ============================================================
        # NOTE: Previous settings caused 9-min avg hold times (too short!)
        # These relaxed thresholds allow positions to develop properly
        
        # MINIMUM HOLD TIME: Don't trigger ANY early exit in first 5 minutes
        MIN_HOLD_SECONDS = 300  # 5 minutes minimum before considering exits
        
        # MTF alignment degraded significantly = EXIT SOONER (only after min hold)
        if alignment_degraded and hold_duration > MIN_HOLD_SECONDS:
            reasons.append(f"MTF alignment degraded: {entry_alignment:.0%} → {current_alignment_score:.0%}")
            action = 'EXIT_SOONER'
            confidence = max(confidence, 0.65)  # Reduced confidence
        
        # Very weak alignment = EXIT NOW (only after min hold, lower threshold)
        if current_alignment_score < 0.15 and hold_duration > MIN_HOLD_SECONDS:
            reasons.append(f"Very weak MTF alignment ({current_alignment_score:.0%})")
            action = 'EXIT_NOW'
            confidence = max(confidence, 0.75)  # Reduced confidence
        
        # Momentum reversed against position = EXIT NOW (only after 10 min grace)
        if not momentum_continuing and hold_duration > 600:  # 10 min grace (was 1 min)
            reasons.append("Momentum reversed against position after 10min")
            action = 'EXIT_NOW'
            confidence = max(confidence, 0.7)  # Reduced confidence
        
        # ============================================================
        # TIME-BASED CONSTRAINTS
        # ============================================================
        
        # Adjust optimal range based on hold_multiplier
        adjusted_max = optimal_range[1] * hold_multiplier
        
        if hold_duration > adjusted_max * 2:
            reasons.append(f"Significantly exceeded optimal hold (2x)")
            action = 'FORCE_EXIT'
            confidence = 0.9
        elif hold_duration > adjusted_max:
            reasons.append(f"Exceeded optimal hold time ({duration_bucket})")
            if action not in ['HOLD_EXTENDED']:
                action = 'EXIT_NOW'
            confidence = max(confidence, 0.7)
        
        # Still under minimum hold + good alignment = HOLD
        if hold_duration < optimal_range[0] and current_alignment_score >= 0.5 and momentum_continuing:
            if action not in ['EXIT_NOW', 'FORCE_EXIT']:
                reasons.append(f"Under optimal hold time, alignment OK - HOLD")
                action = 'HOLD'
                confidence = 0.7
        
        # ============================================================
        # PROFIT-BASED INTELLIGENCE
        # ============================================================
        
        if current_price and position.get('entry_price'):
            entry_price = position['entry_price']
            if side.upper() == 'SHORT':
                pnl_pct = (entry_price - current_price) / entry_price * 100
            else:
                pnl_pct = (current_price - entry_price) / entry_price * 100
            
            # Profitable + alignment weakening = TAKE PROFIT (don't give it back)
            # Increased profit threshold and require min hold time
            if pnl_pct > 1.5 and (alignment_degraded or not momentum_continuing) and hold_duration > MIN_HOLD_SECONDS:
                reasons.append(f"Profit {pnl_pct:.2f}% + alignment/momentum weakening - TAKE PROFIT")
                action = 'TAKE_PROFIT'
                confidence = max(confidence, 0.75)  # Reduced
            
            # Very profitable + extended hold = TAKE PROFIT
            elif pnl_pct > 3.0 and hold_duration > 600:  # Was 2%/5min, now 3%/10min
                reasons.append(f"Strong profit {pnl_pct:.2f}% after 10min - TAKE PROFIT")
                action = 'TAKE_PROFIT'
                confidence = max(confidence, 0.7)  # Reduced
            
            # Profitable + strong alignment = LET IT RUN
            elif pnl_pct > 0.5 and current_alignment_score >= 0.75 and momentum_continuing:
                reasons.append(f"Profit {pnl_pct:.2f}% + strong alignment - LET IT RUN")
                action = 'HOLD_EXTENDED'
                confidence = 0.75
            
            # Stop loss threshold (widened to give positions room to develop)
            elif pnl_pct < -2.5:  # Was -1.5%, now -2.5%
                reasons.append(f"Stop loss triggered: {pnl_pct:.2f}%")
                action = 'FORCE_EXIT'
                confidence = 0.9
        
        # Map actions to exit signals
        should_exit = action in ['EXIT_NOW', 'EXIT_SOONER', 'TAKE_PROFIT', 'FORCE_EXIT']
        
        return {
            'action': action,
            'should_exit': should_exit,
            'confidence': round(min(confidence, 1.0), 2),
            'reasons': reasons,
            'hold_duration_sec': round(hold_duration, 1),
            'duration_bucket': duration_bucket,
            'optimal_bucket': optimal_bucket,
            'hold_multiplier': hold_multiplier,
            'current_mtf_alignment': current_alignment_score,
            'entry_mtf_alignment': entry_alignment,
            'alignment_delta': round(alignment_delta, 2),
            'momentum_continuing': momentum_continuing,
            'recommendation': current_alignment.get('recommendation', 'HOLD_STANDARD')
        }


def _check_momentum_continuation(entry_mtf: dict, current_mtf: dict, side: str) -> bool:
    """
    Check if momentum is continuing in favor of the position.
    Returns True if momentum supports holding, False if it reversed.
    """
    expected_trend = 'BULLISH' if side.upper() == 'LONG' else 'BEARISH'
    
    # Check 1m and 5m for short-term momentum
    short_tf = ['1m', '5m']
    favorable_count = 0
    
    for tf in short_tf:
        current = current_mtf.get(tf, {})
        current_trend = current.get('trend', 'UNKNOWN')
        current_momentum = current.get('momentum', 0)
        
        # Trend aligned with position
        if current_trend == expected_trend:
            favorable_count += 1
        
        # Momentum in right direction
        if side.upper() == 'LONG' and current_momentum > 0:
            favorable_count += 0.5
        elif side.upper() == 'SHORT' and current_momentum < 0:
            favorable_count += 0.5
    
    # Need at least half favorable for momentum to be "continuing"
    return favorable_count >= 1.0


def close_position_tracking(position_id: str, exit_price: float, 
                           pnl_usd: float, pnl_pct: float) -> dict:
    """
    Close position tracking and record outcome for learning.
    Call this when closing a position.
    """
    with _lock:
        position = _active_positions.pop(position_id, None)
        if not position:
            return {'status': 'NOT_FOUND'}
        
        exit_ts = time.time()
        exit_time = datetime.utcnow().isoformat()
        
        hold_duration = exit_ts - position['entry_ts']
        duration_bucket = get_duration_bucket(hold_duration)
        
        exit_mtf = fetch_mtf_trend(position['symbol'])
        exit_alignment = calculate_mtf_alignment(exit_mtf, position['side'])
        
        outcome = {
            'position_id': position_id,
            'symbol': position['symbol'],
            'side': position['side'],
            'entry_time': position['entry_time'],
            'exit_time': exit_time,
            'entry_ts': position['entry_ts'],
            'exit_ts': exit_ts,
            'entry_price': position['entry_price'],
            'exit_price': exit_price,
            'pnl_usd': pnl_usd,
            'pnl_pct': pnl_pct,
            'hold_duration_sec': hold_duration,
            'duration_bucket': duration_bucket,
            'mtf_at_entry': position['mtf_at_entry'],
            'mtf_at_exit': exit_mtf,
            'entry_alignment': position.get('mtf_alignment', {}).get('score', 0),
            'exit_alignment': exit_alignment.get('score', 0),
            'signal_ctx': position.get('signal_ctx', {})
        }
        
        safe_append_jsonl(POSITION_TRACKING_PATH, outcome)
        
        return outcome


def get_optimal_timing(symbol: str, side: str, signal_ctx: dict = None) -> dict:
    """
    Get optimal timing recommendation for a pattern based on learned rules.
    """
    global _timing_rules
    
    if not _timing_rules:
        _timing_rules = safe_read_json(TIMING_RULES_PATH, {})
    
    ofi = signal_ctx.get('ofi', 0.5) if signal_ctx else 0.5
    if ofi < 0.25: ofi_bucket = 'weak'
    elif ofi < 0.5: ofi_bucket = 'moderate'
    elif ofi < 0.75: ofi_bucket = 'strong'
    elif ofi < 0.9: ofi_bucket = 'very_strong'
    else: ofi_bucket = 'extreme'
    
    ensemble = signal_ctx.get('ensemble', 0) if signal_ctx else 0
    if ensemble < -0.6: ens_bucket = 'strong_bear'
    elif ensemble < -0.2: ens_bucket = 'bear'
    elif ensemble < 0.2: ens_bucket = 'neutral'
    elif ensemble < 0.6: ens_bucket = 'bull'
    else: ens_bucket = 'strong_bull'
    
    pattern_keys = [
        f"{symbol}|{side}|{ofi_bucket}|{ens_bucket}",
        f"{symbol}|{side}|{ofi_bucket}",
        f"{symbol}|{side}",
        f"{ofi_bucket}|{ens_bucket}",
        "default"
    ]
    
    for key in pattern_keys:
        if key in _timing_rules:
            rule = _timing_rules[key]
            return {
                'pattern': key,
                'optimal_duration': rule.get('optimal_duration', 'medium'),
                'min_hold_sec': rule.get('min_hold_sec', 300),
                'max_hold_sec': rule.get('max_hold_sec', 3600),
                'expected_ev': rule.get('expected_ev', 0),
                'sample_size': rule.get('n', 0)
            }
    
    return {
        'pattern': 'default',
        'optimal_duration': 'medium',
        'min_hold_sec': 300,
        'max_hold_sec': 3600,
        'expected_ev': 0,
        'sample_size': 0
    }


def learn_timing_rules() -> dict:
    """
    Analyze position outcomes to learn optimal timing per pattern.
    Run this periodically (e.g., nightly) to update timing rules.
    """
    try:
        outcomes = []
        with open(POSITION_TRACKING_PATH, 'r') as f:
            for line in f:
                if line.strip():
                    outcomes.append(json.loads(line))
    except FileNotFoundError:
        return {'status': 'NO_DATA', 'message': 'No position tracking data yet'}
    
    if len(outcomes) < 10:
        return {'status': 'INSUFFICIENT_DATA', 'count': len(outcomes)}
    
    pattern_outcomes = {}
    
    for o in outcomes:
        symbol = o.get('symbol', 'UNK')
        side = o.get('side', 'UNK')
        duration_bucket = o.get('duration_bucket', 'medium')
        pnl = o.get('pnl_usd', 0)
        
        signal = o.get('signal_ctx', {})
        ofi = signal.get('ofi', 0.5)
        if ofi < 0.25: ofi_bucket = 'weak'
        elif ofi < 0.5: ofi_bucket = 'moderate'
        elif ofi < 0.75: ofi_bucket = 'strong'
        elif ofi < 0.9: ofi_bucket = 'very_strong'
        else: ofi_bucket = 'extreme'
        
        pattern_key = f"{symbol}|{side}|{ofi_bucket}"
        duration_key = f"{pattern_key}|{duration_bucket}"
        
        if pattern_key not in pattern_outcomes:
            pattern_outcomes[pattern_key] = {}
        if duration_bucket not in pattern_outcomes[pattern_key]:
            pattern_outcomes[pattern_key][duration_bucket] = {'pnl': 0, 'n': 0, 'wins': 0}
        
        pattern_outcomes[pattern_key][duration_bucket]['pnl'] += pnl
        pattern_outcomes[pattern_key][duration_bucket]['n'] += 1
        if pnl > 0:
            pattern_outcomes[pattern_key][duration_bucket]['wins'] += 1
    
    timing_rules = {}
    
    for pattern_key, durations in pattern_outcomes.items():
        best_bucket = None
        best_ev = float('-inf')
        
        for dur_bucket, stats in durations.items():
            if stats['n'] >= 3:  # Min sample size
                ev = stats['pnl'] / stats['n']
                if ev > best_ev:
                    best_ev = ev
                    best_bucket = dur_bucket
        
        if best_bucket:
            bucket_range = DURATION_BUCKETS.get(best_bucket, (300, 3600))
            timing_rules[pattern_key] = {
                'optimal_duration': best_bucket,
                'min_hold_sec': bucket_range[0],
                'max_hold_sec': bucket_range[1],
                'expected_ev': round(best_ev, 2),
                'n': durations[best_bucket]['n'],
                'wr': round(durations[best_bucket]['wins'] / durations[best_bucket]['n'] * 100, 1)
            }
    
    timing_rules['default'] = {
        'optimal_duration': 'medium',
        'min_hold_sec': 900,
        'max_hold_sec': 3600,
        'expected_ev': 0,
        'n': 0
    }
    
    safe_write_json(TIMING_RULES_PATH, timing_rules)
    
    global _timing_rules
    _timing_rules = timing_rules
    
    return {
        'status': 'SUCCESS',
        'patterns_learned': len(timing_rules) - 1,
        'total_outcomes': len(outcomes),
        'rules': timing_rules
    }


def get_entry_timing_score(symbol: str, side: str) -> dict:
    """
    Get timing score for a potential entry.
    High score = good time to enter, Low score = wait.
    """
    mtf_signals = fetch_mtf_trend(symbol)
    alignment = calculate_mtf_alignment(mtf_signals, side)
    
    score = alignment['score'] * 100
    
    avg_strength = alignment.get('avg_aligned_strength', 0)
    if avg_strength > 1.0:
        score += 10
    elif avg_strength > 0.5:
        score += 5
    
    momentum_sum = sum(s.get('momentum', 0) for s in mtf_signals.values())
    if side.upper() == 'LONG' and momentum_sum > 0:
        score += min(momentum_sum * 5, 15)
    elif side.upper() == 'SHORT' and momentum_sum < 0:
        score += min(abs(momentum_sum) * 5, 15)
    
    score = max(0, min(100, score))
    
    if score >= 75:
        action = 'ENTER_NOW'
    elif score >= 50:
        action = 'ENTER_CAUTIOUS'
    elif score >= 25:
        action = 'WAIT'
    else:
        action = 'SKIP'
    
    return {
        'score': round(score, 1),
        'action': action,
        'mtf_alignment': alignment,
        'details': mtf_signals
    }


def analyze_recent_performance(hours: int = 4) -> dict:
    """
    Analyze recent position timing performance.
    """
    try:
        outcomes = []
        with open(POSITION_TRACKING_PATH, 'r') as f:
            for line in f:
                if line.strip():
                    outcomes.append(json.loads(line))
    except FileNotFoundError:
        return {'status': 'NO_DATA'}
    
    cutoff = time.time() - (hours * 3600)
    recent = [o for o in outcomes if o.get('exit_ts', 0) > cutoff]
    
    if not recent:
        return {'status': 'NO_RECENT_DATA', 'hours': hours}
    
    total_pnl = sum(o.get('pnl_usd', 0) for o in recent)
    winners = sum(1 for o in recent if o.get('pnl_usd', 0) > 0)
    
    by_duration = {}
    for o in recent:
        bucket = o.get('duration_bucket', 'unknown')
        if bucket not in by_duration:
            by_duration[bucket] = {'pnl': 0, 'n': 0}
        by_duration[bucket]['pnl'] += o.get('pnl_usd', 0)
        by_duration[bucket]['n'] += 1
    
    by_alignment = {'high': {'pnl': 0, 'n': 0}, 'medium': {'pnl': 0, 'n': 0}, 'low': {'pnl': 0, 'n': 0}}
    for o in recent:
        align = o.get('entry_alignment', 0.5)
        if align >= 0.75:
            bucket = 'high'
        elif align >= 0.5:
            bucket = 'medium'
        else:
            bucket = 'low'
        by_alignment[bucket]['pnl'] += o.get('pnl_usd', 0)
        by_alignment[bucket]['n'] += 1
    
    return {
        'hours': hours,
        'trades': len(recent),
        'total_pnl': round(total_pnl, 2),
        'win_rate': round(winners / len(recent) * 100, 1) if recent else 0,
        'by_duration': by_duration,
        'by_alignment': by_alignment,
        'recommendations': _generate_timing_recommendations(by_duration, by_alignment)
    }


def _generate_timing_recommendations(by_duration: dict, by_alignment: dict) -> List[str]:
    """Generate actionable recommendations from analysis."""
    recs = []
    
    duration_evs = {k: v['pnl']/v['n'] if v['n'] > 0 else 0 for k, v in by_duration.items()}
    if duration_evs:
        best_dur = max(duration_evs.items(), key=lambda x: x[1])
        worst_dur = min(duration_evs.items(), key=lambda x: x[1])
        if best_dur[1] > 0:
            recs.append(f"Best duration: {best_dur[0]} (EV=${best_dur[1]:.2f})")
        if worst_dur[1] < 0:
            recs.append(f"Avoid: {worst_dur[0]} duration (EV=${worst_dur[1]:.2f})")
    
    if by_alignment['low']['n'] > 0 and by_alignment['low']['pnl'] < 0:
        recs.append("Avoid low MTF alignment entries - losing money")
    if by_alignment['high']['n'] > 0 and by_alignment['high']['pnl'] > 0:
        recs.append("High MTF alignment entries are profitable - prioritize these")
    
    return recs


if __name__ == "__main__":
    print("=" * 70)
    print("POSITION TIMING INTELLIGENCE - System Test")
    print("=" * 70)
    
    print("\n1. Testing MTF signal fetch for BTCUSDT...")
    mtf = fetch_mtf_trend("BTCUSDT")
    print(json.dumps(mtf, indent=2))
    
    print("\n2. Testing entry timing score for BTCUSDT LONG...")
    score = get_entry_timing_score("BTCUSDT", "LONG")
    print(f"   Score: {score['score']}, Action: {score['action']}")
    
    print("\n3. Testing position tracking...")
    pos = open_position_tracking("BTCUSDT", "LONG", 95000.0, {'ofi': 0.65, 'ensemble': 0.3})
    print(f"   Position ID: {pos['position_id']}")
    print(f"   MTF Alignment: {pos['mtf_alignment']['score']}")
    
    print("\n4. Testing exit timing check...")
    time.sleep(1)
    exit_check = check_exit_timing(pos['position_id'], 95100.0)
    print(f"   Action: {exit_check['action']}")
    print(f"   Reasons: {exit_check['reasons']}")
    
    print("\n5. Testing position close...")
    outcome = close_position_tracking(pos['position_id'], 95100.0, 5.0, 0.1)
    print(f"   Duration: {outcome['hold_duration_sec']:.1f}s ({outcome['duration_bucket']})")
    
    print("\n6. Learning timing rules...")
    rules = learn_timing_rules()
    print(f"   Status: {rules['status']}")
    if 'patterns_learned' in rules:
        print(f"   Patterns learned: {rules['patterns_learned']}")
    
    print("\n" + "=" * 70)
    print("Position Timing Intelligence ready!")
    print("=" * 70)
