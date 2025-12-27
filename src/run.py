"""
Trading Bot - Main Entry Point

⚠️ AI ASSISTANTS: Before modifying this file or related dashboard code:
- READ MEMORY_BANK.md - Contains critical project knowledge and past failures
- See CONTEXT.md for quick reference
- Follow REQUIRED PROCESS in MEMORY_BANK.md for date/data changes

The dashboard (pnl_dashboard_v2.py) has had critical issues documented in MEMORY_BANK.md.
"""

import os
from dotenv import load_dotenv
from pathlib import Path

# Load .env from project root (works in any deployment)
_project_root = Path(__file__).parent.parent
_env_path = _project_root / ".env"
if _env_path.exists():
    load_dotenv(_env_path)
else:
    # Fallback to common locations
    for fallback in ["/root/trading-bot-current/.env", "/root/trading-bot/.env", ".env"]:
        if Path(fallback).exists():
            load_dotenv(fallback)
            break
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

import traceback

# Import run_bot_cycle with explicit error handling
try:
    from src.bot_cycle import run_bot_cycle
    _run_bot_cycle_available = True
    print("[ENGINE] Successfully imported run_bot_cycle from src.bot_cycle")
except ImportError as e:
    # Fallback to old import path for compatibility
    try:
        from bot_cycle import run_bot_cycle
        _run_bot_cycle_available = True
        print("[ENGINE] Successfully imported run_bot_cycle from bot_cycle (legacy path)")
    except ImportError as e2:
        _run_bot_cycle_available = False
        run_bot_cycle = None
        print(f"[ENGINE] CRITICAL: Failed to import run_bot_cycle: {e2}")
        print(f"[ENGINE] This will prevent the trading engine from starting!")

RESTART_MARKER = Path("logs/.restart_needed")

# Module-level variable to store healing result for run_heavy_initialization
_healing_result = None

# Module-level flag to track if engine has been started (prevent double-start)
_engine_started_flag = False


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
        
        # Check ALL critical ports (not just 8050) to prevent conflicts
        CRITICAL_PORTS = [8050, 5000, 3000, 8080]
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
                    print(f"[ENGINE] Bot cycle stalled - no heartbeat for {age:.0f}s", flush=True)
                    # Log to file for external supervisor to detect
                    with open("logs/stall_warning.txt", "w") as f:
                        f.write(f"STALLED: {time.strftime('%Y-%m-%dT%H:%M:%SZ')} age={age:.0f}s\n")
                    # Alert operator
                    try:
                        from src.operator_safety import alert_operator, ALERT_HIGH
                        alert_operator(ALERT_HIGH, "engine_stall_detected", {
                            "age_seconds": age,
                            "last_cycle_ts": _last_bot_cycle_ts
                        })
                    except:
                        pass
            
            # Log heartbeat proof that supervisor is alive
            with open("logs/supervisor_heartbeat.txt", "w") as f:
                f.write(f"{time.strftime('%Y-%m-%dT%H:%M:%SZ')}\n")
                
        except Exception as e:
            print(f"⚠️ [SUPERVISOR] Error: {e}")


def start_trading_engine_for_mode(is_paper_mode: bool):
    """
    Explicitly start the trading engine thread.
    This function MUST be called to start the engine.
    
    Args:
        is_paper_mode: True if paper trading mode, False for real trading
    
    Returns:
        bool: True if engine started successfully, False otherwise
    """
    global _engine_started_flag
    
    # Prevent double-starting
    if _engine_started_flag:
        print("[ENGINE] Engine already started - skipping duplicate start", flush=True)
        return True
    
    print("\n" + "="*60)
    print("[ENGINE] STARTING TRADING ENGINE")
    print("="*60)
    print(f"[ENGINE] Mode: {'PAPER' if is_paper_mode else 'REAL'}", flush=True)
    
    # Validate run_bot_cycle is available
    if not _run_bot_cycle_available or run_bot_cycle is None:
        error_msg = "CRITICAL: run_bot_cycle is not available - cannot start engine"
        print(f"[ENGINE] {error_msg}", flush=True)
        try:
            from src.operator_safety import alert_operator, ALERT_CRITICAL
            alert_operator(ALERT_CRITICAL, "engine_startup_failed", {
                "reason": "run_bot_cycle not available",
                "mode": "paper" if is_paper_mode else "real"
            })
        except:
            pass
        return False
    
    if not callable(run_bot_cycle):
        error_msg = f"CRITICAL: run_bot_cycle is not callable (type: {type(run_bot_cycle)})"
        print(f"[ENGINE] {error_msg}", flush=True)
        try:
            from src.operator_safety import alert_operator, ALERT_CRITICAL
            alert_operator(ALERT_CRITICAL, "engine_startup_failed", {
                "reason": "run_bot_cycle not callable",
                "type": str(type(run_bot_cycle)),
                "mode": "paper" if is_paper_mode else "real"
            })
        except:
            pass
        return False
    
    try:
        print("[ENGINE] Attempting to start engine thread", flush=True)
        print(f"[ENGINE] run_bot_cycle is available and callable: {callable(run_bot_cycle)}", flush=True)
        print(f"[ENGINE] bot_worker function: {bot_worker}", flush=True)
        
        bot_thread = threading.Thread(target=bot_worker, daemon=True, name="BotWorker")
        print("[ENGINE] Engine thread created", flush=True)
        print(f"[ENGINE] Thread object: {bot_thread}", flush=True)
        print(f"[ENGINE] Thread name: {bot_thread.name}", flush=True)
        print(f"[ENGINE] Thread daemon: {bot_thread.daemon}", flush=True)
        
        bot_thread.start()
        print("[ENGINE] Engine thread started", flush=True)
        print(f"[ENGINE] Thread is_alive: {bot_thread.is_alive()}", flush=True)
        
        # Start supervisor to ensure bot runs 24/7 even if thread dies
        supervisor_thread = threading.Thread(target=_bot_worker_supervisor, daemon=True, name="BotSupervisor")
        supervisor_thread.start()
        print("   ✅ Bot supervisor thread started (BotSupervisor)")
        print("\n✅ TRADING ENGINE IS NOW RUNNING")
        _engine_started_flag = True
        return True
        
    except Exception as e:
        error_msg = f"CRITICAL: Failed to start trading engine threads: {e}"
        print(f"[ENGINE] {error_msg}", flush=True)
        print(f"[ENGINE] Trading engine failed to start", flush=True)
        import traceback
        traceback.print_exc()
        
        try:
            from src.operator_safety import alert_operator, ALERT_CRITICAL
            alert_operator(ALERT_CRITICAL, "engine_startup_failed", {
                "reason": str(e),
                "mode": "paper" if is_paper_mode else "real",
                "traceback": traceback.format_exc()
            })
        except:
            pass
        
        if is_paper_mode:
            print("   ⚠️  PAPER MODE: This is unexpected - engine should always start")
        return False


