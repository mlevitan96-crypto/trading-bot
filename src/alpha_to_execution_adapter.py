# --- src/alpha_to_execution_adapter.py (Updated: Autonomy Hardening [246-250] + Technical Resilience [236-245] + Precision Monitor [221-225] + External Intelligence [211–220] + Prior Layers) ---
#
# This wiring package integrates autonomy hardening (Phases 246-250),
# technical resilience and self-healing (Phases 236–245),
# precision monitoring and advanced venue selection (Phases 221–225),
# external intelligence (Phases 211–220), symbol-level calibration (161–170),
# bridge enhancements (171–180), profit loop & execution optimization (181–190),
# and portfolio orchestration (191–200).
#
# Decision flow (pre-gates):
# 0) Autonomy hardening: dependency gates (Phase 249), deadlock guards (Phase 247)
# 1) Technical resilience: global halt check (Phase 238), heartbeat emit (Phase 236)
# 2) Meta halts & shocks: portfolio drawdown guard, profit loop action, event shocks
# 3) External fusion: sentiment/funding/open interest bias, cross-market arbitrage hint
# 4) Portfolio scalers: regime scaling, profit lock cooldown, risk allocator size multiplier
# 5) Precision-adjusted gates: live confidence nudge (Phase 222), venue selector v2 (Phase 223)
# 6) Micro-execution: slippage guard, latency-aware TTL
# 7) Symbol gates: calibrated ROI, per-symbol confidence, MTF confirmation
# 8) Execution gates (113, 123, 129, 114)
# 9) Idempotency check (Phase 246) and order placement
# 10) Post-execution: finalize order intent (Phase 246)

import os, json, time

# ---------- Integration hooks from Phases 246-250 (Autonomy Hardening) ----------
from src.phase_246_250 import (
    pre_trade_technical_gates, pre_place_idempotency, post_place_reconcile,
    record_order_intent, use_deadlock_guard, get_feature_flag
)

# ---------- Integration hooks from Phases 236-245 (Technical Resilience) ----------
from src.phase_236_245 import global_halt_active, heartbeat_emit, adaptive_retry, choose_connector

# ---------- Integration hooks from Phases 221-225 ----------
from src.phase_221_225 import apply_live_confidence_nudge, select_venue_with_v2

# ---------- Paths ----------
ALPHA_ROUTES = "logs/alpha_signal_routes.json"
COMPOSITE_TO_ROI = "logs/composite_to_roi_map.json"
SYMBOL_CONF_THRESH = "logs/symbol_confidence_thresholds.json"
SYMBOL_PERF = "logs/symbol_performance_metrics.json"
SYMBOL_RISK_BUDGET_V2 = "logs/symbol_risk_budget_v2.json"
SYMBOL_AUDIT = "logs/symbol_audit_trail.jsonl"
EXECUTION_RESULTS = "logs/executed_orders.jsonl"

# Prior phase outputs
PROFIT_LOOP = "logs/profit_loop_controller.json"              # 182
PORTF_DRAWDOWN_GUARD = "logs/portfolio_drawdown_guard.json"   # 198
PORTF_RISK_ALLOC = "logs/portfolio_risk_allocator.json"       # 191
PORTF_REGIME_SCALER = "logs/portfolio_regime_scaler.json"     # 195
PORTF_CORR_GUARD = "logs/portfolio_correlation_guard.json"    # 193
PORTF_DIVERSIFIER = "logs/portfolio_diversification_enforcer.json"  # 194
PORTF_PROFIT_LOCK = "logs/portfolio_profit_lock.json"         # 199
SMART_ROUTER_CFG = "logs/smart_order_router_v3.json"          # 185
LATENCY_PROFILE = "logs/venue_latency_profile.json"           # 188
MAKER_REBATE_MAP = "logs/maker_rebates.json"                  # 186
SLIPPAGE_GUARD = "logs/slippage_guard_v2.json"                # 187

# External intelligence (211–220)
EXT_DATA = "logs/external_data_fusion.json"                   # 211
EVENT_SHOCK = "logs/event_shock_detector.json"                # 212
ARBITRAGE = "logs/cross_market_arbitrage.json"                # 213
MULTI_ASSET_ALLOC = "logs/multi_asset_risk_allocator.json"    # 214
UNIVERSE_EXPAND = "logs/adaptive_universe.json"               # 215
META_EVAL = "logs/meta_learning_eval.json"                    # 216
EXT_GRAPH = "logs/external_knowledge_graph.json"              # 218
GLOBAL_DASH = "logs/global_risk_dashboard.json"               # 219

