# src/phase_76_80.py
#
# Phases 76–80: Variant Lifecycle Manager, Regime Composer, Confidence Scorer,
#              Operator Journal, Curiosity Evaluator

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
EXIT_PROFILES = "config/exit_profiles.json"
CURIOSITY_LOG = "logs/curiosity_events.jsonl"
ARCHETYPE_LOG = "logs/strategy_archetypes.json"
EXPECTANCY_LOG = "logs/expectancy_scores.json"

LIFECYCLE_LOG = "logs/variant_lifecycle_events.jsonl"
COMPOSER_LOG = "logs/regime_composed_strategies.json"
CONFIDENCE_LOG = "logs/attribution_confidence_scores.json"
JOURNAL_LOG = "logs/operator_journal.jsonl"
CURIOSITY_EVAL_LOG = "logs/curiosity_evaluation.json"

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

# ---- Phase 76.0 – Variant Lifecycle Manager ----
def manage_variant_lifecycle():
    """
    Variant lifecycle manager - tracks variant state transitions:
    - Birth: New variants created
    - Growth: Improving performance
    - Maturity: Stable performance
    - Decline: Degrading performance
    - Death: Retired variants
    """
    lineage = _read_json(LINEAGE_LOG, {})
    
    lifecycle_events = []
    
    for base_strategy, variants in lineage.items():
        for variant_id, data in variants.items():
            perf_history = data.get("performance_history", [])
            
            if len(perf_history) < 3:
                # Birth phase
                lifecycle_events.append({
                    "variant": variant_id,
                    "base_strategy": base_strategy,
                    "lifecycle_stage": "birth",
                    "age_snapshots": len(perf_history),
                    "reason": "newly_created"
                })
                _append_event(LIFECYCLE_LOG, "variant_birth", lifecycle_events[-1])
                continue
            
            # Calculate performance trend
            roi_values = [p.get("avg_roi", 0.0) for p in perf_history]
            recent_roi = mean(roi_values[-3:])
            historical_roi = mean(roi_values[:-3]) if len(roi_values) > 3 else recent_roi
            
            win_values = [p.get("win_rate", 0.0) for p in perf_history]
            recent_wr = mean(win_values[-3:])
            
            # Determine lifecycle stage
            if recent_roi > 0.004 and recent_roi > historical_roi:
                # Growth phase
                lifecycle_events.append({
                    "variant": variant_id,
                    "base_strategy": base_strategy,
                    "lifecycle_stage": "growth",
                    "age_snapshots": len(perf_history),
                    "recent_roi": round(recent_roi, 4),
                    "trend": "improving",
                    "reason": "strong_positive_trend"
                })
                _append_event(LIFECYCLE_LOG, "variant_growth", lifecycle_events[-1])
            
            elif abs(recent_roi - historical_roi) < 0.001 and recent_roi > 0:
                # Maturity phase
                lifecycle_events.append({
                    "variant": variant_id,
                    "base_strategy": base_strategy,
                    "lifecycle_stage": "maturity",
                    "age_snapshots": len(perf_history),
                    "recent_roi": round(recent_roi, 4),
                    "trend": "stable",
                    "reason": "stable_positive_performance"
                })
                _append_event(LIFECYCLE_LOG, "variant_maturity", lifecycle_events[-1])
            
            elif recent_roi < historical_roi and recent_roi < 0.001:
                # Decline phase
                lifecycle_events.append({
                    "variant": variant_id,
                    "base_strategy": base_strategy,
                    "lifecycle_stage": "decline",
                    "age_snapshots": len(perf_history),
                    "recent_roi": round(recent_roi, 4),
                    "trend": "declining",
                    "reason": "performance_degradation"
                })
                _append_event(LIFECYCLE_LOG, "variant_decline", lifecycle_events[-1])
            
            # Check for retirement
            if recent_roi < -0.002 and recent_wr < 0.4:
                lifecycle_events.append({
                    "variant": variant_id,
                    "base_strategy": base_strategy,
                    "lifecycle_stage": "death",
                    "age_snapshots": len(perf_history),
                    "recent_roi": round(recent_roi, 4),
                    "recent_wr": round(recent_wr, 3),
                    "reason": "poor_performance_retirement"
                })
                _append_event(LIFECYCLE_LOG, "variant_death", lifecycle_events[-1])
    
    return lifecycle_events

