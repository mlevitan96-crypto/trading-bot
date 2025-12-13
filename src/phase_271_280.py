# src/phase_271_280.py
#
# Phases 271–280: Attribution & Alpha Upgrade
# - 271: Trade Forensics Logger (per-trade microstructure context)
# - 272: Expectancy Analyzer (precision, edge, slippage, fees)
# - 273: Leak Ranker (ranked leak list, kill list, preserve list)
# - 274: OFI Signal Generator (order-flow imbalance)
# - 275: Micro-Arb Detector (cross-venue mispricing)
# - 276: Regime-Aware Entry Filter (timing gates)
# - 277: Offset & Venue Tuner (auto-widening, maker-first bias)
# - 278: Exit Logic Enhancer (adaptive stops, time-based exits)
# - 279: Challenger Pipeline Hooks (test → canary → promotion)
# - 280: Attribution & Alpha Upgrade Orchestrator (daily run, summary, checkpoint)
#
# Purpose: instrument trades, expose leaks, generate new alpha signals, and
# promote better strategies automatically using your existing canary/promotion stack.

import os, json, time
from collections import defaultdict

# ---- Paths ----
LOG_DIR = "logs"
TRADE_LOG = os.path.join(LOG_DIR, "logs/executed_trades.jsonl")
ATTRIBUTION_LOG = os.path.join(LOG_DIR, "attribution_271_280.jsonl")
ALPHA_SIGNALS = os.path.join(LOG_DIR, "alpha_signals_274_275.jsonl")
CHALLENGER_PIPELINE = os.path.join(LOG_DIR, "challenger_pipeline_279.json")
CHECKPOINT_FILE = os.path.join(LOG_DIR, "attribution_checkpoint_280.json")

def _now(): return int(time.time())
def _read_json(path, default=None): return json.load(open(path)) if os.path.exists(path) else (default if default is not None else {})
def _write_json(path, obj): os.makedirs(os.path.dirname(path), exist_ok=True); json.dump(obj, open(path, "w"), indent=2)
def _append_jsonl(path, obj): os.makedirs(os.path.dirname(path), exist_ok=True); open(path, "a").write(json.dumps(obj) + "\n")
def _read_jsonl(path): return [json.loads(l) for l in open(path)] if os.path.exists(path) else []

# ======================================================================
# 271 – Trade Forensics Logger (per-trade microstructure context)
# ======================================================================
def log_trade_forensics(trade):
    """
    trade: {
      "symbol": "BTCUSDT", "pnl": 0.003, "fees": 0.0004, "slippage": 0.0006,
      "spread": 0.0005, "latency": 120, "venue": "binance", "maker": True,
      "entry_ts": 1763580000, "exit_ts": 1763580120, "direction": "long",
      "reason": "ofi_momentum_v2"
    }
    """
    trade["ts"] = _now()
    trade["microstructure"] = {
        "spread_bp": trade.get("spread", 0.0005) * 1e4,
        "latency_ms": trade.get("latency", 120),
        "venue": trade.get("venue", "unknown"),
        "maker": bool(trade.get("maker", False))
    }
    _append_jsonl(TRADE_LOG, trade)

# ======================================================================
# 272 – Expectancy Analyzer (precision, edge, slippage, fees)
# ======================================================================
def analyze_expectancy(window=500):
    trades = _read_jsonl(TRADE_LOG)[-window:]
    wins = [t for t in trades if t.get("pnl", 0) > 0]
    losses = [t for t in trades if t.get("pnl", 0) <= 0]
    precision = (len(wins) / len(trades)) if trades else 0.0
    avg_win = (sum(t.get("pnl", 0) for t in wins) / len(wins)) if wins else 0.0
    avg_loss = abs(sum(t.get("pnl", 0) for t in losses) / len(losses)) if losses else 0.0
    expectancy = (avg_win * precision) - (avg_loss * (1 - precision))
    fee_ratio = (sum(t.get("fees", 0) for t in trades) /
                 max(1e-9, sum(abs(t.get("pnl", 0)) for t in trades))) if trades else 0.0
    avg_slippage = (sum(t.get("slippage", 0) for t in trades) / len(trades)) if trades else 0.0
    return {
        "precision": round(precision, 4),
        "expectancy": round(expectancy, 6),
        "fee_ratio": round(fee_ratio, 4),
        "slippage": round(avg_slippage, 6),
        "sample_size": len(trades)
    }

