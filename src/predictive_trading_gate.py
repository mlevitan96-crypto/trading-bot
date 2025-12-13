"""
Predictive Trading Gate - SHADOW MODE

This module logs predictions but does NOT enforce them in live trading.
Purpose: Collect data to validate patterns before they are promoted to live.

CRITICAL: All functions are in SHADOW MODE
- Predictions are LOGGED for analysis
- NO trades are blocked or modified based on predictions
- Data collection for backtesting and validation

Based on comprehensive analysis of 3,942 closed positions across 8 days.
Patterns need validation over 30+ days before going live.
"""

import json
import os
from datetime import datetime, timezone
from typing import Dict, Tuple, Optional
import math

RULES_FILE = "feature_store/predictive_trading_rules.json"
SHADOW_LOG = "logs/predictive_shadow.jsonl"
VALIDATION_LOG = "logs/pattern_validation.jsonl"

_rules_cache = None
_rules_load_time = 0

SHADOW_MODE = True

def _load_rules() -> dict:
    """Load predictive trading rules from feature_store."""
    global _rules_cache, _rules_load_time
    
    if _rules_cache and (datetime.now().timestamp() - _rules_load_time) < 60:
        return _rules_cache
    
    try:
        if os.path.exists(RULES_FILE):
            with open(RULES_FILE) as f:
                _rules_cache = json.load(f)
                _rules_load_time = datetime.now().timestamp()
                return _rules_cache
    except Exception as e:
        print(f"[PREDICT] Error loading rules: {e}")
    
    return {}

def get_current_hour_utc() -> int:
    """Get current hour in UTC."""
    return datetime.now(timezone.utc).hour

def get_ofi_bucket(ofi_score: float) -> str:
    """Categorize OFI score into buckets."""
    if ofi_score >= 0.8:
        return "extreme"
    elif ofi_score >= 0.5:
        return "strong"
    elif ofi_score >= 0.3:
        return "moderate"
    else:
        return "weak"

def get_hour_bucket(hour: int) -> str:
    """Categorize hour into buckets based on historical performance."""
    rules = _load_rules()
    hour_rules = rules.get("hour_rules", {})
    
    golden = hour_rules.get("golden_hours", [8])
    good = hour_rules.get("good_hours", [16, 17, 18, 19, 20])
    bad = hour_rules.get("bad_hours", [0, 1, 2, 11, 12, 22, 23])
    
    if hour in golden:
        return "golden"
    elif hour in good:
        return "good"
    elif hour in bad:
        return "bad"
    else:
        return "normal"

def is_beta_inversion_enabled() -> bool:
    """Check if Beta-Inversion strategy is enabled. ALWAYS FALSE - disabled by data analysis."""
    return False

def is_trailing_stop_enabled() -> bool:
    """Check if trailing stops are enabled."""
    rules = _load_rules()
    return rules.get("global_settings", {}).get("trailing_stop_enabled", False)

def _would_invert_direction(symbol: str, proposed_direction: str) -> Tuple[bool, str, str]:
    """
    SHADOW: Check if we WOULD invert the proposed direction (but don't enforce).
    """
    rules = _load_rules()
    inversion_rules = rules.get("direction_inversion_rules", {})
    
    if not inversion_rules.get("enabled", False):
        return False, proposed_direction, "inversion_disabled"
    
    coins_to_invert = inversion_rules.get("coins_to_invert_long", {})
    
    if proposed_direction.upper() == "LONG" and symbol in coins_to_invert:
        coin_data = coins_to_invert[symbol]
        long_wr = coin_data.get("long_wr", 50)
        short_wr = coin_data.get("short_wr", 50)
        
        reason = f"LONG_WR={long_wr}%_SHORT_WR={short_wr}%_would_invert"
        return True, "SHORT", reason
    
    return False, proposed_direction, "no_inversion_needed"

