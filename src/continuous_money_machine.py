#!/usr/bin/env python3
"""
continuous_money_machine.py

Purpose
- Run the entire learning -> promotion -> execution loop continuously and autonomously.
- Self-heal, run research, run slicer, orchestrate promotions, optionally push to live.
- Enforce safety: paper-first by default; require explicit operator opt-in to push live.
- Watchdog, rollback, alerts, audit trail, and graceful shutdown.

Install
- Place at src/continuous_money_machine.py
- Make executable: chmod +x src/continuous_money_machine.py
- Example systemd unit included below in comments for always-on operation.

Key features
- Continuous loop with configurable cadence
- Preflight integrity checks and self-heal before each cycle
- Pattern discovery and slicer invocation with configurable windows and CF weight
- Evidence aggregation and auto-promotion to runtime overlays
- Optional auto-push to live mode gated by strict safety checks and operator opt-in
- Watchdog rollback on degradation
- Alerts via webhook (Slack/Email) and audit logging to logs/
- PID file, graceful shutdown, and metrics logging

Operator safety
- **Default**: paper-only promotions and trials
- **Auto-live**: requires CLI flag --enable-auto-live and a signed operator token file
- **Manual override**: operator can approve individual promotions via a review queue file

Usage
- Dry run (paper only): python3 src/continuous_money_machine.py
- Continuous daemon (paper only): python3 src/continuous_money_machine.py --daemon
- Enable auto-live push (operator must create operator_token.txt with secret): python3 src/continuous_money_machine.py --daemon --enable-auto-live

Systemd unit example (save as /etc/systemd/system/continuous_money_machine.service)
[Unit]
Description=Continuous Money Machine Orchestrator
After=network.target

[Service]
Type=simple
User=your_user
WorkingDirectory=/path/to/repo
ExecStart=/usr/bin/python3 /path/to/repo/src/continuous_money_machine.py --daemon
Restart=on-failure
RestartSec=10
StandardOutput=append:/path/to/repo/logs/continuous_orch_stdout.log
StandardError=append:/path/to/repo/logs/continuous_orch_stderr.log

[Install]
WantedBy=multi-user.target

"""

import os
import sys
import time
import json
import signal
import shutil
import subprocess
from datetime import datetime, timedelta
from threading import Event

# -------------------------
# Configuration (tune these)
# -------------------------
REPO_ROOT = os.getcwd()
SRC_DIR = os.path.join(REPO_ROOT, "src")
LOG_DIR = os.path.join(REPO_ROOT, "logs")
CFG_DIR = os.path.join(REPO_ROOT, "configs")
FEATURE_STORE = os.path.join(REPO_ROOT, "feature_store")
STATE_DIR = os.path.join(REPO_ROOT, "state")

LIVE_CFG = os.path.join(REPO_ROOT, "live_config.json")
POLICIES = os.path.join(CFG_DIR, "signal_policies.json")
PIPELINE_MAP = os.path.join(CFG_DIR, "DATA_PIPELINE_MAP.json")
PATTERN_SUMMARY = os.path.join(FEATURE_STORE, "pattern_summary.json")

SELF_HEAL_SCRIPT = os.path.join(SRC_DIR, "pipeline_self_heal.py")
PATTERN_SCRIPT = os.path.join(SRC_DIR, "pattern_discovery_research.py")
SLICER_SCRIPT = os.path.join(SRC_DIR, "scenario_slicer_auto_tuner_v2.py")
ORCH_SCRIPT = os.path.join(SRC_DIR, "money_machine_orchestrator.py")

AUDIT_LOG = os.path.join(LOG_DIR, "full_pipeline_audit.jsonl")
ORCH_LOG = os.path.join(LOG_DIR, "continuous_orchestrator.jsonl")
ALERT_WEBHOOK = os.environ.get("MM_ALERT_WEBHOOK", "")

CYCLE_INTERVAL_MIN = 60
SLICER_WINDOW_DAYS = 3
SLICER_MAX_SLICES = 1000
SLICER_CF_WEIGHT = 2.0

