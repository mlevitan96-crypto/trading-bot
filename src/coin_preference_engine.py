"""
Coin Preference Engine - Pick right coins first, adjust sizing by tier.

Based on EV analysis:
- TIER 1 (FOCUS): Boost sizing 1.2x - least negative EV, best potential
- TIER 2 (NEUTRAL): Normal sizing 1.0x
- TIER 3 (REDUCE): Reduce sizing 0.5x - worst EV, trade less
"""

import json
import os
from datetime import datetime, timedelta
from typing import Dict, Optional, Tuple

COIN_TIERS_PATH = "feature_store/coin_tier_recommendations.json"
COIN_PERF_CACHE_PATH = "feature_store/coin_performance_cache.json"
ENRICHED_DECISIONS_PATH = "logs/enriched_decisions.jsonl"

TIER_MULTIPLIERS = {
    "tier1": 1.2,   # Focus coins - boost
    "tier2": 1.0,   # Neutral - normal
    "tier3": 0.5,   # Reduce - halve sizing
    "unknown": 0.8  # New/unknown coins - conservative
}

WORST_COMBO_BLOCK_THRESHOLD = -30.0  # Block symbol+direction combos losing > $30


def load_coin_tiers() -> Dict:
    """Load coin tier recommendations."""
    try:
        if os.path.exists(COIN_TIERS_PATH):
            with open(COIN_TIERS_PATH, 'r') as f:
                return json.load(f)
    except Exception as e:
        print(f"⚠️ Could not load coin tiers: {e}")
    return {"tier1_focus": [], "tier2_neutral": [], "tier3_reduce": []}


def get_coin_tier(symbol: str) -> str:
    """Get the tier for a coin."""
    tiers = load_coin_tiers()
    
    if symbol in tiers.get("tier1_focus", []):
        return "tier1"
    elif symbol in tiers.get("tier2_neutral", []):
        return "tier2"
    elif symbol in tiers.get("tier3_reduce", []):
        return "tier3"
    else:
        return "unknown"


def get_size_multiplier(symbol: str) -> float:
    """Get position size multiplier based on coin tier."""
    tier = get_coin_tier(symbol)
    return TIER_MULTIPLIERS.get(tier, 1.0)


def should_block_combo(symbol: str, direction: str) -> Tuple[bool, str]:
    """
    Check if a symbol+direction combo should be blocked due to extreme losses.
    Returns (should_block, reason).
    """
    try:
        if not os.path.exists(ENRICHED_DECISIONS_PATH):
            return False, ""
        
        combo_stats = {}
        with open(ENRICHED_DECISIONS_PATH, 'r') as f:
            for line in f:
                if line.strip():
                    trade = json.loads(line)
                    sym = trade.get('symbol', '')
                    dir_ = trade.get('direction', '') or trade.get('side', '')
                    pnl = trade.get('pnl', 0) or trade.get('net_pnl', 0) or 0
                    
                    key = f"{sym}|{dir_}"
                    if key not in combo_stats:
                        combo_stats[key] = {'total_pnl': 0, 'trades': 0}
                    combo_stats[key]['total_pnl'] += pnl
                    combo_stats[key]['trades'] += 1
        
        combo_key = f"{symbol}|{direction}"
        if combo_key in combo_stats:
            stats = combo_stats[combo_key]
            if stats['total_pnl'] < WORST_COMBO_BLOCK_THRESHOLD and stats['trades'] >= 5:
                return True, f"Combo {combo_key} lost ${abs(stats['total_pnl']):.0f} over {stats['trades']} trades"
        
        return False, ""
        
    except Exception as e:
        print(f"⚠️ Combo block check error: {e}")
        return False, ""


def apply_coin_preference(symbol: str, direction: str, base_size: float) -> Tuple[float, str]:
    """
    Apply coin preference logic to adjust position size.
    Returns (adjusted_size, reason).
    """
    reasons = []
    final_size = base_size
    
    # Check if combo is blocked
    blocked, block_reason = should_block_combo(symbol, direction)
    if blocked:
        return 0.0, f"BLOCKED: {block_reason}"
    
    # Apply tier multiplier
    tier = get_coin_tier(symbol)
    multiplier = TIER_MULTIPLIERS.get(tier, 1.0)
    
    if multiplier != 1.0:
        final_size = base_size * multiplier
        if tier == "tier1":
            reasons.append(f"TIER1 boost: {multiplier}x")
        elif tier == "tier3":
            reasons.append(f"TIER3 reduce: {multiplier}x")
        elif tier == "unknown":
            reasons.append(f"Unknown coin: {multiplier}x conservative")
    
    reason_str = " | ".join(reasons) if reasons else "No adjustment"
    return final_size, reason_str


