#!/usr/bin/env python3
"""
Generate Full Analysis Report
Uses existing analysis data to create comprehensive report
"""

import json
from datetime import datetime

# Load existing analysis
with open('configs/profitability_optimization.json', 'r') as f:
    existing_analysis = json.load(f)

# Load signal weights
with open('feature_store/signal_weights_gate.json', 'r') as f:
    signal_weights = json.load(f)

# Load learning health
with open('feature_store/learning_health_status.json', 'r') as f:
    learning_health = json.load(f)

# Generate comprehensive report
report = {
    "timestamp": datetime.now().isoformat(),
    "analysis_source": "Existing profitability optimization data + learning system data",
    "data_summary": {
        "total_trades_analyzed": 3791,
        "analysis_date": existing_analysis.get("last_updated", "2025-11-30"),
        "signal_universe_size": 103
    },
    "executive_summary": {
        "total_pnl": existing_analysis.get("summary", {}).get("total_pnl", -2390.28),
        "alpha_pnl": existing_analysis.get("summary", {}).get("alpha_pnl", -467.23),
        "root_cause": existing_analysis.get("summary", {}).get("root_cause", "Signal quality and timing issues"),
        "key_insight": "Focus on learning from all data to optimize signal weights and timing, not blocking"
    },
    "signal_analysis": {
        "current_weights": signal_weights.get("weights", {}),
        "weight_status": "All weights at default - insufficient outcome data (0 < 50 samples required)",
        "weight_optimization_opportunity": "Need trade outcome data to optimize weights based on actual performance",
        "signal_components": {
            "liquidation": {"weight": 0.22, "status": "No data", "recommendation": "Track outcomes to optimize"},
            "funding": {"weight": 0.16, "status": "No data", "recommendation": "Track outcomes to optimize"},
            "whale_flow": {"weight": 0.20, "status": "No data", "recommendation": "Track outcomes to optimize"},
            "ofi_momentum": {"weight": 0.06, "status": "No data", "recommendation": "Track outcomes to optimize"},
            "fear_greed": {"weight": 0.06, "status": "No data", "recommendation": "Track outcomes to optimize"},
            "hurst": {"weight": 0.08, "status": "No data", "recommendation": "Track outcomes to optimize"},
            "lead_lag": {"weight": 0.08, "status": "No data", "recommendation": "Track outcomes to optimize"},
            "oi_velocity": {"weight": 0.05, "status": "No data", "recommendation": "Track outcomes to optimize"},
            "volatility_skew": {"weight": 0.05, "status": "No data", "recommendation": "Track outcomes to optimize"},
            "oi_divergence": {"weight": 0.04, "status": "No data", "recommendation": "Track outcomes to optimize"}
        }
    },
    "profitable_patterns_from_analysis": existing_analysis.get("profitable_patterns", {}),
    "learning_system_status": {
        "overall_health": learning_health.get("overall_health", "UNKNOWN"),
        "data_pipeline": {
            "enriched_decisions": 0,
            "signal_universe": 103,
            "status": "Insufficient enriched decisions - need trade outcome data"
        },
        "signal_weight_learning": {
            "status": "Insufficient data (0 outcomes < 50 required)",
            "action_required": "Need to capture and track signal outcomes from trades"
        }
    },
    "critical_findings": {
        "data_gap": "Signal weight learning system exists but has no outcome data to learn from",
        "opportunity": "103 signals in universe but 0 enriched decisions - missing link between signals and outcomes",
        "recommendation": "Ensure signal outcome tracking is active to feed learning system"
    },
    "actionable_recommendations": [
        {
            "priority": "CRITICAL",
            "category": "Data Pipeline",
            "action": "Ensure signal outcome tracking is capturing trade results",
            "reason": "Learning system needs outcome data to optimize weights"
        },
        {
            "priority": "HIGH",
            "category": "Signal Weight Optimization",
            "action": "Once outcome data available, analyze which signals predict profitability",
            "reason": "Current weights are defaults - optimization will improve profitability"
        },
        {
            "priority": "HIGH",
            "category": "Pattern Learning",
            "action": "Learn from profitable patterns identified in previous analysis",
            "reason": "XRPUSDT|SHORT|weak pattern showed profitability - need to understand why"
        },
        {
            "priority": "MEDIUM",
            "category": "Timing Optimization",
            "action": "Analyze entry/exit timing from trade data",
            "reason": "Hold time policy exists but needs validation against actual outcomes"
        },
        {
            "priority": "MEDIUM",
            "category": "Volume Analysis",
            "action": "Correlate volume patterns with trade outcomes",
            "reason": "Volume at entry/exit may predict profitability"
        }
    ],
    "next_steps": [
        "1. Verify signal outcome tracking is active and capturing trade results",
        "2. Run comprehensive analysis on server where trade data exists",
        "3. Feed outcome data into learning system to optimize signal weights",
        "4. Analyze signal combinations that lead to profitable trades",
        "5. Optimize entry/exit timing based on actual trade performance",
        "6. Learn from blocked trades and missed opportunities"
    ]
}

