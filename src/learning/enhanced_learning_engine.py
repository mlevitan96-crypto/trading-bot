#!/usr/bin/env python3
"""
Enhanced Learning Engine
=========================
Unified learning engine that reviews everything:
- Blocked trades
- Missed opportunities
- What-if scenarios
- Signal performance with different weights
- Guard effectiveness

This is the "big wheel" - learning that directly improves signals.
"""

import json
import time
from pathlib import Path
from typing import Dict, List, Optional, Any
from datetime import datetime, timedelta
from collections import defaultdict

from src.infrastructure.path_registry import PathRegistry
from src.signal_bus import get_signal_bus
from src.shadow_execution_engine import get_shadow_engine
from src.analytics.report_generator import AnalyticsReportGenerator
from src.continuous_learning_controller import ContinuousLearningController


class EnhancedLearningEngine:
    """
    Comprehensive learning engine that reviews all aspects of trading.
    
    Features:
    1. Blocked Trade Analysis - What did we miss?
    2. Missed Opportunity Tracking - What would have happened?
    3. What-If Scenarios - Different weights/parameters
    4. Guard Effectiveness - Which guards help/hurt?
    5. Strategy Performance - Which strategies work best?
    6. Feedback Loop - Directly improve signal generation
    """
    
    def __init__(self):
        self.signal_bus = get_signal_bus()
        self.shadow_engine = get_shadow_engine()
        self.analytics = AnalyticsReportGenerator()
        self.learning_controller = ContinuousLearningController()
        
        self.learnings_path = Path(PathRegistry.get_path("feature_store", "enhanced_learnings.json"))
        self.learnings_path.parent.mkdir(parents=True, exist_ok=True)
    
    def run_learning_cycle(self, hours: int = 24) -> Dict[str, Any]:
        """
        Run complete learning cycle.
        
        Reviews:
        1. Blocked trades and opportunity cost
        2. Missed opportunities
        3. Shadow performance (what-if)
        4. Guard effectiveness
        5. Strategy performance
        6. Generates feedback for signal generation
        """
        print("\n" + "="*80)
        print("🧠 ENHANCED LEARNING ENGINE - FULL REVIEW")
        print("="*80)
        
        learnings = {
            "generated_at": datetime.utcnow().isoformat() + 'Z',
            "period_hours": hours,
            "blocked_analysis": self._analyze_blocked_trades(hours),
            "missed_opportunities": self._analyze_missed_opportunities(hours),
            "what_if_scenarios": self._run_what_if_scenarios(hours),
            "guard_effectiveness": self._evaluate_guard_effectiveness(hours),
            "strategy_performance": self._analyze_strategy_performance(hours),
            "feedback": self._generate_feedback(hours)
        }
        
        # Save learnings
        self._save_learnings(learnings)
        
        # Apply feedback
        self._apply_feedback(learnings["feedback"])
        
        return learnings
    
    def _analyze_blocked_trades(self, hours: int) -> Dict[str, Any]:
        """Analyze blocked trades and calculate opportunity cost"""
        print("\n📊 Analyzing Blocked Trades...")
        
        # Get analytics report
        report = self.analytics.generate_full_report(hours)
        blocked_cost = report.get("blocked_opportunity_cost", {})
        
        return {
            "total_blocked": blocked_cost.get("total_blocked", 0),
            "profitable_blocked": blocked_cost.get("profitable_blocked", 0),
            "losing_blocked": blocked_cost.get("losing_blocked", 0),
            "missed_profit": blocked_cost.get("missed_profit", 0.0),
            "avoided_loss": blocked_cost.get("avoided_loss", 0.0),
            "net_opportunity_cost": blocked_cost.get("net_opportunity_cost", 0.0),
            "by_blocker": blocked_cost.get("by_blocker", {})
        }
    
    def _analyze_missed_opportunities(self, hours: int) -> Dict[str, Any]:
        """Analyze missed opportunities (signals that expired before execution)"""
        print("\n🔍 Analyzing Missed Opportunities...")
        
        cutoff_ts = time.time() - (hours * 3600)
        
        # Get expired signals
        expired_signals = self.signal_bus.get_signals(state=None, since_ts=cutoff_ts)
        expired_signals = [s for s in expired_signals if s.get("state") == "expired"]
        
        # Check shadow outcomes for expired signals
        missed_profit = 0.0
        missed_count = 0
        
        for signal_data in expired_signals:
            signal_id = signal_data.get("signal_id")
            # Check if shadow trade exists for this signal
            shadow_perf = self.shadow_engine.get_shadow_performance(hours=hours*2)  # Look back further
            # This is simplified - in practice, would match signal_id to shadow outcomes
        
        return {
            "expired_signals": len(expired_signals),
            "missed_profit": missed_profit,
            "missed_count": missed_count
        }
    
    def _run_what_if_scenarios(self, hours: int) -> Dict[str, Any]:
        """
        Run what-if scenarios with different parameters.
        
        Examples:
        - What if Volatility Guard was disabled?
        - What if ROI threshold was 0.5% instead of 1%?
        - What if signal weights were different?
        """
        print("\n🔮 Running What-If Scenarios...")
        
        scenarios = {}
        
        # Scenario 1: What if Volatility Guard was disabled?
        scenarios["no_volatility_guard"] = self._what_if_no_guard("VolatilityGuard", hours)
        
        # Scenario 2: What if ROI threshold was lower?
        scenarios["lower_roi_threshold"] = self._what_if_parameter_change("roi_threshold", 0.005, hours)
        
        # Scenario 3: What if signal weights were optimized?
        scenarios["optimized_weights"] = self._what_if_weights_optimized(hours)
        
        return scenarios
    
    def _what_if_no_guard(self, guard_name: str, hours: int) -> Dict[str, Any]:
        """What-if: What if a specific guard was disabled?"""
        # Get all signals blocked by this guard
        cutoff_ts = time.time() - (hours * 3600)
        
        # Load decision events
        decision_log_path = Path(PathRegistry.get_path("logs", "signal_decisions.jsonl"))
        blocked_by_guard = []
        
        if decision_log_path.exists():
            try:
                with open(decision_log_path, 'r') as f:
                    for line in f:
                        try:
                            event = json.loads(line.strip())
                            if event.get("ts", 0) >= cutoff_ts:
                                if (event.get("decision") == "BLOCKED" and 
                                    event.get("blocker_component") == guard_name):
                                    blocked_by_guard.append(event)
                        except:
                            continue
            except Exception as e:
                print(f"⚠️ Error reading decisions: {e}")
        
        # Check shadow outcomes for these signals
        total_would_have_pnl = 0.0
        would_win = 0
        would_lose = 0
        
        for event in blocked_by_guard:
            signal_id = event.get("signal_id")
            # Match to shadow outcome
            # Simplified - would need to match signal_id to shadow outcomes
        
        return {
            "guard_name": guard_name,
            "signals_blocked": len(blocked_by_guard),
            "would_win": would_win,
            "would_lose": would_lose,
            "net_pnl_if_disabled": total_would_have_pnl
        }
    
    def _what_if_parameter_change(self, parameter: str, new_value: Any, hours: int) -> Dict[str, Any]:
        """What-if: What if a parameter was different?"""
        # This would require replaying signals with different parameters
        # For now, return placeholder
        return {
            "parameter": parameter,
            "new_value": new_value,
            "note": "Requires signal replay - not yet implemented"
        }
    
    def _what_if_weights_optimized(self, hours: int) -> Dict[str, Any]:
        """What-if: What if signal weights were optimized?"""
        # Use learning controller to get optimized weights
        state = self.learning_controller.get_learning_state()
        weights = state.get("weights", {})
        
        return {
            "current_weights": weights,
            "optimized_weights": weights,  # Would be calculated by optimizer
            "expected_improvement": 0.0  # Would be estimated
        }
    
    def _evaluate_guard_effectiveness(self, hours: int) -> Dict[str, Any]:
        """Evaluate effectiveness of each guard"""
        print("\n🛡️  Evaluating Guard Effectiveness...")
        
        report = self.analytics.generate_full_report(hours)
        guard_effectiveness = report.get("guard_effectiveness", {})
        
        # Categorize guards
        effective_guards = []
        ineffective_guards = []
        
        for guard, stats in guard_effectiveness.items():
            net = stats.get("missed_profit", 0) - stats.get("avoided_loss", 0)
            if net < 0:  # Saved more than lost
                effective_guards.append({
                    "guard": guard,
                    "net_saved": abs(net),
                    "stats": stats
                })
            else:  # Lost more than saved
                ineffective_guards.append({
                    "guard": guard,
                    "net_cost": net,
                    "stats": stats
                })
        
        return {
            "effective_guards": effective_guards,
            "ineffective_guards": ineffective_guards,
            "by_guard": guard_effectiveness
        }
    
    def _analyze_strategy_performance(self, hours: int) -> Dict[str, Any]:
        """Analyze performance by strategy"""
        print("\n🏆 Analyzing Strategy Performance...")
        
        report = self.analytics.generate_full_report(hours)
        strategy_leaderboard = report.get("strategy_leaderboard", {})
        
        # Sort by performance
        sorted_strategies = sorted(
            strategy_leaderboard.items(),
            key=lambda x: x[1].get("total_pnl", 0),
            reverse=True
        )
        
        return {
            "leaderboard": dict(sorted_strategies),
            "top_strategy": sorted_strategies[0][0] if sorted_strategies else None,
            "worst_strategy": sorted_strategies[-1][0] if sorted_strategies else None
        }
    
    def _generate_feedback(self, hours: int) -> Dict[str, Any]:
        """Generate feedback for signal generation"""
        print("\n🔄 Generating Feedback...")
        
        feedback = {
            "guard_adjustments": {},
            "weight_adjustments": {},
            "threshold_adjustments": {},
            "strategy_recommendations": {}
        }
        
        # Analyze guard effectiveness
        guard_effectiveness = self._evaluate_guard_effectiveness(hours)
        
        # Recommend disabling ineffective guards
        for guard_info in guard_effectiveness.get("ineffective_guards", []):
            guard = guard_info["guard"]
            feedback["guard_adjustments"][guard] = {
                "action": "consider_disable",
                "reason": f"Net cost: ${guard_info['net_cost']:.2f}",
                "cost": guard_info["net_cost"]
            }
        
        # Get weight adjustments from learning controller
        state = self.learning_controller.get_learning_state()
        weight_adjustments = state.get("adjustments", {}).get("weights", {})
        feedback["weight_adjustments"] = weight_adjustments
        
        # Strategy recommendations
        strategy_perf = self._analyze_strategy_performance(hours)
        top_strategy = strategy_perf.get("top_strategy")
        if top_strategy:
            feedback["strategy_recommendations"] = {
                "increase_weight": top_strategy,
                "reason": "Top performing strategy"
            }
        
        return feedback
    
    def _apply_feedback(self, feedback: Dict[str, Any]):
        """Apply feedback to system"""
        print("\n✅ Applying Feedback...")
        
        # Apply guard adjustments
        guard_adjustments = feedback.get("guard_adjustments", {})
        for guard, adjustment in guard_adjustments.items():
            action = adjustment.get("action")
            if action == "consider_disable":
                print(f"   ⚠️ Consider disabling {guard}: {adjustment.get('reason')}")
        
        # Apply weight adjustments (via learning controller)
        weight_adjustments = feedback.get("weight_adjustments", {})
        if weight_adjustments:
            print(f"   ⚖️ Applying weight adjustments: {len(weight_adjustments)} signals")
            # Learning controller handles this
        
        # Apply strategy recommendations
        strategy_recs = feedback.get("strategy_recommendations", {})
        if strategy_recs:
            print(f"   🎯 Strategy recommendation: {strategy_recs}")
    
    def _save_learnings(self, learnings: Dict[str, Any]):
        """Save learnings to file"""
        try:
            # Load existing learnings
            existing = {}
            if self.learnings_path.exists():
                try:
                    existing = json.loads(self.learnings_path.read_text())
                except:
                    pass
            
            # Append new learning
            if "history" not in existing:
                existing["history"] = []
            
            existing["history"].append(learnings)
            existing["latest"] = learnings
            
            # Keep last 30 days
            if len(existing["history"]) > 30:
                existing["history"] = existing["history"][-30:]
            
            # Save
            self.learnings_path.write_text(json.dumps(existing, indent=2, default=str))
            print(f"\n💾 Learnings saved to {self.learnings_path}")
        except Exception as e:
            print(f"⚠️ Failed to save learnings: {e}")


# Global singleton
_enhanced_learning_engine_instance = None


def get_enhanced_learning_engine() -> EnhancedLearningEngine:
    """Get global EnhancedLearningEngine instance"""
    global _enhanced_learning_engine_instance
    
    if _enhanced_learning_engine_instance is None:
        _enhanced_learning_engine_instance = EnhancedLearningEngine()
    return _enhanced_learning_engine_instance

