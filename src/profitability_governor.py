# src/profitability_governor.py
#
# v5.6 Profitability Governor
# Purpose: Systematically convert "missed profitable signals" into controlled threshold and sizing uplifts,
#          while preserving resilience via regime- and risk-aware constraints.
#
# Core functions:
# - Shadow PnL attribution: quantify missed gains vs avoided losses by reason/coin/strategy/regime
# - Uplift detection: persistence checks over multiple horizons (1d, 3d, 7d)
# - Controlled adjustments:
#     * Threshold relax (bounded, regime-aware, persistence-required)
#     * Sizing scalar nudges (confidence-/persistence-weighted, risk-aware)
#     * Spillover relax for correlated communities (optional, safe bounds)
# - Digest outputs: log summary to learning_updates.jsonl and profitability_governor.jsonl
#
# Integration:
#   from src.profitability_governor import ProfitabilityGovernor
#   gov = ProfitabilityGovernor()
#   gov.run_cycle()      # call nightly AND after liveness monitor; safe to run multiple times
#
# Optional tie-ins (if present in your repo):
#   - live_config.json: reads/updates thresholds/sizing/spillover safely
#   - logs/shadow_trades.jsonl: uses shadow PnL to estimate missed gains
#   - logs/executed_trades.jsonl: compares real vs shadow to avoid overfitting
#   - logs/operator_digest.jsonl: pulls PCA variance hints for risk-aware sizing
#   - src/trade_liveness_monitor.py: complementary; this governor focuses on profitability adjustments

import os, json, time, math
from collections import defaultdict
from typing import Dict, Any, List, Optional, Tuple

LOGS_DIR = "logs"
os.makedirs(LOGS_DIR, exist_ok=True)

# Inputs
SHADOW_LOG              = f"{LOGS_DIR}/shadow_trades.jsonl"
EXECUTED_TRADES_LOG     = f"{LOGS_DIR}/executed_trades.jsonl"
OPERATOR_DIGEST_LOG     = f"{LOGS_DIR}/operator_digest.jsonl"
DECISION_TRACE_LOG      = f"{LOGS_DIR}/decision_trace.jsonl"
COMPOSITE_LOG           = f"{LOGS_DIR}/composite_scores.jsonl"

# Outputs
LEARNING_UPDATES_LOG    = f"{LOGS_DIR}/learning_updates.jsonl"
PROFIT_GOV_LOG          = f"{LOGS_DIR}/profitability_governor.jsonl"

# Config
LIVE_CFG_PATH           = "live_config.json"

# ---------------- IO helpers ----------------
def _read_jsonl(path, limit=10000):
    rows=[]
    if not os.path.exists(path): return rows
    with open(path,"r") as f:
        for line in f:
            line=line.strip()
            if not line: continue
            try: rows.append(json.loads(line))
            except: continue
    return rows[-limit:]

def _append_jsonl(path, obj):
    with open(path,"a") as f:
        f.write(json.dumps(obj) + "\n")

def _read_json(path, default=None):
    if not os.path.exists(path): return default
    try:
        with open(path,"r") as f: return json.load(f)
    except:
        return default

def _write_json(path, obj):
    tmp = path + ".tmp"
    with open(tmp,"w") as f: json.dump(obj, f, indent=2)
    os.replace(tmp, path)

def _now(): return int(time.time())

def _within_days(ts, days):
    try: return (_now() - int(ts)) <= days*86400
    except: return False

def _bounded(x, lo, hi):
    return max(lo, min(hi, x))

# ---------------- analytics helpers ----------------
def _recent_regime() -> str:
    rows = _read_jsonl(DECISION_TRACE_LOG, 2000)
    for r in reversed(rows):
        regime = r.get("regime") or r.get("context",{}).get("regime")
        if regime: return str(regime)
    return "unknown"

def _pca_variance_recent(default=0.5) -> float:
    rows = _read_jsonl(OPERATOR_DIGEST_LOG, 2000)
    for r in reversed(rows):
        comp = r.get("components", {})
        pca = comp.get("pca", {})
        var = pca.get("variance")
        if var is not None:
            try: return float(var)
            except: break
    return default

