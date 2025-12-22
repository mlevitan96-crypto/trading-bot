#!/usr/bin/env python3
"""
Causal Pattern Analyzer - Understanding WHY, Not Just WHAT
===========================================================
Proactive analysis that identifies underlying causes of success/failure.

Instead of reactive "hour 1 wins more", this analyzes:
- WHAT market conditions existed during winning trades?
- WHAT patterns in OFI, volume, volatility, funding led to success?
- WHY did certain hours perform better? (market conditions, not time itself)
- HOW can we predict success based on current market state?

This enables PROACTIVE trading based on understanding, not reactive adjustments.
"""

import os
import sys
import json
from pathlib import Path
from datetime import datetime, timezone, timedelta
from collections import defaultdict
from typing import Dict, List, Any, Tuple
from statistics import mean, median, stdev

sys.path.insert(0, os.path.dirname(__file__))

from src.data_registry import DataRegistry as DR
from src.infrastructure.path_registry import PathRegistry


def get_market_context(trade: Dict) -> Dict[str, Any]:
    """Extract all market context available at trade entry."""
    context = {
        'ofi': 0.0,
        'ensemble': 0.0,
        'regime': 'unknown',
        'volatility': 0.0,
        'volume': 0.0,
        'funding_rate': 0.0,
        'liquidation_pressure': 0.0,
        'whale_flow': 0.0,
        'fear_greed': 50.0,
        'hour': 12,
        'session': 'unknown',
    }
    
    # Extract from trade record
    context['ofi'] = abs(trade.get('ofi_score', trade.get('ofi', trade.get('entry_ofi', 0))) or 0)
    context['ensemble'] = abs(trade.get('ensemble_score', trade.get('ensemble', 0)) or 0)
    context['regime'] = trade.get('regime', trade.get('market_regime', 'unknown'))
    
    # Extract from signal context if available
    signal_ctx = trade.get('signal_ctx', {})
    if signal_ctx:
        context['ofi'] = abs(signal_ctx.get('ofi', context['ofi']))
        context['ensemble'] = abs(signal_ctx.get('ensemble', context['ensemble']))
        context['regime'] = signal_ctx.get('regime', context['regime'])
        context['volatility'] = signal_ctx.get('volatility', signal_ctx.get('vol_regime', 0))
        context['volume'] = signal_ctx.get('volume', signal_ctx.get('volume_24h', 0))
        context['funding_rate'] = signal_ctx.get('funding_rate', 0)
        context['liquidation_pressure'] = signal_ctx.get('liquidation_pressure', 0)
        context['whale_flow'] = signal_ctx.get('whale_flow', 0)
        context['fear_greed'] = signal_ctx.get('fear_greed', signal_ctx.get('fg_index', 50))
    
    # Extract timing
    entry_time = trade.get('opened_at', trade.get('entry_timestamp', trade.get('timestamp', '')))
    if entry_time:
        try:
            if isinstance(entry_time, str):
                dt = datetime.fromisoformat(entry_time.replace('Z', '+00:00'))
            else:
                dt = datetime.fromtimestamp(entry_time)
            context['hour'] = dt.hour
            context['session'] = get_session(dt)
        except:
            pass
    
    return context


def get_session(dt: datetime) -> str:
    """Get trading session from datetime."""
    hour = dt.hour
    if 0 <= hour < 4:
        return 'asia_night'
    elif 4 <= hour < 8:
        return 'asia_morning'
    elif 8 <= hour < 12:
        return 'europe_morning'
    elif 12 <= hour < 16:
        return 'us_morning'
    elif 16 <= hour < 20:
        return 'us_afternoon'
    else:
        return 'evening'


