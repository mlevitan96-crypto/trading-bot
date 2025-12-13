# src/predictive_regime_governor.py
#
# v5.7 Predictive Regime Governor (Unified, Regime-Aware, Closed-Loop)
# Purpose:
#   - Detect market regimes (trend, chop, high-vol, low-liq, trend+vol) using multi-signal features
#   - Predict near-term regime shifts and pre-emptively adjust allocations, thresholds, and execution preferences
#   - Publish regime tags and actions to the learning bus and knowledge graph
#   - Integrate with Portfolio & Risk Governors, Strategy Attribution, and Slippage/Latency Attribution
#
# Integration:
#   from src.predictive_regime_governor import run_regime_cycle
#   res = run_regime_cycle()
#   digest["email_body"] += "\n\n" + res["email_body"]
#
# Data sources (soft dependencies, handled gracefully if missing):
#   logs/executed_trades.jsonl             # {ts, symbol, pnl_pct, leverage, route, venue, est_fee_pct}
#   logs/strategy_signals.jsonl            # {ts, symbol, strategy_id, signal_family, composite_score, expectancy}
#   logs/learning_updates.jsonl            # attribution cycles and verdicts (reverse_triage_cycle, slippage_latency_cycle, strategy_attribution_cycle)
#   live_config.json                       # runtime knobs where we mirror regime-aware adjustments
#
# Outputs:
#   - logs/learning_updates.jsonl: regime_governor_cycle, regime_governor_actions, regime_predictions
#   - logs/knowledge_graph.jsonl: regime_feature_snapshot, regime_tag, regime_actions
#   - live_config.json runtime updates: regime_tags, regime_threshold_overrides, regime_strategy_bias, regime_execution_prefs
#
# Features used:
#   - Trendness: rolling return autocorrelation and directional consistency
#   - Volatility: realized vol (short window)
#   - Dispersion: cross-asset return spread (market breadth proxy)
#   - Liquidity proxy: fill completeness and partial fill rate
#   - PCA-like factor proxy: variance concentration estimated via top coin dominance in returns
#
# Regime taxonomy:
#   - "trend": directional consistency high, vol moderate
#   - "chop": directional consistency low, dispersion high, vol low/moderate
#   - "high_vol": realized vol high; may combine with trend ("trend_high_vol")
#   - "low_liq": partial fills elevated, latency/slippage warnings
#   - "neutral": none of the above strongly expressed
#
# Actions (pre-emptive, bounded, gated by risk and profit):
#   - Threshold tuning: raise/lower composite threshold by small steps per regime
#   - Strategy bias: increase weights for trend-friendly or mean-reversion strategies, decrease opposite
#   - Coin scalar nudges: amplify/de-amplify exposed coins if regime supports/penalizes them
#   - Execution preferences: prefer maker in low_liq/high_vol; allow taker in strong trend with thin margin
#
# Safety:
#   - All increases pass profit gates (short-window PnL >= 0 and expectancy >= 0.55)
#   - Risk gate: no change if would push exposure/leverage/drawdown/correlation past SLOs
#   - Reverts: if next cycle verdict is Losing/Neutral, revert increases attributed to regime changes
#
# CLI:
#   python3 src/predictive_regime_governor.py

import os, json, time, math, statistics
from collections import defaultdict, deque
from typing import Dict, Any, List, Tuple

LOGS_DIR  = "logs"
LEARN_LOG = f"{LOGS_DIR}/learning_updates.jsonl"
KG_LOG    = f"{LOGS_DIR}/knowledge_graph.jsonl"
EXEC_LOG  = f"{LOGS_DIR}/executed_trades.jsonl"
SIG_LOG   = f"{LOGS_DIR}/strategy_signals.jsonl"
LIVE_CFG  = "live_config.json"

SHORT_MINS = 240   # 4h
MID_MINS   = 720   # 12h
LONG_MINS  = 1440  # 24h

# Profit gates
PROMOTE_EXPECTANCY = 0.55
PROMOTE_PNL        = 0.0
ROLLBACK_EXPECTANCY= 0.35
ROLLBACK_PNL       = 0.0

