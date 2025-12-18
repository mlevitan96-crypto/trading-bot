"""
Healing Escalation Tracker - Monitors heal counts and escalates when thresholds exceeded.

Tracks heal counts in rolling 24h window by category:
- files_created
- files_repaired
- directories_created
- heartbeats_reset
- locks_cleared
- orphans_killed

If any category exceeds threshold (3-5), activates soft kill-switch:
- Block new entries
- Continue managing exits only
- Raise structural issue alert
"""

import os
import json
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple
from datetime import datetime, timedelta
from collections import defaultdict, deque

from src.infrastructure.path_registry import PathRegistry


# Escalation thresholds
HEAL_COUNT_THRESHOLD = 5  # Max heals per category in 24h window
SOFT_KILL_SWITCH_THRESHOLD = 3  # Lower threshold for soft kill-switch (block entries)

# State files
ESCALATION_LOG = PathRegistry.LOGS_DIR / "healing_escalation_log.jsonl"
ESCALATION_STATE = PathRegistry.FEATURE_STORE_DIR / "healing_escalation_state.json"


class HealingEscalationTracker:
    """
    Tracks healing counts and escalates when thresholds exceeded.
    """
    
    def __init__(self):
        self.escalation_log = ESCALATION_LOG
        self.escalation_state_file = ESCALATION_STATE
        self.escalation_log.parent.mkdir(parents=True, exist_ok=True)
        self.escalation_state_file.parent.mkdir(parents=True, exist_ok=True)
        
        # Rolling window (24 hours)
        self.window_hours = 24
        self.heal_history = deque()  # (timestamp, category, count)
        
    def load_state(self) -> Dict[str, Any]:
        """Load escalation state."""
        if self.escalation_state_file.exists():
            try:
                with open(self.escalation_state_file, 'r') as f:
                    return json.load(f)
            except Exception as e:
                print(f"⚠️ [ESCALATION] Failed to load state: {e}")
                return {}
        return {
            "heal_counts_24h": {},
            "escalation_status": "normal",
            "soft_kill_switch_active": False,
            "last_escalation": None,
            "escalation_history": []
        }
    
    def save_state(self, state: Dict[str, Any]):
        """Save escalation state."""
        try:
            with open(self.escalation_state_file, 'w') as f:
                json.dump(state, f, indent=2)
        except Exception as e:
            print(f"⚠️ [ESCALATION] Failed to save state: {e}")
    
    def log_escalation_event(self, category: str, count: int, threshold: int, action: str):
        """Log escalation event to JSONL."""
        event = {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "category": category,
            "count": count,
            "threshold": threshold,
            "action": action,
            "severity": "high" if count >= HEAL_COUNT_THRESHOLD else "medium"
        }
        
        try:
            with open(self.escalation_log, 'a') as f:
                f.write(json.dumps(event) + '\n')
        except Exception as e:
            print(f"⚠️ [ESCALATION] Failed to log event: {e}")
    
    def update_heal_counts(self, healed_components: List[str]):
        """
        Update heal counts from healing cycle.
        
        Args:
            healed_components: List of component names that were healed (e.g., ["signal_engine", "file_integrity"])
        """
        state = self.load_state()
        now = datetime.utcnow()
        cutoff_time = now - timedelta(hours=self.window_hours)
        
        # Initialize counts
        counts_24h = defaultdict(int)
        
        # Process healed components (count each as one heal in its category)
        # Group components into categories
        component_to_category = {
            "signal_engine": "files_repaired",
            "decision_engine": "files_repaired",
            "safety_layer": "files_repaired",
            "exit_gates": "files_repaired",
            "trade_execution": "files_repaired",
            "heartbeat": "heartbeats_reset",
            "feature_store": "directories_created",
            "signal_weights": "files_created",
            "file_integrity": "files_repaired",
            "architecture_components": "files_repaired",
            "self_healing": "files_repaired"
        }
        
        # Count heals by category
        for component in healed_components:
            category = component_to_category.get(component, "files_repaired")  # Default category
            # Add to history
            self.heal_history.append((now.timestamp(), category, 1))
        
        # Clean old entries from history
        while self.heal_history and self.heal_history[0][0] < cutoff_time.timestamp():
            self.heal_history.popleft()
        
        # Recalculate counts from history window
        counts_24h = defaultdict(int)
        for ts, category, count in self.heal_history:
            if ts >= cutoff_time.timestamp():
                counts_24h[category] += count
        
        state["heal_counts_24h"] = dict(counts_24h)
        state["last_updated"] = now.isoformat() + "Z"
        
        # Check for escalation
        escalated = False
        soft_kill_active = state.get("soft_kill_switch_active", False)
        
        for category, count in counts_24h.items():
            if count >= SOFT_KILL_SWITCH_THRESHOLD and not soft_kill_active:
                # Activate soft kill-switch
                soft_kill_active = True
                escalated = True
                action = "soft_kill_switch_activated"
                
                print(f"🚨 [ESCALATION] Soft kill-switch ACTIVATED: {category} has {count} heals in 24h (threshold: {SOFT_KILL_SWITCH_THRESHOLD})")
                print(f"   🔒 Blocking new entries. Managing exits only.")
                
                self.log_escalation_event(category, count, SOFT_KILL_SWITCH_THRESHOLD, action)
                
                state["escalation_status"] = "soft_kill_switch"
                state["soft_kill_switch_active"] = True
                state["escalation_history"].append({
                    "timestamp": now.isoformat() + "Z",
                    "category": category,
                    "count": count,
                    "action": action
                })
                
            elif count >= HEAL_COUNT_THRESHOLD:
                # Critical escalation
                escalated = True
                action = "structural_issue_alert"
                
                print(f"🚨 [ESCALATION] CRITICAL: {category} has {count} heals in 24h (threshold: {HEAL_COUNT_THRESHOLD})")
                print(f"   ⚠️  Structural issue detected - manual review recommended")
                
                self.log_escalation_event(category, count, HEAL_COUNT_THRESHOLD, action)
                
                if state["escalation_status"] != "critical":
                    state["escalation_status"] = "critical"
                    state["escalation_history"].append({
                        "timestamp": now.isoformat() + "Z",
                        "category": category,
                        "count": count,
                        "action": action
                    })
        
        # Auto-recover if counts drop below threshold
        if soft_kill_active:
            max_count = max(counts_24h.values(), default=0)
            if max_count < SOFT_KILL_SWITCH_THRESHOLD:
                print(f"✅ [ESCALATION] Soft kill-switch DEACTIVATED: Max heal count {max_count} below threshold {SOFT_KILL_SWITCH_THRESHOLD}")
                soft_kill_active = False
                state["soft_kill_switch_active"] = False
                state["escalation_status"] = "normal"
                action = "soft_kill_switch_deactivated"
                self.log_escalation_event("recovery", max_count, SOFT_KILL_SWITCH_THRESHOLD, action)
        
        if not escalated and state.get("escalation_status") == "critical":
            max_count = max(counts_24h.values(), default=0)
            if max_count < HEAL_COUNT_THRESHOLD:
                state["escalation_status"] = "normal"
        
        state["soft_kill_switch_active"] = soft_kill_active
        state["last_escalation"] = state["escalation_history"][-1] if state["escalation_history"] else None
        
        self.save_state(state)
        
        return {
            "escalated": escalated,
            "soft_kill_switch_active": soft_kill_active,
            "escalation_status": state["escalation_status"],
            "counts_24h": dict(counts_24h)
        }
    
    def is_soft_kill_switch_active(self) -> bool:
        """Check if soft kill-switch is active (block entries, continue exits)."""
        state = self.load_state()
        return state.get("soft_kill_switch_active", False)
    
    def get_escalation_status(self) -> Dict[str, Any]:
        """Get current escalation status."""
        state = self.load_state()
        return {
            "escalation_status": state.get("escalation_status", "normal"),
            "soft_kill_switch_active": state.get("soft_kill_switch_active", False),
            "heal_counts_24h": state.get("heal_counts_24h", {}),
            "last_escalation": state.get("last_escalation"),
            "thresholds": {
                "soft_kill_switch": SOFT_KILL_SWITCH_THRESHOLD,
                "critical": HEAL_COUNT_THRESHOLD
            }
        }


