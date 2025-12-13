"""
Phase 2 Predictive Position Sizing

Dynamic position sizing using:
1. Half-Kelly Criterion - Size based on edge and win rate
2. Volatility Scaling - Reduce size in high volatility (ATR)
3. Regime Awareness - Reduce size in uncertain regimes

This replaces static sizing with mathematical edge-based allocation.
"""

import numpy as np
import json
import os
import time
from typing import Dict, Optional, Tuple

SIZING_LOG_PATH = "logs/predictive_sizing.jsonl"
SIZING_CONFIG_PATH = "config/predictive_sizing.json"

class PredictiveSizing:
    """
    Calculates position size using Half-Kelly + Volatility Scaling.
    
    Key features:
    - Kelly fraction limits to half for safety
    - ATR-based volatility adjustment
    - Regime-aware multipliers
    - Hard guardrails (max 10% of account)
    """
    
    def __init__(self):
        self.config = self._load_config()
        self.sizing_history: list = []
    
    def _load_config(self) -> Dict:
        """Load sizing configuration."""
        defaults = {
            "max_account_pct": 0.10,      # Max 10% per position
            "min_size_usd": 200.0,        # Minimum $200 (per user preference)
            "max_size_usd": 2000.0,       # Maximum $2000 (per user preference)
            "base_risk_pct": 0.01,        # 1% base risk per trade
            "kelly_fraction": 0.5,        # Half-Kelly
            "min_win_rate": 0.30,         # Don't trade below 30% WR
            "regime_multipliers": {
                "TRENDING": 1.2,          # Boost in trending
                "NOISE": 0.8,             # Reduce in noise
                "MEAN_REVERSION": 1.0     # Normal in mean reversion
            }
        }
        
        if os.path.exists(SIZING_CONFIG_PATH):
            try:
                with open(SIZING_CONFIG_PATH, 'r') as f:
                    loaded = json.load(f)
                    defaults.update(loaded)
            except:
                pass
        
        return defaults
    
    def _log_sizing(self, symbol: str, details: Dict):
        """Log sizing decision for analysis."""
        os.makedirs(os.path.dirname(SIZING_LOG_PATH), exist_ok=True)
        entry = {
            'ts': time.time(),
            'symbol': symbol,
            **details
        }
        with open(SIZING_LOG_PATH, 'a') as f:
            f.write(json.dumps(entry) + '\n')

    def calculate_kelly_fraction(self, win_rate: float, profit_factor: float) -> float:
        """
        Calculate optimal Kelly fraction.
        
        Kelly formula: f* = (p(b+1) - 1) / b
        Where:
        - p = win rate (probability of winning)
        - b = profit factor (average win / average loss)
        
        Returns: Optimal fraction (0 to 1)
        """
        if win_rate <= 0 or profit_factor <= 0:
            return 0.0
        
        if win_rate >= 1.0:
            win_rate = 0.99  # Cap at 99%
        
        # Kelly formula
        b = profit_factor
        p = win_rate
        
        kelly = (p * (b + 1) - 1) / b
        
        # Apply half-Kelly for safety
        safe_kelly = kelly * self.config["kelly_fraction"]
        
        # Clamp to valid range
        return max(0.0, min(0.25, safe_kelly))  # Never exceed 25%

    def calculate_volatility_adjusted_size(
        self, 
        wallet_balance: float,
        price: float,
        atr: float,
        base_risk_pct: Optional[float] = None
    ) -> float:
        """
        Calculate size based on volatility (ATR).
        
        Keeps dollar risk constant by reducing size when ATR is high.
        
        Args:
            wallet_balance: Total account value in USD
            price: Current asset price
            atr: Average True Range (in price units)
            base_risk_pct: Risk per trade as fraction of account
            
        Returns: Position size in USD
        """
        if atr <= 0 or price <= 0:
            return 0.0
        
        base_risk = base_risk_pct or self.config["base_risk_pct"]
        risk_dollars = wallet_balance * base_risk
        
        # ATR as percentage of price
        atr_pct = atr / price
        
        # Size such that 1 ATR move = risk_dollars
        # size_usd * atr_pct = risk_dollars
        size_usd = risk_dollars / atr_pct if atr_pct > 0 else 0
        
        return size_usd

    def get_size(
        self,
        symbol: str,
        wallet_balance: float,
        price: float,
        win_rate: float,
        profit_factor: float,
        current_volatility_atr: float,
        regime: str = "NOISE",
        confidence: float = 0.5
    ) -> Tuple[float, Dict]:
        """
        Calculate optimal position size using all factors.
        
        Args:
            symbol: Trading symbol
            wallet_balance: Account balance in USD
            price: Current asset price
            win_rate: Historical win rate (0-1)
            profit_factor: Average win / average loss
            current_volatility_atr: Current ATR value
            regime: Market regime ('TRENDING', 'MEAN_REVERSION', 'NOISE')
            confidence: Signal confidence (0-1)
            
        Returns:
            (size_usd, details_dict)
        """
        details = {
            'wallet_balance': wallet_balance,
            'price': price,
            'win_rate': win_rate,
            'profit_factor': profit_factor,
            'atr': current_volatility_atr,
            'regime': regime,
            'confidence': confidence
        }
        
        # Reject if win rate too low
        if win_rate < self.config["min_win_rate"]:
            details['size_usd'] = 0
            details['reason'] = f"win_rate {win_rate:.2%} below minimum {self.config['min_win_rate']:.2%}"
            self._log_sizing(symbol, details)
            return 0.0, details
        
        # 1. Kelly-based size
        kelly_frac = self.calculate_kelly_fraction(win_rate, profit_factor)
        kelly_size_usd = wallet_balance * kelly_frac
        
        # 2. Volatility-adjusted size
        vol_size_usd = self.calculate_volatility_adjusted_size(
            wallet_balance, price, current_volatility_atr
        )
        
        # 3. Take the smaller of Kelly or volatility-based
        base_size = min(kelly_size_usd, vol_size_usd) if vol_size_usd > 0 else kelly_size_usd
        
        # 4. Apply regime multiplier
        regime_mult = self.config["regime_multipliers"].get(regime, 1.0)
        regime_adjusted = base_size * regime_mult
        
        # 5. Apply confidence scaling (0.5 to 1.0 based on confidence)
        conf_mult = 0.5 + (confidence * 0.5)
        conf_adjusted = regime_adjusted * conf_mult
        
        # 6. Apply guardrails
        max_size = min(
            wallet_balance * self.config["max_account_pct"],
            self.config["max_size_usd"]
        )
        min_size = self.config["min_size_usd"]
        
        final_size = max(min_size, min(max_size, conf_adjusted))
        
        # Check if we should even take the trade
        if conf_adjusted < min_size * 0.5:
            # Edge too small to justify minimum size
            final_size = 0.0
            details['reason'] = "edge_too_small"
        
        # Build details
        details.update({
            'kelly_fraction': round(kelly_frac, 4),
            'kelly_size_usd': round(kelly_size_usd, 2),
            'vol_size_usd': round(vol_size_usd, 2),
            'regime_mult': regime_mult,
            'conf_mult': round(conf_mult, 2),
            'final_size_usd': round(final_size, 2),
            'reason': details.get('reason', 'calculated')
        })
        
        self._log_sizing(symbol, details)
        
        return final_size, details

    def get_size_simple(
        self,
        wallet_balance: float,
        win_rate: float,
        profit_factor: float,
        current_volatility_atr: float,
        price: float
    ) -> float:
        """
        Simplified sizing for backward compatibility.
        
        Returns position size in quantity units.
        """
        if profit_factor <= 0 or price <= 0:
            return 0.0
        
        # Kelly fraction
        kelly_frac = self.calculate_kelly_fraction(win_rate, profit_factor)
        safe_fraction = kelly_frac * self.config["kelly_fraction"]
        
        # Volatility scalar
        base_risk_dollars = wallet_balance * self.config["base_risk_pct"]
        vol_adjusted_qty = base_risk_dollars / current_volatility_atr if current_volatility_atr > 0 else 0
        
        # Kelly quantity
        kelly_qty = (wallet_balance * safe_fraction) / price
        
        # Take smaller
        final_qty = min(kelly_qty, vol_adjusted_qty) if vol_adjusted_qty > 0 else kelly_qty
        
        # Guardrails
        max_qty = (wallet_balance * self.config["max_account_pct"]) / price
        min_qty = self.config["min_size_usd"] / price
        
        final_qty = min(final_qty, max_qty)
        final_qty = max(0.0, final_qty)
        
        return final_qty


