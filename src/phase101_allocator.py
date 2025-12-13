"""
Phase 10.1 — Attribution-Weighted Allocator + Strategic Enhancements
Integrates breach alerting, venue attribution scoring, shadow experiments, and reward shaping.
"""

import time
import json
import os
from typing import Dict, List, Optional
from src.net_pnl_enforcement import get_net_pnl, get_net_roi

class Phase101Cfg:
    breach_alert_threshold = 3
    breach_window_sec = 86400  # 24h
    reward_decay = 0.98
    reward_boost_win = 1.05
    reward_penalty_loss = 0.95
    attribution_window_trades = 200
    venue_paths = ["spot", "futures"]
    state_path = "logs/phase101_state.json"
    events_path = "logs/phase101_events.jsonl"

CFG101 = Phase101Cfg()

STATE101 = {
    "breach_attempts": [],
    "attribution": {"spot": {}, "futures": {}, "strategy": {}},
    "shadow": {"wins": {}, "enabled": True}
}

def _persist_state():
    os.makedirs(os.path.dirname(CFG101.state_path), exist_ok=True)
    with open(CFG101.state_path, "w") as f:
        json.dump(STATE101, f, indent=2)

def _append_event(event: str, payload: dict):
    os.makedirs(os.path.dirname(CFG101.events_path), exist_ok=True)
    row = {"ts": int(time.time()), "event": event, "payload": payload}
    with open(CFG101.events_path, "a") as f:
        f.write(json.dumps(row) + "\n")

def _load_state():
    global STATE101
    if os.path.exists(CFG101.state_path):
        try:
            with open(CFG101.state_path, "r") as f:
                STATE101 = json.load(f)
        except (json.JSONDecodeError, FileNotFoundError):
            pass

def record_breach_attempt(symbol: str, venue: str, strategy: str):
    """Record enforcement breach attempt and alert if threshold exceeded."""
    STATE101["breach_attempts"].append(time.time())
    _persist_state()
    
    recent_breaches = [t for t in STATE101["breach_attempts"] if time.time() - t < CFG101.breach_window_sec]
    
    if len(recent_breaches) >= CFG101.breach_alert_threshold:
        print(f"🚨 PHASE 10.1 BREACH ALERT: {len(recent_breaches)} attempts in 24h (threshold: {CFG101.breach_alert_threshold})")
        _append_event("phase101_breach_alert", {
            "symbol": symbol,
            "venue": venue,
            "strategy": strategy,
            "count": len(recent_breaches)
        })
        
        try:
            from src.phase87_89_expansion import get_phase87_89_expansion
            phase87 = get_phase87_89_expansion()
            phase87.log_critical_event("phase101_breach_alert", {
                "symbol": symbol,
                "venue": venue,
                "strategy": strategy,
                "count": len(recent_breaches)
            })
        except Exception:
            pass

def update_attribution(symbol: str, strategy: str, net_pnl_usd: float, venue: str = "spot"):
    """
    Update venue and strategy attribution scores based on trade outcome.
    
    Args:
        symbol: Trading symbol
        strategy: Strategy name
        net_pnl_usd: Net P&L in USD (AFTER ALL FEES) - already fee-aware from position_manager
        venue: Trading venue (spot or futures)
    
    CRITICAL: net_pnl_usd parameter is ALREADY net of all fees from position_manager.
    """
    # Decay all scores
    for v in CFG101.venue_paths:
        for k in list(STATE101["attribution"][v].keys()):
            STATE101["attribution"][v][k] *= CFG101.reward_decay
    
    for k in list(STATE101["attribution"]["strategy"].keys()):
        STATE101["attribution"]["strategy"][k] *= CFG101.reward_decay
    
    # Reward/Penalty
    is_win = net_pnl_usd > 0
    
    # Get current portfolio value
    try:
        from src.portfolio_tracker import load_portfolio
        portfolio = load_portfolio()
        portfolio_val = portfolio.get("current_value", 10000)
    except Exception:
        portfolio_val = 10000
    
    mag = max(0.5, min(2.0, 1.0 + abs(net_pnl_usd) / portfolio_val))
    
    sscore = STATE101["attribution"][venue].get(symbol, 1.0)
    tscore = STATE101["attribution"]["strategy"].get(strategy, 1.0)
    
    sscore *= (CFG101.reward_boost_win if is_win else CFG101.reward_penalty_loss) * mag
    tscore *= (CFG101.reward_boost_win if is_win else CFG101.reward_penalty_loss) * mag
    
    STATE101["attribution"][venue][symbol] = sscore
    STATE101["attribution"]["strategy"][strategy] = tscore
    
    _persist_state()
    _append_event("phase101_attribution_update", {
        "symbol": symbol,
        "sscore": round(sscore, 3),
        "strategy": strategy,
        "tscore": round(tscore, 3),
        "net_pnl": round(net_pnl_usd, 2)
    })

