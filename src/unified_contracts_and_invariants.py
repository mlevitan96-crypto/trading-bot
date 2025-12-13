# unified_contracts_and_invariants.py
#
# v5.7 Contracts + Preflight Invariants (Unified)
# Purpose:
#   - Install and validate JSON schema for fee_tier_config.json (basis-point units, correct structure)
#   - Run preflight invariants before each orchestrator cycle to prevent silent failures
#   - Fail-fast with auto-remediation intents logged (rollback, restart scheduler/feeds)
#
# Usage:
#   python3 unified_contracts_and_invariants.py  # bootstraps schema and runs invariants once
#
# Integration (in orchestrator pre-cycle):
#   import unified_contracts_and_invariants as uci
#   res = uci.run_preflight_invariants()
#   if res["fixes"]:
#       # quarantine cycle, perform remediation hooks, then re-run once healthy

import os, json, time
from typing import Dict, Any

try:
    from jsonschema import validate, ValidationError
except ImportError:
    # Minimal fallback: informative error to install dependency
    raise SystemExit("Please install jsonschema: pip install jsonschema")

# ---------------- Paths ----------------
LOGS_DIR = "logs"
CONFIG_DIR = "config"
os.makedirs(LOGS_DIR, exist_ok=True)
os.makedirs(CONFIG_DIR, exist_ok=True)

FEE_TIER_CFG_PATH     = f"{CONFIG_DIR}/fee_tier_config.json"
FEE_TIER_SCHEMA_PATH  = f"{CONFIG_DIR}/fee_tier_config.schema.json"
LEARNING_UPDATES_LOG  = f"{LOGS_DIR}/learning_updates.jsonl"
LIVE_CFG_PATH         = "live_config.json"

# ---------------- Contracts & Gates ----------------
# Units: thresholds in decimal percentage basis points (e.g., 0.0006 = 6 bps = 0.06%)
BPS_MIN = 0.0001  # 1 bps  = 0.01%
BPS_MAX = 0.01    # 100 bps = 1.00%

SCHEDULER_HEARTBEAT_MAX_SECS = 60 * 90  # 90 minutes
FEED_FRESH_SECS              = 2        # signals should refresh within 2 seconds

# ---------------- Utilities ----------------
def _now() -> int:
    return int(time.time())

def _append_jsonl(path: str, obj: Dict[str, Any]) -> None:
    with open(path, "a") as f:
        f.write(json.dumps(obj) + "\n")

def _read_json(path: str, default=None):
    if not os.path.exists(path):
        return default
    try:
        with open(path, "r") as f:
            return json.load(f)
    except Exception:
        return default

def _write_json(path: str, obj) -> None:
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(obj, f, indent=2)
    os.replace(tmp, path)

# ---------------- Fee Tier Config Schema (as Python dict) ----------------
FEE_TIER_CONFIG_SCHEMA = {
    "$schema": "http://json-schema.org/draft-07/schema#",
    "title": "Fee Tier Config",
    "type": "object",
    "required": ["tiers", "symbols"],
    "properties": {
        "tiers": {
            "type": "object",
            "required": ["anchors", "mid", "high"],
            "properties": {
                "anchors": {
                    "type": "object",
                    "required": ["maker_pct", "taker_pct"],
                    "properties": {
                        "maker_pct": {"type": "number", "minimum": BPS_MIN, "maximum": BPS_MAX},
                        "taker_pct": {"type": "number", "minimum": BPS_MIN, "maximum": BPS_MAX}
                    }
                },
                "mid": {
                    "type": "object",
                    "required": ["maker_pct", "taker_pct"],
                    "properties": {
                        "maker_pct": {"type": "number", "minimum": BPS_MIN, "maximum": BPS_MAX},
                        "taker_pct": {"type": "number", "minimum": BPS_MIN, "maximum": BPS_MAX}
                    }
                },
                "high": {
                    "type": "object",
                    "required": ["maker_pct", "taker_pct"],
                    "properties": {
                        "maker_pct": {"type": "number", "minimum": BPS_MIN, "maximum": BPS_MAX},
                        "taker_pct": {"type": "number", "minimum": BPS_MIN, "maximum": BPS_MAX}
                    }
                }
            }
        },
        "symbols": {
            "type": "object",
            "additionalProperties": {
                "type": "string",
                "enum": ["anchors", "mid", "high"]
            }
        }
    }
}

