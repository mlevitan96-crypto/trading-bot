# src/profit_attribution_module.py
#
# v5.7 Profit Attribution Module
# Purpose: Make profitability the single measure of success across the bot ecosystem.
#          Attribute realized PnL to filter/calibration/promotion changes, enforce profit gates,
#          and trigger promotions/rollbacks based on profit—not just expectancy.
#
# Key behaviors:
# - Aggregates realized PnL from executed trades per coin/tier over rolling windows
# - Links profit impact to recent changes (fee calibration, composite relax, promotions)
# - Computes attribution scores (profit_uplift, expectancy_uplift) and ranks contributors
# - Enforces profit gates: promote when profits persist, rollback when profits degrade
# - Writes causal links into knowledge graph for governance and future learning
# - Emits an email-ready digest section focused on “Are we making money?”
#
# Integration (per 30-min meta-learning cycle, after attribution/calibration):
#   from src.profit_attribution_module import ProfitAttributionModule
#   pam = ProfitAttributionModule()
#   summary = pam.run_cycle()
#   digest["email_body"] += summary["email_body"]
#
# Nightly gates:
#   pam.nightly_promotion_and_rollback()
#
# Files used:
# - Reads: logs/executed_trades.jsonl, logs/learning_updates.jsonl, logs/meta_learning.jsonl, config/fee_tier_config.json
# - Writes: logs/learning_updates.jsonl, logs/knowledge_graph.jsonl
#
# Trade schema expectation (executed_trades.jsonl):
#   {
#     "ts": 1732320000,
#     "symbol": "AVAXUSDT",
#     "side": "BUY/SELL",
#     "qty": 10.0,
#     "price": 25.4,
#     "pnl_pct": 0.012,            # realized PnL percent for the trade
#     "pnl": 12.34,                # realized PnL in quote currency (optional, if available)
#     "is_canary": true/false,
#     "tier": "high"               # optional; if missing, module infers from tier config
#   }

import os, json, time
from typing import Dict, Any, List, Optional
from collections import defaultdict, Counter

LOGS_DIR = "logs"
CONFIG_DIR = "config"
os.makedirs(LOGS_DIR, exist_ok=True)
os.makedirs(CONFIG_DIR, exist_ok=True)

EXEC_LOG               = f"{LOGS_DIR}/executed_trades.jsonl"
LEARNING_UPDATES_LOG   = f"{LOGS_DIR}/learning_updates.jsonl"
META_LEARN_LOG         = f"{LOGS_DIR}/meta_learning.jsonl"
KNOWLEDGE_GRAPH_LOG    = f"{LOGS_DIR}/knowledge_graph.jsonl"
FEE_TIER_CFG_PATH      = f"{CONFIG_DIR}/fee_tier_config.json"
LIVE_CFG_PATH          = "live_config.json"

# Windows and thresholds
WINDOW_MINS_SHORT      = 240   # 4 hours window for near-term profit signal
WINDOW_MINS_LONG       = 1440  # 24 hours window for sustained profit evaluation
EXPECTANCY_PROMOTE_GATE = 0.50
EXPECTANCY_ROLLBACK_GATE = 0.30
PNL_PROMOTE_GATE_PCT   = 0.0   # require non-negative realized PnL in short window
PNL_ROLLBACK_GATE_PCT  = -0.0  # rollback if realized PnL <= 0 for two cycles
CONSECUTIVE_PROMOTE_CYCLES = 2
CONSECUTIVE_ROLLBACK_CYCLES = 2

# Size scalar promotion step (bounded)
PROMOTION_SIZE_STEP    = 0.10  # increase by +10% of current scalar (bounded and reversible)
MAX_SIZE_SCALAR        = 1.00
MIN_SIZE_SCALAR        = 0.05

COINS = ["BTCUSDT","ETHUSDT","SOLUSDT","ADAUSDT","XRPUSDT","DOGEUSDT","AVAXUSDT","LINKUSDT","MATICUSDT","DOTUSDT","LTCUSDT"]

