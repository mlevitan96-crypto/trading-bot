# src/phase_96_100.py
#
# Phases 96–100: Strategy Orchestrator, Forecast Synthesizer, Long-Term Planner,
#               Operator Reflection Engine, Evolution Summary Generator

import os
import json
import time
from statistics import mean
from typing import Dict, List, Any

# Paths
LINEAGE_LOG = "config/strategy_lineage.json"
SHADOW_STATE = "config/shadow_strategy_state.json"
TRADE_OUTCOMES = "logs/trade_outcomes.jsonl"
STRATEGIC_ATTRIBUTION = "logs/strategic_attribution.jsonl"
REGIME_FORECAST = "logs/regime_forecast.json"
LIFECYCLE_LOG = "logs/variant_lifecycle_events.jsonl"
OPERATOR_DIGEST = "logs/operator_digest.json"
CURIOSITY_TRACKER = "logs/curiosity_tracker.json"
STABILITY_LOG = "logs/attribution_stability_index.json"

ORCHESTRATOR_LOG = "logs/strategy_orchestration_plan.json"
FORECAST_SYNTHESIS_LOG = "logs/forecast_synthesis.json"
LONG_TERM_PLAN_LOG = "logs/long_term_strategy_plan.json"
REFLECTION_LOG = "logs/operator_reflection.jsonl"
EVOLUTION_SUMMARY_LOG = "logs/evolution_summary.json"

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

# ---- Phase 96.0 – Strategy Orchestrator ----
def orchestrate_strategies():
    """
    Strategy orchestrator - coordinates all strategy actions:
    - Analyzes performance across all variants
    - Generates comprehensive action plan
    - Prioritizes scale up/down/hold decisions
    - Coordinates capital allocation changes
    """
    lineage = _read_json(LINEAGE_LOG, {})
    stability = _read_json(STABILITY_LOG, {}).get("strategies", {})
    
    orchestration_plan = []
    
    for base_strategy, variants in lineage.items():
        for variant_id, data in variants.items():
            perf_history = data.get("performance_history", [])
            
            if len(perf_history) < 5:
                continue
            
            # Calculate performance metrics
            roi_values = [p.get("avg_roi", 0.0) for p in perf_history]
            wr_values = [p.get("win_rate", 0.0) for p in perf_history]
            
            avg_roi = mean(roi_values)
            avg_wr = mean(wr_values)
            recent_roi = mean(roi_values[-3:])
            
            # Get stability if available
            stability_score = stability.get(variant_id, {}).get("stability_score", 0)
            
            # Determine action
            if avg_roi > 0.003 and stability_score > 20:
                action = "scale_up"
                priority = "high"
                reason = "strong_performance_and_stable"
            elif avg_roi > 0.001 and recent_roi > avg_roi:
                action = "scale_up"
                priority = "medium"
                reason = "improving_trend"
            elif avg_roi < -0.001 or stability_score < 5:
                action = "scale_down"
                priority = "high"
                reason = "poor_performance_or_unstable"
            elif recent_roi < avg_roi * 0.5:
                action = "scale_down"
                priority = "medium"
                reason = "declining_trend"
            else:
                action = "hold"
                priority = "low"
                reason = "neutral_performance"
            
            orchestration_plan.append({
                "base_strategy": base_strategy,
                "variant_id": variant_id,
                "avg_roi": round(avg_roi, 4),
                "avg_win_rate": round(avg_wr, 3),
                "recent_roi": round(recent_roi, 4),
                "stability_score": round(stability_score, 2),
                "action": action,
                "priority": priority,
                "reason": reason
            })
    
    # Sort by priority and performance
    priority_order = {"high": 0, "medium": 1, "low": 2}
    orchestration_plan.sort(
        key=lambda x: (priority_order.get(x["priority"], 3), -x["avg_roi"])
    )
    
    _write_json(ORCHESTRATOR_LOG, {
        "plan": orchestration_plan,
        "total_strategies": len(orchestration_plan),
        "scale_up": sum(1 for p in orchestration_plan if p["action"] == "scale_up"),
        "scale_down": sum(1 for p in orchestration_plan if p["action"] == "scale_down"),
        "hold": sum(1 for p in orchestration_plan if p["action"] == "hold"),
        "timestamp": int(time.time())
    })
    
    return orchestration_plan

