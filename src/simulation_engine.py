"""
Multi-asset simulation engine for backtesting adaptive learning system.
Tests how the strategy weighting system performs on historical data.
"""
import pandas as pd
import numpy as np
from datetime import datetime
import json
from pathlib import Path

from src.strategy_performance_memory import log_strategy_result
from src.neural_policy_tuner import evolve_strategy_weights, log_regime_shift

def simulate_multi_asset_learning(historical_data_map, regime_sequence_map, strategy_map):
    """
    Simulate multi-asset trading with adaptive learning.
    
    Args:
        historical_data_map: dict of {symbol: [df1, df2, ...]} - list of sequential OHLCV DataFrames
        regime_sequence_map: dict of {symbol: [regime1, regime2, ...]} - regime for each time period
        strategy_map: dict of {regime: [strategies]} - available strategies per regime
    
    Returns:
        Dict with simulation results
    """
    print("\n" + "="*60)
    print("🔬 Starting Multi-Asset Adaptive Learning Simulation")
    print("="*60)
    
    total_trades = 0
    total_roi = 0
    regime_performance = {}
    
    for symbol, data_series in historical_data_map.items():
        regime_seq = regime_sequence_map.get(symbol, ["Stable"] * len(data_series))
        
        print(f"\n📈 Simulating {symbol}: {len(data_series)} periods")
        
        for t in range(1, len(data_series)):
            df = data_series[t]
            regime = regime_seq[t]
            active_strats = strategy_map.get(regime, [])
            
            # Simulate each strategy
            for strat in active_strats:
                # Simple signal: buy if close > previous close
                signal = df["close"].iloc[-1] > df["close"].iloc[-2] if len(df) >= 2 else False
                
                # Calculate ROI
                if len(df) >= 2:
                    roi = (df["close"].iloc[-1] - df["close"].iloc[-2]) / df["close"].iloc[-2]
                else:
                    roi = 0
                
                # Log result
                log_strategy_result(strat, regime, roi, missed=not signal)
                
                if signal:
                    total_trades += 1
                    total_roi += roi
                    
                    # Track regime performance
                    if regime not in regime_performance:
                        regime_performance[regime] = {"trades": 0, "total_roi": 0}
                    regime_performance[regime]["trades"] += 1
                    regime_performance[regime]["total_roi"] += roi
            
            # Update strategy weights
            weights = evolve_strategy_weights(regime, active_strats)
            log_regime_shift(regime, weights)
    
    # Calculate final statistics
    avg_roi = (total_roi / total_trades * 100) if total_trades > 0 else 0
    
    results = {
        "total_trades": total_trades,
        "average_roi_pct": round(avg_roi, 4),
        "regime_performance": {
            regime: {
                "avg_roi_pct": round(perf["total_roi"] / perf["trades"] * 100, 4) if perf["trades"] > 0 else 0,
                "trade_count": perf["trades"]
            }
            for regime, perf in regime_performance.items()
        }
    }
    
    print(f"\n📊 Simulation Complete:")
    print(f"   Total Trades: {total_trades}")
    print(f"   Average ROI: {avg_roi:.4f}%")
    print(f"\n📈 Performance by Regime:")
    for regime, perf in results["regime_performance"].items():
        print(f"   {regime}: {perf['avg_roi_pct']:.4f}% ROI ({perf['trade_count']} trades)")
    
    return results

def create_sample_simulation():
    """
    Create a sample simulation with synthetic data for testing.
    
    Returns:
        Simulation results
    """
    print("🧪 Running sample simulation with synthetic data...")
    
    # Generate sample data
    symbols = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
    periods = 50
    
    historical_data_map = {}
    regime_sequence_map = {}
    
    for symbol in symbols:
        data_series = []
        regime_seq = []
        
        base_price = 100 if symbol == "ETHUSDT" else 1000
        
        for i in range(periods):
            # Generate random price movements
            returns = np.random.normal(0.001, 0.02, 10)  # 10 candles per period
            prices = base_price * np.cumprod(1 + returns)
            
            df = pd.DataFrame({
                "close": prices,
                "volume": np.random.uniform(1000, 10000, 10)
            })
            
            data_series.append(df)
            
            # Randomly assign regime
            regime_seq.append(np.random.choice(["Stable", "Trending", "Volatile", "Ranging"]))
            
            base_price = prices[-1]  # Update base for next period
        
        historical_data_map[symbol] = data_series
        regime_sequence_map[symbol] = regime_seq
    
    strategy_map = {
        "Stable": ["Sentiment-Fusion"],
        "Trending": ["Trend-Conservative", "Breakout-Aggressive"],
        "Volatile": ["Breakout-Aggressive", "Sentiment-Fusion"],
        "Ranging": ["Trend-Conservative", "Sentiment-Fusion"]
    }
    
    return simulate_multi_asset_learning(historical_data_map, regime_sequence_map, strategy_map)
