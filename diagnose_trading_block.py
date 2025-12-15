#!/usr/bin/env python3
"""
Diagnostic script to identify why trades are not executing.
Run this on your DigitalOcean droplet to pinpoint the blocking issue.
"""

import json
import os
import time
from pathlib import Path
from datetime import datetime

def check_file_exists(path, description):
    """Check if file exists and return status."""
    p = Path(path)
    exists = p.exists()
    size = p.stat().st_size if exists else 0
    mtime = p.stat().st_mtime if exists else 0
    age_seconds = time.time() - mtime if exists else 0
    age_minutes = age_seconds / 60
    
    status = "✅ EXISTS" if exists else "❌ MISSING"
    if exists:
        status += f" | Size: {size} bytes | Age: {age_minutes:.1f} min"
    
    print(f"{status} - {description}")
    return exists, age_minutes

def check_json_file(path, description):
    """Check JSON file and return contents."""
    p = Path(path)
    if not p.exists():
        print(f"❌ MISSING - {description}")
        return None
    
    try:
        with open(p) as f:
            data = json.load(f)
        print(f"✅ EXISTS - {description}")
        return data
    except Exception as e:
        print(f"⚠️ ERROR reading {path}: {e}")
        return None

def check_jsonl_recent(path, description, max_age_minutes=5):
    """Check if JSONL file has recent entries."""
    p = Path(path)
    if not p.exists():
        print(f"❌ MISSING - {description}")
        return False, 0
    
    try:
        mtime = p.stat().st_mtime
        age_seconds = time.time() - mtime
        age_minutes = age_seconds / 60
        
        # Count recent lines
        with open(p, 'r') as f:
            lines = f.readlines()
            recent_count = 0
            for line in lines[-50:]:  # Check last 50 lines
                try:
                    entry = json.loads(line.strip())
                    ts = entry.get('ts', entry.get('timestamp', 0))
                    if isinstance(ts, str):
                        # Try to parse ISO format
                        from dateutil import parser
                        ts_dt = parser.parse(ts)
                        ts = ts_dt.timestamp()
                    if time.time() - ts < max_age_minutes * 60:
                        recent_count += 1
                except:
                    pass
        
        status = "✅ ACTIVE" if age_minutes < max_age_minutes else "⚠️ STALE"
        print(f"{status} - {description} | Age: {age_minutes:.1f} min | Recent entries: {recent_count}")
        return age_minutes < max_age_minutes, recent_count
    except Exception as e:
        print(f"⚠️ ERROR reading {path}: {e}")
        return False, 0

