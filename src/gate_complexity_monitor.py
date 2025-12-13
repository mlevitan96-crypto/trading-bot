# === Gate Complexity Monitor (src/gate_complexity_monitor.py) ===
# Purpose:
# - Track how many gates are actively influencing trades each cycle.
# - Detect over-gating (too many overlapping filters).
# - Recommend simplification: merge, relax, or disable gates when complexity exceeds threshold.
# - Persist overlay so watchdogs can act only if evidence sustains.

import os, json, time
from collections import defaultdict

def _bus(event_name, event_data):
    try:
        from full_integration_blofin_micro_live_and_paper import _bus as main_bus
        main_bus(event_name, event_data)
    except:
        pass

LEARN_LOG   = "logs/learning_updates.jsonl"
EXEC_LOG    = "logs/executed_trades.jsonl"
LIVE_CFG    = "live_config.json"
COMPLEX_LOG = "logs/gate_complexity.jsonl"

def _now(): return int(time.time())

def _read_json(path):
    if not os.path.exists(path): return {}
    try: return json.load(open(path))
    except: return {}

def _write_json(path, obj):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path,"w") as f: json.dump(obj,f,indent=2)

def _append_jsonl(path, row):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path,"a") as f: f.write(json.dumps(row)+"\n")

def _read_jsonl(path, limit=200000):
    rows=[]
    if not os.path.exists(path): return rows
    with open(path,"r") as f:
        for line in f:
            try: rows.append(json.loads(line.strip()))
            except: continue
    return rows[-limit:]

# --- Complexity monitor ---

def run_gate_complexity_monitor(window_hours=12, max_active_gates=8):
    cutoff=_now()-window_hours*3600
    learns=_read_jsonl(LEARN_LOG, 200000)
    execs=_read_jsonl(EXEC_LOG, 200000)
    sample=[r for r in learns if int(r.get("ts",_now()))>=cutoff and r.get("update_type")=="decision_started"]

    active_counts=defaultdict(int)
    for s in sample:
        rc=(s.get("reason_codes") or s.get("gates",{}).get("reason_codes") or [])
        for reason in rc:
            active_counts[reason]+=1

    total_active=len(active_counts)
    suggestions=[]
    if total_active>max_active_gates:
        # Identify least contributing gates (low frequency or low WR)
        exec_sample=[r for r in execs if int(r.get("ts",_now()))>=cutoff]
        gate_pnl=defaultdict(list)
        for r in exec_sample:
            rc=(r.get("reason_codes") or [])
            pnl=float(r.get("net_pnl", r.get("pnl", 0.0)) or 0.0)
            for reason in rc:
                gate_pnl[reason].append(pnl)
        for gate, arr in gate_pnl.items():
            wr=sum(1 for x in arr if x>0)/(len(arr) or 1)
            if wr<0.25 and sum(arr)<0:
                suggestions.append({"gate":gate,"action":"consider_disable","reason":"low WR & negative PnL"})
            elif wr>0.45 and sum(arr)>0:
                suggestions.append({"gate":gate,"action":"consider_merge","reason":"high WR but overlapping"})
            else:
                suggestions.append({"gate":gate,"action":"keep","reason":"neutral"})
    else:
        suggestions.append({"action":"no_change","reason":"gate complexity within safe bounds"})

    cfg=_read_json(LIVE_CFG); rt=cfg.get("runtime",{}) or {}
    rt["gate_complexity_overlay"]={
        "ts":_now(),
        "window_hours":window_hours,
        "total_active_gates":total_active,
        "max_allowed":max_active_gates,
        "suggestions":suggestions
    }
    cfg["runtime"]=rt; _write_json(LIVE_CFG,cfg)

    report={
        "ts":_now(),
        "update_type":"gate_complexity_monitor",
        "total_active_gates":total_active,
        "max_allowed":max_active_gates,
        "suggestions":suggestions
    }
    _append_jsonl(COMPLEX_LOG, report)
    _bus("gate_complexity_monitor_applied", report)

    print(f"🧹 Gate Complexity Monitor | active={total_active} max={max_active_gates} suggestions={len(suggestions)}")
    return {"total_active": total_active, "suggestions": suggestions}

# --- Scheduler integration ---
# Run nightly AFTER adaptive_learning_rate and before meta-governance watchdogs:
#   run_baseline_calibration(days=7, target_wr=0.40)
#   run_adaptive_learning_rate(window_hours=24)
#   run_gate_complexity_monitor(window_hours=12, max_active_gates=8)
#   run_meta_governance_watchdogs()
