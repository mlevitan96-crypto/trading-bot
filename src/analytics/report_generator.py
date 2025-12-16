#!/usr/bin/env python3
"""
Analytics Report Generator
==========================
Generates comprehensive analytics reports from signal bus and shadow execution data.

Answers key questions:
- Blocked Opportunity Cost: How much money did we miss by blocking?
- Signal Decay: How long between signal generation and execution?
- Strategy Leaderboard: Which strategies are most profitable?
- Guard Effectiveness: Which guards save/lose money?
"""

import json
import time
from pathlib import Path
from typing import Dict, List, Optional, Any
from datetime import datetime, timedelta
from collections import defaultdict
import pandas as pd

from src.infrastructure.path_registry import PathRegistry
from src.signal_bus import get_signal_bus
from src.shadow_execution_engine import get_shadow_engine


class AnalyticsReportGenerator:
    """Generates analytics reports from event data"""
    
    def __init__(self):
        self.signal_bus = get_signal_bus()
        self.shadow_engine = get_shadow_engine()
        self.shadow_outcomes_path = Path(PathRegistry.get_path("logs", "shadow_trade_outcomes.jsonl"))
    
    def generate_full_report(self, hours: int = 24) -> Dict[str, Any]:
        """Generate comprehensive analytics report"""
        print("\n" + "="*80)
        print("📊 ANALYTICS REPORT")
        print("="*80)
        
        report = {
            "generated_at": datetime.utcnow().isoformat() + 'Z',
            "period_hours": hours,
            "blocked_opportunity_cost": self._calculate_blocked_opportunity_cost(hours),
            "signal_decay": self._calculate_signal_decay(hours),
            "strategy_leaderboard": self._generate_strategy_leaderboard(hours),
            "guard_effectiveness": self._analyze_guard_effectiveness(hours),
            "shadow_performance": self.shadow_engine.get_shadow_performance(hours)
        }
        
        self._print_report(report)
        return report
    
    def _calculate_blocked_opportunity_cost(self, hours: int) -> Dict[str, Any]:
        """Calculate potential P&L from blocked signals"""
        print("\n💰 BLOCKED OPPORTUNITY COST")
        print("-" * 80)
        
        cutoff_ts = time.time() - (hours * 3600)
        
        # Load shadow outcomes for blocked signals
        blocked_outcomes = []
        if self.shadow_outcomes_path.exists():
            try:
                with open(self.shadow_outcomes_path, 'r') as f:
                    for line in f:
                        try:
                            outcome = json.loads(line.strip())
                            if outcome.get("ts", 0) >= cutoff_ts:
                                if outcome.get("original_decision") == "BLOCKED":
                                    blocked_outcomes.append(outcome)
                        except:
                            continue
            except Exception as e:
                print(f"⚠️ Error reading shadow outcomes: {e}")
        
        if not blocked_outcomes:
            print("   No blocked signal outcomes found")
            return {
                "total_blocked": 0,
                "profitable_blocked": 0,
                "losing_blocked": 0,
                "missed_profit": 0.0,
                "avoided_loss": 0.0,
                "net_opportunity_cost": 0.0
            }
        
        profitable = [o for o in blocked_outcomes if o.get("was_profitable", False)]
        losing = [o for o in blocked_outcomes if not o.get("was_profitable", False)]
        
        missed_profit = sum(o.get("pnl", 0) for o in profitable)
        avoided_loss = abs(sum(o.get("pnl", 0) for o in losing))
        net_cost = missed_profit - avoided_loss
        
        print(f"   Total blocked signals analyzed: {len(blocked_outcomes)}")
        print(f"   Would have been profitable: {len(profitable)}")
        print(f"   Would have lost money: {len(losing)}")
        print(f"   Missed profit: ${missed_profit:.2f}")
        print(f"   Avoided loss: ${avoided_loss:.2f}")
        print(f"   Net opportunity cost: ${net_cost:.2f}")
        
        # By blocker component
        by_blocker = defaultdict(lambda: {"count": 0, "missed_profit": 0.0, "avoided_loss": 0.0})
        for outcome in blocked_outcomes:
            blocker = outcome.get("blocker_component", "Unknown")
            by_blocker[blocker]["count"] += 1
            pnl = outcome.get("pnl", 0)
            if pnl > 0:
                by_blocker[blocker]["missed_profit"] += pnl
            else:
                by_blocker[blocker]["avoided_loss"] += abs(pnl)
        
        print(f"\n   By Blocker Component:")
        for blocker, stats in sorted(by_blocker.items(), key=lambda x: x[1]["count"], reverse=True):
            net = stats["missed_profit"] - stats["avoided_loss"]
            print(f"      {blocker}: {stats['count']} blocked | "
                  f"Missed: ${stats['missed_profit']:.2f} | "
                  f"Avoided: ${stats['avoided_loss']:.2f} | "
                  f"Net: ${net:.2f}")
        
        return {
            "total_blocked": len(blocked_outcomes),
            "profitable_blocked": len(profitable),
            "losing_blocked": len(losing),
            "missed_profit": missed_profit,
            "avoided_loss": avoided_loss,
            "net_opportunity_cost": net_cost,
            "by_blocker": dict(by_blocker)
        }
    
    def _calculate_signal_decay(self, hours: int) -> Dict[str, Any]:
        """Calculate time between signal generation and execution"""
        print("\n⏱️  SIGNAL DECAY (Time to Execution)")
        print("-" * 80)
        
        cutoff_ts = time.time() - (hours * 3600)
        
        # Get all executed signals
        executed_signals = self.signal_bus.get_signals(state=None, since_ts=cutoff_ts)
        executed_signals = [s for s in executed_signals if s.get("state") == "executed"]
        
        if not executed_signals:
            print("   No executed signals found")
            return {
                "total_signals": 0,
                "avg_decay_seconds": 0.0,
                "median_decay_seconds": 0.0
            }
        
        decay_times = []
        for signal_data in executed_signals:
            created_ts = signal_data.get("ts", 0)
            last_change = signal_data.get("last_state_change", created_ts)
            decay = last_change - created_ts
            if decay > 0:
                decay_times.append(decay)
        
        if not decay_times:
            print("   No decay data available")
            return {
                "total_signals": len(executed_signals),
                "avg_decay_seconds": 0.0,
                "median_decay_seconds": 0.0
            }
        
        avg_decay = sum(decay_times) / len(decay_times)
        sorted_decays = sorted(decay_times)
        median_decay = sorted_decays[len(sorted_decays) // 2]
        
        print(f"   Total executed signals: {len(executed_signals)}")
        print(f"   Average decay: {avg_decay:.1f} seconds ({avg_decay/60:.1f} minutes)")
        print(f"   Median decay: {median_decay:.1f} seconds ({median_decay/60:.1f} minutes)")
        
        return {
            "total_signals": len(executed_signals),
            "avg_decay_seconds": avg_decay,
            "median_decay_seconds": median_decay,
            "min_decay_seconds": min(decay_times),
            "max_decay_seconds": max(decay_times)
        }
    
    def _generate_strategy_leaderboard(self, hours: int) -> Dict[str, Any]:
        """Generate strategy performance leaderboard"""
        print("\n🏆 STRATEGY LEADERBOARD")
        print("-" * 80)
        
        cutoff_ts = time.time() - (hours * 3600)
        
        # Load shadow outcomes
        outcomes = []
        if self.shadow_outcomes_path.exists():
            try:
                with open(self.shadow_outcomes_path, 'r') as f:
                    for line in f:
                        try:
                            outcome = json.loads(line.strip())
                            if outcome.get("ts", 0) >= cutoff_ts:
                                outcomes.append(outcome)
                        except:
                            continue
            except Exception as e:
                print(f"⚠️ Error reading outcomes: {e}")
        
        if not outcomes:
            print("   No strategy data available")
            return {}
        
        # Group by strategy (from signal metadata)
        by_strategy = defaultdict(lambda: {
            "trades": 0,
            "profitable": 0,
            "losing": 0,
            "total_pnl": 0.0,
            "avg_pnl_pct": 0.0
        })
        
        for outcome in outcomes:
            # Get strategy from signal
            signal_id = outcome.get("signal_id")
            signal_data = self.signal_bus.get_signal(signal_id)
            if signal_data:
                signal = signal_data.get("signal", {})
                metadata = signal.get("metadata", {})
                strategy = metadata.get("strategy_name") or signal.get("strategy") or "Unknown"
            else:
                strategy = "Unknown"
            
            by_strategy[strategy]["trades"] += 1
            pnl = outcome.get("pnl", 0)
            pnl_pct = outcome.get("pnl_pct", 0)
            by_strategy[strategy]["total_pnl"] += pnl
            by_strategy[strategy]["avg_pnl_pct"] += pnl_pct
            
            if outcome.get("was_profitable", False):
                by_strategy[strategy]["profitable"] += 1
            else:
                by_strategy[strategy]["losing"] += 1
        
        # Calculate win rates and averages
        for strategy, stats in by_strategy.items():
            if stats["trades"] > 0:
                stats["win_rate"] = stats["profitable"] / stats["trades"]
                stats["avg_pnl_pct"] = stats["avg_pnl_pct"] / stats["trades"]
        
        # Sort by total P&L
        sorted_strategies = sorted(by_strategy.items(), key=lambda x: x[1]["total_pnl"], reverse=True)
        
        print(f"   Top Strategies (by P&L):")
        for strategy, stats in sorted_strategies[:10]:
            print(f"      {strategy}: ${stats['total_pnl']:.2f} | "
                  f"{stats['trades']} trades | "
                  f"{stats['win_rate']*100:.1f}% WR | "
                  f"{stats['avg_pnl_pct']*100:.2f}% avg")
        
        return dict(by_strategy)
    
    def _analyze_guard_effectiveness(self, hours: int) -> Dict[str, Any]:
        """Analyze effectiveness of each guard/blocker"""
        print("\n🛡️  GUARD EFFECTIVENESS")
        print("-" * 80)
        
        cutoff_ts = time.time() - (hours * 3600)
        
        # Load shadow outcomes
        outcomes = []
        if self.shadow_outcomes_path.exists():
            try:
                with open(self.shadow_outcomes_path, 'r') as f:
                    for line in f:
                        try:
                            outcome = json.loads(line.strip())
                            if outcome.get("ts", 0) >= cutoff_ts:
                                outcomes.append(outcome)
                        except:
                            continue
            except Exception as e:
                print(f"⚠️ Error reading outcomes: {e}")
        
        # Group by blocker component
        by_blocker = defaultdict(lambda: {
            "blocked_count": 0,
            "would_win": 0,
            "would_lose": 0,
            "missed_profit": 0.0,
            "avoided_loss": 0.0
        })
        
        for outcome in outcomes:
            blocker = outcome.get("blocker_component", "Unknown")
            by_blocker[blocker]["blocked_count"] += 1
            
            pnl = outcome.get("pnl", 0)
            if outcome.get("was_profitable", False):
                by_blocker[blocker]["would_win"] += 1
                by_blocker[blocker]["missed_profit"] += pnl
            else:
                by_blocker[blocker]["would_lose"] += 1
                by_blocker[blocker]["avoided_loss"] += abs(pnl)
        
        print(f"   Guard Effectiveness:")
        for blocker, stats in sorted(by_blocker.items(), key=lambda x: x[1]["blocked_count"], reverse=True):
            net = stats["missed_profit"] - stats["avoided_loss"]
            effectiveness = "✅ Good" if net < 0 else "⚠️ Review"
            print(f"      {blocker}: {effectiveness}")
            print(f"         Blocked: {stats['blocked_count']} | "
                  f"Would win: {stats['would_win']} | "
                  f"Would lose: {stats['would_lose']}")
            print(f"         Missed profit: ${stats['missed_profit']:.2f} | "
                  f"Avoided loss: ${stats['avoided_loss']:.2f} | "
                  f"Net: ${net:.2f}")
        
        return dict(by_blocker)
    
    def _print_report(self, report: Dict):
        """Print formatted report summary"""
        print("\n" + "="*80)
        print("📊 REPORT SUMMARY")
        print("="*80)
        
        shadow = report.get("shadow_performance", {})
        print(f"\nShadow Performance:")
        print(f"   Total trades: {shadow.get('total_trades', 0)}")
        print(f"   Win rate: {shadow.get('win_rate', 0)*100:.1f}%")
        print(f"   Total P&L: ${shadow.get('total_pnl', 0):.2f}")
        
        blocked = report.get("blocked_opportunity_cost", {})
        print(f"\nBlocked Opportunity Cost:")
        print(f"   Net cost: ${blocked.get('net_opportunity_cost', 0):.2f}")
        
        decay = report.get("signal_decay", {})
        print(f"\nSignal Decay:")
        print(f"   Average: {decay.get('avg_decay_seconds', 0)/60:.1f} minutes")
        
        print("\n" + "="*80)


def generate_report(hours: int = 24) -> Dict[str, Any]:
    """Convenience function to generate report"""
    generator = AnalyticsReportGenerator()
    return generator.generate_full_report(hours)


if __name__ == "__main__":
    # Run report
    report = generate_report(hours=24)
    print("\n✅ Report generated")

