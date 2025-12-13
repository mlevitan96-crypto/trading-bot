# src/phase_81_85.py
#
# Phases 81–85: Lifecycle Visualizer, Forecast Validator, Noise Filter,
#              Digest Notifier, Curiosity Tracker

import os
import json
import time
from statistics import mean
from typing import Dict, List, Any

# Paths
LINEAGE_LOG = "config/strategy_lineage.json"
LIFECYCLE_LOG = "logs/variant_lifecycle_events.jsonl"
REGIME_FORECAST = "logs/regime_forecast.json"
REGIME_MEMORY = "logs/symbol_regime_memory.json"
TRADE_OUTCOMES = "logs/trade_outcomes.jsonl"
STRATEGIC_ATTRIBUTION = "logs/strategic_attribution.jsonl"
CURIOSITY_LOG = "logs/curiosity_events.jsonl"
CURIOSITY_EVAL_LOG = "logs/curiosity_evaluation.json"

LIFECYCLE_TIMELINE = "logs/variant_lifecycle_timeline.json"
REGIME_VALIDATION = "logs/regime_forecast_validation.json"
ATTRIBUTION_SMOOTHED = "logs/attribution_smoothed.json"
OPERATOR_DIGEST = "logs/operator_digest.json"
CURIOSITY_TRACKER = "logs/curiosity_tracker.json"

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

# ---- Phase 81.0 – Variant Lifecycle Visualizer ----
def visualize_variant_lifecycle():
    """
    Variant lifecycle visualizer - creates timeline visualization:
    - Aggregates lifecycle events by variant
    - Creates chronological timeline
    - Visualizes state transitions
    - Enables lifecycle pattern analysis
    """
    lifecycle_events = _read_jsonl(LIFECYCLE_LOG)
    
    # Organize by variant
    timeline_by_variant = {}
    
    for event in lifecycle_events:
        variant = event.get("variant", "")
        timestamp = event.get("ts", 0)
        event_type = event.get("event", "")
        lifecycle_stage = event.get("lifecycle_stage", "unknown")
        
        if not variant:
            continue
        
        if variant not in timeline_by_variant:
            timeline_by_variant[variant] = {
                "variant_id": variant,
                "base_strategy": event.get("base_strategy", ""),
                "events": []
            }
        
        timeline_by_variant[variant]["events"].append({
            "timestamp": timestamp,
            "event_type": event_type,
            "lifecycle_stage": lifecycle_stage,
            "details": event
        })
    
    # Sort events chronologically
    for variant, data in timeline_by_variant.items():
        data["events"].sort(key=lambda x: x["timestamp"])
        
        # Add summary stats
        stages = [e["lifecycle_stage"] for e in data["events"]]
        data["total_transitions"] = len(stages)
        data["current_stage"] = stages[-1] if stages else "unknown"
        data["age_events"] = len(data["events"])
    
    _write_json(LIFECYCLE_TIMELINE, {
        "timelines": timeline_by_variant,
        "total_variants": len(timeline_by_variant),
        "timestamp": int(time.time())
    })
    
    return timeline_by_variant

# ---- Phase 82.0 – Regime Forecast Validator ----
def validate_regime_forecast():
    """
    Regime forecast validator - validates prediction accuracy:
    - Compares forecasts to actual regimes
    - Calculates accuracy metrics
    - Tracks regime persistence
    - Measures forecast quality
    """
    forecast = _read_json(REGIME_FORECAST, {})
    regime_memory = _read_json(REGIME_MEMORY, {})
    
    predicted_regime = forecast.get("predicted_regime", "unknown")
    
    # Collect actual regimes from recent memory
    actual_regimes = []
    for symbol, entries in regime_memory.items():
        if entries:
            # Get most recent regime
            recent_entry = entries[-1] if isinstance(entries, list) else entries
            if isinstance(recent_entry, dict):
                actual_regime = recent_entry.get("regime", "unknown")
                actual_regimes.append(actual_regime)
    
    # Calculate accuracy
    if actual_regimes:
        matches = sum(1 for regime in actual_regimes if regime == predicted_regime)
        accuracy = matches / len(actual_regimes)
        
        # Calculate persistence (how long regime stays same)
        regime_counts = {}
        for regime in actual_regimes:
            regime_counts[regime] = regime_counts.get(regime, 0) + 1
        
        most_common = max(regime_counts.values()) if regime_counts else 0
        persistence_score = most_common / len(actual_regimes)
    else:
        accuracy = 0.0
        persistence_score = 0.0
    
    validation = {
        "predicted_regime": predicted_regime,
        "actual_regimes": actual_regimes,
        "accuracy": round(accuracy, 3),
        "persistence_score": round(persistence_score, 3),
        "sample_size": len(actual_regimes),
        "confidence": forecast.get("confidence", 0),
        "validated_at": int(time.time())
    }
    
    _write_json(REGIME_VALIDATION, validation)
    return validation

