#!/bin/bash
# Verify all new deployment features are working

echo "=================================="
echo "DEPLOYMENT VERIFICATION"
echo "=================================="
echo ""

# 1. Check EXCHANGE env var
echo "1️⃣ Checking EXCHANGE configuration..."
EXCHANGE=$(grep "^EXCHANGE=" /root/trading-bot-current/.env 2>/dev/null | cut -d'=' -f2)
if [ -z "$EXCHANGE" ]; then
    EXCHANGE=$(printenv EXCHANGE)
fi
if [ -z "$EXCHANGE" ]; then
    echo "   ⚠️  EXCHANGE not set in .env or environment"
else
    echo "   ✅ EXCHANGE=$EXCHANGE"
fi
echo ""

# 2. Check if validation status file exists
echo "2️⃣ Checking venue symbol validation..."
if [ -f "feature_store/venue_symbol_status.json" ]; then
    echo "   ✅ Validation status file exists"
    cat feature_store/venue_symbol_status.json | jq '.summary' 2>/dev/null || echo "   ⚠️  Could not parse JSON"
else
    echo "   ⚠️  Validation status file not found (may not have run yet)"
    echo "   💡 Validation runs on startup if EXCHANGE=kraken"
fi
echo ""

# 3. Check exchange health status
echo "3️⃣ Checking exchange health..."
if [ -f "feature_store/exchange_health_state.json" ]; then
    echo "   ✅ Exchange health state file exists"
    cat feature_store/exchange_health_state.json | jq '.status, .consecutive_failures' 2>/dev/null || echo "   ⚠️  Could not parse JSON"
else
    echo "   ⚠️  Exchange health state file not found (may not have run yet)"
fi
echo ""

# 4. Check healing escalation status
echo "4️⃣ Checking healing escalation..."
if [ -f "feature_store/healing_escalation_state.json" ]; then
    echo "   ✅ Escalation state file exists"
    cat feature_store/healing_escalation_state.json | jq '.escalation_status, .soft_kill_switch_active' 2>/dev/null || echo "   ⚠️  Could not parse JSON"
else
    echo "   ⚠️  Escalation state file not found (will be created on first heal)"
fi
echo ""

# 5. Check sample readiness
echo "5️⃣ Checking symbol sample readiness..."
if [ -f "feature_store/symbol_sample_readiness.json" ]; then
    echo "   ✅ Sample readiness file exists"
    cat feature_store/symbol_sample_readiness.json | jq '.config' 2>/dev/null || echo "   ⚠️  Could not parse JSON"
else
    echo "   ⚠️  Sample readiness file not found (will be created on first check)"
fi
echo ""

# 6. Check if new Python files exist
echo "6️⃣ Checking new Python files..."
FILES=(
    "src/venue_symbol_validator.py"
    "src/healing_escalation.py"
    "src/exchange_health_monitor.py"
    "src/symbol_sample_readiness.py"
    "src/deployment_safety_checks.py"
)

for file in "${FILES[@]}"; do
    if [ -f "$file" ]; then
        echo "   ✅ $file"
    else
        echo "   ❌ $file MISSING"
    fi
done
echo ""

# 7. Try to run validation manually
echo "7️⃣ Testing validation manually..."
if [ "$EXCHANGE" = "kraken" ]; then
    cd /root/trading-bot-current
    venv/bin/python -c "
import sys
sys.path.insert(0, '.')
try:
    from src.venue_symbol_validator import validate_venue_symbols
    results = validate_venue_symbols(update_config=False)
    print(f'   ✅ Validation ran: {results[\"summary\"][\"valid\"]}/{results[\"summary\"][\"total\"]} valid')
except Exception as e:
    print(f'   ❌ Validation error: {e}')
    import traceback
    traceback.print_exc()
" 2>&1 | head -20
else
    echo "   ℹ️  Skipping (not using Kraken)"
fi
echo ""

# 8. Check bot logs for validation messages
echo "8️⃣ Checking recent bot logs for validation messages..."
journalctl -u tradingbot -n 200 --no-pager | grep -i "\[VALIDATION\]\|\[VENUE-MIGRATION\]\|\[EXCHANGE-HEALTH\]" | tail -10 || echo "   ⚠️  No validation messages found in recent logs"
echo ""

echo "=================================="
echo "VERIFICATION COMPLETE"
echo "=================================="
