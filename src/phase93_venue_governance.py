"""
Phase 9.3 — Venue Governance & Scaling Controller
Purpose: Prioritize futures, temporarily disable spot until sizing/attribution integrity is proven,
and enforce venue-level exposure caps, sanity checks, and expectancy-gated re-enablement.

Scope:
- Venue gates (spot off, futures on) with expectancy thresholds to unfreeze spot
- Size normalization & sanity checks (no position > portfolio value; caps per venue/symbol)
- Trade frequency limits per venue/strategy
- Expectancy guard (rolling Sharpe / net P&L) required for scaling/unfreezing
- Full audit logging via Phase 8.7

Assumes Phase 9.0–9.2 are active.
"""

from dataclasses import dataclass, field, asdict
from typing import Dict, List, Optional
import time
import threading
import json
from pathlib import Path
from datetime import datetime, timedelta

LOGS_DIR = Path("logs")
STATE_FILE = LOGS_DIR / "phase93_state.json"
EVENT_LOG = LOGS_DIR / "phase93_events.jsonl"

# ======================================================================================
# Config
# ======================================================================================

@dataclass
class Phase93Config:
    # Venue priorities
    spot_enabled_initial: bool = False
    futures_enabled_initial: bool = True

    # Expectancy thresholds to re-enable spot (sustained for N checks)
    spot_unfreeze_min_sharpe: float = 0.8
    spot_unfreeze_min_net_pnl_usd: float = 100.0
    spot_unfreeze_required_passes: int = 5  # sustained across checks

    # Exposure caps
    venue_exposure_cap_pct: Dict[str, float] = field(default_factory=lambda: {
        "spot": 0.20,      # cap spot at 20% until proven
        "futures": 0.60    # futures can use up to 60% initially
    })
    symbol_exposure_cap_pct: float = 0.10  # per-symbol cap

    # Sanity checks
    max_position_vs_portfolio_pct: float = 0.50  # any single position >50% portfolio → block
    require_fields: List[str] = field(default_factory=lambda: ["symbol", "venue", "strategy", "entry_price"])

    # Trade frequency controls
    max_trades_per_4h_spot: int = 4
    max_trades_per_4h_futures: int = 12
    per_symbol_per_hour_limit: Dict[str, int] = field(default_factory=lambda: {
        "Sentiment-Fusion": 1, "Trend-Conservative": 2, "EMA-Futures": 3
    })

    # Streak-aware sizing modifier for futures
    losing_streak_threshold: int = 5
    reduce_size_pct_on_streak: float = 0.30

    cadence_sec: int = 300  # 5 minutes governance tick

CFG93 = Phase93Config()

# Runtime state
_state = {
    "spot_enabled": CFG93.spot_enabled_initial,
    "futures_enabled": CFG93.futures_enabled_initial,
    "spot_unfreeze_passes": 0,
    "venue_blocks": {"spot": [], "futures": []},
    "symbol_blocks": [],
    "last_tick_ts": 0,
    "started_at": None
}

def _load_state():
    global _state
    if STATE_FILE.exists():
        try:
            with open(STATE_FILE, 'r') as f:
                _state.update(json.load(f))
        except:
            pass

def _save_state():
    LOGS_DIR.mkdir(exist_ok=True)
    with open(STATE_FILE, 'w') as f:
        json.dump(_state, f, indent=2)

def _emit_event(event_type: str, data: Dict):
    """Log JSONL event"""
    LOGS_DIR.mkdir(exist_ok=True)
    event = {
        "ts": int(time.time()),
        "event": event_type,
        "data": data
    }
    with open(EVENT_LOG, 'a') as f:
        f.write(json.dumps(event) + '\n')

def _emit_dashboard_event(event_type: str, data: Dict):
    """Emit to main dashboard event log"""
    try:
        from src.phase87_89_expansion import phase87_on_any_critical_event
        phase87_on_any_critical_event(event_type, data)
    except:
        pass

# ======================================================================================
# Portfolio and exposure tracking
# ======================================================================================

