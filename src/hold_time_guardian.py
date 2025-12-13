"""
Hold Time Guardian - Automated monitoring and correction for premature exits.

This module continuously monitors trade durations and automatically:
1. Detects when trades are exiting too quickly (below policy minimums)
2. Escalates hold times when short trade patterns emerge
3. Prevents the learning system from shortening hold times with negative EV
4. Self-heals the hold time policy when violations are detected

Run frequency: Every bot cycle + dedicated health check every 15 minutes
"""

import json
import os
import time
from datetime import datetime, timedelta
from typing import Dict, List, Tuple, Any, Optional
from collections import defaultdict

HOLD_TIME_POLICY_PATH = "feature_store/hold_time_policy.json"
GUARDIAN_STATE_PATH = "feature_store/hold_time_guardian_state.json"
POSITIONS_PATH = "logs/positions_futures.json"
GUARDIAN_LOG_PATH = "logs/hold_time_guardian.jsonl"

MINIMUM_HOLD_FLOOR = 900  # 15 minutes - absolute minimum
SHORT_TRADE_THRESHOLD = 300  # 5 minutes - trades shorter than this are "dangerously short"
VIOLATION_ESCALATION_FACTOR = 1.5  # Increase hold time by 50% when violations detected
MAX_HOLD_TIME = 14400  # 4 hours cap
VIOLATION_WINDOW_HOURS = 4  # Look back 4 hours for violations
MIN_TRADES_FOR_DETECTION = 3  # Need at least 3 trades to detect pattern


def _now() -> str:
    return datetime.utcnow().isoformat() + "Z"


def _read_json(path: str, default: Any = None) -> Any:
    try:
        if os.path.exists(path):
            with open(path, 'r') as f:
                return json.load(f)
    except Exception:
        pass
    return default if default is not None else {}


def _write_json(path: str, data: Any) -> bool:
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'w') as f:
            json.dump(data, f, indent=2)
        return True
    except Exception as e:
        print(f"[HOLD-GUARDIAN] Failed to write {path}: {e}")
        return False


def _append_log(entry: Dict) -> None:
    try:
        os.makedirs(os.path.dirname(GUARDIAN_LOG_PATH), exist_ok=True)
        entry["timestamp"] = _now()
        with open(GUARDIAN_LOG_PATH, 'a') as f:
            f.write(json.dumps(entry) + "\n")
    except Exception:
        pass


def _parse_timestamp(ts: str) -> Optional[datetime]:
    """Parse various timestamp formats."""
    if not ts:
        return None
    for fmt in [
        "%Y-%m-%dT%H:%M:%S.%fZ",
        "%Y-%m-%dT%H:%M:%SZ",
        "%Y-%m-%dT%H:%M:%S.%f",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%d %H:%M:%S.%f",
        "%Y-%m-%d %H:%M:%S",
    ]:
        try:
            return datetime.strptime(ts, fmt)
        except ValueError:
            continue
    return None


def get_recent_closed_trades(hours: int = 4) -> List[Dict]:
    """Get trades closed within the last N hours."""
    positions = _read_json(POSITIONS_PATH, {})
    closed = positions.get("closed", [])
    
    cutoff = datetime.utcnow() - timedelta(hours=hours)
    recent = []
    
    for trade in closed:
        closed_at = trade.get("closed_at", "")
        closed_dt = _parse_timestamp(closed_at)
        if closed_dt and closed_dt > cutoff:
            recent.append(trade)
    
    return recent


def calculate_trade_duration(trade: Dict) -> Optional[int]:
    """Calculate trade duration in seconds."""
    opened_at = trade.get("opened_at", "")
    closed_at = trade.get("closed_at", "")
    
    opened_dt = _parse_timestamp(opened_at)
    closed_dt = _parse_timestamp(closed_at)
    
    if opened_dt and closed_dt:
        return int((closed_dt - opened_dt).total_seconds())
    return None


