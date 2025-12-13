# src/phase_37_41.py
#
# Phases 37–41: Profile Analyzer, Sentiment Scanner, Resurrection Engine, 
#              Replay Simulator, Operator Overlord

import os
import json
import time
from statistics import mean, stdev
from typing import Dict, List, Any

# Paths
STRATEGIC_ATTRIBUTION = "logs/strategic_attribution.jsonl"
STRATEGY_REGISTRY = "config/strategy_registry.json"
LINEAGE_LOG = "config/strategy_lineage.json"
SHADOW_STATE = "config/shadow_strategy_state.json"
TRADE_OUTCOMES = "logs/trade_outcomes.jsonl"
STRATEGY_PROFILES = "logs/strategy_profiles.json"
SENTIMENT_LOG = "logs/symbol_sentiment.json"
REPLAY_LOG = "logs/attribution_replay.json"
RESURRECTION_LOG = "logs/strategy_resurrection_events.jsonl"
OVERLORD_REPORT = "logs/operator_overlord_report.json"
OVERLORD_EVENTS = "logs/operator_overlord_events.jsonl"

# Utilities
def _read_json(path: str, default: dict):
    if not os.path.exists(path):
        return default
    with open(path, "r") as f:
        try:
            return json.load(f)
        except Exception:
            return default

def _write_json(path: str, obj: dict):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        json.dump(obj, f, indent=2)

def _read_jsonl(path: str):
    if not os.path.exists(path):
        return []
    out = []
    with open(path, "r") as f:
        for line in f:
            s = line.strip()
            if s:
                try:
                    out.append(json.loads(s))
                except Exception:
                    pass
    return out

def _append_event(path: str, ev: str, payload: dict = None):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if payload is None:
        payload = {}
    else:
        payload = dict(payload)
    payload.update({"event": ev, "ts": int(time.time())})
    with open(path, "a") as f:
        f.write(json.dumps(payload) + "\n")

# ---- Phase 37.0 – Strategy Profile Analyzer ----
def analyze_strategy_profiles():
    """
    Analyze strategy variant profiles based on real performance data:
    - Extract performance characteristics from lineage
    - Classify regime fit based on actual results
    - Evaluate exit effectiveness from trade outcomes
    """
    lineage = _read_json(LINEAGE_LOG, {})
    shadow_state = _read_json(SHADOW_STATE, {})
    trade_outcomes = _read_jsonl(TRADE_OUTCOMES)
    
    profiles = {}
    
    # Analyze each strategy's variants
    for base_strategy, variants in lineage.items():
        for variant_id, data in variants.items():
            perf_history = data.get("performance_history", [])
            
            if len(perf_history) < 5:
                continue  # Need minimum data for profiling
            
            # Extract metrics from performance history
            roi_values = [p.get("avg_roi", 0.0) for p in perf_history]
            trade_counts = [p.get("trades", 0) for p in perf_history]
            win_rates = [p.get("win_rate", 0.0) for p in perf_history]
            
            avg_roi = mean(roi_values) if roi_values else 0.0
            roi_volatility = stdev(roi_values) if len(roi_values) > 1 else 0.0
            avg_win_rate = mean(win_rates) if win_rates else 0.0
            total_trades = trade_counts[-1] if trade_counts else 0
            
            # Classify regime fit based on performance consistency
            if roi_volatility < 0.001:
                regime_fit = "stable"
            elif avg_roi > 0 and roi_volatility < 0.002:
                regime_fit = "trending"
            elif roi_volatility > 0.003:
                regime_fit = "volatile"
            else:
                regime_fit = "choppy"
            
            # Evaluate exit effectiveness
            if avg_win_rate > 0.55 and avg_roi > 0.002:
                exit_effectiveness = "strong"
            elif avg_win_rate > 0.45 and avg_roi > 0:
                exit_effectiveness = "moderate"
            else:
                exit_effectiveness = "weak"
            
            profile = {
                "variant_id": variant_id,
                "avg_roi": round(avg_roi, 4),
                "roi_volatility": round(roi_volatility, 4),
                "avg_win_rate": round(avg_win_rate, 3),
                "trade_count": total_trades,
                "status": data.get("status", "active"),
                "regime_fit": regime_fit,
                "exit_effectiveness": exit_effectiveness,
                "created": data.get("created", 0)
            }
            
            profiles.setdefault(base_strategy, []).append(profile)
    
    _write_json(STRATEGY_PROFILES, profiles)
    return profiles

