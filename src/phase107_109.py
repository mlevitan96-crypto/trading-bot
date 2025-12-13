"""
Phases 10.7–10.9 — Predictive Intelligence + Capital Governance + Autonomous Recovery

Phase 10.7 - Predictive Intelligence:
- Forecast market regimes and pre-bias allocation/risk with per-symbol calibrated weights
- Per-symbol predictive weight overrides (trend/vol/liquidity/flow)
- Online calibration: adjust predictive weights based on realized edge

Phase 10.8 - Capital Governance:
- Expectancy-aware ramp schedules and capital gates
- Venue-level scaling based on sustained performance
- Symbol and venue exposure caps

Phase 10.9 - Autonomous Recovery:
- Detect anomalies (win rate collapse, slippage spikes)
- Automatic mitigation (freeze entries, reduce size, widen stops)
- Methodical reactivation after sustained recovery
"""

import time, os, json, math, random, copy, statistics
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple
from src.net_pnl_enforcement import get_net_pnl, get_net_roi

# ======================================================================================
# Config
# ======================================================================================

@dataclass
class Phase107Cfg:
    w_trend_prob: float = 0.40
    w_vol_forecast: float = 0.30
    w_liquidity_score: float = 0.20
    w_flow_signal: float = 0.10
    
    max_pre_bias_mult: float = 1.30
    min_pre_bias_mult: float = 0.70
    volatility_risk_nudge: float = 0.15
    liquidity_bonus: float = 0.10
    flow_bonus: float = 0.10
    
    calibration_alpha: float = 0.10
    calibration_window_trades: int = 50

@dataclass
class Phase108Cfg:
    venue_scale_gate: Dict[str, Dict[str, float]] = field(default_factory=lambda: {
        "futures": {"wr_pct": 50.0, "sharpe": 0.9, "pnl24h_usd": 200.0, "sustained_ticks": 3},
        "spot":    {"wr_pct": 55.0, "sharpe": 1.0, "pnl24h_usd": 100.0, "sustained_ticks": 5}
    })
    ramp_schedule_pct: List[float] = field(default_factory=lambda: [0.05, 0.10, 0.15, 0.20])
    retreat_pct_step: float = 0.05
    max_symbol_cap_pct: float = 0.10
    max_venue_cap_pct: Dict[str, float] = field(default_factory=lambda: {"futures": 0.60, "spot": 0.20})
    governance_tick_sec: int = 300

@dataclass
class Phase109Cfg:
    anomaly_wr_drop_pct: float = 20.0
    anomaly_sharpe_drop: float = 0.3
    anomaly_slippage_bps_spike: float = 12.0
    freeze_entries_min: int = 30
    reduce_size_factor: float = 0.50
    widen_stops_factor: float = 1.20
    reactivation_sustained_ticks: int = 3
    recovery_tick_sec: int = 300

@dataclass
class Phase107_109Cfg:
    p107: Phase107Cfg = field(default_factory=Phase107Cfg)
    p108: Phase108Cfg = field(default_factory=Phase108Cfg)
    p109: Phase109Cfg = field(default_factory=Phase109Cfg)
    state_path: str = "logs/phase107_109_state.json"
    events_path: str = "logs/phase107_109_events.jsonl"

CFG = Phase107_109Cfg()

STATE = {
    "predictive": {
        "last_bias": {},
        "weights_per_symbol": {},
        "prediction_quality": {}
    },
    "capital": {
        "venue_ticks_green": {"futures": 0, "spot": 0},
        "current_ramp_idx": {"futures": 0, "spot": 0},
        "venue_cap_pct": {"futures": 0.60, "spot": 0.20}
    },
    "recovery": {
        "frozen_until_ts": 0,
        "reactivation_ticks": 0,
        "last_anomaly": None
    }
}

# ======================================================================================
# Persistence
# ======================================================================================

def _persist_state():
    os.makedirs(os.path.dirname(CFG.state_path), exist_ok=True)
    with open(CFG.state_path, "w") as f:
        json.dump(STATE, f, indent=2)

def _append_event(event: str, payload: dict):
    os.makedirs(os.path.dirname(CFG.events_path), exist_ok=True)
    with open(CFG.events_path, "a") as f:
        f.write(json.dumps({"ts": int(time.time()), "event": event, "payload": payload}) + "\n")

# ======================================================================================
# System integration hooks
# ======================================================================================

def _portfolio_value() -> float:
    try:
        from src.portfolio_tracker import load_portfolio
        return load_portfolio().get("current_value", 10000.0)
    except:
        return 10000.0