# Global instance
_sizer: Optional[PredictiveSizing] = None

def get_sizer() -> PredictiveSizing:
    """Get or create the global PredictiveSizing instance."""
    global _sizer
    if _sizer is None:
        _sizer = PredictiveSizing()
    return _sizer

def calculate_size(
    symbol: str,
    wallet_balance: float,
    price: float,
    win_rate: float,
    profit_factor: float,
    atr: float,
    regime: str = "NOISE",
    confidence: float = 0.5
) -> Tuple[float, Dict]:
    """Convenience function for sizing calculation."""
    return get_sizer().get_size(
        symbol, wallet_balance, price, win_rate, profit_factor,
        atr, regime, confidence
    )


if __name__ == "__main__":
    sizer = PredictiveSizing()
    
    # Test sizing
    print("Testing PredictiveSizing...")
    
    size, details = sizer.get_size(
        symbol="BTCUSDT",
        wallet_balance=10000,
        price=97000,
        win_rate=0.55,
        profit_factor=1.5,
        current_volatility_atr=1500,
        regime="TRENDING",
        confidence=0.7
    )
    
    print(f"\nBTCUSDT Position Size: ${size:.2f}")
    print(f"Details: {json.dumps(details, indent=2)}")
    
    # Test with low win rate
    size2, details2 = sizer.get_size(
        symbol="XRPUSDT",
        wallet_balance=10000,
        price=2.5,
        win_rate=0.25,  # Below minimum
        profit_factor=1.2,
        current_volatility_atr=0.05,
        regime="NOISE",
        confidence=0.4
    )
    
    print(f"\nXRPUSDT Position Size: ${size2:.2f}")
    print(f"Reason: {details2.get('reason')}")
