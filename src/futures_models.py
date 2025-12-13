"""
Futures trading models: positions, margin safety, leverage allocation.
Based on futures_integration.py with institutional-grade risk management.
"""
import json
from pathlib import Path
from datetime import datetime
from typing import Dict, Any, List, Optional

# Paths
LOGS = Path("logs")
CONFIGS = Path("configs")


def load(path: Path, fallback=None):
    """Load JSON file with fallback."""
    try:
        with open(path, "r") as f:
            return json.load(f)
    except:
        return fallback if fallback is not None else {}


def save(path: Path, data: Dict[str, Any]):
    """Save JSON file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        json.dump(data, f, indent=2)


class FuturesPosition:
    """
    Futures position with leverage, margin, and liquidation tracking.
    """
    
    def __init__(
        self,
        symbol: str,
        side: str,
        qty: float,
        entry_price: float,
        leverage: int,
        maintenance_margin_ratio: float,
        liquidation_price: Optional[float] = None
    ):
        self.symbol = symbol
        self.side = side  # "LONG" or "SHORT"
        self.qty = qty
        self.entry_price = entry_price
        self.leverage = leverage
        self.maintenance_margin_ratio = maintenance_margin_ratio
        self.liquidation_price = liquidation_price
        self.opened_at = datetime.utcnow().isoformat()
    
    def notional(self) -> float:
        """Calculate notional value (qty * price)."""
        return abs(self.qty) * self.entry_price
    
    def initial_margin(self) -> float:
        """Calculate initial margin required (notional / leverage)."""
        return self.notional() / max(self.leverage, 1)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dict for persistence."""
        return {
            "symbol": self.symbol,
            "side": self.side,
            "qty": self.qty,
            "entry_price": self.entry_price,
            "leverage": self.leverage,
            "maintenance_margin_ratio": self.maintenance_margin_ratio,
            "liquidation_price": self.liquidation_price,
            "opened_at": self.opened_at,
            "notional": self.notional(),
            "initial_margin": self.initial_margin()
        }


class MarginSafetyMonitor:
    """
    Monitors margin safety and liquidation risk for futures positions.
    
    Features:
    - Liquidation buffer tracking
    - Margin ratio alerts
    - Event logging for protective actions
    """
    
    def __init__(self, min_liquidation_buffer_pct=8.0, alert_buffer_pct=12.0):
        self.min_buffer = min_liquidation_buffer_pct
        self.alert_buffer = alert_buffer_pct
        self.events = load(LOGS / "futures_margin_events.json", {"events": []}).get("events", [])
    
    @staticmethod
    def buffer_pct(pos: FuturesPosition, mark_price: float) -> float:
        """
        Calculate liquidation buffer as percentage of mark price.
        
        Args:
            pos: Futures position
            mark_price: Current mark price
        
        Returns:
            Buffer percentage (0-100)
        """
        if not pos.liquidation_price:
            return 100.0
        
        if pos.side == "LONG":
            dist = mark_price - pos.liquidation_price
        else:
            dist = pos.liquidation_price - mark_price
        
        return max(0.0, (dist / mark_price) * 100.0)
    
    def assess(self, positions: List[FuturesPosition], mark_prices: Dict[str, float]) -> Dict[str, Any]:
        """
        Assess margin safety for all positions.
        
        Args:
            positions: List of futures positions
            mark_prices: Dict of current mark prices by symbol
        
        Returns:
            Safety report with alerts
        """
        report = {
            "assessed_at": datetime.utcnow().isoformat(),
            "positions": [],
            "alerts": []
        }
        
        for p in positions:
            mp = mark_prices.get(p.symbol, p.entry_price)
            buf = round(self.buffer_pct(p, mp), 2)
            status = "OK"
            
            if buf <= self.min_buffer:
                status = "REDUCE_EXPOSURE"
                self._log_event(p, buf, "min_buffer_breach")
                report["alerts"].append({
                    "symbol": p.symbol,
                    "buffer_pct": buf,
                    "action": "reduce_exposure"
                })
            elif buf <= self.alert_buffer:
                status = "ALERT"
                self._log_event(p, buf, "low_buffer_alert")
            
            report["positions"].append({
                "symbol": p.symbol,
                "side": p.side,
                "leverage": p.leverage,
                "entry_price": p.entry_price,
                "mark_price": mp,
                "liquidation_price": p.liquidation_price,
                "buffer_pct": buf,
                "status": status
            })
        
        save(LOGS / "futures_margin_safety.json", report)
        return report
    
    def _log_event(self, p: FuturesPosition, buffer_pct: float, event_type: str):
        """Log margin safety event."""
        evt = {
            "timestamp": datetime.utcnow().isoformat(),
            "symbol": p.symbol,
            "side": p.side,
            "leverage": p.leverage,
            "buffer_pct": buffer_pct,
            "event": event_type
        }
        self.events.append(evt)
        save(LOGS / "futures_margin_events.json", {"events": self.events})


