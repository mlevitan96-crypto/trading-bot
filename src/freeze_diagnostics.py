import os
import json
from typing import Dict, Any, List, Optional

LOG_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "logs")

STATE_FILES = [
    "phase82_state.json",
    "phase82_validation_state.json",
    "protective_state.json",
    "futures_protective_state.json",
    "venue_enforcement_state.json",
    "production_health_state.json",
    "phase10x_state.json",
    "phase73_state.json",
    "phase81_state.json",
    "phase101_state.json",
]
def load_json(path: str) -> Optional[Dict[str, Any]]:
    """Load a JSON file safely."""
    try:
        with open(path, "r") as f:
            return json.load(f)
    except Exception:
        return None


def tail_jsonl(path: str, n: int = 200) -> List[Dict[str, Any]]:
    """Load the last N JSONL entries, best effort."""
    full_path = os.path.join(LOG_DIR, path)
    if not os.path.exists(full_path):
        return []

    try:
        with open(full_path, "r") as f:
            lines = f.readlines()[-n:]
    except Exception:
        return []

    out = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except Exception:
            continue
    return out
def extract_indicators(state: Dict[str, Any]) -> Dict[str, Any]:
    """Extract the fields we care about from a phase/overlay state."""
    if not state:
        return {}

    # Some of your state files may nest things; this keeps it shallow and tolerant
    root = state
    if isinstance(state, dict) and "object" in state and isinstance(state["object"], dict):
        root = state["object"]

    return {
        "restart_stage": root.get("restart_stage"),
        "kill_switch": root.get("kill_switch_phase82") or root.get("kill_switch"),
        "protective_mode": root.get("protective_mode"),
        "allowed_symbols": root.get("allowed_symbols"),
        "size_throttle": root.get("size_throttle"),
        "global_block": root.get("global_block"),
        "notes": root.get("notes", []),
        "recommended_actions": root.get("recommended_actions", {}),
        "suspicious_flags": root.get("suspicious_flags", []),
        "raw": root,
    }

def classify_freeze(indicators: Dict[str, Any]) -> Optional[str]:
    """Classify what type of freeze this looks like, or None if not frozen."""
    if not indicators:
        return None

    notes = indicators.get("notes") or []

    # Explicit restart stage
    if indicators.get("restart_stage") == "frozen":
        return "restart_stage_frozen"

    # Hard kill-switch
    if indicators.get("kill_switch"):
        return "phase82_kill_switch"

    # Protective mode on
    if indicators.get("protective_mode"):
        return "protective_mode"

    # No symbols allowed
    if indicators.get("allowed_symbols") == []:
        return "no_symbols_enabled"

    # Zero sizing
    size_throttle = indicators.get("size_throttle")
    if size_throttle is not None and float(size_throttle) == 0.0:
        return "size_throttle_zero"

    # Gates not passed
    if "gates_not_passed" in notes:
        return "gates_not_passed"

    # Global block flag
    if indicators.get("global_block"):
        return "global_block"

    return None
def diagnose_freeze() -> Dict[str, Any]:
    """
    Scan phase/overlay state files and return a single freeze diagnosis object.
    """
    results: Dict[str, Dict[str, Any]] = {}

    # Load all known state files
    for fname in STATE_FILES:
        path = os.path.join(LOG_DIR, fname)
        state = load_json(path)
        indicators = extract_indicators(state) if state else {}
        results[fname] = indicators

    # Find a blocking layer, if any
    for fname, indicators in results.items():
        cause = classify_freeze(indicators)
        if cause:
            rec = indicators.get("recommended_actions", {}) or {}
            safe_to_unfreeze = (
                rec.get("protective_mode") is False
                or rec.get("global_block") is False
                or rec.get("size_throttle") not in (None, 0.0)
            )

            return {
                "is_frozen": True,
                "root_cause": cause,
                "blocking_layer": fname,
                "details": indicators,
                "safe_to_unfreeze": bool(safe_to_unfreeze),
                "recommended_actions": rec,
                "all_layers": results,
            }

    # If no explicit freeze found, treat as not frozen
    return {
        "is_frozen": False,
        "root_cause": None,
        "blocking_layer": None,
        "details": {},
        "safe_to_unfreeze": True,
        "recommended_actions": {},
        "all_layers": results,
    }

def format_summary(diag: Dict[str, Any]) -> str:
    if not diag.get("is_frozen"):
        return "=== FREEZE DIAGNOSTICS ===\n\nState: ACTIVE\nNo blocking freeze conditions detected."

    details = diag.get("details") or {}
    rec = diag.get("recommended_actions") or {}

    lines = []
    lines.append("=== FREEZE DIAGNOSTICS ===")
    lines.append("")
    lines.append(f"State: FROZEN")
    lines.append(f"Root cause: {diag.get('root_cause')}")
    lines.append(f"Blocking layer: {diag.get('blocking_layer')}")
    lines.append("")
    lines.append("Key details:")
    lines.append(f"- restart_stage: {details.get('restart_stage')}")
    lines.append(f"- kill_switch: {details.get('kill_switch')}")
    lines.append(f"- protective_mode: {details.get('protective_mode')}")
    lines.append(f"- size_throttle: {details.get('size_throttle')}")
    lines.append(f"- allowed_symbols: {details.get('allowed_symbols')}")
    lines.append(f"- notes: {details.get('notes')}")
    lines.append(f"- suspicious_flags: {details.get('suspicious_flags')}")
    lines.append("")
    lines.append(f"Safe to unfreeze (per overlay recommendations): {diag.get('safe_to_unfreeze')}")
    lines.append("")
    lines.append("Recommended actions (from overlay, if present):")
    lines.append(json.dumps(rec, indent=2) or "  (none)")

    return "\n".join(lines)


def main():
    diag = diagnose_freeze()
    print(format_summary(diag))


if __name__ == "__main__":
    main()
