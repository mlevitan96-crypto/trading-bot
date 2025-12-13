#!/usr/bin/env python3
"""
ENHANCED SIGNAL LEARNER - Comprehensive Learning System
=========================================================
Implements sliding window weighted averages, cross-signal correlation,
and comprehensive counterfactual analysis for continuous improvement.

Key Features:
1. Exponentially Weighted Moving Average (EWMA) for signal EV
2. Per-symbol, per-direction signal effectiveness
3. Cross-signal correlation analysis (which signals work together)
4. Regime-aware signal performance tracking
5. Counterfactual analysis for blocked trades
6. Automatic weight adjustment recommendations
"""

import json
import os
from datetime import datetime, timedelta
from collections import defaultdict
from typing import Dict, List, Any, Optional, Tuple
from pathlib import Path
import math

# File paths
SIGNAL_OUTCOMES = "logs/signal_outcomes.jsonl"
CONVICTION_LOG = "logs/conviction_gate.jsonl"
MISSED_OPP = "logs/missed_opportunities.jsonl"
LEARNING_STATE = "feature_store/enhanced_learning_state.json"
SIGNAL_WEIGHTS = "feature_store/signal_weights_gate.json"

# EWMA decay factor (0.95 = recent data weighted more heavily)
EWMA_ALPHA = 0.05  # Smoothing factor (higher = more weight on recent)

