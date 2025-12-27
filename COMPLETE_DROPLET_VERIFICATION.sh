#!/bin/bash
# Complete Droplet Verification Script
# Runs all verification checks on the droplet

set -e

echo "======================================================================"
echo "COMPLETE DROPLET VERIFICATION"
echo "======================================================================"
echo ""

# Colors for output
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Navigate to project directory
cd /root/trading-bot-current || cd /root/trading-bot-B || exit 1

echo "Current directory: $(pwd)"
echo "Git status:"
git status --short
echo ""

# 1. Pull latest code
echo "======================================================================"
echo "STEP 1: Pulling latest code from GitHub"
echo "======================================================================"
git pull origin main
echo ""

# 2. Check virtual environment
echo "======================================================================"
echo "STEP 2: Checking virtual environment"
echo "======================================================================"
if [ -d "venv" ]; then
    echo "Virtual environment found"
    source venv/bin/activate
else
    echo "WARNING: Virtual environment not found"
fi
echo ""

# 3. Install/update dependencies
echo "======================================================================"
echo "STEP 3: Installing/updating dependencies"
echo "======================================================================"
pip install -q -r requirements.txt
echo "Dependencies installed"
echo ""

# 4. Run code verification
echo "======================================================================"
echo "STEP 4: Running code pattern verification"
echo "======================================================================"
python3 verify_integration_code.py
CODE_VERIFY=$?
echo ""

# 5. Run complete verification
echo "======================================================================"
echo "STEP 5: Running complete systems verification"
echo "======================================================================"
if [ -f "run_complete_verification.py" ]; then
    python3 run_complete_verification.py
    COMPLETE_VERIFY=$?
else
    echo "WARNING: run_complete_verification.py not found, skipping"
    COMPLETE_VERIFY=0
fi
echo ""

# 6. Check service status
echo "======================================================================"
echo "STEP 6: Checking service status"
echo "======================================================================"
if systemctl is-active --quiet tradingbot; then
    echo -e "${GREEN}Service tradingbot is running${NC}"
    systemctl status tradingbot --no-pager | head -10
elif systemctl is-active --quiet trading-bot; then
    echo -e "${GREEN}Service trading-bot is running${NC}"
    systemctl status trading-bot --no-pager | head -10
else
    echo -e "${RED}WARNING: Trading bot service not running${NC}"
fi
echo ""

# 7. Check recent logs for autonomous brain components
echo "======================================================================"
echo "STEP 7: Checking logs for autonomous brain components"
echo "======================================================================"
if systemctl is-active --quiet tradingbot || systemctl is-active --quiet trading-bot; then
    SERVICE_NAME=$(systemctl is-active --quiet tradingbot && echo "tradingbot" || echo "trading-bot")
    echo "Checking logs for autonomous brain startup messages..."
    journalctl -u $SERVICE_NAME --no-pager -n 200 | grep -E "AUTONOMOUS-BRAIN|SHADOW|POLICY-TUNER|DRIFT|REGIME" | tail -20 || echo "No autonomous brain messages found in recent logs"
else
    echo "Service not running, skipping log check"
fi
echo ""

# 8. Check file structure
echo "======================================================================"
echo "STEP 8: Verifying file structure"
echo "======================================================================"
REQUIRED_FILES=(
    "src/regime_classifier.py"
    "src/shadow_execution_engine.py"
    "src/policy_tuner.py"
    "src/feature_drift_detector.py"
    "src/adaptive_signal_optimizer.py"
)

ALL_FILES_EXIST=true
for file in "${REQUIRED_FILES[@]}"; do
    if [ -f "$file" ]; then
        echo -e "${GREEN}OK: $file${NC}"
    else
        echo -e "${RED}MISSING: $file${NC}"
        ALL_FILES_EXIST=false
    fi
done
echo ""

# Summary
echo "======================================================================"
echo "VERIFICATION SUMMARY"
echo "======================================================================"

if [ $CODE_VERIFY -eq 0 ] && [ $COMPLETE_VERIFY -eq 0 ] && [ "$ALL_FILES_EXIST" = true ]; then
    echo -e "${GREEN}SUCCESS: All verifications passed!${NC}"
    exit 0
else
    echo -e "${YELLOW}WARNING: Some verifications failed - review above${NC}"
    exit 1
fi

