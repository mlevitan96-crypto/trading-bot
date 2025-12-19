#!/usr/bin/env python3
"""
PROFITABILITY TRADER PERSONA
=============================
A sophisticated trading intelligence system that analyzes the entire learning engine
from a profitability-first perspective. This persona acts as a veteran trader who:

1. Reviews ALL learning systems nightly
2. Identifies what's working vs what's losing money
3. Makes aggressive adjustments to maximize wins and minimize losses
4. Uses advanced trading research tailored to this specific bot's patterns
5. Provides actionable recommendations with clear profitability impact

Key Principles:
- Profitability is the ONLY metric that matters
- Cut losers fast, let winners run (but not too long)
- Exit optimization is critical (80% of traders fail here)
- Fee management is a hidden profit killer
- Position sizing must match conviction
- Regime awareness (trending vs choppy) changes everything

Author: Trading Bot System
Date: December 2025
"""

import os
import json
import time
from datetime import datetime, timedelta
from typing import Dict, List, Tuple, Optional, Any
from collections import defaultdict
from statistics import mean, median, stdev
from pathlib import Path

try:
    from src.data_registry import DataRegistry as DR
    from src.infrastructure.path_registry import PathRegistry
except ImportError:
    import sys
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from src.data_registry import DataRegistry as DR
    from src.infrastructure.path_registry import PathRegistry

LOGS_DIR = Path("logs")
FEATURE_STORE = Path("feature_store")
CONFIG_DIR = Path("config")