def track_healing_cycle(healed_components: List[str]) -> Dict[str, Any]:
    """
    Track healing cycle and check for escalation.
    
    Main entry point - call after each healing cycle.
    
    Args:
        healed_components: List of component names that were healed
    
    Returns:
        Escalation result dict
    """
    tracker = HealingEscalationTracker()
    return tracker.update_heal_counts(healed_components)


def is_soft_kill_switch_active() -> bool:
    """Check if soft kill-switch is active (for blocking entries)."""
    tracker = HealingEscalationTracker()
    return tracker.is_soft_kill_switch_active()


def get_escalation_status() -> Dict[str, Any]:
    """Get current escalation status."""
    tracker = HealingEscalationTracker()
    return tracker.get_escalation_status()


if __name__ == "__main__":
    # Test escalation tracking
    print("🧪 Testing Healing Escalation Tracker\n")
    
    # Simulate healing cycles
    tracker = HealingEscalationTracker()
    
    test_stats = [
        {"files_created": 1, "files_repaired": 0},
        {"files_created": 2, "files_repaired": 1},
        {"files_created": 1, "files_repaired": 0},
        {"files_created": 1, "files_repaired": 1},  # Should trigger soft kill-switch (4 files_created)
    ]
    
    for i, stats in enumerate(test_stats, 1):
        print(f"Cycle {i}: {stats}")
        result = tracker.update_heal_counts(stats)
        print(f"  Status: {result['escalation_status']}")
        print(f"  Soft kill-switch: {result['soft_kill_switch_active']}")
        print(f"  Counts: {result['counts_24h']}")
        print()
