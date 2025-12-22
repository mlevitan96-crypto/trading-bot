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
import math
from scipy import stats
try:
    from scipy.stats import chi2_contingency, mannwhitneyu
    HAS_SCIPY = True
except ImportError:
    HAS_SCIPY = False

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
    entry_time = trade.get('opened_at', trade.get('entry_timestamp', trade.get('timestamp', trade.get('ts', ''))))
    if entry_time:
        try:
            if isinstance(entry_time, str):
                dt = datetime.fromisoformat(entry_time.replace('Z', '+00:00'))
            elif isinstance(entry_time, (int, float)):
                # Handle both seconds and milliseconds
                ts_val = float(entry_time)
                if ts_val > 1e12:
                    dt = datetime.fromtimestamp(ts_val / 1000, tz=timezone.utc)
                else:
                    dt = datetime.fromtimestamp(ts_val, tz=timezone.utc)
            else:
                dt = datetime.fromtimestamp(entry_time, tz=timezone.utc)
            intelligence['hour'] = dt.hour
            intelligence['session'] = get_session(dt)
        except:
            intelligence['hour'] = 12
            intelligence['session'] = 'unknown'
    else:
        intelligence['hour'] = 12
        intelligence['session'] = 'unknown'
    
    # Extract entry/exit prices and timestamps for duration analysis
    outcome = trade.get('outcome', {})
    intelligence['entry_price'] = outcome.get('entry_price', trade.get('entry_price', 0))
    intelligence['exit_price'] = outcome.get('exit_price', trade.get('exit_price', 0))
    intelligence['entry_ts'] = trade.get('entry_ts', trade.get('ts', 0))
    intelligence['exit_ts'] = trade.get('exit_ts', trade.get('closed_at', 0))
    
    # Extract fees
    intelligence['fees'] = outcome.get('fees', outcome.get('trading_fees', trade.get('fees', 0)))
    
    # Extract volatility and volume from signal_ctx or trade directly
    signal_ctx = trade.get('signal_ctx', {})
    intelligence['volatility'] = signal_ctx.get('volatility', trade.get('volatility', 0))
    intelligence['volume'] = signal_ctx.get('volume', trade.get('volume', trade.get('volume_24h', 0)))
    
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


def analyze_winning_patterns(trades: List[Dict]) -> Dict[str, Any]:
    """DEEP ANALYSIS: What makes winners different from losers across ALL dimensions."""
    winners = [t for t in trades if t.get('win', False)]
    losers = [t for t in trades if not t.get('win', False)]
    
    if not winners or not losers:
        return {}
    
    patterns = {
        'winning_signatures': [],
        'losing_signatures': [],
        'key_differences': {},
        'winner_profile': {},
        'loser_profile': {},
    }
    
    # Build profiles: What do winners typically have?
    winner_ofi_values = [t.get('ofi', 0) for t in winners if t.get('ofi', 0) > 0]
    loser_ofi_values = [t.get('ofi', 0) for t in losers if t.get('ofi', 0) > 0]
    
    if winner_ofi_values and loser_ofi_values:
        patterns['key_differences']['ofi'] = {
            'winner_avg': mean(winner_ofi_values),
            'winner_median': median(winner_ofi_values),
            'winner_min': min(winner_ofi_values),
            'loser_avg': mean(loser_ofi_values),
            'loser_median': median(loser_ofi_values),
            'loser_max': max(loser_ofi_values),
            'difference_pct': ((mean(winner_ofi_values) - mean(loser_ofi_values)) / mean(loser_ofi_values) * 100) if mean(loser_ofi_values) > 0 else 0,
            'is_winning_factor': mean(winner_ofi_values) > mean(loser_ofi_values),
        }
    
    winner_ens_values = [t.get('ensemble', 0) for t in winners if t.get('ensemble', 0) > 0]
    loser_ens_values = [t.get('ensemble', 0) for t in losers if t.get('ensemble', 0) > 0]
    
    if winner_ens_values and loser_ens_values:
        patterns['key_differences']['ensemble'] = {
            'winner_avg': mean(winner_ens_values),
            'winner_median': median(winner_ens_values),
            'winner_min': min(winner_ens_values),
            'loser_avg': mean(loser_ens_values),
            'loser_median': median(loser_ens_values),
            'loser_max': max(loser_ens_values),
            'difference_pct': ((mean(winner_ens_values) - mean(loser_ens_values)) / mean(loser_ens_values) * 100) if mean(loser_ens_values) > 0 else 0,
            'is_winning_factor': mean(winner_ens_values) > mean(loser_ens_values),
        }
    
    # Compare winners vs losers across ALL intelligence components
    for component in INTELLIGENCE_COMPONENTS:
        winner_values = [t.get(component) for t in winners if t.get(component) is not None]
        loser_values = [t.get(component) for t in losers if t.get(component) is not None]
        
        # Filter zeros for meaningful components
        if component in ['funding', 'liquidation', 'whale_flow', 'fear_greed', 'hurst', 
                         'lead_lag', 'volatility_skew', 'oi_velocity', 'oi_divergence']:
            winner_values = [v for v in winner_values if v != 0]
            loser_values = [v for v in loser_values if v != 0]
        
        if winner_values and loser_values and len(winner_values) >= 10 and len(loser_values) >= 10:
            winner_mean = mean(winner_values)
            loser_mean = mean(loser_values)
            diff_pct = ((winner_mean - loser_mean) / abs(loser_mean) * 100) if loser_mean != 0 else 0
            
            if abs(diff_pct) > 15:  # Significant difference
                patterns['key_differences'][component] = {
                    'winner_avg': winner_mean,
                    'loser_avg': loser_mean,
                    'difference_pct': diff_pct,
                    'is_winning_factor': diff_pct > 0,
                }
    
    # Build winning signatures (combinations that lead to wins)
    winner_combos = defaultdict(int)
    for winner in winners:
        ofi = winner.get('ofi', 0)
        ensemble = winner.get('ensemble', 0)
        regime = winner.get('regime', 'unknown')
        direction = winner.get('direction', 'UNKNOWN')
        symbol = winner.get('symbol', 'UNKNOWN')
        
        ofi_bucket = 'high' if ofi >= 0.6 else 'medium' if ofi >= 0.3 else 'low' if ofi > 0 else 'zero'
        ensemble_bucket = 'high' if ensemble >= 0.4 else 'medium' if ensemble >= 0.2 else 'low' if ensemble > 0 else 'zero'
        
        sig = f"{symbol}|{direction}|{ofi_bucket}_ofi|{ensemble_bucket}_ens|{regime}"
        winner_combos[sig] += 1
    
    # Build losing signatures
    loser_combos = defaultdict(int)
    for loser in losers:
        ofi = loser.get('ofi', 0)
        ensemble = loser.get('ensemble', 0)
        regime = loser.get('regime', 'unknown')
        direction = loser.get('direction', 'UNKNOWN')
        symbol = loser.get('symbol', 'UNKNOWN')
        
        ofi_bucket = 'high' if ofi >= 0.6 else 'medium' if ofi >= 0.3 else 'low' if ofi > 0 else 'zero'
        ensemble_bucket = 'high' if ensemble >= 0.4 else 'medium' if ensemble >= 0.2 else 'low' if ensemble > 0 else 'zero'
        
        sig = f"{symbol}|{direction}|{ofi_bucket}_ofi|{ensemble_bucket}_ens|{regime}"
        loser_combos[sig] += 1
    
    # Find signatures that appear in winners but NOT in losers (pure winning patterns)
    for sig, count in winner_combos.items():
        if sig not in loser_combos and count >= 3:  # Lower threshold to find more patterns
            patterns['winning_signatures'].append({
                'signature': sig,
                'count': count,
                'win_rate': 1.0,  # Only appears in winners
            })
    
    # Find signatures that appear in losers but NOT in winners (pure losing patterns)
    for sig, count in loser_combos.items():
        if sig not in winner_combos and count >= 3:  # Lower threshold
            patterns['losing_signatures'].append({
                'signature': sig,
                'count': count,
                'win_rate': 0.0,  # Only appears in losers
            })
    
    return patterns


def analyze_symbol_intelligence(trades: List[Dict]) -> Dict[str, Any]:
    """Analyze WHY certain symbols win/lose - symbol-specific patterns."""
    symbol_data = defaultdict(lambda: {'winners': [], 'losers': []})
    
    for trade in trades:
        symbol = trade.get('symbol', 'UNKNOWN')
        if symbol != 'UNKNOWN':
            if trade.get('win', False):
                symbol_data[symbol]['winners'].append(trade)
            else:
                symbol_data[symbol]['losers'].append(trade)
    
    symbol_analysis = {}
    for symbol, data in symbol_data.items():
        winners = data['winners']
        losers = data['losers']
        total = len(winners) + len(losers)
        
        if total >= 20:  # Minimum sample per symbol
            win_rate = len(winners) / total if total > 0 else 0
            avg_pnl = mean([t.get('pnl', 0) for t in winners + losers])
            
            # What makes winners different from losers FOR THIS SYMBOL?
            key_differences = {}
            
            # OFI analysis for this symbol
            winner_ofi = [t.get('ofi', 0) for t in winners if t.get('ofi', 0) > 0]
            loser_ofi = [t.get('ofi', 0) for t in losers if t.get('ofi', 0) > 0]
            
            if winner_ofi and loser_ofi:
                winner_ofi_mean = mean(winner_ofi)
                loser_ofi_mean = mean(loser_ofi)
                diff_pct = ((winner_ofi_mean - loser_ofi_mean) / loser_ofi_mean * 100) if loser_ofi_mean > 0 else 0
                if abs(diff_pct) > 10:
                    key_differences['ofi'] = {
                        'winner_avg': winner_ofi_mean,
                        'loser_avg': loser_ofi_mean,
                        'difference_pct': diff_pct,
                        'threshold': min(winner_ofi) if diff_pct > 0 else max(loser_ofi),
                    }
            
            # Ensemble analysis for this symbol
            winner_ens = [t.get('ensemble', 0) for t in winners if t.get('ensemble', 0) > 0]
            loser_ens = [t.get('ensemble', 0) for t in losers if t.get('ensemble', 0) > 0]
            
            if winner_ens and loser_ens:
                winner_ens_mean = mean(winner_ens)
                loser_ens_mean = mean(loser_ens)
                diff_pct = ((winner_ens_mean - loser_ens_mean) / loser_ens_mean * 100) if loser_ens_mean > 0 else 0
                if abs(diff_pct) > 10:
                    key_differences['ensemble'] = {
                        'winner_avg': winner_ens_mean,
                        'loser_avg': loser_ens_mean,
                        'difference_pct': diff_pct,
                        'threshold': min(winner_ens) if diff_pct > 0 else max(loser_ens),
                    }
            
            # Direction analysis for this symbol
            winner_directions = [t.get('direction', 'UNKNOWN') for t in winners]
            loser_directions = [t.get('direction', 'UNKNOWN') for t in losers]
            
            winner_long_pct = winner_directions.count('LONG') / len(winner_directions) if winner_directions else 0
            loser_long_pct = loser_directions.count('LONG') / len(loser_directions) if loser_directions else 0
            
            if abs(winner_long_pct - loser_long_pct) > 0.15:  # 15% difference
                key_differences['direction'] = {
                    'winner_long_pct': winner_long_pct,
                    'loser_long_pct': loser_long_pct,
                    'preferred_direction': 'LONG' if winner_long_pct > loser_long_pct else 'SHORT',
                }
            
            symbol_analysis[symbol] = {
                'win_rate': win_rate,
                'avg_pnl': avg_pnl,
                'total_trades': total,
                'winners': len(winners),
                'losers': len(losers),
                'key_differences': key_differences,
                'importance': 'HIGH' if win_rate > 0.55 or win_rate < 0.45 else 'MEDIUM',
            }
    
    return symbol_analysis


