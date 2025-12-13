"""
Adaptive Learning for Futures Ladder Exits.
Analyzes ladder exit performance, recommends optimized tier allocations, and promotes them to policies.
"""
import json
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Any, Tuple

LOGS = Path("logs")
CONFIGS = Path("configs")
BACKUPS = CONFIGS / "backups"


def load_json(path: Path, fallback=None):
    """Load JSON file with fallback."""
    try:
        with open(path, "r") as f:
            return json.load(f)
    except:
        return fallback if fallback is not None else {}


def save_json(path: Path, data: Dict[str, Any]):
    """Save data to JSON file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        json.dump(data, f, indent=2)


def backup_config(path: Path) -> str:
    """Create timestamped backup of config file."""
    ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    dest = BACKUPS / f"{path.name}_{ts}.json"
    save_json(dest, load_json(path, {}))
    return dest.name


def score_ladder_events(events: List[Dict[str, Any]]) -> Dict[int, float]:
    """
    Score ladder exit events by tier based on exit reason quality.
    
    Positive scores: Profitable exits (RR hits, signal reversals)
    Negative scores: Defensive exits (protective mode, trailing stops)
    
    Args:
        events: List of ladder exit event records
    
    Returns:
        Dict mapping tier_index to cumulative score
    """
    reason_weights = {
        "rr_hit_1.0%": +2.0,
        "rr_hit_2.0%": +3.0,
        "signal_reverse": +1.5,
        "protective_reduce": -1.0,
        "trail_stop": -2.0
    }
    
    tier_scores = {}
    
    for event in events:
        idx = int(event.get("tier_index", 0))
        reason = str(event.get("reason", ""))
        
        weight = 0.0
        if reason.startswith("rr_hit_"):
            if "2.0%" in reason:
                weight = reason_weights["rr_hit_2.0%"]
            elif "1.0%" in reason:
                weight = reason_weights["rr_hit_1.0%"]
            else:
                weight = 1.5
        else:
            weight = reason_weights.get(reason, 0.0)
        
        tier_scores[idx] = tier_scores.get(idx, 0.0) + weight
    
    return tier_scores


def recommend_tier_allocation(current_tiers: List[float], tier_scores: Dict[int, float]) -> List[float]:
    """
    Recommend new tier allocation based on performance scores.
    
    Args:
        current_tiers: Current tier percentages
        tier_scores: Performance scores by tier
    
    Returns:
        Recommended tier percentages (sum to 1.0)
    """
    n = max(len(current_tiers), (max(tier_scores.keys()) + 1) if tier_scores else 3)
    
    raw_scores = [max(0.1, tier_scores.get(i, 0.1)) for i in range(n)]
    
    total = sum(raw_scores)
    recommended = [round(x / total, 2) for x in raw_scores]
    
    diff = round(1.0 - sum(recommended), 2)
    if diff != 0:
        recommended[-1] = round(recommended[-1] + diff, 2)
    
    return recommended


def optimize_exit_policies() -> Dict[str, Any]:
    """
    Analyze ladder exit history and optimize tier allocations.
    
    Process:
    1. Load all ladder exit events
    2. Group by (symbol, strategy, regime) cohorts
    3. Score each tier based on exit reasons
    4. Recommend new tier allocations
    5. Promote recommendations with sufficient data (≥6 events)
    6. Backup original policies before updating
    
    Returns:
        Status dict with backup name and promotion count
    """
    events_data = load_json(LOGS / "ladder_exit_events.json", {"events": []})
    events = events_data.get("events", [])
    
    policies = load_json(CONFIGS / "ladder_exit_policies.json", {
        "defaults": {"tiers_pct": [0.25, 0.25, 0.5]},
        "overrides": []
    })
    
    overrides = policies.get("overrides", [])
    defaults = policies.get("defaults", {"tiers_pct": [0.25, 0.25, 0.5]})
    
    cohorts = {}
    for event in events:
        key = f"{event.get('symbol', '')}|{event.get('strategy', '')}|{event.get('regime', '')}"
        cohorts.setdefault(key, []).append(event)
    
    recommendations = []
    for key, cohort_events in cohorts.items():
        symbol, strategy, regime = key.split("|")
        
        tier_scores = score_ladder_events(cohort_events)
        
        current_tiers = defaults.get("tiers_pct", [0.25, 0.25, 0.5])
        for override in overrides:
            if (override.get("symbol") == symbol and
                override.get("strategy") == strategy and
                override.get("regime") == regime):
                current_tiers = override.get("tiers_pct", current_tiers)
                break
        
        recommended_tiers = recommend_tier_allocation(current_tiers, tier_scores)
        
        recommendations.append({
            "symbol": symbol,
            "strategy": strategy,
            "regime": regime,
            "current_tiers_pct": current_tiers,
            "recommended_tiers_pct": recommended_tiers,
            "tier_scores": tier_scores,
            "events_considered": len(cohort_events),
            "generated_at": datetime.utcnow().isoformat()
        })
    
    save_json(LOGS / "ladder_exit_learning.json", {
        "recommendations": recommendations,
        "timestamp": datetime.utcnow().isoformat()
    })
    
    backup_name = backup_config(CONFIGS / "ladder_exit_policies.json")
    
    promoted_count = 0
    for rec in recommendations:
        if rec["events_considered"] >= 6:
            updated = False
            
            for i, override in enumerate(policies.get("overrides", [])):
                if (override.get("symbol") == rec["symbol"] and
                    override.get("strategy") == rec["strategy"] and
                    override.get("regime") == rec["regime"]):
                    policies["overrides"][i]["tiers_pct"] = rec["recommended_tiers_pct"]
                    policies["overrides"][i]["last_promoted_at"] = datetime.utcnow().isoformat()
                    updated = True
                    promoted_count += 1
                    break
            
            if not updated:
                policies.setdefault("overrides", []).append({
                    "symbol": rec["symbol"],
                    "strategy": rec["strategy"],
                    "regime": rec["regime"],
                    "tiers_pct": rec["recommended_tiers_pct"],
                    "last_promoted_at": datetime.utcnow().isoformat()
                })
                promoted_count += 1
    
    save_json(CONFIGS / "ladder_exit_policies.json", policies)
    
    save_json(LOGS / "ladder_exit_policies_promotion.json", {
        "backup": backup_name,
        "promoted_count": promoted_count,
        "timestamp": datetime.utcnow().isoformat()
    })
    
    return {
        "status": "ok",
        "backup": backup_name,
        "promoted_count": promoted_count,
        "recommendations_generated": len(recommendations)
    }


def rollback_exit_policies() -> Dict[str, Any]:
    """
    Rollback ladder exit policies to latest backup.
    
    Returns:
        Status dict with rollback details
    """
    backups = sorted(BACKUPS.glob("ladder_exit_policies.json_*.json"), reverse=True)
    
    if not backups:
        return {"status": "no_backups"}
    
    latest = backups[0]
    data = load_json(latest, {})
    save_json(CONFIGS / "ladder_exit_policies.json", data)
    
    return {
        "status": "rolled_back",
        "file": latest.name,
        "timestamp": datetime.utcnow().isoformat()
    }


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Adaptive learning for futures ladder exits")
    parser.add_argument("--optimize", action="store_true", help="Analyze exits and optimize policies")
    parser.add_argument("--rollback", action="store_true", help="Rollback to latest backup")
    parser.add_argument("--status", action="store_true", help="Show learning status")
    
    args = parser.parse_args()
    
    if args.optimize:
        print("🧠 Optimizing ladder exit policies...")
        result = optimize_exit_policies()
        print(json.dumps(result, indent=2))
        
        learning_data = load_json(LOGS / "ladder_exit_learning.json", {})
        print("\n📊 Recommendations:")
        print(json.dumps(learning_data, indent=2))
    
    elif args.rollback:
        print("⏪ Rolling back ladder exit policies...")
        result = rollback_exit_policies()
        print(json.dumps(result, indent=2))
    
    elif args.status:
        learning_data = load_json(LOGS / "ladder_exit_learning.json", {})
        promo_data = load_json(LOGS / "ladder_exit_policies_promotion.json", {})
        
        print("📊 Learning Status:")
        print(f"  Recommendations: {len(learning_data.get('recommendations', []))}")
        print(f"  Last promotion: {promo_data.get('timestamp', 'Never')}")
        print(f"  Promoted count: {promo_data.get('promoted_count', 0)}")
        print(f"  Latest backup: {promo_data.get('backup', 'None')}")
    
    else:
        print("Usage: python3 src/futures_exit_learning.py [--optimize | --rollback | --status]")
        print("\nExamples:")
        print("  python3 src/futures_exit_learning.py --optimize   # Analyze and optimize")
        print("  python3 src/futures_exit_learning.py --rollback   # Undo last changes")
        print("  python3 src/futures_exit_learning.py --status     # View learning status")