def analyze_causal_patterns(trades: List[Dict]) -> Dict[str, Any]:
    """Analyze WHY trades succeed or fail based on market conditions."""
    
    winners = []
    losers = []
    
    for trade in trades:
        pnl = trade.get('net_pnl', trade.get('pnl', 0)) or 0
        context = get_market_context(trade)
        context['pnl'] = pnl
        context['symbol'] = trade.get('symbol', 'UNKNOWN')
        context['direction'] = trade.get('direction', trade.get('side', 'UNKNOWN'))
        context['strategy'] = trade.get('strategy', 'UNKNOWN')
        
        if pnl > 0:
            winners.append(context)
        else:
            losers.append(context)
    
    # Analyze patterns in winners vs losers
    patterns = {
        'winning_patterns': {},
        'losing_patterns': {},
        'causal_factors': {},
        'predictive_rules': [],
    }
    
    # 1. OFI Analysis - What OFI levels lead to wins?
    if winners and losers:
        winner_ofi = [w['ofi'] for w in winners if w['ofi'] > 0]
        loser_ofi = [l['ofi'] for l in losers if l['ofi'] > 0]
        
        if winner_ofi and loser_ofi:
            patterns['winning_patterns']['ofi'] = {
                'mean': mean(winner_ofi),
                'median': median(winner_ofi),
                'min': min(winner_ofi),
                'max': max(winner_ofi),
                'stdev': stdev(winner_ofi) if len(winner_ofi) > 1 else 0,
            }
            patterns['losing_patterns']['ofi'] = {
                'mean': mean(loser_ofi),
                'median': median(loser_ofi),
                'min': min(loser_ofi),
                'max': max(loser_ofi),
                'stdev': stdev(loser_ofi) if len(loser_ofi) > 1 else 0,
            }
            
            # Causal insight: If winner OFI is significantly higher, OFI is a causal factor
            if patterns['winning_patterns']['ofi']['mean'] > patterns['losing_patterns']['ofi']['mean'] * 1.2:
                patterns['causal_factors']['ofi'] = {
                    'importance': 'HIGH',
                    'insight': f"Winners have {patterns['winning_patterns']['ofi']['mean']:.3f} avg OFI vs {patterns['losing_patterns']['ofi']['mean']:.3f} for losers",
                    'threshold': patterns['winning_patterns']['ofi']['min'],
                    'recommendation': f"Require OFI >= {patterns['winning_patterns']['ofi']['min']:.3f} for entry"
                }
    
    # 2. Regime Analysis - What regimes lead to wins?
    winner_regimes = defaultdict(int)
    loser_regimes = defaultdict(int)
    
    for w in winners:
        winner_regimes[w['regime']] += 1
    for l in losers:
        loser_regimes[l['regime']] += 1
    
    for regime in set(list(winner_regimes.keys()) + list(loser_regimes.keys())):
        winner_count = winner_regimes.get(regime, 0)
        loser_count = loser_regimes.get(regime, 0)
        total = winner_count + loser_count
        
        if total > 10:  # Minimum sample size
            win_rate = winner_count / total if total > 0 else 0
            if win_rate > 0.55:
                patterns['causal_factors'][f'regime_{regime}'] = {
                    'importance': 'MEDIUM',
                    'insight': f"{regime} regime has {win_rate:.1%} win rate ({winner_count}W/{loser_count}L)",
                    'recommendation': f"Favor trades in {regime} regime"
                }
            elif win_rate < 0.40:
                patterns['causal_factors'][f'regime_{regime}'] = {
                    'importance': 'MEDIUM',
                    'insight': f"{regime} regime has {win_rate:.1%} win rate ({winner_count}W/{loser_count}L)",
                    'recommendation': f"Avoid trades in {regime} regime"
                }
    
    # 3. Hour Analysis - WHY do certain hours perform better?
    # Look at market conditions during those hours, not just the hour itself
    hour_conditions = defaultdict(lambda: {'winners': [], 'losers': []})
    
    for w in winners:
        hour_conditions[w['hour']]['winners'].append(w)
    for l in losers:
        hour_conditions[l['hour']]['losers'].append(l)
    
    for hour in range(24):
        if hour in hour_conditions:
            winners_h = hour_conditions[hour]['winners']
            losers_h = hour_conditions[hour]['losers']
            
            if len(winners_h) + len(losers_h) >= 10:  # Minimum sample
                # What market conditions exist during this hour?
                winner_ofi_h = [w['ofi'] for w in winners_h if w['ofi'] > 0]
                loser_ofi_h = [l['ofi'] for l in losers_h if l['ofi'] > 0]
                
                winner_regimes_h = [w['regime'] for w in winners_h]
                loser_regimes_h = [l['regime'] for l in losers_h]
                
                # Build causal explanation
                explanation = []
                if winner_ofi_h and loser_ofi_h:
                    avg_winner_ofi = mean(winner_ofi_h)
                    avg_loser_ofi = mean(loser_ofi_h)
                    if avg_winner_ofi > avg_loser_ofi * 1.2:
                        explanation.append(f"Higher OFI during this hour ({avg_winner_ofi:.3f} vs {avg_loser_ofi:.3f})")
                
                winner_regime_mode = max(set(winner_regimes_h), key=winner_regimes_h.count) if winner_regimes_h else None
                if winner_regime_mode:
                    explanation.append(f"Dominant regime: {winner_regime_mode}")
                
                win_rate = len(winners_h) / (len(winners_h) + len(losers_h))
                
                if explanation:
                    patterns['causal_factors'][f'hour_{hour}'] = {
                        'importance': 'MEDIUM',
                        'win_rate': win_rate,
                        'insight': f"Hour {hour} performs well because: {'; '.join(explanation)}",
                        'market_conditions': {
                            'avg_winner_ofi': mean(winner_ofi_h) if winner_ofi_h else 0,
                            'avg_loser_ofi': mean(loser_ofi_h) if loser_ofi_h else 0,
                            'dominant_regime': winner_regime_mode,
                        },
                        'recommendation': f"Trade hour {hour} when: {' AND '.join(explanation)}"
                    }
    
    # 4. Strategy Analysis - WHY does Sentiment-Fusion lose?
    strategy_conditions = defaultdict(lambda: {'winners': [], 'losers': []})
    
    for w in winners:
        strategy_conditions[w['strategy']]['winners'].append(w)
    for l in losers:
        strategy_conditions[l['strategy']]['losers'].append(l)
    
    for strategy in strategy_conditions:
        winners_s = strategy_conditions[strategy]['winners']
        losers_s = strategy_conditions[strategy]['losers']
        
        if len(winners_s) + len(losers_s) >= 20:  # Minimum sample
            # What conditions exist when this strategy wins vs loses?
            winner_ofi_s = [w['ofi'] for w in winners_s if w['ofi'] > 0]
            loser_ofi_s = [l['ofi'] for l in losers_s if l['ofi'] > 0]
            
            winner_regimes_s = [w['regime'] for w in winners_s]
            loser_regimes_s = [l['regime'] for l in losers_s]
            
            explanation = []
            if winner_ofi_s and loser_ofi_s:
                avg_winner_ofi = mean(winner_ofi_s)
                avg_loser_ofi = mean(loser_ofi_s)
                if avg_winner_ofi > avg_loser_ofi * 1.15:
                    explanation.append(f"Wins when OFI is high ({avg_winner_ofi:.3f} vs {avg_loser_ofi:.3f})")
                elif avg_winner_ofi < avg_loser_ofi * 0.85:
                    explanation.append(f"Loses when OFI is low ({avg_winner_ofi:.3f} vs {avg_loser_ofi:.3f})")
            
            winner_regime_mode = max(set(winner_regimes_s), key=winner_regimes_s.count) if winner_regimes_s else None
            loser_regime_mode = max(set(loser_regimes_s), key=loser_regimes_s.count) if loser_regimes_s else None
            
            if winner_regime_mode and winner_regime_mode != loser_regime_mode:
                explanation.append(f"Wins in {winner_regime_mode}, loses in {loser_regime_mode}")
            
            win_rate = len(winners_s) / (len(winners_s) + len(losers_s))
            
            if explanation:
                patterns['causal_factors'][f'strategy_{strategy}'] = {
                    'importance': 'HIGH' if win_rate < 0.40 or win_rate > 0.60 else 'MEDIUM',
                    'win_rate': win_rate,
                    'insight': f"{strategy} performance explained by: {'; '.join(explanation)}",
                    'market_conditions': {
                        'avg_winner_ofi': mean(winner_ofi_s) if winner_ofi_s else 0,
                        'avg_loser_ofi': mean(loser_ofi_s) if loser_ofi_s else 0,
                        'winner_regime': winner_regime_mode,
                        'loser_regime': loser_regime_mode,
                    },
                    'recommendation': f"Use {strategy} only when: {' AND '.join(explanation)}"
                }
    
    # 5. Generate Predictive Rules
    # Build rules based on causal understanding, not just correlation
    for factor_name, factor_data in patterns['causal_factors'].items():
        if factor_data.get('importance') == 'HIGH':
            rule = {
                'condition': factor_name,
                'insight': factor_data['insight'],
                'action': factor_data.get('recommendation', ''),
                'confidence': 'HIGH' if 'threshold' in factor_data else 'MEDIUM',
            }
            patterns['predictive_rules'].append(rule)
    
    return patterns


