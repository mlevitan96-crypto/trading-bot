"""
Phase 2 Orchestrator - Integration Layer

Coordinates the Phase 2 offensive upgrades:
1. Regime Filter (Hurst Exponent) - Gates strategies by market type
2. Real-Time Data Aggregator - Fresh OFI and market data
3. Predictive Sizing - Kelly + volatility based position sizing

This module integrates with the existing bot_cycle.py execution flow.
"""

import asyncio
import time
import json
import os
from typing import Dict, Optional, Tuple, List
from concurrent.futures import ThreadPoolExecutor

from src.regime_filter import get_regime_filter, RegimeFilter
from src.real_market_data import get_aggregator, MarketDataAggregator
from src.predictive_sizing import get_sizer, PredictiveSizing

ORCHESTRATOR_STATE_PATH = "logs/phase2_orchestrator_state.json"
ORCHESTRATOR_LOG_PATH = "logs/phase2_orchestrator.jsonl"

# Strategy type mappings
STRATEGY_TYPES = {
    'Trend-Conservative': 'trend_following',
    'Breakout-Aggressive': 'trend_following',
    'Sentiment-Fusion': 'momentum',
    'Mean-Reversion': 'mean_reversion',
    'Range-Trading': 'mean_reversion',
    'Scalping': 'momentum'
}

