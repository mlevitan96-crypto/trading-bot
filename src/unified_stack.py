"""
Unified Institutional Stack — Phases 9.3 through 10.18
One-boot orchestration, consolidated state, single audit/event pipeline.

This module wires all integrated phases into a single cohesive engine.
"""

import time
import os
import json
from typing import Dict, List, Optional

# Import all phase modules
from src.phase93_venue_governance import (
    is_venue_enabled,
    phase93_entry_gate,
    phase93_size_modifier_futures,
    phase93_governance_tick,
    phase93_evaluate_spot_unfreeze
)
from src.phase94_recovery_scaling import phase94_recovery_scaling_tick
from src.phase10_profit_engine import (
    phase10_signal_pipeline,
    freeze_ramps_global,
    block_new_entries_global
)
from src.phase101_allocator import (
    phase101_allocation,
    phase101_update_attribution
)
from src.phase102_futures_optimizer import (
    phase102_periodic_rank,
    phase102_allocation,
    phase102_shadow_tick
)
from src.phase10x_combined import (
    phase103_pre_execution,
    phase104_place_order,
    phase105_experiments_tick,
    phase105_on_trade_close,
    phase105_hygiene_tick
)
from src.phase106_calibration import (
    phase106_on_exec_report,
    phase106_on_trade_close,
    phase106_scenario_tick
)
from src.phase107_109 import (
    phase107_109_pre_sizing,
    phase107_on_trade_close,
    phase108_governance_tick,
    phase109_recovery_tick
)
from src.phase1010_1012 import (
    phase1010_pre_bias,
    phase1011_arbitrage_tick,
    phase1012_dashboard_tick
)
from src.phase1013_1015 import (
    phase1013_on_trade_close,
    phase1014_pre_allocation,
    phase1015_audit_tick
)
from src.phase1016_1018 import (
    phase1016_on_trade_close,
    phase1016_route_tick,
    phase1016_apply_bucket_weight,
    phase1017_hedge_tick,
    phase1018_governance_tick
)

# ======================================================================================
# Unified Persistence
# ======================================================================================

UNIFIED_STATE_PATH = "logs/unified_state.json"
UNIFIED_EVENTS_PATH = "logs/unified_events.jsonl"

STATE = {
    "last_boot_ts": 0,
    "ticks": {},
    "errors": []
}

def _persist_state():
    """Save unified state"""
    os.makedirs(os.path.dirname(UNIFIED_STATE_PATH), exist_ok=True)
    with open(UNIFIED_STATE_PATH, "w") as f:
        json.dump(STATE, f, indent=2)

def _append_event(event: str, payload: dict):
    """Log event to unified event stream"""
    os.makedirs(os.path.dirname(UNIFIED_EVENTS_PATH), exist_ok=True)
    with open(UNIFIED_EVENTS_PATH, "a") as f:
        f.write(json.dumps({
            "ts": int(time.time()),
            "event": event,
            "payload": payload
        }) + "\n")

# ======================================================================================
# Unified Pipeline Wrappers
# ======================================================================================

