"""
Phases 10.13–10.15 — Expectancy Attribution + Risk Parity Allocation + Degradation Auditor

Phase 10.13: Post-Trade Expectancy Attribution
- Unify execution quality, exit efficiency, and realized alpha into per-signal expectancy ledger
- Track avg_edge, exec_quality, exit_efficiency per (symbol, strategy) pair
- Decay-weighted moving averages with configurable min samples

Phase 10.14: Risk Parity & Correlation-Aware Allocation
- Size positions by risk units (default 1000 USD per unit)
- Balance across correlated symbols, suppress clusters when correlation spikes
- Enforce symbol caps (10%) and cluster caps (25%)

Phase 10.15: Degradation Auditor & Auto-Repair
- Detect config drift, stale dashboards, missing hooks, silent failures
- Auto-apply safe guardrail repairs with audit trails
- Periodic audits every 10 minutes

Integration Points:
- phase1013_on_trade_close(trade) - called after every trade closure
- phase1014_pre_allocation(signal) - called before position sizing
- phase1015_audit_tick() - periodic degradation detection
"""

import time
import os
import json
import math
import statistics
from typing import Dict, List, Optional, Tuple
from datetime import datetime
from src.net_pnl_enforcement import get_net_pnl, get_net_roi

# ======================================================================================
# Configuration
# ======================================================================================

class Phase1013Config:
    """Expectancy Attribution Config"""
    min_samples = 10
    decay = 0.98
    state_path = "logs/phase1013_1015_state.json"
    event_log_path = "logs/phase1013_1015_events.jsonl"

class Phase1014Config:
    """Risk Parity Allocation Config"""
    max_symbol_risk_pct = 0.10  # 10% max per symbol
    max_cluster_risk_pct = 0.25  # 25% max per correlated cluster
    correlation_threshold = 0.70  # 0.70+ = highly correlated
    risk_unit_usd = 1000.0  # $1000 per risk unit
    
class Phase1015Config:
    """Degradation Auditor Config"""
    audit_tick_sec = 600  # 10 minutes
    audit_log_path = "logs/phase1015_audit.jsonl"
    max_stale_hours = 24
    repair_enabled = True

CFG1013 = Phase1013Config()
CFG1014 = Phase1014Config()
CFG1015 = Phase1015Config()

# ======================================================================================
# State Management
# ======================================================================================

_state = {
    "phase1013": {
        "ledger": {},  # key=(symbol,strategy) -> {samples, avg_edge, exec_quality, exit_efficiency}
        "last_update": None
    },
    "phase1014": {
        "correlations": {},  # (symbol1, symbol2) -> correlation coefficient
        "last_allocation": {},  # symbol -> {base, sized, risk_units, timestamp}
        "cluster_exposures": {}  # cluster_id -> total_exposure_usd
    },
    "phase1015": {
        "last_audit": None,
        "repairs": [],
        "issues_detected": 0,
        "repairs_applied": 0
    }
}

def _load_state():
    """Load state from disk"""
    global _state
    if os.path.exists(CFG1013.state_path):
        try:
            with open(CFG1013.state_path, "r") as f:
                _state = json.load(f)
        except Exception as e:
            _append_event("state_load_error", {"error": str(e)})
    
def _save_state():
    """Persist state to disk"""
    os.makedirs(os.path.dirname(CFG1013.state_path), exist_ok=True)
    try:
        with open(CFG1013.state_path, "w") as f:
            json.dump(_state, f, indent=2)
    except Exception as e:
        _append_event("state_save_error", {"error": str(e)})

def _append_event(event: str, payload: dict):
    """Append event to JSONL log"""
    os.makedirs(os.path.dirname(CFG1013.event_log_path), exist_ok=True)
    try:
        with open(CFG1013.event_log_path, "a") as f:
            f.write(json.dumps({
                "ts": int(time.time()),
                "iso": datetime.now().isoformat(),
                "event": event,
                "payload": payload
            }) + "\n")
    except Exception:
        pass

def _append_audit(event: str, payload: dict):
    """Append audit event to separate audit trail"""
    os.makedirs(os.path.dirname(CFG1015.audit_log_path), exist_ok=True)
    try:
        with open(CFG1015.audit_log_path, "a") as f:
            f.write(json.dumps({
                "ts": int(time.time()),
                "iso": datetime.now().isoformat(),
                "event": event,
                "payload": payload
            }) + "\n")
    except Exception:
        pass

# ======================================================================================
# Integration Hooks
# ======================================================================================

