"""
Phase 10.2 — Futures Optimizer (Concentration + Shadow Sweeps + Promotion)
Goal: Concentrate exposure into top-attribution futures symbols, continuously run parameter
sweeps in shadow, and promote only configurations that beat baseline expectancy.

Integration with existing system:
- Phase 9.3 enforcement (futures-only focus)
- Phase 10.0 profit gates
- Phase 10.1 attribution tracking
"""

import time
import json
import os
import random
import logging
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple
from src.net_pnl_enforcement import get_net_pnl, get_net_roi

logger = logging.getLogger(__name__)

# ======================================================================================
# Config
# ======================================================================================

@dataclass
class Phase102Config:
    top_n_symbols: int = 3                      # Concentrate in top N futures symbols
    min_expectancy_wr_pct: float = 55.0         # Minimum win rate for concentration eligibility
    min_expectancy_sharpe: float = 1.0          # Minimum Sharpe for concentration eligibility
    min_expectancy_pnl_24h_usd: float = 50.0    # Minimum 24h net P&L for eligibility

    # Allocation multipliers
    boost_multiplier_top: float = 1.50          # Strong winners
    base_multiplier_mid: float = 1.00           # Neutral
    suppress_multiplier_weak: float = 1.00      # No suppression (was 0.50)

    # Per-symbol exposure cap (still respects Phase 9.3 caps; this is additional internal cap)
    max_symbol_exposure_pct_internal: float = 0.10

    # Shadow sweeps
    shadow_enabled: bool = True
    shadow_param_sets_per_symbol: int = 3       # Number of configs to test per symbol/strategy
    promotion_required_wins: int = 3            # Wins required to consider promotion
    promotion_min_wr_pct: float = 55.0
    promotion_min_sharpe: float = 1.0
    sweep_window_trades: int = 50               # Trades considered in sweep evaluation
    demotion_on_decline: bool = True            # Demote live config if it underperforms vs promoted shadow

    # Cadence
    allocator_tick_sec: int = 300               # 5 minutes
    shadow_tick_sec: int = 600                  # 10 minutes

    # Persistence
    state_path: str = "logs/phase102_state.json"
    events_path: str = "logs/phase102_events.jsonl"

CFG102 = Phase102Config()

# ======================================================================================
# Runtime State
# ======================================================================================

STATE102 = {
    "ranked_futures": [],  # [(symbol, score, metrics), ...]
    "allocation_multipliers": {},  # symbol -> multiplier
    "shadow_configs": {},  # "(symbol,strategy)" -> {config_id -> params}
    "shadow_results": {},  # config_id -> {"wins": int, "wr": float, "sharpe": float, "pnl": float}
    "live_configs": {},    # "(symbol,strategy)" -> {"params": dict, "baseline_wr": float, "baseline_sharpe": float}
    "last_rank_ts": 0,
}

# ======================================================================================
# Hook Implementations
# ======================================================================================

def portfolio_value() -> float:
    """Get current portfolio value"""
    try:
        from src.portfolio_tracker import load_portfolio
        portfolio = load_portfolio()
        return portfolio.get("current_value", 10000.0)
    except Exception as e:
        logger.warning(f"Phase 10.2: Portfolio value error: {e}")
        return 10000.0

def get_futures_symbols() -> List[str]:
    """Get list of futures symbols being traded"""
    return ["ETHUSDT", "SOLUSDT", "BTCUSDT", "AVAXUSDT", "DOTUSDT", "TRXUSDT"]

def calc_symbol_win_rate(symbol: str, window_trades: int=50) -> float:
    """Calculate symbol-specific win rate from recent FUTURES trades"""
    try:
        from src.futures_portfolio_tracker import load_futures_trades
        trades_data = load_futures_trades()
        all_trades = trades_data.get("trades", [])
        symbol_trades = [t for t in all_trades if t.get("symbol") == symbol][-window_trades:]
        if not symbol_trades:
            return 0.0
        # CRITICAL: Use net P&L (after fees) for accurate win rate
        wins = sum(1 for t in symbol_trades if get_net_pnl(t) > 0)
        return (wins / len(symbol_trades)) * 100.0
    except Exception:
        return 0.0

