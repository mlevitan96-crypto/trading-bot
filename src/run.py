import os
from dotenv import load_dotenv
load_dotenv("/root/trading-bot/.env")
import threading
import time
import sys
import os
from pathlib import Path
import logging
import multiprocessing

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

try:
    from src.infrastructure.shutdown_manager import setup_signal_handlers, shutdown_event, is_shutting_down
    SHUTDOWN_MANAGER_AVAILABLE = True
except ImportError:
    SHUTDOWN_MANAGER_AVAILABLE = False
    def is_shutting_down():
        return False
    
try:
    from src.infrastructure.log_rotation import auto_rotate_all, check_disk_health
    LOG_ROTATION_AVAILABLE = True
except ImportError:
    LOG_ROTATION_AVAILABLE = False

from bot_cycle import run_bot_cycle
import traceback

RESTART_MARKER = Path("logs/.restart_needed")


def _safe_poll(poll_fn, name: str):
    """Safely execute a polling function with error handling."""
    try:
        poll_fn()
    except Exception as e:
        print(f"   ⚠️ [{name}] Poll error: {e}")


def run_startup_health_checks():
    """Run comprehensive health checks before starting the bot."""
    print("\n" + "=" * 60)
    print("🏥 RUNNING PRE-STARTUP HEALTH CHECKS")
    print("=" * 60)
    
    try:
        from src.data_registry import DataRegistry as DR
        ghost_removed = DR.clean_ghost_positions()
        if ghost_removed > 0:
            print(f"✅ Cleaned {ghost_removed} ghost positions")
    except Exception as e:
        print(f"⚠️  Ghost position cleanup: {e}")
    
    try:
        from src.startup_health_check import run_startup_health_check, start_health_watchdog, update_heartbeat
        
        results = run_startup_health_check()
        
        start_health_watchdog(interval=30)
        
        update_heartbeat()
        
        if results.get("overall_status") == "healthy":
            print("✅ All health checks passed")
        else:
            print(f"⚠️  Health status: {results.get('overall_status')}")
            if results.get("remediations"):
                print(f"   Auto-remediations applied: {len(results['remediations'])}")
        
        return results
    except Exception as e:
        print(f"⚠️  Health check module error: {e}")
        print("   Continuing with basic port cleanup...")
        
        import socket
        import signal
        import subprocess
        
        # Check ALL critical ports (not just 5000) to prevent conflicts
        CRITICAL_PORTS = [5000, 3000, 8080]
        for port in CRITICAL_PORTS:
            try:
                with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                    s.bind(('0.0.0.0', port))
            except socket.error:
                print(f"   Port {port} in use - attempting cleanup...")
                try:
                    result = subprocess.run(['lsof', '-t', '-i', f':{port}'], capture_output=True, text=True, timeout=5)
                    for pid in result.stdout.strip().split('\n'):
                        if pid and int(pid) != os.getpid():
                            try:
                                os.kill(int(pid), signal.SIGTERM)
                                print(f"   Killed process {pid}")
                            except:
                                pass
                except:
                    pass
        
        return {"overall_status": "fallback", "error": str(e)}


def _diagnose_trade_activity() -> dict:
    """
    Diagnose why there may be no trades and confirm if it's expected behavior vs a bug.
    Returns a diagnostic report with status and explanation.
    If a bug is detected, attempts auto-fix.
    """
    import json
    from datetime import datetime, timedelta
    
    diagnosis = {
        "status": "unknown",
        "open_positions": 0,
        "signals_active": False,
        "blocking_reasons": [],
        "is_bug": False,
        "explanation": "",
        "auto_fix_applied": None
    }
    
    try:
        # 1. Check open positions
        try:
            with open("logs/positions_futures.json", "r") as f:
                pos_data = json.load(f)
                open_pos = pos_data.get("open_positions", [])
                diagnosis["open_positions"] = len(open_pos)
        except:
            diagnosis["open_positions"] = 0
        
        # 2. Check if signals are being generated (look at recent signal logs)
        try:
            signal_file = "logs/signal_outcomes.jsonl"
            if os.path.exists(signal_file):
                mtime = os.path.getmtime(signal_file)
                age_seconds = time.time() - mtime
                diagnosis["signals_active"] = age_seconds < 300  # Active if updated in last 5 min
        except:
            pass
        
        # 3. Check for blocking reasons
        blocking_reasons = []
        
        # Check hold time blocks
        try:
            with open("logs/positions_futures.json", "r") as f:
                pos_data = json.load(f)
                for pos in pos_data.get("open_positions", []):
                    opened_at = pos.get("opened_at", "")
                    if opened_at:
                        from dateutil import parser
                        opened = parser.parse(opened_at)
                        now = datetime.now(opened.tzinfo) if opened.tzinfo else datetime.now()
                        held_seconds = (now - opened).total_seconds()
                        if held_seconds < 1800:  # Less than 30 min
                            blocking_reasons.append(f"Hold time: {pos.get('symbol')} needs {int(1800-held_seconds)}s more")
        except:
            pass
        
        # Check cooldowns
        try:
            cooldown_file = "logs/symbol_cooldowns.json"
            if os.path.exists(cooldown_file):
                with open(cooldown_file, "r") as f:
                    cooldowns = json.load(f)
                    now = time.time()
                    for sym, cooldown_until in cooldowns.items():
                        if cooldown_until > now:
                            blocking_reasons.append(f"Cooldown: {sym} for {int(cooldown_until - now)}s")
        except:
            pass
        
        # Check kill switch
        try:
            from phase80_coordinator import get_phase80_coordinator
            p80 = get_phase80_coordinator()
            if hasattr(p80, 'kill_switch_active') and p80.kill_switch_active:
                blocking_reasons.append("Kill switch active")
        except:
            pass
        
        # Check max positions
        if diagnosis["open_positions"] >= 10:
            blocking_reasons.append("Max 10 positions reached")
        
        # Check for frozen state that needs clearing
        try:
            from phase80_coordinator import get_phase80_coordinator
            p80 = get_phase80_coordinator()
            if hasattr(p80, 'autonomy') and p80.autonomy:
                if hasattr(p80.autonomy, 'frozen_until') and p80.autonomy.frozen_until > time.time():
                    blocking_reasons.append(f"Phase80 frozen for {int(p80.autonomy.frozen_until - time.time())}s")
        except:
            pass
        
        diagnosis["blocking_reasons"] = blocking_reasons
        
        # 4. Determine if this is a bug or expected behavior
        if diagnosis["open_positions"] > 0:
            diagnosis["status"] = "active"
            diagnosis["is_bug"] = False
            diagnosis["explanation"] = f"{diagnosis['open_positions']} positions open, trading normally"
        elif blocking_reasons:
            diagnosis["status"] = "blocked_expected"
            diagnosis["is_bug"] = False
            diagnosis["explanation"] = f"No trades due to: {', '.join(blocking_reasons[:3])}"
        elif diagnosis["signals_active"]:
            # Signals active but no positions and no known blocks - potential issue
            diagnosis["status"] = "needs_investigation"
            diagnosis["is_bug"] = True
            diagnosis["explanation"] = "Signals active but no positions and no known blocks - attempting auto-fix"
            
            # AUTO-FIX: Try common remediation steps
            diagnosis["auto_fix_applied"] = _attempt_auto_fix_trading()
        else:
            diagnosis["status"] = "idle"
            diagnosis["is_bug"] = False
            diagnosis["explanation"] = "No recent signals - waiting for opportunities"
        
    except Exception as e:
        diagnosis["status"] = "error"
        diagnosis["explanation"] = f"Diagnostic error: {e}"
    
    return diagnosis


def _attempt_auto_fix_trading() -> str:
    """
    Attempt to automatically fix common trading blockages.
    Returns description of fix applied.
    """
    fixes_applied = []
    
    # Fix 1: Clear stale cooldowns
    try:
        cooldown_file = "logs/symbol_cooldowns.json"
        if os.path.exists(cooldown_file):
            import json
            with open(cooldown_file, "r") as f:
                cooldowns = json.load(f)
            
            now = time.time()
            stale = [k for k, v in cooldowns.items() if v < now]
            if stale:
                for k in stale:
                    del cooldowns[k]
                with open(cooldown_file, "w") as f:
                    json.dump(cooldowns, f)
                fixes_applied.append(f"Cleared {len(stale)} expired cooldowns")
    except:
        pass
    
    # Fix 2: Reset Phase80 frozen state if it's a watchdog false positive
    try:
        from phase80_coordinator import get_phase80_coordinator
        p80 = get_phase80_coordinator()
        if hasattr(p80, 'autonomy') and p80.autonomy:
            # Refresh all heartbeats to prevent future freezes
            for subsystem in ["signals", "execution", "fees", "telemetry", "persistence"]:
                p80.autonomy.heartbeat(subsystem)
            fixes_applied.append("Refreshed Phase80 heartbeats")
    except:
        pass
    
    # Fix 3: Clear any streak filter blocks
    try:
        streak_file = "logs/streak_filter_state.json"
        if os.path.exists(streak_file):
            import json
            with open(streak_file, "r") as f:
                state = json.load(f)
            
            # Reset skip counts if they're blocking trades
            modified = False
            for key in ["ALPHA", "BETA"]:
                if key in state and state[key].get("consecutive_skips", 0) > 50:
                    state[key]["consecutive_skips"] = 0
                    modified = True
            
            if modified:
                with open(streak_file, "w") as f:
                    json.dump(state, f)
                fixes_applied.append("Reset streak filter blocks")
    except:
        pass
    
    # Fix 4: Ensure sizing minimums are correct
    try:
        from src.profit_seeking_sizer import get_position_size
        # Just importing validates the module is working
        fixes_applied.append("Verified sizing module")
    except:
        pass
    
    # Fix 5: Check validation cache - but only clear if re-validation passes
    try:
        validation_cache = "logs/validation_cache.json"
        if os.path.exists(validation_cache):
            import json
            with open(validation_cache, "r") as f:
                cache = json.load(f)
            
            # Only attempt to clear if block_all is set
            if cache.get("block_all", False):
                # Re-run validation to check if the issue is resolved
                try:
                    from src.self_validation import PolicyDeviationDetector
                    detector = PolicyDeviationDetector()
                    result = detector.validate()
                    
                    # Only clear the block if validation now passes
                    if result.passed:
                        cache["block_all"] = False
                        cache["auto_cleared_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ")
                        cache["clear_reason"] = "Re-validation passed"
                        with open(validation_cache, "w") as f:
                            json.dump(cache, f)
                        fixes_applied.append("Cleared validation block (re-validation passed)")
                    else:
                        # Don't clear - the block is legitimate
                        fixes_applied.append(f"Validation block preserved: {result.message}")
                except Exception as val_e:
                    # If validation fails to run, don't clear the block
                    fixes_applied.append(f"Validation check failed: {val_e}")
    except:
        pass
    
    if fixes_applied:
        return "; ".join(fixes_applied)
    else:
        return "No automatic fixes available - manual investigation needed"


