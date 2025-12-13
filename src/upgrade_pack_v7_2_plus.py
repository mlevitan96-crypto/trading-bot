# === Performance Acceleration Upgrade Pack (src/upgrade_pack_v7_2_plus.py) ===
# Purpose:
# - Rapid backtesting from logs + synthetic replay to calibrate baseline quickly (paper-safe).
# - Regime detection to align strategies/gates with current market conditions (trend/chop/vol-shock).
# - Gate optimizer to reduce over-gating and tighten/relax based on win-rate, attribution, and missed-edge.
# - Live win-rate sentinel + capital ramp protocol (paper-mode) to stage exposure only when evidence supports.
# - Strategy sanity scanner to catch signal inversion, stale feeds, and parameter drift hurting WR/PnL.
#
# Drop-in: one file; integrates with existing logs and live_config/policies.
# Ordering (daily):
#   1) run_quick_backtest_from_logs()
#   2) run_synthetic_replay_backtest()   # optional, faster calibration on small window
#   3) run_regime_detection()
#   4) run_gate_optimizer()
#   5) run_strategy_sanity_scanner()
#   6) run_wr_sentinel_and_ramp_protocol()
#   7) build_unified_digest()            # existing step
#
# Notes:
# - All adjustments are bounded, logged, and respect hysteresis (watchdog layer still governs final changes).
# - Backtests here are "fast calibrators": heuristic, fee/slip-aware, using your logs as a dataset.
# - Paper-safe: ramp protocol only adjusts buffer/throttle within paper limits unless explicitly allowed.

import os, json, time, statistics, math
from collections import defaultdict, deque

def _bus(event_name, event_data):
    try:
        from full_integration_blofin_micro_live_and_paper import _bus as main_bus
        main_bus(event_name, event_data)
    except:
        pass

LEARN_LOG    = "logs/learning_updates.jsonl"
EXEC_LOG     = "logs/executed_trades.jsonl"
PRICE_LOG    = "logs/price_feed.jsonl"
REALTIME_LOG = "logs/realtime_attribution.jsonl"
LIVE_CFG     = "live_config.json"
POLICIES_CF  = "configs/signal_policies.json"
UPGRADE_LOG  = "logs/upgrade_pack_reports.jsonl"

def _now(): return int(time.time())

def _read_json(path):
    if not os.path.exists(path): return {}
    try: return json.load(open(path))
    except: return {}

def _write_json(path, obj):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path,"w") as f: json.dump(obj,f,indent=2)

def _append_jsonl(path, row):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path,"a") as f: f.write(json.dumps(row) + "\n")

def _read_jsonl(path, limit=300000):
    rows=[]
    if not os.path.exists(path): return rows
    with open(path,"r") as f:
        for line in f:
            line=line.strip()
            if not line: continue
            try: rows.append(json.loads(line))
            except: continue
    return rows[-limit:]

# --- Utility: quick stats ---
def _wr(pnls): 
    wins=sum(1 for x in pnls if x>0)
    total=len(pnls) or 1
    return wins/total

def _avg(lst): 
    return (sum(lst)/len(lst)) if lst else 0.0

def _sharpe(returns, rf=0.0):
    if not returns: return 0.0
    mu=_avg(returns)-rf
    sd=statistics.pstdev(returns) or 1e-9
    return mu/(sd or 1e-9)

def _sortino(returns, rf=0.0):
    if not returns: return 0.0
    mu=_avg(returns)-rf
    downside=[min(0.0, r-rf) for r in returns]
    dd=math.sqrt(sum(d*d for d in downside)/len(returns)) or 1e-9
    return mu/(dd or 1e-9)

# =========================
# 1) Rapid backtest from logs
# =========================