def unified_pre_entry(signal: Dict) -> bool:
    """
    Router-level and gate-level venue enforcement + profit gates + market intelligence.
    Returns True if signal should proceed to sizing.
    
    IMPORTANT: Logs ALL signals to signal universe for counterfactual learning.
    """
    try:
        symbol = signal.get("symbol", "")
        side = signal.get("side", "")
        venue = signal.get("venue", "futures")
        
        intelligence_context = {
            "ofi": signal.get("ofi"),
            "ofi_raw": signal.get("ofi_raw", signal.get("ofi")),
            "ensemble": signal.get("ensemble"),
            "mtf_confidence": signal.get("mtf_confidence"),
            "regime": signal.get("regime"),
            "volatility": signal.get("volatility"),
            "market_intel": signal.get("market_intel", {}),
            "fear_greed": signal.get("fear_greed"),
            "taker_ratio": signal.get("taker_ratio"),
            "liquidation_bias": signal.get("liquidation_bias"),
        }
        signal_context = {
            "strategy": signal.get("strategy"),
            "venue": venue,
        }
        entry_price = signal.get("price") or signal.get("entry_price")
        
        def _log_signal_blocked(gate: str, reason: str):
            try:
                from src.signal_universe_tracker import log_signal
                log_signal(
                    symbol=symbol,
                    side=side,
                    disposition="BLOCKED",
                    intelligence=intelligence_context,
                    block_reason=reason,
                    block_gate=gate,
                    entry_price=entry_price,
                    signal_context=signal_context
                )
            except:
                pass
        
        # Phase 9.3: Venue router check
        if not is_venue_enabled(venue):
            _append_event("unified_pre_entry_blocked", {"signal": signal, "phase": "9.3_router"})
            _log_signal_blocked("venue_router", f"Venue {venue} disabled")
            return False
        
        # Phase 9.3: Entry gate
        if not phase93_entry_gate(signal):
            _append_event("unified_pre_entry_blocked", {"signal": signal, "phase": "9.3_gate"})
            _log_signal_blocked("phase93_gate", "Entry gate rejected")
            return False
        
        # Phase 10.0: Profit gates
        if not phase10_signal_pipeline(signal):
            _append_event("unified_pre_entry_blocked", {"signal": signal, "phase": "10.0_profit"})
            _log_signal_blocked("profit_gate", "Profit gate rejected")
            return False
        
        # CoinGlass Market Intelligence Gate
        try:
            from src.intelligence_gate import intelligence_gate
            allowed, reason, sizing_mult = intelligence_gate(signal)
            if not allowed:
                _append_event("unified_pre_entry_blocked", {"signal": signal, "phase": "intel_gate", "reason": reason})
                _log_signal_blocked("intel_gate", reason)
                print(f"   🔴 [INTEL-GATE] Blocked {symbol}: {reason}")
                return False
            if sizing_mult != 1.0:
                signal["intel_sizing_mult"] = sizing_mult
                signal["intel_reason"] = reason
        except Exception as e:
            pass
        
        # LEARNED INTELLIGENCE RULES - Apply rules from closed-loop learning
        try:
            from src.intelligence_learning_loop import apply_learned_rules
            learned = apply_learned_rules(signal)
            if not learned.get("allowed", True):
                _append_event("unified_pre_entry_blocked", {
                    "signal": signal, 
                    "phase": "learned_rules", 
                    "reason": learned.get("reason"),
                    "rule_id": learned.get("rule_id")
                })
                _log_signal_blocked("learned_rules", learned.get("reason", "Rule rejected"))
                print(f"   🔴 [LEARNED-RULES] Blocked {symbol}: {learned.get('reason')}")
                return False
            
            # Apply learned sizing multiplier
            if learned.get("sizing_multiplier", 1.0) != 1.0:
                current_mult = signal.get("learned_sizing_mult", 1.0)
                signal["learned_sizing_mult"] = current_mult * learned["sizing_multiplier"]
                signal["learned_rule_id"] = learned.get("rule_id")
                if learned.get("warnings"):
                    print(f"   ⚠️ [LEARNED-RULES] {symbol}: {', '.join(learned['warnings'][:2])}")
        except ImportError:
            pass
        except Exception as e:
            pass
        
        # Signal passed all gates - log as will be executed
        try:
            from src.signal_universe_tracker import log_signal
            log_signal(
                symbol=symbol,
                side=side,
                disposition="EXECUTED",
                intelligence=intelligence_context,
                entry_price=entry_price,
                signal_context=signal_context
            )
        except:
            pass
        
        return True
    except Exception as e:
        STATE["errors"].append({"stage": "pre_entry", "err": str(e)})
        _append_event("unified_error", {"stage": "pre_entry", "err": str(e)})
        return False