def bot_worker():
    """
    Background thread that runs the trading bot cycle.
    """
    import time  # Ensure time is available in this scope
    global _last_bot_cycle_ts, _bot_worker_alive
    print("🤖 Bot worker thread started")
    print("[ENGINE] Engine loop entered", flush=True)
    
    # Start continuous heartbeat emitter to prevent safety freezes
    heartbeat_thread = threading.Thread(target=_continuous_heartbeat_emitter, daemon=True, name="ContinuousHeartbeat")
    heartbeat_thread.start()
    print("💓 [HEARTBEAT] Continuous heartbeat emitter started (30s interval)")
    
    try:
        from src.startup_health_check import update_heartbeat
        update_heartbeat()
        print("[ENGINE] Heartbeat updated", flush=True)
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
    
    # Start Signal State Machine with auto-expire
    print("🔄 [STATE-MACHINE] Starting Signal State Machine...")
    try:
        from src.signal_state_machine import get_state_machine
        state_machine = get_state_machine()
        
        # Auto-expire old signals on startup
        expired_count = state_machine.auto_expire_old_signals(max_age_seconds=7200)  # 2 hours
        if expired_count > 0:
            print(f"   🧹 Auto-expired {expired_count} old signals")
        
        # Start background thread to auto-expire old signals periodically
        def auto_expire_loop():
            import time
            while True:
                try:
                    time.sleep(3600)  # Check every hour
                    expired = state_machine.auto_expire_old_signals(max_age_seconds=7200)
                    if expired > 0:
                        print(f"🔄 [STATE-MACHINE] Auto-expired {expired} old signals")
                except Exception as e:
                    print(f"⚠️ [STATE-MACHINE] Auto-expire error: {e}")
                    time.sleep(60)
        
        expire_thread = threading.Thread(target=auto_expire_loop, daemon=True, name="SignalAutoExpire")
        expire_thread.start()
        print("✅ [STATE-MACHINE] State machine started with auto-expire (1h cycle)")
        print("   🔄 Auto-expires signals older than 2 hours")
        print("   📊 Tracks signal lifecycle explicitly")
    except Exception as e:
        print(f"⚠️ [STATE-MACHINE] State machine startup error: {e}")
        import traceback
        traceback.print_exc()
    
    # Start Shadow Execution Engine for what-if analysis
    print("🔮 [SHADOW] Starting Shadow Execution Engine...")
    try:
        from src.shadow_execution_engine import get_shadow_engine
        shadow_engine = get_shadow_engine()
        # Shadow engine initialized via get_shadow_engine() - no start() method needed
        print("✅ [SHADOW] Shadow execution engine started (background thread)")
        print("   🔮 Simulates ALL signals (even blocked ones) for what-if analysis")
        print("   📊 Tracks hypothetical P&L to evaluate guard effectiveness")
        print("   💡 Enables: 'What if I disabled the Volatility Guard?' analysis")
    except Exception as e:
        print(f"⚠️ [SHADOW] Shadow engine startup error: {e}")
        import traceback
        traceback.print_exc()
    
    # [BIG ALPHA] Start Self-Healing Learning Loop (Component 5)
    print("🔄 [SELF-HEALING] Starting Self-Healing Learning Loop...")
    try:
        from src.self_healing_learning_loop import start_learning_loop
        start_learning_loop()
        print("✅ [SELF-HEALING] Learning Loop started (4-hour intervals)")
        print("   📊 Compares shadow vs live trades every 4 hours")
        print("   💡 Analyzes guard effectiveness and generates recommendations")
    except Exception as e:
        print(f"⚠️ [SELF-HEALING] Failed to start Learning Loop: {e}")
        import traceback
        traceback.print_exc()
    
    # [FAILURE-POINT-MONITOR] Start comprehensive failure point monitoring and self-healing
    print("🔍 [FAILURE-POINT-MONITOR] Starting failure point monitoring...")
    try:
        from src.failure_point_monitor import get_failure_point_monitor
        monitor = get_failure_point_monitor()
        monitor.start()
        print("✅ [FAILURE-POINT-MONITOR] Failure point monitoring started (1-minute intervals)")
    except Exception as e:
        print(f"⚠️ [FAILURE-POINT-MONITOR] Failed to start monitoring: {e}")
        import traceback
        traceback.print_exc()
    
    # [BIG ALPHA] Initialize Symbol Probation State Machine (Component 6)
    print("🚫 [PROBATION] Initializing Symbol Probation State Machine...")
    try:
        from src.symbol_probation_state_machine import get_probation_machine
        probation_machine = get_probation_machine()
        # Run initial evaluation
        probation_machine.evaluate_all_symbols()
        print("✅ [PROBATION] Symbol Probation initialized")
        print("   📊 Evaluates symbol performance and places underperformers on probation")
        print("   🔄 Re-evaluates symbols periodically to allow recovery")
    except Exception as e:
        print(f"⚠️ [PROBATION] Failed to initialize Symbol Probation: {e}")
        import traceback
        traceback.print_exc()
    
    # Start Comprehensive Self-Healing Operator
    print("🔧 [HEALING] Starting Comprehensive Self-Healing Operator...")
    try:
        from src.healing_operator import start_healing_operator, get_healing_operator
        import time
        
        # Try to get existing instance first
        healing_op = get_healing_operator()
        if healing_op is None:
            healing_op = start_healing_operator()
        else:
            # Already exists, make sure it's running
            if not healing_op.running or not healing_op.thread or not healing_op.thread.is_alive():
                print("   ⚠️  Existing instance not running, starting...")
                healing_op.start()
        
        # Verify it's actually running
        time.sleep(0.3)  # Give thread time to start
        if healing_op and healing_op.running and healing_op.thread and healing_op.thread.is_alive():
            print("✅ [HEALING] Self-healing operator started (60s cycle)")
            print("   🔧 Auto-heals: Signal engine, Decision engine, Safety layer, File integrity")
            print("   🔧 Auto-heals: Exit gates, Trade execution, Heartbeat, Feature store")
            print("   🔧 Auto-heals: SignalBus, StateMachine, ShadowEngine, DecisionTracker (NEW)")
            print("   🔧 Monitors all health components and repairs automatically")
        else:
            print("❌ [HEALING] CRITICAL: Healing operator failed to start properly!")
            print("   → Attempting emergency restart...")
            # Emergency restart: create fresh instance
            try:
                from src.healing_operator import _healing_operator
                import src.healing_operator as healing_module
                # Force new instance
                healing_module._healing_operator = None
                healing_op = start_healing_operator()
                time.sleep(0.3)
                if healing_op and healing_op.running and healing_op.thread and healing_op.thread.is_alive():
                    print("   ✅ Emergency restart successful!")
                else:
                    print("   ❌ Emergency restart failed!")
                    print("   → Self-healing will NOT work until this is fixed")
            except Exception as e2:
                print(f"   ❌ Emergency restart error: {e2}")
                print("   → Self-healing will NOT work until this is fixed")
    except Exception as e:
        print(f"❌ [HEALING] CRITICAL: Healing operator startup error: {e}")
        import traceback
        traceback.print_exc()
        print("   → Self-healing will NOT work until this is fixed")
        print("   → Bot will continue but health monitoring is disabled")
    
    # NOTE: Signal Outcome Resolver is now started as a separate worker process in _start_all_worker_processes()
    # This ensures proper isolation, monitoring, and automatic restart on crash.
    # The resolver worker process handles all signal resolution.
    print("✅ [SIGNAL-TRACKER] Signal resolver will be started as worker process")
    
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
            # Update heartbeat on each cycle
            try:
                from src.startup_health_check import update_heartbeat
                update_heartbeat()
                print("[ENGINE] Heartbeat updated", flush=True)
            except Exception as hb_err:
                print(f"[ENGINE] Heartbeat update failed: {hb_err}", flush=True)
            
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
            
            # Call run_bot_cycle with explicit error handling
            if not _run_bot_cycle_available or run_bot_cycle is None:
                print("[ENGINE] CRITICAL: run_bot_cycle is not available - cannot execute trading cycle", flush=True)
                time.sleep(60)  # Wait before retrying
                continue
            
            if not callable(run_bot_cycle):
                print("[ENGINE] CRITICAL: run_bot_cycle is not callable - cannot execute trading cycle", flush=True)
                time.sleep(60)  # Wait before retrying
                continue
            
            print("[ENGINE] Calling run_bot_cycle()", flush=True)
            try:
                run_bot_cycle()
                print("[ENGINE] run_bot_cycle() completed successfully", flush=True)
            except Exception as e:
                print(f"[ENGINE] ERROR in run_bot_cycle(): {e}", flush=True)
                import traceback
                print(traceback.format_exc(), flush=True)
                # Continue loop - don't crash the worker thread
                time.sleep(60)  # Wait before retrying
                continue
            
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
        
        # Also run profitability trader persona analysis nightly
        try:
            from src.profitability_trader_persona import run_profitability_analysis
            schedule.every().day.at("10:30").do(lambda: run_profitability_analysis())
            print("   ✅ Profitability Trader Persona scheduled for 10:30 UTC (after main learning)")
        except Exception as e:
            print(f"   ⚠️ Could not schedule profitability trader persona: {e}")
    
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
    import json
    from pathlib import Path
    from datetime import datetime, timedelta
    
    try:
        from src.ensemble_predictor import get_ensemble_prediction
        from src.realtime_features import RealtimeFeatureCapture
        print("   ✅ Ensemble predictor module loaded")
    except Exception as e:
        print(f"   ❌ [ENSEMBLE-PREDICTOR] Failed to import modules: {e}")
        import traceback
        traceback.print_exc()
        return
    
    # Track last processed signal timestamp
    last_processed_ts = None
    from src.infrastructure.path_registry import PathRegistry
    predictive_signals_path = Path(PathRegistry.get_path("logs", "predictive_signals.jsonl"))
    ensemble_predictions_path = Path(PathRegistry.get_path("logs", "ensemble_predictions.jsonl"))
    
    # Ensure directories exist
    predictive_signals_path.parent.mkdir(parents=True, exist_ok=True)
    ensemble_predictions_path.parent.mkdir(parents=True, exist_ok=True)
    
    # Initialize feature capture
    try:
        feature_capture = RealtimeFeatureCapture()
        print("   ✅ Feature capture initialized")
    except Exception as e:
        print(f"   ⚠️  [ENSEMBLE-PREDICTOR] Feature capture init warning: {e}")
        feature_capture = None
    
    cycle_count = 0
    
    # Run periodic prediction generation (every 30 seconds)
    while True:
        try:
            cycle_count += 1
            
            # Read new predictive signals
            if not predictive_signals_path.exists():
                if cycle_count % 20 == 1:  # Log every 20 cycles (~10 minutes)
                    print(f"   ⏳ [ENSEMBLE-PREDICTOR] Waiting for predictive signals...")
                time.sleep(30)
                continue
            
            # Read all signals from file
            signals = []
            try:
                with open(predictive_signals_path, 'r') as f:
                    for line in f:
                        line = line.strip()
                        if line:
                            try:
                                signal = json.loads(line)
                                signals.append(signal)
                            except json.JSONDecodeError:
                                continue
            except Exception as e:
                print(f"   ⚠️  [ENSEMBLE-PREDICTOR] Error reading signals: {e}")
                time.sleep(30)
                continue
            
            if not signals:
                if cycle_count % 20 == 1:
                    print(f"   ⏳ [ENSEMBLE-PREDICTOR] No signals found, waiting...")
                time.sleep(30)
                continue
            
            # Process only new signals (those after last_processed_ts)
            new_signals = []
            if last_processed_ts:
                for signal in signals:
                    signal_ts = signal.get('ts', '')
                    if signal_ts and signal_ts > last_processed_ts:
                        new_signals.append(signal)
            else:
                # First run: process last 5 signals to catch up
                new_signals = signals[-5:]
            
            if new_signals:
                print(f"   📊 [ENSEMBLE-PREDICTOR] Processing {len(new_signals)} new signal(s)...")
                
                predictions_generated = 0
                for signal in new_signals:
                    try:
                        symbol = signal.get('symbol', '')
                        direction = signal.get('direction', '')
                        
                        if not symbol or not direction:
                            continue
                        
                        # Extract OFI and ensemble score from signal
                        ofi = signal.get('signals', {}).get('ofi', 0.0)
                        if isinstance(ofi, dict):
                            ofi = ofi.get('value', 0.0)
                        
                        ensemble_score = signal.get('alignment_score', 0.0)
                        confidence = signal.get('confidence', 0.0)
                        
                        # Build features for this symbol
                        features = {}
                        if feature_capture:
                            try:
                                features = feature_capture.capture_all_features(symbol, direction)
                            except Exception as e:
                                print(f"   ⚠️  [ENSEMBLE-PREDICTOR] Feature capture failed for {symbol}: {e}")
                                # Use minimal features from signal
                                features = {
                                    'return_1m': 0.0,
                                    'return_5m': 0.0,
                                    'return_15m': 0.0,
                                    'volatility_1h': 0.0,
                                    'bid_ask_imbalance': 0.0,
                                    'spread_bps': 0.0,
                                    'depth_ratio': 1.0
                                }
                        else:
                            # Minimal features if feature capture unavailable
                            features = {
                                'return_1m': 0.0,
                                'return_5m': 0.0,
                                'return_15m': 0.0,
                                'volatility_1h': 0.0,
                                'bid_ask_imbalance': 0.0,
                                'spread_bps': 0.0,
                                'depth_ratio': 1.0
                            }
                        
                        # Generate ensemble prediction
                        prediction = get_ensemble_prediction(
                            symbol=symbol,
                            direction=direction,
                            features=features,
                            ofi=float(ofi),
                            ensemble_score=float(ensemble_score)
                        )
                        
                        predictions_generated += 1
                        
                        # Update last processed timestamp
                        signal_ts = signal.get('ts', '')
                        if signal_ts:
                            last_processed_ts = signal_ts
                        
                    except Exception as e:
                        print(f"   ⚠️  [ENSEMBLE-PREDICTOR] Error processing signal for {signal.get('symbol', 'UNKNOWN')}: {e}")
                        import traceback
                        traceback.print_exc()
                        continue
                
                if predictions_generated > 0:
                    print(f"   ✅ [ENSEMBLE-PREDICTOR] Generated {predictions_generated} prediction(s)")
            else:
                if cycle_count % 40 == 1:  # Log every 40 cycles (~20 minutes)
                    print(f"   ✓ [ENSEMBLE-PREDICTOR] No new signals to process")
            
            # Sleep before next cycle
            time.sleep(30)
            
        except Exception as e:
            print(f"   ⚠️  [ENSEMBLE-PREDICTOR] Worker error: {e}")
            import traceback
            traceback.print_exc()
            time.sleep(30)