def _load_portfolio_data():
    """Load combined portfolio data from spot and futures"""
    spot_file = LOGS_DIR / "portfolio.json"
    futures_file = LOGS_DIR / "portfolio_futures.json"
    
    spot_value = 0
    futures_value = 0
    
    if spot_file.exists():
        with open(spot_file, 'r') as f:
            data = json.load(f)
            spot_value = data.get("current_value", 0)
    
    if futures_file.exists():
        with open(futures_file, 'r') as f:
            data = json.load(f)
            futures_value = data.get("current_value", 0)
    
    return spot_value + futures_value, spot_value, futures_value

def _load_positions():
    """Load open positions from both spot and futures"""
    spot_file = LOGS_DIR / "positions.json"
    futures_file = LOGS_DIR / "positions_futures.json"
    
    all_positions = []
    
    if spot_file.exists():
        with open(spot_file, 'r') as f:
            data = json.load(f)
            for pos in data.get("open_positions", []):
                pos["venue"] = "spot"
                all_positions.append(pos)
    
    if futures_file.exists():
        with open(futures_file, 'r') as f:
            data = json.load(f)
            for pos in data.get("open_positions", []):
                pos["venue"] = "futures"
                all_positions.append(pos)
    
    return all_positions

def portfolio_value() -> float:
    """Get total portfolio value"""
    total, _, _ = _load_portfolio_data()
    return total

def venue_exposure_pct(venue: str) -> float:
    """Calculate current exposure percentage for a venue based on open position notional"""
    total_value = portfolio_value()
    if total_value == 0:
        return 0.0
    
    positions = _load_positions()
    venue_notional = 0
    
    for pos in positions:
        if pos.get("venue") == venue:
            size = pos.get("size", 0)
            venue_notional += size
    
    return venue_notional / total_value

def symbol_exposure_pct(symbol: str) -> float:
    """Calculate current exposure percentage for a symbol"""
    total_value = portfolio_value()
    if total_value == 0:
        return 0.0
    
    positions = _load_positions()
    symbol_value = 0
    
    for pos in positions:
        if pos.get("symbol") == symbol:
            size = pos.get("size", 0)
            symbol_value += size
    
    return symbol_value / total_value

def trades_in_last_hours(hours: int) -> List[Dict]:
    """Get trades from last N hours"""
    cutoff = datetime.now() - timedelta(hours=hours)
    all_trades = []
    
    # Load spot trades
    spot_file = LOGS_DIR / "portfolio.json"
    if spot_file.exists():
        with open(spot_file, 'r') as f:
            data = json.load(f)
            for trade in data.get("trades", []):
                try:
                    ts = datetime.fromisoformat(trade.get("timestamp", "").replace('Z', '+00:00'))
                    if ts.replace(tzinfo=None) >= cutoff:
                        trade["venue"] = "spot"
                        trade["ts"] = ts.timestamp()
                        all_trades.append(trade)
                except:
                    continue
    
    # Load futures trades  
    futures_file = LOGS_DIR / "portfolio_futures.json"
    if futures_file.exists():
        with open(futures_file, 'r') as f:
            data = json.load(f)
            for trade in data.get("trades", []):
                try:
                    ts = datetime.fromisoformat(trade.get("timestamp", "").replace('Z', '+00:00'))
                    if ts.replace(tzinfo=None) >= cutoff:
                        trade["venue"] = "futures"
                        trade["ts"] = ts.timestamp()
                        all_trades.append(trade)
                except:
                    continue
    
    return all_trades

def count_recent_losses(strategy: str, lookback: int = 10) -> int:
    """Count consecutive recent losses for strategy"""
    spot_file = LOGS_DIR / "positions.json"
    futures_file = LOGS_DIR / "positions_futures.json"
    
    all_closed = []
    
    if spot_file.exists():
        with open(spot_file, 'r') as f:
            data = json.load(f)
            all_closed.extend(data.get("closed_positions", []))
    
    if futures_file.exists():
        with open(futures_file, 'r') as f:
            data = json.load(f)
            all_closed.extend(data.get("closed_positions", []))
    
    strategy_trades = [p for p in all_closed if p.get("strategy") == strategy][-lookback:]
    
    streak = 0
    for trade in reversed(strategy_trades):
        roi = trade.get("final_roi", 0)
        if roi < 0:
            streak += 1
        else:
            break
    return streak

