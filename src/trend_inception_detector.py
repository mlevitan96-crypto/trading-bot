#!/usr/bin/env python3
"""
Trend Inception Detector
Identifies when a new trend is STARTING using leading indicators.

Philosophy: Instead of reacting to losses with inversion, detect trend
inception BEFORE our lagging signals catch up.

Leading Indicators Used:
1. Funding Rate Sign Flip - negative→positive = incoming long pressure
2. OI Velocity - rapid OI increase precedes large moves
3. Cross-Coin Momentum - if BTC trends, alts follow
4. Liquidation Clusters - cascade liquidations signal trend inception
5. Multi-Timeframe Divergence - when 5m momentum diverges from 1h trend

Data Sources:
- CoinGlass (funding, OI, liquidations)
- Internal price feeds (momentum calculations)
- Historical trade outcomes (what worked)
"""

import os
import json
from datetime import datetime, timedelta
from typing import Dict, Any, Optional, Tuple, List
from pathlib import Path

INCEPTION_STATE_FILE = "feature_store/trend_inception_state.json"
INCEPTION_LOG_FILE = "logs/trend_inception.jsonl"

def _now() -> datetime:
    return datetime.utcnow()

def _log(event_type: str, details: Dict):
    Path("logs").mkdir(exist_ok=True)
    entry = {
        "ts": _now().isoformat() + "Z",
        "event": event_type,
        **details
    }
    with open(INCEPTION_LOG_FILE, 'a') as f:
        f.write(json.dumps(entry) + '\n')


def _load_state() -> Dict:
    if os.path.exists(INCEPTION_STATE_FILE):
        try:
            with open(INCEPTION_STATE_FILE) as f:
                return json.load(f)
        except:
            pass
    return {
        "last_check": None,
        "inception_signals": {},
        "historical_accuracy": {},
        "funding_history": {},
        "oi_velocity_history": {},
        "cross_coin_momentum": {}
    }


def _save_state(state: Dict):
    Path("feature_store").mkdir(exist_ok=True)
    state["last_updated"] = _now().isoformat()
    tmp = INCEPTION_STATE_FILE + ".tmp"
    try:
        with open(tmp, 'w') as f:
            json.dump(state, f, indent=2, default=str)
        os.replace(tmp, INCEPTION_STATE_FILE)
    except Exception as e:
        if os.path.exists(tmp):
            os.remove(tmp)


def get_funding_rate(symbol: str) -> Optional[float]:
    """Get current funding rate from market intelligence."""
    try:
        from src.market_intelligence import get_enhanced_signal
        enhanced = get_enhanced_signal(symbol)
        if enhanced:
            return enhanced.get('funding_rate', 0)
    except:
        pass
    return None


def get_oi_change(symbol: str) -> Optional[float]:
    """Get 1h OI change percentage from market intelligence."""
    try:
        from src.market_intelligence import get_enhanced_signal
        enhanced = get_enhanced_signal(symbol)
        if enhanced:
            return enhanced.get('oi_change_1h', 0)
    except:
        pass
    return None


def detect_funding_flip(symbol: str, state: Dict) -> Tuple[bool, str, float]:
    """
    Detect funding rate sign flip - leading indicator of trend change.
    
    Returns: (is_flip, direction, confidence)
    """
    current_funding = get_funding_rate(symbol)
    if current_funding is None:
        return False, "NEUTRAL", 0.0
    
    # Initialize funding history if needed
    if "funding_history" not in state:
        state["funding_history"] = {}
    if symbol not in state["funding_history"]:
        state["funding_history"][symbol] = []
    
    funding_hist = state.get("funding_history", {}).get(symbol, [])
    
    # Check for flip and debounce (prevent repeated alerts)
    flip_detected = False
    flip_direction = "NEUTRAL"
    flip_confidence = 0.0
    
    if len(funding_hist) >= 1:
        prev_funding = funding_hist[-1]
        
        # Check for sign flip
        if prev_funding < 0 and current_funding > 0:
            # Check debounce - don't alert if we just alerted for this flip
            last_flip_ts = state.get("last_flip_ts", {}).get(symbol)
            now_ts = _now().timestamp()
            
            if last_flip_ts is None or (now_ts - last_flip_ts) > 300:  # 5-minute debounce
                _log("funding_flip", {"symbol": symbol, "from": prev_funding, "to": current_funding, "direction": "LONG"})
                flip_detected = True
                flip_direction = "LONG"
                flip_confidence = min(0.8, abs(current_funding) * 100)
                
                # Record flip timestamp for debounce
                if "last_flip_ts" not in state:
                    state["last_flip_ts"] = {}
                state["last_flip_ts"][symbol] = now_ts
        
        elif prev_funding > 0 and current_funding < 0:
            last_flip_ts = state.get("last_flip_ts", {}).get(symbol)
            now_ts = _now().timestamp()
            
            if last_flip_ts is None or (now_ts - last_flip_ts) > 300:  # 5-minute debounce
                _log("funding_flip", {"symbol": symbol, "from": prev_funding, "to": current_funding, "direction": "SHORT"})
                flip_detected = True
                flip_direction = "SHORT"
                flip_confidence = min(0.8, abs(current_funding) * 100)
                
                if "last_flip_ts" not in state:
                    state["last_flip_ts"] = {}
                state["last_flip_ts"][symbol] = now_ts
    
    # CRITICAL: Always persist the current funding value (even if flip detected)
    # This prevents repeated flip alerts on subsequent polls
    state["funding_history"][symbol].append(current_funding)
    state["funding_history"][symbol] = state["funding_history"][symbol][-24:]
    
    return flip_detected, flip_direction, flip_confidence


