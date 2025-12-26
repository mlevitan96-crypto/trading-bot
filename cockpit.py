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
tab1, tab2, tab3, tab4 = st.tabs(["📊 Trading", "🔮 Analytics", "📈 Performance", "⏰ 24/7 Trading"])

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
        
        # [BIG ALPHA PHASE 3] Institutional Precision Guards
        st.subheader("🎯 Institutional Precision (Magnet Targets)")
        try:
            # Get current price (reuse from above)
            if current_price <= 0:
                try:
                    from src.exchange_gateway import ExchangeGateway
                    gateway = ExchangeGateway()
                    current_price = gateway.get_price(symbol_selector, venue="futures")
                except:
                    pass
            
            # Option Max Pain
            max_pain_price = 0.0
            max_pain_gap_pct = 0.0
            try:
                from src.institutional_precision_guards import get_max_pain_price, check_price_distance_from_max_pain
                max_pain_price = get_max_pain_price(symbol_selector)
                if max_pain_price > 0 and current_price > 0:
                    distance_pct, is_far = check_price_distance_from_max_pain(current_price, max_pain_price)
                    max_pain_gap_pct = distance_pct
            except Exception as e:
                st.warning(f"Max Pain unavailable: {e}")
            
            # Orderbook Walls
            ask_walls_info = []
            try:
                from src.institutional_precision_guards import get_orderbook_walls
                if current_price > 0:
                    walls_data = get_orderbook_walls(symbol_selector, current_price)
                    ask_walls = walls_data.get("ask_walls", [])
                    institutional_walls = walls_data.get("institutional_ask_walls", [])
                    
                    for wall in ask_walls[:3]:  # Top 3
                        ask_walls_info.append({
                            "price": wall.get("price", 0),
                            "size_usd_m": wall.get("size_usd", 0) / 1e6,
                            "distance_pct": wall.get("distance_pct", 0),
                            "institutional": wall.get("size_usd", 0) > 25000000
                        })
            except Exception as e:
                st.warning(f"Orderbook walls unavailable: {e}")
            
            col1, col2 = st.columns(2)
            with col1:
                max_pain_status = f"${max_pain_price:.2f}" if max_pain_price > 0 else "N/A"
                gap_display = f"{max_pain_gap_pct:.2f}%" if max_pain_gap_pct > 0 else "N/A"
                st.metric("📌 Option Max Pain", max_pain_status, f"Gap: {gap_display}")
                if max_pain_price > 0:
                    st.caption("🎯 Magnet Target: Price tends to move toward Max Pain")
            
            with col2:
                if ask_walls_info:
                    wall_count = len([w for w in ask_walls_info if w.get("institutional")])
                    st.metric("🏛️ Ask Walls", f"{len(ask_walls_info)} detected", f"{wall_count} Institutional (>$25M)" if wall_count > 0 else "")
                    # Show top wall
                    if ask_walls_info:
                        top_wall = ask_walls_info[0]
                        st.caption(f"Top: ${top_wall['price']:.2f} (${top_wall['size_usd_m']:.1f}M, {top_wall['distance_pct']:.2f}% away)")
                else:
                    st.metric("🏛️ Ask Walls", "N/A", "No data")
            
            # Magnet Target Visualization
            if max_pain_price > 0 and current_price > 0:
                st.markdown("**🎯 Magnet Target Visualization:**")
                gap_direction = "ABOVE" if current_price > max_pain_price else "BELOW"
                st.info(f"Current: ${current_price:.2f} | Max Pain: ${max_pain_price:.2f} | Gap: {gap_direction} {max_pain_gap_pct:.2f}%")
            
            # [BIG ALPHA PHASE 4] Liquidation Magnet Distance
            liq_magnet_distance = "N/A"
            liq_cluster_direction = "N/A"
            try:
                from src.intent_intelligence_guards import get_liquidation_heatmap_clusters
                if current_price > 0:
                    clusters_data = get_liquidation_heatmap_clusters(symbol_selector, current_price, limit=2)
                    top_clusters = clusters_data.get("top_clusters", [])
                    if top_clusters:
                        # Find closest cluster
                        closest_cluster = min(top_clusters, key=lambda c: abs(c.get("price", current_price) - current_price))
                        cluster_price = closest_cluster.get("price", current_price)
                        distance_pct = abs(current_price - cluster_price) / current_price * 100 if current_price > 0 else 0
                        liq_magnet_distance = f"{distance_pct:.2f}%"
                        liq_cluster_direction = closest_cluster.get("direction", "UNKNOWN")
            except Exception as e:
                pass
            
            # Display Liquidation Magnet Distance
            st.markdown("**🧲 Liquidation Magnet Distance:**")
            st.metric("Distance to Nearest Cluster", liq_magnet_distance, liq_cluster_direction)
                
        except Exception as e:
            st.warning(f"Institutional precision indicators unavailable: {e}")
        
        st.markdown("---")
        
        # [BIG ALPHA PHASE 5] Execution Quality (BPS) Gauge
        st.subheader("⚡ Execution Quality (Slippage Audit)")
        try:
            from src.trade_execution import get_recent_slippage_stats
            
            slippage_stats = get_recent_slippage_stats(symbol=symbol_selector, hours=24)
            
            if not slippage_stats.get("error"):
                avg_slippage = slippage_stats.get("avg_slippage_bps", 0.0)
                max_slippage = slippage_stats.get("max_slippage_bps", 0.0)
                exceeding_5bps_pct = slippage_stats.get("exceeding_5bps_pct", 0.0)
                total_executions = slippage_stats.get("total_executions", 0)
                
                # Determine quality status
                if abs(avg_slippage) < 3.0:
                    quality_status = "EXCELLENT"
                    quality_color = "🟢"
                elif abs(avg_slippage) < 5.0:
                    quality_status = "GOOD"
                    quality_color = "🟡"
                elif abs(avg_slippage) < 10.0:
                    quality_status = "FAIR"
                    quality_color = "🟠"
                else:
                    quality_status = "POOR"
                    quality_color = "🔴"
                
                col1, col2, col3, col4 = st.columns(4)
                col1.metric("Avg Slippage (BPS)", f"{avg_slippage:.2f}", quality_status, delta_color="inverse")
                col2.metric("Max Slippage (BPS)", f"{max_slippage:.2f}", f"{quality_color} {quality_status}")
                col3.metric("Exceeding 5bps", f"{exceeding_5bps_pct:.1f}%", f"{total_executions} trades")
                col4.metric("Execution Quality", quality_status, quality_color)
                
                # Visual gauge using progress bar
                st.markdown("**Slippage Distribution:**")
                slippage_pct_normalized = min(100, max(0, (abs(avg_slippage) / 10.0) * 100))  # Normalize to 0-100% (10bps = 100%)
                st.progress(slippage_pct_normalized / 100.0)
                st.caption(f"Target: < 5bps | Current: {avg_slippage:.2f}bps | {'✅ Within target' if abs(avg_slippage) < 5.0 else '⚠️ Above target'}")
                
                # Show if FeeAwareGate threshold was auto-adjusted
                try:
                    import json
                    from pathlib import Path
                    config_path = Path("configs/trading_config.json")
                    if config_path.exists():
                        with open(config_path, 'r') as f:
                            trading_config = json.load(f)
                            per_symbol = trading_config.get("per_symbol_fee_gates", {})
                            symbol_config = per_symbol.get(symbol_selector, {})
                            if symbol_config:
                                multiplier = symbol_config.get("min_buffer_multiplier", 1.2)
                                if multiplier != 1.2:
                                    st.info(f"🔧 Auto-adjusted: FeeAwareGate threshold multiplier = {multiplier:.2f} (default: 1.2) due to slippage")
                except:
                    pass
            else:
                st.info(f"Execution quality data unavailable: {slippage_stats.get('error', 'No data')}")
        except Exception as e:
            st.warning(f"Execution quality gauge unavailable: {e}")
        
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
        
        # [BIG ALPHA PHASE 4] Whale CVD vs Retail CVD Divergence Chart
        st.subheader("🐋 Whale CVD vs Retail CVD Divergence")
        try:
            from src.intent_intelligence_guards import get_whale_cvd_intent, load_whale_cvd_threshold
            
            whale_cvd_data = get_whale_cvd_intent(symbol_selector)
            threshold = load_whale_cvd_threshold()
            
            if not whale_cvd_data.get("error"):
                whale_buy = whale_cvd_data.get("whale_buy_vol", 0)
                whale_sell = whale_cvd_data.get("whale_sell_vol", 0)
                whale_net = whale_cvd_data.get("whale_net_cvd", 0)
                whale_dir = whale_cvd_data.get("whale_cvd_direction", "NEUTRAL")
                
                retail_buy = whale_cvd_data.get("retail_buy_vol", 0)
                retail_sell = whale_cvd_data.get("retail_sell_vol", 0)
                retail_net = whale_cvd_data.get("retail_net_cvd", 0)
                retail_dir = whale_cvd_data.get("retail_cvd_direction", "NEUTRAL")
                
                # Calculate divergence
                divergence = "ALIGNED" if whale_dir == retail_dir else "DIVERGENT"
                
                col1, col2, col3, col4 = st.columns(4)
                col1.metric("Whale CVD", whale_dir, f"${whale_net/1e6:.2f}M")
                col2.metric("Retail CVD", retail_dir, f"${retail_net/1e6:.2f}M")
                col3.metric("Divergence", divergence, "⚠️" if divergence == "DIVERGENT" else "✅")
                col4.metric("Threshold", f"${threshold/1e3:.0f}K", "Auto-tuned")
                
                # Create divergence chart data
                chart_data = pd.DataFrame({
                    "Type": ["Whale Buy", "Whale Sell", "Retail Buy", "Retail Sell"],
                    "Volume (M)": [
                        whale_buy / 1e6,
                        whale_sell / 1e6,
                        retail_buy / 1e6,
                        retail_sell / 1e6
                    ]
                })
                
                st.bar_chart(chart_data.set_index("Type"))
                
                if divergence == "DIVERGENT":
                    st.warning(f"⚠️ Whale and Retail CVD are diverging! Whale={whale_dir}, Retail={retail_dir}")
            else:
                st.info("Whale CVD data unavailable")
        except Exception as e:
            st.warning(f"Whale CVD divergence chart unavailable: {e}")
        
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

