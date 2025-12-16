#!/bin/bash
# Get the full error from bot cycle

echo "=== Full Error Traceback ==="
journalctl -u tradingbot --since "16:18:00" | grep -A 50 "run_bot_cycle()" | grep -A 50 "Traceback\|Error\|Exception" | head -60

echo ""
echo "=== Recent bot_cycle errors ==="
journalctl -u tradingbot --since "16:18:00" | grep -E "Error|Exception|Traceback|failed|Failed" | tail -30