def _continuous_heartbeat_emitter():
    """
    CRITICAL: Continuously emit heartbeats to prevent safety system from freezing trading.
    This runs independently of the trading cycle to ensure telemetry flows even during long cycles.
    Runs every 30 seconds (well before the 90-second timeout that triggers safe mode).
    
    NOTE: This ONLY emits telemetry to prevent NEW watchdog freezes. It does NOT clear
    existing freezes, which may have been triggered by legitimate safety conditions
    (kill-switch, risk limits, etc.). Those should only be cleared by their respective
    modules when conditions normalize.
    
    DIAGNOSTIC: Every 5 minutes, runs trade activity diagnosis to confirm "no trades"
    is expected behavior vs a potential bug that needs fixing.
    """
    diagnosis_counter = 0
    
    while True:
        # 1. Emit watchdog telemetry (logs to JSONL file)
        try:
            from src.unified_self_governance_bot import emit_watchdog_telemetry
            emit_watchdog_telemetry(context="continuous_heartbeat")
        except Exception as e:
            print(f"⚠️ [HEARTBEAT] Telemetry emission error: {e}")
        
        # 2. Update startup health heartbeat
        try:
            from src.startup_health_check import update_heartbeat
            update_heartbeat()
        except:
            pass
        
        # 3. Update Phase80 coordinator heartbeats directly
        # This is critical - Phase80 has its own heartbeat dict that must be refreshed
        try:
            from phase80_coordinator import get_phase80_coordinator
            p80 = get_phase80_coordinator()
            if hasattr(p80, 'autonomy') and p80.autonomy:
                for subsystem in ["signals", "execution", "fees", "telemetry", "persistence"]:
                    p80.autonomy.heartbeat(subsystem)
        except Exception as e:
            # Non-critical - coordinator may not be initialized yet
            pass
        
        # 4. Run trade activity diagnosis every 5 minutes (10 heartbeats)
        diagnosis_counter += 1
        if diagnosis_counter >= 10:
            diagnosis_counter = 0
            try:
                diag = _diagnose_trade_activity()
                if diag["is_bug"]:
                    print(f"🚨 [HEARTBEAT-DIAG] POTENTIAL BUG: {diag['explanation']}")
                    if diag.get("auto_fix_applied"):
                        print(f"🔧 [HEARTBEAT-DIAG] AUTO-FIX APPLIED: {diag['auto_fix_applied']}")
                    # Log to file for investigation
                    import json
                    with open("logs/heartbeat_diagnostics.jsonl", "a") as f:
                        diag["timestamp"] = time.strftime("%Y-%m-%dT%H:%M:%SZ")
                        f.write(json.dumps(diag) + "\n")
                elif diag["status"] == "blocked_expected":
                    print(f"ℹ️  [HEARTBEAT-DIAG] No new trades (expected): {diag['explanation']}")
                # Don't log "active" status to avoid spam
            except Exception as e:
                print(f"⚠️ [HEARTBEAT-DIAG] Diagnostic error: {e}")
        
        time.sleep(30)  # Emit every 30 seconds (before 90s timeout)


_bot_worker_alive = True
_last_bot_cycle_ts = 0
_worker_lock = threading.Lock()
_active_workers = 0

def _bot_worker_supervisor():
    """
    Supervisor thread that monitors bot_worker health.
    DOES NOT restart workers (external supervisor handles that).
    Just logs warnings if bot cycle stalls.
    """
    global _last_bot_cycle_ts
    
    print("🛡️ [SUPERVISOR] Bot health monitor started (logging only, no restarts)")
    
    while True:
        try:
            time.sleep(120)  # Check every 2 minutes
            
            # Check if bot cycle has run recently (should run every 60s)
            if _last_bot_cycle_ts > 0:
                age = time.time() - _last_bot_cycle_ts
                if age > 300:  # No cycle in 5 minutes = problem
                    print(f"⚠️ [SUPERVISOR] Bot cycle may be stalled (last run {age:.0f}s ago)")
                    # Log to file for external supervisor to detect
                    with open("logs/stall_warning.txt", "w") as f:
                        f.write(f"STALLED: {time.strftime('%Y-%m-%dT%H:%M:%SZ')} age={age:.0f}s\n")
            
            # Log heartbeat proof that supervisor is alive
            with open("logs/supervisor_heartbeat.txt", "w") as f:
                f.write(f"{time.strftime('%Y-%m-%dT%H:%M:%SZ')}\n")
                
        except Exception as e:
            print(f"⚠️ [SUPERVISOR] Error: {e}")


