# === Full Audit + Fix + Runtime Guard + Scheduler Hook (src/pipeline_self_heal.py) ===
# Purpose:
# - Crawl src/ and logs/ to detect unknown files/modules and stale/corrupt data
# - Trace and auto-fix module file references to canonical paths
# - Quarantine dead/duplicate files and block runtime access
# - Learn canonical mappings in configs/DATA_PIPELINE_MAP.json
# - Enforce canonical directories (no new folders), run before enrichment nightly

import os, time, json, ast, shutil

# Canonical governance
SRC_DIR = "src"
LOG_DIR = "logs"
CFG_DIR = "configs"
QUARANTINE_DIR = os.path.join(LOG_DIR, "quarantine")
AUDIT_LOG = os.path.join(LOG_DIR, "full_pipeline_audit.jsonl")
PIPELINE_MAP = os.path.join(CFG_DIR, "DATA_PIPELINE_MAP.json")

# Canonical files
CANONICAL_FILES = {
    "runtime": "live_config.json",
    "policies": os.path.join(CFG_DIR, "configs/signal_policies.json"),
    "enriched_exec": os.path.join(LOG_DIR, "logs/enriched_decisions.jsonl"),
    "enriched_block": os.path.join(LOG_DIR, "logs/enriched_blocked_signals.jsonl"),
    "tuner_log": os.path.join(LOG_DIR, "logs/scenario_slicer_auto_tuner_v2.jsonl"),
    "governor_log": os.path.join(LOG_DIR, "logs/profit_first_governor.jsonl"),
    "validation_log": os.path.join(LOG_DIR, "logs/validation_suite_patch.jsonl"),
    "executed_trades": os.path.join(LOG_DIR, "logs/executed_trades.jsonl"),
    "strategy_signals": os.path.join(LOG_DIR, "logs/strategy_signals.jsonl"),
}

# Deprecated → Canonical remaps
DEPRECATED_MAP = {
    "logs/enriched_blocked_signals.jsonl": CANONICAL_FILES["enriched_block"],
    "logs/scenario_slicer_auto_tuner_v2.jsonl": CANONICAL_FILES["tuner_log"],
    "logs/profit_first_governor.jsonl": CANONICAL_FILES["governor_log"],
}

# Allowed top-level directories
ALLOWED_DIRS = {SRC_DIR, LOG_DIR, CFG_DIR, "review_kit", ".git", "attached_assets", "__pycache__"}

def _now() -> int:
    return int(time.time())

def _append_jsonl(path: str, row: dict):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "a") as f:
        f.write(json.dumps(row) + "\n")

# ----------- Crawl & Discovery -----------

def crawl_files():
    found = set()
    for root, _, files in os.walk(SRC_DIR):
        for f in files:
            if f.endswith(".py"):
                found.add(os.path.join(root, f))
    for root, _, files in os.walk(LOG_DIR):
        for f in files:
            if f.endswith(".json") or f.endswith(".jsonl"):
                found.add(os.path.join(root, f))
    for root, _, files in os.walk(CFG_DIR):
        for f in files:
            if f.endswith(".json"):
                found.add(os.path.join(root, f))
    return found

def enforce_directories():
    # Prevent creation of unexpected top-level dirs
    top_level = {d for d in os.listdir(".") if os.path.isdir(d)}
    unexpected = [d for d in top_level if d not in ALLOWED_DIRS and not d.startswith(".")]
    actions = []
    for d in unexpected:
        dest = os.path.join(QUARANTINE_DIR, f"dir_{os.path.basename(d)}_{_now()}")
        os.makedirs(QUARANTINE_DIR, exist_ok=True)
        try:
            shutil.move(d, dest)
            actions.append({"ts": _now(), "type": "DIR_QUARANTINED", "dir": d, "dest": dest})
        except Exception as e:
            actions.append({"ts": _now(), "type": "DIR_QUARANTINE_FAILED", "dir": d, "error": str(e)})
    for a in actions:
        _append_jsonl(AUDIT_LOG, a)
    return actions

# ----------- Schema & Freshness -----------

