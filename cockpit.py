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

# Add tabs
tab1, tab2, tab3 = st.tabs(["📊 Trading", "🔮 Analytics", "📈 Performance"])

with tab1:
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("💰 Wallet Balance", f"${STARTING_BALANCE + realized_pnl:,.2f}")
    c2.metric("🌊 Floating PnL", f"${floating_pnl:,.2f}")
    c3.metric("🏦 Realized Profit", f"${realized_pnl:,.2f}")
    c4.metric("📊 Total Trades", len(df_closed))
    
    st.markdown("---")
    
    # 1. Active Trades
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
    else:
        st.info("No trade history yet.")

with tab2:
    st.header("🔮 Analytics & Learning")
    st.markdown("Real-time insights from Shadow Execution Engine and Decision Tracker")
    
    # [BIG ALPHA] Whale Intensity and Hurst Regime Indicators (Component 7)
    st.subheader("🐋 Whale Intensity & Regime Indicators")
    try:
        symbol_selector = st.selectbox("Select Symbol", ["BTCUSDT", "ETHUSDT", "SOLUSDT", "AVAXUSDT", "DOTUSDT"], index=0)
        
        # Get Whale Intensity
        whale_intensity = 0.0
        whale_direction = "NEUTRAL"
        try:
            from src.whale_cvd_engine import get_whale_cvd
            whale_cvd_data = get_whale_cvd(symbol_selector)
            whale_intensity = whale_cvd_data.get("whale_intensity", 0.0)
            whale_direction = whale_cvd_data.get("cvd_direction", "NEUTRAL")
        except Exception as e:
            st.warning(f"Whale CVD unavailable: {e}")
        
        # Get Hurst Regime
        hurst_regime = "unknown"
        hurst_value = 0.5
        is_true_trend = False
        try:
            from src.hurst_exponent import get_hurst_signal
            hurst_signal = get_hurst_signal(symbol_selector)
            hurst_regime = hurst_signal.get("regime", "unknown")
            hurst_value = hurst_signal.get("hurst_value", 0.5)
            is_true_trend = (hurst_regime == "trending" and hurst_value > 0.55)
        except Exception as e:
            st.warning(f"Hurst signal unavailable: {e}")
        
        col1, col2, col3, col4 = st.columns(4)
        col1.metric("🐋 Whale Intensity", f"{whale_intensity:.1f}", f"{whale_direction}")
        col2.metric("📈 Hurst Value", f"{hurst_value:.3f}", "TRUE TREND" if is_true_trend else "")
        col3.metric("🔄 Regime", hurst_regime.upper(), "FORCE-HOLD" if is_true_trend else "")
        col4.metric("🎯 Status", "TRUE TREND" if is_true_trend else "NORMAL", "45min hold" if is_true_trend else "")
        
        st.markdown("---")
        
        # [BIG ALPHA PHASE 2] Liquidation Wall Proximity and OI Velocity
        st.subheader("🏛️ Macro Institutional Guards")
        try:
            # Get current price
            current_price = 0.0
            try:
                from src.exchange_gateway import ExchangeGateway
                gateway = ExchangeGateway()
                current_price = gateway.get_price(symbol_selector, venue="futures")
            except:
                pass
            
            # Liquidation Wall Proximity
            has_nearby_short_liq = False
            liq_distance_pct = 999.0
            try:
                from src.macro_institutional_guards import get_liquidation_heatmap
                if current_price > 0:
                    heatmap = get_liquidation_heatmap(symbol_selector, current_price)
                    has_nearby_short_liq = heatmap.get("has_nearby_short_liq", False)
                    nearby_short = heatmap.get("short_liq_clusters_nearby", [])
                    if nearby_short:
                        liq_distance_pct = min(c.get("distance_pct", 999) for c in nearby_short)
            except Exception as e:
                st.warning(f"Liquidation heatmap unavailable: {e}")
            
            # OI Velocity
            oi_delta_5m = 0.0
            oi_positive = False
            try:
                from src.macro_institutional_guards import get_oi_velocity
                oi_data = get_oi_velocity(symbol_selector)
                oi_delta_5m = oi_data.get("oi_delta_5m", 0.0)
                oi_positive = oi_data.get("is_positive", False)
            except Exception as e:
                st.warning(f"OI velocity unavailable: {e}")
            
            col1, col2 = st.columns(2)
            with col1:
                liq_status = "⚠️ NEARBY" if has_nearby_short_liq else "✅ CLEAR"
                liq_delta = f"{liq_distance_pct:.3f}%" if liq_distance_pct < 999 else "N/A"
                st.metric("🏛️ Liquidation Wall", liq_status, f"Distance: {liq_delta}")
            
            with col2:
                oi_status = "📈 POSITIVE" if oi_positive else "📉 NEGATIVE"
                oi_delta_display = f"${oi_delta_5m:,.0f}" if oi_delta_5m != 0 else "N/A"
                st.metric("💹 OI Velocity (5m)", oi_status, f"Δ: {oi_delta_display}")
            
        except Exception as e:
            st.warning(f"Macro guard indicators unavailable: {e}")
        
        st.markdown("---")
    except Exception as e:
        st.warning(f"Indicator loading error: {e}")
    
    # Signal Pipeline Health
    st.subheader("📊 Signal Pipeline Health")
    try:
        from src.signal_pipeline_monitor import get_pipeline_monitor
        monitor = get_pipeline_monitor()
        health = monitor.get_pipeline_health()
        
        col1, col2, col3, col4 = st.columns(4)
        col1.metric("Total Signals", health.get("total_signals", 0))
        col2.metric("Stuck Signals", health.get("stuck_count", 0))
        col3.metric("Status", health.get("status", "UNKNOWN"))
        col4.metric("Signals/Hour", health.get("throughput", {}).get("signals_per_hour", 0))
        
        # Signals by State
        st.write("**Signals by State:**")
        state_counts = health.get("state_counts", {})
        if state_counts:
            state_data = [{"State": k, "Count": v} for k, v in state_counts.items()]
            df_states = pd.DataFrame(state_data)
            st.dataframe(df_states, use_container_width=True)
        
        # Stuck Signals
        stuck = health.get("stuck_signals", [])
        if stuck:
            st.warning(f"⚠️ {len(stuck)} stuck signals detected!")
            stuck_data = [{"Signal ID": s["signal_id"][:20] + "...", "State": s["state"], "Stuck For": f"{s['stuck_for_hours']:.1f}h", "Symbol": s["symbol"]} for s in stuck[:10]]
            df_stuck = pd.DataFrame(stuck_data)
            st.dataframe(df_stuck, use_container_width=True)
        
        st.markdown("---")
    except Exception as e:
        st.warning(f"Pipeline monitoring unavailable: {e}")
    
    # Time period selector
    hours = st.selectbox("Time Period", [1, 6, 12, 24, 48, 168], index=3, help="Hours to analyze")
    
    try:
        from src.analytics.report_generator import generate_report
        
        with st.spinner("Generating analytics report..."):
            report = generate_report(hours=hours)
        
        # Blocked Opportunity Cost
        st.subheader("💰 Blocked Opportunity Cost")
        blocked = report.get("blocked_opportunity_cost", {})
        
        col1, col2, col3, col4 = st.columns(4)
        col1.metric("Total Blocked", blocked.get("total_blocked", 0))
        col2.metric("Would Win", blocked.get("profitable_blocked", 0))
        col3.metric("Would Lose", blocked.get("losing_blocked", 0))
        col4.metric("Net Cost", f"${blocked.get('net_opportunity_cost', 0):,.2f}")
        
        st.markdown("---")
        
        # Detailed breakdown
        if blocked.get("by_blocker"):
            st.write("**By Blocker Component:**")
            blocker_data = []
            for blocker, stats in blocked["by_blocker"].items():
                blocker_data.append({
                    "Blocker": blocker,
                    "Blocked": stats.get("count", 0),
                    "Missed Profit": f"${stats.get('missed_profit', 0):,.2f}",
                    "Avoided Loss": f"${stats.get('avoided_loss', 0):,.2f}",
                    "Net": f"${stats.get('missed_profit', 0) - stats.get('avoided_loss', 0):,.2f}"
                })
            
            if blocker_data:
                df_blockers = pd.DataFrame(blocker_data)
                st.dataframe(df_blockers, use_container_width=True)
        
        st.markdown("---")
        
        # Guard Effectiveness
        st.subheader("🛡️ Guard Effectiveness")
        guards = report.get("guard_effectiveness", {})
        
        if guards:
            guard_data = []
            for guard, stats in guards.items():
                net = stats.get("missed_profit", 0) - stats.get("avoided_loss", 0)
                guard_data.append({
                    "Guard": guard,
                    "Blocked": stats.get("blocked_count", 0),
                    "Would Win": stats.get("would_win", 0),
                    "Would Lose": stats.get("would_lose", 0),
                    "Missed Profit": f"${stats.get('missed_profit', 0):,.2f}",
                    "Avoided Loss": f"${stats.get('avoided_loss', 0):,.2f}",
                    "Net Impact": f"${net:,.2f}",
                    "Status": "✅ Effective" if net < 0 else "⚠️ Review"
                })
            
            if guard_data:
                df_guards = pd.DataFrame(guard_data)
                st.dataframe(df_guards, use_container_width=True)
        
        st.markdown("---")
        
        # Strategy Leaderboard
        st.subheader("🏆 Strategy Leaderboard")
        strategies = report.get("strategy_leaderboard", {})
        
        if strategies:
            strategy_data = []
            for strategy, stats in sorted(strategies.items(), key=lambda x: x[1].get("total_pnl", 0), reverse=True):
                strategy_data.append({
                    "Strategy": strategy,
                    "Trades": stats.get("trades", 0),
                    "Win Rate": f"{stats.get('win_rate', 0)*100:.1f}%",
                    "Total P&L": f"${stats.get('total_pnl', 0):,.2f}",
                    "Avg P&L %": f"{stats.get('avg_pnl_pct', 0)*100:.2f}%"
                })
            
            if strategy_data:
                df_strategies = pd.DataFrame(strategy_data)
                st.dataframe(df_strategies, use_container_width=True)
        
        st.markdown("---")
        
        # Signal Decay
        st.subheader("⏱️ Signal Decay")
        decay = report.get("signal_decay", {})
        
        col1, col2, col3 = st.columns(3)
        col1.metric("Total Signals", decay.get("total_signals", 0))
        col2.metric("Avg Decay", f"{decay.get('avg_decay_seconds', 0)/60:.1f} min")
        col3.metric("Median Decay", f"{decay.get('median_decay_seconds', 0)/60:.1f} min")
        
    except Exception as e:
        st.error(f"Error generating analytics report: {e}")
        st.info("Make sure Shadow Execution Engine is running and has collected data.")

with tab3:
    st.header("📈 Performance Metrics")
    st.info("Performance metrics coming soon...")
