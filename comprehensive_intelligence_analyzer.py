#!/usr/bin/env python3
"""
Comprehensive Intelligence Analyzer - Understanding WHY ALL Signals Work/Don't Work
====================================================================================
Complete causal analysis of ALL intelligence components:
- Individual signal components (OFI, ensemble, funding, liquidation, whale flow, etc.)
- Signal combinations and interactions
- Strategy-specific intelligence performance
- Market microstructure features
- Why intelligence is good/bad in different conditions

Goal: Understand → Improve → Trade Better → Learn More → Trade Even Better
"""

import os
import sys
import json
from pathlib import Path
from datetime import datetime, timezone, timedelta
from collections import defaultdict
from typing import Dict, List, Any, Tuple, Optional
from statistics import mean, median, stdev

sys.path.insert(0, os.path.dirname(__file__))

from src.data_registry import DataRegistry as DR
from src.infrastructure.path_registry import PathRegistry


# All intelligence signal components we track
INTELLIGENCE_COMPONENTS = [
    'ofi', 'ensemble', 'funding', 'liquidation', 'whale_flow', 
    'fear_greed', 'hurst', 'lead_lag', 'volatility_skew', 
    'oi_velocity', 'oi_divergence', 'mtf', 'volatility', 'volume',
    'taker_ratio', 'liquidation_pressure', 'funding_rate'
]


def extract_all_intelligence(trade: Dict) -> Dict[str, Any]:
    """Extract ALL intelligence components from a trade record."""
    intelligence = {
        # Core signals
        'ofi': 0.0,
        'ensemble': 0.0,
        'mtf': 0.0,
        
        # Market microstructure
        'funding': 0.0,
        'liquidation': 0.0,
        'whale_flow': 0.0,
        'fear_greed': 50.0,
        'hurst': 0.5,
        'lead_lag': 0.0,
        'volatility_skew': 0.0,
        'oi_velocity': 0.0,
        'oi_divergence': 0.0,
        
        # Market conditions
        'regime': 'unknown',
        'volatility': 0.0,
        'volume': 0.0,
        'taker_ratio': 0.5,
        'liquidation_pressure': 0.0,
        'funding_rate': 0.0,
        
        # Strategy
        'strategy': trade.get('strategy', 'UNKNOWN'),
        'direction': trade.get('direction', trade.get('side', 'UNKNOWN')),
        'symbol': trade.get('symbol', 'UNKNOWN'),
        
        # Outcome
        'pnl': 0.0,
        'win': False,
    }
    
    # Extract P&L
    pnl = trade.get('net_pnl', trade.get('pnl', 0)) or 0
    intelligence['pnl'] = pnl
    intelligence['win'] = pnl > 0
    
    # Extract from signal_ctx (primary source)
    signal_ctx = trade.get('signal_ctx', {})
    if signal_ctx:
        intelligence['ofi'] = abs(signal_ctx.get('ofi', signal_ctx.get('ofi_score', 0)) or 0)
        intelligence['ensemble'] = abs(signal_ctx.get('ensemble', signal_ctx.get('ensemble_score', 0)) or 0)
        intelligence['mtf'] = signal_ctx.get('mtf', signal_ctx.get('mtf_confidence', 0)) or 0
        intelligence['regime'] = signal_ctx.get('regime', signal_ctx.get('market_regime', 'unknown'))
        intelligence['volatility'] = signal_ctx.get('volatility', signal_ctx.get('vol_regime', 0)) or 0
        intelligence['volume'] = signal_ctx.get('volume', signal_ctx.get('volume_24h', 0)) or 0
        intelligence['funding_rate'] = signal_ctx.get('funding_rate', 0) or 0
        intelligence['liquidation_pressure'] = signal_ctx.get('liquidation_pressure', 0) or 0
        intelligence['whale_flow'] = signal_ctx.get('whale_flow', 0) or 0
        intelligence['fear_greed'] = signal_ctx.get('fear_greed', signal_ctx.get('fg_index', 50)) or 50
        intelligence['taker_ratio'] = signal_ctx.get('taker_buy_ratio', 0.5) or 0.5
    
    # Extract from ml_features (if available)
    ml_features = trade.get('ml_features', {})
    if ml_features:
        intelligence['hurst'] = ml_features.get('hurst', 0.5) or 0.5
        intelligence['lead_lag'] = ml_features.get('lead_lag', 0) or 0
        intelligence['volatility_skew'] = ml_features.get('volatility_skew', 0) or 0
        intelligence['oi_velocity'] = ml_features.get('oi_velocity', 0) or 0
        intelligence['oi_divergence'] = ml_features.get('oi_divergence', 0) or 0
    
    # Extract from signal_components (if available)
    signal_components = trade.get('signal_components', {})
    if signal_components:
        intelligence['funding'] = signal_components.get('funding', 0) or 0
        intelligence['liquidation'] = signal_components.get('liquidation', 0) or 0
        intelligence['whale_flow'] = signal_components.get('whale_flow', intelligence['whale_flow']) or 0
        intelligence['fear_greed'] = signal_components.get('fear_greed', intelligence['fear_greed']) or 50
        intelligence['hurst'] = signal_components.get('hurst', intelligence['hurst']) or 0.5
        intelligence['lead_lag'] = signal_components.get('lead_lag', intelligence['lead_lag']) or 0
        intelligence['volatility_skew'] = signal_components.get('volatility_skew', intelligence['volatility_skew']) or 0
        intelligence['oi_velocity'] = signal_components.get('oi_velocity', intelligence['oi_velocity']) or 0
        intelligence['oi_divergence'] = signal_components.get('oi_divergence', intelligence['oi_divergence']) or 0
    
    # Extract from _raw fields (fallback)
    _raw = trade.get('_raw', {})
    if _raw:
        intelligence['ofi'] = abs(_raw.get('ofi', _raw.get('ofi_score', intelligence['ofi'])) or 0)
        intelligence['ensemble'] = abs(_raw.get('ensemble', _raw.get('ensemble_score', intelligence['ensemble'])) or 0)
        intelligence['regime'] = _raw.get('regime', intelligence['regime'])
    
    # Extract timing
    entry_time = trade.get('opened_at', trade.get('entry_timestamp', trade.get('timestamp', '')))
    if entry_time:
        try:
            if isinstance(entry_time, str):
                dt = datetime.fromisoformat(entry_time.replace('Z', '+00:00'))
            else:
                dt = datetime.fromtimestamp(entry_time)
            intelligence['hour'] = dt.hour
            intelligence['session'] = get_session(dt)
        except:
            intelligence['hour'] = 12
            intelligence['session'] = 'unknown'
    else:
        intelligence['hour'] = 12
        intelligence['session'] = 'unknown'
    
    return intelligence


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


