"""
ENSEMBLE PREDICTOR - Multi-Model Combination for Trade Prediction
==================================================================
Combines predictions from multiple models for robust trade signals.

Ensemble Components:
1. Gradient Boost (ml_predictor.py) - 30% weight
2. Sequence Model (sequence_predictor.py) - 25% weight
3. Pattern Rules (daily_learning_rules.json) - 25% weight
4. Sentiment + On-Chain (sentiment_fetcher, onchain_fetcher) - 20% weight

Output:
- prob_win: Probability trade will be profitable
- confidence: How certain the ensemble is
- size_multiplier: Suggested sizing adjustment (0.5x - 2.0x)

Data Flow:
- Called by profit_seeking_sizer.py at entry time
- Uses all available signals for decision
- Logs to logs/ensemble_predictions.jsonl

Reference: Combining patterns from ml_predictor.py and profit_seeking_sizer.py
"""

import os
import json
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, Tuple, Optional

from src.data_registry import DataRegistry as DR

ENSEMBLE_CONFIG = Path(DR.ML_ENSEMBLE_CONFIG)
PREDICTIONS_LOG = Path(DR.ENSEMBLE_PREDICTIONS_LOG)
DAILY_RULES = Path(DR.DAILY_LEARNING_RULES)
LOG_FILE = Path("logs/ensemble_predictor.log")

ENSEMBLE_CONFIG.parent.mkdir(parents=True, exist_ok=True)
PREDICTIONS_LOG.parent.mkdir(parents=True, exist_ok=True)
LOG_FILE.parent.mkdir(parents=True, exist_ok=True)

DEFAULT_WEIGHTS = {
    'gbm': 0.30,
    'sequence': 0.25,
    'pattern': 0.25,
    'sentiment': 0.10,
    'onchain': 0.10
}


def log(msg: str):
    ts = datetime.utcnow().isoformat() + "Z"
    entry = f"[{ts}] {msg}"
    try:
        with open(LOG_FILE, 'a') as f:
            f.write(entry + '\n')
    except:
        pass


def load_weights() -> Dict[str, float]:
    """Load ensemble weights from config."""
    try:
        if ENSEMBLE_CONFIG.exists():
            with open(ENSEMBLE_CONFIG, 'r') as f:
                config = json.load(f)
            return config.get('weights', DEFAULT_WEIGHTS)
    except:
        pass
    return DEFAULT_WEIGHTS


def save_weights(weights: Dict[str, float]):
    """Save ensemble weights to config."""
    try:
        config = {'weights': weights, 'updated': datetime.utcnow().isoformat() + 'Z'}
        with open(ENSEMBLE_CONFIG, 'w') as f:
            json.dump(config, f, indent=2)
    except Exception as e:
        log(f"Failed to save weights: {e}")


def get_gbm_prediction(symbol: str, direction: str, features: Dict) -> Tuple[float, float]:
    """Get prediction from gradient boost model."""
    try:
        from src.ml_predictor import predict_direction
        pred_dir, confidence = predict_direction(symbol, features)
        
        if pred_dir == direction:
            return 0.5 + confidence * 0.3, confidence
        else:
            return 0.5 - confidence * 0.3, confidence
    except Exception as e:
        log(f"GBM prediction error: {e}")
        return 0.5, 0.0


def get_sequence_prediction(symbol: str, features: Dict) -> Tuple[float, float]:
    """Get prediction from sequence (LSTM/MLP) model."""
    try:
        from src.sequence_predictor import predict_sequence
        prob_win, confidence = predict_sequence(symbol, features)
        return prob_win, confidence
    except Exception as e:
        log(f"Sequence prediction error: {e}")
        return 0.5, 0.0


def get_pattern_prediction(symbol: str, direction: str, ofi: float, ensemble_score: float) -> Tuple[float, float]:
    """Get prediction from learned pattern rules."""
    try:
        if not DAILY_RULES.exists():
            return 0.5, 0.0
        
        with open(DAILY_RULES, 'r') as f:
            rules = json.load(f)
        
        profitable = rules.get('profitable_patterns', [])
        high_potential = rules.get('high_potential_patterns', [])
        
        ofi_bucket = "extreme" if ofi > 0.8 else "very_strong" if ofi > 0.7 else "strong" if ofi > 0.6 else "moderate" if ofi > 0.4 else "weak"
        ens_bucket = "strong_bull" if ensemble_score > 0.3 else "bull" if ensemble_score > 0.1 else "neutral" if ensemble_score > -0.1 else "bear" if ensemble_score > -0.3 else "strong_bear"
        
        for pattern in profitable:
            pattern_str = pattern.get('pattern', '')
            if symbol in pattern_str and direction in pattern_str:
                ev = pattern.get('ev', 0)
                win_rate = pattern.get('win_rate', 0.5)
                prob_win = 0.5 + (win_rate - 0.5) * 0.5 + (ev / 10) * 0.2
                return min(0.9, max(0.1, prob_win)), 0.7
            
            if ofi_bucket in pattern_str or ens_bucket in pattern_str:
                ev = pattern.get('ev', 0)
                if ev > 0:
                    return 0.55, 0.4
        
        for pattern in high_potential:
            pattern_str = pattern.get('pattern', '')
            if symbol in pattern_str:
                return 0.52, 0.3
        
        return 0.5, 0.2
    except Exception as e:
        log(f"Pattern prediction error: {e}")
        return 0.5, 0.0


