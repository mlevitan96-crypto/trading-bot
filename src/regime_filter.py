"""
Phase 2 Regime Filter - Hurst Exponent Based Market Regime Classification

Calculates the Hurst Exponent to determine if the market is:
- MEAN_REVERSION (H < 0.45): Choppy, range-bound - block trend strategies
- TRENDING (H > 0.55): Persistent moves - block mean-reversion strategies  
- NOISE (0.45 <= H <= 0.55): Random walk - trade cautiously

This acts as a gatekeeper to prevent strategy-regime mismatch whipsaws.
"""

import numpy as np
import json
import os
import time
from typing import Dict, List, Optional, Tuple

REGIME_STATE_PATH = "logs/regime_filter_state.json"
REGIME_HISTORY_PATH = "logs/regime_filter_history.jsonl"

class RegimeFilter:
    """
    Calculates the Hurst Exponent to classify market regime.
    H < 0.5 = Mean Reverting (Chop) -> Block Trend Strategies
    H > 0.5 = Trending (Persistent) -> Block Mean Reversion Strategies
    """
    
    def __init__(self, window_size: int = 100):
        self.window_size = window_size
        self.prices: Dict[str, List[float]] = {}
        self.regime_cache: Dict[str, Dict] = {}
        self.last_update: Dict[str, float] = {}
        self._load_state()
    
    def _load_state(self):
        """Load previous state if available."""
        if os.path.exists(REGIME_STATE_PATH):
            try:
                with open(REGIME_STATE_PATH, 'r') as f:
                    state = json.load(f)
                    self.prices = state.get('prices', {})
                    self.regime_cache = state.get('regime_cache', {})
            except:
                pass
    
    def _save_state(self):
        """Persist state for recovery."""
        os.makedirs(os.path.dirname(REGIME_STATE_PATH), exist_ok=True)
        state = {
            'prices': self.prices,
            'regime_cache': self.regime_cache,
            'ts': time.time()
        }
        with open(REGIME_STATE_PATH, 'w') as f:
            json.dump(state, f)
    
    def _log_regime_change(self, symbol: str, old_regime: str, new_regime: str, hurst: float):
        """Log regime transitions for analysis."""
        os.makedirs(os.path.dirname(REGIME_HISTORY_PATH), exist_ok=True)
        entry = {
            'ts': time.time(),
            'symbol': symbol,
            'old_regime': old_regime,
            'new_regime': new_regime,
            'hurst': round(hurst, 4)
        }
        with open(REGIME_HISTORY_PATH, 'a') as f:
            f.write(json.dumps(entry) + '\n')

    def add_price(self, symbol: str, price: float):
        """
        Ingest new price for a symbol. Maintains fixed window size.
        """
        if symbol not in self.prices:
            self.prices[symbol] = []
        
        self.prices[symbol].append(price)
        if len(self.prices[symbol]) > self.window_size:
            self.prices[symbol].pop(0)
        
        self.last_update[symbol] = time.time()

    def get_hurst_exponent(self, symbol: str) -> float:
        """
        Calculate Hurst Exponent using Rescaled Range (R/S) analysis.
        
        H < 0.5: Anti-persistent (mean-reverting)
        H = 0.5: Random walk (geometric Brownian motion)
        H > 0.5: Persistent (trending)
        """
        if symbol not in self.prices or len(self.prices[symbol]) < self.window_size:
            return 0.5  # Default to random walk if not enough data
        
        series = np.array(self.prices[symbol])
        
        # Calculate log returns for stationarity
        returns = np.diff(np.log(series))
        
        if len(returns) < 10:
            return 0.5
        
        # R/S Analysis
        mean = np.mean(returns)
        cumulative_deviations = np.cumsum(returns - mean)
        R = np.max(cumulative_deviations) - np.min(cumulative_deviations)
        S = np.std(returns)
        
        if S == 0:
            return 0.5
        
        # Approximate Hurst via log(R/S) / log(N)
        RS = R / S
        N = len(returns)
        
        if RS <= 0 or N <= 1:
            return 0.5
            
        H = np.log(RS) / np.log(N)
        
        # Clamp to valid range
        H = max(0.0, min(1.0, H))
        
        return H

    def get_regime(self, symbol: str) -> str:
        """
        Classify current market regime based on Hurst Exponent.
        
        Returns: 'MEAN_REVERSION', 'TRENDING', or 'NOISE'
        """
        h = self.get_hurst_exponent(symbol)
        
        old_regime = self.regime_cache.get(symbol, {}).get('regime', 'NOISE')
        
        if h < 0.45:
            new_regime = "MEAN_REVERSION"
        elif h > 0.55:
            new_regime = "TRENDING"
        else:
            new_regime = "NOISE"
        
        # Log regime changes
        if new_regime != old_regime:
            self._log_regime_change(symbol, old_regime, new_regime, h)
        
        # Update cache
        self.regime_cache[symbol] = {
            'regime': new_regime,
            'hurst': h,
            'ts': time.time()
        }
        
        return new_regime

    def get_regime_details(self, symbol: str) -> Dict:
        """Get full regime details including Hurst value."""
        h = self.get_hurst_exponent(symbol)
        regime = self.get_regime(symbol)
        
        return {
            'symbol': symbol,
            'regime': regime,
            'hurst': round(h, 4),
            'window_size': self.window_size,
            'data_points': len(self.prices.get(symbol, [])),
            'ts': time.time()
        }

    def should_block_strategy(self, symbol: str, strategy_type: str) -> Tuple[bool, str]:
        """
        Determine if a strategy should be blocked based on regime mismatch.
        
        Args:
            symbol: Trading symbol
            strategy_type: 'trend_following', 'mean_reversion', or 'momentum'
            
        Returns:
            (should_block, reason)
        """
        regime = self.get_regime(symbol)
        h = self.get_hurst_exponent(symbol)
        
        strategy_lower = strategy_type.lower().replace('-', '_').replace(' ', '_')
        
        # Block trend-following in mean-reverting markets
        if regime == "MEAN_REVERSION" and strategy_lower in ['trend_following', 'breakout', 'momentum']:
            return True, f"BLOCKED: {strategy_type} in MEAN_REVERSION regime (H={h:.3f})"
        
        # Block mean-reversion in trending markets
        if regime == "TRENDING" and strategy_lower in ['mean_reversion', 'range', 'fade']:
            return True, f"BLOCKED: {strategy_type} in TRENDING regime (H={h:.3f})"
        
        return False, f"ALLOWED: {strategy_type} matches {regime} regime (H={h:.3f})"

    def get_all_regimes(self) -> Dict[str, Dict]:
        """Get regime status for all tracked symbols."""
        result = {}
        for symbol in self.prices.keys():
            result[symbol] = self.get_regime_details(symbol)
        return result

    def persist(self):
        """Save state to disk."""
        self._save_state()