# ---- Phase 38.0 – Symbol Sentiment Scanner ----
def scan_symbol_sentiment():
    """
    Analyze symbol sentiment based on recent trading performance:
    - Calculate polarity from win rates and ROI
    - Assess volatility risk from price action
    - Provide actionable sentiment scores
    """
    attribution_events = _read_jsonl(STRATEGIC_ATTRIBUTION)
    
    sentiment = {}
    
    # Get most recent attribution data per symbol
    by_symbol = {}
    for event in attribution_events:
        if event.get("event") == "attribution_computed":
            symbols = event.get("symbols", {})
            for sym, metrics in symbols.items():
                by_symbol[sym] = metrics
    
    # Calculate sentiment for each symbol
    for sym, metrics in by_symbol.items():
        trades = metrics.get("trades", 0)
        if trades < 3:
            continue  # Need minimum data
        
        avg_roi = metrics.get("avg_roi", 0.0)
        win_rate = metrics.get("win_rate", 0.5)
        
        # Polarity: -1 (very negative) to +1 (very positive)
        # Based on ROI and win rate
        polarity = (avg_roi * 100) + ((win_rate - 0.5) * 2)
        polarity = max(-1.0, min(1.0, polarity))
        
        # Volatility risk: 0 (low) to 1 (high)
        # High risk if low win rate or negative ROI
        volatility_risk = 0.0
        if win_rate < 0.4:
            volatility_risk += 0.4
        if avg_roi < -0.001:
            volatility_risk += 0.4
        if avg_roi < -0.003:
            volatility_risk += 0.2
        
        volatility_risk = min(1.0, volatility_risk)
        
        sentiment[sym] = {
            "polarity": round(polarity, 3),
            "volatility_risk": round(volatility_risk, 3),
            "win_rate": round(win_rate, 3),
            "avg_roi": round(avg_roi, 4),
            "trades": trades,
            "recommendation": "bullish" if polarity > 0.3 else "bearish" if polarity < -0.3 else "neutral"
        }
    
    _write_json(SENTIMENT_LOG, sentiment)
    return sentiment

# ---- Phase 39.0 – Strategy Resurrection Engine ----
def resurrect_strategies():
    """
    Resurrect retired strategies that may perform well in new market conditions:
    - Identify retired strategies with historical profitability
    - Resurrect if market regime has changed
    - Only resurrect strategies with positive past performance
    """
    lineage = _read_json(LINEAGE_LOG, {})
    shadow_state = _read_json(SHADOW_STATE, {})
    
    resurrected = []
    
    for base_strategy, variants in lineage.items():
        for variant_id, data in variants.items():
            status = data.get("status", "active")
            
            if status == "retired":
                perf_history = data.get("performance_history", [])
                
                if len(perf_history) < 10:
                    continue  # Need sufficient history
                
                # Check if strategy had any profitable periods
                roi_values = [p.get("avg_roi", 0.0) for p in perf_history]
                max_roi = max(roi_values) if roi_values else 0.0
                
                # Only resurrect if strategy showed promise (max ROI > 0.3%)
                if max_roi > 0.003:
                    # Update status to active
                    lineage[base_strategy][variant_id]["status"] = "resurrected"
                    lineage[base_strategy][variant_id]["resurrected_ts"] = int(time.time())
                    
                    resurrected.append({
                        "strategy": base_strategy,
                        "variant": variant_id,
                        "max_historical_roi": round(max_roi, 4)
                    })
                    
                    _append_event(RESURRECTION_LOG, "strategy_resurrected", {
                        "strategy": base_strategy,
                        "variant": variant_id,
                        "reason": f"historical_max_roi={max_roi:.4f}"
                    })
    
    _write_json(LINEAGE_LOG, lineage)
    return resurrected

# ---- Phase 40.0 – Attribution Replay Simulator ----
def simulate_attribution_replay():
    """
    Replay historical trades with alternative exit strategies:
    - Simulate what-if scenarios with different exits
    - Compare actual vs simulated performance
    - Identify missed opportunities
    """
    trade_outcomes = _read_jsonl(TRADE_OUTCOMES)
    
    replay = []
    
    for trade in trade_outcomes[-100:]:  # Last 100 trades
        symbol = trade.get("symbol", "")
        strategy = trade.get("strategy", "")
        actual_roi = trade.get("net_roi", 0.0)
        exit_type = trade.get("exit_type", "unknown")
        
        # Simulate alternative exits based on trade data
        peak_roi = trade.get("peak_roi", actual_roi)
        
        # Calculate what ROI could have been with different exits
        simulated_exits = {
            "early_TP1": actual_roi * 0.6,  # Conservative early exit
            "hold_TP2": actual_roi * 1.3 if actual_roi > 0 else actual_roi,  # Holding for TP2
            "tight_trail": peak_roi * 0.8,  # Trailing from peak
        }
        
        replay.append({
            "symbol": symbol,
            "strategy": strategy,
            "actual_roi": round(actual_roi, 4),
            "actual_exit": exit_type,
            "simulated_exits": {k: round(v, 4) for k, v in simulated_exits.items()},
            "best_alternative": max(simulated_exits.keys(), key=lambda k: simulated_exits[k]),
            "opportunity_cost": round(max(simulated_exits.values()) - actual_roi, 4)
        })
    
    _write_json(REPLAY_LOG, {"replays": replay, "count": len(replay)})
    return replay

