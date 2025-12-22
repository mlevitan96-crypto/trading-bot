"""
WEIGHTED SIGNAL AGGREGATOR - Continuous Scoring System
=======================================================
Pure weighted scoring - NO BLOCKING GATES.

CORE PRINCIPLES:
1. WEIGHTED SCORING - Each signal contributes weight × confidence × alignment to total score
2. CONTINUOUS SIZING - Score maps to sizing multiplier (0.4x to 2.0x), never blocks
3. TUNABLE WEIGHTS - Adjust signal weights to control sizing, not pass/fail
4. LEARNING INTEGRATION - All decisions logged for weight optimization

WEIGHTED SCORING SYSTEM:
- Each signal has an adjustable weight stored in feature_store/signal_weights.json
- Signal contribution = weight × confidence × direction_alignment
- Composite score = sum of all signal contributions
- Score maps to sizing multiplier via continuous curve

SIZING CURVE (no blocking - all trades execute):
- score >= 0.50 → 2.0x (ultra high conviction)
- score >= 0.35 → 1.5x (high conviction)
- score >= 0.20 → 1.2x (medium conviction)
- score >= 0.10 → 1.0x (baseline)
- score >= 0.00 → 0.6x (low conviction)
- score < 0.00 → 0.4x (minimum - trading against signals)

SAFEGUARDS (applied post-sizing, not blocking):
- $200 minimum position floor (enforced in sizer)
- Kelly ceiling prevents over-sizing
- Exposure caps from risk engine

LEARNING:
- All trade decisions logged with full signal breakdown
- Nightly learner updates weights based on outcome EV
- Historical stats inform sizing adjustments, not blocking
"""

import os
import json
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, Optional, Tuple

from src.predictive_flow_engine import generate_predictive_signal, get_predictive_engine
from src.signal_outcome_tracker import signal_tracker

GATE_LOG = Path("logs/conviction_gate.jsonl")
BLOCKED_COMBOS_FILE = Path("feature_store/blocked_combos.json")
SIGNAL_WEIGHTS_FILE = Path("feature_store/signal_weights.json")
LEARNED_WEIGHTS_FILE = Path("feature_store/signal_weights_gate.json")
TRADING_CONFIG_FILE = Path("configs/trading_config.json")
GATE_LOG.parent.mkdir(parents=True, exist_ok=True)

FEE_RATE = 0.0008
SLIPPAGE_ESTIMATE = 0.0005
MIN_EXPECTED_EDGE = 0.002

DEFAULT_SIGNAL_WEIGHTS = {
    'liquidation': 0.22,
    'funding': 0.16,
    'oi_velocity': 0.05,
    'whale_flow': 0.20,
    'ofi_momentum': 0.06,
    'fear_greed': 0.06,
    'hurst': 0.08,
    'lead_lag': 0.08,
    'volatility_skew': 0.05,  # Loss aversion / complacency detection
    'oi_divergence': 0.04     # Price/OI trap detection
}

# DIRECTION-SPECIFIC SIGNAL ROUTING
# Now managed by RegimeDirectionRouter for dynamic adaptation
# The router tracks rolling window EV by signal×direction and auto-adjusts
# See src/regime_direction_router.py for implementation

# Fallback static rules (used if router not available)
STATIC_DIRECTION_RULES = {
    'funding': ['SHORT'],
    'liquidation': ['SHORT'],
    'hurst': ['SHORT'],
    'whale_flow': ['SHORT'],
    'lead_lag': ['LONG'],
    'oi_velocity': None,
    'ofi_momentum': None,
    'fear_greed': None,
    'volatility_skew': [],
    'oi_divergence': None,
}

# Track when direction routing was applied for learning
DIRECTION_ROUTING_LOG = Path("logs/direction_routing.jsonl")


def _get_signal_direction_rules(signal_name: str):
    """
    Get allowed directions for a signal from the dynamic router.
    Falls back to static rules if router unavailable.
    """
    try:
        from src.regime_direction_router import get_allowed_directions
        directions = get_allowed_directions(signal_name)
        return directions
    except ImportError:
        return STATIC_DIRECTION_RULES.get(signal_name)
    except Exception:
        return STATIC_DIRECTION_RULES.get(signal_name)

