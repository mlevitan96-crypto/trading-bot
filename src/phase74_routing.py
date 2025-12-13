"""
Phase 7.4 Liquidity-Aware Routing
Maker/taker selection based on queue position and order book imbalance
"""

from typing import Optional
from phase74_config import Phase74Config


class Phase74Routing:
    def __init__(self):
        self.recent_queue_estimates = {}
        self.recent_imbalances = {}
    
    def get_queue_position_estimate(self, symbol: str) -> float:
        try:
            from blofin_client import get_order_book_depth
            depth = get_order_book_depth(symbol)
            
            if not depth or not depth.get("bids") or not depth.get("asks"):
                return self.recent_queue_estimates.get(symbol, 0.5)
            
            bid_volume = sum(float(b[1]) for b in depth["bids"][:10])
            ask_volume = sum(float(a[1]) for a in depth["asks"][:10])
            total_volume = bid_volume + ask_volume
            
            if total_volume == 0:
                return 0.5
            
            queue_estimate = min(bid_volume, ask_volume) / (total_volume / 2)
            self.recent_queue_estimates[symbol] = queue_estimate
            return queue_estimate
        except Exception as e:
            return self.recent_queue_estimates.get(symbol, 0.5)
    
    def get_order_book_imbalance(self, symbol: str) -> float:
        try:
            from blofin_client import get_order_book_depth
            depth = get_order_book_depth(symbol)
            
            if not depth or not depth.get("bids") or not depth.get("asks"):
                return self.recent_imbalances.get(symbol, 0.5)
            
            bid_volume = sum(float(b[1]) for b in depth["bids"][:5])
            ask_volume = sum(float(a[1]) for a in depth["asks"][:5])
            total_volume = bid_volume + ask_volume
            
            if total_volume == 0:
                return 0.5
            
            imbalance = bid_volume / total_volume
            self.recent_imbalances[symbol] = imbalance
            return imbalance
        except Exception as e:
            return self.recent_imbalances.get(symbol, 0.5)
    
    def choose_route(self, symbol: str, config: Phase74Config) -> str:
        if not config.prefer_maker_when_queue_advantage:
            return "taker"
        
        queue_pos = self.get_queue_position_estimate(symbol)
        imbalance = self.get_order_book_imbalance(symbol)
        
        if queue_pos >= config.maker_queue_min and imbalance >= config.maker_imbalance_min:
            return "maker"
        
        return "taker"


_phase74_routing = None

def get_phase74_routing() -> Phase74Routing:
    global _phase74_routing
    if _phase74_routing is None:
        _phase74_routing = Phase74Routing()
    return _phase74_routing
