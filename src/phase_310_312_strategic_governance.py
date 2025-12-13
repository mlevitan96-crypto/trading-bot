# src/phase_310_312_strategic_governance.py
#
# Phases 310–312: Strategic Meta-Governance
# - 310: Council Memory & Voting Ledger (permanent record of votes, rationales, outcomes)
# - 311: Conflict Resolution Engine (detect persistent disagreements, spawn arbitration experiments)
# - 312: Strategic Roadmap Generator (rolling 7-day research agenda aligned with portfolio goals)
#
# Purpose: Elevate governance into institutional-grade planning, arbitration, and roadmap creation.

import os, json, time, random
from collections import defaultdict

LOG_DIR = "logs"
VOTING_LEDGER = os.path.join(LOG_DIR, "voting_ledger.jsonl")
CONFLICT_LOG = os.path.join(LOG_DIR, "conflict_resolution_trace.jsonl")
ROADMAP_LOG = os.path.join(LOG_DIR, "strategic_roadmap_trace.jsonl")

def _now(): return int(time.time())
def _append_jsonl(path, obj): os.makedirs(os.path.dirname(path), exist_ok=True); open(path,"a").write(json.dumps(obj)+"\n")
def _read_jsonl(path): return [json.loads(l) for l in open(path)] if os.path.exists(path) else []

# ======================================================================
# 310 – Council Memory & Voting Ledger
# ======================================================================
def record_vote(hypothesis: str, votes: dict, rationale: str, outcome: bool) -> dict:
    entry = {
        "ts": _now(),
        "hypothesis": hypothesis,
        "votes": votes,
        "rationale": rationale,
        "outcome": outcome
    }
    _append_jsonl(VOTING_LEDGER, entry)
    return entry

# ======================================================================
# 311 – Conflict Resolution Engine
# ======================================================================
def resolve_conflict(hypothesis: str, votes: dict, configs: dict) -> dict:
    """
    Detect persistent disagreements (e.g., <2/3 consensus).
    Spawn arbitration experiments if conflict persists.
    """
    pass_count = list(votes.values()).count("PASS")
    fail_count = list(votes.values()).count("FAIL")
    conflict = pass_count < 2
    resolution = None
    if conflict:
        resolution = {
            "ts": _now(),
            "hypothesis": hypothesis,
            "conflict": True,
            "arbitration_experiment": {
                "risk_mult": random.choice([0.9,1.0,1.1]),
                "threshold": random.choice([0.20,0.25,0.30]),
                "exploration_bias": random.choice(["focused","broad"])
            }
        }
        _append_jsonl(CONFLICT_LOG, resolution)
    return resolution

# ======================================================================
# 312 – Strategic Roadmap Generator
# ======================================================================
def generate_roadmap(hypotheses: list, portfolio_goals: dict) -> dict:
    """
    Build a rolling 7-day research agenda.
    Align hypotheses with portfolio goals (e.g., improve chop regime expectancy).
    """
    agenda = []
    for day in range(1,8):
        h = random.choice(hypotheses) if hypotheses else "None"
        goal = random.choice(list(portfolio_goals.keys())) if portfolio_goals else "General"
        agenda.append({"day": day, "hypothesis": h, "goal": goal})
    roadmap = {"ts": _now(), "agenda": agenda}
    _append_jsonl(ROADMAP_LOG, roadmap)
    return roadmap

# ======================================================================
# Orchestrator Hook
# ======================================================================
def run_strategic_governance(hypothesis: str, votes: dict, rationale: str,
                             configs: dict, hypotheses: list, portfolio_goals: dict) -> dict:
    vote_entry = record_vote(hypothesis, votes, rationale, outcome=(list(votes.values()).count("PASS")>=2))
    conflict = resolve_conflict(hypothesis, votes, configs)
    roadmap = generate_roadmap(hypotheses, portfolio_goals)

    summary = {
        "ts": _now(),
        "vote_entry": vote_entry,
        "conflict_resolution": conflict,
        "roadmap": roadmap
    }
    return summary

# CLI quick run
if __name__=="__main__":
    example = run_strategic_governance(
        hypothesis="Hypothesis: OFI + Sentiment synergy in chop regime improves expectancy.",
        votes={"Governor":"PASS","Researcher":"FAIL","RiskManager":"PASS"},
        rationale="Governor and RiskManager approved, Researcher flagged threshold risk.",
        configs={"risk_mult":1.1,"threshold":0.25,"exploration_bias":"focused"},
        hypotheses=[
            "Hypothesis: Micro-Arb + Regime synergy in trend regime improves expectancy.",
            "Hypothesis: Sentiment + Regime synergy in breakout regime improves expectancy."
        ],
        portfolio_goals={"trend":"Improve trend expectancy","chop":"Reduce chop losses"}
    )
    print("Strategic governance summary:",json.dumps(example,indent=2))
