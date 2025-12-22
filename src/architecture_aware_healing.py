#!/usr/bin/env python3
"""
Architecture-Aware Self-Healing System
======================================
Uses ARCHITECTURE_MAP.md to understand system structure and automatically
diagnose and fix issues across the entire pipeline.

This is an all-encompassing healing layer that:
1. Understands the architecture (from ARCHITECTURE_MAP.md)
2. Monitors all components
3. Diagnoses issues using architecture knowledge
4. Automatically fixes issues
5. Reports on what was fixed
"""

import os
import sys
import json
import time
import subprocess
import multiprocessing
from pathlib import Path
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any, Tuple

# Add src to path
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

class ArchitectureAwareHealing:
    """
    Comprehensive self-healing system that uses architecture knowledge
    to diagnose and fix issues across the entire trading bot pipeline.
    """
    
    def __init__(self):
        self.architecture_map = self._load_architecture_map()
        self.worker_processes = {}  # Will be populated from run.py
        self.healing_log = []
        self.last_healing_cycle = None
        
    def _load_architecture_map(self) -> Dict[str, Any]:
        """Load architecture knowledge from ARCHITECTURE_MAP.md."""
        # For now, we'll encode the key architecture knowledge
        # In the future, could parse ARCHITECTURE_MAP.md
        return {
            "workers": {
                "predictive_engine": {
                    "function": "_worker_predictive_engine",
                    "output": "logs/predictive_signals.jsonl",
                    "max_age_minutes": 5,
                    "critical": True,
                    "depends_on": []
                },
                "ensemble_predictor": {
                    "function": "_worker_ensemble_predictor",
                    "output": "logs/ensemble_predictions.jsonl",
                    "max_age_minutes": 5,
                    "critical": True,
                    "depends_on": ["predictive_engine"]  # Needs predictive_signals.jsonl
                },
                "signal_resolver": {
                    "function": "_worker_signal_resolver",
                    "output": "feature_store/pending_signals.json",
                    "max_age_minutes": 5,
                    "critical": True,
                    "depends_on": ["ensemble_predictor"]  # Needs ensemble_predictions.jsonl
                },
                "feature_builder": {
                    "function": "_worker_feature_builder",
                    "output": "feature_store/features_*.json",
                    "max_age_minutes": 60,
                    "critical": False,
                    "depends_on": []
                }
            },
            "files": {
                "predictive_signals.jsonl": {
                    "path": "logs/predictive_signals.jsonl",
                    "producer": "predictive_engine",
                    "max_age_minutes": 5,
                    "critical": True
                },
                "ensemble_predictions.jsonl": {
                    "path": "logs/ensemble_predictions.jsonl",
                    "producer": "ensemble_predictor",
                    "max_age_minutes": 5,
                    "critical": True
                },
                "pending_signals.json": {
                    "path": "feature_store/pending_signals.json",
                    "producer": "signal_resolver",
                    "max_age_minutes": 5,
                    "critical": True
                },
                "positions_futures.json": {
                    "path": "logs/positions_futures.json",
                    "producer": "portfolio_tracker",
                    "max_age_minutes": 60,
                    "critical": True
                },
                "signal_weights_gate.json": {
                    "path": "feature_store/signal_weights_gate.json",
                    "producer": "signal_weight_learner",
                    "max_age_minutes": 1440,  # 24 hours
                    "critical": False
                },
                "signal_policies.json": {
                    "path": "configs/signal_policies.json",
                    "producer": "feedback_injector",
                    "max_age_minutes": 1440,
                    "critical": True
                }
            },
            "dependencies": {
                "ensemble_predictor": ["predictive_signals.jsonl"],
                "signal_resolver": ["ensemble_predictions.jsonl"],
                "conviction_gate": ["signal_weights_gate.json", "signal_policies.json"]
            }
        }
    
    def run_healing_cycle(self) -> Dict[str, Any]:
        """
        Run a complete healing cycle.
        
        Returns:
            dict with healing results
        """
        print("\n" + "="*80)
        print("🏥 ARCHITECTURE-AWARE HEALING CYCLE")
        print("="*80)
        print(f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print()
        
        results = {
            "timestamp": datetime.now().isoformat(),
            "healed": [],
            "failed": [],
            "warnings": [],
            "stats": {
                "workers_restarted": 0,
                "files_repaired": 0,
                "configs_fixed": 0,
                "processes_checked": 0
            }
        }
        
        # 1. Check and heal worker processes
        print("="*80)
        print("1. CHECKING WORKER PROCESSES")
        print("="*80)
        worker_results = self._heal_worker_processes()
        results["healed"].extend(worker_results["healed"])
        results["failed"].extend(worker_results["failed"])
        results["warnings"].extend(worker_results["warnings"])
        results["stats"]["workers_restarted"] = worker_results["restarted"]
        results["stats"]["processes_checked"] = worker_results["checked"]
        
        # 2. Check and heal file staleness
        print("\n" + "="*80)
        print("2. CHECKING FILE STALENESS")
        print("="*80)
        file_results = self._heal_file_staleness()
        results["healed"].extend(file_results["healed"])
        results["failed"].extend(file_results["failed"])
        results["warnings"].extend(file_results["warnings"])
        results["stats"]["files_repaired"] = file_results["repaired"]
        
        # 3. Check and heal configuration issues
        print("\n" + "="*80)
        print("3. CHECKING CONFIGURATION")
        print("="*80)
        config_results = self._heal_configuration()
        results["healed"].extend(config_results["healed"])
        results["failed"].extend(config_results["failed"])
        results["warnings"].extend(config_results["warnings"])
        results["stats"]["configs_fixed"] = config_results["fixed"]
        
        # 4. Check and heal dependencies
        print("\n" + "="*80)
        print("4. CHECKING DEPENDENCIES")
        print("="*80)
        dep_results = self._heal_dependencies()
        results["healed"].extend(dep_results["healed"])
        results["failed"].extend(dep_results["failed"])
        results["warnings"].extend(dep_results["warnings"])
        
        # Summary
        print("\n" + "="*80)
        print("HEALING CYCLE SUMMARY")
        print("="*80)
        print(f"✅ Healed: {len(results['healed'])} issues")
        print(f"❌ Failed: {len(results['failed'])} issues")
        print(f"⚠️  Warnings: {len(results['warnings'])} issues")
        print()
        
        if results["healed"]:
            print("Healed issues:")
            for issue in results["healed"]:
                print(f"   ✅ {issue}")
            print()
        
        if results["failed"]:
            print("Failed to heal:")
            for issue in results["failed"]:
                print(f"   ❌ {issue}")
            print()
        
        if results["warnings"]:
            print("Warnings:")
            for warning in results["warnings"]:
                print(f"   ⚠️  {warning}")
            print()
        
        self.last_healing_cycle = results
        return results
    
    def _heal_worker_processes(self) -> Dict[str, Any]:
        """Check and restart dead worker processes."""
        results = {
            "healed": [],
            "failed": [],
            "warnings": [],
            "restarted": 0,
            "checked": 0
        }
        
        # Get current worker processes from system
        try:
            # Check if bot service is running
            bot_status = subprocess.run(
                ["systemctl", "is-active", "tradingbot"],
                capture_output=True,
                text=True,
                timeout=5
            )
            
            if bot_status.returncode != 0:
                results["failed"].append("Bot service is not active - cannot check workers")
                return results
            
            # Check each worker process
            for worker_name, worker_info in self.architecture_map["workers"].items():
                results["checked"] += 1
                
                # Check if worker process is running
                is_running = self._check_worker_running(worker_name)
                
                # Check if output file is stale
                output_path = Path(worker_info["output"])
                file_stale = False
                if output_path.exists():
                    mtime = output_path.stat().st_mtime
                    age_minutes = (time.time() - mtime) / 60
                    if age_minutes > worker_info["max_age_minutes"]:
                        file_stale = True
                elif worker_info["critical"]:
                    file_stale = True  # Missing critical file
                
                if not is_running or file_stale:
                    # Try to restart worker
                    print(f"   🔍 Checking {worker_name}...")
                    
                    if not is_running:
                        print(f"      ❌ Process not running")
                    if file_stale:
                        print(f"      ⚠️  Output file stale or missing: {worker_info['output']}")
                    
                    # Check dependencies first
                    deps_ok = True
                    for dep in worker_info.get("depends_on", []):
                        dep_file = self.architecture_map["workers"].get(dep, {}).get("output")
                        if dep_file:
                            dep_path = Path(dep_file)
                            if not dep_path.exists():
                                print(f"      ⚠️  Dependency missing: {dep_file}")
                                deps_ok = False
                            else:
                                dep_mtime = dep_path.stat().st_mtime
                                dep_age = (time.time() - dep_mtime) / 60
                                if dep_age > 60:  # Dependency stale
                                    print(f"      ⚠️  Dependency stale: {dep_file} ({dep_age:.1f} min old)")
                                    deps_ok = False
                    
                    if deps_ok:
                        # Try to restart by restarting bot service
                        print(f"      🔄 Attempting to restart {worker_name}...")
                        restart_success = self._restart_worker(worker_name)
                        
                        if restart_success:
                            results["healed"].append(f"Restarted {worker_name} worker")
                            results["restarted"] += 1
                            print(f"      ✅ {worker_name} restarted successfully")
                        else:
                            results["failed"].append(f"Failed to restart {worker_name} worker")
                            print(f"      ❌ Failed to restart {worker_name}")
                    else:
                        results["warnings"].append(f"{worker_name} has missing/stale dependencies")
                        print(f"      ⚠️  Cannot restart {worker_name} - dependencies not ready")
                else:
                    print(f"   ✅ {worker_name}: Running and healthy")
        
        except Exception as e:
            print(f"   ❌ Error checking workers: {e}")
            import traceback
            traceback.print_exc()
            results["failed"].append(f"Error checking workers: {e}")
        
        return results
    
    def _check_worker_running(self, worker_name: str) -> bool:
        """Check if a worker process is running."""
        try:
            # Check process list for worker name
            result = subprocess.run(
                ["pgrep", "-f", worker_name],
                capture_output=True,
                text=True,
                timeout=5
            )
            return result.returncode == 0 and result.stdout.strip() != ""
        except:
            return False
    
    def _restart_worker(self, worker_name: str) -> bool:
        """
        Restart a worker by restarting the bot service.
        This is a safe way to restart workers.
        """
        try:
            # Restart bot service
            result = subprocess.run(
                ["sudo", "systemctl", "restart", "tradingbot"],
                capture_output=True,
                text=True,
                timeout=30
            )
            
            if result.returncode == 0:
                # Wait a bit for workers to start
                time.sleep(5)
                return True
            else:
                print(f"      ⚠️  systemctl restart failed: {result.stderr}")
                return False
        except Exception as e:
            print(f"      ⚠️  Restart error: {e}")
            return False
    
    def _heal_file_staleness(self) -> Dict[str, Any]:
        """Check and repair stale files."""
        results = {
            "healed": [],
            "failed": [],
            "warnings": [],
            "repaired": 0
        }
        
        for file_name, file_info in self.architecture_map["files"].items():
            file_path = Path(file_info["path"])
            
            if not file_path.exists():
                if file_info["critical"]:
                    print(f"   ❌ Missing critical file: {file_info['path']}")
                    # Try to create empty file or restore from backup
                    try:
                        file_path.parent.mkdir(parents=True, exist_ok=True)
                        if file_name.endswith(".json"):
                            with open(file_path, 'w') as f:
                                json.dump({}, f)
                        elif file_name.endswith(".jsonl"):
                            file_path.touch()
                        results["healed"].append(f"Created missing file: {file_info['path']}")
                        results["repaired"] += 1
                        print(f"      ✅ Created {file_info['path']}")
                    except Exception as e:
                        results["failed"].append(f"Failed to create {file_info['path']}: {e}")
                        print(f"      ❌ Failed to create: {e}")
                else:
                    results["warnings"].append(f"Missing non-critical file: {file_info['path']}")
            else:
                # Check if file is stale
                mtime = file_path.stat().st_mtime
                age_minutes = (time.time() - mtime) / 60
                
                if age_minutes > file_info["max_age_minutes"]:
                    if file_info["critical"]:
                        print(f"   ⚠️  Critical file stale: {file_info['path']} ({age_minutes:.1f} min old)")
                        results["warnings"].append(f"Stale critical file: {file_info['path']} ({age_minutes:.1f} min old)")
                    else:
                        print(f"   ℹ️  Non-critical file stale: {file_info['path']} ({age_minutes:.1f} min old)")
        
        return results
    
    def _heal_configuration(self) -> Dict[str, Any]:
        """Check and fix configuration issues."""
        results = {
            "healed": [],
            "failed": [],
            "warnings": [],
            "fixed": 0
        }
        
        # Check signal_policies.json
        policies_path = Path("configs/signal_policies.json")
        if policies_path.exists():
            try:
                with open(policies_path, 'r') as f:
                    policies = json.load(f)
                
                # Check for required fields
                required_fields = {
                    "long_ofi_requirement": 0.5,
                    "short_ofi_requirement": 0.5
                }
                
                needs_update = False
                for field, default_value in required_fields.items():
                    if field not in policies or policies[field] < default_value:
                        policies[field] = default_value
                        needs_update = True
                        print(f"   ✅ Fixed missing/low {field}: set to {default_value}")
                
                if needs_update:
                    # Backup original
                    backup_path = policies_path.with_suffix(".json.backup")
                    if not backup_path.exists():
                        import shutil
                        shutil.copy(policies_path, backup_path)
                    
                    # Write updated policies
                    with open(policies_path, 'w') as f:
                        json.dump(policies, f, indent=2)
                    
                    results["healed"].append("Updated signal_policies.json with required fields")
                    results["fixed"] += 1
            except Exception as e:
                results["failed"].append(f"Error checking signal_policies.json: {e}")
        else:
            # Create default policies
            try:
                policies_path.parent.mkdir(parents=True, exist_ok=True)
                default_policies = {
                    "long_ofi_requirement": 0.5,
                    "short_ofi_requirement": 0.5,
                    "ofi_threshold": 0.54,
                    "min_ofi_confidence": 0.5
                }
                with open(policies_path, 'w') as f:
                    json.dump(default_policies, f, indent=2)
                results["healed"].append("Created missing signal_policies.json")
                results["fixed"] += 1
                print(f"   ✅ Created signal_policies.json with defaults")
            except Exception as e:
                results["failed"].append(f"Failed to create signal_policies.json: {e}")
        
        return results
    
    def _heal_dependencies(self) -> Dict[str, Any]:
        """Check and fix dependency issues."""
        results = {
            "healed": [],
            "failed": [],
            "warnings": []
        }
        
        # Check each dependency chain
        for component, deps in self.architecture_map["dependencies"].items():
            for dep_file in deps:
                dep_path = Path(dep_file)
                if not dep_path.exists():
                    results["warnings"].append(f"{component} missing dependency: {dep_file}")
                    print(f"   ⚠️  {component} missing dependency: {dep_file}")
                else:
                    # Check if dependency is stale
                    mtime = dep_path.stat().st_mtime
                    age_minutes = (time.time() - mtime) / 60
                    if age_minutes > 60:
                        results["warnings"].append(f"{component} has stale dependency: {dep_file} ({age_minutes:.1f} min old)")
                        print(f"   ⚠️  {component} has stale dependency: {dep_file} ({age_minutes:.1f} min old)")
        
        return results


def main():
    """Run architecture-aware healing cycle."""
    healer = ArchitectureAwareHealing()
    results = healer.run_healing_cycle()
    
    # Save results
    results_path = Path("feature_store/healing_results.json")
    results_path.parent.mkdir(parents=True, exist_ok=True)
    with open(results_path, 'w') as f:
        json.dump(results, f, indent=2)
    
    print(f"\n💾 Healing results saved to: {results_path}")
    
    return 0 if not results["failed"] else 1


if __name__ == "__main__":
    sys.exit(main())
