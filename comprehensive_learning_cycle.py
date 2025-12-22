#!/usr/bin/env python3
"""
Comprehensive Learning Cycle
============================
Complete learning cycle that processes ALL signal data and generates
actionable recommendations to increase profitability.

This script:
1. Processes all resolved signals
2. Runs all learning components
3. Analyzes profitability from all angles
4. Generates actionable recommendations
5. Provides comprehensive summary

Usage:
    python3 comprehensive_learning_cycle.py
"""

import os
import sys
import json
import time
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Any

sys.path.insert(0, os.path.dirname(__file__))

print("=" * 80)
print("COMPREHENSIVE LEARNING CYCLE")
print("=" * 80)
print(f"Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
print()

# Verify active directory
try:
    from src.infrastructure.path_registry import PathRegistry
    active_dir = PathRegistry.get_root()
    print(f"📁 Active Directory: {active_dir}")
    print(f"   (All data will be read from this location)\n")
except Exception as e:
    print(f"⚠️  Could not determine active directory: {e}\n")

results = {
    "generated_at": datetime.now().isoformat(),
    "active_directory": str(active_dir) if 'active_dir' in locals() else "unknown",
    "components": {},
    "recommendations": [],
    "summary": {}
}

# ============================================================================
# STEP 1: Process All Resolved Signals
# ============================================================================
print("=" * 80)
print("STEP 1: PROCESSING ALL RESOLVED SIGNALS")
print("=" * 80)

try:
    from src.signal_outcome_tracker import signal_tracker, PENDING_SIGNALS_FILE
    
    # Check pending signals
    if PENDING_SIGNALS_FILE.exists():
        import json as json_module
        with open(PENDING_SIGNALS_FILE, 'r') as f:
            pending_data = json_module.load(f)
            pending_count = len(pending_data) if isinstance(pending_data, dict) else len(pending_data) if isinstance(pending_data, list) else 0
        print(f"📊 Pending signals: {pending_count:,}")
    
    # Resolve any remaining signals (process in large batches)
    print("   Resolving any remaining pending signals...")
    resolved = signal_tracker.resolve_pending_signals(max_signals_per_cycle=1000, throttle_ms=0)
    print(f"   ✅ Resolved {resolved} signals")
    
    # Get signal outcomes count
    outcomes_file = Path("logs/signal_outcomes.jsonl")
    if outcomes_file.exists():
        with open(outcomes_file, 'r') as f:
            outcomes_count = sum(1 for line in f if line.strip())
        print(f"📊 Total resolved outcomes: {outcomes_count:,}")
        results["components"]["signal_resolution"] = {
            "pending_signals": pending_count,
            "resolved_this_cycle": resolved,
            "total_outcomes": outcomes_count
        }
    else:
        print("   ⚠️  No signal outcomes file found")
        results["components"]["signal_resolution"] = {"error": "No outcomes file"}
        
except Exception as e:
    print(f"   ❌ Error processing signals: {e}")
    import traceback
    traceback.print_exc()
    results["components"]["signal_resolution"] = {"error": str(e)}

print()

# ============================================================================
# STEP 2: Signal Weight Learning
# ============================================================================
print("=" * 80)
print("STEP 2: SIGNAL WEIGHT LEARNING")
print("=" * 80)

try:
    from src.signal_weight_learner import run_weight_update
    
    print("   Running signal weight update...")
    weight_result = run_weight_update(dry_run=False)
    
    if weight_result.get('status') == 'success':
        summary = weight_result.get('summary', {})
        print(f"   ✅ Signal weights updated")
        print(f"      Outcomes analyzed: {summary.get('total_outcomes', 0):,}")
        print(f"      Signals evaluated: {summary.get('signals_evaluated', 0)}")
        
        # Show weight changes
        weight_changes = weight_result.get('weight_changes', {})
        if weight_changes:
            print(f"\n   📊 Weight Changes:")
            for signal, change in sorted(weight_changes.items(), key=lambda x: abs(x[1].get('change_pct', 0)), reverse=True)[:10]:
                old_w = change.get('old_weight', 0)
                new_w = change.get('new_weight', 0)
                change_pct = change.get('change_pct', 0)
                print(f"      {signal:20s} {old_w:.3f} → {new_w:.3f} ({change_pct:+.1f}%)")
        
        results["components"]["signal_weights"] = {
            "status": "success",
            "outcomes_analyzed": summary.get('total_outcomes', 0),
            "weight_changes": weight_changes
        }
    else:
        print(f"   ⚠️  Signal weight update: {weight_result.get('status', 'unknown')}")
        results["components"]["signal_weights"] = weight_result
        
except Exception as e:
    print(f"   ❌ Error in signal weight learning: {e}")
    import traceback
    traceback.print_exc()
    results["components"]["signal_weights"] = {"error": str(e)}

print()

# ============================================================================
# STEP 3: Continuous Learning Controller
# ============================================================================
print("=" * 80)
print("STEP 3: CONTINUOUS LEARNING CONTROLLER")
print("=" * 80)

try:
    from src.continuous_learning_controller import ContinuousLearningController
    
    print("   Running comprehensive learning cycle...")
    clc = ContinuousLearningController()
    learning_state = clc.run_learning_cycle(force=True)
    
    samples = learning_state.get('samples', {})
    profitability = learning_state.get('profitability', {})
    adjustments = learning_state.get('adjustments', [])
    
    print(f"   ✅ Learning cycle complete")
    print(f"      Executed trades: {samples.get('executed', 0):,}")
    print(f"      Blocked signals: {samples.get('blocked', 0):,}")
    print(f"      Adjustments generated: {len(adjustments)}")
    
    # Show profitability summary
    if profitability:
        total_pnl = profitability.get('total_pnl', 0)
        win_rate = profitability.get('win_rate', 0)
        expectancy = profitability.get('expectancy', 0)
        print(f"\n   📊 Profitability Summary:")
        print(f"      Total P&L: ${total_pnl:.2f}")
        print(f"      Win Rate: {win_rate:.1f}%")
        print(f"      Expectancy: ${expectancy:.2f}")
    
    results["components"]["continuous_learning"] = {
        "status": "success",
        "samples": samples,
        "profitability": profitability,
        "adjustments_count": len(adjustments),
        "adjustments": adjustments[:20]  # First 20 for summary
    }
    
except Exception as e:
    print(f"   ❌ Error in continuous learning: {e}")
    import traceback
    traceback.print_exc()
    results["components"]["continuous_learning"] = {"error": str(e)}

print()

# ============================================================================
# STEP 4: Deep Profitability Analysis
# ============================================================================
print("=" * 80)
print("STEP 4: DEEP PROFITABILITY ANALYSIS")
print("=" * 80)

try:
    from src.deep_profitability_analyzer import DeepProfitabilityAnalyzer
    
    print("   Running deep profitability analysis...")
    analyzer = DeepProfitabilityAnalyzer()
    analyzer.load_all_data()
    
    # Run full analysis (includes all sub-analyses)
    full_results = analyzer.run_full_analysis()
    
    print(f"   ✅ Deep analysis complete")
    print(f"      Recommendations: {len(full_results.get('recommendations', []))}")
    
    results["components"]["deep_profitability"] = {
        "status": "success",
        "trade_analysis": full_results.get('trade_analysis', {}),
        "enriched_analysis": full_results.get('enriched_analysis', {}),
        "pattern_analysis": full_results.get('pattern_analysis', {}),
        "duration_analysis": full_results.get('duration_analysis', {}),
        "recommendations": full_results.get('recommendations', [])
    }
    
except Exception as e:
    print(f"   ❌ Error in deep profitability analysis: {e}")
    import traceback
    traceback.print_exc()
    results["components"]["deep_profitability"] = {"error": str(e)}

print()

# ============================================================================
# STEP 5: Comprehensive Intelligence Analysis
# ============================================================================
print("=" * 80)
print("STEP 5: COMPREHENSIVE INTELLIGENCE ANALYSIS")
print("=" * 80)

try:
    from src.comprehensive_intelligence_analysis import run_comprehensive_analysis
    
    print("   Running comprehensive intelligence analysis...")
    intel_results = run_comprehensive_analysis()
    
    data_summary = intel_results.get('data_summary', {})
    actionable_rules = intel_results.get('actionable_rules', {})
    
    print(f"   ✅ Intelligence analysis complete")
    print(f"      Executed: {data_summary.get('executed', 0):,}")
    print(f"      Blocked: {data_summary.get('blocked', 0):,}")
    print(f"      Missed: {data_summary.get('missed', 0):,}")
    
    results["components"]["intelligence_analysis"] = {
        "status": "success",
        "data_summary": data_summary,
        "actionable_rules": actionable_rules
    }
    
except Exception as e:
    print(f"   ⚠️  Comprehensive intelligence analysis error: {e}")
    import traceback
    traceback.print_exc()
    results["components"]["intelligence_analysis"] = {"error": str(e), "note": "Non-critical"}

print()

# ============================================================================
# STEP 6: Strategic Advisor Analysis
# ============================================================================
print("=" * 80)
print("STEP 6: STRATEGIC ADVISOR ANALYSIS")
print("=" * 80)

try:
    from src.strategic_advisor import StrategicAdvisor
    
    print("   Running strategic advisor analysis...")
    advisor = StrategicAdvisor()
    advisor_insights = advisor.run_hourly_analysis()
    
    recommendations_list = advisor_insights.get('recommendations', [])
    metrics = advisor_insights.get('metrics', {})
    
    print(f"   ✅ Strategic analysis complete")
    print(f"      Recommendations: {len(recommendations_list)}")
    if metrics:
        print(f"      Total P&L: ${metrics.get('total_pnl', 0):.2f}")
        print(f"      Win Rate: {metrics.get('win_rate', 0):.1f}%")
    
    results["components"]["strategic_advisor"] = {
        "status": "success",
        "recommendations": recommendations_list,
        "metrics": metrics
    }
    
except Exception as e:
    print(f"   ⚠️  Strategic advisor error: {e}")
    import traceback
    traceback.print_exc()
    results["components"]["strategic_advisor"] = {"error": str(e), "note": "Non-critical"}

print()

# ============================================================================
# STEP 7: Generate Comprehensive Recommendations
# ============================================================================
print("=" * 80)
print("STEP 7: GENERATING ACTIONABLE RECOMMENDATIONS")
print("=" * 80)

all_recommendations = []

# Collect recommendations from all sources
try:
    # From signal weights
    if 'signal_weights' in results["components"] and 'weight_changes' in results["components"]["signal_weights"]:
        weight_changes = results["components"]["signal_weights"]["weight_changes"]
        for signal, change in weight_changes.items():
            change_pct = change.get('change_pct', 0)
            if abs(change_pct) > 10:  # Significant change
                all_recommendations.append({
                    "priority": "HIGH" if abs(change_pct) > 15 else "MEDIUM",
                    "category": "Signal Weights",
                    "action": f"Signal '{signal}' weight changed by {change_pct:+.1f}%",
                    "impact": f"Will {'increase' if change_pct > 0 else 'decrease'} influence of {signal} signals",
                    "data": change
                })
    
    # From continuous learning
    if 'continuous_learning' in results["components"] and 'adjustments' in results["components"]["continuous_learning"]:
        for adj in results["components"]["continuous_learning"]["adjustments"]:
            all_recommendations.append({
                "priority": adj.get('priority', 'MEDIUM'),
                "category": "Learning Adjustments",
                "action": adj.get('action', 'Unknown'),
                "impact": adj.get('expected_impact', 'Unknown'),
                "data": adj
            })
    
    # From deep profitability (recommendations are strings, not dicts)
    if 'deep_profitability' in results["components"] and 'recommendations' in results["components"]["deep_profitability"]:
        for rec in results["components"]["deep_profitability"]["recommendations"]:
            # Recommendations are strings, extract priority from content
            priority = "HIGH" if any(word in rec.lower() for word in ["block", "avoid", "restrict", "critical"]) else "MEDIUM"
            all_recommendations.append({
                "priority": priority,
                "category": "Profitability Optimization",
                "action": rec if isinstance(rec, str) else str(rec),
                "impact": "Improve profitability by following pattern-based insights",
                "data": {"recommendation": rec}
            })
    
    # From strategic advisor
    if 'strategic_advisor' in results["components"] and 'recommendations' in results["components"]["strategic_advisor"]:
        for rec in results["components"]["strategic_advisor"]["recommendations"]:
            all_recommendations.append({
                "priority": rec.get('priority', 'MEDIUM'),
                "category": "Strategic",
                "action": rec.get('action', rec.get('recommendation', 'Unknown')),
                "impact": rec.get('expected_impact', 'Unknown'),
                "data": rec
            })
    
    # Sort by priority
    priority_order = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}
    all_recommendations.sort(key=lambda x: priority_order.get(x.get('priority', 'MEDIUM'), 1))
    
    print(f"   ✅ Generated {len(all_recommendations)} recommendations")
    
