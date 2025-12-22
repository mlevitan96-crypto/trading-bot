#!/usr/bin/env python3
"""
Run Learning Analysis - Wrapper for Existing Learning Engine
============================================================
Uses the existing ContinuousLearningController with configurable parameters.

This script provides a template for analyzing:
- N trades (by calculating hours needed)
- N days/hours (direct parameter)
- All existing learning engine features:
  * Executed trades
  * Blocked trades
  * Missed opportunities
  * Counter intelligence
  * Signal component analysis (including Sentiment-Fusion)
  * Timing analysis
  * Volume analysis
  * All signals
  * Signal weight analysis

Usage:
    # Analyze last 300 trades
    python3 run_learning_analysis.py --trades 300
    
    # Analyze last 7 days
    python3 run_learning_analysis.py --days 7
    
    # Analyze last 48 hours
    python3 run_learning_analysis.py --hours 48
    
    # Run full learning cycle with custom lookback
    python3 run_learning_analysis.py --hours 168 --apply
"""

import os
import sys
import argparse
from pathlib import Path
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(__file__))

from src.continuous_learning_controller import ContinuousLearningController
from src.data_registry import DataRegistry as DR

# Try to import comprehensive evaluation (may fail if aiosqlite not installed)
try:
    from src.comprehensive_learning_evaluation import ComprehensiveLearningEvaluation
    HAS_COMPREHENSIVE_EVAL = True
except ImportError as e:
    if 'aiosqlite' in str(e):
        HAS_COMPREHENSIVE_EVAL = False
        print(f"⚠️  Note: Comprehensive evaluation requires aiosqlite")
        print(f"   Install with: pip install aiosqlite")
        print(f"   Continuing with learning engine analysis only...")
        print()
    else:
        raise


def estimate_hours_for_trades(num_trades: int) -> int:
    """Estimate hours needed to get approximately N trades."""
    # Load recent trades to estimate trade frequency
    try:
        portfolio_path = Path(DR.POSITIONS_FUTURES)
        if portfolio_path.exists():
            import json
            with open(portfolio_path, 'r') as f:
                portfolio = json.load(f)
            
            closed = portfolio.get('closed_positions', [])
            closed = [t for t in closed if t.get('bot_type', 'alpha') == 'alpha']
            
            if len(closed) >= 10:
                # Get last 10 trades to estimate frequency
                recent = closed[-10:]
                times = []
                for t in recent:
                    close_time = t.get('closed_at') or t.get('timestamp', '')
                    if isinstance(close_time, str):
                        try:
                            dt = datetime.fromisoformat(close_time.replace('Z', '+00:00'))
                            times.append(dt.timestamp())
                        except:
                            pass
                
                if len(times) >= 2:
                    # Calculate average time between trades
                    times.sort()
                    intervals = [times[i+1] - times[i] for i in range(len(times)-1)]
                    avg_interval_hours = (sum(intervals) / len(intervals)) / 3600
                    
                    # Estimate hours needed for N trades
                    estimated_hours = int(num_trades * avg_interval_hours * 1.2)  # 20% buffer
                    return max(24, min(estimated_hours, 720))  # Between 1 day and 30 days
        
        # Fallback: assume ~10 trades per day
        return max(24, int(num_trades * 2.4))
    except Exception as e:
        print(f"⚠️  Could not estimate hours from trades, using default: {e}")
        # Fallback: assume ~10 trades per day
        return max(24, int(num_trades * 2.4))


