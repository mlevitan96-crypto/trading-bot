#!/usr/bin/env python3
"""
CONTINUOUS LEARNING CONTROLLER - Central Hub for All Learning
==============================================================
Coordinates all learning in the trading bot: capturing outcomes,
analyzing profitability, generating adjustments, and applying feedback.

ARCHITECTURE:
1. Capture Layer - Collects executed/blocked/missed outcomes
2. Profitability Analyzer - Multi-dimensional performance analysis
3. Adjustment Generator - Produces gate/weight/sizing updates  
4. Feedback Injector - Applies adjustments to system files
5. Cadence Control - Different frequencies for different updates
6. Safety Guardrails - Caps, minimums, rollback, dry-run

MAIN ENTRY POINTS:
- run_learning_cycle() - Complete learning cycle
- get_learning_state() - Current learning state
- apply_adjustments(dry_run=True) - Apply generated adjustments
- log_conviction_outcome(...) - Log a decision outcome

Usage:
    from src.continuous_learning_controller import ContinuousLearningController
    
    controller = ContinuousLearningController()
    state = controller.run_learning_cycle()
    controller.apply_adjustments(dry_run=False)
"""

import json
import os
import time
import threading
from datetime import datetime, timedelta, timezone
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple
from statistics import mean, stdev
from copy import deepcopy

from src.data_registry import DataRegistry as DR
from src.signal_outcome_tracker import signal_tracker
from src.signal_weight_learner import run_weight_update as run_signal_weight_update


LEARNING_STATE_FILE = Path("feature_store/learning_state.json")
SIGNAL_WEIGHTS_FILE = Path("feature_store/signal_weights.json")
BLOCKED_COMBOS_FILE = Path("feature_store/blocked_combos.json")
CONVICTION_GATE_LOG = Path("logs/conviction_gate.jsonl")
LEARNING_AUDIT_LOG = Path("logs/learning_audit.jsonl")
LEARNING_SNAPSHOTS_DIR = Path("logs/learning_snapshots")

LEARNING_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
LEARNING_SNAPSHOTS_DIR.mkdir(parents=True, exist_ok=True)
LEARNING_AUDIT_LOG.parent.mkdir(parents=True, exist_ok=True)  # Ensure logs/ directory exists

SESSIONS = {
    'asia_morning': (0, 4),
    'europe_morning': (4, 8),
    'us_morning': (12, 16),
    'us_afternoon': (16, 20),
    'evening': (20, 24),
    'asia_night': (8, 12),
}

SIGNAL_COMPONENTS = [
    'ofi_momentum', 'funding', 'oi_velocity',
    'liquidation', 'whale_flow', 'fear_greed'
]

CONVICTION_LEVELS = ['ULTRA', 'HIGH', 'MEDIUM', 'LOW', 'REJECT']

REGIMES = ['Stable', 'Volatile', 'Choppy']

MIN_SAMPLES_FOR_ADJUSTMENT = 20
MAX_WEIGHT_CHANGE_PCT = 0.20
MAX_THRESHOLD_CHANGE_PCT = 0.15
KILL_COMBO_WR_THRESHOLD = 0.35
KILL_COMBO_MIN_TRADES = 20

_learning_lock = threading.Lock()


def _get_hour_session(hour: int) -> str:
    """Map UTC hour to trading session."""
    for session, (start, end) in SESSIONS.items():
        if start <= hour < end:
            return session
    return 'unknown'


def _load_json(path: Path, default: Any = None) -> Any:
    """Load JSON file with fallback."""
    try:
        if path.exists():
            return json.loads(path.read_text())
    except Exception as e:
        print(f"⚠️ [CLC] Error loading {path}: {e}")
    return default if default is not None else {}


def _save_json(path: Path, data: dict) -> bool:
    """Atomically save JSON file."""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix('.tmp')
        tmp.write_text(json.dumps(data, indent=2, default=str))
        tmp.rename(path)
        return True
    except Exception as e:
        print(f"⚠️ [CLC] Error saving {path}: {e}")
        return False


def _append_jsonl(path: Path, record: dict) -> bool:
    """Append record to JSONL file."""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, 'a') as f:
            f.write(json.dumps(record, default=str) + '\n')
        return True
    except Exception as e:
        print(f"⚠️ [CLC] Error appending to {path}: {e}")
        return False


def _load_jsonl(path: Path, max_age_hours: int = None, limit: int = None) -> List[dict]:
    """Load JSONL file with optional filtering."""
    records = []
    if not path.exists():
        return records
    
    cutoff_ts = None
    if max_age_hours:
        cutoff_ts = (datetime.utcnow() - timedelta(hours=max_age_hours)).timestamp()
    
    try:
        with open(path, 'r') as f:
            for line in f:
                try:
                    rec = json.loads(line.strip())
                    if cutoff_ts:
                        ts = rec.get('ts') or rec.get('timestamp', 0)
                        if isinstance(ts, str):
                            try:
                                ts = datetime.fromisoformat(ts.replace('Z', '+00:00')).timestamp()
                            except:
                                ts = time.time()
                        if ts < cutoff_ts:
                            continue
                    records.append(rec)
                except:
                    continue
    except:
        pass
    
    if limit and len(records) > limit:
        records = records[-limit:]
    return records