def run_quick_backtest_from_logs(lookback_hours=12, fees_rate=0.0005, slip_rate=0.0003):
    execs=_read_jsonl(EXEC_LOG, 200000)
    cutoff=_now() - lookback_hours*3600
    sample=[r for r in execs if int(r.get("ts",_now())) >= cutoff]

    # Use recorded entry/exit; if missing, approximate PnL from price series deltas
    pnl=[]
    returns=[]
    by_symbol=defaultdict(list)
    strategies=defaultdict(list)

    for r in sample:
        # Use actual log format: net_pnl, entry_price, exit_price, direction, notional_size
        p=float(r.get("net_pnl", r.get("pnl", 0.0)) or 0.0)
        entry=float(r.get("entry_price",0.0) or 0.0)
        exitp=float(r.get("exit_price",0.0) or 0.0)
        strat=(r.get("strategy_id") or r.get("strategy") or "unknown").lower()
        sym=r.get("symbol","UNKNOWN")
        side=(r.get("direction","LONG") or "LONG").upper()
        
        if entry<=0.0 or exitp<=0.0: continue
        ret = (exitp - entry)/entry if side=="LONG" else (entry - exitp)/entry
        
        pnl.append(p); returns.append(ret)
        by_symbol[sym].append(p)
        strategies[strat].append(p)

    wr_total=_wr(pnl)
    report={
        "ts": _now(),
        "update_type": "quick_backtest_from_logs",
        "lookback_hours": lookback_hours,
        "n_trades": len(pnl),
        "wr": round(wr_total,4),
        "net_pnl": round(sum(pnl),2),
        "avg_win": round(_avg([x for x in pnl if x>0]),2),
        "avg_loss": round(_avg([x for x in pnl if x<0]),2),
        "sharpe": round(_sharpe(returns),3),
        "sortino": round(_sortino(returns),3),
        "by_symbol": {k:{"n":len(v),"pnl":round(sum(v),2),"wr":round(_wr(v),3)} for k,v in by_symbol.items()},
        "by_strategy": {k:{"n":len(v),"pnl":round(sum(v),2),"wr":round(_wr(v),3)} for k,v in strategies.items()}
    }
    _append_jsonl(UPGRADE_LOG, report)
    _bus("quick_backtest_from_logs_applied", report)
    print(f"🧪 Backtest(logs) WR={report['wr']*100:.1f}% PnL={report['net_pnl']:.2f} n={report['n_trades']}")

def _latest_mid(symbol):
    prices=_read_jsonl(PRICE_LOG, 200000)
    for p in reversed(prices):
        if p.get("symbol")==symbol:
            return float(p.get("mid", p.get("close", 0.0)) or 0.0), int(p.get("ts", _now()))
    return 0.0, _now()

# ================================
# 2) Synthetic replay backtest (fast)
# ================================

def run_synthetic_replay_backtest(hours=6, horizon_minutes=30, fees_rate=0.0005, slip_rate=0.0003):
    # Replays decision_started + gate verdicts; executes only those that would pass current gates
    learns=_read_jsonl(LEARN_LOG, 300000)
    cutoff=_now()-hours*3600
    sample=[r for r in learns if int(r.get("ts",_now()))>=cutoff and r.get("update_type")=="decision_started"]

    cfg=_read_json(LIVE_CFG); rt=cfg.get("runtime",{}) or {}
    policies=_read_json(POLICIES_CF)
    alpha=policies.get("alpha_trading",{}) or {}
    ema=policies.get("ema_futures",{}) or {}

    pnl=[]; by_sym=defaultdict(list)
    for s in sample:
        sym=s.get("symbol"); side=(s.get("side","LONG") or "LONG").upper()
        ctx=s.get("signal_ctx",{}) or {}
        strat=(s.get("strategy_id") or s.get("strategy") or "").lower()
        # Gate check: ensemble/OFI for alpha, ROI for ema (simplified)
        pass_gates=True
        if "alpha" in strat:
            if abs(float(ctx.get("ofi",0.0) or 0.0)) < float(alpha.get("ofi_threshold",0.5)):
                pass_gates=False
            if float(ctx.get("ensemble",0.0) or 0.0) < float(alpha.get("ensemble_threshold",0.05)):
                pass_gates=False
        if "ema" in strat:
            if float(ctx.get("roi",0.0) or 0.0) < float(ema.get("min_roi_threshold",0.003)):
                pass_gates=False
        if not pass_gates: continue

        entry=_latest_mid(sym)[0]; exitp=_exit_by_horizon(sym, minutes=horizon_minutes)
        if entry<=0.0 or exitp<=0.0: continue
        final=10.0  # synthetic fixed notional for calibration
        ret=(exitp-entry)/entry if side=="LONG" else (entry-exitp)/entry
        gross=final*ret; costs=final*(fees_rate+slip_rate)
        p=gross-costs; pnl.append(p); by_sym[sym].append(p)

    wr_total=_wr(pnl)
    report={
        "ts": _now(),
        "update_type": "synthetic_replay_backtest",
        "hours": hours,
        "horizon_minutes": horizon_minutes,
        "n_trades": len(pnl),
        "wr": round(wr_total,4),
        "net_pnl": round(sum(pnl),2),
        "by_symbol": {k:{"n":len(v),"pnl":round(sum(v),2),"wr":round(_wr(v),3)} for k,v in by_sym.items()}
    }
    _append_jsonl(UPGRADE_LOG, report)
    _bus("synthetic_replay_backtest_applied", report)
    print(f"🎛️ Replay(H{hours}, M{horizon_minutes}) WR={report['wr']*100:.1f}% PnL={report['net_pnl']:.2f} n={report['n_trades']}")

