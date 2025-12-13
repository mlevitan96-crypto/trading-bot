import time
import json
from dataclasses import dataclass, field
from typing import Dict, List, Tuple, Optional

@dataclass
class Phase75Config:
    exec_target_min: float = 0.15
    exec_target_max: float = 0.25

    rr_min_tier: Dict[str, float] = field(default_factory=lambda: {
        "majors": 1.00, "l1s": 0.95, "experimental": 0.90
    })

    slip_cap_tier: Dict[str, float] = field(default_factory=lambda: {
        "majors": 12.0, "l1s": 15.0, "experimental": 18.0
    })

    max_drawdown_pct: float = 3.0

    throttle_size_reduction_pct: float = 0.25
    throttle_duration_hours: int = 24

    relax_nudge_step: float = 0.005

    ev_gate_default_usd: Dict[str, float] = field(default_factory=lambda: {
        "majors": 0.50, "l1s": 0.50, "experimental": 0.60
    })
    ev_gate_temp_usd_majors: float = 0.40

    majors_size_cap_temp: float = 2.5
    majors_size_cap_default: float = 2.0

def default_phase75_cfg() -> Phase75Config:
    return Phase75Config()

class Phase75Monitor:
    def __init__(self, config: Phase75Config):
        self.config = config
        self._throttle_until_ts_tier: Dict[str, float] = {}
        self._freeze_pyramiding_until_ts_tier: Dict[str, float] = {}
        self._ev_gate_overrides_tier: Dict[str, float] = {}
        self._size_cap_overrides_tier: Dict[str, float] = {}
        self._size_multipliers_symbol: Dict[str, float] = {}
        self._pyramiding_disabled_until_symbol: Dict[str, float] = {}
        
        self.last_tier_tick = 0
        self.last_symbol_tick = 0
        
    def now(self) -> float:
        return time.time()
    
    def is_throttled(self, tier: str) -> bool:
        return self._throttle_until_ts_tier.get(tier, 0) > self.now()
    
    def is_frozen_pyramiding(self, tier: str) -> bool:
        return self._freeze_pyramiding_until_ts_tier.get(tier, 0) > self.now()
    
    def is_pyramiding_disabled_symbol(self, symbol: str) -> bool:
        return self._pyramiding_disabled_until_symbol.get(symbol, 0) > self.now()
    
    def tier_for_symbol(self, symbol: str) -> str:
        base = symbol.replace("USDT", "").replace("-", "")
        if base in {"BTC", "ETH"}:
            return "majors"
        elif base in {"SOL", "AVAX"}:
            return "l1s"
        else:
            return "experimental"
    
    def execution_rate_24h_tier(self, tier: str) -> Optional[float]:
        try:
            with open("logs/phase73_audit.json", "r") as f:
                audit = json.load(f)
                signals = audit.get("signals_evaluated", [])
                recent = [s for s in signals if s.get("ts", 0) > self.now() - 86400]
                tier_signals = [s for s in recent if self.tier_for_symbol(s.get("symbol", "")) == tier]
                
                if not tier_signals:
                    return None
                
                executed = sum(1 for s in tier_signals if s.get("outcome") == "executed")
                return executed / len(tier_signals)
        except:
            return None
    
    def realized_rr_24h_tier(self, tier: str) -> Optional[float]:
        try:
            with open("logs/trades.json", "r") as f:
                trades_data = json.load(f)
                trades = trades_data.get("trades", [])
                recent = [t for t in trades 
                         if t.get("exit_ts", 0) > self.now() - 86400
                         and self.tier_for_symbol(t.get("symbol", "")) == tier]
                
                if not recent:
                    return None
                
                net_pnl = sum(t.get("realized_pnl_usd", 0) for t in recent)
                total_size = sum(abs(t.get("size_usd", 0)) for t in recent)
                
                return net_pnl / total_size if total_size > 0 else None
        except:
            return None
    
    def slippage_p75_bps_tier(self, tier: str) -> Optional[float]:
        try:
            with open("logs/trades.json", "r") as f:
                trades_data = json.load(f)
                trades = trades_data.get("trades", [])
                recent = [t for t in trades 
                         if t.get("exit_ts", 0) > self.now() - 86400
                         and self.tier_for_symbol(t.get("symbol", "")) == tier]
                
                if not recent:
                    return None
                
                slippages = [t.get("slippage_bps", 0) for t in recent if "slippage_bps" in t]
                if not slippages:
                    return None
                
                slippages.sort()
                p75_idx = int(len(slippages) * 0.75)
                return slippages[p75_idx]
        except:
            return None
    
    def rolling_drawdown_pct_24h(self) -> Optional[float]:
        try:
            with open("logs/portfolio.json", "r") as f:
                portfolio_data = json.load(f)
                snapshots = portfolio_data.get("hourly_snapshots", [])
                recent = [s for s in snapshots if s.get("timestamp", 0) > self.now() - 86400]
                
                if not recent:
                    return None
                
                values = [s.get("total_value", 0) for s in recent]
                peak = max(values)
                current = values[-1] if values else 0
                
                if peak == 0:
                    return None
                
                drawdown_pct = ((peak - current) / peak) * 100
                return max(0, drawdown_pct)
        except:
            return None
    
    def realized_rr_24h_symbol(self, symbol: str) -> Optional[float]:
        try:
            with open("logs/trades.json", "r") as f:
                trades_data = json.load(f)
                trades = trades_data.get("trades", [])
                recent = [t for t in trades 
                         if t.get("exit_ts", 0) > self.now() - 86400
                         and t.get("symbol") == symbol]
                
                if not recent:
                    return None
                
                net_pnl = sum(t.get("realized_pnl_usd", 0) for t in recent)
                total_size = sum(abs(t.get("size_usd", 0)) for t in recent)
                
                return net_pnl / total_size if total_size > 0 else None
        except:
            return None
    
    def slippage_p75_bps_symbol(self, symbol: str, window_trades: int = 50) -> Optional[float]:
        try:
            with open("logs/trades.json", "r") as f:
                trades_data = json.load(f)
                trades = trades_data.get("trades", [])
                symbol_trades = [t for t in trades if t.get("symbol") == symbol]
                recent = symbol_trades[-window_trades:] if len(symbol_trades) > window_trades else symbol_trades
                
                if not recent:
                    return None
                
                slippages = [t.get("slippage_bps", 0) for t in recent if "slippage_bps" in t]
                if not slippages:
                    return None
                
                slippages.sort()
                p75_idx = int(len(slippages) * 0.75)
                return slippages[p75_idx]
        except:
            return None
    
    def expected_value_usd(self, symbol: str) -> Optional[float]:
        return None
    
    def list_all_symbols(self) -> List[str]:
        return ["ETHUSDT", "SOLUSDT", "AVAXUSDT", "DOTUSDT", "TRXUSDT", "BTCUSDT"]
    
    def decide_tier_action(self, tier: str) -> str:
        exec_rate = self.execution_rate_24h_tier(tier)
        rr = self.realized_rr_24h_tier(tier)
        slip = self.slippage_p75_bps_tier(tier)
        dd = self.rolling_drawdown_pct_24h()
        
        if dd is not None and dd > self.config.max_drawdown_pct:
            return "freeze"
        
        rr_min = self.config.rr_min_tier.get(tier, 0.95)
        slip_cap = self.config.slip_cap_tier.get(tier, 15.0)
        
        if (rr is not None and rr < rr_min) or (slip is not None and slip > slip_cap):
            return "throttle"
        
        if (exec_rate is not None and self.config.exec_target_min <= exec_rate <= self.config.exec_target_max) and (rr is None or rr >= rr_min):
            return "go"
        
        return "hold"
    
    def apply_tier_action(self, tier: str, action: str):
        if action == "freeze":
            self._freeze_pyramiding_until_ts_tier[tier] = self.now() + 3600
            self._ev_gate_overrides_tier[tier] = self.config.ev_gate_default_usd.get(tier, 0.50)
            print(f"⚠️  PHASE75 FREEZE: {tier} - pyramiding disabled, EV gate reset to baseline")
        
        elif action == "throttle":
            self._throttle_until_ts_tier[tier] = self.now() + self.config.throttle_duration_hours * 3600
            self._ev_gate_overrides_tier[tier] = self.config.ev_gate_default_usd.get(tier, 0.50)
            print(f"⚠️  PHASE75 THROTTLE: {tier} - size reduced 25% for 24h, EV gate reset")
        
        elif action == "go":
            if tier == "majors":
                self._ev_gate_overrides_tier[tier] = self.config.ev_gate_temp_usd_majors
                self._size_cap_overrides_tier[tier] = self.config.majors_size_cap_temp
                print(f"✅ PHASE75 GO: {tier} - EV gate relaxed to ${self.config.ev_gate_temp_usd_majors:.2f}, size cap ${self.config.majors_size_cap_temp}x")
            else:
                print(f"✅ PHASE75 GO: {tier} - quality targets met, maintaining parameters")
        
        else:
            if not self.is_throttled(tier):
                self._ev_gate_overrides_tier.pop(tier, None)
                if tier == "majors":
                    self._size_cap_overrides_tier[tier] = self.config.majors_size_cap_default
    
    def decide_symbol_action(self, symbol: str) -> str:
        tier = self.tier_for_symbol(symbol)
        rr = self.realized_rr_24h_symbol(symbol)
        slip = self.slippage_p75_bps_symbol(symbol, 50)
        
        rr_min = self.config.rr_min_tier.get(tier, 0.95)
        slip_cap = self.config.slip_cap_tier.get(tier, 15.0)
        
        if rr is not None and rr < rr_min:
            return "throttle"
        if slip is not None and slip > slip_cap:
            return "throttle"
        
        return "go"
    
    def apply_symbol_action(self, symbol: str, action: str):
        if action == "throttle":
            self._size_multipliers_symbol[symbol] = 1.0 - self.config.throttle_size_reduction_pct
            self._pyramiding_disabled_until_symbol[symbol] = self.now() + 3600
        else:
            self._size_multipliers_symbol.pop(symbol, None)
            self._pyramiding_disabled_until_symbol.pop(symbol, None)
    
    def tier_controller_tick(self):
        for tier in ["majors", "l1s", "experimental"]:
            action = self.decide_tier_action(tier)
            self.apply_tier_action(tier, action)
        
        self.last_tier_tick = self.now()
    
    def symbol_controller_tick(self):
        for symbol in self.list_all_symbols():
            action = self.decide_symbol_action(symbol)
            self.apply_symbol_action(symbol, action)
        
        self.last_symbol_tick = self.now()
    
    def ev_gate_for_entry(self, symbol: str) -> float:
        tier = self.tier_for_symbol(symbol)
        return self._ev_gate_overrides_tier.get(tier, self.config.ev_gate_default_usd.get(tier, 0.50))
    
    def size_cap_for_entry(self, symbol: str) -> float:
        tier = self.tier_for_symbol(symbol)
        return self._size_cap_overrides_tier.get(tier, self.config.majors_size_cap_default if tier == "majors" else 2.0)
    
    def size_multiplier_for_symbol(self, symbol: str) -> float:
        return self._size_multipliers_symbol.get(symbol, 1.0)
    
    def should_allow_pyramiding(self, symbol: str) -> bool:
        tier = self.tier_for_symbol(symbol)
        if self.is_frozen_pyramiding(tier):
            return False
        if self.is_pyramiding_disabled_symbol(symbol):
            return False
        return True
    
    def get_status(self) -> Dict:
        return {
            "tier_overrides": {
                "ev_gates": self._ev_gate_overrides_tier.copy(),
                "size_caps": self._size_cap_overrides_tier.copy(),
                "throttled": {tier: self._throttle_until_ts_tier.get(tier, 0) > self.now() 
                             for tier in ["majors", "l1s", "experimental"]},
                "frozen_pyramiding": {tier: self._freeze_pyramiding_until_ts_tier.get(tier, 0) > self.now() 
                                     for tier in ["majors", "l1s", "experimental"]}
            },
            "symbol_overrides": {
                "size_multipliers": self._size_multipliers_symbol.copy(),
                "pyramiding_disabled": {sym: self._pyramiding_disabled_until_symbol.get(sym, 0) > self.now() 
                                       for sym in self.list_all_symbols()}
            },
            "last_ticks": {
                "tier": self.last_tier_tick,
                "symbol": self.last_symbol_tick
            }
        }

_monitor_instance: Optional[Phase75Monitor] = None

def get_phase75_monitor() -> Phase75Monitor:
    global _monitor_instance
    if _monitor_instance is None:
        _monitor_instance = Phase75Monitor(default_phase75_cfg())
    return _monitor_instance