def calc_symbol_sharpe_24h(symbol: str) -> float:
    """Calculate symbol-specific 24h Sharpe ratio from FUTURES trades"""
    try:
        from src.futures_portfolio_tracker import load_futures_trades
        import numpy as np
        trades_data = load_futures_trades()
        all_trades = trades_data.get("trades", [])
        now = time.time()
        symbol_trades = [t for t in all_trades if t.get("symbol") == symbol and (now - t.get("timestamp", 0)) < 86400]
        if len(symbol_trades) < 5:
            return 0.0
        returns = [t.get("leveraged_roi", 0) for t in symbol_trades]
        if not returns:
            return 0.0
        mean_return = np.mean(returns)
        std_return = np.std(returns) if len(returns) > 1 else 0.01
        return mean_return / (std_return if std_return > 0 else 0.01)
    except Exception:
        return 0.0

def calc_symbol_net_pnl_24h(symbol: str) -> float:
    """Calculate symbol-specific net P&L in last 24h from FUTURES trades"""
    try:
        from src.futures_portfolio_tracker import load_futures_trades
        trades_data = load_futures_trades()
        all_trades = trades_data.get("trades", [])
        now = time.time()
        symbol_trades = [t for t in all_trades if t.get("symbol") == symbol and (now - t.get("timestamp", 0)) < 86400]
        # CRITICAL: Use net P&L (after fees) for accurate 24h tracking
        pnl = sum(get_net_pnl(t) for t in symbol_trades)
        return pnl
    except Exception:
        return 0.0

def calc_strategy_win_rate(strategy: str, window_trades: int=50) -> float:
    """Calculate strategy-specific win rate from FUTURES trades"""
    try:
        from src.futures_portfolio_tracker import load_futures_trades
        trades_data = load_futures_trades()
        all_trades = trades_data.get("trades", [])
        strat_trades = [t for t in all_trades if strategy in t.get("strategy", "")][-window_trades:]
        if not strat_trades:
            return 0.0
        # CRITICAL: Use net P&L (after fees) for accurate win rate
        wins = sum(1 for t in strat_trades if get_net_pnl(t) > 0)
        return (wins / len(strat_trades)) * 100.0
    except Exception:
        return 0.0

def calc_strategy_sharpe_24h(strategy: str) -> float:
    """Calculate strategy-specific 24h Sharpe from FUTURES trades"""
    try:
        from src.futures_portfolio_tracker import load_futures_trades
        import numpy as np
        trades_data = load_futures_trades()
        all_trades = trades_data.get("trades", [])
        now = time.time()
        strat_trades = [t for t in all_trades if strategy in t.get("strategy", "") and (now - t.get("timestamp", 0)) < 86400]
        if len(strat_trades) < 5:
            return 0.0
        returns = [t.get("leveraged_roi", 0) for t in strat_trades]
        if not returns:
            return 0.0
        mean_return = np.mean(returns)
        std_return = np.std(returns) if len(returns) > 1 else 0.01
        return mean_return / (std_return if std_return > 0 else 0.01)
    except Exception:
        return 0.0

def current_market_regime() -> str:
    """Get current market regime"""
    try:
        from src.regime_detector import predict_regime
        return predict_regime() or "stable"
    except Exception:
        return "stable"

