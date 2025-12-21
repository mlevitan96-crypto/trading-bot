#!/usr/bin/env python3
"""
Verify Learning System and Performance
=======================================
Comprehensive check to confirm:
1. Learning systems are running
2. Learning cycles have completed
3. Adjustments have been generated and applied
4. Signal weights have been updated
5. Data enrichment is working
6. Performance is improving
"""

import os
import sys
import json
from pathlib import Path
from datetime import datetime, timedelta
from collections import defaultdict

sys.path.insert(0, os.path.dirname(__file__))

print("=" * 80)
print("LEARNING SYSTEM & PERFORMANCE VERIFICATION")
print("=" * 80)
print(f"Time: {datetime.now().isoformat()}\n")

results = {
    "learning_systems": {},
    "data_collection": {},
    "adjustments": {},
    "performance": {},
    "issues": [],
    "recommendations": []
}

# ============================================================================
# 1. CHECK LEARNING SYSTEMS ARE RUNNING
# ============================================================================

print("1. CHECKING LEARNING SYSTEMS")
print("-" * 80)

# Check Continuous Learning Controller
try:
    from src.continuous_learning_controller import ContinuousLearningController, get_learning_state
    
    controller = ContinuousLearningController()
    state = get_learning_state()
    
    if state:
        results["learning_systems"]["continuous_learning"] = {
            "status": "RUNNING",
            "last_update": state.get("generated_at", "unknown"),
            "samples": state.get("samples", {}),
            "adjustments_pending": len(state.get("adjustments", []))
        }
        print(f"   [OK] Continuous Learning Controller: RUNNING")
        print(f"      Samples: {state.get('samples', {})}")
        print(f"      Pending adjustments: {len(state.get('adjustments', []))}")
    else:
        results["learning_systems"]["continuous_learning"] = {"status": "NO_STATE"}
        results["issues"].append("Continuous Learning Controller has no state")
        print(f"   [WARNING] Continuous Learning Controller: NO STATE")
        
except Exception as e:
    results["learning_systems"]["continuous_learning"] = {"status": "ERROR", "error": str(e)}
    results["issues"].append(f"Continuous Learning Controller error: {e}")
    print(f"   [ERROR] Continuous Learning Controller: {e}")

# Check Learning Audit Log
learning_audit = Path("logs/learning_audit.jsonl")
if learning_audit.exists():
    with open(learning_audit, 'r') as f:
        lines = [line for line in f if line.strip()]
        recent_cycles = []
        for line in lines[-20:]:  # Last 20 entries
            try:
                entry = json.loads(line)
                if entry.get("event") == "learning_cycle_complete":
                    recent_cycles.append(entry)
            except:
                pass
        
        if recent_cycles:
            latest = recent_cycles[-1]
            results["learning_systems"]["audit_log"] = {
                "status": "ACTIVE",
                "total_entries": len(lines),
                "recent_cycles": len(recent_cycles),
                "latest_cycle": latest.get("ts", "unknown"),
                "adjustments_generated": latest.get("adjustments_generated", 0)
            }
            print(f"   [OK] Learning Audit Log: {len(lines)} entries")
            print(f"      Recent cycles: {len(recent_cycles)}")
            print(f"      Latest: {datetime.fromtimestamp(latest.get('ts', 0)).isoformat() if latest.get('ts') else 'unknown'}")
            print(f"      Adjustments generated: {latest.get('adjustments_generated', 0)}")
        else:
            results["learning_systems"]["audit_log"] = {"status": "NO_CYCLES"}
            results["issues"].append("Learning audit log exists but no cycles recorded")
            print(f"   [WARNING] Learning Audit Log: {len(lines)} entries but no cycles")
else:
    results["learning_systems"]["audit_log"] = {"status": "MISSING"}
    results["issues"].append("Learning audit log does not exist")
    print(f"   [MISSING] Learning Audit Log: File does not exist")

# ============================================================================
# 2. CHECK DATA COLLECTION
# ============================================================================

print("\n2. CHECKING DATA COLLECTION")
print("-" * 80)

# Signal Outcomes
signal_outcomes = Path("logs/signal_outcomes.jsonl")
if signal_outcomes.exists():
    with open(signal_outcomes, 'r') as f:
        line_count = sum(1 for line in f if line.strip())
    
    # Check recent outcomes
    with open(signal_outcomes, 'r') as f:
        recent_outcomes = []
        for line in list(f)[-100:]:  # Last 100
            try:
                entry = json.loads(line)
                recent_outcomes.append(entry)
            except:
                pass
    
    results["data_collection"]["signal_outcomes"] = {
        "status": "ACTIVE",
        "total": line_count,
        "recent": len(recent_outcomes)
    }
    print(f"   [OK] Signal Outcomes: {line_count:,} total")
    
    if recent_outcomes:
        # Check signal types
        signal_types = defaultdict(int)
        for outcome in recent_outcomes:
            signal_types[outcome.get("signal_name", "unknown")] += 1
        print(f"      Recent signal types: {dict(signal_types)}")
