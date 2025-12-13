"""
REGIME BIAS MULTIPLIER - Autonomous Direction-Aware Sizing
============================================================
Automatically adjusts position sizing based on aggregate and per-signal
EWMA EV data from the direction router. This enables the bot to naturally
gravitate toward profitable directions without hard blocking.

CORE PRINCIPLES:
1. GRADUAL ADJUSTMENT - Uses EWMA data, no sudden flips
2. DIRECTION-AWARE - Boosts sizing when trading with the trend, reduces when against
3. PER-SIGNAL GRANULARITY - Each signal's EV influences its contribution
4. FULLY TRACKED - Every adjustment logged for learning analysis

MULTIPLIER LOGIC:
- If trading LONG and aggregate LONG EV > SHORT EV: boost 1.1-1.3x
- If trading SHORT and aggregate SHORT EV < LONG EV: reduce 0.5-0.8x
- Magnitude of adjustment scales with EV delta
- Per-signal adjustments layer on top of aggregate

LEARNING INTEGRATION:
- Logs all bias decisions to logs/regime_bias_decisions.jsonl
- Tracks adaptation speed, sizing effectiveness, regime shift detection
- Enables retrospective analysis of "did we shift fast enough?"
"""

import json
import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, Any, Optional, Tuple, List
from collections import defaultdict
import math

DIRECTION_RULES_FILE = Path("feature_store/direction_rules.json")
BIAS_LOG_FILE = Path("logs/regime_bias_decisions.jsonl")
ADAPTATION_METRICS_FILE = Path("feature_store/regime_adaptation_metrics.json")
COIN_REGIME_ANALYSIS_FILE = Path("feature_store/coin_regime_analysis.json")

BIAS_LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
ADAPTATION_METRICS_FILE.parent.mkdir(parents=True, exist_ok=True)

_cached_rules = None
_rules_mtime = 0