def run_shadow_trade(symbol: str, strategy: str, params: Dict) -> Dict:
    """
    Execute a shadow trade simulation (no capital).
    Returns {"symbol":..., "strategy":..., "pnl_usd": float, "win": bool}
    """
    # Simple simulation: random outcome based on current metrics with param influence
    wr = calc_symbol_win_rate(symbol, window_trades=30) or 45.0
    # Params influence: tighter filters = higher quality but fewer trades
    mtf_boost = (params.get("mtf_conf_min", 50) - 50) / 100.0  # 0 to 0.2
    wr_adjusted = min(100.0, wr + mtf_boost * 10)
    
    win = random.random() < (wr_adjusted / 100.0)
    pnl = random.uniform(5, 20) if win else random.uniform(-15, -5)
    
    return {
        "symbol": symbol,
        "strategy": strategy,
        "pnl_usd": pnl,
        "win": win
    }

# ======================================================================================
# Persistence
# ======================================================================================

def _persist_state102():
    try:
        os.makedirs(os.path.dirname(CFG102.state_path), exist_ok=True)
        # Convert tuples to strings for JSON serialization
        serializable = {
            "ranked_futures": STATE102["ranked_futures"],
            "allocation_multipliers": STATE102["allocation_multipliers"],
            "shadow_configs": {str(k): v for k, v in STATE102["shadow_configs"].items()},
            "shadow_results": STATE102["shadow_results"],
            "live_configs": {str(k): v for k, v in STATE102["live_configs"].items()},
            "last_rank_ts": STATE102["last_rank_ts"]
        }
        with open(CFG102.state_path, "w") as f:
            json.dump(serializable, f, indent=2)
    except Exception as e:
        logger.error(f"Phase 10.2 persist error: {e}")

def _append_event102(event: str, payload: dict):
    """Append event to log file with retry logic for transient I/O errors."""
    max_retries = 3
    for attempt in range(max_retries):
        try:
            os.makedirs(os.path.dirname(CFG102.events_path), exist_ok=True)
            with open(CFG102.events_path, "a") as f:
                f.write(json.dumps({"ts": int(time.time()), "event": event, "payload": payload}) + "\n")
                f.flush()
            return
        except OSError as e:
            if attempt < max_retries - 1:
                time.sleep(0.1 * (attempt + 1))
                continue
            pass
        except Exception:
            pass

# ======================================================================================
# Ranking and Concentration
# ======================================================================================

def _eligibility_score(symbol: str) -> Tuple[float, Dict]:
    wr = calc_symbol_win_rate(symbol, window_trades=CFG102.sweep_window_trades) or 0.0
    sh = calc_symbol_sharpe_24h(symbol) or 0.0
    pnl = calc_symbol_net_pnl_24h(symbol) or 0.0
    # Basic eligibility gate
    eligible = (wr >= CFG102.min_expectancy_wr_pct and sh >= CFG102.min_expectancy_sharpe and pnl >= CFG102.min_expectancy_pnl_24h_usd)
    # Score: weighted combination (tune as needed)
    score = (0.5 * wr) + (30.0 * sh) + (0.1 * pnl)
    return (score if eligible else 0.0, {"wr": wr, "sh": sh, "pnl": pnl, "eligible": eligible})

def phase102_rank_futures():
    symbols = get_futures_symbols()
    ranked = []
    for sym in symbols:
        score, metrics = _eligibility_score(sym)
        ranked.append((sym, score, metrics))
    ranked.sort(key=lambda x: x[1], reverse=True)
    STATE102["ranked_futures"] = ranked
    STATE102["last_rank_ts"] = time.time()
    _persist_state102()
    
    top_symbols = [r[0] for r in ranked[:CFG102.top_n_symbols]]
    logger.info(f"📊 PHASE102: Ranked futures (top {CFG102.top_n_symbols}): {top_symbols}")
    _append_event102("phase102_rank_complete", {"ranked": [(r[0], r[1], r[2]) for r in ranked]})

def _allocation_multiplier_for(symbol: str) -> float:
    # If symbol is in top N winners, boost; if eligible but outside top N, base; else suppress
    ranked = STATE102["ranked_futures"]
    top_syms = [r[0] for r in ranked[:CFG102.top_n_symbols]]
    # Find metrics for symbol
    metrics = None
    for r in ranked:
        if r[0] == symbol:
            metrics = r[2]
            break
    if not metrics or not metrics["eligible"]:
        return CFG102.suppress_multiplier_weak
    if symbol in top_syms:
        return CFG102.boost_multiplier_top
    return CFG102.base_multiplier_mid

