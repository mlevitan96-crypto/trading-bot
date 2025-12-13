import math
import numpy as np
from collections import deque

# Persistent learning buffers (bounded) for rolling metrics
ENSEMBLE_STATE = {
    "rolling": {
        "win_rate": deque(maxlen=500),
        "payoff_ratio": deque(maxlen=500),
        "avg_edge": deque(maxlen=500)
    },
    "weights": {
        # Initial weights: can be tuned by learning_engine below
        "mtf": 0.35,           # Multi-timeframe alignment
        "volume": 0.20,        # Volume pressure / abnormality
        "momentum": 0.15,      # Momentum / ADX
        "regime": 0.20,        # Regime alignment score
        "cost_hurdle": 0.10    # Cost-of-trade hurdle
    },
    "threshold": 0.35        # PAPER MODE: Lowered from 0.60 to allow more trades for learning
}


def _zscore(value, series):
    """Calculate z-score of value relative to series."""
    if not series or len(series) < 20:
        return 0.0
    arr = np.array(series)
    mu, sigma = arr.mean(), arr.std() or 1e-6
    return (value - mu) / sigma


def compute_volume_pressure(df):
    """
    Calculate volume pressure score based on current vs historical volume.
    Returns: float [0.0-1.0]
    """
    vol = df['volume'].iloc[-1]
    rolling = df['volume'].rolling(20).mean().iloc[-1]
    q80 = df['volume'].rolling(50).quantile(0.8).iloc[-1]
    
    if math.isnan(rolling) or math.isnan(q80):
        return 0.0
    
    ratio = vol / max(rolling, 1e-6)
    bonus = 0.2 if vol > q80 else 0.0
    return min(1.0, max(0.0, 0.5 * ratio + bonus))


def compute_momentum_adx(df):
    """
    Simple ADX-like proxy using EMA gap slope and consecutive gains.
    Returns: float [0.0-1.0]
    """
    close = df['close']
    ema_fast = close.ewm(span=12, adjust=False).mean()
    ema_slow = close.ewm(span=26, adjust=False).mean()
    gap = (ema_fast - ema_slow) / (ema_slow.replace(0, 1e-6))
    slope = gap.diff().iloc[-1]
    consecutive_up = (close.diff() > 0).tail(6).sum() / 6.0
    score = 0.6 * max(0.0, slope) + 0.4 * consecutive_up
    return min(1.0, max(0.0, score))


def compute_regime_alignment(regime, strategy_name):
    """
    Calculate alignment score between regime and strategy.
    Returns: float (1.0 for favored strategies, 0.3 for others)
    """
    regime_map = {
        "Trending": ["Trend-Conservative", "Breakout-Aggressive"],
        "Volatile": ["Breakout-Aggressive", "Sentiment-Fusion"],
        "Stable": ["Sentiment-Fusion", "Trend-Conservative", "Breakout-Aggressive"],
        "Ranging": ["Trend-Conservative", "Sentiment-Fusion"]
    }
    active = regime_map.get(regime, ["Trend-Conservative"])
    return 1.0 if strategy_name in active else 0.3


def estimate_cost_hurdle(df, expected_roi):
    """
    Estimate total trading costs (fees + spread + slippage).
    Returns: (hurdle_cost, net_edge)
    """
    from src.fee_calculator import TAKER_FEE
    from src.slippage import calculate_volatility
    
    vol = calculate_volatility(df)
    spread_est = 0.0005  # 5 bps default
    slip_est = min(0.005, vol * 0.5)
    fees_est = TAKER_FEE * 2  # entry + exit
    hurdle = spread_est + slip_est + fees_est
    net_edge = expected_roi - hurdle
    
    return max(0.0, hurdle), net_edge


