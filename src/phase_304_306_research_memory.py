# src/phase_304_306_research_memory.py
#
# Phases 304–306: Research Memory & Auto-Promotion
# - 304: Hypothesis Tracker (ledger of generated hypotheses, challenger configs, and outcomes)
# - 305: Auto-Promotion Engine (promote successful hypotheses into live configs automatically)
# - 306: Research Memory Auditor (audit/prune hypothesis ledger + knowledge graph for consistency)
#
# Purpose: Give the bot structured research memory, promote proven ideas, and keep research clean.

import os, json, time, random

LOG_DIR = "logs"
HYPOTHESIS_LOG = os.path.join(LOG_DIR, "hypothesis_ledger.jsonl")
PROMOTION_LOG = os.path.join(LOG_DIR, "promotion_trace.jsonl")
AUDIT_LOG = os.path.join(LOG_DIR, "research_audit_trace.jsonl")
KG_PATH = os.path.join(LOG_DIR, "knowledge_graph.jsonl")

def _now(): return int(time.time())
def _append_jsonl(path, obj): os.makedirs(os.path.dirname(path), exist_ok=True); open(path, "a").write(json.dumps(obj) + "\n")
def _read_jsonl(path): return [json.loads(l) for l in open(path)] if os.path.exists(path) else []

# ======================================================================
# 304 – Hypothesis Tracker
# ======================================================================
def track_hypothesis(hypothesis: str, config: dict) -> dict:
    """
    Record a hypothesis, its challenger config, and initial status.
    """
    entry = {
        "ts": _now(),
        "hypothesis": hypothesis,
        "config": config,
        "status": "pending",
        "outcome_ev": None
    }
    _append_jsonl(HYPOTHESIS_LOG, entry)
    return entry

def update_hypothesis_outcome(hypothesis: str, outcome_ev: float) -> dict:
    """
    Update hypothesis ledger with realized outcome expectancy.
    """
    entries = _read_jsonl(HYPOTHESIS_LOG)
    updated = None
    for e in entries:
        if e["hypothesis"] == hypothesis and e["status"] == "pending":
            e["status"] = "completed"
            e["outcome_ev"] = outcome_ev
            updated = e
    if updated:
        with open(HYPOTHESIS_LOG, "w") as f:
            for e in entries:
                f.write(json.dumps(e) + "\n")
    return updated

# ======================================================================
# 305 – Auto-Promotion Engine
# ======================================================================
def auto_promote(threshold_ev: float = 0.05) -> list:
    """
    Promote hypotheses with outcome_ev > threshold_ev into live configs.
    """
    entries = _read_jsonl(HYPOTHESIS_LOG)
    promoted = []
    for e in entries:
        if e["status"] == "completed" and e["outcome_ev"] is not None and e["outcome_ev"] > threshold_ev:
            promo = {
                "ts": _now(),
                "hypothesis": e["hypothesis"],
                "config": e["config"],
                "outcome_ev": e["outcome_ev"],
                "action": "PROMOTED"
            }
            _append_jsonl(PROMOTION_LOG, promo)
            promoted.append(promo)
    return promoted

# ======================================================================
# 306 – Research Memory Auditor
# ======================================================================
def audit_research_memory(max_age_days: int = 60) -> dict:
    """
    Audit hypothesis ledger and knowledge graph for consistency.
    - Remove stale hypotheses older than max_age_days
    - Flag contradictions between signals and outcomes
    """
    cutoff = _now() - max_age_days*86400
    ledger = _read_jsonl(HYPOTHESIS_LOG)
    kg = _read_jsonl(KG_PATH)

    pruned_ledger = [e for e in ledger if e["ts"] >= cutoff]
    contradictions = []
    for e in kg:
        signals = e.get("signals", {})
        outcome = e.get("outcome_ev", 0.0)
        if outcome < 0 and max(signals.values()) > 0.5:
            contradictions.append(e)

    audit = {
        "ts": _now(),
        "ledger_size_before": len(ledger),
        "ledger_size_after": len(pruned_ledger),
        "contradictions_found": len(contradictions)
    }
    _append_jsonl(AUDIT_LOG, audit)

    # Rewrite pruned ledger
    with open(HYPOTHESIS_LOG, "w") as f:
        for e in pruned_ledger:
            f.write(json.dumps(e) + "\n")

    return audit

# ======================================================================
# Orchestrator Hook
# ======================================================================
def run_research_memory_cycle(hypotheses: list, experiments: list) -> dict:
    """
    Track new hypotheses and experiments, check for promotions, and audit.
    """
    tracked = []
    for i, h in enumerate(hypotheses):
        config = experiments[i]["config"] if i < len(experiments) else {}
        tracked.append(track_hypothesis(h, config))
    
    promoted = auto_promote()
    audit = audit_research_memory()

    summary = {
        "ts": _now(),
        "tracked": tracked,
        "promoted": promoted,
        "audit": audit
    }
    return summary

# CLI quick run
if __name__ == "__main__":
    example = run_research_memory_cycle(
        hypotheses=["Hypothesis: OFI + Sentiment synergy in chop regime improves expectancy."],
        experiments=[{"hypothesis": "test", "config": {"risk_mult":1.1,"threshold":0.25,"exploration_bias":"focused"}}]
    )
    print("Research memory cycle summary:", json.dumps(example, indent=2))