def rolling_sharpe_24h_venue(venue: str) -> float:
    """Calculate 24h Sharpe ratio for venue"""
    positions_file = LOGS_DIR / f"positions{'_futures' if venue == 'futures' else ''}.json"
    
    if not Path(positions_file).exists():
        return 0.0
    
    with open(positions_file, 'r') as f:
        data = json.load(f)
        closed = data.get("closed_positions", [])
    
    # Get last 24h positions
    cutoff = datetime.now() - timedelta(hours=24)
    recent = []
    
    for pos in closed:
        try:
            closed_at = pos.get("closed_at", "")
            dt = datetime.fromisoformat(closed_at.replace('Z', '+00:00'))
            if dt.replace(tzinfo=None) >= cutoff:
                recent.append(pos)
        except:
            continue
    
    if len(recent) < 2:
        return 0.0
    
    # Calculate returns
    returns = [p.get("final_roi", 0) / 100 for p in recent]
    
    import statistics
    if len(returns) < 2:
        return 0.0
    
    mean_return = statistics.mean(returns)
    std_return = statistics.stdev(returns)
    
    if std_return == 0:
        return 0.0
    
    return mean_return / std_return

def net_pnl_24h_venue(venue: str) -> float:
    """Calculate 24h net P&L for venue"""
    positions_file = LOGS_DIR / f"positions{'_futures' if venue == 'futures' else ''}.json"
    
    if not Path(positions_file).exists():
        return 0.0
    
    with open(positions_file, 'r') as f:
        data = json.load(f)
        closed = data.get("closed_positions", [])
    
    # Get last 24h positions
    cutoff = datetime.now() - timedelta(hours=24)
    pnl = 0
    
    for pos in closed:
        try:
            closed_at = pos.get("closed_at", "")
            dt = datetime.fromisoformat(closed_at.replace('Z', '+00:00'))
            if dt.replace(tzinfo=None) >= cutoff:
                gross_profit = pos.get("gross_profit", 0)
                fees = pos.get("fees", 0)
                pnl += (gross_profit - fees)
        except:
            continue
    
    return pnl

# ======================================================================================
# Sanity checks and gates
# ======================================================================================

def phase93_entry_gate(signal: Dict) -> bool:
    """
    Gate new entries by venue enablement, exposure caps, and sanity checks.
    """
    # Required fields
    for k in CFG93.require_fields:
        if k not in signal or signal[k] is None:
            _emit_event("entry_block_missing_fields", {"signal": signal, "missing": k})
            _emit_dashboard_event("phase93_entry_block_missing_fields", {"signal": signal, "missing": k})
            return False

    venue = signal["venue"]
    symbol = signal["symbol"]

    # Venue enablement
    if venue == "spot" and not _state["spot_enabled"]:
        _emit_event("entry_block_spot_disabled", {"symbol": symbol})
        return False
    if venue == "futures" and not _state["futures_enabled"]:
        _emit_event("entry_block_futures_disabled", {"symbol": symbol})
        return False

    # Sanity check: position size vs portfolio
    # Accept both 'position_size_usd' and 'size' (alias) since signals may use either
    pv = portfolio_value() or 0.0
    size_usd = signal.get("position_size_usd") or signal.get("size", 0.0)
    if pv and size_usd > pv * CFG93.max_position_vs_portfolio_pct:
        _emit_event("entry_block_size_sanity", {"symbol": symbol, "size_usd": size_usd, "portfolio_value": pv})
        _emit_dashboard_event("phase93_entry_block_size_sanity", {"symbol": symbol, "size_usd": size_usd, "portfolio_value": pv})
        return False

    # Venue exposure cap
    vexp = venue_exposure_pct(venue) or 0.0
    if vexp >= CFG93.venue_exposure_cap_pct.get(venue, 1.0):
        _emit_event("entry_block_venue_cap", {"venue": venue, "exposure_pct": vexp})
        return False

    # Symbol exposure cap
    sexp = symbol_exposure_pct(symbol) or 0.0
    if sexp >= CFG93.symbol_exposure_cap_pct:
        _emit_event("entry_block_symbol_cap", {"symbol": symbol, "exposure_pct": sexp})
        if symbol not in _state["symbol_blocks"]:
            _state["symbol_blocks"].append(symbol)
        return False

    # Frequency controls
    recent_4h = trades_in_last_hours(4)
    venue_limit = CFG93.max_trades_per_4h_spot if venue == "spot" else CFG93.max_trades_per_4h_futures
    venue_trades_4h = [t for t in recent_4h if t.get("venue") == venue]
    
    if len(venue_trades_4h) >= venue_limit:
        _emit_event("entry_block_frequency_venue", {"venue": venue, "count_4h": len(venue_trades_4h), "limit": venue_limit})
        return False

    # Per strategy per symbol per hour
    strat = signal.get("strategy", "")
    per_hour_limit = CFG93.per_symbol_per_hour_limit.get(strat, 1)
    symbol_strat_trades = [t for t in recent_4h if t.get("strategy") == strat and t.get("symbol") == symbol]
    
    if symbol_strat_trades:
        latest = max(symbol_strat_trades, key=lambda t: t.get("ts", 0))
        time_since = time.time() - latest.get("ts", 0)
        
        if time_since < 3600 and len(symbol_strat_trades) >= per_hour_limit:
            _emit_event("entry_block_frequency_symbol_strategy", {"symbol": symbol, "strategy": strat})
            return False

    return True

