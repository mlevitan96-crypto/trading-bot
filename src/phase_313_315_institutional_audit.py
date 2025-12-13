# src/phase_313_315_institutional_audit.py
#
# Phases 313–315: Institutional Meta-Governance
# - 313: Strategic Attribution Council (link roadmap milestones to portfolio expectancy outcomes)
# - 314: Autonomous Budget Governor (allocate research budget across hypotheses based on council priorities)
# - 315: Institutional Audit Layer (generate nightly audit packets summarizing votes, promotions, conflicts, roadmap progress)
#
# Purpose: Close the loop between planning and realized performance, enforce budget discipline, and produce compliance-grade audit trails.

import os, json, time, random

LOG_DIR = "logs"
ATTRIBUTION_LOG = os.path.join(LOG_DIR, "attribution_trace.jsonl")
BUDGET_LOG = os.path.join(LOG_DIR, "budget_governor_trace.jsonl")
AUDIT_LOG = os.path.join(LOG_DIR, "institutional_audit_trace.jsonl")

def _now(): return int(time.time())
def _append_jsonl(path,obj): os.makedirs(os.path.dirname(path),exist_ok=True); open(path,"a").write(json.dumps(obj)+"\n")

# ======================================================================
# 313 – Strategic Attribution Council
# ======================================================================
def attribute_outcomes(roadmap: dict, portfolio_outcomes: dict) -> dict:
    """
    Link roadmap milestones to realized portfolio expectancy outcomes.
    roadmap: {"agenda":[{"day":1,"hypothesis":"...","goal":"trend"}]}
    portfolio_outcomes: {"trend":0.12,"chop":-0.03,"uncertain":0.05}
    """
    attribution = []
    for item in roadmap.get("agenda",[]):
        goal = item.get("goal","general")
        outcome = portfolio_outcomes.get(goal,0.0)
        attribution.append({
            "day": item["day"],
            "hypothesis": item["hypothesis"],
            "goal": goal,
            "realized_ev": outcome
        })
    result = {"ts":_now(),"attribution":attribution}
    _append_jsonl(ATTRIBUTION_LOG,result)
    return result

# ======================================================================
# 314 – Autonomous Budget Governor
# ======================================================================
def allocate_budget(hypotheses: list, priorities: dict, total_budget: int = 100) -> dict:
    """
    Allocate research budget (exploration quota, compute cycles) across hypotheses.
    priorities: {"trend":3,"chop":6,"uncertain":2}
    """
    allocations = {}
    total_priority = sum(priorities.values()) if priorities else 1
    for h in hypotheses:
        regime = "trend" if "trend" in h.lower() else "chop" if "chop" in h.lower() else "uncertain"
        share = priorities.get(regime,1)/total_priority
        allocations[h] = round(total_budget*share,2)
    result = {"ts":_now(),"budget_allocations":allocations}
    _append_jsonl(BUDGET_LOG,result)
    return result

# ======================================================================
# 315 – Institutional Audit Layer
# ======================================================================
def generate_audit_packet(votes: list, promotions: list, conflicts: list, roadmap: dict, attribution: dict, budget: dict) -> dict:
    """
    Generate nightly audit packet summarizing governance activity.
    """
    packet = {
        "ts":_now(),
        "votes":votes,
        "promotions":promotions,
        "conflicts":conflicts,
        "roadmap":roadmap,
        "attribution":attribution,
        "budget":budget
    }
    _append_jsonl(AUDIT_LOG,packet)
    return packet

# ======================================================================
# Orchestrator Hook
# ======================================================================
def run_institutional_audit(roadmap: dict, portfolio_outcomes: dict, hypotheses: list,
                            priorities: dict, votes: list, promotions: list, conflicts: list) -> dict:
    attribution = attribute_outcomes(roadmap,portfolio_outcomes)
    budget = allocate_budget(hypotheses,priorities)
    packet = generate_audit_packet(votes,promotions,conflicts,roadmap,attribution,budget)
    return packet

# CLI quick run
if __name__=="__main__":
    roadmap = {"agenda":[{"day":1,"hypothesis":"Hypothesis: OFI+Sentiment synergy in chop regime","goal":"chop"}]}
    portfolio_outcomes = {"trend":0.12,"chop":-0.03,"uncertain":0.05}
    hypotheses = ["Hypothesis: OFI+Sentiment synergy in chop regime","Hypothesis: Micro-Arb synergy in trend regime"]
    priorities = {"trend":3,"chop":6,"uncertain":2}
    votes = [{"hypothesis":"OFI+Sentiment","votes":{"Governor":"PASS","Researcher":"PASS","RiskManager":"PASS"}}]
    promotions = [{"hypothesis":"OFI+Sentiment","action":"PROMOTED"}]
    conflicts = []
    example = run_institutional_audit(roadmap,portfolio_outcomes,hypotheses,priorities,votes,promotions,conflicts)
    print("Institutional audit packet:",json.dumps(example,indent=2))
