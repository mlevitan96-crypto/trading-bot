#!/usr/bin/env python3
"""
Market Regime Classifier (The Context Layer)
============================================

Implements a two-layer regime detection system:
1. Hurst Exponent (H) - 100-period rolling window to distinguish:
   - Mean-Reversion (H < 0.45)
   - Random Walk (0.45 <= H <= 0.55)
   - Trending (H > 0.55)

2. Hidden Markov Model (HMM) - Detects hidden volatility states:
   - Low-Vol state
   - High-Vol state

Combines both to provide comprehensive regime classification.
"""

import numpy as np
import json
import os
import time
from typing import Dict, List, Optional, Tuple
from collections import deque
from datetime import datetime, timezone
from pathlib import Path

try:
    from hmmlearn import hmm
    HMMLEARN_AVAILABLE = True
except ImportError:
    HMMLEARN_AVAILABLE = False
    print("⚠️ [REGIME] hmmlearn not available - HMM features disabled")

REGIME_STATE_PATH = "feature_store/regime_classifier_state.json"
REGIME_HISTORY_PATH = "logs/regime_classifier_history.jsonl"


def calculate_hurst_exponent(prices: List[float], max_lag: int = 20) -> float:
    """
    Calculate Hurst Exponent using R/S analysis.
    
    Args:
        prices: List of price values
        max_lag: Maximum lag for R/S calculation
    
    Returns:
        Hurst exponent (0.0 to 1.0)
    """
    if len(prices) < 2:
        return 0.5  # Default to random walk
    
    # Convert to returns
    returns = np.diff(np.log(prices))
    
    if len(returns) < max_lag:
        max_lag = len(returns) - 1
    
    if max_lag < 2:
        return 0.5
    
    lags = range(2, max_lag + 1)
    tau = []
    
    for lag in lags:
        # Split returns into non-overlapping windows
        n_windows = len(returns) // lag
        if n_windows < 1:
            continue
        
        rs_values = []
        
        for i in range(n_windows):
            window = returns[i * lag:(i + 1) * lag]
            if len(window) < 2:
                continue
            
            # Mean-centered cumulative sum
            mean_window = np.mean(window)
            cumsum = np.cumsum(window - mean_window)
            
            # Range
            R = np.max(cumsum) - np.min(cumsum)
            
            # Standard deviation
            S = np.std(window)
            
            if S > 0:
                rs_values.append(R / S)
        
        if rs_values:
            tau.append(np.mean(rs_values))
        else:
            tau.append(0.0)
    
    if len(tau) < 2:
        return 0.5
    
    # Fit log(R/S) vs log(lag) to get Hurst
    log_lags = np.log(lags[:len(tau)])
    log_tau = np.log([t for t in tau if t > 0])
    
    if len(log_tau) < 2:
        return 0.5
    
    # Ensure arrays are same length
    min_len = min(len(log_lags), len(log_tau))
    log_lags = log_lags[:min_len]
    log_tau = log_tau[:min_len]
    
    if len(log_lags) < 2:
        return 0.5
    
    # Linear regression
    H, _ = np.polyfit(log_lags, log_tau, 1)
    
    # Clamp between 0 and 1
    H = max(0.0, min(1.0, H))
    
    return float(H)


def classify_regime_hurst(hurst: float) -> str:
    """
    Classify regime based on Hurst exponent.
    
    Args:
        hurst: Hurst exponent value
    
    Returns:
        Regime classification: 'MEAN_REVERSION', 'RANDOM_WALK', or 'TRENDING'
    """
    if hurst < 0.45:
        return 'MEAN_REVERSION'
    elif hurst > 0.55:
        return 'TRENDING'
    else:
        return 'RANDOM_WALK'