def _get_portfolio_value() -> float:
    """Get current portfolio value"""
    try:
        from src.portfolio_tracker import get_portfolio_summary
        summary = get_portfolio_summary()
        return summary.get("current_value", 10000.0)
    except Exception:
        return 10000.0

def _get_symbol_stats(symbol: str) -> dict:
    """Get symbol trading statistics"""
    try:
        from src.position_manager import get_symbol_trade_history
        history = get_symbol_trade_history(symbol, limit=100)
        if not history:
            return {"win_rate": 0.0, "sharpe": 0.0, "pnl_24h": 0.0, "total_trades": 0}
        
        wins = [t for t in history if t.get("pnl", 0) > 0]
        win_rate = len(wins) / len(history) if history else 0.0
        
        # Calculate Sharpe (simplified)
        pnls = [t.get("pnl", 0) for t in history]
        avg_pnl = statistics.mean(pnls) if pnls else 0.0
        std_pnl = statistics.stdev(pnls) if len(pnls) > 1 else 1.0
        sharpe = (avg_pnl / std_pnl) if std_pnl > 0 else 0.0
        
        # 24h P&L
        cutoff = time.time() - 86400
        recent = [t for t in history if t.get("close_time", 0) > cutoff]
        pnl_24h = sum(t.get("pnl", 0) for t in recent)
        
        return {
            "win_rate": win_rate * 100,
            "sharpe": sharpe,
            "pnl_24h": pnl_24h,
            "total_trades": len(history)
        }
    except Exception:
        return {"win_rate": 0.0, "sharpe": 0.0, "pnl_24h": 0.0, "total_trades": 0}

def _calculate_correlation_matrix(symbols: List[str]) -> Dict[Tuple[str, str], float]:
    """Calculate correlation matrix for symbols"""
    try:
        from src.exchange_gateway import ExchangeGateway
        gateway = ExchangeGateway()
        
        # Fetch recent price data for all symbols
        prices = {}
        for symbol in symbols:
            try:
                candles = gateway.fetch_ohlcv(symbol, timeframe="1h", limit=50, venue="spot")
                if candles:
                    prices[symbol] = [c["close"] for c in candles]
            except Exception:
                continue
        
        # Calculate pairwise correlations
        correlations = {}
        for i, sym1 in enumerate(symbols):
            for sym2 in symbols[i+1:]:
                if sym1 in prices and sym2 in prices:
                    p1, p2 = prices[sym1], prices[sym2]
                    min_len = min(len(p1), len(p2))
                    if min_len > 10:
                        # Simple correlation calculation
                        corr = _pearson_correlation(p1[:min_len], p2[:min_len])
                        correlations[(sym1, sym2)] = corr
                        correlations[(sym2, sym1)] = corr
        
        return correlations
    except Exception as e:
        _append_event("correlation_calc_error", {"error": str(e)})
        return {}

def _pearson_correlation(x: List[float], y: List[float]) -> float:
    """Calculate Pearson correlation coefficient"""
    try:
        n = len(x)
        if n != len(y) or n < 2:
            return 0.0
        
        mean_x = statistics.mean(x)
        mean_y = statistics.mean(y)
        
        numerator = sum((x[i] - mean_x) * (y[i] - mean_y) for i in range(n))
        denominator = math.sqrt(
            sum((x[i] - mean_x)**2 for i in range(n)) *
            sum((y[i] - mean_y)**2 for i in range(n))
        )
        
        return numerator / denominator if denominator > 0 else 0.0
    except Exception:
        return 0.0

def _get_all_symbols() -> List[str]:
    """Get all trading symbols from canonical config"""
    try:
        import json
        from pathlib import Path
        config_path = Path("config/asset_universe.json")
        if config_path.exists():
            config = json.loads(config_path.read_text())
            return [a["symbol"] for a in config.get("asset_universe", []) if a.get("enabled", True)]
        from src.config import LIVE_SYMBOLS
        return LIVE_SYMBOLS
    except Exception:
        return ["ETHUSDT", "SOLUSDT", "AVAXUSDT", "DOTUSDT", "TRXUSDT", "BTCUSDT", 
                "XRPUSDT", "ADAUSDT", "DOGEUSDT", "BNBUSDT", "MATICUSDT",
                "LINKUSDT", "ARBUSDT", "OPUSDT", "PEPEUSDT"]

# ======================================================================================
# Phase 10.13 — Post-Trade Expectancy Attribution
# ======================================================================================

