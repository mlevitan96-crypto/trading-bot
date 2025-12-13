# src/counterfactual_scaling_engine.py
#
# v5.7 Counterfactual Scaling Engine
# Goal: Close the loop between experiments and production by simulating canary trades
#       at full size, measuring expected uplift, and safely promoting high-expectancy
#       patterns. Every step is health-gated and logged to the knowledge graph.
#
# What it does:
# - Reads canary trades (tiny-size experiments) from learning_updates.jsonl
# - Simulates "full-size" outcomes using recent price/return proxies or shadow PnL traces
# - Computes cluster-aware uplift and expectancy per coin and regime
# - Proposes safe promotions: threshold relax, sizing nudges, or promotion of canary to standard routing
# - Health-gated: halts promotions on critical severity, degraded mode, or kill-switch issues
# - Writes outcomes and decisions to:
#     logs/counterfactual_engine.jsonl
#     logs/knowledge_graph.jsonl
#     logs/learning_updates.jsonl
#
# Integration:
#   from src.counterfactual_scaling_engine import CounterfactualScalingEngine
#   cse = CounterfactualScalingEngine()
#   summary = cse.run_cycle()  # call after Meta-Research Desk and before Profitability Governor nightly
#   # Optionally call every 30-min meta cycle as well; it's single-pass safe and health-gated
#
# Assumptions:
# - Canary trades are enqueued as learning_updates entries: {"update_type":"canary_trade_enqueue", "payload": {...}}
# - Shadow trades exist in logs/shadow_trades.jsonl to estimate PnL proxies
# - Executed trades exist for realized PnL comparison
# - Meta-Governor digests provide severity and runtime flags in logs/meta_governor.jsonl

import os, json, time, math
from collections import defaultdict
from typing import Dict, Any, List, Optional, Tuple

COINS = ["BTCUSDT","ETHUSDT","SOLUSDT","ADAUSDT","XRPUSDT","DOGEUSDT","AVAXUSDT","LINKUSDT","MATICUSDT","DOTUSDT","LTCUSDT"]
CLUSTERS = {
    "anchors": {"BTCUSDT","ETHUSDT"},
    "alts": {"SOLUSDT","AVAXUSDT","DOTUSDT","LINKUSDT","MATICUSDT","ADAUSDT","LTCUSDT","DOGEUSDT","XRPUSDT"}
}

LOGS_DIR = "logs"
os.makedirs(LOGS_DIR, exist_ok=True)

LEARNING_UPDATES_LOG   = f"{LOGS_DIR}/learning_updates.jsonl"
META_GOV_LOG           = f"{LOGS_DIR}/meta_governor.jsonl"
SHADOW_LOG             = f"{LOGS_DIR}/shadow_trades.jsonl"
EXEC_LOG               = f"{LOGS_DIR}/executed_trades.jsonl"
COUNTERFACTUAL_LOG     = f"{LOGS_DIR}/counterfactual_engine.jsonl"
KNOWLEDGE_GRAPH_LOG    = f"{LOGS_DIR}/knowledge_graph.jsonl"

LIVE_CFG_PATH          = "live_config.json"

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
    with open(path,"a") as f: f.write(json.dumps(obj) + "\n")

def _read_json(path, default=None):
    if not os.path.exists(path): return default
    try:
        with open(path,"r") as f: return json.load(f)
    except: return default

def _write_json(path, obj):
    tmp = path + ".tmp"
    with open(tmp,"w") as f: json.dump(obj, f, indent=2)
    os.replace(tmp, path)

def _now(): return int(time.time())

def _bounded(x, lo, hi): return max(lo, min(hi, x))

def _within_days(ts, days=7):
    try: return (_now() - int(ts)) <= days*86400
    except: return False

# ---------------- health + config helpers ----------------
def _severity_from_meta_gov() -> Dict[str,str]:
    rows = _read_jsonl(META_GOV_LOG, 3000)
    for r in reversed(rows):
        sev = r.get("health", {}).get("severity", {})
        if sev: return sev
    return {"system":"⚠️"}

