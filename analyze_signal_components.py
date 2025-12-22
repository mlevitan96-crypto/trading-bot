#!/usr/bin/env python3
"""
Signal Component Analysis - Extract Detailed Metrics for Hypothesis Testing
================================================================================
Checks what data we have and extracts:
1. Volatility at Entry (ATR, Volume)
2. Signal Component Breakdown (Liquidation, Funding, Whale Flow separately)
3. Market Regime Classification at entry

For last 1000-1500 trades to test hypotheses about what's causing losses.
"""

import os
import sys
import json
from pathlib import Path
from datetime import datetime, timezone
from collections import defaultdict
from typing import Dict, List, Any, Optional
from statistics import mean, median

sys.path.insert(0, os.path.dirname(__file__))

from src.infrastructure.path_registry import PathRegistry


def _parse_timestamp(ts_value):
    """
    Convert various timestamp formats to Unix timestamp (int).
    Handles:
    - ISO format strings (e.g., '2025-12-16T01:42:55.492612')
    - Unix timestamps (int or float)
    - Unix milliseconds (if > 1e12)
    """
    if ts_value is None:
        return 0
    if isinstance(ts_value, (int, float)):
        # If it's milliseconds (large number), convert to seconds
        if ts_value > 1e12:
            return int(ts_value / 1000)
        return int(ts_value)
    if isinstance(ts_value, str):
        try:
            # Try ISO format (handles with/without timezone)
            dt = datetime.fromisoformat(ts_value.replace('Z', '+00:00'))
            return int(dt.timestamp())
        except:
            try:
                # Try common formats
                for fmt in ["%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S"]:
                    try:
                        dt = datetime.strptime(ts_value.replace('Z', '').replace('+00:00', ''), fmt)
                        return int(dt.timestamp())
                    except:
                        continue
            except:
                pass
    return 0


def load_enriched_decisions(limit: int = 1500) -> List[Dict]:
    """Load enriched decisions with complete signal context."""
    enriched_path = PathRegistry.get_path("logs", "enriched_decisions.jsonl")
    trades = []
    
    if not os.path.exists(enriched_path):
        print(f"ERROR: {enriched_path} not found")
        return []
    
    print(f"Loading from {enriched_path}...")
    with open(enriched_path, 'r') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
                # Only include executed trades
                if record.get('outcome', {}).get('executed', True) is not False:
                    trades.append(record)
            except:
                continue
    
    # Sort by timestamp, take most recent
    trades.sort(key=lambda t: _parse_timestamp(t.get('ts', t.get('entry_ts', 0))), reverse=True)
    return trades[:limit]


def load_predictive_signals() -> Dict[str, List[Dict]]:
    """Load predictive signals with component breakdown."""
    signals_path = PathRegistry.get_path("logs", "predictive_signals.jsonl")
    signals_by_symbol = defaultdict(list)
    
    if not os.path.exists(signals_path):
        print(f"WARNING: {signals_path} not found - signal components may not be available")
        return {}
    
    print(f"Loading from {signals_path}...")
    with open(signals_path, 'r') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                signal = json.loads(line)
                symbol = signal.get('symbol', 'UNKNOWN')
                if symbol != 'UNKNOWN':
                    signals_by_symbol[symbol].append(signal)
            except:
                continue
    
    # Sort by timestamp
    for symbol in signals_by_symbol:
        signals_by_symbol[symbol].sort(key=lambda s: _parse_timestamp(s.get('ts', 0)), reverse=True)
    
    return signals_by_symbol


