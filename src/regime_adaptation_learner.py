"""
REGIME ADAPTATION LEARNER - Tracks and Learns from Regime Transitions
======================================================================
Monitors how well the system adapts to regime changes and identifies
areas for improvement. This is the learning layer that sits on top
of the regime bias multiplier.

WHAT IT TRACKS:
1. Regime Shift Detection Speed - How quickly we detect new regimes
2. Sizing Effectiveness - Are boosted/reduced trades working?
3. Flip Timing Analysis - Are direction flips happening fast enough?
4. Coin-Specific Issues - Which coins are consistently trading wrong
5. Missed Opportunity Analysis - What we should have caught

LEARNING OUTPUTS:
- feature_store/regime_learning_report.json - Comprehensive analysis
- logs/regime_adaptation_events.jsonl - Event stream for debugging
- Recommendations for tuning parameters

Author: Trading Bot
Created: 2025-12-05
"""

import json
import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Any, Optional, Tuple
from collections import defaultdict

TRADES_FILE = Path("logs/trades_futures.json")
BIAS_DECISIONS_FILE = Path("logs/regime_bias_decisions.jsonl")
DIRECTION_ROUTING_LOG = Path("logs/direction_routing.jsonl")
ADAPTATION_EVENTS_FILE = Path("logs/regime_adaptation_events.jsonl")
LEARNING_REPORT_FILE = Path("feature_store/regime_learning_report.json")

ADAPTATION_EVENTS_FILE.parent.mkdir(parents=True, exist_ok=True)
LEARNING_REPORT_FILE.parent.mkdir(parents=True, exist_ok=True)


