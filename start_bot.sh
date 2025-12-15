#!/bin/bash

# 1. Activate Environment
source /root/trading-bot/venv/bin/activate
export PYTHONPATH=/root/trading-bot

# 2. Start Streamlit Dashboard (Background)
echo "🚀 Starting Dashboard..."
nohup streamlit run cockpit.py --server.port 8501 --server.address 0.0.0.0 > /root/trading-bot/logs/streamlit.log 2>&1 &

# 3. Start PnL Reporter (Background) - THE NEW PIECE
echo "📡 Starting PnL Reporter..."
nohup python3 src/pnl_reporter.py > /root/trading-bot/logs/reporter.log 2>&1 &

# 4. Start Main Trading Bot (Foreground)
echo "🧠 Starting Trading Bot..."
python3 run.py
