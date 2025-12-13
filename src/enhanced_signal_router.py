"""
ENHANCED SIGNAL ROUTER - Bridges New Predictive Engine with Trading Bot
========================================================================
This module integrates the new conviction-based signal system with the
existing bot_cycle.py trading logic.

DESIGN GOALS:
1. Minimal changes to bot_cycle.py - wrap, don't rewrite
2. All trades must pass through conviction gate
3. Log everything for analysis
4. Graceful fallback if new system fails

USAGE:
Replace direct alpha_signals usage with:
    from src.enhanced_signal_router import evaluate_trade_opportunity
    
    result = evaluate_trade_opportunity(symbol, alpha_signals, current_price)
    if result['should_trade']:
        # Execute trade with result['size_multiplier']
    else:
        # Log block reason: result['block_reason']
"""

import json
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, Optional, Tuple

from src.conviction_gate import should_trade as conviction_should_trade
from src.predictive_flow_engine import generate_predictive_signal, get_predictive_engine


def _load_live_intelligence(symbol: str) -> Dict[str, Any]:
    """Load live intelligence data from feature_store for signal generation."""
    intel = {
        'funding_rate': 0.0,
        'oi_delta_pct': 0.0,
        'liquidation_volume': 0.0,
        'whale_net_flow': 0.0,
        'fear_greed': 50.0,
        'sentiment_score': 0.0
    }
    
    try:
        summary_path = Path("feature_store/intelligence/summary.json")
        if summary_path.exists():
            data = json.loads(summary_path.read_text())
            
            if 'funding_rates' in data and symbol in data['funding_rates']:
                intel['funding_rate'] = data['funding_rates'].get(symbol, 0.0)
            
            if 'fear_greed' in data:
                intel['fear_greed'] = data['fear_greed']
            
            if 'signals' in data and symbol in data['signals']:
                sig = data['signals'][symbol]
                intel['taker_ratio'] = sig.get('raw_bs_ratio', 1.0)
    except Exception as e:
        pass
    
    try:
        sentiment_path = Path("feature_store/sentiment/latest.json")
        if sentiment_path.exists():
            data = json.loads(sentiment_path.read_text())
            intel['fear_greed'] = data.get('fear_greed', intel['fear_greed'])
            intel['sentiment_score'] = data.get('sentiment_score', 0.0)
    except:
        pass
    
    try:
        onchain_path = Path("feature_store/onchain/exchange_flows.json")
        if onchain_path.exists():
            data = json.loads(onchain_path.read_text())
            net_flow = data.get('net_inflow', 0) - data.get('net_outflow', 0)
            intel['whale_net_flow'] = net_flow
    except:
        pass
    
    return intel

ROUTER_LOG = Path("logs/signal_router.jsonl")
ROUTER_LOG.parent.mkdir(parents=True, exist_ok=True)

ROUTER_STATS = {
    'evaluated': 0,
    'passed_conviction': 0,
    'blocked_conviction': 0,
    'old_system_would_trade': 0,
    'disagreements': 0
}


