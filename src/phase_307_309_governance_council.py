# src/phase_307_309_governance_council.py
#
# Phases 307–309: Research Agenda & Governance Council
# - 307: Research Agenda Scheduler (prioritize hypotheses to test based on expectancy gaps)
# - 308: Cross-Symbol Synergy Engine (detect patterns across symbols, e.g., BTC sentiment + ETH OFI synergy)
# - 309: Governance Council Layer (multi-agent voting system for promotion decisions)
#
# Purpose: Elevate the bot into institutional-grade governance, scheduling research intelligently,
# detecting cross-symbol synergies, and enforcing multi-agent consensus before promotion.

import os, json, time, random
from collections import defaultdict

LOG_DIR = "logs"
COUNCIL_LOG = os.path.join(LOG_DIR, "governance_council_trace.jsonl")
AGENDA_LOG = os.path.join(LOG_DIR, "research_agenda_trace.jsonl")
SYNERGY_LOG = os.path.join(LOG_DIR, "synergy_trace.jsonl")

def _now(): return int(time.time())
def _append_jsonl(path, obj): os.makedirs(os.path.dirname(path), exist_ok=True); open(path,"a").write(json.dumps(obj)+"\n")
def _read_jsonl(path): return [json.loads(l) for l in open(path)] if os.path.exists(path) else []

# ======================================================================
# 307 – Research Agenda Scheduler
# ======================================================================
def schedule_research(hypotheses: list, expectancy_by_regime: dict, max_items: int = 5) -> list:
    """
    Prioritize hypotheses based on expectancy gaps (weakest regimes first).
    """
    weakest = min(expectancy_by_regime, key=expectancy_by_regime.get)
    prioritized = []
    for h in hypotheses:
        if weakest in h.lower():
            prioritized.insert(0,h)
        else:
            prioritized.append(h)
    return prioritized[:max_items]

# ======================================================================
# 308 – Cross-Symbol Synergy Engine
# ======================================================================
def detect_synergies(signal_matrix: dict) -> list:
    """
    Detect cross-symbol synergies.
    signal_matrix: {"BTCUSDT":{"ofi":0.3,"sentiment":0.2}, "ETHUSDT":{"ofi":0.1,"sentiment":0.5}}
    Returns list of synergy hypotheses.
    """
    synergies = []
    symbols = list(signal_matrix.keys())
    for i in range(len(symbols)):
        for j in range(i+1,len(symbols)):
            s1,s2 = symbols[i],symbols[j]
            sigs1,sigs2 = signal_matrix[s1],signal_matrix[s2]
            if sigs1.get("ofi",0)>0.2 and sigs2.get("sentiment",0)>0.2:
                synergies.append(f"Hypothesis: {s1} OFI + {s2} Sentiment synergy improves expectancy.")
    return synergies

# ======================================================================
# 309 – Governance Council Layer
# ======================================================================
def governance_vote(hypothesis: str, configs: dict) -> dict:
    """
    Multi-agent voting system: governors, researchers, risk managers.
    Each agent votes PASS/FAIL based on simple heuristics.
    """
    agents = ["Governor","Researcher","RiskManager"]
    votes = {}
    for a in agents:
        if a=="Governor":
            votes[a] = "PASS" if configs.get("risk_mult",1.0)<=1.25 else "FAIL"
        elif a=="Researcher":
            votes[a] = "PASS" if configs.get("threshold",0.25)<=0.30 else "FAIL"
        elif a=="RiskManager":
            votes[a] = "PASS" if configs.get("exploration_bias","focused")=="focused" else "FAIL"
    allow = list(votes.values()).count("PASS")>=2
    decision = {"ts":_now(),"hypothesis":hypothesis,"votes":votes,"allow_promotion":allow}
    _append_jsonl(COUNCIL_LOG,decision)
    return decision

# ======================================================================
# Orchestrator Hook
# ======================================================================
def run_governance_cycle(hypotheses: list, expectancy_by_regime: dict, signal_matrix: dict, configs: dict) -> dict:
    agenda = schedule_research(hypotheses,expectancy_by_regime)
    synergies = detect_synergies(signal_matrix)
    council = governance_vote(agenda[0] if agenda else "None", configs)

    summary = {
        "ts":_now(),
        "agenda":agenda,
        "synergies":synergies,
        "council_decision":council
    }
    _append_jsonl(AGENDA_LOG,{"agenda":agenda,"ts":_now()})
    _append_jsonl(SYNERGY_LOG,{"synergies":synergies,"ts":_now()})
    return summary

# CLI quick run
if __name__=="__main__":
    example = run_governance_cycle(
        hypotheses=[
            "Hypothesis: OFI + Sentiment synergy in chop regime improves expectancy.",
            "Hypothesis: Micro-Arb + Regime synergy in trend regime improves expectancy."
        ],
        expectancy_by_regime={"trend":0.12,"chop":-0.05,"uncertain":0.02},
        signal_matrix={
            "BTCUSDT":{"ofi":0.3,"sentiment":0.2},
            "ETHUSDT":{"ofi":0.1,"sentiment":0.5}
        },
        configs={"risk_mult":1.1,"threshold":0.25,"exploration_bias":"focused"}
    )
    print("Governance cycle summary:",json.dumps(example,indent=2))