with tab4:
    st.header("⏰ Golden Hour vs 24/7 Trading Comparison")
    st.markdown("Compare Golden Hour (09:00-16:00 UTC) vs 24/7 trading performance with detailed analytics")
    
    # Load closed trades with trading_window field
    try:
        from src.data_registry import DataRegistry as DR
        from datetime import datetime, timedelta, timezone
        import plotly.graph_objects as go
        import plotly.express as px
        
        closed_positions = DR.get_closed_positions(hours=None)  # Get all closed positions
        
        if not closed_positions:
            st.info("No closed trades found. Waiting for trading data...")
        else:
            # Filter trades by trading_window
            golden_hour_trades = [t for t in closed_positions if t.get("trading_window") == "golden_hour"]
            trades_24_7 = [t for t in closed_positions if t.get("trading_window") == "24_7"]
            unknown_trades = [t for t in closed_positions if t.get("trading_window") not in ["golden_hour", "24_7"]]
            
            st.markdown(f"**Total Trades:** {len(closed_positions)} | **Golden Hour:** {len(golden_hour_trades)} | **24/7:** {len(trades_24_7)} | **Unknown:** {len(unknown_trades)}")
            
            # Calculate metrics for each group
            def calculate_metrics(trades):
                if not trades:
                    return {
                        "count": 0, "wins": 0, "losses": 0, "win_rate": 0.0,
                        "total_pnl": 0.0, "avg_pnl": 0.0, "profit_factor": 0.0,
                        "gross_profit": 0.0, "gross_loss": 0.0, "max_win": 0.0, "max_loss": 0.0
                    }
                
                pnls = [t.get("net_pnl", t.get("pnl", 0)) or 0 for t in trades]
                wins = sum(1 for pnl in pnls if pnl > 0)
                losses = len(trades) - wins
                total_pnl = sum(pnls)
                gross_profit = sum(pnl for pnl in pnls if pnl > 0)
                gross_loss = abs(sum(pnl for pnl in pnls if pnl < 0))
                profit_factor = gross_profit / gross_loss if gross_loss > 0 else (gross_profit if gross_profit > 0 else 0.0)
                max_win = max(pnls) if pnls else 0.0
                max_loss = min(pnls) if pnls else 0.0
                
                return {
                    "count": len(trades),
                    "wins": wins,
                    "losses": losses,
                    "win_rate": (wins / len(trades) * 100) if trades else 0.0,
                    "total_pnl": total_pnl,
                    "avg_pnl": total_pnl / len(trades) if trades else 0.0,
                    "profit_factor": profit_factor,
                    "gross_profit": gross_profit,
                    "gross_loss": gross_loss,
                    "max_win": max_win,
                    "max_loss": max_loss
                }
            
            gh_metrics = calculate_metrics(golden_hour_trades)
            all_24_7_metrics = calculate_metrics(trades_24_7)
            
            # Calculate differences (both absolute and percent)
            pnl_diff_dollars = gh_metrics["total_pnl"] - all_24_7_metrics["total_pnl"]
            pnl_total_combined = abs(gh_metrics["total_pnl"]) + abs(all_24_7_metrics["total_pnl"])
            pnl_diff_percent = (pnl_diff_dollars / pnl_total_combined * 100) if pnl_total_combined > 0 else 0.0
            wr_diff = gh_metrics["win_rate"] - all_24_7_metrics["win_rate"]
            pf_diff = gh_metrics["profit_factor"] - all_24_7_metrics["profit_factor"]
            
            # Display comparison metrics with enhanced visualization
            st.subheader("📊 Performance Overview")
            col1, col2, col3 = st.columns(3)
            
            with col1:
                st.markdown("### 🕘 Golden Hour (09:00-16:00 UTC)")
                st.metric("Total Trades", gh_metrics["count"])
                st.metric("Win Rate", f"{gh_metrics['win_rate']:.1f}%")
                st.metric("Total P&L", f"${gh_metrics['total_pnl']:,.2f}", 
                         f"Avg: ${gh_metrics['avg_pnl']:,.2f}")
                st.metric("Profit Factor", f"{gh_metrics['profit_factor']:.2f}")
                st.metric("Gross Profit", f"${gh_metrics['gross_profit']:,.2f}")
                st.metric("Gross Loss", f"${gh_metrics['gross_loss']:,.2f}")
            
            with col2:
                st.markdown("### 🌐 24/7 Trading")
                st.metric("Total Trades", all_24_7_metrics["count"])
                st.metric("Win Rate", f"{all_24_7_metrics['win_rate']:,.1f}%")
                st.metric("Total P&L", f"${all_24_7_metrics['total_pnl']:,.2f}",
                         f"Avg: ${all_24_7_metrics['avg_pnl']:,.2f}")
                st.metric("Profit Factor", f"{all_24_7_metrics['profit_factor']:.2f}")
                st.metric("Gross Profit", f"${all_24_7_metrics['gross_profit']:,.2f}")
                st.metric("Gross Loss", f"${all_24_7_metrics['gross_loss']:,.2f}")
            
            with col3:
                st.markdown("### 📈 Difference (GH - 24/7)")
                st.metric("Trade Count Δ", f"{gh_metrics['count'] - all_24_7_metrics['count']:+d}")
                st.metric("Win Rate Δ", f"{wr_diff:+.1f}%", 
                         "✅ GH Better" if wr_diff > 0 else "⚠️ 24/7 Better")
                st.metric("P&L Δ (Dollars)", f"${pnl_diff_dollars:+,.2f}",
                         "✅ GH Better" if pnl_diff_dollars > 0 else "⚠️ 24/7 Better")
                st.metric("P&L Δ (Percent)", f"{pnl_diff_percent:+.1f}%",
                         "✅ GH Better" if pnl_diff_dollars > 0 else "⚠️ 24/7 Better")
                st.metric("Profit Factor Δ", f"{pf_diff:+.2f}",
                         "✅ GH Better" if pf_diff > 0 else "⚠️ 24/7 Better")
            
            st.markdown("---")
            
            # P&L Comparison Chart
            st.subheader("📈 P&L Comparison Charts")
            chart_col1, chart_col2 = st.columns(2)
            
            with chart_col1:
                # Bar chart comparing metrics
                fig_bar = go.Figure()
                fig_bar.add_trace(go.Bar(
                    name='Golden Hour',
                    x=['Total P&L', 'Avg P&L', 'Win Rate', 'Profit Factor'],
                    y=[gh_metrics['total_pnl'], gh_metrics['avg_pnl'], 
                       gh_metrics['win_rate'], gh_metrics['profit_factor']],
                    marker_color='#FFA500'
                ))
                fig_bar.add_trace(go.Bar(
                    name='24/7 Trading',
                    x=['Total P&L', 'Avg P&L', 'Win Rate', 'Profit Factor'],
                    y=[all_24_7_metrics['total_pnl'], all_24_7_metrics['avg_pnl'],
                       all_24_7_metrics['win_rate'], all_24_7_metrics['profit_factor']],
                    marker_color='#00D4FF'
                ))
                fig_bar.update_layout(
                    title='Performance Metrics Comparison',
                    barmode='group',
                    template='plotly_dark',
                    height=400
                )
                st.plotly_chart(fig_bar, use_container_width=True)
            
            with chart_col2:
                # P&L difference visualization
                fig_diff = go.Figure()
                colors = ['#00FF88' if pnl_diff_dollars > 0 else '#FF4444']
                fig_diff.add_trace(go.Bar(
                    x=['P&L Difference'],
                    y=[pnl_diff_dollars],
                    marker_color=colors[0],
                    text=[f"${pnl_diff_dollars:+,.2f}<br>({pnl_diff_percent:+.1f}%)"],
                    textposition='auto'
                ))
                fig_diff.add_hline(y=0, line_dash="dash", line_color="white", opacity=0.5)
                fig_diff.update_layout(
                    title=f'P&L Difference: Golden Hour vs 24/7',
                    yaxis_title='P&L Difference (USD)',
                    template='plotly_dark',
                    height=400,
                    showlegend=False
                )
                st.plotly_chart(fig_diff, use_container_width=True)
            
            st.markdown("---")
            
            # Daily comparison
            st.subheader("📅 Daily Comparison (Last 7 Days)")
            try:
                from datetime import datetime, timedelta, timezone
                
                def _parse_timestamp_for_comparison(ts):
                    """Parse timestamp for comparison purposes."""
                    if not ts:
                        return 0.0
                    try:
                        if isinstance(ts, (int, float)):
                            return float(ts)
                        if isinstance(ts, str):
                            ts_clean = ts.replace('Z', '+00:00')
                            if 'T' in ts_clean:
                                dt = datetime.fromisoformat(ts_clean)
                                if dt.tzinfo is None:
                                    dt = dt.replace(tzinfo=timezone.utc)
                                return dt.timestamp()
                        return 0.0
                    except:
                        return 0.0
                
                daily_comparison = {}
                for i in range(7):
                    day = (datetime.now(timezone.utc) - timedelta(days=i)).date()
                    day_start = datetime.combine(day, datetime.min.time()).replace(tzinfo=timezone.utc)
                    day_end = day_start + timedelta(days=1)
                    
                    day_gh = [t for t in golden_hour_trades 
                             if day_start.timestamp() <= _parse_timestamp_for_comparison(t.get("closed_at", t.get("opened_at", 0))) < day_end.timestamp()]
                    day_24_7 = [t for t in trades_24_7 
                               if day_start.timestamp() <= _parse_timestamp_for_comparison(t.get("closed_at", t.get("opened_at", 0))) < day_end.timestamp()]
                    
                    daily_comparison[day.isoformat()] = {
                        "golden_hour": calculate_metrics(day_gh),
                        "24_7": calculate_metrics(day_24_7)
                    }
                
                daily_data = []
                for day, metrics in sorted(daily_comparison.items(), reverse=True):
                    gh_pnl = metrics["golden_hour"]["total_pnl"]
                    t24_7_pnl = metrics["24_7"]["total_pnl"]
                    daily_pnl_diff = gh_pnl - t24_7_pnl
                    daily_data.append({
                        "Date": day,
                        "GH Trades": metrics["golden_hour"]["count"],
                        "GH P&L": metrics["golden_hour"]["total_pnl"],
                        "GH WR": f"{metrics['golden_hour']['win_rate']:.1f}%",
                        "24/7 Trades": metrics["24_7"]["count"],
                        "24/7 P&L": metrics["24_7"]["total_pnl"],
                        "24/7 WR": f"{metrics['24_7']['win_rate']:.1f}%",
                        "P&L Diff": daily_pnl_diff
                    })
                
                if daily_data:
                    df_daily = pd.DataFrame(daily_data)
                    
                    # Display as styled dataframe with color coding
                    st.dataframe(
                        df_daily.style.format({
                            "GH P&L": "${:,.2f}",
                            "24/7 P&L": "${:,.2f}",
                            "P&L Diff": "${:+,.2f}"
                        }).applymap(
                            lambda x: 'background-color: #0f2d0f' if isinstance(x, (int, float)) and x > 0 else 
                            ('background-color: #2d0f0f' if isinstance(x, (int, float)) and x < 0 else ''),
                            subset=["GH P&L", "24/7 P&L", "P&L Diff"]
                        ),
                        use_container_width=True,
                        hide_index=True
                    )
                    
                    # Daily P&L comparison chart
                    fig_daily = go.Figure()
                    fig_daily.add_trace(go.Bar(
                        name='Golden Hour',
                        x=df_daily['Date'],
                        y=df_daily['GH P&L'],
                        marker_color='#FFA500'
                    ))
                    fig_daily.add_trace(go.Bar(
                        name='24/7 Trading',
                        x=df_daily['Date'],
                        y=df_daily['24/7 P&L'],
                        marker_color='#00D4FF'
                    ))
                    fig_daily.update_layout(
                        title='Daily P&L Comparison (Last 7 Days)',
                        xaxis_title='Date',
                        yaxis_title='P&L (USD)',
                        barmode='group',
                        template='plotly_dark',
                        height=400
                    )
                    fig_daily.add_hline(y=0, line_dash="dash", line_color="white", opacity=0.3)
                    st.plotly_chart(fig_daily, use_container_width=True)
                else:
                    st.info("No daily comparison data available yet")
                    
            except Exception as e:
                st.warning(f"Daily comparison unavailable: {e}")
            
            st.markdown("---")
            
            # Configuration status
            st.subheader("⚙️ Configuration")
            try:
                from pathlib import Path
                from src.infrastructure.path_registry import PathRegistry
                
                config_file = Path(PathRegistry.get_path("feature_store", "golden_hour_config.json"))
                if config_file.exists():
                    import json
                    with open(config_file, 'r') as f:
                        config = json.load(f)
                    
                    restrict_enabled = config.get("restrict_to_golden_hour", True)
                    status = "🟢 ENABLED (24/7 trading allowed)" if not restrict_enabled else "🔴 DISABLED (Golden Hour only)"
                    st.info(f"**Golden Hour Restriction:** {status}")
                    st.caption(f"Config: `restrict_to_golden_hour = {restrict_enabled}`")
                else:
                    st.warning("Configuration file not found. Using default (restricted to golden hour).")
            except Exception as e:
                st.warning(f"Configuration status unavailable: {e}")
            
    except Exception as e:
        st.error(f"Error loading 24/7 trading data: {e}")
        import traceback
        st.code(traceback.format_exc())