except Exception as e:
    print(f"   ⚠️  Error generating recommendations: {e}")
    import traceback
    traceback.print_exc()

results["recommendations"] = all_recommendations

print()

# ============================================================================
# STEP 8: Generate Summary
# ============================================================================
print("=" * 80)
print("COMPREHENSIVE LEARNING CYCLE SUMMARY")
print("=" * 80)

# Calculate summary statistics
total_outcomes = results["components"].get("signal_resolution", {}).get("total_outcomes", 0)
executed_trades = results["components"].get("continuous_learning", {}).get("samples", {}).get("executed", 0)
profitability = results["components"].get("continuous_learning", {}).get("profitability", {})

summary = {
    "signal_data": {
        "total_outcomes_analyzed": total_outcomes,
        "signals_resolved": results["components"].get("signal_resolution", {}).get("resolved_this_cycle", 0)
    },
    "trade_data": {
        "executed_trades": executed_trades,
        "blocked_signals": results["components"].get("continuous_learning", {}).get("samples", {}).get("blocked", 0)
    },
    "profitability": {
        "total_pnl": profitability.get("total_pnl", 0),
        "win_rate": profitability.get("win_rate", 0),
        "expectancy": profitability.get("expectancy", 0)
    },
    "recommendations_count": len(all_recommendations),
    "high_priority_recommendations": len([r for r in all_recommendations if r.get('priority') == 'HIGH'])
}