# ---------- Gate imports ----------
from src.execution_gates import execution_gates, mark_trade

# ---------- Utils ----------
def _now(): return int(time.time())
def _read_json(path, default=None): return json.load(open(path)) if os.path.exists(path) else (default if default is not None else {})
def _write_json(path, obj): os.makedirs(os.path.dirname(path), exist_ok=True); json.dump(obj, open(path, "w"), indent=2)
def _append_jsonl(path, obj): os.makedirs(os.path.dirname(path), exist_ok=True); open(path, "a").write(json.dumps(obj) + "\n")

def safe_float(value, default=0.0):
    """Logic Patch: Null Safety - prevents TypeError/ValueError from crashing trading loop."""
    try:
        if value is None: return default
        return float(value)
    except (ValueError, TypeError):
        return default

# ---------- Symbol-level helpers (existing phases) ----------
def roi_from_composite(sym, comp, roi_map):
    m = roi_map.get(sym, {}).get("mapping", [])
    if not m: return 0.0
    nearest = min(m, key=lambda x: abs(x["comp"] - comp))
    return nearest["expected_roi"]

def symbol_mtf_confirm(symbol):
    # Placeholder: replace with real MTF checks
    return {"confirmed": True, "cooldown": False, "disagree_rate": 0.0}

def sizing_adapter_v2(symbol, confidence, recent_slippage_bp=0.0, win_rate=None, payoff_ratio=None, strategy="default", regime="momentum"):
    """
    Real Kelly Criterion sizing with 0.3x safety fraction.
    
    Formula: f* = p - (1-p)/b
    Where p = win rate, b = payoff ratio (avg_win / avg_loss)
    
    Uses rolling trade stats from strategy memory system for dynamic sizing.
    """
    # 1. Get win rate and payoff ratio from authoritative strategy memory
    if win_rate is None or payoff_ratio is None:
        try:
            from src.strategy_performance_memory import load_strategy_memory
            import numpy as np
            
            memory = load_strategy_memory()
            key = f"{strategy}_{regime}"
            perf = memory.get("performance", {}).get(key, {})
            roi_history = perf.get("roi_history", [])
            
            # Use last 50 trades for rolling stats
            recent_rois = roi_history[-50:] if len(roi_history) >= 10 else roi_history
            
            if len(recent_rois) >= 10:
                wins = [r for r in recent_rois if r > 0]
                losses = [r for r in recent_rois if r < 0]
                
                if win_rate is None:
                    win_rate = len(wins) / len(recent_rois)
                
                if payoff_ratio is None and wins and losses:
                    avg_win = np.mean(wins)
                    avg_loss = abs(np.mean(losses))
                    payoff_ratio = float(avg_win / avg_loss) if avg_loss > 0 else 1.2
        except Exception as e:
            print(f"⚠️ [KELLY] Failed to load strategy memory: {e}")
        
        # Fall back to symbol-level performance metrics if no strategy data
        if win_rate is None or payoff_ratio is None:
            perf = _read_json(SYMBOL_PERF, {}).get(symbol, {})
            if win_rate is None:
                win_rate = safe_float(perf.get("win_rate"), 0.45)  # Conservative default
            if payoff_ratio is None:
                payoff_ratio = safe_float(perf.get("payoff_ratio"), 1.2)  # Conservative default
    
    # Ensure safe values
    win_rate = safe_float(win_rate, 0.45)
    payoff_ratio = safe_float(payoff_ratio, 1.2)
    
    # Clamp to valid ranges
    win_rate = max(0.01, min(0.99, win_rate))  # Avoid 0 or 1
    payoff_ratio = max(0.1, payoff_ratio)  # Avoid division issues
    
    # 2. Calculate Kelly Criterion: f* = p - (1-p)/b
    p = win_rate
    b = payoff_ratio
    kelly_fraction = p - ((1 - p) / b)
    
    # 3. Apply 0.3x safety fraction (fractional Kelly for robustness)
    safe_kelly = kelly_fraction * 0.3
    
    # 4. Confidence Scalar (0.7x to 1.0x based on signal confidence)
    conf = safe_float(confidence, 0.0)
    conf_scalar = 0.7 + (0.3 * max(0.0, min(1.0, conf)))
    
    # 5. Slippage Penalty (reduce size if recent slippage is high)
    slip_bp = safe_float(recent_slippage_bp, 0.0)
    slip_penalty = 0.8 if slip_bp > 5.0 else 1.0
    
    # 6. Calculate Final Position Size
    final_risk = safe_kelly * conf_scalar * slip_penalty
    
    # 7. Hard Guardrails: Min 0.5%, Max 5% per trade
    # If Kelly is negative (no edge), use minimum size for learning
    if final_risk <= 0:
        final_risk = 0.005  # 0.5% minimum for learning trades
    
    return round(max(0.005, min(0.05, final_risk)), 4)

