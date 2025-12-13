"""
Health Check System - Validates bot integrity and catches configuration issues
"""

import json
import os
from pathlib import Path
from typing import Dict, List, Tuple

class HealthCheck:
    """Comprehensive health check for the trading bot."""
    
    def __init__(self):
        self.results = {
            "status": "unknown",
            "checks_passed": 0,
            "checks_failed": 0,
            "warnings": 0,
            "errors": [],
            "warnings_list": [],
            "details": {}
        }
    
    def run_all_checks(self) -> Dict:
        """Run all health checks and return results."""
        self._check_imports()
        self._check_config_files()
        self._check_log_directories()
        self._check_daily_stats()
        self._check_phase2_integration()
        self._check_phase3_integration()
        self._check_portfolio_trackers()
        self._check_secrets()
        
        # Determine overall status
        if self.results["checks_failed"] == 0:
            if self.results["warnings"] == 0:
                self.results["status"] = "healthy"
            else:
                self.results["status"] = "healthy_with_warnings"
        else:
            self.results["status"] = "unhealthy"
        
        return self.results
    
    def _check_imports(self):
        """Verify all critical modules can be imported."""
        critical_imports = [
            ("portfolio_tracker", "src.portfolio_tracker"),
            ("futures_portfolio_tracker", "src.futures_portfolio_tracker"),
            ("daily_stats_tracker", "src.daily_stats_tracker"),
            ("position_manager", "src.position_manager"),
            ("kelly_sizing", "src.kelly_sizing"),
            ("regime_detector", "src.regime_detector"),
            ("phase2_integration", "src.phase2_integration"),
            ("phase3_integration", "src.phase3_integration"),
            ("bot_cycle", "src.bot_cycle")
        ]
        
        import_results = []
        for display_name, module_path in critical_imports:
            try:
                # Try both import methods for compatibility
                try:
                    __import__(module_path)
                except ModuleNotFoundError:
                    # Fallback for when running from project root
                    import sys
                    import os
                    sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
                    __import__(display_name)
                
                import_results.append({"module": display_name, "status": "ok"})
                self.results["checks_passed"] += 1
            except Exception as e:
                import_results.append({"module": display_name, "status": "failed", "error": str(e)})
                self.results["checks_failed"] += 1
                self.results["errors"].append(f"Import failed: {display_name} - {str(e)}")
        
        self.results["details"]["imports"] = import_results
    
    def _check_config_files(self):
        """Verify all required configuration files exist and are valid JSON."""
        config_files = [
            "configs/pair_overrides.json",
            "configs/leverage_defaults.json",
            "configs/futures_policy.json",
            "configs/ladder_exit_policy.json",
            "configs/phase2_config.json",
            "configs/phase3_config.json"
        ]
        
        config_results = []
        for config_file in config_files:
            if Path(config_file).exists():
                try:
                    with open(config_file) as f:
                        json.load(f)
                    config_results.append({"file": config_file, "status": "ok"})
                    self.results["checks_passed"] += 1
                except json.JSONDecodeError as e:
                    config_results.append({"file": config_file, "status": "invalid_json", "error": str(e)})
                    self.results["checks_failed"] += 1
                    self.results["errors"].append(f"Invalid JSON: {config_file}")
            else:
                config_results.append({"file": config_file, "status": "missing"})
                self.results["warnings"] += 1
                self.results["warnings_list"].append(f"Missing config: {config_file}")
        
        self.results["details"]["config_files"] = config_results
    
    def _check_log_directories(self):
        """Verify log directories exist and are writable."""
        log_dirs = ["logs", "configs"]
        
        dir_results = []
        for log_dir in log_dirs:
            path = Path(log_dir)
            if path.exists() and path.is_dir():
                # Test write permissions
                test_file = path / ".health_check_test"
                try:
                    test_file.touch()
                    test_file.unlink()
                    dir_results.append({"directory": log_dir, "status": "ok"})
                    self.results["checks_passed"] += 1
                except Exception as e:
                    dir_results.append({"directory": log_dir, "status": "not_writable", "error": str(e)})
                    self.results["checks_failed"] += 1
                    self.results["errors"].append(f"Directory not writable: {log_dir}")
            else:
                dir_results.append({"directory": log_dir, "status": "missing"})
                self.results["checks_failed"] += 1
                self.results["errors"].append(f"Missing directory: {log_dir}")
        
        self.results["details"]["directories"] = dir_results
    
    def _check_daily_stats(self):
        """Verify daily stats tracking is operational."""
        try:
            from src.daily_stats_tracker import get_daily_summary, check_and_reset_if_new_day
            
            # Test that we can call these functions
            check_and_reset_if_new_day()
            summary = get_daily_summary()
            
            # Verify the structure
            required_keys = ["date", "trades", "wins", "losses", "total_pnl", "percent_pnl"]
            missing_keys = [k for k in required_keys if k not in summary]
            
            if missing_keys:
                self.results["checks_failed"] += 1
                self.results["errors"].append(f"Daily stats missing keys: {missing_keys}")
                self.results["details"]["daily_stats"] = {"status": "incomplete", "missing": missing_keys}
            else:
                self.results["checks_passed"] += 1
                self.results["details"]["daily_stats"] = {
                    "status": "ok",
                    "current_date": summary["date"],
                    "trades_today": summary["trades"]
                }
        except Exception as e:
            self.results["checks_failed"] += 1
            self.results["errors"].append(f"Daily stats check failed: {str(e)}")
            self.results["details"]["daily_stats"] = {"status": "failed", "error": str(e)}
    
    def _check_phase2_integration(self):
        """Verify Phase 2 capital protection is operational."""
        try:
            from src.phase2_integration import get_phase2_controller
            
            controller = get_phase2_controller()
            status = controller.get_status()
            
            # Verify structure (updated to match actual response structure)
            required_sections = ["shadow_mode", "throttle", "portfolio", "kill_switch", "leverage"]
            missing = [s for s in required_sections if s not in status]
            
            if missing:
                self.results["checks_failed"] += 1
                self.results["errors"].append(f"Phase 2 status missing sections: {missing}")
                self.results["details"]["phase2"] = {"status": "incomplete", "missing": missing}
            else:
                self.results["checks_passed"] += 1
                self.results["details"]["phase2"] = {
                    "status": "ok",
                    "shadow_mode": status.get("shadow_mode", False),
                    "kill_switch": status.get("kill_switch", False)
                }
        except Exception as e:
            self.results["checks_failed"] += 1
            self.results["errors"].append(f"Phase 2 check failed: {str(e)}")
            self.results["details"]["phase2"] = {"status": "failed", "error": str(e)}
    
    def _check_phase3_integration(self):
        """Verify Phase 3 edge compounding is operational."""
        try:
            from src.phase3_integration import get_phase3_controller
            
            controller = get_phase3_controller()
            status = controller.get_status()
            
            # Verify structure
            required_sections = ["relaxation", "drawdown", "ramp", "exposure", "bandits"]
            missing = [s for s in required_sections if s not in status]
            
            if missing:
                self.results["checks_failed"] += 1
                self.results["errors"].append(f"Phase 3 status missing sections: {missing}")
                self.results["details"]["phase3"] = {"status": "incomplete", "missing": missing}
            else:
                self.results["checks_passed"] += 1
                self.results["details"]["phase3"] = {
                    "status": "ok",
                    "ramp_stage": status["ramp"]["current_stage"],
                    "leverage_cap": status["ramp"]["current_leverage_cap"]
                }
        except Exception as e:
            self.results["checks_failed"] += 1
            self.results["errors"].append(f"Phase 3 check failed: {str(e)}")
            self.results["details"]["phase3"] = {"status": "failed", "error": str(e)}
    
    def _check_portfolio_trackers(self):
        """Verify portfolio tracking systems are operational."""
        trackers = [
            ("spot", "src.portfolio_tracker", "load_portfolio"),
            ("futures", "src.futures_portfolio_tracker", "load_futures_portfolio")
        ]
        
        tracker_results = []
        for name, module, func in trackers:
            try:
                mod = __import__(module, fromlist=[func])
                load_func = getattr(mod, func)
                portfolio = load_func()
                
                # Verify basic structure
                if isinstance(portfolio, dict):
                    tracker_results.append({
                        "tracker": name,
                        "status": "ok",
                        "has_data": len(portfolio) > 0
                    })
                    self.results["checks_passed"] += 1
                else:
                    tracker_results.append({
                        "tracker": name,
                        "status": "invalid_format"
                    })
                    self.results["checks_failed"] += 1
                    self.results["errors"].append(f"{name} tracker returned invalid format")
            except Exception as e:
                tracker_results.append({
                    "tracker": name,
                    "status": "failed",
                    "error": str(e)
                })
                self.results["checks_failed"] += 1
                self.results["errors"].append(f"{name} tracker failed: {str(e)}")
        
        self.results["details"]["portfolio_trackers"] = tracker_results
    
    def _check_secrets(self):
        """Verify required secrets are available."""
        required_secrets = [
            "BLOFIN_API_KEY",
            "BLOFIN_API_SECRET",
            "BLOFIN_PASSPHRASE"
        ]
        
        secret_results = []
        for secret in required_secrets:
            if os.getenv(secret):
                secret_results.append({"secret": secret, "status": "ok"})
                self.results["checks_passed"] += 1
            else:
                secret_results.append({"secret": secret, "status": "missing"})
                self.results["checks_failed"] += 1
                self.results["errors"].append(f"Missing secret: {secret}")
        
        self.results["details"]["secrets"] = secret_results


