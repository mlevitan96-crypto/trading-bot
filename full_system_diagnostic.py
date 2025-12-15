#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Comprehensive Trading Bot System Diagnostic
Checks all components: workers, pipeline, dashboard, wallet balance
"""

import os
import sys
import json
import time
import subprocess
from pathlib import Path
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple

# Fix Windows console encoding
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except:
        pass

# Try to import optional dependencies
try:
    import psutil
    PSUTIL_AVAILABLE = True
except ImportError:
    PSUTIL_AVAILABLE = False

try:
    import requests
    REQUESTS_AVAILABLE = True
except ImportError:
    REQUESTS_AVAILABLE = False

# Add src to path
sys.path.insert(0, 'src')

class SystemDiagnostic:
    """Comprehensive system diagnostic tool"""
    
    def __init__(self):
        self.results = {
            "timestamp": time.time(),
            "timestamp_formatted": datetime.now().isoformat(),
            "overall_status": "UNKNOWN",
            "components": {},
            "issues": [],
            "warnings": [],
            "recommendations": []
        }
    
    def run_full_diagnostic(self) -> Dict:
        """Run complete system diagnostic"""
        print("\n" + "="*80)
        print("🔍 COMPREHENSIVE TRADING BOT SYSTEM DIAGNOSTIC")
        print("="*80 + "\n")
        
        # 1. Check worker processes
        print("1️⃣  Checking Worker Processes...")
        self._check_worker_processes()
        print()
        
        # 2. Check file pipeline
        print("2️⃣  Checking File Pipeline...")
        self._check_file_pipeline()
        print()
        
        # 3. Check dashboard
        print("3️⃣  Checking Dashboard...")
        self._check_dashboard()
        print()
        
        # 4. Check wallet balance
        print("4️⃣  Checking Wallet Balance...")
        self._check_wallet_balance()
        print()
        
        # 5. Check signal resolution
        print("5️⃣  Checking Signal Resolution...")
        self._check_signal_resolution()
        print()
        
        # 6. Check config files
        print("6️⃣  Checking Configuration Files...")
        self._check_config_files()
        print()
        
        # 7. Determine overall status
        self._determine_overall_status()
        
        # Print summary
        self._print_summary()
        
        return self.results
    
    def _check_worker_processes(self):
        """Check if all worker processes are running"""
        expected_workers = [
            "predictive_engine",
            "feature_builder", 
            "ensemble_predictor",
            "signal_resolver"
        ]
        
        worker_status = {}
        all_running = True
        
        for worker_name in expected_workers:
            found = False
            pid = None
            cpu_percent = 0.0
            memory_mb = 0.0
            
            if PSUTIL_AVAILABLE:
                # Use psutil if available
                try:
                    for proc in psutil.process_iter(['pid', 'name', 'cmdline', 'cpu_percent', 'memory_info']):
                        try:
                            cmdline = proc.info.get('cmdline', [])
                            if cmdline and any(worker_name in str(arg) for arg in cmdline):
                                found = True
                                pid = proc.info['pid']
                                cpu_percent = proc.info.get('cpu_percent', 0.0)
                                memory_info = proc.info.get('memory_info')
                                if memory_info:
                                    memory_mb = memory_info.rss / 1024 / 1024
                                break
                        except (psutil.NoSuchProcess, psutil.AccessDenied):
                            continue
                except Exception as e:
                    print(f"   ⚠️  Error checking process with psutil: {e}")
            else:
                # Fallback to tasklist (Windows) or ps (Unix)
                try:
                    if sys.platform == "win32":
                        result = subprocess.run(
                            ['tasklist', '/FI', f'IMAGENAME eq python.exe', '/FO', 'CSV'],
                            capture_output=True, text=True, timeout=5
                        )
                        if worker_name in result.stdout:
                            found = True
                    else:
                        result = subprocess.run(
                            ['ps', 'aux'],
                            capture_output=True, text=True, timeout=5
                        )
                        if worker_name in result.stdout:
                            found = True
                except Exception as e:
                    print(f"   ⚠️  Error checking process with subprocess: {e}")
            
            status = "✅ RUNNING" if found else "❌ NOT RUNNING"
            if not found:
                all_running = False
            
            worker_status[worker_name] = {
                "status": status,
                "running": found,
                "pid": pid,
                "cpu_percent": round(cpu_percent, 1) if cpu_percent else None,
                "memory_mb": round(memory_mb, 1) if memory_mb else None
            }
            
            if found and pid:
                print(f"   {status} {worker_name} (PID: {pid}" + 
                      (f", CPU: {cpu_percent:.1f}%" if cpu_percent else "") +
                      (f", RAM: {memory_mb:.1f}MB" if memory_mb else "") + ")")
            else:
                print(f"   {status} {worker_name}")
        
        self.results["components"]["workers"] = worker_status
        
        if not all_running:
            self.results["issues"].append("One or more worker processes are not running")
            self.results["recommendations"].append("Check run.py logs and restart workers if needed")
    
    def _check_file_pipeline(self):
        """Check file pipeline health"""
        pipeline_files = {
            "predictive_signals.jsonl": {
                "path": Path("logs/predictive_signals.jsonl"),
                "max_age_seconds": 3600,  # 1 hour
                "description": "Predictive signals from predictive engine"
            },
            "ensemble_predictions.jsonl": {
                "path": Path("logs/ensemble_predictions.jsonl"),
                "max_age_seconds": 3600,  # 1 hour
                "description": "Ensemble predictions from ensemble predictor"
            },
            "signal_outcomes.jsonl": {
                "path": Path("logs/signal_outcomes.jsonl"),
                "max_age_seconds": 7200,  # 2 hours
                "description": "Resolved signal outcomes"
            },
            "pending_signals.json": {
                "path": Path("feature_store/pending_signals.json"),
                "max_age_seconds": None,  # No max age (can be stale if no new signals)
                "description": "Pending signals awaiting resolution"
            }
        }
        
        pipeline_status = {}
        pipeline_healthy = True
        
        for file_name, file_info in pipeline_files.items():
            path = file_info["path"]
            exists = path.exists()
            age_seconds = None
            line_count = 0
            last_entry = None
            
            if exists:
                try:
                    mtime = path.stat().st_mtime
                    age_seconds = time.time() - mtime
                    
                    # Count lines for JSONL files
                    if path.suffix == ".jsonl":
                        with open(path, 'r') as f:
                            lines = [l for l in f if l.strip()]
                            line_count = len(lines)
                            if lines:
                                try:
                                    last_entry = json.loads(lines[-1])
                                except:
                                    pass
                    elif path.suffix == ".json":
                        with open(path, 'r') as f:
                            data = json.load(f)
                            if isinstance(data, dict):
                                line_count = len(data)
                            elif isinstance(data, list):
                                line_count = len(data)
                except Exception as e:
                    print(f"   ⚠️  Error reading {file_name}: {e}")
            
            # Check if file is stale
            is_stale = False
            if exists and file_info["max_age_seconds"]:
                if age_seconds > file_info["max_age_seconds"]:
                    is_stale = True
                    pipeline_healthy = False
            
            status = "✅ EXISTS" if exists else "❌ MISSING"
            if is_stale:
                status = "⚠️  STALE"
            
            age_str = f"{age_seconds/60:.1f} min ago" if age_seconds else "N/A"
            
            print(f"   {status} {file_name}")
            print(f"      Path: {path}")
            if exists:
                print(f"      Last updated: {age_str}")
                if line_count > 0:
                    print(f"      Entries: {line_count}")
                    if last_entry and 'ts' in last_entry:
                        print(f"      Last entry timestamp: {last_entry.get('ts', 'N/A')}")
            else:
                print(f"      ⚠️  File does not exist")
                if file_name in ["predictive_signals.jsonl", "ensemble_predictions.jsonl"]:
                    pipeline_healthy = False
                    self.results["issues"].append(f"Critical pipeline file missing: {file_name}")
            
            pipeline_status[file_name] = {
                "exists": exists,
                "age_seconds": age_seconds,
                "is_stale": is_stale,
                "line_count": line_count,
                "path": str(path)
            }
        
        self.results["components"]["pipeline"] = pipeline_status
        
        if not pipeline_healthy:
            self.results["warnings"].append("Pipeline files are stale or missing")
    
    def _check_dashboard(self):
        """Check dashboard status"""
        dashboard_url = "http://localhost:5000"
        dashboard_status = {
            "url": dashboard_url,
            "accessible": False,
            "health_endpoint": False,
            "api_endpoint": False,
            "error": None
        }
        
        if not REQUESTS_AVAILABLE:
            print(f"   ⚠️  Cannot check dashboard - 'requests' module not available")
            print(f"      Install with: pip install requests")
            dashboard_status["error"] = "requests module not available"
            self.results["warnings"].append("Cannot check dashboard - requests module missing")
            self.results["components"]["dashboard"] = dashboard_status
            return
        
        try:
            # Check main dashboard
            response = requests.get(dashboard_url, timeout=5)
            if response.status_code == 200:
                dashboard_status["accessible"] = True
                print(f"   ✅ Dashboard accessible at {dashboard_url}")
            else:
                print(f"   ⚠️  Dashboard returned status {response.status_code}")
        except requests.exceptions.ConnectionError:
            print(f"   ❌ Dashboard not accessible at {dashboard_url}")
            dashboard_status["error"] = "Connection refused - dashboard may not be running"
            self.results["issues"].append("Dashboard is not accessible")
            self.results["recommendations"].append("Check if run.py is running and dashboard started successfully")
        except Exception as e:
            print(f"   ⚠️  Dashboard check error: {e}")
            dashboard_status["error"] = str(e)
        
        # Check health endpoint
        try:
            health_url = f"{dashboard_url}/api/dashboard_health"
            response = requests.get(health_url, timeout=5)
            if response.status_code == 200:
                dashboard_status["health_endpoint"] = True
                health_data = response.json()
                print(f"   ✅ Dashboard health endpoint accessible")
                if not health_data.get("healthy", True):
                    print(f"   ⚠️  Dashboard reports unhealthy: {health_data.get('issues', [])}")
        except Exception as e:
            print(f"   ⚠️  Health endpoint error: {e}")
        
        # Check API endpoint
        try:
            api_url = f"{dashboard_url}/api/open_positions_snapshot"
            response = requests.get(api_url, timeout=5)
            if response.status_code == 200:
                dashboard_status["api_endpoint"] = True
                api_data = response.json()
                print(f"   ✅ Dashboard API endpoint accessible")
                print(f"      Open positions: {api_data.get('count', 0)}")
        except Exception as e:
            print(f"   ⚠️  API endpoint error: {e}")
        
        self.results["components"]["dashboard"] = dashboard_status
    
    def _check_wallet_balance(self):
        """Check wallet balance calculation"""
        wallet_status = {
            "balance": None,
            "starting_capital": 10000.0,
            "total_pnl": None,
            "calculation_method": None,
            "error": None
        }
        
        # Try direct calculation from positions file first (no pandas dependency)
        try:
            positions_file = Path("logs/positions_futures.json")
            if positions_file.exists():
                with open(positions_file, 'r') as f:
                    data = json.load(f)
                    closed_positions = data.get("closed_positions", [])
                    
                    total_pnl = 0.0
                    for pos in closed_positions:
                        pnl = pos.get("pnl", pos.get("net_pnl", pos.get("realized_pnl", 0)))
                        if pnl is not None:
                            try:
                                pnl = float(pnl)
                                if not (pnl != pnl):  # Check for NaN
                                    total_pnl += pnl
                            except (TypeError, ValueError):
                                pass
                    
                    balance = wallet_status["starting_capital"] + total_pnl
                    wallet_status["balance"] = balance
                    wallet_status["total_pnl"] = total_pnl
                    wallet_status["calculation_method"] = "Direct from positions_futures.json"
                    
                    print(f"   ✅ Wallet balance calculated: ${balance:,.2f}")
                    print(f"      Starting capital: ${wallet_status['starting_capital']:,.2f}")
                    print(f"      Total P&L: ${total_pnl:,.2f}")
                    print(f"      Closed positions: {len(closed_positions)}")
        except Exception as e:
            print(f"   ⚠️  Error reading positions file: {e}")
        
        # Try using dashboard function if available (requires pandas)
        if wallet_status["balance"] is None:
            try:
                from src.pnl_dashboard import get_wallet_balance
                balance = get_wallet_balance()
                wallet_status["balance"] = balance
                wallet_status["total_pnl"] = balance - wallet_status["starting_capital"]
                wallet_status["calculation_method"] = "DataRegistry.get_closed_positions()"
                
                print(f"   ✅ Wallet balance calculated: ${balance:,.2f}")
                print(f"      Starting capital: ${wallet_status['starting_capital']:,.2f}")
                print(f"      Total P&L: ${wallet_status['total_pnl']:,.2f}")
            except ImportError as e:
                if "pandas" in str(e):
                    print(f"   ⚠️  Cannot use dashboard function - pandas not available")
                    print(f"      Using direct file calculation instead")
                else:
                    raise
            except Exception as e:
                print(f"   ⚠️  Error calculating wallet balance: {e}")
                wallet_status["error"] = str(e)
                if wallet_status["balance"] is None:
                    self.results["warnings"].append(f"Wallet balance calculation failed: {e}")
        
        # Also check if dashboard shows the same balance
        if REQUESTS_AVAILABLE and wallet_status["balance"] is not None:
            try:
                dashboard_url = "http://localhost:5000"
                response = requests.get(f"{dashboard_url}/api/dashboard_health", timeout=5)
                if response.status_code == 200:
                    health_data = response.json()
                    stats = health_data.get("stats", {})
                    dashboard_balance = stats.get("wallet_balance")
                    if dashboard_balance:
                        print(f"      Dashboard shows: ${dashboard_balance:,.2f}")
                        if abs(wallet_status["balance"] - dashboard_balance) > 0.01:
                            print(f"      ⚠️  Balance mismatch between calculation and dashboard!")
                            self.results["warnings"].append(f"Wallet balance mismatch: calculated=${wallet_status['balance']:.2f}, dashboard=${dashboard_balance:.2f}")
            except:
                pass
        
        if wallet_status["balance"] is None:
            print(f"   ❌ Could not calculate wallet balance")
            self.results["issues"].append("Wallet balance could not be calculated")
        
        self.results["components"]["wallet"] = wallet_status
    
    def _check_signal_resolution(self):
        """Check signal resolution pipeline"""
        resolution_status = {
            "pending_signals_count": 0,
            "recent_outcomes_count": 0,
            "oldest_pending_signal": None,
            "newest_outcome": None,
            "issues": []
        }
        
        # Check pending signals
        pending_path = Path("feature_store/pending_signals.json")
        if pending_path.exists():
            try:
                with open(pending_path, 'r') as f:
                    pending_data = json.load(f)
                    if isinstance(pending_data, dict):
                        resolution_status["pending_signals_count"] = len(pending_data)
                        if pending_data:
                            # Find oldest signal
                            oldest_ts = None
                            oldest_id = None
                            for sig_id, sig_data in pending_data.items():
                                ts_epoch = sig_data.get('ts_epoch', 0)
                                if oldest_ts is None or ts_epoch < oldest_ts:
                                    oldest_ts = ts_epoch
                                    oldest_id = sig_id
                            
                            if oldest_ts:
                                age_hours = (time.time() - oldest_ts) / 3600
                                resolution_status["oldest_pending_signal"] = {
                                    "id": oldest_id,
                                    "age_hours": round(age_hours, 1),
                                    "ts_epoch": oldest_ts
                                }
                                print(f"   📊 Pending signals: {len(pending_data)}")
                                print(f"      Oldest signal age: {age_hours:.1f} hours")
                                
                                # Check if signals are stuck (older than 2 hours)
                                if age_hours > 2:
                                    resolution_status["issues"].append(f"Oldest pending signal is {age_hours:.1f} hours old - may be stuck")
                                    self.results["warnings"].append(f"Pending signals may be stuck (oldest is {age_hours:.1f} hours old)")
            except Exception as e:
                print(f"   ⚠️  Error reading pending signals: {e}")
        
        # Check recent outcomes
        outcomes_path = Path("logs/signal_outcomes.jsonl")
        if outcomes_path.exists():
            try:
                with open(outcomes_path, 'r') as f:
                    lines = [l for l in f if l.strip()]
                    # Count outcomes from last 24 hours
                    recent_count = 0
                    newest_ts = None
                    for line in lines[-100:]:  # Check last 100 lines
                        try:
                            entry = json.loads(line)
                            ts_epoch = entry.get('ts_epoch', entry.get('ts', 0))
                            if isinstance(ts_epoch, str):
                                from datetime import datetime
                                dt = datetime.fromisoformat(ts_epoch.replace('Z', '+00:00'))
                                ts_epoch = dt.timestamp()
                            
                            if ts_epoch:
                                age_hours = (time.time() - ts_epoch) / 3600
                                if age_hours < 24:
                                    recent_count += 1
                                if newest_ts is None or ts_epoch > newest_ts:
                                    newest_ts = ts_epoch
                        except:
                            continue
                    
                    resolution_status["recent_outcomes_count"] = recent_count
                    if newest_ts:
                        age_hours = (time.time() - newest_ts) / 3600
                        resolution_status["newest_outcome"] = {
                            "age_hours": round(age_hours, 1),
                            "ts_epoch": newest_ts
                        }
                        print(f"   📊 Recent outcomes (24h): {recent_count}")
                        print(f"      Newest outcome age: {age_hours:.1f} hours")
                        
                        if age_hours > 2:
                            resolution_status["issues"].append(f"Newest outcome is {age_hours:.1f} hours old - resolution may be stuck")
                            self.results["warnings"].append("Signal outcomes are stale - resolution pipeline may be stuck")
            except Exception as e:
                print(f"   ⚠️  Error reading outcomes: {e}")
        
        self.results["components"]["signal_resolution"] = resolution_status
    
    def _check_config_files(self):
        """Check critical configuration files"""
        config_files = {
            "execution_governor.json": Path("config/execution_governor.json"),
            "fee_arbiter.json": Path("config/fee_arbiter.json"),
            "correlation_throttle.json": Path("config/correlation_throttle.json"),
            "live_config.json": Path("config/live_config.json"),
            "signal_policies.json": Path("config/signal_policies.json")
        }
        
        config_status = {}
        all_exist = True
        
        for config_name, config_path in config_files.items():
            exists = config_path.exists()
            config_status[config_name] = {
                "exists": exists,
                "path": str(config_path)
            }
            
            status = "✅ EXISTS" if exists else "⚠️  MISSING"
            print(f"   {status} {config_name}")
            
            if not exists:
                all_exist = False
                if config_name in ["execution_governor.json", "fee_arbiter.json", "correlation_throttle.json"]:
                    self.results["warnings"].append(f"Config file missing: {config_name} (should be auto-created)")
        
        self.results["components"]["configs"] = config_status
    
    def _determine_overall_status(self):
        """Determine overall system status"""
        critical_issues = len(self.results["issues"])
        warnings = len(self.results["warnings"])
        
        if critical_issues > 0:
            self.results["overall_status"] = "❌ UNHEALTHY"
        elif warnings > 0:
            self.results["overall_status"] = "⚠️  WARNINGS"
        else:
            self.results["overall_status"] = "✅ HEALTHY"
    
    def _print_summary(self):
        """Print diagnostic summary"""
        print("="*80)
        print("📋 DIAGNOSTIC SUMMARY")
        print("="*80)
        print(f"\nOverall Status: {self.results['overall_status']}")
        
        if self.results["issues"]:
            print(f"\n❌ Critical Issues ({len(self.results['issues'])}):")
            for issue in self.results["issues"]:
                print(f"   • {issue}")
        
        if self.results["warnings"]:
            print(f"\n⚠️  Warnings ({len(self.results['warnings'])}):")
            for warning in self.results["warnings"]:
                print(f"   • {warning}")
        
        if self.results["recommendations"]:
            print(f"\n💡 Recommendations ({len(self.results['recommendations'])}):")
            for rec in self.results["recommendations"]:
                print(f"   • {rec}")
        
        if not self.results["issues"] and not self.results["warnings"]:
            print("\n✅ All systems operational!")
        
        print("\n" + "="*80)
        
        # Save results to file
        results_file = Path("logs/system_diagnostic_results.json")
        results_file.parent.mkdir(parents=True, exist_ok=True)
        with open(results_file, 'w') as f:
            json.dump(self.results, f, indent=2)
        print(f"📄 Full diagnostic results saved to: {results_file}")
        print("="*80 + "\n")


def main():
    """Run full system diagnostic"""
    diagnostic = SystemDiagnostic()
    results = diagnostic.run_full_diagnostic()
    
    # Exit with appropriate code
    if results["overall_status"] == "❌ UNHEALTHY":
        sys.exit(1)
    elif results["overall_status"] == "⚠️  WARNINGS":
        sys.exit(2)
    else:
        sys.exit(0)


if __name__ == "__main__":
    main()

