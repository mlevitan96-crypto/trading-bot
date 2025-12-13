# src/phase_42_45.py
#
# Phases 42–45: Exit Pair Optimizer, Exit Evolution, Regime Memory, Drift Detector

import os
import json
import time
from statistics import mean, stdev
from typing import Dict, List, Any

# Paths
STRATEGIC_ATTRIBUTION = "logs/strategic_attribution.jsonl"
TRADE_OUTCOMES = "logs/trade_outcomes.jsonl"
EXIT_PROFILES = "config/exit_profiles.json"
STRATEGY_REGISTRY = "config/strategy_registry.json"
SHADOW_STATE = "config/shadow_strategy_state.json"
REGIME_FORECAST = "logs/regime_forecast.json"
EXIT_PAIRING_LOG = "logs/strategy_exit_pairing.jsonl"
EXIT_EVOLUTION_LOG = "logs/exit_profile_evolution.jsonl"
REGIME_MEMORY_LOG = "logs/symbol_regime_memory.json"
DRIFT_LOG = "logs/attribution_drift_events.jsonl"

# Utilities
def _read_json(path: str, default: dict):
    if not os.path.exists(path):
        return default
    with open(path, "r") as f:
        try:
            return json.load(f)
        except Exception:
            return default

def _write_json(path: str, obj: dict):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        json.dump(obj, f, indent=2)

def _read_jsonl(path: str):
    if not os.path.exists(path):
        return []
    out = []
    with open(path, "r") as f:
        for line in f:
            s = line.strip()
            if s:
                try:
                    out.append(json.loads(s))
                except Exception:
                    pass
    return out

def _append_event(path: str, ev: str, payload: dict = None):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if payload is None:
        payload = {}
    else:
        payload = dict(payload)
    payload.update({"event": ev, "ts": int(time.time())})
    with open(path, "a") as f:
        f.write(json.dumps(payload) + "\n")

# ---- Phase 42.0 – Strategy-Exit Pair Optimizer ----
def optimize_exit_pairing():
    """
    Match each strategy variant with its best-performing exit profile:
    - Analyze real trade outcomes by strategy + exit profile
    - Calculate score: avg_roi * 100 + win_rate * 50
    - Assign best exit profile to each strategy
    """
    trade_outcomes = _read_jsonl(TRADE_OUTCOMES)
    shadow_state = _read_json(SHADOW_STATE, {})
    exit_profiles = _read_json(EXIT_PROFILES, {})
    
    pairings = {}
    
    # Group trades by strategy and exit profile
    by_strategy_exit = {}
    for trade in trade_outcomes:
        strategy = trade.get("strategy", "")
        exit_profile = trade.get("exit_profile_id", "")
        roi = trade.get("net_roi", 0.0)
        
        if not strategy or not exit_profile:
            continue
        
        key = f"{strategy}::{exit_profile}"
        if key not in by_strategy_exit:
            by_strategy_exit[key] = []
        by_strategy_exit[key].append(roi)
    
    # Find best exit profile for each strategy
    by_strategy = {}
    for key, roi_list in by_strategy_exit.items():
        strategy, exit_profile = key.split("::")
        
        if len(roi_list) < 3:
            continue  # Need minimum data
        
        avg_roi = mean(roi_list)
        win_rate = sum(1 for r in roi_list if r > 0) / len(roi_list)
        score = avg_roi * 100 + win_rate * 50
        
        if strategy not in by_strategy:
            by_strategy[strategy] = {"best_profile": exit_profile, "best_score": score}
        elif score > by_strategy[strategy]["best_score"]:
            by_strategy[strategy] = {"best_profile": exit_profile, "best_score": score}
    
    # Update shadow state with best pairings
    for base_strategy, variants in shadow_state.items():
        for i, variant in enumerate(variants):
            variant_id = variant.get("variant_id", "")
            if variant_id in by_strategy:
                best_profile = by_strategy[variant_id]["best_profile"]
                shadow_state[base_strategy][i]["exit_profile_id"] = best_profile
                
                pairings[variant_id] = {
                    "exit_profile": best_profile,
                    "score": round(by_strategy[variant_id]["best_score"], 2)
                }
                
                _append_event(EXIT_PAIRING_LOG, "exit_profile_assigned", {
                    "strategy": variant_id,
                    "exit_profile_id": best_profile,
                    "score": round(by_strategy[variant_id]["best_score"], 2)
                })
    
    _write_json(SHADOW_STATE, shadow_state)
    return pairings