def _collect_shadow_pnl(days: int = 7) -> Dict[str, Any]:
    """
    Returns per coin/strategy/regime aggregates:
    missed (positive shadow PnL when vetoed), avoided (negative shadow PnL avoided),
    and net = missed - avoided.
    """
    agg = defaultdict(lambda: {"missed":0.0, "avoided":0.0, "count":0})
    rows = _read_jsonl(SHADOW_LOG, 10000)
    for r in rows:
        ts = r.get("ts") or r.get("timestamp")
        if not _within_days(ts, days): continue
        sym = r.get("asset") or r.get("symbol") or "unknown"
        strat = r.get("strategy") or "unknown"
        regime = r.get("regime") or r.get("context",{}).get("regime") or "unknown"
        key = (sym, strat, regime)
        pnl = float(r.get("shadow_pnl_usd", r.get("shadow_pnl", 0.0)))
        # Heuristic: if the gate blocked a trade and pnl > 0, it's missed gain; pnl < 0 avoided loss
        if pnl > 0: agg[key]["missed"] += pnl
        else: agg[key]["avoided"] += abs(pnl)
        agg[key]["count"] += 1
    # compute net
    for k,v in agg.items():
        v["net"] = round(v["missed"] - v["avoided"], 2)
    return agg

def _composite_scores(days: int = 3) -> List[float]:
    rows = _read_jsonl(COMPOSITE_LOG, 5000) or _read_jsonl(DECISION_TRACE_LOG, 5000)
    vals=[]
    for r in rows:
        ts = r.get("ts") or r.get("timestamp")
        if not _within_days(ts, days): continue
        cs = r.get("metrics",{}).get("composite_score")
        if cs is None: cs = r.get("composite_score")
        try: vals.append(float(cs))
        except: pass
    return vals

def _mean_sigma(vals: List[float]) -> Tuple[float, float]:
    if not vals: return 0.0, 0.0
    m = sum(vals)/len(vals)
    var = sum((v-m)**2 for v in vals)/max(1, len(vals))
    return m, math.sqrt(var)

# ---------------- config helpers ----------------
def _load_thresholds() -> Dict[str,float]:
    cfg = _read_json(LIVE_CFG_PATH, default={})
    thr = (cfg.get("filters", {}).get("composite_thresholds", {})) if cfg else {}
    return {
        "trend": float(thr.get("trend", 0.07)),
        "chop":  float(thr.get("chop", 0.05)),
        "min":   float(thr.get("min", 0.05)),
        "max":   float(thr.get("max", 0.12))
    }

def _save_thresholds(thr: Dict[str,float]):
    cfg = _read_json(LIVE_CFG_PATH, default={})
    cfg.setdefault("filters", {})["composite_thresholds"] = thr
    cfg["last_composite_tune_ts"] = _now()
    _write_json(LIVE_CFG_PATH, cfg)

def _load_sizing() -> Dict[str,float]:
    cfg = _read_json(LIVE_CFG_PATH, default={})
    sizing = cfg.get("sizing", {"size_scalar": 1.0, "independence_bonus": 0.25, "cluster_penalty": 0.30})
    # ensure floats
    sizing["size_scalar"] = float(sizing.get("size_scalar", 1.0))
    sizing["independence_bonus"] = float(sizing.get("independence_bonus", 0.25))
    sizing["cluster_penalty"] = float(sizing.get("cluster_penalty", 0.30))
    return sizing

def _save_sizing(sizing: Dict[str,float]):
    cfg = _read_json(LIVE_CFG_PATH, default={})
    cfg["sizing"] = sizing
    _write_json(LIVE_CFG_PATH, cfg)

def _load_spillover() -> Dict[str,float]:
    cfg = _read_json(LIVE_CFG_PATH, default={})
    spill = cfg.get("spillover", {"enable": True, "follower_hurdle_relax": 0.85})
    spill["follower_hurdle_relax"] = float(spill.get("follower_hurdle_relax", 0.85))
    return spill