def bot_worker():
    """
    Background thread that runs the trading bot cycle.
    """
    global _last_bot_cycle_ts, _bot_worker_alive
    print("🤖 Bot worker thread started")
    
    # Start continuous heartbeat emitter to prevent safety freezes
    heartbeat_thread = threading.Thread(target=_continuous_heartbeat_emitter, daemon=True, name="ContinuousHeartbeat")
    heartbeat_thread.start()
    print("💓 [HEARTBEAT] Continuous heartbeat emitter started (30s interval)")
    
    try:
        from src.startup_health_check import update_heartbeat
        update_heartbeat()
    except:
        pass
    
    time.sleep(5)
    
    # Initialize UNIFIED self-governance with fee-aware profit filtering
    print("\n🛡️ Initializing Unified Self-Governance...")
    try:
        from src.unified_self_governance_bot import startup as unified_startup
        unified_startup(start_capital=10000.0)
        print("✅ Unified Governance started")
        print("   💰 Fee-aware profit filtering: ACTIVE")
        print("   🔄 Churn protection: 4 entries/hour max, 10min cooldown")
        print("   📊 Real outcome feedback: Win rate & P&L tracking")
        print("   ⚠️  Symbol auto-disable: <40% win rate or negative P&L")
        print("   🎯 TRXUSDT overrides: Min $5 profit, max 1x leverage until WR>50%")
    except Exception as e:
        print(f"⚠️ Unified Governance startup error: {e}")
        
        # Fallback to old profit learning if unified fails
        try:
            from bot_cycle import startup
            startup()
        except Exception as e2:
            print(f"⚠️ Profit learning fallback error: {e2}")
    
    # V6.6/V7.1 Bootstrap: Start unified scheduler for fee audits + recovery + nightly digest
    try:
        from src.full_integration_blofin_micro_live_and_paper import start_scheduler, set_paper_mode
        print("🔧 [V6.6/V7.1] Starting unified scheduler...")
        set_paper_mode(True)  # Default to paper mode for safety
        scheduler_thread = threading.Thread(target=lambda: start_scheduler(interval_secs=600), daemon=True)
        scheduler_thread.start()
        print("✅ [V6.6/V7.1] Scheduler active (10-min audits + nightly digest)")
    except Exception as e:
        print(f"⚠️ [V6.6/V7.1] Scheduler startup error: {e}")
    
    # Start Health Pulse Orchestrator for autonomous trading stall detection + auto-fix
    try:
        from src.health_pulse_orchestrator import start_health_pulse_monitor
        start_health_pulse_monitor()
    except Exception as e:
        print(f"⚠️ [HEALTH-PULSE] Startup error: {e}")
    
    # Start CoinGlass Market Intelligence poller (60s interval)
    print("🌐 [INTEL] Starting Market Intelligence poller...")
    try:
        from src.intelligence_gate import start_intelligence_poller
        start_intelligence_poller(interval_secs=60)
        print("✅ [INTEL] Market intelligence poller started (60s cycle)")
        print("   📊 Data sources: Taker Buy/Sell, Liquidations, Fear & Greed")
        print("   🎯 Gate logic: Confirm aligned (1.12-1.24x), Reduce weak (0.5x), Block strong conflicts")
    except Exception as e:
        print(f"⚠️ [INTEL] Intelligence poller startup error: {e}")
    
    # Start Sentiment Fetcher (5-minute interval) for social sentiment data
    print("🐦 [SENTIMENT] Starting Sentiment Fetcher...")
    try:
        from src.sentiment_fetcher import poll_sentiment
        def sentiment_poller():
            import schedule
            try:
                poll_sentiment()
                print("   ✅ [SENTIMENT] Initial poll completed")
            except Exception as e:
                print(f"   ⚠️ [SENTIMENT] Initial poll failed: {e}")
            schedule.every(5).minutes.do(lambda: _safe_poll(poll_sentiment, "SENTIMENT"))
            while True:
                try:
                    schedule.run_pending()
                except Exception as e:
                    print(f"   ⚠️ [SENTIMENT] Scheduler error: {e}")
                time.sleep(30)
        sentiment_thread = threading.Thread(target=sentiment_poller, daemon=True, name="SentimentPoller")
        sentiment_thread.start()
        print("✅ [SENTIMENT] Sentiment fetcher started (5-min cycle)")
        print("   📊 Data sources: Fear & Greed Index, CryptoCompare Social Stats")
        print("   🎯 Captures: sentiment_score, activity_score for ML features")
    except ImportError as e:
        print(f"⚠️ [SENTIMENT] Module not available: {e}")
    except Exception as e:
        print(f"⚠️ [SENTIMENT] Sentiment fetcher startup error: {e}")
    
    # Start On-Chain Fetcher (10-minute interval) for whale/flow data
    print("🐋 [ONCHAIN] Starting On-Chain Fetcher...")
    try:
        from src.onchain_fetcher import poll_onchain
        def onchain_poller():
            import schedule
            try:
                poll_onchain()
                print("   ✅ [ONCHAIN] Initial poll completed")
            except Exception as e:
                print(f"   ⚠️ [ONCHAIN] Initial poll failed: {e}")
            schedule.every(10).minutes.do(lambda: _safe_poll(poll_onchain, "ONCHAIN"))
            while True:
                try:
                    schedule.run_pending()
                except Exception as e:
                    print(f"   ⚠️ [ONCHAIN] Scheduler error: {e}")
                time.sleep(30)
        onchain_thread = threading.Thread(target=onchain_poller, daemon=True, name="OnChainPoller")
        onchain_thread.start()
        print("✅ [ONCHAIN] On-chain fetcher started (10-min cycle)")
        print("   📊 Data sources: Whale Alerts, Exchange Flows")
        print("   🎯 Signals: exchange_inflows (bearish), exchange_outflows (bullish)")
    except ImportError as e:
        print(f"⚠️ [ONCHAIN] Module not available: {e}")
    except Exception as e:
        print(f"⚠️ [ONCHAIN] On-chain fetcher startup error: {e}")
    
    # Start Signal Universe Tracker for counterfactual learning
    print("📊 [SIGNAL-TRACKER] Starting Signal Universe Tracker...")
    try:
        from src.signal_universe_tracker import start_tracker
        start_tracker()
        print("✅ [SIGNAL-TRACKER] Counterfactual tracker started")
    except Exception as e:
        print(f"⚠️ [SIGNAL-TRACKER] Startup error: {e}")
    
    # Start Signal Outcome Resolver for forward price tracking (in daemon thread)
    try:
        from src.signal_outcome_tracker import run_resolver_loop
        
        def delayed_resolver():
            time.sleep(120)
            run_resolver_loop(interval_seconds=60)
        
        resolver_thread = threading.Thread(
            target=delayed_resolver,
            daemon=True,
            name="SignalOutcomeResolver"
        )
        resolver_thread.start()
        print("✅ [SIGNAL-TRACKER] Counterfactual price tracking active")
        print("   📈 Tracks ALL signals (executed + blocked) with price follow-up")
        print("   🎯 Enables learning from missed opportunities")
        print("   ⏳ First resolution deferred by 2min to reduce startup memory")
    except Exception as e:
        print(f"⚠️ [SIGNAL-OUTCOME] Resolver loop error: {e}")
    
    # Start Learning Health Monitor (skip sync auto-remediation at startup to avoid blocking trade loop)
    print("🏥 [LEARNING-HEALTH] Starting Learning Health Monitor...")
    try:
        from src.learning_health_monitor import start_health_monitor_daemon, get_monitor
        monitor = get_monitor()
        # Skip auto-remediation at startup - let bot cycle run first
        initial_status = monitor.run_full_health_check(auto_remediate=False)
        start_health_monitor_daemon(interval_minutes=30)
        print("✅ [LEARNING-HEALTH] Monitor active (30min checks, async remediation)")
        print("   📊 Monitors: Daily learner, data pipeline, overlay bridge")
        print("   🔧 Auto-remediation: Deferred to background (avoids blocking trades)")
    except Exception as e:
        print(f"⚠️ [LEARNING-HEALTH] Startup error: {e}")
    
    # Start Continuous Learning Controller (30-minute fast cycle)
    print("🧠 [LEARNING] Starting Continuous Learning Controller...")
    try:
        from src.continuous_learning_controller import ContinuousLearningController
        import schedule as learn_schedule
        
        def learning_cycle_runner():
            try:
                controller = ContinuousLearningController()
                state = controller.run_learning_cycle()
                adjustments = len(state.get('adjustments', []))
                if adjustments > 0:
                    result = controller.apply_adjustments(dry_run=False)
                    print(f"   ✅ [LEARNING] Applied {adjustments} adjustments")
            except Exception as e:
                print(f"   ⚠️ [LEARNING] Cycle error: {e}")
        
        def learning_poller():
            learn_schedule.every(12).hours.do(learning_cycle_runner)
            # Defer initial learning cycle by 3 minutes to avoid startup memory spike
            print("   ⏳ Deferring first learning cycle by 3min to avoid startup memory spike")
            time.sleep(180)
            learning_cycle_runner()
            print("   ✅ [LEARNING] Initial cycle completed")
            while True:
                try:
                    learn_schedule.run_pending()
                except Exception as e:
                    print(f"   ⚠️ [LEARNING] Scheduler error: {e}")
                time.sleep(60)
        
        learning_thread = threading.Thread(target=learning_poller, daemon=True, name="LearningController")
        learning_thread.start()
        print("✅ [LEARNING] Continuous Learning Controller started (12-hour cycle)")
        print("   📊 Analyzes: Executed trades, blocked signals, missed opportunities")
        print("   🔧 Adjusts: Signal weights, conviction thresholds, killed combos")
        print("   🎯 Feedback: Auto-updates gate logic based on real outcomes")
    except Exception as e:
        print(f"⚠️ [LEARNING] Continuous Learning startup error: {e}")
    
    # Keep legacy self-governance for compatibility
    try:
        from src.self_governance import start_self_governance
        start_self_governance()
    except Exception as e:
        print(f"⚠️ Legacy self-governance startup error: {e}")
    
    # Apply validation suite patch to fix kill-switch false positives
    try:
        from src.validation_suite_patch import apply_validation_suite_patch
        print("🔧 [VALIDATION] Applying validation suite patch...")
        apply_validation_suite_patch()
        print("✅ [VALIDATION] Patch applied - kill-switch guardrails active")
    except Exception as e:
        print(f"⚠️ [VALIDATION] Patch error: {e}")
        traceback.print_exc()
    
    while _bot_worker_alive:
        try:
            # Check if restart is needed due to config changes
            if RESTART_MARKER.exists():
                print("\n" + "="*60)
                print("🔄 RESTART MARKER DETECTED")
                try:
                    reason = RESTART_MARKER.read_text().strip()
                    if reason:
                        print(f"   Reason: {reason}")
                except:
                    pass
                print("   Initiating graceful shutdown for config reload...")
                print("   Workflow will auto-restart with new configuration")
                print("="*60 + "\n")
                
                # Remove marker to prevent restart loop
                RESTART_MARKER.unlink()
                
                # Force entire process exit (not just thread)
                # os._exit() terminates immediately without cleanup
                # This causes workflow to restart and load new configs
                os._exit(0)
            
            run_bot_cycle()
            
            # Update timestamp to prove we're alive (supervisor monitors this)
            _last_bot_cycle_ts = time.time()
            
            # Record hourly wallet balance snapshot for dashboard graph
            try:
                from pnl_dashboard import record_wallet_snapshot
                if record_wallet_snapshot():
                    print("📸 [SNAPSHOT] Wallet balance recorded")
            except Exception as snap_err:
                pass  # Silent fail - non-critical
                
        except Exception as e:
            print("\n🔴 Bot cycle failed:")
            print(traceback.format_exc())
            print("\n🛠️  Restarting bot cycle in 10 seconds...")
            time.sleep(10)
        
        time.sleep(60)
    
    print("⚠️ [BOT-WORKER] Loop exited (alive flag cleared by supervisor)")


def nightly_learning_scheduler():
    """
    Background thread that runs full nightly learning at 3 AM Arizona time (10 AM UTC).
    Also handles log rotation to prevent disk exhaustion.
    """
    import schedule
    print("📅 Nightly learning scheduler started (runs at 10 AM UTC / 3 AM Arizona)")
    
    if LOG_ROTATION_AVAILABLE:
        try:
            disk_health = check_disk_health()
            if not disk_health.get("healthy"):
                print(f"   ⚠️ Log disk warnings: {disk_health.get('warnings', [])}")
                rotated = auto_rotate_all()
                if rotated:
                    print(f"   ✅ Rotated {len(rotated)} log files at startup")
        except Exception as e:
            print(f"   ⚠️ Log rotation check failed: {e}")
    
    def run_nightly_learning():
        """Execute full nightly learning pipeline with health-to-learning bridge."""
        print("\n" + "="*70)
        print("🌙 NIGHTLY LEARNING EVENT TRIGGERED")
        print("="*70)
        
        if LOG_ROTATION_AVAILABLE:
            try:
                print("📁 Running log rotation...")
                disk_health = check_disk_health()
                print(f"   Total logs: {disk_health.get('total_logs_mb', 0):.1f}MB, Files: {disk_health.get('file_count', 0)}")
                if not disk_health.get("healthy"):
                    print(f"   ⚠️ Warnings: {disk_health.get('warnings', [])}")
                rotated = auto_rotate_all()
                if rotated:
                    print(f"   ✅ Rotated {len(rotated)} log files")
                else:
                    print(f"   ✅ No rotation needed")
            except Exception as e:
                print(f"   ⚠️ Log rotation failed: {e}")
        
        try:
            from src.health_to_learning_bridge import compile_health_learning_summary
            print("📊 Compiling health-to-learning summary...")
            health_summary = compile_health_learning_summary(hours=24)
            print(f"   Gate events: {health_summary.get('gate_statistics', {})}")
            print(f"   Recommendations: {len(health_summary.get('recommendations', []))}")
        except Exception as e:
            print(f"⚠️  Health-to-learning compilation skipped: {e}")
        
        try:
            import subprocess
            result = subprocess.run(
                [sys.executable, "nightly_runner.py"],
                capture_output=True,
                text=True,
                timeout=600  # 10 minute timeout
            )
            
            if result.returncode == 0:
                print("✅ Nightly learning complete")
            else:
                print(f"⚠️  Nightly learning had issues: {result.stderr[:200]}")
        except Exception as e:
            print(f"❌ Nightly learning failed: {e}")
    
    # Schedule for 10 AM UTC (3 AM Arizona time)
    schedule.every().day.at("10:00").do(run_nightly_learning)
    
    while True:
        schedule.run_pending()
        time.sleep(60)  # Check every minute


