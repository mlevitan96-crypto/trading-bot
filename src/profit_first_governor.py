# === Profit-First Governor (src/profit_first_governor.py) ===
# Purpose:
# - Make realized profit the sole scoreboard for nightly allocation decisions.
# - Promote/demote strategies and per-symbol routes based on net PnL and WR.
# - Demote chronic laggards (e.g., EMA-Futures) to paper if they drag WR/PnL below thresholds.
# - Elevate profitable symbols (e.g., BNBUSDT) to higher allocation caps.
# - Persist actions to live_config.runtime with audit logs.

import os, json, time, statistics
from collections import defaultdict

EXEC_LOG  = "logs/executed_trades.jsonl"
LIVE_CFG  = "live_config.json"
GOV_LOG   = "logs/profit_first_governor.jsonl"

def _now(): return int(time.time())
def _read_json(path):
    if not os.path.exists(path): return {}
    try: return json.load(open(path))
    except: return {}
def _write_json(path, obj):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w") as f: json.dump(obj, f, indent=2)
def _append_jsonl(path, row):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "a") as f: f.write(json.dumps(row) + "\n")
def _read_jsonl(path, limit=500000):
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

def run_profit_first_governor(window_hours=24, target_wr=0.40, demote_wr=0.25, demote_pnl=-5.0):
    cutoff=_now()-window_hours*3600
    execs=_read_jsonl(EXEC_LOG, 500000)
    sample=[r for r in execs if int(r.get("ts", _now()))>=cutoff]

    by_strategy=defaultdict(list)
    by_symbol=defaultdict(list)
    for r in sample:
        pnl=float(r.get("outcome",{}).get("pnl_usd", r.get("net_pnl",0.0)) or 0.0)
        strat=(r.get("strategy_id") or r.get("strategy") or "unknown").lower()
        sym=r.get("symbol","UNKNOWN")
        by_strategy[strat].append(pnl)
        by_symbol[sym].append(pnl)

    strat_metrics={}
    for s, arr in by_strategy.items():
        strat_metrics[s]={
            "n": len(arr),
            "wr": round(_wr(arr),3),
            "pnl": round(sum(arr),2),
            "avg": round((sum(arr)/(len(arr) or 1)),3)
        }
    sym_metrics={}
    for s, arr in by_symbol.items():
        sym_metrics[s]={
            "n": len(arr),
            "wr": round(_wr(arr),3),
            "pnl": round(sum(arr),2),
            "avg": round((sum(arr)/(len(arr) or 1)),3)
        }

    # Allocation decisions
    promotions=[]; demotions=[]; symbol_boosts=[]

    # Strategy demotion/promotion rules
    for s, m in strat_metrics.items():
        if m["n"]>=10 and (m["wr"]<demote_wr and m["pnl"]<demote_pnl):
            demotions.append({"strategy": s, "reason": "low WR & negative PnL", "metrics": m})
        elif m["n"]>=10 and (m["wr"]>=target_wr and m["pnl"]>0):
            promotions.append({"strategy": s, "reason": "meets target WR & positive PnL", "metrics": m})

    # Per-symbol boosts: elevate symbols with positive PnL and WR>=target
    for sym, m in sym_metrics.items():
        if m["n"]>=5 and m["wr"]>=target_wr and m["pnl"]>0:
            symbol_boosts.append({"symbol": sym, "reason":"profitable symbol", "metrics": m})

    cfg=_read_json(LIVE_CFG)
    rt=cfg.get("runtime",{}) or {}

    # Strategy allocation overlay
    alloc=rt.get("strategy_allocations",{}) or {}
    for d in demotions:
        s=d["strategy"]
        alloc[s]={"mode":"paper", "weight": max(0.05, float(alloc.get(s,{}).get("weight",0.20)) * 0.5)}
        # Hard demote known laggard EMA-Futures more aggressively
        if "ema" in s:
            alloc[s]["weight"]=min(alloc[s]["weight"], 0.05)
            alloc[s]["mode"]="paper"
    for p in promotions:
        s=p["strategy"]
        alloc[s]={"mode":"live", "weight": min(0.50, float(alloc.get(s,{}).get("weight",0.15)) * 1.5)}

    # Symbol route overlay (caps)
    sym_caps=rt.get("symbol_caps",{}) or {}
    for b in symbol_boosts:
        sym=b["symbol"]
        cap=float(sym_caps.get(sym,0.10))
        sym_caps[sym]=min(0.30, max(0.10, cap + 0.05))

    # Global sizing bias: only if portfolio is profitable over window
    portfolio_pnl=round(sum([float(r.get("outcome",{}).get("pnl_usd", r.get("net_pnl",0.0)) or 0.0) for r in sample]),2)
    wr_total=_wr([float(r.get("outcome",{}).get("pnl_usd", r.get("net_pnl",0.0)) or 0.0) for r in sample])
    if wr_total>=target_wr and portfolio_pnl>0:
        rt["size_throttle"]=min(1.00, float(rt.get("size_throttle",0.35)) + 0.10)
        rt["protective_mode"]=False
    else:
        # keep conservative unless evidence is strong
        rt["size_throttle"]=max(0.20, float(rt.get("size_throttle",0.35)))
        rt["protective_mode"]=True

    rt["strategy_allocations"]=alloc
    rt["symbol_caps"]=sym_caps
    rt["profit_first_overlay"]={
        "ts": _now(),
        "window_hours": window_hours,
        "portfolio_wr": round(wr_total,3),
        "portfolio_pnl": portfolio_pnl,
        "promotions": promotions,
        "demotions": demotions,
        "symbol_boosts": symbol_boosts
    }

    cfg["runtime"]=rt
    _write_json(LIVE_CFG, cfg)

    payload={
        "ts": _now(),
        "update_type": "profit_first_governor",
        "window_hours": window_hours,
        "portfolio_wr": round(wr_total,3),
        "portfolio_pnl": portfolio_pnl,
        "promotions": promotions,
        "demotions": demotions,
        "symbol_boosts": symbol_boosts,
        "allocations": alloc,
        "caps": sym_caps,
        "protective_mode": rt["protective_mode"],
        "size_throttle": rt["size_throttle"]
    }
    _append_jsonl(GOV_LOG, payload)
    print(f"💰 Profit-First Governor | WR={wr_total*100:.1f}% PnL={portfolio_pnl:.2f} | promo={len(promotions)} demo={len(demotions)} boosts={len(symbol_boosts)}")

    return payload
