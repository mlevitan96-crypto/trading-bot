import os, json, time

LIVE_CFG = "live_config.json"
OVERRIDE_LOG = "logs/override_audit.jsonl"

def _read_live_cfg():
    if not os.path.exists(LIVE_CFG): return {}
    try:
        return json.load(open(LIVE_CFG))
    except Exception:
        return {}

def _bus(event_type, data):
    try:
        from full_integration_blofin_micro_live_and_paper import _bus as integration_bus
        integration_bus(event_type, data)
    except Exception:
        pass

def audit_overrides():
    cfg = _read_live_cfg()
    rt = cfg.get("runtime", {}) or {}
    overrides = {
        "manual_override": bool(rt.get("manual_override", False)),
        "force_unfreeze": bool(rt.get("force_unfreeze", False)),
        "kill_switch_phase82": bool(rt.get("kill_switch_phase82", False)),
        "protective_mode": bool(rt.get("protective_mode", False)),
    }

    active = [k for k,v in overrides.items() if v]
    conflicts = []
    if overrides["kill_switch_phase82"] and overrides["force_unfreeze"]:
        conflicts.append("kill_switch_vs_force_unfreeze")

    record = {
        "ts": int(time.time()),
        "active_overrides": active,
        "conflicts": conflicts,
        "protective_mode": overrides["protective_mode"],
        "kill_switch": overrides["kill_switch_phase82"],
    }

    _bus("override_audit", record)
    os.makedirs("logs", exist_ok=True)
    with open(OVERRIDE_LOG,"a") as f: f.write(json.dumps(record)+"\n")

    return record

def expire_overrides():
    cfg = _read_live_cfg()
    rt = cfg.get("runtime", {}) or {}
    changed = False
    expired = []

    if rt.get("manual_override", False):
        rt["manual_override"] = False
        changed = True
        expired.append("manual_override")

    if rt.get("force_unfreeze", False):
        rt["force_unfreeze"] = False
        changed = True
        expired.append("force_unfreeze")

    if changed:
        cfg["runtime"] = rt
        with open(LIVE_CFG,"w") as f: json.dump(cfg,f,indent=2)
        _bus("override_expired", {"ts":int(time.time()), "expired": expired, "runtime": rt})
        print(f"🔄 [OVERRIDE-EXPIRED] Cleared: {expired}")

    return expired

def run_override_audit_cycle():
    record = audit_overrides()
    if record["active_overrides"]:
        print(f"⚠️ [OVERRIDE-AUDIT] Active: {record['active_overrides']} | Conflicts: {record['conflicts']}")
    else:
        print("✅ [OVERRIDE-AUDIT] No overrides active")
    
    utc_h = int(time.gmtime().tm_hour)
    if utc_h == 7:
        expire_overrides()
    
    return record