# ---- Phase 97.0 – Forecast Synthesizer ----
def synthesize_forecast():
    """
    Forecast synthesizer - synthesizes regime predictions:
    - Combines regime forecast with market conditions
    - Generates actionable trading recommendations
    - Provides confidence-weighted guidance
    - Links regime to strategy preferences
    """
    regime_forecast = _read_json(REGIME_FORECAST, {})
    
    predicted_regime = regime_forecast.get("predicted_regime", "mixed")
    volatility = regime_forecast.get("volatility", 0)
    trend_strength = regime_forecast.get("trend_strength", 0)
    confidence = regime_forecast.get("confidence", 0)
    
    # Classify volatility
    if volatility > 0.03:
        vol_class = "high"
    elif volatility > 0.015:
        vol_class = "moderate"
    else:
        vol_class = "low"
    
    # Classify trend
    if abs(trend_strength) > 0.7:
        trend_class = "strong"
    elif abs(trend_strength) > 0.3:
        trend_class = "moderate"
    else:
        trend_class = "weak"
    
    # Generate recommendations
    if predicted_regime == "trending" and trend_class == "strong":
        recommended_archetypes = ["trend_follower", "momentum"]
        expected_behavior = "Favor trend-following strategies with wide stops"
    elif predicted_regime == "choppy":
        recommended_archetypes = ["mean_reversion", "scalper"]
        expected_behavior = "Favor mean-reversion and quick scalping strategies"
    elif predicted_regime == "volatile":
        recommended_archetypes = ["breakout", "momentum"]
        expected_behavior = "Favor breakout strategies with tight stops"
    else:
        recommended_archetypes = ["conservative", "mixed"]
        expected_behavior = "Balanced approach across strategy types"
    
    synthesis = {
        "regime": predicted_regime,
        "volatility": round(volatility, 4),
        "volatility_class": vol_class,
        "trend_strength": round(trend_strength, 3),
        "trend_class": trend_class,
        "confidence": round(confidence, 3),
        "recommended_archetypes": recommended_archetypes,
        "expected_behavior": expected_behavior,
        "risk_level": "high" if vol_class == "high" else "moderate" if vol_class == "moderate" else "low",
        "timestamp": int(time.time())
    }
    
    _write_json(FORECAST_SYNTHESIS_LOG, synthesis)
    return synthesis