results["summary"] = summary

# Print summary
print(f"\n📊 DATA PROCESSED:")
print(f"   Signal outcomes: {total_outcomes:,}")
print(f"   Executed trades: {executed_trades:,}")

if profitability:
    print(f"\n💰 PROFITABILITY:")
    print(f"   Total P&L: ${profitability.get('total_pnl', 0):.2f}")
    print(f"   Win Rate: {profitability.get('win_rate', 0):.1f}%")
    print(f"   Expectancy: ${profitability.get('expectancy', 0):.2f} per trade")

print(f"\n💡 RECOMMENDATIONS:")
print(f"   Total: {len(all_recommendations)}")
print(f"   High Priority: {summary['high_priority_recommendations']}")

if all_recommendations:
    print(f"\n   TOP RECOMMENDATIONS:")
    for i, rec in enumerate(all_recommendations[:10], 1):
        priority = rec.get('priority', 'MEDIUM')
        category = rec.get('category', 'Unknown')
        action = rec.get('action', 'Unknown')[:60]  # Truncate for display
        print(f"   {i}. [{priority}] {category}: {action}")

# Save results
output_file = Path("feature_store/comprehensive_learning_cycle_results.json")
output_file.parent.mkdir(parents=True, exist_ok=True)
with open(output_file, 'w') as f:
    json.dump(results, f, indent=2, default=str)