# ---- Phase 83.0 – Attribution Noise Filter ----
def smooth_attribution():
    """
    Attribution noise filter - reduces noise in performance data:
    - Applies exponential moving average
    - Smooths ROI volatility
    - Filters out outliers
    - Provides clearer performance signal
    """
    trade_outcomes = _read_jsonl(TRADE_OUTCOMES)
    
    # Group by strategy
    by_strategy = {}
    for trade in trade_outcomes:
        strategy = trade.get("strategy", "")
        roi = trade.get("net_roi", 0.0)
        timestamp = trade.get("timestamp", 0)
        
        if not strategy:
            continue
        
        if strategy not in by_strategy:
            by_strategy[strategy] = []
        by_strategy[strategy].append({"roi": roi, "timestamp": timestamp})
    
    # Apply EMA smoothing
    smoothed_results = {}
    alpha = 0.3  # EMA smoothing factor
    
    for strategy, trades in by_strategy.items():
        if len(trades) < 3:
            continue
        
        # Sort by timestamp
        trades.sort(key=lambda x: x["timestamp"])
        
        # Calculate EMA
        roi_values = [t["roi"] for t in trades]
        ema = roi_values[0]
        
        for roi in roi_values[1:]:
            ema = alpha * roi + (1 - alpha) * ema
        
        # Also calculate raw average for comparison
        raw_avg = mean(roi_values)
        
        smoothed_results[strategy] = {
            "smoothed_roi": round(ema, 5),
            "raw_avg_roi": round(raw_avg, 5),
            "noise_reduction": round(abs(ema - raw_avg), 5),
            "sample_size": len(trades)
        }
    
    _write_json(ATTRIBUTION_SMOOTHED, {
        "strategies": smoothed_results,
        "total_strategies": len(smoothed_results),
        "smoothing_alpha": alpha,
        "timestamp": int(time.time())
    })
    
    return smoothed_results

# ---- Phase 84.0 – Operator Copilot Digest Notifier ----
def generate_operator_digest():
    """
    Operator copilot digest notifier - summarizes key events:
    - Counts promotions, retirements, mutations
    - Highlights critical alerts
    - Summarizes regime status
    - Provides actionable digest
    """
    lifecycle_events = _read_jsonl(LIFECYCLE_LOG)
    
    # Count recent events (last 24 hours)
    recent_cutoff = time.time() - 86400
    recent_events = [e for e in lifecycle_events if e.get("ts", 0) > recent_cutoff]
    
    # Count by event type
    event_counts = {
        "births": 0,
        "growths": 0,
        "maturities": 0,
        "declines": 0,
        "deaths": 0
    }
    
    for event in recent_events:
        event_type = event.get("event", "")
        if "birth" in event_type:
            event_counts["births"] += 1
        elif "growth" in event_type:
            event_counts["growths"] += 1
        elif "maturity" in event_type:
            event_counts["maturities"] += 1
        elif "decline" in event_type:
            event_counts["declines"] += 1
        elif "death" in event_type:
            event_counts["deaths"] += 1
    
    # Get current regime
    regime_forecast = _read_json(REGIME_FORECAST, {})
    current_regime = regime_forecast.get("predicted_regime", "unknown")
    regime_confidence = regime_forecast.get("confidence", 0)
    
    # Generate alerts
    alerts = []
    if event_counts["declines"] > event_counts["growths"]:
        alerts.append("More variants declining than growing - review strategy performance")
    if event_counts["deaths"] > 2:
        alerts.append(f"{event_counts['deaths']} variants retired - consider mutation or new generation")
    if regime_confidence < 0.5:
        alerts.append(f"Low regime confidence ({regime_confidence:.1%}) - forecast may be unreliable")
    
    digest = {
        "period": "last_24_hours",
        "timestamp": int(time.time()),
        "lifecycle_events": event_counts,
        "total_events": sum(event_counts.values()),
        "regime": {
            "current": current_regime,
            "confidence": round(regime_confidence, 3)
        },
        "alerts": alerts,
        "alert_count": len(alerts),
        "system_status": "warning" if alerts else "healthy"
    }
    
    _write_json(OPERATOR_DIGEST, digest)
    return digest

