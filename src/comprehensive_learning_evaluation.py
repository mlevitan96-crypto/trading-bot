#!/usr/bin/env python3
"""
COMPREHENSIVE LEARNING EVALUATION
==================================
Unified analysis framework that reviews ALL angles:
1. Missed trades - signals not taken that would have worked
2. Blocked trades - what was blocked and counterfactual outcomes
3. Counter intelligence - what-if with opposite directions
4. Signal weight matrix - every combination analyzed

Run modes:
- On-demand: python -m src.comprehensive_learning_evaluation --hours 24
- Scheduled: Nightly at 2 AM via scheduler
- Weekly deep dive: Sundays with extended lookback

Outputs:
- feature_store/comprehensive_analysis.json (structured data)
- reports/comprehensive_evaluation_{date}.md (readable report)
"""

import json
import os
from datetime import datetime, timedelta
from collections import defaultdict
from typing import Dict, List, Any, Optional, Tuple
from itertools import combinations
from pathlib import Path

try:
    from src.data_registry import DataRegistry as DR
except ImportError:
    import sys
    sys.path.insert(0, '/home/runner/workspace')
    from src.data_registry import DataRegistry as DR


DATA_PATHS = {
    'blocked_signals': 'logs/blocked_signals.jsonl',
    'signal_universe': 'logs/signal_universe.jsonl',
    'counterfactual': 'logs/counterfactual_outcomes.jsonl',
    'enriched_decisions': 'logs/enriched_decisions.jsonl',
    'conviction_gate': 'logs/conviction_gate.jsonl',
    'direction_rules': 'feature_store/direction_rules.json',
    'signal_weights': 'feature_store/signal_weights.json',
    'signal_weights_gate': 'feature_store/signal_weights_gate.json',
    'daily_learning_rules': 'feature_store/daily_learning_rules.json',
}

OUTPUT_DIR = Path('reports')
FEATURE_STORE = Path('feature_store')

SIGNAL_TYPES = [
    'liquidation', 'funding', 'whale_flow', 'hurst', 'ofi_momentum',
    'fear_greed', 'oi_velocity', 'volatility_skew', 'oi_divergence', 'lead_lag'
]

CONVICTION_TIERS = ['ULTRA', 'HIGH', 'MEDIUM', 'LOW', 'MINIMUM']

SESSIONS = {
    "asia_night": (0, 4),
    "asia_morning": (4, 8),
    "europe_morning": (8, 12),
    "us_morning": (12, 16),
    "us_afternoon": (16, 20),
    "evening": (20, 24)
}

OFI_BUCKETS = ['weak', 'moderate', 'strong', 'very_strong', 'extreme']
REGIMES = ['Stable', 'Volatile', 'Trending', 'Ranging']
DIRECTIONS = ['LONG', 'SHORT']


def load_jsonl(path: str) -> List[Dict]:
    """Load JSONL file into list of dicts."""
    records = []
    if not os.path.exists(path):
        return records
    try:
        with open(path, 'r') as f:
            for line in f:
                try:
                    records.append(json.loads(line.strip()))
                except:
                    continue
    except Exception:
        pass
    return records


def load_json(path: str) -> Dict:
    """Load JSON file."""
    try:
        with open(path, 'r') as f:
            return json.load(f)
    except:
        return {}


