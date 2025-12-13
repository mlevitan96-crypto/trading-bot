# src/promotion_pruning_autotune.py
#
# Phase 12.5 – Promotion, Pruning & Auto-Tuning Autonomy
# Purpose: Fully automate learning, promotion, pruning, AND threshold evolution.
# - Collect rolling outcomes per coin+strategy
# - Auto-promote winners, auto-prune losers
# - Auto-tune ROI floors, confidence thresholds, profit targets nightly
# - Persist decisions to config/profit_policy.json
# - Log all events for auditability
#
# Integrates with: positions ledger, unified intelligence, governance

import os, json, time
from collections import defaultdict
from typing import Optional

# ---- Config paths ----
POS_LOG    = "logs/positions_learning.jsonl"
POLICY_CFG = "config/profit_policy.json"
EVENT_LOG  = "logs/unified_events.jsonl"

# Dynamic symbol loading from canonical config
try:
    from src.data_registry import DataRegistry as DR
    ALL_SYMBOLS = DR.get_enabled_symbols()
except ImportError:
    ALL_SYMBOLS = [
        "BTCUSDT","ETHUSDT","SOLUSDT","AVAXUSDT","DOTUSDT",
        "TRXUSDT","XRPUSDT","ADAUSDT","DOGEUSDT","BNBUSDT","MATICUSDT",
        "LINKUSDT","ARBUSDT","OPUSDT","PEPEUSDT"
    ]

ROLLING_WINDOW     = 50
PROMOTE_WINRATE    = 0.55
PRUNE_WINRATE      = 0.40
MAX_COLLATERAL_USD = 5000
MIN_COLLATERAL_USD = 100
BASE_COLLATERAL_USD_DEFAULT = 500

MIN_PROFIT_TARGETS_USD = {
    "BTCUSDT": 20, "ETHUSDT": 15, "SOLUSDT": 10, "AVAXUSDT": 10, "DOTUSDT": 10,
    "TRXUSDT": 5,  "XRPUSDT": 10, "ADAUSDT": 10, "DOGEUSDT": 5,  "BNBUSDT": 10, "MATICUSDT": 10,
    "DEFAULT": 10
}

VENUE_FEES = {"taker_pct": 0.0012, "maker_pct": 0.0008}
DEFAULT_SLIPPAGE_PCT = 0.0005
DEFAULT_SPREAD_PCT   = 0.0003

# ---- Helpers ----
def _read_jsonl(path):
    if not os.path.exists(path): return []
    out = []
    with open(path,"r") as f:
        for line in f:
            try: out.append(json.loads(line.strip()))
            except: continue
    return out

def _read_policy():
    if not os.path.exists(POLICY_CFG):
        return {"global":{"MIN_PROFIT_USD":20.0,"BASE_COLLATERAL_USD":BASE_COLLATERAL_USD_DEFAULT},
                "per_symbol":{},"per_strategy":{}}
    with open(POLICY_CFG,"r") as f: return json.load(f)

def _write_policy(cfg):
    os.makedirs(os.path.dirname(POLICY_CFG),exist_ok=True)
    with open(POLICY_CFG,"w") as f: json.dump(cfg,f,indent=2)

def _append_event(event, payload: Optional[dict] = None):
    if payload is None:
        payload = {}
    os.makedirs(os.path.dirname(EVENT_LOG),exist_ok=True)
    payload.update({"event":event,"ts":int(time.time())})
    with open(EVENT_LOG,"a") as f: f.write(json.dumps(payload)+"\n")

def profit_target_for(symbol):
    return MIN_PROFIT_TARGETS_USD.get(symbol,MIN_PROFIT_TARGETS_USD["DEFAULT"])

def estimate_costs(size_usd,taker=True):
    fee_pct = VENUE_FEES["taker_pct"] if taker else VENUE_FEES["maker_pct"]
    fees = size_usd*fee_pct*2
    slip = size_usd*DEFAULT_SLIPPAGE_PCT
    sprd = size_usd*DEFAULT_SPREAD_PCT
    return {"total_cost_usd":fees+slip+sprd}

# ---- Outcomes ----
def collect_outcomes():
    positions = _read_jsonl(POS_LOG)
    outcomes = defaultdict(lambda: defaultdict(list))
    for p in positions:
        if not p.get("closed"): continue
        sym = p.get("symbol")
        if sym not in ALL_SYMBOLS: continue
        strat = p.get("strategy","unknown")
        outcomes[sym][strat].append(p)
    return dict(outcomes)

