import json
from datetime import datetime
import numpy as np


max_drawdown = 0.0
peak_value = 10000.0


def track_performance(current_portfolio_value):
    """
    Track maximum drawdown and peak portfolio value.
    """
    global max_drawdown, peak_value
    
    peak_value = max(peak_value, current_portfolio_value)
    
    if peak_value > 0:
        drawdown = (peak_value - current_portfolio_value) / peak_value
        max_drawdown = max(max_drawdown, drawdown)
    
    print(f"💰 Portfolio Value: ${current_portfolio_value:.2f} | Peak: ${peak_value:.2f} | Max Drawdown: {max_drawdown:.2%}")
    
    log_file = "logs/performance.json"
    try:
        with open(log_file, "r") as f:
            logs = json.load(f)
            if not isinstance(logs, list):
                logs = []
    except (FileNotFoundError, json.JSONDecodeError):
        logs = []
    
    logs.append({
        "timestamp": datetime.utcnow().isoformat(),
        "portfolio_value": round(current_portfolio_value, 2),
        "peak_value": round(peak_value, 2),
        "max_drawdown": round(max_drawdown, 4)
    })
    
    with open(log_file, "w") as f:
        json.dump(logs[-500:], f, indent=2)
    
    return {
        "portfolio_value": current_portfolio_value,
        "peak_value": peak_value,
        "max_drawdown": max_drawdown
    }


def calculate_sharpe_ratio(returns, risk_free_rate=0.0):
    """
    Calculate Sharpe ratio from a list of returns.
    
    Args:
        returns: List or array of periodic returns (ROI values)
        risk_free_rate: Risk-free rate (default 0.0)
    
    Returns:
        float: Sharpe ratio (higher is better)
    """
    if not returns or len(returns) == 0:
        return 0.0
    
    excess_returns = np.array(returns) - risk_free_rate
    mean_excess = np.mean(excess_returns)
    std_dev = np.std(excess_returns)
    
    if std_dev == 0:
        return 0.0
    
    return mean_excess / std_dev


def calculate_sortino_ratio(returns, risk_free_rate=0.0):
    """
    Calculate Sortino ratio from a list of returns.
    Sortino focuses only on downside volatility (negative returns).
    
    Args:
        returns: List or array of periodic returns (ROI values)
        risk_free_rate: Risk-free rate (default 0.0)
    
    Returns:
        float: Sortino ratio (higher is better)
    """
    if not returns or len(returns) == 0:
        return 0.0
    
    excess_returns = np.array(returns) - risk_free_rate
    mean_excess = np.mean(excess_returns)
    downside_returns = excess_returns[excess_returns < 0]
    downside_std = np.std(downside_returns) if len(downside_returns) > 0 else 0.0
    
    if downside_std == 0:
        return 0.0
    
    return mean_excess / downside_std


def track_risk_adjusted_performance(trades):
    """
    Calculate and log risk-adjusted performance metrics.
    
    Args:
        trades: List of trade dicts with 'roi' field
    
    Returns:
        dict: {"sharpe": float, "sortino": float}
    """
    # Extract ROI values from trades
    returns = [t.get('roi', 0) for t in trades if t.get('roi') is not None]
    
    if len(returns) < 2:
        print(f"📈 Risk-Adjusted Metrics: Insufficient data ({len(returns)} trades)")
        return {"sharpe": 0.0, "sortino": 0.0}
    
    sharpe = calculate_sharpe_ratio(returns)
    sortino = calculate_sortino_ratio(returns)
    
    print(f"📈 Sharpe Ratio: {sharpe:.3f} | Sortino Ratio: {sortino:.3f}")
    
    # Append new risk metric entry to separate log file
    risk_log_file = "logs/risk_metrics.json"
    try:
        with open(risk_log_file, "r") as f:
            risk_logs = json.load(f)
            if not isinstance(risk_logs, list):
                risk_logs = []
    except (FileNotFoundError, json.JSONDecodeError):
        risk_logs = []
    
    # Append new entry with timestamp
    risk_logs.append({
        "timestamp": datetime.utcnow().isoformat(),
        "sharpe_ratio": round(sharpe, 3),
        "sortino_ratio": round(sortino, 3),
        "total_trades": len(returns),
        "avg_return": round(np.mean(returns), 4)
    })
    
    # Keep last 500 entries
    with open(risk_log_file, "w") as f:
        json.dump(risk_logs[-500:], f, indent=2)
    
    return {"sharpe": sharpe, "sortino": sortino}