def evaluate_trade_opportunity(
    symbol: str,
    alpha_signals: Dict[str, Any],
    current_price: float,
    regime: str = "momentum",
    portfolio_value: float = 10000.0
) -> Dict[str, Any]:
    """
    Evaluate a trade opportunity through the new conviction gate.
    
    This replaces direct alpha signal evaluation with multi-factor
    predictive signal analysis.
    
    Args:
        symbol: Trading symbol (e.g., 'BTCUSDT')
        alpha_signals: Old-style alpha signals from generate_live_alpha_signals
        current_price: Current market price
        regime: Market regime (momentum, choppy, etc.)
        portfolio_value: Current portfolio value for sizing
    
    Returns:
        {
            'should_trade': bool,
            'direction': str,
            'conviction': str,
            'size_multiplier': float,
            'size_usd': float,
            'block_reason': Optional[str],
            'old_system_decision': bool,  # What old system would have done
            'signals': Dict,
            'reasons': list
        }
    """
    global ROUTER_STATS
    ROUTER_STATS['evaluated'] += 1
    
    ofi_value = alpha_signals.get('ofi_value', 0.0)
    old_direction = alpha_signals.get('combined_signal', 'HOLD')
    old_should_enter = alpha_signals.get('should_enter', False)
    
    old_would_trade = old_should_enter and old_direction != 'HOLD'
    if old_would_trade:
        ROUTER_STATS['old_system_would_trade'] += 1
    
    price_1m_ago = alpha_signals.get('price_1m_ago', current_price * 0.999)
    price_direction = 1 if current_price > price_1m_ago else -1 if current_price < price_1m_ago else 0
    
    try:
        engine = get_predictive_engine()
        clean_symbol = symbol.upper().replace('USDT', '').replace('-USDT', '')
        engine.ofi_tracker.record_reading(clean_symbol, ofi_value, current_price)
    except Exception as e:
        pass
    
    intel = _load_live_intelligence(symbol)
    
    should_trade, gate_result = conviction_should_trade(
        symbol=symbol,
        current_ofi=ofi_value,
        current_price=current_price,
        price_direction=price_direction,
        proposed_direction=old_direction if old_direction != 'HOLD' else None
    )
    
    if should_trade:
        ROUTER_STATS['passed_conviction'] += 1
    else:
        ROUTER_STATS['blocked_conviction'] += 1
    
    if old_would_trade != should_trade:
        ROUTER_STATS['disagreements'] += 1
    
    base_size = 200.0
    
    if should_trade:
        size_multiplier = gate_result.get('size_multiplier', 1.0)
        
        if gate_result.get('conviction') == 'ULTRA':
            size_multiplier = min(size_multiplier * 1.5, 3.0)
        
        if regime == 'choppy':
            size_multiplier *= 0.7
    else:
        size_multiplier = 0.0
    
    size_usd = base_size * size_multiplier
    
    result = {
        'should_trade': should_trade,
        'direction': gate_result.get('direction', 'NEUTRAL'),
        'conviction': gate_result.get('conviction', 'NONE'),
        'size_multiplier': size_multiplier,
        'size_usd': size_usd,
        'block_reason': gate_result.get('block_reason'),
        'expected_edge': gate_result.get('expected_edge', 0),
        'weighted_score': gate_result.get('weighted_score', 0),
        'score_breakdown': gate_result.get('score_breakdown', {}),
        'aligned_signals': gate_result.get('aligned_signals', 0),
        'confidence': gate_result.get('confidence', 0),
        'old_system_decision': old_would_trade,
        'old_direction': old_direction,
        'signals': gate_result.get('signals', {}),
        'reasons': gate_result.get('reasons', []),
        'ts': datetime.utcnow().isoformat()
    }
    
    _log_decision(symbol, result, alpha_signals)
    
    return result


def _log_decision(symbol: str, result: Dict, alpha_signals: Dict):
    """Log routing decision for analysis."""
    try:
        log_entry = {
            'ts': result['ts'],
            'symbol': symbol,
            'should_trade': result['should_trade'],
            'direction': result['direction'],
            'conviction': result['conviction'],
            'size_usd': result['size_usd'],
            'block_reason': result['block_reason'],
            'old_would_trade': result['old_system_decision'],
            'old_direction': result['old_direction'],
            'ofi_value': alpha_signals.get('ofi_value', 0),
            'aligned_signals': result['aligned_signals'],
            'expected_edge': result['expected_edge']
        }
        with open(ROUTER_LOG, 'a') as f:
            f.write(json.dumps(log_entry) + '\n')
    except:
        pass


def get_router_stats() -> Dict[str, Any]:
    """Get routing statistics."""
    global ROUTER_STATS
    
    total = ROUTER_STATS['evaluated']
    if total == 0:
        return ROUTER_STATS
    
    return {
        **ROUTER_STATS,
        'pass_rate': ROUTER_STATS['passed_conviction'] / total,
        'block_rate': ROUTER_STATS['blocked_conviction'] / total,
        'disagreement_rate': ROUTER_STATS['disagreements'] / total,
        'selectivity': 1 - (ROUTER_STATS['passed_conviction'] / max(1, ROUTER_STATS['old_system_would_trade']))
    }


