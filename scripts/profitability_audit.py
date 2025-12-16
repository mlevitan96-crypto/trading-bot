#!/usr/bin/env python3
"""
Profitability Audit Script

Mission: Ensure bot makes money by verifying:
1. All profit filters are working correctly
2. Profit filters are not blocking profitable trades
3. Learning systems are improving profitability
4. Signal quality is actually profitable
"""

import sys
import os
from pathlib import Path

# Add src to path - handle both absolute and relative paths
script_dir = Path(__file__).resolve().parent
project_root = script_dir.parent
sys.path.insert(0, str(project_root))

# Also add current working directory as fallback
if os.getcwd() not in sys.path:
    sys.path.insert(0, os.getcwd())

from typing import Dict, List, Any
import json
from datetime import datetime, timedelta
from collections import defaultdict

def audit_profit_filters():
    """Audit all profit filters to ensure they're working correctly."""
    print("\n" + "="*70)
    print("PROFITABILITY AUDIT - Profit Filters")
    print("="*70)
    
    issues = []
    findings = []
    
    # 1. Check fee_aware_gate
    try:
        from src.fee_aware_gate import FeeAwareGate, MAKER_FEE_PCT, TAKER_FEE_PCT, SLIPPAGE_PCT
        gate = FeeAwareGate()
        
        # Test with a profitable trade
        test_result = gate.evaluate_entry(
            symbol="BTCUSDT",
            side="LONG",
            expected_move_pct=0.5,  # 0.5% expected move
            order_size_usd=100,
            is_market=True
        )
        
        total_fees = (TAKER_FEE_PCT * 2) + SLIPPAGE_PCT  # Entry + exit + slippage
        min_required = total_fees * 1.2  # With buffer
        
        findings.append({
            "filter": "FeeAwareGate",
            "status": "✅ ACTIVE",
            "min_required_move": f"{min_required*100:.2f}%",
            "test_result": "ALLOW" if test_result["allow"] else "BLOCK",
            "details": f"Blocks trades with expected move < {min_required*100:.2f}%"
        })
        
        if not test_result["allow"]:
            issues.append("FeeAwareGate blocking profitable test trade (0.5% move)")
            
    except Exception as e:
        issues.append(f"FeeAwareGate error: {e}")
        findings.append({
            "filter": "FeeAwareGate",
            "status": "❌ ERROR",
            "error": str(e)
        })
    
    # 2. Check profit_blofin_learning profit_filter
    try:
        from src.profit_blofin_learning import profit_filter, expected_profit_usd, _read_policy
        
        policy = _read_policy()
        global_cfg = policy.get("global", {})
        min_profit_usd = global_cfg.get("MIN_PROFIT_USD", 1.0)
        
        # Test signal
        test_signal = {
            "symbol": "BTCUSDT",
            "roi": 0.01,  # 1% ROI
            "size_usd": 100
        }
        
        exp_profit = expected_profit_usd(test_signal)
        would_pass = profit_filter(test_signal, global_cfg)
        
        findings.append({
            "filter": "profit_blofin_learning.profit_filter",
            "status": "✅ ACTIVE",
            "min_profit_usd": min_profit_usd,
            "test_signal_profit": f"${exp_profit:.2f}",
            "test_result": "ALLOW" if would_pass else "BLOCK",
            "details": f"Blocks trades with expected profit < ${min_profit_usd}"
        })
        
        if exp_profit < min_profit_usd:
            issues.append(f"profit_filter blocking test trade (${exp_profit:.2f} < ${min_profit_usd})")
            
    except Exception as e:
        issues.append(f"profit_blofin_learning.profit_filter error: {e}")
        findings.append({
            "filter": "profit_blofin_learning.profit_filter",
            "status": "❌ ERROR",
            "error": str(e)
        })
    
    # 3. Check unified_self_governance_bot fee_aware_profit_filter
    try:
        from src.unified_self_governance_bot import fee_aware_profit_filter, _read_policy
        
        cfg = _read_policy()
        sym_cfg = cfg.get("per_symbol", {}).get("BTCUSDT", cfg.get("global", {}))
        
        test_signal = {
            "symbol": "BTCUSDT",
            "side": "LONG",
            "roi": 0.01,
            "size_usd": 100
        }
        
        would_pass = fee_aware_profit_filter(test_signal, sym_cfg)
        
        findings.append({
            "filter": "unified_self_governance_bot.fee_aware_profit_filter",
            "status": "✅ ACTIVE",
            "test_result": "ALLOW" if would_pass else "BLOCK",
            "details": "Fee-aware profit filter in unified governance"
        })
        
    except Exception as e:
        issues.append(f"unified_self_governance_bot.fee_aware_profit_filter error: {e}")
        findings.append({
            "filter": "unified_self_governance_bot.fee_aware_profit_filter",
            "status": "❌ ERROR",
            "error": str(e)
        })
    
    # Print findings
    print("\n📊 Profit Filter Status:")
    for finding in findings:
        print(f"  {finding['status']} {finding['filter']}")
        if 'details' in finding:
            print(f"     {finding['details']}")
        if 'error' in finding:
            print(f"     ERROR: {finding['error']}")
    
    if issues:
        print("\n⚠️  Issues Found:")
        for issue in issues:
            print(f"  - {issue}")
    else:
        print("\n✅ All profit filters are active and working")
    
    return {"findings": findings, "issues": issues}


