import time
import json
from dataclasses import dataclass, field
from typing import Dict, List, Optional
from pathlib import Path

@dataclass
class Phase76Config:
    majors_size_cap_temp: float = 3.0
    majors_size_cap_default: float = 2.0
    majors_rr_thresh_for_bump: float = 1.10
    majors_slip_p75_thresh_bps: float = 10.0
    majors_bump_duration_hours: int = 24
    majors_auto_revert_rr_floor: float = 1.00
    
    experimental_ev_gate_default: float = 0.60
    experimental_ev_gate_lift: float = 0.70
    experimental_ev_lift_required_profitable_trades: int = 30
    
    second_add_trigger_r: float = 1.00
    second_add_drawdown_since_first_max_r: float = 0.20
    second_add_spread_p50_max_bps: float = 8.0
    second_add_alt_trigger_r_if_poor_liquidity: float = 1.20
    
    correlation_window_hours: int = 24
    correlation_block_threshold: float = 0.70
    
    sessions_to_confirm_bias: int = 3
    maker_bias_queue_nudge: float = 0.05
    maker_bias_imbalance_nudge: float = 0.05
    base_queue_min: float = 0.75
    base_imbalance_min: float = 0.65
    
    losing_streak_trades: int = 5
    losing_streak_throttle_hours: int = 12
    losing_streak_ev_gate_bonus_usd: float = 0.10
    
    profit_lock_pnl_threshold_usd: float = 250.0
    profit_lock_duration_hours: int = 12
    profit_lock_size_reduction_pct: float = 0.25

def default_phase76_cfg() -> Phase76Config:
    return Phase76Config()