def phase1013_on_trade_close(trade: Dict):
    """
    Update expectancy ledger after trade closure.
    
    Expected trade fields:
    - symbol: str
    - strategy: str
    - pnl_usd: float (realized P&L)
    - exec_edge_bps: float (execution quality in basis points)
    - exit_efficiency: float (0.0-1.0, how well exit captured move)
    """
    symbol = trade.get("symbol")
    strategy = trade.get("strategy", "unknown")
    
    if not symbol:
        return
    
    key = f"{symbol}_{strategy}"
    ledger = _state["phase1013"]["ledger"]
    
    # Initialize or retrieve ledger entry
    if key not in ledger:
        ledger[key] = {
            "symbol": symbol,
            "strategy": strategy,
            "samples": 0,
            "avg_edge": 0.0,
            "exec_quality": 0.0,
            "exit_efficiency": 0.0,
            "last_update": None
        }
    
    row = ledger[key]
    row["samples"] += 1
    
    # Update decay-weighted moving averages
    # CRITICAL: Use net P&L (after fees) for accurate expectancy tracking
    net_pnl_usd = get_net_pnl(trade)
    exec_edge_bps = trade.get("exec_edge_bps", 0.0)
    exit_eff = trade.get("exit_efficiency", 0.0)
    
    row["avg_edge"] = (row["avg_edge"] * CFG1013.decay + net_pnl_usd) / (CFG1013.decay + 1)
    row["exec_quality"] = (row["exec_quality"] * CFG1013.decay + exec_edge_bps) / (CFG1013.decay + 1)
    row["exit_efficiency"] = (row["exit_efficiency"] * CFG1013.decay + exit_eff) / (CFG1013.decay + 1)
    row["last_update"] = int(time.time())
    
    ledger[key] = row
    _state["phase1013"]["last_update"] = int(time.time())
    
    # Log event
    _append_event("phase1013_update", {
        "symbol": symbol,
        "strategy": strategy,
        "ledger": row
    })
    
    _save_state()

def get_expectancy_score(symbol: str, strategy: str = "unknown") -> float:
    """
    Calculate composite expectancy score for a symbol/strategy pair.
    
    Score = avg_edge + (exec_quality * 0.1) + (exit_efficiency * 0.1)
    """
    key = f"{symbol}_{strategy}"
    ledger = _state["phase1013"]["ledger"]
    
    if key not in ledger:
        return 0.0
    
    row = ledger[key]
    if row["samples"] < CFG1013.min_samples:
        return 0.0
    
    score = row["avg_edge"] + (row["exec_quality"] * 0.1) + (row["exit_efficiency"] * 0.1)
    return score

# ======================================================================================
# Phase 10.14 — Risk Parity & Correlation-Aware Allocation
# ======================================================================================