def _save_spillover(spill: Dict[str,float]):
    cfg = _read_json(LIVE_CFG_PATH, default={})
    cfg["spillover"] = spill
    _write_json(LIVE_CFG_PATH, cfg)

# ---------------- decision logic ----------------
class ProfitabilityGovernor:
    """
    Converts persistent missed gains (shadow PnL) into controlled threshold and sizing adjustments.
    Guards against overfitting using:
      - multi-horizon persistence (1d, 3d, 7d)
      - regime-aware mapping ("Stable" treated as trend-like)
      - PCA variance risk brakes
      - bounded deltas and max cumulative adjustments
    """
    def __init__(self,
                 min_relax_step=0.01, max_relax_step=0.02,
                 max_cum_relax=0.05,
                 size_nudge_up=0.05, size_nudge_down=0.05,
                 pca_brake_hi=0.60, pca_brake_lo=0.40,
                 spillover_step=0.02, spillover_bounds=(0.80, 0.92)):
        self.min_relax_step = min_relax_step
        self.max_relax_step = max_relax_step
        self.max_cum_relax = max_cum_relax
        self.size_nudge_up = size_nudge_up
        self.size_nudge_down = size_nudge_down
        self.pca_brake_hi = pca_brake_hi
        self.pca_brake_lo = pca_brake_lo
        self.spillover_step = spillover_step
        self.spillover_bounds = spillover_bounds

    def _regime_key(self, regime: str) -> str:
        r = regime.lower()
        if "trend" in r or "stable" in r: return "trend"
        return "chop"

    def _persistence_score(self, agg7: Dict, agg3: Dict, agg1: Dict) -> float:
        """
        Persistence heuristic: weight net > 0 across horizons.
        """
        w7 = 0.5; w3 = 0.35; w1 = 0.15
        net7 = sum(v.get("net",0.0) for v in agg7.values())
        net3 = sum(v.get("net",0.0) for v in agg3.values())
        net1 = sum(v.get("net",0.0) for v in agg1.values())
        total = w7*net7 + w3*net3 + w1*net1
        # scale to [0,1] using soft transform
        return _bounded(1 - math.exp(-abs(total)/100.0), 0.0, 1.0)

    def _composite_alignment(self, regime_key: str, thresholds: Dict[str,float], scores: List[float]) -> Dict[str,Any]:
        m, sigma = _mean_sigma(scores)
        target = _bounded(m + sigma, thresholds["min"], thresholds["max"]) if scores else thresholds[regime_key]
        delta = round(target - thresholds[regime_key], 4)
        return {"target": target, "delta": delta, "mean": m, "sigma": sigma}

    def _bounded_relax(self, current: float, target: float, rel_step: float, bounds: Tuple[float,float]) -> float:
        # Move toward target but limited by rel_step
        if target > current:
            # tightening; we rarely do this here
            new_val = current + min(self.max_relax_step, rel_step)
        else:
            # relaxing toward lower target
            new_val = current - min(self.max_relax_step, rel_step)
        return _bounded(new_val, bounds[0], bounds[1])

    def run_cycle(self) -> Dict[str,Any]:
        regime = _recent_regime()
        regime_key = self._regime_key(regime)

        # Shadow PnL across horizons
        agg1 = _collect_shadow_pnl(1)
        agg3 = _collect_shadow_pnl(3)
        agg7 = _collect_shadow_pnl(7)

        # Persistence and composite alignment
        persistence = self._persistence_score(agg7, agg3, agg1)
        thresholds = _load_thresholds()
        scores = _composite_scores(3)
        align = self._composite_alignment(regime_key, thresholds, scores)

        # Risk brakes via PCA variance
        pca_var = _pca_variance_recent()

        actions=[]

        # Threshold adjustments: only if persistence indicates missed gains are consistent
        # and composite threshold is above the target alignment
        if persistence >= 0.35 and align["delta"] < -0.005:
            # compute relax step scaled by persistence
            step = _bounded(self.min_relax_step + persistence*self.max_relax_step, self.min_relax_step, self.max_relax_step)
            new_val = _bounded(thresholds[regime_key] - step, thresholds["min"], thresholds["max"])
            # bound cumulative relaxation versus baseline (assume baselines 0.07 trend, 0.05 chop)
            baseline = 0.07 if regime_key=="trend" else 0.05
            if baseline - new_val <= self.max_cum_relax:
                thresholds[regime_key] = round(new_val, 4)
                _save_thresholds(thresholds)
                actions.append({"type":"threshold_relax", "key":regime_key, "new": thresholds[regime_key], "persistence": round(persistence,3)})

        # Sizing nudge: increase size when persistence strong and PCA variance is moderate/low
        sizing = _load_sizing()
        size_scalar = float(sizing.get("size_scalar", 1.0))
        if persistence >= 0.5 and pca_var <= self.pca_brake_lo:
            size_scalar = _bounded(size_scalar * (1.0 + self.size_nudge_up), 0.2, 1.5)
            sizing["size_scalar"] = round(size_scalar, 3)
            _save_sizing(sizing)
            actions.append({"type":"size_nudge_up", "new_size_scalar": sizing["size_scalar"], "pca_var": pca_var, "persistence": round(persistence,3)})
        elif pca_var >= self.pca_brake_hi:
            # brake sizing if factor dominance too high
            size_scalar = _bounded(size_scalar * (1.0 - self.size_nudge_down), 0.2, 1.5)
            sizing["size_scalar"] = round(size_scalar, 3)
            _save_sizing(sizing)
            actions.append({"type":"size_nudge_down", "new_size_scalar": sizing["size_scalar"], "pca_var": pca_var})

        # Spillover relax (optional): if missed gains concentrated in follower coins, gently relax follower hurdle
        # Proxy: if a significant share of missed gains are from coins typically followers, relax slightly.
        follower_candidates = {"SOLUSDT","AVAXUSDT","DOTUSDT","LINKUSDT","MATICUSDT","ADAUSDT","LTCUSDT","DOGEUSDT","XRPUSDT"}
        missed_share_followers = 0.0
        total_missed = sum(v["missed"] for v in agg3.values())
        if total_missed > 0:
            missed_followers = sum(v["missed"] for (sym, strat, reg), v in agg3.items() if sym in follower_candidates)
            missed_share_followers = missed_followers / total_missed

        spill = _load_spillover()
        if missed_share_followers >= 0.35 and pca_var <= self.pca_brake_lo:
            new_relax = _bounded(spill["follower_hurdle_relax"] + self.spillover_step, self.spillover_bounds[0], self.spillover_bounds[1])
            if abs(new_relax - spill["follower_hurdle_relax"]) >= 1e-6:
                spill["follower_hurdle_relax"] = round(new_relax, 2)
                _save_spillover(spill)
                actions.append({"type":"spillover_relax_increase", "new": spill["follower_hurdle_relax"], "missed_share_followers": round(missed_share_followers,3)})

        # Attribution summary
        top_missed = sorted(((k,v["net"]) for k,v in agg3.items()), key=lambda kv: kv[1], reverse=True)[:5]
        summary = {
            "ts": _now(),
            "regime": regime,
            "regime_key": regime_key,
            "persistence": round(persistence,3),
            "thresholds": thresholds,
            "composite_align": {"target": round(align["target"],4), "delta": round(align["delta"],4), "mean": round(align["mean"],4), "sigma": round(align["sigma"],4)},
            "pca_variance": round(pca_var,3),
            "top_missed": [{"asset": str(k[0]), "strategy": str(k[1]), "regime": str(k[2]), "net_usd": float(v)} for (k,v) in top_missed],
            "actions": actions
        }

        # Logs
        _append_jsonl(PROFIT_GOV_LOG, summary)
        _append_jsonl(LEARNING_UPDATES_LOG, {"ts": summary["ts"], "update_type": "profitability_governor_cycle", "summary": summary})

        return summary

# ---------------- CLI ----------------
if __name__ == "__main__":
    gov = ProfitabilityGovernor()
    res = gov.run_cycle()
    print("Profitability Governor:", json.dumps(res, indent=2))
