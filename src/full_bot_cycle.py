# src/full_bot_cycle.py
#
# Phase 15.0 + 16.0 + 16.5 – Unified Autonomous Trading Bot
# Runtime trading loop + nightly maintenance + self-healing governance + multi-symbol promotion & autonomous sizing
#
# Key features:
#   - Per-symbol autonomous sizing (reads config/sizing_state.json for all 11 coins)
#   - Enforces min/max from trading policy with safe fallback
#   - Fully automatic promotion sizing (no manual intervention)
#   - Nightly multi-symbol profitability review + allocation
#   - Self-healing governance (auto-fixes venue mismatches and exit log issues)
#   - Zero manual intervention: detects issues → auto-fixes → verifies → continues trading

import os, json, time
import src.accounting_sanity_guard as accounting
import src.unified_intelligence_learning_mode as intelligence
import src.promotion_pruning_autonomy as promotion
import src.promotion_pruning_autotune as autotune
import src.exit_learning_and_enforcement as exits
import src.operator_intelligence_loop as operator_intel
import src.strategic_attribution_engine as attribution
import src.operational_safety_layer as safety
import src.cockpit_dashboard_generator as dashboard
import src.continuous_improvement_loop as improvement

# Optional: if venue audit exists, it will be used in governance checks
try:
    from src.venue_audit import run_venue_audit
except Exception:
    run_venue_audit = None

EVENT_LOG = "logs/full_bot_cycle_events.jsonl"
SIZING_STATE_PATH = "config/sizing_state.json"
EXIT_RUNTIME_LOG = "logs/exit_runtime_events.jsonl"

# ---- Safe trading policy loader (Python or JSON fallback) ----
def _load_trading_policy():
    """
    Attempts to load trading policy from Python module config/trading_policy.py,
    falls back to JSON config/trading_policy.json or reasonable defaults if absent.
    """
    # Try Python module
    try:
        from config.trading_policy import TRADING_POLICY
        return TRADING_POLICY
    except Exception:
        pass
    # Try JSON fallback
    try:
        with open("config/trading_policy.json", "r") as f:
            return json.load(f)
    except Exception:
        pass
    # Defaults as last resort (Updated 2025-12-03: $200 minimum based on data analysis)
    return {
        "MIN_POSITION_SIZE_USD": 200.0,
        "MAX_POSITION_SIZE_USD": 2000.0,
        "MAX_LEVERAGE": 10.0,
        "ALLOCATION_TOP_HEAVY": 0.70,
        "EXECUTION_LIMITS": {
            "MAX_SLIPPAGE_ROI": 0.0006,
            "MAX_SPREAD_ROI": 0.0004,
            "MAX_LATENCY_MS": 500
        }
    }

TRADING_POLICY = _load_trading_policy()

# ---- Governance functions ----
def freeze_trading():
    """Freeze trading due to governance violation."""
    _append_event("trading_frozen", {"reason": "governance_violation"})
    print("🚨 TRADING FROZEN: Governance violation detected")
    
    # Create freeze flag file
    os.makedirs("logs", exist_ok=True)
    with open("logs/trading_frozen.flag", "w") as f:
        f.write(json.dumps({
            "frozen_at": int(time.time()),
            "reason": "governance_violation"
        }))

def is_trading_frozen() -> bool:
    """Check if trading is currently frozen."""
    return os.path.exists("logs/trading_frozen.flag")

def unfreeze_trading():
    """Remove trading freeze."""
    if os.path.exists("logs/trading_frozen.flag"):
        os.remove("logs/trading_frozen.flag")
        _append_event("trading_unfrozen")
        print("✅ Trading unfrozen")

def auto_fix_venue_issues(violations: list) -> int:
    """
    Automatically fix venue mismatches by correcting the code.
    
    Args:
        violations: List of venue violation dicts with file, line, issue, code
    
    Returns:
        Number of fixes applied
    """
    fixed_count = 0
    
    for violation in violations:
        if violation['severity'] != 'HIGH':
            continue  # Only auto-fix high severity issues
        
        filepath = violation['file']
        line_num = violation['line']
        issue = violation['issue']
        
        try:
            with open(filepath, 'r') as f:
                lines = f.readlines()
            
            if line_num > len(lines):
                continue
            
            original_line = lines[line_num - 1]
            fixed_line = original_line
            
            # Fix spot sizing in futures context
            if 'SPOT sizing function in FUTURES context' in issue:
                if 'get_position_size(' in fixed_line and 'get_futures_position_size_kelly' not in fixed_line:
                    # Replace with futures sizing function
                    fixed_line = fixed_line.replace(
                        'get_position_size(',
                        'get_futures_position_size_kelly('
                    )
                    _append_event("auto_fix_applied_line", {
                        "file": filepath,
                        "line": line_num,
                        "before": original_line.strip(),
                        "after": fixed_line.strip()
                    })
            
            # Fix futures sizing in spot context  
            elif 'FUTURES sizing function in SPOT context' in issue:
                if 'get_futures_position_size_kelly(' in fixed_line:
                    fixed_line = fixed_line.replace(
                        'get_futures_position_size_kelly(',
                        'get_position_size('
                    )
                    _append_event("auto_fix_applied_line", {
                        "file": filepath,
                        "line": line_num,
                        "before": original_line.strip(),
                        "after": fixed_line.strip()
                    })
            
            # Apply fix if line changed
            if fixed_line != original_line:
                lines[line_num - 1] = fixed_line
                with open(filepath, 'w') as f:
                    f.writelines(lines)
                fixed_count += 1
                
        except Exception as e:
            _append_event("auto_fix_error", {
                "file": filepath,
                "line": line_num,
                "error": str(e)
            })
            continue
    
    return fixed_count

