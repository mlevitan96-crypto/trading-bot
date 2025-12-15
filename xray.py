import json
import pandas as pd
import os

LOG_DIR = "/root/trading-bot/logs"

def inspect(filename):
    path = os.path.join(LOG_DIR, filename)
    print(f"\n--- INSPECTING: {filename} ---")
    if not os.path.exists(path):
        print("❌ File not found")
        return

    try:
        with open(path, 'r') as f:
            data = json.load(f)
        
        # Unwrap if necessary
        if isinstance(data, dict):
            keys = list(data.keys())
            print(f"ROOT KEYS: {keys}")
            # Try to find the list
            for k in ['open_positions', 'hourly_records', 'trades']:
                if k in data:
                    data = data[k]
                    break
        
        if isinstance(data, list) and len(data) > 0:
            df = pd.DataFrame(data)
            print(f"✅ Found {len(data)} records")
            print(f"COLUMNS: {list(df.columns)}")
            print(f"SAMPLE ROW: {df.iloc[-1].to_dict()}")
        else:
            print("⚠️ File loaded but seems empty or structure is unique.")
            print(f"RAW DATA SNIPPET: {str(data)[:200]}")
    except Exception as e:
        print(f"❌ Error reading file: {e}")

inspect("positions_futures.json")
inspect("pnl_hourly.json")