def phase102_allocate_for_signal(signal: Dict, base_size: float) -> float:
    """
    Call before sizing. Returns adjusted size based on concentration strategy.
    """
    if signal.get("venue", "spot") != "futures":
        # Only optimize futures allocation
        return base_size

    symbol = signal.get("symbol")
    mult = _allocation_multiplier_for(symbol)
    size = base_size * mult

    # Respect internal per-symbol exposure cap
    pv = portfolio_value()
    max_additional = pv * CFG102.max_symbol_exposure_pct_internal
    size_capped = min(size, max_additional)

    STATE102["allocation_multipliers"][symbol] = mult
    _persist_state102()
    
    logger.info(f"🎯 PHASE102: {symbol} allocation {base_size:.2f} → {size_capped:.2f} (mult={mult:.2f}x)")
    _append_event102("phase102_alloc_decision", {"symbol": symbol, "base": base_size, "multiplier": mult, "size_capped": size_capped})
    return size_capped

# ======================================================================================
# Shadow Parameter Sweeps
# ======================================================================================

def _gen_shadow_params(strategy: str) -> Dict:
    """
    Generate a randomized but bounded parameter set for a strategy.
    """
    regime = current_market_regime()
    params = {
        "mtf_conf_min": random.choice([50, 60, 70]),
        "volume_boost_min": random.choice([1.1, 1.25, 1.5]),
        "roi_proj_min_pct": random.choice([0.20, 0.30, 0.50]),
        "atr_trail_mult": random.choice([1.2, 1.5, 1.8]) if regime != "volatile" else random.choice([1.0, 1.2, 1.4]),
        "time_exit_hours": random.choice([4, 6, 8]),
        "cooldown_min": random.choice([20, 30, 45]),
    }
    return params

def _ensure_shadow_configs(symbol: str, strategy: str):
    key = f"{symbol},{strategy}"
    if key not in STATE102["shadow_configs"]:
        STATE102["shadow_configs"][key] = {}
    # Populate up to shadow_param_sets_per_symbol
    while len(STATE102["shadow_configs"][key]) < CFG102.shadow_param_sets_per_symbol:
        cfg_id = f"{symbol}:{strategy}:cfg{len(STATE102['shadow_configs'][key])+1}"
        STATE102["shadow_configs"][key][cfg_id] = _gen_shadow_params(strategy)

def phase102_shadow_sweep_tick():
    if not CFG102.shadow_enabled:
        return
    # Select symbols from top of ranking for sweeps, plus a few random
    ranked = STATE102["ranked_futures"]
    candidates = [r[0] for r in ranked[:CFG102.top_n_symbols]]
    extras = [r[0] for r in ranked[CFG102.top_n_symbols:min(CFG102.top_n_symbols+2, len(ranked))]]
    
    sweep_count = 0
    for symbol in candidates + extras:
        for strategy in ["Trend-Conservative", "Breakout-Aggressive", "Sentiment-Fusion"]:
            _ensure_shadow_configs(symbol, strategy)
            key = f"{symbol},{strategy}"
            for cfg_id, params in STATE102["shadow_configs"][key].items():
                result = run_shadow_trade(symbol, strategy, params)
                pnl = result.get("pnl_usd", 0.0)
                win = bool(result.get("win", False))
                # Update shadow result stats
                row = STATE102["shadow_results"].get(cfg_id, {"wins": 0, "wr": 0.0, "sharpe": 0.0, "pnl": 0.0, "samples": 0})
                row["wins"] += (1 if win else 0)
                row["pnl"] += pnl
                row["samples"] += 1
                # Approximate WR and Sharpe proxies
                row["wr"] = (row["wins"] / max(1, row["samples"])) * 100.0
                row["sharpe"] = max(0.0, row["pnl"] / (row["samples"] or 1)) / 10.0
                STATE102["shadow_results"][cfg_id] = row
                sweep_count += 1
    
    _persist_state102()
    logger.info(f"🔬 PHASE102: Shadow sweep complete ({sweep_count} configs tested)")
    _append_event102("phase102_shadow_tick_complete", {"count": len(STATE102['shadow_results'])})

