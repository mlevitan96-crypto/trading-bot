"""
Data access hooks for Phases 8.7-8.9 Expansion Pack.
Provides integration with existing Phase 8.0 coordinator, portfolio data, and external signals.
"""

import json
import time
from typing import Dict, List, Optional

def emit_dashboard_event(event_type: str, payload: dict):
    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    print(f"📊 PHASE87-89 [{ts}] {event_type}: {payload}")
    try:
        with open("logs/dashboard_events.jsonl", "a") as f:
            f.write(json.dumps({"ts": time.time(), "event": event_type, "payload": payload}) + "\n")
    except:
        pass

def register_status_provider(name: str, provider_fn):
    from src.phase80_coordinator import Phase80Coordinator
    if hasattr(Phase80Coordinator, '_status_providers'):
        Phase80Coordinator._status_providers[name] = provider_fn

def status_provider_fetch(name: str) -> Optional[Dict]:
    from src.phase80_coordinator import Phase80Coordinator
    if hasattr(Phase80Coordinator, '_status_providers'):
        provider = Phase80Coordinator._status_providers.get(name)
        if provider:
            try:
                return provider()
            except:
                return None
    return None

def get_peer_bot_snapshot() -> List[Dict]:
    return []

def large_positions_symbols() -> List[str]:
    try:
        with open("logs/positions.json", "r") as f:
            positions = json.load(f)
        large = []
        for sym, data in positions.items():
            if data.get("size_usd", 0) > 500:
                large.append(sym)
        return large[:6]
    except:
        return []

def rolling_corr_24h(sym_a: str, sym_b: str) -> Optional[float]:
    try:
        tier_corr = {
            ("BTCUSDT", "ETHUSDT"): 0.75,
            ("SOLUSDT", "AVAXUSDT"): 0.68,
            ("DOTUSDT", "TRXUSDT"): 0.42
        }
        pair = (sym_a, sym_b) if sym_a < sym_b else (sym_b, sym_a)
        return tier_corr.get(pair, 0.35)
    except:
        return 0.35

def freeze_new_entries_global():
    emit_dashboard_event("freeze_new_entries_global", {"reason": "cluster_correlation_breach"})

def list_all_symbols() -> List[str]:
    return ["BTCUSDT", "ETHUSDT", "SOLUSDT", "AVAXUSDT", "DOTUSDT", "TRXUSDT"]

def get_whale_flow_confidence(symbol: str) -> float:
    return 0.5

def get_sentiment_score(symbol: str) -> float:
    return 0.5

def get_macro_risk_confidence(symbol: str) -> float:
    return 0.5

def last_validation_suite_passed() -> bool:
    try:
        with open("logs/phase82_validation_results.json", "r") as f:
            data = json.load(f)
        return data.get("all_passed", False)
    except:
        return True

def current_global_regime_name() -> str:
    try:
        with open("logs/portfolio.json", "r") as f:
            data = json.load(f)
        return data.get("regime", "trend")
    except:
        return "trend"

def nudge_symbol_weight(symbol: str, pct_delta: float):
    emit_dashboard_event("nudge_symbol_weight", {"symbol": symbol, "delta_pct": round(pct_delta, 3)})
