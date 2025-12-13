#!/usr/bin/env python3
"""
src/self_heal_auto.py
Automated self-heal module:
- Scans repo for data file references
- Builds/updates configs/DATA_PIPELINE_MAP.json with canonical mappings
- Quarantines truly one-off files (moves to quarantine/)
- Rewrites common open() calls in critical modules to safe_open() where safe
- Emits audit events to logs/full_pipeline_audit.jsonl
Designed to run automatically at startup and on-demand.
"""
import os, re, json, shutil, time
from pathlib import Path

REPO = Path.cwd()
PIPELINE_MAP = REPO / "configs" / "DATA_PIPELINE_MAP.json"
QUARANTINE_DIR = REPO / "quarantine"
AUDIT_LOG = REPO / "logs" / "full_pipeline_audit.jsonl"
SEARCH_PATHS = ["src", "configs", "tools", "feature_store", "logs"]
FILE_PAT = re.compile(r'([A-Za-z0-9_\-\/\.]+?\.(jsonl|json|csv|parquet|db|sqlite|pkl))')

def ts():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

def audit_event(obj):
    obj['ts'] = ts()
    os.makedirs(AUDIT_LOG.parent, exist_ok=True)
    with open(AUDIT_LOG, "a") as f:
        f.write(json.dumps(obj) + "\n")

def load_map():
    if PIPELINE_MAP.exists():
        try:
            return json.load(open(PIPELINE_MAP))
        except Exception:
            return {}
    return {}

def save_map(m):
    os.makedirs(PIPELINE_MAP.parent, exist_ok=True)
    tmp = PIPELINE_MAP.with_suffix(".tmp")
    with open(tmp, "w") as f:
        json.dump(m, f, indent=2)
    tmp.replace(PIPELINE_MAP)
    audit_event({"type":"PIPELINE_MAP_UPDATED","details":"auto-update"})

def find_file_like_strings():
    found = set()
    for p in SEARCH_PATHS:
        for root, _, files in os.walk(p):
            for fn in files:
                fp = Path(root) / fn
                try:
                    txt = fp.read_text(errors="ignore")
                except Exception:
                    continue
                for m in FILE_PAT.findall(txt):
                    found.add(m[0])
    return sorted(found)

def repo_data_files():
    files = []
    for root, _, fns in os.walk("."):
        for fn in fns:
            if fn.endswith((".jsonl",".json",".csv",".parquet",".db",".sqlite",".pkl")):
                files.append(os.path.normpath(os.path.join(root, fn)))
    return sorted(files)

def ensure_canonical_map():
    pm = load_map()
    changed = False
    # flatten existing values to set
    existing = set()
    def collect(o):
        if isinstance(o, dict):
            for v in o.values(): collect(v)
        elif isinstance(o, list):
            for v in o: collect(v)
        elif isinstance(o, str):
            existing.add(os.path.normpath(o))
    collect(pm)
    # find all data files in repo
    data_files = repo_data_files()
    for f in data_files:
        nf = os.path.normpath(f)
        if nf not in existing:
            # add to map under auto_generated namespace
            pm.setdefault("auto_generated", {})
            key = os.path.basename(nf)
            # avoid collisions
            idx = 1
            base_key = key
            while key in pm["auto_generated"]:
                key = f"{base_key}_{idx}"
                idx += 1
            pm["auto_generated"][key] = nf
            existing.add(nf)
            changed = True
            audit_event({"type":"PIPELINE_MAP_ADDED","file":nf,"key":f"auto_generated.{key}"})
    if changed:
        save_map(pm)
    return pm

def quarantine_unmapped_files(pm):
    # any file referenced in code but not present in map -> if exists on disk, add; else log missing
    found_strings = find_file_like_strings()
    mapped = set()
    def collect(o):
        if isinstance(o, dict):
            for v in o.values(): collect(v)
        elif isinstance(o, list):
            for v in o: collect(v)
        elif isinstance(o, str):
            mapped.add(os.path.normpath(o))
    collect(pm)
    os.makedirs(QUARANTINE_DIR, exist_ok=True)
    for s in found_strings:
        s_norm = os.path.normpath(s)
        # if file exists in repo but not mapped, add to map
        if os.path.exists(s_norm) and s_norm not in mapped:
            # add to auto_generated
            pm.setdefault("auto_generated", {})
            key = os.path.basename(s_norm)
            idx = 1
            base_key = key
            while key in pm["auto_generated"]:
                key = f"{base_key}_{idx}"
                idx += 1
            pm["auto_generated"][key] = s_norm
            audit_event({"type":"PIPELINE_MAP_ADDED_FROM_REF","file":s_norm,"key":f"auto_generated.{key}"})
            mapped.add(s_norm)
        elif not os.path.exists(s_norm):
            audit_event({"type":"MISSING_FILE_REFERENCE","ref":s_norm})
    # move truly one-off files (not in map) into quarantine to avoid accidental use
    all_mapped = mapped
    for f in repo_data_files():
        if os.path.normpath(f) not in all_mapped:
            dest = QUARANTINE_DIR / f.lstrip("./")
            dest.parent.mkdir(parents=True, exist_ok=True)
            try:
                shutil.move(f, dest)
                audit_event({"type":"QUARANTINED","file":f,"moved_to":str(dest)})
            except Exception as e:
                audit_event({"type":"QUARANTINE_FAILED","file":f,"error":str(e)})
    save_map(pm)
    return pm

def patch_critical_modules():
    # Replace direct open("logs/positions_futures.json") and similar with safe_open usage
    targets = [
        ("src/position_manager.py", "logs/positions_futures.json"),
        ("src/pnl_dashboard_loader.py", "logs/positions_futures.json"),
        ("src/reconciliation.py", "logs/positions_futures.json")
    ]
    for path, fname in targets:
        p = Path(path)
        if not p.exists():
            continue
        txt = p.read_text()
        changed = False
        if "from src.io_safe import safe_open" not in txt:
            txt = "from src.io_safe import safe_open, AccessBlocked\n" + txt
            changed = True
        # replace common patterns of open("logs/positions_futures.json", "r")
        txt_new = txt.replace(f'open("{fname}"', f'safe_open("{fname}"')
        if txt_new != txt:
            p.write_text(txt_new)
            audit_event({"type":"MODULE_PATCHED","module":path,"note":"replaced open() with safe_open() for positions file"})
    return True

def run():
    audit_event({"type":"SELF_HEAL_START"})
    pm = ensure_canonical_map()
    pm = quarantine_unmapped_files(pm)
    patch_critical_modules()
    audit_event({"type":"SELF_HEAL_COMPLETE"})
    return True

if __name__ == "__main__":
    run()
