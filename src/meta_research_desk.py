# src/meta_research_desk.py
#
# v5.6 Meta-Research Desk
# Purpose: Push the system's learning and profitability as far as safely possible across all 11 coins,
#          with every experiment tied to the Meta-Governor's health checks and intelligence loop.
#
# What this adds:
# - Experiment generation: hypotheses per coin/regime based on missed gains, signal clusters, and composite alignment
# - Expectancy scoring: measure uplift from threshold relax, sizing nudges, spillover relax, and canary trades
# - Canary trades: tiny-size experiments on borderline signals with strict safety gates
# - Knowledge graph logging: connect signals → gates → decisions → outcomes → health → learning
# - 11-coin coverage: ["BTCUSDT","ETHUSDT","SOLUSDT","ADAUSDT","XRPUSDT","DOGEUSDT","AVAXUSDT","LINKUSDT","MATICUSDT","DOTUSDT","LTCUSDT"]
# - Health-tight integration: every action checks Meta-Governor health severity; brakes kick in automatically
# - Seamless integration: can be called nightly and by the Meta-Governor every 30 minutes; safe to run multiple times
#
# Integration:
#   from src.meta_research_desk import MetaResearchDesk
#   mrd = MetaResearchDesk()
#   result = mrd.run_cycle()  # call nightly and/or after meta_governor cycle
#
# Notes:
# - Uses existing logs: decision_trace, composite_scores, shadow_trades, executed_trades, operator_digest
# - Writes: knowledge_graph.jsonl (relationships), research_desk.jsonl (summaries), learning_updates.jsonl (short updates)
# - No external network calls; safe, bounded adjustments only; canary trades require your router/run-time hooks

import os, json, time, math
from collections import defaultdict
from typing import Dict, Any, List, Optional

COINS = ["BTCUSDT","ETHUSDT","SOLUSDT","ADAUSDT","XRPUSDT","DOGEUSDT","AVAXUSDT","LINKUSDT","MATICUSDT","DOTUSDT","LTCUSDT"]

LOGS_DIR = "logs"
os.makedirs(LOGS_DIR, exist_ok=True)

DECISION_TRACE_LOG   = f"{LOGS_DIR}/decision_trace.jsonl"
COMPOSITE_LOG        = f"{LOGS_DIR}/composite_scores.jsonl"
SHADOW_LOG           = f"{LOGS_DIR}/shadow_trades.jsonl"
EXEC_LOG             = f"{LOGS_DIR}/executed_trades.jsonl"
OPERATOR_DIGEST_LOG  = f"{LOGS_DIR}/operator_digest.jsonl"

LEARNING_UPDATES_LOG = f"{LOGS_DIR}/learning_updates.jsonl"
KNOWLEDGE_GRAPH_LOG  = f"{LOGS_DIR}/knowledge_graph.jsonl"
RESEARCH_DESK_LOG    = f"{LOGS_DIR}/research_desk.jsonl"

LIVE_CFG_PATH        = "live_config.json"

try:
    from src.meta_governor import MetaGovernor
except:
    MetaGovernor = None

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

def _within_minutes(ts, minutes):
    try: return (_now() - int(ts)) <= minutes*60
    except: return False

def _within_days(ts, days):
    try: return (_now() - int(ts)) <= days*86400
    except: return False

def _bounded(x, lo, hi): return max(lo, min(hi, x))

def _recent_regime() -> str:
    rows = _read_jsonl(DECISION_TRACE_LOG, 2000)
    for r in reversed(rows):
        regime = r.get("regime") or r.get("context",{}).get("regime")
        if regime: return str(regime)
    return "unknown"

def _regime_key(regime: str) -> str:
    r = regime.lower()
    if "trend" in r or "stable" in r: return "trend"
    return "chop"

def _composite_window(minutes=180) -> List[Dict[str,Any]]:
    rows = _read_jsonl(COMPOSITE_LOG, 5000) or _read_jsonl(DECISION_TRACE_LOG, 5000)
    cutoff = _now() - minutes*60
    out=[]
    for r in rows:
        ts = r.get("ts") or r.get("timestamp")
        sym = r.get("asset") or r.get("symbol")
        comp = r.get("metrics",{}).get("composite_score")
        if comp is None: comp = r.get("composite_score")
        if ts and ts >= cutoff and sym in COINS:
            try: out.append({"ts":int(ts), "symbol":sym, "score":float(comp)})
            except: pass
    return out

def _shadow_pnl(days=7) -> Dict[str, float]:
    rows = _read_jsonl(SHADOW_LOG, 10000)
    agg = defaultdict(float)
    for r in rows:
        ts = r.get("ts") or r.get("timestamp")
        if not _within_days(ts, days): continue
        sym = r.get("asset") or r.get("symbol")
        pnl = float(r.get("shadow_pnl_usd", r.get("shadow_pnl", 0.0)))
        if sym in COINS:
            agg[sym] += pnl
    return dict(agg)

