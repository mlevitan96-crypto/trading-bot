# src/phase_191_200.py
#
# Phases 191–200: Portfolio-Level Orchestration
# - 191: Portfolio Risk Allocator
# - 192: Portfolio Exposure Balancer
# - 193: Correlation Guard
# - 194: Diversification Enforcer
# - 195: Regime-Aware Portfolio Scaler
# - 196: Portfolio Attribution Engine
# - 197: Cross-Symbol Experiment Harness
# - 198: Portfolio Drawdown Guard
# - 199: Portfolio Profit Lock
# - 200: Portfolio Operator Dashboard + Orchestrator
#
# Purpose:
# Elevate the system from symbol-level optimization to full portfolio intelligence:
# risk distribution, correlation control, diversification, regime scaling, attribution,
# experiments, global drawdown guard, profit locks, and unified operator visibility.

import os, json, time, math
from statistics import mean, stdev

# ---- Paths (inputs/outputs) ----
TRADES_LOG = "logs/trades_futures.json"                   # { "history": [ {symbol, roi, fees, ts, sector, regime, size_pct, ...} ] }
SYMBOL_PERF = "logs/symbol_performance_metrics.json"      # per-symbol win_rate, expectancy, drawdown, fee_ratio
SYMBOL_CONF_THRESH = "logs/symbol_confidence_thresholds.json"
SYMBOL_RISK_BUDGET_V2 = "logs/symbol_risk_budget_v2.json" # per-symbol base risk budget
REGIME_FORECAST = "logs/regime_forecast.json"             # {"predicted_regime": "...", "confidence": 0.0..1.0}
CORRELATION_MATRIX = "logs/correlation_matrix.json"       # optional: {"symbols": [...], "matrix": [[...], ...]}
SECTOR_MAP = "logs/symbol_sector_map.json"                # {"BTC": "Layer1", "ETH": "Layer1", "DOGE": "Meme", ...}

PORTF_RISK_ALLOC = "logs/portfolio_risk_allocator.json"
PORTF_EXPOSURE_BAL = "logs/portfolio_exposure_balancer.json"
PORTF_CORR_GUARD = "logs/portfolio_correlation_guard.json"
PORTF_DIVERSIFIER = "logs/portfolio_diversification_enforcer.json"
PORTF_REGIME_SCALER = "logs/portfolio_regime_scaler.json"
PORTF_ATTRIB = "logs/portfolio_attribution.json"
PORTF_EXPERIMENTS = "logs/portfolio_experiments.json"
PORTF_DRAWDOWN_GUARD = "logs/portfolio_drawdown_guard.json"
PORTF_PROFIT_LOCK = "logs/portfolio_profit_lock.json"
PORTF_DASH = "logs/portfolio_operator_dashboard.json"
PORTF_ORCH = "logs/portfolio_orchestrator_191_200.json"

def _now(): return int(time.time())
def _read_json(path, default=None): return json.load(open(path)) if os.path.exists(path) else (default if default is not None else {})
def _write_json(path, obj): os.makedirs(os.path.dirname(path), exist_ok=True); json.dump(obj, open(path, "w"), indent=2)

# ======================================================================
# 191 – Portfolio Risk Allocator
# Distribute total risk across symbols using expectancy, volatility, confidence.
# ======================================================================
def portfolio_risk_allocator(total_risk=0.2):
    perf = _read_json(SYMBOL_PERF, {})
    confs = _read_json(SYMBOL_CONF_THRESH, {})
    base = _read_json(SYMBOL_RISK_BUDGET_V2, {})
    # score per symbol: expectancy * confidence_weight / volatility proxy
    scores = {}
    for sym, p in perf.items():
        exp = p.get("expectancy", 0.0)
        dd_proxy = abs(p.get("drawdown", 0.01)) + 1e-6
        conf_thr = confs.get(sym, {}).get("confidence_threshold", 0.7)
        base_budget = base.get(sym, {}).get("risk_budget", 0.01)
        score = max(0.0, exp) * (0.6 + 0.4 * (1.0 - abs(0.75 - conf_thr))) / dd_proxy
        scores[sym] = {"score": score, "base": base_budget}
    total_score = sum(v["score"] for v in scores.values()) or 1.0
    alloc = {}
    for sym, v in scores.items():
        weight = v["score"] / total_score
        alloc[sym] = {"risk_alloc": round(min(0.05, v["base"] + total_risk * weight), 4), "weight": round(weight, 4)}
    _write_json(PORTF_RISK_ALLOC, {"ts": _now(), "total_risk": total_risk, "alloc": alloc})
    return alloc

