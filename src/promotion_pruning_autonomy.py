# src/promotion_pruning_autonomy.py
#
# Phase 12.0 – Promotion & Pruning Autonomy (Learning Mode)
# Purpose: Close the loop so the bot not only learns but acts on that learning automatically.
# - Rolling outcomes per coin+strategy (50 trades)
# - Promotion gates (auto-enable & scale) and pruning gates (auto-down-weight & pause)
# - Budget reallocation and profit-floor tuning
# - Governance integration (nightly run), event logging, and policy updates
#
# Integrates with:
# - positions ledger (executed or simulated trades in learning mode)
# - policy config (per-symbol and per-strategy overrides)
# - unified governance/intelligence modules already in place
#
# Notes:
# - Learning mode: no real money moved; this manages policy and allocations for eventual promotion.
# - Net edge check leverages cost model (fees+slippage+spread) when available; falls back to pnl gates.

import os
import json
import time
from collections import defaultdict
from typing import Dict, List, Optional

# ---- Config paths ----
POS_LOG    = "logs/positions_learning.jsonl"
POLICY_CFG = "config/profit_policy.json"
EVENT_LOG  = "logs/unified_events.jsonl"

# ---- Universe - Dynamic loading from canonical config ----
try:
    from src.data_registry import DataRegistry as DR
    ALL_SYMBOLS = DR.get_enabled_symbols()
except ImportError:
    ALL_SYMBOLS = [
        "BTCUSDT","ETHUSDT","SOLUSDT","AVAXUSDT","DOTUSDT",
        "TRXUSDT","XRPUSDT","ADAUSDT","DOGEUSDT","BNBUSDT","MATICUSDT",
        "LINKUSDT","ARBUSDT","OPUSDT","PEPEUSDT"
    ]

# ---- Gates & targets ----
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

# ---- Cost model (align with intelligence module) ----
VENUE_FEES = {"taker_pct": 0.0012, "maker_pct": 0.0008}
DEFAULT_SLIPPAGE_PCT = 0.0005
DEFAULT_SPREAD_PCT   = 0.0003

def estimate_round_trip_costs(size_usd: float, taker: bool=True,
                              slippage_pct: float=DEFAULT_SLIPPAGE_PCT,
                              spread_pct: float=DEFAULT_SPREAD_PCT) -> Dict[str, float]:
    fee_pct = VENUE_FEES["taker_pct"] if taker else VENUE_FEES["maker_pct"]
    fees = size_usd * fee_pct * 2
    slip = size_usd * slippage_pct
    sprd = size_usd * spread_pct
    return {"fees_usd": fees, "slippage_usd": slip, "spread_usd": sprd, "total_cost_usd": fees + slip + sprd}

# ---- IO helpers ----
def _read_jsonl(path: str) -> List[dict]:
    if not os.path.exists(path): return []
    out = []
    with open(path, "r") as f:
        for line in f:
            s = line.strip()
            if not s: continue
            try: out.append(json.loads(s))
            except: continue
    return out

def _write_policy(cfg: dict):
    os.makedirs(os.path.dirname(POLICY_CFG), exist_ok=True)
    with open(POLICY_CFG, "w") as f: json.dump(cfg, f, indent=2)

def _read_policy() -> dict:
    if not os.path.exists(POLICY_CFG): 
        return {
            "global": {
                "MIN_PROFIT_USD": 20.0, 
                "BASE_COLLATERAL_USD": BASE_COLLATERAL_USD_DEFAULT
            }, 
            "per_symbol": {}, 
            "per_strategy": {}
        }
    with open(POLICY_CFG, "r") as f: return json.load(f)

def _append_event(event: str, payload: Optional[dict] = None):
    if payload is None:
        payload = {}
    os.makedirs(os.path.dirname(EVENT_LOG), exist_ok=True)
    payload.update({"event": event, "ts": int(time.time())})
    with open(EVENT_LOG, "a") as f: f.write(json.dumps(payload) + "\n")

def profit_target_for(symbol: str) -> float:
    return MIN_PROFIT_TARGETS_USD.get(symbol, MIN_PROFIT_TARGETS_USD["DEFAULT"])

# ---- Outcomes aggregation ----
def collect_outcomes() -> dict:
    positions = _read_jsonl(POS_LOG)
    outcomes = defaultdict(lambda: defaultdict(list))
    for p in positions:
        if not p.get("closed"): continue
        sym = p.get("symbol")
        if sym not in ALL_SYMBOLS: continue
        strat = p.get("strategy", "unknown")
        outcomes[sym][strat].append(p)
    return dict(outcomes)