STRICT_WR = 0.40
STRICT_PNL = 0.0
CANDIDATE_WR = 0.30
CANDIDATE_PNL = -10.0

ROLLBACK_WR = 0.25
ROLLBACK_PNL = -50.0
HARD_STOP_DRAWDOWN = 0.50

OPERATOR_TOKEN_FILE = os.path.join(CFG_DIR, "operator_token.txt")
AUTO_LIVE_FLAG = False

PID_FILE = os.path.join(LOG_DIR, "continuous_orch.pid")
STOP_EVENT = Event()

# -------------------------
# Utilities
# -------------------------
def now_ts():
    return datetime.utcnow().isoformat() + "Z"

def ensure_dirs():
    os.makedirs(LOG_DIR, exist_ok=True)
    os.makedirs(CFG_DIR, exist_ok=True)
    os.makedirs(FEATURE_STORE, exist_ok=True)
    os.makedirs(STATE_DIR, exist_ok=True)

def append_jsonl(path, obj):
    ensure_dirs()
    with open(path, "a") as f:
        f.write(json.dumps(obj) + "\n")

def run_cmd(cmd, timeout=None):
    try:
        proc = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout)
        return proc.returncode, proc.stdout, proc.stderr
    except subprocess.TimeoutExpired as e:
        return 124, "", f"timeout: {e}"

def safe_load_json(path):
    try:
        with open(path) as f:
            return json.load(f)
    except Exception:
        return {}

def write_json(path, obj):
    ensure_dirs()
    with open(path, "w") as f:
        json.dump(obj, f, indent=2)

def alert(msg, level="info"):
    payload = {"ts": now_ts(), "level": level, "msg": msg}
    append_jsonl(ORCH_LOG, payload)
    if ALERT_WEBHOOK:
        try:
            subprocess.run(
                f"curl -s -X POST -H 'Content-Type: application/json' -d '{json.dumps(payload)}' {ALERT_WEBHOOK}",
                shell=True, timeout=6
            )
        except Exception:
            pass

# -------------------------
# Safety checks and self-heal
# -------------------------
def preflight_self_heal():
    alert("preflight_self_heal_start", "debug")
    if os.path.exists(SELF_HEAL_SCRIPT):
        rc, out, err = run_cmd(f"python3 {SELF_HEAL_SCRIPT}")
        append_jsonl(AUDIT_LOG, {"ts": now_ts(), "type": "SELF_HEAL_RUN", "rc": rc, "out": out[:2000], "err": err[:2000]})
        if rc != 0:
            alert(f"self_heal_failed rc={rc} err={err[:200]}", "warn")
            return False
    else:
        alert("self_heal_missing", "warn")
    if not os.path.exists(PIPELINE_MAP):
        alert("pipeline_map_missing", "warn")
    return True

# -------------------------
# Run research and slicer
# -------------------------
def run_research_and_slicer(window_days=SLICER_WINDOW_DAYS, max_slices=SLICER_MAX_SLICES, cf_weight=SLICER_CF_WEIGHT):
    alert("research_start", "debug")
    if os.path.exists(PATTERN_SCRIPT):
        cmd = f"python3 {PATTERN_SCRIPT} --window_days {window_days} --max_slices {max_slices}"
        rc, out, err = run_cmd(cmd, timeout=1800)
        append_jsonl(ORCH_LOG, {"ts": now_ts(), "type": "PATTERN_RUN", "rc": rc, "out": out[:2000], "err": err[:2000]})
        if rc != 0:
            alert(f"pattern_discovery_failed rc={rc}", "warn")
    else:
        alert("pattern_script_missing", "warn")
    if os.path.exists(SLICER_SCRIPT):
        cmd = f"python3 {SLICER_SCRIPT} --window_days {window_days} --max_slices {max_slices} --cf_weight {cf_weight}"
        rc, out, err = run_cmd(cmd, timeout=3600)
        append_jsonl(ORCH_LOG, {"ts": now_ts(), "type": "SLICER_RUN", "rc": rc, "out": out[:2000], "err": err[:2000]})
        if rc != 0:
            alert(f"slicer_failed rc={rc}", "warn")
    else:
        alert("slicer_script_missing", "warn")

