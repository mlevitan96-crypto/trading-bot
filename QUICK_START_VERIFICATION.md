# Quick Start: Verify Expansive Analyzer

## Immediate Steps (After Deployment)

### 1. Deploy to Droplet

```bash
ssh root@YOUR_DROPLET_IP
cd /root/trading-bot-current
git pull origin main
sudo systemctl restart tradingbot
```

### 2. Quick Verification (30 seconds)

```bash
cd /root/trading-bot-current

# Run verification script
bash verify_expansive_analyzer.sh

# OR manually check:
python3 -c "from src.expansive_multi_dimensional_profitability_analyzer import ExpansiveMultiDimensionalProfitabilityAnalyzer; print('✅ OK')"
```

**Expected:** ✅ Module imports successfully

### 3. Manual Test Run (Optional - to see it work immediately)

```bash
# Run the analyzer manually (takes ~30-60 seconds)
python3 -c "
from src.expansive_multi_dimensional_profitability_analyzer import run_expansive_analysis
result = run_expansive_analysis()
print(f\"Status: {result.get('status')}\")
print(f\"Components: {len(result.get('components_completed', []))} completed\")
print(f\"Time: {result.get('execution_time_seconds', 0):.1f}s\")
"
```

**Expected Output:**
```
🔬 EXPANSIVE MULTI-DIMENSIONAL PROFITABILITY ANALYSIS
...
Status: success
Components: 16 completed
Time: 45.2s
```

## Automatic Verification (Next Nightly Run)

### When It Runs
- **Scheduled:** 10:30 UTC (3:30 AM Arizona time)
- **Also runs:** As part of `full_bot_cycle.py` nightly cycle (~07:00 UTC)

### What to Check Next Morning

```bash
# 1. Check if analysis ran
ls -lh reports/expansive_profitability_analysis.json

# 2. Check status
python3 -c "
from src.expansive_multi_dimensional_profitability_analyzer import ExpansiveMultiDimensionalProfitabilityAnalyzer
h = ExpansiveMultiDimensionalProfitabilityAnalyzer.check_health()
print(f\"Status: {h['status']}\")
print(f\"Last run: {h['details'].get('last_run', 'Never')}\")
"

# 3. Check bot logs for profitability analysis
tail -200 /var/log/tradingbot.log | grep -i "profitability\|expansive" | tail -10
```

**Expected:**
- ✅ Analysis file exists and is recent
- ✅ Status shows "healthy" 
- ✅ Logs show "Running EXPANSIVE Multi-Dimensional Analysis..."

## Success Indicators

✅ **All Good If:**
1. Module imports without error
2. Health check returns (even if "unknown" initially)
3. Analysis file created after first run
4. Status file shows "success" or "partial_success"
5. No errors in bot logs related to profitability analysis

## Troubleshooting

### ❌ Module import fails
- Check file exists: `ls -la src/expansive_multi_dimensional_profitability_analyzer.py`
- Check Python path: `python3 -c "import sys; print(sys.path)"`
- Re-pull code: `git pull origin main`

### ❌ Status always "unknown"
- Normal if analyzer hasn't run yet
- Wait for scheduled run OR run manually
- Check bot is running: `sudo systemctl status tradingbot`

### ❌ Components failing
- Check data availability: `ls -la logs/positions_futures.json`
- Check for trades: `python3 -c "from src.data_registry import DataRegistry; print(len(DataRegistry.get_closed_positions(hours=168)))" trades`
- Normal if you have < 5 trades per symbol (not enough data)

## What Happens Next

1. **Tonight (10:30 UTC):** Analyzer runs automatically
2. **Results:** Saved to `reports/expansive_profitability_analysis.json`
3. **Integration:** Insights feed into profitability trader persona
4. **Monitoring:** Healing operator checks health every 60s
5. **Dashboard:** Status visible in self-healing health indicators

## Summary

**Deploy → Verify Import → Wait for Nightly Run → Check Results**

The analyzer is **fully automated** - once deployed, it runs every night and integrates its insights automatically! 🚀
