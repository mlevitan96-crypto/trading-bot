# src/phase_71_75.py
#
# Phases 71–75: Archetype Evolution, Exit Designer, Timeline Tracker,
#              Anomaly Detector, Strategic Curiosity Engine

import os
import json
import time
from statistics import mean, stdev
from typing import Dict, List, Any

# Paths
LINEAGE_LOG = "config/strategy_lineage.json"
SHADOW_STATE = "config/shadow_strategy_state.json"
EXIT_PROFILES = "config/exit_profiles.json"
TRADE_OUTCOMES = "logs/trade_outcomes.jsonl"
STRATEGIC_ATTRIBUTION = "logs/strategic_attribution.jsonl"
DASHBOARD_LOG = "logs/operator_dashboard.json"
ARCHETYPE_LOG = "logs/strategy_archetypes.json"
REGIME_FORECAST = "logs/regime_forecast.json"

EVOLUTION_LOG = "logs/archetype_evolution_events.jsonl"
EXIT_DESIGNER_LOG = "logs/regime_exit_designs.json"
TIMELINE_LOG = "logs/operator_timeline.json"
ANOMALY_LOG = "logs/attribution_anomalies.json"
CURIOSITY_LOG = "logs/curiosity_events.jsonl"

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

# ---- Phase 71.0 – Archetype Evolution Engine ----
def evolve_archetypes():
    """
    Archetype evolution engine - evolves successful archetypes:
    - Identifies high-performing archetypes
    - Creates evolved variants with optimized parameters
    - Maintains genetic lineage
    - Tests parameter improvements
    """
    archetypes = _read_json(ARCHETYPE_LOG, {})
    lineage = _read_json(LINEAGE_LOG, {})
    shadow_state = _read_json(SHADOW_STATE, {})
    
    evolved_variants = []
    
    # Group by archetype
    by_archetype = {}
    for variant_id, arch_data in archetypes.items():
        archetype = arch_data.get("archetype", "unknown")
        perf_score = arch_data.get("performance_score", 0)
        
        if archetype not in by_archetype:
            by_archetype[archetype] = []
        by_archetype[archetype].append({
            "variant_id": variant_id,
            "performance_score": perf_score,
            "data": arch_data
        })
    
    # Evolve top performers in each archetype
    for archetype, variants in by_archetype.items():
        if archetype == "unknown":
            continue
        
        # Sort by performance
        variants.sort(key=lambda x: x["performance_score"], reverse=True)
        
        # Evolve top performer
        if variants and variants[0]["performance_score"] > 0.003:
            best = variants[0]
            variant_id = best["variant_id"]
            
            # Get variant configuration
            variant_config = None
            for shadow_base, shadow_variants in shadow_state.items():
                for sv in shadow_variants:
                    if sv.get("variant_id") == variant_id:
                        variant_config = sv
                        break
            
            if not variant_config:
                continue
            
            # Create evolved variant with parameter improvements
            evolved_id = f"{variant_id}_evo_{int(time.time() % 100000)}"
            
            # Evolve parameters based on archetype
            evolved_filters = dict(variant_config.get("filters", {}))
            
            if archetype == "mean_reversion" and "RSI" in evolved_filters:
                evolved_filters["RSI"] = max(20, evolved_filters["RSI"] - 5)  # More aggressive
            elif archetype == "momentum" and "volume_min" in evolved_filters:
                evolved_filters["volume_min"] = int(evolved_filters["volume_min"] * 1.2)  # Higher volume
            elif archetype == "scalper":
                # Tighter parameters for scalping
                evolved_filters["min_profit_bps"] = evolved_filters.get("min_profit_bps", 10) + 5
            
            # Evolve timeframe
            current_tf = variant_config.get("timeframe", "5m")
            tf_evolution = {
                "1m": "3m",
                "3m": "5m",
                "5m": "3m",  # Test faster
                "15m": "5m"
            }
            evolved_timeframe = tf_evolution.get(current_tf, current_tf)
            
            evolved_variant = {
                "evolved_id": evolved_id,
                "parent_variant": variant_id,
                "archetype": archetype,
                "base_strategy": variant_config.get("base_strategy", ""),
                "evolved_filters": evolved_filters,
                "evolved_timeframe": evolved_timeframe,
                "exit_profile_id": variant_config.get("exit_profile_id", ""),
                "parent_performance": best["performance_score"],
                "created": int(time.time())
            }
            
            evolved_variants.append(evolved_variant)
            _append_event(EVOLUTION_LOG, "archetype_evolved", evolved_variant)
    
    return evolved_variants