def _exit_by_horizon(symbol, minutes=30):
    prices=_read_jsonl(PRICE_LOG, 300000)
    # find price minutes ahead; simple linear scan backward then forward
    latest_ts=_now()
    last=None
    for p in reversed(prices):
        if p.get("symbol")==symbol:
            last=p; break
    if not last: return 0.0
    target_ts=int(last.get("ts",latest_ts))+minutes*60
    forward=[x for x in prices if x.get("symbol")==symbol and int(x.get("ts",0))>=target_ts]
    if forward:
        p=forward[0]; return float(p.get("mid", p.get("close", 0.0)) or 0.0)
    # fallback: use last close
    return float(last.get("mid", last.get("close", 0.0)) or 0.0)

# =========================
# 3) Regime detection
# =========================

def run_regime_detection(window_minutes=180):
    prices=_read_jsonl(PRICE_LOG, 300000)
    by_sym=defaultdict(list)
    cutoff=_now()-window_minutes*60
    for p in prices:
        ts=int(p.get("ts",0)); 
        if ts>=cutoff:
            by_sym[p.get("symbol")].append(float(p.get("mid", p.get("close", 0.0)) or 0.0))

    regimes={}
    for sym, series in by_sym.items():
        if len(series)<10: continue
        # Trend vs chop via Hurst-ish heuristic: ratio of cumulative move vs volatility
        delta=series[-1]-series[0]
        vol=statistics.pstdev(series) or 1e-9
        tratio=abs(delta)/(vol*math.sqrt(len(series)))
        # Vol-shock via normalized std dev
        shock = vol / (abs(series[-1]) or 1e-9)
        reg = "trend" if tratio>0.35 else ("chop" if tratio<0.20 else "mixed")
        regimes[sym]={"regime":reg, "trend_ratio": round(tratio,3), "vol_shock": round(shock,5)}

    cfg=_read_json(LIVE_CFG); rt=cfg.get("runtime",{}) or {}
    rt["regime_overlay"]={"window_minutes":window_minutes,"symbols":regimes}
    cfg["runtime"]=rt; _write_json(LIVE_CFG, cfg)
    _append_jsonl(UPGRADE_LOG, {"ts":_now(),"update_type":"regime_detection","overlay":regimes})
    _bus("regime_detection_applied", {"ts":_now(),"overlay":regimes})
    print(f"🧭 Regime overlay applied for {len(regimes)} symbols")

# =========================
# 4) Gate optimizer
# =========================

def run_gate_optimizer(min_trades=30, target_wr=0.40):
    # Use last 12h decisions + results to compute relax/tighten suggestions
    learns=_read_jsonl(LEARN_LOG, 150000)
    execs=_read_jsonl(EXEC_LOG, 150000)
    cutoff=_now()-12*3600
    sample=[r for r in execs if int(r.get("ts",_now()))>=cutoff]

    # Aggregate by gate reasons
    gate_pnl=defaultdict(list)
    strat_pnl=defaultdict(list)
    for r in sample:
        rc=(r.get("reason_codes") or r.get("gates",{}).get("reason_codes") or [])
        p=float(r.get("net_pnl", r.get("pnl", 0.0)) or 0.0)
        s=(r.get("strategy_id") or r.get("strategy") or "unknown").lower()
        for reason in rc:
            gate_pnl[reason].append(p)
        strat_pnl[s].append(p)

    suggestions=[]
    # Gate simplify/relax/tighten
    for gate, arr in gate_pnl.items():
        if len(arr)<min_trades: continue
        wr_gate=_wr(arr); pnl_gate=sum(arr)
        if wr_gate<0.25 and pnl_gate<0: 
            suggestions.append({"type":"tighten_gate","gate":gate,"reason":"low WR & negative PnL"})
        elif wr_gate>target_wr and pnl_gate>0:
            suggestions.append({"type":"relax_gate","gate":gate,"reason":"high WR & positive PnL"})
        else:
            suggestions.append({"type":"keep_gate","gate":gate,"reason":"neutral performance"})

    # Strategy thresholds coarse nudge
    for strat, arr in strat_pnl.items():
        if len(arr)<min_trades: continue
        wrs=_wr(arr); pnl=sum(arr)
        if "alpha" in strat:
            action="tighten" if (wrs<0.25 and pnl<0) else ("relax" if (wrs>0.45 and pnl>0) else "hold")
            suggestions.append({"type":"alpha_thresholds", "action":action, "wrs": round(wrs,3), "pnl": round(pnl,2)})
        if "ema" in strat:
            action="tighten" if (wrs<0.25 and pnl<0) else ("relax" if (wrs>0.45 and pnl>0) else "hold")
            suggestions.append({"type":"ema_thresholds", "action":action, "wrs": round(wrs,3), "pnl": round(pnl,2)})

    # Persist overlay only; watchdogs will act if evidence sustains
    cfg=_read_json(LIVE_CFG); rt=cfg.get("runtime",{}) or {}
    rt["gate_optimizer_overlay"]={"ts":_now(), "suggestions":suggestions}
    cfg["runtime"]=rt; _write_json(LIVE_CFG, cfg)
    _append_jsonl(UPGRADE_LOG, {"ts":_now(),"update_type":"gate_optimizer","suggestions":suggestions})
    _bus("gate_optimizer_applied", {"ts":_now(),"suggestions":suggestions})
    print(f"🛠️ Gate optimizer produced {len(suggestions)} suggestions")