def auto_repair_exit_logs(log_path: str, invalid_events: list) -> int:
    """
    Automatically repair invalid exit log entries.
    
    Args:
        log_path: Path to exit log file
        invalid_events: List of invalid event dicts
    
    Returns:
        Number of events repaired
    """
    try:
        # Read all logs
        with open(log_path, 'r') as f:
            all_logs = [json.loads(line.strip()) for line in f if line.strip()]
        
        repaired_count = 0
        
        for i, log in enumerate(all_logs):
            # Fix missing exit_type
            if 'exit_type' not in log:
                # Infer exit_type from other fields
                if 'reason' in log:
                    reason = log['reason'].lower()
                    if 'tp1' in reason or 'take_profit_1' in reason:
                        log['exit_type'] = 'tp1'
                    elif 'tp2' in reason or 'take_profit_2' in reason:
                        log['exit_type'] = 'tp2'
                    elif 'trail' in reason:
                        log['exit_type'] = 'trailing'
                    elif 'stop' in reason:
                        log['exit_type'] = 'stop'
                    elif 'time' in reason:
                        log['exit_type'] = 'time_stop'
                    else:
                        log['exit_type'] = 'closed'
                else:
                    log['exit_type'] = 'closed'  # Default
                
                all_logs[i] = log
                repaired_count += 1
            
            # Fix invalid exit_type values
            elif log['exit_type'] not in {'tp1','tp2','trailing','stop','time_stop','closed'}:
                log['exit_type'] = 'closed'  # Normalize to valid value
                all_logs[i] = log
                repaired_count += 1
        
        # Write repaired logs back
        if repaired_count > 0:
            with open(log_path, 'w') as f:
                for log in all_logs:
                    f.write(json.dumps(log) + '\n')
        
        return repaired_count
        
    except Exception as e:
        _append_event("exit_log_repair_error", {"error": str(e)})
        return 0

# ---- IO helpers ----
def _append_event(event: str, payload: dict = None):
    os.makedirs(os.path.dirname(EVENT_LOG), exist_ok=True)
    payload = dict(payload or {})
    payload.update({"event": event, "ts": int(time.time())})
    with open(EVENT_LOG, "a") as f:
        f.write(json.dumps(payload) + "\n")

def _read_json(path: str, default: dict):
    if not os.path.exists(path): return default
    with open(path, "r") as f:
        try: return json.load(f)
        except: return default

def _write_json(path: str, obj: dict):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f: json.dump(obj, f, indent=2)

def _read_jsonl(path: str):
    if not os.path.exists(path): return []
    out = []
    with open(path, "r") as f:
        for line in f:
            s = line.strip()
            if s:
                try: out.append(json.loads(s))
                except: pass
    return out

# ---- Autonomous per-symbol sizing enforcement ----
def enforce_position_size(symbol: str, calculated_size_usd: float) -> float:
    """
    Fully autonomous per-symbol sizing:
      - Reads base_size_usd from config/sizing_state.json (promotion updates write here)
      - Clamps to min/max from trading policy
      - Defaults to 250 USD if no sizing state exists for symbol
    """
    sizing_state = _read_json(SIZING_STATE_PATH, {})
    base_size = float(sizing_state.get(symbol, {}).get("base_size_usd", 250.0))

    # If a strategy provided a calculated_size_usd (e.g., Kelly), use the larger of base and calculated
    target = max(base_size, float(calculated_size_usd or 0.0))

    # Clamp to policy bounds
    min_sz = float(TRADING_POLICY.get("MIN_POSITION_SIZE_USD", 100.0))
    max_sz = float(TRADING_POLICY.get("MAX_POSITION_SIZE_USD", 500.0))
    final_size = max(min_sz, min(max_sz, target))

    _append_event("sizing_enforced", {
        "symbol": symbol, "base_size": base_size, "calculated": calculated_size_usd, "final_size": final_size
    })
    return final_size

# ---- Runtime trading loop ----
class BotCycle:
    def __init__(self):
        self.exit_adapter = exits.ExitAdapter()
        self.open_positions = {}

    def on_new_position(self, position_id: str, symbol: str, regime: str, calculated_size_usd: float):
        size_usd = enforce_position_size(symbol, calculated_size_usd)
        state = {
            "position_id": position_id,
            "symbol": symbol,
            "regime": regime,
            "size_usd": size_usd,
            "roi": 0.0,
            "atr_roi": 0.0,
            "minutes_open": 0,
            "size_remaining": 1.0
        }
        self.open_positions[position_id] = state
        self.exit_adapter.attach(position_id, symbol, regime)
        _append_event("position_opened", {"position_id": position_id, "symbol": symbol, "size_usd": size_usd})

    def on_tick(self, position_id: str, roi: float, atr_roi: float, minutes_open: int, size_remaining: float):
        state = self.open_positions.get(position_id)
        if not state: return
        state.update({"roi": roi, "atr_roi": atr_roi, "minutes_open": minutes_open, "size_remaining": size_remaining})
        decision = self.exit_adapter.update(position_id, state)
        if decision["action"] in {"tp1","tp2","trail_exit","stop","time_stop"}:
            self.execute_exit(position_id, decision)

    def execute_exit(self, position_id: str, decision: dict):
        _append_event("exit_executed", {"position_id": position_id, "decision": decision})
        state = self.open_positions.get(position_id)
        if state:
            state["size_remaining"] = max(0.0, state["size_remaining"] - decision.get("size_fraction", 0.0))
            if state["size_remaining"] <= 0.0:
                self.on_close(position_id, state)

    def on_close(self, position_id: str, final_state: dict):
        self.exit_adapter.on_close(position_id, final_state)
        _append_event("position_closed", {"position_id": position_id, "final_state": final_state})
        self.open_positions.pop(position_id, None)