def analyze_signal_component(component_name: str, trades: List[Dict]) -> Dict[str, Any]:
    """Analyze why a specific signal component works/doesn't work."""
    winners = [t for t in trades if t.get('win', False)]
    losers = [t for t in trades if t.get('win', False) == False]
    
    if not winners or not losers:
        return {}
    
    winner_values = [t.get(component_name, 0) for t in winners if t.get(component_name, 0) != 0]
    loser_values = [t.get(component_name, 0) for t in losers if t.get(component_name, 0) != 0]
    
    if not winner_values or not loser_values:
        return {}
    
    analysis = {
        'component': component_name,
        'winners': {
            'count': len(winner_values),
            'mean': mean(winner_values),
            'median': median(winner_values),
            'min': min(winner_values),
            'max': max(winner_values),
            'stdev': stdev(winner_values) if len(winner_values) > 1 else 0,
        },
        'losers': {
            'count': len(loser_values),
            'mean': mean(loser_values),
            'median': median(loser_values),
            'min': min(loser_values),
            'max': max(loser_values),
            'stdev': stdev(loser_values) if len(loser_values) > 1 else 0,
        },
        'causal_insight': None,
        'recommendation': None,
    }
    
    # Determine if this component is a causal factor
    winner_mean = analysis['winners']['mean']
    loser_mean = analysis['losers']['mean']
    
    if winner_mean > 0 and loser_mean > 0:
        ratio = winner_mean / loser_mean if loser_mean > 0 else 0
        if ratio > 1.2:  # Winners have 20%+ higher values
            analysis['causal_insight'] = f"Winners have {ratio:.2f}x higher {component_name} ({winner_mean:.3f} vs {loser_mean:.3f})"
            analysis['recommendation'] = f"Require {component_name} >= {analysis['winners']['min']:.3f} for entry"
            analysis['importance'] = 'HIGH'
        elif ratio < 0.8:  # Losers have 20%+ higher values
            analysis['causal_insight'] = f"Losers have {ratio:.2f}x higher {component_name} ({loser_mean:.3f} vs {winner_mean:.3f})"
            analysis['recommendation'] = f"Avoid trades when {component_name} >= {analysis['losers']['mean']:.3f}"
            analysis['importance'] = 'HIGH'
        else:
            analysis['importance'] = 'LOW'
    elif winner_mean > 0 and loser_mean == 0:
        analysis['causal_insight'] = f"Winners have {component_name} ({winner_mean:.3f}), losers have none"
        analysis['recommendation'] = f"Require {component_name} > 0 for entry"
        analysis['importance'] = 'HIGH'
    elif winner_mean == 0 and loser_mean > 0:
        analysis['causal_insight'] = f"Losers have {component_name} ({loser_mean:.3f}), winners have none"
        analysis['recommendation'] = f"Avoid trades when {component_name} > 0"
        analysis['importance'] = 'HIGH'
    else:
        analysis['importance'] = 'LOW'
    
    return analysis