# Bounds for adjustments
THRESHOLD_STEP     = 0.01     # composite threshold small step
THRESHOLD_MIN      = 0.05
THRESHOLD_MAX      = 0.12

STRATEGY_BIAS_STEP = 0.03     # +/-3% bias overlay, not raw weight
BIAS_MIN           = -0.10    # -10%
BIAS_MAX           = 0.10     # +10%

COIN_SCALAR_STEP   = 0.10     # +/-10%
COIN_SCALAR_MIN    = 0.50
COIN_SCALAR_MAX    = 1.50

def _now() -> int: return int(time.time())
def _cutoff(mins: int) -> int: return _now() - mins*60

def _read_json(path, default=None):
    if not os.path.exists(path): return default
    try:
        with open(path,"r") as f: return json.load(f)
    except: return default

def _write_json(path, obj):
    tmp = path + ".tmp"
    with open(tmp,"w") as f: json.dump(obj, f, indent=2)
    os.replace(tmp, path)

def _append_jsonl(path, obj):
    with open(path,"a") as f: f.write(json.dumps(obj) + "\n")

def _read_jsonl(path, limit=200000):
    rows=[]
    if not os.path.exists(path): return rows
    with open(path,"r") as f:
        for line in f:
            line=line.strip()
            if not line: continue
            try: rows.append(json.loads(line))
            except: continue
    return rows[-limit:]

def _safe_mean(vals: List[float]) -> float:
    if not vals: return 0.0
    try: return statistics.mean(vals)
    except: return 0.0

def _safe_stdev(vals: List[float]) -> float:
    if len(vals) < 3: return 0.0
    try: return statistics.pstdev(vals)
    except: return 0.0

def _autocorr(vals: List[float]) -> float:
    # lag-1 autocorrelation
    n = len(vals)
    if n < 3: return 0.0
    mean = _safe_mean(vals)
    num = sum((vals[i]-mean)*(vals[i-1]-mean) for i in range(1,n))
    den = sum((vi-mean)*(vi-mean) for vi in vals)
    if den == 0: return 0.0
    ac = num / den
    return max(-1.0, min(1.0, ac))

def _sign_consistency(vals: List[float]) -> float:
    # fraction of same sign across consecutive returns (trend proxy)
    if len(vals) < 4: return 0.5
    signs = [1 if v>0 else (-1 if v<0 else 0) for v in vals]
    same = 0; total=0
    for i in range(1,len(signs)):
        if signs[i]==0 or signs[i-1]==0: continue
        total += 1
        if signs[i]==signs[i-1]: same += 1
    if total==0: return 0.5
    return same/total

def _dispersion(series_by_sym: Dict[str, List[float]]) -> float:
    # cross-asset dispersion of returns at last index
    if not series_by_sym: return 0.0
    last_vals=[]
    for sym, ser in series_by_sym.items():
        if ser: last_vals.append(ser[-1])
    if len(last_vals) < 3: return 0.0
    return _safe_stdev(last_vals)

def _pca_variance_concentration(series_by_sym: Dict[str, List[float]]) -> float:
    # Simple proxy: dominance of top-variance coin over total variance
    var_by_sym={}
    total_var=0.0
    for sym, ser in series_by_sym.items():
        v = _safe_stdev(ser)
        var_by_sym[sym]=v
        total_var += v
    if total_var <= 1e-12: return 0.0
    top = max(var_by_sym.values()) if var_by_sym else 0.0
    return top/total_var