def phase1014_pre_allocation(signal: Dict) -> float:
    """
    Apply risk parity and correlation-aware sizing before position entry.
    
    Expected signal fields:
    - symbol: str
    - strategy: str
    - base_size_usd: float (planned position size)
    
    Returns:
    - adjusted_size_usd: float (risk-parity adjusted size)
    
    Enforcement Logic:
    1. Calculate risk units from base size
    2. Identify correlated cluster (correlation >= 0.70)
    3. Apply correlation suppression: max(0.5, 1.0 - 0.1 * cluster_size)
    4. Enforce symbol cap (10% of portfolio)
    5. Enforce cluster cap (25% of portfolio)
    6. Return adjusted sizing to allocator
    """
    symbol = signal.get("symbol")
    strategy = signal.get("strategy", "unknown")
    base_size = signal.get("base_size_usd", 0.0)
    
    if not symbol or base_size <= 0:
        return 0.0
    
    pv = _get_portfolio_value()
    if pv <= 0:
        return 0.0
    
    # Calculate base risk units
    risk_units = base_size / CFG1014.risk_unit_usd
    
    # Update correlation matrix (compute pairwise correlations)
    symbols = _get_all_symbols()
    correlations = _calculate_correlation_matrix(symbols)
    _state["phase1014"]["correlations"] = {
        f"{s1}_{s2}": corr for (s1, s2), corr in correlations.items()
    }
    
    # Find correlated cluster (all symbols with correlation >= threshold)
    correlated_symbols = set()
    for (s1, s2), corr in correlations.items():
        if symbol in (s1, s2) and corr >= CFG1014.correlation_threshold:
            other = s2 if s1 == symbol else s1
            correlated_symbols.add(other)
    
    cluster_size = len(correlated_symbols)
    
    # Apply correlation suppression to risk units
    if cluster_size > 0:
        suppression_factor = max(0.5, 1.0 - 0.1 * cluster_size)
        risk_units *= suppression_factor
    else:
        suppression_factor = 1.0
    
    # Recalculate sized amount from suppressed risk units
    sized = risk_units * CFG1014.risk_unit_usd
    
    # Enforce symbol cap (10% of portfolio)
    max_symbol_usd = pv * CFG1014.max_symbol_risk_pct
    if sized > max_symbol_usd:
        sized = max_symbol_usd
    
    # Enforce cluster cap (25% of portfolio)
    # Calculate total cluster exposure (current positions + proposed)
    cluster_exposure = sized
    
    try:
        from src.position_manager import get_open_positions
        positions = get_open_positions()
        
        # Include current symbol's existing position
        for pos in positions:
            if pos.get("symbol") == symbol:
                cluster_exposure += abs(pos.get("size", 0))
        
        # Include other correlated symbols' positions
        for other_symbol in correlated_symbols:
            for pos in positions:
                if pos.get("symbol") == other_symbol:
                    cluster_exposure += abs(pos.get("size", 0))
    except Exception:
        pass
    
    max_cluster_usd = pv * CFG1014.max_cluster_risk_pct
    if cluster_exposure > max_cluster_usd:
        # Reduce proposed size to fit within cluster cap
        available_cluster = max_cluster_usd - (cluster_exposure - sized)
        sized = max(0, min(sized, available_cluster))
    
    # Track allocation
    allocation = {
        "symbol": symbol,
        "strategy": strategy,
        "base": base_size,
        "sized": sized,
        "risk_units": risk_units,
        "cluster_size": cluster_size,
        "suppression_factor": suppression_factor,
        "cluster_exposure_usd": cluster_exposure,
        "max_cluster_usd": max_cluster_usd,
        "max_symbol_usd": max_symbol_usd,
        "timestamp": int(time.time())
    }
    
    _state["phase1014"]["last_allocation"][symbol] = allocation
    
    # Log event
    _append_event("phase1014_alloc", allocation)
    
    _save_state()
    
    # Return adjusted sizing to allocator
    return sized

# ======================================================================================
# Phase 10.15 — Degradation Auditor & Auto-Repair
# ======================================================================================

def phase1015_audit_tick():
    """
    Periodic degradation audit.
    
    Checks:
    - Ledger freshness (stale entries)
    - Correlation matrix completeness
    - Dashboard event flow
    - Missing hooks
    
    Auto-repairs:
    - Clear stale ledger entries
    - Rebuild correlation matrix
    - Log warnings for manual review
    """
    issues = []
    repairs_applied = 0
    
    # Check 1: Ledger freshness
    ledger = _state["phase1013"]["ledger"]
    stale_cutoff = time.time() - (CFG1015.max_stale_hours * 3600)
    
    for key, row in list(ledger.items()):
        last_update = row.get("last_update", 0)
        if last_update > 0 and last_update < stale_cutoff:
            issues.append({
                "component": "expectancy_ledger",
                "detail": f"{key} stale for {CFG1015.max_stale_hours}h"
            })
            
            if CFG1015.repair_enabled:
                # Clear stale entry
                del ledger[key]
                repairs_applied += 1
    
    # Check 2: Correlation matrix completeness
    correlations = _state["phase1014"]["correlations"]
    if not correlations:
        issues.append({
            "component": "correlation_matrix",
            "detail": "empty"
        })
        
        if CFG1015.repair_enabled:
            # Rebuild correlation matrix
            symbols = _get_all_symbols()
            new_corr = _calculate_correlation_matrix(symbols)
            _state["phase1014"]["correlations"] = {
                f"{s1}_{s2}": corr for (s1, s2), corr in new_corr.items()
            }
            repairs_applied += 1
    
    # Check 3: Dashboard event flow
    last_update = _state["phase1013"].get("last_update")
    if last_update and last_update < stale_cutoff:
        issues.append({
            "component": "dashboard",
            "detail": "no recent expectancy updates"
        })
    
    # Check 4: Hook integration
    if not _state["phase1014"].get("last_allocation"):
        issues.append({
            "component": "allocation_hook",
            "detail": "no allocations recorded"
        })
    
    # Record audit results
    _state["phase1015"]["last_audit"] = int(time.time())
    _state["phase1015"]["issues_detected"] += len(issues)
    _state["phase1015"]["repairs_applied"] += repairs_applied
    
    if issues:
        _state["phase1015"]["repairs"].extend(issues)
        # Keep only last 100 repairs
        _state["phase1015"]["repairs"] = _state["phase1015"]["repairs"][-100:]
    
    # Log audit results
    _append_audit("phase1015_audit_tick", {
        "issues": issues,
        "repairs_applied": repairs_applied,
        "total_issues": len(issues)
    })
    
    _save_state()
    
    return {
        "issues": issues,
        "repairs_applied": repairs_applied
    }

