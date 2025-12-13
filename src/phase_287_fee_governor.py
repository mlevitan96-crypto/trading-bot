# src/phase_287_fee_governor.py
#
# Phase 287: Fee-Aware Governor
# Purpose: Block trades where expected move <= fees + slippage.
# Integrated directly into exploration policy and entry gates.

import os, json, time

LOG_DIR = "logs"
FEE_GOVERNOR_LOG = os.path.join(LOG_DIR, "fee_governor_trace.jsonl")
FEE_TIER_CONFIG = "config/fee_tier_config.json"

def _now(): return int(time.time())
def _append_jsonl(path, obj): os.makedirs(os.path.dirname(path), exist_ok=True); open(path, "a").write(json.dumps(obj) + "\n")

def _load_fee_tiers():
    """Load volatility-tiered fee configuration."""
    if os.path.exists(FEE_TIER_CONFIG):
        try:
            with open(FEE_TIER_CONFIG) as f:
                return json.load(f).get("fee_tiers", {})
        except:
            pass
    return {}

def _get_symbol_tier(symbol):
    """Get fee tier parameters for a specific symbol."""
    tiers = _load_fee_tiers()
    for tier_name, tier_config in tiers.items():
        if symbol in tier_config.get("symbols", []):
            return tier_config
    # Default to medium volatility if not found
    return {"threshold_pct": 0.10, "fee_pct": 0.06, "slippage_pct": 0.04}

# ======================================================================
# Fee-Aware Governor Core
# ======================================================================
def fee_aware_gate(symbol, expected_move_pct, fee_pct=None, slippage_pct=None):
    """
    Decide whether a trade should be allowed based on expected move vs cost.
    Uses volatility-tiered thresholds from config (BTC/ETH: 0.08%, mid-vol: 0.10%, high-vol: 0.12%).
    expected_move_pct: projected % move (e.g., 1.5 for 1.5%)
    fee_pct: trading fee % per side (default: from tier config, 0.06%)
    slippage_pct: estimated slippage % (default: from tier config, varies by asset)
    Returns: dict with decision and reason
    """
    # Use tier-specific parameters if not provided
    tier_config = _get_symbol_tier(symbol)
    if fee_pct is None:
        fee_pct = tier_config.get("fee_pct", 0.06)
    if slippage_pct is None:
        slippage_pct = tier_config.get("slippage_pct", 0.04)
    
    # Use threshold_pct from tier config if available (preferred method)
    # This is the total cost threshold (fees + slippage) that expected move must exceed
    threshold_pct = tier_config.get("threshold_pct")
    if threshold_pct is not None:
        total_cost = threshold_pct
    else:
        # Fallback to calculating from components
        total_cost = fee_pct * 2 + slippage_pct  # entry + exit fees + slippage
    
    allow_trade = expected_move_pct > total_cost

    decision = {
        "ts": _now(),
        "symbol": symbol,
        "expected_move_pct": expected_move_pct,
        "fee_pct": fee_pct,
        "slippage_pct": slippage_pct,
        "total_cost_pct": round(total_cost, 4),
        "tier": tier_config.get("description", "default"),
        "allow_trade": allow_trade,
        "reason": "PASS" if allow_trade else f"BLOCK: expected move {expected_move_pct:.3f}% <= cost {total_cost:.3f}%"
    }

    _append_jsonl(FEE_GOVERNOR_LOG, decision)
    return decision

# ======================================================================
# Exploration Policy Integration
# ======================================================================
def exploration_policy(symbol, expected_move_pct, stage="bootstrap"):
    """
    Exploration policy with fee-aware gating.
    Stage controls quota and sizing multipliers.
    """
    # Fee-aware check first
    governor_decision = fee_aware_gate(symbol, expected_move_pct)
    if not governor_decision["allow_trade"]:
        return {
            "symbol": symbol,
            "stage": stage,
            "exploration_allowed": False,
            "reason": governor_decision["reason"]
        }

    # Stage-specific exploration quotas
    quotas = {"bootstrap": 12, "unlocked": 8, "high_confidence": 4}
    size_multipliers = {"bootstrap": 0.6, "unlocked": 1.0, "high_confidence": 1.4}

    decision = {
        "symbol": symbol,
        "stage": stage,
        "exploration_allowed": True,
        "quota": quotas.get(stage, 4),
        "size_multiplier": size_multipliers.get(stage, 1.0),
        "reason": "PASS: expected move clears fee cost"
    }
    _append_jsonl(FEE_GOVERNOR_LOG, decision)
    return decision

# ======================================================================
# Orchestrator Hook
# ======================================================================
def run_fee_governor(symbol, expected_move_pct, stage="bootstrap"):
    """
    Public hook for orchestrator integration.
    """
    return exploration_policy(symbol, expected_move_pct, stage)

if __name__ == "__main__":
    # Example test
    summary = run_fee_governor("TRXUSDT", 0.20, stage="bootstrap")  # 0.20% expected move
    print("Fee Governor + Exploration decision:", json.dumps(summary, indent=2))
