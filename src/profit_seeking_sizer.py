"""
PROFIT-SEEKING SIZER - Intelligence-Driven Position Sizing
============================================================
Uses learned patterns and ML predictions to SIZE UP on winners
and SIZE DOWN (not block) on weaker patterns.

Philosophy: MAKE MONEY by trading aggressively on validated edges.
- Winning patterns: 1.5x - 2.0x sizing
- Neutral patterns: 1.0x sizing  
- Weak patterns: 0.5x - 0.75x sizing (still trade, collect data)
- NEVER blocks trades, only adjusts size

User directive: "Make money! Stop trying to not lose!"
"""

import json
import os
from datetime import datetime
from typing import Dict, Tuple, Optional

DAILY_RULES_FILE = "feature_store/daily_learning_rules.json"
SIZING_LOG_FILE = "logs/profit_sizing_decisions.jsonl"

MIN_MULTIPLIER = 0.5
MAX_MULTIPLIER = 2.0
DEFAULT_MULTIPLIER = 1.0


def load_learned_patterns() -> Dict:
    """Load profitable patterns from daily learning."""
    try:
        with open(DAILY_RULES_FILE, 'r') as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def get_pattern_key(symbol: str, direction: str, ofi_bucket: str = None, 
                    ensemble_bucket: str = None) -> list:
    """Generate pattern keys to match against learned rules."""
    keys = []
    
    if ofi_bucket:
        keys.append(f"sym={symbol}|dir={direction}|ofi={ofi_bucket}")
    if ensemble_bucket:
        keys.append(f"sym={symbol}|dir={direction}|ens={ensemble_bucket}")
    if ofi_bucket and ensemble_bucket:
        keys.append(f"sym={symbol}|ofi={ofi_bucket}|ens={ensemble_bucket}")
    
    keys.append(f"sym={symbol}|dir={direction}")
    
    return keys


def classify_ofi(ofi_value: float) -> str:
    """Classify OFI value into bucket."""
    abs_ofi = abs(ofi_value)
    if abs_ofi >= 0.9:
        return "extreme"
    elif abs_ofi >= 0.75:
        return "very_strong"
    elif abs_ofi >= 0.6:
        return "strong"
    elif abs_ofi >= 0.4:
        return "moderate"
    return "weak"


def get_pattern_multiplier(symbol: str, direction: str, ofi: float = 0.5,
                           ensemble_score: float = 0.5) -> Tuple[float, str, Dict]:
    """
    Get sizing multiplier based on learned patterns.
    
    Returns:
        (multiplier, reason, details)
    """
    rules = load_learned_patterns()
    profitable_patterns = rules.get("profitable_patterns", {})
    
    if not profitable_patterns:
        return DEFAULT_MULTIPLIER, "no_patterns_loaded", {}
    
    ofi_bucket = classify_ofi(ofi)
    
    if ensemble_score >= 0.7:
        ens_bucket = "strong_bull" if direction == "LONG" else "strong_bear"
    elif ensemble_score >= 0.55:
        ens_bucket = "bull" if direction == "LONG" else "bear"
    else:
        ens_bucket = "neutral"
    
    pattern_keys = get_pattern_key(symbol, direction, ofi_bucket, ens_bucket)
    
    best_match = None
    best_ev = -999
    
    for key in pattern_keys:
        if key in profitable_patterns:
            pattern = profitable_patterns[key]
            ev = pattern.get("ev", 0)
            if ev > best_ev:
                best_ev = ev
                best_match = {"key": key, **pattern}
    
    if best_match and best_match.get("profitable", False):
        mult = best_match.get("size_multiplier", 1.0)
        mult = max(MIN_MULTIPLIER, min(MAX_MULTIPLIER, mult))
        
        if best_match.get("ev", 0) > 1.0:
            mult = min(MAX_MULTIPLIER, mult * 1.2)
        
        return mult, f"WINNING_PATTERN:{best_match['key']}", {
            "pattern": best_match["key"],
            "ev": best_match.get("ev", 0),
            "wr": best_match.get("wr", 0),
            "trades": best_match.get("trades", 0),
            "pnl": best_match.get("pnl", 0)
        }
    
    return DEFAULT_MULTIPLIER, "no_matching_pattern", {"tried_keys": pattern_keys}