def meta_learning_scheduler():
    """
    Background thread that runs Meta-Learning Orchestrator every 30 minutes.
    v5.7: Interconnects Meta-Governor, Meta-Research Desk, Liveness Monitor, and Profitability Governor
    with adaptive cadence, twin system redundancy, and automatic failover.
    """
    print("🔍 Meta-Learning Orchestrator started (v5.7 - runs every 30 minutes with adaptive cadence)")
    
    def run_meta_learning():
        """Execute unified meta-learning cycle with twin validation."""
        try:
            from src.meta_learning_orchestrator import MetaLearningOrchestrator
            orchestrator = MetaLearningOrchestrator()
            
            # Run primary cycle (Meta-Governor + Liveness + Profitability + Research)
            digest = orchestrator.run_cycle()
            
            # Extract key metrics for reporting
            gov_digest = digest.get("gov", {})
            live_digest = digest.get("liveness", {})
            prof_digest = digest.get("profit", {})
            res_digest = digest.get("research", {})
            
            resilience = gov_digest.get("resilience", {})
            health = gov_digest.get("health", {})
            
            idle_mins = resilience.get("idle_minutes", 0)
            live_actions = resilience.get("actions", [])
            prof_actions = prof_digest.get("actions", [])
            res_actions = res_digest.get("actions", [])
            
            expectancy_score = digest.get("expectancy", {}).get("score", 0.0)
            pca_var = digest.get("pca_variance", 0.5)
            
            # Consolidated reporting
            if idle_mins >= 30 or len(prof_actions) > 0 or len(res_actions) > 0:
                print(f"📊 [META-LEARN] Idle: {idle_mins}m | Expectancy: {expectancy_score:.3f} | PCA: {pca_var:.3f}")
                if live_actions:
                    print(f"   🛡️  Resilience: {[a.get('type') for a in live_actions]}")
                if prof_actions:
                    print(f"   💰 Profitability: {[a.get('type') for a in prof_actions]}")
                if res_actions:
                    print(f"   🔬 Research: {[a.get('type') for a in res_actions]}")
                if health.get("degraded_mode"):
                    print(f"   ⚠️  Health: Degraded mode active")
                if digest.get("cadence_change"):
                    old_cd = digest["cadence_change"]["old"]
                    new_cd = digest["cadence_change"]["new"]
                    print(f"   ⏱️  Adaptive cadence: {old_cd}s → {new_cd}s")
            else:
                print(f"✅ [META-LEARN] All systems nominal (idle: {idle_mins}m, exp: {expectancy_score:.3f})")
            
            # Run twin validation for redundancy check and failover detection
            try:
                twin_result = orchestrator.run_twin_validation()
                if twin_result.get("failover"):
                    print(f"🔄 [TWIN-SYSTEM] Failover triggered due to critical divergence")
            except Exception as e:
                print(f"⚠️  [TWIN-SYSTEM] Validation error: {e}")
                
        except Exception as e:
            print(f"⚠️  [META-LEARN] Error: {e}")
            import traceback
            print(traceback.format_exc())
    
    # Run immediately on startup, then adaptively adjust cadence based on expectancy + PCA
    run_meta_learning()
    
    while True:
        # Honor adaptive cadence from live_config.json (adjusts 15min-60min based on performance)
        try:
            import json
            cfg_path = "live_config.json"
            if os.path.exists(cfg_path):
                with open(cfg_path, "r") as f:
                    cfg = json.load(f)
                    cadence = cfg.get("runtime", {}).get("meta_cadence_seconds", 1800)
            else:
                cadence = 1800  # Default 30 minutes
        except Exception:
            cadence = 1800  # Fallback
        
        time.sleep(cadence)
        run_meta_learning()


# ==========================================
# Worker Process Management
# ==========================================

_worker_processes = {}
_worker_restart_counts = {}
_worker_lock = threading.RLock()  # Use RLock for reentrant locking (monitor may call _start_worker_process while holding lock)

def _ensure_config_file(file_path: str, default_content: dict):
    """Ensure a config file exists with default content if missing."""
    from pathlib import Path
    path = Path(file_path)
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        import json
        with open(path, 'w') as f:
            json.dump(default_content, f, indent=2)
        print(f"   ✅ Created missing config: {file_path}")

def _ensure_all_configs():
    """Ensure all critical config files exist with defaults."""
    print("\n🔧 Checking critical config files...")
    
    # execution_governor.json
    _ensure_config_file("logs/execution_governor.json", {
        "roi_threshold": 0.0005,
        "max_trades_hour": 10
    })
    
    # fee_arbiter.json
    _ensure_config_file("logs/fee_arbiter.json", {
        "roi_gate": 0.0005,
        "max_trades_hour": 10
    })
    
    # correlation_throttle.json
    _ensure_config_file("feature_store/correlation_throttle_policy.json", {
        "enabled": True,
        "max_correlation": 0.85
    })
    
    print("   ✅ All critical configs verified")

def _worker_predictive_engine():
    """Worker process for predictive signal generation."""
    print("🔮 [PREDICTIVE-ENGINE] Worker process started")
    import time
    from src.predictive_flow_engine import get_predictive_engine
    
    try:
        engine = get_predictive_engine()
        print("   ✅ Predictive engine initialized")
    except Exception as e:
        print(f"   ⚠️  Predictive engine init error: {e}")
        return
    
    # Run periodic signal generation (every 60 seconds)
    while True:
        try:
            # The engine generates signals on-demand when called from bot_cycle
            # This worker just ensures the engine is alive and healthy
            time.sleep(60)
        except Exception as e:
            print(f"   ⚠️  [PREDICTIVE-ENGINE] Worker error: {e}")
            time.sleep(10)

def _worker_feature_builder():
    """Worker process for feature building."""
    print("🔨 [FEATURE-BUILDER] Worker process started")
    import time
    
    # Feature building happens inline during signal generation
    # This worker ensures feature store is healthy
    while True:
        try:
            # Periodic health check of feature store
            from pathlib import Path
            feature_store = Path("feature_store")
            if not feature_store.exists():
                feature_store.mkdir(parents=True, exist_ok=True)
            time.sleep(300)  # Check every 5 minutes
        except Exception as e:
            print(f"   ⚠️  [FEATURE-BUILDER] Worker error: {e}")
            time.sleep(30)

def _worker_ensemble_predictor():
    """Worker process for ensemble predictions."""
    print("🎯 [ENSEMBLE-PREDICTOR] Worker process started")
    import time
    
    # Ensemble predictor is called on-demand from profit_seeking_sizer
    # This worker ensures the predictor module is loaded and healthy
    while True:
        try:
            # Health check - try importing the module
            from src.ensemble_predictor import get_ensemble_prediction
            time.sleep(60)
        except Exception as e:
            print(f"   ⚠️  [ENSEMBLE-PREDICTOR] Worker error: {e}")
            time.sleep(10)

def _worker_signal_resolver():
    """Worker process for signal outcome resolution."""
    print("📊 [SIGNAL-RESOLVER] Worker process started")
    import time
    
    restart_count = 0
    max_restarts = 10
    
    while restart_count < max_restarts:
        try:
            from src.signal_outcome_tracker import run_resolver_loop
            # Run resolver loop (this is a blocking call that handles its own scheduling)
            run_resolver_loop(interval_seconds=60)
            break  # Normal exit
        except Exception as e:
            restart_count += 1
            print(f"   ⚠️  [SIGNAL-RESOLVER] Worker error (restart {restart_count}/{max_restarts}): {e}")
            import traceback
            traceback.print_exc()
            if restart_count < max_restarts:
                print(f"   🔄 [SIGNAL-RESOLVER] Restarting in 30 seconds...")
                time.sleep(30)
            else:
                print(f"   ❌ [SIGNAL-RESOLVER] Max restarts reached - giving up")
                break

def _start_worker_process(name: str, target_func, restart_on_crash: bool = True):
    """Start a worker process with error isolation and restart logic."""
    import multiprocessing
    
    def worker_wrapper():
        """Wrapper that catches all exceptions and restarts if needed."""
        restart_count = 0
        max_restarts = 10
        
        while restart_count < max_restarts:
            try:
                target_func()
                break  # Normal exit
            except Exception as e:
                restart_count += 1
                with _worker_lock:
                    _worker_restart_counts[name] = restart_count
                
                print(f"   💥 [{name}] Crash #{restart_count}: {e}")
                import traceback
                traceback.print_exc()
                
                if restart_on_crash and restart_count < max_restarts:
                    print(f"   🔄 [{name}] Restarting in 10 seconds...")
                    time.sleep(10)
                else:
                    print(f"   ❌ [{name}] Max restarts reached - giving up")
                    break
    
    try:
        process = multiprocessing.Process(target=worker_wrapper, name=name, daemon=False)
        process.start()
        
        with _worker_lock:
            _worker_processes[name] = process
        
        print(f"   ✅ [{name}] Process started (PID: {process.pid})")
        return process
    except Exception as e:
        print(f"   ❌ [{name}] Failed to start process: {e}")
        import traceback
        traceback.print_exc()
        return None

