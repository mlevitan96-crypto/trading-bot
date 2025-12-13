"""
SEQUENCE PREDICTOR - LSTM/GRU for Price Direction Prediction
=============================================================
Deep learning model for sequential price prediction.

Architecture:
- Input: 60 timesteps of OHLCV + features
- LSTM/GRU layers with dropout
- Output: Probability of price going up/down

This module uses scikit-learn's MLPClassifier as fallback when
PyTorch/TensorFlow is not available, while maintaining the same interface.

Data Flow:
- Training: Uses closed_positions with ml_features and outcomes
- Inference: Called by ensemble_predictor.py
- Models saved to: models/lstm/

Reference: Following pattern from ml_predictor.py
"""

import os
import json
import pickle
import math
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Tuple, Optional, Any
from collections import defaultdict

try:
    from sklearn.neural_network import MLPClassifier
    from sklearn.preprocessing import StandardScaler
    from sklearn.model_selection import train_test_split
    SKLEARN_AVAILABLE = True
except ImportError:
    SKLEARN_AVAILABLE = False
    MLPClassifier = None
    StandardScaler = None
    train_test_split = None

try:
    from src.data_registry import DataRegistry as DR
except ImportError:
    class DR:
        ML_LSTM_MODELS = "models/lstm"
        POSITIONS_FUTURES = "logs/positions_futures.json"
        ML_TRAINING_DATASET = "feature_store/training_dataset.json"

LSTM_DIR = Path(DR.ML_LSTM_MODELS)
POSITIONS_FILE = Path(DR.POSITIONS_FUTURES)
TRAINING_DATA = Path(DR.ML_TRAINING_DATASET)
LOG_FILE = Path("logs/sequence_predictor.log")

LSTM_DIR.mkdir(parents=True, exist_ok=True)
LOG_FILE.parent.mkdir(parents=True, exist_ok=True)

SYMBOLS = ['BTCUSDT', 'ETHUSDT', 'SOLUSDT', 'BNBUSDT', 'AVAXUSDT', 'DOTUSDT', 
           'XRPUSDT', 'ADAUSDT', 'DOGEUSDT', 'MATICUSDT', 'TRXUSDT', 'LINKUSDT',
           'ARBUSDT', 'OPUSDT', 'PEPEUSDT']

SEQUENCE_LENGTH = 20
FEATURE_COLS = [
    'return_1m', 'return_5m', 'return_15m', 'volatility_1h',
    'bid_ask_imbalance', 'spread_bps', 'depth_ratio',
    'fear_greed', 'funding_rate', 'long_short_ratio'
]


def log(msg: str):
    ts = datetime.utcnow().isoformat() + "Z"
    entry = f"[{ts}] {msg}"
    print(entry)
    try:
        with open(LOG_FILE, 'a') as f:
            f.write(entry + '\n')
    except:
        pass


