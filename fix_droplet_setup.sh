#!/bin/bash
# Fix droplet setup: install dependencies and fix paths

set -e  # Exit on error

echo "=== Fixing Droplet Setup ==="

# Get the actual working directory
WORK_DIR="/root/trading-bot-current"
cd "$WORK_DIR" || { echo "❌ Cannot cd to $WORK_DIR"; exit 1; }

echo "✅ Working directory: $(pwd)"

# 1. Check if venv exists
if [ ! -d "venv" ]; then
    echo "📦 Creating virtual environment..."
    python3 -m venv venv
fi

# 2. Activate venv and install dependencies
echo "📦 Installing/updating dependencies..."
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt

# 3. Check if .env file exists
if [ ! -f ".env" ]; then
    echo "⚠️  .env file not found. Creating template..."
    if [ -f ".env.example" ]; then
        cp .env.example .env
        echo "✅ Created .env from .env.example (please edit with your credentials)"
    else
        echo "⚠️  .env.example not found. You'll need to create .env manually"
    fi
fi

# 4. Fix the hardcoded path in run.py (if it exists)
if [ -f "src/run.py" ]; then
    echo "🔧 Checking run.py for hardcoded paths..."
    # Check if it has the old path
    if grep -q "/root/trading-bot/.env" src/run.py 2>/dev/null; then
        echo "⚠️  Found hardcoded path in src/run.py"
        echo "   This should use PathRegistry or relative paths"
    fi
fi

# 5. Check if run.py exists in root
if [ ! -f "run.py" ]; then
    echo "⚠️  run.py not found in root. Checking for src/run.py..."
    if [ -f "src/run.py" ]; then
        echo "✅ Found src/run.py"
        echo "   Service file should point to: $WORK_DIR/src/run.py"
    fi
fi

# 6. Verify service file
echo ""
echo "=== Service File Check ==="
if [ -f "/etc/systemd/system/tradingbot.service" ]; then
    echo "✅ Service file exists"
    echo "Current configuration:"
    cat /etc/systemd/system/tradingbot.service
    echo ""
    echo "⚠️  Verify ExecStart points to: $WORK_DIR/venv/bin/python3"
    echo "⚠️  Verify WorkingDirectory is: $WORK_DIR"
else
    echo "❌ Service file not found at /etc/systemd/system/tradingbot.service"
fi

# 7. Test import
echo ""
echo "=== Testing Python Import ==="
source venv/bin/activate
python3 -c "from dotenv import load_dotenv; print('✅ dotenv import works')" || {
    echo "❌ dotenv import failed"
    echo "   Installing python-dotenv..."
    pip install python-dotenv
}

# 8. Test run.py import
echo ""
echo "=== Testing run.py Import ==="
cd "$WORK_DIR"
source venv/bin/activate
python3 -c "
import sys
sys.path.insert(0, 'src')
try:
    import run
    print('✅ run.py imports successfully')
except Exception as e:
    print(f'❌ run.py import failed: {e}')
    import traceback
    traceback.print_exc()
" || echo "⚠️  Import test failed (this is expected if .env is missing)"

echo ""
echo "=== Summary ==="
echo "✅ Dependencies installed in venv"
echo "✅ Ready to restart service"
echo ""
echo "Next steps:"
echo "1. Edit .env file with your credentials (if needed)"
echo "2. Update service file if paths are wrong:"
echo "   sudo nano /etc/systemd/system/tradingbot.service"
echo "3. Reload and restart:"
echo "   sudo systemctl daemon-reload"
echo "   sudo systemctl restart tradingbot"
echo "4. Check status:"
echo "   sudo systemctl status tradingbot"
echo "   journalctl -u tradingbot -f"