# ---------------- Bootstrap: ensure schema file exists ----------------
def ensure_fee_tier_schema() -> None:
    if not os.path.exists(FEE_TIER_SCHEMA_PATH):
        _write_json(FEE_TIER_SCHEMA_PATH, FEE_TIER_CONFIG_SCHEMA)
        _append_jsonl(LEARNING_UPDATES_LOG, {
            "ts": _now(),
            "update_type": "schema_bootstrap",
            "file": FEE_TIER_SCHEMA_PATH
        })

# ---------------- Validators ----------------
def validate_fee_tier_config() -> Dict[str, Any]:
    cfg = _read_json(FEE_TIER_CFG_PATH, default={})
    schema = _read_json(FEE_TIER_SCHEMA_PATH, default={})
    if not schema:
        return {"schema_ok": False, "error": "Schema file missing"}

    try:
        validate(instance=cfg, schema=schema)
        return {"schema_ok": True}
    except ValidationError as e:
        return {"schema_ok": False, "error": str(e)}

def validate_fee_tier_units() -> Dict[str, Any]:
    cfg = _read_json(FEE_TIER_CFG_PATH, default={}) or {}
    tiers = cfg.get("tiers", {})
    try:
        for tier_name, vals in tiers.items():
            maker = float(vals.get("maker_pct", 0.0))
            taker = float(vals.get("taker_pct", 0.0))
            if not (BPS_MIN <= maker <= BPS_MAX) or not (BPS_MIN <= taker <= BPS_MAX):
                return {"units_ok": False, "tier": tier_name, "maker_pct": maker, "taker_pct": taker}
        return {"units_ok": True}
    except Exception as e:
        return {"units_ok": False, "error": str(e)}

def check_scheduler_heartbeat() -> Dict[str, Any]:
    live = _read_json(LIVE_CFG_PATH, default={}) or {}
    rt = live.get("runtime", {})
    hb = int(rt.get("scheduler_heartbeat_ts", 0))
    ok = (_now() - hb) <= SCHEDULER_HEARTBEAT_MAX_SECS if hb > 0 else False
    return {"heartbeat_ok": ok, "last_hb_ts": hb}

def check_feed_freshness() -> Dict[str, Any]:
    # Inspect learning_updates for recent OFI/composite markers
    updates = []
    if os.path.exists(LEARNING_UPDATES_LOG):
        with open(LEARNING_UPDATES_LOG, "r") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    updates.append(json.loads(line))
                except Exception:
                    continue

    last_ofi = 0
    last_comp = 0
    for u in reversed(updates):
        if u.get("update_type") == "ofi_signal":
            last_ofi = int(u.get("ts", 0))
            break
    for u in reversed(updates):
        if u.get("update_type") == "composite_filter_result":
            last_comp = int(u.get("ts", 0))
            break

    now = _now()
    ofi_fresh  = (now - last_ofi)  <= FEED_FRESH_SECS if last_ofi  > 0 else False
    comp_fresh = (now - last_comp) <= FEED_FRESH_SECS if last_comp > 0 else False

    return {
        "ofi_fresh": ofi_fresh,
        "comp_fresh": comp_fresh,
        "last_ofi_ts": last_ofi,
        "last_comp_ts": last_comp
    }

# ---------------- Preflight Invariants Runner ----------------
def run_preflight_invariants() -> Dict[str, Any]:
    ensure_fee_tier_schema()

    results = {
        "config_schema": validate_fee_tier_config(),
        "units":         validate_fee_tier_units(),
        "scheduler":     check_scheduler_heartbeat(),
        "feeds":         check_feed_freshness()
    }

    fixes = []
    if not results["config_schema"].get("schema_ok", False):
        fixes.append({"action": "rollback_config", "reason": "schema invalid", "details": results["config_schema"]})
    if not results["units"].get("units_ok", False):
        fixes.append({"action": "rollback_config", "reason": "units out of bounds", "details": results["units"]})
    if not results["scheduler"].get("heartbeat_ok", False):
        fixes.append({"action": "restart_scheduler", "reason": "heartbeat stale"})
    if not results["feeds"].get("ofi_fresh", False) or not results["feeds"].get("comp_fresh", False):
        fixes.append({"action": "restart_feeds", "reason": "stale signals", "details": results["feeds"]})

    payload = {"ts": _now(), "update_type": None, "results": results}
    if fixes:
        payload["update_type"] = "preflight_invariants_fail"
        payload["fixes"] = fixes
    else:
        payload["update_type"] = "preflight_invariants_pass"
    _append_jsonl(LEARNING_UPDATES_LOG, payload)

    return {"results": results, "fixes": fixes}

# ---------------- CLI ----------------
if __name__ == "__main__":
    outcome = run_preflight_invariants()
    print(json.dumps(outcome, indent=2))
