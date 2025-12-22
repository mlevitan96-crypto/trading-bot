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
    
    # Extract P&L - check outcome dict first (enriched_decisions format), then direct fields
    outcome = trade.get('outcome', {})
    pnl = outcome.get('pnl_usd', outcome.get('pnl', 0)) or trade.get('net_pnl', trade.get('pnl', 0)) or 0
    intelligence['pnl'] = pnl
    intelligence['win'] = pnl > 0
    
    # Extract from signal_ctx FIRST (primary source for enriched_decisions.jsonl)
    # This is the canonical format with complete intelligence data
    signal_ctx = trade.get('signal_ctx', {})
    if signal_ctx:
        # Extract from signal_ctx (enriched_decisions format)
        ofi_val = signal_ctx.get('ofi') or signal_ctx.get('ofi_score')
        if ofi_val is not None:
            intelligence['ofi'] = abs(float(ofi_val))
        
        ens_val = signal_ctx.get('ensemble') or signal_ctx.get('ensemble_score') or signal_ctx.get('composite')
        if ens_val is not None:
            intelligence['ensemble'] = abs(float(ens_val))
        
        mtf_val = signal_ctx.get('mtf') or signal_ctx.get('mtf_confidence')
        if mtf_val is not None:
            intelligence['mtf'] = float(mtf_val)
        
        if signal_ctx.get('regime'):
            intelligence['regime'] = signal_ctx.get('regime', 'unknown')
        if signal_ctx.get('volatility'):
            intelligence['volatility'] = float(signal_ctx.get('volatility', 0))
        if signal_ctx.get('volume'):
            intelligence['volume'] = float(signal_ctx.get('volume', signal_ctx.get('volume_24h', 0)))
        if signal_ctx.get('funding_rate'):
            intelligence['funding_rate'] = float(signal_ctx.get('funding_rate', 0))
        if signal_ctx.get('liquidation_pressure'):
            intelligence['liquidation_pressure'] = float(signal_ctx.get('liquidation_pressure', 0))
        if signal_ctx.get('whale_flow'):
            intelligence['whale_flow'] = float(signal_ctx.get('whale_flow', 0))
        if signal_ctx.get('fear_greed') or signal_ctx.get('fg_index'):
            intelligence['fear_greed'] = float(signal_ctx.get('fear_greed', signal_ctx.get('fg_index', 50)))
        if signal_ctx.get('taker_buy_ratio'):
            intelligence['taker_ratio'] = float(signal_ctx.get('taker_buy_ratio', 0.5))
    
    # Extract from intelligence dict (if available in original signal record)
    # Some signals store detailed intelligence in an 'intelligence' field
    intelligence_dict = trade.get('intelligence', {})
    if intelligence_dict:
        # Extract from intelligence.market_intel or intelligence directly
        market_intel = intelligence_dict.get('market_intel', {})
        if market_intel:
            if market_intel.get('funding_rate'):
                intelligence['funding_rate'] = float(market_intel.get('funding_rate', 0))
            if market_intel.get('liquidation_pressure'):
                intelligence['liquidation_pressure'] = float(market_intel.get('liquidation_pressure', 0))
            if market_intel.get('whale_flow'):
                intelligence['whale_flow'] = float(market_intel.get('whale_flow', 0))
            if market_intel.get('fear_greed'):
                intelligence['fear_greed'] = float(market_intel.get('fear_greed', 50))
            if market_intel.get('taker_ratio'):
                intelligence['taker_ratio'] = float(market_intel.get('taker_ratio', 0.5))
        
        # Direct intelligence fields
        if intelligence_dict.get('fear_greed'):
            intelligence['fear_greed'] = float(intelligence_dict.get('fear_greed', 50))
        if intelligence_dict.get('taker_ratio'):
            intelligence['taker_ratio'] = float(intelligence_dict.get('taker_ratio', 0.5))
        if intelligence_dict.get('liquidation_bias'):
            intelligence['liquidation'] = float(intelligence_dict.get('liquidation_bias', 0))
    
    # Fallback to position record directly (for positions_futures.json format)
    # These fields are stored directly in the position when opened (see position_manager.py)
    # Check if value exists and is not None/0 before using
    if intelligence['ofi'] == 0:
        ofi_val = trade.get('ofi_score') or trade.get('ofi') or trade.get('entry_ofi')
        if ofi_val is not None and ofi_val != 0:
            intelligence['ofi'] = abs(float(ofi_val))
    
    if intelligence['ensemble'] == 0:
        ens_val = trade.get('ensemble_score') or trade.get('ensemble') or trade.get('composite')
        if ens_val is not None and ens_val != 0:
            intelligence['ensemble'] = abs(float(ens_val))
    
    if intelligence['mtf'] == 0:
        mtf_val = trade.get('mtf_confidence') or trade.get('mtf')
        if mtf_val is not None and mtf_val != 0:
            intelligence['mtf'] = float(mtf_val)
    
    if intelligence['regime'] == 'unknown':
        regime_val = trade.get('regime') or trade.get('market_regime')
        if regime_val:
            intelligence['regime'] = regime_val
    
    if intelligence['volatility'] == 0:
        vol_val = trade.get('volatility') or trade.get('vol_regime')
        if vol_val is not None and vol_val != 0:
            intelligence['volatility'] = float(vol_val)
    
    # Extract from ml_features (if available)
    ml_features = trade.get('ml_features', {})
    if ml_features:
        intelligence['hurst'] = ml_features.get('hurst', 0.5) or 0.5
        intelligence['lead_lag'] = ml_features.get('lead_lag', 0) or 0
        intelligence['volatility_skew'] = ml_features.get('volatility_skew', 0) or 0
        intelligence['oi_velocity'] = ml_features.get('oi_velocity', 0) or 0
        intelligence['oi_divergence'] = ml_features.get('oi_divergence', 0) or 0
    
    # Extract from signal_components (if available - stored in position when opened)
    signal_components = trade.get('signal_components', {})
    if signal_components:
        intelligence['funding'] = signal_components.get('funding', signal_components.get('funding_rate', 0)) or 0
        intelligence['liquidation'] = signal_components.get('liquidation', signal_components.get('liquidation_pressure', 0)) or 0
        intelligence['whale_flow'] = signal_components.get('whale_flow', intelligence['whale_flow']) or 0
        intelligence['fear_greed'] = signal_components.get('fear_greed', signal_components.get('fg_index', intelligence['fear_greed'])) or 50
        intelligence['hurst'] = signal_components.get('hurst', intelligence['hurst']) or 0.5
        intelligence['lead_lag'] = signal_components.get('lead_lag', intelligence['lead_lag']) or 0
        intelligence['volatility_skew'] = signal_components.get('volatility_skew', intelligence['volatility_skew']) or 0
        intelligence['oi_velocity'] = signal_components.get('oi_velocity', intelligence['oi_velocity']) or 0
        intelligence['oi_divergence'] = signal_components.get('oi_divergence', intelligence['oi_divergence']) or 0
        intelligence['funding_rate'] = signal_components.get('funding_rate', signal_components.get('funding', intelligence['funding_rate'])) or 0
        intelligence['liquidation_pressure'] = signal_components.get('liquidation_pressure', signal_components.get('liquidation', intelligence['liquidation_pressure'])) or 0
    
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
    
    # Get values, including 0 values if they're meaningful (e.g., for boolean flags)
    # But filter out None/missing values
    winner_values = [t.get(component_name) for t in winners if t.get(component_name) is not None]
    loser_values = [t.get(component_name) for t in losers if t.get(component_name) is not None]
    
    # For components that might be 0, include them if we have enough data
    # For components that should be non-zero, filter out zeros
    if component_name in ['funding', 'liquidation', 'whale_flow', 'fear_greed', 'hurst', 
                          'lead_lag', 'volatility_skew', 'oi_velocity', 'oi_divergence']:
        # These should have meaningful non-zero values
        winner_values = [v for v in winner_values if v != 0]
        loser_values = [v for v in loser_values if v != 0]
    
    # Need at least 10 samples in each group for meaningful analysis
    if len(winner_values) < 10 or len(loser_values) < 10:
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
    """Analyze which signal combinations work best - WITH WHY."""
    combinations = defaultdict(lambda: {'winners': [], 'losers': []})
    
    for trade in trades:
        # Build combination signature with more granular buckets
        ofi = trade.get('ofi', 0)
        ensemble = trade.get('ensemble', 0)
        regime = trade.get('regime', 'unknown')
        
        # More granular OFI buckets
        if ofi >= 0.7:
            ofi_bucket = 'very_high'
        elif ofi >= 0.5:
            ofi_bucket = 'high'
        elif ofi >= 0.3:
            ofi_bucket = 'medium'
        elif ofi > 0:
            ofi_bucket = 'low'
        else:
            ofi_bucket = 'zero'
        
        # More granular ensemble buckets
        if ensemble >= 0.5:
            ensemble_bucket = 'very_high'
        elif ensemble >= 0.3:
            ensemble_bucket = 'high'
        elif ensemble >= 0.1:
            ensemble_bucket = 'medium'
        elif ensemble > 0:
            ensemble_bucket = 'low'
        else:
            ensemble_bucket = 'zero'
        
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
            winner_pnl = mean([t.get('pnl', 0) for t in winners]) if winners else 0
            loser_pnl = mean([t.get('pnl', 0) for t in losers]) if losers else 0
            avg_pnl = mean([t.get('pnl', 0) for t in winners + losers])
            
            combo_analysis[combo_key] = {
                'win_rate': win_rate,
                'avg_pnl': avg_pnl,
                'winner_avg_pnl': winner_pnl,
                'loser_avg_pnl': loser_pnl,
                'total_trades': total,
                'winners': len(winners),
                'losers': len(losers),
                'importance': 'HIGH' if win_rate > 0.60 or win_rate < 0.40 else 'MEDIUM',
            }
    
    return combo_analysis


