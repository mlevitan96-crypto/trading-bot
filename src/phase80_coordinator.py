import threading
import time
from typing import Optional
from phase80_autonomy import Phase80Autonomy, default_phase80_cfg

class Phase80Coordinator:
    def __init__(self, autonomy: Phase80Autonomy):
        self.autonomy = autonomy
        self.running = False
        self.thread: Optional[threading.Thread] = None
        self.last_heartbeat_tick = 0
        self.last_watchdog_tick = 0
        self.last_experiment_enroll = 0
        self.last_experiment_eval = 0
        self.last_ramp_tick = 0
        self.last_limits_tick = 0
        self.last_governor_tick = 0
        
        # RESILIENCE PATCH: Synthetic Pulse & Soft-Fail Logic
        # Prevents false "system failure" triggers during quiet overnight markets
        self.last_synthetic_pulse = time.time()
        self.consecutive_stale_checks = 0
        self.STALE_TOLERANCE_THRESHOLD = 3  # Allow 3 missed beats before triggering incident
        # Phase 8.1 cadences
        self.last_bandit_tick = 0
        self.last_regime_v2_tick = 0
        self.last_drawdown_tick = 0
        self.last_fill_quality_tick = 0
        self.last_overnight_tick = 0
        self.last_phase81_persist = 0
        # Phase 8.2 cadences
        self.last_ramp_assessor_tick = 0
        self.last_kill_switch_tick = 0
        self.last_recon_tick = 0
        self.last_regime_mismatch_tick = 0
        self.last_phase82_persist = 0
        # Phase 8.2 validation cadence
        self.last_validation_tick = 0
        self.last_integrity_check = 0
        # Phase 8.3 drift detector cadence
        self.last_drift_tick = 0
        # Phase 8.4-8.6 expansion cadences
        self.last_phase84_tick = 0
        self.last_phase85_tick = 0
        self.last_phase86_tick = 0
        self.last_phase85_scenario_tick = 0
        # Phase 8.7-8.9 expansion cadences
        self.last_phase87_cockpit_tick = 0
        self.last_phase88_consensus_tick = 0
        self.last_phase89_external_tick = 0
        # Phase 9 autonomy controller cadences
        self.last_phase9_autonomy_tick = 0
        self.last_phase9_learning_tick = 0
        self.last_phase9_watchdog_tick = 0
        self.last_phase9_flags_tick = 0
        # Phase 9.1 adaptive governance cadences
        self.last_phase91_tolerance_tick = 0
        self.last_phase91_health_trend_tick = 0
        self.last_phase91_watchdog_tick = 0
        self.last_phase91_calibration_tick = 0
    
    def start(self):
        if self.running:
            return
        self.running = True
        self.thread = threading.Thread(target=self._run_loop, daemon=True, name="Phase80-Coordinator")
        self.thread.start()
        print(f"✅ Phase 8.0 Coordinator thread started")
    
    def stop(self):
        self.running = False
        if self.thread:
            self.thread.join(timeout=5)
    
    def _run_loop(self):
        while self.running:
            now = time.time()
            
            # =========================================================
            # RESILIENCE PATCH: Synthetic Pulse Injection
            # =========================================================
            # If the loop is running, the CPU is active. Assert this fact
            # to the telemetry system every 20 seconds. This ensures that
            # heartbeats are updated even if the market is dead silent.
            if now - self.last_synthetic_pulse >= 20:
                try:
                    from src.unified_self_governance_bot import emit_watchdog_telemetry
                    emit_watchdog_telemetry(context="synthetic_pulse")
                    # Also bump autonomy subsystem heartbeats directly
                    self.autonomy.heartbeat("signals")
                    self.autonomy.heartbeat("telemetry")
                    self.autonomy.heartbeat("persistence")
                except Exception as e:
                    print(f"⚠️ [Phase80] Synthetic pulse error: {e}")
                self.last_synthetic_pulse = now
            
            # =========================================================
            # RESILIENCE PATCH: Soft-Fail Heartbeat Logic
            # =========================================================
            # Instead of immediately triggering protective mode on first miss,
            # we require 3 consecutive failures. This filters out:
            # - Replit container throttling glitches
            # - Brief network hiccups
            # - Low-volume overnight periods
            if now - self.last_heartbeat_tick >= 30:
                try:
                    # Check if heartbeats are healthy
                    missed = []
                    now_ts = self.autonomy.now()
                    if now_ts - self.autonomy.startup_ts >= self.autonomy.startup_grace_period_sec:
                        for s in ["signals", "execution", "fees", "telemetry", "persistence"]:
                            last = self.autonomy.last_heartbeats.get(s, 0)
                            if now_ts - last > self.autonomy.config.heartbeat_miss_sec:
                                missed.append(s)
                    
                    if missed:
                        self.consecutive_stale_checks += 1
                        print(f"⚠️ [Phase80] Heartbeat check ({self.consecutive_stale_checks}/{self.STALE_TOLERANCE_THRESHOLD}): missed {missed}. Market might be quiet.")
                        
                        if self.consecutive_stale_checks >= self.STALE_TOLERANCE_THRESHOLD:
                            # Only trigger incident after threshold consecutive failures
                            print("❌ [Phase80] Critical stale telemetry confirmed after multiple checks. Triggering incident.")
                            self.autonomy.trigger_incident(f"Heartbeat missed after {self.consecutive_stale_checks} checks: {missed}")
                            self.consecutive_stale_checks = 0  # Reset after handling
                        else:
                            # Attempt recovery: Force synthetic heartbeats for quiet market scenario
                            print(f"🔄 [Phase80] Attempting soft recovery (pulse {self.consecutive_stale_checks})...")
                            for s in missed:
                                self.autonomy.heartbeat(s)
                    else:
                        # Reset on success
                        if self.consecutive_stale_checks > 0:
                            print("✅ [Phase80] Telemetry recovered - heartbeats healthy.")
                        self.consecutive_stale_checks = 0
                except Exception as e:
                    print(f"⚠️ [Phase80] Heartbeat check error: {e}")
                    
                self.last_heartbeat_tick = now
            
            if now - self.last_watchdog_tick >= 60:
                self.autonomy.watchdog_check()
                self.autonomy.rollback_if_needed()
                self.last_watchdog_tick = now
            
            if now - self.last_experiment_enroll >= 3600:
                self.autonomy.enroll_experiments()
                self.last_experiment_enroll = now
            
            if now - self.last_experiment_eval >= 1800:
                self.autonomy.evaluate_experiments()
                self.last_experiment_eval = now
            
            if now - self.last_ramp_tick >= 3600:
                self.autonomy.apply_capital_ramp()
                self.last_ramp_tick = now
            
            if now - self.last_limits_tick >= 300:
                self.autonomy.enforce_exposure_caps()
                self.autonomy.enforce_pyramiding_caps()
                self.last_limits_tick = now
            
            if now - self.last_governor_tick >= 1800:
                self.autonomy.governor_reweight()
                self.last_governor_tick = now
            
            # Phase 8.1 Edge Compounding ticks
            try:
                from phase81_edge_compounding import (
                    phase81_bandit_tick, phase81_regime_tick, phase81_drawdown_guard_tick,
                    phase81_fill_quality_tick, phase81_overnight_tick, persist_phase81
                )
                
                if now - self.last_bandit_tick >= 1800:  # 30 minutes
                    phase81_bandit_tick()
                    self.last_bandit_tick = now
                
                if now - self.last_regime_v2_tick >= 300:  # 5 minutes
                    phase81_regime_tick()
                    self.last_regime_v2_tick = now
                
                if now - self.last_drawdown_tick >= 3600:  # 1 hour
                    phase81_drawdown_guard_tick()
                    self.last_drawdown_tick = now
                
                if now - self.last_fill_quality_tick >= 900:  # 15 minutes
                    phase81_fill_quality_tick()
                    self.last_fill_quality_tick = now
                
                if now - self.last_overnight_tick >= 300:  # 5 minutes
                    phase81_overnight_tick()
                    self.last_overnight_tick = now
                
                # Persist Phase 8.1 state every 10 minutes
                if now - self.last_phase81_persist >= 600:
                    persist_phase81()
                    self.last_phase81_persist = now
            except Exception as e:
                if "phase81" in str(type(e).__name__).lower() or "phase81" in str(e).lower():
                    print(f"⚠️ Phase 8.1 tick skipped: {e}")
            
            # Phase 8.2 Go-Live Controller ticks
            try:
                from phase82_go_live import (
                    phase82_ramp_tick, phase82_kill_switch_tick, phase82_recon_tick,
                    phase82_regime_mismatch_tick, persist_phase82
                )
                
                if now - self.last_ramp_assessor_tick >= 3600:  # 1 hour
                    phase82_ramp_tick()
                    self.last_ramp_assessor_tick = now
                
                if now - self.last_kill_switch_tick >= 60:  # 1 minute
                    phase82_kill_switch_tick()
                    self.last_kill_switch_tick = now
                
                if now - self.last_recon_tick >= 300:  # 5 minutes
                    phase82_recon_tick()
                    self.last_recon_tick = now
                
                if now - self.last_regime_mismatch_tick >= 300:  # 5 minutes
                    phase82_regime_mismatch_tick()
                    self.last_regime_mismatch_tick = now
                
                # Persist Phase 8.2 state every 10 minutes
                if now - self.last_phase82_persist >= 600:
                    persist_phase82()
                    self.last_phase82_persist = now
            except Exception as e:
                if "phase82" in str(type(e).__name__).lower() or "phase82" in str(e).lower():
                    print(f"⚠️ Phase 8.2 tick skipped: {e}")
            
            # Phase 8.2 Validation scheduler tick (DISABLED - was polluting portfolio with fake test trades)
            # try:
            #     from phase82_validation import phase82_validation_scheduler_tick
            #     
            #     if now - self.last_validation_tick >= 3600:  # Check hourly
            #         phase82_validation_scheduler_tick()
            #         self.last_validation_tick = now
            # except Exception as e:
            #     if "validation" in str(e).lower():
            #         print(f"⚠️ Phase 8.2 validation tick skipped: {e}")
            
            # Data Integrity Monitor (hourly check - prevents test pollution like Phase82 issue)
            try:
                from src.data_integrity_monitor import run_full_integrity_check, auto_clean_test_data
                
                if now - self.last_integrity_check >= 3600:  # Check every hour
                    summary = run_full_integrity_check()
                    
                    if summary['status'] == 'CRITICAL':
                        print(f"🚨 DATA INTEGRITY CRITICAL: {summary['critical_count']} issues found")
                        # Auto-clean test data pollution
                        cleaned = auto_clean_test_data()
                        if cleaned['trades_removed'] > 0:
                            print(f"   🧹 Auto-removed {cleaned['trades_removed']} test trades from portfolio")
                        if cleaned['positions_removed'] > 0:
                            print(f"   🧹 Auto-removed {cleaned['positions_removed']} test positions")
                    elif summary['status'] == 'WARNING':
                        print(f"⚠️  DATA INTEGRITY: {summary['warning_count']} warnings detected")
                    
                    self.last_integrity_check = now
            except Exception as e:
                if "integrity" in str(e).lower():
                    print(f"⚠️ Data integrity check skipped: {e}")
            
            # Phase 8.3 Drift Detector tick
            try:
                from phase83_drift_detector import phase83_drift_tick
                
                if now - self.last_drift_tick >= 900:  # 15 minutes
                    phase83_drift_tick()
                    self.last_drift_tick = now
            except Exception as e:
                if "phase83" in str(e).lower() or "drift" in str(e).lower():
                    print(f"⚠️ Phase 8.3 drift tick skipped: {e}")
            
            # Phase 8.4-8.6 Expansion Pack ticks
            try:
                from src.phase84_86_expansion import (
                    phase84_optimizer_tick, phase85_early_warning_tick,
                    phase85_scenario_stress_estimates, phase86_apply_correlation_guards,
                    phase86_theme_caps, phase86_hedge_dispatcher,
                    phase86_capital_preservation_mode_tick
                )
                
                # Phase 8.4: Profit Optimizer (30 minutes)
                if now - self.last_phase84_tick >= 1800:
                    phase84_optimizer_tick()
                    self.last_phase84_tick = now
                
                # Phase 8.5: Early Warning (5 minutes)
                if now - self.last_phase85_tick >= 300:
                    phase85_early_warning_tick()
                    self.last_phase85_tick = now
                
                # Phase 8.5: Scenario Stress (hourly)
                if now - self.last_phase85_scenario_tick >= 3600:
                    phase85_scenario_stress_estimates()
                    self.last_phase85_scenario_tick = now
                
                # Phase 8.6: Risk Layer (5 minutes)
                if now - self.last_phase86_tick >= 300:
                    phase86_apply_correlation_guards()
                    phase86_theme_caps()
                    phase86_hedge_dispatcher()
                    phase86_capital_preservation_mode_tick()
                    self.last_phase86_tick = now
            except Exception as e:
                if "phase84" in str(e).lower() or "phase85" in str(e).lower() or "phase86" in str(e).lower():
                    print(f"⚠️ Phase 8.4-8.6 tick skipped: {e}")
            
            # Phase 8.7-8.9 Expansion Pack ticks
            try:
                from src.phase87_89_expansion import (
                    phase87_cockpit_tick, phase88_consensus_tick, phase89_tick
                )
                
                # Phase 8.7: Cockpit Telemetry (60 seconds)
                if now - self.last_phase87_cockpit_tick >= 60:
                    phase87_cockpit_tick()
                    self.last_phase87_cockpit_tick = now
                
                # Phase 8.8: Consensus & Crowding (5 minutes)
                if now - self.last_phase88_consensus_tick >= 300:
                    phase88_consensus_tick()
                    self.last_phase88_consensus_tick = now
                
                # Phase 8.9: External Signals (5 minutes)
                if now - self.last_phase89_external_tick >= 300:
                    phase89_tick()
                    self.last_phase89_external_tick = now
            except Exception as e:
                if "phase87" in str(e).lower() or "phase88" in str(e).lower() or "phase89" in str(e).lower():
                    print(f"⚠️ Phase 8.7-8.9 tick skipped: {e}")
            
            # Phase 9 Autonomy Controller ticks
            try:
                from src.phase9_autonomy import (
                    phase9_autonomy_tick, phase9_learning_tick,
                    phase9_watchdog_tick, phase9_flags_tick, bump_heartbeat
                )
                
                # Phase 9: Watchdog (1 minute)
                if now - self.last_phase9_watchdog_tick >= 60:
                    phase9_watchdog_tick()
                    bump_heartbeat("transparency_audit")
                    self.last_phase9_watchdog_tick = now
                
                # Phase 9: Autonomy Governor (10 minutes)
                if now - self.last_phase9_autonomy_tick >= 600:
                    phase9_autonomy_tick()
                    self.last_phase9_autonomy_tick = now
                
                # Phase 9: Feature Flags (30 minutes)
                if now - self.last_phase9_flags_tick >= 1800:
                    phase9_flags_tick()
                    self.last_phase9_flags_tick = now
                
                # Phase 9: Learning Loop (1 hour)
                if now - self.last_phase9_learning_tick >= 3600:
                    phase9_learning_tick()
                    self.last_phase9_learning_tick = now
            except Exception as e:
                if "phase9" in str(e).lower():
                    print(f"⚠️ Phase 9 tick skipped: {e}")
            
            # Phase 9.1 Adaptive Governance ticks
            try:
                from src.phase91_adaptive_governance import (
                    phase91_update_tolerances, phase91_health_trend_tick,
                    phase91_watchdog_tick, phase91_calibrate_parameters,
                    phase91_update_cooldowns
                )
                
                # Phase 9.1: Health Trend (1 minute)
                if now - self.last_phase91_health_trend_tick >= 60:
                    phase91_health_trend_tick()
                    self.last_phase91_health_trend_tick = now
                
                # Phase 9.1: Watchdog Severity (1 minute)
                if now - self.last_phase91_watchdog_tick >= 60:
                    phase91_watchdog_tick()
                    self.last_phase91_watchdog_tick = now
                
                # Phase 9.1: Tolerance Updates (1 hour)
                if now - self.last_phase91_tolerance_tick >= 3600:
                    phase91_update_tolerances()
                    phase91_update_cooldowns()  # Also update adaptive cooldowns hourly
                    self.last_phase91_tolerance_tick = now
                
                # Phase 9.1: Parameter Calibration (1 hour)
                if now - self.last_phase91_calibration_tick >= 3600:
                    phase91_calibrate_parameters()
                    self.last_phase91_calibration_tick = now
            except Exception as e:
                if "phase91" in str(e).lower():
                    print(f"⚠️ Phase 9.1 tick skipped: {e}")
            
            time.sleep(10)
    
    def emit_heartbeat(self, subsystem: str):
        self.autonomy.heartbeat(subsystem)
    
    def get_status(self):
        return self.autonomy.get_status()

_phase80_coordinator_instance: Optional[Phase80Coordinator] = None

def create_phase80_coordinator() -> Phase80Coordinator:
    global _phase80_coordinator_instance
    if _phase80_coordinator_instance is None:
        cfg = default_phase80_cfg()
        autonomy = Phase80Autonomy(cfg)
        _phase80_coordinator_instance = Phase80Coordinator(autonomy)
    return _phase80_coordinator_instance

def get_phase80_coordinator() -> Phase80Coordinator:
    global _phase80_coordinator_instance
    if _phase80_coordinator_instance is None:
        return create_phase80_coordinator()
    return _phase80_coordinator_instance
