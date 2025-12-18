#!/bin/bash
# Run dashboard fix script with venv

cd /root/trading-bot-current

# Use venv Python
if [ -f "venv/bin/python3" ]; then
    echo "Using venv Python..."
    venv/bin/python3 fix_dashboard_and_healing.py
else
    echo "⚠️  venv not found, using system Python..."
    python3 fix_dashboard_and_healing.py
fi