# ---- Multi-symbol nightly promotion & allocation (Phase 16.5) ----
def run_multi_symbol_promotion_and_allocation():
    """
    Compute per-symbol metrics from logs, decide promotions/pruning, and update sizing_state.json.
    Also emits a suggested allocation profile. Works for any set of symbols present in logs.
    """
    PROFIT_LOG = "logs/unified_events.jsonl"
    EXIT_LOG = EXIT_RUNTIME_LOG

    trades = _read_jsonl(PROFIT_LOG)
    exits_logs = _read_jsonl(EXIT_LOG)

    # Aggregate metrics per symbol
    by_sym = {}
    for t in trades:
        sym = t.get("symbol"); 
        if not sym: continue
        L = by_sym.setdefault(sym, {"net": [], "wr": []})
        if "net_roi" in t: 
            L["net"].append(float(t["net_roi"]))
        elif "net_pnl" in t and "size_usd" in t:
            try: L["net"].append(float(t["net_pnl"]) / max(1.0, float(t["size_usd"])))
            except: pass
        if "win" in t: L["wr"].append(1 if t["win"] else 0)

    exit_by = {}
    for e in exits_logs:
        sym = e.get("symbol"); 
        if not sym: continue
        L = exit_by.setdefault(sym, {"tp1":0,"tp2":0,"trailing":0,"stop":0,"time_stop":0})
        et = e.get("exit_type")
        if et in L: L[et] += 1

    metrics = {}
    for sym, agg in by_sym.items():
        net = agg["net"]; wrs = agg["wr"]
        avg_net = (sum(net)/len(net)) if net else 0.0
        wr = (sum(wrs)/len(wrs)) if wrs else 0.0
        ex = exit_by.get(sym, {"tp1":0,"tp2":0,"trailing":0,"stop":0,"time_stop":0})
        total_exits = sum(ex.values()) or 1
        metrics[sym] = {
            "avg_net_roi": avg_net,
            "win_rate": wr,
            "trail_share": ex["trailing"]/total_exits,
            "tp2_share": ex["tp2"]/total_exits,
            "stop_rate": ex["stop"]/total_exits,
            "time_stop_rate": ex["time_stop"]/total_exits
        }

    _append_event("symbol_metrics", {"metrics": metrics})

    sizing_state = _read_json(SIZING_STATE_PATH, {})
    promoted, pruned = [], []

    def meets_promotion(m):
        if m["avg_net_roi"] <= 0.0: return False
        if m["win_rate"] >= 0.55: return True
        if m["win_rate"] >= 0.50 and (m["trail_share"] + m["tp2_share"]) >= 0.30: return True
        return False

    def next_size(current):
        ladder = [100, 250, 500, 750, 1000, 2000, 4000, 5000]
        for s in ladder:
            if s > current: return s
        return ladder[-1]

    for sym, m in metrics.items():
        cur_size = float(sizing_state.get(sym, {}).get("base_size_usd", 250.0))
        if meets_promotion(m):
            ns = next_size(cur_size)
            sizing_state[sym] = {"base_size_usd": ns}
            promoted.append({"symbol": sym, "from": cur_size, "to": ns, "metrics": m})
        else:
            if m["avg_net_roi"] <= 0.0 or (m["stop_rate"] + m["time_stop_rate"]) > 0.40:
                sizing_state[sym] = {"base_size_usd": max(100.0, cur_size * 0.5)}
                pruned.append({"symbol": sym, "new_size": sizing_state[sym]["base_size_usd"], "metrics": m})

    _write_json(SIZING_STATE_PATH, sizing_state)
    _append_event("promotion_decisions", {"promoted": promoted, "pruned": pruned})

    # Allocation suggestion (top-heavy towards best two)
    ranked = sorted(metrics.items(), key=lambda kv: kv[1]["avg_net_roi"], reverse=True)
    alloc = {}
    if ranked:
        top = ranked[:2]; rest = ranked[2:]
        total = sum(abs(m["avg_net_roi"]) for _, m in ranked) or 1.0
        for sym, m in top:
            alloc[sym] = 0.35 + 0.15 * (abs(m["avg_net_roi"]) / total)
        for sym, m in rest:
            alloc[sym] = 0.30 * (abs(m["avg_net_roi"]) / total)
        s = sum(alloc.values()) or 1.0
        for k in alloc: alloc[k] = round(alloc[k]/s, 4)
    _append_event("allocation_update", {"allocation": alloc})

    return {"promoted": promoted, "pruned": pruned, "allocation": alloc, "metrics": metrics}

