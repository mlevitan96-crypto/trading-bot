# File: src/scenario_slicer_auto_tuner_v2.py
# Patch adds dual-mode gates, expanded slices, stronger counterfactuals, and rollback.

import os, json, time, statistics, random
from collections import defaultdict

ENRICHED_EXEC = "logs/enriched_decisions.jsonl"
ENRICHED_BLOCK = "logs/enriched_blocked_signals.jsonl"
LIVE_CFG = "live_config.json"
POLICIES = "configs/signal_policies.json"
TUNE_LOG = "logs/scenario_slicer_auto_tuner_v2.jsonl"

SYMBOLS_WHITELIST = [
    "BTCUSDT","ETHUSDT","BNBUSDT","SOLUSDT","AVAXUSDT","DOGEUSDT",
    "DOTUSDT","ADAUSDT","MATICUSDT","LTCUSDT","XRPUSDT"
]

def _now(): return int(time.time())
def _append_jsonl(path, row):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "a") as f: f.write(json.dumps(row) + "\n")
def _read_json(path):
    if not os.path.exists(path): return {}
    try: return json.load(open(path))
    except: return {}
def _write_json(path, obj):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w") as f: json.dump(obj, f, indent=2)
def _read_jsonl(path, limit=1000000):
    rows=[]
    if not os.path.exists(path): return rows
    with open(path,"r") as f:
        for line in f:
            line=line.strip()
            if not line: continue
            try: rows.append(json.loads(line))
            except: continue
    return rows[-limit:]

def _wr(pnls):
    wins=sum(1 for x in pnls if x>0)
    total=len(pnls) or 1
    return wins/total

def _score(pnls, target_wr=0.40, cf_bonus=0.0):
    wr=_wr(pnls); pnl=sum(pnls)
    stdev = statistics.pstdev(pnls) if pnls else 0.0
    return {"wr": wr, "pnl": pnl, "stability_penalty": stdev,
            "score": pnl + (wr - target_wr)*100.0 - stdev*0.5 + cf_bonus}

def _ctx(record):
    c = record.get("signal_ctx", {}) or {}
    return {
        "ofi": float(c.get("ofi") or c.get("ofi_score") or c.get("ofi_value") or 0.0),
        "ens": float(c.get("ensemble") or c.get("ens") or 0.0),
        "roi": float(c.get("roi") or c.get("min_roi") or 0.0),
        "vol": float(c.get("volatility") or c.get("vol") or 0.0),
        "liq": float(c.get("liquidity") or c.get("liq") or 0.0),
        "side": (c.get("side") or "").lower(),
        "trend": float(c.get("trend") or 0.0),      # e.g., normalized slope or ADX/EMA slope
        "session": int(c.get("session") or -1)      # 0=Asia,1=EU,2=US (derive in enrichment)
    }

def _direction(record):
    side = (record.get("side") or record.get("direction") or "").lower()
    if side in ("long","buy"): return "long"
    if side in ("short","sell"): return "short"
    cs = _ctx(record)["side"]
    if cs in ("long","short"): return cs
    return "long"

def _bin(x, edges):
    for i,e in enumerate(edges):
        if x <= e: return i
    return len(edges)

def _gate_combos():
    return [
        {"name":"ofi_only", "use_ofi":True, "use_ens":False, "use_roi":False},
        {"name":"ens_only", "use_ofi":False, "use_ens":True, "use_roi":False},
        {"name":"roi_only", "use_ofi":False, "use_ens":False, "use_roi":True},
        {"name":"ofi_plus_ens", "use_ofi":True, "use_ens":True, "use_roi":False},
        {"name":"ofi_plus_roi", "use_ofi":True, "use_ens":False, "use_roi":True},
        {"name":"ens_plus_roi", "use_ofi":False, "use_ens":True, "use_roi":True},
        {"name":"all_three", "use_ofi":True, "use_ens":True, "use_roi":True},
    ]

def _param_grid(baselines):
    ofi0, ens0, roi0 = baselines
    ofi_grid=[round(ofi0+d,3) for d in (-0.10,-0.08,-0.06,-0.04,-0.02,0.0,0.02,0.04,0.06,0.08,0.10)]
    ens_grid=[round(ens0+d,3) for d in (-0.03,-0.02,-0.01,0.0,0.01,0.02,0.03)]
    roi_grid=[round(roi0+d,6) for d in (-0.003,-0.002,-0.001,0.0,0.001,0.002,0.003)]
    return ofi_grid, ens_grid, roi_grid

def _replay_rows(rows, combo, th):
    ofi_th, ens_th, roi_th = th
    pnls=[]
    for r in rows:
        c=_ctx(r)
        pnl=float(r.get("outcome",{}).get("pnl_usd", 0.0) or 0.0)
        take=True
        if combo["use_ofi"]: take = take and (abs(c["ofi"]) >= ofi_th)
        if combo["use_ens"]: take = take and (abs(c["ens"]) >= ens_th)
        if combo["use_roi"]: take = take and (abs(c["roi"]) >= roi_th)
        pnls.append(pnl if take else 0.0)
    return pnls