else:
    results["data_collection"]["signal_outcomes"] = {"status": "MISSING"}
    results["issues"].append("Signal outcomes file does not exist")
    print(f"   [MISSING] Signal Outcomes: File does not exist")

# Enriched Decisions
enriched = Path("logs/enriched_decisions.jsonl")
if enriched.exists():
    with open(enriched, 'r') as f:
        line_count = sum(1 for line in f if line.strip())
    
    results["data_collection"]["enriched_decisions"] = {
        "status": "ACTIVE" if line_count > 0 else "EMPTY",
        "total": line_count
    }
    
    if line_count > 0:
        print(f"   [OK] Enriched Decisions: {line_count:,} entries")
    else:
        results["issues"].append("Enriched decisions file is empty")
        results["recommendations"].append("Run fix_audit_issues.py to populate enriched decisions")
        print(f"   [EMPTY] Enriched Decisions: 0 entries (run fix_audit_issues.py)")
else:
    results["data_collection"]["enriched_decisions"] = {"status": "MISSING"}
    results["issues"].append("Enriched decisions file does not exist")
    print(f"   [MISSING] Enriched Decisions: File does not exist")

# Trades
trades_file = Path("logs/positions_futures.json")
if trades_file.exists():
    try:
        with open(trades_file, 'r') as f:
            data = json.load(f)
            closed = data.get("closed_positions", [])
            open_pos = data.get("open_positions", [])
            
            results["data_collection"]["trades"] = {
                "status": "ACTIVE",
                "closed": len(closed),
                "open": len(open_pos)
            }
            print(f"   [OK] Trades: {len(closed)} closed, {len(open_pos)} open")
            
            # Check recent trades
            if closed:
                recent_trades = closed[-50:]  # Last 50
                wins = sum(1 for t in recent_trades if float(t.get("profit_usd", 0)) > 0)
                wr = (wins / len(recent_trades)) * 100 if recent_trades else 0
                total_pnl = sum(float(t.get("profit_usd", 0)) for t in recent_trades)
                
                results["data_collection"]["recent_performance"] = {
                    "trades": len(recent_trades),
                    "win_rate": round(wr, 2),
                    "total_pnl": round(total_pnl, 2)
                }
                print(f"      Recent 50 trades: {wr:.1f}% WR, ${total_pnl:.2f} P&L")
    except Exception as e:
        results["data_collection"]["trades"] = {"status": "ERROR", "error": str(e)}
        print(f"   [ERROR] Trades: {e}")
else:
    results["data_collection"]["trades"] = {"status": "MISSING"}
    print(f"   [MISSING] Trades: File does not exist")

# ============================================================================
# 3. CHECK ADJUSTMENTS
# ============================================================================

print("\n3. CHECKING ADJUSTMENTS")
print("-" * 80)

# Signal Weights
signal_weights = Path("feature_store/signal_weights_gate.json")
if signal_weights.exists():
    try:
        with open(signal_weights, 'r') as f:
            weights_data = json.load(f)
            weights = weights_data.get("weights", {})
            
            # Default weights for comparison
            defaults = {
                "liquidation": 0.22,
                "funding": 0.16,
                "whale_flow": 0.20,
                "ofi_momentum": 0.06,
                "fear_greed": 0.06
            }
            
            # Check if weights differ from defaults
            has_changes = False
            changes = {}
            for signal, default_weight in defaults.items():
                current = weights.get(signal, default_weight)
                if abs(current - default_weight) > 0.01:  # More than 1% difference
                    has_changes = True
                    changes[signal] = {
                        "default": default_weight,
                        "current": current,
                        "change": round((current - default_weight) / default_weight * 100, 1)
                    }
            
            results["adjustments"]["signal_weights"] = {
                "status": "UPDATED" if has_changes else "DEFAULT",
                "weights": weights,
                "changes": changes
            }
            
            if has_changes:
                print(f"   [OK] Signal Weights: UPDATED (learning is working!)")
                for signal, change in changes.items():
                    print(f"      {signal}: {change['default']:.3f} → {change['current']:.3f} ({change['change']:+.1f}%)")
            else:
                print(f"   [DEFAULT] Signal Weights: Still at defaults (need more data)")
                results["recommendations"].append("Signal weights at defaults - need 50+ outcomes per signal")
    except Exception as e:
        results["adjustments"]["signal_weights"] = {"status": "ERROR", "error": str(e)}
        print(f"   [ERROR] Signal Weights: {e}")
else:
    results["adjustments"]["signal_weights"] = {"status": "MISSING"}
    print(f"   [MISSING] Signal Weights: File does not exist")