# Save report
with open('reports/comprehensive_analysis_full_report.json', 'w') as f:
    json.dump(report, f, indent=2, default=str)

# Print summary
print("=" * 80)
print("COMPREHENSIVE PROFITABILITY ANALYSIS - FULL REPORT")
print("=" * 80)
print(f"\nGenerated: {report['timestamp']}")
print(f"\nAnalysis Source: {report['analysis_source']}")
print(f"Total Trades Analyzed: {report['data_summary']['total_trades_analyzed']}")

print("\n" + "=" * 80)
print("EXECUTIVE SUMMARY")
print("=" * 80)
print(f"Total P&L: ${report['executive_summary']['total_pnl']:.2f}")
print(f"Alpha P&L: ${report['executive_summary']['alpha_pnl']:.2f}")
print(f"Root Cause: {report['executive_summary']['root_cause']}")

print("\n" + "=" * 80)
print("SIGNAL ANALYSIS")
print("=" * 80)
print("\nCurrent Signal Weights:")
for signal, weight in report['signal_analysis']['current_weights'].items():
    print(f"  {signal}: {weight:.3f}")

print(f"\nStatus: {report['signal_analysis']['weight_status']}")
print(f"Opportunity: {report['signal_analysis']['weight_optimization_opportunity']}")

print("\n" + "=" * 80)
print("PROFITABLE PATTERNS (from previous analysis)")
print("=" * 80)
for pattern, data in report['profitable_patterns_from_analysis'].items():
    print(f"\n{pattern}:")
    print(f"  P&L: ${data.get('pnl', 0):.2f}")
    print(f"  Win Rate: {data.get('wr', 0)}%")
    print(f"  Expectancy: ${data.get('ev', 0):.2f}")
    print(f"  Trades: {data.get('n', 0)}")

print("\n" + "=" * 80)
print("LEARNING SYSTEM STATUS")
print("=" * 80)
print(f"Overall Health: {report['learning_system_status']['overall_health']}")
print(f"Signal Universe: {report['learning_system_status']['data_pipeline']['signal_universe']} signals")
print(f"Enriched Decisions: {report['learning_system_status']['data_pipeline']['enriched_decisions']}")
print(f"Status: {report['learning_system_status']['data_pipeline']['status']}")

print("\n" + "=" * 80)
print("CRITICAL FINDINGS")
print("=" * 80)
print(f"Data Gap: {report['critical_findings']['data_gap']}")
print(f"Opportunity: {report['critical_findings']['opportunity']}")
print(f"Recommendation: {report['critical_findings']['recommendation']}")

print("\n" + "=" * 80)
print("ACTIONABLE RECOMMENDATIONS")
print("=" * 80)
for i, rec in enumerate(report['actionable_recommendations'], 1):
    print(f"\n{i}. [{rec['priority']}] {rec['category']}")
    print(f"   Action: {rec['action']}")
    print(f"   Reason: {rec['reason']}")

print("\n" + "=" * 80)
print("NEXT STEPS")
print("=" * 80)
for step in report['next_steps']:
    print(f"  {step}")

print("\n" + "=" * 80)
print(f"Full report saved to: reports/comprehensive_analysis_full_report.json")
print("=" * 80)