def compute_stats(trades: List[dict]) -> dict:
    trades = trades[-ROLLING_WINDOW:]
    wins = [t for t in trades if float(t.get("profit_usd", 0)) > 0]
    net_pnl = sum(float(t.get("profit_usd", 0)) for t in trades)
    avg_roi = sum(float(t.get("roi", 0)) for t in trades) / len(trades) if trades else 0.0
    win_rate = (len(wins)/len(trades)) if trades else 0.0
    avg_size = sum(float(t.get("size_usd", BASE_COLLATERAL_USD_DEFAULT)) for t in trades) / len(trades) if trades else BASE_COLLATERAL_USD_DEFAULT
    costs = estimate_round_trip_costs(avg_size, taker=True)
    exp_profit_usd = avg_roi * avg_size
    net_edge_usd = exp_profit_usd - costs["total_cost_usd"]
    return {
        "samples": len(trades), 
        "win_rate": win_rate, 
        "net_pnl": net_pnl, 
        "avg_roi": avg_roi, 
        "avg_size_usd": avg_size, 
        "net_edge_usd": net_edge_usd
    }

# ---- Policy mutations ----
def promote_pair(policy: dict, symbol: str, strategy: str, stats: dict):
    key = f"{symbol}::{strategy}"
    strat_cfg = policy.setdefault("per_strategy", {}).setdefault(key, {})
    strat_cfg["disabled"] = False
    base = float(strat_cfg.get("BASE_COLLATERAL_USD", BASE_COLLATERAL_USD_DEFAULT))
    strat_cfg["BASE_COLLATERAL_USD"] = min(base * 1.5, MAX_COLLATERAL_USD)
    floor = float(strat_cfg.get("MIN_PROFIT_USD", profit_target_for(symbol)))
    strat_cfg["MIN_PROFIT_USD"] = max(floor, profit_target_for(symbol))
    _append_event("strategy_promoted", {"symbol": symbol, "strategy": strategy, "stats": stats, "new_cfg": strat_cfg})

def prune_pair(policy: dict, symbol: str, strategy: str, stats: dict):
    key = f"{symbol}::{strategy}"
    strat_cfg = policy.setdefault("per_strategy", {}).setdefault(key, {})
    strat_cfg["disabled"] = True
    base = float(strat_cfg.get("BASE_COLLATERAL_USD", BASE_COLLATERAL_USD_DEFAULT))
    strat_cfg["BASE_COLLATERAL_USD"] = max(base * 0.5, MIN_COLLATERAL_USD)
    floor = float(strat_cfg.get("MIN_PROFIT_USD", profit_target_for(symbol)))
    strat_cfg["MIN_PROFIT_USD"] = round(floor * 1.2, 2)
    _append_event("strategy_pruned", {"symbol": symbol, "strategy": strategy, "stats": stats, "new_cfg": strat_cfg})

def review_symbol(policy: dict, symbol: str, best_pairs: List[dict], worst_pairs: List[dict]):
    _append_event("symbol_review_summary", {"symbol": symbol, "best_pairs": best_pairs[:3], "worst_pairs": worst_pairs[:3]})

# ---- Nightly autonomy runner ----
def run_promotion_pruning_nightly():
    outcomes = collect_outcomes()
    policy   = _read_policy()

    for symbol, strat_trades in outcomes.items():
        pairs_stats = []
        for strategy, trades in strat_trades.items():
            stats = compute_stats(trades)
            pairs_stats.append({"strategy": strategy, **stats})
            if stats["samples"] >= ROLLING_WINDOW:
                if stats["win_rate"] >= PROMOTE_WINRATE and stats["net_edge_usd"] > 0 and stats["net_pnl"] >= profit_target_for(symbol):
                    promote_pair(policy, symbol, strategy, stats)
                elif stats["win_rate"] < PRUNE_WINRATE or stats["net_pnl"] < 0:
                    prune_pair(policy, symbol, strategy, stats)
        best = sorted(pairs_stats, key=lambda s: (s["net_pnl"], s["net_edge_usd"]), reverse=True)
        worst = sorted(pairs_stats, key=lambda s: (s["net_pnl"], s["net_edge_usd"]))
        review_symbol(policy, symbol, best, worst)

    _write_policy(policy)
    _append_event("promotion_pruning_cycle_complete", {"ts": int(time.time())})

# ---- If run as a script, execute nightly review once ----
if __name__ == "__main__":
    run_promotion_pruning_nightly()
    print("Promotion & pruning autonomy executed. Policy updated; events logged.")