# ======================================================================================
# Expectancy-based spot unfreeze
# ======================================================================================

def phase93_evaluate_spot_unfreeze():
    """Evaluate if spot trading should be re-enabled based on expectancy"""
    sharpe = rolling_sharpe_24h_venue("spot") or 0.0
    pnl = net_pnl_24h_venue("spot") or 0.0
    ok = (sharpe >= CFG93.spot_unfreeze_min_sharpe) and (pnl >= CFG93.spot_unfreeze_min_net_pnl_usd)
    
    if ok:
        _state["spot_unfreeze_passes"] += 1
        _emit_event("spot_unfreeze_pass", {
            "pass": _state["spot_unfreeze_passes"],
            "sharpe": round(sharpe, 2),
            "pnl": round(pnl, 2)
        })
    else:
        _state["spot_unfreeze_passes"] = 0
        _emit_event("spot_unfreeze_fail", {"sharpe": round(sharpe, 2), "pnl": round(pnl, 2)})

    if _state["spot_unfreeze_passes"] >= CFG93.spot_unfreeze_required_passes and not _state["spot_enabled"]:
        _state["spot_enabled"] = True
        _emit_event("spot_enabled", {"reason": "expectancy_met", "sharpe": sharpe, "pnl": pnl})
        _emit_dashboard_event("phase93_spot_enabled", {"sharpe": sharpe, "pnl": pnl})
        print(f"✅ PHASE93: Spot trading ENABLED - expectancy met (Sharpe: {sharpe:.2f}, P&L: ${pnl:.2f})")

# ======================================================================================
# Futures priority sizing (streak-aware)
# ======================================================================================

def phase93_size_modifier_futures(base_size_usd: float, strategy: str) -> float:
    """Apply futures-specific sizing modifiers"""
    streak_losses = count_recent_losses(strategy) or 0
    size = base_size_usd
    
    if streak_losses >= CFG93.losing_streak_threshold:
        size *= (1.0 - CFG93.reduce_size_pct_on_streak)
        _emit_event("futures_size_reduced_streak", {
            "strategy": strategy,
            "streak_losses": streak_losses,
            "new_size": size
        })
    
    # Cap at symbol exposure limit
    pv = portfolio_value() or 0.0
    max_size = pv * CFG93.symbol_exposure_cap_pct
    return min(size, max_size)

# ======================================================================================
# Governance tick
# ======================================================================================

