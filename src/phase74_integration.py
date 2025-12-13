"""
Phase 7.4 Integration
Wires Profit Engine into bot cycle with complete position management
"""

import time
import json
import threading
from typing import Dict, List
from phase74_config import default_phase74_cfg, Phase74Config
from phase74_expectancy import get_phase74_expectancy
from phase74_sizing import get_phase74_sizing
from phase74_exits import get_phase74_exits
from phase74_pyramiding import get_phase74_pyramiding
from phase74_routing import get_phase74_routing
from phase74_nudges import get_phase74_nudges
from phase75_monitor import get_phase75_monitor
from phase76_performance import get_phase76_performance


class Phase74Integration:
    def __init__(self):
        self.config = default_phase74_cfg()
        self.expectancy = get_phase74_expectancy()
        self.sizing = get_phase74_sizing()
        self.exits = get_phase74_exits()
        self.pyramiding = get_phase74_pyramiding()
        self.routing = get_phase74_routing()
        self.nudges = get_phase74_nudges()
        self.monitor = get_phase75_monitor()
        self.performance = get_phase76_performance()
        self.running = False
        self.position_manager_thread = None
        self.last_position_check = 0
        self.hourly_check_timer = 0
        self.tier_controller_timer = 0
        self.symbol_controller_timer = 0
        self.phase76_hourly_timer = 0
    
    def start(self):
        if self.running:
            return
        
        self.running = True
        self.nudges.enable_ev_temp_for_majors()
        self.position_manager_thread = threading.Thread(
            target=self._position_manager_loop,
            daemon=True
        )
        self.position_manager_thread.start()
        print("✅ Phase 7.4 Profit Engine started")
        print("✅ Phase 7.4 Performance Nudges enabled")
    
    def _position_manager_loop(self):
        while self.running:
            try:
                from position_manager import get_open_positions, get_open_futures_positions, close_position, scale_into_position
                from blofin_client import get_current_price
                
                if time.time() - self.hourly_check_timer >= 3600:
                    try:
                        with open("logs/trades.json", "r") as f:
                            trades_data = json.load(f)
                            majors_trades = [t for t in trades_data.get("trades", [])
                                           if t.get("symbol", "").replace("USDT", "") in {"BTC", "ETH"}
                                           and t.get("exit_ts", 0) > time.time() - 86400]
                            
                            if majors_trades:
                                net_pnl = sum(t.get("realized_pnl_usd", 0) for t in majors_trades)
                                total_size = sum(abs(t.get("size_usd", 0)) for t in majors_trades)
                                realized_rr = net_pnl / total_size if total_size > 0 else None
                            else:
                                realized_rr = None
                    except:
                        realized_rr = None
                    
                    self.nudges.maybe_revert_ev_temp_for_majors(realized_rr)
                    self.hourly_check_timer = time.time()
                
                if time.time() - self.tier_controller_timer >= 3600:
                    self.monitor.tier_controller_tick()
                    self.tier_controller_timer = time.time()
                
                if time.time() - self.symbol_controller_timer >= 900:
                    self.monitor.symbol_controller_tick()
                    self.symbol_controller_timer = time.time()
                
                if time.time() - self.phase76_hourly_timer >= 3600:
                    self.performance.hourly_tick()
                    self.phase76_hourly_timer = time.time()
                
                spot_positions = get_open_positions()
                futures_positions = get_open_futures_positions()
                all_positions = spot_positions + futures_positions
                
                if all_positions:
                    self.last_position_check = time.time()
                    
                    try:
                        with open("logs/portfolio_hourly.json", "r") as f:
                            portfolio_data = json.load(f)
                            portfolio_value = portfolio_data.get("current_value", 10000)
                    except:
                        portfolio_value = 10000
                    
                    try:
                        with open("logs/regime_history.json", "r") as f:
                            regime_data = json.load(f)
                            current_regime = regime_data.get("current_regime", "stable")
                    except:
                        current_regime = "stable"
                    
                    for pos in all_positions:
                        try:
                            symbol = pos.get("symbol", "")
                            strategy = pos.get("strategy", "unknown")
                            current_price = get_current_price(symbol)
                            
                            if not current_price:
                                continue
                            
                            pos["current_price"] = current_price
                            
                            self.precision_exit_update_nudged(pos, current_regime)
                            
                            if self.time_decay_exit_nudged(pos, current_regime):
                                print(f"ℹ️  PHASE74: Time decay exit for {symbol}")
                                close_position(symbol, strategy, current_price, reason="time_decay_phase74")
                                continue
                            
                            if self.monitor.should_allow_pyramiding(symbol) and self.apply_pyramiding_nudged(pos, current_regime):
                                print(f"ℹ️  PHASE74: Pyramiding for {symbol}")
                                scale_into_position(symbol, current_price, strategy, portfolio_value)
                        except Exception as e:
                            print(f"⚠️  PHASE74: Position processing error for {pos.get('symbol', 'unknown')}: {str(e)}")
                
            except Exception as e:
                print(f"⚠️  PHASE74: Position manager loop error: {str(e)}")
            
            time.sleep(30)
    
    def expectancy_gate(self, signal) -> tuple[bool, str]:
        symbol = signal.get("symbol", "")
        ev_gate = self.monitor.ev_gate_for_entry(symbol)
        
        phase76_ev_gate = self.performance.ev_gate_for_entry(symbol)
        if phase76_ev_gate is not None:
            ev_gate = phase76_ev_gate
        
        ev_bonus = self.performance.losing_streak_ev_bonus(symbol)
        ev_gate += ev_bonus
        
        old_ev_gate = self.config.min_expected_value_usd
        self.config.min_expected_value_usd = ev_gate
        result = self.expectancy.expectancy_gate(signal, self.config)
        self.config.min_expected_value_usd = old_ev_gate
        return result
    
    def sizing_multiplier(self, symbol: str) -> float:
        base = self.sizing.sizing_multiplier(symbol, self.config)
        monitor_mult = self.monitor.size_multiplier_for_symbol(symbol)
        phase76_mult = self.performance.size_multiplier_for_entry(symbol)
        
        size_cap = self.monitor.size_cap_for_entry(symbol)
        phase76_cap = self.performance.size_cap_for_entry(symbol)
        if phase76_cap is not None:
            size_cap = phase76_cap
        
        return min(base * monitor_mult * phase76_mult, size_cap)
    
    def precision_exit_update(self, position: Dict):
        self.exits.precision_exit_update(position, self.config)
    
    def time_decay_exit(self, position: Dict) -> bool:
        return self.exits.time_decay_exit(position, self.config)
    
    def apply_pyramiding(self, position: Dict) -> bool:
        return self.pyramiding.apply_pyramiding(position, self.config)
    
    def apply_pyramiding_nudged(self, position: Dict, regime: str) -> bool:
        trigger_r = self.nudges.pyramid_trigger_r(regime)
        r = position.get("unrealized_pnl_pct", 0.0)
        adds = position.get("pyramid_adds", 0)
        
        position_temp = position.copy()
        position_temp["entry_price"] = position.get("entry_price", 0)
        position_temp["current_price"] = position.get("current_price", 0)
        
        old_trigger = self.config.pyramid_trigger_r_multiple
        self.config.pyramid_trigger_r_multiple = trigger_r
        result = self.pyramiding.apply_pyramiding(position_temp, self.config)
        self.config.pyramid_trigger_r_multiple = old_trigger
        
        if result:
            position["pyramid_adds"] = position_temp.get("pyramid_adds", 0)
        
        return result
    
    def precision_exit_update_nudged(self, position: Dict, regime: str):
        old_trailing_start = self.config.trailing_start_r
        self.config.trailing_start_r = self.nudges.trailing_start_r(regime)
        self.exits.precision_exit_update(position, self.config)
        self.config.trailing_start_r = old_trailing_start
    
    def time_decay_exit_nudged(self, position: Dict, regime: str) -> bool:
        old_time_decay_minutes = self.config.time_decay_minutes
        self.config.time_decay_minutes = self.nudges.time_decay_minutes_for(position, regime)
        result = self.exits.time_decay_exit(position, self.config)
        self.config.time_decay_minutes = old_time_decay_minutes
        return result
    
    def choose_route(self, symbol: str) -> str:
        return self.routing.choose_route(symbol, self.config)
    
    def choose_route_nudged(self, symbol: str) -> str:
        q = self.routing.get_queue_position_estimate(symbol)
        imb = self.routing.get_order_book_imbalance(symbol)
        
        if q >= self.nudges.config.maker_queue_min and imb >= self.nudges.config.maker_imbalance_min:
            return "maker"
        return "taker"
    
    def expectancy_gate_nudged(self, signal) -> tuple[bool, str]:
        ev_threshold = self.nudges.ev_gate_usd(signal.symbol)
        passed, reason = self.expectancy.expectancy_gate(signal, self.config)
        
        if not passed:
            return False, reason
        
        ev = getattr(signal, 'expected_value', 0.0)
        if ev < ev_threshold:
            return False, f"EV ${ev:.2f} < nudged threshold ${ev_threshold:.2f}"
        
        return True, ""
    
    def get_status(self) -> Dict:
        return {
            "running": self.running,
            "last_position_check": self.last_position_check,
            "config": {
                "min_expected_value_usd": self.config.min_expected_value_usd,
                "size_ramp_up_pct": self.config.size_ramp_up_pct,
                "pyramid_max_adds": self.config.pyramid_max_adds,
                "trailing_start_r": self.config.trailing_start_r,
                "time_decay_minutes": self.config.time_decay_minutes,
                "prefer_maker_when_queue_advantage": self.config.prefer_maker_when_queue_advantage
            },
            "size_multipliers": self.sizing.size_multipliers,
            "nudges": self.nudges.get_status()
        }


_phase74_integration = None

def get_phase74_integration() -> Phase74Integration:
    global _phase74_integration
    if _phase74_integration is None:
        _phase74_integration = Phase74Integration()
    return _phase74_integration