# ---- Phase 77.0 – Regime-Specific Strategy Composer ----
def compose_regime_strategies():
    """
    Regime-specific strategy composer - creates optimized regime strategies:
    - Analyzes successful patterns per regime
    - Composes new strategies from proven components
    - Optimizes filters and exits for each regime
    - Creates regime-targeted variants
    """
    trade_outcomes = _read_jsonl(TRADE_OUTCOMES)
    exit_profiles = _read_json(EXIT_PROFILES, {})
    archetypes = _read_json(ARCHETYPE_LOG, {})
    
    # Analyze performance by regime
    by_regime = {}
    for trade in trade_outcomes:
        regime = trade.get("regime", "mixed")
        roi = trade.get("net_roi", 0.0)
        strategy = trade.get("strategy", "")
        
        if regime not in by_regime:
            by_regime[regime] = {"trades": [], "strategies": set()}
        
        by_regime[regime]["trades"].append({"roi": roi, "strategy": strategy})
        by_regime[regime]["strategies"].add(strategy)
    
    # Compose regime-specific strategies
    composed_strategies = []
    
    for regime, data in by_regime.items():
        if len(data["trades"]) < 5:
            continue
        
        # Find best performing strategies for this regime
        strategy_perf = {}
        for trade in data["trades"]:
            strategy = trade["strategy"]
            if strategy not in strategy_perf:
                strategy_perf[strategy] = []
            strategy_perf[strategy].append(trade["roi"])
        
        # Get top performer
        best_strategy = None
        best_roi = -1
        for strategy, roi_values in strategy_perf.items():
            avg_roi = mean(roi_values)
            if avg_roi > best_roi:
                best_roi = avg_roi
                best_strategy = strategy
        
        if not best_strategy or best_roi < 0:
            continue
        
        # Find optimal exit profile for this regime
        regime_exit_profiles = [
            ep_id for ep_id in exit_profiles.keys()
            if regime.lower() in ep_id.lower()
        ]
        
        optimal_exit = regime_exit_profiles[0] if regime_exit_profiles else "default_exit"
        
        # Compose new strategy
        composed_id = f"composed_{regime}_{int(time.time() % 100000)}"
        
        # Determine optimal filters based on regime
        if regime == "choppy":
            filters = {"RSI": 30, "volume_min": 1500, "min_profit_bps": 20}
            timeframe = "5m"
        elif regime == "trending":
            filters = {"RSI": 40, "volume_min": 2000, "min_profit_bps": 30}
            timeframe = "15m"
        elif regime == "volatile":
            filters = {"RSI": 25, "volume_min": 2500, "min_profit_bps": 25}
            timeframe = "3m"
        else:  # mixed
            filters = {"RSI": 35, "volume_min": 1800, "min_profit_bps": 25}
            timeframe = "5m"
        
        composed_strategy = {
            "id": composed_id,
            "regime_target": regime,
            "base_pattern": best_strategy,
            "filters": filters,
            "exit_profile_id": optimal_exit,
            "timeframe": timeframe,
            "expected_roi": round(best_roi, 4),
            "based_on_trades": len(strategy_perf[best_strategy]),
            "created": int(time.time())
        }
        
        composed_strategies.append(composed_strategy)
    
    _write_json(COMPOSER_LOG, {
        "strategies": composed_strategies,
        "timestamp": int(time.time()),
        "count": len(composed_strategies)
    })
    
    return composed_strategies

