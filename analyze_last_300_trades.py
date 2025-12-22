#!/usr/bin/env python3
"""
Learning Analysis: Last 300 Trades
==================================
Deep dive into the last 300 trades to identify patterns and generate actionable learning.
"""

import os
import sys
import json
from pathlib import Path
from datetime import datetime, timezone
from collections import defaultdict
from typing import Dict, List, Any
from statistics import mean, median

sys.path.insert(0, os.path.dirname(__file__))

from src.data_registry import DataRegistry as DR
from src.infrastructure.path_registry import PathRegistry

def get_direction(trade: Dict) -> str:
    """Extract trade direction robustly."""
    direction = trade.get('direction', '')
    if isinstance(direction, str):
        direction = direction.upper()
    if not direction or direction not in ['LONG', 'SHORT']:
        # Try alternative fields
        direction = trade.get('side', '').upper()
        if direction in ['BUY', 'LONG']:
            return 'LONG'
        elif direction in ['SELL', 'SHORT']:
            return 'SHORT'
    return direction if direction in ['LONG', 'SHORT'] else 'UNKNOWN'

def get_ofi(trade: Dict) -> float:
    """Extract OFI value robustly."""
    # Try multiple possible field names
    ofi = trade.get('ofi', trade.get('ofi_score', trade.get('ofi_raw', 0)))
    if ofi is None:
        return 0.0
    try:
        return abs(float(ofi))
    except:
        return 0.0

def get_pnl(trade: Dict) -> float:
    """Extract P&L robustly."""
    pnl = trade.get('net_pnl', trade.get('pnl', trade.get('profit', 0)))
    if pnl is None:
        return 0.0
    try:
        return float(pnl)
    except:
        return 0.0

def get_fees(trade: Dict) -> float:
    """Extract total fees."""
    trading_fees = trade.get('trading_fees', trade.get('fees_usd', 0)) or 0
    funding_fees = trade.get('funding_fees', 0) or 0
    try:
        return float(trading_fees) + float(funding_fees)
    except:
        return 0.0

def load_last_300_trades() -> List[Dict]:
    """Load the last 300 closed trades."""
    print("="*80)
    print("LOADING LAST 300 TRADES")
    print("="*80)
    
    try:
        # Use DataRegistry to get closed trades
        portfolio_path = PathRegistry.get_path("logs", "positions_futures.json")
        
        if not portfolio_path.exists():
            print(f"❌ Portfolio file not found: {portfolio_path}")
            return []
        
        with open(portfolio_path, 'r') as f:
            portfolio = json.load(f)
        
        closed = portfolio.get('closed_positions', [])
        
        # Filter to alpha bot trades only
        closed = [t for t in closed if t.get('bot_type', 'alpha') == 'alpha']
        
        # Sort by close time (most recent first)
        def get_close_ts(trade):
            close_time = trade.get('closed_at') or trade.get('timestamp', '')
            if isinstance(close_time, str):
                try:
                    dt = datetime.fromisoformat(close_time.replace('Z', '+00:00'))
                    return dt.timestamp()
                except:
                    return 0
            return float(close_time) if close_time else 0
        
        closed.sort(key=get_close_ts, reverse=True)
        
        # Take last 300
        trades = closed[:300]
        
        print(f"   ✅ Loaded {len(trades)} trades (from {len(closed)} total)")
        print()
        
        return trades
        
    except Exception as e:
        print(f"❌ Error loading trades: {e}")
        import traceback
        traceback.print_exc()
        return []