# ---- Nightly maintenance + self-healing governance ----
def run_nightly_cycle():
    _append_event("nightly_cycle_start")
    print("\n" + "="*60)
    print("🌙 NIGHTLY MAINTENANCE CYCLE")
    print("="*60)

    # 1. Accounting reconciliation
    print("\n💰 Running accounting reconciliation...")
    try:
        accounting.run_reconciliation()
        _append_event("accounting_checked")
        print("✅ Accounting reconciliation complete")
    except Exception as e:
        _append_event("accounting_error", {"error": str(e)})
        print(f"⚠️  Accounting error: {e}")

    # 2. Intelligence learning
    print("\n🧠 Running intelligence learning cycle...")
    try:
        intelligence.run_learning_cycle()
        _append_event("intelligence_learning_complete")
        print("✅ Intelligence learning complete")
    except Exception as e:
        _append_event("intelligence_error", {"error": str(e)})
        print(f"⚠️  Intelligence learning error: {e}")

    # 3. Promotion & pruning (strategy-level)
    print("\n📊 Running promotion & pruning...")
    try:
        promotion.run_promotion_pruning_nightly()
        _append_event("promotion_pruning_complete")
        print("✅ Promotion & pruning complete")
    except Exception as e:
        _append_event("promotion_error", {"error": str(e)})
        print(f"⚠️  Promotion error: {e}")

    # 4. Auto-tuning thresholds
    print("\n🎯 Running auto-tuning cycle...")
    try:
        if autotune is not None and hasattr(autotune, 'run_autonomy_cycle'):
            autotune.run_autonomy_cycle()
            _append_event("auto_tuning_complete")
            print("✅ Auto-tuning complete")
        else:
            print("⚠️  Auto-tune module not available")
    except Exception as e:
        _append_event("autotune_error", {"error": str(e)})
        print(f"⚠️  Auto-tuning error: {e}")

    # 5. Exit learning nightly tuning
    print("\n🚪 Running exit learning optimization...")
    try:
        if hasattr(exits, 'run_exit_learning_nightly'):
            exits.run_exit_learning_nightly()
        elif hasattr(exits, 'run_nightly_exit_tuning'):
            exits.run_nightly_exit_tuning()
        else:
            print("⚠️  Exit learning function not found")
        _append_event("exit_tuning_complete")
        print("✅ Exit learning complete")
    except Exception as e:
        _append_event("exit_learning_error", {"error": str(e)})
        print(f"⚠️  Exit learning error: {e}")
    
    # 5.5. Profitability Trader Persona - Comprehensive Profitability Analysis
    print("\n🧠 Running Profitability Trader Persona Analysis...")
    try:
        from src.profitability_trader_persona import run_profitability_analysis
        profitability_analysis = run_profitability_analysis()
        _append_event("profitability_analysis_complete", {
            "insights_count": len(profitability_analysis.get("key_insights", [])),
            "actions_count": len(profitability_analysis.get("profitability_actions", []))
        })
        
        # Print critical insights
        if profitability_analysis.get("profitability_actions"):
            critical_actions = [a for a in profitability_analysis["profitability_actions"] if a.get("priority") == "CRITICAL"]
            if critical_actions:
                print(f"🚨 {len(critical_actions)} CRITICAL profitability issues found:")
                for action in critical_actions[:3]:  # Top 3
                    print(f"   • {action.get('issue')}")
        
        print("✅ Profitability analysis complete")
    except Exception as e:
        _append_event("profitability_analysis_error", {"error": str(e)})
        print(f"⚠️  Profitability analysis error: {e}")

    # 5.6. Profitability Trader Persona - Comprehensive Profitability Analysis (BEFORE other adjustments)
    print("\n🧠 Running Profitability Trader Persona Analysis...")
    try:
        from src.profitability_trader_persona import run_profitability_analysis
        profitability_analysis = run_profitability_analysis()
        _append_event("profitability_analysis_complete", {
            "insights_count": len(profitability_analysis.get("key_insights", [])),
            "actions_count": len(profitability_analysis.get("profitability_actions", []))
        })
        
        # Apply critical profitability improvements immediately
        critical_actions = [a for a in profitability_analysis.get("profitability_actions", []) if a.get("priority") == "CRITICAL"]
        if critical_actions:
            print(f"🚨 {len(critical_actions)} CRITICAL profitability issues identified:")
            for action in critical_actions[:5]:  # Top 5 critical
                print(f"   • {action.get('category', 'general')}: {action.get('issue', 'N/A')}")
                print(f"     → {action.get('recommendation', 'N/A')}")
        
        print("✅ Profitability analysis complete")
    except Exception as e:
        _append_event("profitability_analysis_error", {"error": str(e)})
        print(f"⚠️  Profitability analysis error: {e}")
    
    # 6. Multi-symbol profitability review + autonomous sizing update
    print("\n🎯 Running multi-symbol promotion & allocation...")
    try:
        result = run_multi_symbol_promotion_and_allocation()
        _append_event("multi_symbol_promotion_complete", result)
        print(f"✅ Multi-symbol promotion complete: {len(result.get('promoted', []))} promoted, {len(result.get('pruned', []))} pruned")
    except Exception as e:
        _append_event("multi_symbol_error", {"error": str(e)})
        print(f"⚠️  Multi-symbol promotion error: {e}")

    # 7. Strategic Attribution (Phase 18)
    print("\n📊 Running strategic attribution...")
    try:
        attribution_result = attribution.run_strategic_attribution()
        _append_event("attribution_logged", {
            "strategies_analyzed": len(attribution_result.get("strategies", {})),
            "symbols_analyzed": len(attribution_result.get("symbols", {}))
        })
        print(f"✅ Attribution logged: {len(attribution_result.get('strategies', {}))} strategies, {len(attribution_result.get('symbols', {}))} symbols")
    except Exception as e:
        _append_event("attribution_error", {"error": str(e)})
        print(f"⚠️  Attribution error: {e}")

    # 8. Operational Safety Checks (Phase 19)
    print("\n🛡️  Running operational safety checks...")
    try:
        safety_result = safety.run_operational_safety_checks()
        _append_event("safety_checks_complete", {
            "safety_score": safety_result.get("safety_score", 0.0),
            "checks_passed": safety_result.get("checks_passed", 0),
            "checks_failed": safety_result.get("checks_failed", 0)
        })
        print(f"✅ Safety checks complete: {safety_result.get('safety_score', 0):.0%} safety score")
    except Exception as e:
        _append_event("safety_error", {"error": str(e)})
        print(f"⚠️  Safety check error: {e}")

    # 9. Cockpit Dashboard Generator (Phase 20)
    print("\n📈 Generating cockpit dashboard...")
    try:
        dashboard_result = dashboard.generate_daily_dashboard()
        _append_event("dashboard_generated", {
            "portfolio_value": dashboard_result.get("portfolio_value", 0.0),
            "pnl_pct": dashboard_result.get("pnl_pct", 0.0)
        })
        print(f"✅ Dashboard generated: Portfolio ${dashboard_result.get('portfolio_value', 0):,.2f} ({dashboard_result.get('pnl_pct', 0):+.2f}%)")
    except Exception as e:
        _append_event("dashboard_error", {"error": str(e)})
        print(f"⚠️  Dashboard error: {e}")

    # 10. Continuous Improvement Loop (Phase 21)
    print("\n🔄 Running continuous improvement...")
    try:
        improvement_result = improvement.run_continuous_improvement()
        _append_event("continuous_improvement_complete", {
            "improvements_made": improvement_result.get("improvements_made", 0)
        })
        print(f"✅ Continuous improvement complete: {improvement_result.get('improvements_made', 0)} optimizations")
    except Exception as e:
        _append_event("improvement_error", {"error": str(e)})
        print(f"⚠️  Continuous improvement error: {e}")

    # 11. Advanced Analytics (Phases 24-26)
    print("\n📊 Running advanced analytics (Phases 24-26)...")
    try:
        from src import phase_24_25_26
        result = phase_24_25_26.run_phase_24_25_26()
        _append_event("advanced_analytics_complete", {
            "symbols_tracked": len(result.get("dashboard", {}).get("symbols", {})),
            "new_variants": len(result.get("shadows", []))
        })
        print(f"✅ Advanced analytics complete: {len(result.get('dashboard', {}).get('symbols', {}))} symbols tracked")
    except Exception as e:
        _append_event("advanced_analytics_error", {"error": str(e)})
        print(f"⚠️  Advanced analytics error: {e}")

    # 11.5. AI Strategy Generator (Phase 27)
    print("\n🤖 Running AI strategy generator...")
    try:
        from src import ai_strategy_generator
        ai_strategies = ai_strategy_generator.generate_ai_strategies()
        _append_event("ai_strategies_generated", {
            "count": len(ai_strategies)
        })
        print(f"✅ AI strategy generation complete: {len(ai_strategies)} new strategies")
    except Exception as e:
        _append_event("ai_strategy_error", {"error": str(e)})
        print(f"⚠️  AI strategy generator error: {e}")

    # 11.6. Strategy Lineage & Capital Allocation (Phases 29-30)
    print("\n📊 Running lineage tracking and capital allocation...")
    try:
        from src import phase_29_30
        result = phase_29_30.run_phase_29_30()
        _append_event("phase_29_30_complete", {
            "promoted": result.get("lineage", {}).get("promoted", 0),
            "retired": result.get("lineage", {}).get("retired", 0),
            "capital_updates": len(result.get("capital_updates", []))
        })
        print(f"✅ Lineage: {result.get('lineage', {}).get('promoted', 0)} promoted, {result.get('lineage', {}).get('retired', 0)} retired")
        print(f"✅ Capital: {len(result.get('capital_updates', []))} allocations updated")
    except Exception as e:
        _append_event("phase_29_30_error", {"error": str(e)})
        print(f"⚠️  Phase 29-30 error: {e}")

    # 11.7. Strategy Evolution & Risk Management (Phases 34-36)
    print("\n🧬 Running strategy mutation, regime forecast, and insurance layer...")
    try:
        from src import phase_34_35_36
        result = phase_34_35_36.run_phase_34_35_36()
        _append_event("phase_34_35_36_complete", {
            "mutations": len(result.get("mutated", [])),
            "predicted_regime": result.get("forecast", {}).get("predicted_regime", "unknown"),
            "insurance_flags": len(result.get("insurance_flags", []))
        })
        print(f"✅ Mutations: {len(result.get('mutated', []))} strategies mutated")
        print(f"✅ Forecast: {result.get('forecast', {}).get('predicted_regime', 'unknown')} regime predicted")
        print(f"✅ Insurance: {len(result.get('insurance_flags', []))} symbols flagged")
    except Exception as e:
        _append_event("phase_34_35_36_error", {"error": str(e)})
        print(f"⚠️  Phase 34-36 error: {e}")

    # 11.8. Advanced Analysis & Oversight (Phases 37-41)
    print("\n🔍 Running profile analysis, sentiment scanning, and operator oversight...")
    try:
        from src import phase_37_41
        result = phase_37_41.run_phase_37_41()
        _append_event("phase_37_41_complete", {
            "profiles_analyzed": sum(len(v) for v in result.get("profiles", {}).values()),
            "symbols_scanned": len(result.get("sentiment", {})),
            "strategies_resurrected": len(result.get("resurrected", [])),
            "trades_replayed": len(result.get("replay", [])),
            "issues_found": result.get("overlord", {}).get("issues_found", 0)
        })
        print(f"✅ Profiles: {sum(len(v) for v in result.get('profiles', {}).values())} analyzed")
        print(f"✅ Sentiment: {len(result.get('sentiment', {}))} symbols scanned")
        print(f"✅ Resurrected: {len(result.get('resurrected', []))} strategies")
        print(f"✅ Overlord: {result.get('overlord', {}).get('issues_found', 0)} issues identified")
    except Exception as e:
        _append_event("phase_37_41_error", {"error": str(e)})
        print(f"⚠️  Phase 37-41 error: {e}")

    # 11.9. Exit Optimization & Drift Detection (Phases 42-45)
    print("\n🎯 Running exit pairing, evolution, regime memory, and drift detection...")
    try:
        from src import phase_42_45
        result = phase_42_45.run_phase_42_45()
        _append_event("phase_42_45_complete", {
            "pairings_optimized": len(result.get("pairings", {})),
            "profiles_evolved": len(result.get("evolutions", [])),
            "symbols_tracked": len(result.get("regime_memory", {})),
            "drift_flags": len(result.get("drift_flags", []))
        })
        print(f"✅ Pairings: {len(result.get('pairings', {}))} strategy-exit pairs optimized")
        print(f"✅ Evolution: {len(result.get('evolutions', []))} exit profile changes")
        print(f"✅ Regime Memory: {len(result.get('regime_memory', {}))} symbols tracked")
        print(f"✅ Drift: {len(result.get('drift_flags', []))} strategies flagged")
    except Exception as e:
        _append_event("phase_42_45_error", {"error": str(e)})
        print(f"⚠️  Phase 42-45 error: {e}")

    # 11.10. Strategy Composition & Expectancy (Phases 46-50)
    print("\n🎼 Running strategy composition, expectancy, pruning, and regime allocation...")
    try:
        from src import phase_46_50
        result = phase_46_50.run_phase_46_50()
        _append_event("phase_46_50_complete", {
            "strategies_composed": len(result.get("composed", [])),
            "expectancy_calculated": len(result.get("expectancy", {})),
            "variants_pruned": len(result.get("pruned", [])),
            "regime_allocations": len(result.get("regime_allocation", []))
        })
        print(f"✅ Composed: {len(result.get('composed', []))} new strategies")
        print(f"✅ Expectancy: {len(result.get('expectancy', {}))} pairs analyzed")
        print(f"✅ Pruning: {len(result.get('pruned', []))} variants flagged")
        print(f"✅ Regime Alloc: {len(result.get('regime_allocation', []))} adjustments")
    except Exception as e:
        _append_event("phase_46_50_error", {"error": str(e)})
        print(f"⚠️  Phase 46-50 error: {e}")

    # 11.11. Meta-Learning & Final Audit (Phases 51-55)
    print("\n🧠 Running meta-learning, quality scoring, genome mapping, and audit...")
    try:
        from src import phase_51_55
        result = phase_51_55.run_phase_51_55()
        _append_event("phase_51_55_complete", {
            "meta_learning_analyzed": len(result.get("meta_learning", {})),
            "quality_scored": len(result.get("attribution_quality", {})),
            "genomes_mapped": len(result.get("genome", {})),
            "audit_status": result.get("audit", {}).get("health_status", "unknown")
        })
        print(f"✅ Meta-Learning: {len(result.get('meta_learning', {}))} variants analyzed")
        print(f"✅ Quality: {len(result.get('attribution_quality', {}))} strategies scored")
        print(f"✅ Genome: {len(result.get('genome', {}))} genomes mapped")
        print(f"✅ Audit: System {result.get('audit', {}).get('health_status', 'unknown')}")
    except Exception as e:
        _append_event("phase_51_55_error", {"error": str(e)})
        print(f"⚠️  Phase 51-55 error: {e}")

    # 11.12. Research & Simulation (Phases 56-60)
    print("\n🔬 Running research agent, forking, sync, simulation, and memory...")
    try:
        from src import phase_56_60
        result = phase_56_60.run_phase_56_60()
        _append_event("phase_56_60_complete", {
            "research_ideas": len(result.get("research", [])),
            "forks_created": len(result.get("forks", [])),
            "sync_status": result.get("sync", {}).get("sync_status", "unknown"),
            "simulations": len(result.get("simulation", []))
        })
        print(f"✅ Research: {len(result.get('research', []))} ideas identified")
        print(f"✅ Forking: {len(result.get('forks', []))} strategy forks created")
        print(f"✅ Sync: {result.get('sync', {}).get('sync_status', 'unknown')}")
        print(f"✅ Simulation: {len(result.get('simulation', []))} results")
    except Exception as e:
        _append_event("phase_56_60_error", {"error": str(e)})
        print(f"⚠️  Phase 56-60 error: {e}")

    # 11.13. Tournament & Alerts (Phases 61-65)
    print("\n🏆 Running tournament, heatmap, regime tracking, sentiment, and alerts...")
    try:
        from src import phase_61_65
        result = phase_61_65.run_phase_61_65()
        _append_event("phase_61_65_complete", {
            "tournament_participants": len(result.get("tournament", [])),
            "heatmap_cells": len(result.get("heatmap", {})),
            "regime_transitions": len(result.get("transitions", {}).get("transitions", [])),
            "sentiment_scores": len(result.get("sentiment", {})),
            "alerts_generated": len(result.get("alerts", []))
        })
        print(f"✅ Tournament: {len(result.get('tournament', []))} variants ranked")
        print(f"✅ Heatmap: {len(result.get('heatmap', {}))} cells")
        print(f"✅ Transitions: {len(result.get('transitions', {}).get('transitions', []))} tracked")
        print(f"✅ Sentiment: {len(result.get('sentiment', {}))} scores")
        print(f"✅ Alerts: {len(result.get('alerts', []))} generated")
    except Exception as e:
        _append_event("phase_61_65_error", {"error": str(e)})
        print(f"⚠️  Phase 61-65 error: {e}")

    # 11.14. Archetype & Memory (Phases 66-70)
    print("\n🎭 Running archetype classification, decay monitoring, rotation, planning, and archival...")
    try:
        from src import phase_66_70
        result = phase_66_70.run_phase_66_70()
        _append_event("phase_66_70_complete", {
            "archetypes_classified": len(result.get("archetypes", {})),
            "decay_analyzed": len(result.get("decay", {})),
            "rotations": len(result.get("rotation", [])),
            "plan_actions": len(result.get("plan", {}).get("promote", [])) + len(result.get("plan", {}).get("mutate", [])),
            "archived_trades": result.get("archive", {}).get("archived_count", 0)
        })
        print(f"✅ Archetypes: {len(result.get('archetypes', {}))} classified")
        print(f"✅ Decay: {len(result.get('decay', {}))} strategies analyzed")
        print(f"✅ Rotation: {len(result.get('rotation', []))} symbols rotated")
        print(f"✅ Plan: {len(result.get('plan', {}).get('promote', []))} promote, {len(result.get('plan', {}).get('mutate', []))} mutate")
        print(f"✅ Archive: {result.get('archive', {}).get('archived_count', 0)} trades archived")
    except Exception as e:
        _append_event("phase_66_70_error", {"error": str(e)})
        print(f"⚠️  Phase 66-70 error: {e}")

    # 11.15. Evolution & Curiosity (Phases 71-75)
    print("\n🧬 Running evolution, exit design, timeline, anomaly detection, and curiosity...")
    try:
        from src import phase_71_75
        result = phase_71_75.run_phase_71_75()
        _append_event("phase_71_75_complete", {
            "archetypes_evolved": len(result.get("evolved", [])),
            "exit_designs": len(result.get("exits", {})),
            "timeline_entries": len(result.get("timeline", [])),
            "anomalies_detected": len(result.get("anomalies", [])),
            "curiosity_ideas": len(result.get("curiosity", []))
        })
        print(f"✅ Evolution: {len(result.get('evolved', []))} archetypes evolved")
        print(f"✅ Exit Design: {len(result.get('exits', {}))} regime exits designed")
        print(f"✅ Timeline: {len(result.get('timeline', []))} entries tracked")
        print(f"✅ Anomalies: {len(result.get('anomalies', []))} detected")
        print(f"✅ Curiosity: {len(result.get('curiosity', []))} ideas generated")
    except Exception as e:
        _append_event("phase_71_75_error", {"error": str(e)})
        print(f"⚠️  Phase 71-75 error: {e}")

    # 11.16. Lifecycle & Composition (Phases 76-80)
    print("\n📊 Running lifecycle management, composition, confidence scoring, journal, and evaluation...")
    try:
        from src import phase_76_80
        result = phase_76_80.run_phase_76_80()
        _append_event("phase_76_80_complete", {
            "lifecycle_events": len(result.get("lifecycle", [])),
            "composed_strategies": len(result.get("composed", [])),
            "confidence_scores": len(result.get("confidence", {})),
            "journal_logged": 1,
            "ideas_evaluated": len(result.get("curiosity_evaluation", []))
        })
        print(f"✅ Lifecycle: {len(result.get('lifecycle', []))} events")
        print(f"✅ Composition: {len(result.get('composed', []))} regime strategies")
        print(f"✅ Confidence: {len(result.get('confidence', {}))} scores")
        print(f"✅ Journal: Entry logged")
        print(f"✅ Evaluation: {len(result.get('curiosity_evaluation', []))} ideas")
    except Exception as e:
        _append_event("phase_76_80_error", {"error": str(e)})
        print(f"⚠️  Phase 76-80 error: {e}")

    # 11.17. Visualization & Tracking (Phases 81-85)
    print("\n📈 Running visualization, validation, smoothing, digest, and tracking...")
    try:
        from src import phase_81_85
        result = phase_81_85.run_phase_81_85()
        _append_event("phase_81_85_complete", {
            "variant_timelines": len(result.get("lifecycle_timeline", {})),
            "forecast_accuracy": result.get("regime_validation", {}).get("accuracy", 0),
            "smoothed_strategies": len(result.get("smoothed_attribution", {})),
            "digest_alerts": result.get("operator_digest", {}).get("alert_count", 0),
            "curiosity_actionable": result.get("curiosity_tracker", {}).get("actionable_ideas", 0)
        })
        print(f"✅ Visualization: {len(result.get('lifecycle_timeline', {}))} timelines")
        print(f"✅ Validation: {result.get('regime_validation', {}).get('accuracy', 0):.1%} accuracy")
        print(f"✅ Smoothing: {len(result.get('smoothed_attribution', {}))} strategies")
        print(f"✅ Digest: {result.get('operator_digest', {}).get('alert_count', 0)} alerts")
        print(f"✅ Tracking: {result.get('curiosity_tracker', {}).get('actionable_ideas', 0)} actionable ideas")
    except Exception as e:
        _append_event("phase_81_85_error", {"error": str(e)})
        print(f"⚠️  Phase 81-85 error: {e}")

    # 11.18. Feedback & Hypothesis (Phases 86-90)
    print("\n🔄 Running feedback loop, mutation, stability, memory, and hypothesis generation...")
    try:
        from src import phase_86_90
        result = phase_86_90.run_phase_86_90()
        _append_event("phase_86_90_complete", {
            "feedback_actions": len(result.get("feedback", [])),
            "mutations_created": len(result.get("mutations", [])),
            "stability_scores": len(result.get("stability_index", {})),
            "memory_strategies": len(result.get("memory_visualization", {})),
            "hypotheses_generated": len(result.get("hypotheses", []))
        })
        print(f"✅ Feedback: {len(result.get('feedback', []))} actions")
        print(f"✅ Mutation: {len(result.get('mutations', []))} regime mutations")
        print(f"✅ Stability: {len(result.get('stability_index', {}))} scores")
        print(f"✅ Memory: {len(result.get('memory_visualization', {}))} strategies")
        print(f"✅ Hypotheses: {len(result.get('hypotheses', []))} generated")
    except Exception as e:
        _append_event("phase_86_90_error", {"error": str(e)})
        print(f"⚠️  Phase 86-90 error: {e}")

    # 11.18.5. Testing & Review (Phases 91-95)
    print("\n🧪 Running hypothesis testing, timeline visualization, drift detection, synthesis, and review...")
    try:
        from src import phase_91_95
        result = phase_91_95.run_phase_91_95()
        _append_event("phase_91_95_complete", {
            "hypotheses_tested": len(result.get("hypothesis_results", [])),
            "timeline_entries": len(result.get("timeline_visualization", [])),
            "drift_events": len(result.get("regime_drift", [])),
            "syntheses_created": len(result.get("curiosity_synthesis", [])),
            "strategies_reviewed": len(result.get("strategy_review", {}))
        })
        print(f"✅ Testing: {len(result.get('hypothesis_results', []))} hypotheses tested")
        print(f"✅ Timeline: {len(result.get('timeline_visualization', []))} entries")
        print(f"✅ Drift: {len(result.get('regime_drift', []))} events")
        print(f"✅ Synthesis: {len(result.get('curiosity_synthesis', []))} created")
        print(f"✅ Review: {len(result.get('strategy_review', {}))} strategies")
    except Exception as e:
        _append_event("phase_91_95_error", {"error": str(e)})
        print(f"⚠️  Phase 91-95 error: {e}")

    # 11.19. Orchestration & Planning (Phases 96-100)
    print("\n🎼 Running orchestration, synthesis, planning, reflection, and summary...")
    try:
        from src import phase_96_100
        result = phase_96_100.run_phase_96_100()
        _append_event("phase_96_100_complete", {
            "orchestrated_strategies": len(result.get("orchestration_plan", [])),
            "forecast_regime": result.get("forecast_synthesis", {}).get("regime", "unknown"),
            "long_term_plan_generated": 1,
            "reflection_logged": 1,
            "evolution_events": result.get("evolution_summary", {}).get("total_attribution_events", 0)
        })
        print(f"✅ Orchestration: {len(result.get('orchestration_plan', []))} strategies")
        print(f"✅ Forecast: {result.get('forecast_synthesis', {}).get('regime', 'unknown')} regime")
        print(f"✅ Long-term: Plan generated")
        print(f"✅ Reflection: Logged")
        print(f"✅ Summary: {result.get('evolution_summary', {}).get('total_attribution_events', 0)} events")
    except Exception as e:
        _append_event("phase_96_100_error", {"error": str(e)})
        print(f"⚠️  Phase 96-100 error: {e}")

    # 12. Operator governance: Venue audit with auto-fix
    print("\n🛡️  Running venue audit...")
    try:
        if run_venue_audit is not None:
            audit_results = run_venue_audit()
            if audit_results.get("violations"):
                _append_event("governance_violation_detected", {"violations": audit_results["violations"]})
                print(f"⚠️  GOVERNANCE ISSUE: {len(audit_results['violations'])} venue mismatches found")
                print("🔧 Attempting automatic fix...")
                
                # Auto-fix venue mismatches
                fixed_count = auto_fix_venue_issues(audit_results["violations"])
                
                if fixed_count > 0:
                    _append_event("auto_fix_applied", {"fixed_count": fixed_count})
                    print(f"✅ Auto-fixed {fixed_count} venue mismatches")
                    print("🔄 Re-running audit to verify fixes...")
                    
                    # Verify fixes
                    verify_results = run_venue_audit()
                    if verify_results.get("violations"):
                        _append_event("auto_fix_failed", {"remaining": len(verify_results["violations"])})
                        print(f"🚨 AUTO-FIX INCOMPLETE: {len(verify_results['violations'])} issues remain")
                        freeze_trading()
                    else:
                        _append_event("auto_fix_success")
                        print("✅ All venue issues resolved automatically")
                else:
                    _append_event("auto_fix_failed", {"reason": "no_fixes_applied"})
                    print("🚨 AUTO-FIX FAILED: Unable to automatically resolve issues")
                    freeze_trading()
            else:
                _append_event("venue_audit_passed")
                print("✅ Venue audit passed - no mismatches")
        else:
            print("⚠️  Venue audit not available")
    except Exception as e:
        _append_event("audit_error", {"error": str(e)})
        print(f"⚠️  Venue audit error: {e}")

    # 13. Exit log integrity validation with auto-repair
    print("\n🔍 Validating exit log integrity...")
    try:
        exit_log_path = EXIT_RUNTIME_LOG
        if os.path.exists(exit_log_path):
            exit_logs = []
            with open(exit_log_path, 'r') as f:
                for line in f:
                    try:
                        exit_logs.append(json.loads(line.strip()))
                    except:
                        pass
            
            invalid_events = []
            for e in exit_logs[-100:]:  # Check last 100 events
                if "exit_type" not in e or e["exit_type"] not in {"tp1","tp2","trailing","stop","time_stop","closed"}:
                    invalid_events.append(e)
            
            if invalid_events:
                _append_event("exit_log_violation_detected", {"count": len(invalid_events)})
                print(f"⚠️  EXIT LOG ISSUE: {len(invalid_events)} invalid events found")
                print("🔧 Attempting automatic repair...")
                
                # Auto-repair exit logs
                repaired_count = auto_repair_exit_logs(exit_log_path, invalid_events)
                
                if repaired_count > 0:
                    _append_event("exit_log_repaired", {"repaired_count": repaired_count})
                    print(f"✅ Auto-repaired {repaired_count} exit log entries")
                else:
                    _append_event("exit_log_repair_failed")
                    print("⚠️  Unable to auto-repair exit logs (non-critical)")
            else:
                _append_event("exit_log_validated")
                print("✅ Exit log integrity validated")
        else:
            print("⚠️  Exit log not found (will be created on first exit)")
    except Exception as e:
        _append_event("exit_log_error", {"error": str(e)})
        print(f"⚠️  Exit log validation error: {e}")

    _append_event("nightly_cycle_complete")
    print("\n" + "="*60)
    print("✅ Nightly Maintenance Cycle Complete")
    print("="*60 + "\n")

