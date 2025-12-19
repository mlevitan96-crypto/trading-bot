#!/usr/bin/env python3
"""
Intelligence Gate Module
Integrates CoinGlass market intelligence into trading execution flow.

Uses only Hobbyist tier endpoints (within API limits):
- Taker Buy/Sell Volume (order flow)
- Liquidation data (cascade risk)  
- Fear & Greed Index (macro sentiment)

Signal Integration:
- Provides entry confirmation/rejection based on intelligence alignment
- Modulates position sizing based on confidence score
- Logs all gate decisions for learning

API Rate Limit: ~30 calls/minute, we use ~12/minute (safe margin)
"""

import os
import json
import time
import threading
from pathlib import Path
from datetime import datetime, timedelta
from typing import Dict, Any, Optional, Tuple

INTEL_DIR = Path("feature_store/intelligence")
SUMMARY_FILE = INTEL_DIR / "summary.json"
GATE_LOG = Path("logs/intelligence_gate.log")

INTEL_STALENESS_SECS = 120

try:
    from src.health_to_learning_bridge import log_gate_decision
except ImportError:
    def log_gate_decision(*args, **kwargs): pass

DIRECTION_MAP = {
    "LONG": "OPEN_LONG",
    "SHORT": "OPEN_SHORT",
    "NEUTRAL": "HOLD"
}

GATE_LOG.parent.mkdir(parents=True, exist_ok=True)


def _log(msg: str):
    ts = datetime.utcnow().isoformat() + "Z"
    entry = f"[{ts}] {msg}"
    print(entry)
    with open(GATE_LOG, 'a') as f:
        f.write(entry + '\n')


def load_intelligence() -> Optional[Dict]:
    """Load latest intelligence from summary file."""
    if not SUMMARY_FILE.exists():
        return None
    
    try:
        with open(SUMMARY_FILE) as f:
            data = json.load(f)
        
        ts_str = data.get('ts', '')
        if ts_str:
            intel_time = datetime.fromisoformat(ts_str.replace('Z', '+00:00').replace('+00:00', ''))
            age_secs = (datetime.utcnow() - intel_time).total_seconds()
            
            if age_secs > INTEL_STALENESS_SECS:
                return None
        
        return data
    except Exception as e:
        _log(f"Error loading intelligence: {e}")
        return None


def get_signal_for_symbol(symbol: str) -> Optional[Dict]:
    """Get intelligence signal for a specific symbol."""
    intel = load_intelligence()
    if not intel:
        return None
    
    signals = intel.get('signals', {})
    
    if symbol in signals:
        return signals[symbol]
    
    if symbol.endswith('USDT') and symbol[:-4] + 'USDT' in signals:
        return signals[symbol[:-4] + 'USDT']
    
    return signals.get(symbol)


# Cache for learned multipliers (loaded once, refreshed periodically)
_INTEL_SIZING_CACHE = None
_INTEL_SIZING_CACHE_TIME = None
_INTEL_SIZING_CACHE_TTL = 300  # Refresh every 5 minutes


def _load_learned_intel_multipliers() -> Dict[str, float]:
    """Load learned sizing multipliers from feature_store, with caching."""
    global _INTEL_SIZING_CACHE, _INTEL_SIZING_CACHE_TIME
    
    now = time.time()
    
    # Return cached if still valid
    if _INTEL_SIZING_CACHE and _INTEL_SIZING_CACHE_TIME and (now - _INTEL_SIZING_CACHE_TIME) < _INTEL_SIZING_CACHE_TTL:
        return _INTEL_SIZING_CACHE
    
    # Default multipliers (fallback if learning hasn't run yet)
    default_multipliers = {
        "strong_conflict": 0.4,
        "moderate_conflict": 0.6,
        "weak_conflict": 0.8,
        "neutral": 0.85,
        "aligned": 1.0,
        "aligned_boost": 1.3,
    }
    
    try:
        import json
        sizing_path = "feature_store/intelligence_gate_sizing.json"
        if os.path.exists(sizing_path):
            with open(sizing_path, 'r') as f:
                data = json.load(f)
                learned = data.get("multipliers", {})
                # Merge with defaults (learned values override)
                _INTEL_SIZING_CACHE = {**default_multipliers, **learned}
                _INTEL_SIZING_CACHE_TIME = now
                return _INTEL_SIZING_CACHE
    except Exception as e:
        _log(f"Error loading learned intel multipliers: {e}")
    
    _INTEL_SIZING_CACHE = default_multipliers
    _INTEL_SIZING_CACHE_TIME = now
    return _INTEL_SIZING_CACHE


