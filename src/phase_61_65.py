# src/phase_61_65.py
#
# Phases 61–65: Tournament Engine, Attribution Heatmap, Regime Transition Tracker,
#              Sentiment Synthesizer, Operator Alert System

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
REGIME_MEMORY = "logs/symbol_regime_memory.json"
EXPECTANCY_LOG = "logs/expectancy_scores.json"
STRATEGY_PROFILES = "logs/strategy_profiles.json"

TOURNAMENT_LOG = "logs/strategy_tournament_results.json"
HEATMAP_LOG = "logs/attribution_heatmap.json"
TRANSITION_LOG = "logs/regime_transition_log.json"
SENTIMENT_LOG = "logs/strategy_sentiment_scores.json"
ALERT_LOG = "logs/operator_alerts.jsonl"
TOURNAMENT_EVENTS = "logs/tournament_events.jsonl"

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

# ---- Phase 61.0 – Strategy Tournament Engine ----
def run_strategy_tournament():
    """
    Strategy tournament engine - ranks and promotes/retires variants:
    - Calculates composite scores (ROI × WR × Sharpe)
    - Ranks all variants by expectancy
    - Auto-promotes top 3 performers
    - Auto-retires bottom 3 performers
    """
    lineage = _read_json(LINEAGE_LOG, {})
    expectancy = _read_json(EXPECTANCY_LOG, {})
    
    tournament_results = []
    
    # Analyze each variant's performance
    for base_strategy, variants in lineage.items():
        for variant_id, data in variants.items():
            perf_history = data.get("performance_history", [])
            
            if len(perf_history) < 5:
                continue  # Need sufficient data for tournament
            
            # Extract metrics
            roi_values = [p.get("avg_roi", 0.0) for p in perf_history]
            win_values = [p.get("win_rate", 0.0) for p in perf_history]
            
            avg_roi = mean(roi_values)
            avg_wr = mean(win_values)
            max_dd = min(roi_values)  # Maximum drawdown
            
            # Get expectancy if available
            exp_score = 0
            for key, exp_data in expectancy.items():
                if variant_id in key:
                    exp_score = exp_data.get("expectancy", 0)
                    break
            
            # Calculate composite tournament score
            # Score = (ROI × 100) + (WR × 50) + (Expectancy × 1000) - (|DD| × 100)
            tournament_score = (
                (avg_roi * 100) +
                (avg_wr * 50) +
                (exp_score * 1000) -
                (abs(max_dd) * 100)
            )
            
            tournament_results.append({
                "strategy": base_strategy,
                "variant": variant_id,
                "roi": round(avg_roi, 4),
                "win_rate": round(avg_wr, 3),
                "drawdown": round(max_dd, 4),
                "expectancy": round(exp_score, 5),
                "tournament_score": round(tournament_score, 2),
                "snapshots": len(perf_history),
                "status": data.get("status", "active")
            })
    
    # Rank by tournament score
    tournament_results.sort(key=lambda x: x["tournament_score"], reverse=True)
    
    # Promote top 3
    for result in tournament_results[:3]:
        if result["tournament_score"] > 0:
            _append_event(TOURNAMENT_EVENTS, "tournament_promote", {
                "variant": result["variant"],
                "score": result["tournament_score"],
                "rank": tournament_results.index(result) + 1
            })
    
    # Retire bottom 3
    for result in tournament_results[-3:]:
        if result["tournament_score"] < 0:
            _append_event(TOURNAMENT_EVENTS, "tournament_retire", {
                "variant": result["variant"],
                "score": result["tournament_score"],
                "rank": tournament_results.index(result) + 1
            })
    
    _write_json(TOURNAMENT_LOG, {
        "results": tournament_results,
        "timestamp": int(time.time()),
        "total_participants": len(tournament_results)
    })
    
    return tournament_results

