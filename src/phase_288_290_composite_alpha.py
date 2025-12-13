# src/phase_288_290_composite_alpha.py
#
# Phases 288–290: Composite Alpha Fusion
# - 288: Signal Normalizer (standardize OFI, micro-arb, sentiment, regime signals)
# - 289: Weighted Fusion Engine (apply regime-aware weights, compute composite score)
# - 290: Composite Gatekeeper (gate execution on composite threshold, log decisions)
#
# Purpose: Reduce false positives by executing only when multiple alpha sources align.
# Integration: Call pre_execution_gate() before any trade. Logs every decision.

import os, json, time
from typing import Dict, Any

# ---- Paths ----
LOG_DIR = "logs"
COMPOSITE_LOG = os.path.join(LOG_DIR, "composite_alpha_trace.jsonl")

# ---- Utilities ----
def _now() -> int:
    return int(time.time())

def _append_jsonl(path: str, obj: Dict[str, Any]) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "a") as f:
        f.write(json.dumps(obj) + "\n")

def _clip(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))

# ======================================================================
# 288 – Signal Normalizer
# ======================================================================
def normalize_signals(raw: Dict[str, float]) -> Dict[str, float]:
    """
    Normalize heterogeneous signals to a common scale [-1, +1].
    Expected raw keys (optional): 'ofi', 'micro_arb', 'sentiment', 'regime_strength'
    Missing keys default to 0.

    Heuristics:
    - ofi: raw z-score-like value; clamp to [-3, +3] then /3
    - micro_arb: basis points edge; clamp to [-15, +15] then /15
    - sentiment: model score in [-1, +1]; clamp directly
    - regime_strength: trend confidence in [0, 1]; transform to [-1, +1] via (2x - 1)
    """
    ofi = raw.get("ofi", 0.0)
    micro = raw.get("micro_arb", 0.0)
    senti = raw.get("sentiment", 0.0)
    regime_strength = raw.get("regime_strength", 0.0)

    ofi_norm = _clip(ofi, -3.0, 3.0) / 3.0
    micro_norm = _clip(micro, -15.0, 15.0) / 15.0
    senti_norm = _clip(senti, -1.0, 1.0)
    regime_norm = _clip(2.0 * regime_strength - 1.0, -1.0, 1.0)

    return {
        "ofi": ofi_norm,
        "micro_arb": micro_norm,
        "sentiment": senti_norm,
        "regime": regime_norm
    }

# ======================================================================
# 289 – Weighted Fusion Engine
# ======================================================================
DEFAULT_REGIME_WEIGHTS = {
    # weights sum ~1.0; adapt by regime
    "trend":     {"ofi": 0.40, "micro_arb": 0.15, "sentiment": 0.25, "regime": 0.20},
    "chop":      {"ofi": 0.25, "micro_arb": 0.40, "sentiment": 0.20, "regime": 0.15},
    "breakout":  {"ofi": 0.45, "micro_arb": 0.20, "sentiment": 0.20, "regime": 0.15},
    "mean_rev":  {"ofi": 0.20, "micro_arb": 0.45, "sentiment": 0.20, "regime": 0.15},
    "uncertain": {"ofi": 0.30, "micro_arb": 0.30, "sentiment": 0.20, "regime": 0.20},
}

REGIME_THRESHOLDS = {
    # VOLATILITY-TIERED ADJUSTMENT (Nov 23, 2025): Lowered to 0.05-0.07 for Stable/trend regime
    # Based on missed opportunity analysis showing 98.5% trades blocked with 319% avg ROI
    # Previous 0.08 trend threshold blocking high-quality signals (0.09+ composites)
    "trend": 0.07,           # Was 0.08 - relaxed for Stable regime to capture quality signals
    "chop": 0.05,            # Kept at 0.05 - matches governance patch baseline_chop
    "breakout": 0.07,        # Kept at 0.07 - allow breakout signals
    "mean_rev": 0.06,        # Kept at 0.06 - slightly conservative for mean reversion
    "uncertain": 0.07,       # Was 0.08 - lowered to match trend regime
}

def _load_adaptive_weights() -> Dict[str, Dict[str, float]]:
    """Load adaptive weights from Phase 291-293 if available, else use defaults."""
    config_path = os.path.join("config", "composite_weights.json")
    if os.path.exists(config_path):
        try:
            with open(config_path) as f:
                cfg = json.load(f)
                if "weights" in cfg:
                    return cfg["weights"]
        except:
            pass
    return DEFAULT_REGIME_WEIGHTS

def _load_adaptive_thresholds() -> Dict[str, float]:
    """Load adaptive thresholds from governance patch if available, else use defaults."""
    config_path = "live_config.json"
    if os.path.exists(config_path):
        try:
            with open(config_path) as f:
                cfg = json.load(f)
                if "filters" in cfg and "composite_thresholds" in cfg["filters"]:
                    thresholds = cfg["filters"]["composite_thresholds"]
                    # Expand to all regime keys using trend/chop as templates
                    return {
                        "trend": thresholds.get("trend", REGIME_THRESHOLDS["trend"]),
                        "chop": thresholds.get("chop", REGIME_THRESHOLDS["chop"]),
                        "breakout": thresholds.get("trend", REGIME_THRESHOLDS["breakout"]),
                        "mean_rev": thresholds.get("chop", REGIME_THRESHOLDS["mean_rev"]),
                        "uncertain": thresholds.get("trend", REGIME_THRESHOLDS["uncertain"]),
                    }
        except:
            pass
    return REGIME_THRESHOLDS