def unified_pre_size(signal: Dict) -> float:
    """
    Sizing pipeline:
    - 10.1 Attribution-weighted base
    - 10.2 Futures optimizer multiplier (futures only)
    - 10.3 Adaptive risk modulation
    - 10.7–10.9 Predictive pre-bias + caps
    - 10.10 Collaborative intelligence bias
    - 10.14 Risk parity + correlation-aware caps
    - 10.16 Meta-bucket weighting (global routing)
    Returns final size (USD).
    """
    try:
        venue = signal.get("venue", "futures")
        symbol = signal.get("symbol")
        
        # 10.1 Attribution-weighted base
        base_attr = phase101_allocation(signal)
        
        # 9.3 Futures size modifier (losing streak throttle for futures)
        if venue == "futures":
            strategy = signal.get("strategy", "")
            futures_modifier = phase93_size_modifier_futures(base_attr, strategy)
            size_93 = base_attr * futures_modifier
        else:
            size_93 = base_attr
        
        # 10.2 Futures optimizer (futures only)
        if venue == "futures":
            size_102 = phase102_allocation({**signal, "planned_size_usd": size_93})
        else:
            size_102 = size_93
        
        # 10.3 Adaptive risk (stops/trailing + size adjustments)
        size_103 = phase103_pre_execution({**signal, "planned_size_usd": size_102})
        if size_103 is None or size_103 <= 0:
            size_103 = size_102
        
        # 10.7–10.9 Predictive + caps
        size_107_109 = phase107_109_pre_sizing({**signal, "planned_size_usd": size_103})
        if size_107_109 is None or size_107_109 <= 0:
            size_107_109 = size_103
        
        # 10.10 Collaborative intelligence (external feeds)
        size_1010 = phase1010_pre_bias({**signal, "planned_size_usd": size_107_109})
        if size_1010 is None or size_1010 <= 0:
            size_1010 = size_107_109
        
        # 10.14 Risk parity + correlation-aware caps
        size_1014 = phase1014_pre_allocation({**signal, "planned_size_usd": size_1010})
        
        # 10.16 Meta-bucket weighting (global routing)
        size_1016 = phase1016_apply_bucket_weight({**signal, "planned_size_usd": size_1014})
        
        # CoinGlass Intelligence sizing modulation
        intel_mult = signal.get("intel_sizing_mult", 1.0)
        size_intel = size_1016 * intel_mult if intel_mult else size_1016
        
        # LEARNED RULES sizing modulation (from closed-loop learning)
        learned_mult = signal.get("learned_sizing_mult", 1.0)
        size_learned = size_intel * learned_mult if learned_mult else size_intel
        
        if learned_mult != 1.0:
            rule_id = signal.get("learned_rule_id", "")
            print(f"   📚 [LEARNED-SIZING] {symbol}: {learned_mult:.2f}x from rule {rule_id}")
        
        # COIN PROFILE ENGINE - Apply coin-specific volatility adjustments
        try:
            from src.coin_profile_engine import get_size_multiplier, get_volatility_class
            coin_mult = get_size_multiplier(symbol)
            size_profiled = size_learned * coin_mult
            if coin_mult != 1.0:
                vol_class = get_volatility_class(symbol)
                print(f"   🎯 [COIN-PROFILE] {symbol}: {coin_mult:.2f}x ({vol_class} volatility)")
        except Exception:
            size_profiled = size_learned
        
        # Final size
        final_size = max(0, size_profiled)
        
        _append_event("unified_pre_size", {
            "symbol": symbol,
            "venue": venue,
            "sizes": {
                "10.1": base_attr,
                "9.3": size_93,
                "10.2": size_102,
                "10.3": size_103,
                "10.7-9": size_107_109,
                "10.10": size_1010,
                "10.14": size_1014,
                "10.16": size_1016,
                "intel": size_intel,
                "intel_mult": intel_mult,
                "final": final_size
            }
        })
        return final_size
    except Exception as e:
        STATE["errors"].append({"stage": "pre_size", "err": str(e)})
        _append_event("unified_error", {"stage": "pre_size", "err": str(e)})
        # Fallback to base size
        try:
            from src.phase101_allocator import phase101_allocation
            return max(0, phase101_allocation(signal))
        except Exception:
            return 0.0

