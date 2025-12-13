"""
Phase 7.3 Integration
Wires Phase 7.3 into the bot cycle and initializes controller
"""

import time
import threading
from phase73_config import default_phase73_cfg
from phase73_controller import get_phase73_controller
from phase73_telemetry import get_phase73_telemetry
from phase73_shorts import short_allowed


class Phase73Integration:
    def __init__(self):
        self.config = default_phase73_cfg()
        self.controller = get_phase73_controller()
        self.telemetry = get_phase73_telemetry()
        self.running = False
        self.controller_thread = None
        self.symbols = ["ETHUSDT", "SOLUSDT", "AVAXUSDT", "DOTUSDT", "TRXUSDT", "BTCUSDT"]
    
    def start(self):
        if self.running:
            return
        
        self.running = True
        self.controller_thread = threading.Thread(target=self._controller_loop, daemon=True)
        self.controller_thread.start()
        print("✅ Phase 7.3 Self-Tuning Controller started")
    
    def _controller_loop(self):
        while self.running:
            try:
                if self.controller.should_run_controller():
                    print("ℹ️  PHASE73: Running hourly controller...")
                    self.controller.controller_adjust_relaxation(self.telemetry)
                    self.controller.autotune_min_hold(self.telemetry, self.symbols)
                    print("✅ PHASE73: Controller run completed")
            except Exception as e:
                print(f"⚠️  PHASE73: Controller error: {str(e)}")
            
            time.sleep(60)
    
    def pre_entry_gate(self, signal, regime_name: str, base_threshold: float) -> tuple[bool, str]:
        thr = self.controller.relaxed_threshold(signal.symbol, regime_name, base_threshold)
        
        if signal.ensemble_score < thr:
            return (False, f"low_ensemble:{signal.ensemble_score:.3f}<{thr:.3f}")
        
        if signal.side == "short":
            allowed, reason = short_allowed(signal.symbol, self.config)
            if not allowed:
                return (False, f"short_suppressed:{reason}")
        
        return (True, "passed")
    
    def enforce_min_hold_on_exit(self, position) -> tuple[bool, str]:
        entry_ts = position.get("entry_ts")
        if not entry_ts:
            return (True, "no_entry_ts")
        
        held = time.time() - entry_ts
        req = self.controller.current_min_hold(position["symbol"])
        
        if held < req:
            return (False, f"min_hold:{held:.0f}s<{req}s")
        
        return (True, "passed")
    
    def get_status(self):
        return {
            "running": self.running,
            "controller_status": self.controller.get_status(),
            "config": {
                "relax_step_per_hour": self.config.relax_step_per_hour,
                "target_exec_rate_min": self.config.target_exec_rate_min,
                "target_rr_min": self.config.target_rr_min,
                "min_hold_bounds_sec": self.config.min_hold_bounds_sec,
                "shorts_min_rr_skew": self.config.shorts_min_rr_skew,
                "shorts_slippage_p75_cap_bps": self.config.shorts_slippage_p75_cap_bps
            }
        }


_phase73_integration = None

def get_phase73_integration() -> Phase73Integration:
    global _phase73_integration
    if _phase73_integration is None:
        _phase73_integration = Phase73Integration()
    return _phase73_integration
