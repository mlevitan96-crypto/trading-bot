# src/fee_attribution_module.py
#
# v5.7 Fee Attribution Module
# Purpose: Attribute expectancy uplift (or degradation) to fee calibration changes.
#          Records causal links in knowledge_graph.jsonl and logs attribution scores per coin/tier.
#
# Behavior:
# - Reads fee_calibration_applied events and expectancy/uplift from meta_learning + counterfactual logs
# - Computes attribution: delta expectancy before vs after calibration
# - Records causal link: {symbol/tier} → {fee_delta} → {expectancy_uplift}
# - Maintains rolling attribution scores per coin/tier
# - Rollback: if attribution shows negative expectancy impact for 2 cycles, revert calibration
# - Email-ready summary string returned for digest inclusion
#
# Integration:
#   from src.fee_attribution_module import FeeAttributionModule
#   fam = FeeAttributionModule()
#   summary = fam.run_cycle()
#   print(summary["email_body"])
#
# Nightly rollback:
#   fam.nightly_rollback()

import os, json, time
from typing import Dict, Any, List, Optional
from collections import defaultdict

LOGS_DIR = "logs"
os.makedirs(LOGS_DIR, exist_ok=True)

LEARNING_UPDATES_LOG  = f"{LOGS_DIR}/learning_updates.jsonl"
META_LEARN_LOG        = f"{LOGS_DIR}/meta_learning.jsonl"
COUNTERFACTUAL_LOG    = f"{LOGS_DIR}/counterfactual_engine.jsonl"
KNOWLEDGE_GRAPH_LOG   = f"{LOGS_DIR}/knowledge_graph.jsonl"
FEE_TIER_CFG_PATH     = "config/fee_tier_config.json"

ROLLBACK_EXPECTANCY = 0.30
ROLLBACK_UPLIFT     = 0.0
CONSECUTIVE_DEGRADE_LIMIT = 2

# Fee baselines (must match fee_aware_governor.py)
MAKER_BASE = 0.02
TAKER_BASE = 0.06

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

def _read_jsonl(path, limit=2000):
    rows=[]
    if not os.path.exists(path): return rows
    with open(path,"r") as f:
        for line in f:
            line=line.strip()
            if not line: continue
            try: rows.append(json.loads(line))
            except: continue
    return rows[-limit:]

def _knowledge_link(subject: Dict[str,Any], predicate: str, obj: Dict[str,Any]):
    _append_jsonl(KNOWLEDGE_GRAPH_LOG, {"ts": _now(), "subject": subject, "predicate": predicate, "object": obj})

def _recent_expectancy(default=0.0):
    rows=_read_jsonl(META_LEARN_LOG, 1000)
    for r in reversed(rows):
        ex = r.get("expectancy", {})
        val = ex.get("score") if isinstance(ex, dict) else None
        if val is not None:
            try: return float(val)
            except: break
    return default

def _recent_uplift_total(default=0.0):
    rows=_read_jsonl(COUNTERFACTUAL_LOG, 1000)
    for r in reversed(rows):
        ut = r.get("uplift_total")
        if ut is not None:
            try: return float(ut)
            except: break
    return default

class FeeAttributionModule:
    """
    Links fee calibration outcomes to expectancy uplift and records attribution scores.
    """
    def __init__(self):
        self.cfg = _read_json(FEE_TIER_CFG_PATH, default={})

    def _aggregate_calibrations(self):
        rows=_read_jsonl(LEARNING_UPDATES_LOG, 2000)
        applied=[r.get("applied") for r in rows if r.get("update_type")=="fee_calibration_applied"]
        return applied[-1] if applied else {}

    def run_cycle(self) -> Dict[str,Any]:
        applied=self._aggregate_calibrations()
        expectancy=_recent_expectancy()
        uplift=_recent_uplift_total()

        attribution={}
        for tier,data in (applied or {}).items():
            delta_maker=data["maker_new"]-data["maker_old"]
            delta_taker=data["taker_new"]-data["taker_old"]
            attribution[tier]={
                "delta_maker": delta_maker,
                "delta_taker": delta_taker,
                "symbols": data.get("symbols", []),
                "expectancy": expectancy,
                "uplift": uplift,
                "effective": (expectancy>=ROLLBACK_EXPECTANCY and uplift>=ROLLBACK_UPLIFT)
            }
            # Knowledge graph causal link
            _knowledge_link({"tier":tier,"symbols":data.get("symbols",[])},
                            "fee_calibration_attribution",
                            {"delta_maker":delta_maker,"delta_taker":delta_taker,"expectancy":expectancy,"uplift":uplift})

        summary={
            "ts":_now(),
            "applied":applied,
            "attribution":attribution,
            "email_body":f"""
=== Fee Attribution Module ===
Expectancy: {expectancy:.3f}  Uplift: {uplift:.3f}
Calibrations applied: {list(applied.keys())}
Attribution results:
{json.dumps(attribution, indent=2)}
""".strip()
        }
        _append_jsonl(LEARNING_UPDATES_LOG, {"ts":summary["ts"],"update_type":"fee_attribution_cycle","summary":{k:v for k,v in summary.items() if k!='email_body'}})
        return summary

    def nightly_rollback(self) -> Dict[str,Any]:
        expectancy=_recent_expectancy()
        uplift=_recent_uplift_total()
        live=_read_json("live_config.json",default={}) or {}
        rt=live.get("runtime",{})
        degrade_count=int(rt.get("fee_attribution_degrade_count",0))

        if expectancy<ROLLBACK_EXPECTANCY or uplift<ROLLBACK_UPLIFT:
            degrade_count+=1
        else:
            degrade_count=max(0,degrade_count-1)

        rolled_back=False
        if degrade_count>=CONSECUTIVE_DEGRADE_LIMIT:
            # Reset fee tiers to baseline
            cfg=self.cfg
            for tier in (cfg.get("tiers",{}) or {}).keys():
                cfg["tiers"][tier]["maker_pct"]=MAKER_BASE
                cfg["tiers"][tier]["taker_pct"]=TAKER_BASE
            _write_json(FEE_TIER_CFG_PATH,cfg)
            rolled_back=True
            _append_jsonl(LEARNING_UPDATES_LOG,{"ts":_now(),"update_type":"fee_attribution_rollback","reason":"expectancy_or_uplift_degrade","expectancy":expectancy,"uplift":uplift})
            _knowledge_link({"expectancy":expectancy,"uplift":uplift},"fee_attribution_rollback",{"rolled_back":True})

        live.setdefault("runtime",{})["fee_attribution_degrade_count"]=degrade_count
        _write_json("live_config.json",live)

        return {"rolled_back":rolled_back,"degrade_count":degrade_count,"expectancy":expectancy,"uplift":uplift}

# ---------------- CLI ----------------
if __name__=="__main__":
    fam=FeeAttributionModule()
    res=fam.run_cycle()
    print(json.dumps(res,indent=2))
    print("\n--- Email Body ---\n")
    print(res["email_body"])
    rb=fam.nightly_rollback()
    print("\nRollback:",json.dumps(rb,indent=2))
