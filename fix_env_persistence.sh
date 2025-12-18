#!/bin/bash
# Fix .env file persistence - Ensure systemd service loads .env correctly

set -e

echo "=========================================="
echo "FIX .ENV PERSISTENCE"
echo "=========================================="
echo ""

# Find the active bot directory
BOT_DIR="/root/trading-bot-current"
if [ ! -d "$BOT_DIR" ]; then
    echo "❌ Bot directory not found: $BOT_DIR"
    exit 1
fi

ENV_FILE="$BOT_DIR/.env"
SERVICE_FILE="/etc/systemd/system/tradingbot.service"

echo "1. Checking .env file..."
if [ -f "$ENV_FILE" ]; then
    echo "   ✅ .env file exists: $ENV_FILE"
    echo ""
    echo "   Current EXCHANGE setting:"
    grep "^EXCHANGE=" "$ENV_FILE" || echo "   ⚠️  EXCHANGE not found in .env"
    echo ""
else
    echo "   ❌ .env file not found: $ENV_FILE"
    echo "   Creating template..."
    cat > "$ENV_FILE" << 'EOF'
EXCHANGE=kraken
KRAKEN_FUTURES_API_KEY=
KRAKEN_FUTURES_API_SECRET=
KRAKEN_FUTURES_TESTNET=true
EOF
    chmod 600 "$ENV_FILE"
    echo "   ✅ Created .env file - EDIT IT NOW with your keys!"
    exit 1
fi

echo "2. Checking systemd service file..."
if [ ! -f "$SERVICE_FILE" ]; then
    echo "   ❌ Service file not found: $SERVICE_FILE"
    exit 1
fi

echo "   ✅ Service file exists"
echo ""

echo "3. Checking if service loads .env file..."
if grep -q "EnvironmentFile" "$SERVICE_FILE"; then
    CURRENT_ENV_FILE=$(grep "EnvironmentFile" "$SERVICE_FILE" | awk '{print $2}' | tr -d '=-')
    echo "   Found EnvironmentFile: $CURRENT_ENV_FILE"
    
    if [ "$CURRENT_ENV_FILE" != "$ENV_FILE" ]; then
        echo "   ⚠️  Service points to different .env file!"
        echo "   Current: $CURRENT_ENV_FILE"
        echo "   Should be: $ENV_FILE"
        echo ""
        echo "   Updating service file..."
        
        # Backup service file
        cp "$SERVICE_FILE" "${SERVICE_FILE}.backup.$(date +%Y%m%d_%H%M%S)"
        
        # Update EnvironmentFile line
        sed -i "s|EnvironmentFile=.*|EnvironmentFile=$ENV_FILE|g" "$SERVICE_FILE"
        
        echo "   ✅ Updated EnvironmentFile to: $ENV_FILE"
    else
        echo "   ✅ Service already points to correct .env file"
    fi
else
    echo "   ⚠️  Service file doesn't have EnvironmentFile directive!"
    echo "   Adding it..."
    
    # Backup service file
    cp "$SERVICE_FILE" "${SERVICE_FILE}.backup.$(date +%Y%m%d_%H%M%S)"
    
    # Add EnvironmentFile after [Service] line
    sed -i "/\[Service\]/a EnvironmentFile=$ENV_FILE" "$SERVICE_FILE"
    
    echo "   ✅ Added EnvironmentFile=$ENV_FILE to service file"
fi

echo ""
echo "4. Verifying .env file has EXCHANGE=kraken..."
if grep -q "^EXCHANGE=kraken" "$ENV_FILE"; then
    echo "   ✅ EXCHANGE=kraken found in .env"
else
    echo "   ⚠️  EXCHANGE=kraken NOT found in .env"
    echo "   Current EXCHANGE value:"
    grep "^EXCHANGE=" "$ENV_FILE" || echo "   (not set)"
    echo ""
    echo "   Adding EXCHANGE=kraken..."
    
    # Remove any existing EXCHANGE line
    sed -i '/^EXCHANGE=/d' "$ENV_FILE"
    
    # Add EXCHANGE=kraken at the top
    sed -i "1i EXCHANGE=kraken" "$ENV_FILE"
    
    echo "   ✅ Added EXCHANGE=kraken to .env file"
fi

echo ""
echo "5. Reloading systemd and restarting bot..."
systemctl daemon-reload
systemctl restart tradingbot

echo ""
echo "6. Verifying environment variable is loaded..."
sleep 2
if systemctl show tradingbot | grep -q "EXCHANGE=kraken"; then
    echo "   ✅ EXCHANGE=kraken is in systemd environment"
else
    echo "   ⚠️  EXCHANGE not found in systemd environment"
    echo "   Checking logs for confirmation..."
fi

echo ""
echo "=========================================="
echo "FIX COMPLETE"
echo "=========================================="
echo ""
echo "Summary:"
echo "  • .env file: $ENV_FILE"
echo "  • Service file: $SERVICE_FILE"
echo "  • Bot restarted"
echo ""
echo "Verify it's working:"
echo "  journalctl -u tradingbot -n 50 | grep -i 'ExchangeGateway\|EXCHANGE'"
echo ""