def ensemble_confidence_score(symbol, strategy_name, df_short, df_long, regime, expected_roi):
    """
    Multi-factor confidence scoring with adaptive thresholds.
    
    Args:
        symbol: Trading symbol
        strategy_name: Strategy being evaluated
        df_short: 1-minute timeframe data
        df_long: 15-minute timeframe data
        regime: Current market regime
        expected_roi: Expected ROI from strategy
    
    Returns:
        (score, adaptive_threshold, components_dict)
    """
    # Multi-timeframe alignment
    roi_s, sig_s = calculate_ema_crossover(df_short)
    roi_l, sig_l = calculate_ema_crossover(df_long)
    mtf = 1.0 if (sig_s and sig_l) else (0.6 if (sig_s or sig_l) else 0.0)
    
    volume = compute_volume_pressure(df_short)
    momentum = compute_momentum_adx(df_short)
    regime_score = compute_regime_alignment(regime, strategy_name)
    hurdle, net_edge = estimate_cost_hurdle(df_short, expected_roi or 0.0)
    cost_hurdle = 1.0 if net_edge > 0 else 0.0
    
    w = ENSEMBLE_STATE['weights']
    score = (w['mtf']*mtf + w['volume']*volume + w['momentum']*momentum +
             w['regime']*regime_score + w['cost_hurdle']*cost_hurdle)
    
    # Learning feedback: track avg edge & adjust threshold slowly via z-score
    ENSEMBLE_STATE['rolling']['avg_edge'].append(net_edge)
    z = _zscore(net_edge, list(ENSEMBLE_STATE['rolling']['avg_edge']))
    # PAPER MODE: Lowered adaptive threshold range from (0.45-0.75) to (0.25-0.50) for more trades
    adaptive_threshold = max(0.25, min(0.50, ENSEMBLE_STATE['threshold'] - 0.03 * z))
    
    return score, adaptive_threshold, {
        "mtf": mtf, "volume": volume, "momentum": momentum,
        "regime": regime_score, "cost_hurdle": cost_hurdle,
        "hurdle": hurdle, "net_edge": net_edge
    }


def calculate_ema_crossover(df):
    """
    Enhanced EMA Crossover Strategy - LEARNING MODE (more permissive for paper trading).
    For paper trading, we want more trades to learn from outcomes.
    Returns: (ROI, signal)
    """
    df["ema_fast"] = df["close"].ewm(span=12, adjust=False).mean()
    df["ema_slow"] = df["close"].ewm(span=26, adjust=False).mean()
    df["momentum"] = df["close"].diff()
    df["volume_ma"] = df["volume"].rolling(window=10).mean()
    
    ema_bullish = df["ema_fast"].iloc[-1] > df["ema_slow"].iloc[-1]
    momentum_positive = df["momentum"].iloc[-1] > 0
    volume_strong = df["volume"].iloc[-1] > df["volume_ma"].iloc[-1] * 0.7
    
    score = sum([ema_bullish, momentum_positive, volume_strong])
    signal = score >= 1
    
    entry = df["close"].iloc[-2]
    exit = df["close"].iloc[-1]
    raw_roi = (exit - entry) / entry
    
    roi = max(min(raw_roi, 0.03), -0.015) if signal else -0.015
    
    return round(roi, 4), signal


def run_trend_conservative(df, return_metrics=False):
    """
    Trend-Conservative: EMA crossover with conservative parameters.
    Returns: (signal, roi) or (signal, roi, metrics) if return_metrics=True
    """
    roi, signal = calculate_ema_crossover(df)
    
    if not signal:
        print(f"📈 Trend-Conservative | No signal - skipping trade")
        if return_metrics:
            return False, None, None
        return False, None
    
    roi = max(roi * 0.8, -0.01)
    
    metrics = None
    if return_metrics:
        avg_vol = df["volume"].rolling(10).mean().iloc[-1] if "volume" in df.columns else 0
        volume_ratio = df["volume"].iloc[-1] / avg_vol if "volume" in df.columns and avg_vol > 0 else 1.0
        momentum = df["close"].diff().iloc[-1] if "close" in df.columns else 0
        ema_slow_val = df["ema_slow"].iloc[-1] if "ema_slow" in df.columns else 0
        ema_gap = (df["ema_fast"].iloc[-1] - ema_slow_val) / ema_slow_val if "ema_fast" in df.columns and ema_slow_val > 0 else 0
        metrics = {"volume_ratio": volume_ratio, "momentum": momentum, "ema_gap": ema_gap}
    
    print(f"📈 Trend-Conservative | Signal: BUY | ROI: {roi:.4f}")
    
    if return_metrics:
        return True, round(roi, 4), metrics
    return True, round(roi, 4)