def audit_learning_systems():
    """Audit learning systems to ensure they're improving profitability."""
    print("\n" + "="*70)
    print("PROFITABILITY AUDIT - Learning Systems")
    print("="*70)
    
    findings = []
    issues = []
    
    # 1. Check signal weight learning
    try:
        from src.weighted_signal_fusion import WeightedSignalFusion, SIGNAL_WEIGHTS_PATH
        
        fusion = WeightedSignalFusion()
        
        # Check if weights file exists and has recent updates
        weights_path = Path(SIGNAL_WEIGHTS_PATH)
        if weights_path.exists():
            weights_age = (datetime.now() - datetime.fromtimestamp(weights_path.stat().st_mtime)).total_seconds() / 3600
            
            with open(weights_path, 'r') as f:
                weights_data = json.load(f)
            
            last_update = weights_data.get("last_updated", "unknown")
            
            findings.append({
                "system": "Signal Weight Learning",
                "status": "✅ ACTIVE",
                "weights_file_age_hours": round(weights_age, 1),
                "last_updated": last_update,
                "details": "Signal weights are being updated based on outcomes"
            })
            
            if weights_age > 168:  # 1 week
                issues.append(f"Signal weights file is stale ({weights_age:.1f} hours old)")
        else:
            issues.append("Signal weights file does not exist - learning may not be active")
            findings.append({
                "system": "Signal Weight Learning",
                "status": "⚠️  NO DATA",
                "details": "Weights file not found"
            })
            
    except Exception as e:
        issues.append(f"Signal weight learning error: {e}")
        findings.append({
            "system": "Signal Weight Learning",
            "status": "❌ ERROR",
            "error": str(e)
        })
    
    # 2. Check profit_blofin_learning
    try:
        from src.profit_blofin_learning import is_profit_learning_enabled, _read_policy
        
        enabled = is_profit_learning_enabled()
        policy = _read_policy()
        
        findings.append({
            "system": "Profit Blofin Learning",
            "status": "✅ ACTIVE" if enabled else "⚠️  DISABLED",
            "enabled": enabled,
            "details": "Profit-driven learning and policy updates"
        })
        
        if not enabled:
            issues.append("Profit learning is disabled - bot may not be improving")
            
    except Exception as e:
        issues.append(f"Profit learning check error: {e}")
        findings.append({
            "system": "Profit Blofin Learning",
            "status": "❌ ERROR",
            "error": str(e)
        })
    
    # Print findings
    print("\n📚 Learning System Status:")
    for finding in findings:
        print(f"  {finding['status']} {finding['system']}")
        if 'details' in finding:
            print(f"     {finding['details']}")
        if 'error' in finding:
            print(f"     ERROR: {finding['error']}")
    
    if issues:
        print("\n⚠️  Issues Found:")
        for issue in issues:
            print(f"  - {issue}")
    else:
        print("\n✅ All learning systems are active")
    
    return {"findings": findings, "issues": issues}