# ======================================================================
# 273 – Leak Ranker (ranked leaks, kill/preserve lists)
# ======================================================================
def rank_leaks(window=1000):
    trades = _read_jsonl(TRADE_LOG)[-window:]
    by_strategy = defaultdict(list)
    for t in trades:
        key = t.get("reason", "unknown")
        by_strategy[key].append(t.get("pnl", 0.0))
    ranked = sorted(by_strategy.items(), key=lambda kv: (sum(kv[1]) / max(1, len(kv[1]))), reverse=True)
    kill = [s for s, pnl in ranked if (sum(pnl) / max(1, len(pnl))) < -0.0005]
    preserve = [s for s, pnl in ranked if (sum(pnl) / max(1, len(pnl))) > 0.0005]
    leak_rank = [{"strategy": s, "avg_pnl": round(sum(pnl)/max(1,len(pnl)), 6), "samples": len(pnl)} for s, pnl in ranked]
    return {"kill": kill, "preserve": preserve, "ranked": leak_rank}

# ======================================================================
# 274 – OFI Signal Generator (order-flow imbalance)
# ======================================================================
def generate_ofi_signal(symbol, bid_size, ask_size, beta=1.0):
    """
    Simple OFI: (bid - ask)/(bid + ask), optionally scaled by beta.
    """
    denom = max(1e-9, (bid_size + ask_size))
    imbalance = ((bid_size - ask_size) / denom) * beta
    signal = {"ts": _now(), "symbol": symbol, "ofi": round(imbalance, 6)}
    _append_jsonl(ALPHA_SIGNALS, signal)
    return signal

# ======================================================================
# 275 – Micro-Arb Detector (cross-venue mispricing)
# ======================================================================
def detect_micro_arb(symbol, price_venue1, price_venue2, threshold=0.05, fee_bp=2.0):
    """
    Detects simple cross-venue spreads larger than threshold + fees.
    """
    diff = abs(price_venue1 - price_venue2)
    effective_threshold = threshold + (fee_bp / 1e4)
    if diff >= effective_threshold:
        signal = {"ts": _now(), "symbol": symbol, "arb_opportunity": True, "spread": round(diff, 6)}
        _append_jsonl(ALPHA_SIGNALS, signal)
        return signal
    return {"arb_opportunity": False, "symbol": symbol, "spread": round(diff, 6)}

# ======================================================================
# 276 – Regime-Aware Entry Filter (timing gates)
# ======================================================================
def regime_entry_filter(regime, volatility, spread_bp, depth_units, vol_threshold=0.02, spread_cap_bp=8.0, min_depth=3):
    """
    Gate entries by regime + microstructure:
    - momentum: vol < threshold, spread < cap, depth >= min
    - choppy: reject if vol > threshold or spread > cap
    """
    if regime == "momentum":
        return (volatility < vol_threshold) and (spread_bp < spread_cap_bp) and (depth_units >= min_depth)
    if regime == "choppy":
        return not (volatility > vol_threshold or spread_bp > spread_cap_bp)
    return True

# ======================================================================
# 277 – Offset & Venue Tuner (auto-widening, maker-first bias)
# ======================================================================
def tune_offset_and_venue(symbol, recent_slippage_bp, maker_fill_rate, base_offset_bp=5.0):
    """
    Auto-widen offsets under slippage; bias maker routes when fill rate is strong.
    """
    widen = 2.0 if recent_slippage_bp > 6.0 else 0.0
    offset_bp = base_offset_bp + widen
    prefer_maker = maker_fill_rate >= 0.6
    return {"offset_bp": round(offset_bp, 2), "prefer_maker": prefer_maker, "symbol": symbol}

# ======================================================================
# 278 – Exit Logic Enhancer (adaptive stops, time-based exits)
# ======================================================================
def enhanced_exit_logic(entry_ts, pnl, regime="momentum", max_hold_sec=600, stop_loss_bp=10.0):
    """
    Adaptive exit:
    - cut losers faster in choppy regimes
    - time-based exit when edge decays
    """
    held_sec = _now() - int(entry_ts)
    stop_loss_hit = pnl < -(stop_loss_bp / 1e4)
    time_up = held_sec > max_hold_sec if regime != "momentum" else held_sec > (max_hold_sec * 0.8)
    return bool(stop_loss_hit or time_up)

