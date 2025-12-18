# Testing Validation on Droplet

Since validation should run but isn't showing in logs, let's debug:

## Step 1: Check Full Startup Logs

```bash
# Get the most recent startup logs (look for initialization)
journalctl -u tradingbot -n 500 --no-pager | grep -A 10 -B 10 "heavy\|initialization\|VALIDATION" | tail -50
```

## Step 2: Test Import Manually

```bash
cd /root/trading-bot-current
source venv/bin/activate

# Test if validation module imports
python3 << 'EOF'
import os
os.chdir('/root/trading-bot-current')
try:
    from src.venue_symbol_validator import validate_venue_symbols
    print("✅ Import successful")
except Exception as e:
    print(f"❌ Import failed: {e}")
    import traceback
    traceback.print_exc()
EOF
```

## Step 3: Test Validation Directly

```bash
cd /root/trading-bot-current
source venv/bin/activate

python3 << 'EOF'
import os
os.chdir('/root/trading-bot-current')
os.environ['EXCHANGE'] = 'kraken'

try:
    from src.venue_symbol_validator import validate_venue_symbols
    print("Running validation...")
    results = validate_venue_symbols(update_config=False)
    print(f"✅ Validation complete: {results['summary']}")
except Exception as e:
    print(f"❌ Validation failed: {e}")
    import traceback
    traceback.print_exc()
EOF
```

## Step 4: Check for Silent Errors

The code has a try/except that might be catching errors silently. Check for any validation error messages:

```bash
journalctl -u tradingbot -n 500 --no-pager | grep -i "validation.*error\|symbol validation error"
```