class HMMVolatilityDetector:
    """
    Hidden Markov Model for volatility state detection.
    """
    
    def __init__(self, n_states: int = 2, n_iter: int = 100):
        """
        Initialize HMM detector.
        
        Args:
            n_states: Number of hidden states (2 = Low-Vol, High-Vol)
            n_iter: Maximum iterations for training
        """
        self.n_states = n_states
        self.n_iter = n_iter
        self.model = None
        self.is_trained = False
        self.returns_buffer = deque(maxlen=500)  # Store recent returns
    
    def update(self, returns: List[float]) -> Optional[str]:
        """
        Update HMM model with new returns and detect current state.
        
        Args:
            returns: List of percentage returns
        
        Returns:
            Current volatility state: 'LOW_VOL' or 'HIGH_VOL', or None if not trained
        """
        if not HMMLEARN_AVAILABLE:
            return None
        
        # Add to buffer
        self.returns_buffer.extend(returns)
        
        if len(self.returns_buffer) < 50:
            return None  # Need more data
        
        try:
            # Prepare data (2D array, single feature)
            X = np.array(list(self.returns_buffer)).reshape(-1, 1)
            
            # Train or retrain model
            if not self.is_trained or len(self.returns_buffer) % 100 == 0:
                self.model = hmm.GaussianHMM(n_components=self.n_states, n_iter=self.n_iter, random_state=42)
                self.model.fit(X)
                self.is_trained = True
            
            # Predict current state
            if self.model and len(X) > 0:
                state = self.model.predict(X[-10:].reshape(-1, 1))[-1]
                
                # Determine which state is low vol vs high vol based on means
                means = self.model.means_.flatten()
                if means[state] < means[1 - state]:
                    return 'LOW_VOL'
                else:
                    return 'HIGH_VOL'
        
        except Exception as e:
            print(f"⚠️ [REGIME] HMM update error: {e}")
            return None
        
        return None