def unified_place_entry(signal: Dict, side: str) -> Optional[Dict]:
    """
    Execution path:
    - Venue executor guard (9.3)
    - Smart order routing (10.4)
    Returns order dict or None if blocked.
    """
    try:
        symbol = signal.get("symbol")
        venue = signal.get("venue", "futures")
        
        # Phase 9.3: Executor guard (venue enabled check)
        if not is_venue_enabled(venue):
            _append_event("unified_place_blocked", {"signal": signal, "phase": "9.3_executor"})
            freeze_ramps_global()  # Alert on venue block
            return None
        
        # Phase 10.4: Efficient execution
        order = phase104_place_order(signal, side)
        
        if order:
            _append_event("unified_place_success", {"signal": signal, "order": order})
        
        return order
    except Exception as e:
        STATE["errors"].append({"stage": "place_entry", "err": str(e)})
        _append_event("unified_error", {"stage": "place_entry", "err": str(e)})
        return None

def unified_on_trade_close(trade: Dict):
    """
    Post-trade updates:
    - 10.1 Attribution
    - 10.5 Experiment demotion checks
    - 10.6 Calibration snapshots
    - 10.7 Prediction calibration
    - 10.13 Expectancy ledger
    - 10.16 Meta-bucket aggregation
    """
    try:
        # 10.1 Attribution
        phase101_update_attribution(
            trade.get("symbol"),
            trade.get("strategy"),
            trade.get("venue", "futures"),
            float(trade.get("pnl_usd", 0.0))
        )
        
        # 10.5 Experiments
        phase105_on_trade_close(trade)
        
        # 10.6 Calibration
        phase106_on_trade_close(trade)
        
        # 10.7 Prediction calibration
        phase107_on_trade_close(trade)
        
        # 10.13 Expectancy ledger
        phase1013_on_trade_close(trade)
        
        # 10.16 Meta-bucket aggregation
        phase1016_on_trade_close(trade)
        
        # [AUTONOMOUS-BRAIN] Log feature performance for drift detection
        try:
            from src.feature_drift_detector import get_drift_monitor
            drift_monitor = get_drift_monitor()
            
            # Extract signal components from trade metadata
            signal_context = trade.get('signal_context', {})
            signal_id = trade.get('signal_id')
            pnl_pct = trade.get('roi_pct', trade.get('pnl_pct', 0.0))
            exit_price = trade.get('exit_price', trade.get('close_price', 0))
            was_profitable = pnl_pct > 0
            
            # Log performance for each signal component
            if signal_context:
                # Map common signal names to drift detector component names
                signal_components = {
                    'ofi': 'ofi_momentum',
                    'ensemble': 'ensemble',
                    'mtf': 'mtf_alignment',
                    'regime': 'regime',
                    'volatility': 'volatility_skew'
                }
                
                for key, signal_name in signal_components.items():
                    if key in signal_context:
                        drift_monitor.log_feature_performance(signal_name, pnl_pct, was_profitable)
        except Exception as e:
            pass  # Non-blocking - drift logging is optional
        
        # [AUTONOMOUS-BRAIN] Close shadow position if it exists
        try:
            from src.shadow_execution_engine import get_shadow_engine
            shadow_engine = get_shadow_engine()
            signal_id = trade.get('signal_id')
            exit_price = trade.get('exit_price', trade.get('close_price', 0))
            
            if signal_id and exit_price > 0:
                shadow_engine.close_position(signal_id, exit_price)
        except Exception as e:
            pass  # Non-blocking - shadow closing is optional
        
        _append_event("unified_trade_close", {"trade": trade})
    except Exception as e:
        STATE["errors"].append({"stage": "on_trade_close", "err": str(e)})
        _append_event("unified_error", {"stage": "on_trade_close", "err": str(e)})