def get_attribution_multiplier(symbol: str, strategy: str, venue: str = "spot") -> float:
    """Get allocation multiplier based on attribution scores."""
    sscore = STATE101["attribution"][venue].get(symbol, 1.0)
    tscore = STATE101["attribution"]["strategy"].get(strategy, 1.0)
    multiplier = max(0.5, min(2.0, (sscore + tscore) / 2.0))
    return multiplier

def shadow_feedback(strategy: str, net_pnl_usd: float):
    """
    Track shadow strategy performance for promotion evaluation.
    
    Args:
        strategy: Strategy name
        net_pnl_usd: Net P&L in USD (AFTER ALL FEES) - already fee-aware from position_manager
    
    CRITICAL: net_pnl_usd parameter is ALREADY net of all fees from position_manager.
    """
    if not STATE101["shadow"]["enabled"]:
        return
    
    wins = STATE101["shadow"]["wins"].get(strategy, 0)
    if net_pnl_usd > 0:
        wins += 1
    else:
        wins = max(0, wins - 1)
    
    STATE101["shadow"]["wins"][strategy] = wins
    _persist_state()
    _append_event("phase101_shadow_feedback", {
        "strategy": strategy,
        "wins": wins,
        "net_pnl": round(net_pnl_usd, 2)
    })

def try_promote_strategy(strategy: str) -> bool:
    """Check if shadow strategy meets promotion criteria."""
    wins = STATE101["shadow"]["wins"].get(strategy, 0)
    
    if wins >= 3:
        print(f"✅ PHASE 10.1: Shadow strategy {strategy} eligible for promotion ({wins} wins)")
        _append_event("phase101_strategy_promoted", {
            "strategy": strategy,
            "wins": wins
        })
        return True
    
    return False

def get_breach_stats() -> Dict:
    """Get breach attempt statistics."""
    recent_breaches = [t for t in STATE101["breach_attempts"] if time.time() - t < CFG101.breach_window_sec]
    
    return {
        "total_breaches": len(STATE101["breach_attempts"]),
        "recent_24h": len(recent_breaches),
        "threshold": CFG101.breach_alert_threshold,
        "alert_active": len(recent_breaches) >= CFG101.breach_alert_threshold
    }

def get_attribution_scores() -> Dict:
    """Get current attribution scores for dashboard."""
    return {
        "spot": dict(STATE101["attribution"]["spot"]),
        "futures": dict(STATE101["attribution"]["futures"]),
        "strategy": dict(STATE101["attribution"]["strategy"])
    }

def start_phase101_allocator():
    """Initialize Phase 10.1 Allocator."""
    _load_state()
    print("🚀 Starting Phase 10.1 Allocator...")
    print("   ℹ️  Breach alerting: 3 attempts/24h threshold")
    print("   ℹ️  Attribution: Venue + strategy reward shaping")
    print("   ℹ️  Shadow experiments: Win-based promotion gates")
    print("✅ Phase 10.1 Allocator started")
    _append_event("phase101_started", {"cfg": "loaded"})