def _calc_venue_stats(venue: str, window_trades: int = 100) -> Tuple[float, float, float]:
    try:
        from src.portfolio_tracker import load_trades
        trades = load_trades()
        venue_trades = [t for t in trades if t.get("venue", "spot") == venue][-window_trades:]
        if not venue_trades:
            return (0.0, 0.0, 0.0)
        
        # CRITICAL: Use net P&L (after fees) for accurate statistics
        wins = sum(1 for t in venue_trades if get_net_pnl(t) > 0)
        wr = (wins / len(venue_trades)) * 100 if venue_trades else 0.0
        
        pnls = [get_net_pnl(t) for t in venue_trades]
        avg_pnl = statistics.mean(pnls) if pnls else 0.0
        std_pnl = statistics.stdev(pnls) if len(pnls) > 1 else 1.0
        sharpe = (avg_pnl / std_pnl) if std_pnl > 0 else 0.0
        
        recent_24h = [t for t in venue_trades if time.time() - t.get("timestamp", 0) < 86400]
        pnl_24h = sum(get_net_pnl(t) for t in recent_24h)
        
        return (wr, sharpe, pnl_24h)
    except:
        return (0.0, 0.0, 0.0)

def _calc_symbol_stats(symbol: str, window_trades: int = 50) -> Tuple[float, float]:
    try:
        from src.portfolio_tracker import load_trades
        trades = load_trades()
        sym_trades = [t for t in trades if t.get("symbol") == symbol][-window_trades:]
        if not sym_trades:
            return (0.0, 0.0)
        
        # CRITICAL: Use net P&L (after fees) for accurate statistics
        wins = sum(1 for t in sym_trades if get_net_pnl(t) > 0)
        wr = (wins / len(sym_trades)) * 100 if sym_trades else 0.0
        
        pnls = [get_net_pnl(t) for t in sym_trades]
        avg_pnl = statistics.mean(pnls) if pnls else 0.0
        std_pnl = statistics.stdev(pnls) if len(pnls) > 1 else 1.0
        sharpe = (avg_pnl / std_pnl) if std_pnl > 0 else 0.0
        
        return (wr, sharpe)
    except:
        return (0.0, 0.0)

def _predict_trend_probability(symbol: str) -> float:
    try:
        from src.regime_detector import predict_regime
        regime = predict_regime()
        if regime in ["trend", "breakout"]:
            return 0.75
        elif regime in ["range", "chop"]:
            return 0.35
        else:
            return 0.50
    except:
        return 0.50

def _forecast_volatility_bps(symbol: str) -> float:
    try:
        from src.market_data import get_market_data
        candles = get_market_data(symbol, "1m", limit=50)
        if candles and len(candles) >= 20:
            closes = [c[4] for c in candles]
            returns = [(closes[i] / closes[i-1] - 1) * 10000 for i in range(1, len(closes))]
            vol_bps = statistics.stdev(returns) if len(returns) > 1 else 50.0
            return vol_bps
    except:
        pass
    return 50.0

def _liquidity_score(symbol: str) -> float:
    try:
        from src.market_data import get_market_data
        candles = get_market_data(symbol, "1m", limit=20)
        if candles and len(candles) >= 10:
            volumes = [c[5] for c in candles]
            avg_vol = statistics.mean(volumes) if volumes else 0
            if avg_vol > 1000000:
                return 0.90
            elif avg_vol > 500000:
                return 0.70
            elif avg_vol > 100000:
                return 0.50
            else:
                return 0.30
    except:
        pass
    return 0.50

def _flow_signal_confidence(symbol: str) -> float:
    return 0.50

def _recent_exec_slippage_bps(symbol: str, lookback: int = 20) -> float:
    try:
        from src.phase106_calibration import STATE106
        reports = STATE106.get("exec_reports", [])
        sym_reports = [r for r in reports if r.get("symbol") == symbol][-lookback:]
        if sym_reports:
            return statistics.mean([r.get("slip_bps", 0) for r in sym_reports])
    except:
        pass
    return 0.0

# ======================================================================================
# Phase 10.7 - Predictive Intelligence
# ======================================================================================

def _weights_for(symbol: str) -> Dict[str, float]:
    w = STATE["predictive"]["weights_per_symbol"].get(symbol)
    if w:
        return w
    w = {
        "w_trend_prob": CFG.p107.w_trend_prob,
        "w_vol_forecast": CFG.p107.w_vol_forecast,
        "w_liquidity_score": CFG.p107.w_liquidity_score,
        "w_flow_signal": CFG.p107.w_flow_signal
    }
    STATE["predictive"]["weights_per_symbol"][symbol] = w
    return w

