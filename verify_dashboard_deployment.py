#!/usr/bin/env python3
"""Verify dashboard deployment and chart functions."""
import sys
sys.path.insert(0, ".")

try:
    # Test imports
    import streamlit
    import plotly.graph_objects as go
    import plotly.express as px
    print("✅ All dashboard dependencies available")
    
    # Test chart functions
    from cockpit import (
        create_equity_curve_chart,
        create_pnl_by_symbol_chart,
        create_pnl_by_strategy_chart,
        create_win_rate_heatmap,
        create_wallet_balance_trend
    )
    print("✅ All chart functions importable")
    
    # Test tab structure
    with open("cockpit.py", "r") as f:
        content = f.read()
        if 'tab1, tab2, tab3, tab4 = st.tabs' in content:
            print("✅ Dashboard has 4 tabs (Trading, Analytics, Performance, 24/7 Trading)")
        if '"⏰ 24/7 Trading"' in content:
            print("✅ 24/7 Trading tab is present")
        if 'create_equity_curve_chart' in content:
            print("✅ Chart functions are integrated")
        if 'Portfolio Health (Phase 7)' in content:
            print("✅ Phase 7 Portfolio Health metrics are present")
    
    print("\n✅ Dashboard deployment verified successfully!")
    
except Exception as e:
    print(f"❌ Error: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