class RegimeBiasMultiplier:
    """
    Calculates position sizing multipliers based on regime direction bias.
    
    Uses EWMA EV data to automatically favor the more profitable direction
    while still allowing trades in both directions (no hard blocking).
    """
    
    MIN_EV_FOR_BOOST = 5.0
    MAX_EV_FOR_REDUCTION = -5.0
    MAX_BOOST = 1.4
    MIN_REDUCTION = 0.4
    EV_SCALE_FACTOR = 50.0
    
    def __init__(self):
        self.adaptation_metrics = self._load_adaptation_metrics()
    
    def _load_direction_rules(self) -> Dict:
        """Load direction rules with caching."""
        global _cached_rules, _rules_mtime
        
        try:
            if DIRECTION_RULES_FILE.exists():
                mtime = os.path.getmtime(DIRECTION_RULES_FILE)
                if mtime > _rules_mtime or _cached_rules is None:
                    _cached_rules = json.loads(DIRECTION_RULES_FILE.read_text())
                    _rules_mtime = mtime
                return _cached_rules
        except Exception as e:
            print(f"[RegimeBias] Error loading direction rules: {e}")
        
        return {'ewma_ev': {}, 'signal_directions': {}}
    
    def _load_adaptation_metrics(self) -> Dict:
        """Load adaptation tracking metrics."""
        try:
            if ADAPTATION_METRICS_FILE.exists():
                return json.loads(ADAPTATION_METRICS_FILE.read_text())
        except:
            pass
        
        return {
            'regime_shifts': [],
            'sizing_effectiveness': {'boosted_trades': [], 'reduced_trades': []},
            'detection_speed': [],
            'missed_opportunities': [],
            'last_update': None
        }
    
    def _save_adaptation_metrics(self):
        """Persist adaptation metrics."""
        try:
            self.adaptation_metrics['last_update'] = datetime.utcnow().isoformat()
            ADAPTATION_METRICS_FILE.write_text(json.dumps(self.adaptation_metrics, indent=2))
        except Exception as e:
            print(f"[RegimeBias] Error saving metrics: {e}")
    
    def get_aggregate_bias(self) -> Dict[str, float]:
        """
        Get aggregate direction bias from all signals.
        Uses AVERAGE per-signal EV to prevent single signals from swamping.
        
        Returns:
            {
                'long_ev': average LONG EV in bps,
                'short_ev': average SHORT EV in bps,
                'bias': 'LONG' | 'SHORT' | 'NEUTRAL',
                'bias_strength': 0.0-1.0
            }
        """
        rules = self._load_direction_rules()
        ewma_ev = rules.get('ewma_ev', {})
        
        long_evs = []
        short_evs = []
        
        for signal, evs in ewma_ev.items():
            if isinstance(evs, dict):
                long_evs.append(evs.get('LONG', 0.0))
                short_evs.append(evs.get('SHORT', 0.0))
        
        signal_count = len(long_evs)
        avg_long = sum(long_evs) / signal_count if signal_count > 0 else 0.0
        avg_short = sum(short_evs) / signal_count if signal_count > 0 else 0.0
        
        delta = avg_long - avg_short
        
        if delta > 3:
            bias = 'LONG'
            strength = min(1.0, delta / 20.0)
        elif delta < -3:
            bias = 'SHORT'
            strength = min(1.0, abs(delta) / 20.0)
        else:
            bias = 'NEUTRAL'
            strength = 0.0
        
        return {
            'long_ev': round(avg_long, 2),
            'short_ev': round(avg_short, 2),
            'delta': round(delta, 2),
            'bias': bias,
            'bias_strength': round(strength, 3),
            'signal_count': signal_count
        }
    
    def get_signal_bias(self, signal_name: str) -> Dict[str, float]:
        """
        Get direction bias for a specific signal.
        
        Returns:
            {
                'long_ev': LONG EV in bps,
                'short_ev': SHORT EV in bps,
                'preferred_direction': 'LONG' | 'SHORT' | 'BOTH',
                'confidence': 0.0-1.0
            }
        """
        rules = self._load_direction_rules()
        ewma_ev = rules.get('ewma_ev', {})
        
        signal_ev = ewma_ev.get(signal_name, {'LONG': 0.0, 'SHORT': 0.0})
        if not isinstance(signal_ev, dict):
            signal_ev = {'LONG': 0.0, 'SHORT': 0.0}
        
        long_ev = signal_ev.get('LONG', 0.0)
        short_ev = signal_ev.get('SHORT', 0.0)
        
        if long_ev > 5 and short_ev > 5:
            preferred = 'BOTH'
            confidence = min(long_ev, short_ev) / 20.0
        elif long_ev > short_ev + 5:
            preferred = 'LONG'
            confidence = min(1.0, (long_ev - short_ev) / 30.0)
        elif short_ev > long_ev + 5:
            preferred = 'SHORT'
            confidence = min(1.0, (short_ev - long_ev) / 30.0)
        else:
            preferred = 'BOTH'
            confidence = 0.3
        
        return {
            'long_ev': round(long_ev, 2),
            'short_ev': round(short_ev, 2),
            'preferred_direction': preferred,
            'confidence': round(min(1.0, confidence), 3)
        }
    
    def get_coin_direction_ev(self, symbol: str, direction: str) -> Dict:
        """
        Get coin-specific direction EV from historical trade performance.
        Uses live trade log (alpha_trades.jsonl) with size-normalized returns.
        
        Returns EV as average return in bps (basis points) per trade.
        """
        try:
            trades_file = Path("logs/alpha_trades.jsonl")
            if not trades_file.exists():
                trades_file = Path("logs/trades_futures.json")
                if not trades_file.exists():
                    return {'ev': 0.0, 'trades': 0, 'has_data': False}
            
            coin_returns = []
            
            if trades_file.suffix == '.json':
                with open(trades_file, 'r') as f:
                    data = json.load(f)
                    if isinstance(data, dict):
                        trades = data.get('trades', [])
                    else:
                        trades = data
                    
                    for t in trades:
                        if symbol in t.get('symbol', '') or symbol.replace('USDT', '') in t.get('symbol', ''):
                            if t.get('side', '').upper() == direction.upper():
                                pnl = t.get('realized_pnl', t.get('pnl_usd', 0))
                                size = t.get('position_size', t.get('notional', 100))
                                if pnl is not None and size and float(size) > 0:
                                    return_bps = (float(pnl) / float(size)) * 10000
                                    coin_returns.append(return_bps)
            else:
                with open(trades_file, 'r') as f:
                    for line in f:
                        try:
                            t = json.loads(line.strip())
                            if symbol in t.get('symbol', ''):
                                if t.get('direction', '').upper() == direction.upper():
                                    pnl = t.get('pnl_usd', t.get('realized_pnl', 0))
                                    size = t.get('position_size', t.get('notional', 100))
                                    if pnl is not None and size and float(size) > 0:
                                        return_bps = (float(pnl) / float(size)) * 10000
                                        coin_returns.append(return_bps)
                        except:
                            pass
            
            if len(coin_returns) < 15:
                return {'ev': 0.0, 'trades': len(coin_returns), 'has_data': False}
            
            recent = coin_returns[-50:]
            avg_return_bps = sum(recent) / len(recent)
            
            return {
                'ev': round(avg_return_bps, 2),
                'trades': len(recent),
                'has_data': True,
                'win_rate': round(sum(1 for r in recent if r > 0) / len(recent) * 100, 1)
            }
        except Exception as e:
            return {'ev': 0.0, 'trades': 0, 'has_data': False, 'error': str(e)}
    
    PROBLEM_COIN_REDUCTION = {
        'ADA': {'SHORT': 0.5},
        'DOT': {'SHORT': 0.4},
        'AVAX': {'SHORT': 0.5},
    }
    
    def calculate_size_multiplier(self, symbol: str, direction: str, 
                                   active_signals: List[str] = None,
                                   base_conviction: str = 'MEDIUM') -> Tuple[float, Dict]:
        """
        Calculate the regime-aware sizing multiplier for a trade.
        
        Now includes:
        1. Aggregate regime bias (normalized average across signals)
        2. Per-signal EV adjustments
        3. Coin-specific direction EV guardrails
        4. Known problem coin hard reductions (ADA/DOT SHORT)
        
        Args:
            symbol: Trading symbol
            direction: 'LONG' or 'SHORT'
            active_signals: List of signals contributing to this trade
            base_conviction: Conviction level from gate
        
        Returns:
            (multiplier, details_dict)
        """
        aggregate = self.get_aggregate_bias()
        
        direction_ev = aggregate['long_ev'] if direction == 'LONG' else aggregate['short_ev']
        opposite_ev = aggregate['short_ev'] if direction == 'LONG' else aggregate['long_ev']
        
        aggregate_mult = 1.0
        
        if direction == aggregate['bias']:
            if direction_ev > self.MIN_EV_FOR_BOOST:
                boost = min(self.MAX_BOOST - 1.0, direction_ev / self.EV_SCALE_FACTOR)
                aggregate_mult = 1.0 + boost
        elif aggregate['bias'] != 'NEUTRAL':
            if direction_ev < self.MAX_EV_FOR_REDUCTION:
                reduction = min(1.0 - self.MIN_REDUCTION, abs(direction_ev) / self.EV_SCALE_FACTOR)
                aggregate_mult = 1.0 - reduction
            elif opposite_ev > direction_ev + 20:
                aggregate_mult = 0.7
        
        signal_mult = 1.0
        signal_adjustments = {}
        
        if active_signals:
            for signal in active_signals:
                sig_bias = self.get_signal_bias(signal)
                
                if sig_bias['preferred_direction'] == direction:
                    sig_ev = sig_bias['long_ev'] if direction == 'LONG' else sig_bias['short_ev']
                    if sig_ev > 10:
                        boost = min(0.1, sig_ev / 200.0)
                        signal_mult += boost
                        signal_adjustments[signal] = f"+{boost:.2f} (ev={sig_ev:.1f})"
                elif sig_bias['preferred_direction'] != 'BOTH' and sig_bias['preferred_direction'] != direction:
                    sig_ev = sig_bias['long_ev'] if direction == 'LONG' else sig_bias['short_ev']
                    if sig_ev < -5:
                        reduction = min(0.1, abs(sig_ev) / 200.0)
                        signal_mult -= reduction
                        signal_adjustments[signal] = f"-{reduction:.2f} (ev={sig_ev:.1f})"
        
        signal_mult = max(0.5, min(1.5, signal_mult))
        
        coin_mult = 1.0
        coin_ev_data = {'has_data': False}
        clean_symbol = symbol.replace('USDT', '').replace('-USDT', '')
        has_hard_guardrail = False
        
        if clean_symbol in self.PROBLEM_COIN_REDUCTION:
            coin_overrides = self.PROBLEM_COIN_REDUCTION[clean_symbol]
            if direction in coin_overrides:
                coin_mult = coin_overrides[direction]
                has_hard_guardrail = True
                signal_adjustments[f'{clean_symbol}_guardrail'] = f"x{coin_mult:.2f} (known problem)"
        
        coin_ev_data = self.get_coin_direction_ev(symbol, direction)
        if coin_ev_data['has_data'] and not has_hard_guardrail:
            if coin_ev_data['ev'] < -20:
                coin_mult = 0.6
                signal_adjustments[f'{clean_symbol}_ev'] = f"x0.6 (coin_ev={coin_ev_data['ev']:.1f})"
            elif coin_ev_data['ev'] < -10:
                coin_mult = 0.8
                signal_adjustments[f'{clean_symbol}_ev'] = f"x0.8 (coin_ev={coin_ev_data['ev']:.1f})"
            elif coin_ev_data['ev'] > 10:
                coin_mult = 1.15
                signal_adjustments[f'{clean_symbol}_ev'] = f"x1.15 (coin_ev={coin_ev_data['ev']:.1f})"
        
        final_mult = aggregate_mult * signal_mult * coin_mult
        final_mult = max(self.MIN_REDUCTION, min(self.MAX_BOOST, final_mult))
        
        details = {
            'symbol': symbol,
            'direction': direction,
            'aggregate_bias': aggregate,
            'aggregate_mult': round(aggregate_mult, 3),
            'signal_mult': round(signal_mult, 3),
            'coin_mult': round(coin_mult, 3),
            'coin_ev': coin_ev_data,
            'signal_adjustments': signal_adjustments,
            'final_mult': round(final_mult, 3),
            'trading_with_regime': direction == aggregate['bias'],
            'direction_ev': round(direction_ev, 2),
            'opposite_ev': round(opposite_ev, 2),
            'base_conviction': base_conviction
        }
        
        self._log_bias_decision(details)
        
        self._track_adaptation(details)
        
        return round(final_mult, 3), details
    
    def _log_bias_decision(self, details: Dict):
        """Log every bias decision for learning analysis."""
        try:
            entry = {
                'ts': datetime.utcnow().isoformat(),
                **details
            }
            with open(BIAS_LOG_FILE, 'a') as f:
                f.write(json.dumps(entry, default=str) + '\n')
        except Exception as e:
            print(f"[RegimeBias] Error logging decision: {e}")
    
    def _track_adaptation(self, details: Dict):
        """Track adaptation metrics for learning."""
        mult = details['final_mult']
        direction = details['direction']
        regime_bias = details['aggregate_bias']['bias']
        
        if mult > 1.1:
            self.adaptation_metrics['sizing_effectiveness']['boosted_trades'].append({
                'ts': datetime.utcnow().isoformat(),
                'symbol': details['symbol'],
                'direction': direction,
                'mult': mult,
                'direction_ev': details['direction_ev']
            })
            if len(self.adaptation_metrics['sizing_effectiveness']['boosted_trades']) > 500:
                self.adaptation_metrics['sizing_effectiveness']['boosted_trades'] = \
                    self.adaptation_metrics['sizing_effectiveness']['boosted_trades'][-250:]
        
        elif mult < 0.9:
            self.adaptation_metrics['sizing_effectiveness']['reduced_trades'].append({
                'ts': datetime.utcnow().isoformat(),
                'symbol': details['symbol'],
                'direction': direction,
                'mult': mult,
                'direction_ev': details['direction_ev']
            })
            if len(self.adaptation_metrics['sizing_effectiveness']['reduced_trades']) > 500:
                self.adaptation_metrics['sizing_effectiveness']['reduced_trades'] = \
                    self.adaptation_metrics['sizing_effectiveness']['reduced_trades'][-250:]
        
        if not details['trading_with_regime'] and regime_bias != 'NEUTRAL':
            if details['direction_ev'] < -10:
                self.adaptation_metrics['missed_opportunities'].append({
                    'ts': datetime.utcnow().isoformat(),
                    'symbol': details['symbol'],
                    'direction': direction,
                    'regime_bias': regime_bias,
                    'direction_ev': details['direction_ev'],
                    'should_have_reduced_more': mult > 0.6
                })
                if len(self.adaptation_metrics['missed_opportunities']) > 200:
                    self.adaptation_metrics['missed_opportunities'] = \
                        self.adaptation_metrics['missed_opportunities'][-100:]
    
    def detect_regime_shift(self) -> Optional[Dict]:
        """
        Detect if a regime shift is occurring.
        Used for proactive notifications and adaptation speed tracking.
        """
        aggregate = self.get_aggregate_bias()
        
        recent_shifts = [s for s in self.adaptation_metrics.get('regime_shifts', [])
                        if datetime.fromisoformat(s['ts']) > datetime.utcnow() - timedelta(hours=24)]
        
        if recent_shifts:
            last_shift = recent_shifts[-1]
            if last_shift['to_bias'] != aggregate['bias'] and aggregate['bias'] != 'NEUTRAL':
                shift = {
                    'ts': datetime.utcnow().isoformat(),
                    'from_bias': last_shift['to_bias'],
                    'to_bias': aggregate['bias'],
                    'long_ev': aggregate['long_ev'],
                    'short_ev': aggregate['short_ev'],
                    'delta': aggregate['delta'],
                    'strength': aggregate['bias_strength']
                }
                self.adaptation_metrics['regime_shifts'].append(shift)
                self._save_adaptation_metrics()
                return shift
        elif aggregate['bias'] != 'NEUTRAL' and aggregate['bias_strength'] > 0.3:
            shift = {
                'ts': datetime.utcnow().isoformat(),
                'from_bias': 'NEUTRAL',
                'to_bias': aggregate['bias'],
                'long_ev': aggregate['long_ev'],
                'short_ev': aggregate['short_ev'],
                'delta': aggregate['delta'],
                'strength': aggregate['bias_strength']
            }
            self.adaptation_metrics['regime_shifts'].append(shift)
            self._save_adaptation_metrics()
            return shift
        
        return None
    
    def get_adaptation_report(self) -> Dict:
        """
        Generate a report on how well the system is adapting.
        Used for learning dashboard and strategic analysis.
        """
        aggregate = self.get_aggregate_bias()
        
        boosted = self.adaptation_metrics['sizing_effectiveness'].get('boosted_trades', [])
        reduced = self.adaptation_metrics['sizing_effectiveness'].get('reduced_trades', [])
        missed = self.adaptation_metrics.get('missed_opportunities', [])
        shifts = self.adaptation_metrics.get('regime_shifts', [])
        
        recent_boosted = [t for t in boosted 
                         if datetime.fromisoformat(t['ts']) > datetime.utcnow() - timedelta(hours=24)]
        recent_reduced = [t for t in reduced
                         if datetime.fromisoformat(t['ts']) > datetime.utcnow() - timedelta(hours=24)]
        recent_missed = [t for t in missed
                        if datetime.fromisoformat(t['ts']) > datetime.utcnow() - timedelta(hours=24)]
        
        with_regime_count = len([t for t in recent_boosted if t['direction'] == aggregate['bias']])
        against_regime_count = len([t for t in recent_reduced if t['direction'] != aggregate['bias']])
        
        report = {
            'current_regime': aggregate,
            'last_24h': {
                'boosted_trades': len(recent_boosted),
                'reduced_trades': len(recent_reduced),
                'missed_opportunities': len(recent_missed),
                'trades_with_regime': with_regime_count,
                'trades_against_regime': against_regime_count
            },
            'regime_shifts_24h': [s for s in shifts 
                                  if datetime.fromisoformat(s['ts']) > datetime.utcnow() - timedelta(hours=24)],
            'adaptation_issues': [],
            'recommendations': []
        }
        
        if len(recent_missed) > 5:
            report['adaptation_issues'].append({
                'type': 'slow_reduction',
                'message': f'{len(recent_missed)} trades taken against regime bias with negative EV',
                'severity': 'high' if len(recent_missed) > 10 else 'medium'
            })
            report['recommendations'].append('Consider lowering MIN_REDUCTION to reduce losing direction faster')
        
        if aggregate['bias'] != 'NEUTRAL' and with_regime_count < against_regime_count:
            report['adaptation_issues'].append({
                'type': 'bias_not_followed',
                'message': f'Regime is {aggregate["bias"]} but taking more {("SHORT" if aggregate["bias"] == "LONG" else "LONG")} trades',
                'severity': 'high'
            })
            report['recommendations'].append('Signal generation may need bias injection')
        
        if aggregate['delta'] > 30 and len(recent_boosted) < 3:
            report['adaptation_issues'].append({
                'type': 'not_boosting_enough',
                'message': f'Strong regime bias ({aggregate["delta"]:.0f}bps delta) but few boosted trades',
                'severity': 'medium'
            })
            report['recommendations'].append('Consider lowering MIN_EV_FOR_BOOST threshold')
        
        return report
    
    def analyze_coin_regime_performance(self, trades: List[Dict]) -> Dict:
        """
        Analyze how each coin performs relative to regime bias.
        Identifies coins that consistently trade against the regime.
        """
        aggregate = self.get_aggregate_bias()
        coin_stats = defaultdict(lambda: {
            'with_regime': {'count': 0, 'pnl': 0},
            'against_regime': {'count': 0, 'pnl': 0},
            'neutral': {'count': 0, 'pnl': 0}
        })
        
        for trade in trades:
            symbol = trade.get('symbol', 'UNKNOWN')
            direction = trade.get('direction', trade.get('side', '')).upper()
            pnl = trade.get('realized_pnl', trade.get('pnl_usd', trade.get('pnl', 0)))
            
            try:
                pnl = float(pnl) if pnl else 0
            except:
                pnl = 0
            
            if aggregate['bias'] == 'NEUTRAL':
                coin_stats[symbol]['neutral']['count'] += 1
                coin_stats[symbol]['neutral']['pnl'] += pnl
            elif direction == aggregate['bias']:
                coin_stats[symbol]['with_regime']['count'] += 1
                coin_stats[symbol]['with_regime']['pnl'] += pnl
            else:
                coin_stats[symbol]['against_regime']['count'] += 1
                coin_stats[symbol]['against_regime']['pnl'] += pnl
        
        analysis = {
            'current_regime': aggregate,
            'coin_performance': {},
            'problem_coins': [],
            'strong_coins': []
        }
        
        for symbol, stats in coin_stats.items():
            total_trades = stats['with_regime']['count'] + stats['against_regime']['count'] + stats['neutral']['count']
            total_pnl = stats['with_regime']['pnl'] + stats['against_regime']['pnl'] + stats['neutral']['pnl']
            
            analysis['coin_performance'][symbol] = {
                'total_trades': total_trades,
                'total_pnl': round(total_pnl, 2),
                'with_regime': stats['with_regime'],
                'against_regime': stats['against_regime'],
                'regime_alignment_pct': round(stats['with_regime']['count'] / total_trades * 100, 1) if total_trades > 0 else 0
            }
            
            if stats['against_regime']['count'] > stats['with_regime']['count'] and stats['against_regime']['pnl'] < -2:
                analysis['problem_coins'].append({
                    'symbol': symbol,
                    'issue': 'trading_against_regime',
                    'against_regime_pnl': round(stats['against_regime']['pnl'], 2),
                    'against_regime_count': stats['against_regime']['count']
                })
            
            if stats['with_regime']['pnl'] > 1 and stats['with_regime']['count'] >= 3:
                analysis['strong_coins'].append({
                    'symbol': symbol,
                    'with_regime_pnl': round(stats['with_regime']['pnl'], 2),
                    'with_regime_count': stats['with_regime']['count']
                })
        
        try:
            COIN_REGIME_ANALYSIS_FILE.write_text(json.dumps(analysis, indent=2))
        except:
            pass
        
        return analysis


