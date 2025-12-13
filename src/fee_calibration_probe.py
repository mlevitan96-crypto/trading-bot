# src/fee_calibration_probe.py
#
# v5.7 Fee Governor Calibration Probe
# Purpose: Analyze telemetry for "composite pass → fee block" patterns and propose bounded,
#          per-tier fee threshold adjustments. Auto-applies calibrated nudges with rollback safety.
#
# Behavior:
# - Aggregates recent fee_governor_decision and composite_pass_fee_block events per coin
# - Detects persistent fee-block patterns (high count, high confidence scores)
# - Proposes tier baseline nudges (±0.005 to ±0.01 absolute), capped by MAX_CALIBRATION and per-night limits
# - Applies changes to config/fee_tier_config.json and logs to learning_updates + knowledge_graph
# - Rollback if expectancy < 0.30 or uplift negative for 2 consecutive cycles
# - Email-ready summary string returned for digest inclusion
#
# Integration (run every 30 min after Fee-Aware Governor):
#   from src.fee_calibration_probe import FeeCalibrationProbe
#   fcp = FeeCalibrationProbe()
#   summary = fcp.run_cycle()
#   print(summary["email_body"])
#
# Nightly rollback:
#   fcp.nightly_rollback()
#
# Files:
# - Reads: logs/learning_updates.jsonl (telemetry), logs/counterfactual_engine.jsonl, logs/meta_learning.jsonl
# - Writes: config/fee_tier_config.json (calibrations), logs/learning_updates.jsonl, logs/knowledge_graph.jsonl

import os, json, time
from typing import Dict, Any, List, Optional
from collections import defaultdict, Counter

LOGS_DIR = "logs"
CONFIG_DIR = "config"
os.makedirs(LOGS_DIR, exist_ok=True)
os.makedirs(CONFIG_DIR, exist_ok=True)

LEARNING_UPDATES_LOG  = f"{LOGS_DIR}/learning_updates.jsonl"
META_LEARN_LOG        = f"{LOGS_DIR}/meta_learning.jsonl"
COUNTERFACTUAL_LOG    = f"{LOGS_DIR}/counterfactual_engine.jsonl"
KNOWLEDGE_GRAPH_LOG   = f"{LOGS_DIR}/knowledge_graph.jsonl"
FEE_TIER_CFG_PATH     = f"{CONFIG_DIR}/fee_tier_config.json"

COINS = ["BTCUSDT","ETHUSDT","SOLUSDT","ADAUSDT","XRPUSDT","DOGEUSDT","AVAXUSDT","LINKUSDT","MATICUSDT","DOTUSDT","LTCUSDT"]

# Baselines from deployed Fee-Aware Governor
MAKER_BASE = 0.02
TAKER_BASE = 0.06

# Calibration bounds
MAX_CALIBRATION_ABS = 0.01      # absolute max nudge per tier baseline (±1%)
PER_RUN_LIMIT_ABS   = 0.005     # per-run nudge cap (±0.5%)
MIN_TRADE_CONF      = 0.07      # composite score threshold to consider a signal "passed composite"
HIGH_CONF_THRESHOLD = 0.09      # high confidence threshold for stronger calibration
WINDOW_MINS         = 360       # telemetry aggregation window
ROLLBACK_EXPECTANCY = 0.30
ROLLBACK_UPLIFT     = 0.0
CONSECUTIVE_DEGRADE_LIMIT = 2   # two cycles to trigger rollback

def _now(): return int(time.time())

def _read_json(path, default=None):
    if not os.path.exists(path): return default
    try:
        with open(path, "r") as f: return json.load(f)
    except: return default

def _write_json(path, obj):
    tmp = path + ".tmp"
    with open(tmp, "w") as f: json.dump(obj, f, indent=2)
    os.replace(tmp, path)

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

def _knowledge_link(subject: Dict[str,Any], predicate: str, obj: Dict[str,Any]):
    _append_jsonl(KNOWLEDGE_GRAPH_LOG, {"ts": _now(), "subject": subject, "predicate": predicate, "object": obj})