# ---- Phase 72.0 – Regime-Adaptive Exit Designer ----
def design_regime_exits():
    """
    Regime-adaptive exit designer - designs optimal exits per regime:
    - Analyzes historical exits by regime
    - Designs regime-specific exit parameters
    - Optimizes TP levels, trailing stops, time exits
    - Creates adaptive exit profiles
    """
    trade_outcomes = _read_jsonl(TRADE_OUTCOMES)
    exit_profiles = _read_json(EXIT_PROFILES, {})
    
    # Group trades by regime
    by_regime = {"choppy": [], "trending": [], "volatile": [], "mixed": []}
    
    for trade in trade_outcomes:
        regime = trade.get("regime", "mixed")
        roi = trade.get("net_roi", 0.0)
        exit_type = trade.get("exit_type", "unknown")
        
        if regime in by_regime:
            by_regime[regime].append({"roi": roi, "exit_type": exit_type})
    
    # Design exits for each regime
    regime_designs = {}
    
    for regime, trades in by_regime.items():
        if len(trades) < 5:
            continue
        
        # Analyze successful exits
        profitable_trades = [t for t in trades if t["roi"] > 0]
        
        if not profitable_trades:
            continue
        
        roi_values = [t["roi"] for t in profitable_trades]
        avg_roi = mean(roi_values)
        roi_std = stdev(roi_values) if len(roi_values) > 1 else 0
        
        # Design regime-specific parameters
        if regime == "choppy":
            # Tight exits for choppy markets
            tp1_roi = avg_roi * 0.4  # Take profit earlier
            tp2_roi = avg_roi * 0.7
            trail_atr = 1.5  # Tight trailing
            time_stop = 120  # Shorter hold time
        elif regime == "trending":
            # Let winners run in trends
            tp1_roi = avg_roi * 0.3
            tp2_roi = avg_roi * 1.2  # Let it run
            trail_atr = 2.0  # Wider trailing
            time_stop = 300  # Longer hold time
        elif regime == "volatile":
            # Quick exits in volatility
            tp1_roi = avg_roi * 0.5
            tp2_roi = avg_roi * 0.8
            trail_atr = 1.8
            time_stop = 90
        else:  # mixed
            tp1_roi = avg_roi * 0.4
            tp2_roi = avg_roi * 0.9
            trail_atr = 1.7
            time_stop = 180
        
        regime_designs[regime] = {
            "TP1_ROI": round(tp1_roi, 4),
            "TP2_ROI": round(tp2_roi, 4),
            "trail_ATR_multiplier": round(trail_atr, 2),
            "time_stop_seconds": time_stop,
            "based_on_trades": len(trades),
            "avg_roi": round(avg_roi, 4),
            "win_rate": round(len(profitable_trades) / len(trades), 3)
        }
    
    _write_json(EXIT_DESIGNER_LOG, regime_designs)
    return regime_designs