def compute_stats(trades):
    trades = trades[-ROLLING_WINDOW:]
    wins = [t for t in trades if float(t.get("profit_usd",0))>0]
    net_pnl = sum(float(t.get("profit_usd",0)) for t in trades)
    avg_roi = sum(float(t.get("roi",0)) for t in trades)/len(trades) if trades else 0.0
    win_rate = len(wins)/len(trades) if trades else 0.0
    avg_size = sum(float(t.get("size_usd",BASE_COLLATERAL_USD_DEFAULT)) for t in trades)/len(trades) if trades else BASE_COLLATERAL_USD_DEFAULT
    costs = estimate_costs(avg_size)
    exp_profit_usd = avg_roi*avg_size
    net_edge_usd = exp_profit_usd-costs["total_cost_usd"]
    return {"samples":len(trades),"win_rate":win_rate,"net_pnl":net_pnl,
            "avg_roi":avg_roi,"avg_size_usd":avg_size,"net_edge_usd":net_edge_usd}

# ---- Promotion / Pruning ----
def promote_pair(policy,symbol,strategy,stats):
    key=f"{symbol}::{strategy}"
    strat_cfg=policy.setdefault("per_strategy",{}).setdefault(key,{})
    strat_cfg["disabled"]=False
    base=float(strat_cfg.get("BASE_COLLATERAL_USD",BASE_COLLATERAL_USD_DEFAULT))
    strat_cfg["BASE_COLLATERAL_USD"]=min(base*1.5,MAX_COLLATERAL_USD)
    strat_cfg["MIN_PROFIT_USD"]=max(float(strat_cfg.get("MIN_PROFIT_USD",profit_target_for(symbol))),
                                    profit_target_for(symbol))
    _append_event("strategy_promoted",{"symbol":symbol,"strategy":strategy,"stats":stats,"new_cfg":strat_cfg})

def prune_pair(policy,symbol,strategy,stats):
    key=f"{symbol}::{strategy}"
    strat_cfg=policy.setdefault("per_strategy",{}).setdefault(key,{})
    strat_cfg["disabled"]=True
    base=float(strat_cfg.get("BASE_COLLATERAL_USD",BASE_COLLATERAL_USD_DEFAULT))
    strat_cfg["BASE_COLLATERAL_USD"]=max(base*0.5,MIN_COLLATERAL_USD)
    floor=float(strat_cfg.get("MIN_PROFIT_USD",profit_target_for(symbol)))
    strat_cfg["MIN_PROFIT_USD"]=round(floor*1.2,2)
    _append_event("strategy_pruned",{"symbol":symbol,"strategy":strategy,"stats":stats,"new_cfg":strat_cfg})

# ---- Auto-Tuning thresholds ----
def autotune_thresholds(policy,symbol,stats):
    sym_cfg=policy.setdefault("per_symbol",{}).setdefault(symbol,{})
    
    # ROI floor tuning
    roi_floor=float(sym_cfg.get("MIN_ROI",0.003))
    if stats["win_rate"]>0.6 and stats["net_edge_usd"]>0:
        roi_floor=max(roi_floor-0.0002,0.0025)
    elif stats["win_rate"]<0.45 or stats["net_pnl"]<0:
        roi_floor+=0.0002
    sym_cfg["MIN_ROI"]=round(roi_floor,4)
    
    # Confidence threshold tuning
    conf_floor=float(sym_cfg.get("MIN_CONF",0.6))
    if stats["win_rate"]>0.65: conf_floor=max(conf_floor-0.02,0.5)
    elif stats["win_rate"]<0.4: conf_floor=min(conf_floor+0.02,0.8)
    sym_cfg["MIN_CONF"]=round(conf_floor,2)
    
    # Profit target tuning
    pt=float(sym_cfg.get("MIN_PROFIT_USD",profit_target_for(symbol)))
    if stats["net_pnl"]>profit_target_for(symbol): pt=max(pt-1,profit_target_for(symbol))
    elif stats["net_pnl"]<0: pt+=1
    sym_cfg["MIN_PROFIT_USD"]=round(pt,2)
    
    _append_event("thresholds_autotuned",{"symbol":symbol,"stats":stats,"new_cfg":sym_cfg})

# ---- Nightly runner ----
def run_autonomy_cycle():
    outcomes=collect_outcomes()
    policy=_read_policy()
    for symbol,strat_trades in outcomes.items():
        all_trades_for_symbol = []
        for strategy,trades in strat_trades.items():
            stats=compute_stats(trades)
            all_trades_for_symbol.extend(trades)
            if stats["samples"]>=ROLLING_WINDOW:
                if stats["win_rate"]>=PROMOTE_WINRATE and stats["net_edge_usd"]>0 and stats["net_pnl"]>=profit_target_for(symbol):
                    promote_pair(policy,symbol,strategy,stats)
                elif stats["win_rate"]<PRUNE_WINRATE or stats["net_pnl"]<0:
                    prune_pair(policy,symbol,strategy,stats)
        if all_trades_for_symbol:
            symbol_stats = compute_stats(all_trades_for_symbol)
            autotune_thresholds(policy,symbol,symbol_stats)
    _write_policy(policy)
    _append_event("autonomy_cycle_complete",{})

if __name__=="__main__":
    run_autonomy_cycle()
    print("Phase 12.5 autonomy cycle complete. Promotion, pruning, and thresholds auto-tuned.")