def analyze_trade_durations(trades: List[Dict]) -> Dict[str, Dict]:
    """Analyze trade durations by symbol."""
    by_symbol = defaultdict(list)
    
    for trade in trades:
        symbol = trade.get("symbol", "UNKNOWN")
        duration = calculate_trade_duration(trade)
        pnl = trade.get("pnl") or trade.get("net_pnl", 0)
        
        if duration is not None and duration > 0:
            by_symbol[symbol].append({
                "duration": duration,
                "pnl": pnl,
                "is_short": duration < SHORT_TRADE_THRESHOLD,
                "is_very_short": duration < 120,  # < 2 minutes
            })
    
    analysis = {}
    for symbol, trades_list in by_symbol.items():
        if not trades_list:
            continue
            
        durations = [t["duration"] for t in trades_list]
        pnls = [t["pnl"] for t in trades_list]
        short_count = sum(1 for t in trades_list if t["is_short"])
        very_short_count = sum(1 for t in trades_list if t["is_very_short"])
        
        avg_duration = sum(durations) / len(durations)
        avg_pnl = sum(pnls) / len(pnls)
        short_pct = short_count / len(trades_list) * 100
        
        analysis[symbol] = {
            "trade_count": len(trades_list),
            "avg_duration_sec": round(avg_duration),
            "avg_duration_min": round(avg_duration / 60, 1),
            "avg_pnl": round(avg_pnl, 2),
            "short_trade_count": short_count,
            "very_short_count": very_short_count,
            "short_trade_pct": round(short_pct, 1),
            "violation_detected": short_pct > 50 and len(trades_list) >= MIN_TRADES_FOR_DETECTION,
        }
    
    return analysis


def detect_violations(analysis: Dict[str, Dict]) -> List[Dict]:
    """Detect symbols with hold time violations."""
    violations = []
    
    for symbol, stats in analysis.items():
        if stats.get("violation_detected"):
            violations.append({
                "symbol": symbol,
                "severity": "HIGH" if stats["very_short_count"] > 0 else "MEDIUM",
                "short_trade_pct": stats["short_trade_pct"],
                "avg_duration_min": stats["avg_duration_min"],
                "trade_count": stats["trade_count"],
                "avg_pnl": stats["avg_pnl"],
            })
        elif stats["trade_count"] >= 2 and stats["avg_duration_sec"] < MINIMUM_HOLD_FLOOR:
            violations.append({
                "symbol": symbol,
                "severity": "LOW",
                "short_trade_pct": stats["short_trade_pct"],
                "avg_duration_min": stats["avg_duration_min"],
                "trade_count": stats["trade_count"],
                "avg_pnl": stats["avg_pnl"],
            })
    
    return violations


def fix_violations(violations: List[Dict]) -> Dict[str, Any]:
    """Auto-fix hold time violations by escalating minimums."""
    if not violations:
        return {"status": "no_violations", "fixes_applied": 0}
    
    policy = _read_json(HOLD_TIME_POLICY_PATH, {})
    symbol_hold_times = dict(policy.get("symbol_hold_times", {}))
    fixes = []
    
    for violation in violations:
        symbol = violation["symbol"]
        current_hold = symbol_hold_times.get(symbol, MINIMUM_HOLD_FLOOR)
        
        if violation["severity"] == "HIGH":
            escalation = 2.0  # Double hold time for severe violations
        elif violation["severity"] == "MEDIUM":
            escalation = VIOLATION_ESCALATION_FACTOR
        else:
            escalation = 1.25
        
        new_hold = min(int(current_hold * escalation), MAX_HOLD_TIME)
        new_hold = max(new_hold, MINIMUM_HOLD_FLOOR)
        
        if new_hold > current_hold:
            symbol_hold_times[symbol] = new_hold
            fix = {
                "symbol": symbol,
                "old_hold_sec": current_hold,
                "new_hold_sec": new_hold,
                "old_hold_min": round(current_hold / 60, 1),
                "new_hold_min": round(new_hold / 60, 1),
                "severity": violation["severity"],
                "reason": f"Short trades detected ({violation['short_trade_pct']:.0f}% below {SHORT_TRADE_THRESHOLD}s)",
            }
            fixes.append(fix)
            print(f"🛡️ [HOLD-GUARDIAN] {symbol}: Hold time {current_hold}s → {new_hold}s (severity: {violation['severity']})")
    
    if fixes:
        policy["symbol_hold_times"] = symbol_hold_times
        policy["updated_at"] = _now()
        policy["version"] = policy.get("version", 1) + 1
        
        if "guardian_fixes" not in policy:
            policy["guardian_fixes"] = []
        policy["guardian_fixes"].append({
            "timestamp": _now(),
            "fixes": fixes,
        })
        
        if len(policy["guardian_fixes"]) > 50:
            policy["guardian_fixes"] = policy["guardian_fixes"][-50:]
        
        _write_json(HOLD_TIME_POLICY_PATH, policy)
        
        _append_log({
            "event": "violations_fixed",
            "fixes": fixes,
            "total_violations": len(violations),
        })
    
    return {
        "status": "fixed",
        "fixes_applied": len(fixes),
        "fixes": fixes,
    }


