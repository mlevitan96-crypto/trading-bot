# src/phase_29_30.py
#
# Phase 29.0 – Strategy Lineage Tracker
# Phase 30.0 – AI-Governed Capital Allocator

import os, json, time
from statistics import mean

ATTRIBUTION_LOG = "logs/strategic_attribution.jsonl"
VARIANT_STATE = "config/shadow_strategy_state.json"
SIZING_STATE = "config/sizing_state.json"
LINEAGE_LOG = "config/strategy_lineage.json"
LINEAGE_EVENTS = "logs/lineage_events.jsonl"
CAPITAL_EVENTS = "logs/capital_allocator_events.jsonl"

def _read_json(path: str, default: dict):
    if not os.path.exists(path): 
        return default
    with open(path, "r") as f:
        try: 
            return json.load(f)
        except: 
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
                except: 
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

# ---- Phase 29.0 – Strategy Lineage Tracker ----
def update_strategy_lineage():
    """
    Track strategy variant performance over time:
    - Monitor variant ROI history
    - Retire underperformers (avg ROI < -0.2% after 15+ trades)
    - Promote winners (avg ROI > 0.3% after 15+ trades)
    - Log all lineage events for audit trail
    """
    # shadow_strategy_state.json has structure: {strategy_name: [variant1, variant2, ...]}
    variants = _read_json(VARIANT_STATE, {})
    lineage = _read_json(LINEAGE_LOG, {})
    
    promoted_count = 0
    retired_count = 0

    # Process shadow strategy variants
    for base_strategy, variant_list in variants.items():
        if not isinstance(variant_list, list):
            continue
        
        # Initialize lineage entry for this strategy
        if base_strategy not in lineage:
            lineage[base_strategy] = {}
        
        # Process each variant in the list
        for variant_data in variant_list:
            if not isinstance(variant_data, dict):
                continue
            
            variant_id = variant_data.get("id", "unknown")
            perf_data = variant_data.get("performance", {})
            
            # Extract performance metrics
            trades = perf_data.get("trades", 0)
            win_rate = perf_data.get("win_rate", 0.0)
            total_roi = perf_data.get("total_roi", 0.0)
            
            # Calculate average ROI
            avg_roi = total_roi / trades if trades > 0 else 0.0
            
            # Initialize lineage entry for this variant
            if variant_id not in lineage[base_strategy]:
                lineage[base_strategy][variant_id] = {
                    "created": variant_data.get("created", int(time.time())),
                    "performance_history": [],
                    "status": "active"
                }
            
            # Update performance history
            lineage[base_strategy][variant_id]["performance_history"].append({
                "ts": int(time.time()),
                "trades": trades,
                "win_rate": win_rate,
                "avg_roi": avg_roi
            })
            
            # Limit history to last 30 entries
            history = lineage[base_strategy][variant_id]["performance_history"]
            if len(history) > 30:
                lineage[base_strategy][variant_id]["performance_history"] = history[-30:]
            
            # Evaluate for promotion/retirement (need 15+ trades)
            if trades >= 15:
                current_status = lineage[base_strategy][variant_id]["status"]
                
                # Retire underperformers
                if avg_roi < -0.002 and current_status == "active":
                    lineage[base_strategy][variant_id]["status"] = "retired"
                    lineage[base_strategy][variant_id]["retired_ts"] = int(time.time())
                    _append_event(LINEAGE_EVENTS, "variant_retired", {
                        "strategy": base_strategy, 
                        "variant": variant_id,
                        "avg_roi": avg_roi,
                        "trades": trades
                    })
                    retired_count += 1
                
                # Promote winners
                elif avg_roi > 0.003 and win_rate > 0.50 and current_status == "active":
                    lineage[base_strategy][variant_id]["status"] = "promoted"
                    lineage[base_strategy][variant_id]["promoted_ts"] = int(time.time())
                    _append_event(LINEAGE_EVENTS, "variant_promoted", {
                        "strategy": base_strategy, 
                        "variant": variant_id,
                        "avg_roi": avg_roi,
                        "win_rate": win_rate,
                        "trades": trades
                    })
                    promoted_count += 1

    _write_json(LINEAGE_LOG, lineage)
    _append_event(LINEAGE_EVENTS, "lineage_update_complete", {
        "promoted": promoted_count,
        "retired": retired_count,
        "total_variants": sum(len(v) for v in lineage.values())
    })
    
    return {
        "lineage": lineage,
        "promoted": promoted_count,
        "retired": retired_count
    }