def _would_skip_hour(hour: int = None) -> Tuple[bool, str]:
    """
    SHADOW: Check if we WOULD skip this hour (but don't enforce).
    """
    if hour is None:
        hour = get_current_hour_utc()
    
    rules = _load_rules()
    hour_rules = rules.get("hour_rules", {})
    skip_hours = hour_rules.get("skip_hours", [0, 1, 2, 11, 12, 22, 23])
    
    if hour in skip_hours:
        evidence = hour_rules.get("evidence", {}).get(f"hour_{hour}", {})
        wr = evidence.get("win_rate", 0)
        ev = evidence.get("ev", 0)
        return True, f"hour_{hour}_would_skip_WR={wr}%_EV=${ev}"
    
    return False, "hour_allowed"

def _get_hour_multiplier(hour: int = None) -> float:
    """Get position size multiplier for current hour."""
    if hour is None:
        hour = get_current_hour_utc()
    
    rules = _load_rules()
    multipliers = rules.get("hour_rules", {}).get("hour_multipliers", {})
    
    return multipliers.get(str(hour), 1.0)

def _check_aggressive_pattern(
    symbol: str, 
    direction: str, 
    ofi_score: float,
    hour: int = None
) -> Tuple[bool, float, str]:
    """
    SHADOW: Check if current trade matches an aggressive pattern.
    """
    if hour is None:
        hour = get_current_hour_utc()
    
    ofi_bucket = get_ofi_bucket(ofi_score)
    hour_bucket = get_hour_bucket(hour)
    
    rules = _load_rules()
    patterns = rules.get("aggressive_patterns", {}).get("patterns", [])
    
    for pattern in patterns:
        conditions = pattern.get("conditions", {})
        
        match = True
        if "symbol" in conditions and conditions["symbol"] != symbol:
            match = False
        if "direction" in conditions and conditions["direction"].upper() != direction.upper():
            match = False
        if "ofi_bucket" in conditions and conditions["ofi_bucket"] != ofi_bucket:
            match = False
        if "hour_bucket" in conditions and conditions["hour_bucket"] != hour_bucket:
            match = False
        if "hour" in conditions and conditions["hour"] != hour:
            match = False
        
        if match:
            multiplier = pattern.get("size_multiplier", 1.0)
            pattern_id = pattern.get("id", "unknown")
            return True, multiplier, pattern_id
    
    return False, 1.0, "no_pattern_match"

def _check_avoid_pattern(
    symbol: str,
    direction: str,
    ofi_score: float,
    hour: int = None
) -> Tuple[bool, str]:
    """
    SHADOW: Check if current trade matches a pattern to avoid.
    """
    if hour is None:
        hour = get_current_hour_utc()
    
    ofi_bucket = get_ofi_bucket(ofi_score)
    hour_bucket = get_hour_bucket(hour)
    
    rules = _load_rules()
    patterns = rules.get("avoid_patterns", {}).get("patterns", [])
    
    for pattern in patterns:
        conditions = pattern.get("conditions", {})
        
        match = True
        if "symbol" in conditions and conditions["symbol"] != symbol:
            match = False
        if "direction" in conditions and conditions["direction"].upper() != direction.upper():
            match = False
        if "ofi_bucket" in conditions and conditions["ofi_bucket"] != ofi_bucket:
            match = False
        if "hour_bucket" in conditions and conditions["hour_bucket"] != hour_bucket:
            match = False
        
        if match:
            pattern_id = pattern.get("id", "unknown")
            return True, pattern_id
    
    return False, "no_avoid_match"

