# File: futures_shadow_auto_promote.py
# Purpose: Nightly auto-promotion from shadow experiments into live configs:
#   - Ladder exit tiers (configs/ladder_exit_policies.json)
#   - EMA spans per symbol/strategy/regime (configs/signal_policies.json)
#   - Leverage budgets (configs/leverage_budgets.json)
# Includes backups, audit logs, criteria gates, dry-run, and rollback utilities.
#
# Usage:
#   1) Run shadow experiments first (produces logs/shadow_{SYMBOL}.json)
#      python3 src/futures_backtesting_and_shadow.py --shadow --symbol BTCUSDT --data data/BTCUSDT_1m.csv --configs configs/shadow_configs.json
#
#   2) Promote best config if criteria satisfied:
#      python3 futures_shadow_auto_promote.py --promote --symbol BTCUSDT
#
#   3) Dry-run (see what would change without writing):
#      python3 futures_shadow_auto_promote.py --promote --symbol BTCUSDT --dry-run
#
#   4) Rollback last changes for all target config files:
#      python3 futures_shadow_auto_promote.py --rollback-all
#
#   5) Rollback specific file:
#      python3 futures_shadow_auto_promote.py --rollback-file ladder_exit_policies.json

import json
from pathlib import Path
from datetime import datetime
import argparse

LOGS = Path("logs")
CONFIGS = Path("configs")
BACKUPS = CONFIGS / "backups"

# -----------------------------
# IO helpers
# -----------------------------
def load(path: Path, fallback=None):
    try:
        with open(path, "r") as f:
            return json.load(f)
    except:
        return fallback if fallback is not None else {}