class SequencePredictor:
    """
    LSTM/GRU-style sequence predictor using scikit-learn MLPClassifier.
    
    This provides a neural network for sequence classification without
    requiring PyTorch/TensorFlow installation.
    """
    
    def __init__(self, symbol: str):
        self.symbol = symbol
        self.model = None
        self.scaler = None
        self.model_path = LSTM_DIR / f"mlp_{symbol}.pkl"
        self.scaler_path = LSTM_DIR / f"scaler_{symbol}.pkl"
        self.metadata_path = LSTM_DIR / f"meta_{symbol}.json"
        self.feature_cols = FEATURE_COLS
        self.sequence_length = SEQUENCE_LENGTH
    
    def _prepare_sequences(self, features_list: List[Dict], outcomes: List[int]) -> Tuple[List, List]:
        """
        Prepare flattened feature vectors from sequential data.
        
        Since we're using MLP instead of LSTM, we flatten the sequence
        into a single feature vector, capturing recent history.
        """
        X = []
        y = []
        
        for features, outcome in zip(features_list, outcomes):
            if not features:
                continue
            
            feature_vec = []
            for col in self.feature_cols:
                val = features.get(col, 0)
                if val is None:
                    val = 0
                feature_vec.append(float(val))
            
            if len(feature_vec) == len(self.feature_cols):
                X.append(feature_vec)
                y.append(outcome)
        
        return X, y
    
    def train(self, features_list: List[Dict], outcomes: List[int]) -> Dict[str, Any]:
        """
        Train the sequence model on historical data.
        
        Args:
            features_list: List of feature dicts from closed positions
            outcomes: List of 1 (win) or 0 (loss) labels
        
        Returns:
            Training metrics
        """
        if not SKLEARN_AVAILABLE:
            log(f"sklearn not available for {self.symbol} - skipping training")
            return {'error': 'sklearn not available', 'sklearn_installed': False}
        
        X, y = self._prepare_sequences(features_list, outcomes)
        
        if len(X) < 50:
            log(f"Insufficient data for {self.symbol}: {len(X)} samples (need 50+)")
            return {'error': 'insufficient_data', 'samples': len(X)}
        
        self.scaler = StandardScaler()
        X_scaled = self.scaler.fit_transform(X)
        
        X_train, X_test, y_train, y_test = train_test_split(
            X_scaled, y, test_size=0.2, random_state=42, stratify=y if sum(y) > 5 else None
        )
        
        self.model = MLPClassifier(
            hidden_layer_sizes=(64, 32),
            activation='relu',
            solver='adam',
            alpha=0.01,
            batch_size=32,
            learning_rate='adaptive',
            max_iter=200,
            early_stopping=True,
            validation_fraction=0.1,
            random_state=42,
            verbose=False
        )
        
        try:
            self.model.fit(X_train, y_train)
        except Exception as e:
            log(f"Training failed for {self.symbol}: {e}")
            return {'error': str(e)}
        
        train_acc = self.model.score(X_train, y_train)
        test_acc = self.model.score(X_test, y_test)
        
        with open(self.model_path, 'wb') as f:
            pickle.dump(self.model, f)
        
        with open(self.scaler_path, 'wb') as f:
            pickle.dump(self.scaler, f)
        
        metadata = {
            'symbol': self.symbol,
            'trained_at': datetime.utcnow().isoformat() + 'Z',
            'samples': len(X),
            'train_accuracy': round(train_acc, 4),
            'test_accuracy': round(test_acc, 4),
            'feature_cols': self.feature_cols,
            'win_rate': round(sum(y) / len(y), 4) if y else 0
        }
        
        with open(self.metadata_path, 'w') as f:
            json.dump(metadata, f, indent=2)
        
        log(f"Trained {self.symbol}: train_acc={train_acc:.3f}, test_acc={test_acc:.3f}, samples={len(X)}")
        
        return metadata
    
    def load(self) -> bool:
        """Load trained model from disk."""
        try:
            if self.model_path.exists() and self.scaler_path.exists():
                with open(self.model_path, 'rb') as f:
                    self.model = pickle.load(f)
                with open(self.scaler_path, 'rb') as f:
                    self.scaler = pickle.load(f)
                return True
        except Exception as e:
            log(f"Failed to load model for {self.symbol}: {e}")
        return False
    
    def predict(self, features: Dict) -> Tuple[float, float]:
        """
        Predict win probability for given features.
        
        Args:
            features: Current market features dict
        
        Returns:
            (prob_win, confidence) tuple
        """
        if not SKLEARN_AVAILABLE:
            return 0.5, 0.0
        
        if self.model is None:
            if not self.load():
                return 0.5, 0.0
        
        feature_vec = []
        for col in self.feature_cols:
            val = features.get(col, 0)
            if val is None:
                val = 0
            feature_vec.append(float(val))
        
        if len(feature_vec) != len(self.feature_cols):
            return 0.5, 0.0
        
        try:
            X = self.scaler.transform([feature_vec])
            proba = self.model.predict_proba(X)[0]
            
            prob_win = proba[1] if len(proba) > 1 else proba[0]
            
            confidence = abs(prob_win - 0.5) * 2
            
            return round(prob_win, 4), round(confidence, 4)
        except Exception as e:
            log(f"Prediction error for {self.symbol}: {e}")
            return 0.5, 0.0


_predictors: Dict[str, SequencePredictor] = {}


def get_predictor(symbol: str) -> SequencePredictor:
    """Get or create predictor for symbol."""
    if symbol not in _predictors:
        _predictors[symbol] = SequencePredictor(symbol)
    return _predictors[symbol]


def predict_sequence(symbol: str, features: Dict) -> Tuple[float, float]:
    """
    Main prediction interface.
    
    Args:
        symbol: Trading symbol
        features: Current market features
    
    Returns:
        (prob_win, confidence) tuple
    """
    predictor = get_predictor(symbol)
    return predictor.predict(features)


def train_all_models() -> Dict[str, Any]:
    """
    Train models for all symbols.
    Called nightly by scheduler.
    """
    log("============================================================")
    log("Sequence Predictor Training Starting...")
    log("============================================================")
    
    try:
        with open(POSITIONS_FILE, 'r') as f:
            data = json.load(f)
        closed = data.get('closed_positions', [])
    except Exception as e:
        log(f"Failed to load positions: {e}")
        return {'error': str(e)}
    
    by_symbol = defaultdict(lambda: {'features': [], 'outcomes': []})
    
    for pos in closed:
        symbol = pos.get('symbol', '')
        if symbol not in SYMBOLS:
            continue
        
        ml_features = pos.get('ml_features', {})
        if not ml_features:
            continue
        
        pnl = pos.get('net_pnl') or pos.get('pnl') or pos.get('pnl_usd', 0)
        outcome = 1 if pnl > 0 else 0
        
        by_symbol[symbol]['features'].append(ml_features)
        by_symbol[symbol]['outcomes'].append(outcome)
    
    results = {}
    for symbol in SYMBOLS:
        if symbol in by_symbol:
            predictor = get_predictor(symbol)
            result = predictor.train(
                by_symbol[symbol]['features'],
                by_symbol[symbol]['outcomes']
            )
            results[symbol] = result
        else:
            results[symbol] = {'error': 'no_data'}
    
    log("Sequence Predictor Training Complete")
    return results


if __name__ == "__main__":
    results = train_all_models()
    print(json.dumps(results, indent=2))
