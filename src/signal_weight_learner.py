#!/usr/bin/env python3
"""
SIGNAL WEIGHT LEARNER - EV-Based Weight Auto-Updater
=====================================================
Automatically adjusts signal weights based on historical performance.
Signals that predict profitable moves get more weight.

ARCHITECTURE:
1. Read signal outcomes from logs/signal_outcomes.jsonl
2. Read current stats from feature_store/signal_stats.json
3. Calculate per-signal EV at each horizon
4. Determine optimal horizon for each signal
5. Adjust weights based on EV (higher EV = more weight)
6. Write updated weights to feature_store/signal_weights_gate.json

MAIN ENTRY POINTS:
- run_weight_update() - Execute weight update cycle
- SignalWeightLearner.calculate_signal_ev() - Get EV for a signal
- SignalWeightLearner.update_weights() - Recalculate all weights

Usage:
    from src.signal_weight_learner import run_weight_update
    result = run_weight_update()
"""

import json
import os
from datetime import datetime
from pathlib import Path
from collections import defaultdict
from typing import Dict, List, Optional, Any, Tuple
from statistics import mean, stdev


SIGNAL_OUTCOMES_FILE = Path("logs/signal_outcomes.jsonl")
SIGNAL_STATS_FILE = Path("feature_store/signal_stats.json")
SIGNAL_WEIGHTS_GATE_FILE = Path("feature_store/signal_weights_gate.json")

HORIZONS = ['1m', '5m', '15m', '30m', '1h']

DEFAULT_SIGNAL_WEIGHTS = {
    'liquidation': 0.22,
    'funding': 0.16,
    'oi_velocity': 0.05,
    'whale_flow': 0.20,
    'ofi_momentum': 0.06,
    'fear_greed': 0.06,
    'hurst': 0.08,
    'lead_lag': 0.08,
    'volatility_skew': 0.05,
    'oi_divergence': 0.04
}

MIN_SAMPLES_FOR_ADJUSTMENT = 50
MAX_WEIGHT_CHANGE_PCT = 0.20
MIN_WEIGHT_FLOOR = 0.05
MAX_HISTORY_ENTRIES = 100


def _load_json(path: Path, default: Any = None) -> Any:
    """Load JSON file with fallback."""
    try:
        if path.exists():
            return json.loads(path.read_text())
    except Exception as e:
        print(f"⚠️ [SignalWeightLearner] Error loading {path}: {e}")
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
        print(f"⚠️ [SignalWeightLearner] Error saving {path}: {e}")
        return False


def _load_jsonl(path: Path) -> List[dict]:
    """Load JSONL file."""
    records = []
    if not path.exists():
        return records
    try:
        with open(path, 'r') as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        records.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue
    except Exception as e:
        print(f"⚠️ [SignalWeightLearner] Error loading JSONL {path}: {e}")
    return records