# ======================================================================
# 192 – Portfolio Exposure Balancer
# Keeps total long/short exposure within limits, scales per-symbol sizes.
# ======================================================================
def portfolio_exposure_balancer(max_total_exposure=0.6, long_bias_cap=0.7):
    trades = _read_json(TRADES_LOG, {"history": []}).get("history", [])
    # approximate current exposure by sum of size_pct per symbol (latest entries)
    latest_by_sym = {}
    for t in trades[-2000:]:
        latest_by_sym[t.get("symbol")] = t
    total_exposure = sum(abs(latest_by_sym[s].get("size_pct", 0.0)) for s in latest_by_sym)
    long_exposure = sum(latest_by_sym[s].get("size_pct", 0.0) for s in latest_by_sym if latest_by_sym[s].get("direction") == "BUY")
    long_bias = long_exposure / max(1e-6, total_exposure) if total_exposure else 0.5
    scale = min(1.0, max_total_exposure / max(1e-6, total_exposure)) if total_exposure > max_total_exposure else 1.0
    bias_adj = 1.0 if long_bias <= long_bias_cap else (long_bias_cap / long_bias)
    result = {"ts": _now(), "total_exposure": round(total_exposure, 4), "long_bias": round(long_bias, 4), "scale": round(scale, 3), "bias_adjustment": round(bias_adj, 3)}
    _write_json(PORTF_EXPOSURE_BAL, result)
    return result

# ======================================================================
# 193 – Correlation Guard
# Blocks new trades that would push portfolio correlation above threshold.
# ======================================================================
def portfolio_correlation_guard(max_corr=0.7):
    cm = _read_json(CORRELATION_MATRIX, {})
    symbols = cm.get("symbols", [])
    matrix = cm.get("matrix", [])
    # Compute average off-diagonal correlation among active symbols
    n = len(symbols)
    avg_corr = 0.0; pairs = 0
    if matrix and n > 1:
        for i in range(n):
            for j in range(i+1, n):
                avg_corr += abs(matrix[i][j]); pairs += 1
        avg_corr = avg_corr / pairs if pairs else 0.0
    decision = {"ts": _now(), "avg_corr": round(avg_corr, 3), "guard_active": avg_corr > max_corr, "threshold": max_corr}
    _write_json(PORTF_CORR_GUARD, decision)
    return decision

# ======================================================================
# 194 – Diversification Enforcer
# Ensures minimum diversification across sectors or signal families.
# ======================================================================
def diversification_enforcer(min_sectors=3, max_sector_share=0.5):
    sector_map = _read_json(SECTOR_MAP, {})
    trades = _read_json(TRADES_LOG, {"history": []}).get("history", [])
    latest_by_sym = {}
    for t in trades[-2000:]:
        latest_by_sym[t.get("symbol")] = t
    sector_exposure = {}
    total = 0.0
    for sym, t in latest_by_sym.items():
        sector = sector_map.get(sym, "Unknown")
        size = abs(t.get("size_pct", 0.0))
        sector_exposure[sector] = sector_exposure.get(sector, 0.0) + size
        total += size
    sectors_count = len([s for s, val in sector_exposure.items() if val > 0])
    shares = {s: (v / max(1e-6, total)) for s, v in sector_exposure.items()}
    violations = [s for s, sh in shares.items() if sh > max_sector_share]
    result = {"ts": _now(), "sectors_count": sectors_count, "shares": {k: round(v, 3) for k, v in shares.items()}, "violations": violations, "min_sectors": min_sectors}
    _write_json(PORTF_DIVERSIFIER, result)
    return result