def check_file_health(path: str, max_age_hours: float = 24.0):
    if not os.path.exists(path):
        return {"file": path, "status": "MISSING"}

    mtime = os.path.getmtime(path)
    age_hours = (time.time() - mtime) / 3600.0
    if age_hours > max_age_hours:
        status = {"file": path, "status": f"STALE ({age_hours:.1f}h)"}
    else:
        status = {"file": path, "status": "OK"}

    # Light schema checks
    try:
        if path.endswith(".jsonl"):
            with open(path, "r") as f:
                line_count = 0
                for i, line in enumerate(f):
                    line = line.strip()
                    if not line:
                        continue
                    rec = json.loads(line)
                    line_count += 1
                    # For enriched decisions: expect minimal keys
                    if path == CANONICAL_FILES["enriched_exec"]:
                        if "symbol" not in rec:
                            return {"file": path, "status": "BAD_SCHEMA", "line": i, "reason": "missing symbol"}
                    if i > 20:
                        break
                status["line_count_sample"] = line_count
        elif path.endswith(".json"):
            with open(path, "r") as f:
                obj = json.load(f)
            if not isinstance(obj, dict):
                return {"file": path, "status": "BAD_SCHEMA", "reason": "not a dict"}
    except Exception as e:
        return {"file": path, "status": "CORRUPT", "error": str(e)}

    return status

# ----------- Import Tracing & Auto-Fix -----------

def trace_file_literals(pyfile: str):
    refs = []
    try:
        with open(pyfile, "r") as f:
            tree = ast.parse(f.read(), filename=pyfile)
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                if node.value.endswith(".json") or node.value.endswith(".jsonl"):
                    refs.append(node.value)
    except Exception:
        pass
    return refs

def fix_module_paths(pyfile: str):
    changed = False
    try:
        with open(pyfile, "r") as f:
            content = f.read()
        
        original = content
        
        # Fix deprecated paths
        for dead, canon in DEPRECATED_MAP.items():
            if dead in content:
                content = content.replace(f'"{dead}"', f'"{canon}"')
                content = content.replace(f"'{dead}'", f"'{canon}'")
                changed = True
        
        # Enforce canonical directories for any accidental paths
        for ref in set(trace_file_literals(pyfile)):
            # Normalize: if path references non-canonical location of canonical file, redirect
            basename = os.path.basename(ref)
            if basename in DEPRECATED_MAP:
                content = content.replace(f'"{ref}"', f'"{DEPRECATED_MAP[basename]}"')
                content = content.replace(f"'{ref}'", f"'{DEPRECATED_MAP[basename]}'")
                changed = True
            # If referencing a canonical filename but wrong folder, rewrite to canonical folder
            for key, canonical in CANONICAL_FILES.items():
                if os.path.basename(canonical) == basename and ref != canonical:
                    content = content.replace(f'"{ref}"', f'"{canonical}"')
                    content = content.replace(f"'{ref}'", f"'{canonical}'")
                    changed = True
        
        if changed and content != original:
            with open(pyfile, "w") as f:
                f.write(content)
    except Exception as e:
        _append_jsonl(AUDIT_LOG, {"ts": _now(), "type": "FIX_MODULE_PATHS_FAILED", "module": pyfile, "error": str(e)})
    return changed

# ----------- Quarantine -----------

def quarantine_file(path: str):
    os.makedirs(QUARANTINE_DIR, exist_ok=True)
    basename = os.path.basename(path)
    dest = os.path.join(QUARANTINE_DIR, f"{basename}.{_now()}")
    try:
        shutil.move(path, dest)
        _append_jsonl(AUDIT_LOG, {"ts": _now(), "type": "FILE_QUARANTINED", "file": path, "dest": dest})
        return dest
    except Exception as e:
        _append_jsonl(AUDIT_LOG, {"ts": _now(), "type": "FILE_QUARANTINE_FAILED", "file": path, "error": str(e)})
        return None

def quarantine_unexpected_files(all_files: set):
    # Build expected set (canonical files + known logs)
    expected = set(CANONICAL_FILES.values())
    expected.add(AUDIT_LOG)
    expected.add(PIPELINE_MAP)
    
    # Add known system files that should not be quarantined
    known_logs = {
        "logs/trade_log.jsonl",
        "logs/trades_futures.json",
        "logs/trades_futures_backup.json",
        "logs/strategy_signals.jsonl",
        "logs/executed_trades.jsonl",
        "logs/enriched_decisions.jsonl",
        "logs/enriched_blocked_signals.jsonl",
    }
    expected.update(known_logs)
    
    quarantined = []
    for f in all_files:
        if f.endswith(".py"):
            continue
        # Skip snapshots and quarantine folders
        if "/snapshots/" in f or f.startswith(QUARANTINE_DIR) or "/quarantine/" in f:
            continue
        # Skip review_kit
        if "/review_kit/" in f:
            continue
        
        base = os.path.basename(f)
        # Only quarantine deprecated files explicitly
        if base in DEPRECATED_MAP and f != DEPRECATED_MAP[base]:
            dest = quarantine_file(f)
            if dest:
                quarantined.append((f, dest))
    return quarantined