# ---- Phase 43.0 – Exit Profile Evolution Engine ----
def evolve_exit_profiles():
    """
    Evolve exit profiles based on performance:
    - Clone successful profiles (avg ROI > 0.3%)
    - Mutate parameters: TP1/TP2 levels, ATR multipliers
    - Retire poor performers (avg ROI < -0.2%)
    """
    trade_outcomes = _read_jsonl(TRADE_OUTCOMES)
    exit_profiles = _read_json(EXIT_PROFILES, {})
    
    # Group trades by exit profile
    by_profile = {}
    for trade in trade_outcomes:
        profile_id = trade.get("exit_profile_id", "")
        roi = trade.get("net_roi", 0.0)
        
        if not profile_id:
            continue
        
        if profile_id not in by_profile:
            by_profile[profile_id] = []
        by_profile[profile_id].append(roi)
    
    evolutions = []
    
    for profile_id, roi_list in by_profile.items():
        if len(roi_list) < 10:
            continue  # Need minimum data
        
        avg_roi = mean(roi_list)
        
        # Clone successful profiles
        if avg_roi > 0.003:
            base_profile = exit_profiles.get(profile_id, {})
            if not base_profile:
                continue
            
            # Create mutated clone
            import random
            random.seed(int(time.time()) + hash(profile_id))
            
            new_id = f"{profile_id}_evo{int(time.time()) % 10000}"
            clone = base_profile.copy()
            
            # Mutate parameters
            if "TP1_ROI" in clone:
                clone["TP1_ROI"] = round(clone["TP1_ROI"] * random.uniform(1.05, 1.15), 4)
            if "TP2_ROI" in clone:
                clone["TP2_ROI"] = round(clone["TP2_ROI"] * random.uniform(1.05, 1.15), 4)
            if "ATR_stop_multiplier" in clone:
                clone["ATR_stop_multiplier"] = round(clone["ATR_stop_multiplier"] * random.uniform(0.9, 1.1), 2)
            if "ATR_trail_multiplier" in clone:
                clone["ATR_trail_multiplier"] = round(clone["ATR_trail_multiplier"] * random.uniform(0.9, 1.1), 2)
            
            clone["parent_profile"] = profile_id
            clone["created"] = int(time.time())
            
            exit_profiles[new_id] = clone
            evolutions.append({"from": profile_id, "to": new_id, "reason": "high_performance"})
            
            _append_event(EXIT_EVOLUTION_LOG, "exit_profile_evolved", {
                "from": profile_id,
                "to": new_id,
                "avg_roi": round(avg_roi, 4)
            })
        
        # Retire poor performers
        elif avg_roi < -0.002:
            if profile_id in exit_profiles:
                exit_profiles[profile_id]["status"] = "retired"
                exit_profiles[profile_id]["retired_ts"] = int(time.time())
                evolutions.append({"profile": profile_id, "action": "retired", "reason": "poor_performance"})
                
                _append_event(EXIT_EVOLUTION_LOG, "exit_profile_retired", {
                    "exit_profile_id": profile_id,
                    "avg_roi": round(avg_roi, 4)
                })
    
    _write_json(EXIT_PROFILES, exit_profiles)
    return evolutions