# Learning State Adjustments
try:
    state = get_learning_state()
    if state:
        adjustments = state.get("adjustments", [])
        applied = state.get("applied", False)
        
        results["adjustments"]["learning_state"] = {
            "status": "HAS_ADJUSTMENTS" if adjustments else "NO_ADJUSTMENTS",
            "count": len(adjustments),
            "applied": applied,
            "adjustments": adjustments[:10]  # First 10
        }
        
        if adjustments:
            print(f"   [OK] Learning State: {len(adjustments)} adjustments generated")
            if applied:
                print(f"      [OK] Adjustments have been APPLIED")
            else:
                print(f"      [PENDING] Adjustments generated but not yet applied")
                results["recommendations"].append("Run fix_learning_system.py to apply adjustments")
        else:
            print(f"   [NO_ADJUSTMENTS] Learning State: No adjustments generated")
            results["recommendations"].append("No adjustments generated - may need more trade data")
except:
    pass

# ============================================================================
# 4. CHECK PERFORMANCE TRENDS
# ============================================================================

print("\n4. CHECKING PERFORMANCE TRENDS")
print("-" * 80)

if trades_file.exists():
    try:
        with open(trades_file, 'r') as f:
            data = json.load(f)
            closed = data.get("closed_positions", [])
        
        if len(closed) >= 100:
            # Compare first 50 vs last 50
            first_50 = closed[:50]
            last_50 = closed[-50:]
            
            def calc_metrics(trades):
                wins = sum(1 for t in trades if float(t.get("profit_usd", 0)) > 0)
                wr = (wins / len(trades)) * 100 if trades else 0
                pnl = sum(float(t.get("profit_usd", 0)) for t in trades)
                avg_pnl = pnl / len(trades) if trades else 0
                return {"win_rate": wr, "total_pnl": pnl, "avg_pnl": avg_pnl, "trades": len(trades)}
            
            first_metrics = calc_metrics(first_50)
            last_metrics = calc_metrics(last_50)
            
            wr_improvement = last_metrics["win_rate"] - first_metrics["win_rate"]
            pnl_improvement = last_metrics["total_pnl"] - first_metrics["total_pnl"]
            
            results["performance"]["trend"] = {
                "first_50": first_metrics,
                "last_50": last_metrics,
                "wr_improvement": round(wr_improvement, 2),
                "pnl_improvement": round(pnl_improvement, 2)
            }
            
            print(f"   First 50 trades: {first_metrics['win_rate']:.1f}% WR, ${first_metrics['total_pnl']:.2f} P&L")
            print(f"   Last 50 trades:  {last_metrics['win_rate']:.1f}% WR, ${last_metrics['total_pnl']:.2f} P&L")
            
            if wr_improvement > 0:
                print(f"   [IMPROVING] Win rate improved by {wr_improvement:+.1f}%")
            else:
                print(f"   [DECLINING] Win rate declined by {wr_improvement:.1f}%")
            
            if pnl_improvement > 0:
                print(f"   [IMPROVING] P&L improved by ${pnl_improvement:+.2f}")
            else:
                print(f"   [DECLINING] P&L declined by ${pnl_improvement:.2f}")
        else:
            print(f"   [INSUFFICIENT_DATA] Need at least 100 trades for trend analysis ({len(closed)} available)")
            results["performance"]["trend"] = {"status": "INSUFFICIENT_DATA", "trades": len(closed)}
    except Exception as e:
        print(f"   [ERROR] Performance analysis: {e}")

# ============================================================================
# 5. SUMMARY & RECOMMENDATIONS
# ============================================================================

print("\n" + "=" * 80)
print("VERIFICATION SUMMARY")
print("=" * 80)

# Overall status
all_ok = (
    results["learning_systems"].get("audit_log", {}).get("status") == "ACTIVE" and
    results["data_collection"].get("signal_outcomes", {}).get("status") == "ACTIVE" and
    results["data_collection"].get("trades", {}).get("status") == "ACTIVE"
)

if all_ok:
    print("\n[OK] Core systems are working!")
else:
    print("\n[WARNING] Some systems need attention")

# Issues
if results["issues"]:
    print(f"\nIssues Found: {len(results['issues'])}")
    for issue in results["issues"][:10]:
        print(f"  - {issue}")

# Recommendations
if results["recommendations"]:
    print(f"\nRecommendations:")
    for rec in results["recommendations"]:
        print(f"  - {rec}")

# Save report
report_path = Path("reports/learning_verification_report.json")
report_path.parent.mkdir(parents=True, exist_ok=True)

report = {
    "timestamp": datetime.now().isoformat(),
    "results": results,
    "overall_status": "OK" if all_ok else "NEEDS_ATTENTION"
}

with open(report_path, 'w') as f:
    json.dump(report, f, indent=2, default=str)

print(f"\n[OK] Full report saved to: {report_path}")
print("\n" + "=" * 80)
print("VERIFICATION COMPLETE")
print("=" * 80)