SCORE_TO_SIZING_CURVE = {
    'ULTRA': {'min_score': 0.50, 'multiplier': 2.0},
    'HIGH': {'min_score': 0.35, 'multiplier': 1.5},
    'MEDIUM': {'min_score': 0.20, 'multiplier': 1.2},
    'BASELINE': {'min_score': 0.10, 'multiplier': 1.0},
    'LOW': {'min_score': 0.00, 'multiplier': 0.6},
    'MINIMUM': {'min_score': -999, 'multiplier': 0.4}
}

STRICT_SCORE_THRESHOLDS = {
    'ULTRA': 0.50,
    'HIGH': 0.35,
    'MEDIUM': 0.20,
    'LOW': 0.10
}

RELAXED_SCORE_THRESHOLDS = {
    'ULTRA': 0.50,
    'HIGH': 0.35,
    'MEDIUM': 0.20,
    'LOW': 0.10
}

KILLED_COMBOS = set()
SIGNAL_WEIGHTS = DEFAULT_SIGNAL_WEIGHTS.copy()


def _load_trading_config() -> Dict[str, Any]:
    """Load trading configuration from file."""
    try:
        if TRADING_CONFIG_FILE.exists():
            return json.loads(TRADING_CONFIG_FILE.read_text())
    except Exception as e:
        print(f"[ConvictionGate] Error loading trading config: {e}")
    return {}


def _get_paper_mode() -> bool:
    """
    Determine if we're in paper trading mode.
    
    Priority:
    1. Environment variable TRADING_MODE ('paper' or 'live')
    2. Config file configs/trading_config.json mode field
    3. Default: True (paper mode for safety)
    """
    env_mode = os.environ.get('TRADING_MODE', '').lower()
    if env_mode in ('paper', 'live'):
        return env_mode == 'paper'
    
    config = _load_trading_config()
    mode = config.get('mode', 'paper').lower()
    return mode == 'paper'


def _get_score_thresholds() -> Dict[str, float]:
    """Get score thresholds based on trading mode."""
    if _get_paper_mode():
        config = _load_trading_config()
        paper_thresholds = config.get('thresholds', {}).get('paper', {}).get('score_thresholds', {})
        if paper_thresholds:
            return {k: float(v) for k, v in paper_thresholds.items()}
        return RELAXED_SCORE_THRESHOLDS.copy()
    else:
        config = _load_trading_config()
        live_thresholds = config.get('thresholds', {}).get('live', {}).get('score_thresholds', {})
        if live_thresholds:
            return {k: float(v) for k, v in live_thresholds.items()}
        return STRICT_SCORE_THRESHOLDS.copy()


PAPER_MODE = _get_paper_mode()
SCORE_THRESHOLDS = _get_score_thresholds()

_mode_logged = False
def _log_mode_once():
    """Log the current trading mode once at startup."""
    global _mode_logged
    if not _mode_logged:
        mode_str = "PAPER (relaxed thresholds)" if PAPER_MODE else "LIVE (strict thresholds)"
        print(f"[ConvictionGate] Running in {mode_str} mode")
        print(f"[ConvictionGate] Score thresholds: ULTRA={SCORE_THRESHOLDS['ULTRA']:.2f}, HIGH={SCORE_THRESHOLDS['HIGH']:.2f}, MEDIUM={SCORE_THRESHOLDS['MEDIUM']:.2f}, LOW={SCORE_THRESHOLDS['LOW']:.2f}")
        _mode_logged = True


def _load_signal_weights():
    """
    Load learnable signal weights from file.
    
    Priority:
    1. Learned weights from signal_weights_gate.json (auto-updated by learner)
    2. Manual weights from signal_weights.json
    3. Default weights
    """
    global SIGNAL_WEIGHTS
    weights_loaded = False
    
    try:
        if LEARNED_WEIGHTS_FILE.exists():
            data = json.loads(LEARNED_WEIGHTS_FILE.read_text())
            weights = data.get('weights', {})
            if weights:
                for key in DEFAULT_SIGNAL_WEIGHTS:
                    if key in weights:
                        SIGNAL_WEIGHTS[key] = float(weights[key])
                weights_loaded = True
                print(f"[ConvictionGate] Loaded learned weights from {LEARNED_WEIGHTS_FILE.name}")
    except Exception as e:
        print(f"[ConvictionGate] Error loading learned weights: {e}")
    
    if not weights_loaded:
        try:
            if SIGNAL_WEIGHTS_FILE.exists():
                data = json.loads(SIGNAL_WEIGHTS_FILE.read_text())
                weights = data.get('weights', {})
                for key in DEFAULT_SIGNAL_WEIGHTS:
                    if key in weights:
                        SIGNAL_WEIGHTS[key] = float(weights[key])
        except:
            pass


