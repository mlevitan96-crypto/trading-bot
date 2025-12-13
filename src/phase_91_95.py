# src/phase_91_95.py
#
# Phases 91–95: Hypothesis Tester, Timeline Visualizer, Regime Drift Detector,
#              Curiosity Synthesizer, Strategy Reviewer

import os
import json
import time
from statistics import mean, stdev
from typing import Dict, List, Any

# Paths
LINEAGE_LOG = "config/strategy_lineage.json"
TRADE_OUTCOMES = "logs/trade_outcomes.jsonl"
HYPOTHESIS_LOG = "logs/hypothesis_events.jsonl"
OPERATOR_DIGEST = "logs/operator_digest.json"
LIFECYCLE_LOG = "logs/variant_lifecycle_events.jsonl"
REGIME_FORECAST = "logs/regime_forecast.json"
REGIME_MEMORY = "logs/symbol_regime_memory.json"
CURIOSITY_LOG = "logs/curiosity_events.jsonl"
CURIOSITY_EVAL_LOG = "logs/curiosity_evaluation.json"

HYPOTHESIS_TEST_LOG = "logs/hypothesis_test_results.json"
TIMELINE_VISUAL = "logs/operator_timeline_visualization.json"
REGIME_DRIFT_LOG = "logs/regime_drift_events.jsonl"
CURIOSITY_SYNTHESIS_LOG = "logs/curiosity_synthesis.json"
STRATEGY_REVIEW_LOG = "logs/strategy_review.json"

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

# ---- Phase 91.0 – Hypothesis Tester ----
def test_hypotheses():
    """
    Hypothesis tester - tests generated hypotheses:
    - Evaluates hypotheses against actual data
    - Determines support/rejection/inconclusive
    - Calculates confidence levels
    - Provides evidence-based results
    """
    hypothesis_events = _read_jsonl(HYPOTHESIS_LOG)
    trade_outcomes = _read_jsonl(TRADE_OUTCOMES)
    
    test_results = []
    
    # Get recent hypotheses to test
    recent_hypotheses = hypothesis_events[-10:] if len(hypothesis_events) > 10 else hypothesis_events
    
    for hyp in recent_hypotheses:
        hypothesis_id = hyp.get("hypothesis_id", "")
        hypothesis_text = hyp.get("hypothesis", "")
        idea_type = hyp.get("idea_type", "unknown")
        test_regime = hyp.get("test_regime", "mixed")
        
        # Test based on hypothesis type
        if idea_type == "archetype_gap":
            # Test if filling archetype gap improves performance
            # (Would need actual archetype data - for now, analyze regime performance)
            regime_trades = [t for t in trade_outcomes if t.get("regime") == test_regime]
            if len(regime_trades) > 5:
                avg_roi = mean([t.get("net_roi", 0.0) for t in regime_trades])
                result = "supported" if avg_roi > 0.002 else "inconclusive" if avg_roi > 0 else "rejected"
                confidence = min(0.95, len(regime_trades) / 50)
            else:
                result = "insufficient_data"
                confidence = 0.0
                
        elif idea_type == "exit_optimization":
            # Test if exit optimization improves win rate
            if trade_outcomes:
                win_rate = sum(1 for t in trade_outcomes if t.get("net_roi", 0) > 0) / len(trade_outcomes)
                result = "supported" if win_rate > 0.55 else "inconclusive" if win_rate > 0.45 else "rejected"
                confidence = 0.7
            else:
                result = "insufficient_data"
                confidence = 0.0
                
        elif idea_type == "regime_opportunity":
            # Test if regime-specific strategies outperform
            regime_trades = [t for t in trade_outcomes if t.get("regime") == test_regime]
            all_trades = trade_outcomes
            
            if len(regime_trades) > 5 and len(all_trades) > 10:
                regime_roi = mean([t.get("net_roi", 0.0) for t in regime_trades])
                all_roi = mean([t.get("net_roi", 0.0) for t in all_trades])
                
                if regime_roi > all_roi * 1.15:  # 15% improvement
                    result = "supported"
                    confidence = 0.8
                elif regime_roi > all_roi:
                    result = "inconclusive"
                    confidence = 0.5
                else:
                    result = "rejected"
                    confidence = 0.6
            else:
                result = "insufficient_data"
                confidence = 0.0
        else:
            result = "not_tested"
            confidence = 0.0
        
        test_result = {
            "hypothesis_id": hypothesis_id,
            "hypothesis": hypothesis_text,
            "idea_type": idea_type,
            "test_regime": test_regime,
            "result": result,
            "confidence": round(confidence, 3),
            "tested_at": int(time.time())
        }
        
        test_results.append(test_result)
    
    _write_json(HYPOTHESIS_TEST_LOG, {
        "results": test_results,
        "total_tested": len(test_results),
        "supported": sum(1 for r in test_results if r["result"] == "supported"),
        "rejected": sum(1 for r in test_results if r["result"] == "rejected"),
        "inconclusive": sum(1 for r in test_results if r["result"] == "inconclusive"),
        "timestamp": int(time.time())
    })
    
    return test_results