def main():
    print("=" * 80)
    print("TRADING BOT DIAGNOSTIC - Why Trades Are Not Executing")
    print("=" * 80)
    print(f"Time: {datetime.now().isoformat()}\n")
    
    issues = []
    
    # 1. Check signal generation files
    print("\n[1] SIGNAL GENERATION FILES")
    print("-" * 80)
    pred_active, _ = check_jsonl_recent("logs/predictive_signals.jsonl", "predictive_signals.jsonl", max_age_minutes=10)
    ensemble_active, _ = check_jsonl_recent("logs/ensemble_predictions.jsonl", "ensemble_predictions.jsonl", max_age_minutes=10)
    outcomes_active, outcomes_count = check_jsonl_recent("logs/signal_outcomes.jsonl", "signal_outcomes.jsonl", max_age_minutes=10)
    
    if not pred_active:
        issues.append("⚠️ predictive_signals.jsonl is not updating (signals not being generated)")
    if not ensemble_active:
        issues.append("⚠️ ensemble_predictions.jsonl is not updating")
    if not outcomes_active:
        issues.append("❌ signal_outcomes.jsonl is not updating (signals not reaching execution)")
    
    # 2. Check alpha signal policy
    print("\n[2] ALPHA SIGNAL POLICY")
    print("-" * 80)
    signal_policy = check_json_file("configs/signal_policies.json", "signal_policies.json")
    if signal_policy:
        alpha_trading = signal_policy.get("alpha_trading", {})
        enabled = alpha_trading.get("enabled", False)
        enabled_symbols = alpha_trading.get("enabled_symbols", [])
        cooldown = alpha_trading.get("cooldown_seconds", 120)
        
        print(f"   alpha_trading.enabled: {enabled}")
        print(f"   alpha_trading.enabled_symbols: {enabled_symbols}")
        print(f"   alpha_trading.cooldown_seconds: {cooldown}")
        
        if not enabled:
            issues.append("❌ CRITICAL: alpha_trading.enabled = false (signals blocked before conviction gate)")
        if enabled_symbols and len(enabled_symbols) == 0:
            issues.append("⚠️ enabled_symbols is empty (no symbols allowed)")
    
    # 3. Check live config
    print("\n[3] LIVE CONFIG")
    print("-" * 80)
    live_config = check_json_file("live_config.json", "live_config.json")
    if live_config:
        runtime = live_config.get("runtime", {})
        allowed_symbols = runtime.get("allowed_symbols_mode", [])
        print(f"   runtime.allowed_symbols_mode: {allowed_symbols}")
        
        if allowed_symbols and len(allowed_symbols) > 0:
            issues.append(f"⚠️ Symbol restriction active: only {allowed_symbols} allowed")
        else:
            print("   ✅ No symbol restrictions (all symbols allowed)")
    
    # 4. Check execution gates
    print("\n[4] EXECUTION GATES")
    print("-" * 80)
    exec_gov = check_json_file("logs/execution_governor.json", "execution_governor.json")
    fee_arb = check_json_file("logs/fee_arbiter.json", "fee_arbiter.json")
    throttle = check_json_file("logs/correlation_throttle.json", "correlation_throttle.json")
    
    if exec_gov:
        roi_thresh = exec_gov.get("roi_threshold", 0.005)
        max_trades = exec_gov.get("max_trades_hour", 2)
        print(f"   execution_governor.roi_threshold: {roi_thresh} ({roi_thresh*100:.2f}%)")
        print(f"   execution_governor.max_trades_hour: {max_trades}")
        
        if roi_thresh > 0.01:
            issues.append(f"⚠️ ROI threshold very high: {roi_thresh*100:.2f}% (may block all trades)")
        if max_trades < 2:
            issues.append(f"⚠️ Max trades per hour very low: {max_trades}")
    
    if fee_arb:
        roi_gate = fee_arb.get("roi_gate", 0.006)
        print(f"   fee_arbiter.roi_gate: {roi_gate} ({roi_gate*100:.2f}%)")
        
        if roi_gate > 0.01:
            issues.append(f"⚠️ Fee arbiter ROI gate very high: {roi_gate*100:.2f}%")
    
    # 5. Check pending signals
    print("\n[5] PENDING SIGNALS")
    print("-" * 80)
    pending = check_json_file("feature_store/pending_signals.json", "pending_signals.json")
    if pending:
        count = len(pending)
        print(f"   Pending signals: {count}")
        if count > 0:
            print("   ✅ Signals are being logged (conviction gate is working)")
        else:
            issues.append("⚠️ No pending signals (conviction gate may not be called)")
    else:
        issues.append("⚠️ pending_signals.json missing (signals not being logged)")
    
    # 6. Check recent signal activity
    print("\n[6] RECENT SIGNAL ACTIVITY")
    print("-" * 80)
    try:
        with open("logs/predictive_signals.jsonl", "r") as f:
            lines = f.readlines()
            if lines:
                last_line = lines[-1]
                entry = json.loads(last_line.strip())
                symbol = entry.get("symbol", "N/A")
                direction = entry.get("direction", "N/A")
                conviction = entry.get("conviction", "N/A")
                ts = entry.get("ts", entry.get("timestamp", "N/A"))
                print(f"   Last signal: {symbol} {direction} ({conviction}) at {ts}")
            else:
                print("   ⚠️ No signals in predictive_signals.jsonl")
    except Exception as e:
        print(f"   ⚠️ Error reading predictive_signals.jsonl: {e}")
    
    # 7. Check execution gate blocks
    print("\n[7] EXECUTION GATE BLOCKS")
    print("-" * 80)
    try:
        exec_gates_path = Path("logs/execution_gates.jsonl")
        if exec_gates_path.exists():
            with open(exec_gates_path, "r") as f:
                lines = f.readlines()
                recent_blocks = []
                for line in lines[-20:]:
                    try:
                        entry = json.loads(line.strip())
                        if not entry.get("approved", True):
                            recent_blocks.append(entry.get("reason", "unknown"))
                    except:
                        pass
                
                if recent_blocks:
                    from collections import Counter
                    block_counts = Counter(recent_blocks)
                    print("   Recent block reasons:")
                    for reason, count in block_counts.most_common(5):
                        print(f"     - {reason}: {count} times")
                else:
                    print("   ✅ No recent blocks (or file format different)")
        else:
            print("   ⚠️ execution_gates.jsonl not found")
    except Exception as e:
        print(f"   ⚠️ Error checking execution gates: {e}")
    
    # 8. Summary
    print("\n" + "=" * 80)
    print("DIAGNOSTIC SUMMARY")
    print("=" * 80)
    
    if not issues:
        print("✅ No obvious blocking issues detected.")
        print("   Signals are being generated and may be passing through gates.")
        print("   Check logs for specific block reasons.")
    else:
        print(f"Found {len(issues)} potential issues:\n")
        for i, issue in enumerate(issues, 1):
            print(f"{i}. {issue}")
        
        print("\n🔧 RECOMMENDED FIXES:")
        print("   1. Enable alpha trading: configs/signal_policies.json → alpha_trading.enabled = true")
        print("   2. Remove symbol restrictions: live_config.json → runtime.allowed_symbols_mode = []")
        print("   3. Lower ROI thresholds for paper trading (0.0005 = 0.05%)")
        print("   4. Increase max_trades_hour to 10 for paper trading")
    
    print("\n" + "=" * 80)

if __name__ == "__main__":
    main()