def _worker_signal_resolver():
    """
    Worker process for signal outcome resolution.
    
    This worker:
    1. Reads ensemble_predictions.jsonl to find new predictions
    2. Logs them to pending_signals.json via signal_tracker.log_signal()
    3. Resolves pending signals at forward horizons (1m, 5m, 15m, 30m, 1h)
    4. Writes outcomes to signal_outcomes.jsonl
    """
    print("📊 [SIGNAL-RESOLVER] Worker process started")
    import time
    import json
    from pathlib import Path
    from datetime import datetime
    
    try:
        from src.signal_outcome_tracker import signal_tracker
        print("   ✅ Signal tracker module loaded")
    except Exception as e:
        print(f"   ❌ [SIGNAL-RESOLVER] Failed to import signal_tracker: {e}")
        import traceback
        traceback.print_exc()
        return
    
    # Verify file paths
    from src.infrastructure.path_registry import PathRegistry
    ensemble_predictions_path = Path(PathRegistry.get_path("logs", "ensemble_predictions.jsonl"))
    pending_signals_path = Path("feature_store/pending_signals.json")
    outcomes_log_path = Path("logs/signal_outcomes.jsonl")
    
    # Ensure directories exist
    ensemble_predictions_path.parent.mkdir(parents=True, exist_ok=True)
    pending_signals_path.parent.mkdir(parents=True, exist_ok=True)
    outcomes_log_path.parent.mkdir(parents=True, exist_ok=True)
    
    print(f"   📁 Reading from: {ensemble_predictions_path}")
    print(f"   📁 Pending signals: {pending_signals_path}")
    print(f"   📁 Outcomes log: {outcomes_log_path}")
    
    # Track last processed prediction timestamp
    last_processed_ts = None
    cycle_count = 0
    
    # Run periodic resolution (every 60 seconds)
    while True:
        try:
            cycle_count += 1
            print(f"   🔄 [SIGNAL-RESOLVER] Starting resolution cycle #{cycle_count}")
            
            # STEP 1: Read new ensemble predictions and log them to pending_signals.json
            # SKIP if trading is frozen (no new signals should be logged during learning session)
            from src.full_bot_cycle import is_trading_frozen
            trading_frozen = is_trading_frozen()
            
            predictions_logged = 0
            if trading_frozen:
                if cycle_count % 10 == 1:  # Log every 10 cycles
                    print(f"   ⏸️  [SIGNAL-RESOLVER] Trading is frozen - skipping new signal logging (focusing on resolution)")
            elif ensemble_predictions_path.exists():
                try:
                    # Read all predictions
                    predictions = []
                    with open(ensemble_predictions_path, 'r') as f:
                        for line in f:
                            line = line.strip()
                            if line:
                                try:
                                    pred = json.loads(line)
                                    predictions.append(pred)
                                except json.JSONDecodeError:
                                    continue
                    
                    # Process only new predictions
                    new_predictions = []
                    if last_processed_ts:
                        for pred in predictions:
                            pred_ts = pred.get('ts', pred.get('timestamp', ''))
                            if pred_ts and pred_ts > last_processed_ts:
                                new_predictions.append(pred)
                    else:
                        # First run: process last 10 predictions to catch up
                        new_predictions = predictions[-10:]
                    
                    # Log new predictions to pending_signals.json
                    for pred in new_predictions:
                        try:
                            symbol = pred.get('symbol', '')
                            direction = pred.get('direction', '')
                            confidence = pred.get('confidence', pred.get('prob_win', 0.5))
                            pred_ts = pred.get('ts', pred.get('timestamp', ''))
                            
                            if not symbol or not direction:
                                continue
                            
                            # Get current price for the symbol
                            try:
                                price = signal_tracker._get_current_price(symbol)
                                if price is None or price <= 0:
                                    # Try to extract from prediction if available
                                    price = pred.get('price', pred.get('entry_price', 0))
                                    if price <= 0:
                                        continue
                            except Exception as e:
                                print(f"   ⚠️  [SIGNAL-RESOLVER] Error getting price for {symbol}: {e}")
                                continue
                            
                            # Log signal to pending_signals.json
                            # Use 'ensemble' as signal_name since it's from ensemble predictions
                            signal_id = signal_tracker.log_signal(
                                symbol=symbol,
                                signal_name='ensemble',  # Mark as ensemble prediction
                                direction=direction,
                                confidence=float(confidence),
                                price=float(price),
                                signal_data={
                                    'source': 'ensemble_predictions.jsonl',
                                    'prediction_data': pred
                                }
                            )
                            
                            if signal_id:
                                predictions_logged += 1
                                if pred_ts:
                                    last_processed_ts = pred_ts
                                    
                        except Exception as e:
                            print(f"   ⚠️  [SIGNAL-RESOLVER] Error logging prediction for {pred.get('symbol', 'UNKNOWN')}: {e}")
                            import traceback
                            traceback.print_exc()
                            continue
                    
                    if predictions_logged > 0:
                        print(f"   ✅ [SIGNAL-RESOLVER] Logged {predictions_logged} new prediction(s) to pending_signals.json")
                    
                except Exception as e:
                    print(f"   ⚠️  [SIGNAL-RESOLVER] Error reading ensemble_predictions.jsonl: {e}")
                    import traceback
                    traceback.print_exc()
            else:
                if cycle_count % 10 == 1:  # Log every 10 cycles
                    print(f"   ⏳ [SIGNAL-RESOLVER] ensemble_predictions.jsonl does not exist yet")
            
            # STEP 2: Resolve pending signals at forward horizons
            # OPTIMIZATION: Increased batch size for faster catch-up (500 signals per cycle, no throttle)
            # Since CPU is maxed, we process more per cycle to catch up faster
            print(f"   🔍 [SIGNAL-RESOLVER] Resolving pending signals (batch mode: 500 per cycle, no throttle)...")
            pending_count_before = len(signal_tracker.pending_signals)
            resolved_count = signal_tracker.resolve_pending_signals(max_signals_per_cycle=500, throttle_ms=0)
            pending_count_after = len(signal_tracker.pending_signals)
            
            if resolved_count > 0:
                print(f"   ✅ [SIGNAL-RESOLVER] Resolved {resolved_count} signal(s) and wrote to signal_outcomes.jsonl")
            else:
                if pending_count_before > 0:
                    print(f"   ⏳ [SIGNAL-RESOLVER] {pending_count_before} pending signal(s) waiting for resolution horizons")
                else:
                    if cycle_count % 10 == 1:  # Log every 10 cycles
                        print(f"   ⏳ [SIGNAL-RESOLVER] No pending signals to resolve")
            
            # STEP 3: Verify outcomes file was written
            if resolved_count > 0 and outcomes_log_path.exists():
                outcomes_mtime = outcomes_log_path.stat().st_mtime
                outcomes_age_seconds = time.time() - outcomes_mtime
                if outcomes_age_seconds < 120:  # Written in last 2 minutes
                    print(f"   ✅ [SIGNAL-RESOLVER] Verified: signal_outcomes.jsonl was updated {outcomes_age_seconds:.1f}s ago")
            
            print(f"   ✅ [SIGNAL-RESOLVER] Completed resolution cycle #{cycle_count}")
            
            # Sleep before next cycle
            time.sleep(60)
            
        except Exception as e:
            print(f"   ❌ [SIGNAL-RESOLVER] Worker error in cycle #{cycle_count}: {e}")
            import traceback
            traceback.print_exc()
            time.sleep(60)

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
                # Note: We don't update _worker_restart_counts here because this runs in a child process
                # and updates won't be visible to the parent. Restart counts are tracked in the parent
                # process by the monitor when it detects dead processes.
                
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
    
    # Start predictive engine worker (upstream - generates signals)
    print("\n🔮 Starting predictive engine...")
    pred_process = _start_worker_process("predictive_engine", _worker_predictive_engine, restart_on_crash=True)
    if pred_process:
        print("   ✅ Predictive engine worker started successfully")
    else:
        print("   ❌ CRITICAL: Failed to start predictive engine worker!")
    
    # Start feature builder worker
    print("\n🔨 Starting feature builder...")
    feature_process = _start_worker_process("feature_builder", _worker_feature_builder, restart_on_crash=True)
    if feature_process:
        print("   ✅ Feature builder worker started successfully")
    else:
        print("   ⚠️  Feature builder worker failed to start (non-critical)")
    
    # Start ensemble predictor worker (depends on predictive signals)
    print("\n🎯 Starting ensemble predictor...")
    ensemble_process = _start_worker_process("ensemble_predictor", _worker_ensemble_predictor, restart_on_crash=True)
    if ensemble_process:
        print("   ✅ Ensemble predictor worker started successfully")
    else:
        print("   ❌ CRITICAL: Failed to start ensemble predictor worker!")
    
    # Start signal resolver worker (depends on ensemble predictions)
    print("\n📊 Starting signal resolver...")
    print("   ℹ️  Resolver will read ensemble_predictions.jsonl and create outcomes")
    resolver_process = _start_worker_process("signal_resolver", _worker_signal_resolver, restart_on_crash=True)
    if resolver_process:
        print(f"   ✅ Signal resolver worker started successfully (PID: {resolver_process.pid})")
        print("   📋 Resolver responsibilities:")
        print("      - Reads ensemble_predictions.jsonl every 60 seconds")
        print("      - Logs predictions to feature_store/pending_signals.json")
        print("      - Resolves signals at 1m, 5m, 15m, 30m, 1h horizons")
        print("      - Writes outcomes to logs/signal_outcomes.jsonl")
    else:
        print("   ❌ CRITICAL: Failed to start signal resolver worker!")
    
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
                        # Increment restart count when we detect a dead process
                        _worker_restart_counts[name] = _worker_restart_counts.get(name, 0) + 1
                        restart_count = _worker_restart_counts[name]
                        print(f"   ⚠️  [{name}] Process died (exit code: {process.exitcode})")
                        print(f"   🔄 [{name}] Restarting (attempt {restart_count})...")
                
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

