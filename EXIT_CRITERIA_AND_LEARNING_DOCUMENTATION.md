# Exit Criteria & Learning System Documentation

## Current Exit Criteria

### 1. **Profit Targets (Priority Exit - Runs First)**
Located in: `src/phase92_profit_discipline.py` and `src/trailing_stop.py`

**Tiered Profit Targets:**
- **+0.5% after 30 minutes** → Close position (lock in early gains)
- **+1.0% after 60 minutes** → Close position
- **+1.5% after 90 minutes** → Close position
- **+2.0% anytime** → Close position (big winners)

**Execution Order:** These are checked FIRST before any time-based exits, ensuring profitable trades exit early.

### 2. **Trailing Stops (Dynamic Protection)**
Located in: `src/trailing_stop.py`

**Tiered Trailing Stops (based on hold time):**
- **< 30 min:** Tight trailing stop (prevents immediate reversals)
- **30-120 min:** Medium trailing stop
- **120-240 min:** Wide trailing stop
- **> 240 min:** Overnight protection (wider stop)

**ATR-Based:** Trailing stop distance adjusts based on market volatility (ATR multiplier).

### 3. **Time-Based Exits (Only if no profit target hit)**
Located in: `src/phase92_profit_discipline.py`

**Tiered Time Exits:**
- **2 hours:** Exit if losing > 0.5%
- **4 hours:** Exit if gain < 0.2% (stagnant position)
- **8 hours:** Exit if gain < 0.5% (weak position)
- **12 hours:** Maximum hold time (force exit)

**Note:** These only trigger if NO profit target was reached.

### 4. **Stop Losses**
Located in: `src/exit_learning_and_enforcement.py` and `src/position_timing_intelligence.py`

- **Default:** -0.5% to -2.5% depending on system
- **Dynamic:** Adjusts based on MAE (Max Adverse Excursion) analysis
- **Regime-aware:** Wider stops in volatile markets

### 5. **Multi-Timeframe Intelligence Exits**
Located in: `src/position_timing_intelligence.py`

- **TAKE_PROFIT:** Profitable + alignment weakening (lock in gains)
- **FORCE_EXIT:** Stop loss threshold hit
- **HOLD_EXTENDED:** Profitable + strong alignment + momentum continuing
- **EXIT_NOW:** Alignment degraded OR exceeded optimal time

## Exit Learning Systems

### 1. **Nightly Exit Tuner** (Primary Learning System)
Located in: `src/exit_learning_and_enforcement.py::ExitTuner`

**What It Does:**
- Analyzes `logs/exit_runtime_events.jsonl` (all exit events)
- Tracks profitability by exit type:
  - Profit target exits (profit_target_*)
  - Trailing stop exits
  - Time stops
  - Stop losses
- Calculates:
  - Hit rates for each exit type
  - Profitability rate (% of exits that were profitable)
  - MFE/MAE averages (max favorable/adverse excursion)
  - Average ATR (volatility)

**Learning Adjustments:**
1. **Profit Targets:**
   - If TP1 hit frequently but TP2 rare → Lower TP2 threshold
   - If many time_stops before TP1 → Raise TP1 threshold (take profit earlier)
   - Monitors: If profit targets have high hit rate but low profitability → May be exiting too early

2. **Trailing Stops:**
   - Widen in high volatility (ATR > 0.7%)
   - Tighten in choppy markets (ATR < 0.3%)

3. **Stop Losses:**
   - If stop rate > 25% and MAE large → Loosen stop (reduce false stops)
   - If stop rate < 10% and MAE small → Tighten stop (protect downside)

4. **Minimum Hold Times:**
   - If time_stops > 20% of exits → Increase min hold (positions need more time)

**Saves to:** `config/exit_policy.json` (per-symbol overrides)

**Scheduled:** Nightly at ~3 AM Arizona time (10 AM UTC)

### 2. **Exit Timing Intelligence** (MFE/MAE Analysis)
Located in: `src/exit_timing_intelligence.py`