def run_learning_analysis(hours: int = None, days: int = None, trades: int = None, apply: bool = False):
    """Run learning analysis with configurable parameters."""
    print("="*80)
    print("LEARNING ANALYSIS - Using Existing Learning Engine")
    print("="*80)
    print(f"Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print()
    
    # Determine lookback hours
    if trades:
        lookback_hours = estimate_hours_for_trades(trades)
        print(f"📊 Analyzing last {trades} trades (estimated {lookback_hours} hours lookback)")
    elif days:
        lookback_hours = days * 24
        print(f"📊 Analyzing last {days} days ({lookback_hours} hours)")
    elif hours:
        lookback_hours = hours
        print(f"📊 Analyzing last {hours} hours")
    else:
        lookback_hours = 168  # Default: 7 days
        print(f"📊 Using default: last 7 days ({lookback_hours} hours)")
    
    print()
    
    # Initialize learning controller with custom lookback
    print("="*80)
    print("INITIALIZING LEARNING ENGINE")
    print("="*80)
    print(f"Lookback period: {lookback_hours} hours ({lookback_hours/24:.1f} days)")
    print()
    print("Learning engine will analyze:")
    print("  ✅ Executed trades")
    print("  ✅ Blocked trades")
    print("  ✅ Missed opportunities")
    print("  ✅ Counter intelligence")
    print("  ✅ Signal component contribution (including Sentiment-Fusion)")
    print("  ✅ Timing analysis (by hour, session)")
    print("  ✅ Volume analysis")
    print("  ✅ All signals")
    print("  ✅ Signal weight analysis")
    print("  ✅ By symbol + direction")
    print("  ✅ By market regime")
    print("  ✅ By conviction level")
    print()
    
    controller = ContinuousLearningController(lookback_hours=lookback_hours)
    
    # Run learning cycle
    print("="*80)
    print("RUNNING LEARNING CYCLE")
    print("="*80)
    state = controller.run_learning_cycle(force=True)
    
    # Display key results
    print()
    print("="*80)
    print("KEY RESULTS")
    print("="*80)
    
    samples = state.get('samples', {})
    print(f"📊 Samples analyzed:")
    print(f"   Executed trades: {samples.get('executed', 0)}")
    print(f"   Blocked signals: {samples.get('blocked', 0)}")
    print(f"   Missed opportunities: {samples.get('missed_found', 0)}")
    print()
    
    profitability = state.get('profitability', {})
    if profitability:
        print(f"💰 Profitability Analysis:")
        by_symbol_dir = profitability.get('by_symbol_direction', {})
        if by_symbol_dir:
            print(f"   Symbol+Direction combinations: {len(by_symbol_dir)}")
        
        by_hour = profitability.get('by_hour', {})
        if by_hour:
            print(f"   Hour analysis: {len(by_hour)} hours analyzed")
        
        by_regime = profitability.get('by_regime', {})
        if by_regime:
            print(f"   Regime analysis: {len(by_regime)} regimes")
        
        signal_components = profitability.get('signal_component_contribution', {})
        if signal_components:
            print(f"   Signal components analyzed: {len(signal_components)}")
            print()
            print(f"   Signal Component Performance:")
            for comp, data in signal_components.items():
                total = data.get('total_aligned', 0)
                if total > 0:
                    win_contrib = data.get('winner_contribution', 0)
                    print(f"      {comp}: {win_contrib:.1f}% winner contribution ({total} aligned)")
    print()
    
    # Signal weight analysis
    print("="*80)
    print("SIGNAL WEIGHT ANALYSIS")
    print("="*80)
    print("   (This includes Sentiment-Fusion and all other signals)")
    print()
    
    try:
        from src.signal_weight_learner import SignalWeightLearner
        learner = SignalWeightLearner()
        
        # Get current weights
        current_weights = learner.current_weights
        print(f"   Current signal weights:")
        for signal, weight in sorted(current_weights.items(), key=lambda x: x[1], reverse=True):
            print(f"      {signal}: {weight:.4f}")
        print()
        
        # Calculate EV for each signal
        print(f"   Signal Expected Values (EV):")
        for signal in current_weights.keys():
            ev_5m = learner.calculate_signal_ev(signal, horizon='5m')
            if ev_5m != 0:
                print(f"      {signal} (5m): {ev_5m:.4f}")
    except Exception as e:
        print(f"   ⚠️  Could not load signal weight analysis: {e}")
    
    print()
    
    # Comprehensive evaluation
    print("="*80)
    print("RUNNING COMPREHENSIVE EVALUATION")
    print("="*80)
    print("   (Includes full signal weight matrix analysis)")
    print()
    
    if HAS_COMPREHENSIVE_EVAL:
        try:
            evaluator = ComprehensiveLearningEvaluation(hours=lookback_hours)
            eval_results = evaluator.run_full_evaluation()
        except Exception as e:
            print(f"   ⚠️  Comprehensive evaluation error: {e}")
            import traceback
            traceback.print_exc()
            eval_results = {}
    else:
        print(f"   ⚠️  Comprehensive evaluation skipped (aiosqlite not installed)")
        eval_results = {}
    
    if eval_results and HAS_COMPREHENSIVE_EVAL:
        try:
            signal_matrix = eval_results.get('signal_weight_matrix', {})
            if signal_matrix:
                signal_perf = signal_matrix.get('signal_performance', {})
                if signal_perf:
                    print(f"   Signal Performance Summary:")
                    for signal, data in sorted(signal_perf.items(), 
                                             key=lambda x: x[1].get('ev', 0), reverse=True):
                        ev = data.get('ev', 0)
                        win_rate = data.get('win_rate', 0)
                        total = data.get('total_signals', 0)
                        if total > 0:
                            status = "✅" if ev > 0 else "❌"
                            print(f"      {status} {signal}: EV={ev:.4f}, WR={win_rate:.1f}%, N={total}")
                    
                    # Check for Sentiment-Fusion specifically
                    if 'Sentiment-Fusion' in signal_perf or 'sentiment_fusion' in signal_perf:
                        sent_data = signal_perf.get('Sentiment-Fusion') or signal_perf.get('sentiment_fusion')
                        if sent_data:
                            print()
                            print(f"   🔍 Sentiment-Fusion Analysis:")
                            print(f"      EV: {sent_data.get('ev', 0):.4f}")
                            print(f"      Win Rate: {sent_data.get('win_rate', 0):.1f}%")
                            print(f"      Total Signals: {sent_data.get('total_signals', 0)}")
                            print(f"      Total P&L: ${sent_data.get('total_pnl', 0):.2f}")
        except Exception as e:
            print(f"   ⚠️  Could not process comprehensive evaluation results: {e}")
            import traceback
            traceback.print_exc()
    
    print()
    
    # Adjustments
    adjustments = state.get('adjustments', [])
    if adjustments:
        print("="*80)
        print("GENERATED ADJUSTMENTS")
        print("="*80)
        print(f"   {len(adjustments)} adjustments generated")
        print()
        
        # Group by type/category
        by_type = {}
        for adj in adjustments:
            # Try multiple fields to find the type
            adj_type = (adj.get('type') or adj.get('category') or 
                       adj.get('gate_type') or 'gate_adjustment')
            
            # Normalize type names
            if 'gate' in str(adj_type).lower() or 'hour' in str(adj.get('gate', '')):
                adj_type = 'gate_threshold'
            elif 'weight' in str(adj_type).lower() or 'component' in str(adj_type).lower():
                adj_type = 'signal_weight'
            elif 'combo' in str(adj_type).lower() or 'kill' in str(adj_type).lower():
                adj_type = 'combo_blocking'
            elif 'sizing' in str(adj_type).lower():
                adj_type = 'position_sizing'
            else:
                adj_type = 'other'
            
            if adj_type not in by_type:
                by_type[adj_type] = []
            by_type[adj_type].append(adj)
        
        for adj_type, adj_list in by_type.items():
            print(f"   📋 {adj_type.replace('_', ' ').title()} ({len(adj_list)} adjustments):")
            for adj in adj_list[:5]:  # Show first 5 of each type
                # Handle nested change dict (from gate adjustments)
                change = adj.get('change', {})
                if isinstance(change, dict):
                    action = change.get('action', adj.get('action', ''))
                    gate = change.get('gate', adj.get('gate', adj.get('component', '')))
                    delta = change.get('delta', adj.get('delta', adj.get('change', '')))
                else:
                    action = adj.get('action', '')
                    gate = adj.get('gate', adj.get('component', ''))
                    delta = adj.get('delta', adj.get('change', ''))
                
                reason = adj.get('reason', adj.get('rationale', ''))
                
                # Format the output
                if action and gate:
                    if delta:
                        print(f"      - {action} {gate} by {delta}")
                    else:
                        print(f"      - {action} {gate}")
                elif action:
                    print(f"      - {action}")
                elif gate:
                    print(f"      - Gate: {gate}")
                elif adj.get('component'):
                    # Signal weight adjustment
                    old_w = adj.get('old_weight', '')
                    new_w = adj.get('new_weight', '')
                    change_w = adj.get('change', '')
                    if old_w and new_w:
                        print(f"      - Adjust {adj.get('component')}: {old_w:.4f} → {new_w:.4f} ({change_w:+.4f})")
                    else:
                        print(f"      - Adjust {adj.get('component')}")
                else:
                    # Fallback: show key non-dict fields
                    key_fields = {k: v for k, v in adj.items() 
                                if k not in ['type', 'category', 'change'] and 
                                   not isinstance(v, dict) and v}
                    if key_fields:
                        print(f"      - {', '.join(f'{k}={v}' for k, v in key_fields.items())}")
                    else:
                        print(f"      - {adj.get('target', 'Adjustment')}")
                
                if reason:
                    print(f"        Reason: {reason}")
            if len(adj_list) > 5:
                print(f"      ... and {len(adj_list) - 5} more {adj_type.replace('_', ' ')} adjustments")
            print()
    
    # Apply adjustments if requested
    if apply and adjustments:
        print("="*80)
        print("APPLYING ADJUSTMENTS")
        print("="*80)
        controller.apply_adjustments(dry_run=False)
        print("   ✅ Adjustments applied")
    elif adjustments:
        print("="*80)
        print("ADJUSTMENTS NOT APPLIED (use --apply to apply)")
        print("="*80)
        print("   Run with --apply flag to apply the generated adjustments")
    
    print()
    print("="*80)
    print("ANALYSIS COMPLETE")
    print("="*80)
    print(f"   Full state saved to: feature_store/learning_state.json")
    print(f"   Results available in state object")
    print("="*80)
    
    return state


def main():
    parser = argparse.ArgumentParser(
        description='Run learning analysis using existing learning engine',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Analyze last 300 trades
  python3 run_learning_analysis.py --trades 300
  
  # Analyze last 7 days
  python3 run_learning_analysis.py --days 7
  
  # Analyze last 48 hours
  python3 run_learning_analysis.py --hours 48
  
  # Run and apply adjustments
  python3 run_learning_analysis.py --hours 168 --apply
        """
    )
    
    group = parser.add_mutually_exclusive_group()
    group.add_argument('--trades', type=int, help='Analyze last N trades')
    group.add_argument('--days', type=int, help='Analyze last N days')
    group.add_argument('--hours', type=int, help='Analyze last N hours')
    
    parser.add_argument('--apply', action='store_true', 
                       help='Apply generated adjustments (default: dry-run)')
    
    args = parser.parse_args()
    
    state = run_learning_analysis(
        hours=args.hours,
        days=args.days,
        trades=args.trades,
        apply=args.apply
    )
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