# ---- Phase 85.0 – Strategic Curiosity Tracker ----
def track_curiosity():
    """
    Strategic curiosity tracker - tracks research progress:
    - Counts ideas generated vs tested
    - Tracks evaluation status
    - Measures research coverage
    - Monitors innovation pipeline
    """
    curiosity_events = _read_jsonl(CURIOSITY_LOG)
    curiosity_eval = _read_json(CURIOSITY_EVAL_LOG, {})
    
    # Count by event type
    idea_count = sum(1 for e in curiosity_events if e.get("event") == "curiosity_idea")
    
    # Count by evaluation status
    evaluations = curiosity_eval.get("evaluations", [])
    
    status_counts = {
        "test_immediately": 0,
        "test_when_ready": 0,
        "archive_for_later": 0,
        "reject": 0
    }
    
    for eval_item in evaluations:
        status = eval_item.get("status", "unknown")
        if status in status_counts:
            status_counts[status] += 1
    
    # Calculate metrics
    total_evaluated = sum(status_counts.values())
    actionable = status_counts["test_immediately"] + status_counts["test_when_ready"]
    
    if total_evaluated > 0:
        actionable_rate = actionable / total_evaluated
        test_rate = status_counts["test_immediately"] / total_evaluated
    else:
        actionable_rate = 0.0
        test_rate = 0.0
    
    tracker = {
        "total_ideas_generated": idea_count,
        "total_ideas_evaluated": total_evaluated,
        "status_breakdown": status_counts,
        "actionable_ideas": actionable,
        "actionable_rate": round(actionable_rate, 3),
        "immediate_test_rate": round(test_rate, 3),
        "pipeline_health": "healthy" if actionable_rate > 0.5 else "needs_ideas",
        "timestamp": int(time.time())
    }
    
    _write_json(CURIOSITY_TRACKER, tracker)
    return tracker

# ---- Unified Runner ----
def run_phase_81_85():
    """
    Execute all five phases:
    - Lifecycle visualization
    - Forecast validation
    - Attribution smoothing
    - Digest notification
    - Curiosity tracking
    """
    lifecycle = visualize_variant_lifecycle()
    regime_validation = validate_regime_forecast()
    smoothed = smooth_attribution()
    digest = generate_operator_digest()
    curiosity = track_curiosity()
    
    return {
        "lifecycle_timeline": lifecycle,
        "regime_validation": regime_validation,
        "smoothed_attribution": smoothed,
        "operator_digest": digest,
        "curiosity_tracker": curiosity
    }

if __name__ == "__main__":
    result = run_phase_81_85()
    print(f"Phase 81: {len(result['lifecycle_timeline'])} variant timelines")
    print(f"Phase 82: Forecast accuracy: {result['regime_validation'].get('accuracy', 0):.1%}")
    print(f"Phase 83: {len(result['smoothed_attribution'])} strategies smoothed")
    print(f"Phase 84: {result['operator_digest']['total_events']} events, {result['operator_digest']['alert_count']} alerts")
    print(f"Phase 85: {result['curiosity_tracker']['total_ideas_generated']} ideas, {result['curiosity_tracker']['actionable_ideas']} actionable")