# ---- Phase 62.0 – Attribution Heatmap Generator ----
def generate_attribution_heatmap():
    """
    Attribution heatmap generator - visualizes performance across dimensions:
    - Symbol × Timeframe × Regime matrix
    - Identifies hot/cold spots in parameter space
    - Highlights underperforming combinations
    """
    trade_outcomes = _read_jsonl(TRADE_OUTCOMES)
    
    heatmap = {}
    
    # Group by symbol, timeframe, regime
    for trade in trade_outcomes:
        symbol = trade.get("symbol", "")
        timeframe = trade.get("timeframe", "5m")
        regime = trade.get("regime", "unknown")
        roi = trade.get("net_roi", 0.0)
        
        if not symbol:
            continue
        
        key = f"{symbol}_{timeframe}_{regime}"
        
        if key not in heatmap:
            heatmap[key] = {"roi_values": [], "count": 0}
        
        heatmap[key]["roi_values"].append(roi)
        heatmap[key]["count"] += 1
    
    # Calculate summary statistics
    summary = {}
    for key, data in heatmap.items():
        if len(data["roi_values"]) < 3:
            continue  # Skip sparse cells
        
        avg_roi = mean(data["roi_values"])
        win_rate = sum(1 for r in data["roi_values"] if r > 0) / len(data["roi_values"])
        
        parts = key.split("_")
        summary[key] = {
            "symbol": parts[0] if len(parts) > 0 else "unknown",
            "timeframe": parts[1] if len(parts) > 1 else "unknown",
            "regime": parts[2] if len(parts) > 2 else "unknown",
            "avg_roi": round(avg_roi, 4),
            "win_rate": round(win_rate, 3),
            "trade_count": data["count"],
            "heat_score": round(avg_roi * win_rate * 100, 2)  # Combined heat metric
        }
    
    _write_json(HEATMAP_LOG, summary)
    return summary

# ---- Phase 63.0 – Regime Transition Tracker ----
def track_regime_transitions():
    """
    Regime transition tracker - monitors market regime changes:
    - Detects regime shifts from forecasts
    - Logs transition history with volatility context
    - Calculates regime persistence metrics
    """
    forecast = _read_json(REGIME_FORECAST, {})
    transition_history = _read_json(TRANSITION_LOG, {"transitions": [], "stats": {}})
    
    current_regime = forecast.get("predicted_regime", "unknown")
    last_transition = transition_history["transitions"][-1] if transition_history["transitions"] else None
    last_regime = last_transition.get("to") if last_transition else None
    
    # Detect regime shift
    if current_regime != last_regime and current_regime != "unknown":
        transition = {
            "timestamp": int(time.time()),
            "from": last_regime,
            "to": current_regime,
            "volatility": forecast.get("volatility", 0),
            "trend_strength": forecast.get("trend_strength", 0),
            "confidence": forecast.get("confidence", 0)
        }
        
        transition_history["transitions"].append(transition)
        _append_event(TRANSITION_LOG, "regime_shift", transition)
        
        # Update regime persistence stats
        if last_regime:
            persistence_key = f"{last_regime}_persistence_mins"
            if last_transition:
                duration = (transition["timestamp"] - last_transition["timestamp"]) / 60
                if persistence_key not in transition_history["stats"]:
                    transition_history["stats"][persistence_key] = []
                transition_history["stats"][persistence_key].append(round(duration, 1))
    
    # Calculate average persistence per regime
    for key, durations in transition_history.get("stats", {}).items():
        if durations:
            avg_key = key.replace("_mins", "_avg_mins")
            transition_history["stats"][avg_key] = round(mean(durations), 1)
    
    _write_json(TRANSITION_LOG, transition_history)
    return transition_history

# ---- Phase 64.0 – Strategy Sentiment Synthesizer ----
def synthesize_strategy_sentiment():
    """
    Strategy sentiment synthesizer - generates sentiment scores:
    - Combines performance + regime alignment + momentum
    - Calculates bullish/bearish sentiment per variant
    - Factors in recent trend direction
    """
    lineage = _read_json(LINEAGE_LOG, {})
    forecast = _read_json(REGIME_FORECAST, {})
    shadow_state = _read_json(SHADOW_STATE, {})
    
    sentiment_scores = {}
    
    predicted_regime = forecast.get("predicted_regime", "unknown")
    
    for base_strategy, variants in lineage.items():
        for variant_id, data in variants.items():
            perf_history = data.get("performance_history", [])
            
            if len(perf_history) < 5:
                continue
            
            # Extract performance metrics
            roi_values = [p.get("avg_roi", 0.0) for p in perf_history]
            win_values = [p.get("win_rate", 0.0) for p in perf_history]
            
            avg_roi = mean(roi_values)
            avg_wr = mean(win_values)
            
            # Calculate momentum (recent vs historical)
            recent_roi = mean(roi_values[-3:])
            historical_roi = mean(roi_values[:-3]) if len(roi_values) > 3 else avg_roi
            momentum = recent_roi - historical_roi
            
            # Regime alignment score
            regime_match = 1.0
            for shadow_base, shadow_variants in shadow_state.items():
                for sv in shadow_variants:
                    if sv.get("variant_id") == variant_id:
                        target_regime = sv.get("regime_target", "mixed")
                        regime_match = 1.2 if target_regime == predicted_regime else 0.8
                        break
            
            # Calculate composite sentiment score
            # Score = (ROI × 50) + (WR × 30) + (Momentum × 100) × Regime_Match
            sentiment_score = (
                (avg_roi * 50) +
                (avg_wr * 30) +
                (momentum * 100)
            ) * regime_match
            
            # Classify sentiment
            if sentiment_score > 1.0:
                sentiment = "bullish"
            elif sentiment_score < -0.5:
                sentiment = "bearish"
            else:
                sentiment = "neutral"
            
            sentiment_scores[variant_id] = {
                "strategy": base_strategy,
                "variant": variant_id,
                "score": round(sentiment_score, 3),
                "sentiment": sentiment,
                "momentum": round(momentum, 4),
                "regime_match": regime_match,
                "avg_roi": round(avg_roi, 4),
                "avg_wr": round(avg_wr, 3)
            }
    
    _write_json(SENTIMENT_LOG, sentiment_scores)
    return sentiment_scores