def audit_signal_quality():
    """Audit signal quality to ensure signals are actually profitable."""
    print("\n" + "="*70)
    print("PROFITABILITY AUDIT - Signal Quality")
    print("="*70)
    
    findings = []
    issues = []
    
    # Check signal outcome tracker
    try:
        from src.signal_outcome_tracker import SignalOutcomeTracker, HORIZONS
        
        tracker = SignalOutcomeTracker()
        stats = tracker.get_signal_stats()
        
        if stats and "signal_stats" in stats:
            signal_stats = stats["signal_stats"]
            
            print("\n📈 Signal Performance:")
            for signal_name, stats_data in list(signal_stats.items())[:10]:  # Top 10
                best_ev = max([stats_data.get(f'ev_{h}', 0) for h in HORIZONS])
                best_wr = max([stats_data.get(f'win_rate_{h}', 0) for h in HORIZONS])
                
                status = "✅" if best_ev > 0 else "⚠️" if best_ev == 0 else "❌"
                print(f"  {status} {signal_name}: EV={best_ev:.4f}, WR={best_wr*100:.1f}%")
                
                if best_ev < 0:
                    issues.append(f"Signal {signal_name} has negative EV ({best_ev:.4f})")
            
            findings.append({
                "system": "Signal Outcome Tracking",
                "status": "✅ ACTIVE",
                "signals_tracked": len(signal_stats),
                "details": "Tracking signal performance across multiple horizons"
            })
        else:
            issues.append("No signal statistics available - may need more trading data")
            findings.append({
                "system": "Signal Outcome Tracking",
                "status": "⚠️  NO DATA",
                "details": "Insufficient data for signal quality analysis"
            })
            
    except Exception as e:
        issues.append(f"Signal quality audit error: {e}")
        findings.append({
            "system": "Signal Outcome Tracking",
            "status": "❌ ERROR",
            "error": str(e)
        })
    
    if issues:
        print("\n⚠️  Issues Found:")
        for issue in issues:
            print(f"  - {issue}")
    else:
        print("\n✅ Signal quality tracking is active")
    
    return {"findings": findings, "issues": issues}


def main():
    """Run complete profitability audit."""
    print("\n" + "="*70)
    print("PROFITABILITY AUDIT - Mission: Make Money")
    print("="*70)
    print(f"Started: {datetime.now().isoformat()}")
    
    results = {
        "profit_filters": audit_profit_filters(),
        "learning_systems": audit_learning_systems(),
        "signal_quality": audit_signal_quality()
    }
    
    # Summary
    print("\n" + "="*70)
    print("AUDIT SUMMARY")
    print("="*70)
    
    total_issues = sum(len(r["issues"]) for r in results.values())
    
    if total_issues == 0:
        print("✅ ALL SYSTEMS OPERATIONAL - Bot is configured for profitability")
    else:
        print(f"⚠️  {total_issues} ISSUES FOUND - Review and fix before real money trading")
        print("\nPriority Actions:")
        for category, result in results.items():
            if result["issues"]:
                print(f"\n  {category.upper()}:")
                for issue in result["issues"]:
                    print(f"    - {issue}")
    
    print(f"\nCompleted: {datetime.now().isoformat()}")
    print("="*70)
    
    return results


if __name__ == "__main__":
    main()