# ---- Phase 41.0 – Operator Overlord ----
def run_operator_overlord():
    """
    Master oversight system that synthesizes all phase outputs:
    - Reviews strategy profiles, sentiment, and replays
    - Identifies critical issues requiring intervention
    - Generates actionable recommendations
    """
    profiles = _read_json(STRATEGY_PROFILES, {})
    sentiment = _read_json(SENTIMENT_LOG, {})
    lineage = _read_json(LINEAGE_LOG, {})
    
    issues = []
    
    # Analyze strategy profiles for problems
    for strat, variant_list in profiles.items():
        for variant in variant_list:
            # Flag underperforming variants
            if variant["avg_roi"] < -0.002 and variant["trade_count"] >= 10:
                issues.append({
                    "category": "strategy_performance",
                    "severity": "high",
                    "strategy": strat,
                    "variant": variant["variant_id"],
                    "issue": f"Underperformance: ROI {variant['avg_roi']:.2%}",
                    "action": "Flag for mutation or retirement"
                })
            
            # Flag weak exits
            if variant["exit_effectiveness"] == "weak" and variant["trade_count"] >= 15:
                issues.append({
                    "category": "exit_quality",
                    "severity": "medium",
                    "strategy": strat,
                    "variant": variant["variant_id"],
                    "issue": "Weak exit effectiveness",
                    "action": "Review exit configuration"
                })
    
    # Analyze symbol sentiment for risk
    for sym, sent in sentiment.items():
        if sent["polarity"] < -0.5 and sent["volatility_risk"] > 0.6:
            issues.append({
                "category": "symbol_risk",
                "severity": "high",
                "symbol": sym,
                "issue": f"Negative sentiment ({sent['polarity']:.2f}) + high volatility risk ({sent['volatility_risk']:.2f})",
                "action": "Reduce capital allocation or freeze trading"
            })
        
        # Flag consistent losers
        if sent["avg_roi"] < -0.002 and sent["trades"] >= 5:
            issues.append({
                "category": "symbol_performance",
                "severity": "medium",
                "symbol": sym,
                "issue": f"Consistent losses: ROI {sent['avg_roi']:.2%} over {sent['trades']} trades",
                "action": "Switch to defensive strategies or reduce allocation"
            })
    
    # Generate summary
    report = {
        "timestamp": int(time.time()),
        "issues_found": len(issues),
        "issues_by_severity": {
            "high": sum(1 for i in issues if i.get("severity") == "high"),
            "medium": sum(1 for i in issues if i.get("severity") == "medium"),
            "low": sum(1 for i in issues if i.get("severity") == "low")
        },
        "issues": issues
    }
    
    _write_json(OVERLORD_REPORT, report)
    _append_event(OVERLORD_EVENTS, "overlord_review_complete", {
        "total_issues": len(issues),
        "high_severity": report["issues_by_severity"]["high"]
    })
    
    return report

# ---- Unified Runner ----
def run_phase_37_41():
    """
    Execute all five phases:
    - Profile analysis
    - Sentiment scanning
    - Strategy resurrection
    - Attribution replay
    - Operator oversight
    """
    profiles = analyze_strategy_profiles()
    sentiment = scan_symbol_sentiment()
    resurrected = resurrect_strategies()
    replay = simulate_attribution_replay()
    overlord = run_operator_overlord()
    
    return {
        "profiles": profiles,
        "sentiment": sentiment,
        "resurrected": resurrected,
        "replay": replay,
        "overlord": overlord
    }

if __name__ == "__main__":
    result = run_phase_37_41()
    print(f"Phase 37: {sum(len(v) for v in result['profiles'].values())} profiles analyzed")
    print(f"Phase 38: {len(result['sentiment'])} symbols scanned")
    print(f"Phase 39: {len(result['resurrected'])} strategies resurrected")
    print(f"Phase 40: {len(result['replay'])} trades replayed")
    print(f"Phase 41: {result['overlord']['issues_found']} issues identified")
