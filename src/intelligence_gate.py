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
    Includes Whale CVD filter - blocks trades where whale flow diverges from signal.
    
    Returns:
        Tuple of (allowed: bool, reason: str, sizing_multiplier: float)
        - allowed: False if blocked by Whale CVD divergence, True otherwise
        - reason: Explanation for decision (including "WHALE_CONFLICT" if blocked)
        - sizing_multiplier: Learned multiplier based on intel alignment (2.5x for ULTRA conviction)
    """
    symbol = signal.get('symbol', '')
    action = signal.get('action', signal.get('direction', ''))
    
    # [WHALE CVD FILTER] Check whale flow alignment
    try:
        from src.whale_cvd_engine import check_whale_cvd_alignment, get_whale_cvd
        
        signal_direction = 'LONG' if action.upper() in ['OPEN_LONG', 'BUY', 'LONG'] else 'SHORT'
        if signal_direction == 'SHORT' and action.upper() not in ['OPEN_SHORT', 'SELL', 'SHORT']:
            signal_direction = 'LONG'  # Default fallback
        
        whale_aligned, whale_reason, whale_cvd_data = check_whale_cvd_alignment(symbol, signal_direction)
        
        # Block if whale CVD diverges from signal direction
        if not whale_aligned and whale_reason == "DIVERGING":
            whale_intensity = whale_cvd_data.get("whale_intensity", 0.0)
            if whale_intensity >= 30.0:  # Only block if significant whale activity
                _log(f"❌ WHALE-CONFLICT {symbol}: Signal={signal_direction} conflicts with Whale CVD={whale_cvd_data.get('cvd_direction', 'UNKNOWN')} (intensity={whale_intensity:.1f})")
                try:
                    from src.health_to_learning_bridge import log_gate_decision
                    log_gate_decision("intelligence_gate", symbol, action, False, "WHALE_CONFLICT", {
                        "whale_cvd_direction": whale_cvd_data.get('cvd_direction'),
                        "signal_direction": signal_direction,
                        "whale_intensity": whale_intensity,
                        "cvd_total": whale_cvd_data.get('cvd_total', 0)
                    })
                except:
                    pass
                # [BIG ALPHA] Log to signal_bus for guard effectiveness tracking (Component 8)
                try:
                    from src.signal_bus import get_signal_bus
                    signal_bus = get_signal_bus()
                    signal_bus.emit_signal({
                        "symbol": symbol,
                        "direction": signal_direction,
                        "action": action,
                        "event": "WHALE_CONFLICT",
                        "whale_cvd_direction": whale_cvd_data.get('cvd_direction'),
                        "whale_intensity": whale_intensity,
                        "cvd_total": whale_cvd_data.get('cvd_total', 0),
                        "blocked": True,
                        "reason": "WHALE_CONFLICT"
                    }, source="intelligence_gate")
                except Exception as e:
                    _log(f"⚠️ Failed to log WHALE_CONFLICT to signal_bus: {e}")
                return False, "WHALE_CONFLICT", 0.0
    
    # [BIG ALPHA PHASE 2] MACRO INSTITUTIONAL GUARDS
    # 1. Liquidation Guard - Block LONG signals within 0.5% of Short liquidation clusters
    try:
        from src.macro_institutional_guards import check_liquidation_wall_conflict
        # Get current price from signal or exchange
        current_price = signal.get('price') or signal.get('entry_price') or signal.get('expected_price')
        if not current_price:
            # Try to get from exchange gateway
            try:
                from src.exchange_gateway import ExchangeGateway
                gateway = ExchangeGateway()
                ticker = gateway.get_ticker(symbol, venue="futures")
                if ticker:
                    current_price = float(ticker.get('last', ticker.get('close', 0)))
            except:
                pass
        
        if current_price and current_price > 0:
            should_block_liq, liq_reason, liq_data = check_liquidation_wall_conflict(symbol, signal_direction, current_price)
            if should_block_liq and liq_reason == "LIQ_WALL_CONFLICT":
                _log(f"❌ LIQ-WALL-CONFLICT {symbol}: LONG signal blocked within 0.5% of Short liquidation cluster (price={current_price:.2f}, cluster={liq_data.get('cluster_price', 0):.2f})")
                try:
                    from src.health_to_learning_bridge import log_gate_decision
                    log_gate_decision("intelligence_gate", symbol, action, False, "LIQ_WALL_CONFLICT", liq_data)
                except:
                    pass
                # Log to signal_bus
                try:
                    from src.signal_bus import get_signal_bus
                    signal_bus = get_signal_bus()
                    signal_bus.emit_signal({
                        "symbol": symbol,
                        "direction": signal_direction,
                        "action": action,
                        "event": "LIQ_WALL_CONFLICT",
                        "current_price": current_price,
                        "cluster_price": liq_data.get('cluster_price'),
                        "distance_pct": liq_data.get('distance_pct'),
                        "short_liq_amount": liq_data.get('short_liq_amount'),
                        "blocked": True,
                        "reason": "LIQ_WALL_CONFLICT"
                    }, source="intelligence_gate")
                except Exception as e:
                    _log(f"⚠️ Failed to log LIQ_WALL_CONFLICT to signal_bus: {e}")
                return False, "LIQ_WALL_CONFLICT", 0.0
    except Exception as e:
        _log(f"⚠️ Liquidation Guard check failed for {symbol}: {e}")
    
    # 2. Trap Detection - Block LONG entries if Retail Long/Short Ratio > 2.0
    try:
        from src.macro_institutional_guards import check_long_trap
        is_trap, trap_ratio = check_long_trap(symbol)
        if is_trap and signal_direction == "LONG":
            _log(f"❌ LONG-TRAP-DETECTED {symbol}: Retail Long/Short Ratio={trap_ratio:.2f} > 2.0 (retail very long = potential trap)")
            try:
                from src.health_to_learning_bridge import log_gate_decision
                log_gate_decision("intelligence_gate", symbol, action, False, "LONG_TRAP_DETECTED", {
                    "retail_ratio": trap_ratio
                })
            except:
                pass
            # Log to signal_bus
            try:
                from src.signal_bus import get_signal_bus
                signal_bus = get_signal_bus()
                signal_bus.emit_signal({
                    "symbol": symbol,
                    "direction": signal_direction,
                    "action": action,
                    "event": "LONG_TRAP_DETECTED",
                    "retail_ratio": trap_ratio,
                    "blocked": True,
                    "reason": "LONG_TRAP_DETECTED"
                }, source="intelligence_gate")
            except Exception as e:
                _log(f"⚠️ Failed to log LONG_TRAP_DETECTED to signal_bus: {e}")
            return False, "LONG_TRAP_DETECTED", 0.0
    except Exception as e:
        _log(f"⚠️ Trap Detection check failed for {symbol}: {e}")
        
        # Store whale CVD data for ULTRA conviction check
        whale_cvd_direction = whale_cvd_data.get("cvd_direction", "NEUTRAL")
        whale_intensity = whale_cvd_data.get("whale_intensity", 0.0)
    except Exception as e:
        _log(f"⚠️ Whale CVD check failed for {symbol}: {e}")
        whale_cvd_direction = "UNKNOWN"
        whale_intensity = 0.0
        whale_aligned = True
        whale_reason = "CHECK_FAILED"
    
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
        
        # [ULTRA CONVICTION] If Whale CVD and Retail OFI both align, assign 2.5x sizing
        ultra_conviction = False
        if whale_aligned and whale_reason == "ALIGNED" and whale_intensity >= 50.0:
            # Check if we have OFI data (retail flow proxy)
            # OFI alignment is indicated by signal direction matching intel direction
            # Both whale CVD and retail (OFI via intel) align = ULTRA conviction
            if (signal_is_long and whale_cvd_direction == "LONG") or (signal_is_short and whale_cvd_direction == "SHORT"):
                ultra_conviction = True
                sizing_mult = 2.5  # ULTRA conviction multiplier
                _log(f"🚀 ULTRA-CONVICTION {symbol}: Whale CVD + Retail OFI aligned → 2.5x sizing")
        else:
            # Apply boost for high confidence (learned boost multiplier)
            if intel_confidence >= 0.7:
                boost_mult = multipliers.get("aligned_boost", 1.3)
                sizing_mult = min(boost_mult, base_mult * (1 + (intel_confidence * 0.3)))
            else:
                sizing_mult = base_mult * (1 + (intel_confidence * 0.2))  # Reduced from 0.3
            
            sizing_mult = min(sizing_mult, 1.5)  # Cap at 1.5x (unless ULTRA conviction)
        
        # Get OFI ratio and bid-ask spread for logging
        ofi_ratio = None
        bid_ask_spread_bps = None
        try:
            from src.exchange_gateway import ExchangeGateway
            from src.venue_config import get_venue
            gateway = ExchangeGateway()
            venue = get_venue(symbol) if hasattr(__import__('src.venue_config', fromlist=['get_venue']), 'get_venue') else "futures"
            
            # Get OFI ratio from signal if available
            if signal and isinstance(signal, dict):
                ofi_ratio = signal.get("ofi_ratio") or signal.get("ofi_score") or signal.get("ofi")
            
            # Get bid-ask spread
            try:
                ticker = gateway.get_ticker(symbol, venue=venue)
                if ticker and "bid" in ticker and "ask" in ticker:
                    bid = float(ticker.get("bid", 0))
                    ask = float(ticker.get("ask", 0))
                    mid = (bid + ask) / 2 if (bid > 0 and ask > 0) else 0
                    if mid > 0:
                        bid_ask_spread_bps = ((ask - bid) / mid) * 10000  # Convert to basis points
            except:
                pass
        except:
            pass
        
        reason_code = "ultra_conviction" if ultra_conviction else f"intel_confirmed_{intel_direction.lower()}"
        _log(f"✅ INTEL-CONFIRM {symbol}: Signal={action} aligns with Intel={intel_direction} (conf={intel_confidence:.2f}, mult={sizing_mult:.2f}, OFI={ofi_ratio}, Spread={bid_ask_spread_bps:.1f}bps, Whale={whale_cvd_direction}) [LEARNED]")
        log_gate_decision("intelligence_gate", symbol, action, True, reason_code,
                          {
                              "intel_direction": intel_direction, 
                              "confidence": intel_confidence, 
                              "composite": composite_score, 
                              "sizing_mult": sizing_mult,
                              "ofi_ratio": ofi_ratio,
                              "bid_ask_spread_bps": bid_ask_spread_bps,
                              "whale_cvd_direction": whale_cvd_direction,
                              "whale_intensity": whale_intensity,
                              "ultra_conviction": ultra_conviction
                          })
        return True, reason_code, sizing_mult
    
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
        
        # Get OFI ratio and bid-ask spread for logging
        ofi_ratio = None
        bid_ask_spread_bps = None
        try:
            from src.exchange_gateway import ExchangeGateway
            from src.venue_config import get_venue
            gateway = ExchangeGateway()
            venue = get_venue(symbol) if hasattr(__import__('src.venue_config', fromlist=['get_venue']), 'get_venue') else "futures"
            
            # Get OFI ratio from signal if available
            if signal and isinstance(signal, dict):
                ofi_ratio = signal.get("ofi_ratio") or signal.get("ofi_score") or signal.get("ofi")
            
            # Get bid-ask spread
            try:
                ticker = gateway.get_ticker(symbol, venue=venue)
                if ticker and "bid" in ticker and "ask" in ticker:
                    bid = float(ticker.get("bid", 0))
                    ask = float(ticker.get("ask", 0))
                    mid = (bid + ask) / 2 if (bid > 0 and ask > 0) else 0
                    if mid > 0:
                        bid_ask_spread_bps = ((ask - bid) / mid) * 10000  # Convert to basis points
            except:
                pass
        except:
            pass
        
        _log(f"⚠️ INTEL-REDUCE {symbol}: Signal={action} conflicts with Intel={intel_direction} (conf={intel_confidence:.2f}, mult={sizing_mult:.2f}, OFI={ofi_ratio}, Spread={bid_ask_spread_bps:.1f}bps) [LEARNED]")
        log_gate_decision("intelligence_gate", symbol, action, True, reason,
                          {
                              "intel_direction": intel_direction, 
                              "confidence": intel_confidence, 
                              "sizing_mult": sizing_mult, 
                              "composite": composite_score,
                              "ofi_ratio": ofi_ratio,
                              "bid_ask_spread_bps": bid_ask_spread_bps
                          })
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
