#!/usr/bin/env python3
"""
src/io_safe.py
Runtime-safe I/O helpers: safe_open, AccessBlocked, and pipeline map loader.
Use safe_open() for all runtime state reads/writes to enforce canonical registry.
"""
import os, json
from fcntl import flock, LOCK_EX

CANONICAL_MAP_PATH = "configs/DATA_PIPELINE_MAP.json"

class AccessBlocked(Exception):
    pass

def load_pipeline_map():
    try:
        with open(CANONICAL_MAP_PATH, "r") as f:
            return json.load(f)
    except Exception:
        return {}

def _collect_paths(obj, out):
    if isinstance(obj, dict):
        for v in obj.values():
            _collect_paths(v, out)
    elif isinstance(obj, list):
        for v in obj:
            _collect_paths(v, out)
    elif isinstance(obj, str):
        out.add(os.path.normpath(obj))

def allowed_paths_set():
    pm = load_pipeline_map()
    allowed = set()
    _collect_paths(pm, allowed)
    # Always allow logs, configs, feature_store, quarantine, and reports
    allowed.update({
        os.path.normpath("logs"),
        os.path.normpath("configs"),
        os.path.normpath("feature_store"),
        os.path.normpath("quarantine"),
        os.path.normpath("reports")
    })
    return allowed

def is_allowed(path):
    path = os.path.normpath(path)
    allowed = allowed_paths_set()
    for a in allowed:
        if path == a or path.startswith(a + os.sep):
            return True
    return False

def safe_open(path, mode="r"):
    path = os.path.normpath(path)
    if not is_allowed(path):
        raise AccessBlocked(f"ACCESS_BLOCKED {path}")
    if any(m in mode for m in ("w", "a", "x")):
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        f = open(path, mode)
        try:
            flock(f, LOCK_EX)
        except Exception:
            pass
        return f
    else:
        return open(path, mode)
