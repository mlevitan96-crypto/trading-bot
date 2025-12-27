#!/usr/bin/env python3
"""
Adaptive Signal Optimizer
==========================

Maintains three distinct Weight Profiles based on detected market regime:
- TREND: Optimized for trending markets
- RANGE: Optimized for mean-reverting/range-bound markets
- CHOP: Optimized for choppy/uncertain markets

Switches active profile based on regime classifier output.
"""

import json
from pathlib import Path
from typing import Dict, Optional, Any
from src.regime_classifier import get_regime_classifier, active_regime

WEIGHT_PROFILES_PATH = Path("feature_store/regime_weight_profiles.json")

# Default weight profiles for each regime
DEFAULT_PROFILES = {
    'TREND': {
        'ofi': 0.30,
        'ensemble': 0.25,
        'mtf_alignment': 0.20,
        'momentum': 0.15,
        'regime': 0.10,
        'volume': 0.08,
        'market_intel': 0.05,
        'session': 0.02
    },
    'RANGE': {
        'ofi': 0.20,
        'ensemble': 0.15,
        'mtf_alignment': 0.10,
        'regime': 0.25,
        'volume': 0.15,
        'market_intel': 0.10,
        'momentum': 0.05,
        'session': 0.05
    },
    'CHOP': {
        'ofi': 0.15,
        'ensemble': 0.20,
        'mtf_alignment': 0.15,
        'regime': 0.15,
        'volume': 0.15,
        'market_intel': 0.12,
        'momentum': 0.08,
        'session': 0.10
    }
}


class AdaptiveSignalOptimizer:
    """
    Manages regime-specific weight profiles and switches based on market regime.
    """
    
    def __init__(self):
        self.weight_profiles = DEFAULT_PROFILES.copy()
        self.active_regime = 'CHOP'  # Default
        self._load_profiles()
    
    def _load_profiles(self):
        """Load weight profiles from disk."""
        if WEIGHT_PROFILES_PATH.exists():
            try:
                with open(WEIGHT_PROFILES_PATH, 'r') as f:
                    data = json.load(f)
                    self.weight_profiles = data.get('profiles', DEFAULT_PROFILES)
            except Exception as e:
                print(f"⚠️ [ADAPTIVE-SIGNAL] Error loading profiles: {e}")
    
    def _save_profiles(self):
        """Save weight profiles to disk."""
        WEIGHT_PROFILES_PATH.parent.mkdir(parents=True, exist_ok=True)
        
        data = {
            'profiles': self.weight_profiles,
            'updated_at': json.dumps(str)
        }
        
        with open(WEIGHT_PROFILES_PATH, 'w') as f:
            json.dump(data, f, indent=2)
    
    def update_regime(self, symbol: str):
        """
        Update active regime based on classifier.
        
        Args:
            symbol: Trading symbol to get regime for
        """
        regime = active_regime(symbol)
        
        # Map regime to profile name
        if 'TREND' in regime:
            self.active_regime = 'TREND'
        elif 'RANGE' in regime or 'MEAN_REVERSION' in regime:
            self.active_regime = 'RANGE'
        else:
            self.active_regime = 'CHOP'
    
    def get_active_weights(self, symbol: str) -> Dict[str, float]:
        """
        Get active weight profile for current regime.
        
        Args:
            symbol: Trading symbol (used to determine regime)
        
        Returns:
            Dictionary of signal weights
        """
        # Update regime
        self.update_regime(symbol)
        
        # Return weights for active regime
        return self.weight_profiles.get(self.active_regime, DEFAULT_PROFILES['CHOP']).copy()
    
    def get_active_regime(self) -> str:
        """Get current active regime name."""
        return self.active_regime
    
    def update_weight_profile(self, regime: str, weights: Dict[str, float]):
        """
        Update weight profile for a regime.
        
        Args:
            regime: Regime name ('TREND', 'RANGE', or 'CHOP')
            weights: New weight dictionary
        """
        if regime in self.weight_profiles:
            self.weight_profiles[regime] = weights.copy()
            self._save_profiles()


# Global instance
_adaptive_optimizer: Optional[AdaptiveSignalOptimizer] = None


def get_adaptive_optimizer() -> AdaptiveSignalOptimizer:
    """Get or create global adaptive optimizer instance."""
    global _adaptive_optimizer
    if _adaptive_optimizer is None:
        _adaptive_optimizer = AdaptiveSignalOptimizer()
    return _adaptive_optimizer


def get_active_weights(symbol: str) -> Dict[str, float]:
    """
    Get active weight profile for a symbol based on current regime.
    
    Args:
        symbol: Trading symbol
    
    Returns:
        Signal weights dictionary
    """
    optimizer = get_adaptive_optimizer()
    return optimizer.get_active_weights(symbol)