def analyze_trades(trades: List[Dict]) -> Dict[str, Any]:
    """Perform comprehensive analysis."""
    if not trades:
        return {}
    
    print("="*80)
    print("ANALYZING TRADES")
    print("="*80)
    print()
    
    # Initialize metrics
    metrics = {
        'total_trades': len(trades),
        'total_pnl': 0.0,
        'total_fees': 0.0,
        'winning_trades': 0,
        'losing_trades': 0,
        'by_direction': {'LONG': [], 'SHORT': []},
        'by_ofi_bucket': defaultdict(list),
        'by_symbol': defaultdict(list),
        'by_strategy': defaultdict(list),
        'by_regime': defaultdict(list),
    }
    
    # Process each trade
    for trade in trades:
        direction = get_direction(trade)
        pnl = get_pnl(trade)
        fees = get_fees(trade)
        ofi = get_ofi(trade)
        symbol = trade.get('symbol', 'UNKNOWN')
        strategy = trade.get('strategy', 'UNKNOWN')
        regime = trade.get('regime', trade.get('market_regime', 'UNKNOWN'))
        
        metrics['total_pnl'] += pnl
        metrics['total_fees'] += fees
        
        if pnl > 0:
            metrics['winning_trades'] += 1
        else:
            metrics['losing_trades'] += 1
        
        # Group by direction
        if direction in ['LONG', 'SHORT']:
            metrics['by_direction'][direction].append({
                'pnl': pnl,
                'ofi': ofi,
                'symbol': symbol,
                'strategy': strategy,
            })
        
        # Group by OFI bucket
        if ofi < 0.3:
            bucket = 'LOW (0-0.3)'
        elif ofi < 0.5:
            bucket = 'MEDIUM (0.3-0.5)'
        elif ofi < 0.7:
            bucket = 'HIGH (0.5-0.7)'
        else:
            bucket = 'VERY_HIGH (0.7+)'
        metrics['by_ofi_bucket'][bucket].append({
            'pnl': pnl,
            'direction': direction,
            'ofi': ofi,
        })
        
        # Group by symbol
        metrics['by_symbol'][symbol].append({
            'pnl': pnl,
            'direction': direction,
            'ofi': ofi,
        })
        
        # Group by strategy
        metrics['by_strategy'][strategy].append({
            'pnl': pnl,
            'direction': direction,
            'ofi': ofi,
        })
        
        # Group by regime
        metrics['by_regime'][regime].append({
            'pnl': pnl,
            'direction': direction,
            'ofi': ofi,
        })
    
    return metrics

