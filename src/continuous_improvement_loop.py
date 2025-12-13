# src/continuous_improvement_loop.py
#
# Phase 21.0 - Continuous Improvement Loop
# Purpose:
#   - Learns from recent performance to refine strategies
#   - Adjusts filters, thresholds, and sizing based on outcomes
#   - Tracks improvement metrics over time
#   - Logs optimization decisions and parameter updates

import os, json, time

IMPROVEMENT_LOG = "logs/continuous_improvement.jsonl"
TUNING_STATE = "config/auto_tuning_state.json"

def _append_event(event: str, data: dict = None):
    os.makedirs(os.path.dirname(IMPROVEMENT_LOG), exist_ok=True)
    entry = {"event": event, "ts": int(time.time())}
    if data:
        entry.update(data)
    with open(IMPROVEMENT_LOG, "a") as f:
        f.write(json.dumps(entry) + "\n")

def _read_json(path: str, default: dict):
    if not os.path.exists(path):
        return default
    try:
        with open(path, "r") as f:
            return json.load(f)
    except:
        return default

def _write_json(path: str, data: dict):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        json.dump(data, f, indent=2)

def run_continuous_improvement():
    """
    Continuous improvement cycle:
    - Review recent attribution data
    - Identify optimization opportunities
    - Adjust thresholds (ROI floor, confidence, etc.)
    - Log improvement actions taken
    """
    # Load current tuning state
    tuning_state = _read_json(TUNING_STATE, {
        "roi_floor": 0.0018,  # 0.18% default
        "confidence_threshold": 0.70,
        "max_correlation": 0.75,
        "last_update": 0
    })
    
    # Load attribution data to analyze recent performance
    attribution_file = "logs/strategic_attribution.jsonl"
    recent_attribution = {}
    
    if os.path.exists(attribution_file):
        with open(attribution_file, "r") as f:
            for line in f:
                try:
                    event = json.loads(line.strip())
                    if event.get("event") == "attribution_computed":
                        recent_attribution = event
                        break  # Most recent
                except:
                    pass
    
    improvements_made = []
    
    # Example improvement logic: Adjust ROI floor based on overall performance
    strategies = recent_attribution.get("strategies", {})
    if strategies:
        avg_win_rate = sum(s["win_rate"] for s in strategies.values()) / len(strategies)
        
        # If win rate is high (>60%), we can be slightly more aggressive with ROI floor
        if avg_win_rate > 0.60:
            old_floor = tuning_state["roi_floor"]
            tuning_state["roi_floor"] = max(0.0015, old_floor * 0.95)  # Lower by 5% but don't go below 0.15%
            improvements_made.append({
                "parameter": "roi_floor",
                "old_value": old_floor,
                "new_value": tuning_state["roi_floor"],
                "reason": f"High win rate ({avg_win_rate:.1%}) allows more aggressive entry"
            })
        
        # If win rate is low (<45%), be more conservative
        elif avg_win_rate < 0.45:
            old_floor = tuning_state["roi_floor"]
            tuning_state["roi_floor"] = min(0.0025, old_floor * 1.05)  # Raise by 5% but don't go above 0.25%
            improvements_made.append({
                "parameter": "roi_floor",
                "old_value": old_floor,
                "new_value": tuning_state["roi_floor"],
                "reason": f"Low win rate ({avg_win_rate:.1%}) requires more selective entry"
            })
    
    # Update timestamp
    tuning_state["last_update"] = int(time.time())
    
    # Save updated tuning state
    _write_json(TUNING_STATE, tuning_state)
    
    improvement_summary = {
        "improvements_made": len(improvements_made),
        "actions": improvements_made,
        "current_state": tuning_state
    }
    
    _append_event("improvement_cycle_complete", improvement_summary)
    
    return improvement_summary

if __name__ == "__main__":
    result = run_continuous_improvement()
    print("Phase 21.0 Continuous Improvement Loop complete.")
    print(f"Improvements made: {result['improvements_made']}")
    if result["actions"]:
        for action in result["actions"]:
            print(f"  - {action['parameter']}: {action['old_value']:.4f} → {action['new_value']:.4f} ({action['reason']})")
