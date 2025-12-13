"""
Health-to-Learning Bridge
========================
Feeds all monitoring, health check, and auto-remediation data into the nightly learning engine.
Ensures the system continuously improves from operational events.

Components that feed learning:
1. Health pulse events (stalls, recoveries)
2. Auto-remediation actions (what was fixed, did it work?)
3. Gate decisions (streak filter, intelligence gate blocks)
4. Kill-switch activations and recoveries
5. Position close outcomes (win/loss + reasons)
"""

import json
import os
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, Any, List, Optional

LOGS_DIR = Path("logs")
FEATURE_DIR = Path("feature_store")
LEARNING_EVENTS_FILE = LOGS_DIR / "learning_events.jsonl"
HEALTH_LEARNING_SUMMARY = FEATURE_DIR / "health_learning_summary.json"

def _append_jsonl(path: Path, record: Dict[str, Any]):
    """Thread-safe append to JSONL file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    record["logged_at"] = datetime.utcnow().isoformat() + "Z"
    with open(path, "a") as f:
        f.write(json.dumps(record) + "\n")

def _now_iso() -> str:
    return datetime.utcnow().isoformat() + "Z"

def log_health_event(event_type: str, details: Dict[str, Any], outcome: Optional[str] = None):
    """
    Log a health/monitoring event for learning analysis.
    
    event_type: health_pulse, auto_remediation, gate_decision, kill_switch, position_close
    details: Context about what happened
    outcome: success, failure, pending (for later analysis)
    """
    event = {
        "ts": _now_iso(),
        "event_type": event_type,
        "details": details,
        "outcome": outcome
    }
    _append_jsonl(LEARNING_EVENTS_FILE, event)

def log_gate_decision(gate_name: str, symbol: str, direction: str, allowed: bool, reason: str, context: Dict = None):
    """Log gate decisions (streak filter, intelligence gate) for pattern analysis."""
    log_health_event("gate_decision", {
        "gate": gate_name,
        "symbol": symbol,
        "direction": direction,
        "allowed": allowed,
        "reason": reason,
        "context": context or {}
    }, outcome="allowed" if allowed else "blocked")

def log_auto_remediation(action: str, trigger: str, success: bool, before_state: Dict = None, after_state: Dict = None):
    """Log auto-remediation actions to learn which fixes work."""
    log_health_event("auto_remediation", {
        "action": action,
        "trigger": trigger,
        "before_state": before_state or {},
        "after_state": after_state or {}
    }, outcome="success" if success else "failure")

def log_position_outcome(position_id: str, symbol: str, direction: str, pnl: float, 
                         close_reason: str, hold_duration_s: float, entry_gates_passed: List[str]):
    """Log position outcomes with full context for attribution."""
    log_health_event("position_close", {
        "position_id": position_id,
        "symbol": symbol,
        "direction": direction,
        "pnl": pnl,
        "close_reason": close_reason,
        "hold_duration_s": hold_duration_s,
        "entry_gates_passed": entry_gates_passed,
        "was_profitable": pnl > 0
    }, outcome="profit" if pnl > 0 else "loss")

def compile_health_learning_summary(hours: int = 24) -> Dict[str, Any]:
    """
    Compile health/monitoring events into learning insights.
    Called by nightly learning engine.
    """
    cutoff = datetime.utcnow() - timedelta(hours=hours)
    
    events = []
    if LEARNING_EVENTS_FILE.exists():
        with open(LEARNING_EVENTS_FILE) as f:
            for line in f:
                try:
                    event = json.loads(line.strip())
                    event_ts = datetime.fromisoformat(event.get("ts", "").replace("Z", ""))
                    if event_ts >= cutoff:
                        events.append(event)
                except:
                    continue
    
    gate_decisions = [e for e in events if e.get("event_type") == "gate_decision"]
    position_closes = [e for e in events if e.get("event_type") == "position_close"]
    remediations = [e for e in events if e.get("event_type") == "auto_remediation"]
    health_pulses = [e for e in events if e.get("event_type") == "health_pulse"]
    
    gate_stats = {}
    for gate in ["streak_filter", "intelligence_gate"]:
        gate_events = [g for g in gate_decisions if g.get("details", {}).get("gate") == gate]
        allowed = [g for g in gate_events if g.get("details", {}).get("allowed")]
        blocked = [g for g in gate_events if not g.get("details", {}).get("allowed")]
        
        allowed_then_profit = 0
        allowed_then_loss = 0
        for a in allowed:
            sym = a.get("details", {}).get("symbol")
            dir_a = a.get("details", {}).get("direction")
            related_closes = [
                p for p in position_closes 
                if p.get("details", {}).get("symbol") == sym
            ]
            for close in related_closes:
                if close.get("outcome") == "profit":
                    allowed_then_profit += 1
                else:
                    allowed_then_loss += 1
        
        block_reasons = {}
        for b in blocked:
            reason = b.get("details", {}).get("reason", "unknown")
            block_reasons[reason] = block_reasons.get(reason, 0) + 1
        
        gate_stats[gate] = {
            "total_decisions": len(gate_events),
            "allowed_count": len(allowed),
            "blocked_count": len(blocked),
            "block_rate": len(blocked) / max(len(gate_events), 1),
            "allowed_then_profit": allowed_then_profit,
            "allowed_then_loss": allowed_then_loss,
            "gate_accuracy": allowed_then_profit / max(allowed_then_profit + allowed_then_loss, 1),
            "block_reasons": block_reasons
        }
    
    position_stats = {
        "total_closes": len(position_closes),
        "profits": len([p for p in position_closes if p.get("outcome") == "profit"]),
        "losses": len([p for p in position_closes if p.get("outcome") == "loss"]),
        "by_close_reason": {},
        "by_symbol": {}
    }
    
    for p in position_closes:
        reason = p.get("details", {}).get("close_reason", "unknown")
        position_stats["by_close_reason"][reason] = position_stats["by_close_reason"].get(reason, 0) + 1
        
        sym = p.get("details", {}).get("symbol", "unknown")
        if sym not in position_stats["by_symbol"]:
            position_stats["by_symbol"][sym] = {"wins": 0, "losses": 0, "total_pnl": 0}
        pnl = p.get("details", {}).get("pnl", 0)
        if pnl > 0:
            position_stats["by_symbol"][sym]["wins"] += 1
        else:
            position_stats["by_symbol"][sym]["losses"] += 1
        position_stats["by_symbol"][sym]["total_pnl"] += pnl
    
    remediation_stats = {
        "total_actions": len(remediations),
        "successes": len([r for r in remediations if r.get("outcome") == "success"]),
        "failures": len([r for r in remediations if r.get("outcome") == "failure"]),
        "by_action": {}
    }
    for r in remediations:
        action = r.get("details", {}).get("action", "unknown")
        if action not in remediation_stats["by_action"]:
            remediation_stats["by_action"][action] = {"success": 0, "failure": 0}
        if r.get("outcome") == "success":
            remediation_stats["by_action"][action]["success"] += 1
        else:
            remediation_stats["by_action"][action]["failure"] += 1
    
    recommendations = []
    
    for gate_name, stats in gate_stats.items():
        if stats["block_rate"] > 0.9:
            recommendations.append({
                "type": "gate_too_strict",
                "gate": gate_name,
                "action": "Consider relaxing thresholds",
                "evidence": f"Blocking {stats['block_rate']*100:.1f}% of signals"
            })
        if stats["gate_accuracy"] < 0.4:
            recommendations.append({
                "type": "gate_ineffective",
                "gate": gate_name,
                "action": "Gate is not improving outcomes - review logic",
                "evidence": f"Only {stats['gate_accuracy']*100:.1f}% of allowed trades profitable"
            })
    
    if remediation_stats["failures"] > remediation_stats["successes"]:
        recommendations.append({
            "type": "remediation_failing",
            "action": "Review auto-remediation logic",
            "evidence": f"{remediation_stats['failures']} failures vs {remediation_stats['successes']} successes"
        })
    
    summary = {
        "compiled_at": _now_iso(),
        "period_hours": hours,
        "total_events": len(events),
        "gate_statistics": gate_stats,
        "position_statistics": position_stats,
        "remediation_statistics": remediation_stats,
        "recommendations": recommendations
    }
    
    FEATURE_DIR.mkdir(parents=True, exist_ok=True)
    with open(HEALTH_LEARNING_SUMMARY, "w") as f:
        json.dump(summary, f, indent=2)
    
    return summary

def get_learning_recommendations() -> List[Dict[str, Any]]:
    """Get actionable recommendations from health learning analysis."""
    if HEALTH_LEARNING_SUMMARY.exists():
        with open(HEALTH_LEARNING_SUMMARY) as f:
            summary = json.load(f)
        return summary.get("recommendations", [])
    return []

def apply_learning_recommendations():
    """
    Auto-apply recommendations from health learning.
    Only applies low-risk optimizations; logs high-risk for review.
    """
    recommendations = get_learning_recommendations()
    applied = []
    deferred = []
    
    for rec in recommendations:
        if rec.get("type") == "gate_too_strict":
            deferred.append(rec)
        elif rec.get("type") == "gate_ineffective":
            deferred.append(rec)
        elif rec.get("type") == "remediation_failing":
            deferred.append(rec)
    
    return {
        "applied": applied,
        "deferred": deferred,
        "message": "Recommendations logged for operator review"
    }


if __name__ == "__main__":
    print("=" * 60)
    print("Health-to-Learning Bridge - Manual Run")
    print("=" * 60)
    
    summary = compile_health_learning_summary(hours=24)
    print(f"\nCompiled {summary['total_events']} events from last 24h")
    
    print("\n📊 Gate Statistics:")
    for gate, stats in summary.get("gate_statistics", {}).items():
        print(f"   {gate}: {stats['blocked_count']}/{stats['total_decisions']} blocked ({stats['block_rate']*100:.1f}%)")
        print(f"      Accuracy: {stats['gate_accuracy']*100:.1f}%")
    
    print("\n📈 Position Statistics:")
    pos_stats = summary.get("position_statistics", {})
    print(f"   Total: {pos_stats.get('total_closes', 0)} closes")
    print(f"   Wins: {pos_stats.get('profits', 0)} | Losses: {pos_stats.get('losses', 0)}")
    
    print("\n🔧 Auto-Remediation Statistics:")
    rem_stats = summary.get("remediation_statistics", {})
    print(f"   Success: {rem_stats.get('successes', 0)} | Failures: {rem_stats.get('failures', 0)}")
    
    print("\n💡 Recommendations:")
    for rec in summary.get("recommendations", []):
        print(f"   [{rec.get('type')}] {rec.get('action')}")
        print(f"      Evidence: {rec.get('evidence')}")