def calculate_atr_from_prices(symbol: str, entry_ts: int, window: int = 14) -> Optional[float]:
    """Calculate ATR from price history if available."""
    # Try to find price data
    price_paths = [
        PathRegistry.get_path("logs", "price_history.jsonl"),
        "logs/price_history.jsonl",
        "feature_store/price_data.jsonl",
    ]
    
    for price_path in price_paths:
        if os.path.exists(price_path):
            try:
                prices = []
                with open(price_path, 'r') as f:
                    for line in f:
                        try:
                            p = json.loads(line.strip())
                            if p.get('symbol') == symbol:
                                prices.append(p)
                        except:
                            continue
                
                # Filter prices around entry time (within 1 hour)
                relevant_prices = [p for p in prices 
                                 if abs(p.get('ts', 0) - entry_ts) < 3600]
                
                if len(relevant_prices) >= window:
                    # Sort by timestamp
                    relevant_prices.sort(key=lambda x: x.get('ts', 0))
                    
                    # Calculate True Range
                    trs = []
                    for i in range(1, len(relevant_prices)):
                        high = float(relevant_prices[i].get('high', 0))
                        low = float(relevant_prices[i].get('low', 0))
                        prev_close = float(relevant_prices[i-1].get('close', 0))
                        
                        if high > 0 and low > 0 and prev_close > 0:
                            tr = max(high - low, abs(high - prev_close), abs(low - prev_close))
                            trs.append(tr)
                    
                    if len(trs) >= window:
                        # ATR = average of last window TRs
                        atr = mean(trs[-window:])
                        return atr
            except Exception as e:
                pass
    
    return None


def extract_signal_components(signal_data: Dict) -> Dict[str, Any]:
    """Extract individual signal components from signal data."""
    components = {
        'liquidation_cascade': None,
        'funding_rate': None,
        'whale_flow': None,
        'oi_velocity': None,
        'fear_greed': None,
        'hurst': None,
        'lead_lag': None,
        'volatility_skew': None,
        'oi_divergence': None,
    }
    
    # Check if signals dict exists
    signals = signal_data.get('signals', {})
    if isinstance(signals, dict):
        # Liquidation
        liq = signals.get('liquidation', {})
        if isinstance(liq, dict):
            components['liquidation_cascade'] = {
                'cascade_active': liq.get('cascade_active', False),
                'confidence': liq.get('confidence', 0),
                'direction': liq.get('direction', 'NEUTRAL'),
                'total_1h': liq.get('total_1h', 0),
            }
        
        # Funding
        funding = signals.get('funding', {})
        if isinstance(funding, dict):
            components['funding_rate'] = {
                'rate': funding.get('funding_rate', 0),
                'confidence': funding.get('confidence', 0),
                'direction': funding.get('direction', 'NEUTRAL'),
            }
        
        # Whale Flow
        whale = signals.get('whale_flow', {})
        if isinstance(whale, dict):
            components['whale_flow'] = {
                'net_flow_usd': whale.get('net_flow_usd', 0),
                'confidence': whale.get('confidence', 0),
                'direction': whale.get('direction', 'NEUTRAL'),
            }
        
        # OI Velocity
        oi_vel = signals.get('oi_velocity', {})
        if isinstance(oi_vel, dict):
            components['oi_velocity'] = {
                'change_1h_pct': oi_vel.get('change_1h_pct', 0),
                'confidence': oi_vel.get('confidence', 0),
            }
        
        # Fear/Greed
        fg = signals.get('fear_greed', {})
        if isinstance(fg, dict):
            components['fear_greed'] = {
                'index': fg.get('index', 50),
                'confidence': fg.get('confidence', 0),
            }
        
        # Hurst
        hurst = signals.get('hurst', {})
        if isinstance(hurst, dict):
            components['hurst'] = hurst.get('value', 0.5)
        
        # Lead/Lag
        lead_lag = signals.get('lead_lag', {})
        if isinstance(lead_lag, dict):
            components['lead_lag'] = lead_lag.get('value', 0)
        
        # Volatility Skew
        vol_skew = signals.get('volatility_skew', {})
        if isinstance(vol_skew, dict):
            components['volatility_skew'] = vol_skew.get('value', 0)
        
        # OI Divergence
        oi_div = signals.get('oi_divergence', {})
        if isinstance(oi_div, dict):
            components['oi_divergence'] = oi_div.get('value', 0)
    
    return components