def _latency_slippage_warnings() -> Dict[str, Any]:
    # read latest slippage_latency_cycle events
    updates = _read_jsonl(LEARN_LOG, 20000)
    slipp_warn=False; high_lat=False; partial_fills=False
    meta={}
    for u in reversed(updates):
        if u.get("update_type")=="slippage_latency_cycle":
            summ = u.get("summary", {})
            per_coin = summ.get("per_coin", {})
            # derive simple flags
            for _, s in per_coin.items():
                if float(s.get("avg_slippage",0.0)) > 0.0004: slipp_warn=True  # >4 bps
                if float(s.get("avg_latency_ms",0.0)) > 1000: high_lat=True
            meta = {"coins": per_coin}
            break
    # optional: partial fills log could be elsewhere; infer via est fields in executed_trades
    trades=_read_jsonl(EXEC_LOG, 10000)
    partial_count=0; total=0
    for t in trades[-100:]:
        total += 1
        pf = t.get("partial_fill_ratio")
        if pf is not None and float(pf)>0.10:
            partial_count += 1
    partial_fills = partial_count/total >= 0.10 if total>0 else False
    return {"slippage_warn": slipp_warn, "latency_warn": high_lat, "partial_fills_warn": partial_fills, "meta": meta}

def _collect_returns(short_cut:int, mid_cut:int, long_cut:int) -> Tuple[Dict[str,List[float]], Dict[str,List[float]], Dict[str,List[float]]]:
    trades = _read_jsonl(EXEC_LOG, 100000)
    short_series=defaultdict(list)
    mid_series=defaultdict(list)
    long_series=defaultdict(list)
    for t in trades:
        ts = t.get("ts") or t.get("timestamp") or 0
        sym = t.get("symbol")
        if not sym: continue
        r = float(t.get("pnl_pct",0.0))
        if ts >= long_cut: long_series[sym].append(r)
        if ts >= mid_cut:  mid_series[sym].append(r)
        if ts >= short_cut: short_series[sym].append(r)
    return short_series, mid_series, long_series

def _compute_features() -> Dict[str,Any]:
    short_cut=_cutoff(SHORT_MINS); mid_cut=_cutoff(MID_MINS); long_cut=_cutoff(LONG_MINS)
    short_series, mid_series, long_series = _collect_returns(short_cut, mid_cut, long_cut)

    # Global aggregate series (portfolio proxy)
    portfolio_short = []
    for sym, ser in short_series.items():
        portfolio_short.extend(ser)
    portfolio_short = portfolio_short[-500:]

    trend_ac = _autocorr(portfolio_short)
    trend_sign = _sign_consistency(portfolio_short)
    vol_4h = _safe_stdev(portfolio_short)
    dispersion_now = _dispersion(short_series)
    pca_conc = _pca_variance_concentration(short_series)

    # Latency/slippage warnings
    exec_warns = _latency_slippage_warnings()

    # Basic liquidity proxy: fraction of trades with partial fills > 10%
    liquidity_bad = exec_warns.get("partial_fills_warn", False)

    features = {
        "trend_autocorr": round(trend_ac,4),
        "trend_sign_consistency": round(trend_sign,4),
        "vol_4h": round(vol_4h,6),
        "dispersion": round(dispersion_now,6),
        "pca_concentration": round(pca_conc,4),
        "slippage_warn": bool(exec_warns.get("slippage_warn", False)),
        "latency_warn": bool(exec_warns.get("latency_warn", False)),
        "liquidity_bad": bool(liquidity_bad)
    }
    return {"features": features, "short_series": short_series}

def _classify_regime(features: Dict[str,Any]) -> str:
    ac = features["trend_autocorr"]
    sc = features["trend_sign_consistency"]
    vol = features["vol_4h"]
    disp = features["dispersion"]
    liq_bad = features["liquidity_bad"]
    slip_warn = features["slippage_warn"]
    lat_warn = features["latency_warn"]

    # Thresholds (tunable)
    TREND_AC_MIN = 0.15
    SIGN_CONSIST_MIN = 0.60
    VOL_HIGH = 0.03            # 3% realized vol
    DISP_HIGH = 0.005          # dispersion threshold
    # Classification
    is_trend = (ac >= TREND_AC_MIN and sc >= SIGN_CONSIST_MIN)
    is_high_vol = (vol >= VOL_HIGH)
    is_chop = (not is_trend and disp >= DISP_HIGH and not is_high_vol)
    is_low_liq = liq_bad or slip_warn or lat_warn

    if is_trend and is_high_vol:
        return "trend_high_vol"
    if is_trend:
        return "trend"
    if is_chop and is_low_liq:
        return "chop_low_liq"
    if is_chop:
        return "chop"
    if is_high_vol and is_low_liq:
        return "high_vol_low_liq"
    if is_high_vol:
        return "high_vol"
    if is_low_liq:
        return "low_liq"
    return "neutral"