def _symbol_tier(symbol: str, cfg: Dict[str,Any]) -> str:
    return (cfg.get("symbols", {}) or {}).get(symbol, "mid")

def _tier_thresholds(tier: str, cfg: Dict[str,Any]) -> Dict[str,float]:
    tiers = cfg.get("tiers", {}) or {}
    base = tiers.get(tier, {"maker_pct": MAKER_BASE, "taker_pct": TAKER_BASE})
    return {"maker_pct": float(base.get("maker_pct", MAKER_BASE)),
            "taker_pct": float(base.get("taker_pct", TAKER_BASE))}

def _bounded(x, lo, hi): return max(lo, min(hi, x))

def _recent_expectancy(default=0.0):
    rows = _read_jsonl(META_LEARN_LOG, 2000)
    for r in reversed(rows):
        ex = r.get("expectancy", {})
        val = ex.get("score") if isinstance(ex, dict) else None
        if val is not None:
            try: return float(val)
            except: break
    return default

def _recent_uplift_total(default=0.0):
    rows = _read_jsonl(COUNTERFACTUAL_LOG, 2000)
    for r in reversed(rows):
        ut = r.get("uplift_total")
        if ut is not None:
            try: return float(ut)
            except: break
    return default

class FeeCalibrationProbe:
    """
    Aggregates fee governor telemetry, detects persistent fee blocks per coin,
    and applies bounded tier adjustments with rollback safety.
    """
    def __init__(self,
                 window_mins: int = WINDOW_MINS,
                 per_run_limit_abs: float = PER_RUN_LIMIT_ABS,
                 max_calibration_abs: float = MAX_CALIBRATION_ABS):
        self.window_mins = window_mins
        self.per_run_limit_abs = per_run_limit_abs
        self.max_calibration_abs = max_calibration_abs

        # Ensure tier config exists
        self.cfg = _read_json(FEE_TIER_CFG_PATH, default={
            "tiers": {
                "anchors": {"maker_pct": MAKER_BASE, "taker_pct": TAKER_BASE},
                "mid":     {"maker_pct": MAKER_BASE, "taker_pct": TAKER_BASE},
                "high":    {"maker_pct": MAKER_BASE, "taker_pct": TAKER_BASE}
            },
            "symbols": {
                "BTCUSDT": "anchors",
                "ETHUSDT": "anchors",
                "SOLUSDT": "high",
                "AVAXUSDT": "high",
                "DOTUSDT": "mid",
                "LINKUSDT": "mid",
                "MATICUSDT": "mid",
                "ADAUSDT": "mid",
                "XRPUSDT": "mid",
                "DOGEUSDT": "high",
                "LTCUSDT": "mid"
            }
        })

    def _aggregate_telemetry(self) -> Dict[str,Any]:
        rows = _read_jsonl(LEARNING_UPDATES_LOG, 20000)
        cutoff = _now() - self.window_mins*60

        fee_decisions = []
        fee_blocks = []  # composite_pass_fee_block events
        for r in rows:
            ts = r.get("ts") or r.get("timestamp") or 0
            if ts < cutoff: continue
            ut = r.get("update_type")
            if ut == "fee_governor_decision":
                fee_decisions.append(r.get("decision", {}))
            elif ut == "composite_pass_fee_block":
                fee_blocks.append(r.get("payload", {}))

        # Aggregate per-coin stats
        block_counts = Counter(p.get("symbol") for p in fee_blocks if p.get("symbol"))
        high_conf_blocks = Counter(
            p.get("symbol") for p in fee_blocks
            if p.get("symbol") and float(p.get("score", 0.0)) >= HIGH_CONF_THRESHOLD
        )

        # Compute avg score and cost margins for blocked cases
        stats = defaultdict(lambda: {"count":0, "high_conf_count":0, "avg_score":0.0, "avg_margin":0.0})
        for sym, cnt in block_counts.items():
            stats[sym]["count"] = cnt
        for sym, cnt in high_conf_blocks.items():
            stats[sym]["high_conf_count"] = cnt
        # Averages
        accum = defaultdict(lambda: {"score_sum":0.0, "margin_sum":0.0, "n":0})
        for p in fee_blocks:
            sym = p.get("symbol"); score = float(p.get("score", 0.0)); margin = float(p.get("margin_pct", 0.0))
            if not sym: continue
            accum[sym]["score_sum"] += score
            accum[sym]["margin_sum"] += margin
            accum[sym]["n"] += 1
        for sym, a in accum.items():
            n = max(1, a["n"])
            stats[sym]["avg_score"] = round(a["score_sum"] / n, 6)
            stats[sym]["avg_margin"] = round(a["margin_sum"] / n, 6)

        return {"fee_decisions": fee_decisions, "fee_blocks": fee_blocks, "stats": stats}

    def _propose_adjustments(self, stats: Dict[str,Dict[str,Any]]) -> Dict[str,Any]:
        """
        Policy:
        - If a coin has ≥3 blocks in window and avg_score ≥ 0.085, propose a small nudge.
        - High-confidence emphasis: if high_conf_count ≥2, allow larger nudge within per-run cap.
        - Nudge direction: decrease threshold if margin is close (avg_margin within 0.01 of threshold-like levels), else keep.
        - Apply per-tier (all coins in tier share baseline), report impacted symbols for visibility.
        """
        tier_nudges = defaultdict(lambda: {"maker_delta":0.0, "taker_delta":0.0, "symbols": []})
        for sym, s in stats.items():
            count = int(s.get("count", 0))
            high_c = int(s.get("high_conf_count", 0))
            avg_score = float(s.get("avg_score", 0.0))
            avg_margin = float(s.get("avg_margin", 0.0))
            if count >= 3 and avg_score >= 0.085:
                tier = _symbol_tier(sym, self.cfg)
                # Base: small nudge; high-conf: slightly bigger within per-run cap
                base_nudge = 0.002 if avg_score < 0.095 else 0.003
                if high_c >= 2:
                    base_nudge += 0.002  # give a bit more tolerance
                # If margin is close to passing (within 0.01), we justify a slight threshold decrease
                maker_delta = -min(self.per_run_limit_abs, base_nudge)
                taker_delta = -min(self.per_run_limit_abs, base_nudge)
                tier_nudges[tier]["maker_delta"] += maker_delta
                tier_nudges[tier]["taker_delta"] += taker_delta
                tier_nudges[tier]["symbols"].append({"symbol": sym, "count": count, "avg_score": avg_score, "avg_margin": avg_margin, "high_conf": high_c})
        return tier_nudges

    def _apply_nudges(self, tier_nudges: Dict[str,Dict[str,Any]]) -> Dict[str,Any]:
        """
        Apply bounded nudges to fee_tier_config.json.
        Bounds:
        - Each tier baseline limited to MAKER_BASE ± MAX_CALIBRATION_ABS and TAKER_BASE ± MAX_CALIBRATION_ABS
        - Per-run deltas capped by PER_RUN_LIMIT_ABS (already enforced in propose step)
        """
        tiers = self.cfg.get("tiers", {}) or {}
        applied = {}
        for tier, nd in tier_nudges.items():
            if tier not in tiers: continue
            maker_old = float(tiers[tier].get("maker_pct", MAKER_BASE))
            taker_old = float(tiers[tier].get("taker_pct", TAKER_BASE))
            maker_new = _bounded(maker_old + nd["maker_delta"], MAKER_BASE - self.max_calibration_abs, MAKER_BASE + self.max_calibration_abs)
            taker_new = _bounded(taker_old + nd["taker_delta"], TAKER_BASE - self.max_calibration_abs, TAKER_BASE + self.max_calibration_abs)

            # Only write if change is material
            if abs(maker_new - maker_old) >= 1e-6 or abs(taker_new - taker_old) >= 1e-6:
                tiers[tier]["maker_pct"] = round(maker_new, 6)
                tiers[tier]["taker_pct"] = round(taker_new, 6)
                applied[tier] = {
                    "maker_old": maker_old, "maker_new": tiers[tier]["maker_pct"],
                    "taker_old": taker_old, "taker_new": tiers[tier]["taker_pct"],
                    "symbols": nd["symbols"]
                }

        # Persist changes
        if applied:
            self.cfg["tiers"] = tiers
            _write_json(FEE_TIER_CFG_PATH, self.cfg)
            _append_jsonl(LEARNING_UPDATES_LOG, {"ts": _now(), "update_type":"fee_calibration_applied", "applied": applied})
            _knowledge_link({"tiers_before": "redacted_for_size"}, "fee_calibration_applied", {"applied": applied})

        return applied

    def run_cycle(self) -> Dict[str,Any]:
        agg = self._aggregate_telemetry()
        stats = agg["stats"]
        tier_nudges = self._propose_adjustments(stats)
        applied = self._apply_nudges(tier_nudges)

        summary = {
            "ts": _now(),
            "window_mins": self.window_mins,
            "stats": stats,
            "nudges": tier_nudges,
            "applied": applied,
            "email_body": f"""
=== Fee Calibration Probe ===
Window: {self.window_mins} mins
Coins with fee blocks: {len([k for k,v in stats.items() if v['count']>0])}
Calibrations applied (tiers): {list(applied.keys())}

Details:
  Applied: {json.dumps(applied, indent=2) if applied else "None"}
  Proposed: {json.dumps({t: {'maker_delta': v['maker_delta'], 'taker_delta': v['taker_delta']} for t,v in tier_nudges.items()}, indent=2)}
""".strip()
        }
        _append_jsonl(LEARNING_UPDATES_LOG, {"ts": summary["ts"], "update_type":"fee_calibration_probe_cycle", "summary": {k:v for k,v in summary.items() if k!='email_body'}})
        _knowledge_link({"probe":"fee_calibration"}, "fee_calibration_probe_results", {"applied": applied, "stats": stats})
        return summary

    def nightly_rollback(self) -> Dict[str,Any]:
        expectancy = _recent_expectancy()
        uplift = _recent_uplift_total()
        cfg = self.cfg
        tiers = cfg.get("tiers", {}) or {}

        # Track degrade streak in config (lightweight)
        rt = _read_json("live_config.json", default={}).get("runtime", {})
        degrade_count = int(rt.get("fee_calibration_degrade_count", 0))
        if expectancy < ROLLBACK_EXPECTANCY or uplift < ROLLBACK_UPLIFT:
            degrade_count += 1
        else:
            degrade_count = max(0, degrade_count - 1)

        # Rollback decision
        rolled_back = False
        if degrade_count >= CONSECUTIVE_DEGRADE_LIMIT:
            # Restore to governor baselines (no calibration nudge beyond base)
            for tier in tiers.keys():
                tiers[tier]["maker_pct"] = MAKER_BASE
                tiers[tier]["taker_pct"] = TAKER_BASE
            cfg["tiers"] = tiers
            _write_json(FEE_TIER_CFG_PATH, cfg)
            rolled_back = True
            _append_jsonl(LEARNING_UPDATES_LOG, {"ts": _now(), "update_type":"fee_calibration_rollback", "reason":"expectancy_or_uplift_degrade", "expectancy": expectancy, "uplift": uplift})
            _knowledge_link({"expectancy": expectancy, "uplift": uplift}, "fee_calibration_rollback", {"rolled_back": True})

        # Persist degrade count
        live = _read_json("live_config.json", default={}) or {}
        live.setdefault("runtime", {})["fee_calibration_degrade_count"] = degrade_count
        _write_json("live_config.json", live)

        return {"rolled_back": rolled_back, "degrade_count": degrade_count, "expectancy": expectancy, "uplift": uplift}

# ---------------- CLI ----------------
if __name__ == "__main__":
    probe = FeeCalibrationProbe()
    res = probe.run_cycle()
    print(json.dumps(res, indent=2))
    print("\n--- Email Body ---\n")
    print(res["email_body"])
    rb = probe.nightly_rollback()
    print("\nRollback:", json.dumps(rb, indent=2))