def match_trade_with_signals(trade: Dict, signals_by_symbol: Dict[str, List[Dict]]) -> Optional[Dict]:
    """Match trade with predictive signals to get component breakdown."""
    symbol = trade.get('symbol', 'UNKNOWN')
    entry_ts_raw = trade.get('entry_ts', trade.get('ts', 0))
    entry_ts = _parse_timestamp(entry_ts_raw)
    
    if symbol == 'UNKNOWN' or not entry_ts:
        return None
    
    # Find signal closest to entry time (within 5 minutes)
    signals = signals_by_symbol.get(symbol, [])
    
    best_match = None
    best_diff = float('inf')
    
    for signal in signals:
        signal_ts_raw = signal.get('ts', 0)
        signal_ts = _parse_timestamp(signal_ts_raw)
        diff = abs(signal_ts - entry_ts)
        
        if diff < 300 and diff < best_diff:  # Within 5 minutes
            best_match = signal
            best_diff = diff
    
    return best_match


def analyze_trade_metrics(trade: Dict, signals_by_symbol: Dict[str, List[Dict]]) -> Dict[str, Any]:
    """Extract all requested metrics for a trade."""
    metrics = {
        'trade_id': trade.get('ts', 0),
        'symbol': trade.get('symbol', 'UNKNOWN'),
        'strategy': trade.get('strategy', 'UNKNOWN'),
        'direction': trade.get('signal_ctx', {}).get('side', 'UNKNOWN'),
        'entry_ts': _parse_timestamp(trade.get('entry_ts', trade.get('ts', 0))),
        'entry_price': trade.get('outcome', {}).get('entry_price', 0),
        'exit_price': trade.get('outcome', {}).get('exit_price', 0),
        'pnl': trade.get('outcome', {}).get('pnl_usd', 0),
        'win': trade.get('outcome', {}).get('pnl_usd', 0) > 0,
    }
    
    # Extract signal context
    signal_ctx = trade.get('signal_ctx', {})
    metrics['ofi'] = signal_ctx.get('ofi', 0)
    metrics['ensemble'] = signal_ctx.get('ensemble', 0)
    metrics['regime'] = signal_ctx.get('regime', 'unknown')
    
    # Try to get volatility/ATR
    entry_ts = metrics['entry_ts']
    if entry_ts:
        atr = calculate_atr_from_prices(metrics['symbol'], entry_ts)
        if atr:
            metrics['atr'] = atr
            metrics['atr_pct'] = (atr / metrics['entry_price'] * 100) if metrics['entry_price'] > 0 else 0
    
    # Try to get volume
    volume = signal_ctx.get('volume', 0)
    if volume:
        metrics['volume'] = volume
        metrics['volume_24h'] = signal_ctx.get('volume_24h', volume)
    
    # Try to get volatility
    volatility = signal_ctx.get('volatility', 0)
    if volatility:
        metrics['volatility'] = volatility
    
    # Match with predictive signals to get component breakdown
    matched_signal = match_trade_with_signals(trade, signals_by_symbol)
    if matched_signal:
        components = extract_signal_components(matched_signal)
        metrics['signal_components'] = components
        metrics['signal_matched'] = True
        metrics['signal_ts'] = _parse_timestamp(matched_signal.get('ts', 0))
    else:
        metrics['signal_components'] = {}
        metrics['signal_matched'] = False
    
    # Check if signal_ctx has any component data
    if not metrics['signal_components']:
        # Try to extract from signal_ctx directly
        if 'liquidation' in signal_ctx:
            metrics['signal_components']['liquidation_cascade'] = signal_ctx.get('liquidation')
        if 'funding_rate' in signal_ctx:
            metrics['signal_components']['funding_rate'] = signal_ctx.get('funding_rate')
        if 'whale_flow' in signal_ctx:
            metrics['signal_components']['whale_flow'] = signal_ctx.get('whale_flow')
    
    return metrics