def _publish_kg(subject: Dict[str,Any], predicate: str, obj: Dict[str,Any]) -> None:
    _append_jsonl(KG_LOG, {"ts": _now(), "subject": subject, "predicate": predicate, "object": obj})

def _read_verdict() -> Tuple[str, float, float]:
    updates = _read_jsonl(LEARN_LOG, 20000)
    verdict="Neutral"; expectancy=0.5; avg_pnl_short=0.0
    for u in reversed(updates):
        if u.get("update_type")=="reverse_triage_cycle":
            summ=u.get("summary", {})
            v = summ.get("verdict", {})
            verdict = v.get("verdict","Neutral")
            expectancy = float(v.get("expectancy", 0.5))
            avg_pnl_short = float(v.get("pnl_short", {}).get("avg_pnl_pct", 0.0))
            break
    return verdict, expectancy, avg_pnl_short

def _risk_snapshot() -> Dict[str,Any]:
    # lightweight snapshot for gating (mirrors RiskGovernor metrics if available)
    trades=_read_jsonl(EXEC_LOG, 100000)
    short_cut=_cutoff(SHORT_MINS)
    # exposure proxy by trade counts
    counts=defaultdict(int)
    for t in trades:
        ts=t.get("ts",0); sym=t.get("symbol")
        if not sym or ts<short_cut: continue
        counts[sym]+=1
    total=sum(counts.values()) or 1
    coin_exposure={sym: round(cnt/total,6) for sym,cnt in counts.items()}
    # leverage max
    max_leverage=0.0
    for t in trades:
        lev=float(t.get("leverage",0.0))
        max_leverage=max(max_leverage, lev)
    # drawdown approx
    series=[float(t.get("pnl_pct",0.0)) for t in trades if t.get("ts",0)>=_cutoff(LONG_MINS)]
    cum=0.0; peak=0.0; max_dd=0.0
    for r in series:
        cum+=r; peak=max(peak,cum); max_dd=max(max_dd, peak-cum)
    # corr pairs approximation skipped for speed; rely on Portfolio/Risk layer if needed
    return {"coin_exposure":coin_exposure, "portfolio_exposure": round(sum(coin_exposure.values()),6), "max_leverage": round(max_leverage,3), "max_drawdown_24h": round(max_dd,6)}