_bias_instance = None

def get_regime_bias_multiplier() -> RegimeBiasMultiplier:
    """Get singleton instance of RegimeBiasMultiplier."""
    global _bias_instance
    if _bias_instance is None:
        _bias_instance = RegimeBiasMultiplier()
    return _bias_instance


def calculate_regime_size_multiplier(symbol: str, direction: str,
                                     active_signals: List[str] = None,
                                     base_conviction: str = 'MEDIUM') -> Tuple[float, Dict]:
    """
    Convenience function to get regime-aware sizing multiplier.
    
    Returns:
        (multiplier, details)
    """
    bias = get_regime_bias_multiplier()
    return bias.calculate_size_multiplier(symbol, direction, active_signals, base_conviction)


def get_current_regime_bias() -> Dict:
    """Get current aggregate regime bias."""
    bias = get_regime_bias_multiplier()
    return bias.get_aggregate_bias()


def get_adaptation_report() -> Dict:
    """Get adaptation effectiveness report."""
    bias = get_regime_bias_multiplier()
    return bias.get_adaptation_report()


if __name__ == '__main__':
    import sys
    
    bias = RegimeBiasMultiplier()
    
    print("=" * 60)
    print("REGIME BIAS MULTIPLIER STATUS")
    print("=" * 60)
    
    aggregate = bias.get_aggregate_bias()
    print(f"\nAggregate Bias:")
    print(f"  LONG EV:  {aggregate['long_ev']:+.1f} bps")
    print(f"  SHORT EV: {aggregate['short_ev']:+.1f} bps")
    print(f"  Delta:    {aggregate['delta']:+.1f} bps")
    print(f"  Bias:     {aggregate['bias']} (strength: {aggregate['bias_strength']:.2f})")
    
    print(f"\nExample Multipliers:")
    for direction in ['LONG', 'SHORT']:
        mult, details = bias.calculate_size_multiplier('BTCUSDT', direction, 
                                                        ['funding', 'whale_flow'])
        print(f"  {direction}: {mult:.2f}x (aggregate: {details['aggregate_mult']:.2f}, signal: {details['signal_mult']:.2f})")
    
    report = bias.get_adaptation_report()
    print(f"\nAdaptation Report (24h):")
    print(f"  Boosted trades:  {report['last_24h']['boosted_trades']}")
    print(f"  Reduced trades:  {report['last_24h']['reduced_trades']}")
    print(f"  Missed opportunities: {report['last_24h']['missed_opportunities']}")
    
    if report['adaptation_issues']:
        print(f"\n  Issues:")
        for issue in report['adaptation_issues']:
            print(f"    - [{issue['severity']}] {issue['message']}")
    
    if report['recommendations']:
        print(f"\n  Recommendations:")
        for rec in report['recommendations']:
            print(f"    - {rec}")
