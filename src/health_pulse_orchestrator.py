# src/health_pulse_orchestrator.py

import os
import json
import time
from typing import Dict, List, Optional
from collections import defaultdict

EVENTS_LOG = "logs/unified_events.jsonl"
HEALTH_STATE = "logs/health_pulse_state.json"

def _read_jsonl(path: str) -> List[dict]:
    if not os.path.exists(path):
        return []
    out = []
    with open(path, "r") as f:
        for line in f:
            try:
                out.append(json.loads(line))
            except:
                continue
    return out

def _append_json(path: str, obj: dict):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "a") as f:
        f.write(json.dumps(obj) + "\n")

def log_health_event(event: str, payload: dict = None):
    payload = dict(payload or {})
    payload.update({"ts": int(time.time()), "event": event})
    _append_json(EVENTS_LOG, payload)

def get_recent_events(minutes: int = 30) -> List[dict]:
    now = int(time.time())
    return [e for e in _read_jsonl(EVENTS_LOG) if (now - int(e.get("ts", now))) <= minutes * 60]

def count_recent_trades(minutes: int = 30) -> int:
    """Count trades executed in last N minutes."""
    recent = get_recent_events(minutes)
    trades = [e for e in recent if e.get("event") in (
        "profit_blofin_entry", "entry_opened", "position_opened"
    )]
    return len(trades)

def get_freeze_status() -> Dict[str, any]:
    """Get current freeze state from unified governance."""
    try:
        from src.unified_self_governance_bot import FREEZE_STATE, is_frozen
        now = int(time.time())
        frozen_until = FREEZE_STATE.get("frozen_until", 0)
        freeze_started = FREEZE_STATE.get("freeze_started", 0)
        currently_frozen = frozen_until > now
        
        return {
            "frozen": is_frozen(),
            "frozen_until": frozen_until,
            "elapsed_seconds": max(0, now - freeze_started) if (currently_frozen and freeze_started > 0) else 0
        }
    except Exception as e:
        return {"frozen": False, "error": str(e)}

def get_metrics_freshness() -> Dict[str, any]:
    """Check freshness of performance metrics."""
    try:
        from src.performance_metrics import compute_performance_metrics
        metrics = compute_performance_metrics()
        return {
            "age_hours": metrics.get("age_hours", 0.0),
            "total_fills": metrics.get("total_fills", 0),
            "is_stale": metrics.get("age_hours", 0.0) > 6.0
        }
    except Exception as e:
        return {"age_hours": 999, "total_fills": 0, "is_stale": True, "error": str(e)}

def get_signal_activity(minutes: int = 15) -> Dict[str, int]:
    """Count alpha signals generated recently."""
    recent = get_recent_events(minutes)
    signals = defaultdict(int)
    for e in recent:
        evt_name = e.get("event", "")
        if "alpha" in evt_name.lower() or "signal" in evt_name.lower():
            signals[evt_name] += 1
    return dict(signals)

def get_dashboard_verification_status() -> Dict[str, any]:
    """Check dashboard verification health status."""
    try:
        from src.dashboard_verification import get_verification_service
        service = get_verification_service()
        
        # Try to load cached status first (fast)
        if not service.is_healthy():
            # Cached status shows unhealthy, run full verification
            healthy, status = service.run_verification()
            return status
        else:
            # Cached status shows healthy
            return {
                "healthy": True,
                "severity": "OK",
                "issues": [],
                "suggested_fixes": []
            }
    except Exception as e:
        return {
            "healthy": False,
            "severity": "WARNING",
            "issues": [f"verification_service_error: {str(e)}"],
            "suggested_fixes": []
        }

def get_self_validation_status() -> Dict[str, any]:
    """Check self-validation layer health status."""
    try:
        from src.self_validation import get_validation_orchestrator
        orchestrator = get_validation_orchestrator()
        return orchestrator.get_health_status()
    except Exception as e:
        return {
            "healthy": False,
            "severity": "WARNING",
            "message": f"Self-validation error: {str(e)}",
            "details": {}
        }

def get_data_file_integrity_status() -> Dict[str, any]:
    """
    Check data file integrity - primary vs backup, file existence, staleness.
    Uses centralized check from unified_self_governance_bot.
    """
    try:
        from src.unified_self_governance_bot import verify_data_file_integrity
        is_ok = verify_data_file_integrity()
        return {
            "healthy": is_ok,
            "issue": None if is_ok else "data_file_integrity_check_failed"
        }
    except Exception as e:
        return {
            "healthy": False,
            "issue": f"integrity_check_error: {str(e)}"
        }

