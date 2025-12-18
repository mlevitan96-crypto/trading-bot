#!/bin/bash
# Verify .env is loaded correctly

echo "=========================================="
echo "VERIFY .ENV SETUP"
echo "=========================================="
echo ""

BOT_DIR="/root/trading-bot-current"
ENV_FILE="$BOT_DIR/.env"
SERVICE_FILE="/etc/systemd/system/tradingbot.service"

echo "1. Checking .env file..."
echo "   File: $ENV_FILE"
if [ -f "$ENV_FILE" ]; then
    echo "   ✅ Exists"
    echo ""
    echo "   EXCHANGE settings:"
    grep "^EXCHANGE=" "$ENV_FILE" | head -1
    echo ""
    echo "   All EXCHANGE lines (to check for duplicates):"
    grep "^EXCHANGE=" "$ENV_FILE" || echo "   (none found)"
else
    echo "   ❌ Not found"
fi

echo ""
echo "2. Checking systemd service file..."
if [ -f "$SERVICE_FILE" ]; then
    echo "   ✅ Service file exists"
    echo ""
    echo "   EnvironmentFile directive:"
    grep "EnvironmentFile" "$SERVICE_FILE" || echo "   ⚠️  Not found"
    echo ""
    echo "   Full [Service] section:"
    sed -n '/\[Service\]/,/\[.*\]/p' "$SERVICE_FILE" | head -20
else
    echo "   ❌ Service file not found"
fi

echo ""
echo "3. Checking if bot process has EXCHANGE variable..."
BOT_PID=$(systemctl show tradingbot --property=MainPID --value)
if [ -n "$BOT_PID" ] && [ "$BOT_PID" != "0" ]; then
    echo "   Bot PID: $BOT_PID"
    if sudo cat /proc/$BOT_PID/environ 2>/dev/null | tr '\0' '\n' | grep -q "^EXCHANGE="; then
        echo "   ✅ EXCHANGE variable found in process environment:"
        sudo cat /proc/$BOT_PID/environ 2>/dev/null | tr '\0' '\n' | grep "^EXCHANGE="
    else
        echo "   ⚠️  EXCHANGE variable NOT found in process environment"
    fi
else
    echo "   ⚠️  Bot process not running or PID not found"
fi

echo ""
echo "4. Checking bot logs for exchange initialization..."
echo "   Recent ExchangeGateway messages:"
journalctl -u tradingbot -n 100 --no-pager | grep -i "ExchangeGateway" | tail -5 || echo "   (none found)"

echo ""
echo "=========================================="