# ======================================================================================
# Promotion / Demotion Logic
# ======================================================================================

def _baseline_for(symbol: str, strategy: str) -> Tuple[float, float]:
    # Baseline from live config metrics if available, else compute from strategy-wide
    key = f"{symbol},{strategy}"
    live = STATE102["live_configs"].get(key)
    if live:
        return (live.get("baseline_wr", 0.0), live.get("baseline_sharpe", 0.0))
    wr = calc_strategy_win_rate(strategy, window_trades=CFG102.sweep_window_trades) or 0.0
    sh = calc_strategy_sharpe_24h(strategy) or 0.0
    return (wr, sh)

def _best_shadow_cfg(symbol: str, strategy: str) -> Optional[Tuple[str, Dict]]:
    key = f"{symbol},{strategy}"
    if key not in STATE102["shadow_configs"]:
        return None
    best_id, best_row = None, None
    for cfg_id in STATE102["shadow_configs"][key].keys():
        row = STATE102["shadow_results"].get(cfg_id)
        if not row:
            continue
        # Require minimum samples and thresholds
        if row["wins"] >= CFG102.promotion_required_wins and row["wr"] >= CFG102.promotion_min_wr_pct and row["sharpe"] >= CFG102.promotion_min_sharpe:
            if not best_row or (row["wr"] + row["sharpe"]*100) > (best_row["wr"] + best_row["sharpe"]*100):
                best_id, best_row = cfg_id, row
    if not best_id:
        return None
    return (best_id, STATE102["shadow_configs"][key][best_id])

def phase102_try_promote(symbol: str, strategy: str):
    candidate = _best_shadow_cfg(symbol, strategy)
    if not candidate:
        return
    cfg_id, params = candidate
    base_wr, base_sh = _baseline_for(symbol, strategy)
    row = STATE102["shadow_results"].get(cfg_id, {})
    if row and (row["wr"] >= base_wr) and (row["sharpe"] >= base_sh):
        # Promote: replace/record live config
        key = f"{symbol},{strategy}"
        STATE102["live_configs"][key] = {"params": params, "baseline_wr": row["wr"], "baseline_sharpe": row["sharpe"]}
        _persist_state102()
        logger.info(f"⬆️  PHASE102: PROMOTED {cfg_id} (WR={row['wr']:.1f}%, Sharpe={row['sharpe']:.2f})")
        _append_event102("phase102_promotion", {"symbol": symbol, "strategy": strategy, "cfg_id": cfg_id, "params": params, "stats": row})

def phase102_try_demote(symbol: str, strategy: str):
    if not CFG102.demotion_on_decline:
        return
    key = f"{symbol},{strategy}"
    live = STATE102["live_configs"].get(key)
    if not live:
        return
    # If current performance significantly worse than promoted baseline, demote
    curr_wr = calc_strategy_win_rate(strategy, window_trades=CFG102.sweep_window_trades) or 0.0
    curr_sh = calc_strategy_sharpe_24h(strategy) or 0.0
    if (curr_wr + curr_sh*100) < (live["baseline_wr"] + live["baseline_sharpe"]*100) * 0.90:
        del STATE102["live_configs"][key]
        _persist_state102()
        logger.warning(f"⬇️  PHASE102: DEMOTED {key} (performance declined)")
        _append_event102("phase102_demotion", {"symbol": symbol, "strategy": strategy, "curr_wr": curr_wr, "curr_sh": curr_sh})

# ======================================================================================
# Attribution Integration (on trade close)
# ======================================================================================