def unified_on_exec_report(exec: Dict):
    """
    Execution report ingestion:
    - 10.6 Calibration auto-tuning
    """
    try:
        phase106_on_exec_report(exec)
        _append_event("unified_exec_report", {"exec": exec})
    except Exception as e:
        STATE["errors"].append({"stage": "on_exec_report", "err": str(e)})
        _append_event("unified_error", {"stage": "on_exec_report", "err": str(e)})

# ======================================================================================
# Unified Periodic Ticks
# ======================================================================================

def _tick_wrapper(name: str, fn, *args, **kwargs):
    """Wrapper for periodic tasks with error handling"""
    try:
        fn(*args, **kwargs)
        STATE["ticks"][name] = int(time.time())
        _persist_state()
    except Exception as e:
        STATE["errors"].append({"stage": f"tick:{name}", "err": str(e)})
        _append_event("unified_error", {"stage": f"tick:{name}", "err": str(e)})

def tick_phase93_audit():
    """Phase 9.3: Venue enforcement audit"""
    _tick_wrapper("phase93_audit", phase93_governance_tick)

def tick_phase93_spot_unfreeze():
    """Phase 9.3: Evaluate spot unfreeze"""
    _tick_wrapper("phase93_spot_unfreeze", phase93_evaluate_spot_unfreeze)

def tick_phase94_capital():
    """Phase 9.4: Capital gate"""
    _tick_wrapper("phase94_capital", phase94_recovery_scaling_tick)

def tick_phase102_rank():
    """Phase 10.2: Ranking"""
    _tick_wrapper("phase102_rank", phase102_periodic_rank)

def tick_phase102_shadow():
    """Phase 10.2: Shadow trading"""
    def shadow_exec():
        from src.phase102_futures_optimizer import run_shadow_trade
        phase102_shadow_tick(run_shadow_trade)
    _tick_wrapper("phase102_shadow", shadow_exec)

def tick_phase105_experiments():
    """Phase 10.5: Experiments"""
    def exp_exec():
        from src.phase102_futures_optimizer import run_shadow_trade
        phase105_experiments_tick(run_shadow_trade)
    _tick_wrapper("phase105_experiments", exp_exec)

def tick_phase105_hygiene():
    """Phase 10.5: Hygiene checks"""
    _tick_wrapper("phase105_hygiene", phase105_hygiene_tick)

def tick_phase106_scenarios():
    """Phase 10.6: Calibration scenarios"""
    _tick_wrapper("phase106_scenarios", phase106_scenario_tick)

def tick_phase108_governance():
    """Phase 10.8: Capital governance"""
    _tick_wrapper("phase108_governance", phase108_governance_tick)

def tick_phase109_recovery():
    """Phase 10.9: Autonomous recovery"""
    def recovery_exec():
        from src.data_registry import DataRegistry as DR
        SYMBOLS = DR.get_enabled_symbols()
        phase109_recovery_tick(SYMBOLS)
    _tick_wrapper("phase109_recovery", recovery_exec)

def tick_phase1011_arbitrage():
    """Phase 10.11: Cross-venue arbitrage"""
    _tick_wrapper("phase1011_arbitrage", phase1011_arbitrage_tick)

def tick_phase1012_dashboard():
    """Phase 10.12: Dashboard updates"""
    _tick_wrapper("phase1012_dashboard", phase1012_dashboard_tick)

def tick_phase1015_audit():
    """Phase 10.15: Degradation audit"""
    _tick_wrapper("phase1015_audit", phase1015_audit_tick)

def tick_phase1016_route():
    """Phase 10.16: Meta-expectancy routing"""
    _tick_wrapper("phase1016_route", phase1016_route_tick)