def phase93_governance_tick():
    """Periodic governance checks"""
    try:
        # Expectancy evaluation for spot
        phase93_evaluate_spot_unfreeze()

        # Venue exposure monitoring
        for venue, cap in CFG93.venue_exposure_cap_pct.items():
            vexp = venue_exposure_pct(venue) or 0.0
            if vexp > cap:
                _emit_event("venue_exposure_breach", {
                    "venue": venue,
                    "exposure_pct": round(vexp, 3),
                    "cap_pct": cap
                })

        _state["last_tick_ts"] = int(time.time())
        _save_state()
        
        _emit_event("tick", {
            "spot_enabled": _state["spot_enabled"],
            "futures_enabled": _state["futures_enabled"],
            "spot_unfreeze_passes": _state["spot_unfreeze_passes"]
        })
    except Exception as e:
        print(f"⚠️ Phase 9.3 governance tick error: {e}")

def _governance_loop():
    """Run governance checks every N seconds"""
    while True:
        try:
            time.sleep(CFG93.cadence_sec)
            phase93_governance_tick()
        except Exception as e:
            print(f"⚠️ Phase 9.3 governance loop error: {e}")

# ======================================================================================
# Bootstrap
# ======================================================================================

def start_phase93_venue_governance():
    """Initialize Phase 9.3 Venue Governance & Scaling Controller"""
    _load_state()
    _state["started_at"] = datetime.now().isoformat()
    
    # Start governance thread
    gov_thread = threading.Thread(target=_governance_loop, daemon=True, name="Phase93-Governance")
    gov_thread.start()
    
    # Initial governance check
    phase93_governance_tick()
    
    _emit_event("phase93_started", {
        "config": {
            "spot_enabled_initial": CFG93.spot_enabled_initial,
            "futures_enabled_initial": CFG93.futures_enabled_initial,
            "venue_caps": CFG93.venue_exposure_cap_pct,
            "symbol_cap_pct": CFG93.symbol_exposure_cap_pct
        }
    })
    _emit_dashboard_event("phase93_started", {"config": asdict(CFG93)})
    
    print("🎯 PHASE93 [{}] phase93_started: {}".format(
        datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        {
            "spot_enabled": _state["spot_enabled"],
            "futures_enabled": _state["futures_enabled"],
            "spot_cap": CFG93.venue_exposure_cap_pct["spot"],
            "futures_cap": CFG93.venue_exposure_cap_pct["futures"]
        }
    ))

def get_phase93_status() -> Dict:
    """Get current Phase 9.3 status for dashboard"""
    total_value = portfolio_value()
    positions = _load_positions()
    
    # Calculate position notional for each venue (size is already in USD)
    spot_notional = sum(
        pos.get("size", 0)
        for pos in positions if pos.get("venue") == "spot"
    )
    futures_notional = sum(
        pos.get("size", 0)
        for pos in positions if pos.get("venue") == "futures"
    )
    
    return {
        "spot_enabled": _state.get("spot_enabled", False),
        "futures_enabled": _state.get("futures_enabled", True),
        "spot_unfreeze_passes": _state.get("spot_unfreeze_passes", 0),
        "spot_unfreeze_required": CFG93.spot_unfreeze_required_passes,
        "spot_sharpe_24h": rolling_sharpe_24h_venue("spot"),
        "spot_pnl_24h": net_pnl_24h_venue("spot"),
        "futures_sharpe_24h": rolling_sharpe_24h_venue("futures"),
        "futures_pnl_24h": net_pnl_24h_venue("futures"),
        "venue_exposure": {
            "spot": {
                "pct": venue_exposure_pct("spot"),
                "cap": CFG93.venue_exposure_cap_pct["spot"],
                "value_usd": spot_notional
            },
            "futures": {
                "pct": venue_exposure_pct("futures"),
                "cap": CFG93.venue_exposure_cap_pct["futures"],
                "value_usd": futures_notional
            }
        },
        "symbol_blocks": _state.get("symbol_blocks", []),
        "last_tick": _state.get("last_tick_ts", 0),
        "config": asdict(CFG93),
        "started_at": _state.get("started_at")
    }

def is_venue_enabled(venue: str) -> bool:
    """Check if a venue is currently enabled"""
    if venue == "spot":
        return _state.get("spot_enabled", False)
    elif venue == "futures":
        return _state.get("futures_enabled", True)
    return False