class CaptureLayer:
    """
    Captures all outcomes for learning:
    - Executed trades (from positions_futures.json)
    - Blocked trades with counterfactuals
    - Missed opportunities
    """
    
    def __init__(self):
        self.executed_cache = []
        self.blocked_cache = []
        self.missed_cache = []
    
    def load_executed_trades(self, hours: int = 168) -> List[dict]:
        """Load executed trades from canonical positions file.
        
        Excludes bad trades from December 18, 2025 1:00 AM - 6:00 AM UTC
        (per MEMORY_BANK.md - bad trades window that should be ignored).
        """
        try:
            data = DR.read_json(DR.POSITIONS_FUTURES)
            if not data:
                return []
            
            closed = data.get('closed_positions', [])
            cutoff = (datetime.utcnow() - timedelta(hours=hours)).timestamp()
            
            # Bad trades window: Dec 18, 2025 1:00 AM - 6:00 AM UTC
            # These trades should be excluded from all analysis
            bad_trades_start = datetime(2025, 12, 18, 1, 0, 0, tzinfo=timezone.utc).timestamp()
            bad_trades_end = datetime(2025, 12, 18, 6, 0, 0, tzinfo=timezone.utc).timestamp()
            
            executed = []
            excluded_bad = 0
            
            for pos in closed:
                ts_str = pos.get('closed_at') or pos.get('opened_at', '')
                try:
                    if isinstance(ts_str, str):
                        ts = datetime.fromisoformat(ts_str.replace('Z', '+00:00')).timestamp()
                    else:
                        ts = float(ts_str) if ts_str else 0
                except:
                    ts = 0
                
                # Exclude bad trades window (Dec 18, 2025 1:00 AM - 6:00 AM UTC)
                if bad_trades_start <= ts <= bad_trades_end:
                    excluded_bad += 1
                    continue
                
                if ts >= cutoff:
                    pnl = pos.get('net_pnl', pos.get('pnl', 0))
                    roi = pos.get('net_roi', pos.get('final_roi', 0))
                    
                    executed.append({
                        'symbol': pos.get('symbol', ''),
                        'direction': pos.get('direction', ''),
                        'pnl': float(pnl) if pnl else 0,
                        'roi': float(roi) if roi else 0,
                        'won': float(pnl) > 0 if pnl else False,
                        'strategy': pos.get('strategy', ''),
                        'leverage': pos.get('leverage', 1),
                        'margin': pos.get('margin_collateral', 0),
                        'entry_price': pos.get('entry_price', 0),
                        'exit_price': pos.get('exit_price', 0),
                        'opened_at': pos.get('opened_at', ''),
                        'closed_at': pos.get('closed_at', ''),
                        'close_reason': pos.get('close_reason', ''),
                        'bot_type': pos.get('bot_type', 'alpha'),
                        'ts': ts
                    })
            
            if excluded_bad > 0:
                print(f"⚠️ [CLC] Excluded {excluded_bad} bad trades from Dec 18, 2025 1:00-6:00 AM UTC window")
            
            self.executed_cache = executed
            return executed
        except Exception as e:
            print(f"⚠️ [CLC] Error loading executed trades: {e}")
            return []
    
    def load_blocked_signals(self, hours: int = 168) -> List[dict]:
        """Load blocked signals from conviction gate log."""
        records = _load_jsonl(CONVICTION_GATE_LOG, max_age_hours=hours)
        blocked = [r for r in records if not r.get('should_trade', True)]
        self.blocked_cache = blocked
        return blocked
    
    def load_counterfactual_outcomes(self) -> List[dict]:
        """Load counterfactual outcomes (what blocked trades would have done)."""
        data = _load_json(Path(DR.COUNTERFACTUAL_LEARNINGS))
        return data.get('symbol_adjustments', []) if data else []
    
    def load_missed_opportunities(self, hours: int = 168) -> List[dict]:
        """Load missed opportunities from scanner."""
        records = _load_jsonl(Path(DR.MISSED_OPPORTUNITIES), max_age_hours=hours)
        self.missed_cache = records
        return records
    
    def get_sample_counts(self) -> dict:
        """Get counts of all sample types."""
        return {
            'executed': len(self.executed_cache),
            'blocked': len(self.blocked_cache),
            'counterfactual_tracked': len(self.load_counterfactual_outcomes()),
            'missed_found': len(self.missed_cache)
        }