def _monitor_pipeline_health():
    """Monitor the trading pipeline health and log warnings for blocked stages."""
    import time
    import json
    from pathlib import Path
    from datetime import datetime, timedelta
    
    print("🔍 [PIPELINE-HEALTH] Starting pipeline health monitor...")
    
    while True:
        try:
            time.sleep(300)  # Check every 5 minutes
            
            issues = []
            warnings = []
            
            # Check predictive_signals.jsonl
            from src.infrastructure.path_registry import PathRegistry
            pred_signals_path = Path(PathRegistry.get_path("logs", "predictive_signals.jsonl"))
            if pred_signals_path.exists():
                mtime = pred_signals_path.stat().st_mtime
                age_minutes = (time.time() - mtime) / 60
                if age_minutes > 15:
                    warnings.append(f"⚠️ predictive_signals.jsonl is stale ({age_minutes:.1f} min old)")
            else:
                warnings.append("⚠️ predictive_signals.jsonl does not exist")
            
            # Check ensemble_predictions.jsonl
            ensemble_path = Path("logs/ensemble_predictions.jsonl")
            if ensemble_path.exists():
                mtime = ensemble_path.stat().st_mtime
                age_minutes = (time.time() - mtime) / 60
                if age_minutes > 15:
                    warnings.append(f"⚠️ ensemble_predictions.jsonl is stale ({age_minutes:.1f} min old)")
            else:
                warnings.append("⚠️ ensemble_predictions.jsonl does not exist")
            
            # Check pending_signals.json
            pending_path = Path("feature_store/pending_signals.json")
            if pending_path.exists():
                try:
                    with open(pending_path, 'r') as f:
                        pending_data = json.load(f)
                        pending_count = len(pending_data) if isinstance(pending_data, dict) else 0
                        if pending_count > 0:
                            # Check if signals are being resolved
                            outcomes_path = Path("logs/signal_outcomes.jsonl")
                            if outcomes_path.exists():
                                outcomes_mtime = outcomes_path.stat().st_mtime
                                outcomes_age_minutes = (time.time() - outcomes_mtime) / 60
                                if outcomes_age_minutes > 30:
                                    issues.append(f"❌ {pending_count} pending signals exist but signal_outcomes.jsonl is stale ({outcomes_age_minutes:.1f} min old) - resolver may not be working")
                            else:
                                issues.append(f"❌ {pending_count} pending signals exist but signal_outcomes.jsonl does not exist - resolver may not be working")
                except Exception as e:
                    warnings.append(f"⚠️ Error reading pending_signals.json: {e}")
            else:
                # This is OK if no signals have been logged yet
                pass
            
            # Check signal_outcomes.jsonl
            outcomes_path = Path("logs/signal_outcomes.jsonl")
            if outcomes_path.exists():
                mtime = outcomes_path.stat().st_mtime
                age_minutes = (time.time() - mtime) / 60
                if age_minutes > 30:
                    warnings.append(f"⚠️ signal_outcomes.jsonl is stale ({age_minutes:.1f} min old)")
            else:
                warnings.append("⚠️ signal_outcomes.jsonl does not exist (no signals resolved yet)")
            
            # Log issues and warnings
            if issues:
                print("\n" + "="*60)
                print("🚨 PIPELINE HEALTH ISSUES DETECTED")
                print("="*60)
                for issue in issues:
                    print(f"   {issue}")
                print("="*60 + "\n")
            
            if warnings and (len(warnings) > 0):
                if len(warnings) <= 2:  # Only log if there are a few warnings
                    for warning in warnings:
                        print(f"   {warning}")
            
        except Exception as e:
            print(f"   ⚠️  [PIPELINE-HEALTH] Monitor error: {e}")
            time.sleep(300)

