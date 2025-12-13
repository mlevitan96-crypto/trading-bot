"""
Missed opportunity tracking and adaptive threshold tuning.
"""
import json
from datetime import datetime, timedelta
from pathlib import Path
import pandas as pd
import pytz

MISSED_LOG_FILE = "logs/missed_opportunities.json"
ARIZONA_TZ = pytz.timezone('America/Phoenix')

def get_arizona_time():
    """Get current time in Arizona timezone."""
    return datetime.now(ARIZONA_TZ)

def initialize_missed_log():
    """Initialize missed opportunities log file."""
    Path("logs").mkdir(exist_ok=True)
    if not Path(MISSED_LOG_FILE).exists():
        log = {
            "missed_trades": [],
            "heatmap": {},
            "created_at": get_arizona_time().isoformat()
        }
        with open(MISSED_LOG_FILE, 'w') as f:
            json.dump(log, f, indent=2)

def log_missed_trade(symbol, strategy, filters_blocked, entry_price, exit_price, indicators, regime):
    """
    Log a missed trading opportunity.
    
    Args:
        symbol: Trading pair
        strategy: Strategy name
        filters_blocked: List of filters that blocked the trade
        entry_price: Would-be entry price
        exit_price: Would-be exit price
        indicators: Dict of indicator values
        regime: Current market regime
    """
    initialize_missed_log()
    
    roi = (exit_price - entry_price) / entry_price
    
    # Only log if it would have been profitable
    if roi > 0.002:
        with open(MISSED_LOG_FILE, 'r') as f:
            log = json.load(f)
        
        missed_trade = {
            "timestamp": get_arizona_time().isoformat(),
            "symbol": symbol,
            "strategy": strategy,
            "regime": regime,
            "filters_blocked": filters_blocked,
            "entry_price": round(entry_price, 2),
            "exit_price": round(exit_price, 2),
            "missed_roi": round(roi, 6),
            "indicators": {k: round(v, 6) if isinstance(v, (int, float)) else v for k, v in indicators.items()}
        }
        
        log["missed_trades"].append(missed_trade)
        
        # Update heatmap (initialize if missing)
        if "heatmap" not in log:
            log["heatmap"] = {}
        
        key = f"{symbol}_{regime}"
        if key not in log["heatmap"]:
            log["heatmap"][key] = {}
        for f in filters_blocked:
            log["heatmap"][key][f] = log["heatmap"][key].get(f, 0) + 1
        
        # Keep last 200 missed trades
        if len(log["missed_trades"]) > 200:
            log["missed_trades"] = log["missed_trades"][-200:]
        
        with open(MISSED_LOG_FILE, 'w') as f:
            json.dump(log, f, indent=2)
        
        print(f"📊 Missed opportunity: {symbol} | Filters: {', '.join(filters_blocked)} | Would-be ROI: {roi*100:.2f}%")

def score_signal(ema_ok, momentum_ok, volume_ok, roi_ok):
    """
    Calculate signal confidence score (0-1).
    
    Args:
        ema_ok: EMA filter passed
        momentum_ok: Momentum filter passed
        volume_ok: Volume filter passed
        roi_ok: ROI filter passed
    
    Returns:
        Confidence score between 0 and 1
    """
    return sum([ema_ok, momentum_ok, volume_ok, roi_ok]) / 4.0

def detect_untracked_moves(symbol, df, strategy, regime):
    """
    Detect significant price moves that weren't captured by strategies.
    
    Args:
        symbol: Trading pair
        df: DataFrame with OHLCV data
        strategy: Strategy name
        regime: Current market regime
    """
    if len(df) < 2:
        return
    
    df_copy = df.copy()
    df_copy["roi"] = df_copy["close"].pct_change()
    spike = df_copy["roi"].iloc[-1]
    
    # Log if significant move (>1%)
    if abs(spike) > 0.01:
        indicators = {
            "ema_fast": df_copy["close"].ewm(span=12, adjust=False).mean().iloc[-1],
            "ema_slow": df_copy["close"].ewm(span=26, adjust=False).mean().iloc[-1],
            "momentum": df_copy["close"].diff().iloc[-1],
            "volume": df_copy["volume"].iloc[-1],
            "volume_ma": df_copy["volume"].rolling(window=10).mean().iloc[-1]
        }
        log_missed_trade(
            symbol=symbol,
            strategy=strategy,
            filters_blocked=["No Signal"],
            entry_price=df_copy["close"].iloc[-2],
            exit_price=df_copy["close"].iloc[-1],
            indicators=indicators,
            regime=regime
        )