class ProfitabilityAnalyzer:
    """
    Analyzes profitability across multiple dimensions:
    - Symbol + Direction
    - Hour / Session
    - Market Regime
    - Conviction Level
    - Signal Component
    """
    
    def __init__(self, executed_trades: List[dict]):
        self.trades = executed_trades
    
    def _calculate_metrics(self, trades: List[dict]) -> dict:
        """Calculate standard metrics for a group of trades."""
        if not trades:
            return {
                'n': 0, 'win_rate': 0, 'total_pnl': 0,
                'expected_value': 0, 'avg_winner': 0, 'avg_loser': 0
            }
        
        n = len(trades)
        wins = [t for t in trades if t.get('won', False)]
        losses = [t for t in trades if not t.get('won', False)]
        
        win_rate = len(wins) / n if n > 0 else 0
        total_pnl = sum(t.get('pnl', 0) for t in trades)
        ev = total_pnl / n if n > 0 else 0
        
        avg_winner = mean([t.get('pnl', 0) for t in wins]) if wins else 0
        avg_loser = mean([t.get('pnl', 0) for t in losses]) if losses else 0
        
        return {
            'n': n,
            'win_rate': round(win_rate * 100, 2),
            'total_pnl': round(total_pnl, 2),
            'expected_value': round(ev, 4),
            'avg_winner': round(avg_winner, 2),
            'avg_loser': round(avg_loser, 2)
        }
    
    def analyze_by_symbol_direction(self) -> dict:
        """Analyze profitability by symbol + direction combo."""
        groups = defaultdict(list)
        for t in self.trades:
            key = f"{t.get('symbol', 'UNK')}_{t.get('direction', 'UNK')}"
            groups[key].append(t)
        
        return {k: self._calculate_metrics(v) for k, v in groups.items()}
    
    def analyze_by_hour(self) -> dict:
        """Analyze profitability by hour of day."""
        groups = defaultdict(list)
        for t in self.trades:
            ts_str = t.get('opened_at', '')
            try:
                if isinstance(ts_str, str) and ts_str:
                    dt = datetime.fromisoformat(ts_str.replace('Z', '+00:00'))
                    hour = dt.hour
                else:
                    hour = 0
            except:
                hour = 0
            groups[f"hour_{hour}"].append(t)
        
        return {k: self._calculate_metrics(v) for k, v in groups.items()}
    
    def analyze_by_session(self) -> dict:
        """Analyze profitability by trading session."""
        groups = defaultdict(list)
        for t in self.trades:
            ts_str = t.get('opened_at', '')
            try:
                if isinstance(ts_str, str) and ts_str:
                    dt = datetime.fromisoformat(ts_str.replace('Z', '+00:00'))
                    session = _get_hour_session(dt.hour)
                else:
                    session = 'unknown'
            except:
                session = 'unknown'
            groups[session].append(t)
        
        return {k: self._calculate_metrics(v) for k, v in groups.items()}
    
    def analyze_by_regime(self) -> dict:
        """Analyze profitability by market regime (from strategy field)."""
        groups = defaultdict(list)
        for t in self.trades:
            strategy = t.get('strategy', '')
            regime = 'Stable'
            if 'volatile' in strategy.lower():
                regime = 'Volatile'
            elif 'choppy' in strategy.lower():
                regime = 'Choppy'
            groups[regime].append(t)
        
        return {k: self._calculate_metrics(v) for k, v in groups.items()}
    
    def analyze_by_conviction(self) -> dict:
        """Analyze profitability by conviction level."""
        gate_log = _load_jsonl(CONVICTION_GATE_LOG, max_age_hours=168)
        conviction_map = {}
        for rec in gate_log:
            if rec.get('should_trade'):
                key = f"{rec.get('symbol', '')}_{rec.get('ts', '')}"
                conviction_map[key] = rec.get('conviction', 'MEDIUM')
        
        groups = defaultdict(list)
        for t in self.trades:
            ts_str = t.get('opened_at', '')
            symbol = t.get('symbol', '')
            key_prefix = f"{symbol}_"
            conviction = 'MEDIUM'
            for k, v in conviction_map.items():
                if k.startswith(key_prefix):
                    conviction = v
                    break
            groups[conviction].append(t)
        
        return {k: self._calculate_metrics(v) for k, v in groups.items()}
    
    def analyze_signal_component_contribution(self) -> dict:
        """Analyze which signal components contribute to winners vs losers."""
        gate_log = _load_jsonl(CONVICTION_GATE_LOG, max_age_hours=168)
        
        component_stats = {comp: {'winner_aligned': 0, 'loser_aligned': 0, 'total': 0} 
                          for comp in SIGNAL_COMPONENTS}
        
        signal_info = {}
        for rec in gate_log:
            if rec.get('should_trade'):
                signals = rec.get('signals', {})
                ts = rec.get('ts', '')
                symbol = rec.get('symbol', '')
                signal_info[f"{symbol}_{ts}"] = signals
        
        for t in self.trades:
            won = t.get('won', False)
            symbol = t.get('symbol', '')
            
            for key, signals in signal_info.items():
                if key.startswith(f"{symbol}_"):
                    for comp in SIGNAL_COMPONENTS:
                        comp_data = signals.get(comp, {})
                        if isinstance(comp_data, dict):
                            is_aligned = comp_data.get('aligned', False) or comp_data.get('signal') not in ['NEUTRAL', None]
                        else:
                            is_aligned = bool(comp_data)
                        
                        if is_aligned:
                            component_stats[comp]['total'] += 1
                            if won:
                                component_stats[comp]['winner_aligned'] += 1
                            else:
                                component_stats[comp]['loser_aligned'] += 1
                    break
        
        result = {}
        for comp, stats in component_stats.items():
            total = stats['total']
            if total > 0:
                win_contribution = stats['winner_aligned'] / total
                result[comp] = {
                    'total_aligned': total,
                    'winner_contribution': round(win_contribution * 100, 2),
                    'loser_contribution': round((1 - win_contribution) * 100, 2),
                    'predictive_lift': round((win_contribution - 0.5) * 2, 4)
                }
            else:
                result[comp] = {
                    'total_aligned': 0,
                    'winner_contribution': 50.0,
                    'loser_contribution': 50.0,
                    'predictive_lift': 0.0
                }
        
        return result
    
    def get_full_analysis(self) -> dict:
        """Get complete profitability analysis across all dimensions."""
        return {
            'by_symbol_dir': self.analyze_by_symbol_direction(),
            'by_hour': self.analyze_by_hour(),
            'by_session': self.analyze_by_session(),
            'by_regime': self.analyze_by_regime(),
            'by_conviction': self.analyze_by_conviction(),
            'by_signal_component': self.analyze_signal_component_contribution()
        }


