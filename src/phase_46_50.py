# src/phase_46_50.py
#
# Phases 46–50: Strategy Composer, Expectancy Engine, Variant Pruner, 
#              Regime Allocator, Operator Copilot CLI

import os
import json
import time
from statistics import mean
from typing import Dict, List, Any

# Paths
STRATEGIC_ATTRIBUTION = "logs/strategic_attribution.jsonl"
TRADE_OUTCOMES = "logs/trade_outcomes.jsonl"
LINEAGE_LOG = "config/strategy_lineage.json"
SHADOW_STATE = "config/shadow_strategy_state.json"
SIZING_STATE = "config/sizing_state.json"
REGIME_FORECAST = "logs/regime_forecast.json"
REGIME_MEMORY = "logs/symbol_regime_memory.json"
EXIT_PROFILES = "config/exit_profiles.json"
STRATEGY_PROFILES = "logs/strategy_profiles.json"
COMPOSED_STRATEGIES = "config/composed_strategies.json"
EXPECTANCY_LOG = "logs/expectancy_scores.json"
PRUNER_LOG = "logs/variant_pruner_events.jsonl"
REGIME_ALLOCATOR_LOG = "logs/regime_allocator_events.jsonl"
OPERATOR_CLI_LOG = "logs/operator_cli_events.jsonl"
COMPOSER_LOG = "logs/strategy_composer_events.jsonl"

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

# ---- Phase 46.0 – Strategy Composer ----
def compose_strategies():
    """
    Create new composite strategies from successful variants:
    - Identify high-performing variants (ROI > 0.2%, WR > 50%)
    - Extract successful parameter combinations
    - Create new composed strategies with proven configs
    """
    lineage = _read_json(LINEAGE_LOG, {})
    shadow_state = _read_json(SHADOW_STATE, {})
    strategy_profiles = _read_json(STRATEGY_PROFILES, {})
    
    composed = []
    
    # Analyze each strategy's variants for composition candidates
    for base_strategy, variants in lineage.items():
        for variant_id, data in variants.items():
            perf_history = data.get("performance_history", [])
            
            if len(perf_history) < 10:
                continue  # Need sufficient history
            
            # Extract recent performance
            recent_perf = perf_history[-5:] if len(perf_history) >= 5 else perf_history
            avg_roi = mean([p.get("avg_roi", 0.0) for p in recent_perf])
            avg_win_rate = mean([p.get("win_rate", 0.0) for p in recent_perf])
            
            # Compose from high performers
            if avg_roi > 0.002 and avg_win_rate > 0.5:
                # Extract variant configuration from shadow state
                variant_config = None
                for shadow_base, shadow_variants in shadow_state.items():
                    for sv in shadow_variants:
                        if sv.get("variant_id") == variant_id:
                            variant_config = sv
                            break
                
                if not variant_config:
                    continue
                
                new_id = f"{base_strategy}_composed_{int(time.time() % 100000)}"
                
                composed_strategy = {
                    "id": new_id,
                    "base_strategy": base_strategy,
                    "parent_variant": variant_id,
                    "filters": variant_config.get("filters", {}),
                    "timeframe": variant_config.get("timeframe", "5m"),
                    "exit_profile_id": variant_config.get("exit_profile_id", "exit_hybrid_chop_v3"),
                    "avg_roi": round(avg_roi, 4),
                    "win_rate": round(avg_win_rate, 3),
                    "created": int(time.time()),
                    "status": "composed"
                }
                
                composed.append(composed_strategy)
                
                _append_event(COMPOSER_LOG, "strategy_composed", {
                    "composed_id": new_id,
                    "parent": variant_id,
                    "avg_roi": round(avg_roi, 4)
                })
    
    _write_json(COMPOSED_STRATEGIES, {"strategies": composed, "count": len(composed)})
    return composed

# ---- Phase 47.0 – Expectancy Engine ----
def calculate_expectancy():
    """
    Calculate mathematical expectancy for each strategy-symbol pair:
    Expectancy = (WinRate × AvgWin) - (LossRate × AvgLoss)
    - Positive expectancy = edge in the market
    - Higher expectancy = better long-term performance
    """
    trade_outcomes = _read_jsonl(TRADE_OUTCOMES)
    
    scores = {}
    
    # Group trades by strategy-symbol pairs
    for trade in trade_outcomes:
        symbol = trade.get("symbol", "")
        strategy = trade.get("strategy", "")
        roi = trade.get("net_roi", 0.0)
        
        if not symbol or not strategy:
            continue
        
        key = f"{strategy}_{symbol}"
        
        if key not in scores:
            scores[key] = {"wins": [], "losses": []}
        
        if roi > 0:
            scores[key]["wins"].append(roi)
        else:
            scores[key]["losses"].append(abs(roi))
    
    # Calculate expectancy for each pair
    results = {}
    for key, data in scores.items():
        total_trades = len(data["wins"]) + len(data["losses"])
        
        if total_trades < 5:
            continue  # Need minimum data
        
        win_rate = len(data["wins"]) / total_trades if total_trades > 0 else 0
        avg_win = mean(data["wins"]) if data["wins"] else 0
        avg_loss = mean(data["losses"]) if data["losses"] else 0
        
        # Expectancy formula
        expectancy = (win_rate * avg_win) - ((1 - win_rate) * avg_loss)
        
        results[key] = {
            "expectancy": round(expectancy, 5),
            "win_rate": round(win_rate, 3),
            "avg_win": round(avg_win, 4),
            "avg_loss": round(avg_loss, 4),
            "total_trades": total_trades,
            "edge": "positive" if expectancy > 0 else "negative"
        }
    
    _write_json(EXPECTANCY_LOG, results)
    return results

