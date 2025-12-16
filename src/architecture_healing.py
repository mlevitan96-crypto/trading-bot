#!/usr/bin/env python3
"""
Architecture-Specific Self-Healing
==================================
Self-healing functions for the new clean architecture components:
- SignalBus health
- StateMachine stuck signals
- ShadowExecutionEngine health
- DecisionTracker health
- PipelineMonitor health
"""

import time
import json
from pathlib import Path
from typing import Dict, List, Optional, Any
from datetime import datetime

try:
    from src.infrastructure.path_registry import PathRegistry
except ImportError:
    PathRegistry = None


class ArchitectureHealing:
    """
    Self-healing for new architecture components.
    
    Heals:
    - SignalBus: Corrupted event log, missing files
    - StateMachine: Stuck signals, invalid states
    - ShadowExecutionEngine: Missing outcomes log, corrupted data
    - DecisionTracker: Missing decisions log
    - PipelineMonitor: Health check failures
    """
    
    def __init__(self):
        self.healing_log = []
    
    def heal_signal_bus(self) -> Dict[str, Any]:
        """Heal SignalBus issues"""
        result = {"healed": False, "failed": False, "actions": []}
        
        try:
            if PathRegistry:
                bus_log = Path(PathRegistry.get_path("logs", "signal_bus.jsonl"))
            else:
                bus_log = Path("logs/signal_bus.jsonl")
            
            # Ensure log file exists
            if not bus_log.exists():
                bus_log.parent.mkdir(parents=True, exist_ok=True)
                bus_log.touch()
                result["actions"].append("Created signal_bus.jsonl")
                result["healed"] = True
            
            # Check for corrupted entries (non-JSON lines)
            if bus_log.exists() and bus_log.stat().st_size > 0:
                try:
                    corrupted_lines = 0
                    with open(bus_log, 'r') as f:
                        for line_num, line in enumerate(f, 1):
                            line = line.strip()
                            if not line:
                                continue
                            try:
                                json.loads(line)
                            except json.JSONDecodeError:
                                corrupted_lines += 1
                                result["actions"].append(f"Found corrupted line {line_num} in signal_bus.jsonl")
                    
                    if corrupted_lines > 0:
                        # Backup and clean corrupted lines
                        backup_path = bus_log.with_suffix('.jsonl.backup')
                        bus_log.rename(backup_path)
                        bus_log.touch()
                        
                        # Re-write valid lines
                        with open(backup_path, 'r') as f_in, open(bus_log, 'w') as f_out:
                            for line in f_in:
                                line = line.strip()
                                if not line:
                                    continue
                                try:
                                    json.loads(line)  # Validate
                                    f_out.write(line + '\n')
                                except json.JSONDecodeError:
                                    pass  # Skip corrupted line
                        
                        result["actions"].append(f"Cleaned {corrupted_lines} corrupted lines from signal_bus.jsonl")
                        result["healed"] = True
                except Exception as e:
                    result["actions"].append(f"Error checking signal_bus.jsonl: {e}")
                    result["failed"] = True
            
        except Exception as e:
            result["failed"] = True
            result["error"] = str(e)
        
        return result
    
    def heal_state_machine(self) -> Dict[str, Any]:
        """Heal StateMachine issues (stuck signals, invalid states)"""
        result = {"healed": False, "failed": False, "actions": []}
        
        try:
            from src.signal_state_machine import get_state_machine
            from src.signal_bus import SignalState
            
            state_machine = get_state_machine()
            
            # Auto-expire stuck signals
            stuck = state_machine.get_stuck_signals(max_age_seconds=3600)  # 1 hour
            if stuck:
                expired_count = state_machine.auto_expire_old_signals(max_age_seconds=7200)  # 2 hours
                if expired_count > 0:
                    result["actions"].append(f"Auto-expired {expired_count} stuck/old signals")
                    result["healed"] = True
            
            # Check for signals in invalid states
            # (StateMachine validates transitions, but we can check for orphaned states)
            from src.signal_bus import get_signal_bus
            bus = get_signal_bus()
            all_signals = bus.get_signals()
            
            invalid_states = []
            for signal_data in all_signals:
                state = signal_data.get("state")
                if state not in [s.value for s in SignalState]:
                    invalid_states.append(signal_data.get("signal_id"))
            
            if invalid_states:
                # Try to fix invalid states by expiring them
                for signal_id in invalid_states[:10]:  # Limit to 10 at a time
                    try:
                        state_machine.transition(signal_id, SignalState.EXPIRED, reason="Invalid state - auto-fix")
                        result["actions"].append(f"Fixed invalid state for signal {signal_id[:20]}")
                        result["healed"] = True
                    except:
                        pass
            
        except Exception as e:
            result["failed"] = True
            result["error"] = str(e)
        
        return result
    
    def heal_shadow_engine(self) -> Dict[str, Any]:
        """Heal ShadowExecutionEngine issues"""
        result = {"healed": False, "failed": False, "actions": []}
        
        try:
            if PathRegistry:
                outcomes_log = Path(PathRegistry.get_path("logs", "shadow_trade_outcomes.jsonl"))
            else:
                outcomes_log = Path("logs/shadow_trade_outcomes.jsonl")
            
            # Ensure log file exists
            if not outcomes_log.exists():
                outcomes_log.parent.mkdir(parents=True, exist_ok=True)
                outcomes_log.touch()
                result["actions"].append("Created shadow_trade_outcomes.jsonl")
                result["healed"] = True
            
            # Check if shadow engine is running
            try:
                from src.shadow_execution_engine import get_shadow_engine
                shadow_engine = get_shadow_engine()
                if not shadow_engine._running:
                    # Try to restart
                    shadow_engine.start()
                    result["actions"].append("Restarted ShadowExecutionEngine")
                    result["healed"] = True
            except Exception as e:
                result["actions"].append(f"Shadow engine check failed: {e}")
                # Non-critical, continue
            
        except Exception as e:
            result["failed"] = True
            result["error"] = str(e)
        
        return result
    
    def heal_decision_tracker(self) -> Dict[str, Any]:
        """Heal DecisionTracker issues"""
        result = {"healed": False, "failed": False, "actions": []}
        
        try:
            if PathRegistry:
                decisions_log = Path(PathRegistry.get_path("logs", "signal_decisions.jsonl"))
            else:
                decisions_log = Path("logs/signal_decisions.jsonl")
            
            # Ensure log file exists
            if not decisions_log.exists():
                decisions_log.parent.mkdir(parents=True, exist_ok=True)
                decisions_log.touch()
                result["actions"].append("Created signal_decisions.jsonl")
                result["healed"] = True
            
        except Exception as e:
            result["failed"] = True
            result["error"] = str(e)
        
        return result
    
    def heal_pipeline_monitor(self) -> Dict[str, Any]:
        """Heal PipelineMonitor issues"""
        result = {"healed": False, "failed": False, "actions": []}
        
        try:
            # PipelineMonitor is stateless, just verify it can be instantiated
            from src.signal_pipeline_monitor import get_pipeline_monitor
            monitor = get_pipeline_monitor()
            health = monitor.get_pipeline_health()
            
            # Check for critical issues
            if health.get("status") == "CRITICAL":
                stuck_count = health.get("stuck_count", 0)
                if stuck_count > 10:
                    # Try to auto-expire stuck signals
                    from src.signal_state_machine import get_state_machine
                    state_machine = get_state_machine()
                    expired = state_machine.auto_expire_old_signals(max_age_seconds=3600)  # 1 hour
                    if expired > 0:
                        result["actions"].append(f"Auto-expired {expired} stuck signals to fix pipeline health")
                        result["healed"] = True
            
        except Exception as e:
            result["failed"] = True
            result["error"] = str(e)
        
        return result
    
    def run_architecture_healing_cycle(self) -> Dict[str, Any]:
        """Run complete healing cycle for architecture components"""
        results = {
            "healed": [],
            "failed": [],
            "actions": []
        }
        
        # 1. SignalBus
        try:
            result = self.heal_signal_bus()
            if result["healed"]:
                results["healed"].append("signal_bus")
            if result["failed"]:
                results["failed"].append("signal_bus")
            results["actions"].extend(result.get("actions", []))
        except Exception as e:
            results["failed"].append("signal_bus")
            results["actions"].append(f"SignalBus healing error: {e}")
        
        # 2. StateMachine
        try:
            result = self.heal_state_machine()
            if result["healed"]:
                results["healed"].append("state_machine")
            if result["failed"]:
                results["failed"].append("state_machine")
            results["actions"].extend(result.get("actions", []))
        except Exception as e:
            results["failed"].append("state_machine")
            results["actions"].append(f"StateMachine healing error: {e}")
        
        # 3. ShadowEngine
        try:
            result = self.heal_shadow_engine()
            if result["healed"]:
                results["healed"].append("shadow_engine")
            if result["failed"]:
                results["failed"].append("shadow_engine")
            results["actions"].extend(result.get("actions", []))
        except Exception as e:
            results["failed"].append("shadow_engine")
            results["actions"].append(f"ShadowEngine healing error: {e}")
        
        # 4. DecisionTracker
        try:
            result = self.heal_decision_tracker()
            if result["healed"]:
                results["healed"].append("decision_tracker")
            if result["failed"]:
                results["failed"].append("decision_tracker")
            results["actions"].extend(result.get("actions", []))
        except Exception as e:
            results["failed"].append("decision_tracker")
            results["actions"].append(f"DecisionTracker healing error: {e}")
        
        # 5. PipelineMonitor
        try:
            result = self.heal_pipeline_monitor()
            if result["healed"]:
                results["healed"].append("pipeline_monitor")
            if result["failed"]:
                results["failed"].append("pipeline_monitor")
            results["actions"].extend(result.get("actions", []))
        except Exception as e:
            results["failed"].append("pipeline_monitor")
            results["actions"].append(f"PipelineMonitor healing error: {e}")
        
        return results


# Global singleton
_architecture_healing_instance = None


def get_architecture_healing() -> ArchitectureHealing:
    """Get global ArchitectureHealing instance"""
    global _architecture_healing_instance
    
    if _architecture_healing_instance is None:
        _architecture_healing_instance = ArchitectureHealing()
    return _architecture_healing_instance