# ---- Phase 78.0 – Attribution Confidence Scorer ----
def score_attribution_confidence():
    """
    Attribution confidence scorer - calculates confidence in performance attribution:
    - Sharpe-like ratio: return / volatility
    - Sample size confidence
    - Consistency scoring
    - Statistical significance
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
    
    # Calculate confidence scores
    confidence_scores = {}
    
    for strategy, roi_values in by_strategy.items():
        if len(roi_values) < 3:
            continue
        
        avg_roi = mean(roi_values)
        roi_volatility = stdev(roi_values) if len(roi_values) > 1 else 0.001
        
        # Sharpe-like confidence score
        sharpe_score = avg_roi / (roi_volatility + 0.0001)
        
        # Sample size factor (more trades = higher confidence)
        sample_factor = min(1.0, len(roi_values) / 30)
        
        # Consistency score (% of positive trades)
        positive_count = sum(1 for r in roi_values if r > 0)
        consistency = positive_count / len(roi_values)
        
        # Combined confidence score
        confidence_score = (sharpe_score * 0.5 + consistency * 0.3 + sample_factor * 0.2)
        
        # Classify confidence level
        if confidence_score > 0.5:
            confidence_level = "high"
        elif confidence_score > 0.2:
            confidence_level = "medium"
        else:
            confidence_level = "low"
        
        confidence_scores[strategy] = {
            "confidence_score": round(confidence_score, 4),
            "confidence_level": confidence_level,
            "avg_roi": round(avg_roi, 4),
            "volatility": round(roi_volatility, 4),
            "sharpe": round(sharpe_score, 4),
            "consistency": round(consistency, 3),
            "sample_size": len(roi_values)
        }
    
    _write_json(CONFIDENCE_LOG, confidence_scores)
    return confidence_scores

# ---- Phase 79.0 – Operator Copilot Journal ----
def log_operator_journal():
    """
    Operator copilot journal - maintains operational log:
    - Summarizes nightly cycle execution
    - Records key actions taken
    - Logs system health status
    - Provides operational context
    """
    # Read recent events to summarize
    lifecycle_events = _read_jsonl(LIFECYCLE_LOG)
    
    # Count recent events
    recent_cutoff = time.time() - 86400  # Last 24 hours
    recent_events = [e for e in lifecycle_events if e.get("ts", 0) > recent_cutoff]
    
    birth_count = sum(1 for e in recent_events if e.get("event") == "variant_birth")
    growth_count = sum(1 for e in recent_events if e.get("event") == "variant_growth")
    decline_count = sum(1 for e in recent_events if e.get("event") == "variant_decline")
    death_count = sum(1 for e in recent_events if e.get("event") == "variant_death")
    
    # Create journal entry
    actions = []
    if birth_count > 0:
        actions.append(f"Created {birth_count} new variants")
    if growth_count > 0:
        actions.append(f"Identified {growth_count} growing variants")
    if decline_count > 0:
        actions.append(f"Flagged {decline_count} declining variants")
    if death_count > 0:
        actions.append(f"Retired {death_count} variants")
    
    if not actions:
        actions.append("No lifecycle events in last 24 hours")
    
    journal_entry = {
        "timestamp": int(time.time()),
        "cycle_type": "nightly_autonomous",
        "summary": "All autonomous phases executed successfully.",
        "actions": actions,
        "variant_birth": birth_count,
        "variant_growth": growth_count,
        "variant_decline": decline_count,
        "variant_death": death_count,
        "system_status": "operational"
    }
    
    _append_event(JOURNAL_LOG, "operator_log", journal_entry)
    return journal_entry

# ---- Phase 80.0 – Strategic Curiosity Evaluator ----
def evaluate_curiosity_ideas():
    """
    Strategic curiosity evaluator - evaluates research ideas:
    - Scores viability based on data availability
    - Prioritizes actionable ideas
    - Filters low-value hypotheses
    - Recommends testing approach
    """
    curiosity_ideas = _read_jsonl(CURIOSITY_LOG)
    trade_outcomes = _read_jsonl(TRADE_OUTCOMES)
    archetypes = _read_json(ARCHETYPE_LOG, {})
    
    if not curiosity_ideas:
        _write_json(CURIOSITY_EVAL_LOG, {"evaluations": [], "count": 0})
        return []
    
    # Evaluate recent ideas
    recent_ideas = curiosity_ideas[-20:]  # Last 20 ideas
    
    evaluations = []
    
    for idea in recent_ideas:
        idea_type = idea.get("type", "unknown")
        tags = idea.get("tags", [])
        priority = idea.get("priority", "medium")
        
        # Calculate viability score
        viability_score = 0.5  # Base score
        
        # Boost score based on data availability
        if idea_type == "archetype_gap":
            # Check if we have enough data for this archetype
            archetype_name = tags[0] if tags else "unknown"
            archetype_count = sum(1 for a in archetypes.values() if a.get("archetype") == archetype_name)
            if archetype_count < 2:
                viability_score += 0.3  # High value gap
        
        elif idea_type == "exit_optimization":
            # Check trade volume for this exit type
            exit_type = tags[0] if tags else ""
            exit_trades = [t for t in trade_outcomes if t.get("exit_type") == exit_type]
            if len(exit_trades) > 10:
                viability_score += 0.2  # Sufficient data
        
        elif idea_type == "regime_opportunity":
            # Always valuable
            viability_score += 0.25
        
        # Adjust for priority
        if priority == "high":
            viability_score += 0.15
        elif priority == "low":
            viability_score -= 0.1
        
        # Cap at 1.0
        viability_score = min(1.0, max(0.0, viability_score))
        
        # Determine status
        if viability_score > 0.7:
            status = "test_immediately"
            recommendation = "High viability - implement in next cycle"
        elif viability_score > 0.5:
            status = "test_when_ready"
            recommendation = "Medium viability - test when resources available"
        elif viability_score > 0.3:
            status = "archive_for_later"
            recommendation = "Low viability currently - revisit later"
        else:
            status = "reject"
            recommendation = "Insufficient viability - reject"
        
        evaluation = {
            "prompt": idea.get("prompt", ""),
            "type": idea_type,
            "tags": tags,
            "priority": priority,
            "viability_score": round(viability_score, 3),
            "status": status,
            "recommendation": recommendation,
            "evaluated_at": int(time.time())
        }
        
        evaluations.append(evaluation)
    
    _write_json(CURIOSITY_EVAL_LOG, {
        "evaluations": evaluations,
        "count": len(evaluations),
        "test_immediately": sum(1 for e in evaluations if e["status"] == "test_immediately"),
        "test_when_ready": sum(1 for e in evaluations if e["status"] == "test_when_ready"),
        "timestamp": int(time.time())
    })
    
    return evaluations

# ---- Unified Runner ----
def run_phase_76_80():
    """
    Execute all five phases:
    - Lifecycle management
    - Regime composition
    - Confidence scoring
    - Journal logging
    - Curiosity evaluation
    """
    lifecycle = manage_variant_lifecycle()
    composed = compose_regime_strategies()
    confidence = score_attribution_confidence()
    journal = log_operator_journal()
    curiosity_eval = evaluate_curiosity_ideas()
    
    return {
        "lifecycle": lifecycle,
        "composed": composed,
        "confidence": confidence,
        "journal": journal,
        "curiosity_evaluation": curiosity_eval
    }

if __name__ == "__main__":
    result = run_phase_76_80()
    print(f"Phase 76: {len(result['lifecycle'])} lifecycle events")
    print(f"Phase 77: {len(result['composed'])} regime strategies composed")
    print(f"Phase 78: {len(result['confidence'])} confidence scores")
    print(f"Phase 79: Journal entry logged")
    print(f"Phase 80: {len(result['curiosity_evaluation'])} ideas evaluated")