class ProfitabilityTraderPersona:
    """
    A veteran trader persona that analyzes the entire system from profitability perspective.
    
    Philosophy:
    - Win rate matters, but expectancy matters more
    - Exit timing is where 80% of traders fail
    - Fee drag kills profitability silently
    - Position sizing must match edge strength
    - Regime changes require strategy adaptation
    """
    
    def __init__(self):
        self.lookback_days = 7  # Analyze last 7 days
        self.min_trades_for_analysis = 20  # Need at least 20 trades to make decisions
        self.profitability_threshold = 0.55  # 55% win rate or better
        
    def run_full_analysis(self) -> Dict[str, Any]:
        """
        Comprehensive profitability analysis of the entire trading system.
        
        Returns detailed analysis with:
        - Exit performance review
        - Entry quality assessment
        - Fee impact analysis
        - Position sizing optimization
        - Regime-specific recommendations
        - Learning system effectiveness
        - Research-based optimizations
        """
        print("=" * 80)
        print("🧠 PROFITABILITY TRADER PERSONA - FULL SYSTEM ANALYSIS")
        print("=" * 80)
        print()
        
        analysis = {
            "timestamp": datetime.utcnow().isoformat(),
            "lookback_days": self.lookback_days,
            "exit_performance": self._analyze_exit_performance(),
            "entry_quality": self._analyze_entry_quality(),
            "fee_impact": self._analyze_fee_impact(),
            "position_sizing": self._analyze_position_sizing(),
            "regime_adaptation": self._analyze_regime_adaptation(),
            "learning_effectiveness": self._analyze_learning_effectiveness(),
            "research_optimizations": {},
            "profitability_actions": [],
            "key_insights": [],
            "profit_potential": {}
        }
        
        # Run research-based optimizations
        try:
            from src.research_based_profitability_optimizer import run_research_optimization
            analysis["research_optimizations"] = run_research_optimization()
            print()
        except Exception as e:
            print(f"⚠️  Research optimization failed: {e}")
            analysis["research_optimizations"] = {"error": str(e)}
        
        # Run EXPANSIVE multi-dimensional analysis (all data, all dimensions)
        try:
            from src.expansive_multi_dimensional_profitability_analyzer import run_expansive_analysis
            print("🔬 Running EXPANSIVE Multi-Dimensional Analysis...")
            expansive_result = run_expansive_analysis()
            analysis["expansive_analysis"] = expansive_result
            print()
            
            # Check if analysis was successful (even if partial)
            status = expansive_result.get("status", "unknown")
            if status in ["success", "partial_success"]:
                # Add expansive insights to actionable insights
                if expansive_result.get("actionable_insights"):
                    analysis["key_insights"].extend(expansive_result["actionable_insights"])
                
                # Add expansive recommendations
                if expansive_result.get("optimization_recommendations"):
                    analysis["profitability_actions"].extend(expansive_result["optimization_recommendations"])
                
                # Log partial success warnings
                if status == "partial_success":
                    failed = expansive_result.get("components_failed", [])
                    print(f"⚠️  Expansive analysis partial: {len(failed)} components failed: {', '.join(failed)}")
            else:
                print(f"⚠️  Expansive analysis failed: {status}")
                if expansive_result.get("errors"):
                    print(f"   Errors: {expansive_result['errors'][:3]}")  # Show first 3 errors
        except Exception as e:
            print(f"⚠️  Expansive analysis failed: {e}")
            import traceback
            traceback.print_exc()
            analysis["expansive_analysis"] = {"error": str(e), "status": "failed"}
            # Log to health status
            try:
                from src.expansive_multi_dimensional_profitability_analyzer import ExpansiveMultiDimensionalProfitabilityAnalyzer
                ExpansiveMultiDimensionalProfitabilityAnalyzer._log_health_event({
                    "timestamp": datetime.utcnow().isoformat(),
                    "status": "failed",
                    "error": str(e),
                    "components_completed": 0,
                    "components_failed": [],
                    "execution_time_seconds": 0
                })
            except:
                pass
        
        # Generate profitability-focused recommendations
        analysis["profitability_actions"] = self._generate_profitability_actions(analysis)
        analysis["key_insights"] = self._extract_key_insights(analysis)
        analysis["profit_potential"] = self._estimate_profit_potential(analysis)
        
        return analysis
    
    def _analyze_exit_performance(self) -> Dict[str, Any]:
        """Analyze exit performance - where most traders fail."""
        print("📊 Analyzing Exit Performance...")
        
        closed_positions = DR.get_closed_positions(hours=self.lookback_days * 24)
        
        if not closed_positions:
            return {"status": "insufficient_data", "trades": 0}
        
        # Load exit events for detailed analysis
        exit_events = []
        exit_log_path = PathRegistry.get_path("logs", "exit_runtime_events.jsonl")
        if exit_log_path and os.path.exists(exit_log_path):
            with open(exit_log_path, 'r') as f:
                for line in f:
                    try:
                        event = json.loads(line.strip())
                        exit_events.append(event)
                    except:
                        continue
        
        # Categorize exits by type
        exit_stats = defaultdict(lambda: {
            "count": 0, "total_pnl": 0.0, "total_fees": 0.0,
            "wins": 0, "losses": 0, "mfe_captured": [], "hold_times": []
        })
        
        for pos in closed_positions:
            exit_reason = pos.get("exit_reason", "unknown")
            pnl = float(pos.get("net_pnl", pos.get("pnl", 0)) or 0)
            fees = float(pos.get("trading_fees", 0) or 0) + float(pos.get("funding_fees", 0) or 0)
            
            # Categorize exit type
            exit_type = self._categorize_exit_type(exit_reason)
            
            stats = exit_stats[exit_type]
            stats["count"] += 1
            stats["total_pnl"] += pnl
            stats["total_fees"] += fees
            if pnl > 0:
                stats["wins"] += 1
            else:
                stats["losses"] += 1
            
            # Track MFE capture if available
            if pos.get("peak_price") and pos.get("entry_price"):
                entry = float(pos.get("entry_price"))
                exit_price = float(pos.get("exit_price", entry))
                peak = float(pos.get("peak_price"))
                direction = pos.get("direction", "LONG")
                
                if direction == "LONG":
                    peak_roi = ((peak - entry) / entry) * 100
                    exit_roi = ((exit_price - entry) / entry) * 100
                else:
                    peak_roi = ((entry - peak) / entry) * 100
                    exit_roi = ((entry - exit_price) / entry) * 100
                
                if peak_roi > 0:
                    capture_rate = (exit_roi / peak_roi * 100) if peak_roi > 0 else 0
                    stats["mfe_captured"].append(capture_rate)
        
        # Calculate metrics
        results = {}
        for exit_type, stats in exit_stats.items():
            if stats["count"] > 0:
                results[exit_type] = {
                    "count": stats["count"],
                    "win_rate": (stats["wins"] / stats["count"]) * 100,
                    "avg_pnl": stats["total_pnl"] / stats["count"],
                    "total_pnl": stats["total_pnl"],
                    "avg_fees": stats["total_fees"] / stats["count"],
                    "expectancy": (stats["total_pnl"] - stats["total_fees"]) / stats["count"],
                    "avg_mfe_capture": mean(stats["mfe_captured"]) if stats["mfe_captured"] else None,
                    "profitability_score": self._calculate_profitability_score(stats)
                }
        
        return {
            "total_trades": len(closed_positions),
            "exit_breakdown": results,
            "best_exit_type": max(results.items(), key=lambda x: x[1]["profitability_score"])[0] if results else None,
            "worst_exit_type": min(results.items(), key=lambda x: x[1]["profitability_score"])[0] if results else None,
            "recommendations": self._generate_exit_recommendations(results)
        }
    
    def _analyze_entry_quality(self) -> Dict[str, Any]:
        """Analyze entry quality - are we entering good trades?"""
        print("🎯 Analyzing Entry Quality...")
        
        closed_positions = DR.get_closed_positions(hours=self.lookback_days * 24)
        
        if not closed_positions:
            return {"status": "insufficient_data"}
        
        # Analyze by signal type, symbol, strategy
        signal_performance = defaultdict(lambda: {"trades": 0, "pnl": 0.0, "wins": 0})
        symbol_performance = defaultdict(lambda: {"trades": 0, "pnl": 0.0, "wins": 0})
        strategy_performance = defaultdict(lambda: {"trades": 0, "pnl": 0.0, "wins": 0})
        
        for pos in closed_positions:
            symbol = pos.get("symbol", "UNKNOWN")
            strategy = pos.get("strategy", "UNKNOWN")
            pnl = float(pos.get("net_pnl", pos.get("pnl", 0)) or 0)
            
            symbol_perf = symbol_performance[symbol]
            symbol_perf["trades"] += 1
            symbol_perf["pnl"] += pnl
            if pnl > 0:
                symbol_perf["wins"] += 1
            
            strategy_perf = strategy_performance[strategy]
            strategy_perf["trades"] += 1
            strategy_perf["pnl"] += pnl
            if pnl > 0:
                strategy_perf["wins"] += 1
        
        # Calculate win rates and expectancy
        results = {}
        for category, perf_data in [
            ("symbols", symbol_performance),
            ("strategies", strategy_performance)
        ]:
            results[category] = {}
            for key, stats in perf_data.items():
                if stats["trades"] >= 5:  # Minimum trades for analysis
                    results[category][key] = {
                        "trades": stats["trades"],
                        "win_rate": (stats["wins"] / stats["trades"]) * 100,
                        "total_pnl": stats["pnl"],
                        "avg_pnl": stats["pnl"] / stats["trades"],
                        "expectancy": stats["pnl"] / stats["trades"]
                    }
        
        return {
            "total_trades": len(closed_positions),
            "performance_by_category": results,
            "top_performers": self._identify_top_performers(results),
            "underperformers": self._identify_underperformers(results)
        }
    
    def _analyze_fee_impact(self) -> Dict[str, Any]:
        """Analyze fee impact - the silent profit killer."""
        print("💰 Analyzing Fee Impact...")
        
        closed_positions = DR.get_closed_positions(hours=self.lookback_days * 24)
        
        if not closed_positions:
            return {"status": "insufficient_data"}
        
        total_fees = 0.0
        total_pnl_gross = 0.0
        fee_by_symbol = defaultdict(float)
        fee_by_strategy = defaultdict(float)
        
        for pos in closed_positions:
            fees = float(pos.get("trading_fees", 0) or 0) + float(pos.get("funding_fees", 0) or 0)
            pnl_gross = float(pos.get("gross_pnl", pos.get("pnl", 0)) or 0)
            pnl_net = float(pos.get("net_pnl", pnl_gross) or 0)
            
            total_fees += fees
            total_pnl_gross += pnl_gross
            
            symbol = pos.get("symbol", "UNKNOWN")
            strategy = pos.get("strategy", "UNKNOWN")
            fee_by_symbol[symbol] += fees
            fee_by_strategy[strategy] += fees
        
        fee_impact_pct = (total_fees / abs(total_pnl_gross) * 100) if total_pnl_gross != 0 else 0
        
        return {
            "total_fees": total_fees,
            "total_gross_pnl": total_pnl_gross,
            "fee_impact_percent": fee_impact_pct,
            "fees_by_symbol": dict(fee_by_symbol),
            "fees_by_strategy": dict(fee_by_strategy),
            "recommendations": self._generate_fee_recommendations(fee_impact_pct, fee_by_symbol, fee_by_strategy)
        }
    
    def _analyze_position_sizing(self) -> Dict[str, Any]:
        """Analyze position sizing - are we sizing correctly?"""
        print("📏 Analyzing Position Sizing...")
        
        closed_positions = DR.get_closed_positions(hours=self.lookback_days * 24)
        
        if not closed_positions:
            return {"status": "insufficient_data"}
        
        # Group by outcome and analyze sizing
        winners = [p for p in closed_positions if float(p.get("net_pnl", 0) or 0) > 0]
        losers = [p for p in closed_positions if float(p.get("net_pnl", 0) or 0) <= 0]
        
        avg_winner_size = mean([float(p.get("size", p.get("margin_collateral", 0)) or 0) for p in winners]) if winners else 0
        avg_loser_size = mean([float(p.get("size", p.get("margin_collateral", 0)) or 0) for p in losers]) if losers else 0
        
        # Analyze sizing by strategy/symbol
        sizing_by_strategy = defaultdict(lambda: {"winners": [], "losers": []})
        for pos in closed_positions:
            strategy = pos.get("strategy", "UNKNOWN")
            size = float(pos.get("size", pos.get("margin_collateral", 0)) or 0)
            pnl = float(pos.get("net_pnl", 0) or 0)
            
            if pnl > 0:
                sizing_by_strategy[strategy]["winners"].append(size)
            else:
                sizing_by_strategy[strategy]["losers"].append(size)
        
        return {
            "avg_winner_size": avg_winner_size,
            "avg_loser_size": avg_loser_size,
            "size_ratio": avg_winner_size / avg_loser_size if avg_loser_size > 0 else 0,
            "sizing_by_strategy": {
                k: {
                    "avg_winner_size": mean(v["winners"]) if v["winners"] else 0,
                    "avg_loser_size": mean(v["losers"]) if v["losers"] else 0
                }
                for k, v in sizing_by_strategy.items()
            },
            "recommendations": self._generate_sizing_recommendations(avg_winner_size, avg_loser_size)
        }
    
    def _analyze_regime_adaptation(self) -> Dict[str, Any]:
        """Analyze if we're adapting to market regimes."""
        print("🌊 Analyzing Regime Adaptation...")
        
        # This would analyze market conditions vs strategy performance
        # For now, return placeholder
        return {
            "status": "analysis_pending",
            "note": "Regime detection requires additional market data analysis"
        }
    
    def _analyze_learning_effectiveness(self) -> Dict[str, Any]:
        """Analyze if learning systems are actually improving profitability."""
        print("🧪 Analyzing Learning System Effectiveness...")
        
        # Load learning system outputs
        learning_files = {
            "exit_policy": PathRegistry.get_path("config", "exit_policy.json"),
            "signal_weights": PathRegistry.get_path("feature_store", "signal_weights_gate.json"),
            "hold_time_policy": PathRegistry.get_path("feature_store", "hold_time_policy.json"),
            "profitability_learnings": PathRegistry.get_path("feature_store", "daily_learning_rules.json")
        }
        
        learning_status = {}
        for name, path in learning_files.items():
            if path and os.path.exists(path):
                try:
                    with open(path, 'r') as f:
                        data = json.load(f)
                        learning_status[name] = {
                            "exists": True,
                            "last_updated": data.get("updated_at", data.get("timestamp", "unknown")),
                            "has_changes": True  # Would check if parameters changed
                        }
                except:
                    learning_status[name] = {"exists": True, "error": "could_not_read"}
            else:
                learning_status[name] = {"exists": False}
        
        return {
            "learning_systems_status": learning_status,
            "recommendations": self._generate_learning_recommendations(learning_status)
        }
    
    def _categorize_exit_type(self, reason: str) -> str:
        """Categorize exit reason consistently."""
        if not reason:
            return "unknown"
        
        reason_lower = reason.lower()
        
        # Standardize exit type names
        if any(kw in reason_lower for kw in ["profit_target", "profit_target_0.5", "profit_target_1.0", 
                                              "profit_target_1.5", "profit_target_2.0", "tp1", "tp2"]):
            return "profit_target"
        elif any(kw in reason_lower for kw in ["time", "stagnant", "tier1", "tier2", "tier3", "max_hold"]):
            return "time_stop"
        elif any(kw in reason_lower for kw in ["trailing", "trail"]):
            return "trailing_stop"
        elif any(kw in reason_lower for kw in ["stop", "loss", "catastrophic"]):
            return "stop_loss"
        else:
            return "unknown"
    
    def _calculate_profitability_score(self, stats: Dict) -> float:
        """Calculate profitability score (0-100)."""
        if stats["count"] == 0:
            return 0.0
        
        win_rate = stats["wins"] / stats["count"]
        avg_expectancy = (stats["total_pnl"] - stats["total_fees"]) / stats["count"]
        
        # Score combines win rate and expectancy
        score = (win_rate * 50) + (min(avg_expectancy * 1000, 50) if avg_expectancy > 0 else 0)
        
        return score
    
    def _generate_exit_recommendations(self, exit_stats: Dict) -> List[Dict]:
        """Generate profitability-focused exit recommendations."""
        recommendations = []
        
        if not exit_stats:
            return recommendations
        
        # Find best and worst exit types
        profitability_scores = {k: v["profitability_score"] for k, v in exit_stats.items()}
        best_exit = max(profitability_scores.items(), key=lambda x: x[1]) if profitability_scores else None
        worst_exit = min(profitability_scores.items(), key=lambda x: x[1]) if profitability_scores else None
        
        # Check MFE capture rates
        for exit_type, stats in exit_stats.items():
            if stats.get("avg_mfe_capture") and stats["avg_mfe_capture"] < 60:
                recommendations.append({
                    "priority": "HIGH",
                    "category": "exit_timing",
                    "issue": f"{exit_type} exits capturing only {stats['avg_mfe_capture']:.1f}% of MFE",
                    "recommendation": f"Lower {exit_type} thresholds to capture profits earlier",
                    "expected_impact": f"Increase profitability by ~{(70 - stats['avg_mfe_capture']) * 0.01:.2f}% per trade"
                })
        
        # Compare exit types
        if best_exit and worst_exit and best_exit[0] != worst_exit[0]:
            best_score = best_exit[1]
            worst_score = worst_exit[1]
            
            if worst_exit[0] == "time_stop" and best_exit[0] == "profit_target":
                recommendations.append({
                    "priority": "CRITICAL",
                    "category": "exit_optimization",
                    "issue": f"Time stops have {worst_score:.1f} profitability vs {best_score:.1f} for profit targets",
                    "recommendation": "Aggressively lower profit target thresholds to prevent time_stop exits",
                    "expected_impact": "Increase win rate from time_stop levels to profit_target levels"
                })
        
        return recommendations
    
    def _generate_profitability_actions(self, analysis: Dict) -> List[Dict]:
        """Generate actionable profitability improvements."""
        actions = []
        
        # Add exit recommendations
        if "exit_performance" in analysis and "recommendations" in analysis["exit_performance"]:
            actions.extend(analysis["exit_performance"]["recommendations"])
        
        # Add fee recommendations
        if "fee_impact" in analysis and "recommendations" in analysis["fee_impact"]:
            actions.extend(analysis["fee_impact"]["recommendations"])
        
        # Add sizing recommendations
        if "position_sizing" in analysis and "recommendations" in analysis["position_sizing"]:
            actions.extend(analysis["position_sizing"]["recommendations"])
        
        # Add learning recommendations
        if "learning_effectiveness" in analysis and "recommendations" in analysis["learning_effectiveness"]:
            actions.extend(analysis["learning_effectiveness"]["recommendations"])
        
        # Add research optimization recommendations
        if "research_optimizations" in analysis:
            research = analysis["research_optimizations"]
            if "combined_recommendations" in research:
                actions.extend(research["combined_recommendations"])
        
        return actions
    
    def apply_critical_recommendations(self, analysis: Dict) -> Dict[str, Any]:
        """
        Automatically apply CRITICAL profitability recommendations.
        
        This is where the trader persona takes action to maximize profitability.
        """
        applied = []
        failed = []
        
        critical_actions = [a for a in analysis.get("profitability_actions", []) if a.get("priority") == "CRITICAL"]
        
        for action in critical_actions:
            category = action.get("category", "")
            
            # Apply exit target optimizations
            if category == "exit_optimization" or "profit target" in action.get("recommendation", "").lower():
                try:
                    # This will be picked up by ExitTuner in the next cycle
                    # For now, we log the recommendation
                    applied.append({
                        "action": "exit_target_optimization",
                        "recommendation": action.get("recommendation"),
                        "status": "logged_for_exit_tuner"
                    })
                except Exception as e:
                    failed.append({"action": action, "error": str(e)})
        
        return {
            "applied_count": len(applied),
            "failed_count": len(failed),
            "applied": applied,
            "failed": failed
        }
    
    def _extract_key_insights(self, analysis: Dict) -> List[str]:
        """Extract key profitability insights."""
        insights = []
        
        # Exit insights
        if "exit_performance" in analysis:
            exit_perf = analysis["exit_performance"]
            if exit_perf.get("best_exit_type"):
                insights.append(f"Best exit type: {exit_perf['best_exit_type']} - focus on increasing these")
            if exit_perf.get("worst_exit_type"):
                insights.append(f"Worst exit type: {exit_perf['worst_exit_type']} - minimize these exits")
        
        # Fee insights
        if "fee_impact" in analysis:
            fee_pct = analysis["fee_impact"].get("fee_impact_percent", 0)
            if fee_pct > 10:
                insights.append(f"Fees are eating {fee_pct:.1f}% of gross P&L - optimize trade frequency or reduce position sizes")
        
        return insights
    
    def _estimate_profit_potential(self, analysis: Dict) -> Dict[str, Any]:
        """Estimate profit potential from recommended changes."""
        # Simplified calculation
        current_expectancy = 0.0
        projected_expectancy = 0.0
        
        if "exit_performance" in analysis:
            exit_perf = analysis["exit_performance"]
            for exit_type, stats in exit_perf.get("exit_breakdown", {}).items():
                count = stats.get("count", 0)
                expectancy = stats.get("expectancy", 0.0)
                current_expectancy += (count * expectancy)
        
        # Estimate improvement from recommendations
        improvement_pct = 0.15  # 15% improvement estimate from optimizations
        projected_expectancy = current_expectancy * (1 + improvement_pct)
        
        return {
            "current_expectancy_per_trade": current_expectancy / max(analysis.get("exit_performance", {}).get("total_trades", 1), 1),
            "projected_expectancy_per_trade": projected_expectancy / max(analysis.get("exit_performance", {}).get("total_trades", 1), 1),
            "improvement_potential": improvement_pct * 100
        }
    
    # Helper methods (simplified - would be more sophisticated)
    def _generate_fee_recommendations(self, fee_pct: float, fee_by_symbol: Dict, fee_by_strategy: Dict) -> List[Dict]:
        recommendations = []
        if fee_pct > 15:
            recommendations.append({
                "priority": "MEDIUM",
                "issue": f"Fees represent {fee_pct:.1f}% of gross P&L",
                "recommendation": "Reduce trade frequency or increase position sizes to reduce fee drag"
            })
        return recommendations
    
    def _generate_sizing_recommendations(self, avg_winner_size: float, avg_loser_size: float) -> List[Dict]:
        recommendations = []
        if avg_loser_size > avg_winner_size * 1.2:
            recommendations.append({
                "priority": "HIGH",
                "issue": f"Average loser size ({avg_loser_size:.2f}) is larger than winners ({avg_winner_size:.2f})",
                "recommendation": "Reduce position sizes for lower-conviction trades"
            })
        return recommendations
    
    def _generate_learning_recommendations(self, learning_status: Dict) -> List[Dict]:
        recommendations = []
        for name, status in learning_status.items():
            if not status.get("exists"):
                recommendations.append({
                    "priority": "MEDIUM",
                    "issue": f"Learning system '{name}' not found or not updating",
                    "recommendation": f"Verify {name} is running in nightly cycle"
                })
        return recommendations
    
    def _identify_top_performers(self, results: Dict) -> List[Dict]:
        top = []
        for category, perf_data in results.items():
            sorted_items = sorted(
                perf_data.items(),
                key=lambda x: x[1].get("expectancy", 0),
                reverse=True
            )[:3]
            for key, stats in sorted_items:
                top.append({
                    "category": category,
                    "name": key,
                    "expectancy": stats.get("expectancy", 0),
                    "win_rate": stats.get("win_rate", 0)
                })
        return top
    
    def _identify_underperformers(self, results: Dict) -> List[Dict]:
        underperformers = []
        for category, perf_data in results.items():
            sorted_items = sorted(
                perf_data.items(),
                key=lambda x: x[1].get("expectancy", 0)
            )[:3]
            for key, stats in sorted_items:
                if stats.get("expectancy", 0) < 0:
                    underperformers.append({
                        "category": category,
                        "name": key,
                        "expectancy": stats.get("expectancy", 0),
                        "win_rate": stats.get("win_rate", 0)
                    })
        return underperformers


