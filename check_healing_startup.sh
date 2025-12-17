#!/bin/bash
# Quick script to check if healing operator is being started

echo "Checking if bot_worker thread is running..."
journalctl -u tradingbot -n 1000 | grep -E "(Bot worker|bot_worker|HEALING|Starting.*Healing)" | tail -20

echo ""
echo "Checking if healing operator started successfully..."
journalctl -u tradingbot -n 1000 | grep -E "(✅.*HEALING|Healing operator started|Self-healing operator)" | tail -10

echo ""
echo "Checking for healing operator errors..."
journalctl -u tradingbot -n 1000 | grep -i "healing.*error" | tail -10
