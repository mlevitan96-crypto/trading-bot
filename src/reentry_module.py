from src.volatility_monitor import detect_volatility_spike
from src.position_manager import open_futures_position


def get_real_price(symbol: str) -> float:
    """Get real market price from BloFin futures client."""
    try:
        from src.blofin_futures_client import BlofinFuturesClient
        client = BlofinFuturesClient()
        blofin_symbol = symbol.replace("USDT", "-USDT")
        price = client.get_mark_price(blofin_symbol)
        if isinstance(price, (int, float)) and price > 0:
            return float(price)
    except Exception as e:
        print(f"  ⚠️ BloFin price fetch failed for {symbol}: {e}")
    
    try:
        from src.market_data import get_latest_price
        price = get_latest_price(symbol)
        if price and price > 0:
            return float(price)
    except Exception as e:
        print(f"  ⚠️ Market data price fetch failed for {symbol}: {e}")
    
    return 0.0


def reenter_market(df, place_order):
    """
    Re-enter market when volatility normalizes.
    Returns dict with reentry status.
    """
    status = detect_volatility_spike(df)
    
    if status["action"] == "normal":
        assets = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
        positions_opened = []
        
        for asset in assets:
            entry_price = get_real_price(asset)
            
            if entry_price <= 0:
                print(f"  ⚠️ Skipping {asset}: Could not get valid market price")
                continue
            
            order_result = place_order(asset, "buy", "market", 1.0)
            
            if order_result:
                try:
                    position = open_futures_position(
                        symbol=asset,
                        direction="LONG",
                        entry_price=entry_price,
                        size=200.0,
                        leverage=5,
                        strategy="Reentry-Module",
                        signal_context={"trigger": "volatility_normalized", "module": "reentry"}
                    )
                    if position:
                        positions_opened.append(asset)
                        print(f"  ✅ Opened position: {asset} LONG @ ${entry_price:.2f}")
                except Exception as e:
                    print(f"  ⚠️ Failed to record position for {asset}: {e}")
        
        print(f"✅ Market re-entry: Conditions normalized ({len(positions_opened)} positions opened)")
        return {"reentry": True, "positions": positions_opened}
    
    return {"reentry": False}