def fuse_signals(norm: Dict[str, float], regime: str) -> float:
    # Load adaptive weights if available (Phase 291-293 integration)
    REGIME_WEIGHTS = _load_adaptive_weights()
    w = REGIME_WEIGHTS.get(regime, REGIME_WEIGHTS.get("uncertain", DEFAULT_REGIME_WEIGHTS["uncertain"]))
    composite = (
        w["ofi"] * norm.get("ofi", 0.0) +
        w["micro_arb"] * norm.get("micro_arb", 0.0) +
        w["sentiment"] * norm.get("sentiment", 0.0) +
        w["regime"] * norm.get("regime", 0.0)
    )
    return composite

# ======================================================================
# 290 – Composite Gatekeeper
# ======================================================================
def composite_gate(symbol: str,
                   raw_signals: Dict[str, float],
                   regime: str,
                   expected_move_pct: float,
                   fee_cost_pct: float,
                   slippage_pct: float,
                   side: str,
                   size_multiplier: float,
                   stage: str) -> Dict[str, Any]:
    """
    Gate execution on composite score AND cost-awareness:
    - Normalize signals
    - Fuse with regime-aware weights
    - Check regime-adaptive threshold
    - Require expected_move_pct > (fee_cost_pct + slippage_pct)

    Returns decision dict with audit fields.
    """
    norm = normalize_signals(raw_signals)
    composite = fuse_signals(norm, regime)
    # Load adaptive thresholds from governance patch (live_config.json) or use defaults
    adaptive_thresholds = _load_adaptive_thresholds()
    threshold = adaptive_thresholds.get(regime, adaptive_thresholds.get("uncertain", REGIME_THRESHOLDS["uncertain"]))
    cost_floor = fee_cost_pct + slippage_pct
    pass_composite = composite >= threshold
    pass_cost = expected_move_pct > cost_floor
    allow = pass_composite and pass_cost

    decision = {
        "ts": _now(),
        "symbol": symbol,
        "side": side,
        "stage": stage,
        "regime": regime,
        "signals_raw": raw_signals,
        "signals_norm": norm,
        "composite_score": round(composite, 4),
        "threshold": round(threshold, 4),
        "expected_move_pct": round(expected_move_pct, 4),
        "fee_cost_pct": round(fee_cost_pct, 4),
        "slippage_pct": round(slippage_pct, 4),
        "cost_floor_pct": round(cost_floor, 4),
        "pass_composite": pass_composite,
        "pass_cost": pass_cost,
        "allow_trade": allow,
        "size_multiplier": round(size_multiplier, 3),
        "reason": (
            "PASS: composite & cost cleared"
            if allow else
            ("BLOCK: composite below threshold"
             if not pass_composite else
             "BLOCK: expected move <= cost")
        )
    }
    _append_jsonl(COMPOSITE_LOG, decision)
    return decision

# ======================================================================
# Orchestrator & Execution Hooks
# ======================================================================
def run_composite_alpha(symbol: str,
                        regime: str,
                        raw_signals: Dict[str, float],
                        expected_move_pct: float,
                        fee_cost_pct: float = 0.12,
                        slippage_pct: float = 0.05,
                        side: str = "BUY",
                        stage: str = "bootstrap",
                        size_multiplier: float = 0.6) -> Dict[str, Any]:
    """
    Public hook for orchestrators: compute composite decision and log it.
    """
    return composite_gate(
        symbol=symbol,
        raw_signals=raw_signals,
        regime=regime,
        expected_move_pct=expected_move_pct,
        fee_cost_pct=fee_cost_pct,
        slippage_pct=slippage_pct,
        side=side,
        size_multiplier=size_multiplier,
        stage=stage
    )

def pre_execution_gate(order: Dict[str, Any]) -> Dict[str, Any]:
    """
    Execution-bridge hook. Accepts an order dict with:
      - symbol, side, regime, stage
      - signals: {ofi, micro_arb, sentiment, regime_strength}
      - expected_move_pct
      - fee_cost_pct, slippage_pct
      - size_multiplier

    Returns decision with allow_trade flag. Caller should proceed only if allow_trade True.
    """
    symbol = order.get("symbol", "UNKNOWN")
    side = order.get("side", "BUY")
    regime = order.get("regime", "uncertain")
    stage = order.get("stage", "bootstrap")
    signals = order.get("signals", {})
    expected_move_pct = float(order.get("expected_move_pct", 0.0))
    fee_cost_pct = float(order.get("fee_cost_pct", 0.12))
    slippage_pct = float(order.get("slippage_pct", 0.05))
    size_multiplier = float(order.get("size_multiplier", 0.6))

    decision = composite_gate(
        symbol=symbol,
        raw_signals=signals,
        regime=regime,
        expected_move_pct=expected_move_pct,
        fee_cost_pct=fee_cost_pct,
        slippage_pct=slippage_pct,
        side=side,
        size_multiplier=size_multiplier,
        stage=stage
    )
    return decision

if __name__ == "__main__":
    example_order = {
        "symbol": "SOLUSDT",
        "side": "BUY",
        "regime": "trend",
        "stage": "bootstrap",
        "signals": {
            "ofi": 1.8,
            "micro_arb": 8.0,
            "sentiment": 0.35,
            "regime_strength": 0.7
        },
        "expected_move_pct": 0.65,
        "fee_cost_pct": 0.12,
        "slippage_pct": 0.05,
        "size_multiplier": 0.6
    }
    result = pre_execution_gate(example_order)
    print("Composite alpha decision:", json.dumps(result, indent=2))
