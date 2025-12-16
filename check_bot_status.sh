#!/bin/bash
# Quick diagnostic script to check bot status and logs

echo "=== Bot Service Status ==="
systemctl status tradingbot --no-pager -l | head -20

echo ""
echo "=== Checking for log files ==="
cd ~/trading-bot-current || exit 1

if [ -d "logs" ]; then
    echo "✅ logs/ directory exists"
    ls -lh logs/ | head -10
else
    echo "❌ logs/ directory does not exist"
fi

echo ""
echo "=== Checking bot_out.log ==="
if [ -f "logs/bot_out.log" ]; then
    echo "✅ bot_out.log exists"
    echo "Last 20 lines:"
    tail -20 logs/bot_out.log
else
    echo "❌ bot_out.log does not exist"
    echo "Checking for other log files..."
    find logs/ -name "*.log" -type f 2>/dev/null | head -5
fi

echo ""
echo "=== Checking for errors ==="
if [ -f "logs/bot_err.log" ]; then
    echo "Last 20 lines of bot_err.log:"
    tail -20 logs/bot_err.log
fi

echo ""
echo "=== Checking systemd journal ==="
journalctl -u tradingbot -n 30 --no-pager

echo ""
echo "=== Checking if bot process is running ==="
ps aux | grep -E "python.*run\.py|trading.*bot" | grep -v grep

echo ""
echo "=== Checking for new architecture components ==="
if [ -f "logs/signal_bus.jsonl" ]; then
    echo "✅ signal_bus.jsonl exists"
    echo "Last 3 lines:"
    tail -3 logs/signal_bus.jsonl 2>/dev/null || echo "File is empty or unreadable"
else
    echo "⚠️  signal_bus.jsonl does not exist yet (will be created on first signal)"
fi