def reload_signal_weights():
    """Reload signal weights from file (called periodically to pick up learned updates)."""
    _load_signal_weights()


_load_signal_weights()


def _load_killed_combos():
    """Load combos that should never be traded."""
    global KILLED_COMBOS
    
    if BLOCKED_COMBOS_FILE.exists():
        try:
            data = json.loads(BLOCKED_COMBOS_FILE.read_text())
            KILLED_COMBOS = set(data.get('killed', []))
        except:
            pass
    
    try:
        rules_file = Path("feature_store/daily_learning_rules.json")
        if rules_file.exists():
            rules = json.loads(rules_file.read_text())
            patterns = rules.get('patterns', {})
            
            for pattern_key, pattern_data in patterns.items():
                if isinstance(pattern_data, dict):
                    trades = pattern_data.get('trades', 0)
                    win_rate = pattern_data.get('win_rate', 0.5)
                    avg_pnl = pattern_data.get('avg_pnl', 0)
                    
                    if trades >= 50 and win_rate < 0.35 and avg_pnl < -0.5:
                        parts = pattern_key.split('_')
                        if len(parts) >= 2:
                            symbol = parts[0]
                            direction = parts[1].upper()
                            KILLED_COMBOS.add(f"{symbol}_{direction}")
    except:
        pass


_load_killed_combos()


def reload_config():
    """Reload configuration at runtime (useful for mode changes)."""
    global PAPER_MODE, SCORE_THRESHOLDS, _mode_logged
    PAPER_MODE = _get_paper_mode()
    SCORE_THRESHOLDS = _get_score_thresholds()
    _mode_logged = False
    _log_mode_once()