def _now(): return int(time.time())

def _append_jsonl(path, obj):
    with open(path, "a") as f: f.write(json.dumps(obj) + "\n")

def _read_jsonl(path, limit=20000):
    rows=[]
    if not os.path.exists(path): return rows
    with open(path, "r") as f:
        for line in f:
            line=line.strip()
            if not line: continue
            try: rows.append(json.loads(line))
            except: continue
    return rows[-limit:]

def _read_json(path, default=None):
    if not os.path.exists(path): return default
    try:
        with open(path,"r") as f: return json.load(f)
    except: return default

def _write_json(path, obj):
    tmp=path+".tmp"
    with open(tmp,"w") as f: json.dump(obj, f, indent=2)
    os.replace(tmp, path)

def _bounded(x, lo, hi): return max(lo, min(hi, x))

def _knowledge_link(subject: Dict[str,Any], predicate: str, obj: Dict[str,Any]):
    _append_jsonl(KNOWLEDGE_GRAPH_LOG, {"ts": _now(), "subject": subject, "predicate": predicate, "object": obj})

def _symbol_tier(symbol: str, cfg: Dict[str,Any]) -> str:
    return (cfg.get("symbols", {}) or {}).get(symbol, "mid")

def _recent_expectancy(default=0.0):
    rows=_read_jsonl(META_LEARN_LOG, 2000)
    for r in reversed(rows):
        ex = r.get("expectancy", {})
        val = ex.get("score") if isinstance(ex, dict) else None
        if val is not None:
            try: return float(val)
            except: break
    return default