class SignalWeightLearner:
    """
    EV-based signal weight learner.
    
    Reads historical signal outcomes and adjusts weights based on 
    which signals predict profitable moves most accurately.
    """
    
    def __init__(self):
        self.outcomes: List[dict] = []
        self.stats: dict = {}
        self.current_weights: Dict[str, float] = dict(DEFAULT_SIGNAL_WEIGHTS)
        self.signal_evs: Dict[str, Dict[str, float]] = {}
        self.best_horizons: Dict[str, str] = {}
        self.disagreement_tracker: Dict[str, Dict[str, int]] = defaultdict(lambda: defaultdict(int))
        
        self._load_data()
    
    def _load_data(self):
        """Load all required data sources."""
        self.outcomes = _load_jsonl(SIGNAL_OUTCOMES_FILE)
        self.stats = _load_json(SIGNAL_STATS_FILE, {'signals': {}})
        
        gate_data = _load_json(SIGNAL_WEIGHTS_GATE_FILE)
        if gate_data and 'weights' in gate_data:
            self.current_weights = gate_data['weights']
        else:
            self.current_weights = dict(DEFAULT_SIGNAL_WEIGHTS)
        
        print(f"📊 [SignalWeightLearner] Loaded {len(self.outcomes)} outcomes, "
              f"{len(self.stats.get('signals', {}))} signal stats")
    
    def _get_outcomes_for_signal(self, signal_name: str) -> List[dict]:
        """Get all outcomes for a specific signal."""
        return [o for o in self.outcomes if o.get('signal_name') == signal_name]
    
    def calculate_signal_ev(self, signal_name: str, horizon: str = '5m') -> float:
        """
        Calculate Expected Value for a signal at a specific horizon.
        
        EV = (Win Rate * Avg Win) - (Loss Rate * Avg Loss)
        
        For directional signals:
        - Win = price moved in predicted direction
        - Measure both accuracy (did it move right way?) and magnitude (how much?)
        
        Args:
            signal_name: Name of the signal (e.g., 'funding', 'whale_flow')
            horizon: Time horizon ('1m', '5m', '15m', '30m', '1h')
        
        Returns:
            Expected value as a float (can be negative)
        """
        outcomes = self._get_outcomes_for_signal(signal_name)
        
        if not outcomes:
            stats = self.stats.get('signals', {}).get(signal_name, {})
            return stats.get(f'ev_{horizon}', 0.0)
        
        wins = []
        losses = []
        
        for outcome in outcomes:
            returns = outcome.get('returns', {})
            hits = outcome.get('hits', {})
            
            ret = returns.get(horizon, 0)
            hit = hits.get(horizon, False)
            
            direction = outcome.get('direction', 'LONG')
            
            if direction == 'LONG':
                actual_return = ret
            else:
                actual_return = -ret
            
            if hit:
                wins.append(abs(actual_return))
            else:
                losses.append(abs(actual_return))
        
        total = len(wins) + len(losses)
        if total == 0:
            return 0.0
        
        win_rate = len(wins) / total
        loss_rate = 1 - win_rate
        
        avg_win = mean(wins) if wins else 0.0
        avg_loss = mean(losses) if losses else 0.0
        
        ev = (win_rate * avg_win) - (loss_rate * avg_loss)
        
        return ev
    
    def calculate_all_evs(self) -> Dict[str, Dict[str, float]]:
        """
        Calculate EV for all signals across all horizons.
        
        Returns:
            Dict mapping signal_name -> {horizon -> ev}
        """
        all_signals = set(DEFAULT_SIGNAL_WEIGHTS.keys())
        
        for outcome in self.outcomes:
            signal_name = outcome.get('signal_name')
            if signal_name:
                all_signals.add(signal_name)
        
        for signal_name in self.stats.get('signals', {}).keys():
            all_signals.add(signal_name)
        
        result = {}
        for signal_name in all_signals:
            result[signal_name] = {}
            for horizon in HORIZONS:
                ev = self.calculate_signal_ev(signal_name, horizon)
                result[signal_name][horizon] = round(ev, 6)
        
        self.signal_evs = result
        return result
    
    def determine_best_horizon(self, signal_name: str) -> Tuple[str, float]:
        """
        Determine which horizon works best for a signal.
        
        Returns:
            Tuple of (best_horizon, best_ev)
        """
        if signal_name not in self.signal_evs:
            self.calculate_all_evs()
        
        evs = self.signal_evs.get(signal_name, {})
        
        if not evs:
            return ('5m', 0.0)
        
        best_horizon = max(evs.keys(), key=lambda h: evs[h])
        best_ev = evs[best_horizon]
        
        return (best_horizon, best_ev)
    
    def determine_all_best_horizons(self) -> Dict[str, Tuple[str, float]]:
        """
        Determine best horizon for all signals.
        
        Returns:
            Dict mapping signal_name -> (best_horizon, best_ev)
        """
        if not self.signal_evs:
            self.calculate_all_evs()
        
        result = {}
        for signal_name in self.signal_evs:
            result[signal_name] = self.determine_best_horizon(signal_name)
            self.best_horizons[signal_name] = result[signal_name][0]
        
        return result
    
    def track_signal_disagreements(self) -> Dict[str, Dict[str, Any]]:
        """
        Track disagreements between signals and which one was right.
        
        Analyzes cases where signals gave conflicting directions
        and records which signal's prediction was correct.
        """
        outcome_by_ts = defaultdict(list)
        for outcome in self.outcomes:
            ts = outcome.get('ts', '')
            symbol = outcome.get('symbol', '')
            key = f"{symbol}_{ts[:16]}"
            outcome_by_ts[key].append(outcome)
        
        disagreement_stats: Dict[str, Dict[str, Any]] = {}
        
        def get_or_create_stats(signal: str) -> Dict[str, Any]:
            if signal not in disagreement_stats:
                disagreement_stats[signal] = {
                    'total_disagreements': 0,
                    'wins_when_disagreed': 0,
                    'signals_disagreed_with': {}
                }
            return disagreement_stats[signal]
        
        for key, outcomes in outcome_by_ts.items():
            if len(outcomes) < 2:
                continue
            
            directions = [(o.get('signal_name'), o.get('direction'), o.get('hits', {}).get('5m', False)) 
                         for o in outcomes]
            
            for i, (sig1, dir1, hit1) in enumerate(directions):
                for j, (sig2, dir2, hit2) in enumerate(directions):
                    if i >= j:
                        continue
                    if dir1 != dir2 and sig1 and sig2:
                        stats1 = get_or_create_stats(sig1)
                        stats2 = get_or_create_stats(sig2)
                        stats1['total_disagreements'] += 1
                        stats2['total_disagreements'] += 1
                        
                        if hit1 and not hit2:
                            stats1['wins_when_disagreed'] += 1
                            stats1['signals_disagreed_with'][sig2] = stats1['signals_disagreed_with'].get(sig2, 0) + 1
                        elif hit2 and not hit1:
                            stats2['wins_when_disagreed'] += 1
                            stats2['signals_disagreed_with'][sig1] = stats2['signals_disagreed_with'].get(sig1, 0) + 1
        
        result = {}
        for signal, stats in disagreement_stats.items():
            total = stats['total_disagreements']
            wins = stats['wins_when_disagreed']
            result[signal] = {
                'total_disagreements': total,
                'wins_when_disagreed': wins,
                'disagreement_win_rate': round(wins / total, 4) if total > 0 else 0.5,
                'often_disagrees_with': dict(stats['signals_disagreed_with'])
            }
        
        return result
    
    def get_sample_counts(self) -> Dict[str, int]:
        """Get sample count for each signal."""
        counts = defaultdict(int)
        for outcome in self.outcomes:
            signal_name = outcome.get('signal_name')
            if signal_name:
                counts[signal_name] += 1
        
        for signal_name in DEFAULT_SIGNAL_WEIGHTS:
            if signal_name not in counts:
                stats = self.stats.get('signals', {}).get(signal_name, {})
                counts[signal_name] = stats.get('n', 0)
        
        return dict(counts)
    
    def update_weights(self) -> Dict[str, float]:
        """
        Update weights based on calculated EVs.
        
        Logic:
        1. Calculate EV for each signal at best horizon
        2. Normalize EVs to [0, 1] range
        3. Apply bounded adjustment: max ±20% change per cycle
        4. Ensure weights sum to 1.0
        5. Write to signal_weights_gate.json
        
        Returns:
            New weights dict
        """
        best_horizons = self.determine_all_best_horizons()
        sample_counts = self.get_sample_counts()
        disagreement_stats = self.track_signal_disagreements()
        
        new_weights = dict(self.current_weights)
        reasoning = {}
        signals_with_data = []
        signals_no_data = []
        
        for signal_name in DEFAULT_SIGNAL_WEIGHTS:
            sample_count = sample_counts.get(signal_name, 0)
            
            if sample_count < MIN_SAMPLES_FOR_ADJUSTMENT:
                signals_no_data.append(signal_name)
                reasoning[signal_name] = f"Insufficient data ({sample_count} < {MIN_SAMPLES_FOR_ADJUSTMENT} samples), keeping current weight"
                continue
            
            signals_with_data.append(signal_name)
            
            best_horizon, best_ev = best_horizons.get(signal_name, ('5m', 0.0))
            
            current_weight = self.current_weights.get(signal_name, DEFAULT_SIGNAL_WEIGHTS.get(signal_name, 0.10))
            
            if best_ev > 0:
                adjustment = min(MAX_WEIGHT_CHANGE_PCT, best_ev * 10)
            else:
                adjustment = max(-MAX_WEIGHT_CHANGE_PCT, best_ev * 10)
            
            disagreement_bonus = 0.0
            if signal_name in disagreement_stats:
                dwr = disagreement_stats[signal_name].get('disagreement_win_rate', 0.5)
                if dwr > 0.55:
                    disagreement_bonus = min(0.05, (dwr - 0.5) * 0.2)
                elif dwr < 0.45:
                    disagreement_bonus = max(-0.05, (dwr - 0.5) * 0.2)
            
            total_adjustment = adjustment + disagreement_bonus
            total_adjustment = max(-MAX_WEIGHT_CHANGE_PCT, min(MAX_WEIGHT_CHANGE_PCT, total_adjustment))
            
            # Apply venue-aware clamping during initial learning period
            try:
                from src.learning_venue_migration import VenueMigrationManager
                migration_manager = VenueMigrationManager()
                clamp_multiplier = migration_manager.get_learning_clamp_multiplier()
                
                # Clamp adjustment to max ±10% during initial learning period
                if clamp_multiplier < 1.0:
                    venue_max_change = 0.10  # 10% max during initial period
                    clamped_adjustment = max(-venue_max_change, min(venue_max_change, total_adjustment * clamp_multiplier))
                    if abs(clamped_adjustment) < abs(total_adjustment):
                        total_adjustment = clamped_adjustment
            except Exception:
                pass  # If venue migration not available, use normal adjustment
            
            new_weight = current_weight * (1 + total_adjustment)
            new_weight = max(MIN_WEIGHT_FLOOR, new_weight)
            
            new_weights[signal_name] = new_weight
            
            change_pct = ((new_weight / current_weight) - 1) * 100 if current_weight > 0 else 0
            direction = "increased" if change_pct > 0 else "decreased"
            reasoning[signal_name] = f"EV={best_ev:.4f}, best_horizon={best_horizon}, {direction} {abs(change_pct):.1f}%"
        
        total = sum(new_weights.values())
        if total > 0:
            new_weights = {k: round(v / total, 4) for k, v in new_weights.items()}
        
        self._save_weights(new_weights, reasoning, signals_with_data, signals_no_data)
        
        self.current_weights = new_weights
        return new_weights
    
    def _save_weights(self, weights: Dict[str, float], reasoning: Dict[str, str],
                     signals_with_data: List[str], signals_no_data: List[str]):
        """Save weights to signal_weights_gate.json with full metadata."""
        existing = _load_json(SIGNAL_WEIGHTS_GATE_FILE, {})
        
        history = existing.get('history', [])
        
        if existing.get('weights'):
            history.append({
                'ts': existing.get('updated_at', datetime.utcnow().isoformat()),
                'weights': existing.get('weights', {})
            })
        
        if len(history) > MAX_HISTORY_ENTRIES:
            history = history[-MAX_HISTORY_ENTRIES:]
        
        output = {
            'updated_at': datetime.utcnow().isoformat(),
            'weights': weights,
            'reasoning': reasoning,
            'data_quality': {
                'total_outcomes': len(self.outcomes),
                'signals_with_data': signals_with_data,
                'signals_no_data': signals_no_data,
                'min_samples_required': MIN_SAMPLES_FOR_ADJUSTMENT
            },
            'evs_by_horizon': self.signal_evs,
            'best_horizons': {k: {'horizon': v, 'ev': self.signal_evs.get(k, {}).get(v, 0)} 
                            for k, v in self.best_horizons.items()},
            'history': history,
            'config': {
                'max_weight_change_pct': MAX_WEIGHT_CHANGE_PCT,
                'min_weight_floor': MIN_WEIGHT_FLOOR,
                'min_samples': MIN_SAMPLES_FOR_ADJUSTMENT
            }
        }
        
        if _save_json(SIGNAL_WEIGHTS_GATE_FILE, output):
            print(f"✅ [SignalWeightLearner] Saved updated weights to {SIGNAL_WEIGHTS_GATE_FILE}")
        else:
            print(f"❌ [SignalWeightLearner] Failed to save weights")
    
    def get_learning_summary(self) -> dict:
        """Get a summary of current learning state."""
        best_horizons = self.determine_all_best_horizons()
        sample_counts = self.get_sample_counts()
        
        summary = {
            'total_outcomes': len(self.outcomes),
            'signals': {}
        }
        
        for signal_name in set(DEFAULT_SIGNAL_WEIGHTS.keys()) | set(self.signal_evs.keys()):
            horizon, ev = best_horizons.get(signal_name, ('5m', 0.0))
            summary['signals'][signal_name] = {
                'sample_count': sample_counts.get(signal_name, 0),
                'current_weight': self.current_weights.get(signal_name, 0),
                'best_horizon': horizon,
                'best_ev': ev,
                'has_enough_data': sample_counts.get(signal_name, 0) >= MIN_SAMPLES_FOR_ADJUSTMENT
            }
        
        return summary
    
    def analyze_signal_combinations(self) -> Dict[str, Any]:
        """
        Analyze which signal combinations work well together.
        
        Returns performance when multiple signals agree vs disagree.
        """
        outcome_by_ts = defaultdict(list)
        for outcome in self.outcomes:
            ts = outcome.get('ts', '')
            symbol = outcome.get('symbol', '')
            key = f"{symbol}_{ts[:16]}"
            outcome_by_ts[key].append(outcome)
        
        agreement_results = {
            'all_agree': {'wins': 0, 'total': 0},
            'majority_agree': {'wins': 0, 'total': 0},
            'split': {'wins': 0, 'total': 0}
        }
        
        combo_performance = defaultdict(lambda: {'wins': 0, 'total': 0})
        
        for key, outcomes in outcome_by_ts.items():
            if len(outcomes) < 2:
                continue
            
            long_signals = [o.get('signal_name') for o in outcomes if o.get('direction') == 'LONG']
            short_signals = [o.get('signal_name') for o in outcomes if o.get('direction') == 'SHORT']
            
            any_hit = any(o.get('hits', {}).get('5m', False) for o in outcomes)
            
            if len(long_signals) == len(outcomes) or len(short_signals) == len(outcomes):
                category = 'all_agree'
            elif len(long_signals) > len(outcomes) / 2 or len(short_signals) > len(outcomes) / 2:
                category = 'majority_agree'
            else:
                category = 'split'
            
            agreement_results[category]['total'] += 1
            if any_hit:
                agreement_results[category]['wins'] += 1
            
            combo_key = tuple(sorted([o.get('signal_name') for o in outcomes]))
            combo_performance[combo_key]['total'] += 1
            if any_hit:
                combo_performance[combo_key]['wins'] += 1
        
        result: Dict[str, Any] = {
            'agreement_analysis': {}
        }
        
        for cat, stats in agreement_results.items():
            total = stats['total']
            wins = stats['wins']
            result['agreement_analysis'][cat] = {
                'total': total,
                'wins': wins,
                'win_rate': round(wins / total, 4) if total > 0 else 0
            }
        
        best_combos = []
        for combo, stats in combo_performance.items():
            if stats['total'] >= 5:
                win_rate = stats['wins'] / stats['total']
                best_combos.append({
                    'signals': list(combo),
                    'total': stats['total'],
                    'win_rate': round(win_rate, 4)
                })
        
        best_combos.sort(key=lambda x: (-x['win_rate'], -x['total']))
        result['best_combinations'] = best_combos[:10]
        
        return result


