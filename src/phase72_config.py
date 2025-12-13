"""
Phase 7.2 - Configuration & Feature Flags (Tier-Based)
Execution Relaxation & Strategy Discipline with per-tier thresholds
"""
from dataclasses import dataclass, field
from typing import Dict
import json
import os

CONFIG_FILE = "configs/phase72_config.json"


@dataclass
class Phase72Config:
    """Phase 7.2 feature flags and tier-based thresholds."""
    
    # Master switch
    enabled: bool = True
    
    # Per-tier ensemble relaxation (% reduction from base)
    relax_pct_stable: Dict[str, float] = field(default_factory=lambda: {
        "majors": 0.03,      # 3% relaxation for BTC, ETH
        "l1s": 0.05,         # 5% relaxation for SOL, AVAX
        "experimental": 0.00  # 0% relaxation for DOT, TRX, XRP, etc.
    })
    
    # Base ensemble threshold before relaxation
    min_ensemble_score_base: float = 0.55
    
    # Minimum hold time
    min_hold_seconds: int = 420  # 7 minutes (increased from 3 min based on exit timing analysis)
    min_hold_allow_protective_exit: bool = True
    
    # SHORT suppression (per-symbol rolling stats)
    suppress_shorts_until_profitable: bool = False  # Allow all SHORT signals (was True)
    shorts_min_wr: float = 0.48  # 48% win rate required
    shorts_min_pnl_usd: float = 0.0  # P&L must be >= 0
    shorts_window_trades: int = 30  # Rolling window size
    
    # Blofin fees
    blofin_fee_maker: float = 0.0002  # 0.02%
    blofin_fee_taker: float = 0.0006  # 0.06%
    
    # Dashboard refresh
    dashboard_refresh_sec: int = 60
    
    # Futures margin
    futures_margin_pct: float = 0.06  # 6% of portfolio
    futures_margin_ratchet_enabled: bool = True
    futures_margin_max_pct: float = 0.10  # Ratchet to 10% when profitable
    
    def get_tier_relaxation(self, tier: str, regime: str) -> float:
        """
        Get ensemble threshold relaxation for tier and regime.
        
        Args:
            tier: "majors", "l1s", or "experimental"
            regime: "Stable", "Trending", etc.
            
        Returns:
            Relaxation percentage (e.g., 0.03 for 3%)
        """
        if regime.lower() == "stable":
            return self.relax_pct_stable.get(tier, 0.0)
        return 0.0  # No relaxation in non-stable regimes
    
    def get_ensemble_threshold(self, tier: str, regime: str) -> float:
        """
        Get adjusted ensemble threshold for tier and regime.
        
        Args:
            tier: Symbol tier
            regime: Market regime
            
        Returns:
            Adjusted threshold (base * (1 - relaxation))
        """
        relax = self.get_tier_relaxation(tier, regime)
        return self.min_ensemble_score_base * (1.0 - relax)
    
    def save(self):
        """Save configuration to file."""
        os.makedirs(os.path.dirname(CONFIG_FILE), exist_ok=True)
        with open(CONFIG_FILE, 'w') as f:
            json.dump(self.__dict__, f, indent=2)
    
    @classmethod
    def load(cls) -> 'Phase72Config':
        """Load configuration from file."""
        if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE, 'r') as f:
                    data = json.load(f)
                    return cls(**data)
            except Exception as e:
                print(f"⚠️  Phase 7.2 config load error: {e}, using defaults")
                pass
        return cls()


# Global config instance
_config = None

def get_phase72_config() -> Phase72Config:
    """Get or create global config."""
    global _config
    if _config is None:
        _config = Phase72Config.load()
    return _config


def update_phase72_config(updates: Dict):
    """Update configuration values."""
    config = get_phase72_config()
    for key, value in updates.items():
        if hasattr(config, key):
            setattr(config, key, value)
    config.save()
    print(f"✅ Phase 7.2 config updated: {updates}")


def reset_phase72_config():
    """Reset config to defaults."""
    global _config
    _config = Phase72Config()
    _config.save()
    print("✅ Phase 7.2 config reset to defaults")