def run_health_check() -> Dict:
    """Run health check and return results."""
    checker = HealthCheck()
    return checker.run_all_checks()


def print_health_report():
    """Run health check and print formatted report."""
    results = run_health_check()
    
    print("=" * 60)
    print("🏥 TRADING BOT HEALTH CHECK")
    print("=" * 60)
    print(f"\nOverall Status: {results['status'].upper()}")
    print(f"✅ Checks Passed: {results['checks_passed']}")
    print(f"❌ Checks Failed: {results['checks_failed']}")
    print(f"⚠️  Warnings: {results['warnings']}")
    
    if results["errors"]:
        print("\n❌ ERRORS:")
        for error in results["errors"]:
            print(f"  • {error}")
    
    if results["warnings_list"]:
        print("\n⚠️  WARNINGS:")
        for warning in results["warnings_list"]:
            print(f"  • {warning}")
    
    print("\n📊 DETAILED RESULTS:")
    for section, data in results["details"].items():
        print(f"\n{section.upper().replace('_', ' ')}:")
        if isinstance(data, dict) and "status" in data:
            print(f"  Status: {data['status']}")
            for key, value in data.items():
                if key != "status":
                    print(f"  {key}: {value}")
        elif isinstance(data, list):
            for item in data:
                status = item.get("status", "unknown")
                name = item.get("module") or item.get("file") or item.get("directory") or item.get("tracker") or item.get("secret", "unknown")
                symbol = "✅" if status == "ok" else "❌"
                print(f"  {symbol} {name}: {status}")
    
    print("\n" + "=" * 60)
    
    return results


if __name__ == "__main__":
    print_health_report()
