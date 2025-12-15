import streamlit as st
import pandas as pd
import json
import os
import requests
import time

# --- CONFIG ---
st.set_page_config(page_title="AlphaOps Pro", layout="wide", page_icon="🦅")
st.markdown("""<style>.stApp { background-color: #0e1117; }</style>""", unsafe_allow_html=True)

try:
    from streamlit_autorefresh import st_autorefresh
    st_autorefresh(interval=5000, key="data_refresh")
except:
    pass

LOG_DIR = "/root/trading-bot/logs"
POS_FILE = os.path.join(LOG_DIR, "positions_futures.json")
HIST_FILE = os.path.join(LOG_DIR, "trades_futures.json")

def load_data(path):
    if not os.path.exists(path): return []
    try:
        with open(path, 'r') as f:
            data = json.load(f)
            if isinstance(data, list): return data
            if isinstance(data, dict):
                return data.get("trades", []) or data.get("open_positions", []) or []
            return []
    except: return []

def get_kraken_prices(symbols):
    if not symbols: return {}
    pairs = [s.replace("BTC","XBT").replace("-","").replace("_","")+"USDT" for s in symbols]
    try:
        url = f"https://api.kraken.com/0/public/Ticker?pair={','.join(pairs)}"
        r = requests.get(url, timeout=1).json()
        return {k: float(v['c'][0]) for k,v in r['result'].items()}
    except: return {}

# --- LOAD DATA ---
open_trades = load_data(POS_FILE)
closed_trades = load_data(HIST_FILE)

df_open = pd.DataFrame(open_trades)
df_closed = pd.DataFrame(closed_trades)

# --- METRICS ---
STARTING_BALANCE = 10000.0
realized_pnl = 0.0
if not df_closed.empty and 'net_pnl' in df_closed.columns:
    realized_pnl = df_closed['net_pnl'].sum()

floating_pnl = 0.0
if not df_open.empty:
    symbols = df_open['symbol'].unique().tolist() if 'symbol' in df_open.columns else []
    prices = get_kraken_prices(symbols)
    
    for i, row in df_open.iterrows():
        entry = float(row.get('entry_price', 0))
        size = float(row.get('size', 0))
        sym = row.get('symbol', '')
        current = entry
        for k, v in prices.items():
            if sym.replace("-","") in k or sym.replace("BTC","XBT") in k:
                current = v
                break
        
        if entry > 0:
            pnl = ((current - entry) / entry) * size * entry # Simple USD PnL approx
            if row.get('side', 'LONG').upper() == 'SHORT': pnl *= -1
            floating_pnl += pnl
            df_open.at[i, 'current_price'] = current
            df_open.at[i, 'pnl_usd'] = pnl

# --- DISPLAY ---
st.title("🦅 AlphaOps Pro")
c1, c2, c3, c4 = st.columns(4)
c1.metric("💰 Wallet Balance", f"${STARTING_BALANCE + realized_pnl:,.2f}")
c2.metric("🌊 Floating PnL", f"${floating_pnl:,.2f}")
c3.metric("🏦 Realized Profit", f"${realized_pnl:,.2f}")
c4.metric("📊 Total Trades", len(df_closed))

st.markdown("---")

# 1. Active Trades (The Fix is Here)
st.subheader("📡 Active Trades")
if not df_open.empty:
    cols = ['symbol', 'side', 'entry_price', 'current_price', 'size', 'pnl_usd']
    valid_cols = [c for c in cols if c in df_open.columns]
    
    # SMART FORMATTING: Only format specific numeric columns
    format_dict = {
        'entry_price': '{:.4f}',
        'current_price': '{:.4f}',
        'size': '{:.4f}',
        'pnl_usd': '{:.2f}'
    }
    # Only apply formats to columns that actually exist
    final_formats = {k: v for k, v in format_dict.items() if k in valid_cols}
    
    st.dataframe(df_open[valid_cols].style.format(final_formats), use_container_width=True)
else:
    st.info("No active trades currently open.")

# 2. History
st.subheader("📜 Trade History")
if not df_closed.empty:
    if 'exit_time' in df_closed.columns:
        df_closed['exit_time'] = pd.to_datetime(df_closed['exit_time'])
        df_closed = df_closed.sort_values('exit_time', ascending=False)
        
    cols = ['symbol', 'side', 'entry_price', 'exit_price', 'net_pnl', 'exit_time']
    valid_cols = [c for c in cols if c in df_closed.columns]
    
    st.dataframe(
        df_closed[valid_cols].head(50).style.format({
            'entry_price': '{:.4f}', 'exit_price': '{:.4f}', 'net_pnl': '${:.2f}'
        }), 
        use_container_width=True
    )
