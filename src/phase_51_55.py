# src/phase_51_55.py
#
# Phases 51–55: Meta-Learning, Attribution Quality, Genome Mapping, 
#              Operator Dashboard, Final Audit

import os
import json
import time
from statistics import mean, stdev
from typing import Dict, List, Any

# Paths
STRATEGIC_ATTRIBUTION = "logs/strategic_attribution.jsonl"
TRADE_OUTCOMES = "logs/trade_outcomes.jsonl"
LINEAGE_LOG = "config/strategy_lineage.json"
SHADOW_STATE = "config/shadow_strategy_state.json"
EXIT_PROFILES = "config/exit_profiles.json"
STRATEGY_PROFILES = "logs/strategy_profiles.json"
EXPECTANCY_LOG = "logs/expectancy_scores.json"
SENTIMENT_LOG = "logs/symbol_sentiment.json"
META_LEARNING_LOG = "logs/meta_learning_report.json"
ATTRIBUTION_QUALITY_LOG = "logs/attribution_quality.json"
GENOME_LOG = "logs/strategy_genome.json"
DASHBOARD_LOG = "logs/operator_dashboard.json"
AUDIT_LOG = "logs/final_audit_report.json"

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

# ---- Phase 51.0 – Meta-Learning Engine ----
def run_meta_learning():
    """
    Analyze performance trends across all variants:
    - Calculate ROI slope (improving/declining/flat)
    - Identify learning patterns
    - Flag accelerating or decelerating strategies
    """
    lineage = _read_json(LINEAGE_LOG, {})
    
    meta = {}
    
    for base_strategy, variants in lineage.items():
        for variant_id, data in variants.items():
            perf_history = data.get("performance_history", [])
            
            if len(perf_history) < 10:
                continue  # Need sufficient history for trend analysis
            
            # Extract ROI values over time
            roi_values = [p.get("avg_roi", 0.0) for p in perf_history]
            
            # Calculate trend slope
            n = len(roi_values)
            x_mean = (n - 1) / 2
            y_mean = mean(roi_values)
            
            numerator = sum((i - x_mean) * (roi_values[i] - y_mean) for i in range(n))
            denominator = sum((i - x_mean) ** 2 for i in range(n))
            
            slope = numerator / denominator if denominator != 0 else 0
            
            # Classify trend
            if slope > 0.0001:
                trend = "improving"
            elif slope < -0.0001:
                trend = "declining"
            else:
                trend = "flat"
            
            # Calculate acceleration (second derivative)
            if len(roi_values) >= 5:
                recent_slope = (roi_values[-1] - roi_values[-3]) / 2
                early_slope = (roi_values[2] - roi_values[0]) / 2
                acceleration = recent_slope - early_slope
            else:
                acceleration = 0
            
            meta[variant_id] = {
                "strategy": base_strategy,
                "trend": trend,
                "slope": round(slope, 6),
                "acceleration": round(acceleration, 6),
                "current_roi": round(roi_values[-1], 4),
                "snapshots": len(perf_history)
            }
    
    _write_json(META_LEARNING_LOG, meta)
    return meta

# ---- Phase 52.0 – Attribution Quality ----
def score_attribution_quality():
    """
    Score attribution quality for each strategy:
    - Signal clarity: How often exits are well-defined vs unknown
    - Exit consistency: Variance in ROI outcomes
    - Regime alignment: Performance consistency within regime
    """
    trade_outcomes = _read_jsonl(TRADE_OUTCOMES)
    
    quality = {}
    
    # Group trades by strategy
    by_strategy = {}
    for trade in trade_outcomes:
        strategy = trade.get("strategy", "")
        if not strategy:
            continue
        
        if strategy not in by_strategy:
            by_strategy[strategy] = {
                "roi": [],
                "exit_types": [],
                "regimes": []
            }
        
        by_strategy[strategy]["roi"].append(trade.get("net_roi", 0.0))
        by_strategy[strategy]["exit_types"].append(trade.get("exit_type", "unknown"))
        by_strategy[strategy]["regimes"].append(trade.get("regime", "unknown"))
    
    # Calculate quality scores
    for strategy, data in by_strategy.items():
        if len(data["roi"]) < 5:
            continue  # Need minimum data
        
        # Signal clarity: percentage of non-unknown exits
        unknown_count = data["exit_types"].count("unknown")
        signal_clarity = 1.0 - (unknown_count / len(data["exit_types"]))
        
        # Exit consistency: inverse of ROI standard deviation
        roi_std = stdev(data["roi"]) if len(data["roi"]) > 1 else 0
        exit_consistency = 1.0 / (1.0 + roi_std) if roi_std > 0 else 1.0
        
        # Regime alignment: count of most common regime
        regime_counts = {}
        for r in data["regimes"]:
            regime_counts[r] = regime_counts.get(r, 0) + 1
        
        most_common_regime = max(regime_counts.keys(), key=lambda k: regime_counts[k]) if regime_counts else "unknown"
        regime_alignment = regime_counts.get(most_common_regime, 0) / len(data["regimes"])
        
        quality[strategy] = {
            "signal_clarity": round(signal_clarity, 3),
            "exit_consistency": round(exit_consistency, 3),
            "regime_alignment": most_common_regime,
            "regime_consistency": round(regime_alignment, 3),
            "total_trades": len(data["roi"]),
            "quality_score": round((signal_clarity + exit_consistency + regime_alignment) / 3, 3)
        }
    
    _write_json(ATTRIBUTION_QUALITY_LOG, quality)
    return quality

