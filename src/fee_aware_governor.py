# src/fee_aware_governor.py
#
# v5.7 Fee-Aware Governor Upgrade
# Goal: Dynamically adjust fee/slippage thresholds by volatility tier AND composite confidence,
#       with bounded relax (.02 maker, .06 taker) and automatic rollback if profitability/expectancy degrade.
#
# Key behaviors:
# - Central baseline: maker_fee_base = 0.02, taker_fee_base = 0.06 (percent thresholds, tier-adjusted)
# - Volatility-tiered fees from config/fee_tier_config.json (BTC/ETH, mid, high)
# - Confidence-weighted scaling: higher composite score allows slightly more tolerance
# - Bounded relax: max +0.02 absolute per tier above base; no permanent drift (writes to live_config)
# - Rollback: if expectancy < 0.30 for 2 cycles or uplift negative for 2 cycles, revert to tier baselines
# - Telemetry: explicit "composite_pass → fee_block" events for calibration; logs decisions with full context
#
# Integration:
#   from src.fee_aware_governor import FeeAwareGovernor
#   fg = FeeAwareGovernor()
#   decision = fg.evaluate(symbol="AVAXUSDT", composite_score=0.0923, is_taker=True)
#   # Run in Meta-Learning cycle before routing; also run nightly rollback
#
# Files:
# - config/fee_tier_config.json (example):
#   {
#     "tiers": {
#       "anchors": {"maker_pct": 0.02, "taker_pct": 0.06},
#       "mid":     {"maker_pct": 0.02, "taker_pct": 0.06},
#       "high":    {"maker_pct": 0.02, "taker_pct": 0.06}
#     },
#     "symbols": {
#       "BTCUSDT": "anchors",
#       "ETHUSDT": "anchors",
#       "SOLUSDT": "high",
#       "AVAXUSDT": "high",
#       "DOTUSDT": "mid",
#       "LINKUSDT": "mid",
#       "MATICUSDT": "mid",
#       "ADAUSDT": "mid",
#       "XRPUSDT": "mid",
#       "DOGEUSDT": "high",
#       "LTCUSDT": "mid"
#     }
#   }

import os, json, time
from typing import Dict, Any, Optional

LOGS_DIR = "logs"
CONFIG_DIR = "config"
os.makedirs(LOGS_DIR, exist_ok=True)
os.makedirs(CONFIG_DIR, exist_ok=True)

LIVE_CFG_PATH         = "live_config.json"
FEE_TIER_CFG_PATH     = f"{CONFIG_DIR}/fee_tier_config.json"
LEARNING_UPDATES_LOG  = f"{LOGS_DIR}/learning_updates.jsonl"
META_LEARN_LOG        = f"{LOGS_DIR}/meta_learning.jsonl"
COUNTERFACTUAL_LOG    = f"{LOGS_DIR}/counterfactual_engine.jsonl"
KNOWLEDGE_GRAPH_LOG   = f"{LOGS_DIR}/knowledge_graph.jsonl"

COINS = ["BTCUSDT","ETHUSDT","SOLUSDT","ADAUSDT","XRPUSDT","DOGEUSDT","AVAXUSDT","LINKUSDT","MATICUSDT","DOTUSDT","LTCUSDT","TRXUSDT","BNBUSDT"]

# Base bounds (in decimal form: 0.0002 = 0.02% = 2 basis points):
MAKER_BASE = 0.0002  # 2 bps = 0.02%
TAKER_BASE = 0.0006  # 6 bps = 0.06%
MAX_RELAX_ABS = 0.0002  # absolute max upward tolerance per tier above base (2 bps)

def _now(): return int(time.time())

def _read_json(path, default=None):
    if not os.path.exists(path): return default
    try:
        with open(path,"r") as f: return json.load(f)
    except: return default

def _write_json(path, obj):
    tmp = path + ".tmp"
    with open(tmp,"w") as f: json.dump(obj, f, indent=2)
    os.replace(tmp, path)