def _compute_cf_bonus(block_rows, combo, th, weight=1.0):
    pnls_cf = _replay_rows(block_rows, combo, th)
    pnl=sum(pnls_cf); wr=_wr(pnls_cf)
    # Stronger counterfactual influence to unlock missed edge, capped for safety
    base = pnl + (wr-0.40)*50.0
    return min(75.0, max(0.0, base * weight))

def _apply_conditional_policy(cfg, policy_key, th, res):
    # Persist conditional policy
    policies=_read_json(POLICIES)
    cond = policies.get("conditional_policies", []) or []
    cond=[p for p in cond if not all(p[k]==policy_key[k] for k in policy_key)]
    cond.append({
        **policy_key,
        "ts": _now(),
        "thresholds": {"ofi": th[0], "ensemble": th[1], "roi": th[2]},
        "expected": {"wr": res["wr"], "pnl": res["pnl"], "score": res["score"]}
    })
    policies["conditional_policies"]=cond
    _write_json(POLICIES, policies)

    # Activate overlay live
    cfg = cfg or _read_json(LIVE_CFG)
    rt = cfg.get("runtime", {}) or {}
    overlays = rt.get("conditional_overlays", []) or []
    overlays=[o for o in overlays if not all(o.get(k)==policy_key[k] for k in policy_key)]
    overlays.append({**policy_key, "thresholds": {"ofi": th[0], "ensemble": th[1], "roi": th[2]}})
    rt["conditional_overlays"]=overlays

    # Safety posture: relax only if robust
    rt["protective_mode"]=False if res["wr"]>=0.40 and res["pnl"]>0 else True
    rt["size_throttle"]=min(1.00, max(0.25, float(rt.get("size_throttle",0.35)) + (res["score"]>0)*0.05))

    # Rollback checkpoint
    rt["conditional_overlays_checkpoint"]={"ts": _now(), "policy_key": policy_key, "metrics_expected": res}
    cfg["runtime"]=rt
    _write_json(LIVE_CFG, cfg)

def _record_exploration_candidate(policy_key, th, res):
    # Store candidate overlays for exploration (no live activation)
    _append_jsonl(TUNE_LOG, {"ts": _now(), "update_type":"exploration_candidate",
                             "policy_key": policy_key,
                             "thresholds": {"ofi": th[0], "ensemble": th[1], "roi": th[2]},
                             "res": res})