**What It Does:**
- Analyzes historical trades to calculate:
  - **MFE (Max Favorable Excursion):** Best price reached during trade
  - **MAE (Max Adverse Excursion):** Worst drawdown during trade
  - **Capture Rate:** % of MFE we actually captured (exit price vs peak)
- Learns optimal exit targets per:
  - Symbol
  - Direction (LONG/SHORT)
  - OFI bucket (signal strength)
  - Pattern

**Key Insight:** Optimal exits typically capture ~70% of MFE for profitable patterns.

**Saves to:** `feature_store/exit_timing_rules.json`

### 3. **Complete Feedback Loop** (Exit Timing Quality)
Located in: `src/complete_feedback_loop.py`

**What It Does:**
- Analyzes if exits were:
  - **Too Early:** Quick losses that might have recovered
  - **Too Late:** Held through reversals, gave back profits
  - **Good:** Profit locked on alignment drop
- Updates exit signal weights based on timing quality

**Adjustments:**
- If exiting too early frequently → Increase hold_duration weight
- If exiting too late frequently → Increase trailing_stop and momentum_reversal weights

### 4. **Futures Exit Learning** (Ladder Exit Optimization)
Located in: `src/futures_exit_learning.py`

**What It Does:**
- Optimizes ladder exit tier allocations (25%, 25%, 50% splits)
- Scores exits by reason:
  - **Positive:** RR hits, signal reversals (profitable)
  - **Negative:** Protective mode, trailing stops (defensive)
- Promotes better tier allocations when sufficient data (≥6 events)

**Saves to:** `configs/ladder_exit_policies.json`

## Current Status Check

To verify exit learning is working:

```bash
# Check if exit tuner has run
cat logs/exit_tuning_events.jsonl | tail -20

# Check current exit policy
cat config/exit_policy.json

# Check exit timing rules
cat feature_store/exit_timing_rules.json

# Check recent exit events
tail -50 logs/exit_runtime_events.jsonl
```

## What You Should See

### ✅ **Good Signs:**
- Exit gates show `profit_target_0.5pct`, `profit_target_1.0pct` exits
- Executive summary shows profitable exit rates
- Exit tuner logs show adjustments: "Lowered TP2", "Raised TP1", etc.
- MFE analysis shows capture rates improving over time

### ⚠️ **Warning Signs:**
- Mostly `time_stop` exits (profit targets not hitting)
- Low profitability rate despite profit targets
- Executive summary shows "exited too early" or "exited too late" frequently
- No exit tuner activity in logs

## How to Verify Learning is Active

The exit tuner should run nightly. Check if it's scheduled:

```bash
# Check nightly orchestration
grep -r "ExitTuner\|exit.*tuner\|run_nightly_tuning" src/

# Check scheduler registration
grep -r "register.*exit\|nightly.*exit" src/
```

## Recommendations for Better Profit Capture

If you're seeing trades that could have exited earlier with more profit:

1. **Lower Profit Targets Temporarily:**
   - Change TP1 from 0.5% to 0.3% (after 20 min instead of 30 min)
   - More aggressive early profit-taking

2. **Enable Exit Timing Intelligence:**
   - Use MFE analysis to set dynamic targets per symbol
   - Let it learn optimal capture rates

3. **Review Hold Time Policy:**
   - Check `feature_store/hold_time_policy.json`
   - Reduce minimum hold if positions are reversing before targets

4. **Monitor Exit Events:**
   - Check `logs/exit_runtime_events.jsonl` for exit reasons
   - Identify which symbols/strategies exit poorly

## Next Steps

I can:
1. **Create a diagnostic script** to analyze recent exits and identify missed profit opportunities
2. **Enhance exit learning** to be more aggressive about early profit-taking
3. **Add real-time exit recommendations** based on MFE/MAE for open positions
4. **Optimize profit targets** based on your specific concerns

Would you like me to create a comprehensive exit analysis report showing:
- Which trades exited early vs late
- Average MFE capture rates
- Recommended adjustments to profit targets
- Exit learning effectiveness