# ---- Phase 92.0 – Operator Timeline Visualizer ----
def visualize_operator_timeline():
    """
    Operator timeline visualizer - creates chronological timeline:
    - Aggregates lifecycle events over time
    - Visualizes system evolution timeline
    - Tracks key milestones
    - Provides temporal context
    """
    lifecycle_events = _read_jsonl(LIFECYCLE_LOG)
    operator_digest = _read_json(OPERATOR_DIGEST, {})
    
    # Create timeline entries
    timeline = []
    
    # Group events by day
    events_by_day = {}
    for event in lifecycle_events:
        timestamp = event.get("ts", 0)
        day_key = timestamp // 86400  # Day granularity
        
        if day_key not in events_by_day:
            events_by_day[day_key] = {
                "births": 0,
                "growths": 0,
                "maturities": 0,
                "declines": 0,
                "deaths": 0
            }
        
        event_type = event.get("event", "")
        if "birth" in event_type:
            events_by_day[day_key]["births"] += 1
        elif "growth" in event_type:
            events_by_day[day_key]["growths"] += 1
        elif "maturity" in event_type:
            events_by_day[day_key]["maturities"] += 1
        elif "decline" in event_type:
            events_by_day[day_key]["declines"] += 1
        elif "death" in event_type:
            events_by_day[day_key]["deaths"] += 1
    
    # Convert to timeline
    for day_key, counts in sorted(events_by_day.items()):
        timeline.append({
            "day": day_key,
            "timestamp": day_key * 86400,
            "events": counts,
            "net_change": counts["births"] - counts["deaths"],
            "total_activity": sum(counts.values())
        })
    
    _write_json(TIMELINE_VISUAL, {
        "timeline": timeline,
        "total_days": len(timeline),
        "current_status": operator_digest.get("system_status", "unknown"),
        "timestamp": int(time.time())
    })
    
    return timeline

# ---- Phase 93.0 – Regime Drift Detector ----
def detect_regime_drift():
    """
    Regime drift detector - detects regime prediction drift:
    - Compares forecasted vs actual regimes
    - Detects prediction drift per symbol
    - Measures forecast accuracy
    - Identifies problematic symbols
    """
    regime_forecast = _read_json(REGIME_FORECAST, {})
    regime_memory = _read_json(REGIME_MEMORY, {})
    
    predicted_regime = regime_forecast.get("predicted_regime", "unknown")
    
    drift_events = []
    
    for symbol, entries in regime_memory.items():
        if not entries or not isinstance(entries, list):
            continue
        
        # Get recent actual regimes
        recent_regimes = [e.get("regime", "unknown") for e in entries[-5:] if isinstance(e, dict)]
        
        if not recent_regimes:
            continue
        
        # Count matches with prediction
        matches = sum(1 for r in recent_regimes if r == predicted_regime)
        match_rate = matches / len(recent_regimes)
        
        # Detect drift if match rate is low
        if match_rate < 0.4:  # Less than 40% match
            drift = {
                "symbol": symbol,
                "predicted_regime": predicted_regime,
                "actual_regimes": recent_regimes,
                "match_rate": round(match_rate, 3),
                "drift_severity": "high" if match_rate < 0.2 else "moderate"
            }
            drift_events.append(drift)
            _append_event(REGIME_DRIFT_LOG, "regime_drift", drift)
    
    return drift_events

# ---- Phase 94.0 – Strategic Curiosity Synthesizer ----
def synthesize_curiosity():
    """
    Strategic curiosity synthesizer - synthesizes research ideas:
    - Combines multiple curiosity ideas
    - Creates actionable research plans
    - Prioritizes synthesis by viability
    - Generates integrated research approach
    """
    curiosity_events = _read_jsonl(CURIOSITY_LOG)
    curiosity_eval = _read_json(CURIOSITY_EVAL_LOG, {})
    
    # Get high-priority ideas
    evaluations = curiosity_eval.get("evaluations", [])
    high_priority = [e for e in evaluations if e.get("status") in ["test_immediately", "test_when_ready"]]
    
    # Group by type
    by_type = {}
    for idea in high_priority:
        idea_type = idea.get("type", "unknown")
        if idea_type not in by_type:
            by_type[idea_type] = []
        by_type[idea_type].append(idea)
    
    # Synthesize by type
    syntheses = []
    
    for idea_type, ideas in by_type.items():
        if not ideas:
            continue
        
        tags = []
        for idea in ideas:
            tags.extend(idea.get("tags", []))
        
        unique_tags = list(set(tags))
        
        # Create synthesis
        if idea_type == "archetype_gap":
            synthesis_text = f"Develop {', '.join(unique_tags[:3])} archetype strategies with regime-adaptive parameters"
            testing_approach = "Shadow test new archetypes in parallel across all regimes"
            
        elif idea_type == "exit_optimization":
            synthesis_text = f"Optimize {', '.join(unique_tags[:3])} exits with time-based and volatility-based triggers"
            testing_approach = "A/B test exit strategies on same signals"
            
        elif idea_type == "regime_opportunity":
            synthesis_text = f"Exploit regime opportunities in {', '.join(unique_tags[:3])} markets"
            testing_approach = "Deploy regime-specific variants with increased capital"
            
        else:
            synthesis_text = f"Explore {idea_type} opportunities across {', '.join(unique_tags[:2])}"
            testing_approach = "Incremental testing with limited capital"
        
        synthesis = {
            "idea_type": idea_type,
            "idea_count": len(ideas),
            "tags": unique_tags[:5],
            "synthesis": synthesis_text,
            "testing_approach": testing_approach,
            "priority": "high" if len(ideas) > 2 else "medium"
        }
        
        syntheses.append(synthesis)
    
    _write_json(CURIOSITY_SYNTHESIS_LOG, {
        "syntheses": syntheses,
        "total_syntheses": len(syntheses),
        "timestamp": int(time.time())
    })
    
    return syntheses