class AdjustmentGenerator:
    """
    Generates specific adjustments based on profitability analysis:
    - Gate adjustments (loosen/tighten thresholds)
    - Signal weight changes
    - Killed combos list
    - Sizing tier calibration
    """
    
    def __init__(self, profitability: dict, sample_counts: dict):
        self.profitability = profitability
        self.sample_counts = sample_counts
        self.adjustments = []
    
    def generate_gate_adjustments(self) -> dict:
        """Generate gate threshold adjustments."""
        to_loosen = []
        to_tighten = []
        
        cf_data = _load_json(Path(DR.COUNTERFACTUAL_LEARNINGS))
        if cf_data:
            for gate_info in cf_data.get('gates_to_loosen', []):
                if gate_info.get('would_win_pct', 0) > 55:
                    to_loosen.append({
                        'gate': gate_info.get('gate'),
                        'reason': gate_info.get('recommendation'),
                        'blocked_count': gate_info.get('blocked', 0),
                        'would_win_pct': gate_info.get('would_win_pct'),
                        'suggested_change': -0.05
                    })
            
            for gate_info in cf_data.get('gates_to_tighten', []):
                to_tighten.append({
                    'gate': gate_info.get('gate'),
                    'reason': gate_info.get('recommendation'),
                    'suggested_change': 0.05
                })
        
        by_hour = self.profitability.get('by_hour', {})
        for hour_key, metrics in by_hour.items():
            if metrics['n'] >= MIN_SAMPLES_FOR_ADJUSTMENT:
                if metrics['win_rate'] > 55 and metrics['expected_value'] > 0:
                    to_loosen.append({
                        'gate': hour_key,
                        'reason': f"High win rate {metrics['win_rate']}% with EV ${metrics['expected_value']}",
                        'metrics': metrics,
                        'suggested_change': -0.05
                    })
                elif metrics['win_rate'] < 40 and metrics['expected_value'] < 0:
                    to_tighten.append({
                        'gate': hour_key,
                        'reason': f"Low win rate {metrics['win_rate']}% with EV ${metrics['expected_value']}",
                        'metrics': metrics,
                        'suggested_change': 0.05
                    })
        
        return {
            'to_loosen': to_loosen,
            'to_tighten': to_tighten
        }
    
    def generate_weight_adjustments(self) -> dict:
        """Generate signal component weight adjustments."""
        by_component = self.profitability.get('by_signal_component', {})
        current_weights = _load_json(SIGNAL_WEIGHTS_FILE, {'weights': {}})
        weights = current_weights.get('weights', {})
        
        new_weights = dict(weights)
        adjustments = []
        
        for comp, stats in by_component.items():
            if stats['total_aligned'] >= MIN_SAMPLES_FOR_ADJUSTMENT:
                lift = stats['predictive_lift']
                current = weights.get(comp, 0.15)
                
                change = lift * 0.1
                change = max(-MAX_WEIGHT_CHANGE_PCT * current, 
                           min(MAX_WEIGHT_CHANGE_PCT * current, change))
                
                new_weight = max(0.02, min(0.5, current + change))
                
                if abs(change) > 0.001:
                    new_weights[comp] = round(new_weight, 4)
                    adjustments.append({
                        'component': comp,
                        'old_weight': current,
                        'new_weight': new_weight,
                        'change': round(change, 4),
                        'reason': f"Predictive lift: {lift:.2%}",
                        'confidence': min(1.0, stats['total_aligned'] / 50)
                    })
        
        total = sum(new_weights.values())
        if total > 0:
            new_weights = {k: round(v / total, 4) for k, v in new_weights.items()}
        
        return {
            'component_weights': new_weights,
            'adjustments': adjustments
        }
    
    def generate_killed_combos(self) -> List[dict]:
        """Identify symbol+direction combos that should be killed."""
        by_sym_dir = self.profitability.get('by_symbol_dir', {})
        killed = []
        
        for combo, metrics in by_sym_dir.items():
            if (metrics['n'] >= KILL_COMBO_MIN_TRADES and 
                metrics['win_rate'] < KILL_COMBO_WR_THRESHOLD * 100 and
                metrics['total_pnl'] < 0):
                
                killed.append({
                    'combo': combo,
                    'trades': metrics['n'],
                    'win_rate': metrics['win_rate'],
                    'total_pnl': metrics['total_pnl'],
                    'reason': f"Sustained poor performance: {metrics['win_rate']}% WR, ${metrics['total_pnl']} P&L"
                })
        
        return killed
    
    def generate_sizing_calibration(self) -> dict:
        """Calibrate conviction level to size multiplier based on realized edge."""
        by_conviction = self.profitability.get('by_conviction', {})
        
        base_map = {
            'ULTRA': 2.0,
            'HIGH': 1.5,
            'MEDIUM': 1.0,
            'LOW': 0.5,
            'REJECT': 0.0
        }
        
        calibrated = dict(base_map)
        
        for level, metrics in by_conviction.items():
            if level in calibrated and metrics['n'] >= MIN_SAMPLES_FOR_ADJUSTMENT:
                base = base_map.get(level, 1.0)
                
                ev = metrics['expected_value']
                if ev > 0.5:
                    adjustment = min(0.5, ev * 0.2)
                elif ev < -0.2:
                    adjustment = max(-0.5, ev * 0.5)
                else:
                    adjustment = 0
                
                calibrated[level] = round(max(0.0, min(3.0, base + adjustment)), 2)
        
        return calibrated
    
    def generate_all_adjustments(self) -> dict:
        """Generate all adjustment types."""
        gate_adj = self.generate_gate_adjustments()
        weight_adj = self.generate_weight_adjustments()
        killed = self.generate_killed_combos()
        sizing = self.generate_sizing_calibration()
        
        all_adj = []
        
        for item in gate_adj['to_loosen']:
            all_adj.append({
                'target': 'gate',
                'change': {'action': 'loosen', 'gate': item['gate'], 'delta': item.get('suggested_change', -0.05)},
                'reason': item['reason'],
                'confidence': 0.7,
                'applied': False
            })
        
        for item in gate_adj['to_tighten']:
            all_adj.append({
                'target': 'gate',
                'change': {'action': 'tighten', 'gate': item['gate'], 'delta': item.get('suggested_change', 0.05)},
                'reason': item['reason'],
                'confidence': 0.7,
                'applied': False
            })
        
        for adj in weight_adj.get('adjustments', []):
            all_adj.append({
                'target': 'weight',
                'change': {'component': adj['component'], 'new_weight': adj['new_weight']},
                'reason': adj['reason'],
                'confidence': adj['confidence'],
                'applied': False
            })
        
        for kill in killed:
            all_adj.append({
                'target': 'killed_combo',
                'change': {'combo': kill['combo']},
                'reason': kill['reason'],
                'confidence': 0.8,
                'applied': False
            })
        
        return {
            'gate_feedback': gate_adj,
            'weights': weight_adj,
            'killed_candidates': killed,
            'sizing': {'conviction_size_map': sizing},
            'adjustments': all_adj
        }