class Phase2Orchestrator:
    """
    Master orchestrator for Phase 2 offensive upgrades.
    
    Responsibilities:
    - Update regime filter with latest prices
    - Gate strategies based on regime
    - Fetch real-time market data
    - Calculate optimal position sizes
    """
    
    def __init__(self):
        self.regime_filter = get_regime_filter(window_size=100)
        self.data_aggregator = get_aggregator()
        self.sizer = get_sizer()
        
        self.executor = ThreadPoolExecutor(max_workers=4)
        self.last_update: Dict[str, float] = {}
        self.blocked_count = 0
        self.allowed_count = 0
        
        self._load_state()
    
    def _load_state(self):
        """Load previous state if available."""
        if os.path.exists(ORCHESTRATOR_STATE_PATH):
            try:
                with open(ORCHESTRATOR_STATE_PATH, 'r') as f:
                    state = json.load(f)
                    self.blocked_count = state.get('blocked_count', 0)
                    self.allowed_count = state.get('allowed_count', 0)
            except:
                pass
    
    def _save_state(self):
        """Persist state."""
        os.makedirs(os.path.dirname(ORCHESTRATOR_STATE_PATH), exist_ok=True)
        state = {
            'ts': time.time(),
            'blocked_count': self.blocked_count,
            'allowed_count': self.allowed_count,
            'regimes': self.regime_filter.get_all_regimes()
        }
        with open(ORCHESTRATOR_STATE_PATH, 'w') as f:
            json.dump(state, f, indent=2)
    
    def _log_decision(self, decision_type: str, details: Dict):
        """Log orchestrator decisions."""
        os.makedirs(os.path.dirname(ORCHESTRATOR_LOG_PATH), exist_ok=True)
        entry = {
            'ts': time.time(),
            'type': decision_type,
            **details
        }
        with open(ORCHESTRATOR_LOG_PATH, 'a') as f:
            f.write(json.dumps(entry) + '\n')

    def update_price(self, symbol: str, price: float):
        """
        Update regime filter with latest price.
        Should be called on every price update.
        """
        self.regime_filter.add_price(symbol, price)
        self.last_update[symbol] = time.time()

    def get_regime(self, symbol: str) -> str:
        """Get current regime classification for symbol."""
        return self.regime_filter.get_regime(symbol)

    def should_block_strategy(self, symbol: str, strategy_name: str) -> Tuple[bool, str]:
        """
        Check if a strategy should be blocked based on regime.
        
        NOTE: CONVERTED - This function now always returns False (never blocks).
        Use get_regime_sizing_multiplier() for sizing adjustments.
        
        Args:
            symbol: Trading symbol
            strategy_name: Name of strategy (e.g., 'Trend-Conservative')
            
        Returns:
            (should_block, reason) - should_block is always False
        """
        # Map strategy name to type
        strategy_type = STRATEGY_TYPES.get(strategy_name, 'momentum')
        
        # Use new sizing multiplier method
        sizing_mult, reason = self.regime_filter.get_regime_sizing_multiplier(symbol, strategy_type)
        
        # Log sizing adjustment (no longer blocking)
        if sizing_mult < 1.0:
            self._log_decision('sizing_reduction', {
                'symbol': symbol,
                'strategy': strategy_name,
                'strategy_type': strategy_type,
                'sizing_multiplier': sizing_mult,
                'reason': reason
            })
        else:
            self.allowed_count += 1
        
        # Always return False (never blocks)
        return False, reason
    
    def get_regime_sizing_multiplier(self, symbol: str, strategy_name: str) -> Tuple[float, str]:
        """
        Get sizing multiplier based on regime alignment.
        
        Args:
            symbol: Trading symbol
            strategy_name: Name of strategy (e.g., 'Trend-Conservative')
            
        Returns:
            (sizing_multiplier, reason) - multiplier between 0.6x and 1.0x
        """
        strategy_type = STRATEGY_TYPES.get(strategy_name, 'momentum')
        return self.regime_filter.get_regime_sizing_multiplier(symbol, strategy_type)

    async def refresh_market_data(self, symbols: List[str]):
        """
        Refresh market data for multiple symbols asynchronously.
        """
        tasks = [self.data_aggregator.get_snapshot(s) for s in symbols]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        for symbol, result in zip(symbols, results):
            if isinstance(result, Exception):
                print(f"[PHASE2] Error refreshing {symbol}: {result}")
        
        return results

    def refresh_market_data_sync(self, symbols: List[str]):
        """
        Synchronous wrapper for market data refresh.
        Use in sync code paths.
        """
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                # Already in async context, schedule on executor
                future = self.executor.submit(
                    lambda: asyncio.run(self.refresh_market_data(symbols))
                )
                return future.result(timeout=5)
            else:
                return loop.run_until_complete(self.refresh_market_data(symbols))
        except Exception as e:
            print(f"[PHASE2] Sync refresh error: {e}")
            return []

    def get_ofi_signal(self, symbol: str) -> float:
        """Get current OFI signal for symbol."""
        return self.data_aggregator.get_smoothed_ofi(symbol)

    def is_data_fresh(self, symbol: str, max_age_sec: float = 2.0) -> bool:
        """Check if market data is fresh enough."""
        return self.data_aggregator.is_data_fresh(symbol, max_age_sec)

    def calculate_position_size(
        self,
        symbol: str,
        wallet_balance: float,
        price: float,
        win_rate: float,
        profit_factor: float,
        atr: float,
        confidence: float = 0.5
    ) -> Tuple[float, Dict]:
        """
        Calculate optimal position size using Phase 2 sizing.
        
        Returns:
            (size_usd, details_dict)
        """
        regime = self.get_regime(symbol)
        
        size, details = self.sizer.get_size(
            symbol=symbol,
            wallet_balance=wallet_balance,
            price=price,
            win_rate=win_rate,
            profit_factor=profit_factor,
            current_volatility_atr=atr,
            regime=regime,
            confidence=confidence
        )
        
        self._log_decision('sizing', {
            'symbol': symbol,
            'size_usd': size,
            'regime': regime,
            **details
        })
        
        return size, details

    def pre_trade_check(
        self,
        symbol: str,
        strategy_name: str,
        price: float,
        wallet_balance: float,
        win_rate: float,
        profit_factor: float,
        atr: float,
        confidence: float
    ) -> Dict:
        """
        Complete pre-trade check integrating all Phase 2 components.
        
        Returns comprehensive decision dict:
        - allowed: bool
        - size_usd: float
        - regime: str
        - ofi: float
        - reason: str
        """
        result = {
            'symbol': symbol,
            'strategy': strategy_name,
            'ts': time.time()
        }
        
        # 1. Update price and get regime
        self.update_price(symbol, price)
        regime = self.get_regime(symbol)
        result['regime'] = regime
        result['hurst'] = self.regime_filter.get_hurst_exponent(symbol)
        
        # 2. Check regime compatibility
        blocked, block_reason = self.should_block_strategy(symbol, strategy_name)
        if blocked:
            result['allowed'] = False
            result['size_usd'] = 0
            result['reason'] = block_reason
            return result
        
        # 3. Get OFI signal
        ofi = self.get_ofi_signal(symbol)
        result['ofi'] = ofi
        
        # 4. Calculate position size
        size, size_details = self.calculate_position_size(
            symbol, wallet_balance, price, win_rate, profit_factor, atr, confidence
        )
        
        result['size_usd'] = size
        result['kelly_fraction'] = size_details.get('kelly_fraction', 0)
        result['regime_mult'] = size_details.get('regime_mult', 1.0)
        
        # 5. Final decision
        if size > 0:
            result['allowed'] = True
            result['reason'] = 'passed_all_checks'
        else:
            result['allowed'] = False
            result['reason'] = size_details.get('reason', 'size_zero')
        
        self._log_decision('pre_trade', result)
        
        return result

    def get_stats(self) -> Dict:
        """Get orchestrator statistics."""
        total = self.blocked_count + self.allowed_count
        return {
            'blocked_count': self.blocked_count,
            'allowed_count': self.allowed_count,
            'block_rate': self.blocked_count / total if total > 0 else 0,
            'regimes': self.regime_filter.get_all_regimes()
        }

    def persist(self):
        """Save all state to disk."""
        self._save_state()
        self.regime_filter.persist()