def generate_proactive_recommendations(patterns: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Generate proactive recommendations based on causal understanding."""
    recommendations = []
    
    # Rule 1: OFI-based proactive entry
    if 'ofi' in patterns['causal_factors']:
        ofi_factor = patterns['causal_factors']['ofi']
        recommendations.append({
            'type': 'PROACTIVE_ENTRY_RULE',
            'priority': 'HIGH',
            'rule': f"Only enter trades when OFI >= {ofi_factor.get('threshold', 0.5):.3f}",
            'reasoning': ofi_factor['insight'],
            'implementation': 'Update conviction_gate.py to enforce OFI threshold proactively',
        })
    
    # Rule 2: Regime-based proactive filtering
    regime_rules = [k for k in patterns['causal_factors'] if k.startswith('regime_')]
    for regime_key in regime_rules:
        regime_factor = patterns['causal_factors'][regime_key]
        if regime_factor.get('importance') == 'MEDIUM':
            recommendations.append({
                'type': 'PROACTIVE_REGIME_FILTER',
                'priority': 'MEDIUM',
                'rule': regime_factor['recommendation'],
                'reasoning': regime_factor['insight'],
                'implementation': 'Check current regime before entry, apply filter proactively',
            })
    
    # Rule 3: Strategy-specific proactive conditions
    strategy_rules = [k for k in patterns['causal_factors'] if k.startswith('strategy_')]
    for strategy_key in strategy_rules:
        strategy_factor = patterns['causal_factors'][strategy_key]
        if strategy_factor.get('win_rate', 0.5) < 0.40:  # Losing strategy
            recommendations.append({
                'type': 'PROACTIVE_STRATEGY_CONDITION',
                'priority': 'HIGH',
                'rule': strategy_factor['recommendation'],
                'reasoning': strategy_factor['insight'],
                'implementation': f"Only use {strategy_key.replace('strategy_', '')} when market conditions match winning patterns",
            })
    
    # Rule 4: Hour-based proactive conditions (based on WHY, not just hour)
    hour_rules = [k for k in patterns['causal_factors'] if k.startswith('hour_')]
    for hour_key in hour_rules:
        hour_factor = patterns['causal_factors'][hour_key]
        recommendations.append({
            'type': 'PROACTIVE_HOUR_CONDITION',
            'priority': 'MEDIUM',
            'rule': hour_factor['recommendation'],
            'reasoning': hour_factor['insight'],
            'implementation': 'Check market conditions (OFI, regime) during this hour, not just the hour itself',
        })
    
    return recommendations


def main():
    print("="*80)
    print("CAUSAL PATTERN ANALYZER - Understanding WHY")
    print("="*80)
    print(f"Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print()
    
    # Load trades
    print("Loading trades...")
    try:
        portfolio_path = PathRegistry.get_path("logs", "positions_futures.json")
        with open(portfolio_path, 'r') as f:
            portfolio = json.load(f)
        
        closed = portfolio.get('closed_positions', [])
        closed = [t for t in closed if t.get('bot_type', 'alpha') == 'alpha']
        
        # Exclude bad trades window (Dec 18, 2025 1:00-6:00 AM UTC)
        bad_start = datetime(2025, 12, 18, 1, 0, 0, tzinfo=timezone.utc).timestamp()
        bad_end = datetime(2025, 12, 18, 6, 0, 0, tzinfo=timezone.utc).timestamp()
        
        filtered = []
        for trade in closed:
            closed_at = trade.get('closed_at', '')
            if closed_at:
                try:
                    if isinstance(closed_at, str):
                        ts = datetime.fromisoformat(closed_at.replace('Z', '+00:00')).timestamp()
                    else:
                        ts = float(closed_at)
                    
                    if bad_start <= ts <= bad_end:
                        continue
                except:
                    pass
            filtered.append(trade)
        
        # Take last 300
        filtered.sort(key=lambda t: (
            datetime.fromisoformat(t.get('closed_at', '2000-01-01').replace('Z', '+00:00')).timestamp()
            if isinstance(t.get('closed_at'), str) else 0
        ), reverse=True)
        trades = filtered[:300]
        
        print(f"   ✅ Loaded {len(trades)} trades (after excluding bad trades window)")
        print()
    except Exception as e:
        print(f"❌ Error loading trades: {e}")
        import traceback
        traceback.print_exc()
        return 1
    
    # Analyze causal patterns
    print("="*80)
    print("ANALYZING CAUSAL PATTERNS")
    print("="*80)
    print("   Understanding WHY trades succeed/fail, not just WHAT happened")
    print()
    
    patterns = analyze_causal_patterns(trades)
    
    # Display findings
    print("="*80)
    print("CAUSAL FACTORS IDENTIFIED")
    print("="*80)
    print()
    
    for factor_name, factor_data in sorted(patterns['causal_factors'].items(), 
                                           key=lambda x: {'HIGH': 3, 'MEDIUM': 2, 'LOW': 1}.get(x[1].get('importance', 'LOW'), 0),
                                           reverse=True):
        importance = factor_data.get('importance', 'MEDIUM')
        insight = factor_data.get('insight', '')
        recommendation = factor_data.get('recommendation', '')
        
        icon = '🔴' if importance == 'HIGH' else '🟡'
        print(f"{icon} {factor_name.upper()}")
        print(f"   {insight}")
        if recommendation:
            print(f"   → {recommendation}")
        print()
    
    # Generate proactive recommendations
    print("="*80)
    print("PROACTIVE RECOMMENDATIONS")
    print("="*80)
    print("   Based on causal understanding, not reactive correlation")
    print()
    
    recommendations = generate_proactive_recommendations(patterns)
    
    for rec in recommendations:
        priority = rec.get('priority', 'MEDIUM')
        icon = '🔴' if priority == 'HIGH' else '🟡'
        print(f"{icon} {rec['type']}")
        print(f"   Rule: {rec['rule']}")
        print(f"   Reasoning: {rec['reasoning']}")
        print(f"   Implementation: {rec['implementation']}")
        print()
    
    # Save results
    output = {
        'generated_at': datetime.now().isoformat(),
        'trades_analyzed': len(trades),
        'patterns': patterns,
        'recommendations': recommendations,
    }
    
    output_path_str = PathRegistry.get_path("feature_store", "causal_pattern_analysis.json")
    output_path = Path(output_path_str)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    with open(output_path, 'w') as f:
        json.dump(output, f, indent=2, default=str)
    
    print("="*80)
    print("ANALYSIS COMPLETE")
    print("="*80)
    print(f"✅ Results saved to: {output_path}")
    print()
    print("📊 Summary:")
    print(f"   - Analyzed {len(trades)} trades")
    print(f"   - Identified {len(patterns['causal_factors'])} causal factors")
    print(f"   - Generated {len(recommendations)} proactive recommendations")
    print()
    print("🎯 Next Steps:")
    print("   1. Review causal factors to understand WHY patterns occur")
    print("   2. Implement proactive rules based on market conditions")
    print("   3. Test proactive rules in paper trading")
    print("   4. Monitor if proactive approach improves performance")
    print("="*80)
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