def save(path: Path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        json.dump(data, f, indent=2)

def backup(path: Path) -> str:
    ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    dest = BACKUPS / f"{path.name}_{ts}.json"
    save(dest, load(path, {}))
    return dest.name

def latest_backup(name: str) -> Path:
    files = sorted(BACKUPS.glob(f"{name}_*.json"), reverse=True)
    return files[0] if files else None

# -----------------------------
# Criteria gates (configurable)
# -----------------------------
DEFAULT_CRITERIA = {
    "min_events": 10,           # minimum trade/exits/events considered in shadow result
    "min_avg_roi_pct": 0.5,     # minimum average ROI per trade (%)
    "max_dd_pct": 15.0,         # maximum drawdown allowed (%)
    "min_risk_adjusted": 0.0    # min (avg_roi - 0.5*DD) improvement over current baseline
}

def compute_risk_adjusted(avg_roi_pct: float, max_dd_pct: float) -> float:
    return avg_roi_pct - 0.5 * max_dd_pct

# -----------------------------
# Helper: read current baselines
# -----------------------------
def load_ladder_policies():
    return load(CONFIGS / "ladder_exit_policies.json",
                {"defaults": {"tiers_pct": [0.25, 0.25, 0.5]}, "overrides": []})

def load_signal_policies():
    # Per-symbol/strategy/regime EMA config
    # {
    #   "defaults": {"ema_short":12,"ema_long":26},
    #   "overrides":[{"symbol":"BTCUSDT","strategy":"EMA","regime":"trending","ema_short":8,"ema_long":21}]
    # }
    return load(CONFIGS / "configs/signal_policies.json",
                {"defaults": {"ema_short": 12, "ema_long": 26}, "overrides": []})

def load_leverage_budgets():
    # Example structure:
    # {
    #   "defaults": {"max_leverage": 3},
    #   "overrides":[{"symbol":"BTCUSDT","regime":"trending","max_leverage":5}]
    # }
    return load(CONFIGS / "leverage_budgets.json",
                {"defaults": {"max_leverage": 3}, "overrides": []})

# -----------------------------
# Baseline fetch for comparison
# -----------------------------
def current_tiers_for(symbol: str, strategy: str = "EMA", regime: str = "any") -> list:
    pol = load_ladder_policies()
    tiers = pol.get("defaults", {}).get("tiers_pct", [0.25, 0.25, 0.5])
    for ov in pol.get("overrides", []):
        if ov.get("symbol") == symbol and ov.get("strategy", strategy) == strategy and ov.get("regime", regime) == regime:
            tiers = ov.get("tiers_pct", tiers)
            break
    return tiers

def current_ema_for(symbol: str, strategy: str = "EMA", regime: str = "any") -> dict:
    pol = load_signal_policies()
    ema_short = pol.get("defaults", {}).get("ema_short", 12)
    ema_long = pol.get("defaults", {}).get("ema_long", 26)
    for ov in pol.get("overrides", []):
        if ov.get("symbol") == symbol and ov.get("strategy", strategy) == strategy and ov.get("regime", regime) == regime:
            ema_short = ov.get("ema_short", ema_short)
            ema_long = ov.get("ema_long", ema_long)
            break
    return {"ema_short": ema_short, "ema_long": ema_long}

def current_leverage_for(symbol: str, regime: str = "any") -> int:
    lb = load_leverage_budgets()
    lev = lb.get("defaults", {}).get("max_leverage", 3)
    for ov in lb.get("overrides", []):
        if ov.get("symbol") == symbol and ov.get("regime", regime) == regime:
            lev = ov.get("max_leverage", lev)
            break
    return int(lev)

# -----------------------------
# Promotion logic
# -----------------------------
def select_winner(symbol: str) -> dict:
    shadow = load(LOGS / f"shadow_{symbol}.json", {"ranked": []})
    ranked = shadow.get("ranked", [])
    return ranked[0] if ranked else {}

def meets_criteria(winner: dict, criteria: dict) -> (bool, str):
    avg_roi = float(winner.get("avg_roi_pct", 0.0))
    dd = float(winner.get("max_drawdown_pct", 100.0))
    events = int(winner.get("events", 0))  # optional; if not present, fail criteria or set conservative default
    # If events not provided in shadow output, fail safe unless explicitly set
    if events == 0 and "events" not in winner:
        return False, "events_not_provided"

    if events < criteria["min_events"]:
        return False, f"too_few_events:{events}<{criteria['min_events']}"
    if avg_roi < criteria["min_avg_roi_pct"]:
        return False, f"avg_roi_low:{avg_roi}<{criteria['min_avg_roi_pct']}"
    if dd > criteria["max_dd_pct"]:
        return False, f"drawdown_high:{dd}>{criteria['max_dd_pct']}"
    return True, "ok"

def improvement_over_baseline(symbol: str, winner: dict, criteria: dict) -> (bool, float):
    # Baseline proxy from current live config is not directly available; compare risk-adjusted score alone to threshold.
    ras = compute_risk_adjusted(float(winner.get("avg_roi_pct", 0.0)), float(winner.get("max_drawdown_pct", 0.0)))
    return (ras >= criteria["min_risk_adjusted"]), ras

def promote_ladder_tiers(symbol: str, winner: dict, dry_run: bool = False) -> dict:
    tiers = winner.get("tiers_pct")
    if not tiers or not isinstance(tiers, list):
        return {"status": "skipped", "component": "ladder_tiers", "reason": "no_tiers_in_winner"}

    policies = load_ladder_policies()
    backup_name = backup(CONFIGS / "ladder_exit_policies.json") if not dry_run else None

    updated = False
    now = datetime.utcnow().isoformat()
    # Try regime-aware override if present, else generic
    regime = winner.get("regime", "any")
    strategy = winner.get("strategy", "EMA")

    for i, ov in enumerate(policies.get("overrides", [])):
        if ov.get("symbol") == symbol and ov.get("strategy", strategy) == strategy and ov.get("regime", regime) == regime:
            policies["overrides"][i]["tiers_pct"] = tiers
            policies["overrides"][i]["last_promoted_at"] = now
            updated = True
            break
    if not updated:
        policies.setdefault("overrides", []).append({
            "symbol": symbol,
            "strategy": strategy,
            "regime": regime,
            "tiers_pct": tiers,
            "last_promoted_at": now
        })

    if not dry_run:
        save(CONFIGS / "ladder_exit_policies.json", policies)

    return {"status": "promoted" if not dry_run else "dry_run", "component": "ladder_tiers", "backup": backup_name, "new_tiers": tiers}

def promote_signal_ema(symbol: str, winner: dict, dry_run: bool = False) -> dict:
    ema_short = winner.get("ema_short")
    ema_long = winner.get("ema_long")
    if ema_short is None or ema_long is None:
        return {"status": "skipped", "component": "signal_ema", "reason": "no_ema_in_winner"}

    policies = load_signal_policies()
    backup_name = backup(CONFIGS / "configs/signal_policies.json") if not dry_run else None

    updated = False
    now = datetime.utcnow().isoformat()
    regime = winner.get("regime", "any")
    strategy = winner.get("strategy", "EMA")

    for i, ov in enumerate(policies.get("overrides", [])):
        if ov.get("symbol") == symbol and ov.get("strategy", strategy) == strategy and ov.get("regime", regime) == regime:
            policies["overrides"][i]["ema_short"] = int(ema_short)
            policies["overrides"][i]["ema_long"] = int(ema_long)
            policies["overrides"][i]["last_promoted_at"] = now
            updated = True
            break
    if not updated:
        policies.setdefault("overrides", []).append({
            "symbol": symbol,
            "strategy": strategy,
            "regime": regime,
            "ema_short": int(ema_short),
            "ema_long": int(ema_long),
            "last_promoted_at": now
        })

    if not dry_run:
        save(CONFIGS / "configs/signal_policies.json", policies)

    return {"status": "promoted" if not dry_run else "dry_run", "component": "signal_ema", "backup": backup_name, "ema_short": int(ema_short), "ema_long": int(ema_long)}

def promote_leverage_budget(symbol: str, winner: dict, dry_run: bool = False) -> dict:
    lev = winner.get("leverage")
    if lev is None:
        return {"status": "skipped", "component": "leverage_budget", "reason": "no_leverage_in_winner"}

    budgets = load_leverage_budgets()
    backup_name = backup(CONFIGS / "leverage_budgets.json") if not dry_run else None

    updated = False
    now = datetime.utcnow().isoformat()
    regime = winner.get("regime", "any")

    for i, ov in enumerate(budgets.get("overrides", [])):
        if ov.get("symbol") == symbol and ov.get("regime", regime) == regime:
            budgets["overrides"][i]["max_leverage"] = int(lev)
            budgets["overrides"][i]["last_promoted_at"] = now
            updated = True
            break
    if not updated:
        budgets.setdefault("overrides", []).append({
            "symbol": symbol,
            "regime": regime,
            "max_leverage": int(lev),
            "last_promoted_at": now
        })

    if not dry_run:
        save(CONFIGS / "leverage_budgets.json", budgets)

    return {"status": "promoted" if not dry_run else "dry_run", "component": "leverage_budget", "backup": backup_name, "max_leverage": int(lev)}

# -----------------------------
# Audit logging
# -----------------------------
def write_promotion_audit(symbol: str, winner: dict, decisions: list, criteria: dict, ras: float, dry_run: bool):
    audit = load(LOGS / "shadow_promotions.json", {"events": []})
    audit["events"].append({
        "timestamp": datetime.utcnow().isoformat(),
        "symbol": symbol,
        "winner": winner,
        "decisions": decisions,
        "criteria": criteria,
        "risk_adjusted_score": ras,
        "dry_run": dry_run
    })
    save(LOGS / "shadow_promotions.json", audit)

# -----------------------------
# Rollback utilities
# -----------------------------
def rollback_file(name: str) -> dict:
    bk = latest_backup(name)
    if not bk:
        return {"status": "no_backup", "file": name}
    data = load(bk, {})
    save(CONFIGS / name, data)
    return {"status": "rolled_back", "file": name, "backup": bk.name}

def rollback_all() -> dict:
    targets = ["ladder_exit_policies.json", "configs/signal_policies.json", "leverage_budgets.json"]
    res = []
    for t in targets:
        res.append(rollback_file(t))
    return {"status": "done", "results": res}

# -----------------------------
# Orchestrator
# -----------------------------
def promote_all(symbol: str, criteria_overrides: dict = None, dry_run: bool = False) -> dict:
    criteria = DEFAULT_CRITERIA.copy()
    if criteria_overrides:
        criteria.update(criteria_overrides)

    winner = select_winner(symbol)
    if not winner:
        return {"status": "no_winner", "symbol": symbol}

    ok, reason = meets_criteria(winner, criteria)
    if not ok:
        return {"status": "rejected", "symbol": symbol, "reason": reason}

    improved, ras = improvement_over_baseline(symbol, winner, criteria)
    if not improved:
        return {"status": "rejected", "symbol": symbol, "reason": f"risk_adjusted_below_threshold:{ras}<{criteria['min_risk_adjusted']}"}

    decisions = []
    decisions.append(promote_ladder_tiers(symbol, winner, dry_run))
    decisions.append(promote_signal_ema(symbol, winner, dry_run))
    decisions.append(promote_leverage_budget(symbol, winner, dry_run))

    write_promotion_audit(symbol, winner, decisions, criteria, ras, dry_run)

    return {"status": "promoted" if not dry_run else "dry_run", "symbol": symbol, "risk_adjusted_score": ras, "decisions": decisions}

# -----------------------------
# CLI
# -----------------------------
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Auto-promote shadow winners into live configs (tiers, EMA, leverage)")
    parser.add_argument("--promote", action="store_true", help="Promote best shadow config if criteria met")
    parser.add_argument("--symbol", type=str, default="BTCUSDT", help="Symbol to promote (matches shadow_{SYMBOL}.json)")
    parser.add_argument("--dry-run", action="store_true", help="Do not write changes; show decisions only")
    parser.add_argument("--min-events", type=int, help="Override min events criteria")
    parser.add_argument("--min-avg-roi", type=float, help="Override min avg ROI (%%) criteria")
    parser.add_argument("--max-dd", type=float, help="Override max drawdown (%%) criteria")
    parser.add_argument("--min-risk-adj", type=float, help="Override min risk-adjusted score criteria")
    parser.add_argument("--rollback-all", action="store_true", help="Rollback ladder, signal, and leverage configs to latest backups")
    parser.add_argument("--rollback-file", type=str, help="Rollback a single config file by name")
    args = parser.parse_args()

    if args.rollback_all:
        print(json.dumps(rollback_all(), indent=2))
    elif args.rollback_file:
        print(json.dumps(rollback_file(args.rollback_file), indent=2))
    elif args.promote:
        overrides = {}
        if args.min_events is not None: overrides["min_events"] = args.min_events
        if args.min_avg_roi is not None: overrides["min_avg_roi_pct"] = args.min_avg_roi
        if args.max_dd is not None: overrides["max_dd_pct"] = args.max_dd
        if args.min_risk_adj is not None: overrides["min_risk_adjusted"] = args.min_risk_adj
        res = promote_all(args.symbol, overrides, dry_run=args.dry_run)
        print(json.dumps(res, indent=2))
    else:
        print("Usage examples:")
        print("  Promote winner: python3 futures_shadow_auto_promote.py --promote --symbol BTCUSDT")
        print("  Dry-run:        python3 futures_shadow_auto_promote.py --promote --symbol BTCUSDT --dry-run")
        print("  Rollback all:   python3 futures_shadow_auto_promote.py --rollback-all")
        print("  Rollback file:  python3 futures_shadow_auto_promote.py --rollback-file ladder_exit_policies.json")