def _runtime_flags() -> Dict[str,Any]:
    flags = {"degraded_mode": False, "kill_switch_cleared": True}
    rows = _read_jsonl(META_GOV_LOG, 3000)
    for r in reversed(rows):
        h = r.get("health", {})
        if "degraded_mode" in h: flags["degraded_mode"] = bool(h["degraded_mode"])
        if "kill_switch_cleared" in h: flags["kill_switch_cleared"] = bool(h["kill_switch_cleared"])
        return flags
    return flags

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
    cfg["last_counterfactual_tune_ts"] = _now()
    _write_json(LIVE_CFG_PATH, cfg)

def _load_sizing() -> Dict[str,float]:
    cfg = _read_json(LIVE_CFG_PATH, default={})
    sizing = cfg.get("sizing", {"size_scalar": 1.0})
    sizing["size_scalar"] = float(sizing.get("size_scalar",1.0))
    return sizing

def _save_sizing(sizing: Dict[str,float]):
    cfg = _read_json(LIVE_CFG_PATH, default={})
    cfg["sizing"] = sizing
    _write_json(LIVE_CFG_PATH, cfg)

# ---------------- canary + pnl helpers ----------------
def _canary_events(days=7) -> List[Dict[str,Any]]:
    rows = _read_jsonl(LEARNING_UPDATES_LOG, 12000)
    out=[]
    for r in rows:
        if r.get("update_type") == "canary_trade_enqueue":
            ts = r.get("ts")
            if _within_days(ts, days):
                payload = r.get("payload", {})
                sym = payload.get("symbol")
                if sym in COINS:
                    out.append(payload)
    return out

def _shadow_pnl_by_coin(days=7) -> Dict[str,float]:
    rows = _read_jsonl(SHADOW_LOG, 10000)
    agg=defaultdict(float)
    for r in rows:
        ts = r.get("ts") or r.get("timestamp")
        if not _within_days(ts, days): continue
        sym = r.get("asset") or r.get("symbol")
        pnl = float(r.get("shadow_pnl_usd", r.get("shadow_pnl", 0.0)))
        if sym in COINS:
            agg[sym]+=pnl
    return dict(agg)

def _real_pnl_by_coin(days=7) -> Dict[str,float]:
    rows = _read_jsonl(EXEC_LOG, 8000)
    agg=defaultdict(float)
    for r in rows:
        ts = r.get("ts") or r.get("timestamp")
        if not _within_days(ts, days): continue
        sym = r.get("asset") or r.get("symbol")
        pnl = float(r.get("pnl_usd", r.get("pnl", 0.0)))
        if sym in COINS:
            agg[sym]+=pnl
    return dict(agg)

def _cluster_share(uplift_by_coin: Dict[str,float]) -> Dict[str,float]:
    anchors = sum(uplift_by_coin.get(c,0.0) for c in CLUSTERS["anchors"])
    alts    = sum(uplift_by_coin.get(c,0.0) for c in CLUSTERS["alts"])
    total   = anchors + alts
    return {
        "anchors_share": round((anchors/total) if total>0 else 0.0, 3),
        "alts_share": round((alts/total) if total>0 else 0.0, 3),
        "total_uplift": round(total, 2)
    }

# ---------------- simulation + promotion logic ----------------
def _simulate_full_size(canaries: List[Dict[str,Any]], shadow_by_coin: Dict[str,float], real_by_coin: Dict[str,float]) -> Dict[str,Any]:
    projections = {}
    for c in canaries:
        sym = c.get("symbol")
        if not sym or sym not in COINS: continue
        canary_size = float(c.get("size_scalar", 0.05))
        scale_factor = _bounded(1.0 / max(0.01, canary_size), 1.0, 100.0)
        shadow = shadow_by_coin.get(sym, 0.0)
        real   = real_by_coin.get(sym, 0.0)
        base_uplift = shadow - real
        projected = base_uplift + _bounded(base_uplift * (scale_factor - 1.0), -abs(base_uplift), abs(base_uplift)*2.0)
        projections[sym] = round(projected, 2)
    return {"projections": projections, "total": round(sum(projections.values()), 2)}