# ---- Phase 53.0 – Strategy Genome Mapper ----
def map_strategy_genomes():
    """
    Map complete genetic profile of each strategy:
    - Filters configuration
    - Exit profile assignment
    - Timeframe preference
    - Regime targeting
    - Performance DNA
    """
    shadow_state = _read_json(SHADOW_STATE, {})
    exit_profiles = _read_json(EXIT_PROFILES, {})
    lineage = _read_json(LINEAGE_LOG, {})
    
    genome = {}
    
    for base_strategy, variants in shadow_state.items():
        for variant in variants:
            variant_id = variant.get("variant_id", "")
            
            # Extract configuration genome
            genome[variant_id] = {
                "base_strategy": base_strategy,
                "filters": variant.get("filters", {}),
                "exit_profile_id": variant.get("exit_profile_id", "unknown"),
                "timeframe": variant.get("timeframe", "5m"),
                "regime_target": variant.get("regime_target", "mixed"),
                "status": variant.get("status", "active"),
                "created": variant.get("created", 0)
            }
            
            # Add performance genome from lineage
            if base_strategy in lineage and variant_id in lineage[base_strategy]:
                lineage_data = lineage[base_strategy][variant_id]
                perf_history = lineage_data.get("performance_history", [])
                
                if perf_history:
                    recent_perf = perf_history[-5:] if len(perf_history) >= 5 else perf_history
                    genome[variant_id]["performance_dna"] = {
                        "avg_roi": round(mean([p.get("avg_roi", 0.0) for p in recent_perf]), 4),
                        "avg_win_rate": round(mean([p.get("win_rate", 0.0) for p in recent_perf]), 3),
                        "snapshots": len(perf_history),
                        "status": lineage_data.get("status", "active")
                    }
    
    _write_json(GENOME_LOG, genome)
    return genome

# ---- Phase 54.0 – Operator Intelligence Dashboard ----
def build_operator_dashboard():
    """
    Build comprehensive operator dashboard:
    - Strategy-level insights from all phases
    - Performance trends and quality scores
    - Regime alignment and exit effectiveness
    - Actionable recommendations
    """
    meta = _read_json(META_LEARNING_LOG, {})
    quality = _read_json(ATTRIBUTION_QUALITY_LOG, {})
    genome = _read_json(GENOME_LOG, {})
    expectancy = _read_json(EXPECTANCY_LOG, {})
    sentiment = _read_json(SENTIMENT_LOG, {})
    
    dashboard = {
        "timestamp": int(time.time()),
        "strategies": {},
        "symbols": {},
        "system_health": {}
    }
    
    # Build strategy-level dashboard
    for variant_id, genome_data in genome.items():
        strategy_name = genome_data.get("base_strategy", "unknown")
        
        dashboard["strategies"][variant_id] = {
            "base": strategy_name,
            "regime_target": genome_data.get("regime_target", "unknown"),
            "exit_profile": genome_data.get("exit_profile_id", "unknown"),
            "timeframe": genome_data.get("timeframe", "5m"),
            "trend": meta.get(variant_id, {}).get("trend", "unknown"),
            "slope": meta.get(variant_id, {}).get("slope", 0),
            "clarity": quality.get(variant_id, {}).get("signal_clarity", 0),
            "consistency": quality.get(variant_id, {}).get("exit_consistency", 0),
            "quality_score": quality.get(variant_id, {}).get("quality_score", 0),
            "status": genome_data.get("status", "active")
        }
    
    # Build symbol-level dashboard
    for symbol, sent_data in sentiment.items():
        dashboard["symbols"][symbol] = {
            "polarity": sent_data.get("polarity", 0),
            "volatility_risk": sent_data.get("volatility_risk", 0),
            "recommendation": sent_data.get("recommendation", "neutral"),
            "win_rate": sent_data.get("win_rate", 0),
            "avg_roi": sent_data.get("avg_roi", 0)
        }
    
    # Calculate system health metrics
    total_strategies = len(genome)
    improving = sum(1 for v in meta.values() if v.get("trend") == "improving")
    declining = sum(1 for v in meta.values() if v.get("trend") == "declining")
    high_quality = sum(1 for v in quality.values() if v.get("quality_score", 0) > 0.7)
    
    dashboard["system_health"] = {
        "total_strategies": total_strategies,
        "improving": improving,
        "declining": declining,
        "flat": total_strategies - improving - declining,
        "high_quality_count": high_quality,
        "system_quality": round(high_quality / total_strategies, 2) if total_strategies > 0 else 0
    }
    
    _write_json(DASHBOARD_LOG, dashboard)
    return dashboard