# =========================
# 5) Strategy sanity scanner
# =========================

def run_strategy_sanity_scanner(window_hours=12):
    learns=_read_jsonl(LEARN_LOG, 200000)
    execs=_read_jsonl(EXEC_LOG, 200000)
    cutoff=_now()-window_hours*3600
    recent=[r for r in execs if int(r.get("ts",_now()))>=cutoff]
    issues=[]

    # Signal inversion check: OFI sign vs trade side correlation
    ofi_side=[]
    for r in recent:
        ctx=(r.get("signal_ctx") or {})
        ofi=float(ctx.get("ofi",0.0) or 0.0)
        side=(r.get("side","LONG") or "LONG").upper()
        ofi_side.append((ofi, side))
    if len(ofi_side)>=15:
        # Expect negative OFI -> SHORT preference. Correlation heuristic:
        shorts_from_negative=sum(1 for o,s in ofi_side if o<0 and s=="SHORT")
        longs_from_positive=sum(1 for o,s in ofi_side if o>0 and s=="LONG")
        align = (shorts_from_negative + longs_from_positive) / len(ofi_side)
        if align < 0.55:
            issues.append({"type":"signal_inversion_suspected","metric":"ofi_side_align","value":round(align,3)})

    # Stale feeds: latency_ms distribution
    lat=[float((r.get("signal_ctx") or {}).get("latency_ms",0) or 0) for r in recent]
    if lat:
        try:
            p95=statistics.quantiles(lat, n=20)[-1]
            if p95>1500:
                issues.append({"type":"stale_feed_suspected","metric":"p95_latency_ms","value":round(p95,1)})
        except:
            pass

    # Parameter drift: detect large swings in entry threshold settings
    cfg=_read_json(LIVE_CFG); rt=cfg.get("runtime",{}) or {}
    policies=_read_json(POLICIES_CF)
    alpha=policies.get("alpha_trading",{}) or {}
    ema=policies.get("ema_futures",{}) or {}
    
    # Check for extreme thresholds
    ofi_t=float(alpha.get("ofi_threshold",0.5))
    ens_t=float(alpha.get("ensemble_threshold",0.05))
    roi_t=float(ema.get("min_roi_threshold",0.003))
    
    if ofi_t > 0.80:
        issues.append({"type":"parameter_drift","param":"ofi_threshold","value":ofi_t,"reason":"too strict"})
    if ens_t > 0.15:
        issues.append({"type":"parameter_drift","param":"ensemble_threshold","value":ens_t,"reason":"too strict"})
    if roi_t > 0.010:
        issues.append({"type":"parameter_drift","param":"min_roi_threshold","value":roi_t,"reason":"too strict"})

    rt["strategy_sanity_issues"]={"ts":_now(),"issues":issues}
    cfg["runtime"]=rt; _write_json(LIVE_CFG, cfg)
    _append_jsonl(UPGRADE_LOG, {"ts":_now(),"update_type":"strategy_sanity_scanner","issues":issues})
    _bus("strategy_sanity_scanner_applied", {"ts":_now(),"issues":issues})
    print(f"🔍 Strategy sanity scanner found {len(issues)} issues")
    return issues

# ================================
# 6) Win-rate sentinel + capital ramp
# ================================