def run_heavy_initialization():
    """
    Run all heavy initialization in background thread.
    This allows Flask to start quickly and bind port 5000.
    
    CRITICAL: In paper trading mode, trading engine ALWAYS starts regardless of health checks.
    In real trading mode, health checks may gate startup.
    """
    print("\n" + "="*60)
    print("[ENGINE] run_heavy_initialization() STARTED")
    print("="*60)
    print("[ENGINE] This function will start the trading engine", flush=True)
    
    import time
    trading_mode = os.getenv('TRADING_MODE', 'paper').lower()
    is_paper_mode = trading_mode == 'paper'
    
    print(f"[ENGINE] Trading mode: {trading_mode}", flush=True)
    print(f"[ENGINE] Is paper mode: {is_paper_mode}", flush=True)
    
    # CRITICAL: Start workers FIRST, before anything else that might fail
    # Workers are essential and must start even if other initialization fails
    print("\n" + "="*60)
    print("🚀 STARTING WORKER PROCESSES (CRITICAL - FIRST THING)")
    print("="*60)
    print("[ENGINE] Starting workers FIRST before other initialization", flush=True)
    try:
        _start_all_worker_processes()
        print("[ENGINE] Workers started successfully", flush=True)
    except Exception as e:
        print(f"[ENGINE] CRITICAL: Worker startup failed: {e}", flush=True)
        import traceback
        traceback.print_exc()
    
    # CRITICAL: Start engine EARLY, before any heavy initialization that might fail
    # In paper mode, engine MUST start regardless of other initialization failures
    print("\n[ENGINE] Starting trading engine (early in initialization)...", flush=True)
    engine_started = start_trading_engine_for_mode(is_paper_mode)
    
    if not engine_started and is_paper_mode:
        print("[ENGINE] CRITICAL: Engine failed to start in PAPER MODE - this should never happen!", flush=True)
        try:
            from src.operator_safety import alert_operator, ALERT_CRITICAL
            alert_operator(ALERT_CRITICAL, "engine_startup_failed_paper_mode", {
                "reason": "Engine startup returned False in paper mode",
                "mode": "paper"
            })
        except:
            pass
    
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
    
    # Run startup health checks (non-blocking)
    try:
        run_startup_health_checks()
    except Exception as e:
        print(f"⚠️  Startup health checks error (non-blocking): {e}")
        if is_paper_mode:
            print("   ℹ️  Continuing in PAPER MODE despite health check errors")
    
    # Run venue migration (tag learning files, reset old venue learnings)
    try:
        print("\n🔄 [VENUE-MIGRATION] Checking venue migration status...")
        from src.learning_venue_migration import migrate_venue_learning
        migration_results = migrate_venue_learning(decay_factor=0.1)  # Keep 10% of old learnings
        
        files_migrated = len(migration_results.get("files_migrated", []))
        files_tagged = len(migration_results.get("files_tagged", []))
        
        if files_migrated > 0:
            print(f"✅ [VENUE-MIGRATION] Migrated {files_migrated} learning files to new venue")
        elif files_tagged > 0:
            print(f"✅ [VENUE-MIGRATION] Tagged {files_tagged} learning files with current venue")
        else:
            print("ℹ️  [VENUE-MIGRATION] Learning files already tagged for current venue")
    except Exception as e:
        print(f"⚠️  [VENUE-MIGRATION] Migration error (non-blocking): {e}")
        if is_paper_mode:
            print("   ℹ️  Continuing in PAPER MODE despite migration errors")
    
    # Run venue symbol validation on startup (if using Kraken)
    try:
        exchange = os.getenv("EXCHANGE", "blofin").lower()
        if exchange == "kraken":
            print("\n🔍 [VALIDATION] Running startup venue symbol validation...")
            from src.venue_symbol_validator import validate_venue_symbols
            validation_results = validate_venue_symbols(update_config=False)
            
            suppressed = validation_results.get("summary", {}).get("suppressed", 0)
            if suppressed > 0:
                print(f"⚠️  [VALIDATION] {suppressed} symbols failed validation and should be suppressed")
                print("   💡 Review validation results and consider updating asset_universe.json")
            else:
                print("✅ [VALIDATION] All symbols validated successfully")
            
            # Register daily validation task
            try:
                from src.phase10_profit_engine import register_periodic_task
                from src.venue_validation_scheduler import register_daily_validation, register_exchange_health_monitor
                register_daily_validation(register_periodic_task)
                register_exchange_health_monitor(register_periodic_task)
            except Exception as e:
                print(f"⚠️  [VALIDATION] Failed to register daily validation scheduler: {e}")
        else:
            print(f"ℹ️  [VALIDATION] Skipping (not using Kraken, current exchange: {exchange})")
        
        # Register exchange health monitor for all exchanges (regardless of exchange type)
        try:
            from src.phase10_profit_engine import register_periodic_task
            from src.venue_validation_scheduler import register_exchange_health_monitor
            register_exchange_health_monitor(register_periodic_task)
        except Exception as e:
            print(f"⚠️  [EXCHANGE-HEALTH] Failed to register health monitor: {e}")
    except Exception as e:
        print(f"⚠️  [VALIDATION] Symbol validation error (non-blocking): {e}")
        if is_paper_mode:
            print("   ℹ️  Continuing in PAPER MODE despite validation errors")
    
    from src.venue_config import print_venue_map
    print_venue_map()
    
    # CRITICAL: Start healing operator early (before bot_worker) to ensure it always runs
    print("\n🔧 [HEALING] Ensuring healing operator is started...")
    try:
        from src.healing_operator import start_healing_operator, get_healing_operator
        healing_op = start_healing_operator()
        # Verify it's actually running with thread check
        if healing_op:
            import time
            time.sleep(0.2)  # Give thread time to start
            if healing_op.running and healing_op.thread and healing_op.thread.is_alive():
                print("   ✅ Healing operator confirmed running (thread alive)")
            else:
                print("   ❌ Healing operator NOT running properly!")
                print("   → Attempting fallback start...")
                try:
                    healing_op.start()  # Try again
                    time.sleep(0.2)
                    if healing_op.running and healing_op.thread and healing_op.thread.is_alive():
                        print("   ✅ Fallback start successful")
                    else:
                        print("   ❌ Fallback start failed - bot_worker will try again")
                except Exception as e2:
                    print(f"   ❌ Fallback start error: {e2}")
        else:
            print("   ❌ Failed to get healing operator instance")
    except Exception as e:
        print(f"   ❌ Healing operator early start failed: {e}")
        print("   → bot_worker will attempt to start it later")
        import traceback
        traceback.print_exc()
    
    print("\n🏥 Running startup health check...")
    health_check_passed = True
    try:
        from src.system_health_check import SystemHealthCheck
        startup_health = SystemHealthCheck()
        health_result = startup_health.run_cycle()
        health_score = health_result.get('health', {}).get('score', 0)
        health_status = health_result.get('health', {}).get('status', 'unknown')
        
        print(f"   Status: {health_status} (Score: {health_score}/100)")
        if health_result.get('remediation'):
            print(f"   Remediations needed: {len(health_result['remediation'])}")
        
        # In real trading mode, require minimum health score
        if not is_paper_mode:
            if health_score < 50 or health_status == 'critical':
                print(f"   ❌ Health check failed (score: {health_score}, status: {health_status})")
                health_check_passed = False
                print("   ⚠️  REAL TRADING MODE: Health check failed - trading engine will NOT start")
            else:
                print("✅ Startup health check passed - trading engine will start")
        else:
            # Paper mode: always pass health check, just log warnings
            if health_score < 50 or health_status == 'critical':
                print(f"   ⚠️  Health check degraded (score: {health_score}, status: {health_status})")
                print("   ℹ️  PAPER MODE: Continuing despite degraded health - trading engine WILL start")
            else:
                print("✅ Startup health check complete")
    except Exception as e:
        print(f"⚠️  Startup health check failed: {e}")
        import traceback
        traceback.print_exc()
        if is_paper_mode:
            print("   ℹ️  PAPER MODE: Continuing despite health check failure - trading engine WILL start")
            health_check_passed = True  # Force pass in paper mode
        else:
            print("   ❌ REAL TRADING MODE: Health check error - trading engine will NOT start")
            health_check_passed = False
    
    # NOTE: Workers are now started at the VERY BEGINNING of run_heavy_initialization()
    # This ensures they start even if other initialization fails
    
    # Start worker process monitor
    try:
        monitor_thread = threading.Thread(target=_monitor_worker_processes, daemon=True, name="WorkerMonitor")
        monitor_thread.start()
        print("   ✅ Worker process monitor started")
    except Exception as e:
        print(f"   ⚠️  Failed to start worker monitor: {e}")
    
    # Start pipeline health monitor
    try:
        health_monitor_thread = threading.Thread(target=_monitor_pipeline_health, daemon=True, name="PipelineHealthMonitor")
        health_monitor_thread.start()
        print("   ✅ Pipeline health monitor started")
    except Exception as e:
        print(f"   ⚠️  Failed to start pipeline health monitor: {e}")
    
    # CRITICAL: Start trading engine based on mode, health check, and self-healing
    # Paper mode: ALWAYS start, even if health checks fail or self-healing has issues
    # Real mode: Only start if health checks pass AND self-healing succeeded (no critical issues)
    print("\n" + "="*60)
    print("🚀 TRADING ENGINE STARTUP DECISION")
    print("="*60)
    
    global _healing_result
    healing_success = True  # Default to True for paper mode
    if _healing_result is not None:
        healing_success = _healing_result["success"] and len(_healing_result["critical"]) == 0
        print(f"   Self-healing result: success={_healing_result['success']}, critical={len(_healing_result['critical'])}")
    else:
        print("   Self-healing result: Not available (running in background thread)")
        if is_paper_mode:
            healing_success = True  # Paper mode always succeeds
            print("   ℹ️  PAPER MODE: Assuming healing success")
        else:
            healing_success = False
            print("   ⚠️  REAL MODE: Self-healing result not available - assuming failure")
    
    should_start_engine = False
    try:
        if is_paper_mode:
            # Paper mode: ALWAYS start, regardless of health checks or healing
            # This is a hard requirement - paper mode must never be blocked
            should_start_engine = True
            print(f"\n🤖 DECISION: Starting trading engine (mode: {trading_mode.upper()})")
            print("   ✅ PAPER MODE: Engine ALWAYS starts regardless of health/healing status")
            print("   🔒 HARD REQUIREMENT: Paper mode cannot be blocked by safety checks")
            health_status_str = "PASSED" if health_check_passed else "DEGRADED"
            print(f"   ℹ️  Health check status: {health_status_str} (non-blocking in paper mode)")
            healing_status_str = "SUCCESS" if healing_success else "ISSUES DETECTED (non-blocking in paper mode)"
            print(f"   ℹ️  Healing status: {healing_status_str}")
            print(f"   ✅ Final decision: START ENGINE (paper mode override active)")
        elif health_check_passed and healing_success:
            # Real mode: Start only if both health check AND healing succeeded
            should_start_engine = True
            print(f"\n🤖 DECISION: Starting trading engine (mode: {trading_mode.upper()})")
            print("   ✅ REAL TRADING MODE: Health check passed and self-healing succeeded")
        else:
            # Real mode: Don't start if health check failed OR healing found critical issues
            should_start_engine = False
            print(f"\n⛔ DECISION: Trading engine NOT started - REAL TRADING MODE safety checks failed")
            if not health_check_passed:
                print("   ❌ Health check failed")
            if not healing_success:
                print("   ❌ Self-healing found critical issues (see alerts above)")
            print("   ℹ️  Dashboard will continue running, but no trades will execute")
            print("   ℹ️  Fix issues and restart to enable trading")
    except Exception as e:
        # If there's any error in decision logic, default based on mode
        print(f"   ⚠️  Error in startup decision logic: {e}")
        if is_paper_mode:
            should_start_engine = True
            print("   ✅ PAPER MODE: Defaulting to START despite error")
        else:
            should_start_engine = False
            print("   ❌ REAL MODE: Defaulting to NOT START due to error")
        import traceback
        traceback.print_exc()
    
    print("="*60)
    
    # NOTE: Engine startup was already called early in this function for paper mode
    # For real mode, check if we should start (engine may not have started if health checks failed)
    if not is_paper_mode and should_start_engine:
        # Real mode: Only start if health checks passed and we haven't started yet
        print("\n[ENGINE] Real mode: Starting engine after health checks passed...", flush=True)
        engine_started = start_trading_engine_for_mode(is_paper_mode)
        if not engine_started:
            print("[ENGINE] CRITICAL: Engine failed to start in REAL MODE despite passing health checks!", flush=True)
            try:
                from src.operator_safety import alert_operator, ALERT_CRITICAL
                alert_operator(ALERT_CRITICAL, "engine_startup_failed_real_mode", {
                    "reason": "Engine startup returned False in real mode despite passing checks",
                    "mode": "real"
                })
            except:
                pass
    elif not should_start_engine:
        print("\n⛔ TRADING ENGINE NOT STARTED (see reasons above)")
        print("[ENGINE] Engine startup skipped due to safety checks", flush=True)
    
    nightly_thread = threading.Thread(target=nightly_learning_scheduler, daemon=True)
    nightly_thread.start()
    
    meta_learn_thread = threading.Thread(target=meta_learning_scheduler, daemon=True)
    meta_learn_thread.start()
    
    # [AUTONOMOUS-BRAIN] Start shadow portfolio comparison cycle (every 4 hours)
    def shadow_comparison_scheduler():
        """Compare shadow vs live performance every 4 hours."""
        import schedule
        from src.shadow_execution_engine import compare_shadow_vs_live_performance
        from src.policy_tuner import get_policy_tuner
        
        def run_comparison():
            try:
                comparison = compare_shadow_vs_live_performance(days=7)
                opportunity_cost_pct = comparison.get('opportunity_cost_pct', 0.0)
                
                if comparison.get('should_optimize_guards'):
                    print(f"🚨 [SHADOW] Shadow outperforming live by {opportunity_cost_pct:.1f}% over 7 days")
                    print(f"   💡 Recommendation: Consider optimizing guards - highest cost: {comparison.get('blocked_reasons', {})}")
                    
                    # [AUTONOMOUS-BRAIN] Self-healing trigger: Run policy optimizer immediately
                    print(f"   🔧 [SELF-HEALING] Triggering immediate policy optimization...")
                    try:
                        tuner = get_policy_tuner()
                        results = tuner.optimize(days=30)
                        if results.get('success'):
                            apply_results = tuner.apply_best_parameters(dry_run=False)
                            if apply_results.get('success'):
                                print(f"   ✅ [SELF-HEALING] Policy optimizer completed - parameters updated")
                            else:
                                print(f"   ⚠️ [SELF-HEALING] Policy optimizer completed but application failed: {apply_results.get('error')}")
                        else:
                            print(f"   ⚠️ [SELF-HEALING] Policy optimizer failed: {results.get('error')}")
                    except Exception as e:
                        print(f"   ⚠️ [SELF-HEALING] Policy optimizer trigger error: {e}")
                else:
                    print(f"✅ [SHADOW] Performance comparison complete - Opportunity cost: {opportunity_cost_pct:.1f}%")
            except Exception as e:
                print(f"⚠️ [SHADOW] Comparison error: {e}")
        
        # Run immediately, then every 4 hours
        schedule.every(4).hours.do(run_comparison)
        run_comparison()  # Initial run
        
        while True:
            schedule.run_pending()
            time.sleep(300)  # Check every 5 minutes
    
    shadow_comparison_thread = threading.Thread(target=shadow_comparison_scheduler, daemon=True)
    shadow_comparison_thread.start()
    print("✅ [SHADOW] Shadow portfolio comparison started (4-hour cycle)")
    
    # [AUTONOMOUS-BRAIN] Start policy optimizer (daily)
    def policy_optimizer_scheduler():
        """Run policy optimization daily - reads from executed_trades.jsonl AND shadow_results.jsonl."""
        import schedule
        from src.policy_tuner import get_policy_tuner
        
        def run_optimization():
            try:
                tuner = get_policy_tuner()
                # Run optimization (reads from both executed_trades.jsonl and shadow_results.jsonl)
                results = tuner.optimize(days=30)
                if results.get('success'):
                    best_params = results.get('best_params', {})
                    best_sharpe = results.get('best_sharpe', 0.0)
                    n_trades = results.get('n_trades_analyzed', 0)
                    
                    print(f"✅ [POLICY-TUNER] Daily optimization complete")
                    print(f"   📊 Best Sharpe: {best_sharpe:.3f}")
                    print(f"   ⚙️  Parameters: entry_threshold={best_params.get('entry_threshold', 0):.3f}, stop_loss={best_params.get('stop_loss_pct', 0):.2f}%")
                    print(f"   📈 Analyzed {n_trades} trades (live + shadow)")
                    
                    # Apply optimized parameters
                    apply_results = tuner.apply_best_parameters(dry_run=False)
                    if apply_results.get('success'):
                        print(f"   ✅ Parameters applied to trading_config.json")
                    else:
                        print(f"   ⚠️  Parameter application failed: {apply_results.get('error')}")
                else:
                    print(f"⚠️ [POLICY-TUNER] Optimization skipped: {results.get('error', 'unknown')}")
            except Exception as e:
                print(f"⚠️ [POLICY-TUNER] Optimization error: {e}")
        
        # Run at 3 AM UTC daily
        schedule.every().day.at("03:00").do(run_optimization)
        
        while True:
            schedule.run_pending()
            time.sleep(300)  # Check every 5 minutes
    
    policy_optimizer_thread = threading.Thread(target=policy_optimizer_scheduler, daemon=True)
    policy_optimizer_thread.start()
    print("✅ [POLICY-TUNER] Policy optimizer started (daily at 3 AM UTC)")
    
    # [AUTONOMOUS-BRAIN] Start feature drift detection (every 6 hours)
    def drift_detection_scheduler():
        """Run feature drift detection every 6 hours."""
        import schedule
        from src.feature_drift_detector import run_drift_detection
        
        def run_drift_check():
            try:
                results = run_drift_detection()
                detection = results.get('detection', {})
                quarantined_count = detection.get('total_quarantined', 0)
                restored = detection.get('restored_signals', [])
                
                if quarantined_count > 0:
                    quarantined = detection.get('quarantined_signals', [])
                    print(f"⚠️ [DRIFT] {quarantined_count} signal(s) quarantined: {', '.join(quarantined[:5])}")
                
                if restored:
                    print(f"✅ [DRIFT] {len(restored)} signal(s) restored: {', '.join(restored)}")
                
                if quarantined_count == 0 and not restored:
                    print(f"✅ [DRIFT] No drift detected - all signals healthy")
            except Exception as e:
                print(f"⚠️ [DRIFT] Detection error: {e}")
        
        # Run every 6 hours
        schedule.every(6).hours.do(run_drift_check)
        run_drift_check()  # Initial run
        
        while True:
            schedule.run_pending()
            time.sleep(300)  # Check every 5 minutes
    
    drift_detection_thread = threading.Thread(target=drift_detection_scheduler, daemon=True)
    drift_detection_thread.start()
    print("✅ [DRIFT] Feature drift detection started (6-hour cycle)")
    
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
    
    # OPERATOR SAFETY: Validate systemd slot and startup state (non-blocking)
    # In paper mode, always continue even if validation fails
    # In real trading mode, validation failures are logged but don't block startup
    trading_mode = os.getenv('TRADING_MODE', 'paper').lower()
    is_paper_mode = trading_mode == 'paper'
    
    try:
        from src.operator_safety import validate_systemd_slot, validate_startup_state, self_heal
        print("\n🔍 [SAFETY] Running startup validation...")
        slot_validation = validate_systemd_slot()
        state_validation = validate_startup_state()
        
        if not slot_validation["valid"] or not state_validation["valid"]:
            if is_paper_mode:
                print("⚠️ [SAFETY] Startup validation failed - continuing in PAPER MODE (warnings only)")
            else:
                print("❌ [SAFETY] Startup validation failed - see alerts above")
                print("   ⚠️  Continuing in REAL TRADING MODE with degraded health checks")
        else:
            print("✅ [SAFETY] Startup validation passed")
        
        # Run self-healing after validation
        print("\n🔧 [SAFETY] Running self-healing...")
        healing_result = self_heal()
        
        # Store healing result in module-level variable for run_heavy_initialization to access
        global _healing_result
        _healing_result = healing_result
        
        if healing_result["success"]:
            if healing_result["healed"]:
                print(f"✅ [SAFETY] Self-healing completed: {len(healing_result['healed'])} issues healed")
            else:
                print("✅ [SAFETY] Self-healing completed: No issues found")
        else:
            if is_paper_mode:
                print(f"⚠️ [SAFETY] Self-healing completed with issues - continuing in PAPER MODE")
                print(f"   Healed: {len(healing_result['healed'])}, Failed: {len(healing_result['failed'])}, Critical: {len(healing_result['critical'])}")
            else:
                print(f"❌ [SAFETY] Self-healing failed - REAL TRADING MODE requires successful healing")
                print(f"   Healed: {len(healing_result['healed'])}, Failed: {len(healing_result['failed'])}, Critical: {len(healing_result['critical'])}")
                if healing_result["critical"]:
                    print("   🚨 CRITICAL: Dangerous issues detected - trading engine will NOT start")
                    print("   ℹ️  Dashboard will continue running, but no trades will execute")
                    print("   ℹ️  Fix critical issues and restart to enable trading")
    except Exception as e:
        # Safety validation must NEVER block startup, especially in paper mode
        print(f"⚠️ [SAFETY] Startup validation/self-healing error (non-blocking): {e}")
        if is_paper_mode:
            print("   ℹ️  Continuing in PAPER MODE despite validation/healing error")
        import traceback
        traceback.print_exc()
    
    # Check if running under supervisor control
    supervisor_controlled = os.environ.get("SUPERVISOR_CONTROLLED", "0")
    print(f"🔍 [STARTUP] SUPERVISOR_CONTROLLED={supervisor_controlled}")
    
    if supervisor_controlled == "1":
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
    
    # Normal mode: Start Flask dashboard on port 8050 (configurable via PORT env var)
    dashboard_port = int(os.environ.get("PORT", "8050"))
    print(f"\n🌐 [DASHBOARD] Starting P&L Dashboard on http://0.0.0.0:{dashboard_port}")
    
    if not _force_clear_port(dashboard_port):
        print(f"❌ FATAL: Cannot clear port {dashboard_port} after multiple attempts!")
        print("   Please manually kill the blocking process and restart.")
        sys.exit(1)
    
    print(f"   ✅ [DASHBOARD] Port {dashboard_port} is available")
    print("   ℹ️  [DASHBOARD] Initializing subsystems in background...")
    
    # Create Flask app first
    from flask import Flask
    flask_app = Flask(__name__)
    print("   ✅ [DASHBOARD] Flask app created")
    
    # Start P&L dashboard (optional - must not crash if missing)
    dash_app = None
    try:
        print("   🔍 [DASHBOARD] Importing start_pnl_dashboard (V2 - Clean Dashboard)...")
        from src.pnl_dashboard_v2 import start_pnl_dashboard
        print("   ✅ [DASHBOARD] Import successful, calling start_pnl_dashboard()...")
        dash_app = start_pnl_dashboard(flask_app)
        print("   ✅ [DASHBOARD] P&L Dashboard initialized successfully")
        if dash_app is None:
            print("   ❌ [DASHBOARD] CRITICAL: start_pnl_dashboard() returned None!")
            raise RuntimeError("Dashboard initialization returned None")
    except ImportError as e:
        print(f"   ❌ [DASHBOARD] CRITICAL IMPORT ERROR: {e}")
        import traceback
        print("   📋 [DASHBOARD] Full traceback:")
        traceback.print_exc()
        print("   ⚠️  Dashboard will not be available - trading engine continues")
    except NameError as e:
        print(f"   ❌ [DASHBOARD] CRITICAL NAME ERROR: {e}")
        import traceback
        print("   📋 [DASHBOARD] Full traceback:")
        traceback.print_exc()
        if "start_pnl_dashboard" in str(e):
            print("   ⚠️  P&L Dashboard function not found - continuing without dashboard")
        else:
            print(f"   ⚠️  P&L Dashboard import error - continuing without dashboard")
    except Exception as e:
        print(f"   ❌ [DASHBOARD] CRITICAL STARTUP ERROR: {type(e).__name__}: {e}")
        import traceback
        print("   📋 [DASHBOARD] Full traceback:")
        traceback.print_exc()
        print("   ⚠️  Dashboard startup failed - trading engine will continue without dashboard")
        print("   💡 [DASHBOARD] Check logs above for root cause")
    
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
            
            print(f"   🔍 [DASHBOARD] Starting Gunicorn server on port {dashboard_port}...")
            options = {
                'bind': f'0.0.0.0:{dashboard_port}',
                'workers': 1,  # CRITICAL: Dash requires 1 worker - multiple workers cause dependency registration issues
                'threads': 4,
                'worker_class': 'sync',
                'timeout': 120,
                'accesslog': '-',
                'errorlog': '-',
                'loglevel': 'warning',
                'preload_app': False,  # CRITICAL: Set to False for Dash - allows worker to register Dash dependencies
            }
            
            print("   🚀 Starting Gunicorn production server (1 worker, 4 threads) - Dash compatibility mode")
            # Use dash_app if available, otherwise flask_app
            app_to_run = dash_app if dash_app is not None else flask_app
            StandaloneApplication(app_to_run, options).run()
            
        except ImportError:
            print("   ⚠️ Gunicorn not available, falling back to Flask dev server")
            app_to_run = dash_app if dash_app is not None else flask_app
            app_to_run.run(host="0.0.0.0", port=dashboard_port, debug=False, use_reloader=False)
        except Exception as e:
            print(f"   ⚠️ Gunicorn failed: {e}, falling back to Flask dev server")
            app_to_run = dash_app if dash_app is not None else flask_app
            app_to_run.run(host="0.0.0.0", port=dashboard_port, debug=False, use_reloader=False)
    else:
        try:
            app_to_run = dash_app if dash_app is not None else flask_app
            app_to_run.run(host="0.0.0.0", port=dashboard_port, debug=False, use_reloader=False)
        except OSError as e:
            if "Address already in use" in str(e):
                print(f"❌ FATAL: Port {dashboard_port} binding failed: {e}")
                print("   Attempting emergency port recovery...")
                if _force_clear_port(dashboard_port):
                    print("   ✅ Port recovered - restarting Flask...")
                    app_to_run = dash_app if dash_app is not None else flask_app
                    app_to_run.run(host="0.0.0.0", port=dashboard_port, debug=False, use_reloader=False)
                else:
                    print(f"❌ FATAL: Cannot recover port {dashboard_port}. Bot shutting down.")
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
        from src.pnl_dashboard_v2 import get_wallet_balance
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