def analyze_multi_dimensional_patterns(trades: List[Dict]) -> List[Dict]:
    """Discover complex multi-dimensional patterns that predict wins/losses."""
    patterns = []
    
    # Group by multiple dimensions
    pattern_groups = defaultdict(lambda: {'winners': [], 'losers': []})
    
    for trade in trades:
        ofi = trade.get('ofi', 0)
        ensemble = trade.get('ensemble', 0)
        regime = trade.get('regime', 'unknown')
        direction = trade.get('direction', 'UNKNOWN')
        symbol = trade.get('symbol', 'UNKNOWN')
        strategy = trade.get('strategy', 'UNKNOWN')
        
        # Create multi-dimensional key
        ofi_tier = 'high' if ofi >= 0.6 else 'medium' if ofi >= 0.3 else 'low'
        ens_tier = 'high' if ensemble >= 0.3 else 'medium' if ensemble >= 0.1 else 'low'
        
        # Try different combinations
        key1 = f"{symbol}|{direction}|{ofi_tier}_ofi|{ens_tier}_ens"
        key2 = f"{strategy}|{direction}|{regime}"
        key3 = f"{symbol}|{strategy}|{ofi_tier}_ofi"
        
        for key in [key1, key2, key3]:
            if trade.get('win', False):
                pattern_groups[key]['winners'].append(trade)
            else:
                pattern_groups[key]['losers'].append(trade)
    
    # Analyze each pattern
    for pattern_key, data in pattern_groups.items():
        winners = data['winners']
        losers = data['losers']
        total = len(winners) + len(losers)
        
        if total >= 15:  # Minimum sample
            win_rate = len(winners) / total if total > 0 else 0
            avg_pnl = mean([t.get('pnl', 0) for t in winners + losers])
            
            # Only include significant patterns
            if win_rate > 0.55 or win_rate < 0.45:  # Clear winner or loser
                patterns.append({
                    'pattern': pattern_key,
                    'win_rate': win_rate,
                    'avg_pnl': avg_pnl,
                    'total_trades': total,
                    'winners': len(winners),
                    'losers': len(losers),
                    'importance': 'HIGH' if abs(win_rate - 0.5) > 0.15 else 'MEDIUM',
                })
    
    return sorted(patterns, key=lambda x: abs(x['win_rate'] - 0.5), reverse=True)


def analyze_temporal_patterns(trades: List[Dict]) -> Dict[str, Any]:
    """Analyze temporal patterns: hour of day, day of week, trading session."""
    temporal_data = {
        'by_hour': defaultdict(lambda: {'winners': [], 'losers': []}),
        'by_session': defaultdict(lambda: {'winners': [], 'losers': []}),
        'by_day_of_week': defaultdict(lambda: {'winners': [], 'losers': []}),
    }
    
    for trade in trades:
        hour = trade.get('hour', 12)
        session = trade.get('session', 'unknown')
        
        # Get day of week from timestamp
        ts = trade.get('ts', trade.get('entry_ts', 0))
        if ts:
            try:
                if isinstance(ts, str):
                    dt = datetime.fromisoformat(ts.replace('Z', '+00:00'))
                else:
                    dt = datetime.fromtimestamp(ts if ts < 1e12 else ts / 1000)
                day_of_week = dt.strftime('%A')
            except:
                day_of_week = 'Unknown'
        else:
            day_of_week = 'Unknown'
        
        if trade.get('win', False):
            temporal_data['by_hour'][hour]['winners'].append(trade)
            temporal_data['by_session'][session]['winners'].append(trade)
            temporal_data['by_day_of_week'][day_of_week]['winners'].append(trade)
        else:
            temporal_data['by_hour'][hour]['losers'].append(trade)
            temporal_data['by_session'][session]['losers'].append(trade)
            temporal_data['by_day_of_week'][day_of_week]['losers'].append(trade)
    
    analysis = {
        'best_hours': [],
        'worst_hours': [],
        'best_sessions': [],
        'worst_sessions': [],
        'best_days': [],
        'worst_days': [],
    }
    
    # Analyze hours
    for hour in range(24):
        data = temporal_data['by_hour'][hour]
        total = len(data['winners']) + len(data['losers'])
        if total >= 10:
            win_rate = len(data['winners']) / total if total > 0 else 0
            avg_pnl = mean([t.get('pnl', 0) for t in data['winners'] + data['losers']])
            analysis['best_hours'].append({
                'hour': hour,
                'win_rate': win_rate,
                'avg_pnl': avg_pnl,
                'total': total,
            })
            analysis['worst_hours'].append({
                'hour': hour,
                'win_rate': win_rate,
                'avg_pnl': avg_pnl,
                'total': total,
            })
    
    analysis['best_hours'] = sorted([h for h in analysis['best_hours'] if h['win_rate'] > 0.5],
                                   key=lambda x: x['win_rate'], reverse=True)[:5]
    analysis['worst_hours'] = sorted([h for h in analysis['worst_hours'] if h['win_rate'] < 0.5],
                                     key=lambda x: x['win_rate'])[:5]
    
    # Analyze sessions
    for session, data in temporal_data['by_session'].items():
        total = len(data['winners']) + len(data['losers'])
        if total >= 15:
            win_rate = len(data['winners']) / total if total > 0 else 0
            avg_pnl = mean([t.get('pnl', 0) for t in data['winners'] + data['losers']])
            if win_rate > 0.5:
                analysis['best_sessions'].append({
                    'session': session,
                    'win_rate': win_rate,
                    'avg_pnl': avg_pnl,
                    'total': total,
                })
            else:
                analysis['worst_sessions'].append({
                    'session': session,
                    'win_rate': win_rate,
                    'avg_pnl': avg_pnl,
                    'total': total,
                })
    
    analysis['best_sessions'] = sorted(analysis['best_sessions'],
                                       key=lambda x: x['win_rate'], reverse=True)
    analysis['worst_sessions'] = sorted(analysis['worst_sessions'],
                                       key=lambda x: x['win_rate'])
    
    # Analyze days of week
    for day, data in temporal_data['by_day_of_week'].items():
        total = len(data['winners']) + len(data['losers'])
        if total >= 20:
            win_rate = len(data['winners']) / total if total > 0 else 0
            avg_pnl = mean([t.get('pnl', 0) for t in data['winners'] + data['losers']])
            if win_rate > 0.5:
                analysis['best_days'].append({
                    'day': day,
                    'win_rate': win_rate,
                    'avg_pnl': avg_pnl,
                    'total': total,
                })
            else:
                analysis['worst_days'].append({
                    'day': day,
                    'win_rate': win_rate,
                    'avg_pnl': avg_pnl,
                    'total': total,
                })
    
    analysis['best_days'] = sorted(analysis['best_days'],
                                  key=lambda x: x['win_rate'], reverse=True)
    analysis['worst_days'] = sorted(analysis['worst_days'],
                                   key=lambda x: x['win_rate'])
    
    return analysis


def analyze_trade_duration(trades: List[Dict]) -> Dict[str, Any]:
    """Analyze trade duration: how long winners hold vs losers."""
    winners = [t for t in trades if t.get('win', False)]
    losers = [t for t in trades if not t.get('win', False)]
    
    winner_durations = []
    loser_durations = []
    
    for trade in winners:
        entry_ts = trade.get('entry_ts', trade.get('ts', 0))
        exit_ts = trade.get('exit_ts', 0)
        
        if entry_ts and exit_ts:
            try:
                if isinstance(entry_ts, str):
                    entry_dt = datetime.fromisoformat(entry_ts.replace('Z', '+00:00'))
                    entry_ts = entry_dt.timestamp()
                elif entry_ts > 1e12:
                    entry_ts = entry_ts / 1000
                
                if isinstance(exit_ts, str):
                    exit_dt = datetime.fromisoformat(exit_ts.replace('Z', '+00:00'))
                    exit_ts = exit_dt.timestamp()
                elif exit_ts > 1e12:
                    exit_ts = exit_ts / 1000
                
                duration_hours = (exit_ts - entry_ts) / 3600
                if duration_hours > 0 and duration_hours < 720:  # Reasonable range (0-30 days)
                    winner_durations.append(duration_hours)
            except:
                pass
    
    for trade in losers:
        entry_ts = trade.get('entry_ts', trade.get('ts', 0))
        exit_ts = trade.get('exit_ts', 0)
        
        if entry_ts and exit_ts:
            try:
                if isinstance(entry_ts, str):
                    entry_dt = datetime.fromisoformat(entry_ts.replace('Z', '+00:00'))
                    entry_ts = entry_dt.timestamp()
                elif entry_ts > 1e12:
                    entry_ts = entry_ts / 1000
                
                if isinstance(exit_ts, str):
                    exit_dt = datetime.fromisoformat(exit_ts.replace('Z', '+00:00'))
                    exit_ts = exit_dt.timestamp()
                elif exit_ts > 1e12:
                    exit_ts = exit_ts / 1000
                
                duration_hours = (exit_ts - entry_ts) / 3600
                if duration_hours > 0 and duration_hours < 720:  # Reasonable range
                    loser_durations.append(duration_hours)
            except:
                pass
    
    analysis = {}
    
    if winner_durations and loser_durations:
        analysis = {
            'winners': {
                'mean_hours': mean(winner_durations),
                'median_hours': median(winner_durations),
                'min_hours': min(winner_durations),
                'max_hours': max(winner_durations),
                'count': len(winner_durations),
            },
            'losers': {
                'mean_hours': mean(loser_durations),
                'median_hours': median(loser_durations),
                'min_hours': min(loser_durations),
                'max_hours': max(loser_durations),
                'count': len(loser_durations),
            },
        }
        
        winner_mean = analysis['winners']['mean_hours']
        loser_mean = analysis['losers']['mean_hours']
        diff_pct = ((winner_mean - loser_mean) / loser_mean * 100) if loser_mean > 0 else 0
        
        analysis['difference_pct'] = diff_pct
        analysis['optimal_duration'] = analysis['winners']['median_hours'] if diff_pct > 0 else None
    
    return analysis