def analyze_signal_combinations(trades: List[Dict]) -> Dict[str, Any]:
    """Analyze which signal combinations work best."""
    combinations = defaultdict(lambda: {'winners': [], 'losers': []})
    
    for trade in trades:
        # Build combination signature
        ofi_bucket = 'high' if trade.get('ofi', 0) >= 0.5 else 'low'
        ensemble_bucket = 'high' if trade.get('ensemble', 0) >= 0.3 else 'low'
        regime = trade.get('regime', 'unknown')
        
        combo_key = f"OFI:{ofi_bucket}|ENS:{ensemble_bucket}|REG:{regime}"
        
        if trade.get('win', False):
            combinations[combo_key]['winners'].append(trade)
        else:
            combinations[combo_key]['losers'].append(trade)
    
    # Analyze each combination
    combo_analysis = {}
    for combo_key, data in combinations.items():
        winners = data['winners']
        losers = data['losers']
        total = len(winners) + len(losers)
        
        if total >= 10:  # Minimum sample
            win_rate = len(winners) / total if total > 0 else 0
            avg_pnl = mean([t.get('pnl', 0) for t in winners + losers])
            
            combo_analysis[combo_key] = {
                'win_rate': win_rate,
                'avg_pnl': avg_pnl,
                'total_trades': total,
                'winners': len(winners),
                'losers': len(losers),
                'importance': 'HIGH' if win_rate > 0.60 or win_rate < 0.40 else 'MEDIUM',
            }
    
    return combo_analysis


def analyze_strategy_intelligence(strategy_name: str, trades: List[Dict]) -> Dict[str, Any]:
    """Analyze why a specific strategy works/doesn't work."""
    strategy_trades = [t for t in trades if t.get('strategy', '').lower() == strategy_name.lower()]
    
    if len(strategy_trades) < 20:
        return {}
    
    winners = [t for t in strategy_trades if t.get('win', False)]
    losers = [t for t in strategy_trades if not t.get('win', False)]
    
    analysis = {
        'strategy': strategy_name,
        'total_trades': len(strategy_trades),
        'win_rate': len(winners) / len(strategy_trades) if strategy_trades else 0,
        'avg_pnl': mean([t.get('pnl', 0) for t in strategy_trades]),
        'winning_conditions': {},
        'losing_conditions': {},
        'causal_factors': [],
        'recommendations': [],
    }
    
    # Analyze what conditions lead to wins vs losses
    for component in INTELLIGENCE_COMPONENTS:
        winner_values = [t.get(component, 0) for t in winners if t.get(component, 0) != 0]
        loser_values = [t.get(component, 0) for t in losers if t.get(component, 0) != 0]
        
        if winner_values and loser_values:
            winner_mean = mean(winner_values)
            loser_mean = mean(loser_values)
            
            if winner_mean > loser_mean * 1.15:
                analysis['winning_conditions'][component] = {
                    'winner_avg': winner_mean,
                    'loser_avg': loser_mean,
                    'threshold': min(winner_values),
                }
                analysis['causal_factors'].append(f"{component} >= {min(winner_values):.3f}")
                analysis['recommendations'].append(f"Use {strategy_name} only when {component} >= {min(winner_values):.3f}")
            elif loser_mean > winner_mean * 1.15:
                analysis['losing_conditions'][component] = {
                    'winner_avg': winner_mean,
                    'loser_avg': loser_mean,
                    'threshold': max(loser_values),
                }
                analysis['causal_factors'].append(f"{component} < {max(loser_values):.3f}")
                analysis['recommendations'].append(f"Avoid {strategy_name} when {component} >= {max(loser_values):.3f}")
    
    return analysis


