#!/usr/bin/env python3
import json, time, os
LOG="logs/blocked_signals.jsonl"
os.makedirs(os.path.dirname(LOG), exist_ok=True)
def log_blocked(decision, reason="blocked"):
    try:
        entry = {"ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "reason": reason, "decision": decision}
        with open(LOG, "a") as f:
            f.write(json.dumps(entry) + "\n")
    except Exception:
        pass
