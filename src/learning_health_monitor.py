#!/usr/bin/env python3
"""
LEARNING HEALTH MONITOR
Comprehensive health checks with auto-remediation for all learning systems.

Monitors:
- Daily Intelligence Learner
- Multi-Dimensional Grid Analyzer
- Pattern Discovery Engine
- Signal Universe Tracker
- Data file integrity
- Rule file freshness

Auto-remediates:
- Missing/corrupt files
- Stale data
- Failed learning runs
- Broken integrations
"""

import json
import os
import time
from datetime import datetime, timedelta
from typing import Dict, List, Tuple, Optional, Any
import threading
import traceback

try:
    from src.data_registry import DataRegistry as DR
except ImportError:
    import sys
    sys.path.insert(0, '/home/runner/workspace')
    from src.data_registry import DataRegistry as DR


HEALTH_STATUS_PATH = "feature_store/learning_health_status.json"
HEALTH_HISTORY_PATH = "logs/learning_health_history.jsonl"

CRITICAL_FILES = {
    "enriched_decisions": DR.ENRICHED_DECISIONS,
    "signals_universe": DR.SIGNALS_UNIVERSE,
    "learned_rules": DR.LEARNED_RULES,
    "daily_learning_rules": "feature_store/daily_learning_rules.json",
    "optimal_thresholds": "feature_store/optimal_thresholds.json",
    "learning_history": "feature_store/learning_history.jsonl",
    # CRITICAL DATA FILES - must check integrity, not just existence
    "portfolio_master": DR.PORTFOLIO_MASTER,
    "positions_futures": DR.POSITIONS_FUTURES,
    # PROFITABILITY ACCELERATION MODULE FILES
    "fee_gate_learning": "feature_store/fee_gate_learning.json",
    "hold_time_policy": "feature_store/hold_time_policy.json",
    "edge_sizer_calibration": "feature_store/edge_sizer_calibration.json",
    "coinglass_correlations": "feature_store/coinglass_correlations.json",
    "strategic_advisor_state": DR.STRATEGIC_ADVISOR_STATE,
}

MAX_STALENESS_HOURS = {
    "enriched_decisions": 24,
    "signals_universe": 24,
    "learned_rules": 48,
    "daily_learning_rules": 48,
    "optimal_thresholds": 48,
    "learning_history": 48,
    "portfolio_master": 168,  # 7 days max - should always be updated
    "positions_futures": 168,  # 7 days max
    # PROFITABILITY ACCELERATION MODULE STALENESS
    "fee_gate_learning": 48,
    "hold_time_policy": 48,
    "edge_sizer_calibration": 48,
    "coinglass_correlations": 24,
    "strategic_advisor_state": 2,  # Should run hourly, alert if >2h stale
}

# Files that need JSON integrity validation (not just existence)
INTEGRITY_CHECK_FILES = ["portfolio_master", "positions_futures"]


def load_json(path: str) -> Dict:
    """Load JSON file safely."""
    try:
        with open(path, 'r') as f:
            return json.load(f)
    except:
        return {}


def save_json(path: str, data: Dict):
    """Save JSON file atomically."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp_path = path + ".tmp"
    with open(tmp_path, 'w') as f:
        json.dump(data, f, indent=2)
    os.replace(tmp_path, path)


def append_jsonl(path: str, record: Dict):
    """Append record to JSONL file."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'a') as f:
        f.write(json.dumps(record) + "\n")


def count_jsonl_records(path: str) -> int:
    """Count records in JSONL file."""
    if not os.path.exists(path):
        return 0
    try:
        with open(path, 'r') as f:
            return sum(1 for _ in f)
    except:
        return 0


def get_file_age_hours(path: str) -> Optional[float]:
    """Get file age in hours."""
    if not os.path.exists(path):
        return None
    try:
        mtime = os.path.getmtime(path)
        age_seconds = time.time() - mtime
        return age_seconds / 3600
    except:
        return None