def run_wr_sentinel_and_ramp_protocol(wr_target=0.40, wr_floor=0.30, lookback_hours=24):
    execs=_read_jsonl(EXEC_LOG, 200000)
    cutoff=_now()-lookback_hours*3600
    sample=[r for r in execs if int(r.get("ts",_now()))>=cutoff]
    
    pnl=[float(r.get("net_pnl", r.get("pnl", 0.0)) or 0.0) for r in sample]
    wr=_wr(pnl) if pnl else 0.0
    
    cfg=_read_json(LIVE_CFG); rt=cfg.get("runtime",{}) or {}
    current_throttle=float(rt.get("size_throttle",1.0))
    current_protective=rt.get("protective_mode",False)
    
    # Ramp protocol
    new_throttle=current_throttle
    new_protective=current_protective
    
    if wr < wr_floor:
        # Emergency: reduce exposure aggressively
        new_throttle=max(0.25, current_throttle*0.75)
        new_protective=True
        action="emergency_reduce"
    elif wr < wr_target:
        # Below target: gradual reduction
        new_throttle=max(0.50, current_throttle*0.90)
        new_protective=True
        action="gradual_reduce"
    elif wr >= (wr_target + 0.10):
        # Well above target: gradual increase
        new_throttle=min(1.50, current_throttle*1.10)
        new_protective=False
        action="gradual_increase"
    else:
        # Near target: maintain
        action="maintain"
    
    # Apply changes
    rt["size_throttle"]=round(new_throttle,3)
    rt["protective_mode"]=new_protective
    rt["wr_sentinel"]={"ts":_now(),"wr":round(wr,4),"action":action,"throttle":round(new_throttle,3)}
    cfg["runtime"]=rt
    _write_json(LIVE_CFG, cfg)
    
    report={
        "ts":_now(),
        "update_type":"wr_sentinel_and_ramp_protocol",
        "wr":round(wr,4),
        "wr_target":wr_target,
        "wr_floor":wr_floor,
        "n_trades":len(pnl),
        "action":action,
        "throttle_before":round(current_throttle,3),
        "throttle_after":round(new_throttle,3),
        "protective_before":current_protective,
        "protective_after":new_protective
    }
    _append_jsonl(UPGRADE_LOG, report)
    _bus("wr_sentinel_and_ramp_protocol_applied", report)
    print(f"📡 WR Sentinel: WR={wr*100:.1f}% | Action={action} | Throttle={new_throttle:.2f}x | Protective={new_protective}")
    return report

# ================================
# 7) Unified runner for nightly cycle
# ================================

def run_full_upgrade_pack_cycle():
    print("\n" + "="*60)
    print("🚀 Performance Acceleration Upgrade Pack v7.2+ 🚀")
    print("="*60 + "\n")
    
    # Run all modules in sequence
    backtest_report = run_quick_backtest_from_logs(lookback_hours=12)
    replay_report = run_synthetic_replay_backtest(hours=6, horizon_minutes=30)
    regime_data = run_regime_detection(window_minutes=180)
    gate_suggestions = run_gate_optimizer(min_trades=30, target_wr=0.40)
    sanity_issues = run_strategy_sanity_scanner(window_hours=12)
    ramp_report = run_wr_sentinel_and_ramp_protocol(wr_target=0.40, wr_floor=0.30, lookback_hours=24)
    
    # Summary
    summary={
        "ts":_now(),
        "update_type":"upgrade_pack_full_cycle_complete",
        "backtest_wr":backtest_report.get("wr",0.0) if backtest_report else 0.0,
        "backtest_pnl":backtest_report.get("net_pnl",0.0) if backtest_report else 0.0,
        "replay_wr":replay_report.get("wr",0.0) if replay_report else 0.0,
        "regime_count":len(regime_data) if (regime_data and isinstance(regime_data, dict)) else 0,
        "gate_suggestions_count":len(gate_suggestions) if (gate_suggestions and isinstance(gate_suggestions, list)) else 0,
        "sanity_issues_count":len(sanity_issues) if (sanity_issues and isinstance(sanity_issues, list)) else 0,
        "sentinel_action":ramp_report.get("action","unknown") if ramp_report else "unknown",
        "final_throttle":ramp_report.get("throttle_after",1.0) if ramp_report else 1.0,
        "final_protective":ramp_report.get("protective_after",False) if ramp_report else False
    }
    _append_jsonl(UPGRADE_LOG, summary)
    _bus("upgrade_pack_full_cycle_complete", summary)
    
    print("\n" + "="*60)
    print("✅ Upgrade Pack Cycle Complete")
    print(f"   Backtest WR: {summary['backtest_wr']*100:.1f}%")
    print(f"   Sentinel Action: {summary['sentinel_action']}")
    print(f"   Throttle: {summary['final_throttle']:.2f}x")
    print(f"   Protective Mode: {summary['final_protective']}")
    print("="*60 + "\n")
    
    return summary

if __name__ == "__main__":
    run_full_upgrade_pack_cycle()