# Global instance
_orchestrator: Optional[Phase2Orchestrator] = None

def get_orchestrator() -> Phase2Orchestrator:
    """Get or create the global Phase2Orchestrator instance."""
    global _orchestrator
    if _orchestrator is None:
        _orchestrator = Phase2Orchestrator()
    return _orchestrator

def pre_trade_check(
    symbol: str,
    strategy_name: str,
    price: float,
    wallet_balance: float,
    win_rate: float,
    profit_factor: float,
    atr: float,
    confidence: float
) -> Dict:
    """Convenience function for pre-trade checks."""
    return get_orchestrator().pre_trade_check(
        symbol, strategy_name, price, wallet_balance,
        win_rate, profit_factor, atr, confidence
    )

def update_price(symbol: str, price: float):
    """Update price in regime filter."""
    get_orchestrator().update_price(symbol, price)

def get_regime(symbol: str) -> str:
    """Get current market regime."""
    return get_orchestrator().get_regime(symbol)

def should_block_strategy(symbol: str, strategy_name: str) -> Tuple[bool, str]:
    """Check if strategy should be blocked."""
    return get_orchestrator().should_block_strategy(symbol, strategy_name)


if __name__ == "__main__":
    import asyncio
    
    print("Testing Phase 2 Orchestrator...")
    orch = Phase2Orchestrator()
    
    # Simulate price updates for trending market
    print("\nSimulating TRENDING market for BTCUSDT...")
    for i in range(110):
        orch.update_price("BTCUSDT", 95000 + i * 50)
    
    regime = orch.get_regime("BTCUSDT")
    print(f"Regime: {regime}")
    
    # Test strategy blocking
    blocked, reason = orch.should_block_strategy("BTCUSDT", "Mean-Reversion")
    print(f"Mean-Reversion: {reason}")
    
    blocked, reason = orch.should_block_strategy("BTCUSDT", "Trend-Conservative")
    print(f"Trend-Conservative: {reason}")
    
    # Test pre-trade check
    print("\nRunning pre-trade check...")
    result = orch.pre_trade_check(
        symbol="BTCUSDT",
        strategy_name="Trend-Conservative",
        price=100000,
        wallet_balance=10000,
        win_rate=0.55,
        profit_factor=1.5,
        atr=1500,
        confidence=0.7
    )
    print(json.dumps(result, indent=2))
    
    # Stats
    print("\nOrchestrator Stats:")
    print(json.dumps(orch.get_stats(), indent=2))
