"""
Policy Cap Event Logging for Autonomous Optimization Detection

Emits structured events whenever Kelly sizing or other systems hit policy caps,
enabling the autonomous operator to detect optimization opportunities.
"""
import json
import os
from datetime import datetime
from pathlib import Path


def emit_policy_cap_event(event_type, data):
    """
    Emit a structured policy cap event for autonomous consumption.
    
    Args:
        event_type: Type of cap event ("kelly_policy_cap", "budget_cap", "governance_cap")
        data: Event-specific data dictionary
    """
    log_dir = Path("logs")
    log_dir.mkdir(exist_ok=True)
    log_file = log_dir / "policy_cap_events.jsonl"
    
    event = {
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "event_type": event_type,
        **data
    }
    
    with open(log_file, "a") as f:
        f.write(json.dumps(event) + "\n")


def emit_kelly_policy_cap(
    venue,
    strategy,
    regime,
    symbol,
    requested_size,
    final_size,
    min_limit,
    max_limit,
    cap_reason
):
    """
    Emit event when Kelly sizing hits policy cap.
    
    Args:
        venue: "spot" or "futures"
        strategy: Strategy name
        regime: Current market regime
        symbol: Trading symbol
        requested_size: Kelly-calculated size before cap
        final_size: Final size after policy cap
        min_limit: Policy minimum limit
        max_limit: Policy maximum limit
        cap_reason: "min_cap" or "max_cap"
    """
    reduction_pct = ((final_size - requested_size) / requested_size * 100) if requested_size > 0 else 0.0
    
    emit_policy_cap_event("kelly_policy_cap", {
        "venue": venue,
        "strategy": strategy,
        "regime": regime,
        "symbol": symbol,
        "requested_size_usd": round(requested_size, 2),
        "final_size_usd": round(final_size, 2),
        "reduction_usd": round(requested_size - final_size, 2),
        "reduction_pct": round(reduction_pct, 2),
        "policy_min": min_limit,
        "policy_max": max_limit,
        "cap_reason": cap_reason,
        "severity": "high" if abs(reduction_pct) > 30 else "medium"
    })


def emit_budget_cap(
    venue,
    strategy,
    regime,
    symbol,
    requested_margin,
    budget_limit,
    final_margin
):
    """
    Emit event when requested margin hits strategy budget cap.
    
    Args:
        venue: "spot" or "futures"
        strategy: Strategy name
        regime: Current market regime
        symbol: Trading symbol
        requested_margin: Kelly-calculated margin request
        budget_limit: Strategy margin budget from allocator
        final_margin: Final margin after budget cap
    """
    reduction_pct = ((final_margin - requested_margin) / requested_margin * 100) if requested_margin > 0 else 0.0
    
    emit_policy_cap_event("budget_cap", {
        "venue": venue,
        "strategy": strategy,
        "regime": regime,
        "symbol": symbol,
        "requested_margin_usd": round(requested_margin, 2),
        "budget_limit_usd": round(budget_limit, 2),
        "final_margin_usd": round(final_margin, 2),
        "reduction_usd": round(requested_margin - budget_limit, 2),
        "reduction_pct": round(reduction_pct, 2),
        "severity": "high" if abs(reduction_pct) > 30 else "medium"
    })


def emit_profit_per_trade_metric(
    symbol,
    strategy,
    venue,
    position_size_usd,
    profit_usd,
    roi_pct,
    trade_duration_seconds
):
    """
    Emit profit-per-trade metric for USD P&L velocity tracking.
    
    Args:
        symbol: Trading symbol
        strategy: Strategy name
        venue: "spot" or "futures"
        position_size_usd: Position size in USD
        profit_usd: Realized profit in USD
        roi_pct: ROI as percentage
        trade_duration_seconds: Trade duration in seconds
    """
    profit_per_hour = (profit_usd / trade_duration_seconds * 3600) if trade_duration_seconds > 0 else 0.0
    
    emit_policy_cap_event("profit_per_trade", {
        "symbol": symbol,
        "strategy": strategy,
        "venue": venue,
        "position_size_usd": round(position_size_usd, 2),
        "profit_usd": round(profit_usd, 4),
        "roi_pct": round(roi_pct, 4),
        "trade_duration_seconds": trade_duration_seconds,
        "profit_per_hour_usd": round(profit_per_hour, 4),
        "is_profitable": profit_usd > 0,
        "is_meaningful": profit_usd >= 0.50  # $0.50+ profits are meaningful
    })


