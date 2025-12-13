#!/usr/bin/env python3
"""
INTELLIGENCE-BASED SIGNAL INVERSION
====================================
Applies promoted intelligence rules to invert signals based on comprehensive 
analysis of 630 enriched decisions showing systematic signal misprediction.

Key Finding: Signals are systematically inverted - actual WR 16-22% vs 78-84% if inverted.

Usage:
    from src.intelligence_inversion import apply_intelligence_inversion
    
    modified_signal = apply_intelligence_inversion(signal, bot_id="alpha")
"""

import json
import os
from datetime import datetime
from typing import Any, Dict, Optional, Tuple

RULES_PATH = "feature_store/promoted_intelligence_rules.json"
DEFAULTS = {
    "global_strategy": {"default_action": "INVERT"},
    "symbol_rules": [],
    "ofi_rules": {},
    "ensemble_rules": {}
}


def load_intelligence_rules() -> Dict:
    """Load promoted intelligence rules from file."""
    if os.path.exists(RULES_PATH):
        try:
            with open(RULES_PATH, "r") as f:
                return json.load(f)
        except Exception as e:
            print(f"[INTEL] Failed to load rules: {e}")
    return DEFAULTS


def get_symbol_rule(rules: Dict, symbol: str, direction: str) -> Dict:
    """Get inversion rule for a specific symbol and direction."""
    symbol_rules = rules.get("symbol_rules", [])
    
    dir_map = {"LONG": "buy", "SHORT": "sell", "BUY": "buy", "SELL": "sell"}
    dir_key = dir_map.get(direction.upper(), direction.lower())
    
    for rule in symbol_rules:
        if rule.get("symbol") == symbol:
            action_key = f"{dir_key}_action"
            action = rule.get(action_key, rule.get("action", "INVERT"))
            return {
                "action": action,
                "wr": rule.get(f"{dir_key}_wr", 0),
                "inverted_wr": rule.get(f"inverted_{dir_key}_wr", 0)
            }
    
    return {"action": rules.get("global_strategy", {}).get("default_action", "INVERT")}


def should_invert_ensemble(rules: Dict, ensemble: float) -> bool:
    """Check if we should invert based on ensemble (market sentiment)."""
    ensemble_rules = rules.get("ensemble_rules", {})
    
    if ensemble > 0.05:
        bullish_rule = ensemble_rules.get("bullish", {})
        return bullish_rule.get("action", "INVERT") == "INVERT"
    
    return False


def get_ofi_preference(rules: Dict, ofi: float) -> str:
    """Get OFI-based action (PREFER, ALLOW, CAUTIOUS)."""
    ofi_rules = rules.get("ofi_rules", {})
    abs_ofi = abs(ofi)
    
    if abs_ofi < 0.3:
        return ofi_rules.get("weak", {}).get("action", "ALLOW")
    elif abs_ofi < 0.5:
        return ofi_rules.get("moderate", {}).get("action", "ALLOW")
    elif abs_ofi < 0.7:
        return ofi_rules.get("strong", {}).get("action", "CAUTIOUS")
    else:
        return ofi_rules.get("very_strong", {}).get("action", "CAUTIOUS")


def invert_direction(direction: str) -> str:
    """Invert a direction (BUY/LONG -> SELL/SHORT and vice versa)."""
    direction_upper = direction.upper()
    
    if direction_upper in ("BUY", "LONG"):
        return "SHORT"
    elif direction_upper in ("SELL", "SHORT"):
        return "LONG"
    
    return direction


def get_adaptation_override(rules: Dict, symbol: str, direction: str) -> Optional[Dict]:
    """Check if adaptation layer has an override for this symbol/direction."""
    adaptation = rules.get("adaptation_layer", {})
    overrides = adaptation.get("symbol_overrides", {})
    
    if symbol in overrides:
        dir_key = "LONG" if direction.upper() in ("LONG", "BUY") else "SHORT"
        if dir_key in overrides[symbol]:
            return overrides[symbol][dir_key]
    
    return None