# ---- Phase 95.0 – Autonomous Strategy Reviewer ----
def review_strategies():
    """
    Autonomous strategy reviewer - reviews all strategies:
    - Analyzes performance by base strategy
    - Calculates variant success rates
    - Provides strength ratings
    - Recommends actions per strategy
    """
    lineage = _read_json(LINEAGE_LOG, {})
    trade_outcomes = _read_jsonl(TRADE_OUTCOMES)
    
    reviews = {}
    
    for base_strategy, variants in lineage.items():
        variant_count = len(variants)
        
        # Collect all performance data
        all_roi_values = []
        all_wr_values = []
        total_trades = 0
        
        for variant_id, data in variants.items():
            perf_history = data.get("performance_history", [])
            
            for perf in perf_history:
                all_roi_values.append(perf.get("avg_roi", 0.0))
                all_wr_values.append(perf.get("win_rate", 0.0))
                total_trades += perf.get("total_trades", 0)
        
        if not all_roi_values:
            continue
        
        avg_roi = mean(all_roi_values)
        avg_wr = mean(all_wr_values)
        roi_volatility = stdev(all_roi_values) if len(all_roi_values) > 1 else 0
        
        # Determine strength
        if avg_roi > 0.003 and avg_wr > 0.55:
            strength = "strong"
            recommendation = "Scale up capital allocation"
        elif avg_roi > 0.001 and avg_wr > 0.5:
            strength = "moderate"
            recommendation = "Maintain current allocation"
        elif avg_roi > 0:
            strength = "weak"
            recommendation = "Consider mutations or reduced allocation"
        else:
            strength = "poor"
            recommendation = "Retire or major mutation needed"
        
        reviews[base_strategy] = {
            "variant_count": variant_count,
            "total_trades": total_trades,
            "avg_roi": round(avg_roi, 4),
            "avg_win_rate": round(avg_wr, 3),
            "roi_volatility": round(roi_volatility, 4),
            "strength": strength,
            "recommendation": recommendation
        }
    
    _write_json(STRATEGY_REVIEW_LOG, {
        "reviews": reviews,
        "total_strategies": len(reviews),
        "strong": sum(1 for r in reviews.values() if r["strength"] == "strong"),
        "moderate": sum(1 for r in reviews.values() if r["strength"] == "moderate"),
        "weak": sum(1 for r in reviews.values() if r["strength"] == "weak"),
        "poor": sum(1 for r in reviews.values() if r["strength"] == "poor"),
        "timestamp": int(time.time())
    })
    
    return reviews

# ---- Unified Runner ----
def run_phase_91_95():
    """
    Execute all five phases:
    - Hypothesis testing
    - Timeline visualization
    - Drift detection
    - Curiosity synthesis
    - Strategy review
    """
    hypothesis_results = test_hypotheses()
    timeline = visualize_operator_timeline()
    drift = detect_regime_drift()
    curiosity_synthesis = synthesize_curiosity()
    strategy_review = review_strategies()
    
    return {
        "hypothesis_results": hypothesis_results,
        "timeline_visualization": timeline,
        "regime_drift": drift,
        "curiosity_synthesis": curiosity_synthesis,
        "strategy_review": strategy_review
    }

if __name__ == "__main__":
    result = run_phase_91_95()
    print(f"Phase 91: {len(result['hypothesis_results'])} hypotheses tested")
    print(f"Phase 92: {len(result['timeline_visualization'])} timeline entries")
    print(f"Phase 93: {len(result['regime_drift'])} drift events detected")
    print(f"Phase 94: {len(result['curiosity_synthesis'])} syntheses created")
    print(f"Phase 95: {len(result['strategy_review'])} strategies reviewed")
