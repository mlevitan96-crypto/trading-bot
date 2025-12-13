# src/operator_intelligence_loop.py
#
# Phase 23.0 – Operator Intelligence Loop
# Purpose:
#   - Review attribution, diagnostics, governance, and strategy evolution
#   - Issue full system report with recommendations and auto-actions
#   - Auto-promote/prune strategies and symbols
#   - Auto-freeze trading if systemic failure detected
#   - Log to operator_intelligence_events.jsonl and daily_readiness_report.json

import os, json, time
from statistics import mean

ATTRIBUTION_LOG = "logs/strategic_attribution.jsonl"
SAFETY_LOG = "logs/operational_safety.jsonl"
IMPROVEMENT_LOG = "logs/continuous_improvement.jsonl"
SIZING_STATE = "config/sizing_state.json"
READINESS_REPORT = "logs/daily_readiness_report.json"
EVENT_LOG = "logs/operator_intelligence_events.jsonl"

def _append_event(ev: str, payload: dict = None):
    os.makedirs(os.path.dirname(EVENT_LOG), exist_ok=True)
    if payload is None:
        payload = {}
    else:
        payload = dict(payload)
    payload.update({"event": ev, "ts": int(time.time())})
    with open(EVENT_LOG, "a") as f: 
        f.write(json.dumps(payload) + "\n")

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

