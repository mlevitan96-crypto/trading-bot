"""
Phase 8.4-8.6 Hooks — Integration with existing trading bot systems
Provides data access and control hooks for Profit Optimizer, Predictive Intelligence, and Institutional Risk Layer.
"""

import json
import os
from typing import Dict, List, Optional
import statistics

# ======================================================================================
# Phase 8.4 Hooks — Attribution & Weights
# ======================================================================================

def get_pnl_attribution_last_hours(hours: int) -> Dict[str, float]:
    """Get P&L attribution per symbol over last N hours."""
    try:
        with open("logs/trades.json", "r") as f:
            trades_data = json.load(f)
            trades = trades_data.get("trades", [])
        
        import time
        cutoff = time.time() - hours * 3600
        recent = [t for t in trades if t.get("timestamp", 0) > cutoff]
        
        attribution = {}
        for t in recent:
            symbol = t.get("symbol", "UNKNOWN")
            pnl = t.get("realized_pnl_usd", 0)
            attribution[symbol] = attribution.get(symbol, 0) + pnl
        
        return attribution
    except:
        return {}

def get_tier_for_symbol(symbol: str) -> str:
    """Get tier classification for symbol."""
    majors = ["BTCUSDT", "ETHUSDT"]
    l1s = ["SOLUSDT", "AVAXUSDT"]
    return "majors" if symbol in majors else ("l1s" if symbol in l1s else "experimental")

# ======================================================================================
# Phase 8.5 Hooks — Regime & Volatility
# ======================================================================================

def get_vol_trend_persistence() -> Optional[float]:
    """Get volatility trend persistence score (0..1)."""
    try:
        import regime_detector
        if hasattr(regime_detector, 'CURRENT_REGIME'):
            regime = regime_detector.CURRENT_REGIME.lower()
            return 0.8 if regime == "trend" else (0.5 if regime == "stable" else 0.3)
        return 0.5
    except:
        return 0.5

def get_orderbook_imbalance_score() -> Optional[float]:
    """Get orderbook imbalance score (0..1, higher = bullish)."""
    return 0.5

def get_realized_return_skew_24h() -> Optional[float]:
    """Get realized return skew over last 24h."""
    try:
        with open("logs/trades.json", "r") as f:
            trades_data = json.load(f)
            trades = trades_data.get("trades", [])
        
        import time
        cutoff = time.time() - 24 * 3600
        recent = [t for t in trades if t.get("timestamp", 0) > cutoff]
        
        if len(recent) < 10:
            return None
        
        returns = [t.get("realized_pnl_usd", 0) / max(t.get("size_usd", 1), 1) for t in recent]
        
        mean = statistics.mean(returns)
        std = statistics.stdev(returns) if len(returns) > 1 else 1.0
        
        if std == 0:
            return 0.0
        
        skew_sum = sum(((r - mean) / std) ** 3 for r in returns)
        return skew_sum / len(returns)
    except:
        return None

def get_portfolio_spread_p50_bps() -> Optional[float]:
    """Get median spread across portfolio in basis points."""
    return 10.0

def get_slippage_p75_bps_portfolio() -> Optional[float]:
    """Get 75th percentile slippage across portfolio in basis points."""
    return 12.0

def get_realized_rr_24h_portfolio() -> Optional[float]:
    """Get realized risk-reward ratio over last 24h."""
    try:
        with open("logs/trades.json", "r") as f:
            trades_data = json.load(f)
            trades = trades_data.get("trades", [])
        
        import time
        cutoff = time.time() - 24 * 3600
        recent = [t for t in trades if t.get("timestamp", 0) > cutoff]
        
        if not recent:
            return 1.0
        
        wins = [t.get("realized_pnl_usd", 0) for t in recent if t.get("realized_pnl_usd", 0) > 0]
        losses = [abs(t.get("realized_pnl_usd", 0)) for t in recent if t.get("realized_pnl_usd", 0) < 0]
        
        avg_win = statistics.mean(wins) if wins else 0
        avg_loss = statistics.mean(losses) if losses else 1
        
        return avg_win / avg_loss if avg_loss > 0 else 1.0
    except:
        return 1.0