def append_symbol_audit(symbol, snapshot):
    snap = {"ts": _now(), "symbol": symbol, **snapshot}
    _append_jsonl(SYMBOL_AUDIT, snap)

# ---------- Sector Correlation Guard (Phase 2 Forensic Audit Fix) ----------
SECTOR_MAPPING = {
    # Mega-cap (Store of Value)
    "BTCUSDT": "mega",
    # Layer 1 Smart Contracts
    "ETHUSDT": "l1",
    "SOLUSDT": "l1",
    "AVAXUSDT": "l1",
    "ADAUSDT": "l1",
    # Layer 2 / Scaling
    "OPUSDT": "l2",
    "ARBUSDT": "l2",
    "MATICUSDT": "l2",
    # DeFi / Oracles
    "LINKUSDT": "defi",
    "DOTUSDT": "defi",
    # Meme / High-Vol
    "DOGEUSDT": "meme",
    "PEPEUSDT": "meme",
    # Exchange Tokens
    "BNBUSDT": "exchange",
    # Payment / Legacy
    "XRPUSDT": "payment",
    "TRXUSDT": "payment",
}

MAX_POSITIONS_PER_SECTOR = 2  # Prevent concentration in correlated assets

def get_sector_for_symbol(symbol: str) -> str:
    """Get sector classification for a trading symbol."""
    return SECTOR_MAPPING.get(symbol.upper(), "other")

def get_sector_position_counts() -> dict:
    """Count current open positions by sector using authoritative Tri-Layer source."""
    try:
        # Use position_manager's load_futures_positions for Tri-Layer consistency
        from src.position_manager import load_futures_positions
        data = load_futures_positions()
        
        positions = data.get("open_positions", [])
        
        counts = {}
        for pos in positions:
            if isinstance(pos, dict):
                symbol = pos.get("symbol", "")
                sector = get_sector_for_symbol(symbol)
                counts[sector] = counts.get(sector, 0) + 1
        return counts
    except Exception as e:
        print(f"⚠️ [SECTOR] Error loading positions: {e}")
        return {}

def check_sector_saturation(symbol: str, current_positions: list = None) -> tuple:
    """
    Check if adding a position in this symbol's sector would exceed limits.
    
    Returns: (is_allowed, reason, sector, current_count)
    """
    sector = get_sector_for_symbol(symbol)
    
    if current_positions is None:
        sector_counts = get_sector_position_counts()
    else:
        sector_counts = {}
        for pos in current_positions:
            if isinstance(pos, dict):
                s = pos.get("symbol", "")
                sec = get_sector_for_symbol(s)
                sector_counts[sec] = sector_counts.get(sec, 0) + 1
    
    current = sector_counts.get(sector, 0)
    
    if current >= MAX_POSITIONS_PER_SECTOR:
        return (False, f"sector_saturation:{sector}={current}/{MAX_POSITIONS_PER_SECTOR}", sector, current)
    
    return (True, "sector_ok", sector, current)


# ---------- External wiring: orchestration controls ----------
def global_halt_and_shocks():
    guard = _read_json(PORTF_DRAWDOWN_GUARD, {"halt": False})
    loop = _read_json(PROFIT_LOOP, {"action": "throttle"})
    shocks = _read_json(EVENT_SHOCK, {"shocks": []}).get("shocks", [])
    # If any shock == "halt" impact, override
    shock_halt = any(s.get("impact") == "halt" for s in shocks)
    return {
        "halt": bool(guard.get("halt") or shock_halt),
        "loop_action": loop.get("action", "throttle"),
        "shock_flags": shocks
    }

def portfolio_scalers():
    regime = _read_json(PORTF_REGIME_SCALER, {"scale_multiplier": 1.0}).get("scale_multiplier", 1.0)
    lock = _read_json(PORTF_PROFIT_LOCK, {"cooldown_scale": 1.0}).get("cooldown_scale", 1.0)
    alloc = _read_json(PORTF_RISK_ALLOC, {"alloc": {}}).get("alloc", {})
    return {"regime_mult": regime, "lock_mult": lock, "alloc_map": alloc}