def print_router_summary():
    """Print a summary of routing statistics."""
    stats = get_router_stats()
    print("\n" + "=" * 60)
    print("ENHANCED SIGNAL ROUTER - Summary")
    print("=" * 60)
    print(f"Total Evaluated: {stats['evaluated']}")
    print(f"Passed Conviction: {stats['passed_conviction']} ({stats.get('pass_rate', 0):.1%})")
    print(f"Blocked by Conviction: {stats['blocked_conviction']} ({stats.get('block_rate', 0):.1%})")
    print(f"Old System Would Trade: {stats['old_system_would_trade']}")
    print(f"Disagreements: {stats['disagreements']} ({stats.get('disagreement_rate', 0):.1%})")
    print(f"Selectivity Improvement: {stats.get('selectivity', 0):.1%}")
    print("=" * 60)


def enhanced_alpha_entry_wrapper(
    symbol: str,
    alpha_signals: Dict[str, Any],
    current_price: float,
    portfolio_value: float,
    regime: str = "momentum",
    open_order_fn = None
) -> Tuple[bool, Dict[str, Any]]:
    """
    Enhanced wrapper for alpha entries that uses conviction gate.
    
    This can be used as a drop-in replacement for alpha_entry_wrapper
    with additional conviction gating.
    
    Returns:
        (success, telemetry_dict)
    """
    eval_result = evaluate_trade_opportunity(
        symbol=symbol,
        alpha_signals=alpha_signals,
        current_price=current_price,
        regime=regime,
        portfolio_value=portfolio_value
    )
    
    if not eval_result['should_trade']:
        return False, {
            'blocked': True,
            'reason': eval_result['block_reason'],
            'conviction': eval_result['conviction'],
            'old_would_trade': eval_result['old_system_decision']
        }
    
    if open_order_fn is None:
        return True, {
            'dry_run': True,
            'would_execute': True,
            'direction': eval_result['direction'],
            'size_usd': eval_result['size_usd'],
            'conviction': eval_result['conviction']
        }
    
    try:
        direction = eval_result['direction']
        size_usd = eval_result['size_usd']
        
        if size_usd < 200:
            size_usd = 200
        
        position_size = size_usd / current_price if current_price > 0 else 0
        
        order_result = open_order_fn(
            symbol=symbol,
            side=direction,
            strategy_id=f"Enhanced-Alpha-{eval_result['conviction']}",
            notional_usd=size_usd
        )
        
        return True, {
            'executed': True,
            'direction': direction,
            'size_usd': size_usd,
            'position_size': position_size,
            'conviction': eval_result['conviction'],
            'order_result': order_result,
            'aligned_signals': eval_result['aligned_signals'],
            'expected_edge': eval_result['expected_edge']
        }
    except Exception as e:
        return False, {
            'error': str(e),
            'conviction': eval_result['conviction']
        }


def should_skip_trailing_stop(hold_duration_minutes: float, direction: str) -> Tuple[bool, str]:
    """
    Determine if trailing stop should be skipped for long-hold positions.
    
    Based on analysis: trailing stops cause -$349 from 146 exits at 3% WR.
    For positions held 60+ minutes, trailing stops should be disabled.
    
    Returns:
        (should_skip, reason)
    """
    if hold_duration_minutes >= 60:
        return True, f"hold_time_{hold_duration_minutes:.0f}m_exceeds_60m_threshold"
    
    if hold_duration_minutes >= 30:
        return True, f"hold_time_{hold_duration_minutes:.0f}m_trailing_stop_disabled_30m+"
    
    return False, "normal_trailing_stop"


if __name__ == "__main__":
    print("=" * 60)
    print("ENHANCED SIGNAL ROUTER - Test")
    print("=" * 60)
    
    mock_alpha_signals = {
        'ofi_value': 0.5,
        'combined_signal': 'LONG',
        'should_enter': True,
        'arb_opportunity': False
    }
    
    result = evaluate_trade_opportunity(
        symbol='BTCUSDT',
        alpha_signals=mock_alpha_signals,
        current_price=95000.0,
        regime='momentum',
        portfolio_value=10000.0
    )
    
    print(f"\nSymbol: BTCUSDT")
    print(f"Should Trade: {result['should_trade']}")
    print(f"Direction: {result['direction']}")
    print(f"Conviction: {result['conviction']}")
    print(f"Size USD: ${result['size_usd']:.2f}")
    print(f"Block Reason: {result['block_reason']}")
    print(f"Old System Would Trade: {result['old_system_decision']}")
    print(f"Aligned Signals: {result['aligned_signals']}/6")
    
    print_router_summary()