class LeverageAllocator:
    """
    Proposes per-strategy/regime leverage caps based on performance and volatility.
    Integrates with regime detector and attribution data.
    """
    
    def __init__(self, base_leverage_map=None, max_leverage=10, safety_buffer=0.2):
        # Default leverage by regime
        self.base_leverage_map = base_leverage_map or {
            "Stable": 2.0,
            "Volatile": 3.0,
            "Trending": 4.0,
            "Ranging": 2.0
        }
        self.max_leverage = max_leverage
        self.safety_buffer = safety_buffer
    
    def propose(self, attribution_summary: List[Dict], vol_snapshot: Dict) -> Dict[str, Any]:
        """
        Propose leverage budgets based on strategy performance and volatility.
        
        Args:
            attribution_summary: List of attribution records
            vol_snapshot: Volatility data per symbol/regime
        
        Returns:
            Leverage budget proposals
        """
        proposal = {
            "proposals": [],
            "generated_at": datetime.utcnow().isoformat()
        }
        
        for row in attribution_summary:
            key = f"{row['symbol']}|{row['strategy']}|{row['regime']}"
            base = self.base_leverage_map.get(row["regime"], 2.0)
            vol = vol_snapshot.get(row["symbol"], {}).get("volatility_index", 1.0)
            regime_conf = vol_snapshot.get(row["symbol"], {}).get("regime_confidence", 0.5)
            
            # Performance boost
            perf_boost = 0.0
            if row.get("trades", 0) >= 8:
                perf_boost += max(0.0, (row.get("winrate", 0.5) - 0.5)) * 4.0
                perf_boost += max(0.0, row.get("avg_roi", 0.0)) * 100.0
            
            # Volatility dampening
            vol_damp = min(0.5, (vol - 1.0) * 0.3)
            
            # Regime confidence gate
            conf_gate = 1.0 if regime_conf >= 0.6 else 0.85
            
            proposed = base * conf_gate + perf_boost - vol_damp
            proposed = max(1.0, min(self.max_leverage, proposed))
            proposed *= (1.0 - self.safety_buffer)
            
            proposal["proposals"].append({
                "key": key,
                "symbol": row["symbol"],
                "strategy": row["strategy"],
                "regime": row["regime"],
                "proposed_leverage": round(proposed, 2),
                "inputs": {
                    "base": base,
                    "winrate": row.get("winrate", 0.5),
                    "avg_roi": row.get("avg_roi", 0.0),
                    "volatility_index": vol,
                    "regime_confidence": regime_conf
                }
            })
        
        return proposal
    
    def persist(self, proposal: Dict[str, Any]):
        """Save leverage proposal to configs."""
        save(CONFIGS / "leverage_budgets.json", proposal)


class FuturesAttribution:
    """
    Separate attribution tracking for futures with leverage, funding fees, margin costs.
    """
    
    def __init__(self, file=LOGS / "futures_attribution.json"):
        self.file = file
        self.data = load(self.file, {"summary": []})
    
    def log(
        self,
        symbol: str,
        strategy: str,
        regime: str,
        leverage: int,
        pnl: float,
        roi: float,
        fees: float,
        trades: int = 1
    ):
        """Log futures trade attribution."""
        self.data["summary"].append({
            "symbol": symbol,
            "strategy": strategy,
            "regime": regime,
            "leverage": leverage,
            "pnl": pnl,
            "roi": roi,
            "fees": fees,
            "trades": trades,
            "timestamp": datetime.utcnow().isoformat()
        })
    
    def persist(self):
        """Save attribution data."""
        save(self.file, self.data)
    
    def get_summary(self) -> List[Dict[str, Any]]:
        """Get attribution summary."""
        return self.data.get("summary", [])


class LeverageShadowLab:
    """
    Shadow testing lab for leverage configurations before live deployment.
    """
    
    def __init__(self, file=LOGS / "futures_shadow_results.json"):
        self.file = file
        self.results = load(self.file, {"experiments": []})
    
    def run(self, name: str, config: Dict[str, Any], metrics: Dict[str, Any]):
        """
        Run shadow experiment.
        
        Args:
            name: Experiment name
            config: Leverage configuration dict
            metrics: Performance metrics
        """
        self.results["experiments"].append({
            "name": name,
            "config": config,
            "metrics": metrics,
            "timestamp": datetime.utcnow().isoformat()
        })
    
    def persist(self):
        """Save shadow experiment results."""
        save(self.file, self.results)
    
    def get_experiments(self) -> List[Dict[str, Any]]:
        """Get all shadow experiments."""
        return self.results.get("experiments", [])