class FeedbackInjector:
    """
    Applies adjustments to system files:
    - feature_store/signal_weights.json
    - feature_store/blocked_combos.json
    - feature_store/learning_state.json
    """
    
    def __init__(self):
        self.applied_count = 0
        self.failed_count = 0
    
    def create_snapshot(self) -> str:
        """Create snapshot of current state before changes."""
        ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        snapshot = {
            'timestamp': ts,
            'signal_weights': _load_json(SIGNAL_WEIGHTS_FILE),
            'blocked_combos': _load_json(BLOCKED_COMBOS_FILE),
            'learning_state': _load_json(LEARNING_STATE_FILE)
        }
        
        snapshot_path = LEARNING_SNAPSHOTS_DIR / f"snapshot_{ts}.json"
        _save_json(snapshot_path, snapshot)
        return str(snapshot_path)
    
    def rollback_to_snapshot(self, snapshot_path: str) -> bool:
        """Rollback to a previous snapshot."""
        try:
            snapshot = _load_json(Path(snapshot_path))
            if not snapshot:
                return False
            
            if snapshot.get('signal_weights'):
                _save_json(SIGNAL_WEIGHTS_FILE, snapshot['signal_weights'])
            if snapshot.get('blocked_combos'):
                _save_json(BLOCKED_COMBOS_FILE, snapshot['blocked_combos'])
            if snapshot.get('learning_state'):
                _save_json(LEARNING_STATE_FILE, snapshot['learning_state'])
            
            return True
        except Exception as e:
            print(f"⚠️ [CLC] Rollback failed: {e}")
            return False
    
    def apply_weight_adjustments(self, weights: dict, dry_run: bool = True) -> bool:
        """Apply signal weight adjustments."""
        if dry_run:
            print(f"🔍 [DRY-RUN] Would update signal weights: {weights.get('component_weights', {})}")
            return True
        
        try:
            current = _load_json(SIGNAL_WEIGHTS_FILE, {'weights': {}})
            new_weights = weights.get('component_weights', {})
            
            current['weights'] = new_weights
            current['updated_at'] = datetime.utcnow().isoformat()
            current['adjustments'] = [a.get('reason', '') for a in weights.get('adjustments', [])][:5]
            current['source'] = 'continuous_learning_controller'
            
            return _save_json(SIGNAL_WEIGHTS_FILE, current)
        except Exception as e:
            print(f"⚠️ [CLC] Error applying weights: {e}")
            return False
    
    def apply_killed_combos(self, killed: List[dict], dry_run: bool = True) -> bool:
        """Apply killed combo updates."""
        if dry_run:
            combos = [k.get('combo') for k in killed]
            print(f"🔍 [DRY-RUN] Would add killed combos: {combos}")
            return True
        
        try:
            current = _load_json(BLOCKED_COMBOS_FILE, {'killed': [], 'updated_at': ''})
            existing = set(current.get('killed', []))
            
            for kill in killed:
                combo = kill.get('combo', '')
                if combo:
                    existing.add(combo)
            
            current['killed'] = list(existing)
            current['updated_at'] = datetime.utcnow().isoformat()
            current['last_additions'] = [k.get('combo') for k in killed]
            
            return _save_json(BLOCKED_COMBOS_FILE, current)
        except Exception as e:
            print(f"⚠️ [CLC] Error applying killed combos: {e}")
            return False
    
    def save_learning_state(self, state: dict, dry_run: bool = True) -> bool:
        """Save the complete learning state."""
        if dry_run:
            print(f"🔍 [DRY-RUN] Would save learning state with {len(state.get('adjustments', []))} adjustments")
            return True
        
        try:
            return _save_json(LEARNING_STATE_FILE, state)
        except Exception as e:
            print(f"⚠️ [CLC] Error saving learning state: {e}")
            return False
    
    def apply_all(self, adjustments: dict, dry_run: bool = True) -> Tuple[int, int]:
        """Apply all adjustments. Returns (applied_count, failed_count)."""
        applied = 0
        failed = 0
        
        if adjustments.get('weights', {}).get('component_weights'):
            if self.apply_weight_adjustments(adjustments['weights'], dry_run):
                applied += 1
            else:
                failed += 1
        
        if adjustments.get('killed_candidates'):
            if self.apply_killed_combos(adjustments['killed_candidates'], dry_run):
                applied += 1
            else:
                failed += 1
        
        self.applied_count = applied
        self.failed_count = failed
        return applied, failed