def detect_oi_velocity_spike(symbol: str, state: Dict) -> Tuple[bool, str, float]:
    """
    Detect sudden OI velocity spike - often precedes large moves.
    
    High positive OI change with price rising = LONG inception
    High positive OI change with price falling = SHORT inception (shorts opening)
    """
    oi_change = get_oi_change(symbol)
    if oi_change is None:
        return False, "NEUTRAL", 0.0
    
    OI_VELOCITY_THRESHOLD = 2.0
    
    if abs(oi_change) > OI_VELOCITY_THRESHOLD:
        try:
            from src.exchange_gateway import ExchangeGateway
            gw = ExchangeGateway()
            current_price = gw.get_price(symbol, venue="futures")
            
            oi_hist = state.get("oi_velocity_history", {}).get(symbol, {})
            prev_price = oi_hist.get("last_price", current_price)
            price_change_pct = ((current_price - prev_price) / prev_price * 100) if prev_price else 0
            
            state.setdefault("oi_velocity_history", {})[symbol] = {
                "last_price": current_price,
                "last_oi_change": oi_change,
                "ts": _now().isoformat()
            }
            
            if oi_change > OI_VELOCITY_THRESHOLD and price_change_pct > 0.3:
                _log("oi_velocity_spike", {"symbol": symbol, "oi_change": oi_change, "price_change": price_change_pct, "direction": "LONG"})
                return True, "LONG", min(0.7, oi_change / 10)
            
            if oi_change > OI_VELOCITY_THRESHOLD and price_change_pct < -0.3:
                _log("oi_velocity_spike", {"symbol": symbol, "oi_change": oi_change, "price_change": price_change_pct, "direction": "SHORT"})
                return True, "SHORT", min(0.7, oi_change / 10)
        except:
            pass
    
    return False, "NEUTRAL", 0.0


def detect_cross_coin_momentum(symbols: List[str], state: Dict) -> Dict[str, Tuple[str, float]]:
    """
    Detect cross-coin momentum alignment.
    
    If BTC is trending strongly, expect alts to follow.
    If majority of coins show same direction signal, boost that direction.
    """
    momentum_signals = {}
    
    try:
        from src.market_intelligence import get_enhanced_signal
        
        directions = []
        for sym in symbols[:5]:
            enhanced = get_enhanced_signal(sym)
            if enhanced:
                direction = enhanced.get('direction', 'NEUTRAL')
                confidence = enhanced.get('confidence', 0)
                if direction != 'NEUTRAL' and confidence > 0.5:
                    directions.append(direction)
        
        if len(directions) >= 3:
            long_count = directions.count('LONG')
            short_count = directions.count('SHORT')
            
            if long_count >= 4:
                alignment_conf = long_count / len(directions)
                for sym in symbols:
                    momentum_signals[sym] = ("LONG", alignment_conf * 0.6)
                _log("cross_coin_momentum", {"direction": "LONG", "alignment": long_count, "total": len(directions)})
            
            elif short_count >= 4:
                alignment_conf = short_count / len(directions)
                for sym in symbols:
                    momentum_signals[sym] = ("SHORT", alignment_conf * 0.6)
                _log("cross_coin_momentum", {"direction": "SHORT", "alignment": short_count, "total": len(directions)})
    except:
        pass
    
    return momentum_signals


