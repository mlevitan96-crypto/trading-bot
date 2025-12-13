"""
Multi-timeframe signal confirmation system.
Confirms trading signals across multiple timeframes for higher quality trades.
"""
from src.strategy_runner import run_trend_conservative, run_breakout_aggressive, run_sentiment_fusion


def confirm_signal_multi_timeframe(symbol, strategy_name, client):
    """
    Confirm trading signal across both 1m (short-term) and 15m (medium-term) timeframes.
    
    Args:
        symbol: Trading pair (e.g., 'BTCUSDT')
        strategy_name: Strategy to run ('Trend-Conservative', 'Breakout-Aggressive', 'Sentiment-Fusion')
        client: BlofinClient instance for fetching market data
    
    Returns:
        Tuple (confirmed, avg_roi, signal_data_short) where:
        - confirmed: True if both timeframes agree
        - avg_roi: Average ROI across both timeframes
        - signal_data_short: Signal data from short timeframe (for logging)
    """
    try:
        df_short = client.fetch_ohlcv(symbol, timeframe="1m", limit=100)
        df_long = client.fetch_ohlcv(symbol, timeframe="15m", limit=100)
        
        if strategy_name == "Trend-Conservative":
            result_short = run_trend_conservative(df_short, return_metrics=True)
            result_long = run_trend_conservative(df_long, return_metrics=True)
        elif strategy_name == "Breakout-Aggressive":
            result_short = run_breakout_aggressive(df_short, return_metrics=True)
            result_long = run_breakout_aggressive(df_long, return_metrics=True)
        elif strategy_name == "Sentiment-Fusion":
            result_short = run_sentiment_fusion(df_short, return_metrics=True)
            result_long = run_sentiment_fusion(df_long, return_metrics=True)
        else:
            return False, None, None
        
        signal_short, roi_short, signal_data_short = result_short if len(result_short) == 3 else (result_short[0], result_short[1], None)
        signal_long, roi_long, signal_data_long = result_long if len(result_long) == 3 else (result_long[0], result_long[1], None)
        
        print(f"   🔍 MTF Check {symbol}-{strategy_name}: 1m={signal_short} ROI={roi_short} | 15m={signal_long} ROI={roi_long}")
        
        if signal_short and signal_long and roi_short is not None and roi_long is not None:
            avg_roi = (roi_short + roi_long) / 2
            print(f"   ✅ Multi-timeframe confirmed: 1m ROI={roi_short*100:.2f}% | 15m ROI={roi_long*100:.2f}% | Avg={avg_roi*100:.2f}%")
            return True, avg_roi, signal_data_short
        elif signal_short and roi_short is not None:
            print(f"   🟡 Partial confirmation: 1m signal (ROI={roi_short*100:.2f}%) but 15m disagrees")
            return 'partial', roi_short, signal_data_short
        elif signal_long and roi_long is not None:
            print(f"   🟡 Partial confirmation: 15m signal (ROI={roi_long*100:.2f}%) but 1m disagrees")
            return 'partial', roi_long, signal_data_long
        else:
            return False, None, None
            
    except Exception as e:
        print(f"⚠️ Multi-timeframe confirmation error for {symbol}: {e}")
        return False, None, None


