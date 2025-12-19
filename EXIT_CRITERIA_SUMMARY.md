# Exit Criteria & Learning System - Quick Reference

## ✅ **Exit Criteria in Place**

### **1. Profit Targets (CHECKED FIRST - Priority Exit)**
- **+0.5% after 30 minutes** → Close (lock in early gains)
- **+1.0% after 60 minutes** → Close
- **+1.5% after 90 minutes** → Close  
- **+2.0% anytime** → Close (big winners)

**Location:** `src/phase92_profit_discipline.py` and `src/trailing_stop.py`

### **2. Trailing Stops (Dynamic Protection)**
- Tiered stops based on hold time (tight → wide)
- ATR-based distance adjustment (volatility-aware)

**Location:** `src/trailing_stop.py`

### **3. Time-Based Exits (Only if no profit target hit)**
- 2h if losing > 0.5%
- 4h if gain < 0.2%
- 8h if gain < 0.5%
- 12h max hold

**Location:** `src/phase92_profit_discipline.py`

### **4. Stop Losses**
- Default: -0.5% to -2.5%
- Dynamic adjustment based on MAE analysis

**Location:** Multiple systems

## ✅ **Learning Systems Active**

### **1. Nightly Exit Tuner** ⭐ PRIMARY LEARNING
**What it does:**
- Analyzes all exit events from `logs/exit_runtime_events.jsonl`
- Tracks profitability by exit type
- Calculates MFE (Max Favorable Excursion) capture rates
- **NEW:** Automatically adjusts profit targets if:
  - >20% of exits are early (missing >30% of potential profit)
  - Lower targets to capture profits before reversals
  - Raise targets if MFE is consistently much higher

**Runs:** Nightly at 3 AM Arizona time (10 AM UTC)

**Saves to:** `config/exit_policy.json` (per-symbol adjustments)

### **2. Exit Timing Intelligence**
- MFE/MAE analysis per symbol/pattern
- Learns optimal exit targets based on historical performance

**Saves to:** `feature_store/exit_timing_rules.json`

### **3. Complete Feedback Loop**
- Identifies "too early" vs "too late" exits
- Adjusts exit signal weights accordingly

## ✅ **What Was Just Added**

1. **MFE Tracking in Exit Events:**
   - Now logs `peak_price` and `mfe_roi` when positions close
   - Calculates `capture_rate_pct` (% of MFE we captured)
   - Enables learning from missed profit opportunities

2. **Enhanced Exit Learning:**
   - Detects early exits automatically (<70% MFE capture)
   - Lowers profit targets if missing too much profit
   - Tracks average capture rates per symbol

3. **Diagnostic Tool:**
   - `analyze_exit_performance.py` - Analyze recent exits
   - Identifies trades that exited early/late
   - Recommends adjustments

## 📊 **How to Verify Learning is Working**

### **On your droplet, run:**

```bash
# Check if exit tuner has run
tail -50 logs/exit_tuning_events.jsonl

# Check current exit policy
cat config/exit_policy.json

# Analyze exit performance
cd /root/trading-bot-current
venv/bin/python analyze_exit_performance.py
```

### **What to Look For:**

**✅ Good Signs:**
- Exit events show `mfe_roi` and `capture_rate_pct` fields
- Exit tuner logs show adjustments like "Lowered targets - missing avg X% profit"
- Average capture rate > 70% (capturing most of the profit)
- More `profit_target` exits than `time_stop` exits

**⚠️ Warning Signs:**
- Capture rate < 60% (exiting too early)
- Many `time_stop` exits (profit targets not hitting)
- Exit tuner not running or no adjustments being made

## 🎯 **Next Steps**

The system is now:
1. ✅ Tracking MFE (maximum profit reached) for every trade
2. ✅ Calculating capture rates (% of MFE we captured)
3. ✅ Learning from early exits automatically
4. ✅ Adjusting profit targets based on missed profit opportunities

**After deployment, the exit tuner will:**
- Analyze all exits nightly
- Identify if we're exiting too early (missing profit)
- Automatically lower profit targets to capture profits before reversals
- Improve over time based on actual trade outcomes

**You can monitor this in:**
- Dashboard executive summary (exit gates analysis)
- `logs/exit_tuning_events.jsonl` (tuning decisions)
- `analyze_exit_performance.py` (detailed analysis)