def run_scenario_slicer_auto_tuner_v2(window_days=14,
                                      strict_wr=0.40, strict_pnl=0.0,
                                      explore_wr=0.30, explore_pnl=-10.0,
                                      max_slices=500, cf_weight=1.0):
    cutoff=_now()-window_days*86400
    exec_rows=_read_jsonl(ENRICHED_EXEC, 1000000)
    block_rows=_read_jsonl(ENRICHED_BLOCK, 1000000)

    exec_rows=[r for r in exec_rows if r.get("symbol") in SYMBOLS_WHITELIST and int(r.get("ts",_now()))>=cutoff]
    block_rows=[r for r in block_rows if r.get("symbol") in SYMBOLS_WHITELIST and int(r.get("ts",_now()))>=cutoff]

    if not exec_rows:
        _append_jsonl(TUNE_LOG, {"ts": _now(), "update_type":"no_exec_data"})
        return

    cfg=_read_json(LIVE_CFG)
    policies=_read_json(POLICIES)
    ofi0=float(policies.get("alpha_trading",{}).get("ofi_threshold",0.50))
    ens0=float(policies.get("alpha_trading",{}).get("ensemble_threshold",0.05))
    roi0=float(policies.get("ema_futures",{}).get("min_roi_threshold",0.003))
    ofi_grid, ens_grid, roi_grid=_param_grid((ofi0, ens0, roi0))
    combos=_gate_combos()

    # Build slices: symbol, direction, vol, liq, trend, session
    slices=defaultdict(list)
    for r in exec_rows:
        sym=r.get("symbol","UNKNOWN")
        dirn=_direction(r)
        c=_ctx(r)
        vol_bin=_bin(c["vol"], [10,20,35,60])
        liq_bin=_bin(c["liq"], [1e5,5e5,1e6])
        trend_bin=_bin(c["trend"], [-0.5,-0.2,0.0,0.2,0.5])
        session_bin=c["session"] if c["session"] in (0,1,2) else 3  # 3=unknown
        key=(sym,dirn,vol_bin,liq_bin,trend_bin,session_bin)
        slices[key].append(r)

    keys=list(slices.keys()); random.shuffle(keys); keys=keys[:max_slices]

    applied=0; explored=0; considered=0
    for key in keys:
        sym, dirn, vol_bin, liq_bin, trend_bin, session_bin = key
        rows=slices[key]
        if len(rows) < 20: continue

        # Blocked slice match
        block_slice=[b for b in block_rows
                     if (b.get("symbol")==sym and _direction(b)==dirn
                         and _bin(_ctx(b)["vol"], [10,20,35,60])==vol_bin
                         and _bin(_ctx(b)["liq"], [1e5,5e5,1e6])==liq_bin
                         and _bin(_ctx(b)["trend"], [-0.5,-0.2,0.0,0.2,0.5])==trend_bin
                         and ((_ctx(b)["session"] if _ctx(b)["session"] in (0,1,2) else 3)==session_bin))]

        best=None
        for combo in combos:
            for ofi_th in (ofi_grid if combo["use_ofi"] else [ofi0]):
                for ens_th in (ens_grid if combo["use_ens"] else [ens0]):
                    for roi_th in (roi_grid if combo["use_roi"] else [roi0]):
                        pnls=_replay_rows(rows, combo, (ofi_th,ens_th,roi_th))
                        cf_bonus=_compute_cf_bonus(block_slice, combo, (ofi_th,ens_th,roi_th), weight=cf_weight) if block_slice else 0.0
                        res=_score(pnls, target_wr=strict_wr, cf_bonus=cf_bonus)
                        considered+=1
                        _append_jsonl(TUNE_LOG, {
                            "ts": _now(),
                            "slice": {"symbol": sym, "direction": dirn, "vol_bin": vol_bin,
                                      "liq_bin": liq_bin, "trend_bin": trend_bin, "session_bin": session_bin},
                            "combo": combo["name"],
                            "thresholds": {"ofi": ofi_th, "ensemble": ens_th, "roi": roi_th},
                            "res": res, "cf_bonus": cf_bonus, "blocked_count": len(block_slice)
                        })
                        if (best is None) or (res["score"] > best["res"]["score"]):
                            best={"combo": combo["name"], "th": (ofi_th,ens_th,roi_th), "res": res}

        policy_key={"symbol": sym, "direction": dirn, "vol_bin": vol_bin,
                    "liq_bin": liq_bin, "trend_bin": trend_bin, "session_bin": session_bin,
                    "combo": best["combo"] if best else "none"}

        # Strict deployment gate
        if best and best["res"]["wr"]>=strict_wr and best["res"]["pnl"]>strict_pnl:
            _apply_conditional_policy(cfg, policy_key, best["th"], best["res"])
            applied+=1
            _append_jsonl(TUNE_LOG, {"ts": _now(), "update_type":"slice_winner_applied",
                                     "slice": policy_key, "winner": best})
        # Exploration candidate: log only, no live changes
        elif best and best["res"]["wr"]>=explore_wr and best["res"]["pnl"]>=explore_pnl:
            _record_exploration_candidate(policy_key, best["th"], best["res"])
            explored+=1
        else:
            _append_jsonl(TUNE_LOG, {"ts": _now(), "update_type":"slice_winner_rejected",
                                     "slice": policy_key, "reason":"fails strict & explore gates",
                                     "candidate": best})

    print(f"🧭 Slicer v2 (dual-mode) | applied={applied} explored={explored} considered={considered}")

    # Protective stance if nothing applied
    if applied == 0:
        cfg=_read_json(LIVE_CFG)
        rt=cfg.get("runtime",{}) or {}
        rt["protective_mode"]=True
        cfg["runtime"]=rt
        _write_json(LIVE_CFG, cfg)

# --- Rollback hook (call after each winner applied; run via watchdog every 6h) ---
def rollback_on_degradation(min_wr=0.40, min_pnl=0.0, lookback_hours=6):
    cfg=_read_json(LIVE_CFG)
    rt=cfg.get("runtime",{}) or {}
    cp=rt.get("conditional_overlays_checkpoint")
    if not cp: return
    cutoff=_now()-lookback_hours*3600
    rows=_read_jsonl(ENRICHED_EXEC, 200000)
    rows=[r for r in rows if int(r.get("ts",_now()))>=cutoff]
    pnls=[float(r.get("outcome",{}).get("pnl_usd",0.0) or 0.0) for r in rows]
    wr=_wr(pnls); pnl=sum(pnls)
    if wr<min_wr or pnl<=min_pnl:
        # Revert last overlay activation by clearing conditional_overlays
        rt["conditional_overlays"] = []
        rt["protective_mode"]=True
        rt["size_throttle"]=max(0.25, float(rt.get("size_throttle",0.35)) - 0.05)
        rt["conditional_overlays_checkpoint"]=None
        cfg["runtime"]=rt
        _write_json(LIVE_CFG, cfg)
        _append_jsonl(TUNE_LOG, {"ts": _now(), "update_type":"rollback_applied",
                                 "reason":"degradation", "wr": wr, "pnl": pnl})