def run_weight_update(dry_run: bool = False) -> dict:
    """
    Execute a complete weight update cycle.
    
    This is the main entry point for periodic weight updates.
    
    Args:
        dry_run: If True, calculate but don't save changes
    
    Returns:
        Dict with update results
    """
    print("🔄 [SignalWeightLearner] Starting weight update cycle...")
    
    learner = SignalWeightLearner()
    
    learner.calculate_all_evs()
    
    summary_before = learner.get_learning_summary()
    
    if not dry_run:
        new_weights = learner.update_weights()
    else:
        new_weights = None
        print("🔍 [DRY-RUN] Skipping weight save")
    
    combinations = learner.analyze_signal_combinations()
    disagreements = learner.track_signal_disagreements()
    
    result = {
        'status': 'success',
        'timestamp': datetime.utcnow().isoformat(),
        'dry_run': dry_run,
        'summary': summary_before,
        'new_weights': new_weights,
        'signal_evs': learner.signal_evs,
        'best_horizons': {k: v[0] for k, v in learner.determine_all_best_horizons().items()},
        'combinations': combinations,
        'disagreements': disagreements,
        'data_quality': {
            'total_outcomes': len(learner.outcomes),
            'signals_analyzed': list(learner.signal_evs.keys())
        }
    }
    
    print(f"✅ [SignalWeightLearner] Weight update complete. "
          f"Analyzed {len(learner.outcomes)} outcomes across {len(learner.signal_evs)} signals")
    
    return result


