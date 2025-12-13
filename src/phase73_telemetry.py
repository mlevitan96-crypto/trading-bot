"""
Phase 7.3 Telemetry
Provides metrics for dynamic controller
"""

import json
import os
from typing import Dict, List, Tuple, Optional
from datetime import datetime, timedelta
from phase72_tiers import tier_for_symbol


class Phase73Telemetry:
    def __init__(self):
        self.signals_log = "logs/futures_attribution.json"
        self.trades_log = "logs/closed_trades.json"
        self.blocks_log = "logs/phase73_blocks.json"
    
    def get_execution_rate_24h_tier(self, tier: str) -> float:
        try:
            signals_file = "logs/signals_history.json"
            if not os.path.exists(signals_file):
                return 0.5
            
            with open(signals_file, 'r') as f:
                signals = json.load(f)
            
            cutoff = datetime.now() - timedelta(hours=24)
            cutoff_ts = cutoff.timestamp()
            
            total = 0
            executed = 0
            
            for sig in signals:
                if sig.get("ts", 0) < cutoff_ts:
                    continue
                symbol = sig.get("symbol", "")
                if tier_for_symbol(symbol) == tier:
                    total += 1
                    if sig.get("executed", False):
                        executed += 1
            
            return (executed / total) if total > 0 else 0.5
        except Exception:
            return 0.5
    
    def get_realized_rr_24h_tier(self, tier: str) -> Optional[float]:
        try:
            if not os.path.exists(self.trades_log):
                return None
            
            with open(self.trades_log, 'r') as f:
                trades = json.load(f)
            
            cutoff = datetime.now() - timedelta(hours=24)
            cutoff_ts = cutoff.timestamp()
            
            rrs = []
            for trade in trades:
                if trade.get("exit_ts", 0) < cutoff_ts:
                    continue
                symbol = trade.get("symbol", "")
                if tier_for_symbol(symbol) == tier:
                    pnl = trade.get("pnl_usd_realized", 0)
                    risk = abs(trade.get("entry_price", 0) - trade.get("stop_price", trade.get("entry_price", 0))) * trade.get("size_units", 0)
                    if risk > 0:
                        rrs.append(pnl / risk)
            
            return sum(rrs) / len(rrs) if rrs else None
        except Exception:
            return None
    
    def get_realized_vol_24h(self, symbol: str) -> Optional[float]:
        try:
            if not os.path.exists(self.trades_log):
                return None
            
            with open(self.trades_log, 'r') as f:
                trades = json.load(f)
            
            cutoff = datetime.now() - timedelta(hours=24)
            cutoff_ts = cutoff.timestamp()
            
            returns = []
            for trade in trades:
                if trade.get("exit_ts", 0) < cutoff_ts or trade.get("symbol") != symbol:
                    continue
                entry_price = trade.get("entry_price", 0)
                exit_price = trade.get("exit_price", 0)
                if entry_price > 0:
                    ret = (exit_price - entry_price) / entry_price
                    returns.append(abs(ret))
            
            if not returns:
                return None
            
            avg_vol = sum(returns) / len(returns)
            return min(1.0, avg_vol * 10)
        except Exception:
            return None
    
    def get_liquidity_score_24h(self, symbol: str) -> Optional[float]:
        try:
            if not os.path.exists(self.trades_log):
                return None
            
            with open(self.trades_log, 'r') as f:
                trades = json.load(f)
            
            cutoff = datetime.now() - timedelta(hours=24)
            cutoff_ts = cutoff.timestamp()
            
            slippages = []
            for trade in trades:
                if trade.get("exit_ts", 0) < cutoff_ts or trade.get("symbol") != symbol:
                    continue
                slippage = trade.get("slippage_bps", 0)
                slippages.append(abs(slippage))
            
            if not slippages:
                return None
            
            avg_slip = sum(slippages) / len(slippages)
            return max(0.0, min(1.0, 1.0 - (avg_slip / 20.0)))
        except Exception:
            return None
    
    def get_shorts_stats_symbol(self, symbol: str, window: int) -> Tuple[float, float, int]:
        try:
            attr_file = "logs/futures_attribution.json"
            if not os.path.exists(attr_file):
                return (0.0, 0.0, 0)
            
            with open(attr_file, 'r') as f:
                data = json.load(f)
            
            symbol_data = data.get("per_symbol", {}).get(symbol, {})
            short_data = symbol_data.get("SHORT", {})
            
            trades_count = short_data.get("trades", 0)
            wins = short_data.get("wins", 0)
            pnl = short_data.get("pnl_usd", 0.0)
            
            wr = (wins / trades_count) if trades_count > 0 else 0.0
            return (wr, pnl, trades_count)
        except Exception:
            return (0.0, 0.0, 0)
    
    def get_shorts_rr_skew(self, symbol: str, window: int) -> Optional[float]:
        try:
            if not os.path.exists(self.trades_log):
                return None
            
            with open(self.trades_log, 'r') as f:
                trades = json.load(f)
            
            wins = []
            losses = []
            
            short_trades = [t for t in trades if t.get("symbol") == symbol and t.get("side") == "short"][-window:]
            
            for trade in short_trades:
                pnl = trade.get("pnl_usd_realized", 0)
                if pnl > 0:
                    wins.append(pnl)
                elif pnl < 0:
                    losses.append(abs(pnl))
            
            if not wins or not losses:
                return None
            
            win_median = sorted(wins)[len(wins) // 2]
            loss_median = sorted(losses)[len(losses) // 2]
            
            return win_median / loss_median if loss_median > 0 else None
        except Exception:
            return None
    
    def get_shorts_slippage_p75(self, symbol: str, window: int) -> Optional[float]:
        try:
            if not os.path.exists(self.trades_log):
                return None
            
            with open(self.trades_log, 'r') as f:
                trades = json.load(f)
            
            slippages = []
            short_trades = [t for t in trades if t.get("symbol") == symbol and t.get("side") == "short"][-window:]
            
            for trade in short_trades:
                slippage = abs(trade.get("slippage_bps", 0))
                slippages.append(slippage)
            
            if not slippages:
                return None
            
            slippages.sort()
            p75_idx = int(len(slippages) * 0.75)
            return slippages[p75_idx]
        except Exception:
            return None
    
    def get_blocked_reasons_symbol(self, symbol: str, hours: int) -> List[str]:
        try:
            if not os.path.exists(self.blocks_log):
                return []
            
            with open(self.blocks_log, 'r') as f:
                blocks = json.load(f)
            
            cutoff = datetime.now() - timedelta(hours=hours)
            cutoff_ts = cutoff.timestamp()
            
            reasons = []
            for block in blocks:
                if block.get("ts", 0) < cutoff_ts or block.get("symbol") != symbol:
                    continue
                reasons.append(block.get("reason", "unknown"))
            
            return reasons
        except Exception:
            return []
    
    def get_fees_symbol(self, symbol: str, hours: int) -> Tuple[float, float]:
        try:
            if not os.path.exists(self.trades_log):
                return (0.0, 0.0)
            
            with open(self.trades_log, 'r') as f:
                trades = json.load(f)
            
            cutoff = datetime.now() - timedelta(hours=hours)
            cutoff_ts = cutoff.timestamp()
            
            maker_fees = 0.0
            taker_fees = 0.0
            
            for trade in trades:
                if trade.get("exit_ts", 0) < cutoff_ts or trade.get("symbol") != symbol:
                    continue
                maker_fees += trade.get("maker_fees_usd", 0.0)
                taker_fees += trade.get("taker_fees_usd", 0.0)
            
            return (maker_fees, taker_fees)
        except Exception:
            return (0.0, 0.0)


_phase73_telemetry = None

def get_phase73_telemetry() -> Phase73Telemetry:
    global _phase73_telemetry
    if _phase73_telemetry is None:
        _phase73_telemetry = Phase73Telemetry()
    return _phase73_telemetry