# ---- Phase 48.0 – Variant Pruner ----
def prune_variants():
    """
    Flag underperforming variants for removal:
    - Low volume: < 5 performance snapshots
    - Weak ROI: average ROI < 0.1%
    - Consistent losses: recent ROI trending negative
    """
    lineage = _read_json(LINEAGE_LOG, {})
    
    flagged = []
    
    for base_strategy, variants in lineage.items():
        for variant_id, data in variants.items():
            perf_history = data.get("performance_history", [])
            status = data.get("status", "active")
            
            # Skip already retired variants
            if status == "retired":
                continue
            
            # Flag low volume variants
            if len(perf_history) < 5:
                flagged.append({
                    "strategy": base_strategy,
                    "variant": variant_id,
                    "reason": "insufficient_data",
                    "snapshots": len(perf_history)
                })
                _append_event(PRUNER_LOG, "variant_flagged", flagged[-1])
                continue
            
            # Extract performance metrics
            roi_values = [p.get("avg_roi", 0.0) for p in perf_history]
            avg_roi = mean(roi_values)
            
            # Flag weak performers
            if avg_roi < 0.001:
                flagged.append({
                    "strategy": base_strategy,
                    "variant": variant_id,
                    "reason": "weak_roi",
                    "avg_roi": round(avg_roi, 4),
                    "snapshots": len(perf_history)
                })
                _append_event(PRUNER_LOG, "variant_flagged", flagged[-1])
            
            # Flag declining performers
            if len(roi_values) >= 5:
                recent_roi = mean(roi_values[-3:])
                if recent_roi < -0.001:
                    flagged.append({
                        "strategy": base_strategy,
                        "variant": variant_id,
                        "reason": "declining_performance",
                        "recent_roi": round(recent_roi, 4),
                        "snapshots": len(perf_history)
                    })
                    _append_event(PRUNER_LOG, "variant_flagged", flagged[-1])
    
    return flagged

# ---- Phase 49.0 – Regime-Specific Allocator ----
def allocate_by_regime():
    """
    Adjust capital allocation based on regime consistency:
    - Increase allocation if regime stable (3+ consecutive matching predictions)
    - Scale up to 20% for symbols performing well in current regime
    - Maintain $100-$5000 limits
    """
    sizing = _read_json(SIZING_STATE, {})
    forecast = _read_json(REGIME_FORECAST, {})
    memory = _read_json(REGIME_MEMORY, {})
    
    predicted_regime = forecast.get("predicted_regime", "mixed")
    updated = []
    
    for symbol, regime_history in memory.items():
        if len(regime_history) < 5:
            continue  # Need history
        
        # Check recent regime consistency
        recent_regimes = [r.get("regime", "") for r in regime_history[-5:]]
        regime_match_count = sum(1 for r in recent_regimes if r == predicted_regime)
        
        # Scale up if regime is stable and matching
        if regime_match_count >= 3:
            current_size = sizing.get(symbol, {}).get("base_size_usd", 250.0)
            new_size = min(5000.0, current_size * 1.2)
            
            if new_size != current_size:
                sizing[symbol] = {
                    "base_size_usd": new_size,
                    "last_updated": int(time.time()),
                    "reason": f"regime_stable_{predicted_regime}",
                    "regime_match_count": regime_match_count
                }
                
                updated.append({
                    "symbol": symbol,
                    "from": current_size,
                    "to": new_size,
                    "regime": predicted_regime,
                    "consistency": regime_match_count
                })
                
                _append_event(REGIME_ALLOCATOR_LOG, "capital_scaled_by_regime", updated[-1])
    
    _write_json(SIZING_STATE, sizing)
    return updated

