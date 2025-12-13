"""
Regime-based strategy attribution backtesting.
"""
import pandas as pd

def backtest_strategy_attribution(regime, strategy, historical_df):
    """
    Backtest a strategy against historical data for a specific regime.
    
    Args:
        regime: Market regime (Trending, Volatile, Stable, Ranging)
        strategy: Strategy name
        historical_df: DataFrame with OHLCV data
    
    Returns:
        Dict with backtest results
    """
    if len(historical_df) < 30:
        return {"error": "Insufficient data for backtest"}
    
    df = historical_df.copy()
    
    # Calculate indicators
    df["ema_fast"] = df["close"].ewm(span=12, adjust=False).mean()
    df["ema_slow"] = df["close"].ewm(span=26, adjust=False).mean()
    df["momentum"] = df["close"].diff()
    df["volume_ma"] = df["volume"].rolling(window=10).mean()
    
    # Generate signals based on enhanced criteria
    signals = (
        (df["ema_fast"] > df["ema_slow"]) &
        (df["momentum"] > 0) &
        (df["volume"] > df["volume_ma"])
    )
    
    # Calculate forward returns
    df["forward_return"] = df["close"].shift(-1) / df["close"] - 1
    
    # Filter to signals only
    signal_returns = df[signals]["forward_return"].dropna()
    
    if len(signal_returns) == 0:
        return {
            "regime": regime,
            "strategy": strategy,
            "signals": 0,
            "avg_roi": 0,
            "win_rate": 0,
            "total_return": 0
        }
    
    avg_roi = signal_returns.mean()
    win_rate = (signal_returns > 0).sum() / len(signal_returns)
    total_return = signal_returns.sum()
    
    print(f"📊 Backtest | Regime: {regime} | Strategy: {strategy} | Signals: {len(signal_returns)} | Avg ROI: {round(avg_roi, 4)} | Win Rate: {round(win_rate*100, 1)}%")
    
    return {
        "regime": regime,
        "strategy": strategy,
        "signals": len(signal_returns),
        "avg_roi": round(avg_roi, 6),
        "win_rate": round(win_rate, 4),
        "total_return": round(total_return, 6),
        "best_return": round(signal_returns.max(), 6),
        "worst_return": round(signal_returns.min(), 6)
    }

def run_regime_backtest(regime, historical_data_dict):
    """
    Run backtest across all assets for a regime.
    
    Args:
        regime: Market regime
        historical_data_dict: Dict of {symbol: DataFrame}
    
    Returns:
        List of backtest results
    """
    results = []
    
    for symbol, df in historical_data_dict.items():
        result = backtest_strategy_attribution(regime, "Enhanced-EMA", df)
        result["symbol"] = symbol
        results.append(result)
    
    return results
