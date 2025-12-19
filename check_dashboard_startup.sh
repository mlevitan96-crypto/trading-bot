#!/bin/bash
# Comprehensive dashboard startup diagnostic script

echo "=========================================="
echo "Dashboard Startup Diagnostic"
echo "=========================================="
echo ""

echo "1. Checking if dashboard process is running..."
ps aux | grep -E "python.*run\.py|gunicorn|flask" | grep -v grep || echo "   ❌ No dashboard process found"
echo ""

echo "2. Checking if port 8050 is listening..."
if ss -tlnp | grep -q ":8050"; then
    echo "   ✅ Port 8050 is listening"
    ss -tlnp | grep ":8050"
else
    echo "   ❌ Port 8050 is NOT listening"
fi
echo ""

echo "3. Checking for dashboard startup messages in logs..."
journalctl -u tradingbot --since "10 minutes ago" | grep -E "(DASHBOARD|Starting P|dashboard|build_app|start_pnl|🌐.*8050)" || echo "   ❌ No dashboard startup messages found"
echo ""

echo "4. Checking for dashboard errors in logs..."
journalctl -u tradingbot --since "10 minutes ago" | grep -A 10 -E "(❌.*DASHBOARD|CRITICAL.*dashboard|ImportError|NameError|Traceback)" || echo "   ℹ️  No dashboard errors found in recent logs"
echo ""

echo "5. Checking environment variables..."
echo "   SUPERVISOR_CONTROLLED: ${SUPERVISOR_CONTROLLED:-not set}"
echo "   PORT: ${PORT:-not set (default 8050)}"
echo "   USE_GUNICORN: ${USE_GUNICORN:-not set (default 1)}"
echo ""

echo "6. Testing dashboard import manually..."
cd /root/trading-bot-current
python3 -c "
import sys
sys.path.insert(0, 'src')
try:
    print('   🔍 Testing import...')
    from src.pnl_dashboard import build_app, start_pnl_dashboard
    print('   ✅ Import successful')
    
    print('   🔍 Testing build_app()...')
    from flask import Flask
    app = Flask(__name__)
    dash = build_app(app)
    print('   ✅ build_app() successful')
except Exception as e:
    print(f'   ❌ Error: {e}')
    import traceback
    traceback.print_exc()
" 2>&1 | sed 's/^/   /'
echo ""

echo "7. Full startup log (last 100 lines)..."
journalctl -u tradingbot -n 100 | tail -50
echo ""

echo "=========================================="
echo "Diagnostic Complete"
echo "=========================================="