class RegimeAdaptationLearner:
    """
    Analyzes regime adaptation effectiveness and generates learning insights.
    """
    
    def __init__(self):
        self.events = []
    
    def _log_event(self, event_type: str, data: Dict):
        """Log an adaptation event."""
        try:
            entry = {
                'ts': datetime.utcnow().isoformat(),
                'event': event_type,
                **data
            }
            with open(ADAPTATION_EVENTS_FILE, 'a') as f:
                f.write(json.dumps(entry) + '\n')
            self.events.append(entry)
        except:
            pass
    
    def _load_trades(self, hours: int = 24) -> List[Dict]:
        """Load recent trades."""
        try:
            if TRADES_FILE.exists():
                data = json.loads(TRADES_FILE.read_text())
                if isinstance(data, dict):
                    trades = data.get('trades', [])
                else:
                    trades = data
                
                cutoff = datetime.utcnow() - timedelta(hours=hours)
                recent = []
                for t in trades:
                    ts = t.get('close_timestamp', t.get('timestamp'))
                    if ts:
                        try:
                            if isinstance(ts, str):
                                trade_time = datetime.fromisoformat(ts.replace('Z', ''))
                            else:
                                trade_time = datetime.fromtimestamp(ts)
                            if trade_time > cutoff:
                                recent.append(t)
                        except:
                            pass
                return recent
        except:
            pass
        return []
    
    def _load_bias_decisions(self, hours: int = 24) -> List[Dict]:
        """Load recent bias decisions."""
        try:
            if BIAS_DECISIONS_FILE.exists():
                cutoff = datetime.utcnow() - timedelta(hours=hours)
                decisions = []
                with open(BIAS_DECISIONS_FILE, 'r') as f:
                    for line in f:
                        try:
                            d = json.loads(line.strip())
                            ts = d.get('ts')
                            if ts:
                                dt = datetime.fromisoformat(ts)
                                if dt > cutoff:
                                    decisions.append(d)
                        except:
                            pass
                return decisions
        except:
            pass
        return []
    
    def analyze_sizing_effectiveness(self, hours: int = 24) -> Dict:
        """
        Analyze if regime-adjusted sizing is actually helping.
        
        Compares P&L of:
        - Boosted trades (mult > 1.1) vs normal trades
        - Reduced trades (mult < 0.9) vs if they had normal sizing
        """
        trades = self._load_trades(hours)
        decisions = self._load_bias_decisions(hours)
        
        decision_map = {}
        for d in decisions:
            key = f"{d.get('symbol')}_{d.get('ts', '')[:16]}"
            decision_map[key] = d
        
        boosted_pnl = []
        reduced_pnl = []
        normal_pnl = []
        
        for t in trades:
            pnl = t.get('realized_pnl', t.get('pnl_usd', t.get('pnl', 0)))
            try:
                pnl = float(pnl) if pnl else 0
            except:
                pnl = 0
            
            symbol = t.get('symbol', '')
            ts = t.get('entry_timestamp', t.get('timestamp', ''))
            key = f"{symbol}_{str(ts)[:16]}"
            
            decision = decision_map.get(key, {})
            mult = decision.get('final_mult', 1.0)
            
            if mult > 1.1:
                boosted_pnl.append({'pnl': pnl, 'mult': mult, 'symbol': symbol})
            elif mult < 0.9:
                reduced_pnl.append({'pnl': pnl, 'mult': mult, 'symbol': symbol})
            else:
                normal_pnl.append({'pnl': pnl, 'mult': mult, 'symbol': symbol})
        
        analysis = {
            'period_hours': hours,
            'boosted_trades': {
                'count': len(boosted_pnl),
                'total_pnl': round(sum(t['pnl'] for t in boosted_pnl), 2),
                'avg_pnl': round(sum(t['pnl'] for t in boosted_pnl) / len(boosted_pnl), 2) if boosted_pnl else 0,
                'avg_mult': round(sum(t['mult'] for t in boosted_pnl) / len(boosted_pnl), 2) if boosted_pnl else 0
            },
            'reduced_trades': {
                'count': len(reduced_pnl),
                'total_pnl': round(sum(t['pnl'] for t in reduced_pnl), 2),
                'avg_pnl': round(sum(t['pnl'] for t in reduced_pnl) / len(reduced_pnl), 2) if reduced_pnl else 0,
                'avg_mult': round(sum(t['mult'] for t in reduced_pnl) / len(reduced_pnl), 2) if reduced_pnl else 0
            },
            'normal_trades': {
                'count': len(normal_pnl),
                'total_pnl': round(sum(t['pnl'] for t in normal_pnl), 2),
                'avg_pnl': round(sum(t['pnl'] for t in normal_pnl) / len(normal_pnl), 2) if normal_pnl else 0
            },
            'effectiveness': {}
        }
        
        if boosted_pnl and normal_pnl:
            boost_avg = analysis['boosted_trades']['avg_pnl']
            normal_avg = analysis['normal_trades']['avg_pnl']
            if boost_avg > normal_avg:
                analysis['effectiveness']['boosting'] = 'WORKING'
                analysis['effectiveness']['boost_improvement'] = round(boost_avg - normal_avg, 2)
            else:
                analysis['effectiveness']['boosting'] = 'NOT_HELPING'
                analysis['effectiveness']['boost_improvement'] = round(boost_avg - normal_avg, 2)
        
        if reduced_pnl:
            reduced_avg = analysis['reduced_trades']['avg_pnl']
            if reduced_avg < 0:
                analysis['effectiveness']['reduction'] = 'CORRECT_TO_REDUCE'
                analysis['effectiveness']['loss_mitigated'] = round(abs(reduced_avg) * len(reduced_pnl) * 0.3, 2)
            else:
                analysis['effectiveness']['reduction'] = 'OVER_REDUCED'
        
        self._log_event('sizing_effectiveness_analyzed', analysis)
        
        return analysis
    
    def analyze_coin_problems(self, hours: int = 48) -> Dict:
        """
        Deep analysis of problematic coins - what's going wrong?
        """
        trades = self._load_trades(hours)
        
        coin_stats = defaultdict(lambda: {
            'total_pnl': 0,
            'trade_count': 0,
            'long_pnl': 0,
            'long_count': 0,
            'short_pnl': 0,
            'short_count': 0,
            'signals_used': defaultdict(lambda: {'count': 0, 'pnl': 0}),
            'losing_streaks': [],
            'current_streak': 0
        })
        
        for t in trades:
            symbol = t.get('symbol', 'UNKNOWN')
            pnl = t.get('realized_pnl', t.get('pnl_usd', t.get('pnl', 0)))
            direction = t.get('direction', t.get('side', '')).upper()
            signals = t.get('entry_signals', t.get('signals', []))
            
            try:
                pnl = float(pnl) if pnl else 0
            except:
                pnl = 0
            
            coin_stats[symbol]['total_pnl'] += pnl
            coin_stats[symbol]['trade_count'] += 1
            
            if direction == 'LONG':
                coin_stats[symbol]['long_pnl'] += pnl
                coin_stats[symbol]['long_count'] += 1
            else:
                coin_stats[symbol]['short_pnl'] += pnl
                coin_stats[symbol]['short_count'] += 1
            
            if isinstance(signals, list):
                for sig in signals:
                    coin_stats[symbol]['signals_used'][sig]['count'] += 1
                    coin_stats[symbol]['signals_used'][sig]['pnl'] += pnl
            
            if pnl < 0:
                coin_stats[symbol]['current_streak'] += 1
            else:
                if coin_stats[symbol]['current_streak'] >= 3:
                    coin_stats[symbol]['losing_streaks'].append(coin_stats[symbol]['current_streak'])
                coin_stats[symbol]['current_streak'] = 0
        
        problem_coins = []
        for symbol, stats in coin_stats.items():
            if stats['total_pnl'] < -2.0:
                signals_analysis = []
                for sig, sig_stats in stats['signals_used'].items():
                    avg_pnl = sig_stats['pnl'] / sig_stats['count'] if sig_stats['count'] > 0 else 0
                    signals_analysis.append({
                        'signal': sig,
                        'count': sig_stats['count'],
                        'pnl': round(sig_stats['pnl'], 2),
                        'avg_pnl': round(avg_pnl, 2)
                    })
                
                worst_direction = 'LONG' if stats['long_pnl'] < stats['short_pnl'] else 'SHORT'
                
                problem_coins.append({
                    'symbol': symbol,
                    'total_pnl': round(stats['total_pnl'], 2),
                    'trade_count': stats['trade_count'],
                    'long': {'pnl': round(stats['long_pnl'], 2), 'count': stats['long_count']},
                    'short': {'pnl': round(stats['short_pnl'], 2), 'count': stats['short_count']},
                    'worst_direction': worst_direction,
                    'signals': sorted(signals_analysis, key=lambda x: x['pnl']),
                    'losing_streaks': stats['losing_streaks'],
                    'current_losing_streak': stats['current_streak']
                })
        
        problem_coins.sort(key=lambda x: x['total_pnl'])
        
        analysis = {
            'period_hours': hours,
            'total_coins_analyzed': len(coin_stats),
            'problem_coins': problem_coins[:5],
            'diagnoses': []
        }
        
        for coin in problem_coins[:5]:
            diagnosis = self._diagnose_coin_problem(coin)
            analysis['diagnoses'].append({
                'symbol': coin['symbol'],
                **diagnosis
            })
        
        self._log_event('coin_problems_analyzed', analysis)
        
        return analysis
    
    def _diagnose_coin_problem(self, coin_data: Dict) -> Dict:
        """
        Diagnose the root cause of a coin's poor performance.
        """
        diagnosis = {
            'primary_issue': None,
            'secondary_issues': [],
            'recommendations': []
        }
        
        long_pnl = coin_data['long']['pnl']
        short_pnl = coin_data['short']['pnl']
        long_count = coin_data['long']['count']
        short_count = coin_data['short']['count']
        
        if long_pnl < -1 and short_pnl < -1:
            diagnosis['primary_issue'] = 'BOTH_DIRECTIONS_LOSING'
            diagnosis['recommendations'].append(f"Consider pausing {coin_data['symbol']} until regime stabilizes")
            diagnosis['recommendations'].append("Increase minimum OFI threshold for this coin")
        elif abs(long_pnl - short_pnl) > 3:
            worse = 'LONG' if long_pnl < short_pnl else 'SHORT'
            better = 'SHORT' if worse == 'LONG' else 'LONG'
            diagnosis['primary_issue'] = f'WRONG_DIRECTION_BIAS'
            diagnosis['secondary_issues'].append(f"{worse} is losing ${abs(min(long_pnl, short_pnl)):.2f}")
            diagnosis['recommendations'].append(f"Reduce {worse} sizing for {coin_data['symbol']}")
            diagnosis['recommendations'].append(f"Increase confidence threshold for {worse}")
        
        if coin_data['current_losing_streak'] >= 3:
            diagnosis['secondary_issues'].append(f"Currently on {coin_data['current_losing_streak']}-trade losing streak")
            diagnosis['recommendations'].append("Temporary size reduction warranted")
        
        if coin_data['losing_streaks']:
            avg_streak = sum(coin_data['losing_streaks']) / len(coin_data['losing_streaks'])
            if avg_streak > 4:
                diagnosis['secondary_issues'].append(f"Frequent long losing streaks (avg: {avg_streak:.1f})")
                diagnosis['recommendations'].append("Check if signals are lagging for this coin")
        
        bad_signals = [s for s in coin_data.get('signals', []) if s['avg_pnl'] < -0.3]
        if bad_signals:
            worst = bad_signals[0]
            diagnosis['secondary_issues'].append(f"Signal '{worst['signal']}' has {worst['avg_pnl']:.2f} avg P&L")
            diagnosis['recommendations'].append(f"Reduce '{worst['signal']}' weight for {coin_data['symbol']}")
        
        return diagnosis
    
    def analyze_adaptation_speed(self, hours: int = 72) -> Dict:
        """
        Analyze if we're adapting fast enough to regime changes.
        """
        decisions = self._load_bias_decisions(hours)
        trades = self._load_trades(hours)
        
        if not decisions:
            return {'status': 'no_data', 'message': 'No bias decisions recorded yet'}
        
        regime_bias_history = []
        for d in decisions:
            regime_bias_history.append({
                'ts': d.get('ts'),
                'bias': d.get('aggregate_bias', {}).get('bias', 'NEUTRAL'),
                'long_ev': d.get('aggregate_bias', {}).get('long_ev', 0),
                'short_ev': d.get('aggregate_bias', {}).get('short_ev', 0)
            })
        
        regime_changes = []
        prev_bias = None
        for r in regime_bias_history:
            if prev_bias and r['bias'] != prev_bias and r['bias'] != 'NEUTRAL':
                regime_changes.append({
                    'ts': r['ts'],
                    'from': prev_bias,
                    'to': r['bias'],
                    'long_ev': r['long_ev'],
                    'short_ev': r['short_ev']
                })
            prev_bias = r['bias']
        
        pnl_after_changes = []
        for change in regime_changes:
            change_time = datetime.fromisoformat(change['ts'])
            window_start = change_time
            window_end = change_time + timedelta(hours=6)
            
            window_trades = [t for t in trades if self._trade_in_window(t, window_start, window_end)]
            window_pnl = sum(self._get_pnl(t) for t in window_trades)
            
            pnl_after_changes.append({
                'change': change,
                'trades_after': len(window_trades),
                'pnl_after_6h': round(window_pnl, 2)
            })
        
        analysis = {
            'period_hours': hours,
            'regime_changes_detected': len(regime_changes),
            'regime_changes': regime_changes[-5:],
            'performance_after_changes': pnl_after_changes[-5:],
            'speed_assessment': 'ADEQUATE',
            'recommendations': []
        }
        
        negative_after = [p for p in pnl_after_changes if p['pnl_after_6h'] < -1]
        if len(negative_after) > len(pnl_after_changes) / 2:
            analysis['speed_assessment'] = 'TOO_SLOW'
            analysis['recommendations'].append("Reduce EWMA alpha for faster adaptation")
            analysis['recommendations'].append("Lower persistence window requirement")
        
        return analysis
    
    def _trade_in_window(self, trade: Dict, start: datetime, end: datetime) -> bool:
        """Check if trade is within time window."""
        ts = trade.get('entry_timestamp', trade.get('timestamp'))
        if not ts:
            return False
        try:
            if isinstance(ts, str):
                trade_time = datetime.fromisoformat(ts.replace('Z', ''))
            else:
                trade_time = datetime.fromtimestamp(ts)
            return start <= trade_time <= end
        except:
            return False
    
    def _get_pnl(self, trade: Dict) -> float:
        """Extract P&L from trade."""
        pnl = trade.get('realized_pnl', trade.get('pnl_usd', trade.get('pnl', 0)))
        try:
            return float(pnl) if pnl else 0
        except:
            return 0
    
    def generate_full_report(self, hours: int = 48) -> Dict:
        """
        Generate comprehensive learning report.
        """
        sizing = self.analyze_sizing_effectiveness(hours)
        coins = self.analyze_coin_problems(hours)
        speed = self.analyze_adaptation_speed(hours * 1.5)
        
        report = {
            'generated_at': datetime.utcnow().isoformat(),
            'period_hours': hours,
            'sizing_effectiveness': sizing,
            'problem_coins': coins,
            'adaptation_speed': speed,
            'summary': {
                'boosted_trade_count': sizing['boosted_trades']['count'],
                'reduced_trade_count': sizing['reduced_trades']['count'],
                'boost_effectiveness': sizing['effectiveness'].get('boosting', 'UNKNOWN'),
                'problem_coin_count': len(coins['problem_coins']),
                'top_problem_coin': coins['problem_coins'][0]['symbol'] if coins['problem_coins'] else None,
                'adaptation_speed': speed.get('speed_assessment', 'UNKNOWN')
            },
            'action_items': []
        }
        
        if sizing['effectiveness'].get('boosting') == 'NOT_HELPING':
            report['action_items'].append({
                'priority': 'high',
                'action': 'Review boost logic - boosted trades underperforming',
                'data': sizing['effectiveness']
            })
        
        for coin in coins['problem_coins'][:2]:
            report['action_items'].append({
                'priority': 'high',
                'action': f"Investigate {coin['symbol']} - losing ${abs(coin['total_pnl']):.2f}",
                'data': self._diagnose_coin_problem(coin)
            })
        
        if speed.get('speed_assessment') == 'TOO_SLOW':
            report['action_items'].append({
                'priority': 'medium',
                'action': 'Regime adaptation too slow - consider faster EWMA',
                'data': speed['recommendations']
            })
        
        try:
            LEARNING_REPORT_FILE.write_text(json.dumps(report, indent=2))
        except:
            pass
        
        return report


