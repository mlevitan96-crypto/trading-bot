# --- bot_cycle.py (integration patch) ---

import json, os, time

# Paths from phases
EXEC_GOV_LOG = "logs/execution_governance.json"          # Phase 113
FEE_ARBITER_LOG = "logs/fee_arbiter_policy.json"         # Phase 123
THROTTLE_LOG = "logs/throughput_throttle.json"           # Phase 129
ANOMALY_DEF_LOG = "logs/real_time_anomaly_defense.jsonl" # Phase 114
ML_LIVE_PREDICTIONS = "logs/ml_live_predictions.json"    # Phase 136 (optional gating later)

def _load_json(path, default):
    return json.load(open(path)) if os.path.exists(path) else default

# ---- Startup init: default protective gates ----
def init_protective_gates():
    # Set sane defaults if files aren’t present yet
    if not os.path.exists(EXEC_GOV_LOG):
        json.dump({"roi_threshold": 0.005, "max_trades_hour": 2, "win_rate": 0.0, "fee_ratio": 1.0}, open(EXEC_GOV_LOG, "w"))
    if not os.path.exists(FEE_ARBITER_LOG):
        json.dump({"roi_gate": 0.006, "prefer_limit": True, "max_trades_hour": 2, "fee_ratio": 1.0}, open(FEE_ARBITER_LOG, "w"))
    if not os.path.exists(THROTTLE_LOG):
        json.dump({"severity": "medium", "max_trades_hour": 2, "roi_threshold": 0.006}, open(THROTTLE_LOG, "w"))

# Call once at startup
init_protective_gates()

# ---- Helper: enforcement of hourly cap ----
_trade_timestamps = []  # track per-process; replace with persistent store if needed

def can_trade_now(max_per_hour: int) -> bool:
    now = int(time.time())
    # purge older than 3600s
    global _trade_timestamps
    _trade_timestamps = [t for t in _trade_timestamps if now - t < 3600]
    return len(_trade_timestamps) < max_per_hour

def mark_trade():
    _trade_timestamps.append(int(time.time()))

# ---- Core gating function (use this before placing any order) ----
def execution_gates(symbol: str, predicted_roi: float, signal_mtf_ok: bool, signal_quality_score: float, prefer_limit_default: bool=True):
    gov = _load_json(EXEC_GOV_LOG, {"roi_threshold": 0.005, "max_trades_hour": 2})
    arb = _load_json(FEE_ARBITER_LOG, {"roi_gate": 0.006, "prefer_limit": True, "max_trades_hour": 2})
    thr = _load_json(THROTTLE_LOG, {"severity": "low", "max_trades_hour": gov.get("max_trades_hour", 2), "roi_threshold": gov.get("roi_threshold", 0.005)})

    # 1) Full multi-timeframe confirmation required
    if not signal_mtf_ok:
        return {"approved": False, "reason": "mtf_not_confirmed"}

    # 2) ROI gate selection: throttle can raise, fee arbiter is strict mode when fee ratio high
    roi_gate = max(arb.get("roi_gate", 0.006), thr.get("roi_threshold", gov.get("roi_threshold", 0.005)))
    if predicted_roi < roi_gate:
        return {"approved": False, "reason": f"roi_below_gate_{roi_gate:.4f}"}

    # 3) Hourly throughput cap (use stricter of governor vs throttle vs fee arbiter)
    max_per_hour = min(gov.get("max_trades_hour", 2), thr.get("max_trades_hour", 2), arb.get("max_trades_hour", 2))
    if not can_trade_now(max_per_hour):
        return {"approved": False, "reason": "hourly_cap_reached"}

    # 4) Prefer limit orders when fee burden high
    prefer_limit = arb.get("prefer_limit", prefer_limit_default)

    # 5) Optional anomaly pre-check: block if recent anomalies flagged severe
    anomalies_recent = 0
    if os.path.exists(ANOMALY_DEF_LOG):
        try:
            with open(ANOMALY_DEF_LOG, "r") as f:
                lines = f.readlines()[-50:]
                anomalies_recent = sum(1 for ln in lines if '"type":' in ln)
        except:
            anomalies_recent = 0
    if anomalies_recent > 10:
        return {"approved": False, "reason": "anomaly_defense_block"}

    return {
        "approved": True,
        "order_type": "limit" if prefer_limit else "market",
        "max_trades_hour": max_per_hour,
        "roi_gate_used": roi_gate,
        "notes": {"symbol": symbol, "signal_quality": signal_quality_score}
    }

# ---- Example usage in your signal loop ----
# Compute predicted_roi (from your strategy or ML), and signal_mtf_ok (1m & 15m agree).
# Then call:
# decision = execution_gates(sym, predicted_roi, signal_mtf_ok=True, signal_quality_score=quality_score)
# if decision["approved"]:
#     place_order(sym, order_type=decision["order_type"], ...)
#     mark_trade()
# else:
#     log_block(sym, reason=decision["reason"])