def _predictive_bias(symbol: str) -> Tuple[float, Dict]:
    tp = max(0.0, min(1.0, _predict_trend_probability(symbol)))
    vf_bps = max(0.0, _forecast_volatility_bps(symbol))
    lq = max(0.0, min(1.0, _liquidity_score(symbol)))
    flow = max(0.0, min(1.0, _flow_signal_confidence(symbol)))
    
    w = _weights_for(symbol)
    vf_norm = min(1.5, vf_bps / 100.0)
    
    score = (
        w["w_trend_prob"] * tp +
        w["w_vol_forecast"] * (1.0 - vf_norm) +
        w["w_liquidity_score"] * lq +
        w["w_flow_signal"] * flow
    )
    
    mult = CFG.p107.min_pre_bias_mult + (CFG.p107.max_pre_bias_mult - CFG.p107.min_pre_bias_mult) * max(0.0, min(1.0, score))
    mult *= 1.0 + (CFG.p107.liquidity_bonus * lq) - (CFG.p107.volatility_risk_nudge * min(1.0, vf_norm)) + (CFG.p107.flow_bonus * (flow - 0.5))
    
    return (max(CFG.p107.min_pre_bias_mult, min(CFG.p107.max_pre_bias_mult, mult)), 
            {"tp": tp, "vf_bps": vf_bps, "vf_norm": vf_norm, "lq": lq, "flow": flow, "score": score, "weights": w})

def _update_prediction_quality(symbol: str, outcome_positive: bool):
    q = STATE["predictive"]["prediction_quality"].get(symbol, {"correct": 0, "total": 0})
    q["total"] += 1
    q["correct"] += (1 if outcome_positive else 0)
    STATE["predictive"]["prediction_quality"][symbol] = q

def _online_calibrate_weights(symbol: str):
    q = STATE["predictive"]["prediction_quality"].get(symbol, {"correct": 0, "total": 0})
    if q["total"] < CFG.p107.calibration_window_trades:
        return
    
    correctness = q["correct"] / max(1, q["total"])
    w = _weights_for(symbol)
    alpha = CFG.p107.calibration_alpha
    
    if correctness < 0.55:
        w["w_trend_prob"] = min(0.60, w["w_trend_prob"] + alpha * 0.10)
        w["w_liquidity_score"] = min(0.40, w["w_liquidity_score"] + alpha * 0.05)
        w["w_flow_signal"] = min(0.30, w["w_flow_signal"] + alpha * 0.05)
        w["w_vol_forecast"] = max(0.10, w["w_vol_forecast"] - alpha * 0.10)
    else:
        base = Phase107Cfg()
        for k in ["w_trend_prob","w_vol_forecast","w_liquidity_score","w_flow_signal"]:
            w[k] = w[k] + alpha * (getattr(base, k) - w[k])
    
    STATE["predictive"]["weights_per_symbol"][symbol] = w
    _append_event("phase107_calibration_update", {"symbol": symbol, "weights": w, "correctness": correctness})

def phase107_get_bias(symbol: str) -> Tuple[float, Dict]:
    mult, inputs = _predictive_bias(symbol)
    STATE["predictive"]["last_bias"][symbol] = {"mult": mult, "inputs": inputs}
    _persist_state()
    return (mult, inputs)

# ======================================================================================
# Phase 10.8 - Capital Governance
# ======================================================================================

def _venue_gate_green(venue: str) -> bool:
    wr, sh, pnl = _calc_venue_stats(venue)
    gate = CFG.p108.venue_scale_gate[venue]
    return (wr >= gate["wr_pct"] and sh >= gate["sharpe"] and pnl >= gate["pnl24h_usd"])

def phase108_capital_gate_tick():
    for venue in ["futures", "spot"]:
        if _venue_gate_green(venue):
            STATE["capital"]["venue_ticks_green"][venue] += 1
        else:
            STATE["capital"]["venue_ticks_green"][venue] = 0
            current_cap = STATE["capital"]["venue_cap_pct"][venue]
            reduced = max(0.0, current_cap - CFG.p108.retreat_pct_step)
            STATE["capital"]["venue_cap_pct"][venue] = reduced
            _append_event("phase108_retreat", {"venue": venue, "cap_pct": reduced})
        
        gate = CFG.p108.venue_scale_gate[venue]
        if STATE["capital"]["venue_ticks_green"][venue] >= gate["sustained_ticks"]:
            idx = STATE["capital"]["current_ramp_idx"][venue]
            if idx < len(CFG.p108.ramp_schedule_pct) - 1:
                idx += 1
                STATE["capital"]["current_ramp_idx"][venue] = idx
                STATE["capital"]["venue_cap_pct"][venue] = min(CFG.p108.max_venue_cap_pct[venue], CFG.p108.ramp_schedule_pct[idx])
                _append_event("phase108_ramp_advance", {"venue": venue, "ramp_idx": idx, "cap_pct": STATE["capital"]["venue_cap_pct"][venue]})
    
    _persist_state()