def apply_intelligence_inversion(
    signal: Dict[str, Any],
    bot_id: str = "alpha",
    force_invert: bool = False,
    force_follow: bool = False
) -> Dict[str, Any]:
    """
    Apply adaptive intelligence-based inversion to a signal.
    
    ADAPTIVE LOGIC (learns when to invert vs follow):
    1. Check adaptation layer (learned from live performance) first
    2. If adaptation says FOLLOW - don't invert even if base rules say invert
    3. If adaptation says INVERT - invert
    4. If adaptation says NEUTRAL - use base rules
    5. Base rules from 630 enriched decisions analysis
    
    Args:
        signal: Original signal dict with 'direction', 'symbol', 'ofi', 'ensemble'
        bot_id: "alpha" or "beta" - determines inversion behavior
        force_invert: Override rules and always invert
        force_follow: Override rules and always follow (no inversion)
        
    Returns:
        Modified signal with inversion applied if appropriate
    """
    rules = load_intelligence_rules()
    modified = signal.copy()
    
    symbol = signal.get("symbol", "UNKNOWN")
    direction = signal.get("direction", signal.get("side", "LONG")).upper()
    ofi = signal.get("ofi", 0.5)
    ensemble = signal.get("ensemble", 0)
    
    if direction == "BUY":
        direction = "LONG"
    elif direction == "SELL":
        direction = "SHORT"
    
    modified["original_direction"] = direction
    modified["inverted"] = False
    modified["inversion_reason"] = None
    modified["bot_id"] = bot_id
    modified["adaptation_applied"] = False
    
    should_invert = False
    inversion_reason = None
    
    if force_follow:
        should_invert = False
        inversion_reason = "forced_follow"
    elif force_invert:
        should_invert = True
        inversion_reason = "forced_inversion"
    else:
        adaptation = get_adaptation_override(rules, symbol, direction)
        
        if adaptation:
            modified["adaptation_applied"] = True
            action = adaptation.get("action", "NEUTRAL")
            
            if action == "FOLLOW":
                should_invert = False
                inversion_reason = f"adaptation_follow: {adaptation.get('reason', 'learned from performance')}"
            elif action == "INVERT":
                should_invert = True
                inversion_reason = f"adaptation_invert: {adaptation.get('reason', 'learned from performance')}"
        
        if not modified["adaptation_applied"]:
            symbol_rule = get_symbol_rule(rules, symbol, direction)
            
            if symbol_rule.get("action") == "INVERT":
                should_invert = True
                inversion_reason = f"symbol_rule: {symbol} {direction} (WR: {symbol_rule.get('wr', 0)}% -> {symbol_rule.get('inverted_wr', 0)}%)"
            elif symbol_rule.get("action") == "FOLLOW":
                should_invert = False
                inversion_reason = f"symbol_rule: {symbol} {direction} has good WR - follow signal"
            
            if should_invert_ensemble(rules, ensemble) and not should_invert:
                should_invert = True
                inversion_reason = f"ensemble_rule: bullish sentiment ({ensemble:.3f} > 0.05) has 12.9% WR"
    
    if should_invert:
        new_direction = invert_direction(direction)
        modified["direction"] = new_direction
        modified["inverted"] = True
        modified["inversion_reason"] = inversion_reason
        
        log_inversion(symbol, direction, new_direction, inversion_reason, bot_id)
    else:
        modified["direction"] = direction
        if inversion_reason:
            modified["follow_reason"] = inversion_reason
    
    ofi_action = get_ofi_preference(rules, ofi)
    modified["ofi_action"] = ofi_action
    
    if ofi_action == "CAUTIOUS" and abs(ofi) > 0.7:
        modified["size_modifier"] = 0.7
        modified["ofi_note"] = "Very strong OFI (>0.7) has 17.9% WR - reduced sizing"
    elif 0.3 <= abs(ofi) <= 0.5:
        modified["size_modifier"] = 1.2
        modified["ofi_note"] = "Moderate OFI (0.3-0.5) has best WR (25.5%) - boosted sizing"
    else:
        modified["size_modifier"] = 1.0
    
    return modified


def log_inversion(symbol: str, original: str, new: str, reason: str, bot_id: str):
    """Log inversion for audit trail."""
    ts = datetime.utcnow().isoformat() + "Z"
    print(f"[{ts}] [INTEL-INVERT] [{bot_id.upper()}] {symbol}: {original} -> {new} | {reason}")


def get_inversion_stats(rules: Dict = None) -> Dict:
    """Get summary statistics from intelligence rules."""
    if rules is None:
        rules = load_intelligence_rules()
    
    return {
        "source": rules.get("analysis_source", "unknown"),
        "key_finding": rules.get("key_finding", ""),
        "global_action": rules.get("global_strategy", {}).get("default_action", "INVERT"),
        "symbol_count": len(rules.get("symbol_rules", [])),
        "expected_improvement": rules.get("expected_improvement", {}),
        "version": rules.get("version", "1.0")
    }


if __name__ == "__main__":
    test_signal = {
        "symbol": "BTCUSDT",
        "direction": "BUY",
        "ofi": 0.4,
        "ensemble": 0.08
    }
    
    print("=" * 60)
    print("INTELLIGENCE INVERSION TEST")
    print("=" * 60)
    
    print(f"\nOriginal signal: {test_signal}")
    
    inverted = apply_intelligence_inversion(test_signal, bot_id="alpha")
    print(f"\nInverted signal: {inverted}")
    
    print(f"\n  Direction: {inverted['original_direction']} -> {inverted['direction']}")
    print(f"  Inverted: {inverted['inverted']}")
    print(f"  Reason: {inverted['inversion_reason']}")
    print(f"  OFI Action: {inverted['ofi_action']}")
    print(f"  Size Modifier: {inverted['size_modifier']}")
    
    stats = get_inversion_stats()
    print(f"\nInversion Stats: {stats}")