def shadow_predict(
    symbol: str,
    proposed_direction: str,
    ofi_score: float,
    size_usd: float,
    hour: int = None
) -> Dict:
    """
    SHADOW MODE: Log what we WOULD do, but don't change anything.
    
    This is for data collection and pattern validation.
    All trades proceed as normal - we just log predictions.
    
    Returns prediction data for logging purposes.
    """
    if hour is None:
        hour = get_current_hour_utc()
    
    ofi_bucket = get_ofi_bucket(ofi_score)
    hour_bucket = get_hour_bucket(hour)
    
    prediction = {
        "mode": "SHADOW",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "symbol": symbol,
        "proposed_direction": proposed_direction.upper(),
        "ofi_score": ofi_score,
        "ofi_bucket": ofi_bucket,
        "hour": hour,
        "hour_bucket": hour_bucket,
        "original_size_usd": size_usd,
        "predictions": {}
    }
    
    would_skip, skip_reason = _would_skip_hour(hour)
    prediction["predictions"]["would_skip_hour"] = would_skip
    prediction["predictions"]["skip_reason"] = skip_reason
    
    would_avoid, avoid_pattern = _check_avoid_pattern(symbol, proposed_direction, ofi_score, hour)
    prediction["predictions"]["would_avoid_pattern"] = would_avoid
    prediction["predictions"]["avoid_pattern"] = avoid_pattern
    
    would_invert, new_direction, invert_reason = _would_invert_direction(symbol, proposed_direction)
    prediction["predictions"]["would_invert"] = would_invert
    prediction["predictions"]["inverted_direction"] = new_direction
    prediction["predictions"]["invert_reason"] = invert_reason
    
    is_aggressive, multiplier, pattern_id = _check_aggressive_pattern(
        symbol, 
        new_direction if would_invert else proposed_direction, 
        ofi_score, 
        hour
    )
    prediction["predictions"]["would_boost"] = is_aggressive
    prediction["predictions"]["size_multiplier"] = multiplier
    prediction["predictions"]["aggressive_pattern"] = pattern_id
    
    hour_mult = _get_hour_multiplier(hour)
    prediction["predictions"]["hour_multiplier"] = hour_mult
    
    hypothetical_size = size_usd
    if is_aggressive:
        hypothetical_size *= multiplier
    hypothetical_size *= hour_mult
    hypothetical_size = max(hypothetical_size, 200.0)
    prediction["predictions"]["hypothetical_size"] = hypothetical_size
    
    if would_skip or would_avoid:
        prediction["predictions"]["hypothetical_action"] = "SKIP"
    elif would_invert:
        prediction["predictions"]["hypothetical_action"] = f"INVERT_TO_{new_direction}"
    elif is_aggressive:
        prediction["predictions"]["hypothetical_action"] = f"BOOST_{multiplier}x"
    else:
        prediction["predictions"]["hypothetical_action"] = "NORMAL"
    
    _log_shadow_prediction(prediction)
    
    return prediction

def _log_shadow_prediction(prediction: dict):
    """Log shadow prediction to file for later analysis."""
    os.makedirs(os.path.dirname(SHADOW_LOG) or ".", exist_ok=True)
    
    with open(SHADOW_LOG, "a") as f:
        f.write(json.dumps(prediction) + "\n")

def record_outcome(
    symbol: str,
    direction: str,
    entry_price: float,
    exit_price: float,
    pnl: float,
    prediction: dict
):
    """
    Record the actual outcome of a trade to validate predictions.
    Call this when a position closes to compare prediction vs reality.
    """
    validation_record = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "symbol": symbol,
        "direction": direction,
        "entry_price": entry_price,
        "exit_price": exit_price,
        "pnl": pnl,
        "was_profitable": pnl > 0,
        "prediction": prediction.get("predictions", {}),
        "prediction_accuracy": {}
    }
    
    preds = prediction.get("predictions", {})
    
    if preds.get("would_skip_hour") or preds.get("would_avoid_pattern"):
        validation_record["prediction_accuracy"]["skip_was_correct"] = pnl < 0
    
    if preds.get("would_invert"):
        inverted_dir = preds.get("inverted_direction")
        validation_record["prediction_accuracy"]["invert_would_help"] = (
            (direction == "LONG" and pnl < 0 and inverted_dir == "SHORT") or
            (direction == "SHORT" and pnl < 0 and inverted_dir == "LONG")
        )
    
    if preds.get("would_boost"):
        validation_record["prediction_accuracy"]["boost_was_correct"] = pnl > 0
    
    os.makedirs(os.path.dirname(VALIDATION_LOG) or ".", exist_ok=True)
    with open(VALIDATION_LOG, "a") as f:
        f.write(json.dumps(validation_record) + "\n")