class CadenceController:
    """
    Manages different update frequencies:
    - Fast (30 min): gate adjustments, weights
    - Daily: killed combos, sizing
    - Weekly: structural rules
    """
    
    FAST_INTERVAL_SECONDS = 30 * 60
    DAILY_INTERVAL_SECONDS = 24 * 60 * 60
    WEEKLY_INTERVAL_SECONDS = 7 * 24 * 60 * 60
    
    def __init__(self):
        self.last_fast = 0
        self.last_daily = 0
        self.last_weekly = 0
        self._load_timestamps()
    
    def _load_timestamps(self):
        """Load last run timestamps from state."""
        state = _load_json(LEARNING_STATE_FILE)
        if state:
            cadence = state.get('cadence', {})
            self.last_fast = cadence.get('last_fast', 0)
            self.last_daily = cadence.get('last_daily', 0)
            self.last_weekly = cadence.get('last_weekly', 0)
    
    def _save_timestamps(self):
        """Save timestamps to state."""
        state = _load_json(LEARNING_STATE_FILE, {})
        state['cadence'] = {
            'last_fast': self.last_fast,
            'last_daily': self.last_daily,
            'last_weekly': self.last_weekly
        }
        _save_json(LEARNING_STATE_FILE, state)
    
    def should_run_fast(self) -> bool:
        """Check if fast loop should run."""
        return time.time() - self.last_fast >= self.FAST_INTERVAL_SECONDS
    
    def should_run_daily(self) -> bool:
        """Check if daily loop should run."""
        return time.time() - self.last_daily >= self.DAILY_INTERVAL_SECONDS
    
    def should_run_weekly(self) -> bool:
        """Check if weekly loop should run."""
        return time.time() - self.last_weekly >= self.WEEKLY_INTERVAL_SECONDS
    
    def mark_fast_complete(self):
        """Mark fast loop as complete."""
        self.last_fast = time.time()
        self._save_timestamps()
    
    def mark_daily_complete(self):
        """Mark daily loop as complete."""
        self.last_daily = time.time()
        self._save_timestamps()
    
    def mark_weekly_complete(self):
        """Mark weekly loop as complete."""
        self.last_weekly = time.time()
        self._save_timestamps()
    
    def get_pending_cycles(self) -> List[str]:
        """Get list of cycles that should run."""
        pending = []
        if self.should_run_fast():
            pending.append('fast')
        if self.should_run_daily():
            pending.append('daily')
        if self.should_run_weekly():
            pending.append('weekly')
        return pending