def phase108_get_venue_cap(venue: str) -> float:
    return STATE["capital"]["venue_cap_pct"].get(venue, 0.20)

# ======================================================================================
# Phase 10.9 - Autonomous Recovery
# ======================================================================================

def _recovery_freeze(minutes: int, reason: str):
    STATE["recovery"]["frozen_until_ts"] = int(time.time() + minutes * 60)
    STATE["recovery"]["last_anomaly"] = reason
    _append_event("phase109_freeze", {"minutes": minutes, "reason": reason})
    _persist_state()

def _recovery_unfreeze_if_ready():
    if STATE["recovery"]["frozen_until_ts"] and time.time() >= STATE["recovery"]["frozen_until_ts"]:
        STATE["recovery"]["frozen_until_ts"] = 0
        STATE["recovery"]["reactivation_ticks"] = 0
        _append_event("phase109_unfreeze", {})
        _persist_state()

def _anomaly_detect(symbol: str) -> Optional[str]:
    wr, sh = _calc_symbol_stats(symbol)
    slip_bps = _recent_exec_slippage_bps(symbol)
    
    if slip_bps >= CFG.p109.anomaly_slippage_bps_spike:
        return f"slippage_spike({slip_bps:.1f}bps)"
    if sh <= 0.2:
        return "sharpe_collapse"
    if wr <= 30.0:
        return "wr_collapse"
    return None

def phase109_recovery_tick(symbols: List[str]):
    anomaly_count = 0
    for sym in symbols:
        reason = _anomaly_detect(sym)
        if reason:
            anomaly_count += 1
            _append_event("phase109_mitigation", {"symbol": sym, "reason": reason})
            if anomaly_count >= 2:
                _recovery_freeze(CFG.p109.freeze_entries_min, f"multi_anomaly:{reason}")
    
    if anomaly_count == 0:
        STATE["recovery"]["reactivation_ticks"] += 1
        if STATE["recovery"]["reactivation_ticks"] >= CFG.p109.reactivation_sustained_ticks:
            _recovery_unfreeze_if_ready()

def phase109_is_frozen() -> bool:
    return STATE["recovery"]["frozen_until_ts"] > 0 and time.time() < STATE["recovery"]["frozen_until_ts"]

# ======================================================================================
# Trade closure hooks
# ======================================================================================

def phase107_on_trade_close(trade: Dict):
    symbol = trade.get("symbol")
    # CRITICAL: Use net P&L (after fees) for accurate outcome classification
    pnl = get_net_pnl(trade)
    outcome_positive = pnl > 0.0
    _update_prediction_quality(symbol, outcome_positive)
    _online_calibrate_weights(symbol)

# ======================================================================================
# Status & Bootstrap
# ======================================================================================

def get_phase107_109_status() -> Dict:
    return {
        "predictive": {
            "last_bias": STATE["predictive"]["last_bias"],
            "weights_count": len(STATE["predictive"]["weights_per_symbol"]),
            "prediction_quality": STATE["predictive"]["prediction_quality"]
        },
        "capital": {
            "venue_ticks_green": STATE["capital"]["venue_ticks_green"],
            "current_ramp_idx": STATE["capital"]["current_ramp_idx"],
            "venue_cap_pct": STATE["capital"]["venue_cap_pct"]
        },
        "recovery": {
            "is_frozen": phase109_is_frozen(),
            "frozen_until_ts": STATE["recovery"]["frozen_until_ts"],
            "reactivation_ticks": STATE["recovery"]["reactivation_ticks"],
            "last_anomaly": STATE["recovery"]["last_anomaly"]
        }
    }

def start_phase107_109():
    if os.path.exists(CFG.state_path):
        try:
            with open(CFG.state_path, "r") as f:
                loaded = json.load(f)
                STATE.update(loaded)
        except:
            pass
    
    _persist_state()
    _append_event("phase107_109_started", {
        "predictive_weights": {
            "trend": CFG.p107.w_trend_prob,
            "vol": CFG.p107.w_vol_forecast,
            "liquidity": CFG.p107.w_liquidity_score,
            "flow": CFG.p107.w_flow_signal
        },
        "capital_ramps": CFG.p108.ramp_schedule_pct,
        "recovery_freeze_min": CFG.p109.freeze_entries_min
    })
    
    print("🎯 Starting Phase 10.7-10.9...")
    print(f"   ℹ️  Phase 10.7 - Predictive Intelligence: per-symbol calibration")
    print(f"   ℹ️  Phase 10.8 - Capital Governance: ramp schedule {CFG.p108.ramp_schedule_pct}")
    print(f"   ℹ️  Phase 10.9 - Autonomous Recovery: anomaly detection + freeze")
    
    return (phase108_capital_gate_tick, phase109_recovery_tick)