class ConvictionGate:
    """
    Weighted Signal Aggregator - Pure Continuous Scoring.
    
    Combines predictive signals with learnable weights to produce
    a composite score that drives sizing decisions. NO BLOCKING.
    
    All trades execute - low scores mean smaller positions.
    """
    
    MIN_TRADES_FOR_STATS = 30
    
    SCORE_TO_SIZE_CURVE = [
        (0.50, 2.0, 'ULTRA'),
        (0.35, 1.5, 'HIGH'),
        (0.20, 1.2, 'MEDIUM'),
        (0.10, 1.0, 'BASELINE'),
        (0.00, 0.6, 'LOW'),
        (-999, 0.4, 'MINIMUM')
    ]
    
    def __init__(self):
        self.engine = get_predictive_engine()
        self.decision_count = 0
        self.trade_count = 0
        self.block_count = 0
        _log_mode_once()
    
    def _get_historical_stats(self, symbol: str, direction: str) -> Dict[str, Any]:
        """Get historical performance for symbol+direction combo."""
        try:
            rules_file = Path("feature_store/daily_learning_rules.json")
            if rules_file.exists():
                rules = json.loads(rules_file.read_text())
                patterns = rules.get('patterns', {})
                
                pattern_key = f"{symbol}_{direction.lower()}"
                for key, data in patterns.items():
                    if key.startswith(pattern_key):
                        return {
                            'trades': data.get('trades', 0),
                            'win_rate': data.get('win_rate', 0.5),
                            'avg_pnl': data.get('avg_pnl', 0),
                            'has_data': True
                        }
        except:
            pass
        
        return {
            'trades': 0,
            'win_rate': 0.5,
            'avg_pnl': 0,
            'has_data': False
        }
    
    def _calculate_expected_value(self, win_rate: float, avg_win: float = 0.01, 
                                  avg_loss: float = 0.008) -> float:
        """Calculate expected value after fees and slippage."""
        gross_ev = (win_rate * avg_win) - ((1 - win_rate) * avg_loss)
        net_ev = gross_ev - FEE_RATE - SLIPPAGE_ESTIMATE
        return net_ev
    
    def _is_killed_combo(self, symbol: str, direction: str) -> bool:
        """Check if this combo should be killed."""
        combo_key = f"{symbol}_{direction.upper()}"
        return combo_key in KILLED_COMBOS
    
    def _calculate_weighted_score(self, signals: Dict[str, Any], direction: str, 
                                  symbol: str = '', current_price: float = 0.0) -> Tuple[float, Dict[str, float]]:
        """
        Calculate weighted score for a proposed direction.
        
        DIRECTION-SPECIFIC ROUTING (2025-12-05):
        - Signals only contribute to score if the PROPOSED trade direction
          matches the signal's profitable direction from EWMA analysis
        - e.g., funding only counts for SHORT trades (where it has +15bps EV)
        - Signals are STILL TRACKED even when filtered for learning
        
        Returns:
            (total_score, breakdown_dict)
        """
        breakdown = {}
        total_score = 0.0
        direction_filtered = {}  # Track what was filtered for learning
        
        signal_map = {
            'liquidation': signals.get('liquidation', {}),
            'funding': signals.get('funding', {}),
            'oi_velocity': signals.get('oi_velocity', {}),
            'whale_flow': signals.get('whale_flow', {}),
            'ofi_momentum': signals.get('ofi_momentum', {}),
            'fear_greed': signals.get('fear_greed', {}),
            'hurst': signals.get('hurst', {}),
            'lead_lag': signals.get('lead_lag', {}),
            'volatility_skew': signals.get('volatility_skew', {}),
            'oi_divergence': signals.get('oi_divergence', {})
        }
        
        for signal_name, signal_data in signal_map.items():
            weight = SIGNAL_WEIGHTS.get(signal_name, 0.1)
            confidence = signal_data.get('confidence', 0.0)
            signal_direction = signal_data.get('signal', 'NEUTRAL')
            
            # DIRECTION-SPECIFIC ROUTING CHECK (now dynamic via RegimeDirectionRouter)
            # Check if this signal should contribute to score for this trade direction
            allowed_directions = _get_signal_direction_rules(signal_name)
            direction_allowed = True
            
            if allowed_directions is not None:
                if allowed_directions == []:  # Signal disabled
                    direction_allowed = False
                    direction_filtered[signal_name] = 'disabled'
                elif direction not in allowed_directions:
                    # Signal doesn't work for this trade direction
                    direction_allowed = False
                    direction_filtered[signal_name] = f'only_works_{allowed_directions}'
            
            if signal_direction in ('LONG', 'STRONG_LONG'):
                alignment = 1 if direction == 'LONG' else -1
            elif signal_direction in ('SHORT', 'STRONG_SHORT'):
                alignment = 1 if direction == 'SHORT' else -1
            else:
                alignment = 0
            
            if 'STRONG' in str(signal_direction):
                confidence = min(1.0, confidence * 1.3)
            
            # Calculate contribution (but only add to score if direction allowed)
            raw_contribution = weight * confidence * alignment
            
            if direction_allowed:
                contribution = raw_contribution
            else:
                contribution = 0.0  # Don't count signal for wrong direction
            
            breakdown[signal_name] = round(contribution, 4)
            total_score += contribution
            
            # ALWAYS log signals for outcome tracking (even when filtered)
            if symbol and current_price > 0 and confidence > 0:
                try:
                    signal_tracker.log_signal(
                        symbol=symbol,
                        signal_name=signal_name,
                        direction=signal_direction,
                        confidence=confidence,
                        price=current_price,
                        signal_data=signal_data
                    )
                except Exception as e:
                    pass
        
        # Log direction routing decisions for learning
        if direction_filtered and symbol:
            self._log_direction_routing(symbol, direction, direction_filtered, breakdown)
        
        cascade_active = signals.get('liquidation', {}).get('cascade_active', False)
        if cascade_active:
            total_score *= 1.2
            breakdown['cascade_boost'] = round(total_score * 0.2, 4)
        
        return round(total_score, 4), breakdown
    
    def _log_direction_routing(self, symbol: str, direction: str, 
                               filtered: Dict[str, str], breakdown: Dict[str, float]):
        """Log direction routing decisions for learning verification."""
        try:
            entry = {
                'ts': datetime.utcnow().isoformat(),
                'symbol': symbol,
                'direction': direction,
                'signals_filtered': filtered,
                'final_breakdown': breakdown
            }
            with open(DIRECTION_ROUTING_LOG, 'a') as f:
                f.write(json.dumps(entry) + '\n')
        except:
            pass
    
    def _score_to_conviction_and_size(self, score: float) -> Tuple[str, float]:
        """
        Convert weighted score to conviction level AND sizing multiplier.
        
        Uses continuous curve - never returns REJECT.
        All scores map to a sizing multiplier (0.4x to 2.0x).
        """
        for min_score, multiplier, level in self.SCORE_TO_SIZE_CURVE:
            if score >= min_score:
                return level, multiplier
        return 'MINIMUM', 0.4
    
    def evaluate(self, symbol: str, current_ofi: float = 0.0, 
                 current_price: float = 0.0,
                 price_direction: int = 0,
                 proposed_direction: Optional[str] = None) -> Dict[str, Any]:
        """
        Evaluate trade opportunity with WEIGHTED SCORING - NO BLOCKING.
        
        All trades execute. Composite score determines sizing only.
        
        Args:
            symbol: Trading symbol (e.g., 'BTCUSDT')
            current_ofi: Current order flow imbalance
            current_price: Current price
            price_direction: Recent price direction (1=up, -1=down)
            proposed_direction: If provided, evaluate this specific direction
        
        Returns:
            {
                'should_trade': True (always - no blocking),
                'direction': str,
                'conviction': str (ULTRA/HIGH/MEDIUM/BASELINE/LOW/MINIMUM),
                'size_multiplier': float (0.4x to 2.0x based on score),
                'composite_score': float (the weighted total),
                'expected_edge': float,
                'signals': Dict,
                'reasons': list
            }
        """
        self.decision_count += 1
        
        clean_symbol = symbol.replace('USDT', '').replace('-USDT', '')
        
        prediction = generate_predictive_signal(
            clean_symbol, current_ofi, current_price, price_direction
        )
        
        direction = proposed_direction or prediction['direction']
        
        if direction == 'NEUTRAL':
            direction = 'LONG' if current_ofi > 0 else 'SHORT' if current_ofi < 0 else 'LONG'
        
        signals = prediction.get('signals', {})
        weighted_score, score_breakdown = self._calculate_weighted_score(
            signals, direction, symbol=symbol, current_price=current_price
        )
        
        conviction, base_size_mult = self._score_to_conviction_and_size(weighted_score)
        
        hist_stats = self._get_historical_stats(clean_symbol, direction)
        if hist_stats['has_data']:
            expected_edge = self._calculate_expected_value(hist_stats['win_rate'])
            hist_adjustment = self._calculate_historical_adjustment(hist_stats)
            base_size_mult *= hist_adjustment
            score_breakdown['hist_adjustment'] = hist_adjustment
            score_breakdown['hist_win_rate'] = hist_stats['win_rate']
        else:
            expected_edge = prediction['confidence'] * 0.01 - FEE_RATE - SLIPPAGE_ESTIMATE
        
        if expected_edge > 0.005:
            base_size_mult *= 1.15
            score_breakdown['edge_boost'] = 1.15
        
        if prediction['signals'].get('liquidation', {}).get('cascade_active'):
            base_size_mult *= 1.25
            score_breakdown['cascade_boost'] = 1.25
            if conviction in ('HIGH', 'MEDIUM'):
                conviction = 'ULTRA'
        
        try:
            from src.regime_bias_multiplier import calculate_regime_size_multiplier
            active_signals = [s for s, data in signals.items() 
                             if isinstance(data, dict) and data.get('confidence', 0) > 0.3]
            regime_mult, regime_details = calculate_regime_size_multiplier(
                clean_symbol, direction, active_signals, conviction
            )
            base_size_mult *= regime_mult
            score_breakdown['regime_bias_mult'] = regime_mult
            score_breakdown['regime_direction_ev'] = regime_details.get('direction_ev', 0)
            score_breakdown['trading_with_regime'] = regime_details.get('trading_with_regime', False)
        except Exception:
            pass
        
        size_multiplier = max(0.4, min(2.5, base_size_mult))
        
        # ====================================================================
        # OFI THRESHOLD ENFORCEMENT (Based on Learning Analysis)
        # ====================================================================
        # Key Finding: LONG trades with OFI < 0.5 are losing money
        # Solution: Require OFI ≥ 0.5 for LONG trades (match SHORT requirements)
        # ====================================================================
        should_trade = True
        block_reason = None
        
        # Get OFI threshold from signal policies
        try:
            from pathlib import Path
            import json as json_mod
            signal_policy_path = Path("configs/signal_policies.json")
            if signal_policy_path.exists():
                with open(signal_policy_path, 'r') as f:
                    policy_data = json_mod.load(f)
                    alpha_policy = policy_data.get("alpha_trading", {})
                    
                    # Get direction-specific OFI requirement
                    long_ofi_req = alpha_policy.get("long_ofi_requirement", alpha_policy.get("ofi_threshold", 0.5))
                    short_ofi_req = alpha_policy.get("short_ofi_requirement", alpha_policy.get("ofi_threshold", 0.5))
                    min_ofi = alpha_policy.get("min_ofi_confidence", 0.5)
                    
                    # Use direction-specific threshold
                    required_ofi = long_ofi_req if direction.upper() == "LONG" else short_ofi_req
                    ofi_abs = abs(current_ofi)
                    
                    # Enforce OFI threshold
                    if ofi_abs < required_ofi:
                        should_trade = False
                        block_reason = f"OFI {ofi_abs:.3f} below required {required_ofi:.3f} for {direction}"
                        score_breakdown['ofi_block'] = f"OFI {ofi_abs:.3f} < {required_ofi:.3f}"
        except Exception as e:
            # If policy load fails, use default threshold
            ofi_abs = abs(current_ofi)
            if ofi_abs < 0.5:
                should_trade = False
                block_reason = f"OFI {ofi_abs:.3f} below minimum 0.5 (policy load failed, using default)"
        
        self.trade_count += 1
        
        result = self._build_result(
            should_trade,
            direction, conviction, size_multiplier,
            expected_edge, block_reason, prediction, prediction['reasons'],
            weighted_score, score_breakdown
        )
        self._log_decision(symbol, result)
        
        return result
    
    def _calculate_historical_adjustment(self, hist_stats: Dict[str, Any]) -> float:
        """
        Calculate sizing adjustment based on historical performance.
        
        NOT a gate - just adjusts sizing up/down based on track record.
        """
        if not hist_stats['has_data'] or hist_stats['trades'] < self.MIN_TRADES_FOR_STATS:
            return 1.0
        
        win_rate = hist_stats['win_rate']
        
        if win_rate >= 0.55:
            return 1.3
        elif win_rate >= 0.45:
            return 1.1
        elif win_rate >= 0.35:
            return 0.8
        elif win_rate >= 0.25:
            return 0.5
        else:
            return 0.4
    
    def _build_result(self, should_trade: bool, direction: str, conviction: str,
                     size_multiplier: float, expected_edge: float,
                     block_reason: Optional[str], prediction: Dict,
                     reasons: list, weighted_score: float = 0.0,
                     score_breakdown: Optional[Dict[str, float]] = None) -> Dict[str, Any]:
        """Build the result dictionary."""
        return {
            'should_trade': should_trade,
            'direction': direction,
            'conviction': conviction,
            'size_multiplier': size_multiplier,
            'expected_edge': round(expected_edge, 5),
            'block_reason': block_reason,
            'weighted_score': weighted_score,
            'score_breakdown': score_breakdown or {},
            'aligned_signals': prediction.get('aligned_signals', 0),
            'confidence': prediction.get('confidence', 0),
            'signals': prediction.get('signals', {}),
            'reasons': reasons[:10],
            'paper_mode': PAPER_MODE,
            'ts': datetime.utcnow().isoformat()
        }
    
    def _log_decision(self, symbol: str, result: Dict):
        """Log the decision for analysis."""
        try:
            log_entry = {
                'symbol': symbol,
                'ts': result['ts'],
                'should_trade': result['should_trade'],
                'direction': result['direction'],
                'conviction': result['conviction'],
                'size_multiplier': result['size_multiplier'],
                'expected_edge': result['expected_edge'],
                'block_reason': result['block_reason'],
                'weighted_score': result.get('weighted_score', 0),
                'score_breakdown': result.get('score_breakdown', {}),
                'paper_mode': PAPER_MODE
            }
            with open(GATE_LOG, 'a') as f:
                f.write(json.dumps(log_entry) + '\n')
            
            # Also log blocked signals for counterfactual analysis
            if not result['should_trade'] and result['block_reason']:
                self._log_blocked_signal(symbol, result)
        except:
            pass
    
    def _log_blocked_signal(self, symbol: str, result: Dict):
        """Log blocked signals with full context for learning."""
        try:
            blocked_entry = {
                'ts': result['ts'],
                'symbol': symbol,
                'direction': result['direction'],
                'block_reason': result['block_reason'],
                'weighted_score': result.get('weighted_score', 0),
                'expected_edge': result['expected_edge'],
                'score_breakdown': result.get('score_breakdown', {}),
                'signals': {k: {'direction': v.get('signal'), 'confidence': v.get('confidence', 0)} 
                           for k, v in result.get('signals', {}).items() if isinstance(v, dict)},
                'price_at_block': None,  # Will be filled by tracker
                'paper_mode': PAPER_MODE
            }
            blocked_log = 'logs/blocked_signals.jsonl'
            with open(blocked_log, 'a') as f:
                f.write(json.dumps(blocked_entry) + '\n')
        except Exception as e:
            pass
    
    def get_stats(self) -> Dict[str, Any]:
        """Get gate statistics."""
        return {
            'decisions': self.decision_count,
            'trades_allowed': self.trade_count,
            'trades_blocked': self.block_count,
            'block_rate': self.block_count / max(1, self.decision_count),
            'killed_combos': len(KILLED_COMBOS),
            'paper_mode': PAPER_MODE,
            'score_thresholds': SCORE_THRESHOLDS
        }
    
    def is_paper_mode(self) -> bool:
        """Check if running in paper mode."""
        return PAPER_MODE


