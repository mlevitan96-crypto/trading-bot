# Deployment Safety Checks Integration

## Overview

The deployment safety checks validate system readiness before switching A/B slots. This prevents deploying broken configurations.

## Integration with deploy.sh

To integrate safety checks into your `/root/trading-bot-tools/deploy.sh` script, add this before the slot switch:

```bash
# Before slot switch, run safety checks
echo "[deploy] Running pre-deployment safety checks..."
cd "$INACTIVE"

# Run safety checks using venv Python
if "$INACTIVE/venv/bin/python" "$INACTIVE/scripts/pre_deployment_checks.py" --slot "$INACTIVE"; then
    echo "[deploy] ✅ Safety checks passed"
else
    echo "[deploy] ❌ Safety checks FAILED - aborting deployment"
    echo "[deploy] Fix errors and try again"
    exit 1
fi

# Continue with slot switch...
```

## What Gets Checked

1. **Environment Variables**
   - `EXCHANGE` must be set (kraken or blofin)
   - If Kraken: `KRAKEN_FUTURES_API_KEY`, `KRAKEN_FUTURES_API_SECRET`, `KRAKEN_FUTURES_TESTNET`

2. **Exchange Connectivity**
   - Tests mark price fetch
   - Tests orderbook availability
   - Tests OHLCV data access
   - Handles testnet limitations gracefully

3. **Symbol Validation** (Kraken only)
   - Validates symbols exist on exchange
   - Checks orderbook liquidity
   - Warnings only (doesn't block deployment)

## Manual Check

You can run checks manually:

```bash
# Check current slot
cd /root/trading-bot-current
/root/trading-bot-current/venv/bin/python scripts/pre_deployment_checks.py

# Check specific slot
/root/trading-bot-B/venv/bin/python /root/trading-bot-B/scripts/pre_deployment_checks.py --slot /root/trading-bot-B
```

## Exit Codes

- `0` = All checks passed, safe to deploy
- `1` = Checks failed, deployment should be blocked

## Notes

- Checks are non-blocking for symbol validation (warnings only)
- Connectivity failures will block deployment
- Missing API keys will block deployment
