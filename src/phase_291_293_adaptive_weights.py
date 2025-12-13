# src/phase_291_293_adaptive_weights.py
#
# Phases 291–293: Adaptive Weight Learner
# - 291: Signal Attribution Tracker (rolling expectancy per signal: ofi, micro_arb, sentiment, regime)
# - 292: Weight Optimizer (adjust regime-aware fusion weights from rolling performance)
# - 293: Weight Publisher (write updated weights to config for Phase 289 fusion engine)
#
# Purpose: Make Composite Alpha Fusion adaptive. Learn which signals add lift per regime
# and update weights nightly based on audited decisions.

import os, json, time
from collections import defaultdict
from typing import Dict, Any, List

LOG_DIR = "logs"
CONFIG_DIR = "config"
COMPOSITE_LOG = os.path.join(LOG_DIR, "composite_alpha_trace.jsonl")
EXPECTANCY_LOG = os.path.join(LOG_DIR, "expectancy_trace.jsonl")
ADAPTIVE_TRACE = os.path.join(LOG_DIR, "adaptive_weights_trace.jsonl")
WEIGHTS_CONFIG = os.path.join(CONFIG_DIR, "composite_weights.json")

DEFAULT_WEIGHTS = {
    "trend":     {"ofi": 0.40, "micro_arb": 0.15, "sentiment": 0.25, "regime": 0.20},
    "chop":      {"ofi": 0.25, "micro_arb": 0.40, "sentiment": 0.20, "regime": 0.15},
    "breakout":  {"ofi": 0.45, "micro_arb": 0.20, "sentiment": 0.20, "regime": 0.15},
    "mean_rev":  {"ofi": 0.20, "micro_arb": 0.45, "sentiment": 0.20, "regime": 0.15},
    "uncertain": {"ofi": 0.30, "micro_arb": 0.30, "sentiment": 0.20, "regime": 0.20}
}

def _now() -> int: 
    return int(time.time())

def _read_json(path: str, default=None):
    return json.load(open(path)) if os.path.exists(path) else (default if default is not None else {})

def _write_json(path: str, obj: Dict[str, Any]) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    json.dump(obj, open(path, "w"), indent=2)

def _append_jsonl(path: str, obj: Dict[str, Any]) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    open(path, "a").write(json.dumps(obj) + "\n")

def _read_jsonl(path: str) -> List[Dict[str, Any]]:
    return [json.loads(l) for l in open(path)] if os.path.exists(path) else []

def _clip(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))

def _extract_signal_contributions(entry: Dict[str, Any]) -> Dict[str, float]:
    norm = entry.get("signals_norm", {})
    regime = entry.get("regime", "uncertain")
    w = DEFAULT_WEIGHTS.get(regime, DEFAULT_WEIGHTS["uncertain"])
    comp_parts = {
        "ofi": abs(w["ofi"] * float(norm.get("ofi", 0.0))),
        "micro_arb": abs(w["micro_arb"] * float(norm.get("micro_arb", 0.0))),
        "sentiment": abs(w["sentiment"] * float(norm.get("sentiment", 0.0))),
        "regime": abs(w["regime"] * float(norm.get("regime", 0.0))),
    }
    total = sum(comp_parts.values())
    if total <= 0:
        return {k: 0.0 for k in comp_parts.keys()}
    shares = {k: v / total for k, v in comp_parts.items()}
    return shares

def _expected_value_from_entry(entry: Dict[str, Any]) -> float:
    ev = entry.get("ev")
    if ev is not None:
        try: 
            return float(ev)
        except: 
            pass
    em = float(entry.get("expected_move_pct", 0.0))
    cost = float(entry.get("fee_cost_pct", 0.0)) + float(entry.get("slippage_pct", 0.0))
    allow = bool(entry.get("allow_trade", False))
    return (em - cost) if allow else 0.0

def track_rolling_attribution(window: int = 500) -> Dict[str, Dict[str, float]]:
    entries = _read_jsonl(COMPOSITE_LOG)
    entries = entries[-window:]
    regime_signal_ev = defaultdict(lambda: defaultdict(float))
    regime_counts = defaultdict(int)

    for e in entries:
        regime = e.get("regime", "uncertain")
        shares = _extract_signal_contributions(e)
        ev = _expected_value_from_entry(e)
        for sig, share in shares.items():
            regime_signal_ev[regime][sig] += ev * share
        regime_counts[regime] += 1

    for regime in regime_signal_ev.keys():
        count = max(1, regime_counts.get(regime, 1))
        for sig in regime_signal_ev[regime].keys():
            regime_signal_ev[regime][sig] = regime_signal_ev[regime][sig] / count

    return regime_signal_ev

def optimize_weights(rolling_ev: Dict[str, Dict[str, float]],
                     base_weights: Dict[str, Dict[str, float]] = None,
                     learning_rate: float = 0.15,
                     min_weight: float = 0.05,
                     max_weight: float = 0.60) -> Dict[str, Dict[str, float]]:
    base = base_weights or DEFAULT_WEIGHTS
    updated = {}

    for regime, bw in base.items():
        evs = rolling_ev.get(regime, {"ofi": 0.0, "micro_arb": 0.0, "sentiment": 0.0, "regime": 0.0})
        vals = [evs.get("ofi", 0.0), evs.get("micro_arb", 0.0), evs.get("sentiment", 0.0), evs.get("regime", 0.0)]
        m = min(vals)
        shifted = [v - m + 1e-5 for v in vals]
        total_shifted = sum(shifted)
        shares = [v / total_shifted for v in shifted] if total_shifted > 0 else [0.25, 0.25, 0.25, 0.25]
        target = {
            "ofi": shares[0],
            "micro_arb": shares[1],
            "sentiment": shares[2],
            "regime": shares[3],
        }
        new_w = {k: bw[k] + learning_rate * (target[k] - bw[k]) for k in bw.keys()}
        new_w = {k: _clip(v, min_weight, max_weight) for k, v in new_w.items()}
        s = sum(new_w.values())
        if s == 0:
            new_w = {"ofi": 0.25, "micro_arb": 0.25, "sentiment": 0.25, "regime": 0.25}
        else:
            new_w = {k: v / s for k, v in new_w.items()}
        updated[regime] = new_w

    return updated

def publish_weights(weights: Dict[str, Dict[str, float]]) -> None:
    _write_json(WEIGHTS_CONFIG, {"ts": _now(), "weights": weights})

def load_current_weights() -> Dict[str, Dict[str, float]]:
    cfg = _read_json(WEIGHTS_CONFIG, {})
    if "weights" in cfg:
        return cfg["weights"]
    return DEFAULT_WEIGHTS

def run_adaptive_weight_update(window: int = 500,
                               learning_rate: float = 0.15,
                               min_weight: float = 0.05,
                               max_weight: float = 0.60) -> Dict[str, Any]:
    rolling_ev = track_rolling_attribution(window=window)
    current = load_current_weights()
    updated = optimize_weights(rolling_ev, base_weights=current,
                               learning_rate=learning_rate,
                               min_weight=min_weight, max_weight=max_weight)
    publish_weights(updated)

    audit = {
        "ts": _now(),
        "window": window,
        "learning_rate": learning_rate,
        "min_weight": min_weight,
        "max_weight": max_weight,
        "rolling_ev": rolling_ev,
        "old_weights": current,
        "new_weights": updated
    }
    _append_jsonl(ADAPTIVE_TRACE, audit)
    return audit

if __name__ == "__main__":
    summary = run_adaptive_weight_update(window=500, learning_rate=0.15)
    print("Adaptive weight learner summary:", json.dumps(summary, indent=2))