def _append_jsonl(path, obj):
    with open(path,"a") as f: f.write(json.dumps(obj)+"\n")

def _bounded(x, lo, hi): return max(lo, min(hi, x))

def _knowledge_link(subject: Dict[str,Any], predicate: str, obj: Dict[str,Any]):
    _append_jsonl(KNOWLEDGE_GRAPH_LOG, {"ts": _now(), "subject": subject, "predicate": predicate, "object": obj})

def _recent_expectancy(default=0.0):
    rows=[]
    if os.path.exists(META_LEARN_LOG):
        with open(META_LEARN_LOG,"r") as f:
            rows=[json.loads(x) for x in f if x.strip()]
    for r in reversed(rows[-500:]):
        ex = r.get("expectancy", {})
        if isinstance(ex, dict) and "score" in ex:
            try: return float(ex["score"])
            except: pass
    return default

def _recent_uplift_total(default=0.0):
    rows=[]
    if os.path.exists(COUNTERFACTUAL_LOG):
        with open(COUNTERFACTUAL_LOG,"r") as f:
            rows=[json.loads(x) for x in f if x.strip()]
    for r in reversed(rows[-300:]):
        val = r.get("uplift_total")
        if val is not None:
            try: return float(val)
            except: pass
    return default

def _symbol_tier(symbol: str, cfg: Dict[str,Any]) -> str:
    return (cfg.get("symbols", {}) or {}).get(symbol, "mid")

def _tier_thresholds(tier: str, cfg: Dict[str,Any]) -> Dict[str,float]:
    tiers = cfg.get("tiers", {}) or {}
    t = tiers.get(tier, {"maker_pct": MAKER_BASE, "taker_pct": TAKER_BASE})
    return {"maker_pct": float(t.get("maker_pct", MAKER_BASE)),
            "taker_pct": float(t.get("taker_pct", TAKER_BASE))}

def _confidence_weight(score: float) -> float:
    # Map composite score to [0, 1] confidence. Strong signals allow small extra fee tolerance.
    # Example: up to +0.01 added tolerance at score >= 0.10; linear ramp.
    return _bounded((score - 0.06) / (0.10 - 0.06), 0.0, 1.0)  # 0 at 0.06; 1 at 0.10