# ---- Phase 65.0 – Operator Copilot Alert System ----
def run_operator_alerts():
    """
    Operator copilot alert system - generates actionable alerts:
    - Heatmap drift alerts (ROI < -0.5%)
    - Regime shift notifications
    - Tournament results (promotions/retirements)
    - Performance degradation warnings
    """
    heatmap = _read_json(HEATMAP_LOG, {})
    transitions = _read_json(TRANSITION_LOG, {}).get("transitions", [])
    tournament = _read_json(TOURNAMENT_LOG, {}).get("results", [])
    sentiment = _read_json(SENTIMENT_LOG, {})
    
    alerts = []
    
    # Heatmap drift alerts
    for key, data in heatmap.items():
        if data.get("avg_roi", 0) < -0.005:
            alerts.append({
                "type": "heatmap_drift",
                "severity": "high",
                "key": key,
                "symbol": data.get("symbol"),
                "regime": data.get("regime"),
                "avg_roi": data.get("avg_roi"),
                "message": f"Negative performance in {key}: {data.get('avg_roi', 0):.2%}"
            })
    
    # Regime shift alerts
    if transitions:
        last_transition = transitions[-1]
        alerts.append({
            "type": "regime_shift",
            "severity": "medium",
            "from": last_transition.get("from"),
            "to": last_transition.get("to"),
            "volatility": last_transition.get("volatility"),
            "message": f"Regime shifted from {last_transition.get('from')} to {last_transition.get('to')}"
        })
    
    # Tournament alerts
    if tournament:
        # Promote top performers
        for result in tournament[:3]:
            if result.get("tournament_score", 0) > 1.0:
                alerts.append({
                    "type": "tournament_promote",
                    "severity": "low",
                    "variant": result.get("variant"),
                    "score": result.get("tournament_score"),
                    "message": f"Top performer: {result.get('variant')} (score: {result.get('tournament_score', 0):.2f})"
                })
        
        # Retire poor performers
        for result in tournament[-3:]:
            if result.get("tournament_score", 0) < -1.0:
                alerts.append({
                    "type": "tournament_retire",
                    "severity": "medium",
                    "variant": result.get("variant"),
                    "score": result.get("tournament_score"),
                    "message": f"Poor performer: {result.get('variant')} (score: {result.get('tournament_score', 0):.2f})"
                })
    
    # Sentiment alerts
    bearish_count = sum(1 for s in sentiment.values() if s.get("sentiment") == "bearish")
    if bearish_count > len(sentiment) * 0.5:
        alerts.append({
            "type": "sentiment_warning",
            "severity": "high",
            "bearish_count": bearish_count,
            "total_strategies": len(sentiment),
            "message": f"High bearish sentiment: {bearish_count}/{len(sentiment)} strategies bearish"
        })
    
    # Log all alerts
    for alert in alerts:
        _append_event(ALERT_LOG, "copilot_alert", alert)
    
    return alerts

# ---- Unified Runner ----
def run_phase_61_65():
    """
    Execute all five phases:
    - Strategy tournament ranking
    - Attribution heatmap generation
    - Regime transition tracking
    - Strategy sentiment synthesis
    - Operator alert generation
    """
    tournament = run_strategy_tournament()
    heatmap = generate_attribution_heatmap()
    transitions = track_regime_transitions()
    sentiment = synthesize_strategy_sentiment()
    alerts = run_operator_alerts()
    
    return {
        "tournament": tournament,
        "heatmap": heatmap,
        "transitions": transitions,
        "sentiment": sentiment,
        "alerts": alerts
    }

if __name__ == "__main__":
    result = run_phase_61_65()
    print(f"Phase 61: {len(result['tournament'])} variants ranked in tournament")
    print(f"Phase 62: {len(result['heatmap'])} heatmap cells generated")
    print(f"Phase 63: {len(result['transitions'].get('transitions', []))} regime transitions tracked")
    print(f"Phase 64: {len(result['sentiment'])} sentiment scores calculated")
    print(f"Phase 65: {len(result['alerts'])} alerts generated")