def analyze_regime_intelligence(trades: List[Dict]) -> Dict[str, Any]:
    """Analyze why certain regimes work/don't work."""
    regime_data = defaultdict(lambda: {'winners': [], 'losers': []})
    
    for trade in trades:
        regime = trade.get('regime', 'unknown')
        if trade.get('win', False):
            regime_data[regime]['winners'].append(trade)
        else:
            regime_data[regime]['losers'].append(trade)
    
    regime_analysis = {}
    for regime, data in regime_data.items():
        winners = data['winners']
        losers = data['losers']
        total = len(winners) + len(losers)
        
        if total >= 20:
            win_rate = len(winners) / total if total > 0 else 0
            avg_pnl = mean([t.get('pnl', 0) for t in winners + losers])
            
            # What signals work in this regime?
            winning_signals = {}
            for component in INTELLIGENCE_COMPONENTS:
                winner_values = [t.get(component, 0) for t in winners if t.get(component, 0) != 0]
                if winner_values:
                    winning_signals[component] = {
                        'mean': mean(winner_values),
                        'min': min(winner_values),
                    }
            
            regime_analysis[regime] = {
                'win_rate': win_rate,
                'avg_pnl': avg_pnl,
                'total_trades': total,
                'winning_signals': winning_signals,
                'importance': 'HIGH' if win_rate > 0.60 or win_rate < 0.40 else 'MEDIUM',
            }
    
    return regime_analysis


