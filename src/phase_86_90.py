# src/phase_86_90.py
#
# Phases 86–90: Feedback Loop, Regime-Aware Mutation, Stability Index,
#              Memory Visualizer, Hypothesis Generator

import os
import json
import time
from statistics import mean, stdev
from typing import Dict, List, Any

# Paths
LINEAGE_LOG = "config/strategy_lineage.json"
SHADOW_STATE = "config/shadow_strategy_state.json"
TRADE_OUTCOMES = "logs/trade_outcomes.jsonl"
STRATEGIC_ATTRIBUTION = "logs/strategic_attribution.jsonl"
CURIOSITY_LOG = "logs/curiosity_events.jsonl"
CURIOSITY_EVAL_LOG = "logs/curiosity_evaluation.json"
REGIME_FORECAST = "logs/regime_forecast.json"
LIFECYCLE_LOG = "logs/variant_lifecycle_events.jsonl"
OPERATOR_DIGEST = "logs/operator_digest.json"

FEEDBACK_LOG = "logs/operator_feedback_events.jsonl"
MUTATION_LOG = "logs/regime_mutation_events.jsonl"
STABILITY_LOG = "logs/attribution_stability_index.json"
MEMORY_VISUAL = "logs/strategic_memory_visualization.json"
HYPOTHESIS_LOG = "logs/hypothesis_events.jsonl"

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

# ---- Phase 86.0 – Operator Feedback Loop ----
def process_operator_feedback():
    """
    Operator feedback loop - processes system-generated feedback:
    - Analyzes lifecycle events for action recommendations
    - Generates feedback based on performance
    - Creates actionable operator recommendations
    - Closes the autonomous feedback loop
    """
    lifecycle_events = _read_jsonl(LIFECYCLE_LOG)
    operator_digest = _read_json(OPERATOR_DIGEST, {})
    
    feedback_actions = []
    
    # Process recent lifecycle events
    recent_cutoff = time.time() - 86400  # Last 24 hours
    recent_events = [e for e in lifecycle_events if e.get("ts", 0) > recent_cutoff]
    
    for event in recent_events:
        variant = event.get("variant", "")
        lifecycle_stage = event.get("lifecycle_stage", "")
        event_type = event.get("event", "")
        
        if not variant:
            continue
        
        # Generate feedback based on lifecycle stage
        if lifecycle_stage == "growth":
            feedback_actions.append({
                "variant": variant,
                "action": "promote",
                "reason": "strong_growth_detected",
                "lifecycle_stage": lifecycle_stage
            })
            _append_event(FEEDBACK_LOG, "operator_feedback", feedback_actions[-1])
        
        elif lifecycle_stage == "decline":
            feedback_actions.append({
                "variant": variant,
                "action": "mutate",
                "reason": "performance_declining",
                "lifecycle_stage": lifecycle_stage
            })
            _append_event(FEEDBACK_LOG, "operator_feedback", feedback_actions[-1])
        
        elif lifecycle_stage == "death":
            feedback_actions.append({
                "variant": variant,
                "action": "retire",
                "reason": "poor_performance_retirement",
                "lifecycle_stage": lifecycle_stage
            })
            _append_event(FEEDBACK_LOG, "operator_feedback", feedback_actions[-1])
    
    # Process alerts from digest
    alerts = operator_digest.get("alerts", [])
    for alert in alerts:
        feedback_actions.append({
            "variant": "system_wide",
            "action": "investigate",
            "reason": alert,
            "source": "digest_alert"
        })
        _append_event(FEEDBACK_LOG, "operator_feedback", feedback_actions[-1])
    
    return feedback_actions