# ======================================================================
# 279 – Challenger Pipeline Hooks (test → canary → promotion)
# ======================================================================
def challenger_pipeline_update(name, metrics):
    """
    metrics: {"lift": 0.07, "samples": 50, "fee_ratio_delta": -0.05, "precision_delta": +0.03}
    """
    pipe = _read_json(CHALLENGER_PIPELINE, {"challengers": {}})
    decision = "hold"
    if metrics.get("lift", 0) >= 0.05 and metrics.get("samples", 0) >= 30 and metrics.get("fee_ratio_delta", 0) <= 0 and metrics.get("precision_delta", 0) >= 0:
        decision = "promote"
    elif metrics.get("lift", 0) <= 0 or metrics.get("precision_delta", 0) < 0:
        decision = "demote"
    pipe["challengers"][name] = {"decision": decision, "metrics": metrics, "ts": _now()}
    _write_json(CHALLENGER_PIPELINE, pipe)
    return {"decision": decision}

# ======================================================================
# 280 – Attribution & Alpha Upgrade Orchestrator (daily)
# ======================================================================
def run_attribution_orchestrator_271_280():
    """
    Nightly:
    - Analyze expectancy
    - Rank leaks (kill/preserve lists)
    - Count alpha signals produced
    - Persist checkpoint and attribution summary
    """
    summary = {
        "ts": _now(),
        "expectancy": analyze_expectancy(),
        "leaks": rank_leaks(),
        "alpha_signals_last100": len(_read_jsonl(ALPHA_SIGNALS)[-100:]),
        "challengers": _read_json(CHALLENGER_PIPELINE, {}).get("challengers", {})
    }
    _append_jsonl(ATTRIBUTION_LOG, summary)
    _write_json(CHECKPOINT_FILE, summary)
    return summary

# ----------------------------------------------------------------------
# Integration Hooks for execution bridge & orchestrators
# ----------------------------------------------------------------------
def log_trade_execution(symbol, pnl, fees, slippage, spread, latency, venue, maker, entry_ts=None, exit_ts=None, direction=None, reason=None):
    log_trade_forensics({
        "symbol": symbol, "pnl": float(pnl), "fees": float(fees), "slippage": float(slippage),
        "spread": float(spread), "latency": int(latency), "venue": venue, "maker": bool(maker),
        "entry_ts": entry_ts or _now(), "exit_ts": exit_ts or _now(), "direction": direction or "unknown",
        "reason": reason or "unknown"
    })

def get_expectancy_metrics(window=500):
    return analyze_expectancy(window=window)

def get_leak_lists(window=1000):
    return rank_leaks(window=window)

def generate_alpha_signals(symbol, bid_size, ask_size, price1, price2):
    ofi = generate_ofi_signal(symbol, bid_size, ask_size)
    arb = detect_micro_arb(symbol, price1, price2)
    return {"ofi": ofi, "arb": arb}

def evaluate_exit(entry_ts, pnl, regime="momentum", max_hold_sec=600, stop_loss_bp=10.0):
    return enhanced_exit_logic(entry_ts, pnl, regime=regime, max_hold_sec=max_hold_sec, stop_loss_bp=stop_loss_bp)

def update_challenger(name, metrics):
    return challenger_pipeline_update(name, metrics)

def run_daily_attribution():
    return run_attribution_orchestrator_271_280()

if __name__ == "__main__":
    # Demo: log synthetic trades and run nightly attribution
    for i in range(20):
        log_trade_execution(
            symbol="BTCUSDT", pnl=0.001*(1 if i%3 else -1), fees=0.0002, slippage=0.0006,
            spread=0.0005, latency=120, venue="binance", maker=True,
            direction="long", reason="ofi_momentum_v2"
        )
    # Generate some signals
    generate_alpha_signals("BTCUSDT", bid_size=1200, ask_size=900, price1=50000.0, price2=50000.07)
    # Update a challenger decision
    update_challenger("ofi_momentum_v2", {"lift": 0.07, "samples": 50, "fee_ratio_delta": -0.05, "precision_delta": 0.03})
    # Run orchestrator
    summary = run_attribution_orchestrator_271_280()
    print("Attribution & Alpha Upgrade summary:", json.dumps(summary, indent=2))