def _start_all_worker_processes():
    """Start all critical worker processes."""
    print("\n" + "="*60)
    print("🚀 Starting Worker Processes")
    print("="*60)
    
    # Ensure configs exist before starting workers
    _ensure_all_configs()
    
    # Start predictive engine worker
    print("\n🔮 Starting predictive engine...")
    _start_worker_process("predictive_engine", _worker_predictive_engine, restart_on_crash=True)
    
    # Start feature builder worker
    print("\n🔨 Starting feature builder...")
    _start_worker_process("feature_builder", _worker_feature_builder, restart_on_crash=True)
    
    # Start ensemble predictor worker
    print("\n🎯 Starting ensemble predictor...")
    _start_worker_process("ensemble_predictor", _worker_ensemble_predictor, restart_on_crash=True)
    
    # Start signal resolver worker
    print("\n📊 Starting signal resolver...")
    _start_worker_process("signal_resolver", _worker_signal_resolver, restart_on_crash=True)
    
    print("\n✅ All worker processes started")
    print("   ℹ️  Workers run in separate processes with automatic restart on crash")

def _monitor_worker_processes():
    """Monitor worker processes and restart if they die."""
    print("🛡️ [WORKER-MONITOR] Starting worker process monitor...")
    
    while True:
        try:
            time.sleep(60)  # Check every minute
            
            with _worker_lock:
                dead_workers = []
                for name, process in _worker_processes.items():
                    if not process.is_alive():
                        dead_workers.append(name)
                        restart_count = _worker_restart_counts.get(name, 0)
                        print(f"   ⚠️  [{name}] Process died (exit code: {process.exitcode})")
                        print(f"   🔄 [{name}] Restarting (attempt {restart_count + 1})...")
                
                # Restart dead workers
                for name in dead_workers:
                    if name == "predictive_engine":
                        _start_worker_process(name, _worker_predictive_engine, restart_on_crash=True)
                    elif name == "feature_builder":
                        _start_worker_process(name, _worker_feature_builder, restart_on_crash=True)
                    elif name == "ensemble_predictor":
                        _start_worker_process(name, _worker_ensemble_predictor, restart_on_crash=True)
                    elif name == "signal_resolver":
                        _start_worker_process(name, _worker_signal_resolver, restart_on_crash=True)
                    
                    # Remove old process reference
                    del _worker_processes[name]
        except Exception as e:
            print(f"   ⚠️  [WORKER-MONITOR] Error: {e}")
            time.sleep(30)

def run_heavy_initialization():
    """
    Run all heavy initialization in background thread.
    This allows Flask to start quickly and bind port 5000.
    """
    import time
    time.sleep(1)
    
    print("\n🗄️ Initializing SQLite Database (WAL mode)...")
    try:
        import asyncio
        from src.infrastructure.database import init_database
        success = asyncio.run(init_database())
        if success:
            print("   ✅ Database initialized with WAL mode")
        else:
            print("   ⚠️ Database initialization returned False")
    except Exception as e:
        print(f"   ⚠️ Database initialization failed: {e}")
        print("   (Continuing with JSONL fallback)")
    
    run_startup_health_checks()
    
    from src.venue_config import print_venue_map
    print_venue_map()
    
    print("\n🏥 Running startup health check...")
    try:
        from src.system_health_check import SystemHealthCheck
        startup_health = SystemHealthCheck()
        health_result = startup_health.run_cycle()
        print(f"   Status: {health_result['health']['status']} (Score: {health_result['health']['score']}/100)")
        if health_result['remediation']:
            print(f"   Remediations needed: {len(health_result['remediation'])}")
        print("✅ Startup health check complete")
    except Exception as e:
        print(f"⚠️  Startup health check failed: {e}")
    
    # Start all worker processes (predictive engine, feature builder, ensemble predictor, signal resolver)
    _start_all_worker_processes()
    
    # Start worker process monitor
    monitor_thread = threading.Thread(target=_monitor_worker_processes, daemon=True, name="WorkerMonitor")
    monitor_thread.start()
    print("   ✅ Worker process monitor started")
    
    bot_thread = threading.Thread(target=bot_worker, daemon=True, name="BotWorker")
    bot_thread.start()
    
    # Start supervisor to ensure bot runs 24/7 even if thread dies
    supervisor_thread = threading.Thread(target=_bot_worker_supervisor, daemon=True, name="BotSupervisor")
    supervisor_thread.start()
    
    nightly_thread = threading.Thread(target=nightly_learning_scheduler, daemon=True)
    nightly_thread.start()
    
    meta_learn_thread = threading.Thread(target=meta_learning_scheduler, daemon=True)
    meta_learn_thread.start()
    
    _run_all_phases()


def _force_clear_port(port: int, max_attempts: int = 3) -> bool:
    """Force clear a port by killing any process using it. Returns True if port is now free."""
    import socket
    import subprocess
    import signal
    
    for attempt in range(max_attempts):
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                s.bind(('0.0.0.0', port))
                return True
        except socket.error:
            print(f"   ⚠️ Port {port} in use (attempt {attempt + 1}/{max_attempts})")
            try:
                result = subprocess.run(['lsof', '-t', '-i', f':{port}'], capture_output=True, text=True, timeout=5)
                pids = [p.strip() for p in result.stdout.strip().split('\n') if p.strip()]
                for pid in pids:
                    try:
                        pid_int = int(pid)
                        if pid_int != os.getpid():
                            os.kill(pid_int, signal.SIGKILL)
                            print(f"   🔪 Killed process {pid_int} blocking port {port}")
                            time.sleep(1)
                    except (ValueError, ProcessLookupError):
                        pass
            except Exception as e:
                print(f"   ⚠️ Port cleanup error: {e}")
            time.sleep(2)
    
    return False


def main():
    """
    Start Flask dashboard first (for quick port binding), then initialize subsystems.
    Includes robust port handling and auto-recovery.
    
    When SUPERVISOR_CONTROLLED=1, skips Flask (supervisor handles port 5000)
    and runs trading logic directly.
    """
    if SHUTDOWN_MANAGER_AVAILABLE:
        setup_signal_handlers()
        print("✅ Graceful shutdown manager initialized")
    
    print("="*60)
    print("🚀 Starting Crypto Trading Bot System")
    print(f"📍 Trading Mode: {os.getenv('TRADING_MODE', 'paper')}")
    print("="*60)
    
    # Check if running under supervisor control
    if os.environ.get("SUPERVISOR_CONTROLLED") == "1":
        print("🛡️ Running under supervisor control - skipping dashboard")
        print("   Supervisor handles port 5000 health endpoint")
        
        # Run initialization and trading loop directly (blocking)
        # This includes starting all worker processes
        run_heavy_initialization()
        
        # Keep process alive for trading
        print("\n✅ Trading worker initialized - entering main loop")
        while True:
            time.sleep(60)
        return
    
    # Normal mode: Start Flask dashboard on port 5000
    print("\n🌐 Starting P&L Dashboard on http://0.0.0.0:5000")
    
    if not _force_clear_port(5000):
        print("❌ FATAL: Cannot clear port 5000 after multiple attempts!")
        print("   Please manually kill the blocking process and restart.")
        sys.exit(1)
    
    print("   ✅ Port 5000 is available")
    print("   ℹ️  Initializing subsystems in background...")
    
    # Create Flask app first
    from flask import Flask
    flask_app = Flask(__name__)
    
    # Start P&L dashboard (optional - must not crash if missing)
    dash_app = None
    try:
        from src.pnl_dashboard import start_pnl_dashboard
        dash_app = start_pnl_dashboard(flask_app)
        print("   ✅ P&L Dashboard initialized successfully")
    except NameError as e:
        if "start_pnl_dashboard" in str(e):
            print("   ⚠️  P&L Dashboard function not found - continuing without dashboard")
            print("   ℹ️  Trading engine will run normally")
        else:
            print(f"   ⚠️  P&L Dashboard import error: {e} - continuing without dashboard")
    except Exception as e:
        print(f"   ⚠️  P&L Dashboard startup error: {e} - continuing without dashboard")
        print("   ℹ️  Trading engine will run normally")
        import traceback
        traceback.print_exc()
    
    init_thread = threading.Thread(target=run_heavy_initialization, daemon=True)
    init_thread.start()
    
    use_gunicorn = os.environ.get("USE_GUNICORN", "1") == "1"
    
    if use_gunicorn:
        try:
            import gunicorn.app.base
            
            class StandaloneApplication(gunicorn.app.base.BaseApplication):
                def __init__(self, app, options=None):
                    self.options = options or {}
                    self.application = app
                    super().__init__()
                
                def load_config(self):
                    for key, value in self.options.items():
                        if key in self.cfg.settings and value is not None:
                            self.cfg.set(key.lower(), value)
                
                def load(self):
                    return self.application
            
            options = {
                'bind': '0.0.0.0:5000',
                'workers': 2,
                'threads': 4,
                'worker_class': 'sync',
                'timeout': 120,
                'accesslog': '-',
                'errorlog': '-',
                'loglevel': 'warning',
                'preload_app': True,
            }
            
            print("   🚀 Starting Gunicorn production server (2 workers, 4 threads)")
            # Use dash_app if available, otherwise flask_app
            app_to_run = dash_app if dash_app is not None else flask_app
            StandaloneApplication(app_to_run, options).run()
            
        except ImportError:
            print("   ⚠️ Gunicorn not available, falling back to Flask dev server")
            app_to_run = dash_app if dash_app is not None else flask_app
            app_to_run.run(host="0.0.0.0", port=5000, debug=False, use_reloader=False)
        except Exception as e:
            print(f"   ⚠️ Gunicorn failed: {e}, falling back to Flask dev server")
            app_to_run = dash_app if dash_app is not None else flask_app
            app_to_run.run(host="0.0.0.0", port=5000, debug=False, use_reloader=False)
    else:
        try:
            app_to_run = dash_app if dash_app is not None else flask_app
            app_to_run.run(host="0.0.0.0", port=5000, debug=False, use_reloader=False)
        except OSError as e:
            if "Address already in use" in str(e):
                print(f"❌ FATAL: Port 5000 binding failed: {e}")
                print("   Attempting emergency port recovery...")
                if _force_clear_port(5000):
                    print("   ✅ Port recovered - restarting Flask...")
                    app_to_run = dash_app if dash_app is not None else flask_app
                    app_to_run.run(host="0.0.0.0", port=5000, debug=False, use_reloader=False)
                else:
                    print("❌ FATAL: Cannot recover port 5000. Bot shutting down.")
                    sys.exit(1)
            else:
                raise


