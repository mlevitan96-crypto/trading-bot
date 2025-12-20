#!/usr/bin/env python3
"""
COMPREHENSIVE PROFITABILITY ANALYSIS - MASSIVE DEEP DIVE
=========================================================
Uses ALL data sources to learn from everything:
- Executed trades (winners and losers)
- Blocked trades (what would have happened?)
- Missed opportunities (counterfactual learning)
- All signals (executed + blocked + skipped)
- Exit timing, entry timing, volume, every signal component
- Signal weight optimization opportunities

Focus: WINNING through learning and optimization, not blocking.
"""

import json
import os
import sys
from datetime import datetime, timedelta
from collections import defaultdict
from typing import Dict, List, Any, Tuple, Optional
import statistics
from pathlib import Path

# Add src to path
sys.path.insert(0, os.path.dirname(__file__))

# Try to import DataRegistry
try:
    from src.data_registry import DataRegistry as DR
    DR_AVAILABLE = True
except Exception as e:
    print(f"Warning: DataRegistry not available ({e}), using direct file access")
    DR_AVAILABLE = False
    DR = None


class ComprehensiveProfitabilityAnalysis:
    """Massive deep dive analysis using ALL data sources"""
    
    def __init__(self):
        self.trades = []  # Executed trades
        self.all_signals = []  # All signals (executed + blocked + skipped)
        self.blocked_signals = []  # Blocked signals
        self.missed_opportunities = []  # Missed opportunities
        self.counterfactual_outcomes = []  # Counterfactual learning
        self.enriched_decisions = []  # Enriched decision records
        self.signal_outcomes = []  # Signal outcome tracking
        self.learning_data = {}  # Learning system data
        
        self.analysis_results = {
            "timestamp": datetime.now().isoformat(),
            "data_summary": {},
            "signal_analysis": {},
            "timing_analysis": {},
            "volume_analysis": {},
            "weight_optimization": {},
            "winner_loser_patterns": {},
            "learning_insights": {},
            "recommendations": []
        }
    
    def load_all_data_sources(self):
        """Load EVERY data source available"""
        print("=" * 80)
        print("LOADING ALL DATA SOURCES")
        print("=" * 80)
        
        # 1. Executed trades
        print("\n[1] Loading executed trades...")
        if DR_AVAILABLE:
            try:
                # Try database first
                self.trades = DR.get_closed_trades_from_db(limit=10000)
                if self.trades:
                    print(f"   [OK] Loaded {len(self.trades)} trades from database")
                else:
                    # Try JSON fallback
                    self.trades = DR.get_closed_positions(hours=None)
                    if self.trades:
                        print(f"   [OK] Loaded {len(self.trades)} trades from JSON")
            except Exception as e:
                print(f"   ⚠ DataRegistry failed: {e}")
        
        # Direct file access fallback
        if not self.trades:
            for path in ["logs/positions_futures.json", "data/trading_system.db"]:
                if os.path.exists(path):
                    try:
                        if path.endswith('.json'):
                            with open(path, 'r') as f:
                                data = json.load(f)
                                if isinstance(data, dict):
                                    self.trades = data.get("closed_positions", [])
                                elif isinstance(data, list):
                                    self.trades = data
                            if self.trades:
                                print(f"   [OK] Loaded {len(self.trades)} trades from {path}")
                                break
                    except Exception as e:
                        print(f"   ⚠ Error loading {path}: {e}")
        
        # 2. All signals (executed + blocked + skipped)
        print("\n[2] Loading all signals...")
        signal_paths = [
            "logs/signals.jsonl",
            "logs/predictive_signals.jsonl",
            "logs/signal_outcomes.jsonl"
        ]
        for path in signal_paths:
            if os.path.exists(path):
                try:
                    with open(path, 'r') as f:
                        count = 0
                        for line in f:
                            if line.strip():
                                try:
                                    sig = json.loads(line)
                                    self.all_signals.append(sig)
                                    # Separate blocked signals
                                    if sig.get('disposition') == 'BLOCKED' or sig.get('status') == 'blocked':
                                        self.blocked_signals.append(sig)
                                    count += 1
                                except:
                                    pass
                    if count > 0:
                        print(f"   [OK] Loaded {count} signals from {path}")
                        break
                except Exception as e:
                    print(f"   ⚠ Error loading {path}: {e}")
        
        # 3. Missed opportunities
        print("\n[3] Loading missed opportunities...")
        missed_paths = [
            "logs/missed_opportunities.jsonl",
            DR.MISSED_OPPORTUNITIES if DR_AVAILABLE else "logs/missed_opportunities.jsonl"
        ]
        for path in missed_paths:
            if os.path.exists(path):
                try:
                    with open(path, 'r') as f:
                        for line in f:
                            if line.strip():
                                try:
                                    self.missed_opportunities.append(json.loads(line))
                                except:
                                    pass
                    if self.missed_opportunities:
                        print(f"   [OK] Loaded {len(self.missed_opportunities)} missed opportunities")
                        break
                except Exception as e:
                    print(f"   ⚠ Error loading {path}: {e}")
        
        # 4. Counterfactual outcomes
        print("\n[4] Loading counterfactual outcomes...")
        counterfactual_paths = [
            "logs/counterfactual_outcomes.jsonl",
            DR.COUNTERFACTUAL_OUTCOMES if DR_AVAILABLE else "logs/counterfactual_outcomes.jsonl"
        ]
        for path in counterfactual_paths:
            if os.path.exists(path):
                try:
                    with open(path, 'r') as f:
                        for line in f:
                            if line.strip():
                                try:
                                    self.counterfactual_outcomes.append(json.loads(line))
                                except:
                                    pass
                    if self.counterfactual_outcomes:
                        print(f"   ✓ Loaded {len(self.counterfactual_outcomes)} counterfactual outcomes")
                        break
                except Exception as e:
                    print(f"   ⚠ Error loading {path}: {e}")
        
        # 5. Enriched decisions
        print("\n[5] Loading enriched decisions...")
        enriched_paths = [
            "logs/enriched_decisions.jsonl",
            DR.ENRICHED_DECISIONS if DR_AVAILABLE else "logs/enriched_decisions.jsonl"
        ]
        for path in enriched_paths:
            if os.path.exists(path):
                try:
                    with open(path, 'r') as f:
                        for line in f:
                            if line.strip():
                                try:
                                    self.enriched_decisions.append(json.loads(line))
                                except:
                                    pass
                    if self.enriched_decisions:
                        print(f"   ✓ Loaded {len(self.enriched_decisions)} enriched decisions")
                        break
                except Exception as e:
                    print(f"   ⚠ Error loading {path}: {e}")
        
        # 6. Learning system data
        print("\n[6] Loading learning system data...")
        learning_paths = {
            "adaptive_weights": "feature_store/adaptive_weights.json",
            "learned_rules": "feature_store/learned_rules.json",
            "signal_weights": "feature_store/signal_weights.json",
            "pattern_discoveries": "feature_store/pattern_discoveries.json",
            "exit_timing": "feature_store/exit_timing_mfe.json",
            "hold_time_rules": "feature_store/hold_time_rules.json"
        }
        for key, path in learning_paths.items():
            if os.path.exists(path):
                try:
                    with open(path, 'r') as f:
                        self.learning_data[key] = json.load(f)
                    print(f"   ✓ Loaded {key}")
                except Exception as e:
                    print(f"   ⚠ Error loading {key}: {e}")
        
        # Summary
        print("\n" + "=" * 80)
        print("DATA SUMMARY")
        print("=" * 80)
        print(f"Executed Trades: {len(self.trades)}")
        print(f"All Signals: {len(self.all_signals)}")
        print(f"Blocked Signals: {len(self.blocked_signals)}")
        print(f"Missed Opportunities: {len(self.missed_opportunities)}")
        print(f"Counterfactual Outcomes: {len(self.counterfactual_outcomes)}")
        print(f"Enriched Decisions: {len(self.enriched_decisions)}")
        print(f"Learning Data Files: {len(self.learning_data)}")
        
        self.analysis_results["data_summary"] = {
            "trades": len(self.trades),
            "all_signals": len(self.all_signals),
            "blocked_signals": len(self.blocked_signals),
            "missed_opportunities": len(self.missed_opportunities),
            "counterfactual_outcomes": len(self.counterfactual_outcomes),
            "enriched_decisions": len(self.enriched_decisions),
            "learning_files": len(self.learning_data)
        }
    
    def analyze_signal_components(self):
        """Analyze every signal component and its effectiveness"""
        print("\n" + "=" * 80)
        print("SIGNAL COMPONENT ANALYSIS")
        print("=" * 80)
        
        if not self.trades:
            print("No trades to analyze")
            return
        
        # Signal components from predictive_flow_engine
        signal_components = [
            'liquidation', 'funding', 'oi_velocity', 'whale_flow',
            'ofi_momentum', 'fear_greed', 'hurst', 'lead_lag',
            'volatility_skew', 'oi_divergence'
        ]
        
        signal_performance = {}
        
        for trade in self.trades:
            # Extract signal data from trade
            signals = trade.get('signals', {})
            if not signals:
                # Try to get from enriched decisions
                trade_id = trade.get('trade_id') or trade.get('id')
                for ed in self.enriched_decisions:
                    if ed.get('trade_id') == trade_id:
                        signals = ed.get('signals', {})
                        break
            
            pnl = self._get_pnl(trade)
            is_winner = pnl > 0
            
            # Analyze each signal component
            for component in signal_components:
                if component not in signal_performance:
                    signal_performance[component] = {
                        'total_trades': 0,
                        'winners': 0,
                        'losers': 0,
                        'total_pnl': 0,
                        'win_pnl': [],
                        'loss_pnl': [],
                        'signal_values': [],
                        'weight_used': []
                    }
                
                signal_value = signals.get(component) or signals.get(f'{component}_signal')
                if signal_value is not None:
                    signal_performance[component]['total_trades'] += 1
                    signal_performance[component]['total_pnl'] += pnl
                    signal_performance[component]['signal_values'].append(signal_value)
                    
                    if is_winner:
                        signal_performance[component]['winners'] += 1
                        signal_performance[component]['win_pnl'].append(pnl)
                    else:
                        signal_performance[component]['losers'] += 1
                        signal_performance[component]['loss_pnl'].append(abs(pnl))
        
        # Calculate metrics
        results = {}
        for component, perf in signal_performance.items():
            if perf['total_trades'] > 0:
                win_rate = (perf['winners'] / perf['total_trades']) * 100
                avg_win = statistics.mean(perf['win_pnl']) if perf['win_pnl'] else 0
                avg_loss = statistics.mean(perf['loss_pnl']) if perf['loss_pnl'] else 0
                rr_ratio = avg_win / avg_loss if avg_loss > 0 else 0
                expectancy = (win_rate/100 * avg_win) - ((100-win_rate)/100 * avg_loss)
                avg_signal_value = statistics.mean(perf['signal_values']) if perf['signal_values'] else 0
                
                results[component] = {
                    'total_trades': perf['total_trades'],
                    'win_rate': round(win_rate, 2),
                    'total_pnl': round(perf['total_pnl'], 2),
                    'avg_win': round(avg_win, 2),
                    'avg_loss': round(avg_loss, 2),
                    'risk_reward': round(rr_ratio, 2),
                    'expectancy': round(expectancy, 2),
                    'avg_signal_value': round(avg_signal_value, 3),
                    'profitability_score': round(expectancy * perf['total_trades'], 2)
                }
        
        # Sort by profitability score
        sorted_signals = sorted(results.items(), key=lambda x: x[1]['profitability_score'], reverse=True)
        
        print("\nSignal Component Performance (sorted by profitability):")
        print("-" * 80)
        for component, metrics in sorted_signals:
            print(f"\n{component.upper()}:")
            print(f"  Trades: {metrics['total_trades']}")
            print(f"  Win Rate: {metrics['win_rate']:.1f}%")
            print(f"  Total P&L: ${metrics['total_pnl']:.2f}")
            print(f"  Avg Win: ${metrics['avg_win']:.2f} | Avg Loss: ${metrics['avg_loss']:.2f}")
            print(f"  Risk/Reward: {metrics['risk_reward']:.2f}")
            print(f"  Expectancy: ${metrics['expectancy']:.2f}")
            print(f"  Profitability Score: {metrics['profitability_score']:.2f}")
            print(f"  Avg Signal Value: {metrics['avg_signal_value']:.3f}")
        
        self.analysis_results["signal_analysis"]["component_performance"] = results
        self.analysis_results["signal_analysis"]["sorted_by_profitability"] = [
            {"component": c, **m} for c, m in sorted_signals
        ]
    
    def analyze_signal_combinations(self):
        """Analyze which signal combinations work best"""
        print("\n" + "=" * 80)
        print("SIGNAL COMBINATION ANALYSIS")
        print("=" * 80)
        
        if not self.trades:
            print("No trades to analyze")
            return
        
        combination_performance = defaultdict(lambda: {
            'trades': 0, 'winners': 0, 'total_pnl': 0, 'win_pnl': [], 'loss_pnl': []
        })
        
        for trade in self.trades:
            signals = trade.get('signals', {})
            if not signals:
                continue
            
            # Get active signals (non-zero values)
            active_signals = [k for k, v in signals.items() if v and v != 0]
            if len(active_signals) < 2:
                continue
            
            # Create combination key (sorted for consistency)
            combo_key = "+".join(sorted(active_signals))
            
            pnl = self._get_pnl(trade)
            is_winner = pnl > 0
            
            combination_performance[combo_key]['trades'] += 1
            combination_performance[combo_key]['total_pnl'] += pnl
            
            if is_winner:
                combination_performance[combo_key]['winners'] += 1
                combination_performance[combo_key]['win_pnl'].append(pnl)
            else:
                combination_performance[combo_key]['loss_pnl'].append(abs(pnl))
        
        # Calculate metrics and sort
        results = []
        for combo, perf in combination_performance.items():
            if perf['trades'] >= 3:  # Minimum sample size
                win_rate = (perf['winners'] / perf['trades']) * 100
                avg_win = statistics.mean(perf['win_pnl']) if perf['win_pnl'] else 0
                avg_loss = statistics.mean(perf['loss_pnl']) if perf['loss_pnl'] else 0
                expectancy = (win_rate/100 * avg_win) - ((100-win_rate)/100 * avg_loss)
                
                results.append({
                    'combination': combo,
                    'trades': perf['trades'],
                    'win_rate': round(win_rate, 2),
                    'total_pnl': round(perf['total_pnl'], 2),
                    'avg_win': round(avg_win, 2),
                    'avg_loss': round(avg_loss, 2),
                    'expectancy': round(expectancy, 2),
                    'profitability_score': round(expectancy * perf['trades'], 2)
                })
        
        results.sort(key=lambda x: x['profitability_score'], reverse=True)
        
        print(f"\nTop Signal Combinations (n≥3):")
        print("-" * 80)
        for r in results[:20]:  # Top 20
            print(f"\n{r['combination']}:")
            print(f"  Trades: {r['trades']} | WR: {r['win_rate']:.1f}% | P&L: ${r['total_pnl']:.2f}")
            print(f"  Expectancy: ${r['expectancy']:.2f} | Score: {r['profitability_score']:.2f}")
        
        self.analysis_results["signal_analysis"]["combinations"] = results
    
    def analyze_timing(self):
        """Analyze entry and exit timing"""
        print("\n" + "=" * 80)
        print("TIMING ANALYSIS")
        print("=" * 80)
        
        if not self.trades:
            print("No trades to analyze")
            return
        
        entry_timing = defaultdict(lambda: {'trades': 0, 'winners': 0, 'total_pnl': 0})
        exit_timing = defaultdict(lambda: {'trades': 0, 'winners': 0, 'total_pnl': 0})
        hold_duration = {'winners': [], 'losers': []}
        
        for trade in self.trades:
            pnl = self._get_pnl(trade)
            is_winner = pnl > 0
            
            # Entry timing (hour of day)
            entry_ts = self._get_timestamp(trade, 'entry')
            if entry_ts:
                entry_hour = datetime.fromtimestamp(entry_ts).hour
                entry_timing[entry_hour]['trades'] += 1
                entry_timing[entry_hour]['total_pnl'] += pnl
                if is_winner:
                    entry_timing[entry_hour]['winners'] += 1
            
            # Exit timing (hour of day)
            exit_ts = self._get_timestamp(trade, 'exit')
            if exit_ts:
                exit_hour = datetime.fromtimestamp(exit_ts).hour
                exit_timing[exit_hour]['trades'] += 1
                exit_timing[exit_hour]['total_pnl'] += pnl
                if is_winner:
                    exit_timing[exit_hour]['winners'] += 1
            
            # Hold duration
            if entry_ts and exit_ts:
                duration_minutes = (exit_ts - entry_ts) / 60
                if is_winner:
                    hold_duration['winners'].append(duration_minutes)
                else:
                    hold_duration['losers'].append(duration_minutes)
        
        # Entry timing results
        print("\nEntry Timing by Hour:")
        print("-" * 80)
        entry_results = []
        for hour in sorted(entry_timing.keys()):
            perf = entry_timing[hour]
            if perf['trades'] > 0:
                wr = (perf['winners'] / perf['trades']) * 100
                entry_results.append({
                    'hour': hour,
                    'trades': perf['trades'],
                    'win_rate': round(wr, 2),
                    'total_pnl': round(perf['total_pnl'], 2)
                })
                print(f"  {hour:02d}:00 - Trades: {perf['trades']:3d} | WR: {wr:5.1f}% | P&L: ${perf['total_pnl']:8.2f}")
        
        # Exit timing results
        print("\nExit Timing by Hour:")
        print("-" * 80)
        exit_results = []
        for hour in sorted(exit_timing.keys()):
            perf = exit_timing[hour]
            if perf['trades'] > 0:
                wr = (perf['winners'] / perf['trades']) * 100
                exit_results.append({
                    'hour': hour,
                    'trades': perf['trades'],
                    'win_rate': round(wr, 2),
                    'total_pnl': round(perf['total_pnl'], 2)
                })
                print(f"  {hour:02d}:00 - Trades: {perf['trades']:3d} | WR: {wr:5.1f}% | P&L: ${perf['total_pnl']:8.2f}")
        
        # Hold duration
        print("\nHold Duration:")
        print("-" * 80)
        if hold_duration['winners']:
            avg_winner_duration = statistics.mean(hold_duration['winners'])
            print(f"  Winners: {avg_winner_duration:.1f} minutes (avg)")
        if hold_duration['losers']:
            avg_loser_duration = statistics.mean(hold_duration['losers'])
            print(f"  Losers: {avg_loser_duration:.1f} minutes (avg)")
        
        self.analysis_results["timing_analysis"] = {
            "entry_by_hour": entry_results,
            "exit_by_hour": exit_results,
            "hold_duration": {
                "winners_avg_minutes": round(statistics.mean(hold_duration['winners']), 1) if hold_duration['winners'] else None,
                "losers_avg_minutes": round(statistics.mean(hold_duration['losers']), 1) if hold_duration['losers'] else None
            }
        }
    
    def analyze_volume_patterns(self):
        """Analyze volume patterns at entry and exit"""
        print("\n" + "=" * 80)
        print("VOLUME ANALYSIS")
        print("=" * 80)
        
        if not self.trades:
            print("No trades to analyze")
            return
        
        volume_data = {'winners': [], 'losers': []}
        
        for trade in self.trades:
            pnl = self._get_pnl(trade)
            is_winner = pnl > 0
            
            # Try to get volume data
            volume = trade.get('volume') or trade.get('entry_volume') or trade.get('volume_at_entry')
            if volume:
                if is_winner:
                    volume_data['winners'].append(volume)
                else:
                    volume_data['losers'].append(volume)
        
        if volume_data['winners'] or volume_data['losers']:
            print("\nVolume at Entry:")
            if volume_data['winners']:
                print(f"  Winners (avg): {statistics.mean(volume_data['winners']):,.0f}")
            if volume_data['losers']:
                print(f"  Losers (avg): {statistics.mean(volume_data['losers']):,.0f}")
        
        self.analysis_results["volume_analysis"] = {
            "winners_avg_volume": round(statistics.mean(volume_data['winners']), 0) if volume_data['winners'] else None,
            "losers_avg_volume": round(statistics.mean(volume_data['losers']), 0) if volume_data['losers'] else None
        }
    
    def analyze_weight_optimization(self):
        """Analyze signal weight optimization opportunities"""
        print("\n" + "=" * 80)
        print("SIGNAL WEIGHT OPTIMIZATION")
        print("=" * 80)
        
        # Get current weights
        current_weights = {}
        if 'signal_weights' in self.learning_data:
            current_weights = self.learning_data['signal_weights']
        elif 'adaptive_weights' in self.learning_data:
            current_weights = self.learning_data['adaptive_weights']
        
        # Get signal performance from earlier analysis
        signal_perf = self.analysis_results.get("signal_analysis", {}).get("component_performance", {})
        
        if not signal_perf:
            print("No signal performance data available")
            return
        
        # Calculate optimal weights based on profitability score
        total_score = sum(m.get('profitability_score', 0) for m in signal_perf.values())
        
        recommendations = []
        for component, metrics in signal_perf.items():
            if total_score > 0:
                optimal_weight = max(0.05, min(0.5, (metrics['profitability_score'] / total_score) * 10))
                current_weight = current_weights.get(component, 0.1)
                change_pct = ((optimal_weight - current_weight) / current_weight * 100) if current_weight > 0 else 0
                
                recommendations.append({
                    'component': component,
                    'current_weight': round(current_weight, 3),
                    'optimal_weight': round(optimal_weight, 3),
                    'change_pct': round(change_pct, 1),
                    'profitability_score': metrics['profitability_score'],
                    'expectancy': metrics['expectancy']
                })
        
        recommendations.sort(key=lambda x: abs(x['change_pct']), reverse=True)
        
        print("\nWeight Optimization Recommendations:")
        print("-" * 80)
        for rec in recommendations[:10]:  # Top 10
            direction = "↑" if rec['change_pct'] > 0 else "↓"
            print(f"\n{rec['component']}:")
            print(f"  Current: {rec['current_weight']:.3f} → Optimal: {rec['optimal_weight']:.3f} ({direction}{abs(rec['change_pct']):.1f}%)")
            print(f"  Profitability Score: {rec['profitability_score']:.2f} | Expectancy: ${rec['expectancy']:.2f}")
        
        self.analysis_results["weight_optimization"] = {
            "current_weights": current_weights,
            "recommendations": recommendations
        }
    
    def analyze_winner_loser_patterns(self):
        """Deep dive into what makes winners vs losers"""
        print("\n" + "=" * 80)
        print("WINNER vs LOSER PATTERN ANALYSIS")
        print("=" * 80)
        
        if not self.trades:
            print("No trades to analyze")
            return
        
        winners = []
        losers = []
        
        for trade in self.trades:
            pnl = self._get_pnl(trade)
            if pnl > 0:
                winners.append(trade)
            elif pnl < 0:
                losers.append(trade)
        
        print(f"\nWinners: {len(winners)} | Losers: {len(losers)}")
        
        # Analyze differences
        winner_signals = defaultdict(list)
        loser_signals = defaultdict(list)
        
        for trade in winners:
            signals = trade.get('signals', {})
            for k, v in signals.items():
                if v and v != 0:
                    winner_signals[k].append(v)
        
        for trade in losers:
            signals = trade.get('signals', {})
            for k, v in signals.items():
                if v and v != 0:
                    loser_signals[k].append(v)
        
        print("\nSignal Value Differences (Winners vs Losers):")
        print("-" * 80)
        differences = []
        all_components = set(list(winner_signals.keys()) + list(loser_signals.keys()))
        
        for component in all_components:
            if winner_signals[component] and loser_signals[component]:
                winner_avg = statistics.mean(winner_signals[component])
                loser_avg = statistics.mean(loser_signals[component])
                diff = winner_avg - loser_avg
                diff_pct = (diff / abs(loser_avg) * 100) if loser_avg != 0 else 0
                
                differences.append({
                    'component': component,
                    'winner_avg': round(winner_avg, 3),
                    'loser_avg': round(loser_avg, 3),
                    'difference': round(diff, 3),
                    'difference_pct': round(diff_pct, 1)
                })
                
                print(f"  {component}:")
                print(f"    Winners: {winner_avg:.3f} | Losers: {loser_avg:.3f} | Diff: {diff:+.3f} ({diff_pct:+.1f}%)")
        
        self.analysis_results["winner_loser_patterns"] = {
            "winner_count": len(winners),
            "loser_count": len(losers),
            "signal_differences": differences
        }
    
    def analyze_blocked_trades_learning(self):
        """Learn from blocked trades - what would have happened?"""
        print("\n" + "=" * 80)
        print("BLOCKED TRADES LEARNING")
        print("=" * 80)
        
        if not self.blocked_signals and not self.counterfactual_outcomes:
            print("No blocked trade data available")
            return
        
        # Analyze counterfactual outcomes
        if self.counterfactual_outcomes:
            blocked_winners = 0
            blocked_losers = 0
            blocked_pnl = 0
            
            for outcome in self.counterfactual_outcomes:
                pnl = outcome.get('pnl') or outcome.get('profit_usd') or 0
                blocked_pnl += pnl
                if pnl > 0:
                    blocked_winners += 1
                elif pnl < 0:
                    blocked_losers += 1
            
            print(f"\nBlocked Trades Analysis:")
            print(f"  Total Blocked: {len(self.counterfactual_outcomes)}")
            print(f"  Would Have Won: {blocked_winners}")
            print(f"  Would Have Lost: {blocked_losers}")
            print(f"  Total P&L if Traded: ${blocked_pnl:.2f}")
            
            self.analysis_results["learning_insights"]["blocked_trades"] = {
                "total": len(self.counterfactual_outcomes),
                "would_have_won": blocked_winners,
                "would_have_lost": blocked_losers,
                "total_pnl": round(blocked_pnl, 2)
            }
    
    def generate_recommendations(self):
        """Generate actionable recommendations based on all analysis"""
        print("\n" + "=" * 80)
        print("ACTIONABLE RECOMMENDATIONS")
        print("=" * 80)
        
        recommendations = []
        
        # Signal weight recommendations
        weight_recs = self.analysis_results.get("weight_optimization", {}).get("recommendations", [])
        for rec in weight_recs[:5]:  # Top 5
            if abs(rec['change_pct']) > 10:  # Significant change
                recommendations.append({
                    "priority": "HIGH",
                    "category": "Signal Weights",
                    "action": f"Increase {rec['component']} weight from {rec['current_weight']:.3f} to {rec['optimal_weight']:.3f}",
                    "reason": f"Profitability score: {rec['profitability_score']:.2f}, Expectancy: ${rec['expectancy']:.2f}"
                })
        
        # Timing recommendations
        timing = self.analysis_results.get("timing_analysis", {})
        entry_timing = timing.get("entry_by_hour", [])
        if entry_timing:
            best_entry = max(entry_timing, key=lambda x: x['total_pnl'])
            if best_entry['total_pnl'] > 0:
                recommendations.append({
                    "priority": "MEDIUM",
                    "category": "Entry Timing",
                    "action": f"Focus entries around {best_entry['hour']:02d}:00 UTC",
                    "reason": f"Best performing hour: {best_entry['win_rate']:.1f}% WR, ${best_entry['total_pnl']:.2f} P&L"
                })
        
        # Signal combination recommendations
        combos = self.analysis_results.get("signal_analysis", {}).get("combinations", [])
        if combos:
            best_combo = combos[0]
            if best_combo['expectancy'] > 0:
                recommendations.append({
                    "priority": "HIGH",
                    "category": "Signal Combinations",
                    "action": f"Prioritize trades with signal combination: {best_combo['combination']}",
                    "reason": f"Expectancy: ${best_combo['expectancy']:.2f}, {best_combo['win_rate']:.1f}% WR"
                })
        
        print("\nTop Recommendations:")
        for i, rec in enumerate(recommendations[:10], 1):
            print(f"\n{i}. [{rec['priority']}] {rec['category']}")
            print(f"   Action: {rec['action']}")
            print(f"   Reason: {rec['reason']}")
        
        self.analysis_results["recommendations"] = recommendations
    
    def _get_pnl(self, trade):
        """Extract P&L from trade record"""
        return trade.get('profit_usd') or trade.get('pnl') or trade.get('net_pnl') or trade.get('realized_pnl') or 0
    
    def _get_timestamp(self, trade, type='entry'):
        """Extract timestamp from trade record"""
        if type == 'entry':
            ts = trade.get('entry_ts') or trade.get('entry_timestamp') or trade.get('opened_at')
        else:
            ts = trade.get('exit_ts') or trade.get('exit_timestamp') or trade.get('closed_at')
        
        if isinstance(ts, str):
            try:
                dt = datetime.fromisoformat(ts.replace('Z', '+00:00'))
                return dt.timestamp()
            except:
                pass
        
        return ts if isinstance(ts, (int, float)) else None
    
    def run_full_analysis(self):
        """Run complete comprehensive analysis"""
        print("=" * 80)
        print("COMPREHENSIVE PROFITABILITY ANALYSIS - MASSIVE DEEP DIVE")
        print("=" * 80)
        print(f"Started: {datetime.now().isoformat()}\n")
        
        # Load all data
        self.load_all_data_sources()
        
        if not self.trades:
            print("\n[WARNING] No trade data found!")
            print("This script should be run on the server where data exists.")
            print("Server: 159.65.168.230")
            return self.analysis_results
        
        # Run all analyses
        self.analyze_signal_components()
        self.analyze_signal_combinations()
        self.analyze_timing()
        self.analyze_volume_patterns()
        self.analyze_weight_optimization()
        self.analyze_winner_loser_patterns()
        self.analyze_blocked_trades_learning()
        self.generate_recommendations()
        
        # Save results
        os.makedirs("reports", exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_file = f"reports/comprehensive_profitability_analysis_{timestamp}.json"
        
        with open(output_file, 'w') as f:
            json.dump(self.analysis_results, f, indent=2, default=str)
        
        print("\n" + "=" * 80)
        print("ANALYSIS COMPLETE")
        print("=" * 80)
        print(f"Results saved to: {output_file}")
        
        return self.analysis_results


if __name__ == "__main__":
    analyzer = ComprehensiveProfitabilityAnalysis()
    results = analyzer.run_full_analysis()
