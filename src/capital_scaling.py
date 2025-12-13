# src/capital_scaling.py
#
# Capital Scaling Framework – Institutional-grade rules for safe allocation growth
# Modules:
# 1. Scaling thresholds (expectancy, win rate, drawdown, audit compliance)
# 2. Incremental scaling logic (shadow → canary → production)
# 3. Safety rollback (auto-deescalation on breach)
# 4. Audit packets for transparency

import os, json, time

# Use absolute paths relative to project root
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOG_DIR = os.path.join(PROJECT_ROOT, "logs")
SCALING_LOG = os.path.join(LOG_DIR,"capital_scaling.jsonl")

def _now(): return int(time.time())
def _append_jsonl(path,obj): os.makedirs(os.path.dirname(path),exist_ok=True); open(path,"a").write(json.dumps(obj)+"\n")

# ======================================================================
# 1. Scaling Thresholds
# ======================================================================
def scaling_thresholds(metrics, audit_pass=True):
    """
    metrics: {"expectancy":0.002,"win_rate":0.62,"profit_factor":1.7,"drawdown":-0.015}
    audit_pass: True if nightly audit passed
    Rules:
      - Expectancy > 0
      - Win rate >= 0.60
      - Profit factor >= 1.5
      - Max drawdown >= -0.05 (i.e., not worse than -5%)
      - Audit compliance required
    """
    return (metrics["expectancy"]>0 and
            metrics["win_rate"]>=0.60 and
            metrics["profit_factor"]>=1.5 and
            metrics["drawdown"]>=-0.05 and
            audit_pass)

# ======================================================================
# 2. Incremental Scaling Logic
# ======================================================================
def scale_allocation(current_mode, metrics, audit_pass=True):
    """
    Modes: shadow → canary → production
    Canary allocation: 1-5% capital
    Production allocation: full capital
    """
    decision = {"ts":_now(),"current_mode":current_mode,"metrics":metrics,"audit_pass":audit_pass}
    if not scaling_thresholds(metrics,audit_pass):
        decision["next_mode"] = current_mode
        decision["action"] = "HOLD"
    else:
        if current_mode=="shadow":
            decision["next_mode"] = "canary"
            decision["action"] = "PROMOTE"
        elif current_mode=="canary":
            decision["next_mode"] = "production"
            decision["action"] = "PROMOTE"
        else:
            decision["next_mode"] = "production"
            decision["action"] = "HOLD"
    _append_jsonl(SCALING_LOG,decision)
    return decision

# ======================================================================
# 3. Safety Rollback
# ======================================================================
def rollback_allocation(current_mode, metrics):
    """
    If thresholds breached, rollback allocation.
    """
    decision = {"ts":_now(),"current_mode":current_mode,"metrics":metrics}
    if not scaling_thresholds(metrics,audit_pass=True):
        if current_mode=="production":
            decision["next_mode"] = "canary"
            decision["action"] = "ROLLBACK"
        elif current_mode=="canary":
            decision["next_mode"] = "shadow"
            decision["action"] = "ROLLBACK"
        else:
            decision["next_mode"] = "shadow"
            decision["action"] = "HOLD"
    else:
        decision["next_mode"] = current_mode
        decision["action"] = "HOLD"
    _append_jsonl(SCALING_LOG,decision)
    return decision

# ======================================================================
# 4. Audit Packet
# ======================================================================
def scaling_audit(metrics, decision):
    packet = {"ts":_now(),"metrics":metrics,"decision":decision}
    _append_jsonl(SCALING_LOG,packet)
    return packet

# CLI quick run
if __name__=="__main__":
    metrics = {"expectancy":0.002,"win_rate":0.62,"profit_factor":1.7,"drawdown":-0.015}
    decision = scale_allocation("shadow",metrics,audit_pass=True)
    rollback = rollback_allocation("production",metrics)
    audit = scaling_audit(metrics,decision)
    print(json.dumps({"decision":decision,"rollback":rollback,"audit":audit},indent=2))
