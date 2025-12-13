def choose_execution_mode(spread, momentum_slope, depth_proxy):
    """
    Smart order routing based on market conditions.
    
    Args:
        spread: Current bid-ask spread (as decimal, e.g., 0.0005 = 5 bps)
        momentum_slope: Recent price momentum slope (positive = uptrend)
        depth_proxy: Estimated order book depth in USD
    
    Returns:
        str: Execution mode ('maker', 'taker', or 'slice')
    
    Routing Logic:
        - 'maker': Tight spread + negative momentum = post limit order
        - 'slice': Thin order book = split large orders
        - 'taker': Default = immediate market execution
    """
    if spread < 0.0005 and momentum_slope < 0.0:
        return 'maker'
    
    if depth_proxy < 100000:
        return 'slice'
    
    return 'taker'


def estimate_spread(df):
    """
    Estimate bid-ask spread from OHLCV data.
    Uses high-low range as proxy for spread.
    
    Args:
        df: DataFrame with OHLCV data
    
    Returns:
        float: Estimated spread as decimal
    """
    if df is None or df.empty or 'high' not in df.columns or 'low' not in df.columns:
        return 0.001
    
    recent_hl = df[['high', 'low']].tail(10)
    avg_range = (recent_hl['high'] - recent_hl['low']).mean()
    avg_price = df['close'].tail(10).mean()
    
    if avg_price <= 0:
        return 0.001
    
    spread = avg_range / avg_price
    return max(spread, 0.0001)


def estimate_momentum_slope(df, window=5):
    """
    Calculate momentum slope from recent price action.
    
    Args:
        df: DataFrame with OHLCV data
        window: Lookback window for slope calculation
    
    Returns:
        float: Momentum slope (positive = uptrend, negative = downtrend)
    """
    if df is None or df.empty or 'close' not in df.columns:
        return 0.0
    
    if len(df) < window:
        return 0.0
    
    prices = df['close'].tail(window).values
    x = list(range(len(prices)))
    
    if len(prices) < 2:
        return 0.0
    
    mean_x = sum(x) / len(x)
    mean_y = sum(prices) / len(prices)
    
    numerator = sum((x[i] - mean_x) * (prices[i] - mean_y) for i in range(len(x)))
    denominator = sum((x[i] - mean_x) ** 2 for i in range(len(x)))
    
    if denominator == 0:
        return 0.0
    
    slope = numerator / denominator
    
    return slope / max(mean_y, 1.0)


def estimate_depth_proxy(df):
    """
    Estimate order book depth from volume data.
    
    Args:
        df: DataFrame with OHLCV data
    
    Returns:
        float: Estimated depth in USD (volume * price)
    """
    if df is None or df.empty or 'volume' not in df.columns or 'close' not in df.columns:
        return 100000
    
    recent_vol = df['volume'].tail(10).mean()
    recent_price = df['close'].tail(10).mean()
    
    depth = recent_vol * recent_price
    
    return depth


def get_execution_recommendation(df):
    """
    Get complete execution recommendation based on market data.
    
    Args:
        df: DataFrame with OHLCV data
    
    Returns:
        dict: {'mode': str, 'spread': float, 'momentum': float, 'depth': float}
    """
    spread = estimate_spread(df)
    momentum = estimate_momentum_slope(df)
    depth = estimate_depth_proxy(df)
    mode = choose_execution_mode(spread, momentum, depth)
    
    return {
        'mode': mode,
        'spread': spread,
        'momentum': momentum,
        'depth': depth
    }