def _executed_recent(minutes=180) -> Dict[str,int]:
    rows = _read_jsonl(EXEC_LOG, 5000)
    cutoff = _now() - minutes*60
    counts = defaultdict(int)
    for r in rows:
        ts = r.get("ts") or r.get("timestamp")
        sym = r.get("asset") or r.get("symbol")
        if sym in COINS and ts and ts >= cutoff:
            counts[sym] += 1
    return dict(counts)

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
    sizing["size_scalar"] = float(sizing.get("size_scalar", 1.0))
    return sizing

def _save_sizing(sizing: Dict[str,float]):
    cfg = _read_json(LIVE_CFG_PATH, default={})
    cfg["sizing"] = sizing
    _write_json(LIVE_CFG_PATH, cfg)

def _expectancy(real_rows: List[Dict[str,Any]], shadow_rows: List[Dict[str,Any]], horizon_days=7) -> Dict[str,Any]:
    cutoff = _now() - horizon_days*86400
    real_pnl = defaultdict(float); shadow_pnl = defaultdict(float)
    for r in real_rows:
        ts = r.get("ts") or r.get("timestamp")
        if not ts or ts < cutoff: continue
        sym = r.get("asset") or r.get("symbol")
        pnl = float(r.get("pnl_usd", r.get("pnl", 0.0)))
        if sym in COINS: real_pnl[sym] += pnl
    for r in shadow_rows:
        ts = r.get("ts") or r.get("timestamp")
        if not ts or ts < cutoff: continue
        sym = r.get("asset") or r.get("symbol")
        pnl = float(r.get("shadow_pnl_usd", r.get("shadow_pnl", 0.0)))
        if sym in COINS: shadow_pnl[sym] += pnl
    uplift = {sym: round(shadow_pnl.get(sym,0.0) - real_pnl.get(sym,0.0), 2) for sym in COINS}
    score = _bounded(1 - math.exp(-max(0.0, sum(v for v in uplift.values() if v>0))/300.0), 0.0, 1.0)
    return {"uplift": uplift, "score": round(score,3)}

def _canary_candidates(thresholds: Dict[str,float], regime_key: str, composite_recent: List[Dict[str,Any]]) -> List[Dict[str,Any]]:
    thr = thresholds.get(regime_key, 0.08)
    by_coin = defaultdict(list)
    for r in composite_recent:
        sym, score = r["symbol"], r["score"]
        if thr - 0.02 <= score < thr and sym in COINS:
            by_coin[sym].append(r)
    cands=[]
    for sym, rows in by_coin.items():
        rows.sort(key=lambda x: x["score"], reverse=True)
        if rows:
            cands.append({"symbol": sym, "score": rows[0]["score"], "ts": rows[0]["ts"]})
    return cands[:min(11,len(cands))]

