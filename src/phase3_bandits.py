"""
Phase 3 Per-Ticker Bandits & Attribution

Multi-armed bandit learning for per-symbol strategy optimization.
Tracks feature attribution and suppresses weak features.
"""

from dataclasses import dataclass, field
from typing import Dict, Optional
import json
from pathlib import Path
from datetime import datetime


@dataclass
class ArmStats:
    """Statistics for a single bandit arm (symbol-strategy pair)."""
    pulls: int = 0
    value: float = 0.0
    wins: int = 0
    losses: int = 0
    total_pnl: float = 0.0
    avg_expectancy: float = 0.0


@dataclass
class Attribution:
    """Feature attribution for a symbol."""
    feature_strengths: Dict[str, float] = field(default_factory=dict)
    expected_contribution_usd: float = 0.0


@dataclass
class BanditState:
    """Per-symbol bandit state."""
    arms: Dict[str, ArmStats] = field(default_factory=dict)
    attribution: Attribution = field(default_factory=Attribution)


class BanditLearner:
    """Multi-armed bandit learning system."""
    
    def __init__(self, alpha: float = 0.3):
        """
        Initialize bandit learner.
        
        Args:
            alpha: Soft update rate for arm values (0-1)
        """
        self.alpha = alpha
        self.state: Dict[str, BanditState] = {}
        self._load_state()
    
    def update_arm(self, symbol: str, strategy: str, reward: float) -> ArmStats:
        """
        Update bandit arm with reward signal.
        
        Args:
            symbol: Trading symbol
            strategy: Strategy name
            reward: Reward (e.g., expectancy per trade in USD)
            
        Returns:
            Updated arm statistics
        """
        if symbol not in self.state:
            self.state[symbol] = BanditState()
        
        arm_key = f"{strategy}"
        if arm_key not in self.state[symbol].arms:
            self.state[symbol].arms[arm_key] = ArmStats()
        
        arm = self.state[symbol].arms[arm_key]
        
        arm.pulls += 1
        arm.value = (1 - self.alpha) * arm.value + self.alpha * reward
        arm.total_pnl += reward
        
        if reward > 0:
            arm.wins += 1
        else:
            arm.losses += 1
        
        if arm.pulls > 0:
            arm.avg_expectancy = arm.total_pnl / arm.pulls
        
        self._save_state()
        return arm
    
    def get_arm(self, symbol: str, strategy: str) -> Optional[ArmStats]:
        """Get arm statistics for symbol-strategy pair."""
        if symbol not in self.state:
            return None
        
        arm_key = f"{strategy}"
        return self.state[symbol].arms.get(arm_key)
    
    def get_best_strategy(self, symbol: str) -> Optional[str]:
        """Get highest-value strategy for symbol."""
        if symbol not in self.state or not self.state[symbol].arms:
            return None
        
        best_arm = max(self.state[symbol].arms.items(), key=lambda x: x[1].value)
        return best_arm[0]
    
    def suppress_weak_features(self, symbol: str, min_strength: float = 0.15) -> Attribution:
        """
        Zero out features below minimum strength.
        
        Args:
            symbol: Trading symbol
            min_strength: Minimum feature strength threshold
            
        Returns:
            Attribution with weak features suppressed
        """
        if symbol not in self.state:
            return Attribution()
        
        attr = self.state[symbol].attribution
        suppressed_features = {
            k: (v if v >= min_strength else 0.0)
            for k, v in attr.feature_strengths.items()
        }
        
        return Attribution(
            feature_strengths=suppressed_features,
            expected_contribution_usd=attr.expected_contribution_usd
        )
    
    def update_attribution(self, symbol: str, feature: str, strength: float,
                          contribution_usd: float, decay: float = 0.97):
        """
        Update feature attribution with exponential decay.
        
        Args:
            symbol: Trading symbol
            feature: Feature name (e.g., "momentum", "mean_reversion")
            strength: Feature strength (0-1)
            contribution_usd: Expected contribution in USD
            decay: Decay factor for existing attribution
        """
        if symbol not in self.state:
            self.state[symbol] = BanditState()
        
        attr = self.state[symbol].attribution
        
        if not attr.feature_strengths:
            attr.feature_strengths = {}
        
        old_strength = attr.feature_strengths.get(feature, 0.0)
        attr.feature_strengths[feature] = decay * old_strength + (1 - decay) * strength
        
        attr.expected_contribution_usd = decay * attr.expected_contribution_usd + (1 - decay) * contribution_usd
        
        self._save_state()
    
    def get_attribution(self, symbol: str) -> Attribution:
        """Get attribution for symbol."""
        if symbol not in self.state:
            return Attribution()
        return self.state[symbol].attribution
    
    def _save_state(self):
        """Save bandit state to disk."""
        state_file = Path("logs/phase3_bandit_state.json")
        state_file.parent.mkdir(exist_ok=True)
        
        data = {}
        for symbol, state in self.state.items():
            data[symbol] = {
                "arms": {
                    k: {
                        "pulls": v.pulls,
                        "value": v.value,
                        "wins": v.wins,
                        "losses": v.losses,
                        "total_pnl": v.total_pnl,
                        "avg_expectancy": v.avg_expectancy
                    }
                    for k, v in state.arms.items()
                },
                "attribution": {
                    "feature_strengths": state.attribution.feature_strengths,
                    "expected_contribution_usd": state.attribution.expected_contribution_usd
                }
            }
        
        data["_meta"] = {
            "alpha": self.alpha,
            "updated_at": datetime.now().isoformat()
        }
        
        with open(state_file, 'w') as f:
            json.dump(data, f, indent=2)
    
    def _load_state(self):
        """Load bandit state from disk."""
        state_file = Path("logs/phase3_bandit_state.json")
        
        if state_file.exists():
            try:
                with open(state_file) as f:
                    data = json.load(f)
                    
                    for symbol, state_data in data.items():
                        if symbol == "_meta":
                            continue
                        
                        arms = {}
                        for arm_key, arm_data in state_data.get("arms", {}).items():
                            arms[arm_key] = ArmStats(
                                pulls=arm_data.get("pulls", 0),
                                value=arm_data.get("value", 0.0),
                                wins=arm_data.get("wins", 0),
                                losses=arm_data.get("losses", 0),
                                total_pnl=arm_data.get("total_pnl", 0.0),
                                avg_expectancy=arm_data.get("avg_expectancy", 0.0)
                            )
                        
                        attr_data = state_data.get("attribution", {})
                        attribution = Attribution(
                            feature_strengths=attr_data.get("feature_strengths", {}),
                            expected_contribution_usd=attr_data.get("expected_contribution_usd", 0.0)
                        )
                        
                        self.state[symbol] = BanditState(arms=arms, attribution=attribution)
            except Exception:
                pass


_bandit_learner: Optional[BanditLearner] = None


def get_bandit_learner() -> BanditLearner:
    """Get or create bandit learner singleton."""
    global _bandit_learner
    if _bandit_learner is None:
        _bandit_learner = BanditLearner()
    return _bandit_learner