def analyze_entry_price_positioning(trades: List[Dict]) -> Dict[str, Any]:
    """Analyze entry price positioning relative to recent price action."""
    # Group trades by symbol to analyze price positioning
    symbol_trades = defaultdict(list)
    for trade in trades:
        symbol = trade.get('symbol', 'UNKNOWN')
        if symbol != 'UNKNOWN':
            symbol_trades[symbol].append(trade)
    
    analysis = {}
    
    for symbol, symbol_trade_list in symbol_trades.items():
        if len(symbol_trade_list) < 20:
            continue
        
        # Get entry prices
        entry_prices = []
        for trade in symbol_trade_list:
            entry_price = trade.get('entry_price', 0)
            if entry_price and entry_price > 0:
                entry_prices.append(entry_price)
        
        if len(entry_prices) < 10:
            continue
        
        # Calculate price percentiles
        entry_prices_sorted = sorted(entry_prices)
        p25 = entry_prices_sorted[len(entry_prices_sorted) // 4]
        p50 = entry_prices_sorted[len(entry_prices_sorted) // 2]
        p75 = entry_prices_sorted[3 * len(entry_prices_sorted) // 4]
        
        # Analyze winners vs losers by price position
        winners_low = []  # Entry price < p25
        winners_mid = []  # p25 <= Entry price < p75
        winners_high = []  # Entry price >= p75
        losers_low = []
        losers_mid = []
        losers_high = []
        
        for trade in symbol_trade_list:
            entry_price = trade.get('entry_price', 0)
            if not entry_price or entry_price <= 0:
                continue
            
            is_winner = trade.get('win', False)
            
            if entry_price < p25:
                if is_winner:
                    winners_low.append(trade)
                else:
                    losers_low.append(trade)
            elif entry_price < p75:
                if is_winner:
                    winners_mid.append(trade)
                else:
                    losers_mid.append(trade)
            else:
                if is_winner:
                    winners_high.append(trade)
                else:
                    losers_high.append(trade)
        
        # Calculate win rates by price position
        low_total = len(winners_low) + len(losers_low)
        mid_total = len(winners_mid) + len(losers_mid)
        high_total = len(winners_high) + len(losers_high)
        
        if low_total >= 5 and mid_total >= 5 and high_total >= 5:
            low_wr = len(winners_low) / low_total if low_total > 0 else 0
            mid_wr = len(winners_mid) / mid_total if mid_total > 0 else 0
            high_wr = len(winners_high) / high_total if high_total > 0 else 0
            
            analysis[symbol] = {
                'low_price_wr': low_wr,
                'mid_price_wr': mid_wr,
                'high_price_wr': high_wr,
                'best_position': 'low' if low_wr > max(mid_wr, high_wr) else 'mid' if mid_wr > high_wr else 'high',
                'p25_price': p25,
                'p50_price': p50,
                'p75_price': p75,
            }
    
    return analysis


def calculate_statistical_significance(trades: List[Dict], pattern_name: str, 
                                      pattern_trades: List[Dict], 
                                      all_trades: List[Dict]) -> Dict[str, Any]:
    """Calculate statistical significance of a pattern."""
    if not HAS_SCIPY or len(pattern_trades) < 10:
        return {'significant': False, 'p_value': 1.0, 'method': 'insufficient_data'}
    
    pattern_winners = len([t for t in pattern_trades if t.get('win', False)])
    pattern_total = len(pattern_trades)
    pattern_wr = pattern_winners / pattern_total if pattern_total > 0 else 0
    
    all_winners = len([t for t in all_trades if t.get('win', False)])
    all_total = len(all_trades)
    all_wr = all_winners / all_total if all_total > 0 else 0
    
    # Chi-square test for independence
    contingency = [
        [pattern_winners, pattern_total - pattern_winners],
        [all_winners - pattern_winners, (all_total - pattern_total) - (all_winners - pattern_winners)]
    ]
    
    try:
        chi2, p_value, dof, expected = chi2_contingency(contingency)
        significant = p_value < 0.05
        
        return {
            'significant': significant,
            'p_value': p_value,
            'chi2': chi2,
            'method': 'chi2',
            'pattern_wr': pattern_wr,
            'baseline_wr': all_wr,
        }
    except:
        return {'significant': False, 'p_value': 1.0, 'method': 'error'}


def calculate_risk_adjusted_metrics(trades: List[Dict]) -> Dict[str, Any]:
    """Calculate risk-adjusted performance metrics."""
    pnls = [t.get('pnl', 0) for t in trades if t.get('pnl') is not None]
    
    if not pnls or len(pnls) < 10:
        return {}
    
    mean_pnl = mean(pnls)
    std_pnl = stdev(pnls) if len(pnls) > 1 else 0
    
    # Sharpe ratio (annualized, assuming daily trades)
    sharpe = (mean_pnl / std_pnl * (365 ** 0.5)) if std_pnl > 0 else 0
    
    # Sortino ratio (only downside deviation)
    downside_pnls = [p for p in pnls if p < 0]
    downside_std = stdev(downside_pnls) if len(downside_pnls) > 1 else 0
    sortino = (mean_pnl / downside_std * (365 ** 0.5)) if downside_std > 0 else 0
    
    # Win rate
    winners = [p for p in pnls if p > 0]
    win_rate = len(winners) / len(pnls) if pnls else 0
    
    # Average win vs average loss
    avg_win = mean(winners) if winners else 0
    losses = [p for p in pnls if p < 0]
    avg_loss = mean(losses) if losses else 0
    win_loss_ratio = abs(avg_win / avg_loss) if avg_loss != 0 else 0
    
    # Profit factor
    total_wins = sum(winners) if winners else 0
    total_losses = abs(sum(losses)) if losses else 0
    profit_factor = total_wins / total_losses if total_losses > 0 else 0
    
    return {
        'sharpe_ratio': sharpe,
        'sortino_ratio': sortino,
        'win_rate': win_rate,
        'avg_win': avg_win,
        'avg_loss': avg_loss,
        'win_loss_ratio': win_loss_ratio,
        'profit_factor': profit_factor,
        'total_trades': len(pnls),
        'mean_pnl': mean_pnl,
        'std_pnl': std_pnl,
    }


def analyze_sequence_patterns(trades: List[Dict]) -> Dict[str, Any]:
    """Analyze sequence patterns: streaks, what happens after wins/losses."""
    # Sort trades by timestamp
    sorted_trades = sorted(trades, key=lambda t: t.get('ts', t.get('entry_ts', 0)))
    
    analysis = {
        'win_streaks': [],
        'loss_streaks': [],
        'after_win': {'next_win_rate': 0, 'next_avg_pnl': 0, 'count': 0},
        'after_loss': {'next_win_rate': 0, 'next_avg_pnl': 0, 'count': 0},
        'streak_impact': {},
    }
    
    # Track streaks
    current_streak = 0
    current_streak_type = None
    max_win_streak = 0
    max_loss_streak = 0
    
    for i, trade in enumerate(sorted_trades):
        is_winner = trade.get('win', False)
        
        # Track streaks
        if is_winner:
            if current_streak_type == 'win':
                current_streak += 1
            else:
                if current_streak_type == 'loss' and current_streak > 0:
                    analysis['loss_streaks'].append(current_streak)
                    max_loss_streak = max(max_loss_streak, current_streak)
                current_streak = 1
                current_streak_type = 'win'
        else:
            if current_streak_type == 'loss':
                current_streak += 1
            else:
                if current_streak_type == 'win' and current_streak > 0:
                    analysis['win_streaks'].append(current_streak)
                    max_win_streak = max(max_win_streak, current_streak)
                current_streak = 1
                current_streak_type = 'loss'
        
        # Analyze what happens after wins/losses
        if i < len(sorted_trades) - 1:
            next_trade = sorted_trades[i + 1]
            next_is_winner = next_trade.get('win', False)
            next_pnl = next_trade.get('pnl', 0)
            
            if is_winner:
                analysis['after_win']['count'] += 1
                if next_is_winner:
                    analysis['after_win']['next_win_rate'] += 1
                analysis['after_win']['next_avg_pnl'] += next_pnl
            else:
                analysis['after_loss']['count'] += 1
                if next_is_winner:
                    analysis['after_loss']['next_win_rate'] += 1
                analysis['after_loss']['next_avg_pnl'] += next_pnl
    
    # Finalize streaks
    if current_streak > 0:
        if current_streak_type == 'win':
            analysis['win_streaks'].append(current_streak)
            max_win_streak = max(max_win_streak, current_streak)
        else:
            analysis['loss_streaks'].append(current_streak)
            max_loss_streak = max(max_loss_streak, current_streak)
    
    # Calculate averages
    if analysis['after_win']['count'] > 0:
        analysis['after_win']['next_win_rate'] = analysis['after_win']['next_win_rate'] / analysis['after_win']['count']
        analysis['after_win']['next_avg_pnl'] = analysis['after_win']['next_avg_pnl'] / analysis['after_win']['count']
    
    if analysis['after_loss']['count'] > 0:
        analysis['after_loss']['next_win_rate'] = analysis['after_loss']['next_win_rate'] / analysis['after_loss']['count']
        analysis['after_loss']['next_avg_pnl'] = analysis['after_loss']['next_avg_pnl'] / analysis['after_loss']['count']
    
    # Streak statistics
    if analysis['win_streaks']:
        analysis['streak_impact']['max_win_streak'] = max_win_streak
        analysis['streak_impact']['avg_win_streak'] = mean(analysis['win_streaks'])
    
    if analysis['loss_streaks']:
        analysis['streak_impact']['max_loss_streak'] = max_loss_streak
        analysis['streak_impact']['avg_loss_streak'] = mean(analysis['loss_streaks'])
    
    return analysis


def analyze_exit_timing(trades: List[Dict]) -> Dict[str, Any]:
    """Analyze exit timing: optimal exit points, early vs late exits."""
    winners = [t for t in trades if t.get('win', False)]
    losers = [t for t in trades if not t.get('win', False)]
    
    analysis = {
        'winner_exits': {'early': [], 'optimal': [], 'late': []},
        'loser_exits': {'early': [], 'optimal': [], 'late': []},
        'optimal_exit_duration': None,
    }
    
    # Analyze exit timing for winners
    winner_durations = []
    winner_pnls = []
    
    for trade in winners:
        entry_ts = trade.get('entry_ts', trade.get('ts', 0))
        exit_ts = trade.get('exit_ts', 0)
        pnl = trade.get('pnl', 0)
        
        if entry_ts and exit_ts:
            try:
                if isinstance(entry_ts, str):
                    entry_dt = datetime.fromisoformat(entry_ts.replace('Z', '+00:00'))
                    entry_ts = entry_dt.timestamp()
                elif entry_ts > 1e12:
                    entry_ts = entry_ts / 1000
                
                if isinstance(exit_ts, str):
                    exit_dt = datetime.fromisoformat(exit_ts.replace('Z', '+00:00'))
                    exit_ts = exit_dt.timestamp()
                elif exit_ts > 1e12:
                    exit_ts = exit_ts / 1000
                
                duration_hours = (exit_ts - entry_ts) / 3600
                if duration_hours > 0 and duration_hours < 720:
                    winner_durations.append(duration_hours)
                    winner_pnls.append(pnl)
            except:
                pass
    
    if winner_durations and winner_pnls:
        # Find optimal duration (highest P&L per hour)
        pnl_per_hour = [pnl / dur for pnl, dur in zip(winner_pnls, winner_durations)]
        optimal_idx = pnl_per_hour.index(max(pnl_per_hour))
        analysis['optimal_exit_duration'] = winner_durations[optimal_idx]
        
        # Categorize exits
        median_duration = median(winner_durations)
        for dur, pnl in zip(winner_durations, winner_pnls):
            if dur < median_duration * 0.5:
                analysis['winner_exits']['early'].append({'duration': dur, 'pnl': pnl})
            elif dur > median_duration * 1.5:
                analysis['winner_exits']['late'].append({'duration': dur, 'pnl': pnl})
            else:
                analysis['winner_exits']['optimal'].append({'duration': dur, 'pnl': pnl})
    
    return analysis


def analyze_drawdown_patterns(trades: List[Dict]) -> Dict[str, Any]:
    """Analyze drawdown patterns: maximum adverse/favorable excursion."""
    analysis = {
        'winners': {'max_favorable': [], 'max_adverse': []},
        'losers': {'max_favorable': [], 'max_adverse': []},
    }
    
    for trade in trades:
        entry_price = trade.get('entry_price', 0)
        exit_price = trade.get('exit_price', 0)
        direction = trade.get('direction', 'UNKNOWN').upper()
        is_winner = trade.get('win', False)
        
        if not entry_price or not exit_price or entry_price <= 0:
            continue
        
        # Calculate price movement
        if direction == 'LONG':
            price_change_pct = ((exit_price - entry_price) / entry_price) * 100
        elif direction == 'SHORT':
            price_change_pct = ((entry_price - exit_price) / entry_price) * 100
        else:
            continue
        
        # For winners, track max favorable (how much it went in our favor)
        # For losers, track max adverse (how much it went against us)
        if is_winner:
            analysis['winners']['max_favorable'].append(abs(price_change_pct))
        else:
            analysis['losers']['max_adverse'].append(abs(price_change_pct))
    
    # Calculate statistics
    if analysis['winners']['max_favorable']:
        analysis['winners']['avg_max_favorable'] = mean(analysis['winners']['max_favorable'])
        analysis['winners']['median_max_favorable'] = median(analysis['winners']['max_favorable'])
    
    if analysis['losers']['max_adverse']:
        analysis['losers']['avg_max_adverse'] = mean(analysis['losers']['max_adverse'])
        analysis['losers']['median_max_adverse'] = median(analysis['losers']['max_adverse'])
    
    return analysis


def analyze_signal_strength(trades: List[Dict]) -> Dict[str, Any]:
    """Analyze signal strength: weak vs strong signals, confidence levels."""
    analysis = {
        'strong_signals': {'winners': [], 'losers': []},
        'weak_signals': {'winners': [], 'losers': []},
        'signal_strength_threshold': None,
    }
    
    # Calculate signal strength (combination of OFI and Ensemble)
    signal_strengths = []
    for trade in trades:
        ofi = trade.get('ofi', 0)
        ensemble = trade.get('ensemble', 0)
        
        # Normalize and combine
        strength = (ofi * 0.6 + ensemble * 0.4) if (ofi > 0 or ensemble > 0) else 0
        signal_strengths.append(strength)
    
    if signal_strengths:
        median_strength = median([s for s in signal_strengths if s > 0])
        analysis['signal_strength_threshold'] = median_strength
        
        for trade, strength in zip(trades, signal_strengths):
            is_winner = trade.get('win', False)
            
            if strength >= median_strength:
                if is_winner:
                    analysis['strong_signals']['winners'].append(trade)
                else:
                    analysis['strong_signals']['losers'].append(trade)
            else:
                if is_winner:
                    analysis['weak_signals']['winners'].append(trade)
                else:
                    analysis['weak_signals']['losers'].append(trade)
    
    # Calculate win rates
    strong_total = len(analysis['strong_signals']['winners']) + len(analysis['strong_signals']['losers'])
    weak_total = len(analysis['weak_signals']['winners']) + len(analysis['weak_signals']['losers'])
    
    if strong_total > 0:
        analysis['strong_signals']['win_rate'] = len(analysis['strong_signals']['winners']) / strong_total
    if weak_total > 0:
        analysis['weak_signals']['win_rate'] = len(analysis['weak_signals']['winners']) / weak_total
    
    return analysis


def analyze_market_condition_interactions(trades: List[Dict]) -> Dict[str, Any]:
    """Analyze how market conditions interact with signals."""
    analysis = {
        'high_volatility': {'winners': [], 'losers': []},
        'low_volatility': {'winners': [], 'losers': []},
        'high_volume': {'winners': [], 'losers': []},
        'low_volume': {'winners': [], 'losers': []},
    }
    
    # Get volatility and volume values
    volatilities = [t.get('volatility', 0) for t in trades if t.get('volatility', 0) > 0]
    volumes = [t.get('volume', 0) for t in trades if t.get('volume', 0) > 0]
    
    vol_threshold = median(volatilities) if volatilities else 0
    vol_volume_threshold = median(volumes) if volumes else 0
    
    for trade in trades:
        is_winner = trade.get('win', False)
        volatility = trade.get('volatility', 0)
        volume = trade.get('volume', 0)
        
        if volatility > 0:
            if volatility >= vol_threshold:
                if is_winner:
                    analysis['high_volatility']['winners'].append(trade)
                else:
                    analysis['high_volatility']['losers'].append(trade)
            else:
                if is_winner:
                    analysis['low_volatility']['winners'].append(trade)
                else:
                    analysis['low_volatility']['losers'].append(trade)
        
        if volume > 0:
            if volume >= vol_volume_threshold:
                if is_winner:
                    analysis['high_volume']['winners'].append(trade)
                else:
                    analysis['high_volume']['losers'].append(trade)
            else:
                if is_winner:
                    analysis['low_volume']['winners'].append(trade)
                else:
                    analysis['low_volume']['losers'].append(trade)
    
    # Calculate win rates
    for condition in ['high_volatility', 'low_volatility', 'high_volume', 'low_volume']:
        winners = len(analysis[condition]['winners'])
        losers = len(analysis[condition]['losers'])
        total = winners + losers
        if total > 0:
            analysis[condition]['win_rate'] = winners / total
            analysis[condition]['total'] = total
    
    return analysis


def analyze_fee_impact(trades: List[Dict]) -> Dict[str, Any]:
    """Analyze fee impact on profitability."""
    analysis = {
        'total_fees': 0,
        'fees_vs_pnl': 0,
        'high_fee_trades': {'winners': [], 'losers': []},
        'low_fee_trades': {'winners': [], 'losers': []},
    }
    
    fees_list = []
    for trade in trades:
        outcome = trade.get('outcome', {})
        fees = outcome.get('fees', outcome.get('trading_fees', 0))
        pnl = trade.get('pnl', 0)
        
        if fees > 0:
            fees_list.append(fees)
            analysis['total_fees'] += fees
    
    if fees_list:
        median_fees = median(fees_list)
        total_pnl = sum([t.get('pnl', 0) for t in trades])
        analysis['fees_vs_pnl'] = (analysis['total_fees'] / abs(total_pnl) * 100) if total_pnl != 0 else 0
        
        for trade in trades:
            outcome = trade.get('outcome', {})
            fees = outcome.get('fees', outcome.get('trading_fees', 0))
            is_winner = trade.get('win', False)
            
            if fees >= median_fees:
                if is_winner:
                    analysis['high_fee_trades']['winners'].append(trade)
                else:
                    analysis['high_fee_trades']['losers'].append(trade)
            else:
                if is_winner:
                    analysis['low_fee_trades']['winners'].append(trade)
                else:
                    analysis['low_fee_trades']['losers'].append(trade)
        
        high_fee_total = len(analysis['high_fee_trades']['winners']) + len(analysis['high_fee_trades']['losers'])
        low_fee_total = len(analysis['low_fee_trades']['winners']) + len(analysis['low_fee_trades']['losers'])
        
        if high_fee_total > 0:
            analysis['high_fee_trades']['win_rate'] = len(analysis['high_fee_trades']['winners']) / high_fee_total
        if low_fee_total > 0:
            analysis['low_fee_trades']['win_rate'] = len(analysis['low_fee_trades']['winners']) / low_fee_total
    
    return analysis


def analyze_correlation_matrix(trades: List[Dict]) -> Dict[str, Any]:
    """Analyze correlations between signals and outcomes."""
    # Extract all signal values
    signals = ['ofi', 'ensemble', 'volatility', 'volume']
    signal_data = {sig: [] for sig in signals}
    
    for trade in trades:
        for sig in signals:
            val = trade.get(sig, 0)
            if val is not None and val != 0:
                signal_data[sig].append((val, trade.get('win', False)))
    
    correlations = {}
    
    # Calculate correlation between each signal and win rate
    for sig in signals:
        if len(signal_data[sig]) >= 20:
            values = [v[0] for v in signal_data[sig]]
            wins = [1 if v[1] else 0 for v in signal_data[sig]]
            
            # Simple correlation: do higher values correlate with wins?
            if len(values) > 1:
                mean_val = mean(values)
                mean_win = mean(wins)
                
                # Calculate correlation coefficient
                numerator = sum((values[i] - mean_val) * (wins[i] - mean_win) for i in range(len(values)))
                denom_val = math.sqrt(sum((v - mean_val) ** 2 for v in values))
                denom_win = math.sqrt(sum((w - mean_win) ** 2 for w in wins))
                
                if denom_val > 0 and denom_win > 0:
                    corr = numerator / (denom_val * denom_win)
                    correlations[sig] = {
                        'correlation': corr,
                        'interpretation': 'positive' if corr > 0.1 else 'negative' if corr < -0.1 else 'neutral',
                        'sample_size': len(values),
                    }
    
    return correlations


def analyze_feature_importance(trades: List[Dict]) -> List[Dict]:
    """Rank features by their predictive power for wins/losses."""
    features = []
    
    # Test each feature
    test_features = [
        ('ofi', lambda t: t.get('ofi', 0)),
        ('ensemble', lambda t: t.get('ensemble', 0)),
        ('regime', lambda t: t.get('regime', 'unknown')),
        ('symbol', lambda t: t.get('symbol', 'UNKNOWN')),
        ('strategy', lambda t: t.get('strategy', 'UNKNOWN')),
        ('hour', lambda t: t.get('hour', 12)),
        ('direction', lambda t: t.get('direction', 'UNKNOWN')),
    ]
    
    for feat_name, extractor in test_features:
        # Group by feature value
        groups = defaultdict(lambda: {'winners': [], 'losers': []})
        
        for trade in trades:
            feat_val = extractor(trade)
            if feat_val is not None:
                if trade.get('win', False):
                    groups[feat_val]['winners'].append(trade)
                else:
                    groups[feat_val]['losers'].append(trade)
        
        # Calculate information gain (how well this feature separates winners from losers)
        total_winners = sum(len(g['winners']) for g in groups.values())
        total_losers = sum(len(g['losers']) for g in groups.values())
        total = total_winners + total_losers
        
        if total > 0:
            baseline_entropy = -((total_winners/total) * math.log2(total_winners/total) if total_winners > 0 else 0) - \
                              ((total_losers/total) * math.log2(total_losers/total) if total_losers > 0 else 0)
            
            weighted_entropy = 0
            for feat_val, group in groups.items():
                group_total = len(group['winners']) + len(group['losers'])
                if group_total > 0:
                    group_wr = len(group['winners']) / group_total
                    group_entropy = -((group_wr * math.log2(group_wr) if group_wr > 0 else 0) + 
                                    ((1-group_wr) * math.log2(1-group_wr) if group_wr < 1 else 0))
                    weighted_entropy += (group_total / total) * group_entropy
            
            information_gain = baseline_entropy - weighted_entropy
            
            features.append({
                'feature': feat_name,
                'information_gain': information_gain,
                'groups': len(groups),
                'importance': 'HIGH' if information_gain > 0.1 else 'MEDIUM' if information_gain > 0.05 else 'LOW',
            })
    
    return sorted(features, key=lambda x: x['information_gain'], reverse=True)


def analyze_regime_transitions(trades: List[Dict]) -> Dict[str, Any]:
    """Analyze what happens when market regime changes."""
    # Sort trades by timestamp
    sorted_trades = sorted(trades, key=lambda t: t.get('ts', t.get('entry_ts', 0)))
    
    transitions = {
        'regime_changes': [],
        'after_transition': {'winners': [], 'losers': []},
    }
    
    prev_regime = None
    for i, trade in enumerate(sorted_trades):
        current_regime = trade.get('regime', 'unknown')
        
        if prev_regime and prev_regime != current_regime:
            transitions['regime_changes'].append({
                'from': prev_regime,
                'to': current_regime,
                'trade': trade,
            })
            
            # Track outcome after transition
            if i < len(sorted_trades) - 1:
                next_trade = sorted_trades[i + 1]
                if next_trade.get('win', False):
                    transitions['after_transition']['winners'].append(next_trade)
                else:
                    transitions['after_transition']['losers'].append(next_trade)
        
        prev_regime = current_regime
    
    # Calculate win rate after transitions
    total_after = len(transitions['after_transition']['winners']) + len(transitions['after_transition']['losers'])
    if total_after > 0:
        transitions['after_transition']['win_rate'] = len(transitions['after_transition']['winners']) / total_after
    
    return transitions


def analyze_risk_reward_ratios(trades: List[Dict]) -> Dict[str, Any]:
    """Analyze risk/reward ratios for different conditions."""
    analysis = {
        'overall': {'avg_risk_reward': 0, 'count': 0},
        'by_strategy': {},
        'by_symbol': {},
    }
    
    risk_rewards = []
    
    for trade in trades:
        pnl = trade.get('pnl', 0)
        entry_price = trade.get('entry_price', 0)
        exit_price = trade.get('exit_price', 0)
        
        if entry_price > 0 and exit_price > 0:
            # Calculate risk/reward: how much we risked vs gained
            price_change_pct = abs((exit_price - entry_price) / entry_price) * 100
            
            if pnl > 0:
                # Winner: reward is pnl, risk is what we could have lost
                risk_reward = pnl / abs(price_change_pct) if price_change_pct > 0 else 0
            else:
                # Loser: risk is loss, reward is what we could have gained
                risk_reward = abs(pnl) / price_change_pct if price_change_pct > 0 else 0
            
            if risk_reward > 0:
                risk_rewards.append(risk_reward)
                analysis['overall']['count'] += 1
                
                # By strategy
                strategy = trade.get('strategy', 'UNKNOWN')
                if strategy not in analysis['by_strategy']:
                    analysis['by_strategy'][strategy] = []
                analysis['by_strategy'][strategy].append(risk_reward)
                
                # By symbol
                symbol = trade.get('symbol', 'UNKNOWN')
                if symbol not in analysis['by_symbol']:
                    analysis['by_symbol'][symbol] = []
                analysis['by_symbol'][symbol].append(risk_reward)
    
    if risk_rewards:
        analysis['overall']['avg_risk_reward'] = mean(risk_rewards)
        analysis['overall']['median_risk_reward'] = median(risk_rewards)
    
    # Calculate averages for each group
    for strategy, rrs in analysis['by_strategy'].items():
        if rrs:
            analysis['by_strategy'][strategy] = {
                'avg': mean(rrs),
                'median': median(rrs),
                'count': len(rrs),
            }
    
    for symbol, rrs in analysis['by_symbol'].items():
        if rrs:
            analysis['by_symbol'][symbol] = {
                'avg': mean(rrs),
                'median': median(rrs),
                'count': len(rrs),
            }
    
    return analysis


def analyze_leverage_impact(trades: List[Dict]) -> Dict[str, Any]:
    """Analyze how leverage affects trade outcomes."""
    analysis = {
        'by_leverage': {},
        'optimal_leverage': None,
    }
    
    for trade in trades:
        outcome = trade.get('outcome', {})
        leverage = outcome.get('leverage', trade.get('leverage', 1))
        is_winner = trade.get('win', False)
        
        if leverage > 0:
            if leverage not in analysis['by_leverage']:
                analysis['by_leverage'][leverage] = {'winners': [], 'losers': []}
            
            if is_winner:
                analysis['by_leverage'][leverage]['winners'].append(trade)
            else:
                analysis['by_leverage'][leverage]['losers'].append(trade)
    
    # Calculate win rates by leverage
    best_leverage = None
    best_wr = 0
    
    for leverage, data in analysis['by_leverage'].items():
        winners = len(data['winners'])
        losers = len(data['losers'])
        total = winners + losers
        
        if total >= 10:
            wr = winners / total if total > 0 else 0
            avg_pnl = mean([t.get('pnl', 0) for t in data['winners'] + data['losers']])
            
            analysis['by_leverage'][leverage] = {
                'win_rate': wr,
                'avg_pnl': avg_pnl,
                'total': total,
            }
            
            if wr > best_wr:
                best_wr = wr
                best_leverage = leverage
    
    analysis['optimal_leverage'] = best_leverage
    
    return analysis


def synthesize_key_insights(all_analyses: Dict[str, Any]) -> Dict[str, Any]:
    """Synthesize all analyses into key actionable insights."""
    insights = {
        'critical_findings': [],
        'top_opportunities': [],
        'major_risks': [],
        'data_quality_issues': [],
        'recommended_actions': [],
    }
    
    # Critical findings
    risk_metrics = all_analyses.get('risk_metrics', {})
    if risk_metrics.get('profit_factor', 1) < 1.0:
        insights['critical_findings'].append({
            'finding': f"Strategy is losing money (Profit Factor: {risk_metrics.get('profit_factor', 0):.2f})",
            'severity': 'CRITICAL',
            'impact': 'Strategy needs fundamental changes',
        })
    
    # Top opportunities
    multi_dim = all_analyses.get('multi_dimensional', [])
    winning_patterns = [p for p in multi_dim if p.get('win_rate', 0) > 0.55]
    if winning_patterns:
        best = max(winning_patterns, key=lambda x: x.get('win_rate', 0))
        insights['top_opportunities'].append({
            'opportunity': f"Pattern: {best.get('pattern', '')} has {best.get('win_rate', 0):.1%} win rate",
            'action': f"Focus on trades matching: {best.get('pattern', '')}",
            'confidence': 'HIGH' if best.get('total_trades', 0) >= 20 else 'MEDIUM',
        })
    
    # Major risks
    temporal = all_analyses.get('temporal', {})
    worst_hours = temporal.get('worst_hours', [])
    if worst_hours:
        worst = worst_hours[0] if worst_hours else None
        if worst and worst.get('win_rate', 0.5) < 0.3:
            insights['major_risks'].append({
                'risk': f"Hour {worst.get('hour', 0):02d}:00 has {worst.get('win_rate', 0):.1%} win rate",
                'action': f"Avoid trading at hour {worst.get('hour', 0):02d}:00",
                'severity': 'HIGH',
            })
    
    # Data quality issues
    signal_analyses = all_analyses.get('signal_components', {})
    if not signal_analyses:
        insights['data_quality_issues'].append({
            'issue': 'No signal component data available',
            'impact': 'Cannot analyze individual signal components',
            'fix': 'Enhance data_enrichment_layer.py to include signal components',
        })
    
    # Recommended actions
    if insights['critical_findings']:
        insights['recommended_actions'].append({
            'priority': 'URGENT',
            'action': 'Review and fix fundamental strategy issues',
            'reason': 'Strategy is losing money',
        })
    
    if insights['top_opportunities']:
        insights['recommended_actions'].append({
            'priority': 'HIGH',
            'action': insights['top_opportunities'][0]['action'],
            'reason': f"High win rate pattern identified ({insights['top_opportunities'][0]['opportunity']})",
        })
    
    return insights


def analyze_direction_intelligence(trades: List[Dict]) -> Dict[str, Any]:
    """Analyze WHY LONG vs SHORT trades win/lose differently."""
    direction_data = defaultdict(lambda: {'winners': [], 'losers': []})
    
    for trade in trades:
        direction = trade.get('direction', 'UNKNOWN').upper()
        if direction in ['LONG', 'SHORT']:
            if trade.get('win', False):
                direction_data[direction]['winners'].append(trade)
            else:
                direction_data[direction]['losers'].append(trade)
    
    direction_analysis = {}
    for direction, data in direction_data.items():
        winners = data['winners']
        losers = data['losers']
        total = len(winners) + len(losers)
        
        if total >= 30:  # Minimum sample
            win_rate = len(winners) / total if total > 0 else 0
            avg_pnl = mean([t.get('pnl', 0) for t in winners + losers])
            
            # What makes winners different from losers in this direction?
            key_differences = {}
            for component in ['ofi', 'ensemble', 'mtf', 'regime']:
                winner_values = [t.get(component) for t in winners if t.get(component) is not None]
                loser_values = [t.get(component) for t in losers if t.get(component) is not None]
                
                if component == 'regime':
                    # For regime, compare most common
                    if winner_values and loser_values:
                        winner_mode = max(set(winner_values), key=winner_values.count) if winner_values else None
                        loser_mode = max(set(loser_values), key=loser_values.count) if loser_values else None
                        if winner_mode and winner_mode != loser_mode:
                            key_differences[component] = {
                                'winner_mode': winner_mode,
                                'loser_mode': loser_mode,
                            }
                else:
                    # For numeric, compare means
                    winner_values = [v for v in winner_values if v != 0]
                    loser_values = [v for v in loser_values if v != 0]
                    if winner_values and loser_values and len(winner_values) >= 5 and len(loser_values) >= 5:
                        winner_mean = mean(winner_values)
                        loser_mean = mean(loser_values)
                        diff_pct = ((winner_mean - loser_mean) / abs(loser_mean) * 100) if loser_mean != 0 else 0
                        if abs(diff_pct) > 15:
                            key_differences[component] = {
                                'winner_avg': winner_mean,
                                'loser_avg': loser_mean,
                                'difference_pct': diff_pct,
                            }
            
            direction_analysis[direction] = {
                'win_rate': win_rate,
                'avg_pnl': avg_pnl,
                'total_trades': total,
                'winners': len(winners),
                'losers': len(losers),
                'key_differences': key_differences,
                'importance': 'HIGH' if win_rate > 0.60 or win_rate < 0.40 else 'MEDIUM',
            }
    
    return direction_analysis


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
    
    # Show top 5 winning combinations (if any exist)
    winning_combos = [c for c in sorted_combos if c[1].get('win_rate', 0) > 0.50 and c[1].get('total_trades', 0) >= 20][:5]
    if winning_combos:
        print("   ✅ TOP WINNING COMBINATIONS (WHY they work):")
        for combo, data in winning_combos:
            win_rate = data.get('win_rate', 0)
            total = data.get('total_trades', 0)
            avg_pnl = data.get('avg_pnl', 0)
            winner_pnl = data.get('winner_avg_pnl', 0)
            loser_pnl = data.get('loser_avg_pnl', 0)
            print(f"   🟢 {combo}")
            print(f"      Win Rate: {win_rate:.1%}, Trades: {total}, Avg P&L: ${avg_pnl:.2f}")
            if winner_pnl and loser_pnl:
                print(f"      Winners avg: ${winner_pnl:.2f} | Losers avg: ${loser_pnl:.2f}")
            # Extract conditions from combo string
            conditions = combo.split('|')
            print(f"      → ✅ ENTER when: {' AND '.join(conditions)}")
            print()
    else:
        print("   ⚠️  No clearly winning combinations found (all < 50% win rate)")
        print("   💡 This suggests we need to find what makes winners different")
        print()
    
    # Show bottom 5 losing combinations
    losing_combos = [c for c in sorted_combos if c[1].get('win_rate', 0) < 0.50 and c[1].get('total_trades', 0) >= 20][:5]
    if losing_combos:
        print("   ❌ TOP LOSING COMBINATIONS (WHY they fail):")
        for combo, data in losing_combos:
            win_rate = data.get('win_rate', 0)
            total = data.get('total_trades', 0)
            avg_pnl = data.get('avg_pnl', 0)
            winner_pnl = data.get('winner_avg_pnl', 0)
            loser_pnl = data.get('loser_avg_pnl', 0)
            print(f"   🔴 {combo}")
            print(f"      Win Rate: {win_rate:.1%}, Trades: {total}, Avg P&L: ${avg_pnl:.2f}")
            if winner_pnl and loser_pnl:
                print(f"      Winners avg: ${winner_pnl:.2f} | Losers avg: ${loser_pnl:.2f}")
            conditions = combo.split('|')
            print(f"      → ❌ AVOID when: {' AND '.join(conditions)}")
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
    
    # DEEP ANALYSIS: What makes winners different from losers
    print("="*80)
    print("DEEP WINNING PATTERN ANALYSIS")
    print("="*80)
    print("   What makes winners fundamentally different from losers?")
    print()
    
    winning_patterns = analyze_winning_patterns(intelligence_data)
    
    # Key differences between winners and losers
    key_differences = winning_patterns.get('key_differences', {})
    if key_differences:
        print("   🔍 KEY DIFFERENCES (Winners vs Losers):")
        for component, diff_data in sorted(key_differences.items(),
                                          key=lambda x: abs(x[1].get('difference_pct', 0)),
                                          reverse=True)[:10]:
            is_winning = diff_data.get('is_winning_factor', False)
            diff_pct = diff_data.get('difference_pct', 0)
            winner_avg = diff_data.get('winner_avg', 0)
            loser_avg = diff_data.get('loser_avg', 0)
            winner_min = diff_data.get('winner_min', winner_avg)
            loser_max = diff_data.get('loser_max', loser_avg)
            
            icon = '✅' if is_winning else '❌'
            direction = 'higher' if is_winning else 'lower'
            print(f"   {icon} {component.upper()}: Winners have {abs(diff_pct):.1f}% {direction} values")
            print(f"      Winners: {winner_avg:.3f} (min: {winner_min:.3f}) | Losers: {loser_avg:.3f} (max: {loser_max:.3f})")
            if is_winning:
                threshold = winner_min if 'min' in diff_data else winner_avg * 0.9
                print(f"      → ✅ ENTER when {component} >= {threshold:.3f} (winners minimum)")
            else:
                threshold = loser_max if 'max' in diff_data else loser_avg * 0.9
                print(f"      → ❌ AVOID when {component} >= {threshold:.3f} (losers maximum)")
            print()
    else:
        print("   ⚠️  No significant differences found in available data")
        print("   💡 This may indicate:")
        print("      - Data quality issues (missing intelligence components)")
        print("      - Random outcomes (no clear pattern)")
        print("      - Need more granular analysis (symbol-specific, direction-specific)")
        print()
    
    # Pure winning signatures (only appear in winners)
    winning_sigs = winning_patterns.get('winning_signatures', [])
    if winning_sigs:
        print("   ✅ PURE WINNING PATTERNS (Only in winners - 100% win rate):")
        for sig_data in sorted(winning_sigs, key=lambda x: x.get('count', 0), reverse=True)[:10]:
            sig = sig_data.get('signature', '')
            count = sig_data.get('count', 0)
            print(f"   🟢 {sig}")
            print(f"      Appeared in {count} winners, 0 losers (100% win rate)")
            conditions = sig.split('|')
            print(f"      → ✅ ENTER when: {' AND '.join(conditions)}")
            print()
    else:
        print("   ⚠️  No pure winning patterns found (patterns that only appear in winners)")
        print("   💡 This suggests winners and losers share similar conditions")
        print("      Need to find subtler differences or missing intelligence data")
        print()
    
    # Pure losing signatures (only appear in losers)
    losing_sigs = winning_patterns.get('losing_signatures', [])
    if losing_sigs:
        print("   ❌ PURE LOSING PATTERNS (Only in losers - 0% win rate):")
        for sig_data in sorted(losing_sigs, key=lambda x: x.get('count', 0), reverse=True)[:10]:
            sig = sig_data.get('signature', '')
            count = sig_data.get('count', 0)
            print(f"   🔴 {sig}")
            print(f"      Appeared in {count} losers, 0 winners (0% win rate)")
            conditions = sig.split('|')
            print(f"      → ❌ AVOID when: {' AND '.join(conditions)}")
            print()
    
    # Multi-dimensional pattern discovery
    print("="*80)
    print("MULTI-DIMENSIONAL PATTERN DISCOVERY")
    print("="*80)
    print("   Complex patterns across symbol + direction + signals + strategy")
    print()
    
    multi_dim_patterns = analyze_multi_dimensional_patterns(intelligence_data)
    
    winning_multi = [p for p in multi_dim_patterns if p.get('win_rate', 0) > 0.55][:10]
    if winning_multi:
        print("   ✅ WINNING MULTI-DIMENSIONAL PATTERNS:")
        for pattern in winning_multi:
            win_rate = pattern.get('win_rate', 0)
            total = pattern.get('total_trades', 0)
            avg_pnl = pattern.get('avg_pnl', 0)
            print(f"   🟢 {pattern['pattern']}")
            print(f"      Win Rate: {win_rate:.1%}, Trades: {total}, Avg P&L: ${avg_pnl:.2f}")
            conditions = pattern['pattern'].split('|')
            print(f"      → ✅ ENTER when: {' AND '.join(conditions)}")
            print()
    
    losing_multi = [p for p in multi_dim_patterns if p.get('win_rate', 0) < 0.45][:10]
    if losing_multi:
        print("   ❌ LOSING MULTI-DIMENSIONAL PATTERNS:")
        for pattern in losing_multi:
            win_rate = pattern.get('win_rate', 0)
            total = pattern.get('total_trades', 0)
            avg_pnl = pattern.get('avg_pnl', 0)
            print(f"   🔴 {pattern['pattern']}")
            print(f"      Win Rate: {win_rate:.1%}, Trades: {total}, Avg P&L: ${avg_pnl:.2f}")
            conditions = pattern['pattern'].split('|')
            print(f"      → ❌ AVOID when: {' AND '.join(conditions)}")
            print()
    
    # Symbol-specific analysis
    print("="*80)
    print("SYMBOL-SPECIFIC ANALYSIS")
    print("="*80)
    print("   Understanding WHY certain symbols win/lose differently")
    print()
    
    symbol_analysis = analyze_symbol_intelligence(intelligence_data)
    
    for symbol, data in sorted(symbol_analysis.items(),
                              key=lambda x: x[1].get('win_rate', 0.5),
                              reverse=True):
        win_rate = data.get('win_rate', 0)
        total = data.get('total_trades', 0)
        avg_pnl = data.get('avg_pnl', 0)
        key_diffs = data.get('key_differences', {})
        
        icon = '🟢' if win_rate > 0.55 else '🟡' if win_rate > 0.50 else '🔴'
        print(f"{icon} {symbol}")
        print(f"   Win Rate: {win_rate:.1%}, Trades: {total}, Avg P&L: ${avg_pnl:.2f}")
        
        if key_diffs:
            print(f"   🔍 WHY {symbol} WINS/LOSES:")
            for component, diff_data in key_diffs.items():
                if component == 'direction':
                    preferred = diff_data.get('preferred_direction')
                    winner_pct = diff_data.get('winner_long_pct', 0)
                    loser_pct = diff_data.get('loser_long_pct', 0)
                    print(f"      • Winners: {winner_pct:.1%} LONG | Losers: {loser_pct:.1%} LONG")
                    print(f"      → ✅ Prefer {preferred} for {symbol}")
                else:
                    diff_pct = diff_data.get('difference_pct', 0)
                    winner_avg = diff_data.get('winner_avg', 0)
                    loser_avg = diff_data.get('loser_avg', 0)
                    threshold = diff_data.get('threshold', 0)
                    direction_str = 'higher' if diff_pct > 0 else 'lower'
                    print(f"      • Winners have {abs(diff_pct):.1f}% {direction_str} {component} ({winner_avg:.3f} vs {loser_avg:.3f})")
                    if diff_pct > 0:
                        print(f"      → ✅ ENTER {symbol} when {component} >= {threshold:.3f}")
                    else:
                        print(f"      → ❌ AVOID {symbol} when {component} >= {threshold:.3f}")
        print()
    
    # Analyze direction-specific patterns
    print("="*80)
    print("DIRECTION-SPECIFIC ANALYSIS (LONG vs SHORT)")
    print("="*80)
    print("   Understanding WHY LONG and SHORT trades win/lose differently")
    print()
    
    # Analyze LONG vs SHORT
    long_trades = [t for t in intelligence_data if t.get('direction', '').upper() == 'LONG']
    short_trades = [t for t in intelligence_data if t.get('direction', '').upper() == 'SHORT']
    
    if long_trades and short_trades:
        long_winners = [t for t in long_trades if t.get('win', False)]
        short_winners = [t for t in short_trades if t.get('win', False)]
        
        long_wr = len(long_winners) / len(long_trades) if long_trades else 0
        short_wr = len(short_winners) / len(short_trades) if short_trades else 0
        
        long_avg_pnl = mean([t.get('pnl', 0) for t in long_trades])
        short_avg_pnl = mean([t.get('pnl', 0) for t in short_trades])
        
        print(f"   📊 LONG: {len(long_trades)} trades, {long_wr:.1%} win rate, ${long_avg_pnl:.2f} avg P&L")
        print(f"   📊 SHORT: {len(short_trades)} trades, {short_wr:.1%} win rate, ${short_avg_pnl:.2f} avg P&L")
        print()
        
        # What makes LONG winners different from LONG losers?
        if len(long_winners) >= 10 and len(long_trades) - len(long_winners) >= 10:
            long_winner_ofi = [t.get('ofi', 0) for t in long_winners if t.get('ofi', 0) > 0]
            long_loser_ofi = [t.get('ofi', 0) for t in long_trades if not t.get('win', False) and t.get('ofi', 0) > 0]
            
            if long_winner_ofi and long_loser_ofi:
                long_winner_ofi_mean = mean(long_winner_ofi)
                long_loser_ofi_mean = mean(long_loser_ofi)
                diff_pct = ((long_winner_ofi_mean - long_loser_ofi_mean) / long_loser_ofi_mean * 100) if long_loser_ofi_mean > 0 else 0
                if abs(diff_pct) > 10:
                    print(f"   🔍 LONG TRADES: Winners have {abs(diff_pct):.1f}% {'higher' if diff_pct > 0 else 'lower'} OFI")
                    print(f"      Winners avg OFI: {long_winner_ofi_mean:.3f} | Losers avg OFI: {long_loser_ofi_mean:.3f}")
                    if diff_pct > 0:
                        print(f"      → ✅ ENTER LONG when OFI >= {min(long_winner_ofi):.3f}")
                    else:
                        print(f"      → ❌ AVOID LONG when OFI >= {max(long_loser_ofi):.3f}")
                    print()
        
        # What makes SHORT winners different from SHORT losers?
        if len(short_winners) >= 10 and len(short_trades) - len(short_winners) >= 10:
            short_winner_ofi = [t.get('ofi', 0) for t in short_winners if t.get('ofi', 0) > 0]
            short_loser_ofi = [t.get('ofi', 0) for t in short_trades if not t.get('win', False) and t.get('ofi', 0) > 0]
            
            if short_winner_ofi and short_loser_ofi:
                short_winner_ofi_mean = mean(short_winner_ofi)
                short_loser_ofi_mean = mean(short_loser_ofi)
                diff_pct = ((short_winner_ofi_mean - short_loser_ofi_mean) / short_loser_ofi_mean * 100) if short_loser_ofi_mean > 0 else 0
                if abs(diff_pct) > 10:
                    print(f"   🔍 SHORT TRADES: Winners have {abs(diff_pct):.1f}% {'higher' if diff_pct > 0 else 'lower'} OFI")
                    print(f"      Winners avg OFI: {short_winner_ofi_mean:.3f} | Losers avg OFI: {short_loser_ofi_mean:.3f}")
                    if diff_pct > 0:
                        print(f"      → ✅ ENTER SHORT when OFI >= {min(short_winner_ofi):.3f}")
                    else:
                        print(f"      → ❌ AVOID SHORT when OFI >= {max(short_loser_ofi):.3f}")
                    print()
    else:
        print("   ⚠️  Insufficient data for direction-specific analysis")
        print()
    
    direction_analysis = analyze_direction_intelligence(intelligence_data)
    
    for direction, data in sorted(direction_analysis.items(),
                                 key=lambda x: x[1].get('win_rate', 0.5),
                                 reverse=True):
        win_rate = data.get('win_rate', 0)
        total = data.get('total_trades', 0)
        avg_pnl = data.get('avg_pnl', 0)
        key_diffs = data.get('key_differences', {})
        
        icon = '🟢' if win_rate > 0.60 else '🟡' if win_rate > 0.50 else '🔴'
        print(f"{icon} {direction}")
        print(f"   Win Rate: {win_rate:.1%}, Trades: {total}, Avg P&L: ${avg_pnl:.2f}")
        
        if key_diffs:
            print(f"   🔍 WHY {direction} WINS/LOSES:")
            for component, diff_data in key_diffs.items():
                if component == 'regime':
                    winner_mode = diff_data.get('winner_mode')
                    loser_mode = diff_data.get('loser_mode')
                    print(f"      • Winners in {winner_mode}, losers in {loser_mode}")
                    print(f"      → ✅ Use {direction} in {winner_mode} regime")
                else:
                    diff_pct = diff_data.get('difference_pct', 0)
                    winner_avg = diff_data.get('winner_avg', 0)
                    loser_avg = diff_data.get('loser_avg', 0)
                    direction_str = 'higher' if diff_pct > 0 else 'lower'
                    print(f"      • Winners have {abs(diff_pct):.1f}% {direction_str} {component} ({winner_avg:.3f} vs {loser_avg:.3f})")
                    if diff_pct > 0:
                        print(f"      → ✅ ENTER {direction} when {component} >= {winner_avg * 0.9:.3f}")
                    else:
                        print(f"      → ❌ AVOID {direction} when {component} >= {loser_avg * 0.9:.3f}")
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
    
    # TEMPORAL ANALYSIS
    print("="*80)
    print("TEMPORAL PATTERN ANALYSIS")
    print("="*80)
    print("   Understanding WHEN trades win/lose (hour, session, day of week)")
    print()
    
    temporal_analysis = analyze_temporal_patterns(intelligence_data)
    
    if temporal_analysis.get('best_hours'):
        print("   ✅ BEST HOURS TO TRADE:")
        for hour_data in temporal_analysis['best_hours'][:5]:
            print(f"   🟢 Hour {hour_data['hour']:02d}:00 - {hour_data['win_rate']:.1%} win rate, ${hour_data['avg_pnl']:.2f} avg P&L ({hour_data['total']} trades)")
            print(f"      → ✅ Prefer trading at {hour_data['hour']:02d}:00")
        print()
    
    if temporal_analysis.get('worst_hours'):
        print("   ❌ WORST HOURS TO TRADE:")
        for hour_data in temporal_analysis['worst_hours'][:5]:
            print(f"   🔴 Hour {hour_data['hour']:02d}:00 - {hour_data['win_rate']:.1%} win rate, ${hour_data['avg_pnl']:.2f} avg P&L ({hour_data['total']} trades)")
            print(f"      → ❌ Avoid trading at {hour_data['hour']:02d}:00")
        print()
    
    if temporal_analysis.get('best_sessions'):
        print("   ✅ BEST TRADING SESSIONS:")
        for session_data in temporal_analysis['best_sessions'][:3]:
            print(f"   🟢 {session_data['session']} - {session_data['win_rate']:.1%} win rate, ${session_data['avg_pnl']:.2f} avg P&L ({session_data['total']} trades)")
            print(f"      → ✅ Prefer {session_data['session']} session")
        print()
    
    if temporal_analysis.get('worst_sessions'):
        print("   ❌ WORST TRADING SESSIONS:")
        for session_data in temporal_analysis['worst_sessions'][:3]:
            print(f"   🔴 {session_data['session']} - {session_data['win_rate']:.1%} win rate, ${session_data['avg_pnl']:.2f} avg P&L ({session_data['total']} trades)")
            print(f"      → ❌ Avoid {session_data['session']} session")
        print()
    
    # TRADE DURATION ANALYSIS
    print("="*80)
    print("TRADE DURATION ANALYSIS")
    print("="*80)
    print("   Understanding optimal holding time (how long winners hold vs losers)")
    print()
    
    duration_analysis = analyze_trade_duration(intelligence_data)
    
    if duration_analysis:
        winner_mean = duration_analysis['winners'].get('mean_hours', 0)
        loser_mean = duration_analysis['losers'].get('mean_hours', 0)
        diff_pct = duration_analysis.get('difference_pct', 0)
        optimal = duration_analysis.get('optimal_duration')
        
        print(f"   📊 Winners hold: {winner_mean:.1f} hours (median: {duration_analysis['winners'].get('median_hours', 0):.1f}h)")
        print(f"   📊 Losers hold: {loser_mean:.1f} hours (median: {duration_analysis['losers'].get('median_hours', 0):.1f}h)")
        
        if abs(diff_pct) > 10:
            direction = 'longer' if diff_pct > 0 else 'shorter'
            print(f"   🔍 Winners hold {abs(diff_pct):.1f}% {direction} than losers")
            if optimal:
                print(f"   → ✅ Consider exiting after {optimal:.1f} hours (winners' median duration)")
        print()
    
    # ENTRY PRICE POSITIONING ANALYSIS
    print("="*80)
    print("ENTRY PRICE POSITIONING ANALYSIS")
    print("="*80)
    print("   Understanding optimal entry price position (low/mid/high relative to recent range)")
    print()
    
    price_analysis = analyze_entry_price_positioning(intelligence_data)
    
    for symbol, data in sorted(price_analysis.items())[:5]:
        low_wr = data.get('low_price_wr', 0)
        mid_wr = data.get('mid_price_wr', 0)
        high_wr = data.get('high_price_wr', 0)
        best = data.get('best_position', 'mid')
        
        print(f"   📊 {symbol}:")
        print(f"      Low price (bottom 25%): {low_wr:.1%} win rate")
        print(f"      Mid price (25-75%): {mid_wr:.1%} win rate")
        print(f"      High price (top 25%): {high_wr:.1%} win rate")
        print(f"      → ✅ Best entry position: {best} (relative to recent price range)")
        print()
    
    # RISK-ADJUSTED METRICS
    print("="*80)
    print("RISK-ADJUSTED PERFORMANCE METRICS")
    print("="*80)
    print("   Understanding risk-adjusted returns (Sharpe, Sortino, Profit Factor)")
    print()
    
    risk_metrics = calculate_risk_adjusted_metrics(intelligence_data)
    
    if risk_metrics:
        print(f"   📊 Sharpe Ratio: {risk_metrics.get('sharpe_ratio', 0):.2f} (annualized)")
        print(f"   📊 Sortino Ratio: {risk_metrics.get('sortino_ratio', 0):.2f} (annualized)")
        print(f"   📊 Profit Factor: {risk_metrics.get('profit_factor', 0):.2f}")
        print(f"   📊 Win/Loss Ratio: {risk_metrics.get('win_loss_ratio', 0):.2f}")
        print(f"   📊 Avg Win: ${risk_metrics.get('avg_win', 0):.2f} | Avg Loss: ${risk_metrics.get('avg_loss', 0):.2f}")
        print()
        
        # Interpretation
        sharpe = risk_metrics.get('sharpe_ratio', 0)
        profit_factor = risk_metrics.get('profit_factor', 0)
        
        if sharpe > 1.0:
            print(f"   ✅ Sharpe > 1.0: Good risk-adjusted returns")
        elif sharpe > 0:
            print(f"   🟡 Sharpe 0-1.0: Acceptable but could improve")
        else:
            print(f"   🔴 Sharpe < 0: Poor risk-adjusted returns")
        
        if profit_factor > 1.5:
            print(f"   ✅ Profit Factor > 1.5: Profitable strategy")
        elif profit_factor > 1.0:
            print(f"   🟡 Profit Factor 1.0-1.5: Marginally profitable")
        else:
            print(f"   🔴 Profit Factor < 1.0: Losing strategy")
        print()
    
    # SEQUENCE/STREAK ANALYSIS
    print("="*80)
    print("SEQUENCE & STREAK ANALYSIS")
    print("="*80)
    print("   Understanding patterns in trade sequences (streaks, what happens after wins/losses)")
    print()
    
    sequence_analysis = analyze_sequence_patterns(intelligence_data)
    
    if sequence_analysis.get('after_win', {}).get('count', 0) > 0:
        after_win_wr = sequence_analysis['after_win']['next_win_rate']
        after_win_pnl = sequence_analysis['after_win']['next_avg_pnl']
        print(f"   📊 AFTER A WIN:")
        print(f"      Next trade win rate: {after_win_wr:.1%}")
        print(f"      Next trade avg P&L: ${after_win_pnl:.2f}")
        if after_win_wr < 0.4:
            print(f"      → ⚠️  Wins are often followed by losses (reversion)")
        elif after_win_wr > 0.6:
            print(f"      → ✅ Wins tend to cluster (momentum)")
        print()
    
    if sequence_analysis.get('after_loss', {}).get('count', 0) > 0:
        after_loss_wr = sequence_analysis['after_loss']['next_win_rate']
        after_loss_pnl = sequence_analysis['after_loss']['next_avg_pnl']
        print(f"   📊 AFTER A LOSS:")
        print(f"      Next trade win rate: {after_loss_wr:.1%}")
        print(f"      Next trade avg P&L: ${after_loss_pnl:.2f}")
        if after_loss_wr > 0.6:
            print(f"      → ✅ Losses are often followed by wins (reversion)")
        elif after_loss_wr < 0.4:
            print(f"      → ⚠️  Losses tend to cluster (negative momentum)")
        print()
    
    if sequence_analysis.get('streak_impact'):
        max_win = sequence_analysis['streak_impact'].get('max_win_streak', 0)
        max_loss = sequence_analysis['streak_impact'].get('max_loss_streak', 0)
        if max_win > 0:
            print(f"   📊 Max win streak: {max_win} trades")
        if max_loss > 0:
            print(f"   📊 Max loss streak: {max_loss} trades")
        print()
    
    # EXIT TIMING ANALYSIS
    print("="*80)
    print("EXIT TIMING ANALYSIS")
    print("="*80)
    print("   Understanding optimal exit timing (when to exit for maximum profit)")
    print()
    
    exit_analysis = analyze_exit_timing(intelligence_data)
    
    if exit_analysis.get('optimal_exit_duration'):
        optimal_hours = exit_analysis['optimal_exit_duration']
        print(f"   ✅ Optimal exit duration: {optimal_hours:.1f} hours")
        print(f"      → Consider exiting winners after ~{optimal_hours:.1f} hours for best P&L/hour")
        print()
    
    if exit_analysis.get('winner_exits'):
        early_count = len(exit_analysis['winner_exits']['early'])
        optimal_count = len(exit_analysis['winner_exits']['optimal'])
        late_count = len(exit_analysis['winner_exits']['late'])
        
        if early_count + optimal_count + late_count > 0:
            print(f"   📊 Winner exit timing:")
            print(f"      Early exits: {early_count}")
            print(f"      Optimal exits: {optimal_count}")
            print(f"      Late exits: {late_count}")
            print()
    
    # DRAWDOWN ANALYSIS
    print("="*80)
    print("DRAWDOWN & EXCURSION ANALYSIS")
    print("="*80)
    print("   Understanding maximum favorable/adverse price movement")
    print()
    
    drawdown_analysis = analyze_drawdown_patterns(intelligence_data)
    
    if drawdown_analysis.get('winners', {}).get('avg_max_favorable'):
        avg_fav = drawdown_analysis['winners']['avg_max_favorable']
        print(f"   📊 Winners: Avg max favorable movement: {avg_fav:.2f}%")
        print(f"      → Winners typically see {avg_fav:.2f}% price movement in our favor")
        print()
    
    if drawdown_analysis.get('losers', {}).get('avg_max_adverse'):
        avg_adv = drawdown_analysis['losers']['avg_max_adverse']
        print(f"   📊 Losers: Avg max adverse movement: {avg_adv:.2f}%")
        print(f"      → Losers typically see {avg_adv:.2f}% price movement against us")
        print()
    
    # SIGNAL STRENGTH ANALYSIS
    print("="*80)
    print("SIGNAL STRENGTH ANALYSIS")
    print("="*80)
    print("   Understanding weak vs strong signals (confidence levels)")
    print()
    
    signal_strength_analysis = analyze_signal_strength(intelligence_data)
    
    if signal_strength_analysis.get('strong_signals', {}).get('win_rate') is not None:
        strong_wr = signal_strength_analysis['strong_signals']['win_rate']
        strong_total = len(signal_strength_analysis['strong_signals']['winners']) + len(signal_strength_analysis['strong_signals']['losers'])
        print(f"   📊 Strong Signals (OFI + Ensemble above median):")
        print(f"      Win Rate: {strong_wr:.1%}, Trades: {strong_total}")
        if strong_wr > 0.55:
            print(f"      → ✅ Strong signals are more reliable")
        elif strong_wr < 0.45:
            print(f"      → ⚠️  Strong signals are not more reliable")
        print()
    
    if signal_strength_analysis.get('weak_signals', {}).get('win_rate') is not None:
        weak_wr = signal_strength_analysis['weak_signals']['win_rate']
        weak_total = len(signal_strength_analysis['weak_signals']['winners']) + len(signal_strength_analysis['weak_signals']['losers'])
        print(f"   📊 Weak Signals (OFI + Ensemble below median):")
        print(f"      Win Rate: {weak_wr:.1%}, Trades: {weak_total}")
        print()
    
    if signal_strength_analysis.get('signal_strength_threshold'):
        threshold = signal_strength_analysis['signal_strength_threshold']
        print(f"   🎯 Signal Strength Threshold: {threshold:.3f}")
        print(f"      → Consider requiring signal strength >= {threshold:.3f} for entry")
        print()
    
    # MARKET CONDITION INTERACTIONS
    print("="*80)
    print("MARKET CONDITION INTERACTIONS")
    print("="*80)
    print("   Understanding how volatility and volume affect trade outcomes")
    print()
    
    market_condition_analysis = analyze_market_condition_interactions(intelligence_data)
    
    for condition in ['high_volatility', 'low_volatility', 'high_volume', 'low_volume']:
        data = market_condition_analysis.get(condition, {})
        if data.get('win_rate') is not None and data.get('total', 0) >= 10:
            wr = data['win_rate']
            total = data['total']
            icon = '🟢' if wr > 0.55 else '🟡' if wr > 0.50 else '🔴'
            print(f"   {icon} {condition.replace('_', ' ').title()}:")
            print(f"      Win Rate: {wr:.1%}, Trades: {total}")
            if wr > 0.55:
                print(f"      → ✅ Prefer trading in {condition.replace('_', ' ')} conditions")
            elif wr < 0.45:
                print(f"      → ❌ Avoid trading in {condition.replace('_', ' ')} conditions")
            print()
    
    # FEE IMPACT ANALYSIS
    print("="*80)
    print("FEE IMPACT ANALYSIS")
    print("="*80)
    print("   Understanding how fees affect profitability")
    print()
    
    fee_analysis = analyze_fee_impact(intelligence_data)
    
    if fee_analysis.get('total_fees', 0) > 0:
        total_fees = fee_analysis['total_fees']
        fees_vs_pnl = fee_analysis.get('fees_vs_pnl', 0)
        print(f"   📊 Total fees paid: ${total_fees:.2f}")
        print(f"   📊 Fees as % of total P&L: {fees_vs_pnl:.1f}%")
        
        if fees_vs_pnl > 50:
            print(f"      → ⚠️  Fees are eating >50% of profits - consider reducing trade frequency")
        elif fees_vs_pnl > 25:
            print(f"      → 🟡 Fees are significant - monitor trade frequency")
        else:
            print(f"      → ✅ Fees are reasonable")
        print()
    
    if fee_analysis.get('high_fee_trades', {}).get('win_rate') is not None:
        high_fee_wr = fee_analysis['high_fee_trades']['win_rate']
        low_fee_wr = fee_analysis.get('low_fee_trades', {}).get('win_rate', 0)
        print(f"   📊 High fee trades: {high_fee_wr:.1%} win rate")
        print(f"   📊 Low fee trades: {low_fee_wr:.1%} win rate")
        if high_fee_wr < low_fee_wr:
            print(f"      → ⚠️  Higher fees correlate with lower win rates")
        print()
    
    # CORRELATION ANALYSIS
    print("="*80)
    print("SIGNAL CORRELATION ANALYSIS")
    print("="*80)
    print("   Understanding which signals correlate with wins/losses")
    print()
    
    correlations = analyze_correlation_matrix(intelligence_data)
    
    if correlations:
        for signal, corr_data in sorted(correlations.items(), 
                                       key=lambda x: abs(x[1].get('correlation', 0)), 
                                       reverse=True):
            corr = corr_data.get('correlation', 0)
            interp = corr_data.get('interpretation', 'neutral')
            icon = '🟢' if abs(corr) > 0.2 else '🟡' if abs(corr) > 0.1 else '⚪'
            direction = 'positive' if corr > 0 else 'negative'
            print(f"   {icon} {signal.upper()}: {corr:.3f} correlation ({interp})")
            if abs(corr) > 0.15:
                print(f"      → {'Higher' if corr > 0 else 'Lower'} {signal} correlates with wins")
            print()
    else:
        print("   ⚠️  Insufficient data for correlation analysis")
        print()
    
    # FEATURE IMPORTANCE RANKING
    print("="*80)
    print("FEATURE IMPORTANCE RANKING")
    print("="*80)
    print("   Ranking features by predictive power (information gain)")
    print()
    
    feature_importance = analyze_feature_importance(intelligence_data)
    
    if feature_importance:
        print("   📊 Top Predictive Features:")
        for i, feat in enumerate(feature_importance[:7], 1):
            importance = feat.get('importance', 'LOW')
            icon = '🔴' if importance == 'HIGH' else '🟡' if importance == 'MEDIUM' else '⚪'
            print(f"   {icon} {i}. {feat['feature'].upper()}: {feat['information_gain']:.4f} information gain")
            print(f"      ({feat['groups']} distinct values, {importance} importance)")
            print()
    else:
        print("   ⚠️  Could not calculate feature importance")
        print()
    
    # REGIME TRANSITION ANALYSIS
    print("="*80)
    print("REGIME TRANSITION ANALYSIS")
    print("="*80)
    print("   Understanding what happens when market regime changes")
    print()
    
    regime_transitions = analyze_regime_transitions(intelligence_data)
    
    if regime_transitions.get('regime_changes'):
        num_transitions = len(regime_transitions['regime_changes'])
        print(f"   📊 Total regime transitions: {num_transitions}")
        
        if regime_transitions.get('after_transition', {}).get('win_rate') is not None:
            after_wr = regime_transitions['after_transition']['win_rate']
            total_after = len(regime_transitions['after_transition']['winners']) + len(regime_transitions['after_transition']['losers'])
            print(f"   📊 Win rate after regime change: {after_wr:.1%} ({total_after} trades)")
            if after_wr > 0.55:
                print(f"      → ✅ Regime changes create opportunities")
            elif after_wr < 0.45:
                print(f"      → ⚠️  Regime changes create risk")
            print()
    
    # RISK/REWARD RATIO ANALYSIS
    print("="*80)
    print("RISK/REWARD RATIO ANALYSIS")
    print("="*80)
    print("   Understanding risk-adjusted returns by strategy and symbol")
    print()
    
    risk_reward = analyze_risk_reward_ratios(intelligence_data)
    
    if risk_reward.get('overall', {}).get('avg_risk_reward', 0) > 0:
        avg_rr = risk_reward['overall']['avg_risk_reward']
        median_rr = risk_reward['overall'].get('median_risk_reward', 0)
        print(f"   📊 Overall avg risk/reward: {avg_rr:.2f} (median: {median_rr:.2f})")
        if avg_rr > 2.0:
            print(f"      → ✅ Excellent risk/reward ratio")
        elif avg_rr > 1.5:
            print(f"      → 🟡 Good risk/reward ratio")
        else:
            print(f"      → ⚠️  Poor risk/reward ratio")
        print()
    
    # Show by strategy
    if risk_reward.get('by_strategy'):
        print("   📊 By Strategy:")
        for strategy, data in sorted(risk_reward['by_strategy'].items(),
                                   key=lambda x: x[1].get('avg', 0),
                                   reverse=True)[:5]:
            avg_rr = data.get('avg', 0)
            count = data.get('count', 0)
            if count >= 10:
                print(f"      {strategy}: {avg_rr:.2f} avg R/R ({count} trades)")
        print()
    
    # LEVERAGE IMPACT ANALYSIS
    print("="*80)
    print("LEVERAGE IMPACT ANALYSIS")
    print("="*80)
    print("   Understanding optimal leverage for different conditions")
    print()
    
    leverage_analysis = analyze_leverage_impact(intelligence_data)
    
    if leverage_analysis.get('optimal_leverage'):
        optimal = leverage_analysis['optimal_leverage']
        optimal_data = leverage_analysis['by_leverage'].get(optimal, {})
        optimal_wr = optimal_data.get('win_rate', 0)
        print(f"   ✅ Optimal Leverage: {optimal}x")
        print(f"      Win Rate: {optimal_wr:.1%}, Avg P&L: ${optimal_data.get('avg_pnl', 0):.2f}")
        print(f"      → Consider using {optimal}x leverage")
        print()
    
    if leverage_analysis.get('by_leverage'):
        print("   📊 Win Rate by Leverage:")
        for leverage, data in sorted(leverage_analysis['by_leverage'].items(),
                                    key=lambda x: x[1].get('win_rate', 0),
                                    reverse=True):
            if isinstance(data, dict) and data.get('total', 0) >= 10:
                wr = data.get('win_rate', 0)
                total = data.get('total', 0)
                icon = '🟢' if wr > 0.55 else '🟡' if wr > 0.50 else '🔴'
                print(f"   {icon} {leverage}x: {wr:.1%} win rate ({total} trades)")
        print()
    
    # STATISTICAL SIGNIFICANCE TESTING
    print("="*80)
    print("STATISTICAL SIGNIFICANCE TESTING")
    print("="*80)
    print("   Verifying which patterns are statistically significant (not random)")
    print()
    
    if HAS_SCIPY:
        # Test top multi-dimensional patterns
        significant_patterns = []
        for pattern in multi_dim_patterns[:10]:
            pattern_trades = [t for t in intelligence_data 
                            if any(pattern['pattern'] in str(t.get(k, '')) for k in ['symbol', 'strategy', 'direction'])]
            if len(pattern_trades) >= 10:
                sig_test = calculate_statistical_significance(
                    intelligence_data, pattern['pattern'], pattern_trades, intelligence_data
                )
                if sig_test.get('significant', False):
                    significant_patterns.append((pattern, sig_test))
        
        if significant_patterns:
            print(f"   ✅ Found {len(significant_patterns)} statistically significant patterns (p < 0.05):")
            for pattern, sig_test in significant_patterns[:5]:
                print(f"   🟢 {pattern['pattern']}")
                print(f"      Win Rate: {pattern['win_rate']:.1%} vs Baseline: {sig_test.get('baseline_wr', 0):.1%}")
                print(f"      p-value: {sig_test.get('p_value', 1.0):.4f} (statistically significant)")
                print()
        else:
            print("   ⚠️  No patterns found with statistical significance (p < 0.05)")
            print("   💡 This may indicate patterns are due to random variation")
            print()
    else:
        print("   ⚠️  scipy not available - skipping statistical significance testing")
        print("   💡 Install scipy for statistical validation: pip install scipy")
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
        'winning_patterns': winning_patterns,
        'directions': direction_analysis,
        'symbols': symbol_analysis,
        'multi_dimensional': multi_dim_patterns,
        'temporal': temporal_analysis,
        'duration': duration_analysis,
        'price_positioning': price_analysis,
        'risk_metrics': risk_metrics,
        'sequences': sequence_analysis,
        'exit_timing': exit_analysis,
        'drawdowns': drawdown_analysis,
        'signal_strength': signal_strength_analysis,
        'market_conditions': market_condition_analysis,
        'fee_impact': fee_analysis,
        'correlations': correlations,
        'feature_importance': feature_importance,
        'regime_transitions': regime_transitions,
        'risk_reward': risk_reward,
        'leverage': leverage_analysis,
    }
    
    improvements = generate_improvement_plan(all_analyses)
    
    # SYNTHESIZE KEY INSIGHTS
    print("="*80)
    print("KEY INSIGHTS SYNTHESIS - What We're Actually Learning")
    print("="*80)
    print("   Synthesizing all analyses into actionable insights")
    print()
    
    key_insights = synthesize_key_insights(all_analyses)
    
    if key_insights.get('critical_findings'):
        print("   🔴 CRITICAL FINDINGS:")
        for finding in key_insights['critical_findings']:
            print(f"   🔴 {finding['finding']}")
            print(f"      Impact: {finding.get('impact', 'Unknown')}")
            print()
    
    if key_insights.get('top_opportunities'):
        print("   ✅ TOP OPPORTUNITIES:")
        for opp in key_insights['top_opportunities'][:3]:
            print(f"   🟢 {opp['opportunity']}")
            print(f"      Action: {opp['action']}")
            print(f"      Confidence: {opp.get('confidence', 'UNKNOWN')}")
            print()
    
    if key_insights.get('major_risks'):
        print("   ⚠️  MAJOR RISKS:")
        for risk in key_insights['major_risks'][:3]:
            print(f"   🔴 {risk['risk']}")
            print(f"      Action: {risk['action']}")
            print()
    
    if key_insights.get('data_quality_issues'):
        print("   📊 DATA QUALITY ISSUES:")
        for issue in key_insights['data_quality_issues']:
            print(f"   ⚠️  {issue['issue']}")
            print(f"      Impact: {issue.get('impact', 'Unknown')}")
            print(f"      Fix: {issue.get('fix', 'Unknown')}")
            print()
    
    if key_insights.get('recommended_actions'):
        print("   🎯 RECOMMENDED ACTIONS (Priority Order):")
        for action in key_insights['recommended_actions']:
            priority = action.get('priority', 'MEDIUM')
            icon = '🔴' if priority == 'URGENT' else '🟡' if priority == 'HIGH' else '🟢'
            print(f"   {icon} [{priority}] {action['action']}")
            print(f"      Why: {action.get('reason', 'Unknown')}")
            print()
    
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
    print(f"   - Analyzed {len(symbol_analysis)} symbols")
    print(f"   - Discovered {len(multi_dim_patterns)} multi-dimensional patterns")
    print(f"   - Found {len(winning_patterns.get('winning_signatures', []))} pure winning signatures")
    print(f"   - Found {len(winning_patterns.get('losing_signatures', []))} pure losing signatures")
    print(f"   - Analyzed temporal patterns (hours, sessions, days)")
    print(f"   - Analyzed trade duration patterns")
    print(f"   - Analyzed entry price positioning")
    print(f"   - Analyzed sequence/streak patterns")
    print(f"   - Analyzed exit timing optimization")
    print(f"   - Analyzed drawdown patterns")
    print(f"   - Analyzed signal strength (weak vs strong)")
    print(f"   - Analyzed market condition interactions")
    print(f"   - Analyzed fee impact on profitability")
    print(f"   - Analyzed signal correlations with outcomes")
    print(f"   - Ranked features by predictive power")
    print(f"   - Analyzed regime transition impacts")
    print(f"   - Analyzed risk/reward ratios by strategy/symbol")
    print(f"   - Analyzed leverage impact on outcomes")
    print(f"   - Calculated risk-adjusted metrics (Sharpe: {risk_metrics.get('sharpe_ratio', 0):.2f}, Profit Factor: {risk_metrics.get('profit_factor', 0):.2f})")
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