# ----------- Runtime Guard -----------

def safe_open(path: str, mode: str = "r", *, block_quarantined: bool = True):
    # Block access to quarantined files
    if block_quarantined and os.path.exists(QUARANTINE_DIR):
        if path.startswith(QUARANTINE_DIR) or "/quarantine/" in path:
            _append_jsonl(AUDIT_LOG, {"ts": _now(), "type": "ACCESS_BLOCKED", "file": path})
            raise RuntimeError(f"Access blocked: {path} is quarantined")
    return open(path, mode)

# ----------- Learning Map -----------

def update_pipeline_map(fixes: list):
    os.makedirs(CFG_DIR, exist_ok=True)
    # Record canonical references and last success timestamp
    record = {
        "ts": _now(),
        "canonical": CANONICAL_FILES,
        "deprecated_map": DEPRECATED_MAP,
        "fixes": fixes,
        "last_self_heal": _now(),
    }
    with open(PIPELINE_MAP, "w") as f:
        json.dump(record, f, indent=2)

# ----------- Self-Heal Orchestration -----------

def run_self_heal(max_age_hours: float = 24.0):
    os.makedirs(LOG_DIR, exist_ok=True)
    os.makedirs(CFG_DIR, exist_ok=True)
    actions = []

    # Enforce allowed directories
    dir_actions = enforce_directories()
    actions.extend(dir_actions)

    # Crawl current files
    all_files = crawl_files()

    # Health checks for canonical files
    for name, path in CANONICAL_FILES.items():
        status = check_file_health(path, max_age_hours=max_age_hours)
        _append_jsonl(AUDIT_LOG, {"ts": _now(), "type": "HEALTH_CHECK", "name": name, **status})

    # Trace imports and auto-fix references
    fixes = []
    for f in sorted(all_files):
        if f.endswith(".py"):
            before_refs = trace_file_literals(f)
            fixed = fix_module_paths(f)
            after_refs = trace_file_literals(f)
            if fixed:
                entry = {"ts": _now(), "type": "MODULE_PATHS_FIXED", "module": f, "before": before_refs, "after": after_refs}
                _append_jsonl(AUDIT_LOG, entry)
                fixes.append(entry)

    # Quarantine deprecated files found anywhere
    quarantined = quarantine_unexpected_files(all_files)
    for orig, dest in quarantined:
        _append_jsonl(AUDIT_LOG, {"ts": _now(), "type": "UNEXPECTED_QUARANTINED", "file": orig, "dest": dest})

    # Update learning map
    update_pipeline_map(fixes)

    # Summary
    summary = {
        "ts": _now(),
        "type": "SELF_HEAL_SUMMARY",
        "fixed_modules": len(fixes),
        "quarantined_files": len(quarantined),
        "directory_actions": len(dir_actions),
    }
    _append_jsonl(AUDIT_LOG, summary)
    return summary

# ----------- Scheduler Hook -----------

def nightly_pre_enrichment_self_heal():
    """
    Call this at the start of your nightly scheduler, BEFORE enrichment:
    - Ensures canonical paths and directories
    - Blocks shadow files
    - Auto-fixes module references
    """
    summary = run_self_heal(max_age_hours=24.0)
    print(f"🔧 [SELF-HEAL] fixed_modules={summary['fixed_modules']} quarantined_files={summary['quarantined_files']} dir_actions={summary['directory_actions']}")
    return summary

# Example usage in your scheduler:
# from src.pipeline_self_heal import nightly_pre_enrichment_self_heal, safe_open
# nightly_pre_enrichment_self_heal()
# ... then run enrichment, auto-tuner v2, digest, governor ...
# Ensure modules use safe_open(path) instead of open(path) for guarded access.