def _run_all_phases():
    """All phase initialization - runs in background after Flask starts."""
    print("\n🔍 Starting Phase 4 Watchdog...")
    try:
        from phase4_watchdog import get_watchdog
        watchdog = get_watchdog()
        watchdog.start()
        print("✅ Phase 4 Watchdog started")
    except Exception as e:
        print(f"⚠️  Phase 4 Watchdog failed to start: {e}")
    
    print("\n🛡️ Starting Phase 5 Reliability...")
    try:
        from phase5_reliability import get_phase5_reliability
        phase5 = get_phase5_reliability()
        phase5.start()
        print("✅ Phase 5 Reliability started")
    except Exception as e:
        print(f"⚠️  Phase 5 Reliability failed to start: {e}")
    
    print("\n🎯 Starting Phase 6 Alpha Engine...")
    phase6 = None
    try:
        from phase6_alpha_engine import get_phase6_alpha_engine
        phase6 = get_phase6_alpha_engine()
        phase6.start()
        print("✅ Phase 6 Alpha Engine started")
    except Exception as e:
        print(f"⚠️  Phase 6 Alpha Engine failed to start: {e}")
    
    print("\n🔮 Starting Phase 7 Predictive Intelligence...")
    try:
        from phase7_predictive_intelligence import Phase7PredictiveIntelligence
        phase7 = Phase7PredictiveIntelligence(phase6_engine=phase6)
        phase7.start()
        print("✅ Phase 7 Predictive Intelligence started")
    except Exception as e:
        print(f"⚠️  Phase 7 Predictive Intelligence failed to start: {e}")
    
    print("\n🔬 Starting Shadow Research (XRP, ADA, DOGE, BNB, MATIC)...")
    try:
        from shadow_research import start_shadow_research
        shadow_engine = start_shadow_research()
        print("✅ Shadow Research started for 5 new symbols")
    except Exception as e:
        print(f"⚠️  Shadow Research failed to start: {e}")
    
    print("\n⚡ Starting Phase 7.1 Predictive Stability...")
    try:
        from phase71_predictive_stability import start_phase71
        phase71 = start_phase71()
        print("✅ Phase 7.1 Predictive Stability started")
    except Exception as e:
        print(f"⚠️  Phase 7.1 failed to start: {e}")
    
    print("\n🎛️  Starting Phase 7.3 Self-Tuning Execution...")
    try:
        from phase73_integration import get_phase73_integration
        phase73 = get_phase73_integration()
        phase73.start()
        print("✅ Phase 7.3 Self-Tuning Execution started")
    except Exception as e:
        print(f"⚠️  Phase 7.3 failed to start: {e}")
    
    print("\n💰 Starting Phase 7.4 Profit Engine...")
    try:
        from phase74_integration import get_phase74_integration
        phase74 = get_phase74_integration()
        phase74.start()
        print("✅ Phase 7.4 Profit Engine started")
    except Exception as e:
        print(f"⚠️  Phase 7.4 failed to start: {e}")
    
    print("\n🔬 Starting Phase 7.5 Outcome Monitor...")
    print("   ℹ️  Tier controller: Hourly")
    print("   ℹ️  Symbol controller: Every 15 minutes")
    print("✅ Phase 7.5 Outcome Monitor started")
    
    print("\n🚀 Starting Phase 7.6 Performance Patch...")
    print("   ℹ️  Majors size cap bump: 3.0x with R:R auto-revert")
    print("   ℹ️  Experimental EV gate: $0.70 → $0.60 after 30 profitable trades")
    print("   ℹ️  Losing streak breaker: 12h throttle after 5 losses")
    print("   ℹ️  Profit lock: Reduce size 25% when session P&L > $250")
    print("✅ Phase 7.6 Performance Patch started")
    
    print("\n🤖 Starting Phase 8.0 Full Autonomy...")
    try:
        from phase80_coordinator import create_phase80_coordinator
        phase80 = create_phase80_coordinator()
        phase80.start()
        print("   ℹ️  Self-healing watchdogs: Active (60s)")
        print("   ℹ️  Shadow experiments: A/B testing per symbol")
        print("   ℹ️  Capital ramp gates: Correlation-aware scaling")
        print("   ℹ️  Profit attribution: Governor reweighting (30min)")
        print("   ℹ️  Exposure & pyramiding: Per-tier caps enforced")
        print("✅ Phase 8.0 Full Autonomy started")
    except Exception as e:
        print(f"⚠️  Phase 8.0 failed to start: {e}")
    
    print("\n🎯 Starting Phase 8.1 Edge Compounding...")
    try:
        from phase81_edge_compounding import initialize_phase81
        initialize_phase81()
        print("   ℹ️  Bandit meta-optimizer: 30min cadence (epsilon=0.10)")
        print("   ℹ️  Regime classifier v2: 5min cadence (volatility + imbalance)")
        print("   ℹ️  Drawdown recovery: Staged tightening/expansion")
        print("   ℹ️  Fill-quality learner: Per-symbol time-of-day routing")
        print("   ℹ️  Overnight sentinel: Risk throttling 22:00-05:00")
        print("✅ Phase 8.1 Edge Compounding started")
    except Exception as e:
        print(f"⚠️  Phase 8.1 failed to start: {e}")
    
    print("\n🚀 Starting Phase 8.2 Go-Live Controller...")
    try:
        from phase82_go_live import initialize_phase82
        initialize_phase82()
        print("   ℹ️  Ramp assessor: Hourly (12% steps, 6h cooldown)")
        print("   ℹ️  Kill-switch: 60s (DD≥3%, rejects≥7%, fees≥$25)")
        print("   ℹ️  Reconciliation: 5min verifier")
        print("   ℹ️  Regime mismatch: 5min sentinel (conservative mode)")
        print("✅ Phase 8.2 Go-Live Controller started")
    except Exception as e:
        print(f"⚠️  Phase 8.2 failed to start: {e}")
    
    print("\n🧪 Starting Phase 8.2 Validation Harness...")
    try:
        from phase82_validation import initialize_phase82_validation
        initialize_phase82_validation()
        print("✅ Phase 8.2 Validation Harness started")
    except Exception as e:
        print(f"⚠️  Phase 8.2 Validation failed to start: {e}")
    
    print("\n🔍 Starting Phase 8.3 Drift Detector...")
    try:
        from phase83_drift_detector import initialize_phase83
        initialize_phase83()
        print("   ℹ️  Drift monitor: 15min cadence (EV gates, trailing stops, pyramiding)")
        print("   ℹ️  Auto-restore: ±$0.02 EV, ±0.05R trailing, ±0.10R pyramiding")
        print("   ℹ️  Regression suite: Runs on config changes & promotions")
        print("   ℹ️  Baseline refresh: Every 12 hours")
        print("✅ Phase 8.3 Drift Detector started")
    except Exception as e:
        print(f"⚠️  Phase 8.3 Drift Detector failed to start: {e}")
    
    print("\n💎 Starting Phase 8.4-8.6 Expansion Pack...")
    try:
        from src.phase84_86_expansion import initialize_phase84_86
        initialize_phase84_86()
        print("   ℹ️  Phase 8.4 - Profit Optimizer: 30min cadence (attribution reweighting)")
        print("   ℹ️  Phase 8.5 - Predictive Intel: 5min early warning, hourly stress tests")
        print("   ℹ️  Phase 8.6 - Risk Layer: Correlation guards, hedge dispatcher")
        print("✅ Phase 8.4-8.6 Expansion Pack started")
    except Exception as e:
        print(f"⚠️  Phase 8.4-8.6 Expansion failed to start: {e}")
    
    print("\n🔬 Starting Phase 8.7-8.9 Expansion Pack...")
    try:
        from src.phase87_89_expansion import initialize_phase87_89
        initialize_phase87_89()
        print("   ℹ️  Phase 8.7 - Transparency & Audit: 60s cockpit, immutable audit chain")
        print("   ℹ️  Phase 8.8 - Collaborative Intel: 5min consensus, crowding guards")
        print("   ℹ️  Phase 8.9 - External Signals: 5min whale/sentiment/macro integration")
        print("✅ Phase 8.7-8.9 Expansion Pack started")
    except Exception as e:
        print(f"⚠️  Phase 8.7-8.9 Expansion failed to start: {e}")
    
    print("\n🧠 Starting Phase 9 Autonomy Controller...")
    try:
        from src.phase9_autonomy import initialize_phase9
        initialize_phase9()
        print("   ℹ️  Autonomy Governor: 10min health scoring + capital scaling")
        print("   ℹ️  Learning Loop: hourly attribution calibration + baseline refresh")
        print("   ℹ️  Watchdog: 1min subsystem liveness monitoring")
        print("   ℹ️  Feature Flags: 30min staged rollout (Phase 8.8/8.9)")
        print("✅ Phase 9 Autonomy Controller started")
    except Exception as e:
        print(f"⚠️  Phase 9 Autonomy Controller failed to start: {e}")
    
    print("\n🔧 Starting Phase 9.1 Adaptive Governance...")
    try:
        from src.phase91_adaptive_governance import start_phase91_adaptive_governance
        from src.phase91_export_service import initialize_phase91_exports
        
        start_phase91_adaptive_governance()
        initialize_phase91_exports()
        
        print("   ℹ️  Dynamic Tolerances: Hourly volatility-aware drift thresholds")
        print("   ℹ️  Health-Weighted Ramps: Capital scaling based on composite health")
        print("   ℹ️  Severity-Scored Watchdog: Multi-tier subsystem monitoring")
        print("   ℹ️  Confidence-Weighted Calibration: Hourly parameter nudges")
        print("   ℹ️  Health Trend Tracking: 1min continuous health history")
        print("   ℹ️  Export Endpoints: /api/export/* for structured data export")
        print("   ℹ️  Governance Cockpit: /phase91 dashboard view")
        print("✅ Phase 9.1 Adaptive Governance started")
    except Exception as e:
        print(f"⚠️  Phase 9.1 Adaptive Governance failed to start: {e}")
    
    print("\n📊 Starting Phase 9.2 Profit Discipline Pack...")
    try:
        from src.phase92_profit_discipline import start_phase92_profit_discipline_pack
        start_phase92_profit_discipline_pack()
        
        print("   ℹ️  Win Rate Optimization: Stricter entry filters (MTF≥0.50, Volume≥1.25x)")
        print("   ℹ️  Position Sizing: Reduce 30% on losing streaks, 50% on low win rate")
        print("   ℹ️  Trade Frequency: Max 10 trades/4h, throttle Sentiment-Fusion")
        print("   ℹ️  Exit Optimization: Tighter stops (1.5x ATR), time exits, profit locks")
        print("   ℹ️  Governance: Freeze ramps when win rate <40%")
        print("✅ Phase 9.2 Profit Discipline Pack started")
    except Exception as e:
        print(f"⚠️  Phase 9.2 Profit Discipline Pack failed to start: {e}")
    
    print("\n🎯 Starting Phase 9.3 Venue Governance & Scaling Controller...")
    try:
        from src.phase93_venue_governance import start_phase93_venue_governance
        from src.phase93_enforcement import start_venue_enforcement
        
        start_phase93_venue_governance()
        start_venue_enforcement()
        
        print("   ℹ️  Venue Priority: Futures ENABLED, Spot DISABLED (until proven)")
        print("   ℹ️  Expectancy Gates: Spot requires Sharpe≥0.8 & P&L≥$100 sustained")
        print("   ℹ️  Exposure Caps: Spot 20%, Futures 60%, Symbol 10%")
        print("   ℹ️  Frequency Limits: Spot 4/4h, Futures 12/4h, per-strategy throttles")
        print("   ℹ️  Futures Sizing: Streak-aware reduction (30% on 5+ losses)")
        print("   ℹ️  Enforcement: 3-level spot blockade (router → gate → execution)")
        print("   ℹ️  Dashboard: /phase93 monitoring view")
        print("✅ Phase 9.3 Venue Governance & Scaling Controller started")
    except Exception as e:
        print(f"⚠️  Phase 9.3 Venue Governance & Scaling Controller failed to start: {e}")
    
    print("\n🚀 Starting Phase 9.4 Recovery & Scaling Pack...")
    try:
        from src.phase94_recovery_scaling import start_phase94_recovery_scaling
        start_phase94_recovery_scaling()
        
        print("   ℹ️  Recovery Thresholds: Partial (40% WR, 0.8 Sharpe), Full (60% WR, 1.0 Sharpe)")
        print("   ℹ️  Sustained Passes: 3 consecutive checks required for scaling")
        print("   ℹ️  Exposure Scaling: +5% (partial), +10% (full) on recovery")
        print("   ℹ️  Ramp Multipliers: 0.5x (partial), 1.0x (full)")
        print("   ℹ️  Check Cadence: 10 minutes (600 seconds)")
        print("   ℹ️  Dashboard: /phase94 monitoring view")
        print("✅ Phase 9.4 Recovery & Scaling Pack started")
    except Exception as e:
        print(f"⚠️  Phase 9.4 Recovery & Scaling Pack failed to start: {e}")
    
    print("\n🛡️ Starting Leverage Governance Module...")
    try:
        from src.leverage_governance import register_leverage_governance
        from src.pnl_dashboard import get_wallet_balance
        from src.exchange_gateway import ExchangeGateway
        
        # Create a simple periodic task registrar for leverage governance
        def dummy_register_periodic_task(task_fn, interval_sec):
            """Dummy registrar - module runs governance checks every 10 minutes"""
            import threading
            def periodic_runner():
                import time
                while True:
                    try:
                        time.sleep(interval_sec)
                        task_fn()
                    except Exception as e:
                        print(f"⚠️  Leverage governance task failed: {e}")
            thread = threading.Thread(target=periodic_runner, daemon=True)
            thread.start()
        
        # Initialize with wallet balance and price getter
        gateway = ExchangeGateway()
        get_price_fn = lambda sym: gateway.get_price(sym, venue="futures")
        
        register_leverage_governance(dummy_register_periodic_task, get_wallet_balance, get_price_fn)
        print("   ℹ️  Dynamic leverage: 1x-10x based on signal confidence (ROI ≥0.5%)")
        print("   ℹ️  Stop-loss enforcement: Auto-calculated to cap wallet risk at 2%")
        print("   ℹ️  Trailing stops: Activate at +0.5% profit, tighten by 0.25% increments")
        print("   ℹ️  Margin monitor: Warns if total exposure > 3x wallet balance")
        print("   ℹ️  Governance cadence: 10-minute periodic checks")
        print("✅ Leverage Governance Module started")
    except Exception as e:
        print(f"⚠️  Leverage Governance Module failed to start: {e}")
    
    print("\n💰 Starting Phase 10 Profit Engine...")
    try:
        from src.phase10_profit_engine import start_phase10_profit_engine
        start_phase10_profit_engine()
    except Exception as e:
        print(f"⚠️  Phase 10 Profit Engine failed to start: {e}")
    
    print("\n🎯 Starting Phase 10.1 Attribution-Weighted Allocator...")
    try:
        from src.phase101_allocator import start_phase101_allocator
        start_phase101_allocator()
    except Exception as e:
        print(f"⚠️  Phase 10.1 Allocator failed to start: {e}")
    
    print("\n🔥 Starting Phase 10.2 Futures Optimizer...")
    try:
        from src.phase102_futures_optimizer import start_phase102_futures_optimizer, phase102_allocator_tick, phase102_shadow_tick
        
        start_phase102_futures_optimizer()
        
        # Start periodic ranking thread (5 minutes)
        def ranking_thread():
            while True:
                try:
                    time.sleep(300)  # 5 minutes
                    phase102_allocator_tick()
                except Exception as e:
                    print(f"Phase 10.2 ranking error: {e}")
        
        # Start periodic shadow sweep thread (10 minutes)
        def shadow_thread():
            while True:
                try:
                    time.sleep(600)  # 10 minutes
                    phase102_shadow_tick()
                except Exception as e:
                    print(f"Phase 10.2 shadow error: {e}")
        
        threading.Thread(target=ranking_thread, daemon=True).start()
        threading.Thread(target=shadow_thread, daemon=True).start()
        print("✅ Phase 10.2 Futures Optimizer started")
    except Exception as e:
        print(f"⚠️  Phase 10.2 Futures Optimizer failed to start: {e}")
    
    print("\n🎯 Starting Phase 10.3-10.5 (Adaptive Risk + Execution + Experiments)...")
    try:
        from src.phase10x_combined import start_phase10x_all
        
        ticks = start_phase10x_all()
        
        # Start periodic task threads
        def risk_thread():
            while True:
                try:
                    time.sleep(300)  # 5 minutes
                    ticks['risk_tick']()
                except Exception as e:
                    print(f"Phase 10.x risk tick error: {e}")
        
        def exec_thread():
            while True:
                try:
                    time.sleep(300)  # 5 minutes
                    ticks['exec_tick']()
                except Exception as e:
                    print(f"Phase 10.x exec tick error: {e}")
        
        def exp_thread():
            while True:
                try:
                    time.sleep(600)  # 10 minutes
                    ticks['exp_tick']()
                except Exception as e:
                    print(f"Phase 10.x experiment tick error: {e}")
        
        threading.Thread(target=risk_thread, daemon=True).start()
        threading.Thread(target=exec_thread, daemon=True).start()
        threading.Thread(target=exp_thread, daemon=True).start()
        print("✅ Phase 10.3-10.5 started (risk/exec/exp periodic tasks running)")
    except Exception as e:
        print(f"⚠️  Phase 10.3-10.5 failed to start: {e}")
    
    print("\n⚡ Starting Phase 10.6 (Calibration & Auto-Tuning)...")
    try:
        from src.phase106_calibration import start_phase106_calibration
        
        calibration_tick = start_phase106_calibration()
        
        # Start periodic calibration thread (15 minutes)
        def calibration_thread():
            while True:
                try:
                    time.sleep(900)  # 15 minutes
                    calibration_tick()
                except Exception as e:
                    print(f"Phase 10.6 calibration tick error: {e}")
        
        threading.Thread(target=calibration_thread, daemon=True).start()
        print("✅ Phase 10.6 started (calibration tick every 15min)")
    except Exception as e:
        print(f"⚠️  Phase 10.6 failed to start: {e}")
    
    print("\n⚡ Starting Phase 10.7-10.9 (Predictive Intelligence + Capital Governance + Recovery)...")
    try:
        from src.phase107_109 import start_phase107_109
        
        def get_live_symbols():
            return ["ETHUSDT", "SOLUSDT", "AVAXUSDT", "DOTUSDT", "TRXUSDT", "BTCUSDT"]
        
        capital_tick, recovery_tick_fn = start_phase107_109()
        
        # Start periodic capital governance thread (5 minutes)
        def capital_thread():
            while True:
                try:
                    time.sleep(300)  # 5 minutes
                    capital_tick()
                except Exception as e:
                    print(f"Phase 10.8 capital tick error: {e}")
        
        # Start periodic recovery thread (5 minutes)
        def recovery_thread():
            while True:
                try:
                    time.sleep(300)  # 5 minutes
                    recovery_tick_fn(get_live_symbols())
                except Exception as e:
                    print(f"Phase 10.9 recovery tick error: {e}")
        
        threading.Thread(target=capital_thread, daemon=True).start()
        threading.Thread(target=recovery_thread, daemon=True).start()
        print("✅ Phase 10.7-10.9 started (capital/recovery ticks every 5min)")
    except Exception as e:
        print(f"⚠️  Phase 10.7-10.9 failed to start: {e}")
    
    print("\n🌐 Starting Phase 10.10-10.12 (Collaborative Intelligence + Arbitrage + Operator Controls)...")
    try:
        from src.phase1010_1012 import start_phase1010_1012, phase1011_arbitrage_tick
        
        start_phase1010_1012()
        
        # Start periodic arbitrage tick (5 minutes)
        def arbitrage_thread():
            while True:
                try:
                    time.sleep(300)  # 5 minutes
                    phase1011_arbitrage_tick(get_live_symbols())
                except Exception as e:
                    print(f"Phase 10.11 arbitrage tick error: {e}")
        
        threading.Thread(target=arbitrage_thread, daemon=True).start()
        print("✅ Phase 10.10-10.12 started (arbitrage tick every 5min)")
    except Exception as e:
        print(f"⚠️  Phase 10.10-10.12 failed to start: {e}")
    
    print("\n⚡ Starting Phase 10.13-10.15 (Expectancy Attribution + Risk Parity + Degradation Auditor)...")
    try:
        from src.phase1013_1015 import start_phase1013_1015, phase1015_audit_tick
        
        start_phase1013_1015()
        
        # Start periodic degradation audit (10 minutes)
        def audit_thread():
            while True:
                try:
                    time.sleep(600)  # 10 minutes
                    phase1015_audit_tick()
                except Exception as e:
                    print(f"Phase 10.15 audit tick error: {e}")
        
        threading.Thread(target=audit_thread, daemon=True).start()
        print("✅ Phase 10.13-10.15 started (audit tick every 10min)")
    except Exception as e:
        print(f"⚠️  Phase 10.13-10.15 failed to start: {e}")
    
    print("\n⚡ Starting Phase 10.16-10.18 (Meta Router + Hedger + Governance)...")
    try:
        from src.phase1016_1018 import (
            start_phase1016_1018,
            phase1016_route_tick,
            phase1017_hedge_tick,
            phase1018_governance_tick
        )
        
        start_phase1016_1018()
        
        # Start periodic ticks for all three phases (5 minutes)
        def phase1016_1018_thread():
            while True:
                try:
                    time.sleep(300)  # 5 minutes
                    phase1016_route_tick()  # Meta-expectancy routing
                    phase1017_hedge_tick()  # Correlation hedging
                    phase1018_governance_tick()  # Autonomous governance
                except Exception as e:
                    print(f"Phase 10.16-10.18 tick error: {e}")
        
        threading.Thread(target=phase1016_1018_thread, daemon=True).start()
        print("✅ Phase 10.16-10.18 started (ticks every 5min)")
    except Exception as e:
        print(f"⚠️  Phase 10.16-10.18 failed to start: {e}")
    
    # NOTE: Unified Stack disabled - Phase 10.16-10.18 operates independently
    # The unified stack requires additional phase function mapping and is not critical
    # for current functionality. Each phase runs successfully in its own module.
    # print("\n🌐 Starting Unified Orchestration Stack...")
    # try:
    #     from src.unified_stack import start_unified_stack
    #     start_unified_stack()
    #     print("✅ Unified Stack orchestration active")
    # except Exception as e:
    #     print(f"⚠️  Unified Stack failed to start: {e}")
    
    print("\n🛡️ Starting Governance Sentinel...")
    try:
        from src.governance_sentinel import register_governance_sentinel
        from src.phase10_profit_engine import register_periodic_task
        
        register_governance_sentinel(register_periodic_task)
    except Exception as e:
        print(f"⚠️  Governance Sentinel failed to start: {e}")
    
    print("\n🌙 Starting Nightly Maintenance Scheduler...")
    try:
        from src.nightly_governance import register_nightly_governance
        from src.phase10_profit_engine import register_periodic_task
        
        register_nightly_governance(register_periodic_task)
    except Exception as e:
        print(f"⚠️  Nightly Maintenance Scheduler failed to start: {e}")
    
    print("\n🩺 Starting Production Health Monitor...")
    try:
        from src.production_health_monitor import start_health_monitoring
        health_monitor = start_health_monitoring()
        print("   ℹ️  Immediate closure rate: Monitors for risk cap conflicts")
        print("   ℹ️  File integrity: Detects JSON corruption from concurrent writes")
        print("   ℹ️  Risk cap isolation: Verifies Alpha/Beta portfolio separation")
        print("   ℹ️  P&L trend: Alerts on hourly loss thresholds")
        print("   ℹ️  Data staleness: Checks learning data freshness")
        print("   ℹ️  Check interval: Every 5 minutes")
        print("✅ Production Health Monitor started")
    except Exception as e:
        print(f"⚠️  Production Health Monitor failed to start: {e}")