def refresh_coin_tiers():
    """
    Refresh coin tier recommendations based on latest trade data.
    Should be called nightly or on demand.
    """
    try:
        if not os.path.exists(ENRICHED_DECISIONS_PATH):
            print("⚠️ No enriched decisions found for coin tier refresh")
            return
        
        # Aggregate by symbol
        by_symbol = {}
        with open(ENRICHED_DECISIONS_PATH, 'r') as f:
            for line in f:
                if line.strip():
                    trade = json.loads(line)
                    sym = trade.get('symbol', 'UNKNOWN')
                    pnl = trade.get('pnl', 0) or trade.get('net_pnl', 0) or 0
                    
                    if sym not in by_symbol:
                        by_symbol[sym] = {'trades': 0, 'wins': 0, 'total_pnl': 0}
                    by_symbol[sym]['trades'] += 1
                    by_symbol[sym]['total_pnl'] += pnl
                    if pnl > 0:
                        by_symbol[sym]['wins'] += 1
        
        # Calculate EV for each
        for sym in by_symbol:
            stats = by_symbol[sym]
            stats['ev'] = stats['total_pnl'] / stats['trades'] if stats['trades'] > 0 else 0
        
        # Sort by EV (best to worst)
        sorted_coins = sorted(
            [(s, d) for s, d in by_symbol.items() if d['trades'] >= 10],
            key=lambda x: x[1]['ev'],
            reverse=True
        )
        
        # Split into tiers
        n = len(sorted_coins)
        tier1_count = max(1, n // 3)
        tier3_count = max(1, n // 4)
        
        tier1 = [s for s, _ in sorted_coins[:tier1_count]]
        tier2 = [s for s, _ in sorted_coins[tier1_count:-tier3_count]] if n > 4 else []
        tier3 = [s for s, _ in sorted_coins[-tier3_count:]] if tier3_count > 0 else []
        
        # Save
        tiers = {
            "generated_at": datetime.utcnow().isoformat() + "Z",
            "tier1_focus": tier1,
            "tier2_neutral": tier2,
            "tier3_reduce": tier3,
            "by_symbol": {s: {"ev": d["ev"], "trades": d["trades"]} for s, d in by_symbol.items()}
        }
        
        with open(COIN_TIERS_PATH, 'w') as f:
            json.dump(tiers, f, indent=2)
        
        print(f"✅ Coin tiers refreshed: T1={tier1}, T2={tier2}, T3={tier3}")
        
    except Exception as e:
        print(f"❌ Coin tier refresh error: {e}")


def get_coin_preference_summary() -> Dict:
    """Get summary of coin preference state."""
    tiers = load_coin_tiers()
    return {
        "tier1_focus": tiers.get("tier1_focus", []),
        "tier2_neutral": tiers.get("tier2_neutral", []),
        "tier3_reduce": tiers.get("tier3_reduce", []),
        "tier_multipliers": TIER_MULTIPLIERS,
        "block_threshold": WORST_COMBO_BLOCK_THRESHOLD
    }


if __name__ == "__main__":
    print("=== Coin Preference Engine ===\n")
    
    # Refresh tiers
    refresh_coin_tiers()
    
    # Show summary
    summary = get_coin_preference_summary()
    print(f"\nTIER 1 (Focus, 1.2x): {summary['tier1_focus']}")
    print(f"TIER 2 (Neutral, 1.0x): {summary['tier2_neutral']}")
    print(f"TIER 3 (Reduce, 0.5x): {summary['tier3_reduce']}")
    
    # Test some coins
    print("\n=== Test Adjustments ===")
    test_cases = [
        ("TRXUSDT", "LONG", 100),
        ("BTCUSDT", "SHORT", 100),
        ("DOTUSDT", "SHORT", 100),
        ("BNBUSDT", "SHORT", 100),
    ]
    
    for sym, dir_, size in test_cases:
        adj_size, reason = apply_coin_preference(sym, dir_, size)
        print(f"{sym} {dir_} ${size} -> ${adj_size:.0f} | {reason}")