def run_operator_intelligence():
    """
    Comprehensive operator intelligence review:
    - Analyzes attribution data from Phase 18
    - Reviews safety status from Phase 19
    - Incorporates improvements from Phase 21
    - Auto-promotes high performers
    - Auto-prunes underperformers
    - Freezes trading on governance violations
    - ENHANCED: Detects policy cap saturation and profit velocity issues
    """
    # Load all analytics data
    attribution_events = _read_jsonl(ATTRIBUTION_LOG)
    safety_events = _read_jsonl(SAFETY_LOG)
    improvement_events = _read_jsonl(IMPROVEMENT_LOG)
    sizing_state = _read_json(SIZING_STATE, {})
    
    # ENHANCED: Load policy cap and profit velocity data
    from src.policy_cap_events import get_policy_cap_summary, get_profit_velocity_summary
    cap_summary = get_policy_cap_summary(hours=24)
    profit_velocity = get_profit_velocity_summary(hours=24)

    # ---- 1. Attribution Summary (from Phase 18 data) ----
    by_symbol = {}
    
    # Parse attribution events to extract symbol performance
    for event in attribution_events:
        if event.get("event") == "attribution_computed":
            symbols = event.get("symbols", {})
            for sym, metrics in symbols.items():
                if sym not in by_symbol:
                    by_symbol[sym] = {
                        "trades": metrics.get("trades", 0),
                        "win_rate": metrics.get("win_rate", 0.0),
                        "avg_roi": metrics.get("avg_roi", 0.0),
                        "total_roi": metrics.get("total_roi", 0.0)
                    }

    summary = {}
    promoted = []
    pruned = []
    
    for sym, data in by_symbol.items():
        avg_roi = data["avg_roi"]
        win_rate = data["win_rate"]
        
        summary[sym] = {
            "trades": data["trades"],
            "win_rate": round(win_rate, 3),
            "avg_roi": round(avg_roi, 4),
            "total_roi": round(data["total_roi"], 4)
        }
        
        # Promotion logic: high win rate OR positive ROI with decent volume
        if (win_rate > 0.55 and avg_roi > 0.001) or (avg_roi > 0.002 and data["trades"] >= 5):
            current = sizing_state.get(sym, {}).get("base_size_usd", 250.0)
            next_size = min(5000.0, current * 1.5)
            sizing_state[sym] = {"base_size_usd": next_size}
            promoted.append({"symbol": sym, "from": current, "to": next_size, "reason": f"WR:{win_rate:.1%} ROI:{avg_roi:.2%}"})
            _append_event("symbol_promoted", {"symbol": sym, "from": current, "to": next_size})
        
        # Pruning logic: poor performance or negative ROI
        elif avg_roi < -0.005 or (win_rate < 0.40 and data["trades"] >= 5):
            current = sizing_state.get(sym, {}).get("base_size_usd", 250.0)
            next_size = max(100.0, current * 0.5)
            sizing_state[sym] = {"base_size_usd": next_size}
            pruned.append({"symbol": sym, "from": current, "to": next_size, "reason": f"WR:{win_rate:.1%} ROI:{avg_roi:.2%}"})
            _append_event("symbol_pruned", {"symbol": sym, "from": current, "to": next_size})

    # Save updated sizing state
    if promoted or pruned:
        _write_json(SIZING_STATE, sizing_state)

    # ---- 2. Governance Violation Detection (from Phase 19 data) ----
    violations = []
    latest_safety_score = 1.0
    
    for event in safety_events:
        if event.get("event") == "safety_checks_complete":
            latest_safety_score = event.get("safety_score", 1.0)
        if event.get("event") == "safety_critical_failure":
            violations.extend(event.get("issues", []))

    freeze_triggered = False
    if latest_safety_score < 0.50 or violations:
        freeze_triggered = True
        _append_event("trading_frozen", {"reason": "safety_failure", "safety_score": latest_safety_score, "violations": violations})
        # Create freeze flag
        with open("logs/trading_frozen.flag", "w") as f:
            f.write(json.dumps({"reason": "safety_failure", "ts": int(time.time())}))

    # ---- 3. Improvement Insights (from Phase 21 data) ----
    improvements_applied = []
    for event in improvement_events:
        if event.get("event") == "improvement_cycle_complete":
            improvements_applied = event.get("actions", [])

    # ---- 4. ENHANCED: Policy Cap Saturation Detection ----
    optimization_opportunities = []
    
    # Check for policy cap saturation
    if cap_summary["high_severity_count"] >= 3:
        opportunity = {
            "type": "policy_cap_saturation",
            "severity": "high",
            "description": f"Kelly sizing hitting policy caps {cap_summary['total_caps']} times (avg reduction: {cap_summary['avg_reduction_pct']:.1f}%)",
            "recommendation": "Increase trading policy limits to allow larger position sizes",
            "current_limits": "$200-$1000",
            "suggested_limits": "$400-$2000"
        }
        optimization_opportunities.append(opportunity)
        _append_event("optimization_opportunity_detected", opportunity)
        
        # ENHANCED: Create formal optimization proposal
        from src.autonomous_optimization_proposals import propose_policy_increase
        propose_policy_increase(
            current_min=200,
            current_max=1000,
            suggested_min=400,
            suggested_max=2000,
            reason=f"Kelly sizing hitting policy caps {cap_summary['total_caps']}x with avg {cap_summary['avg_reduction_pct']:.1f}% reduction - profitable signals being limited",
            severity="high"
        )
    
    # Check for profitable but small trades
    if profit_velocity["total_trades"] >= 5:
        if profit_velocity["avg_profit_usd"] > 0 and profit_velocity["avg_profit_usd"] < 0.50:
            opportunity = {
                "type": "low_profit_velocity",
                "severity": "medium",
                "description": f"Trades are profitable but generating tiny profits (avg ${profit_velocity['avg_profit_usd']:.4f} per trade)",
                "recommendation": "Position sizes too small - profitable signals not being maximized",
                "current_avg_profit": f"${profit_velocity['avg_profit_usd']:.4f}",
                "target_avg_profit": "$1.00+",
                "meaningful_profit_rate": f"{profit_velocity['meaningful_profit_pct']:.1f}%"
            }
            optimization_opportunities.append(opportunity)
            _append_event("optimization_opportunity_detected", opportunity)
            
            # ENHANCED: Create formal optimization proposal
            from src.autonomous_optimization_proposals import propose_policy_increase
            propose_policy_increase(
                current_min=200,
                current_max=1000,
                suggested_min=400,
                suggested_max=2000,
                reason=f"Profitable trades generating tiny profits (avg ${profit_velocity['avg_profit_usd']:.4f}/trade) - position sizes too small to maximize returns",
                severity="medium"
            )
    
    # ---- 5. Daily Readiness Report ----
    report = {
        "timestamp": int(time.time()),
        "date": time.strftime("%Y-%m-%d %H:%M:%S"),
        "symbol_summary": summary,
        "promoted_symbols": promoted,
        "pruned_symbols": pruned,
        "improvements_applied": improvements_applied,
        "safety_score": latest_safety_score,
        "governance_violations": violations,
        "trading_frozen": freeze_triggered,
        "optimization_opportunities": optimization_opportunities,
        "policy_cap_summary": cap_summary,
        "profit_velocity_summary": profit_velocity,
        "readiness_status": "READY" if not freeze_triggered and latest_safety_score >= 0.80 else "DEGRADED" if not freeze_triggered else "FROZEN"
    }
    
    _write_json(READINESS_REPORT, report)
    _append_event("operator_intelligence_summary", {
        "promoted": len(promoted),
        "pruned": len(pruned),
        "safety_score": latest_safety_score,
        "status": report["readiness_status"]
    })

    return report

if __name__ == "__main__":
    result = run_operator_intelligence()
    print("Phase 23.0 Operator Intelligence Loop executed. Strategic review and auto-actions complete.")
    print(f"Status: {result['readiness_status']} | Safety: {result['safety_score']:.0%}")
    print(f"Promoted: {len(result['promoted_symbols'])} | Pruned: {len(result['pruned_symbols'])}")