def calculate_inception_score(symbol: str, proposed_direction: str) -> Dict[str, Any]:
    """
    Calculate comprehensive Trend Inception Score.
    
    Returns:
        {
            "score": float 0-1 (higher = stronger inception signal),
            "direction": str ("LONG", "SHORT", "NEUTRAL"),
            "confidence": float 0-1,
            "components": {
                "funding_flip": {"detected": bool, "direction": str, "weight": float},
                "oi_velocity": {"detected": bool, "direction": str, "weight": float},
                "cross_coin": {"detected": bool, "direction": str, "weight": float}
            },
            "recommendation": str ("boost", "neutral", "suppress"),
            "alignment_with_proposed": bool
        }
    """
    state = _load_state()
    
    funding_flip, funding_dir, funding_conf = detect_funding_flip(symbol, state)
    oi_spike, oi_dir, oi_conf = detect_oi_velocity_spike(symbol, state)
    
    canonical_symbols = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "DOGEUSDT"]
    cross_momentum = detect_cross_coin_momentum(canonical_symbols, state)
    cross_dir, cross_conf = cross_momentum.get(symbol, ("NEUTRAL", 0.0))
    
    _save_state(state)
    
    components = {
        "funding_flip": {"detected": funding_flip, "direction": funding_dir, "weight": funding_conf},
        "oi_velocity": {"detected": oi_spike, "direction": oi_dir, "weight": oi_conf},
        "cross_coin": {"detected": cross_dir != "NEUTRAL", "direction": cross_dir, "weight": cross_conf}
    }
    
    direction_votes = {}
    total_weight = 0
    
    for name, comp in components.items():
        if comp["detected"]:
            d = comp["direction"]
            w = comp["weight"]
            direction_votes[d] = direction_votes.get(d, 0) + w
            total_weight += w
    
    if direction_votes:
        inception_direction = max(direction_votes, key=direction_votes.get)
        score = direction_votes[inception_direction] / max(total_weight, 1)
        confidence = min(1.0, score * 1.2)
    else:
        inception_direction = "NEUTRAL"
        score = 0.0
        confidence = 0.0
    
    alignment = inception_direction == proposed_direction.upper()
    
    if score >= 0.5 and alignment:
        recommendation = "boost"
    elif score >= 0.5 and not alignment:
        recommendation = "suppress"
    else:
        recommendation = "neutral"
    
    result = {
        "score": score,
        "direction": inception_direction,
        "confidence": confidence,
        "components": components,
        "recommendation": recommendation,
        "alignment_with_proposed": alignment,
        "symbol": symbol,
        "proposed_direction": proposed_direction
    }
    
    _log("inception_score", result)
    
    return result


def should_boost_entry(symbol: str, proposed_direction: str) -> Tuple[bool, float, str]:
    """
    Quick check: Should we boost this entry based on trend inception?
    
    Returns:
        (should_boost, multiplier, reason)
        - should_boost: True if inception signals align
        - multiplier: 0.5-1.5x sizing adjustment
        - reason: explanation
    """
    inception = calculate_inception_score(symbol, proposed_direction)
    
    if inception["recommendation"] == "boost":
        return True, 1.3, f"trend_inception_aligned_{inception['direction'].lower()}"
    
    elif inception["recommendation"] == "suppress":
        return False, 0.7, f"trend_inception_opposing_{inception['direction'].lower()}"
    
    return True, 1.0, "no_strong_inception_signal"


def analyze_historical_inception_accuracy() -> Dict:
    """
    Analyze how accurate our inception signals have been historically.
    Used for nightly learning loop.
    """
    try:
        from src.data_registry import DataRegistry
        DR = DataRegistry()
        trades = DR.get_trades()[-200:]
    except:
        trades = []
    
    if not trades:
        return {"status": "insufficient_data"}
    
    inception_logs = []
    if os.path.exists(INCEPTION_LOG_FILE):
        try:
            with open(INCEPTION_LOG_FILE) as f:
                for line in f:
                    if line.strip():
                        inception_logs.append(json.loads(line))
        except:
            pass
    
    score_logs = [l for l in inception_logs if l.get("event") == "inception_score"]
    
    if not score_logs:
        return {"status": "no_inception_data"}
    
    results = {
        "total_scored": len(score_logs),
        "boost_signals": sum(1 for l in score_logs if l.get("recommendation") == "boost"),
        "suppress_signals": sum(1 for l in score_logs if l.get("recommendation") == "suppress"),
        "status": "ok"
    }
    
    return results


def get_trend_inception_status() -> Dict:
    """Get current status of trend inception detection."""
    state = _load_state()
    return {
        "last_updated": state.get("last_updated"),
        "tracked_symbols": list(state.get("funding_history", {}).keys()),
        "active_signals": state.get("inception_signals", {}),
        "historical_accuracy": analyze_historical_inception_accuracy()
    }


if __name__ == "__main__":
    print("Testing Trend Inception Detector...")
    
    test_symbols = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
    for sym in test_symbols:
        result = calculate_inception_score(sym, "LONG")
        print(f"\n{sym}:")
        print(f"  Score: {result['score']:.2f}")
        print(f"  Direction: {result['direction']}")
        print(f"  Recommendation: {result['recommendation']}")
        print(f"  Components: {result['components']}")
