import time, json, os, ccxt
from dotenv import load_dotenv

load_dotenv("/root/trading-bot/.env")
exchange = ccxt.blofin({
    'apiKey': os.getenv("BLOFIN_API_KEY"),
    'secret': os.getenv("BLOFIN_API_SECRET"),
    'password': os.getenv("BLOFIN_PASSPHRASE"),
    'options': {'defaultType': 'future'}
})

print("🚀 BloFin Reporter Running...")
while True:
    try:
        pos = exchange.fetch_positions()
        active = [p for p in pos if float(p.get('contracts',0))!=0]
        pnl = sum(float(p.get('unrealizedPnl',0)) for p in active)
        
        with open("/root/trading-bot/logs/pnl_live.json", "w") as f:
            json.dump({"floating_pnl": pnl, "timestamp": time.time()}, f)
            
        with open("/root/trading-bot/logs/positions_futures.json", "w") as f:
            json.dump({"open_positions": active, "timestamp": time.time()}, f)
            
        print(f"✅ PnL: ${pnl:.2f} | Positions: {len(active)}")
    except Exception as e:
        print(f"⚠️ Error: {e}")
    time.sleep(5)
