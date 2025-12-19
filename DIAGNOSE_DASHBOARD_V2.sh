#!/bin/bash
# Dashboard V2 Diagnostic Script

echo "=== Dashboard V2 Diagnostic ==="
echo ""

# 1. Check if file exists
echo "1. Checking if dashboard file exists..."
if [ -f "src/pnl_dashboard_v2.py" ]; then
    echo "   ✅ src/pnl_dashboard_v2.py exists"
else
    echo "   ❌ src/pnl_dashboard_v2.py NOT FOUND"
    exit 1
fi

# 2. Check Python syntax
echo ""
echo "2. Checking Python syntax..."
python3 -m py_compile src/pnl_dashboard_v2.py 2>&1
if [ $? -eq 0 ]; then
    echo "   ✅ Syntax OK"
else
    echo "   ❌ Syntax error found"
    exit 1
fi

# 3. Check imports
echo ""
echo "3. Testing imports..."
python3 -c "from src.pnl_dashboard_v2 import start_pnl_dashboard; print('✅ Import successful')" 2>&1
if [ $? -eq 0 ]; then
    echo "   ✅ Import successful"
else
    echo "   ❌ Import failed - see error above"
    exit 1
fi

# 4. Check recent logs for dashboard messages
echo ""
echo "4. Checking recent dashboard startup logs..."
journalctl -u tradingbot --since "10 minutes ago" | grep -i "DASHBOARD\|dashboard" | tail -30

# 5. Check for errors
echo ""
echo "5. Checking for errors in recent logs..."
journalctl -u tradingbot --since "10 minutes ago" | grep -E "ERROR|Traceback|Exception|Failed" | grep -i "dashboard" | tail -20

# 6. Check if port 8050 is listening
echo ""
echo "6. Checking if port 8050 is listening..."
netstat -tlnp 2>/dev/null | grep 8050 || ss -tlnp 2>/dev/null | grep 8050 || echo "   ⚠️  Port 8050 not found listening"

# 7. Check bot status
echo ""
echo "7. Checking bot service status..."
systemctl status tradingbot --no-pager | head -15

echo ""
echo "=== Diagnostic Complete ==="