def diagnose_health() -> Dict[str, any]:
    """
    Comprehensive health diagnosis.
    
    Returns:
        diagnosis: Classification of current state
        issues: List of detected problems
        recommended_fix: Auto-fix action to take
    """
    now = int(time.time())
    
    # Gather telemetry
    trades_30m = count_recent_trades(30)
    freeze_status = get_freeze_status()
    metrics_status = get_metrics_freshness()
    signals_15m = get_signal_activity(15)
    
    recent_bypasses = [e for e in get_recent_events(5) if "bypass" in e.get("event", "")]
    
    issues = []
    diagnosis = "healthy"
    recommended_fix = None
    
    # Issue 1: Frozen state
    if freeze_status.get("frozen"):
        elapsed_sec = freeze_status.get("elapsed_seconds", 0)
        if elapsed_sec > 3600:  # Frozen >1h
            issues.append(f"frozen_prolonged ({elapsed_sec // 60} minutes)")
            diagnosis = "critical"
            
            # Check if metrics are stale
            if metrics_status.get("is_stale"):
                recommended_fix = "refresh_metrics_and_clear_freeze"
            else:
                recommended_fix = "clear_freeze"
        else:
            issues.append(f"frozen_active ({elapsed_sec // 60} minutes)")
            if not recent_bypasses:
                diagnosis = "degraded"
    
    # Issue 2: Zero trades for extended period (only flag if not recently frozen)
    if trades_30m == 0:
        if freeze_status.get("frozen"):
            issues.append("zero_trades_while_frozen")
        else:
            # Check if signals are generating
            total_signals = sum(signals_15m.values())
            if total_signals == 0:
                issues.append("zero_trades_zero_signals")
                diagnosis = "degraded" if diagnosis == "healthy" else diagnosis
            else:
                issues.append("zero_trades_with_signals")
                diagnosis = "warning"
                recommended_fix = "investigate_filters"
    
    # Issue 3: Stale metrics
    if metrics_status.get("is_stale"):
        issues.append(f"stale_metrics ({metrics_status.get('age_hours', 0):.1f}h)")
        if diagnosis == "healthy":
            diagnosis = "warning"
    
    # Issue 4: Dashboard verification (backend/UI mismatch)
    dashboard_status = get_dashboard_verification_status()
    if not dashboard_status.get("healthy"):
        dashboard_issues = dashboard_status.get("issues", [])
        for issue in dashboard_issues:
            issues.append(f"dashboard_{issue}")
        
        severity = dashboard_status.get("severity", "WARNING")
        if severity == "CRITICAL" and diagnosis in ("healthy", "warning", "degraded"):
            diagnosis = "critical"
        elif severity == "WARNING" and diagnosis == "healthy":
            diagnosis = "warning"
        
        # Set recommended fix for dashboard issues
        if not recommended_fix and dashboard_status.get("suggested_fixes"):
            recommended_fix = dashboard_status["suggested_fixes"][0]
    
    # Issue 5: Self-validation layer (position sizing drift)
    validation_status = get_self_validation_status()
    if not validation_status.get("healthy"):
        issues.append(f"validation_{validation_status.get('message', 'unknown')}")
        
        severity = validation_status.get("severity", "WARNING")
        if severity == "CRITICAL" and diagnosis in ("healthy", "warning", "degraded"):
            diagnosis = "critical"
            # AUTO-REMEDIATION: Freeze trading on systematic drift
            if not recommended_fix:
                recommended_fix = "freeze_trading_validation_drift"
        elif severity == "WARNING" and diagnosis == "healthy":
            diagnosis = "warning"
    
    # Issue 6: Data file integrity (primary vs backup, file paths)
    data_file_status = get_data_file_integrity_status()
    if not data_file_status.get("healthy"):
        issues.append(f"data_file_{data_file_status.get('issue', 'unknown')}")
        diagnosis = "critical" if diagnosis in ("healthy", "warning") else diagnosis
        if not recommended_fix:
            recommended_fix = "fix_data_file_integrity"
    
    return {
        "diagnosis": diagnosis,
        "issues": issues,
        "recommended_fix": recommended_fix,
        "telemetry": {
            "trades_30m": trades_30m,
            "freeze_status": freeze_status,
            "metrics_status": metrics_status,
            "signals_15m": signals_15m,
            "recent_bypasses_count": len(recent_bypasses),
            "dashboard_status": dashboard_status,
            "validation_status": validation_status,
            "data_file_status": data_file_status
        }
    }