# ======================================================================
# 195 – Regime-Aware Portfolio Scaler
# Scales portfolio risk based on predicted regime.
# ======================================================================
def regime_aware_portfolio_scaler():
    fc = _read_json(REGIME_FORECAST, {"predicted_regime": "mixed", "confidence": 0.5})
    regime = fc.get("predicted_regime", "mixed"); conf = fc.get("confidence", 0.5)
    # Policy: trending -> scale up; volatile/choppy -> scale down; mixed -> neutral
    if regime == "trending":
        mult = 1.0 + 0.3 * conf
    elif regime in ("volatile", "choppy"):
        mult = 1.0 - 0.3 * conf
    else:
        mult = 1.0
    result = {"ts": _now(), "regime": regime, "confidence": conf, "scale_multiplier": round(mult, 3)}
    _write_json(PORTF_REGIME_SCALER, result)
    return result

# ======================================================================
# 196 – Portfolio Attribution Engine
# Aggregates PnL by symbol, sector, and signal family (if available).
# ======================================================================
def portfolio_attribution_engine():
    trades = _read_json(TRADES_LOG, {"history": []}).get("history", [])
    sector_map = _read_json(SECTOR_MAP, {})
    by_sym, by_sector = {}, {}
    total = {"pnl_net": 0.0, "fees": 0.0}
    for t in trades[-5000:]:
        sym = t.get("symbol")
        pnl = t.get("roi", 0.0) - t.get("fees", 0.0)
        sector = sector_map.get(sym, "Unknown")
        by_sym.setdefault(sym, {"pnl_net": 0.0, "fees": 0.0, "n": 0})
        by_sym[sym]["pnl_net"] += pnl; by_sym[sym]["fees"] += t.get("fees", 0.0); by_sym[sym]["n"] += 1
        by_sector.setdefault(sector, {"pnl_net": 0.0, "fees": 0.0, "n": 0})
        by_sector[sector]["pnl_net"] += pnl; by_sector[sector]["fees"] += t.get("fees", 0.0); by_sector[sector]["n"] += 1
        total["pnl_net"] += pnl; total["fees"] += t.get("fees", 0.0)
    result = {"ts": _now(), "by_symbol": by_sym, "by_sector": by_sector, "total": total}
    _write_json(PORTF_ATTRIB, result)
    return result

# ======================================================================
# 197 – Cross-Symbol Experiment Harness
# Runs A/B by symbol groups (e.g., sectors), measures lift and stability.
# ======================================================================
def cross_symbol_experiment_harness():
    attrib = _read_json(PORTF_ATTRIB, {"by_symbol": {}, "by_sector": {}})
    by_sector = attrib.get("by_sector", {})
    lifts = {}
    # naive lift: sector pnl per trade vs overall average
    total_n = sum(s.get("n", 0) for s in by_sector.values()) or 1
    total_avg = sum(s.get("pnl_net", 0.0) for s in by_sector.values()) / total_n
    for sec, rec in by_sector.items():
        sec_avg = (rec.get("pnl_net", 0.0) / max(1, rec.get("n", 1)))
        lift = sec_avg - total_avg
        lifts[sec] = {"avg_per_trade": round(sec_avg, 6), "lift_vs_total": round(lift, 6), "promote": (lift > 0.005 and rec.get("n", 0) >= 50)}
    _write_json(PORTF_EXPERIMENTS, {"ts": _now(), "sector_lifts": lifts})
    return lifts

# ======================================================================
# 198 – Portfolio Drawdown Guard
# Halts trading if global drawdown exceeds threshold.
# ======================================================================
def portfolio_drawdown_guard(max_drawdown=-0.05):
    trades = _read_json(TRADES_LOG, {"history": []}).get("history", [])
    # approximate drawdown as min rolling net pnl over last N trades
    pnl_list = [t.get("roi", 0.0) - t.get("fees", 0.0) for t in trades[-2000:]]
    dd = min(sum(pnl_list[max(0, i-50):i]) for i in range(1, len(pnl_list)+1)) if pnl_list else 0.0
    guard = {"ts": _now(), "rolling_dd": round(dd, 6), "halt": (dd <= max_drawdown), "threshold": max_drawdown}
    _write_json(PORTF_DRAWDOWN_GUARD, guard)
    return guard