class ProfitAttributionModule:
    """
    Profit-centered governance: attribute realized PnL to system changes, promote when profits persist,
    and rollback when profits degrade—making profit the ultimate measure of success.
    """
    def __init__(self,
                 short_window_mins: int = WINDOW_MINS_SHORT,
                 long_window_mins: int = WINDOW_MINS_LONG):
        self.short_window_mins = short_window_mins
        self.long_window_mins  = long_window_mins
        self.tiers_cfg = _read_json(FEE_TIER_CFG_PATH, default={"tiers": {}, "symbols": {}})
        self.live_cfg  = _read_json(LIVE_CFG_PATH, default={}) or {}
        self.runtime   = self.live_cfg.get("runtime", {})
        self.size_scalars = self.runtime.get("size_scalars", {s: 0.10 for s in COINS})  # default 10%

    # ---------- Aggregation ----------
    def _aggregate_pnl(self, window_mins: int) -> Dict[str,Dict[str,float]]:
        cutoff = _now() - window_mins*60
        rows = _read_jsonl(EXEC_LOG, 20000)
        per_coin = defaultdict(lambda: {"pnl_sum":0.0, "pnl_pct_sum":0.0, "n":0, "canary_n":0})
        per_tier = defaultdict(lambda: {"pnl_sum":0.0, "pnl_pct_sum":0.0, "n":0})

        for r in rows:
            ts = r.get("ts") or r.get("timestamp") or 0
            if ts < cutoff: continue
            sym = r.get("symbol") or r.get("asset")
            if not sym: continue
            tier = r.get("tier") or _symbol_tier(sym, self.tiers_cfg)
            pnl = float(r.get("pnl", 0.0))
            pnl_pct = float(r.get("pnl_pct", 0.0))
            per_coin[sym]["pnl_sum"] += pnl
            per_coin[sym]["pnl_pct_sum"] += pnl_pct
            per_coin[sym]["n"] += 1
            if r.get("is_canary", False): per_coin[sym]["canary_n"] += 1
            per_tier[tier]["pnl_sum"] += pnl
            per_tier[tier]["pnl_pct_sum"] += pnl_pct
            per_tier[tier]["n"] += 1

        # Averages
        for sym, s in per_coin.items():
            n = max(1, s["n"])
            s["avg_pnl_pct"] = round(s["pnl_pct_sum"]/n, 6)
        for tier, s in per_tier.items():
            n = max(1, s["n"])
            s["avg_pnl_pct"] = round(s["pnl_pct_sum"]/n, 6)

        return {"per_coin": per_coin, "per_tier": per_tier, "window_mins": window_mins}

    def _recent_changes(self) -> Dict[str,Any]:
        """
        Pulls recent system changes to attribute profit impact:
        - fee_calibration_applied
        - fee_attribution_cycle
        - remediation_threshold_nudge / emergency_activate (composite relax context)
        - promotions_with_evidence (if logged elsewhere)
        """
        rows=_read_jsonl(LEARNING_UPDATES_LOG, 5000)
        cutoff_short = _now() - self.short_window_mins*60
        changes=[]
        for r in rows:
            ts = r.get("ts") or r.get("timestamp") or 0
            if ts < cutoff_short: continue
            ut = r.get("update_type")
            if ut in ("fee_calibration_applied",
                      "fee_attribution_cycle",
                      "remediation_threshold_nudge",
                      "emergency_activate",
                      "promotion_with_evidence"):
                changes.append(r)
        return {"changes": changes}

    # ---------- Attribution ----------
    def _attribute_profit(self,
                          pnl_short: Dict[str,Any],
                          pnl_long: Dict[str,Any],
                          changes: Dict[str,Any]) -> Dict[str,Any]:
        """
        Heuristic attribution:
        - If a tier had fee calibration applied and short-window avg_pnl_pct improved vs long-window baseline, credit calibration.
        - If composite relax was active and more trades executed with positive pnl, credit relax.
        - If promotions occurred and the coin’s short-window pnl is positive, credit promotion.
        """
        per_tier_short = pnl_short["per_tier"]
        per_tier_long  = pnl_long["per_tier"]
        per_coin_short = pnl_short["per_coin"]
        expectancy = _recent_expectancy()

        # Index changes
        tier_cal = {}     # tier -> delta maker/taker
        relax_events = [] # composite relax indicators
        promotions = []   # symbols promoted

        for c in changes["changes"]:
            ut = c.get("update_type")
            if ut == "fee_calibration_applied":
                applied = c.get("applied", {})
                for tier, data in applied.items():
                    tier_cal[tier] = {"delta_maker": data.get("maker_new",0.0) - data.get("maker_old",0.0),
                                      "delta_taker": data.get("taker_new",0.0) - data.get("taker_old",0.0),
                                      "symbols": data.get("symbols", [])}
            elif ut in ("remediation_threshold_nudge","emergency_activate"):
                relax_events.append(ut)
            elif ut == "promotion_with_evidence":
                payload = c.get("payload", {})
                sym = payload.get("symbol")
                if sym: promotions.append(sym)

        # Compute tier-level attribution
        tier_attr = {}
        for tier, s_short in per_tier_short.items():
            s_long = per_tier_long.get(tier, {"avg_pnl_pct":0.0})
            uplift_pct = round(s_short.get("avg_pnl_pct", 0.0) - s_long.get("avg_pnl_pct", 0.0), 6)
            tier_attr[tier] = {
                "avg_pnl_pct_short": s_short.get("avg_pnl_pct", 0.0),
                "avg_pnl_pct_long": s_long.get("avg_pnl_pct", 0.0),
                "uplift_pct": uplift_pct,
                "calibration": tier_cal.get(tier, None)
            }
            _knowledge_link({"tier": tier, "baseline_pct": s_long.get("avg_pnl_pct",0.0)},
                            "profit_attribution_tier",
                            {"short_pct": s_short.get("avg_pnl_pct",0.0), "uplift_pct": uplift_pct, "calibration": tier_cal.get(tier)})

        # Coin-level attribution and promotion candidates
        coin_attr = {}
        promote_candidates = []
        rollback_candidates = []
        for sym, s_short in per_coin_short.items():
            avg_short = s_short.get("avg_pnl_pct", 0.0)
            n = s_short.get("n", 0)
            canary_n = s_short.get("canary_n", 0)
            tier = _symbol_tier(sym, self.tiers_cfg)
            avg_long = pnl_long["per_coin"].get(sym, {}).get("avg_pnl_pct", 0.0)
            uplift_pct = round(avg_short - avg_long, 6)

            coin_attr[sym] = {
                "avg_pnl_pct_short": avg_short,
                "avg_pnl_pct_long": avg_long,
                "uplift_pct": uplift_pct,
                "n_trades_short": n,
                "canary_trades_short": canary_n,
                "tier": tier
            }

            # Promotion gate: non-negative short-window pnl, expectancy strong, enough trades, or positive uplift
            if avg_short >= PNL_PROMOTE_GATE_PCT and expectancy >= EXPECTANCY_PROMOTE_GATE and n >= 2:
                promote_candidates.append(sym)

            # Rollback gate: negative short-window pnl with weak expectancy
            if avg_short <= PNL_ROLLBACK_GATE_PCT and expectancy <= EXPECTANCY_ROLLBACK_GATE and n >= 2:
                rollback_candidates.append(sym)

            _knowledge_link({"symbol": sym, "tier": tier},
                            "profit_attribution_coin",
                            {"avg_short": avg_short, "avg_long": avg_long, "uplift_pct": uplift_pct, "expectancy": expectancy})

        return {
            "tier_attr": tier_attr,
            "coin_attr": coin_attr,
            "promote_candidates": promote_candidates,
            "rollback_candidates": rollback_candidates,
            "expectancy": expectancy,
            "relax_events": relax_events
        }

    # ---------- Gates (tracked across cycles) ----------
    def _update_cycle_streaks(self, promote_syms: List[str], rollback_syms: List[str]) -> Dict[str,Any]:
        rt = self.runtime
        promote_streaks = rt.get("promote_streaks", {})
        rollback_streaks = rt.get("rollback_streaks", {})

        # Update counts
        for s in promote_syms:
            promote_streaks[s] = int(promote_streaks.get(s, 0)) + 1
            rollback_streaks[s] = 0
        for s in rollback_syms:
            rollback_streaks[s] = int(rollback_streaks.get(s, 0)) + 1
            promote_streaks[s] = 0

        # Persist
        rt["promote_streaks"] = promote_streaks
        rt["rollback_streaks"] = rollback_streaks
        self.runtime = rt
        self.live_cfg["runtime"] = rt
        _write_json(LIVE_CFG_PATH, self.live_cfg)

        return {"promote_streaks": promote_streaks, "rollback_streaks": rollback_streaks}

    def _apply_promotions_and_rollbacks(self, streaks: Dict[str,Any]) -> Dict[str,Any]:
        promote_applied = []
        rollback_applied = []
        scalars = self.size_scalars

        for sym, streak in streaks["promote_streaks"].items():
            if streak >= CONSECUTIVE_PROMOTE_CYCLES:
                old = float(scalars.get(sym, 0.10))
                new = _bounded(round(old * (1.0 + PROMOTION_SIZE_STEP), 6), MIN_SIZE_SCALAR, MAX_SIZE_SCALAR)
                scalars[sym] = new
                promote_applied.append({"symbol": sym, "old_size_scalar": old, "new_size_scalar": new})

        for sym, streak in streaks["rollback_streaks"].items():
            if streak >= CONSECUTIVE_ROLLBACK_CYCLES:
                old = float(scalars.get(sym, 0.10))
                new = _bounded(round(old * (1.0 - PROMOTION_SIZE_STEP), 6), MIN_SIZE_SCALAR, MAX_SIZE_SCALAR)
                scalars[sym] = new
                rollback_applied.append({"symbol": sym, "old_size_scalar": old, "new_size_scalar": new})

        # Persist size scalars
        self.runtime["size_scalars"] = scalars
        self.live_cfg["runtime"] = self.runtime
        _write_json(LIVE_CFG_PATH, self.live_cfg)

        # Log and link
        if promote_applied:
            _append_jsonl(LEARNING_UPDATES_LOG, {"ts": _now(), "update_type":"promotion_with_evidence", "payload": {"promotions": promote_applied}})
            for p in promote_applied:
                _knowledge_link({"symbol": p["symbol"], "old_scalar": p["old_size_scalar"]},
                                "promotion_with_evidence", {"new_scalar": p["new_size_scalar"]})

        if rollback_applied:
            _append_jsonl(LEARNING_UPDATES_LOG, {"ts": _now(), "update_type":"rollback_due_to_profit", "payload": {"rollbacks": rollback_applied}})
            for r in rollback_applied:
                _knowledge_link({"symbol": r["symbol"], "old_scalar": r["old_size_scalar"]},
                                "rollback_due_to_profit", {"new_scalar": r["new_size_scalar"]})

        return {"promotions": promote_applied, "rollbacks": rollback_applied, "size_scalars": scalars}

    # ---------- Public API ----------
    def run_cycle(self) -> Dict[str,Any]:
        pnl_short = self._aggregate_pnl(self.short_window_mins)
        pnl_long  = self._aggregate_pnl(self.long_window_mins)
        changes   = self._recent_changes()
        attr      = self._attribute_profit(pnl_short, pnl_long, changes)
        streaks   = self._update_cycle_streaks(attr["promote_candidates"], attr["rollback_candidates"])
        applied   = self._apply_promotions_and_rollbacks(streaks)

        # Email digest
        email = f"""
=== Profit Attribution ===
Expectancy: {attr['expectancy']:.3f}
Short-window avg PnL pct (by tier): { {t: v['avg_pnl_pct_short'] for t,v in attr['tier_attr'].items()} }
Promote candidates: {attr['promote_candidates']}
Rollback candidates: {attr['rollback_candidates']}

Applied promotions: {applied['promotions']}
Applied rollbacks: {applied['rollbacks']}

Top coin uplift (short - long):
{json.dumps({s: v['uplift_pct'] for s,v in attr['coin_attr'].items()}, indent=2)}
""".strip()

        summary = {
            "ts": _now(),
            "pnl_short": pnl_short,
            "pnl_long": pnl_long,
            "attr": attr,
            "streaks": streaks,
            "applied": applied,
            "email_body": email
        }
        _append_jsonl(LEARNING_UPDATES_LOG, {"ts": summary["ts"], "update_type":"profit_attribution_cycle", "summary": {k:v for k,v in summary.items() if k!='email_body'}})
        return summary

    def nightly_promotion_and_rollback(self) -> Dict[str,Any]:
        """
        Optional nightly consolidation pass to ensure promotions/rollbacks reflect sustained profit outcomes.
        This can simply re-emit current scalars and reset streaks if needed.
        """
        rt = self.runtime
        # Reset streaks nightly to avoid stale promotions/rollbacks accumulating without fresh evidence
        rt["promote_streaks"] = {}
        rt["rollback_streaks"] = {}
        self.live_cfg["runtime"] = rt
        _write_json(LIVE_CFG_PATH, self.live_cfg)

        _append_jsonl(LEARNING_UPDATES_LOG, {"ts": _now(), "update_type":"profit_attribution_nightly_reset", "size_scalars": rt.get("size_scalars")})
        return {"reset": True, "size_scalars": rt.get("size_scalars")}

# ---------------- CLI ----------------
if __name__ == "__main__":
    pam = ProfitAttributionModule()
    res = pam.run_cycle()
    print(json.dumps(res, indent=2))
    print("\n--- Email Body ---\n")
    print(res["email_body"])
    rb = pam.nightly_promotion_and_rollback()
    print("\nNightly:", json.dumps(rb, indent=2))