_gate_instance = None

def get_conviction_gate() -> ConvictionGate:
    """Get singleton gate instance."""
    global _gate_instance
    if _gate_instance is None:
        _gate_instance = ConvictionGate()
    return _gate_instance


def should_trade(symbol: str, current_ofi: float = 0.0, 
                current_price: float = 0.0,
                price_direction: int = 0,
                proposed_direction: Optional[str] = None) -> Tuple[bool, Dict[str, Any]]:
    """
    Convenience function to check if a trade should be taken.
    
    Returns:
        (should_trade, full_evaluation_result)
    """
    gate = get_conviction_gate()
    result = gate.evaluate(
        symbol, current_ofi, current_price, price_direction, proposed_direction
    )
    return result['should_trade'], result


def get_trade_size_multiplier(symbol: str, direction: str, 
                              base_size: float = 200.0,
                              ofi: float = 0.0,
                              price: float = 0.0) -> Tuple[float, str, Dict]:
    """
    Get the recommended trade size based on weighted scoring.
    
    Always returns a positive size (no blocking).
    
    Returns:
        (recommended_size, conviction_level, full_result)
    """
    gate = get_conviction_gate()
    result = gate.evaluate(symbol, ofi, price, 0, direction)
    
    recommended_size = base_size * result['size_multiplier']
    return recommended_size, result['conviction'], result