def _expectancy_score(uplift_total: float) -> float:
    return round(_bounded(1 - math.exp(-max(0.0, uplift_total)/300.0), 0.0, 1.0), 3)

def _knowledge_link(subject: Dict[str,Any], predicate: str, obj: Dict[str,Any]):
    _append_jsonl(KNOWLEDGE_GRAPH_LOG, {"ts": _now(), "subject": subject, "predicate": predicate, "object": obj})

# ---------------- promotion actions ----------------
def _promote_thresholds(thresholds: Dict[str,float], regime_key: str, uplift_score: float, max_cum_relax=0.05) -> Optional[Dict[str,Any]]:
    baseline = 0.07 if regime_key=="trend" else 0.05
    step = _bounded(0.01 + uplift_score*0.01, 0.01, 0.02)
    new_val = _bounded(thresholds[regime_key] - step, thresholds["min"], thresholds["max"])
    if baseline - new_val > max_cum_relax:
        return None
    thresholds[regime_key] = round(new_val, 4)
    _save_thresholds(thresholds)
    _knowledge_link({"regime_key": regime_key, "threshold": baseline}, "counterfactual_threshold_relax", {"new_threshold": thresholds[regime_key], "uplift_score": uplift_score})
    _append_jsonl(LEARNING_UPDATES_LOG, {"ts": _now(), "update_type":"counterfactual_threshold_relax", "regime_key": regime_key, "new": thresholds[regime_key], "uplift_score": uplift_score})
    return {"type":"threshold_relax", "key": regime_key, "new": thresholds[regime_key], "uplift_score": uplift_score}

def _promote_sizing(sizing: Dict[str,float], uplift_score: float, pca_var: float) -> Optional[Dict[str,Any]]:
    if pca_var >= 0.60: return None
    step = _bounded(0.02 + uplift_score*0.03, 0.02, 0.06)
    size_scalar = float(sizing.get("size_scalar", 1.0))
    new_scalar = _bounded(size_scalar*(1.0 + step), 0.2, 1.5)
    if abs(new_scalar - size_scalar) < 1e-6:
        return None
    sizing["size_scalar"] = round(new_scalar, 3)
    _save_sizing(sizing)
    _knowledge_link({"size_scalar": size_scalar}, "counterfactual_size_nudge_up", {"new_size_scalar": sizing["size_scalar"], "uplift_score": uplift_score, "pca_var": pca_var})
    _append_jsonl(LEARNING_UPDATES_LOG, {"ts": _now(), "update_type":"counterfactual_size_nudge_up", "new_size_scalar": sizing["size_scalar"], "uplift_score": uplift_score, "pca_var": pca_var})
    return {"type":"size_nudge_up", "new_size_scalar": sizing["size_scalar"], "uplift_score": uplift_score, "pca_var": pca_var}

def _promote_canary_to_standard(canaries: List[Dict[str,Any]], projections: Dict[str,float], max_promotions=3) -> List[Dict[str,Any]]:
    symbols = {c.get("symbol") for c in canaries if c.get("symbol")}
    ranked = sorted(((sym, projections.get(sym,0.0)) for sym in symbols if sym is not None), key=lambda kv: kv[1], reverse=True)
    promotions=[]
    for sym, proj in ranked[:max_promotions]:
        promo = {"symbol": sym, "mode": "promotion", "size_multiplier": 0.2, "reason": "counterfactual_success", "projected_uplift_usd": proj}
        promotions.append(promo)
        _knowledge_link({"coin": sym, "projected_uplift_usd": proj}, "counterfactual_promote_to_standard", promo)
        _append_jsonl(LEARNING_UPDATES_LOG, {"ts": _now(), "update_type":"counterfactual_promotion_enqueue", "payload": promo})
    return promotions