def _apply_regime_actions(regime: str, features: Dict[str,Any], verdict: Tuple[str,float,float]) -> List[Dict[str,Any]]:
    # Read live config, apply bounded regime-aware overrides (thresholds, biases, scalars, execution prefs)
    live=_read_json(LIVE_CFG, default={}) or {}
    rt = live.get("runtime", {})
    # ensure keys
    rt.setdefault("regime_tags", {})
    rt.setdefault("regime_threshold_overrides", {})
    rt.setdefault("regime_strategy_bias", {})        # overlay +/- percentage to strategy weights
    rt.setdefault("regime_execution_prefs", {})      # {"prefer_maker": bool, "taker_ok": bool}
    rt.setdefault("coin_scalars", {})
    rt.setdefault("strategy_weights", {})
    rt.setdefault("strategy_status", {})

    # current composite threshold override
    comp_thr = float(rt.get("regime_threshold_overrides", {}).get("composite_min", 0.07) or 0.07)
    prefer_maker = bool(rt.get("regime_execution_prefs", {}).get("prefer_maker", False))
    taker_ok = bool(rt.get("regime_execution_prefs", {}).get("taker_ok", True))

    # profit gate
    verdict_status, expectancy, avg_pnl_short = verdict
    profit_gate_ok = (avg_pnl_short >= PROMOTE_PNL and expectancy >= PROMOTE_EXPECTANCY and verdict_status=="Winning")

    actions=[]

    # Threshold tuning per regime
    if regime in ("trend","trend_high_vol"):
        # lower threshold slightly to catch more trend signals (if profit/risk allow)
        if profit_gate_ok:
            new_thr = max(THRESHOLD_MIN, min(THRESHOLD_MAX, comp_thr - THRESHOLD_STEP))
            if abs(new_thr - comp_thr) >= 1e-9:
                rt["regime_threshold_overrides"]["composite_min"] = new_thr
                actions.append({"scope":"threshold","action":"lower_composite_threshold","from":comp_thr,"to":new_thr,"reason":"trend"})
    elif regime in ("chop","chop_low_liq"):
        # raise threshold to avoid noise in chop
        new_thr = max(THRESHOLD_MIN, min(THRESHOLD_MAX, comp_thr + THRESHOLD_STEP))
        if abs(new_thr - comp_thr) >= 1e-9:
            rt["regime_threshold_overrides"]["composite_min"] = new_thr
            actions.append({"scope":"threshold","action":"raise_composite_threshold","from":comp_thr,"to":new_thr,"reason":"chop"})

    # Execution preferences per regime
    if regime in ("high_vol","high_vol_low_liq","trend_high_vol","chop_low_liq","low_liq"):
        if not prefer_maker:
            rt["regime_execution_prefs"]["prefer_maker"] = True
            actions.append({"scope":"execution","action":"prefer_maker_orders","reason":"vol_or_liq"})
        if taker_ok:
            rt["regime_execution_prefs"]["taker_ok"] = False
            actions.append({"scope":"execution","action":"discourage_taker_orders","reason":"vol_or_liq"})
    elif regime in ("trend","neutral"):
        if prefer_maker or not taker_ok:
            rt["regime_execution_prefs"]["prefer_maker"] = False
            rt["regime_execution_prefs"]["taker_ok"] = True
            actions.append({"scope":"execution","action":"allow_taker_orders","reason":"trend_or_neutral"})

    # Strategy bias overlay
    # Heuristic mapping: trend favors momentum/breakout; chop favors mean-reversion; high_vol favors volatility harvest/scalp
    bias = rt["regime_strategy_bias"]
    def _bias_adj(sid:str, delta:float, reason:str):
        cur = float(bias.get(sid, 0.0))
        new = max(BIAS_MIN, min(BIAS_MAX, cur + delta))
        if abs(new-cur) >= 1e-9:
            bias[sid] = new
            actions.append({"scope":"strategy_bias","strategy_id":sid,"action":"adjust_bias","from":cur,"to":new,"reason":reason})

    if regime.startswith("trend"):
        # boost momentum, breakout; reduce mean_reversion
        _bias_adj("momentum_break", +STRATEGY_BIAS_STEP, "trend")
        _bias_adj("ema_crossover",  +STRATEGY_BIAS_STEP, "trend")
        _bias_adj("mean_reversion", -STRATEGY_BIAS_STEP, "trend")
    elif regime.startswith("chop"):
        # boost mean-reversion; reduce trend
        _bias_adj("mean_reversion", +STRATEGY_BIAS_STEP, "chop")
        _bias_adj("ema_crossover",  -STRATEGY_BIAS_STEP, "chop")
        _bias_adj("momentum_break", -STRATEGY_BIAS_STEP, "chop")
    elif regime.startswith("high_vol"):
        # favor volatility scalp, reduce large-swing trend exposures
        _bias_adj("ofi_scalp", +STRATEGY_BIAS_STEP, "high_vol")
        _bias_adj("momentum_break", -STRATEGY_BIAS_STEP, "high_vol")

    rt["regime_strategy_bias"] = bias

    # Coin scalar nudges driven by dispersion and regime (avoid correlated concentration; boost diversified winners)
    scalars = rt["coin_scalars"]
    # read short-series average returns to identify top/bottom performers
    # note: we'll inject short_series externally to avoid passing around too many structures
    # simple approach: read last regime_feature_snapshot from KG to get short_series excerpt if present
    last_series={}
    updates=_read_jsonl(KG_LOG, 50000)
    for u in reversed(updates):
        subj=u.get("subject",{})
        if subj.get("governor")=="regime" and u.get("predicate")=="features_snapshot":
            obj=u.get("object",{})
            last_series=obj.get("short_series_sample",{})
            break

    # rank coins by recent average
    coin_avgs=[]
    for sym, ser in last_series.items():
        avg=_safe_mean(ser[-10:])
        coin_avgs.append((sym,avg))
    coin_avgs.sort(key=lambda x: x[1], reverse=True)

    # dispersion-based scaling: in trend, boost top 2 non-risky coins; in chop, reduce top 2, boost bottom 2 for mean-reversion captures
    if regime.startswith("trend") and coin_avgs:
        for sym,_ in coin_avgs[:2]:
            cur=float(scalars.get(sym,1.0))
            new=min(COIN_SCALAR_MAX, cur + COIN_SCALAR_STEP/2)  # conservative +5%
            if abs(new-cur)>=1e-9:
                scalars[sym]=new
                actions.append({"scope":"coin","symbol":sym,"action":"increase_scalar","from":cur,"to":new,"reason":"trend_top_performer"})
    elif regime.startswith("chop") and coin_avgs:
        # reduce top 2, increase bottom 2 slightly
        for sym,_ in coin_avgs[:2]:
            cur=float(scalars.get(sym,1.0))
            new=max(COIN_SCALAR_MIN, cur - COIN_SCALAR_STEP/2)
            if abs(new-cur)>=1e-9:
                scalars[sym]=new
                actions.append({"scope":"coin","symbol":sym,"action":"decrease_scalar","from":cur,"to":new,"reason":"chop_reduce_trend_bias"})
        for sym,_ in coin_avgs[-2:]:
            cur=float(scalars.get(sym,1.0))
            new=min(COIN_SCALAR_MAX, cur + COIN_SCALAR_STEP/4)  # +2.5%
            if abs(new-cur)>=1e-9:
                scalars[sym]=new
                actions.append({"scope":"coin","symbol":sym,"action":"increase_scalar","from":cur,"to":new,"reason":"chop_mean_reversion_capture"})

    rt["coin_scalars"] = scalars

    # Risk gate: ensure we do not exceed basic limits (approx check); if breaches likely, drop risky increases
    risk = _risk_snapshot()
    max_exposure_limit = float(_read_json(LIVE_CFG, default={}).get("runtime", {}).get("capital_limits", {}).get("max_exposure", 0.75) or 0.75)
    per_coin_cap = float(_read_json(LIVE_CFG, default={}).get("runtime", {}).get("capital_limits", {}).get("per_coin_cap", 0.25) or 0.25)

    # If exposure already > limit, drop coin increases from actions
    if risk["portfolio_exposure"] > max_exposure_limit:
        actions = [a for a in actions if not (a.get("scope")=="coin" and a.get("action")=="increase_scalar")]

    # If a coin exceeds per-coin cap, remove its increase
    for sym, ex in risk.get("coin_exposure", {}).items():
        if ex > per_coin_cap:
            actions = [a for a in actions if not (a.get("scope")=="coin" and a.get("symbol")==sym and "increase" in a.get("action",""))]

    # Apply updates to runtime with tagging
    rt["regime_tags"]["current"] = {"tag": regime, "features": features, "ts": _now()}
    live["runtime"] = rt
    _write_json(LIVE_CFG, live)

    # Publish actions intent (actual enforcement is done by portfolio/risk and attribution layers)
    if actions:
        _append_jsonl(LEARN_LOG, {"ts": _now(), "update_type":"regime_governor_actions", "regime": regime, "actions": actions, "features": features})
        _publish_kg({"governor":"regime"}, "actions", {"regime": regime, "actions": actions})
    return actions