# Global instance for shared access
_regime_filter: Optional[RegimeFilter] = None

def get_regime_filter(window_size: int = 100) -> RegimeFilter:
    """Get or create the global RegimeFilter instance."""
    global _regime_filter
    if _regime_filter is None:
        _regime_filter = RegimeFilter(window_size)
    return _regime_filter

def update_price(symbol: str, price: float):
    """Convenience function to update price in global filter."""
    get_regime_filter().add_price(symbol, price)

def get_regime(symbol: str) -> str:
    """Convenience function to get regime from global filter."""
    return get_regime_filter().get_regime(symbol)

def should_block_strategy(symbol: str, strategy_type: str) -> Tuple[bool, str]:
    """Convenience function to check if strategy should be blocked."""
    return get_regime_filter().should_block_strategy(symbol, strategy_type)


if __name__ == "__main__":
    # Test the regime filter
    rf = RegimeFilter(window_size=50)
    
    # Simulate trending market
    print("Simulating TRENDING market...")
    for i in range(60):
        rf.add_price("BTCUSDT", 50000 + i * 100)
    
    print(f"  Hurst: {rf.get_hurst_exponent('BTCUSDT'):.4f}")
    print(f"  Regime: {rf.get_regime('BTCUSDT')}")
    print(f"  Details: {rf.get_regime_details('BTCUSDT')}")
    
    # Test blocking
    blocked, reason = rf.should_block_strategy("BTCUSDT", "mean_reversion")
    print(f"  Mean Reversion: {reason}")
    
    blocked, reason = rf.should_block_strategy("BTCUSDT", "trend_following")
    print(f"  Trend Following: {reason}")
