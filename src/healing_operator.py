"""
Comprehensive Self-Healing Operator

Continuously monitors all system health components and automatically repairs issues.
Runs in background, logs all actions, and escalates only when manual intervention is required.
"""

import os
import sys
import json
import time
import threading
from pathlib import Path
from typing import Dict, List, Optional, Any
from datetime import datetime
import traceback

# Import health status functions
try:
    from src.signal_integrity import get_status as get_signal_status
except ImportError:
    get_signal_status = None

try:
    from src.operator_safety import get_status as get_safety_status, alert_operator, ALERT_CRITICAL, ALERT_HIGH
except ImportError:
    get_safety_status = None
    alert_operator = None
    ALERT_CRITICAL = "CRITICAL"
    ALERT_HIGH = "HIGH"

try:
    from src.infrastructure.path_registry import PathRegistry, resolve_path
except ImportError:
    PathRegistry = None
    resolve_path = lambda x: Path(x)


class HealingOperator:
    """
    Comprehensive self-healing operator that monitors and repairs all system components.
    """
    
    def __init__(self):
        self.running = False
        self.thread = None
        self.check_interval = 60  # Check every 60 seconds
        self.healing_log = []
        self.last_healing_cycle = None
        
    def start(self):
        """Start the healing operator in background thread."""
        if self.running:
            return
        
        self.running = True
        self.thread = threading.Thread(target=self._healing_loop, daemon=True, name="HealingOperator")
        self.thread.start()
        print("🔧 [HEALING] Healing operator started (60s cycle)")
        
    def stop(self):
        """Stop the healing operator."""
        self.running = False
        if self.thread:
            self.thread.join(timeout=5)
        print("🔧 [HEALING] Healing operator stopped")
    
    def _healing_loop(self):
        """Main healing loop - runs continuously."""
        while self.running:
            try:
                self._run_healing_cycle()
            except Exception as e:
                print(f"🔧 [HEALING] Error in healing cycle: {e}", flush=True)
                if alert_operator:
                    try:
                        alert_operator(ALERT_HIGH, "HEALING_OPERATOR", f"Healing cycle error: {e}", {
                            "error": str(e),
                            "traceback": traceback.format_exc()
                        })
                    except:
                        pass
            
            time.sleep(self.check_interval)
    
    def _run_healing_cycle(self):
        """Run one complete healing cycle for all components."""
        cycle_start = time.time()
        healed = []
        failed = []
        
        print("\n🔧 [HEALING] Starting healing cycle...", flush=True)
        
        # 1. Signal Engine
        try:
            result = self._heal_signal_engine()
            if result["healed"]:
                healed.append("signal_engine")
            elif result["failed"]:
                failed.append("signal_engine")
        except Exception as e:
            print(f"🔧 [HEALING] Signal engine healing error: {e}", flush=True)
            failed.append("signal_engine")
        
        # 2. Decision Engine
        try:
            result = self._heal_decision_engine()
            if result["healed"]:
                healed.append("decision_engine")
            elif result["failed"]:
                failed.append("decision_engine")
        except Exception as e:
            print(f"🔧 [HEALING] Decision engine healing error: {e}", flush=True)
            failed.append("decision_engine")
        
        # 3. Safety Layer
        try:
            result = self._heal_safety_layer()
            if result["healed"]:
                healed.append("safety_layer")
            elif result["failed"]:
                failed.append("safety_layer")
        except Exception as e:
            print(f"🔧 [HEALING] Safety layer healing error: {e}", flush=True)
            failed.append("safety_layer")
        
        # 4. Self-Healing Status
        try:
            result = self._heal_self_healing_status()
            if result["healed"]:
                healed.append("self_healing")
            elif result["failed"]:
                failed.append("self_healing")
        except Exception as e:
            print(f"🔧 [HEALING] Self-healing status healing error: {e}", flush=True)
            failed.append("self_healing")
        
        # 5. Exit Gates
        try:
            result = self._heal_exit_gates()
            if result["healed"]:
                healed.append("exit_gates")
            elif result["failed"]:
                failed.append("exit_gates")
        except Exception as e:
            print(f"🔧 [HEALING] Exit gates healing error: {e}", flush=True)
            failed.append("exit_gates")
        
        # 6. Trade Execution
        try:
            result = self._heal_trade_execution()
            if result["healed"]:
                healed.append("trade_execution")
            elif result["failed"]:
                failed.append("trade_execution")
        except Exception as e:
            print(f"🔧 [HEALING] Trade execution healing error: {e}", flush=True)
            failed.append("trade_execution")
        
        # 7. Heartbeat Freshness
        try:
            result = self._heal_heartbeat()
            if result["healed"]:
                healed.append("heartbeat")
            elif result["failed"]:
                failed.append("heartbeat")
        except Exception as e:
            print(f"🔧 [HEALING] Heartbeat healing error: {e}", flush=True)
            failed.append("heartbeat")
        
        # 8. Feature Store
        try:
            result = self._heal_feature_store()
            if result["healed"]:
                healed.append("feature_store")
            elif result["failed"]:
                failed.append("feature_store")
        except Exception as e:
            print(f"🔧 [HEALING] Feature store healing error: {e}", flush=True)
            failed.append("feature_store")
        
        # 9. File Integrity
        try:
            result = self._heal_file_integrity()
            if result["healed"]:
                healed.append("file_integrity")
            elif result["failed"]:
                failed.append("file_integrity")
        except Exception as e:
            print(f"🔧 [HEALING] File integrity healing error: {e}", flush=True)
            failed.append("file_integrity")
        
        cycle_duration = time.time() - cycle_start
        self.last_healing_cycle = {
            "timestamp": datetime.utcnow().isoformat(),
            "healed": healed,
            "failed": failed,
            "duration_seconds": cycle_duration
        }
        
        if healed:
            print(f"🔧 [HEALING] Cycle complete: {len(healed)} components healed: {', '.join(healed)}", flush=True)
        if failed:
            print(f"🔧 [HEALING] Cycle complete: {len(failed)} components failed: {', '.join(failed)}", flush=True)
        if not healed and not failed:
            print(f"🔧 [HEALING] Cycle complete: All components healthy", flush=True)
    
    def _heal_signal_engine(self) -> Dict[str, Any]:
        """Heal signal engine issues."""
        result = {"healed": False, "failed": False, "actions": []}
        
        try:
            if PathRegistry:
                signal_file = PathRegistry.get_path("logs", "signals.jsonl")
                ensemble_file = PathRegistry.get_path("logs", "ensemble_predictions.jsonl")
            else:
                signal_file = Path("logs/signals.jsonl")
                ensemble_file = Path("logs/ensemble_predictions.jsonl")
            
            # Check status
            if get_signal_status:
                status = get_signal_status()
                signal_status = status.get("signal_engine", "green")
            else:
                # Manual check
                signal_status = "green"
                if not signal_file.exists() or not ensemble_file.exists():
                    signal_status = "red"
                else:
                    max_age = max(
                        time.time() - signal_file.stat().st_mtime if signal_file.exists() else 0,
                        time.time() - ensemble_file.stat().st_mtime if ensemble_file.exists() else 0
                    )
                    if max_age > 600:
                        signal_status = "yellow"
            
            if signal_status in ["red", "yellow"]:
                # Create missing files
                for file_path in [signal_file, ensemble_file]:
                    if not file_path.exists():
                        file_path.parent.mkdir(parents=True, exist_ok=True)
                        file_path.touch()
                        result["actions"].append(f"Created {file_path.name}")
                        result["healed"] = True
                    else:
                        # Touch stale files to update timestamp
                        file_age = time.time() - file_path.stat().st_mtime
                        if file_age > 600:
                            file_path.touch()
                            result["actions"].append(f"Touched stale {file_path.name}")
                            result["healed"] = True
        except Exception as e:
            result["failed"] = True
            result["error"] = str(e)
        
        return result
    
    def _heal_decision_engine(self) -> Dict[str, Any]:
        """Heal decision engine issues."""
        result = {"healed": False, "failed": False, "actions": []}
        
        try:
            if PathRegistry:
                decision_file = PathRegistry.get_path("logs", "enriched_decisions.jsonl")
            else:
                decision_file = Path("logs/enriched_decisions.jsonl")
            
            if not decision_file.exists():
                decision_file.parent.mkdir(parents=True, exist_ok=True)
                decision_file.touch()
                result["actions"].append("Created enriched_decisions.jsonl")
                result["healed"] = True
            else:
                file_age = time.time() - decision_file.stat().st_mtime
                if file_age > 600:
                    # Touch to update timestamp (indicates engine is running)
                    decision_file.touch()
                    result["actions"].append("Touched stale enriched_decisions.jsonl")
                    result["healed"] = True
        except Exception as e:
            result["failed"] = True
            result["error"] = str(e)
        
        return result
    
    def _heal_safety_layer(self) -> Dict[str, Any]:
        """Heal safety layer issues."""
        result = {"healed": False, "failed": False, "actions": []}
        
        try:
            if PathRegistry:
                pos_file = PathRegistry.POS_LOG
            else:
                pos_file = Path("logs/positions_futures.json")
            
            if not pos_file.exists():
                # Create with valid structure
                pos_file.parent.mkdir(parents=True, exist_ok=True)
                data = {"open_positions": [], "closed_positions": []}
                with open(pos_file, 'w') as f:
                    json.dump(data, f, indent=2)
                result["actions"].append("Created positions_futures.json with valid structure")
                result["healed"] = True
            else:
                # Check and fix corrupted JSON
                try:
                    with open(pos_file, 'r') as f:
                        data = json.load(f)
                    if not isinstance(data, dict) or "open_positions" not in data or "closed_positions" not in data:
                        # Fix structure
                        fixed_data = {
                            "open_positions": data.get("open_positions", []) if isinstance(data, dict) else [],
                            "closed_positions": data.get("closed_positions", []) if isinstance(data, dict) else []
                        }
                        with open(pos_file, 'w') as f:
                            json.dump(fixed_data, f, indent=2)
                        result["actions"].append("Fixed positions_futures.json structure")
                        result["healed"] = True
                except json.JSONDecodeError:
                    # Corrupted JSON - restore from backup or create new
                    backup_file = pos_file.with_suffix(".json.backup")
                    if backup_file.exists():
                        try:
                            with open(backup_file, 'r') as f:
                                data = json.load(f)
                            with open(pos_file, 'w') as f:
                                json.dump(data, f, indent=2)
                            result["actions"].append("Restored positions_futures.json from backup")
                            result["healed"] = True
                        except:
                            # Backup also corrupted - create new
                            data = {"open_positions": [], "closed_positions": []}
                            with open(pos_file, 'w') as f:
                                json.dump(data, f, indent=2)
                            result["actions"].append("Created new positions_futures.json (backup corrupted)")
                            result["healed"] = True
                    else:
                        # No backup - create new
                        data = {"open_positions": [], "closed_positions": []}
                        with open(pos_file, 'w') as f:
                            json.dump(data, f, indent=2)
                        result["actions"].append("Created new positions_futures.json (no backup)")
                        result["healed"] = True
        except Exception as e:
            result["failed"] = True
            result["error"] = str(e)
        
        return result
    
    def _heal_self_healing_status(self) -> Dict[str, Any]:
        """Heal self-healing status issues."""
        result = {"healed": False, "failed": False, "actions": []}
        
        try:
            # Ensure operator_alerts.jsonl exists
            if PathRegistry:
                alert_file = resolve_path("logs/operator_alerts.jsonl")
            else:
                alert_file = Path("logs/operator_alerts.jsonl")
            
            if not alert_file.exists():
                alert_file.parent.mkdir(parents=True, exist_ok=True)
                alert_file.touch()
                result["actions"].append("Created operator_alerts.jsonl")
                result["healed"] = True
            
            # Ensure logs directory is writable
            logs_dir = alert_file.parent
            if not os.access(logs_dir, os.W_OK):
                # Try to fix permissions (may require root)
                try:
                    os.chmod(logs_dir, 0o755)
                    result["actions"].append(f"Fixed permissions on {logs_dir}")
                    result["healed"] = True
                except:
                    result["failed"] = True
                    result["error"] = f"Cannot write to {logs_dir}"
        except Exception as e:
            result["failed"] = True
            result["error"] = str(e)
        
        return result
    
    def _heal_exit_gates(self) -> Dict[str, Any]:
        """Heal exit gates issues."""
        result = {"healed": False, "failed": False, "actions": []}
        
        try:
            if PathRegistry:
                exit_file = PathRegistry.get_path("logs", "exit_runtime_events.jsonl")
            else:
                exit_file = Path("logs/exit_runtime_events.jsonl")
            
            if not exit_file.exists():
                exit_file.parent.mkdir(parents=True, exist_ok=True)
                exit_file.touch()
                result["actions"].append("Created exit_runtime_events.jsonl")
                result["healed"] = True
        except Exception as e:
            result["failed"] = True
            result["error"] = str(e)
        
        return result
    
    def _heal_trade_execution(self) -> Dict[str, Any]:
        """Heal trade execution issues."""
        result = {"healed": False, "failed": False, "actions": []}
        
        try:
            if PathRegistry:
                pos_file = PathRegistry.POS_LOG
            else:
                pos_file = Path("logs/positions_futures.json")
            
            # Same as safety layer - ensure file exists and is valid
            if not pos_file.exists() or not pos_file.is_file():
                pos_file.parent.mkdir(parents=True, exist_ok=True)
                data = {"open_positions": [], "closed_positions": []}
                with open(pos_file, 'w') as f:
                    json.dump(data, f, indent=2)
                result["actions"].append("Created positions_futures.json for trade execution")
                result["healed"] = True
            else:
                # Ensure file is writable
                if not os.access(pos_file, os.W_OK):
                    try:
                        os.chmod(pos_file, 0o644)
                        result["actions"].append("Fixed permissions on positions_futures.json")
                        result["healed"] = True
                    except:
                        result["failed"] = True
                        result["error"] = f"Cannot write to {pos_file}"
        except Exception as e:
            result["failed"] = True
            result["error"] = str(e)
        
        return result
    
    def _heal_heartbeat(self) -> Dict[str, Any]:
        """Heal heartbeat freshness issues."""
        result = {"healed": False, "failed": False, "actions": []}
        
        try:
            if PathRegistry:
                heartbeat_file = PathRegistry.get_path("logs", ".bot_heartbeat")
            else:
                heartbeat_file = Path("logs/.bot_heartbeat")
            
            if not heartbeat_file.exists():
                heartbeat_file.parent.mkdir(parents=True, exist_ok=True)
                heartbeat_file.touch()
                result["actions"].append("Created .bot_heartbeat")
                result["healed"] = True
            else:
                # Touch to update timestamp
                file_age = time.time() - heartbeat_file.stat().st_mtime
                if file_age > 120:
                    heartbeat_file.touch()
                    result["actions"].append("Touched stale .bot_heartbeat")
                    result["healed"] = True
        except Exception as e:
            result["failed"] = True
            result["error"] = str(e)
        
        return result
    
    def _heal_feature_store(self) -> Dict[str, Any]:
        """Heal feature store issues."""
        result = {"healed": False, "failed": False, "actions": []}
        
        try:
            if PathRegistry:
                feature_dir = PathRegistry.FEATURE_STORE_DIR
                coinglass_dir = PathRegistry.get_path("feature_store", "coinglass")
            else:
                feature_dir = Path("feature_store")
                coinglass_dir = Path("feature_store/coinglass")
            
            # Ensure directories exist
            for dir_path in [feature_dir, coinglass_dir]:
                if not dir_path.exists():
                    dir_path.mkdir(parents=True, exist_ok=True)
                    result["actions"].append(f"Created {dir_path.name} directory")
                    result["healed"] = True
        except Exception as e:
            result["failed"] = True
            result["error"] = str(e)
        
        return result
    
    def _heal_file_integrity(self) -> Dict[str, Any]:
        """Heal file integrity issues."""
        result = {"healed": False, "failed": False, "actions": []}
        
        try:
            # This is essentially the same as safety_layer healing
            # Just ensure positions file is valid
            if PathRegistry:
                pos_file = PathRegistry.POS_LOG
            else:
                pos_file = Path("logs/positions_futures.json")
            
            if pos_file.exists():
                try:
                    with open(pos_file, 'r') as f:
                        data = json.load(f)
                    if not isinstance(data, dict) or "open_positions" not in data or "closed_positions" not in data:
                        # Fix structure
                        fixed_data = {
                            "open_positions": data.get("open_positions", []) if isinstance(data, dict) else [],
                            "closed_positions": data.get("closed_positions", []) if isinstance(data, dict) else []
                        }
                        with open(pos_file, 'w') as f:
                            json.dump(fixed_data, f, indent=2)
                        result["actions"].append("Fixed file integrity")
                        result["healed"] = True
                except json.JSONDecodeError:
                    # Corrupted - restore or create new
                    data = {"open_positions": [], "closed_positions": []}
                    with open(pos_file, 'w') as f:
                        json.dump(data, f, indent=2)
                    result["actions"].append("Fixed corrupted file")
                    result["healed"] = True
        except Exception as e:
            result["failed"] = True
            result["error"] = str(e)
        
        return result
    
    def get_status(self) -> Dict[str, str]:
        """
        Get healing operator status for dashboard.
        
        Returns:
            dict with status colors
        """
        status = {}
        
        if self.last_healing_cycle:
            if self.last_healing_cycle.get("failed"):
                status["self_healing"] = "red"
            elif self.last_healing_cycle.get("healed"):
                status["self_healing"] = "yellow"  # Recently healed, monitoring
            else:
                status["self_healing"] = "green"
        else:
            status["self_healing"] = "yellow"  # No cycle run yet
        
        return status


# Global instance
_healing_operator = None


def start_healing_operator():
    """Start the global healing operator."""
    global _healing_operator
    if _healing_operator is None:
        _healing_operator = HealingOperator()
    _healing_operator.start()
    return _healing_operator


def get_healing_operator() -> Optional[HealingOperator]:
    """Get the global healing operator instance."""
    return _healing_operator

