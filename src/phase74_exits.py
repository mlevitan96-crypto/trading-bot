"""
Phase 7.4 Precision Exits
Adaptive trailing, volatility stops, profit unlocks, time decay
"""

import time
from typing import Optional, Dict
from phase74_config import Phase74Config


class Phase74Exits:
    def __init__(self):
        pass
    
    def current_r_multiple(self, position: Dict) -> Optional[float]:
        try:
            entry_price = position.get("entry_price", 0)
            current_price = position.get("current_price", 0)
            stop_price = position.get("stop_price", entry_price)
            side = position.get("side", "long")
            
            if entry_price == 0 or stop_price == 0 or current_price == 0:
                return None
            
            risk_per_unit = abs(entry_price - stop_price)
            if risk_per_unit == 0:
                return None
            
            if side == "long":
                pnl_per_unit = current_price - entry_price
            else:
                pnl_per_unit = entry_price - current_price
            
            return pnl_per_unit / risk_per_unit
        except Exception:
            return None
    
    def atr_bps(self, symbol: str) -> Optional[float]:
        try:
            from blofin_futures_client import BlofinFuturesClient
            client = BlofinFuturesClient()
            
            instrument_id = f"{symbol[:3]}-USDT"
            candles = client.get_candles(instrument_id, bar="1H", limit=24)
            
            if not candles or len(candles) < 2:
                return 150.0
            
            highs = [float(c[2]) for c in candles]
            lows = [float(c[3]) for c in candles]
            closes = [float(c[4]) for c in candles]
            
            trs = []
            for i in range(1, len(candles)):
                hl = highs[i] - lows[i]
                hc = abs(highs[i] - closes[i-1])
                lc = abs(lows[i] - closes[i-1])
                trs.append(max(hl, hc, lc))
            
            if not trs:
                return 150.0
            
            atr = sum(trs) / len(trs)
            avg_price = sum(closes) / len(closes)
            
            return (atr / avg_price) * 10000.0
        except Exception:
            return 150.0
    
    def compute_vol_stop_price(self, position: Dict, config: Phase74Config) -> float:
        atr = self.atr_bps(position["symbol"])
        risk_bps = (atr or 150) * config.vol_stop_k
        
        entry_price = position["entry_price"]
        side = position["side"]
        
        if side == "long":
            return entry_price * (1.0 - risk_bps / 10000.0)
        else:
            return entry_price * (1.0 + risk_bps / 10000.0)
    
    def precision_exit_update(self, position: Dict, config: Phase74Config):
        r = self.current_r_multiple(position)
        if r is None:
            return
        
        if r >= config.trailing_start_r:
            position["trailing_active"] = True
            current_step = position.get("trailing_step_bps", config.trailing_step_bps)
            position["trailing_step_bps"] = min(config.trailing_max_bps, current_step)
        
        if r >= config.tp_unlock_r:
            tp_price = position.get("tp_price")
            if tp_price:
                position["tp_price"] = tp_price * config.tp_widen_factor
        
        position["vol_stop_price"] = self.compute_vol_stop_price(position, config)
    
    def time_decay_exit(self, position: Dict, config: Phase74Config) -> bool:
        entry_ts = position.get("entry_ts", time.time())
        held_min = (time.time() - entry_ts) / 60.0
        r = self.current_r_multiple(position)
        
        if held_min >= config.time_decay_minutes:
            if r is None or r < config.time_progress_r_threshold:
                return True
        
        return False


_phase74_exits = None

def get_phase74_exits() -> Phase74Exits:
    global _phase74_exits
    if _phase74_exits is None:
        _phase74_exits = Phase74Exits()
    return _phase74_exits
