# src/meta_governor.py
#
# v5.6 Meta-Governor Orchestrator
# Unifies Trade Liveness Monitor + Profitability Governor + Health Pulse into one cycle.
# Produces a single digest entry every 30 minutes with resilience + profitability actions.

import os, json, time
from typing import Dict, Any

from src.trade_liveness_monitor import TradeLivenessMonitor
from src.profitability_governor import ProfitabilityGovernor
from src.governance_patch import PatchOrchestrator  # optional, for health pulse/severity

LOGS_DIR = "logs"
os.makedirs(LOGS_DIR, exist_ok=True)

META_GOV_LOG = f"{LOGS_DIR}/meta_governor.jsonl"
LEARNING_UPDATES_LOG = f"{LOGS_DIR}/learning_updates.jsonl"

def _append_jsonl(path, obj):
    with open(path, "a") as f: f.write(json.dumps(obj) + "\n")

def _now(): return int(time.time())

class MetaGovernor:
    def __init__(self):
        self.liveness = TradeLivenessMonitor()
        self.profit = ProfitabilityGovernor()
        self.patch = PatchOrchestrator()  # includes health pulse + severity flags

    def run_cycle(self) -> Dict[str,Any]:
        # Step 1: Run liveness monitor (without profitability governor embedded)
        live_summary = self.liveness.run_cycle()

        # Step 2: Run profitability governor
        profit_summary = self.profit.run_cycle()

        # Step 3: Apply governance patch safeguards (health pulse, watchdog, kill-switch)
        patch_summary = self.patch.apply_all()

        # Step 4: Consolidate into one digest entry
        digest = {
            "ts": _now(),
            "resilience": {
                "idle_minutes": live_summary["idle_minutes"],
                "actions": live_summary["actions"],
                "blockers": live_summary["blockers"],
                "passable": live_summary["passable"]
            },
            "profitability": {
                "persistence": profit_summary.get("persistence", {}),
                "actions": profit_summary.get("actions", []),
                "top_missed": profit_summary.get("top_missed", [])
            },
            "health": {
                "severity": patch_summary.get("health_severity", {}),
                "degraded_mode": patch_summary.get("degraded_mode", False),
                "kill_switch_cleared": patch_summary.get("kill_switch_cleared", False)
            }
        }

        # Step 5: Persist logs
        _append_jsonl(META_GOV_LOG, digest)
        _append_jsonl(LEARNING_UPDATES_LOG, {"ts": digest["ts"], "update_type":"meta_governor_cycle", "digest": digest})

        return digest

# ---------------- CLI ----------------
if __name__ == "__main__":
    mg = MetaGovernor()
    res = mg.run_cycle()
    print("Meta-Governor Digest:", json.dumps(res, indent=2))