def save_json(path: str, data: Dict):
    """Save JSON file atomically."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp_path = path + ".tmp"
    with open(tmp_path, 'w') as f:
        json.dump(data, f, indent=2)
    os.replace(tmp_path, path)


def get_session(ts: datetime) -> str:
    """Get trading session from timestamp."""
    hour = ts.hour
    for session, (start, end) in SESSIONS.items():
        if start <= hour < end:
            return session
    return "unknown"


def classify_ofi(ofi: float) -> str:
    """Classify OFI into bucket."""
    ofi = abs(ofi)
    if ofi < 0.25:
        return "weak"
    elif ofi < 0.50:
        return "moderate"
    elif ofi < 0.75:
        return "strong"
    elif ofi < 0.90:
        return "very_strong"
    return "extreme"


class ComprehensiveLearningEvaluation:
    """
    Unified analysis framework that consolidates all learning modules.
    """
    
    def __init__(self, hours: int = 24, deep_dive: bool = False):
        self.hours = hours
        self.deep_dive = deep_dive
        self.now = datetime.utcnow()
        self.cutoff = self.now - timedelta(hours=hours)
        self.cutoff_ts = self.cutoff.timestamp()
        
        self.data = {}
        self.results = {
            'meta': {
                'run_time': self.now.isoformat(),
                'lookback_hours': hours,
                'deep_dive': deep_dive,
            },
            'executed_trades': {},
            'blocked_signals': {},
            'missed_opportunities': {},
            'counter_intelligence': {},
            'signal_weight_matrix': {},
            'signal_combinations': {},
            'recommendations': [],
        }
        
        self._load_all_data()
    
    def _load_all_data(self):
        """Load all data sources.
        
        Phase 4 Migration: Uses SQLite for closed trades and signals via DataRegistry.
        JSONL is used for blocked_signals, counterfactual, enriched_decisions etc.
        """
        for name, path in DATA_PATHS.items():
            if path.endswith('.jsonl'):
                self.data[name] = load_jsonl(path)
            else:
                self.data[name] = load_json(path)
        
        self.data['closed_trades'] = DR.get_closed_trades_from_db()
        self.data['open_positions'] = DR.get_open_positions()
        
        self.data['signal_outcomes'] = DR.get_signals_from_db(limit=10000)
    
    def _filter_by_time(self, records: List[Dict], ts_fields: List[str] = None) -> List[Dict]:
        """Filter records to the analysis time window."""
        if ts_fields is None:
            ts_fields = ['closed_at', 'close_timestamp', 'exit_timestamp', 'ts', 'timestamp', 'entry_timestamp', 'opened_at']
        
        filtered = []
        for r in records:
            ts = None
            for field in ts_fields:
                if field in r:
                    ts = r[field]
                    break
            
            if ts is not None:
                if isinstance(ts, str):
                    try:
                        ts = datetime.fromisoformat(ts.replace('Z', '')).timestamp()
                    except:
                        continue
                if ts > self.cutoff_ts:
                    filtered.append(r)
        
        return filtered
    
    def _get_pnl(self, trade: Dict) -> float:
        """Extract P&L from trade record."""
        for field in ['realized_pnl', 'pnl_usd', 'pnl', 'net_pnl']:
            if field in trade and trade[field] is not None:
                try:
                    return float(trade[field])
                except:
                    pass
        return 0.0
    
    def run_full_evaluation(self) -> Dict:
        """Run complete evaluation across all modules."""
        print("=" * 70)
        print("🔬 COMPREHENSIVE LEARNING EVALUATION")
        print("=" * 70)
        print(f"Run time: {self.now.isoformat()}")
        print(f"Lookback: {self.hours} hours | Deep dive: {self.deep_dive}")
        print()
        
        self._analyze_executed_trades()
        self._analyze_blocked_signals()
        self._analyze_missed_opportunities()
        self._analyze_counter_intelligence()
        self._analyze_signal_weight_matrix()
        self._analyze_signal_combinations()
        self._generate_recommendations()
        
        self._save_results()
        self._generate_report()
        
        return self.results
    
    def _analyze_executed_trades(self):
        """Analyze executed trades performance."""
        print("📊 SECTION 1: EXECUTED TRADES ANALYSIS")
        print("-" * 50)
        
        closed = self._filter_by_time(self.data.get('closed_trades', []))
        
        by_symbol = defaultdict(lambda: {'trades': 0, 'wins': 0, 'pnl': 0.0, 'trades_list': []})
        by_direction = defaultdict(lambda: {'trades': 0, 'wins': 0, 'pnl': 0.0})
        by_session = defaultdict(lambda: {'trades': 0, 'wins': 0, 'pnl': 0.0})
        by_signal = defaultdict(lambda: {'trades': 0, 'wins': 0, 'pnl': 0.0})
        by_conviction = defaultdict(lambda: {'trades': 0, 'wins': 0, 'pnl': 0.0})
        by_ofi_bucket = defaultdict(lambda: {'trades': 0, 'wins': 0, 'pnl': 0.0})
        
        for trade in closed:
            pnl = self._get_pnl(trade)
            is_win = pnl > 0
            
            symbol = trade.get('symbol', 'UNKNOWN')
            direction = trade.get('side', trade.get('direction', 'UNKNOWN'))
            conviction = trade.get('conviction', 'UNKNOWN')
            ofi = abs(trade.get('ofi_score', trade.get('ofi_value', trade.get('ofi', trade.get('entry_ofi', 0)))))
            ofi_bucket = classify_ofi(ofi)
            
            entry_ts = trade.get('entry_timestamp', trade.get('opened_at', trade.get('timestamp')))
            if entry_ts:
                try:
                    if isinstance(entry_ts, str):
                        dt = datetime.fromisoformat(entry_ts.replace('Z', '').split('+')[0])
                    else:
                        dt = datetime.fromtimestamp(entry_ts)
                    session = get_session(dt)
                except:
                    session = 'unknown'
            else:
                session = 'unknown'
            
            signals = trade.get('entry_signals', trade.get('signals', []))
            if not signals:
                signal_components = trade.get('signal_components', {})
                if isinstance(signal_components, dict):
                    signals = list(signal_components.keys())
            if isinstance(signals, str):
                signals = [signals]
            
            by_symbol[symbol]['trades'] += 1
            by_symbol[symbol]['wins'] += 1 if is_win else 0
            by_symbol[symbol]['pnl'] += pnl
            by_symbol[symbol]['trades_list'].append(trade)
            
            by_direction[direction]['trades'] += 1
            by_direction[direction]['wins'] += 1 if is_win else 0
            by_direction[direction]['pnl'] += pnl
            
            by_session[session]['trades'] += 1
            by_session[session]['wins'] += 1 if is_win else 0
            by_session[session]['pnl'] += pnl
            
            by_conviction[conviction]['trades'] += 1
            by_conviction[conviction]['wins'] += 1 if is_win else 0
            by_conviction[conviction]['pnl'] += pnl
            
            by_ofi_bucket[ofi_bucket]['trades'] += 1
            by_ofi_bucket[ofi_bucket]['wins'] += 1 if is_win else 0
            by_ofi_bucket[ofi_bucket]['pnl'] += pnl
            
            for sig in signals:
                by_signal[sig]['trades'] += 1
                by_signal[sig]['wins'] += 1 if is_win else 0
                by_signal[sig]['pnl'] += pnl
        
        def calc_metrics(d: Dict) -> Dict:
            for key, val in d.items():
                n = val['trades']
                val['win_rate'] = round(val['wins'] / n * 100, 1) if n > 0 else 0
                val['ev'] = round(val['pnl'] / n, 4) if n > 0 else 0
            return dict(d)
        
        self.results['executed_trades'] = {
            'total_trades': len(closed),
            'total_pnl': round(sum(self._get_pnl(t) for t in closed), 2),
            'overall_win_rate': round(sum(1 for t in closed if self._get_pnl(t) > 0) / len(closed) * 100, 1) if closed else 0,
            'by_symbol': calc_metrics(by_symbol),
            'by_direction': calc_metrics(by_direction),
            'by_session': calc_metrics(by_session),
            'by_signal': calc_metrics(by_signal),
            'by_conviction': calc_metrics(by_conviction),
            'by_ofi_bucket': calc_metrics(by_ofi_bucket),
        }
        
        print(f"   Total trades: {len(closed)}")
        print(f"   Total P&L: ${self.results['executed_trades']['total_pnl']:.2f}")
        print(f"   Win rate: {self.results['executed_trades']['overall_win_rate']}%")
        print()
    
    def _analyze_blocked_signals(self):
        """Analyze blocked signals and their counterfactual outcomes."""
        print("🚫 SECTION 2: BLOCKED SIGNALS ANALYSIS")
        print("-" * 50)
        
        blocked = self._filter_by_time(self.data.get('blocked_signals', []))
        
        by_reason = defaultdict(lambda: {'count': 0, 'would_profit': 0, 'would_loss': 0, 'potential_pnl': 0.0})
        by_symbol = defaultdict(lambda: {'count': 0, 'would_profit': 0, 'would_loss': 0, 'potential_pnl': 0.0})
        by_direction = defaultdict(lambda: {'count': 0, 'would_profit': 0, 'would_loss': 0, 'potential_pnl': 0.0})
        
        profitable_blocks = []
        
        for sig in blocked:
            reason = sig.get('block_reason', sig.get('reason', 'unknown'))
            symbol = sig.get('symbol', 'UNKNOWN')
            direction = sig.get('direction', sig.get('side', 'UNKNOWN'))
            
            counterfactual_pnl = sig.get('counterfactual_pnl', sig.get('potential_pnl', 0))
            would_profit = counterfactual_pnl > 0 if counterfactual_pnl else False
            
            by_reason[reason]['count'] += 1
            by_symbol[symbol]['count'] += 1
            by_direction[direction]['count'] += 1
            
            if would_profit:
                by_reason[reason]['would_profit'] += 1
                by_symbol[symbol]['would_profit'] += 1
                by_direction[direction]['would_profit'] += 1
                by_reason[reason]['potential_pnl'] += counterfactual_pnl
                by_symbol[symbol]['potential_pnl'] += counterfactual_pnl
                by_direction[direction]['potential_pnl'] += counterfactual_pnl
                profitable_blocks.append(sig)
            else:
                by_reason[reason]['would_loss'] += 1
                by_symbol[symbol]['would_loss'] += 1
                by_direction[direction]['would_loss'] += 1
        
        def calc_block_metrics(d: Dict) -> Dict:
            for key, val in d.items():
                n = val['count']
                val['profit_rate'] = round(val['would_profit'] / n * 100, 1) if n > 0 else 0
                val['avg_potential'] = round(val['potential_pnl'] / val['would_profit'], 2) if val['would_profit'] > 0 else 0
            return dict(d)
        
        self.results['blocked_signals'] = {
            'total_blocked': len(blocked),
            'would_have_profited': len(profitable_blocks),
            'missed_profit': round(sum(b.get('counterfactual_pnl', 0) for b in profitable_blocks), 2),
            'by_reason': calc_block_metrics(by_reason),
            'by_symbol': calc_block_metrics(by_symbol),
            'by_direction': calc_block_metrics(by_direction),
            'top_missed': sorted(profitable_blocks, key=lambda x: x.get('counterfactual_pnl', 0), reverse=True)[:10],
        }
        
        print(f"   Total blocked: {len(blocked)}")
        print(f"   Would have profited: {len(profitable_blocks)}")
        print(f"   Missed profit: ${self.results['blocked_signals']['missed_profit']:.2f}")
        print()
    
    def _analyze_missed_opportunities(self):
        """Analyze signals we didn't take that would have worked."""
        print("💎 SECTION 3: MISSED OPPORTUNITIES ANALYSIS")
        print("-" * 50)
        
        signal_outcomes = self._filter_by_time(self.data.get('signal_outcomes', []))
        
        missed = [s for s in signal_outcomes if s.get('disposition', '') in ['MISSED', 'NOT_TAKEN', 'FILTERED']]
        
        profitable_missed = []
        by_signal = defaultdict(lambda: {'count': 0, 'profitable': 0, 'total_potential': 0.0})
        by_symbol = defaultdict(lambda: {'count': 0, 'profitable': 0, 'total_potential': 0.0})
        
        for m in missed:
            signal_type = m.get('signal_type', m.get('signal', 'unknown'))
            symbol = m.get('symbol', 'UNKNOWN')
            
            pnl_1m = m.get('pnl_1m', 0)
            pnl_5m = m.get('pnl_5m', 0)
            pnl_15m = m.get('pnl_15m', 0)
            best_pnl = max(pnl_1m, pnl_5m, pnl_15m) if any([pnl_1m, pnl_5m, pnl_15m]) else 0
            
            by_signal[signal_type]['count'] += 1
            by_symbol[symbol]['count'] += 1
            
            if best_pnl > 0:
                by_signal[signal_type]['profitable'] += 1
                by_signal[signal_type]['total_potential'] += best_pnl
                by_symbol[symbol]['profitable'] += 1
                by_symbol[symbol]['total_potential'] += best_pnl
                profitable_missed.append({**m, 'best_pnl': best_pnl})
        
        def calc_missed_metrics(d: Dict) -> Dict:
            for key, val in d.items():
                n = val['count']
                val['hit_rate'] = round(val['profitable'] / n * 100, 1) if n > 0 else 0
                val['avg_potential'] = round(val['total_potential'] / val['profitable'], 4) if val['profitable'] > 0 else 0
            return dict(d)
        
        self.results['missed_opportunities'] = {
            'total_missed': len(missed),
            'profitable_missed': len(profitable_missed),
            'total_missed_profit': round(sum(m['best_pnl'] for m in profitable_missed), 2),
            'by_signal': calc_missed_metrics(by_signal),
            'by_symbol': calc_missed_metrics(by_symbol),
            'top_missed': sorted(profitable_missed, key=lambda x: x.get('best_pnl', 0), reverse=True)[:10],
        }
        
        print(f"   Total missed: {len(missed)}")
        print(f"   Profitable missed: {len(profitable_missed)}")
        print(f"   Total missed profit: ${self.results['missed_opportunities']['total_missed_profit']:.2f}")
        print()
    
    def _analyze_counter_intelligence(self):
        """What-if analysis: what if we took the opposite direction?"""
        print("🔄 SECTION 4: COUNTER INTELLIGENCE (Direction Analysis)")
        print("-" * 50)
        
        counterfactual = self._filter_by_time(self.data.get('counterfactual', []))
        closed = self._filter_by_time(self.data.get('closed_trades', []))
        
        by_symbol = defaultdict(lambda: {
            'our_pnl': 0.0, 'opposite_pnl': 0.0, 'trades': 0,
            'our_correct': 0, 'opposite_better': 0
        })
        by_direction = defaultdict(lambda: {
            'our_pnl': 0.0, 'opposite_pnl': 0.0, 'trades': 0,
            'our_correct': 0, 'opposite_better': 0
        })
        
        for trade in closed:
            symbol = trade.get('symbol', 'UNKNOWN')
            direction = trade.get('side', trade.get('direction', 'UNKNOWN'))
            our_pnl = self._get_pnl(trade)
            
            opposite_pnl = -our_pnl
            
            by_symbol[symbol]['trades'] += 1
            by_symbol[symbol]['our_pnl'] += our_pnl
            by_symbol[symbol]['opposite_pnl'] += opposite_pnl
            
            by_direction[direction]['trades'] += 1
            by_direction[direction]['our_pnl'] += our_pnl
            by_direction[direction]['opposite_pnl'] += opposite_pnl
            
            if our_pnl >= opposite_pnl:
                by_symbol[symbol]['our_correct'] += 1
                by_direction[direction]['our_correct'] += 1
            else:
                by_symbol[symbol]['opposite_better'] += 1
                by_direction[direction]['opposite_better'] += 1
        
        def calc_counter_metrics(d: Dict) -> Dict:
            for key, val in d.items():
                n = val['trades']
                val['direction_accuracy'] = round(val['our_correct'] / n * 100, 1) if n > 0 else 0
                val['our_ev'] = round(val['our_pnl'] / n, 4) if n > 0 else 0
                val['opposite_ev'] = round(val['opposite_pnl'] / n, 4) if n > 0 else 0
                val['ev_advantage'] = round(val['our_ev'] - val['opposite_ev'], 4)
            return dict(d)
        
        total_our = sum(v['our_pnl'] for v in by_symbol.values())
        total_opposite = sum(v['opposite_pnl'] for v in by_symbol.values())
        total_trades = sum(v['trades'] for v in by_symbol.values())
        total_correct = sum(v['our_correct'] for v in by_symbol.values())
        
        self.results['counter_intelligence'] = {
            'total_trades': total_trades,
            'direction_accuracy': round(total_correct / total_trades * 100, 1) if total_trades > 0 else 0,
            'our_total_pnl': round(total_our, 2),
            'opposite_total_pnl': round(total_opposite, 2),
            'by_symbol': calc_counter_metrics(by_symbol),
            'by_direction': calc_counter_metrics(by_direction),
            'symbols_to_invert': [
                k for k, v in by_symbol.items()
                if v['trades'] >= 5 and v['direction_accuracy'] < 45
            ],
        }
        
        print(f"   Direction accuracy: {self.results['counter_intelligence']['direction_accuracy']}%")
        print(f"   Our total P&L: ${total_our:.2f}")
        print(f"   Opposite would be: ${total_opposite:.2f}")
        if self.results['counter_intelligence']['symbols_to_invert']:
            print(f"   ⚠️ Consider inverting: {self.results['counter_intelligence']['symbols_to_invert']}")
        print()
    
    def _analyze_signal_weight_matrix(self):
        """Analyze every signal weight and score across all dimensions."""
        print("⚖️ SECTION 5: SIGNAL WEIGHT MATRIX")
        print("-" * 50)
        
        signal_outcomes = self.data.get('signal_outcomes', [])
        current_weights = self.data.get('signal_weights', {})
        gate_weights = self.data.get('signal_weights_gate', {}).get('weights', {})
        
        signal_performance = defaultdict(lambda: {
            'total': 0, 'wins': 0, 'pnl': 0.0,
            'by_direction': {'LONG': {'n': 0, 'wins': 0, 'pnl': 0.0}, 'SHORT': {'n': 0, 'wins': 0, 'pnl': 0.0}},
            'by_session': defaultdict(lambda: {'n': 0, 'wins': 0, 'pnl': 0.0}),
            'by_ofi': defaultdict(lambda: {'n': 0, 'wins': 0, 'pnl': 0.0}),
            'by_conviction': defaultdict(lambda: {'n': 0, 'wins': 0, 'pnl': 0.0}),
        })
        
        for outcome in signal_outcomes:
            signal_type = outcome.get('signal_type', outcome.get('signal', 'unknown'))
            direction = outcome.get('direction', 'UNKNOWN')
            
            pnl_5m = outcome.get('pnl_5m', 0)
            is_win = pnl_5m > 0 if pnl_5m else False
            
            signal_performance[signal_type]['total'] += 1
            signal_performance[signal_type]['wins'] += 1 if is_win else 0
            signal_performance[signal_type]['pnl'] += pnl_5m if pnl_5m else 0
            
            if direction in ['LONG', 'SHORT']:
                signal_performance[signal_type]['by_direction'][direction]['n'] += 1
                signal_performance[signal_type]['by_direction'][direction]['wins'] += 1 if is_win else 0
                signal_performance[signal_type]['by_direction'][direction]['pnl'] += pnl_5m if pnl_5m else 0
        
        signal_matrix = {}
        for sig, data in signal_performance.items():
            n = data['total']
            signal_matrix[sig] = {
                'current_weight': current_weights.get(sig, gate_weights.get(sig, 0)),
                'total_signals': n,
                'win_rate': round(data['wins'] / n * 100, 1) if n > 0 else 0,
                'total_pnl': round(data['pnl'], 2),
                'ev': round(data['pnl'] / n, 4) if n > 0 else 0,
                'by_direction': {
                    d: {
                        'n': v['n'],
                        'win_rate': round(v['wins'] / v['n'] * 100, 1) if v['n'] > 0 else 0,
                        'ev': round(v['pnl'] / v['n'], 4) if v['n'] > 0 else 0,
                    }
                    for d, v in data['by_direction'].items()
                },
            }
        
        positive_ev_signals = [s for s, d in signal_matrix.items() if d['ev'] > 0]
        negative_ev_signals = [s for s, d in signal_matrix.items() if d['ev'] < 0]
        
        optimal_weights = {}
        for sig, data in signal_matrix.items():
            ev = data['ev']
            if ev > 0.1:
                optimal_weights[sig] = min(0.25, data['current_weight'] * 1.2)
            elif ev > 0:
                optimal_weights[sig] = data['current_weight']
            elif ev > -0.05:
                optimal_weights[sig] = max(0.05, data['current_weight'] * 0.9)
            else:
                optimal_weights[sig] = max(0.03, data['current_weight'] * 0.7)
        
        total_weight = sum(optimal_weights.values())
        if total_weight > 0:
            optimal_weights = {k: round(v / total_weight, 4) for k, v in optimal_weights.items()}
        
        self.results['signal_weight_matrix'] = {
            'current_weights': current_weights or gate_weights,
            'signal_performance': signal_matrix,
            'positive_ev_signals': positive_ev_signals,
            'negative_ev_signals': negative_ev_signals,
            'recommended_weights': optimal_weights,
            'weight_changes': {
                sig: {
                    'current': signal_matrix.get(sig, {}).get('current_weight', 0),
                    'recommended': optimal_weights.get(sig, 0),
                    'change': round(optimal_weights.get(sig, 0) - signal_matrix.get(sig, {}).get('current_weight', 0), 4)
                }
                for sig in set(list(signal_matrix.keys()) + list(optimal_weights.keys()))
            }
        }
        
        print(f"   Signals analyzed: {len(signal_matrix)}")
        print(f"   Positive EV: {len(positive_ev_signals)}")
        print(f"   Negative EV: {len(negative_ev_signals)}")
        print()
    
    def _analyze_signal_combinations(self):
        """Analyze every combination of signals."""
        print("🔗 SECTION 6: SIGNAL COMBINATIONS ANALYSIS")
        print("-" * 50)
        
        closed = self._filter_by_time(self.data.get('closed_trades', []))
        
        combo_performance = defaultdict(lambda: {'trades': 0, 'wins': 0, 'pnl': 0.0})
        pair_performance = defaultdict(lambda: {'trades': 0, 'wins': 0, 'pnl': 0.0})
        triple_performance = defaultdict(lambda: {'trades': 0, 'wins': 0, 'pnl': 0.0})
        
        for trade in closed:
            signals = trade.get('entry_signals', trade.get('signals', []))
            if not signals:
                signal_components = trade.get('signal_components', {})
                if isinstance(signal_components, dict):
                    signals = list(signal_components.keys())
            if isinstance(signals, str):
                signals = [signals]
            if not signals:
                continue
            
            pnl = self._get_pnl(trade)
            is_win = pnl > 0
            
            combo_key = '+'.join(sorted(signals))
            combo_performance[combo_key]['trades'] += 1
            combo_performance[combo_key]['wins'] += 1 if is_win else 0
            combo_performance[combo_key]['pnl'] += pnl
            
            for pair in combinations(sorted(signals), 2):
                pair_key = '+'.join(pair)
                pair_performance[pair_key]['trades'] += 1
                pair_performance[pair_key]['wins'] += 1 if is_win else 0
                pair_performance[pair_key]['pnl'] += pnl
            
            if len(signals) >= 3:
                for triple in combinations(sorted(signals), 3):
                    triple_key = '+'.join(triple)
                    triple_performance[triple_key]['trades'] += 1
                    triple_performance[triple_key]['wins'] += 1 if is_win else 0
                    triple_performance[triple_key]['pnl'] += pnl
        
        def calc_combo_metrics(d: Dict, min_trades: int = 3) -> List[Dict]:
            results = []
            for combo, data in d.items():
                if data['trades'] >= min_trades:
                    wr = data['wins'] / data['trades'] * 100
                    ev = data['pnl'] / data['trades']
                    results.append({
                        'combination': combo,
                        'trades': data['trades'],
                        'win_rate': round(wr, 1),
                        'total_pnl': round(data['pnl'], 2),
                        'ev': round(ev, 4),
                    })
            return sorted(results, key=lambda x: x['ev'], reverse=True)
        
        self.results['signal_combinations'] = {
            'full_combos': calc_combo_metrics(combo_performance)[:20],
            'pairs': calc_combo_metrics(pair_performance)[:20],
            'triples': calc_combo_metrics(triple_performance)[:20],
            'best_combo': calc_combo_metrics(combo_performance)[0] if combo_performance else None,
            'worst_combo': calc_combo_metrics(combo_performance)[-1] if combo_performance else None,
            'best_pair': calc_combo_metrics(pair_performance)[0] if pair_performance else None,
        }
        
        print(f"   Unique combinations: {len(combo_performance)}")
        print(f"   Signal pairs: {len(pair_performance)}")
        print(f"   Signal triples: {len(triple_performance)}")
        if self.results['signal_combinations']['best_combo']:
            bc = self.results['signal_combinations']['best_combo']
            print(f"   Best combo: {bc['combination']} (EV=${bc['ev']:.4f}, WR={bc['win_rate']}%)")
        print()
    
    def _generate_recommendations(self):
        """Generate actionable recommendations based on analysis."""
        print("💡 SECTION 7: RECOMMENDATIONS")
        print("-" * 50)
        
        recommendations = []
        
        counter_intel = self.results.get('counter_intelligence', {})
        if counter_intel.get('symbols_to_invert'):
            for sym in counter_intel['symbols_to_invert']:
                sym_data = counter_intel.get('by_symbol', {}).get(sym, {})
                recommendations.append({
                    'priority': 'HIGH',
                    'category': 'direction',
                    'action': f'Consider inverting {sym} signals',
                    'reason': f"Direction accuracy only {sym_data.get('direction_accuracy', 0)}% with {sym_data.get('trades', 0)} trades",
                    'potential_impact': f"${abs(sym_data.get('our_pnl', 0) - sym_data.get('opposite_pnl', 0)):.2f} improvement",
                })
        
        signal_matrix = self.results.get('signal_weight_matrix', {})
        for sig in signal_matrix.get('negative_ev_signals', [])[:3]:
            sig_data = signal_matrix.get('signal_performance', {}).get(sig, {})
            if sig_data.get('total_signals', 0) >= 10:
                recommendations.append({
                    'priority': 'MEDIUM',
                    'category': 'weight',
                    'action': f'Reduce weight for {sig}',
                    'reason': f"Negative EV (${sig_data.get('ev', 0):.4f}) across {sig_data.get('total_signals', 0)} signals",
                    'potential_impact': 'Reduce loss exposure',
                })
        
        blocked = self.results.get('blocked_signals', {})
        if blocked.get('missed_profit', 0) > 50:
            top_reason = max(
                blocked.get('by_reason', {}).items(),
                key=lambda x: x[1].get('potential_pnl', 0),
                default=('unknown', {})
            )
            if top_reason[1].get('potential_pnl', 0) > 20:
                recommendations.append({
                    'priority': 'MEDIUM',
                    'category': 'filter',
                    'action': f"Review blocking reason: {top_reason[0]}",
                    'reason': f"Blocked {top_reason[1].get('count', 0)} signals that would have made ${top_reason[1].get('potential_pnl', 0):.2f}",
                    'potential_impact': f"Capture ${top_reason[1].get('potential_pnl', 0):.2f} more profit",
                })
        
        combos = self.results.get('signal_combinations', {})
        best_combo = combos.get('best_combo')
        if best_combo and best_combo.get('ev', 0) > 0.1:
            recommendations.append({
                'priority': 'LOW',
                'category': 'combo',
                'action': f"Prioritize signal combination: {best_combo['combination']}",
                'reason': f"Best performing combo with EV=${best_combo['ev']:.4f} and WR={best_combo['win_rate']}%",
                'potential_impact': 'Increase allocation to best combo',
            })
        
        self.results['recommendations'] = recommendations
        
        for rec in recommendations:
            priority_emoji = {'HIGH': '🔴', 'MEDIUM': '🟡', 'LOW': '🟢'}.get(rec['priority'], '⚪')
            print(f"   {priority_emoji} [{rec['priority']}] {rec['action']}")
            print(f"      Reason: {rec['reason']}")
        print()
    
    def _save_results(self):
        """Save results to feature store."""
        FEATURE_STORE.mkdir(exist_ok=True)
        output_path = FEATURE_STORE / 'comprehensive_analysis.json'
        save_json(str(output_path), self.results)
        print(f"💾 Results saved to: {output_path}")
    
    def _generate_report(self):
        """Generate human-readable markdown report."""
        OUTPUT_DIR.mkdir(exist_ok=True)
        date_str = self.now.strftime('%Y%m%d_%H%M')
        report_path = OUTPUT_DIR / f'comprehensive_evaluation_{date_str}.md'
        
        lines = [
            f"# Comprehensive Learning Evaluation",
            f"",
            f"**Run Time:** {self.now.isoformat()}",
            f"**Lookback:** {self.hours} hours",
            f"**Deep Dive:** {self.deep_dive}",
            f"",
            f"---",
            f"",
            f"## Executive Summary",
            f"",
            f"| Metric | Value |",
            f"|--------|-------|",
            f"| Total Trades | {self.results['executed_trades'].get('total_trades', 0)} |",
            f"| Total P&L | ${self.results['executed_trades'].get('total_pnl', 0):.2f} |",
            f"| Win Rate | {self.results['executed_trades'].get('overall_win_rate', 0)}% |",
            f"| Direction Accuracy | {self.results['counter_intelligence'].get('direction_accuracy', 0)}% |",
            f"| Missed Profit | ${self.results['blocked_signals'].get('missed_profit', 0):.2f} |",
            f"",
        ]
        
        lines.extend([
            f"## Recommendations",
            f"",
        ])
        for rec in self.results.get('recommendations', []):
            priority_badge = {'HIGH': '**HIGH**', 'MEDIUM': 'MEDIUM', 'LOW': 'LOW'}.get(rec['priority'], rec['priority'])
            lines.append(f"- [{priority_badge}] {rec['action']}")
            lines.append(f"  - *{rec['reason']}*")
            lines.append(f"  - Potential: {rec['potential_impact']}")
            lines.append("")
        
        lines.extend([
            f"## Signal Weight Matrix",
            f"",
            f"| Signal | Current Weight | Win Rate | EV | Recommended |",
            f"|--------|---------------|----------|-----|-------------|",
        ])
        for sig, data in self.results.get('signal_weight_matrix', {}).get('signal_performance', {}).items():
            rec_weight = self.results['signal_weight_matrix'].get('recommended_weights', {}).get(sig, 0)
            lines.append(f"| {sig} | {data.get('current_weight', 0):.2%} | {data.get('win_rate', 0)}% | ${data.get('ev', 0):.4f} | {rec_weight:.2%} |")
        lines.append("")
        
        lines.extend([
            f"## Best Signal Combinations",
            f"",
            f"| Combination | Trades | Win Rate | EV |",
            f"|-------------|--------|----------|-----|",
        ])
        for combo in self.results.get('signal_combinations', {}).get('full_combos', [])[:10]:
            lines.append(f"| {combo['combination']} | {combo['trades']} | {combo['win_rate']}% | ${combo['ev']:.4f} |")
        lines.append("")
        
        with open(report_path, 'w') as f:
            f.write('\n'.join(lines))
        
        print(f"📄 Report saved to: {report_path}")


def run_comprehensive_evaluation(hours: int = 24, deep_dive: bool = False) -> Dict:
    """Run comprehensive evaluation (main entry point)."""
    evaluator = ComprehensiveLearningEvaluation(hours=hours, deep_dive=deep_dive)
    return evaluator.run_full_evaluation()


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description='Comprehensive Learning Evaluation')
    parser.add_argument('--hours', type=int, default=24, help='Lookback hours')
    parser.add_argument('--deep-dive', action='store_true', help='Enable deep dive mode')
    args = parser.parse_args()
    
    run_comprehensive_evaluation(hours=args.hours, deep_dive=args.deep_dive)
