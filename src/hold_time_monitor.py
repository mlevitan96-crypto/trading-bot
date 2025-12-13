#!/usr/bin/env python3
"""
HOLD TIME IMPROVEMENT MONITOR
Tracks whether the hold time fixes are working.
Integrated into nightly learning for review.

Phase 4 Migration: Uses SQLite for closed trades via DataRegistry.
"""

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Any

try:
    from src.data_registry import DataRegistry as DR
except ImportError:
    import sys
    sys.path.insert(0, '/home/runner/workspace')
    from src.data_registry import DataRegistry as DR

MONITOR_LOG = Path("logs/hold_time_monitor.jsonl")

DURATION_BUCKETS = {
    "flash": (0, 60),        # <1 min - BAD
    "quick": (60, 300),      # 1-5 min - BAD
    "short": (300, 900),     # 5-15 min - OK
    "medium": (900, 3600),   # 15-60 min - GOOD (positive EV)
    "extended": (3600, 14400), # 1-4 hrs - GOOD
    "long": (14400, float('inf'))
}

def get_bucket(seconds: float) -> str:
    for name, (min_s, max_s) in DURATION_BUCKETS.items():
        if min_s <= seconds < max_s:
            return name
    return "long"


def analyze_recent_hold_times(hours: int = 24) -> Dict[str, Any]:
    """Analyze hold times from recent closed positions.
    
    Phase 4 Migration: Uses SQLite for closed trades via DataRegistry.
    """
    closed = DR.get_closed_trades_from_db()
    
    if not closed:
        return {"error": "No closed positions in database"}
    
    # Filter to recent
    cutoff = datetime.now(timezone.utc).timestamp() - (hours * 3600)
    recent = []
    
    for p in closed:
        try:
            closed_at = p.get("closed_at")
            if closed_at:
                ts = datetime.fromisoformat(closed_at.replace('Z', '+00:00')).timestamp()
                if ts >= cutoff:
                    recent.append(p)
        except:
            continue
    
    if not recent:
        return {"error": f"No trades in last {hours}h", "total_closed": len(closed)}
    
    # Calculate hold times
    hold_times = []
    bucket_counts = {k: 0 for k in DURATION_BUCKETS}
    bucket_pnl = {k: 0.0 for k in DURATION_BUCKETS}
    
    for p in recent:
        try:
            opened = datetime.fromisoformat(p["opened_at"].replace('Z', '+00:00'))
            closed_dt = datetime.fromisoformat(p["closed_at"].replace('Z', '+00:00'))
            hold_secs = abs((closed_dt - opened).total_seconds())
            pnl = p.get("pnl", 0) or 0
            
            bucket = get_bucket(hold_secs)
            bucket_counts[bucket] += 1
            bucket_pnl[bucket] += pnl
            hold_times.append(hold_secs)
        except:
            continue
    
    if not hold_times:
        return {"error": "Could not parse hold times"}
    
    avg_hold = sum(hold_times) / len(hold_times)
    min_hold = min(hold_times)
    max_hold = max(hold_times)
    
    # Calculate improvements
    bad_exits = bucket_counts["flash"] + bucket_counts["quick"]
    good_exits = bucket_counts["short"] + bucket_counts["medium"] + bucket_counts["extended"] + bucket_counts["long"]
    
    bad_pnl = bucket_pnl["flash"] + bucket_pnl["quick"]
    good_pnl = bucket_pnl["short"] + bucket_pnl["medium"] + bucket_pnl["extended"] + bucket_pnl["long"]
    
    result = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "hours_analyzed": hours,
        "trades_analyzed": len(recent),
        "avg_hold_minutes": round(avg_hold / 60, 1),
        "min_hold_minutes": round(min_hold / 60, 1),
        "max_hold_minutes": round(max_hold / 60, 1),
        "bucket_counts": bucket_counts,
        "bucket_pnl": {k: round(v, 2) for k, v in bucket_pnl.items()},
        "bad_exits_count": bad_exits,
        "good_exits_count": good_exits,
        "bad_exits_pct": round(bad_exits / len(recent) * 100, 1) if recent else 0,
        "good_exits_pct": round(good_exits / len(recent) * 100, 1) if recent else 0,
        "bad_exits_pnl": round(bad_pnl, 2),
        "good_exits_pnl": round(good_pnl, 2),
        "improvement_needed": bad_exits > good_exits,
        "target_avg_hold_min": 15  # Goal: 15+ min average
    }
    
    # Log for tracking over time
    os.makedirs(MONITOR_LOG.parent, exist_ok=True)
    with open(MONITOR_LOG, 'a') as f:
        f.write(json.dumps(result) + '\n')
    
    return result


def print_hold_time_report():
    """Print hold time report for nightly review."""
    print("\n" + "=" * 60)
    print("HOLD TIME IMPROVEMENT MONITOR")
    print("=" * 60)
    
    result = analyze_recent_hold_times(hours=24)
    
    if "error" in result:
        print(f"   Error: {result['error']}")
        return result
    
    print(f"\nAnalysis period: Last {result['hours_analyzed']}h")
    print(f"Trades analyzed: {result['trades_analyzed']}")
    print()
    print(f"HOLD TIME STATS:")
    print(f"   Average: {result['avg_hold_minutes']} min (Target: >{result['target_avg_hold_min']} min)")
    print(f"   Min: {result['min_hold_minutes']} min")
    print(f"   Max: {result['max_hold_minutes']} min")
    print()
    print("BUCKET DISTRIBUTION:")
    for bucket, count in result['bucket_counts'].items():
        pnl = result['bucket_pnl'].get(bucket, 0)
        status = "BAD" if bucket in ["flash", "quick"] else "GOOD"
        print(f"   {bucket:12s}: {count:3d} trades | P&L: ${pnl:+.2f} | {status}")
    print()
    print(f"IMPROVEMENT SUMMARY:")
    print(f"   Bad exits (<5 min): {result['bad_exits_count']} ({result['bad_exits_pct']}%) | P&L: ${result['bad_exits_pnl']:.2f}")
    print(f"   Good exits (>5 min): {result['good_exits_count']} ({result['good_exits_pct']}%) | P&L: ${result['good_exits_pnl']:.2f}")
    
    if result['improvement_needed']:
        print("\n   STATUS: IMPROVEMENT NEEDED - Too many early exits")
    else:
        print("\n   STATUS: IMPROVING - More positions held longer")
    
    if result['avg_hold_minutes'] < result['target_avg_hold_min']:
        print(f"   ALERT: Avg hold ({result['avg_hold_minutes']} min) below target ({result['target_avg_hold_min']} min)")
    else:
        print(f"   SUCCESS: Avg hold meets target!")
    
    return result


if __name__ == "__main__":
    print_hold_time_report()