class MetaResearchDesk:
    """
    Generates and runs safe micro-experiments across all 11 coins.
    - Tied to Meta-Governor health severity; brakes act automatically
    - Feeds knowledge graph + learning updates so the main brain can learn
    - Integrates with nightly and 30-minute cycles
    """
    def __init__(self,
                 canary_size_scalar=0.05,
                 max_canaries_per_cycle=5,
                 relax_step=0.01,
                 max_cum_relax=0.05,
                 pca_brake_hi=0.60,
                 pca_brake_lo=0.40):
        self.canary_size_scalar = canary_size_scalar
        self.max_canaries = max_canaries_per_cycle
        self.relax_step = relax_step
        self.max_cum_relax = max_cum_relax
        self.pca_brake_hi = pca_brake_hi
        self.pca_brake_lo = pca_brake_lo
        self.meta = MetaGovernor() if MetaGovernor else None

    def _health_ok(self) -> Dict[str,Any]:
        sev = {"system":"✅"}
        degraded=False
        kill_cleared=False
        
        # Read latest Meta-Governor digest from logs instead of triggering a full cycle
        # This avoids race conditions with the dedicated meta_governor_scheduler thread
        meta_gov_log = f"{LOGS_DIR}/meta_governor.jsonl"
        if os.path.exists(meta_gov_log):
            try:
                rows = _read_jsonl(meta_gov_log, limit=10)
                if rows:
                    latest = rows[-1]
                    health = latest.get("health", {})
                    sev = health.get("severity", {}) or sev
                    degraded = health.get("degraded_mode", False)
                    kill_cleared = health.get("kill_switch_cleared", False)
            except Exception:
                pass  # Fall back to defaults
        
        return {"severity": sev, "degraded": degraded, "kill_cleared": kill_cleared}

    def _knowledge_link(self, subject: Dict[str,Any], predicate: str, obj: Dict[str,Any]):
        _append_jsonl(KNOWLEDGE_GRAPH_LOG, {
            "ts": _now(),
            "subject": subject,
            "predicate": predicate,
            "object": obj
        })

    def _apply_threshold_relax(self, regime_key: str, thresholds: Dict[str,float], pca_var: float) -> Optional[Dict[str,Any]]:
        if pca_var >= self.pca_brake_hi:
            return None
        baseline = 0.07 if regime_key=="trend" else 0.05
        new_val = _bounded(thresholds[regime_key] - self.relax_step, thresholds["min"], thresholds["max"])
        if baseline - new_val > self.max_cum_relax:
            return None
        thresholds[regime_key] = round(new_val, 4)
        _save_thresholds(thresholds)
        self._knowledge_link({"regime_key": regime_key, "threshold": baseline}, "relaxed_threshold", {"new_threshold": thresholds[regime_key]})
        _append_jsonl(LEARNING_UPDATES_LOG, {"ts": _now(), "update_type": "research_threshold_relax", "regime_key": regime_key, "new": thresholds[regime_key]})
        return {"regime_key": regime_key, "new_threshold": thresholds[regime_key]}

    def _apply_canaries(self, candidates: List[Dict[str,Any]], pca_var: float) -> List[Dict[str,Any]]:
        if pca_var >= self.pca_brake_hi: return []
        sizing = _load_sizing()
        size_scalar = round(_bounded(self.canary_size_scalar * sizing.get("size_scalar",1.0), 0.01, 0.10), 3)
        canaries=[]
        for c in candidates[:self.max_canaries]:
            sym = c["symbol"]; score = c["score"]
            canary = {"symbol": sym, "size_scalar": size_scalar, "score": score, "ts": c["ts"]}
            self._knowledge_link({"coin": sym, "score": score}, "canary_trade", {"size_scalar": size_scalar})
            _append_jsonl(LEARNING_UPDATES_LOG, {"ts": _now(), "update_type":"canary_trade_enqueue", "payload": canary})
            canaries.append(canary)
        return canaries

    def run_cycle(self) -> Dict[str,Any]:
        regime = _recent_regime()
        regime_key = _regime_key(regime)
        thresholds = _load_thresholds()
        composite_recent = _composite_window(180)
        pca_var = _pca_variance_recent()

        health = self._health_ok()
        sev = health["severity"]
        degraded = health["degraded"]
        system_ok = ("🔴" not in sev.values())

        expect = _expectancy(_read_jsonl(EXEC_LOG, 8000), _read_jsonl(SHADOW_LOG, 8000), horizon_days=7)

        borderline = _canary_candidates(thresholds, regime_key, composite_recent)

        actions=[]

        # Enforce degraded mode and kill-switch checks before risky actions
        # Do NOT relax thresholds or issue canaries when system is in degraded state
        if degraded or not health.get("kill_cleared", True):
            actions.append({"type":"health_brake", "reason":"degraded_mode_or_kill_switch_active"})
        elif not system_ok:
            actions.append({"type":"health_brake", "reason":"critical_severity_detected"})
        else:
            # Only proceed with threshold relaxation and canaries when system is healthy
            if expect["score"] >= 0.35 and pca_var < self.pca_brake_hi:
                relax_result = self._apply_threshold_relax(regime_key, thresholds, pca_var)
                if relax_result: actions.append({"type":"threshold_relax", **relax_result})

            if pca_var <= self.pca_brake_lo and borderline:
                canaries = self._apply_canaries(borderline, pca_var)
                if canaries: actions.append({"type":"canary_enqueue", "count": len(canaries)})

        self._knowledge_link({"expectancy_score": expect["score"], "pca_var": pca_var, "regime_key": regime_key},
                             "experiment_outcomes",
                             {"actions": actions, "severity": sev})

        summary = {
            "ts": _now(),
            "regime": regime,
            "regime_key": regime_key,
            "thresholds": thresholds,
            "pca_variance": round(pca_var,3),
            "expectancy_score": expect["score"],
            "expectancy_uplift": expect["uplift"],
            "borderline_candidates": borderline,
            "health_severity": sev,
            "degraded_mode": degraded,
            "actions": actions,
            "coins": COINS
        }
        _append_jsonl(RESEARCH_DESK_LOG, summary)
        _append_jsonl(LEARNING_UPDATES_LOG, {"ts": summary["ts"], "update_type":"meta_research_cycle", "summary": summary})
        return summary

if __name__ == "__main__":
    mrd = MetaResearchDesk()
    res = mrd.run_cycle()
    print("Meta-Research Desk:", json.dumps(res, indent=2))