# ======================================================================================
# API / Dashboard Support
# ======================================================================================

def get_status() -> dict:
    """Get current phase 10.13-10.15 status"""
    return {
        "phase1013": {
            "ledger_entries": len(_state["phase1013"]["ledger"]),
            "last_update": _state["phase1013"].get("last_update"),
            "top_expectancy": _get_top_expectancy_signals(5)
        },
        "phase1014": {
            "correlation_pairs": len(_state["phase1014"]["correlations"]),
            "recent_allocations": len(_state["phase1014"]["last_allocation"]),
            "cluster_count": len(set(
                alloc.get("cluster_size", 0) 
                for alloc in _state["phase1014"]["last_allocation"].values()
            ))
        },
        "phase1015": {
            "last_audit": _state["phase1015"].get("last_audit"),
            "total_issues": _state["phase1015"].get("issues_detected", 0),
            "total_repairs": _state["phase1015"].get("repairs_applied", 0),
            "recent_repairs": _state["phase1015"]["repairs"][-10:]
        }
    }

def _get_top_expectancy_signals(limit: int = 10) -> List[dict]:
    """Get top expectancy signals sorted by score"""
    ledger = _state["phase1013"]["ledger"]
    
    scored = []
    for key, row in ledger.items():
        if row["samples"] >= CFG1013.min_samples:
            score = get_expectancy_score(row["symbol"], row["strategy"])
            scored.append({
                "symbol": row["symbol"],
                "strategy": row["strategy"],
                "expectancy_score": score,
                "samples": row["samples"],
                "avg_edge": row["avg_edge"],
                "exec_quality": row["exec_quality"],
                "exit_efficiency": row["exit_efficiency"]
            })
    
    scored.sort(key=lambda x: x["expectancy_score"], reverse=True)
    return scored[:limit]

def get_expectancy_ledger() -> dict:
    """Get full expectancy ledger"""
    return _state["phase1013"]["ledger"]

def get_correlation_matrix() -> dict:
    """Get correlation matrix"""
    return _state["phase1014"]["correlations"]

def get_recent_allocations() -> dict:
    """Get recent risk parity allocations"""
    return _state["phase1014"]["last_allocation"]

def get_audit_history() -> List[dict]:
    """Get degradation audit history"""
    return _state["phase1015"]["repairs"]

# ======================================================================================
# Bootstrap
# ======================================================================================

def start_phase1013_1015():
    """Initialize Phases 10.13-10.15"""
    # Load persisted state before any operations
    _load_state()
    
    _append_event("phase1013_1015_started", {
        "phase1013": "Expectancy Attribution",
        "phase1014": "Risk Parity Allocation",
        "phase1015": "Degradation Auditor",
        "config": {
            "expectancy_min_samples": CFG1013.min_samples,
            "expectancy_decay": CFG1013.decay,
            "risk_parity": {
                "max_symbol_pct": CFG1014.max_symbol_risk_pct,
                "max_cluster_pct": CFG1014.max_cluster_risk_pct,
                "correlation_threshold": CFG1014.correlation_threshold
            },
            "audit_tick_sec": CFG1015.audit_tick_sec
        }
    })
    
    print("⚡ Starting Phase 10.13-10.15 (Expectancy + Risk Parity + Auditor)...")
    print(f"   ℹ️  Phase 10.13 - Expectancy Attribution: decay={CFG1013.decay}, min_samples={CFG1013.min_samples}")
    print(f"   ℹ️  Phase 10.14 - Risk Parity: symbol_cap={CFG1014.max_symbol_risk_pct*100}%, cluster_cap={CFG1014.max_cluster_risk_pct*100}%")
    print(f"   ℹ️  Phase 10.15 - Degradation Auditor: tick={CFG1015.audit_tick_sec}s, auto_repair={CFG1015.repair_enabled}")
    print("✅ Phase 10.13-10.15 started (audit tick every 10min)")
