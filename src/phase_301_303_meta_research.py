# src/phase_301_303_meta_research.py
#
# Phases 301–303: Meta-Research & Governance Overlays
# - 301: Expectancy Attribution Governor (route more capital to signals/regimes with proven lift)
# - 302: Self-Healing Knowledge Graph (auto-prune stale/contradictory entries)
# - 303: Meta-Research Brain (generate nightly hypotheses from knowledge graph, spawn challenger experiments)
#
# Purpose: Let the bot research itself, evolve hypotheses, and govern capital allocation at meta-level.

import os, json, time, random
from collections import defaultdict

LOG_DIR = "logs"
META_RESEARCH_LOG = os.path.join(LOG_DIR, "meta_research_trace.jsonl")
KG_PATH = os.path.join(LOG_DIR, "knowledge_graph.jsonl")

def _now(): return int(time.time())
def _append_jsonl(path, obj): os.makedirs(os.path.dirname(path), exist_ok=True); open(path, "a").write(json.dumps(obj) + "\n")
def _read_jsonl(path): return [json.loads(l) for l in open(path)] if os.path.exists(path) else []

# ======================================================================
# 301 – Expectancy Attribution Governor
# ======================================================================
def expectancy_governor(signal_ev: dict, base_alloc: dict, total_capital: float = 100000.0) -> dict:
    """
    Route more capital to signals/regimes with proven expectancy lift.
    signal_ev: {"ofi":0.12,"micro_arb":0.05,"sentiment":-0.02,"regime":0.08}
    base_alloc: {"BTCUSDT":30000,"ETHUSDT":40000,"SOLUSDT":30000}
    """
    boost_factor = {sig: max(0.5, 1.0 + ev) for sig, ev in signal_ev.items()}
    boosted = {}
    total = sum(base_alloc.values())
    for sym, alloc in base_alloc.items():
        # Example: weight OFI more if EV positive
        boosted[sym] = round(alloc * (1.0 + sum(boost_factor.values())/len(boost_factor)), 2)
    # Normalize back to total_capital
    scale = total_capital / sum(boosted.values()) if sum(boosted.values()) > 0 else 1.0
    boosted = {sym: round(val * scale, 2) for sym, val in boosted.items()}
    return boosted

# ======================================================================
# 302 – Self-Healing Knowledge Graph
# ======================================================================
def prune_knowledge_graph(max_age_days: int = 30) -> list:
    """
    Auto-prune stale or contradictory entries from knowledge graph.
    - Remove entries older than max_age_days
    - Remove entries with outcome_ev contradictory to signals (e.g., strong positive signals but negative outcome)
    """
    entries = _read_jsonl(KG_PATH)
    cutoff = _now() - max_age_days*86400
    pruned = []
    for e in entries:
        if e["ts"] < cutoff: continue
        signals = e.get("signals", {})
        outcome = e.get("outcome_ev", 0.0)
        if outcome < 0 and max(signals.values()) > 0.5:
            continue  # contradictory
        pruned.append(e)
    # Rewrite pruned graph
    with open(KG_PATH, "w") as f:
        for e in pruned:
            f.write(json.dumps(e) + "\n")
    return pruned

# ======================================================================
# 303 – Meta-Research Brain
# ======================================================================
def generate_hypotheses(entries: list, max_hypotheses: int = 3) -> list:
    """
    Generate nightly hypotheses from knowledge graph entries.
    Example: "OFI + sentiment synergy in chop regimes improves expectancy"
    """
    hypotheses = []
    regimes = set(e.get("regime","uncertain") for e in entries)
    signals = ["ofi","micro_arb","sentiment","regime"]
    for _ in range(min(max_hypotheses, len(regimes))):
        r = random.choice(list(regimes))
        s1, s2 = random.sample(signals, 2)
        hypotheses.append(f"Hypothesis: {s1.upper()} + {s2.upper()} synergy in {r} regime improves expectancy.")
    return hypotheses

def spawn_challenger_experiments(hypotheses: list) -> list:
    """
    Spawn challenger experiments to test hypotheses.
    """
    experiments = []
    for h in hypotheses:
        experiments.append({
            "hypothesis": h,
            "config": {
                "risk_mult": random.choice([0.9,1.0,1.1]),
                "threshold": random.choice([0.20,0.25,0.30]),
                "exploration_bias": random.choice(["focused","broad"])
            }
        })
    return experiments

# ======================================================================
# Orchestrator Hook
# ======================================================================
def run_meta_research(signal_ev: dict, base_alloc: dict, total_capital: float = 100000.0) -> dict:
    boosted_alloc = expectancy_governor(signal_ev, base_alloc, total_capital)
    pruned_graph = prune_knowledge_graph()
    hypotheses = generate_hypotheses(pruned_graph)
    experiments = spawn_challenger_experiments(hypotheses)

    summary = {
        "ts": _now(),
        "boosted_alloc": boosted_alloc,
        "hypotheses": hypotheses,
        "experiments": experiments
    }
    _append_jsonl(META_RESEARCH_LOG, summary)
    return summary

# CLI quick run
if __name__ == "__main__":
    example = run_meta_research(
        signal_ev={"ofi":0.12,"micro_arb":0.05,"sentiment":-0.02,"regime":0.08},
        base_alloc={"BTCUSDT":30000,"ETHUSDT":40000,"SOLUSDT":30000},
        total_capital=100000.0
    )
    print("Meta-research summary:", json.dumps(example, indent=2))
