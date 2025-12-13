"""
Phase 2 Volatility Baseline Revalidation - Dynamic vol baseline for Kelly scaling.

Continuously updates volatility baseline using EMA smoothing and adjusts
position sizing based on current market regime.
"""

import numpy as np
from typing import List
import json
from pathlib import Path
from datetime import datetime


class VolatilityMonitor:
    """Monitors and revalidates volatility baseline for Kelly scaling."""
    
    def __init__(self, cfg, log_file: str = "logs/phase2_volatility.json"):
        self.cfg = cfg
        self.log_file = Path(log_file)
        self.baselines = {}  # symbol -> baseline vol %
        self.load_baselines()
    
    def load_baselines(self):
        """Load saved volatility baselines."""
        if self.log_file.exists():
            try:
                with open(self.log_file) as f:
                    data = json.load(f)
                    self.baselines = data.get("baselines", {})
            except Exception:
                pass
    
    def save_baselines(self):
        """Save volatility baselines to disk."""
        self.log_file.parent.mkdir(exist_ok=True)
        data = {
            "baselines": self.baselines,
            "updated_at": datetime.now().isoformat()
        }
        with open(self.log_file, 'w') as f:
            json.dump(data, f, indent=2)
    
    def compute_realized_daily_vol(self, returns_1m: List[float]) -> float:
        """
        Calculate realized daily volatility from 1-minute returns.
        
        Args:
            returns_1m: List of 1-minute returns
            
        Returns:
            Daily volatility (standard deviation)
        """
        if len(returns_1m) < 2:
            return 0.0
        
        returns_array = np.array(returns_1m)
        # Annualize 1-minute volatility to daily
        # sqrt(390) for 390 1-minute bars in a trading day
        vol_1m = np.std(returns_array)
        vol_daily = vol_1m * np.sqrt(390)
        
        return float(vol_daily)
    
    def revalidate_baseline(self, symbol: str, returns_1m: List[float]) -> float:
        """
        Recompute and smooth volatility baseline for a symbol.
        
        Uses EMA to smooth transitions and prevent overreaction to spikes.
        
        Args:
            symbol: Trading symbol
            returns_1m: Recent 1-minute returns
            
        Returns:
            Updated annual volatility percentage
        """
        # Calculate current realized volatility
        realized_daily_vol = self.compute_realized_daily_vol(returns_1m)
        
        # Annualize (252 trading days)
        annual_vol_pct = float(realized_daily_vol * np.sqrt(252) * 100.0)
        
        # Get previous baseline or use config default
        prev_baseline = self.baselines.get(symbol, self.cfg.vol_baseline_annual_pct)
        
        # EMA smoothing
        smoothed = (self.cfg.vol_smooth_alpha * annual_vol_pct + 
                   (1 - self.cfg.vol_smooth_alpha) * prev_baseline)
        
        # Update and save
        self.baselines[symbol] = smoothed
        self.save_baselines()
        
        return smoothed
    
    def get_baseline(self, symbol: str) -> float:
        """Get current volatility baseline for symbol."""
        return self.baselines.get(symbol, self.cfg.vol_baseline_annual_pct)
    
    def kelly_adjustment(self, current_vol_pct: float, baseline_vol_pct: float) -> float:
        """
        Calculate Kelly size adjustment based on volatility regime.
        
        Lower vol → increase size (less whipsaw risk)
        Higher vol → decrease size (more whipsaw risk)
        
        Args:
            current_vol_pct: Current realized volatility %
            baseline_vol_pct: Baseline volatility %
            
        Returns:
            Position size multiplier (0.5 to 1.5, capped)
        """
        if current_vol_pct <= 0:
            return 1.0
        
        # Vol ratio: current vs baseline
        vol_ratio = max(0.1, min(3.0, current_vol_pct / baseline_vol_pct))
        
        # Inverse relationship: higher vol → smaller scaler
        raw_scaler = 1.0 / vol_ratio
        
        # Apply Phase 2 cap
        max_increase = 1.0 + self.cfg.kelly_position_size_cap  # 1.5
        min_decrease = 0.5
        
        return max(min_decrease, min(max_increase, raw_scaler))
    
    def get_vol_regime(self, current_vol_pct: float, baseline_vol_pct: float) -> str:
        """
        Classify volatility regime.
        
        Args:
            current_vol_pct: Current realized volatility %
            baseline_vol_pct: Baseline volatility %
            
        Returns:
            Regime name: "Low", "Normal", "Elevated", "High"
        """
        ratio = current_vol_pct / baseline_vol_pct if baseline_vol_pct > 0 else 1.0
        
        if ratio < 0.7:
            return "Low"
        elif ratio < 1.3:
            return "Normal"
        elif ratio < 2.0:
            return "Elevated"
        else:
            return "High"