def analyze_volatility_hypothesis(trades: List[Dict]) -> Dict[str, Any]:
    """Test hypothesis: Losses correlate with Low Volatility or Extreme Volatility."""
    analysis = {
        'winners_by_volatility': defaultdict(list),
        'losers_by_volatility': defaultdict(list),
        'volatility_buckets': {
            'very_low': [],
            'low': [],
            'medium': [],
            'high': [],
            'very_high': [],
        }
    }
    
    for trade in trades:
        atr_pct = trade.get('atr_pct', 0)
        volatility = trade.get('volatility', 0)
        is_winner = trade.get('win', False)
        
        # Use ATR % if available, otherwise volatility
        vol_metric = atr_pct if atr_pct > 0 else (volatility * 100 if volatility > 0 else None)
        
        if vol_metric is None:
            continue
        
        # Bucket volatility
        if vol_metric < 0.5:
            bucket = 'very_low'
        elif vol_metric < 1.0:
            bucket = 'low'
        elif vol_metric < 2.0:
            bucket = 'medium'
        elif vol_metric < 3.0:
            bucket = 'high'
        else:
            bucket = 'very_high'
        
        analysis['volatility_buckets'][bucket].append(trade)
        
        if is_winner:
            analysis['winners_by_volatility'][bucket].append(trade)
        else:
            analysis['losers_by_volatility'][bucket].append(trade)
    
    # Calculate win rates by bucket
    results = {}
    for bucket in analysis['volatility_buckets']:
        winners = len(analysis['winners_by_volatility'][bucket])
        losers = len(analysis['losers_by_volatility'][bucket])
        total = winners + losers
        
        if total > 0:
            win_rate = winners / total
            avg_pnl = mean([t.get('pnl', 0) for t in analysis['volatility_buckets'][bucket]])
            
            results[bucket] = {
                'win_rate': win_rate,
                'avg_pnl': avg_pnl,
                'total': total,
                'winners': winners,
                'losers': losers,
            }
    
    return results


def analyze_signal_component_hypothesis(trades: List[Dict]) -> Dict[str, Any]:
    """Test hypothesis: Liquidation Cascade signals cause losses, Whale Flow is accurate."""
    analysis = {
        'by_liquidation': {'winners': [], 'losers': []},
        'by_funding': {'winners': [], 'losers': []},
        'by_whale_flow': {'winners': [], 'losers': []},
    }
    
    for trade in trades:
        is_winner = trade.get('win', False)
        components = trade.get('signal_components', {})
        
        # Liquidation Cascade
        liq = components.get('liquidation_cascade', {})
        if liq and isinstance(liq, dict) and liq.get('cascade_active', False):
            if is_winner:
                analysis['by_liquidation']['winners'].append(trade)
            else:
                analysis['by_liquidation']['losers'].append(trade)
        
        # Funding Rate
        funding = components.get('funding_rate', {})
        if funding and isinstance(funding, dict):
            funding_rate = funding.get('rate', 0)
            if abs(funding_rate) > 0.0001:  # Non-zero funding
                if is_winner:
                    analysis['by_funding']['winners'].append(trade)
                else:
                    analysis['by_funding']['losers'].append(trade)
        
        # Whale Flow
        whale = components.get('whale_flow', {})
        if whale and isinstance(whale, dict):
            net_flow = whale.get('net_flow_usd', 0)
            if abs(net_flow) > 10000:  # Significant whale flow
                if is_winner:
                    analysis['by_whale_flow']['winners'].append(trade)
                else:
                    analysis['by_whale_flow']['losers'].append(trade)
    
    # Calculate win rates
    results = {}
    for component, data in analysis.items():
        winners = len(data['winners'])
        losers = len(data['losers'])
        total = winners + losers
        
        if total > 0:
            win_rate = winners / total
            avg_pnl = mean([t.get('pnl', 0) for t in data['winners'] + data['losers']])
            
            results[component] = {
                'win_rate': win_rate,
                'avg_pnl': avg_pnl,
                'total': total,
                'winners': winners,
                'losers': losers,
            }
    
    return results