def generate_improvement_plan(analyses: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Generate actionable improvement plan based on all analyses."""
    improvements = []
    
    # 1. Signal component improvements
    for component, analysis in analyses.get('signal_components', {}).items():
        if analysis.get('importance') == 'HIGH' and analysis.get('recommendation'):
            improvements.append({
                'type': 'SIGNAL_THRESHOLD',
                'component': component,
                'action': analysis['recommendation'],
                'reasoning': analysis['causal_insight'],
                'priority': 'HIGH',
            })
    
    # 2. Strategy improvements
    for strategy, analysis in analyses.get('strategies', {}).items():
        if analysis.get('win_rate', 0.5) < 0.40:  # Losing strategy
            for rec in analysis.get('recommendations', []):
                improvements.append({
                    'type': 'STRATEGY_CONDITION',
                    'strategy': strategy,
                    'action': rec,
                    'reasoning': f"{strategy} has {analysis['win_rate']:.1%} win rate",
                    'priority': 'HIGH',
                })
    
    # 3. Signal combination improvements
    for combo, data in analyses.get('combinations', {}).items():
        if data.get('win_rate', 0.5) > 0.60:  # Winning combination
            improvements.append({
                'type': 'COMBINATION_RULE',
                'combination': combo,
                'action': f"Favor trades matching: {combo}",
                'reasoning': f"{combo} has {data['win_rate']:.1%} win rate",
                'priority': 'MEDIUM',
            })
        elif data.get('win_rate', 0.5) < 0.40:  # Losing combination
            improvements.append({
                'type': 'COMBINATION_RULE',
                'combination': combo,
                'action': f"Avoid trades matching: {combo}",
                'reasoning': f"{combo} has {data['win_rate']:.1%} win rate",
                'priority': 'MEDIUM',
            })
    
    # 4. Regime-specific improvements
    for regime, data in analyses.get('regimes', {}).items():
        if data.get('win_rate', 0.5) > 0.60:
            improvements.append({
                'type': 'REGIME_OPTIMIZATION',
                'regime': regime,
                'action': f"Optimize for {regime} regime conditions",
                'reasoning': f"{regime} has {data['win_rate']:.1%} win rate",
                'priority': 'MEDIUM',
            })
    
    return improvements


def main():
    print("="*80)
    print("COMPREHENSIVE INTELLIGENCE ANALYZER - Understanding WHY ALL Signals Work")
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
        
        # Take last 500 for comprehensive analysis
        filtered.sort(key=lambda t: (
            datetime.fromisoformat(t.get('closed_at', '2000-01-01').replace('Z', '+00:00')).timestamp()
            if isinstance(t.get('closed_at'), str) else 0
        ), reverse=True)
        trades = filtered[:500]
        
        print(f"   ✅ Loaded {len(trades)} trades (after excluding bad trades window)")
        print()
    except Exception as e:
        print(f"❌ Error loading trades: {e}")
        import traceback
        traceback.print_exc()
        return 1
    
    # Extract all intelligence from trades
    print("="*80)
    print("EXTRACTING ALL INTELLIGENCE COMPONENTS")
    print("="*80)
    print("   Extracting: OFI, Ensemble, Funding, Liquidation, Whale Flow,")
    print("               Fear/Greed, Hurst, Lead/Lag, Volatility Skew,")
    print("               OI Velocity, OI Divergence, Regime, Volatility, Volume...")
    print()
    
    intelligence_data = []
    for trade in trades:
        intel = extract_all_intelligence(trade)
        intelligence_data.append(intel)
    
    print(f"   ✅ Extracted intelligence from {len(intelligence_data)} trades")
    print()
    
    # Analyze each signal component
    print("="*80)
    print("ANALYZING INDIVIDUAL SIGNAL COMPONENTS")
    print("="*80)
    print("   Understanding WHY each signal works/doesn't work")
    print()
    
    signal_analyses = {}
    for component in INTELLIGENCE_COMPONENTS:
        analysis = analyze_signal_component(component, intelligence_data)
        if analysis and analysis.get('importance') in ['HIGH', 'MEDIUM']:
            signal_analyses[component] = analysis
    
    # Display signal component findings
    for component, analysis in sorted(signal_analyses.items(), 
                                      key=lambda x: {'HIGH': 3, 'MEDIUM': 2, 'LOW': 1}.get(x[1].get('importance', 'LOW'), 0),
                                      reverse=True):
        importance = analysis.get('importance', 'MEDIUM')
        insight = analysis.get('causal_insight', '')
        recommendation = analysis.get('recommendation', '')
        
        icon = '🔴' if importance == 'HIGH' else '🟡'
        print(f"{icon} {component.upper()}")
        if insight:
            print(f"   {insight}")
        if recommendation:
            print(f"   → {recommendation}")
        print()
    
    # Analyze signal combinations
    print("="*80)
    print("ANALYZING SIGNAL COMBINATIONS")
    print("="*80)
    print("   Understanding which combinations work best")
    print()
    
    combo_analysis = analyze_signal_combinations(intelligence_data)
    
    for combo, data in sorted(combo_analysis.items(), 
                             key=lambda x: x[1].get('win_rate', 0.5), 
                             reverse=True)[:10]:
        win_rate = data.get('win_rate', 0)
        total = data.get('total_trades', 0)
        icon = '🟢' if win_rate > 0.60 else '🟡' if win_rate > 0.50 else '🔴'
        print(f"{icon} {combo}")
        print(f"   Win Rate: {win_rate:.1%}, Trades: {total}")
        print()
    
    # Analyze strategies
    print("="*80)
    print("ANALYZING STRATEGY INTELLIGENCE")
    print("="*80)
    print("   Understanding WHY each strategy works/doesn't work")
    print()
    
    strategies = set(t.get('strategy', 'UNKNOWN') for t in intelligence_data)
    strategy_analyses = {}
    
    for strategy in strategies:
        analysis = analyze_strategy_intelligence(strategy, intelligence_data)
        if analysis:
            strategy_analyses[strategy] = analysis
    
    for strategy, analysis in sorted(strategy_analyses.items(),
                                    key=lambda x: x[1].get('win_rate', 0.5)):
        win_rate = analysis.get('win_rate', 0)
        total = analysis.get('total_trades', 0)
        icon = '🟢' if win_rate > 0.60 else '🟡' if win_rate > 0.50 else '🔴'
        print(f"{icon} {strategy.upper()}")
        print(f"   Win Rate: {win_rate:.1%}, Trades: {total}")
        if analysis.get('causal_factors'):
            print(f"   Causal Factors: {', '.join(analysis['causal_factors'][:3])}")
        if analysis.get('recommendations'):
            print(f"   → {analysis['recommendations'][0]}")
        print()
    
    # Analyze regimes
    print("="*80)
    print("ANALYZING REGIME INTELLIGENCE")
    print("="*80)
    print("   Understanding which signals work in which regimes")
    print()
    
    regime_analysis = analyze_regime_intelligence(intelligence_data)
    
    for regime, data in sorted(regime_analysis.items(),
                              key=lambda x: x[1].get('win_rate', 0.5),
                              reverse=True):
        win_rate = data.get('win_rate', 0)
        total = data.get('total_trades', 0)
        icon = '🟢' if win_rate > 0.60 else '🟡' if win_rate > 0.50 else '🔴'
        print(f"{icon} {regime.upper()}")
        print(f"   Win Rate: {win_rate:.1%}, Trades: {total}")
        winning_signals = data.get('winning_signals', {})
        if winning_signals:
            top_signals = sorted(winning_signals.items(), 
                               key=lambda x: x[1].get('mean', 0), 
                               reverse=True)[:3]
            print(f"   Top Signals: {', '.join([f'{k}={v[\"mean\"]:.3f}' for k, v in top_signals])}")
        print()
    
    # Generate improvement plan
    print("="*80)
    print("INTELLIGENCE IMPROVEMENT PLAN")
    print("="*80)
    print("   Actionable improvements based on causal understanding")
    print()
    
    all_analyses = {
        'signal_components': signal_analyses,
        'strategies': strategy_analyses,
        'combinations': combo_analysis,
        'regimes': regime_analysis,
    }
    
    improvements = generate_improvement_plan(all_analyses)
    
    for imp in sorted(improvements, 
                     key=lambda x: {'HIGH': 3, 'MEDIUM': 2, 'LOW': 1}.get(x.get('priority', 'LOW'), 0),
                     reverse=True)[:20]:
        priority = imp.get('priority', 'MEDIUM')
        icon = '🔴' if priority == 'HIGH' else '🟡'
        print(f"{icon} {imp['type']}: {imp.get('component', imp.get('strategy', imp.get('combination', '')))}")
        print(f"   Action: {imp['action']}")
        print(f"   Reasoning: {imp['reasoning']}")
        print()
    
    # Save results
    output = {
        'generated_at': datetime.now().isoformat(),
        'trades_analyzed': len(intelligence_data),
        'analyses': all_analyses,
        'improvements': improvements,
    }
    
    output_path_str = PathRegistry.get_path("feature_store", "comprehensive_intelligence_analysis.json")
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
    print(f"   - Analyzed {len(intelligence_data)} trades")
    print(f"   - Analyzed {len(signal_analyses)} signal components")
    print(f"   - Analyzed {len(strategy_analyses)} strategies")
    print(f"   - Analyzed {len(combo_analysis)} signal combinations")
    print(f"   - Analyzed {len(regime_analysis)} regimes")
    print(f"   - Generated {len(improvements)} improvement recommendations")
    print()
    print("🎯 Next Steps:")
    print("   1. Review signal component analyses to understand WHY each works")
    print("   2. Review strategy analyses to understand WHY strategies succeed/fail")
    print("   3. Implement improvement recommendations")
    print("   4. Test improvements in paper trading")
    print("   5. Monitor performance and iterate")
    print("   6. Cycle: Understand → Improve → Trade Better → Learn More → Trade Even Better")
    print("="*80)
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