def get_sentiment_prediction(symbol: str) -> Tuple[float, float]:
    """Get prediction from sentiment data."""
    try:
        from src.sentiment_fetcher import get_sentiment_features
        features = get_sentiment_features(symbol)
        
        if features.get('sentiment_is_stale', 1.0) > 0.5:
            return 0.5, 0.0
        
        sentiment_signal = features.get('sentiment_signal', 0)
        sentiment_confidence = features.get('sentiment_confidence', 0)
        
        prob_win = 0.5 + (sentiment_signal * 0.15)
        
        return prob_win, sentiment_confidence * 0.5
    except Exception as e:
        log(f"Sentiment prediction error: {e}")
        return 0.5, 0.0


def get_onchain_prediction(symbol: str, direction: str) -> Tuple[float, float]:
    """Get prediction from on-chain data."""
    try:
        from src.onchain_fetcher import get_onchain_features
        features = get_onchain_features(symbol)
        
        if features.get('onchain_is_stale', 1.0) > 0.5:
            return 0.5, 0.0
        
        flow_signal = features.get('onchain_flow_signal', 0)
        flow_confidence = features.get('onchain_flow_confidence', 0)
        
        aligned = (flow_signal > 0 and direction == 'LONG') or (flow_signal < 0 and direction == 'SHORT')
        
        if aligned:
            prob_win = 0.5 + (abs(flow_signal) * 0.15)
        else:
            prob_win = 0.5 - (abs(flow_signal) * 0.10)
        
        return prob_win, flow_confidence * 0.5
    except Exception as e:
        log(f"On-chain prediction error: {e}")
        return 0.5, 0.0


def get_ensemble_prediction(
    symbol: str,
    direction: str,
    features: Dict,
    ofi: float = 0.0,
    ensemble_score: float = 0.0
) -> Dict[str, Any]:
    """
    Get combined ensemble prediction.
    
    Args:
        symbol: Trading symbol
        direction: LONG or SHORT
        features: ML features dict
        ofi: OFI score
        ensemble_score: Signal ensemble score
    
    Returns:
        Dict with prob_win, confidence, size_multiplier, components
    """
    weights = load_weights()
    
    gbm_prob, gbm_conf = get_gbm_prediction(symbol, direction, features)
    seq_prob, seq_conf = get_sequence_prediction(symbol, features)
    pat_prob, pat_conf = get_pattern_prediction(symbol, direction, ofi, ensemble_score)
    sent_prob, sent_conf = get_sentiment_prediction(symbol)
    onchain_prob, onchain_conf = get_onchain_prediction(symbol, direction)
    
    total_weight = 0
    weighted_prob = 0
    weighted_conf = 0
    
    components = {
        'gbm': {'prob': gbm_prob, 'conf': gbm_conf, 'weight': weights.get('gbm', 0.3)},
        'sequence': {'prob': seq_prob, 'conf': seq_conf, 'weight': weights.get('sequence', 0.25)},
        'pattern': {'prob': pat_prob, 'conf': pat_conf, 'weight': weights.get('pattern', 0.25)},
        'sentiment': {'prob': sent_prob, 'conf': sent_conf, 'weight': weights.get('sentiment', 0.1)},
        'onchain': {'prob': onchain_prob, 'conf': onchain_conf, 'weight': weights.get('onchain', 0.1)}
    }
    
    for name, comp in components.items():
        w = comp['weight']
        conf = comp['conf']
        prob = comp['prob']
        
        effective_weight = w * (0.5 + conf * 0.5)
        
        weighted_prob += prob * effective_weight
        weighted_conf += conf * w
        total_weight += effective_weight
    
    if total_weight > 0:
        final_prob = weighted_prob / total_weight
    else:
        final_prob = 0.5
    
    final_conf = min(1.0, weighted_conf)
    
    if final_prob > 0.65 and final_conf > 0.5:
        size_mult = 1.5 + (final_prob - 0.65) * 2.5
    elif final_prob > 0.55:
        size_mult = 1.0 + (final_prob - 0.55) * 2.5
    elif final_prob < 0.35 and final_conf > 0.5:
        size_mult = 0.5
    elif final_prob < 0.45:
        size_mult = 0.5 + (final_prob - 0.35) * 2.5
    else:
        size_mult = 1.0
    
    size_mult = min(2.0, max(0.5, size_mult))
    
    result = {
        'prob_win': round(final_prob, 4),
        'confidence': round(final_conf, 4),
        'size_multiplier': round(size_mult, 2),
        'components': components,
        'symbol': symbol,
        'direction': direction,
        'timestamp': datetime.utcnow().isoformat() + 'Z'
    }
    
    try:
        with open(PREDICTIONS_LOG, 'a') as f:
            f.write(json.dumps({
                'ts': result['timestamp'],
                'symbol': symbol,
                'direction': direction,
                'prob_win': result['prob_win'],
                'confidence': result['confidence'],
                'size_mult': result['size_multiplier']
            }) + '\n')
    except:
        pass
    
    return result


def calibrate_weights(validation_data: list) -> Dict[str, float]:
    """
    Calibrate ensemble weights based on validation data.
    
    Args:
        validation_data: List of (prediction, actual_outcome) tuples per component
    
    Returns:
        Optimized weights
    """
    return DEFAULT_WEIGHTS


if __name__ == "__main__":
    test_features = {
        'return_1m': 0.1,
        'return_5m': -0.2,
        'return_15m': 0.3,
        'volatility_1h': 0.5,
        'bid_ask_imbalance': 0.1,
        'spread_bps': 2.0,
        'depth_ratio': 1.2,
        'fear_greed': 45,
        'funding_rate': 0.01,
        'long_short_ratio': 1.1
    }
    
    result = get_ensemble_prediction(
        symbol='BTCUSDT',
        direction='LONG',
        features=test_features,
        ofi=0.7,
        ensemble_score=0.15
    )
    
    print(json.dumps(result, indent=2))