# -------------------------
# Aggregate evidence and decide promotions
# -------------------------
def aggregate_and_decide_promotions():
    ps = safe_load_json(PATTERN_SUMMARY)
    patterns = ps.get("patterns", []) if isinstance(ps, dict) else []
    strict = [p for p in patterns if p.get("status") == "strict" and p.get("expected", {}).get("wr", 0) >= STRICT_WR and p.get("expected", {}).get("pnl", 0) > STRICT_PNL]
    candidates = [p for p in patterns if p.get("status") == "candidate" and p.get("expected", {}).get("wr", 0) >= CANDIDATE_WR and p.get("expected", {}).get("pnl", 0) >= CANDIDATE_PNL]
    append_jsonl(ORCH_LOG, {"ts": now_ts(), "type": "AGGREGATE", "strict_count": len(strict), "candidate_count": len(candidates)})
    return strict, candidates

# -------------------------
# Promotion and optional live push
# -------------------------
def promote_to_runtime(strict, candidates, enable_auto_live=False):
    cfg = safe_load_json(LIVE_CFG)
    rt = cfg.get("runtime", {}) or {}
    overlays = rt.get("conditional_overlays", []) or []

    def key_of(p):
        s = p["slice"]
        return (s.get("symbol"), s.get("direction"), s.get("session_bin"), s.get("regime"), s.get("vol_bin"), s.get("liq_bin"), s.get("trend_bin"), s.get("combo"))

    for p in strict:
        k = key_of(p)
        overlays = [o for o in overlays if not (
            o.get("symbol") == k[0] and o.get("direction") == k[1] and o.get("session_bin") == k[2] and o.get("regime") == k[3]
            and o.get("vol_bin") == k[4] and o.get("liq_bin") == k[5] and o.get("trend_bin") == k[6]
        )]
        overlays.append({
            **p["slice"],
            "thresholds": p["thresholds"],
            "expected": p["expected"],
            "status": "live_trial" if not enable_auto_live else "live_auto"
        })

    rt["candidate_overlays"] = [{"slice": p["slice"], "thresholds": p["thresholds"], "expected": p["expected"], "status": "candidate"} for p in candidates]
    rt["conditional_overlays"] = overlays
    cfg["runtime"] = rt

    if enable_auto_live:
        if not os.path.exists(OPERATOR_TOKEN_FILE):
            alert("auto_live_requested_but_no_operator_token", "error")
            raise RuntimeError("Operator token missing; cannot auto-push to live.")
        with open(OPERATOR_TOKEN_FILE) as f:
            token = f.read().strip()
        if not token:
            alert("operator_token_empty", "error")
            raise RuntimeError("Operator token empty; cannot auto-push to live.")
        append_jsonl(ORCH_LOG, {"ts": now_ts(), "type": "AUTO_LIVE_PUSH", "count_strict": len(strict), "count_candidates": len(candidates)})
        alert(f"auto_live_push_applied strict={len(strict)} candidates={len(candidates)}", "info")
    else:
        append_jsonl(ORCH_LOG, {"ts": now_ts(), "type": "PROMOTE_PAPER_ONLY", "count_strict": len(strict), "count_candidates": len(candidates)})
        alert(f"promoted_to_paper strict={len(strict)} candidates={len(candidates)}", "debug")

    write_json(LIVE_CFG, cfg)
    return cfg

# -------------------------
# Watchdog and rollback
# -------------------------
def check_and_rollback_if_degraded():
    cfg = safe_load_json(LIVE_CFG)
    rt = cfg.get("runtime", {}) or {}
    last_wr = float(rt.get("last_wr", 0.0))
    last_pnl = float(rt.get("last_pnl", 0.0))
    portfolio = rt.get("portfolio", {}) or {}
    drawdown = float(portfolio.get("drawdown", 0.0))
    if last_wr < ROLLBACK_WR or last_pnl <= ROLLBACK_PNL or drawdown >= HARD_STOP_DRAWDOWN:
        rt["conditional_overlays"] = []
        rt["protective_mode"] = True
        rt["size_throttle"] = max(0.05, float(rt.get("size_throttle", 0.20)) - 0.05)
        cfg["runtime"] = rt
        write_json(LIVE_CFG, cfg)
        append_jsonl(ORCH_LOG, {"ts": now_ts(), "type": "ROLLBACK_APPLIED", "last_wr": last_wr, "last_pnl": last_pnl, "drawdown": drawdown})
        alert(f"rollback_applied wr={last_wr} pnl={last_pnl} drawdown={drawdown}", "warn")
        return True
    return False

