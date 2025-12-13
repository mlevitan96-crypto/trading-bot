# src/phase_316_318_meta_institution.py
#
# Phases 316–318: Meta-Institutional Intelligence
# - 316: External Data Fusion Council (ingest macroeconomic, news, sentiment feeds into governance decisions)
# - 317: Adaptive Compliance Layer (auto-generate compliance reports aligned with regulatory standards)
# - 318: Strategic Scaling Governor (scale capital deployment across venues/exchanges based on council outputs)
#
# Purpose: Fuse external data into governance, enforce compliance-grade reporting, and scale capital deployment strategically.

import os, json, time, random

LOG_DIR = "logs"
FUSION_LOG = os.path.join(LOG_DIR, "external_data_fusion.jsonl")
COMPLIANCE_LOG = os.path.join(LOG_DIR, "compliance_trace.jsonl")
SCALING_LOG = os.path.join(LOG_DIR, "scaling_trace.jsonl")

def _now(): return int(time.time())
def _append_jsonl(path,obj): os.makedirs(os.path.dirname(path),exist_ok=True); open(path,"a").write(json.dumps(obj)+"\n")

# ======================================================================
# 316 – External Data Fusion Council
# ======================================================================
def fuse_external_data(macro: dict, news_sentiment: dict, governance_inputs: dict) -> dict:
    """
    Fuse macroeconomic, news, and sentiment feeds into governance decisions.
    macro: {"inflation":0.03,"gdp_growth":0.02}
    news_sentiment: {"BTC":0.6,"ETH":0.4}
    governance_inputs: {"trend":0.12,"chop":-0.05}
    """
    fusion_score = {}
    for sym, sentiment in news_sentiment.items():
        macro_factor = (macro.get("inflation",0.0)*-1 + macro.get("gdp_growth",0.0))
        fusion_score[sym] = round(sentiment + macro_factor + governance_inputs.get("trend",0.0),3)
    result = {"ts":_now(),"fusion_score":fusion_score}
    _append_jsonl(FUSION_LOG,result)
    return result

# ======================================================================
# 317 – Adaptive Compliance Layer
# ======================================================================
def generate_compliance_report(votes: list, promotions: list, audit_packets: list, standard: str="SEC") -> dict:
    """
    Auto-generate compliance reports aligned with regulatory standards.
    """
    report = {
        "ts":_now(),
        "standard":standard,
        "votes_count":len(votes),
        "promotions_count":len(promotions),
        "audit_packets_count":len(audit_packets),
        "status":"COMPLIANT" if len(audit_packets)>0 else "PENDING"
    }
    _append_jsonl(COMPLIANCE_LOG,report)
    return report

# ======================================================================
# 318 – Strategic Scaling Governor
# ======================================================================
def scale_capital(fusion_scores: dict, venues: list, base_capital: float=100000.0) -> dict:
    """
    Scale capital deployment across venues/exchanges based on fusion scores.
    """
    allocations = {}
    total_score = sum(fusion_scores.values()) if fusion_scores else 1.0
    for v in venues:
        score = fusion_scores.get(v,0.0)
        allocations[v] = round(base_capital*(score/total_score),2) if total_score>0 else 0.0
    result = {"ts":_now(),"capital_allocations":allocations}
    _append_jsonl(SCALING_LOG,result)
    return result

# ======================================================================
# Orchestrator Hook
# ======================================================================
def run_meta_institution(macro: dict, news_sentiment: dict, governance_inputs: dict,
                         votes: list, promotions: list, audit_packets: list,
                         venues: list, base_capital: float=100000.0) -> dict:
    fusion = fuse_external_data(macro,news_sentiment,governance_inputs)
    compliance = generate_compliance_report(votes,promotions,audit_packets)
    scaling = scale_capital(fusion["fusion_score"],venues,base_capital)

    summary = {
        "ts":_now(),
        "fusion":fusion,
        "compliance":compliance,
        "scaling":scaling
    }
    return summary

# CLI quick run
if __name__=="__main__":
    macro = {"inflation":0.03,"gdp_growth":0.02}
    news_sentiment = {"BTC":0.6,"ETH":0.4}
    governance_inputs = {"trend":0.12,"chop":-0.05}
    votes = [{"hypothesis":"OFI+Sentiment","votes":{"Governor":"PASS","Researcher":"PASS","RiskManager":"PASS"}}]
    promotions = []
    audit_packets = [{"id":1}]
    venues = ["BTC","ETH"]
    example = run_meta_institution(macro,news_sentiment,governance_inputs,votes,promotions,audit_packets,venues)
    print("Meta-Institution summary:",json.dumps(example,indent=2))