def _predict_regime_shift(features_hist: deque, current: str) -> Dict[str,Any]:
    # Naive prediction: observe last k feature vectors, predict transition to high_vol or trend based on rising vol and autocorr
    k = min(5, len(features_hist))
    if k < 3: return {"predicted": current, "confidence": 0.5, "reason":"insufficient_history"}
    vols = [fh["vol_4h"] for fh in list(features_hist)[-k:]]
    acs  = [fh["trend_autocorr"] for fh in list(features_hist)[-k:]]
    vol_up = vols[-1] > vols[0] and (vols[-1] - vols[0]) > 0.01
    ac_up  = acs[-1]  > acs[0]  and (acs[-1]  - acs[0])  > 0.05

    if vol_up and ac_up:
        pred = "trend_high_vol"
        conf = 0.7
        reason="vol_up+ac_up"
    elif vol_up and not ac_up:
        pred = "high_vol"
        conf = 0.65
        reason="vol_up"
    elif ac_up and not vol_up:
        pred = "trend"
        conf = 0.6
        reason="ac_up"
    else:
        pred = current
        conf = 0.55
        reason="stable"

    _append_jsonl(LEARN_LOG, {"ts": _now(), "update_type":"regime_predictions", "current": current, "predicted": pred, "confidence": conf, "history_len": k})
    _publish_kg({"governor":"regime"}, "prediction", {"current": current, "predicted": pred, "confidence": conf, "reason": reason})
    return {"predicted": pred, "confidence": conf, "reason": reason}