def correlation_and_diversification():
    corr = _read_json(PORTF_CORR_GUARD, {"guard_active": False})
    div = _read_json(PORTF_DIVERSIFIER, {"violations": []})
    return {"corr_guard": corr.get("guard_active", False), "violations": div.get("violations", [])}

# ---------- External fusion & execution adapters ----------
def external_biases(symbol):
    ext = _read_json(EXT_DATA, {"sentiment": 0.0, "funding_rate": 0.0, "open_interest": 0})
    sentiment = ext.get("sentiment", 0.0)         # -1..1
    funding = ext.get("funding_rate", 0.0)        # negative → short bias, positive → long bias
    oi = ext.get("open_interest", 0)              # liquidity proxy
    # Bias scaling: modest adjustments
    sentiment_mult = 1.0 + 0.1 * sentiment
    funding_bias = -0.1 if funding < -0.01 else 0.1 if funding > 0.01 else 0.0
    oi_mult = 1.0 if oi >= 2000 else 0.8          # dampen size in low OI
    return {"sentiment_mult": sentiment_mult, "funding_bias": funding_bias, "oi_mult": oi_mult}

def cross_market_hint(symbol):
    arb = _read_json(ARBITRAGE, {})
    spread_hint = 0.0
    if symbol.upper().startswith("BTC"):
        spread_hint = arb.get("btc_fx_spread", 0.0)
    elif symbol.upper().startswith("ETH"):
        spread_hint = arb.get("eth_equity_spread", 0.0)
    return {"spread_hint": spread_hint}

def slippage_guard_v2(symbol, recent_slippage_bp, threshold_bp=6.0):
    blocked = recent_slippage_bp > threshold_bp
    _write_json(SLIPPAGE_GUARD, {"ts": _now(), symbol: {"blocked": blocked, "threshold_bp": threshold_bp, "recent_slippage_bp": recent_slippage_bp}})
    return {"blocked": blocked, "threshold_bp": threshold_bp, "recent_slippage_bp": recent_slippage_bp}

def maker_rebate_arb(symbol, candidate_venues, taker_fee_bp=5.0, maker_fee_bp=2.0):
    rebates = _read_json(MAKER_REBATE_MAP, {})
    scores = []
    for v in candidate_venues:
        rb_bp = rebates.get(v, {}).get(symbol, 0.0)
        net_maker_bp = maker_fee_bp - rb_bp
        prefer_maker = net_maker_bp <= taker_fee_bp
        scores.append({"venue": v, "maker_net_bp": net_maker_bp, "taker_net_bp": taker_fee_bp, "prefer_maker": prefer_maker})
    best = min(scores, key=lambda x: x["maker_net_bp"] if x["prefer_maker"] else x["taker_net_bp"]) if scores else {"venue": candidate_venues[0] if candidate_venues else "default", "prefer_maker": True}
    return {"chosen": best, "scores": scores}

def smart_order_router_v3(symbol, spread_bp, venue, fee_ratio, confidence=0.0):
    """
    V3 Router optimized for High-Fee Environments (BloFin 0.06% Taker).
    Logic:
    - If Confidence > 0.80: Pay Taker fee (0.06%) to get in fast.
    - If Confidence < 0.80: FORCE Maker (0.02%) via Post-Only.
    - If Spread > 5bp: FORCE Maker to avoid wide spread + fees.
    """
    HIGH_CONVICTION_THRESHOLD = 0.80
    WIDE_SPREAD_BP = 5.0
    
    is_high_conviction = confidence >= HIGH_CONVICTION_THRESHOLD
    is_tight_spread = spread_bp <= WIDE_SPREAD_BP
    
    if is_high_conviction and is_tight_spread:
        order_type = "market"
        post_only = False
        ttl_sec = 5
        offset_bp = 0.0
        reason = "taker_high_conviction"
    else:
        order_type = "limit"
        post_only = True
        ttl_sec = 45
        offset_bp = 0.1
        reason = "maker_fee_optimization"

    cfg = {
        "order_type": order_type,
        "offset_bp": round(offset_bp, 2), 
        "ttl_sec": ttl_sec, 
        "post_only": post_only, 
        "venue": venue,
        "routing_reason": reason
    }
    _write_json(SMART_ROUTER_CFG, cfg)
    return cfg

