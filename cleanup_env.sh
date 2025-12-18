#!/bin/bash
# Clean up duplicate EXCHANGE lines in .env file

ENV_FILE="/root/trading-bot-current/.env"

if [ ! -f "$ENV_FILE" ]; then
    echo "❌ .env file not found: $ENV_FILE"
    exit 1
fi

echo "Cleaning up duplicate EXCHANGE lines in .env..."
echo ""

# Backup first
cp "$ENV_FILE" "${ENV_FILE}.backup.$(date +%Y%m%d_%H%M%S)"

# Remove all EXCHANGE lines
sed -i '/^EXCHANGE=/d' "$ENV_FILE"

# Add single EXCHANGE=kraken at the top (after any comments)
if ! grep -q "^EXCHANGE=" "$ENV_FILE"; then
    # Find first non-comment line and insert before it
    if head -1 "$ENV_FILE" | grep -q "^#"; then
        # If first line is a comment, add after it
        sed -i '1a EXCHANGE=kraken' "$ENV_FILE"
    else
        # Otherwise add at the top
        sed -i '1i EXCHANGE=kraken' "$ENV_FILE"
    fi
fi

echo "✅ Cleaned up duplicate EXCHANGE lines"
echo ""
echo "Current .env EXCHANGE settings:"
grep "^EXCHANGE=" "$ENV_FILE"