# ---- Phase 44.0 – Symbol Regime Memory ----
def update_regime_memory():
    """
    Track regime history for each symbol:
    - Record predicted regime from Phase 35
    - Maintain 30-period rolling history per symbol
    - Enable regime pattern recognition
    """
    regime_forecast = _read_json(REGIME_FORECAST, {})
    memory = _read_json(REGIME_MEMORY_LOG, {})
    attribution_events = _read_jsonl(STRATEGIC_ATTRIBUTION)
    
    # Get current predicted regime
    predicted_regime = regime_forecast.get("predicted_regime", "mixed")
    
    # Extract symbols from attribution data
    symbols_seen = set()
    for event in attribution_events:
        if event.get("event") == "attribution_computed":
            for sym in event.get("symbols", {}).keys():
                symbols_seen.add(sym)
    
    # Update memory for each symbol
    for sym in symbols_seen:
        sequence = memory.setdefault(sym, [])
        
        # Add current regime observation
        sequence.append({
            "ts": int(time.time()),
            "regime": predicted_regime,
            "volatility": regime_forecast.get("volatility", 0.0),
            "trend_strength": regime_forecast.get("trend_strength", 0.0)
        })
        
        # Keep last 30 observations
        if len(sequence) > 30:
            memory[sym] = sequence[-30:]
    
    _write_json(REGIME_MEMORY_LOG, memory)
    return memory

# ---- Phase 45.0 – Attribution Drift Detector ----
def detect_attribution_drift():
    """
    Detect performance degradation in strategies:
    - Monitor exit type distribution (TP2 rate, stop rate)
    - Track ROI trends over time
    - Flag strategies showing drift
    """
    trade_outcomes = _read_jsonl(TRADE_OUTCOMES)
    
    drift_flags = []
    
    # Group trades by strategy (recent 50 trades)
    by_strategy = {}
    for trade in trade_outcomes[-100:]:  # Last 100 trades
        strategy = trade.get("strategy", "")
        if not strategy:
            continue
        
        if strategy not in by_strategy:
            by_strategy[strategy] = []
        by_strategy[strategy].append(trade)
    
    # Analyze each strategy for drift
    for strategy, trades in by_strategy.items():
        if len(trades) < 10:
            continue  # Need minimum data
        
        # Calculate metrics
        exit_types = [t.get("exit_type", "") for t in trades]
        roi_values = [t.get("net_roi", 0.0) for t in trades]
        
        tp2_rate = sum(1 for e in exit_types if e == "tp2") / len(exit_types)
        stop_rate = sum(1 for e in exit_types if e == "stop_loss") / len(exit_types)
        avg_roi = mean(roi_values)
        
        # Detect drift conditions
        drift_detected = False
        drift_reasons = []
        
        if tp2_rate < 0.1:
            drift_detected = True
            drift_reasons.append("low_tp2_rate")
        
        if stop_rate > 0.5:
            drift_detected = True
            drift_reasons.append("high_stop_rate")
        
        if avg_roi < -0.002:
            drift_detected = True
            drift_reasons.append("negative_roi")
        
        if drift_detected:
            flag = {
                "strategy": strategy,
                "tp2_rate": round(tp2_rate, 3),
                "stop_rate": round(stop_rate, 3),
                "avg_roi": round(avg_roi, 4),
                "trade_count": len(trades),
                "drift_reasons": drift_reasons
            }
            drift_flags.append(flag)
            
            _append_event(DRIFT_LOG, "attribution_drift_detected", flag)
    
    return drift_flags

# ---- Unified Runner ----
def run_phase_42_45():
    """
    Execute all four phases:
    - Exit pairing optimization
    - Exit profile evolution
    - Regime memory tracking
    - Attribution drift detection
    """
    pairings = optimize_exit_pairing()
    evolutions = evolve_exit_profiles()
    memory = update_regime_memory()
    drift = detect_attribution_drift()
    
    return {
        "pairings": pairings,
        "evolutions": evolutions,
        "regime_memory": memory,
        "drift_flags": drift
    }

if __name__ == "__main__":
    result = run_phase_42_45()
    print(f"Phase 42: {len(result['pairings'])} exit pairings optimized")
    print(f"Phase 43: {len(result['evolutions'])} exit profiles evolved")
    print(f"Phase 44: {len(result['regime_memory'])} symbols in regime memory")
    print(f"Phase 45: {len(result['drift_flags'])} drift flags detected")
