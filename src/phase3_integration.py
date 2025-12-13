"""
Phase 3 Integration - Edge Compounding Orchestration

Main controller for Phase 3 features:
- Adaptive filter relaxation
- Per-ticker bandits & attribution
- Correlation & exposure controls
- Drawdown-aware throttle
- Funding cost model
- Missed opportunity replay
- Capital ramp
"""

from typing import Dict, List, Tuple, Optional
from dataclasses import dataclass
import json
from pathlib import Path
from datetime import datetime

from src.phase3_config import get_phase3_config, Phase3Config
from src.phase3_adaptive_relax import (
    BlockStats, choose_relax_policy, get_relaxed_threshold,
    RelaxationState, update_relaxation_state, save_relaxation_state, load_relaxation_state
)
from src.phase3_bandits import get_bandit_learner, BanditLearner, Attribution
from src.phase3_correlation import (
    theme_for_symbol, compute_theme_exposure, correlation_block_check,
    exposure_cap_check, get_exposure_state
)
from src.phase3_drawdown import (
    DrawdownState, update_drawdown_state, dd_adjust_size,
    should_pause_ramp, save_drawdown_state, load_drawdown_state
)
from src.phase3_funding import funding_cost_ok, estimate_funding_rate, log_funding_decision
from src.phase3_mor import replay_missed_opportunities, get_missed_signals
from src.phase3_ramp import CapitalRampController


@dataclass
class Phase3State:
    """Complete Phase 3 state."""
    relaxation: RelaxationState
    drawdown: DrawdownState
    ramp_controller: CapitalRampController