def intelligence_gate(signal: Dict) -> Tuple[bool, str, float]:
    """
    Check if signal aligns with market intelligence (enhanced with funding + OI).
    
    Uses LEARNED sizing multipliers from historical performance data.
    
    Returns:
        Tuple of (allowed: bool, reason: str, sizing_multiplier: float)
        - allowed: True if signal passes gate (always True now)
        - reason: Explanation for decision
        - sizing_multiplier: Learned multiplier based on intel alignment
    """
    symbol = signal.get('symbol', '')
    action = signal.get('action', signal.get('direction', ''))
    
    # Load learned multipliers
    multipliers = _load_learned_intel_multipliers()
    
    intel_signal = get_signal_for_symbol(symbol)
    
    if not intel_signal:
        return True, "no_intel_data", 1.0
    
    intel_direction = intel_signal.get('direction', 'NEUTRAL')
    intel_confidence = intel_signal.get('confidence', 0)
    composite_score = intel_signal.get('composite', 0)
    raw_data = intel_signal.get('raw', {})
    
    from src.market_intelligence import get_enhanced_signal
    enhanced = get_enhanced_signal(symbol)
    if enhanced:
        intel_direction = enhanced.get('direction', intel_direction)
        intel_confidence = enhanced.get('confidence', intel_confidence)
        composite_score = enhanced.get('enhanced_composite', composite_score)
        funding_rate = enhanced.get('funding_rate', 0)
        oi_change = enhanced.get('oi_change_1h', 0)
        _log(f"📊 Enhanced intel {symbol}: dir={intel_direction} conf={intel_confidence:.2f} funding={funding_rate:.5f} oi_delta={oi_change:.1f}%")
    
    signal_is_long = action.upper() in ['OPEN_LONG', 'BUY', 'LONG']
    signal_is_short = action.upper() in ['OPEN_SHORT', 'SELL', 'SHORT']
    
    if intel_direction == 'NEUTRAL':
        sizing_mult = multipliers.get("neutral", 0.85)
        return True, "intel_neutral", sizing_mult
    
    intel_is_long = intel_direction == 'LONG'
    intel_is_short = intel_direction == 'SHORT'
    
    if (signal_is_long and intel_is_long) or (signal_is_short and intel_is_short):
        # Intel aligns with signal - use learned aligned multiplier
        base_mult = multipliers.get("aligned", 1.0)
        # Apply boost for high confidence (learned boost multiplier)
        if intel_confidence >= 0.7:
            boost_mult = multipliers.get("aligned_boost", 1.3)
            sizing_mult = min(boost_mult, base_mult * (1 + (intel_confidence * 0.3)))
        else:
            sizing_mult = base_mult * (1 + (intel_confidence * 0.2))  # Reduced from 0.3
        
        sizing_mult = min(sizing_mult, 1.5)  # Cap at 1.5x
        
        _log(f"✅ INTEL-CONFIRM {symbol}: Signal={action} aligns with Intel={intel_direction} (conf={intel_confidence:.2f}, mult={sizing_mult:.2f}) [LEARNED]")
        log_gate_decision("intelligence_gate", symbol, action, True, f"intel_confirmed_{intel_direction.lower()}",
                          {"intel_direction": intel_direction, "confidence": intel_confidence, "composite": composite_score, "sizing_mult": sizing_mult})
        return True, f"intel_confirmed_{intel_direction.lower()}", sizing_mult
    
    if (signal_is_long and intel_is_short) or (signal_is_short and intel_is_long):
        # CONVERTED TO SIZING ADJUSTMENT: Never block, only reduce sizing
        # Use LEARNED multipliers instead of hard-coded values
        if intel_confidence >= 0.6:
            sizing_mult = multipliers.get("strong_conflict", 0.4)
            reason = f"intel_conflict_{intel_direction.lower()}_strong"
        elif intel_confidence >= 0.4:
            sizing_mult = multipliers.get("moderate_conflict", 0.6)
            reason = f"intel_conflict_{intel_direction.lower()}_moderate"
        else:
            sizing_mult = multipliers.get("weak_conflict", 0.8)
            reason = f"intel_conflict_{intel_direction.lower()}_weak"
        
        _log(f"⚠️ INTEL-REDUCE {symbol}: Signal={action} conflicts with Intel={intel_direction} (conf={intel_confidence:.2f}, mult={sizing_mult:.2f}) [LEARNED]")
        log_gate_decision("intelligence_gate", symbol, action, True, reason,
                          {"intel_direction": intel_direction, "confidence": intel_confidence, "sizing_mult": sizing_mult, "composite": composite_score})
        return True, reason, sizing_mult
    
    return True, "no_action_match", 1.0