# ---- Phase 98.0 – Long-Term Strategy Planner ----
def generate_long_term_plan():
    """
    Long-term strategy planner - creates 30/90 day strategic plan:
    - Sets mutation cycle targets
    - Plans composition goals
    - Schedules curiosity testing
    - Defines capital allocation shifts
    """
    curiosity_tracker = _read_json(CURIOSITY_TRACKER, {})
    lifecycle_events = _read_jsonl(LIFECYCLE_LOG)
    operator_digest = _read_json(OPERATOR_DIGEST, {})
    
    # Calculate current trends
    recent_births = sum(1 for e in lifecycle_events[-50:] if e.get("event") == "variant_birth")
    recent_deaths = sum(1 for e in lifecycle_events[-50:] if e.get("event") == "variant_death")
    
    actionable_ideas = curiosity_tracker.get("actionable_ideas", 0)
    total_ideas = curiosity_tracker.get("total_ideas_evaluated", 0)
    
    # 30-day plan
    next_30_days = {
        "mutation_cycles": 4,  # Weekly mutations
        "composition_targets": max(2, recent_births // 2),
        "expected_regime": "adapting to market conditions",
        "capital_shifts": "Toward high-stability, positive-ROI variants",
        "retirement_target": max(1, recent_deaths),
        "testing_focus": "Regime-specific optimizations"
    }
    
    # 90-day plan
    next_90_days = {
        "strategy_forks": 6,  # New variant lineages
        "exit_evolution_cycles": 12,  # Weekly exit optimizations
        "curiosity_testing": min(10, actionable_ideas),
        "archetype_diversification": "Expand underrepresented archetypes",
        "performance_target": "+2% absolute improvement",
        "capital_efficiency": "Reduce position sizes on low-performers"
    }
    
    plan = {
        "next_30_days": next_30_days,
        "next_90_days": next_90_days,
        "strategic_priorities": [
            "Maintain profitable variants",
            "Mutate declining strategies",
            "Test curiosity-driven hypotheses",
            "Optimize regime-specific exits",
            "Improve capital allocation efficiency"
        ],
        "risk_management": {
            "max_portfolio_drawdown": "5%",
            "position_size_limits": "$100-$500",
            "leverage_cap": "30% of portfolio for futures"
        },
        "generated_at": int(time.time())
    }
    
    _write_json(LONG_TERM_PLAN_LOG, plan)
    return plan

# ---- Phase 99.0 – Operator Reflection Engine ----
def log_operator_reflection():
    """
    Operator reflection engine - generates system reflection:
    - Analyzes recent system performance (ENHANCED: includes USD P&L velocity)
    - Identifies improvement areas
    - Logs operational insights
    - Recommends next focus areas
    - ENHANCED: Detects policy cap saturation and profit velocity issues
    """
    lifecycle_events = _read_jsonl(LIFECYCLE_LOG)
    operator_digest = _read_json(OPERATOR_DIGEST, {})
    trade_outcomes = _read_jsonl(TRADE_OUTCOMES)
    
    # ENHANCED: Load policy cap and profit velocity data
    from src.policy_cap_events import get_policy_cap_summary, get_profit_velocity_summary
    cap_summary = get_policy_cap_summary(hours=168)  # 7 days
    profit_velocity = get_profit_velocity_summary(hours=168)  # 7 days
    
    # Recent performance
    recent_trades = trade_outcomes[-50:] if len(trade_outcomes) > 50 else trade_outcomes
    
    if recent_trades:
        recent_roi_values = [t.get("net_roi", 0.0) for t in recent_trades]
        avg_recent_roi = mean(recent_roi_values)
        win_rate = sum(1 for r in recent_roi_values if r > 0) / len(recent_roi_values)
    else:
        avg_recent_roi = 0.0
        win_rate = 0.0
    
    # ENHANCED: Calculate USD P&L metrics (not just percentage)
    avg_profit_usd = profit_velocity.get("avg_profit_usd", 0.0)
    avg_profit_per_hour = profit_velocity.get("avg_profit_per_hour_usd", 0.0)
    total_trades = profit_velocity.get("total_trades", 0)
    
    # Lifecycle analysis
    recent_events = lifecycle_events[-20:] if len(lifecycle_events) > 20 else lifecycle_events
    growth_count = sum(1 for e in recent_events if e.get("lifecycle_stage") == "growth")
    decline_count = sum(1 for e in recent_events if e.get("lifecycle_stage") == "decline")
    
    # ENHANCED: Generate reflection with USD P&L awareness
    if avg_profit_usd > 1.0 and avg_recent_roi > 0.002:
        performance_assessment = "Strong recent performance with meaningful USD profits"
        next_focus = "Maintain current strategies, explore scaling winners"
    elif avg_profit_usd > 0 and avg_profit_usd < 0.50:
        performance_assessment = "Profitable but tiny profits - position sizes too small"
        next_focus = "CRITICAL: Increase position sizing limits to maximize profitable signals"
    elif avg_recent_roi > 0:
        performance_assessment = "Neutral performance, system stable but not exceptional"
        next_focus = "Identify and amplify best performers, mutate underperformers"
    else:
        performance_assessment = "Challenging performance, system needs optimization"
        next_focus = "Review strategy mix, increase mutation rate, test new approaches"
    
    # ENHANCED: Add policy cap saturation detection
    cap_saturation_detected = cap_summary.get("high_severity_count", 0) >= 3
    if cap_saturation_detected:
        performance_assessment += " | POLICY CAPS BLOCKING GROWTH"
        next_focus += " | Recommend increasing position size limits"
    
    if growth_count > decline_count:
        lifecycle_assessment = "Positive lifecycle trends with more growth than decline"
    else:
        lifecycle_assessment = "Concerning lifecycle trends, review strategy quality"
    
    # ENHANCED: Build recommendations with USD P&L awareness
    recommendations = [
        "Continue autonomous evolution cycles",
        "Monitor regime forecast accuracy",
        "Test high-viability curiosity ideas",
        "Optimize capital allocation based on stability"
    ]
    
    if cap_saturation_detected:
        recommendations.insert(0, f"🚨 URGENT: Kelly sizing hitting policy caps {cap_summary['total_caps']}x - increase limits from $200-$1000 to $400-$2000")
    
    if avg_profit_usd > 0 and avg_profit_usd < 0.50 and total_trades >= 5:
        recommendations.insert(0, f"⚠️ Position sizes too small: Avg profit ${avg_profit_usd:.4f}/trade - profitable signals not being maximized")
    
    reflection = {
        "timestamp": int(time.time()),
        "performance_assessment": performance_assessment,
        "lifecycle_assessment": lifecycle_assessment,
        "avg_recent_roi": round(avg_recent_roi, 4),
        "recent_win_rate": round(win_rate, 3),
        "avg_profit_usd": round(avg_profit_usd, 4),  # ENHANCED
        "avg_profit_per_hour_usd": round(avg_profit_per_hour, 4),  # ENHANCED
        "policy_cap_count": cap_summary.get("total_caps", 0),  # ENHANCED
        "cap_saturation_detected": cap_saturation_detected,  # ENHANCED
        "growth_vs_decline": f"{growth_count} growth vs {decline_count} decline",
        "system_alerts": operator_digest.get("alert_count", 0),
        "next_focus": next_focus,
        "recommendations": recommendations
    }
    
    _append_event(REFLECTION_LOG, "operator_reflection", reflection)
    return reflection

# ---- Phase 100.0 – Evolution Summary Generator ----
def generate_evolution_summary():
    """
    Evolution summary generator - summarizes system evolution:
    - Total attribution events processed
    - Average performance metrics
    - Signal clarity improvements
    - Overall evolution progress
    """
    trade_outcomes = _read_jsonl(TRADE_OUTCOMES)
    lineage = _read_json(LINEAGE_LOG, {})
    lifecycle_events = _read_jsonl(LIFECYCLE_LOG)
    
    # Calculate summary metrics
    total_trades = len(trade_outcomes)
    
    if trade_outcomes:
        roi_values = [t.get("net_roi", 0.0) for t in trade_outcomes]
        avg_roi = mean(roi_values)
        
        exit_types = [t.get("exit_type", "unknown") for t in trade_outcomes]
        clarity_count = sum(1 for et in exit_types if et not in ["unknown", "", None])
        clarity_rate = clarity_count / len(exit_types) if exit_types else 0
    else:
        avg_roi = 0.0
        clarity_rate = 0.0
    
    # Count variants
    total_variants = sum(len(variants) for variants in lineage.values())
    
    # Lifecycle summary
    birth_count = sum(1 for e in lifecycle_events if e.get("event") == "variant_birth")
    death_count = sum(1 for e in lifecycle_events if e.get("event") == "variant_death")
    growth_count = sum(1 for e in lifecycle_events if e.get("event") == "variant_growth")
    
    summary = {
        "total_attribution_events": total_trades,
        "total_variants": total_variants,
        "avg_roi": round(avg_roi, 4),
        "signal_clarity_rate": round(clarity_rate, 3),
        "lifecycle_summary": {
            "births": birth_count,
            "deaths": death_count,
            "growth_events": growth_count,
            "net_growth": birth_count - death_count
        },
        "evolution_health": "healthy" if avg_roi > 0 and clarity_rate > 0.7 else "needs_improvement",
        "timestamp": int(time.time())
    }
    
    _write_json(EVOLUTION_SUMMARY_LOG, summary)
    return summary

# ---- Unified Runner ----
def run_phase_96_100():
    """
    Execute all five phases:
    - Strategy orchestration
    - Forecast synthesis
    - Long-term planning
    - Operator reflection
    - Evolution summary
    """
    orchestration = orchestrate_strategies()
    forecast = synthesize_forecast()
    long_term_plan = generate_long_term_plan()
    reflection = log_operator_reflection()
    evolution_summary = generate_evolution_summary()
    
    return {
        "orchestration_plan": orchestration,
        "forecast_synthesis": forecast,
        "long_term_plan": long_term_plan,
        "operator_reflection": reflection,
        "evolution_summary": evolution_summary
    }

if __name__ == "__main__":
    result = run_phase_96_100()
    print(f"Phase 96: {len(result['orchestration_plan'])} strategies orchestrated")
    print(f"Phase 97: Forecast synthesized for {result['forecast_synthesis']['regime']} regime")
    print(f"Phase 98: Long-term plan generated")
    print(f"Phase 99: Reflection logged")
    print(f"Phase 100: Evolution summary - {result['evolution_summary']['total_attribution_events']} events, {result['evolution_summary']['avg_roi']:.2%} avg ROI")