# ---- Phase 30.0 – AI-Governed Capital Allocator ----
def run_capital_allocator():
    """
    Intelligent capital allocation based on performance:
    - Increase allocation by 1.5x for profitable symbols (avg ROI > 0.2%)
    - Decrease allocation by 0.5x for losing symbols (avg ROI < -0.1%)
    - Enforce limits: $100 min, $5000 max
    - Track all allocation changes
    - Uses MOST RECENT attribution data per symbol
    """
    attribution_events = _read_jsonl(ATTRIBUTION_LOG)
    sizing = _read_json(SIZING_STATE, {})
    
    # Parse attribution data by symbol - keep only MOST RECENT metrics
    by_symbol = {}
    for event in attribution_events:
        if event.get("event") == "attribution_computed":
            symbols = event.get("symbols", {})
            for sym, metrics in symbols.items():
                # Always overwrite with latest data
                by_symbol[sym] = {
                    "trades": metrics.get("trades", 0),
                    "avg_roi": metrics.get("avg_roi", 0.0),
                    "win_rate": metrics.get("win_rate", 0.0),
                    "timestamp": event.get("ts", 0)
                }

    updates = []
    
    for sym, data in by_symbol.items():
        if data["trades"] < 5:
            continue  # Need minimum trade history
        
        avg_roi = data["avg_roi"]
        current_size = sizing.get(sym, {}).get("base_size_usd", 250.0)
        
        # Increase allocation for winners
        if avg_roi > 0.002:
            next_size = min(5000.0, current_size * 1.5)
            if next_size != current_size:
                sizing[sym] = {
                    "base_size_usd": next_size,
                    "last_updated": int(time.time()),
                    "reason": f"profitable (avg ROI: {avg_roi:.2%})",
                    "based_on_trades": data["trades"]
                }
                updates.append({
                    "symbol": sym, 
                    "from": current_size, 
                    "to": next_size,
                    "reason": "increase_profitable",
                    "avg_roi": avg_roi
                })
        
        # Decrease allocation for losers
        elif avg_roi < -0.001:
            next_size = max(100.0, current_size * 0.5)
            if next_size != current_size:
                sizing[sym] = {
                    "base_size_usd": next_size,
                    "last_updated": int(time.time()),
                    "reason": f"unprofitable (avg ROI: {avg_roi:.2%})",
                    "based_on_trades": data["trades"]
                }
                updates.append({
                    "symbol": sym, 
                    "from": current_size, 
                    "to": next_size,
                    "reason": "decrease_unprofitable",
                    "avg_roi": avg_roi
                })

    _write_json(SIZING_STATE, sizing)
    _append_event(CAPITAL_EVENTS, "capital_allocation_updated", {
        "updates": updates,
        "total_symbols": len(sizing)
    })
    
    return updates

# ---- Unified Runner ----
def run_phase_29_30():
    """
    Execute both Phase 29 and Phase 30:
    - Track strategy lineage
    - Allocate capital intelligently
    """
    lineage_result = update_strategy_lineage()
    capital_updates = run_capital_allocator()
    
    return {
        "lineage": lineage_result,
        "capital_updates": capital_updates
    }

if __name__ == "__main__":
    result = run_phase_29_30()
    print(f"Phase 29.0: {result['lineage']['promoted']} promoted, {result['lineage']['retired']} retired")
    print(f"Phase 30.0: {len(result['capital_updates'])} capital allocations updated")