class RegimeClassifier:
    """
    Multi-layered regime classifier combining Hurst Exponent and HMM.
    """
    
    def __init__(self, window_size: int = 100):
        """
        Initialize regime classifier.
        
        Args:
            window_size: Rolling window size for Hurst calculation
        """
        self.window_size = window_size
        self.prices: Dict[str, deque] = {}
        self.returns: Dict[str, deque] = {}
        self.regime_cache: Dict[str, Dict] = {}
        self.last_update: Dict[str, float] = {}
        self.hmm_detector = HMMVolatilityDetector() if HMMLEARN_AVAILABLE else None
        
        self._load_state()
    
    def _load_state(self):
        """Load previous state if available."""
        state_path = Path(REGIME_STATE_PATH)
        if state_path.exists():
            try:
                with open(state_path, 'r') as f:
                    state = json.load(f)
                    # Restore prices as deque
                    self.prices = {
                        symbol: deque(prices_list, maxlen=self.window_size)
                        for symbol, prices_list in state.get('prices', {}).items()
                    }
                    self.returns = {
                        symbol: deque(returns_list, maxlen=500)
                        for symbol, returns_list in state.get('returns', {}).items()
                    }
                    self.regime_cache = state.get('regime_cache', {})
                    self.last_update = state.get('last_update', {})
            except Exception as e:
                print(f"⚠️ [REGIME] Error loading state: {e}")
    
    def _save_state(self):
        """Persist state for recovery."""
        state_path = Path(REGIME_STATE_PATH)
        state_path.parent.mkdir(parents=True, exist_ok=True)
        
        state = {
            'prices': {
                symbol: list(prices) for symbol, prices in self.prices.items()
            },
            'returns': {
                symbol: list(returns) for symbol, returns in self.returns.items()
            },
            'regime_cache': self.regime_cache,
            'last_update': self.last_update,
            'ts': time.time()
        }
        
        with open(state_path, 'w') as f:
            json.dump(state, f, indent=2)
    
    def _log_regime_change(self, symbol: str, old_regime: Dict, new_regime: Dict):
        """Log regime changes to history."""
        history_path = Path(REGIME_HISTORY_PATH)
        history_path.parent.mkdir(parents=True, exist_ok=True)
        
        entry = {
            'symbol': symbol,
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'old_regime': old_regime,
            'new_regime': new_regime,
            'ts': time.time()
        }
        
        with open(history_path, 'a') as f:
            f.write(json.dumps(entry) + '\n')
    
    def update_price(self, symbol: str, price: float):
        """
        Update price history for a symbol.
        
        Args:
            symbol: Trading symbol
            price: Current price
        """
        if symbol not in self.prices:
            self.prices[symbol] = deque(maxlen=self.window_size)
            self.returns[symbol] = deque(maxlen=500)
        
        prev_price = self.prices[symbol][-1] if len(self.prices[symbol]) > 0 else price
        self.prices[symbol].append(price)
        
        # Calculate and store return
        if prev_price > 0:
            ret = (price - prev_price) / prev_price
            self.returns[symbol].append(ret)
    
    def get_regime(self, symbol: str, force_recalculate: bool = False) -> Dict[str, any]:
        """
        Get current regime classification for a symbol.
        
        Args:
            symbol: Trading symbol
            force_recalculate: Force recalculation even if cached
        
        Returns:
            Dict with regime information:
            {
                'hurst_regime': 'MEAN_REVERSION' | 'RANDOM_WALK' | 'TRENDING',
                'hurst_value': float,
                'volatility_state': 'LOW_VOL' | 'HIGH_VOL' | None,
                'composite_regime': str,  # Combined classification
                'confidence': float,
                'timestamp': str
            }
        """
        # Check cache (refresh every 60 seconds)
        now = time.time()
        if not force_recalculate and symbol in self.regime_cache:
            last_update = self.last_update.get(symbol, 0)
            if (now - last_update) < 60 and symbol in self.regime_cache:
                return self.regime_cache[symbol]
        
        # Need at least window_size prices
        if symbol not in self.prices or len(self.prices[symbol]) < self.window_size:
            default_regime = {
                'hurst_regime': 'RANDOM_WALK',
                'hurst_value': 0.5,
                'volatility_state': None,
                'composite_regime': 'NEUTRAL',
                'confidence': 0.0,
                'timestamp': datetime.now(timezone.utc).isoformat()
            }
            self.regime_cache[symbol] = default_regime
            return default_regime
        
        # Calculate Hurst exponent
        prices_list = list(self.prices[symbol])
        hurst = calculate_hurst_exponent(prices_list)
        hurst_regime = classify_regime_hurst(hurst)
        
        # Get volatility state from HMM
        volatility_state = None
        if self.hmm_detector and symbol in self.returns:
            returns_list = list(self.returns[symbol])
            volatility_state = self.hmm_detector.update(returns_list)
        
        # Composite regime classification
        composite_regime = self._combine_regimes(hurst_regime, volatility_state)
        
        # Confidence based on data quality
        confidence = min(1.0, len(prices_list) / self.window_size)
        if volatility_state:
            confidence = (confidence + 0.8) / 2  # Boost confidence if HMM is available
        
        regime_info = {
            'hurst_regime': hurst_regime,
            'hurst_value': round(hurst, 4),
            'volatility_state': volatility_state,
            'composite_regime': composite_regime,
            'confidence': round(confidence, 3),
            'timestamp': datetime.now(timezone.utc).isoformat()
        }
        
        # Update cache
        old_regime = self.regime_cache.get(symbol, {})
        self.regime_cache[symbol] = regime_info
        self.last_update[symbol] = now
        
        # Log regime changes
        if old_regime.get('composite_regime') != composite_regime:
            self._log_regime_change(symbol, old_regime, regime_info)
        
        # Periodically save state
        if int(now) % 300 == 0:  # Every 5 minutes
            self._save_state()
        
        return regime_info
    
    def _combine_regimes(self, hurst_regime: str, volatility_state: Optional[str]) -> str:
        """
        Combine Hurst-based regime with volatility state.
        
        Args:
            hurst_regime: Hurst classification
            volatility_state: HMM volatility state
        
        Returns:
            Composite regime string
        """
        # Base regime from Hurst
        if hurst_regime == 'TRENDING':
            base = 'TREND'
        elif hurst_regime == 'MEAN_REVERSION':
            base = 'RANGE'
        else:
            base = 'CHOP'
        
        # Add volatility modifier
        if volatility_state:
            if volatility_state == 'HIGH_VOL':
                return f"{base}_HIGH_VOL"
            else:
                return f"{base}_LOW_VOL"
        
        return base
    
    def get_active_regime(self, symbol: str) -> str:
        """
        Get active regime string (for compatibility with existing code).
        
        Args:
            symbol: Trading symbol
        
        Returns:
            Regime string: 'TREND', 'RANGE', or 'CHOP'
        """
        regime_info = self.get_regime(symbol)
        composite = regime_info['composite_regime']
        
        # Extract base regime
        if 'TREND' in composite:
            return 'TREND'
        elif 'RANGE' in composite:
            return 'RANGE'
        else:
            return 'CHOP'


# Global instance
_regime_classifier: Optional[RegimeClassifier] = None


def get_regime_classifier() -> RegimeClassifier:
    """Get or create global regime classifier instance."""
    global _regime_classifier
    if _regime_classifier is None:
        _regime_classifier = RegimeClassifier()
    return _regime_classifier


def active_regime(symbol: str) -> str:
    """
    Get active regime for a symbol (compatibility function).
    
    Args:
        symbol: Trading symbol
    
    Returns:
        Regime string: 'TREND', 'RANGE', or 'CHOP'
    """
    classifier = get_regime_classifier()
    return classifier.get_active_regime(symbol)