class ContinuousLearningController:
    """
    Main controller that coordinates all learning components.
    
    Usage:
        controller = ContinuousLearningController()
        state = controller.run_learning_cycle()
        controller.apply_adjustments(dry_run=False)
    """
    
    def __init__(self, lookback_hours: int = 168):
        self.lookback_hours = lookback_hours
        self.capture = CaptureLayer()
        self.cadence = CadenceController()
        self.injector = FeedbackInjector()
        self.current_state = None
        self.pending_adjustments = None
    
    def run_learning_cycle(self, force: bool = False) -> dict:
        """
        Run a complete learning cycle.
        
        Args:
            force: If True, run all cycles regardless of cadence
        
        Returns:
            Complete learning state dict
        """
        with _learning_lock:
            print("🧠 [CLC] Starting learning cycle...")
            
            try:
                resolved_count = signal_tracker.resolve_pending_signals()
                if resolved_count > 0:
                    print(f"📊 [CLC] Resolved {resolved_count} pending signal outcomes")
            except Exception as e:
                print(f"⚠️ [CLC] Signal resolution error: {e}")
            
            executed = self.capture.load_executed_trades(hours=self.lookback_hours)
            blocked = self.capture.load_blocked_signals(hours=self.lookback_hours)
            missed = self.capture.load_missed_opportunities(hours=self.lookback_hours)
            sample_counts = self.capture.get_sample_counts()
            
            print(f"📊 [CLC] Loaded {sample_counts['executed']} executed, {sample_counts['blocked']} blocked")
            
            analyzer = ProfitabilityAnalyzer(executed)
            profitability = analyzer.get_full_analysis()
            
            generator = AdjustmentGenerator(profitability, sample_counts)
            adjustments = generator.generate_all_adjustments()
            
            try:
                signal_weight_result = run_signal_weight_update(dry_run=False)
                if signal_weight_result.get('status') == 'success':
                    print(f"⚖️ [CLC] Signal weights updated based on {signal_weight_result.get('summary', {}).get('total_outcomes', 0)} outcomes")
            except Exception as e:
                print(f"⚠️ [CLC] Signal weight update error: {e}")
                signal_weight_result = {}
            
            try:
                from src.enhanced_signal_learner import run_direction_learning
                direction_recs = run_direction_learning()
                if direction_recs:
                    print(f"🔄 [CLC] Direction routing evaluated: {len(direction_recs)} recommendations")
            except Exception as e:
                print(f"⚠️ [CLC] Direction learning error: {e}")
            
            pending = self.cadence.get_pending_cycles()
            if force:
                pending = ['fast', 'daily', 'weekly']
            
            state = {
                'generated_at': datetime.utcnow().isoformat(),
                'samples': sample_counts,
                'profitability': profitability,
                'gate_feedback': adjustments['gate_feedback'],
                'weights': adjustments['weights'],
                'sizing': adjustments['sizing'],
                'adjustments': adjustments['adjustments'],
                'pending_cycles': pending,
                'cadence': {
                    'last_fast': self.cadence.last_fast,
                    'last_daily': self.cadence.last_daily,
                    'last_weekly': self.cadence.last_weekly
                }
            }
            
            self.current_state = state
            self.pending_adjustments = adjustments
            
            _append_jsonl(LEARNING_AUDIT_LOG, {
                'event': 'learning_cycle_complete',
                'ts': time.time(),
                'samples': sample_counts,
                'adjustments_generated': len(adjustments['adjustments']),
                'pending_cycles': pending
            })
            
            print(f"✅ [CLC] Learning cycle complete. {len(adjustments['adjustments'])} adjustments generated.")
            return state
    
    def apply_adjustments(self, dry_run: bool = True) -> dict:
        """
        Apply pending adjustments to system files.
        
        Args:
            dry_run: If True, only simulate changes
        
        Returns:
            Summary of applied changes
        """
        if not self.pending_adjustments:
            print("⚠️ [CLC] No pending adjustments. Run learning cycle first.")
            return {'status': 'no_adjustments', 'applied': 0, 'failed': 0}
        
        with _learning_lock:
            snapshot_path = None
            if not dry_run:
                snapshot_path = self.injector.create_snapshot()
                print(f"📸 [CLC] Snapshot created: {snapshot_path}")
            
            applied, failed = self.injector.apply_all(self.pending_adjustments, dry_run)
            
            if self.current_state and not dry_run:
                for adj in self.current_state.get('adjustments', []):
                    adj['applied'] = True
                self.injector.save_learning_state(self.current_state, dry_run=False)
            
            pending = self.cadence.get_pending_cycles()
            if not dry_run:
                if 'fast' in pending:
                    self.cadence.mark_fast_complete()
                if 'daily' in pending:
                    self.cadence.mark_daily_complete()
                if 'weekly' in pending:
                    self.cadence.mark_weekly_complete()
            
            _append_jsonl(LEARNING_AUDIT_LOG, {
                'event': 'adjustments_applied',
                'ts': time.time(),
                'dry_run': dry_run,
                'applied': applied,
                'failed': failed,
                'snapshot_path': snapshot_path
            })
            
            status = 'dry_run' if dry_run else 'applied'
            print(f"{'🔍' if dry_run else '✅'} [CLC] {status.upper()}: {applied} applied, {failed} failed")
            
            return {
                'status': status,
                'applied': applied,
                'failed': failed,
                'snapshot_path': snapshot_path
            }
    
    def get_learning_state(self) -> dict:
        """Get current learning state from file or memory."""
        if self.current_state:
            return self.current_state
        return _load_json(LEARNING_STATE_FILE, {})
    
    def rollback(self, snapshot_path: str = None) -> bool:
        """Rollback to a previous snapshot."""
        if not snapshot_path:
            snapshots = sorted(LEARNING_SNAPSHOTS_DIR.glob("snapshot_*.json"))
            if not snapshots:
                print("⚠️ [CLC] No snapshots available for rollback")
                return False
            snapshot_path = str(snapshots[-1])
        
        success = self.injector.rollback_to_snapshot(snapshot_path)
        if success:
            print(f"✅ [CLC] Rolled back to {snapshot_path}")
            _append_jsonl(LEARNING_AUDIT_LOG, {
                'event': 'rollback',
                'ts': time.time(),
                'snapshot_path': snapshot_path,
                'success': True
            })
        return success