def get_ml_confidence_multiplier(symbol: str, direction: str, 
                                  features: Dict = None) -> Tuple[float, str]:
    """
    Get sizing multiplier based on ML prediction confidence.
    """
    try:
        from src.ml_predictor import predict
        
        if features is None:
            features = {"direction": 1 if direction == "LONG" else 0}
        
        pred_direction, confidence = predict(symbol, features)
        
        if pred_direction == 'UNKNOWN':
            return DEFAULT_MULTIPLIER, "no_model"
        
        if pred_direction == direction:
            if confidence >= 0.7:
                return 1.5, f"ML_AGREES_HIGH:{confidence:.2f}"
            elif confidence >= 0.6:
                return 1.25, f"ML_AGREES_MED:{confidence:.2f}"
            else:
                return 1.1, f"ML_AGREES_LOW:{confidence:.2f}"
        else:
            if confidence >= 0.7:
                return 0.6, f"ML_DISAGREES_HIGH:{confidence:.2f}"
            elif confidence >= 0.6:
                return 0.75, f"ML_DISAGREES_MED:{confidence:.2f}"
            else:
                return 0.9, f"ML_DISAGREES_LOW:{confidence:.2f}"
                
    except Exception as e:
        return DEFAULT_MULTIPLIER, f"ml_error:{str(e)[:30]}"


def get_ensemble_multiplier(symbol: str, direction: str, features: Dict = None,
                            ofi: float = 0.0, ensemble_score: float = 0.0) -> Tuple[float, str, Dict]:
    """
    Get sizing multiplier from ensemble predictor (GBM + LSTM + Pattern + Sentiment + On-Chain).
    
    This is the NEW multi-model ensemble that combines all available signals.
    
    Returns:
        (multiplier, reason, details)
    """
    try:
        from src.ensemble_predictor import get_ensemble_prediction
        
        if features is None:
            features = {}
        
        result = get_ensemble_prediction(
            symbol=symbol,
            direction=direction,
            features=features,
            ofi=ofi,
            ensemble_score=ensemble_score
        )
        
        prob_win = result.get('prob_win', 0.5)
        confidence = result.get('confidence', 0)
        size_mult = result.get('size_multiplier', 1.0)
        
        if prob_win > 0.65 and confidence > 0.5:
            reason = f"ENSEMBLE_STRONG_WIN:prob={prob_win:.2f},conf={confidence:.2f}"
        elif prob_win > 0.55:
            reason = f"ENSEMBLE_FAVORABLE:prob={prob_win:.2f}"
        elif prob_win < 0.40 and confidence > 0.5:
            reason = f"ENSEMBLE_WEAK:prob={prob_win:.2f}"
        else:
            reason = f"ENSEMBLE_NEUTRAL:prob={prob_win:.2f}"
        
        details = {
            'prob_win': prob_win,
            'confidence': confidence,
            'components': result.get('components', {})
        }
        
        return size_mult, reason, details
        
    except Exception as e:
        return DEFAULT_MULTIPLIER, f"ensemble_error:{str(e)[:30]}", {}


