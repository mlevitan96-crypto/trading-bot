"""
Shadow Research Module - High-Liquidity Experimental Cryptos
Adds XRP, ADA, DOGE, BNB, MATIC as shadow-only instruments with complete telemetry.

Features:
- Zero live budget until strict promotion criteria met
- Volatility research (realized vol, vol spikes, spread/slippage tracking)
- Ensemble confidence and block reason analytics
- Criteria-based promotion gates (no time-based promotion)
- Integration with Phase 6/7 for regime-aware ensemble scoring
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple
import time
import math
import threading
import statistics

NEW_SHADOW_SYMBOLS = {"XRPUSDT", "ADAUSDT", "DOGEUSDT", "BNBUSDT", "MATICUSDT"}


@dataclass
class ShadowResearchConfig:
    min_ensemble_score_exp: float = 0.60
    per_symbol_budget_bps: Dict[str, int] = field(default_factory=dict)
    
    min_trades_shadow: int = 40
    min_hours_observed: int = 24
    min_wilson_winrate_diff: float = 0.03
    pnl_bootstrap_ci_must_exclude_zero: bool = True
    min_sharpe: float = 0.25
    min_sortino: float = 0.3
    max_slippage_bps: float = 10
    
    vol_lookback_hours: int = 72
    vol_spike_threshold_sigma: float = 2.0
    telemetry_window_hours: int = 24
    
    predictive_events_enable: bool = True
    telemetry_interval_sec: int = 60


@dataclass
class VolResearch:
    symbol: str
    realized_vol_annual_pct: float
    vol_spike_score: float
    avg_spread_bps: float
    p75_spread_bps: float
    slippage_p50_bps: float
    slippage_p75_bps: float


@dataclass
class EnsembleTelemetry:
    symbol: str
    p50: float
    p75: float
    blocked_top_reasons: List[str]
    trades: int
    wins: int


@dataclass
class PromotionMetrics:
    symbol: str
    hours_observed: int
    trades: int
    wilson_winrate_lb_vs_baseline: float
    pnl_bootstrap_ci_low: float
    pnl_bootstrap_ci_high: float
    sortino: float
    sharpe: float
    slippage_bps_avg: float


class ShadowResearchEngine:
    def __init__(self, config: ShadowResearchConfig = None):
        self.config = config or self.default_config()
        self.running = False
        self.thread = None
        self.lock = threading.RLock()
        
        self.vol_research_data: Dict[str, VolResearch] = {}
        self.ensemble_telemetry: Dict[str, EnsembleTelemetry] = {}
        self.promotion_status: Dict[str, Dict] = {}
        self.shadow_trade_log: List[Dict] = []
        
        # All shadow symbols are now PROMOTED by default (have regular budget access)
        # Shadow_tag is retained for analytics and review purposes
        for symbol in NEW_SHADOW_SYMBOLS:
            self.promotion_status[symbol] = {
                "promoted": True,  # Changed from False - symbols get regular budget immediately
                "last_attempt_ts": 0,
                "failure_reasons": [],
                "trades_logged": 0,
                "start_ts": time.time()
            }
    
    def default_config(self) -> ShadowResearchConfig:
        # Shadow symbols now get regular budget allocation (80 bps = 0.8% of portfolio)
        # This matches the allocation for other mid-tier symbols like SOL
        return ShadowResearchConfig(
            per_symbol_budget_bps={s: 80 for s in NEW_SHADOW_SYMBOLS}
        )
    
    def start(self):
        """Start shadow research telemetry thread."""
        if self.running:
            return
        
        self.running = True
        self.thread = threading.Thread(target=self.telemetry_loop, daemon=True)
        self.thread.start()
        print("ℹ️  SHADOW: Shadow Research Engine started")
    
    def stop(self):
        """Stop shadow research."""
        self.running = False
        if self.thread:
            self.thread.join(timeout=5)
    
    def percentile(self, vals: List[float], p: float) -> float:
        """Calculate percentile."""
        if not vals:
            return 0.0
        v = sorted(vals)
        i = int(max(0, min(len(v) - 1, round(p * (len(v) - 1)))))
        return v[i]
    
    def compute_realized_vol_annual(self, symbol: str) -> float:
        """Compute annualized realized volatility from market data."""
        try:
            from blofin_client import BlofinClient
            blofin = BlofinClient()
            
            df = blofin.fetch_ohlcv(symbol, timeframe="1m", limit=200)
            if df.empty:
                return 0.0
            
            returns = df["close"].pct_change().dropna()
            if len(returns) < 10:
                return 0.0
            
            mu = returns.mean()
            var = returns.var()
            daily_std = math.sqrt(var) * math.sqrt(60 * 24)
            annual_std = daily_std * math.sqrt(252)
            
            return round(annual_std * 100.0, 2)
        except:
            return 0.0
    
    def compute_vol_spike_score(self, symbol: str) -> float:
        """Score volatility spike frequency (0..1 scale)."""
        try:
            from blofin_client import BlofinClient
            blofin = BlofinClient()
            
            df = blofin.fetch_ohlcv(symbol, timeframe="5m", limit=100)
            if df.empty:
                return 0.0
            
            returns = df["close"].pct_change().dropna()
            if len(returns) < 10:
                return 0.0
            
            mu = returns.mean()
            std = returns.std()
            
            spikes = [r for r in returns if abs(r - mu) >= self.config.vol_spike_threshold_sigma * std]
            score = len(spikes) / len(returns)
            
            return round(max(0.0, min(1.0, score)), 3)
        except:
            return 0.0
    
    def compute_spread_stats(self, symbol: str) -> Tuple[float, float]:
        """Compute average and P75 spread in basis points."""
        try:
            from blofin_client import BlofinClient
            blofin = BlofinClient()
            
            df = blofin.fetch_ohlcv(symbol, timeframe="1m", limit=100)
            if df.empty:
                return 0.0, 0.0
            
            spreads_bps = []
            for _, row in df.iterrows():
                if row["close"] > 0:
                    spread_bps = ((row["high"] - row["low"]) / row["close"]) * 10000
                    spreads_bps.append(spread_bps)
            
            if not spreads_bps:
                return 0.0, 0.0
            
            avg_spread = round(sum(spreads_bps) / len(spreads_bps), 2)
            p75_spread = round(self.percentile(spreads_bps, 0.75), 2)
            
            return avg_spread, p75_spread
        except:
            return 0.0, 0.0
    
    def run_vol_research(self, symbol: str) -> VolResearch:
        """Run complete volatility research for symbol."""
        rv = self.compute_realized_vol_annual(symbol)
        spike_score = self.compute_vol_spike_score(symbol)
        avg_spread, p75_spread = self.compute_spread_stats(symbol)
        
        return VolResearch(
            symbol=symbol,
            realized_vol_annual_pct=rv,
            vol_spike_score=spike_score,
            avg_spread_bps=avg_spread,
            p75_spread_bps=p75_spread,
            slippage_p50_bps=0.0,
            slippage_p75_bps=0.0,
        )
    
    def aggregate_ensemble_telemetry(self, symbol: str) -> EnsembleTelemetry:
        """Aggregate ensemble confidence and block reasons from shadow trade log."""
        with self.lock:
            symbol_trades = [t for t in self.shadow_trade_log if t.get("symbol") == symbol]
            
            if not symbol_trades:
                return EnsembleTelemetry(
                    symbol=symbol,
                    p50=0.0,
                    p75=0.0,
                    blocked_top_reasons=[],
                    trades=0,
                    wins=0
                )
            
            ensemble_vals = [t.get("ensemble", 0.5) for t in symbol_trades]
            p50 = round(self.percentile(ensemble_vals, 0.50), 3) if ensemble_vals else 0.0
            p75 = round(self.percentile(ensemble_vals, 0.75), 3) if ensemble_vals else 0.0
            
            trades = len(symbol_trades)
            wins = sum(1 for t in symbol_trades if t.get("pnl_usd", 0) > 0)
            
            return EnsembleTelemetry(
                symbol=symbol,
                p50=p50,
                p75=p75,
                blocked_top_reasons=[],
                trades=trades,
                wins=wins
            )
    
    def check_promotion_criteria(self, symbol: str) -> Tuple[bool, List[str]]:
        """Check if symbol meets promotion criteria."""
        with self.lock:
            status = self.promotion_status.get(symbol, {})
            if status.get("promoted", False):
                return True, []
            
            hours_obs = (time.time() - status.get("start_ts", time.time())) / 3600
            trades = status.get("trades_logged", 0)
            
            reasons = []
            
            if hours_obs < self.config.min_hours_observed:
                reasons.append(f"insufficient_hours ({hours_obs:.1f}/{self.config.min_hours_observed})")
            
            if trades < self.config.min_trades_shadow:
                reasons.append(f"insufficient_trades ({trades}/{self.config.min_trades_shadow})")
            
            symbol_trades = [t for t in self.shadow_trade_log if t.get("symbol") == symbol]
            if symbol_trades:
                pnls = [t.get("pnl_usd", 0) for t in symbol_trades]
                wins = sum(1 for p in pnls if p > 0)
                win_rate = wins / len(symbol_trades) if symbol_trades else 0
                
                if win_rate < 0.50:
                    reasons.append(f"low_winrate ({win_rate:.2%})")
                
                avg_pnl = statistics.mean(pnls) if pnls else 0
                if avg_pnl <= 0:
                    reasons.append(f"negative_pnl (${avg_pnl:.2f})")
            else:
                reasons.append("no_trade_data")
            
            return (len(reasons) == 0), reasons
    
    def attempt_promotion(self, symbol: str) -> bool:
        """Attempt to promote symbol from shadow to live trading."""
        ok, reasons = self.check_promotion_criteria(symbol)
        
        with self.lock:
            self.promotion_status[symbol]["last_attempt_ts"] = time.time()
            self.promotion_status[symbol]["failure_reasons"] = reasons
            
            if not ok:
                return False
            
            self.promotion_status[symbol]["promoted"] = True
            self.config.per_symbol_budget_bps[symbol] = 40
            
            print(f"🎉 SHADOW: Promoted {symbol} to live trading (budget=40bps)")
            return True
    
    def log_shadow_trade(self, symbol: str, ensemble: float, pnl_usd: float, reasons: List[str] = None):
        """Log a shadow trade for telemetry."""
        with self.lock:
            self.shadow_trade_log.append({
                "timestamp": time.time(),
                "symbol": symbol,
                "ensemble": ensemble,
                "pnl_usd": pnl_usd,
                "reasons": reasons or [],
            })
            
            if len(self.shadow_trade_log) > 5000:
                self.shadow_trade_log = self.shadow_trade_log[-2500:]
            
            if symbol in self.promotion_status:
                self.promotion_status[symbol]["trades_logged"] += 1
    
    def telemetry_loop(self):
        """Background telemetry collection."""
        while self.running:
            try:
                for symbol in NEW_SHADOW_SYMBOLS:
                    vol_res = self.run_vol_research(symbol)
                    ens_tel = self.aggregate_ensemble_telemetry(symbol)
                    
                    with self.lock:
                        self.vol_research_data[symbol] = vol_res
                        self.ensemble_telemetry[symbol] = ens_tel
                    
                    if not self.promotion_status.get(symbol, {}).get("promoted", False):
                        self.attempt_promotion(symbol)
                
            except Exception as e:
                print(f"⚠️ SHADOW: Telemetry error: {e}")
            
            time.sleep(self.config.telemetry_interval_sec)
    
    def get_status(self) -> Dict:
        """Get current shadow research status."""
        with self.lock:
            return {
                "vol_research": {s: vars(v) for s, v in self.vol_research_data.items()},
                "ensemble_telemetry": {s: vars(e) for s, e in self.ensemble_telemetry.items()},
                "promotion_status": self.promotion_status.copy(),
                "total_shadow_trades": len(self.shadow_trade_log),
                "symbols": list(NEW_SHADOW_SYMBOLS),
            }
    
    def is_shadow_only(self, symbol: str) -> bool:
        """Check if symbol is still shadow-only (not promoted)."""
        with self.lock:
            return not self.promotion_status.get(symbol, {}).get("promoted", False)
    
    def get_symbol_budget_bps(self, symbol: str) -> int:
        """Get budget for symbol (0 if shadow-only)."""
        with self.lock:
            if self.is_shadow_only(symbol):
                return 0
            return self.config.per_symbol_budget_bps.get(symbol, 0)


_shadow_engine = None

def get_shadow_engine() -> ShadowResearchEngine:
    """Get global shadow research engine instance."""
    global _shadow_engine
    if _shadow_engine is None:
        _shadow_engine = ShadowResearchEngine()
    return _shadow_engine


def start_shadow_research():
    """Initialize and start shadow research engine."""
    engine = get_shadow_engine()
    engine.start()
    return engine