def tick_phase1017_hedge():
    """Phase 10.17: Correlation hedging"""
    _tick_wrapper("phase1017_hedge", phase1017_hedge_tick)

def tick_phase1018_governance():
    """Phase 10.18: Autonomous governance"""
    _tick_wrapper("phase1018_governance", phase1018_governance_tick)

# ======================================================================================
# Bootstrap
# ======================================================================================

def start_unified_stack():
    """Initialize unified orchestration system"""
    print("🌐 Starting Unified Institutional Stack (Phases 9.3-10.18)...")
    
    STATE["last_boot_ts"] = int(time.time())
    _persist_state()
    
    # Register periodic tasks
    from src.phase10_profit_engine import register_periodic_task
    
    # Phase 9.3-9.4: Venue & Capital
    register_periodic_task(tick_phase93_audit, interval_sec=600)         # 10m
    register_periodic_task(tick_phase93_spot_unfreeze, interval_sec=600)  # 10m
    register_periodic_task(tick_phase94_capital, interval_sec=300)       # 5m
    
    # Phase 10.2: Futures Optimizer
    register_periodic_task(tick_phase102_rank, interval_sec=300)          # 5m
    register_periodic_task(tick_phase102_shadow, interval_sec=600)        # 10m
    
    # Phase 10.5: Experiments & Hygiene
    register_periodic_task(tick_phase105_experiments, interval_sec=600)   # 10m
    register_periodic_task(tick_phase105_hygiene, interval_sec=900)       # 15m
    
    # Phase 10.6: Calibration
    register_periodic_task(tick_phase106_scenarios, interval_sec=900)     # 15m
    
    # Phase 10.8-10.9: Governance & Recovery
    register_periodic_task(tick_phase108_governance, interval_sec=300)    # 5m
    register_periodic_task(tick_phase109_recovery, interval_sec=300)      # 5m
    
    # Phase 10.11-10.12: Arbitrage & Dashboard
    register_periodic_task(tick_phase1011_arbitrage, interval_sec=300)    # 5m
    register_periodic_task(tick_phase1012_dashboard, interval_sec=300)    # 5m
    
    # Phase 10.15: Degradation Audit
    register_periodic_task(tick_phase1015_audit, interval_sec=600)        # 10m
    
    # Phase 10.16-10.18: Meta Router + Hedger + Governance
    register_periodic_task(tick_phase1016_route, interval_sec=300)        # 5m
    register_periodic_task(tick_phase1017_hedge, interval_sec=300)        # 5m
    register_periodic_task(tick_phase1018_governance, interval_sec=300)   # 5m
    
    # Net P&L Enforcement (Fee-Aware Intelligence)
    from src.net_pnl_enforcement import register_fee_enforcement
    register_fee_enforcement(register_periodic_task)                       # 10m
    
    _append_event("unified_stack_started", {
        "boot_ts": STATE["last_boot_ts"],
        "cadences": {
            "venue_audit": 600,
            "capital": 300,
            "optimizer": 300,
            "experiments": 600,
            "calibration": 900,
            "governance": 300,
            "recovery": 300,
            "arbitrage": 300,
            "audit": 600,
            "meta_router": 300,
            "hedger": 300,
            "autonomous": 300
        }
    })
    
    print("✅ Unified Stack started successfully")
    print("   ℹ️  All phases 9.3-10.18 orchestrated")
    print("   ℹ️  Consolidated state: logs/unified_state.json")
    print("   ℹ️  Event stream: logs/unified_events.jsonl")

# ======================================================================================
# State Export for Dashboard
# ======================================================================================

def get_unified_state() -> Dict:
    """Get current unified stack state"""
    return {
        "boot_ts": STATE.get("last_boot_ts", 0),
        "ticks": STATE.get("ticks", {}),
        "errors": STATE.get("errors", [])[-20:],  # Last 20 errors
        "uptime_sec": int(time.time()) - STATE.get("last_boot_ts", 0)
    }