def validate_policy_sanity() -> Dict[str, Any]:
    """Validate that the hold time policy doesn't have dangerously short values."""
    policy = _read_json(HOLD_TIME_POLICY_PATH, {})
    symbol_hold_times = policy.get("symbol_hold_times", {})
    
    issues = []
    fixes = []
    
    for symbol, hold_time in symbol_hold_times.items():
        if hold_time < MINIMUM_HOLD_FLOOR:
            issues.append({
                "symbol": symbol,
                "current": hold_time,
                "minimum": MINIMUM_HOLD_FLOOR,
                "issue": "below_minimum_floor",
            })
            symbol_hold_times[symbol] = MINIMUM_HOLD_FLOOR
            fixes.append({
                "symbol": symbol,
                "old": hold_time,
                "new": MINIMUM_HOLD_FLOOR,
                "reason": "below_minimum_floor",
            })
    
    tier_defaults = policy.get("tier_defaults", {})
    for tier, default_hold in tier_defaults.items():
        if default_hold < MINIMUM_HOLD_FLOOR:
            old_val = default_hold
            tier_defaults[tier] = max(MINIMUM_HOLD_FLOOR, default_hold)
            issues.append({
                "tier": tier,
                "current": old_val,
                "minimum": MINIMUM_HOLD_FLOOR,
                "issue": "tier_default_too_low",
            })
    
    if fixes:
        policy["symbol_hold_times"] = symbol_hold_times
        policy["tier_defaults"] = tier_defaults
        policy["updated_at"] = _now()
        _write_json(HOLD_TIME_POLICY_PATH, policy)
        
        print(f"🛡️ [HOLD-GUARDIAN] Policy sanity check: Fixed {len(fixes)} issues")
        _append_log({
            "event": "policy_sanity_fix",
            "issues": issues,
            "fixes": fixes,
        })
    
    return {
        "status": "checked",
        "issues_found": len(issues),
        "fixes_applied": len(fixes),
        "issues": issues,
    }