def run_breakout_aggressive(df, return_metrics=False):
    """
    Breakout-Aggressive: EMA crossover with aggressive scaling.
    Returns: (signal, roi) or (signal, roi, metrics) if return_metrics=True
    """
    roi, signal = calculate_ema_crossover(df)
    
    if not signal:
        print(f"🚀 Breakout-Aggressive | No signal - skipping trade")
        if return_metrics:
            return False, None, None
        return False, None
    
    roi = max(roi * 1.2, -0.015)
    
    metrics = None
    if return_metrics:
        avg_vol = df["volume"].rolling(10).mean().iloc[-1] if "volume" in df.columns else 0
        volume_ratio = df["volume"].iloc[-1] / avg_vol if "volume" in df.columns and avg_vol > 0 else 1.0
        momentum = df["close"].diff().iloc[-1] if "close" in df.columns else 0
        ema_slow_val = df["ema_slow"].iloc[-1] if "ema_slow" in df.columns else 0
        ema_gap = (df["ema_fast"].iloc[-1] - ema_slow_val) / ema_slow_val if "ema_fast" in df.columns and ema_slow_val > 0 else 0
        metrics = {"volume_ratio": volume_ratio, "momentum": momentum, "ema_gap": ema_gap}
    
    print(f"🚀 Breakout-Aggressive | Signal: BUY | ROI: {roi:.4f}")
    
    if return_metrics:
        return True, round(roi, 4), metrics
    return True, round(roi, 4)


def run_sentiment_fusion(df, return_metrics=False):
    """
    Sentiment-Fusion: EMA with volume confirmation + fallback ROI logic.
    Returns: (signal, roi) or (signal, roi, metrics) if return_metrics=True
    """
    roi, signal = calculate_ema_crossover(df)
    
    if not signal:
        print(f"🧠 Sentiment-Fusion | No signal - skipping trade")
        if return_metrics:
            return False, None, None
        return False, None
    
    avg_volume = df["volume"].tail(20).mean()
    recent_volume = df["volume"].iloc[-1]
    volume_boost = 1.1 if avg_volume > 0 and recent_volume > avg_volume * 1.2 else 0.9
    volume_ratio = recent_volume / avg_volume if avg_volume > 0 else 1.0
    
    roi = roi * volume_boost
    roi = max(min(roi, 0.015), -0.01)
    
    if roi == 0.0 or abs(roi) < 0.0001:
        momentum = df["close"].diff().tail(5).mean() / df["close"].iloc[-1] if len(df) >= 5 else 0.0
        volume_pct = min(volume_ratio / 2.0, 0.01)
        fallback_roi = abs(momentum) * volume_pct * 1.5
        roi = max(fallback_roi, 0.001)
        print(f"   🔄 Fallback ROI triggered: {roi:.4f} (momentum={momentum:.4f}, vol_ratio={volume_ratio:.2f})")
    
    metrics = None
    if return_metrics:
        momentum = df["close"].diff().iloc[-1] if "close" in df.columns else 0
        ema_gap = (df["ema_fast"].iloc[-1] - df["ema_slow"].iloc[-1]) / df["ema_slow"].iloc[-1] if "ema_fast" in df.columns else 0
        metrics = {"volume_ratio": volume_ratio, "momentum": momentum, "ema_gap": ema_gap}
    
    print(f"🧠 Sentiment-Fusion | Signal: BUY | ROI: {roi:.4f} | Volume Boost: {volume_boost:.2f}")
    
    if return_metrics:
        return True, round(roi, 4), metrics
    return True, round(roi, 4)
