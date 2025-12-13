# src/phase_294_297_expansion_integrated.py
#
# Phases 294–297: Advanced Autonomy Expansion (Integrated into bot_cycle)
# - 294: Meta-Learning Exploration Decay (adaptive exploration quotas by regime & confidence)
# - 295: Challenger Experiment Engine (spawn nightly micro-tests, retire losers, promote winners)
# - 296: Expectancy-Driven Curriculum (allocate exploration quota to weakest regimes/symbols)
# - 297: Risk Elasticity Governor (adjust leverage & position sizing dynamically by health + expectancy)

import os, json, time, random

LOG_DIR = "logs"
EXPANSION_LOG = os.path.join(LOG_DIR, "expansion_trace.jsonl")

def _now(): 
    return int(time.time())

def _append_jsonl(path, obj): 
    os.makedirs(os.path.dirname(path), exist_ok=True)
    open(path, "a").write(json.dumps(obj) + "\n")

def exploration_decay(stage: str, regime: str, confidence: float) -> int:
    base = {"bootstrap": 12, "unlocked": 8, "high_confidence": 4}
    quota = base.get(stage, 4)
    decay = int(quota * (1.0 - confidence))
    if regime in ["chop", "uncertain"]:
        decay += 2
    return max(1, decay)

def challenger_experiments(symbol: str, regime: str) -> dict:
    experiments = [
        {"name": "timing_offset", "param": random.choice([5, 10, 15])},
        {"name": "venue_bias", "param": random.choice(["maker_pref", "taker_pref"])},
        {"name": "entry_filter", "param": random.choice(["tight_spread", "loose_spread"])},
    ]
    selected = random.sample(experiments, k=random.randint(1, 2))
    return {"symbol": symbol, "regime": regime, "experiments": selected}

def expectancy_curriculum(expectancy_by_regime: dict) -> dict:
    weakest = min(expectancy_by_regime, key=expectancy_by_regime.get)
    allocation = {r: (6 if r == weakest else 2) for r in expectancy_by_regime.keys()}
    return {"allocation": allocation, "weakest": weakest}

def risk_elasticity(health: float, rolling_ev: float) -> float:
    base = 1.0
    if health > 0.85 and rolling_ev > 0.1:
        base *= 1.25
    elif health < 0.75 or rolling_ev < 0.0:
        base *= 0.75
    return round(base, 3)

def run_expansion_cycle(stage: str, regime: str, confidence: float,
                        symbol: str, expectancy_by_regime: dict,
                        health: float, rolling_ev: float) -> dict:
    decay_quota = exploration_decay(stage, regime, confidence)
    challenger = challenger_experiments(symbol, regime)
    curriculum = expectancy_curriculum(expectancy_by_regime)
    risk_mult = risk_elasticity(health, rolling_ev)

    summary = {
        "ts": _now(),
        "stage": stage,
        "regime": regime,
        "confidence": confidence,
        "decay_quota": decay_quota,
        "challenger": challenger,
        "curriculum": curriculum,
        "risk_multiplier": risk_mult
    }
    _append_jsonl(EXPANSION_LOG, summary)
    return summary

def nightly_orchestrator_hook(stage: str, regime: str, confidence: float,
                              symbol: str, expectancy_by_regime: dict,
                              health: float, rolling_ev: float):
    summary = run_expansion_cycle(stage, regime, confidence, symbol,
                                  expectancy_by_regime, health, rolling_ev)
    print("Expansion cycle summary:", json.dumps(summary, indent=2))

if __name__ == "__main__":
    example = nightly_orchestrator_hook(
        stage="bootstrap",
        regime="chop",
        confidence=0.3,
        symbol="SOLUSDT",
        expectancy_by_regime={"trend":0.12,"chop":-0.05,"uncertain":0.02},
        health=0.83,
        rolling_ev=0.08
    )
