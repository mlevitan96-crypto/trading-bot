"""
Phase 7.4 Pyramiding
Add to winning positions under controlled risk
"""

from typing import Dict
from phase74_config import Phase74Config
from phase74_exits import get_phase74_exits


class Phase74Pyramiding:
    def __init__(self):
        self.exits = get_phase74_exits()
    
    def can_pyramid(self, position: Dict, config: Phase74Config) -> bool:
        adds = position.get("pyramid_adds", 0)
        
        if adds >= config.pyramid_max_adds:
            return False
        
        r = self.exits.current_r_multiple(position)
        if r is None:
            return False
        
        return r >= config.pyramid_trigger_r_multiple
    
    def build_pyramid_add(self, position: Dict, config: Phase74Config) -> Dict:
        base_size = position.get("initial_size_units", position.get("size_units", 0))
        add_size = base_size * config.pyramid_add_size_fraction
        
        current_step = position.get("trailing_step_bps", config.trailing_step_bps)
        position["trailing_step_bps"] = min(
            config.trailing_max_bps,
            current_step + config.pyramid_trailing_tighten_bps
        )
        
        return {
            "symbol": position["symbol"],
            "side": position["side"],
            "size_units": add_size,
            "route": "taker",
            "is_pyramid_add": True
        }
    
    def apply_pyramiding(self, position: Dict, config: Phase74Config) -> bool:
        if not self.can_pyramid(position, config):
            return False
        
        add_order = self.build_pyramid_add(position, config)
        
        position["pyramid_adds"] = position.get("pyramid_adds", 0) + 1
        
        print(f"ℹ️  PHASE74: {position['symbol']} pyramiding add #{position['pyramid_adds']} (size={add_order['size_units']:.4f})")
        
        return True


_phase74_pyramiding = None

def get_phase74_pyramiding() -> Phase74Pyramiding:
    global _phase74_pyramiding
    if _phase74_pyramiding is None:
        _phase74_pyramiding = Phase74Pyramiding()
    return _phase74_pyramiding
