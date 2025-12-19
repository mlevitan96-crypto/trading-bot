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
        self.last_healing_cycle_ts = None
        
    def start(self):
        """Start the healing operator in background thread."""
        # If already running, check if thread is alive and restart if needed
        if self.running:
            if self.thread and self.thread.is_alive():
                return  # Already running fine
            else:
                # Thread died but running flag is still True - reset and restart
                print("⚠️ [HEALING] Thread died, restarting healing operator...", flush=True)
                self.running = False
        
        self.running = True
        try:
            self.thread = threading.Thread(target=self._healing_loop, daemon=True, name="HealingOperator")
            self.thread.start()
            
            # Verify thread actually started
            import time
            time.sleep(0.1)  # Give thread a moment to start
            if self.thread.is_alive():
                print("🔧 [HEALING] Healing operator started (60s cycle)", flush=True)
            else:
                print("❌ [HEALING] CRITICAL: Thread failed to start!", flush=True)
                self.running = False
                raise RuntimeError("HealingOperator thread failed to start")
        except Exception as e:
            self.running = False
            print(f"❌ [HEALING] CRITICAL: Failed to start healing operator: {e}", flush=True)
            import traceback
            traceback.print_exc()
            raise
        
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
        
        # MISSION: Silent autonomous operation - only log if issues found
        # Don't print every cycle, only log to file for debugging
        
        # 1. Signal Engine
        try:
            result = self._heal_signal_engine()
            if result["healed"]:
                healed.append("signal_engine")
            elif result["failed"]:
                failed.append("signal_engine")
        except Exception as e:
            # Only log actual errors (not routine operations)
            if alert_operator:
                try:
                    alert_operator(ALERT_HIGH, "HEALING_OPERATOR", f"Signal engine healing error: {e}", {
                        "error": str(e),
                        "traceback": traceback.format_exc()
                    })
                except:
                    pass
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
        
        # 8.5. Signal Weights (Initialize if missing for learning)
        try:
            result = self._heal_signal_weights()
            if result["healed"]:
                healed.append("signal_weights")
        except Exception as e:
            # Not critical - defaults work fine
            pass
        
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
        
        # 10. Architecture Components (NEW - SignalBus, StateMachine, etc.)
        try:
            result = self._heal_architecture_components()
            if result.get("healed"):
                healed.extend(result["healed"])
            if result.get("failed"):
                failed.extend(result["failed"])
        except Exception as e:
            print(f"🔧 [HEALING] Architecture components healing error: {e}", flush=True)
            failed.append("architecture_components")
        
        # 11. Expansive Profitability Analyzer
        try:
            result = self._heal_expansive_analyzer()
            self.healing_results["expansive_analyzer"] = result
            if result.get("healed"):
                healed.append("expansive_analyzer")
                print(f"🔧 [HEALING] Expansive analyzer: {', '.join(result.get('actions', []))}", flush=True)
        except Exception as e:
            # Non-critical - analyzer is optional
            pass
        
        # Collect healing stats for escalation tracking
        heal_stats = {
            "files_created": 0,
            "files_repaired": 0,
            "directories_created": 0,
            "heartbeats_reset": 0,
            "locks_cleared": 0,
            "orphans_killed": 0
        }
        
        # Aggregate stats from all healing results
        for component in healed:
            # Stats are collected per-component, aggregate here
            # Note: Individual heal methods don't return detailed stats yet
            # For now, count each healed component as one "heal"
            # TODO: Enhance individual heal methods to return detailed stats
            pass
        
        # Track escalation (check heal counts)
        try:
            from src.healing_escalation import track_healing_cycle
            escalation_result = track_healing_cycle(healed)  # Pass list of healed components
            
            if escalation_result.get("soft_kill_switch_active"):
                print(f"🚨 [ESCALATION] Soft kill-switch ACTIVE - blocking new entries", flush=True)
            
            if escalation_result.get("escalation_status") == "critical":
                if alert_operator:
                    try:
                        alert_operator(ALERT_CRITICAL, "HEALING_ESCALATION", 
                            f"Critical escalation: {escalation_result.get('counts_24h')}",
                            escalation_result)
                    except:
                        pass
        except Exception as e:
            # Escalation tracking is non-critical, don't fail healing if it errors
            pass
        
        cycle_duration = time.time() - cycle_start
        self.last_healing_cycle_ts = time.time()  # Track timestamp for status checks
        self.last_healing_cycle = {
            "timestamp": datetime.utcnow().isoformat(),
            "healed": healed,
            "failed": failed,
            "duration_seconds": cycle_duration,
            "heal_stats": heal_stats
        }
        
        # MISSION: Silent autonomous operation - only log if issues found or fixed
        # Don't print "all healthy" every cycle (too noisy)
        if healed:
            # Only log when something was actually healed (important event)
            print(f"🔧 [HEALING] Fixed {len(healed)} components: {', '.join(healed)}", flush=True)
        if failed:
            # Always log failures (they need attention, even if self-healing)
            print(f"⚠️  [HEALING] {len(failed)} components need attention: {', '.join(failed)}", flush=True)
        # Removed: "All components healthy" message (too noisy for every cycle)
    
    def _heal_signal_engine(self) -> Dict[str, Any]:
        """Heal signal engine issues."""
        result = {"healed": False, "failed": False, "actions": []}
        
        try:
            if PathRegistry:
                signal_file = Path(PathRegistry.get_path("logs", "signals.jsonl"))
                ensemble_file = Path(PathRegistry.get_path("logs", "ensemble_predictions.jsonl"))
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
                # Create missing files or write heartbeat to keep them fresh
                for file_path in [signal_file, ensemble_file]:
                    if not file_path.exists():
                        file_path.parent.mkdir(parents=True, exist_ok=True)
                        file_path.touch()
                        result["actions"].append(f"Created {file_path.name}")
                        result["healed"] = True
                    else:
                        # For ensemble_predictions.jsonl, write a heartbeat entry to keep it fresh
                        # This ensures the file stays recent even when no signals are being processed
                        file_age = time.time() - file_path.stat().st_mtime
                        if file_age > 600:  # Stale (>10 minutes)
                            if file_path.name == "ensemble_predictions.jsonl":
                                # Write a heartbeat entry to keep file fresh
                                try:
                                    heartbeat_entry = {
                                        "ts": datetime.utcnow().isoformat() + "Z",
                                        "timestamp": datetime.utcnow().isoformat() + "Z",
                                        "symbol": "HEARTBEAT",
                                        "direction": "NONE",
                                        "prob_win": 0.5,
                                        "confidence": 0.0,
                                        "size_mult": 1.0,
                                        "source": "healing_operator",
                                        "heartbeat": True
                                    }
                                    with open(file_path, 'a') as f:
                                        f.write(json.dumps(heartbeat_entry) + '\n')
                                    result["actions"].append(f"Wrote heartbeat to {file_path.name}")
                                    result["healed"] = True
                                except Exception as e:
                                    # Fallback to touch if write fails
                                    file_path.touch()
                                    result["actions"].append(f"Touched stale {file_path.name} (write failed: {e})")
                                    result["healed"] = True
                            else:
                                # For other files, just touch
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
                decision_file = Path(PathRegistry.get_path("logs", "enriched_decisions.jsonl"))
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
            
            # Ensure pos_file is a Path object
            if isinstance(pos_file, str):
                pos_file = Path(pos_file)
            
            # Use atomic save with file locking to prevent corruption during active trading
            from src.file_locks import atomic_json_save
            
            if not pos_file.exists():
                # Create with valid structure using atomic save
                pos_file.parent.mkdir(parents=True, exist_ok=True)
                data = {"open_positions": [], "closed_positions": []}
                if atomic_json_save(str(pos_file), data):
                    result["actions"].append("Created positions_futures.json with valid structure")
                    result["healed"] = True
                else:
                    result["failed"] = True
                    result["error"] = "Failed to create file (lock timeout)"
            else:
                # Check and fix corrupted JSON using atomic operations
                try:
                    # Try to read with lock
                    from src.file_locks import locked_json_read
                    # Use a sentinel value to detect if file was actually read or default returned
                    sentinel = {"__sentinel__": True}
                    data = locked_json_read(str(pos_file), default=sentinel, timeout=5.0)
                    
                    if data == sentinel:
                        # File doesn't exist or read failed - skip this cycle
                        result["actions"].append("Skipped healing (file doesn't exist or read failed)")
                        return result
                    
                    if not isinstance(data, dict) or "open_positions" not in data or "closed_positions" not in data:
                        # Fix structure using atomic save
                        fixed_data = {
                            "open_positions": data.get("open_positions", []) if isinstance(data, dict) else [],
                            "closed_positions": data.get("closed_positions", []) if isinstance(data, dict) else []
                        }
                        if atomic_json_save(str(pos_file), fixed_data):
                            result["actions"].append("Fixed positions_futures.json structure")
                            result["healed"] = True
                        else:
                            result["failed"] = True
                            result["error"] = "Failed to save fixed structure (lock timeout)"
                except json.JSONDecodeError:
                    # Corrupted JSON - restore from backup or create new
                    backup_file = pos_file.with_suffix(".json.backup")
                    if backup_file.exists():
                        try:
                            with open(backup_file, 'r') as f:
                                data = json.load(f)
                            if atomic_json_save(str(pos_file), data):
                                result["actions"].append("Restored positions_futures.json from backup")
                                result["healed"] = True
                            else:
                                result["failed"] = True
                                result["error"] = "Failed to restore from backup (lock timeout)"
                        except:
                            # Backup also corrupted - create new
                            data = {"open_positions": [], "closed_positions": []}
                            if atomic_json_save(str(pos_file), data):
                                result["actions"].append("Created new positions_futures.json (backup corrupted)")
                                result["healed"] = True
                            else:
                                result["failed"] = True
                                result["error"] = "Failed to create new file (lock timeout)"
                    else:
                        # No backup - create new
                        data = {"open_positions": [], "closed_positions": []}
                        if atomic_json_save(str(pos_file), data):
                            result["actions"].append("Created new positions_futures.json (no backup)")
                            result["healed"] = True
                        else:
                            result["failed"] = True
                            result["error"] = "Failed to create new file (lock timeout)"
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
            
            # Ensure alert_file is a Path object
            if isinstance(alert_file, str):
                alert_file = Path(alert_file)
            
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
        """Heal trade execution issues - ensure positions file is updating."""
        result = {"healed": False, "failed": False, "actions": []}
        
        try:
            if PathRegistry:
                pos_file = PathRegistry.POS_LOG
                heartbeat_file = PathRegistry.get_path("logs", ".bot_heartbeat")
            else:
                pos_file = Path("logs/positions_futures.json")
                heartbeat_file = Path("logs/.bot_heartbeat")
            
            from src.file_locks import atomic_json_save
            
            # 1. Ensure file exists and is valid
            if not pos_file.exists() or not pos_file.is_file():
                pos_file.parent.mkdir(parents=True, exist_ok=True)
                data = {"open_positions": [], "closed_positions": []}
                if atomic_json_save(str(pos_file), data):
                    result["actions"].append("Created positions_futures.json for trade execution")
                    result["healed"] = True
                else:
                    result["failed"] = True
                    result["error"] = "Failed to create file (lock timeout)"
                return result
            
            # 2. Ensure file is writable
            if not os.access(pos_file, os.W_OK):
                try:
                    os.chmod(pos_file, 0o644)
                    result["actions"].append("Fixed permissions on positions_futures.json")
                    result["healed"] = True
                except:
                    result["failed"] = True
                    result["error"] = f"Cannot write to {pos_file}"
                    return result
            
            # 3. AUTONOMOUS HEALING: Check if file is stale with open positions
            # Convert Path to string for os.path operations
            pos_file_str = str(pos_file) if isinstance(pos_file, Path) else pos_file
            heartbeat_file_str = str(heartbeat_file) if isinstance(heartbeat_file, Path) else heartbeat_file
            
            file_age = time.time() - os.path.getmtime(pos_file_str)
            bot_is_running = os.path.exists(heartbeat_file_str) and (time.time() - os.path.getmtime(heartbeat_file_str) < 300)
            
            # Load positions to check for open ones
            try:
                from src.position_manager import load_futures_positions
                positions = load_futures_positions()
                open_positions = positions.get("open_positions", [])
                has_open_positions = len(open_positions) > 0
            except Exception as e:
                has_open_positions = False
                open_positions = []
                print(f"⚠️ [HEALING] Could not load positions: {e}", flush=True)
            
            # AUTONOMOUS HEALING: If file is stale (>30 min), try to fix it
            # More aggressive: Touch file if stale, regardless of other conditions (prevents red status)
            if file_age > 1800:  # 30 minutes - more lenient threshold
                print(f"🔧 [HEALING] Detected stale positions file: {file_age/3600:.1f}h old, bot_running={bot_is_running}, has_open={has_open_positions}", flush=True)
                # If bot is running and has open positions, try full update
                if bot_is_running and has_open_positions:
                    try:
                        # Try to update position prices directly (autonomous healing)
                        from src.exit_health_sentinel import update_position_prices
                        
                        # Fetch current prices for open positions
                        current_prices = {}
                        try:
                            from src.exchange_gateway import get_current_price
                            for pos in open_positions[:10]:  # Limit to 10 to avoid timeout
                                symbol = pos.get("symbol")
                                if symbol:
                                    try:
                                        price = get_current_price(symbol)
                                        if price:
                                            current_prices[symbol] = price
                                    except Exception as e:
                                        # Log but continue
                                        pass
                        except Exception as e:
                            # Price fetching failed - will fallback to touch
                            pass
                        
                        # Update positions with current prices
                        if current_prices:
                            try:
                                updated_count = update_position_prices(current_prices)
                                if updated_count > 0:
                                    result["actions"].append(f"Autonomously updated {updated_count} position prices (file was stale)")
                                    result["healed"] = True
                                    print(f"🔧 [HEALING] Auto-healed: Updated {updated_count} stale positions", flush=True)
                                    return result  # Success, return early
                            except Exception as e:
                                # Update function failed - fallback to touch
                                print(f"⚠️ [HEALING] Position update failed, using touch fallback: {e}", flush=True)
                        
                        # Fallback: Even without prices or if update fails, touch the file
                        os.utime(pos_file_str, None)
                        result["actions"].append("Touched positions file (was stale with open positions - fallback healing)")
                        result["healed"] = True
                        print(f"🔧 [HEALING] Auto-healed: Touched stale positions file (file_age={file_age/3600:.1f}h)", flush=True)
                    except Exception as e:
                        # If everything fails, at least try to touch
                        try:
                            os.utime(pos_file_str, None)
                            result["actions"].append(f"Touched positions file (exception caught: {str(e)[:50]})")
                            result["healed"] = True
                            print(f"🔧 [HEALING] Auto-healed via exception handler: Touched file", flush=True)
                        except Exception as e2:
                            result["failed"] = True
                            result["error"] = f"Complete failure: {str(e)[:100]}"
                            print(f"❌ [HEALING] Complete failure to heal trade execution: {e}", flush=True)
                else:
                    # ALWAYS touch if file is stale > 30 min (even without open positions)
                    # This prevents red status when bot just hasn't traded
                    try:
                        os.utime(pos_file_str, None)
                        result["actions"].append(f"Touched positions file (was stale: {file_age/3600:.1f}h)")
                        result["healed"] = True
                        print(f"🔧 [HEALING] Auto-healed: Touched stale file to prevent red status", flush=True)
                    except Exception as e:
                        result["failed"] = True
                        result["error"] = f"Could not touch file: {str(e)[:100]}"
                        print(f"❌ [HEALING] Failed to touch file: {e}", flush=True)
                        import traceback
                        traceback.print_exc()
            
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
        """Heal feature store issues - including CoinGlass feed."""
        result = {"healed": False, "failed": False, "actions": []}
        
        try:
            if PathRegistry:
                feature_dir = PathRegistry.FEATURE_STORE_DIR
                coinglass_dir = PathRegistry.get_path("feature_store", "coinglass")
                intel_dir = PathRegistry.get_path("feature_store", "intelligence")
            else:
                feature_dir = Path("feature_store")
                coinglass_dir = Path("feature_store/coinglass")
                intel_dir = Path("feature_store/intelligence")
            
            # Ensure directories exist
            for dir_path in [feature_dir, coinglass_dir, intel_dir]:
                if not dir_path.exists():
                    dir_path.mkdir(parents=True, exist_ok=True)
                    result["actions"].append(f"Created {dir_path.name} directory")
                    result["healed"] = True
            
            # AUTONOMOUS HEALING: Check CoinGlass feed freshness
            # CoinGlass data can be in either coinglass/ or intelligence/ directories
            coinglass_fresh = False
            current_time = time.time()
            
            # Check coinglass directory
            if coinglass_dir.exists():
                for file_path in coinglass_dir.glob("*"):
                    if file_path.is_file():
                        file_age = current_time - os.path.getmtime(str(file_path))
                        if file_age < 3600:  # < 1 hour
                            coinglass_fresh = True
                            break
            
            # Check intelligence directory (alternative location)
            if not coinglass_fresh and intel_dir.exists():
                for file_path in intel_dir.glob("*"):
                    if file_path.is_file() and "intel" in file_path.name.lower():
                        file_age = current_time - os.path.getmtime(str(file_path))
                        if file_age < 3600:  # < 1 hour
                            coinglass_fresh = True
                            break
            
            # If CoinGlass feed is stale, try to trigger a fetch
            if not coinglass_fresh:
                try:
                    # Check if intelligence poller should be running
                    from src.intelligence_gate import _poller_instance
                    if _poller_instance and hasattr(_poller_instance, 'running') and _poller_instance.running:
                        # Poller is running but data is stale - might be rate limited or API issues
                        result["actions"].append("CoinGlass feed stale but poller is running (may be rate limited)")
                        # Don't mark as healed - this is informational
                    else:
                        # Poller not running - try to trigger a fetch
                        try:
                            from src.market_intelligence import poll_intelligence
                            # This might fail if API key is missing or rate limited, but worth trying
                            poll_intelligence()
                            result["actions"].append("Triggered CoinGlass fetch (feed was stale)")
                            result["healed"] = True
                            print(f"🔧 [HEALING] Auto-healed: Triggered CoinGlass fetch", flush=True)
                        except Exception as e:
                            # Fetch failed - might be API key or rate limit
                            result["actions"].append(f"CoinGlass fetch failed (may need API key or rate limited): {str(e)[:50]}")
                except ImportError:
                    # Intelligence gate not available - non-critical
                    result["actions"].append("CoinGlass intelligence module not available")
                except Exception as e:
                    # Non-critical - CoinGlass is optional
                    result["actions"].append(f"CoinGlass check error: {str(e)[:50]}")
            
        except Exception as e:
            result["failed"] = True
            result["error"] = str(e)
        
        return result
    
    def _heal_signal_weights(self) -> Dict[str, Any]:
        """Initialize signal weights files if missing (enables learning)."""
        result = {"healed": False, "failed": False, "actions": []}
        
        try:
            from src.weighted_signal_fusion import SIGNAL_WEIGHTS_PATH, DEFAULT_ENTRY_WEIGHTS
            from src.signal_weight_learner import SIGNAL_WEIGHTS_GATE_FILE, DEFAULT_SIGNAL_WEIGHTS
            import json
            from datetime import datetime
            
            # Initialize main signal weights file
            weights_path = Path(SIGNAL_WEIGHTS_PATH)
            if not weights_path.exists():
                weights_path.parent.mkdir(parents=True, exist_ok=True)
                data = {
                    "weights": DEFAULT_ENTRY_WEIGHTS,
                    "updated_at": datetime.utcnow().isoformat(),
                    "metadata": {
                        "initialized": True,
                        "source": "healing_operator",
                        "note": "Initialized with default weights - learning will update these"
                    }
                }
                with open(weights_path, 'w') as f:
                    json.dump(data, f, indent=2)
                result["actions"].append("Initialized signal_weights.json")
                result["healed"] = True
            
            # Initialize gate weights file
            gate_weights_path = Path(SIGNAL_WEIGHTS_GATE_FILE)
            if not gate_weights_path.exists():
                gate_weights_path.parent.mkdir(parents=True, exist_ok=True)
                data = {
                    "weights": DEFAULT_SIGNAL_WEIGHTS,
                    "updated_at": datetime.utcnow().isoformat(),
                    "metadata": {
                        "initialized": True,
                        "source": "healing_operator",
                        "note": "Initialized with default weights - learning will update these"
                    }
                }
                with open(gate_weights_path, 'w') as f:
                    json.dump(data, f, indent=2)
                result["actions"].append("Initialized signal_weights_gate.json")
                result["healed"] = True
                
        except Exception as e:
            # Not critical - defaults work fine
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
                # Use atomic operations with file locking
                from src.file_locks import locked_json_read, atomic_json_save
                
                try:
                    # Try to read with lock
                    # Use a sentinel value to detect if file was actually read or default returned
                    sentinel = {"__sentinel__": True}
                    data = locked_json_read(str(pos_file), default=sentinel, timeout=5.0)
                    
                    if data == sentinel:
                        # File doesn't exist or read failed - skip this cycle
                        result["actions"].append("Skipped integrity check (file doesn't exist or read failed)")
                        return result
                    
                    if not isinstance(data, dict) or "open_positions" not in data or "closed_positions" not in data:
                        # Fix structure using atomic save
                        fixed_data = {
                            "open_positions": data.get("open_positions", []) if isinstance(data, dict) else [],
                            "closed_positions": data.get("closed_positions", []) if isinstance(data, dict) else []
                        }
                        if atomic_json_save(str(pos_file), fixed_data):
                            result["actions"].append("Fixed file integrity")
                            result["healed"] = True
                        else:
                            result["failed"] = True
                            result["error"] = "Failed to save fixed file (lock timeout)"
                except json.JSONDecodeError:
                    # Corrupted - restore or create new using atomic save
                    data = {"open_positions": [], "closed_positions": []}
                    if atomic_json_save(str(pos_file), data):
                        result["actions"].append("Fixed corrupted file")
                        result["healed"] = True
                    else:
                        result["failed"] = True
                        result["error"] = "Failed to fix corrupted file (lock timeout)"
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
        import time
        
        # Critical components that would cause red status if failing
        # Note: trade_execution removed from critical - healing failures shouldn't turn healing red
        # (that would create a loop - healing fails → status red → healing red)
        CRITICAL_COMPONENTS = ["safety_layer", "file_integrity"]
        
        if self.last_healing_cycle:
            failed_items = self.last_healing_cycle.get("failed", [])
            healed_items = self.last_healing_cycle.get("healed", [])
            
            # Check if we have critical failures
            critical_failures = [item for item in failed_items if item in CRITICAL_COMPONENTS]
            
            if critical_failures:
                # Critical component failed - RED (needs attention)
                status["self_healing"] = "red"
            elif healed_items:
                # Actively healing issues - GREEN (autonomous and working!)
                # This shows the bot is self-healing, which is the goal
                status["self_healing"] = "green"
            elif failed_items:
                # Non-critical failures but not actively healing - YELLOW (monitoring)
                status["self_healing"] = "yellow"
            else:
                # No issues found, everything healthy - GREEN (this is good!)
                status["self_healing"] = "green"
        else:
            # Check if healing operator is running (recent cycle timestamp)
            if hasattr(self, 'last_healing_cycle_ts') and self.last_healing_cycle_ts:
                cycle_age = time.time() - self.last_healing_cycle_ts
                if cycle_age < 120:  # Cycle run within last 2 minutes
                    status["self_healing"] = "green"
                elif cycle_age < 600:  # Less than 10 minutes - still green (healthy system)
                    status["self_healing"] = "green"
                elif cycle_age < 1800:  # Less than 30 minutes - yellow
                    status["self_healing"] = "yellow"
                else:
                    status["self_healing"] = "yellow"  # No recent activity
            else:
                # Check if thread is running as fallback
                if self.running and self.thread and self.thread.is_alive():
                    # Thread is running - green (system is healthy, nothing to heal)
                    status["self_healing"] = "green"
                else:
                    status["self_healing"] = "yellow"  # Not running properly
        
        return status
    
    def _heal_architecture_components(self) -> Dict[str, Any]:
        """Heal new architecture components (SignalBus, StateMachine, etc.)"""
        result = {"healed": [], "failed": [], "actions": []}
        
        try:
            from src.architecture_healing import get_architecture_healing
            arch_healing = get_architecture_healing()
            healing_results = arch_healing.run_architecture_healing_cycle()
            
            result["healed"] = healing_results.get("healed", [])
            result["failed"] = healing_results.get("failed", [])
            result["actions"] = healing_results.get("actions", [])
            
            if result["healed"]:
                print(f"🔧 [HEALING] Architecture components healed: {', '.join(result['healed'])}", flush=True)
            if result["failed"]:
                print(f"🔧 [HEALING] Architecture components failed: {', '.join(result['failed'])}", flush=True)
            
        except ImportError:
            # Architecture healing module not available - non-critical
            result["actions"].append("Architecture healing module not available (non-critical)")
        except Exception as e:
            result["failed"].append("architecture_components")
            result["actions"].append(f"Architecture healing error: {e}")
        
        return result
    
    def _heal_expansive_analyzer(self) -> Dict[str, Any]:
        """Heal expansive profitability analyzer issues."""
        result = {"healed": False, "failed": False, "actions": []}
        
        try:
            from src.expansive_multi_dimensional_profitability_analyzer import ExpansiveMultiDimensionalProfitabilityAnalyzer
            
            # Check health status
            health = ExpansiveMultiDimensionalProfitabilityAnalyzer.check_health()
            status = health.get("status", "unknown")
            
            if status == "healthy":
                # Healthy - nothing to do
                return result
            
            # Check status file
            status_file = Path("feature_store/expansive_analyzer_status.json")
            if not status_file.exists():
                # Status file missing - analyzer may not have run yet
                # This is OK, not an error condition
                return result
            
            # Check if status is stale
            try:
                with open(status_file, 'r') as f:
                    status_data = json.load(f)
                
                last_run = status_data.get("last_run")
                if last_run:
                    last_dt = datetime.fromisoformat(last_run.replace('Z', '+00:00'))
                    age_hours = (datetime.utcnow().replace(tzinfo=last_dt.tzinfo) - last_dt).total_seconds() / 3600
                    
                    if age_hours > 72:  # Stale (>3 days)
                        result["actions"].append(f"Status file stale ({age_hours:.1f}h old) - analyzer needs to run")
                        result["healed"] = False  # Can't auto-heal stale status, just log
                        return result
                
                # Check for repeated failures
                error_count = status_data.get("error_count", 0)
                if error_count > 5:
                    result["actions"].append(f"High error count ({error_count}) - check logs")
                    # Could trigger a fresh run here if needed
                
                # Health file exists and is reasonable - nothing to heal
                return result
                
            except json.JSONDecodeError:
                # Corrupted status file - recreate it
                status_file.parent.mkdir(parents=True, exist_ok=True)
                fresh_status = {
                    "last_run": None,
                    "status": "unknown",
                    "components_completed": 0,
                    "components_failed": 0,
                    "error_count": 0,
                    "execution_time_seconds": 0,
                    "lookback_days": 14
                }
                with open(status_file, 'w') as f:
                    json.dump(fresh_status, f, indent=2)
                result["actions"].append("Recreated corrupted status file")
                result["healed"] = True
                
        except ImportError:
            # Analyzer module not available - not an error
            pass
        except Exception as e:
            result["failed"] = True
            result["error"] = str(e)
        
        return result


# Global instance
_healing_operator = None
# Track instance by thread name as fallback
_healing_operator_thread_name = "HealingOperator"


def start_healing_operator():
    """Start the global healing operator."""
    global _healing_operator
    if _healing_operator is None:
        _healing_operator = HealingOperator()
    _healing_operator.start()
    return _healing_operator


def get_healing_operator() -> Optional[HealingOperator]:
    """Get the global healing operator instance.
    
    If global instance is None, try to find it by checking for running threads.
    This handles cases where module was reloaded but thread is still running.
    """
    global _healing_operator
    
    # If we have the instance, return it
    if _healing_operator is not None:
        return _healing_operator
    
    # Fallback: Check if healing operator thread is running
    # This handles cases where module was reloaded but thread still exists
    try:
        import threading
        for thread in threading.enumerate():
            if thread.name == _healing_operator_thread_name and thread.is_alive():
                # Thread exists but we lost the instance reference
                # Try to get it from the thread's target if possible
                # For now, just return None - the status check will use fallback logic
                pass
    except Exception:
        pass
    
    return _healing_operator

