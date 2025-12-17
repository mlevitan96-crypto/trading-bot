#!/bin/bash
# Setup CoinGlass API Key for Trading Bot

set -euo pipefail

echo "🔑 CoinGlass API Key Setup"
echo "=========================="
echo ""

# Check if running as root
if [ "$EUID" -ne 0 ]; then 
    echo "⚠️  Please run as root (use sudo)"
    exit 1
fi

# Get API key from user
read -p "Enter your CoinGlass API key: " API_KEY

if [ -z "$API_KEY" ]; then
    echo "❌ API key cannot be empty"
    exit 1
fi

echo ""
echo "Setting up CoinGlass API key..."
echo ""

# Method 1: Check if systemd service exists
SERVICE_FILE="/etc/systemd/system/tradingbot.service"
if [ -f "$SERVICE_FILE" ]; then
    echo "📝 Found systemd service: $SERVICE_FILE"
    
    # Check if Environment directive already exists
    if grep -q "COINGLASS_API_KEY" "$SERVICE_FILE"; then
        echo "⚠️  COINGLASS_API_KEY already exists in service file"
        echo "    Updating existing entry..."
        # Use sed to update existing key
        sed -i "s|Environment=.*COINGLASS_API_KEY=.*|Environment=\"COINGLASS_API_KEY=$API_KEY\"|g" "$SERVICE_FILE"
    else
        echo "➕ Adding COINGLASS_API_KEY to service file..."
        # Find [Service] section and add Environment line after it
        sed -i '/\[Service\]/a Environment="COINGLASS_API_KEY='"$API_KEY"'"' "$SERVICE_FILE"
    fi
    
    echo "✅ Updated systemd service file"
    echo ""
    echo "Reloading systemd and restarting bot..."
    systemctl daemon-reload
    systemctl restart tradingbot
    
    echo ""
    echo "✅ Bot restarted with CoinGlass API key"
    
# Method 2: Check if service uses EnvironmentFile
elif [ -f "/etc/systemd/system/tradingbot.service" ]; then
    ENV_FILE=$(grep "EnvironmentFile" /etc/systemd/system/tradingbot.service | awk '{print $2}' | tr -d '=-')
    
    if [ -n "$ENV_FILE" ]; then
        echo "📝 Found EnvironmentFile: $ENV_FILE"
        echo "COINGLASS_API_KEY=$API_KEY" >> "$ENV_FILE"
        echo "✅ Added to environment file"
        
        systemctl daemon-reload
        systemctl restart tradingbot
        echo "✅ Bot restarted"
    fi
else
    echo "⚠️  Could not find systemd service file"
    echo "   Creating environment file method..."
    
    # Create environment file
    ENV_FILE="/etc/tradingbot/env"
    mkdir -p "$(dirname "$ENV_FILE")"
    echo "COINGLASS_API_KEY=$API_KEY" > "$ENV_FILE"
    chmod 600 "$ENV_FILE"
    
    echo "✅ Created $ENV_FILE"
    echo "   Add this to your systemd service:"
    echo "   EnvironmentFile=$ENV_FILE"
fi

# Verify it's set
echo ""
echo "Verifying API key is set..."
sleep 2
if systemctl show tradingbot | grep -q "COINGLASS_API_KEY"; then
    echo "✅ API key is in systemd environment"
else
    echo "⚠️  API key not found in systemd environment"
    echo "   You may need to manually edit the service file"
fi

echo ""
echo "🧪 Testing CoinGlass connection..."
cd /root/trading-bot-current || cd /root/trading-bot-A || cd /root/trading-bot-B

# Wait a moment for bot to start
sleep 3

# Run diagnostic
if [ -f "check_coinglass_feed.py" ]; then
    python3 check_coinglass_feed.py
else
    echo "⚠️  Diagnostic script not found, checking logs instead..."
    journalctl -u tradingbot -n 50 | grep -i "coinglass\|intel" | tail -10
fi

echo ""
echo "📋 Next Steps:"
echo "1. Wait 2-3 minutes for CoinGlass data to be fetched"
echo "2. Check dashboard - CoinGlass feed should turn green"
echo "3. Run: python3 check_coinglass_feed.py"