# ---- Phase 73.0 – Operator Timeline Tracker ----
def track_operator_timeline():
    """
    Operator timeline tracker - maintains operational timeline:
    - Records strategy state changes over time
    - Tracks trend evolution
    - Monitors quality metrics progression
    - Provides historical context
    """
    dashboard = _read_json(DASHBOARD_LOG, {})
    
    timeline_entries = []
    
    # Build timeline from dashboard data
    for variant_id, data in dashboard.get("strategies", {}).items():
        entry = {
            "timestamp": int(time.time()),
            "variant": variant_id,
            "base_strategy": data.get("base", ""),
            "trend": data.get("trend", "unknown"),
            "clarity": data.get("clarity", 0),
            "consistency": data.get("consistency", 0),
            "quality_score": data.get("quality_score", 0),
            "status": data.get("status", "active")
        }
        timeline_entries.append(entry)
    
    # Add system health snapshot
    system_health = dashboard.get("system_health", {})
    if system_health:
        timeline_entries.append({
            "timestamp": int(time.time()),
            "type": "system_snapshot",
            "total_strategies": system_health.get("total_strategies", 0),
            "improving": system_health.get("improving", 0),
            "declining": system_health.get("declining", 0),
            "system_quality": system_health.get("system_quality", 0)
        })
    
    _write_json(TIMELINE_LOG, {"entries": timeline_entries, "last_updated": int(time.time())})
    return timeline_entries

# ---- Phase 74.0 – Attribution Anomaly Detector ----
def detect_attribution_anomalies():
    """
    Attribution anomaly detector - identifies unusual patterns:
    - Detects extreme ROI outliers (> 5% or < -5%)
    - Flags zero-ROI trades (potential issues)
    - Identifies exit type anomalies
    - Highlights statistical outliers
    """
    trade_outcomes = _read_jsonl(TRADE_OUTCOMES)
    
    anomalies = []
    
    if not trade_outcomes:
        _write_json(ANOMALY_LOG, {"anomalies": [], "count": 0})
        return anomalies
    
    # Calculate baseline statistics
    roi_values = [t.get("net_roi", 0.0) for t in trade_outcomes]
    if len(roi_values) > 1:
        avg_roi = mean(roi_values)
        roi_std = stdev(roi_values)
        
        # Define anomaly thresholds (3 standard deviations)
        upper_threshold = avg_roi + (3 * roi_std)
        lower_threshold = avg_roi - (3 * roi_std)
    else:
        upper_threshold = 0.05
        lower_threshold = -0.05
    
    # Detect anomalies
    for trade in trade_outcomes:
        roi = trade.get("net_roi", 0.0)
        strategy = trade.get("strategy", "")
        symbol = trade.get("symbol", "")
        exit_type = trade.get("exit_type", "")
        
        anomaly_detected = False
        anomaly_reasons = []
        
        # Extreme ROI outlier
        if roi > upper_threshold:
            anomaly_detected = True
            anomaly_reasons.append(f"extreme_positive_roi_{roi:.2%}")
        elif roi < lower_threshold:
            anomaly_detected = True
            anomaly_reasons.append(f"extreme_negative_roi_{roi:.2%}")
        
        # Zero ROI (potential issue)
        if roi == 0.0:
            anomaly_detected = True
            anomaly_reasons.append("zero_roi")
        
        # Unknown exit type
        if exit_type in ["unknown", "", None]:
            anomaly_detected = True
            anomaly_reasons.append("unknown_exit_type")
        
        if anomaly_detected:
            anomalies.append({
                "strategy": strategy,
                "symbol": symbol,
                "roi": round(roi, 4),
                "exit_type": exit_type,
                "anomaly_reasons": anomaly_reasons,
                "timestamp": trade.get("timestamp", int(time.time()))
            })
    
    _write_json(ANOMALY_LOG, {
        "anomalies": anomalies,
        "count": len(anomalies),
        "last_check": int(time.time()),
        "thresholds": {
            "upper": round(upper_threshold, 4),
            "lower": round(lower_threshold, 4)
        }
    })
    
    return anomalies

