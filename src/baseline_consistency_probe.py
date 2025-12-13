# src/baseline_consistency_probe.py
#
# v5.7 Baseline Consistency Probe
# Purpose: Verify that all modules are aligned with the centralized composite baseline config.
# Redundancy layers:
#   1. Primary source: config/composite_baseline.json
#   2. Backup: live_config.json.backup
#   3. Probe: checks each module for hardcoded baseline drift
#   4. Self-Remediation: auto-nudge thresholds if drift detected
#   5. Emergency Autonomy Suite: restores baseline from backup if corruption occurs
#
# Integration:
#   from src.baseline_consistency_probe import BaselineConsistencyProbe
#   probe = BaselineConsistencyProbe()
#   summary = probe.run_cycle()
#   print(summary["email_body"])

import os, json, time

LOGS_DIR = "logs"
os.makedirs(LOGS_DIR, exist_ok=True)

CONFIG_DIR = "config"
os.makedirs(CONFIG_DIR, exist_ok=True)

BASELINE_CONFIG_PATH = f"{CONFIG_DIR}/composite_baseline.json"
LIVE_CFG_PATH        = "live_config.json"
LEARNING_UPDATES_LOG = f"{LOGS_DIR}/learning_updates.jsonl"
KNOWLEDGE_GRAPH_LOG  = f"{LOGS_DIR}/knowledge_graph.jsonl"

MODULES = [
    "counterfactual_scaling_engine.py",
    "emergency_autonomy_suite.py",
    "meta_research_desk.py",
    "trade_liveness_monitor.py",
    "governance_patch.py",
    "profitability_governor.py"
]

def _now(): return int(time.time())

def _append_jsonl(path, obj):
    with open(path,"a") as f: f.write(json.dumps(obj) + "\n")

def _read_json(path, default=None):
    if not os.path.exists(path): return default
    try:
        with open(path,"r") as f: return json.load(f)
    except: return default

def _write_json(path, obj):
    tmp = path + ".tmp"
    with open(tmp,"w") as f: json.dump(obj, f, indent=2)
    os.replace(tmp, path)

def _knowledge_link(subject, predicate, obj):
    _append_jsonl(KNOWLEDGE_GRAPH_LOG, {"ts": _now(), "subject": subject, "predicate": predicate, "object": obj})

class BaselineConsistencyProbe:
    def __init__(self):
        self.baseline = _read_json(BASELINE_CONFIG_PATH, default={"trend":0.07,"chop":0.05,"min":0.05,"max":0.12})
        self.live_cfg = _read_json(LIVE_CFG_PATH, default={})
        self.backup   = (self.live_cfg.get("backup", {}) or {}).get("composite_thresholds", {})

    def _check_module_baseline(self, module_path: str) -> dict:
        try:
            with open(f"src/{module_path}","r") as f:
                text = f.read()
            drift = "0.08" in text  # naive check for hardcoded baseline
            return {"module": module_path, "drift": drift}
        except Exception as e:
            return {"module": module_path, "error": str(e)}

    def run_cycle(self) -> dict:
        results = [self._check_module_baseline(m) for m in MODULES]
        mismatches = [r for r in results if r.get("drift")]

        # Auto-remediation: if drift detected, enforce baseline in live_config
        enforced=None
        if mismatches:
            cfg = self.live_cfg or {}
            filters = cfg.get("filters", {})
            filters["composite_thresholds"] = self.baseline
            cfg["filters"] = filters
            _write_json(LIVE_CFG_PATH, cfg)
            enforced = {"enforced_baseline": self.baseline, "modules_with_drift": [m["module"] for m in mismatches]}
            _append_jsonl(LEARNING_UPDATES_LOG, {"ts": _now(), "update_type":"baseline_enforce", "payload": enforced})
            _knowledge_link({"baseline": self.baseline}, "baseline_enforce", enforced)

        summary = {
            "ts": _now(),
            "baseline": self.baseline,
            "backup": self.backup,
            "results": results,
            "mismatches": mismatches,
            "enforced": enforced,
            "email_body": f"""
=== Baseline Consistency Probe ===
Baseline (primary): {self.baseline}
Backup (live_config): {self.backup}

Modules checked: {len(MODULES)}
Mismatches: {len(mismatches)}

Drift detected in: {[m['module'] for m in mismatches]}
Baseline enforced: {bool(enforced)}
""".strip()
        }
        _append_jsonl(LEARNING_UPDATES_LOG, {"ts": summary["ts"], "update_type":"baseline_consistency_probe", "summary": {k:v for k,v in summary.items() if k!='email_body'}})
        _knowledge_link({"baseline": self.baseline}, "baseline_consistency_probe", {"results": results, "mismatches": mismatches})
        return summary

# CLI
if __name__ == "__main__":
    probe = BaselineConsistencyProbe()
    res = probe.run_cycle()
    print(json.dumps(res, indent=2))
    print("\n--- Email Body ---\n")
    print(res["email_body"])