def is_paper_mode() -> bool:
    """Check if running in paper mode."""
    return PAPER_MODE


if __name__ == "__main__":
    print("=" * 60)
    print("CONVICTION GATE - Test")
    print("=" * 60)
    
    print(f"\nPaper Mode: {PAPER_MODE}")
    print(f"Score Thresholds: {SCORE_THRESHOLDS}")
    
    gate = get_conviction_gate()
    
    test_cases = [
        ('BTC', 0.5, 95000, 1),
        ('ETH', -0.3, 3500, -1),
        ('SOL', 0.8, 200, 0),
    ]
    
    for symbol, ofi, price, price_dir in test_cases:
        result = gate.evaluate(symbol, ofi, price, price_dir)
        print(f"\n{symbol}USDT:")
        print(f"  Should Trade: {result['should_trade']}")
        print(f"  Direction: {result['direction']}")
        print(f"  Conviction: {result['conviction']}")
        print(f"  Size Multiplier: {result['size_multiplier']}")
        print(f"  Expected Edge: {result['expected_edge']:.4f}")
        print(f"  Paper Mode: {result['paper_mode']}")
        if result['block_reason']:
            print(f"  Block Reason: {result['block_reason']}")
    
    print("\n" + "=" * 60)
    print("Gate Stats:")
    stats = gate.get_stats()
    for key, value in stats.items():
        print(f"  {key}: {value}")