def get_fear_greed() -> int:
    """Get current Fear & Greed index."""
    intel = load_intelligence()
    if intel:
        return intel.get('fear_greed', 50)
    return 50


def should_be_contrarian() -> bool:
    """Check if market is in extreme sentiment zone (contrarian opportunities)."""
    fg = get_fear_greed()
    return fg < 25 or fg > 75


def get_strongest_signal() -> Optional[Tuple[str, str, float]]:
    """
    Get the symbol with strongest intelligence signal.
    
    Returns:
        Tuple of (symbol, direction, confidence) or None
    """
    intel = load_intelligence()
    if not intel:
        return None
    
    signals = intel.get('signals', {})
    best = None
    best_conf = 0
    
    for symbol, sig in signals.items():
        if sig.get('direction') != 'NEUTRAL':
            conf = sig.get('confidence', 0)
            if conf > best_conf:
                best = (symbol, sig['direction'], conf)
                best_conf = conf
    
    return best


class IntelligencePoller:
    """Background thread that polls CoinGlass at safe intervals."""
    
    def __init__(self, interval_secs: int = 60):
        self.interval = interval_secs
        self.running = False
        self.thread = None
        self.last_poll = None
        self.poll_count = 0
    
    def _poll_loop(self):
        """Main polling loop with enhanced intelligence (funding + OI)."""
        from src.market_intelligence import poll_enhanced_intelligence
        
        while self.running:
            try:
                poll_enhanced_intelligence()
                self.last_poll = datetime.utcnow()
                self.poll_count += 1
            except Exception as e:
                _log(f"Poll error: {e}")
            
            time.sleep(self.interval)
    
    def start(self):
        """Start background polling."""
        if self.running:
            return
        
        self.running = True
        self.thread = threading.Thread(target=self._poll_loop, daemon=True)
        self.thread.start()
        _log(f"Intelligence poller started (interval={self.interval}s)")
    
    def stop(self):
        """Stop background polling."""
        self.running = False
        if self.thread:
            self.thread.join(timeout=5)
        _log("Intelligence poller stopped")
    
    def is_healthy(self) -> bool:
        """Check if poller is running and recent."""
        if not self.running or not self.last_poll:
            return False
        age = (datetime.utcnow() - self.last_poll).total_seconds()
        return age < self.interval * 2


_poller_instance = None


def start_intelligence_poller(interval_secs: int = 60):
    """Start the global intelligence poller."""
    global _poller_instance
    if _poller_instance is None:
        _poller_instance = IntelligencePoller(interval_secs)
    _poller_instance.start()
    return _poller_instance


def get_poller() -> Optional[IntelligencePoller]:
    """Get the global poller instance."""
    return _poller_instance


def intelligence_summary() -> Dict:
    """Get a summary of current intelligence state."""
    intel = load_intelligence()
    
    if not intel:
        return {
            'status': 'no_data',
            'fear_greed': 50,
            'signals': {},
            'poller_running': _poller_instance.running if _poller_instance else False
        }
    
    signals = intel.get('signals', {})
    long_signals = [s for s, d in signals.items() if d.get('direction') == 'LONG']
    short_signals = [s for s, d in signals.items() if d.get('direction') == 'SHORT']
    
    return {
        'status': 'active',
        'ts': intel.get('ts'),
        'fear_greed': intel.get('fear_greed', 50),
        'long_signals': long_signals,
        'short_signals': short_signals,
        'total_signals': len(signals),
        'strongest': get_strongest_signal(),
        'poller_running': _poller_instance.running if _poller_instance else False
    }