# ---- Phase 87.0 – Regime-Aware Mutation Engine ----
def mutate_by_regime():
    """
    Regime-aware mutation engine - creates regime-specific mutations:
    - Mutates strategies based on current regime
    - Adjusts parameters for regime conditions
    - Creates regime-optimized variants
    - Tests mutations under appropriate conditions
    """
    lineage = _read_json(LINEAGE_LOG, {})
    regime_forecast = _read_json(REGIME_FORECAST, {})
    shadow_state = _read_json(SHADOW_STATE, {})
    
    current_regime = regime_forecast.get("predicted_regime", "mixed")
    
    mutations = []
    
    # Find candidates for regime-specific mutation
    for base_strategy, variants in lineage.items():
        for variant_id, data in variants.items():
            perf_history = data.get("performance_history", [])
            
            if len(perf_history) < 5:
                continue
            
            # Calculate recent performance
            roi_values = [p.get("avg_roi", 0.0) for p in perf_history]
            recent_roi = mean(roi_values[-3:])
            
            # Mutate declining or neutral strategies
            if -0.001 < recent_roi < 0.002:
                # Get original variant config
                original_config = None
                for shadow_base, shadow_variants in shadow_state.items():
                    for sv in shadow_variants:
                        if sv.get("variant_id") == variant_id:
                            original_config = sv
                            break
                
                if not original_config:
                    continue
                
                # Create regime-specific mutation
                mutation_id = f"{variant_id}_mut_{current_regime}_{int(time.time() % 100000)}"
                
                # Adjust filters based on regime
                mutated_filters = dict(original_config.get("filters", {}))
                
                if current_regime == "choppy":
                    # Tighter parameters for choppy markets
                    if "RSI" in mutated_filters:
                        mutated_filters["RSI"] = max(20, mutated_filters["RSI"] - 5)
                    mutated_filters["min_profit_bps"] = mutated_filters.get("min_profit_bps", 20) + 5
                    timeframe = "5m"
                    
                elif current_regime == "trending":
                    # Wider parameters for trends
                    if "RSI" in mutated_filters:
                        mutated_filters["RSI"] = min(50, mutated_filters["RSI"] + 5)
                    mutated_filters["min_profit_bps"] = mutated_filters.get("min_profit_bps", 20) + 10
                    timeframe = "15m"
                    
                elif current_regime == "volatile":
                    # Quick parameters for volatility
                    if "RSI" in mutated_filters:
                        mutated_filters["RSI"] = max(15, mutated_filters["RSI"] - 10)
                    mutated_filters["volume_min"] = int(mutated_filters.get("volume_min", 1000) * 1.5)
                    timeframe = "3m"
                    
                else:  # mixed
                    timeframe = original_config.get("timeframe", "5m")
                
                mutation = {
                    "mutation_id": mutation_id,
                    "parent_variant": variant_id,
                    "base_strategy": base_strategy,
                    "regime_target": current_regime,
                    "mutated_filters": mutated_filters,
                    "timeframe": timeframe,
                    "exit_profile_id": f"exit_{current_regime}_optimized",
                    "parent_roi": round(recent_roi, 4),
                    "created": int(time.time())
                }
                
                mutations.append(mutation)
                _append_event(MUTATION_LOG, "regime_mutation", mutation)
    
    return mutations

# ---- Phase 88.0 – Attribution Stability Index ----
def compute_stability_index():
    """
    Attribution stability index - measures performance stability:
    - Calculates signal clarity (non-zero ratio)
    - Measures volatility of returns
    - Computes stability score (clarity / volatility)
    - Identifies stable vs unstable strategies
    """
    trade_outcomes = _read_jsonl(TRADE_OUTCOMES)
    
    # Group by strategy
    by_strategy = {}
    for trade in trade_outcomes:
        strategy = trade.get("strategy", "")
        roi = trade.get("net_roi", 0.0)
        
        if not strategy:
            continue
        
        if strategy not in by_strategy:
            by_strategy[strategy] = []
        by_strategy[strategy].append(roi)
    
    # Calculate stability index
    stability_index = {}
    
    for strategy, roi_values in by_strategy.items():
        if len(roi_values) < 5:
            continue
        
        # Signal clarity (% non-zero returns)
        non_zero = sum(1 for r in roi_values if abs(r) > 0.0001)
        clarity = non_zero / len(roi_values)
        
        # Volatility
        volatility = stdev(roi_values) if len(roi_values) > 1 else 0.001
        
        # Stability score (higher is more stable)
        stability_score = clarity / (volatility + 0.0001)
        
        # Classify stability
        if stability_score > 50:
            stability_class = "highly_stable"
        elif stability_score > 20:
            stability_class = "stable"
        elif stability_score > 10:
            stability_class = "moderately_stable"
        else:
            stability_class = "unstable"
        
        stability_index[strategy] = {
            "clarity": round(clarity, 3),
            "volatility": round(volatility, 4),
            "stability_score": round(stability_score, 2),
            "stability_class": stability_class,
            "sample_size": len(roi_values)
        }
    
    _write_json(STABILITY_LOG, {
        "strategies": stability_index,
        "total_strategies": len(stability_index),
        "timestamp": int(time.time())
    })
    
    return stability_index