# ---- Phase 75.0 – Strategic Curiosity Engine ----
def run_curiosity_engine():
    """
    Strategic curiosity engine - generates research questions:
    - Analyzes gaps in current strategies
    - Proposes novel parameter combinations
    - Suggests unexplored approaches
    - Generates hypothesis for testing
    """
    archetypes = _read_json(ARCHETYPE_LOG, {})
    trade_outcomes = _read_jsonl(TRADE_OUTCOMES)
    regime_forecast = _read_json(REGIME_FORECAST, {})
    
    curiosity_ideas = []
    
    # Analyze archetype coverage
    archetype_counts = {}
    for variant_id, data in archetypes.items():
        archetype = data.get("archetype", "unknown")
        archetype_counts[archetype] = archetype_counts.get(archetype, 0) + 1
    
    # Suggest underrepresented archetypes
    all_archetypes = ["breakout", "mean_reversion", "momentum", "scalper", "trend_follower", "conservative", "sentiment_driven"]
    for arch in all_archetypes:
        if archetype_counts.get(arch, 0) < 2:
            curiosity_ideas.append({
                "type": "archetype_gap",
                "prompt": f"What if we develop more {arch} strategies?",
                "tags": [arch, "coverage", "diversification"],
                "priority": "high"
            })
    
    # Analyze exit type performance
    if trade_outcomes:
        exit_types = {}
        for trade in trade_outcomes:
            exit_type = trade.get("exit_type", "unknown")
            roi = trade.get("net_roi", 0.0)
            if exit_type not in exit_types:
                exit_types[exit_type] = []
            exit_types[exit_type].append(roi)
        
        # Suggest improvements for underperforming exits
        for exit_type, roi_values in exit_types.items():
            if len(roi_values) >= 5:
                avg_roi = mean(roi_values)
                if avg_roi < 0:
                    curiosity_ideas.append({
                        "type": "exit_optimization",
                        "prompt": f"Can we improve {exit_type} exits? Current avg ROI: {avg_roi:.2%}",
                        "tags": [exit_type, "exit_optimization", "negative_roi"],
                        "priority": "high"
                    })
    
    # Regime-based curiosity
    current_regime = regime_forecast.get("predicted_regime", "unknown")
    if current_regime != "unknown":
        curiosity_ideas.append({
            "type": "regime_opportunity",
            "prompt": f"What untested strategies work best in {current_regime} regime?",
            "tags": [current_regime, "regime_specific", "opportunity"],
            "priority": "medium"
        })
    
    # General research questions
    curiosity_ideas.extend([
        {
            "type": "parameter_combination",
            "prompt": "What if we combine RSI < 30 with volume spike > 2x average?",
            "tags": ["RSI", "volume", "reversal", "combination"],
            "priority": "medium"
        },
        {
            "type": "time_decay",
            "prompt": "Can we evolve exits based on time-of-day patterns?",
            "tags": ["exit", "time_decay", "temporal"],
            "priority": "low"
        },
        {
            "type": "rotation_strategy",
            "prompt": "What happens if we rotate symbols based on correlation changes?",
            "tags": ["rotation", "correlation", "dynamic"],
            "priority": "medium"
        }
    ])
    
    # Log all ideas
    for idea in curiosity_ideas:
        _append_event(CURIOSITY_LOG, "curiosity_idea", idea)
    
    return curiosity_ideas

# ---- Unified Runner ----
def run_phase_71_75():
    """
    Execute all five phases:
    - Archetype evolution
    - Exit design
    - Timeline tracking
    - Anomaly detection
    - Curiosity engine
    """
    evolved = evolve_archetypes()
    exits = design_regime_exits()
    timeline = track_operator_timeline()
    anomalies = detect_attribution_anomalies()
    curiosity = run_curiosity_engine()
    
    return {
        "evolved": evolved,
        "exits": exits,
        "timeline": timeline,
        "anomalies": anomalies,
        "curiosity": curiosity
    }

if __name__ == "__main__":
    result = run_phase_71_75()
    print(f"Phase 71: {len(result['evolved'])} archetypes evolved")
    print(f"Phase 72: {len(result['exits'])} regime exit designs")
    print(f"Phase 73: {len(result['timeline'])} timeline entries")
    print(f"Phase 74: {len(result['anomalies'])} anomalies detected")
    print(f"Phase 75: {len(result['curiosity'])} curiosity ideas generated")
