"""
Phase 7.4 Expectancy Gate
Trade only when expected value is positive after fees
"""

import json
import os
from typing import List
from datetime import datetime, timedelta
from phase74_config import Phase74Config


class Phase74Expectancy:
    def __init__(self):
        self.trades_log = "logs/closed_trades.json"
    
    def rolling_net_outcomes_usd(self, symbol: str, window: int) -> List[float]:
        try:
            if not os.path.exists(self.trades_log):
                return []
            
            with open(self.trades_log, 'r') as f:
                trades = json.load(f)
            
            symbol_trades = [t for t in trades if t.get("symbol") == symbol][-window:]
            outcomes = [t.get("pnl_usd_realized", 0.0) for t in symbol_trades]
            return outcomes
        except Exception:
            return []
    
    def slippage_p75_bps(self, symbol: str, window: int) -> float:
        try:
            if not os.path.exists(self.trades_log):
                return 15.0
            
            with open(self.trades_log, 'r') as f:
                trades = json.load(f)
            
            symbol_trades = [t for t in trades if t.get("symbol") == symbol][-window:]
            slippages = [abs(t.get("slippage_bps", 0)) for t in symbol_trades]
            
            if not slippages:
                return 15.0
            
            slippages.sort()
            p75_idx = int(len(slippages) * 0.75)
            return slippages[min(p75_idx, len(slippages) - 1)]
        except Exception:
            return 15.0
    
    def baseline_notional(self, symbol: str) -> float:
        try:
            portfolio_file = "logs/portfolio.json"
            if not os.path.exists(portfolio_file):
                return 1000.0
            
            with open(portfolio_file, 'r') as f:
                portfolio = json.load(f)
            
            total_value = portfolio.get("total_value_usd", 10000.0)
            return total_value * 0.15
        except Exception:
            return 1000.0
    
    def expected_value_usd(self, symbol: str, config: Phase74Config) -> float:
        outcomes = self.rolling_net_outcomes_usd(symbol, config.ev_window_trades)
        
        if not outcomes:
            return 0.0
        
        mean = sum(outcomes) / len(outcomes)
        slip_bps = self.slippage_p75_bps(symbol, config.ev_window_trades)
        notional = self.baseline_notional(symbol)
        slip_cost = notional * (slip_bps / 10000.0)
        
        return mean - slip_cost
    
    def expectancy_gate(self, signal, config: Phase74Config) -> tuple[bool, str]:
        if signal.ensemble_score < config.min_ensemble_score:
            return (False, f"low_ensemble:{signal.ensemble_score:.3f}<{config.min_ensemble_score}")
        
        ev = self.expected_value_usd(signal.symbol, config)
        if ev < config.min_expected_value_usd:
            return (False, f"low_ev:${ev:.2f}<${config.min_expected_value_usd}")
        
        return (True, f"passed:ev=${ev:.2f}")


_phase74_expectancy = None

def get_phase74_expectancy() -> Phase74Expectancy:
    global _phase74_expectancy
    if _phase74_expectancy is None:
        _phase74_expectancy = Phase74Expectancy()
    return _phase74_expectancy
