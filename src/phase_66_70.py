# src/phase_66_70.py
#
# Phases 66–70: Archetype Classifier, Decay Monitor, Symbol Rotation,
#              Operator Planner, Strategic Memory Consolidator

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
SIZING_STATE = "config/sizing_state.json"
SENTIMENT_LOG = "logs/strategy_sentiment_scores.json"
EXPECTANCY_LOG = "logs/expectancy_scores.json"
META_LEARNING_LOG = "logs/meta_learning_report.json"

ARCHETYPE_LOG = "logs/strategy_archetypes.json"
DECAY_LOG = "logs/attribution_decay.json"
ROTATION_LOG = "logs/symbol_rotation_events.jsonl"
PLAN_LOG = "logs/operator_plan.json"
ARCHIVE_LOG = "logs/strategic_memory_archive.json"

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

# ---- Phase 66.0 – Strategy Archetype Classifier ----
def classify_archetypes():
    """
    Strategy archetype classifier - categorizes strategies by type:
    - Breakout, mean-reversion, momentum, scalper, trend-follower
    - Based on filters, timeframes, exit profiles
    - Enables archetype-specific optimization
    """
    shadow_state = _read_json(SHADOW_STATE, {})
    lineage = _read_json(LINEAGE_LOG, {})
    
    archetypes = {}
    
    for base_strategy, variants in shadow_state.items():
        for variant in variants:
            variant_id = variant.get("variant_id", "")
            filters = variant.get("filters", {})
            timeframe = variant.get("timeframe", "5m")
            exit_profile_id = variant.get("exit_profile_id", "")
            regime_target = variant.get("regime_target", "mixed")
            
            # Classify archetype based on characteristics
            archetype = "unknown"
            
            # Breakout strategies
            if "breakout" in base_strategy.lower() or "ATR" in exit_profile_id:
                archetype = "breakout"
            # Mean reversion strategies
            elif "RSI" in str(filters) or filters.get("RSI"):
                archetype = "mean_reversion"
            # Momentum strategies
            elif "volume" in str(filters) or filters.get("volume_min"):
                archetype = "momentum"
            # Scalper strategies (short timeframes)
            elif timeframe in ["1m", "3m"]:
                archetype = "scalper"
            # Trend follower strategies
            elif "trend" in base_strategy.lower() or "trend" in exit_profile_id.lower():
                archetype = "trend_follower"
            # Conservative strategies
            elif "conservative" in base_strategy.lower() or "conservative" in exit_profile_id.lower():
                archetype = "conservative"
            # Sentiment-based strategies
            elif "sentiment" in base_strategy.lower():
                archetype = "sentiment_driven"
            
            # Get performance data
            performance_score = 0
            if base_strategy in lineage and variant_id in lineage[base_strategy]:
                perf_history = lineage[base_strategy][variant_id].get("performance_history", [])
                if perf_history:
                    recent_roi = mean([p.get("avg_roi", 0.0) for p in perf_history[-5:]])
                    performance_score = recent_roi
            
            archetypes[variant_id] = {
                "strategy": base_strategy,
                "variant": variant_id,
                "archetype": archetype,
                "timeframe": timeframe,
                "regime_target": regime_target,
                "performance_score": round(performance_score, 4),
                "filters": filters
            }
    
    _write_json(ARCHETYPE_LOG, archetypes)
    return archetypes