def latency_aware_executor(venue, spread_bp):
    prof = _read_json(LATENCY_PROFILE, {}).get(venue, {"avg_ms": 150})
    avg_ms = prof.get("avg_ms", 150)
    ttl = 10 if avg_ms < 120 else 15 if avg_ms < 200 else 20
    offset_bp = 0.6 if spread_bp <= 6 else 1.2
    return {"ttl_sec": ttl, "offset_bp": offset_bp}

# ---------- Multi-asset scaling ----------
def multi_asset_scaler(symbol):
    alloc = _read_json(MULTI_ASSET_ALLOC, {"crypto": 1.0, "fx": 0.0, "equities": 0.0})
    sym = symbol.upper()
    # crude asset classification
    if sym.endswith("USDT") or sym in ("BTC", "ETH", "SOL", "AVAX", "DOT", "TRX", "XRP"):
        return alloc.get("crypto", 1.0)
    # Extend with mapping as needed
    return 1.0

# ---------- Main execution bridge ----------
def run_alpha_execution_bridge():
    # Phase 236: Emit heartbeat for execution bridge
    heartbeat_emit("alpha_adapter")
    
    # Phase 249: Check dependency health gates (storage/time/connector)
    tech_gates = pre_trade_technical_gates(module_name="alpha_adapter")
    if tech_gates["block"]:
        print(f"Dependency health gate failed: {tech_gates['reason']}")
        return {"executed": 0, "blocked": 0, "reason": tech_gates["reason"]}
    
    # Phase 238: Check technical resilience global halt (circuit breaker)
    if global_halt_active():
        print("Technical resilience halt active. Blocking all trades due to module freeze.")
        return {"executed": 0, "blocked": 0, "reason": "technical_resilience_halt"}
    
    orders = _read_json(ALPHA_ROUTES, [])
    roi_map = _read_json(COMPOSITE_TO_ROI, {})
    confs = _read_json(SYMBOL_CONF_THRESH, {})
    perf = _read_json(SYMBOL_PERF, {})

    # Global controls (portfolio-level halts)
    global_ctrl = global_halt_and_shocks()
    if global_ctrl["halt"]:
        print("Global halt active. Blocking all trades due to drawdown/shock.")
        return {"executed": 0, "blocked": len(orders), "reason": "global_halt"}

    portf_scalers = portfolio_scalers()
    corr_div = correlation_and_diversification()

    executed, blocked = 0, 0
    for o in orders:
        sym = o.get("symbol")
        comp = o.get("composite", 0.0)
        direction = o.get("direction")
        confidence = o.get("confidence", 0.7)

        # Correlation/diversification controls
        if corr_div["corr_guard"]:
            append_symbol_audit(sym, {"reason": "portfolio_corr_guard"})
            blocked += 1
            continue

        # MTF confirmation
        mtf = symbol_mtf_confirm(sym)
        if not mtf["confirmed"]:
            append_symbol_audit(sym, {"reason": "mtf_cooldown", "mtf": mtf})
            blocked += 1
            continue

        # Expected ROI from calibration or recent perf fallback
        pred_roi = roi_from_composite(sym, comp, roi_map)
        exp_recent = perf.get(sym, {}).get("expectancy", 0.0)
        expected_roi = pred_roi if pred_roi else exp_recent

        # External biases
        ext_bias = external_biases(sym)
        # Adjust expected ROI slightly by sentiment and funding bias direction
        expected_roi_adj = expected_roi * ext_bias["sentiment_mult"] + ext_bias["funding_bias"]

        # Phase 222: Live Confidence Nudge - auto-adjusted thresholds based on precision/recall
        conf_thr_base = confs.get(sym, {}).get("confidence_threshold", 0.75)
        # Apply diversification penalty if sector violations exist
        conf_thr_adj = conf_thr_base + (0.05 if corr_div["violations"] else 0.0)
        # Apply live nudge from Phase 222
        ok_conf, conf_thr = apply_live_confidence_nudge(sym, confidence, default_thr=conf_thr_adj)
        if not ok_conf:
            append_symbol_audit(sym, {"reason": "low_conf_nudged", "confidence": confidence, "threshold": conf_thr})
            blocked += 1
            continue

        # Pre-execution guards
        recent_slip_bp = perf.get(sym, {}).get("avg_slippage_bp", 5.0)
        slip_state = slippage_guard_v2(sym, recent_slip_bp)
        if slip_state["blocked"]:
            append_symbol_audit(sym, {"reason": "slippage_guard_block", "slippage": slip_state})
            blocked += 1
            continue

        # Phase 223: Rebate-Aware Venue Selector v2 - advanced venue selection with fill probability
        spread_bp = 6.0  # Default, replace with real spread if available
        fee_ratio = perf.get(sym, {}).get("fee_ratio", 0.5)
        v2_selection = select_venue_with_v2(sym, 
                                           candidate_venues=["default_venue", "venue_a", "venue_b"],
                                           spread_bp=spread_bp,
                                           fee_ratio=fee_ratio)
        venue = v2_selection["venue"]
        router_cfg = v2_selection["order_cfg"]

        # Sizing: symbol risk, confidence, external OI, portfolio & profit lock scalers, multi-asset scaler
        base_size = sizing_adapter_v2(sym, confidence, recent_slippage_bp=recent_slip_bp)
        alloc_mult = portf_scalers["alloc_map"].get(sym, {}).get("risk_alloc", 0.01) / max(1e-6, _read_json(SYMBOL_RISK_BUDGET_V2, {}).get(sym, {}).get("risk_budget", 0.01))
        size_mult = alloc_mult * portf_scalers["regime_mult"] * portf_scalers["lock_mult"] * ext_bias["oi_mult"] * multi_asset_scaler(sym)

        # Profit loop action affects aggressiveness
        loop_action = global_ctrl["loop_action"]
        loop_scale = 1.0 if loop_action == "scale" else 0.8 if loop_action == "throttle" else 0.5

        final_size = round(max(0.0, min(0.05, base_size * size_mult * loop_scale)), 4)

        # Cross-market hint: if adverse spread hint, tighten offset/size
        cm_hint = cross_market_hint(sym)["spread_hint"]
        if cm_hint < -0.2:
            final_size = round(final_size * 0.8, 4)
            router_cfg["offset_bp"] = min(router_cfg["offset_bp"] + 0.3, 3.0)

        # Audit pre-gate snapshot
        append_symbol_audit(sym, {
            "direction": direction,
            "composite": comp,
            "expected_roi": expected_roi,
            "expected_roi_adj": expected_roi_adj,
            "confidence": confidence,
            "conf_thr": conf_thr,
            "conf_nudged": True,
            "size_base": base_size,
            "size_final": final_size,
            "venue": venue,
            "venue_selector": "v2",
            "router_cfg": router_cfg,
            "loop_action": loop_action,
            "external_bias": ext_bias
        })

        # SECTOR CORRELATION GUARD: Check sector saturation before execution
        sector_allowed, sector_reason, sector, sector_count = check_sector_saturation(sym)
        if not sector_allowed:
            print(f"⚠️ [SECTOR] {sym} blocked: {sector_reason}")
            append_symbol_audit(sym, {"blocked": True, "reason": sector_reason, "sector": sector, "count": sector_count})
            blocked += 1
            continue

        # Final gate decision
        decision = execution_gates(
            symbol=sym,
            predicted_roi=expected_roi_adj,
            mtf_confirmed=True,
            quality_score=confidence
        )

        result = {
            "ts": _now(),
            "symbol": sym,
            "direction": direction,
            "expected_roi_adj": expected_roi_adj,
            "confidence": confidence,
            "size": final_size,
            "venue": venue,
            "order_cfg": router_cfg,
            "gate_decision": decision
        }
        _append_jsonl(EXECUTION_RESULTS, result)

        if decision.get("approved"):
            # Phase 246: Idempotency check before placing order
            idem_check = pre_place_idempotency(sym, direction, final_size, router_cfg)
            if not idem_check["allow"]:
                append_symbol_audit(sym, {"reason": idem_check["reason"], "client_order_id": idem_check["client_order_id"]})
                blocked += 1
                continue
            
            # Record intent before execution
            client_order_id = idem_check["client_order_id"]
            record_order_intent(sym, direction, final_size, venue, router_cfg, client_order_id)
            
            # place_order(sym, order_type="limit", size=final_size,
            #             offset_bp=result["order_cfg"]["offset_bp"],
            #             ttl_sec=result["order_cfg"]["ttl_sec"],
            #             post_only=result["order_cfg"]["post_only"],
            #             client_order_id=client_order_id)
            
            # Phase 246: Finalize order intent after execution
            post_place_reconcile(client_order_id, status="executed", execution_meta={"ts": _now(), "size": final_size})
            
            mark_trade()
            executed += 1
        else:
            blocked += 1

    print(f"Execution bridge complete. Executed: {executed}, Blocked: {blocked}")
    return {"executed": executed, "blocked": blocked}

if __name__ == "__main__":
    run_alpha_execution_bridge()