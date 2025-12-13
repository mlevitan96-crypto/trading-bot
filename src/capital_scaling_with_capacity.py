# src/capital_scaling_with_capacity.py
#
# Capital Scaling Framework + Capacity Testing Integration
# Ensures scaling decisions respect both performance thresholds and capacity limits.

import os, json, time, random
from statistics import mean

# Use absolute paths relative to project root
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOG_DIR = os.path.join(PROJECT_ROOT, "logs")
SCALING_LOG = os.path.join(LOG_DIR,"capital_scaling.jsonl")

def _now(): return int(time.time())
def _append_jsonl(path,obj): os.makedirs(os.path.dirname(path),exist_ok=True); open(path,"a").write(json.dumps(obj)+"\n")

# ======================================================================
# Capacity Testing Functions
# ======================================================================
def measure_slippage(expected_price, actual_price):
    return (actual_price-expected_price)/expected_price

def fill_quality(order, fills):
    total_filled = sum(f["size"] for f in fills)
    completeness = total_filled/order["size"]
    avg_latency = mean([f["latency_ms"] for f in fills]) if fills else 0
    latency_penalty = avg_latency/1000.0
    return round(completeness-latency_penalty,4)

def track_drawdown(pnl_series):
    equity, peak, max_dd = 1.0, 1.0, 0.0
    for r in pnl_series:
        equity *= (1+r)
        peak = max(peak,equity)
        dd = (equity-peak)/peak
        max_dd = min(max_dd,dd)
    return round(max_dd,4)

def capacity_curve(allocations,trades):
    curves = []
    for alloc in allocations:
        slippages = [measure_slippage(t["expected"],t["actual"]) for t in trades]
        qualities = [fill_quality(t["order"],t["fills"]) for t in trades]
        pnl_series = [random.uniform(-0.02,0.03) for _ in trades]
        dd = track_drawdown(pnl_series)
        curves.append({
            "allocation":alloc,
            "avg_slippage":round(mean(slippages),6),
            "avg_fill_quality":round(mean(qualities),6),
            "max_drawdown":dd
        })
    return curves

# ======================================================================
# Capital Scaling Thresholds
# ======================================================================
def scaling_thresholds(metrics,audit_pass=True,capacity=None):
    """
    metrics: {"expectancy":0.002,"win_rate":0.62,"profit_factor":1.7,"drawdown":-0.015}
    capacity: {"avg_slippage":0.001,"avg_fill_quality":0.9,"max_drawdown":-0.03}
    """
    perf_ok = (metrics["expectancy"]>0 and
               metrics["win_rate"]>=0.60 and
               metrics["profit_factor"]>=1.5 and
               metrics["drawdown"]>=-0.05 and
               audit_pass)
    cap_ok = True
    if capacity:
        cap_ok = (capacity["avg_slippage"]<=0.002 and
                  capacity["avg_fill_quality"]>=0.8 and
                  capacity["max_drawdown"]>=-0.05)
    return perf_ok and cap_ok

# ======================================================================
# Scaling Logic with Capacity Check
# ======================================================================
def scale_allocation(current_mode,metrics,audit_pass=True,capacity=None):
    decision = {"ts":_now(),"current_mode":current_mode,"metrics":metrics,"capacity":capacity}
    if not scaling_thresholds(metrics,audit_pass,capacity):
        decision["next_mode"]=current_mode; decision["action"]="HOLD"
    else:
        if current_mode=="shadow":
            decision["next_mode"]="canary"; decision["action"]="PROMOTE"
        elif current_mode=="canary":
            decision["next_mode"]="production"; decision["action"]="PROMOTE"
        else:
            decision["next_mode"]="production"; decision["action"]="HOLD"
    _append_jsonl(SCALING_LOG,decision)
    return decision

def rollback_allocation(current_mode,metrics,capacity=None):
    decision = {"ts":_now(),"current_mode":current_mode,"metrics":metrics,"capacity":capacity}
    if not scaling_thresholds(metrics,audit_pass=True,capacity=capacity):
        if current_mode=="production":
            decision["next_mode"]="canary"; decision["action"]="ROLLBACK"
        elif current_mode=="canary":
            decision["next_mode"]="shadow"; decision["action"]="ROLLBACK"
        else:
            decision["next_mode"]="shadow"; decision["action"]="HOLD"
    else:
        decision["next_mode"]=current_mode; decision["action"]="HOLD"
    _append_jsonl(SCALING_LOG,decision)
    return decision

# CLI quick run
if __name__=="__main__":
    metrics={"expectancy":0.002,"win_rate":0.62,"profit_factor":1.7,"drawdown":-0.015}
    trades=[{"expected":100,"actual":100.2,"order":{"size":1.0,"ts":_now()},
             "fills":[{"size":0.5,"latency_ms":120},{"size":0.5,"latency_ms":200}]}]
    curves=capacity_curve([0.05],trades)
    capacity=curves[0]
    decision=scale_allocation("shadow",metrics,audit_pass=True,capacity=capacity)
    rollback=rollback_allocation("production",metrics,capacity=capacity)
    print(json.dumps({"decision":decision,"rollback":rollback,"capacity":capacity},indent=2))