# ---- Phase 55.0 – Final Audit Layer ----
def run_final_audit():
    """
    Comprehensive system audit:
    - Verify all critical files exist
    - Check for empty or corrupted data
    - Validate data integrity
    - Generate audit report
    """
    critical_files = [
        STRATEGIC_ATTRIBUTION,
        TRADE_OUTCOMES,
        LINEAGE_LOG,
        SHADOW_STATE,
        EXIT_PROFILES,
        STRATEGY_PROFILES,
        EXPECTANCY_LOG,
        META_LEARNING_LOG,
        ATTRIBUTION_QUALITY_LOG,
        GENOME_LOG,
        DASHBOARD_LOG
    ]
    
    audit = {
        "timestamp": int(time.time()),
        "missing": [],
        "empty": [],
        "valid": [],
        "warnings": []
    }
    
    for file_path in critical_files:
        if not os.path.exists(file_path):
            audit["missing"].append(file_path)
        elif os.path.getsize(file_path) < 10:
            audit["empty"].append(file_path)
        else:
            audit["valid"].append(file_path)
            
            # Additional validation for JSON files
            try:
                if file_path.endswith('.json'):
                    data = _read_json(file_path, None)
                    if data is None or (isinstance(data, dict) and len(data) == 0):
                        audit["warnings"].append(f"{file_path}: Empty JSON object")
                elif file_path.endswith('.jsonl'):
                    data = _read_jsonl(file_path)
                    if len(data) == 0:
                        audit["warnings"].append(f"{file_path}: No events logged")
            except Exception as e:
                audit["warnings"].append(f"{file_path}: {str(e)}")
    
    # System health check
    audit["health_status"] = "healthy" if len(audit["missing"]) == 0 and len(audit["empty"]) == 0 else "degraded"
    audit["files_checked"] = len(critical_files)
    audit["files_valid"] = len(audit["valid"])
    
    _write_json(AUDIT_LOG, audit)
    return audit

# ---- Unified Runner ----
def run_phase_51_55():
    """
    Execute all five phases:
    - Meta-learning trend analysis
    - Attribution quality scoring
    - Strategy genome mapping
    - Operator dashboard generation
    - Final system audit
    """
    meta = run_meta_learning()
    quality = score_attribution_quality()
    genome = map_strategy_genomes()
    dashboard = build_operator_dashboard()
    audit = run_final_audit()
    
    return {
        "meta_learning": meta,
        "attribution_quality": quality,
        "genome": genome,
        "dashboard": dashboard,
        "audit": audit
    }

if __name__ == "__main__":
    result = run_phase_51_55()
    print(f"Phase 51: {len(result['meta_learning'])} variants analyzed for trends")
    print(f"Phase 52: {len(result['attribution_quality'])} strategies scored")
    print(f"Phase 53: {len(result['genome'])} strategy genomes mapped")
    print(f"Phase 54: Dashboard built with {result['dashboard']['system_health']['total_strategies']} strategies")
    print(f"Phase 55: Audit complete - {result['audit']['health_status']}")