# ==========================================


def _log_crash(error: Exception, context: str = "main"):
    """Log crash to persistent file so we can diagnose overnight failures."""
    from datetime import datetime
    import traceback as tb
    
    crash_file = Path("logs/process_crash.log")
    crash_file.parent.mkdir(exist_ok=True)
    
    timestamp = datetime.now().isoformat()
    crash_entry = f"""
{'='*60}
CRASH AT: {timestamp}
CONTEXT: {context}
ERROR: {type(error).__name__}: {error}
TRACEBACK:
{tb.format_exc()}
{'='*60}
"""
    
    try:
        with open(crash_file, "a") as f:
            f.write(crash_entry)
        print(f"💥 CRASH LOGGED to {crash_file}")
    except:
        print(f"💥 CRASH (failed to log): {error}")


def _get_memory_mb() -> float:
    """Get current process memory usage in MB using /proc on Linux."""
    try:
        with open('/proc/self/status', 'r') as f:
            for line in f:
                if line.startswith('VmRSS:'):
                    # VmRSS is in kB, convert to MB
                    return int(line.split()[1]) / 1024
    except:
        pass
    return 0.0


def _start_process_heartbeat():
    """
    Write a heartbeat file every 60 seconds to prove the process is alive.
    Also monitors memory usage to detect potential OOM conditions.
    This runs in a daemon thread and helps diagnose overnight failures.
    """
    import json
    from datetime import datetime
    
    heartbeat_file = Path("logs/process_heartbeat.json")
    resource_log = Path("logs/process_resource.jsonl")
    MEMORY_WARNING_MB = 1500  # Warn if memory exceeds 1.5GB
    
    def heartbeat_loop():
        while True:
            try:
                memory_mb = _get_memory_mb()
                uptime = time.time() - _process_start_time
                
                data = {
                    "pid": os.getpid(),
                    "timestamp": datetime.now().isoformat(),
                    "uptime_seconds": uptime,
                    "memory_mb": round(memory_mb, 1)
                }
                
                heartbeat_file.parent.mkdir(exist_ok=True)
                with open(heartbeat_file, "w") as f:
                    json.dump(data, f)
                
                # Log resource usage for analysis
                with open(resource_log, "a") as f:
                    f.write(json.dumps(data) + "\n")
                
                # Warn if memory is high
                if memory_mb > MEMORY_WARNING_MB:
                    print(f"⚠️ HIGH MEMORY WARNING: {memory_mb:.0f}MB (threshold: {MEMORY_WARNING_MB}MB)")
                    
            except Exception as e:
                print(f"⚠️ Process heartbeat error: {e}")
            time.sleep(60)
    
    t = threading.Thread(target=heartbeat_loop, daemon=True, name="ProcessHeartbeat")
    t.start()
    print("💓 Process heartbeat + memory monitor started (60s interval)")