class LearningHealthMonitor:
    """Monitors health of all learning systems with auto-remediation."""
    
    def __init__(self):
        self.status = {
            "last_check": None,
            "overall_health": "unknown",
            "components": {},
            "issues": [],
            "remediations": [],
        }
        self._lock = threading.Lock()
    
    def check_file_exists(self, name: str, path: str) -> Tuple[bool, str]:
        """Check if a critical file exists."""
        if os.path.exists(path):
            return True, f"{name}: EXISTS"
        return False, f"{name}: MISSING at {path}"
    
    def check_file_freshness(self, name: str, path: str) -> Tuple[bool, str]:
        """Check if a file is fresh (not stale)."""
        age = get_file_age_hours(path)
        max_age = MAX_STALENESS_HOURS.get(name, 48)
        
        if age is None:
            return False, f"{name}: Cannot determine age"
        
        if age > max_age:
            return False, f"{name}: STALE ({age:.1f}h old, max {max_age}h)"
        
        return True, f"{name}: FRESH ({age:.1f}h old)"
    
    def check_file_integrity(self, name: str, path: str) -> Tuple[bool, str]:
        """Check if a file has valid content."""
        if not os.path.exists(path):
            return False, f"{name}: File not found"
        
        try:
            if path.endswith('.json'):
                data = load_json(path)
                if not data:
                    return False, f"{name}: Empty JSON"
                return True, f"{name}: Valid JSON"
            
            elif path.endswith('.jsonl'):
                count = count_jsonl_records(path)
                if count == 0:
                    return False, f"{name}: Empty JSONL"
                return True, f"{name}: {count} records"
            
            else:
                size = os.path.getsize(path)
                if size == 0:
                    return False, f"{name}: Empty file"
                return True, f"{name}: {size} bytes"
        
        except Exception as e:
            return False, f"{name}: Read error - {e}"
    
    def check_daily_learner(self) -> Dict:
        """Check if daily learner is functional."""
        result = {
            "name": "Daily Intelligence Learner",
            "healthy": False,
            "checks": [],
            "last_run": None,
            "issues": []
        }
        
        rules_path = "feature_store/daily_learning_rules.json"
        if os.path.exists(rules_path):
            rules = load_json(rules_path)
            generated_at = rules.get("generated_at")
            if generated_at:
                result["last_run"] = generated_at
                
                try:
                    last_dt = datetime.fromisoformat(generated_at.replace('Z', '+00:00'))
                    age_hours = (datetime.now() - last_dt.replace(tzinfo=None)).total_seconds() / 3600
                    
                    if age_hours < 48:
                        result["checks"].append(f"Last run: {age_hours:.1f}h ago (OK)")
                    else:
                        result["checks"].append(f"Last run: {age_hours:.1f}h ago (STALE)")
                        result["issues"].append("Daily learning rules are stale")
                except:
                    result["checks"].append("Cannot parse last run time")
                    result["issues"].append("Invalid timestamp in rules")
            
            profitable = rules.get("profitable_patterns", {})
            high_potential = rules.get("high_potential_patterns", {})
            result["checks"].append(f"Profitable patterns: {len(profitable)}")
            result["checks"].append(f"High potential patterns: {len(high_potential)}")
            
            result["healthy"] = len(result["issues"]) == 0
        else:
            result["issues"].append("Daily learning rules file missing")
        
        return result
    
    def check_learning_history(self) -> Dict:
        """Check learning history accumulation."""
        result = {
            "name": "Learning History",
            "healthy": False,
            "checks": [],
            "issues": []
        }
        
        history_path = "feature_store/learning_history.jsonl"
        count = count_jsonl_records(history_path)
        
        result["checks"].append(f"Snapshots: {count}")
        
        if count >= 2:
            result["checks"].append("Trend analysis possible")
            result["healthy"] = True
        elif count == 1:
            result["checks"].append("Need more snapshots for trends")
            result["healthy"] = True
        else:
            result["issues"].append("No learning history")
        
        return result
    
    def check_data_pipeline(self) -> Dict:
        """Check data pipeline health."""
        result = {
            "name": "Data Pipeline",
            "healthy": False,
            "checks": [],
            "issues": []
        }
        
        enriched_count = count_jsonl_records(DR.ENRICHED_DECISIONS)
        signals_count = count_jsonl_records(DR.SIGNALS_UNIVERSE)
        
        result["checks"].append(f"Enriched decisions: {enriched_count}")
        result["checks"].append(f"Signal universe: {signals_count}")
        
        if enriched_count >= 10:
            result["checks"].append("Sufficient data for learning")
            result["healthy"] = True
        else:
            result["issues"].append(f"Insufficient enriched decisions ({enriched_count}, need 10+)")
        
        return result
    
    def check_conditional_overlay(self) -> Dict:
        """Check conditional overlay bridge integration."""
        result = {
            "name": "Conditional Overlay Bridge",
            "healthy": False,
            "checks": [],
            "issues": []
        }
        
        try:
            from src.conditional_overlay_bridge import apply_multi_dimensional_rules
            result["checks"].append("Module importable: YES")
            
            test_ctx = {"ofi": 0.5, "ensemble": 0.05, "ofi_threshold": 0.50}
            updated_ctx = apply_multi_dimensional_rules("BTCUSDT", "LONG", test_ctx.copy())
            result["checks"].append("Function callable: YES")
            
            result["healthy"] = True
        except ImportError as e:
            result["issues"].append(f"Import error: {e}")
        except Exception as e:
            result["issues"].append(f"Execution error: {e}")
        
        return result
    
    def check_fee_gate_health(self) -> Dict:
        """
        Check fee gate learning health.
        - Check feature_store/fee_gate_learning.json exists and is fresh (<48h)
        - Verify threshold values are within valid range (0.10-0.30)
        - Auto-remediate: regenerate defaults if missing/corrupt
        """
        result = {
            "name": "Fee Gate Learning",
            "healthy": False,
            "checks": [],
            "issues": []
        }
        
        fee_gate_path = CRITICAL_FILES.get("fee_gate_learning", "feature_store/fee_gate_learning.json")
        
        if not os.path.exists(fee_gate_path):
            result["checks"].append("File: MISSING")
            result["issues"].append("fee_gate_learning.json missing - needs regeneration")
            self._regenerate_fee_gate_defaults(fee_gate_path)
            result["checks"].append("Auto-remediated: Created defaults")
        else:
            result["checks"].append("File: EXISTS")
            age = get_file_age_hours(fee_gate_path)
            if age and age < 48:
                result["checks"].append(f"Freshness: FRESH ({age:.1f}h)")
            else:
                result["checks"].append(f"Freshness: STALE ({age:.1f}h)" if age else "Freshness: UNKNOWN")
                result["issues"].append("fee_gate_learning stale (>48h)")
            
            data = load_json(fee_gate_path)
            threshold = data.get("threshold", 0.17)
            
            if 0.10 <= threshold <= 0.30:
                result["checks"].append(f"Threshold: VALID ({threshold:.4f})")
                result["healthy"] = True
            else:
                result["checks"].append(f"Threshold: OUT OF RANGE ({threshold:.4f})")
                result["issues"].append(f"Fee gate threshold {threshold} outside valid range [0.10, 0.30]")
                self._regenerate_fee_gate_defaults(fee_gate_path)
                result["checks"].append("Auto-remediated: Reset to defaults")
        
        if not result["issues"]:
            result["healthy"] = True
        
        return result
    
    def _regenerate_fee_gate_defaults(self, path: str):
        """Regenerate fee gate defaults."""
        defaults = {
            "threshold": 0.17,
            "min_buffer_multiplier": 1.2,
            "updated_at": datetime.now().isoformat(),
            "auto_generated": True,
            "history": []
        }
        save_json(path, defaults)
        print(f"   ⚕️ Regenerated fee gate defaults at {path}")
    
    def check_hold_time_health(self) -> Dict:
        """
        Check hold time policy health.
        - Check feature_store/hold_time_policy.json exists and is fresh
        - Verify min_hold_seconds values are sensible (60-7200)
        - Auto-remediate: run hold time learner or reset to defaults
        """
        result = {
            "name": "Hold Time Policy",
            "healthy": False,
            "checks": [],
            "issues": []
        }
        
        hold_time_path = CRITICAL_FILES.get("hold_time_policy", "feature_store/hold_time_policy.json")
        
        if not os.path.exists(hold_time_path):
            result["checks"].append("File: MISSING")
            result["issues"].append("hold_time_policy.json missing")
            self._regenerate_hold_time_defaults(hold_time_path)
            result["checks"].append("Auto-remediated: Created defaults")
        else:
            result["checks"].append("File: EXISTS")
            age = get_file_age_hours(hold_time_path)
            if age and age < 48:
                result["checks"].append(f"Freshness: FRESH ({age:.1f}h)")
            else:
                result["checks"].append(f"Freshness: STALE ({age:.1f}h)" if age else "Freshness: UNKNOWN")
                result["issues"].append("hold_time_policy stale (>48h)")
            
            data = load_json(hold_time_path)
            symbol_holds = data.get("symbol_hold_times", {})
            
            invalid_holds = []
            for symbol, hold_sec in symbol_holds.items():
                if not (60 <= hold_sec <= 7200):
                    invalid_holds.append(f"{symbol}={hold_sec}s")
            
            if not invalid_holds:
                result["checks"].append(f"Hold times: VALID ({len(symbol_holds)} symbols)")
                result["healthy"] = True
            else:
                result["checks"].append(f"Hold times: {len(invalid_holds)} INVALID")
                result["issues"].append(f"Invalid hold times: {', '.join(invalid_holds[:5])}")
                self._regenerate_hold_time_defaults(hold_time_path)
                result["checks"].append("Auto-remediated: Reset to defaults")
        
        if not result["issues"]:
            result["healthy"] = True
        
        return result
    
    def _regenerate_hold_time_defaults(self, path: str):
        """Regenerate hold time policy defaults with profitable minimum hold times."""
        defaults = {
            "version": 1,
            "updated_at": datetime.now().isoformat(),
            "symbol_hold_times": {
                "BTCUSDT": 1800, "ETHUSDT": 1800, "BNBUSDT": 1200, "SOLUSDT": 1500,
                "XRPUSDT": 1200, "ADAUSDT": 1200, "DOTUSDT": 1500, "LINKUSDT": 1800,
                "AVAXUSDT": 1800, "MATICUSDT": 1200, "OPUSDT": 1800, "ARBUSDT": 1200,
                "DOGEUSDT": 1200, "TRXUSDT": 3600, "PEPEUSDT": 1800
            },
            "tier_defaults": {"major": 1800, "other_major": 1500, "altcoin": 1200},
            "auto_generated": True,
            "note": "Defaults set to 20-30min minimum based on data showing 'medium' duration is profitable while 'quick' loses money"
        }
        save_json(path, defaults)
        print(f"   ⚕️ Regenerated hold time defaults at {path}")
    
    def check_hold_time_guardian(self) -> Dict:
        """Run the hold time guardian to detect and fix premature exits."""
        result = {
            "name": "Hold Time Guardian",
            "healthy": True,
            "checks": [],
            "issues": [],
            "fixes_applied": 0
        }
        
        try:
            from src.hold_time_guardian import run_guardian_check, get_guardian_status
            
            status = get_guardian_status()
            result["checks"].append(f"Last check: {status.get('last_check', 'never')}")
            result["checks"].append(f"Total fixes applied: {status.get('total_fixes', 0)}")
            
            if status.get("symbols_below_floor"):
                result["issues"].append(f"Symbols below floor: {status['symbols_below_floor']}")
            
            guardian_result = run_guardian_check()
            
            if guardian_result.get("violations_detected", 0) > 0:
                result["checks"].append(f"Violations detected: {guardian_result['violations_detected']}")
                if guardian_result.get("fix_result", {}).get("fixes_applied", 0) > 0:
                    result["fixes_applied"] = guardian_result["fix_result"]["fixes_applied"]
                    result["checks"].append(f"Auto-fixed: {result['fixes_applied']} violations")
            else:
                result["checks"].append("No violations detected")
            
            result["healthy"] = len(result["issues"]) == 0
            
        except Exception as e:
            result["issues"].append(f"Guardian error: {e}")
            result["healthy"] = False
        
        return result
    
    def check_edge_sizer_health(self) -> Dict:
        """
        Check edge sizer calibration health.
        - Check feature_store/edge_sizer_calibration.json exists
        - Verify grade multipliers are within bounds (0.3-2.0)
        - Auto-remediate: reset to conservative defaults
        """
        result = {
            "name": "Edge Sizer Calibration",
            "healthy": False,
            "checks": [],
            "issues": []
        }
        
        edge_sizer_path = CRITICAL_FILES.get("edge_sizer_calibration", "feature_store/edge_sizer_calibration.json")
        
        if not os.path.exists(edge_sizer_path):
            result["checks"].append("File: MISSING")
            result["issues"].append("edge_sizer_calibration.json missing")
            self._regenerate_edge_sizer_defaults(edge_sizer_path)
            result["checks"].append("Auto-remediated: Created defaults")
        else:
            result["checks"].append("File: EXISTS")
            age = get_file_age_hours(edge_sizer_path)
            if age and age < 48:
                result["checks"].append(f"Freshness: FRESH ({age:.1f}h)")
            else:
                result["checks"].append(f"Freshness: STALE ({age:.1f}h)" if age else "Freshness: UNKNOWN")
            
            data = load_json(edge_sizer_path)
            multipliers = data.get("multipliers", {})
            
            invalid_mults = []
            for grade, mult in multipliers.items():
                if not (0.3 <= mult <= 2.0):
                    invalid_mults.append(f"{grade}={mult}")
            
            if not invalid_mults:
                result["checks"].append(f"Multipliers: VALID ({len(multipliers)} grades)")
                result["healthy"] = True
            else:
                result["checks"].append(f"Multipliers: {len(invalid_mults)} OUT OF BOUNDS")
                result["issues"].append(f"Invalid multipliers: {', '.join(invalid_mults)}")
                self._regenerate_edge_sizer_defaults(edge_sizer_path)
                result["checks"].append("Auto-remediated: Reset to defaults")
        
        if not result["issues"]:
            result["healthy"] = True
        
        return result
    
    def _regenerate_edge_sizer_defaults(self, path: str):
        """Regenerate edge sizer calibration defaults."""
        defaults = {
            "version": 1,
            "updated_at": datetime.now().isoformat(),
            "multipliers": {"A": 1.5, "B": 1.2, "C": 1.0, "D": 0.7, "F": 0.5},
            "min_multiplier": 0.3,
            "max_multiplier": 2.0,
            "auto_generated": True
        }
        save_json(path, defaults)
        print(f"   ⚕️ Regenerated edge sizer defaults at {path}")
    
    def check_correlation_throttle_health(self) -> Dict:
        """
        Check correlation throttle health.
        - Check correlation matrix freshness in feature_store/coinglass_correlations.json
        - Alert if matrix is >24h stale
        - Auto-remediate: trigger correlation refresh or use fallback
        """
        result = {
            "name": "Correlation Throttle",
            "healthy": False,
            "checks": [],
            "issues": []
        }
        
        corr_path = CRITICAL_FILES.get("coinglass_correlations", "feature_store/coinglass_correlations.json")
        throttle_policy_path = "feature_store/correlation_throttle_policy.json"
        
        corr_exists = os.path.exists(corr_path)
        policy_exists = os.path.exists(throttle_policy_path)
        
        if not corr_exists and not policy_exists:
            result["checks"].append("Correlation data: MISSING")
            result["issues"].append("No correlation data available")
            self._regenerate_correlation_defaults(throttle_policy_path)
            result["checks"].append("Auto-remediated: Created fallback policy")
        else:
            if corr_exists:
                result["checks"].append("Correlation matrix: EXISTS")
                age = get_file_age_hours(corr_path)
                if age and age < 24:
                    result["checks"].append(f"Matrix freshness: FRESH ({age:.1f}h)")
                else:
                    result["checks"].append(f"Matrix freshness: STALE ({age:.1f}h)" if age else "Matrix freshness: UNKNOWN")
                    result["issues"].append("Correlation matrix stale (>24h)")
            
            if policy_exists:
                result["checks"].append("Throttle policy: EXISTS")
                data = load_json(throttle_policy_path)
                threshold = data.get("high_corr_threshold", 0.7)
                if 0.5 <= threshold <= 0.9:
                    result["checks"].append(f"Threshold: VALID ({threshold:.2f})")
                else:
                    result["checks"].append(f"Threshold: INVALID ({threshold:.2f})")
                    result["issues"].append(f"Correlation threshold {threshold} outside range [0.5, 0.9]")
        
        if not result["issues"]:
            result["healthy"] = True
        
        return result
    
    def _regenerate_correlation_defaults(self, path: str):
        """Regenerate correlation throttle defaults."""
        defaults = {
            "version": 1,
            "updated_at": datetime.now().isoformat(),
            "high_corr_threshold": 0.7,
            "extreme_corr_threshold": 0.85,
            "max_cluster_exposure_pct": 0.30,
            "max_positions_per_cluster": 3,
            "clusters": {
                "BTC": ["BTCUSDT", "ETHUSDT", "SOLUSDT"],
                "ALT": ["AVAXUSDT", "DOTUSDT", "ARBUSDT", "OPUSDT"],
                "MEME": ["DOGEUSDT", "PEPEUSDT"],
                "STABLE": ["BNBUSDT", "XRPUSDT", "ADAUSDT", "TRXUSDT", "LINKUSDT", "MATICUSDT"]
            },
            "auto_generated": True
        }
        save_json(path, defaults)
        print(f"   ⚕️ Regenerated correlation throttle defaults at {path}")
    
    def check_strategic_advisor_health(self) -> Dict:
        """
        Check strategic advisor health.
        - Check feature_store/strategic_advisor_state.json freshness
        - Verify last run was <2h ago
        - Auto-remediate: trigger advisor run
        """
        result = {
            "name": "Strategic Advisor",
            "healthy": False,
            "checks": [],
            "issues": []
        }
        
        advisor_path = CRITICAL_FILES.get("strategic_advisor_state", DR.STRATEGIC_ADVISOR_STATE)
        
        if not os.path.exists(advisor_path):
            result["checks"].append("State file: MISSING")
            result["issues"].append("strategic_advisor_state.json missing")
            
            try:
                from src.strategic_advisor import StrategicAdvisor
                advisor = StrategicAdvisor()
                advisor.run_hourly_analysis()
                result["checks"].append("Auto-remediated: Triggered advisor run")
            except Exception as e:
                result["checks"].append(f"Auto-remediation failed: {e}")
        else:
            result["checks"].append("State file: EXISTS")
            age = get_file_age_hours(advisor_path)
            
            if age and age < 2:
                result["checks"].append(f"Last run: RECENT ({age:.1f}h ago)")
                result["healthy"] = True
            elif age and age < 24:
                result["checks"].append(f"Last run: {age:.1f}h ago (acceptable)")
                result["healthy"] = True
            else:
                result["checks"].append(f"Last run: STALE ({age:.1f}h ago)" if age else "Last run: UNKNOWN")
                result["issues"].append("Strategic advisor not running regularly")
                
                try:
                    from src.strategic_advisor import StrategicAdvisor
                    advisor = StrategicAdvisor()
                    advisor.run_hourly_analysis()
                    result["checks"].append("Auto-remediated: Triggered advisor run")
                except Exception as e:
                    result["checks"].append(f"Auto-remediation failed: {e}")
            
            data = load_json(advisor_path)
            runs = data.get("runs_count", 0)
            recs = data.get("total_recommendations", 0)
            result["checks"].append(f"Total runs: {runs}, Recommendations: {recs}")
        
        if not result["issues"]:
            result["healthy"] = True
        
        return result
    
    def check_streak_filter_health(self) -> Dict:
        """
        Check streak filter health for both Alpha and Beta bots.
        - Detect if filter is blocking all trades
        - Auto-reset if blocked too long or too many skips
        """
        result = {
            "name": "Streak Filter",
            "healthy": False,
            "checks": [],
            "issues": []
        }
        
        try:
            from src.streak_filter import run_streak_health_check, AUTO_RESET_CONFIG
            
            streak_health = run_streak_health_check()
            
            for bot_type, bot_data in streak_health.get("bots", {}).items():
                stats = bot_data.get("stats", {})
                skips = stats.get("trades_skipped", 0)
                allowed = stats.get("trades_allowed", 0)
                last_win = stats.get("last_trade_win", True)
                
                status = "OK" if bot_data.get("healthy") else "BLOCKED"
                result["checks"].append(f"{bot_type.upper()}: {status} (skips={skips}, allowed={allowed})")
                
                for issue in bot_data.get("issues", []):
                    result["issues"].append(f"{bot_type.upper()}: {issue}")
            
            if streak_health.get("auto_resets"):
                for bot in streak_health["auto_resets"]:
                    result["checks"].append(f"Auto-reset applied to {bot.upper()}")
            
            result["checks"].append(f"Auto-reset thresholds: {AUTO_RESET_CONFIG['max_skips_before_reset']} skips, {AUTO_RESET_CONFIG['max_hours_blocked']}h blocked")
            
            result["healthy"] = streak_health.get("healthy", False)
            
        except Exception as e:
            result["issues"].append(f"Streak filter check failed: {e}")
        
        if not result["issues"]:
            result["healthy"] = True
        
        return result
    
    def run_auto_remediation(self, issues: List[Dict]) -> List[Dict]:
        """Auto-remediate discovered issues."""
        remediations = []
        
        for issue in issues:
            name = issue.get("name", "")
            problems = issue.get("issues", [])
            
            for problem in problems:
                remediation = self._attempt_remediation(name, problem)
                if remediation:
                    remediations.append(remediation)
        
        return remediations
    
    def _attempt_remediation(self, component: str, problem: str) -> Optional[Dict]:
        """Attempt to remediate a specific problem."""
        remediation = {
            "component": component,
            "problem": problem,
            "action": None,
            "success": False,
            "timestamp": datetime.now().isoformat()
        }
        
        # CRITICAL: Portfolio/positions file corruption - restore from backup
        if component in ["portfolio_master", "positions_futures"]:
            if "empty" in problem.lower() or "error" in problem.lower() or "parse" in problem.lower():
                try:
                    path = CRITICAL_FILES.get(component)
                    print(f"\n🚨 CRITICAL: {component} corruption detected - attempting restore...")
                    if DR.restore_from_backup(path):
                        remediation["action"] = f"Restored {component} from backup"
                        remediation["success"] = True
                    else:
                        remediation["action"] = f"No backup available for {component}"
                        remediation["success"] = False
                except Exception as e:
                    remediation["action"] = f"Restore failed: {e}"
                return remediation
        
        if "stale" in problem.lower() or "rules" in problem.lower():
            try:
                from src.daily_intelligence_learner import run_daily_analysis
                print(f"\n🔧 AUTO-REMEDIATION: Running daily learning for {component}...")
                run_daily_analysis(save_snapshot=True)
                remediation["action"] = "Ran daily learning cycle"
                remediation["success"] = True
            except Exception as e:
                remediation["action"] = f"Failed to run learning: {e}"
        
        elif "missing" in problem.lower():
            try:
                if "rules" in problem.lower():
                    from src.daily_intelligence_learner import run_daily_analysis
                    run_daily_analysis(save_snapshot=True)
                    remediation["action"] = "Generated missing rules file"
                    remediation["success"] = True
                elif "history" in problem.lower():
                    from src.daily_intelligence_learner import run_daily_analysis
                    run_daily_analysis(save_snapshot=True)
                    remediation["action"] = "Created learning history"
                    remediation["success"] = True
            except Exception as e:
                remediation["action"] = f"Failed to create file: {e}"
        
        elif "import" in problem.lower():
            remediation["action"] = "Manual fix required - check module imports"
            remediation["success"] = False
        
        return remediation if remediation["action"] else None
    
    def run_full_health_check(self, auto_remediate: bool = True) -> Dict:
        """Run comprehensive health check on all learning systems."""
        with self._lock:
            print("\n" + "="*70)
            print("🏥 LEARNING HEALTH MONITOR - Full System Check")
            print("="*70)
            print(f"Check time: {datetime.now().isoformat()}")
            
            all_healthy = True
            all_issues = []
            components = {}
            
            print("\n📁 FILE CHECKS:")
            print("-"*50)
            for name, path in CRITICAL_FILES.items():
                exists_ok, exists_msg = self.check_file_exists(name, path)
                fresh_ok, fresh_msg = self.check_file_freshness(name, path)
                valid_ok, valid_msg = self.check_file_integrity(name, path)
                
                status = "✅" if (exists_ok and fresh_ok and valid_ok) else "❌"
                print(f"   {status} {name}")
                print(f"      {exists_msg}")
                print(f"      {fresh_msg}")
                print(f"      {valid_msg}")
                
                if not (exists_ok and fresh_ok and valid_ok):
                    all_healthy = False
                    all_issues.append({
                        "name": name,
                        "issues": [msg for ok, msg in [(exists_ok, exists_msg), (fresh_ok, fresh_msg), (valid_ok, valid_msg)] if not ok]
                    })
            
            print("\n🔧 COMPONENT CHECKS:")
            print("-"*50)
            
            daily_check = self.check_daily_learner()
            components["daily_learner"] = daily_check
            status = "✅" if daily_check["healthy"] else "❌"
            print(f"   {status} {daily_check['name']}")
            for check in daily_check["checks"]:
                print(f"      {check}")
            if daily_check["issues"]:
                all_healthy = False
                all_issues.append(daily_check)
            
            history_check = self.check_learning_history()
            components["learning_history"] = history_check
            status = "✅" if history_check["healthy"] else "❌"
            print(f"   {status} {history_check['name']}")
            for check in history_check["checks"]:
                print(f"      {check}")
            if history_check["issues"]:
                all_healthy = False
                all_issues.append(history_check)
            
            data_check = self.check_data_pipeline()
            components["data_pipeline"] = data_check
            status = "✅" if data_check["healthy"] else "❌"
            print(f"   {status} {data_check['name']}")
            for check in data_check["checks"]:
                print(f"      {check}")
            if data_check["issues"]:
                all_healthy = False
                all_issues.append(data_check)
            
            overlay_check = self.check_conditional_overlay()
            components["conditional_overlay"] = overlay_check
            status = "✅" if overlay_check["healthy"] else "❌"
            print(f"   {status} {overlay_check['name']}")
            for check in overlay_check["checks"]:
                print(f"      {check}")
            if overlay_check["issues"]:
                all_healthy = False
                all_issues.append(overlay_check)
            
            print("\n🎯 PROFITABILITY ACCELERATION MODULE CHECKS:")
            print("-"*50)
            
            fee_gate_check = self.check_fee_gate_health()
            components["fee_gate_learning"] = fee_gate_check
            status = "✅" if fee_gate_check["healthy"] else "❌"
            print(f"   {status} {fee_gate_check['name']}")
            for check in fee_gate_check["checks"]:
                print(f"      {check}")
            if fee_gate_check["issues"]:
                all_healthy = False
                all_issues.append(fee_gate_check)
            
            hold_time_check = self.check_hold_time_health()
            components["hold_time_policy"] = hold_time_check
            status = "✅" if hold_time_check["healthy"] else "❌"
            print(f"   {status} {hold_time_check['name']}")
            for check in hold_time_check["checks"]:
                print(f"      {check}")
            if hold_time_check["issues"]:
                all_healthy = False
                all_issues.append(hold_time_check)
            
            edge_sizer_check = self.check_edge_sizer_health()
            components["edge_sizer_calibration"] = edge_sizer_check
            status = "✅" if edge_sizer_check["healthy"] else "❌"
            print(f"   {status} {edge_sizer_check['name']}")
            for check in edge_sizer_check["checks"]:
                print(f"      {check}")
            if edge_sizer_check["issues"]:
                all_healthy = False
                all_issues.append(edge_sizer_check)
            
            corr_throttle_check = self.check_correlation_throttle_health()
            components["correlation_throttle"] = corr_throttle_check
            status = "✅" if corr_throttle_check["healthy"] else "❌"
            print(f"   {status} {corr_throttle_check['name']}")
            for check in corr_throttle_check["checks"]:
                print(f"      {check}")
            if corr_throttle_check["issues"]:
                all_healthy = False
                all_issues.append(corr_throttle_check)
            
            strategic_check = self.check_strategic_advisor_health()
            components["strategic_advisor"] = strategic_check
            status = "✅" if strategic_check["healthy"] else "❌"
            print(f"   {status} {strategic_check['name']}")
            for check in strategic_check["checks"]:
                print(f"      {check}")
            if strategic_check["issues"]:
                all_healthy = False
                all_issues.append(strategic_check)
            
            streak_check = self.check_streak_filter_health()
            components["streak_filter"] = streak_check
            status = "✅" if streak_check["healthy"] else "❌"
            print(f"   {status} {streak_check['name']}")
            for check in streak_check["checks"]:
                print(f"      {check}")
            if streak_check["issues"]:
                all_healthy = False
                all_issues.append(streak_check)
            
            guardian_check = self.check_hold_time_guardian()
            components["hold_time_guardian"] = guardian_check
            status = "✅" if guardian_check["healthy"] else "🛡️"
            print(f"   {status} {guardian_check['name']}")
            for check in guardian_check["checks"]:
                print(f"      {check}")
            if guardian_check.get("fixes_applied", 0) > 0:
                print(f"      🔧 Auto-fixed {guardian_check['fixes_applied']} hold time violations")
            if guardian_check["issues"]:
                all_healthy = False
                all_issues.append(guardian_check)
            
            remediations = []
            if auto_remediate and all_issues:
                print("\n🔧 AUTO-REMEDIATION:")
                print("-"*50)
                remediations = self.run_auto_remediation(all_issues)
                for rem in remediations:
                    status = "✅" if rem["success"] else "❌"
                    print(f"   {status} {rem['component']}: {rem['action']}")
            
            overall = "HEALTHY" if all_healthy else ("REMEDIATED" if any(r["success"] for r in remediations) else "DEGRADED")
            
            self.status = {
                "last_check": datetime.now().isoformat(),
                "overall_health": overall,
                "components": components,
                "issues": [{"name": i.get("name"), "problems": i.get("issues", [])} for i in all_issues],
                "remediations": remediations,
                "all_healthy": all_healthy
            }
            
            save_json(HEALTH_STATUS_PATH, self.status)
            
            append_jsonl(HEALTH_HISTORY_PATH, {
                "timestamp": datetime.now().isoformat(),
                "overall": overall,
                "healthy": all_healthy,
                "issue_count": len(all_issues),
                "remediation_count": len(remediations)
            })
            
            print("\n" + "="*70)
            print(f"🏥 OVERALL HEALTH: {overall}")
            print("="*70)
            
            return self.status
    
    def get_status(self) -> Dict:
        """Get current health status."""
        if os.path.exists(HEALTH_STATUS_PATH):
            return load_json(HEALTH_STATUS_PATH)
        return self.status