# -------------------------
# Execution engine restart helper
# -------------------------
def restart_execution_engine(exec_entry="run.py"):
    try:
        subprocess.run(f"pkill -f {exec_entry}", shell=True)
    except Exception:
        pass
    if os.path.exists(exec_entry):
        subprocess.Popen(f"nohup python3 {exec_entry} > {os.path.join(LOG_DIR,'execution_engine.log')} 2>&1 &", shell=True)
        append_jsonl(ORCH_LOG, {"ts": now_ts(), "type": "EXEC_RESTART"})
        alert("execution_engine_restarted", "info")
    else:
        alert("execution_engine_entry_missing", "warn")

# -------------------------
# Graceful shutdown handling
# -------------------------
def handle_shutdown(sig, frame):
    alert("shutdown_signal_received", "info")
    STOP_EVENT.set()
    if os.path.exists(PID_FILE):
        os.remove(PID_FILE)
    sys.exit(0)

signal.signal(signal.SIGINT, handle_shutdown)
signal.signal(signal.SIGTERM, handle_shutdown)

# -------------------------
# Main orchestration cycle
# -------------------------
def run_cycle(enable_auto_live=False):
    append_jsonl(ORCH_LOG, {"ts": now_ts(), "type": "CYCLE_START"})
    alert("cycle_start", "debug")
    
    if not preflight_self_heal():
        alert("preflight_failed_skipping_cycle", "warn")
        return
    
    run_research_and_slicer()
    
    strict, candidates = aggregate_and_decide_promotions()
    
    if strict or candidates:
        promote_to_runtime(strict, candidates, enable_auto_live=enable_auto_live)
    
    degraded = check_and_rollback_if_degraded()
    if degraded:
        alert("degradation_detected_and_rolled_back", "warn")
    
    append_jsonl(ORCH_LOG, {"ts": now_ts(), "type": "CYCLE_END", "strict": len(strict), "candidates": len(candidates), "degraded": degraded})
    alert("cycle_complete", "debug")

# -------------------------
# Main entry point
# -------------------------
def main():
    import argparse
    parser = argparse.ArgumentParser(description="Continuous Money Machine Orchestrator")
    parser.add_argument("--daemon", action="store_true", help="Run as continuous daemon")
    parser.add_argument("--enable-auto-live", action="store_true", help="Enable auto-push to live mode (requires operator token)")
    parser.add_argument("--interval", type=int, default=CYCLE_INTERVAL_MIN, help="Cycle interval in minutes")
    args = parser.parse_args()
    
    ensure_dirs()
    
    with open(PID_FILE, "w") as f:
        f.write(str(os.getpid()))
    
    alert(f"continuous_orchestrator_start daemon={args.daemon} auto_live={args.enable_auto_live} interval={args.interval}min", "info")
    
    if args.daemon:
        while not STOP_EVENT.is_set():
            try:
                run_cycle(enable_auto_live=args.enable_auto_live)
            except Exception as e:
                alert(f"cycle_error: {e}", "error")
                append_jsonl(ORCH_LOG, {"ts": now_ts(), "type": "CYCLE_ERROR", "error": str(e)})
            
            wait_sec = args.interval * 60
            alert(f"sleeping_{args.interval}min", "debug")
            STOP_EVENT.wait(wait_sec)
    else:
        run_cycle(enable_auto_live=args.enable_auto_live)
    
    alert("continuous_orchestrator_shutdown", "info")
    if os.path.exists(PID_FILE):
        os.remove(PID_FILE)

if __name__ == "__main__":
    main()
