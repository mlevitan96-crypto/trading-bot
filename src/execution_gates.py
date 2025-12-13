# src/execution_gates.py
# Integration of Phases 113, 123, 129, 114
# - Phase 113: Execution Governor (adaptive quality gates)
# - Phase 123: Adaptive Fee Arbiter (solves 124% fee ratio)
# - Phase 129: Throughput Throttle Manager (emergency brake)
# - Phase 114: Real-Time Anomaly Defense

import json
import os
import time

# ---- Paths ----
EXEC_GOV_PATH = "logs/execution_governance.json"          # Phase 113
FEE_ARBITER_PATH = "logs/fee_arbiter_policy.json"         # Phase 123
THROTTLE_PATH = "logs/throughput_throttle.json"           # Phase 129
ANOMALY_DEF_PATH = "logs/real_time_anomaly_defense.jsonl" # Phase 114
TRADE_LOG_PATH = "logs/execution_gate_approvals.jsonl"
BLOCKED_LOG_PATH = "logs/execution_gate_rejections.jsonl"

# ---- Startup Initialization ----
def init_protective_gates():
    """Initialize protective gates with safe defaults if files don't exist yet."""
    defaults = {
        EXEC_GOV_PATH: {"roi_threshold": 0.005, "max_trades_hour": 2, "win_rate": 0.0, "fee_ratio": 1.0},
        FEE_ARBITER_PATH: {"roi_gate": 0.006, "prefer_limit": True, "max_trades_hour": 2, "fee_ratio": 1.0},
        THROTTLE_PATH: {"severity": "low", "max_trades_hour": 2, "roi_threshold": 0.005}
    }
    for path, obj in defaults.items():
        if not os.path.exists(path):
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w") as f:
                json.dump(obj, f, indent=2)
    
    print("✅ [EXECUTION GATES] Protective gates initialized (Phases 113, 123, 129, 114)")

# ---- Hourly Cap Tracking ----
_trade_timestamps = []

def can_trade_now(max_per_hour: int) -> bool:
    """Check if we can trade based on hourly cap."""
    now = int(time.time())
    global _trade_timestamps
    _trade_timestamps = [t for t in _trade_timestamps if now - t < 3600]
    return len(_trade_timestamps) < max_per_hour

def mark_trade():
    """Mark that a trade was executed (for hourly cap tracking)."""
    _trade_timestamps.append(int(time.time()))

# ---- Execution Gating ----
def execution_gates(symbol: str, predicted_roi: float, mtf_confirmed: bool, quality_score: float = 0.5):
    """
    Multi-layer execution gating system integrating Phases 113, 123, 129, 114.
    
    Args:
        symbol: Trading pair (e.g., "BTCUSDT")
        predicted_roi: Predicted ROI from strategy (e.g., 0.008 for 0.8%)
        mtf_confirmed: Whether multi-timeframe confirmation passed
        quality_score: Signal quality score (0-1), default 0.5
    
    Returns:
        dict with:
            - approved: bool (whether trade should proceed)
            - reason: str (rejection reason if not approved)
            - order_type: str ("limit" or "market" if approved)
            - roi_gate_used: float (ROI threshold used)
            - max_trades_hour: int (current hourly cap)
    """
    ts = int(time.time())
    
    # Load policies
    governor = json.load(open(EXEC_GOV_PATH)) if os.path.exists(EXEC_GOV_PATH) else {}
    fee_policy = json.load(open(FEE_ARBITER_PATH)) if os.path.exists(FEE_ARBITER_PATH) else {}
    throttle = json.load(open(THROTTLE_PATH)) if os.path.exists(THROTTLE_PATH) else {}

    # ROI gate (adaptive - use strictest)
    roi_gate = max(
        governor.get("roi_threshold", 0.005),
        fee_policy.get("roi_gate", 0.005),
        throttle.get("roi_threshold", 0.005)
    )

    # Hourly cap (strictest of all policies)
    max_trades_hour = min(
        governor.get("max_trades_hour", 2),
        fee_policy.get("max_trades_hour", 2),
        throttle.get("max_trades_hour", 2)
    )

    prefer_limit = fee_policy.get("prefer_limit", True)

    # --- Gate Checks ---
    
    # 1. MTF Confirmation Required
    if not mtf_confirmed:
        return _log_block(symbol, predicted_roi, "mtf_not_confirmed", ts)

    # 2. ROI Gate
    if predicted_roi < roi_gate:
        return _log_block(symbol, predicted_roi, f"roi_below_{roi_gate:.4f}", ts)

    # 3. Hourly Cap
    if not can_trade_now(max_trades_hour):
        return _log_block(symbol, predicted_roi, "hourly_cap_exceeded", ts)

    # 4. Anomaly Defense (Phase 114)
    anomalies_recent = 0
    if os.path.exists(ANOMALY_DEF_PATH):
        try:
            with open(ANOMALY_DEF_PATH, "r") as f:
                lines = f.readlines()[-50:]
                anomalies_recent = sum(1 for ln in lines if '"type":' in ln)
        except:
            anomalies_recent = 0
    
    if anomalies_recent > 10:
        return _log_block(symbol, predicted_roi, "anomaly_defense_block", ts)

    # All gates passed - approve trade
    return _log_approve(symbol, predicted_roi, roi_gate, max_trades_hour, prefer_limit, ts, quality_score)

# ---- Logging Functions ----
def _log_block(symbol, roi, reason, ts):
    """Log a blocked trade."""
    blocked = {
        "ts": ts,
        "symbol": symbol,
        "predicted_roi": roi,
        "status": "BLOCKED",
        "reason": reason
    }
    os.makedirs(os.path.dirname(BLOCKED_LOG_PATH), exist_ok=True)
    with open(BLOCKED_LOG_PATH, "a") as f:
        f.write(json.dumps(blocked) + "\n")
    
    return {"approved": False, "reason": reason}

def _log_approve(symbol, roi, roi_gate, max_trades_hour, prefer_limit, ts, quality_score):
    """Log an approved trade."""
    approved = {
        "ts": ts,
        "symbol": symbol,
        "predicted_roi": roi,
        "status": "APPROVED",
        "roi_gate": roi_gate,
        "max_trades_hour": max_trades_hour,
        "prefer_limit": prefer_limit,
        "quality_score": quality_score
    }
    
    os.makedirs(os.path.dirname(TRADE_LOG_PATH), exist_ok=True)
    with open(TRADE_LOG_PATH, "a") as f:
        f.write(json.dumps(approved) + "\n")
    
    mark_trade()
    
    return {
        "approved": True,
        "order_type": "limit" if prefer_limit else "market",
        "roi_gate_used": roi_gate,
        "max_trades_hour": max_trades_hour
    }

# ---- Convenience function for logging rejections (backward compatibility) ----
def log_gate_rejection(symbol: str, strategy: str, reason: str, predicted_roi: float):
    """Log when a trade is rejected by execution gates (legacy interface)."""
    _log_block(symbol, predicted_roi, reason, int(time.time()))