# ---------------- main engine ----------------
class CounterfactualScalingEngine:
    def __init__(self,
                 max_cum_relax=0.05,
                 max_promotions=3):
        self.max_cum_relax = max_cum_relax
        self.max_promotions = max_promotions

    def _regime_key(self, regime: Optional[str]) -> str:
        r = (regime or "").lower()
        return "trend" if ("trend" in r or "stable" in r) else "chop"

    def _last_regime(self) -> str:
        rows = _read_jsonl(META_GOV_LOG, 1000)
        for r in reversed(rows):
            break
        rd = _read_jsonl(f"{LOGS_DIR}/research_desk.jsonl", 1000)
        for r in reversed(rd):
            reg = r.get("regime")
            if reg: return str(reg)
        return "unknown"

    def run_cycle(self) -> Dict[str,Any]:
        sev = _severity_from_meta_gov()
        flags = _runtime_flags()
        critical = ("🔴" in sev.values())
        degraded = flags.get("degraded_mode", False)
        kill_ok = flags.get("kill_switch_cleared", True)

        health_brake = critical or degraded or (not kill_ok)

        canaries = _canary_events(days=7)
        shadow_by_coin = _shadow_pnl_by_coin(days=7)
        real_by_coin   = _real_pnl_by_coin(days=7)

        sim = _simulate_full_size(canaries, shadow_by_coin, real_by_coin)
        uplift_by_coin = sim["projections"]
        cluster = _cluster_share(uplift_by_coin)
        uplift_total = sim["total"]
        expectancy = _expectancy_score(uplift_total)

        thresholds = _load_thresholds()
        sizing     = _load_sizing()
        regime_key = self._regime_key(self._last_regime())

        actions=[]

        if not health_brake:
            if expectancy >= 0.5:
                thr_action = _promote_thresholds(thresholds, regime_key, expectancy, max_cum_relax=self.max_cum_relax)
                if thr_action: actions.append(thr_action)

            pca_var = _read_json(f"{LOGS_DIR}/meta_learning_pca_cache.json", default={"var":0.5}).get("var",0.5)
            size_action = _promote_sizing(sizing, expectancy, pca_var)
            if size_action: actions.append(size_action)

            if expectancy >= 0.4 and cluster["total_uplift"] > 0:
                promos = _promote_canary_to_standard(canaries, uplift_by_coin, max_promotions=self.max_promotions)
                if promos: actions.append({"type":"promote_canaries", "count": len(promos)})

        else:
            actions.append({"type":"health_brake", "critical": critical, "degraded": degraded, "kill_switch_cleared": kill_ok})

        _knowledge_link({"uplift_total": uplift_total, "expectancy": expectancy, "cluster": cluster, "regime_key": regime_key},
                        "counterfactual_outcomes",
                        {"actions": actions, "severity": sev, "flags": flags})

        summary = {
            "ts": _now(),
            "severity": sev,
            "flags": flags,
            "health_brake": health_brake,
            "canaries_count": len(canaries),
            "uplift_by_coin": uplift_by_coin,
            "uplift_total": uplift_total,
            "cluster_share": cluster,
            "expectancy": expectancy,
            "actions": actions,
            "thresholds": thresholds,
            "sizing": sizing,
            "coins": COINS
        }

        _append_jsonl(COUNTERFACTUAL_LOG, summary)
        _append_jsonl(LEARNING_UPDATES_LOG, {"ts": summary["ts"], "update_type":"counterfactual_cycle", "summary": summary})
        return summary

if __name__ == "__main__":
    cse = CounterfactualScalingEngine()
    res = cse.run_cycle()
    print("Counterfactual Scaling Engine:", json.dumps(res, indent=2))