def analyze_regime_hypothesis(trades: List[Dict]) -> Dict[str, Any]:
    """Test hypothesis: Bot fails to detect Stable/Chop regimes accurately."""
    analysis = defaultdict(lambda: {'winners': [], 'losers': []})
    
    for trade in trades:
        regime = trade.get('regime', 'unknown')
        is_winner = trade.get('win', False)
        
        if is_winner:
            analysis[regime]['winners'].append(trade)
        else:
            analysis[regime]['losers'].append(trade)
    
    # Calculate win rates by regime
    results = {}
    for regime, data in analysis.items():
        winners = len(data['winners'])
        losers = len(data['losers'])
        total = winners + losers
        
        if total > 0:
            win_rate = winners / total
            avg_pnl = mean([t.get('pnl', 0) for t in data['winners'] + data['losers']])
            
            results[regime] = {
                'win_rate': win_rate,
                'avg_pnl': avg_pnl,
                'total': total,
                'winners': winners,
                'losers': losers,
            }
    
    return results


def main():
    print("="*80)
    print("SIGNAL COMPONENT ANALYSIS - Hypothesis Testing")
    print("="*80)
    print(f"Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print()
    
    # Load data
    print("Loading trades...")
    trades = load_enriched_decisions(limit=1500)
    print(f"Loaded {len(trades)} trades")
    print()
    
    print("Loading predictive signals...")
    signals_by_symbol = load_predictive_signals()
    print(f"Loaded signals for {len(signals_by_symbol)} symbols")
    print()
    
    if not trades:
        print("ERROR: No trades found!")
        print()
        print("Checking alternative data sources...")
        
        # Try positions_futures.json
        portfolio_path = PathRegistry.get_path("logs", "positions_futures.json")
        if os.path.exists(portfolio_path):
            print(f"Found positions_futures.json at {portfolio_path}")
            with open(portfolio_path, 'r') as f:
                portfolio = json.load(f)
            closed = portfolio.get('closed_positions', [])
            print(f"Found {len(closed)} closed positions")
            if closed:
                print("NOTE: positions_futures.json may not have complete signal component data")
                print("Recommendation: Run data enrichment to create enriched_decisions.jsonl")
        else:
            print("positions_futures.json not found")
        
        print()
        print("RECOMMENDATION: Run data enrichment first:")
        print("  python -c 'from src.data_enrichment_layer import enrich_recent_decisions, persist_enriched_data; persist_enriched_data(enrich_recent_decisions(168))'")
        return 1
    
    # Extract metrics for each trade
    print("Extracting metrics...")
    enriched_trades = []
    for trade in trades:
        metrics = analyze_trade_metrics(trade, signals_by_symbol)
        enriched_trades.append(metrics)
    
    # Data availability report
    print()
    print("="*80)
    print("DATA AVAILABILITY REPORT")
    print("="*80)
    
    total = len(enriched_trades)
    
    if total == 0:
        print("No trades to analyze")
        return 1
    
    atr_count = sum(1 for t in enriched_trades if t.get('atr') is not None)
    volatility_count = sum(1 for t in enriched_trades if t.get('volatility', 0) > 0)
    volume_count = sum(1 for t in enriched_trades if t.get('volume', 0) > 0)
    signal_matched_count = sum(1 for t in enriched_trades if t.get('signal_matched', False))
    liquidation_count = sum(1 for t in enriched_trades 
                          if t.get('signal_components', {}).get('liquidation_cascade') is not None)
    funding_count = sum(1 for t in enriched_trades 
                       if t.get('signal_components', {}).get('funding_rate') is not None)
    whale_flow_count = sum(1 for t in enriched_trades 
                          if t.get('signal_components', {}).get('whale_flow') is not None)
    regime_count = sum(1 for t in enriched_trades if t.get('regime', 'unknown') != 'unknown')
    
    print(f"Total trades analyzed: {total}")
    print()
    print(f"Volatility Metrics:")
    print(f"   - ATR at entry: {atr_count}/{total} ({atr_count/total*100:.1f}%)")
    print(f"   - Volatility value: {volatility_count}/{total} ({volatility_count/total*100:.1f}%)")
    print(f"   - Volume: {volume_count}/{total} ({volume_count/total*100:.1f}%)")
    print()
    print(f"Signal Components:")
    print(f"   - Signal matched: {signal_matched_count}/{total} ({signal_matched_count/total*100:.1f}%)")
    print(f"   - Liquidation Cascade: {liquidation_count}/{total} ({liquidation_count/total*100:.1f}%)")
    print(f"   - Funding Rate: {funding_count}/{total} ({funding_count/total*100:.1f}%)")
    print(f"   - Whale Flow: {whale_flow_count}/{total} ({whale_flow_count/total*100:.1f}%)")
    print()
    print(f"Regime Classification:")
    print(f"   - Regime data: {regime_count}/{total} ({regime_count/total*100:.1f}%)")
    print()
    
    # Hypothesis Testing
    print("="*80)
    print("HYPOTHESIS 1: Volatility at Entry (Low/Extreme = Losses)")
    print("="*80)
    
    vol_analysis = analyze_volatility_hypothesis(enriched_trades)
    
    if vol_analysis:
        print("   Win Rate by Volatility Bucket (ATR % or Volatility):")
        for bucket in ['very_low', 'low', 'medium', 'high', 'very_high']:
            if bucket in vol_analysis:
                data = vol_analysis[bucket]
                wr = data['win_rate']
                total = data['total']
                avg_pnl = data['avg_pnl']
                icon = '[GOOD]' if wr > 0.5 else '[BAD]'
                print(f"   {icon} {bucket.upper()}: {wr:.1%} win rate, ${avg_pnl:.2f} avg P&L ({total} trades)")
        
        # Test hypothesis
        very_low_wr = vol_analysis.get('very_low', {}).get('win_rate', 0.5)
        very_high_wr = vol_analysis.get('very_high', {}).get('win_rate', 0.5)
        medium_wr = vol_analysis.get('medium', {}).get('win_rate', 0.5)
        
        if very_low_wr < 0.4 or very_high_wr < 0.4:
            print()
            print("   [CONFIRMED] HYPOTHESIS CONFIRMED: Extreme volatility (very low or very high) correlates with losses")
        elif medium_wr > max(very_low_wr, very_high_wr):
            print()
            print("   [CONFIRMED] HYPOTHESIS CONFIRMED: Medium volatility performs better than extremes")
        else:
            print()
            print("   [NOT CONFIRMED] HYPOTHESIS NOT CONFIRMED: Volatility pattern unclear")
    else:
        print("   WARNING: Insufficient volatility data for analysis")
    print()
    
    print("="*80)
    print("HYPOTHESIS 2: Signal Component Breakdown")
    print("="*80)
    print("   Testing: Liquidation Cascade causes losses, Whale Flow is accurate")
    print()
    
    component_analysis = analyze_signal_component_hypothesis(enriched_trades)
    
    if component_analysis:
        for component, data in component_analysis.items():
            wr = data['win_rate']
            total = data['total']
            avg_pnl = data['avg_pnl']
            icon = '[GOOD]' if wr > 0.5 else '[BAD]'
            component_name = component.replace('by_', '').replace('_', ' ').title()
            print(f"   {icon} {component_name}: {wr:.1%} win rate, ${avg_pnl:.2f} avg P&L ({total} trades)")
        
        # Test specific hypotheses
        liq_wr = component_analysis.get('by_liquidation', {}).get('win_rate', 0.5)
        whale_wr = component_analysis.get('by_whale_flow', {}).get('win_rate', 0.5)
        
        print()
        if liq_wr < 0.4:
            print("   [CONFIRMED] HYPOTHESIS CONFIRMED: Liquidation Cascade signals correlate with losses")
        else:
            print("   [NOT CONFIRMED] HYPOTHESIS NOT CONFIRMED: Liquidation Cascade doesn't cause losses")
        
        if whale_wr > 0.5:
            print("   [CONFIRMED] HYPOTHESIS CONFIRMED: Whale Flow signals are accurate")
        else:
            print("   [NOT CONFIRMED] HYPOTHESIS NOT CONFIRMED: Whale Flow signals are not accurate")
    else:
        print("   WARNING: Insufficient signal component data for analysis")
    print()
    
    print("="*80)
    print("HYPOTHESIS 3: Regime Classification Accuracy")
    print("="*80)
    print("   Testing: Bot fails to detect Stable/Chop regimes accurately")
    print()
    
    regime_analysis = analyze_regime_hypothesis(enriched_trades)
    
    if regime_analysis:
        print("   Win Rate by Regime:")
        for regime, data in sorted(regime_analysis.items(), 
                                  key=lambda x: x[1].get('win_rate', 0.5),
                                  reverse=True):
            wr = data['win_rate']
            total = data['total']
            avg_pnl = data['avg_pnl']
            icon = '[GOOD]' if wr > 0.5 else '[BAD]'
            print(f"   {icon} {regime.upper()}: {wr:.1%} win rate, ${avg_pnl:.2f} avg P&L ({total} trades)")
        
        # Test hypothesis
        stable_wr = regime_analysis.get('Stable', {}).get('win_rate', 0.5)
        unknown_wr = regime_analysis.get('unknown', {}).get('win_rate', 0.5)
        
        print()
        if stable_wr < 0.4 and unknown_wr < 0.4:
            print("   [CONFIRMED] HYPOTHESIS CONFIRMED: Stable/Unknown regimes have low win rates")
            print("      Bot may be misclassifying regimes or trading poorly in stable conditions")
        else:
            print("   [NOT CONFIRMED] HYPOTHESIS NOT CONFIRMED: Regime classification may be working")
    else:
        print("   WARNING: Insufficient regime data for analysis")
    print()
    
    # Export detailed data
    print("="*80)
    print("EXPORTING DETAILED DATA")
    print("="*80)
    
    output_file = PathRegistry.get_path("feature_store", "signal_component_analysis.json")
    output_file.parent.mkdir(parents=True, exist_ok=True)
    
    export_data = {
        'generated_at': datetime.now().isoformat(),
        'total_trades': len(enriched_trades),
        'data_availability': {
            'atr': atr_count,
            'volatility': volatility_count,
            'volume': volume_count,
            'signal_matched': signal_matched_count,
            'liquidation': liquidation_count,
            'funding': funding_count,
            'whale_flow': whale_flow_count,
            'regime': regime_count,
        },
        'volatility_analysis': vol_analysis,
        'component_analysis': component_analysis,
        'regime_analysis': regime_analysis,
        'detailed_trades': enriched_trades[:500],  # Export first 500 for review
    }
    
    with open(output_file, 'w') as f:
        json.dump(export_data, f, indent=2)
    
    print(f"Detailed data exported to: {output_file}")
    print(f"   - {len(enriched_trades)} trades with metrics")
    print(f"   - First 500 trades included in export for detailed review")
    print()
    
    # Summary
    print("="*80)
    print("SUMMARY")
    print("="*80)
    print(f"Analyzed {len(enriched_trades)} trades")
    print(f"Data availability:")
    print(f"   - Volatility (ATR/Vol): {max(atr_count, volatility_count)}/{total} ({max(atr_count, volatility_count)/total*100:.1f}%)")
    print(f"   - Signal Components: {signal_matched_count}/{total} ({signal_matched_count/total*100:.1f}%)")
    print(f"   - Regime: {regime_count}/{total} ({regime_count/total*100:.1f}%)")
    print()
    print("Recommendations:")
    if signal_matched_count < total * 0.5:
        print("   - Enhance data_enrichment_layer.py to include signal components in enriched_decisions.jsonl")
    if atr_count < total * 0.3:
        print("   - Add ATR calculation at entry time to position logging")
    if regime_count < total * 0.8:
        print("   - Ensure regime is always set in signal_ctx")
    print()
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