def get_current_weights() -> Dict[str, float]:
    """Get current signal weights from gate file."""
    data = _load_json(SIGNAL_WEIGHTS_GATE_FILE)
    if data and 'weights' in data:
        return data['weights']
    return dict(DEFAULT_SIGNAL_WEIGHTS)


def get_signal_ev(signal_name: str, horizon: str = '5m') -> float:
    """Quick helper to get EV for a specific signal."""
    learner = SignalWeightLearner()
    return learner.calculate_signal_ev(signal_name, horizon)


if __name__ == "__main__":
    result = run_weight_update(dry_run=False)
    
    print("\n" + "="*60)
    print("SIGNAL WEIGHT LEARNER - RESULTS")
    print("="*60)
    
    print(f"\n📊 Total Outcomes Analyzed: {result['data_quality']['total_outcomes']}")
    
    print("\n📈 Signal EVs by Best Horizon:")
    for signal, ev_data in result.get('signal_evs', {}).items():
        best_h = result.get('best_horizons', {}).get(signal, '5m')
        best_ev = ev_data.get(best_h, 0)
        print(f"  {signal}: EV={best_ev:.4f} @ {best_h}")
    
    if result.get('new_weights'):
        print("\n⚖️ Updated Weights:")
        for signal, weight in sorted(result['new_weights'].items(), key=lambda x: -x[1]):
            print(f"  {signal}: {weight:.4f}")
    
    print("\n🤝 Signal Combination Analysis:")
    for cat, stats in result.get('combinations', {}).get('agreement_analysis', {}).items():
        print(f"  {cat}: {stats['wins']}/{stats['total']} = {stats['win_rate']:.1%}")
    
    print("\n" + "="*60)
