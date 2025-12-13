# src/portfolio_scaling_policy.py
#
# Portfolio-Level Scaling Policy
# - Analyzes portfolio-level capacity curves to make global scaling decisions
# - Ensures portfolio-wide thresholds are met before scaling up
# - Provides audit trail for portfolio-level scaling actions

import os, json, time

# Use absolute paths relative to project root
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOG_DIR = os.path.join(PROJECT_ROOT, "logs")
PORTFOLIO_SCALING_LOG = os.path.join(LOG_DIR, "portfolio_scaling.jsonl")

def _now(): return int(time.time())
def _append_jsonl(path,obj): os.makedirs(os.path.dirname(path),exist_ok=True); open(path,"a").write(json.dumps(obj)+"\n")

# Portfolio-level thresholds (stricter than per-asset)
PORTFOLIO_THRESHOLDS = {
    "max_slippage": 0.002,        # 0.2% max portfolio-weighted slippage
    "min_fill_quality": 0.80,     # 80% min portfolio-weighted fill quality
    "max_drawdown": -0.05,        # -5% max portfolio-level drawdown
    "min_allocation": 0.05        # Don't test below 5% allocation
}

def portfolio_capacity_thresholds_met(curves):
    """
    Check if portfolio capacity curves meet thresholds.
    curves: list of {"allocation":0.05, "avg_slippage":0.001, "avg_fill_quality":0.85, "max_drawdown":-0.02}
    """
    if not curves:
        return False
    
    # Check each allocation level tested
    for curve in curves:
        if curve["allocation"] < PORTFOLIO_THRESHOLDS["min_allocation"]:
            continue  # Skip very low allocations
        
        # All thresholds must pass
        if (curve["avg_slippage"] > PORTFOLIO_THRESHOLDS["max_slippage"] or
            curve["avg_fill_quality"] < PORTFOLIO_THRESHOLDS["min_fill_quality"] or
            curve["max_drawdown"] < PORTFOLIO_THRESHOLDS["max_drawdown"]):
            return False
    
    return True

def portfolio_scaling_decision(current_mode, portfolio_curves, audit_pass=True):
    """
    Make portfolio-level scaling decision based on capacity curves.
    current_mode: "shadow", "canary", or "production"
    portfolio_curves: capacity curves from multi_asset_orchestration
    """
    decision = {
        "ts": _now(),
        "current_mode": current_mode,
        "audit_pass": audit_pass,
        "thresholds_met": portfolio_capacity_thresholds_met(portfolio_curves)
    }
    
    # Decision logic
    if not audit_pass or not decision["thresholds_met"]:
        decision["next_mode"] = current_mode
        decision["action"] = "HOLD"
        decision["reason"] = "Audit failed" if not audit_pass else "Capacity thresholds not met"
    else:
        if current_mode == "shadow":
            decision["next_mode"] = "canary"
            decision["action"] = "PROMOTE"
            decision["reason"] = "Portfolio capacity curves passed all thresholds"
        elif current_mode == "canary":
            decision["next_mode"] = "production"
            decision["action"] = "PROMOTE"
            decision["reason"] = "Canary testing successful, ready for production"
        else:
            decision["next_mode"] = "production"
            decision["action"] = "HOLD"
            decision["reason"] = "Already in production mode"
    
    _append_jsonl(PORTFOLIO_SCALING_LOG, decision)
    return decision

def portfolio_scaling_audit(portfolio_info, decision):
    """
    Create audit packet for portfolio scaling decision.
    """
    audit = {
        "ts": _now(),
        "portfolio": portfolio_info,
        "decision": decision,
        "thresholds": PORTFOLIO_THRESHOLDS
    }
    return audit

# CLI quick run
if __name__ == "__main__":
    # Mock capacity curves
    curves = [
        {"allocation": 0.05, "avg_slippage": 0.0015, "avg_fill_quality": 0.85, "max_drawdown": -0.02},
        {"allocation": 0.10, "avg_slippage": 0.0018, "avg_fill_quality": 0.83, "max_drawdown": -0.03},
        {"allocation": 0.20, "avg_slippage": 0.0019, "avg_fill_quality": 0.81, "max_drawdown": -0.04}
    ]
    
    decision = portfolio_scaling_decision("shadow", curves, audit_pass=True)
    audit = portfolio_scaling_audit({"portfolio": "11 assets"}, decision)
    
    print(json.dumps({"decision": decision, "audit": audit}, indent=2))