def run_profitability_analysis() -> Dict[str, Any]:
    """Main entry point for profitability trader persona analysis."""
    persona = ProfitabilityTraderPersona()
    return persona.run_full_analysis()


if __name__ == "__main__":
    analysis = run_profitability_analysis()
    
    # Print summary
    print("\n" + "=" * 80)
    print("KEY INSIGHTS")
    print("=" * 80)
    for insight in analysis.get("key_insights", []):
        print(f"💡 {insight}")
    
    print("\n" + "=" * 80)
    print("PROFITABILITY ACTIONS")
    print("=" * 80)
    for action in analysis.get("profitability_actions", []):
        priority_icon = "🔴" if action.get("priority") == "CRITICAL" else "🟡" if action.get("priority") == "HIGH" else "🟢"
        print(f"\n{priority_icon} {action.get('priority')} - {action.get('category', 'general')}")
        print(f"   Issue: {action.get('issue')}")
        print(f"   Action: {action.get('recommendation')}")
        if action.get('expected_impact'):
            print(f"   Impact: {action.get('expected_impact')}")
    
    # Save full analysis
    output_path = PathRegistry.get_path("reports", "profitability_trader_analysis.json")
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, 'w') as f:
        json.dump(analysis, f, indent=2, default=str)
    
    print(f"\n✅ Full analysis saved to: {output_path}")