def analyze_shadow_predictions() -> dict:
    """
    Analyze shadow predictions to see how accurate they are.
    Call this periodically to check if patterns are working.
    """
    if not os.path.exists(VALIDATION_LOG):
        return {"error": "No validation data yet"}
    
    records = []
    with open(VALIDATION_LOG) as f:
        for line in f:
            if line.strip():
                try:
                    records.append(json.loads(line))
                except:
                    pass
    
    if not records:
        return {"error": "No validation records"}
    
    analysis = {
        "total_records": len(records),
        "skip_predictions": {"total": 0, "correct": 0},
        "invert_predictions": {"total": 0, "would_help": 0},
        "boost_predictions": {"total": 0, "correct": 0}
    }
    
    for r in records:
        accuracy = r.get("prediction_accuracy", {})
        
        if "skip_was_correct" in accuracy:
            analysis["skip_predictions"]["total"] += 1
            if accuracy["skip_was_correct"]:
                analysis["skip_predictions"]["correct"] += 1
        
        if "invert_would_help" in accuracy:
            analysis["invert_predictions"]["total"] += 1
            if accuracy["invert_would_help"]:
                analysis["invert_predictions"]["would_help"] += 1
        
        if "boost_was_correct" in accuracy:
            analysis["boost_predictions"]["total"] += 1
            if accuracy["boost_was_correct"]:
                analysis["boost_predictions"]["correct"] += 1
    
    for key in ["skip_predictions", "invert_predictions", "boost_predictions"]:
        data = analysis[key]
        if data["total"] > 0:
            accuracy_key = "correct" if key != "invert_predictions" else "would_help"
            data["accuracy_pct"] = 100 * data[accuracy_key] / data["total"]
    
    return analysis

def get_validation_summary() -> str:
    """Get human-readable summary of prediction validation."""
    analysis = analyze_shadow_predictions()
    
    if "error" in analysis:
        return f"Validation: {analysis['error']}"
    
    lines = [
        f"Shadow Prediction Validation ({analysis['total_records']} records):",
    ]
    
    skip = analysis["skip_predictions"]
    if skip["total"] > 0:
        lines.append(f"  Skip predictions: {skip.get('accuracy_pct', 0):.0f}% correct ({skip['correct']}/{skip['total']})")
    
    invert = analysis["invert_predictions"]
    if invert["total"] > 0:
        lines.append(f"  Invert predictions: {invert.get('accuracy_pct', 0):.0f}% would help ({invert['would_help']}/{invert['total']})")
    
    boost = analysis["boost_predictions"]
    if boost["total"] > 0:
        lines.append(f"  Boost predictions: {boost.get('accuracy_pct', 0):.0f}% correct ({boost['correct']}/{boost['total']})")
    
    return "\n".join(lines)

if __name__ == "__main__":
    print("Testing Shadow Mode Predictions...")
    
    pred = shadow_predict(
        symbol="ETHUSDT",
        proposed_direction="SHORT",
        ofi_score=0.85,
        size_usd=200,
        hour=8
    )
    print(f"ETHUSDT SHORT ofi=0.85 hour=8:")
    print(f"  Action: {pred['predictions']['hypothetical_action']}")
    print(f"  Size: ${pred['predictions']['hypothetical_size']:.0f}")
    
    pred = shadow_predict(
        symbol="DOGEUSDT",
        proposed_direction="LONG",
        ofi_score=0.6,
        size_usd=200,
        hour=16
    )
    print(f"\nDOGEUSDT LONG ofi=0.6 hour=16:")
    print(f"  Action: {pred['predictions']['hypothetical_action']}")
    print(f"  Would invert: {pred['predictions']['would_invert']}")
    
    pred = shadow_predict(
        symbol="XRPUSDT",
        proposed_direction="SHORT",
        ofi_score=0.7,
        size_usd=200,
        hour=11
    )
    print(f"\nXRPUSDT SHORT ofi=0.7 hour=11:")
    print(f"  Action: {pred['predictions']['hypothetical_action']}")
    print(f"  Would skip: {pred['predictions']['would_skip_hour']}")
