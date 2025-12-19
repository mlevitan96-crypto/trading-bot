#!/bin/bash
# Quick verification script for Expansive Profitability Analyzer

echo "🔍 Verifying Expansive Profitability Analyzer..."
echo ""

echo "1. Checking module import..."
python3 -c "from src.expansive_multi_dimensional_profitability_analyzer import ExpansiveMultiDimensionalProfitabilityAnalyzer; print('✅ Module imports successfully')" 2>&1 || echo "❌ Import failed"

echo ""
echo "2. Checking health status..."
python3 -c "
from src.expansive_multi_dimensional_profitability_analyzer import ExpansiveMultiDimensionalProfitabilityAnalyzer
h = ExpansiveMultiDimensionalProfitabilityAnalyzer.check_health()
print(f'   Status: {h[\"status\"]}')
if h.get('details'):
    print(f'   Last run: {h[\"details\"].get(\"last_run\", \"Never\")}')
    print(f'   Components: {h[\"details\"].get(\"components_completed\", 0)} completed')
" 2>&1

echo ""
echo "3. Checking status file..."
if [ -f "feature_store/expansive_analyzer_status.json" ]; then
    echo "   ✅ Status file exists"
    python3 -m json.tool feature_store/expansive_analyzer_status.json 2>/dev/null | head -10 || echo "   ⚠️  Could not parse status file"
else
    echo "   ⚠️  Status file not found (will be created on first run)"
fi

echo ""
echo "4. Checking analysis output..."
if [ -f "reports/expansive_profitability_analysis.json" ]; then
    echo "   ✅ Analysis file exists"
    python3 -c "
import json
try:
    with open('reports/expansive_profitability_analysis.json') as f:
        data = json.load(f)
    print(f'   Status: {data.get(\"status\")}')
    print(f'   Components: {len(data.get(\"components_completed\", []))} completed')
    print(f'   Insights: {len(data.get(\"actionable_insights\", []))} actionable insights')
except Exception as e:
    print(f'   ⚠️  Error reading file: {e}')
" 2>&1
else
    echo "   ⚠️  Analysis file not found (will be created on first run)"
fi

echo ""
echo "5. Checking integration..."
python3 -c "
try:
    from src.healing_operator import get_healing_operator
    print('   ✅ Healing operator integration OK')
except Exception as e:
    print(f'   ⚠️  Healing operator check failed: {e}')

try:
    from src.learning_health_monitor import LearningHealthMonitor
    monitor = LearningHealthMonitor()
    check = monitor.check_expansive_profitability_analyzer()
    status = check.get('status', 'N/A')
    print(f'   ✅ Learning health monitor integration OK (status: {status})')
except Exception as e:
    print(f'   ⚠️  Learning health monitor check failed: {e}')
" 2>&1

echo ""
echo "6. Checking scheduling..."
if grep -q "run_profitability_analysis\|profitability.*persona" src/run.py src/full_bot_cycle.py src/scheduler_with_analysis.py 2>/dev/null; then
    echo "   ✅ Scheduled in nightly cycle"
    grep -h "run_profitability\|profitability.*persona" src/run.py src/full_bot_cycle.py 2>/dev/null | head -2
else
    echo "   ⚠️  Not found in scheduler files"
fi

echo ""
echo "✅ Verification complete!"
