def apply_slippage(price, volatility):
    """
    Simulate realistic slippage based on market volatility with tick-size-aware rounding.
    
    Args:
        price: Execution price
        volatility: Market volatility (std dev of returns)
    
    Returns:
        Adjusted price after slippage with appropriate decimal precision
    """
    slippage_pct = min(volatility * 0.5, 0.005)
    slipped_price = price * (1 + slippage_pct)
    
    # Use price-band heuristics for realistic tick sizes
    # Prevents rounding artifacts that cause phantom losses on low-priced assets
    if price <= 1.0:
        # Sub-dollar assets (e.g., TRXUSDT $0.07) - use 4 decimal places
        return round(slipped_price, 4)
    elif price <= 100:
        # Mid-price assets (e.g., ETHUSDT $3000) - use 2 decimal places
        return round(slipped_price, 2)
    else:
        # High-price assets (e.g., BTCUSDT $80000) - use 1 decimal place
        return round(slipped_price, 1)


def calculate_volatility(df):
    """
    Calculate recent price volatility.
    
    Args:
        df: DataFrame with 'close' prices
    
    Returns:
        Volatility as standard deviation of returns
    """
    returns = df["close"].pct_change().dropna()
    volatility = returns.std()
    return volatility