def apply_auto_fix(fix_action: str) -> Dict[str, any]:
    """
    Apply recommended fix action.
    
    Returns:
        success: Whether fix was applied
        action: What was done
        error: Error message if failed
    """
    result = {"success": False, "action": fix_action, "error": None}
    
    try:
        if fix_action == "freeze_trading_validation_drift":
            # AUTO-REMEDIATION: Freeze trading when systematic drift detected
            from src.unified_self_governance_bot import freeze_entries
            
            # Freeze for 60 minutes
            freeze_entries(minutes=60)
            
            log_health_event("auto_remediation_freeze_drift", {
                "reason": "systematic_position_sizing_drift",
                "duration_hours": 1.0
            })
            
            result["success"] = True
            result["action"] = "Froze trading for 1 hour due to systematic validation drift"
            print("🔧 [AUTO-REMEDIATE] Trading frozen - systematic drift detected")
            
        elif fix_action == "refresh_metrics_and_clear_freeze":
            # Force metric refresh by triggering evaluation with synchronization
            from src.performance_metrics import compute_performance_metrics
            from src.unified_self_governance_bot import evaluate_kill_switch, clear_freeze, is_frozen, FREEZE_STATE
            
            # Capture current freeze state before refresh
            freeze_before = FREEZE_STATE.get("frozen_until", 0)
            freeze_started_before = FREEZE_STATE.get("freeze_started", 0)
            
            # Compute fresh metrics and re-evaluate kill-switch
            fresh_metrics = compute_performance_metrics()
            was_triggered = evaluate_kill_switch(fresh_metrics)
            
            # Only clear freeze if:
            # 1. It's still frozen after evaluation
            # 2. It's the SAME freeze (not re-triggered by fresh metrics)
            freeze_after = FREEZE_STATE.get("frozen_until", 0)
            
            if is_frozen() and freeze_after == freeze_before and not was_triggered:
                # Same freeze persists after fresh evaluation - safe to clear
                clear_freeze(reason="health_pulse_stale_metrics_persistent_freeze")
                log_health_event("health_pulse_force_unfreeze", {
                    "reason": "stale_metrics_persistent_freeze_after_refresh"
                })
                result["success"] = True
                result["action"] = "Refreshed metrics and cleared stale freeze"
                print("🏥 [HEALTH-PULSE] Auto-fix: Refreshed metrics + cleared stale freeze")
            elif not is_frozen():
                # Freeze was auto-cleared by fresh metrics evaluation
                result["success"] = True
                result["action"] = "Refreshed metrics - freeze auto-cleared"
                print("🏥 [HEALTH-PULSE] Auto-fix: Metrics refreshed, freeze auto-cleared")
            else:
                # Freeze was re-triggered by fresh metrics - respect it
                result["success"] = True
                result["action"] = "Refreshed metrics - freeze re-triggered (legitimate)"
                print("🏥 [HEALTH-PULSE] Auto-fix: Metrics refreshed, freeze re-triggered (risk detected)")
                log_health_event("health_pulse_freeze_retriggered", {
                    "reason": "fresh_metrics_triggered_kill_switch"
                })
        
        elif fix_action == "clear_freeze":
            from src.unified_self_governance_bot import clear_freeze
            clear_freeze(reason="health_pulse_prolonged_freeze")
            log_health_event("health_pulse_clear_freeze", {
                "reason": "prolonged_freeze_no_stale_metrics"
            })
            result["success"] = True
            result["action"] = "Cleared prolonged freeze"
            print("🏥 [HEALTH-PULSE] Auto-fix: Cleared prolonged freeze")
        
        elif fix_action == "investigate_filters":
            # Log issue for manual review
            log_health_event("health_pulse_alert_filter_blocking", {
                "issue": "signals_generating_but_zero_trades",
                "action": "investigate_fee_filters_or_sizing"
            })
            result["success"] = True
            result["action"] = "Logged filter investigation alert"
            print("⚠️ [HEALTH-PULSE] Alert: Signals generating but zero trades (check filters)")
        
        elif fix_action == "AUTO_RESTORE_BACKUP":
            # Dashboard verification detected file corruption
            from src.dashboard_verification import BackendStateCollector
            collector = BackendStateCollector()
            collector._attempt_restore_backup()
            log_health_event("health_pulse_restore_backup", {
                "reason": "dashboard_verification_detected_corruption"
            })
            result["success"] = True
            result["action"] = "Restored positions file from backup"
            print("🔧 [HEALTH-PULSE] Auto-fix: Restored positions file from backup")
        
        elif fix_action == "CHECK_DASHBOARD_FILE_PATH":
            # Log critical alert that dashboard is loading wrong file
            log_health_event("health_pulse_alert_dashboard_mismatch", {
                "issue": "backend_has_positions_but_ui_shows_zero",
                "action": "verify_dashboard_load_function_uses_correct_file_path"
            })
            result["success"] = True
            result["action"] = "Logged dashboard file path mismatch alert"
            print("⚠️ [HEALTH-PULSE] CRITICAL: Backend has positions but UI shows 0 - check dashboard file path!")
        
        elif fix_action == "CHECK_POSITION_SAVE_FUNCTION":
            # Log alert that position save function may be disabled
            log_health_event("health_pulse_alert_stale_positions", {
                "issue": "position_file_not_updated_recently",
                "action": "verify_position_save_function_is_enabled"
            })
            result["success"] = True
            result["action"] = "Logged stale position file alert"
            print("⚠️ [HEALTH-PULSE] Alert: Position file stale - check if save function is commented out!")
        
        elif fix_action == "REFRESH_DASHBOARD_DATA":
            # Force dashboard data refresh by touching the file
            try:
                import os
                futures_log = "logs/positions_futures.json"
                if os.path.exists(futures_log):
                    os.utime(futures_log, None)
                log_health_event("health_pulse_refresh_dashboard", {
                    "action": "touched_file_to_force_refresh"
                })
                result["success"] = True
                result["action"] = "Triggered dashboard data refresh"
                print("🔄 [HEALTH-PULSE] Auto-fix: Triggered dashboard data refresh")
            except Exception as e:
                result["error"] = str(e)
        
        elif fix_action == "fix_data_file_integrity":
            # AUTO-REPAIR: Data file integrity issues (primary vs backup mismatch)
            import os
            import json
            import shutil
            from datetime import datetime
            
            primary_file = "logs/trades_futures.json"
            backup_file = "logs/trades_futures_backup.json"
            repair_log = []
            
            primary_exists = os.path.exists(primary_file)
            backup_exists = os.path.exists(backup_file)
            
            # Case 1: Primary missing but backup exists - restore from backup
            if not primary_exists and backup_exists:
                shutil.copy2(backup_file, primary_file)
                repair_log.append("restored_primary_from_backup")
                print("🔧 [AUTO-REPAIR] Restored primary trades file from backup")
            
            # Case 2: Both exist but primary has fewer trades - merge or copy
            elif primary_exists and backup_exists:
                try:
                    with open(primary_file, 'r') as f:
                        primary_data = json.load(f)
                    with open(backup_file, 'r') as f:
                        backup_data = json.load(f)
                    
                    primary_count = len(primary_data) if isinstance(primary_data, list) else 0
                    backup_count = len(backup_data) if isinstance(backup_data, list) else 0
                    
                    if backup_count > primary_count:
                        # Backup has more trades - merge unique trades
                        if isinstance(primary_data, list) and isinstance(backup_data, list):
                            # Create set of trade IDs from primary
                            primary_ids = set()
                            for t in primary_data:
                                tid = t.get("trade_id") or t.get("id") or f"{t.get('symbol')}_{t.get('entry_time')}"
                                primary_ids.add(tid)
                            
                            # Add unique trades from backup
                            merged_count = 0
                            for t in backup_data:
                                tid = t.get("trade_id") or t.get("id") or f"{t.get('symbol')}_{t.get('entry_time')}"
                                if tid not in primary_ids:
                                    primary_data.append(t)
                                    merged_count += 1
                            
                            # Save merged data with timestamp backup
                            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                            emergency_backup = f"logs/trades_futures_pre_merge_{timestamp}.json"
                            shutil.copy2(primary_file, emergency_backup)
                            
                            with open(primary_file, 'w') as f:
                                json.dump(primary_data, f, indent=2)
                            
                            repair_log.append(f"merged_{merged_count}_trades_from_backup")
                            print(f"🔧 [AUTO-REPAIR] Merged {merged_count} missing trades from backup into primary")
                except json.JSONDecodeError as je:
                    # Primary file corrupted - restore from backup
                    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                    corrupted_backup = f"logs/trades_futures_corrupted_{timestamp}.json"
                    shutil.copy2(primary_file, corrupted_backup)
                    shutil.copy2(backup_file, primary_file)
                    repair_log.append("restored_primary_corrupted_json")
                    print("🔧 [AUTO-REPAIR] Primary file corrupted - restored from backup")
            
            # Case 3: Neither exists - create empty primary
            elif not primary_exists and not backup_exists:
                with open(primary_file, 'w') as f:
                    json.dump([], f)
                repair_log.append("created_empty_primary")
                print("🔧 [AUTO-REPAIR] Created empty primary trades file")
            
            # Log the repair
            log_health_event("auto_repair_data_file_integrity", {
                "repairs": repair_log,
                "primary_exists_after": os.path.exists(primary_file),
                "backup_exists": backup_exists
            })
            
            result["success"] = True
            result["action"] = f"Data file integrity repaired: {', '.join(repair_log) if repair_log else 'no issues found'}"
            print(f"✅ [AUTO-REPAIR] Data file integrity check complete: {repair_log}")
        
    except Exception as e:
        result["error"] = str(e)
        log_health_event("health_pulse_auto_fix_failed", {
            "fix_action": fix_action,
            "error": str(e)
        })
        print(f"❌ [HEALTH-PULSE] Auto-fix failed: {e}")
    
    return result

