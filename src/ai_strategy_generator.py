# src/ai_strategy_generator.py
#
# Phase 27.0 – AI-Driven Strategy Generator
# Purpose:
#   - Analyze attribution logs and regime data
#   - Detect underperformance by symbol, strategy, and regime
#   - Generate new strategy variants with rationale and expected behavior
#   - Output to config/ai_generated_strategies.json
#   - Log events to logs/ai_strategy_generator_events.jsonl
#   - Integrate with Shadow Lab and Operator Intelligence

import os, json, time, random
from statistics import mean

ATTRIBUTION_LOG = "logs/strategic_attribution.jsonl"
REGIME_LOG = "logs/regime_state.json"
STRATEGY_REGISTRY = "config/strategy_registry.json"
EXIT_PROFILES = "config/exit_profiles.json"
OUTPUT_PATH = "config/ai_generated_strategies.json"
EVENT_LOG = "logs/ai_strategy_generator_events.jsonl"

def _read_json(path: str, default: dict):
    if not os.path.exists(path): 
        return default
    with open(path, "r") as f:
        try: 
            return json.load(f)
        except: 
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
                except: 
                    pass
    return out

def _append_event(ev: str, payload: dict = None):
    os.makedirs(os.path.dirname(EVENT_LOG), exist_ok=True)
    if payload is None:
        payload = {}
    else:
        payload = dict(payload)
    payload.update({"event": ev, "ts": int(time.time())})
    with open(EVENT_LOG, "a") as f: 
        f.write(json.dumps(payload) + "\n")

def generate_ai_strategies():
    """
    AI-driven strategy generation:
    - Analyzes attribution data to find underperforming symbols/strategies
    - Detects regime-specific weaknesses (chop, trend, volatile)
    - Generates targeted strategy variants with rationale
    - Outputs recommendations for Shadow Lab testing
    """
    attribution_events = _read_jsonl(ATTRIBUTION_LOG)
    regime = _read_json(REGIME_LOG, {
        "regime": "stable",
        "volatility": 0.002, 
        "trend_strength": 0.5
    })
    registry = _read_json(STRATEGY_REGISTRY, {})
    exit_profiles = _read_json(EXIT_PROFILES, {})
    
    generated = []
    by_symbol = {}
    
    # Determine regime type
    current_vol = regime.get("volatility", 0.002)
    trend_strength = regime.get("trend_strength", 0.5)
    
    if current_vol < 0.0015:
        regime_type = "choppy"
    elif trend_strength > 0.6:
        regime_type = "trending"
    elif current_vol > 0.025:
        regime_type = "volatile"
    else:
        regime_type = "mixed"
    
    # Parse attribution events to extract symbol-strategy performance
    for event in attribution_events:
        if event.get("event") == "attribution_computed":
            symbols = event.get("symbols", {})
            for sym, metrics in symbols.items():
                if sym not in by_symbol:
                    by_symbol[sym] = {
                        "trades": metrics.get("trades", 0),
                        "win_rate": metrics.get("win_rate", 0.0),
                        "avg_roi": metrics.get("avg_roi", 0.0),
                        "total_roi": metrics.get("total_roi", 0.0)
                    }
    
    # Analyze each symbol for underperformance
    for sym, data in by_symbol.items():
        if data["trades"] < 5:
            continue  # Need minimum trade history
        
        avg_roi = data["avg_roi"]
        win_rate = data["win_rate"]
        
        # Generate strategy if underperforming
        if avg_roi < -0.001 or win_rate < 0.45:
            variant_id = f"AI_Strategy_{sym}_{random.randint(1000,9999)}"
            
            # Select appropriate exit profile based on regime
            selected_profile = None
            profile_id = None
            
            for pid, profile in exit_profiles.items():
                if profile.get("regime_target") == regime_type and profile.get("status") == "active":
                    selected_profile = profile.get("logic", {})
                    profile_id = pid
                    break
            
            # Determine optimization approach based on performance
            if win_rate < 0.45:
                # Low win rate → use defensive profile or create one
                approach = "defensive"
                if selected_profile:
                    exit_logic = selected_profile
                    rationale = f"{sym} has low win rate ({win_rate:.1%}). Using {profile_id} exit profile for {regime_type} regime."
                else:
                    exit_logic = {
                        "TP1_ROI": 0.004,
                        "TP2_ROI": 0.008,
                        "TRAIL_ATR_MULT": 2.0,
                        "STOP_ATR_MULT": 2.5,
                        "TIME_STOP_MINUTES": 45,
                        "MIN_CONFIDENCE": 0.65
                    }
                    rationale = f"{sym} has low win rate ({win_rate:.1%}). Using defensive approach with tighter profit targets and wider stops."
            else:
                # Negative ROI but decent WR → optimize exits
                approach = "exit_optimization"
                if selected_profile:
                    exit_logic = selected_profile
                    rationale = f"{sym} has negative ROI ({avg_roi:.2%}). Using {profile_id} exit profile optimized for {regime_type} regime."
                else:
                    exit_logic = {
                        "TP1_ROI": 0.006,
                        "TP2_ROI": 0.012,
                        "TRAIL_ATR_MULT": 1.8,
                        "STOP_ATR_MULT": 1.5,
                        "TRAIL_ACTIVATION": 0.003,
                        "TIME_STOP_MINUTES": 60
                    }
                    rationale = f"{sym} has negative ROI ({avg_roi:.2%}). Optimizing exit logic to capture more profit and reduce loss size."
            
            variant = {
                "symbol": sym,
                "variant_id": variant_id,
                "approach": approach,
                "regime_target": regime_type,
                "exit_profile_id": profile_id if profile_id else "custom",
                "timeframe": "1m",
                "exit_logic": exit_logic,
                "expected_behavior": f"Improved {approach} for {sym} in {regime_type} regime",
                "rationale": rationale,
                "performance_target": {
                    "min_win_rate": 0.50,
                    "min_avg_roi": 0.002,
                    "max_stop_rate": 0.35
                },
                "generated_ts": int(time.time()),
                "status": "ai_generated",
                "parent_performance": {
                    "trades": data["trades"],
                    "win_rate": win_rate,
                    "avg_roi": avg_roi
                }
            }
            generated.append(variant)
            _append_event("ai_strategy_generated", {
                "variant_id": variant_id,
                "symbol": sym,
                "approach": approach
            })
    
    # Save generated strategies
    _write_json(OUTPUT_PATH, {
        "timestamp": int(time.time()),
        "date": time.strftime("%Y-%m-%d %H:%M:%S"),
        "regime": regime_type,
        "strategies": generated
    })
    
    _append_event("ai_strategy_generation_complete", {
        "count": len(generated),
        "regime": regime_type
    })
    
    return generated

if __name__ == "__main__":
    result = generate_ai_strategies()
    print(f"Phase 27.0 AI Strategy Generator executed. {len(result)} new strategies generated.")