_monitor_instance = None
_monitor_thread = None


def get_monitor() -> LearningHealthMonitor:
    """Get singleton monitor instance."""
    global _monitor_instance
    if _monitor_instance is None:
        _monitor_instance = LearningHealthMonitor()
    return _monitor_instance


def run_periodic_health_check(interval_minutes: int = 30, initial_delay_minutes: int = 5):
    """Run health checks periodically.
    
    Args:
        interval_minutes: Minutes between health checks
        initial_delay_minutes: Delay before first check to let bot stabilize (avoids startup memory spike)
    """
    monitor = get_monitor()
    
    if initial_delay_minutes > 0:
        print(f"   ⏳ Deferring first auto-remediation by {initial_delay_minutes}min to avoid startup memory spike")
        time.sleep(initial_delay_minutes * 60)
    
    while True:
        try:
            monitor.run_full_health_check(auto_remediate=True)
        except Exception as e:
            print(f"❌ Health check error: {e}")
            traceback.print_exc()
        
        time.sleep(interval_minutes * 60)


def start_health_monitor_daemon(interval_minutes: int = 30):
    """Start health monitor as background daemon."""
    global _monitor_thread
    
    if _monitor_thread is not None and _monitor_thread.is_alive():
        print("🏥 Health monitor already running")
        return
    
    _monitor_thread = threading.Thread(
        target=run_periodic_health_check,
        args=(interval_minutes,),
        daemon=True,
        name="LearningHealthMonitor"
    )
    _monitor_thread.start()
    print(f"🏥 Learning health monitor started (interval: {interval_minutes}min)")


if __name__ == "__main__":
    import sys
    
    if "--daemon" in sys.argv:
        interval = 30
        for arg in sys.argv:
            if arg.startswith("--interval="):
                interval = int(arg.split("=")[1])
        
        print(f"Starting health monitor daemon (interval: {interval}min)...")
        run_periodic_health_check(interval)
    else:
        monitor = LearningHealthMonitor()
        monitor.run_full_health_check(auto_remediate=True)