def run_guardian_check() -> Dict[str, Any]:
    """
    Main guardian check - run this every bot cycle or on schedule.
    
    Returns a summary of the check and any actions taken.
    """
    print("🛡️ [HOLD-GUARDIAN] Running automated hold time check...")
    
    result = {
        "timestamp": _now(),
        "status": "ok",
        "actions": [],
    }
    
    sanity = validate_policy_sanity()
    if sanity["fixes_applied"] > 0:
        result["actions"].append({
            "type": "policy_sanity_fix",
            "details": sanity,
        })
    
    recent_trades = get_recent_closed_trades(hours=VIOLATION_WINDOW_HOURS)
    result["trades_analyzed"] = len(recent_trades)
    
    if len(recent_trades) < MIN_TRADES_FOR_DETECTION:
        result["status"] = "insufficient_data"
        print(f"🛡️ [HOLD-GUARDIAN] Only {len(recent_trades)} trades in window, need {MIN_TRADES_FOR_DETECTION}+")
        return result
    
    analysis = analyze_trade_durations(recent_trades)
    result["symbol_analysis"] = analysis
    
    violations = detect_violations(analysis)
    result["violations_detected"] = len(violations)
    
    if violations:
        result["status"] = "violations_detected"
        fix_result = fix_violations(violations)
        result["fix_result"] = fix_result
        result["actions"].append({
            "type": "violation_fix",
            "details": fix_result,
        })
        
        if fix_result["fixes_applied"] > 0:
            print(f"🛡️ [HOLD-GUARDIAN] AUTO-FIXED {fix_result['fixes_applied']} hold time violations!")
    else:
        result["status"] = "ok"
        print("🛡️ [HOLD-GUARDIAN] No violations detected - hold times are healthy")
    
    state = _read_json(GUARDIAN_STATE_PATH, {})
    state["last_check"] = _now()
    state["last_result"] = result["status"]
    state["total_checks"] = state.get("total_checks", 0) + 1
    state["total_fixes"] = state.get("total_fixes", 0) + len(result.get("fix_result", {}).get("fixes", []))
    _write_json(GUARDIAN_STATE_PATH, state)
    
    return result


def get_guardian_status() -> Dict[str, Any]:
    """Get the current guardian status for dashboard/monitoring."""
    state = _read_json(GUARDIAN_STATE_PATH, {})
    policy = _read_json(HOLD_TIME_POLICY_PATH, {})
    
    symbol_hold_times = policy.get("symbol_hold_times", {})
    
    below_floor = [s for s, h in symbol_hold_times.items() if h < MINIMUM_HOLD_FLOOR]
    
    return {
        "last_check": state.get("last_check", "never"),
        "last_result": state.get("last_result", "unknown"),
        "total_checks": state.get("total_checks", 0),
        "total_fixes": state.get("total_fixes", 0),
        "symbols_monitored": len(symbol_hold_times),
        "symbols_below_floor": below_floor,
        "minimum_floor_sec": MINIMUM_HOLD_FLOOR,
        "minimum_floor_min": round(MINIMUM_HOLD_FLOOR / 60, 1),
        "policy_version": policy.get("version", 0),
    }


def block_short_exit(symbol: str, duration_sec: int, min_hold_sec: int) -> Tuple[bool, str]:
    """
    Check if an exit should be blocked due to insufficient hold time.
    
    Returns: (should_block, reason)
    """
    if duration_sec >= min_hold_sec:
        return False, ""
    
    remaining = min_hold_sec - duration_sec
    reason = f"Hold time guardian: {remaining}s remaining (min {min_hold_sec}s)"
    
    _append_log({
        "event": "exit_blocked",
        "symbol": symbol,
        "duration_sec": duration_sec,
        "min_hold_sec": min_hold_sec,
        "remaining_sec": remaining,
    })
    
    return True, reason


if __name__ == "__main__":
    print("=" * 60)
    print("🛡️ HOLD TIME GUARDIAN - Manual Check")
    print("=" * 60)
    
    result = run_guardian_check()
    
    print("\n📊 SUMMARY:")
    print(f"   Status: {result['status']}")
    print(f"   Trades analyzed: {result.get('trades_analyzed', 0)}")
    print(f"   Violations: {result.get('violations_detected', 0)}")
    print(f"   Actions taken: {len(result.get('actions', []))}")
    
    if result.get("symbol_analysis"):
        print("\n📈 BY SYMBOL:")
        for sym, stats in result["symbol_analysis"].items():
            status = "⚠️ VIOLATION" if stats.get("violation_detected") else "✅ OK"
            print(f"   {sym}: avg {stats['avg_duration_min']}min, {stats['short_trade_pct']:.0f}% short, EV=${stats['avg_pnl']:.2f} {status}")