# ======================================================================
# 199 – Portfolio Profit Lock
# Lock gains once daily/weekly target hit; scale down risk temporarily.
# ======================================================================
def portfolio_profit_lock(daily_target=0.01, cooldown_scale=0.7):
    trades = _read_json(TRADES_LOG, {"history": []}).get("history", [])
    today = time.strftime("%Y-%m-%d", time.localtime(_now()))
    day_pnl = sum((t.get("roi", 0.0) - t.get("fees", 0.0)) for t in trades if time.strftime("%Y-%m-%d", time.localtime(t.get("ts", _now()))) == today)
    lock = {"ts": _now(), "day_pnl": round(day_pnl, 6), "locked": (day_pnl >= daily_target), "cooldown_scale": cooldown_scale if day_pnl >= daily_target else 1.0, "target": daily_target}
    _write_json(PORTF_PROFIT_LOCK, lock)
    return lock

# ======================================================================
# 200 – Portfolio Operator Dashboard + Orchestrator
# Unified portfolio view + nightly orchestration.
# ======================================================================
def portfolio_operator_dashboard():
    dash = {
        "ts": _now(),
        "risk_alloc": _read_json(PORTF_RISK_ALLOC, {}),
        "exposure_bal": _read_json(PORTF_EXPOSURE_BAL, {}),
        "corr_guard": _read_json(PORTF_CORR_GUARD, {}),
        "diversifier": _read_json(PORTF_DIVERSIFIER, {}),
        "regime_scaler": _read_json(PORTF_REGIME_SCALER, {}),
        "attrib": _read_json(PORTF_ATTRIB, {}),
        "experiments": _read_json(PORTF_EXPERIMENTS, {}),
        "drawdown_guard": _read_json(PORTF_DRAWDOWN_GUARD, {}),
        "profit_lock": _read_json(PORTF_PROFIT_LOCK, {}),
    }
    _write_json(PORTF_DASH, dash)
    return dash

def run_portfolio_orchestrator_191_200():
    alloc = portfolio_risk_allocator(total_risk=0.2)
    expo = portfolio_exposure_balancer(max_total_exposure=0.6, long_bias_cap=0.7)
    corr = portfolio_correlation_guard(max_corr=0.7)
    div = diversification_enforcer(min_sectors=3, max_sector_share=0.5)
    regime = regime_aware_portfolio_scaler()
    attrib = portfolio_attribution_engine()
    lifts = cross_symbol_experiment_harness()
    guard = portfolio_drawdown_guard(max_drawdown=-0.05)
    lock = portfolio_profit_lock(daily_target=0.01, cooldown_scale=0.7)
    dash = portfolio_operator_dashboard()
    summary = {
        "ts": _now(),
        "symbols_allocated": len(alloc),
        "exposure": expo,
        "avg_corr": corr.get("avg_corr"),
        "sectors": len(div.get("shares", {})),
        "regime_scale": regime.get("scale_multiplier"),
        "halt": guard.get("halt"),
        "profit_locked": lock.get("locked"),
    }
    _write_json(PORTF_ORCH, summary)
    print("Portfolio orchestrator (191–200) completed. Summary:", summary)
    return summary

# ---- Integration hooks (use inside alpha_to_execution_adapter / execution layer) ----
# Example usage at decision time:
# 1) Check global halts and correlation/diversification guards before placing new orders.
# guard = _read_json(PORTF_DRAWDOWN_GUARD, {"halt": False})
# if guard.get("halt"): skip all new trades
# corr = _read_json(PORTF_CORR_GUARD, {"guard_active": False})
# div = _read_json(PORTF_DIVERSIFIER, {"violations": []})
# if corr.get("guard_active"): restrict new orders on highly correlated symbols
# if div.get("violations"): bias orders away from violating sectors
#
# 2) Scale sizes using portfolio alloc + regime scaling + profit lock cooldown:
# alloc = _read_json(PORTF_RISK_ALLOC, {"alloc": {}})
# regime = _read_json(PORTF_REGIME_SCALER, {"scale_multiplier": 1.0})
# lock = _read_json(PORTF_PROFIT_LOCK, {"cooldown_scale": 1.0})
# size_pct = base_symbol_size * alloc["alloc"].get(sym, {}).get("risk_alloc", 0.01) * regime["scale_multiplier"] * lock["cooldown_scale"]

if __name__ == "__main__":
    run_portfolio_orchestrator_191_200()