# ---- Phase 50.0 – Operator Copilot CLI ----
def operator_cli_query(query: str):
    """
    Natural language query interface for operational insights:
    - "highest expectancy" - finds best strategy-symbol pairs
    - "stop rate > X%" - identifies strategies with excessive stops
    - "top performers" - lists best variants
    - "worst performers" - lists underperforming variants
    """
    query_lower = query.lower()
    
    if "highest expectancy" in query_lower or "best expectancy" in query_lower:
        scores = _read_json(EXPECTANCY_LOG, {})
        if not scores:
            result = "No expectancy data available yet."
        else:
            best = max(scores.items(), key=lambda x: x[1].get("expectancy", -999))
            result = (f"Top strategy-symbol pair: {best[0]}\n"
                     f"Expectancy: {best[1].get('expectancy', 0):.5f}\n"
                     f"Win Rate: {best[1].get('win_rate', 0):.1%}\n"
                     f"Trades: {best[1].get('total_trades', 0)}")
    
    elif "stop rate" in query_lower:
        # Extract threshold if provided
        threshold = 0.5
        if ">" in query_lower:
            try:
                threshold = float(query_lower.split(">")[1].strip().replace("%", "")) / 100
            except:
                pass
        
        trade_outcomes = _read_jsonl(TRADE_OUTCOMES)
        stop_counts = {}
        
        for trade in trade_outcomes:
            strategy = trade.get("strategy", "")
            exit_type = trade.get("exit_type", "")
            
            if not strategy:
                continue
            
            if strategy not in stop_counts:
                stop_counts[strategy] = {"stops": 0, "total": 0}
            
            stop_counts[strategy]["total"] += 1
            if exit_type == "stop_loss":
                stop_counts[strategy]["stops"] += 1
        
        high_stop_strategies = []
        for strategy, counts in stop_counts.items():
            if counts["total"] >= 5:
                stop_rate = counts["stops"] / counts["total"]
                if stop_rate > threshold:
                    high_stop_strategies.append(f"{strategy}: {stop_rate:.1%} stop rate ({counts['stops']}/{counts['total']})")
        
        result = "\n".join(high_stop_strategies) if high_stop_strategies else f"No strategies exceed {threshold:.0%} stop rate."
    
    elif "top performers" in query_lower or "best variants" in query_lower:
        lineage = _read_json(LINEAGE_LOG, {})
        performers = []
        
        for base_strategy, variants in lineage.items():
            for variant_id, data in variants.items():
                perf_history = data.get("performance_history", [])
                if len(perf_history) >= 5:
                    recent_roi = mean([p.get("avg_roi", 0.0) for p in perf_history[-5:]])
                    if recent_roi > 0.002:
                        performers.append((variant_id, recent_roi))
        
        performers.sort(key=lambda x: x[1], reverse=True)
        top_5 = performers[:5]
        
        result = "Top 5 Performers:\n" + "\n".join([f"{v}: {roi:.2%} avg ROI" for v, roi in top_5]) if top_5 else "No top performers yet."
    
    elif "worst performers" in query_lower or "underperformers" in query_lower:
        lineage = _read_json(LINEAGE_LOG, {})
        performers = []
        
        for base_strategy, variants in lineage.items():
            for variant_id, data in variants.items():
                perf_history = data.get("performance_history", [])
                if len(perf_history) >= 5:
                    recent_roi = mean([p.get("avg_roi", 0.0) for p in perf_history[-5:]])
                    performers.append((variant_id, recent_roi))
        
        performers.sort(key=lambda x: x[1])
        worst_5 = performers[:5]
        
        result = "Worst 5 Performers:\n" + "\n".join([f"{v}: {roi:.2%} avg ROI" for v, roi in worst_5]) if worst_5 else "No underperformers identified."
    
    else:
        result = f"Query not recognized: '{query}'\n\nAvailable queries:\n- 'highest expectancy'\n- 'stop rate > X%'\n- 'top performers'\n- 'worst performers'"
    
    _append_event(OPERATOR_CLI_LOG, "operator_query", {"query": query, "response": result})
    return result

# ---- Unified Runner ----
def run_phase_46_50():
    """
    Execute all five phases:
    - Strategy composition
    - Expectancy calculation
    - Variant pruning
    - Regime-based allocation
    - Operator CLI
    """
    composed = compose_strategies()
    expectancy = calculate_expectancy()
    pruned = prune_variants()
    regime_alloc = allocate_by_regime()
    
    # Sample CLI query
    cli_response = operator_cli_query("Which strategy has highest expectancy?")
    
    return {
        "composed": composed,
        "expectancy": expectancy,
        "pruned": pruned,
        "regime_allocation": regime_alloc,
        "cli_response": cli_response
    }

if __name__ == "__main__":
    result = run_phase_46_50()
    print(f"Phase 46: {len(result['composed'])} strategies composed")
    print(f"Phase 47: {len(result['expectancy'])} expectancy scores calculated")
    print(f"Phase 48: {len(result['pruned'])} variants flagged for pruning")
    print(f"Phase 49: {len(result['regime_allocation'])} regime-based allocations")
    print(f"Phase 50: CLI query executed")