# ---- Phase 89.0 – Strategic Memory Visualizer ----
def visualize_memory():
    """
    Strategic memory visualizer - creates memory visualization:
    - Aggregates historical performance by strategy
    - Visualizes variant counts and performance
    - Provides strategic memory overview
    - Enables pattern recognition
    """
    lineage = _read_json(LINEAGE_LOG, {})
    
    memory_visualization = {}
    
    for base_strategy, variants in lineage.items():
        # Calculate aggregate metrics
        variant_count = len(variants)
        
        all_roi_values = []
        all_wr_values = []
        total_trades = 0
        
        for variant_id, data in variants.items():
            perf_history = data.get("performance_history", [])
            
            for perf in perf_history:
                all_roi_values.append(perf.get("avg_roi", 0.0))
                all_wr_values.append(perf.get("win_rate", 0.0))
                total_trades += perf.get("total_trades", 0)
        
        if all_roi_values:
            avg_roi = mean(all_roi_values)
            avg_wr = mean(all_wr_values)
        else:
            avg_roi = 0.0
            avg_wr = 0.0
        
        memory_visualization[base_strategy] = {
            "variant_count": variant_count,
            "avg_roi": round(avg_roi, 4),
            "avg_win_rate": round(avg_wr, 3),
            "total_trades": total_trades,
            "performance_rating": "good" if avg_roi > 0.002 else "neutral" if avg_roi > 0 else "poor"
        }
    
    _write_json(MEMORY_VISUAL, {
        "strategies": memory_visualization,
        "total_base_strategies": len(memory_visualization),
        "timestamp": int(time.time())
    })
    
    return memory_visualization

# ---- Phase 90.0 – Autonomous Hypothesis Generator ----
def generate_hypotheses():
    """
    Autonomous hypothesis generator - creates testable hypotheses:
    - Analyzes curiosity ideas
    - Generates testable hypotheses
    - Links hypotheses to regime conditions
    - Provides structured research questions
    """
    curiosity_events = _read_jsonl(CURIOSITY_LOG)
    curiosity_eval = _read_json(CURIOSITY_EVAL_LOG, {})
    regime_forecast = _read_json(REGIME_FORECAST, {})
    
    current_regime = regime_forecast.get("predicted_regime", "mixed")
    
    # Get recent high-priority ideas
    evaluations = curiosity_eval.get("evaluations", [])
    high_priority_ideas = [
        e for e in evaluations 
        if e.get("status") in ["test_immediately", "test_when_ready"]
    ]
    
    hypotheses = []
    
    for idea in high_priority_ideas[-5:]:  # Last 5 actionable ideas
        prompt = idea.get("prompt", "")
        idea_type = idea.get("type", "unknown")
        tags = idea.get("tags", [])
        
        # Generate hypothesis based on idea type
        if idea_type == "archetype_gap":
            hypothesis_text = f"Developing {tags[0] if tags else 'new'} archetype strategies will improve portfolio diversification and reduce correlation risk"
            expected_outcome = "Reduced drawdowns and smoother equity curve"
            
        elif idea_type == "exit_optimization":
            hypothesis_text = f"Optimizing {tags[0] if tags else 'exit'} exits will improve win rate by 5-10% without sacrificing average ROI"
            expected_outcome = "Higher win rate with stable or improved ROI"
            
        elif idea_type == "regime_opportunity":
            hypothesis_text = f"Strategies optimized for {current_regime} regime will outperform generic strategies by 15-20%"
            expected_outcome = "Regime-specific strategies show higher ROI in matching conditions"
            
        else:
            hypothesis_text = f"{prompt} This optimization will lead to measurable performance improvements"
            expected_outcome = "Positive impact on risk-adjusted returns"
        
        hypothesis = {
            "hypothesis_id": f"hyp_{int(time.time() % 100000)}_{len(hypotheses)}",
            "source_idea": prompt,
            "idea_type": idea_type,
            "hypothesis": hypothesis_text,
            "expected_outcome": expected_outcome,
            "test_regime": current_regime,
            "tags": tags,
            "viability_score": idea.get("viability_score", 0.5),
            "status": "proposed",
            "created": int(time.time())
        }
        
        hypotheses.append(hypothesis)
        _append_event(HYPOTHESIS_LOG, "hypothesis_generated", hypothesis)
    
    return hypotheses

# ---- Unified Runner ----
def run_phase_86_90():
    """
    Execute all five phases:
    - Feedback loop processing
    - Regime-aware mutation
    - Stability index calculation
    - Memory visualization
    - Hypothesis generation
    """
    feedback = process_operator_feedback()
    mutations = mutate_by_regime()
    stability = compute_stability_index()
    memory = visualize_memory()
    hypotheses = generate_hypotheses()
    
    return {
        "feedback": feedback,
        "mutations": mutations,
        "stability_index": stability,
        "memory_visualization": memory,
        "hypotheses": hypotheses
    }

if __name__ == "__main__":
    result = run_phase_86_90()
    print(f"Phase 86: {len(result['feedback'])} feedback actions")
    print(f"Phase 87: {len(result['mutations'])} regime mutations")
    print(f"Phase 88: {len(result['stability_index'])} stability scores")
    print(f"Phase 89: {len(result['memory_visualization'])} strategies visualized")
    print(f"Phase 90: {len(result['hypotheses'])} hypotheses generated")