def run_adaptation_analysis(hours: int = 48) -> Dict:
    """Run full adaptation analysis."""
    learner = RegimeAdaptationLearner()
    return learner.generate_full_report(hours)


def analyze_problem_coins(hours: int = 48) -> Dict:
    """Analyze problematic coins."""
    learner = RegimeAdaptationLearner()
    return learner.analyze_coin_problems(hours)


if __name__ == '__main__':
    print("=" * 60)
    print("REGIME ADAPTATION LEARNING REPORT")
    print("=" * 60)
    
    learner = RegimeAdaptationLearner()
    report = learner.generate_full_report(48)
    
    print(f"\nSummary:")
    print(f"  Boosted trades: {report['summary']['boosted_trade_count']}")
    print(f"  Reduced trades: {report['summary']['reduced_trade_count']}")
    print(f"  Boost effectiveness: {report['summary']['boost_effectiveness']}")
    print(f"  Problem coins: {report['summary']['problem_coin_count']}")
    print(f"  Top problem: {report['summary']['top_problem_coin']}")
    print(f"  Adaptation speed: {report['summary']['adaptation_speed']}")
    
    if report['action_items']:
        print(f"\nAction Items:")
        for item in report['action_items']:
            print(f"  [{item['priority']}] {item['action']}")
    
    print(f"\nFull report saved to: {LEARNING_REPORT_FILE}")
