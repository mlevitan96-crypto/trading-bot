# src/digest_extension.py
#
# v7.2 Digest Extension: Unified Nightly Report
# Purpose:
# - Extend nightly digest to include gate attribution stats, counterfactual summary,
#   auto-calibration adjustments, and strategy auto-tuning changes.
# - Produces one consolidated JSON + TXT digest for review.

import os, json, time
from src.full_integration_blofin_micro_live_and_paper import _bus

LEARN_LOG   = "logs/learning_updates.jsonl"
DIGEST_JSON = "logs/nightly_digest.json"
DIGEST_TXT  = "logs/nightly_digest.txt"

def _read_jsonl(path, limit=200000):
    rows=[]
    if not os.path.exists(path): return rows
    with open(path,"r") as f:
        for line in f:
            line=line.strip()
            if not line: continue
            try: rows.append(json.loads(line))
            except: continue
    return rows[-limit:]

def build_unified_digest():
    rows=_read_jsonl(LEARN_LOG,200000)

    cf_summaries=[r for r in rows if r.get("update_type")=="counterfactual_summary"]
    cf_latest=cf_summaries[-1] if cf_summaries else {}

    ac_events=[r for r in rows if r.get("update_type")=="auto_calibration_applied"]
    ac_latest=ac_events[-1] if ac_events else {}

    st_events=[r for r in rows if r.get("update_type")=="strategy_auto_tuning_applied"]
    st_latest=st_events[-1] if st_events else {}

    gate_events=[r for r in rows if r.get("update_type")=="gate_attribution"]
    gate_counts={}
    for ev in gate_events[-50000:]:
        for rc in ev.get("reason_codes",[]):
            gate_counts[rc]=gate_counts.get(rc,0)+1

    digest={
        "ts":int(time.time()),
        "counterfactual_summary":cf_latest,
        "auto_calibration":ac_latest,
        "strategy_auto_tuning":st_latest,
        "gate_counts":gate_counts
    }

    os.makedirs("logs",exist_ok=True)
    with open(DIGEST_JSON,"w") as f: json.dump(digest,f,indent=2)

    lines=[]
    lines.append("=== Nightly Unified Digest ===")
    lines.append(f"Counterfactual: Δ={cf_latest.get('delta_sum_net')} taken_sum={cf_latest.get('taken_sum_net')} blocked_sum={cf_latest.get('blocked_sum_net')}")
    lines.append(f"Auto-Calib: size_throttle {ac_latest.get('before',{}).get('size_throttle')}→{ac_latest.get('after',{}).get('size_throttle')} "
                 f"protective_mode {ac_latest.get('before',{}).get('protective_mode')}→{ac_latest.get('after',{}).get('protective_mode')}")
    ar = st_latest.get('alpha_report',{}) or {}
    er = st_latest.get('ema_report',{}) or {}
    lines.append(f"Strategy Tuning: Alpha OFI {ar.get('ofi_threshold_before')}→{ar.get('ofi_threshold_after')} "
                 f"Ensemble {ar.get('ensemble_threshold_before')}→{ar.get('ensemble_threshold_after')} "
                 f"EMA ROI {er.get('min_roi_before')}→{er.get('min_roi_after')}")
    lines.append("Gate Counts: "+", ".join([f"{k}={v}" for k,v in gate_counts.items()]) if gate_counts else "Gate Counts: (none)")

    with open(DIGEST_TXT,"w") as f: f.write("\n".join(lines))

    _bus("nightly_digest_extended", digest)
    print("\n".join(lines))
    return digest