def get_profit_seeking_size(symbol: str, direction: str, base_size: float,
                            ofi: float = 0.5, ensemble_score: float = 0.5,
                            ml_features: Dict = None, use_ensemble: bool = True) -> Tuple[float, Dict]:
    """
    MAIN ENTRY: Get profit-optimized position size.
    
    NEVER blocks trades, only adjusts sizing.
    - Boosts on winning patterns
    - Reduces on weak patterns  
    - Uses ML confidence for additional adjustment
    - Uses ensemble predictor (GBM + LSTM + Sentiment + On-Chain) for final decision
    
    Returns:
        (final_size, attribution_details)
    """
    pattern_mult, pattern_reason, pattern_details = get_pattern_multiplier(
        symbol, direction, ofi, ensemble_score
    )
    
    ml_mult, ml_reason = get_ml_confidence_multiplier(
        symbol, direction, ml_features
    )
    
    ensemble_mult = DEFAULT_MULTIPLIER
    ensemble_reason = "disabled"
    ensemble_details = {}
    
    if use_ensemble:
        ensemble_mult, ensemble_reason, ensemble_details = get_ensemble_multiplier(
            symbol, direction, ml_features, ofi, ensemble_score
        )
    
    if use_ensemble and "error" not in ensemble_reason.lower():
        combined_mult = (pattern_mult * 0.35) + (ml_mult * 0.25) + (ensemble_mult * 0.40)
    else:
        combined_mult = (pattern_mult * 0.7) + (ml_mult * 0.3)
    
    combined_mult = max(MIN_MULTIPLIER, min(MAX_MULTIPLIER, combined_mult))
    
    final_size = base_size * combined_mult
    
    MIN_FLOOR = 200.0
    if final_size < MIN_FLOOR:
        final_size = MIN_FLOOR
    
    attribution = {
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "symbol": symbol,
        "direction": direction,
        "base_size": round(base_size, 2),
        "final_size": round(final_size, 2),
        "combined_multiplier": round(combined_mult, 3),
        "pattern_multiplier": round(pattern_mult, 3),
        "pattern_reason": pattern_reason,
        "pattern_details": pattern_details,
        "ml_multiplier": round(ml_mult, 3),
        "ml_reason": ml_reason,
        "ensemble_multiplier": round(ensemble_mult, 3),
        "ensemble_reason": ensemble_reason,
        "ensemble_details": ensemble_details,
        "ofi": round(ofi, 3),
        "ensemble_score": round(ensemble_score, 3)
    }
    
    try:
        os.makedirs(os.path.dirname(SIZING_LOG_FILE), exist_ok=True)
        with open(SIZING_LOG_FILE, 'a') as f:
            f.write(json.dumps(attribution) + "\n")
    except Exception:
        pass
    
    return final_size, attribution


def get_sizing_summary() -> Dict:
    """Get summary of recent sizing decisions."""
    try:
        decisions = []
        with open(SIZING_LOG_FILE, 'r') as f:
            for line in f:
                try:
                    decisions.append(json.loads(line.strip()))
                except:
                    pass
        
        if not decisions:
            return {"error": "no decisions logged"}
        
        recent = decisions[-100:]
        
        boosted = [d for d in recent if d.get("combined_multiplier", 1) > 1.1]
        reduced = [d for d in recent if d.get("combined_multiplier", 1) < 0.9]
        neutral = [d for d in recent if 0.9 <= d.get("combined_multiplier", 1) <= 1.1]
        
        return {
            "total_decisions": len(recent),
            "boosted": len(boosted),
            "reduced": len(reduced),
            "neutral": len(neutral),
            "avg_multiplier": sum(d.get("combined_multiplier", 1) for d in recent) / len(recent),
            "top_boosted_patterns": list(set(d.get("pattern_reason", "") for d in boosted))[:5]
        }
    except FileNotFoundError:
        return {"error": "no log file yet"}


if __name__ == "__main__":
    print("=" * 60)
    print("PROFIT-SEEKING SIZER TEST")
    print("=" * 60)
    
    test_cases = [
        ("DOTUSDT", "SHORT", 500, 0.8, 0.3),
        ("BNBUSDT", "SHORT", 500, 0.4, 0.5),
        ("ETHUSDT", "LONG", 500, 0.6, 0.7),
        ("BTCUSDT", "SHORT", 500, 0.5, 0.5),
    ]
    
    for symbol, direction, base, ofi, ens in test_cases:
        final, attr = get_profit_seeking_size(symbol, direction, base, ofi, ens)
        print(f"\n{symbol} {direction}:")
        print(f"  Base: ${base} -> Final: ${final:.0f} ({attr['combined_multiplier']:.2f}x)")
        print(f"  Pattern: {attr['pattern_reason']}")
        print(f"  ML: {attr['ml_reason']}")
