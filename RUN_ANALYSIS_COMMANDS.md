# Commands to Run Comprehensive Analysis on Droplet

**Server:** 159.65.168.230  
**Base Directory:** `/opt/trading-bot/`  
**Analysis Script:** `comprehensive_profitability_analysis.py`

---

## Step-by-Step Commands

### 1. Connect to Droplet
```bash
ssh kraken
```

### 2. Navigate to Correct Directory
```bash
cd /opt/trading-bot
```

### 3. Verify You're in the Right Place
```bash
pwd
# Should output: /opt/trading-bot

ls -la
# Should show: src/, logs/, data/, feature_store/, configs/, etc.
```

### 4. Check Data Files Exist
```bash
# Check trade data
ls -lh logs/positions_futures.json

# Check signals
ls -lh logs/signals.jsonl

# Check signal outcomes
ls -lh logs/signal_outcomes.jsonl

# Check enriched decisions
ls -lh logs/enriched_decisions.jsonl

# Check database
ls -lh data/trading_system.db
```

### 5. Run Comprehensive Analysis
```bash
python comprehensive_profitability_analysis.py
```

### 6. Alternative: Run Existing Analysis Tools
```bash
# Option 1: Comprehensive trade analysis
python src/comprehensive_trade_analysis.py

# Option 2: Deep profitability analyzer
python src/deep_profitability_analyzer.py

# Option 3: Generate full analysis report
python generate_full_analysis.py
```

### 7. Check Results
```bash
# Results will be saved to reports/
ls -lh reports/

# View latest analysis
ls -lt reports/ | head -5
```

---

## Quick One-Liner (All Steps Combined)

```bash
ssh kraken "cd /opt/trading-bot && python comprehensive_profitability_analysis.py"
```

---

## Verify Data Collection Status

Before running analysis, check if data is being collected:

```bash
# On droplet
cd /opt/trading-bot

# Check signal outcomes count
wc -l logs/signal_outcomes.jsonl

# Check enriched decisions count
wc -l logs/enriched_decisions.jsonl

# Check signals count
wc -l logs/signals.jsonl

# Check closed trades
python -c "import json; data=json.load(open('logs/positions_futures.json')); print(f'Closed trades: {len(data.get(\"closed_positions\", []))}'); print(f'Open positions: {len(data.get(\"open_positions\", []))}')"
```

---

## If Analysis Script Not Found

If the script isn't on the droplet yet, you need to:

1. **Pull latest code from Git:**
```bash
cd /opt/trading-bot
git pull origin main
```

2. **Or copy the script manually:**
```bash
# From your local machine, copy the script
scp comprehensive_profitability_analysis.py root@159.65.168.230:/opt/trading-bot/
```

---

## Expected Output

The analysis will:
1. Load all data sources (trades, signals, blocked, missed opportunities)
2. Analyze signal components and weights
3. Analyze timing, volume, patterns
4. Generate recommendations
5. Save results to `reports/comprehensive_profitability_analysis_[timestamp].json`

---

## Troubleshooting

### If "command not found" for python:
```bash
# Try python3 instead
python3 comprehensive_profitability_analysis.py
```

### If script has import errors:
```bash
# Make sure you're in the right directory
cd /opt/trading-bot

# Check Python path
python -c "import sys; print(sys.path)"
```

### If no data found:
```bash
# Check if bot is running and collecting data
ps aux | grep python | grep run.py

# Check recent log entries
tail -50 logs/bot_out.log
```

---

**Remember:** All data is on the droplet at `/opt/trading-bot/`. You must run analysis there to access the actual trade data.