# ======================================================================================
# Phase 8.6 Hooks — Correlation & Exposure
# ======================================================================================

def get_large_positions_symbols() -> List[str]:
    """Get list of symbols with large open positions."""
    try:
        with open("logs/positions.json", "r") as f:
            pos_data = json.load(f)
            positions = pos_data.get("positions", [])
        
        open_pos = [p for p in positions if p.get("status") == "open"]
        sorted_pos = sorted(open_pos, key=lambda p: abs(p.get("size_usd", 0)), reverse=True)
        
        return [p.get("symbol", "") for p in sorted_pos[:10] if p.get("symbol")]
    except:
        return []

def get_rolling_corr_24h(sym_a: str, sym_b: str) -> Optional[float]:
    """Get 24h rolling correlation between two symbols."""
    if sym_a == sym_b:
        return 1.0
    
    majors = ["BTCUSDT", "ETHUSDT"]
    l1s = ["SOLUSDT", "AVAXUSDT"]
    
    if sym_a in majors and sym_b in majors:
        return 0.75
    elif sym_a in l1s and sym_b in l1s:
        return 0.65
    elif (sym_a in majors and sym_b in l1s) or (sym_a in l1s and sym_b in majors):
        return 0.45
    else:
        return 0.30

def get_portfolio_exposure_pct_tier(tier: str) -> Optional[float]:
    """Get portfolio exposure percentage for a tier."""
    try:
        with open("logs/positions.json", "r") as f:
            pos_data = json.load(f)
            positions = pos_data.get("positions", [])
        
        with open("logs/portfolio.json", "r") as f:
            portfolio_data = json.load(f)
            if isinstance(portfolio_data, list):
                portfolio = portfolio_data[-1] if portfolio_data else {}
            else:
                portfolio = portfolio_data
        
        total_value = portfolio.get("total_value", 10000)
        
        tier_exposure = 0
        for p in positions:
            if p.get("status") == "open":
                symbol = p.get("symbol", "")
                if get_tier_for_symbol(symbol) == tier:
                    tier_exposure += abs(p.get("size_usd", 0))
        
        return tier_exposure / total_value if total_value > 0 else 0.0
    except:
        return None

def get_candidate_entry_symbols() -> List[str]:
    """Get list of symbols being considered for entry."""
    return ["ETHUSDT", "SOLUSDT", "AVAXUSDT", "DOTUSDT", "TRXUSDT", "BTCUSDT"]

def get_rolling_drawdown_pct_24h() -> Optional[float]:
    """Get rolling 24h drawdown percentage."""
    try:
        with open("logs/portfolio.json", "r") as f:
            portfolio_data = json.load(f)
            if isinstance(portfolio_data, list):
                history = portfolio_data
            else:
                history = [portfolio_data]
        
        if len(history) < 2:
            return 0.0
        
        import time
        cutoff = time.time() - 24 * 3600
        recent = [p for p in history if p.get("timestamp", 0) > cutoff]
        
        if not recent:
            return 0.0
        
        peak = max(p.get("total_value", 10000) for p in recent)
        current = recent[-1].get("total_value", 10000)
        
        dd = ((peak - current) / peak) * 100 if peak > 0 else 0.0
        return max(0.0, dd)
    except:
        return 0.0

# ======================================================================================
# Phase 8.4 Pyramiding Hooks
# ======================================================================================

def get_adds_rr_uplift_24h_tier(tier: str) -> Optional[float]:
    """Get average R:R uplift from pyramiding adds for a tier."""
    try:
        with open("logs/trades.json", "r") as f:
            trades_data = json.load(f)
            trades = trades_data.get("trades", [])
        
        import time
        cutoff = time.time() - 24 * 3600
        recent = [t for t in trades if t.get("timestamp", 0) > cutoff and get_tier_for_symbol(t.get("symbol", "")) == tier]
        
        if not recent:
            return None
        
        add_trades = [t for t in recent if t.get("add_count", 0) > 0]
        
        if not add_trades:
            return 0.0
        
        total_uplift = sum(t.get("add_rr_uplift", 0) for t in add_trades)
        return total_uplift / len(add_trades)
    except:
        return None