print(f"\n💾 Full results saved to: {output_file}")

# Generate human-readable summary
summary_file = Path("feature_store/learning_cycle_summary.md")
with open(summary_file, 'w') as f:
    f.write("# Comprehensive Learning Cycle Summary\n\n")
    f.write(f"**Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")
    f.write("## Data Processed\n\n")
    f.write(f"- Signal Outcomes: {total_outcomes:,}\n")
    f.write(f"- Executed Trades: {executed_trades:,}\n\n")
    f.write("## Profitability Metrics\n\n")
    if profitability:
        f.write(f"- Total P&L: ${profitability.get('total_pnl', 0):.2f}\n")
        f.write(f"- Win Rate: {profitability.get('win_rate', 0):.1f}%\n")
        f.write(f"- Expectancy: ${profitability.get('expectancy', 0):.2f} per trade\n\n")
    f.write("## Actionable Recommendations\n\n")
    for i, rec in enumerate(all_recommendations, 1):
        f.write(f"### {i}. [{rec.get('priority', 'MEDIUM')}] {rec.get('category', 'Unknown')}\n\n")
        f.write(f"**Action:** {rec.get('action', 'Unknown')}\n\n")
        f.write(f"**Expected Impact:** {rec.get('impact', 'Unknown')}\n\n")
        f.write("---\n\n")

print(f"📄 Human-readable summary saved to: {summary_file}")

print("\n" + "=" * 80)
print("✅ COMPREHENSIVE LEARNING CYCLE COMPLETE")
print("=" * 80)
print(f"\nReview the recommendations above and in:")
print(f"   - {output_file}")
print(f"   - {summary_file}")
print(f"\nOnce reviewed, you can decide which actions to take.")
print("=" * 80)
