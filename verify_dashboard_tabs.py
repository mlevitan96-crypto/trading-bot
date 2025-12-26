#!/usr/bin/env python3
"""Verify dashboard tabs are correct."""
import sys
sys.path.insert(0, ".")

from flask import Flask
from src.pnl_dashboard_v2 import build_app

flask_app = Flask(__name__)
dash_app = build_app(flask_app)

# Find the Tabs component
tabs_component = None
for child in dash_app.layout.children:
    if hasattr(child, 'id') and child.id == 'main-tabs':
        tabs_component = child
        break

if tabs_component:
    print(f"✅ Found main-tabs component with {len(tabs_component.children)} tabs")
    for i, tab in enumerate(tabs_component.children):
        if hasattr(tab, 'label'):
            print(f"  Tab {i+1}: {tab.label} (value: {tab.value})")
        else:
            print(f"  Tab {i+1}: {type(tab)}")
else:
    print("❌ Could not find main-tabs component")
    print("Available children:")
    for i, child in enumerate(dash_app.layout.children):
        print(f"  {i}: {type(child)} (id: {getattr(child, 'id', 'N/A')})")