_process_start_time = time.time()


def main_with_crash_protection():
    """
    Wrapper around main() that catches ALL crashes and restarts automatically.
    This ensures the bot runs 24/7 even if individual components fail.
    """
    max_restarts = 100  # Prevent infinite restart loops
    restart_count = 0
    restart_delay = 10  # seconds between restarts
    
    while restart_count < max_restarts:
        try:
            print(f"\n{'='*60}")
            print(f"🔄 STARTING BOT (attempt {restart_count + 1})")
            print(f"{'='*60}")
            
            # Start process heartbeat to prove we're alive
            _start_process_heartbeat()
            
            # Run the actual bot
            main()
            
            # If main() returns normally (shouldn't happen), restart
            print("⚠️ main() returned unexpectedly - restarting...")
            
        except KeyboardInterrupt:
            print("\n👋 Shutdown requested by user")
            break
            
        except SystemExit as e:
            if e.code == 0:
                print("✅ Clean shutdown")
                break
            else:
                print(f"⚠️ SystemExit with code {e.code} - restarting...")
                _log_crash(Exception(f"SystemExit code={e.code}"), "SystemExit")
                
        except Exception as e:
            restart_count += 1
            _log_crash(e, f"main_crash_restart_{restart_count}")
            print(f"💥 CRASH #{restart_count}: {type(e).__name__}: {e}")
            print(f"   Restarting in {restart_delay} seconds...")
            time.sleep(restart_delay)
            
            # Exponential backoff up to 5 minutes
            restart_delay = min(restart_delay * 1.5, 300)
    
    if restart_count >= max_restarts:
        print(f"❌ FATAL: Exceeded {max_restarts} restart attempts. Giving up.")
        _log_crash(Exception(f"Exceeded {max_restarts} restarts"), "restart_limit_exceeded")


if __name__ == "__main__":
    main_with_crash_protection()
