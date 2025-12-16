#!/bin/bash
# Verify bot is working correctly

echo "=== Bot Status Check ==="
cd ~/trading-bot-current || exit 1

echo ""
echo "1. Check if bot cycle is running:"
ps aux | grep -E "run_bot_cycle|bot_cycle" | grep -v grep || echo "   (bot cycle runs in thread, not separate process)"

echo ""
echo "2. Check recent bot cycle completions:"
journalctl -u tradingbot --since "5 minutes ago" | grep -E "Bot cycle completed|run_bot_cycle.*completed" | tail -5

echo ""
echo "3. Check if signals are being generated:"
if [ -f "logs/predictive_signals.jsonl" ]; then
    file_age=$(($(date +%s) - $(stat -c %Y logs/predictive_signals.jsonl)))
    echo "   predictive_signals.jsonl: Last updated $((file_age / 60)) minutes ago"
    echo "   Last 2 lines:"
    tail -2 logs/predictive_signals.jsonl 2>/dev/null | head -2
else
    echo "   ⚠️  predictive_signals.jsonl does not exist"
fi

echo ""
echo "4. Check if positions are being updated:"
if [ -f "logs/positions_futures.json" ]; then
    file_age=$(($(date +%s) - $(stat -c %Y logs/positions_futures.json)))
    echo "   positions_futures.json: Last updated $((file_age / 60)) minutes ago"
    if [ $file_age -lt 300 ]; then
        echo "   ✅ File is recent (less than 5 minutes old)"
    else
        echo "   ⚠️  File is stale (more than 5 minutes old)"
    fi
else
    echo "   ⚠️  positions_futures.json does not exist"
fi

echo ""
echo "5. Check for any errors in last 5 minutes:"
journalctl -u tradingbot --since "5 minutes ago" | grep -E "Error|Exception|Traceback|failed|Failed" | tail -5 || echo "   ✅ No errors found"

echo ""
echo "6. Check dashboard status files:"
if [ -f "logs/signal_bus.jsonl" ]; then
    bus_size=$(wc -l < logs/signal_bus.jsonl 2>/dev/null || echo "0")
    echo "   signal_bus.jsonl: $bus_size lines"
fi

if [ -f "logs/shadow_trade_outcomes.jsonl" ]; then
    shadow_size=$(wc -l < logs/shadow_trade_outcomes.jsonl 2>/dev/null || echo "0")
    echo "   shadow_trade_outcomes.jsonl: $shadow_size lines"
fi

echo ""
echo "=== Summary ==="
echo "If bot cycle is completing successfully, the bot is working!"
echo "Signals and trades should start appearing in the logs."