# ---- Phase 67.0 – Attribution Decay Monitor ----
def monitor_attribution_decay():
    """
    Attribution decay monitor - tracks performance degradation:
    - ROI trend analysis (recent vs historical)
    - Signal clarity decay detection
    - Early warning for strategy degradation
    """
    trade_outcomes = _read_jsonl(TRADE_OUTCOMES)
    
    decay_analysis = {}
    
    # Group trades by strategy
    by_strategy = {}
    for trade in trade_outcomes:
        strategy = trade.get("strategy", "")
        if not strategy:
            continue
        
        if strategy not in by_strategy:
            by_strategy[strategy] = []
        by_strategy[strategy].append(trade)
    
    # Analyze decay for each strategy
    for strategy, trades in by_strategy.items():
        if len(trades) < 10:
            continue  # Need sufficient history
        
        # Sort by timestamp if available
        trades_sorted = sorted(trades, key=lambda x: x.get("timestamp", 0))
        
        # Extract ROI sequence
        roi_sequence = [t.get("net_roi", 0.0) for t in trades_sorted]
        
        # Calculate trend (recent vs historical)
        recent_roi = mean(roi_sequence[-5:]) if len(roi_sequence) >= 5 else mean(roi_sequence)
        historical_roi = mean(roi_sequence[:-5]) if len(roi_sequence) > 5 else recent_roi
        roi_trend = recent_roi - historical_roi
        
        # Signal clarity analysis
        clarity_sequence = [
            1 if t.get("exit_type") not in ["unknown", None, ""] else 0
            for t in trades_sorted
        ]
        signal_clarity = mean(clarity_sequence) if clarity_sequence else 0
        
        # Recent clarity vs historical
        recent_clarity = mean(clarity_sequence[-5:]) if len(clarity_sequence) >= 5 else signal_clarity
        historical_clarity = mean(clarity_sequence[:-5]) if len(clarity_sequence) > 5 else signal_clarity
        clarity_decay = recent_clarity - historical_clarity
        
        # Classify decay status
        if roi_trend < -0.002 or clarity_decay < -0.2:
            decay_status = "degrading"
        elif roi_trend > 0.002 and clarity_decay > -0.1:
            decay_status = "improving"
        else:
            decay_status = "stable"
        
        decay_analysis[strategy] = {
            "roi_trend": round(roi_trend, 5),
            "signal_clarity": round(signal_clarity, 3),
            "clarity_decay": round(clarity_decay, 3),
            "recent_roi": round(recent_roi, 4),
            "historical_roi": round(historical_roi, 4),
            "decay_status": decay_status,
            "trade_count": len(trades)
        }
    
    _write_json(DECAY_LOG, decay_analysis)
    return decay_analysis

# ---- Phase 68.0 – Symbol Rotation Engine ----
def rotate_symbols():
    """
    Symbol rotation engine - reallocates capital from underperformers:
    - Rotates away from low-sentiment symbols
    - Reallocates to high-expectancy symbols
    - Maintains diversification
    """
    sizing = _read_json(SIZING_STATE, {})
    sentiment = _read_json(SENTIMENT_LOG, {})
    expectancy = _read_json(EXPECTANCY_LOG, {})
    
    rotations = []
    
    # Calculate symbol scores from strategy performance
    symbol_scores = {}
    for key, exp_data in expectancy.items():
        parts = key.split("_")
        if len(parts) >= 2:
            symbol = parts[-1]  # Last part is usually symbol
            if symbol not in symbol_scores:
                symbol_scores[symbol] = []
            symbol_scores[symbol].append(exp_data.get("expectancy", 0))
    
    # Average expectancy per symbol
    symbol_avg_expectancy = {
        sym: mean(scores) for sym, scores in symbol_scores.items() if scores
    }
    
    # Identify rotation candidates
    available_symbols = ["ETHUSDT", "SOLUSDT", "AVAXUSDT", "DOTUSDT", "TRXUSDT", "BTCUSDT"]
    
    for symbol, state in sizing.items():
        current_size = state.get("base_size_usd", 0)
        
        # Skip if no allocation
        if current_size < 100:
            continue
        
        # Get symbol's expectancy
        symbol_expectancy = symbol_avg_expectancy.get(symbol, 0)
        
        # Rotate if expectancy is negative
        if symbol_expectancy < -0.0005:
            # Find better symbol
            best_symbol = max(
                available_symbols,
                key=lambda s: symbol_avg_expectancy.get(s, 0)
            )
            
            if best_symbol != symbol and symbol_avg_expectancy.get(best_symbol, 0) > symbol_expectancy:
                # Perform rotation
                if best_symbol not in sizing:
                    sizing[best_symbol] = {"base_size_usd": 0}
                
                sizing[best_symbol]["base_size_usd"] = sizing[best_symbol].get("base_size_usd", 0) + current_size
                sizing[symbol]["base_size_usd"] = 0
                
                rotation = {
                    "from": symbol,
                    "to": best_symbol,
                    "amount": current_size,
                    "from_expectancy": round(symbol_expectancy, 5),
                    "to_expectancy": round(symbol_avg_expectancy.get(best_symbol, 0), 5)
                }
                
                rotations.append(rotation)
                _append_event(ROTATION_LOG, "symbol_rotated", rotation)
    
    _write_json(SIZING_STATE, sizing)
    return rotations

