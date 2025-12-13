def rotate_to_stablecoin(df, place_order):
    """
    Rotate all positions to stablecoin during high volatility.
    """
    assets = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
    
    for asset in assets:
        place_order(asset, "sell", "market", 1.0)
    
    place_order("USDT", "buy", "market", 1.0)
    
    print("🛡️ Protective mode: Rotated to stablecoin")
