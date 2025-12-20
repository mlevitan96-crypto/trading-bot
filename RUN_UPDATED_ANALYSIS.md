# Run Updated Analysis - Commands

The analysis script has been updated to match signals to trades. Run this on the droplet:

## Commands

```bash
# 1. Connect to droplet
ssh root@159.65.168.230

# 2. Navigate to correct directory
cd /root/trading-bot-current

# 3. Pull latest code (with updated analysis script)
git pull origin main

# 4. Run updated comprehensive analysis
python3 comprehensive_profitability_analysis.py
```

## What's New

The updated script now:
- Matches signals from `logs/signals.jsonl` to trades by symbol + timestamp
- Extracts signal components (OFI, ensemble, liquidation, funding, etc.) from signals
- Analyzes signal component performance
- Analyzes signal combinations
- Provides signal weight optimization recommendations

## Expected Output

You should now see:
- Signal Component Performance analysis
- Signal Combination analysis
- Signal Weight Optimization recommendations
- Winner vs Loser signal differences

## If You See Errors

If there are import or syntax errors:
```bash
# Check Python version
python3 --version

# Check if in correct directory
pwd
ls -la comprehensive_profitability_analysis.py

# Try with explicit path
python3 /root/trading-bot-current/comprehensive_profitability_analysis.py
```