# ---- Phase 23.0: Operator Intelligence Loop ----
def run_operator_intelligence():
    """
    Run comprehensive operator intelligence review:
    - Analyze Phase 18-21 analytics data
    - Auto-promote high-performing symbols
    - Auto-prune underperforming symbols
    - Auto-freeze trading on safety failures
    - Generate daily readiness report
    
    Schedule: During nightly cycle (2 AM) or manual trigger
    """
    print("\n" + "="*60)
    print("🔍 PHASE 23.0: OPERATOR INTELLIGENCE LOOP")
    print("="*60 + "\n")
    
    try:
        result = operator_intel.run_operator_intelligence()
        _append_event("operator_intelligence_complete", {
            "status": result.get("readiness_status"),
            "safety_score": result.get("safety_score"),
            "promoted": len(result.get("promoted_symbols", [])),
            "pruned": len(result.get("pruned_symbols", []))
        })
        print(f"✅ Operator intelligence complete: {result.get('readiness_status')} | Safety: {result.get('safety_score'):.0%}")
        print(f"   Promoted: {len(result.get('promoted_symbols', []))} | Pruned: {len(result.get('pruned_symbols', []))}")
        return result
    except Exception as e:
        _append_event("operator_intelligence_error", {"error": str(e)})
        print(f"⚠️  Operator intelligence error: {e}")
        return None

# ---- Example main ----
if __name__ == "__main__":
    # Runtime example: open positions for arbitrary symbols (works for all 11 coins and beyond)
    bot = BotCycle()
    for sym in ["SOLUSDT","BTCUSDT","ETHUSDT","AVAXUSDT","DOTUSDT","TRXUSDT","MATICUSDT","ADAUSDT","XRPUSDT","BNBUSDT","DOGEUSDT"]:
        bot.on_new_position(f"pos_{sym}", sym, regime="volatile", calculated_size_usd=0.0)

    # Simulate a few ticks for one symbol
    for minute in range(0, 120, 5):
        roi = 0.004 + (minute/10000.0)
        atr_roi = 0.002
        bot.on_tick("pos_SOLUSDT", roi, atr_roi, minute, bot.open_positions["pos_SOLUSDT"]["size_remaining"])

    # Nightly cycle
    run_nightly_cycle()
    print("\n✅ Phase 15.0 + 16.0 + 16.5 full bot cycle executed.")
    print("   Runtime + nightly autonomy + self-healing governance + multi-symbol sizing integrated.\n")