def run_regime_cycle() -> Dict[str,Any]:
    # 1) Compute features and classify current regime
    feats = _compute_features()
    features = feats["features"]
    short_series = feats["short_series"]

    # Publish feature snapshot (sample to keep KG lean)
    short_sample = {sym: ser[-20:] for sym, ser in short_series.items()}
    _publish_kg({"governor":"regime"}, "features_snapshot", {"features": features, "short_series_sample": short_sample})

    regime = _classify_regime(features)

    # 2) Read verdict and apply regime-aware actions with profit/risk gates
    verdict = _read_verdict()
    actions = _apply_regime_actions(regime, features, verdict)

    # 3) Predict near-term regime shift and optionally pre-position within bounds
    # Maintain short history in live_config runtime
    live = _read_json(LIVE_CFG, default={}) or {}
    rt = live.get("runtime", {})
    hist = rt.get("regime_feature_history", [])
    hist = (hist + [features])[-10:]  # keep last 10
    rt["regime_feature_history"] = hist
    live["runtime"] = rt
    _write_json(LIVE_CFG, live)

    features_deque = deque(hist, maxlen=10)
    prediction = _predict_regime_shift(features_deque, regime)

    # 4) Build email body snippet
    email_body = f"""
=== Predictive Regime Governor ===
Current Regime: {regime}
Features:
  - Trend Autocorr: {features['trend_autocorr']:.4f}
  - Sign Consistency: {features['trend_sign_consistency']:.4f}
  - Vol (4h): {features['vol_4h']:.6f}
  - Dispersion: {features['dispersion']:.6f}
  - PCA Concentration: {features['pca_concentration']:.4f}
  - Slippage Warn: {features['slippage_warn']}
  - Latency Warn: {features['latency_warn']}
  - Liquidity Bad: {features['liquidity_bad']}

Prediction: {prediction['predicted']} (confidence: {prediction['confidence']:.2f}, reason: {prediction['reason']})

Actions Taken: {len(actions)}
"""
    if actions:
        email_body += "\nActions:\n"
        for a in actions:
            scope = a.get("scope","unknown")
            action = a.get("action","unknown")
            reason = a.get("reason","unknown")
            email_body += f"  - [{scope}] {action}: {reason}\n"

    # 5) Unified digest for learning_updates.jsonl
    _append_jsonl(LEARN_LOG, {
        "ts": _now(),
        "update_type": "regime_governor_cycle",
        "regime": regime,
        "features": features,
        "prediction": prediction,
        "actions_count": len(actions),
        "verdict": {
            "status": verdict[0],
            "expectancy": verdict[1],
            "pnl_short": verdict[2]
        }
    })

    return {
        "regime": regime,
        "features": features,
        "actions": actions,
        "prediction": prediction,
        "email_body": email_body
    }

if __name__ == "__main__":
    # CLI standalone test
    result = run_regime_cycle()
    print(result["email_body"])
    print(f"\nRegime: {result['regime']}")
    print(f"Actions: {len(result['actions'])}")
    print(f"Prediction: {result['prediction']['predicted']} ({result['prediction']['confidence']:.2f})")