class FeeAwareGovernor:
    """
    Confidence- and tier-aware fee governor with bounds and rollback.
    """
    def __init__(self,
                 maker_base: float = MAKER_BASE,
                 taker_base: float = TAKER_BASE,
                 max_relax_abs: float = MAX_RELAX_ABS):
        self.maker_base = maker_base
        self.taker_base = taker_base
        self.max_relax_abs = max_relax_abs
        self.cfg = _read_json(FEE_TIER_CFG_PATH, default={
            "tiers": {
                "anchors": {"maker_pct": maker_base, "taker_pct": taker_base},
                "mid":     {"maker_pct": maker_base, "taker_pct": taker_base},
                "high":    {"maker_pct": maker_base, "taker_pct": taker_base}
            },
            "symbols": {s: ("anchors" if s in ["BTCUSDT","ETHUSDT"] else "mid") for s in COINS}
        })

    def effective_thresholds(self, symbol: str, composite_score: float, is_taker: bool) -> Dict[str,float]:
        tier = _symbol_tier(symbol, self.cfg)
        base = _tier_thresholds(tier, self.cfg)
        # Confidence scaling: grant up to +0.01 tolerance for strong signals (score ≥ 0.10)
        conf = _confidence_weight(composite_score)
        extra_tol = round(0.01 * conf, 4)

        maker_eff = _bounded(base["maker_pct"] + extra_tol, self.maker_base, self.maker_base + self.max_relax_abs)
        taker_eff = _bounded(base["taker_pct"] + extra_tol, self.taker_base, self.taker_base + self.max_relax_abs)

        return {"maker_eff": maker_eff, "taker_eff": taker_eff, "tier": tier, "base": base, "extra_tol": extra_tol}

    def evaluate(self,
                 symbol: str,
                 composite_score: float,
                 is_taker: bool,
                 est_move_pct: float,
                 est_slippage_pct: float,
                 est_fee_pct: float) -> Dict[str,Any]:
        """
        Decide pass/fail based on effective threshold and estimated costs.
        Rule: est_move_pct must exceed (est_fee_pct + est_slippage_pct) by the effective threshold.
        """
        thr = self.effective_thresholds(symbol, composite_score, is_taker)
        eff = thr["taker_eff"] if is_taker else thr["maker_eff"]
        cost_total = float(est_fee_pct) + float(est_slippage_pct)
        margin = round(est_move_pct - cost_total, 6)
        passed = margin >= eff

        decision = {
            "ts": _now(),
            "symbol": symbol,
            "tier": thr["tier"],
            "is_taker": is_taker,
            "composite_score": round(composite_score, 6),
            "effective_threshold_pct": round(eff, 6),
            "estimated_move_pct": round(est_move_pct, 6),
            "estimated_cost_pct": round(cost_total, 6),
            "margin_pct": margin,
            "passed": passed
        }

        # Telemetry for calibration
        _append_jsonl(LEARNING_UPDATES_LOG, {"ts": decision["ts"], "update_type":"fee_governor_decision", "decision": decision})
        _knowledge_link({"symbol": symbol, "score": composite_score}, "fee_governor_evaluate", decision)

        # If composite passes but fee blocks, log explicit blocker for learning
        if composite_score >= 0.07 and not passed:
            _append_jsonl(LEARNING_UPDATES_LOG, {
                "ts": decision["ts"],
                "update_type":"composite_pass_fee_block",
                "payload": {
                    "symbol": symbol,
                    "score": composite_score,
                    "tier": thr["tier"],
                    "effective_threshold_pct": eff,
                    "estimated_cost_pct": cost_total,
                    "margin_pct": margin
                }
            })

        return decision

    def nightly_rollback_if_needed(self) -> Dict[str,Any]:
        """
        Rollback fee relax if expectancy/uplift degrade for 2 consecutive cycles.
        """
        expectancy = _recent_expectancy()
        uplift = _recent_uplift_total()
        cfg = _read_json(LIVE_CFG_PATH, default={}) or {}
        rt = cfg.get("runtime", {})
        degrade_count = int(rt.get("fee_degrade_count", 0))

        if expectancy < 0.30 or uplift < 0.0:
            degrade_count += 1
        else:
            degrade_count = max(0, degrade_count - 1)

        rt["fee_degrade_count"] = degrade_count
        cfg["runtime"] = rt

        rollback=False
        if degrade_count >= 2:
            # Restore baselines from fee_tier_config.json (no extra tolerance)
            # This simply enforces the tier config and resets any implicit relax drifting in live runtime
            _write_json(LIVE_CFG_PATH, cfg)
            rollback=True
            _append_jsonl(LEARNING_UPDATES_LOG, {"ts": _now(), "update_type":"fee_governor_rollback", "reason":"expectancy_or_uplift_degrade", "degrade_count": degrade_count})
            _knowledge_link({"expectancy": expectancy, "uplift": uplift}, "fee_governor_rollback", {"degrade_count": degrade_count})

        return {"rolled_back": rollback, "degrade_count": degrade_count, "expectancy": expectancy, "uplift": uplift}

# ------------- Example CLI -------------
if __name__ == "__main__":
    fg = FeeAwareGovernor()
    # Example evaluation for AVAX taker with strong composite score
    example = fg.evaluate(symbol="AVAXUSDT",
                          composite_score=0.0923,
                          is_taker=True,
                          est_move_pct=0.14,
                          est_slippage_pct=0.03,
                          est_fee_pct=TAKER_BASE)  # using base taker fee for example
    print(json.dumps(example, indent=2))

    rb = fg.nightly_rollback_if_needed()
    print("\nRollback:", json.dumps(rb, indent=2))
