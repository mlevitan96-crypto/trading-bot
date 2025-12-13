"""
Phase 2 Execution Guardrails - Pre-trade validation and kill switches.

Comprehensive go/no-go checks before any order execution with full audit trails.
"""

from dataclasses import dataclass
from typing import Dict, List, Tuple, Optional
from datetime import datetime
import json
from pathlib import Path


@dataclass
class PortfolioState:
    """Current portfolio state for risk checks."""
    daily_pnl_bps: float
    portfolio_value: float
    shadow_mode: bool
    throttle_active: bool


@dataclass
class BlockStats:
    """Statistics about recent signal blocking."""
    block_pct: float  # Percentage of signals blocked
    block_hours: float  # Hours of heavy blocking
    total_signals: int
    blocked_signals: int


class ExecutionGuards:
    """Pre-trade validation and execution guardrails."""
    
    def __init__(self, cfg, log_file: str = "logs/phase2_execution_guards.json"):
        self.cfg = cfg
        self.log_file = Path(log_file)
        self.kill_switch_active = False
        self.load_state()
    
    def load_state(self):
        """Load execution guard state."""
        if self.log_file.exists():
            try:
                with open(self.log_file) as f:
                    data = json.load(f)
                    self.kill_switch_active = data.get("kill_switch_active", False)
            except Exception:
                pass
    
    def save_state(self):
        """Save execution guard state."""
        self.log_file.parent.mkdir(exist_ok=True)
        data = {
            "kill_switch_active": self.kill_switch_active,
            "updated_at": datetime.now().isoformat()
        }
        with open(self.log_file, 'w') as f:
            json.dump(data, f, indent=2)
    
    def check_daily_loss_kill_switch(self, portfolio: PortfolioState) -> Tuple[bool, Optional[str]]:
        """
        Check if daily loss kill switch should activate.
        
        Args:
            portfolio: Current portfolio state
            
        Returns:
            (passed, reason) - False if kill switch triggered
        """
        if portfolio.shadow_mode:
            return (True, None)  # No kill switch in shadow mode
        
        if portfolio.daily_pnl_bps <= -self.cfg.daily_loss_kill_switch_bps:
            self.kill_switch_active = True
            self.save_state()
            return (False, f"kill_switch_triggered:daily_loss={portfolio.daily_pnl_bps:.1f}bps<-{self.cfg.daily_loss_kill_switch_bps}bps")
        
        return (True, None)
    
    def reset_kill_switch(self):
        """Manually reset kill switch (called at midnight or by operator)."""
        self.kill_switch_active = False
        self.save_state()
    
    def check_per_trade_risk_cap(self, position_size_usd: float, portfolio_value: float) -> Tuple[bool, Optional[str]]:
        """
        Ensure single trade doesn't exceed risk cap.
        
        Args:
            position_size_usd: Proposed position size in USD
            portfolio_value: Total portfolio value
            
        Returns:
            (passed, reason)
        """
        risk_bps = (position_size_usd / portfolio_value) * 10000
        
        if risk_bps > self.cfg.per_trade_risk_bps_cap:
            return (False, f"per_trade_risk_exceeded:{risk_bps:.1f}bps>{self.cfg.per_trade_risk_bps_cap}bps")
        
        return (True, None)
    
    def check_slippage_expectation(self, expected_slippage_bps: float) -> Tuple[bool, Optional[str]]:
        """
        Validate expected slippage is within acceptable range.
        
        Args:
            expected_slippage_bps: Estimated slippage in basis points
            
        Returns:
            (passed, reason)
        """
        if expected_slippage_bps > self.cfg.max_slippage_bps:
            return (False, f"slippage_too_high:{expected_slippage_bps:.1f}bps>{self.cfg.max_slippage_bps}bps")
        
        return (True, None)
    
    def pre_trade_validation(self,
                            signal,
                            symbol_budget_usd: float,
                            position_size_usd: float,
                            expected_slippage_bps: float,
                            portfolio: PortfolioState,
                            mtf_decision,
                            throttle_state) -> Tuple[bool, List[str], Dict]:
        """
        Comprehensive pre-trade go/no-go with full audit trail.
        
        Args:
            signal: Trading signal
            symbol_budget_usd: Allocated budget for symbol
            position_size_usd: Proposed position size
            expected_slippage_bps: Expected slippage
            portfolio: Current portfolio state
            mtf_decision: Multi-timeframe decision
            throttle_state: Risk throttle state
            
        Returns:
            (allowed, block_reasons, audit_trail)
        """
        reasons = []
        audit = {
            "timestamp": datetime.now().isoformat(),
            "symbol": getattr(signal, 'symbol', 'UNKNOWN'),
            "checks": {}
        }
        
        # Check 1: Kill switch
        kill_switch_ok, kill_reason = self.check_daily_loss_kill_switch(portfolio)
        audit["checks"]["kill_switch"] = {"passed": kill_switch_ok, "reason": kill_reason}
        if not kill_switch_ok:
            reasons.append(kill_reason)
            return (False, reasons, audit)
        
        # Check 2: MTF confirmation
        audit["checks"]["mtf"] = {
            "passed": mtf_decision.allowed,
            "reason": mtf_decision.reason,
            "relaxed": mtf_decision.relaxed_policy_used
        }
        if not mtf_decision.allowed:
            reasons.append(mtf_decision.reason or "mtf_blocked")
        
        # Check 3: Symbol budget
        budget_ok = symbol_budget_usd > 0
        audit["checks"]["symbol_budget"] = {
            "passed": budget_ok,
            "budget_usd": symbol_budget_usd
        }
        if not budget_ok:
            reasons.append(f"symbol_budget_blocked:budget=${symbol_budget_usd:.2f}")
        
        # Check 4: Per-trade risk cap
        risk_ok, risk_reason = self.check_per_trade_risk_cap(position_size_usd, portfolio.portfolio_value)
        audit["checks"]["per_trade_risk"] = {"passed": risk_ok, "reason": risk_reason}
        if not risk_ok:
            reasons.append(risk_reason)
        
        # Check 5: Slippage threshold
        slippage_ok, slippage_reason = self.check_slippage_expectation(expected_slippage_bps)
        audit["checks"]["slippage"] = {"passed": slippage_ok, "reason": slippage_reason}
        if not slippage_ok:
            reasons.append(slippage_reason)
        
        # Check 6: Throttle state
        from src.phase2_gates import evaluate_throttle
        throttle_active = evaluate_throttle(throttle_state, self.cfg)
        from src.phase2_gates import allowed_leverage
        max_lev = allowed_leverage(portfolio.shadow_mode, throttle_active, self.cfg)
        audit["checks"]["throttle"] = {
            "active": throttle_active,
            "max_leverage": max_lev,
            "sharpe": throttle_state.sharpe,
            "sortino": throttle_state.sortino
        }
        
        # Final decision
        allowed = len(reasons) == 0
        audit["final_decision"] = {"allowed": allowed, "block_reasons": reasons}
        
        return (allowed, reasons, audit)