class Phase3Controller:
    """
    Main controller for Phase 3 edge compounding.
    
    Orchestrates all Phase 3 features with minimal complexity.
    """
    
    def __init__(self, cfg: Optional[Phase3Config] = None):
        """
        Initialize Phase 3 controller.
        
        Args:
            cfg: Optional Phase3Config, defaults to get_phase3_config()
        """
        self.cfg = cfg or get_phase3_config()
        
        self.bandit_learner = get_bandit_learner()
        
        self.state = Phase3State(
            relaxation=load_relaxation_state(),
            drawdown=load_drawdown_state(),
            ramp_controller=CapitalRampController(
                stages=self.cfg.ramp_stages,
                hold_sharpe=self.cfg.ramp_hold_sharpe,
                hold_sortino=self.cfg.ramp_hold_sortino,
                max_drawdown_bps=self.cfg.ramp_max_drawdown_bps
            )
        )
    
    def check_correlation_and_exposure(self, symbol: str, position_size_usd: float,
                                      open_positions: List[Dict],
                                      portfolio_value: float,
                                      corr_matrix=None,
                                      symbol_list: Optional[List[str]] = None) -> Tuple[bool, List[str]]:
        """
        Check correlation and theme exposure constraints.
        
        Args:
            symbol: Symbol to check
            position_size_usd: Proposed position size
            open_positions: Current open positions
            portfolio_value: Total portfolio value
            corr_matrix: Correlation matrix (numpy array)
            symbol_list: List of symbols matching corr_matrix order
            
        Returns:
            (allowed, block_reasons)
        """
        reasons = []
        
        if self.cfg.cross_symbol_corr_block_threshold > 0 and corr_matrix is not None and symbol_list:
            if correlation_block_check(
                symbol, open_positions, corr_matrix, symbol_list,
                self.cfg.cross_symbol_corr_block_threshold
            ):
                reasons.append("high_cross_correlation")
        
        if self.cfg.max_theme_exposure_bps:
            if exposure_cap_check(
                symbol, position_size_usd, open_positions,
                portfolio_value, self.cfg.max_theme_exposure_bps
            ):
                theme = theme_for_symbol(symbol)
                reasons.append(f"theme_exposure_cap_{theme}")
        
        return (len(reasons) == 0, reasons)
    
    def check_funding_cost(self, symbol: str, side: str,
                          attribution_strength: float) -> Tuple[bool, Optional[str]]:
        """
        Check funding cost constraints for futures.
        
        Args:
            symbol: Trading symbol
            side: "LONG" or "SHORT"
            attribution_strength: Maximum attribution strength for symbol
            
        Returns:
            (allowed, block_reason)
        """
        if not self.cfg.funding_cost_model_enable:
            return (True, None)
        
        allowed = funding_cost_ok(
            symbol, side, attribution_strength,
            self.cfg.funding_cost_bps_cap,
            self.cfg.min_attribution_strength * 2.0
        )
        
        if not allowed:
            expected_cost = estimate_funding_rate(symbol, side)
            log_funding_decision(symbol, side, expected_cost, attribution_strength,
                               allowed, "cost_exceeds_cap_low_attribution")
            return (False, "funding_cost_too_high")
        
        return (True, None)
    
    def adjust_size_for_drawdown(self, base_size: float,
                                 portfolio_value: float) -> Tuple[float, bool]:
        """
        Adjust position size based on drawdown state.
        
        Args:
            base_size: Base position size
            portfolio_value: Current portfolio value
            
        Returns:
            (adjusted_size, soft_block_active)
        """
        if not self.cfg.dd_throttle_enable:
            return (base_size, False)
        
        self.state.drawdown = update_drawdown_state(self.state.drawdown, portfolio_value)
        save_drawdown_state(self.state.drawdown)
        
        adjusted_size, soft_block = dd_adjust_size(
            base_size,
            self.state.drawdown.current_drawdown_bps,
            self.cfg.dd_soft_block_bps,
            self.cfg.dd_size_reduction_pct
        )
        
        self.state.drawdown.soft_block_active = soft_block
        
        return (adjusted_size, soft_block)
    
    def get_leverage_cap(self, throttle_ok: bool, sharpe: float,
                        sortino: float) -> float:
        """
        Get current leverage cap from capital ramp.
        
        Args:
            throttle_ok: Phase 2 throttle status
            sharpe: Current Sharpe ratio
            sortino: Current Sortino ratio
            
        Returns:
            Maximum allowed leverage
        """
        return self.state.ramp_controller.get_current_leverage_cap(
            throttle_ok, sharpe, sortino,
            self.state.drawdown.current_drawdown_bps
        )
    
    def update_relaxation(self, block_stats: BlockStats):
        """
        Update filter relaxation state.
        
        Args:
            block_stats: Current blocking statistics
        """
        if not self.cfg.adaptive_relax_enable:
            return
        
        self.state.relaxation = update_relaxation_state(
            self.state.relaxation,
            block_stats,
            self.cfg.choke_block_threshold_pct,
            self.cfg.relax_window_hours
        )
        
        save_relaxation_state(self.state.relaxation)
    
    def get_relaxed_threshold(self) -> Optional[float]:
        """Get relaxed MTF threshold if active."""
        if not self.state.relaxation.is_relaxed:
            return None
        
        return get_relaxed_threshold(self.state.relaxation.policy)
    
    def update_bandit(self, symbol: str, strategy: str, pnl: float):
        """
        Update bandit arm for symbol-strategy pair.
        
        Args:
            symbol: Trading symbol
            strategy: Strategy name
            pnl: Trade P&L in USD
        """
        if not self.cfg.bandit_enable:
            return
        
        self.bandit_learner.update_arm(symbol, strategy, pnl)
    
    def get_attribution(self, symbol: str, suppress_weak: bool = True) -> Attribution:
        """
        Get attribution for symbol.
        
        Args:
            symbol: Trading symbol
            suppress_weak: Whether to suppress weak features
            
        Returns:
            Attribution object
        """
        if suppress_weak:
            return self.bandit_learner.suppress_weak_features(
                symbol, self.cfg.min_attribution_strength
            )
        
        return self.bandit_learner.get_attribution(symbol)
    
    def run_mor_replay(self) -> Dict:
        """
        Run missed opportunity replay.
        
        Returns:
            Replay statistics
        """
        if not self.cfg.mor_enable:
            return {"replayed_count": 0}
        
        relax_policy = self.state.relaxation.policy if self.state.relaxation.is_relaxed else None
        
        attribution_data = {}
        for symbol in ["BTCUSDT", "ETHUSDT", "SOLUSDT", "AVAXUSDT", "DOTUSDT", "TRXUSDT"]:
            attr = self.get_attribution(symbol, suppress_weak=False)
            if attr.feature_strengths:
                attribution_data[symbol] = max(attr.feature_strengths.values())
        
        return replay_missed_opportunities(
            lookback_hours=self.cfg.mor_lookback_hours,
            replay_limit=self.cfg.mor_replay_limit_per_day,
            relax_policy=relax_policy,
            attribution_data=attribution_data
        )
    
    def get_status(self) -> Dict:
        """Get comprehensive Phase 3 status."""
        exposure_state = get_exposure_state([], 10000.0)
        ramp_progress = self.state.ramp_controller.get_ramp_progress()
        
        return {
            "relaxation": {
                "active": self.state.relaxation.is_relaxed,
                "policy": self.state.relaxation.policy,
                "total_hours": round(self.state.relaxation.total_relaxation_hours, 2)
            },
            "drawdown": {
                "current_bps": round(self.state.drawdown.current_drawdown_bps, 1),
                "max_bps": round(self.state.drawdown.max_drawdown_bps, 1),
                "soft_block_active": self.state.drawdown.soft_block_active
            },
            "ramp": ramp_progress,
            "exposure": {
                "by_theme": {
                    k: round(v, 1) for k, v in exposure_state.theme_exposure_bps.items()
                },
                "total_bps": round(exposure_state.total_exposure_bps, 1)
            },
            "bandits": {
                "active": self.cfg.bandit_enable,
                "alpha": self.cfg.bandit_alpha,
                "symbols_tracked": len(self.bandit_learner.state)
            },
            "mor": {
                "enabled": self.cfg.mor_enable,
                "lookback_hours": self.cfg.mor_lookback_hours
            }
        }


_phase3_controller: Optional[Phase3Controller] = None


def get_phase3_controller() -> Phase3Controller:
    """Get or create Phase 3 controller singleton."""
    global _phase3_controller
    if _phase3_controller is None:
        _phase3_controller = Phase3Controller()
    return _phase3_controller
