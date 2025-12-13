"""
Phase 2 Integration - Main orchestration layer for Phase 2 features.

Provides simple API for bot to use all Phase 2 capabilities:
- Shadow mode trading
- Statistical promotion gates
- Volatility-aware sizing
- Execution guardrails
- Comprehensive telemetry
"""

from typing import Dict, List, Tuple, Optional
from dataclasses import dataclass
from datetime import datetime
import json
from pathlib import Path

from src.phase2_config import get_phase2_config, Phase2Config
from src.phase2_gates import (
    SignalDecision, ThrottleState, PromotionMetrics, PromotionDecision,
    wilson_score_interval, bootstrap_pnl_ci, evaluate_throttle, 
    promotion_gate, allowed_leverage
)
from src.phase2_budget_allocator import SymbolBudgetAllocator, SymbolStats
from src.phase2_volatility import VolatilityMonitor
from src.phase2_execution_guards import ExecutionGuards, PortfolioState, BlockStats
from src.phase2_telemetry import Phase2Telemetry


@dataclass
class Phase2State:
    """Complete Phase 2 state."""
    throttle: ThrottleState
    portfolio: PortfolioState
    block_stats: BlockStats


class Phase2Controller:
    """
    Main controller for Phase 2 features.
    
    Provides unified API for bot integration with minimal complexity.
    """
    
    def __init__(self, cfg: Optional[Phase2Config] = None):
        """
        Initialize Phase 2 controller.
        
        Args:
            cfg: Optional Phase2Config, defaults to get_phase2_config()
        """
        self.cfg = cfg or get_phase2_config()
        
        # Initialize subsystems
        self.budget_allocator = SymbolBudgetAllocator(self.cfg)
        self.vol_monitor = VolatilityMonitor(self.cfg)
        self.execution_guards = ExecutionGuards(self.cfg)
        self.telemetry = Phase2Telemetry()
        
        # Load state
        self.state = self._load_state()
    
    def _load_state(self) -> Phase2State:
        """Load Phase 2 state from disk."""
        state_file = Path("logs/phase2_state.json")
        
        if state_file.exists():
            try:
                with open(state_file) as f:
                    data = json.load(f)
                    
                    throttle = ThrottleState(
                        sharpe=data.get("throttle", {}).get("sharpe"),
                        sortino=data.get("throttle", {}).get("sortino"),
                        snapshots_collected=data.get("throttle", {}).get("snapshots_collected", 0),
                        active=data.get("throttle", {}).get("active", False)
                    )
                    
                    portfolio = PortfolioState(
                        daily_pnl_bps=data.get("portfolio", {}).get("daily_pnl_bps", 0.0),
                        portfolio_value=data.get("portfolio", {}).get("portfolio_value", 10000.0),
                        shadow_mode=self.cfg.shadow_mode,
                        throttle_active=throttle.active
                    )
                    
                    block_stats = BlockStats(
                        block_pct=data.get("block_stats", {}).get("block_pct", 0.0),
                        block_hours=data.get("block_stats", {}).get("block_hours", 0.0),
                        total_signals=data.get("block_stats", {}).get("total_signals", 0),
                        blocked_signals=data.get("block_stats", {}).get("blocked_signals", 0)
                    )
                    
                    return Phase2State(throttle=throttle, portfolio=portfolio, block_stats=block_stats)
            except Exception:
                pass
        
        # Default state
        return Phase2State(
            throttle=ThrottleState(),
            portfolio=PortfolioState(
                daily_pnl_bps=0.0,
                portfolio_value=10000.0,
                shadow_mode=self.cfg.shadow_mode,
                throttle_active=False
            ),
            block_stats=BlockStats(block_pct=0.0, block_hours=0.0, total_signals=0, blocked_signals=0)
        )
    
    def _save_state(self):
        """Save Phase 2 state to disk."""
        state_file = Path("logs/phase2_state.json")
        state_file.parent.mkdir(exist_ok=True)
        
        data = {
            "throttle": {
                "sharpe": self.state.throttle.sharpe,
                "sortino": self.state.throttle.sortino,
                "snapshots_collected": self.state.throttle.snapshots_collected,
                "active": self.state.throttle.active
            },
            "portfolio": {
                "daily_pnl_bps": self.state.portfolio.daily_pnl_bps,
                "portfolio_value": self.state.portfolio.portfolio_value,
                "shadow_mode": self.state.portfolio.shadow_mode,
                "throttle_active": self.state.portfolio.throttle_active
            },
            "block_stats": {
                "block_pct": self.state.block_stats.block_pct,
                "block_hours": self.state.block_stats.block_hours,
                "total_signals": self.state.block_stats.total_signals,
                "blocked_signals": self.state.block_stats.blocked_signals
            },
            "updated_at": datetime.now().isoformat()
        }
        
        with open(state_file, 'w') as f:
            json.dump(data, f, indent=2)
    
    def validate_signal(self, signal, expected_slippage_bps: float = 5.0) -> Tuple[bool, List[str], Dict]:
        """
        Comprehensive signal validation through all Phase 2 gates.
        
        Args:
            signal: Trading signal object (must have .symbol attribute)
            expected_slippage_bps: Expected slippage in basis points
            
        Returns:
            (allowed, block_reasons, audit_trail)
        """
        symbol = getattr(signal, 'symbol', 'UNKNOWN')
        
        # Get symbol budget
        symbol_budget = self.budget_allocator.get_budget_usd(symbol, self.state.portfolio.portfolio_value)
        
        # Estimate position size (simplified - would use actual sizing logic)
        position_size_usd = symbol_budget * 0.15  # 15% of budget
        
        # MTF decision (simplified - would use actual MTF check)
        mtf_decision = SignalDecision(allowed=True, reason=None)
        if self.cfg.mtf_confirm_required:
            # In real integration, this would call actual MTF check
            # For now, pass through
            pass
        
        # Run execution guards
        allowed, reasons, audit = self.execution_guards.pre_trade_validation(
            signal=signal,
            symbol_budget_usd=symbol_budget,
            position_size_usd=position_size_usd,
            expected_slippage_bps=expected_slippage_bps,
            portfolio=self.state.portfolio,
            mtf_decision=mtf_decision,
            throttle_state=self.state.throttle
        )
        
        # Log decision
        self.telemetry.log_signal_decision(audit)
        
        # Update block stats
        self.state.block_stats.total_signals += 1
        if not allowed:
            self.state.block_stats.blocked_signals += 1
        
        if self.state.block_stats.total_signals > 0:
            self.state.block_stats.block_pct = (
                self.state.block_stats.blocked_signals / self.state.block_stats.total_signals * 100
            )
        
        self._save_state()
        
        return (allowed, reasons, audit)
    
    def update_throttle(self, sharpe: float, sortino: float):
        """
        Update risk throttle metrics.
        
        Args:
            sharpe: Current Sharpe ratio
            sortino: Current Sortino ratio
        """
        self.state.throttle.sharpe = sharpe
        self.state.throttle.sortino = sortino
        self.state.throttle.snapshots_collected += 1
        self.state.throttle.active = evaluate_throttle(self.state.throttle, self.cfg)
        
        self._save_state()
    
    def update_portfolio(self, portfolio_value: float, daily_pnl: float):
        """
        Update portfolio state.
        
        Args:
            portfolio_value: Current portfolio value in USD
            daily_pnl: Today's P&L in USD
        """
        self.state.portfolio.portfolio_value = portfolio_value
        self.state.portfolio.daily_pnl_bps = (daily_pnl / portfolio_value) * 10000 if portfolio_value > 0 else 0
        self.state.portfolio.throttle_active = self.state.throttle.active
        
        self._save_state()
    
    def get_symbol_budget(self, symbol: str) -> float:
        """Get USD budget for symbol."""
        return self.budget_allocator.get_budget_usd(symbol, self.state.portfolio.portfolio_value)
    
    def get_max_leverage(self) -> float:
        """Get currently allowed leverage."""
        return allowed_leverage(
            self.state.portfolio.shadow_mode,
            self.state.throttle.active,
            self.cfg
        )
    
    def emit_telemetry(self):
        """Emit telemetry snapshot."""
        self.telemetry.emit_metrics_snapshot(self.cfg)
    
    def get_status(self) -> Dict:
        """Get comprehensive Phase 2 status."""
        return {
            "shadow_mode": self.cfg.shadow_mode,
            "throttle": {
                "active": self.state.throttle.active,
                "sharpe": self.state.throttle.sharpe,
                "sortino": self.state.throttle.sortino,
                "snapshots": self.state.throttle.snapshots_collected
            },
            "portfolio": {
                "value": self.state.portfolio.portfolio_value,
                "daily_pnl_bps": self.state.portfolio.daily_pnl_bps
            },
            "blocking": {
                "pct": self.state.block_stats.block_pct,
                "total": self.state.block_stats.total_signals,
                "blocked": self.state.block_stats.blocked_signals
            },
            "leverage": {
                "max_allowed": self.get_max_leverage(),
                "live_cap": self.cfg.max_leverage_live,
                "shadow_cap": self.cfg.max_leverage_shadow
            },
            "kill_switch": self.execution_guards.kill_switch_active
        }


# Global controller instance
_phase2_controller: Optional[Phase2Controller] = None


def get_phase2_controller() -> Phase2Controller:
    """Get or create Phase 2 controller singleton."""
    global _phase2_controller
    if _phase2_controller is None:
        _phase2_controller = Phase2Controller()
    return _phase2_controller