def generate_insights(metrics: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Generate actionable insights from metrics."""
    insights = []
    
    print("="*80)
    print("KEY INSIGHTS")
    print("="*80)
    print()
    
    # 1. Overall Performance
    total_pnl = metrics['total_pnl']
    total_fees = metrics['total_fees']
    net_pnl = total_pnl - total_fees
    win_rate = (metrics['winning_trades'] / metrics['total_trades']) * 100 if metrics['total_trades'] > 0 else 0
    
    print(f"📊 OVERALL PERFORMANCE:")
    print(f"   Total Trades: {metrics['total_trades']}")
    print(f"   Gross P&L: ${total_pnl:,.2f}")
    print(f"   Total Fees: ${total_fees:,.2f}")
    print(f"   Net P&L: ${net_pnl:,.2f}")
    print(f"   Win Rate: {win_rate:.1f}% ({metrics['winning_trades']}W / {metrics['losing_trades']}L)")
    print()
    
    insights.append({
        'type': 'overall',
        'title': 'Overall Performance',
        'data': {
            'total_trades': metrics['total_trades'],
            'gross_pnl': total_pnl,
            'fees': total_fees,
            'net_pnl': net_pnl,
            'win_rate': win_rate,
        }
    })
    
    # 2. Direction Analysis
    long_trades = metrics['by_direction']['LONG']
    short_trades = metrics['by_direction']['SHORT']
    
    if long_trades:
        long_pnl = sum(t['pnl'] for t in long_trades)
        long_avg_ofi = mean([t['ofi'] for t in long_trades])
        long_win_rate = (sum(1 for t in long_trades if t['pnl'] > 0) / len(long_trades)) * 100
    else:
        long_pnl = 0
        long_avg_ofi = 0
        long_win_rate = 0
    
    if short_trades:
        short_pnl = sum(t['pnl'] for t in short_trades)
        short_avg_ofi = mean([t['ofi'] for t in short_trades])
        short_win_rate = (sum(1 for t in short_trades if t['pnl'] > 0) / len(short_trades)) * 100
    else:
        short_pnl = 0
        short_avg_ofi = 0
        short_win_rate = 0
    
    print(f"📈 DIRECTION ANALYSIS:")
    print(f"   LONG Trades: {len(long_trades)}")
    print(f"      P&L: ${long_pnl:,.2f}")
    print(f"      Avg OFI: {long_avg_ofi:.3f}")
    print(f"      Win Rate: {long_win_rate:.1f}%")
    print()
    print(f"   SHORT Trades: {len(short_trades)}")
    print(f"      P&L: ${short_pnl:,.2f}")
    print(f"      Avg OFI: {short_avg_ofi:.3f}")
    print(f"      Win Rate: {short_win_rate:.1f}%")
    print()
    
    insights.append({
        'type': 'direction',
        'title': 'Direction Performance',
        'data': {
            'long': {
                'count': len(long_trades),
                'pnl': long_pnl,
                'avg_ofi': long_avg_ofi,
                'win_rate': long_win_rate,
            },
            'short': {
                'count': len(short_trades),
                'pnl': short_pnl,
                'avg_ofi': short_avg_ofi,
                'win_rate': short_win_rate,
            }
        }
    })
    
    # 3. OFI Bucket Analysis
    print(f"📊 OFI BUCKET ANALYSIS:")
    for bucket in ['LOW (0-0.3)', 'MEDIUM (0.3-0.5)', 'HIGH (0.5-0.7)', 'VERY_HIGH (0.7+)']:
        bucket_trades = metrics['by_ofi_bucket'][bucket]
        if bucket_trades:
            bucket_pnl = sum(t['pnl'] for t in bucket_trades)
            bucket_win_rate = (sum(1 for t in bucket_trades if t['pnl'] > 0) / len(bucket_trades)) * 100
            print(f"   {bucket}: {len(bucket_trades)} trades, P&L: ${bucket_pnl:,.2f}, Win Rate: {bucket_win_rate:.1f}%")
    print()
    
    # 4. Top/Bottom Performers
    print(f"🏆 TOP PERFORMERS:")
    symbol_pnl = {sym: sum(t['pnl'] for t in trades) for sym, trades in metrics['by_symbol'].items()}
    top_symbols = sorted(symbol_pnl.items(), key=lambda x: x[1], reverse=True)[:5]
    for sym, pnl in top_symbols:
        count = len(metrics['by_symbol'][sym])
        print(f"   {sym}: ${pnl:,.2f} ({count} trades)")
    print()
    
    print(f"📉 BOTTOM PERFORMERS:")
    bottom_symbols = sorted(symbol_pnl.items(), key=lambda x: x[1])[:5]
    for sym, pnl in bottom_symbols:
        count = len(metrics['by_symbol'][sym])
        print(f"   {sym}: ${pnl:,.2f} ({count} trades)")
    print()
    
    return insights

def generate_recommendations(metrics: Dict[str, Any], insights: List[Dict]) -> List[Dict[str, Any]]:
    """Generate actionable recommendations."""
    recommendations = []
    
    print("="*80)
    print("ACTIONABLE RECOMMENDATIONS")
    print("="*80)
    print()
    
    # Analyze direction performance
    long_trades = metrics['by_direction']['LONG']
    short_trades = metrics['by_direction']['SHORT']
    
    if long_trades:
        long_pnl = sum(t['pnl'] for t in long_trades)
        long_avg_ofi = mean([t['ofi'] for t in long_trades])
    else:
        long_pnl = 0
        long_avg_ofi = 0
    
    if short_trades:
        short_pnl = sum(t['pnl'] for t in short_trades)
        short_avg_ofi = mean([t['ofi'] for t in short_trades])
    else:
        short_pnl = 0
        short_avg_ofi = 0
    
    # Recommendation 1: OFI Thresholds
    if long_avg_ofi < 0.5 and long_pnl < 0:
        recommendations.append({
            'priority': 'HIGH',
            'category': 'OFI Thresholds',
            'action': f'LONG trades with low OFI ({long_avg_ofi:.3f}) are losing money. Enforce minimum OFI ≥ 0.5 for LONG trades.',
            'impact': 'Should reduce losing LONG trades significantly',
        })
        print(f"🔴 HIGH PRIORITY: LONG trades have low OFI ({long_avg_ofi:.3f}) and negative P&L (${long_pnl:,.2f})")
        print(f"   → Enforce minimum OFI ≥ 0.5 for LONG trades")
        print()
    
    if short_avg_ofi >= 0.5 and short_pnl > 0:
        recommendations.append({
            'priority': 'MEDIUM',
            'category': 'OFI Thresholds',
            'action': f'SHORT trades with high OFI ({short_avg_ofi:.3f}) are profitable. Maintain current OFI requirements.',
            'impact': 'Current strategy is working for SHORT trades',
        })
        print(f"✅ SHORT trades with high OFI ({short_avg_ofi:.3f}) are profitable (${short_pnl:,.2f})")
        print(f"   → Maintain current OFI requirements for SHORT")
        print()
    
    # Recommendation 2: Direction Bias
    if long_pnl < 0 and short_pnl > 0:
        recommendations.append({
            'priority': 'HIGH',
            'category': 'Direction Bias',
            'action': 'LONG trades are losing while SHORT trades are winning. Consider reducing LONG trade frequency or increasing LONG OFI requirements.',
            'impact': 'Should improve overall profitability',
        })
        print(f"🔴 HIGH PRIORITY: LONG losing (${long_pnl:,.2f}) vs SHORT winning (${short_pnl:,.2f})")
        print(f"   → Consider reducing LONG trade frequency or increasing LONG OFI requirements")
        print()
    
    # Recommendation 3: OFI Bucket Analysis
    low_ofi_trades = metrics['by_ofi_bucket']['LOW (0-0.3)']
    if low_ofi_trades:
        low_pnl = sum(t['pnl'] for t in low_ofi_trades)
        if low_pnl < 0:
            recommendations.append({
                'priority': 'MEDIUM',
                'category': 'OFI Thresholds',
                'action': 'Trades with OFI < 0.3 are losing money. Consider blocking all trades with OFI < 0.3.',
                'impact': 'Should reduce low-quality trades',
            })
            print(f"⚠️  MEDIUM PRIORITY: Low OFI trades (<0.3) are losing (${low_pnl:,.2f})")
            print(f"   → Consider blocking all trades with OFI < 0.3")
            print()
    
    # Recommendation 4: Symbol Performance
    symbol_pnl = {sym: sum(t['pnl'] for t in trades) for sym, trades in metrics['by_symbol'].items()}
    losing_symbols = [sym for sym, pnl in symbol_pnl.items() if pnl < -100 and len(metrics['by_symbol'][sym]) >= 5]
    if losing_symbols:
        recommendations.append({
            'priority': 'MEDIUM',
            'category': 'Symbol Selection',
            'action': f'These symbols are consistently losing: {", ".join(losing_symbols[:5])}. Consider reducing position sizes or skipping these symbols.',
            'impact': 'Should reduce losses from underperforming symbols',
        })
        print(f"⚠️  MEDIUM PRIORITY: Consistently losing symbols: {', '.join(losing_symbols[:5])}")
        print(f"   → Consider reducing position sizes or skipping these symbols")
        print()
    
    return recommendations

def main():
    print("="*80)
    print("LEARNING ANALYSIS: LAST 300 TRADES")
    print("="*80)
    print(f"Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print()
    
    # Load trades
    trades = load_last_300_trades()
    
    if not trades:
        print("❌ No trades found. Cannot perform analysis.")
        return 1
    
    # Analyze
    metrics = analyze_trades(trades)
    
    # Generate insights
    insights = generate_insights(metrics)
    
    # Generate recommendations
    recommendations = generate_recommendations(metrics, insights)
    
    # Save results
    results = {
        'generated_at': datetime.now().isoformat(),
        'analysis_period': 'last_300_trades',
        'total_trades_analyzed': len(trades),
        'metrics': metrics,
        'insights': insights,
        'recommendations': recommendations,
    }
    
    output_path = PathRegistry.get_path("feature_store", "last_300_trades_analysis.json")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    with open(output_path, 'w') as f:
        json.dump(results, f, indent=2, default=str)
    
    print("="*80)
    print("ANALYSIS COMPLETE")
    print("="*80)
    print(f"✅ Results saved to: {output_path}")
    print()
    print(f"📊 Summary:")
    print(f"   - Analyzed {len(trades)} trades")
    print(f"   - Generated {len(insights)} insights")
    print(f"   - Generated {len(recommendations)} recommendations")
    print("="*80)
    
    return 0

if __name__ == "__main__":
    sys.exit(main())