def get_mtf_confidence_score(symbol, strategy_name, client, alpha_side="LONG"):
    """
    Get a graded confidence score from MTF analysis to use as quality modifier.
    
    This function returns a confidence score even when MTF doesn't fully confirm,
    allowing Alpha/OFI signals to proceed with adjusted sizing.
    
    Args:
        symbol: Trading pair
        strategy_name: Strategy to evaluate
        client: BlofinClient instance
        alpha_side: The side suggested by Alpha/OFI ("LONG" or "SHORT")
    
    Returns:
        Tuple (confidence_score, mtf_data) where:
        - confidence_score: 0.0 to 1.0 (1.0 = full confirmation, 0.0 = complete disagreement)
        - mtf_data: Dictionary with detailed metrics
    """
    try:
        df_short = client.fetch_ohlcv(symbol, timeframe="1m", limit=100)
        df_long = client.fetch_ohlcv(symbol, timeframe="15m", limit=100)
        
        if df_short is None or len(df_short) < 30 or df_long is None or len(df_long) < 30:
            return 0.5, {"reason": "insufficient_data"}
        
        df_short["ema_fast"] = df_short["close"].ewm(span=12, adjust=False).mean()
        df_short["ema_slow"] = df_short["close"].ewm(span=26, adjust=False).mean()
        df_long["ema_fast"] = df_long["close"].ewm(span=12, adjust=False).mean()
        df_long["ema_slow"] = df_long["close"].ewm(span=26, adjust=False).mean()
        
        ema_gap_short = (df_short["ema_fast"].iloc[-1] - df_short["ema_slow"].iloc[-1]) / df_short["ema_slow"].iloc[-1]
        ema_gap_long = (df_long["ema_fast"].iloc[-1] - df_long["ema_slow"].iloc[-1]) / df_long["ema_slow"].iloc[-1]
        
        ema_direction_short = "LONG" if ema_gap_short > 0 else "SHORT"
        ema_direction_long = "LONG" if ema_gap_long > 0 else "SHORT"
        
        momentum_short = df_short["close"].diff().iloc[-1]
        momentum_long = df_long["close"].diff().iloc[-1]
        momentum_dir_short = "LONG" if momentum_short > 0 else "SHORT"
        momentum_dir_long = "LONG" if momentum_long > 0 else "SHORT"
        
        volume_ratio_short = df_short["volume"].iloc[-1] / df_short["volume"].rolling(10).mean().iloc[-1] if df_short["volume"].rolling(10).mean().iloc[-1] > 0 else 1.0
        volume_ratio_long = df_long["volume"].iloc[-1] / df_long["volume"].rolling(10).mean().iloc[-1] if df_long["volume"].rolling(10).mean().iloc[-1] > 0 else 1.0
        
        score = 0.0
        
        if ema_direction_short == alpha_side:
            score += 0.20
        if ema_direction_long == alpha_side:
            score += 0.25
        
        if momentum_dir_short == alpha_side:
            score += 0.15
        if momentum_dir_long == alpha_side:
            score += 0.15
        
        if volume_ratio_short > 1.0:
            score += 0.10
        if volume_ratio_long > 1.0:
            score += 0.10
        
        score += min(abs(ema_gap_short) * 10, 0.05)
        
        score = min(score, 1.0)
        
        mtf_data = {
            "ema_gap_1m": ema_gap_short,
            "ema_gap_15m": ema_gap_long,
            "ema_dir_1m": ema_direction_short,
            "ema_dir_15m": ema_direction_long,
            "momentum_1m": momentum_short,
            "momentum_15m": momentum_long,
            "volume_ratio_1m": volume_ratio_short,
            "volume_ratio_15m": volume_ratio_long,
            "alpha_side": alpha_side,
            "alignment_score": score
        }
        
        print(f"   📊 MTF Confidence {symbol}: Score={score:.2f} | EMA 1m={ema_direction_short} 15m={ema_direction_long} | Alpha={alpha_side}")
        
        return score, mtf_data
        
    except Exception as e:
        print(f"⚠️ MTF confidence error for {symbol}: {e}")
        return 0.5, {"error": str(e)}


def should_trade_multi_timeframe(symbol, strategy_name, client, roi_threshold=0.0005):
    """
    Simplified multi-timeframe check with built-in ROI threshold.
    Allows partial confirmation with near-miss ROI.
    
    Args:
        symbol: Trading pair
        strategy_name: Strategy to run
        client: BlofinClient instance
        roi_threshold: Minimum ROI threshold (default 0.3%)
    
    Returns:
        Tuple (should_trade, avg_roi, signal_data)
    """
    confirmed, avg_roi, signal_data = confirm_signal_multi_timeframe(symbol, strategy_name, client)
    
    if confirmed == False or avg_roi is None:
        return False, None, None
    
    near_miss_threshold = roi_threshold * 0.5
    
    if confirmed == True and avg_roi >= roi_threshold:
        return True, avg_roi, signal_data
    elif confirmed == 'partial' and avg_roi >= roi_threshold:
        print(f"   🟢 Accepting partial confirmation with ROI {avg_roi*100:.2f}% >= {roi_threshold*100:.1f}%")
        return True, avg_roi, signal_data
    elif avg_roi >= near_miss_threshold:
        print(f"   🟡 Near-miss ROI: {avg_roi*100:.2f}% (threshold={roi_threshold*100:.1f}%, near-miss={near_miss_threshold*100:.1f}%)")
        return 'near_miss', avg_roi, signal_data
    else:
        print(f"   ⏸️  ROI {avg_roi*100:.2f}% below minimum threshold {near_miss_threshold*100:.1f}%")
        return False, avg_roi, signal_data