_outcome_log_file = Path("logs/conviction_outcomes.jsonl")


def log_conviction_outcome(
    symbol: str,
    direction: str,
    conviction: str,
    aligned_signals: int,
    executed: bool,
    outcome_pnl: float = 0.0,
    signal_components: Dict[str, bool] = None
) -> bool:
    """
    Log a conviction gate outcome for learning.
    
    Args:
        symbol: Trading symbol (e.g., 'BTCUSDT')
        direction: Trade direction ('LONG' or 'SHORT')
        conviction: Conviction level ('ULTRA', 'HIGH', 'MEDIUM', 'LOW', 'REJECT')
        aligned_signals: Number of aligned signals
        executed: Whether the trade was executed
        outcome_pnl: P&L if executed, counterfactual P&L if blocked
        signal_components: Dict of which components were aligned
    
    Returns:
        True if logged successfully
    """
    record = {
        'symbol': symbol,
        'direction': direction,
        'conviction': conviction,
        'aligned_signals': aligned_signals,
        'executed': executed,
        'outcome_pnl': outcome_pnl,
        'signal_components': signal_components or {},
        'ts': time.time(),
        'ts_iso': datetime.utcnow().isoformat(),
        'hour_utc': datetime.utcnow().hour,
        'session': _get_hour_session(datetime.utcnow().hour)
    }
    
    return _append_jsonl(_outcome_log_file, record)


def run_learning_cycle(force: bool = False) -> dict:
    """Convenience function to run a learning cycle."""
    controller = ContinuousLearningController()
    return controller.run_learning_cycle(force=force)


def get_learning_state() -> dict:
    """Convenience function to get current learning state."""
    controller = ContinuousLearningController()
    return controller.get_learning_state()


def apply_adjustments(dry_run: bool = True) -> dict:
    """Convenience function to apply adjustments."""
    controller = ContinuousLearningController()
    controller.run_learning_cycle()
    return controller.apply_adjustments(dry_run=dry_run)


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Continuous Learning Controller")
    parser.add_argument("--run", action="store_true", help="Run learning cycle")
    parser.add_argument("--apply", action="store_true", help="Apply adjustments")
    parser.add_argument("--dry-run", action="store_true", default=True, help="Dry run mode")
    parser.add_argument("--force", action="store_true", help="Force all cycles")
    parser.add_argument("--state", action="store_true", help="Show current state")
    parser.add_argument("--rollback", type=str, help="Rollback to snapshot path")
    
    args = parser.parse_args()
    
    controller = ContinuousLearningController()
    
    if args.state:
        state = controller.get_learning_state()
        print(json.dumps(state, indent=2, default=str))
    
    elif args.rollback:
        controller.rollback(args.rollback)
    
    elif args.run or args.apply:
        state = controller.run_learning_cycle(force=args.force)
        print(f"\n📊 Samples: {state['samples']}")
        print(f"📈 Adjustments: {len(state['adjustments'])}")
        
        if args.apply:
            result = controller.apply_adjustments(dry_run=args.dry_run)
            print(f"\n{'🔍 DRY-RUN' if args.dry_run else '✅ APPLIED'}: {result}")
    
    else:
        print("Continuous Learning Controller")
        print("=" * 50)
        print("\nUsage:")
        print("  python -m src.continuous_learning_controller --run")
        print("  python -m src.continuous_learning_controller --apply --dry-run")
        print("  python -m src.continuous_learning_controller --apply --no-dry-run")
        print("  python -m src.continuous_learning_controller --state")
        print("  python -m src.continuous_learning_controller --rollback <snapshot_path>")