def health_pulse_cycle():
    """
    Main health pulse orchestrator - runs every minute.
    
    Detects trading stalls, diagnoses root cause, and applies auto-fixes.
    """
    try:
        diagnosis = diagnose_health()
        
        # Log health snapshot
        log_health_event("health_pulse_check", {
            "diagnosis": diagnosis["diagnosis"],
            "issues": diagnosis["issues"],
            "telemetry": diagnosis["telemetry"]
        })
        
        # Apply auto-fix if needed
        if diagnosis.get("recommended_fix"):
            fix_result = apply_auto_fix(diagnosis["recommended_fix"])
            
            if fix_result["success"]:
                log_health_event("health_pulse_auto_fix_applied", {
                    "fix": diagnosis["recommended_fix"],
                    "result": fix_result
                })
                print(f"✅ [HEALTH-PULSE] Auto-fix applied: {fix_result['action']}")
            else:
                log_health_event("health_pulse_auto_fix_failed", {
                    "fix": diagnosis["recommended_fix"],
                    "error": fix_result.get("error")
                })
                print(f"❌ [HEALTH-PULSE] Auto-fix failed: {fix_result.get('error')}")
        
        # Status reporting
        if diagnosis["diagnosis"] == "critical":
            print(f"🚨 [HEALTH-PULSE] CRITICAL: {', '.join(diagnosis['issues'])}")
        elif diagnosis["diagnosis"] == "degraded":
            print(f"⚠️ [HEALTH-PULSE] DEGRADED: {', '.join(diagnosis['issues'])}")
        elif diagnosis["diagnosis"] == "warning":
            print(f"💡 [HEALTH-PULSE] Warning: {', '.join(diagnosis['issues'])}")
        else:
            # Only log healthy status every 10 minutes to reduce noise
            recent_health_checks = [e for e in get_recent_events(10) 
                                   if e.get("event") == "health_pulse_healthy_quiet"]
            if not recent_health_checks:
                log_health_event("health_pulse_healthy_quiet", {})
        
    except Exception as e:
        log_health_event("health_pulse_cycle_error", {"error": str(e)})
        print(f"❌ [HEALTH-PULSE] Cycle error: {e}")

def start_health_pulse_monitor():
    """Start health pulse monitoring as periodic task."""
    import threading
    
    def _run():
        while True:
            time.sleep(60)  # Run every minute
            try:
                health_pulse_cycle()
            except Exception as e:
                print(f"❌ [HEALTH-PULSE] Monitor error: {e}")
    
    thread = threading.Thread(target=_run, daemon=True, name="HealthPulse")
    thread.start()
    log_health_event("health_pulse_monitor_started", {})
    print("🏥 [HEALTH-PULSE] Monitor started (1-minute intervals)")
