"""
Phase 2 Symbol Budget Allocator - Per-symbol capital allocation with automatic blocking.

Punishes poor performers and rewards proven edge with dynamic budget allocation.
"""

from dataclasses import dataclass
from typing import Dict, Optional
import json
from pathlib import Path


@dataclass
class SymbolStats:
    """Performance statistics for a symbol."""
    trades: int
    wins: int
    losses: int
    winrate: float
    expectancy_per_trade: float
    pnl_total: float
    pnl_bootstrap_ci_low: float
    pnl_bootstrap_ci_high: float
    slippage_bps_avg: float
    last_update: str


class SymbolBudgetAllocator:
    """Manages per-symbol budget allocation with automatic blocking."""
    
    def __init__(self, cfg, log_file: str = "logs/phase2_budget_allocator.json"):
        self.cfg = cfg
        self.log_file = Path(log_file)
        self.stats: Dict[str, SymbolStats] = {}
        self.load_stats()
    
    def load_stats(self):
        """Load symbol stats from disk."""
        if self.log_file.exists():
            try:
                with open(self.log_file) as f:
                    data = json.load(f)
                    for symbol, stats_dict in data.get("symbol_stats", {}).items():
                        self.stats[symbol] = SymbolStats(**stats_dict)
            except Exception:
                pass
    
    def save_stats(self):
        """Save symbol stats to disk."""
        self.log_file.parent.mkdir(exist_ok=True)
        data = {
            "symbol_stats": {
                symbol: vars(stats)
                for symbol, stats in self.stats.items()
            }
        }
        with open(self.log_file, 'w') as f:
            json.dump(data, f, indent=2)
    
    def get_budget_bps(self, symbol: str) -> float:
        """
        Calculate budget for symbol in basis points of portfolio.
        
        Rules:
        1. If symbol has min trades and poor performance → block (0 bps)
        2. If slippage too high → reduce budget by 50%
        3. Otherwise use configured base budget
        
        Args:
            symbol: Trading symbol
            
        Returns:
            Budget in basis points (0-120)
        """
        # Get base budget from config
        base_bps = self.cfg.per_symbol_budget_bps.get(symbol, 0)
        
        # If no stats yet, use base budget
        if symbol not in self.stats:
            return base_bps
        
        stats = self.stats[symbol]
        
        # Block if symbol has proven to be unprofitable
        if (stats.trades >= self.cfg.symbol_block_min_trades and
            stats.winrate < self.cfg.symbol_block_winrate_threshold and
            stats.expectancy_per_trade < 0):
            return 0.0  # Full block
        
        # Penalize high slippage
        if stats.slippage_bps_avg > self.cfg.max_slippage_bps:
            return base_bps * 0.5  # 50% reduction
        
        return base_bps
    
    def get_budget_usd(self, symbol: str, portfolio_value: float) -> float:
        """
        Convert budget from bps to USD.
        
        Args:
            symbol: Trading symbol
            portfolio_value: Current portfolio value in USD
            
        Returns:
            Budget in USD
        """
        bps = self.get_budget_bps(symbol)
        return (bps / 10000.0) * portfolio_value
    
    def update_symbol_stats(self, symbol: str, stats: SymbolStats):
        """Update statistics for a symbol."""
        self.stats[symbol] = stats
        self.save_stats()
    
    def get_all_budgets(self, portfolio_value: float) -> Dict[str, float]:
        """Get budget allocation for all symbols."""
        return {
            symbol: self.get_budget_usd(symbol, portfolio_value)
            for symbol in self.cfg.per_symbol_budget_bps.keys()
        }
    
    def get_blocking_reason(self, symbol: str) -> Optional[str]:
        """
        Get reason why symbol is blocked, if any.
        
        Returns:
            Blocking reason string or None if not blocked
        """
        if symbol not in self.stats:
            return None
        
        stats = self.stats[symbol]
        budget_bps = self.get_budget_bps(symbol)
        
        if budget_bps == 0:
            return f"blocked:winrate={stats.winrate:.1%}<{self.cfg.symbol_block_winrate_threshold:.0%},expectancy={stats.expectancy_per_trade:.2f}<0,trades={stats.trades}>={self.cfg.symbol_block_min_trades}"
        
        if budget_bps < self.cfg.per_symbol_budget_bps.get(symbol, 0):
            return f"reduced:slippage={stats.slippage_bps_avg:.1f}bps>{self.cfg.max_slippage_bps}bps"
        
        return None