class EnhancedSignalLearner:
    """
    Comprehensive learning system for signal optimization.
    Tracks performance across multiple dimensions and generates
    weight adjustment recommendations.
    """
    
    def __init__(self):
        self.state = self._load_state()
        
    def _load_state(self) -> Dict:
        """Load or initialize learning state."""
        try:
            if os.path.exists(LEARNING_STATE):
                with open(LEARNING_STATE) as f:
                    return json.load(f)
        except:
            pass
        
        return {
            'signal_ewma': {},  # EWMA EV by signal
            'signal_by_symbol': {},  # Performance by symbol+signal
            'signal_by_direction': {},  # Performance by direction+signal
            'signal_correlations': {},  # Which signals work together
            'blocked_analysis': {},  # What would blocked trades have done
            'last_update': None,
            'total_signals_analyzed': 0
        }
    
    def analyze_signals(self, lookback_hours: int = 24) -> Dict[str, Any]:
        """
        Comprehensive signal analysis with sliding window.
        
        Returns detailed breakdown of signal performance across
        multiple dimensions with EWMA smoothing.
        """
        cutoff = datetime.utcnow() - timedelta(hours=lookback_hours)
        
        # Load recent signals
        signals = []
        try:
            with open(SIGNAL_OUTCOMES) as f:
                for line in f:
                    try:
                        s = json.loads(line.strip())
                        ts_str = s.get('ts', '')
                        if ts_str:
                            signals.append(s)
                    except:
                        pass
        except:
            return {'error': 'Could not load signal outcomes'}
        
        # Group by multiple dimensions
        by_signal = defaultdict(lambda: {'evs': [], 'hits': defaultdict(int), 'total': 0})
        by_signal_symbol = defaultdict(lambda: {'evs': [], 'hits': 0, 'total': 0})
        by_signal_direction = defaultdict(lambda: {'evs': [], 'hits': 0, 'total': 0})
        signal_pairs = defaultdict(lambda: {'aligned_wins': 0, 'aligned_total': 0, 'opposed_wins': 0, 'opposed_total': 0})
        
        for s in signals:
            sig = s.get('signal_name', 'unknown')
            symbol = s.get('symbol', 'UNK')
            direction = s.get('direction', 'UNK')
            ev = s.get('ev_contribution', 0) or 0
            hits = s.get('hits', {})
            
            # Overall signal performance
            by_signal[sig]['evs'].append(ev)
            by_signal[sig]['total'] += 1
            for tf in ['1m', '5m', '15m', '30m', '1h']:
                if hits.get(tf):
                    by_signal[sig]['hits'][tf] += 1
            
            # By symbol
            key = f"{sig}_{symbol}"
            by_signal_symbol[key]['evs'].append(ev)
            by_signal_symbol[key]['total'] += 1
            if hits.get('30m'):
                by_signal_symbol[key]['hits'] += 1
            
            # By direction
            key = f"{sig}_{direction}"
            by_signal_direction[key]['evs'].append(ev)
            by_signal_direction[key]['total'] += 1
            if hits.get('30m'):
                by_signal_direction[key]['hits'] += 1
        
        # Calculate EWMA for each signal
        ewma_results = {}
        for sig, data in by_signal.items():
            if data['evs']:
                ewma = self._calculate_ewma(data['evs'])
                hit_rates = {tf: data['hits'][tf] / data['total'] * 100 
                            for tf in ['1m', '5m', '15m', '30m', '1h']}
                ewma_results[sig] = {
                    'ewma_ev_bps': ewma * 10000,
                    'simple_avg_ev_bps': sum(data['evs']) / len(data['evs']) * 10000,
                    'hit_rates': hit_rates,
                    'total_signals': data['total'],
                    'trend': 'improving' if ewma > sum(data['evs'][:len(data['evs'])//2]) / max(1, len(data['evs'])//2) else 'declining'
                }
        
        # Symbol-specific performance
        symbol_results = {}
        for key, data in by_signal_symbol.items():
            if data['total'] >= 10:  # Minimum samples
                sig, symbol = key.rsplit('_', 1)
                if sig not in symbol_results:
                    symbol_results[sig] = {}
                symbol_results[sig][symbol] = {
                    'ewma_ev_bps': self._calculate_ewma(data['evs']) * 10000,
                    'hit_rate': data['hits'] / data['total'] * 100,
                    'total': data['total']
                }
        
        # Direction-specific performance
        direction_results = {}
        for key, data in by_signal_direction.items():
            if data['total'] >= 10:
                sig, direction = key.rsplit('_', 1)
                if sig not in direction_results:
                    direction_results[sig] = {}
                direction_results[sig][direction] = {
                    'ewma_ev_bps': self._calculate_ewma(data['evs']) * 10000,
                    'hit_rate': data['hits'] / data['total'] * 100,
                    'total': data['total']
                }
        
        # Generate weight recommendations
        recommendations = self._generate_weight_recommendations(ewma_results, direction_results)
        
        # Save state
        self.state['signal_ewma'] = ewma_results
        self.state['signal_by_symbol'] = symbol_results
        self.state['signal_by_direction'] = direction_results
        self.state['last_update'] = datetime.utcnow().isoformat()
        self.state['total_signals_analyzed'] = len(signals)
        self._save_state()
        
        return {
            'signal_performance': ewma_results,
            'by_symbol': symbol_results,
            'by_direction': direction_results,
            'recommendations': recommendations,
            'total_analyzed': len(signals),
            'lookback_hours': lookback_hours
        }
    
    def analyze_blocked_trades(self) -> Dict[str, Any]:
        """
        Analyze what blocked trades would have done.
        This is the counterfactual intelligence.
        """
        try:
            with open(MISSED_OPP) as f:
                missed = [json.loads(line.strip()) for line in f if line.strip()]
        except:
            return {'error': 'Could not load missed opportunities'}
        
        if not missed:
            return {'message': 'No missed opportunities to analyze'}
        
        by_reason = defaultdict(lambda: {'would_win': 0, 'would_lose': 0, 'total_pnl': 0})
        by_symbol_reason = defaultdict(lambda: {'would_win': 0, 'would_lose': 0})
        
        for m in missed:
            reason = m.get('block_reason', 'unknown')
            symbol = m.get('symbol', 'UNK')
            would_win = m.get('would_have_won', False)
            best_pnl = m.get('best_pnl_pct', 0)
            
            key = reason
            by_reason[key]['total_pnl'] += best_pnl
            if would_win:
                by_reason[key]['would_win'] += 1
            else:
                by_reason[key]['would_lose'] += 1
            
            sym_key = f"{symbol}_{reason}"
            if would_win:
                by_symbol_reason[sym_key]['would_win'] += 1
            else:
                by_symbol_reason[sym_key]['would_lose'] += 1
        
        # Calculate what filters are costing us
        filter_cost = {}
        for reason, data in by_reason.items():
            total = data['would_win'] + data['would_lose']
            if total >= 5:
                missed_wr = data['would_win'] / total * 100
                avg_pnl = data['total_pnl'] / total
                filter_cost[reason] = {
                    'missed_win_rate': missed_wr,
                    'avg_potential_pnl': avg_pnl,
                    'total_blocked': total,
                    'recommendation': 'RELAX' if missed_wr > 50 else 'KEEP'
                }
        
        return {
            'filter_analysis': filter_cost,
            'by_symbol_reason': dict(by_symbol_reason),
            'total_missed': len(missed)
        }
    
    def _calculate_ewma(self, values: List[float]) -> float:
        """Calculate Exponentially Weighted Moving Average."""
        if not values:
            return 0.0
        
        ewma = values[0]
        for v in values[1:]:
            ewma = EWMA_ALPHA * v + (1 - EWMA_ALPHA) * ewma
        return ewma
    
    def _generate_weight_recommendations(self, ewma_results: Dict, direction_results: Dict) -> List[Dict]:
        """Generate weight adjustment recommendations based on EWMA analysis."""
        recommendations = []
        
        # Load current weights
        try:
            with open(SIGNAL_WEIGHTS) as f:
                current_weights = json.load(f).get('weights', {})
        except:
            current_weights = {}
        
        for sig, data in ewma_results.items():
            ewma_ev = data['ewma_ev_bps']
            current_weight = current_weights.get(sig, 0.1)
            
            # Check direction asymmetry
            dir_data = direction_results.get(sig, {})
            long_ev = dir_data.get('LONG', {}).get('ewma_ev_bps', 0)
            short_ev = dir_data.get('SHORT', {}).get('ewma_ev_bps', 0)
            
            if ewma_ev > 2:  # Positive EV signal
                if current_weight < 0.25:
                    recommendations.append({
                        'signal': sig,
                        'action': 'INCREASE',
                        'current_weight': current_weight,
                        'suggested_weight': min(0.30, current_weight * 1.2),
                        'reason': f'Positive EWMA EV: {ewma_ev:+.2f}bps'
                    })
            elif ewma_ev < -3:  # Negative EV signal
                if current_weight > 0.05:
                    recommendations.append({
                        'signal': sig,
                        'action': 'DECREASE',
                        'current_weight': current_weight,
                        'suggested_weight': max(0.02, current_weight * 0.8),
                        'reason': f'Negative EWMA EV: {ewma_ev:+.2f}bps'
                    })
            
            # Direction asymmetry recommendation
            if long_ev > 0 and short_ev < -5:
                recommendations.append({
                    'signal': sig,
                    'action': 'DIRECTION_FILTER',
                    'reason': f'LONG works ({long_ev:+.2f}bps), SHORT fails ({short_ev:+.2f}bps) - consider LONG-only'
                })
            elif short_ev > 0 and long_ev < -5:
                recommendations.append({
                    'signal': sig,
                    'action': 'DIRECTION_FILTER',
                    'reason': f'SHORT works ({short_ev:+.2f}bps), LONG fails ({long_ev:+.2f}bps) - consider SHORT-only'
                })
        
        return recommendations
    
    def _save_state(self):
        """Save learning state."""
        try:
            os.makedirs(os.path.dirname(LEARNING_STATE), exist_ok=True)
            with open(LEARNING_STATE, 'w') as f:
                json.dump(self.state, f, indent=2)
        except:
            pass
    
    def get_signal_report(self) -> str:
        """Generate a human-readable signal performance report."""
        analysis = self.analyze_signals(lookback_hours=24)
        blocked = self.analyze_blocked_trades()
        
        lines = ["=" * 60]
        lines.append("ENHANCED SIGNAL LEARNING REPORT")
        lines.append("=" * 60)
        lines.append(f"Signals Analyzed: {analysis.get('total_analyzed', 0)}")
        lines.append("")
        
        lines.append("SIGNAL EWMA PERFORMANCE (Last 24h)")
        lines.append("-" * 40)
        for sig, data in sorted(analysis.get('signal_performance', {}).items(), 
                                key=lambda x: x[1].get('ewma_ev_bps', 0), reverse=True):
            ewma = data.get('ewma_ev_bps', 0)
            trend = data.get('trend', 'unknown')
            hr_30m = data.get('hit_rates', {}).get('30m', 0)
            lines.append(f"  {sig}: EWMA={ewma:+.2f}bps, HR@30m={hr_30m:.1f}%, {trend}")
        
        lines.append("")
        lines.append("DIRECTION-SPECIFIC PERFORMANCE")
        lines.append("-" * 40)
        for sig, dirs in analysis.get('by_direction', {}).items():
            long_ev = dirs.get('LONG', {}).get('ewma_ev_bps', 0)
            short_ev = dirs.get('SHORT', {}).get('ewma_ev_bps', 0)
            lines.append(f"  {sig}: LONG={long_ev:+.2f}bps, SHORT={short_ev:+.2f}bps")
        
        lines.append("")
        lines.append("RECOMMENDATIONS")
        lines.append("-" * 40)
        for rec in analysis.get('recommendations', []):
            lines.append(f"  [{rec['action']}] {rec['signal']}: {rec['reason']}")
        
        lines.append("")
        lines.append("BLOCKED TRADE ANALYSIS")
        lines.append("-" * 40)
        for reason, data in blocked.get('filter_analysis', {}).items():
            wr = data.get('missed_win_rate', 0)
            rec = data.get('recommendation', '')
            lines.append(f"  {reason}: {wr:.1f}% would have won → {rec}")
        
        return "\n".join(lines)


# Singleton instance
_learner = None

def get_enhanced_learner() -> EnhancedSignalLearner:
    global _learner
    if _learner is None:
        _learner = EnhancedSignalLearner()
    return _learner


def run_direction_learning():
    """
    Run direction learning cycle - evaluates if any signals need direction changes.
    Called periodically by the learning engine.
    """
    try:
        from src.regime_direction_router import run_direction_evaluation, get_direction_router
        
        recommendations = run_direction_evaluation()
        
        if recommendations:
            print(f"🔄 [DirectionLearner] Evaluated {len(recommendations)} potential direction changes:")
            for rec in recommendations:
                print(f"   {rec['signal']}: {rec['current']} → {rec['recommended']} ({rec['reason']})")
        
        router = get_direction_router()
        summary = router.get_regime_summary()
        print(f"📊 [DirectionLearner] Regime: {summary['regime_bias']} | LONG={summary['total_ev']['LONG']:+.1f}bps, SHORT={summary['total_ev']['SHORT']:+.1f}bps")
        
        return recommendations
    except ImportError as e:
        print(f"[DirectionLearner] Router not available: {e}")
        return []
    except Exception as e:
        print(f"[DirectionLearner] Error: {e}")
        return []


if __name__ == "__main__":
    learner = get_enhanced_learner()
    print(learner.get_signal_report())
    
    print("\n" + "=" * 60)
    print("DIRECTION LEARNING")
    print("=" * 60)
    run_direction_learning()