def analyze_strategy_intelligence(strategy_name: str, trades: List[Dict]) -> Dict[str, Any]:
    """Analyze why a specific strategy works/doesn't work - DEEP CAUSAL ANALYSIS."""
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
        'why_winning': [],  # NEW: Explain WHY winners win
        'why_losing': [],   # NEW: Explain WHY losers lose
    }
    
    # DEEP CAUSAL ANALYSIS: Compare winners vs losers across ALL dimensions
    for component in INTELLIGENCE_COMPONENTS:
        winner_values = [t.get(component) for t in winners if t.get(component) is not None]
        loser_values = [t.get(component) for t in losers if t.get(component) is not None]
        
        # Filter out zeros for components that should be meaningful
        if component in ['funding', 'liquidation', 'whale_flow', 'fear_greed', 'hurst', 
                         'lead_lag', 'volatility_skew', 'oi_velocity', 'oi_divergence']:
            winner_values = [v for v in winner_values if v != 0]
            loser_values = [v for v in loser_values if v != 0]
        
        if winner_values and loser_values and len(winner_values) >= 5 and len(loser_values) >= 5:
            winner_mean = mean(winner_values)
            loser_mean = mean(loser_values)
            winner_median = median(winner_values)
            loser_median = median(loser_values)
            
            # Calculate difference and significance
            diff_pct = ((winner_mean - loser_mean) / abs(loser_mean) * 100) if loser_mean != 0 else 0
            
            # If winners have significantly higher values (20%+ difference)
            if winner_mean > loser_mean * 1.20:
                threshold = min(winner_values)
                analysis['winning_conditions'][component] = {
                    'winner_avg': winner_mean,
                    'winner_median': winner_median,
                    'loser_avg': loser_mean,
                    'loser_median': loser_median,
                    'threshold': threshold,
                    'difference_pct': diff_pct,
                }
                analysis['why_winning'].append(
                    f"Winners have {diff_pct:.1f}% higher {component} ({winner_mean:.3f} vs {loser_mean:.3f})"
                )
                analysis['causal_factors'].append(f"{component} >= {threshold:.3f}")
                analysis['recommendations'].append(
                    f"✅ USE {strategy_name} when {component} >= {threshold:.3f} (winners avg {winner_mean:.3f})"
                )
            # If losers have significantly higher values (20%+ difference)
            elif loser_mean > winner_mean * 1.20:
                threshold = max(loser_values)
                analysis['losing_conditions'][component] = {
                    'winner_avg': winner_mean,
                    'winner_median': winner_median,
                    'loser_avg': loser_mean,
                    'loser_median': loser_median,
                    'threshold': threshold,
                    'difference_pct': abs(diff_pct),
                }
                analysis['why_losing'].append(
                    f"Losers have {abs(diff_pct):.1f}% higher {component} ({loser_mean:.3f} vs {winner_mean:.3f})"
                )
                analysis['causal_factors'].append(f"{component} < {threshold:.3f}")
                analysis['recommendations'].append(
                    f"❌ AVOID {strategy_name} when {component} >= {threshold:.3f} (losers avg {loser_mean:.3f})"
                )
    
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
    
    # Load trades - use enriched_decisions.jsonl as primary source (has complete intelligence data)
    # Per Memory Bank and other analysis tools, this is the canonical source
    print("Loading trades...")
    try:
        # Try enriched_decisions.jsonl first (has complete signal_ctx with OFI, ensemble, etc.)
        enriched_path = PathRegistry.get_path("logs", "enriched_decisions.jsonl")
        trades = []
        
        if os.path.exists(enriched_path):
            print(f"   📊 Loading from enriched_decisions.jsonl (complete intelligence data)...")
            with open(enriched_path, 'r') as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        record = json.loads(line)
                        # Only include executed trades (not blocked)
                        if record.get('outcome', {}).get('executed', True) is not False:
                            trades.append(record)
                    except:
                        continue
            print(f"   ✅ Loaded {len(trades)} enriched records")
        
        # If enriched_decisions is empty or doesn't exist, try to populate it first
        if not trades:
            print(f"   ⚠️  enriched_decisions.jsonl is empty or not found")
            print(f"   💡 Attempting to populate enriched_decisions.jsonl from signals and trades...")
            try:
                from src.data_enrichment_layer import enrich_recent_decisions, persist_enriched_data
                # Enrich last 7 days of data
                enriched = enrich_recent_decisions(168)  # 7 days
                if enriched:
                    persist_enriched_data(enriched)
                    print(f"   ✅ Populated enriched_decisions.jsonl with {len(enriched)} records")
                    # Reload from enriched_decisions
                    with open(enriched_path, 'r') as f:
                        for line in f:
                            line = line.strip()
                            if not line:
                                continue
                            try:
                                record = json.loads(line)
                                if record.get('outcome', {}).get('executed', True) is not False:
                                    trades.append(record)
                            except:
                                continue
                else:
                    print(f"   ⚠️  No enriched data generated, falling back to positions_futures.json...")
            except Exception as e:
                print(f"   ⚠️  Could not populate enriched_decisions: {e}")
                print(f"   💡 Falling back to positions_futures.json...")
        
        # Fallback to positions_futures.json if still no trades
        if not trades:
            portfolio_path = PathRegistry.get_path("logs", "positions_futures.json")
            if os.path.exists(portfolio_path):
                with open(portfolio_path, 'r') as f:
                    portfolio = json.load(f)
                
                closed = portfolio.get('closed_positions', [])
                closed = [t for t in closed if t.get('bot_type', 'alpha') == 'alpha']
                trades = closed
                print(f"   ✅ Loaded {len(trades)} trades from positions_futures.json")
                print(f"   ⚠️  NOTE: positions_futures.json may not have complete intelligence data")
                print(f"   💡 For complete analysis, run: python3 -c 'from src.data_enrichment_layer import enrich_recent_decisions, persist_enriched_data; persist_enriched_data(enrich_recent_decisions(168))'")
            else:
                print(f"   ❌ positions_futures.json also not found!")
                return 1
        
        # Exclude bad trades window (Dec 18, 2025 1:00-6:00 AM UTC)
        bad_start = datetime(2025, 12, 18, 1, 0, 0, tzinfo=timezone.utc).timestamp()
        bad_end = datetime(2025, 12, 18, 6, 0, 0, tzinfo=timezone.utc).timestamp()
        
        filtered = []
        for trade in trades:
            # Get timestamp from various possible fields
            ts = None
            for field in ['closed_at', 'exit_ts', 'ts', 'timestamp']:
                if field in trade:
                    ts_val = trade[field]
                    if ts_val:
                        try:
                            if isinstance(ts_val, str):
                                ts = datetime.fromisoformat(ts_val.replace('Z', '+00:00')).timestamp()
                            else:
                                ts = float(ts_val)
                            break
                        except:
                            continue
            
            if ts and bad_start <= ts <= bad_end:
                continue
            filtered.append(trade)
        
        # Take last 500 for comprehensive analysis
        if filtered:
            # Sort by timestamp (most recent first)
            filtered.sort(key=lambda t: (
                datetime.fromisoformat(t.get('closed_at', t.get('exit_ts', t.get('ts', '2000-01-01'))).replace('Z', '+00:00')).timestamp()
                if isinstance(t.get('closed_at', t.get('exit_ts', t.get('ts', ''))), str) else 
                float(t.get('exit_ts', t.get('ts', 0)) or 0)
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
    
    # Diagnostic: Check what fields are available in trades
    if trades:
        sample_trade = trades[0]
        available_fields = set(sample_trade.keys())
        intelligence_fields = {'ofi_score', 'ensemble_score', 'mtf_confidence', 'regime', 
                             'signal_components', 'ml_features', 'signal_ctx', 'volatility'}
        found_fields = available_fields.intersection(intelligence_fields)
        print(f"   📊 Sample trade fields: {len(available_fields)} total")
        print(f"   ✅ Intelligence fields found: {', '.join(sorted(found_fields))}")
        if 'signal_components' in sample_trade and sample_trade['signal_components']:
            print(f"   ✅ signal_components keys: {', '.join(sample_trade['signal_components'].keys())}")
        print()
    
    intelligence_data = []
    for trade in trades:
        intel = extract_all_intelligence(trade)
        intelligence_data.append(intel)
    
    # Diagnostic: Check extraction results
    if not intelligence_data:
        print(f"   ⚠️  No trades loaded - cannot perform analysis")
        print(f"   💡 Try running data enrichment first:")
        print(f"      python3 -c 'from src.data_enrichment_layer import enrich_recent_decisions; enrich_recent_decisions(168)'")
        return 1
    
    trades_with_ofi = sum(1 for t in intelligence_data if t.get('ofi', 0) > 0)
    trades_with_ensemble = sum(1 for t in intelligence_data if t.get('ensemble', 0) > 0)
    trades_with_regime = sum(1 for t in intelligence_data if t.get('regime', 'unknown') != 'unknown')
    trades_with_components = sum(1 for t in intelligence_data if t.get('signal_components') or any(t.get(c, 0) != 0 for c in ['funding', 'liquidation', 'whale_flow']))
    
    total = len(intelligence_data)
    print(f"   ✅ Extracted intelligence from {total} trades")
    print(f"   📊 Extraction stats:")
    print(f"      - Trades with OFI data: {trades_with_ofi} ({trades_with_ofi/total*100:.1f}%)")
    print(f"      - Trades with Ensemble data: {trades_with_ensemble} ({trades_with_ensemble/total*100:.1f}%)")
    print(f"      - Trades with Regime data: {trades_with_regime} ({trades_with_regime/total*100:.1f}%)")
    print(f"      - Trades with signal components: {trades_with_components} ({trades_with_components/total*100:.1f}%)")
    print()
    
    # Analyze each signal component - DEEP CAUSAL ANALYSIS
    print("="*80)
    print("ANALYZING INDIVIDUAL SIGNAL COMPONENTS")
    print("="*80)
    print("   Understanding WHY each signal works/doesn't work")
    print("   Comparing winners vs losers to find causal factors")
    print()
    
    signal_analyses = {}
    for component in INTELLIGENCE_COMPONENTS:
        analysis = analyze_signal_component(component, intelligence_data)
        if analysis and analysis.get('importance') in ['HIGH', 'MEDIUM']:
            signal_analyses[component] = analysis
    
    # Display signal component findings with WHY
    if signal_analyses:
        for component, analysis in sorted(signal_analyses.items(), 
                                          key=lambda x: {'HIGH': 3, 'MEDIUM': 2, 'LOW': 1}.get(x[1].get('importance', 'LOW'), 0),
                                          reverse=True):
            importance = analysis.get('importance', 'MEDIUM')
            insight = analysis.get('causal_insight', '')
            recommendation = analysis.get('recommendation', '')
            winners_stats = analysis.get('winners', {})
            losers_stats = analysis.get('losers', {})
            
            icon = '🔴' if importance == 'HIGH' else '🟡'
            print(f"{icon} {component.upper()}")
            if insight:
                print(f"   {insight}")
            if winners_stats and losers_stats:
                winner_mean = winners_stats.get('mean', 0)
                loser_mean = losers_stats.get('mean', 0)
                print(f"   📊 Winners avg: {winner_mean:.3f} | Losers avg: {loser_mean:.3f}")
            if recommendation:
                print(f"   → {recommendation}")
            print()
    else:
        print("   ⚠️  No signal components with sufficient data for analysis")
        print("   💡 This means detailed signal components (funding, liquidation, etc.)")
        print("      are not available in the enriched_decisions data")
        print("   💡 Consider enhancing data_enrichment_layer.py to include these components")
        print()
    
    # Analyze signal combinations - WITH WHY
    print("="*80)
    print("ANALYZING SIGNAL COMBINATIONS")
    print("="*80)
    print("   Understanding which combinations work best and WHY")
    print()
    
    combo_analysis = analyze_signal_combinations(intelligence_data)
    
    # Deep dive into top/bottom combinations to understand WHY
    sorted_combos = sorted(combo_analysis.items(), 
                          key=lambda x: x[1].get('win_rate', 0.5), 
                          reverse=True)
    
    # Show top 3 winning combinations
    winning_combos = [c for c in sorted_combos if c[1].get('win_rate', 0) > 0.50][:3]
    if winning_combos:
        print("   ✅ TOP WINNING COMBINATIONS (WHY they work):")
        for combo, data in winning_combos:
            win_rate = data.get('win_rate', 0)
            total = data.get('total_trades', 0)
            avg_pnl = data.get('avg_pnl', 0)
            print(f"   🟢 {combo}")
            print(f"      Win Rate: {win_rate:.1%}, Trades: {total}, Avg P&L: ${avg_pnl:.2f}")
            # Extract conditions from combo string
            conditions = combo.split('|')
            print(f"      → Trade when: {' AND '.join(conditions)}")
            print()
    
    # Show bottom 3 losing combinations
    losing_combos = [c for c in sorted_combos if c[1].get('win_rate', 0) < 0.50][:3]
    if losing_combos:
        print("   ❌ TOP LOSING COMBINATIONS (WHY they fail):")
        for combo, data in losing_combos:
            win_rate = data.get('win_rate', 0)
            total = data.get('total_trades', 0)
            avg_pnl = data.get('avg_pnl', 0)
            print(f"   🔴 {combo}")
            print(f"      Win Rate: {win_rate:.1%}, Trades: {total}, Avg P&L: ${avg_pnl:.2f}")
            conditions = combo.split('|')
            print(f"      → AVOID when: {' AND '.join(conditions)}")
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
        avg_pnl = analysis.get('avg_pnl', 0)
        icon = '🟢' if win_rate > 0.60 else '🟡' if win_rate > 0.50 else '🔴'
        print(f"{icon} {strategy.upper()}")
        print(f"   Win Rate: {win_rate:.1%}, Trades: {total}, Avg P&L: ${avg_pnl:.2f}")
        
        # WHY WINNING - What conditions lead to wins?
        why_winning = analysis.get('why_winning', [])
        if why_winning:
            print(f"   ✅ WHY WINNING:")
            for reason in why_winning[:3]:  # Top 3 reasons
                print(f"      • {reason}")
        
        # WHY LOSING - What conditions lead to losses?
        why_losing = analysis.get('why_losing', [])
        if why_losing:
            print(f"   ❌ WHY LOSING:")
            for reason in why_losing[:3]:  # Top 3 reasons
                print(f"      • {reason}")
        
        # ACTIONABLE RECOMMENDATIONS
        recommendations = analysis.get('recommendations', [])
        if recommendations:
            print(f"   🎯 ACTIONABLE RULES:")
            for rec in recommendations[:3]:  # Top 3 recommendations
                print(f"      {rec}")
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
            signal_strs = [f"{k}={v.get('mean', 0):.3f}" for k, v in top_signals]
            print(f"   Top Signals: {', '.join(signal_strs)}")
        print()
    
    # Generate improvement plan - FOCUSED ON WHY
    print("="*80)
    print("ACTIONABLE TRADING RULES - Based on WHY We Win/Lose")
    print("="*80)
    print("   Rules to enter trades based on understanding, not correlation")
    print()
    
    all_analyses = {
        'signal_components': signal_analyses,
        'strategies': strategy_analyses,
        'combinations': combo_analysis,
        'regimes': regime_analysis,
    }
    
    improvements = generate_improvement_plan(all_analyses)
    
    # Group improvements by type and show WHY
    entry_rules = []
    avoid_rules = []
    
    for imp in improvements:
        action = imp.get('action', '').lower()
        if 'avoid' in action or 'don\'t' in action or 'skip' in action:
            avoid_rules.append(imp)
        else:
            entry_rules.append(imp)
    
    if entry_rules:
        print("   ✅ ENTER TRADES WHEN:")
        for imp in sorted(entry_rules, 
                         key=lambda x: {'HIGH': 3, 'MEDIUM': 2, 'LOW': 1}.get(x.get('priority', 'LOW'), 0),
                         reverse=True)[:10]:
            priority = imp.get('priority', 'MEDIUM')
            icon = '🔴' if priority == 'HIGH' else '🟡'
            print(f"   {icon} {imp['action']}")
            print(f"      WHY: {imp['reasoning']}")
            print()
    
    if avoid_rules:
        print("   ❌ AVOID TRADES WHEN:")
        for imp in sorted(avoid_rules, 
                         key=lambda x: {'HIGH': 3, 'MEDIUM': 2, 'LOW': 1}.get(x.get('priority', 'LOW'), 0),
                         reverse=True)[:10]:
            priority = imp.get('priority', 'MEDIUM')
            icon = '🔴' if priority == 'HIGH' else '🟡'
            print(f"   {icon} {imp['action']}")
            print(f"      WHY: {imp['reasoning']}")
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