def get_policy_cap_summary(hours=24):
    """
    Get summary of policy cap events in the last N hours.
    
    Args:
        hours: Number of hours to look back
    
    Returns:
        dict: Summary statistics
    """
    log_file = Path("logs/policy_cap_events.jsonl")
    if not log_file.exists():
        return {
            "total_caps": 0,
            "kelly_policy_caps": 0,
            "budget_caps": 0,
            "avg_reduction_pct": 0.0,
            "high_severity_count": 0
        }
    
    cutoff_time = datetime.utcnow().timestamp() - (hours * 3600)
    
    kelly_caps = []
    budget_caps = []
    high_severity = 0
    
    with open(log_file, "r") as f:
        for line in f:
            if not line.strip():
                continue
            event = json.loads(line)
            
            event_time = datetime.fromisoformat(event["timestamp"].replace("Z", "")).timestamp()
            if event_time < cutoff_time:
                continue
            
            if event["event_type"] == "kelly_policy_cap":
                kelly_caps.append(event)
                if event.get("severity") == "high":
                    high_severity += 1
            elif event["event_type"] == "budget_cap":
                budget_caps.append(event)
                if event.get("severity") == "high":
                    high_severity += 1
    
    all_caps = kelly_caps + budget_caps
    avg_reduction = sum(abs(c.get("reduction_pct", 0)) for c in all_caps) / len(all_caps) if all_caps else 0.0
    
    # Calculate severity counts by reduction percentage
    medium_severity = sum(1 for c in all_caps if 15 < c.get("reduction_pct", 0) <= 30)
    low_severity = sum(1 for c in all_caps if c.get("reduction_pct", 0) <= 15)
    
    return {
        "total_caps": len(all_caps),
        "kelly_policy_caps": len(kelly_caps),
        "budget_caps": len(budget_caps),
        "avg_reduction_pct": round(avg_reduction, 2),
        "high_severity_count": high_severity,
        "medium_severity_count": medium_severity,
        "low_severity_count": low_severity,
        "sample_recent": all_caps[-5:] if all_caps else []
    }


def get_profit_velocity_summary(hours=24):
    """
    Get USD P&L velocity summary from profit-per-trade events.
    
    Args:
        hours: Number of hours to look back
    
    Returns:
        dict: Profit velocity statistics
    """
    log_file = Path("logs/policy_cap_events.jsonl")
    if not log_file.exists():
        return {
            "total_trades": 0,
            "avg_profit_usd": 0.0,
            "avg_profit_per_hour_usd": 0.0,
            "meaningful_profit_count": 0
        }
    
    cutoff_time = datetime.utcnow().timestamp() - (hours * 3600)
    
    profit_events = []
    
    with open(log_file, "r") as f:
        for line in f:
            if not line.strip():
                continue
            event = json.loads(line)
            
            event_time = datetime.fromisoformat(event["timestamp"].replace("Z", "")).timestamp()
            if event_time < cutoff_time:
                continue
            
            if event["event_type"] == "profit_per_trade":
                profit_events.append(event)
    
    if not profit_events:
        return {
            "total_trades": 0,
            "avg_profit_usd": 0.0,
            "avg_profit_per_hour_usd": 0.0,
            "meaningful_profit_count": 0,
            "meaningful_profit_pct": 0.0
        }
    
    avg_profit = sum(e.get("profit_usd", 0) for e in profit_events) / len(profit_events)
    avg_profit_per_hour = sum(e.get("profit_per_hour_usd", 0) for e in profit_events) / len(profit_events)
    meaningful_count = sum(1 for e in profit_events if e.get("is_meaningful", False))
    
    return {
        "total_trades": len(profit_events),
        "avg_profit_usd": round(avg_profit, 4),
        "avg_profit_per_hour_usd": round(avg_profit_per_hour, 4),
        "meaningful_profit_count": meaningful_count,
        "meaningful_profit_pct": round(meaningful_count / len(profit_events) * 100, 2) if profit_events else 0.0
    }
