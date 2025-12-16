#!/bin/bash
# Check if signals are being generated

echo "=== Signal Generation Check ==="
cd ~/trading-bot-current || exit 1

echo ""
echo "1. Check if trading engine is running:"
ps aux | grep -E "run_bot_cycle|bot_cycle" | grep -v grep || echo "   ⚠️  Bot cycle not found in process list"

echo ""
echo "2. Check recent log entries for signal generation:"
journalctl -u tradingbot --since "5 minutes ago" | grep -E "ALPHA|signal|SIGNAL|predictive" | tail -20 || echo "   ⚠️  No signal-related logs found"

echo ""
echo "3. Check file ages:"
echo "   predictive_signals.jsonl:"
if [ -f "logs/predictive_signals.jsonl" ]; then
    ls -lh logs/predictive_signals.jsonl
    echo "   Last modified: $(stat -c %y logs/predictive_signals.jsonl)"
    echo "   Size: $(wc -l < logs/predictive_signals.jsonl) lines"
    echo "   Last 3 lines:"
    tail -3 logs/predictive_signals.jsonl 2>/dev/null || echo "   (file is empty)"
else
    echo "   ❌ File does not exist"
fi

echo ""
echo "   ensemble_predictions.jsonl:"
if [ -f "logs/ensemble_predictions.jsonl" ]; then
    ls -lh logs/ensemble_predictions.jsonl
    echo "   Last modified: $(stat -c %y logs/ensemble_predictions.jsonl)"
    echo "   Size: $(wc -l < logs/ensemble_predictions.jsonl) lines"
    echo "   Last 3 lines:"
    tail -3 logs/ensemble_predictions.jsonl 2>/dev/null || echo "   (file is empty)"
else
    echo "   ❌ File does not exist"
fi

echo ""
echo "   positions_futures.json:"
if [ -f "logs/positions_futures.json" ]; then
    ls -lh logs/positions_futures.json
    echo "   Last modified: $(stat -c %y logs/positions_futures.json)"
    file_age=$(($(date +%s) - $(stat -c %Y logs/positions_futures.json)))
    echo "   Age: $((file_age / 60)) minutes"
else
    echo "   ❌ File does not exist"
fi

echo ""
echo "4. Check if bot cycle is being called:"
journalctl -u tradingbot --since "10 minutes ago" | grep -E "bot_cycle|ENGINE|Starting trading" | tail -10