class Phase76Performance:
    def __init__(self, config: Phase76Config):
        self.config = config
        self.majors_cap_until_ts: Optional[float] = None
        self.experimental_ev_lift_active: bool = True
        self.maker_bias_positive_sessions: int = 0
        self.profit_lock_until_ts: Optional[float] = None
        self.symbol_losing_streak_until_ts: Dict[str, float] = {}
        self.symbol_ev_bonus: Dict[str, float] = {}
        self.maker_queue_threshold: float = config.base_queue_min
        self.maker_imbalance_threshold: float = config.base_imbalance_min
        self.session_maker_wins: int = 0
        self.session_taker_wins: int = 0
    
    def now(self) -> float:
        return time.time()
    
    def is_majors(self, symbol: str) -> bool:
        return symbol.replace("-", "") in {"BTCUSDT", "ETHUSDT"}
    
    def is_experimental(self, symbol: str) -> bool:
        experimental = {"DOTUSDT", "TRXUSDT", "XRPUSDT", "ADAUSDT", "DOGEUSDT", "BNBUSDT", "MATICUSDT"}
        return symbol.replace("-", "") in experimental
    
    def tier_for_symbol(self, symbol: str) -> str:
        if self.is_majors(symbol):
            return "majors"
        if self.is_experimental(symbol):
            return "experimental"
        return "l1s"
    
    def realized_rr_24h_tier(self, tier: str) -> Optional[float]:
        try:
            trades_path = Path("logs/trades.json")
            if not trades_path.exists():
                return None
            
            with open(trades_path) as f:
                trades = [json.loads(line) for line in f if line.strip()]
            
            cutoff = self.now() - 24 * 3600
            tier_trades = [t for t in trades 
                          if t.get("exit_timestamp", 0) > cutoff 
                          and self.tier_for_symbol(t.get("symbol", "")) == tier]
            
            if not tier_trades:
                return None
            
            total_pnl = sum(t.get("realized_pnl_usd", 0) for t in tier_trades)
            total_size = sum(t.get("size_usd", 1) for t in tier_trades)
            
            return total_pnl / total_size if total_size > 0 else None
        except:
            return None
    
    def slippage_p75_bps_tier(self, tier: str) -> Optional[float]:
        try:
            trades_path = Path("logs/trades.json")
            if not trades_path.exists():
                return None
            
            with open(trades_path) as f:
                trades = [json.loads(line) for line in f if line.strip()]
            
            cutoff = self.now() - 24 * 3600
            tier_trades = [t for t in trades 
                          if t.get("exit_timestamp", 0) > cutoff 
                          and self.tier_for_symbol(t.get("symbol", "")) == tier]
            
            slippages = [t.get("slippage_bps", 0) for t in tier_trades if "slippage_bps" in t]
            if not slippages:
                return None
            
            slippages.sort()
            p75_idx = int(len(slippages) * 0.75)
            return slippages[p75_idx]
        except:
            return None
    
    def experimental_profitable_trades_last_n(self, n: int) -> int:
        try:
            trades_path = Path("logs/trades.json")
            if not trades_path.exists():
                return 0
            
            with open(trades_path) as f:
                trades = [json.loads(line) for line in f if line.strip()]
            
            exp_trades = [t for t in trades if self.is_experimental(t.get("symbol", ""))]
            exp_trades.sort(key=lambda x: x.get("exit_timestamp", 0), reverse=True)
            recent = exp_trades[:n]
            
            return sum(1 for t in recent if t.get("realized_pnl_usd", 0) > 0)
        except:
            return 0
    
    def symbol_losing_streak_count(self, symbol: str) -> int:
        try:
            trades_path = Path("logs/trades.json")
            if not trades_path.exists():
                return 0
            
            with open(trades_path) as f:
                trades = [json.loads(line) for line in f if line.strip()]
            
            symbol_trades = [t for t in trades if t.get("symbol") == symbol]
            symbol_trades.sort(key=lambda x: x.get("exit_timestamp", 0), reverse=True)
            
            streak = 0
            for t in symbol_trades[:10]:
                if t.get("realized_pnl_usd", 0) < 0:
                    streak += 1
                else:
                    break
            
            return streak
        except:
            return 0
    
    def maybe_enable_majors_size_cap_bump(self):
        rr = self.realized_rr_24h_tier("majors")
        slip = self.slippage_p75_bps_tier("majors")
        
        if (rr is not None and rr >= self.config.majors_rr_thresh_for_bump and 
            slip is not None and slip <= self.config.majors_slip_p75_thresh_bps):
            self.majors_cap_until_ts = self.now() + self.config.majors_bump_duration_hours * 3600
            print(f"✅ PHASE76: Majors size cap bumped to {self.config.majors_size_cap_temp}x (R:R={rr:.2f}, slip={slip:.1f}bps)")
    
    def maybe_revert_majors_size_cap_bump(self):
        if self.majors_cap_until_ts and self.now() > self.majors_cap_until_ts:
            self.majors_cap_until_ts = None
            print(f"⏰ PHASE76: Majors size cap reverted to {self.config.majors_size_cap_default}x (timer expired)")
            return
        
        rr = self.realized_rr_24h_tier("majors")
        if rr is not None and rr < self.config.majors_auto_revert_rr_floor and self.majors_cap_until_ts:
            self.majors_cap_until_ts = None
            print(f"⚠️  PHASE76: Majors size cap reverted to {self.config.majors_size_cap_default}x (R:R={rr:.2f} below floor)")
    
    def experimental_ev_gate_for_entry(self) -> float:
        return self.config.experimental_ev_gate_lift if self.experimental_ev_lift_active else self.config.experimental_ev_gate_default
    
    def maybe_relax_experimental_ev_gate(self):
        count_profitable = self.experimental_profitable_trades_last_n(self.config.experimental_ev_lift_required_profitable_trades)
        if count_profitable >= self.config.experimental_ev_lift_required_profitable_trades and self.experimental_ev_lift_active:
            self.experimental_ev_lift_active = False
            print(f"✅ PHASE76: Experimental EV gate relaxed to ${self.config.experimental_ev_gate_default:.2f} ({count_profitable} profitable trades)")
    
    def apply_losing_streak_breaker(self, symbol: str):
        if symbol_losing_streak_count := self.symbol_losing_streak_count(symbol):
            if symbol_losing_streak_count >= self.config.losing_streak_trades:
                self.symbol_losing_streak_until_ts[symbol] = self.now() + self.config.losing_streak_throttle_hours * 3600
                self.symbol_ev_bonus[symbol] = self.config.losing_streak_ev_gate_bonus_usd
                print(f"⚠️  PHASE76: Losing streak breaker for {symbol} ({symbol_losing_streak_count} losses, throttle 12h, EV +${self.config.losing_streak_ev_gate_bonus_usd:.2f})")
    
    def is_in_losing_streak_throttle(self, symbol: str) -> bool:
        return self.symbol_losing_streak_until_ts.get(symbol, 0) > self.now()
    
    def losing_streak_ev_bonus(self, symbol: str) -> float:
        if self.is_in_losing_streak_throttle(symbol):
            return self.symbol_ev_bonus.get(symbol, 0.0)
        return 0.0
    
    def maybe_enable_profit_lock(self):
        try:
            portfolio_path = Path("logs/portfolio.json")
            if not portfolio_path.exists():
                return
            
            with open(portfolio_path) as f:
                portfolio = json.load(f)
            
            current_value = portfolio.get("total_value_usd", 0)
            starting_value = 10000.0
            session_pnl = current_value - starting_value
            
            if session_pnl >= self.config.profit_lock_pnl_threshold_usd and not self.profit_lock_until_ts:
                self.profit_lock_until_ts = self.now() + self.config.profit_lock_duration_hours * 3600
                print(f"🔒 PHASE76: Profit lock enabled (session P&L ${session_pnl:.2f}, lock 12h)")
        except:
            pass
    
    def maybe_disable_profit_lock(self):
        if self.profit_lock_until_ts and self.now() > self.profit_lock_until_ts:
            self.profit_lock_until_ts = None
            print(f"🔓 PHASE76: Profit lock disabled (timer expired)")
    
    def is_profit_lock_active(self) -> bool:
        return self.profit_lock_until_ts is not None and self.now() <= self.profit_lock_until_ts
    
    def ev_gate_for_entry(self, symbol: str) -> Optional[float]:
        if self.is_experimental(symbol):
            return self.experimental_ev_gate_for_entry()
        return None
    
    def size_cap_for_entry(self, symbol: str) -> Optional[float]:
        if self.is_majors(symbol) and self.majors_cap_until_ts:
            return self.config.majors_size_cap_temp
        return None
    
    def size_multiplier_for_entry(self, symbol: str) -> float:
        mult = 1.0
        
        if self.is_in_losing_streak_throttle(symbol):
            mult *= (1.0 - self.config.losing_streak_throttle_hours / 24.0)
        
        if self.is_profit_lock_active():
            mult *= (1.0 - self.config.profit_lock_size_reduction_pct)
        
        return mult
    
    def hourly_tick(self):
        self.maybe_enable_majors_size_cap_bump()
        self.maybe_revert_majors_size_cap_bump()
        self.maybe_relax_experimental_ev_gate()
        self.maybe_enable_profit_lock()
        self.maybe_disable_profit_lock()
        
        for symbol in ["ETHUSDT", "SOLUSDT", "AVAXUSDT", "DOTUSDT", "TRXUSDT", "BTCUSDT"]:
            self.apply_losing_streak_breaker(symbol)
    
    def get_status(self) -> Dict:
        return {
            "majors_cap_bump": {
                "active": self.majors_cap_until_ts is not None,
                "cap": self.config.majors_size_cap_temp if self.majors_cap_until_ts else self.config.majors_size_cap_default,
                "expires_ts": self.majors_cap_until_ts
            },
            "experimental_ev_gate": {
                "active_lift": self.experimental_ev_lift_active,
                "current_gate": self.experimental_ev_gate_for_entry()
            },
            "losing_streak_throttles": {
                symbol: {
                    "active": self.is_in_losing_streak_throttle(symbol),
                    "ev_bonus": self.losing_streak_ev_bonus(symbol),
                    "expires_ts": self.symbol_losing_streak_until_ts.get(symbol)
                }
                for symbol in ["ETHUSDT", "SOLUSDT", "AVAXUSDT", "DOTUSDT", "TRXUSDT", "BTCUSDT"]
            },
            "profit_lock": {
                "active": self.is_profit_lock_active(),
                "expires_ts": self.profit_lock_until_ts,
                "size_reduction_pct": self.config.profit_lock_size_reduction_pct if self.is_profit_lock_active() else 0.0
            },
            "config": {
                "majors_rr_thresh": self.config.majors_rr_thresh_for_bump,
                "majors_slip_thresh_bps": self.config.majors_slip_p75_thresh_bps,
                "experimental_profitable_trades_required": self.config.experimental_ev_lift_required_profitable_trades,
                "losing_streak_threshold": self.config.losing_streak_trades,
                "profit_lock_threshold_usd": self.config.profit_lock_pnl_threshold_usd
            }
        }

_phase76_instance: Optional[Phase76Performance] = None

def get_phase76_performance() -> Phase76Performance:
    global _phase76_instance
    if _phase76_instance is None:
        _phase76_instance = Phase76Performance(default_phase76_cfg())
    return _phase76_instance