def phase102_on_trade_close(trade: Dict):
    """
    Feed attribution and sweep outcomes when trades close.
    """
    symbol = trade.get("symbol")
    strategy = trade.get("strategy")
    # CRITICAL: Use net P&L (after fees) for accurate tracking
    pnl = get_net_pnl(trade)
    
    # Update live config baselines opportunistically
    wr = calc_symbol_win_rate(symbol, window_trades=CFG102.sweep_window_trades) or 0.0
    sh = calc_symbol_sharpe_24h(symbol) or 0.0
    key = f"{symbol},{strategy}"
    live = STATE102["live_configs"].get(key)
    if live:
        # Nudge baseline if improving
        live["baseline_wr"] = max(live["baseline_wr"], wr)
        live["baseline_sharpe"] = max(live["baseline_sharpe"], sh)
        STATE102["live_configs"][key] = live
        _persist_state102()
    
    # Periodic promote/demote
    phase102_try_promote(symbol, strategy)
    phase102_try_demote(symbol, strategy)
    
    # Audit
    _append_event102("phase102_trade_close", {"symbol": symbol, "strategy": strategy, "pnl": pnl, "wr": wr, "sharpe": sh})

# ======================================================================================
# Ticks
# ======================================================================================

def phase102_allocator_tick():
    phase102_rank_futures()
    # Recompute multipliers for top N; others suppressed/base
    for sym, _, _ in STATE102["ranked_futures"]:
        mult = _allocation_multiplier_for(sym)
        STATE102["allocation_multipliers"][sym] = mult
    _persist_state102()
    _append_event102("phase102_allocator_tick", {"ranked": STATE102["ranked_futures"], "multipliers": STATE102["allocation_multipliers"]})

def phase102_shadow_tick():
    phase102_shadow_sweep_tick()
    _append_event102("phase102_shadow_tick", {"results_count": len(STATE102["shadow_results"])})

# ======================================================================================
# Status getters for dashboard
# ======================================================================================

def get_phase102_status() -> Dict:
    return {
        "ranked_futures": STATE102["ranked_futures"][:10],
        "allocation_multipliers": STATE102["allocation_multipliers"],
        "top_n": CFG102.top_n_symbols,
        "shadow_configs_count": len(STATE102["shadow_configs"]),
        "shadow_results_count": len(STATE102["shadow_results"]),
        "live_configs_count": len(STATE102["live_configs"]),
        "last_rank_ts": STATE102["last_rank_ts"]
    }

def get_shadow_leaderboard() -> List[Dict]:
    """Get top shadow configs by performance"""
    leaderboard = []
    for cfg_id, stats in STATE102["shadow_results"].items():
        if stats["samples"] >= 5:
            leaderboard.append({
                "cfg_id": cfg_id,
                "wr": stats["wr"],
                "sharpe": stats["sharpe"],
                "pnl": stats["pnl"],
                "samples": stats["samples"]
            })
    leaderboard.sort(key=lambda x: x["wr"] + x["sharpe"] * 100, reverse=True)
    return leaderboard[:20]

# ======================================================================================
# Bootstrap
# ======================================================================================

def start_phase102_futures_optimizer():
    os.makedirs(os.path.dirname(CFG102.state_path), exist_ok=True)
    if not os.path.exists(CFG102.state_path):
        _persist_state102()
    
    logger.info("🚀 Starting Phase 10.2 Futures Optimizer...")
    logger.info(f"   ℹ️  Top N symbols: {CFG102.top_n_symbols}")
    logger.info(f"   ℹ️  Boost multiplier: {CFG102.boost_multiplier_top}x")
    logger.info(f"   ℹ️  Suppress multiplier: {CFG102.suppress_multiplier_weak}x")
    logger.info(f"   ℹ️  Shadow configs per symbol: {CFG102.shadow_param_sets_per_symbol}")
    logger.info("✅ Phase 10.2 Futures Optimizer started")
    
    _append_event102("phase102_started", {"cfg": "loaded"})