def get_missed_opportunities_stats():
    """
    Get statistics on missed opportunities.
    
    Returns:
        Dict with statistics
    """
    if not Path(MISSED_LOG_FILE).exists():
        return {"total_missed": 0, "total_roi_missed": 0}
    
    with open(MISSED_LOG_FILE, 'r') as f:
        log = json.load(f)
    
    missed = log.get("missed_trades", [])
    
    if not missed:
        return {"total_missed": 0, "total_roi_missed": 0}
    
    total_roi = sum(m["missed_roi"] for m in missed)
    
    # Group by filter
    filter_stats = {}
    for trade in missed:
        for f in trade["filters_blocked"]:
            if f not in filter_stats:
                filter_stats[f] = {"count": 0, "total_roi": 0}
            filter_stats[f]["count"] += 1
            filter_stats[f]["total_roi"] += trade["missed_roi"]
    
    return {
        "total_missed": len(missed),
        "total_roi_missed": round(total_roi, 4),
        "by_filter": filter_stats,
        "heatmap": log.get("heatmap", {})
    }

def auto_tune_thresholds():
    """
    Automatically adjust thresholds based on missed opportunities.
    
    Returns:
        Dict with tuning recommendations
    """
    if not Path(MISSED_LOG_FILE).exists():
        return {"message": "No missed opportunities to analyze"}
    
    with open(MISSED_LOG_FILE, 'r') as f:
        log = json.load(f)
    
    missed = log.get("missed_trades", [])
    
    if not missed:
        return {"message": "No missed opportunities to analyze"}
    
    df = pd.DataFrame(missed)
    
    # Group by filters blocked
    grouped = df.groupby(df["filters_blocked"].apply(lambda x: ','.join(x)))["missed_roi"].agg(['mean', 'count'])
    
    recommendations = {}
    
    # Check each filter type
    roi_blocked = df[df["filters_blocked"].apply(lambda x: "ROI" in x)]
    if len(roi_blocked) > 0 and roi_blocked["missed_roi"].mean() > 0.005:
        recommendations["ROI"] = {
            "current": 0.003,
            "suggested": 0.002,
            "reason": f"Blocked {len(roi_blocked)} trades with avg ROI {roi_blocked['missed_roi'].mean():.4f}"
        }
    
    momentum_blocked = df[df["filters_blocked"].apply(lambda x: "Momentum" in x)]
    if len(momentum_blocked) > 0 and momentum_blocked["missed_roi"].mean() > 0.005:
        recommendations["Momentum"] = {
            "current": 0.0,
            "suggested": -0.001,
            "reason": f"Blocked {len(momentum_blocked)} trades with avg ROI {momentum_blocked['missed_roi'].mean():.4f}"
        }
    
    volume_blocked = df[df["filters_blocked"].apply(lambda x: "Volume" in x)]
    if len(volume_blocked) > 0 and volume_blocked["missed_roi"].mean() > 0.005:
        recommendations["Volume"] = {
            "current": 1.0,
            "suggested": 0.9,
            "reason": f"Blocked {len(volume_blocked)} trades with avg ROI {volume_blocked['missed_roi'].mean():.4f}"
        }
    
    return {
        "total_analyzed": len(missed),
        "recommendations": recommendations,
        "top_filters": grouped.to_dict() if not grouped.empty else {}
    }


def learned_threshold_updates(missed_data, current_thresholds):
    """
    Analyze missed opportunities and generate threshold update recommendations.
    If suppressed signals frequently show net positive ROI, relax thresholds gradually.
    
    Args:
        missed_data: List of {missed_roi, filters_blocked, symbol, strategy, regime}
        current_thresholds: Dict of current threshold values by regime
    
    Returns:
        dict: Updated threshold recommendations
    """
    import numpy as np
    
    if not missed_data:
        return current_thresholds
    
    roi_pos = [m.get('missed_roi', 0) for m in missed_data if m.get('missed_roi', 0) > 0]
    avg_pos = np.mean(roi_pos) if roi_pos else 0.0
    
    updates = dict(current_thresholds)
    
    # Example tuning rules (gentle nudges)
    # ROI filter: if average missed ROI > 0.005, lower ROI threshold by 10% (bounded)
    if avg_pos > 0.005:
        for regime in updates:
            if isinstance(updates[regime], dict) and 'ROI' in updates[regime]:
                updates[regime]['ROI'] = max(0.0015, updates[regime]['ROI'] * 0.90)
    
    # Momentum filter: if many missed trades list 'Momentum', relax slightly
    momentum_missed = [m for m in missed_data if 'Momentum' in m.get('filters_blocked', [])]
    if len(momentum_missed) > 5:
        for regime in updates:
            if isinstance(updates[regime], dict) and 'Momentum' in updates[regime]:
                updates[regime]['Momentum'] = updates[regime]['Momentum'] - 0.0005
    
    # Volume filter: if 'Volume' blocks with avg positive ROI, ease by 5%
    vol_missed = [m for m in missed_data if 'Volume' in m.get('filters_blocked', []) and m.get('missed_roi', 0) > 0]
    if len(vol_missed) > 5:
        for regime in updates:
            if isinstance(updates[regime], dict) and 'VolumeRatio' in updates[regime]:
                updates[regime]['VolumeRatio'] = updates[regime]['VolumeRatio'] * 0.95
    
    return updates
