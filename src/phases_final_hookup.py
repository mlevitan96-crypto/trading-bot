# --- bot_cycle.py (Final Hookup for Phases 113, 123, 129, 114) ---

import os
import json
import time

# ---- Paths ----
EXEC_GOV_PATH = "logs/execution_governance.json"     # Phase 113
FEE_ARBITER_PATH = "logs/fee_arbiter_policy.json"    # Phase 123
THROTTLE_PATH = "logs/throughput_throttle.json"      # Phase 129
ANOMALY_DEF_PATH = "logs/real_time_anomaly_defense.jsonl"  # Phase 114
TRADE_LOG_PATH = "logs/trades_futures.json"
BLOCKED_LOG_PATH = "logs/missed_opportunities.json"

# ---- Startup Initialization ----
def init_protective_gates():
    defaults = {
        EXEC_GOV_PATH: {"roi_threshold": 0.005, "max_trades_hour": 2, "win_rate": 0.0, "fee_ratio": 1.0},
        FEE_ARBITER_PATH: {"roi_gate": 0.006, "prefer_limit": True, "max_trades_hour": 2, "fee_ratio": 1.0},
        THROTTLE_PATH: {"severity": "low", "max_trades_hour": 2, "roi_threshold": 0.005}
    }
    for path, obj in defaults.items():
        if not os.path.exists(path):
            os.makedirs(os.path.dirname(path), exist_ok=True)
            json.dump(obj, open(path, "w"))

init_protective_gates()

# ---- Hourly Cap Tracking ----
_trade_timestamps = []

def can_trade_now(max_per_hour: int) -> bool:
    now = int(time.time())
    global _trade_timestamps
    _trade_timestamps = [t for t in _trade_timestamps if now - t < 3600]
    return len(_trade_timestamps) < max_per_hour

def mark_trade():
    _trade_timestamps.append(int(time.time()))

# ---- Execution Gating ----
def execution_gates(symbol: str, predicted_roi: float, mtf_confirmed: bool, quality_score: float):
    ts = int(time.time())
    governor = json.load(open(EXEC_GOV_PATH)) if os.path.exists(EXEC_GOV_PATH) else {}
    fee_policy = json.load(open(FEE_ARBITER_PATH)) if os.path.exists(FEE_ARBITER_PATH) else {}
    throttle = json.load(open(THROTTLE_PATH)) if os.path.exists(THROTTLE_PATH) else {}

    # ROI gate (adaptive)
    roi_gate = max(governor.get("roi_threshold", 0.005),
                   fee_policy.get("roi_gate", 0.005),
                   throttle.get("roi_threshold", 0.005))

    # Hourly cap (strictest of all policies)
    max_trades_hour = min(governor.get("max_trades_hour", 2),
                          fee_policy.get("max_trades_hour", 2),
                          throttle.get("max_trades_hour", 2))

    prefer_limit = fee_policy.get("prefer_limit", True)

    # --- Gate Checks ---
    if not mtf_confirmed:
        return _log_block(symbol, predicted_roi, "mtf_not_confirmed", ts)

    if predicted_roi < roi_gate:
        return _log_block(symbol, predicted_roi, f"roi_below_{roi_gate:.4f}", ts)

    if not can_trade_now(max_trades_hour):
        return _log_block(symbol, predicted_roi, "hourly_cap_exceeded", ts)

    # Anomaly defense (Phase 114)
    anomalies_recent = 0
    if os.path.exists(ANOMALY_DEF_PATH):
        with open(ANOMALY_DEF_PATH, "r") as f:
            anomalies_recent = sum(1 for ln in f.readlines()[-50:] if '"type":' in ln)
    if anomalies_recent > 10:
        return _log_block(symbol, predicted_roi, "anomaly_defense_block", ts)

    # Approved trade
    return _log_approve(symbol, predicted_roi, roi_gate, max_trades_hour, prefer_limit, ts, quality_score)

# ---- Logging ----
def _log_block(symbol, roi, reason, ts):
    blocked = {
        "ts": ts, "symbol": symbol, "predicted_roi": roi,
        "status": "BLOCKED", "reason": reason
    }
    os.makedirs(os.path.dirname(BLOCKED_LOG_PATH), exist_ok=True)
    with open(BLOCKED_LOG_PATH, "a") as f:
        f.write(json.dumps(blocked) + "\n")
    return {"approved": False, "reason": reason}

def _log_approve(symbol, roi, roi_gate, max_trades_hour, prefer_limit, ts, quality_score):
    approved = {
        "ts": ts, "symbol": symbol, "predicted_roi": roi,
        "status": "APPROVED", "roi_gate": roi_gate,
        "max_trades_hour": max_trades_hour, "prefer_limit": prefer_limit,
        "quality_score": quality_score
    }
    trades = json.load(open(TRADE_LOG_PATH)) if os.path.exists(TRADE_LOG_PATH) else {"history": []}
    trades["history"].append(approved)
    os.makedirs(os.path.dirname(TRADE_LOG_PATH), exist_ok=True)
    with open(TRADE_LOG_PATH, "w") as f:
        json.dump(trades, f, indent=2)
    mark_trade()
    return {"approved": True, "order_type": "limit" if prefer_limit else "market"}

# ---- Example Usage in Signal Loop ----
# decision = execution_gates(sym, predicted_roi, mtf_confirmed=True, quality_score=quality_score)
# if decision["approved"]:
#     place_order(sym, order_type=decision["order_type"], size=position_size)
# else:
#     print(f"Trade blocked for {sym}: {decision['reason']}")