# ---- Phase 69.0 – Operator Copilot Planner ----
def generate_operator_plan():
    """
    Operator copilot planner - generates actionable strategy plan:
    - Recommends promotions (improving trends)
    - Suggests mutations (declining performance)
    - Identifies retirements (poor signal clarity)
    - Provides regime-aware recommendations
    """
    decay = _read_json(DECAY_LOG, {})
    meta_learning = _read_json(META_LEARNING_LOG, {})
    archetypes = _read_json(ARCHETYPE_LOG, {})
    
    plan = {
        "timestamp": int(time.time()),
        "promote": [],
        "mutate": [],
        "retire": [],
        "regime_expectation": "mixed",
        "archetype_recommendations": {}
    }
    
    # Analyze decay patterns
    for strategy, stats in decay.items():
        roi_trend = stats.get("roi_trend", 0)
        signal_clarity = stats.get("signal_clarity", 1.0)
        decay_status = stats.get("decay_status", "stable")
        
        # Promotion candidates (strong positive trend)
        if roi_trend > 0.002 and signal_clarity > 0.7:
            plan["promote"].append({
                "strategy": strategy,
                "roi_trend": roi_trend,
                "reason": "strong_positive_trend"
            })
        
        # Mutation candidates (declining but salvageable)
        elif roi_trend < -0.002 and signal_clarity > 0.5:
            plan["mutate"].append({
                "strategy": strategy,
                "roi_trend": roi_trend,
                "reason": "declining_performance"
            })
        
        # Retirement candidates (poor signal quality)
        elif signal_clarity < 0.5:
            plan["retire"].append({
                "strategy": strategy,
                "clarity": signal_clarity,
                "reason": "low_signal_clarity"
            })
    
    # Archetype-specific recommendations
    archetype_perf = {}
    for variant_id, arch_data in archetypes.items():
        archetype = arch_data.get("archetype", "unknown")
        perf_score = arch_data.get("performance_score", 0)
        
        if archetype not in archetype_perf:
            archetype_perf[archetype] = []
        archetype_perf[archetype].append(perf_score)
    
    for archetype, scores in archetype_perf.items():
        if scores:
            plan["archetype_recommendations"][archetype] = {
                "avg_performance": round(mean(scores), 4),
                "count": len(scores),
                "recommendation": "scale_up" if mean(scores) > 0.002 else "scale_down" if mean(scores) < 0 else "maintain"
            }
    
    _write_json(PLAN_LOG, plan)
    return plan

# ---- Phase 70.0 – Strategic Memory Consolidator ----
def consolidate_memory():
    """
    Strategic memory consolidator - archives old attribution data:
    - Archives data older than 30 days
    - Maintains recent high-value data
    - Prevents log bloat
    - Enables historical analysis
    """
    trade_outcomes = _read_jsonl(TRADE_OUTCOMES)
    
    cutoff_timestamp = time.time() - (30 * 86400)  # 30 days ago
    
    archived_trades = []
    recent_trades = []
    
    for trade in trade_outcomes:
        trade_timestamp = trade.get("timestamp", time.time())
        
        if trade_timestamp < cutoff_timestamp:
            archived_trades.append(trade)
        else:
            recent_trades.append(trade)
    
    # Archive summary
    archive = {
        "timestamp": int(time.time()),
        "archived_count": len(archived_trades),
        "recent_count": len(recent_trades),
        "cutoff_date": int(cutoff_timestamp),
        "archived_symbols": list(set(t.get("symbol", "") for t in archived_trades if t.get("symbol"))),
        "archived_strategies": list(set(t.get("strategy", "") for t in archived_trades if t.get("strategy")))
    }
    
    _write_json(ARCHIVE_LOG, archive)
    return archive

# ---- Unified Runner ----
def run_phase_66_70():
    """
    Execute all five phases:
    - Archetype classification
    - Decay monitoring
    - Symbol rotation
    - Operator planning
    - Memory consolidation
    """
    archetypes = classify_archetypes()
    decay = monitor_attribution_decay()
    rotation = rotate_symbols()
    plan = generate_operator_plan()
    archive = consolidate_memory()
    
    return {
        "archetypes": archetypes,
        "decay": decay,
        "rotation": rotation,
        "plan": plan,
        "archive": archive
    }

if __name__ == "__main__":
    result = run_phase_66_70()
    print(f"Phase 66: {len(result['archetypes'])} archetypes classified")
    print(f"Phase 67: {len(result['decay'])} strategies analyzed for decay")
    print(f"Phase 68: {len(result['rotation'])} symbol rotations")
    print(f"Phase 69: Plan generated - {len(result['plan']['promote'])} promote, {len(result['plan']['mutate'])} mutate, {len(result['plan']['retire'])} retire")
    print(f"Phase 70: {result['archive']['archived_count']} trades archived")
